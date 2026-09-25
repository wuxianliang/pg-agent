# v13 控制面迁移调查：RP-CE 原语与 LoopX 长时设计如何落进 PostgreSQL（2026-09-25）

> 日期：2026-09-25。综合执笔：不重做探针、不改代码、不改既有文档、不 commit。
> 事实源：`prompt-exports/cpm-probe-a-v13-inventory-2026-09-25.md`（卷宗 A）、
> `cpm-probe-b-rpce-mechanisms-2026-09-25.md`（卷宗 B）、
> `cpm-probe-c-loopx-mechanisms-2026-09-25.md`（卷宗 C）。
> 先验（不重审）：`docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md`（谱系文）、
> `docs/reviews/v13-control-plane-oracle-r2-2026-09-21.md`（R2；**§1–§3 是 D1–D3 唯一条文**）、
> `docs/reviews/v13-control-plane-completeness-review-2026-09-21.md`（完备性）、
> R1 共识 1–14（R2 §0 明文保留）。设计 §6.8 与教程 ch08/ch12/ch14 只作术语对照。
> 本调查抽查了 `v13/schema/v13_core.sql`、`v13/twophase/v13_twophase.sql`、`v13/load.py`、
> `v13/` 内 `pg_advisory_xact_lock` 调用点。未进入 repoprompt-ce / loopx。

**一句话：** 五机制与 A15–A21 已裁齐；v13 代码停在最小 loop。控制面缺口是规格未落 SQL，不是缺一台新机器。落地 = 新 stage 换体把已裁条文写进函数与 gate，外加三处真新决策（D4 根会话出生、D5 墙是否抬会话态、D6 审批载荷）。不搬 LoopX 26 表，不把 RP-CE epoch 加成列。

---

## 0. 执行摘要

v13 已有的最小 loop（卷宗 A §1；16 stage 全绿。代码始于 `20cf491`，晚于规格提交 `f88f1db`，故 A15–A21 全部是「规格已裁、代码未开工」）：

| 已有 | 锚点 |
|---|---|
| effects 五 kind + fence/lease/attempt + 单活跃索引 | A #1；core:96–128 |
| events append-only、开放 type、`source_effect_id` | A #2；core:28–57 |
| claim / complete（出口 `stale/replay/accepted`） | A #1；core:267、core:300 |
| 两阶段恢复：judge 过期回收，其余 kind 进 unknown 墙 | A stage 4；`v13_requeue_stale` |
| fork + `spawn_kind` 三值 + latch 机制 | A #5；periphery |
| 预算策略行 + advance ⑤ | A #12 的预算侧；economy |
| manifest、水位七键、`decisions.epoch` 三值 | A #7 #8。此 epoch **不是** run epoch，见 §2.4 |

缺口集中在 **A15–A21 的函数与 gate 为零**（卷宗 A #6、#10、#11、#14–#17、#19、#20）。human / settle / 预算 / steer 是「运输层在、合同形状不在」。demo 驱动只跑已实现的五 kind，cancel 是进程内 `CancelFlag`，不落 `cancel/requested`（A §4）。

谱系文 §3 的五机制仍成立，且被代码强化：状态在行里，推进是 parse+advance，干预是 events INSERT，结算是 complete / refresh，高层是投影。RP-CE 是时–日读法，LoopX 是天–周读法（谱系文 §2），不是第二套运行时。完备性 §1.1 的 turn 读法已闭合，本报告不重开 Codex。

**本次落地明确不做：** 新表、新列、`effects.status` 扩词、`v13_agent_run` 总调度、LoopX 的 `quota_spends` / `command_receipts` / `outbox` / `leases`、把 `decisions.epoch` 当成 run generation。

---

## 1. 先验压缩（引用，不重审）

映射表里「新裁 = 否」的依据。实施时撞上这些条文，停下来对照，不要用「迁移需要」改裁。

