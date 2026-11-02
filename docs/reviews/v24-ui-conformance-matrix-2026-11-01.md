# v24 Chainlit UI conformance matrix (2026-11-02)

Current status: M1 (`5dfaea8`) and M2 (`459ee317f9f31fa5f7af0e5be24bdfd237dec4ec`) are committed on local `v24/ui-chainlit`; no push or main update. M2's final UI gate and all 13 S13 commands exited 0 with no SKIP. See [final M2 acceptance](#final-post-review-m2-acceptance-2026-11-02), [README](../../v24/ui/README.md#final-post-review-m2-acceptance-2026-11-02) and [ledger](v24-ui-deviation-ledger-2026-11-01.md#final-post-review-m2-acceptance-2026-11-02). Next: M3 fake Chainlit, persistent sessions/history/toolset and cross-process resume. M2's interaction simulation is not Chainlit acceptance; `MAX_SAFE_ARGS_BYTES` remains unmeasured until M5.

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
