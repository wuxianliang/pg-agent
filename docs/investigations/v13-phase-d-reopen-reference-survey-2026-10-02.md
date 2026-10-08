# v13 Phase D 被裁项重开：pi+LoopX+RP-CE 参考系统调查（2026-10-02）

**性质：调查报告 + 路线图提案。不是计划，不是裁决，未跑任何 gate。** 按 Phase D 计划合同，「父若要打开，另写计划」——本文为后续逐项重开计划提供证据底座。父指令（2026-10-02）：被 Phase D 目标表述挡住的项目，必须最终参考 pi+LoopX+RP-CE 的长时间工作流开发过程来推进 v13 一一解决。

调查产物：本报告。三路只读探针卷宗（loopx 治理层 / pi 执行器 / RP-CE 工作台）+ `~/rp-goal-e2e` 管线实测亲验。探针承重结论已由主会话逐条 grep 复核（见 §6 抽查记录）。

---

## 1. 用户系统的真实形态（rp-goal-e2e 管线实测）

`~/rp-goal-e2e` 是一条已真实跑通（含失败路径）的 E2E 管线，2026-10-01/02 两轮测试：

```
LoopX bootstrap ──> .loopx/registry.json + .codex/goals/<id>/ACTIVE_GOAL_STATE.md
   │  spawn_policy(allowed=false, max_children=3)、coordination(write_scope=[src/math.js, test/math.test.js],
   │  requires_parent_approval=[write,publish,production-action])、registered_agents=[pi-rp-goal-e2e-mul-01]
   ▼
pi 执行者（agent_id=pi-ce-agent-2a3572）──在──> RP-CE app-managed worktree
   │  ~/.repoprompt-worktrees/rp-goal-e2e/rp-agent-7ce2cc36-agent（分支 rp/agent/<session>-agent）
   │  产出 commit c08828f（mul + node:test）
   ▼
LoopX 控制器独立复核（diff 审查 + 从 worktree 根重跑 node --test，exit 0）
   ▼
writeback：ACTIVE_GOAL_STATE.md todo 状态机推进（advancement_task→done，带 evidence/successor/completion_turn_key）
   + rollout-event-log.jsonl（21 事件）+ task-leases/.lifecycle-fences 收据
   ▼
user_gate（open）：「Owner decision: authorize git-disposition merge of CE worktree branch … or reject.
   No merge/add/commit/push is performed without this explicit request.」
```

失败路径同样实测过：三个 worktree 中一个空置（失败/弃置 run）、一个产出偏差提交（9eacfb51 "Add subtraction"，任务要的是 fib）、一个正确产出停在人工门。**门挡住的不是理想路径，是含偏差在内的全部路径。**

### 1.1 与 v13 的同构表（关键发现：语义已在两面对齐）

| 参考面（实测） | v13 对应物 | 状态 |
|---|---|---|
| LoopX task_class 闭集 `advancement_task/continuous_monitor/user_gate/user_action/blocker`（`control_plane/todos/contract.py:72-82`） | Phase A T1.1 同名闭集 | **已对齐**（v13 设计时即取自 LoopX） |
| todo 状态 `open/done/blocked/deferred` + `completion_continuation ∈ {active_goal, successor, no_followup}` + `successor_todo_ids` + `completion_turn_key` | T1.1 状态闭集 / `link_on=successor` / apply_id 幂等重放 | 已对齐；v13 更严（同键异参 RAISE） |
| `replan_obligation_id = "replan-"+sha256(frontier_revision+progress_fingerprint+kind+agent_id)`，ack 关闭（`autonomous_replan_obligation.py:249-263`、`ack_policy.py:37-70`） | frontier_gap 语义键 `replan:{root}:{gap_kind}:{subject}:{object}` + 义务折叠 | 已对齐；v13 无 agent_id 维度（合理：PG 单库单树时期无多 agent） |
| fence 收据 `operation_id/request_digest/lock_token/fence_owner/lease_epoch/state`（`task_lease_lifecycle.ts:387-447`） | v13 claim 的 attempt_no/fence/lease_until + `task_lease_fence_receipt_v0` 同构 | 已对齐 |
| user_gate 开放态阻塞 git disposition（`requires_parent_approval`） | Phase 0 T2 / Phase C C5：human pending = 非终态 waiting，skip 是人工动作 | **语义完全一致**；RP-CE 侧同样设计（agent 起的 merge 永不自动批准，见 §3.3） |
| `quota_should_run` 事件（should_run/delivery_allowed/must_attempt_work/quiet_noop_allowed/closeout_required/interaction_mode） | PC-4 被裁两次的 goal 级配额门 | **参考实现存在**（§3.1），v13 缺口是重开载体而非语义 |
| `execution_profile`（cadence/spend_rule/outcome_floor/degradation_policy） | duty_cycle（shadow 种子）+ quota_window（session 局部） | 部分对齐；goal 级与 outcome_floor 缺 |