| 条文 | 一句话 | 出处 |
|---|---|---|
| 零新表零新列 | 信封住 `artifacts.kind` + schema + `tools.input_schema` | R1.1；R2 §0 |
| D1 / A15 | `result_kind ∈ {progress,finish,wait,reject}` 是唯一分派键；LoopX 六值只作可空 `delivery_kind`，路由不读 | R2 §1 |
| 续跑 | 新 `effect_id` + 新冻结 request；attempt 只重试同一 `request_hash` | R1.2；R2 §5 A15 |
| 审批两段 | succeeded + `wait`/`wait_reason=approval` → 恰一个 human → 续跑。`needs_approval` 永不是 status，也不得作 settle 参数 | R1.3；R2 §1.2；ch12 |
| D2 / A17 | `spawn_subsession` = `tools` 行 `kind=sql` + guard 具名 VOLATILE 例外 + DEFINER + 两参咨询锁。路径 B（worker 窗口 spawn）否决 | R2 §2 |
| 不预扣 | spawn 只做 reserved **准入**；不在 spawn 时扣 `turn_no` | R1.11（R2 保留） |
| 子唤醒 | 子 closeout **不得在持子行锁的事务里写父事件**。唤醒 = 提交后调用者 parse+advance，或扫地僧 `v13_recover_idle`。子终态行是真相，通知只是提示 | R1.7。R2 §0 只复述锁半句，唤醒半句仍在 |
| A16 | `session/completed\|failed\|cancelled` + 对账收据，与终态、预算终态同事务；前置 fail-closed；closeout 不再扣预算 | R2 §5；ch05.3 |
| A18 | worker 第四务（控制订阅）；`interruptible` 是 allowlist 键；核心不杀进程；mutating 中断 → unknown | R2 §5；ch08/ch12 |
| A19 | worktree = latch `name='worktree'` + binding artifact；prepare/merge/release 走 FS effect；子不继承；无 binding 拒 claim | R2 §5；ch08/ch14 |
| A20 / D3 | 证据/动作分离；单一 `goal/override`；explore 首版 = 同会话 llm+只读，不 spawn | R2 §3 |
| A21 | `v_goal_tree(root)` 是参数化 STABLE SRF，不是 VIEW、不是物化表 | R2 §5；B16 |
| 动作闭集 | 仍是 finish/reject/human/sql/tool/llm。信封枚举不是动词 | R2 §4；ch04 |

教程已经把这些写成合同，代码没跟上：ch08 三步+第四务，ch12 `v13_resolve_unknown` 与粘性 cancel，ch14 spawn 与 `v13_fork` 同一 primitive，ch07 `artifacts.kind` 词表。设计 §6.8 是交叉引用，不是新平面。

---

## 2. 原语级映射总表

`新裁 = 否` 表示不许另开设计。`D4–D6` 见 §6。编号续的是**控制面 R2 的 D1–D3**，不是文件面 `repoprompt-native-on-v13-feasibility-v2` 里的 D1–D5。

**同名警告：** `decisions.epoch ∈ {pre-bind, pre-finalize, post-execute}`（卷宗 A #7，stage 6，INSERT 期固化）不是 RP-CE 的 run epoch（卷宗 B §1 `DomainAgentRunTurnEpoch`）。禁止复用该列，禁止为 run generation 加列。

### 2.1 RP-CE 五原语

谱系文 §4：外部 harness 以 wrapper 为主档，五原语是已有动词换名。代码把这句话收窄为：运输层在，合同层不在。

| 原语 | 源 | v13 现状 | PG 落地 | 新裁 |
|---|---|---|---|---|
| `startOrResume` | B §1：`start` 总是新会话（L448 拒传入 session_id）。过期句柄用同 session 的 `steer` 续（B §5 `agentRunExpiredHandleRecoveryNote`） | 根 INSERT 今天可行（§3 抽查）。子会话可读不可推进 turn（A #5） | **根、续跑、子会话三者拆开。** 根 = 新 sessions 行（D4；P2 才封唯一写路径）。harness 续跑 = 同一 session 的**新 effect_id**（A15），不是 `start`，也不是新会话。lease 住已有 `lease_until` | 根见 D4；续跑否 |
| `sendUserMessage` / `steer` | B §1 op=steer；epoch `transitionKind=steering` | A #13 部分：`user/message` 推 `max_event_seq`，在途 advance 步 0 返 `stale` | 开放事件 `steer/injected`（ch01 已登记，代码零生产者）。claimed 期间不改已冻结 request（R1.9）。水位 = 已实现的 `v13_probe` 七键（A #8） | 否 |
| `interruptTurn` | B §4 `executeCancel` L1174–1216：先拒 expired/terminal。生命周期在 domain store，不在 view model | A #10 未实现。`cancelled` 只是枚举，零生产者。demo 旗不落事件 | `v13_cancel` 写 `cancel/requested`。粘性：收 ready，不同步改 claimed（ch12）。进程打断 = A18 第四务；SQL 不杀进程 | 否 |
| `respondToPermissionRequest` | B §1 Interaction；respond 必须等于当前 pending id，否则带回实际 id（L10714–10720） | A #3/#11 未实现。`kind=human` 与六个路由出口已有；`interaction_ref` 零命中 | A15 两段。id 不匹配则拒，错误里带回当前 ref。不住新表 | 载荷见 D6 |
| `shutdown` | B §3：摘 records、waiter 全部 `cancelled`；无 handler 写 dormant，否则 interrupted | 租约回收已实现（`v13_requeue_stale` / `v13_renew_lease`，A stage 4） | 不建 dormant/interrupted 列。worker 死 = lease 过期 → judge 回收或 unknown 墙。协作停 = `v13_cancel`。5s drain 是进程内 deadline，不进 schema | 否 |

### 2.2 `agent_run` 六 op

