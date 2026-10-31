# v24 Tool/Plugin ABI W7 lifecycle and recovery execution record

Date: 2026-11-01 (+08:00; the evidence directory uses the UTC stamp `2026-10-31T20:00:02Z`). Scope: work item W7-7 of the [W7 plan](../plans/v24-tool-plugin-abi-w7-lifecycle-recovery-2026-11-01.md) — documentation, the 32-command serial sweep, and the seven scope audits for the W7 recovery-closure stage. This record reports only this run's measurements. It does not embed its own SHA or a future commit SHA.

## Result

The required 32 commands ran serially in the plan's order and all exited 0. The first command started at `2026-10-31T20:01:44Z` and the last at `2026-10-31T20:04:16Z`; these are command start times, not an end-to-end duration. Commands 1–31 ended in their exact command-specific `[passed]` lines. Command 32 was the pinned SQL diff: exit 0, a zero-byte log, an empty last-line field, and no `[passed]`. No exit 2, `[SKIP]` or missing required marker occurred.

```text
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
```

W7 is a post-M5 recovery-closure stage, not a new design §10 milestone. M4 remains complete under C.11 and M5 remains complete; W7 does not reopen either. `cases=30` is function-level counting: the 14 W4c sub-scenarios (A1+B1+C1+D3+E1+F3+G1+H1+L2) plus one case per R01–R16. Rows 14–24 remain the eleven frozen closeout commands: **closeout stays 11/11**; s13 is extension evidence, not a twelfth item. Seven scope audits passed the precheck, the post-documentation final run, and the post-edit confirmation run.

## Candidate and provenance

