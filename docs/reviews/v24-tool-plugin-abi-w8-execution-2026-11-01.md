# v24 Tool/Plugin ABI W8 v1 acceptance execution record

Date: 2026-11-01 (+08:00; the evidence directory uses the UTC stamp `2026-11-01T03:31:23Z`). Scope: W8 of the [W8 plan](../plans/v24-tool-plugin-abi-w8-v1-acceptance-2026-11-01.md) — the first per-item acceptance of design §7.4 done-when 1–8, the frozen 32-command serial sweep, the independent SUP-1 observation, and the eight-item disposition. This record is the acceptance authority. It does not embed its own SHA or a future commit SHA.

## Result

The frozen 32-command serial sweep ran once, in order, from the repository root with the plan's exact `ENVPFX` prefix. All 32 rows exited 0 and matched the pre-frozen last line byte-for-byte (row 32 exited 0 with a zero-byte log and an empty last line). No exit 2 and no `[SKIP]` occurred. The first command started at `2026-11-01T03:44:36Z` and the last ended at `2026-11-01T03:47:13Z`; these are command window timestamps, not an end-to-end acceptance duration.

SUP-1 ran separately after row 32 and is not part of the 32-row table. It exited 0 with the exact last line `[pass] B0-2 DB-only multi-provides probe; zero process spawns`; its positive and cross-realm rejection lines are quoted below. It is a W8-added supplementary observation, not a design §7.4 requirement, not row 33, not a twelfth closeout item, and not an input to the eight-item aggregation.

Seventeen clause tokens, in canonical order:

```text
1a=PASS; 1b=PASS; 2a=PASS; 2b=PASS; 3a=PASS; 3b=PASS; 4a=PASS; 5a=PASS-LIMITED; 5b=PASS; 6a=PASS; 6b=PASS; 6c=PASS; 7a=PASS; 7b=PASS; 7c=PASS; 8a=PASS; 8b=PASS
```

Eight-item projection:

| # | clauses | clause tokens | verdict | key evidence |
|---:|---|---|---|---|
| 1 | 1a, 1b | `1a=PASS`; `1b=PASS` | **PASS** | rows 3–8 and 29–31 exit 0 with exact markers; `test_node.py:75-77` is the SKIP/return-2 branch |
| 2 | 2a, 2b | `2a=PASS`; `2b=PASS` | **PASS** | row 30 `python=ok node=ok`; `g12_a` asserts spawn 2/3 and `teardown_two_install` asserts disposed/released/closed |
| 3 | 3a, 3b | `3a=PASS`; `3b=PASS` | **PASS** | row 30 pins list==search and read!=list; the same start passes the literal three-key requires |
| 4 | 4a | `4a=PASS` | **PASS** | row 30 `g12_b`: one continuation, two transport calls, three tool effects |
| 5 | 5a, 5b | `5a=PASS-LIMITED`; `5b=PASS` | **PASS-LIMITED** | row 30 `g12_c` and `tamper_case`/R11/R12 under `ZeroSpawn`; 5a reads "all invalid args" as the enumerated set |
| 6 | 6a, 6b, 6c | `6a=PASS`; `6b=PASS`; `6c=PASS` | **PASS** | rows 12–13 B0 `_compare`; row 30 `g12_l` provider-request and tool-message byte equality |
| 7 | 7a, 7b, 7c | `7a=PASS`; `7b=PASS`; `7c=PASS` | **PASS** | row 32 zero-byte SQL diff plus audits 1/6; closed 32+SUP-1 construction inventory and ENVPFX |
| 8 | 8a, 8b | `8a=PASS`; `8b=PASS` | **PASS** | rows 14–24 are the eleven frozen closeout commands; s13 is not a twelfth item; audit 7(d) re-checks at final |

The declaration gate in plan §6.4 is satisfied: every item is in `{PASS, PASS-LIMITED}` and SUP-1 has no contradiction with any clause predicate. The declaration sentence is:

> 在本记录所列实际运行日，基于 `HEAD_sweep` 与最终一致的执行源码，按设计 §7.4 done-when 1–8 宣告 v24 Tool/Plugin ABI v1 通过有边界验收。M4、M5 的既有完成声明继续有效；W8 不新增 M 阶段。closeout 仍为 11/11，s13 为 extension evidence。SUP-1 是 W8 自加的补充观察，不是本次验收的组成部分。具体限制以本轮 matrix 与 execution record 为准。

The unified non-declaration range required by plan §8.5 applies verbatim:

> 不声明硬实时 12 秒上界；C.18.3 的 T1/T2/T3 保持分层。`linux_real=not_run`；非 UTF-8 文件名证据仅为 macOS root-level shim，不覆盖子目录真实非法名称。不声明工具自动重执行，tool 仍为 `no_replay`。不承诺慢 scope 的分页收敛。不调用真实 provider，不进行 gate 对外网络访问；"无网络"是逐行构造论证，不是 OS 级隔离证明。

## Candidate and provenance