卷宗 B §1：op ∈ `start|poll|wait|cancel|steer|respond`（`MCPAgentControlToolProvider.swift` L180–266），缺省 wait。**不建 `v13_agent_run(op)`**——那是第二个推进函数（谱系文 §3.2 的反面）。

| op | 源 | 现状 | PG 落地 | 新裁 |
|---|---|---|---|---|
| start | §2.1。worktree 参数仅 start（B L193–201） | worktree 名 latch 零使用（A #17） | 出生与工作面分开。prepare/merge/release 是 FS effect（A19，P3）。子不继承 latch | 根路径 D4；worktree 否 |
| poll | timeout=0；`session_ids` 先全量授权再返回任何快照（B §1） | 无快照函数；行可读 | STABLE 投影，读 sessions/effects/events。不建快照表。多 id = 驱动循环 | 否 |
| wait | 第一个 interesting 胜出；判定键是 cursor=registration+epoch（B §1、§4） | demo 轮询（A §4） | 驱动轮询或 LISTEN。丢唤醒不靠 waiter 表，靠 `v13_recover_idle`（R1.7；`v13/` 检索零命中）。完备性 §1.3 已判语法糖 | 否 |
| cancel | §2.1 | A #10 | `v13_cancel`。子树扇出是 P3；P1 只做单会话 | 否 |
| steer | `shouldWait` = 显式 wait 或带 timeout（B L1333–1345） | A #13 | 同 §2.1。`wait=false` 的警告字段是 MCP 响应形状，不进事件 | 否 |
| respond | 顶层只接受标量 `response`，另有 answers/skip/amendment（B payload 节） | A #11 | human 的 `v13_complete`，匹配 `interaction_ref` | D6 |

`agent_manage` / `agent_session_link` 不进第一期。`get_log` / `extract_handoff` = 读 events + A15 `control.handoff`（稳定 `delivery_id`，不采 XML，transcript 只存 hash，R1.4）。`cleanup_sessions` 的墓碑删除不迁：停会话是 cancel，不删行。link actor「永不持久化」（B §4）保持不持久化；其「`indeterminate` 优先于 receipt」只吸收进 §4，不建 send 账本表。

### 2.3 审批、恢复句柄、compaction

| 项 | 源 | 现状 | PG 落地 | 新裁 |
|---|---|---|---|---|
| 审批流 | B §1：kind ∈ instruction/question/user_input/approval/hook_approval/mcp_elicitation | A #11 零命中 | 六种 kind 折叠进 `wait_reason=approval` + artifact，不加 effect status。`delivery_kind=USER_ACTION_REQUIRED` 必须同时 wait+approval+ref，否则 complete 拒（R2 §1.2） | D6 |
| 恢复句柄 | B §1 注册四元组 + epoch；B §4 `publishTerminal` 按 commitID 重放；B §5 `indeterminate_after_commit` | fence/lease/attempt 已实现（A #1）。墙无关闭入口（A stage 4） | 句柄 = `(session_id, effect_id, fence)`，不是新列。细节 §4 | 会话态见 D5；其余否 |
| compaction | B §3 frontier = version + frozenPrefixTurnCount + lastFrozenTurnID；`get_log` **故意丢弃** frontier | chunks（stage 7）+ memory watermark（stage 11）已实现（A §1） | 不建 frontier 表。权威是 events + chunks。压缩叙述不是 transcript。与「get_log 不掺压缩叙述」同纪律 | 否 |

### 2.4 三套运行枚举 → 已有两列

卷宗 B §1：`AgentSessionRunState`（8 值）、snapshot `Status`（6 值）、durable state（4 值）不是 1:1，`waitingFor*` 三者折叠成 `waiting_for_input`。v13 已有 `sessions.status` 六值（core:14–15）与 `effects.status` 六值（core:112–113）。再加一列 = 违反零新列。

| RP-CE | 投影读法（不落新列） |
|---|---|
| `idle` | 无 ready/claimed，session `ready` |
| `running` | 存在 claimed |
| `waitingForUser/Question/Approval` | 与 B 的 snapshot 一样折叠。落点是 `result_kind=wait` 或 session `waiting` + human。三层 wait 已裁（R2 §1.2；ch05），不要合成一个 status |
| `completed/failed/cancelled` | session 同名终态。effect 终态是另一列 |
| snapshot `expired` | **不**进 sessions.status。RP-CE 的 300s TTL 是进程内快照。v13 = lease 过期（已实现）+ 同 session 新 effect 续（A15） |
| durable `dormant/active/interrupted/terminal` | 不建。v13 没有「进程活着」可声称：行在即活，lease 在即有主。interrupted = 墙或 cancel 在途 |

`blocked_unknown` 已在闭集里，生产者未写（A #19；core:16–18 自注归 ch12）。ch12 草图只 UPDATE effects。这是 D5。

### 2.5 LoopX settlement 四步

