# v24 Chainlit UI conformance matrix (2026-11-02)

Current status: **M5 closeout with abandoned historical evidence (2026-11-04).** The final post-review snapshot uses `MAX_SAFE_ARGS_BYTES=128`: 13 targets 64–124 plus two additional 128 B probes per class (one repeat each), 45 probes, 45/45 passed; 14 complete targets; exec11 completed five HTTP requests with no guard rejection. The two unrecoverable historical proofs (original-52 baseline, WI-1 pre-incident logical equality) are abandoned by the dated coordinator record `docs/reviews/v24-ui-m5-evidence-abandonment-2026-11-04.json`; the audit reports them under `abandoned_evidence`, never as proof, and does not count them as blockers. The current completion receipt under `prompt-exports/v24-m5-evidence/` has five gates exit0 and `source_unchanged=true`, with `gate_receipt.failures=[]`; exact receipt paths and SHA256 values are recorded in `prompt-exports/v24-m5-evidence/m5-formal-review.json`. The first two formal reviews rejected the 160 claim and then the 128 snapshot; the third and fourth completed 2/2 with inventory and source-binding P1s, since repaired; the final review of this closeout is recorded in the same JSON. The 2026-11-02/03 and earlier-2026-11-04 sections below are dated checkpoint history; where they say `None`, `BLOCKED`, `160`, `six blockers` or `no waiver file`, they are superseded by this status and by the closeout snapshot at the end of this file.

| M5 contract (current at 2026-11-04 post-measurement) | Evidence / disposition |
|---|---|
| Real defaults/entry/credential/preflight/IDLE | `test_real_entry.py` exit0; key → actual adapter → preflight → empty scratch → resources covered; real UI defaults to `read`; provider factory split to `provider.py`. Admission is proved at 8000/8001/8048/8192/12000/16384 and rejected at 16385 for the real profile. |
| Existing deterministic regressions | Pre-review receipt `wi3-checks-*-completion` records five gates: `real_entry`, `ui_gate`, `audit_contracts`, `backend` and the full `run_m4_checks.py` sweep (16 commands, exits=0, skips=0, Node `--node`). Each gate carries exit, log SHA256 and before/after full runtime source maps; the current completion receipt; completion refuses to pass without this receipt. |
| Current real workflows | short1/write10 4/skill2 HTTP calls completed on the 8192 snapshot; current-profile exec11 `v24-real-k5a0wn53` completed five HTTP requests with `write → bash → readback → final` and no guard rejection. `MAX_SAFE_ARGS_BYTES=128` came from the later 45-probe batch. |
| Capacity | Real ceiling 16384 is admission headroom only; the SQL 4096 reserve is unchanged and a 16,384 B body would exceed it. Current record: 13 targets 64–124 × three classes plus two additional 128 B probes per class (one repeat each) = 45 probes, 45/45 passed, 14 complete targets, 3 boundary repeats, 0 excluded/failed/infrastructure. The 160 B batch (41/42) and 224 B pilot remain historical; the 128 batch ran while the prompt already rendered 128, so it is compliance/robustness, not an unprompted threshold. |
| Display consistency | `catalog.limits_contract` renders `completion_cap`, `body_byte_ceiling` and the safe-args state from the runtime `UiLimits` for the system prompt and footer; the marked README block matches 8000/16384/512/4096/128. `SKILL.md` is a synchronized static mirror of 128, not a runtime renderer. The audit checks exact prompt/footer forwarding, defaults and the skill value; `test_audit_m5.py` rejects stale README, hardcoded/swapped prompt values, footer constants and a stale skill. |
| Audit / evidence safety | `audit_m5.py` creates output with O_EXCL; snapshot exits3/NOT ACCEPTED and lists any remaining blockers plus `abandoned_evidence`; completion additionally requires the current five-gate receipt before deriving blockers. The two historical proofs are removed from blockers only when the dated abandonment record is complete and exact (`m5-abandoned-evidence-v1`, `decision=abandoned`, `synthetic_proof=false`, both ids `status=abandoned`/`proof=unavailable`); malformed, missing or duplicate records fail closed. `test_audit_m5.py` covers overwrite/tamper, gate-receipt mutations, exclusion/omission/alias counterexamples, forwarding regressions and abandonment mutations. CLI evidence dirs inside the repo are limited to `prompt-exports/`. |
| Preservation | New audit reports tracked HEAD/resume and 55 captured untracked minus2 source edits separately. The original-52 baseline and WI-1 pre-incident equality are unavailable and are abandoned, not reconstructed; the abandonment record is `docs/reviews/v24-ui-m5-evidence-abandonment-2026-11-04.json`. |
| Browser / review / completion | Coordinator browser receipt proves translated `credentials_absent` (“凭证缺失”), harmless submission, and HTTP200 after; receipt source matches the historical WI-2A snapshot, not post-review sources. The first two formal reviews rejected (160 claim, then 128 docs/audit); the third and fourth completed 2/2 with inventory and source-binding P1s, since repaired. The final review of the closeout binds the current runtime and closeout documents and is recorded in `prompt-exports/v24-m5-evidence/m5-formal-review.json`; the two abandoned proofs stay visible as `abandoned_evidence`, not as proof. |

Historical status at M4 repair closeout: **M4 review repairs accepted: final independent Oracle review passed 2/2, with no remaining blocker (2026-11-03).** Round-1 integration review did not pass; its blockers remain historical evidence. Commit policy is one separate local repair commit on `v24/ui-chainlit` after closing checks; no push or M5 work. The [repair evidence record](v24-ui-m4-review-fixes-2026-11-03.md) is the current inventory and test-command source.

## M4 round-2 repair coverage (2026-11-03; final review passed)

The first repair integration review completed 2/2 lanes. L1's no-P1 conclusion is rejected against two subsequently reproduced L2 paths; earlier test GREEN is not integrated acceptance. The targeted plan completed only L2 (1/2); L1 failed with provider_error/no response. [The repair record](v24-ui-m4-review-fixes-2026-11-03.md) inventories all44 review items and all23 initial-plan and28 recovery-candidate items. Recovery providers returned2/2, but L1 supplied only analysis; L2's required os.waitid is absent in the local runtime, so the separated-group candidate was stopped before artifact edits. The final same-group consultation completed2/2; its27 material items are also inventoried. The parent coordinating agent selected live supervisor as PG leader, same-group shell and trusted private real-rc status followed by self-KILL; valid statuses uniformly expect supervisor-9. No waitid/split-group layer. Final artifact/UI/Backend wrappers all exited0 without SKIP; exact receipts are in the repair record. Normal SPAWN/EXIT requires trusted status,-9,EOF,reap and absent group; unsolicited STOP is unknown.

