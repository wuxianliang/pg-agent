# Investigation: 为什么 v13 runtime 持续开发却不能完成

## Summary

v13 不能收敛的首要原因不是“还差几个函数”，而是没有把“完整 runtime 完成”定义成一个可执行、可组合的产品级验收谓词。项目持续接受 stage-local green + 明确 non-claim；同时把原推进/监督入口和需要发生角色反转的集成接缝冻结。因此局部能力可以不断增加，但没有逻辑路径把它们升级为完整 runtime。

## Symptoms

- 多份 v13 计划明确写出目标，但同时标注“未实现/未跑 gate/不得宣布产品可用”。
- controller thin cut 已完成并推送，但计划明确它不证明 provider 交付、无人值守、D-3 或多入口共存。
- v13 同时存在 roadmap Phase A/B/C、long-loop Phase A/B/C/D、native wait/poll/steer、unattended authorization 以及 stage 40–44 等不同范围。
- 多个阶段要求“不改旧 stage/不建第二份 advance/不建第二状态源”，导致后续能力只能在既有窄接缝中接线。

## Background / Prior Research

### Git archaeology: `6662002B-20AB-4D20-B25E-6E8F6F36FAB2`

- v13 never had one end-state gate. It accumulated per-stage contracts and per-stage green gates that were explicitly prohibited from composing with later stages.
- Key trail: `3a1be85` (2026-09-28 roadmap acceptance), `e7a3ca6` / `2206874` / `4fa59dc` / `b7b5f88` (long-loop Phase 0/A/B/C/D planning), `fb295ac` / `05a1687` / `78e77c7` (driver/supervisor/fair-claim ownership and freezes), stages 40–44 on 2026-10-08/09, and `c5a495d` (controller thin cut on 2026-10-10).
- Several later contracts narrowed the connection: native wait/poll/steer was rejected by thin cut; stage 42 bans the four agentctl verbs; D-3 remains producer-only; driver byte freezes preserve old ownership.
- On the same day as thin cut completion, v23 was started with one durable table, one `Control.execute` entry and one gate, explicitly not inheriting v13/v15 runtime structures. This is evidence of non-convergence, not proof that v13 code is useless.

### Phase/dependency audit: `9A623019-6118-456A-9AB6-8B3D5452F3AD`

- Two incompatible Phase A/B/C/D taxonomies coexist: roadmap stages 21–29 and long-loop stages 30+, making phase references ambiguous.
- The dependency spine is compositional on paper: roadmap 21–29 → long-loop A 30–35 → B 36 → C 37–38 → D 39. But the live tree continued to stages 40–44 outside that spine without adding a product-level composition gate.
- Phase 0 is documentation/technical adjudication only; it says A–D were unreviewed and must not start. Later accepted sub-plans, matrices and live stages shipped anyway, leaving stale status/provenance contradictions.
- Repeated stop/ASK_USER gates remain around product DB/roles and stannum grants, route policy binding and first-parse override, canonical/reuse algorithms, stopped-root failed-snap lock rechecks, recover/children-terminal behavior, B1 closed sets, PC-4 and multi-goal claim behavior.
- The single `v13_advance` replacement rule is contradictory across documents: Phase A owns it, later phases forbid a second replacement, while R0 explicitly edits the existing copy. This is only reconciled by later authorization and freeze exceptions.

### Gate boundary audit: `38BB355D-7ABA-43CE-9083-4154375DB678`

- Thin cut proves one mocked/superuser/temporary-DB vertical chain: envelope → parse → one advance → SQL steer → observe → six-word pure disposition.
- It intentionally does not prove provider delivery, product-role ACLs, concurrency or multi-entry quiescence, unattended operation, native wait/poll/steer host behavior, D-3 body consumption, or stage 45.
- The matrices and README encode these as explicit gaps, not accidental omissions. Repeated local green gates therefore cannot logically upgrade into product-runtime proof.

## Investigator Findings

### 1. v13 has no single executable completion state

Evidence:

- `v13/load.py:3-7,55-61,103-109` defines cumulative append-only stage loading, not a product acceptance runner.
- Stage gates are independently run and manually composed; there is no one command requiring the complete host/provider/control/role/concurrency story.
- Matrix #91 is green while its gap column still excludes provider delivery, unattended operation, multi-entry coexistence, native wait/poll/steer host behavior and D-3 body consumption (`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md:140-142`).
- The loop-driver README repeats that the thin cut proves only envelope → SQL → durable event → observe and does not prove product roles, provider delivery, unattended or multi-entry (`v13/loop_driver/README.md:80-106`).

Therefore:

```text
stage green ≠ composition green ≠ product ready ≠ complete v13 runtime
```

### 2. The phase model is ambiguous but not literally cyclic

