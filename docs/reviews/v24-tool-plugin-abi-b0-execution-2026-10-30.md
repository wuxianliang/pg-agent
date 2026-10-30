# v24 Tool/Plugin ABI B0 execution record — source snapshot + B0-2

Date: 2026-10-30. Final acceptance record: B0-1 through B0-7. Earlier fixture failures and corrections are retained below; the final serial runbook and audit are appended after them.

## Worktree identity

- Candidate: `/Users/wxl/Projects/.repoprompt-worktrees/pg-agent/rp-agent-61bc0d9e-b0-abi-baseline-20261030-1f584100`
- Worktree ID: `wt_8003f4b4446906b84d30b6adc2bc00c2b8229859fa85d0f1c616232ac58656f1`
- Candidate branch: `b0-abi-baseline-20261030`
- Candidate HEAD: `a4b7dba5e945af03d04f4145103ddaaff2ee18ec`
- Candidate upstream: none configured (isolated branch).
- Candidate initial status before edits: clean; host/sql/s10/s11/load baseline tracked at HEAD. Original source `v24/host/**`, `v24/sql/**`, `v24/s11/**`, `v24/load.py` are clean. Original `v24/s10/README.md` is modified, so the candidate uses the committed HEAD copy (no source dirty hunk imported).
- At initial B0-2 snapshot, the only candidate additions were the explicitly copied plan, this execution record, and `v24/b0/test_multi_provides.py`; subsequent B0 assets and closeout records are itemized below.

## Original checkout snapshot (read-only)

- Path: `/Users/wxl/Projects/pg-agent`
- HEAD: `a4b7dba5e945af03d04f4145103ddaaff2ee18ec`
- Branch/upstream: `main` / `origin/main`
- Remote: `https://github.com/wuxianliang/pg-agent.git`
- Tracked changes: 11; untracked entries: 126.
- Host/SQL focused status is clean. The only focused v24 dirty path is `v24/s10/README.md`; the modified README and dirty docs/matrix/ledger are deliberately excluded from candidate source.
- Original plan SHA-256: `4af6d7507522511477d29842ded1c54e44654e009b4aae128026e7cccc43a52d`
- External ABI design SHA-256 (read-only, not copied): `c9ba39a99daf08715cb51e6c8587c54983463b265b9cd66f4f855c57164469ce`
- Original AGENTS.md SHA-256: `6a8e6683e1f5346772215a53fea3f458529b46375a29803ee31d28066f3dfc5a`
- Environment snapshot from original checkout command: macOS `Darwin 25.6.0 arm64`; Python `3.14.6`; uv `0.11.26`; PostgreSQL client `17.11`; Node `v23.11.0`. Candidate shell: Python `3.14.6`; uv `0.8.24`; PostgreSQL client `17.11`; Node `v24.13.1`. The gate ran under uv-managed Python `3.12.11`. DuckDB CLI: not available. `DEEPSEEK_API_KEY` was present in the original shell environment; its value is not recorded and was cleared for the gate command.

### Full original porcelain v2 status captured before edits