Final independent review of snapshot `2026-11-03/1537` completed 2/2: both lanes permit committing, no remaining blocker. [Final reconciliation](v24-ui-m4-review-fixes-2026-11-03.md#final-independent-review--pass) checks every material claim and records optional memory/drain/timing limits. Parent verified all 17 receipt hashes/last lines/exits, with no SKIP; S13 reuse is explicitly identified.

| Requirement / check | Round-2 current state |
|---|---|
| Main-shell exits before artifact kill / same-group background child | Final GREEN: held main-shell-exit windows confirm shell absent/artifact live before PID-only and group kills; artifact-9, sentinel=false, group absent. Supervisor-only death fallback also returns unknown and cleans group. |
| Inner shell Popen OSError | Final GREEN: injected inner Popen OSError becomes known io_error/exit3 without traceback/private text. Bad/missing/duplicate/oversized/out-of-range/mismatched/read-fault statuses are unknown; legal1/7/9/127/247 remain successful. |
| Review honesty / diagnostics | Gate print now points to actual Backend blank-answer coverage; runner records actual argv and reproduction separately. Final UI marker and wrapper receipts confirm both; actual Backend entry/positive control passed again. |
| Shared fixed messages / extension validation | Final GREEN: exact BashOutputLimitError type maps one fixed public constant; arbitrary detail stays generic. Invalid extensions return invalid_arguments before root/walk, with zero helper calls. |
| Precommit audit / whitespace | Audit explicitly applies only to uncommitted baseline tree and checks the five authorized new files' trailing whitespace/EOF blanks. Final post-doc round-2 audit receipt is in the repair report; no postcommit replay claim. |
| Limits and scope | Same14 paths; caps stay independent and unchanged. Old spill eviction and single-line line_too_long documented; no new tool surface via unused spill_read helper. |

## Round-1 repair execution coverage — historical, review did not pass

| Requirement / check | Round-1 execution evidence |
|---|---|
| Complete skills under write10 and exec11 | Final four-case GREEN: 20 actual builds/sends, 36 durable effects, full 570/533 B skill → small-file read → edit → readback → final. Bodies 7,380–7,741 B; minimum body headroom 259 B. Full history and pins retained. |
| Historical exact ten steps / double requires semantic wall / 2001B continuation | Final UI GREEN, exact historical marker retained. Complete 8001 B actual-app tool result persists before rejection; SessionStore retains three complete finals before measured fourth-turn refusal, with no trimming. |
| Bash large-output/full-spill, host termination, paged spill reuse, search accounting | Final artifact regressions GREEN: complete 1,230,027 B spill reconstructed by both readers; silent host-kill sentinel suppressed and group absent; immutable snapshot reuse/race probes, skip counts and filter constraints passed. Ordinary file limit remains 1 MiB; managed spill limit 4 MiB. |
| Backend real empty answer / restart / frontend / close | Final-source expanded Backend GREEN, read7/exec11 each across three actual processes, real blank answer zero-RPC/positive control, old-binding read-only, steer/cancel, mocked frontend and targeted pre-dispose recovery. Broader closure/browser limits remain. |
| S13 compatibility | Fresh 13/13 exit 0, explicit `test_node.py --node`, no SKIP. All commands/exact last lines/logs in [the repair record](v24-ui-m4-review-fixes-2026-11-03.md). |
| Freeze / review / commit | Post-doc audit entry checks 1,451 tracked / 52 original untracked files against explicit 9-tracked/5-new whitelist, unchanged caps/shared core and branch/main/index. Final execution receipt is in the repair report. At that checkpoint review was pending; it subsequently requested changes as recorded above. HEAD remains `f4b95d4`, no new commit/push or M5. |

Historical closeout status at `f4b95d4`: **M4 final acceptance was recorded as GREEN (2026-11-03).** The final UI gate exited 0 with `steps=10; effects=5; artifacts=2; families=2` (SHA256 `312c6e2b8521c99f13dd1f2012a0a4368d83b29e29ba71a2e165adb19929704b`); the 13 authorized S13 executions all exited 0 including explicit `--node`; the final M3 aggregation passed 12/12 checks with read7 and exec11 each in three distinct actual processes (SHA256 `d82389ab0768c2b17ae0d837272e80d393cc0e2d78dcb38115bc0c4970bbac2e`); browser §6.3 is 8/8 with a real database close proof; the integrated review completed 2/2 lanes with B1/B2/skill A8 resolved; and the pre-doc-final source audit passed (2,143 snapshot path hashes, 1,449 tracked blobs, 10 authorized tracked changes + 2 new skill files, 52 original untracked hashes unchanged, empty index, `main` unchanged, no browser-token leak). Acceptance baseline: HEAD `243dd9d33cc54725955709f10e162f153757141d`; `main` `1143dce6da0572bccab083da9a6be0175210b062`. That local M4 closeout was committed as `f4b95d4a46e55e0e2b5bb2f6dde3d6d66b23cd35`; it was not pushed. M5 has not started; `MAX_SAFE_ARGS_BYTES` remains `None`. Historical RED/NOT RUN/preflight-BLOCKED and interim-pending records below retain their original dates and scope.

Preparation exception (2026-11-02): `open_env()` now supplies default `V24_SKILLS_ROOT` while retaining explicit values. Disposable mocked-server default/explicit checks passed; existing `uv run python v24/ui/test_ui_gate.py` exited 0, last line `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` (log `/tmp/v24-m3-prep-ui-gate.log`). Skill mounting remains M4.

## Historical M1 acceptance (scope at execution time)

Scope was M1 only. W9 was green before that work; M2 had not started. The following S13 commands verify compatibility after D-UI-6.

| Acceptance | Actual command | Exit | Last line / observed result |
|---|---|---:|---|
| Persistent init | `uv run python -m v24.ui.env --init` | 0 | `{"status": "ok", "loaded": ["already_initialized"]}` |
| Persistent status | `uv run python -m v24.ui.env --status` | 0 | `{"status": "ok", "diffs": [], "db_name": "agent_v24_ui"}` |
| Migration boundary | `uv run python -m v24.ui.env --migrate` | 2 | `migration_unsupported` |
| Disposable helper/persistence proof | `PYTHONPATH=/Users/wxl/Projects/pg-agent uv run python /tmp/v24-m1-disposable.py` | 0 | `[disposable] migrate=2 migration_unsupported; drift=2; reset --yes=0; persistent state untouched` |
| Existing D-UI-6 before | `uv run python -m v24.ui.d_ui_6_acl --check` | 0 | `{"status": "preupgrade"}` |
| Existing D-UI-6 apply | `uv run python -m v24.ui.d_ui_6_acl --apply` | 0 | `{"status": "completed"}` |
| Existing D-UI-6 after | `uv run python -m v24.ui.d_ui_6_acl --check` | 0 | `{"status": "completed"}` |
| Runtime | `uv run python -m v24.ui.control --selftest` | 0 | `[effect] id=9a828def-443a-3e6c-fee6-f74d6af4afb9 kind=model_call status=succeeded ordinal=0 created_at=2026-11-02T00:30:39.8538+08:00` |
| Oracle correction checks | `PYTHONPATH=/Users/wxl/Projects/pg-agent uv run python /tmp/v24-m1-review-checks.py` | 0 | `[passed] disposable CLI empty-init recovery, SQL/OID/manifest drift, lock=3, migrate=2, reset drift=0; persistent untouched` |

The temporary diagnostic scripts exercised disposable servers only. Their observed cases: create-only/idempotent init, exactly ten tables, failed-initial-init recovery, SQL/OID/fingerprint/manifest/version drift, lock exclusion, unsupported migration, explicit reset, all three helper states, unexpected PUBLIC ACL rejection, activation rejection cleanup and incomplete-close state retention. The persistent helper sequence ran only after disposable proof. OID `4785566` and fingerprint `0f1b51ffafbdebe1facdc0d89bda27a872c1caa8881a1b52e02a7545ac1e9285` were unchanged; only the permissions and manifest digests in loaded.json were rebound.

The final selftest printed run `31c5aefd-5bc5-4d90-95f9-280352728cdf`, completed with `done`, exactly `{read}` pins and tools, an actual succeeded read with exact fixture output, and unspent token samples `[20000,19995,19995,19990]` (10 spent). Same-scope second start `914fb23e-7c21-43cb-adb3-50f936f95d39` committed and completed. Three durable effect IDs/kinds/statuses/ordinals/timestamps were printed. Python/SQL RPC errors rolled back to IDLE, and returned rejected domain envelopes committed. A separate in-memory pagination check verified 1-based offsets 1/2/3, complete lines and continuation offsets 2/3; Pi's original read descriptor confirms 1-indexed semantics.

| Affected gate command | Exit | Exact last line |
|---|---:|---|
| `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| `uv run python v24/s9/test_g8.py` | 0 | `[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)` |
| `uv run python v24/cordis/dp4/test_closeout.py` | 0 | `[passed] CDP4-B` |
| `uv run python v24/cordis/dp4/test_loop.py` | 0 | `[passed] CDP4-T` |
| `uv run python v24/cordis/dp4/test_reducer.py` | 0 | `[passed] CDP4-M` |
| `uv run python v24/cordis/dp4/test_run.py` | 0 | `[passed] CDP4-R` |
| `uv run python v24/cordis/dp5/test_boundaries.py` | 0 | `[passed] CDP5-B (W5: B1-B6 final layout, ACL, capacity, seed/closure, bounds, frozen)` |
| `uv run python v24/cordis/dp5/test_dispatch.py` | 0 | `[passed] CDP5-D (W3: D1-D12 atomic producer, five modes, host path, fences, limits)` |
| `uv run python v24/cordis/dp5/test_listeners.py` | 0 | `[passed] CDP5-E (W2: E1-E7 registration/revocation subset; ordering/unavailable/real drain are W3 D evidence)` |
| `uv run python v24/cordis/dp5/test_resolution.py` | 0 | `[passed] CDP5-R (W4: R1-R8, five-mode reference, purity and host premises)` |
| `uv run python v24/cordis/dp6/test_boundaries.py` | 0 | `[passed] CDP6-B (W5: whole layout/ACL, three interpreters/terminal/replay/slot, closure/successor/protocol bounds, frozen surfaces)` |
| `uv run python v24/cordis/dp6/test_dispose.py` | 0 | `[passed] CDP6-U/D` |
| `uv run python v24/cordis/dp6/test_recovery.py` | 0 | `[passed] CDP6-R` |
| `uv run python v24/cordis/dp6/test_scanner.py` | 0 | `[passed] CDP6-S` |
| `uv run python v24/cordis/dp6/test_upgrade.py` | 0 | `[passed] CDP6-H` |

| S13 command (all 13 required gates) | Exit | Exact last line |
|---|---:|---|
| `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` |
| `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` |
| `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` |
| `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` |
| `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21` |
| `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` |
| `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` |
| `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` |
| `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` |
| `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` |
| `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` |
| `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` |
| `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` |

Additional Node vector command `uv run python v24/s13/test_vectors.py --node` exited 0; exact last line: `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked`.

D-UI-6 retains BASE `57e2c1e` and the full load/sql/S1–S12 scope. Exactly six M paths are accepted: permissions SQL, S1 test_g1, S9 test_g8, and immutable historical S9/S10/S11 READMEs. The first three use unique literal substitutions of raw BASE bytes; the README source commits/blobs/SHA256 are pinned in the plan and ledger and their bytes were not edited. DP5 and DP6 each printed `[D-UI-6] exact six M paths; immutable provenance and in-memory negatives passed`. Negatives reject extra bytes, missing/seventh paths, non-M status, admin removal/PUBLIC/another SQL-line mutation, old S1 denial, old S9 count/negative assertion and README mutation. All twelve SQL hashes remain checked with only the permissions hash changed. S13 retains BASE `c8c4bd0`, twelve frozen paths, whole-module renderer AST comparison stripping exactly five W9 additions, and `[scope] passed base=c8c4bd0 checks=6`. DP4 retains its original BASE/scope and an exact permissions-byte exception.

The mandatory Oracle review used explicit selection plus git diff artifacts snapshot `2026-11-02/0006`; all three lanes completed. Initial requests for correction concerned drift reset, read continuation, lifecycle cleanup, JSON adaptation, executable catalog extraction and the selftest's actual-read assertion. These were corrected in scope and verified by the runtime/disposable checks above. No D-UI-6 scope blocker was found. No second review was requested.

Observed compatibility deviation: db_fingerprint retains the pre-existing deterministic functions-then-columns compact JSON encoding so the existing environment remains loadable. No host/load/design changes. Physical checkout `/Users/wxl/Projects/pg-agent`; pre-M1 HEAD `9ba0b782797c5c2c421f6355f01d0047d1955b23`; main baseline `1143dce6da0572bccab083da9a6be0175210b062` remains unchanged. No push. Next milestone: M2, assigned separately.

## Historical M2 execution addendum — BLOCKED (2026-11-02; superseded by final acceptance)

M1 tables above are preserved as historical results. M2 acceptance is still red; this addendum records only the execution below.

| M2 gate | Actual command | Exit | Exact final line / result |
|---|---|---:|---|
| UI acceptance | `uv run python v24/ui/test_ui_gate.py` | 1 | `AssertionError: 3001-byte continuation: {"build_rejections": [{"estimate": 4913, "pins": ["file_search", "read"], "reason": "reserve_insufficient", "reserve": 4096}], "bytes": 3001, "close_reason": "provider_failure", "durable_ui_history_equal": true, "run_id": "c93411f8-9806-4122-b05a-e5ebb0eddb9f", "sha256": "28f0d94dc3450903621bc868ed89ac71a6386f217a81549ae67d2a498a5888b3", "status": "failed", "transport_calls": 1, "unconsumed_outcomes": [{"kind": "final", "text": "large complete"}]}` |

Full output is `/tmp/v24-m2-token0-20261102-final.log`. The 3001-byte read succeeds; durable value/content, UI output and journal-derived history match byte-for-byte (SHA256 `28f0d94dc3450903621bc868ed89ac71a6386f217a81549ae67d2a498a5888b3`). The continuation's `DeepSeekAdapter.build()` rejects estimate 4913 against reserve 4096 before a second transport call; final remains unconsumed. The request pins remain `{read,file_search}`. Do not change SQL, host, the approved plan, or reduce requires to claim green.

Per the coordinator's reconciliation of three completed Oracle lanes, the Oracle outputs agree on the 4096/4913 conflict. This records the coordinator's reading of those Oracle outputs. The lane1 recommendation to replace the fixture with 2050 bytes is rejected because the approved plan explicitly requires 3001. A 2001-byte fixture is a future alternative only if the user amends the plan; it was not tested and is unverified. `MAX_SAFE_ARGS_BYTES` measures model-generated tool argument capacity and is distinct from this provider input-history estimate/reserve conflict.

The token-0 gate defect is corrected and its valid public-API scenario passed: start budget 4096; interaction consumes 4096; waiting has 0 remaining; respond commits; kernel ends `completed` with `close_reason=budget_exhausted`, null final and no successor model; UI displays `run · budget exhausted` with error type, not ordinary completion. The old start-at-zero approach would fail at `reserve_zero` and is no longer used.

Independent cases reached and logged before the remaining large-text failure:

```text
[case] family shared core and canonical JSON parity: passed
[case] v24.text.plain schema/page/render semantics for M2 tools: passed
[case] generating and normal terminal render: passed
[case] primary sequence: exact 10 steps; 2 requires/2 pins; owner=pi_tools; provider has 3 scripted calls
[case] DB install/fiber digest checks and artifact/realm negative controls: passed
[case] interaction/respond: waiting payload readable; empty UI answer makes zero respond calls; nonempty answer -> answered
[case] interaction/token-0: start=4096 usage=4096 -> waiting/tokens=0 -> respond committed -> completed/budget_exhausted; UI=run · budget exhausted (error); transport=1; successors=0
[case] spill paging and sensitive-path rejection: passed
[case] subprocess environment allowlist/workspace-root isolation: passed
[case] SQL catalog closure: ten tables, no views/extensions
[case] explanation caps: run note <=2000 chars; tool args <=500 chars, model tools step <=2000 chars
```

These are scenario observations within the failing gate, not an M2 pass. Other §6.1 checks not evidenced by these lines remain unfinished/unverified; see the M2 ledger addendum. In particular, the current gate does not claim full crash-after-started recovery, drift probes, unpinned SQL negative, complete independent descriptor vocabulary, or dispatcher-level malformed-output checks.

### Historical S13 during blocked M2 (NOT RUN; superseded by final acceptance)

All 13 S13 commands below were **NOT RUN during M2** because the acceptance gate is red. The M1 rows above remain prior historical evidence and must not be represented as M2 regression results.

| S13 command | M2 result |
|---|---|
| `uv run python v24/s13/test_contracts.py` | NOT RUN |
| `uv run python v24/s13/test_vectors.py` | NOT RUN |
| `uv run python v24/s13/test_descriptor.py` | NOT RUN |
| `uv run python v24/s13/test_schema.py` | NOT RUN |
| `uv run python v24/s13/test_renderers.py` | NOT RUN |
| `uv run python v24/s13/test_results.py` | NOT RUN |
| `uv run python v24/s13/test_registry.py` | NOT RUN |
| `uv run python v24/s13/test_line_json.py` | NOT RUN |
| `uv run python v24/s13/test_pages.py` | NOT RUN |
| `uv run python v24/s13/test_wiring.py` | NOT RUN |
| `uv run python v24/s13/test_tools.py` | NOT RUN |
| `uv run python v24/s13/test_lifecycle.py` | NOT RUN |
| `uv run python v24/s13/test_node.py --node` | NOT RUN |

No M2 commit or push. The M2 source and these review updates remain uncommitted on `v24/ui-chainlit`.


## M2 closeout rerun (2026-11-02) — D-UI-7

This section supersedes the earlier M2 RED/NOT RUN status without deleting it. The user-authorized two-lane Oracle plan correction changes only the current structurally valid unpinned-call expectation: public settle committed/emitted[], sole model unknown, original success receipt retained, run blocked_unknown, close_intent.reason=semantic_violation, result.close_reason=unknown, no tool effect/subprocess/target file, connections IDLE; no cancel. Requires and pins remain exactly {read,file_search}. The subsequent missing-pin invalid_outcome guard is not reached by this scenario; other invalid_outcome paths are outside this conclusion. See the ledger's D-UI-7 reconciliation table.

| Invariant / scenario | Executed evidence in ui-gate-04.log |
|---|---|
| 1–3, 5–9, 22 | Active no-network guard; validate_manifest matches 12 SQL_LOAD_ORDER entries; ten tables/no views/extensions before deliberate disposable drift; three consumed primary ScriptedTransport calls; completed/done/turn_no>=3; exact two pins and provider tools; DB manifest/artifact/adapter/descriptor reads and mismatch controls; byte-identical shared core and independent descriptor vocabulary/implications |
| 4, 12–13 | On-disk journal equals memory; six-event closed vocabulary; 42 dispatch start/finish pairs checked before crash; full status+StepRecord incremental/replay equality; claimed-after-started discovered active, real lease recovery unknown, exactly one notification |
| 9 negative | Exact public semantic settlement and receipt assertions described above; no SQL seed, no requires reduction |
| 10–11, 17 | Sensitive/excluded nonexistent paths rejected; spilled read pages reconstruct bytes; both real subprocess envs checked for approved root/no keys/no PG* |
| 14 | CLI main status exit 2 for copied SQL bytes, disposable loaded.json OID/manifest digest and dropped table; db_fingerprint changes; tracked SQL untouched |
| 15–16 | Both families' real dispatcher unknown-key output_check and schema-valid/page-invalid relation normalize to invalid_tool_output; malformed frame yields durable error.code=bad_frame despite journal payload.reason=None; full failed content and unknown short-code rendering |
| 16 large text | Authorized 2001 bytes, two real builds/two consumed transports; observations[-1] contains the 2001 tool message; durable/UI/history/build/sent bytes identical; continuation estimate=3911/reserve=4096/max_tokens=185 |
| Interaction/render | Actual waiting projection rendered (not a constructed StepRecord); empty answer makes no respond call; nonempty respond completes; token-zero seal renders budget exhausted/error; semantic reason comes from close_intent |

The earlier printed estimate=1678 in /tmp/v24-m2-ui-gate-20261102.log described the first small-input build, not the continuation. Final continuation evidence is estimate=3911 with content SHA256 73c26bb0babd5b4b30c185f7ad197f3ba82db1772095f45d5481ce19ced515ab and second-body SHA256 f847ca9f102c2a64768a5130c432e60525cc962eee4fa34703f9760d0b22c060. The original 3001 RED remains historical; MAX_SAFE_ARGS_BYTES is unchanged. The exact real-adapter unknown_tool_name negative is source-reviewed only (deepseek.py:539-542), not independently executed this round.

All commands below actually ran with task-specific temporary UV_CACHE_DIR and XDG_RUNTIME_DIR. All exits are 0 and full S13 logs contain no SKIP; expected internal drift exit 2 cases are assertions within the successful UI gate, not standalone acceptance exit-2 results. Formal implementation review and final UI rerun are recorded in the next addendum.

| Command | Exit | Exact last line | Full log |
|---|---:|---|---|
| `uv run python v24/ui/test_ui_gate.py` | 0 | `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` | `/tmp/v24-m2-closeout-20261102/ui-gate-04.log` |
| `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `/tmp/v24-m2-closeout-20261102/s13-test_contracts.log` |
| `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `/tmp/v24-m2-closeout-20261102/s13-test_descriptor.log` |
| `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `/tmp/v24-m2-closeout-20261102/s13-test_pages.log` |
| `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `/tmp/v24-m2-closeout-20261102/s13-test_registry.log` |
| `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21` | `/tmp/v24-m2-closeout-20261102/s13-test_renderers.log` |
| `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `/tmp/v24-m2-closeout-20261102/s13-test_results.log` |
| `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `/tmp/v24-m2-closeout-20261102/s13-test_schema.log` |
| `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` | `/tmp/v24-m2-closeout-20261102/s13-test_tools.log` |
| `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `/tmp/v24-m2-closeout-20261102/s13-test_vectors.log` |
| `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `/tmp/v24-m2-closeout-20261102/s13-test_line_json.log` |
| `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` | `/tmp/v24-m2-closeout-20261102/s13-test_lifecycle.log` |
| `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `/tmp/v24-m2-closeout-20261102/s13-test_wiring.log` |
| `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `/tmp/v24-m2-closeout-20261102/s13-test_node.log` |


## Final post-review M2 acceptance (2026-11-02)

All 14 commands below actually finished after the review fixes and the full waiting-payload credential scan. Each exit and exact last line was checked against the complete saved log and final-results.json. All exits are 0; no S13 SKIP or exit 2. Temporary task UV_CACHE_DIR/XDG_RUNTIME_DIR were used; their exact values are retained in /tmp/v24-m2-closeout-20261102/final-results-with-hashes.json. No new implementation or Oracle review was run during this final evidence reconciliation.

Formal implementation review: two completed lanes, export prompt-exports/oracle-review-2026-11-02-115709-new-chat-b46b3d-1215.md, fully read through the End marker. The ledger's formal reconciliation inventories both lanes: glob matching, real search assertions, readable aggregate spill, binary accounting and nested unknown-model reasons were repaired; final execution below validates those repairs. Remaining workload/regex risks and M3 application behavior are explicitly scoped follow-ups, not newly verified behavior.

Fail-closed limitation: render_secret_detected refuses presentation with no StepRecord; it is not a successful byte-equivalence case and does not redact, truncate or mutate tool text. Emitted tool records remain verbatim; the 2001 continuation is independently verified. Bearer/DSN examples in ordinary source/docs and structured secret-key names may trigger refusal; ordinary token words alone need not. This heuristic is incomplete and does not erase durable/model history. M3 must explicitly handle refusal; no application-level handling is claimed here. Separately supplied waiting payloads are scanned in full, including text past the presentation bound. The plan was not relaxed to allow altered tool bytes.

The gate's first four timeline records (install x2, started, generating) are harness-generated; six are derived from durable effects/terminal projection. Empty-answer suppression is a UI simulation, not proof of a Chainlit application guard. The harness's start-budget display still uses integer remaining_tokens; no full application budget-display proof is claimed. MAX_SAFE_ARGS_BYTES stays None/unmeasured. The only continuation evidence used is observations[-1], containing the 2001-byte tool message, estimate=3911/reserve=4096/max_tokens=185; estimate=1678 is the earlier first build only. The 3001 RED and earlier unverified records remain historical. Original success receipt/no cancel and both pins {read,file_search} remain unchanged. Real-adapter unknown_tool_name is source-reviewed/execution-unverified.

| Command | Exit | Exact last line | Full log |
|---|---:|---|---|
| `uv run python v24/ui/test_ui_gate.py` | 0 | `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` | `/tmp/v24-m2-closeout-20261102/ui-gate-final-07.log` |
| `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `/tmp/v24-m2-closeout-20261102/s13-final-test_contracts.log` |
| `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `/tmp/v24-m2-closeout-20261102/s13-final-test_descriptor.log` |
| `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `/tmp/v24-m2-closeout-20261102/s13-final-test_pages.log` |
| `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `/tmp/v24-m2-closeout-20261102/s13-final-test_registry.log` |
| `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21` | `/tmp/v24-m2-closeout-20261102/s13-final-test_renderers.log` |
| `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `/tmp/v24-m2-closeout-20261102/s13-final-test_results.log` |
| `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `/tmp/v24-m2-closeout-20261102/s13-final-test_schema.log` |
| `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` | `/tmp/v24-m2-closeout-20261102/s13-final-test_tools.log` |
| `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `/tmp/v24-m2-closeout-20261102/s13-final-test_vectors.log` |
| `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `/tmp/v24-m2-closeout-20261102/s13-final-test_line_json.log` |
| `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` | `/tmp/v24-m2-closeout-20261102/s13-final-test_lifecycle.log` |
| `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `/tmp/v24-m2-closeout-20261102/s13-final-test_wiring.log` |
| `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `/tmp/v24-m2-closeout-20261102/s13-final-test_node.log` |

Full-log integrity (logs are local temporary evidence, not committed):

| Log basename | SHA256 |
|---|---|
| `ui-gate-final-07.log` | `448928423deff2195c281440260d9418304cff0b34ee0569ca87eada51341b72` |
| `s13-final-test_contracts.log` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| `s13-final-test_descriptor.log` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| `s13-final-test_pages.log` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| `s13-final-test_registry.log` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| `s13-final-test_renderers.log` | `5aeef691ed63cc133112e3f044f27bdfad80e0d9fc01ae63e66f0725c0d3e0af` |
| `s13-final-test_results.log` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| `s13-final-test_schema.log` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| `s13-final-test_tools.log` | `0f36d1c45d7bf0b68bb8da03d9932e42ed75930d207886d61b51f2586d4f303f` |
| `s13-final-test_vectors.log` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| `s13-final-test_line_json.log` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| `s13-final-test_lifecycle.log` | `764f32972f018fc2a96a9f2382ab1771fc7ee32843f3d1fd6c389a05daa31c60` |
| `s13-final-test_wiring.log` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| `s13-final-test_node.log` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |


Frozen/whitelist audit before staging: branch v24/ui-chainlit, parent HEAD 5dfaea8422efb6bde8b214cec9f7ff19e340908e; main remains 1143dce6da0572bccab083da9a6be0175210b062. All 92 baseline frozen paths have unchanged SHA256 (frozen-before.json -> frozen-audit-final.json under the evidence directory); no tracked changes outside the eight authorized paths. SQL/host/S13/load/root pyproject/design files are unchanged. Only the 2001 fixture and D-UI-7 semantic-contract corrections touch the authoritative plan. Historical D-UI-6 is intact. Commit scope is M2 only; no push or main update.

## M3 final acceptance (2026-11-02)

M3 adds only `app.py`, `sessions.py` and the independent UI `pyproject.toml`, plus README/matrix/ledger closeout. Chainlit is pinned at 2.12.0; mode is fake, effective pins stay `{read,file_search}`. No host/SQL/S13/load/root project/design/vector or other M1/M2 runtime source changed from preparation HEAD `7703a5d`. No environment reset, W9/D-UI-6 replay, real provider call, push or main update occurred. Local generated `uv.lock` and Chainlit configuration/markdown are not part of this whitelist commit.

All commands below actually finished with exit 0. Shell tests used `UV_CACHE_DIR=/tmp/v24-m3-uv-cache` and `XDG_RUNTIME_DIR=/tmp/v24-m3-runtime`. Embedded PostgreSQL needed sandbox escalation for shared memory; the earlier sandbox `shmat` startup failure did not reach M3 assertions.

| Check / command | Exit | Exact final line | Evidence |
|---|---:|---|---|
| `uv run python v24/ui/test_ui_gate.py` (final source) | 0 | `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` | `/tmp/v24-m3-closeout/ui-final.log` |
| `uv run python /tmp/v24-m3-closeout/backend-check.py` | 0 | `[passed] M3 three-process running/waiting rehydrate; installs reused; history; steer/cancel/close; lock lifecycle` | `/tmp/v24-m3-closeout/backend-final.log` |
| `uv run python /tmp/v24-m3-closeout/edge-check.py` | 0 | `[passed] M3 review edge cases` | `/tmp/v24-m3-closeout/edge.log` |

The backend script uses three actual child processes on a disposable database: runtime #1 leaves running/waiting runs; runtime #2 rehydrates those exact bindings, checks unchanged install IDs/install-effect counts, answers waiting, starts a second run in the same scope and checks injected history; runtime #3 replays terminal without worker execution, refuses catalog drift, restores and closes. Each child checks second-process lock refusal and lock reacquisition after close. Unit fault checks cover malformed UUID records, torn/unterminated turns tails, flush failure and cancellation during backend construction on its owner thread.

Edge checks cover a paused `Step.send()` followed by the old idle and a new submission; persistent consumption delivers the next output without a third message. They also cover answer/cancel task-end pairing, attachment-only token recovery of a waiting run at 32 conversations, blocked-unknown no-start/no-drive/no-reclaim, partial installation cleanup in a later process, and synthetic sensitive final/waiting projection refusal with no final/ask payload emitted. The attempted sensitive read was correctly rejected earlier by the frozen journal secret scanner; it is not claimed as durable sensitive-text admission evidence.

| S13 command | Exit | Exact final line |
|---|---:|---|
| `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` |
| `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` |
| `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` |
| `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` |
| `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/opt/homebrew/bin/node` |
| `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` |
| `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` |
| `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21` |
| `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` |
| `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` |
| `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` |
| `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` |
| `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` |

Results and exact final lines were rechecked against all complete logs and `/tmp/v24-m3-closeout/s13-results.json`; no SKIP. The optional Node vectors path is not claimed here; the required Node gate was explicitly enabled.

### §6.3 browser checklist — all eight passed

Real Chainlit frontend at `127.0.0.1:8000`, driven through kimi-webbridge; snapshots were inspected and waiting screenshot visually checked. This records browser automation, not independent human signoff. Files below are private local evidence under `/tmp/v24-m3-closeout/`, not Git artifacts because tokens appear in snapshots.

| §6.3 | Observed behavior | Private evidence |
|---|---|---|
| 1 | Initial page shows FAKE, `agent_v24_ui`, workspace, effective toolset 2, scope and token; no run before first message | `01-initial.json` |
| 2 | Ordered install Pi/RP → started → generating → model tools → read → model final → completed, final bubble visible | `02-completed.json` |
| 3 | `/tools` shows read/file_search; `/skills` shows empty available-skills block and M4 notice | `03-tools.json`, `03-skills.json` |
| 4 | Busy ordinary text produces `steer queued`, then final `steered: please change direction now` | `04-steered.json` |
| 5 | `/cancel` acknowledges request and eventually projects `run · cancelled` | `05-cancelled.json` |
| 6 | Reload creates fresh scope; wrong token denied; original token replays old completed run; valid token with unrelated run also denied | `06-refreshed.json`, `06-denied.json`, `06-resumed.json`, `06-wrong-run.json` |
| 7 | Interaction stays waiting without answer; answer produces final `answered` and completed; composer usable afterwards | `07-waiting.json`, `07-still-waiting.json`, `07-waiting.png`, `07-fixed-waiting.json`, `07-fixed-answered.json` |
| 8 | `/close` displays converged → off/dispose → scope closed; subsequent resume denied | `08-closed.json`, `08-denied.json` |

The original post-answer busy indicator defect was fixed by balancing `AskUserMessage.send()`'s unconditional task restart in `finally`; #7/#8 were rerun after server restart. The acceptance browser group was closed, the fake server exited gracefully (exit 0), and the persistent process lock was reacquired/released successfully. Recoverable scopes were not reset. Review dispositions are in the ledger. M4/M5 remained outside that milestone.

Final pre-stage audit: all 1443 tracked paths outside the three closeout documents are byte-identical to preparation HEAD `7703a5da7c13f994c7265610b253c5a118d1c483`; per-path SHA256 records are in `/tmp/v24-m3-closeout/frozen-final.json`. Main remains `1143dce6da0572bccab083da9a6be0175210b062`. `git diff --check` and M3 source syntax/credential-marker checks passed. The six staged paths are app/session/project plus README/matrix/ledger; generated dependency/configuration files and unrelated work remain untracked. No amend or push.


## M4 admission preflight — BLOCKED (2026-11-03)

> **Historical preflight snapshot.** This section records the 2026-11-03 preflight before M4 source implementation and the final acceptance. Its NOT RUN/BLOCKED statements describe that checkpoint only; M4 final acceptance is GREEN below.

Scope was admission sizing and baseline/frozen audit only. No M4 artifact, skill, catalog, app or gate source was implemented or edited. Branch `v24/ui-chainlit`, HEAD `243dd9d33cc54725955709f10e162f153757141d`, `main` `1143dce6da0572bccab083da9a6be0175210b062`. Before this documentation update, all 1,449 tracked hashes and 52 unrelated untracked paths were unchanged and tracked/index diffs were empty. This update changes only README/matrix/ledger. No persistent reset/init/migrate and no provider/network call occurred; historical transports were local scripted transports, and every sizing row made zero sends. `MAX_SAFE_ARGS_BYTES` remains `None`.

### Frozen build measurements

All rows called frozen `DeepSeekAdapter.build` with reserve 4,096 and `FRAMING_MARGIN=256`; estimate is canonical body bytes + 256. Admission requires body ≤3,839; a 512-token completion requires body ≤3,328. `None` max_tokens means rejection, not zero. Candidate files are temporary sizing artifacts, not handlers.

| Scenario | Candidate status | Pins | Body B | Estimate | Available | max_tokens | Build |
|---|---|---:|---:|---:|---:|---:|---|
| `full11-minimal-start` | complete proposal, full descriptions | 11 | 5,720 | 5,976 | -1,880 | None | rejected |
| `schema-only11-NONCOMPLIANT-start` | full schema, empty descriptions (NONCOMPLIANT) | 11 | 4,041 | 4,297 | -201 | None | rejected |
| `relaxed11-NONCOMPLIANT-minimal-start` | relaxed bounds/enums (NONCOMPLIANT) | 11 | 3,584 | 3,840 | 256 | 256 | admitted |
| `short-full11-start` | complete schema, compact descriptors | 11 | 5,251 | 5,507 | -1,411 | None | rejected |
| `short-full11-continuation` | complete schema, compact descriptors | 11 | 5,459 | 5,715 | -1,619 | None | rejected |
| `short-full11-2001-continuation` | complete schema, compact descriptors | 11 | 7,459 | 7,715 | -3,619 | None | rejected |
| `short-read7-start` | complete schema, compact descriptors | 7 | 3,263 | 3,519 | 577 | 512 | admitted |
| `short-read7-continuation` | complete schema, compact descriptors | 7 | 3,471 | 3,727 | 369 | 369 | admitted |
| `short-read7-2001-continuation` | complete schema, compact descriptors | 7 | 5,471 | 5,727 | -1,631 | None | rejected |
| `short-full11-app-start` | complete schema, compact descriptors + app prompt | 11 | 6,183 | 6,439 | -2,343 | None | rejected |
| `short-read7-app-start` | complete 7-pin schema + app prompt | 7 | 4,195 | 4,451 | -355 | None | rejected |
| `minimum-prose-FULL-schema11-start` | full schema, minimum prose | 11 | 4,666 | 4,922 | -826 | None | rejected |
| `minimum-prose-RELAXED-schema11-start` | relaxed + 625 B prose (NONCOMPLIANT) | 11 | 4,209 | 4,465 | -369 | None | rejected |
| `minimum-prose-RELAXED-schema11-app` | relaxed + 625 B prose + app prompt (NONCOMPLIANT) | 11 | 4,940 | 5,196 | -1,100 | None | rejected |
| `empty-prose-RELAXED-schema11-app-NONCOMPLIANT` | relaxed, empty prose + app prompt (NONCOMPLIANT) | 11 | 4,315 | 4,571 | -475 | None | rejected |
| `minimum-prose-FULL-schema11-app` | full schema, minimum prose + app prompt | 11 | 5,397 | 5,653 | -1,557 | None | rejected |
| `minimum-prose-FULL-schema7-app` | full schema, minimum prose + app prompt | 7 | 3,693 | 3,949 | 147 | 147 | admitted |
| `relaxed-read7-2001-NONCOMPLIANT` | relaxed, 7 pins, 2,001 continuation (NONCOMPLIANT) | 7 | 4,460 | 4,716 | -620 | None | rejected |

The 4,041-byte result is the complete proposed schema with descriptions removed (noncompliant); it is candidate-specific, not a universal impossibility. A relaxed noncompliant skeleton admits at 3,584 bytes, so required field names alone are not the blocker. The full-schema minimum-prose 11-pin candidate (4,666), relaxed skeleton plus 625 bytes of required prose (4,209), shortest complete app prompt with that skeleton (4,940) and complete-schema app (5,397) all reject. For 4,041 bytes the reserve would need at least 4,298 for one token (4,809 for 512); for 5,397 at least 5,654 (6,165 for 512). These are arithmetic requirements for these candidates, not authorization to edit reserve. The admitted 7-pin application row (3,693/147 tokens) has no history and is not complete workload acceptance.

### Historical two-key regression (separate fixture, executed)

`uv run python /tmp/v24-m4-preflight-20261103/historical.py` exited 0 after the 0700 repair. Only baseline artifact bytes from HEAD `243dd9d` were substituted into a gate-local fixture; registry, SQL, adapter and runtime paths were real, and the disposable PostgreSQL database was private. The planned production read7/exec11 requirements were not weakened and the 2,001 fixture was not narrowed.

| Subset | Executed result |
|---|---|
| Original primary | Exactly 10 steps, 5 effects, 2 artifacts/2 families, 3 scripted transports exhausted; original incremental/full replay and verbatim-output assertions retained |
| Original 2,001-byte continuation | 2,001 ASCII `A` bytes (SHA256 `73c26bb0babd5b4b30c185f7ad197f3ba82db1772095f45d5481ce19ced515ab`); two builds and two sends; second body 3,655, estimate 3,911, reserve 4,096, max_tokens 185, wire 3,672; body SHA256 `45e4c7ee14c455b392d5a5b942a140a08fafe5bfdaad0949ca54d8cd741cb945`, wire `f847ca9f102c2a64768a5130c432e60525cc962eee4fa34703f9760d0b22c060` |
| Original D-UI-7 semantic wall | Exactly `{read,file_search}` pins/requires; committed with `emitted=[]`; sole model `unknown`; run `blocked_unknown`; `close_intent.reason=semantic_violation`; `result.close_reason=unknown`; original success receipt retained; no tool effect, subprocess or target file; both connections IDLE; no cancel/retry |

The first historical attempt exited 1 with `JournalError: journal directory must be private (0700); got 0755`; after temporary directory correction the 0700 rerun exited 0. The temporary `coexist.py` simultaneous old/full-11 probe exited 1 with `ValueError: invalid_catalog`; its generator emitted pin dictionaries as `TOOL_SPECS`. Coexistence is unverified, not a pass and not a product/admission blocker.

### Commands, exits, logs and hashes

| Command | Exit | Exact last line | Full log | SHA256 |
|---|---:|---|---|---|
| `uv run python /tmp/v24-m4-preflight-20261103/measure.py` (first attempt) | 1 | `ModuleNotFoundError: No module named 'v24.s13.plugin_fixtures'` | `/tmp/v24-m4-preflight-20261103/measure-attempt1.log` | `ee88a15b545d95ced31bef92f5ebe439af44f9bed238a865adc28e2bf20ccf8a` |
| `uv run python /tmp/v24-m4-preflight-20261103/measure.py` | 0 | `MEASUREMENTS_COMPLETE actual_transport_count=0` | `/tmp/v24-m4-preflight-20261103/measure.log` | `c6b0a1bd5dc1e1ada8846393d3e5d0fa1abcfe63654176d712895bd1fb5e42a0` |
| `uv run python /tmp/v24-m4-preflight-20261103/extra.py` | 0 | `relaxed_tools_bytes=3491` | `/tmp/v24-m4-preflight-20261103/extra.log` | `f19754cc70be25ca9c6767935b19eb5236c98c9ad5bf1486582d3f4eb5ec961b` |
| `uv run python /tmp/v24-m4-preflight-20261103/final_measure.py` | 0 | `FINAL_MEASUREMENTS_COMPLETE actual_transport_count=0` | `/tmp/v24-m4-preflight-20261103/final-measure.log` | `372bdadc91191d9cdb5a8b930937ec2315f4926ca8fecc13f7ee2ad9151b8a5d` |
| `uv run python /tmp/v24-m4-preflight-20261103/minimum_measure.py` | 0 | `MINIMUM_MEASUREMENTS_COMPLETE actual_transport_count=0` | `/tmp/v24-m4-preflight-20261103/minimum-measure.log` | `6cf3cc26907f67fb94e70a4f6744319eda41290b2de2fd3bb78d58b51ae7a2cd` |
| `uv run python /tmp/v24-m4-preflight-20261103/historical.py` (first attempt) | 1 | `v24.host.journal.JournalError: journal directory must be private (0700); got 0755: /private/tmp/v24-m4-preflight-20261103/historical-runtime` | `/tmp/v24-m4-preflight-20261103/historical-attempt1.log` | `049da2a8986afd43029b7adc12893ca7d1777f309cfd70496718977aad65470d` |
| `uv run python /tmp/v24-m4-preflight-20261103/historical.py` (0700 repair) | 0 | `[passed] unchanged historical primary + 2001 actual continuation + D-UI-7 TWO requires` | `/tmp/v24-m4-preflight-20261103/historical.log` | `9e0971f93eaac468a99b168cc71dc011359bba36b41ae1c6650021a9df75198a` |
| `uv run python /tmp/v24-m4-preflight-20261103/coexist.py` | 1 | `ValueError: invalid_catalog` | `/tmp/v24-m4-preflight-20261103/coexist.log` | `02d6222676d6e2b2ab08b800872ee451d763e98d2403dc1227286b4c8b72b0b9` |
| `uv run python /tmp/v24-m4-preflight-20261103/final_audit.py` | 0 | `[passed] final baseline/frozen audit; tracked=1449 unchanged; untracked=52 unchanged; private PostgreSQL stopped` | `/tmp/v24-m4-preflight-20261103/final-audit.log` | `8b2781b1be78cbdc66e8ffc0056c3a67727bd9e9b66b86ee3773e34cbc0c8394` |

`audit.py` also exited 0; its long `FROZEN REFERENCES` line is retained in `audit.log` (SHA256 `f6102ec57db45f2288566cd46ab7320e4ada8cdfea17f47017d65ae9eb4a015d`). The early `python` bootstrap exited 127 with no file written and is not probe evidence.

Full M4 UI gate, all-stage S13, M3 three-process/lifecycle, browser, new-handler behavior, simultaneous old/full-11 integration and formal implementation review were **NOT RUN**. No M4 commit was created; nothing was staged, committed, pushed or reset. `MAX_SAFE_ARGS_BYTES` remains `None` and is distinct from input admission.

## M4 interim implementation evidence — historical, superseded (2026-11-03)

> **Historical interim snapshot.** This section records the 2026-11-03 checkpoint before the final M3, browser, review and audit results. Its pending/RED statements are not current status; **M4 final acceptance is GREEN** in [M4 final acceptance](#m4-final-acceptance--green-2026-11-03). Retained for provenance without deleting the earlier records.

This section superseded the preflight BLOCKED record above without deleting it. At this interim checkpoint, M4 source implementation was present on `v24/ui-chainlit`; the full UI gate and all 13 S13 gates were green. **M4 was not yet accepted or committed**: the disposable M3 three-process regression and browser `/close` check were RED, the multi-family uninstall-progression repair was pending, the single formal integrated review was in progress, and the final frozen audit had not run. The final resolution is recorded below.

### Source scope and deviations

At the interim checkpoint, the M4 source set under test was `v24/host/deepseek.py`, `v24/ui/{app,catalog,test_ui_gate}.py`, `v24/ui/plugins/{pi_tools,rp_tools}.py` and the two `v24/ui/skills/*/SKILL.md` files, plus these three closeout documents. `deepseek.py` was the only completed host exception, allocated as D-UI-8. The browser-close defect was subsequently repaired under D-UI-9 in `v24/ui/control.py`; that file became the 12th allowed path. SQL, all other host files, lock/thread ownership and the remaining frozen sources stayed frozen. No real provider, W9 redo, D-UI-6 replay, persistent environment reset/init/migrate or M5 work occurred.

### Interim M4 done-when / invariant evidence — historical

| Requirement | Interim gate evidence (full log `ui-20261103T121431-1-test_ui_gate.log`; final gate below) |
|---|---|
| `exec` 11 keys in one run; both families invoked | Real `host_run_pins` and every sent `body.tools` equal the catalog set exactly 11; the same `exec` run legitimately invokes Pi `read` and RP `get_file_tree`; independent production `read` 7-pin and `exec` 11-pin runs both exercise both families; terminal completes |
| Catalog exactly 7/4 | Pi artifact declares 7 (`read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`); RP declares 4 (`read_file`, `file_search`, `get_file_tree`, `apply_edits`); toolset subsets are `read` 7 / `write` 10 / `exec` 11 |
| Skills virtual mount | `.v24/skills/{repo-recon,surgical-edit}/SKILL.md` reads equal source bytes; exact three-child XML, frontmatter grammar/escaping; malformed name/length/duplicate/extra/multiline/symlink fail closed; `ls('.')` has no `.v24`; no workspace `.v24` exists; write/edit/apply virtual mounts rejected |
| Security/defaults | Existing and absent sensitive targets across all 11 tools; traversal/outside-absolute/symlink/`.v24` refusal; failure leaves input bytes unchanged; actual subprocess env has no provider keys and no `PG*`; renderer credential refusal with no mutation |
| Shared core / canonical | Unique matching marker regions, byte-identical shared core, all 12 original canonical parity fixtures, invalid NaN/Inf/surrogate/unsafe-integer rejection, fixed budgets |
| Interim artifact sizes, `ceil(+20%)` | Pi interim 1,159 lines / 52,689 B → 1,391 / 63,227; RP interim 1,120 / 52,179 B → 1,344 / 62,615; hard 3,000 lines / 160 KiB. Final: Pi 1,160/52,732 → 1,392/63,279; RP 1,121/52,222 → 1,346/62,667 |
| Invariants 1–8, 15–18, 22 | No-socket guards; manifest 12-order and exactly ten tables/zero views/extensions; HEAD `243dd9d` prescribed main exactly 10 steps/5 effects/2 artifacts/2 families/3 transports; six-event journal, 206 physical dispatch pairs before crash, full replay; digest alignment incl. 33 dispatcher fixtures; all 11 through the real dispatcher at schema and page layers; malformed frame `unknown`/`bad_frame`; spill/UI/history/model bytes equal |
| Invariant 9, historical D-UI-7 | Original two requires exactly `{read,file_search}`; committed with `emitted=[]`; sole model `unknown`; run `blocked_unknown`; `close_intent.reason=semantic_violation`; `result.close_reason=unknown`; original 5-token success receipt retained; no tool/successor/process/file; both IDLE; no retry/cancel. A separate production `read` 7-pin semantic-wall negative is also green |
| Invariants 10–11, 21, 23 | Path fences above; `read` and `bash` spills page to exact source bytes (integrated gate 63 pages each; standalone artifact probe 57 pages each), >50-page retention boundary, no new page allocation/pruning or original mtime change; bash non-zero is success/exit 2 with footer and merged stdout/stderr; durable `printf 'a\0b'` is `succeeded` with `a\uFFFDb`/exit 0/no NUL, `host_effect` JSONB readable and run continues; timeout group cleanup |
| Invariants 12–14 | Incremental/full replay identical; crash-after-started/1 ms lease claimed effect enters active then exactly one unknown terminal notification; copied SQL/manifest/OID/dropped-table drift exits 2 without persistent mutation |
| Invariants 19–20 | Skill mount above; RP `apply_edits` direct and durable `mode_conflict`, all-miss `status=failed`, four statuses, rewrite/create-empty/no-change/search/list, exact/no-fuzzy, ambiguity/overlap, no mutation on error |
| D-UI-8 admission (`v24/host/deepseek.py` only, `+10/−2`, patch `1d3f8df554e12097212bfde6690769d1f73d68f8c37fecbd20b31e742b9b81dd`) | Exact UTF-8 8,000 admitted; 8,001 `body_too_large`; default `None` retains 4,096/256/512 and 3,911/185 plus `reserve_insufficient` at 3,840; small positive reserves respected; zero/bool/invalid reserves `reserve_zero`; durable `body_too_large` is failed/class failure with zero sends/tools/successors and both IDLE |
| Simultaneous registry | Four approvals for old/new families coexist in one runtime registry under distinct realms; DB lookup works and legitimate old and new calls complete before negatives; no pin-record `TOOL_SPECS` or invalid-catalog substitute |

### Interim build measurements — historical, superseded

At the interim checkpoint, actual complete app prompt, skills block and production descriptors, empty history; canonical body excludes margin and `max_tokens`; reserve 4,096.

| Scenario | Build | Body B | Estimate | `max_tokens` | `admission_body_sha256` |
|---|---:|---:|---:|---:|---|
| `read7-actual-app` | 1 | 4,728 | 4,984 | 512 | `7f87910e26a08cbc0e7fc1c15a4444f98181947f21d3f0df50cdfc7a039806e0` |
| `read7-actual-app` | 2 | 5,191 | 5,447 | 512 | `652309c0db560e5627035b79d31c4a96e7d25823a2539cf95f02d733054db5ae` |
| `read7-actual-app` | 3 | 5,416 | 5,672 | 512 | `cefdb2c701441dc03291645bfaaa9f9fca405504d0d45444683a6a0b1238e0ec` |
| `exec11-actual-app` | 1 | 6,712 | 6,968 | 512 | `69ed5f7e37b3bb8b19113dcc28cab5fe06a3392fc0502ea53c48fa15a108d9cf` |
| `exec11-actual-app` | 2 | 7,175 | 7,431 | 512 | `1cf17f826b139724e426a0af0b068b876f046e059f55d24534a50d6cd8575903` |
| `exec11-actual-app` | 3 | 7,400 | 7,656 | 512 | `dce4b31176a659b0d318b9f608337e3461125934b4e1537794392c93704d2351` |
| `read7-2001` | 1 | 3,485 | 3,741 | 355 | `d35a9f6f320bb49678f7f7be553fbeda2f25f69829084b80d05377a0d6e57f27` |
| `read7-2001` | 2 | 5,718 | 5,974 | 512 | `5143e4e28f9999830c7ab5703b94b420264eddea36fb8c17092c076cb89eae2d` |
| `historical-2001` | 1 | 1,422 | 1,678 | 512 | `7c1d1742678ada5cb29667fb52c2095e07de407b7150dba7cc86981f28e2df30` |
| `historical-2001` | 2 | 3,655 | 3,911 | 185 | `45e4c7ee14c455b392d5a5b942a140a08fafe5bfdaad0949ca54d8cd741cb945` |

The gate uses input `inspect`; the skills-owner construction used `Inspect README.md.` and measured `read7` 4,739/4,995 and `exec11` 6,723/6,979. The 11-byte input difference explains 4,728 vs 4,739 and 6,712 vs 6,723; the app prompt, skills block and complete descriptors are otherwise the same. These are construction/admission observations, **not a general 8,000-byte safety proof**; different prompt/history content can exceed the ceiling and fails closed.

### Interim commands, exits, exact last lines, logs and hashes — historical

All 14 rows actually completed with exit 0; the S13 sweep contains no SKIP, and `test_node.py --node` ran explicitly. The UI row is the earlier 12:14 run, superseded by the final 12:58 run in the final acceptance; the S13 rows are the final authorized reuse. The UI gate checks `chainlit` is absent from `sys.modules`; no persistent UI database was used.

| Command | Exit | Exact last line | Full log | SHA256 |
|---|---:|---|---|---|
| `uv run python v24/ui/test_ui_gate.py` | 0 | `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` | `/private/tmp/v24-m4-implementation/gate/ui-20261103T121431-1-test_ui_gate.log` | `83af4eb96046c783923d53585a663911b573f8f2c56ff245cacdeb08a498fa38` |
| `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-1-test_contracts.log` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-2-test_descriptor.log` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-3-test_lifecycle.log` | `f8ae4562fc85df10719366cff100f0a4ae9f061c337fb84f701d8ab7f0c27410` |
| `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-4-test_line_json.log` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-5-test_node.log` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |
| `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-6-test_pages.log` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-7-test_registry.log` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-8-test_renderers.log` | `5aeef691ed63cc133112e3f044f27bdfad80e0d9fc01ae63e66f0725c0d3e0af` |
| `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-9-test_results.log` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-10-test_schema.log` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-11-test_tools.log` | `6e3243859c98c3f9c6607f3d558aa9dbb73380e3e7d28e5dbf6675cff842f6a9` |
| `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-12-test_vectors.log` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-13-test_wiring.log` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |

Additional executed checks, separate from the 14 rows above:

| Check | Exit | Exact last line | Full log | SHA256 |
|---|---:|---|---|---|
| Focused admission probe | 0 | `[passed] focused byte admission; boundaries=10; default_comparisons=485; constructor_runtime=true; small_reserve=true; invalid_reserve=true; historical_2001=3911/185; provider_calls=0; db_calls=0` | `/tmp/v24-m4-implementation/admission-focused.log` | `bad6c106a8ebd7943f346a1cf7d68c11a3857a6b172ea33867b88a837c1d71a9` |
| Pure M4 black-box gate | 0 | `[passed] M4 pure black-box gate checks` | `/private/tmp/v24-m4-implementation/gate/pure-stable-r2.log` | `322f8f365b4e0980874ed9b8dc62cb97fc047c5a0638b3ea83340a5bc76df0e7` |
| Historical metadata fixture | 0 | `[passed] historical metadata fixture; two original keys; four simultaneous old/new approvals; no DB or handler execution` | `/private/tmp/v24-m4-implementation/gate/history-fixture.log` | `15589b5ea7b390e2243e74b962ddfebc7fd72ca71a9b1eae615bd436973ec30d` |
| `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 PYTHONDONTWRITEBYTECODE=1 uv run python v24/b0/test_golden.py` (reused; authorized) | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `/tmp/v24-m4-implementation/admission-b0.log` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 PYTHONDONTWRITEBYTECODE=1 uv run python v24/s11/test_g10.py` (reused; authorized) | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `/tmp/v24-m4-implementation/admission-s11.log` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| Skills integration | 0 | `PASS skills discovery, fail-closed paths, snapshot wiring, prompt and cleanup (18 tests; no sockets/DB)` | `/tmp/v24-m4-implementation/skills/test-skills.log` | `7f808174ab0d2c2c4ba904d6c7f696b47f6e638241e4c7e68156ed7491a4a56c` |
| Artifact probes (standalone, pre-integration) | 0 each | Exact last lines: `[passed] standalone artifact probes; checks=62; tools=11; artifacts=2`; `[passed] artifact edge/host probes; checks=9; tools=11; baseline_cases=12`; `[passed] artifact boundary probes; groups=3; regex_deadline=executed`; `[passed] spill-source reuse probes; paging_cases=4; pages_each=57; no_new_spills=true`; `[passed] unprovable cleanup exits1/unknown; direct child fallback reaped; no leaked command/path/traceback` | `/tmp/v24-m4-implementation/artifacts/{probe,edge-probe,boundary-probe,spill-source-probe,cleanup-probe}.log` | see `artifacts/final-report.json` |

The B0/S11 rows are the handoff executions reused under explicit user authorization after the identical host patch (`1d3f8df…`) and 111 other frozen sources were rechecked; they are not fresh runs of this documentation turn.

### Interim pending items — all resolved in final acceptance

| Item | Interim state (superseded) | Final resolution |
|---|---|---|
| Disposable M3 three-process regression | Phase 1/2 exit 0; phase 3 exit 1 at `close_scope`; the combined runner stopped. | **GREEN.** Six final real processes (read `10812/10866/10892`, exec `10992/11047/11077`); `final3-validation` exit 0 aggregates 12/12 checks; the original `final3-all`/`final3-backend-edges` RED remains preserved and reconciled. |
| Browser §6.3 check 8 (`/close`) | RED: `run · converged` then `close_incomplete`; first seven checks acceptance-partial only. | **GREEN.** 8/8 checks; 46 private snapshot SHA256 values in `acceptance-final.json`; real `closed_at` DB proof with two installs/fibers disposed, two prepare/release exactly once, six close phases and binding removed. |
| D-UI-9 `control.py` repair | Pending focused Oracle and a minimal uninstall-progression repair; `control.py` allocated as the 12th path. | **Accepted.** Two methods only, `+38/−9`, final SHA256 `e2a608de1d7bacaf722e4665ee8b4807d911b3299639623f98ee87d5f79dac8b`; focused Oracle 2/2 lanes for `close_scope`; actual DB close proof green. |
| Single formal integrated review | In progress (`3DF0`); no findings. | **Complete.** 2/2 lanes, no failed lane, no repeat review; B1/B2/skill A8 resolved; item-by-item accepted/rejected/deferred dispositions in `review/HANDOFF.md` and `DOCS-HANDOFF.md`. |
| Final audit and closeout | Pending; no final pre-stage audit or commit. | **Pre-doc-final audit PASS** (2,143/1,449/10+2/52/index/main/no token leak), followed by coordinator recheck after these docs and one local closeout commit; no push. |

At the interim checkpoint, the browser-close RED was a confirmed product defect, not a harness or documentation artifact, and M3 phase 3 was blocked. The historical M3 §6.3 eight-check pass remains the 2026-11-02 record. Final resolution: browser 8/8 and DB proof, M3 12/12 and six distinct processes, and D-UI-9 accepted. The interim RED evidence remains preserved as history.

### Oracle-directed M4 bug dispositions (artifact source)

The artifact owner's focused Oracle and review dispositions were resolved before the integrated gate; this documentation update did not edit or re-run artifact source.

| Named issue | Confirmed behavior | Disposition |
|---|---|---|
| Spill republish beyond 50 pages | Actual 220,000-byte fixture failed at page 39/offset 73,683 under the 8 MiB cap; original spill removed, 38 files left. | Resolved by managed-spill provenance/snapshot reuse; integrated gate pages 63 each and standalone probe 57 pages each reconstruct exact bytes with no new allocation/pruning and unchanged original mtime; unrelated-generation pruning limitation retained explicitly |
| Generated notice placeholder | `finish_text`/`finish_command` could replace placeholder spellings inside source content. | Resolved: source placeholders are preserved; bash case asserts the literal `.v24/spill/` + 32 zeros + `.txt literal-source` survives |
| Separators | Page joins could alter mixed line endings. | Resolved: exact UTF-8/LF/CRLF/lone-CR/U+2028/VT bytes verified |
| Cleanup `EPERM` masking | Darwin `killpg(0)`/`SIGTERM` both returned `EPERM` before `poll()`; `poll()` then returned 0 and `killpg(0)` returned `ESRCH`. | Resolved: reap-before-signal, bounded cleanup; success only on `ESRCH` + reaped child; unprovable cleanup maps to existing exit 1/unknown; no leaked command/path/traceback and no new protocol code |

These are artifact-source dispositions recorded from the focused reconciliation. The formal integrated review covers the immutable 2026-11-03/1223 formal-snapshot source hashes; later final hashes were covered by the subsequent item-by-item fix/regression reconciliation, not by a second formal review. The artifact probes and full logs are in `/tmp/v24-m4-implementation/artifacts/`; the structured rows are in `final-report.json`.

## M4 final acceptance — GREEN (2026-11-03)

> Historical acceptance at `f4b95d4`; the later review found the P1 in the repair record. These historical logs and sizes do not certify the current repair.

**M4 acceptance is complete.** The final UI gate, the 13 authorized S13 gates, the final M3 aggregation, browser §6.3 and its database close proof, the 2/2 integrated review, and the pre-doc-final source audit are green. That local M4 closeout was committed as `f4b95d4a46e55e0e2b5bb2f6dde3d6d66b23cd35`; it was not pushed. Acceptance baseline: HEAD `243dd9d33cc54725955709f10e162f153757141d`; `main` `1143dce6da0572bccab083da9a6be0175210b062`.

D-UI-8 remains accepted exactly as recorded above: `v24/host/deepseek.py` only, `+10/−2`, source SHA256 `4278fb9a55a91e0f809748a07d8dfef7bbc40d76350d351a3820310f1d236620`; 8,000 admitted, 8,001 `body_too_large`; default `None` still 4,096/256/512; 3,655→3,911/185 and `reserve_insufficient` at 3,840 preserved; 485 default comparisons; fallback only when the computed allowance is below 1.

### Final execution evidence

| Check | Exit | Exact result / last line | Log / evidence | SHA256 / reference |
|---|---:|---|---|---|
| Final UI gate | 0 | `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2`; gate source SHA256 `47962ce868d7be50bcde4045a576b5658ede6d8592841b015bb03a6133b6cdb3` | `/private/tmp/v24-m4-implementation/gate/ui-20261103T125824-1-test_ui_gate.log` | `312c6e2b8521c99f13dd1f2012a0a4368d83b29e29ba71a2e165adb19929704b` |
| 13 S13 commands incl. `test_node.py --node` | 0 each | final authorized reuse; 13 S13 rows unchanged in the interim command table above; Node `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-*.log` | `verification-results.json` |
| M3 final aggregate acceptance | 0 | **GREEN.** `[passed] FINAL M3 GREEN aggregation;12 final checks exit0/loghashes_verified; read7=3 distinct actual processes; exec11=3 distinct actual processes; final source hashes unchanged; append-only journals; fullprompt8000; frontend+oldcatalogreadonly+ready_steer+browserDB+frozen52 audit passed; original RED retained/reconciled; no tests repeated` | `/private/tmp/v24-m4-implementation/m3/final3-validation.log` | `d82389ab0768c2b17ae0d837272e80d393cc0e2d78dcb38115bc0c4970bbac2e` |
| Browser §6.3 | — | 8/8 PASS; `acceptance-final.json` records 46 private snapshot SHA256 values; no raw snapshot or token copied | `/tmp/v24-m4-implementation/m3/browser-evidence/acceptance-final.json` | file is private; final run `24bc18d3-ce65-4934-9da0-3f9e3c0e770a` |
| Browser DB proof | 0 | `[passed] final browser DB proof; scope=8ea869b2-04ca-4a29-abb4-688610c78756; real_closed_at=true; final_catalog=true; installs_disposed=2; fibers_off_disposed=2; prepares=2 exactly_once; releases=2 exactly_once; six_close_phases=true; binding_removed=true; old_partial_metadata_retained=true; readonly=true; no_tokens=true` | `/private/tmp/v24-m4-implementation/m3/final3-browser-db-proof.log` | `53bc4e1b40d4b0e0fb39c54e6ab7ac97fd2bb4668a51d869ff5a67d6adec7169` |
| Frontend probes | 0 | `[passed] M3 frontend behavior probes; persistent_consumer=true; tagged_answer=true; ask_task_end=3; end_cancels=true; hub_construction_cancel_closes_on_owner=true; browser_acceptance=separate` | `/private/tmp/v24-m4-implementation/m3/final3-frontend.log` | `72b5aa0d34c01e1979e9f1d8f9602026489d09c755c83a9b635821694b3d23b0` |
| Historical read-only replay | 0 | `[passed] pre-M4 catalog_changed replay-only; old metadata/install rows unchanged; zero drive/respond/send; close_incomplete retains waiting recovery` | `/private/tmp/v24-m4-implementation/m3/final3-historical-replay.log` | `e67d6a2151dd30c7a590949a5e226e7a48d3aee1c73eec01c569a2c75aa0a40d` |
| Frozen audit | 0 | `[passed] all 1449 tracked blobs/modes audited; only10 authorized tracked paths differ; original52 untracked content hashes preserved; only2 authorized skill additions; SQL/B0/S11/S13 and other host frozen; control only2 methods; final source hashes unchanged; branch/HEAD/main unchanged; staged empty; diff_check=0` | `/private/tmp/v24-m4-implementation/m3/final3-frozen-audit.log` | `0237b76e80df809722c151fdb6560877d5d9b4790634767bfe87b3027a9e4f7c` |
| Immediate-steer edges | 0 | `[passed] M3 immediate-steer edges; exact3 committed receipts/deferred_false generations2,3,4; seed/latest sends_once; superseded_readyeffects cancelled_zero_dispatch; no_claimed_pending; stale_inbox_dropped; cancel_zero_send; next_start_usable; actual_scope_closed; production_unchanged` | `/private/tmp/v24-m4-implementation/m3/final3-backend-edges-immediate.log` | `eed3775aea2d59b9b38892a9247199c5bd5e3c26fcc31e511274a773dd33bf91` |
| Cleanup verification | 0 | `[passed] private browser+cluster stopped; HTTP18024 closed; private PG socket absent; cluster clean shutdown confirmed; 130 metadata/snapshot evidence files content hashes retained; persistent environments untouched` | `/private/tmp/v24-m4-implementation/m3/final3-cleanup-verification.log` | `cee25d2599630a1d3a67e326cf46ade63e3f59fda3147922525730440913765f` |
| Formal integrated review | — | 2/2 lanes completed (`claude-opus-5-5`, `gpt-6.1-sol-xhigh`) against the immutable 2026-11-03/1223 formal-snapshot hashes; later final hashes were covered by item-by-item fix/regression reconciliation, not a second formal review; no failed lane; B1/B2/skill A8 resolved; all material claims accepted/rejected/deferred in `review/HANDOFF.md` and `DOCS-HANDOFF.md` | `prompt-exports/oracle-review-2026-11-03-123642-new-chat-7dc707-8e69.md` | export read through the 2-lane end marker |
| Pre-doc-final source audit | — | PASS: 2,143 snapshot path hashes; 1,449 tracked blobs, 1,439 unchanged, 10 authorized tracked changes; 52 original untracked hashes unchanged; 2 new skill files; index empty; `main` unchanged; no browser-token leak; credential scan of the 12 allowed paths no matches | `/tmp/v24-m4-implementation/coordinator-final-source-audit.json` | coordinator rechecks after these docs and before the single closeout commit |

### M3 real-process rows

| Phase | Exit | Exact last line | Log | SHA256 |
|---|---:|---|---|---|
| read 1 | 0 | `[passed] M3 process regression phase=1 toolset=read pid=10812 builds=3; resources_closed=true; provider=fake; private_db=true` | `/private/tmp/v24-m4-implementation/m3/final3-read-phase1.log` | `54ab05965b1a12f712ae33bb0c226322ab836c26ebe00518f8eed612b8ebd71b` |
| read 2 | 0 | `[passed] M3 process regression phase=2 toolset=read pid=10866 builds=1; resources_closed=true; provider=fake; private_db=true` | `/private/tmp/v24-m4-implementation/m3/final3-read-phase2.log` | `d4622a0edf03ab93992477b0ed35bc12f0524a91c2922b445dc9f3577a5a666e` |
| read 3 | 0 | `[passed] M3 process regression phase=3 toolset=read pid=10892 builds=3; resources_closed=true; provider=fake; private_db=true` | `/private/tmp/v24-m4-implementation/m3/final3-read-phase3.log` | `d3d7dab40b2ce7b759e93fb08952b949b8230a3c5bc3650d0eb853410b736581` |
| exec 1 | 0 | `[passed] M3 process regression phase=1 toolset=exec pid=10992 builds=3; resources_closed=true; provider=fake; private_db=true` | `/private/tmp/v24-m4-implementation/m3/final3-exec-phase1.log` | `e95073d717f35482a08098414c36b96b07fdbc3ab8174f3c0a0e84426405f794` |
| exec 2 | 0 | `[passed] M3 process regression phase=2 toolset=exec pid=11047 builds=1; resources_closed=true; provider=fake; private_db=true` | `/private/tmp/v24-m4-implementation/m3/final3-exec-phase2.log` | `0977f2049bd3b62ddc5af8a183f8cd659a4b96a3c73fc45648fdfabb7e577ef7` |
| exec 3 | 0 | `[passed] M3 process regression phase=3 toolset=exec pid=11077 builds=3; resources_closed=true; provider=fake; private_db=true` | `/private/tmp/v24-m4-implementation/m3/final3-exec-phase3.log` | `b02232a40273222414adbb2d8b18fca5cb3b06054f2434b34d715b1aa0161272` |

The final M3 owner handoff is `/tmp/v24-m4-implementation/m3/FINAL-HANDOFF.md`; `final3-validation` is a verification-only aggregation of 12 existing results and did not rerun tests. It confirms 7 actual builds per toolset, unchanged final source manifest and append-only journals. The original `final3-all` remains exit 1 and the immediate-edge fixture is the Oracle-reconciled replacement.

### Final sizing

Canonical body bytes exclude `max_tokens` and the 256-byte margin; reserve 4,096.

| Scenario | Builds (body B) | Result |
|---|---|---|
| `read7` actual app | 4,818 / 5,281 / 5,506 | 512 each |
| `exec11` actual app | 6,802 / 7,265 / 7,490 | 512 each |
| `write10` actual app | 6,434 / 6,721 / 6,980 | 512 each; bash excluded; permitted mutation plus readback and continuation |
| `exec11` 2,001-byte tool output | 6,802 → 9,045 | first 512; next actual build `body_too_large`, zero extra send, IDLE |
| `exec11` history | 6,849 / 7,575 / 8,303 | first two 512; third `body_too_large`, zero extra send, IDLE |
| `read7` 2,001 | 3,485 / 5,718 | 355 / 512 |
| historical 2,001 | 1,422 / 3,655 | 512 / 185 |

The separate M3 real-process fixture recorded canonical body ranges read 4,871–5,191 B and exec 6,855–7,175 B across 7 builds per toolset; its text differs, so it is not substituted for the gate rows. These are tested observations, **not general 8,000-byte or provider-token safety**.

### Final artifacts, ABI and control

Pi is `1,160` lines / `52,732` B → cap `1,392` / `63,279` B, SHA256 `3e5246557c02127e66d9532aafeb7ae4cd273b1668b222bd2d3d452a3137c688`; RP is `1,121` / `52,222` → `1,346` / `62,667`, SHA256 `b9e9a17a6f213e87d65e0e5421fd8a4d695d192f5e3db6e4caf98ee995d9c338`; shared core SHA256 `f962502170e4412554cce3afd6cda80552be5bd09840b4b8364289e3afc06979` (`34,793` B; identical in Pi and RP; gate-defined `_only_shared` range from BEGIN marker through END marker inclusive, including both trailing newlines, each marker exactly once); hard cap 3,000 lines / 160 KiB. B1 release/inspect is workspace-independent while prepare/invoke retain root validation. B2 uses top-level `request.reservation` as the sole authority; 26 captured frames / 16 inspect cases across both families, both targets, moved/deleted roots and known/absent all passed. The lifecycle workspace copy is gone and the 16 actual frames are green. B2 evidence is in `artifacts/b2-HANDOFF.json`, `artifacts/b2-focused-reconciliation.md` and `artifacts/b2-dispatcher-wire-results.json`.

D-UI-9 is the minimal `v24/ui/control.py` exception: `+38/−9`, final SHA256 `e2a608de1d7bacaf722e4665ee8b4807d911b3299639623f98ee87d5f79dac8b`, 369 lines/23,323 B; only `_retire_install` and `close_scope` changed, with all other method spans byte-identical to HEAD. The focused `close_scope` Oracle completed 2/2 lanes and the accepted algorithm uses bounded fresh public keys, accepts committed/deferred/replay receipts, requires authoritative `closed_at` before final cache/metadata removal, never infers closure from zero pending work, and adds no extra worker/model send. The DB proof above closes the runtime hold. The accepted exception record is in the [ledger](v24-ui-deviation-ledger-2026-11-01.md#d-ui-9--minimal-controlpy-uninstall-progression-exception-accepted).

### Review dispositions and deferred limitations

One formal integrated review only; 2/2 lanes completed, no failed lane. Its own handoff left final runtime acceptance to the coordinator; the final UI/M3/browser runs above close that hold without a repeat review. B1 (stale workspace blocking stateless release/inspect) resolved in final artifacts with prepare/invoke still validated. B2 (host inspect top-level reservation versus artifact args) resolved: top-level `request.reservation` is the sole authority, actual host frames pass, and the historical four failures apply only to the preserved formal-snapshot hashes. Skill A8 is implemented: the prompt explicitly says to read an applicable skill, the invisible-footer dependency is removed, and `MAX_SAFE_ARGS_BYTES` remains unmeasured `None`.

B3 `write10` and A1 exec/history headroom are no longer deferred: the final sizing table supplies three `write10` builds and the durable 9,045/8,303 refusals. All remaining optional findings are deferred/known limitations: ordinary source spill churn/retention is accepted policy; unreadable/binary/non-UTF8 overwrite remains fail-closed with no lstat-only relaxation; fuzzy performance, slash-glob workspace-relative semantics, capped `find`/`ls` notice, concurrent-directory conservative failure, unused imports/shared code, historical git/env/test coupling and opt-in field validation are not changed. No performance/glob/retention/overwrite semantic refactor is implied.

### Limits and next step

`MAX_SAFE_ARGS_BYTES` remains `None` and unmeasured (M5 output-argument capacity). The 8,000 ceiling has real tested headroom refusal at the 9,045 B and 8,303 B durable cases; it is not a universal threshold and is not provider token safety. The old partly disposed binding remains read-only `catalog_changed` with metadata preserved; no rewrite or recovery was attempted. No real provider, `finish_length`, W9 redo, D-UI-6 replay, environment reset/init/migrate, or M5 work occurred; no push. That closeout was committed locally as `f4b95d4`; this later repair remains uncommitted pending the user's final independent review. M5 has not started.

Preserved RED: `final3-all` exit 1, last line `[blocked] final3-backend-edges; stopped before next check; consult Oracle before repair`, SHA256 `8fba7804d4411be8fee652c4f7b3744c69ed285c1c3a0b8369303f01f2085277`; `final3-backend-edges` exit 1, last line `AssertionError`, SHA256 `c072ec6deb66d8e6a0856a908df40894353a68b7aa57e43376324d0a83391277`; and the earlier `final2-read-phase3` exit 1 at `close_scope`, SHA256 `7205b8e7242cce0a400a04b7679b35f938e7aa0831a77ae18b0606e805f28bf8`. The Oracle-driven replacement `final3-backend-edges-immediate` is exit 0, SHA256 `eed3775aea2d59b9b38892a9247199c5bd5e3c26fcc31e511274a773dd33bf91`, using `prompt-exports/oracle-plan-2026-11-03-130135-new-chat-5c5b5e-299e.md` and `m3/oracle-steer-reconciliation.md`; `final3-validation` aggregates 12/12 green and no historical result was rewritten.

Historical RED/NOT RUN/preflight-BLOCKED records above, including the M2 RED, the M4 preflight BLOCKED record, the interim M4 pending record, `final2-read-phase3` and the original `final3-all`/`final3-backend-edges` RED, remain at their original dates and scope; the interim M4 pending section is explicitly marked historical/superseded and retains its interim state alongside the final resolution. No historical RED/NOTRUN/preflight-BLOCKED evidence was deleted.

## M5 measured closeout snapshot (2026-11-04)

Status: **closeout with abandoned historical evidence (2026-11-04); formal review of this closeout recorded in `m5-formal-review.json`.** Current profile (`16384` admission ceiling, newline-only escape, cap 512, reserve 4096) was measured with a real key; the earlier no-key checkpoint remains historical.

| Contract | Evidence / disposition |
|---|---|
| Safe args | `catalog.MAX_SAFE_ARGS_BYTES=128` after the first formal review rejected the 160 claim. Thirteen targets 64–124 × three classes plus two additional 128 B probes per class (one repeat each): 45 probes, 45 passed; 14 complete targets, 3 boundary repeats. The earlier 160 batch (42 probes, 41 passed, one `finish_length`) and the 224 pilot failure are retained as historical. Working recommendation, not a token guarantee. |
| Capacity record | `prompt-exports/v24-m5-evidence/wi3-final-capacity-summary.json`, SHA256 `b2b400b9aed765e90a0c012211207431e9d15d971847ff395c9827ed332910dc`; 45 samples, 0 excluded, 0 failed, 14 complete targets, 3 boundary repeats; source hashes match the audited sources. |
| exec11 | `v24-real-k5a0wn53`, SHA256 `e5411fb32ea2e10473a2eefc9539a859d53649b71c462706ca57bf1abb89bb3f`; 5 HTTP, all checks true, `guard_rejections=[]`, current profile/source. One earlier `duplicate_bash` attempt is retained as a failed measurement. |
| Render contract | `catalog.limits_contract` feeds the prompt and footer through exact keyword forwarding (AST-checked: parameter identity, runtime footer attributes and checked defaults; no literal 8000); the skill is a synchronized static mirror of `max_safe_args_bytes=128`, not a runtime keyword renderer. README marked block `max_safe_args_bytes=128`; audit derives the render check and it passes. |
| Offline gates | Pre-review gate receipt `prompt-exports/v24-m5-evidence/wi3-checks-*-completion/wi3-runner-completion-receipt.json`: the current receipt JSON, runner log SHA256 `2cc3ba1312c0d14053216f216958fb6541ee76e4cfb4c1e01943cc880756e48c`; `gates_ok=true`, every gate exit0 and `source_unchanged=true`; the current completion receipt. `test_real_entry.py` (`capacity=measured:128`), `test_ui_gate.py` (`steps=10; effects=5; artifacts=2; families=2`), `test_audit_m5.py`, `test_backend_regressions.py`, and the full M4 runner 16 commands exit0/skips0. |
| Remaining | The two historical proofs are abandoned (D-UI-19) and reported as `abandoned_evidence`, never as proof; they are not completion blockers. All other items are evidenced: current five-gate receipt, exec11, final-profile capacity, safe-args 128 and render contract. Completion requires the formal review recorded in `m5-formal-review.json` to bind the current runtime and closeout documents. No `main` mutation. |