源：卷宗 C §2。四步在 `effect_program.py:159-165`：`VALIDATION, DURABLE_WRITEBACK, QUOTA_SPEND, TERMINAL_CLOSEOUT`。身份 = `(goal_id, agent_id, todo_id XOR replan_obligation_id, turn_instance_id)` → `effect_id`。XOR 两者都有或都无即 RuntimeError。

| 步 | 源 | 现状 | PG 落地 | 新裁 |
|---|---|---|---|---|
| VALIDATION | TS fail-closed；未知字段即 error；`turn_key` 必须等于 plan（C §5） | llm 空文本降级 failed 已在 complete（core:355–365，本调查抽查）。harness 信封校验无 | complete 换体：接受 `succeeded` 前校验 `harness_result`。原始输出只进 `candidate_kind`，不授权（R2 §1.1） | 否 |
| DURABLE_WRITEBACK | 先 journal `prepared` 再调 provider；回调须 `{ok, appended}`（C §2） | complete 同事务写 status + `effect_done` + `tool/result` 或 `llm/message`（core:370–390）。context settle 是 `v13_refresh_context`（A #4，部分） | 不把 journal 文件搬成表。`prepared` = 已 claimed 且 fence 已发。崩溃在 complete 前 = 墙（§4），不是重执行 | 否 |
| QUOTA_SPEND | 只在 validated writeback 之后；digest 乐观并发；void 按 bucket 夹减，不为负（C §2、§4） | A #12 部分。扣减在 **advance ⑤**，不在 complete。spawn 准入未实现 | R1.11：spawn 不改 `turn_no`。花费只在各会话 advance ⑤。closeout 封账不二次扣（A16）。窗口 void 不建表（§3） | 否。并读见 §8 |
| TERMINAL_CLOSEOUT | 仅完成且 `no_followup`；失败不得当成未花费（C §2，`docs/architecture.md:105-112`） | A #16 未实现。回合终结事件只有 `turn/end` | A16 三事件 + 收据 `spent / produced hashes / children / unconsumed / state_hash` + `closeout/inbox_residual`。同事务。前置 active=0、unknown=0、pending human=0。子会话只写自己的日志（R1.7） | 否 |

谱系文 §3.4「effect 终态化 + 预算同事务扣减 = QUOTA_SPEND」对照代码要收窄，不是改裁：**扣减与建工作同事务（advance ⑤），不与 complete 同事务。** complete 是 writeback，closeout 是封账。三笔三次事务，靠收据与墙对齐，不靠合成一个大事务。

进度机 `identity_required → writeback_required → … → settled`（C `docs/quota-allocation.md:132-150`）是查询投影，不是 status 列。可观察的分裂只有两处，出口都已指定：complete 前崩溃 = 墙；子已终结父未醒 = `v13_recover_idle`（未实现）。A16 禁止「已终结但收据缺失」。

### 2.6 quota、attention、adapter 三档

| 项 | 源 | 现状 | PG 落地 | 新裁 |
|---|---|---|---|---|
| quota 账本 | C §4：资格 ≠ 奖励 ≠ 审批；无负债；void 是 append-only；`spent_slots` 禁止做成可 UPDATE 计数器（C 末条 ③） | 策略行 + 可 UPDATE 的 `turn_no`（core:20）+ 同事务检查。无 void 事件 | **不改 `turn_no`。** R1.11 已指定它是花费计数；A16 收据是封账副本。`human_reward` 保持开放事件（ch13），与审批分开。void/窗口见 §3 | 否 |
| attention | C §3：只读、无副作用；权威是逐 goal `should-run`；`next_automatic_turn` 纯 advisory，执行前必须再问一次 | A #15 未实现 | A21 `v_goal_tree(root)`。`attention_rank` 是输出列不是表列（R1：human > unknown > cancel > duty_cycle=0 > 其余按最近材料事件）。投影不授权（R1.5）。资格仍是 `quota.should_run`，advance 读它。pg_cron 是扫地僧不是节拍器（ch13） | 否 |
| `in_loop` | C §5：worker 在自己 loop 里调控制面；dsh 自述不写 LoopX 状态 | loop 就在 PG。sql 快路 = 库内 in_loop（A stage 3 P4a） | 保持。外部 harness 不得 in_loop 写自己的状态（谱系文 §5） | 否 |
| `wrapper` | C §5：能包 command/prompt/workspace，不能改内部 loop | claim 的 handler 过滤在，第四务不在 | **主档**（谱系文 §4）。harness = `tools.handler`，不是 `effects.kind` 新值（闭集五值，core:99–100）。结果住 `artifacts.kind=harness_result` | 否 |
| `passive_posthoc` | C §5：不能启动也不能拦截，只事后分类 | 无 | **不建。** 触发：出现 v13 没启动、只能看 diff/log 的执行者。提前做 = 第二个真相源的入口 | 否（YAGNI） |

