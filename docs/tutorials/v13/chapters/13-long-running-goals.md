# 第 13 章：长时运行与目标树——loopx 映射

> 前置：第 1、4、5 章。产出：`parent_session_id` 缝 + quota 策略行 + pg_cron 扫地僧（G7 部分）。
> 对照上游：loopx（`/Users/wxl/Projects/loopx-nooa-agent-session-layer`，
> 长时运行 agent 的控制面）——概念映射，不搬它的表。
> 设计对照：`docs/designs/v13-context-on-pg.md` §6.2 触点 6、§8 pg_cron、§12 YAGNI。

## 13.1 这一章要做什么

到此为止的 v13 是一个**单会话 turn 引擎**。长时运行工作（loopx 的领域）多出四件事：
目标要活过任何一次执行；计算配额要管「下一个工作段给不给跑」；
todo/handoff 要有结构；人的 reward 要挂在确切的 run 上。

v13 的余量设计：**余量 = 身份缝 + 开放类型 + 策略数据，不预建机器。**

LoopX 概念 → v13 原语的完整映射（逐条零或一列成本）：

| LoopX 概念 | v13 落点 | 新增 |
|---|---|---|
| goal（持久目标，活过线程重载） | `sessions` 控制行——「会话是行不是连接」（v3 裁决） | 0 |
| bounded turn / 一个已验证工作段 | `turn_no/max_turns`；更深的切片=子会话 | 1 列 |
| executor（Codex/Claude Code，短命、provider 中立） | 某个 handler 的 worker（`handler='claude-code'`） | 0 |
| compute quota（duty cycle，决定下一个工作段） | **策略行**；advance 同事务读它（第 5 章⑤纪律） | 纪律 |
| human_reward overlay `{recorded_at, decision, reward, reason_summary, follow_up}` | **开放事件类型** + `source_effect_id`（挂确切 run） | 0 |
| todos / handoff | 子会话（`parent_session_id`）+ 类型化事件 | 1 列 |
| gates | thresholds + human 平面（第 4、12 章） | 0 |
| evidence | artifacts（第 7 章） | 0 |
| scheduler tick | **pg_cron 扫地僧**（13.2）：丢通知 / 过期租约 / 投影构建 / verify_index。**不是节拍器**——turn 推进仍靠 settle | 0（调度是行） |
| dashboard（投影） | 视图（第 15 章） | 0 |
| 预取排序（触点 6） | **YAGNI 台账**（13.3）。触发：长目标树落地 **且** 下一查询可预测 | 0（不建） |

**总预付成本 = 2 个可空列（`parent_session_id`、`parent_cutoff_seq`）+ 2 条纪律。**
这两列现在就定（第 1 章 DDL 已带），因为它们定的是**身份与预算归属语义**
——子会话预算从哪继承、fork 边界在哪——后补会漂。
pg_cron 进核心是因为它替代了仓库否则要自己写的扫描恢复；预取排序不进——
还没有「下一查询可预测」的证据。

## 13.2 tick = pg_cron 扫地僧，不是节拍器

quota 仍是数据，与 reward / 审批分离（loopx 裁决）：

```sql
-- 策略行。advance 的预算检查读 (policy_name, version)：
-- 插一行 duty_cycle=0.5，同一个 advance 函数的资格即变，零代码改动。
INSERT INTO thresholds(policy_name:'scheduler', policy_version:1, signal:'quota.should_run', ...);
```

**cron 间隔不是 duty_cycle。** quota 决定这个 goal 有没有资格被推进；
settle 决定现在推进。pg_cron 的 job 是一行调度，跑的是扫地，不是心跳：

```sql
-- 扫地僧。不是 SELECT v13_advance(sid) FROM sessions。
SELECT cron.schedule('v13-sweep-stale', '*/5 * * * *',
  $$SELECT v13_requeue_stale(100);$$);          -- 过期租约 / 丢通知 → 重入队
SELECT cron.schedule('v13-sweep-recover', '*/5 * * * *',
  $$SELECT v13_recover_idle(100);$$);           -- 非终态、无活跃 effect、有未消费事件
                                               -- → 幂等 parse+advance（第 5 章第三来源）
SELECT cron.schedule('v13-sweep-transcript', '*/5 * * * *',
  $$SELECT v13_rebuild_transcript_chunks(100);$$);  -- 记忆逐字层：tick 批量构建，水印谓词
SELECT cron.schedule('v13-verify-index', '15 3 * * *',
  $$SELECT v13_verify_chunk_indexes();$$);      -- 夜跑；与第 7 章 G-ctx2 同一条命令
```

四件事都是恢复与维护，主路径仍是：

