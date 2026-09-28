# v13 长循环 Phase A 计划（2026-09-29）

**状态：合同复审 group `E4759295-BD50-405C-8E6E-D0D5367BD73D`，完成的 grok 与 kimi 两路均为 P0=0、P1=0。codex 402 不是内容分。其后只改本轮 P2 措辞。未实现。未跑 gate。未提交。** 未调用真实 provider。未改 `v13/load.py`，未改 stage 1–29。

本文只规划 Phase A：控制链，加上首期真链，含 G2，以及这条真链必要的 read 注册与接线。不是 Fake-only 期。不是 Phase B/C/D。不是 v14/v15。不是外层 LoopX/RP-CE wrapper。PG 是唯一控制语义 owner。外部 IO 不进事务。不建第二状态源，不建工作流引擎，不建新表。

权威是 `docs/plans/v13-long-loop-plan-2026-09-28.md`。本文不改写其中的用户决定与技术裁决。调查 `docs/investigations/v13-long-loop-workflow-borrowing-gap-2026-09-28.md` 不是权威。冲突时按 Phase 0，并在第 2 节点名。初稿来自 Oracle group `9B15EE78-B66C-4178-B793-FB8F6B7328B7` 的主 lane（chat `new-chat-A4CA8A`）。pair 按活体重读修订了主 lane。另外两 lane 是另一份草稿，不并入本文，避免两套控制面。本地导出不是接受条件。

重读行与未读项记在 `docs/reviews/v13-long-loop-phase-a-plan-evidence-2026-09-29.md`。该文件不是 gate 通过证明。

## 1. 状态

交付物是这一份候选计划。运行时不在本轮。A 仍未审核，不得按本文开工，直到父复审另有决定。B/C/D 仍是 Phase 0 §9 的未审核占位。

Phase 0 点名的臂，本文不改行号：spawn `:805-808`，approval `:894-897`，continuation `:941-944`，收据 `:862-866`，`context_refresh` `:1012`，预算 human `:1027`，`resolve_budget` `:996`，judge `:1043`，`v13_triage_steer` `:1056`，`v13_route` `:1060`，`CASE` `:1089`，会话锁 `:737`，终态先返回 `:754-756`。explore RAISE 仍是 `v13/triage/v13_triage.sql:529`。本轮未重跑该测试。本轮重读了 spawn 臂的真分支 `:790-829`：`:805-808` 仍是 `should_run` 为假时返回 `waiting`；`:814-816` 在真分支里调用 `v13_spawn_subsession`。计划门不得插入这段内部。

## 2. 优先级与冲突

1. Phase 0 §2 的用户决定，以及本轮把范围钉在 Phase A。不改 stage 1–29 字节，不改父循环 memory，不改指纹函数，不改 `v13/fanout/v13_fanout.sql`。
2. Phase 0 技术裁决 T0–T7。本文引用，不改写。
3. 第 5 节的 Phase A 选择。它们只填 Phase 0 §10 当时未冻结、而写者又必须有唯一答案的空位。父可以退回。退回前不得另写一套控制面。
4. 调查。与 Phase 0 冲突则调查作废。

五个驱动器出口不是新的 `v13_advance` 返回词。活体 `terminal` 与 `waiting` 保留，包括 `:754-756` 的终态先返回。`wait`、`user_action`、`provider`、`stopping` 只存在于驱动器出口，不写进 `v13_advance`。活体返回词的完整闭集本轮没有编目；`plan_arm` 开工时重读全文并记录正文哈希，不得靠本文补一份返回词表。

调查冲突（不跟随）：

| # | 调查 | 本文 |
|---|---|---|
| 1 | 计划门放进 `should_run`，策略升到 v4 | T1.3：单独只读谓词。不是新 block id。不把布尔改成「无计划即假」。活跃策略 version 维持 3 |
| 2 | `plan/superseded` | 不建该种类。替换是新的 `plan/committed`，`supersedes` 指向旧 `plan_id` |
| 3 | 切片 1a 以 Fake-only 变绿分期 | A 不是 Fake 期。Fake 绿不是产品可用 |
| 4 | B3 考虑 `scheduler/applied` | T5：不建 cadence ACK。无目录。C/D 不得重开 |
| 5 | C5 用 operator `complete(skip)` 当超时解卡 | T2：无人值守 skip 未授权。等待保持非终态。不把 skip 写成解卡器 |
| 6 | 抄 LoopX 64/8/5 与席位常数 | 不把未核的 64 或 8 写成 A3 常数。活体 `v13/spawn/v13_spawn.sql:401` 的 `v_depth > 64` 是另一处深度守卫，本文不复用、不修改 |
| 7 | `v13_apply_plan` 把两种调用混成一次 | 一个具名 SQL，两个 `call_kind`。不用这个函数名 |
| 8 | D17 重开「第二状态源？」 | T1 已裁：事件加 STABLE 折叠，不建表 |
| 9 | 驱动器看见 `workflow_id` 就 spawn | 不建第三条循环。子会话只由活体 advance 的 spawn 臂调用 `v13_spawn_subsession`。驱动器不调用该函数 |
| 10 | `judgment_templates` 当工作流目录 | 隔离 gate 没有退出码 0。不读、不写、不迁移该表。版本化 `v13_policies` 行加新的 STABLE 解析器 |

## 3. 范围

### 3.1 在 A 内

A1、A2、A3、A4、B1、B2、B6、C1、C2 的合同（不是工具子集交付）、C3、C4 的首期真链部分、C7、G2，以及这条真链必要的 read 注册与接线。

确定性 gate 用 FakeLLM/FakeTool。真实 provider 验收是同一条路径上的另一条命令，须另行授权。本规划轮不调用。一库一树，一根，一个 goal。claim 仍是全局池。测试库不得出现第二棵树。不改 fanout SQL。

### 3.2 不在 A 内

- B3：不建 cadence ACK、`scheduler/applied`、RRULE、scheduler 状态表、新收据。没有目录。C/D 不得重开。due 不进 hint。
- G1 完整工具面在 Phase B。A 只注册并接线真链要用的 read。
- B4、B5、D1、D2、D3、G3、单 goal 无人值守在 Phase C。收据写者仍是 harness。驱动器不得写 `turn/material_spent`。
- 多 goal 公平、并发帽、soak 在 Phase D。
- C5：合法的人等待是非终态 `waiting`。无人值守 skip 未授权。A 不实现，也不把它当解卡。
- C6 留在 Phase C。V11 本轮未读。
- PC-4 不实现。不改 `v13/quota_window` 的 session 局部计数。不声称 goal 级配额。
- 不建 `command_receipts`。不建 link 表、send 账本。不建第二 plan/todo 写者。
- explore spawn 维持 RAISE `v13: explore spawn`。计划门不把它改成成功只读。
- `v13_recover_idle` 不改造成计划臂。它不是 effect 入队者。`pending` 不是跳过计划门的许可。G3 对它的消费留在 Phase C。`recover/nudge` 不加入指纹排除名单。Phase A 的 claim 路径不调用 `v13_recover_idle`，也不调用 `v13_insert_nudge`。

B6 所有权表在 A 交付。Phase C 声称无人值守之前必须再次提交这张表。A 交出这张表，不等于无人值守已授权。

## 4. 首期真链合同

操作者授权的根，一棵树，一个 goal。确定性 gate 与将来的真实 provider 验收走同一序列。Fake 绿不得写成产品可用。

脚本在 FakeLLM/FakeTool 里是固定回合，不是第二套控制语义。模型提议，SQL 判定。