---

## 3. 与 LoopX PG 蓝图的对表

源：卷宗 C 附节对 `loopx/docs/LoopX on Pgembed.md` 的摘要（26 表 / 6 schema）。本调查未重读该文。蓝图是对照物，不是施工图。v11 与 ch13 已拒六层控制面表；R1.1 零新表零新列。整包 **不迁**。

| 蓝图物件 | 判定 | 说明 |
|---|---|---|
| `leases.fencing_token` + `one_active_lease_per_todo` | **证实，不吸收表** | 已有 `effects.fence`（claim/requeue 递增；complete CAS 失配 `stale`，core:321–325）+ `ux_v13_effects_single_active`（core:128）。a2 把 fence+1，死 worker 的 complete 得 `stale`。C 末条说 fencing_token「取代 effect_id」——**不采纳取代**。`effect_id` 是逻辑身份（`v13_effect_id` = sid:last_user_seq:cycle:kind:req_hash，A core:175）；fence 是运输令牌。续跑改 request ⇒ 新 id（A15），与 fence 正交 |
| `command_receipts` | **语义证实，表冲突** | 幂等已有三处：`UNIQUE (session_id, idempotency_key)`（core:124）；终态 complete 返回 `replay` 且不写第二条事件（core:329–334）；A17 同 tool_call id 重放同一 child。A16 收据是事件载荷。C 末条 ②「receipt 与 effect 必须分表」与零新表、与 A16「同事务、无中间态」冲突。崩溃分裂由墙承担。**不建表** |
| `quota_spends` + append-only 窗口 | **纪律证实，表冲突** | 「不在执行前预扣」= R1.11，已裁。张力：C 要求花费计数永不可 UPDATE；v13 的 `turn_no` 就是可 UPDATE 计数器，且 R1.11 指定它为花费点。**不改裁、不建表。** 若将来要「过期 slot 让可见总数下降、已追加事件不撤回」，走开放事件 `quota/spent` + `quota/voided` 与 STABLE 窗口函数（仍零新表）。触发前做 = 第二套账本 |
| `outbox` | **不吸收** | 唤醒已有 `pgmq` `v13_work`（A #18，非 v6 bridge）。父唤醒是扫地僧重入（R1.7），不是通知行。无外部 webhook 消费者，不预建 |
| kernel/reader/worker；Agent 无库账号 | **证实原则，不吸收四角色名** | 已有 NOLOGIN 的 recall/resolve/route + 双登录池 + `v13_worker`（A core:816–842）。看板只读可以是对 SRF 的 GRANT，不是表。张力：蓝图 worker 只碰 scheduler/outbox；v13 worker 调 complete 写 effect 终态。这是 ch08「申报不裁决」，**不把 worker 缩成只写出箱** |
| `execute_command` 14 步 | **证实唯一推进，不建第二入口** | 认证/水位/幂等/锁/转移/事件/收据分别已有角色、`v13_probe`、complete CAS、session→effect 锁序、advance、events、A16。再包一层 = 第三个循环 |
| `goal_versions` / `todos` / `gates` / `monitors` / `schedules` | **不吸收** | goal=sessions；todo=子会话；gate=thresholds+human；monitor=扫地僧；schedule=pg_cron 行。ch13 的两列（`parent_session_id`、`parent_cutoff_seq`，core:23–24）已经付过 | 

咨询锁注记（本调查抽查，非卷宗）：v13 全树 `pg_advisory_xact_lock` 都是**一参**（`v13_lock_key` 返回 bigint，resolve:410–416；mgraph 用 `v13_lock_key(sid,'mgraph-build')`）。chunks 的 `hashtextextended(k, seed)` 第二参是哈希种子，**不是**锁类号。R2 §2.3 要求 spawn 用**两参** `pg_advisory_xact_lock(<类号>, hashtext(root_session_id))`。一参与两参锁空间不相交，故不与 recall/mgraph 互斥。类号在两参空间内写成具名常量即可，不是用户裁决。仅 spawn 准入取此锁；closeout/recover 不得取。

---

## 4. 恢复语义

三套说法保护同一条禁令：**越过提交边界之后，回复丢了，也不许自动重执行。**

