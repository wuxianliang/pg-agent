# v24 Chainlit agent runtime — focused critique (2026-11-01)

Scope: only the amended plan and the export’s Oracle 2 `## Generated Plan` baseline (from `## Summary`). No re-litigation of the settled owner-fiber, pin-ladder, or English-skills decisions.

References: `P` = `docs/plans/v24-chainlit-agent-runtime-2026-11-01.md`; `E` = `prompt-exports/oracle-plan-2026-11-01-150535-plan-v24-agent-syste-39c6.md`, generated-baseline lines only.

## Actionable findings

1. [blocker] The catalog labels a v1 artifact with the v2 adapter declaration — `P:189-205` and `E:932` prescribe `adapter_declaration_digest("python")`, but that helper hard-codes `v24.line-json.v2`, version 2 (`v24/host/registry.py:378-382`); the working v1 fixture uses `v24.line-json.v1`, version 1 (`v24/s11/plugin_fixtures.py:90-115`) — Use the v1 declaration digest in both manifest and `ApprovedAdapter`; assert the protocol/version in the catalog gate. The five-tuple may still match with the wrong declaration, so existing checks would not catch this.

2. [blocker] Chainlit startup cannot construct the specified run — `P:537-539` installs before `create_scope`, although install requires `scope_id` (`P:462`); `on_chat_start` also has no first user message for `start_run` (`P:472`, `E:1051`), while the manual flow starts after the first message (`P:728-729`) — Create scope/run lazily on the first ordinary `on_message`: create scope → install/activate → start with that message. Explicitly reconcile emission order with the gate’s `run · started`-before-install sequence (`P:668-678`).

3. [high] `asyncio.to_thread` does not provide the promised thread confinement — `P:268,440,526` require one owning worker thread, but `P:631` dispatches through the default pool, which may use different threads over the runtime lifetime — Use a dedicated single-worker executor or an explicit worker thread plus queue; construct, use, and close `HostDB` and `HostJournal` on that same thread.

4. [high] The scoped install cache is unsafe across close/re-admission — `P:418-420,436` define the cache but no eviction; `P:470` closes the scope after every `uninstall_tools`; once close starts, install and start fail with `scope_closed` (`v24/sql/40_interpreters.sql:2817-2818,2981-2982`) — Split partial uninstall from `close_scope`; close only after all installs and runs are finished; purge that scope’s install/fiber/session entries on dispose/close; require a new scope and fresh installs for re-admission. Add close→install/start failure and close→new-scope success tests.

5. [high] `/resume <run_id>` lacks an ownership check — `P:548,560` accepts an arbitrary ID; the admin role bypasses scope ownership (`v24/sql/49_host_reads.sql:11-20`), and `HostDB` performs host reads on that control connection (`v24/host/db.py:123-154`) — Resolve the run’s scope first and permit only the current thread’s scope (or an explicit authorization rule) before replay; test a foreign run ID returns `not_found_or_denied` without emitting steps.

6. [high] The control API omits required generation and response contracts — `P:426-428` omits `p_expected_generation`, although SQL requires it for steer/respond/cancel (`v24/sql/47_verbs.sql:73-86,147-148,172-184`); `P:776` later calls `respond` with an extra generation argument, and no Chainlit-string→JSON-object mapping is defined — Either pass generation explicitly or read it on the confined thread immediately before each verb; make `response` a non-empty object and define its wire shape; specify `stale_generation`, `interaction_mismatch`, and `already_terminal` handling.

7. [high] Real-provider preflight ordering contradicts itself — `P:534-537` opens the environment before constructing the adapter, but `P:720-722` requires adapter preflight before any DB transaction — Use key check → adapter construction → preflight with no `HostDB` → `open_env` → scope/install; also make the no-key process-exit versus page-banner behavior consistent.

8. [high] The gate lacks database/filesystem isolation — `P:653-710` gives no fixture ownership or teardown despite the persistent environment in `P:104-113`; the baseline explicitly says to import disposable fixture utilities (`E:1210`) — Run the gate against a disposable database and temporary journal/workspace/spawn directories, never the user’s `agent_v24_ui` or `.uidata`; restore mutated artifact bytes and environment variables in `finally`.

9. [high] The proposed steer-superseded predicate cannot detect an overwritten steer — `P:515` compares `pending_steer.generation < driving_generation`; each steer replaces pending state with generation `old+1` while advancing driving generation to the same value (`v24/sql/40_interpreters.sql:916-923`), so only the newest instruction remains and the predicate is false — Retain local steer sequence/instruction state as `E:1085` requires and mark earlier entries superseded when a newer steer replaces them before consumption; do not infer lost instructions from the latest projection alone.

10. [high] The v1 known-error render row has the wrong effect status — `P:505` expects `tool_call` `succeeded` plus `output.status=='error'`, but an exit-3 v1 frame becomes dispatcher class `failure` (`v24/host/plugins.py:129-134`; `v24/host/line_json.py:352-356`) — Render failed tool effects from `outcome.body.result.output.{code,message}`; change the row to `failed` (with whatever display name is desired) or identify an actual producer of the succeeded/error shape.

