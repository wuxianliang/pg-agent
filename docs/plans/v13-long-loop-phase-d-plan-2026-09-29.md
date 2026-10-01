# v13 长循环 Phase D 计划（2026-09-29）

**状态：候选计划。本规划轮未实现、未跑任何 gate、未提交、未推送。** 不得宣布产品可用。不得把本文的存在写成证据。不得把将来的 Fake 退出码 0 写成产品可用，也不得写成 Phase A 的 `real_authorized_exit_0`。父复审整组接受第 10 节之前，不得开工。

2026-10-01 计划复审闭环（5 轮，oracle group `7374FB79-5604-47EE-A7F8-865793FE6ED7`；codex lane `new-chat-BD0271`、grok lane `new-chat-oracle-2-86D6D5`；修订由 pair 会话 `1301B2BC-9F0B-4C31-BD37-D62DA613E47B` 执行，父逐条工具核验）：轮 1 两路均退回（codex P0=1/P1=3/P2=1；grok P0=1/P1=6/P2=4），主修四臂关联作用域、GRANT 角色具名 `v13_route`、现状 36 项、requeue 三分支等 13 项；轮 2 grok P0=0/P1=1/P2=3（codex 因 watchdog 中断，不计分），修 EXECUTE 行号 `:892-897`、指纹 `:79-82`、配额 `:94-99`、tool/llm 主语；轮 3 grok 接受、codex P1=1（§9 DEFINER 机制），修挂载时/运行时权限检查之分；轮 4 codex P1=1（README 必含句无条件 owner），改按重读二选一；轮 5 两路一致接受，P0=0/P1=0/P2=0。接受的是本计划合同文本，不是实现、不是 gate、不是产品可用。

本文替换同路径底稿里的 Open Questions，不另留一套控制面。底稿的背景事实沿用，行号按第 3 节的复核，不按底稿的偏一行引用。

权威顺序：本轮用户范围（Phase D 只做一库多 goal 领用、公平，饥饿保护只指第 4.3 节那条，全局并发帽、多日 soak 的可执行合同，并表态多根路径竞态与 C4 多 lane）→ Phase 0 `docs/plans/v13-long-loop-plan-2026-09-28.md` 的 §2 与 §9 → 同文件 T0–T7 → 已接受的 Phase A / B / C → 底稿。调查 `docs/investigations/v13-long-loop-workflow-borrowing-gap-2026-09-28.md` 不是权威。冲突则停，并在第 2 节点名。

本规划轮没有改 `v13/load.py`，没有改 stage 1–29，没有改已接受的 Phase 0 / A / B / C 计划，没有改指纹函数，没有改 `v13/fanout/v13_fanout.sql`，没有调用真实 provider，没有跑下面任何一条命令。HEAD=`aa571f8`。`v13/load.py` 的 `SQL_LOAD_ORDER` 已是 36 项，表尾 `workspace_admit`（Phase A 六键 30–35、Phase B `workspace_admit` 36 均已提交落地）。Phase C 未交付（`goal_supervise` 不存在）。工作区另有未提交的 `frontier_gap` 进行中，含 `v13/frontier_gap/v13_frontier_gap.sql:395-396` 的 `v13: replan gap: not_single_tree`；是否入序以实现当时表尾为准。下文「调用已有函数」：A/B 已落地；C 仍指按已接受计划装上之后的函数。

## 执行索引

索引只导航，不替代第 4–7 节的合同。

| 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| `fair_claim` | 新的多 goal 领用入口、库级 `claimed` 帽、根 in-flight 排序、跨根路径第二道闸 | `UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py` 退出码 0；活体 `v13_claim` 正文哈希不变；不替换 `v13_advance` | `v13/fair_claim/v13_fair_claim.sql`、`test_fair_claim.py`、`README.md`；`v13/load.py` 只追加 `fair_claim` | 1..29 已装；A/B/C 计划尾部已装到 `goal_supervise`；`v13_tool_effect_open` 已存在 | L |
| `fair_driver` | 本期 gate 的具名调用者 `claim_one`，不是已证明的生产角色；加上 4 根 8 tick 的有界 soak | `UV_FROZEN=1 uv run python v13/fair_driver/test_fair_driver.py` 退出码 0；序列 R1、R2、R3、R4、R1；无新事件；不含 `load.py` | `v13/fair_driver/driver.py`、`test_fair_driver.py`、`README.md` | `fair_claim` 已装 | M |
| 明确不做 | C4 多 lane、PC-4、PC-6 接入、PC-8 削弱、artifact 增长、成本可观测、B3、自动 skip | 第 4.10 节与第 8 节追溯表写明不做，且没有对应目录 | 无新目录 | 无 | S |

本规划轮没有跑上表任何命令。

## 1. 若需要替换 `v13_claim` 或再替换 `v13_advance`，本计划停止

活体领用保持 `v13/fanout/v13_fanout.sql` 里那一份 `v13_claim`。Phase D 不 `CREATE OR REPLACE` 它，不改该文件字节。`attempt_no` 与 `fence` 的活体递增点因此仍在。本期新函数是**第二个入口**，同一递增语义，见第 4.2 节。这是选择，不是把「唯一递增点」悄悄改写成已经只有一个入口。

Phase A 的 `v13/plan_arm` 是唯一一份计划中的 `CREATE OR REPLACE v13_advance`。Phase B / C 没有第二份。Phase D 的每个新 SQL 文件、每段新 Python，都不得再出现这个替换，也不得出现 `CREATE OR REPLACE` 下列函数：`v13_claim`、`v13_advance`、`v13_scheduler_hint`、`v13_should_run`、`v13_should_run_gate`、`v13_goal_fingerprint`、`v13_recover_idle`、`v13_requeue_stale`、`v13_enqueue_effect`、`v13_quota_eligible`、`v13_advisory_class`、`v13_spawn_subsession`、`v13_spawn_occupancy`、`v13_tool_effect_open`、`v13_goal_stop`、`v13_goal_lifecycle`、`v13_attempt_ok`、`v13_requires_worktree`。不得编辑 `v13/plan_arm/**`、`v13/loop_driver/**`、`v13/workspace_admit/**`、`v13/workspace_exec/**`、`v13/frontier_gap/**`、`v13/goal_supervise/**`、`v13/goal_supervisor/**`。

下面任何一条如果在实现时被证明必须改上述函数体，或必须再 `CREATE OR REPLACE` 一次：该阶段停并 `ASK_USER`，不得标成 `exit_0`，不得靠删断言换退出码 0。

- 公平不得靠改 `v13_claim` 的 `ORDER BY created_at`。
- 全局帽不得做成 `should_run` 的新 block id，不得把活跃策略升到 version 4，不得替换 gate。
- 帽不得写进 `v13_scheduler_hint`。Phase C 禁止替换 hint。
- 饥饿不得靠改 `v13_requeue_stale`。`judge` / `mgraph_consolidate` 过期且 attempt 仍有余量才回 `ready`；`failed` + `lease_exhausted` 只属于 `judge` / `mgraph_consolidate` 的 attempt 耗尽；tool/llm 过期只走 `unknown` 并起墙。
- 路径竞态不得靠编辑 Phase B 打开者，不得删 `not_single_tree`。
- PC-4 不得靠替换 `v13_quota_eligible` 或 gate 重开。
- 零新事件种类。不得为了公平、帽、soak、通知去改指纹排除名单。

本计划不包含那份替换，也不给它留阶段目录。

## 2. 优先级与冲突

1. 本轮用户范围：一库多 goal 的领用查询；公平。饥饿保护只指第 4.3 节那条，in-flight 更高的根不能在另一个 in-flight 为 0 且仍有合格 ready 的根之前再领走下一行。不声称任意交错下没有饥饿。不新增轮转游标。第 4.9 节已有的免责声明保留。全局并发帽；多日 soak 的可执行合同。外加必须表态的两项：Phase B 留下的多根路径竞态；Phase 0 放到 D 的 C4 多 lane。
2. Phase 0 的用户决定与 T0–T7。本文引用，不改写。PG 是唯一控制语义 owner。外部 IO 不进事务。不建第二状态源，不建新表，不加列，不建工作流引擎，不建 cadence ACK / RRULE / scheduler 状态表。不改 stage 1–29 字节。不分配 30、31 这类假 stage 数字。
3. 已接受的 Phase A、B、C 合同。本文消费，不改写，不编辑它们的目录。
4. 第 4 节与第 10 节的 Phase D 选择。父可整组退回。退回前不得另写一套控制面，不得私自改成 `CREATE OR REPLACE v13_claim`。
5. 调查。与上面冲突则调查作废。

