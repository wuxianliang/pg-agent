# v24 D-S7-2 fairness plan critique — 2026-10-25

## Scope and verdict

Reviewed the complete current plan, the complete original export, and the complete continuation export. Only the original export's **Generated Plan** response (`prompt-exports/oracle-plan-2026-10-25-151628-v24-d-s7-2-fairness-0d54.md:368-713`) is treated as baseline; its composed prompt and selection material are context only. The continuation is `prompt-exports/oracle-plan-2026-10-25-153303-v24-d-s7-2-fairness-8d91.md`.

O1–O6 are accepted as settled. In particular, this review does not propose DRR, a different host burst, partial scans, quarantine, or closure of the general D-S7-2 debt. Source checks were bounded to the worker, DB/journal interfaces, host read/recovery/claim SQL, and the named test seams. No implementation was changed and no gate was run.

The host-only design remains viable, but it is not implementation-ready until the O5 per-call guard, prepared-ready reclaim overlap, claim error taxonomy, and opportunity accounting are made precise. The original export's substantive recovery, pagination, validation, file-impact, and regression content is mostly retained; the principal fidelity regression is that the continuation's formulas and recovery distinctions were not fully recomputed after the adjudicated orphan rechecks and O5 rule.

## Findings

### 1. O5 is stated as a rule but lacks the mechanism that enforces it

Plan `:126` removes failure counts/quarantine, and `:142` says an effect gets at most one fresh claim per top-level fair call, but the state table contains no per-call attempted set. Without one, a later visit in the same call can wrap the cursor and claim the same effect again. Plan `:164` further says “下次 visit 再观察,” contradicting `:65`, `:83`, and `:142`, which correctly defer re-observation until the next **top-level call**.

**Correction:** specify an invocation-local `attempted_effects: set[UUID]`, created empty for every `run_scopes_until_idle` call and discarded on every return/exception. Check and insert the effect ID **before** every covered `db.claim` call, not after a response; a lost or malformed response is not permission to claim again in that call. Complete the O3 scan first, then filter attempted IDs before determining class availability and selecting a candidate. If no unattempted candidate remains, that visit produces no fresh opportunity and the remaining ready work must keep the result non-idle. Advance `effect_cursor`/`host_streak` only for an actual selection, not for a filtered candidate.

Add G11-G coverage with multiple visits of one scope inside one top-level call: deferred, confirmed stale/terminal, and token-race outcomes must all suppress that effect until the next call; the next call must read and try it again. Test both wrap-around and a second candidate so the check proves suppression rather than merely cursor movement. Change plan `:164` to “next top-level call,” and remove the obsolete optional `quarantined` statistic at `:130` and residual “failure state” cleanup wording at `:128`; O5 leaves no such state to clean.

### 2. Prepared `ready` reclaims are a real claim path and can bypass a discovery-only guard

This is not hypothetical API bookkeeping. `_resume_prepared` sends a prepared record whose DB row is `ready` directly through `_claim_and_execute` (`v24/host/worker.py:160-170`), and that path performs a new `db.claim`, token re-read, and execution (`:342-368`). Only the `claimed` branch reuses the original token. The plan acknowledges “ready 重新 claim” at `:138` and `:161`, but `:74` excludes every prepared resume from new-work accounting, `:142` describes filtering only in discovery, and `:143` permits one prepared plus one fresh dispatch.

That leaves two distinct hazards:

- If only discovery consults the O5 set, a prepared-ready claim and a discovery claim can target the same effect in one top-level call after a race/recovery makes it ready again.
- If prepared-ready claims are instead counted as fresh opportunities without changing anything else, FC-1/FC-2 and the one-fresh-opportunity-per-visit formulas fail. For example, an A visit with a prepared-ready host reclaim followed by an A discovery claim produces two physical new claims before B's first visit; the first two physical claim opportunities need not contain one per scope. An uncounted prepared host reclaim also cannot be assumed to follow the discovery-only host streak.

**Correction:** separate **physical claim safety** from **recovery/fairness accounting**. At minimum, every claim of a row observed `ready`, including a prepared-ready reclaim, must pass through the same per-call attempted guard in finding 1. A claimed-token resume makes no new claim and does not consume that guard.

