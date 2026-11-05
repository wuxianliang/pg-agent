# v24 UI — M4 Chainlit agent runtime

Current status: **M5 closeout with abandoned historical evidence (2026-11-04).** `MAX_SAFE_ARGS_BYTES=128` was measured on the current profile after four formal review rounds (the first rejected the 160 B claim; later rounds rejected 128 snapshot defects): 13 targets 64–124 plus two additional 128 B probes per class (one repeat each) (45 probes, 45 passed), 14 complete targets and 3 boundary repeats. Earlier 144/160 batches showed sporadic `finish_length` and are retained as historical, not reused. The bound is an explicit working recommendation, not a token guarantee. `exec11` completes durably (five HTTP requests; write → bash → readback → final; empty guard rejections). The two unrecoverable historical proofs (original-52 baseline and WI-1 pre-incident logical equality) are abandoned by the dated coordinator record `docs/reviews/v24-ui-m5-evidence-abandonment-2026-11-04.json`; the audit reports them under `abandoned_evidence`, never as proof. The formal-review gate is recorded in `prompt-exports/v24-m5-evidence/m5-formal-review.json` after the review binds the current runtime and closeout documents; the final outcome is recorded in the JSON. Real admission ceiling 16384, legacy/fake 8000, completion cap 512, SQL reserve 4096 and run budget/lease/timeout are unchanged. Commit and push of this closeout on `v24/ui-chainlit` are authorized by the 2026-11-04 coordinator decision; `main` is not modified or switched.

## M5 WI-3 incomplete checkpoint (2026-11-03)

The durable evidence is under ignored `prompt-exports/v24-m5-evidence/wi2a-20261103T134358Z/` and the WI-2 reconciliation. It records 8 current-profile HTTP requests: short, write10, and skill completed; exec11 stopped at the first guard failure (`tool_failure`) with no bash execution, readback, or durable final. The original `/tmp` baseline and WI-1 receipts are absent; the resume snapshot contains 1,456 tracked hashes and 55 captured untracked hashes, so it cannot prove the original 52-file baseline or pre-incident logical equality. The historical WI-1 PGDATA incident remains a limitation. The focused offline contracts and the existing 16-command M4 runner passed in WI-2A; those receipts are historical checkpoint evidence, not M5 completion. The post-review offline fixes are verified by `test_real_entry.py`, `test_audit_m5.py`, and a fresh full `run_m4_checks.py` sweep; the audit snapshot exits 3 (`NOT ACCEPTED`) and completion derives the remaining blockers. No new real provider call was possible without a key. See [M5 checkpoint record](../../docs/reviews/v24-ui-m5-incomplete-checkpoint-2026-11-03.md) for source/evidence hashes, actual browser proof, audit results and remaining blockers.

<!-- M5_CURRENT_VALUES_BEGIN -->
legacy_body_bytes=8000; real_body_bytes=16384; output_token_cap=512; reserve_tokens=4096; max_safe_args_bytes=128
<!-- M5_CURRENT_VALUES_END -->

Current capacity values: legacy/fake 8000, real 16384, completion cap 512, SQL reserve 4096, run budget/lease/timeout unchanged, and `MAX_SAFE_ARGS_BYTES=128`. The safe-args value is the post-review working recommendation: 13 targets 64–124 plus two additional 128 B probes per class (one repeat each), 45 probes (45/45, no failures), 14 complete targets and 3 boundary repeats. The batch ran while the prompt already rendered 128, so it measures compliance/robustness, not an unprompted capacity threshold; earlier 144/160 batches showed sporadic `finish_length` (the 160 batch was 41/42) and are retained as historical, so 128 is not a token guarantee. The 16384 real ceiling remains admission headroom for six rounds, not a target body size: retained 8192-snapshot bodies grew 5,917→7,520 B over write10's four rounds and exec11 `v24-real-k5a0wn53` observed canonical bodies 6,498 / 7,416 / 8,080 / 8,434 / 8,734 B (wire maximum 8,751 B) with 12,265 tokens over five rounds, so six rounds project to roughly 14.7k tokens, inside the 20,000-token run budget, while a 16,384 B body would be ≈5.2k input tokens, above the 4,096 SQL reserve. Rounds 4–5 exceed 8192; round 3 (8,080 B) does not. The reserve and the D-UI-8 fallback are unchanged. The 16384 value is admission headroom, not a target body size or a token-safety proof: a body near 16 KB is ≈5.2k input tokens, above the 4096 SQL reserve, so such a call can settle as an unknown/blocked outcome rather than complete; the observed exec11 wire maximum is 8,751 B, below the reserve. The two unrecoverable historical proofs are abandoned by the dated coordinator record `docs/reviews/v24-ui-m5-evidence-abandonment-2026-11-04.json`; completion reports them under `abandoned_evidence` and does not count them as blockers, without writing a synthetic proof. Every other gate, receipt, measurement and formal-review requirement remains mandatory. `catalog.limits_contract` is the single renderer for the prompt and footer; the skill file mirrors the same number and the audit derives the render blocker from the renderer, the footer call site and this marked README block.

## M5 real entry and audit discipline (2026-11-03 review fixes)

The real UI remains explicit opt-in and is not a gate. It requires an absolute, empty scratch directory; the default toolset is `read`, and `write`/`exec` must be requested explicitly because this frontend has no authentication and must bind loopback only:

```sh
SCRATCH="$(cd "$(mktemp -d)" && pwd -P)"
chmod 700 "$SCRATCH"
UV_NO_SYNC=1 UV_NO_ENV_FILE=1 \
V24_UI_MODE=real V24_UI_WORKSPACE_ROOT="$SCRATCH" V24_UI_TOOLSET=read \
  uv run --project v24/ui chainlit run v24/ui/app.py --host 127.0.0.1 --port 8000 --headless
```

The order is key → actual `DeepSeekAdapter` → local preflight → empty-scratch validation → toolset validation → data directory/lock/`open_env`/`AgentRuntime`. A missing key returns `credentials_absent` and leaves the service alive; a missing/non-empty/non-ignored scratch returns `workspace_required`, `workspace_not_empty`, or `workspace_invalid` before database resources. Real mode rejects a scratch equal to the data root, containing it, or under the runtime spill/spawn subtrees. The app does **not** enforce a bind address; the operator must use `127.0.0.1`. One executor thread owns the runtime, so a provider call of up to 120 s can queue every session command; stop/steer during that call is not W13 acceptance. After a real `write`/`exec` run the scratch is non-empty, so a restart with the same directory fails `workspace_not_empty`; real-mode resume across restarts is not claimed. The manual CLI remains:

```sh
UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python -m v24.ui.real --real-provider-smoke --scenario short
# no flag: not_requested / 0; missing key: credentials_absent / 2
```

`--evidence-dir` inside the repository is restricted to the ignored `prompt-exports/` root; the default already satisfies this. Audit output is created with `O_EXCL` and never overwrites retained evidence. Snapshot mode exits **3** with `[snapshot-consistent; NOT ACCEPTED]`; completion mode additionally requires the current five-gate receipt (each gate exit 0, log SHA256 re-verified, and before/after full runtime source maps equal to the audit-time map) before deriving the remaining blockers from current evidence. Pre-review receipt `wi3-checks-*-completion` has the current completion receipt and `gate_receipt.failures=[]`. The two abandoned proofs are reported as `abandoned_evidence` (never as proof) and are not blockers; the formal-review gate is recorded in `prompt-exports/v24-m5-evidence/m5-formal-review.json` after it binds the current runtime and closeout documents; exec11 and final-profile capacity are now evidenced, and the render contract is a derived check, not a standing blocker. The 16384 real ceiling is an admission bound, not a token/reserve safety proof; the SQL 4096 reserve and D-UI-8 fallback are unchanged.

### Final-profile measurement matrix (executed 2026-11-04)

Thirteen targets 64–124 (mixed step) × three content classes, plus two additional 128 B probes per class (one repeat each): 45 probes, all 45 `contract_passed`, 14 complete targets, 3 boundary repeats. The 128 B bound is the post-review working recommendation; the earlier 160 B batch (42 probes, 41 passed, one `finish_length`) and the 224 B pilot failure are retained as historical and are not reused. The bound is not a token guarantee: `finish_length` is stochastic when reasoning consumes the 512-token cap, and W12 (raise the cap) remains the structural fix.

```sh
for target in 64 68 72 80 84 88 92 96 100 104 108 116 124; do
  for class in ascii cjk escape; do
    UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python -m v24.ui.real \
      --real-provider-smoke --profile current --scenario probe \
      --target-args-bytes "$target" --content-class "$class"
  done
done
# two extra repeats per class at the 128 B bound
for round in 1 2; do
  for class in ascii cjk escape; do
    UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python -m v24.ui.real \
      --real-provider-smoke --profile current --scenario probe \
      --target-args-bytes 128 --content-class "$class"
  done
done
UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python -m v24.ui.real \
  --real-provider-smoke --profile current --scenario exec11
```

The capacity record is `prompt-exports/v24-m5-evidence/wi3-final-capacity-summary.json` (SHA256 `b2b400b9aed765e90a0c012211207431e9d15d971847ff395c9827ed332910dc`; 45 samples, 0 excluded, 0 failed, 14 complete targets, 3 boundary repeats). exec11 evidence is `v24-real-k5a0wn53` (SHA256 `e5411fb32ea2e10473a2eefc9539a859d53649b71c462706ca57bf1abb89bb3f`; five HTTP requests, all checks true, `guard_rejections=[]`). Backfilled `catalog.MAX_SAFE_ARGS_BYTES=128`; the prompt and footer render from it, and the `surgical-edit` skill is a synchronized static mirror of the same value checked by the audit. A missing key still prints `credentials_absent` and exits 2 without constructing an adapter or opening a database.

Historical status at M4 repair closeout: **M4 review repairs accepted: final independent Oracle review completed 2/2 with no remaining blocker (2026-11-03).** Round-1 review did not pass; both reproduced supervisor P1 findings and failed/partial plan history are preserved. Commit policy is one separate local repair commit on `v24/ui-chainlit` after closing checks; no push or M5 work. See [the repair record](../../docs/reviews/v24-ui-m4-review-fixes-2026-11-03.md) for the complete item inventory, executed checks and remaining evidence.

## M4 review repair (2026-11-03; final review passed)

