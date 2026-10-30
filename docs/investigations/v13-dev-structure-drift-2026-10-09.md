# Investigation: v13 开发结构偏差（agent_run 原语 × loopx 长运行）

> 日期：2026-10-09。调查，不是裁决，不改 SQL、不 commit。
> 问题：v13 是不是在开发结构上偏了？用户要的形状是——在 agent loop 上先造出 RepoPrompt-CE `agent_run` 一类控制原语，再把这组原语交给 loopx 一类长时间运行的控制方案。有参考项目，开发本应极简、单刀直入。反复修改扩展都不能如愿，原因是什么？

## Summary

偏了，而且不是「还没做完」。用户要的两层——loop 上的 `agent_run` 式控制原语，再交给 loopx 式纯 disposition 长运行——在参考项目里各是一个入口。v13 把这两个入口拆成 stage 40–44 的并排合同，再用 `driver.py` 字节冻结和负向 AST 测试禁止它们互相调用。反复扩展不如愿，是因为验收从「证明驱动器被降级、原语被调用」改成了「证明旧驱动器没被碰、新场景不调用新原语」。字面禁令（不建 `v13_agent_run`、不建第二 `advance`）被遵守了，不是阻断。

## Symptoms

- 用户要的是两层薄切：loop 上的 `agent_run` 式控制原语（start/poll/wait/steer/respond/cancel），上面再坐一个 loopx 式长运行控制器。参考项目在工作区里，按理不应再长出第二套引擎。
- 2026-10-02 设计稿 `docs/designs/v13-agent-control-minimal-form-2026-10-02.md` 已判定：动词层做完了较难的一面，卡住的是「从未被 gate 要求过的角色反转」；极简形态 = 一个工具族 + 一个 controller 会话 + 一个 gate；明文不做 `v13_agent_run` 总调度、不搬 LoopX 26 表、不建第二推进函数。
- 同日另一份调查 `docs/investigations/v13-phase-d-reopen-reference-survey-2026-10-02.md` §8 把 v13 改定位为 pi 替代，并提出「乙起步（LoopX 治理权威，v13=执行器）/ 甲收敛（v13 唯一权威）」双模式。与「PG 是唯一控制语义 owner」并存。
- 2026-09-28 `docs/investigations/v13-long-loop-workflow-borrowing-gap-2026-09-28.md` 已写明正确形状：不建引擎；长循环 = host 触发 + disposition 纯函数；工作流 = 提示词模板 + 已有动词。随后施工仍按 stage 追加。
- 2026-10-02 盘点时 `SQL_LOAD_ORDER` 到 39。本日 `v13/load.py` 已到 **44**：40 `agentctl`、41 `agentctl_verbs`、42 `goal_workflow`、43 `external_exec`、44 `ce_map`。极简切片之后又追加了四段，而不是停在「工具族 + 一个 gate」。
- 2026-10-08 `docs/investigations/v13-stage41-d3-stage42-deadlock-2026-10-08.md`：未跟踪计划把「steer 正文必须已被既有消费者读过」和「42 不得调用四个 agentctl 动词、且必须等 41 全绿进 main」拼成死锁。生产者在等一个谁都不许写的读者。
- v13 顶层目录远超两层切面：`agentctl` / `agentctl_verbs` / `control` / `loop` / `loop_driver` / `goal_supervise` / `goal_supervisor` / `goal_workflow` / `fair_claim` / `fair_driver` / `should_run` / `quota_window` / `attention` / `govern` / `frontier_gap` / `workflow_bind` / `external_exec` / `ce_map` / `pi_parity` / `pi_ports` 并存。
- 驱动器仍是 Python 进程（LoopDriver、GoalSupervisor、fair_driver、RealChain），不是「一个 agent turn 把控制动词当工具调」。这是 10-02 设计稿 §0 的原症状，目录扩张之后是否仍在，待核。

## Background / Prior Research

### 已有文书（本调查不重跑）

- 极简形态裁决（2026-10-02）：数据面已统一（sessions/events/effects + 动词层）；角色面统一公式 = turn 边界持有者 + 四动词。v13 把边界放在 `v13_advance`。缺的不是引擎，是工具面接线。长跑驻留「不建新调度」。见 `docs/designs/v13-agent-control-minimal-form-2026-10-02.md` §2 裁决一至三、§6 不做清单。
- 长循环借鉴（2026-09-28）：LoopX 无工作流引擎、无常驻进程，`loop_controller.py` 是纯函数；RP-CE 无 DAG，编排是提示词，工具面就是 `agent_run`。v13 缺的是计划/前沿/disposition/心跳，不是再搬一张表。见 `docs/investigations/v13-long-loop-workflow-borrowing-gap-2026-09-28.md` §0–§1。
- 定位修正（2026-10-02）：pi 只是宿主；v13 已占据 turn 引擎槽位，缺的是「被驾驶模式」。见 `docs/investigations/v13-phase-d-reopen-reference-survey-2026-10-02.md` §8。
- stage 41/42 死锁（2026-10-08）：已提交 D-3 只要求 gate 覆盖正文消费；未跟踪父计划把它加强成「必须引用冻结树里已有消费者」，同时禁止 42 成为那个消费者。见 `docs/investigations/v13-stage41-d3-stage42-deadlock-2026-10-08.md`。

### Git / 参考项目事实