| 说法 | 源 | v13 对应 | 关闭 |
|---|---|---|---|
| epoch CAS | B §4 `beginEpoch`：epoch 不符即 `stale`；换 epoch 把旧 waiter 摘掉 | complete 的 fence CAS → `stale`（core:321–325）。「换 epoch」= 新 effect_id 或 fence+1，不是 generation 列。旧 fence 的 complete 失败，等价于 waiter 被摘 | 失配即拒绝，无关闭动作 |
| `publishTerminal` | B §4 L420–533：同 commitID 重放 `accepted`；不同 commitID → `different_commit_already_published` | 已终态（含 unknown）complete 返回 `replay`，不写第二条事件（core:329–334） | closeout 同样：已终态则返回已有 `session/*` 事件，禁止再 append |
| `indeterminate_after_commit` | B §5：commit 已开始则先上报 indeterminate，journal `.committing` **绝不自动重执行** | 非 judge 的 lease 过期 → `unknown` 且 fence+1（twophase a2）。worker 也可 `complete(...,'unknown')`（A18）。两者都是**建墙**。complete 不能拆墙 | 只有 `v13_resolve_unknown` |
| `resolve_prepared` | C §2：`absent` 可执行；`committed` 用 payload；`unknown` fail-closed，不重执行 | `absent`→`not_happened`；`committed`→`confirmed`（payload_hash 必须对上已落结果）；观察仍 unknown → **不要调用** | 同上 |
| `settlement_owed` | C §2：有 run 无 receipt = 未完成；补收据不再扣；恢复地址是 `turn_instance_id`，禁止按 recency 挑 | 投影，不落列。键是 `effect_id`。closeout 回滚后，先前 advance 已提交的 `turn_no` 保持，重试只封账 | closeout 重入；不新扣 |
| 续跑新 effect_id | A15 / R1.2 | 审批或 steer 改变 request ⇒ `request_hash` 变 ⇒ `v13_effect_id` 自然是新 uuid。同 request 的运输重试复用 id、attempt 继续（ch12 练习 2）。身份函数已经把两者分开，不要加列来「区分」 | advance 建新行，不是 resolve |

### 4.1 unknown 墙的关闭入口

抽查与卷宗 A 一致：`v13_requeue_stale` 把非 judge 过期行写成 `unknown` 并 `fence+1`，不改 `sessions.status`，没有关闭函数。`v13_complete` 看见 `unknown` 就 `replay`。ch12 规定了形状，代码未写。关闭入口零新列，resolution 闭集不扩：

```text
v13_resolve_unknown(p_effect uuid, p_resolution text, p_evidence jsonb) → text
  resolution ∈ {confirmed, rolled_back, not_happened}     -- ch12，不增第四值
  调用者：控制角色。不是 worker 自动路径，不是 requeue，不是 cancel。
  拒绝（行与事件零变化）：
    status ≠ unknown
    evidence 缺失或非 object
    resolution 与 evidence.observation 不一致
      confirmed    要求 observation=committed，且 payload_hash 对得上已落结果
      not_happened 要求 observation=absent
      rolled_back  要求 compensation_ref
    observation=unknown          -- LoopX 的 fail-closed：不关闭
  接受（同事务）：
    confirmed → succeeded；另两值 → failed          -- ch12 CASE
    append unknown_resolved（resolution + evidence 哈希，不复制正文）
    不入队、不调外部 IO、不自行建重试 effect
  重试权在上层：not_happened 且外部计数仍 ≤1 时，advance 按同一逻辑键重挂
    （effect_id 不变，attempt 继续，ch12 练习 2）。不是本函数的副作用。
  禁止：
    requeue 关闭墙（它只建墙）
    cancel 把 unknown 改成 cancelled（ch12：不掩埋）
    complete 复活 unknown（core:329–334 已执法，换体不得打开）
    按「最近一条 unknown」挑选（必须传入 effect_id；多条命中即拒，对齐 C 的 ValueError）
```

会话态是否在建墙时置 `blocked_unknown`、在最后一条 unknown 被 resolve 后清回 `waiting`，是 D5。P1 只动 effect 行（与 ch12 草图一致）。D5 拍板前不要写 sessions UPDATE。

sql 档不走这条墙：A17 `mutating=false`，崩溃即回滚（R2 §2.4）。judge 过期走 a1/a1'（回收或 `lease_exhausted`），不进墙——判断无外部副作用。不要把 judge 的 failed 改道成 resolve_unknown。

---

## 5. 分期路线

依赖序，不是 R2 §9 的文档修订序（docs 已落在 `f88f1db`）。新 SQL **只追加** `SQL_LOAD_ORDER`（现 16 项，末项 `mgraph_assembly`）。后 stage `CREATE OR REPLACE` 换体，**不改** stage 1–16 的文件，否则既有 gate 的加载前缀会变。新行为的 gate 跑在新 stage 上，并按 AGENTS.md 回归此前全部 stage。测试用 Fake，不调真实 provider。

### P1 · 单会话控制动词（最小可落地）

不依赖 D4。D5 不挡 effect 级关闭。D6 若选扩充载荷，须在冻结校验 schema 前拍板；按 §6 倾向起草则可开工。