The first repair review completed 2/2 lanes; L1's no-P1 assessment was contradicted by L2's subsequently reproduced main-shell-exit/background leak and inner-shell-spawn false-success paths. The targeted repair-plan consultation completed only 1/2 lanes: L1 failed with provider_error/no response; L2 supplied the selected minimal artifact-only plan. No 2/2 plan pass is claimed. A recovery consultation returned two provider-completed responses, but L1 was only an analysis fragment. L2's separated-group candidate requires os.waitid, unavailable in this Python3.12.11/darwin runtime; that candidate was stopped before artifact edits. The final same-group consultation completed2/2 with material conclusions, and the parent coordinating agent selected that smaller topology. Supervisor remains live PG leader, shell inherits the group, and private status carries the real shell rc before group self-SIGKILL. Supervisor terminal emissions self-KILL with rc-9, avoiding the valid-frame/TERM race. Normal accepted SPAWN/EXIT frames also require reap, EOF and absent group; unsolicited STOP/missing status is unknown. Local timeout/cap retains its original cause only after cleanup proof. No waitid/split-group compatibility is added. Final artifact, UI and Backend wrapper regressions all exit0/noSKIP; supervisor-only death fallback and held main-shell-exit PID/group-kill windows are covered.

The repair keeps the 8,000-byte admission ceiling and full 7/10/11 pin sets. Prompt/descriptions and English skills were shortened without trimming tool text or history. Four final round-2 production capacity regressions passed: each reads a complete skill, reads a small file, edits, reads back and finishes through actual adapter builds and scripted sends (20 builds/sends, 36 durable effects). Complete skills are 570/533 B; final bodies span 7,380–7,741 B (259 B minimum body headroom). These measurements do not prove token/usage safety or extra real-provider rounds.

- `repo-recon`：修改陌生仓库前建立结构地图，分页读关键文件，输出不超过 120 words 的摘要。
- `surgical-edit`：先读原文，用一次精确 edit 批量修改，处理歧义后回读验证；大内容小步追加。

Reproduce the checks with `uv run python v24/ui/run_m4_checks.py --log-dir /tmp/v24-m4-checks`; `--only s13` selects all 13 S13 commands including `--node`. This repair's fresh S13 sweep is 13/13 exit 0 without SKIP. Round-1 executions are retained separately. Final round-2 artifact, UI and expanded Backend logs are in `/tmp/v24-m4-repair-round2-20261103/{artifacts-final,ui-final,backend-final}`; [the repair record](../../docs/reviews/v24-ui-m4-review-fixes-2026-11-03.md) lists exact commands, final lines, logs and every disposition. The read-only freeze audit applies only to this uncommitted precommit tree at baseline HEAD with an empty index; it deliberately fails after the repair commit. Reproduce that precommit snapshot audit with `uv run python v24/ui/audit_m4_repair.py --baseline /tmp/v24-m4-review-fix-baseline-20261103.json --output /tmp/v24-m4-audit.json`. Runner receipts record actual `sys.executable` argv in `command` and the `uv run python ...` reproduction in `reproduce_command`; audit additionally checks whitespace in all five authorized new files. Gate's interaction marker now points to the real Backend blank-answer test. Earlier browser snapshots are historical and are not recertified by mocked frontend tests.

