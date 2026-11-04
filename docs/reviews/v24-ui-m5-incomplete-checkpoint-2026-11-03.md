# v24 M5 measurement / review checkpoint — 2026-11-03

> **Current status (2026-11-04, after the measured closeout run and the abandonment decision):** M5 closeout. `MAX_SAFE_ARGS_BYTES=128` is the measured current-profile bound: 13 targets 64–124 × three classes plus two additional 128 B probes per class (one repeat each) = 45 probes, 45/45 passed, 14 complete targets, 3 boundary repeats; the earlier 160 B batch is historical. exec11 completed with five HTTP requests and no guard rejection. The two unrecoverable historical evidence proofs are abandoned by the dated coordinator record `docs/reviews/v24-ui-m5-evidence-abandonment-2026-11-04.json` (twelfth addendum, D-UI-19); the audit reports them under `abandoned_evidence`, never as proof. Completion requires the formal review recorded in `prompt-exports/v24-m5-evidence/m5-formal-review.json` to bind the current runtime and closeout documents. The 2026-11-03 text below is the historical INCOMPLETE checkpoint and is superseded by the seventh through twelfth addenda where they say so.

Status: **M5 INCOMPLETE, uncommitted; fifth formal review ACCEPT for continuation only.** Five formal 2/2 Oracle reviews have run without executing tests. The first four returned Request changes overall; after repairing every accepted P1, the fifth review returned **ACCEPT for continuation from both lanes** and identified no P1. Two P2 limitations remain documented below. This is not M5 completion: the seven evidence-derived blockers, the missing real-provider exec11/final capacity run and the unimplemented full render contract still stand. No completion commit, staging, push, amend, main mutation, or new provider request (no key present). Coordinator owns actual browser actions and final review. Historical REDs/reviews and original52 files remain unchanged.

## Authority and exact source scope

Read in full: ignored plan export `prompt-exports/oracle-plan-2026-11-03-164519-v24-m5-chainlit-runt-b345.md`, including both lanes, coordinator checkpoint reconciliation and WI-2A amendment; `prompt-exports/v24-m5-evidence/WI2-CHECKPOINT.md`; `wi2a-20261103T134358Z/checkpoint.json`. Planning opinions are not test results. The authoritative plan had no WI-2A amendment; the dated appendix now records that approval and actual incomplete result without rewriting prior text.

Branch `v24/ui-chainlit`, HEAD `a6ba59657c53d3cf1a7e00cc90aad80bf025f617`; main/origin-main `1143dce6da0572bccab083da9a6be0175210b062`. Historical WI-2A source hashes (superseded by the post-review fixes below; retained to identify the real-workflow snapshot):

| Source | SHA256 |
|---|---|
| v24/ui/app.py | eabd56bf5acba895341ca551ac620dbcd8332ac5dce17b22c119c79a28122f5d |
| v24/ui/catalog.py | ff9151b1b2a57ce7352e1a6eee1812b47180ebb6e4c264ec5409305d7279e751 |
| v24/ui/control.py | 2f07bcd35f06c50e2eec0d9f7f0044f61159938461ee180b2053b74202a3b730 |
| v24/ui/real.py | 59d46f38a3a6e7dc2d3bca6b9939f1e448bf601b534979b0467936283f52607c |
| v24/ui/test_real_entry.py | 6de290ea309dc7f5707d6169fd044741835c51197b6121393d3ab6564fb42642 |

Real ceiling8192, legacy/fake8000, cap512, SQL reserve4096, timeout120s, worker default lease30000ms, budget24 steps/24 tool calls/20000 tokens/600000ms; `MAX_SAFE_ARGS_BYTES=None`. No new budgets, host, SQL, workflow, prompt, guard, or skill changes were made in WI-3. The old `audit_m4_repair.py` was not executed or modified; its hash remains frozen, as does `run_m4_checks.py`.

## Current-source retained WI-2A evidence

Evidence root `prompt-exports/v24-m5-evidence/wi2a-20261103T134358Z/`; private directory0700, raw journals never published. `checkpoint.json` SHA256 `499eacb1a40a0c5a0bc48258a2c17a5800c4fb374e046932c8b009397a921636`.

| Scenario | Exit | HTTP | Canonical bodies B | Result |
|---|---:|---:|---|---|
| short | 0 | 1 | 4330 | completed, durable final |
| write10 | 0 | 4 | 5917/6803/7219/7520 | completed; full ten pins/provider tools, full skill read/continuation, exactly one write, durable readback/final |
| skill | 0 | 2 | 6230/7118 | completed; full skill read/continuation and final |
| exec11 | 1 | 1 | 6316 | cancelled, contract incomplete; model write rejected by exact-command/content guard before write/bind; no bash/readback/final |

Total8 HTTP; all observed usage within4096 reserve, actual/requested cap512. The guard-rejected exec11 is not a body-capacity refusal and proves no write/bash/readback/final completion. No workflow/guard change or replacement attempt was made. An earlier direct-script invocation failed `ModuleNotFoundError: No module named v24`, exit1/HTTP0 before provider/DB activity; its log remains, followed by the one actual module short attempt. There is no new provider call in WI-3.

WI-2A retained deterministic commands (not rerun for unchanged runtime):

| Command | Exit | Exact last line / receipt |
|---|---:|---|
| `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/test_real_entry.py` | 0 | `[passed] M5 real entry offline contracts; WI2=workflows/probes/receipts; sockets=0; capacity=unmeasured` (`focused-wi2a.log`) |
| `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/run_m4_checks.py --log-dir prompt-exports/v24-m5-evidence/wi2a-20261103T134358Z/m4` | 0 | `[passed] M4 private checks; commands=16; exits=0; skips=0; persistent_pgdata_untouched=true` (`m4/results.json`, all16 exits/log hashes/last lines independently checked by new audit) |
| private-PGDATA/bootstrap `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` (`s10-g9.log`; exact bootstrap command is in checkpoint) |

## Legacy capacity observations — historical source only

`WI2-CHECKPOINT.md` and `checkpoint-reconciliation.json` retain21 command receipts,20 real invocations/25 HTTP, usage51884 prompt +6793 completion. The legacy ten targets128/256/384/512/768/1024/1536/2048/3072/4096 include complete matched successes128 ASCII/256 CJK/512 ASCII, repeated escape256/384 length observations, and body rejections3072/4096. Failed length complete args are unavailable; residual bytes are not complete args. Legacy workflows include successful short/write10/skill and incomplete exec11 attempts (first body8048>8000 after skill/write; second selected bash but failed the guard). Those source hashes are historical. Current8192 does not retroactively turn them into final-profile acceptance. No safe or monotonic threshold is inferred; final-profile capacity/repetitions and scope recommendation remain incomplete.

## Dated provenance correction — 2026-11-03

Historical [WI-1 report](v24-ui-m5-wi1-offline-report-2026-11-03.md) statements at Verification receipts / Source hashes describing logs as remaining in `/tmp` are preserved as statements at that earlier handoff. **They are no longer true at resume/WI-3:** the original `/tmp/v24-m5-baseline-20261103/baseline.json`, `/tmp/v24-m5-wi1-receipts-20261103/receipts.json`, and associated original logs are unavailable. This addendum corrects survival claims; it does not recreate missing receipts or replace original52 proof. Matching five published WI-1 hashes only establishes those source bytes, not missing full-log or original-baseline verification.

