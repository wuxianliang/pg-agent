# 第 5 章：turn 与推进——两阶段 advance、三角色与预算即策略

> 前置：第 1–4 章。产出：`v13/loop/advance.sql`（G4 + G-ctx1 验收）。
> 对照上游：`v12/turn`（G4：有界 turn 端到端）、loopx 的 quota 门（第 13 章展开）。
> 设计对照：`docs/designs/v13-context-on-pg.md` §4.3（两阶段 / 三角色）、§6.8（信封族）、§10 G-ctx1。

## 5.1 这一章要做什么

前四章造好了全部零件：日志（1）、账本（2）、唤醒（3）、决策（4）。
本章把它们串成唯一的推进函数。v13 的 loop 不是 Python 里的 while——
**是 SQL 里的一次幂等推进，每拨一格走两笔事务**：

```text
v13_parse(session_id)    → 快照 / 缺口 / 判断补齐     （解析事务，不碰会话锁）
v13_advance(session_id)  → progressed | waiting | terminal
                         （变更事务，FOR UPDATE，毫秒级）
```

谁调用？三个来源，语义完全相同（先 parse 再 advance）：
- worker settle 完一个 effect 后；
- driver 周期扫描（tick，第 13 章）；
- 人工/外部直接调用。

这就是「loop 在 SQL 边界上」的最终形态：**循环本身住在调用者手里，
状态机住在数据库里。** 拆成两笔事务不是风格，是下一节那条物理事实。

## 5.2 两阶段与三角色

持会话行的 `FOR UPDATE` 做 1.3–1.6s 的库内判断时，连 `INSERT INTO events`
都被挂起：`events.session_id` 的 FK 检查要对该行加 `FOR KEY SHARE`，
与 `FOR UPDATE` 互斥；第 1 章的 `v13_append_event` 还要 `UPDATE sessions.next_seq`。
用户发言和 cancel 都进不来。**这不是延迟问题，是干预面停摆。**

所以 advance 是两笔事务，不是一笔：

| 相 | 锁 | 做什么 | 提交后 |
|---|---|---|---|
| **解析事务** `v13_parse` | 不碰会话锁；`pg_advisory_xact_lock(hash(查询 × 候选集))` | recall 算缺口，resolve 补 decisions | advisory 锁随事务释放 |
| **变更事务** `v13_advance` | `sessions FOR UPDATE`，毫秒级 | 水位复核 + 原五步（建 effect / 路由 / 预算） | 会话锁释放，干预面恢复 |

三角色把两相拆成三种权限形状——**recall = SELECT，resolve = 写 decisions + IO，
route 持会话锁**：

| 角色 | 事务 | 干什么 |
|---|---|---|
| **recall** | 解析 | 纯 `SELECT`：`fold_state`、`LEFT JOIN decisions` 算缺口、读候选。只读角色即可。 |
| **resolve** | 解析 | 写 `decisions` + 判断 IO（`typesafe_ask` / Jev）。写角色。本相唯一允许的外部 IO。 |
| **route** | 变更 | 持会话锁：复核水位、建 effect、走 `v_routes`、扣预算。变更相不再 `typesafe_ask`。 |

第 2 章「外部 IO 一律不进事务」对**生成 IO** 仍成立（llm/tool/human 永远走 worker）。
演化的那一刀是：**纯判断 IO 幂等、可缓存、廉价，可以进解析事务，但必须离开会话锁。**

