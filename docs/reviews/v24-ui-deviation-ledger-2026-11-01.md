# v24 UI deviation ledger (2026-11-01)

Current status: **M4 review repairs accepted: final independent Oracle review passed 2/2, with no remaining blocker (2026-11-03).** Round-1 integration review did not pass; its blockers and consultation failures remain recorded. Commit policy is one separate local repair commit on `v24/ui-chainlit` after closing checks; no push or M5 work. The [repair record](v24-ui-m4-review-fixes-2026-11-03.md) inventories every review item, current dispositions and evidence limits.

## M4 round-2 review boundaries (2026-11-03; final review passed)

The round-1 independent integration review completed 2/2 lanes: L1's no-P1 clearance was contradicted by reproduced L2 supervisor lifecycle/startup failures, so integrated acceptance was **not obtained**. All44 material review claims, including L1's smaller suggestions, are dispositioned in [the repair record](v24-ui-m4-review-fixes-2026-11-03.md). The targeted strategy completed only1/2 lanes: L1 failed with provider_error/no response; L2 completed the source-grounded artifact-only plan selected for implementation. A failed lane supplies no review evidence and is not counted as a 2/2 pass.

The initial strategy proposed separate supervisor/shell groups and a <=64 B private status pipe. Its recovery consultation returned2/2 provider-completed responses, but L1 was only analysis and L2 required waitid(WNOWAIT). Direct runtime verification found Python3.12.11/darwin supports process_group but lacks os.waitid (despite WNOWAIT existing); the candidate was stopped before artifact edits. The final same-group consultation then completed2/2 with material conclusions; the parent coordinating agent selected the smaller live-supervisor-PG-leader topology. Shell inherits that group and private status carries actual shell rc before group self-SIGKILL. Supervisor terminal emissions self-KILL with rc-9; normal accepted SPAWN/EXIT frames uniformly require supervisor-9, resolving the accepted valid-frame/TERM race without L2's rejected waitid remedy or L1's rejected SPAWNrc0 special case. Parent still needs trusted status, reap, EOF and absent group; missing status/unproved cleanup remains unknown. Unsolicited STOP is unknown; locally recorded timeout/cap is preserved only with cleanup proof. No split-group compatibility layer is added. Final artifact/UI/Backend wrapper regressions all exited0/noSKIP. Held main-shell-exit PID/group-kill probes suppress the delayed sentinel and prove group absent; supervisor-only death returns unknown and parent cleans its group. Inner Popen fault is io_error/exit3 without traceback, legal1/7/9/127/247 stays successful, and missing/bad/duplicate/oversized/out-of-range/mismatched/read-fault status stays unknown. Exact-type fixed public message and extension-before-root/walk tests also pass. These are execution receipts in the repair record, separate from the candidate consultations; These executions were subsequently accepted by the final 2/2 independent review of snapshot `2026-11-03/1537`; no remaining blocker. [The final inventory](v24-ui-m4-review-fixes-2026-11-03.md#final-independent-review--pass) records every final-lane claim, including optional short-line memory amplification, conservative drain-window unknowns and abort-probe timing limits. These are accepted boundaries, not newly relaxed resource or correctness requirements.

The audit deliberately certifies only the uncommitted baseline-HEAD tree with an empty index, not the later commit; it now separately checks whitespace in all five authorized new files. Runner records actual sys.executable argv plus a reproduction command. Gate output no longer claims an unexecuted blank-answer assertion. Three cap assertions stay independent to detect drift. Immutable reused spills retain mtime and may be evicted by later distinct spills under50/8MiB; a long single source line may be stored fully yet read back as line_too_long. The unused internal spill_read consolidation is not a new tool surface. No reference-pinning or paging semantic redesign is introduced.

## Round-1 repair boundaries — historical, integrated review did not pass

The initiating review and repair-plan consultation each completed 2/2 lanes. [The repair record](v24-ui-m4-review-fixes-2026-11-03.md) inventories every material item with exactly one accepted/rejected/unresolved disposition and records rejected estimates, preserved limitations and final execution evidence. The artifact strategy also completed a separate 2/2-lane consultation. Planning consultations are not final implementation review; at that checkpoint no integrated repair review had been sent. The later independent review did not pass, as recorded above.

This pair leaves the repair uncommitted. After the parent coordinating agent's final independent Oracle review passes, that parent agent will create one separate local M4 repair commit under the existing conventions, without pushing. Existing local closeout `f4b95d4` is retained; no amend, reset or push. Host (including D-UI-8), SQL, S13, load, root project, designs and vectors stay frozen. `MAX_SAFE_ARGS_BYTES=None` and `real_mode_not_enabled` remain M5 boundaries. Ordinary tool/file limits and full text/history contracts may not be lowered or silently bypassed to pass capacity checks.

A7 is handled at the caller: the plan's `close_scope -> None` contract remains, while gate verifies authoritative `closed_at` and repeated-close behavior. The 3839/3840 allowance cliff is an explicitly accepted D-UI-8 behavior and remains unchanged. Targeted close interruption, arbitrary child-tree recovery, silent bash-descendant termination and platform-specific filename behavior retain separate evidence limits; no universal recovery or process sandbox is claimed. Fresh S13 is 13/13 exit 0 with explicit `--node`; final UI, artifact and expanded Backend executions all exited 0. Four complete-skill chains have 20 actual builds/sends and 36 effects with full 10/11 pins; final bodies 7,380–7,741 B. The large-output strategy bounds cleaned complete output to managed 4 MiB spills (with terminal-annotation room), keeps ordinary files/writes at 1 MiB, and never calls a discarded prefix full output. The silent delayed-sentinel host-kill regression now proves suppression and absent process group; arbitrary detached daemons remain outside that probe. Linux illegal-filename behavior remains unverified (`errno=92` on this filesystem). Final source-size/hash and reproducible post-doc freeze audit receipts are in the repair report.

Historical closeout status at `f4b95d4`: **M4 final acceptance was recorded as GREEN (2026-11-03).** The final UI gate exited 0 with `steps=10; effects=5; artifacts=2; families=2` (SHA256 `312c6e2b8521c99f13dd1f2012a0a4368d83b29e29ba71a2e165adb19929704b`); the 13 authorized S13 executions all exited 0 including explicit `--node`; the final M3 aggregation passed 12/12 checks with read7 and exec11 each in three distinct actual processes (SHA256 `d82389ab0768c2b17ae0d837272e80d393cc0e2d78dcb38115bc0c4970bbac2e`); browser §6.3 is 8/8 with a real database close proof; the integrated review completed 2/2 lanes with B1/B2/skill A8 resolved; and the pre-doc-final source audit passed (2,143 snapshot path hashes, 1,449 tracked blobs, 10 authorized tracked changes + 2 new skill files, 52 original untracked hashes unchanged, empty index, `main` unchanged, no browser-token leak). Acceptance baseline: HEAD `243dd9d33cc54725955709f10e162f153757141d`; `main` `1143dce6da0572bccab083da9a6be0175210b062`. That local M4 closeout was committed as `f4b95d4a46e55e0e2b5bb2f6dde3d6d66b23cd35`; it was not pushed. M5 has not started; `MAX_SAFE_ARGS_BYTES` remains `None`. Historical RED/NOT RUN/preflight-BLOCKED and interim-pending records below retain their original dates and scope.

## M3 closeout and review dispositions (2026-11-02)

M3 is limited to fake Chainlit runtime integration, session/history/toolset behavior and cross-process rehydrate/resume. The independent UI project pins `chainlit==2.12.0`; `app.py` owns one async hub with a single executor thread, and `sessions.py` owns atomic metadata plus bounded turns. The final UI gate, all 13 S13 gates, three-process disposable backend proof, focused review edge checks and all eight §6.3 browser checks exited 0. The browser used kimi-webbridge; snapshots contain resume tokens and remain private under `/tmp/v24-m3-closeout/`.

The accepted review findings are closed as follows: a persistent event consumer survives idle sentinels; capacity creates attachment-only state so token resume remains available; constructor cancellation shields and closes the backend on its owner thread; nested cleanup closes runtime after flush failure and always shuts down the executor; UUID/token-hash validation quarantines malformed state; torn turn tails are repaired before append; steer inbox entries carry run IDs and are discarded across runs; `blocked_unknown` is replay-only and excluded from new work/reclamation; setup ownership is persisted before install so partial failures remain discoverable and `/close` can reconstruct cleanup approvals. A Chainlit 2.12 task lifecycle gap discovered by browser testing was fixed by pairing the background `AskUserMessage.send()` task with `context.emitter.task_end()`; the composer became usable after answers. One Oracle lane completed and one failed with provider 401; the completed lane's nine findings were checked against code and tests.

Oracle reconciliation: 1/2 lanes completed. `gpt-6.1-sol-xhigh` completed; `claude-opus-5-5` failed with provider 401 and supplied no review evidence. One review was run; no post-fix re-review is claimed. Export: `prompt-exports/oracle-review-2026-11-02-162615-new-chat-d843c6-977c.md` (private/ignored). All nine material findings came from the completed lane; each was checked against implementation and assigned exactly one disposition below.

| Finding (source: completed GPT lane) | Disposition | Checked implementation / verification |
|---|---|---|
| Old idle strands next run output | accepted | Persistent `consume`; focused test delays previous Step.send, submits next message behind idle and observes its output without a third message |
| Capacity blocks recovery | accepted | `new` registers attachment-only state; waiting-run token resume at 32 records succeeds without new conversation/install |
| Constructor cancellation leaks backend | accepted | Shielded construction; paused constructor/shutdown fault closes on owner thread |
| Flush failure skips cleanup | accepted | Nested `finally` in Backend.close/shutdown; injected flush OSError still closes runtime and executor cleanup is structurally unconditional |
| Malformed UUID/hash types abort load | accepted | String validation before UUID/hash parsing; malformed numeric/list/dict records quarantine/skip |
| Torn turns tail loses next append | accepted | Atomic retained-record rewrite on load; truncated and valid-unterminated tails survive append/reload |
| Steer crosses run boundary | accepted | Run-ID-tagged inbox and terminal/resume clearing; start→steer→cancel then fresh run excludes old instruction |
| blocked_unknown starts/reclaims work | accepted | Explicit replay-only guard and reclaim exclusion; focused no-start/no-drive/no-reclaim check |
| Failed install orphans scope | accepted | Persist setup ownership before install; actual one-family partial install resumed and disposed in a second process |

M3 command/evidence index: UI gate `/tmp/v24-m3-closeout/ui-final.log`, three-process proof `backend-final.log`, fault cases `edge.log`, S13 `s13-results.json` and each `test_*.log`, browser eight-item outcomes in the [matrix](v24-ui-conformance-matrix-2026-11-01.md#m3-final-acceptance-2026-11-02). All commands and exact final lines are recorded there. Temporary probes are verification evidence outside the milestone source whitelist, not a new committed gate suite. Browser automation exercised all eight specified behaviors; no independent human signoff is claimed.

The local `uv.lock` is generated dependency state and is excluded from this strict M3 source whitelist, along with `.chainlit/`, generated root `chainlit.md` and unrelated untracked work. Only app/session/project and the three closeout documents are committed. No SQL was added, so SQL_LOAD_ORDER remains unchanged. Setup-cleanup `/resume <scope_id> <token>` is a narrowly scoped recovery hint for `setup_incomplete`; it does not admit arbitrary scope IDs as normal run bindings. Persistent environment reset and historical D-UI-6/W9 replay were not performed. The fake server and browser group were closed; process lock reacquisition succeeded. Final pre-stage audit compared all 1443 tracked non-closeout paths byte-for-byte with preparation `7703a5da7c13f994c7265610b253c5a118d1c483` and saved SHA256 in `/tmp/v24-m3-closeout/frozen-final.json`; all matched. Main remains `1143dce6da0572bccab083da9a6be0175210b062`. Diff whitespace and source syntax/credential-marker checks passed. This is one M3 commit, no amend or push.

Limits remain explicit: effective UI pins are `{read,file_search}`; `/skills` is an empty M4 notice; real mode is disabled; provider network was never called; `MAX_SAFE_ARGS_BYTES` is unmeasured for M5. The attempted sensitive-read fixture was rejected by the frozen journal scanner before durable admission, so the M3 assertion covers synthetic final/waiting projection refusal and separately records journal rejection. At the M3 closeout, M4/M5 had not started.

## Authorized M3 preparation exception (2026-11-02)

User authorizes only adding the default `V24_SKILLS_ROOT` export in `open_env()`, preserving explicit environment configuration, before M3. No other control-plane exception is inferred. Disposable mocked-server checks passed for default skills/spill and explicit skills preservation. Existing UI gate exit 0; exact last line `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2`, log `/tmp/v24-m3-prep-ui-gate.log`. Navigation summaries now point to the final M2 record; historical RED/NOT RUN bodies are retained. Separate preparation commit, no amend or push.

## D-UI-6 — approved install ACL and exact immutable audit manifest

User explicitly authorizes only adding `v24_admin` to the public install wrapper EXECUTE GRANT, retaining 27 SQL statements, minimal S1/S9 ACL expectations, and exact exceptions in S13/DP4/DP5/DP6 audits. Original BASEs and complete scopes remain intact; update only the permissions hash among all 12 SQL hashes. S13 retains its 12 frozen paths, whole-module renderer AST stripping exactly five W9 additions, and checks=6 marker.

DP5/DP6 retain BASE `57e2c1e` and full `v24/load.py`, `v24/sql`, S1–S12 scope. Exactly six M-status deltas are allowed and required: permissions SQL, S1 test_g1, S9 test_g8, and historical S9/S10/S11 READMEs. First three equal raw BASE blobs transformed only by unique approved literal substitutions. Other frozen files have zero diff. Reject missing delta, seventh path, non-M status, or historical README mutation. The READMEs must not be edited.

| Historical path | Source commit | Blob | SHA256 |
|---|---|---|---|
| v24/s9/README.md | f3c48a1fc11567e6f7e6bd422eb97fac3c3a29a9 | 3ac204b4ef399091e6cc2aa43765c8b22eeca981 | 0a3c64ddb0e4997d287de81b5c93582cb97320bcb18416c18f7e54fcd318551b |
| v24/s10/README.md | d8029b73e230d68c4a3817fa14a95c72151f4c02 | b37b5fe03ab43d09565d3a17a08d1c6677cdeb02 | a25595bf64d05a649313ba9a48b1e8f1c1c385a365330799be2a126787610ae3 |
| v24/s11/README.md | d13391d27f9c7363906282af4cea4160c5aa97a8 | 2fb92cdcdee994ad030a2b9046b4d8fc5cb267b4 | dc9e0e575d3cb2061eff286ae5fefa3d83b2bf8a2d36cae200c4eca484262063 |

All three sources are ancestors of pre-M1 9ba0b782797c5c2c421f6355f01d0047d1955b23 and equal that HEAD's bytes. Prior 0189029/five-path assumptions are superseded by verified provenance. Negative controls reject extra bytes, SQL admin removal/PUBLIC/second-line mutation, old S1 admin-denied block, old S9 count/negative assertion, README mutation, and seventh path.

Authorized dedicated helper `v24/ui/d_ui_6_acl.py` has --check/--apply only: exact preupgrade, ACL-upgraded metadata-old, completed states; reject other drift. Apply holds .uidata/lock and validates target agent_v24_ui, server identity, database OID and fingerprint; execute only the target admin GRANT and atomically rebind permissions digest and manifest digest. Disposable proof precedes existing-state check/apply/check. No reset/replay/load_stage; ordinary migrate remains unsupported/2. Plan/ledger/audit/ACL/helper paths are explicit M1 whitelist exceptions; host/load/design are unchanged.

Factual correction: lookup_install raises AdapterNotFound(adapter_not_approved), never None. UI RPC commits returned domain rejection envelopes and rolls back Python/SQL exceptions, leaving IDLE.

## Historical M1 execution evidence (2026-11-02; next-step status superseded)

- Physical checkout: `/Users/wxl/Projects/pg-agent`, branch `v24/ui-chainlit`, pre-commit HEAD `9ba0b782797c5c2c421f6355f01d0047d1955b23`; main baseline `1143dce6da0572bccab083da9a6be0175210b062`; no push.
- `uv run python -m v24.ui.env --init` exit 0, last line `{"status": "ok", "loaded": ["already_initialized"]}`; `--status` exit 0, last line `{"status": "ok", "diffs": [], "db_name": "agent_v24_ui"}`; `--migrate` exit 2, last line `migration_unsupported`.
- Existing-state D-UI-6 `--check/--apply/--check` exited 0/0/0 with `preupgrade`/`completed`/`completed`; OID 4785566 and fingerprint `0f1b51ffafbdebe1facdc0d89bda27a872c1caa8881a1b52e02a7545ac1e9285` stayed unchanged. Disposable helper proof exited 0; last line `migrate=2 migration_unsupported; drift=2; reset --yes=0; persistent state untouched`.
- `uv run python -m v24.ui.control --selftest` exit 0. First run `31c5aefd-5bc5-4d90-95f9-280352728cdf` completed with `done`; pins `{read}`; actual tool effect succeeded; unspent tokens `[20000,19995,19995,19990]`; same-scope second start `914fb23e-7c21-43cb-adb3-50f936f95d39` committed and completed. The effect timeline printed three IDs, kinds, statuses, ordinals and timestamps.
- Focused S1/S9, DP4/DP5/DP6 and all 13 S13 commands passed exit 0, including `uv run python v24/s13/test_node.py --node` (`node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node`).
- Oracle review used selected diff artifacts `2026-11-02/0006` and three completed lanes. Accepted fixes: read continuation/error mapping, drift reset recovery, literal-only catalog extraction, JSON response adaptation, and selftest tool-effect assertion. D-UI-6 scope was approved unchanged; no blocker found.

Next milestone: M2, not started.

## Historical M2 execution addendum — BLOCKED / acceptance RED (2026-11-02; superseded by final acceptance)

The M1 record above is preserved unchanged as historical evidence. This addendum supersedes its forward-looking M2 status. HEAD remains `5dfaea8422efb6bde8b214cec9f7ff19e340908e`, branch `v24/ui-chainlit`; main remains `1143dce6da0572bccab083da9a6be0175210b062`. M2 is incomplete and uncommitted. Cleanup was cancelled before any restore/delete; all M2 source work remains in the working tree. No commit or push.

Actual final command: `uv run python v24/ui/test_ui_gate.py`, exit **1**. Full stdout/stderr: `/tmp/v24-m2-token0-20261102-final.log`. Exact final line:

```text
AssertionError: 3001-byte continuation: {"build_rejections": [{"estimate": 4913, "pins": ["file_search", "read"], "reason": "reserve_insufficient", "reserve": 4096}], "bytes": 3001, "close_reason": "provider_failure", "durable_ui_history_equal": true, "run_id": "c93411f8-9806-4122-b05a-e5ebb0eddb9f", "sha256": "28f0d94dc3450903621bc868ed89ac71a6386f217a81549ae67d2a498a5888b3", "status": "failed", "transport_calls": 1, "unconsumed_outcomes": [{"kind": "final", "text": "large complete"}]}
```

The only observed red scenario in this run is the original 3001-byte continuation. Its real read effect succeeds; durable content, UI output and journal-derived history are byte-identical. Original `DeepSeekAdapter.build()` rejects the continuation before transport: input estimate 4913 exceeds admitted reserve 4096. There is one transport call total and the scripted final remains unconsumed. SQL `48_loop.sql` policy/model_reserve fixes the reserve ceiling; host `deepseek.py` checks estimate/available. Neither was changed, nor were the plan/specification or the two requires reduced. This is not an owner-fiber failure: two requires produce exactly `{read,file_search}`, with Pi as owner and RP providing file_search.

Per the coordinator's reconciliation of three completed Oracle lanes, the Oracle outputs agree on reserve 4096 / estimate 4913. This records the coordinator's reading of those Oracle outputs; no additional Oracle review was run. Lane1's suggestion that replacing 3001 with 2050 remains compliant is rejected: the plan specifies the 3001 fixture. A 2001-byte fixture is only a possible future option requiring the user to amend the plan; it was **not run, unverified**, and is not M2 acceptance evidence.

`catalog.MAX_SAFE_ARGS_BYTES` remains `None`: it concerns generated tool-call argument capacity in provider output (M5 measurement). It does not govern this input-context estimate/admission-reserve conflict. No safe-args number was invented.

### In-scope corrections and observed independent cases

Only M2-whitelisted source was edited. Token-0 was a gate construction defect, not a plan contradiction: start with budget 4096; the interaction's legal usage consumes 4096; observe waiting with remaining_tokens=0; respond through the public verb. The kernel commits a budget seal with `status=completed`, `result.close_reason=budget_exhausted`, null final_text and interaction, and no successor model. UI now renders `run · budget exhausted` as `error`, including the exact reason, rather than ordinary `run · completed`. Transport count remains one. No owner-table budget seeding was used.

The same gate log records these cases as reached/passed before the final red case: shared-core bytes/canonical JSON parity; direct schema/page/render checks; generating/normal terminal render; exact primary ten-step sequence with two pins and three scripted model calls; DB install/fiber digests plus artifact/realm mismatch controls; interaction/empty-answer guard/nonempty respond; token-0 seal/UI; read spill pagination and sensitive paths; approved subprocess environment construction; ten-table/no-view/no-extension closure; explanation text caps. These are internal cases of an exit-1 gate, not separately successful acceptance commands. Empty answers are guarded in the gate's UI simulation, not by changes to M1 control. Spill reconstruction validates/removes the known presentation footer before comparing content pages. Workspace injection follows the actual allowlist then ApprovedPlugin root override.

The current gate is not a proof of all §6.1 invariants. In particular, no new evidence is claimed here for the missing claimed-effect crash/recovery case, drift probes, journal pairing/closed event set, unpinned SQL-call negative, complete independent descriptor vocabulary checks, or actual dispatcher-level malformed-output schema/page probes. The current direct schema helper checks the first family/read only, despite its broad log label. The primary model script currently uses ScriptedUiAdapter rather than the plan's ScriptedTransport/model_adapter recipe. Those remain unverified/unfinished; they have not been silently counted as passes. M2 remains blocked and incomplete.

All **13 S13 commands were NOT RUN during M2**, because acceptance remains red; M1 S13 results above are historical only. Per-command NOT RUN entries and the observed-case matrix are in the appended M2 section of the conformance matrix.

Retained diagnostic evidence: `/tmp/v24-m2-observe-20261102-8a27/{observe.py,observe.log,evidence.json,large-effects.json,captured-build-input.json,journal.jsonl}`. The earlier disposable observation exited 0 with final line `[diagnostic-only] observations recorded; sources unchanged; M2 remains RED`; its offline reserve=8192 probe only measures estimate=4913, never sends or settles, and is **diagnostic only, not PASS**. It also preserves the initial-zero reserve_zero reproduction. Latest gate source hashes and process/status closeout are recorded in the companion `/tmp/v24-m2-closeout-20261102/` artifacts. Temporary evidence is local and not committed.

## D-UI-7 — M2 unpinned-call acceptance correction (2026-11-02)

This dated addendum supersedes the M2 BLOCKED status above; all prior RED/unverified records, including the original 3001-byte failure, remain historical evidence. User authorization follows the two completed Oracle plan lanes in `prompt-exports/oracle-plan-2026-11-02-113919-new-chat-d7eab8-f940.md` (read through the end-of-group marker). D-UI-7 was unoccupied before this addition; D-UI-6 is unchanged.

For the current structurally valid scripted success receipt naming unpinned `write`, frozen SQL first marks a semantic violation (`48_loop.sql:565-580`), then commits model `unknown` and run `blocked_unknown` (`:865-881`). The exact projection is `close_intent={kind:unknown,reason:semantic_violation,effect_id:<model>}`, `result.close_reason=unknown`. The original success receipt, including the unpinned call, is preserved. The later `:1116-1126` missing-pin `invalid_outcome` guard is not reached by this scenario; this is not a claim about every invalid_outcome branch. D4/§6.1-9/§8/§10/§14 and a dated plan correction now describe this contract. SQL, host, S13, owner fiber and both required keys are unchanged.

The corrected gate captures the real public settle response: exactly one committed receipt with matching effect ID and `emitted=[]`; exactly one durable model effect with unknown status, original success outcome, no tool effect; exact run terminal/reason, no target file or subprocess, one scripted adapter call, and both connections IDLE. It does not cancel or retry this terminal run. An unquiesced unknown does not prove `/close` convergence. The model effect has no semantic reason in its success outcome; `render_state` reads `close_intent.reason`. For malformed v2 frames, frozen worker `dispatch_finished.payload.reason` is `None`; the actual durable short code is `outcome.body.result.output.error.code=bad_frame`, which the M2 renderer displays without inventing content or truncating tool bytes.

### Oracle reconciliation

Both lanes completed. L1 = primary `new-chat-D7EAB8`; L2 = additional `new-chat-oracle-2-D72FE9`. This table reconciles plan advice; it is not the required final implementation review.

| Claim / advice | Source | Checked evidence | Disposition |
|---|---|---|---|
| Semantic contract and narrow plan correction | L1, L2 | SQL `48_loop.sql:565-580,865-881`; strengthened-03 durable projection; gate-04 real committed negative | accepted |
| Preserve original success receipt while effect status is unknown | L1, L2 | gate-04 asserts outcome.class=success, exact write call and token usage against the sole model effect | accepted |
| Remove terminal cancel | L1, L2 | `_unpinned_sql_negative` ends after exact terminal, render and IDLE assertions; no cancel | accepted |
| Render close_intent reason; handle unknown with null reason | L1; L2 later receipt clarification | `render_state` uses close_intent; gate-04 verifies semantic_violation and unknown fallback; durable malformed error code read from outcome | accepted |
| Exercise actual waiting rendering | L2 | `_interaction_runs` calls render_state on the real waiting projection; checks name/type/interaction ID and seen suppression | accepted |
| Assert actual subprocess environment, including every PG* | L2 | wrapped real subprocess.run still executes both artifacts; captured env has approved root, no API keys and no key starting PG | accepted |
| Allocate D-UI-7 only if unused | L2 | pre-edit search found no D-UI-7 in plan or UI ledger/matrix | accepted |
| Preserve historical RED and use authorized 2001 continuation | L1, L2 | old addenda retained; gate-04 observations[-1] contains full 2001 tool message and equals the sent second body | accepted |
| Execute remaining gate cases, 13 S13 and final review | L1, L2 | gate-04 completed including journal/recovery/drift; fresh S13 command records and formal review recorded in closeout below; L1 optional-review wording does not override repository requirement | accepted |
| L2 early requires={read} | L2 early segment | M2 catalog, primary and negative run pins are exactly {read,file_search}; gate enforces both | rejected |
| Independent scope is necessary | L1/L2 early suggestion; L2 later keeps current interface/scope | negative is an independent run after all other users of its installed scope; disposable DB cleans terminal state | rejected |
| Real adapter rejects unknown names before SQL | L1, L2 | source-reviewed `deepseek.py:539-542`; this exact provider-negative case was not independently executed this round | accepted (source-reviewed; execution unverified) |
| Optional extra real-adapter negative test | L1 | SQL-backstop case deliberately uses ScriptedUiAdapter; no such additional run claimed | rejected (not required for M2) |

### M2 acceptance evidence

The initial rerun `/tmp/v24-m2-ui-gate-20261102.log` exited 0, but its printed estimate **1678** came from the first small-input build (`observations[0]`); it is not continuation evidence. Strengthened-01/02/03 exited 1 (logs `/tmp/v24-m2-ui-gate-strengthened-01.log`, `-02.log`, `-03.log`). The first exposed the mistaken journal payload.reason expectation; the latter two exposed the plan's invalid_outcome expectation. These failures are retained, not relabelled as acceptance. Their full AssertionError last lines remain in their complete logs.

After the authorized correction, `/tmp/v24-m2-closeout-20261102/ui-gate-04.log` exited 0; exact last line `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2`. The **second** real build has estimate **3911**, reserve **4096**, max_tokens **185**, 2001-byte tool content SHA256 `73c26bb0babd5b4b30c185f7ad197f3ba82db1772095f45d5481ce19ced515ab`, body SHA256 `f847ca9f102c2a64768a5130c432e60525cc962eee4fa34703f9760d0b22c060`; two real builds and two transport calls, script exhausted. Durable/UI/history/build/sent tool-message bytes are equal. No reserve/host/SQL change and no MAX_SAFE_ARGS_BYTES measurement is implied.

The full gate also reaches independent descriptor vocabularies/implications, full status+StepRecord incremental/replay equality, turn_no>=3, manifest/order validation, dispatcher output_check and page rejection for both families, malformed frame unknown/bad_frame, real waiting/response/token-zero rendering, spill and path exclusions, actual subprocess environment checks, six-event journal vocabulary with 42 paired dispatches before the crash case, claimed-after-started recovery with exactly one terminal notification, and drift probes on copied SQL/disposable metadata/database (expected internal exit 2). The prior unverified records describe earlier runs only.

Fresh S13 command results, final post-review UI result and implementation review are recorded below when completed; no prior M1 result is reused.


### Fresh M2 command results (2026-11-02)

All 13 S13 commands below actually completed with exit 0 and no SKIP. Each command used temporary task UV_CACHE_DIR/XDG_RUNTIME_DIR. M1 results and the older M2 NOT RUN table are preserved as history. Formal review and the final UI rerun follow in the next addendum.

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

## Formal implementation review reconciliation (2026-11-02)

**Oracle reconciliation** — two lanes completed; no missing lane. This is the required implementation review, separate from the earlier plan consultation and read-only probes. Export `prompt-exports/oracle-review-2026-11-02-115709-new-chat-b46b3d-1215.md` was read through `End of Oracle group: 2 lanes above.` R1 = primary `new-chat-B46B3D` (approve with fixes); R2 = additional `new-chat-oracle-2-87BDA8` (request changes). Neither lane executed tests. The four R2 blockers and R1's required glob/search fixes were checked and repaired before the final reruns; no second review was used as a substitute for execution.

| Finding / advice | Source | Checked evidence / action | Disposition |
|---|---|---|---|
| Default auto glob fails; explicit path regex must remain usable | R1 P1-1, R2 §1 | RP auto-glob uses fnmatch without regex compilation; `_search_semantics` executes default glob and explicit path regex | accepted |
| Search assertions can pass with empty results | R1 P1-3 | Primary README path/line assertion and table for auto/path/both/literal/whole-word/context/filter/count/binary/max_results | accepted |
| Oversize aggregate spill cannot be read or can be pruned | R2 §2 | Reject aggregate above Pi's readable limit before spill write; gate rejects oversized aggregate and reconstructs multi-file RP spill through Pi read | accepted |
| Binary both-mode counts/limit incorrect; capped summary ambiguous | R1 P2, R2 §3 | Content eligibility precedes path admission; real mixed fixture verifies counts/limit; summary adds limit_reached | accepted |
| Unknown model loses nested reason | R2 §4 | `render_effect` checks body.result.reason; focused transport/finish_length/null fallback plus semantic and malformed durable cases | accepted |
| Secret-looking ordinary content raises and may abort UI | R1 P1-4; user follow-up | Fail closed retained and tested explicitly as refusal, not an equality pass; M3 must handle render_secret_detected. Full separately supplied waiting payload is scanned before bounds | accepted |
| Redact/replace credential-shaped tool output or scan only args | R1 P1-4 alternatives | No authorization to mutate tool text; no placeholder or redacted/truncated tool record is emitted | rejected |
| Waiting output may be empty | R1 P1-5 | Actual waiting projection plus originating durable payload passed into render_state; output must contain continue?; seen suppression retained | accepted |
| Reserve is smaller than legal artifact output | R1 P1-6 | 2001 second build measured 3911/4096, max_tokens=185; historical 3001 measured 4913 rejection; no universal ~2.1 KB threshold claimed | accepted |
| File/time budget and regex backtracking risk | R1 P1-2 | `_walk` enumerates candidates and stdlib re can run one long search; no bounded-work guarantee. Deferred M4 risk, not a measured timeout or an M2 fix | accepted |
| Extension normalization, empty paths, unreadable directory, hidden/symlink documentation | R1 P2 filters | Current extensions require dot, paths=[] searches nothing, directory OSError rejects, hidden/symlink entries skipped. Retain explicit current semantics; M4 usability follow-up | accepted |
| Distinguish context lines from hits and separate blocks | R1 P2 context | Current context retains N: text formatting; M4 presentation enhancement, no false claim of match-only line count | accepted |
| Spill footer offset wording and shrink-loop cost | R1 P2 shared finish_text | Shared core must remain byte-identical to M1 Pi artifact, outside M2 edits; RP spills are read via Pi read, not file_search offset. Lockstep M4 follow-up | accepted |
| Noncompleted terminal must expose reason | R1 P2 terminal | render_state displays close_intent.reason then result reason/close_reason; real semantic negative asserts it | accepted |
| Null-body robustness / redundant f-string / dead fallback | R1 P2 renderer | Legal unknown body=None handled and tested; redundant f-string removed. Arbitrary malformed succeeded/failed receipts are not a supported host contract or newly claimed proof; input.tool fallback retained | accepted |
| Remove big_text alias and default read key | R1 P2 fake | Plan §10 explicitly permits fake big-text extension; retain scripted alias/default as fixture convenience, never a real-adapter claim | rejected |
| Empty-answer check is gate simulation, not application guard | R1 P2 gate | Gate only proves its simulated UI does not call respond for empty text. Actual Chainlit guard remains M3, unverified here | accepted |
| First four timeline steps constructed by gate | R1 P2 sequence | Install/start/generating records are harness records; exact ten includes six durable-derived records. No Chainlit emission proof claimed | accepted |
| Gate hygiene and constant marker | R1 P2 hygiene | Unused imports removed; final counts derived from measured steps/effects/families and checked against expected marker. The harness still supplies remaining_tokens as an integer budget display and retains unused locals; these are acknowledged hygiene issues, not evidence of full budget display or application behavior | accepted |
| Stale README status, duplicate tables, ephemeral logs | R1 P2 docs | Current README heading fixed, historical RED retained. Exact tables in all three docs retained per user; final log SHA256 inventory added | accepted |
| D-UI-7, second-build proof and source-only adapter claims | R1 not-findings | Exact semantic receipt and observations[-1] checks retained. Real-adapter unknown_tool_name remains source-reviewed/execution-unverified | accepted |

### Rendering refusal and measured limits

The §4.4 credential recheck is implemented by refusing the record with `ValueError(render_secret_detected)`. It does not redact, truncate, replace, modify durable bytes, or turn the refused case into a byte-equivalence PASS. Every emitted succeeded/failed tool record still equals host join_content byte-for-byte; the 2001 continuation is a separate successful equality case. The negative tests establish refusal only. Credential-shaped examples in ordinary source/docs (Bearer followed by a token, PostgreSQL URLs), or structured keys such as api_key, can trigger false positives; plain token/Authorization words are not automatically secrets. This heuristic is not a complete secret detector and does not remove text already present in durable history/model context. M3 must surface the refusal explicitly; that application flow is not implemented or verified by M2. No plan exception permitting altered tool bytes was added.

Artifact output up to 32 KiB does not imply that every such result fits frozen model admission. The measured 2001-byte continuation leaves only 185 completion tokens, below the requested cap 512; 3001 was rejected at estimate 4913. The limit depends on the whole body, not a universal text-length threshold. Reserve/host/SQL remain frozen. M4/M5 were to evaluate tool budget/reserve tradeoffs separately. File enumeration and catastrophic regex backtracking remain known risks; no timeout benchmark is claimed. `/close` convergence, real provider behavior, and actual Chainlit empty-answer/refusal handling remain outside M2 evidence.


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

## M4 admission preflight record (2026-11-03)

> **Historical preflight snapshot.** This section records the 2026-11-03 preflight before M4 source implementation and the final acceptance. Its NOT RUN/BLOCKED statements describe that checkpoint only; M4 final acceptance is GREEN below.

M3 remains complete. M4 preflight executed and is blocked, unimplemented and unverified; there is no completed M4 commit. This record allocates no deviation: **D-UI-8 remains unused**, and no exception, production pin reduction or reserve change was approved or implemented. The authoritative report is `/tmp/v24-m4-preflight-20261103/REPORT.md`; the matrix records all 18 build rows and every command exit, log and hash.

Baseline: branch `v24/ui-chainlit`, HEAD `243dd9d33cc54725955709f10e162f153757141d`, `main` `1143dce6da0572bccab083da9a6be0175210b062`. Before this documentation update, all 1,449 tracked hashes and 52 unrelated untracked paths were unchanged and tracked/index diffs were empty. This update changes only README/matrix/ledger. No production source, authoritative plan, SQL, host, reserve, `FRAMING_MARGIN` or fake-adapter bytes were edited. No persistent UI reset/init/migrate and no provider/network call occurred; sizing probes made zero sends. `MAX_SAFE_ARGS_BYTES` remains `None`; it measures model-generated tool-argument capacity for M5 and is distinct from this input-context admission conflict.

### Candidate-specific blockage (not a universal impossibility)

With reserve 4,096 and margin 256, a body must be ≤3,839 bytes to admit (≤3,328 for 512 completion tokens). The complete 11-tool proposal at its 5,251-byte start is estimate 5,507 (`available=-1,411`) and rejected. The complete proposed schema with all descriptions removed is 4,041/4,297 (`-201`), but it is noncompliant and candidate-specific; a relaxed noncompliant 3,584-byte skeleton admits with 256 tokens, so the field names alone are not a universal mathematical impossibility. No compliant candidate was established: full-schema minimum prose is 4,666/4,922 (`-826`); relaxed skeleton plus 625 bytes of required descriptor prose is 4,209/4,465 (`-369`); the shortest complete app prompt with that skeleton is 4,940/5,196 (`-1,100`); complete-schema app is 5,397/5,653 (`-1,557`). For 4,041 bytes the reserve would need at least 4,298 for one token (4,809 for 512); for 5,397 at least 5,654 (6,165 for 512). These are arithmetic requirements for these candidates, not permission to edit policy. The admitted 7-pin application row (3,693/147 tokens) has no history and is not complete workload acceptance.

The preflight stopped because no compliant admission solution was established under the frozen policy, not because implementation was prohibited. A dated model-admission/reserve policy decision or an explicit acceptance-scope amendment is required before implementation; nothing here approves one.

### Historical two-key regression and coexistence

The original historical subset was executed separately against gate-local baseline artifacts and a disposable private PostgreSQL database, preserving the planned production read7/exec11 requirements and the 2,001-byte fixture. `historical.py` exited 0: original primary exactly 10 steps/5 effects/2 artifacts/2 families/3 transports; original 2,001-byte continuation two builds/two sends, second estimate 3,911/reserve 4,096/max_tokens 185, body 3,655/wire 3,672, body SHA256 `45e4c7ee14c455b392d5a5b942a140a08fafe5bfdaad0949ca54d8cd741cb945` and wire `f847ca9f102c2a64768a5130c432e60525cc962eee4fa34703f9760d0b22c060`; original D-UI-7 two-requires contract exact (committed/`emitted=[]`, sole `unknown`, `blocked_unknown`, `semantic_violation`, `close_reason=unknown`, receipt retained, no tool effect/subprocess/target file, IDLE, no cancel/retry). The first attempt exited 1 on a 0755 journal directory; after the temporary directory was corrected to 0700 the rerun exited 0. These are separate historical regression results, not new M4 acceptance.

The temporary `coexist.py` simultaneous old/full-11 probe exited 1 with `ValueError: invalid_catalog` because its generator emitted pin dictionaries as `TOOL_SPECS`. Simultaneous fixture coexistence is unverified; this RED is a harness error, not a pass and not a product/admission blocker. No simultaneous durable-install PASS is claimed.

### Review and stopping point

Oracle reconciliation for this preflight: one lane completed (`gpt-6.1-sol-xhigh`); `claude-opus-5-5` failed with provider 401 and supplied no usable plan. This is admission preflight, not the required formal implementation review. Full M4 UI gate, all-stage S13, M3 three-process/lifecycle, browser, new-handler behavior, simultaneous integration and formal review were **NOT RUN**. No M4 commit was created; nothing was staged, committed, pushed or reset. The next step is a user decision on the frozen model admission/reserve conflict before implementation.

## M4 interim implementation ledger — historical, superseded (2026-11-03)

> **Historical interim snapshot.** This section records the 2026-11-03 checkpoint before the final M3, browser, review and audit results. Its pending/RED statements are not current status; **M4 final acceptance is GREEN** in [M4 final acceptance](#m4-final-acceptance--green-2026-11-03). The final D-UI-9 accepted record is below. Retained for provenance without rewriting the preflight BLOCKED record above.

This record supplemented the preflight BLOCKED section above without rewriting it. At this interim checkpoint, the user had explicitly authorized the 8,000-byte M4 admission ceiling, recorded as D-UI-8. A second exception was allocated as D-UI-9 for the confirmed multi-family uninstall-progression defect exposed by the browser `/close` check; it was pending and not yet applied. M4 was not yet accepted or committed.

### D-UI-8 — authorized 8,000-byte build admission ceiling

**Final status: accepted in M4 final acceptance.** User authorization covers only raising the opt-in input-admission ceiling to 8,000 canonical UTF-8 body bytes for M4. This is the host admission exception in the final M4 source set.

| Element | Authorized actual state |
|---|---|
| Allowed file | `v24/host/deepseek.py` only; exact diff `+10/−2`, patch SHA256 `1d3f8df554e12097212bfde6690769d1f73d68f8c37fecbd20b31e742b9b81dd`, resulting source SHA256 `4278fb9a55a91e0f809748a07d8dfef7bbc40d76350d351a3820310f1d236620` |
| Constructor | Additive keyword/property `body_byte_ceiling: int | None = None`; stores `None` unchanged; no new constructor/configuration validation |
| Measurement point | Canonical UTF-8 provider body **before** `max_tokens`, after the canonical body construction; `FRAMING_MARGIN=256` is excluded from the measured body bytes |
| Rejection | Configured ceiling and body bytes > ceiling → `AdapterFailure("body_too_large")`; no transport send |
| Default `None` | Frozen path unchanged: reserve 4,096, margin 256, cap 512; body 3,655 → estimate 3,911 / `max_tokens` 185; body 3,840 (estimate 4,096) → `reserve_insufficient`; 485 default comparisons (8 body sizes × 6 reserves × 10 caps + 5 malformed cases) |
| Configured ceiling | 8,000 admitted (estimate 8,256 / 512); 8,001 `body_too_large`; 3,839 admitted with 1 token; 3,840 admitted with 512; small positive reserves 1/2/7/64/185/256 respected and never exceeded |
| Fallback | Only when the computed `max_tokens` is below 1 (nonpositive allowance): `min(cap, tokens)` instead of `reserve_insufficient`; positive allowances such as 185 are preserved, and `cap` remains 512 |
| Invalid input | Zero, negative, boolean and invalid reserves still raise `reserve_zero`; `None`/malformed caps retain prior behavior |
| Unchanged | SQL reserve 4,096, completion cap 512, margin 256, `PreparedCall`, provider wire format, S13/B0/S11 audits and all 111 other frozen host/SQL/S13/load/project/design/vector sources |
| Evidence | `admission-focused.log` exit 0, SHA256 `bad6c106a8ebd7943f346a1cf7d68c11a3857a6b172ea33867b88a837c1d71a9`; exact host diff in `admission-handoff.md`; reused B0/S11 exits 0 |
| Explicit non-claims | Not provider token safety; `ProviderReply.tokens` still includes prompt+completion and SQL guards are frozen; `MAX_SAFE_ARGS_BYTES` stays `None` (M5 output-argument capacity); 8,000 is not a general safety bound |

The integrated UI gate exercises both the configured 8,000 path and the default `None` path. Its durable `body_too_large` case is `failed`/class failure with zero sends, tools or successors and both connections IDLE. The historical 2,001 continuation under the default path remains 3,911/185, and under the configured ceiling produces the same body/wire bytes and two consumed sends; the ceiling does not rewrite the fixture.

### D-UI-9 — historical interim note

At the interim checkpoint, the browser §6.3 check 8 failure was confirmed read-only as a **product multi-family uninstall-progression defect**, not a harness error. Pi install remained `dispose_pending` with the episode retiring, zero active effects and no release. SQL advanced one fiber per advance; `control._retire_install` performed only one dispose, and the worker could not clear multiple tool families. The `/close` timeline therefore showed `run · converged` followed by `close_incomplete` without the off/dispose/closed sequence.

D-UI-9 was allocated for the minimal `v24/ui/control.py` repair at that checkpoint but was not yet applied. The final accepted two-method repair, focused Oracle reconciliation and actual DB close proof are recorded in [M4 final acceptance](#m4-final-acceptance--green-2026-11-03). The original interim pending table is superseded and not repeated as current status.

### Interim measurements, historical coexistence and source scope — historical

Interim numbers follow; the final gate and M3 numbers are in the final acceptance section. The plan's artifact hard cap remains 3,000 lines / 160 KiB. Interim `wc -l -c` was Pi 1,159 / 52,689 B and RP 1,120 / 52,179 B; the interim gate pinned `ceil(actual×1.20)` at Pi 1,391 / 63,227 B and RP 1,344 / 62,615 B. Final is Pi 1,160/52,732 → 1,392/63,279 and RP 1,121/52,222 → 1,346/62,667. Catalog toolsets are `read` 7 / `write` 10 / `exec` 11; Pi provides 7 and RP provides 4. The production `exec` run pins exactly those 11 in one run and invokes both families; the independent production `read` 7-pin path is also green. The historical fixtures remain independent: original primary exactly 10 steps/5 effects/2 artifacts/2 families/3 transports; D-UI-7 exactly two requires `{read,file_search}` with the recorded semantic wall and original success receipt; original 2,001 continuation two actual builds/two sends, second 3,655/3,911/4,096/185, body/wire `f847ca9f102c2a64768a5130c432e60525cc962eee4fa34703f9760d0b22c060`. No production pin was reduced to two and no historical fixture was rewritten.

Actual complete-app admission bodies are `read7` 4,728 / 5,191 / 5,416 B and `exec11` 6,712 / 7,175 / 7,400 B (reserve 4,096, cap 512). The skills-owner construction used `Inspect README.md.` and measured `read7` 4,739 / 4,995 and `exec11` 6,723 / 6,979; the gate's `inspect` is 11 B shorter and the rest of the app/skills/descriptor content is the same. These rows are tested observations under the configured ceiling, **not a general 8,000-byte safety guarantee**.

### Oracle-directed M4 bug dispositions

The artifact-source defects found during M4 were dispositioned with focused Oracle advice and repaired by the artifact owner; this documentation turn edited and re-ran no source. The integrated UI gate subsequently exercised the repaired behavior.

| Named failure | Disposition |
|---|---|
| `spill_page_republishes_source` / >50-page retention | Accepted and resolved by managed-spill provenance/snapshot reuse. The failing 220,000 B fixture stopped at page 39/offset 73,683, removed the original and left 38 files; the repaired gate pages 63 pages each for four Pi/RP relative/absolute cases with exact bytes, no new allocations, no pruning and unchanged original mtime. Unrelated-generation pruning remains an explicit limitation. |
| Generated-notice placeholder | Accepted and resolved by preserving literal placeholders in source content; bash and finish-text cases retain the literal `.v24/spill/<32 zeros>.txt` spelling. |
| Separators | Accepted and resolved; mixed LF/CRLF/lone-CR/U+2028/VT and UTF-8 payloads page back byte-exactly. |
| Cleanup `EPERM` masking | Accepted and resolved: Darwin `killpg(0)`/`SIGTERM` both returned `EPERM` before `poll()`, then `poll()` returned 0 and `killpg(0)` returned `ESRCH`; cleanup now reaps first, is bounded at 0.55 s, succeeds only on `ESRCH` + reaped child, and maps unprovable cleanup to the existing exit 1/unknown without a new protocol code or leaked diagnostics. |

These dispositions are recorded from `artifacts/review-reconciliation.md`, `artifacts/final-report.json` and `gate/named-failures.md`. The formal integrated review covers the immutable 2026-11-03/1223 formal-snapshot source hashes; later final hashes were covered by the subsequent item-by-item fix/regression reconciliation (B1/B2/skill A8 and the final runtime gates), not by a second formal review of those final hashes.

## M4 final acceptance — GREEN (2026-11-03)

> Historical acceptance at `f4b95d4`; the later review found the P1 in the repair record. Historical review completion and green tests do not stand in for this repair's final independent review.

**M4 acceptance is complete.** The final UI gate, the 13 authorized S13 gates, the final M3 aggregation, browser §6.3 and its database close proof, the 2/2 integrated review, and the pre-doc-final source audit are green. That local M4 closeout was committed as `f4b95d4a46e55e0e2b5bb2f6dde3d6d66b23cd35`; it was not pushed. Acceptance baseline: HEAD `243dd9d33cc54725955709f10e162f153757141d`; `main` `1143dce6da0572bccab083da9a6be0175210b062`.

D-UI-8 remains accepted exactly as recorded above: `v24/host/deepseek.py` only, `+10/−2`, source SHA256 `4278fb9a55a91e0f809748a07d8dfef7bbc40d76350d351a3820310f1d236620`; 8,000 admitted, 8,001 `body_too_large`; default `None` still 4,096/256/512; 3,655→3,911/185 and `reserve_insufficient` at 3,840 preserved; 485 default comparisons; fallback only when the computed allowance is below 1.

### D-UI-9 — minimal `control.py` uninstall-progression exception (accepted)

| Element | Accepted actual state |
|---|---|
| Allowed file | `v24/ui/control.py` only; the 12th allowed path. Exact diff `+38/−9`, patch SHA256 `0a04b8f5f99c8bc8992f3fefeb65619bb3ec7b10ec0bece7c4ce3045e64106ed`; final file SHA256 `e2a608de1d7bacaf722e4665ee8b4807d911b3299639623f98ee87d5f79dac8b`, 369 lines / 23,323 B |
| Scope | Only `_retire_install` and `close_scope` changed. `_retire_install` method hash `e13355f7c181c23edc74e3c707e4645a6a4dccdbc7aeb4461dc3ec9eaaf2e1b1`; `close_scope` method hash `0d655ada6084d5c5214bb18eee80b8e86ab416fdf007056211492fcbc1c0e43c`; all raw line content outside the two method spans is byte-identical to HEAD; no SQL/host/app/session/rehydrate helper change |
| `_retire_install` behavior | Reads the target install/fibers; sends off only for undisposed `want_on` fibers; each of at most 64 rounds issues a fresh-key public dispose, accepts only committed/replay, runs one existing worker and rereads until `disposed_at`; exhaustion is `close_incomplete`. No direct handler/SQL/effect reset and no extra model send |
| `close_scope` behavior | Exact version-1 scope read with false `has_more`, null cursor, one exact item and explicit `closed_at`; bounded 64 distinct public close keys; accepts committed/deferred/replay acknowledgements but requires the authoritative reread to prove closure; nonempty emitted work fails incomplete rather than dispatching; no uncertain-RPC retry; already-closed needs no close RPC; already-terminal race is verified by `closed_at`; final scope/cache pops only after proved closure |
| Focused Oracle | `close_scope`: 2/2 lanes completed and read through the end marker; export `prompt-exports/oracle-plan-2026-11-03-124036-new-chat-4638d8-16e9.md`; reconciliation `/tmp/v24-m4-implementation/m3/oracle-scope-reconciliation.md`. Accepted Lane 2's core algorithm and strict read contract plus Lane 1's nonempty-emitted fail-closed guard; rejected outright replay rejection, broad error masking and an extra all-local-installs precondition. `_retire_install` follows the recovered focused disposal response (`m3/oracle-retire-lane2-recovered.md`); it is not claimed as a separately completed two-lane review |
| Runtime proof | Browser DB proof exit 0, log SHA256 `53bc4e1b40d4b0e0fb39c54e6ab7ac97fd2bb4668a51d869ff5a67d6adec7169`: scope `8ea869b2-04ca-4a29-abb4-688610c78756`, real `closed_at`, 2 installs disposed, 2 fibers off/disposed, 2 `host_prepare` and 2 `host_release` exactly once each, six close phases, binding removed, old partial metadata retained, no tokens. Focused `scope-proof`, guard and close-failure proofs exit 0 (`15232796…`, `978d6cc4…`, `35dc3437…`) |
| Limits / non-claims | Arbitrary child-tree topology is not fully proved; the old partly disposed binding remains read-only `catalog_changed` with metadata preserved and no rewrite/recovery; no real provider, no extra scope worker/model sends and no M5 claim |

D-UI-9 authorizes only this minimal two-method repair; it does not relax the SQL, other host, lock/thread or remaining frozen-source boundaries.

### Final tests and measurements

| Check | Result |
|---|---|
| Final UI gate | exit 0; `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2`; log SHA256 `312c6e2b8521c99f13dd1f2012a0a4368d83b29e29ba71a2e165adb19929704b`; gate source SHA256 `47962ce868d7be50bcde4045a576b5658ede6d8592841b015bb03a6133b6cdb3` |
| S13 | 13/13 exit 0 including explicit `test_node.py --node`; authorized reuse checked by the final frozen-source/host-patch audit; exact rows/logs/hashes in the matrix |
| M3 final aggregate acceptance | **GREEN.** read7 `10812/10866/10892`, exec11 `10992/11047/11077`, all exit 0; 7 actual builds per toolset; final `final3-validation` exit 0, 12/12 checks, SHA256 `d82389ab0768c2b17ae0d837272e80d393cc0e2d78dcb38115bc0c4970bbac2e` |
| Browser | 8/8 §6.3 checks; 46 private snapshot SHA256 values in `acceptance-final.json`; actual DB proof as above; no token/raw snapshot in Git |
| Frontend / historical / audit | frontend probes, historical read-only replay, frozen audit and immediate-steer edges all exit 0 (`72b5aa0d…`, `e67d6a21…`, `0237b76e…`, `eed3775a…`); cleanup verification exit 0 (`cee25d25…`) |
| Review | 2/2 lanes against the immutable 2026-11-03/1223 formal-snapshot hashes; later final hashes were covered by item-by-item fix/regression reconciliation, not a second formal review; no failed lane; B1/B2/skill A8 resolved; item-by-item accepted/rejected/deferred dispositions in `review/HANDOFF.md` and `DOCS-HANDOFF.md` |
| Audit | pre-doc-final PASS: 2,143 snapshot path hashes; 1,449 tracked blobs, 1,439 unchanged, 10 authorized tracked changes; 52 original untracked hashes unchanged; 2 new skill files; index empty; `main` unchanged; no browser-token leak; credential scan of the 12 allowed paths no matches. Coordinator rechecks after these docs before the single closeout commit |

The final M3 owner handoff is `/tmp/v24-m4-implementation/m3/FINAL-HANDOFF.md`; `final3-validation` is a verification-only aggregation of 12 existing results and did not rerun tests. It confirms 7 actual builds per toolset, unchanged final source manifest and append-only journals. The original `final3-all` remains exit 1 and the immediate-edge fixture is the Oracle-reconciled replacement.

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

The separate M3 real-process fixture recorded read bodies 4,871–5,191 B and exec 6,855–7,175 B across 7 builds per toolset; its text differs and it is not substituted for the gate rows. These are tested observations, **not general 8,000-byte or provider-token safety**.

Artifacts: Pi `1,160` lines / `52,732` B → cap `1,392` / `63,279` B, SHA256 `3e5246557c02127e66d9532aafeb7ae4cd273b1668b222bd2d3d452a3137c688`; RP `1,121` / `52,222` → `1,346` / `62,667`, SHA256 `b9e9a17a6f213e87d65e0e5421fd8a4d695d192f5e3db6e4caf98ee995d9c338`; shared core SHA256 `f962502170e4412554cce3afd6cda80552be5bd09840b4b8364289e3afc06979` (`34,793` B; identical in Pi and RP; gate-defined `_only_shared` range from BEGIN marker through END marker inclusive, including both trailing newlines, each marker exactly once); hard cap 3,000 lines / 160 KiB. B1 release/inspect is workspace-independent while prepare/invoke retain root validation; B2 uses top-level `request.reservation` as the sole authority with 26 captured frames / 16 inspect cases green (`artifacts/b2-HANDOFF.json`, `artifacts/b2-focused-reconciliation.md`, `artifacts/b2-dispatcher-wire-results.json`); the lifecycle workspace copy is gone.

**2026-11-03 correction.** The earlier final-doc shared-core SHA `3c2cb23f03f79819e505906bd3c55814da29ab2665348980c01e156be7f318d4` is superseded by `f962502170e4412554cce3afd6cda80552be5bd09840b4b8364289e3afc06979` under the gate's marker-inclusive definition. It does not reproduce from the final Pi/RP bytes; its origin is not inferred. This is a docs-only correction: no source, gate, test or historical evidence changed.

### Review dispositions and deferred limitations

One formal integrated review only, 2/2 lanes completed with no failed lane. Its own handoff left final runtime acceptance to the coordinator; the final UI/M3/browser runs above close that hold without a repeat review. B1 is resolved in final artifacts (stateless release/inspect; prepare/invoke still validate). B2 is resolved (top-level reservation is the sole authority; actual host frames pass; historical four failures apply only to the preserved formal-snapshot hashes). Skill A8 is implemented (explicit skill-read instruction; invisible-footer dependency removed; `MAX_SAFE_ARGS_BYTES` unmeasured `None`). No unresolved source blocker remains from the review inventory.

B3 `write10` and A1 exec/history headroom are no longer deferred: the final sizing table supplies three `write10` builds and the durable 9,045/8,303 refusals. Deferred/known limitations: ordinary source-spill churn and current retention policy; unreadable/binary/non-UTF8 overwrite remains fail-closed with no lstat-only relaxation; fuzzy performance; workspace-relative slash-glob semantics; capped `find`/`ls` notice; conservative concurrent-directory failure; unused imports/shared code; historical git/env/test coupling; opt-in field validation. No performance/glob/retention/overwrite semantic refactor is implied.

### Limits and next step

`MAX_SAFE_ARGS_BYTES` remains `None` and unmeasured (M5 output-argument capacity). The 8,000 ceiling has real tested headroom refusal at the 9,045 B and 8,303 B durable cases; it is not a universal threshold and is not provider token safety. The old partly disposed binding remains read-only `catalog_changed` with metadata preserved; no rewrite or recovery was attempted. No real provider, `finish_length`, W9 redo, D-UI-6 replay, environment reset/init/migrate, or M5 work occurred; no push. That closeout was committed locally as `f4b95d4`; this later repair remains uncommitted pending the user's final independent review. M5 has not started.

Preserved RED: `final3-all` exit 1, last line `[blocked] final3-backend-edges; stopped before next check; consult Oracle before repair`, SHA256 `8fba7804d4411be8fee652c4f7b3744c69ed285c1c3a0b8369303f01f2085277`; `final3-backend-edges` exit 1, last line `AssertionError`, SHA256 `c072ec6deb66d8e6a0856a908df40894353a68b7aa57e43376324d0a83391277`; and the earlier `final2-read-phase3` exit 1 at `close_scope`, SHA256 `7205b8e7242cce0a400a04b7679b35f938e7aa0831a77ae18b0606e805f28bf8`. The Oracle-driven replacement `final3-backend-edges-immediate` is exit 0, SHA256 `eed3775aea2d59b9b38892a9247199c5bd5e3c26fcc31e511274a773dd33bf91`, using `prompt-exports/oracle-plan-2026-11-03-130135-new-chat-5c5b5e-299e.md` and `m3/oracle-steer-reconciliation.md`; `final3-validation` aggregates 12/12 green and no historical result was rewritten.

Historical RED/NOT RUN/preflight-BLOCKED records above, including the M2 RED, the M4 preflight BLOCKED record, the interim M4 pending record, `final2-read-phase3`, and the original `final3-all`/`final3-backend-edges` RED, remain at their original dates and scope; the interim M4 pending section is explicitly marked historical/superseded and retains its interim state alongside the final resolution. No historical RED/NOTRUN/preflight-BLOCKED evidence was deleted.