1. **读前奏。** `v13_plan_prelude` 零 INSERT，包括零 session 行。不是 start-goal。不建 `command_receipts`。不调用 `v13_open_session`。
2. **提交入口。** `v13_plan_commit_entry` 调用已有 `v13_open_session`，显式传入 `{"route_policy_name":"default","version":2}`。空对象 `{}` 是失败夹具：活体缺省绑定 version `1`（`v13/spawn/v13_spawn.sql:285-320`）。入口在调用之前拒绝缺 `version` 的 spec。不修改 `v13_open_session`。version 2 是这条种子的冻结 version，因为缺省是 1，且 Phase 0 §5 的夹具形状使用 2。这不是「产品绑定已经闭合」。
3. **首次 parse 之前。** `v13_submit_override`，`intent=direct`。本计划没有已审核的 triage pass 带，种子里不加。不复制 seam 夹具 `UPDATE tools SET enabled=false WHERE name='spawn_subsession'`。产品装载含 govern。explore 维持 RAISE。不把会被 DROP 的库的 `max_cycles=6` 抄进种子。
4. **规划 IO。** 在任何 DB 事务之外。先调用 `v13_plan_admit(p_actor, p_session)`。它只读：会话存在，status 不是 `completed`/`failed`/`cancelled`，生命周期不是 stopped，以及与写者相同的两类授权：显式 `NULL::uuid` 且 `v13_control_operator()` 为真，或非 NULL 且 `v13_control_authorized(actor, target)` 为真。失败则不调用 provider。准入不是安全边界：停复与终态的拒绝在写者锁内。进程里记住的 `apply_id` 不跳过准入。只有已经交给写者的那个 id 的重试才先打写者，不得用准入把写者跳过。
5. **`plan_commit`。** 根事件流上，一个事务写出一条 `plan/committed` 和一条孪生 `todo/delta`。同一个 `apply_id`，`call_kind=plan_commit`，同一份 canonical jsonb。成员只从 `plan/committed` 应用一次，不从孪生 delta 再应用一次。载荷上的 `todo_id` 在 `todos` 多于一个 id 时是 JSON null；只有一个 id 时等于那个 id。写者零 effect，不调用 `v13_advance`。
6. **`selected_todo`。** 0 或 1 行。真链只有一个 `advancement_task`，`dispatch=provider`。
7. **新 advance 臂。** 在 govern 已持有的会话锁内重读 `selected_todo`，创建或采纳一个 effect，经写者写入绑定，然后提交。外部 IO 只在提交之后。驱动器不 INSERT effect，不 INSERT 收据，不调用 `v13_spawn_subsession`。
8. **父 spawn 请求，不是 harness 终答。** 这一类不进 `v13_harness_result_project`，也不因 C7 投影失败而被丢掉。它是 llm 的 `v13_complete` 载荷：非空 `text`，加上 `tool_calls`。该载荷不存放 `result_kind`。不得把 `result_kind` 塞进这次 complete 来制造归档对。合法名字只有 `spawn_subsession`，args 键只有 `task`（`v13/spawn/v13_spawn.sql:94-133` 与 `:246-256`）。其它名字 RAISE。不改这两处。不把 `read_file_py` 写成 `tool/call`。已有 complete 在 llm 成功且带 `tool_calls` 时自己写 `tool/call`（`v13/acl/v13_acl.sql:408-426`）。驱动器不 INSERT 该事件，不调用 `v13_spawn_subsession`。下一次 `v13_advance` 是 spawn advance，走活体 spawn 臂（`v13/govern/v13_govern.sql:814-816`），写零 plan/todo。看见 `workflow_id` 而没有这条 tool_call 时，不 spawn。子会话已有一条 `spawn/task`（`v13/spawn/v13_spawn.sql:438-439`）。生产调用者只有 `v13/real_chain/chain.py`：那次 advance 提交之后调用 `v13_child_pointer`，不 INSERT。`loop_driver` 允许名单不含这个函数。`plan_arm` 不调用它。参数来自子行 `parent_session_id`、根上溯、已绑定 `todo_id`、根最大 `events.seq`。不复制父 transcript。spawn SQL 不改。不改 `v13_session_log`。
9. **子 read，另一类。** 不是 `tool/call`，不调用 `v13_llm_tool_calls`，不进 harness 投影。子 advance 仍写零 plan/todo。同一份 `CREATE OR REPLACE v13_advance` 另加子 read 前缀。结算前缀与派发半段在会话不是根时跳过。这个 read 前缀仍运行：会话是子，已有恰好一条 `workflow/pointer`，且该子还没有任何 `read_file_py` effect，包括已经 `succeeded` 的。然后才创建一个 `tool` effect，`tool_name=read_file_py`。不写 `tool/call`。不改 T1.3 点名臂。做不到就停并 `ASK_USER`，不得靠跳过这次 read 换退出码 0。`should_run` 为假时该前缀零新 effect。驱动器在该 advance 提交之后，用 5 参 `v13_complete` 把有界摘录写入 `effects.result`，见第 5.9 节。脚本只调用这一次。不调用 edit/write/bash。不交付完整 G1。子会话经 `v13_fork` 继承父的 `route_policy_version`（`v13/fanout/v13_fanout.sql:967-971`）。根开在 version 2，子也是 2。不改 `v13_fork`。
10. **C7 只覆盖 harness 终答。** 名字是 `harness_turn`。必须有 `result_kind`。投影失败不调用 complete。父 spawn 请求不是这一类。
11. **成功归档的生产者。** 十二步链不会产生 `succeeded` 加 `result_kind` `progress|finish` 这一对。不得把 `result_kind` 塞进 spawn 的 llm complete。spawn advance 写零 plan/todo。子 advance 写零 plan/todo。子 `read_file_py` effect 已是 `succeeded`、摘录已能从 `effects.result` 读回之后，这一次根上的 `v13_advance` 只经 `loop_driver` 已有的结算入口发出。该入口已经执行 stopped 根上 `failed` IS NOT NULL 的禁令。禁令命中时，`chain.py` 不调用 `v13_advance`，也不归档。不得另开一次绕过 snap 检查的调用。这一次是根 `wait` 下的 T0 结算 advance，不是 provider 再入队。只在这一次、且会话不是 stopped、也不是终态时，结算前缀先核对子 `read_file_py` 摘录，再经 `v13_plan_writer` 写一条 `update`：`runnable→done`。`apply_id` 为 `archive:{root}:{todo_id}:{effect_id}:done:`，due 为空。`effect_id` 是该子上已成功的 `read_file_py` effect。子由已有 `workflow/pointer` 的 `todo_id` 与 `parent_session_id` 定位。不建表，不加第五个 verb，不建第二写者。这个前缀若不能放在点名活体臂之外，停并 `ASK_USER`。不得靠跳过归档换退出码 0。effect 的成功 status 仍是 `succeeded`，不是 `completed`（`v13/schema/v13_core.sql:112`）。
12. **C4 首期部分。** 见第 5.9 节。不是 `prompt-exports/` 路径。计划工件本身不能变成 `plan/committed`。不建多 lane。

真链计划体，Phase A 脚本，不是 Phase 0 裁决：一个 todo；`task_class=advancement_task`；`verb=add_new`；`status=runnable`；`due` 为 JSON null；无 link。

驱动器在一次 provider 跳上的事务边界：

1. 事务内调用 `v13_advance`，提交。此事务内无外部 IO。
2. 事务外做模型或工具 IO。
3. 事务内走已有 `v13_complete`，以及结算所要求的 `v13_advance`，提交。持久结果是 complete 之后的 SQL 行，不是 provider 原文。
4. 按第 5.6 节的 B1 决定是否再入队。`wait` 禁止的是下一次 provider 跳，不是禁止 T0 已经要求的结算调用。根 `wait` 之后，`chain.py` 仍跑子回合。

已 stopped 的根上，顶层 snap 满足 `failed` IS NOT NULL 时，驱动器不调用 `v13_advance`。这包括 JSON `false`、`0`、非空文本。键缺失与 JSON null 不在禁令内。这是驱动器纪律，不写进 advance 自检。终态根先走活体 `:754-756`，不在这道禁令里。

`should_run=false` 只保证对应臂零新 effect。收据臂在有 material 候选且无同源收据时仍会写。驱动器不得把 `should_run=false` 实现成「拒绝一切 advance」。

## 5. Phase A 选择（不是 Phase 0 裁决）

本节每个选择都是为了关掉 Phase 0 §10 的空位。不是用户投票，也不是对 Phase 0 文本的修订。jsonb 相等仍是唯一相等运算符。实现若发现不够，停并 `ASK_USER`，不得另做比较器。

已知 jsonb 事实，写入测试：对象键序不影响相等；数组序影响相等；缺键与 JSON null 不相等。canonical 的闭集键必须逐键出现，不用缺键表示 null。

### 5.1 函数名

Phase 0 未冻结函数名。本计划固定如下，避免两个写者。撞上已有函数就停，不静默改名去覆盖活体函数。

| 名字 | 性质 | 作用 |
|---|---|---|
| `v13_plan_prelude(jsonb)` | STABLE | 读前奏。零写 |
| `v13_plan_admit(uuid, uuid)` | STABLE | IO 前只读准入。参数是 `p_actor`、`p_session`。零写。不代替锁内拒绝 |
| `v13_plan_commit_entry(jsonb)` | VOLATILE | 唯一允许被链调用的 `v13_open_session` 包装 |
| `v13_plan_writer(...)` | VOLATILE | 唯一计划写者。两个 `call_kind` |
| `v13_plan_apply_id(text)` | IMMUTABLE | 绑定与归档的确定性 `apply_id` |
| `v13_plan_current(uuid)` | STABLE | 当前 advancement 计划，或空 |
| `v13_selected_todo(uuid)` | STABLE | 0 或 1 行 |
| `v13_plan_gate(uuid)` | STABLE | 布尔。不进 `should_run` |
| `v13_plan_inventory(...)` | STABLE | A3 库存 |
| `v13_plan_horizon(...)` | STABLE | A3 前沿投影 |
| `v13_harness_result_project(jsonb)` | STABLE | C7 投影。零写 |
| `v13_workflow_resolve(text, int)` | STABLE | C1 解析器。唯一生产调用者是 `v13/real_chain/chain.py`。不进 `loop_driver` 允许名单 |
| `v13_child_pointer(...)` | VOLATILE | C3。只在子会话上写一条 `workflow/pointer` |

不用 `v13_apply_plan`。不扩展 `v13_should_run` 的返回形状。不把这些名字写进 route key，不把 B1 出口写入 `decisions`。

`v13_plan_writer` 参数：`p_actor uuid`，`p_session uuid`，`p_apply_id uuid`，`p_call_kind text`，`p_canonical jsonb`，`p_now timestamptz`。`p_call_kind` 必须等于 `p_canonical->>'call_kind'`，否则 RAISE、零写。`plan_commit` 不读时钟。到期迁移要求非空 `p_now`。写者不调用 `clock_timestamp()` 或 `now()` 来决定水位。

### 5.2 canonical

`canonical` 是 jsonb。闭集键。无时间戳。无这次写入自己的 `events.seq`。uuid 用小写带连字符的文本。其它拼写 RAISE、零写。

`plan_commit` 的键：`schema_version`（整数 1），`call_kind`（`plan_commit`），`based_on_seq`（整数），`supersedes`（uuid 文本或 JSON null），`todos`（数组，按 `todo_id` 的 uuid 字节序排列；未排序则 RAISE，写者不得悄悄排序后再与调用者原文比较）。

每个 todo 对象的键：`todo_id`，`text`，`text_hash`，`task_class`，`status`，`due`（字符串或 JSON null），`verb`。`verb` 只允许 `add_new` 或 `reuse`。这是 Phase A 表示选择：T1.1 要求 reuse 由新的 `plan_commit` 在同事务写明，不能靠推断。父若退回 `verb`，实现停，不另造平行载荷。

`todo_delta` 的键：`schema_version`，`call_kind`（`todo_delta`），`verb`（只许 `update` 或 `link_successor`），`todo_id`，`status_from`，`status_to`，`binding`（对象或 JSON null），`due`，`quarantine`（对象或 JSON null），`text_hash`，`link`（对象或 JSON null）。`add_new` 与 `reuse` 只出现在 `plan_commit` 的 `todos[]` 里。其它 verb RAISE、零写。到期提升、成功归档、隔离、再启用都是 `update` 形状。

`link` 也是 Phase A 表示选择。`link_successor` 与 `resume_when` 需要目标，又不能塞进 `binding`。`link` 的闭集是 `{"on","id"}`。`on` 只允许 `successor` 与 `resume`。`id` 是同一根上的 `todo_id`。这不是表达式语言。父若退回 `link`，实现停。

同一次 `plan_commit` 写出一条 `plan/committed` 和一条孪生 `todo/delta`，共用 `apply_id`、`call_kind=plan_commit` 和同一份 canonical。孪生 delta 的载荷 `todo_id` 在 `todos` 多于一个 id 时为 JSON null。成员只从 `plan/committed` 应用一次。初始 delta 禁止改用 `call_kind=todo_delta`。此后的完成、绑定、到期、归档、隔离、再启用才各自用 `call_kind=todo_delta` 与自己的 `apply_id`。

`status_from = status_to` 不是迁移。它只在 status 不是 `done` 或 `dropped` 时合法，并且只用于载荷型 `update` 或 `link_successor`：绑定、`link`、隔离，可同时出现。真正的 status 变化仍必须是第 5.3 节列出的边。首次绑定的 canonical 是 `status_from = status_to =` 当前 `runnable`，加上绑定对象。从 `runnable` 隔离仍是同一条 delta 里的 `runnable→blocked`。`pending` 与 `blocked` 保持原 status，只增加隔离对象。`done` 与 `dropped` 仍无出边。