**结论：用户想要的系统不是新发明——它是 v13 既有语义的文件版运行时。重开工作是把 v13 已对齐面的另一半（被裁项）按参考实现补齐，而不是引入新范式。**

---

## 2. 三仓角色定位（沿用户 2026-09-26 定位定稿）

| 系统 | 定位 | 本次新增证据 |
|---|---|---|
| pi | 执行器（进程内 turn 引擎） | 无内建权限/写域（README 明说）；`pi-<repo>-<task>-<nn>` 命名出自治理层而非 pi；无 review lane 原语；RPC/JSONL/SDK 三入口可程序化驱动；session JSONL 树 + SQLite 后端可选 |
| RP-CE | 工作台+委托拓扑（时-日） | worktree merge=带人工门状态机；Oracle 1+4 lane 并行不裁决；oversight grant 四能力+auto-wake 三问准入；冷恢复把 in-flight 归一为终结 |
| LoopX | 治理经济层（天-周） | quota 状态机七态；outcome_floor streak 强制；settlement 三步链同 Turn 同身份；四件套 crash 恢复；**仓内已有 postgresql_v0 authority provider 先例** |

---

## 3. 逐项证据与重开判断

### 3.1 PC-4 goal 级配额 —— 参考语义完整，重开载体是机械问题

**LoopX 实现**（探针卷宗一，已抽查）：

- **三分离**是三种状态类别，不是三个函数：资格（quota 状态机 `paused/blocked_health/operator_gate/waiting/focus_wait/throttled/eligible`，`loopx/quota.py:402-473`）、审批（`operator_gate` 态只开 `safe_bypass_allowed` 缝）、reward（human reward/教训只作只读告警，永不给执行权，`_supporting_projections.py:34-75`；文档 `docs/quota-allocation.md:40,250,293` 明说 quota 不决定 reward/write approval）。
- **spend_rule 执法在 spend 侧**：`spend_commit.ts:348-396` 只认 6 种 disposition；`slot_accounting.py:683-951` 预览阶段要求「latest unspent Turn settlement writeback」存在；`settlement_plan.ts:41-45` spend 步 precondition 写死「matching durable writeback exists」。即 **v13 Phase C 已交付的 settlement 链（收据臂+goal_supervisor settle_once）就是 spend 侧执法点的对应物**。
- **outcome_floor**：`outcome_gap_streak`/`small_scale_streak` 是 runs 历史前缀 fold（`delivery_history.ts:174-175`）；streak≥阈值（3）→ quota 态改 `focus_wait` + 只开 `outcome_floor_recovery` 一条缝（`quota.py:228-307`）。「canonical wait」豁免由纯函数判（bound todo+advancement_task+resume_condition 未满足）。
- **spent 不用计数器**：窗口内 spend/void 事件重算求和（`quota.py:358-399`）——天然跨天衰减、免 reset 作业。**与 v13 quota_window 的事件重算同构，只差作用域（session→根树）**。

**RP-CE 佐证**：凭据信封 60 秒/单次 redeem/用后清零/只递 ID 不递内容（`DomainCredentialEnvelope.swift:220-341`）——若 v13 后期要把 provider key 递给 DB 外进程，这是最短寿信封的参考形状。