| # | 冲突 | 本文 |
|---|---|---|
| 1 | 调查切片 4 把公平、全局帽、饥饿、PC-6/PC-8、长期增长、多日 soak 收成一套实现建议 | 调查不是权威。PC-6 只作禁止接入。PC-8 只作不得削弱。artifact 增长与成本可观测不做。soak 是加速夹具，不是多日运行 |
| 2 | 多 goal 领用若 `CREATE OR REPLACE v13_claim`，fanout 字节不动但活体语义被换掉 | 新名字 `v13_claim_fair`。活体函数正文哈希必须前后相同。`test_fanout` / 既有 `stage_bytes` 不得被这份替换打红 |
| 3 | 「claim 是 `attempt_no` 唯一递增点」（`v13/fanout/v13_fanout.sql` 的 claim 注释；schema 同文）与第二个领用入口 | 见第 4.2 节与第 10 节。两个入口、同一次 +1。requeue 仍不递增 `attempt_no`。第二个递增入口已由第 10 节裁决为 `accept_second_entry`，不再是开工停点。不在打开者里递增，那是 Phase B 已写死的另一件事 |
| 4 | 把帽做成 `should_run` 新 block，策略 version 4 | Phase A 与 Phase C 都写了活跃 version 维持 3、不加 block id。帽做在 `v13_claim_fair` 的锁内计数。`v13_should_run` 仍是 `v13/should_run/v13_should_run.sql:195-202` 的布尔包装，govern 未替换它 |
| 5 | 把 `spawn_budget` 的 8/4/8 重新解释成全局帽 | 矩阵行 25「双根互不占席位」是已测语义，不是缺陷。席位仍按根。全局帽是另一行政策 `global_concurrency`。T7 禁止把未重读的 8 或 64 写成裁决；本文只把活体种子钉成回归，不把它裁成帽 |
| 6 | 公平单位用「用户」或单独的 goal 表 | 活体没有 goal 表，没有用户表。Phase A T1.1 把 plan/todo 钉在根流。公平单位只能是根会话（`parent_session_id IS NULL`） |
| 7 | Phase 0 §7 行 C4 与 §9 把多 lane 放在 D；D 的四项命名交付是领用、公平、帽、soak | **停点级冲突，本文的选择是不实现。** C4 多 lane 是咨询 / oracle 多 lane，不是多 goal 调度。Phase A 已把首期单 lane 写成 `effect_id` 加有界摘录。多 lane 没有已审核的载体，硬做就会变成第二状态源或新事件。不建目录、不建政策、不给领用函数加 lane 参数，所以**不构成第二状态源**。父若认为缺多 lane 则 D 不能接受：停，重写计划，不得在 `fair_claim` 里塞进 lane |
| 8 | T7 允许后期用「新 stage 的 STABLE 重算 + should_run 新版本门」做 PC-4；Phase C §4.11 已关闭 | **保持关闭。** 四项交付都不沿树计 `turn/material_spent`。不改 `v13/quota_window/v13_quota_window.sql:94-99`。父若认为缺 PC-4 则 D 不可交付：停并点名依赖，不得静默升 version 4 |
| 9 | 「多日 soak」若读成必须墙钟跑许多天 | Phase C 已把 `supervisor_max_ticks = 2` 写成「soak，不是多日运行」。D 的合同是有界 tick 的确定性 gate。真实多日运营仍未授权 |
| 10 | 公平要可回放，因而插入 `fair/served` 一类事件 | 该种类会进入 `v13_goal_fingerprint`（排除名单只有 govern `:62-65` 与 `:79-82` 那八类），随后 `v13_goal_resume` 可 RAISE `v13: goal fingerprint`。本期零新事件种类。公平只由领取返回值与 STABLE 折叠观察 |
| 11 | 把 `attention_rank` 接进领用，当作公平序 | PC-6：秩是注意力，不是调度。领用路径不读它，不建成 VIEW |
| 12 | 任务说明要求点名「更新 2026-09-26 矩阵的哪些行」；Phase A §11 默认不改那两份 | **不改** `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` 与 `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` 的历史行。行 25、26、69、73、81 的状态保持原样。态度写在本期新矩阵与新台账。父若要一行指针，另说 |
| 13 | Phase A `loop_driver` 允许名单不含 `v13_claim`；Phase C `goal_supervisor` 明确禁止 `v13_claim`、`v13_enqueue_effect`、`v13_advance` | 不扩展那两份名单，不编辑那两个目录。`claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色。超级用户夹具不证明生产可运行。本期仍不给 `v13_claim_fair` GRANT，不写 stannum GRANT。没有这个具名调用者就不算交付 |
| 14 | Phase B `not_single_tree` 使已提交的第二根上，打开者在路径扫描之前就 RAISE；底稿仍要求 D 关闭多根路径竞态 | 不删该检查。数据库侧序列化用新触发器加新函数。跨根 `path_busy` 不经过打开者。父若要求打开者本身在两个已提交根上打出 `path_busy`：停。那是编辑 Phase B 或第二套打开者 |
| 15 | B3 cadence ACK、无人值守 skip、第二状态源 | 不重开。人等待仍是非终态 `waiting`。driver 不 skip、不 complete、不 INSERT / UPDATE effects 或 events，不写 `turn/material_spent` |
| 16 | T6「一库一树仍需要」与 Phase D 多根正例 | Phase 0 §2 用户已决定 D 是多 goal 公平、并发帽与 soak。T6「一库一树仍需要」的理由仍成立：活体 `v13_claim` 仍是全局池，禁止改 `v13/fanout/v13_fanout.sql`。A/B/C 夹具仍是一棵树。Phase D 的正例授权在同一库使用多个根会话，这是该用户决定的例外，不是废除 T6。`not_single_tree` 负例不削弱。 |

不允许的声称：活体 `v13_claim` 已经公平；`spawn_budget` 已经是全局帽；session-local 配额已经是 goal 级；attention 已经是调度；Fake 绿即产品可用；人可以离开生产终端；多 lane 已交付；跨根 `path_busy` 已由打开者本身复现；PC-4 已实现；绑定窗或产品角色已闭合。

## 3. 本轮复核，不是已通过

实现时必须再 `pg_get_functiondef`。对不上就停。本规划轮没有跑探针。

行号以本节为准。父会话重读 `v13/spawn/v13_spawn.sql:24-25`：`INSERT` 在 `:24`，`spawn_budget` 的 value 在 `:25`。导出曾把活体写成 `:23-24`，那是错的，不以导出为准。`v13_claim` 的租约赋值在 schema 里是 **`:266-272`**（Phase C 引 `:267-271`，偏一行）。fanout 的 claim 起点 **`:266`** 与底稿一致，这一份才是加载后的正文。

| 机制 | 位置 | 复核结论 |
|---|---|---|
| 加载顺序 | `v13/load.py` | HEAD=`aa571f8` 已 36 项，表尾 `workspace_admit`（Phase A 六键 30–35、Phase B `workspace_admit` 36 均已提交落地）。Phase C 未交付（`goal_supervise` 不存在）。工作区另有未提交的 `frontier_gap` 进行中；是否入序以实现当时表尾为准。新键只许追加在**当时**表尾。本期要求当时表尾已经是 `goal_supervise`。不是则停，不替 C 补键 |
| `v13_claim(text, int)` | fanout `:266-303` 覆盖 schema `:266-294` | 全局 `status='ready'`，`ORDER BY created_at`，`FOR UPDATE SKIP LOCKED LIMIT 1`。`attempt_no+1`，`fence+1`，`lease_until = clock_timestamp() + p_lease_ms/1000.0`。过滤只另有 `v13_attempt_ok`、`op_seq` 空或同 scope 的 `min`、以及 `v13_requires_worktree` 且无 `worktree` latch 则跳过。没有 session / root / goal 过滤，没有帽 |
| 活体 `v13_claim` 候选关联 | fanout `v13_claim` 体内 | 候选子查询 `SELECT effect_id FROM effects` 未起别名。`op_seq` 臂的 `e.session_id` / `e.mutation_scope` 与 worktree 臂的 `e.session_id` 关联到 UPDATE 目标行 `e`。活体语义：行 r 被领走当且仅当 r 在「以 r 自身会话关联计算的池」中最老且过臂。跨会话污染例：A（`created_at` 老、工具需 worktree、A 会话无 latch）、B（`created_at` 新、需 worktree、B 会话有 latch）→ 测 B 时池含 A（B 有 latch）candidate=A≠B；测 A 时池空 → 活体 UPDATE 0 行、两行都领不出；而按行局部谓词 `v13_fair_eligible(B)=true` |
| `ux_v13_effects_single_active` | `v13/schema/v13_core.sql:128-129` | 部分唯一索引：同一 `session_id` 至多一行 `ready\|claimed`。不是「每个非终态会话必须占一个全局席位」。它不数跨会话的帽 |
| `v13_requeue_stale` | `v13/control/v13_control.sql:1079` 起，选择条件 `:1087` 一带；三分支在 `:1102-1130` | `lease_until < clock_timestamp()` 才入选。`infinity` 与 NULL 不满足 `<`。三分支：`judge` / `mgraph_consolidate` 过期且 `v13_attempt_ok` 为真 → `ready`（cancel 下 → `cancelled`），`fence+1`，不增 `attempt_no`；**attempt 耗尽 → `failed` + error `lease_exhausted`（`:1114-1124`，`WITH capped AS`）**；其它 kind → `unknown` 并 `v13_raise_unknown_wall`。`ready` 重挂仅 attempt 仍有余量。这是饥饿的既有终局：tool/llm 过期只走 `unknown` 并起墙；`failed` + `lease_exhausted` 只属于 `judge` / `mgraph_consolidate` 的 attempt 耗尽。本期不改 |
| `should_run` version 3 | `v13/govern/v13_govern.sql` 政策激活与 `v13_should_run_gate` | 七个 id：`human_pending`、`unknown_wall`、`unconsumed_cancel`、`duty_cycle`（种子 effect 是 `shadow`）、`quota_window`、`capabilities`、`goal_stopped`。加 id 必须改函数允许名单并升 version。本期不做 |
| `v13_should_run(uuid)` | `v13/should_run/v13_should_run.sql:195-202` | 返回 gate IS NULL。签名仍是一个 uuid 进、布尔出。不是全局帽的站点 |
| `v13_recover_idle()` | govern `:453-515` | 已经全局扫描 `ready\|waiting` 且无 `ready\|claimed\|unknown` effect 的会话。零 effect、零 advance，只经 `v13_insert_nudge` 写 `recover/nudge`。跳过 stopped。不是领用器。本期不调用它来发公平 |
| `v13_scheduler_hint(uuid)` | govern `:517-576` | 只返回 `run_now` / `wait` / `dont_notify`。未 spawn 的 `tool/call` 且 `public.v13_spawn_budget_snapshot(p_sid, v_requested)` 为假时已经 `wait`（装载后正文，govern `:571-576` 一带）。spawn 预算已经进 hint。due 不在返回值里。本期不把全局帽再塞进去 |
| `v13_spawn_occupancy(uuid)` | `v13/spawn/v13_spawn.sql:159-188` | 只数一个根的非终态后代，不含根自己。环或 `d > 64` RAISE `v13: spawn root cycle`。公平计数**禁止调用它**：一棵坏树会把全部领用打崩。深度 64 是这道守卫，不是席位 |
| 席位种子 | spawn `:24-25` | 活体 `{"max_nonterminal":8,"max_depth":4,"max_fanout":8}`。三键校验在 `v13_spawn_subsession` 读政策处（底稿所指数带，开工重读 `:408-413` 一带）。这是回归钉，不是新裁决 |
| 根咨询锁 | spawn `:423` | `pg_advisory_xact_lock(v13_advisory_class('spawn_budget'), hashtext(v_root::text))`，类号 13001，**按根**。双根互不占席位 |
| 深度守卫 | spawn `:401` | `v_depth > 64` 的上溯守卫。不得挪成帽，不得挪成公平窗口 |
| `v13_enqueue_effect` | control `:902-940` | 唯一入队者。身份 `v13_effect_id`。INSERT 不写 status，默认 `ready`，不写 `tool/call`，不调 `v13_send_work`。`failed\|cancelled` 且仍有 attempt 余量则重挂 `ready` 并 `fence+1`。`unknown` RAISE。本期 driver 不调用 |
| 指纹 | govern `:40-95`，排除名单 `:62-65` 与 `:79-82` | 八类之外都进哈希，含 effects 的 status / attempt_no / fence。领用会改变指纹，**因为行变了，不是因为新事件**。零新事件种类则 `goal/stopped` 之后的合法重放不会被本期事件打坏 |
| `v13_pending_human` | control `:120-127` | 只计 human 的 `ready\|claimed`，不计 `unknown`。领用**不**用它当过滤器 |
| `v13_advance` | govern `:719` 起；会话锁、终态先返回 | 在途 `ready\|claimed` 则 `waiting`。Phase A 替换之后，加载后的正文是 `plan_arm` 那一份。本期前后哈希要比的是**装上本期之前**的那一份，不是退回 govern |
| `v13_quota_eligible` | quota_window 时钟是 `:93` 的 `transaction_timestamp()`，本 session 计数 `:94-99` | 只计本 session 的 `turn/material_spent`。不可注入虚拟时钟。松种子 `window_hours=8760`、`allowed=1000000`、`slot_minutes=0`（`:43`）。加速 soak **不能**驱动这扇窗 |
| `op_seq` | schema effects 列注释 | DP1 恒 NULL，没有写入者。不新造写入者。活体 `v13_claim` 正文含大段注释，行号易漂；开工只复读已装载的 `v13_claim` 的 `pg_get_functiondef`，注释块不是谓词。对不上第 4.3 节的四臂散文则停。不要改 fanout |
| 单会话活跃上界与帽 | 索引 `:128-129` 加「帽若按 ready+claimed 计」 | **若帽把候选自己的 `ready` 行算进占用，帽会自己卡死**：池里只要有一行 ready，计数已经 ≥ 1，cap=1 时永远领不走。架构说明里的「帽低于非终态会话数会死锁」针对的是把 `ready\|claimed` 当成占用。本期因此**只数 `status='claimed'`**。入队不受帽限制。见第 4.4 节 |

`not_single_tree` 已在 `v13/workspace_admit/v13_workspace_admit.sql:140-141` 落地（打开者，提交 `2f7d515`）。`frontier_gap` 另有 replan gap 用的同名 token，均不删。`v13_claim` 本身仍不拒绝第二根。

## 4. Phase D 选择

父可整组退回。退回前实现停。这些选择只填 Phase 0 §10「一库多 goal 的领用查询未写出」，以及底稿的七个问题。不是 Phase 0 裁决，也不是对 A/B/C 文本的修订。

### 4.1 公平的单位

单位是根会话：`sessions.parent_session_id IS NULL` 的那一行。子会话上的 effect 归到沿 `parent_session_id` 上溯得到的根。plan/todo 不参与领用。没有当前计划的根，只要有合格 `ready` effect，仍可被领走。不调用 `v13_plan_current`、`v13_plan_gate`、`v13_selected_todo`。领用不是计划臂，也不是工作区打开。

不存在的东西：goal 表、用户表、lane id、per-user 配额列。

### 4.2 领用函数，以及第二个递增入口

不替换 `v13_claim`。新函数是本期多 goal 领用入口。`claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色。活体 `v13_claim` 留给既有单 goal gate 与负例。单 goal 测试继续直接调用活体函数；本期不把那些测试改成调用新函数。

`v13_claim_fair` 对选中的那一行做与活体相同的赋值：`status='claimed'`，`attempt_no = attempt_no + 1`，`fence = fence + 1`，`lease_owner = p_worker`，`lease_until` 为有限时刻。原因：Phase B 已经把「`claimed` 且 `attempt_no=0`」标成 complete 可能拒绝的停点。公平领走的行必须能被既有 5 参 `v13_complete` 用返回的 `attempt_no` 与 `fence` 完成。打开者那种不递增的 `claimed` 不是这条路径。

这破坏「源码里只有一个递增点」的字面，不破坏「一次成功领用 +1、requeue 不 +1」的次数语义。第二个递增入口已由第 10 节裁决为 `accept_second_entry`，不再是开工停点。不得为了保住字面唯一而把 `attempt_no` 留在 0，也不得因此去改 `v13_claim`。

撞上已有同名函数或目录就停，不静默改名。本规划轮在给定材料里没有这些 `fair_*` 新函数名。实现时再搜 `v13/` 与 `docs/`：

| 名字 | 性质 | 作用 |
|---|---|---|
| `v13_claim_fair(p_worker text, p_lease_ms int DEFAULT 60000)` | VOLATILE | 唯一多 goal 领用者。成功返回六键 jsonb；无行可领返回 SQL NULL。不 COMMIT |
| `v13_fair_root(p_sid uuid)` | STABLE | 唯一根上溯。环或深于 64 则返回 NULL，不 RAISE。领用、合格谓词、快照共用，不得各写一份 `WITH RECURSIVE` |
| `v13_fair_eligible(p_effect uuid)` | STABLE | 唯一合格谓词。快照逐行调用它。领用必须调用 `v13_fair_eligible(e.effect_id)`，不得在 CTE 里再写一份谓词正文，见第 4.2 与第 4.3 节。零写 |
| `v13_fair_snapshot()` | 同上，若体内只有 STABLE 则标 STABLE；若必须调用 VOLATILE 的 `v13_goal_lifecycle` 则标 VOLATILE。零写合同不变 | 当下折叠。不是预约，不是事件 |
| `v13_path_conflict_locked(p_request jsonb)` | VOLATILE | 全局路径锁加前缀复检。不 INSERT |
| `v13_workspace_path_guard()` | VOLATILE | BEFORE INSERT 触发器函数。调用上一行，使插入路径与直接调用共用一个谓词 |

`v13_goal_lifecycle` 已是 stage 29 活体：`v13/govern/v13_govern.sql:129`，`LANGUAGE sql STABLE`，uuid 进、text 出。实现时重读签名。对不上则停。不得把它标成 VOLATILE，也不得包一层假 STABLE。