`text_hash = encode(digest(convert_to(text, 'UTF8'), 'sha256'), 'hex')`。不 trim。复用 `v13/schema/v13_core.sql:90` 已有的 `digest`。不加扩展。空文本 RAISE。`char_length(text) > 1024` RAISE。1024 对齐已读的 spawn task 帽 `v13/spawn/v13_spawn.sql:255`，不是 LoopX 常数。不 trim 的空格参与哈希。reuse 要求同一个 `todo_id` 且同一个 `text_hash`，否则 RAISE、整笔零写。reuse 不重置 class、status、binding、due、归档。提交体里的 class、status、due 必须与折叠现状一致，否则按重置拒绝。

`due` 是 `timestamptz` 能解析的原文，或 JSON null。写者不把原文规范化成另一种拼写。无法解析则 RAISE。

事件载荷在 canonical 之外还有：`apply_id`，`call_kind`，`canonical`，`plan_id`，以及 delta 上的 `todo_id`。`plan_id` 由首次写入生成并放在载荷上，不放进 canonical。重放返回已存储的 `plan_id`。

未知键 RAISE、零写。`schema_version` 不是 1 则同样拒绝。

### 5.3 写者行为

目标域是根。任何调用先沿 `parent_session_id` 映射到根（`v13/spawn/v13_spawn.sql:398`），`FOR UPDATE` 锁根行。不锁子会话来代替。不把子会话改成事件域。根没有父。

事件序是 `events.seq`（`v13/schema/v13_core.sql:30`）。不新造序列列。

锁内顺序按 T1.1：映射；锁根；T1.4 授权；按 `apply_id` 在根流上查找；合法重放直接返回、零写，此步先于 stopped/终态拒绝；同键而 `call_kind` 或 canonical 不同则 RAISE。只有首次请求才拒绝 stopped 或 status 为 `completed`/`failed`/`cancelled`，然后才做水位（仅 `plan_commit`）与迁移校验。

合法重放：根流上该 `apply_id` 的每一行，`call_kind` 与 canonical jsonb 都与本次相同。`plan_commit` 的成功形状是一行 `plan/committed` 加上同事务、同 canonical 的初始 `todo/delta`。事件 type 不同不是冲突。返回 `{plan_id, todo_ids, replayed}`。不调用 provider。

授权只这两类，不套到普通 tool/llm complete：显式 `NULL::uuid` 且 `v13_control_operator()` 为真；或非 NULL 且 `v13_control_authorized(actor, target)` 为真。根没有父，非 NULL 的根规划恒拒。显式 NULL 且不是 operator：RAISE、零写。无人值守规划仍未授权。测试里的超级用户通过 operator，只证明夹具，不证明产品角色。

水位种类本轮只关闭 `user/message`（`v13/schema/v13_core.sql:70-78`）。`steer/injected` 只是路线图 F2 提案（`docs/plans/v13-layered-control-roadmap-2026-09-26.md:71`），不是已关闭的活体字面。父审核在 `v13/` 里没有找到这个字面的写入者。`plan_contract` 可以只带 `user/message` 水位并退出码 0。`ASK_USER` 发生在把任何 steer 字面加进谓词之前，不是本 stage 开工的拦路条件。不新增第三种，不新增 `v13_steer`。`based_on_seq` 绑定的是 `events.seq`，不是 `turn_no`。只有 `user/message` 已证明会增加 `turn_no`。提交时 `based_on_seq` 必须等于锁内、写入之前的根最大 `seq`。其后根上出现更大 `seq` 的 `user/message`，该计划对 advancement 失效。steer 字面在活体 INSERT 被引出之前不进失效谓词。计划事件自己把 `seq` 推高，但不是 `user/message`，不得因此失效。失效是折叠谓词，不是触发器，不是自动插入。当前计划是仍通过该谓词的最新一条 `plan/committed`（`seq`，再 `plan_id` 字节序）。`todo_delta` 不参加比较，不制造新的当前计划，水位失效后仍可记账。记账不是复活。

`supersedes` 非 null 时，该 `plan_id` 必须已在根流上，否则 RAISE。空 `todos` RAISE。同一计划内重复 `todo_id` RAISE。`add_new` 后 class 不可变。

初始状态与迁移照 T1.1，不放宽：

| class | `add_new` 初态 |
|---|---|
| `advancement_task` | `pending` 或 `runnable` |
| `user_gate` / `user_action` / `blocker` | `pending`、`runnable` 或 `blocked` |
| `continuous_monitor` | 只许 `waiting`，且 `due` 非空 |

status 闭集：`pending`、`runnable`、`waiting`、`blocked`、`done`、`dropped`。迁移：`pending`→`runnable|dropped`；`runnable`→`waiting|blocked|done|dropped`；`waiting`→`runnable|blocked|dropped`；`blocked`→`runnable|dropped`；`done` 与 `dropped` 无出边。`waiting→dropped|blocked` 保持为取消与退役出口。

非 monitor 的 `waiting→runnable` 本计划不新造。这类 todo 留在 `waiting` 时，`dispatch=none`。

monitor 到期提升是独立 `apply_id` 的 `todo_delta`：class 为 `continuous_monitor`，当前 `waiting`，`due` 非空且 `due <= p_now`，则 `waiting→runnable`。首次写入服从 T1.4。SQL 不睡觉。A 的驱动器不跑到期循环，不把到期写进 hint，不把 `v13_recover_idle` 改成闹钟。测试直接调用写者。

monitor 成功是另一条 delta：`runnable→waiting`，新的非空 `due`。不是 `done`。

关系：链记在载体上。`link.id` 在载体变为 `done` 之前不可选。载体 `dropped` 不解除这次等待。除 `done` 以外的 status 都不解除。`on=successor` 与 `on=resume` 共用这条规则。拒环。两端都是同一根上的 todo。A 不把 `resume_when` 评估成 nudge。`children_terminal` 与现有 hint 仍是活体唤醒。并发窗要等 `plan_arm`，不声称旧实现已闭合。

绑定对象：`{"effect_id": <uuid 或 null>, "child_session_id": <uuid 或 null>}`。JSON null 表示折叠值不变，不是清除。清除只用 `{"clear_binding": true}`。失败隔离不自动清绑定。

隔离对象：`{"effect_id": <uuid>, "cleared": false}`。未解除表示最新一份 quarantine 的 `cleared` 不是 true。selector 排除带未解除标记的 todo，即使 status 仍是 `runnable`，即使绑定已清。普通 `update` 不得把它改回 `runnable`，也不得单独清标记。再启用不是第五个 verb：`update`，独立 `apply_id`，`blocked→runnable`，`quarantine` 为 `cleared: true` 且 `effect_id` 与未解除标记相同，同一条 delta 的 `binding` 必须是 `{"clear_binding": true}`，以免旧 effect id 留在折叠里。`done`/`dropped` 不得用这条形状重开。不建表，不加列，不加 status，不加事件种类。

确定性 `apply_id` 由 `v13_plan_apply_id` 从自然键算出，供 advance 重入时重放。自然键：

- 绑定：`bind:{root}:{todo_id}:{effect_id}`
- 成功归档：`archive:{root}:{todo_id}:{effect_id}:{status_to}:{due 原文或空}`
- 隔离：`quarantine:{root}:{todo_id}:{effect_id}`
- 再启用：`reenable:{root}:{todo_id}:{effect_id}`
- 到期：`due:{root}:{todo_id}:{due 原文}`

算法：该文本的 UTF-8 SHA-256，取前 16 字节，按 RFC 4122 设置 version 与 variant 位，得到 uuid。同一自然键永远同一 uuid。`plan_commit` 的 `apply_id` 不走这个派生。它由驱动器在一次规划尝试组开始时生成，进程内持有。不建账本。进程崩溃后，只有调用者仍能提交原来的 `apply_id` 与同一 canonical，才能重放。

规划尝试上界：provider 调用 2 次，然后停。写者传输重试另计 2 次，必须复用已有 canonical 与 `apply_id`，不得为此再调 provider。任一上限用尽即停。无睡眠循环。成本记录是驱动器返回值里的 `attempts_used`，加上测试日志。不插入 `plan/cost` 或任何新事件种类来记成本。那些事件不在指纹排除名单里；排除它们又必须改指纹函数。两者都不做。

错误消息前缀 `v13: plan writer:`，后接一个 token：`replay_conflict`、`stopped`、`terminal`、`waterline`、`transition`、`reuse_hash`、`cycle`、`auth`、`empty_due`、`bad_initial`、`canonical`、`not_root`。没有 `cap`。读帽不是写者错误。前奏：`v13: plan prelude: version_required`。入口：`v13: plan commit entry: version_required`。

新 SQL 文件里加 `BEFORE INSERT` 触发器，`WHEN (NEW.type IN ('plan/committed','todo/delta'))`，只校验载荷闭集。其它 type 不进入该触发器。不改旧守卫。水位只在写者锁内。超级用户仍可能用形状合法的裸 INSERT 绕过水位；这不是产品角色证明。驱动器侧用静态检查禁止裸 INSERT。不 REVOKE 旧表上的现有授权。不改 `v13_core` 的表定义，不加表级 CHECK。`events.type` 是开放词表（`v13_core.sql:32-35`），新种类不被旧表 CHECK 拒绝。

`workflow/pointer` 的守卫写在 `workflow_bind` 的新 SQL 里，不写进 plan 写者的触发器。

### 5.4 读帽

这些是 Phase A 种子，不是 LoopX 64/8/5，不是席位常数，也不是 `spawn.sql:401` 的深度 64。stage README 照录。以后要改，另写计划，禁止静默修改。

| 种子 | 值 |
|---|---|
| `inventory_scan_cap` | 32 |
| `inventory_return_cap` | 32 |
| `horizon_items` | 4 |
| `horizon_relations` | 4 |
| `horizon_gaps` | 1 |
| `item_text_cap` | 1024 |
| 规划 provider 尝试 | 2 |
| 摘录字符帽 | 1024 |

两个库存帽相等，所以输出 LIMIT 不能假装自己是扫描硬顶。顺序：`events.seq`，再 `todo_id` uuid 字节序。溢出必须返回省略计数。