`resume-baseline.json` SHA256 `31622c4d18034f89864e8bcd612fa7bcedc3cd6f77e05c9a5b468348df5a09d0` contains1456 tracked hashes and55 captured untracked hashes. New audit separately reports HEAD changes, resume changes, frozen paths, and53 preserved captured untracked files with the two WI-2 source changes (`real.py`, `test_real_entry.py`). The original52 files are preserved since resume only. This does not upgrade their pre-WI-1 proof. Initial WI-1 tests touched persistent PGDATA/global state; cleanup and later67330-entry metadata comparison are historical evidence, but pre-incident logical equality cannot be proved. No current audit result makes that claim.

The WI-3 retained manifest pins146 existing evidence files as observed now, SHA256 `1d6f4b33d2176d711aca0ce69e6ab5331eaab940bfb7c5d095addacbd66386c6`. It verifies old receipt log/last-line/evidence hashes and within-command source equality; current-source comparisons are reported separately. Pinning retained bytes now is not original lost-baseline proof. Current raw durable/journal hashes are independently rechecked; exit codes are recorded receipt facts, not recovered OS exit observations.

## Display consistency and production scope for coordinator review

Current prompt and footer reference `catalog.OUTPUT_TOKEN_CAP`; footer also reads `catalog.MAX_SAFE_ARGS_BYTES`. The new audit asserts these AST references and the README marked current-values block against current constants. Legacy8000/current8192 profiles and cap512/reserve4096 are checked in retained profile evidence and current source hashes. **Full rendering contract is not complete:** system prompt does not display the safe-args state or profile ceiling, and README has no production-generated renderer. Adding safe-args/profile values to the production prompt or central rendering function would change production request bytes and need coordinator scope review plus affected evidence/regressions. WI-3 reports that need before making production changes. No prompt or footer text changed.

## WI-3 audit and runner

New `v24/ui/audit_m5.py` and `run_m5_checks.py` inspect files/git/retained receipts and the service process liveness; no DB/provider IO. An unrelated pre-existing `.claude/settings.local.json` appeared outside the captured55 inventory (mtime2026-11-02); it is reported separately, untouched and excluded from the deliverable/index. Historical ledger EOF whitespace is preserved; checks cover new files and changed lines. The runner clears environment to a minimal allowlist, runs no runtime gate or real provider call, and saves actual command/exit/last-line/log SHA256/audit-source SHA256. Snapshot mode accepts only a valid **INCOMPLETE snapshot**, `milestone_acceptance=false`; it fails on integrity discrepancies. Completion mode exits1 for the known blockers, including missing original52 proof, incomplete final capacity/exec11 and review/display contracts. There is no fake-green completion path. Missing evidence, altered source, staged files or changed main refs fail integrity checks. No old-audit execution or gate weakening.

Reproduction commands (from repo root): `python3 v24/ui/run_m5_checks.py` and `python3 v24/ui/run_m5_checks.py --completion`. Receipts/logs are ignored under unique `wi3-checks-<UTC>-snapshot|completion/` directories. Actual post-browser snapshot exit0 last line `[passed] M5 INCOMPLETE snapshot checks; milestone_acceptance=false; original52_proof=unavailable`; completion exit1 last line `[failed] M5 audit; mode=completion_rejected; errors=7`. Audit freezes1448 tracked paths, verifies146 retained evidence file hashes,21 historical command receipts,18 WI-2A offline command receipts and4 current real summaries with current-source matches; captured55 untracked contain53 unchanged plus the two identified WI-2 changes. It verifies browser receipt/screenshot/source hashes and service liveness separately. Every final runner audit result also records exact deliverable SHA256 values, avoiding a self-hashing documentation cycle.

`python3 prompt-exports/v24-m5-evidence/wi3-audit-negative-checks.py` exit0, exact last line `[passed] M5 audit negative checks; staged/main_ref/retained_log rejected; file_mutations=0; provider_calls=0`. It fault-injects metadata in memory: each case returns1 with respectively `index_not_empty`, `refs_changed_since_resume`, and `retained_evidence_hash_mismatch`, without modifying index/main/evidence bytes. Syntax compilation of the two new scripts passes. Existing runtime gates were not rerun. Latest immutable runner receipts and a final ignored handoff manifest supply exact exits/log/source/deliverable hashes.

## Actual missing-key Chainlit service — coordinator browser handoff

Ignored helper `prompt-exports/v24-m5-evidence/launch_missing_key_ui.py` launches the existing absolute `v24/ui/app.py` with the existing UI interpreter, `PYTHONPATH=<repo>`, scratch cwd/HOME, `V24_UI_MODE=real`, and no provider-key or PG* environment variables. No adapter, DB or provider call is constructed by launch; actual on-chat-start follows the existing missing-key-before-resources path. Generated `.chainlit`, translations, chainlit.md and caches stay in scratch. Repository `.chainlit/config.toml` is untouched.

Launch exited0; service alive at HTTP200 on **http://127.0.0.1:18924**, PID **31138**. Log and launch receipt: ignored `prompt-exports/v24-m5-evidence/wi3-missing-key-ui/server.log` and `service.json`. The launch receipt's pending browser field is historical and superseded by coordinator's actual browser evidence at14:32:49Z. Coordinator used Kimi WebBridge, observed `credentials_absent` translated “凭证缺失”, submitted a harmless message, and observed UI still available plus HTTP200 afterward. The after-submit DOM contains the translated message and usable textbox; `browser-submit.json` confirms actual BUTTON submission. Source hashes in browser receipt match current production. This is actual browser evidence supplied by coordinator, not a mock or an action performed by this WI-3 agent.

Browser receipt SHA256 `f9fcd0c6f463bb565f2a8c980801a9464ab1ce13e29d7b2b1deb5ab481d2f21c`; after-submit DOM SHA256 `b7ad93166aa121f3048316a66c72e6cc649f72a72c87c40d99d02bc3dd7b1c93`; screenshot SHA256 `acf3f3dd8c0bb69012861d8e37a4444fb81bf24fd8745e72c7dab1155c586c1d`. Files `browser-receipt.json`, `browser-after-submit.json`, `browser-missing-key.png` and intermediate `browser-*` receipts remain private under the same ignored service directory. No provider request was requested. Actual browser proof closes the no-key UI case only; it does not prove a real-provider UI workflow or full M5 acceptance.

Cleanup after coordinator inspection: `kill -TERM 31138`; retain scratch/logs. No production edits were required. Service stays running through WI-3 final handoff; coordinator owns subsequent cleanup. Browser missing-key case is observed; remaining M5 acceptance stays incomplete.

## Review claim inventory / unresolved acceptance

| Material claim | Evidence / disposition |
|---|---|
| WI-2A authorization allows only ceiling8192 | accepted: supplied coordinator2/2 checkpoint and precise source/profile hashes |
| short/write10/skill succeeded on current source | accepted with retained summary/log/source verification; not repeated here |
| exec11 completed or capacity is proven | rejected: guard rejected before write/bind; no bash/readback/final, final-profile capacity unfinished |
| Legacy ten sizes prove final-profile capacity | rejected: historical-source samples, incomplete repetitions/mixed causes |
| Original `/tmp` logs/baseline survive | rejected as a current claim; dated correction above, historical text retained |
| Resume53+2 captured-untracked comparison proves original52 | rejected: resume scope only |
| WI-1 cleanup proves pre-incident logical equality | rejected: unprovable from retained evidence |
| All display values/rendering contract already complete | unresolved pending coordinator production-scope review; current-value assertion is narrower |
| HTTP200 alone proves actual UI credentials_absent | rejected; actual coordinator DOM/submission/screenshot/receipt now supplies separate browser proof |
| M5 formally reviewed/complete or ready for completion commit | rejected: no new formal review, known incomplete blockers; completion mode must fail |