Final review against snapshot `2026-11-03/1537` completed 2/2 and permits a local commit. [The repair record](../../docs/reviews/v24-ui-m4-review-fixes-2026-11-03.md#final-independent-review--pass) inventories both lanes and optional limits. Very short lines can amplify memory during full-output splitting; the 100ms terminal drain can conservatively return unknown under extreme load or detached output holders. The 350ms abort probe may fail to establish a child on a loaded runner; current executions passed. No peak-memory or scheduling guarantee is claimed.

Spill reuse preserves immutable snapshots without refreshing mtime. Later distinct writes may evict an older referenced spill under the 50-file/8 MiB retention bound, so an old notice can return not_found. Full bounded bash output is stored, but a source line exceeding the line-preserving reader budget can return line_too_long; arbitrary single-line reconstruction is not promised. The internal spill_read helper has no caller and adds no tool surface. Artifact cap assertions intentionally remain independent in gate, artifact regression and audit.

Historical closeout status at `f4b95d4`: **M4 final acceptance was recorded as GREEN (2026-11-03).** The final UI gate exited 0 with `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` (SHA256 `312c6e2b8521c99f13dd1f2012a0a4368d83b29e29ba71a2e165adb19929704b`), all 13 authorized S13 gates exited 0 including the explicit `--node` invocation, the final M3 aggregation passed 12/12 checks with read7 and exec11 each in three distinct actual processes (SHA256 `d82389ab0768c2b17ae0d837272e80d393cc0e2d78dcb38115bc0c4970bbac2e`), browser §6.3 is 8/8 with a real database close proof, the integrated review completed 2/2 lanes with B1/B2/skill A8 resolved, and the pre-doc-final source audit passed (2,143 snapshot path hashes, 1,449 tracked blobs, 10 authorized tracked changes + 2 new skill files, 52 original untracked hashes unchanged, empty index, `main` unchanged, no browser-token leak). Acceptance baseline: HEAD `243dd9d33cc54725955709f10e162f153757141d`; `main` `1143dce6da0572bccab083da9a6be0175210b062`. That local M4 closeout was committed as `f4b95d4a46e55e0e2b5bb2f6dde3d6d66b23cd35`; it was not pushed. M5 has not started; `MAX_SAFE_ARGS_BYTES` remains `None`. Historical RED/NOT RUN/preflight-BLOCKED and interim-pending records below retain their original dates and scope.

Preparation (2026-11-02): authorized minimal `open_env()` exception exports default `V24_SKILLS_ROOT=<repo>/v24/ui/skills` with `setdefault`, preserving explicit configuration. A disposable, mocked-server check passed for default skills/spill exports and explicit skills preservation; the existing UI gate exited 0, last line `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` (log `/tmp/v24-m3-prep-ui-gate.log`). At that preparation, this did not implement skill mounting (M4).

M2 added `file_search` alongside `read`, with durable rendering and a disposable UI gate. Both keys remain required and pinned; Pi owns the run and RP supplies `file_search`. M3 added the fake Chainlit frontend and durable conversation recovery. The following M1/M2 evidence retains its original scope; no real provider is used.

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

`read` is verbatim UTF-8 without line numbers, bounded to 2000 lines/32 KiB and the 40960-byte serialized-value budget; truncated text spills under `.v24/spill/`. It rejects sensitive paths, symlinks, traversal, nonregular files, invalid UTF-8, NUL, and files over 1 MiB. Known file failures use v2 failure frames/exit 3. Completion cap is 512; provider length termination fails the run rather than truncating a final. At that M2 record, skills and the other ten planned tools were later milestones.

The pre-existing fingerprint encoding uses the deterministic functions-then-columns compact JSON field order. M1 preserves that encoding and fingerprint instead of silently migrating existing metadata; the D-UI-6 helper changes exactly the two authorized digests. SQL-manifest arrays retain SQL_LOAD_ORDER.

Exact acceptance commands, exits and final lines are recorded in [the UI conformance matrix](../../docs/reviews/v24-ui-conformance-matrix-2026-11-01.md) and [deviation ledger](../../docs/reviews/v24-ui-deviation-ledger-2026-11-01.md). The commit stays on `v24/ui-chainlit`; no push.

## Session control plane (S0-M1, 2026-11-05)

`v24/ui/sessions.py` is now a compatibility facade over the headless
`v24/session/store.py`.  `sessions.json` is written as `format_version=2` with
`session_id`, `state`, `session_revision`, `counter_origin`, `start_index`,
bounded `receipts`, and `pending_intent`; the top-level `conversations` key and
the existing `/resume` token/binding lookup are preserved.  A v1 file is
migrated in place after an exclusive `sessions.json.v1.bak`/`turns.jsonl.v1.bak`
copy; every atomic replacement keeps the previous file as `.prev`.  A corrupt
or unknown-version file makes the whole store fail closed (`session_store_corrupt`
or `session_store_unsupported`) and is never overwritten.

`v24/session/` is transport-neutral: it does not import Chainlit or `v24.ui`.
M1 provides `SessionStore` and `SessionService.start/poll` over an injected
`SessionBackend`; the M1 gate uses a scripted backend.  The app still uses the
legacy conversation entry points, so `/resume` and the current UI behave as
before.  Wiring `AgentRuntime` through `SessionBackend` and moving the UI to
session-level verbs is M4 work.

M1 gates (all exit 0): `v24/session/test_session_verbs.py`,
`v24/ui/test_ui_gate.py`, `v24/ui/test_backend_regressions.py`; the offline
`v24/ui/test_real_entry.py` was also run.  S0 keeps
`git diff -- v24/sql v24/load.py v24/host/deepseek.py` empty.

## M3 closeout (2026-11-02)

Launch from the repository root after the existing environment has been initialized:

```sh
V24_UI_MODE=fake uv run --project v24/ui chainlit run v24/ui/app.py \
  --host 127.0.0.1 --port 8000 --headless
```

The independent project pins `chainlit==2.12.0`. A single executor thread owns PostgreSQL connections, journal, runtime, session files and the process lock. Async callbacks submit commands; one persistent consumer per browser session renders immutable events. Callbacks return promptly so busy text reaches the steer inbox. Fake adapter latency is 0.5 seconds on the worker thread. `AskUserMessage` answer/cancel cleanup balances Chainlit 2.12's task restart, keeping the composer usable.

Refresh creates a new conversation without destroying the old scope. Keep the displayed token private; `/resume <run_id> <token>` reattaches an indexed run, while `/resume <run_id>` only accepts the current conversation. Tokens are SHA256-only in `sessions.json`. Running/waiting recovery rehydrates and validates the original workspace/toolset/catalog and durable install identities; terminal runs replay without worker execution. Same-scope subsequent runs inject bounded user/final history. Catalog mismatch is replay-only. `blocked_unknown` is replay-only and cannot start new work or be reclaimed.

At the M3 closeout, `/tools` exposed effective `{read,file_search}` and `/skills` displayed an empty block with the then-current M4 notice. `real` mode was refused (`real_mode_not_enabled`); skill mounting, the remaining tools and safe-args measurement were scheduled for M4/M5. No real provider was called.

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

## M4 admission preflight — BLOCKED (2026-11-03)

> **Historical preflight snapshot.** This section records the 2026-11-03 preflight before M4 source implementation. Its NOT RUN/BLOCKED statements describe that checkpoint only; M4 final acceptance is GREEN below.

M4 has no source implementation yet. Preflight ran on `v24/ui-chainlit` at HEAD `243dd9d33cc54725955709f10e162f153757141d`; `main` is `1143dce6da0572bccab083da9a6be0175210b062`. Before this documentation update, all 1,449 tracked hashes and 52 unrelated untracked paths were unchanged and the index was empty. This update changes only README/matrix/ledger; no production source, plan, SQL, host, reserve, `FRAMING_MARGIN` or fake-adapter bytes were edited. `MAX_SAFE_ARGS_BYTES` remains `None` (M5 output-argument capacity, distinct from input admission). No persistent reset/init/migrate and no provider/network call occurred; sizing probes used local scripted transports with zero sends.

With reserve 4,096 and margin 256, admission requires body ≤3,839 bytes (≤3,328 for a 512-token completion). The complete 11-tool proposal at 5,251 bytes measures estimate 5,507 (`available=-1,411`) and is rejected. The complete-schema candidate with all descriptions removed is 4,041/4,297; that is a candidate-specific size, not a universal impossibility — a relaxed noncompliant 3,584-byte body admits. No compliant candidate was established: the full-schema 11-pin minimum-prose probe is 4,666/4,922 (`-826`), the relaxed skeleton plus 625 bytes of required prose is 4,209/4,465 (`-369`), the shortest complete app prompt with that skeleton is 4,940/5,196 (`-1,100`), and the complete-schema 11-pin app is 5,397/5,653 (`-1,557`). For 4,041 bytes the reserve would need at least 4,298 for one token (4,809 for 512); for 5,397 it would need at least 5,654 (6,165 for 512). These are arithmetic requirements, not authorization to change policy.

A 7-pin read-only start admits at 3,263/3,519 and its continuation at 3,471/3,727; the 7-pin 2,001 continuation rejects at 5,471/5,727. A 7-pin minimum-prose app start admits at 3,693/3,949 with 147 tokens, but it has no history and is not complete workload acceptance. Every admitted sizing row made zero sends.

A separate historical regression using baseline two-key artifacts and disposable PostgreSQL passed: original primary exactly 10 steps/5 effects/2 families/3 transports; original 2,001-byte continuation two builds/two sends with second estimate 3,911/reserve 4,096/max_tokens 185; original D-UI-7 two-requires semantic wall. The first attempt exited 1 on a 0755 journal directory; the corrected 0700 rerun exited 0. A temporary simultaneous old/full-11 probe exited 1 (`invalid_catalog`), so coexistence integration is unverified. These historical results are not new M4 acceptance and do not weaken the planned production read7/exec11 requirements.

Full M4 UI gate, all-stage S13, M3 regression, browser, new-handler, simultaneous-integration and formal implementation review were **NOT RUN**. No M4 commit was created; nothing was staged, committed, pushed or reset. The next step is a user decision on the frozen admission/reserve conflict or an explicit acceptance-scope amendment. Details: [matrix](../../docs/reviews/v24-ui-conformance-matrix-2026-11-01.md#m4-admission-preflight--blocked-2026-11-03), [ledger](../../docs/reviews/v24-ui-deviation-ledger-2026-11-01.md#m4-admission-preflight-record-2026-11-03).

## M4 interim implementation record — historical, superseded (2026-11-03)

> **Historical interim snapshot.** This section records the 2026-11-03 checkpoint before the final M3, browser, review and audit results. Its pending/RED statements are not current status; **M4 final acceptance is GREEN** in [M4 final acceptance](#m4-final-acceptance--green-2026-11-03). Retained for provenance without deleting the earlier records.

This section superseded the preflight BLOCKED status above without deleting it. At this interim checkpoint, M4 source implementation was present on `v24/ui-chainlit`, but **M4 was not yet accepted or committed**. The full UI gate and all 13 S13 commands were green; the disposable M3 three-process regression and the browser `/close` check were RED or in progress; the single formal integrated review and the final frozen/whitelist audit were pending. The final resolution is recorded below.

### Implemented scope

- **Toolsets and families.** `v24/ui/catalog.py` exposes `read` 7 keys, `write` 10 and `exec` 11. `v24.ui.pi_tools` provides 7 (`read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`) and `v24.ui.rp_tools` provides 4 (`read_file`, `file_search`, `get_file_tree`, `apply_edits`); the `exec` union is exactly those 11. The production `exec` run pins all 11 and legitimately invokes Pi `read` and RP `get_file_tree`; independent production `read` (7) and `exec` (11) scenarios both exercise both families. Catalog counts are exactly 7/4.
- **Skills.** `catalog.available_skills()` derives three-child frontmatter XML from `V24_SKILLS_ROOT` without following links, and `app.build_system_prompt()` appends the constructor snapshot. `.v24/skills/<name>/SKILL.md` is readable through the mounted `read` with bytes equal to its source; `ls('.')` contains no `.v24`; no workspace `.v24` is created or copied; `write`/`edit`/`apply_edits` virtual mounts are rejected. Malformed metadata fails closed as `invalid_skill`. The skills block is 439 B; the complete prompt including final newline is 1,190 B.
- **Security/defaults.** Path fences cover existing and absent sensitive targets across all 11 tools; traversal, outside-absolute, symlink and `.v24` paths are refused; failure leaves input bytes unchanged. Approved subprocess environments contain no provider keys and no `PG*`; renderer credential refusal does not mutate durable bytes. The gate also preserves no-socket, SQL-closure, shared-core, descriptor, replay, drift and isolation checks.
- **Artifact limits (interim record; final values are 1,160/1,121 in the final acceptance).** The plan's hard cap remains 3,000 lines / 160 KiB. Interim `wc -l -c` values were Pi 1,159 / 52,689 B and RP 1,120 / 52,179 B; the interim gate pinned `ceil(actual×1.20)` at Pi 1,391 / 63,227 B and RP 1,344 / 62,615 B. The shared core digest is `3a8e5823755c035210266372c20a3a383be2feeda4e1ac2682c2289d6b361b5d`.
- **Admission (D-UI-8).** `app.py` sets `UI_BODY_BYTE_CEILING = 8000` on the fake adapter only. `v24/host/deepseek.py` gains the opt-in constructor property `body_byte_ceiling` (exact `+10/−2` patch, patch SHA256 `1d3f8df554e12097212bfde6690769d1f73d68f8c37fecbd20b31e742b9b81dd`). Canonical UTF-8 body bytes (before `max_tokens`, excluding the 256 B margin) above the configured ceiling fail as `body_too_large`. With `None`, the frozen path is unchanged: reserve 4,096, margin 256, cap 512, the historical 3,655→3,911/185 arithmetic, and `reserve_insufficient` at 3,840. With a configured ceiling, 8,000 is admitted, 8,001 is rejected, and a computed allowance below 1 uses `min(cap, tokens)`; positive allowances such as 185 are preserved. SQL/reserve/margin/cap are unchanged, and this change is not provider token safety.

### Interim build measurements — historical, superseded

Canonical admission body bytes from the actual complete app prompt, skills block and production descriptors with empty history; reserve 4,096 and `max_tokens` 512 for every actual-app row; margin excluded.

| Scenario | Build | Body B | Estimate | `max_tokens` |
|---|---:|---:|---:|---:|
| `read7-actual-app` | 1 | 4,728 | 4,984 | 512 |
| `read7-actual-app` | 2 | 5,191 | 5,447 | 512 |
| `read7-actual-app` | 3 | 5,416 | 5,672 | 512 |
| `exec11-actual-app` | 1 | 6,712 | 6,968 | 512 |
| `exec11-actual-app` | 2 | 7,175 | 7,431 | 512 |
| `exec11-actual-app` | 3 | 7,400 | 7,656 | 512 |
| `read7-2001` | 1 | 3,485 | 3,741 | 355 |
| `read7-2001` | 2 | 5,718 | 5,974 | 512 |
| `historical-2001` | 1 | 1,422 | 1,678 | 512 |
| `historical-2001` | 2 | 3,655 | 3,911 | 185 |

The gate used user input `inspect`; the skills owner's construction used `Inspect README.md.` and measured `read7` 4,739/4,995 and `exec11` 6,723/6,979. The 11-byte input difference explains 4,728 vs 4,739 and 6,712 vs 6,723; the rest of the request is the same complete app/skills/descriptor content. These are tested construction/admission observations, **not a general 8,000-byte safety proof**: a different prompt or history can exceed the ceiling and then fails closed.

The historical fixtures remain independent of the production 7/11 scenarios. The original primary is still exactly 10 steps, 5 effects, 2 artifacts/2 families and 3 scripted transports. The D-UI-7 wall still uses exactly the two historical requires `{read,file_search}`: committed with `emitted=[]`, sole model `unknown`, run `blocked_unknown`, `close_intent.reason=semantic_violation`, `result.close_reason=unknown`, original 5-token success receipt retained, no tool effect/subprocess/target file, both connections IDLE, no retry/cancel. The original 2,001-byte continuation still performs two actual builds and two consumed sends; the second body is 3,655, estimate 3,911, reserve 4,096, `max_tokens` 185, body/wire SHA256 `f847ca9f102c2a64768a5130c432e60525cc962eee4fa34703f9760d0b22c060`. No production pin reduction, 3,001 rewrite or historical replacement occurred.

### Interim commands executed — historical

The UI row is the earlier 12:14 run, superseded by the final 12:58 UI gate in the final acceptance; the S13 rows are the final authorized reuse. The UI gate and S13 sweep ran from the repository root under the sanitized private-cluster wrapper; all S13 exits are 0 and the explicit Node gate actually ran. B0/S11 rows are reused handoff executions under explicit user authorization after the identical host patch and 111 other frozen sources were rechecked.

| Command | Exit | Exact last line | Full log | SHA256 |
|---|---:|---|---|---|
| `uv run python v24/ui/test_ui_gate.py` | 0 | `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` | `/private/tmp/v24-m4-implementation/gate/ui-20261103T121431-1-test_ui_gate.log` | `83af4eb96046c783923d53585a663911b573f8f2c56ff245cacdeb08a498fa38` |
| 13 S13 commands, including `test_node.py --node` | 0 each | exact per-command lines, logs and SHA256 in the [matrix](../../docs/reviews/v24-ui-conformance-matrix-2026-11-01.md#m4-interim-implementation-evidence--historical-superseded-2026-11-03); required Node line `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `/private/tmp/v24-m4-implementation/gate/s13-20261103T121540-*.log` | `verification-results.json` |
| `uv run python /tmp/v24-m4-implementation/gate/pure.py` | 0 | `[passed] M4 pure black-box gate checks` | `/private/tmp/v24-m4-implementation/gate/pure-stable-r2.log` | `322f8f365b4e0980874ed9b8dc62cb97fc047c5a0638b3ea83340a5bc76df0e7` |
| `uv run python /tmp/v24-m4-implementation/gate/history_fixture.py` | 0 | `[passed] historical metadata fixture; two original keys; four simultaneous old/new approvals; no DB or handler execution` | `/private/tmp/v24-m4-implementation/gate/history-fixture.log` | `15589b5ea7b390e2243e74b962ddfebc7fd72ca71a9b1eae615bd436973ec30d` |
| `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 PYTHONDONTWRITEBYTECODE=1 uv run python v24/b0/test_golden.py` (reused) | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `/tmp/v24-m4-implementation/admission-b0.log` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 PYTHONDONTWRITEBYTECODE=1 uv run python v24/s11/test_g10.py` (reused) | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `/tmp/v24-m4-implementation/admission-s11.log` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |

The focused admission probe also exited 0: `[passed] focused byte admission; boundaries=10; default_comparisons=485; constructor_runtime=true; small_reserve=true; invalid_reserve=true; historical_2001=3911/185; provider_calls=0; db_calls=0` (`/tmp/v24-m4-implementation/admission-focused.log`, SHA256 `bad6c106a8ebd7943f346a1cf7d68c11a3857a6b172ea33867b88a837c1d71a9`). Its 485 comparisons cover 8 body sizes × 6 reserves × 10 caps plus 5 malformed cases; it proves the default `None` path unchanged, not provider token safety.

### Interim pending items — all resolved in final acceptance

| Item | Interim state (superseded) | Final resolution |
|---|---|---|
| Disposable M3 three-process regression | Phase 1/2 exited 0; phase 3 exited 1 at `close_scope`; the combined runner stopped. | **GREEN.** Final `final3-validation` exit 0 aggregates 12/12 checks; read7 and exec11 each passed in three distinct real processes; the original `final3-all` RED is retained and reconciled. |
| Browser §6.3 check 8 (`/close`) | RED: `run · converged` then `close_incomplete`; first seven checks were acceptance-partial only. | **GREEN.** Final 8/8 checks; 46 private snapshot SHA256 values in `acceptance-final.json`; real `closed_at` DB proof, two installs/fibers disposed, two prepare/release exactly once, six close phases, binding removed. |
| D-UI-9 `control.py` repair | Pending Oracle and a minimal uninstall-progression repair; `control.py` allocated as the 12th path. | **Accepted.** Two methods only, `+38/−9`, final SHA256 `e2a608de1d7bacaf722e4665ee8b4807d911b3299639623f98ee87d5f79dac8b`; focused Oracle 2/2 lanes; actual DB close proof green. |
| Single formal integrated review | In progress (`3DF0`); no findings. | **Complete.** 2/2 lanes, no failed lane, no repeat review; B1/B2/skill A8 resolved; item-by-item accepted/rejected/deferred dispositions in `review/HANDOFF.md` and `DOCS-HANDOFF.md`. |
| Final audit and closeout | Pending; no final pre-stage audit or commit. | **Pre-doc-final audit PASS**, followed by the coordinator's recheck after these docs and one local closeout commit; no push. |

At the interim checkpoint, these items blocked acceptance. Final resolution: M3 and browser are GREEN, the review is complete and the pre-doc-final audit passed. The historical M3 §6.3 eight-check pass remains the 2026-11-02 record; the interim M3 phase 3 assertion and browser-close RED remain preserved as history. No source was edited for this documentation update.

### Interim limits and next step — historical

At this interim checkpoint, no real provider was called and no `finish_length` measurement existed. No W9 redo, D-UI-6 replay, persistent environment reset/init/migrate or M5 work occurred. `MAX_SAFE_ARGS_BYTES` remained `None` (M5 output-argument capacity, distinct from input admission). D-UI-8's `deepseek.py` admission ceiling was accepted; D-UI-9 was allocated but not yet applied. SQL, all other host files, lock/thread ownership and the remaining frozen sources were unchanged. The final section records the accepted D-UI-9 result, final limits and the M5 sequencing.

## M4 final acceptance — GREEN (2026-11-03)

> Historical acceptance at `f4b95d4`; the later review found the P1 below. This section's logs and measurements retain their original scope and do not certify the current repair.

**M4 acceptance is complete.** The final UI gate, all 13 authorized S13 gates, the final M3 aggregation, browser §6.3 and its database close proof, the 2/2 integrated review, and the pre-doc-final source audit are green. That local M4 closeout was committed as `f4b95d4a46e55e0e2b5bb2f6dde3d6d66b23cd35`; it was not pushed. Acceptance baseline: HEAD `243dd9d33cc54725955709f10e162f153757141d`; `main` `1143dce6da0572bccab083da9a6be0175210b062`.

D-UI-8 remains accepted: `v24/host/deepseek.py` only, `+10/−2`, source SHA256 `4278fb9a55a91e0f809748a07d8dfef7bbc40d76350d351a3820310f1d236620`; 8,000 admitted, 8,001 `body_too_large`; default `None` 4,096/256/512, 3,655→3,911/185 and `reserve_insufficient` at 3,840 preserved; 485 default comparisons, fallback only below 1.

### Final evidence

| Check | Result |
|---|---|
| Final UI gate | exit 0; `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2`; log `/private/tmp/v24-m4-implementation/gate/ui-20261103T125824-1-test_ui_gate.log`; SHA256 `312c6e2b8521c99f13dd1f2012a0a4368d83b29e29ba71a2e165adb19929704b`; gate source SHA256 `47962ce868d7be50bcde4045a576b5658ede6d8592841b015bb03a6133b6cdb3` |
| S13 | 13/13 exit 0, including explicit `test_node.py --node`; the logs are authorized reuse checked by the final frozen-source/host-patch audit; exact rows, logs and hashes are in the [matrix](../../docs/reviews/v24-ui-conformance-matrix-2026-11-01.md#m4-interim-implementation-evidence--historical-superseded-2026-11-03); Node line `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` |
| M3 final aggregate acceptance | **GREEN.** read7 PIDs `10812/10866/10892` and exec11 PIDs `10992/11047/11077`, all exit 0; 7 actual builds per toolset; final `final3-validation` exit 0, 12/12 checks, log SHA256 `d82389ab0768c2b17ae0d837272e80d393cc0e2d78dcb38115bc0c4970bbac2e` |
| Browser | §6.3 8/8 PASS; `browser-evidence/acceptance-final.json` holds 46 private snapshot SHA256 values; no token or raw snapshot is copied into Git |
| Browser DB proof | exit 0; real `closed_at`; 2 installs disposed; 2 fibers off/disposed; 2 `host_prepare` and 2 `host_release` exactly once each; six close phases `request/drain/retire/cascade/barrier/finalize`; binding removed; old partial metadata retained; log SHA256 `53bc4e1b40d4b0e0fb39c54e6ab7ac97fd2bb4668a51d869ff5a67d6adec7169` |
| Review | 2/2 lanes completed (`claude-opus-5-5`, `gpt-6.1-sol-xhigh`) against the immutable 2026-11-03/1223 formal-snapshot hashes; later final hashes were covered by item-by-item fix/regression reconciliation, not a second formal review; no failed lane; B1/B2/skill A8 resolved; every material claim is accepted/rejected/deferred in `review/HANDOFF.md` and `DOCS-HANDOFF.md`. The review handoff left final runtime acceptance to the coordinator; the UI/M3/browser runs above close that hold without a repeat review |
| Audit | pre-doc-final audit PASS: 2,143 snapshot path hashes; 1,449 tracked blobs, 1,439 unchanged, 10 authorized tracked changes + 2 new skill files; 52 original untracked content hashes unchanged; empty index; `main` unchanged; no browser-token leak. The coordinator's credential scan of the 12 allowed paths found no matches; the audit is re-run after these docs and before the single closeout commit. |

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

### Artifacts, B1/B2 and control

Pi is `1,160` lines / `52,732` B → cap `1,392` / `63,279` B, SHA256 `3e5246557c02127e66d9532aafeb7ae4cd273b1668b222bd2d3d452a3137c688`; RP is `1,121` / `52,222` → `1,346` / `62,667`, SHA256 `b9e9a17a6f213e87d65e0e5421fd8a4d695d192f5e3db6e4caf98ee995d9c338`; shared core SHA256 `f962502170e4412554cce3afd6cda80552be5bd09840b4b8364289e3afc06979` (`34,793` B; identical in Pi and RP; gate-defined `_only_shared` range from BEGIN marker through END marker inclusive, including both trailing newlines, each marker exactly once); hard cap 3,000 lines / 160 KiB. B1 release/inspect is workspace-independent while prepare/invoke retain root validation. B2 uses top-level `request.reservation` as the sole authority; 26 captured frames / 16 inspect cases across both families, both targets, moved/deleted roots and known/absent all passed (`artifacts/b2-HANDOFF.json`, `artifacts/b2-focused-reconciliation.md`, `artifacts/b2-dispatcher-wire-results.json`). The lifecycle workspace copy is gone and the 16 actual frames are green. D-UI-9 (`v24/ui/control.py` only, `+38/−9`, final SHA256 `e2a608de1d7bacaf722e4665ee8b4807d911b3299639623f98ee87d5f79dac8b`, 369 lines/23,323 B) changed only `_retire_install` and `close_scope`; focused `close_scope` Oracle 2/2 lanes and the browser DB proof above close the runtime hold. The accepted exception record is in the [ledger](../../docs/reviews/v24-ui-deviation-ledger-2026-11-01.md#d-ui-9--minimal-controlpy-uninstall-progression-exception-accepted).

### Limits and next step

`MAX_SAFE_ARGS_BYTES` remains `None` and unmeasured (M5 output-argument capacity). The 8,000 ceiling has real tested headroom refusal at the 9,045 B and 8,303 B durable cases; it is not a universal threshold. The final `write10` row and those two `body_too_large` rows close the review's B3/A1 evidence gaps; they are not deferred. The old partly disposed binding remains read-only `catalog_changed` with metadata preserved; no rewrite or recovery was attempted. Optional review items remain deferred: capped `find`/`ls` notice, workspace-relative slash globs, unreadable/binary/non-UTF8 overwrite fail-closed, performance/retention/content-address changes. No real provider, `finish_length`, W9 redo, D-UI-6 replay, environment reset/init/migrate, or M5 work occurred; no push. M5 starts only after the M4 closeout commit.

Preserved RED: `final3-all` exit 1, last line `[blocked] final3-backend-edges; stopped before next check; consult Oracle before repair`, SHA256 `8fba7804d4411be8fee652c4f7b3744c69ed285c1c3a0b8369303f01f2085277`; `final3-backend-edges` exit 1, last line `AssertionError`, SHA256 `c072ec6deb66d8e6a0856a908df40894353a68b7aa57e43376324d0a83391277`; and the earlier `final2-read-phase3` exit 1 at `close_scope`, SHA256 `7205b8e7242cce0a400a04b7679b35f938e7aa0831a77ae18b0606e805f28bf8`. The Oracle-driven replacement `final3-backend-edges-immediate` is exit 0, SHA256 `eed3775aea2d59b9b38892a9247199c5bd5e3c26fcc31e511274a773dd33bf91`, using `prompt-exports/oracle-plan-2026-11-03-130135-new-chat-5c5b5e-299e.md` and `m3/oracle-steer-reconciliation.md`; `final3-validation` aggregates 12/12 green and no historical result was rewritten.

Historical RED/NOTRUN/preflight-BLOCKED records above, including the M2 RED, the M4 preflight BLOCKED record, the interim M4 pending record, and the original `final3-all`/`final3-backend-edges` RED, remain at their original dates and scope; the interim M4 pending section is explicitly marked historical/superseded and retains its interim state alongside the final resolution. No historical RED/NOTRUN/preflight-BLOCKED evidence was deleted.
