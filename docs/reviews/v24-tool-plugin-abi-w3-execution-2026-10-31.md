# v24 Tool/Plugin ABI W3 execution record

Date: 2026-10-31 (+08:00). Scope: the registry/transport sub-stage in [W3 plan](../plans/v24-tool-plugin-abi-w3-registry-transport-2026-10-31.md), specifically W3-6 evidence/documentation and W3-7 publication of the existing W3-1…W3-5 candidate. This record does not claim M2 completion.

## Result

The required 26 commands ran serially in the specified order and all exited 0 with their command-specific `[passed]` last line. No exit 2, `[SKIP]`, missing pass marker or `not_run` occurred. The two W3 markers were exactly:

```text
[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14
[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true
```

Rows 12–22 below are the 11 frozen closeout commands. Closeout remains **11/11**; W3 is extension evidence, not a twelfth closeout item. Inherited Node and multilingual checks passed; that does not establish W3 Node behavior. No real provider call was made. The authoritative run is the post-review sweep starting 2026-10-31T03:25:04+08:00.

## Candidate and provenance

- Checkout: `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `e2a13349b894078a8127942f39d866f9dbb7cfb1`.
- Original candidate before closeout documentation: tracked changes in `registry.py`, `line_json.py`, the design, `test_contracts.py` and `design_conformance.json`; untracked W3 gates, plan and critique. Unrelated `.ctx-export-*`, `.token-probe*`, `ctx_export_check*` and `v20/experiments/ce_native_d5/` remained outside the publication allowlist.
- Full `git status --porcelain=v2` is in provenance; SHA-256 `b9fa69ffc1d4702a5cc28761595f5de256e36a14221420d12fbc32aa3172468f`.
- Environment: uv `0.8.24 (252f88733 2025-10-07)`; Python `3.12.11`; Node `v24.13.1`. Each version command exited 0.
- Evidence directory: `/tmp/w3-20261031T032503/`. It contains `provenance.txt`, sorted `source-sha256.txt`, redacted `credential-scan.txt`, `span-identity.tsv`, `01.log`–`26.log`, `results.tsv`, `merged.log`, `scope-audit.tsv` and four scope logs.
- `source-sha256.txt` inventories all tracked files under `v24` plus the candidate/documentation allowlist; SHA-256 `1a8be039b293e5330282a47fd215910e3020fc443666f2435a647df3d29a36bf`. The complete inventory is also embedded in provenance. The inventory includes this record as it stood before the final sweep; subsequent evidence refreshes are documentation-only and separately inventoried before publication.
- `provenance.txt` SHA-256: `2865dd813cc38a4d61d58da8e304323babb84db269c0beab597e7c28af9aae91`.
- `results.tsv` SHA-256: `ec088daf2e62d321c2988d198643ed49a9b1d3edf6ed5a9b6ebe3246dd8202ba`.
- `merged.log` SHA-256: `bb8997ee2ea932a3de834f277c4fa45b535aafe83b5890b0c99e20f81086295b`.
- `span-identity.tsv` SHA-256: `b0897d597cc65294e74b64b06ba579fbd0a4c4a9da46b6ecc604c406f5c84311`.
- `credential-scan.txt` SHA-256: `60474c032b60871795a69daaf72bbf5355fc7c025522a30805ca20264a055155`. The scan covered 13 candidate/docs files and checked private keys, provider keys, GitHub tokens, AWS access keys and quoted literal credentials; no pattern matched. It does not dump environment values.
- The final sweep followed the review fixes. Production source, gates, design and vector data were final at sweep start. README/ledger/matrix/plan Result and this record were refreshed afterwards to identify the final run. Documentation is recorded separately from tested-source identity.

Every command used exactly this prefix:

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

The runner redirected each producer to its own log, then immediately captured `rc=$?`; no tail or pipeline supplied the exit status. The TSV stores the expanded full command, start time at `+08:00`, producer exit code, actual last line and SHA-256 of the log. The merged log preserves the same command identity and raw output. A nonzero exit or missing required marker would have stopped the run before subsequent commands and publication.

## Implementation and coverage

Production changes are confined to `v24/host/registry.py` and `v24/host/line_json.py`. Registry adds the fieldless shared mixin, `ApprovedTool`, `ToolBinding`, `ApprovedPlugin.from_manifest()`, adapter declaration digest, union indexing, `match_tool()` and the v2 `match_pin()` rejection. Transport adds independent v2 request construction and classification, per-tool process specification, and static protocol routing. The dispatcher itself is unchanged.

| Gate | Measured coverage | Boundary |
|---|---|---|
| `v24/s13/test_registry.py` | 17 cases; three manifest byte cases; six zero-spawn match paths; all 14 construction reasons | Approved v1 retains 17 fields; v1 schema closures stay `None`; v2 closures belong to `ApprovedTool`; manifest artifact digest is caller-supplied. |
| `v24/s13/test_line_json.py` | 10 cases; five request + two response byte cases; 46 invalid + nine whitespace parse rows; five preflight rejections; four unknown outcomes | Process results are stubbed; v1 bytes/classification and the public adapter keyword remain covered; float/unsafe-int success values classify as `bad_frame`. |

The frozen 4745 B manifest reproduces `0ad584415af8743045dd12275a54fa2f43a65395fc8669753416688c9c3e3db5`. Registry matches `list` and `search` to distinct approved tools. The added noncanonical bytes and equivalent UTF-8 str probes preserve raw manifest identity and differ from the canonical dict digest; dict input uses `compact_json`. New construction tokens cover new v2 decisions only; existing `_hex64`, digest mismatch and process/artifact validation prose remains intact. Frozen frame cases retain `m2_pending`; the five-field artifact case retains `m3_pending`.

W2 regression markers remain descriptor 16, schema 9, renderers 7/21 inner goldens/three digest pairs, and results 8. W1 remains 10 suites/71 cases and nine PostgreSQL/Python canonical comparisons. B0 checks retain 29 Python and 34 Python+Node byte cases with six structural cases. Those measured facts do not extend W3's proof boundary.

## Design revision and append-only span proof

Old design SHA-256:

`2606aedc7135e7085219d0a9c99d1ccca5c22ee33baee6a82dd6f137ce7cac24`

New design SHA-256:

`269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0`

The old design bytes are an exact prefix of the new design. All changes append C.7–C.10 after the existing C.6; no existing source line moved or changed. C.7 resolves `double_lf` to `extra_frame` under frozen-vector authority. C.8 supersedes C.2's unreachable transport `J` failure mapping. C.9 owns schema closures and the bounded 14-token vocabulary. C.10 clarifies §7 stage boundaries, manifest byte semantics and evidence requirements.

**Deviation from the plan's in-place wording:** D4/W3-5/File-by-file proposed §4.1/§7 edits. The clarifications were appended as C.9/C.10 to preserve line-anchored pinned-span identity. `test_contracts.py` changes only `DESIGN_SHA256`; `design_conformance.json` changes only `design_input.sha256_at_review`. There is no relaxed assertion, span re-bless or vector-status promotion.

The proof compared every baseline/current `design_sections` object for exact equality, recomputed the current line slice SHA, and checked its first line against the pinned heading. There are **25 suite references to 23 unique spans** (the §5.4 and §8.2 references repeat); every line range, heading and content SHA is identical. Full per-reference hashes are preserved in `span-identity.tsv` and remain in the unchanged vector metadata. The unique ranges are:

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

## Scope and compatibility audits

These are the plan's four exact audit commands, executed after command 26:

| Audit command | Exit | Actual result |
|---|---:|---|
| `git diff --exit-code -- v24/sql` | 0 | Empty output. |
| `git diff --exit-code -- v24/host/plugins.py v24/host/worker.py v24/host/deepseek.py v24/host/journal.py v24/host/db.py v24/host/process_io.py` | 0 | Empty output. |
| `git diff --exit-code -- v24/host/canonical.py v24/host/descriptor.py v24/host/tool_schema.py v24/host/renderers.py v24/host/tool_results.py` | 0 | Empty output. |
| `git diff --stat -- v24/s13/vectors` | 0 | Only `design_conformance.json`: 2 +−; one file changed, one insertion, one deletion. |

`scope-audit.tsv` SHA-256 is `9dcf02b036c9bf1dba72014b119bcd49d9fcccc3ab969c4aff91c1cb21b5002e`. A separate name/status check confirmed only `design_conformance.json` changed and no untracked vector file exists. No SQL was added; loader/SQL load order is unchanged.

Risk #9 remains material: unchanged `plugins.py` passes `lookup_install()` results directly to `line_json.run()` in `_resource`/`_inspect`, so an approved v2 entry automatically selects v2 frames there. `_tool` still calls `match_pin()` and fails closed with `protocol_mismatch` for v2. This is existing coupling, not a W3 dispatcher change or evidence that v2 dispatcher integration is complete. The ledger records it as `D-ABI-W3-7`; appendix placement is `D-ABI-W3-8`.

## Final 26-command serial run

All commands below are prefixed by the exact `$ENVPFX` expansion shown above. `results.tsv` and `merged.log` contain each fully expanded command. Start times are `+08:00`. Rows 1–2 are W3; 3–6 W2; 7–11 W1/B0; 12–22 closeout; 23–26 G9/G10/Node/multilingual.

| # | Started (+08:00) | Command after ENVPFX | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T03:25:04+08:00 | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 2 | 2026-10-31T03:25:05+08:00 | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 3 | 2026-10-31T03:25:06+08:00 | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T03:25:06+08:00 | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T03:25:07+08:00 | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T03:25:08+08:00 | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T03:25:08+08:00 | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 8 | 2026-10-31T03:25:09+08:00 | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 9 | 2026-10-31T03:25:11+08:00 | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 10 | 2026-10-31T03:25:13+08:00 | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 11 | 2026-10-31T03:25:15+08:00 | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 12 | 2026-10-31T03:25:17+08:00 | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 13 | 2026-10-31T03:25:18+08:00 | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 14 | 2026-10-31T03:25:19+08:00 | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 15 | 2026-10-31T03:25:21+08:00 | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 16 | 2026-10-31T03:25:24+08:00 | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 17 | 2026-10-31T03:25:26+08:00 | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 18 | 2026-10-31T03:25:34+08:00 | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `0e47b6cf4ceb60e9bf2fbe14eb432d18745d4099ef16decc75eae54469f725a2` |
| 19 | 2026-10-31T03:25:38+08:00 | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `a3a4bc3f8fae0883833cf64792084d97aa02a09759ba8cdd92edf1b67ca16320` |
| 20 | 2026-10-31T03:25:42+08:00 | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `f676acdf1a9050f2f41c82ce5ca718455240a468be9a5539ab69a6aea293ebd3` |
| 21 | 2026-10-31T03:25:46+08:00 | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `dd0342d17595b9fd9304a9b72527feb5c12df685b6423887f3faaea952a4e3f7` |
| 22 | 2026-10-31T03:25:49+08:00 | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `1834c6620c0f0ee2686bf08e747f26de2fb503e0e9a93b4304605219c58f7859` |
| 23 | 2026-10-31T03:25:55+08:00 | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 24 | 2026-10-31T03:25:58+08:00 | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 25 | 2026-10-31T03:26:01+08:00 | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 26 | 2026-10-31T03:26:03+08:00 | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `8fac2e01d3103b0a5d121b71df5cc9cf8927bb01ea21b6befadcf19f10c235ad` |

All 26 rows are passed. The log hashes above identify this run, not an earlier W2 or W3 invocation.

## What W3 does not prove

- M2 completion, `plugins.py` v2 dispatcher behavior, `worker.py` additive `model_text`, or `deepseek._tools` accepting v2.
- The filesystem semantics, pagination convergence or 12-second budget owned by `test_tools.py`/`test_lifecycle.py`/`test_node.py` and later tool stages.
- Real v2 subprocess lifecycle, mixed-batch barriers, crash/restart, second spawn, replay/`no_replay`, journal-only replay or tool-message byte stability. The two new gates use process stubs; inherited v1 subprocess checks are not v2 lifecycle evidence.
- Artifact digest computation (M3), or renderer execution under budget in a live dispatcher. Supplied digest shapes and pure renderer goldens do not establish those claims.
- Any W3 Node-side implementation or behavior. Passing inherited Node/vector/multilingual commands preserves existing evidence only.

No provider call was made. Closeout remains **11/11**; s13 is extension evidence.

## Review corrections and evidence boundary

**Oracle reconciliation** — all three lanes completed after one failed artifact-delivery attempt was retried with an explicit UTF-8 attachment. The failed attempt supplied no substantive code review. The completed review did not rerun gates; findings were checked locally before acting. The table inventories its material claims, including single-lane and conflicting findings. The verdict differences (approve-with-fixes versus request-changes) were resolved by fixing the substantiated gaps and executing a fresh full sweep, without a further review round.

| Finding | Source lanes | Checked evidence | Disposition |
|---|---|---|---|
| Initial review lacked files; review package was not assessable | 1/2/3, first attempt | Retry attachment contained sources/diff/evidence; all lanes confirmed receipt | accepted — delivery failure resolved by explicit attachment. |
| Temporary evidence should be published durably | 2, first attempt | User explicitly requires external `/tmp` logs plus committed execution record/hashes | rejected — retain requested evidence placement; no extra publication requirement. |
| Record table, span proof, appendix-only diff, pin edits, audit results, counts and 13-path publication boundary agree | 1/2/3 | Local table/log SHA comparison, baseline span comparison and scope audits | accepted — independently checked locally. |
| Required noncanonical bytes probe was absent and ledger overclaimed coverage | 1/2/3 | Initial registry gate only supplied dict manifests | accepted — case 3 now passes noncanonical bytes and equivalent UTF-8 str, checks raw SHA differs from canonical SHA and tools remain equal. |
| Positive closure recompile claim actually tested plugin-level retention | 3 | Initial case 17a retained nested tool closure identity | accepted — case 17 now separately rebuilds `ApprovedTool`, proves both closure identities change, and checks valid/invalid args/output; plugin retention is labeled separately. |
| Renaming `run(adapter=...)` to `entry` breaks v1 keyword callers | 1/2 | Baseline public signature versus candidate; no existing in-repo keyword caller was established | accepted — restore the `adapter` name and exercise v1 transport through keyword calls; inherited positional B0 callers still pass. |
| Plan step 9 retained the withdrawn post-decode `J` failure branch | 1/2/3 | D14/C.8 and production strict decoder contradict that sentence | accepted — remove it; strict-load failures are `bad_frame` and no post-decode `J` branch exists. |
| Plan overstates token coverage, provides-count reasons and key-validation location | 1 | D12/C.9, `from_manifest` and registry gate | accepted — bound the reason table to new decision points, distinguish direct/from-manifest count errors and locate key checks at descriptor validation. |
| Row #10 timeout-cap description is inaccurate | 1 | The reviewed report gave no specific discrepancy; row #10 and production both distinguish cap range and tool-over-cap | rejected — no change to the valid timeout-cap contract. |
| `CanonicalError` may escape `from_manifest` | 1 | `canonical.py` defines `CanonicalError(ValueError)` and `strict_loads(str | bytes)`; constructor catches `ValueError` | rejected — proposed exception gap is not present. |
| `from_manifest` is not entirely filesystem-free | 2 | `cls(...)` performs cwd/workspace `isdir`/`realpath`; no artifact bytes read | accepted — correct component wording to distinguish metadata from artifact contents. |
| Plan line anchors are stale | 1 | Unchanged pinned ranges in span proof | accepted — align §2.3/§2.4/§5.1 citations with full pinned ranges. |
| Credential scan predates final documentation | 1 | Per-run provenance is a snapshot, not a final staged scan | accepted — W3-7 separately rescans all 13 staged blobs and checks exact path allowlist. |
| Local absolute checkout/user paths could be redacted | 1 | User requested local evidence/provenance; W2 style also includes concrete paths | rejected — preserve intentional source/evidence identity. |
| Registry module/match-pin explanatory docstrings were removed | 1 | Baseline/current diff confirms removed explanatory text; no executable behavior involved | accepted — nonblocking documentation loss in user-supplied W3-1…5 candidate; no additional production edit for it. |

The first complete sweep at `/tmp/w3-20261031T030237/` passed 26/26 for the pre-review candidate, but does not establish the corrected gate/source identity. It is retained as historical evidence only. After the three probe/compatibility fixes, a second complete 26-command sweep was required and is the authoritative run in the table above. No gate was weakened, no marker count changed and no vector was re-blessed. Only `line_json.py` and the two existing W3 gates required source changes; no W4 file changed. Final documentation now distinguishes measured raw-byte/closure/keyword probes from implementation assertions.

## Publication

This record and the README, ledger, matrix and plan Result are documentation updates after the measured sweep. Publication uses exactly the 13 candidate paths specified by the user, normal hooks, commit message `v24: add W3 registry approval model and line-json v2 transport`, and non-force `git push origin main`. It excludes unrelated context/probe/experiment files. The committed record identifies the tested base and evidence; the resulting commit/push outcome is recorded separately in external publication evidence and reported after execution, avoiding a self-referential commit hash in this file.