读算法：按序行走当前计划成员的折叠结果，载荷最多纳入 32 行。另允许探测紧接着的 1 行，只用来判断溢出，不进入载荷。不扫描成员集之外的整段历史来做精确总数。`omitted_count` 因此只是 0 或 1。`omitted_complete=false` 表示真实剩余没有被点完，不是「省略数等于剩余总数」。返回 `rows_examined`、`rows_returned`、`omitted_count`、`omitted_complete`。33 条夹具：examined=32，returned=32，omitted=1，complete=false。32 条：omitted=0。0 条：全 0，不报错。返回的 id 必须是序下的前 32。

无当前计划时返回空库存、零写。前沿：未 `done`/`dropped` 的成员为 item，最多 4。`successor`/`resume` 边为 relation，最多 4。gap 最多 1，只是投影：未退役的 `blocker`，或指向不在当前成员集中的边。按同一全序取第一条。item、relation、gap 各自返回省略标志，规则与库存相同：探测紧接着的 1 行，所以各自的 omitted 只是 0 或 1。第五个 item 时 item omitted=1。gap 投影零 INSERT，不写 `replan/required`，不算 T3 哈希句，不算 B4。

`v13_plan_gate` 为真，当且仅当根上有 T1.2 当前计划，且 `v13_selected_todo` 的那一行属于该计划成员集。0 行则门为假。门为假只跳过派发半段，不禁止第 7.3 节的结算前缀经写者归档。`v13_advance` 里的计划臂在会话不是根时整段跳过。控制动词不咨询这道门。子会话可以调用只读折叠，读的是根流，不成为第二事件域。

`selected_todo` 的排除：绑定的 effect 未终态；或子会话 status 不在 `completed`/`failed`/`cancelled`；或 effect/子会话已终态但归档折叠尚未确认；或带未解除隔离标记；或不在当前成员集；或该 todo 是某条链的 `link.id`，而载体尚未 `done`；或 status 不是可派发状态。终态失败不自动回到 `runnable`。从未离开 `runnable` 但已经写上绑定、归档尚未确认的 todo，不可再选。

全序下第一条可派发行。`dispatch`：

- `advancement_task` 或 `continuous_monitor`，且折叠后为 `runnable`，且未被排除：`provider`
- `user_gate`、`user_action`、`blocker`，且 status 属于 `pending`、`runnable`、`blocked`：`operator`。这三类不得派到 `provider`。驱动器不得为此调用 provider
- 其余：`none`

「需要人」的 Phase A 谓词就是上一行。`should_run` 为假时，驱动器不为它入队新的 provider 跳。

### 5.5 指针

活体 spawn 已经在子会话上写一条 `spawn/task`，键集被 `v13/spawn/v13_spawn.sql` 的事件守卫钉死。不改那个守卫，不改 `v13_spawn_subsession`。`user/message` 会增加 `turn_no` 并可能把 `completed`/`failed` 重置为 `ready`。指针不用 `user/message`。

`v13_child_pointer` 锁子会话行。首次写入时，子会话若已 stopped 或 status 为 `completed`/`failed`/`cancelled`，RAISE、零写。合法的同载荷重放仍返回已存储的 `event_id`，包括唯一冲突上的重放，零新事件。异载荷 RAISE、零写。载荷闭集：`schema_version`（1），`parent_session_id`，`root_session_id`，`todo_id`，`up_to_seq`。不含父事件正文，不含整份 plan canonical。新 SQL 里的部分唯一索引保证每个子会话至多一条。生产调用者只有 `v13/real_chain/chain.py`，见第 4 节第 8 步。`workflow_bind` 的测试可以把该函数当被测单元直接调用。`plan_arm` 不调用。`loop_driver` 允许名单不含它。根上的 `user/message` 计数不变，根的当前计划仍在。

`v13_session_log` 存在于 `v13/observe/v13_observe.sql:130`。本计划不替换它。测试用 `pg_get_functiondef` 断言正文哈希不变。

chunks 是否把 `workflow/pointer` 或 `plan/committed` 收进模型上下文，本轮未读。组装吃 `v13_plan_inventory`、`v13_plan_horizon` 与这一条指针，不改 chunks SQL。若实现重读发现活体组装看不到 `spawn/task` 与指针、因而必须把父 transcript 倾倒进 `user/message` 才能让子模型开工，停并 `ASK_USER`。不得静默倾倒。

### 5.6 B1 出口

位置：一次 `v13_complete` 已经提交之后，下一次 provider 入队之前。返回值不进 `decisions`，不加 route key。每个出口只调用已有动词，或什么都不调用。hint 函数是已有 `v13_scheduler_hint`（`v13/govern/v13_govern.sql:517`）。不新起 hint 函数，不把 due 写进去。`run_now` 不是单独的入队许可。

| 出口 | 行为 |
|---|---|
| `wait` | 不入队下一次 provider/selected_todo advance。包括计划门为假、`should_run` 为假、hint 为 `wait` 或 `dont_notify`、`human_pending`、`dispatch=none`、没有选中行。人等待时 session 保持非终态 |
| `user_action` | 不调用 provider，不 skip，不 complete 那条 human effect |
| `provider` | 结算 advance 已经提交之后，再入队恰好一次 `v13_advance`。这一次是再入队，不把 T0 要求的结算调用算进去。条件是计划门为真、`should_run` 为真、hint 为 `run_now`、`dispatch=provider` |
| `terminal` | 只走已有 closeout |
| `stopping` | 只调用 `v13_goal_stop`，操作者授权。不是新的 session status 词 |

没有 `repair`、`replan`、`capability_adapter_handoff`。这些情况返回 `wait`，零插入。B4 在 Phase C。

判定顺序：session 已是 `completed`/`failed`/`cancelled` → `terminal`；调用者要求停止且操作者授权成立 → `stopping`；`dispatch=operator` → `user_action`；计划门为假，或 `should_run` 为假，或 hint 属于 `wait`/`dont_notify`，或 `human_pending`，或没有 provider 候选 → `wait`；provider 条件全真 → `provider`；其余 → `wait`。

`wait` 不取消 T0。真链里，子摘录已经落在 `effects.result` 之后，根 `wait` 下还有一次结算 `v13_advance`。它只经 `loop_driver` 已有的结算入口发出。该入口执行 stopped 根上 `failed` IS NOT NULL 的禁令。命中时不调用 `v13_advance`，也不归档。不得另开一次绕过 snap 检查的调用。那一次不是 `provider` 再入队，也不把 spawn complete 当成 harness 终答。`provider_requeue_one_advance` 不把这次结算算进去。stopped 上不写 plan/todo。

### 5.7 C7

SQL 键、驱动器 DTO、provider schema 分开。C7 只投影 `harness_turn` 终答。四个 `result_kind` 只来自 `v13/control/v13_control.sql:41`：`progress`、`finish`、`wait`、`reject`。不引入 LoopX `VALIDATED_*`。不改 `harness_result_schema`。父 spawn 请求与子 `read_file_py` 都不是这一类，不得共用一个 `tool/call` 形状。

可选键名单是提案，不是已关闭事实。父已在 `v13/control/v13_control.sql:51-59` 看到 `signals` 与 `wake`，所以上一版只列到 `content_hash` 的名单不完整。`loop_driver` 开工时重读整份 `harness_result_schema`，把行号写进该目录 README。与活体不一致就停。在那之前，投影只强制：未知键失败，缺 `result_kind` 失败，不把缺键填成 `progress`。`wait_reason` 若出现且不在重读到的枚举里则失败；若缺席，保持缺席。散文、非对象、空对象都失败，且不映射成 `reject`。失败计入尝试上界，不调用 complete。

投影函数返回 DTO：`ok`，`result_kind` 或 null，`wait_reason` 或 null，`harness` 或 null。`harness` 只含活体 schema 允许的键，供已有 complete 路径使用。`validated_receipt` 是 complete 提交后的持久 effect 行，不是 provider 原文。驱动器保留 provider 原文仅到本次尝试结束，不把它写成第二本账。

harness 终答的归档对仍是：effect `succeeded` 且 `result_kind` 是 `progress` 或 `finish`。十二步链不产生这一对。它的 `done` 只由第 4 节第 11 步的后一次根结算 advance 写出。spawn 的 llm complete 不带 `result_kind`，所以这一对不得在 spawn advance 上触发。没有 `result_kind` 的父 llm complete 不是对不上，不得压掉第 4 节第 11 步的写入。对不上、`wait`、`reject` 只适用于 `harness_turn` 终答。effect `failed` 或 `cancelled` 时，走隔离 `update`，不自动 `dropped`。对不上时不写矛盾的 todo 状态，零 `replan` 事件，不忙等。驱动器不自己改 effect status。`reject` 不由驱动器合成失败。

`done` 只用于该类的完成态。monitor 成功仍是 `runnable→waiting` 加新 due。真链不使用 monitor。臂在没有可解析 due 时，不得猜 due，不得把 monitor 归档成 `done`，不得插入 `replan/required`。

### 5.8 策略行、四层文本、read 注册

不碰 `judgment_templates`。新政策行：`v13_policies.name = workflow_template`，`version = 1`，`active`。解析器按 name 与 version 返回冻结 value；缺失或非 active 则 RAISE；零写。

value 的闭集：`schema_version`（1）；`layers` 是恰好四键的对象，键为 `assertion`、`assembly`、`judgment`、`workflow`，每个值是非空文本；`labels` 可以含 `read_only`；`allowed_tools` 为 `read_pi`、`read_file_swift`、`read_file_py`、`read_duck`；`parent_tools` 为 `spawn_subsession`；`chain` 为 `first_real_chain`。解析器返回这四段正文。驱动器按这个顺序输出四段，不拼成一行 `SYSTEM_PROMPT`，也不写回。子串检查扫这四段正文。`judgment` 仍是文本，不是 `judgment_templates`，也不是可执行门。

四层由驱动器组装成有序四段，不合并成一行 `SYSTEM_PROMPT`，不写回 `v13_policies`。`judgment` 层只是文本，不是 `judgment_templates`，也不是可执行门。标签留在政策里，不写进 tools 目录，也不选择 provider 端点。端点只在测试进程的 FakeLLM，或将来另行授权的适配器里，不进 `v13_policies`，不进库。缺省不隐式变成 `pair`。真链脚本显式使用夹具标签 `read_only`。`read_only` 不改变 explore 的 RAISE。

`allowed_tools` 是这条真链的驱动器允许名单，不是 Phase B 的目录交付，也不是第二套 SQL 门。`parent_tools` 里的 `spawn_subsession` 交给 `v13_advance` 的活体 spawn 臂，不是「驱动器看不见」的停点。停点只针对既不在 `allowed_tools` 也不在 `parent_tools` 的名字。那些名字驱动器不执行。若重读发现活体 `v13_advance` 会执行这种两边都不在的名字，停并 `ASK_USER`。不得用 `enabled=false` 的 UPDATE 去假装产品闭合。