新函数都 `SET search_path = pg_catalog, public`，都不是 `SECURITY DEFINER`。都 `REVOKE EXECUTE FROM PUBLIC`。本期不给 `v13_claim_fair` GRANT，不写 stannum GRANT，不 GRANT 给 `PUBLIC`，不 GRANT 给一个被写成已经证明的产品角色。`claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色。超级用户夹具不证明生产可运行。路径函数 `v13_path_conflict_locked` 与 `v13_workspace_path_guard` 保持 `REVOKE EXECUTE FROM PUBLIC`，另外 `GRANT EXECUTE` 给 `v13_route`（已核：`v13/schema/v13_core.sql:866` INSERT、`:892-897` EXECUTE 链）。不得 GRANT 给 `PUBLIC`，不得 GRANT 给 stannum，不得因此 GRANT `v13_claim_fair`。断言执行面用超级用户连接 `SET ROLE v13_route`（非超级用户身份、`READ COMMITTED`）。该证明只覆盖直接 enqueue 路径。链上若 `42501` 到不了复检则停，不得删 `path_guard_execute_reaches_recheck`。

#### `v13_claim_fair` 的参数与返回

- `p_worker`：非 NULL、非空、长度 1..128、不含 NUL。等于 `v13_workspace_opener` 则 RAISE，避免冒充 Phase B/C 的 ambiguous hold 主人。
- `p_lease_ms`：缺省 60000。合法闭区间 **1..600000**（1 毫秒到 10 分钟）。NULL、小于 1、大于 600000：RAISE。不写 `infinity`。上界是为了这条函数不能把帽席位钉成天级租约。活体 `v13_claim` 的参数范围不改，仍可被测试用更大的 `p_lease_ms` 调用。600000 不是席位常数，不是 8，不是 64。
- 隔离级别不是 `read committed`：在任何锁与任何 UPDATE 之前 RAISE。驱动器负责先进入事务并设置该级别。函数再查 `current_setting('transaction_isolation')`，与 `read committed` 不完全相等就拒绝。

成功时 jsonb **恰好**六键，多一键测试失败：

| 键 | 含义 |
|---|---|
| `effect_id` | 被领走的行 |
| `attempt_no` | UPDATE 之后的值 |
| `fence` | UPDATE 之后的值 |
| `kind` | 行上的 kind |
| `request` | 行上的 request，不改写 |
| `root_session_id` | 上溯到的根 |

无行可领、帽满、合格集为空、会话锁内重验失败、effect `FOR UPDATE NOWAIT` 得到 `55P03`、UPDATE 影响到 0 行：都返回 NULL。不 RAISE。不得等到 `statement_timeout`。不在同一次调用里改领另一根。帽满不是错误。驱动器不得从 NULL 里猜原因；测试用 `v13_fair_snapshot` 区分。

不写 events，不写 `tool/call`，不调用 `v13_send_work`、`v13_enqueue_effect`、`v13_advance`、`v13_complete`、`v13_spawn_subsession`、`v13_spawn_occupancy`、`v13_insert_nudge`、`v13_recover_idle`。

错误前缀 `v13: claim fair:`。token 只有 `canonical` 与 `policy`。

- `canonical`：隔离级别、worker、lease 上界、冒充 `v13_workspace_opener`。零写。
- `policy`：没有恰好一行 active 且 `version = 1` 的 `global_concurrency`（缺失、重复、或 active 的其它 version），或 value 形状不对，或 `claimed_cap < 1`。零写。不得读任意 active 行。

活体异常原样传播，不包装成这两个 token。没有 `cap` token，没有 `not_single_tree` token，没有 `starved` token。

#### 锁内顺序

前一步失败则零写。函数自己不 COMMIT。锁只活到调用者的事务结束，不跨外部 IO。

1. 隔离级别与参数。失败 RAISE `canonical`。
2. 只选恰好一行 active 且 `version = 1` 的 `global_concurrency`。缺失、重复、或 active 的其它 version：RAISE `v13: claim fair: policy`。不得读任意 active 行。
3. `pg_advisory_xact_lock(13002, 1)`。类号是本期常量，不写进政策 JSON，不修改 `v13_advisory_class`。实现时全库搜索 `13002` 与 `13003`；已有使用则停。`13001` 仍只属于 `spawn_budget`。本函数仍禁止再取 13003，仍禁止取 13001。
4. 仍持有该锁时按同一规则重读：只选恰好一行 active 且 `version = 1`。缺失、重复、或 active 的其它 version 仍 RAISE `policy`。不得读任意 active 行。`claimed_cap` 取这一次。
5. `SELECT count(*) FROM effects WHERE status = 'claimed'`。大于等于 cap 则返回 NULL。不选行。
6. 一条不锁 effect 行的 SELECT 选出排序第一的 `effect_id`。WHERE 调用 `v13_fair_eligible(e.effect_id)`，不得在 CTE 里再写一份谓词正文。排序仍要每行的根与 `inflight_claimed`，由调用 `v13_fair_root` 的 CTE 算出，不在 PL/pgSQL 里对每个 effect 循环上溯。这条 SELECT 不 `FOR UPDATE`，不 `SKIP LOCKED`。没有候选则返回 NULL。
7. 在取得任何 effect 行锁之前，先 `SELECT ... FROM sessions WHERE session_id = 该根 FOR UPDATE`。若 effect 所在会话不是该根，再 `SELECT ... FROM sessions WHERE session_id = effect 所在会话 FOR UPDATE`。顺序固定为先根、后这一把子会话，不得反过来，不得再锁第三把会话。Phase 0 T0 的开工门：读后写、并声称保护已 stopped 根的新 stage，必须在与 `v13_goal_stop` 相同的根会话行锁内重验。锁内重跑终态与 lifecycle，并再调用 `v13_fair_eligible`。失败闭集只有：effect 所在会话 status 属于 `completed` / `failed` / `cancelled`，或任一边 `v13_goal_lifecycle` 是 `stopped`，或 `v13_fair_eligible` 已为假，或上溯失败。命中则不 UPDATE，返回 NULL。根会话 status 要重读，但终态本身不是失败条件。不得在已持有 effect 行锁后再锁 `sessions`。
8. 然后才 `SELECT ... FROM effects WHERE effect_id = 选中行 FOR UPDATE NOWAIT`。`55P03` 则返回 NULL，不得等到 `statement_timeout`。不在同一次调用里改领另一根，不得再锁第三把会话。不得在已持有 effect 行锁后再锁 `sessions`。
9. 再数一次 `claimed`。大于等于 cap 则返回 NULL，不 UPDATE。这一次是为了活体 `v13_claim` 可能在本锁之外领走了别的行。
10. 锁到之后再按原赋值 UPDATE，且 `status` 仍是 `ready`。`lease_until = clock_timestamp() + make_interval(secs => p_lease_ms / 1000.0)`。影响到的行数不是 1 则返回 NULL，不重试循环。
11. 返回六键对象。

effect 行锁是 `FOR UPDATE NOWAIT`，不是 `SKIP LOCKED`。锁不到就 NULL，不得超时，也不得在同一次调用里改领下一行。公平领用彼此之间被 13002 串行。活体 `v13_claim` 与正持有 effect 行锁的 `v13_advance` 可以挡住选中行；挡住则本调用返回 NULL。不得写成「先锁 effect 再取 13002」，也不得写成「先锁 effect 再锁 session」。

仍禁止再取 13003，仍禁止取 `spawn_budget` 的 13001。根会话 `FOR UPDATE` 之后、任何 effect 行锁之前，若 effect 所在会话不是该根，再锁这一把子会话。顺序固定为先根、后这一把子会话，不得反过来，不得再锁第三把会话。不得在已持有 effect 行锁后再锁 `sessions`。这样不与 advance / goal_stop / 打开者组成「持有 effect 行锁再等会话锁」的环；插入路径仍只在触发器里取 13003。

一次调用最多领一行。不在函数内循环补领。

### 4.3 公平算法

没有新表，所以没有轮转游标。严格轮转的「上次发给谁」无法在零新事件、零新列的前提下跨事务记住。本文不实现轮转游标。

排序元组，全序，小者胜：

1. `inflight_claimed` 升序。该根上 `status='claimed'` 的 effect 行数，含根会话自己与所有能上溯到该根的会话。**不含** `ready`，不含 `unknown`，不含 `succeeded`。把 `ready` 算进 in-flight 会惩罚积压的根，造成饥饿。
2. 候选行的 `created_at` 升序。
3. 候选行的 `effect_id` 升序，钉死同一微秒。

不按 `fence` 排序，不按历史上全部 `attempt_no` 之和排序。后者会让长寿根永久输给不断新建的根，那是另一种饥饿，而且无法在没有时间窗的前提下归零。没有时间窗是因为不建新事件、也不读可注入的时钟来做「最近 N 分钟」。

因此保护的是：**一个 in-flight 更高的根，不能在另一个 in-flight 为 0 且仍有合格 ready 的根之前，再领走下一行。** 深树上多个更老的 ready，只要该根已经有一行 `claimed`，空闲根的更年轻 ready 先被领走。

`peer_idle_beats_older_sibling_backlog`：根 A 的 `claimed` 行与更老的 ready 分属该根下两个会话；根 B 的更年轻 ready 的 `created_at` 更晚；公平领用返回根 B。两行不得塞进同一 `session_id`。`created_at` 用该断言里允许的 `UPDATE effects SET created_at` 写成严格先后。

帽满时不领。帽只限制全局 `claimed` 行数，不按根再切一刀。根之间的spread靠排序，不靠 per-root 子帽。不写 8。

残留，必须写进 README，不得写成已闭合：`claimed_cap = 1` 的连续领用残留只指仍会回到 `ready` 的路径。`judge` / `mgraph_consolidate` 经未改的 `v13_requeue_stale` 挂回 `ready`（仅 `v13_attempt_ok` 仍为真、attempt 仍有余量），或 `failed|cancelled` 经 `v13_enqueue_effect` 重挂回 `ready`（`created_at` 与 `attempt_no` 都不变）。attempt 耗尽则 requeue 打成 `failed` + `lease_exhausted`（只属于 `judge` / `mgraph_consolidate`），不是这条残留。这些行下一次仍可能是最老且 in-flight 已回到 0，可以连续领走唯一席位。其它 kind 的过期 claimed 仍转 `unknown` 并起墙（tool/llm 过期只走这条），不是这条残留。不要用同一个「requeue」指 `ready` / `failed` / `unknown` 这三种结果。种子是 2，就是为了夹具不走这条。stage 只插入或接受与种子 jsonb 相等的行，不相等则装载 RAISE，不覆盖。函数读到政策后再校验 `claimed_cap >= 1`；这不是第二套装载规则，也不把「至少为 2」写成产品不变量。

活体 `v13_claim` 完全不看这个排序，可以按全局最老领走，从而打乱公平序，也可以在帽满之后继续领。这是第 4.4 节的洞，不是公平函数的内部例外。

#### 合格谓词 `v13_fair_eligible`

领用必须调用 `v13_fair_eligible(e.effect_id)`，不得在 CTE 里再写一份谓词正文。快照仍逐行调用它。

与活体 claim 对齐的部分：凡活体以函数表达的谓词必须调用原函数（`v13_attempt_ok`、`v13_requires_worktree`）。`status='ready'` 与 `op_seq` 臂按行自身会话计算：`status='ready'` 看该行自己；`op_seq` 臂用该行自己的 `session_id` / `mutation_scope`。这两臂在已装载的 `v13_claim` 里是内联 SQL，没有可调用函数。活体按 UPDATE 目标行关联计算池（候选子查询未起别名，见第 3 节），跨会话数据可致活体与行局部四臂不一致，甚至领不出任何行；该关联语义差异记录在案，合格函数不模仿活体的跨行关联。活体 `v13_claim` 正文含大段注释，行号易漂；开工只复读已装载的 `v13_claim` 的 `pg_get_functiondef`，注释块不是谓词。对不上下面四臂散文则停。不要改 fanout。断言名 `eligible_matches_live_claim_on_shared_arms`：在无跨会话污染的夹具数据上（相关会话 latch 状态一致或无 worktree 要求、每会话单一 `mutation_scope`、`op_seq` 统一 NULL）逐行一致。「公平可选集 ⊆ 行自身四臂集合」。终态过滤只看 effect 所在会话，不看根会话 status。不要写全体相等断言。不写无条件的「真子集」断言。加上 effect 所在会话的终态、不可解析上溯、stopped 之后，公平可选集是活体可选集的子集；差集见证由实际执行的那条断言提供（stopped 二选一、终态会话、不可解析上溯夹具），不依赖互斥的 `stopped_root_not_fair_claimed`。不得把「不要把行号当可抄正文」读成删掉这两臂。四臂散文如下：

- 行存在且 `status = 'ready'`
- `v13_attempt_ok(kind, attempt_no)`
- `op_seq IS NULL` 或等于同 `session_id`、同 `mutation_scope`、`status <> 'succeeded'` 的 `min(op_seq)`
- 不是 `v13_requires_worktree(tool_name)` 为真且该会话没有 `latches.name = 'worktree'`

本期多加的部分，活体 claim **没有**：

- effect 所在会话的 `status` 不是 `completed` / `failed` / `cancelled`
- 上溯得到根。上溯深度守卫与 spawn 相同：超过 64 或走上已在路径里的 id，视为不可解析。不可解析则不合格。**不 RAISE**。一棵坏树不得挡住其它根。64 在这里只是与 `v13_spawn_occupancy` / spawn `:401` 相同的环守卫，README 写明「不是席位，不是 `max_depth`」
- `v13_goal_lifecycle(根)` 与 `v13_goal_lifecycle(本会话)` 都不是 `stopped`

根会话 `FOR UPDATE` 之后、任何 effect 行锁之前，若 effect 所在会话不是该根，再锁这一把子会话，然后才重验。锁内重跑终态与 lifecycle。失败闭集与第 4.2 节第 7 步相同，只有这些：effect 所在会话 status 属于 `completed` / `failed` / `cancelled`，或任一边 `v13_goal_lifecycle` 是 `stopped`，或 `v13_fair_eligible` 已为假，或上溯失败。根会话 status 要重读，但终态本身不是失败条件，也不是新过滤器。装到 stage 29 之后，要核对的是 `v13/govern/v13_govern.sql:753-756` 那一份 `v13_advance`：它只检查正在推进的会话 `p_sid`，不检查根的 status。Phase A 替换之后，哈希对象是 `plan_arm` 那一份，不是 fanout `:514-516`。开工用 `pg_get_functiondef` 复读；若那一份改为检查根 status，停。根已终态、子会话仍非终态且有合格 ready 时，公平领用仍可领该行。这是指定行为，不是洞。不要加「终态根必须返回 NULL」的断言。

不加的过滤器，避免把「已经合法入队的 ready」领丢：

- 不看 `v13_should_run`
- 不看 `v13_pending_human`
- 不看 `v13_scheduler_hint`
- 不按 kind 排除 human / llm / tool / judge / context_refresh。活体池没有这道排除。父若要排除 human：整组退回，不得在实现里悄悄加

`unknown` 不是 ready，天然不会被领。它也不占帽，也不算 in-flight。墙住的会话因此不永久占用并发席位；它永久不能再前进，那是 requeue 的既有语义，本期不修。

### 4.4 全局并发帽

语义是**库级、跨根、只数 `claimed`**。不是 per-root `spawn_budget`，不是 `ready\|claimed` 之和，不是每根一条子帽，不是 `should_run` 的门。

政策行，不碰 `workflow_template`、`workspace_tool_subset`、`should_run`、`spawn_budget`、`quota_window`、`judgment_templates`：

- `v13_policies.name = global_concurrency`
- `version = 1`
- `active`
- 不存在则 INSERT
- jsonb 相等则跳过
- 不相等则装载 RAISE，不 UPDATE

函数读，不是装载：`v13_claim_fair` 与 `v13_fair_snapshot` 都只选恰好一行 active 且 `version = 1` 的 `global_concurrency`。缺失、重复、或 active 的其它 version：各自 RAISE 已有的 `policy` 错误（`v13: claim fair: policy` 与 `v13: fair snapshot: policy`）。不得读任意 active 行。上面的「不存在则 INSERT」仍只属于装载，不因这次读规则而删除。

value 闭集，键必须逐个出现，多一个键装载 RAISE：

- `schema_version`：整数 1
- `claimed_cap`：整数 **2**

`claimed_cap` 在装载时以及函数读政策时都必须 `>= 1` 且 `<= 2147483647`。小于 1 则 RAISE `v13: claim fair: policy`，不插入半截政策。value 不得含 `max_nonterminal`、`max_depth`、`max_fanout`。

种子 2 的理由：`fair_claim` 在政策不存在时插入 `claimed_cap=2`。形状与上面三条相同：不存在则 INSERT，jsonb 相等则跳过，不相等则装载 RAISE、不 UPDATE。不得把 stage 写成不插入政策。这个种子不是产品并发能力证明，不是 8，不是 64，不是 Phase A 的 32，也不是 spawn_budget 的 8/4/8。夹具用已插入的值证明「两个根可以并行占席」和「第三笔公平领用在前两笔尚未 complete 时返回 NULL」。README 句子见第 7.2 节。父可退回这个数字；退回前不得改用 8 或 64，也不得改成 stage 不插入。

为何不数 `ready`：候选在被领走之前是 `ready`。把自身算进占用，则只要池非空就可能 `count >= cap`，第一笔也领不走。索引 `ux_v13_effects_single_active` 只说明每个会话至多一个活跃 effect，并不要求帽 ≥ 会话数。入队不读这行政策。四棵会话各自持有 `ready`、帽为 2 时，四次 `v13_enqueue_effect` 都必须成功；公平领用只能成功两笔。这就是下限断言，替代「帽不得低于会话数」那条会自锁的读法。

占用包含谁：

- 公平函数刚刚领走的行
- 活体 `v13_claim` 领走的行
- Phase B 打开者标成 `claimed` 且 `lease_until = infinity` 的行

最后一类会一直占席，直到别的已接受路径把它移出 `claimed`。本期不续租、不清行、不改成 `unknown`、不调用 `v13_goal_lease_once`。`infinity` 不会被 `v13_requeue_stale` 收走。这是 G4 残留在帽上的投影，不是新漏洞。父若要求本期释放这种行：停。

另有一个必须写入 README 与台账的洞：有限租约过期后，`claimed` 行只有在有人调用未改过的 `v13_requeue_stale` 时才变 `unknown` 并释放席位。本期 `fair_driver` 禁止调用它。A/B/C 也没有点名生产 requeue 调用者。worker 崩溃后，席位保持占用、该会话按既有语义起墙，直到外部调用 requeue。本期不新增这个 owner，也不把 Phase C 监督进程改成 owner。

`unknown` 不占席。过期的其它 kind 被既有 requeue 打成 `unknown` 之后，席位释放，会话进入 `blocked_unknown`（tool/llm 过期只走这条）。`failed` + `lease_exhausted` 只属于 `judge` / `mgraph_consolidate` 的 attempt 耗尽，席位同样释放。公平函数不调用 requeue。测试断言 `requeue_wall_unchanged_frees_cap` 写明：活体 unknown 墙仍会升起并保持，席位释放。

帽的洞，必须写进矩阵，不得写成库级不变量：**活体 `v13_claim` 不取 13002，不读 `global_concurrency`，帽满之后仍可领走。** 帽只约束 `v13_claim_fair`。`claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色。不建触发器去拦所有 `ready→claimed`，因为那会改变活体 `v13_claim` 与既有 gate 的语义。