```text
# branch.oid a4b7dba5e945af03d04f4145103ddaaff2ee18ec
# branch.head main
# branch.upstream origin/main
# branch.ab +0 -0
1 .M N... 100644 100644 100644 be6d18c3bcb4f736bd83e43cb65e92446811f08f be6d18c3bcb4f736bd83e43cb65e92446811f08f docs/designs/v24-db-native-agent-system-2026-10-22.md
1 .M N... 100644 100644 100644 c4d676d7b36dbf984ce4df5fa83570e9dbdbae65 c4d676d7b36dbf984ce4df5fa83570e9dbdbae65 docs/designs/v24-pg-agent-2026-10-22.md
1 .M N... 100644 100644 100644 011d49839f03cfc52cfc825c243da3a207eb9cb4 011d49839f03cfc52cfc825c243da3a207eb9cb4 docs/plans/v24-s4-agent-loop-2026-10-24.md
1 .M N... 100644 100644 100644 c64a454ba5f5c4b9613578fac6b3776c0471c3f2 c64a454ba5f5c4b9613578fac6b3776c0471c3f2 docs/reviews/v20-deviation-ledger-2026-10-14.md
1 .M N... 100644 100644 100644 4b540eb74497bc6521a1986ea78dfa1b49417ee8 4b540eb74497bc6521a1986ea78dfa1b49417ee8 docs/reviews/v24-conformance-matrix-2026-10-23.md
1 .M N... 100644 100644 100644 59bd3938db9f06d4cc3bd7ff08c0d8cce4365ce9 59bd3938db9f06d4cc3bd7ff08c0d8cce4365ce9 docs/reviews/v24-deviation-ledger-2026-10-23.md
1 .M N... 100644 100644 100644 6d277cbfe5c6f47421d97a404e761bb7290fab18 6d277cbfe5c6f47421d97a404e761bb7290fab18 v20/alpha/README.md
1 .M N... 100644 100644 100644 222e2b5125462ec74d2bee376e293a22245b5d10 222e2b5125462ec74d2bee376e293a22245b5d10 v20/alpha/host.py
1 .M N... 100644 100644 100644 5ec778fa2a27198aaed77145731e4fddbf17838c 5ec778fa2a27198aaed77145731e4fddbf17838c v20/alpha/setup_db.py
1 .M N... 100644 100644 100644 f0ec7cc4f9fd3d98778956cc3bb42013198599e6 f0ec7cc4f9fd3d98778956cc3bb42013198599e6 v20/alpha/tools.py
1 .M N... 100644 100644 100644 0414afc79c3573a7972e4d7b31c178d81c10cab9 0414afc79c3573a7972e4d7b31c178d81c10cab9 v24/s10/README.md
? .ctx-export-v13-discover-2.txt
? .ctx-export-v13-discover.txt
? .token-probe-2.txt
? .token-probe.txt
? ctx_export_check.txt
? ctx_export_check2.txt
? ctx_export_check3.txt
? docs/designs/v13.1-workbench-plane.md
? docs/designs/v20-ce-native-design-5-2026-10-13.md
? docs/designs/v20-runtime-charter-draft-2026-10-12.md
? docs/designs/v20-three-layer-implementation-reference-2026-10-13.md
? docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md
? docs/investigations/ce-first-class-structures-v20-2026-10-13.md
? docs/investigations/ce-v20-as-executor-2026-10-13.md
? docs/investigations/cordis-vs-pg-cordis-design-2026-10-21.md
? docs/investigations/deepseek-harness-design-vs-v24-2026-10-29.md
? docs/investigations/jev-engineering-overall-design-impact-2026-09-22.md
? docs/investigations/r0a-file-plane-v3-design-points-2026-09-30.md
? docs/investigations/repoprompt-ce-swift-tool-migration-strategy-2026-09-27.md
? docs/investigations/v13-dev-structure-drift-2026-10-09.md
? docs/investigations/v13-dp9-mgraph-demo-trial-2026-09-24.md
? docs/investigations/v13-dp9-mgraph-v2-demo-rerun-2026-09-24.md
? docs/investigations/v13-long-loop-workflow-borrowing-gap-2026-09-28.md
? docs/investigations/v13-m3-stop-why-and-how-to-advance-2026-09-25.md
? docs/investigations/v13-mgraph-v2-candidates-contradiction-investigation-2026-09-24.md
? docs/investigations/v13-mgraph-v2-cjk-routing-investigation-2026-09-24.md
? docs/investigations/v13-multilang-tool-call-test-2026-09-23.md
? docs/investigations/v13-runtime-nonconvergence-2026-10-11.md
? docs/investigations/v13-s1-s2-e-i-four-step-survey-2026-10-06.md
? docs/investigations/v13-stage41-d3-stage42-deadlock-2026-10-08.md
? docs/investigations/v13-tool-authoring-simplification-2026-09-23.md
? docs/investigations/v14-pi-parity-gap-investigation-2026-09-28.md
? docs/investigations/v17-design-impl-tests-2026-10-07.md
? docs/investigations/v24-drift-factcheck-2026-10-29.md
? docs/investigations/v24-plugin-vs-agent-sequencing-brief-2026-10-29.md
? docs/investigations/v24-tool-plugin-abi-design-brief-2026-10-29.md
? "docs/investigations/\346\234\254\345\234\260\345\216\237\347\224\237Agent\347\263\273\347\273\237\346\236\266\346\236\204\350\260\203\347\240\224\346\212\245\345\221\212.md"
? docs/paper/A_Programming_Paradigm_for_Spatiotemporal_Composability_2114250287861366784.md
? "docs/plans/pg-agent-v13.1-\350\256\276\350\256\241\346\226\271\346\241\210.md"
? docs/plans/v13-controller-thin-cut-2026-10-09.md
? docs/plans/v13-dp10-multilang-tools-plan-2026-09-23.md
? docs/plans/v13-native-wait-poll-steer-2026-10-09.md
? docs/plans/v13-stage40-agentctl-observe-2026-10-08.md
? docs/plans/v13-stage41-agentctl-verbs-2026-10-08.md
? docs/plans/v13-stage42-goal-workflow-2026-10-08.md
? docs/plans/v13-stage43-external-exec-2026-10-09.md
? docs/plans/v13-stage44-ce-map-2026-10-09.md
? docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md
? docs/plans/v24-tool-plugin-abi-b0-baseline-2026-10-30.md
? docs/reviews/v13-controller-thin-cut-plan-critique-2026-10-10.md
? docs/reviews/v13-dp10-plan-critique-2026-09-23.md
? docs/reviews/v13-dp2-dp3-debt-closure-l4-2026-09-22.md
? docs/reviews/v13-dp2-fix-dp3-impl-l4-review-2026-09-22.md
? docs/reviews/v13-dp2-impl-l4-review-2026-09-22.md
? docs/reviews/v13-dp4-impl-l4-review-2026-09-22.md
? docs/reviews/v13-dp5-impl-l4-review-2026-09-22.md
? docs/reviews/v13-dp6-impl-l4-review-2026-09-22.md
? docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md
? docs/reviews/v13-dp7-impl-l4-review-2026-09-23.md
? docs/reviews/v13-dp8-impl-l4-review-2026-09-23.md
? docs/reviews/v13-minimal-agent-loop-demo-plan-critique-2026-09-23.md
? docs/reviews/v13-native-read-tools-plan-critique-2026-09-27.md
? docs/reviews/v13-stage40-agentctl-observe-plan-critique-2026-10-08.md
? docs/reviews/v13-stage41-agentctl-verbs-plan-critique-2026-10-08.md
? docs/reviews/v13-stage42-goal-workflow-plan-critique-2026-10-08.md
? docs/reviews/v13-stage43-external-exec-plan-critique-2026-10-09.md
? docs/reviews/v13-stage44-ce-map-plan-critique-2026-10-09.md
? docs/reviews/v13-tool-ports-spec-plan-critique-2026-09-27.md
? docs/reviews/v13-unattended-continuation-plan-critique-2026-10-01.md
? docs/reviews/v20-alpha-plan-critique-2026-10-14.md
? docs/reviews/v23-minimal-agent-loop-plan-critique-2026-10-10.md
? docs/reviews/v24-post-closeout-followup-plan-critique-2026-10-25.md
? docs/reviews/v24-tool-plugin-abi-b0-baseline-plan-critique-2026-10-30.md
? docs/tutorials/v13/how_to_make_a_tool_for_v13.md
? v20/alpha/drive.py
? v20/alpha/provider.py
? v20/alpha/read_file.py
? v20/alpha/test_run.py
? v20/experiments/ce_facades/BRIEF.md
? v20/experiments/ce_facades/report.json
? v20/experiments/ce_facades/run_experiment.py
? v20/experiments/ce_facades/scenario.py
? v20/experiments/ce_facades/session_object.py
? v20/experiments/ce_facades/substrate.py
? v20/experiments/ce_facades/test_experiment.py
? v20/experiments/ce_facades/thin_adapter.py
? v20/experiments/ce_facades/unloadable_profile.py
? v20/experiments/ce_facades/workflow_container.py
? v20/experiments/ce_facades_r2/BRIEF.md
? v20/experiments/ce_facades_r2/control.py
? v20/experiments/ce_facades_r2/db.py
? v20/experiments/ce_facades_r2/exports/macro-run_135
? v20/experiments/ce_facades_r2/exports/macro-run_300
? v20/experiments/ce_facades_r2/exports/plan-run_169
? v20/experiments/ce_facades_r2/exports/plan-run_218
? v20/experiments/ce_facades_r2/exports/plan-run_254
? v20/experiments/ce_facades_r2/exports/plan-run_55
? v20/experiments/ce_facades_r2/exports/plan-run_7
? v20/experiments/ce_facades_r2/exports/plan-run_89
? v20/experiments/ce_facades_r2/report.json
? v20/experiments/ce_facades_r2/run_experiment.py
? v20/experiments/ce_facades_r2/scenario.py
? v20/experiments/ce_facades_r2/schema.sql
? v20/experiments/ce_facades_r2/session_object.py
? v20/experiments/ce_facades_r2/test_experiment.py
? v20/experiments/ce_facades_r2/thin_adapter.py
? v20/experiments/ce_facades_r2/unloadable_profile.py
? v20/experiments/ce_facades_r2/workflow_container.py
? v20/experiments/ce_native_d5/BRIEF.md
? v20/experiments/ce_native_d5/control.py
? v20/experiments/ce_native_d5/db.py
? v20/experiments/ce_native_d5/exports/02c36bcdca62ca1de2b47598a700f27553536d662590cd0803103abe78952971
? v20/experiments/ce_native_d5/exports/1deadf3cfd9d7e3faca91b55b17413b7236967e688fcbc89c7a6a6371f6a4acf
? v20/experiments/ce_native_d5/exports/30c2d0391fb71a9a71fe601728e8740c03b7b642865247d553b4081ecc294358
? v20/experiments/ce_native_d5/exports/35d1211932ae8b3a247cb84408caaef4e5907e0bf1e2a25a0aca07cd25e1c722
? v20/experiments/ce_native_d5/exports/542d630bad41d2296ea4cf6b2ad03b0a75c3cb954a911b2c6fed0a0e3ca9539c
? v20/experiments/ce_native_d5/exports/780adaf9a5ed7523551f854bb5e3bb754d63baf95026b8a3da71f12b0fef77c7
? v20/experiments/ce_native_d5/exports/9ae1dc73d0c5b2aa252036bbdd5572f0ded82203e3f73ab7198d5e6857d10ac9
? v20/experiments/ce_native_d5/exports/d7b0717202604f4941983807ee1dbed5cab2458921145e952cf6230aa400da46
? v20/experiments/ce_native_d5/exports/d892433b6e978bd5b5cf46798700f16ec04c85baf05a4fcbcc65f936b6b083f2
? v20/experiments/ce_native_d5/exports/e811e1ebb5f584ba17b364d7bac66bad0de3e0e223757e48c386de0e31ac63db
? v20/experiments/ce_native_d5/report.json
? v20/experiments/ce_native_d5/run_experiment.py
? v20/experiments/ce_native_d5/scenario.py
? v20/experiments/ce_native_d5/schema.sql
? v20/experiments/ce_native_d5/test_experiment.py
```