The least disruptive accounting consistent with plan `:74`, `:82`, O4's separate quotas, and the existing FC formulas is origin-based: a prepared-ready reclaim remains `prepared_attempts`/recovery work and does not increment `new_opportunities`, the fresh effect cursor, or `host_streak`; it is nevertheless barred from claiming the same effect twice in one call. Discovery may still select a **different** unattempted effect, preserving O4's separate prepared and fresh quotas. FC-1/2/3 must then say explicitly that their “fresh” unit is discovery-originated, and their closed-system preconditions do not include a visit where prepared activity leaves no eligible discovery candidate.

If O1 was instead intended to count every physical `advance(... class=claim ...)` as a fresh opportunity, the current prepared/fresh split, burst accounting, and FC bounds cannot be retained unchanged. That interpretation requires new formulas and tests before M-F1a; it cannot be resolved by silently incrementing `new_opportunities` in the prepared branch. Add G11 cases for both orders—prepared-ready then discovery, and discovery then a prepared-ready record becoming visible—asserting one physical claim per effect per call, separate recovery/fresh counters, and continued fresh dispatch for a different eligible effect.

### 3. The claim error table must distinguish races from protocol failures by phase and by re-read evidence

Plan `:166` makes `invalid_args` fail-fast, while `:165` and O5 allow a confirmed terminal race to be skipped. Current SQL proves these rules overlap: a claim against a terminal target returns **`invalid_args`**, not `already_terminal` (`v24/sql/30_advance.sql:579-585`). An expired business claim returns `stale_claim` (`:880-885`). The original export's generic grouping of `stale_claim`/`invalid_args`/`already_terminal` at `:565` is therefore not an implementable classification for the fair path.

Use a phase-specific table such as the following, without adding or renaming any kernel code:

| Observed result | Fair-path classification and action |
|---|---|
| Claim `deferred`, valid empty claim token | Expected live-claim conflict. The attempt counts; zero IO/receipt; suppress that effect for the rest of this top-level call. |
| Claim `stale_claim` | Use at most one `host_effect` re-read to confirm the stale/terminal/changed-state race. On confirmation, count the attempt, suppress the effect, and leave recovery to the existing quota; never issue a second business attempt. A failed or contradictory re-read is protocol-fatal. |
| Claim `invalid_args` | Re-read once. A terminal current status confirms a terminal race and follows O5 suppression. A nonterminal row means malformed request/lease or another protocol error: raise `HostDBError` immediately. Do not expect `already_terminal` from the current terminal-target claim branch. |
| Claim `committed` with a structurally valid token | Re-read `host_effect`. Exact claimed status/token match authorizes execution; any status/token mismatch is a token race with zero IO and per-call suppression. A read error or malformed envelope is protocol-fatal. |
| Unknown disposition, committed-without-token, malformed envelope/cursor, driver exception, `unauthorized`, `effect_id_conflict`, or other non-race error | Fail fast as `HostDBError`/`HostContractError` or propagate the driver exception. Do not convert it to a skippable conflict or claim again to obtain details. |
| Settlement `replay` | Record the existing settlement event; no additional dispatch. |
| Settlement `receipt_conflict`/`stale_claim` | Preserve the durable outcome for reconcile/conflict handling; do not turn it into a fresh-claim conflict or new IO. Other settlement protocol errors need the same explicit fatal rule rather than the blanket “all errors return False” mapping. |

The fair path also cannot blindly reuse legacy error suppression. `_reconcile`, `_resume_prepared`, and `_orphan_state` currently skip point-read errors (`worker.py:161-163,208-210,267-269`); `_expired_claims` converts read/cursor errors to `False` (`:282-301`); `_recover` converts an error envelope to zero (`:303-311`); `_settle` maps every error envelope to `False` (`:688-699`). Preserve those mappings only on legacy entry points. Fair wrappers must validate envelopes and distinguish expected races from protocol errors, subject only to an explicitly chosen out-of-roster ownership rule in finding 7.

G11-G should include separate real or scripted cases for terminal-target `invalid_args` versus malformed-request `invalid_args`, plus stale confirmation failure, committed/token mismatch, malformed committed envelopes, and recovery/read errors. These are different assertions and should not share one generic “error envelope” expectation.

### 4. FC-1/2/3 need one consistent opportunity unit and an explicit opportunity-dense window

