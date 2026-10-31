# v24 Tool/Plugin ABI W4c execution record

Date: 2026-10-31 (+08:00). Scope: W4c lifecycle/replay/Node extension in [W4 plan](../plans/v24-tool-plugin-abi-w4-dispatcher-worker-wiring-2026-10-31.md), corresponding to design §10 M4. This record completes M4 but does not retroactively complete W4b's pending M3 timing/cutoff.

## Result

The required 32 serial commands ran in the specified order and all exited 0. Commands 30–31 are the W4c gates; their markers are exactly:

```text
[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true
[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node
```

Rows 14–24 are the 11 frozen closeout commands. Closeout remains **11/11**; s13 is not a twelfth closeout item. No exit 2, `[SKIP]` or missing marker occurred in the 32 commands. **M4 is complete.** W4b's **M3 implementation remains timing/cutoff pending**; `tool.search_budget_timing_m3_pending` stays `m3_pending` and no 12-second wall-clock gate exists.

## Candidate and provenance

- Checkout: `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `80dc0c45f5f7618fecb1a97f09cbe67b2caef109`.
- Candidate paths: `v24/s13/test_lifecycle.py`, `v24/s13/test_node.py`, this record, the W4 plan, matrix/ledger and `v24/s13/README.md`. No production host/SQL/design/vector change in W4c.
- Environment: uv `0.8.24 (252f88733 2025-10-07)`; Python `3.12.11`; Node `v24.13.1`; local PostgreSQL test database.
- Evidence directory: `/tmp/w4c-20261031T044427/`. It contains `provenance.txt`, `git-status-porcelain.txt`, `source-sha256.txt`, redacted `credential-scan.txt`, `01.log`–`32.log`, `results.tsv`, `merged.log`, `scope-audit.tsv`, and six `scope-*.log` files.
- `results.tsv` SHA-256: `4796e9c43b34b4d4a0eb3af8047149f727f9af0f7272283d93eb27c95fe8b839`.
- `merged.log` SHA-256: `82a139de05ccde3a91dc6aadba338265e070cb243e1231621a7a6edba54b6742`.
- `scope-audit.tsv` SHA-256: `53e1b3394c7eae2eb96383d0475de964e40717502e40252b95bd7ebad30d87e7`.
- `source-sha256.txt` SHA-256: `064d481156744464e3b6d61d477f60968dc254e41ed02d23b82ee1fd53683a11`; `credential-scan.txt` SHA-256: `e79c6ebb624949cb04f0423b962eb18a92953f2aaff146e92fef69e5d4bb0d43`.
- `provenance.txt` SHA-256: `018f4c3d8e996c0e53f0784715da39109206ff4c2b09975c47d559ad167eb60f`; `git-status-porcelain.txt` is generated after the sweep with the full `git status --porcelain=v2` and version/identity snapshot.

Every command used exactly this prefix:

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

The runner redirected each producer to its own log, then immediately captured `rc=$?`; no tail or pipeline supplied the exit status. The TSV stores the expanded command, UTC start time, exit code, actual last line and SHA-256 of the log. A nonzero exit or missing required marker would have stopped the run before publication.

## Implementation and coverage

| Case | Coverage | Result |
|---|---|---|
| G12-A | Python read + Node list/search, two installs, three-key start, real subprocess, full off/dispose/release/scope-close lifecycle; list/search share one install | Passed |
| G12-B | Same model batch with three tools, barrier, exactly one continuation (2 model effects / 1 continuation), list/search pins share install | Passed |
| G12-C | invalid args (`offset=0`) → `invalid_tool_arguments`, zero spawn (sentinel + spawn log) | Passed |
| G12-D | invalid output (`bad_value`, `bad_relation`) and renderer exception → failure, not unknown | Passed |
| G12-E | plugin timeout → unknown `timeout`, run `blocked_unknown`, one model request | Passed |
| G12-F | artifact/adapter/descriptor tamper → failure, zero spawn | Passed |
| G12-G | crash after tool `dispatch_finished`, rebuild journal/worker, `_reconcile` resubmits journal outcome without second spawn | Passed |
| G12-H | Node search with 19999 ms lease and 15000 ms tool timeout → `lease_insufficient`, zero spawn | Passed |
| G12-L | success and known-error legacy echo provider requests and tool messages match B0 golden bytes exactly | Passed |

Replay evidence from G12-G: the tool handler is replaced with a raising function and the renderer digest is changed in test memory only; the rebuilt worker calls `_reconcile`, whose settlement payload contains `reconciled=true`. The assertions are `replay_source=journal tool_message`, `rerender=false`, `second_spawn=false`, `journal_event_types_unchanged=true`, and no second settlement for the effect. The three replay-related `results_v2` cases were executed while their `status` fields stayed `m4_pending`.

Node missing was checked by replacing `node_path()` with `None`: `test_node.py --node` prints `[SKIP] W4 node contract; node_missing` and exits 2; it is not a pass. The actual 32-command run had Node `v24.13.1` present and both W4c gates green.

## Scope and compatibility audits

All six checks are pinned to `c8c4bd0`; no bare `git diff` decided a result.

| Check | Exit | Actual result |
|---|---:|---|
| frozen modules, frozen s13 tests and no untracked frozen dirs | 0 | `[scope] passed frozen_modules_and_untracked` |
| vectors except design metadata | 0 | `[scope] passed vectors_except_design_conformance` |
| design restore after SHA substitution | 0 | `[scope] passed design_conformance_restore old=269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0 new=ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b` |
| registry exact D12 patch | 0 | `[scope] passed registry_exact_patch plus=5 minus=1` |
| host import purity | 0 | `[scope] passed host_import_purity` |
| SQL zero diff | 0 | `[scope] passed sql_zero_diff` |

`test_wiring.py` also ran its built-in six-check audit during command 02. W4c does not change design, `design_conformance.json`, `test_contracts.py`, production host code or vectors; design SHA remains `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b`.

## Final 32-command serial run

All commands below are prefixed by the exact `$ENVPFX` expansion shown above. Start times are UTC.

| # | Started (UTC) | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T04:44:27Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-10-31T04:44:56Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-10-31T04:45:00Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T04:45:00Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T04:45:01Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T04:45:02Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T04:45:02Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-10-31T04:45:03Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-10-31T04:45:03Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-10-31T04:45:04Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-10-31T04:45:06Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-10-31T04:45:08Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-10-31T04:45:10Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-10-31T04:45:12Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-31T04:45:12Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-31T04:45:14Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-31T04:45:16Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-31T04:45:18Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-31T04:45:20Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-31T04:45:29Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `8375d44931099d10ecf896627013eb6446fb7f34f3d160879fdc5135ce96d180` |
| 21 | 2026-10-31T04:45:34Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `58872902e39a0384d5efa6eb134f4a5baa87182c202db6b60036ba3a2f0427f2` |
| 22 | 2026-10-31T04:45:38Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `ad06c2d0e9276ac0c7ea491da71e0fbfb4e34a0a023926464c70ad5dc5bc5069` |
| 23 | 2026-10-31T04:45:42Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `3027f20597521ee5b7fb314ff056ade9104e6f8184d262a02d74871f5b3a5b7c` |
| 24 | 2026-10-31T04:45:44Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `e0b3adcec7e5107938e0d5ebabb64e61da17e603f4fa29c8591047089de73cdd` |
| 25 | 2026-10-31T04:45:51Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-10-31T04:45:54Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-10-31T04:45:57Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-10-31T04:45:59Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `530a33d06f986f8cf0e9142af0598faad8d2a0b34a3355e30301985b7eb6b134` |
| 29 | 2026-10-31T04:46:01Z | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=74; read=16; list=7; search=24; pagination_converged=true; page_contracts_imported=3` | `af5e1f72bd02838fbda62a7fb28d045477ead46bfd4fa332882d9e3be2d3dc88` |
| 30 | 2026-10-31T04:46:10Z | `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true` | `e0e76e0b042bf67dbc7b3db3586940bf59f06eb98cd2b065ebbbbf99daf476a4` |
| 31 | 2026-10-31T04:46:21Z | `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |
| 32 | 2026-10-31T04:46:23Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | `<empty>` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Deviations, limits and unresolved assumptions

- **D-ABI-W4-9** (ledger) records the execute-only `m4_pending` statuses, the test-only renderer-digest fault injection, and Node-missing SKIP semantics.
- **M4 complete; M3 timing still pending:** W4c's lifecycle gate does not prove the 12-second plugin scan budget, cutoff page-fill timing or cross-platform wall-clock behavior. W4b's M3 implementation completion statement remains `timing/cutoff pending`; W4c does not upgrade it.
- **Replay boundary:** the replay test uses the journal-only `_reconcile` path after a tool `dispatch_finished`; it proves no rerender/second spawn for that window. It does not cover every crash window, mixed-batch replay with multiple pending tools, or a real process restart.
- **Node missing:** the SKIP simulation is a unit-level replacement of `node_path()`, not a full missing-Node environment. The final evidence run used Node `v24.13.1`.
- **No network/provider:** all runs use local PostgreSQL, real local Python/Node plugin subprocesses and the existing `ScriptedTransport`; no real provider socket is opened.
- **No vector/status/design changes:** W4c only adds the two gate files and documentation; closeout remains 11/11 and s13 remains extension evidence.

## Publication

This record, the README, matrix, ledger and W4c plan Result are documentation updates after the measured sweep. Publication uses the W4c file list plus the plan/README/matrix/ledger/record paths, normal hooks (no `--no-verify`), commit message `v24: add v2 lifecycle, replay and Node extension gates`, and non-force `git push origin main`. It excludes the unrelated `.ctx-export-*`, `.token-probe*`, `ctx_export_check*` and `v20/experiments/ce_native_d5/` files. The resulting commit/push outcome is reported after execution; this file does not embed its own commit hash.