### Hash manifest for candidate HEAD source exercised/referenced by B0-2

SHA-256 hashes are of the candidate filesystem bytes at baseline (all selected files are tracked clean HEAD copies):

```text
80a15e056653090fc7f977aad3b27452fe090829c9bcd3067c020034b52bd1d6  v24/host/__init__.py
72b9e1dae5dce8b63e05ac079f75f9e55f665081b15863afa027f17b8892de1f  v24/host/db.py
c96ac31e03b6a8f47c5c6afc085b11f8816be27bda836ae452151e88980faf22  v24/host/deepseek.py
fd359802212da0ac8217aa262f4c5af5f0a10dc5126afc31074d5a950ce6599d  v24/host/journal.py
d93a70a23ac91734ab62648f977194db9847b2b2a03a59c2179eb1e6fe5899ad  v24/host/line_json.py
0ca9886430c8ce59943a445936be43555c65da229a6ee0397af3b1e50b9f5dd0  v24/host/plugin_smoke.py
2fc6b87eb20e6b0ad815c39966e44618f4141e8c4ebac5eea1f5aa213d4673ce  v24/host/plugins.py
47f1b0d0c821710eec5b97784b23e08f6d7a4c23aba40c9a4456eebc6c1a95df  v24/host/process_io.py
9f23d38542dab985ce2e6a1fb847ab826496c394b2488d5a2dcdac5d20cef1f1  v24/host/registry.py
d56de4f0e82ca43a8606a4ae834afc913b7d421e40f5721d6f997eff827b07a4  v24/host/smoke.py
a24f2af1d0bc0b98ac11555c4ec074a57bf078ab7831420a8cc14d98a127aaf4  v24/host/worker.py
20156f3c7eb5e8a88dddceb32addd360a3f0a8ac10dbe5a443e18f374912b071  v24/load.py
32825fde8f5c4628c65effb1a930b3dc74ba30619afebd4a269fb1545c31e036  v24/s1/setup_db.py
f4ef27633a7a5d80ab35fd85cfc789ab4b3479c84c5aa445ad373986f81add5a  v24/s10/README.md
cf75a3e2711b0560e36ac1dd4a205ce3dbd359358794edf2c7de1f8963188408  v24/s10/test_g9.py
dc9e0e575d3cb2061eff286ae5fefa3d83b2bf8a2d36cae200c4eca484262063  v24/s11/README.md
52b4f8829fb5eae230a349f0ba7d2727e062aac5ba1eec21279cc700010a7031  v24/s11/plugin_fixtures.py
58e09e3573e85e8a6abb85cc8da3d0fca87180c6ac1ef2bf5d37b0d1f0206e4f  v24/s11/plugins/echo.js
50fb18ee57d088ce8a866a1d0c3beaa1d3ebcd0bcc27c58502ea8306808c199f  v24/s11/plugins/echo.py
4b3383dabac238c0d4cbc356aaf78562690ce4c8f88483d829f7ef96e31dc11d  v24/s11/test_g10.py
47878c083dfee9bd66ccca9170238038bda85b2506fa26ba61870704a44daba8  v24/s11/test_node.py
c93d4746bc20e2a7f46ba6f2b9af3cb1af92aae12c04f1d23a235f5482bd94cb  v24/s2/test_g3a.py
f8ee841505b063ae7d8ac8f608847bd3649ba87f30d8007dbb39982a504c0f41  v24/s4/test_g2b.py
bdde1e413e35993b787ea1a2acadb282fb259a1ee14f2afdd9ac7476cc3bbc59  v24/s5/test_g4.py
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
```