主会话用 `git log` / `git show` 抽查了 explore 回报。HEAD 与 10-08/10-09 五笔提交属实；explore 把 stage 17 的 `8b7c2a5` 记成 2026-09-20，实为 **2026-09-26**（`git show` 主题仍是 `v13: add control-plane stage 17`）。下面只保留抽查过的事实。

**HEAD** `ae70340`（2026-10-09 14:11）`v13: map ce control primitives`。`v13/` 工作区干净。10-02 极简稿之后实际落地的 v13 提交：

| 日期 | hash | 主题 | stage | 相对用户两层切面 |
|---|---|---|---|---|
| 10-05 | `961dfe0` | record stage40 agentctl and D-A oracle rulings | 文书 | 把极简切片写成裁决，尚未写运行时 |
| 10-06 | `998901f` | allow phase-d paths in the v13 source freeze | 冻结放宽 | 为后续目录开闸，不是原语 |
| 10-06 | `b304695` | add authorized fake unattended acceptance | 验收夹具 | 假的无人值守，不是 loopx 控制器 |
| 10-08 | `a19aefc` | add agentctl observe tool | 40 | 只读工具行，最接近「原语」的第一刀 |
| 10-08 | `95af56b` | add agentctl steer answer cancel | 41 | 写动词。仍是 SQL 工具，不是 `agent_run` 会话机 |
| 10-09 | `5f65d7a` | accept one fake goal workflow | 42 | 长运行形状的有界 Fake；**明文不调用四个 agentctl 动词** |
| 10-09 | `c16e928` | add external executor ingress check | 43 | 入口分类，不是执行器运行时 |
| 10-09 | `ae70340` | map ce control primitives | 44 | 静态 jsonb 对照表，调用它不执行签名 |

更早、且后来被冻结的控制层（抽查 log，未逐文件重读）：`05a1687` goal_supervisor tick（10-01）、`78e77c7` fair claim driver（10-01）。它们在 agentctl 之前就占了「谁驱动循环」的位置。

**字面禁令被遵守，语义边界被绕开**（explore `BA6ED0D2`，主会话抽查了后半）：

- `git log -S v13_agent_run -- v13` 无提交。没有第二份 `v13_advance`。没有 LoopX 26 表、没有 v15 桥、没有新的 `effects.kind`。
- 绕开发生在改名后的 stage：`goal_workflow` 在 `LoopDriver` 上编排多步 advance / spawn / settlement；`external_exec` 与 `ce_map` 把推迟的控制面收成更窄的声明。

**已亲自读过的刀口（不是 explore 转述）：**

- `v13/goal_workflow/README.md:51`：`actl_driver_demoted` 延期。不调用 `v13_agentctl_observe/steer/answer/cancel`。唯一推进者是一个 `LoopDriver`（`:3`、`:42`）。退出码 0 只表示「单 goal、Fake、上界 4」。
- `v13/ce_map/README.md:3-5`、`:32-48`：`v13_ce_map()` 返回静态 jsonb。CE 原语被指到既有签名（`observe_poll` → `v13_agentctl_observe`，`startOrResume` → `v13_enqueue_effect`，`steerUserTurn` → `v13_agentctl_steer`，`respondToPermissionRequest` → 六参 `v13_complete`，`shutdown` → 字符串 `unsupported`）。函数不执行这些签名，不是 CE 会话运行时。`not_claimed` 含 worktree_bind / merge / auto_wake / oracle_lanes。
- `v13/agentctl/README.md:3`：stage 40 只登记一个只读工具。写动词在 41。这是 tools 行，不是 `agent_run` 的 start/poll/wait/steer/respond 状态机。

**由此已经能排除的解释：** 「还没开始做原语」不成立——40/41 已提交。「参考项目没被看」不成立——44 把 RP-CE 文件行号写进了 SQL 字符串。「禁令没人理」不成立——禁令被字面遵守，所以用户要的 `agent_run` 形状不能用那个名字落地，长运行层又被写成不得调用刚落地的动词。

## Investigator Findings

（pair 填写。主会话不在此段下笔，避免覆盖。）

### Scope and evidence discipline

Investigator read-only review at the parent-verified HEAD `ae70340` on **2026-10-09**. The stage-44 load tail, static `ce_map`, lack of `v13_agent_run`/second advance, and stage-42 README boundaries are carried forward as established parent facts, not re-litigated. Narrow explore probes were dispatched for CE lifecycle, LoopX purity, and stage-42 history; substantive reports and load-bearing claims were checked against local source and Git. The stage-42 probe's claim of an unresolved procedural stop is **not adopted without qualification**: the current untracked parent plan explicitly contains Ruling A. Git cannot establish when an untracked draft was edited or whether a separate user authorization occurred. No gates were run in this investigation; existing check counts remain historical reports, not new validation claims. All changes in this turn are confined to this findings section.

Reference path shorthand below: CE `AgentRunMCPToolService.swift` means `repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift`; LoopX `loop_controller.py` / `turn_contract_generated.py` mean `loopx/loopx/control_plane/turn_driver/`; `turn-loop-controller-v0.md` means `loopx/docs/reference/protocols/turn-loop-controller-v0.md`. Local references are current checkout evidence, not claims that these exact reference revisions were consulted by the historical implementer.

### Verdict table