```sql
-- 解析事务。recall 只读，resolve 写 decisions + 判断 IO。不碰 sessions 行锁。
CREATE OR REPLACE FUNCTION v13_parse(p_sid uuid)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_snap jsonb;
BEGIN
  -- recall = 纯 SELECT：快照内 fold_state + LEFT JOIN decisions 算缺口
  -- v_snap 记录水位：max_event_seq / goal_hash / candidate_set_hash
  -- pg_advisory_xact_lock(hash(查询 × 候选集))  —— 并发重复解析只付一次款
  -- resolve：v13_resolve_judgments(...)        —— 写 decisions + typesafe_ask
  --          上限 = 策略行，单位是批，默认 ≤1 批（≤32 问）
  --          INSERT ... ON CONFLICT DO NOTHING
  --          超时不落行（放弃分支零新增 Jev 调用；已发出的调用可能已计费）
  -- 同一 v13_resolve_judgments 两种调用者：
  --   这里（快路，有批上限） / worker 慢路（judge effect，分批无上限）
  RETURN v_snap;
END $$;

-- 变更事务。route 持会话锁。毫秒级。本事务不再 typesafe_ask。
CREATE OR REPLACE FUNCTION v13_advance(p_sid uuid, p_snap jsonb)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE v_ctx_status text; v_route text;
BEGIN
  PERFORM 1 FROM sessions WHERE session_id=p_sid FOR UPDATE;   -- 会话锁，仅变更相
  -- 水位复核：锁下 max_event_seq / goal_hash / candidate_set_hash
  --          与 p_snap 不一致 → 弃批，返回让调用者重解析
  -- ① 终态或有未决 effect：直接返回
  -- ② context gate：required_revision vs active_revision
  --    不匹配 → 建 context_refresh effect → return 'waiting'（第 10 章展开）
  -- ③ 决策：读已落行的 decisions（缓存命中在解析相已发生）
  --         缺口仍在（超过快路批上限）→ 建 judge effect → return 'waiting'
  -- ④ 路由：v_routes 给出动作
  --    sql  → 同事务直接执行目录函数 + effect 终态化（零队列往返）；
  --           不入队、不 claim/settle——回执 = 同事务的行 + 事件（不是 effect
  --           经 worker 的结算）；库内、零外部 IO、零队列；默认只读，
  --           具名写允许名单例外（5.4④）
  --    tool/llm/human → 建 effect + 入队（第 3 章）→ return 'waiting'
  --    finish/reject → closeout：三终结事件+对账收据+终态同事务（5.3）
  --                    → return 'terminal'
  -- ⑤ 预算：turn_no 递增在创建工作的同一事务检查/扣减
  RETURN 'progressed';
END $$;
```

调用者每拨一格两句 SQL（各自一笔事务，中间自动提交）：

```text
SELECT v13_parse(sid);            -- 解析事务
SELECT v13_advance(sid, snap);    -- 变更事务
```

**④ 的下游：harness result 四值消费表（A15）。** ④ 建的 `llm` effect 结算后，
下一格 parse+advance 消费的不是 harness 土话，是 `harness_result` 信封（第 7 章）
里唯一持久化的分派键 `result_kind`——四值。四值里 `progress` 是新增立法：
没有它，中间进展只能误用 `wait`（语义相反）。`delivery_kind` 是可选对照
注释，路由不读（分层词表在第 7 章）：

| `result_kind` | advance 行为 | material spend（同 logical_turn_id ≤1 次） | 可伴随事件 |
|---|---|---|---|
| `progress` | 不终结，下一格 parse+advance | **是，除非同批存在 `repair/required` 或 `replan/required`**（真进展不附修复信号；防「progress+repair」双义） | 可带 repair/replan |
| `finish` | 走验收门；过则 closeout completed | 是 | 禁止 repair/replan |
| `wait` | 零新 harness/llm/tool effect；`wait_reason=approval` 时恰建一个 human effect | 否 | 可带 repair/replan |
| `reject` | closeout failed | 否 | 禁止把 unknown 伪装成 reject |

- `wait_reason ∈ {approval|evidence|quota}` normative（进 pg_jsonschema，缺省
  非法）。approval 的 wake=human settle；evidence/quota 必带**机器可判定 wake
  condition**（事件类型/not_before/artifact 到达/子终态），缺失 →
  `v13_complete` 拒收。
- **协调者未齐子树按 `wait` 处理（A21）**：orchestrator 的 required 子任务未全部
  终态 → 本格零新 harness/llm/tool effect——`wait` 语义（wake=子终态，机器
  可判定），不是 `progress`；「子齐父未验收」由 recover_idle 扫回验收链
  （第 13 章 13.2）。