## B0-2 execution

- Status: PASS.
- Full command: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_multi_provides.py`
- Exit code: `0`.
- Captured log: `/tmp/v24-b0-multi-provides.log` (outside candidate); SHA-256: `6dedc5969fd3adbb6222825d0293481b48834642ae28d8dc70cf501feb1c2b39`.
- Actual last line: `[pass] B0-2 DB-only multi-provides probe; zero process spawns`.
- Positive result: one install created exactly `k0/k1` slots with `contribution_seq=[0,1]`; digest, descriptor, realm, episode, and resolve checks passed; one public start yielded exactly two live public host pins matching their slots and sharing provider fiber/episode/install.
- Negative result: cross-realm `k1` requirement returned `dependency_unresolved`; no run was created.
- Zero-spawn boundary: neither dispatcher nor worker is constructed; `line_json.run_process` and `process_io.run_process` are patched to fail; Python socket connect/create_connection entry points are denied.
- Fixture-only retries before the passing run corrected the episode field name (`current_episode_id` assumption replaced by `fiber_control` emitted episode), normalized psycopg bytea text, and used the scope-creating admin principal for public `start`. No production failure or STOP-S condition occurred.

## Scope boundary

At the B0-2 snapshot, no production source, SQL, s10/s11 gate, loader, matrix, ledger, golden/checker, or closeout code had been changed. The ABI design is external read-only input and is not in the delivery.

## B0-2 correction rerun (2026-10-30)

- Correction: process sentinels increment a shared call counter before raising; a `finally` assertion requires `len(process_calls) == 0`, including if a caller swallows a sentinel exception. P8 now directly counts `v24.pins` joined to runs in the fixture scope and asserts zero.
- Full command: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_multi_provides.py`
- Exit code: `0`.
- Captured log: `/tmp/v24-b0-multi-provides-rerun.log`; SHA-256: `6dedc5969fd3adbb6222825d0293481b48834642ae28d8dc70cf501feb1c2b39`.
- Actual last line: `[pass] B0-2 DB-only multi-provides probe; zero process spawns`.
- Result: P1–P7 and P8 passed; process sentinel count asserted zero in `finally`; direct P8 scope run-pin count was zero.