Audit development REDs are preserved in a dated ignored development record: initial narrow audit misparsed quoted Unicode git paths; the next pre-closeout run lacked not-yet-created new files; a later snapshot reported unrelated settings inventory and historical ledger EOF formatting. Those implementation failures were corrected without weakening retained evidence checks, production gates or completion criteria. Runner now writes a unique timestamped directory for every run, preserving failures and successes.

No additional real calls, completion commit or main mutation is permitted by this checkpoint. Remaining work requires coordinator decisions and acceptance; the delivered work is reviewable INCOMPLETE documentation, audit/receipts, and missing-key service preparation.

## Post-review fix addendum (2026-11-03, still INCOMPLETE)

Formal Oracle review of the uncommitted snapshot completed **2/2 lanes** and both returned **Request changes**; neither lane ran tests or a provider call. The coordinator verified every material claim. Accepted fixes:

- Real UI now requires an explicit absolute, empty `V24_UI_WORKSPACE_ROOT`; repo-internal scratch is limited to `.uidata/` or `prompt-exports/`. Default toolset is `read`; `write`/`exec` require explicit `V24_UI_TOOLSET`. The constructor validates key → actual adapter → preflight → scratch before creating the data directory, lock, environment, or runtime.
- `v24/ui/provider.py` now owns credential resolution/adapter construction; `app.py` imports only that small factory. `real.py` keeps the compatibility function alias for the CLI/tests. `UiLimits` rejects invalid body/cap/timeout/lease/budget combinations. Prompt and footer read the runtime `completion_cap` (512).
- `--evidence-dir` inside the repository is restricted to ignored `prompt-exports/`; audit output is created with `O_EXCL` and refuses to overwrite retained evidence. Snapshot mode exits **3** with `[snapshot-consistent; NOT ACCEPTED]`; completion blockers are derived from current evidence. Service liveness is narrowed to `pid_exists`/`pid_only_unverified`.
- Offline tests now use system temporary directories; new `test_audit_m5.py` covers snapshot semantics, overwrite refusal, current-source tamper rejection, and derived blockers. Guard rejections record stable `key`/`predicate` fields without relaxing the exact write/bash predicates.

Verified in this review-fix round:

- `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/test_real_entry.py` exit0, last line `[passed] M5 real entry offline contracts; WI2=workflows/probes/receipts; sockets=0; capacity=unmeasured`; log `/tmp/v24-review5-real.log`, SHA256 `656e0b5ad3c87a11c103f152f69bd3f8511cec2ccfc5a05dafe3add0ef04f09f`.
- `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/test_audit_m5.py` exit0, last line `[passed] M5 audit contracts; snapshot=3/NOT ACCEPTED; overwrite and tamper rejected; blockers derived`; log `/tmp/v24-review4-audit-test2.log`, SHA256 `f59af30a350a2f9a6c7482b33b98c1a565a880c52333d86bd87196d95a5c7044`.
- Full `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/run_m4_checks.py --log-dir /tmp/v24-m5-review5-checks` exit0, `commands=16; exits=0; skips=0`, last line `[passed] M4 private checks; commands=16; exits=0; skips=0; persistent_pgdata_untouched=true`; all 13 S13 ran, Node used `--node` explicitly; `results.json` SHA256 `bb9e9b4d2a65445579c52967175088dfc5209ad4c743398e753e13840a2a7646`.
- `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/test_backend_regressions.py` exit0, last line `[passed] backend regressions; read7_exec11=three_processes_each; empty_answer=real_entry_zero_rpc; old_binding=readonly; same_scope_next_start=true; busy_steer_cancel=true; close_checkpoint=targeted_fiber_off_before_dispose; repeated_close=authoritative; python_connect_tripwire=true; db_transport=unix`; log `/tmp/v24-review3-backend.log`, SHA256 `21a27943114f1ea330e9aadc073c28e64263b2590a359029fa80c87d698a0c48`.
- Snapshot audit `uv run python v24/ui/run_m5_checks.py` exit3, last line `[snapshot-consistent; NOT ACCEPTED] M5 INCOMPLETE snapshot; milestone_acceptance=false; blockers=7; original52_proof=unavailable`; exact receipt `prompt-exports/v24-m5-evidence/wi3-checks-20261103T171656962500Z-snapshot/wi3-runner-snapshot-receipt.json`, log `/tmp/v24-final-snapshot.log` SHA256 `354d7e8b5705a963f5e107ec5567462feb4bc617278cfbcf02ec5b1f497f6ca6`; the runner creates a fresh `wi3-checks-*-snapshot/` directory containing the 0600 current-source manifest, audit JSON and receipt. The current-source manifest SHA256 is `e144864a74cba1da1d84f3f0517bdefec4323ee9a274e111d790f27317c0d583`; it covers 11 current sources including `sessions.py` and `test_backend_regressions.py`.
- Completion audit `uv run python v24/ui/run_m5_checks.py --completion` exit1, last line `[failed] M5 audit; mode=completion_rejected; errors=7; blockers=7`; exact receipt `prompt-exports/v24-m5-evidence/wi3-checks-20261103T171657477526Z-completion/wi3-runner-completion-receipt.json`, log `/tmp/v24-final-completion.log` SHA256 `c6d348b439b9565725ea8fb6c8dcd6a5ded2766ffe492e49ea4aeda5513829bc`; its own completed receipt directory retains the same manifest and a separate receipt. The audit JSON is intentionally not quoted by its own hash; the final handoff records the exact path and digest.

The seven evidence-derived blockers are `max_safe_args_bytes_none`, `current_exec11_guard_rejected_before_write_bind_bash_readback_final`, `final_profile_capacity_repeats_and_recommendation_incomplete`, `original52_pre_WI1_baseline_proof_lost`, `WI1_preincident_PGDATA_logical_equality_unproven`, `full_UI_acceptance_and_formal_M5_review_not_accepted`, and `full_prompt_footer_README_render_contract_needs_coordinator_scope_review`.

Final review-fix production sources (the audit manifest must match this table):

| Source | SHA256 |
|---|---|
| v24/ui/app.py | 61b76f8149ff082de9e8bfe36b00b2ed82c04e59b636d7b614627bc1efbb0daa |
| v24/ui/catalog.py | 88d53202f4000764deba09cfcd69bfab3541ae1a924c6799eb0b5ce09ea08be0 |
| v24/ui/control.py | 2f07bcd35f06c50e2eec0d9f7f0044f61159938461ee180b2053b74202a3b730 |
| v24/ui/real.py | 7c16d44be7e78e9fc7b51cda0580e352eb0c2e1c9008c43526ee7a2ffa6aa96e |
| v24/ui/provider.py | a8e4ab0ec6daf6164b22cd51e4ad4291f3f18cdcdcfe8681d4d7417204d89365 |
| v24/ui/test_real_entry.py | ec7a5e10072239b314dfbdf981133d841320d97b65309846a43446a3f7209d3a |
| v24/ui/audit_m5.py | e0aef2a202c14677f659ce2082a36fed4d3ee10b21520a59d1f1484abab640ae |
| v24/ui/run_m5_checks.py | a8122b29983dd3b09826c2e324288183a48ec4d6e080cd0fb860c79895b6f5fd |
| v24/ui/test_audit_m5.py | 56fa7306f73e125d25102f66b063bb717adf412e83ba63adda5908c0fd2d2c25 |
| v24/ui/sessions.py | e3d46fee5cacf01e761760600260223ab3780df7c0894d91b1dca3e41ec103df |
| v24/ui/test_backend_regressions.py | 9e981ec251e55720fa627c36910de9d09c2c15dfe2a78e2d7bc2ded3dd951973 |