```text
worker settle(effect)
  → v13_parse → v13_advance     -- 第 5 章：两阶段，语义与扫地扫描完全相同
```

NOTIFY 不持久、队列 at-least-once、worker 可能在 settle 之后、下一格 parse
之前被杀——扫地把这些缝扫回去。连续两次扫地必须零新 effect（幂等）。
**把 cron 当节拍器**（每个 session 每 N 秒强制 `v13_advance`，靠时钟拨 turn）
是被拒形状：空转付扫描税，干预面被无意义的 parse 打扰，duty_cycle 从
「资格」退化成「心跳频率」。

「pg_cron tick」另有一条 YAGNI：扫描恢复的空转成本实测超标时，再考虑
少扫空转的聪明调度。那是扫地僧的优化，不是把它改回节拍器。扩展取舍
（pg_cron 为何 P1 进、pg_net 为何 P0 排除）在第 15 章。

## 13.3 预取排序进 YAGNI 台账

长目标树让「下一个问题是什么」看起来可猜——ContextPipe 的触点 6
（预取排序）就等在这扇门后面。v13 的裁决：**P2，进台账，本章不建。**

| 项 | 本章态度 | 触发条件 | 触发后的形态 |
|---|---|---|---|
| **预取排序（触点 6）** | 不建 | 长目标树落地 **且** 下一查询可预测 | SQL 构造有界候选；Jev 可选重排；**预取仍由 worker 执行**（effect，不是解析相里的 IO） |
| 更聪明的 tick（少扫空转） | 不建 | 扫描恢复的空转成本实测超标 | 仍是扫地僧；只减少空转，不改 settle 主路径 |

性价比（设计 §6.2）：预取排在摘要验收、复用 intent、压缩 hint、效用遥测
之后。没有「下一查询可预测」的证据时，预取是把猜测写成 effect——
钱先花、答案可能用不上，还污染缓存身份（第 14 章 ForkPrefix）。

触发之前若出现「下一查询预取」表、解析相里的预取 IO、或把预取写进
默认 assemble，gate 红。触发之后预取也不进会话锁、不进 `v13_parse` 的
判断预算：它是 worker 上的 effect，与 llm/tool 同纪律。

## 13.4 逐段解释

- **「goal 不是聊天线程」=「会话是行不是连接」**：loopx 的核心洞察在 v13 里
  是同一个事实的 PG 表述。goal 是一行，executor 是一批短命 worker，
  谁在跑由 lease 说话——loopx 的「registered agents are peers, no durable leader」
  就是 claim/fence/lease 的多 worker 形态（第 8 章已备好）。
- **reward overlay 是事件不是表**：`{recorded_at, decision, reward, reason_summary,
  follow_up}` 作为 `human_reward` 类型事件追加，`source_effect_id` 指向被评判的 run——
  「后来的 tick 和 dashboard 能确切看到哪个决策被奖励」（loopx 文档原文的诉求）
  在 v13 里是一次 `SELECT ... WHERE type='human_reward'`。这里的「后来的 tick」
  是扫地僧扫到这条事件，不是时钟拨出来的下一拍。
- **executor 也可以是重型外部 agent**：`handler='claude-code'` 的 worker 跑
  `claude -p`，bounded turn = max_turns，evidence = settle 时落的 artifacts——
  **长时运行外部 agent 运行时只是又一个 handler**，这是第 8 章合同的直接收益。
- **quota 管资格，cron 管缝**：`duty_cycle=0` 的 goal 被恢复扫描跳过
  （compute-paused）；它仍可能被 settle 之后的 parse+advance 看见——那时
  变更相读同一行策略，拒绝建新工作。两处读同一份数据，没有第二套调度面。
- **不建的（loopx 六层控制面表结构）**：v11 已裁「不引入第二套调度面」。
  目标树 / 配额 / 扫地全部寄生在已有平面上；loopx 本身（或任何控制面产品）
  可以作为**策略层+视图层**坐在同一个 PG 上，或经 SQL 面从外部驱动——
  两个方向都因为「全是行」而成立，不用现在选。预取排序与聪明 tick 同裁，
  触发条件写在 13.3，机制可以后建。

## 13.5 硬性规定与 gate（G7 部分）