## B0-3/B0-4 golden capture and check (2026-10-30)

- Source: candidate worktree `b0-abi-baseline-20261030` at base `a4b7dba5e945af03d04f4145103ddaaff2ee18ec`; no production/host/SQL changes were made. Capture output paths below are temporary, outside the repository; direct and symlink-resolved attempts targeting the repository were rejected with exit 2. The fixed candidate vectors were copied only after two independently captured directories matched byte-for-byte and were reviewed.
- Full capture command for run 1: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/capture_golden.py --output /tmp/v24-b0-golden-capture-14 > /tmp/v24-b0-capture-14.log 2>&1` — exit `0`; log SHA-256 `396ae79d92e0d307c6aec665bfd538b7186626a463ddfa3bdb254a5947f37bc4`; last line: `[captured] /private/tmp/v24-b0-golden-capture-14; cases={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 8}`.
- Full capture command for run 2: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/capture_golden.py --output /tmp/v24-b0-golden-capture-15 > /tmp/v24-b0-capture-15.log 2>&1` — exit `0`; log SHA-256 `f8fc9428153438db8cdb87d0a46028805d98601eef18bb7eb1022d70c826a300`; last line: `[captured] /private/tmp/v24-b0-golden-capture-15; cases={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 8}`.
- `diff -rq /tmp/v24-b0-golden-capture-14 /tmp/v24-b0-golden-capture-15` exited `0` with no output. This is the byte-for-byte stability check. Candidate directories and logs remain outside the repository.
- Read-only Python/PostgreSQL command: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_golden.py` — exit `0`; log SHA-256 `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861`; actual last line: `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python`.
- Read-only Python+Node+PostgreSQL command: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_golden.py --node` — exit `0`; log SHA-256 `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0`; actual last line: `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node`.
- Vector inventory: descriptor 5; frames/stdout/parser 23 (4 request frames, 10 language-specific raw stdout cases, 9 parser byte cases); provider request 4 (initial and continuation for success and known error); tool-message bytes 2; F6 structural vectors 6. There are 34 byte cases plus six structural cases, 40 entries total. F6 observed event types, tool-message keys, and `dispatch_started`/`dispatch_finished` payload key sets come from actual captured `HostWorker` journal records; declared event types are checked separately. The lease value is observed by spying on `_lease_for` during the actual `run_until_idle` claim path (the method result passed to `HostDB.claim`), then independently compared with `default_lease_ms`: both are 30000 ms.
- Expected vector file SHA-256:
  - `v24/b0/golden/descriptor_v1.json`: `eeaf281f89de42a7c4d0e4e49e692678c69ddb12c47f47fb9344ad09345561c7`
  - `v24/b0/golden/frames_v1.json`: `74f1220be8ab553fbd4e4399a106bb64c91143332105546182c6cde2778a6a80`
  - `v24/b0/golden/provider_requests_v1.json`: `36ed983f0302c374fc92b3153c0c2a5dbb0fbb722665394ef5643bc51d86e921`
  - `v24/b0/golden/tool_messages_v1.json`: `caea917ae1779922742b427561f9985a69fa9917496b86ec23ec37b478f7ad14`