| Question | Verdict | File:line evidence |
|---|---|---|
| Is the drift merely unfinished? | **No. It is structurally welded side-by-side, with unfinished residuals on top.** The decisive defect is that v13 kept an existing Python push loop and supervisory writer, then added agentctl, a fake workflow, ingress classification, and a static CE map beside it; it never made the agent loop own the lifecycle surface. | `v13/loop_driver/driver.py:173-177,315-318,387-397,423-464`; `v13/goal_supervisor/driver.py:174-218,232-268`; `v13/goal_workflow/README.md:3,42-51`; `v13/load.py:55-61` |
| What is the two-layer reference cut? | **One lifecycle tool service, then one pure disposition/controller boundary.** RP-CE has one `execute(args)` dispatching `start/poll/wait/cancel/steer/respond`; LoopX has `decide_loop_disposition(...)` returning a typed disposition without effects. | RP-CE `AgentRunMCPToolService.swift:412-438`; `:440-453`; `:1009-1047`; `:1174-1215`; `:1218-1310`; `:1505-1538`. LoopX `loop_controller.py:1-17,639-670`; `turn_contract_generated.py:31-39`; `turn-loop-controller-v0.md:3-17,176-217` |
| Did v13 implement that lifecycle surface? | **No.** Stage 40/41 produced SQL handlers and catalog rows, not an `agent_run` session operation boundary. `ce_map` is a static mapping function; it does not execute mapped signatures. | `v13/agentctl_verbs/v13_agentctl_verbs.sql:61-64,139-142,263-266,343-378`; `v13/ce_map/v13_ce_map.sql:5-18`; `v13/ce_map/README.md:3-5,32-48` |
| Can an agent turn select the three verbs? | **Yes, through the existing production SQL route, but not as a Python driver call.** The verbs are registered as `kind='sql'` tools; `v13_plan_arm` dynamically executes the selected handler, and the stage-41 test drives that route through `v13_advance`. There is no direct call from `LoopDriver` or `GoalSupervisor`. | `v13/agentctl_verbs/v13_agentctl_verbs.sql:331-378`; `v13/plan_arm/v13_plan_arm.sql:779-789`; `v13/agentctl_verbs/test_agentctl_verbs.py:1186-1201,1315-1335`; no verb references in `v13/loop_driver/driver.py` or `v13/goal_supervisor/driver.py` outside their unrelated control surface |
| Is `goal_workflow` refusing agentctl a local scheduling choice? | **No. It is a structural consequence of the stage contract.** The plan explicitly says not to call all four agentctl verbs, not to call `GoalSupervisor.tick`, `run_turn`, `decide`, or `decide_exit`, and not to modify the driver’s allowed SQL set. The test then makes those names AST-banned. | `docs/plans/v13-stage42-goal-workflow-2026-10-08.md:5-9,25-28`; `v13/goal_workflow/README.md:49-53`; `v13/goal_workflow/test_goal_workflow.py:76-107,523-558,671-687` |
| What happened to D-3 at stage 42? | **The requirement remained open; milestone acceptance was narrowed to producer delivery.** The current drafts explicitly adopted Ruling A, while the committed stage-41 test asserts residual openness and stage 42 forbids becoming the consumer. Git proves the split acceptance, not an unauthorized bypass of an unchanged stop. | `docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:15,411-413,647`; `docs/plans/v13-stage41-agentctl-verbs-2026-10-08.md:9-24`; `docs/plans/v13-stage42-goal-workflow-2026-10-08.md:5-9,25-27`; `docs/investigations/v13-stage41-d3-stage42-deadlock-2026-10-08.md:1-15,125-140`; `git show 5f65d7a` message `v13: accept one fake goal workflow`, 8 files |
| Which complexity is PostgreSQL-necessary? | **Transactions, row locks, SECURITY DEFINER, fixed `search_path`, ACLs, authorization, claim/fence/complete, and keeping provider/tool IO outside the transaction are real.** They explain SQL wrappers and settlement plumbing, not the need for disconnected driver entry paths or a static CE map. | `v13/agentctl_verbs/v13_agentctl_verbs.sql:61-118,139-260,263-325`; `v13/loop_driver/driver.py:315-385`; `v13/goal_supervisor/driver.py:68-104,174-268` |
| Which complexity is reference-as-checklist process? | **The stage/load/documentation machinery and non-rewiring freeze are process artifacts.** `SQL_LOAD_ORDER` must only grow at the end; each stage has its own setup/test/README/review tail; `AGENTS.md` requires one stage per commit and immediate push. This makes a vertical adapter cut awkward unless the plan explicitly authorizes a cross-layer change. | `AGENTS.md:13-20,29-35,51-68`; `v13/load.py:3-7,55-61`; `docs/plans/v13-stage42-goal-workflow-2026-10-08.md:21-28,717-748` |

### File:line evidence and interpretation

#### 1. RP-CE is one operation surface, not a second orchestration engine

`AgentRunMCPToolService.execute` normalizes one `op` string and switches over exactly `start`, `poll`, `wait`, `cancel`, `steer`, and `respond`; `poll` is deliberately implemented as `executeWait(..., forcePoll: true)` rather than as another engine (`AgentRunMCPToolService.swift:412-438`). `start` rejects an existing `session_id` because it creates a new session (`:440-453`). `wait`/`poll` resolve the target session and return a snapshot or wait for an interesting state (`:1009-1047`); `cancel` checks expiry/terminal/active state, then cancels the run (`:1174-1215`); `steer` dispatches an instruction into an active run or starts a follow-up epoch (`:1218-1310`); `respond` resolves a pending interaction and returns the updated snapshot (`:1505-1538`). The important shape is one lifecycle dispatcher whose orchestration remains the model’s prompt/tool interaction, not a separate database engine.