- repair/replan 走**异步 fold**：`repair/required` → 下一格路由既有 `sql`
  （库内修复）或 `human`（超限）；`replan/required` → 路由既有 `llm`
  （重 triage/编排）或 `human`。上限 = thresholds 行（`harness.repair_count` /
  `harness.replan_count` 信号，第 4 章命名风格）+ 本会话事件计数 fold，
  带满 → human 或 reject。
- **三层 wait 消歧（同名不同物，互不蕴含）**：`sessions.status='waiting'`
  （会话等外部）≠ advance 返回 `'waiting'`（本格已建 effect）≠
  `result_kind=wait`（本格不建下一执行 effect）：

| 层 | 载体 | 语义 |
|---|---|---|
| `sessions.status='waiting'` | 会话控制行（第 1 章） | 会话在等外部——有 ready/claimed effect 或等审批，wake 前零自动推进 |
| advance 返回 `'waiting'` | 推进函数返回值 | 本格已建 effect，推进让位给 worker |
| `result_kind=wait` | `harness_result` 信封（第 7 章） | 本格零新 harness/llm/tool effect（`wait_reason=approval` 时恰建一个 human effect） |

## 5.3 变更相的五步与 closeout（A16）

五步原样留在变更相——设计原话是「建 effect / 路由 / 预算扣减，原五步原样」。
变的是③不再在锁内调判断：判断补齐发生在已经提交的解析相。

五步的终点不是「写个终结事件」就完事——**closeout 是规范级收尾**（原练习 1
升格）：

- **三终结事件**：`session/completed` / `session/failed` / `session/cancelled`
  （第 1 章登记），各带**对账收据**——`spent`（material 花费汇总）、
  `produced hashes`（产出 artifact 指纹）、`children 汇总`（子会话终态）、
  `unconsumed`（未消费输入，另记 `closeout/inbox_residual` 事件）、
  `state_hash`（终结时控制态指纹）。
- **同事务**：收据、终结事件、session 终态、预算终态一笔落库——不存在
  「已终结但收据缺失」的中间态。closeout 本身不再扣预算。
- **前置 fail-closed**：对账不齐（预算未封账、children 未汇总）→ 终态
  不得落，封闭而非兜底。
- **子 closeout 不持子锁写父事件**：向父会话追加事件时不得持有子行锁——
  锁序不新增边（第 2 章锁序注释；spawn 只锁父的同一条纪律）。

## 5.4 逐段解释

- **解析相不碰会话锁**：recall 是 `SELECT`，resolve 的判断 IO 可以跑 1.3–1.6s，
  同一 session 的 `INSERT INTO events`（用户发言、cancel）必须当时就能成功。
  这是 G-ctx1 的第一句。
- **advisory lock 消灭双重付款**：并发两条 parse 撞上同一「查询 × 候选集」，
  `pg_advisory_xact_lock` 把第二人挡住；`INSERT ... ON CONFLICT DO NOTHING`
  让重复解析变成读已有 `decisions` 行。锁是事务级的，parse 一提交即释放，
  不串行化变更相，更不挡住 events。
- **双速 resolve**：`v13_resolve_judgments` 只有一个。advance 内快路按策略行
  卡批上限（默认 ≤1 批 = ≤32 问）；更大的缺口在变更相建 `judge` effect，
  由 worker 慢路分批调用同一函数、无上限。双速是同一函数在两双手里，
  不是两套判断管线。
- **超时不落行**：resolve 失败或超时不写 `decisions` 行；事件计数防止重试风暴。
  措辞是「放弃分支零新增 Jev 调用」，不是绝对零成本——已发出的调用可能已计费。
- **水位复核是两相之间的正确性缝**：parse 提交到 advance 拿锁之间，用户可能
  已经发言或 cancel。锁下发现 `max_event_seq` / `goal_hash` / `candidate_set_hash`
  与快照不一致，就弃批重解析——否则旧意图、旧候选集的答案会被用在新 turn 上。