另有一个必须写入 README 与台账的洞：`13002` 在会话行锁之前取得，公平领用彼此串行。会话 `FOR UPDATE` 等待期间持有 `13002`，排头的会话锁等待会阻塞所有后续公平领用（队头阻塞）。活体 `v13_claim` 不取 `13002`，不受影响。与 `v13_advance` / `v13_goal_stop` / 打开者 / 活体 claim 不构成等待环（effect 是 `NOWAIT`、路径只取 `13003` 且不锁行）。

### 4.5 快照

`v13_fair_snapshot()` 零写，不取 13002，不做 `FOR UPDATE`。它不是领用的依据。领用在锁内重新计数。并发下快照可以与下一次领用不一致。测试只在没有并发领用者时用它做断言。它与 `v13_claim_fair` 一样，只选恰好一行 active 且 `version = 1` 的 `global_concurrency`。缺失、重复、或 active 的其它 version：RAISE `v13: fair snapshot: policy`。不得读任意 active 行。

返回 jsonb 的键恰好是：

| 键 | 含义 |
|---|---|
| `schema_version` | 1 |
| `claimed_cap` | 恰好一行 active 且 `version = 1` 的政策整数。缺失、重复、active 的其它 version，或形状错：RAISE `v13: fair snapshot: policy`，零写。不得读任意 active 行 |
| `claimed_count` | 全库 `status='claimed'` 的精确行数，不受下面的 32 帽截断 |
| `omitted_count` | 0 或 1 |
| `omitted_complete` | 布尔。`omitted_count = 1` 时为假；`omitted_count = 0` 时为真。没有第三态 |
| `unresolved_count` | 上溯失败的会话数，精确，不截断 |
| `roots` | 数组 |

`roots` 的每个元素键恰好是 `root_session_id`、`inflight_claimed`、`claimable_ready`、`oldest_ready_at`。`oldest_ready_at` 是合格 ready 行里最小的 `created_at`，没有则为 JSON null。`claimable_ready` 使用与领用相同的 `v13_fair_eligible`，按根计数。排序是 `root_session_id::text COLLATE "C"`，避免库 locale 改变 JSON 数组序。

扫描帽种子 `fair_snapshot_cap = 32`，再探测紧接着的 1 个根。这是 Phase A 库存帽的同一形状，不是席位常数，不是 LoopX。第 33 个根：返回前 32 个，`omitted_count = 1`，`omitted_complete = false`，`claimed_count` 仍是全库精确值。不得把截断数组的 in-flight 相加当成 `claimed_count`。0 个可解析根时 `roots` 为 `[]`，`omitted_count` 为 0，`omitted_complete` 为真，不 RAISE。`claimed_count` 与 `unresolved_count` 仍取全库精确值，不要写成计数为 0。

不可解析的会话不出现在 `roots` 里。它们的 effect 不合格。快照不调用 `v13_spawn_occupancy`，因此不因环而 RAISE。

错误前缀 `v13: fair snapshot:`，token 只有 `policy`。

两次调用在同一事务、中间零写时，jsonb 相等。不要求跨事务字节相同。

### 4.6 多根路径竞态

Phase B 打开者在已提交的第二根上 RAISE `not_single_tree`，零工作区 effect，而且先于路径扫描。两个已提交根之间，打开者到不了「看不见对方未提交忙行」那一步。真正的窗口只可能出现在：两个事务的快照都还只看见一个根，又都通过了检查，然后都插入带 `workspace_root` 的 tool effect。本期**不**删除 `not_single_tree`，所以不把那扇门打开。

交付的是门若放行之后的第二道闸，加上一个不经过打开者的跨根复现。

`v13_path_conflict_locked(p_request jsonb)`：

1. 隔离级别不是 `read committed` 则 RAISE `v13: workspace open: canonical`，不取锁。
2. 取 13003 之前检查字符串形状，失败则不取锁。不调用 `realpath`，不看文件系统，不要求打开者的允许名单（那是打开者夹具，不是 enqueue 的全局门），不复制工具/payload 闭集，不改 `v13_tool_effect_open`。`workspace_root` 必须是绝对字符串：以 `/` 开头，不是单独的 `/`。以 `/` 开头时丢掉前导空段；中间空段、尾斜杠、整段 `.` 或 `..` 才是 `canonical`。无 `\`，无 NUL。`/tmp/ws` 必须能通过。否则 RAISE `v13: workspace open: canonical`。`paths` 必须是非空数组；空数组同样 RAISE `canonical`。元素仍用下面的相对路径规则。
3. `pg_advisory_xact_lock(13003, 1)`。事务结束释放。不 `FOR UPDATE` 任何 effect 行，不锁会话行，不取 13002，不取 13001。
4. 复检。冲突则 RAISE `v13: workspace open: path_busy`。无冲突则返回 void。不 INSERT，不改行。

`p_request` 必须是 object，且含字符串 `workspace_root` 与字符串数组 `paths`。缺键、类型不对、或上面的形状不对，都 RAISE `v13: workspace open: canonical`，且发生在取 13003 之前。其它键允许存在，因为打开者落库的规范请求不止这两键。

比较仍是 Phase B 的字符串拼接，这里写死，避免实现时再选一套。不是打开者允许名单，也不是工具/payload 闭集：

- 忙行：`kind = 'tool'`，`status ∈ {ready, claimed, unknown}`，`request` 含 `workspace_root`。没有该键的旧 effect 不参加，包括不带该键的 `read_file_py`。
- 比较的是「`workspace_root` 字符串 + 每个相对段」拼出的段序列。不因为两个 `workspace_root` 字符串不同就跳过。`/tmp/ws` + `sub/file.txt` 与 `/tmp/ws/sub` + `file.txt` 是冲突。以 `/` 开头时丢掉前导空段；`/tmp/ws` 必须能通过取锁前的绝对字符串检查，不得把前导空段当成 `canonical`。否则会在取 13003 之前 RAISE，复现不了阻塞。
- 段前缀：`a` 与 `a/b` 冲突；`a` 与 `ab` 不冲突；`a/b` 与 `a/c` 不冲突。
- 同一请求自己的父段与子段不互斥。本函数不插入，所以没有「自己与自己」的行。触发器在 BEFORE INSERT 里调用它时，新行还不在表里，同样不与自己比较。
- 相对路径：非空，不以 `/` 开头，无空段，无整段 `.` 或 `..`，无 `\`，无 NUL，无尾斜杠。违反对 `canonical`。
- 不补父段。父段规则仍由打开者负责。本函数只比较已经写在 `paths` 里的段。

触发器 `trg_effects_workspace_path_lock`，BEFORE INSERT ON `effects`，`FOR EACH ROW`，`WHEN (NEW.kind = 'tool' AND NEW.request ? 'workspace_root')`，执行 `v13_workspace_path_guard()`。守卫只调用 `v13_path_conflict_locked(NEW.request)`，然后 `RETURN NEW`。冲突则插入失败，整笔回滚。不把触发器扩成 `BEFORE UPDATE`。

路径函数 `v13_path_conflict_locked` 与 `v13_workspace_path_guard` 保持 `REVOKE EXECUTE FROM PUBLIC`。另外 `GRANT EXECUTE` 给 `v13_route`（已核：`v13/schema/v13_core.sql:866` INSERT、`:892-897` EXECUTE 链）。不得 GRANT 给 `PUBLIC`，不得 GRANT 给 stannum，不得因此 GRANT `v13_claim_fair`。断言执行面用超级用户连接 `SET ROLE v13_route`（非超级用户身份、`READ COMMITTED`）。该证明只覆盖直接 enqueue 路径。链上若 `42501` 到不了复检则停，不得删 `path_guard_execute_reaches_recheck`。

不要求实现前审计每一个历史写者。指定的新行为：任何带 `workspace_root` 的 INSERT，包括既有 `v13_enqueue_effect`、`v13_tool_effect_open`、advance 臂的调用者，只要事务不是 `READ COMMITTED`，触发器 RAISE `v13: workspace open: canonical`，零插入。不改这些函数的字节。

这是第二份路径谓词。打开者体内的扫描保持 Phase B 原文，不抽取、不替换。漂移风险写进台账。父若要求只留一份谓词：停，因为那要编辑 `v13_tool_effect_open`。

已知洞，写入本期台账，不在本期堵：`v13_enqueue_effect` 的 `failed|cancelled` 重挂是 `UPDATE effects SET status='ready'`（`v13/control/v13_control.sql:922-925`），不触发只挂 BEFORE INSERT 的路径闸。根 A 的失败行在 B 插入时不在忙集里，随后 A 重挂，两根可以出现重叠 ready。不把触发器扩成 `BEFORE UPDATE OF status`：那会改变既有重挂路径，须另一次父确认。本期不改 `v13_enqueue_effect`。

触发器改变的是**装上本期之后**的插入行为，不改 Phase B 文件字节。单根上打开者仍先锁根行；触发器在 INSERT 时再取 13003。同会话重复取同一咨询锁是计数重入，不会自死锁。

跨根复现不调用打开者，避免 `not_single_tree`：

- 两个已提交的根。
- 连接 A：`READ COMMITTED`，`v13_enqueue_effect` 插入一行带 `workspace_root` 与 `paths` 的 tool effect，事务保持打开。触发器已取 13003。
- 连接 B：也必须是 `READ COMMITTED`，再调用 `v13_path_conflict_locked`，参数是重叠路径。它阻塞在 13003 上。连接 B 若不是 `READ COMMITTED`，会在取 13003 之前就因隔离级别 RAISE，复现不了阻塞。
- A 提交。
- B 得到 `v13: workspace open: path_busy`，B 零新行。

另有一条负例：两个已提交根上调用 `v13_tool_effect_open`，仍是 `not_single_tree`，零工作区 effect。不得把这条改成成功。

锁序若做不到「路径函数不锁行、领用函数不取 13003」，停。不得加第三把业务锁，不得把咨询锁持有到事务外。

### 4.7 具名调用者

今天没有任何已接受计划允许一个进程调用 `v13_claim`。`claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色。超级用户夹具不证明生产可运行。本期仍不给 `v13_claim_fair` GRANT，不写 stannum GRANT。不修改旧允许名单。