#### 2. LoopX supplies the thin long-running layer

The LoopX module states that it computes the next disposition from one validated receipt and one fresh quota/scheduler decision, and “never invokes a model, sleeps, mutates a host scheduler, writes state, or spends quota” (`loopx/control_plane/turn_driver/loop_controller.py:1-17`). `decide_loop_disposition` constructs validated inputs, walks the ordered contract, and returns the first matching disposition; invalid/stale inputs raise rather than becoming a disposition (`:639-670`). The enum is exactly eight outputs—`run_now`, `capability_action_required`, `wait`, `stop`, `user_action_required`, `repair`, `replan`, `terminal`—in the generated contract (`turn_contract_generated.py:31-39`). The protocol repeats that the controller is an exported transition API, not an implicit loop, and its managed-step consumer returns without executing anything (`turn-loop-controller-v0.md:3-17`).

#### 3. v13 already had the pusher before agentctl existed

`LoopDriver.advance` directly calls `v13_advance` and commits it (`v13/loop_driver/driver.py:173-177`). `serve` performs provider/tool IO, then claims and completes the effect and calls `_settlement_advance` in the same committed transaction (`:315-385`); `_settlement_advance` itself calls `v13_advance` (`:387-397`). `decide_exit` itself is a pure local precedence function over already supplied values (`:95-112`), but `LoopDriver.decide` populates those values through database reads (`:401-420`) and `take_exit` performs effects: provider enqueues one requeue `v13_advance`, stopping calls `v13_goal_stop`, while wait/user_action/terminal are no-ops (`:423-439`). `run_turn` then combines entry advance, bounded serving, exit decision, and exit action (`:441-464`). This class is not an agent-selectable lifecycle tool dispatcher: its Python caller owns entry advance, serving, settlement, stop, and requeue timing. That proves the inspected controller path has not been demoted to IO/claim/complete; it does not prove that an authorized adapter could never let a model drive the existing SQL primitive.

`GoalSupervisor.tick` is a stateful supervisory entry path, not a pure disposition. Its separate class/connection does not establish a simultaneously running second process or resident scheduler. It settles unpaid work through `LoopDriver.settle_once`, may replan, handles human holds with notify/observe, can lease an effect, recovers idle work, reads scheduling/plan state, and may stop the goal (`v13/goal_supervisor/driver.py:174-268`). Its own preamble says it has no B1 exit machine/provider IO, but that does not make it pure; it still owns database reads/writes and settlement sequencing. This is the pre-existing authority that stage 40/41 were added beside.

#### 4. The agentctl verbs are real route tools, but no current driver consumes them

Stage 41 creates three `VOLATILE SECURITY DEFINER` functions, grants them only to `v13_route`, and inserts `agentctl_steer`, `agentctl_answer`, and `agentctl_cancel` as enabled SQL tools (`v13/agentctl_verbs/v13_agentctl_verbs.sql:61-64,139-142,263-266,327-378`). Thus they are not merely dead test helpers: the production SQL route selects the frozen handler and executes `SELECT %s($1,$2)` (`v13/plan_arm/v13_plan_arm.sql:779-789`), so a model-selected route can invoke them. The stage-41 route test proves that shape by preparing a parsed tool choice, calling `v13_advance`, and reading the resulting tool effect (`v13/agentctl_verbs/test_agentctl_verbs.py:1186-1201`; the full chain repeats this for all three verbs at `:1315-1335`).

But this is not the RP-CE lifecycle boundary. No `LoopDriver` method calls those wrappers; no `GoalSupervisor` method calls them; and stage 42 explicitly bans their names. The route can produce a tool effect, but there is no host/controller adapter that treats start/poll/wait/steer/respond/cancel as the agent turn’s complete control surface. This is why “the tools exist” and “the requested two-layer shape exists” are different claims.

#### 5. The stage-42 negative assertions forbid the desired vertical connection

The stage-42 test’s `DECIDE_BANNED` set includes `decide`, `decide_exit`, `run_turn`, `tick`, `GoalSupervisor`, and all four `v13_agentctl_*` names (`v13/goal_workflow/test_goal_workflow.py:76-92`). The AST scan rejects any call whose name is in that set (`:523-532`). The human-pending scene separately forbids `v13_cancel`, `v13_complete`, `v13_agentctl_answer`, and `v13_agentctl_cancel` (`:94-99,543-558`), and the SQL/body check rejects any `v13_agentctl_` occurrence (`:671-687`). The README says the same thing in plain language: `actl_driver_demoted` is deferred and the scene does not call observe/steer/answer/cancel (`v13/goal_workflow/README.md:49-53`). This is not a scheduling optimization; it is a gate-enforced ban on the connection the user asked for.

#### 6. Stage 42 landed by preserving the freeze, not by completing the cut

The stage-42 plan says it is a “pure tail append” that does not refactor `v13_advance` or `LoopDriver`, and that it is a first green fake scenario, not unattended operation, does not call the four agentctl verbs, and does not close D-3 (`docs/plans/v13-stage42-goal-workflow-2026-10-08.md:5-9`). Its scope repeats “do not call” the four verbs and “do not call” `GoalSupervisor.tick`, `run_turn`, `decide`, or `decide_exit`, while prohibiting changes to `ALLOWED_CONTROL_SQL` (`:25-28`). The resulting commit `5f65d7a` is exactly “v13: accept one fake goal workflow” and changes only the stage-42 implementation/tests/load/review files, not the driver or agentctl consumer path (`git show 5f65d7a`).

