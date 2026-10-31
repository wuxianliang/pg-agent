# v24 Tool/Plugin ABI W4a execution record

Date: 2026-10-31 (+08:00). Scope: W4a dispatcher/worker/provider wiring in [W4 plan](../plans/v24-tool-plugin-abi-w4-dispatcher-worker-wiring-2026-10-31.md), corresponding to design §10 M2. This record does not claim M3 or M4.

## Result

The required 29 serial commands ran in the specified order and all exited 0. Rows 1–28 carry their command-specific `[passed]` last line; row 29 is the plan's explicit `git diff --exit-code c8c4bd0 -- v24/sql` scope check with empty output, for which no `[passed]` marker applies. No exit 2, `[SKIP]`, missing pass marker or `not_run` occurred. The two W4a markers were exactly:

```text
[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true
[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true
```

Rows 14–24 are the 11 frozen closeout commands. Closeout remains **11/11**; W4a is extension evidence and s13 is not a twelfth closeout item. **M2 is complete** after this run. That statement does **not** mean real filesystem tools, pagination convergence, mixed batch, crash/restart, replay, or the 12-second budget are verified. No real provider call was made and no socket was opened by the W4a gates.

## Candidate and provenance

- Checkout: `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `c8c4bd09acf87ff3338477c8e18d4933df64d87c`.
- The authoritative sweep started 2026-10-31T02:59:06Z and ended at the last row's start 2026-10-31T03:00:40Z. The six scope audits ran 2026-10-31T03:00:51Z–03:00:53Z.
- Candidate paths: `v24/host/{tool_pages,plugins,worker,deepseek,registry}.py`, `v24/s13/{test_pages,test_wiring,w4_stub_plugin}.py`, `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`, `v24/s13/test_contracts.py`, `v24/s13/vectors/design_conformance.json`, the W4 plan, this record, the matrix/ledger, and `v24/s13/README.md`.
- Full `git status --porcelain=v2` is preserved in `git-status-porcelain.txt`; SHA-256 `e863280f64baafcd59d563118d995ba2f078998ca513a5aee468bdacf336d0b2`.
- Environment: uv `0.8.24 (252f88733 2025-10-07)`; Python `3.12.11`; Node `v24.13.1`. Each version command exited 0.
- Evidence directory: `/tmp/w4a-20261031T025906/`. It contains `provenance.txt`, `git-status-porcelain.txt`, `source-sha256.txt`, redacted `credential-scan.txt`, `01.log`–`29.log`, `results.tsv`, `merged.log`, `scope-audit.tsv`, and six `scope-*.log` files.
- `provenance.txt` SHA-256: `f45bc69a7d1a7598803de79fbb8543951b94375df0085b817ca0dc82b7a2715a`.
- `results.tsv` SHA-256: `e5db88c91bcf774f5dd383fc3d7a54fad8ffc0a1eabbb93b400e2ccde3d3c35e`.
- `merged.log` SHA-256: `666b2e69abbd542a863ac37190d0f846aae44974f315ed4e3cdb8e76d2eed943`.
- `scope-audit.tsv` SHA-256: `8d2eaaa786c55059f49b955f006d96d29056816a09dfca0f5c52eefcb7d68102`.
- `source-sha256.txt` SHA-256: `a11429b0de0ade5b968208261862e7503c061002fe634c3a9f05a47d6b9f733d`; `credential-scan.txt` SHA-256: `83e87de2d6b97200b19879b75b409543750d36d57ef64ddb2715e73b3b5a52c7`.
- A pre-sweep candidate at `/tmp/w4a-20261031T025653/` stopped at command 25 because G9-A asserted the v1 hashed provider name. It is retained as historical evidence only and does not establish the final candidate; the fix is described under deviations.

Every command used exactly this prefix:

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

The runner redirected each producer to its own log, then immediately captured `rc=$?`; no tail or pipeline supplied the exit status. The TSV stores the expanded command, UTC start time, exit code, actual last line and SHA-256 of the log. The merged log preserves the same command identity and raw output. A nonzero exit or missing required marker would have stopped the run before subsequent commands and publication.

## Implementation and coverage

| Area | Measured coverage | Boundary |
|---|---|---|
| `tool_pages.py` | 3 contracts; 5417 page cases; 4281 `validate_page` ⇔ `page_error` differentials on output-schema-valid values; unknown id/version/digest rejected; import-direction child asserts no oracle import | Two documented reference gaps are one-sided: empty read with offset>1 and negative `skipped`. `w1_reference.py` was not changed. |
| `plugins._tool_v2` | Thirteen-step order; v2 envelope guard for `match_tool`/preflight; fixed host messages; `InstanceError` path/rule with `/etc/passwd` degradation tested by the `invalid_tool_arguments` path probe; six zero-spawn categories (args, schema, five artifact reasons, workspace, lease, four match failures) | No real filesystem tool. Pre-spawn rejections may still have `dispatch_started`; zero spawn is proven by process count, not journal. |
| `worker._execute_tool` / `_call_tool_handler` | 2-tuple, `{class,result}`, `{class,result,model_text}`; non-str model_text TypeError; `tool_handler=None` and raising-handler branches; dispatch payload key set unchanged; v1 fallback equals `canonical_json(output)` | No replay/restart; those remain W4c. |
| `deepseek._tools` | Frozen 482/550/796 B projection cases and SHA values; safe-name mapping; two key-mismatch rows; `{"v":2,"tool":{}}` still `descriptor_invalid`; four B0 v1 request lengths/SHAs | v2-only `name:key`; v1 keeps `_safe_name` hash suffix, so B0/G9 v1 bytes are unchanged. |
| `registry.environment()` | Exact +5/−1 patch; root injected from the registry value, host value ignored; v1 adapter has no injection; allowlist missing the name gets no root | Conditional by design; v2 fixtures must opt in. |
| `w4_stub_plugin.py` | 11 scenarios; one-line frames; `--spawn-log <abs>`; prepare/release/inspect plus invoke; no filesystem semantics | Test asset only, not M3. |
| End-to-end v2 | One real prepare + invoke lifecycle per scenario; 11-byte `one\n二\n三` model text and journal consistency; meta exclusion; v1 resource receipt on a v2 frame; per-tool 5000/15000/entry timeout; 19999 ms lease spy | No mixed batch, crash/restart, replay, Node, or real provider. |

## Design revision and append-only span proof

Old design SHA-256:

`269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0`

New design SHA-256:

`15afb72dfb8f4f274d36b1722ad3b50501388abbe2a6a0d0ce6e6eeba12f7800`

The old design bytes are an exact prefix of the new design; all changes append C.11–C.16 after C.10. No existing source line moved or changed. C.11 maps W labels to M stages and supersedes the old §7.4 #1 wording; C.12 owns `tool_pages`/root injection; C.13 owns the thirteen steps, host messages and v2 provider name mapping; C.14 owns `dispatch_started` and process-count zero spawn; C.15 rewrites the §7.4 W labels; C.16 bounds the 12-second proof.

The proof compared every baseline/current `design_sections` object for exact equality, recomputed the current line slice SHA, and checked its first line against the pinned heading. There are **25 suite references to 23 unique spans**; every line range, heading and content SHA is identical. The unique ranges are:

| Ref | Unchanged line range | Ref | Unchanged line range |
|---|---|---|---|
| §2.3 | 163–199 | §2.4 | 200–221 |
| §3.1 | 224–286 | §3.2 | 287–339 |
| §3.3 | 340–408 | §4.2 | 481–495 |
| §4.3 | 496–519 | §4.4 | 520–528 |
| §5.1 | 531–591 | §5.2 | 592–657 |
| §5.3 | 658–687 | §5.3.1 | 688–703 |
| §5.4 | 704–727 | §5.5 | 728–764 |
| §5.6 | 765–787 | §6.1 | 790–801 |
| §6.2 | 802–826 | §6.3 | 827–879 |
| §6.4 | 880–887 | §7.2 | 929–936 |
| §8.2 | 1014–1025 | §8.3 | 1026–1033 |
| Appendix A | 1072–1178 | | |

`test_contracts.py` changes only `DESIGN_SHA256`; `v24/s13/vectors/design_conformance.json` changes only `design_input.sha256_at_review`. There is no span re-bless and no vector case/status/expected-value change.

## Scope and compatibility audits

All audits are explicitly pinned to `c8c4bd0`; no bare `git diff` decided a result. The sixth check is the explicit SQL diff, also command 29.

| Check | Exit | Actual result |
|---|---:|---|
| frozen modules + no untracked frozen dirs | 0 | `[scope] passed frozen_modules_and_untracked` |
| vectors except design metadata | 0 | `[scope] passed vectors_except_design_conformance` |
| design restore after SHA substitution | 0 | `[scope] passed design_conformance_restore old=269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0 new=15afb72dfb8f4f274d36b1722ad3b50501388abbe2a6a0d0ce6e6eeba12f7800` |
| registry exact D12 patch | 0 | `[scope] passed registry_exact_patch plus=5 minus=1` |
| host import purity | 0 | `[scope] passed host_import_purity` |
| SQL zero diff | 0 | `[scope] passed sql_zero_diff` |

`test_wiring.py` runs the same six-check audit at its end and prints `[scope] passed base=c8c4bd0 checks=6`. The registry audit uses `git show c8c4bd0:v24/host/registry.py` plus the exact D12 replacement and `cmp`-equivalent byte equality; because the original `return` spans two lines and the second line is unchanged context, the audit uses `git diff -U1` to assert one hunk, one deletion and five additions. This is a faithful +5/−1 patch, not a relaxation.

## Final 29-command serial run

All commands below are prefixed by the exact `$ENVPFX` expansion shown above. Start times are UTC.

| # | Started (UTC) | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T02:59:06Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-10-31T02:59:35Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-10-31T02:59:39Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T02:59:40Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T02:59:40Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T02:59:41Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T02:59:41Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-10-31T02:59:42Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-10-31T02:59:43Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-10-31T02:59:43Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-10-31T02:59:45Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-10-31T02:59:47Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-10-31T02:59:49Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-10-31T02:59:51Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-31T02:59:52Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-31T02:59:53Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-31T02:59:55Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-31T02:59:58Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-31T03:00:00Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-31T03:00:08Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `4b92bd6b26708adaf07e9da600aae85fbded5b3fcd835688155de60cad6458c1` |
| 21 | 2026-10-31T03:00:13Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `5dbc3096260c7efb5f2eefa32e15534a32cd1f9a0dc57d62760b6d27cee5116e` |
| 22 | 2026-10-31T03:00:17Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `63d300afce5a4591dd71d0db995d50c4d734af5f7ebee8325b9c2e59e7a73b33` |
| 23 | 2026-10-31T03:00:21Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `2d2e7ff10c036516104a3bd9c0da14e8c1c0d42fef80b9491676ad7c625e0828` |
| 24 | 2026-10-31T03:00:23Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `4bae708a0201293572c8acece48666ba082c9552a2a7f2980d634ed4e42598f6` |
| 25 | 2026-10-31T03:00:30Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-10-31T03:00:33Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-10-31T03:00:36Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-10-31T03:00:38Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `0d82cd791fd0bbf490d9968a8c60fb9ae6a2de202875ecd1677fd560e5ff6bb8` |
| 29 | 2026-10-31T03:00:40Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | `<empty>` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Deviations, limits and unresolved assumptions

- D-ABI-W4-1…6 are recorded in the [deviation ledger](v24-deviation-ledger-2026-10-23.md). They cover the v1-shaped pre-`lookup_install` boundary, `match_tool` before args, `dispatch_started` on pre-spawn rejection, transport-valid 60001..65536 frames, conditional root injection, and the new `tool_pages` module.
- **v2-only provider name mapping (plan/code reconciliation):** design §6.4 and `provider_projection_v2` require `name` = `read/list/search`; current v1 `_safe_name` always appends a hash and G9-A/B0 freeze that v1 behavior. The final implementation keeps `_safe_name` for v1 and uses the approved key for safe v2 keys in the v2 branch only. The first sweep at `/tmp/w4a-20261031T025653/` failed at G9-A after a global `_safe_name` change; that attempt was reverted and the final 29-command sweep is authoritative.
- **Unresolved assumption (a), W4b input:** `ApprovedAdapterRegistry.__init__` accepts `ApprovedAdapter | ApprovedPlugin`, so `build_registry` can carry an `ApprovedPlugin` if one is supplied. However `PluginSpec.entry` is typed `ApprovedAdapter`, and `build_spec`/`build_adapter` only construct v1 entries with a single `tool_key`/`descriptor`. Conclusion: s13 `fixtures.py` must build its own v2 registry; `v24/s11/**` stays zero-diff.
- **Unresolved assumption (b), lease:** an empirical harness run wrapped `HostWorker._execute_tool` and recorded the effect. The effect contained `lease_until` (e.g. `2026-10-31T10:45:07.946255+08:00`), `status=claimed`, `kind=tool_call`. The implementation reads that field directly; there is no `db.host_effect(effect_id)` fallback branch. A missing/non-string `lease_until` fails closed as `lease_insufficient`.
- **Unresolved assumption (c), env:** `v24/s13/test_line_json.py` still defines `env_names = ("PATH", "HOME", "V24_W3_UNSET_TEST_VARIABLE")` at line 118 (the plan's 171–178 anchor is the later `expected_env` computation). D12's condition leaves those v1/v2 ProcessSpec assertions unchanged.
- Limitations: no real provider, no network socket, no real filesystem tool, no Node v2 tool, no mixed batch, no crash/restart, no journal replay, no second-spawn proof, no pagination convergence, no 12-second wall-clock gate, no SQL/kernel change, no `HostWorker.lease_ok` wiring, and no change to `default_lease_ms` (30000) or `replay_class`.
- No frozen vector status was promoted. `results_v2` m2 cases remain `m2_pending`; `provider_projection_v2` cases remain `provisional_w2_pending`.

## Publication

This record, the README, matrix, ledger and plan Result are documentation updates after the measured sweep. Publication uses exactly the candidate paths in the plan/user list, normal hooks (no `--no-verify`), commit message `v24: wire v2 dispatcher, worker model_text and provider projection`, and non-force `git push origin main`. It excludes the unrelated `.ctx-export-*`, `.token-probe*`, `ctx_export_check*` and `v20/experiments/ce_native_d5/` files. The committed record identifies the tested base and evidence; the resulting commit/push outcome is reported separately after execution, avoiding a self-referential commit hash in this file.