目录 `v13/fair_driver`，无 SQL，无加载键。文件 `driver.py` 只提供：

`claim_one(conn, worker: str, lease_ms: int = 60000)`

行为：

- 调用时连接不得已经在事务里。已在事务里则 Python 侧直接失败，消息 `v13: claim fair: canonical`，不调用领用函数。
- 开始事务，第一条是 `SET TRANSACTION ISOLATION LEVEL READ COMMITTED`。
- 调用 `v13_claim_fair` 一次。
- 成功则 COMMIT，把六键对象交给调用者；SQL NULL 则 COMMIT 并返回 None。
- 死锁 `40P01`：ROLLBACK，同一参数再试，**含第一次最多 2 次**，无睡眠。仍失败则把错误抛出。
- 其它错误：ROLLBACK，不重试。
- NULL 不是重试条件。同一 tick 不忙等。
- 事务内无文件系统、无网络、无 `pg_sleep`。函数返回之后也不做工具 IO。工具 IO 仍属于 Phase B 适配器或将来的工人，不在这个函数里。

`fair_claim_retries = 2` 只覆盖死锁。不是规划重试，不是 provider 重试。

驱动器允许调用的 SQL 只有 `v13_claim_fair`。不得调用 `v13_claim`、`v13_fair_snapshot`、`v13_enqueue_effect`、`v13_complete`、`v13_advance`、`v13_recover_idle`、`v13_requeue_stale`、`v13_scheduler_hint`、`v13_should_run`、`v13_spawn_subsession`、`v13_tool_effect_open`、`v13_path_conflict_locked`、`v13_plan_writer`、`v13_goal_stop`、`v13_goal_lease_once`。快照、路径函数、活体 claim、requeue、complete、fork、enqueue 只允许出现在测试文件。

`static_check` 扫 `driver.py`：去掉注释之后，出现 `v13_` 名字且不是 `v13_claim_fair` 即失败。出现 `INSERT INTO effects`、`INSERT INTO events`、`INSERT INTO sessions`、`INSERT INTO artifacts`、`UPDATE `、`turn/material_spent`、`pg_cron`、`pg_sleep`、API key 字段名即失败。注释里写名字不算。测试文件禁止那四类 `INSERT`。不得用 `INSERT INTO effects` 构造 `attempt_not_ok_skipped`。测试文件的 `UPDATE effects` 白名单只有这三句，且各有位置限制：

- `UPDATE effects SET created_at` 只允许出现在 `tie_oldest_created_at`、`peer_idle_beats_older_sibling_backlog`、`root_should_run_false_does_not_block_other_ready`，以及 `test_fair_driver.py` 里 soak 夹具对 `created_at` 的改写。
- `UPDATE effects SET lease_until` 只允许出现在 `requeue_wall_unchanged_frees_cap` 与 `unknown_does_not_consume_cap`。后者把公平领走的 llm 的 `lease_until` 改到过去，调用未改过的 `v13_requeue_stale`，断言该行已是 `unknown`、不计入 `claimed_count`，且另一根的 `ready` 仍可被 `v13_claim_fair` 领走。不得改用 `pg_sleep`。
- `UPDATE effects SET attempt_no` 只允许出现在 `attempt_not_ok_skipped`：把已经 `ready` 的行改到 `v13_attempt_ok(kind, attempt_no)` 为假，然后断言 `v13_claim_fair` 返回 NULL、该行仍是 `ready`。`v13_enqueue_effect` 有余量才会重挂成 `ready`，构造不出这个状态。

驱动器路径不可以。

不 import `loop_driver`，不 import `goal_supervisor`，不复制 B1 五出口，不调用 provider，不构造 FakeLLM。领用不咨询模型。`no_real_provider` 只证明这条进程没有网络，也没有把 `V13_REAL_PROVIDER_AUTHORIZATION` 设成 `1`。

`goal_supervisor` 的禁止名单保持原样。监督进程不领用。公平驱动器不 `v13_advance`。两者可以同时存在：advance 提交出 `ready` 行之后，另一次事务里 `claim_one` 把它领走。这与今天「工人调用 `v13_claim`」是同一分段，只是工人改调新函数。本期不修改那个尚未存在的监督进程。

### 4.8 数据流

从已有入队到 effect 行，再到下一次领用。公平驱动器不出现在入队那一段。

1. 既有 SQL（`v13_enqueue_effect`，或 advance 里的既有臂）在**另一个已提交事务**里插入或重挂一行 `status='ready'`。身份仍是 `v13_effect_id`。本期不新造入队者。
2. 调用者在事务外决定 worker 名与 lease。没有模型步骤。
3. `claim_one` 打开 `READ COMMITTED` 事务，事务内只有 `v13_claim_fair`。
4. 函数校验参数与政策，取 13002，数 `claimed`。已满则 NULL，COMMIT，驱动器返回 None。effect 行不变。
5. 未满则一条不锁 effect 行的语句选出合格且排序获胜的 `effect_id`，WHERE 调用 `v13_fair_eligible(e.effect_id)`。在取得任何 effect 行锁之前先锁该根会话行；若 effect 所在会话不是该根，再锁这一把子会话。顺序固定为先根、后这一把子会话，不得反过来，不得再锁第三把会话。锁内重跑终态与 lifecycle；失败闭集同第 4.2 节第 7 步，则不 UPDATE，返回 NULL。然后才对选中 effect `FOR UPDATE NOWAIT`。不得在已持有 effect 行锁后再锁 `sessions`。`55P03` 则返回 NULL，不得等到 `statement_timeout`，不在同一次调用里改领另一根。
6. 再数一次帽。仍有余量且 `status` 仍是 `ready` 则按原赋值 UPDATE 那一行：`claimed`，`attempt_no+1`，`fence+1`，`lease_owner`，有限 `lease_until`。0 行则 NULL。
7. 返回六键。驱动器 COMMIT。13002 释放。此时还没有外部 IO。
8. 其后，**别的**已有路径用返回的 `attempt_no` 与 `fence` 调用 5 参 `v13_complete`。那不是 `claim_one`。complete 成功则行离开 `claimed`，帽席位释放。失败的 llm complete 写 `effect_done`，不写 `turn/material_spent`。收据仍只由 harness 收据臂写。本期领用的夹具用 `kind='llm'`，不是 `harness_turn`，所以不产生 material 候选。
9. 下一 tick 再次进入第 3 步。不在同一次 `claim_one` 里领第二行。

测试夹具插在第 1 步与第 8 步，用具名函数，不用驱动器。`created_at` 若在同一事务里都等于 `now()`，排序会退化为 `effect_id`。夹具因此在入队之后、领用之前，用测试文件里的 `UPDATE effects SET created_at` 写成严格递增的显式时间戳。做不到这句 UPDATE 就停并 `ASK_USER`，不得改用 `pg_sleep`。

并发两名工人：两个连接各跑一次 `claim_one`。13002 把两次公平领用串行。帽为 2、合格行为 3 时，两笔成功，第三笔 NULL。活体 `v13_claim` 从旁插入时，公平函数对选中 effect 用 `FOR UPDATE NOWAIT`。锁不到则 `55P03`，返回 NULL，不得等到 `statement_timeout`，不得在同一次调用里改领下一行。测试把 timeout 只当作挂死探测器，不断言毫秒阈值。

丢弃与重复：驱动器 COMMIT 成功但响应丢失时，行已经是 `claimed`。再次 `claim_one` 不会领到同一行，因为谓词只要 `ready`。不提供「按 effect_id 重放领用」。调用者若丢了返回值，只能从 `effects` 里按 `lease_owner = worker` 且 `status='claimed'` 找。本期不把这个查找放进驱动器，避免驱动器变成第二套状态读者以外的写者。测试可以直接 SELECT。这个窗口与活体 claim 相同：领用没有单独的收据事件。

乱序：后开始的事务若先拿到 13002，会先领走当前排序的第一名。这是锁的顺序，不是事件时间的顺序。不补发。

### 4.9 soak 合同

不是多日运行，不是 `pg_cron`，不是墙钟，不调用 `v13_quota_eligible` 去「快进窗口」。`transaction_timestamp()` 不可注入。配额政策行在 soak 前后 jsonb 必须相同。

种子：

| 种子 | 值 | 不是 |
|---|---|---|
| `claimed_cap` | 2 | 席位 8；不是产品并发能力证明。不存在则 `fair_claim` INSERT，不相等则装载 RAISE、不覆盖。也不是「至少为 2」的产品不变量 |
| `fair_soak_roots` | 4 | 席位常数 |
| `fair_soak_ticks` | 8 | Phase C 的 `supervisor_max_ticks=2`；也不是多日 tick |
| `fair_claim_retries` | 2 | 只用于 40P01 |
| `fair_snapshot_cap` | 32 | 扫描硬顶；省略数只是 0 或 1 |
| lease 上界 | 600000 ms | 不是活体 `v13_claim` 的上界。只是 `v13_claim_fair` 的闭区间上界；活体不设这道上界，测试仍可传更大的 `p_lease_ms` |

soak 不使用 FakeLLM / FakeTool。没有模型步骤可伪造。不得为了看起来像真链而加一个空 Fake。

脚本在测试里，不在驱动器里。驱动器每个 tick 只被调用一次 `claim_one`。测试在 tick 之间调用 `v13_complete`。四次入队用 `kind='llm'`。每次 `request` 必须互不相同，tick 7 的新行 `request` 也必须与 R1 原行不同，否则 `v13_effect_id` 命中 failed 重挂，effects 增量是 4 不是 5。不带 `logical_turn_id`。若 `v13_reject_bad_harness_request` 拒绝这种请求：停，消息 `v13: claim fair: ask_user`，不改成裸 INSERT。

时间戳设成 `T1 < T2 < T3 < T4`，分别属于根 R1..R4，各一行 ready，起始 in-flight 全 0。

| tick | 测试在调用驱动器之前做的事 | `claim_one` 的期望 |
|---|---|---|
| 1 | 无 | 领到 R1。测试不 complete |
| 2 | 无 | 领到 R2。此时 `claimed_count = 2` |
| 3 | 无 | NULL。R3、R4 仍是 ready |
| 4 | 用 tick 1 返回的 attempt/fence 对 R1 做 5 参 `v13_complete(..., 'failed', NULL)` | 领到 R3。R2 仍 claimed，R3 的 in-flight 为 0，即使 R1 上若还有更老的行也不在本脚本里 |
| 5 | 无 | NULL |
| 6 | complete R2 | 领到 R4 |
| 7 | complete R3 与 R4；再入队 R1 上一行新的 ready，`created_at` 晚于 T4 | 领到 R1 的新行 |
| 8 | 无 | NULL |

成功领用序列必须是 R1、R2、R3、R4、R1。NULL 不计入这个序列。任一根本次第二次成功领用出现之前，四个根都已经成功一次。任一时刻经由公平函数形成的 `claimed_count` 不超过 2。tick 3 与 tick 5 证明帽会挡住仍有 ready 的根，而不是把它们标成失败或 `unknown`。

事件：每次 `claim_one` 前后，events 行数不变。整个脚本的 events 增量 = 夹具被迫写入的事件数 + 测试自己调用的 `v13_complete` 写下的 `effect_done` 数（llm `failed` 只写 `effect_done`，不写 `llm/message`，不写 `turn/material_spent`）。sessions 增量等于 4 个根（不加子会话）。effects 增量等于 5（四行加 tick 7 的一行）。这些数字是脚本的精确计数，不是模糊上界。