The 10-08 investigation did not itself authorize construction: “在 stage 41 计划的『不得提交』被明文改掉之前，本调查不授权提交……不授权写 `v13/goal_workflow/`” (`docs/investigations/v13-stage41-d3-stage42-deadlock-2026-10-08.md:11`). **That stop was conditional, and the current drafts do contain the relevant amendment.** The parent plan labels it “2026-10-08 D-3 死锁修订（Ruling A）” and says “第 2 项的完成条件不再包含……既有消费者。正文消费保持未关闭，不是第 3 项的前置” (`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:15`); stage 41 says “生产者可在两条 gate 都退出 0 之后提交” and stage 42 says “不等 D-3 正文消费闭合” (`docs/plans/v13-stage41-agentctl-verbs-2026-10-08.md:9`; `docs/plans/v13-stage42-goal-workflow-2026-10-08.md:5`). The deadlock report itself proposed exactly this split at `:154-162`. Therefore the probe's stronger inference—commit against a demonstrably unchanged stop—is not established. These drafts are untracked, and neither producer nor scene commit includes them; their amendment timing/user approval cannot be reconstructed from these Git snapshots alone.

What **is** committed and decisive: `95af56b` (2026-10-08 23:55 +08:00) delivers a test named `actl_steer_body_residual_open`, which checks `CONSUMER is None`, the nine non-consumers, and absence of the old '不得退出 0' wording (`v13/agentctl_verbs/test_agentctl_verbs.py:1555-1576`). It explicitly does **not** prove consumption. The committed ledger records S41-D3 as “未关闭。不发明消费者。不改 memory、triage、envelope 或水位谓词” (`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md:170`). Then `5f65d7a` (2026-10-09 01:13 +08:00, `v13: accept one fake goal workflow`) adds eight files, +1859/-12 lines, including a 99-line SQL read function and a 1565-line test scene, without changing either driver or any body consumer. Its S42-1 ledger accepts the four-advance Fake while expressly leaving D-3 open (`same ledger:172-177`; `git show 5f65d7a`). **The escape from the deadlock was narrowing what green means, not connecting producer to consumer.** Transparent residual reporting avoids a false D-3 claim, but does not satisfy the user's vertical cut.

The stronger process proof is the acceptance reversal. The minimal-form design requested `actl_driver_demoted`: “controller 路径的 Python 侧调用面 ⊆ {claim, complete, provider 调用}；无 decide_exit 参与” (`docs/designs/v13-agent-control-minimal-form-2026-10-02.md:308`, S2 listing at `:338-345`). The parent plan then says “`actl_driver_demoted` **延期**……该文件哨兵外字节不能改” and replaces it with `actl_driver_untouched` plus `actl_scene_no_decide_exit` (`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:298-302,670`). The first new test restores bytes against `fb295ac`; the second checks only the scene AST, not a demoted production controller (`v13/goal_workflow/test_goal_workflow.py:495-536`; `v13/plan_arm/test_plan_arm.py:275-318`). Thus 'prove role reversal' became 'prove the old driver was not changed and this new scene avoids its exit machine.'

Why did the Fake scene stay green without the primitive? The parent plan calls the empty envelope and resulting human/`low_intent_confidence` a live fact, “不是待修缺陷”, and orders each advance to return from prefix/spawn arms **before `v13_route`** (`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:304-312`; stage-42 plan `:5`). The test hardcodes Fake plan/spawn answers and Python choreography (`v13/goal_workflow/test_goal_workflow.py:962-994,1128-1269`), whereas the earlier stage-41 tests separately exercise mock → parse → SQL route (`v13/agentctl_verbs/test_agentctl_verbs.py:1262-1368`). Two separately green paths never establish their composition. This is the exact reason stage 42 landed without becoming the steer-body consumer.

#### 7. What PostgreSQL forced—and what the checklist process added

Under the chosen PostgreSQL authority/SQL-tool security contract, necessary correctness obligations include `SECURITY DEFINER`, fixed `search_path`, owner/ACL restrictions, route authorization, row locks, effect claim/fence tokens, and single-transaction completion (`v13/agentctl_verbs/v13_agentctl_verbs.sql:61-118,139-260,263-325`). Durable effect settlement needs explicit transaction boundaries while provider/tool IO stays outside them (`v13/loop_driver/driver.py:315-385`). Lease/fence and recovery protect durable concurrent execution; however, putting replan selection, recovery, notification projection, and stop dispatch together inside `GoalSupervisor.tick` is an architecture choice, not a PostgreSQL requirement (`v13/goal_supervisor/driver.py:129-172,217-268`). PG can remain the sole state/authorization owner behind a thin tool adapter and pure disposition; the D-A.3 ruling even permits stopping duplicate autonomous ticks by deployment configuration and forbids two independent pushers in one deployment (`docs/reviews/v13-agentctl-da-rulings-2026-10-03.md:24`).

