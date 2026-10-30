# v24 post-closeout follow-up plan critique

## Scope and assessment

Reviewed the current `docs/plans/v24-post-closeout-followup-2026-10-25.md` and only the **Generated Plan → Response** portion of `prompt-exports/oracle-plan-2026-10-25-093837-v24-oracle-d80bc2-9f39.md`; the export's composed prompt and selection material were treated as context, not baseline plan text. Code references below are from the intended v24 worktree at `996cb5bc86f38fe5cbc21d058e93df54b4923620`.

The recorded D1–D7 decisions are not reopened. The plan's principal corrections are sound, but the following implementation and evidence seams remain. This was a static review: no runtime gates, merge, or provider call was run.

## Findings

### 1. M-S/G9 must bind journal evidence and make borrowed ownership explicit

**High — an inconsistent journal can still yield false success, and the wrong borrowed context manager can destroy the shared fixture.**

The per-invocation request-key requirement is correct, but three ownership/binding contracts remain:

- **Bind dispatch evidence to both the known run and the settled outcome.** The checks at `docs/plans/v24-post-closeout-followup-2026-10-25.md:276` and `:284` select journal records by model ID and compare only the `final`/`usage` subtrees of `mapping.result`. `HostJournal.records_for()` and `last()` filter only by effect ID (`v24/host/journal.py:257-271`), while journal `run_id` is optional and only type-checked (`:195-196`). Require both dispatch records' `run_id` to equal the bootstrap run, `dispatch_finished.payload.outcome` to equal the historical effect's outcome, and the **whole** `mapping.result` to equal `outcome.body.result`; the worker already records that authoritative outcome (`v24/host/worker.py:459-470`). Otherwise a wrong-run record or an `unknown` journaled outcome alongside success-looking mapping can satisfy the enumerated checks. Add mismatched-run and mismatched-outcome G9-L negatives without changing the journal format.
- **Define borrowed contexts as non-owning.** “Borrowed context” (`docs/plans/v24-post-closeout-followup-2026-10-25.md:291-293`) must mean `nullcontext(fixture)` and `nullcontext()`, not returning the real `StageTestDB`: its `__exit__()` calls cleanup (`v24/s1/setup_db.py:493-500`), which reaches `DROP DATABASE ... WITH (FORCE)` (`:320-330`). Reusing the real helper context likewise closes the outer helper. Patch the canonical dynamic import targets `v24.s1.setup_db` and `v24.host.deepseek.DeepSeekAdapter` (`v24/host/smoke.py:57`, `:68`), not only G9's differently imported aliases (`v24/s10/test_g9.py:45-54`). The outer host/owner and helper must remain usable; smoke owns and closes only its new HostDB/journal.
- **Give G9 an observable, owned journal path and captured stdout.** `_live()` returns only an integer, deletes the path on success, and exposes a path only in failure output. “Independent journal directory” alone cannot support the required deletion/retention/no-premature-output assertions or test-side cleanup. Patch `tempfile.mkdtemp` to create and record a fresh child directory per invocation under G9's `workdir`—never return the shared workdir itself—and use `redirect_stdout`. After each retention assertion, the outer temporary-directory owner can remove the test evidence.

These are test-only seams except for the stricter verifier comparisons. They require no production injection parameter and no nested `setup_db()`.

### 2. P0 requests an impossible future SHA and no longer explicitly owns the formal plan in the source branch

**High — P0 cannot be completed as written, and the first milestone can omit the supposed authoritative plan.**

- P0 must record the “最终发布源提交” (`docs/plans/v24-post-closeout-followup-2026-10-25.md:200`), but that commit is produced only by the subsequent M-H/M-M/M-S/M-E/M-F commits and is fixed at M-P (`:377`, `:608-615`). P0 should record the then-current v24 HEAD and the fixed historical baselines; M-P should record the final full source SHA after M-F.
- The generated response explicitly required the formal plan to be tracked at the same repository-relative path in the **v24 worktree** (`prompt-exports/oracle-plan-2026-10-25-093837-v24-oracle-d80bc2-9f39.md:148`). The current handoff says only to carry it into an isolated release/integration worktree (`docs/plans/v24-post-closeout-followup-2026-10-25.md:7`). Yet P0's results ride the first milestone (`:44`), the plan is updated from P0 onward (`:422`), and M-H through M-F commit from v24. Restore the explicit source-worktree tracking step before P0/M-H, without moving or overwriting the main checkout's untracked original.