这条 gate 退出码 0 允许声称的只有：在这 4 根、这 8 tick、这颗种子下，公平函数没有在帽内把第二笔给已经 in-flight 的根，驱动器没有写事件，配额政策没有被拨动。不允许声称：生产多日运行已执行；饥饿在任意交错下不存在；活体 `v13_claim` 也遵守帽；配额窗口已按加速时间验证。

### 4.10 明确不做

**C4 多 lane。** 无目录、无政策、无事件、无函数参数。Phase 0 把它放在 D，与四项命名交付冲突，已在第 2 节第 7 行停下并选择不做。不构成第二状态源，因为它没有状态面。

**PC-4。** 不实现根配额，不声称 goal 级配额，不声称无人值守多 spawn 预算。不升 `should_run`。T7 的形状本期不写，理由与 Phase C §4.11 相同：要写新门就必须抄 gate 全文，抄错会改变配额以外的布尔。

**PC-6。** `v13_claim_fair` 与 `driver.py` 不引用 `attention_rank`、`v13_attention`。不把秩接到领用。

**PC-8。** 不删 `v13_spawn_subsession` 的 cap RAISE，不接住它，不调用它。复活窗口仍不承诺零 RAISE，也不承诺绝对不超售。公平领用不创建子会话，因此既不修复也不扩大那个窗口。

**artifact 增长与成本可观测。** 不做。没有不增加事件种类、也不建表的载体。`attempts_used` 不新增。成本不是本期返回值。

**B3。** 无 cadence 目录。

**自动 skip。** 不实现。

**第二份 advance，第二份 enqueue，指纹换体，fanout 换体。** 不实现。

### 4.11 错误与边界

| 情况 | 结果 | 状态 |
|---|---|---|
| 池空 | NULL | 零写 |
| 帽满，仍有 ready | NULL | ready 保持 ready |
| 隔离级别不对 | `v13: claim fair: canonical` | 零写 |
| 政策缺失、重复、其它 version 或形状错 | `v13: claim fair: policy` | 零写。不得读任意 active 行 |
| worker 空、过长、或为 `v13_workspace_opener` | `canonical` | 零写 |
| lease 越界 | `canonical` | 零写 |
| 选出时根已 stopped | 该行不合格，不锁 effect 的 SELECT 不选它；可以选出别的根，或 NULL | 不写 events |
| 会话锁内重验失败 | 先根、后至多一把子会话，闭集同第 4.2 节第 7 步，不 UPDATE，返回 NULL | 不改领另一根，不得再锁第三把会话。不得在已持有 effect 行锁后再锁 `sessions` |
| 根已终态、子会话仍非终态且有合格 ready | 公平领用仍可领该行 | 指定行为，不是洞。不要加「终态根必须返回 NULL」断言 |
| `workspace_root` 不是绝对字符串，或 `paths` 为空 | `v13: workspace open: canonical`，不取 13003 | 零插入。不调用 `realpath`，不改打开者 |
| 上溯成环或深于 64 | 该行不合格，不 RAISE | 其它根仍可领 |
| 无 worktree latch 但工具要求 worktree | 不合格，与活体相同 | 零写该行 |
| `v13_attempt_ok` 为假 | 不合格 | 超帽 `ready` 行（`attempt_not_ok_skipped` 夹具人为制造）无自动终结路径——活体构造上仅策略翻新降 cap 才可达（fanout 注释自述），requeue 只处理 `claimed`；本期该行保持 `ready` |
| 与活体 claim 抢同一行 | 选中 effect `FOR UPDATE NOWAIT` 得到 `55P03`，或 UPDATE 0 行，返回 NULL | 不双领。不得超时，不在同一次调用里改领下一行。索引也不允许同一会话两行活跃 |
| 40P01 | 驱动器最多 2 次 | 无睡眠 |
| 过期 llm/tool | 测试若调用 `v13_requeue_stale`，行变 `unknown` 并起墙 | 帽释放。本期函数不这么做 |
| `infinity` 的 workspace `claimed` | 计入 `claimed_count` | 公平函数不改它 |
| 第二根上调用打开者 | `not_single_tree` | 零工作区 effect |
| 重叠路径经 `v13_path_conflict_locked` | `v13: workspace open: path_busy` | 调用者零新行 |
| 快照时政策缺失、重复、其它 version 或形状错 | `v13: fair snapshot: policy` | 零写。不得读任意 active 行 |
| 33 个根的快照 | 返回 32，`omitted_count=1` | 零写 |
| enqueue 在帽已满时 | 成功，只要会话上还没有活跃行 | 帽不拦入队 |
| driver 已在事务中 | Python `v13: claim fair: canonical` | 不调用 SQL |
| 同一次响应丢失 | 行已 claimed | 再次领用不会领同一行，也没有领用事件可重放 |

`v13_should_run` 为假不拦领用。`root_should_run_false_does_not_block_other_ready`：根会话有 human `ready` 且该根 `v13_should_run` 为假；子会话有 llm `ready`，其 `created_at` 早于 human；两边 in-flight 都是 0。`v13_claim_fair` 返回这个子会话 llm，human 保持 `ready`。`UPDATE effects SET created_at` 允许写在这个断言里。不把 `duty_cycle=0` 当夹具。不新增 block id。删掉「子会话或另一根」这种不定胜负的写法。

`stopped_root_not_fair_claimed` 与 `stopped_enqueue_raises` 互斥，第 7.1 节的 gate 只收其中一条。无 effect 时 `v13_goal_stop` 可以成功。enqueue 在 stopped 根上成功时只跑前一条：公平领用跳过该行，活体 `v13_claim` 仍可领走它。enqueue RAISE 时只跑后一条，README 写明公平跳过未动态执行。后一条通过只闭合 stopped 这一对；§7.1 其余断言仍须通过，才允许整个 `fair_claim` gate 标 `exit_0`。不要让两条同时成为必绿断言。不要两个都标成已测。

子会话终态必须在 UPDATE 前锁住：根会话 `FOR UPDATE` 之后、任何 effect 行锁之前，若 effect 所在会话不是该根，再锁这一把子会话。顺序固定为先根、后这一把子会话，不得反过来，不得再锁第三把会话。锁内重跑终态与 lifecycle；失败则不 UPDATE，返回 NULL。然后才对 effect `FOR UPDATE NOWAIT`。不得在已持有 effect 行锁后再锁 `sessions`。

## 5. 范围

### 5.1 在 D 内

- 一库多根的 `v13_claim_fair` 与 `v13_fair_snapshot`。
- 按根的 in-flight 公平。饥饿保护只指第 4.3 节那条。第 4.9 节的免责声明保留，不声称任意交错下没有饥饿，不新增轮转游标。
- `global_concurrency` version 1，锁内帽。
- 有界 soak 合同。
- 路径第二道闸与跨根 `path_busy` 复现（不经过打开者）。
- 对 C4 多 lane 与 PC-4 的明确不做。
- 对矩阵行 25、26、PC-4、PC-6、PC-8 的态度：不削弱席位与超售断言，不重开 PC-4，不把秩当调度，不修改复活窗口。

### 5.2 不在 D 内

- 修改 stage 1–29、fanout 字节、指纹函数、A/B/C 目录与计划。
- 替换 `v13_claim` 或 `v13_advance`。
- 新表、新列、新事件种类、工作流引擎、cadence、outbox、多 lane。
- 真实 provider、stannum GRANT、产品库名、产品角色证明。
- 多日墙钟运行、可注入的配额时钟。
- 释放 `infinity` claimed、把 unknown 墙改回 ready、无人值守 skip、无人值守 `plan_commit`。
- 扩展 `loop_driver` 或 `goal_supervisor` 的 SQL 允许名单。
- 把 `read_tools/` 加进 `SQL_LOAD_ORDER`，或调用 `v13/read_tools/setup_db.py`。

## 6. 目录、文件、追加

本规划轮不改 `v13/load.py`。实现时若表尾不是 `goal_supervise`，停。允许的动作只是在当时表尾追加，整数值为当时最大值 + 1。禁止插到 1–29 中间，禁止插到 `goal_supervise` 前面，禁止重排。不分配 30 或 31。

| 顺序 | 目录 | SQL | 键名 |
|---|---|---|---|
| `goal_supervise` 之后 | `v13/fair_claim` | `v13_fair_claim.sql` | `fair_claim` |
| 无加载键 | `v13/fair_driver` | 无 | 不分配 |

`fair_driver` 若发现自己必须有 SQL，或必须替换 claim / advance：停。

依赖与尾部顺序分开：

- `fair_claim` 的加载前缀含 1..29、Phase A 尾部直到 `real_chain`、`workspace_admit`、`frontier_gap`、`goal_supervise`。`v13_attempt_ok`、`v13_requires_worktree`、`v13_goal_lifecycle` 在 `v13_claim_fair` 函数体内调用。只有 `v13_enqueue_effect` 只在测试里，领用路径不调用它。`v13_tool_effect_open` 必须已存在，供「两个根仍是 `not_single_tree`」使用；不存在则停，不在本期重造打开者。
- `fair_driver` 依赖 `fair_claim` 已装。不依赖十二步链，不依赖监督进程。

### 6.1 文件清单

| 路径 | 动作 | 职责 |
|---|---|---|
| `v13/fair_claim/v13_fair_claim.sql` | 新建 | 政策、六个函数、触发器、REVOKE。路径函数另 `GRANT EXECUTE` 给 `v13_route`（已核：schema `:866` INSERT、`:892-897` EXECUTE 链），不 GRANT `v13_claim_fair`。无 `CREATE TABLE`，无 `ALTER TABLE`，无第二份 advance/claim |
| `v13/fair_claim/test_fair_claim.py` | 新建 | 第 7.1 节断言。夹具可调用活体具名函数 |
| `v13/fair_claim/README.md` | 新建 | 种子、行号、洞、残留、未证明产品角色 |
| `v13/fair_driver/driver.py` | 新建 | 只有 `claim_one` |
| `v13/fair_driver/test_fair_driver.py` | 新建 | 第 7.2 节，含 soak 脚本 |
| `v13/fair_driver/README.md` | 新建 | 第 7.2 节要求逐字存在的句子 |
| `v13/load.py` | 实现时只追加表尾一项 | 规划轮不改。键 `fair_claim` |
| `docs/reviews/v13-long-loop-phase-d-conformance-matrix-2026-09-29.md` | 实现里程碑新建 | 不是本规划轮 |
| `docs/reviews/v13-long-loop-phase-d-deviation-ledger-2026-09-29.md` | 实现里程碑新建 | 不是本规划轮 |
| stage 1–29、`v13/fanout/v13_fanout.sql`、A/B/C 目录、2026-09-26 矩阵与台账、三份已接受计划 | 不改 | 见第 2 节 |

没有产品库迁移。一次性测试库不装载 `fair_claim` 即无此行为；已装载库无 DOWN 脚本。测试库一次性创建。不读 `global_concurrency` 的旧函数不受新政策行影响；但路径触发器会改变旧调用路径带 `workspace_root` 的 INSERT 行为（非 `READ COMMITTED` 拒绝、`path_busy`）。新政策行留在 `v13_policies` 里，对不读该行的旧代码是无关行。不写 DOWN 脚本去改 stage 1–29。

## 7. 分期合同

本规划轮没有跑本节任何命令。命令退出码 0 只是将来实现里程碑的通过条件。Fake 绿不是产品可用。

矩阵与台账是实现里程碑才创建的新文件。不改 Phase 0 / A / B / C 的矩阵、台账、计划与证据，也不改 2026-09-26 那两份。

列：条目，目录，允许的声称，证据指针，状态。状态从 `not_run` 起。只有对应 gate 退出码 0 之后，该行才能写成 `exit_0`，并带上命令、退出码与库名。不设 `real_authorized_exit_0`。本文的存在不是证据。`fair_claim` 的里程碑创建全表骨架，`fair_driver` 行先 `not_run`。后一个里程碑只改自己的行。

公共纪律：双连接阻塞断言用 `pg_locks` 有界轮询确认等待，不用 `pg_sleep`。新建一次性库；名字不得匹配 `agent_v13_%`，不得使用 `agent_v13_longloop_p0_probe`；已存在则拒绝并退出，不 DROP；清理只 DROP 本次创建成功的那一个；现有库不得 DROP。先装 1..29 到 govern，再装已落地的 A/B/C 尾部直到 `goal_supervise`，再装本期直到该测试的键。不调用 `v13/read_tools/setup_db.py`。超级用户不是产品角色证明，超级用户夹具不证明生产可运行。新函数 `REVOKE EXECUTE FROM PUBLIC`。路径函数另外 `GRANT EXECUTE` 给 `v13_route`（已核：schema `:866` INSERT、`:892-897` EXECUTE 链）；不得 GRANT 给 `PUBLIC`，不得 GRANT 给 stannum，不得因此 GRANT `v13_claim_fair`。

证据：命令、退出码、一次性库名、断言名、相关 event / effect 计数。本规划轮没有这些退出码。

### 7.1 `v13/fair_claim`

交付：政策行，`v13_claim_fair`，`v13_fair_eligible`，`v13_fair_snapshot`，路径函数与触发器。无驱动器循环，无 provider，无 advance 替换。

依赖：第 6 节。无本期前驱键。

Gate：`UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py`。本规划轮未跑。

断言：