The reference-as-checklist process added stage-specific directories, cumulative loader entries, exact source-freeze allowlists, setup/gate scripts, review rows, and per-stage commits. The precise repository sentences are “里程碑 = 计划正文划分的 stage / gate” (`AGENTS.md:13`), “一个里程碑一次提交。不要顺手把无关工作区的改动卷进同一次提交” (`:16`), and “MUST 立即提交代码并推送……MUST NOT 把多个里程碑积压到一次提交” (`:9`). New SQL must be appended to the loader and matrix/ledger/README updated (`:27-31`); the mandated sequence is “测试全绿 → 更新收尾工件 → git add（按路径）→ git commit → git push” (`:64`). The v13-specific append rule is “New stages append their SQL file at the END of SQL_LOAD_ORDER only” (`v13/load.py:3-5`). **AGENTS.md does not itself forbid a vertical rewire, does not require every milestone to add SQL, and does not forbid related cross-layer files in one milestone.** It makes the already-chosen producer/scene split awkward to deliver atomically; the actual prohibition comes from the parent plan's byte freezes (`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:58-67`), stage-41 refusal to change any driver (`docs/plans/v13-stage41-agentctl-verbs-2026-10-08.md:18-20`), and stage-42 '纯尾追加，不做重构' plus no-agentctl/no-D-3 scope (`docs/plans/v13-stage42-goal-workflow-2026-10-08.md:7,25-30`). The executable freeze enforces those choices: “R1 removal must restore ALL baseline driver.py bytes” and “run_turn edit outside sentinel must fail” (`v13/plan_arm/test_plan_arm.py:289,314`).

This is not a necessary consequence of 'no second engine'. The minimal-form design prohibited only “`v13_agent_run` 总调度 / 第二推进函数” while also asking for controller routing and executor-of-record demotion (`docs/designs/v13-agent-control-minimal-form-2026-10-02.md:322-345,350`). A renamed/new adapter delegating to the sole existing advance was conceptually compatible; preserving all old driver bytes was an additional choice. The references became named implementation buckets instead of integration boundaries: the parent plan labels LoopX macro / CE meso / agent-loop micro, makes the goal 'consecutive integers 40,41,42' with a green Fake, then distinguishes functional consumption from cumulative loading (`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:33-37,50-54,498-506`). Its dependency table expressly says 43 does not consume 42's scene and 44 does not consume 43's classifier (`:505-506`). Extra stages then provide safely bounded producer/classifier/map evidence but not the missing composition.

### Eliminated alternatives

- **“The references were unavailable or never consulted.”** Eliminated. A misunderstanding of the composition boundary is not eliminated; RP-CE’s actual one-service op switch and LoopX’s pure disposition contract are in the workspace and match the intended shape (`AgentRunMCPToolService.swift:412-438`; `loop_controller.py:1-17,639-670`). v13 even records the CE mapping, but only as static JSON (`v13/ce_map/v13_ce_map.sql:5-18`).
- **“The user asked for a second engine and the project correctly refused it.”** Eliminated. Neither reference requires a second engine: RP-CE uses one `execute(op)` lifecycle surface, and LoopX’s controller is explicitly not a loop or scheduler (`turn-loop-controller-v0.md:3-17`).
- **“Stage 42 was the missing consumer but only forgot a call.”** Eliminated. The plan and tests expressly ban the four verbs and the existing driver/supervisor calls (`docs/plans/v13-stage42-goal-workflow-2026-10-08.md:25-28`; `v13/goal_workflow/test_goal_workflow.py:76-107,523-558`). The refusal is designed behavior.
- **“Agentctl is test-only SQL.”** Eliminated, with qualification. The functions are registered production SQL tools and route-authorized (`v13/agentctl_verbs/v13_agentctl_verbs.sql:327-378`), and a model-selected SQL arm is tested through `v13_advance` (`test_agentctl_verbs.py:1186-1201`). What is missing is a production Python/host lifecycle consumer, not the SQL producer.
- **“D-3 was silently declared satisfied, or 42 demonstrably ignored an unchanged stop.”** Both are unsupported. D-3 remains expressly open; current drafts contain Ruling A, and the 10-08 investigation recommended that split. Git proves producer-only acceptance and no consumer, but cannot date untracked draft edits or establish missing user approval (`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:15`; `v13/agentctl_verbs/test_agentctl_verbs.py:1555-1576`; `docs/investigations/v13-stage41-d3-stage42-deadlock-2026-10-08.md:154-166`).
- **“All extra layers are required by PostgreSQL.”** Eliminated. PG explains transaction/authorization/lease complexity, not multiple push authorities, a static CE map, or a Fake workflow that is forbidden from using the primitive it is meant to validate (`v13/loop_driver/driver.py:315-397`; `v13/goal_workflow/test_goal_workflow.py:76-107`).

### 8-line conclusion

1. The drift is **layers welded side by side**, not merely an unfinished final adapter.
2. RP-CE already demonstrates the needed agent-loop primitive as one `execute(op)` lifecycle surface.
3. LoopX already demonstrates the needed long-running layer as a pure disposition function with no model, sleep, host, state, or quota effects.
4. v13 had `LoopDriver` and `GoalSupervisor` owning advance/settlement/supervision before agentctl, so later stages were additive rather than connective.
5. The no-second-engine bans did not logically block the user’s shape; the additional driver freeze and deferred demotion blocked the vertical rewire.
6. `goal_workflow` refusing agentctl is therefore a structural freeze consequence, enforced by its plan and negative AST tests, not local scheduling taste.
7. Ruling A unblocked producer-only acceptance; stage 42 then proved a bypassing Fake, not body consumption or composition of the two layers.
8. The thin implementation should have been one lifecycle tool boundary plus one pure host-triggered disposition consumer; the stage/checklist process instead turned that cut into a sequence of parallel acceptance artifacts.

## Investigation Log

### Phase 1 - 症状与假设