四段正文不得指示模型自 skip、按 `workflow_id` spawn、或自己 INSERT `plan/committed`。gate 扫这四段正文里的这些子串，不扫键名。

read 注册放在 `v13/real_chain` 的 SQL 里，是装载 DML，不是前奏，也不是每次开会话的 INSERT。不调用 `v13/read_tools/setup_db.py`。不 DROP `agent_v13_read_tools`。不把 `read_tools/` 加进 `SQL_LOAD_ORDER` 的前 29 项。Phase 0 §5 已核的形状是四行工具名加 8 条带。本轮未重读 `test_read_tools.py`。实现时重读 `TOOL_ROWS`、`NEW_BANDS`、`BASELINE_TOOLS`。与「四名、八条带」不一致就停。

`default` version 2：实现时重读活体 `default` v1 的 value，复制后再追加重读到的 8 条带。不存在则 INSERT 这份复制体；已存在且冻结体一致则跳过；已存在且不一致则装载 RAISE，不 UPDATE。不得插入空 value。工具按 name 幂等插入，不 ALTER 旧表，不改已存在行的列。真链入口传 `version: 2`。测试断言根与子的 `route_policy_version` 都是 2。

Fake 门里的 `read_file_py` 由 FakeTool 返回固定摘录，不跑真实文件系统读，不打开 stannum。stannum GRANT 仍是未闭合的产品依赖，不写进新 SQL，不算第 30 项。

### 5.9 C4 首期部分

首期需要的咨询引用，不是多 lane，也不是把 `prompt-exports/` 当真相。

Phase A 选择：脚本化 `read_file_py` 的有界摘录，就是该 tool effect 经已有 `v13_complete` 写下的 `effects.result`。持久引用是这个 `effect_id`。摘录在调用 complete 之前由驱动器检查，超过 1024 字符则失败、不 complete、不截断。驱动器不 `INSERT INTO artifacts`。不新建 artifact 写者。不改 `harness_result_schema`。

活体落点已读，不是未决发明：`v13_is_harness_tool` 只在 name 为 `harness_turn` 且 kind 为 `tool` 时为真（`v13/control/v13_control.sql:97-99`）。`v13_complete` 只对 harness 工具调用 `v13_validate_harness_result_v1`（`v13/acl/v13_acl.sql:381-386`）。成功时 `UPDATE effects SET result = p_result`（`:411`），tool 成功再写 `tool/result`（`:415-418`）。`read_file_py` 不是 `harness_turn`，所以这段摘录不走 harness 闭集。全库 SQL 没有 `NEW.type = 'tool/result'` 的载荷守卫。不改这些旧行。

拒绝范围只是 `v13_complete` 的载荷。把 `plan/committed` 的 canonical 放进 complete 结果，不得因此变成计划。规划路径仍可把同一份 canonical 交给 `v13_plan_writer`。

这不是「artifact 表已经接上」。注册 read 工具时不得把 `read_file_py` 标成 `harness_turn`。若实现重读发现后来的 complete 正文拒绝这段 jsonb，停并 `ASK_USER`。不得改用驱动器插 artifact，不得把 C4 断言从 gate 里拿掉来换退出码 0。本 gate 必须跑到有摘录的那一次，并且摘录在 complete 之后仍能从 `effects.result` 读回。

## 6. 追加规则与计划目录

`v13/load.py:5-6` 只许在表尾追加。今天 `:17-46` 是 29 项，末项 `govern/v13_govern.sql`。`:48-78` 的 `STAGE_THROUGH["govern"]=29`。本规划轮不改这个文件。本文不分配 30、31 这类数字。

实现提交只能在 `SQL_LOAD_ORDER` 表尾追加，并给 `STAGE_THROUGH` 增加名字键。当时的整数值是「当前最大值 + 1」。禁止插到 29 项中间，禁止重排已落地的键。一个 stage 一份 SQL。计划目录与尾部顺序：

| 顺序 | 目录 | SQL | 键名 |
|---|---|---|---|
| 1 | `v13/plan_contract` | `v13_plan_contract.sql` | `plan_contract` |
| 2 | `v13/plan_read` | `v13_plan_read.sql` | `plan_read` |
| 3 | `v13/plan_arm` | `v13_plan_arm.sql` | `plan_arm` |
| 4 | `v13/loop_driver` | `v13_loop_driver.sql` | `loop_driver` |
| 5 | `v13/workflow_bind` | `v13_workflow_bind.sql` | `workflow_bind` |
| 6 | `v13/real_chain` | `v13_real_chain.sql` | `real_chain` |

`loop_driver` 的 SQL 只放 STABLE 的 `v13_harness_result_project`。它不 `CREATE OR REPLACE v13_advance`。C7 的 SQL 键层只有这一份，不在 Python 与 `real_chain` 各写一个解析器。`plan_arm` 测试直接插入 `workflow/pointer` 夹具行，因为该 type 的载荷守卫要到 `workflow_bind` 才装上。

依赖，与尾部顺序分开：

- `plan_read` 依赖 `plan_contract`。
- `plan_arm` 依赖 `plan_contract` 与 `plan_read`。全仓库新文件里只有这一份 `CREATE OR REPLACE v13_advance`。
- `workflow_bind` 的对象依赖 `plan_contract` 的词表与已有 `v13_policies`。它不依赖计划臂。代码可以在 `plan_contract` 之后写。`load.py` 的追加仍必须落在 `loop_driver` 之后、`real_chain` 之前。禁止为了提前测试把键插到 `plan_arm` 前面。
- `loop_driver` 的 B1/B6/C7 门用夹具文本即可跑，不要求 `workflow_bind` 已装。
- `real_chain` 依赖 `loop_driver` 与 `workflow_bind`。它是第一次把解析器输出接进四层组装的 gate。

B3 没有目录，没有 SQL，没有 Python 包。

每个测试库：新建一次性库，先装 1..29 到 govern，再按上表追加到该测试所在的键。不调用 read_tools 的 `setup_db.py`。库名不得匹配 `agent_v13_%`，不得使用 `agent_v13_longloop_p0_probe`。名字已存在则拒绝并退出，不 DROP。清理只 DROP 本次创建成功的那一个名字。现有库不得 DROP。

## 7. 分期合同

本规划轮没有跑本节任何命令。实现里程碑才跑。命令形式：`UV_FROZEN=1 uv run python v13/<dir>/test_<name>.py`，退出码 0。Fake 绿不是产品可用。

公共纪律：超级用户夹具不是产品角色证明。不改 stage 1–29 文件字节。不把探针、`prompt-exports/`、调查写进测试依赖。断言名在证据里原样记录。

### 7.1 `v13/plan_contract`

交付：A1 写者，A2 状态机与绑定载荷，A4 零 INSERT 前奏，以及调用已有 `v13_open_session` 的提交入口。无 advance 替换。无 provider。无驱动器循环。

追溯：A1、A2、A4。

依赖：活体 1..29。无本计划内的前驱。

本目录可退出码 0，水位谓词里只有 `user/message`。保持未决：产品库名、产品角色、stannum、PC-4、非 monitor 回程、stopped 上的 `user/message`、steer 活体字面。`waterline_user_message` 只在未 stopped 的根上插入 `user/message`。`steer_literal_not_closed` 不把 `steer/injected` 写进谓词。`ASK_USER` 只在有人要把任何 steer 字面加进谓词之前，不是本 stage 开工的拦路条件。不新增 `v13_steer`。

Gate：`UV_FROZEN=1 uv run python v13/plan_contract/test_plan_contract.py`。本规划轮未跑。

断言：`prelude_zero_insert`；`empty_spec_rejected`；`explicit_version_binds_column`；`plan_commit_one_tx`；`replay_same_ids`；`replay_after_stop`（无 `ready|claimed|unknown` effect 时可以 `v13_goal_stop`，其后重放返回原身份，事件数不变，指纹不变，不改指纹函数）；`conflict_raises`；`first_write_stopped`；`first_write_terminal`；`root_actor_rejected`；`waterline_user_message`；`steer_literal_not_closed`（本测试不插入 `steer/injected` 来充作活体生产者；README 写明该字面未关闭）；`reuse_keeps_fold`；`class_initial_and_transitions`；`link_cycle_and_goal`；`quarantine_reenable`；`canonical_hash_and_order`；`writer_skips_should_run`。计划事件种类不进入指纹排除名单。

证据：命令、退出码、一次性库名、断言名、事件计数。

收尾：创建 `docs/reviews/v13-long-loop-phase-a-conformance-matrix-2026-09-29.md` 与 `docs/reviews/v13-long-loop-phase-a-deviation-ledger-2026-09-29.md`，全表先 `not_run`。本目录 README 记录种子帽与「未证明产品角色」。

提交边界：`v13/plan_contract/`，`v13/load.py` 里这一次表尾追加，矩阵与台账的本 stage 行，本目录 README。

### 7.2 `v13/plan_read`

交付：A3。STABLE 库存与前沿。零写，不入队。

依赖：`plan_contract`。

Gate：`UV_FROZEN=1 uv run python v13/plan_read/test_plan_read.py`。本规划轮未跑。

断言：`zero_write`；`inventory_33`；`inventory_32`；`inventory_0`；`horizon_caps`（第五个 item 时 item omitted=1；relation 与 gap 同样各有省略标志）；`gap_inserts_nothing`；`text_cap`；`empty_plan`；`child_reads_root_stream`。子上的指针事件不改变根的当前计划。gate 断言 `rows_examined`，不断言「返回行数看起来对」。

提交：`v13/plan_read/`，对应 `load.py` 追加，矩阵/台账行，README。README 再次写下种子数字。

### 7.3 `v13/plan_arm`

交付：T1.3 与 T1.6 那一份 `CREATE OR REPLACE v13_advance`。内含 selected_todo 臂与锁内绑定。不替换 `v13_recover_idle`。不替换指纹函数。不替换 `v13_scheduler_hint`。不编辑 stage 1–29 的测试。

追溯：A1 的接线，A2 的绑定窗。B1 的入队点由下一目录消费本臂。

依赖：`plan_contract`、`plan_read`。

本轮未读完整 CASE。物理插入点是开工门。实现先重读 govern 里活体 `v13_advance` 全文，把源函数正文哈希写进本目录 README。新正文是该副本加上一个臂。做不到下列后置条件就停并 `ASK_USER`，不得改点名臂的内部：