**v13 重开判断**：Phase D §4.10 关闭理由是「抄 gate 全文怕错」。参考证据把重开范围收窄为三件，且都有逐行参考：
1. goal 级窗口计数：`v13_quota_eligible` 的 session 局部计数改为沿根树聚合的 STABLE 重算（LoopX spent 重算同构；一库多根后单 goal=一根树，Phase D 公平面已交付多根正例）；
2. should_run 门版本 4：新增 block id（如 `goal_quota`），**必须按 T7/Phase C §4.11 的既有条款贴加载后 gate 全文哈希**——LoopX 的 5 允许位析取结构（`decision_summary.py:264-270`）可作为逐臂对照的校验参照，把「抄错」风险变成「逐臂 diff 可证」；
3. outcome_floor 投影：`outcome_gap_streak` fold + `focus_wait` 形态的 exemption（不新增事件种类，闭集投影）。
不建 quota 表、不建 reward 面（reward 三分离=只读告警，v13 economy/summary 已有投影位）。

### 3.2 C4 多 lane 咨询 —— 参考答案收敛为「并行只读车道 + 不建仲裁」

**RP-CE 实现**（探针卷宗三，已抽查）：

- Oracle roster = 1 主 + 4 辅（`OracleGroupContracts.swift:67-104`），TaskGroup 并行、按 laneIndex 还原顺序、group status 三分类（failed/partialFailure/completed）；**单 lane 显式拒绝进 coordinator**。
- **仲裁是显式非目标**（`docs/architecture/oracle-groups-rewrite.md:19-30`）："The coordinator does not combine, rank, vote on, or choose among lane answers… No answer synthesis or arbitration. No automatic winner selection." 收敛路径=把结果交给人工/下游 agent 裁决（`AgentRunOracleReviewContext` / extract_handoff）。
- per-lane 参数矩阵：外层按 roster 对齐、内层不带 lane 字段（`OracleExecutionResolver.swift:96-131`）。

**用户自己工作流的佐证**：v14 G1 计划的 71 轮对抗审核就是双 lane（codex gpt + cursor grok）+ 主会话 triage + 拍板——**lane 不裁决、父裁决**的活例，且两 lane 分歧本身被记档（v13-long-loop Phase D 计划复审同款：5 轮双 lane 收敛 P0/P1=0）。

**pi 侧反证**（探针卷宗二）：pi 无 review lane/第二意见原语——确认多 lane 咨询属于治理层（PG 侧），不属于执行器。

**v13 重开判断**：Phase D 把 C4 裁「不做」的理由是「没有已审核的载体，硬做会变第二状态源」。参考证据给出的载体形状恰好绕开该理由：
- 咨询 lane = **只读 llm effect 的 fanout 维度**（llm effect/events 是既有面；lane 是 effect 载荷/派生维度，不是新状态源）；
- 收据 = 既有 llm complete + 有序 lane 结果投影（对照 RP-CE 按 laneIndex 还原顺序 + primary 投影=第一条）；
- **不建仲裁器、不做合成**（照抄 RP-CE 非目标条款进 v13 计划合同）；裁决走既有人工面（human effect / ASK_USER）。
- 首期闭集建议 1+4（对齐 RP-CE 上限），lane 并行数与 spawn_budget 的关系须在重开计划里显式裁决（不写 8/64 常数）。

### 3.3 真实长时运行（无人值守/多日） —— 三层参考：恢复、节律、唤醒

**LoopX 四件套 crash 恢复**（探针卷宗一）：
1. per-turn 身份与收据 replay（heartbeat receipt；settlement_effect_id = `goal:agent:(todo|replan):turn_instance`，**同 Turn 同身份**跨步幂等——`effect_program.ts:415-459`）；
2. 未结案 turn 强制恢复（`unsettled_host_turn_recovery.ts:480-560`，repair ∈ {monitor_poll, resume_prior_turn, lifecycle}，**恢复转移不花配额**）；
3. 写路径歧义 → `ambiguous` + 同 operation_id 重试（replay→observe→commit 三段式）；
4. refresh 重放/修收据（决策 ∈ replay/repair_receipt/reject）。
调度持久态（rrule/stateful_backoff/24h TTL）在 `scheduler/state_store.ts`——**无人值守节律跨天连续不靠 cron 靠持久态+重放**。

