# v13 控制面完备性复核:缺口 1–5 填补后,三个层次的读法是否闭合(2026-09-21)

> 输入:`docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md`(调查)
> + `docs/designs/v13-context-on-pg.md` + v13 tutorial 16 章逐章复核
> (本轮新细读:ch08 多语言 harness / ch12 干预面 / ch14 fork 与回放;
> 抽查:ch02 四件套、ch06 目录、ch11 kill 边界)。
> **结论:否——缺口 1–5 填补后,Codex 层(turn 读法)与 LoopX 层(goal 读法)闭合,
> 会话委托读法(RP-CE 对应层)仍剩 3 条缝(A/B/C)。三条缝与缺口 1–5 同级
> (信封与合同形状,不是机器),建议并入缺口 1 的扩展裁决一次收口。**

## 0. 判定标准(先立尺子,防建错方向)

调查报告的核心结论是「三者不是三层楼,是一部电梯」:控制谱系的三个时间尺度
(turn / 会话 / goal)是**同一组原语的三个读法**。因此「具有三种层次的
agent 控制功能」的正确判据不是「三个功能模块建出来」,而是:

> **每个读法的控制动词组,都能在同一组核心原语(effects/events/sessions/
> thresholds/parse+advance+settle)上闭合,且不需要新的执行机制。**

用错判据的后果:为「RP-CE 层」建一个 session-manager 服务、为「LoopX 层」
建一套调度器——正好是 v11 已拒的第二套调度面的复活。

## 1. 逐层判定总表

### 1.1 Codex 层 = turn 读法(秒–分尺度)——**闭合 ✅**

| turn 读法动词 | v13 落点 | 状态 |
|---|---|---|
| start turn | parse+advance 五步,turn_no/max_turns(ch05) | ✅ |
| steer(turn 中注入) | events INSERT + 水位复核(G-ctx1) | ✅;缺口 5 补 gate 断言后完全闭合 |
| interrupt turn | cancel 事件 + 粘性收束(ch12) | ✅(会话/turn 语义;进程级传导见缝 A) |
| respond approval | human effect settle(ch12) | ✅ |
| compact | transcript chunks 投影 + 三层记忆栈(设计 §4.4) | ✅ |
| resume | 行是唯一真相,parse+advance 从表推出现场 | ✅ |
| fork | 会话树 O(1) fork + 三种回放(ch14) | ✅ |
| goal | sessions 控制行(ch13) | ✅ |

**判定:缺口 1–5 之外,turn 读法不需要任何新东西。**

### 1.2 LoopX 层 = goal 读法(天–周尺度)——**缺口 2+3 填补后闭合 ✅**

| goal 读法动词 | v13 落点 | 状态 |
|---|---|---|
| goal 持久(活过线程) | sessions 行;executor=短命 worker(ch13) | ✅ |
| quota should-run | 策略行,advance 同事务读(ch13) | ✅ |
| gates | thresholds + human 平面(ch13 映射) | ✅ |
| capability gate | effect.handler + claim 过滤,无人认领即 waiting(ch06/08) | ✅(队列语义天然覆盖) |
| reward overlay | human_reward 开放事件 + source_effect_id(ch13) | ✅ |
| settlement:writeback | settle | ✅ |
| settlement:spend | 预算同事务扣减(ch05 ⑤) | ✅ |
| settlement:closeout | 终结事件族 | **缺口 3** 填补后 ✅ |
| attention/看板 | 参数化 STABLE SRF `v_goal_tree(root)`（B16：非 VIEW 非物化；史稿旧句「递归 CTE 视图」作废，实现勿抄） | **缺口 2** 填补后 ✅ |
| scheduler tick | pg_cron 扫地僧,非节拍器(ch13) | ✅ |
| peers/no leader | 多 worker claim/lease/fence(ch08) | ✅ |
| backoff/退避 | thresholds 一行(机制在,形状未定) | ✅(策略细节,不列缝) |

**判定:LoopX 六层映射无结构性残缺;缺口 2/3 是收尾工件不是机器。**
与 ch13 既有映射表(「总预付成本=2 列+2 纪律」)一致。

### 1.3 RP-CE 层 = 会话委托读法(时–日尺度)——**缺口 1+4 填补后仍剩 3 缝 ⚠️**

