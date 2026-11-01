# Focused critique: v24 Tool/Plugin ABI W8 v1 acceptance plan

Review target: `docs/plans/v24-tool-plugin-abi-w8-v1-acceptance-2026-11-01.md`.

Baseline compared: both generated Oracle lanes in `prompt-exports/oracle-plan-2026-11-01-082729-w8-deep-plan-v24-too-1497.md` (lane 1: 150–620; lane 2: 629–1297). Repository checks were made at HEAD `62972465995f738726cd6bb8c5ecb956d86303ac`; the tracked worktree was clean. This was a static review only: no sweep or gate was run.

The plan is not yet execution-ready. The main blockers are the impossible precheck form of audit 7, the Result/fallback/publication ordering, and two incorrect evidence bindings. The detailed command table, Node-fatal rule, frozen-design/vector/SQL constraints, 11/11 rule, and no-runner rule should remain unchanged.

## 1. Implementation-bearing lane content lost or weakened

### 1.1 Lane 1's assertion-level binding read is reduced to function-entry anchors

- **Lane 1, export 373–385** assigns exact read spans for the lifecycle helpers and assertions, G12-A/B/C/F/L, R14, B0 `_compare`, and the Node gate, plus an assertion-oriented `evidence-binding.tsv`.
- **Plan §4.3 and §13 W8-1** mostly give function-entry anchors such as `g12_a:641`; they do not specify the assertion spans that the executor must bind, despite Done-when W8-1 requiring file, line interval, and SHA-256.

Function names alone do not satisfy the plan's own fail-closed binding rule. Carry forward lane 1's binding-read table, adapted to the plan's 17 clause IDs and corrected by §2.2 below. In particular, bind the actual assertions at `test_lifecycle.py:645-678`, `:687-708`, `:723-735`, `:793-829`, `:957-1002`, and `test_node.py:91-121`, rather than merely naming their enclosing functions.

### 1.2 Lane 1's exit-condition verdict semantics disappear

- **Lane 1, export 461–478** defines `NOT-TRIGGERED` and assigns explicit dispositions to the six design exit conditions.
- **Plan §8.1 and §8.4** remove `NOT-TRIGGERED` from the closed vocabulary and give the six rows only prose under “W8 当前处理”.

This conflicts with Done-when 6, which requires a verdict for each of the six conditions, and leaves audit 7 able to check only their row count. Restore an explicit verdict column and a closed vocabulary for this table, or define a separate exit-condition vocabulary. Do not leave the executor to infer verdicts from prose.

### 1.3 Lane 2's scripted-transport verification loses its implementation owner

- **Lane 2, export 808–818** requires W8-0 to verify the actual `model_adapter`/harness transport path, in addition to the lifecycle, byte, and zero-spawn assertions.
- **Plan §4.3 clauses 7b/7c and §13 W8-0/W8-1** mention source inspection generally, but W8-1 names only lifecycle, Node, and golden files, while 7c is reduced to absence of `--real-provider-smoke` from the command table.

The absence of one smoke command does not prove that another swept entry point cannot construct a real provider. Restore an explicit, owned pre-sweep binding for the scripted transport construction used by the lifecycle/B0 paths and an external-network entry-point review covering the other swept gates. Clearing credentials is supporting hygiene, not proof of no network access.

### 1.4 Lane 2's required full rerun after a rebase is weakened

- **Lane 2, export 1218–1226** explicitly requires a complete acceptance rerun after any safe rebase.
- **Plan §12.3** says only to confirm the accepted HEAD/source after a rebase and then update the same publication unit.

That is also inconsistent with the fixed `6297246` baseline and plan §§7.1, 10.4, and 12.1, which invalidate the sweep when HEAD changes. A rebase cannot be repaired by a fingerprint check. Under this pinned plan, remote divergence must stop publication; a revised/re-baselined plan and a new full W8-0 → sweep → audit sequence are required.

### 1.5 The residual-debt placement decision loses its ledger record

- **Lane 1, export 447–457**, and **lane 2, export 1050–1063**, both allocate a ledger entry to the location/vocabulary of the §9/§8/exit-condition adjudication.
- **Plan §9.4** has entries for A1–A6 and provenance, but none for A7 or the residual-debt adjudication vocabulary.