**RP-CE 冷恢复 + auto-wake**（探针卷宗三，已抽查）：
- 冷恢复把上次 persisted run state 归一为「已终结」而非假装活着；上次被打断仍在执行的工具标 cancelled（`AgentSessionRestoreSupport.swift:61-234`）——**与 v13 unknown 墙语义同向但更细**（v13 过期 tool→unknown+墙；RP-CE 直接取消+生成 cancelled result）。
- **oversight auto-wake**（v13 V11 一直「未读未闭合」的参考语义就在这）：grant 四能力闭集 `poll/wait/read/sendWhenIdle`（从不按角色推断，`DomainAgentSessionLinkModels.swift:35-53`）；endpoint 带世代、未解析绑定 fail-closed；**唤醒准入三问定序**（basis 四态/suppression 四因，`AgentSessionLinkAutoWake.swift:160-202`）；tombstone 作传输栅栏（in-flight 的 provider 调用不可被本地取消撤回）。架构文 `docs/architecture/agent-session-oversight-auto-wake.md` 四所有者表。
- worktree merge 人工门：routed Agent Mode 的 apply **显式拒绝** `confirm_preview=true`（`MCPWorktreeToolProvider+Merge.swift:73-74`），必须走 `awaitingApproval` 挂起 + UI 决策 + 600s 超时=显式拒绝 outcome——**merge gate 在 RP-CE 与 LoopX user_gate 两面都是设计内人工门，印证 v13 T2/C5 的等待合同是正确基线，不是待修破损**。

**pi 佐证**：pi 无内建权限系统——执行器的写域约束必须由治理层给（v13 Phase B workspace_admit 已交付 write_scope 准入；pi 的 tool allowlist≈v13 grant 面）。

**v13 重开判断**（分三步，依赖递增）：
1. **UA 授权增补先行**（计划已成文待复审）：让 supervisor tick 获得授权的 exit 0 形态——这是任何长时运行的第一刀，不依赖本调查其余部分；
2. **V11 auto-wake 阅读+接线**：以 RP-CE 三问准入+tombstone 栅栏为参考语义写重开计划（v13 已有 `v13_wake_is_satisfied_v1` 四变体 one-of 与 B6「本 tick 默认不调用」的伏笔）；唤醒替代轮询是多日运行的成本前提；
3. **多日 soak 授权**：LoopX 节律=持久态+重放（不是 cron、不是 sleep 循环）——v13 形态=scheduler_hint 三值+驱动器睡眠（T5 已裁）+跨天收据 replay；真实多日运行需真实 provider 授权（另行授权，与 UA 同款 env-gated 先例）。

### 3.4 公平领用残留（PD-H1..H9） —— LoopX 已有 PG 先例，双入口可长期化

- LoopX authority provider 枚举 `file_v0|sqlite_v0|postgresql_v0`（`local_authority_provider.ts:22-25`），仓内已有 `postgresql_authority_store.ts/service.ts` ——**LoopX 自己也在把权威面迁 PG，v13 可反向对照其表形状**。
- HANDOFF_MODES `legacy|soft_claim|hard_lease`（`handoff_mode_policy.ts:6`）——对应 v13「活体 v13_claim（legacy）+ v13_claim_fair（hard_lease 语义）」的双入口格局。**参考证据支持把 PD-H1（帽的洞）从「接受残留」升级为「迁移计划」**：LoopX 用 authority-transition 围栏做写者迁移（legacy writer fence + 已应用前缀校验），v13 若要把活体 claim 纳入帽，是「第二份 CREATE OR REPLACE v13_claim」红线的重开——须单独计划，不是顺手改。
- 短期不动 PD-H1..H9 的依据不变（超级用户夹具不证明生产；产品角色核验仍是 Phase 0 §10 未决门）。

---

## 4. 路线图提案（R0–R4）——已被 §8.2 调整版取代（父定位修正 2026-10-02：v13=pi 替代，先承载互动再内化；原 R1–R4 保留为内化阶段清单）