- **①「有未决 effect 直接返回」**：会话同一时刻至多一个活跃工作单元
  （partial unique index 可以把这条做成 DDL：`CREATE UNIQUE INDEX ... ON effects(session_id)
  WHERE status IN ('ready','claimed')`——**用建表语句消灭 80% 竞态**，v8 裁决）。
- **② gate 在决策前**：上下文不新鲜就先刷新——「消费前先判新鲜度」
  是 v9 唯一被保留的思想，形态从七张表的管线降为一个 revision 比较。
- **③ 判断先行，但不持会话锁**：先问 `decisions`（解析相已按 `request_hash`
  补齐或命中 cached），再按路由动作建对应 effect。判断与行动分离，
  缓存收益最大化；**全命中时 parse + advance 零外部调用**。
- **④ sql 动作零往返**：`tools.kind='sql'`（第 6 章）在变更相同一事务内
  直接执行——不进队列、不租约、不 worker。**sql 快路 = 库内、零外部 IO、
  零队列；默认只读**；具名写允许名单内函数可写 sessions/events/latches/
  artifacts 指针——名单 = `v13_tools_guard` 源码闭集（`v13_fork` /
  `v13_spawn_subsession` / 装配函数，A17）。**轻工具走快路，重工具走账本**，
  两条路都从同一张目录表出发。
- **⑤ 预算即策略数据**：`max_turns` 不是常数。它来自版本化策略行——
  插一行 `duty_cycle=0.5` 的策略，同一个 advance 函数行为即变（第 13 章 loopx 映射）。
  纪律：**预算检查与工作创建同事务**（仍在变更相）——不存在「先检查后创建」的窗口。
- **护栏在哪**：llm effect 的出站护栏（PII/切题/安全三题）作为 judge 决策的
  前置信号进 fold_state（v12 G4 形态）；注入否决走 `reject` 路由。
  护栏是路由带的一行，不是一段代码。

## 5.5 一个 turn 的完整时序

```text
v13_append_event(user/message)          -- 解析相不得阻塞这一行
→ v13_parse                             -- 解析事务：recall SELECT + resolve 补 decisions
→ v13_advance                           -- 变更事务：FOR UPDATE 毫秒级
    缺口仍在 → judge effect（waiting）
→ worker: FakeJev/真Jev → settle(answer) → 事件 judge/answered
→ v13_parse → v13_advance → v_routes = tool:duck_query → tool effect（waiting）
→ worker: duck 工作台（第 9 章）→ settle(result artifact)（第 7 章）
→ v13_parse → v13_advance → v_routes = llm → llm effect（waiting）
→ worker: FakeLLM → settle(text) → 事件 assistant/message
→ v13_parse → v13_advance → v_routes = finish → 验收门 → closeout（5.3）→ terminal
```

每个箭头都是一次幂等推进（parse 一笔 + advance 一笔）。崩溃在任何一点，
重启后一次 parse+advance 从表推出现场：解析相中途被杀则事务回滚、零 `decisions`
脏行；变更相中途被杀则会话锁随回滚消失，不残留。

## 5.6 硬性规定与 gate