The matrix table remains, but the decision's rationale no longer lands in the ledger as required by the plan's own document-ownership model. Fold that rationale into an existing entry or restore a dedicated entry; no new file or expanded scope is needed.

For avoidance of doubt, the plan **does retain** lane 1's untracked-delta algorithm and README block-removal audit (§10.2–§10.3), and lane 2's mandatory SUP-1 handling, evidence-directory inventory, and six exit conditions (§7.4, §8.4, §11). Those are not omissions.

## 2. Anchor verification, incorrect bindings, and unresolved seams

### 2.1 Numeric anchors and symbols

No requested numeric anchor was off by more than two lines, and no named symbol was missing. Specifically:

- `test_lifecycle.py` defines `ZeroSpawn` at 80, `teardown_two_install` at 162, `CountingSpawn` at 253, `g12_a` at 641, `g12_b` at 683, `g12_c` at 713, `tamper_case` at 793, `g12_f` at 834, and `g12_l` at 957.
- The R09 continuation query and `assert continuation == 0` are at **2158–2161**. Lines **2163–2168** begin the following journal-order check. The plan's `:2158-2161` reference is correct and must not be “corrected” to `:2163-2168`.
- `test_node.py:75-77` is the Node-missing `[SKIP]`/exit-2 branch; `:91-121` contains the two-key start, two-tool batch, same-install pins, and spawn count 3.
- B0 `_compare` is at `test_golden.py:92`, its marker print starts at 177, and the SUP-1 `[pass]` marker is at `test_multi_provides.py:292`.
- `s13/README.md:100`, `:184`, `:187`, and `:209`; `s7/README.md:215-227`; `test_contracts.py:10` and `:42-43`; and `test_wiring.py:790-888` all have the meanings the plan assigns them.
- Design §7.4 (`:952-986`), §8 (`:999-1033`), §9 (`:1034-1059`), C.14 (`:1370-1374`), C.15 (`:1375-1379`), and C.18 (`:1398-1437`) are the correct spans. The other cited design spans, including §5.5–§5.6, §6.3–§6.4, C.10, C.11, C.16, and C.17, also match.
- The cited fixture/host anchors (`fixtures.py:353/409/417/425`, `registry.py:246`, `deepseek.py:355`, `plugins.py:137`, `worker.py:1027`) and the named W7/M5/matrix/ledger/README historical anchors are valid.

The problems below are therefore semantic misbindings, not line-number drift.

### 2.2 Clause 5b cites the wrong process sentinel

**Plan §4.3 clause 5b** binds tamper zero-spawn to `CountingSpawn:253`. The code uses `ZeroSpawn` for the negative probes:

- G12-F/tamper: `test_lifecycle.py:818-829`;
- R11: `:2362-2378`;
- R12: `:2451-2463`.

Each pairs the `line_json.run_process` sentinel with the plugin spawn-log baseline. `CountingSpawn` exists, but it is used for positive process-count evidence elsewhere, not as the cited negative tamper sentinel. Replace `CountingSpawn` in clause 5b with `ZeroSpawn` and the actual assertion spans.

The historical matrix makes the same erroneous `CountingSpawn` claim at `v24-conformance-matrix-2026-10-23.md:873`. Do not rewrite that historical line during W8; instead, ensure the new W8 binding follows the code and records the correction without repeating the error.

### 2.3 Clause 6b must not inherit G12-L/R14 as descriptor-byte evidence

**Plan §4.3 clause 6b** says “同上”, apparently inheriting both `g12_l` and B0 `_compare` from 6a. G12-L loads only provider requests and tool messages (`test_lifecycle.py:958-963`) and compares those domains at `:990-1002`. R14 likewise compares provider requests and tool messages, not descriptors (`:2592-2718`).

Descriptor-byte equality is supplied by B0's live capture and `_compare` (`v24/b0/test_golden.py:92-106`). Make 6b's binding explicitly B0-only; retain G12-L/R14 for 6a/6c. Otherwise W8-1 can mark a nonexistent descriptor assertion `BOUND`.

### 2.4 “B0/S1” is a stale, ambiguous guard reference

**Plan §4.3 clause 7b** says “B0/S1 另有 socket guard”, although the supplementary probe is now named SUP-1 and the plan otherwise uses S1 for stage s1. The directly verified guard is `v24/b0/test_multi_provides.py:279-284`. Rename the reference to SUP-1 and identify any B0 golden guard by its exact file/function rather than the ambiguous “B0”.