The missing-key service PID `31138` still exists but is reported only as `pid_exists`/`pid_only_unverified`; the audit does not infer a healthy service from it. No provider key was present (`DEEPSEEK_API_KEY`/`OPENAI_API_KEY` absent), so no new real request was made.

Still blocked, not waived: current-source exec11 (guard rejected before write/bind; no bash/readback/final), final-profile capacity with ten targets/encoding families/boundary repeats and a measured `MAX_SAFE_ARGS_BYTES`, the lost original-52 baseline, the unprovable WI-1 pre-incident PGDATA logical equality, formal M5 acceptance, and the full prompt/footer/README render contract. The 8192 real ceiling is only an admission bound; it does not prove the SQL 4096 reserve or output-token safety. M5 remains INCOMPLETE, unstaged and uncommitted.

## Second review-fix addendum (2026-11-03, still INCOMPLETE)

A new formal Oracle group reviewed the first review-fix snapshot with the default 2 lanes (`claude-opus-5-5` xhigh and `gpt-6.1-sol-xhigh`); neither lane ran tests or a provider call. Export: `prompt-exports/oracle-review-2026-11-03-233915-new-chat-afeb00-87fe.md` (private/ignored). Lane 1 approved the snapshot for continuation with fixes; Lane 2 requested changes. The coordinator verified every material claim against the code and disposed of the findings as follows.

| Finding | Source | Disposition |
|---|---|---|
| `V24_UI_TOOLSET` was validated only after data-dir creation, lock, `open_env` and `status_env` | L1 P1-1 | accepted; toolset is now resolved/validated before `data_dir.mkdir`; regression patches `open_env`/`acquire_lock` to raise and asserts no data directory. |
| Completion audit cleared blockers on file presence/self-assertion and used a substring render check | L1 P1-2 | accepted in part; snapshot retains exact constants, completion permits only a measured `MAX_SAFE_ARGS_BYTES` in `1..8192`, proof files must carry matching markers and referenced file hashes, formal review must reference an existing export digest, capacity samples must reference retained summaries, and render/cap checks inspect only `build_system_prompt` body AST. The audit still cannot authenticate an external review or capacity record; docs now say so. |
| A null current-sources manifest bypassed the source comparison | L2 P1-1 | accepted; non-dict `files_sha256` is `current_sources_manifest_invalid`; a null-manifest negative test was added. |
| Completion could never accept a measured `MAX_SAFE_ARGS_BYTES` because the snapshot constants assertion required `None` | L2 P1-2 | accepted; completion-specific constants allow a measured int, while snapshot still requires the current `None`; focused `completion_blockers` regression added. |
| A write could precede the full skill read and still pass the receipt | L2 P1-3 | accepted; `skill_before_write` now requires the skill read dispatch to finish before the first write dispatch, `skill_continuation` must be present in the write's parent model request, and a reordered `write→skill→readback→final` negative workflow asserts failure. |
| Cap tests did not prove the UI consumed `limits.completion_cap`; audit cap check could pass via a default argument | L1 P2-1 | accepted; app/catalog 256-cap prompt tests added and the audit cap check now inspects the function body. |
| A real scratch equal to the data root or inside spill/spawn could expose runtime state | L1 P2-2 | accepted in part; real mode now rejects scratch equal to the data root, containing it, or under spill/spawn. Explicit `exec` still has host-shell authority by design; real mode defaults to `read`. |
| `git diff --check` failure crashed before writing the audit record | L1 P2-3 | accepted; uses `subprocess.run(check=False)` and records `tracked_diff_whitespace`. |
| `UiLimits` malformed budget items raised `TypeError` and the comment overclaimed cross-field proof | L1 P2-5 | accepted; normalized to `ValueError("budget_items")` with a malformed-item regression; comment narrowed. |
| W13 stop/steer, loopback enforcement and restart-after-write caveats were missing from the attached docs | L1 P2-8 | accepted; added to README and this record. Single-executor provider calls can queue all session commands; the app does not enforce a bind address, so the operator must use loopback; a non-empty real scratch rejects restart after write/exec. |
| Integration-level audit test is not hermetic; CLI defaults to legacy profile; environment scrub spans the run; nits | L1 P2-4/6/7/9 | accepted as non-blocking limitations. The test is an integration check against retained evidence, not a unit fixture; CLI `--profile` remains explicit; no claim is made that `sockets=0` covers libpq/subprocesses. |

Repairs were verified by `test_real_entry.py` exit0, `test_audit_m5.py` exit0, `test_ui_gate.py` exit0, and the full 16-command sweep under `/tmp/v24-m5-review2-checks` exit0/skips0 with `results.json` SHA256 `9b1f31073d04139279dc46ce62079175d2f453bfb5d7110a4b90af93c4233fb7`. The current-source manifest SHA256 is `4cbae41a5f108f2148f0c93e3e2c3db771f96ea664a463a8fd7ca984ee72f9d6`. The seven blockers remain; in particular `MAX_SAFE_ARGS_BYTES` is still `None`, exec11/final-profile capacity are unchanged, and the lost original52/pre-incident proofs are not reconstructed. A third formal Oracle re-review of this repaired snapshot is required before any acceptance claim.

## Third review-fix addendum (2026-11-03/04, still INCOMPLETE)

The third formal Oracle group again completed 2/2 static lanes without running tests or a provider call (`claude-opus-5-5` xhigh approved with fixes; `gpt-6.1-sol-xhigh` requested changes). Export: `prompt-exports/oracle-review-2026-11-04-001202-new-chat-f5a5d4-0943.md`. Material claims were checked against the code and disposed as follows.

| Finding | Source | Disposition |
|---|---|---|
| Capacity completion accepted ten samples by path/hash without opening them; one summary could be reused; `boundary_repeats` was a bare integer; exec11 lacked `profile=current` | L1/L2 P1 | accepted; each sample must now resolve to a unique summary inside `EVIDENCE`, the summary must be a current-profile probe with `source_unchanged`, matching source hashes, `contract_passed`, controlled `cancelled`/`measurement_complete`, exact file and write-once checks, and one actual-complete tool arg; `(target_args_bytes, content_class)` is derived from the summary; at least ten distinct pairs and a derived duplicate count matching `boundary_repeats>=2` are required; `safe_args_bytes` cannot exceed the largest matched success; exec11 now requires current profile and both skill checks. `real.py` records the probe target/content dimensions only for probe receipts. |
| The prompt/footer/README render blocker could be cleared by an unused `MAX_SAFE_ARGS_BYTES`/profile name in the function body | L1/L2 P1/P2 | accepted in the fail-closed direction; the full render contract is not implemented and is outside the authorized production change. The blocker is now unconditional until a coordinator-authorized render contract exists; no name reference can clear it. |
| A fake-mode binding could be resumed by a real-mode backend, which would send a real provider request over fake history | L2 P1 | accepted; conversation rows and bindings persist `mode` plus a stable `limits_digest`; real mode requires exact mode and digest, fake mode rejects an explicit real binding and permits only legacy absent mode. Tests assert persistence and real-mode refusal of fake/legacy/changed-limit bindings without a provider/DB call. |
| `readback_after_write`/`readback_after_bash`/`bash_executed` could be satisfied by different effects, so write→read→bash→final could pass exec11 | L2 P1 | accepted; one successful `read result.txt` effect must match the final bytes, finish after the successful write, and for exec11 finish after the same successful bash effect. A `bash_after_read` negative workflow asserts `contract_passed` false while bash/durable final remain true. |
| Missing retained evidence could crash the audit before writing a structured result; review export under `prompt-exports/` was unreachable | L2 P2 | accepted in part; expected missing evidence now yields named errors and a written rejected result; review export resolution accepts a relative path under `EVIDENCE` or `prompt-exports/` (with hash and containment checks) but deliberately rejects absolute paths and symlink escapes. |
| Remaining P2s (integration-level audit test, CLI default profile, no full environment scrub, nits) | L1/L2 P2 | accepted as non-blocking limitations; no claim is made that offline sockets=0 covers libpq/subprocesses or that the audit can authenticate an external Oracle/capacity record. |