```text
G-ctx1（两阶段 advance）断言：
✓ 解析相不得阻塞 events INSERT：mock 下两连接实测——连接 A 停在 v13_parse
  未提交，连接 B 对同一 session 做 INSERT INTO events（或 v13_append_event /
  cancel）必须立即成功，不得等解析相提交
✓ 持锁时长：变更相 sessions FOR UPDATE 的持锁时间有上限断言（毫秒级；
  不得复现持锁跑完 1.3–1.6s 判断调用的旧形状）
✓ 缓存命中零外部调用：全部 request_hash 已有 answered/cached 行时，
  parse + advance 的 typesafe/Jev 外部调用计数 = 0
✓ 并发重复解析仅一次付款：同查询×候选集两条 parse 并行，advisory lock +
  ON CONFLICT DO NOTHING，外部调用只发生一次
✓ 生产断言 typesafe.mock_response IS NULL（mock 不得进生产）
✓ steer 缝（G-ctx1 扩，第 12 章）：claimed 期间注入的 steer 不缝进已冻结
  request——request_hash 逐字节不变
✓ steer 不丢失：settle 后下一格 parse+advance 消费（steer/injected 事件
  之后的有效推进可检）
✓ 旧 request_hash 不得用于新水位：steer 落事件后，携旧水位的 advance
  锁下复核不一致 → 弃批重解析（不得用旧批建 effect）
✓ steer 注入立即可写：claimed 期间 events INSERT 不被挡（与第一条同源）
✓ G-ctx1-spawn：spawn 批量建子全程在变更相事务内（父 FOR UPDATE 已持、
  零入队）；持锁时长上限沿用毫秒级口径——超限改函数/索引，
  不得改回队列「自愈」

G4（turn gate）节选断言：
✓ 全链路 fake（FakeJudge/FakeLLM/FakeTool）一轮 turn 走完 sql/tool/llm/human 四路
✓ 预算耗尽 → 强制 human/finish，不静默继续
✓ 崩溃恢复：杀在任一 settle 后 → parse+advance 幂等续跑，无重复外部调用
✓ 同 session 并发两次 advance：变更相串行化，无双重 effect（单活跃索引拒第二个）
✓ 阈值换版本 → 新 turn 用新路由，进行中 turn 不受影响
```

## 5.7 检查点练习

1. 实现 5.3 的 closeout：三终结事件 + 对账收据与终态、预算终态同一事务落库。
   断言：收据字段齐（spent/produced hashes/children 汇总/unconsumed/
   state_hash）；对账不齐时终态不落（fail-closed）；子会话 closeout 写
   父事件时不持子锁。
2. 给变更相加「无效输入拒绝」：fold_state 为空时直接 reject 封闭（v8 不变量：
   强制策略失败封闭——fail-closed，不 fallback）。
3. G-ctx1 两连接实验：连接 A 在 `v13_parse` 里对判断 IO 注入可暂停的 mock，
   暂停期间连接 B 对同一 session `v13_append_event`；断言 B 立即成功。
   再量变更相 `FOR UPDATE` 持锁时长（应是毫秒，不是秒）。再造全缓存命中：
   外部调用计数必须为 0。
4. 量一次 parse+advance 的延迟（空会话 + 10k 事件会话）。这是第 14 章回放设计的输入数据。

## 5.8 回到 vN 对照

- `v12/turn/test_turn.py`：有界 turn 端到端（sql/tool/llm/human/护栏/预算/崩溃恢复）
  ——G4 的直系祖先。v12 把判断和路由放在同一把会话锁里；v13 把判断 IO 移出
  会话锁，G-ctx1 是这条物理事实的 gate。
- `v8` 的 loop 分散在 seal/dispatch/close 一族 stage；v13 压成 parse 函数 +
  advance 函数 + 一个路由视图。减法成立的根基：单活跃索引 + 同事务结算已把
  竞态消灭在 DDL 层；两阶段只是把「不该盖住干预面的那一段 IO」从锁里拆出去。

## 5.9 内在合理性：前因后果

**作用力。** 先于一切设计偏好，介质本身给出这些事实：
**行锁只在事务内活着**——backend 一死，锁随回滚消失，没有一把锁能跨调用存活；
**`FOR UPDATE` 与 FK 检查的 `FOR KEY SHARE` 互斥**——持会话锁做 1.3–1.6s 的
库内判断期间，连 `INSERT INTO events`（用户发言、cancel）都被挂起，干预面停摆；
**崩溃可以落在任何指令边界**，包括「刚检查完、还没创建」的缝隙；
**外部 IO 与事务之间没有原子性**——模型/工具调用一旦发出，rollback 撤不回来，
超时也不等于失败（对面可能已经生效）；**生成 IO 永远不能进事务**，
**纯判断 IO 幂等、可缓存、廉价，可以进解析事务，但必须离开会话锁**；
**判断有真实成本**，但同一问题同一上下文的答案可以缓存复用；
**CHECK/UNIQUE 是声明式执法**——引擎在写入时刻拒绝，并发之下不存在人工检查
留下的窗口。这些不是偏好，是这个系统泡在里面的水。

