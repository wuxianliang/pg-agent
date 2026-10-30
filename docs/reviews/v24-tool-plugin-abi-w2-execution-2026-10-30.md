# v24 Tool/Plugin ABI W2 execution record

Date: 2026-10-30 (the final serial run started 2026-10-31 00:28 +08:00). Scope: the W2 pure host contract sub-stage defined by [`v24-tool-plugin-abi-w2-host-contracts-2026-10-30.md`](../plans/v24-tool-plugin-abi-w2-host-contracts-2026-10-30.md). This record covers only W2; it does not claim M2 completion or any W3/W4 behavior.

## Result

W2 is implemented and verified. Five pure host modules were added, `registry.py` was reduced to a canonical re-export, four DB-free gates were added, and all 40 W2-domain cases are reproduced by production code. The design §7.1/§7.3/§7.4 revision and conformance repin are complete. A final serial run of the 24 required commands exited 0 for every command, with no exit 2, SKIP or `not_run`.

> The run in this section is the **pre-hardening** candidate. A post-review hardening pass and its separate 24-command run are recorded in “W2 hardening supplement” at the end of this file; do not read this section as evidence for the current working tree.

W2 is extension evidence, not a twelfth closeout item. Closeout remains **11/11**. W3 registry/multi-tool/line-json v2, W4 dispatcher/worker/provider wiring, M3 filesystem tools/artifact digest/12-second timing, and M4 replay/journal behavior remain unverified.

## Provenance