| 期 | 内容 | 参考依据 | 前置 | 规模预估 |
|---|---|---|---|---|
| **R0 同步+收口** | pull main（v14 已并入，18 commits）；复审并落地已成文的 UA 授权增补（三提交：计划入库→预存冻结红修复→授权机器） | Phase A real-provider env-gated 先例 | 无 | UA 计划已排定 |
| **R1 goal 级配额（PC-4 重开）** | 新 stage：根树窗口 STABLE 重算 + should_run 门 v4（贴 gate 全文哈希）+ outcome_floor streak 投影 + focus_wait 型 exemption | LoopX quota 状态机/spent 事件重算/spend 侧执法（§3.1） | R0 | L（含 1..N 回归） |
| **R2 咨询多 lane（C4 重开）** | 只读 llm 咨询 lane：1+4 闭集、有序 lane 收据、primary 投影、**不建仲裁**（非目标条款入合同）；lane×spawn_budget 关系显式裁决 | RP-CE Oracle roster/非目标条款 + v14 双 lane 对抗循环活例（§3.2） | R0；与 R1 无序 | M |
| **R3 wake 接线（V11 重开）+ 多日运行授权** | V11 阅读+auto-wake 接线（三问准入/tombstone 栅栏参考语义）；多日 soak 授权形态（持久态+重放节律） | RP-CE oversight auto-wake 架构 + LoopX 四件套/scheduler state（§3.3） | R0 完成；建议在 R1 后（配额先于节律，防失控成本） | L |
| **R4 公平面残留处置** | PD-H1..H9 逐条：优先 H1（帽的洞）→ 活体 claim 迁移围栏计划（对照 LoopX authority-transition）；其余维持台账 | LoopX postgresql_v0 authority 先例（§3.4） | R1（配额语义先稳） | 视裁决 |

顺序理由：R0 是一切的地基（四 gate 预存冻结红也在此修）；R1/R2 可并行但都依赖 R0 的基线复核；R3 依赖授权心态与配额护栏；R4 是收尾处置。**每期必须按仓库纪律另写计划过审（多 lane 复审），不动 stage 1–29 字节，外部 IO 不进事务，新表先过 R4 表达形式裁决四问。**

## 5. 不因本调查改变的既有裁决

- 零新表默认（R4 表达形式终裁）：R1 的窗口重算/outcome_floor 走投影；R2 的 lane 收据走既有 events/effects；若实现期证明必须新表，先答四问。
- 不建第二状态源/工作流引擎（Phase 0 用户决定）；不建 cadence ACK/RRULE/scheduler 状态表（B3）——LoopX 的 scheduler state 只作参考语义，其 RRULE 形状不进口（T5 已裁三值 hint+驱动器睡眠）。
- 无人值守 skip 恒不授权（T2）；无人值守 plan_commit 恒不授权（T1.4）；explore RAISE 保持（直至 R2 另裁）。
- 真实 provider/多日运行 = 授权制，不因参考系统存在而默认开启。
- 一模一样=0 的 parity 结论不变：参考系统是语义来源，不是逐字节移植目标（LoopX 26 表治理面整包不搬的裁决维持）。

## 6. 探针结论抽查记录（主会话亲验）

| 承重结论 | 抽查 | 结果 |
|---|---|---|
| LoopX 有 PG authority 先例 | `ls loopx/control_plane/coordination/ \| grep -i postgres` | ✅ postgresql_authority_service.ts / store.ts |
| quota 七态含 focus_wait/operator_gate | `grep -n "focus_wait\|operator_gate" loopx/quota.py` | ✅ :210-292 |
| RP-CE agent merge 永不自动批准 | `grep confirm_preview MCPWorktreeToolProvider+Merge.swift` | ✅ :73-74 显式拒绝 routed agent 的 confirm_preview=true |
| LoopX task_class 与 v13 同名闭集 | `grep advancement_task contract.py` | ✅ :72-74 |
| Oracle 不裁决是显式非目标 | `grep "does not combine" oracle-groups-rewrite.md` | ✅ :19,23 |

三份探针卷宗原文存于本次会话记录（loopx 治理层 / pi 执行器 / RP-CE 工作台，各含完整 file:line 指针），重开计划撰写时直接引用。

## 8. 定位修正：v13 = pi 替代——Phase A–D 尾部的承载调整（2026-10-02 父补正）