The roadmap uses Phase A/B/C for stages 21–29; the long-loop plan uses Phase A/B/C/D for stages 30–39. Stage 40–44 then continue beyond both original spines. This is a provenance and authorization problem, not a proof of a dependency cycle.

- Roadmap: `docs/plans/v13-layered-control-roadmap-2026-09-26.md:185-233`.
- Long-loop scope and status: `docs/plans/v13-long-loop-plan-2026-09-28.md:1-3,267-287`.
- Live tail: `v13/load.py:55-61,103-109`.

A reader can truthfully say “Phase B is complete” and “Phase B is not implemented” when referring to different taxonomies. That prevents a stable definition of what the next completion gate is.

### 3. Producer/consumer edges were intentionally separated

Stage 41 is explicitly producer-only: `steer/injected.payload.text` has no consumer and `CONSUMER` remains unset (`v13/agentctl_verbs/README.md:1-5`; `v13/agentctl_verbs/test_agentctl_verbs.py:1555-1576`). Stage 42 is green partly because it deliberately does not call the four agentctl verbs; its AST gate bans `run_turn`, `decide_exit`, `GoalSupervisor` and all four `v13_agentctl_*` names (`v13/goal_workflow/test_goal_workflow.py:76-107,523-558`; `docs/plans/v13-stage42-goal-workflow-2026-10-08.md:5-9,25-28`).

The later D-3 ruling solved a process deadlock by removing consumer closure as a prerequisite; it did not create a consumer. Thus the project could commit a producer and an independent scene without ever closing the producer → consumer edge.

### 4. Freeze rules protect safety but also freeze the role-reversal seam

Necessary safety constraints include:

- one durable state owner;
- one `v13_advance` owner;
- external IO outside DB transactions;
- row locks, fence/lease, complete and settlement;
- append-only SQL loading.

The additional integration constraints are stronger:

- `r1_driver_restore()` restores `driver.py` to the `fb295ac` bytes after stripping the sentinel (`v13/plan_arm/test_plan_arm.py:275-348`);
- sentinel-outside `run_turn` changes are rejected;
- stage 42 bans the new agentctl calls and old decision/exit machine;
- source/AST allowlists accept only predeclared paths and changes.

The original minimal-form design wanted `actl_driver_demoted` — the controller-side Python surface reduced to claim / external IO / complete — but the later plan deferred it and replaced it with `actl_driver_untouched` plus a scene-level no-call test (`docs/designs/v13-agent-control-minimal-form-2026-10-02.md:308-345`; `docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:298-302`).

This converts the needed vertical rewire into a contract exception. It is not a PostgreSQL impossibility; it is a current-plan impossibility while all prohibitions remain active.

### 5. Local test scope is intentionally narrower than product scope

Thin cut is deliberately:

- temporary database;
- stage 41 load;
- superuser connection;
- mock judgment;
- one tree and one entry path;
- no real provider;
- no concurrent promoters.

The plan explicitly says the gate does not prove product roles, provider delivery, multiple-entry coexistence, unattended, native wait/poll/steer host behavior or D-3 (`docs/plans/v13-controller-thin-cut-2026-10-09.md:248,333,342,405-426,459`). This is an honest local contract, but there is no mandatory later composition gate that consumes its output and closes those gaps.

Earlier v13 gates do contain ACL and concurrency evidence. That is counterevidence against “nothing was rigorous”; it is not composition evidence. The problem is not lack of tests in general, but lack of one test whose pass condition spans the ownership and delivery boundaries.

### 6. Process rewards bounded non-claims

The repository accepts “green plus explicit non-claim” as a valid milestone shape:

- stage 41 green while D-3 remains open;
- stage 44 green while CE map remains static and not a CE runtime;
- thin cut green while provider and unattended remain unproven.

This process is valuable for honesty but insufficient for convergence. It permits new local evidence without requiring the next consumer or host edge to be delivered. `AGENTS.md` enforces one milestone/one commit and artifact updates, but does not require a product-level closure gate (`AGENTS.md:13-35,51-68`).

The v23 M1 implementation is a counterexample: one durable table, one `Control.execute` entry, one host/disposition boundary and one gate. It demonstrates a different acceptance architecture, not that v13's individual SQL work has no value.

## Investigation Log

### Phase 1 - Initial assessment

**Hypotheses:**

1. “完成”不是单一目标，而是多个层级（L0/L1/L2、Phase A-D、provider/无人值守/多入口）叠加，导致局部完成无法成为全局完成。
2. 计划的硬性冻结条件和“不能新增第二推进者/第二状态源/第二 advance”使新增能力依赖旧实现的未冻结接缝。
3. gate 主要证明本地、Fake、超级用户、单库、单入口场景，无法自动升级为产品运行时证明。
4. 计划之间存在被拒合同、后置授权和依赖未闭合，造成路线持续重排。