| | |
|---|---|
| 交付 | A15 校验（四值、wait 词表、wake、同 logical turn material ≤1、progress+repair 零 spend）；A16 无子会话 closeout（三事件+收据+同事务+二次调用重放）；`v13_resolve_unknown`；单会话 `v13_cancel`（粘性，不扇出）；steer 断言（claimed 期间 request 不变）；审批两段（恰一个 human，续跑新 effect_id，status 闭集不变） |
| stage | 17 `v13/control/v13_control.sql`。换体 `v13_complete`、`v13_advance`。事件 type 零 DDL（开放词表，core:37） |
| 前置 | 代码树零 `CREATE EXTENSION pg_jsonschema`。第一步装扩展探针；装不上就停，不要用临时 CHECK 替代 R2 §1.2 |
| gate | `uv run python v13/control/test_control.py`，加 stage 1–16 回归。名沿用已裁：G-ctx10-delivery / wait-lexicon / wake / spend；G-closeout 前置；G4「只有 resolve_unknown 能离开 unknown」 |
| 判据 | 乱填 `delivery_kind` 不改变是否建 effect；缺 wake 则拒且零事件；closeout 回滚则无 `session/completed`；二次 closeout 不追加第二条终结事件；cancel 不改 unknown；审批全程 status 无审批词；1–16 仍绿 |

P1 不做：spawn、唯一写路径、子树扇出、worktree、triage、quota 新事件、demo 接线（gitignored，不进 gate）。

### P2 · spawn + 目标树 + 扫地僧

依赖 D4，依赖 P1 的 closeout（子终态是 closeout，不是新 status）。

| | |
|---|---|
| 交付 | `tools` 行 `spawn_subsession, kind=sql, mutating=false`；`v13_spawn_subsession` DEFINER，与 `v13_fork` 同一 primitive；guard 换体，例外条件全用 R2 §2.2，不许「有 write_targets 就放行」；两参咨询锁只在准入路径；准入是查询聚合（非终态子孙 `max_turns` 之和 + requested ≤ 剩余），**不加 `sessions.reserved` 列**（R2：DDL 无此列，单语句 CAS 作废）；`v_goal_tree(root)`；`v13_recover_idle` 含「子齐父未验收」与未消费 repair/replan；子 closeout 事务内零父事件 |
| stage | 18，只追加 |
| gate | G-sql-write-closed、G-spawn-unique-writer、G-spawn-fanout、G-ctx1-spawn（持锁毫秒级；超限改函数，不改回队列） |
| 判据 | 名单外 INSERT sessions 拒；N 个 tool_call 要么 N 子要么零子；并发 sibling 无超售；spawn 前后父 `turn_no` 不变；子 closeout 后一次 recover 把父扫进验收，第二次零新 effect |

### P3 · cancel 传导与 worktree

R1.14：任何 mutating 外部 harness 启用前必须完成。

| | |
|---|---|
| 交付 | `allowlist.interruptible ∈ {required, best_effort, unsupported}`（零新列）；`v13_cancel` 同事务扇出，祖先优先、同层 `session_id` 升序（ch12）；fake 第四务。A19：latch + `worktree_binding` artifact；prepare/merge/release = FS effect；子不复制；无 binding 拒 claim。prefix identity 默认排除 worktree |
| stage | 19 |
| gate | G6 增断言（ch08 已列）。SQL 中无 `pg_terminate_backend` |
| 判据 | required 档收到 `cancel/requested` 后 settle cancelled；unsupported 跑完被粘性吸收；mutating 中断 settle unknown，且 cancel 不能改掉它；无 binding 零执行；终态子孙零扇出 |

### P4 · triage（A20）

10a 不依赖树，但 R2 §9 禁止 10b 早于 spawn。同 stage 落地，10b 在 P2 之后才有实值。null 树字段不点火（R2 §3.1）。

| | |
|---|---|
| 交付 | 消费 `goal/override`（ch01 已登记）；阶梯 1–7（R2 §3.2）；explore = 同会话 llm+只读，不占 depth/reserved；Jev 只产 `Choice{direct,decompose,human}` |
| stage | 20，不得早于 18 |
| gate | G-triage-action-closed、G-triage-explore-depth、G-triage-evidence-hash、G-triage-10a-null-tree |
| 判据 | `thresholds.action` 仍六值；override 打穿预算 → 零 child + human；已探索仍 review → human；根上无 Jev 证据不得 SQL-direct |

---

## 6. 待用户裁决（控制面 D4–D6）

只列会分叉、且 A15–A21 没写死的点。倾向不是裁决。

### D4 · 根会话的 INSERT 入口（挡 P2，不挡 P1）

A17 闭集 = `{v13_fork, v13_spawn_subsession}`，字面是「任何角色 INSERT sessions 被拒」（R2 §2.5）。`start` 生的是根，没有 parent，不是 spawn。今天没有禁 INSERT 的触发器（抽查：现有触发器是 policy 列、context 指针、fork 列 UPDATE）。P2 若按字面封死，根会话无法出生。

