# v24 UI — M3 fake Chainlit runtime

Current status: M3 fake Chainlit acceptance is complete on local `v24/ui-chainlit`; see [M3 closeout](#m3-closeout-2026-11-02). Baselines: M1 `5dfaea8`, M2 `459ee317f9f31fa5f7af0e5be24bdfd237dec4ec`, preparation `7703a5d`. The final UI gate, all 13 S13 commands and §6.3 eight browser checks passed. No push or main update; M4/M5 have not started. Historical RED/NOT RUN records remain below.

Preparation (2026-11-02): authorized minimal `open_env()` exception exports default `V24_SKILLS_ROOT=<repo>/v24/ui/skills` with `setdefault`, preserving explicit configuration. A disposable, mocked-server check passed for default skills/spill exports and explicit skills preservation; the existing UI gate exited 0, last line `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` (log `/tmp/v24-m3-prep-ui-gate.log`). This does not implement skill mounting (M4).

M2 added `file_search` alongside `read`, with durable rendering and a disposable UI gate. Both keys remain required and pinned; Pi owns the run and RP supplies `file_search`. M3 adds the fake Chainlit frontend and durable conversation recovery. The following M1/M2 evidence retains its original scope; no real provider is used.

From the repository root:

```sh
uv run python -m v24.ui.env --init
uv run python -m v24.ui.env --status
uv run python -m v24.ui.d_ui_6_acl --check
uv run python -m v24.ui.control --selftest
```

The environment is `agent_v24_ui` on the repository's embedded PostgreSQL. `.uidata/` contains private metadata, lock, journal, workspace and spill; it is ignored by Git. Init is create-only and returns `already_initialized` on an exact match. Drift refuses startup. `--migrate` prints `migration_unsupported` and exits 2. `--reset --yes` is destructive and was tested only against a disposable server; the existing environment was preserved.

The approved D-UI-6 helper supports only `--check` and `--apply`. It recognizes exact preupgrade, ACL-upgraded/metadata-old and completed states, holds the environment lock, checks target/server/OID/fingerprint, grants admin EXECUTE on `v24.install` only, and atomically updates the permissions and SQL-manifest digests. It never reloads SQL. Existing-state check/apply/check each exited 0: `preupgrade`, `completed`, `completed`. Database OID 4785566 and fingerprint `0f1b51ffafbdebe1facdc0d89bda27a872c1caa8881a1b52e02a7545ac1e9285` were preserved.

The selftest runs prepare/install/fiber activation, model → actual read subprocess → model final. It checks database-read install/fiber/manifest/artifact/adapter/descriptor digests, registry mismatch exceptions, RPC rollback and idle connections, exact `{read}` pins and model tools, and prints every effect's ID/kind/status/ordinal/time. Successful returned domain rejections are committed; Python/SQL exceptions are rolled back.

Empirical same-scope result (2026-11-02): first run `31c5aefd-5bc5-4d90-95f9-280352728cdf` completed with `done`; second start `914fb23e-7c21-43cb-adb3-50f936f95d39` committed and completed in that same scope. M3 may use this evidence for scope reuse; M2 still must prove two requires across families.

Raw `remaining_tokens` includes admission reservation/refund and was `[15904,19995,15899,19990]`. The monotonic unspent budget (raw plus outstanding model reservation) was `[20000,19995,19995,19990]`, spending 10 tokens. This records the actual SQL behavior; no budget SQL was changed.

`read` is verbatim UTF-8 without line numbers, bounded to 2000 lines/32 KiB and the 40960-byte serialized-value budget; truncated text spills under `.v24/spill/`. It rejects sensitive paths, symlinks, traversal, nonregular files, invalid UTF-8, NUL, and files over 1 MiB. Known file failures use v2 failure frames/exit 3. Completion cap is 512; provider length termination fails the run rather than truncating a final. Skills and the other ten planned tools are later milestones.

The pre-existing fingerprint encoding uses the deterministic functions-then-columns compact JSON field order. M1 preserves that encoding and fingerprint instead of silently migrating existing metadata; the D-UI-6 helper changes exactly the two authorized digests. SQL-manifest arrays retain SQL_LOAD_ORDER.

Exact acceptance commands, exits and final lines are recorded in [the UI conformance matrix](../../docs/reviews/v24-ui-conformance-matrix-2026-11-01.md) and [deviation ledger](../../docs/reviews/v24-ui-deviation-ledger-2026-11-01.md). The commit stays on `v24/ui-chainlit`; no push.

## M3 closeout (2026-11-02)

Launch from the repository root after the existing environment has been initialized:

```sh
V24_UI_MODE=fake uv run --project v24/ui chainlit run v24/ui/app.py \
  --host 127.0.0.1 --port 8000 --headless
```

The independent project pins `chainlit==2.12.0`. A single executor thread owns PostgreSQL connections, journal, runtime, session files and the process lock. Async callbacks submit commands; one persistent consumer per browser session renders immutable events. Callbacks return promptly so busy text reaches the steer inbox. Fake adapter latency is 0.5 seconds on the worker thread. `AskUserMessage` answer/cancel cleanup balances Chainlit 2.12's task restart, keeping the composer usable.

Refresh creates a new conversation without destroying the old scope. Keep the displayed token private; `/resume <run_id> <token>` reattaches an indexed run, while `/resume <run_id>` only accepts the current conversation. Tokens are SHA256-only in `sessions.json`. Running/waiting recovery rehydrates and validates the original workspace/toolset/catalog and durable install identities; terminal runs replay without worker execution. Same-scope subsequent runs inject bounded user/final history. Catalog mismatch is replay-only. `blocked_unknown` is replay-only and cannot start new work or be reclaimed.

`/tools` currently exposes effective `{read,file_search}`. `/skills` displays an empty block with the M4 notice. `real` mode is refused (`real_mode_not_enabled`); skill mounting, the remaining tools and safe-args measurement remain M4/M5. No real provider was called.

`/close` converges bound runs, turns fibers off/disposes installs, closes scope and removes local bindings; failures retain recovery metadata. At 32 unreclaimable conversations, an attachment-only session still permits token resume. A failed setup persists ownership before installation; its recovery hint uses `/resume <scope_id> <token>` solely for cleanup with `/close`. Normal run resume rules are unchanged. Shutdown closes thread-owned resources and releases the process lock; it preserves recoverable scopes. Sensitive render failures show only `presentation refused`; no raw exception, final or question payload is sent.

Acceptance: the final `uv run python v24/ui/test_ui_gate.py` exited 0 (`steps=10; effects=5; artifacts=2; families=2`), all 13 S13 commands exited 0 without SKIP, and three-process running/waiting recovery plus review fault cases exited 0. Browser checks used the real Chainlit 2.12 frontend through kimi-webbridge and inspected its timeline, waiting state, steer/cancel, refresh/resume and close ordering. This is browser automation evidence, not an assertion of an independent human signoff. See the [M3 matrix](../../docs/reviews/v24-ui-conformance-matrix-2026-11-01.md#m3-final-acceptance-2026-11-02) for commands, exact final lines and all eight checklist outcomes, and the [M3 ledger](../../docs/reviews/v24-ui-deviation-ledger-2026-11-01.md#m3-closeout-and-review-dispositions-2026-11-02) for review dispositions and limits. Private browser snapshots contain resume tokens and remain outside Git in `/tmp/v24-m3-closeout/`.

## Historical M2 RED (2026-11-02; superseded by closeout below)

At this earlier attempt, M2 work was present but uncommitted. The latest `uv run python v24/ui/test_ui_gate.py` exited 1; complete output is `/tmp/v24-m2-token0-20261102-final.log`. The ten-step primary run, two pins `{read,file_search}` with Pi as owner and RPCE providing the non-owner `file_search`, interaction/respond, the corrected token-0 budget seal, spill/sensitive-path checks, environment isolation, and the ten-table catalog check were logged as reached before the final red scenario.

The remaining blocker is the plan's original 3001-byte read continuation. The read and durable/UI/history text agree byte-for-byte, but `DeepSeekAdapter.build()` rejects its 4913-byte input estimate against the frozen 4096 reserve (`reserve_insufficient`). Only one transport call occurs and the scripted final remains unconsumed. This does not authorize a SQL/host/spec change or reducing `requires`. Per the user's report, three Oracle lanes agree on the estimate/reserve conflict; the lane1 2050-byte replacement suggestion is rejected because it changes the approved fixture. A 2001-byte fixture is only an untested option if the user amends the plan. `MAX_SAFE_ARGS_BYTES` is a separate model tool-argument capacity measure and does not resolve this input-context reserve conflict.

The token-0 test now starts with 4096 tokens, reaches waiting, consumes all 4096 with interaction usage, then responds. The kernel seals with `close_reason=budget_exhausted`; UI shows `run · budget exhausted` as an error, not normal completion. Starting at zero was a gate construction bug (`reserve_zero`), not a plan blocker.

Exact last line of that exit-1 gate:

```text
AssertionError: 3001-byte continuation: {"build_rejections": [{"estimate": 4913, "pins": ["file_search", "read"], "reason": "reserve_insufficient", "reserve": 4096}], "bytes": 3001, "close_reason": "provider_failure", "durable_ui_history_equal": true, "run_id": "c93411f8-9806-4122-b05a-e5ebb0eddb9f", "sha256": "28f0d94dc3450903621bc868ed89ac71a6386f217a81549ae67d2a498a5888b3", "status": "failed", "transport_calls": 1, "unconsumed_outcomes": [{"kind": "final", "text": "large complete"}]}
```

All 13 S13 gates were **not run for M2** because the UI acceptance is red. M1's earlier S13 results above remain M1 evidence only. See the appended M2 sections in the [conformance matrix](../../docs/reviews/v24-ui-conformance-matrix-2026-11-01.md) and [deviation ledger](../../docs/reviews/v24-ui-deviation-ledger-2026-11-01.md) for scenario outcomes, exact failure line, and remaining unverified gate invariants. No M2 commit or push was made.


## M2 closeout rerun (2026-11-02)

This addendum supersedes the historical blocked section above. M2 adds the RepoPrompt-style file_search family and Chainlit-neutral durable rendering. The primary scripted run has exactly ten rendered steps, five effects and two pins {read,file_search}, with Pi owning the run and RP providing the non-owner tool. No Chainlit server or real provider is required; M3 remains separate.

An unpinned key reaching SQL as a structurally valid scripted success receipt ends the model effect as unknown and the run as blocked_unknown. The semantic reason is close_intent.reason=semantic_violation; result.close_reason is unknown. The original success receipt remains stored. No tool effect, subprocess or target file is created; no cancel or retry is attempted. This D-UI-7 correction describes frozen SQL, with both requires unchanged. The real-adapter unknown_tool_name negative was source-reviewed (deepseek.py:539-542), not independently executed this round.

The authorized large fixture is 2001 ASCII bytes. The actual second build contains the complete tool message and is sent: estimate=3911, reserve=4096, max_tokens=185; two builds and two consumed transport calls. Durable/UI/history/build/sent bytes agree (text SHA256 73c26bb0babd5b4b30c185f7ad197f3ba82db1772095f45d5481ce19ced515ab). The earlier estimate=1678 measured the first small-input build and is not continuation evidence. The original 3001 RED is retained above and in the ledger. MAX_SAFE_ARGS_BYTES remains unmeasured/None.

Rendering now exercises real waiting state, token-zero budget seal and close_intent semantic reason. Malformed frames have journal payload.reason=None; the durable host outcome.body.result.output.error.code supplies bad_frame. Tool text is not truncated by UI. The gate also proves real subprocess environment isolation (all PG* absent), exact incremental/full replay, journal pairs before crash recovery, independent descriptor rules, dispatcher schema/page normalization, spill paging and drift on disposable state/copied SQL.

Fresh command results follow. All were actually executed with temporary task UV_CACHE_DIR/XDG_RUNTIME_DIR; all S13 exits are 0 with no SKIP. Formal implementation review and final post-review UI evidence are recorded in the next addendum. The branch remains v24/ui-chainlit; no push or main update is authorized.

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