Third-review repairs passed `test_real_entry.py`, `test_audit_m5.py`, `test_ui_gate.py`, `test_backend_regressions.py`, and the full 16-command sweep under `/tmp/v24-m5-review5-checks` (`results.json` SHA256 `bb9e9b4d2a65445579c52967175088dfc5209ad4c743398e753e13840a2a7646`). The current-source manifest is now 11 files (including `sessions.py` and `test_backend_regressions.py`) with SHA256 `e144864a74cba1da1d84f3f0517bdefec4323ee9a274e111d790f27317c0d583`. No key is present, `MAX_SAFE_ARGS_BYTES` remains `None`, exec11/final-profile capacity remain unavailable, and the render contract remains a hard scope blocker. The fifth formal review subsequently accepted this snapshot for continuation only; see the fifth-review addendum. This record makes no completion or commit claim.

## Fourth review-fix addendum (2026-11-04, still INCOMPLETE)

The fourth formal Oracle group completed 2/2 static lanes without executing tests or a provider call. Lane 1 approved with fixes for continuation; Lane 2 requested changes. Export: `prompt-exports/oracle-review-2026-11-04-004611-new-chat-d3dafb-b350.md`. Coordinator dispositions:

| Finding | Source | Disposition |
|---|---|---|
| Capacity repeats could be established by separate files copying the same run; source identity covered only 11 UI files | L1/L2 P1 | accepted; every sample summary now requires a unique non-empty `run_id`; the audit recomputes `real._source_hashes()`'s full runtime map (`v24/load.py`, `s1/setup_db.py`, host/ui/plugin/skill/SQL files) and requires the recorded map to match that exact key set and bytes, not only the 11-file UI manifest. Negative tests cover reused run IDs, a mutated host/SQL/skill hash, and a missing runtime key. |
| Ten targets and three content classes were not all required; repeats could sit below the recommended threshold | L1 P1 | accepted; every target must have `ascii`, `cjk` and `escape` evidence, at least ten targets are required, `safe_args_bytes` is capped by the largest fully covered target, and repeats are counted only at/above `safe_args_bytes` and must equal `boundary_repeats>=2`. Tests cover missing class/targets and repeats below the threshold. |
| A probe summary with one dispatched success plus a cancelled undispatched continuation could be rejected; a second dispatched model was not explicitly rejected | L2 P1 | accepted; exactly one model with `dispatch_count==1` and `durable_status=='succeeded'` must carry the one actual-complete arg; additional model rows are allowed only with zero dispatches and `cancelled`. Positive and double-dispatch/ready/failed negatives were added. Exec11 also now requires completed status, empty guard rejections, bash/readback/durable/file checks and a current 8192-byte limit. |
| Present-but-malformed retained/baseline/checkpoint/browser manifests could crash before writing a result | L2 P2 | accepted; a guarded manifest parser appends `*_evidence_invalid` and still writes a rejected result. |
| Render docstrings still implied evidence-only derivation; cross-profile conversation rows are counted; README `/tmp` command is ambiguous; wire cap is hardcoded in the transport; exec11 predicate was thin | L1 P2 / L2 P2 | partially accepted. Exec11 and malformed-manifest handling were strengthened; the render blocker is intentionally unconditional and its docstring is a known wording nit. `_conversations()` may count rows from another profile, the README uses a literal `/tmp` example, and the offline transport asserts 512; these do not create a false acceptance and remain documented limitations. No production prompt/render change was made outside scope. |

Fourth-review repairs passed the targeted tests and the full 16-command sweep under `/tmp/v24-m5-review5-checks` (`results.json` SHA256 `bb9e9b4d2a65445579c52967175088dfc5209ad4c743398e753e13840a2a7646`). The final 11-file current-source manifest is `e144864a74cba1da1d84f3f0517bdefec4323ee9a274e111d790f27317c0d583`; the runtime source map is broader and is checked separately. The fifth formal review then accepted this repaired snapshot for continuation 2/2 with no P1; see the fifth-review addendum below. M5 completion remains unsupported.

## Fifth review addendum (2026-11-04, ACCEPT for continuation only)

The fifth formal Oracle group completed 2/2 static lanes without executing tests or a provider call. Both lanes returned **ACCEPT for continuation** and identified no P1. Export: `prompt-exports/oracle-review-2026-11-04-011511-new-chat-28e639-f00e.md`.

The lanes verified: unique capacity `run_id`s; full runtime-source hash equality; ten target sizes with all three content classes; safe-args capping and at/above-threshold repeats; one dispatched-success probe model with only zero-dispatch/cancelled continuations allowed; strengthened exec11 evidence; and guarded malformed-manifest handling. The unconditional render blocker was accepted as an explicit INCOMPLETE-scope blocker, not as completion evidence. Two non-blocking P2s remain documented: some referenced evidence payloads outside the guarded manifests can still raise before a structured audit result is written, and `audit_m5.py` retains pre-scope-blocker docstring wording. The README scratch example was corrected docs-only to use `mktemp -d` with a resolved physical path.

This is **not** M5 completion. The seven blockers still stand: no measured `MAX_SAFE_ARGS_BYTES`, no current-profile final-capacity/repeat recommendation, exec11 has no current successful write/bash/readback/final, the original52/pre-incident proof is lost, no accepted full UI/M5 completion review exists, and the shared prompt/footer/README render contract is unimplemented. No key is present. No staging, commit, push, amend, or main mutation is authorized.

## Sixth addendum (2026-11-04): bounded measurement repair, M5 still INCOMPLETE

The coordinator authorized one bounded measurement repair plus a budget recheck. This addendum records the actual change and evidence; it does not rewrite the earlier sections and does not claim M5 completion. No staging, commit, push, amend, or main mutation occurred.