- Output guard verification: direct `--output "$PWD/v24/b0/golden"`, nonexistent in-repository `--output "$PWD/v24/b0/.candidate-that-must-not-exist"`, and a `/tmp` symlink resolving into `v24/b0` each exited `2` with `candidate output must resolve outside the repository; delivery/tracked paths are forbidden`. The absent target remained absent. Each failure log SHA-256 was `4289e28d89851b314da515c28305a70f81e6f802d14d8c7a2afa514a9726337c`. All four fixed vector hashes were identical before and after these attempts.
- Oracle review: the one planned review call completed with three lanes, but its context contained only the untracked B0 plan, not the candidate code/vector artifacts; therefore it was not a code-level validation. Its actionable concerns on path confinement, runtime lease provenance, journal-derived structures, and exact case inventory were addressed in the candidate, with the updated guards and exact IDs checked locally. No second review call was made.
- No live provider was called. Captures omit authorization headers; no secrets were found in reviewed vector files.




## B0-5 through B0-7 final acceptance (2026-10-30)

Candidate source SHA: `a4b7dba5e945af03d04f4145103ddaaff2ee18ec`. Stable candidate source fingerprint: `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155`. The fingerprint covers sorted executable/test/helper sources and fixed golden vectors under `v24/host`, `v24/sql`, `v24/s1`…`s8`, `v24/s10`, `v24/s11`, `v24/b0`, and `v24/load.py`; README files, evidence documents, and transient caches are excluded. Documentation-only closeout edits after the rerun therefore do not change the tested source fingerprint. Each command row preserves its actual merged-log SHA-256. Credentials were removed from each invocation and `UV_NO_ENV_FILE=1` was set; no real provider was called.

### Final runbook (strict serial order)

| # | executed_at (+08:00) | source_sha | candidate_fingerprint | command | exit | actual last line | merged log SHA-256 | status |
|---:|---|---|---|---|---:|---|---|---|
| 1 | 2026-10-30T12:05:56+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_multi_provides.py` | 0 | `[pass] B0-2 DB-only multi-provides probe; zero process spawns` | `6dedc5969fd3adbb6222825d0293481b48834642ae28d8dc70cf501feb1c2b39` | passed |
| 2 | 2026-10-30T12:05:57+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` | passed |
| 3 | 2026-10-30T12:05:59+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` | passed |
| 4 | 2026-10-30T12:06:01+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` | passed |
| 5 | 2026-10-30T12:06:02+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` | passed |
| 6 | 2026-10-30T12:06:03+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` | passed |
| 7 | 2026-10-30T12:06:05+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` | passed |
| 8 | 2026-10-30T12:06:07+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` | passed |
| 9 | 2026-10-30T12:06:09+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` | passed |
| 10 | 2026-10-30T12:06:14+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `c7d98f9b6548c97a7e90df71412137e5d97c5ed6e059ea9508f9cf7cec9832cd` | passed |
| 11 | 2026-10-30T12:06:18+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `2e063d43bbb1e6a37b1ae95300708de715d13758f76fa75042670562a01b1586` | passed |
| 12 | 2026-10-30T12:06:21+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `451193c57cb9db973e6104c01f319591b1c0847e9a3067d0c6a356eb134d6a96` | passed |
| 13 | 2026-10-30T12:06:25+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `fa5caf141da4abb92851f3ce93387f4b63bfb162757e248f663e5f04b52d3cda` | passed |
| 14 | 2026-10-30T12:06:27+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `8e6cdc57f4f1e50e0663fd307955088576da208df4409530cb372905b3629b9c` | passed |
| 15 | 2026-10-30T12:06:34+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` | passed |
| 16 | 2026-10-30T12:06:37+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` | passed |
| 17 | 2026-10-30T12:06:40+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` | passed |
| 18 | 2026-10-30T12:06:42+08:00 | `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` | `89e6b109151f4131b5722919033720b39433e3247a7f5c262b651f60372b1155` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `2cf820fd87e580ea487983292f85c3507ac3ca541d296bda692eb74adf1a66a4` | passed |