### 3. M-E needs separate negative-control and live-attempt evidence records

**Medium — one status/exit-code tuple cannot faithfully describe both commands.**

M-E mandates an actually executed keyless negative control (`docs/plans/v24-post-closeout-followup-2026-10-25.md:311`) and then defines evidence fields around a singular command/status/exit record (`:323-346`). The negative control really executes and returns `credentials_absent`/2; the live-attempt record may simultaneously be `not_run`, `not_authorized`, and `not_executed`. Those are different events, commands, timestamps, and exit semantics.

Require separate, named **negative-control** and **live-attempt** rows (or equivalent field groups) in all three artifacts. Never copy the negative control's real exit 2 into the live attempt's exit code. This clarification preserves, rather than changes, the settled rule that M-P depends on completion of M-E's evidence state, not live success.

### 4. Cleanup, run-cancellation, and interruption semantics need exact contracts

**Medium — success ordering is fixed, but failure evidence and cancellation coverage still have gaps.**

- **Recursive deletion can destroy the journal before reporting failure.** The plan says failures retain the journal and cleanup failures preserve evidence (`docs/plans/v24-post-closeout-followup-2026-10-25.md:21`, `:285`, `:300`). A real `rmtree` can unlink `journal.jsonl` and then fail to remove the directory or another entry. It cannot both attempt recursive deletion and guarantee that the original journal survives every cleanup error. Decide whether retention is guaranteed only before deletion starts and best-effort afterward, or name a cleanup design that supplies the stronger guarantee. G9-L should include a partial-deletion failure, not only a test double that raises before deleting anything. The required **success** order remains verify → leak check → close resources → fixture exit → verified deletion → success output; this finding does not weaken it.
- **Run cancellation needs an explicit late-success negative.** The kernel permits a cancelled run to retain a succeeded model and successful late outcome while preserving the cancel seal (`v24/sql/48_loop.sql:817-830`; demonstrated at `v24/s4/test_g2b.py:2176-2189`). The plan's `status="completed"` plus matching `run.result.final_text` checks correctly reject this state, but G9-F's listed fixtures do not isolate it. Add a cancelled-run/late-success case within the existing G9-F or direct-verifier coverage; do not change the kernel's late-settlement contract.
- **The generated response's process-interruption cleanup requirement was weakened.** The baseline explicitly required failure **or interruption** to close resources and retain the journal (`prompt-exports/oracle-plan-2026-10-25-093837-v24-oracle-d80bc2-9f39.md:406`). The current text retains only no-retry/no-SKIP wording and a hard-kill disclaimer (`docs/plans/v24-post-closeout-followup-2026-10-25.md:285`). Specify that an ordinary Python `KeyboardInterrupt` follows the best-effort `finally` cleanup/journal-retention path and is not converted into success or SKIP; distinguish that from SIGTERM/SIGKILL, for which no such guarantee exists without a handler. Add a G9 interruption case using `ScriptTransport` to raise `KeyboardInterrupt`, asserting one HTTP attempt, no retry, no success output, closed resources, and retained journal. Do not claim that synchronous injection proves an OS-level signal exit status, and do not add a signal-handling subsystem.

### 5. Release freshness, staging, and identity checks need to be made operational

**Medium — the M-P/M-A split is correct, but its surrounding commands do not yet prove the intended release.**