| Change | Exact disposition |
|---|---|
| Real admission ceiling | `REAL_UI_LIMITS.body_byte_ceiling` is now 16384 (legacy/fake remain 8000). This is admission headroom for six real rounds; it is not a measured safe-args value, not a target body size, and not token/reserve safety. |
| Budget recheck | Retained 8192-snapshot write10 bodies 5,917/6,803/7,219/7,520 B used 1,893/2,110/2,207/2,265 prompt tokens (≈3.1–3.3 B/token). Five to six rounds project to ≈12–15k tokens, inside the unchanged 20,000-token run budget. A 16,384 B body is ≈5.2k input tokens, above the unchanged SQL 4,096-token reserve, so the ceiling is neither a target size nor a reason to change the reserve. |
| Probe escape family | `_probe_content(..., 'escape')` is now generated newline-terminated lines (`E0000\n` …) covering JSON `\n` escaping only. Quotes, backslashes and tabs are gone because exact-copy failure there measured model JSON fidelity, not capacity. `ascii`, `cjk`, and `escape` remain the three classes. Old escape summaries used different content semantics and cannot support the new final-profile capacity record. |
| exec11 prompt | The user prompt now requires the bash `command` verbatim, with no echo/chaining/pipes/quoting changes. Prompt and guard share `real.EXEC11_COMMAND`; the guard predicate was not relaxed. |
| Render contract | Previously a standing scope blocker. `catalog.limits_contract` is now the single renderer for `completion_cap`, `body_byte_ceiling`, and the safe-args state; the system prompt and footer both take runtime `UiLimits`, and an unmeasured safe-args value renders no number. The README marked block is synchronized. `audit_m5.py` derives the blocker from the renderer arguments/calls, the footer call site, and the README block; `test_audit_m5.py` reopens it for a stale README or a prompt without the shared call. This removes the render item from the blocker list only; the other six blockers stand. |

### Verification receipts (all offline; no provider call)

| Check | Result |
|---|---|
| `v24/ui/test_real_entry.py` | exit0, last line `[passed] M5 real entry offline contracts; WI2=workflows/probes/receipts; sockets=0; capacity=unmeasured`. Admission proved at 8000/8001/8048/8192/12000/16384 and rejected at 16385; offline exec11 now completes five sends on the current profile. |
| `v24/ui/test_audit_m5.py` | exit0, last line `[passed] M5 audit contracts; snapshot=3/NOT ACCEPTED; overwrite and tamper rejected; blockers derived`. |
| `v24/ui/test_ui_gate.py` | exit0, last line `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2`. |
| `v24/ui/test_backend_regressions.py` | exit0, last line `[passed] backend regressions; ... db_transport=unix`. |
| Full `run_m4_checks.py` sweep | 16 commands, exits=0, skips=0; last line `[passed] M4 private checks; commands=16; exits=0; skips=0; persistent_pgdata_untouched=true`; results `/tmp/v24-m5-review6-checks/results.json`, SHA256 `b54cd22f03ffc644cf6f5692bdc1c11b70b128304f301812bdc35f9e20380431`. |
| Snapshot audit | exit3, `[snapshot-consistent; NOT ACCEPTED] ... blockers=6`; errors `[]`; `full_render_contract=verified`; audit `/prompt-exports/v24-m5-evidence/wi3-checks-20261104T000632109861Z-snapshot/wi3-audit-snapshot.json`, SHA256 `c368f061b17bd812ce13ed6013f06ed358a9ed68c21cbd2b8b4f9ec179f1287e`. |
| Completion audit | exit1, `[failed] M5 audit; mode=completion_rejected; errors=6; blockers=6`; errors are the six blockers below; audit SHA256 `a9aac9c096882433105ed7b6cca16ebf85da415cc4a1865b9bb60512ac0051d1`. |
| Current-source manifest | SHA256 `995f5eb832d2cd8edf35689b9f9d9fb27b47f068831c6d8c7e8c03333f1c146d` (both audit runs). |

### What remains blocked

`DEEPSEEK_API_KEY` and `OPENAI_API_KEY` are absent. The authorized 10 targets × 3 classes matrix, the at/above-safe boundary repeats, and the exec11 rerun were **not run**; `MAX_SAFE_ARGS_BYTES` remains `None` and must not be guessed. The six derived blockers are: `max_safe_args_bytes_none`, `current_exec11_guard_rejected_before_write_bind_bash_readback_final`, `final_profile_capacity_repeats_and_recommendation_incomplete`, `original52_pre_WI1_baseline_proof_lost`, `WI1_preincident_PGDATA_logical_equality_unproven`, and `full_UI_acceptance_and_formal_M5_review_not_accepted`. The exact command matrix is in `v24/ui/README.md` under “Final-profile measurement matrix”. Current-environment invocation prints `credentials_absent` and exits 2 without an adapter or database.

The audit receipts above were produced before the last documentation edits, so their recorded `deliverable_sha256` values are snapshots taken before the final text; the source, render-contract, and evidence checks they performed are unchanged, and rerunning the audits reproduces the same verified render contract and six blockers.

## Seventh addendum (2026-11-04): measured closeout candidate

The coordinator supplied the real provider key and authorized the measurement. All runs used `python -m v24.ui.real --real-provider-smoke --profile current` with a fresh private evidence directory per call; no test script opened a provider socket. The code under test is the post-render-contract, post-escape-family revision with `REAL_UI_LIMITS.body_byte_ceiling=16384`, `completion_cap=512`, SQL reserve 4096, and `MAX_SAFE_ARGS_BYTES=160`.

| Item | Result |
|---|---|
| Pilot | 64/96/128/160/192 all passed for ascii/cjk/escape; 224 ascii hit `finish_length`; 256 cjk was contract-incomplete. |
| Authoritative matrix | Targets 64,72,80,88,96,104,112,120,128,136,144,160 × ascii/cjk/escape = 42 probes, 41 `contract_passed`. The only failure was the second repeated 160 B ascii probe (`finish_length`, 512 completion tokens). |
| 160 B repeats | 160 B has eight successful samples (ascii base+1 repeat, cjk/escape base+2 repeats); capacity boundary repeats = 5. |
| Capacity record | `prompt-exports/v24-m5-evidence/wi3-final-capacity-summary.json`, SHA256 `b60279dc02901bdff34565f7743af91ae2949e5dc533451bb31df4265eafd91f`; 12 complete targets, 41 samples, source hashes equal the audited runtime map. |
| exec11 | First attempt after the source finalization failed `duplicate_bash` (second bash rejected before any second side effect). A fresh retry `v24-real-4ajjmgv5` completed: 5 HTTP, write → bash → readback → final, all checks true, `guard_rejections=[]`; SHA256 `d8b3651dc0cc20876cbf3bbfc0d30cd4231516df98bfd8b330c6a687c90961b8`. |
| Backfill | `catalog.MAX_SAFE_ARGS_BYTES=160`; prompt, footer and `surgical-edit` skill render from it; `test_ui_gate.py`, `test_real_entry.py` and `test_audit_m5.py` updated; prompt SHA256 is now `44f41835462a72a4adbe325a81d2829b3b30c9aca9229be90476cbc45c4439a9`. |
| Offline gates | `test_real_entry.py` exit0 (`capacity=measured:160`); `test_ui_gate.py` exit0 (`steps=10; effects=5; artifacts=2; families=2`); `test_audit_m5.py` exit0; `test_backend_regressions.py` exit0; `run_m4_checks.py` 16 commands exit0/skips0. |
| Completion audit | Exactly three blockers remain: `original52_pre_WI1_baseline_proof_lost`, `WI1_preincident_PGDATA_logical_equality_unproven`, `full_UI_acceptance_and_formal_M5_review_not_accepted`. exec11, capacity, safe args and the render contract are cleared. |

The two historical proof blockers are not product defects and cannot be reconstructed: the original `/tmp` baseline and WI-1 logs are gone. They must be recorded as coordinator-accepted evidence-loss deviations (D-UI-14/D-UI-15), not replaced by synthetic proof. The formal review is the only remaining actionable item. This snapshot is uncommitted; no staging, commit, push, amend or main mutation occurred.

## 第八次补充：首次正式复审 REJECT 后的 128 修订（2026-11-04）