- 会话锁仍是调用开始时那一把，与 `:737` 同一模式。
- 已终态会话仍在 `:754-756` 的位置提前返回。本臂不把它往后挪。
- 计划门为假时，不制造新 effect，不改 T1.3 点名的活体臂。这不是「零 plan/todo 写入」。不在 `CASE` 里加「无计划则全局停」。
- 新代码都在这一份替换里，都不插入点名臂内部。spawn advance 写零 plan/todo。子 advance 写零 plan/todo。十二步链的 `done` 只发生在第 4 节第 11 步那一次 advance。该前缀先核对子 `read_file_py` 摘录，再写归档。父 llm complete 没有 `result_kind`，不是第 5.7 节的对不上，不得因此压掉这次写入。对不上、`wait`、`reject` 只适用于 `harness_turn` 终答。会话不是 stopped、也不是终态时，用 `workflow/pointer` 的 `todo_id` 与 `parent_session_id` 找到子，其 effect 已 `succeeded` 且摘录在 `effects.result`，则经 `v13_plan_writer` 写一条 `update`，`runnable→done`，键为 `archive:{root}:{todo_id}:{effect_id}:done:`，due 为空。这个前缀若不能放在点名臂之外，停并 `ASK_USER`。不得靠跳过归档换退出码 0。harness 终答若真有 `succeeded` 加 `progress|finish`，仍可走第 5.7 节那一对；十二步链不靠它。`failed|cancelled` 仍是一条隔离 `update`，当时仍 `runnable` 则同一条 delta 写 `status_to=blocked`。无新 due 的 monitor 写零 plan/todo。`plan_arm` 测试直接插入 `workflow/pointer` 夹具行，因为该 type 的载荷守卫要到 `workflow_bind` 才装上。派发半段只在门为真时运行。已有绑定且该 effect 尚未终态：采纳，不建第二个。绑定的 effect 已经终态、隔离已解除、status 可派发：创建一个新 effect，并写新绑定，`apply_id` 为 `bind:{root}:{todo_id}:{new_effect_id}`。`provider` 抄活体模型回合的 effect kind。`operator` 创建一个 `human` effect。`none` 不创建。
- 插入点不在 T1.3 点名的任一臂内部。已读的 `v13/govern/v13_govern.sql:790-829` 不得被改写。
- 不新增 `v13_advance` 返回词。活体 `terminal` 与 `waiting` 保留。
- 派发半段一次调用最多为一个 selected todo 创建一个新 effect。采纳只发生在该绑定 effect 尚未终态时。
- 绑定、归档与隔离只经 `v13_plan_writer`。禁止绕过写者去 INSERT plan/todo。本替换不调用 `v13_child_pointer`。
- effect 种类必须是 `v13/schema/v13_core.sql:99-100` 已有的 `judge|tool|llm|context_refresh|human` 之一。具体哪一个，从重读到的活体模型回合抄。不发明第六种，因为那要改 stage 1 的 CHECK。
- 派发半段不调用 `v13_spawn_subsession`。spawn 仍只在活体臂 `v13/govern/v13_govern.sql:814-816`。
- 结算前缀与活体 finish/收据在同一事务。活体臂 RAISE 则归档一起回滚。stopped 上的 finish 仍允许活体路径写收据，同时本调用新增的 plan/todo 事件数为 0。
- `should_run` 为假时，本臂零新 effect。
- 会话不是根时，结算前缀与派发半段跳过，子上零 plan/todo。第 4 节第 9 步的 read 前缀仍运行。只有该子还没有任何 `read_file_py` effect，包括已经 `succeeded` 的，才创建一个 `tool` effect。不写 `tool/call`，不调用 `v13_llm_tool_calls`，不改 `:790-829` 与其它点名臂。插不进去就停并 `ASK_USER`。本 gate 不得靠跳过该 effect 退出码 0。`should_run` 为假时该前缀零新 effect。
- 全文件禁止第二段 `CREATE OR REPLACE` 再盖掉自己。其它新 stage 文件禁止再替换 `v13_advance`。

`should_run` 政策 version 仍是 3。不新增 block id。

Gate：`UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py`。本规划轮未跑。

断言：`no_plan_no_new_effect`；`live_spawn_stopped`；`live_approval`；`live_continuation`；`live_receipt`；`live_finish_stopped_without_failed_key`；`bind_once`；`archive_progress`；`archive_when_not_reselected`（只覆盖第 5.7 节的匹配：门为假、`selected_todo` 为 0、会话非 stopped 且非终态时，匹配则写者恰好一条 delta、零新 effect；对不上、`wait`、`reject`、无新 due 的 monitor 为零 plan/todo；stopped 上仍零 plan/todo）；`reenable_binds_new_effect`（再启用后 todo 可选；派发创建新 `effect_id`；其后失败的隔离是新 delta，事件数 +1，不是旧隔离 `apply_id` 的重放）；`monitor_due_not_guessed`；`child_skips_arm`；`policy_version_unchanged`；`recover_idle_and_fingerprint_unmodified`；`spawn_arm_still_calls_spawn_subsession`；`plan_arm_does_not_call_child_pointer`；`archive_child_excerpt_done`（顺序与 `archive_todo_delta_done` 相同：spawn advance 零 plan/todo；摘录落库后恰好一条归档 delta，折叠为 `done`）；`child_read_effect_not_tool_call`（子 read 前缀只建 `tool` effect，零 `tool/call`；插不进点名臂则本 gate 不退出码 0）；`dispatch_kind`（`provider` 抄活体模型回合 kind，`operator` 是 `human`，`none` 零 effect）；`stage_bytes`（stage 1–29 路径相对本提交父提交的 diff 为空；`load.py` 只增加尾部）。

`live_receipt` 用 SQL 调用 advance，证明写者不是驱动器。`recover_idle_and_fingerprint_unmodified` 比较装载本 stage 前后的函数正文哈希。

提交：`v13/plan_arm/`，`load.py` 追加，矩阵/台账，README。函数替换与活体臂断言同一提交。禁止只提交替换函数。

### 7.4 `v13/loop_driver`

交付：B1 五个出口；B2 四层文本组装，不是一份 `SYSTEM_PROMPT`；B6 表与静态检查；C7 投影与驱动器映射。FakeLLM/FakeTool。外部 IO 在事务外。开工时重读整份 `harness_result_schema`，行号写入本目录 README。与活体不一致就停。可选键名单在那之前只是提案。

追溯：B1、B2、B6、C7。真链端到端不在本目录宣称完成。

依赖：`plan_arm` 已装。不要求 `workflow_bind` 已装。

Python 放在 `v13/loop_driver/driver.py`。测试沿用仓库已有 stage 测试的连接方式，不新造框架。

驱动器允许调用的 SQL 闭集：`v13_plan_prelude`，`v13_plan_admit`，`v13_plan_commit_entry`，`v13_plan_writer`，`v13_plan_current`，`v13_selected_todo`，`v13_plan_gate`，`v13_plan_inventory`，`v13_plan_horizon`，`v13_harness_result_project`，`v13_submit_override`，`v13_advance`，`v13_complete`，`v13_goal_stop`，`v13_should_run`，`v13_scheduler_hint`，`v13_wake_is_satisfied_v1`（只读）。不含 `v13_child_pointer`，也不含 `v13_workflow_resolve`。本目录装在 `workflow_bind` 之前，门不得要求这两个函数已经存在。tool/llm 的 complete 用 5 参，即显式 NULL，不因此要求 operator。6 参只留给已有的人工作用，且驱动器不传 `skip`。驱动器不调用 `v13_open_session`、`v13_spawn_subsession`、`v13_recover_idle`、`v13_insert_nudge`、`v13_goal_resume`、`v13_cancel`。

静态检查扫本目录与 `real_chain` 的 Python，不扫 `plan_arm` 的 SQL。禁止出现：`INSERT INTO effects`，`INSERT INTO events`，`INSERT INTO sessions`，`INSERT INTO artifacts`，`turn/material_spent`，cron/`pg_cron` 注册，以及请求 JSON 体里的 API key 字段。持久副作用必须再进一次具名 SQL，并在该 SQL 的会话锁内重查。

迟到 complete：acl `:300-304` 是 fence 不一致返回 `stale`，已经终态返回 `replay`。`:459-469` 的 5 参包装传 `NULL::uuid`。没有另设 `origin_user_seq` 拒绝。仍处于 `claimed` 的迟到 complete 不自动是 `replay`。`stale` 时不归档为成功。`replay` 时用确定性 `apply_id` 再调用写者，使第二次归档成为重放。

B6 表写在本目录 README 的 `## B6`，测试解析该节，缺行即失败。

| 职责 | 持久语义所有者 | 驱动器允许 | 禁止 |
|---|---|---|---|
| identity | `v13_plan_commit_entry` → `v13_open_session` | 传显式 version | 驱动器 INSERT session；空 spec |
| enqueue | `v13_advance` 内的新臂，以及活体臂各自的 effect | 按 B1 调用 advance | 驱动器 INSERT effect；claim 路径上的 `v13_recover_idle`；驱动器调用 `v13_spawn_subsession` |
| receipt | advance 里的 harness 收据臂 | 发起含有候选的结算调用并接受结果 | 驱动器写 `turn/material_spent` |
| closeout | 已有 closeout | `terminal` 出口走该路径 | 驱动器直接改 session status |
| projection | 本节 STABLE 函数 | 只读 | 把驱动器缓存当成权威 |
| cancel classification | 已有 cancel / `v13_goal_stop` | A 的链不调用 cancel | 驱动器自造分类 |
| harness observation | 提交后的 SQL 结果 | 事务外观察 IO，再提交给具名 SQL | 把观察文件当成控制状态 |
| result_kind | C7 投影；持久形态是 complete 之后的 effect 行 | 映射四个字面 | 散文成功；默认缺字段；`VALIDATED_*` |
| actor | 规划：operator 的 NULL，或直接父。tool/llm complete：显式 NULL。human：非 NULL 亲缘 | 测试超级用户走 operator NULL | 以 agent 身份自 skip |
| credentials and filesystem | 事务外的进程环境 | Fake 路径无密钥。真实验收从环境读 | 密钥进入请求 JSON；密钥进库 |
| disposition write permission | 具名 SQL | 调用闭集 | 裸 INSERT |
| policy | `v13_policies` 与解析器 | 读冻结行 | 改 `judgment_templates` |
| children_terminal observation | `v13_wake_is_satisfied_v1` 的 `children_terminal` 分支起于 `v13/spawn/v13_spawn.sql:793`。函数体没有整份读完 | 只读 | 把它改成计划门；为它调用 recover_idle |
| pointer | `v13_child_pointer` | 只有 `v13/real_chain/chain.py` 在创建子会话的 advance 提交之后调用 | 本目录允许名单不含它；`plan_arm` 不调用；禁止 INSERT |
| fourth-duty | 本轮未读到这个符号 | 无 | 为填表而新造职责 |