1. **Refresh at M-P and use remote refs for remote topology.** P0 fetches once but still runs `git merge-base main v24` and `git rev-list --left-right --count main...v24` (`docs/plans/v24-post-closeout-followup-2026-10-25.md:483-489`), even though local main is intentionally allowed to remain stale. After fetching, those checks should use `origin/main`. Fetch again immediately before choosing the M-P base; the P0 fetch can be five milestones old. If the publish push is rejected because main advanced, discard the unpublished candidate and restart the same one-merge procedure from fresh `origin/main`, rerunning all candidate checks if D4 still applies; merely fetching and retrying does not validate the new base.
2. **Clarify merge staging and the tested-tree comparison.** M-P's “只提交” evidence documents (`:389`) weakens the generated response's clearer instruction to inspect all merge-staged content and **additionally** stage only named evidence documents (`prompt-exports/oracle-plan-2026-10-25-093837-v24-oracle-d80bc2-9f39.md:508-510`). Restore that wording so the merge cannot be read as docs-only. Define the identity check as a tested-tree→merge-tree diff containing only declared documentation paths, with execution files unchanged; full-tree equality is impossible because the draft release record and evidence edits are expected. M-A should similarly verify that merge→audit changes exactly the release record and this plan.
3. **Verify exact parents and remote ancestry, not just display them.** `git show --format='%H %P'` plus source-ancestor checks (`docs/plans/v24-post-closeout-followup-2026-10-25.md:598-604`) does not prove that the intended merge and audit commits reached `origin/main`. Compare merge identity and parent order exactly against `<merge_sha> <recorded_main_base> <fixed_v24_source_sha>`. M-P's immediate post-push check should equate `origin/main` with the merge SHA. After M-A, explicitly fetch and require both `<merge_sha>` and `<audit_sha>` to be ancestors of `origin/main`. Spell out M-A's push as `git push origin HEAD:refs/heads/main` from the isolated release branch, as already done for M-P.

### 6. Restore the network-test safeguard and correct the reference gaps

**Low — localized corrections, with no design expansion.**

- The generated G9 contract prohibited both a new real-network-capable test entry and a public adapter-injection interface (`prompt-exports/oracle-plan-2026-10-25-093837-v24-oracle-d80bc2-9f39.md:412`). The current “不新增生产注入参数” (`docs/plans/v24-post-closeout-followup-2026-10-25.md:291`) preserves only the second idea. Restore the explicit prohibition on adding a real-network-capable G9 entry alongside the existing ScriptTransport/network-deny requirements.
- `docs/plans/v99-core-native-plugin-plane-2026-10-20.md` is cited as the W1–W4 boundary authority (`docs/plans/v24-post-closeout-followup-2026-10-25.md:654`), but it is untracked in v24 and absent from both `v24:` and `main:`; it will not silently appear in the release. Label it as a non-release working reference and keep the operative Phase 0/W1–W4 boundary in the tracked release record, or deliberately review and list that document in the release manifest. Do not leave a released reference whose target is absent.
- Two line references in the current-state note are off by one: the `ready/claimed` predicate begins at `v24/sql/49_host_reads.sql:184` (use `:183-186` for the filter), and G9 `ALL_CASES` spans `v24/s10/test_g9.py:69-70`, not `:68-69` (`docs/plans/v24-post-closeout-followup-2026-10-25.md:66`).

## Requested corrections verified, not findings

- **Smoke success ordering:** M-S now has the required verify → leak check → close journal/DB → fixture exit → verified directory removal → success output order (`docs/plans/v24-post-closeout-followup-2026-10-25.md:285`, `:300`). Known run/model handles, strict reader envelopes, journal mapping/final/usage equality, and nonnegative integer checks are supported by the current code and reader payloads.
- **Per-invocation smoke identity:** M-S now requires unique request keys on every invocation and explicitly rejects PID-only reuse (`:270`, `:297`), matching stored-response replay in `v24/sql/30_advance.sql:254-262`. This closes the repeated-borrowed-fixture collision; do not reintroduce PID-only keys.
- **G9 fixture borrowing seam:** The dynamic imports provide a sound test-only alternative to nested setup (`v24/host/smoke.py:57`, `:65`, `:68`). Finding 1 specifies the non-owning teardown and canonical patch targets required to make that seam safe; no production injection or nested `setup_db()` is needed.
- **M-E dependency:** M-P consistently requires an accurately recorded M-E state, not a successful live call (`:173`, `:343-348`, `:394`, `:614`). A started live failure remains `failed`; host defects or unattributed failures still require resolution before release.
- **Publish-record split:** M-P creates the draft record without a fictitious merge SHA; M-A separately adds the real merge SHA/parents and pushes the audit commit (`:175`, `:390-392`, `:401-413`). This removes the self-reference problem and should be retained.