首次正式复审 2/2 lanes 均要求修改；上一条 160 记录保留为历史，不删除。修订后的最终状态：

- `MAX_SAFE_ARGS_BYTES=128`（`catalog.py`），prompt/footer/skill 由 `limits_contract` 单一来源渲染；README marked block 同步为 128。
- 最终权威批次在最终源码上重跑：13 个 base target（64–124 混合步长）× 三类 + 128 B 每类 2 次重复 = 45 probes（45/45 passed、0 excluded、0 failed）；14 complete targets，3 boundary repeats。capacity 记录 SHA256 `b2b400b9aed765e90a0c012211207431e9d15d971847ff395c9827ed332910dc`，`attempts` 45/0/0/0（sampled/excluded/failed/infrastructure）。
- exec11 `v24-real-k5a0wn53`（SHA256 `e5411fb32ea2e10473a2eefc9539a859d53649b71c462706ca57bf1abb89bb3f`），5 HTTP，全部检查 true，`guard_rejections=[]`。
- **循环性披露：** 128 批次运行时 prompt 已写 128，故它测量的是合规/稳健性，不是无提示的容量发现；160 批次与 224 pilot 仅作历史。
- 16384 补记 D-UI-17（取代 D-UI-11 的 8192-only 许可）；audit 增加 attempts/失败登记、render 关键字转发 AST 检查、pre-commit-only 说明；runner 与 audit 的 13 文件 source 清单一致。
- 离线 gates 全绿：`test_real_entry`（`capacity=measured:128`）、`test_ui_gate`、`test_audit_m5`、`test_backend_regressions`；M4 runner 16/16。
- completion audit 仍只剩 3 个 blocker：`original52_pre_WI1_baseline_proof_lost`、`WI1_preincident_PGDATA_logical_equality_unproven`、`full_UI_acceptance_and_formal_M5_review_not_accepted`。两处历史证据不可恢复，未伪造；第二次 2/2 已于 2026-11-04 09:32 复审 REJECT（gate receipt 未强制 + 文档数字矛盾），修复后等待第三次 2/2。
- 未暂存、未提交、未 push。

## 第九次补充：gate receipt 强制、accounting/forwarding 硬化与文档校正（2026-11-04）

第二次 2/2 复审（`prompt-exports/oracle-review-2026-11-04-093239-new-chat-ee3520-0a96.md`）两个 lane 均 REJECT：standalone completion 未强制 gate receipt，matrix 表/D-UI-17/README 的 exec11 数字与记录矛盾；另有 exclusion、canonical 去重、batch inventory、infrastructure 空白理由、forwarding 旧常量和默认值未校验等 P2。本轮逐项修复，未触碰任何 request-shaping 生产源（`app.py`/`catalog.py`/`control.py`/`real.py`/`provider.py`/`sessions.py` 等），capacity/exec11 的 45 样本与 5 HTTP 证据不需要重测。

- **Gate receipt 强制。** `run_m5_checks.py --completion` 在调用 audit 前写 `gates.json`（schema `m5-gates-v1`）：五个 gate（`real_entry`、`ui_gate`、`audit_contracts`、`backend`、`m4`）的 exit、log SHA256、last line、before/after 全量 runtime source map，文件 0600。`audit_m5.py --completion` 新增 blocker `current_gate_receipt_missing_or_failed`：缺文件、schema/names 不符、任一 exit≠0、log 哈希或 last line 不符、或 source map 不等于当前全量 map，均阻止 acceptance；audit 结果记录 `gate_receipt.sha256`。snapshot 不要求该 receipt，仍只列三项证据 blocker。
- **Capacity accounting。** 低于或等于 recommendation 的失败只能归入 failed，不得以 `incomplete_target` 排除；排除仅允许 target>safe 且非 complete。所有 sample/excluded/infrastructure/failed 共用 canonical resolved path 与 run ID 唯一性。inventory 以 capacity 记录里的完整 source map 精确对账：45/45，少一个/多一个/重复引用都拒绝。infrastructure 必须 `measurement_reason='transport'` 且 ≤10%；accepted failure 与 `finish_length` 比例 ≤10%；`finish_length_rate` 必须精确等于 `n/total`。
- **Forwarding 校验。** prompt 的 `completion_cap`/`body_byte_ceiling`/`max_safe_args_bytes` keyword 必须是同名参数（拒绝 `BODY_BYTE_CEILING`）；footer 必须转发 `self.completion_cap`/`self.body_byte_ceiling`，safe-args 省略时其默认常量已被单独校验；app wrapper 必须转发全部三参数，turn 调用点必须传 runtime 属性；`limits_contract` 与 prompt 默认值、skill 静态 `MAX_SAFE_ARGS_BYTES=128` 均断言。新增 footer 省略、footer legacy 常量、prompt legacy 常量、skill stale 值反例。
- **文档。** matrix 的 M5 contract 表改为 current 2026-11-04；D-UI-17/README 改为 canonical bodies 6,498 / 7,416 / 8,080 / 8,434 / 8,734 B（wire max 8,751）、12,265 tokens（remaining 7,735），round 4–5 超 8192、round 3 不超；stale "second 2/2" 改为 third。skill 明确为 synchronized static mirror，不再声称动态 render。
- **本轮 pre-review receipt。** `prompt-exports/v24-m5-evidence/wi3-checks-*-completion/`；the current completion receipt；audit `wi3-audit-completion.json`；runner log SHA256 `2cc3ba1312c0d14053216f216958fb6541ee76e4cfb4c1e01943cc880756e48c`。五个 gate 全部 exit0、source_unchanged=true；audit `completion_rejected`，`gate_receipt.failures=[]`，仍剩 3 个 blocker（original52、WI-1 pre-incident、formal review）。
- **代码 source hashes。** `v24/ui/audit_m5.py` `(see current source map)`；`v24/ui/run_m5_checks.py` `1f82407df76aee1a2c7f368fc041e9d736796ac2189417f9b75abe1f0db2c271`；`v24/ui/test_audit_m5.py` `(see current source map)`。这些文件已从 measurement binding 的 request-source 子集中排除；全量 map 仅用于 gate receipt/snapshot 身份。
- 未暂存、未提交、未 push；第三次复审已请求，结果记录在 `prompt-exports/v24-m5-evidence/m5-formal-review.json`（可用时）。

## 第十次补充：第三次复审 partial（1/2）与 review-binding/wrapper 修复（2026-11-04）

第三次 `ask_oracle` review group 中，`claude-opus-5-5` lane 因 provider 401 失败，`gpt-6.1-sol-xhigh` lane 完成并 REJECT，因此该 group 不是有效的 2/2，只能作为单 lane 静态审查。完成的 lane 确认 gate receipt、capacity 排除、exec11 与三 blocker 状态；同时提出两个 P1：