fourth-duty：实现时只在将要复制的 `v13_advance` 正文里查找这个词。找到则把活体名字写进该行，所有者仍是 SQL。找不到则该行写 `none`，并注明查找范围。Phase C 重交这张表之前，不得声称无人值守。

Gate：`UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py`。本规划轮未跑。

断言：五个出口各一条；`repair`/`replan`/`capability_adapter_handoff` 得到 `wait` 且零新事件；`provider_requeue_one_advance`（`provider` 出口在 T0 结算 advance 之外再入队恰好一次）；`t0_settlement_advance`（有候选且未被 T0 禁止时，结算 advance 仍然发生，不并进上一句）；`user_action` 无 provider、无 skip、human effect 仍待应答、session 非终态；`stopping` 只见 `v13_goal_stop`，session status 词里没有 `stopping`；`decisions` 行数不变；C7 四值可投影，散文与缺键失败且不调用 complete；`io_outside_txn`；`retry_bound_2`；`stopped_failed_snap`；`no_recover_idle`；`no_direct_spawn`；`static_check`；`four_layers`（夹具文本，不调用 `v13_workflow_resolve`）；`override_before_parse`（`goal/override` 在该会话第一次 `v13_advance` 之前已存在；驱动器不新造 parse 函数）；`workflow_id_does_not_spawn`。B6 节行齐全。README 写明本表不授权无人值守。

本目录不在 stopped 根上插入 `user/message`。

提交：`v13/loop_driver/`，`load.py` 追加，矩阵/台账，README。

### 7.5 `v13/workflow_bind`

交付：C1 政策行与解析器；C2 合同；C3 一条 `workflow/pointer`。无工具子集交付，无 explore 行为变更，无 G1。

依赖：对象依赖 `plan_contract`。负载前缀因追加位置而包含 `plan_arm` 与 `loop_driver`。本目录测试不得依赖计划臂的派发。

开工门已由本轮重读收窄，不是未读：spawn 在子上写 `spawn/task`，不写 `user/message`。指针按第 5.5 节另写一条，不改 spawn SQL。本目录测试可以把 `v13_child_pointer` 当被测单元直接调用。生产调用者不在本目录。若实现时发现必须改 `v13/spawn/v13_spawn.sql` 才能留下这一条，停。

Gate：`UV_FROZEN=1 uv run python v13/workflow_bind/test_workflow_bind.py`。本规划轮未跑。

断言：`judgment_templates_untouched`；`resolve_v1`；`label_does_not_open_explore`；`no_tool_flag_update`；`one_pointer`；`pointer_not_transcript`；`session_log_unchanged`；`root_waterline_unchanged`。

提交：`v13/workflow_bind/`，`load.py` 追加，矩阵/台账，README。C2 行写明子集交付不在本行。

### 7.6 `v13/real_chain`

交付：第 4 节的整段序列；G2 的 Fake 门；本链 read 注册；C4 的 `effect_id` 加有界摘录；`workflow/pointer` 的唯一生产调用。真实 provider 命令另有授权路径，见下，本规划轮不跑。

追溯：G2，真链所需 read，C4 首期部分。多 lane 不建。G1 行保持「未交付」。

依赖：`loop_driver` 与 `workflow_bind`。

Python 在 `v13/real_chain/chain.py`，调用 `loop_driver`，不复制第二套出口机。`workflow_bind` 已装之后，只有这个文件调用 `v13_workflow_resolve`，并把返回的四段正文交给驱动器。该函数不进 `loop_driver` 允许名单。`loop_driver` 的 `four_layers` 仍可用夹具文本。创建子会话的 `v13_advance` 提交之后，只有这个文件调用 `v13_child_pointer`。不 INSERT。参数来自子行 `parent_session_id`、根上溯、绑定的 `todo_id`、根最大 `events.seq`。

Gate：`UV_FROZEN=1 uv run python v13/real_chain/test_real_chain.py`。本规划轮未跑。该命令是确定性 Fake 门。

断言：`prelude_zero_insert`；`open_session_version_2`；`child_inherits_version_2`；`override_before_parse`；`admission_before_io`；`plan_commit_on_root`；`selected_one_provider_todo`；`arm_bind_then_io_after_commit`；`spawn_only_from_live_arm`；`spawn_call_not_harness_projected`；`one_child_pointer`；`child_read_file_py_only`；`child_read_effect_not_tool_call`；`deny_edit_write_bash`；`c7_four_kinds_and_prose`；`receipt_by_advance`；`archive_todo_delta_done`（spawn advance 增加的 plan/todo 为 0；摘录写入 `effects.result` 之后恰好一条归档 delta，折叠为 `done`；跳过归档不得退出码 0）；`excerpt_on_effect_not_prompt_exports`；`plan_artifact_not_committed_via_complete`；`explore_still_raises`；`spawn_subsession_not_disabled`；`single_tree`；`four_layers_from_resolver`（发出的四段按 `assertion`、`assembly`、`judgment`、`workflow` 等于 `v13_workflow_resolve('workflow_template', 1)`，且不拼成一行 `SYSTEM_PROMPT`）；`real_provider_script_refuses`。

`real_provider_script_refuses`：`V13_REAL_PROVIDER_AUTHORIZATION` 未设置或不是 `1` 时，`accept_real_provider.py` 非零退出，消息 `v13: real provider not authorized`，且零网络调用。这个负例留在 `test_real_chain.py`。它不填写 `real_authorized_exit_0`。授权信号只有这个变量等于 `1`，没有第二道未定义的父检查。

FakeTool 不写文件系统，不打开 socket。不调用 read_tools `setup_db.py`。README 写明 Fake 退出码 0 不是产品可用。

第 5.9 节的落点是已读的非 harness complete。本 gate 不得改成跳过摘录后退出码 0。若重读发现该落点已不在活体 complete 里，停并 `ASK_USER`。

提交：`v13/real_chain/`，`load.py` 追加，矩阵/台账，README。真实验收不在这个提交的通过条件里。

### 7.7 不建：B3

没有 `v13/cadence` 或类似目录。不建 `scheduler/applied`。不把 hint 收成 ACK。测试可以同步调用出口函数，不注册时钟。due 不进 hint。非 `run_now` 不入队。`run_now` 之后仍看 `should_run` 与计划门。C/D 若重开 B3，即与 Phase 0 T5 冲突，应当停。

## 8. 条目追溯

Phase 0 §7 的归属维持不变。

| 项 | 归属 | 本计划 |
|---|---|---|
| A1 | A | `plan_contract` 写者与水位；`plan_arm` 只加臂，不改 `should_run` |
| A2 | A | `plan_contract` 状态机与绑定；`plan_arm` 锁内绑定。禁止用 spawn 表示 todo |
| A3 | A | `plan_read`。LIMIT 不是扫描硬顶 |
| A4 | A | `plan_contract` 前奏与入口。不建 `command_receipts`。不得声称 ingress 已等于 start-goal |
| B1 | A | `loop_driver` 五出口。不得声称心跳已经按计划选下一项，直到 `plan_arm` 与本目录都退出码 0 |
| B2 | A | `loop_driver` 四层组装；模板数据在 `workflow_bind`。一份 SYSTEM_PROMPT 不算完成 |
| B3 | A 的不做项 | 无目录。C/D 不得重开 |
| B4 | C | 不实现。gap 投影零插入 |
| B5 | C | A 的驱动器不是收据写者 |
| B6 | A；C 声称无人值守前再交表 | `loop_driver` README。A 的交付不授权该声称 |
| C1 | A | `workflow_bind`。`judgment_templates` 不动 |
| C2 | 合同在 A；子集在 B | 合同在 `workflow_bind`。explore 仍 RAISE。子集不交付 |
| C3 | A | `workflow_bind` 交付函数；唯一生产调用者是 `real_chain/chain.py`。不改 `v13_session_log` |
| C4 | 首期在 A；多 lane 在 D | 首期 `effect_id` 加摘录在 `real_chain`。多 lane 不建 |
| C5 | 各期遵守等待；无人值守 skip 未授权 | `loop_driver` 的 `wait`/`user_action` 遵守。不实现自动 skip |
| C6 | C | 不实现。V11 未读 |
| C7 | A | `loop_driver` 投影。四个 `result_kind` |
| D1 | C | 不实现 |
| D2 | C | 不实现 |
| D3 | C | 不实现。哈希句之前不得标绿 |
| G1 | B | 不交付。真链 read 只在 `real_chain` |
| G2 | A | `real_chain` 的 Fake 门。真实调用另行授权 |
| G3 | C | `v13_recover_idle` 不改。消费留在 C |
| G4 | 单 goal 续租与配额声称在 C；公平与 soak 在 D | 不实现。PC-4 不开工 |

不得声称：有过 plan 事件即放行；已有计划层；前沿已按 B4 可读；ingress 已等于 start-goal；hint 已被 ACK；驱动器只做 IO 已闭合；explore 已是成功只读；handoff 收据已是内容水合；问答卡死所以必须自动 skip；session-local 配额就是 goal 级；Fake 绿即产品可用；绑定窗在 `plan_arm` 退出码 0 之前已经闭合。

## 9. §10 开工门处置