Closeout commands #4–#14 are the frozen **11/11**. Commands #1–#3 are the B0 probe and Python/Node golden checks. Commands #15–#18 are separate G9, G10, Node, and multilingual extension checks. All 18 exited 0; Node and multilingual were executed (not skipped). Logs are retained outside the repository at `/tmp/v24-b0-final-20261030-rerun/`; the log directory is not part of the delivery.

### Exercised source manifest

This sorted manifest covers host/SQL, loader, B0 assets, s10/s11, and the closeout tests/setup helpers. Digests are SHA-256 of candidate files after the final run and documentation updates; documentation-only files are included here for auditability even though excluded from the stable source fingerprint above. The primary checkout retains its pre-existing dirty `v24/s10/README.md` unchanged; its primary working-tree hash differs from the candidate HEAD manifest by design and that path is unstaged.

```text
51b35472285f78100cd9a16810f1128fd5159c3f9b17dbdebe3d7b54626fd8ee  v24/b0/README.md
d69452b723c9f0a9b201685331167c1c91b94045435177ef6e7316a7b84cba1b  v24/b0/capture_golden.py
eeaf281f89de42a7c4d0e4e49e692678c69ddb12c47f47fb9344ad09345561c7  v24/b0/golden/descriptor_v1.json
74f1220be8ab553fbd4e4399a106bb64c91143332105546182c6cde2778a6a80  v24/b0/golden/frames_v1.json
36ed983f0302c374fc92b3153c0c2a5dbb0fbb722665394ef5643bc51d86e921  v24/b0/golden/provider_requests_v1.json
caea917ae1779922742b427561f9985a69fa9917496b86ec23ec37b478f7ad14  v24/b0/golden/tool_messages_v1.json
a03a3f620744ad3400769efb583499e22957c61c94f93bbc4b9dd1de3fed4a4e  v24/b0/golden_cases.py
41e999ac84e2bb42db0f0b1e4a113312534fea211327012e097b1afc81c1c97f  v24/b0/test_golden.py
dc7476bf6f8b6e3c6ecbdc505c40ee6f7b3793381680bc20375c2c4224339d5e  v24/b0/test_multi_provides.py
80a15e056653090fc7f977aad3b27452fe090829c9bcd3067c020034b52bd1d6  v24/host/__init__.py
72b9e1dae5dce8b63e05ac079f75f9e55f665081b15863afa027f17b8892de1f  v24/host/db.py
c96ac31e03b6a8f47c5c6afc085b11f8816be27bda836ae452151e88980faf22  v24/host/deepseek.py
fd359802212da0ac8217aa262f4c5af5f0a10dc5126afc31074d5a950ce6599d  v24/host/journal.py
d93a70a23ac91734ab62648f977194db9847b2b2a03a59c2179eb1e6fe5899ad  v24/host/line_json.py
0ca9886430c8ce59943a445936be43555c65da229a6ee0397af3b1e50b9f5dd0  v24/host/plugin_smoke.py
2fc6b87eb20e6b0ad815c39966e44618f4141e8c4ebac5eea1f5aa213d4673ce  v24/host/plugins.py
47f1b0d0c821710eec5b97784b23e08f6d7a4c23aba40c9a4456eebc6c1a95df  v24/host/process_io.py
9f23d38542dab985ce2e6a1fb847ab826496c394b2488d5a2dcdac5d20cef1f1  v24/host/registry.py
d56de4f0e82ca43a8606a4ae834afc913b7d421e40f5721d6f997eff827b07a4  v24/host/smoke.py
a24f2af1d0bc0b98ac11555c4ec074a57bf078ab7831420a8cc14d98a127aaf4  v24/host/worker.py
20156f3c7eb5e8a88dddceb32addd360a3f0a8ac10dbe5a443e18f374912b071  v24/load.py
32825fde8f5c4628c65effb1a930b3dc74ba30619afebd4a269fb1545c31e036  v24/s1/setup_db.py
d06b6a6635d85794965c14a6f9a3c271f051856e9aa9ed9251858f6b93888fa1  v24/s1/test_ddl.py
ba390caa6f464f79cb5478427565f9d4c2739025b87c268189408e2e9bc610ae  v24/s1/test_g1.py
f4ef27633a7a5d80ab35fd85cfc789ab4b3479c84c5aa445ad373986f81add5a  v24/s10/README.md
cf75a3e2711b0560e36ac1dd4a205ce3dbd359358794edf2c7de1f8963188408  v24/s10/test_g9.py
dc9e0e575d3cb2061eff286ae5fefa3d83b2bf8a2d36cae200c4eca484262063  v24/s11/README.md
52b4f8829fb5eae230a349f0ba7d2727e062aac5ba1eec21279cc700010a7031  v24/s11/plugin_fixtures.py
58e09e3573e85e8a6abb85cc8da3d0fca87180c6ac1ef2bf5d37b0d1f0206e4f  v24/s11/plugins/echo.js
50fb18ee57d088ce8a866a1d0c3beaa1d3ebcd0bcc27c58502ea8306808c199f  v24/s11/plugins/echo.py
4b3383dabac238c0d4cbc356aaf78562690ce4c8f88483d829f7ef96e31dc11d  v24/s11/test_g10.py
47878c083dfee9bd66ccca9170238038bda85b2506fa26ba61870704a44daba8  v24/s11/test_node.py
c93d4746bc20e2a7f46ba6f2b9af3cb1af92aae12c04f1d23a235f5482bd94cb  v24/s2/test_g3a.py
c7749a1de1ed37d4ecd74f99e4085fd68aeee1537137806bb37b41d8f8000d72  v24/s3/test_g2.py
f8ee841505b063ae7d8ac8f608847bd3649ba87f30d8007dbb39982a504c0f41  v24/s4/test_g2b.py
bdde1e413e35993b787ea1a2acadb282fb259a1ee14f2afdd9ac7476cc3bbc59  v24/s5/test_g4.py
b1b21c86bc085a2a1d442208fa768f0dffca18f1648b256a147a1facaa81352a  v24/s6/test_g5.py
efaa2990ea97c8c9d3e912bfb85f109412c0844fdada31d4a6f0877e940c92c8  v24/s7/test_g6.py
5d50bb3f6281ee30557481050903eebbcef22bdfc5e4ec9e379dcc239a50211e  v24/s8/test_g7.py
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
```