**推导。** 干预面要活着，解析事务就不能锁 `sessions`：recall 必须是纯
`SELECT`，resolve 的判断 IO 只能发生在这把不挡 events 的锁外
（advisory 锁只串行化「同一查询 × 候选集」的付款，不串行化会话）。
判断有成本且同题可缓存，所以 resolve 写 `decisions` 行、`ON CONFLICT DO NOTHING`
吃掉重复解析；并发第二人付零次款。变更相仍要保证「同一时刻至多一个活跃
工作单元」和「预算检查与工作创建同事务」，所以 route 仍对 session
`FOR UPDATE`——但锁只罩建账/路由/扣减，持锁时长是毫秒。两相之间会话可能
被新事件改写，所以变更相拿锁后复核水位，不一致即弃批重解析。缺口可能超过
一批，所以同一 `v13_resolve_judgments` 有两种调用者：advance 内快路有批上限，
worker 慢路分批无上限。sql 动作与 effect 的分界线不是性能，是「有无外部
IO」：库内函数（默认只读，具名写允许名单例外）留在变更相同一事务快路，
tool/llm/human 建账入队。
推进来源天然有三个（settle 唤醒、tick 扫描、人工），语义必须完全一致，
而三者唯一的公共地形是数据库本身，**唯一解仍是幂等 SQL**：循环住在调用者
手里，状态机住在库里，谁拨一格都是 parse 然后 mutate。

**反事实。** 把循环搬回 Python 的 while：三个推进来源变成三条代码路径，
各自实现「现在能不能推进」。t0 时刻，worker A settle 完一个 effect，读库确认
「无活跃工作，可以推进」；t1 时刻，tick 扫描进程读到同一份空表；t2 时刻两边
各自 INSERT effect——「至多一个活跃」碎成两份外部调用，钱花两遍，没有任何
一层报错，账本上只留下两行都「合法」的记录。再把判断塞回单事务、持着会话锁
跑 `typesafe_ask`：t0 用户按了 cancel，`INSERT INTO events` 等那把
`FOR UPDATE`；t1 判断还在 1.5s 的 HTTP 上；t2 干预面停摆——cancel 不是慢，
是暂时不存在。再把预算改成异步扣减：turn N 在检查点读到余额尚余，检查与
创建之间另一个并发 turn 插入新工作，双方都认定自己在预算内——超支不抛异常，
只出账单。

**被拒替代。** **单事务 advance 持会话锁做判断**：本章若把 `v13_parse` 与
`v13_advance` 合成一笔、开头就 `FOR UPDATE`，G4 仍可能绿，G-ctx1 必红——
解析相期间 events INSERT 被阻塞，干预面停摆。这是被两阶段明确拒绝的旧形状。
**应用层单例调度器**：把互斥交给一个独占进程——进程死亡即全局停摆，「单例」
本身还得靠运维约定维持，等于把不变量从 DDL 降级为承诺。
**消息驱动的紧循环**：settle 后直接向自己发下一条消息，省一次 tick 空转——
但通知不持久、队列至多保证 at-least-once，崩溃后要么丢一格要么重放一格，
而幂等 parse+advance + 周期扫描本就以一次空转的代价买回精确恢复。
**变更相里连生成调用**：一个函数里做完判断、调模型、结算——生成调用
不受事务保护，长事务把行锁与快照悬挂在外部延迟上，崩溃回滚撤不回已发出的
IO，账本反而失去对账基准。判断 IO 进解析相可以，是因为它幂等可缓存且
**已经离开会话锁**；把同一调用放回话锁里，干预面再次停摆。