| 会话读法动词 | v13 落点 | 状态 |
|---|---|---|
| startOrResume | 建 effect(handler 参数+lease),ch13 executor=handler | ✅ |
| sendUserMessage/steer | append_event | ✅ |
| respondToPermissionRequest | human effect | ✅ |
| shutdown | 租约回收/fence(ch02/03) | ✅ |
| 多 provider/模型目录 | request 冻结 + 策略行;目录是数据 | ✅(无新机制) |
| session 树/委托 | parent_session_id(ch13/14) | ✅ |
| fork/handoff | O(1) fork(ch14);handoff 信封 | **缺口 1** 填补后 ✅(但见缝 B:缺口 1 只是信封族一角) |
| worktree 隔离 | mutation_scope 存在(ch08 op_seq 并行纪律),归属未裁 | **缺口 4** 填补后 ✅ |
| wait/poll/竞速 | SELECT/LISTEN,驱动者语法糖 | ✅(不需机制) |
| liveness/epoch 幂等 | lease_until + fence + 单调 seq | ✅ |
| **interruptTurn(进程级)** | **粘性 cancel 不传导到子进程** | **缝 A** |
| **驱动信封(request/result/审批上行/续跑)** | **未定义** | **缝 B** |
| **spawn 子会话(编排闭环)** | **路由动作空间不含建会话** | **缝 C** |

## 2. 三条残留缝(逐条:问题 / 为什么缺口 1–5 不覆盖 / 最小填补形状)

### 缝 A:cancel 的传导深度(harness handler 的主动中断纪律)

- **问题**:ch12 裁决粘性 cancel「不强制杀正在跑的 effect,cancel 是事实,
  settle 时自然吸收」。对内部 FakeLLM/FakeTool 成立(秒级 settle)。但
  `handler='claude-code'` 的 effect 是一个可能跑 20–30 分钟的外部 harness
  turn——粘性语义下人按了 cancel,外部进程继续烧钱到自然结束。
  RP-CE 的 `interruptTurn`、Codex 的 `interruptUserTurn` 在这一档是
  **主动打断**(给进程发信号、带回执)。
- **为什么缺口 1–5 不覆盖**:缺口 5 只补「steer 事件何时被消费」的断言,
  不涉及 worker 进程对 cancel 的响应义务。
- **最小填补形状**:**handler 合同加一条可选纪律**(ch08 worker 三步合同
  变三步+一务):mutating/长跑 handler SHOULD 订阅本 session 的
  cancel 事件,收到即向子进程发中断并 settle(cancelled);不订阅的
  handler 退回粘性语义。**零新表零新函数**——worker 轮询 events 是
  读,kill 是进程内行为,settle 走已有 v13_complete。
  gate:G6 加「cancel 后订阅式 handler 的外部调用提前终止」断言。
  这与 v8 kill-at-every-boundary(ch11)的哲学一致:杀点是事实,
  恢复靠账本,只是把「谁去杀」从崩溃语义扩展到控制语义。

### 缝 B:handler↔harness 信封族(缺口 1 的扩展)

- **问题**:缺口 1 只定了**会话间** handoff 信封。驱动外部 harness 还需要
  一族**handler 与 harness 之间**的信封,缺口 1–5 都没覆盖:
  1. **request 信封**:harness effect 的 request payload 形状——
     prompt + harness 会话标识(resume/续跑语义)+ 沙箱/审批策略参数;
  2. **审批上行**:外部 harness 中途发 approval request(RP-CE 的
     `respondToServerRequest` 场景)。v13 的 worker 三步合同一笔到底,
     中途抛不出问题。接线只能两段(本段为史稿原案形状;**`settle('needs_approval')`
     已被 R2 否决——needs_approval 永不是 effect status,也不得作 settle 参数,
     现行为 succeeded+`result_kind=wait`/`wait_reason=approval` 信封,见文末
     R2 收口):harness effect 终态化(需审批信号随结果信封落账 + 问题
     artifact)→ advance 建 human effect → 人答 → 下一个 harness
     effect **续跑**(带 resume 参数)。原语全部已有,**续跑参数如何进
     新 effect 的 request 是必须裁的信封字段**;
  3. **result 信封**:turn 结果的分类形状——LoopX 六值
     (VALIDATED_PROGRESS/COMPLETION/REPAIR_REQUIRED/REPLAN_REQUIRED/
     USER_ACTION_REQUIRED/WAIT)还是 v13 简化(finish/reject/wait),
     决定路由视图怎么消费 harness 结果。
- **为什么缺口 1–5 不覆盖**:handoff 是 session→session;这族是
  effect→harness→effect。
- **最小填补形状**:与缺口 1 合并成**一个「控制面信封族」裁决**:
  handoff 事件信封 + harness request/result 信封 + 审批上行两段接线。
  全部是 artifacts 载荷的类型约定(第 7 章 artifacts 平面直接承载),
  零新机制。

### 缝 C:spawn 子会话的正面落点(编排闭环的最后一个动词)

- **问题**:v_routes 动作空间 = sql/tool/llm/human/finish/reject(ch05),
  **没有「建子会话」**。RP-CE 的 orchestrate 闭环靠 LLM 调 agent_run
  工具派子会话;v13 的哲学下这个闭环 = LLM 决策 → 工具调用 →
  子会话行——但「创建子会话」这个动词在目录/路由里没有正面落点。
  ch14 已证明 worker 可以是「新会话的创建者」(dream worker),
  哲学上合法,只是没写进正常编排路径。