### Phase 1.5 - External / Git fact gathering

The three read-only explores established the git trail, phase dependency ambiguity, and gate proof boundary. Their findings were appended above. No web lookup was needed; the relevant evidence is local repository history and documents.

### Phase 2 - Context gathering

The context builder timed out after five minutes but left a broad selection containing the primary roadmap, long-loop plans, thin-cut/native/unattended plans, structure-drift investigation, review matrices/ledger, AGENTS.md and relevant v13 gate files. A narrower retry was rejected because the tab was already context-builder controlled. The selection was used for the main pair and Oracle synthesis.

### Phase 3/4 - Pair and Oracle

The pair investigator appended the structured findings above. Oracle synthesis was attempted but timed out; its recovered chat tail confirmed the same model: no executable completion state, explicit non-claims, role-reversal freeze, and v23 as the counterexample. Final conclusions below rely on the pair findings plus direct spot-checks of the cited files.

## Root Cause

The primary root cause is **missing product-level closure semantics**: v13 has many stage-local acceptance predicates but no single executable predicate that composes them into “complete runtime.” The second necessary root cause is **freezing the integration seam while accepting non-consumption as a valid milestone boundary**. The old driver/supervisor retain progression ownership, stage 41 provides a producer, stage 42 deliberately avoids consuming it, and the byte/AST rules make the role reversal require a new exception rather than normal implementation.

The phase naming/status contradictions amplify the problem but are not a literal dependency cycle. Provider delivery, D-3 body consumption, unattended operation, native host behavior, PC-4 and multi-goal soak are real downstream work, but they are symptoms of the missing composition contract rather than the primary explanation for the project repeatedly reopening plans.

## Recommendations

1. **Freeze feature growth and define one v13 composition gate first.** Make one command and one matrix row the only route to “technical v13 runtime complete.” It must name the supported tier: one lifecycle entry, one existing advance path, agentctl producer plus consumer, disposition, product-role ACL, entry-point quiescence, and an explicitly scoped provider boundary. If real provider is separately authorized, make it a second named tier rather than an implicit future.
2. **Split the phase namespaces.** Rename roadmap phases as `L1-21..29` / `L2-26..29` and long-loop phases as `LL-A..D-30..39`; add a status table showing planned, implemented, locally gated, composition-gated and product-gated. Retire or supersede stale “A–D unreviewed” language in a dated authority note.
3. **Authorize one controlled role-reversal milestone.** Preserve one durable state owner, one `v13_advance`, transaction boundaries and no second runtime. Explicitly exempt only the controller/consumer seam from the byte-freeze and negative AST rules for that milestone. Positively test the call edge; stop using “old file untouched” as the proxy for architectural progress.
4. **Classify gates into three tiers.** Local safety gate, composition gate, product gate. A local green row with a non-claim must not count toward product completion until its output is consumed by the next layer.
5. **Make stage dependencies executable.** Every producer stage must name its consumer stage and a composition test. A producer-only stage may close as a local artifact, but the roadmap must keep the overall milestone open. Do not add stages 45+ until the prior composition gate is green.
6. **Bound ASK_USER.** Each stop must identify owner, exact contradictory contract, required decision and evidence needed after authorization. Once authorized, record the exception in the single closure plan instead of creating another parallel taxonomy.

## Preventive Measures

- Add a repository-level `v13/accept_runtime.py` or equivalent composition runner; it should fail if any declared provider/consumer edge, role, or entry-point condition is omitted.
- Require every matrix row to have `scope`, `consumer`, `non_claims`, `next unblock evidence`, and `counts_toward_product_completion` fields.
- Add a machine-readable phase manifest with unique IDs; prohibit duplicate Phase A/B/C/D names across plan families without namespace prefixes.
- Keep explicit negative claims, but make them state transitions in a readiness ledger rather than allowing “green” to look like end-state progress.
- Track ownership of each advance/serve/settle/consumer path in one table and gate changes to that ownership directly.
- Treat v23’s one-entry/one-gate shape as a design reference for future bounded runtime slices, without claiming it solved v13's broader scope.

## Final Synthesis

The answer to “why can’t it finish if the goal is documented?” is:

> **Documentation specifies desired behavior, but completion requires a single executable composition contract. v13 had many local contracts and increasingly strict preservation rules, but no composition contract.**

That created a stable failure mode:

```text
new local stage
  → local green gate
  → explicit non-claim
  → next local stage
  → no mandatory consumer/composition gate
```

The result is not random drift. It is a predictable outcome of the acceptance architecture. The most important correction is therefore not to write more stage plans. It is to first decide and encode the one bounded runtime slice that counts as complete, explicitly authorize the required seam rewire, and require one vertical gate to consume all prior outputs. Until that exists, continued stage development can be correct locally while remaining incapable of producing a finished v13 runtime.
