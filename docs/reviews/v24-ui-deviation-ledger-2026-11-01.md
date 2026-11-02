# v24 UI deviation ledger (2026-11-01)

M1 only; feature branch `v24/ui-chainlit`, no push (plan D7 overrides general AGENTS main/push rule). W9 was already green before this work and is not reimplemented.

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

## M1 execution evidence (2026-11-02)

- Physical checkout: `/Users/wxl/Projects/pg-agent`, branch `v24/ui-chainlit`, pre-commit HEAD `9ba0b782797c5c2c421f6355f01d0047d1955b23`; main baseline `1143dce6da0572bccab083da9a6be0175210b062`; no push.
- `uv run python -m v24.ui.env --init` exit 0, last line `{"status": "ok", "loaded": ["already_initialized"]}`; `--status` exit 0, last line `{"status": "ok", "diffs": [], "db_name": "agent_v24_ui"}`; `--migrate` exit 2, last line `migration_unsupported`.
- Existing-state D-UI-6 `--check/--apply/--check` exited 0/0/0 with `preupgrade`/`completed`/`completed`; OID 4785566 and fingerprint `0f1b51ffafbdebe1facdc0d89bda27a872c1caa8881a1b52e02a7545ac1e9285` stayed unchanged. Disposable helper proof exited 0; last line `migrate=2 migration_unsupported; drift=2; reset --yes=0; persistent state untouched`.
- `uv run python -m v24.ui.control --selftest` exit 0. First run `31c5aefd-5bc5-4d90-95f9-280352728cdf` completed with `done`; pins `{read}`; actual tool effect succeeded; unspent tokens `[20000,19995,19995,19990]`; same-scope second start `914fb23e-7c21-43cb-adb3-50f936f95d39` committed and completed. The effect timeline printed three IDs, kinds, statuses, ordinals and timestamps.
- Focused S1/S9, DP4/DP5/DP6 and all 13 S13 commands passed exit 0, including `uv run python v24/s13/test_node.py --node` (`node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node`).
- Oracle review used selected diff artifacts `2026-11-02/0006` and three completed lanes. Accepted fixes: read continuation/error mapping, drift reset recovery, literal-only catalog extraction, JSON response adaptation, and selftest tool-effect assertion. D-UI-6 scope was approved unchanged; no blocker found.

Next milestone: M2, not started.

## M2 execution addendum — BLOCKED / acceptance RED (2026-11-02)

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

Artifact output up to 32 KiB does not imply that every such result fits frozen model admission. The measured 2001-byte continuation leaves only 185 completion tokens, below the requested cap 512; 3001 was rejected at estimate 4913. The limit depends on the whole body, not a universal text-length threshold. Reserve/host/SQL remain frozen. M4/M5 must evaluate tool budget/reserve tradeoffs separately. File enumeration and catastrophic regex backtracking remain known risks; no timeout benchmark is claimed. `/close` convergence, real provider behavior, and actual Chainlit empty-answer/refusal handling remain outside M2 evidence.


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