1. **Formal review 绑定过窄。** `completion_blockers()` 仍用 `request_source_hashes()`（44 个 request-shaping 文件）校验 review record，因此 audit/runner/test/docs 改动后旧 review 仍有效。已新增 `review_source_hashes()`：全量 runtime map + `DOCS` + `NEW`（含 checkpoint），review record 的 `source_sha256` 必须与当前 map 精确相等；measurement 仍用较窄的 request 子集，两者分开。`test_audit_m5.py` 增加 review-docs / review-code / runtime-subset 反例。
2. **App wrapper 只查名字出现。** 旧检查收集 wrapper 参数里的 `Name` 集合；`BODY_BYTE_CEILING if body_byte_ceiling is None else BODY_BYTE_CEILING` 或交换位置仍可通过。现要求 wrapper 签名恰为 `skills_block, history, completion_cap, body_byte_ceiling, max_safe_args_bytes`，三个默认值均为 `None`，调用恰为 5 个位置参数，且每个都是精确的 `DEFAULT if param is None else param`；新增交换位置与 legacy non-default branch 反例。
3. 单 lane P2 的测试隔离已修：`missing_class`/`too_few_targets`/`too_few_repeats` 同步 attempts 与 inventory，`repeats_below_safe`/`duplicate_pairs` 同步 sample 元数据，新增跨类别 duplicate run ID 反例。文档当前介绍改为 128，matrix skill 行改为 synchronized static mirror；所有运行型 receipt 数字只作为 2026-11-04 03:40 pre-review 快照，最新值以 `m5-formal-review.json` 与 receipt 目录为准。

当前代码 hashes：`v24/ui/audit_m5.py` `(see current source map)`；`v24/ui/run_m5_checks.py` `1f82407df76aee1a2c7f368fc041e9d736796ac2189417f9b75abe1f0db2c271`；`v24/ui/test_audit_m5.py` `(see current source map)`。未暂存、未提交、未 push；第三次复审的配置主 lane 因 provider 401 不可用；独立完成的 lane 与最终结果记录在 `prompt-exports/v24-m5-evidence/m5-formal-review.json`，不伪造 group 2/2。

## 第十一次补充：transport 排除、负面 fixture 隔离与静态 skill 文案（2026-11-04）

第三次复审的完成 lane 在 11:37 给出 ACCEPT for continuation，但保留两个 P2；同时指出 transport 失败可伪装成 `excluded` 绕过 infrastructure 上限。本轮修复后仍未触碰任何 request-shaping 生产源或测量证据。

- **Transport 不得排除。** `capacity_samples_match()` 的 `excluded_samples` 分支新增 `measurement_reason in ('target_missed','finish_length')`；`transport` 只能进入 `infrastructure_samples`，否则 `capacity_samples_match=false`。新增 `excluded_transport` 反例（700 B、`transport`、`incomplete_target`），并与已有 `infrastructure_transport` 正例配对。
- **Fixture 隔离。** `too_few_targets` 改为 30 个有效样本、9 个 complete target、3 个 boundary repeat，只违反 10-target 规则；`cross_category_duplicate_run_id` 的失败样本改用已接受的 `target_missed`，只违反跨类别 run-ID 唯一性；`failure_miss_at_safe` 作为唯一 ID 正例保留。
- **Credential scan 覆盖。** `scan_paths` 纳入 `M5_AUTHORIZED`（含 `test_ui_gate.py` 与 `skills/surgical-edit/SKILL.md`）；`test_ui_gate.py` 的 bearer 示例改为 `synthetic-token-shaped-example`，避免把测试夹具误报为凭据。
- **静态 skill 文案。** README 与 D-UI-13 改为 prompt/footer 由单一常量渲染、`SKILL.md` 是 audit 校验的 synchronized static mirror，不再声称 skill 动态渲染。
- **Inventory 与 source binding。** `capacity_samples_match()` 的 inventory 不再要求 summary 的 full source map 等于 batch 的 56 文件 map；它使用与 measurement freshness 相同的单一 `is_verification_path()` 谓词过滤 recorded map，再做**精确** request-source 相等比较——多一个 production skill 就拒绝，只多 `test_new.py` 等 verification 文件则通过。inventory 也不再按 target 或 `source_unchanged` 过滤，而是计入所有匹配 probe；历史批次只由精确命名且 SHA256 固定在 `CAPACITY_EXEMPT_MANIFESTS` 的 `wi3-final-capacity-summary.run{1..5}-superseded.json` 与 `wi3-final-capacity-partials.json` 明确列出并跳过。新增 `omitted_failure_verification`（512 B，首个样本之前）、`omitted_undeclared_target`（76 B）、`removed_production_source`、`unapproved_manifest`、`unapproved_run_manifest`（`run999`）必须拒绝；`superseded_extra`/`partials_extra`/`excluded_valid_above_safe`/`verification_extra` 正例必须通过。
- **Matrix digest 标注。** Offline gates 行的 receipt/audit hashes 统一记录在 `m5-formal-review.json`，避免 per-run 值再次过期。
- **本轮 pre-review receipt。** `prompt-exports/v24-m5-evidence/wi3-checks-*-completion/`；the current completion receipt；audit `wi3-audit-completion.json`；the current receipt JSON；runner log SHA256 `2cc3ba1312c0d14053216f216958fb6541ee76e4cfb4c1e01943cc880756e48c`。五个 gate 全部 exit0、source_unchanged=true；audit `completion_rejected`，`gate_receipt.failures=[]`，仍剩 3 个 blocker。
- **代码 source hashes。** `v24/ui/audit_m5.py` `(see current source map)`；`v24/ui/run_m5_checks.py` `1f82407df76aee1a2c7f368fc041e9d736796ac2189417f9b75abe1f0db2c271`；`v24/ui/test_audit_m5.py` `(see current source map)`；`v24/ui/test_ui_gate.py` `(see current source map)`。
- **Review numbering（后续说明）。** 第十/十一次补充记录的是 provider 401 时的 interim partial/gpt-only 状态；provider 恢复后，同一个 third review 最终以 2/2 完成，后续第四轮也 2/2 完成。历史段落保留当时状态，不再代表当前结论；最终结果记录在 `prompt-exports/v24-m5-evidence/m5-formal-review.json`。
- 未暂存、未提交、未 push。

## 第十二次补充：历史证据放弃与 M5 收尾（2026-11-04）

协调者按用户本次直接指示，放弃两处不可恢复的历史证据，不再要求重建，并记录该事实：

- `original52_pre_WI1_baseline_proof_lost`：原始 `/tmp` baseline 与 WI-1 日志已丢失；resume 快照只能证明 resume 之后的限定比较，不能升级为 original52 证明。
- `WI1_preincident_PGDATA_logical_equality_unproven`：保留的日志无法重建 incident 前的 PGDATA 逻辑相等；历史 incident 记录保持不变。

放弃记录为 `docs/reviews/v24-ui-m5-evidence-abandonment-2026-11-04.json`（schema `m5-abandoned-evidence-v1`）。它**不是 proof**：`synthetic_proof=false`，两项均为 `status=abandoned`、`proof=unavailable`，并写明没有合成 baseline 或逻辑相等证明。`audit_m5.py` 只在记录合法且恰好列出这两项时，才把它们从 completion blocker 移除，并在审计结果的 `abandoned_evidence` 中继续列出；记录缺失、schema/decision/synthetic_proof/decided_by/status/proof/reason 任一不符、id 缺失或重复，都 fail closed，两个 blocker 恢复。`test_audit_m5.py` 覆盖 valid 与上述全部反例。

放弃只解除这两条历史 proof；completion 仍要求当前五 gate receipt、exec11、final-profile capacity、safe-args、render contract，以及绑定当前 runtime + `DOCS` + `NEW` 的 2/2 正式复审。此前所有 “INCOMPLETE / completion cannot exit 0 / no waiver file” 表述保留为其时点记录，本节是新的、有日期的协调者决定。最终五个 gate、completion audit 与正式复审的路径/SHA256 记录在 `prompt-exports/v24-m5-evidence/m5-formal-review.json`。

本次用户明确指示提交并推送 `v24/ui-chainlit`；该直接指示取代此前“本分支不 push”的约定，仍不修改、不切换、不 force-push `main`。
