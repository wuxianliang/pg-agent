# Bounded critique: v24 Tool/Plugin ABI W1 plan

Date: 2026-10-30

## Scope and verdict

This compares `docs/plans/v24-tool-plugin-abi-w1-cross-language-vectors-2026-10-30.md` (`P` below) only with the **Generated Plan** portion of `prompt-exports/oracle-plan-2026-10-30-133718-w1-deep-plan-cross-l-6464.md` (`E`: the partial first lane and two completed lanes, lines 173–1371). Claims material to the critique were checked against the ABI design and selected host/B0 code. The composed prompt and selected-file dump are not evidence for these findings.

The plan preserves the no-production-change boundary, fixed-`expected_hex` discipline, candidate provenance, the corrected malformed-B0-probe interpretation, and the adjudicated Q1/Q5 direction. It is not yet implementation-ready: several required vector families or deterministic rules have no checkable owner, and the execution graph can continue after STOP-R. No finding below requires reopening those Oracle rulings.

## 1. Supported implementation-bearing content missing, weakened, or generalized

### 1. Descriptor v2 has canonical bytes but no complete validator-case inventory

`P:97` specifies canonicalization and three full descriptors, while `P:101` covers JSON Schema. Neither pins the descriptor validator matrix: per-level missing/extra keys, key and description bounds, every limit boundary, concurrency/replay enums, annotation implications, provide/pin/request key equality, renderer identity, and descriptor size/depth rejection. The completed export retains these at `E:578,621,973-989`; the ABI requires them at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:237-267,890-893`.

Consequently, W1 can be green without fixed expectations for the M2 descriptor validator. Schema vectors are not a substitute for descriptor closed-set and cross-field cases.

### 2. Provider projection and manifest vectors lack consistent ownership

Provider v2 projection is promised at `P:49,152`, but no provider-projection domain, case IDs, expected bytes, or negative key-mismatch cases appear in `P:95-102,224-236`. The export's concrete projection seam at `E:357-361` and the ABI projection contract at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:835-839` therefore have no W1 acceptance artifact.

There is also a direct allowlist contradiction: `manifest_adapter_v2.json` is defined at `P:99`, but is absent from the new-file allowlist at `P:224-236`; `descriptor_v2.json` only says “adapter/manifest or linked manifest domain.” The checker cannot derive an exact required file inventory from these alternatives.

### 3. Frame vectors omit operation results, preflight rules, and exact error shapes

`P:98` reduces successful frames to `{ok,v,result}` and known errors to `{ok,v,error}`. It does not carry forward:

- invoke `result={value,meta?}` and prepare/release/inspect `{"prepared":true}` / `{"released":true}` / `{"observed":"known"}`;
- error code regex, 1024-byte message bound, and exit-0/exit-3/frame pairing;
- non-object frames and preflight rejects such as prepare-with-tool, invoke-without-tool, invalid/reserved tool key, and non-object args;
- a fixed parser-reason mapping for these cases.

These are explicit at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:522-562` and were implementation-bearing inventory at `E:374-392,1005-1019`. Generic envelope names do not determine the M2 parser contract.

### 4. The 60,000-byte success-frame target and its boundary cases disappeared

`P:98` retains only the 65,536-byte stdout hard cap; the plan contains no 60,000-byte success-frame target. The ABI makes that target part of plugin pagination at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:730-738`, and the export preserves both the target and its distinction from transport failure at `E:402-404,1088-1091,1138-1142`.

Without fixed 60000/60001/65536/65537 classifications, W1 cannot distinguish a plugin pagination-target violation from a valid frame near the transport cap or from `stdout_limit` unknown. Q2's complete-item rule alone does not specify the serialized-page budget.

### 5. Renderer and tool goldens are reduced to headings rather than determinate expectations

`P:93` requires exact content/meta but supplies neither a closed golden-case list nor the exact read/list/search projection forms, footers, no-hit behavior, and separators retained at `E:336-344,1053-1063`. It also cites ABI §3.2–3.3 as the renderer-rule source; those sections primarily contain descriptors. The actual projection rules are at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:780,805,833`.

The tool table at `P:102` similarly generalizes away required case semantics retained at `E:1158-1177`, including root-relative output and inside/outside absolute paths, selected-window UTF-8 failure, read `truncated_by`, first-match-per-line search, and precise `total`/`scanned_files`/per-rescan skip meanings (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:747-754,772-779,822-832`). “Fixture bytes as hex” also does not define how symlink, special-file, or non-UTF-8-name fixtures are represented. A broad §6 reference cannot let the checker prove that the pinned ID inventory covers these behaviors.

### 6. Schema error determinism is weaker than the baseline