- Checkout `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `a41ce220b60af95070d93ce1571d09d70299a5cf` (`v24: close out Tool/Plugin ABI M5`), with `origin/main` at the same commit.
- Environment: uv `0.8.24 (252f88733 2025-10-07)`, Python `3.12.11` at `/Users/wxl/Projects/pg-agent/.venv/bin/python3`, Node `v24.13.1` at `/Users/wxl/.nvm/versions/node/v24.13.1/bin/node`, PostgreSQL `17.11 (Homebrew)`, Darwin `25.6.0` / macOS `26.6.2 (25G83)` / arm64; real local plugin subprocesses and the local database.
- Exactly eight candidate paths: `v24/s13/test_lifecycle.py`, `v24/s13/w4_stub_plugin.py`, `v24/s13/w7_recover.py`, `v24/s13/README.md`, `docs/reviews/v24-conformance-matrix-2026-10-23.md`, `docs/reviews/v24-deviation-ledger-2026-10-23.md`, this execution record, and `docs/plans/v24-tool-plugin-abi-w7-lifecycle-recovery-2026-11-01.md`.
- Evidence directory `/tmp/v24-abi-w7-20261031T200002Z/`. It contains `provenance.txt`, the initial porcelain status, a precheck and a final `source-sha256` snapshot, the W7-0 untracked baseline, `01.log`–`32.log`, `results.tsv`, `merged.log`, `scope-precheck/`, `scope-final/`, `scope-confirmation/`, `credential-scan.txt`, and `publication-receipt.txt`.
- The W7-0 untracked baseline has 35 `sha256  path` entries. It was captured with ignored files included (`v20/experiments/ce_native_d5/__pycache__/*.pyc`), so audit 7 compares inside that same universe: non-ignored untracked paths plus still-present baseline paths. That keeps unchanged ignored files out of the `removed` set without scanning `.venv` or other large ignored trees.
- The W7-7 brief names `v24/s13/vectors/b0_golden/golden.json` as a source-digest input. That path does not exist anywhere in this checkout (`git ls-files` and a repository-wide grep return no hit). The B0 goldens actually used by the lifecycle cases are the four files under `v24/b0/golden/`; the two consumed by R14 are listed below. This is a documentation-input correction, not a gate deviation.

The current code and artifact digests are:

| Source / artifact | SHA-256 |
|---|---|
| `v24/s13/test_lifecycle.py` | `4b11c4f4690b31bcfa4be912e38b879a754cba1c5a01a8080ae618302365e47f` |
| `v24/s13/w4_stub_plugin.py` | `916ca5b2e997a4ba0386c51b18b0da3663d00772d67497d7753c75d95fa634fa` |
| `v24/s13/w7_recover.py` | `d5c3178038577053d651f1ad53e2d3895f417503253a17045995d8e36d39b85d` |
| `v24/s13/plugins/fs_read.py` | `260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c` |
| `v24/s13/plugins/fs_tools.js` | `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5` |
| `v24/b0/golden/provider_requests_v1.json` | `36ed983f0302c374fc92b3153c0c2a5dbb0fbb722665394ef5643bc51d86e921` |
| `v24/b0/golden/tool_messages_v1.json` | `caea917ae1779922742b427561f9985a69fa9917496b86ec23ec37b478f7ad14` |

The eight final candidate digests (including the documents, which cannot contain their own hash) are recorded in the external `source-sha256.txt` and `publication-receipt.txt`. Stable evidence digests:

| Evidence file | SHA-256 |
|---|---|
| `results.tsv` | `b7a15862889c1f1ec3824a5fdb2a013765c3c389df507fa3340bf3917fdd97e9` |
| `merged.log` | `ae1126a803eae47d9ffd183d254fc44fe04335ce00a9c94eece209be0be2e5bc` |
| `30.log` | `79e4a46000fa009f3adc97cce0f5c2c5c7b5fa533e20bcab4e7157a21e3abf7d` |

## 32-command serial sweep

The exact prefix for every row is `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`. Row 30 uses the W7 marker (`cases=30; recovery_probes=16; ... no_replay=true`); every other expected last line is unchanged from the M5 sweep. Row 32 is the SQL diff and has a zero-byte log.

| # | UTC start | Command | Exit | Actual last line | Log SHA-256 |
|---:|---|---|---:|---|---|
| 1 | 2026-10-31T20:01:44Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-10-31T20:02:13Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-10-31T20:02:17Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T20:02:17Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T20:02:18Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T20:02:19Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T20:02:19Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-10-31T20:02:20Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-10-31T20:02:20Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-10-31T20:02:21Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-10-31T20:02:23Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-10-31T20:02:25Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-10-31T20:02:27Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-10-31T20:02:29Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-31T20:02:29Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-31T20:02:31Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-31T20:02:32Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-31T20:02:35Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-31T20:02:37Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-31T20:02:45Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `f07f61c8a7d4f7f0aa941d60204706ba8440a59671e7a5d20554cc8893c158a4` |
| 21 | 2026-10-31T20:02:50Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `5a29512d14d1267d45a9173dd730d28461bbc39b738e70db795b90142c6a1c0a` |
| 22 | 2026-10-31T20:02:54Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `da0fcd0741e4281d8fcd27e4ca800b964da5b3a684e1185a2b6a88f4623cdf48` |
| 23 | 2026-10-31T20:02:58Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `595f22275ddff77dea049c82e9be7ab0fcb7514eb6bed552b94629c653ccaec6` |
| 24 | 2026-10-31T20:03:00Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `9703538de06d4e1e2b7e3554adcbf8d02c10fe31a4f3b144e56d0dfe83b957d6` |
| 25 | 2026-10-31T20:03:06Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-10-31T20:03:09Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-10-31T20:03:12Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-10-31T20:03:15Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `a81c76c77f9274e7c0592b03c683d6c1bc62eca7ab78ae0f2279cf1f522548a7` |
| 29 | 2026-10-31T20:03:17Z | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` | `d60495a3634f0f18eb7ee422af745b90af3e66454e67a342bfabfe8261accf74` |
| 30 | 2026-10-31T20:03:34Z | `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` | `79e4a46000fa009f3adc97cce0f5c2c5c7b5fa533e20bcab4e7157a21e3abf7d` |
| 31 | 2026-10-31T20:04:14Z | `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |
| 32 | 2026-10-31T20:04:16Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | `<empty>` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Scope audits

The seven audits are the inherited `test_wiring.scope_audit` groups 1/4/5/6 against `c8c4bd0` plus the W7 delta against `a41ce220b60af95070d93ce1571d09d70299a5cf`. Check 1 allows only the four W7 s13 paths (`README.md`, `test_lifecycle.py`, `w4_stub_plugin.py`, `w7_recover.py`) and requires zero diff for `v24/host`, `v24/sql`, `v24/s13/vectors`, and every other `v24/s13/test_*.py`. Check 2 pins the whole vectors tree. Check 3 pins `design_conformance.json`, `test_contracts.py` and the ABI design to their `a41ce22` bytes, with `DESIGN_SHA256 = 778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d`. Check 7 requires the tracked delta and the untracked `path+sha256` delta to be a subset of the eight candidates and prints the added/changed/removed counts.

### Precheck (before the sweep)

| # | Audit | UTC start | Exit | Last line | Log SHA-256 |
|---:|---|---:|---:|---|---|
| 1 | `frozen_modules_and_untracked` | 2026-10-31T20:01:27Z | 0 | `[scope] passed frozen_modules_and_untracked` | `be6ced25e306e998216c14dacb4fced76e8fab4ae73291dd1d2f9e45392caf49` |
| 2 | `vectors_zero_diff` | 2026-10-31T20:01:27Z | 0 | `[scope] passed vectors_zero_diff` | `5ef25b905850e018652426d696d78d0b3e440c65e89d4d6cbc01c620c5727f2f` |
| 3 | `design_pins_zero_diff` | 2026-10-31T20:01:28Z | 0 | `[scope] passed design_pins_zero_diff` | `e230334d2cf50aca7cd30001ba33ba4c9569013c1e3b28dd5d047a294a5b3337` |
| 4 | `registry_exact_patch` | 2026-10-31T20:01:29Z | 0 | `[scope] passed registry_exact_patch` | `ea1a744fa0f1430df824bcd3b98d7d48214af0b61e2e5d709a4b88f50e26e27c` |
| 5 | `host_import_purity` | 2026-10-31T20:01:29Z | 0 | `[scope] passed host_import_purity` | `f22b3a92ba8926508ee266282111acb354f4098f7f21f77a6310568b520f98b3` |
| 6 | `sql_zero_diff` | 2026-10-31T20:01:30Z | 0 | `[scope] passed sql_zero_diff` | `89f69d2e7dcd649ca47f5094ff8820ba349bf688ca43708db3fcf2248985950d` |
| 7 | `w7_candidate_only` | 2026-10-31T20:01:30Z | 0 | `[scope] passed w7_candidate_only` | `1cebb340fb2a7f8a588ef4930cb3bed99fb8284b3ea3ad53bfed352382a8c625` |

### Final (after all documentation)

| # | Audit | UTC start | Exit | Last line | Log SHA-256 |
|---:|---|---:|---:|---|---|
| 1 | `frozen_modules_and_untracked` | 2026-10-31T20:06:35Z | 0 | `[scope] passed frozen_modules_and_untracked` | `be6ced25e306e998216c14dacb4fced76e8fab4ae73291dd1d2f9e45392caf49` |
| 2 | `vectors_zero_diff` | 2026-10-31T20:06:35Z | 0 | `[scope] passed vectors_zero_diff` | `5ef25b905850e018652426d696d78d0b3e440c65e89d4d6cbc01c620c5727f2f` |
| 3 | `design_pins_zero_diff` | 2026-10-31T20:06:36Z | 0 | `[scope] passed design_pins_zero_diff` | `e230334d2cf50aca7cd30001ba33ba4c9569013c1e3b28dd5d047a294a5b3337` |
| 4 | `registry_exact_patch` | 2026-10-31T20:06:36Z | 0 | `[scope] passed registry_exact_patch` | `ea1a744fa0f1430df824bcd3b98d7d48214af0b61e2e5d709a4b88f50e26e27c` |
| 5 | `host_import_purity` | 2026-10-31T20:06:37Z | 0 | `[scope] passed host_import_purity` | `f22b3a92ba8926508ee266282111acb354f4098f7f21f77a6310568b520f98b3` |
| 6 | `sql_zero_diff` | 2026-10-31T20:06:37Z | 0 | `[scope] passed sql_zero_diff` | `89f69d2e7dcd649ca47f5094ff8820ba349bf688ca43708db3fcf2248985950d` |
| 7 | `w7_candidate_only` | 2026-10-31T20:06:38Z | 0 | `[scope] passed w7_candidate_only` | `c6d1dd88aa972910a2ad6bf437027d7af4a867aea056cb164b7b30c08eb9d5f7` |

### Confirmation (after the post-audit record/Result edits)

The confirmation pass re-ran the same seven audits after the final-audit table and the plan Result were written. Its labels, exits, last lines and log digests are recorded only in the external `publication-receipt.txt`, per the plan's rule that the confirmation results do not become a second in-repo audit table.

## R15/R16 fresh-process evidence

Both cases close the parent's journal→db→owner handles and invoke `v24/s13/w7_recover.py` in a separate OS process; the child opens only `HostDB`/`HostJournal`, calls `_reconcile`, never constructs a registry and never spawns.

- **R15 (three pending settlements):** the parent patches `harness.db.settle` so every `tool_call` settle returns `{"error": {"code": "w7_injected_settle_error"}}`. All three tool effects finish dispatch but remain `claimed` with settlement 0; the observed count is 9 injected settle attempts for 3 pending effects. The fresh process reports `[w7-recover] reconciled=3 settlements=3`; afterwards all three effects are `succeeded`, each has exactly one settlement, the continuation count is 1, and the two installs' spawn operations are unchanged. Restoring the saved bound method (direct assignment, no `patch.stop()`) before recovery is the hard boundary: a leaked patch would settle the pending effects in-process and invalidate the evidence.
- **R16 (K3.5 backfill):** the parent injects `HostCrash` before the `settlement_committed` append for the tool effect. At that point the DB row is already `succeeded` with `settled_at` set, the journal has one `dispatch_finished` and zero settlements, and the spawn operations are `{prepare: 1, invoke: 1}`. The fresh process reports `reconciled=0 settlements=1`; the backfilled payload is `reason="database_terminal"`, `conflict=false`, and `reconciled` is absent. The effect row is byte-for-byte unchanged across recovery, the second `_reconcile` returns 0, the run completes with one continuation, and the spawn count does not move.

## R03/R13 process-cleanup observations

- **R03 (real host crash, test-side cleanup only):** the host child is terminated by `SIGKILL` after the plugin has spawned (`WIFSIGNALED=true`, `WTERMSIG=9`, `signal_name=SIGKILL`). The plugin is still live at crash time (`ps -o stat=` = `Ss`); the test then sends `killpg(plugin_pid, SIGKILL)` and observes `ps=""`. The `invoke` count is 1 at crash and 1 after recovery, with no second spawn and no live plugin PID. This proves the test's cleanup is complete and that recovery does not spawn again. It does **not** prove host-side automatic group kill: the signal that removes the plugin here comes from the test.
- **R13 (host timeout, host-side group kill):** the plugin's own 1000 ms timeout drives the host path. After 1.131 s both the plugin PID and the grandchild PID read `ps=""`, and the test has sent no signal before the observation. The grandchild (`sleep(60)`, same process group, not a new session) can only disappear through the host's group-level kill (`process_io._kill_group`); `.child` proves it was started. The restart reports `reconciled=0` and leaves the journal at 12 records and 3 settlements. This is the only host-auto-group-kill evidence in W7; R03's `killpg` must not be cited for it.

## V24_W7_* environment-only note

`v24/s13/w7_recover.py` reads exactly two configuration inputs, `V24_W7_ADMIN_DSN` and `V24_W7_SERVICE_DSN`. They are test-process environment only: `test_lifecycle.py` sets them from the fixture's existing role DSNs when it spawns the child, they are not read by `v24/host/**` or `v24/sql/**`, they are not persisted, and they are not production configuration. No new env/argv/wire switch was added to a production entry point.

## Limits

- **No tool replay.** Every tool effect remains `no_replay`; K1/K2 stay `settle_unknown`, with no `reset_ready` tool call and no automatic re-execution. W7 proves non-replay, not replayability.
- **No real provider or network.** The model transport is scripted; `DEEPSEEK_API_KEY`/`OPENAI_*` are unset by the sweep prefix.
- **No Linux real.** `linux_real=not_run`; R03 uses `fork`/`waitpid`/`killpg` on macOS only.
- **No infinite crash set.** K0–K5+K3.5 is the plan's enumeration, not every possible interleaving; model `dispatch_started`-to-response crashes remain outside W7.
- **No 12-second wall-clock claim.** This stage does not re-open the M3 timing discussion and adds no wall-clock gate.
- **No production change.** Host, SQL, vectors, fixture modules, design, pins and frozen tests are zero-diff; W7-8 was not triggered.
- **Case-count semantics.** `cases=30` is function-level; R11/R13/R14/R15/R16 sub-probes are deliberately not counted as extra cases, unlike the W4c sub-scenario count of 14.
- **One input correction.** The brief's `v24/s13/vectors/b0_golden/golden.json` is absent; `v24/b0/golden/*.json` is the actual B0 golden set.

## Deviations

No W7-8 deviation. The only deviations are documentation/evidence-tooling details: the absent `b0_golden` path described above; audit 7's baseline-universe handling for the ignored `__pycache__` entries in the 35-entry W7-0 snapshot; and running one confirmation audit after the final-audit table and the plan Result were written, as the plan requires for post-audit edits. No runtime, host, SQL, loader, fixture, plugin, vector or ABI-design byte changed.

## Publication

The publication unit is the eight candidate paths listed above. After all documentation was written, all seven audits were rerun in full; after the final-audit table and the plan Result were added, one confirmation pass was rerun. Staging, the credential scan, the single commit and the non-force push are performed outside this record. The commit SHA, push exit code, remote ref update line, post-push `git rev-parse origin/main`, UTC time, sweep HEAD, 32/32 result, audit labels/exits/log digests and the eight-path manifest are recorded in the external `/tmp/v24-abi-w7-20261031T200002Z/publication-receipt.txt`; this record does not embed its own commit hash.