11. [high] Interaction/respond and deterministic in-flight controls lost their verification — the fixed script has only two tools plus final (`P:661-665`), and the M3 manual list has no waiting-interaction case or way to hold fake work in flight (`P:726-734`); the baseline explicitly requires waiting-interaction verification (`E:1357`) — Add a scripted interaction→respond path and a controllable fake delay/barrier for steer/cancel; assert empty response remains waiting, valid object response resumes, and token-zero response renders the resulting terminal state.

12. [medium] The pin ladder has stale, contradictory residual text — `P:691` says eleven pins without milestone parameterization, and `P:850` says M1 asserts eleven and falls back to a driver install; these contradict `P:316-318,703,834` — Make every assertion equal the current milestone catalog (`{read}`, `{read,file_search}`, then eleven), retain diagnostics on failure, and remove the automatic-fallback wording.

13. [medium] M4’s fixed three-call gate cannot prove that a skill was loaded — `P:661-665,684` allow only `read`, `file_search`, final, while `P:829` requires at least one skill loaded by `read` — Add a `.v24/skills/<name>/SKILL.md` read to the M4 script and update its exact steps/call count, or add an explicitly separate skill run while retaining the one-run eleven-pin assertion.

14. [medium] M3 requires eleven tools before M4 supplies them — `P:409` defines only two catalog entries through M2/M3, but `P:551,730` demand eleven at M3 — Make `/tools` list `all_specs()` rather than a hard-coded count; expect two at M3 and move the eleven-key manual assertion to M4.

15. [medium] The v1 string result is stated correctly but not carried through output verification — `P:71` is accurate; the host JSON-decodes the string exactly once (`v24/host/line_json.py:133-145`) and model text is `canonical_json(result.output)` (`v24/host/worker.py:1067-1073`), while neither `P:504` nor `E:1124` specifies how decoded v1 output becomes model-visible text — Require artifacts to emit `result=json.dumps(object)`, specify renderer input as the decoded `output` object, and gate a nested success value plus rejection of an unstringified v2-style `{value}` success frame; do not JSON-decode it a second time.

16. [medium] `/resume` incorrectly calls effect rows immutable — `P:51,231` correctly describe changing effect states, but `P:560` claims immutable rows; the reader exposes mutable `status`, `outcome`, and settlement fields (`v24/sql/49_host_reads.sql:239-263`) — Define resume as replay of the current effect versions, deduplicated by `(effect_id,fingerprint)`, with no immutability assumption.

17. [medium] Bash’s spill destination is unavailable to the artifact — `P:615` requires full output under `.uidata`, but artifacts receive only `V24_WORKSPACE_ROOT` and enforce its path fence (`P:605-607`); with custom `--root` (`P:241`) they cannot locate `.uidata`, and the model cannot read a spill outside the root — Prefer `<workspace_root>/.v24/spill/` and return a root-relative path; otherwise add an explicit allowlisted data-directory variable and an access rule.

18. [medium] `run_state` does not define whether it returns a poll envelope or a run projection — `P:430` returns an unspecified dict; `poll` wraps the projection under `run` (`v24/sql/47_verbs.sql:63-68`), while `P:447-448` expects top-level status/revision — Specify that `run_state` validates and returns `poll()["run"]` (with envelope metadata separately if needed), and derive `final_text` from `run.result.final_text`.

19. [medium] Skill validation and loading instructions were weakened from the baseline — `E:1144` requires frontmatter validation and XML escaping, and `E:1158` requires instructions to load bodies with `read` and resolve relative resources; `P:564-591` retains examples but not all of these requirements — Restore explicit validation/escaping and prompt instructions for skill-body loading and relative paths; this introduces no selection state.

20. [low] The export’s selection/codemap-marker requirement is fully replaced by the amended no-selection design — `E:982` asks for markers “where available”, while `P:256-260,621` deliberately has no selection and maps `selected` to `full` with disclosure — Treat `P:621` as the complete v1 contract and record that replacement in the conformance matrix; do not implement hidden selection/codemap state.

## Direct answers to the named checks

- **Pin ladder:** executable as one fresh run per milestone, with M4’s eleven pins in one run. Owner validation only requires a live, on, installed owner (`v24/sql/40_interpreters.sql:2820-2831`); every required key is independently resolved through `v24.resolve` (`:2833-2849`), and successful start emits one pin per requirement (`:625-628`). Eleven is below the sixteen-requirement cap (`:2775-2776`). It is not executable as mutating one existing run’s pin set across milestones: pins are created at start, and no add-pin path is specified.
- **Cache/close:** the `(scope_id,identity,tool_key)` key correctly prevents cross-scope reuse before closure, but is insufficient after `scope_control('close')`; item 4 is required.
- **Line-JSON result:** the plan’s wire description is right. The host, not the renderer, performs the single JSON-string decode; the actual gaps are the wrong failed-tool mapping and missing nested-frame/output assertions (items 10 and 15).

## Questions that materially change design or order

1. When is a scope closed—run terminal, chat end, or only explicit reset? This determines teardown work, durable `/resume` behavior, cache eviction, and persistent-database growth.
2. Is `.uidata/workspace/` intentionally shared by every scope and restart? If yes, “one-time scratch” (`P:241`) needs a precise retention/privacy definition; if no, workspace creation and root propagation must become scope-specific before M1.
3. For real mode without credentials, must the Chainlit process exit 2, or should an already-launched page show `credentials_absent`? The answer determines whether M5 needs a separate CLI/preflight entry rather than only `on_chat_start` logic.