```text
✓ 子会话预算归属：父 goal 的 quota 扣减包含活跃子会话的消耗（一次递归聚合）
✓ duty_cycle=0 的 goal：恢复扫描跳过（compute-paused 语义）
✓ human_reward 事件挂在不存在的 effect → 拒绝（FK 语义）
✓ 树深度/环检查：parent 链不得成环（递归 CTE 断言）

tick = 扫地僧，不是节拍器：
✓ pg_cron job 跑 requeue_stale / 空闲恢复扫描 / transcript 投影构建 / verify_index
✓ 主路径 turn 推进由 settle 触发 parse+advance；关掉 cron 之后，
  settle 仍能把一个有界 turn 走完
✓ 连续两次扫地零新 effect（幂等）；不得出现「每个 session 每 N 秒强制 advance」
✓ cron 间隔 ≠ duty_cycle：资格是策略行，缝是扫描

预取排序在台账上：
✓ 触发条件未满足时，不存在下一查询预取表 / 预取 effect 族 /
  解析相里的预取 IO / 默认 assemble 的预取 section
✓ 台账行写明触发：长目标树落地且下一查询可预测；形态：SQL 有界候选、
  Jev 可选重排、预取仍由 worker 执行
```

## 13.6 检查点练习

1. 写 `v_goal_tree(root_id)` 递归视图：goal → 活跃子会话 → 各自状态/预算余量。
   这就是「agent-native Kanban 的看板」——一行 SQL。
2. 实现 duty_cycle 策略行 + 恢复扫描过滤，压测：100 个 goal、quota 0.1，
   断言一个扫地周期内恰 ~10 个有资格被推进。再关 cron、只走 settle：
   一个有界 turn 必须仍能走完——这是「不是节拍器」的断言。
3. 用 human_reward 事件 + `v_routes` 组合：reward=follow_up 时自动生成一条
   follow_up 子会话。体会「reward 是数据，后续动作是路由」。
4. 把 13.3 的预取排序行抄进第 15 章能看到的台账注释。不要实现预取。
   思考题：下一查询还不可预测时，预取会污染哪一份缓存身份？（第 14 章）

## 13.7 回到 vN 对照

- loopx `docs/state-interaction-model.md` / `quota-allocation.md`：goal-owned state
  清单与 quota 与 reward 分离的裁决——本章映射表的两条主输入。
- `v11-dev.md` 附录 A.1：loopx 行「采纳 run-bound reward overlay / quota 持久门控，
  拒绝六层控制面表结构」——v13 与 v11 的裁决一致，实现重量差一个数量级。
- 第 5 章把 tick 列为 parse+advance 的第三来源：本章把它收成扫地僧，
  主路径仍是 settle。第 15 章收扩展取舍（pg_cron P1 进、pg_net P0 排除）。

## 13.8 内在合理性：前因后果

**作用力。** 队列 at-least-once、NOTIFY 不持久、崩溃可落在任何指令边界——
settle 之后、下一格 parse 之前被杀，是常态不是事故。行锁只在事务内活着，
没有一把跨调用的「调度锁」能当心跳。判断与生成都有成本；「下一个问题
大概是什么」在目标树未落地、查询不可预测时只是猜测。pg_cron 的 job 是行，
能替代仓库否则要自己写并测试的扫描恢复；它不是时钟权威。

**推导。** 主路径必须是 settle → parse+advance，三个来源语义相同（第 5 章）。
丢通知与过期租约是缝，不是节拍 ⇒ tick 是扫地僧：requeue、空闲恢复、
投影构建、verify_index 夜跑。quota 是资格（策略行，变更相同事务读），
cron 间隔是扫缝的频率，两者不是同一个旋钮。长目标树让预取看起来诱人，
但收益条件是「下一查询可预测」——未满足时预取是提前花的 effect，
还可能改写前缀身份；所以触点 6 进台账，形态预告为 SQL 有界候选 +
可选 Jev 重排 + worker 执行，不进解析相。

**反事实。** 把 cron 当节拍器：T0，每个 session 每 5 秒 `v13_advance`；
T1，大多数 session 无未消费事件、无活跃工作，parse 空转仍占连接、
仍碰水位；T2，duty_cycle=0.1 的本意是「十个里跑一个」，被心跳改写成
「每 5 秒打扰一次」——资格与频率焊死，账单跟时钟走，不跟工作走。
再在目标树刚落、下一问还不可预测时上预取：T0'，SQL 猜一批候选并建
embed/recall effect；T1'，用户问了另一件事；T2'，预取结果进不了
manifest（query hash 不对），钱已付，缓存身份可能已变。

**被拒替代。** **应用层单例调度器当节拍器**——进程死亡即全局停摆，
第 5 章已拒。**消息驱动的紧循环**（settle 后直接给自己发下一格）——
通知不持久，崩溃后要么丢一格要么重放一格；扫地僧以一次空转买回
精确恢复。**在解析相做预取 IO**——把猜测塞进第 5 章那条不该盖住
干预面的锁外 IO，还让预取与判断抢批上限。**为预取新建控制面表**——
v11 已裁的第二套调度面的复活。