- `policy_seed_idempotent`
- `policy_rejects_unequal`
- `policy_keys_closed`
- `cap_seed_is_2`（`fair_claim` 在政策不存在时插入 `claimed_cap=2`。不相等则装载 RAISE，不覆盖。不是「stage 不插入」）
- `spawn_budget_seed_unchanged`（active `spawn_budget` 仍是活体那份 jsonb。这是回归钉。README 写「不是全局帽」）
- `should_run_version_still_3`
- `no_new_should_run_block`
- `live_claim_body_unchanged`
- `hashes_unmodified`（装载本 stage 前后：`v13_claim`、`v13_advance`、`v13_goal_fingerprint`、`v13_scheduler_hint`、`v13_recover_idle`、`v13_requeue_stale`、`v13_enqueue_effect`、`v13_should_run`、`v13_should_run_gate`、`v13_quota_eligible`、`v13_advisory_class`、`v13_spawn_subsession`、`v13_spawn_occupancy`、`v13_tool_effect_open`、`v13_goal_lifecycle`、`v13_goal_stop`、`v13_attempt_ok`、`v13_requires_worktree`）
- `fair_claim_returns_six_keys`（成功对象恰好六个键 `effect_id`、`attempt_no`、`fence`、`kind`、`request`、`root_session_id`，缺键或多项失败）
- `fair_claim_bumps_attempt_once`
- `fair_claim_bumps_fence_once`
- `fair_claim_lease_finite`
- `fair_claim_rejects_opener_owner`
- `lease_above_600000_rejected`（只断言 `v13_claim_fair`。600000 ms 只是该函数的闭区间上界。活体 `v13_claim` 不设这道上界，测试仍可传更大的 `p_lease_ms`）
- `isolation_not_read_committed_rejected`
- `empty_pool_returns_null`
- `enqueue_not_capped`（4 个根各一行 ready，帽为 2，四次 enqueue 都成功）
- `cap_blocks_third_claim`（两笔 `claimed` 未完成时，第三笔公平领用 NULL，第三行仍 `ready`）
- `ready_does_not_consume_cap`
- `unknown_does_not_consume_cap`（把公平领走的 llm 的 `lease_until` 改到过去，调用未改过的 `v13_requeue_stale`，断言该行已是 `unknown`、不计入 `claimed_count`，且另一根的 `ready` 仍可被 `v13_claim_fair` 领走。不得改用 `pg_sleep`。这是 `UPDATE effects SET lease_until` 白名单的第二处）
- `infinity_claim_holds_cap`（打开者留下的 `infinity` 行计入 `claimed_count`；公平函数不改那一行）
- `eligible_matches_live_claim_on_shared_arms`（在无跨会话污染的夹具数据上——相关会话 latch 状态一致或无 worktree 要求、每会话单一 `mutation_scope`、`op_seq` 统一 NULL——逐行一致。「公平可选集 ⊆ 行自身四臂集合」。不写无条件的「真子集」断言。加上 effect 所在会话的终态、不可解析上溯、stopped 之后，公平可选集是活体可选集的子集；差集见证由实际执行的那条断言提供（stopped 二选一、终态会话、不可解析上溯夹具），不依赖互斥的 `stopped_root_not_fair_claimed`。不要写全体相等断言）
- `peer_idle_beats_older_sibling_backlog`（根 A 的 `claimed` 行与更老的 ready 分属该根下两个会话；根 B 的更年轻 ready 的 `created_at` 更晚；公平领用返回根 B。允许该断言 `UPDATE effects SET created_at`）
- `tie_oldest_created_at`
- `tie_effect_id`
- `stopped_root_not_fair_claimed` / `stopped_enqueue_raises`（互斥，gate 只收其中一条。enqueue 在 stopped 根上成功时只跑前一条：公平领用跳过，活体 `v13_claim` 仍可领走。enqueue RAISE 时只跑后一条，README 写明公平跳过未动态执行；后一条通过只闭合 stopped 这一对；§7.1 其余断言仍须通过，才允许整个 `fair_claim` gate 标 `exit_0`。不要让两条同时成为必绿断言）
- `live_claim_still_claims_when_cap_full`（帽满后活体 `v13_claim` 仍能领走。这是洞的证据，不是把洞标成已闭合）
- `root_should_run_false_does_not_block_other_ready`（根会话有 human `ready` 且该根 `v13_should_run` 为假；子会话有 llm `ready`，其 `created_at` 早于 human；两边 in-flight 都是 0。`v13_claim_fair` 返回这个子会话 llm，human 保持 `ready`。允许该断言 `UPDATE effects SET created_at`）
- `worktree_without_latch_skipped`
- `attempt_not_ok_skipped`（只允许在该断言里 `UPDATE effects SET attempt_no`，把已经 `ready` 的行改到 `v13_attempt_ok(kind, attempt_no)` 为假，然后断言 `v13_claim_fair` 返回 NULL、该行仍是 `ready`。不允许 `INSERT INTO effects`）
- `nowait_does_not_wait`（另一连接持有选中 ready 的行锁；公平领用 `FOR UPDATE NOWAIT` 得到 `55P03` 则返回 NULL，不得等到 `statement_timeout`，不改领下一行。这不是活体 `v13_claim` 的 `SKIP LOCKED`）
- `two_fair_claimers_respect_cap`
- `snapshot_zero_write`
- `snapshot_two_calls_identical`
- `snapshot_orders_by_root_id`（`root_session_id::text COLLATE "C"`，不随库 locale 改变数组序）
- `snapshot_cap_33`
- `snapshot_does_not_raise_on_occupancy`（新函数源码不含 `v13_spawn_occupancy`）
- `occupancy_counts_one_root`（两根各有一个非终态子会话时，两边的 `v13_spawn_occupancy` 都只数自己的后代）
- `no_new_event_type`
- `fair_claim_adds_no_event`
- `fingerprint_function_unmodified`
- `path_busy_two_roots_two_connections`（第 4.6 节的 A/B 剧本。连接 B 也必须是 `READ COMMITTED`，且两边的 `workspace_root` 必须通过取锁前的绝对字符串检查；否则会在取 13003 之前 RAISE，复现不了阻塞。令牌 `v13: workspace open: path_busy`，败者零新行）
- `path_guard_rejects_non_read_committed`（任何带 `workspace_root` 的 INSERT，包括既有 `v13_enqueue_effect`、`v13_tool_effect_open`、advance 臂的调用者，事务不是 `READ COMMITTED` 时触发器 RAISE `v13: workspace open: canonical`，零插入。不改这些函数的字节。不要求实现前审计每一个历史写者）
- `path_guard_execute_reaches_recheck`（超级用户连接 `SET ROLE v13_route`，非超级用户身份、`READ COMMITTED`、插入一行合法 `workspace_root` tool effect，必须到达路径复检或 `path_busy`，不得是 `42501`。该证明只覆盖直接 enqueue 路径，不是打开者路径。做不到则停，不得删断言。路径函数保持 `REVOKE EXECUTE FROM PUBLIC`，另外 `GRANT EXECUTE` 给 `v13_route`（已核：schema `:866` INSERT、`:892-897` EXECUTE 链）；不得 GRANT 给 `PUBLIC`，不得 GRANT 给 stannum，不得因此 GRANT `v13_claim_fair`）
- `path_distinct_ab_not_busy`
- `overlapping_root_strings_are_busy`
- `two_roots_opener_still_not_single_tree`（已落地正文复验：打开者仍 RAISE 已落地的 `not_single_tree`）
- `opener_source_still_has_not_single_tree`（已落地正文复验：`v13_tool_effect_open` 源码仍含该令牌）
- `requeue_wall_unchanged_frees_cap`（把公平领走的 llm 的 `lease_until` 改到过去，调用未改过的 `v13_requeue_stale`，该行变 `unknown`。活体 unknown 墙仍会升起并保持，席位释放。`claimed_count` 下降，另一根的公平领用可以继续）
- `no_table_no_column`
- `no_second_advance_replace`
- `advisory_class_function_unmodified`
- `hint_unmodified`
- `quota_policy_unchanged`
- `stage_bytes`

断言名单不包含「终态根必须返回 NULL」。根已终态、子会话仍非终态且有合格 ready 时，公平领用仍可领该行。这是指定行为，不是洞。

`stage_bytes`：相对本提交的父提交，stage 1–29、fanout 文件、已接受的 Phase 0/A/B/C 计划、以及第 5.2 节点名的目录 diff 为空；`load.py` 只在表尾增加 `fair_claim`。

`hashes_unmodified` 里的 Phase A/B/C 函数，若前缀还没装上：整个 stage 停，不把缺失写成哈希相等。

提交边界：`v13/fair_claim/`，`v13/load.py` 的这一次表尾追加，两份新评审文件的骨架与本行，本目录 README。

README 必须写下：种子 2/4/8/32 与 lease 上界；`fair_claim` 在政策不存在时插入 `claimed_cap=2`，已有不相等行则装载 RAISE、不覆盖；spawn `:24-25` 的重读结果；`v13_goal_lifecycle` 的 volatility；stopped 分叉只测 `stopped_root_not_fair_claimed` 与 `stopped_enqueue_raises` 其中一条，enqueue RAISE 时写明公平跳过未动态执行，后一条通过只闭合 stopped 这一对，§7.1 其余断言仍须通过才允许整个 fair_claim gate 标 exit_0；`v13_reject_bad_harness_request` 是否接受夹具 llm 请求；13002 与 13003；「帽不约束活体 `v13_claim`」；「`infinity` 占席且本期不释放」；「`cap=1` 连续领用残留只指仍回到 ready 的路径，不是过期 claimed 转 unknown，也不是 attempt 耗尽转 failed」；「根会话 FOR UPDATE 之后、任何 effect 行锁之前，若 effect 所在会话不是该根，再锁这一把子会话；顺序先根后子，不得反过来，不得再锁第三把会话；不得在已持有 effect 行锁后再锁 sessions」；「13002 在会话行锁之前取得；排头的会话锁等待会阻塞所有后续公平领用；活体 v13_claim 不取 13002」；「path_guard_execute_reaches_recheck 的 SET ROLE 证明只覆盖直接 enqueue 路径」（两种重读结果都要有）；打开者路径身份句按第 9 节重读结果二选一写入，README 测试按重读结果查找对应那一句，不得两句都要求：打开者是 `SECURITY DEFINER` 时写「打开者路径上触发器嵌套函数的运行时身份是打开者 owner，不是外层 SET ROLE」；是 INVOKER 时写「打开者路径上触发器嵌套函数的运行时身份是调用时的有效身份」；「未证明产品角色」；「未证明 material 已扣」；「64 只是上溯守卫」；「有限租约过期后，席位只有在外部调用未改过的 v13_requeue_stale 时才释放；fair_driver 不是这个调用者」。

按 AGENTS.md，这条 gate 实跑全绿并且收尾工件写完之后，才允许路径级提交并推送。本规划轮不做。提交信息形状：`v13: add multi-goal fair claim and global claimed cap`。禁止 `git add -A`。禁止纳入 `uv.lock`、`prompt-exports/`、调查、stage 1–29、A/B/C 目录、2026-09-26 矩阵、父循环 memory。禁止 force、`reset --hard`、自动 stash、跳 hook。

### 7.2 `v13/fair_driver`

交付：`claim_one` 与第 4.9 节 soak。无加载键，无 SQL。

依赖：`fair_claim` 已装。

Gate：`UV_FROZEN=1 uv run python v13/fair_driver/test_fair_driver.py`。本规划轮未跑。

断言：

- `claim_one_read_committed`
- `already_in_transaction_rejected`
- `null_does_not_retry`
- `deadlock_retries_at_most_2`（证据面是驱动器单元注入，不是真实库死锁。测试在 DB-API 层注入一次或两次 `40P01`，断言重试至多 2 次、无睡眠、第二次仍失败则抛出。会话锁至多两把，顺序先根后子，effect 仍是 `NOWAIT`。不得因此把 stage 停在 `ask_user`。不得改成真实库死锁）
- `static_check`
- `no_insert_in_driver_or_test`
- `driver_does_not_update`
- `no_material_spent`
- `no_real_provider`
- `no_sleep_no_cron`
- `no_fake_llm_required`
- `soak_sequence_r1_r2_r3_r4_r1`
- `no_second_claim_before_each_root_once`
- `soak_cap_never_exceeded`
- `soak_claim_adds_no_event`
- `soak_row_counts`（sessions +4，effects +5；events 增量 = 夹具被迫写入的事件数 + 测试自己调用的 `v13_complete` 写下的 `effect_done` 数。llm `failed` 只写 `effect_done`）
- `soak_quota_policy_unchanged`
- `soak_not_multiday`（README 含第 7.2 节的句子）
- `attention_not_referenced`
- `hint_not_called`
- `live_claim_not_called_by_driver`
- `supervisor_allowlist_not_edited`（不改 `goal_supervisor` 路径；若该目录尚未落地，停，不创建它）
- `c4_multilane_absent`
- `pc4_not_reopened`
- `stage_bytes`（无 `load.py` 改动；第 5.2 节目录 diff 为空）

README 必须含下列句子，测试按子串查找，缺一句即失败：