Plan `:81` says any `S·k` global opportunities give every scope `k` attempts **if every visit produces one fresh opportunity**, but then says visits without fresh discovery are not counted. Simply dropping those visits from the trace does not preserve the theorem: two A opportunities separated by empty B visits can form a consecutive two-opportunity window with zero B opportunities. Plan `:88` mostly states the necessary dense-window assumption, but weakens the unit again by writing “全局机会/visits.” Opportunities and visits are interchangeable only when every visit yields exactly one discovery-fresh attempt.

**Correction:** keep two separate contracts:

1. RR visit fairness holds for the fixed roster regardless of empty/blocked visits.
2. The exact `S·k` opportunity bound, the `4N` class-selection bound's conversion to `4SN`, and ADV-L's prefix-difference assertion hold only in an **opportunity-dense** interval: fixed roster, every visit completes discovery, and every visit produces exactly one discovery-originated claim attempt. A visit with no eligible unattempted candidate, a fatal error, or an excluded prepared-overlap case violates the premise; it is not silently filtered out of the evidence.

Define class availability after O5 filtering, and make FC-3's `N` count eligible candidates in the target discovery class. G11-L should separately test (a) a dense interval where numeric bounds must hold and (b) empty/conflicted visits where only RR visit rotation is promised. G11-B may prove the prepared/fresh quota and burst behavior, but must not use a prepared-heavy trace as evidence of the dense FC numeric bound unless its assumptions are independently asserted.

### 5. The RPC formulas were not updated for three orphan checks or prepared-ready claims

The plan now has orphan checks before prepared, after prepared, and after recovery (`:137`, `:139`, `:140`). Each check can inspect the full unfinished-dispatch snapshot and perform one point read per candidate. Nevertheless, `:150` retains the continuation's one-check `J_u` term. The continuation formula at `:49` was correct only for its then-single orphan check.

**Correction:** with a common bound `J_u` for the three finite snapshots, the per-visit journal-stage bound is:

```text
2J_p + J_r + 3J_u
```

More precisely, use `J_u1 + J_u2 + J_u3` when each recheck takes a fresh bounded snapshot. Do not charge only one scan while specifying three. Add an instrumentation case with an **expired** unfinished dispatch that passes the first two checks and is recovered before the third; a live orphan exits at check one and cannot establish the three-check maximum.

The same paragraph also accounts only for the fresh claim pair. A normal fresh claim is two RPCs—one `advance` plus one `host_effect` re-read (`worker.py:346,354`), not two re-reads. A prepared-ready reclaim can add another claim/re-read pair beyond the initial `J_r` point read; a claimed-token resume does not. Add that possible pair to the per-visit bound, and separately budget any error-classification re-read required by finding 3. G11-B/G should record these actual RPC sequences rather than checking only pagination calls.

### 6. Pass termination and `RoundStats` are not yet implementable contracts

The algorithm refers to a “complete roster pass” at `:144`, but no state tracks which scopes have been visited in the current pass, where a pass starts when RR resumes mid-roster, or which pass-level pending/progress flags are reset. `next_scope_after` alone cannot reconstruct a complete observational pass.

**Correction:** specify invocation-local pass state (for example, `visited_this_pass` plus pass-progress/residual-work flags), reset at each pass boundary and not carried across top-level calls. Evaluate a just-completed full pass before declaring budget exhaustion: with `S=1`, an empty roster member, and `max_rounds=1`, “complete idle pass” and “budget exhausted” otherwise conflict. Define analogous precedence for `blocked_no_progress` versus `budget_exhausted`.

The statistics contract also needs these corrections:

- Existing `RoundStats.merge` sums neither `rounds` nor `idle` (`worker.py:51-59`); the fair aggregator must set them deliberately rather than relying on old merge behavior.
- Define whether `pending_work` means “seen during the call” or “still pending at return.” OR-merging a historical flag cannot be used to prove final idleness. Keep a separate diagnostic if both meanings are wanted, and specify how `stop_reason` is assigned rather than merged.
- Plan `:140` and G11-F require recovery command count and actual applied count to be distinct, but `:130` adds no field for the latter. Define explicit command/applied/manual-debt/has-more representations while retaining legacy `recovered` semantics for the old entry.
- Clearing per-scope maps when a scope leaves the roster (`:128`) must not clear the scalar `next_scope_after`; `:114` deliberately uses that UUID as a strict-order anchor even when it is absent from the new roster. Clear only the keyed per-scope state.
- Define `resume_cursor` by stable journal first-occurrence order (ideally journal sequence plus effect ID), not a mutable candidate-list index. Otherwise removal of the cursor candidate can reset rotation to the head.