### 2.5 Node-path variability is assigned to commands instead of expected output

**Plan §3 Done-when 3** allows rows 27/28/31 to vary their `node=` path while saying that the 32 commands remain byte-identical. Those commands contain no `node=` token; the token occurs in their expected last lines. Plan §7.3 has the correct rule. Correct §3 to say that only `expected-last-lines.txt` for rows 27/28/31 may change, not the commands.

### 2.6 The claim of unanimous A1–A7 lane recommendations is factually wrong

**Plan §5:172** says the two lanes agree completely. The export shows material disagreements:

- A5: lane 1 explicitly inserts before `## Execution` (export 294–299); lane 2 specifies EOF README append at export 1012 and 1245.
- A6: lane 1 calls the supplementary probe non-essential corroboration (export 301–304); lane 2 makes SUP-1/audit failure block W8 at export 710–718 and 777–785.

The plan may adopt its current A5/A6 choices, but it must record the disagreement and the reason for choosing the stricter SUP-1 and insertion-point rules. A later adjudication outside this export would need its own citation; it is not evidenced by these two drafts.

## 3. Content that needs correction or a simpler authority design

### 3.1 SUP-1 is an added W8 release requirement, not a §7.4 requirement

G12-A and the Node gate already prove the v2 Node same-install/two-pin behavior (`test_lifecycle.py:671-677`; `test_node.py:114-121`). SUP-1 adds DB-only v1-descriptor corroboration; it does not fill a missing Node or §7.4 assertion. The plan is right not to make it row 33 or a closeout item, but its mandatory status is an additional W8 policy choice, not something the design or code requires.

Keep that explicit in A6 and clause 3a: SUP-1 may block this conservatively defined W8 publication without being misrepresented as necessary to prove the Node lifecycle. If mandatory status was not intentional, lane 1's corroboration-only treatment is the smaller design and requires no new command or code.

### 3.2 The 17-row register plus 8-row token projection is not the only way to preserve detail

Lane 2's single authoritative 8-row matrix, with every subclause predicate in its evidence/assertion columns (export 740–818), is a simpler design that already preserves all 17 requirements without a second verdict projection. The plan may instead retain its record-authoritative 17-row register, but then the projection audit must be fully specified as in §4.2 below.

The possible simplification is to remove duplicate verdict authority, **not** to remove the precise clause predicates, evidence anchors, limits, or falsifiers.

### 3.3 The fixed count of 26 untracked entries is stale and unnecessary

**Plan §15 risk 2** hard-codes 26 pre-existing untracked entries, while §10.3 correctly requires a fresh `U0` snapshot. Untracked state is not pinned by HEAD; this review's `git status --short` returned nine porcelain entries, including a directory. Use the actual W8-0 `U0` count and paths rather than a historical count.

## 4. Acceptance-machinery self-consistency and missing lifecycle behavior

### 4.1 Blocker: precheck audit 7 requires post-sweep documents that do not exist

Plan §10.4 and §13 run all seven audits at W8-2, before the sweep. At that point the new execution record and matrix/README/ledger W8 sections have not been written. Nevertheless, audit 7 at §10.2 requires:

- four W8 sections containing `11/11`;
- exactly 8 matrix projection rows and 10/3/6 residual-debt rows;
- matrix tokens equal to the record's 17-row register.

These assertions cannot pass at precheck. This problem existed in embryo in both lane drafts, and the new token-equality rule makes it more explicit. Split audit 7 into phase-specific assertions: precheck checks baseline/candidate scope only; final and confirmation additionally check document structure and register/matrix consistency. Define what the common success marker means in each phase without weakening any final check.

### 4.2 The register/projection audit needs a canonical algorithm, not “逐 token 相等”

Plan §§6.1, 6.4, and 10.2 do not define:

- the canonical 17-token order and serialization (spacing, clause IDs, and `PASS-LIMITED` spelling);
- whether the matrix's item verdict is recomputed using the §6.4 worst-clause rule, rather than merely comparing embedded tokens;
- whether `evidence-binding.tsv` starts as a two-state binding file and later acquires verdict/evidence/limit/falsifier columns, or how it differs from the in-record “17 行 clause register”;
- which four of the five candidate documents are the “四个 W8 小节” checked for `11/11`.