**Hypothesis:** 不如愿的原因不是「还没把参考项目抄完」，而是开发结构把「两层薄切」翻译成了「追加 stage + 对齐 parity 行 + 计划条文互锁」。参考项目因此变成清单，而不是刀口。

**待证假设：**

1. **过程偏差（H1）**：`AGENTS.md` 的「一里程碑 = 一 stage = 追加 `SQL_LOAD_ORDER` = 一提交」把极简设计切成 S1/S2/S3，相邻计划再追加 42–44。单刀直入在这套收尾纪律下不合法。
2. **参考被物化（H2）**：`agent_run` 是会话生命周期上的五个 op；loopx `loop_controller` 是不调用模型的纯函数。v13 把两者都收成 SQL 合同 + Python 驱动 + gate。有参考增加了搬运面，而不是减少了设计面。
3. **层被焊死（H3）**：长运行语义（should_run / quota / attention / govern / goal_supervise / fair_claim / frontier）写进了与 turn 推进同一条追加链，且发生在「agent 持有控制动词」之前。之后每次扩展都改内核，而不是调用稳定原语。
4. **权威来回翻（H4）**：「PG 唯一 owner」「v13 = pi 替代、被 LoopX/RP-CE 驾驶」「不建 `v13_agent_run` / 不建第二 advance」三条同时有效，使用户要的形状在裁决链里不合法，只能再表达成一个 stage。
5. **条文死锁（H5）**：完成条件写在未跟踪计划里，且与已提交裁决矛盾。agent 服从最新停止规则，不服从两层切面。10-08 死锁是该结构的实例，不是偶发。
6. **清单代替刀口（H6）**：parity 的改变桶 / 永不建桶把「借形状」变成「关行」。关不完就继续开 stage。

**Findings:** 症状已用 `v13/load.py:17-61`（44 段）和上述四份文书核对。根因与「44 段里哪些其实是第二引擎」尚未用提交史和源码钉死。

**Evidence:** `v13/load.py:40-61`；`docs/designs/v13-agent-control-minimal-form-2026-10-02.md:165-182`、`:348-363`；`docs/investigations/v13-stage41-d3-stage42-deadlock-2026-10-08.md:1-20`。

**Conclusion:** H1–H6 的方向与 Phase 1.5 一致，但「42 如何在 10-08 死锁之后仍进 main」和「LoopDriver 是否真是唯一推进者」还未用源码行号钉死。

### Phase 2 - context builder / oracle 初判（待 pair 抽查，不是终判）

**Hypothesis:** 偏差是层被焊成并排 stage，不是「还没做完」。

**Findings:** Oracle `explain-v13-structure-dr-0AC1B0` 初判：RP-CE 最小面是一个 `agent_run.execute(op)` 会话入口；LoopX 最小面是无副作用 `decide_loop_disposition`。v13 在原语之前已有 LoopDriver / GoalSupervisor 占住推进权；40–44 追加在旁边。`goal_workflow` 不调用 agentctl 被判为冻结+禁止后续 stage 补前置语义的推论，不是漏接线。字面「不建第二引擎」被实现成「不允许重新接线」。

**Evidence:** 选择集含 `AgentRunMCPToolService.swift` 切片、`loop_controller.py`、`v13/loop_driver/driver.py`、`v13/goal_supervisor/driver.py`。行号尚未由本会话复核。

**Conclusion:** 采用为待证命题。Phase 4 已抽查行号，写入 Root Cause。

### Phase 4 - 抽查与收口

**Hypothesis:** 验收反转（`actl_driver_demoted` → `actl_driver_untouched` + 场景禁调 agentctl）是把参考变成更多 stage 的机制。

**Findings:** 行号已核。`AgentRunMCPToolService.swift:412-438` 确为六 op 分派。`loop_controller.py:1-17` 确为纯函数。`driver.py:173-177` 直接调 `v13_advance`；`decide_exit` 本身纯（`:95-112`），推进权在 `take_exit` / `run_turn`（`:423-464`）。`test_plan_arm.py:289,314` 把哨兵外改 `run_turn` 判失败。父计划 `:298-312` 明文：降级断言延期，因为字节不能改；场景攻在 `v13_route` 之前返回的臂上。stage 42 计划 `:5-9` 禁止调用四个 agentctl 动词。`test_goal_workflow.py:76-92` 把这些名字写进 `DECIDE_BANNED`。D-A.3 禁止同一部署两个独立推进者，但没有授权降级既有 `LoopDriver`。

**Evidence:** 上列行号本会话 `read_file` 核过。pair 的一处纠正保留：`AGENTS.md` 本身不禁止纵向重接线；禁令在计划的字节冻结、「纯尾追加」和负向 AST。

**Conclusion:** 确认。写入 Root Cause。

## Root Cause

不如愿的原因不是缺参考、也不是缺动词。是验收条件把「角色反转」改成了「禁止变更」。

用户要的刀口在两个参考里已经极小：

- RP-CE：一个 `execute(op)`，闭集 `start/poll/wait/cancel/steer/respond`（`AgentRunMCPToolService.swift:412-438`）。编排是模型调这个工具，不是第二个引擎。
- LoopX：`decide_loop_disposition` 是纯函数，不调模型、不睡眠、不写状态、不花 quota（`loop_controller.py:1-17`）。host 决定要不要再跑一次 turn。

v13 已有唯一 durable 推进函数 `v13_advance`。SQL route 已能按工具名执行 handler（`v13/plan_arm/v13_plan_arm.sql:779-789`）。stage 40/41 把 observe/steer/answer/cancel 登记成了这条路径上的工具。到这里，薄切已经够用：一个 agent turn 选这些工具，外层一个纯函数读回执，决定下一跳。