| Phase 0 §10 项 | 处置 |
|---|---|
| 产品库名 | 保持未决。测试用新的一次性名字，禁止 `agent_v13_%` 与探针名。本文不命名产品库 |
| `route_policy_version` 绑定 | 合同已写明：缺省是 v1。实现必须传显式 version。真链种子是 version 2。子会话由 `v13_fork` 继承。产品安装保持未决 |
| 首次 parse 前的 override 或已审核 triage pass | 实现义务：`intent=direct` 的 `v13_submit_override`。本计划不加 triage pass 带。`TOOL_ROWS` 原文仍须在实现时重读 |
| 产品角色与 stannum GRANT | 保持未决。超级用户夹具不是证明。新 SQL 不写 stannum GRANT |
| canonical 与文本哈希 | 第 5 节作为 Phase A 选择已写明。相等运算符仍是 jsonb 相等 |
| stopped 根上 `p_snap->>'failed' IS NOT NULL` 不得再调用 advance | `loop_driver` 的义务。不是 advance 自检。`plan_arm` 禁止顺手加进函数体 |
| 锁内重验 | `plan_arm` 实现。不声称旧实现已安全 |
| 那一份 `CREATE OR REPLACE v13_advance` 尚未写出 | `plan_arm` 交付。禁止插入 T1.3 点名臂 |
| `v13_recover_idle` 是否入队 | 本轮已读：不入队 effect。消费保持未决，留在 C。A 不改造它 |
| 非 monitor 的 `waiting→runnable` | 保持未决。不新造 |
| `children_terminal` 行号 | 分支起于 `v13/spawn/v13_spawn.sql:793`。没有读完整个函数。并发窗要等 `plan_arm`，不算已闭合 |
| 用户消息 / steer 字面 | `user/message` 已由 `v13/schema/v13_core.sql:70-78` 核到。`steer/injected` 保持未决。`plan_contract` 可以只带 `user/message` 退出码 0。`ASK_USER` 只在把 steer 字面加进谓词之前 |
| B1 出口闭集 | 第 5.6 节作为 Phase A 选择已写明 |
| 事件种类表级 CHECK | 已核：开放词表。新守卫在新 SQL |
| 迟到 complete 的重放行 | 已核：acl `:300-304` 与 `:459-469`。未发现额外的迟到序号分支。不新发明 |
| 规划写者未实现 | `plan_contract` 交付 |
| PC-4 | 保持未决。Phase C 之前不开工 |
| 一库多 goal 的领用查询 | 保持未决。Phase D |
| 真实 provider 授权 | 保持未决。第 10 节的命令本轮不跑 |
| A–D 审核 | 本文是未审核的 Phase A 候选。B/C/D 仍是占位 |
| `e915e92` 落后 14 | Phase 0 已声明不再是开工门。不重开 |
| V11 | 保持未读。C6 不在 A |
| 席位常数 | 保持未读。不写 8 或 64。spawn `:401` 的 64 不挪用 |
| `result_kind` 四值 | 本轮已读。这是 Phase A 引用，不是改写 Phase 0 |
| 矩阵路径 | 第 11 节的新文件。不把 2026-09-26 控制面矩阵当作已核 |
| stopped 上的 `user/message` | 保持未决，未读。需要这个事实的测试不得先写进通过条件 |

另外保持为实现停点。未决前不得把对应 stage 标绿：`v13_advance` 完整正文与返回词闭集；`test_read_tools.py` 的 `TOOL_ROWS` / `NEW_BANDS` / `BASELINE_TOOLS`；活体 advance 是否会在驱动器看不见时执行名单外工具；chunks 对 plan 事件的纳入；fourth-duty 是否出现在将复制的 advance 正文；生产非超级用户 operator；非 harness 的 complete 仍可能拒绝任意 jsonb 键。`v13_spawn_owner` 的 CREATE 本轮未读，也不改。第 5.9 节保留 `ASK_USER` 停点，摘录断言不得为了退出码 0 拿掉。`harness_result_schema` 的可选键名单保持未决。

## 10. Gate 命令与真实 provider 验收

本规划轮未跑下列命令，也未调用真实 provider。

确定性 gate，退出码 0 才是各 stage 的实现通过条件：

1. `UV_FROZEN=1 uv run python v13/plan_contract/test_plan_contract.py`
2. `UV_FROZEN=1 uv run python v13/plan_read/test_plan_read.py`
3. `UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py`
4. `UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py`
5. `UV_FROZEN=1 uv run python v13/workflow_bind/test_workflow_bind.py`
6. `UV_FROZEN=1 uv run python v13/real_chain/test_real_chain.py`

真实 provider 验收，不是上述退出码，不是本规划轮，不是 Fake 门的别名：

`UV_FROZEN=1 uv run python v13/real_chain/accept_real_provider.py`

`V13_REAL_PROVIDER_AUTHORIZATION=1` 是唯一授权信号。未设置或不是 `1`：非零退出，消息 `v13: real provider not authorized`，零网络。本规划轮不设置该变量，也不跑这条命令，也不跑 Fake gate。

变量为 `1` 时：同一条第 4 节控制序列，适配器是 `v13/real_chain/adapter.py` 的 `RealProviderAdapter`。该路径上没有 FakeLLM、没有 FakeTool。凭据只从进程环境读取，不进请求 JSON，不进库。退出码 0 只在这些 SQL 可见里程碑成立时：根上有 `plan/committed`；恰好一个子会话且 `route_policy_version=2`；恰好一条 `workflow/pointer`；read effect 为 `succeeded`，有界摘录仍在 `effects.result`；advancement todo 已归档为 `done`；仍是一棵树。不要求固定的模型正文。provider 错误是非零退出。矩阵行 `fake_exit_0` 与 `real_authorized_exit_0` 分开。两个退出码都不等于产品可用。

实现不得把这些命令换成 stage runner，也不得为了本相位声称而去冒充 stage 1–29 全矩阵已跑。Phase 0 的探针命令不是本相位 gate。`plan_arm` 的 `stage_bytes` 只证明该提交没有改 stage 1–29 字节，不是 29 个旧测试的重跑。

## 11. 收尾与提交边界

实现里程碑，不是本规划轮，才更新：

- 新矩阵 `docs/reviews/v13-long-loop-phase-a-conformance-matrix-2026-09-29.md`
- 新台账 `docs/reviews/v13-long-loop-phase-a-deviation-ledger-2026-09-29.md`
- 该 stage 自己的 README

矩阵列：条目，目录，允许的声称，证据指针，状态。状态从 `not_run` 开始。只有对应 gate 退出码 0 之后，该行才能写成 `exit_0` 并带上命令、退出码与库名。G2 拆成 `fake_exit_0` 与 `real_authorized_exit_0`，不得合成一行。本文档的存在不是证据。`plan_contract` 的里程碑创建这两份文件的全表骨架。后续里程碑只改自己的行。

默认不改路线图，不改 2026-09-26 控制面矩阵。Phase 0 计划与 Phase 0 证据本相位不改。父以后若要求一行指针，再另说。本规划轮不动它们。

每个实现里程碑的提交是路径级 add：该 stage 目录，`v13/load.py` 的那次追加，新矩阵与台账中的对应行，该 stage README。禁止 `git add -A`。禁止纳入 `uv.lock`、`prompt-exports/`、调查、stage 1–29、父循环 memory、探针与日志。禁止 force、`reset --hard`、自动 stash、跳 hook。

提交顺序：`plan_contract`，`plan_read`，`plan_arm`，然后 `loop_driver`，然后 `workflow_bind`，最后 `real_chain`。`load.py` 键必须按第 6 节的尾部顺序，不得超车。`plan_arm` 的函数替换与它的活体臂测试同一提交。本规划轮不提交、不推送。父在自己的复审之后才决定发表。

无法只做路径级 add 时停。不把调查补进仓库。

## 12. 留给父复审

合同复审 group `E4759295-BD50-405C-8E6E-D0D5367BD73D` 完成的 grok 与 kimi 两路均为 P0=0、P1=0。codex 402 不是内容分。其后只改 P2 措辞。未实现。未跑 gate。未提交。父对措辞的复审仍需要。不宣布产品可用，不宣布 A 已可开工。

上一轮父组 `E232EF04-1D97-4BFD-9132-EBEC4A627FD3` 的八项 P1 与列出的 P2 已改入本文，那次计数不是本次通过。上一轮父组 `5E9D44CE-3B36-47C2-A576-D225D54D45D1` 的剩余项已改入本文，那次计数不是本次通过。上一轮父组 `1B4EAC94-AFF2-421E-A6F6-666864E93852` 的剩余项已改入本文，那次计数不是本次通过。本轮父组 `73A027A0-7DDE-48E0-91B6-0EF73AE24516`：只有 grok `new-chat-F65F63` 完成，记 P0=0、P1=1、P2=2。codex 额度 402，kimi 无内容，都不是通过。本修订针对这轮剩余项。修订本身不把计数写成零。

请父决定是否接受下列 Phase A 选择，或退回后重写计划。实现在退回前不得私自换一套：

- canonical 在 todo 上增加 `verb`，在 `todo_delta` 上增加 `link`。
- binding、quarantine、确定性 `apply_id`、错误 token 的具体形状。
- `based_on_seq` 使用 `events.seq`，不用 `turn_no`。已关闭的水位种类只有 `user/message`。`steer/injected` 仍是未关闭的路线图提案。
- 读帽 32/32、4/4/1、文本 1024、规划尝试 2。它们故意不是 64/8/5。
- 指针类型是 `workflow/pointer`，不是 `user/message`。子上已有的 `spawn/task` 不改。
- B1 五出口，以及「`wait` 不吞掉 T0 结算调用」。
- stopped 上不补写归档。
- `loop_driver` 有一份 STABLE SQL，键的位置在 `plan_arm` 与 `workflow_bind` 之间。
- C4 首期引用是 tool effect 的 `effect_id` 加 complete 已写下的有界 `effects.result`，不是新的 artifact 写者，也不是 `prompt-exports/`。
- `workflow_template` 政策行、四层文本、驱动器 `allowed_tools`。`judgment_templates` 保持不碰。
- 真实验收命令与 `V13_REAL_PROVIDER_AUTHORIZATION`。
- 成本只留在进程内 `attempts_used`，不新造事件种类。
- `resume`/`successor` 只影响可选性，不制造 nudge。`dropped` 不释放后继。
- 驱动器不调用 `v13_spawn_subsession`。子会话只由活体 advance 臂创建。`v13_child_pointer` 的生产调用者只有 `real_chain/chain.py`。
- `user_gate` / `user_action` / `blocker` 在 `pending|runnable|blocked` 时 `dispatch=operator`，不得派到 `provider`。非 monitor 的 `waiting` 保持 `dispatch=none`。退回这个谓词时不得另长一张出口表。

尚未能在本文关闭、父不应把它看成已核的事实：第 9 节后半的实现停点，尤其是完整 advance 正文、stopped 上的 `user/message`、steer 活体字面、产品角色、stannum、V11、席位常数、fourth-duty、chunks、`TOOL_ROWS` 原文、非 harness complete 对任意 jsonb 的拒绝、`harness_result_schema` 的完整可选键。摘录的已读落点见第 5.9 节，停点仍在。

`plan_arm` 是最大实现风险：它必须整份替换 `v13_advance`，又不许动点名臂，不许新返回词，不许第二份 `CREATE OR REPLACE`。后置条件做不到就停。旧文件不改，所以回退方式是不装载新 stage，不是从 govern 里撤销字节。测试库是一次性的。没有产品库迁移，因为产品库名仍关闭。

Phase B/C/D 不因为本文写了占位就可以开工。PC-4、无人值守 skip、多 goal 领用、cadence ACK，都不在下一个实现提交里。