Resolve the empty-roster contradiction at `:112` versus `:144` together with ownership below: unconditional zero-visit idle is not equivalent to “empty roster and no pending work.”

### 7. Explicit roster ownership and off-roster journal debt are undefined

All three journal queries are worker-global (`v24/host/journal.py:273-316`). Existing worker helpers call `host_effect` **before** checking whether the returned row belongs to the requested scope (`worker.py:160-166,207-213,266-272`). Thus an explicit roster is not an ownership boundary: off-roster journal records can cause reads, errors, and unresolved work, and an empty roster provides no visits through which to classify them.

This interacts directly with the new fail-fast rule. Treating every `not_found_or_denied` as fatal can make an unrelated or no-longer-authorized journal record stop every roster; silently skipping it can make the worker report idle while durable outcomes remain unsettled. A unique scope per test does not isolate this condition if cases still share a journal.

**Correction:** lock one ownership/idle contract before implementation:

- either require a dedicated journal per worker identity and require the roster to cover every unresolved journal scope, validating violations explicitly; or
- support subsets by classifying off-roster/unauthorized journal IDs as unresolved external debt, never processing them under another scope and never silently treating them as empty. Then define whether `idle` is roster-scoped or worker-wide and expose the off-roster debt separately.

The journal currently lacks a reliable scope field for pre-filtering, so “just filter before `host_effect`” is not an available implementation shortcut. Add an off-roster pending/prepared/unfinished case, including an empty explicit roster, and use a fresh journal per isolated G11 case unless the shared-journal behavior is the feature under test.

### 8. FC-4's proposed cold-start harness does not yet control all inputs it names

Plan `:84` and ADV-H rely on a scripted clock and identical DB/journal starts. G9's `FakeClock` drives `ScriptTransport` (`v24/s10/test_g9.py:156-164,180-183`); it does not control `HostDB.remaining_lease_ms`, which uses `datetime.now(timezone.utc)` (`v24/host/db.py:204-215`), or SQL recovery's `now()`. Creating two workers sequentially also does not recreate the same DB/journal prefix after the first worker has appended events and changed rows.

**Correction:** specify snapshot/restore of both DB state and journal prefix, or construction of two independently identical fixtures, before each cold run. Restrict the basic FC-4 selection case to lease-independent paths, or seed lease states safely away from expiry boundaries; do not cite G9's transport clock as control over worker/DB lease decisions. If cold determinism is intended to cover prepared/orphan/recovery branches at lease boundaries, a real worker/DB clock design is missing and must be added deliberately rather than assumed from the fixture name.

The default roster cursor also needs one exact binding: `HostDB.host_scopes(after=...)` takes a UUID (`db.py:135-136`), so plan `:134` must pass `response["next_cursor"]["scope_id"]`, validate that shape, and check strict advancement. Passing the cursor dictionary itself is not the existing API.

## Material decisions to lock before M-F1a

1. **Prepared-ready accounting:** use the least-disruptive origin-based accounting in finding 2 with a shared physical-claim guard, or count every physical claim and redesign the FC quotas/bounds. Do not leave the two interpretations to separate implementation and model authors.
2. **Roster versus worker ownership:** decide who owns off-roster journal debt and whether `idle` describes the roster or the whole worker. This determines explicit-subset behavior, empty-roster results, fixture/journal layout, and the fail-fast exception taxonomy.
3. **Caller cancellation:** the plan covers existing DB `cancel_requested` recovery but not cancellation of the new top-level loop. If cooperative caller cancellation is required, decide it before freezing the API/stats: check only at safe visit boundaries, and once claim/execution starts, preserve the journal/settlement path rather than abandoning an outcome. If it is not required, state explicitly that `max_rounds` limits visits only and is neither a wall-clock deadline nor in-flight cancellation/preemption.