- Checkout: `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD `7097961b991f6750ca82797d0b7f955b909cdc5b`.
- Working-tree status before the run: digest `6bc499fd29827c32e5dbdea3f0e7c43b6e791241d1baa6aa9e53816f5b388f4d` (porcelain-v2).
- Plan source SHA-256: `18b532628ffb4cdf7197fd0725870ffa9aa212b4c7a2339401ee32578ed79a35`.
- Design source SHA-256: `0de115c947967cc92a5e15ec7bf7c53f38abe78bcfcc89f77e06042be1313d04` (repinned; see below).
- Allowlist source manifest: `/tmp/w2-allowlist-sha256.txt`, SHA-256 `221888d4e279de20fdf0b7fde7af4301f6c8410c68cbec9b17ad0fed68b376f6`. It covers the five new modules, `registry.py`, the four new tests, `test_contracts.py`, `design_conformance.json`, the README, the design, ledger, matrix, plan and plan critique. This record is excluded from its own manifest.
- Environment: Darwin arm64; Python 3.12.11; uv 0.8.24; Node v24.13.1; PostgreSQL client 17.11.
- Evidence directory: `/tmp/w2-final-20261031T002828/`, containing `provenance.txt` (SHA-256 `d24593acdff291f480b5622e5c86bc5845e0f5dc5c56e51b0d2c955ed0397b44`), `results.tsv` (SHA-256 `a415e54f6a00bb02fe3b83f5e428bf43ec054095aceb211e48202c60ae94abe6`), per-command logs `01.log`–`24.log`, and `merged.log` (SHA-256 `2b050e16b55c33b02a97d47f78385a4ce52dc27a3975b818324cd9cf56de5851`).
- The run used the credential-clearing prefix `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`. No provider call was made.
- The final run preceded the W2 ledger/matrix sections, the plan Result/status edit, and this record. Those are docs-only changes; no gate reads them. All source/data files in the allowlist were final at run time.

## Implementation

| File | Lines | Responsibility |
|---|---:|---|
| `v24/host/canonical.py` | 217 | PG `jsonb::text`, deep-freeze types, `RegistryError`, compact `J`, `escaped_len`, `strict_loads`; stdlib only. |
| `v24/host/tool_schema.py` | 376 | Closed 13-keyword schema subset, structural bounds, first-error order, path format, reusable compiled closure. |
| `v24/host/renderers.py` | 280 | Three pure renderers, immutable registry, 21 embedded five-key goldens, golden/render digest formulas and pinned digest checks. |
| `v24/host/descriptor.py` | 320 | Strict parse, 17-step descriptor v2 validation, four-reason vocabulary, depth/PG-byte bounds, render identity. |
| `v24/host/tool_results.py` | 266 | Success/failure/unknown envelopes, usage, model-text join, builtin meta, five-domain measurement, frame classification, `ToolDispatchResult`. |
| `v24/host/registry.py` | 250 | Removed seven canonical definitions; re-exports them from `canonical`; `AdapterNotFound` remains local. |

The test files are `test_descriptor.py` (320), `test_schema.py` (210), `test_renderers.py` (238), and `test_results.py` (341). All four are standalone scripts with exit-code semantics.

No runtime host module changed: `plugins.py`, `worker.py`, `line_json.py`, `deepseek.py`, `journal.py`, `db.py`, and `process_io.py` have zero diff. The contract modules import only `canonical`, `tool_schema` and `renderers`; `canonical` imports only stdlib. No production code reads `v24/s13/vectors/*`.

## Coverage

| Gate | W2 cases | Actual last line | Exit |
|---|---:|---|---:|
| `v24/s13/test_descriptor.py` | 16 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | 0 |
| `v24/s13/test_schema.py` | 9 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | 0 |
| `v24/s13/test_renderers.py` | 7 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | 0 |
| `v24/s13/test_results.py` | 8 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | 0 |

- Descriptor: 9 byte cases (6 canonical + 3 complete descriptors) plus 7 table cases. The three render digests are read=`ca52198cf6c2edae798f2340ba4f370f658d422fa05f5d529c28510dea0a680c`, list=`5b0bbe8d0fc70ea68c73baeb01b4df1d6be1a4e31e303dc22e3079605376f9c7`, search=`fd2f51e8c3d7328b0af7ceafcbefc21418f799921e9e470f12b3f7b1b6344011`.
- Schema: 13 allow / 29 deny / 13 invalid-allowed rows; depth 16/17, nodes 256/257, properties 128/129, enum 64/65; first-error and path probes.
- Renderers: 21 inner goldens (read 8 / list 5 / search 8), three manifests, one digest table; every `len(J(content)) == 27 + E(T)`.
- Results: three envelope bytes, three usage rows, two 11-byte model texts, builtin-meta three states, nine cap−1/cap/cap+1 rows, four frame boundaries, and every `prefix_scenarios` candidate content/meta/measures. The three `m4_pending` cases remain `m4_pending` and unexecuted; `page_decision` is not implemented.

## Design revision and conformance repin

- §7.1 adds `canonical.py` and the three new test files, narrows `test_descriptor.py` to descriptor-only, and records the W2 registry extraction plus the W3 registry work separately.
- §7.3 replaces the old broad `test_descriptor.py` row with four gate rows.
- §7.4 adds `test_schema.py`, `test_renderers.py`, and `test_results.py` to the s13 gate block and restates done-when #1 as “W2 covers four of nine s13 gates”.
- The design SHA changed from `976567da3f7a381f488200bfc11b0ce933b3924b2bd9551c50846742081eb951` to `0de115c947967cc92a5e15ec7bf7c53f38abe78bcfcc89f77e06042be1313d04`.
- `v24/s13/test_contracts.py:DESIGN_SHA256` and `v24/s13/vectors/design_conformance.json:design_input.sha256_at_review` were updated in the same change set. `test_contracts.py` and `test_vectors.py` passed immediately afterward.
- Pinned spans after the edits: §7.2 `925–932`→`929–936`, §8.2 `1004–1015`→`1014–1025`, §8.3 `1016–1023`→`1026–1033`, Appendix A `1062–1168`→`1072–1178`. Every span heading and content SHA-256 is unchanged; only line numbers moved.
- The other eight domain vector files and all case IDs, statuses, owners and expected values are unchanged. Only `design_conformance.json` metadata differs among vector files.

## Scope and compatibility audits

- `git diff --exit-code -- v24/sql v24/s10 v24/s11 v24/load.py v24/b0`: exit 0.
- `git diff --exit-code -- v24/host/plugins.py v24/host/worker.py v24/host/line_json.py v24/host/deepseek.py v24/host/journal.py v24/host/db.py v24/host/process_io.py`: exit 0.
- `v24/s13/vectors/`: only `design_conformance.json` is modified; no untracked vector file exists.
- `v24.host.registry` still exports `_FrozenDict`, `_FrozenList`, `_freeze`, `_quote`, `pg_jsonb_text`, `descriptor_digest` and `RegistryError` with the same object identity as `v24.host.canonical`; non-dict `descriptor_digest` still raises `RegistryError`.
- B0 v1 bytes are unchanged in both modes (`byte_cases=29` Python, `byte_cases=34` Python+Node).
- The 11 frozen closeout commands are rows 10–20 of the final table; all exited 0, so closeout remains **11/11**.
- No credential file or key was added. Every Python command ran with the four provider variables unset and `UV_NO_ENV_FILE=1`.

## Final 24-command serial run

Rows 1–4 are the new W2 gates; rows 5–9 are W1/B0; rows 10–20 are the 11 frozen closeout commands; rows 21–24 are G9/G10/Node/multilingual extension checks. All commands exited 0 with their required marker. Times are local `+08:00`.

| # | Started | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T00:28:29+08:00 | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 2 | 2026-10-31T00:28:29+08:00 | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 3 | 2026-10-31T00:28:30+08:00 | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 4 | 2026-10-31T00:28:30+08:00 | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 5 | 2026-10-31T00:28:31+08:00 | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 6 | 2026-10-31T00:28:32+08:00 | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 7 | 2026-10-31T00:28:33+08:00 | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 8 | 2026-10-31T00:28:35+08:00 | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 9 | 2026-10-31T00:28:37+08:00 | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 10 | 2026-10-31T00:28:40+08:00 | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 11 | 2026-10-31T00:28:40+08:00 | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 12 | 2026-10-31T00:28:42+08:00 | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 13 | 2026-10-31T00:28:44+08:00 | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 14 | 2026-10-31T00:28:47+08:00 | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 15 | 2026-10-31T00:28:48+08:00 | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 16 | 2026-10-31T00:28:57+08:00 | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `c3007be35bf12cfae39911fd04c8fc44d957eb9b1c1c1a6ee2678fae14fd5c3e` |
| 17 | 2026-10-31T00:29:02+08:00 | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `d325dd47cdd1276586f9207293473ee8852982cd0c44fd99ae74522ade6032fc` |
| 18 | 2026-10-31T00:29:06+08:00 | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `06e5fd2620fda47309631e384390d6027aa0efd9b0c08a0805d974f0b4602510` |
| 19 | 2026-10-31T00:29:10+08:00 | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `e263da20bfa797c72877a311e6e8f86675c14bf2927850680fc55815e9e3174b` |
| 20 | 2026-10-31T00:29:13+08:00 | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `15093627c9e14283bf76e14c1230dabcd1484a8d13d5d680ae3b86f381712290` |
| 21 | 2026-10-31T00:29:19+08:00 | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 22 | 2026-10-31T00:29:22+08:00 | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 23 | 2026-10-31T00:29:26+08:00 | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 24 | 2026-10-31T00:29:28+08:00 | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `6f3f7061de940669ae48b1e3b58e85ca5e0ab3df3f242c415bf80174778fa041` |

All 24 rows are `passed`; no exit 2, no `[SKIP]`, no `not_run`.

## What W2 does not prove

- It does not prove M2 completion, and it does not prove W3 (`ApprovedTool`/`ApprovedPlugin`/`ToolBinding`/`match_tool`/`environment()`, line-json v2, `plugins.py` v2).
- It does not prove W4 dispatcher/worker/provider wiring, additive `model_text` in `worker._execute_tool`, or `deepseek._tools` accepting v2.
- It does not prove read/list/search filesystem semantics, pagination convergence, the 12-second scan budget, or any subprocess behavior.
- It does not prove replay/`no_replay`, journal replay, second-spawn behavior, or tool-message byte stability (M4).
- The renderer goldens are embedded fixed data; W2 proves the projection functions and digests, not that a live dispatcher invokes them under budget.
- The DB-free W2 gates do not weaken cross-language evidence: PostgreSQL canonical behavior is still covered by the inherited `test_vectors.py`.

Publication follows `AGENTS.md`: path-scoped staging, no `git add -A`, no `--no-verify`, no force push. This record is committed with the W2 milestone.

## W2 hardening supplement (2026-10-31)

> Historical boundary: the run above is the **pre-hardening** candidate (design SHA `0de115c9…`). It is retained unchanged and does not cover the post-review working tree. This supplement records a separate serial run of the same 24 commands over the hardened candidate (design SHA `2606aedc…`). No result above is retroactively extended.

### What changed

A three-lane Oracle review of the W2 code raised four contract gaps and one coverage gap; the hardening pass fixes them and records two further boundary clarifications:

- `canonical.strict_loads`: integer literals are rejected as `unsafe_integer` by digit count before `int()`, so Python's 4300-digit conversion cap can no longer leak a bare `ValueError`.
- `canonical.compact_json`: `J` now encodes with an explicit stack. Finite deep JSON is accepted instead of being rejected at Python's recursion limit; cyclic containers raise `circular_reference`. Byte output is unchanged (all 71 vectors, 21 renderer goldens and three digests still match).
- `descriptor.parse_descriptor`: every decoder/lexical failure, including `RecursionError` from deep nesting, normalizes to `invalid_descriptor`.
- `tool_results`: success `value` and content/meta are checked against the `J` domain; `frame_bytes`/`measure` normalize `CanonicalError` and `RecursionError` to `invalid_tool_output`; `ToolDispatchResult` validates the outer `{status,output,usage}`, class/status agreement, usage and the class-specific envelope.
- `renderers`: any exception raised by `fn`, including `RendererError`, reclassifies to `render_failed`; non-`J` content/meta is `invalid_tool_content`; the renderer gate checks production `measure` on all 21 goldens.
- `tool_schema`: a schema with `properties` or `required` is object-shaped even without `type`, so it must declare `additionalProperties`; bare `{}` remains any-JSON.

Design §3.1, §5.2, §5.3, §5.4 and §5.5 are pinned spans, so the normative clarifications were appended as **Appendix C** rather than edited in place. Four §7.3 test-matrix rows were rewritten with net-zero line count. The design SHA changed `0de115c9…` → `2606aedc7135e7085219d0a9c99d1ccca5c22ee33baee6a82dd6f137ce7cac24`; every pinned span heading, line range and content SHA was re-verified unchanged, and only `design_conformance.json` metadata differs among the eight domain vector files. `DESIGN_SHA256` and `design_conformance.json.design_input.sha256_at_review` were repinned atomically.

### Provenance

- Checkout: `/Users/wxl/Projects/pg-agent`; branch `main`; HEAD `070de34b57117cd2b910bf33deaa71176d51ed9f`.
- Working-tree status: digest `957e00554306953c5bfdb6a49687b658fb99a12a04426cdcffaedeaa1c18067f` (porcelain-v2); tracked diff SHA-256 `f42394ef76ebc1234239925bac436d23eb3bf2a664fbb55937a4f6efd6017101`.
- Design source SHA-256: `2606aedc7135e7085219d0a9c99d1ccca5c22ee33baee6a82dd6f137ce7cac24`.
- Plan source SHA-256 at run start: `69cf9ef64ec41e86d371f0867512a1781bdbd9b1c5fd2fbeccce4b9604450312` (final at run start; only this record, the ledger and the matrix were edited afterwards).
- Allowlist source manifest: `/tmp/w2-hardening-20261031/allowlist-sha256.txt`, SHA-256 `f664b10c46bd6dc82292215f5fa0afbff5db3f42ae7b42f4375817f9fb54c7cb`. It covers five production modules, four gates, `test_contracts.py`, `design_conformance.json`, the design and the README. This record, the plan, the ledger and the matrix are excluded from it.
- Environment: Darwin arm64; Python 3.12.11; uv 0.8.24; Node v24.13.1; PostgreSQL client 17.11.
- Evidence directory: `/tmp/w2-hardening-20261031/`, containing `provenance.txt` (SHA-256 `5f82620a9c49e8590ac5e51c4aa19148d24809015172cf7d5867b048c30753df`), `results.tsv` (SHA-256 `3febaf0ba49daf7272afff7c6c9c4b58ea7af1681b9f27da2375330287df667a`), per-command logs `01.log`–`24.log`, and `merged.log` (SHA-256 `ad05d4bbb19e54dbed7da3dcf83b904b799719447b2d06fb4653468efadf7b04`).
- Every command ran under `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`. No provider call was made.

### Line counts after hardening

| File | Lines | File | Lines |
|---|---:|---|---:|
| `v24/host/canonical.py` | 264 | `v24/s13/test_descriptor.py` | 329 |
| `v24/host/tool_schema.py` | 383 | `v24/s13/test_schema.py` | 232 |
| `v24/host/renderers.py` | 288 | `v24/s13/test_renderers.py` | 254 |
| `v24/host/descriptor.py` | 322 | `v24/s13/test_results.py` | 415 |
| `v24/host/tool_results.py` | 297 | | |

Case counts and markers are unchanged: descriptor 16, schema 9, renderers 7 (21 inner goldens), results 8.

### Final 24-command serial run (hardened candidate)

Times are UTC. Rows 1–4 are the four W2 gates; rows 5–9 are W1/B0; rows 10–20 are the 11 frozen closeout commands; rows 21–24 are G9/G10/Node/multilingual extension checks.

| # | Started | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-30T17:19:41Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 2 | 2026-10-30T17:19:41Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 3 | 2026-10-30T17:19:42Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 4 | 2026-10-30T17:19:43Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 5 | 2026-10-30T17:19:43Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 6 | 2026-10-30T17:19:44Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 7 | 2026-10-30T17:19:46Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 8 | 2026-10-30T17:19:47Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 9 | 2026-10-30T17:19:49Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 10 | 2026-10-30T17:19:52Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 11 | 2026-10-30T17:19:52Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 12 | 2026-10-30T17:19:54Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 13 | 2026-10-30T17:19:55Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 14 | 2026-10-30T17:19:58Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 15 | 2026-10-30T17:20:00Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 16 | 2026-10-30T17:20:09Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `2bab1a021670bb91cc4d2456bea52387774d8010a69163a6769e46f26fbbf3b3` |
| 17 | 2026-10-30T17:20:13Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `bfa9992772f864c6b3037ac5b295f75a682150edc7d34d4772b5f585870f48a5` |
| 18 | 2026-10-30T17:20:17Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `a5603747bda7990790a864b8eb64e5159018a07fc3610d5df18c27a888c8cb14` |
| 19 | 2026-10-30T17:20:21Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `185aec6ab28114f82618ab145ed55c1538629af789db1840a523f621a2a887bb` |
| 20 | 2026-10-30T17:20:24Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `e7d0f73c7b7f2c896886f5d6196b1c4a9200acc94542e56361b3646e4d6db5c6` |
| 21 | 2026-10-30T17:20:30Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 22 | 2026-10-30T17:20:33Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 23 | 2026-10-30T17:20:36Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 24 | 2026-10-30T17:20:38Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `df75f50043feeec307777eadb18cd9634b9f633a0f8029780b6ca9925eba61f5` |

All 24 rows exited 0; no exit 2, no `[SKIP]`, no `not_run`.

### Scope audits

- `git diff --exit-code -- v24/sql v24/s10 v24/s11 v24/load.py v24/b0`: exit 0.
- `git diff --exit-code -- v24/host/plugins.py v24/host/worker.py v24/host/line_json.py v24/host/deepseek.py v24/host/journal.py v24/host/db.py v24/host/process_io.py`: exit 0.
- `git status --porcelain -- v24/s13/vectors`: only `design_conformance.json` is modified; no untracked vector file.
- `v24.host.registry` re-exports `_FrozenDict`, `_FrozenList`, `_freeze`, `_quote`, `pg_jsonb_text`, `descriptor_digest` and `RegistryError` with the same object identity as `v24.host.canonical`; `grep -rn 's13/vectors' v24/host` has zero hits.
- B0 v1 bytes are unchanged in both modes (29 Python, 34 Python+Node); all 71 W1 cases and all 21 renderer goldens still match.

### Additional boundary not proved

- The W3 frame parser must still decide how a syntactically valid success frame whose `value` leaves the `J` domain (for example `1.5` under `output_schema={}`) is classified. Appendix C.2 fixes the intended contract (ordinary `invalid_tool_output` failure, not unknown), but W2 does not implement frame parsing and does not prove it.
- `ToolDispatchResult` is a v2-only container; W2 does not wire it into `worker._execute_tool`, and it does not prove the v1 path stays on the 2-tuple/`{class,result}` return shapes.