`P:101` asks for stable path/rule expectations but does not define path syntax, first-error traversal, the rule vocabulary, or recursive JSON-distinct enum equality. The export supplied those seams at `E:425-430,1093-1106`; the ABI only partially defines them at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:697-728`.

This is not a request to implement the M2 validator in W1. It is a missing fixed contract without which different validators can produce different accepted expectations for the same schema/instance corpus.

## 2. Underspecified seams, contradictions, dependencies, and references

### 7. Non-PG compact JSON and the cross-language matrix are not deterministic

The plan names “compact sorted JSON” but never fully defines the accepted number grammar, duplicate-key handling, Unicode/escape rules, and key ordering for frames, manifests, renderer digests, and result budgets. `P:117` further shortens Q3 to “compact UTF-8,” while the baseline consistently used compact-sorted bytes (`E:574-576,1078-1091`). Existing helpers do not fill the gap: `v24/host/journal.py:64-69` is Python `sort_keys=True` with no safe-integer/float rejection, and `v24/host/registry.py:131-134` explicitly accepts integers of any size and floats.

`P:97` puts strict lexical rejection mainly on the Node PG canonicalizer; no equivalent Python input boundary or separate PG-observation-versus-ABI-rejection semantics is specified. Finally, `P:127` says Python and Node must verify several transforms “如决定为跨语言同 bytes,” leaving the actual domain-by-domain Node obligation undecided despite the fixed-byte ruling. Fixed expected files cannot by themselves make two unspecified serializers or budget calculators agree.

### 8. Renderer digest ordering and work-item dependencies are internally inconsistent

The formula at `P:91` hashes `cases`, but W1 never fixes the golden-case object shape or array ordering. Sorting object keys does not canonicalize array order, so the same cases in another order yield another renderer and descriptor digest. The export made ordering and the renderer-before-descriptor dependency explicit at `E:324-344`.

The execution index reverses that dependency: W1-3 freezes descriptors at `P:151`, while W1-5 only later freezes renderer cases/digests at `P:153`, even though `P:91` says descriptors embed those values. Capture/checker construction is later still at W1-6 (`P:154`), after earlier items already require captured fixed expectations. No dependency edge resolves this cycle.

### 9. STOP-R is simultaneously terminal and a successful work-item outcome

The ruling at `P:110` and risk table at `P:255` prohibit Q5-dependent vector promotion and W1 closure while STOP-R is active. Yet W1-5's Done condition is “Q5有算法或STOP” (`P:153`), after which W1-6 through W1-9 capture, gate, audit, and publish (`P:154-157`). This conflicts with `P:15` and provides no mandatory blocked/not-run branch.

The plan must distinguish “STOP-R recorded” from “milestone done,” and state whether any non-Q5 assets may be promoted while closure remains blocked. As written, an active STOP-R can satisfy a work item and flow into publication.

### 10. The W1 checker has no specified PostgreSQL fixture or PG/Node sequencing

The first W1 byte gates run at `P:178-182`, before the loader and database setup at `P:198-200`, but no W1 asset owns `server_helper_scope`/`setup_db`, a fixture database, or installation of `v24.canonical_json`. The existing B0 script performs that setup explicitly at `v24/b0/test_golden.py:153-168`; its PG producer rolls back at `v24/b0/golden_cases.py:45-51`.

The plan also does not say to close or roll back PG before spawning Node. B0 closes its descriptor connection before later producers at `v24/b0/golden_cases.py:256-269`, and the completed export made this phasing explicit at `E:1213`. The listed W1 command is therefore not reproducible from the plan alone and does not yet demonstrate the repository's no-external-IO-in-a-DB-transaction invariant.

## 3. Important lifecycle/testability gaps present in both plan and export

### 11. Green vectors are not bound to the synchronized design revision

Both versions check vector self-consistency, cross-file references, inventories, and eventual manual document agreement, but neither defines durable conformance evidence from each contract family to the reviewed ABI design revision/sections. `P:163` records the input design SHA at isolation, while `P:169` checks only vector-internal consistency. A later Q amendment, renderer-template edit, or tool-contract edit can therefore leave every automated check green while vectors no longer represent the design.

This is central to W1's synchronization purpose. A reviewed design-to-case mapping or equivalent explicit conformance gate is missing; provenance alone does not detect drift.

### 12. The prescribed capture commands cannot be rerun after a normal first attempt

`P:87,167` requires each destination to be absent, but `P:190-192` hard-codes `/tmp/v24-w1-a` and `/tmp/v24-w1-b`. After a successful capture—or a failure after directory publication—those paths exist, and the inherited guard must refuse them (`v24/b0/capture_golden.py:34-35`). The export repeats the same fixed-path pattern at `E:1227-1233` and likewise gives no retry lifecycle.

Neither version says how to select fresh evidence-preserving destinations for STOP-N/STOP-V retries or a later final-candidate rerun. The listed commands thus work only once unless an undocumented out-of-repo cleanup or path change occurs.

## 4. Materially design-changing questions still requiring an explicit answer

1. **What does `max_meta_bytes=0` mean?** The ABI currently permits it (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:250-254`), while Q4 charges absent meta as `{}` = two bytes. `P:117` says to reconcile this but does not ratify the export's proposed minimum of two or define special zero semantics (`E:409-415,603-611`). This changes descriptor validity and bytes, so W1-1 cannot be considered closed without an answer.

2. **Are non-canonical response whitespace and CRLF accepted?** The partial first lane requires rejection (`E:384-392,425-428`); the completed third lane accepts non-canonical key order, surrounding whitespace, and CRLF (`E:1014-1016`). `P:112` resolves request byte equality and response key order only. The ABI's “one JSON frame plus one LF” wording at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:554-562` does not unambiguously settle surrounding whitespace. This changes the response acceptance corpus and must be resolved by evidence/design review, not inferred from either lane.

## Boundary of this critique

No material out-of-scope production implementation was found in the target plan, and the inherited gate/provenance requirements are supported by the baseline; this critique does not propose removing them. It also does not reconsider the adopted strict Q1 budget-exhaustion behavior or Q5 STOP-R. The immediate need is to make the preserved contracts checkable and the stop/dependency lifecycle executable, not to add runtime scope.