| 选项 | 内容 |
|---|---|
| A（倾向） | 闭集加 `v13_open_session`：DEFINER，只插 `parent_session_id IS NULL`，不复制 latch，不占 reserved。扩员走 R2 §2.2 已有程序（改 guard 源码 + 设计修订 + gate 同发），不是 `UPDATE tools`。补的是 start 的具名入口，不是推翻唯一写路径 |
| B | 唯一写路径只约束 route/worker/模型角色，bootstrap 可直插。与「任何角色」字面冲突，须复访改字面 |
| C | 根也走 `v13_fork`（parent 空）。扭曲 fork（要 cutoff 与 `spawn_kind`）。不倾向 |

### D5 · `blocked_unknown` 谁来写（不挡 P1 的 effect 级关闭）

枚举在 core:14–15，注释把生产者指给 ch12；ch12 草图只改 effects。卷宗 A #19：零生产者。

| 选项 | 内容 |
|---|---|
| A（倾向） | a2 建墙的同一事务把 session 置 `blocked_unknown`（已是则不变）。resolve 在该 session 再无 unknown 时清回 `waiting`。cancel / requeue / complete 不得清。closeout 前置 unknown=0 保持 |
| B | 不用这个枚举。unknown 只住 effect 行，session 保持 `waiting`。死值以后再删（删 = 改 CHECK，另一次迁移） |

倾向 A，因为注释已经承诺有生产者；死值会让 poll 与「会话等裁决」对不上。P1 不要抢跑写这句 UPDATE。

### D6 · 审批载荷闭集（P1 schema 冻结前）

A15 写死了 `interaction_ref` 与两段接线，没写 RP-CE 的 options/fields/skip/amendment/elicitation 进不进 v1。

| 选项 | 内容 |
|---|---|
| A（倾向） | v1 = `interaction_ref` + 标量 `response` + 可选 `answers` jsonb + `skip` bool，`schema_version=1`。六种 kind 折叠进 artifact。amendment/elicitation 等版本门 |
| B | v1 即卷宗 B 的 Interaction 全结构 |

倾向 A：两段接线不依赖全结构。选 B 也不推翻 A15，只是 v1 更宽。

### 明确不新裁

- 不建 `v13_agent_run`。六 op 是驱动组合。
- 不把「caller 必须是直接父、失败消息不可区分」（B §2）收进 P1。触发：第二个 principal，或 MCP agent-originated caller。
- 不建 `passive_posthoc`。触发见 §2.6。
- 不建 quota 表。窗口 void 的触发见 §3。
- 不复访 D1/D2/D3、不预扣、closeout 不二次扣、路径 B、六值进路由。

---

## 7. 证据等级

| 材料 | 等级 | 说明 |
|---|---|---|
| 卷宗 A/B/C 的 file:line | 源码级（探针） | 本调查未重进两个 root。锚点以卷宗为准 |
| 本调查抽查的 v13 SQL | 源码级 | complete 对 unknown 返回 replay（core:329–334）；requeue a2 不改 session；sessions 触发器不是禁 INSERT；advisory lock 全树一参；`pg_jsonschema` 与 `v13_recover_idle` 在 `v13/` 零命中；`SQL_LOAD_ORDER` 16 项 |
| R2 §1–§3、§5 的 A15–A21、R1.1–14 | 已裁条文 | 不是新证据。冲突只标注 |
| 谱系文 §2–§5、完备性 §1 | 2026-09-21 的设计判断 | 沿用。§3.4 的 spend 落点按代码收窄到 advance ⑤ |
| §2 映射、§4 关闭入口、§5 分期、§6 倾向 | 本调查的判断 | 落地列都能指向上两行。指不上的没写 |
| 卷宗 C 附节 26 表 | 探针摘要级 | 未重读蓝图全文。卷宗没列的列，本报告不发明 |

---

## 8. 不确定与边界

1. **R1.11「spent 在 advance/closeout 递增」与 A16「closeout 不再扣」。** 并读：扣减只在 advance ⑤；closeout 把已提交的 `turn_no` 抄进收据，与 session 终态同事务封死，不第二次扣。若并读被拒，应复访 A16，不要各扣一次。这不是 D4–D6——两句可以同时满足——但是最容易被实现者读炸的一句。
2. **epoch 与 fence 行为等价**是映射判断，不是两边源码的联合证明。已证明的只有：v13 失配出口是 `stale`/`replay`，且没有 epoch 列。
3. **C 末条「fencing_token 取代 effect_id」**与 A15 冲突。本报告取 A15，张力写在 §3。
4. **ch12 正文与 core 注释对 `blocked_unknown` 不一致。** 已列为 D5，不代裁。
5. **未覆盖：** Codex 内层；`agent_manage` 全 op 的字段级对照；蓝图里卷宗 C 没展开的列；目标机能否 `CREATE EXTENSION pg_jsonschema`（未跑）。
6. **边界：** 未改 v13 代码与既有文档；未 commit；未进入 repoprompt-ce / loopx。