偏差发生在这之前和这之后：

1. **推进权先被占住。** `LoopDriver.advance` 直接调 `v13_advance`（`driver.py:173-177`）。`run_turn` 拥有入口 advance、serve、退出判断和退出动作（`:441-464`）。`take_exit` 在 provider 臂上再排一次 advance（`:423-439`）。`GoalSupervisor.tick` 是另一个会写库的监督入口。这些都早于 agentctl（10-01 的 `05a1687` / `78e77c7`，对 10-08 的 `a19aefc`）。
2. **降级被冻结掉。** 10-02 极简稿要的是 `actl_driver_demoted`：controller 路径上 Python 只剩 claim / 事务外 IO / complete。后来 `test_plan_arm.py:289` 要求剔掉 R1 哨兵后 `driver.py` 字节全等于 `fb295ac`，`:314` 规定哨兵外改 `run_turn` 必须失败。父计划因此把降级断言延期，改成 `actl_driver_untouched` 与 `actl_scene_no_decide_exit`（`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:298-302`）。
3. **纵向调用被写成负向测试。** stage 42 是「纯尾追加」，明文不调用四个 agentctl 动词、不闭合 D-3（`docs/plans/v13-stage42-goal-workflow-2026-10-08.md:5-9,25-28`）。场景被要求打在 `v13_route` 之前就返回的臂上，模型根本选不到工具（同父计划 `:304-312`）。`test_goal_workflow.py:76-92` 的 `DECIDE_BANNED` 把四个 `v13_agentctl_*` 和 `decide_exit` / `run_turn` / `GoalSupervisor` 一并禁掉。绿的含义变成：旧推进者没被碰，新场景也没用新原语。
4. **参考因此变成清单。** 40/41 是生产者，没有 host 消费者。42 是被禁止调用生产者的 Fake 场景。43 是入口分类。44 的 `v13_ce_map()` 只返回静态 jsonb，调用它不执行签名（`v13/ce_map/README.md:3-5,32-48`）。每一刀都能独立全绿，没有一刀要求「上层调用下层」。

「不建第二引擎」没有逻辑上挡住这个形状。挡住它的是额外一条：把「不新增 durable 引擎」实施成「不许把既有 `v13_advance` 重新接给 agent turn，也不许把 `LoopDriver` 降成适配器」。D-A 裁了 v13 唯一权威、同一部署不得有两个独立推进者（`docs/reviews/v13-agentctl-da-rulings-2026-10-03.md` D-A / D-A.3），但没有同时授权把既有推进者降级。冻结保护的正是要被反转的那个角色。

`AGENTS.md` 的「一里程碑一提交、SQL 只追加」不是主因。它让已经选定的生产者/场景分裂不便原子交付，但没有禁止一次里程碑同时改驱动器和工具面。真正的禁令写在父计划的字节冻结、stage 42 的「纯尾追加」和负向 gate 里。

所以有参考却不能单刀直入：参考的价值是组合关系（谁调用谁），开发结构把它拆成可独立关闭的名称桶，再用冻结禁止组合。每关闭一桶，就多一个 stage，离两层相叠更远。

## Recommendations

1. **停止把「`driver.py` 未改」当成这条线的进展。** `actl_driver_untouched` 与 `actl_scene_no_decide_exit` 不能再当角色反转的验收。字节冻结可以继续保护无关改动，但不能保护正在被反转的那个角色。机械位置：`v13/plan_arm/test_plan_arm.py:289,314`。
2. **下一刀只证一条纵向链，不加 stage 45。** 一个 Fake turn 经既有 `v13_advance` → SQL route（`v13_plan_arm.sql:779-789`）选中 `agentctl_*`；handler 改变目标会话的 durable 状态；外层一个纯函数读这份回执，只返回一个 disposition，不调模型、不写库。不新建 `v13_advance`，不建 `v13_agent_run` 总调度。替代断言就叫这一条链成立，不叫「旧文件没被碰」。
3. **明文授权 controller 路径上把 `LoopDriver` 降成 claim / 事务外 IO / complete。** 这与 D-A.3（同一部署不得两个独立推进者）和「不建第二 advance」兼容。不兼容的是现在的字节冻结。降级必须允许改 `driver.py` 哨兵外的 `run_turn` / `take_exit`，否则下一个 stage 仍会被迫绕开它。
4. **停止「消费者必须已存在，但后续 stage 不得成为消费者」。** 若消费者不存在，生产者、消费者与组合 gate 放进同一个纵向切片。`goal_workflow` 的禁调可以留作历史夹具，不得再当下一 stage 的模板。`ce_map` 保持静态即可，不要再加一张对照表来充当运行时。

## Preventive Measures

- 控制面的验收必须断言一条调用边（谁调用谁、结果进了哪一行），不能断言「没改某文件」。缺席不是进展。
- 借参考时先写组合关系，再写「不重建引擎」。只有正向边存在之后，负面清单才不会把重接线一并禁掉。
- 字节冻结只保护已结算的内核。正在反转的角色所在文件（这里是 `v13/loop_driver/driver.py` 的 `run_turn` / `take_exit`）不得进入这种冻结。
- 一个里程碑可以同时改驱动器和工具面，当且仅当该里程碑就是重接线。`AGENTS.md` 已经允许；不要再在计划里加更严的「纯尾追加」。
