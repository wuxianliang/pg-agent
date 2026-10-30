# v24 Tool/Plugin ABI W1 execution record

Date: 2026-10-30. The initial handoff below is preserved as history. The final execution section records completed W1 vectors, reference checks, and inherited regression evidence; publication follows the repository commit/push sequence.

## Candidate and source provenance

- Primary checkout (read-only): `/Users/wxl/Projects/pg-agent`; branch `main`, upstream `origin/main`, HEAD `f990b1df0470dcc0a31a3975518caa8b69474176`.
- Candidate: `/Users/wxl/Projects/.repoprompt-worktrees/pg-agent/rp-worktree-v24-abi-w1-vectors-4fb67a3f-4fb67a3f`; branch `v24-abi-w1-vectors`, no upstream; HEAD `f990b1df0470dcc0a31a3975518caa8b69474176`; RepoPrompt worktree ID `wt_faf56fea41cf3d68e6e12ac6b0566d97176bec3fc3019e2731979897a97434e0`.
- The RepoPrompt binding and shell `pwd`/`git rev-parse --show-toplevel` both resolved to the candidate path before mutations. No stash, reset, fetch, checkout or primary mutation was performed.
- Primary was dirty before work. Its complete porcelain-v2 status, unstaged binary patch, empty staged patch and input hashes are preserved outside the repository under `/tmp/v24-abi-w1-evidence-20261030/`. The primary was not edited.
- Explicitly imported from primary into candidate: ABI design `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`, source SHA-256 `bdfe65dcd7f1a445671d9754fd99d2642edfee516b35c9f17ba84c7c15d90c70`; W1 plan `docs/plans/v24-tool-plugin-abi-w1-cross-language-vectors-2026-10-30.md`, source SHA-256 `0ae6e4125ed54607b3a5b0c0bcf24c540c3c72b9de60659c808edd4fd82ea622`. Both candidate copies matched these hashes immediately after import. `AGENTS.md` was read from primary, SHA-256 `6a8e6683e1f5346772215a53fea3f458529b46375a29803ee31d28066f3dfc5a`; it was not imported because the candidate already carries the repository instructions supplied for this task.
- No other primary source input was imported. Candidate source snapshot is the committed tree at the base commit. Its sorted SHA-256 manifest covers 1,261 tracked files and is `/tmp/v24-abi-w1-evidence-20261030/candidate-source-sha256-sorted.txt`, SHA-256 `f08313541bb33b42a3086cd65f8ed1c79a2c9177d53bec70259484e25f4e9ed6`.

## Environment and retained evidence

Environment: Darwin 25.6.0 arm64; Python 3.14.6; uv 0.8.24; Node v24.13.1; PostgreSQL client 17.11; Git 2.49.0. `DEEPSEEK_API_KEY` was present in the primary shell; no value was read or recorded. No provider command was run. Full version/environment output is preserved in `/tmp/v24-abi-w1-evidence-20261030/environment.txt` (SHA-256 `1e1f40eb07e7a2797b4e8c6be8834a7cd819b34b7a58703030dec66b306449b5`).

External evidence files and SHA-256:

- `primary-status-initial.txt` and `primary-status-final.txt`: both `a3fe021615b8251d0e07696e569df2b404b085a4eeee7aa1e86e637b918248f7`; `cmp` confirmed the primary porcelain status is unchanged.
- `candidate-status-initial.txt`: `229107ff348132342f6a7486d325521d233c34182cb825b09882a3130a3f1579`
- `candidate-status-final.txt`: `d659f8c4b8ba03647232ca634e70794316579f4c170b298007b903d59e3aa5ca`
- `w1-source-sha256-sorted.txt` (the five design/plan/README/inventory deliverables, excluding this self-referential record): `de08173200ddc2c43841c6087e5d7d371930ac106654bfd0520f04383629fed4`
- `primary-unstaged-initial.patch`: `ed167efed915d4971e14839d11a7307bfe9b3c287776248be56ee7c3355c2197`
- `primary-staged-initial.patch` (empty): `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `primary-input-sha256.txt`: `ea74e2681b3e341ce87451ff4ee0a988d5a5433a82ada20d4a07ebfb5806562f`

## Initial handoff work-item result

- W1-0: complete. Candidate binding, physical location, base, branch, primary dirty state, exact inputs, environment, full status and sorted tracked-source hashes are recorded.
- W1-1: complete as design contract. ABI design §0.4 and the plan record Q1–Q5, request/response framing, vector location, ordering, confidence and overturn evidence. STOP-R is `design_resolved` for the static design proof only.
- W1-2: complete as inventory only. Format `v24-tool-plugin-abi-w1-vectors-1`, fixed required suite/case IDs, byte/table shapes, status/owner vocabularies, design map and B0 boundary are in `v24/s13/vectors/`.
- W1-5: design resolution recorded. No code, vector payload, or gate is implied.

## Initial handoff commands and actual results

| Command/action | Result |
|---|---|
| RepoPrompt `manage_worktree show @current` | Candidate path/ID/branch/base matched the requested binding. |
| `pwd`; `git rev-parse --show-toplevel`; `git status --short --branch`; `git rev-parse HEAD` in candidate | Exit 0; physical root matched requested path; clean base branch before imports. |
| Primary `git status --short --branch`; source `shasum -a 256`; plan and AGENTS reads | Exit 0; primary dirty paths were observed and left unchanged. |
| Explicit copy of ABI design and W1 plan; candidate SHA check | Exit 0; each imported SHA matched its primary source SHA. |
| `python3 -m json.tool v24/s13/vectors/design_conformance.json` | Exit 0; inventory JSON parsed successfully. |
| Inventory assertion script | Exit 0; 10 suites, 71 unique required case IDs, 2 reviewed design decisions; status/owner/stage vocabularies valid and production/gate claims false. |
| Final primary status comparison | Exit 0; initial and final porcelain-v2 status snapshots byte-identical (SHA-256 above). |
| `git diff --check` | Exit 0. Candidate additions are untracked, listed by final `git status`; no tracked production path diff exists. |

No W1/B0/inherited gate, vector capture, PostgreSQL query, Node reference, Python reference, provider call, or tool subprocess was run. There are no passing test or gate claims. Later W1 work must complete W1-3/4/6/7/8/9 and the plan's complete serial gate run before milestone publication. User directed not to commit/push during this split work item; no commit or push was attempted.

## Initial scope audit at handoff

Candidate changes are limited to the explicitly imported ABI design and W1 plan, the new `v24/s13/README.md`, `v24/s13/vectors/README.md`, `v24/s13/vectors/design_conformance.json`, and this execution record. No `v24/host/**`, `v24/sql/**`, `v24/s10/**`, `v24/s11/**`, `v24/load.py`, B0 assets, or unrelated primary edits were changed. Later agents may add the remaining W1 allowlisted vectors/reference/checkers and final closeout artifacts; do not describe this handoff as W1 complete.

## Final W1 implementation and review

W1-3/4/6/7/8/9 are complete. The implementation contains independent Python/Node test references, guarded external capture, 71 fixed outer case IDs in 10 suites, and read-only vector/contract checkers. The schema and filesystem fixtures are declarations; no M2 schema validator or real read/list/search tool was implemented or executed. All tools' first production verification stage is M3. Suite states now describe downstream M2/M3/M4 verification rather than unfinished W1 generation. Renderer digests remain provisional W2-pending.

The final reviewed design SHA-256 is `976567da3f7a381f488200bfc11b0ce933b3924b2bd9551c50846742081eb951`. Each suite pins its exact design headings, line spans, and span SHA; `test_contracts.py` independently pins all required IDs and the design SHA. Checks reject stale design input, missing/extra/duplicate IDs, invalid labels, inconsistent bytes, broken cross-file links, impossible tool-page relations, or over-budget successful tool fixtures.

Python, Node, and PostgreSQL directly match nine fixed canonical descriptor byte cases. Python and Node also reproduce request frames, response classifications, renderer outputs, renderer golden/manifest digests, model text, semantic budgets and all finalized Q5 prefix scenarios. Q5 probes include exact cap−1/cap/cap+1 byte boundaries, all-prefix selection without a monotonicity assumption, footer removal, cursor/decimal-width/safe-integer edges, source errors, semantic contradictions, and scan cutoff. Meta stays separate from model text; absent/empty normalization and nonempty built-in meta rejection are explicit. B0 bytes remain unchanged.

The three reviewed provisional render digests are read=`ca52198cf6c2edae798f2340ba4f370f658d422fa05f5d529c28510dea0a680c`, list=`5b0bbe8d0fc70ea68c73baeb01b4df1d6be1a4e31e303dc22e3079605376f9c7`, search=`fd2f51e8c3d7328b0af7ceafcbefc21418f799921e9e470f12b3f7b1b6344011`. M2 must reproduce them; plugin artifact digest and 12-second timing stay M3-pending; replay stays M4-pending.

Prior Oracle review was completed before this continuation. The remaining recommendations were implemented and spot-checked: concrete fixture outcomes, independent inventory pins, direct byte comparisons, complete closed-object probes, invalid allowed-keyword examples, renderer/counter parity, and exact design-span linkage. No new Oracle review was needed after those corrections.

### Capture and promotion

Earlier candidate directories and their failure/review history are preserved. Semantic candidates `-o/-p` matched; status-only `-q/-r` candidates matched without changing expected bytes. Final audit found contradictory `.git` skip prose and an offset2 read fixture that still used offset1. The design now consistently excludes `.git` without incrementing hidden; the read fixture contains an invalid second line and actually requests offset2. These concrete corrections were reviewed, the design SHA/span hashes were repinned, and final candidates `/tmp/v24-w1-candidate-s` and `-t` matched byte-for-byte before promotion. Inputs and expected bytes unrelated to those fixture corrections were preserved. No checker writes expected data or provides a re-bless option.

Final capture file SHA-256:

| File | SHA-256 |
|---|---|
| `descriptor_v2.json` | `a9303427169361afd3c593464d203369d45dc2c200d8ec59c0263138c1944232` |
| `design_conformance.json` | `6464656812d34f99263d29259e4de38961c6c29ecdc78c69e8a6385d787c923a` |
| `frames_v2.json` | `648bc7f937c6abf32f75dae037269f182961fd9e5af224f9bf950c03c40ff2ef` |
| `manifest_adapter_v2.json` | `b8328f64e2a110eca36205d12c65e7e9c842163619dc3c5ff350da4f1f817ed4` |
| `provider_projection_v2.json` | `c1d72334de54c049207b6ab5ca66f048c2a50edaf6a1b2eb76d17ccd5334170f` |
| `renderers.json` | `a6dd7d625555b1559ec00b30895928e79a2cee3c2d08818bc222fb933eeaf409` |
| `results_v2.json` | `07fad763c9a20bc5a222fdc9b62d9c93da19529870956bf16cb4f4dd4c01e4da` |
| `schema_v2.json` | `91c2aeae799ae6714821d017fbc8ccbd4c75533ce6b9394b2829897673308917` |
| `tool_contracts.json` | `b1084856abf7206733c0282a9ebb39745715533ef0b18409078ca84c4da46922` |

### Final serial gate evidence

The table below records the complete serial run at 2026-10-30 11:15 UTC. All commands used the credential-clearing prefix `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`; each exited 0 and emitted its required pass marker, with no exit2/SKIP. The 11 frozen closeout commands are rows 6–16; rows 1–5 and 17–20 are extension checks.

After the capture-script whitespace correction, the same 20 commands were run serially again at 2026-10-30 11:19–11:20 UTC. All 20 exited 0 with status `passed`, no SKIP, and base source SHA `f990b1df0470dcc0a31a3975518caa8b69474176`. The tested source-manifest SHA-256 / candidate fingerprint is `cf202a6aa7b328dc2acc8e7ad9766ff4108c4899ea3f2df6e6155dd3b9061253`; the manifest is `/tmp/v24-w1-commit-evidence-20261030/source-sha256.txt`. All current source/data hashes match that manifest except this execution record, whose latest-evidence paragraph was necessarily updated afterward. Full latest commands, timestamps, exits, pass markers, per-log hashes and statuses are recorded in `/tmp/v24-w1-commit-evidence-20261030/commands.json`, SHA-256 `ec63b694e340f9a407ccdf326bed59ecfe11abcb81ea2ec62bfd0473dea07873`. Its logs are `/tmp/v24-w1-commit-evidence-20261030/01.log` through `20.log`. The older table below is retained as a separate fully passing run; the latest JSON is the authoritative evidence for the commit candidate.

For the earlier run, the tested source-manifest SHA-256 was `4b6c196306ff8fca62fdfdfb533496f862c32fab95605fa5394caf91bce6a59e`; its sorted source manifest and command metadata remain under `/tmp/v24-w1-release-evidence-20261030/`. Earlier successful runs at `/tmp/v24-w1-final-evidence-20261030/` and `/tmp/v24-w1-final-status-evidence-20261030/` are preserved.

| # | Started (UTC) | Command (prefix above) | Exit/status | Actual last line | Merged-log SHA-256 |
|---|---|---|---|---|---|
| 1 | 2026-10-30T11:15:50.380350+00:00 | `uv run python v24/s13/test_contracts.py` | 0 / passed | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 2 | 2026-10-30T11:15:50.910312+00:00 | `uv run python v24/s13/test_vectors.py` | 0 / passed | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 3 | 2026-10-30T11:15:52.716799+00:00 | `uv run python v24/s13/test_vectors.py --node` | 0 / passed | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 4 | 2026-10-30T11:15:54.665267+00:00 | `uv run python v24/b0/test_golden.py` | 0 / passed | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 5 | 2026-10-30T11:15:56.606926+00:00 | `uv run python v24/b0/test_golden.py --node` | 0 / passed | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 6 | 2026-10-30T11:15:58.703003+00:00 | `uv run python v24/load.py` | 0 / passed | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 7 | 2026-10-30T11:15:59.213053+00:00 | `uv run python v24/s1/setup_db.py --self-check` | 0 / passed | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 8 | 2026-10-30T11:16:00.775029+00:00 | `uv run python v24/s1/test_ddl.py` | 0 / passed | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 9 | 2026-10-30T11:16:02.341630+00:00 | `uv run python v24/s1/test_g1.py` | 0 / passed | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 10 | 2026-10-30T11:16:04.806201+00:00 | `uv run python v24/s2/test_g3a.py` | 0 / passed | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 11 | 2026-10-30T11:16:06.621173+00:00 | `uv run python v24/s3/test_g2.py` | 0 / passed | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 12 | 2026-10-30T11:16:11.754946+00:00 | `uv run python v24/s4/test_g2b.py` | 0 / passed | `[passed] v24 S4 W1-W6` | `0744115b9edb8d16f0bda88e0741b3f3893328dc4b5bedaf9354f502e9e474a3` |
| 13 | 2026-10-30T11:16:15.924481+00:00 | `uv run python v24/s5/test_g4.py` | 0 / passed | `[passed] v24 S5 W1-W4` | `2e3b7cd2bf4195493342cd1d3ab693f4e4cb31e92783ef229e9d7cdf99bdcd09` |
| 14 | 2026-10-30T11:16:19.330718+00:00 | `uv run python v24/s6/test_g5.py` | 0 / passed | `[passed] v24 S6 W1-W4` | `4a6c2e4ae70a41197ca9cb69c65402384fa482bdee534fe6c3ed3ded11ea29ee` |
| 15 | 2026-10-30T11:16:23.203516+00:00 | `uv run python v24/s8/test_g7.py` | 0 / passed | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `3d765c682a8a07108de952024a04698f0bf68851a3aa509576c99b8292caabc2` |
| 16 | 2026-10-30T11:16:25.602000+00:00 | `uv run python v24/s7/test_g6.py` | 0 / passed | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `30cb58d858a0be0a5e52e1e39cb3615e0237df483bc6fec9e7269e1c085f1b3d` |
| 17 | 2026-10-30T11:16:31.920402+00:00 | `uv run python v24/s10/test_g9.py` | 0 / passed | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 18 | 2026-10-30T11:16:34.945707+00:00 | `uv run python v24/s11/test_g10.py` | 0 / passed | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 19 | 2026-10-30T11:16:38.123674+00:00 | `uv run python v24/s11/test_node.py --node` | 0 / passed | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 20 | 2026-10-30T11:16:40.114802+00:00 | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 / passed | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `6d11c56050de4f769718ddb751f0f3ba8bf439a1b67c934a9e768d21f7e13043` |

### Final scope and publication audit

- `git diff f990b1df0470dcc0a31a3975518caa8b69474176 --exit-code -- v24/host v24/sql v24/s10 v24/s11 v24/load.py v24/b0` exited 0. No new SQL or SQL load entry exists. B0 checker, vectors and probe are unchanged.
- Candidate changes are restricted to `v24/s13/**`, the imported ABI design and W1 plan, this execution record, and W1-only appended sections in the candidate matrix/ledger. Primary dirty files were not copied into these review documents.
- All source/data files were inspected and scanned for private keys, API-key/token patterns and credential filenames. No credential file or secret was found in the W1 allowlist. API credentials were removed for every test; no real provider was called.
- The initial split-item no-publication instruction is historical. The resumed full-plan task authorizes completing the milestone. Commit uses explicit path staging and normal hooks; no force/reset/stash or hook bypass is permitted.
- Remote discovery three times failed (including an HTTP/1.1 retry) before authentication with `LibreSSL SSL_connect: SSL_ERROR_SYSCALL` to `github.com:443`. No remote write occurred during these discovery attempts. The concrete tested candidate will be committed and an append-only `HEAD:main` push attempted, preserving the dirty local primary checkout and its local `main` ref. That ref cannot be advanced inside the dirty primary merely to spell the plan's illustrative `git push origin main` command. Git's non-force push remains the remote ancestry check. A failed push leaves W1-10 incomplete and will be reported explicitly.