- `加速夹具不是多日生产运行。真实多日运营仍未授权。`
- `v13_quota_eligible 使用 transaction_timestamp()，不可注入。本 soak 不证明配额窗口。`
- `fair_claim 在政策不存在时插入 claimed_cap=2。这个种子不是产品并发能力证明，也不是 spawn_budget 的 8/4/8。已有不相等行则装载 RAISE，不覆盖。`
- `公平不写入事件。v13_goal_fingerprint 不改。`
- `活体 v13_claim 不看 global_concurrency。帽只约束 v13_claim_fair。`
- `not_single_tree 仍在打开者里。跨根 path_busy 不经过打开者。`
- `PC-4 保持关闭。`
- `C4 多 lane 不在本期实现。`
- `有限租约过期后，席位只有在外部调用未改过的 v13_requeue_stale 时才释放；fair_driver 不是这个调用者。`
- `本驱动器不是无人值守监督进程，也不授权离开生产终端。`

提交边界：`v13/fair_driver/`，矩阵与台账的本行，README。不含 `load.py`。提交顺序在 `fair_claim` 之后。提交信息形状：`v13: add fair claim driver and bounded multi-root soak`。路径级 add 的禁令与上一节相同。

## 8. 追溯

Phase 0 §7 的归属不改。

| 项 | 归属 | 本计划 |
|---|---|---|
| G4 公平、饥饿、多日 soak | D | `fair_claim` 的排序与帽；`fair_driver` 的 8 tick。不是墙钟多日。饥饿保护只指第 4.3 节那条，不声称任意交错下没有饥饿，不新增轮转游标 |
| G4 单 goal 续租与崩溃行 | C | 不重做。`infinity` 行继续占帽。不调用 `v13_goal_lease_once` |
| 一库多 goal 领用查询 | Phase 0 §10，归 D | `v13_claim_fair`。不替换 `v13_claim` |
| C4 多 lane | Phase 0 写在 D | **本期不做**，第 2 节第 7 行。无状态面 |
| PC-4 | 可后期；Phase C 已关闭 | 保持关闭 |
| PC-6 | 秩不是调度 | 不接入 |
| PC-8 | 复活窗口不承诺零 RAISE / 绝对不超售 | 不削弱，不调用 spawn |
| 矩阵行 25 | 双根互不占 spawn 席位 | `occupancy_counts_one_root` 再钉一次。全局帽不是这张席位 |
| 矩阵行 26 | 并发 sibling 无超售 | 不改 `v13_spawn_subsession`。不把 cap RAISE 接住 |
| B3 | A 的不做项 | 无目录 |
| 无人值守 skip | 未授权 | 不做 |
| A/B/C 已写的写者、打开者、监督进程 | 已接受计划 | 不编辑。领用是新的调用者 |

不得声称：有过 plan 事件即放行；活体最老优先已经是多 goal 公平；session-local 配额就是 goal 级；有循环即无人值守已通；Fake 绿即产品可用；soak 退出码 0 等于多日运行已完成。

## 9. 开工重读与 ASK_USER

实现先做这些重读。任一停点成立：不写绕过代码，不改 stage 1–29，不替换 `v13_claim` 或 `v13_advance`，不把该 stage 标成 `exit_0`。

| 重读 | 停点 |
|---|---|
| `SQL_LOAD_ORDER` 表尾 | 不是 `goal_supervise`。停。不补前置键 |
| 函数名、目录名、`13002`、`13003`、政策名 `global_concurrency` | 已存在。停，不静默改名 |
| fanout `v13_claim` 正文 | 开工只复读已装载的 `v13_claim` 的 `pg_get_functiondef`。对不上第 4.3 节的四臂散文则停。正文含大段注释，行号易漂；注释块不是谓词。不要改 fanout。新函数不得少掉 `v13_attempt_ok`、`op_seq`、`v13_requires_worktree` |
| `v13_advisory_class` | 除 `spawn_budget → 13001` 外还有别的类，或 13001 已变。停。不改该函数 |
| `v13_goal_lifecycle` 签名与 volatility | 不是 uuid 进、text 出。停。VOLATILE 则合格函数不得假称 STABLE |
| `v13_reject_bad_harness_request` 对夹具 llm 请求 | 拒绝。停，消息 `v13: claim fair: ask_user`。不裸 INSERT |
| `effects.created_at` / `lease_until` 能否由测试 UPDATE | 不能。停。不用 `pg_sleep` 代替 |
| stopped 之后 `v13_enqueue_effect` | 二选一写进 README。enqueue 成功则只跑 `stopped_root_not_fair_claimed`。enqueue RAISE 则只跑 `stopped_enqueue_raises`，README 写明公平跳过未动态执行，后一条通过只闭合 stopped 这一对；§7.1 其余断言仍须通过，才允许整个 `fair_claim` gate 标 `exit_0`。不要两条都标成必绿，也不能既标成「已跳过」又标成「无法构造」 |
| `v13_tool_effect_open` 是否仍含 `not_single_tree` | 不含该令牌：停，不在本期重写打开者。路径函数保持 `REVOKE EXECUTE FROM PUBLIC`，另外 `GRANT EXECUTE` 给 `v13_route`（已核：schema `:866` INSERT、`:892-897` EXECUTE 链）。不得 GRANT 给 `PUBLIC`，不得 GRANT 给 stannum，不得因此 GRANT `v13_claim_fair`。断言执行面用超级用户连接 `SET ROLE v13_route`（非超级用户身份、`READ COMMITTED`）。该证明只覆盖直接 enqueue 路径。`path_guard_execute_reaches_recheck` 若是 `42501`，或到不了路径复检 / `path_busy`：停，不得删断言 |
| `v13_tool_effect_open` 是否 `SECURITY DEFINER` | 开工记录是否 DEFINER。触发器函数的 EXECUTE 权限在 `CREATE TRIGGER` 挂载时检查，点火时不重新检查 EXECUTE。触发器体内对嵌套函数（`v13_workspace_path_guard` → `v13_path_conflict_locked`）的运行时权限检查，按当时有效身份：经 INVOKER 的直接 enqueue 路径插入时，身份是 `SET ROLE` 后的 `v13_route`；经 `SECURITY DEFINER` 打开者插入时，身份是打开者 owner，不是外层会话的 `SET ROLE` 身份。因此 `path_guard_execute_reaches_recheck` 的「`SET ROLE v13_route`」证明范围只覆盖直接 enqueue 路径。打开者路径的运行时身份按重读结果记 README：DEFINER 时是打开者 owner，不是外层 `SET ROLE`；INVOKER 时是调用时的有效身份 |
| 触发器与打开者锁序 | 必须改打开者才能避免死锁。停 |
| 40P01 不能稳定复现 | 不构成停点。`deadlock_retries_at_most_2` 用 DB-API 注入，见第 7.2 节。不得改成真实库死锁，也不得删断言 |
| 任何合同只有 `CREATE OR REPLACE v13_claim` 或第二份 `v13_advance` 才成立 | 停。第 1 节 |
| 父要求打开者在两个已提交根上返回 `path_busy` | 停。不造第二套打开者 |
| 父要求 PC-4、多 lane、新事件种类、或把 8/4/8 写成全局帽 | 停。整组退回，不在实现里换一套 |

另外保持未决，不得写成已核：产品库名、产品角色、stannum GRANT、V11、真实 provider 授权、stopped 上的 `user/message` 是否改变领用（领用不读水位）、`steer/injected`。`claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色。超级用户夹具不证明生产可运行。本期仍不给 `v13_claim_fair` GRANT，不写 stannum GRANT。产品执行角色若要调用它，还须另持 `v13_goal_lifecycle`、`v13_attempt_ok`、`v13_requires_worktree` 的 EXECUTE；那条链本期不证明。

## 10. 四项裁决

用户把 Mid-flow 的四个取舍交给 Oracle。group `40BFBEDD-9B00-4B33-A9BD-A93E2335404A`。完成的 grok `new-chat-49AA14` 与 codex `new-chat-oracle-2-D4CC41` 选项一致。这不是 stage 通过，也不是产品可用。实现不得换成下面被否决的形状。

| 题 | 裁决 | 不得改成 |
|---|---|---|
| 第二递增入口 | `accept_second_entry`：`v13_claim_fair` 一次 `attempt_no+1`、`fence+1`，不替换活体 `v13_claim` | 把 `attempt_no` 留在 0；`CREATE OR REPLACE v13_claim`；改 fanout 字节 |
| 帽的洞 | `accept_hole`：帽只约束 `v13_claim_fair`；活体 `v13_claim` 帽满仍可领 | 用触发器拦所有 `ready→claimed`；把帽放进 `should_run` version 4 或 hint；把 8/4/8 写成全局帽 |
| C4 多 lane | `exclude`：本期不实现 | 给领用函数加 lane 参数、政策、表或事件 |
| 路径竞态 | `trigger_not_opener`：新函数加触发器；打开者仍 RAISE `not_single_tree` | 编辑 `v13_tool_effect_open`；删 `not_single_tree`；让打开者返回 `path_busy` |

下列其余选择仍是本计划合同，不是另一次产品投票：

- 新函数 `v13_claim_fair`，不 `CREATE OR REPLACE v13_claim`。它是第二个 `attempt_no` / `fence` 递增入口，一次 +1。活体函数字节不动。
- `claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色。超级用户夹具不证明生产可运行。本期仍不给 `v13_claim_fair` GRANT，不写 stannum GRANT。不扩展 `loop_driver` 与 `goal_supervisor` 的允许名单。
- 帽是全库 `claimed` 行数。政策 `global_concurrency` version 1。`fair_claim` 在政策不存在时插入 `claimed_cap=2`；jsonb 相等则跳过；不相等则装载 RAISE、不 UPDATE。这个种子不是产品并发能力证明。不数 `ready`。下限是 1，不是「非终态会话数」。不升 `should_run` version。
- 活体 `v13_claim` 可以突破这顶帽。不加触发器去堵这个洞。
- 公平单位是根。排序是 in-flight `claimed` 升序，然后 `created_at`，然后 `effect_id`。没有轮转游标，没有新事件。`cap=1` 连续领用残留只指仍回到 `ready` 的路径：`judge` / `mgraph_consolidate` 经未改的 `v13_requeue_stale`（仅 attempt 仍有余量），或 `failed|cancelled` 经 `v13_enqueue_effect` 重挂。`failed` + `lease_exhausted` 只属于 `judge` / `mgraph_consolidate` 的 attempt 耗尽。tool/llm 过期只走 `unknown` 并起墙。
- 领用不看 `should_run`、hint、attention。跳过 stopped 根与不可解析的上溯。
- `v13_claim_fair` 的 lease 只允许 1..600000 毫秒，缺省 60000。600000 ms 只是该函数的闭区间上界。活体 `v13_claim` 不设这道上界，测试仍可传更大的 `p_lease_ms`。拒绝 `infinity`，拒绝 worker 名 `v13_workspace_opener`。
- 路径：触发器加 `v13_path_conflict_locked`，咨询锁类 13003，事务内释放。不编辑打开者，不删除 `not_single_tree`。跨根 `path_busy` 由新函数在两个连接上复现，不由打开者复现。
- 领用先取 13002，再锁选中根的会话行；若 effect 所在会话不是该根，再锁这一把子会话，然后才对选中 effect `FOR UPDATE NOWAIT`。顺序固定为先根、后这一把子会话，不得反过来，不得再锁第三把会话。不取 13003，不取 13001。不得在已持有 effect 行锁后再锁 `sessions`。不得做成「先锁 effect 再锁 session」。
- C4 多 lane 不实现。
- PC-4 保持关闭。
- soak 是 4 根、8 tick、无睡眠、无 FakeLLM。不证明配额窗口，不证明多日运行。
- PC-6 不接入。PC-8 不削弱。artifact 增长与成本可观测不做。
- 不改 2026-09-26 的矩阵与台账。新建本期两份评审文件。
- 零新表、零新列、零新事件种类。

上表四项已经裁决。不得在实现里换成 `CREATE OR REPLACE v13_claim`，也不得加成 `should_run` version 4。

本规划轮未跑：

- `UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py`
- `UV_FROZEN=1 uv run python v13/fair_driver/test_fair_driver.py`

它们是计划，不是通过。实现里程碑还要按 AGENTS.md 的顺序：对应 gate 实跑退出码 0，更新该 stage README、本期矩阵与台账、以及仅有的那一次 `load.py` 表尾追加，然后按路径 `git add`、提交、推送。本规划轮不提交、不推送。规划文档本身何时进仓库，由父决定。

## 11. 引用

- `docs/plans/v13-long-loop-plan-2026-09-28.md` — Phase 0 权威。§2、§7、§9、§10、T7。
- `docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md` — 唯一计划中的 `v13_advance` 替换；禁止改 fanout 字节。
- `docs/plans/v13-long-loop-phase-b-plan-2026-09-29.md` — `not_single_tree` 与多根路径竞态的移交。
- `docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md` — PC-4 关闭；`supervisor_max_ticks=2` 不是多日 soak。
- `v13/fanout/v13_fanout.sql:266` — 活体 `v13_claim`，全局 ready 池。不得改字节。
- `v13/spawn/v13_spawn.sql:24-25` — `spawn_budget` 活体种子 8/4/8。`:32-36` 的 `v13_advisory_class` 对 `spawn_budget` 返回 13001。`:423` 按根上锁。
- `v13/schema/v13_core.sql:128-129` — 每会话至多一个 `ready|claimed`。
- `v13/quota_window/v13_quota_window.sql:94-99` — 配额只计本 session。时钟是 `:93` 的 `transaction_timestamp()`，不可注入。
- `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` — 行 25、26 不削弱。本期不改该文件。
- `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` — PC-4、PC-6、PC-8。本期不改该文件。
- `docs/investigations/v13-long-loop-workflow-borrowing-gap-2026-09-28.md` — 非权威。切片 4 被 Phase 0 收进 D，但不自动成为交付。