- **为什么缺口 1–5 不覆盖**:缺口 2 是投影(看树),不是创建。
- **最小填补形状**:**INSERT tools 一行**——`spawn_subsession`(kind=sql,
  参数:parent、goal 承接、预算继承声明),模型经 llm effect 的工具面
  调用它建子会话行。零新机制(目录是表,ch06 承诺兑现的又一例);
  或者路由动作加 spawn——**二选一需要裁**,按 v13 哲学(重工具走账本、
  路由只做动作分类)倾向前者。gate:子会话预算归属断言已有(ch13),
  加「spawn 工具建会话即落 forked 事件」即可。

## 3. 结论与建议

1. **缺口 1–5 填补 ≠ 三层齐备**。turn 读法、goal 读法闭合;
   会话委托读法剩缝 A/B/C。
2. 三条缝都是**信封与合同形状**,与缺口 1–5 同级、同性质——
   建议缺口 1 扩为「控制面信封族」(handoff + harness request/result +
   审批上行)一次裁决,缝 A 进 ch08 worker 合同、缝 C 进 ch06 目录,
   编号沿用「A1–A14 全局唯一」修订体系追加(A15 起)。
3. 判定尺子本身写进设计:防「为层次建服务」的复发——每次控制面新增
   需求先过 §0 的动词闭合判据,再过调查报告 §3.1 映射表。
4. 无需改核心 schema:三条缝全部落在「目录行 / 事件类型 / artifacts
   载荷约定 / worker 合同文档」层——与「9 表 9 不变量」零冲突,
   与文件面 I-file-1…7 零冲突。

## 附:本轮细读/抽查记录

- ch08(全文):worker 三步合同、handlers[] 过滤、lease 是行上的时钟、
  错误信封跨语言统一——缝 A 的合同挂点。
- ch12(全文):粘性 cancel「不强制杀正在跑的 effect」原文、human effect
  即慢速 worker、resolve_unknown 三 resolution——缝 A/B 的对照基准。
- ch14(全文):会话树两列 O(1)、ForkPrefix 与日志前缀分离、三种回放、
  「RSI 层 = 日志的读者 + 新会话的创建者」——缝 C 的哲学依据。
- ch02 抽查:四件套 DDL、fence CAS、两级锁序。
- ch11 抽查:kill-at-every-boundary 是崩溃语义(杀 worker 自身),
  不含「控制语义的主动中断」——缝 A 确认。
- ch06 抽查：只读角色执法 + allowlist 数据化；路由动作空间确认无 spawn。

## R2 收口（2026-09-21）

> 三条缝与缺口 1–5 的裁决已由 R2 终裁记录收口：
> `docs/reviews/v13-control-plane-oracle-r2-2026-09-21.md`（唯一权威，
> A15–A21 分配总表见其 §5）。本节只登记对应关系，不复述裁决。

- **缝 A = A18**：worker 第四务（控制订阅）+ 目录 interruptible
  （required/best_effort/unsupported）+ 核心永不杀进程 + mutating 中断后
  副作用不明 → unknown + 父 cancel 同事务对子孙扇出 cancel/requested。
  落位 ch08/ch11/ch12；G6 增断言。
- **缝 B = A15（四值收口，六值对照）**：`result_kind ∈ {progress, finish,
  wait, reject}` 是唯一持久化 settle/advance 分派键；LoopX 六值 =
  `delivery_kind` 可选对照注释，路由永不读。审批上行按两段接线收口：
  harness effect succeeded + `result_kind=wait`/`wait_reason=approval` →
  human effect → 续跑新 effect（mode=resume）——审批词永不进
  `effects.status`，interaction_ref 必填。缝 B 原文「中途 settle 审批态」
  的接线形状被否决。
- **缝 C = A17（kind='sql' 收口）**：spawn 落 tools 目录行 `spawn_subsession`
  （`kind='sql'`，执行函数 `v13_spawn_subsession` 与 `v13_fork` 同一
  primitive）；`v13_tools_guard` 具名 VOLATILE 例外闭集放行。本节原文的
  备选（路由动作加 spawn、专档 handler）均否决——动作闭集不动，二选一
  已裁。
- **缺口 1–5 与三条缝全部对应 A15–A21**：缺口 1（handoff 信封）→ A15；
  缺口 2（attention/看板）→ A21（`v_goal_tree` 参数化 STABLE SRF +
  recover_idle 扩谓词）；缺口 3（closeout）→ A16；缺口 4（worktree）→
  A19；缺口 5（steer 消费断言）→ A15 gate 族同发；缝 A/B/C →
  A18/A15/A17。A20（triage 证据/动作分离）为 D3 收敛项，与编排闭环相接
  （spawn 准入读硬安全策略行）。

§3 建议的落实情况：「缺口 1 扩为控制面信封族一次裁决」已按 R2
D1/D2/D3 三题一体终裁完成；修订编号 A15–A21 已登记 errata，各受影响
文档按 R2 §9 顺序落位。