Without these rules, two auditors can produce different results, or a wrong item-level verdict can pass while its tokens match. Specify the exact projection and independently recompute each of the eight item verdicts. Also distinguish the external working TSV from the authoritative in-record register.

### 4.3 Result, declaration, fallback, and publication have conflicting temporal rules

Several rules need to be reconciled before execution:

- §6.5 says the declaration is written **only** in the execution record, while §9.5 requires a declaration in README and §17 supplies a formal declaration sentence for the plan Result. State that the record is authoritative and the others are bounded restatements/links, or change the “only”.
- §17 requires all §12.3 conditions before the acceptance sentence may be written, but §12.3 includes staging, commit, push, and the external receipt. The Result must be written before final/confirmation audit and commit. Gate the sentence on the pre-publication acceptance conditions through confirmation; keep commit/push outcomes only in the receipt.
- The automatic evidence-only fallback in §§2.1 and 6.5 is not currently a publishable alternative: §6.4 forbids matrix/ledger/README on failure, §12.3 requires exactly five paths as the publication unit, and audit 7(f) requires a matrix projection. Call it an unpublished STOP outcome unless a separate, fully specified fallback publication path is intended.
- §17 asks Result to retain actual blockers, while rollback §12.2 restores the plan's pre-execution copy. Clarify whether a failed attempt's Result is retained in the evidence directory before rollback, so the fallback record is not silently erased.

The confirmation audit itself does **not** need a self-reference deadlock: the W7 pattern of recording final results in-repo and confirmation results only externally is sound. The actual precheck deadlock is §4.1, and the potential Result cycle comes from treating push/receipt as prerequisites for a document that must precede them.

### 4.4 The no-network/no-real-provider evidence bar is still under-specified

Clause 7b is `PASS-LIMITED`, but §7.4 #7's “不打开网络” is a hard requirement, not something that a platform limitation can waive. The plan needs a per-row construction argument or an equivalent fail-closed guard for every swept entry point, including inherited gates and plugin children. Conversely, 7c cannot rest solely on the absence of `v24.host.smoke --real-provider-smoke`.

No OS-level isolation claim is necessary, and no new runtime/test code should be added. If the static construction evidence cannot cover all 32 commands and SUP-1, the clause is `NOT-DEMONSTRATED` and W8 stops rather than converting the limitation into a pass.

### 4.5 Cancellation and audit testability are unspecified

Neither lane nor the plan says how to classify an interrupted sweep or how to validate the new audit machinery. Add two narrow rules without adding a runner or changing tests:

- SIGINT/SIGTERM/executor cancellation invalidates the attempt, preserves its logs, blocks publication, and requires an environment/process-cleanliness check before a fresh row-1 attempt.
- The external audit recorder should have negative controls in the evidence directory for at least a matrix/register token mismatch and an out-of-candidate untracked-content delta. This checks that the new acceptance audit can actually fail; it does not create a repository test suite or alter frozen files.

## 5. Questions that materially affect design or order

1. **Is evidence-only fallback only an unpublished STOP record, or is it intended as a successful deliverable?** The latter requires a different candidate set and phase-aware audit rules; the former should be stated explicitly.
2. **Which acceptance authority is intended: the plan's 17-row record register plus projection, or lane 2's single detailed 8-row matrix?** This determines the audit algorithm and document-update order. Retaining both requires §4.2.
3. **Is SUP-1 intentionally an independent publication blocker even though it is only corroborative for §7.4?** This resolves the actual A6 disagreement and determines whether an unrelated SUP-1 failure prevents an otherwise complete declaration.
4. **What static evidence is sufficient for the hard no-network requirement across every swept command?** If a per-entry-point construction inventory is not accepted, W8 needs a different evidence mechanism and cannot proceed with the current PASS-LIMITED rationale.
5. **Who owns and retains `/tmp/v24-abi-w8-<UTC>/`, and for how long?** If the item-by-item declaration depends on inspectable logs, receipt, and audit-recorder source after reboot or `/tmp` cleanup, an external durable retention rule is needed; otherwise the record should explicitly state that its in-repo measurements and digests are the retained acceptance evidence.

All corrections above can remain within the existing W8 plan and its five execution candidates. None requires editing the pinned design, changing SQL, promoting or regenerating vectors, adding an M stage, weakening Node absence, adding a runner, or changing closeout from 11/11.