父补正：**pi 在 LoopX 和 RP-CE 中只是宿主；pg-agent 本身就是 pi 的替代。v13 的 Phase A–D 四步需要调整才能承载 LoopX 与 RP-CE 的互动。** 本节取代 §4 作为路线图权威，§1–§3 的证据全部沿用。

### 8.1 pi 槽位的真实契约（从 rp-goal-e2e 实测反推）

pi 不带任何治理——它只跑 turn。全部治理状态在 LoopX 文件面 / RP-CE session JSON 里，互动经由 pi 中转四条：

| 方向 | 互动内容 | 现载体 |
|---|---|---|
| LoopX→执行器 | goal state 读取、quota should-run 门、task lease/fence 领取、agent 注册身份 | ACTIVE_GOAL_STATE.md + task-leases/ + registry |
| 执行器→LoopX | todo add/complete（带证据/后继/turn_key）、rollout 事件、runs、settlement（writeback→spend→closeout） | loopx CLI + fence 收据 |
| RP-CE→执行器 | session spawn/steer/respond、worktree 绑定（rp/agent/*-agent）、oversight grant、auto-wake | agent_run + manage_worktree + agent_session_link |
| 执行器→RP-CE | turn 结果、transcript、merge 处置请求（awaitingApproval）、handoff | session JSON + merge 状态机 |

**v13 已占据槽位核心**：`loop_driver.run_turn`（override→advance→serve 循环→B1 出口→take_exit，`v13/loop_driver/driver.py:441`）就是 pi 的 turn 引擎对等物；`user/message` 事件（`v13_append_event`）就是消息 ingress；`settle_once` 就是 settlement 跳。2026-09-21 对照调查已裁「RP-CE 五原语无一超出 effects/events/human 平面已有动词」「外部 harness=wrapper 深度」。**缺的不是语义，是「被驾驶模式」：A–D 全部按 v13 自驱设计（自己的 plan/todo goal 面 + goal_supervisor 自律），外部宿主驱动时的权威归属与入口契约从未落。**

### 8.2 调整版路线图（E0–E3 承载 + I1–I4 内化）

**送裁 D-A（先于一切）：权威归属两模式**

| | 甲：v13 唯一权威 | 乙：LoopX 治理权威，v13=执行器+账本 |
|---|---|---|
| 形状 | v13 plan/todo/settlement fold 即 goal 状态；LoopX 状态文件降为投影/适配 | LoopX 保留 goal 治理（文件或其 postgresql_v0 店）；v13 提供 session/turn 引擎+事件账本+claim/fence+收据，经适配面被两宿主调用 |
| 依据 | Phase 0 用户决定「PG 是唯一控制语义 owner」 | LoopX 语义现成（outcome_floor/reward/attention/quota 七态）；短期省一次大内化 |
| 代价 | 须把 LoopX 语义逐面落进 v13（=原 R1–R4 内化清单） | 双 goal 面并存须模式开关（被驾驶时 v13 goal_supervisor/plane 静默）；与「不建第二状态源」存在张力，须显式裁决豁免边界 |

**建议：乙起步（先接通互动，v13 立刻进槽位）、甲收敛（LoopX 语义逐面内化，原 R1–R4 清单不变）。** 两模式共享同一承载面（E1–E3），不互斥。

**E0 基座收口**：pull main（v14 已并入）+ UA 授权增补三提交（已成文计划复审落地）。任何被驾驶/自驱形态的地基。

**E1 执行器契约面（pi 槽位合同，纯 v13 侧）**：
- ingress/egress 信封适配：外部消息进（user/message 注入+首 parse 前 override 语义）、turn 驱动（run_turn 参数面）、结果出（B1 出口词+result_kind 投影）——对齐 A15–A21 信封族裁决，薄 Python 面，外部 IO 不进事务；
- 外部 agent 身份：v13 actor 模型现为 operator/human/亲缘三元，须加注册式外部执行者身份（对照 LoopX `registered_agents` fail-closed 身份面，`control_plane/agents/identity.py:26-72`）；
- gate：一条 Fake-provider 的「外部进程驱动 v13 一完整回合」e2e。

**E2 RP-CE 承载面**：worktree 绑定握手（v13 workspace_bind+latch ↔ RP-CE `AgentSessionWorktreeBinding`）、merge 处置 human gate 接线（v13 human effect ↔ RP-CE awaitingApproval 状态机，两面同为人工门已证）、五原语映射落地（survey §3.1 映射表）、oversight/observe（V11 前置阅读）。

**E3 LoopX 承载面**：agent 注册对接、lease/fence 契约对照（v13 claim/fence vs `task_lease_fence_receipt_v0`，已证同构）、writeback 投影（v13 fold → LoopX state schema，或 LoopX postgresql_v0 指向同库——注意其自建 `loopx_control_plane` schema 不读 v13 表，对接=契约适配）、quota 门转发（LoopX should-run → v13 admission）。D-A 裁决落在此期。

**I1–I4 内化清单（=原 R1–R4，甲收敛阶段，不变）**：I1 goal 配额（PC-4）、I2 咨询 lane（C4）、I3 wake+多日（V11）、I4 公平面残留（PD-H）。

### 8.3 四 Phase 的具体「调整点」对照

| Phase | 已交付（自驱形态） | 承载形态需调整
|---|---|---|
| A 控制链+真链 | run_turn/settle_once/user-message ingress | E1 信封适配+外部身份；run_turn 的 stop/override 参数面外部化 |
| B 工具/工作区 | workspace_admit/exec、worktree latch、write_scope | E2 绑定握手形状；merge 处置接 RP-CE 人工门 |
| C 单 goal 无人值守 | goal_supervisor tick、plan/todo goal 面 | **模式开关**：被 LoopX 驾驶时 replan/lease/notify 职责让渡（静默条件须裁）；UA 是两种形态共同地基 |
| D 多 goal 公平 | fair_claim/cap（内部 worker 面） | E3 外部 agent 注册接入领用；D-A 裁决后定帽的归属 |

### 8.4 新增送裁问题（并入 §7）

6. **D-A 权威归属**：乙起步+甲收敛是否接受？模式开关的静默语义（goal_supervisor 让渡条件）如何定义？
7. **E1 外部身份形状**：注册表（新政策行/表？过 R4 四问）还是复用 v13_control_operator 的扩展角色？
8. **E3 对接深度**：writeback 走 v13→LoopX 文件投影，还是 LoopX postgresql_v0 同库共存（后者双 schema 并存，须裁不违反单状态源）？


1. **R1 的 should_run v4**：block id 命名（`goal_quota`?）与 duty_cycle shadow 效果的关系——goal 配额满时应 block 还是 shadow 起步？（LoopX 对应=throttled 态，非硬门）
2. **R2 lane 与 spawn 席位**：咨询 lane 是否计入 spawn_budget 的 max_fanout/max_nonterminal？（RP-CE Oracle lane 不占 worktree；v13 llm effect 是 effect 面非会话面——倾向不计，须裁）
3. **R3 唤醒方向**：v13 wake 谁触发——goal_supervisor 轮询内嵌（现状）还是独立 wake 消费者？（RP-CE=wake coordinator 独立所有者；LoopX=scheduler 持久态）涉及 B6 表新增行。
4. **R4 活体 claim 迁移**：是否重开「禁止 CREATE OR REPLACE v13_claim」红线（Phase D §1）以堵 PD-H1？或双入口长期化+requeue 侧加帽（改动更小但仍触 control.sql）？
5. **调查产物归档**：本报告按惯例留 docs/investigations/ 不提交；三份探针卷宗是否随 R0 提交（对照既有 investigation 不入库惯例）待父定。

**已裁（2026-10-08 stage 40 追加，不删上文，不把 I1–I4 标成关闭）。** §8.2 里已被 2026-10-03 裁决覆盖的句子：D-A 裁甲，v13 是唯一权威；否决「乙起步甲收敛」；不建治理权威模式开关。§8.4 的权威归属、外部身份方向、投影/store 选择同样已裁：身份不自动获得 operator；不与 `postgresql_v0` 同库共存。2026-10-08 父计划不采用 D-A.2 的 file sink，不否认该历史裁决。stage 45 明确不交付。这些裁决不等于本 stage 已实现外部身份、wake 或投影。