- Checkout `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; `HEAD_sweep` `5dcbf633ca7b08e171255ee3cf2900d0e5dd6008` (`v24: apply W7 lifecycle review fixes and refresh evidence`); `origin/main` at the same commit before the sweep.
- Environment: uv `0.8.24 (252f88733 2025-10-07)`, Python `3.12.11` at `/Users/wxl/Projects/pg-agent/.venv/bin/python3`, Node `v24.13.1` at `/Users/wxl/.nvm/versions/node/v24.13.1/bin/node`, pgembed `0.3.0rc2` (PostgreSQL `18.4`, fixture-managed Unix socket), Homebrew `psql 17.11` present as a client, Darwin `25.6.0` / macOS `26.6.2 (25G83)` / arm64. No real provider and no outbound network connection were used.
- The sweep ran with the parent environment `UV_OFFLINE=1` and every row prefixed with `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`.
- The tracked worktree was clean at sweep start and after row 32. The W8-0 untracked baseline `U0` has 27 entries; the six candidates were 5 present plus this record absent before W8-5. `baseline-candidates/` holds the pre-run copies and `absent.txt` records the missing record.
- Exactly six candidate paths:
  1. `docs/plans/v24-tool-plugin-abi-w8-v1-acceptance-2026-11-01.md` (plan, new)
  2. `docs/reviews/v24-tool-plugin-abi-w8-plan-critique-2026-11-01.md` (plan-period critique, new)
  3. `v24/s13/README.md`
  4. `docs/reviews/v24-conformance-matrix-2026-10-23.md`
  5. `docs/reviews/v24-deviation-ledger-2026-10-23.md`
  6. `docs/reviews/v24-tool-plugin-abi-w8-execution-2026-11-01.md` (this record, new)
- Evidence directory `/tmp/v24-abi-w8-20261101T033123Z/`. It contains `provenance.txt`, `baseline-untracked.txt`, `baseline-candidates/`, `expected-last-lines.txt`, `source-sha256-sweep.txt`, `01.log`–`32.log`, `results.tsv`, `merged.log`, `sup-1.log`, `supplementary/results.tsv`, `claim-evidence.txt`, `evidence-binding.tsv`, `register-w8.tsv`, `scope-precheck/`, `scope-final/`, `scope-confirmation/`, `run-audits-w8.py`, `credential-scan.txt`, and `publication-receipt.txt`.
- `results.tsv` SHA-256 `980e79a4f2a229586bf84a8d30f11bc0ca2c273932af4fc09a1988e20dc0f0f4`; `merged.log` SHA-256 `79aa511d41f0bfbeb5bd5456c838cc3babd9f81d4321787aba2da8aee54cca9f`; `evidence-binding.tsv` SHA-256 `f12dc3126e95aae348eab6b5ab9b9078f10addf04770c350f716711c6e5350b1`; `register-w8.tsv` SHA-256 `721960e0459d80aacdad49388b61c9fc0c889059e968414478ea4f64d2574c42`; `sup-1.log` SHA-256 `6dedc5969fd3adbb6222825d0293481b48834642ae28d8dc70cf501feb1c2b39`.
- The full post-sweep source fingerprint (167 tracked `v24/**` files excluding the editable `v24/s13/README.md`, plus the ABI design) is in Appendix A. The seven rows matching the W7 record's source table are unchanged: `test_lifecycle.py f189a5c8…`, `w4_stub_plugin.py 916ca5b2…`, `w7_recover.py 64563988…`, `fs_read.py 260274da…`, `fs_tools.js efd05d63…`, `provider_requests_v1.json 36ed983f…`, `tool_messages_v1.json caea917a…`. The ABI design SHA is `778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d`.

## 32-command serial sweep

The command table, order and `ENVPFX` prefix are the frozen plan §7.2 table. Rows 27/28/31 use the current literal Node path only in their expected last lines; their command bytes do not contain `node=`. Row 32 has no marker and is required to exit 0 with zero output. The `last_line` column is the producer's actual last non-empty line; row 32 is `<empty>` with a zero-byte log.

| # | UTC start → end | Command | Exit | Actual last line | Log SHA-256 |
|---:|---|---|---:|---|---|
| 1 | 2026-11-01T03:44:36Z → 2026-11-01T03:45:05Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-11-01T03:45:05Z → 2026-11-01T03:45:09Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-11-01T03:45:09Z → 2026-11-01T03:45:10Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-11-01T03:45:10Z → 2026-11-01T03:45:10Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-11-01T03:45:10Z → 2026-11-01T03:45:11Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-11-01T03:45:11Z → 2026-11-01T03:45:12Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-11-01T03:45:12Z → 2026-11-01T03:45:12Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-11-01T03:45:12Z → 2026-11-01T03:45:13Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-11-01T03:45:13Z → 2026-11-01T03:45:13Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-11-01T03:45:13Z → 2026-11-01T03:45:15Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-11-01T03:45:15Z → 2026-11-01T03:45:17Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-11-01T03:45:17Z → 2026-11-01T03:45:19Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-11-01T03:45:19Z → 2026-11-01T03:45:21Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-11-01T03:45:21Z → 2026-11-01T03:45:22Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-11-01T03:45:22Z → 2026-11-01T03:45:23Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-11-01T03:45:23Z → 2026-11-01T03:45:25Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-11-01T03:45:25Z → 2026-11-01T03:45:28Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-11-01T03:45:28Z → 2026-11-01T03:45:30Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-11-01T03:45:30Z → 2026-11-01T03:45:38Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-11-01T03:45:38Z → 2026-11-01T03:45:42Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `4963eac4c672538bbc63e5caf8d93d3283423366ec6cf5e65d6fb62ed296c4f8` |
| 21 | 2026-11-01T03:45:43Z → 2026-11-01T03:45:47Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `7d4ee5489f8bec00328d281c7878130f895f10d0203d93572fd456a71e0469bf` |
| 22 | 2026-11-01T03:45:47Z → 2026-11-01T03:45:51Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `a44e9c05842f28ff4b692cc3850b05e498336503b60ff9dec8e5b4b415befb60` |
| 23 | 2026-11-01T03:45:51Z → 2026-11-01T03:45:54Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `085426c0f643f67aad3a44f3131db4a506721255502a36b04336be7f8a99b31c` |
| 24 | 2026-11-01T03:45:54Z → 2026-11-01T03:46:01Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `1e61f25f4d5697147ec8e8fb4bde45b54581123e238071f45ab4e4e41ae2575b` |
| 25 | 2026-11-01T03:46:01Z → 2026-11-01T03:46:04Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-11-01T03:46:04Z → 2026-11-01T03:46:07Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-11-01T03:46:07Z → 2026-11-01T03:46:09Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-11-01T03:46:09Z → 2026-11-01T03:46:11Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `469fe6b6ae16163e770824031091569aa9b859bb330ca95d08389bb22cec81ff` |
| 29 | 2026-11-01T03:46:11Z → 2026-11-01T03:46:28Z | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` | `fff82b867c27e6514d34b5d322fc78572491d403853f7690f1ab8d779058dca5` |
| 30 | 2026-11-01T03:46:28Z → 2026-11-01T03:47:11Z | `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` | `e88641e33e7c153a4385ff6056ea92b1fb6cfa69d1ccb618d449ff6c643d04fa` |
| 31 | 2026-11-01T03:47:11Z → 2026-11-01T03:47:13Z | `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |
| 32 | 2026-11-01T03:47:13Z → 2026-11-01T03:47:13Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | `<empty>` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Row 29's `[probe]` and `[evidence]` lines, verbatim (informational only; `linux_real=not_run` is a non-declaration reference, not a gate):

```text
[probe] W5-R25 newlines_1m; peak_kib=1793.044
[probe] W5-R25 wide; peak_kib=3959.904
[probe] W5-R01..R29 green
[probe] W6-L01..L11 green
[probe] W6-S25 real_clock_elapsed_ms=50.338; overshoot_ms=0.338
[probe] W6-S26 enum_cost_wall_ms=121.926; json_stringify_count=600
[probe] W6-S01..S26 green
[evidence] non_utf8_source=preload_shim; linux_real=not_run
[evidence] read_artifact_sha256=260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c; read_1m_wall_ms=93; read_peak_kib=3959.904; permission_probe=real
```

The three required markers on rows 29/30/31 are:

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node
```

No row exited 2 or printed `[SKIP]`. Rows 14–24 are exactly the eleven frozen closeout commands from `v24/s7/README.md:215-227`: closeout remains **11/11**, and s13 is extension evidence, not a twelfth item.

## SUP-1

SUP-1 is the W8-added DB-only multi-provides observation. It ran once, after row 32, in its own process with the same `ENVPFX` prefix and `UV_OFFLINE=1`. It is not part of `01.log`–`32.log` and does not occupy row 33.

| item | UTC start → end | command | exit | last line | log SHA-256 |
|---|---|---|---|---|---|
| SUP-1 | 2026-11-01T03:47:15Z → 2026-11-01T03:47:18Z | `uv run python v24/b0/test_multi_provides.py` | 0 | `[pass] B0-2 DB-only multi-provides probe; zero process spawns` | `6dedc5969fd3adbb6222825d0293481b48834642ae28d8dc70cf501feb1c2b39` |

The complete output is three lines:

```text
[pass] positive: one install -> two live slots -> one run -> two matching pins
[pass] negative: cross-realm requirement is unresolved; no run or pin
[pass] B0-2 DB-only multi-provides probe; zero process spawns
```

The marker is `[pass]`, not `[passed]`; `v24/b0/test_multi_provides.py` is frozen and W8 does not change its spelling. The positive line confirms one install → two live slots → one run → two matching pins at the DB layer. The negative line confirms the cross-realm requirement is unresolved and creates no run or pin. SUP-1 has no contradiction with any clause predicate, so no `unrelated-infrastructure` label is needed; it remains supplementary and is not an input to §6.4.

## Acceptance and residual debt

`BOUND` in the register below is a binding statement, not a verdict. The load-bearing file digests are `test_lifecycle.py f189a5c83c91f34100e9056718139601bbe6a910fbc84763524c65f4f0df89fc`, `test_node.py 56170aec7b9df910e0b8ff118c6473e907b035f87d8bd76fbeaed811a03f012a`, `test_golden.py 41e999ac84e2bb42db0f0b1e4a113312534fea211327012e097b1afc81c1c97f`, and `test_wiring.py 2afe5a9b15f518f93384651fa0973547678d175db91682c2848761c401f25077`. The full per-span digests are in `evidence-binding.tsv`.

### Clause register (17 rows)

| clause | required predicate | file:line span | binding | this-round evidence | verdict | limitation | falsifier |
|---|---|---|---|---|---|---|---|
| 1a | nine design-named s13 gates exit 0 and print the exact final marker | test_descriptor.py:321-324; test_schema.py:224-227; test_renderers.py:246-249; test_results.py:407-410; test_registry.py:527-529; test_line_json.py:384-389; test_tools.py:1710-1715; test_lifecycle.py:2862-2864; test_node.py:124 | BOUND | rows 3-8,29-31 exit 0 and expected_match=yes | PASS | — | any row non-zero, exit 2, [SKIP], or marker mismatch |
| 1b | Node absent prints [SKIP] and returns 2, never a pass | test_node.py:75-77 | BOUND | static branch observed; Node v24.13.1 present, so the absent branch did not execute; rows 27 and 31 ran with --node | PASS | static contract: missing-Node branch not executed in this round | Node absent but recorded as PASS |
| 2a | full install->prepare->activate->start->model->tool->settlement->off->dispose->release->scope close | test_lifecycle.py:643-682,162-179 | BOUND | row 30 exit 0; g12_a completed; teardown_two_install asserts disposed, disposed_at, slot released and close_scope().closed_at | PASS | local PostgreSQL, scripted model transport, macOS (environment note, not predicate narrowing) | any missing stage assertion; in-process-only call; release/scope close absent |
| 2b | Python and Node are real subprocesses with non-zero spawn counts | test_lifecycle.py:678-679; test_node.py:120-121 | BOUND | row 30 python=ok node=ok; g12_a spawn_count(read)=2 and spawn_count(node)=3; test_node spawn=3 | PASS | — | spawn count 0; either language missing |
| 3a | one Node install provides list+search, distinct from the read install | test_lifecycle.py:673-677; test_node.py:114-119 | BOUND | row 30 pins list==search and read != list; row 31 host_run_pins has two keys with one provider_install_id | PASS | — | two installs; pins point to different installs |
| 3b | one start requires exactly read,list,search | test_lifecycle.py:647-648,155-159 | BOUND | row 30 g12_a start_run(..., ["read","list","search"], ...) | PASS | — | requires length != 3 |
| 4a | one three-tool model batch yields exactly one continuation and two transport calls | test_lifecycle.py:689-710 | BOUND | row 30 exit 0; g12_b model_call count 2, continuation count 1, len(transport.calls)==2 | PASS | — | continuation 0 or >1; tools from different batches |
| 5a | invalid args fail before any spawn; process count unchanged | test_lifecycle.py:725-737,80-98 | BOUND | row 30 exit 0; g12_c runs under ZeroSpawn, reports invalid_tool_arguments, spawn_count == baseline | PASS-LIMITED | all invalid args is read as the design/gate enumeration; no malicious concurrent-workspace claim | journal-event counting only; a real spawn in the failure phase |
| 5b | artifact/adapter/descriptor tamper and workspace unavailability produce zero spawn | test_lifecycle.py:795-831,2373-2389,2462-2474 | BOUND | row 30 exit 0; tamper_case uses ZeroSpawn plus spawn-log baseline; R11 four shapes; R12 double proof | PASS | — | one of journal/spawn-log proofs missing; recovery success mixed into the failure phase |
| 6a | provider request bodies are byte-identical to B0 | test_lifecycle.py:960-1004 | BOUND | rows 12-13 B0 check; row 30 g12_l compares transport call body to expected_hex | PASS | — | any byte difference; parsed-JSON comparison only; golden regenerated |
| 6b | descriptor bytes are byte-identical to B0 | test_golden.py:92-106 | BOUND | rows 12-13 _compare covers descriptor_v1.json expected_hex | PASS | — | any byte difference; treating G12-L/R14 as descriptor evidence |
| 6c | tool message content is byte-identical to B0 | test_lifecycle.py:960-1004 | BOUND | rows 12-13 B0 check; row 30 g12_l compares content.encode("utf-8") to expected_hex | PASS | — | any byte difference |
| 7a | v24/sql zero diff and no untracked SQL | test_wiring.py:801-805,869-871 | BOUND | row 32 exit 0 with zero-byte output; precheck audits 1 and 6 | PASS | row 32 is stronger than the design's uncommitted-only diff | SQL differs; untracked SQL exists |
| 7b | no gate opens an outbound network connection | claim-evidence.txt:7b; test_g2b.py:70-78; test_g9.py:99-102; test_multi_provides.py:279-284 | BOUND | closed 32-row plus SUP-1 construction inventory; ENVPFX; logs show unix-only pgembed, no outbound connection | PASS | static construction plus credential scrub; not OS-level isolation | a gate constructs a real adapter; network dependency download; inventory gap |
| 7c | no gate constructs a real provider adapter | claim-evidence.txt:7c; test_g9.py:540-561 | BOUND | no --real-provider-smoke in the command table; scripted transports; g9 smoke patches DeepSeekAdapter and _live | PASS | static construction argument | sweep includes --real-provider-smoke; a gate constructs a real provider |
| 8a | eleven frozen closeout commands all pass | v24/s7/README.md:215-227 | BOUND | rows 14-24 exit 0 with exact markers; closeout 11/11 | PASS | — | count != 11; a command skipped or replaced |
| 8b | s13 is not the twelfth closeout item | v24/s13/README.md:184; plan 6.1,10.3(d) | BOUND | rows 14-24 are exactly 11; s13 is not a twelfth item; audit 7(d) re-checks at final | PASS | final text audit is a W8-6 gate; a failure there withdraws the declaration | s13 or SUP-1 written as the twelfth item |

The clause verdicts are `1a PASS, 1b PASS, 2a PASS, 2b PASS, 3a PASS, 3b PASS, 4a PASS, 5a PASS-LIMITED, 5b PASS, 6a PASS, 6b PASS, 6c PASS, 7a PASS, 7b PASS, 7c PASS, 8a PASS, 8b PASS`. Applying plan §6.4's worst-of order yields the eight-item projection in the Result. Item 5 is the only `PASS-LIMITED`: 5a's "all invalid args" is read as the design/gate enumeration, and the row explicitly does not claim malicious concurrent-workspace safety. No item is `NOT-DEMONSTRATED`, `BLOCKED`, or `FAIL`.

SUP-1's failure-handling rule from plan §5.3 was not triggered because SUP-1 passed. Its role remains outside the aggregation: if it had failed, the executor would have answered only whether the failure directly contradicted a clause predicate; a contradiction would have failed that clause, and an unrelated infrastructure failure would have been labelled with a written reason. The absence of a failure means no such judgement is recorded.

### Residual debt summary

The closed-set dispositions and their this-round evidence are in the matrix W8 section; this record summarizes the counts and links there.

| Set | Rows | Verdict distribution | Authority |
|---|---:|---|---|
| §9 risks | 10 | 1 MITIGATED, 2 MITIGATED, 3 MITIGATED, 4 ACCEPTED-LIMITATION, 5 ACCEPTED-LIMITATION, 6 MITIGATED, 7 DEFERRED-REVISION, 8 MITIGATED, 9 ACCEPTED-LIMITATION, 10 MITIGATED (conditional on the observed row 29 run) | matrix W8 §9 table |
| §8 deferred revisions | 3 | §8.1 DEFERRED-REVISION, §8.2 DEFERRED-REVISION, §8.3 DEFERRED-REVISION | matrix W8 §8 table |
| Design exit conditions | 6 | 1–6 all NOT-TRIGGERED | matrix W8 exit-condition table |

The risk and revision verdicts do not widen the acceptance: #4/#5/#9 remain accepted limitations, #7 remains a deferred revision, and the six design exit conditions remain untriggered in this run. No trigger was observed that would convert any row to `TRIGGERED-STOP`.

## Scope audits

The seven audits are the inherited `test_wiring.scope_audit` groups 1/4/5/6 against `c8c4bd0`, the W8 frozen delta against `5dcbf63`, and the candidate-only audit 7. Audit 7 is phase-graded: precheck checks (a) only; final and confirmation check (a)–(f). The audit harness is external to the repository and does not enumerate or schedule gates.

### Precheck

The precheck ran after the W8-1 binding and before the sweep, using audit-harness revision 1 (`run-audits-w8-rev1.py`, SHA-256 `704701e698a4a7ff44711b3381b993651e2284c958978637cf9c6d78303b387f`). Revision 1 implemented audit 7(a) for precheck and the two required negative controls.

| # | Audit | UTC start | Exit | Last line | Log SHA-256 |
|---:|---|---:|---:|---|---|
| 1 | `frozen_modules_and_untracked` | 2026-11-01T03:34:21Z | 0 | `[scope] passed frozen_modules_and_untracked` | `4647c65994f5c05f0b786dc2e8816e574f53c36b36e8b0e073c15880c0beda04` |
| 2 | `vectors_zero_diff` | 2026-11-01T03:34:22Z | 0 | `[scope] passed vectors_zero_diff` | `7d2c139e3c5b3ec357affdc55f7b7256cf5e98a71eb2bf9224580a650989c0f9` |
| 3 | `design_pins_zero_diff` | 2026-11-01T03:34:22Z | 0 | `[scope] passed design_pins_zero_diff` | `be0a78551e3fd1c3f5ced31d75c0c9e9eea6dfcb58ea715839a390fa22fa8172` |
| 4 | `registry_exact_patch` | 2026-11-01T03:34:23Z | 0 | `[scope] passed registry_exact_patch` | `ea1a744fa0f1430df824bcd3b98d7d48214af0b61e2e5d709a4b88f50e26e27c` |
| 5 | `host_import_purity` | 2026-11-01T03:34:24Z | 0 | `[scope] passed host_import_purity` | `f22b3a92ba8926508ee266282111acb354f4098f7f21f77a6310568b520f98b3` |
| 6 | `sql_zero_diff` | 2026-11-01T03:34:24Z | 0 | `[scope] passed sql_zero_diff` | `89f69d2e7dcd649ca47f5094ff8820ba349bf688ca43708db3fcf2248985950d` |
| 7 | `w8_candidate_only` | 2026-11-01T03:34:25Z | 0 | `[scope] passed w8_candidate_only phase=precheck checks=1` | `4309df5743c81cc9ca54c9b63f377a19fce6fc38c89a756ae380b5a88dcc8f6d` |

The precheck negative controls failed as required: a synthetic matrix token inconsistent with the register exited non-zero with the expected (f) mismatch, and an out-of-candidate untracked content change exited non-zero with the expected outside-candidate path.

### Final

The final audit ran after all five W8 documents were written, with audit-harness revision 2 (`run-audits-w8.py`, SHA-256 `b2e6eed4c1d7eed3b7e1d2c54f48c85e70aba6ac4bde57099c8875258ec38a89`). Revision 2 keeps revision 1's checks and implements (d) the closeout wording, (e) the four table shapes, and (f) the 17-token and item-projection equality. The final pass ran with `UV_OFFLINE=1` and the same `ENVPFX` prefix.

| # | Audit | UTC start | Exit | Last line | Log SHA-256 |
|---:|---|---:|---:|---|---|
| 1 | `frozen_modules_and_untracked` | 2026-11-01T03:53:41Z | 0 | `[scope] passed frozen_modules_and_untracked` | `306e7f5956fc866991cb9c446d6e224ed985a013b3ca933afc79a2ecb639447a` |
| 2 | `vectors_zero_diff` | 2026-11-01T03:53:41Z | 0 | `[scope] passed vectors_zero_diff` | `7d2c139e3c5b3ec357affdc55f7b7256cf5e98a71eb2bf9224580a650989c0f9` |
| 3 | `design_pins_zero_diff` | 2026-11-01T03:53:42Z | 0 | `[scope] passed design_pins_zero_diff` | `be0a78551e3fd1c3f5ced31d75c0c9e9eea6dfcb58ea715839a390fa22fa8172` |
| 4 | `registry_exact_patch` | 2026-11-01T03:53:42Z | 0 | `[scope] passed registry_exact_patch` | `ea1a744fa0f1430df824bcd3b98d7d48214af0b61e2e5d709a4b88f50e26e27c` |
| 5 | `host_import_purity` | 2026-11-01T03:53:43Z | 0 | `[scope] passed host_import_purity` | `f22b3a92ba8926508ee266282111acb354f4098f7f21f77a6310568b520f98b3` |
| 6 | `sql_zero_diff` | 2026-11-01T03:53:43Z | 0 | `[scope] passed sql_zero_diff` | `89f69d2e7dcd649ca47f5094ff8820ba349bf688ca43708db3fcf2248985950d` |
| 7 | `w8_candidate_only` | 2026-11-01T03:53:44Z | 0 | `[scope] passed w8_candidate_only phase=final checks=6` | `717e515689777233f5cb2b7bbda8404e49db284e7f69461cf6fe565b3c64f2d1` |

All seven exited 0 and matched their phase-specific last lines. The three negative controls failed as required: token mismatch (`2b=FAIL`), an untracked path outside the candidate set (`outside.txt`), and a projection table with 9 data rows where 8 are required. The final audit's revision 2 SHA-256 is the same as the script that produced this table.

The confirmation pass is run after the final-audit table and the plan Result are written. Its labels, exits, last lines and log digests are recorded only in the external `publication-receipt.txt`, as required by the plan; they do not become a second in-repo audit table.

## Deviations / Limits / Publication

### Deviations

No runtime, host, SQL, loader, fixture, plugin, vector or ABI-design byte changed. The only pre-sweep document correction was inside the untracked W8 plan: W8-1 tightened the 7a span to `test_wiring.py:801-805,869-871`, the 5b span to `test_lifecycle.py:795-831`, and the `g12_a` anchor to `:643`; `U0` was refreshed afterwards. Those edits changed no executed source and no verdict input. The precheck used audit-harness revision 1; final and confirmation use revision 2 because revision 1's final path printed `checks=6` without implementing (d)–(f). This is an evidence-tooling correction, not a gate relaxation: revision 2 re-runs (a) and adds the missing checks, and the precheck's (a) result remains valid.

No STOP condition was triggered. No production or test repair, design repin, vector re-bless, promotion, aggregate runner or new M stage was needed.

### Limits

The unified non-declaration paragraph in the Result applies. In addition, the W7 boundaries remain: R03's plugin cleanup is test-side; R13 is the host-side timeout process-group cleanup; the unobserved crash windows before model response, fair-worker recovery debt, and automatic recovery of blocked sibling effects remain outside W8. The acceptance does not re-adjudicate M5's 34 frozen `status` positions and does not promote the four pending tokens.

### Publication

The publication unit is the six candidate paths listed above. The single commit, path-scoped staging, credential scan and non-force push are performed after the confirmation audit. The commit SHA, push exit code, remote ref update, post-push `git rev-parse origin/main`, UTC time, `HEAD_sweep`, 32/32 result, audit labels/exits/log digests and the six-path manifest are recorded in the external `/tmp/v24-abi-w8-20261101T033123Z/publication-receipt.txt`; that receipt is a publication log, not acceptance authority. This record does not embed its own SHA or the future commit SHA.

## Appendix A — post-sweep source fingerprint

All 167 tracked `v24/**` files except the editable `v24/s13/README.md`, plus the ABI design. Generated after row 32; the tracked worktree was clean. This table is a provenance snapshot, not a second acceptance input.

```text
# W8 post-sweep source fingerprint
# HEAD=5dcbf633ca7b08e171255ee3cf2900d0e5dd6008
# excludes v24/s13/README.md (the only executable-source-adjacent path W8 may edit)
d69452b723c9f0a9b201685331167c1c91b94045435177ef6e7316a7b84cba1b  v24/b0/capture_golden.py
a03a3f620744ad3400769efb583499e22957c61c94f93bbc4b9dd1de3fed4a4e  v24/b0/golden_cases.py
eeaf281f89de42a7c4d0e4e49e692678c69ddb12c47f47fb9344ad09345561c7  v24/b0/golden/descriptor_v1.json
74f1220be8ab553fbd4e4399a106bb64c91143332105546182c6cde2778a6a80  v24/b0/golden/frames_v1.json
36ed983f0302c374fc92b3153c0c2a5dbb0fbb722665394ef5643bc51d86e921  v24/b0/golden/provider_requests_v1.json
caea917ae1779922742b427561f9985a69fa9917496b86ec23ec37b478f7ad14  v24/b0/golden/tool_messages_v1.json
51b35472285f78100cd9a16810f1128fd5159c3f9b17dbdebe3d7b54626fd8ee  v24/b0/README.md
41e999ac84e2bb42db0f0b1e4a113312534fea211327012e097b1afc81c1c97f  v24/b0/test_golden.py
dc7476bf6f8b6e3c6ecbdc505c40ee6f7b3793381680bc20375c2c4224339d5e  v24/b0/test_multi_provides.py
ed08ea1a20b386a4dda0fad53bbfa30a5db09a4ce45b19e0ceeed62bc96018e9  v24/cordis/dp1/README.md
67a9bc056c7706123a9a6756ec8e0dd96eb5d880c947b62bbe59ed8f4273acc8  v24/cordis/dp1/setup_db.py
bee679753e3c7b77705d0780813c6d1a992b81c2c757a13054a0d1564e543755  v24/cordis/dp1/test_ddl.py
21d786e3bd3f15dd9f20ff5dd94f3ecc1865081a9564fb7dad80c00c45dde262  v24/cordis/dp1/test_environment.py
ca2d8f027b5cb541fe708c15667305a7b09d11c9187f2b40d7b5c3c6e2db82b9  v24/cordis/dp1/test_kernel.py
fecb91b6e3b05cf86c04c5703fc29d0632a8dafa704b84cee4d921f90ea899be  v24/cordis/dp2/README.md
0308ff2fd74467a21de0434b4623596d09f3ffdb06aa94f778aed94074390094  v24/cordis/dp2/test_activation.py
e9a261238468c4a7d337828d78eb6fc33812b71e79a9117912af2f235a6c0f4a  v24/cordis/dp2/test_boundaries.py
2d597653d3eb084122eb139ffda58b5a1fc9b35fc7072c2a4fb2955653a37c0e  v24/cordis/dp2/test_install.py
203740fe77cecbc44a28528e534f96bd2bb2091707ab4237c0d45d2b4d5cc458  v24/cordis/dp2/test_kernel.py
0f83679beb125b250153993be31612b4dbe4c05a8167b50d3ce1b06895157526  v24/cordis/dp2/test_support.py
3878fbfb5550623019a3dae9e372185d90a5bbef14ac3357fe57570dc6ef6073  v24/cordis/dp3/README.md
0a1fe7a76a1cb48d48c2ce3321deaa4b075a2e1d3cb6de6a9b190f1a9b11b28b  v24/cordis/dp3/test_boundaries.py
a91b3d697ce524a75ecb0061cd4fc52ebbd1dbccb021903f30570be4980e5fac  v24/cordis/dp3/test_dispose.py
e7243922f1bba25013274dc01910e117066568c26de74a82a34c4f733c9e0c6d  v24/cordis/dp3/test_live.py
4195f6905cce4fc18b5e898f8f06cf239e2c32426a1c11c9b3289f1ea7fa2e0c  v24/cordis/dp3/test_protocol.py
41e0d1a9418b04035b67ff7bfb43ac189f1d2749b16da538254e4218cfbb056d  v24/cordis/dp3/test_teardown.py
b3531acc0121b32f1abfdf53f91d7c98bd56aa3ee003c379bcc8c48bd67f70b3  v24/cordis/dp4/dp4_support.py
76da148cbc8d246f0f9037a49aa6dd32e3cebba1e304761a4573369ed8448dd9  v24/cordis/dp4/README.md
b086bae233e5b9e8f3746797f841c3e6c3f4ea02387b6f06e68ee64af3388e9c  v24/cordis/dp4/test_boundaries.py
49563ff5c5ff4bf37c2092d9dc3a2722c34abde6898c11365ef54e9924bc761e  v24/cordis/dp4/test_closeout.py
a7a4e994f92a72c58e7214ebac21263de66381adf888919c97ebd6c4610fbac6  v24/cordis/dp4/test_loop.py
1ef7971cc7708e5fa14ecb75b66e3d05c184438bf8b193094085de6c79ad5214  v24/cordis/dp4/test_reducer.py
5213c39eda8870262bfd4ee721d60cb1a359bd0479696735ea58acc480129e7b  v24/cordis/dp4/test_run.py
2ac5472b2067e761f771a39639b0ec0a9c60e97c1d0fa94b0010c4ca7350ddc0  v24/cordis/dp5/README.md
e402f74d6f867ec9fe8e708e9c83aa989919b3f8005db7a39ffc77a3acf9f819  v24/cordis/dp5/test_boundaries.py
fcaddc1df468c738c2723a380b131312fffc853e3518d043c0230370029ace0d  v24/cordis/dp5/test_dispatch.py
f06fb035e3dd0c6d173f1a4ff15aee950007fd28b9ed3f68c4ff6ead212564ef  v24/cordis/dp5/test_listeners.py
1ab9e080a1c441416257f674a2c3f81d82fb11327c60e9ba253a1f30f79c2854  v24/cordis/dp5/test_resolution.py
32bb0bca61063d718bd1588d11ce0dbfad01d790817718cf7ac4e68bd1176ec0  v24/cordis/dp6/driver.py
9af33d06640a6abbec5cc800049617996419b0451cb47bf3a77f45437f057793  v24/cordis/dp6/README.md
822da772968451a595be87e68afb744e112d50069e99a5610fbda91163582cd6  v24/cordis/dp6/test_boundaries.py
91eb92f881b70b3de22989f91ebd1e0981238b10349978e1767f7ad6565db672  v24/cordis/dp6/test_dispose.py
10c414fe57a3a82887b81af8a7acd519d558b22b8bb0275404ab26a923b09ca1  v24/cordis/dp6/test_recovery.py
fdf2f927b3767f0c529ae945fa0215ffae7d04739a79872f28213fd8ca6ccc80  v24/cordis/dp6/test_scanner.py
1288c0780050ab3dfcc41773b7bdd6687d0d96ac4597a31e7a24ce7cef813012  v24/cordis/dp6/test_upgrade.py
f7779e557bc4affe68437ee1ce2220cb3b1ae98ee938cf285e5a958b3d9b15d2  v24/cordis/helper_budget.py
6fb4f62c05cac34420e0e15c11640cbfc18a0e99134f635cdb2dffafebe650c1  v24/cordis/load.py
6503aecb1db3825cd3256755d45cbee681eaae5c2fddc338ffee8f1ecfb10707  v24/cordis/sql/00_schema.sql
498efe45a651d95c2b88e3ee9e4134fb15d0c0261a4450117e25d05d206c7df1  v24/cordis/sql/10_installs.sql
d94eb095c25bb680305adbd183568839414ecc1687a89f607d7e3c78d152f06a  v24/cordis/sql/11_scopes.sql
bd9018f2cf0b69655a37338b214a63bea45848dc2f0d45c2782abc243ac38c88  v24/cordis/sql/12_fibers.sql
d10fec2a364faa6e95d024816d8912acb2a357de088cc1f69cf48310e70568f7  v24/cordis/sql/13_episodes.sql
d5c0eb3eda92fd249dcd0bea478a206e46ce02d20c886f8fb57f09d0c81fd393  v24/cordis/sql/14_contributions.sql
d0f776394842d57fe492b5af0fcde1703e483a35dec2d38d6a1f8e74b89d8ff8  v24/cordis/sql/15_pins.sql
2503bc8e4d2b96b6dc2895496a9f5c2716eb4f5e7377befd6413f5395270caa0  v24/cordis/sql/16_runs.sql
d911700448d839b713479d2cb5f052a88bdb8193756ff68588b2b40ce2d8873a  v24/cordis/sql/17_effects.sql
aac4b01231f05f858ce824d6aa4995328f4cb8d6f9772d2aec19a93d46499ebf  v24/cordis/sql/18_events.sql
1ec6d87aa4100d010dc5e23305e4fb6c9463b66e6168f08ac2e684245eb0d260  v24/cordis/sql/19_requests.sql
15c3e90c3d7a8b2735ed0ff25fce528986704a6e1e7da48ce97310900e55131f  v24/cordis/sql/20_relations.sql
f76d3957fefa70ae7082b519045350f8b0d8e2dc503fff6b8965159443b661af  v24/cordis/sql/30_triggers.sql
5da724a46d9da9bbddb1eb2b5afdf9bb5e64bfd068757502f12f5b3dd5514239  v24/cordis/sql/40_advance.sql
9b22a4f98db917fdca18c848ecafb6bc4e952fa17f639019cd49d68dce3c21be  v24/cordis/sql/41_lifecycle.sql
3d16c96e4e0dc4526e96db734ad5e4f7e92351a6a4536453ecbc5ce052cddef2  v24/cordis/sql/42_teardown.sql
ac7eeab71001bdcee4a0bd7cdc349a4047ecadeb04dca40b08e0e1301fcc903f  v24/cordis/sql/43_loop.sql
092736127aa5dac6acdc7f6abfb84ca87b98c02048fd4c0eb115559632770324  v24/cordis/sql/44_events.sql
fa82cc648aa1af24ee84c0eeeaef49abcab22874bad40b6212f48f3099ac6df1  v24/cordis/sql/50_permissions.sql
80a15e056653090fc7f977aad3b27452fe090829c9bcd3067c020034b52bd1d6  v24/host/__init__.py
7d089b0a1e031e8367feb1cb5d37a55a241b652d502d2f1a583c3c29a794fdbd  v24/host/canonical.py
72b9e1dae5dce8b63e05ac079f75f9e55f665081b15863afa027f17b8892de1f  v24/host/db.py
226e1a8cd7c2a36bfc439827f89a8fdb3aca7d62ffcbf65868d3aa026de6e37c  v24/host/deepseek.py
8847af103560fc4fcd2679db25e94718c371b11da23c85beb739eccb1a9725fe  v24/host/descriptor.py
fd359802212da0ac8217aa262f4c5af5f0a10dc5126afc31074d5a950ce6599d  v24/host/journal.py
c0647de7db6a7b043eaf1da3fd0d336cf1399bed4988ced3c753771b8849b6cb  v24/host/line_json.py
0ca9886430c8ce59943a445936be43555c65da229a6ee0397af3b1e50b9f5dd0  v24/host/plugin_smoke.py
49c55e94c8b77b00e43795ef439758bc5ea56c89748b6ae6cb8fba0d7dd8af8a  v24/host/plugins.py
47f1b0d0c821710eec5b97784b23e08f6d7a4c23aba40c9a4456eebc6c1a95df  v24/host/process_io.py
42e1e090217e9364c4b408fc1ded2a90ef4da915ccce257dd4b427d4cf99b8de  v24/host/registry.py
b4d0f8d62ca08c8070f23ac218ce66e5b5d01e71cddb03095c322fd8cbf8c578  v24/host/renderers.py
d56de4f0e82ca43a8606a4ae834afc913b7d421e40f5721d6f997eff827b07a4  v24/host/smoke.py
bb336f8c57db8b00c12d4b9033cccef32ec387579a52e2957268920d4d2ce711  v24/host/tool_pages.py
57cf4c20b3ecbd6f95d33e0871c53b11d771ebfaa147f8c036d504aaae490bf5  v24/host/tool_results.py
ea3fe5af7f3d2c4bde716924803298e450a87ed3db6a143b1fb724352ea7262e  v24/host/tool_schema.py
10bb41b00e84c66afba32e5e7bd845fdde4017d5cdb2c9ba7f538327c4126168  v24/host/worker.py
20156f3c7eb5e8a88dddceb32addd360a3f0a8ac10dbe5a443e18f374912b071  v24/load.py
6dfa217e086e331746e15da193e121a52d11e0df392f9685ccd931ba4bd7459b  v24/s1/fake_host.py
39556df95a4b30b4dce9384d01d84a60a20d987a5eb131fb4b4dc28887ed28f4  v24/s1/README.md
32825fde8f5c4628c65effb1a930b3dc74ba30619afebd4a269fb1545c31e036  v24/s1/setup_db.py
d06b6a6635d85794965c14a6f9a3c271f051856e9aa9ed9251858f6b93888fa1  v24/s1/test_ddl.py
ba390caa6f464f79cb5478427565f9d4c2739025b87c268189408e2e9bc610ae  v24/s1/test_g1.py
a25595bf64d05a649313ba9a48b1e8f1c1c385a365330799be2a126787610ae3  v24/s10/README.md
cf75a3e2711b0560e36ac1dd4a205ce3dbd359358794edf2c7de1f8963188408  v24/s10/test_g9.py
52b4f8829fb5eae230a349f0ba7d2727e062aac5ba1eec21279cc700010a7031  v24/s11/plugin_fixtures.py
58e09e3573e85e8a6abb85cc8da3d0fca87180c6ac1ef2bf5d37b0d1f0206e4f  v24/s11/plugins/echo.js
50fb18ee57d088ce8a866a1d0c3beaa1d3ebcd0bcc27c58502ea8306808c199f  v24/s11/plugins/echo.py
dc9e0e575d3cb2061eff286ae5fefa3d83b2bf8a2d36cae200c4eca484262063  v24/s11/README.md
4b3383dabac238c0d4cbc356aaf78562690ce4c8f88483d829f7ef96e31dc11d  v24/s11/test_g10.py
47878c083dfee9bd66ccca9170238038bda85b2506fa26ba61870704a44daba8  v24/s11/test_node.py
a24d4a4dc2b839ce920b5d9f405c28780264910aa10735517f3d07176b5b1cd4  v24/s12/fair_support.py
1c9a8ca0a8376d428098ddba3cd4dc0c1f22fab49022975e1a959b66e1dfc5f3  v24/s12/README.md
f8a6752f9ac02e9351e917b1385f75bedbdea277a1b13b9a5c700cb79d24855c  v24/s12/test_g11.py
4501e49da944c84984f5b99c9fd2411f65a16cbadafa1cc06090d5e5238025d1  v24/s13/capture_vectors.py
f2b5b84d9539ad9580645cabb15bf92dd169bb6a75b00c2eb1f25f069ac99bf5  v24/s13/fixtures.py
260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c  v24/s13/plugins/fs_read.py
efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5  v24/s13/plugins/fs_tools.js
5b2202decdef60a29cd57369b089e28c7885973c4d35205bf33fa1a674a3b8b8  v24/s13/test_contracts.py
e75f27ecd48f3aedfa8b3c61779fe4253b3f173e9cebf73d64de8bb3f2c412d6  v24/s13/test_descriptor.py
f189a5c83c91f34100e9056718139601bbe6a910fbc84763524c65f4f0df89fc  v24/s13/test_lifecycle.py
b1a8eda548aa4f459db31ab557379175e1fc2f83056d459c9e9d9e56f92a3b8b  v24/s13/test_line_json.py
56170aec7b9df910e0b8ff118c6473e907b035f87d8bd76fbeaed811a03f012a  v24/s13/test_node.py
7212bf8c3d24d3f3764f06b33192c4023de6a313ca3ac1e73b5fc4b95aafb2e3  v24/s13/test_pages.py
f41880296784a9c62f17d4017af701ced15837fac84f19c4a06e504a7598c364  v24/s13/test_registry.py
0eaaacbcba68c7707ef78e24b0dcbde76cacdf2485bb69ccca12ae438b6020d4  v24/s13/test_renderers.py
01d1653ffb4b3a1c5a61d0eaeff1b112027548934c1b80a93c9b413ee0adfe08  v24/s13/test_results.py
dee7cf0453befada0b181b47ea0dd9269981c02f7894f72b2f28bf2ebd9fcc4a  v24/s13/test_schema.py
4df195f18d9583d920e64b1e5a5715d3626b97abdc00ffb0313651879d992d92  v24/s13/test_tools.py
b0590cf0a3a6378d3b1cd308c8190249b6e3454af9035baa5f31c48e0dcc63a0  v24/s13/test_vectors.py
2afe5a9b15f518f93384651fa0973547678d175db91682c2848761c401f25077  v24/s13/test_wiring.py
a9303427169361afd3c593464d203369d45dc2c200d8ec59c0263138c1944232  v24/s13/vectors/descriptor_v2.json
07bf853e82bd11a4e05550bb4edf9ef7b8b4b34f30dd8f9915ecabf357d86d6f  v24/s13/vectors/design_conformance.json
648bc7f937c6abf32f75dae037269f182961fd9e5af224f9bf950c03c40ff2ef  v24/s13/vectors/frames_v2.json
b8328f64e2a110eca36205d12c65e7e9c842163619dc3c5ff350da4f1f817ed4  v24/s13/vectors/manifest_adapter_v2.json
c1d72334de54c049207b6ab5ca66f048c2a50edaf6a1b2eb76d17ccd5334170f  v24/s13/vectors/provider_projection_v2.json
6878f2c93fdbab92a9aa14b97567c8316dbdfda7861803bcffc1ba1b39e9b973  v24/s13/vectors/README.md
a6dd7d625555b1559ec00b30895928e79a2cee3c2d08818bc222fb933eeaf409  v24/s13/vectors/renderers.json
07fad763c9a20bc5a222fdc9b62d9c93da19529870956bf16cb4f4dd4c01e4da  v24/s13/vectors/results_v2.json
91c2aeae799ae6714821d017fbc8ccbd4c75533ce6b9394b2829897673308917  v24/s13/vectors/schema_v2.json
b1084856abf7206733c0282a9ebb39745715533ef0b18409078ca84c4da46922  v24/s13/vectors/tool_contracts.json
8bc8817973435330517a4398e050cffcdc9fb32e4e110e352bf412962b4c613a  v24/s13/w1_reference.js
17b56bfa923847da36d546eba0ac8c85aad68ef7f0668047d57fbc2d9e1c6f0a  v24/s13/w1_reference.py
916ca5b2e997a4ba0386c51b18b0da3663d00772d67497d7753c75d95fa634fa  v24/s13/w4_stub_plugin.py
512abcdd363eb289c313bbb9f421de9098cd486b808fb0f8cdbb52149cae5583  v24/s13/w4b_non_utf8_preload.cjs
64563988dbfe69cc7d61a5907954e247071b8433fe1aac168ee609b4c3531f1b  v24/s13/w7_recover.py
c369807638ad51b3a91f596c12c3f0707cef70db922793cef5ede54b261dafe5  v24/s2/README.md
c93d4746bc20e2a7f46ba6f2b9af3cb1af92aae12c04f1d23a235f5482bd94cb  v24/s2/test_g3a.py
d01bd971b915a174c5c9929b78b2b6d517bcafe5a60646cc01817713f1e3b7ab  v24/s3/README.md
c7749a1de1ed37d4ecd74f99e4085fd68aeee1537137806bb37b41d8f8000d72  v24/s3/test_g2.py
a0bf84e6f66b42ee05c9042d06b189f9e5543f40554d39ef067f0d0e5297be70  v24/s4/fake_llm.py
672d401c6683899e28dd6b3da0c7243018fbc2d85dfbb5f975828be8e84898b7  v24/s4/README.md
f8ee841505b063ae7d8ac8f608847bd3649ba87f30d8007dbb39982a504c0f41  v24/s4/test_g2b.py
b68d461c2b5f0baddd16c7bd6406e68521b77c20a702a56222ec8e271eb12fbb  v24/s5/README.md
bdde1e413e35993b787ea1a2acadb282fb259a1ee14f2afdd9ac7476cc3bbc59  v24/s5/test_g4.py
cca37ad686bef04e3524c9b78043d376817f93f199aa12f1db8577f328cddbe2  v24/s6/crash_worker.py
30ce9b36054f8a69382eee5c13385ec8e70e5e4d02aee87ae39566bb64388295  v24/s6/fake_crash_host.py
5f4971d02ea211d8ebc582abc8f3939658a01756ba0f50876b8089135bb98362  v24/s6/g5_support.py
e4cf7382aaa80ee126eafbc15a04f30e2505fc4067edff1ea0f30c5507afaaef  v24/s6/README.md
fd11df22176b0e4af3c7602468830520934af441cbf2d054ab71cae24dbbc564  v24/s6/recover_worker.py
b1b21c86bc085a2a1d442208fa768f0dffca18f1648b256a147a1facaa81352a  v24/s6/test_g5.py
5a137653a3cbd2f7b3bc437269aac87437472931d8db34c30a554f841d7b5053  v24/s7/g6_support.py
d97fc02b772c5b96a6f30b83517c415094520df3f6eeded21dfb2f4c862cce69  v24/s7/README.md
efaa2990ea97c8c9d3e912bfb85f109412c0844fdada31d4a6f0877e940c92c8  v24/s7/test_g6.py
b75658a09e73caa5540d885ae7fa95bb4d9d829cc09efb161419fbd32160394e  v24/s8/README.md
5d50bb3f6281ee30557481050903eebbcef22bdfc5e4ec9e379dcc239a50211e  v24/s8/test_g7.py
b162f7bbe9330fcd996daacca16eee5c1b992ca7cf0d836d63ca1452853149b2  v24/s9/h_support.py
0a3c64ddb0e4997d287de81b5c93582cb97320bcb18416c18f7e54fcd318551b  v24/s9/README.md
4e235c8478eab54551dd81a55985385d5fab83688b5b6a003dad8bd5741e8438  v24/s9/test_g8.py
05b6b47e0f71881e64fba3c55609c16608e4bc15c44f321ad5a87ede7979bc6d  v24/sql/00_schema.sql
a365a235edefe49258038bef4b28a3cd5f8204ab22a71336e892efc706cbae76  v24/sql/10_schema.sql
1c75ce97c79abdba9151bd8dfd22bb7b1167c10e256ed8fa54d4adf927da5af1  v24/sql/20_triggers.sql
087a5bcdb4b9132e25b2d04bc0a31606d429fba5d5cfbb0a257f0a2440715870  v24/sql/30_advance.sql
2ebefff558f243891a613787a47ef68dcfb825b1bcc16b78f019e328f982c5f9  v24/sql/40_interpreters.sql
f629ddd511754a4828da4b4dc4da278c1a4bfcb2359f15f00fd6634f9e4f332e  v24/sql/45_capability.sql
bb32336bf6e262f62a55a78d55bf3ac7b649c06a50bdda9eda6263f96ed083ef  v24/sql/46_cleanup.sql
5c5bdc611f33f5b37d1652f29aeda97323882487c27cf800ac53371a76ea0265  v24/sql/47_verbs.sql
f23a93cdd5c14966442bf30eb1339b6e110c3b1c279b95650704aa9e12870f30  v24/sql/48_loop.sql
242748a0fe29cbedc723df9d5de18dd1fba7e9767cfce56a3bc218d1a17ce6c4  v24/sql/49_host_reads.sql
b46abde9f5fc4259f9ea833440ca0c0815a4a14a578e058b861f59990d90af8d  v24/sql/49_recovery.sql
578cba9fefc0e0238d6ffd42e458b235bd59ae56a7fa6b1f84a2de36fddbdafe  v24/sql/50_permissions.sql
778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d  docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md
```