### Freeze and scope audit

- Candidate HEAD remained `a4b7dba5e945af03d04f4145103ddaaff2ee18ec`; all exercised tracked production/gate inputs were from that base. `git diff --exit-code -- v24/host v24/sql v24/s10 v24/s11 v24/load.py` returned 0 before and after the run. No new SQL was introduced; loader order is unchanged.
- B0-only deliverables: `v24/b0/**`, this plan, this execution record, plus B0 additions to the v24 conformance matrix and deviation ledger. The external ABI design is read-only and excluded.
- B0-5 boundary labels and Q1–Q5/W4/W5/W6 ownership appear consistently in the README, plan Result, matrix, and deviation ledger. Q1–Q5 and W4 behavior remain unverified by B0 as stated; W5/W6 require empty-page, offset-bound, and pagination-convergence checks, with W1 design synchronization before tool implementation.
- Capture and fixture failures documented earlier in this record remain intact. A bare `python` launch attempt failed before any command ran because the shell has no `python` executable; the runner was restarted as `python3`, after which all 18 commands executed and passed. A whitespace-only candidate correction preceded the final full rerun; no assertion or runtime behavior changed.
- Oracle note: the single planned review had plan-only context, so it was not code-level acceptance. The independent local acceptance inspected the probe, golden checker, fixed ID inventory, capture path guards, case counts, journal-derived structures, and zero-process `finally` assertion; no second Oracle review was made.

B0-1 through B0-7 are complete on the candidate. The next operation is to transfer this exact allowlisted B0 delta to the primary checkout, preserve its unrelated dirty worktree content, and publish the single authorized milestone commit to `origin/main`.
