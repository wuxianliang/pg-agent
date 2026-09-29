# v13 长循环 Phase C 计划（2026-09-29）

**状态：完成的复审 lane 为 P0=0、P1=0（`untitled-chat-FF43BD`、`untitled-chat-AEC26D`、`untitled-chat-35BBE8`）。P2 不阻挡接受。其它 lane 多次没有内容分，不是零分，也不是否决。未实现。本规划轮未跑任何 gate。尚未提交。** 计划合同已被上述完成 lane 接受。不得宣布产品可用。不得把未完成 lane 写成 P0=0。Fake 退出码 0 不是产品可用，也不是 Phase A 的 `real_authorized_exit_0`。父组 `810F15E6-381F-486E-9A15-1F36F9A47614`、`10BD0645-DD7A-4AC5-9A40-C96923DADB32`、`0F41F9D5-D659-43F5-8DA3-D28B8D78885C`、`ED1FCF23-F95D-4FCC-9B2E-54B7F0412662`、`4A0BAA9D-159C-4638-BC26-F0AEDC13BF91`、`D6385E6F-190A-4388-BD37-645AADD4BF0D`、`F358297A-C8D9-44BD-980B-98339592CCF2`、`B815EE9A-C80A-4204-96FF-25F34F03981A` 都不是接受。缺的 lane 不是零分。kimi 的配额失败不是内容零分。本文只把修补写进合同，不是复审通过。

本规划轮没有改 `v13/load.py`，没有改 stage 1–29，没有改已接受的 Phase 0 / A / B 计划，没有改指纹函数，没有改 fanout SQL，没有调用真实 provider，没有跑下面任何一条 gate，没有提交，没有推送。`main` 与 `origin/main` 同为 `4fa59dc`。Phase A（`2206874`）与 Phase B（`4fa59dc`）的产品 SQL/Python 都还未落地。下文「调用已有函数」指那些阶段按已接受计划装上之后的函数，不是本轮仓库里已经能执行的对象。

权威顺序：本轮用户范围（Phase C 只做单 goal 无人值守）；Phase 0 `docs/plans/v13-long-loop-plan-2026-09-28.md` 的 §2、§7、§9、T0–T7；已接受的 Phase A 计划，尤其 §3.2、§7.3、§7.4、§8；已接受的 Phase B 计划，尤其 §3.2、§4.1、§4.8、§6、§8。调查不是权威。冲突时按这个顺序，并在第 2 节点名。

初稿是 Oracle group `DE10860B-C22A-4256-9806-C47951504A91` 的三路草稿，不是接受。主 lane `new-chat-D6D485` 是底稿。另外两路是另一份控制面，不并入，避免两套写者。pair 按活体重读改了主 lane 里会撞 stage 1–29 守卫的载荷。重读行在 `docs/reviews/v13-long-loop-phase-c-plan-evidence-2026-09-29.md`。该文件不是 gate 通过证明。

## 1. 若需要第二份 `v13_advance` 替换，本计划停止

Phase A 的 `v13/plan_arm` 是唯一一份计划中的 `CREATE OR REPLACE v13_advance`。Phase B 没有第二份。Phase C 的每个新 SQL 文件、每段新 Python，都不得再出现这个替换。不得编辑 `v13/plan_arm/**` 去把新臂插进那份副本。

下面任何一条如果在实现时被证明必须改 `v13_advance` 函数体，或必须再 `CREATE OR REPLACE` 一次：该阶段停并 `ASK_USER`，不得标成 `exit_0`，不得靠删断言换退出码 0。

- B4 的插入者不进 advance。advance 不插 `replan/required`。
- B5 的收据仍由已经在那一份替换里原样复制的 harness 收据臂写入。本期只增加进程调用者。
- 工作区 effect 不是活体 harness 前驱。不得为它放宽收据谓词，不得加宽 `v13_llm_tool_calls`。
- C5 不改两键 human 请求，不把 `interaction/offered` 插进 approval 臂。那是 advance 体内的写入。
- D1 不改 `v13_scheduler_hint`。
- G3 不改 `v13_recover_idle`，不把它改成 effect 入队者。
- PC-4 不靠替换 advance 来做配额门。本期也不替换 `v13_should_run` 或 govern 的 gate。

本计划不包含这份替换，也不给它留阶段目录。

## 2. 优先级与冲突

1. 本轮用户范围：单 goal 无人值守。不是 v14/v15，不是外层 wrapper。PG 是唯一控制语义 owner。外部 IO 不进事务。
2. Phase 0 的用户决定与 T0–T7。本文引用，不改写。
3. 已接受的 Phase A、Phase B 合同。本文消费，不改写，不编辑它们的目录。
4. 第 4 节的 Phase C 选择。父可整组退回。退回前不得另写一套控制面。
5. 调查。与上面冲突则调查作废。

| # | 调查 / 易混句 | 本文 |
|---|---|---|
| 1 | 计划门放进 `should_run`，策略升到 v4 | 计划门仍是 Phase A 的 `v13_plan_gate`。活跃策略 version 维持 3。不为计划谓词升版本，不加 block id |
| 2 | `plan/superseded` | 不建该种类 |
| 3 | Fake-only 分期，或把 Fake 退出码 0 写成产品可用 | 确定性 gate 用 FakeLLM/FakeTool 的场合只在已经要模型的夹具里。监督进程本身不调用 provider。Fake 绿不是产品可用 |
| 4 | B3：`scheduler/applied`、cadence ACK、RRULE、scheduler 状态表 | 不建。无目录。C 不重开。D 也不得靠本期开口 |
| 5 | C5 用 operator `complete(skip)` 当超时解卡 | 不实现自动 skip。人等待保持非终态 `waiting` |
| 6 | 抄 LoopX 64/8，或把 spawn 深度 64 当本期帽 | 不写 8，不写 64。种子见第 4.8 节 |
| 7 | `v13_apply_plan` 把两种调用混成一次 | 不建这个函数。不修改 `v13_plan_writer` |
| 8 | 第二状态源、新表、工作流引擎 | 不建表，不加列，不建账本 |
| 9 | 看见 `workflow_id` 就 spawn | 监督进程不调用 `v13_spawn_subsession` |
| 10 | 把 `judgment_templates` 当工作流目录 | 不读、不写、不迁移该表 |
| 11 | 「驱动器是收据写者」或「quiet = 驱动器跳过收据写入」 | 收据写者仍是 advance 里的 harness 收据臂。quiet = 这一跳不调用 `v13_advance`。有未付 harness 候选就必须调用并接受结果 |
| 12 | 「驱动器入队 `replan/required` 以绕过 L24」 | 作废。L24（路线图 `:130`）禁的是停滞自动插入。合法插入只有第 4.1 节的具名 SQL，且只针对计划图语义缺口。驱动器不 INSERT 事件 |
| 13 | exactly-once 通知、outbox、`notify/sent` | 不承诺 exactly-once。不建 outbox。不插入通知事件 |
| 14 | C6 的 link 表或 send 账本 | 不建。观察者不代答 |
| 15 | 把 V11 或 auto-wake 标成已闭合 | V11 本轮未读。不标闭合。不新增 `request_attention` 授权 |
| 16 | 有循环就声称无人值守已通 | B6 表写进 Phase C 的 README 并且对应 gate 退出码 0 之前，不得声称。即便退出码 0，也不是产品可用，也不是人可以离开生产终端 |
| 17 | session-local 配额就是 goal 级配额 | PC-4 关闭。不改 `v13_quota_eligible`。不声称 goal 级配额，不声称无人值守多 spawn 预算 |

主 lane 与 kimi lane 都把 `frontier_hash`、`obligation_key` 一类键写进 `replan/required` 载荷。这与活体守卫冲突，本文不跟随。见第 4.1 节。另一 lane 的 `replan/responded`、`notify/sent`、`evidence/attached`、以及「每 10 秒续租」循环，本文不跟随。

## 3. 本轮重读，不是已通过

行号记在证据文档。这里只钉会改变合同的句子。实现仍须在装载后用 `pg_get_functiondef` 复核；对不上就停。

- `replan/required` 的活体载荷键必须恰好是 `schema_version`。`source_effect_id` 不得为 NULL。守卫在 `v13/control/v13_control.sql:425-428` 与 `:447-448`。该触发器没有被更后的 stage 替换。signals 路径写入的就是 `{"schema_version":1}` 加上该 effect 的 id（`v13/acl/v13_acl.sql:435-436`）。多出来的键会 RAISE `v13: event payload`。本文不改这个守卫。
- `events.source_effect_id` 无 FK（`v13/schema/v13_core.sql:37`）。
- 收据候选与写入在 `v13/govern/v13_govern.sql:849-866`。候选是 harness 前驱，且 `result_kind` 为 `finish`，或为 `progress` 且该前驱还没有 `repair/required` / `replan/required`。尚无同源 `turn/material_spent` 时就会写。该臂不读 `should_run`。
- `v13_is_harness_tool` 只在 name 为 `harness_turn` 且 kind 为 `tool` 时为真（`v13/control/v13_control.sql:97-99`）。工作区六个名字不是这条。
- `v13_harness_predecessor` 只选 harness tool（同文件 `:180` 起）。把语义缺口的 `replan/required` 挂到这种前驱上，会让下一次 advance 的 signals ledger（govern `:845-852` 一带）RAISE。本文禁止这种挂接。
- 指纹排除名单是 session `completed|failed|cancelled`、`goal/stopped|resumed`、`control/handoff`、`wake/satisfied`、`turn/material_spent`（`v13/govern/v13_govern.sql:62-65` 与 `:79-82`）。`replan/required`、`interaction/offered`、`recover/nudge` 都不在名单里。本文不改指纹函数。stopped 之后的首次写入必须拒绝，否则 `v13_goal_resume` 会拒复。
- 两键 human 请求是 `schema_version` 与 `interaction_ref`（`v13/govern/v13_govern.sql:911-912`）。没有 options，没有 timeout。
- `v13_recover_idle()` 的加载后正文在 govern `:453-519`。零参数。不 INSERT effect，不调用 `v13_enqueue_effect`，不调用 `v13_advance`。它调用 `v13_insert_nudge`，后者写 `recover/nudge`（`v13/spawn/v13_spawn.sql:193-196`）。stopped 会话被跳过。返回 `pending` 与 `nudged`。本文不改这个函数。
- `v13_requeue_stale` 的加载后正文是 `v13/control/v13_control.sql:1079`。`v13/*.sql` 里更后的文件没有再替换它。选择条件是 `status = 'claimed' AND lease_until < clock_timestamp()`（`:1087`）。`infinity` 与 NULL 不满足 `<`。非 `judge` / `mgraph_consolidate` 的过期 `claimed` 被标成 `unknown`（`:1127-1130`），不是收回 `ready`。本文不改它。
- `v13_claim` 的缺省租约是 `p_lease_ms` 缺省 60000，`lease_until = clock_timestamp() + 该间隔`（`v13/schema/v13_core.sql:267-271`）。这是活体缺省，不是本期新帽。
- `v13_scheduler_hint(uuid)` 返回 `run_now` / `wait` / `dont_notify`。stopped 返回 `dont_notify`（govern `:545-546`）。函数起于 `:534`。due 不在返回值里。
- `v13_observe(uuid, uuid[])` 在任一 id 未通过 `v13_control_authorized` 时直接 `RETURN`，零行，不 RAISE（`v13/observe/v13_observe.sql:86-88`）。空结果不是「没有事实」。
- `artifacts` 有 `artifact_id` 与 `produced_by`，没有会话列（`v13/manifest/v13_manifest.sql:52-59`）。来源 effect 必须已经 `succeeded`（同文件 `:81-88`）。
- `v13_quota_eligible(uuid)` 只计本 session 的 `turn/material_spent`（`v13/quota_window/v13_quota_window.sql:53` 与 `:94-99`）。
- `WHEN 'tool'`（govern `:1137-1168`）按 snap 里的 route 新建 effect 并 `v13_send_work`。它不扫描已有 `claimed` 行。一次结算 `v13_advance` 仍会跑到这个臂，如果 route 选中了工具。

Phase A 的 canonical 闭集未知键 RAISE。本文不把 `responds_to_frontier_hash` 加进 `plan/committed` 或 `todo/delta`。那是编辑 `v13_plan_writer` 或它的触发器。

## 4. Phase C 选择

父可整组退回。退回前实现停。这些选择只填 Phase 0 §10 与 Phase A/B 已经写成「不得声称」的空位。

### 4.1 B4 哈希句与三个函数

语义缺口写者是新函数，不复用 `v13_complete` 的 signals 路径。signals 路径保持原样。模型信号不是义务。advance 不调用插入者。驱动器不 INSERT 事件。

投影与插入分开：

| 名字 | 性质 | 作用 |
|---|---|---|
| `v13_frontier_project(uuid, bigint)` | STABLE | 参数 `p_root`、`p_before_seq`。`p_before_seq` 为 NULL 表示当前流，并且只在这一支调用一参 `v13_plan_current`。非 NULL 时在本函数内按 `seq < p_before_seq` 重折 Phase A 水位，不调用那个一参函数，不改 Phase A。返回闭集 Frontier jsonb，以及只对该 jsonb 计算的 `frontier_hash`。`has_obligation` 是与 `gaps` 同序的布尔数组，在 jsonb 之外。`omitted_count` 与 `omitted_complete` 也在 jsonb 之外。零写 |
| `v13_obligation_open(uuid)` | STABLE | 参数 `p_root`。零写。把每条义务事件的前缀恢复到 `seq <` 该事件 `seq`，在未截断的缺口集上枚举自然键，调用 `v13_plan_apply_id` 比对。必须恰好一个 gap 的 uuid 等于 `source_effect_id`。返回的 32 条里没有这个键，且 `omitted_complete` 为假，不是缺失，不得清开放位，不得当成已回应。当前开放位只看未截断集里该键的最后一次出现或消失 |
| `v13_replan_gap_insert(uuid, uuid, text, uuid, uuid, text)` | VOLATILE | 参数 `p_actor`、`p_root`、`p_gap_kind`、`p_subject`、`p_object`、`p_expected_hash`。`p_object` 可为 NULL。唯一插入者。uuid 只在本函数的根锁内派生 |

撞上已有同名函数就停，不静默改名。实现时搜索三个函数 `v13_frontier_project`、`v13_obligation_open`、`v13_replan_gap_insert`，以及三个目录 `v13/frontier_gap`、`v13/goal_supervise`、`v13/goal_supervisor`。本规划轮这三处都没有同名。不是只搜两个。

**规范序列化。** `Frontier` 是 jsonb，键必须逐个出现：`schema_version`（整数 1）、`plan_id`（当前计划 uuid 文本，或无当前计划时 JSON null）、`members`（数组）、`gaps`（数组）。每个 member 的键必须逐个出现：`todo_id`、`task_class`、`status`、`text_hash`、`due`（原文或 JSON null）、`link_on`（文本或 JSON null）、`link_id`（文本或 JSON null）。每个 gap 的键必须逐个出现：`gap_kind`、`subject_todo_id`、`object_todo_id`（文本或 JSON null）。数组顺序是对应 id 的字节序，JSON null 排在最后。

排除，不得成为 Frontier 的键，也不得因此改变哈希：`attempt_no`、`fence`、重试次数、streak、cap 消耗、配额剩余、收据条数、`duty_cycle`、`should_run`、`turn_no`、`events.seq`、时钟、lease、通知次数、effect id、session id。成员、status、文本哈希、due、link、缺口的变化必须改变哈希。

两份文档分开。`frontier_hash` 只消化一份未截断的 Frontier jsonb。那份 jsonb 含每一个成员和每一个缺口。增加、删除或改一个缺口的字段，都必须改变这个哈希。`encode(digest(convert_to(Frontier::text, 'UTF8'), 'sha256'), 'hex')`，复用已有 `digest`。每个 gap 对象的键恰好是 `gap_kind`、`subject_todo_id`、`object_todo_id`。驱动器只原样传递返回的 `frontier_hash` 文本，自己不计算哈希。驱动器读到的 `gaps` 与 `has_obligation` 是这份额外文档的 32 条前缀。`omitted_count` 与 `omitted_complete` 在哈希之外。`omitted_complete = false` 仍拒绝首次插入。返回的 32 条里没有某键，且 `omitted_complete` 为假，仍不是缺失，不得清开放位。关闭谓词的在场/不在场，以及 H/H'，只用义务折叠文档：同一套 Frontier 键，只重放 `plan/committed` 与 `todo/delta`，无水位过滤，无 32 帽。`v13_frontier_project` 的 `frontier_hash` 不关闭任何一位。它仍只是插入时的 `p_expected_hash` 与 `stale` 比较值。实现时核对 `jsonb::text` 的对象键序是确定性的。不是就停并 `ASK_USER`，不另写序列化器。

非 NULL 的 `p_before_seq` 在 `v13_frontier_project` 内部、用 `seq < p_before_seq` 重折 Phase A 水位。活体一参 `v13_plan_current` 只用于 `p_before_seq` 为 NULL 的当前检查。不改 Phase A。水位谓词对不上已接受的 Phase A 文本：停并 `ASK_USER`。

两套折叠分开。

水位前沿是 `v13_frontier_project` 与一参 `v13_plan_current`：未截断 jsonb、`frontier_hash`，另有 32 条前缀给驱动器读。首次插入的 `no_gap`、`stale`、`p_expected_hash` 只用这一套。当前投影仍按水位过滤。返回的 32 条里没有某键，且 `omitted_complete` 为假，不是缺失，不得清开放位。`omitted_complete = false` 仍拒绝首次插入。

义务折叠只重放 `plan/committed` 与 `todo/delta`。`v13_obligation_open` 只重放这两种事件。它不调用 `v13_frontier_project`，也不让水位帽清掉开放位。一个键是开放的，当且仅当它的 `replan/required` 行存在（`source_effect_id` 不在 `effects` 里，载荷恰好 `{"schema_version":1}`），并且该键出现在当前义务折叠里。当前义务折叠只有 `plan/committed` 与 `todo/delta`，无水位，无 32 帽。`obligation_open_count` 计这些开放位，不设帽。返回的 32 条里没有某键，且 `omitted_complete` 为假，仍不是缺失。`user/message` 与 steer 不改变义务折叠。更晚的 `plan/committed` 替换它的缺口集。语义键是 `(root, gap_kind, subject, object)`，不含 `plan_id`。换 `plan_id` 不是修复，也不插第二条 `replan/required`。

**关闭谓词。** 开放位与「已回应」是同一位。P 关闭这一位，当且仅当 P 是 `plan/committed` 或 `todo/delta`，该键在义务折叠里、上一条义务折叠事件处仍在。上一条计划事件只指义务折叠里的前一条，种类是 `plan/committed` 或 `todo/delta`。该键在 `seq <= P.seq` 的义务折叠里不在，且这两次义务折叠的哈希不同。H 与 H' 只消化义务折叠文档：同一套 Frontier 键，只重放 `plan/committed` 与 `todo/delta`，无水位过滤，无 32 帽。没有载荷字段存放哈希。`v13_frontier_project` 的 `frontier_hash` 仍只是插入时的 `p_expected_hash` 与 `stale` 比较值。已加载的每一种水位失效事件，包括 `user/message` 与 steer，只让可派发的水位投影失效，不清除义务折叠里最后的语义状态。水位把当前数组折空不是缺失。更晚的计划事件若仍含该键，这一位保持开放，并且不另插 `replan/required`。这些失效种类既不打开也不关闭这一位。

同一语义键再次出现，重放原来那条义务，不插第二条。第二次插入返回原 `event_id`。义务事件数仍是 1。缺口在、修掉、同键再回来：开放计数 `1 → 0 → 1`。

父若要求这个键真实出现在 `replan/required` 或 `plan/committed` 载荷上：停并 `ASK_USER`。前者要改 stage 17 的守卫，后者要改 Phase A 写者。两者都不做。

缺口闭集只有两个，不进口 LoopX 16 条，不建 `[15,30,60]`，不建 `replan_history`，不建 semantic-delta ACK 事件：

| `gap_kind` | 含义 | 对象 |
|---|---|---|
| `dangling_link` | 当前计划成员的 `link.id` 非空，且不在当前成员集。与 `successor_missing` 不重叠 | `subject_todo_id` 是载体；`object_todo_id` 是该非空目标 |
| `successor_missing` | 当前计划成员的 `link.on = successor` 且 `link.id` 为 JSON null | `subject_todo_id` 是载体；`object_todo_id` 为 JSON null |

`blocker` 未退役、monitor 到期、streak、attempt、配额都不是缺口。无当前计划时缺口数组为空，哈希仍可计算，插入者见空数组则 RAISE `no_gap`，零写。

这两个缺口必须能经 `v13_plan_writer` 产生。写者若已经拒绝 dangling link 或空 successor：该 kind 不进入实现闭集。两个都被拒绝，闭集变空：停并 `ASK_USER`。不得绕过写者 INSERT 计划事件来制造缺口，不得改写者来放行。

扫描帽是种子 `frontier_gap_cap = 32`，再探测紧接着的 1 行。第 33 个缺口使 `omitted_count = 1`、`omitted_complete = false`，投影仍零写；插入者 RAISE `v13: replan gap: cap`，零写。不得为不完整前沿发布义务。这个 32 是本期种子，不是席位常数。

义务自然键：`replan:{root}:{gap_kind}:{subject_todo_id}:{object_todo_id 或空}`。不含 `plan_id`，不含哈希。新的 `plan_id` 不是新义务，也不回应旧缺口。`plan_id` 仍可留在 Frontier jsonb 里。生成与插入只发生在插入者的根锁内。`source_effect_id` 经 Phase A `v13_plan_apply_id` 从这句文本派生。不复制算法。该函数签名若不是「text 进、uuid 出」，停，不另写一份。Python 不调用该函数，也不自己算这个 uuid。`static_check` 见到 Python 调用即失败。插入者按这个语义键重放。`obligation_at_most_one` 是每个语义键一条 `replan/required`。`no_gap` 与 `stale` 只在该语义键还没有旧义务时适用。

STABLE 折叠 `v13_obligation_open` 只重放 `plan/committed` 与 `todo/delta`。它不调用 `v13_frontier_project`。水位帽不能清掉开放位。它可以调用同一个 `v13_plan_apply_id`，只为了比对候选 uuid。它把义务折叠恢复到 `seq < O.seq`，枚举自然键，必须恰好一个 gap 对上 `O.source_effect_id`。不加载荷键，不建表，不建账本。若该函数不能从 STABLE 函数调用：停并 `ASK_USER`。不得声称 D3 断言可实现。

插入者锁内顺序，前一步失败则零写：

1. 会话隔离级别不是 `READ COMMITTED`：RAISE `canonical`。驱动器在调用前设置该隔离级别。函数自己也检查。
2. 沿 `parent_session_id` 映射到根，对 `v13_goal_stop` 所锁的同一行做 `FOR UPDATE`。`parent_session_id IS NULL` 的行被锁之后若多于一个根会话：RAISE `not_single_tree`。`obligation_at_most_one` 靠这把锁成立，不建唯一索引。
3. 授权先于任何重放返回。只两类，不套到普通 tool/llm complete：显式 `NULL::uuid` 且 `v13_control_operator()` 为真；或非 NULL 且 `v13_control_authorized(actor, target)` 为真。根上非 NULL 拒绝，RAISE `auth`，零写，不返回旧事件。显式 NULL 且不是 operator：同样 RAISE `auth`，零写。无人值守 `plan_commit` 仍未授权。本函数不是 `plan_commit`，不调用 `v13_plan_writer`。
4. 只有授权通过之后，才在这把锁内调用 `v13_plan_apply_id` 派生 uuid。
5. 该 uuid 已存在于 `effects`：RAISE `canonical`，零写。这防止挂到 harness 前驱。
6. 根流上已有 `type = replan/required` 且 `source_effect_id` 等于该语义键 uuid：重放，返回原 `event_id`，零新事件。这一步先于 stopped / 终态拒绝，也先于 `no_gap` 与 `stale`。载荷只能是 `{"schema_version":1}`。同一语义键再次出现也走这一步，不插第二条。新的 `plan_id` 不改变这个 uuid。
7. 只有该语义键还没有旧义务时，才拒绝根已 stopped，或 status 属于 `completed` / `failed` / `cancelled`。
8. 只有没有旧义务时，才锁内重算当前投影。`omitted_complete` 为假：RAISE `cap`，零写。不得把「不在返回的 32 条里」当成 `no_gap`。当前水位过滤后的数组为空，或该语义键不在未截断缺口集里：RAISE `no_gap`。`p_expected_hash` 与只消化 Frontier jsonb 的哈希不等：RAISE `stale`。第 6 步已经重放返回之后，`cap`、`no_gap`、`stale` 都走不到。
9. 只有没有旧义务时，才插入一条根上的 `replan/required`。载荷恰好 `{"schema_version":1}`。`source_effect_id` 是锁内派生的 uuid。零 effect，不调用 advance，不写 `turn/material_spent`，不调用 `v13_insert_nudge`。

不给 `replan/required` 加新的载荷触发器。加了就会拒绝 signals 路径。折叠与 D3 只认：载荷键恰好 `schema_version`，且 `source_effect_id` 不在 `effects` 里。signals 路径的行有真实 effect id，不算义务。

错误前缀 `v13: replan gap:`，token 只使用：`auth`、`stopped`、`terminal`、`no_gap`、`stale`、`canonical`、`cap`、`not_single_tree`。

### 4.2 B5 谁可以调用 `v13_advance`

收据事件只由 harness 收据臂写入。监督进程、Phase A 驱动器、Phase B 驱动器都不得 INSERT 这个类型。`task_class` 不是豁免。`should_run=false` 不是「不要调用 advance」，也不是「零事件」。

| 种类 | 是否候选 | 调用者 | 本期新增 | 收据 |
|---|---|---|---|---|
| `harness_turn` 且 `result_kind` 为 `progress` 或 `finish`，status `succeeded`，尚无同源收据 | 是。活体谓词见第 3 节。实现重读 `plan_arm` 副本，正文必须仍是这句 | Phase A `loop_driver` 的结算入口。监督进程不直接调用 `v13_advance`。它调用 `goal_supervise` 里的 `v13_harness_settle` | 新增的是同一事务包装，不是第二份 advance | 臂写。第二次不得写出第二张同源收据 |
| harness 的 `wait` / `reject` | 不在活体候选谓词里 | 不新增 | 无 | 不发明收据 |
| 非 harness 的 tool，含 `read_file_py` | 否 | Phase A 为归档而发生的那次 advance 仍归 A | 无 | 不声称扣了 material |
| 工作区六个工具 | 否。不是 `harness_turn` | 不调用 | 无 | 不声称已扣 material。父若要求本期为它写收据：停并 `ASK_USER`。不得放宽谓词，不得加宽 `v13_llm_tool_calls`，不得编辑 `workspace_exec` |
| human | 否 | 无 | 无 | 不 complete，不 skip |
| monitor quiet | 无未付 harness 候选 | 无 | 无 | 不调用 advance，所以没有新收据 |
| monitor 若已经完成一次未付 `harness_turn` | 与第一行相同 | 与第一行相同 | 与第一行相同 | `task_class` 不抑制收据 |
| planning | 写者零 effect | 不调用 | 无 | 无收据 |

`v13_unpaid_harness_turn(uuid)` 只定义在 `goal_supervise` 的 SQL 里，不是 `goal_supervisor` 的 SQL。监督进程只调用它。它是 STABLE。它返回抄来的收据 SELECT，不加 `LIMIT`，不加 `ORDER`。成功时是 0 或 1 行，只因为活体 SELECT 已经如此。否则该 stage 非零退出，不自行挑一行。候选集必须与第 3 节的活体 harness 谓词同一句，并且还没有把该 id 写成 `source_effect_id` 的 `turn/material_spent`。它不是收据臂的第二份写者。对不上活体谓词：把帮助函数改成与活体 SELECT 一致。要改收据臂才能一致，则进入第 1 节的停止。

`v13_harness_settle(uuid, uuid, uuid, jsonb)` 也在 `goal_supervise`。参数是 `p_actor`、`p_root`、`p_effect_id`、`p_snap`。`p_snap` 是该未付 harness effect 上已经存着的结果 jsonb。列名在实现时从加载后的目录读出，写入 README。本规划轮不发明列名，也不发明一份 snap。目录里没有这份已存 jsonb：停并 `ASK_USER`，消息 `v13: harness settle: ask_user`。驱动器原样复制该 jsonb，不增删 `failed` 或 `route`。`stopped_failed_snap_no_advance` 在该 effect 上存一个非空 `failed`。`stopped_without_failed_key_still_settles` 存一份没有 `failed` 键的 jsonb。

驱动器在这个结算事务开始时设置 `READ COMMITTED`。其它隔离级别在调用 `v13_advance` 之前拒绝，零次 advance，错误 `v13: harness settle: canonical`。一个事务：先锁 `v13_goal_stop` 所锁的那一行根会话。实现重读该锁语句，对不上就停，不改 `v13_goal_stop`。锁之后、任何 advance 之前，做第 4.1 节的两类授权。失败则 RAISE `v13: harness settle: auth`，不调用 advance。然后在同一把锁下要求 `p_effect_id` 仍是同一个合格 harness 前驱，含 `result_kind` 与 `succeeded`。已 stopped 且 `p_snap->>'failed' IS NOT NULL`：不调用 `v13_advance`，零 `resolve/failed`。这包括 JSON `false`、`0`、非空文本。键缺失与 JSON null 不在这道禁令内。

不接受未绑定 effect 的根级结算调用。共享查询抄加载后的收据臂 SELECT，含它的顺序与 limit，再加上未付 `turn/material_spent` 过滤。不另写字节序胜者。只有该 SELECT 返回 `p_effect_id` 时才调用 `v13_advance`。两条未付行都还在、且该 SELECT 没有已经只返回其中一条：进入第 1 节的停止，不替换 advance。`multiple_unpaid_candidates`：新收据的 `source_effect_id` 必须等于被允许调用的那个 `p_effect_id`，另一 id 不增加 `turn/material_spent`。已有 `v13_advance` 若提前返回、消费不了该候选：该 stage 按第 1 节非零退出，不是 `exit_0`。不替换 advance。否则在同一把锁、同一事务里调用已有 `v13_advance`。调用返回之后，外层才提交。`v13_unpaid_harness_turn` 与 `v13_harness_settle` 只定义在 `goal_supervise`。对监督进程，它们是唯一的 advance 路径。这不是禁止 Phase A 结算入口。监督进程按第 4.7 节允许名单调用，不直接调用 `v13_advance`，也不调用 `v13_interaction_offer`。一次 tick 对一个未付候选至多结算一次。human 待应答不得跳过这次结算。

`goal_stopped` 本身不禁止收据；该事件在指纹排除名单里。quiet 与「有未付候选」互斥。有未付 `progress|finish` 候选时，这一跳不是 quiet，即使 `should_run` 为假、即使 B1 出口是 `wait`。

这次调用不计入 Phase A 的 `provider_requeue_one_advance`。它不是 provider 再入队。监督进程不因此再启动模型。

`WHEN 'tool'` 不扫描已有 `claimed` 行。结算调用仍是完整的已有 `v13_advance`。若 snap 的 route 选中工具，活体臂可以新建别的 effect 并 `v13_send_work`。那是既有函数。本期不禁止这次新建，也不为此替换 advance。

断言 `settlement_does_not_dispatch_claimed_workspace` 只绑定调用前已经存在、且 `lease_owner = v13_workspace_opener` 的那个 `effect_id`：收据可以增加；该行 status 不变；不为该 `effect_id` 新增 `tool/call`；不把该行交给 `v13_send_work`。整个调用出现别的新 effect，不是本断言的失败。若要求整个调用零 `v13_send_work`，那是改 advance，停并 `ASK_USER`。govern `:764-773` 的 waiting 返回不是通过。

### 4.3 B6

无人值守声称之前，`goal_supervisor` README 必须有 `## B6`。测试解析该节，缺行即失败。Phase A `loop_driver` 的表不授权该声称。实现时把 Phase A 已有行照抄进本节，所有者不改。「监督进程允许」一列只写本期进程能做的事，避免把 A 的 chain 调用者说成 C 又做了一遍。

Phase A 行名必须都在：identity、enqueue、receipt、closeout、projection、cancel classification、harness observation、result_kind、actor、credentials and filesystem、disposition write permission、policy、children_terminal observation、pointer、fourth-duty。

`fourth-duty`：只读加载后的 `plan_arm` 里那份 `v13_advance` 正文，查找这个词。不复制函数。找到则把活体名字写进该行，所有者仍是 SQL。没有活体名字就写 `none`，并记下查找范围。不得为填表新造职责。不得写「驱动器只做 IO」。

本期新增行：

| 职责 | 持久语义所有者 | 监督进程允许 | 禁止 |
|---|---|---|---|
| supervision | 具名 SQL 与已有 advance | 第 4.7 节 SQL 允许名单。入口未点名时不含一跳 import | INSERT effects/events；把 recover 当入队者；第二份 advance |
| lease | `v13_goal_lease_once` | 每个 tick 对有限租约至多一次 | 续租循环；缩短或改写 infinity；编辑打开者 |
| ambiguous hold | `v13_goal_ambiguous_hold` | 只读 | 标 `unknown`；标 `succeeded` 或 `failed`；cancel；清路径 |
| notification | `v13_notify_project` 与政策行 | 读 DTO | outbox；`notify/sent`；exactly-once 声称 |
| observation | `v13_observe_fold` | 只读 | 代答；link 表；send 账本 |
| evidence | `v13_evidence_check` | 测试可调用。监督进程不调用 | INSERT artifacts；把证据焊到 wake |
| replan obligation | `v13_replan_gap_insert` | 投影有未结缺口时调用 | 模型信号当义务；计数器触发插入；裸 INSERT |

### 4.4 C5

合法的人等待是非终态 `waiting`。本期不实现自动 skip，不把 options / timeout / deadline 写进 human effect 的两键请求。两键字面已读：`schema_version`、`interaction_ref`。实现重读 `plan_arm` 副本里的对应 enqueue。对不上就停。不改那份副本。

旁路仍是 `interaction/offered`。具名函数 `v13_interaction_offer(uuid, uuid, uuid, jsonb)`，VOLATILE。参数是 `p_actor`、`p_root`、`p_apply_id`、`p_offer`。`source_effect_id` 不是单独参数。它在 `p_offer` 里，和其它键一起校验。监督进程的允许名单不含它。测试直接调用，用来钉合同，不是让无人值守进程去发问，也不是解卡。

载荷闭集：`schema_version`（1）、`apply_id`、`interaction_ref`、`offer_kind`（`approval` 或 `question`）、`source_effect_id`（uuid 文本）、`options`（文本数组，长度 0 到种子 4，调用者排好，函数不代为排序）、`deadline`（可解析的 `timestamptz` 原文或 JSON null）。无其它键。缺 `source_effect_id` 或不是 uuid 文本：RAISE `canonical`，零写。不建唯一索引。

`p_apply_id` 必须等于 `p_offer` 的 `apply_id`。不相等：RAISE `canonical`，零写。重放身份只有 `interaction_ref`。不建唯一索引。

锁内顺序：隔离级别不是 `READ COMMITTED` 时，在查找、重放、写入之前 RAISE `v13: interaction offer: canonical`，零写。然后对 `v13_goal_stop` 所锁的同一行做 `FOR UPDATE`。`parent_session_id IS NULL` 的行被锁之后若多于一个根会话则 `not_single_tree`。`offer_race_one_event` 靠这把锁成立，不建唯一索引。然后做第 4.1 节的两类授权。授权失败 RAISE `auth`，零写，不返回旧事件。只有授权通过之后，才按 `interaction_ref` 查找重放。同载荷重放先于 stopped / 终态拒绝，返回原 `event_id`，零新事件。异载荷 RAISE `replay_conflict`。首次在 stopped 或终态上写：RAISE，零写。截止时间已过也不调用 `v13_complete`，不写 skip。

不把这个函数插进 approval 臂。那需要第二份 advance，或编辑 `plan_arm`。两者都停。错误前缀 `v13: interaction offer:`。Phase B 的 `human_pending` 拒绝保持在打开者里。本期不改打开者。

### 4.5 C6

`v13_observe_fold(uuid, uuid)`，STABLE，参数 `p_actor`、`p_root`。零写。先调用 `v13_control_authorized`。失败则 RAISE `v13: observe fold: auth`，不把 `v13_observe` 的空返回当成没有事实。授权通过之后调用已有 `v13_observe(p_actor, ids)`。`ids` 是本根树按 `session_id` 字节序的前 4 个，长度 1 到 4。第 5 个 id 只用来把 `omitted_count` 设为 1，不传入。这不是单元素数组。不修改 `v13_observe`。不 GRANT 新观察权。根上非 NULL 恒拒，与规划写者相同。监督进程用 operator 的显式 NULL。

返回闭集：`schema_version`、`root_session_id`、`lifecycle_stopped`、`session_status`、`pending_human`、`obligation_open_count`、`omitted_count`、`omitted_complete`。帽 4 只作用于本根交给 `v13_observe` 的行。按 `session_id` 字节序列出本根树的 id，最多传入 4 个，再探测是否还有第 5 个。因此 `omitted_count` 只是 0 或 1。摘要字段不截断。`pending_human` 为真，当且仅当该根有 `kind='human'` 且 status 属于 `ready`、`claimed` 或 `unknown` 的 effect。`obligation_open_count` 是全部开放义务的计数，不帽在 4。五条 observe 行的夹具：`omitted_count=1`，`omitted_complete=false`，零写。不返回 provider 原文，不返回 transcript。不建 link 表，不建 send 账本。观察者不 `v13_complete`、不 skip、不代答。不出现 `request_attention`。

`obligation_open_count` 只数第 4.1 节的义务行，而且是全量。这不是 auto-wake。README 与矩阵写明 V11 未读，不得声称 auto-wake 已闭合。

### 4.6 D1

不新造 hint 函数，不把 due 写进 hint。政策行：

- `v13_policies.name = notify_policy`
- `version = 1`
- `active`
- 不存在则 INSERT
- jsonb 相等则跳过
- 不相等则装载 RAISE，不 UPDATE

不得 UPDATE `workflow_template`、`workspace_tool_subset` 或 `judgment_templates`。value 闭集只有：`schema_version`（1）、`notify_on_user_gate`（true）、`notify_on_human_pending`（true）。没有 mute 键。没有冷却秒数。持久冷却需要一条不在指纹排除名单里的事件。本文不建那条事件。父若要求持久冷却：停并 `ASK_USER`。

`notify_on_human_pending` 由 `goal_supervise` 直接调用 `v13_notify_project` 断言。监督 tick 在返回 `waiting` 之后结束，不靠继续 tick 来证明这个开关。`v13_notify_project(uuid)`，STABLE，零写。先读 `v13_scheduler_hint`。根已 stopped，或 hint 为 `dont_notify`：返回 `deliver = false`，`reason = stopped_dont_notify`。零插入。`dont_notify` 是「已停，别触发」，不是用户静音。否则仅当政策开关为真且根上确有对应事实（未退役的 `user_gate`，或 human effect 仍是 `ready` / `claimed` / `unknown`）时返回 `deliver = true`，`reason = eligible`。活体 `v13_pending_human` 只计 `ready` / `claimed`（`v13/control/v13_control.sql:121-128`），不计 `unknown`。投影不得用它代替这句 SELECT。没有事实则 `reason = no_notice_fact`。第 4.9 节的 hold 有行时优先：`deliver = false`，`reason = ambiguous_hold`，零插入。它压过 `user_gate` 与 human 待应答。

监督进程把这个 DTO 放进进程内返回值。不插入 `notify/sent`，不建 outbox。不承诺 exactly-once，也不承诺已经送达。hint 若不能按「一个 uuid 进、三值文本出」调用：停。投递退回为读取加载后的那个三值函数，仍不新造事件族。

### 4.7 G3 与监督进程

`v13_recover_idle` 的消费定义：装载后正文与第 3 节一致，且不 INSERT effect 时，唯一生产调用者是 `v13/goal_supervisor/driver.py`。测试可以调用它。生产路径每个 tick 至多一次，在自己的事务里。不在 claim 路径上调用，不从打开者调用，不从 `plan_arm` 调用。返回值只进入进程内 tick 报告。返回值不得导致：插入 effect、插入 event、调用 `v13_insert_nudge`、调用 `v13_enqueue_effect`、调用 `v13_claim`、改 lease、把行标成 `unknown`、再调用一次 `v13_advance`。已有的 nudge 是该函数自己的行为，不是派发许可。不把 `recover/nudge` 加入指纹排除名单。

重读若发现它 INSERT effect 或调用 `v13_advance`：停，监督进程不调用它，不包装它，不把阶段标成 `exit_0`。

**允许直接调用的 SQL：**

- `v13_frontier_project`
- `v13_replan_gap_insert`
- `v13_unpaid_harness_turn`
- `v13_scheduler_hint`
- `v13_notify_project`
- `v13_observe_fold`
- `v13_goal_ambiguous_hold`
- `v13_goal_lease_once`
- `v13_recover_idle`（仅当上面的重读允许）
- `v13_harness_settle`（仅第 4.2 节的结算包装。不直接调用 `v13_advance`）
- `v13_should_run`（只对根。签名不是一个 uuid 进、布尔出则停，不包新函数，不用 `duty_cycle=0`）
- `v13_plan_current`
- `v13_selected_todo`
- `v13_wake_is_satisfied_v1`（只读。不把证据焊上去）
- `v13_goal_stop`（仅当 tick 输入 `request_stop` 为真，且根不是终态。不要求出口词 `stopping`。不加出口词）

不得调用：`v13_complete`、`v13_evidence_check`、`v13_plan_writer`、`v13_plan_apply_id`、`v13_plan_gate`、`v13_plan_commit_entry`、`v13_open_session`、`v13_tool_effect_open`、`v13_tool_result_accept`、`v13_spawn_subsession`、`v13_child_pointer`、`v13_enqueue_effect`、`v13_claim`、`v13_cancel`、`v13_insert_nudge`、`v13_interaction_offer`、`v13_llm_tool_calls`、`v13_goal_resume`、`v13_advance`。不得把 `replan/required` 放进 complete 的 signals。不得 INSERT / UPDATE effects、events、sessions、artifacts。不得写 `turn/material_spent`。

`v13_supervise_disposition(uuid)` 不新建。出口词只用 Phase A 已有的只读折叠：`v13_selected_todo` 的 `dispatch`，加上 `v13_should_run`、`v13_scheduler_hint`，以及本期自己的 human 待应 SELECT（`ready` / `claimed` / `unknown`）。不用 `v13_pending_human` 代替这句，因为它不计 `unknown`。监督进程不复制五出口状态机。不按公开函数个数挑选 API。

已接受的 Phase A 只写出文件 `v13/loop_driver/driver.py`，没有写出一跳函数名。因此本期不能点名那个入口。G3 续行接受项因此非零退出，消息 `v13: supervisor: ask_user`。其它断言可以记下，但不能代替这一项，也不能把无人值守续行行写成 `exit_0`。不编辑 `loop_driver` 去补名字，不复制出口机。无人值守 `plan_commit` 仍未授权。被 import 的函数不得调用 `v13_plan_writer`、`v13_plan_commit_entry`、`v13_plan_admit`。

父若以后点名那一个入口，调用合同是：一个会话 id 进，返回 Phase A 已有的一个出口词；外部 IO 在事务外；FakeLLM，不调用真实 provider。它能当唯一结算者，仅当已 stopped 的根上、已存 effect jsonb 的 `failed` 为 SQL NOT NULL 时，该入口不到达 `v13_advance`，且零 `resolve/failed`。做不到这个拒绝，它就不是结算者。本 tick 至多调用一次 `v13_harness_settle`。`unattended_continuation` 保持非零退出，消息 `v13: supervisor: ask_user`。同一个候选不得由两者都结算。不编辑 `loop_driver`。提交之后不再结算第二次。Fake 正例不依赖人：一次监督 tick 调用该入口，结果落成 SQL 行，下一次 tick 看见这次 advance。在名字被点明、且拒绝成立之前，这个正例不得标绿。

一次 tick，上界 `supervisor_max_ticks = 2`，无睡眠，无 `pg_cron`。事务内无文件系统 IO、无网络。监督进程只调用第 4.7 节允许名单。未付结算保持自己的事务。顺序：

1. 终态则返回。
2. 在任何调用之前决定唯一结算者。一跳入口还没被点名时，不 import `loop_driver`。有未付候选则调用 `v13_harness_settle` 一次并提交。名字被点明之后，只有该入口能守住 stopped 根上 `failed` IS NOT NULL 的拒绝，它才可以代替 `v13_harness_settle` 结算同一个候选，不能同时再调一次。做不到该拒绝，它就不是结算者，本 tick 仍至多调用一次 `v13_harness_settle`，且 `unattended_continuation` 保持非零 `v13: supervisor: ask_user`。不得结算两次。提交之后不再结算。human 待应答不得跳过这次结算。不直接调用 `v13_advance`。已有 `v13_advance` 若提前返回、消费不了该候选：按第 1 节非零退出，不是 `exit_0`。不替换 advance。不编辑 `loop_driver`。
3. 然后，human 仍待应答才挡住 provider import，并返回 `waiting`。不 skip。这个守卫在任何 provider import 之前，但在第 2 步结算并提交之后。返回 `waiting` 后本 tick 结束。后面的步骤本 tick 不再执行。这次返回不消费 `request_stop`。不得 cancel、skip 或 complete 该 human effect 来逼出 stop。
4. 未 stopped 且非终态，且水位投影 `omitted_complete` 为真时，才可能插入一条还没有义务的缺口。缺口按驱动器读到的 32 条前缀，取 `has_obligation` 数组里第一条为假的。一次 tick 至多一条。`omitted_complete` 为假则不调用插入者。调用 `v13_replan_gap_insert` 前设 `READ COMMITTED`。
5. 读 ambiguous hold。有 hold 行则 `deliver=false`，零插入。
6. `lease_once` 可以零次。若调用，只更新传入的那一个 `p_effect_id`。根已 stopped 或终态则不调用。调用前设 `READ COMMITTED`。
7. 在允许时至多一次 `v13_recover_idle`。
8. 读 hint 与 notify，再读 observe。
9. 只有本 tick 没有在第 3 步返回 `waiting`，且 `request_stop` 为真、根不是终态时，才走 `v13_goal_stop`。不要求出口词 `stopping`。不加出口词。返回 `waiting` 不消费 `request_stop`。

任一写调用失败则 tick 失败返回，不忙等。无人值守 `plan_commit` 仍未授权。

`p_expected_hash` 只来自 `v13_frontier_project` 返回的 `frontier_hash` 文本，原样传入。驱动器不把 `frontier` 再转成文本，也不自己算哈希。传输重试只适用于 `v13_replan_gap_insert`：最多 2 次，复用同一组 `gap_kind`、`subject`、`object` 与同一份返回哈希。不因此调用 provider，也不因此调用 `v13_plan_apply_id`。

允许声称的上限，只在 `goal_supervisor` gate 退出码 0 之后：单 goal、operator 角色、确定性 Fake 夹具下，进程可以在人不回答时保持 `waiting`，并且不为了解卡而 skip。不得声称产品角色已闭合，不得声称真实 provider 已通，不得声称人可以离开生产终端，不得声称 PC-4 配额。

### 4.8 种子

| 种子 | 值 | 不是 |
|---|---|---|
| `frontier_gap_cap` | 32 | 席位常数 |
| `observe_return_cap` | 4 | LoopX 16 |
| `evidence_refs_cap` | 4 | 席位常数 |
| `offer_options_cap` | 4 | 席位常数 |
| `supervisor_max_ticks` | 2 | soak，不是多日运行 |
| `replan_transport_retries` | 2 | 无界重试 |

不写 8，不写 64，不写 `[15,30,60]`，不挪用 Phase B 的 51200。51200 仍只是工作区结果文本帽。

### 4.9 G4 单 goal 切片

`v13_goal_ambiguous_hold(p_root uuid)`，STABLE，零写。只返回该根树里 `kind = 'tool'`、`lease_owner = 'v13_workspace_opener'`、status 为 `claimed` 的行的 `effect_id` 与 `tool_name`。不返回别的树。监督进程不得因此调用接受函数、`v13_cancel`、`v13_recover_idle`，也不得把行改成 `unknown`、`ready`、`succeeded` 或 `failed`。路径继续被 Phase B 的未终态扫描占住。本期不重写那次扫描，不编辑打开者。

SQL 不能证明外部进程已死。因此本期不提供 `mark_unknown`。父若要求把崩溃行标成 `unknown` 或 `cancelled`：停并 `ASK_USER`。不得在驱动器里猜测进程死亡。

`v13_goal_lease_once(uuid, uuid, uuid)`，VOLATILE。参数 `p_actor`、`p_session`、`p_effect_id`。`p_session` 先解析成唯一根。授权与第 4.1 节插入者相同两类，并且在任何更新之前检查。根上非 NULL，或显式 NULL 且不是 operator：RAISE `auth`，零更新。行为：驱动器先把会话设成 `READ COMMITTED`；函数发现不是该隔离级别则 RAISE `canonical`，零更新。先锁 `v13_goal_stop` 所锁的那一行根，并在这把锁下重查根生命周期，然后才锁并更新 effect。说不出与 `v13_goal_stop` 相同的根锁就停，不改该函数。`parent_session_id IS NULL` 的行被锁之后若多于一个根：RAISE `not_single_tree`，零更新。目标 effect 必须属于该根，且在任何更新之前 `status = 'claimed'`。找不到该行，或不在该根：并入 `not_claimed`。`stopped`、`terminal`、`not_claimed` 都是零行更新并 RAISE。前缀是 `v13: goal lease:`。不改 status，不改 `attempt_no`，不改 `fence`，不插事件。其它 effect 不变。

- `lease_owner = v13_workspace_opener`，或 `lease_until` 已是 `infinity`，或 `lease_until` 为 NULL：零行更新，返回 `infinite_unchanged`。NULL 与 `infinity` 同一句。不把它们改成有限租约。这不是 RAISE。
- 只更新传入的 `p_effect_id` 这一行。该行 `claimed`、`lease_owner` 不是 `v13_workspace_opener`、且 `lease_until` 有限且非 NULL：只把这一行写成 `greatest(现有值, clock_timestamp() + make_interval(secs => 60))`。60 秒只是活体 `v13_claim` 缺省 60000 毫秒的换算，不是新帽。成功或拒绝时，其它 effect 都不变。
- 每个 tick 对同一 effect 至多一次。没有睡眠，没有「每 10 秒」循环，没有 `pg_cron`。

这不是第二本账。不持有跨 IO 的 advisory lock。重读若发现加载后的 `v13_requeue_stale` 或 `v13_recover_idle` 会收回 `infinity` 或 NULL：不创建 `v13_goal_lease_once`，不在 Python 里循环 `UPDATE lease_until`。`goal_supervise` 的 gate 以非零退出，消息 `v13: goal lease: ask_user`。不得把这个失败改成跳过断言后的退出码 0。本规划轮读到的正文不会收回 infinity 或 NULL；实现仍须复核加载后的正文。

多 goal 领用、公平、饥饿、并发帽、多日 soak 仍是 Phase D。本期不写那条查询。

### 4.10 D2

可选键不进 `harness_result_schema`，不进 Phase B 的结果闭集。未知键失败是 Phase A 的 C7 合同。本期不改。函数是 `v13_evidence_check(p_root uuid, p_todo_id uuid, p_refs jsonb)`，STABLE，零写。`p_root` 是比较用的根。`p_todo_id` 是折叠任务类用的 todo。`p_refs` 为 JSON null：返回 ok，不读 `p_todo_id` 的证据。已有 complete 保持可用。监督进程不调用它，测试可以调用。

| 折叠后的 `task_class` | 键为 null | 键非 null |
|---|---|---|
| `advancement_task` | ok。不读 `children_terminal` | 下面的 artifact 规则 |
| `continuous_monitor` | ok。quiet 不因此去 complete | RAISE `wrong_class` |
| `user_gate` / `user_action` / `blocker` | ok。应答不是 artifact | RAISE `wrong_class` |

artifact 规则，只在键存在时：数组长度 1 到种子 4；每个元素是已存在的 `artifacts.artifact_id`；`produced_by` 指向的 effect 为 `succeeded`；该 effect 的 `session_id` 沿 `parent_session_id` 能到同一个根。否则 RAISE `v13: evidence: bad_ref`。没有会话列，不 `ALTER` 表。驱动器与测试都不得 `INSERT INTO artifacts`。`v13_evidence_check` 与 `v13_wake_is_satisfied_v1` 的正文互不引用。不进口 `VALIDATED_*`。

没有已存在的具名 artifact 写者时，`evidence_good_ref` 仍留在 gate 里。不声称正例已核。不 INSERT artifacts。C5、C6、D1、G4 的断言仍然执行。进程最后以非零退出，消息 `v13: evidence: ask_user`。该 stage 不是 `exit_0`。README 句子不能代替正例。写者存在时必须跑正例，不得用 README 句子替换。`bad_ref` 与「键缺失仍可 complete」无论写者在不在，都要跑。

### 4.11 PC-4 保持关闭

本期不实现根配额，不声称 goal 级配额，不声称无人值守多 spawn 预算。不改 `v13_quota_eligible` 的 session 局部计数。不 `CREATE OR REPLACE` `v13_should_run` 或 govern 的 gate。不升政策 version。

T7 的形状可以是新 stage 里的 STABLE 重算加一版新门，并且不必改 stage 1–29 的文件字节。本文不包含那个形状。原因是：要写新版本就必须抄 govern 的 gate 全文，抄错会改变配额以外的 `should_run`。本规划轮没有把那份正文收成可逐项对照的新版本。因此关闭，而不是假装「做不到所以文件字节被禁止」。父若以后要打开 PC-4，另写计划，并在那份计划里贴出加载后的 gate 全文哈希。

## 5. 范围

### 5.1 在 C 内

- B4 与 D3：第 4.1 节。哈希句先于 D3 断言。本规划轮未跑。
- B5：第 4.2 节的调用者表。工作区收据保持停止。
- B6：写在 `goal_supervisor` README。
- C5：等待合同与旁路函数。无自动 skip。旁路不接入 advance。
- C6：零写观察。
- D1：政策行加 STABLE 投影。
- D2：可选证据检查。
- G3：第 4.7 节。
- G4 的单 goal 切片：hold 与一次租约更新。
- PC-4：明确关闭，不实现。

一库一树，一个根，一个 goal。除 `not_single_tree` 负例外，测试不建第二根。负例只在会回滚的事务里，用已有具名函数再开一个根，零本期事件，回滚后仍是一棵树。不改 fanout SQL。

### 5.2 不在 C 内

- Phase D：多 goal 公平、饥饿、并发帽、多日 soak、多 goal 领用查询。
- B3。无目录。
- 自动 skip，以及把 options/timeout 写进两键 human 请求。
- 第二份 `v13_advance`。第二份 `v13_enqueue_effect`。
- PC-4，以及任何 goal 级配额或无人值守多 spawn 预算的声称。
- 修改 Phase B 的打开者、接受函数、路径互斥、`workspace_tool_subset`。不编辑 `v13/workspace_admit/**`、`v13/workspace_exec/**`、`v13/plan_arm/**`、`v13/loop_driver/**`、`v13/real_chain/**`、`v13/workflow_bind/**`、`v13/plan_contract/**`、`v13/plan_read/**`。
- 改指纹函数、fanout SQL、`quota_window`、stage 1–29 字节、已接受的三份计划。
- 真实 provider、`V13_REAL_PROVIDER_AUTHORIZATION`、stannum GRANT、请求 JSON 或库内的 API key。
- 新表、新列、工作流引擎、cadence、outbox、link 表、send 账本、`command_receipts`、`replan_history`。
- 把 `v13_recover_idle` 改成 effect 入队者，或在 claim 路径上调用它来代替计划臂。
- 无人值守 `plan_commit`。监督进程不调用 `v13_plan_writer`。
- 完整 G1 的再交付，十二步真链的再交付。

## 6. 目录与追加

本规划轮不改 `v13/load.py`，不分配 30、31 这类数字。实现时若 `workspace_admit` 还不是 `SQL_LOAD_ORDER` 的最后一项，停。Phase C 不补 Phase A/B 的键。允许的动作只是在当时的表尾追加，整数值为当时的「当前最大值 + 1」。禁止插到 1–29 中间，禁止插到 `workspace_admit` 前面，禁止重排。

| 顺序 | 目录 | SQL | 键名 |
|---|---|---|---|
| `workspace_admit` 之后 | `v13/frontier_gap` | `v13_frontier_gap.sql` | `frontier_gap` |
| 其后 | `v13/goal_supervise` | `v13_goal_supervise.sql` | `goal_supervise` |
| 无加载键 | `v13/goal_supervisor` | 无 | 不分配 |

`goal_supervisor` 发现自己必须有 SQL，或必须替换 advance：停。

依赖与尾部顺序分开：

- `frontier_gap` 的加载前缀含 1..29、Phase A 尾部直到 `real_chain`、以及 `workspace_admit`。它调用 `v13_plan_current` 与 `v13_plan_apply_id`。这两个符号在加载后不存在则停，不在本期再造。
- `goal_supervise` 依赖 `frontier_gap` 已装，以便观察计数能读到义务折叠。它交付 `v13_unpaid_harness_turn` 与 `v13_harness_settle`。监督进程只调用，不直接调用 `v13_advance`，不在自己的目录里再定义。它不调用工作区打开者，不替换 advance。候选集对不上活体收据谓词、且只有改收据臂才能对上：停，第 1 节。
- `goal_supervisor` 依赖前两个已装。它不依赖十二步链脚本。

每个新函数 `REVOKE EXECUTE FROM PUBLIC`。不 GRANT 给一个被写成已经证明的产品角色。新 SQL 不写 stannum GRANT。

装载测试库：新建一次性库；名字不得匹配 `agent_v13_%`，不得使用 `agent_v13_longloop_p0_probe`；已存在则拒绝并退出，不 DROP；清理只 DROP 本次创建成功的那一个。先装 1..29 到 govern，再装 Phase A 尾部与 `workspace_admit`，再装本期直到该测试的键。不调用 `v13/read_tools/setup_db.py`。不 DROP 现有库。超级用户夹具不是产品角色证明。

## 7. 分期合同

本规划轮没有跑本节任何命令。命令退出码 0 只是实现里程碑的通过条件。Fake 绿不是产品可用。

矩阵与台账是实现里程碑才创建的新文件。不改 Phase 0 / A / B 的矩阵、台账、计划与证据：

- `docs/reviews/v13-long-loop-phase-c-conformance-matrix-2026-09-29.md`
- `docs/reviews/v13-long-loop-phase-c-deviation-ledger-2026-09-29.md`

列：条目，目录，允许的声称，证据指针，状态。状态从 `not_run` 起。只有对应 gate 退出码 0 之后，该行才能写成 `exit_0`，并带上命令、退出码与库名。不设 `real_authorized_exit_0`。本文的存在不是证据。`frontier_gap` 的里程碑创建全表骨架，其余行先 `not_run`。后续里程碑只改自己的行。

公共证据：命令、退出码、一次性库名、断言名、相关 event / effect 计数。本规划轮没有这些退出码。

### 7.1 `v13/frontier_gap`

交付：B4 投影与插入，以及 D3 的断言。无 advance 替换，无 provider，无监督循环。

依赖：第 6 节。无本期前驱键。

Gate：`UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py`。本规划轮未跑。

断言：

- `project_zero_write`
- `hash_excludes_counters`
- `hash_changes_on_gap`
- `gap_cap_33_refuses_insert`
- `empty_plan_no_gap`
- `gap_kinds_closed`
- `writer_cannot_produce_gap_stops`（两个 kind 都不能经 `v13_plan_writer` 产生时，本 gate 非零退出，消息 `v13: replan gap: ask_user`。不得改用裸 INSERT，不得删本断言）
- `insert_one_replan_required`（载荷键恰好 `schema_version`；`source_effect_id` 不在 `effects`）
- `obligation_at_most_one`（每个语义键一条 `replan/required`。自然键不含 `plan_id`）
- `replay_same_event`
- `root_actor_replay_rejected`（合法插入之后，用根 UUID 当 actor 重试：RAISE `auth`，零写，不返回旧 `event_id`）
- `gap_reappears_same_event`（缺口在、修掉、同语义键再回来：开放计数 `1 → 0 → 1`，义务事件数仍是 1。第二次插入返回原 `event_id`）
- `user_message_keeps_obligation_open`（夹具字面是加载后的水位失效种类，可以不是 `user/message`。水位缺口数组可以折空。旧义务仍开放，`obligation_open_count` 仍计它。这不是缺失。已有义务上的再次插入返回原 `event_id`，不跑 `no_gap`）
- `obligation_message_plan_sequence`（义务，然后水位失效事件，然后修复计划：开放计数 `1 → 1 → 0`，因为修复计划去掉了该键。新计划仍含同一缺口：`1 → 1 → 1`，且不另插 `replan/required`。夹具字面必须是加载后的水位种类）
- `new_plan_same_dangling_stays_open`（新 `plan_id` 复用同一悬空关系：旧义务仍开放。第二次插入返回原 `event_id`。新 `plan_id` 不是新义务，也不是修复）
- `replay_after_stop`
- `first_insert_stopped_refused`
- `first_insert_terminal_refused`
- `counter_does_not_insert`
- `quota_exhaustion_does_not_insert`（不新增 block id，不把 `duty_cycle=0` 当夹具。不能在不改 `quota_window` 的前提下做成配额耗尽时，用计数器不变哈希、无缺口则 `no_gap` 这个替身。矩阵该行必须带 README 句子 `没有伪造配额账`。该行退出码 0 不是配额实跑，也不是 PC-4 证明）
- `response_same_hash_stays_open`
- `response_gap_removed_answers`
- `other_gap_does_not_answer_this_one`
- `binding_delta_hash_unchanged`（义务写下之后，只改绑定、不改 Frontier 键的 `todo_delta`：`frontier_hash` 不变，义务仍开放）
- `ack_substitute_does_not_reset`（一条开放义务之后调用 `v13_recover_idle`，让它写下已有的 `recover/nudge`。开放计数仍是 1，义务事件数仍是 1，`frontier_hash` 不变。不新增 ack 事件种类）
- `receipt_count_not_an_obligation`
- `signal_row_not_in_obligation_count`（经 `v13_complete` 的 signals 路径造出的行不进义务条数。造不出这条活体行就停，不改用测试 INSERT `replan/required`）
- `insert_does_not_call_advance`
- `payload_guard_unchanged`
- `advance_sql_not_replaced`
- `fingerprint_unmodified`
- `policy_version_still_3`
- `stage_bytes`

D3 四类就是：`counter_does_not_insert` 与 `quota_exhaustion_does_not_insert`；`hash_excludes_counters`；`ack_substitute_does_not_reset`（第三类，与哈希句同一命令，此前不得标绿）；`receipt_count_not_an_obligation`。不移植 280 行交织夹具，不建 `replan_history`。这些断言是计划，本轮未跑，不得写成已绿。

`stage_bytes`：相对本提交的父提交，stage 1–29、已接受的 Phase 0/A/B 计划、以及第 5.2 节点名的目录 diff 为空；`load.py` 只在表尾增加 `frontier_gap`。

提交边界：`v13/frontier_gap/`，`v13/load.py` 的这一次表尾追加，两份新评审文件的骨架与本行，本目录 README。README 记录种子、加载后 `v13_complete` 的 signals 段哈希、`jsonb::text` 的核对结论、写者能否产生两个 gap kind。

### 7.2 `v13/goal_supervise`

交付：C5 旁路、C6 折叠、D1 政策与投影、D2 检查、`v13_unpaid_harness_turn`、`v13_harness_settle`、ambiguous hold、一次租约函数。无文件系统执行，无 advance 替换。`goal_supervisor` 只调用这两个函数，不直接调用 `v13_advance`，也不在本目录之外再定义它们。

依赖：`frontier_gap`。

Gate：`UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py`。本规划轮未跑。

若加载后的 requeue 或 recover 会收回 `infinity` 或 NULL：本 gate 非零退出，消息 `v13: goal lease: ask_user`。不创建 `v13_goal_lease_once`。不得把该失败改成退出码 0。

否则断言：

- `waiting_not_terminal`
- `two_key_request_unchanged`
- `offer_not_wired_into_advance`
- `offer_replay`
- `offer_isolation_rejected`（非 `READ COMMITTED`：在查找之前 RAISE `v13: interaction offer: canonical`，零写）
- `offer_race_one_event`（两个 `READ COMMITTED` 连接抢同一 `interaction_ref`：只留一条事件；第二次同载荷返回原 `event_id`）
- `offer_auth_before_replay`（用根 UUID 当 actor 重试：RAISE `auth`，零写，不返回旧 `event_id`）
- `offer_replay_after_stop`
- `offer_first_write_stopped_refused`
- `offer_first_write_terminal_refused`
- `deadline_does_not_skip`
- `no_offer_unique_index`
- `explore_spawn_still_raises`
- `observe_zero_write`
- `observe_auth_raises`
- `observer_does_not_answer`
- `observe_cap_omitted`（五条 observe 行：`omitted_count=1`，`omitted_complete=false`，零写。摘要字段不截断。`obligation_open_count` 不帽在 4）
- `v11_not_marked_closed`
- `no_link_table_no_send_ledger`
- `notify_policy_idempotent`
- `workflow_template_v1_unchanged`
- `workspace_subset_v1_unchanged`
- `judgment_templates_untouched`
- `dont_notify_not_a_mute`
- `notify_eligible_inserts_nothing`
- `hint_function_unmodified`
- `evidence_absent_complete_works`
- `evidence_not_in_harness_result`
- `evidence_bad_ref_no_write`
- `evidence_wrong_class_user_gate`
- `evidence_wrong_class_monitor`
- `evidence_null_ok_for_advancement`
- `evidence_not_welded_to_wake`
- `evidence_good_ref`（断言留在 gate。没有具名 artifact 写者：不声称正例，不 INSERT artifacts；C5、C6、D1、G4 断言仍执行；进程非零退出，消息 `v13: evidence: ask_user`，本 stage 不是 `exit_0`。写者存在则跑正例，README 句子不能代替）
- `unpaid_predicate_matches_live_arm`（候选集与活体收据谓词同一句。要改收据臂才能对上则本 gate 不退出码 0，进入第 1 节）
- `stop_before_settle_no_resolve_failed`（两个连接。stop 先提交。其后的结算包装不增加 `resolve/failed`，resume 指纹不变。不替换 advance）
- `ambiguous_hold_zero_write`
- `ambiguous_stays_claimed`
- `lease_once_extends_finite`
- `lease_infinity_unchanged`（`infinity` 与 NULL 都零更新）
- `lease_auth_rejected`（根 UUID actor 或非 operator 的 NULL：RAISE `auth`，零更新）
- `lease_once_does_not_bump_attempt`
- `lease_stopped_refused`
- `lease_lock_session_then_effect`
- `no_advisory_lock`
- `no_renewal_loop_in_sql`
- `opener_files_unmodified`
- `recover_idle_unmodified`
- `policy_version_still_3`
- `no_second_advance_replace`
- `stage_bytes`

`stage_bytes`：相对本提交的父提交，stage 1–29、已接受的 Phase 0/A/B 计划、以及第 5.2 节点名的目录 diff 为空；`load.py` 只在表尾增加 `goal_supervise`。

提交边界：`v13/goal_supervise/`，`load.py` 的这一次追加，矩阵与台账的本行，README。README 写入 human 两键的重读名、artifact 列的重读结论、hint 签名、requeue 正文哈希。C5 行写明无人值守 skip 仍未授权。

### 7.3 `v13/goal_supervisor`

交付：B5 的结算调用者，B6 表，G3 的消费。无加载键，无 SQL。不复制 `loop_driver` 的出口机。不调用真实 provider。

依赖：`frontier_gap` 与 `goal_supervise` 已装。

Gate：`UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py`。本规划轮未跑。

`unattended_continuation` 不是可选项。已接受的 Phase A 没有一跳函数名，所以这一项不是 `exit_0`。先跑完第 7.3 节除 `fake_hop_persists_then_observed` 以外的断言。只有它们都通过，才发出 `v13: supervisor: ask_user`。其它失败仍是那个失败。矩阵行：一跳名字还没点明时，`fake_hop_persists_then_observed` 保持 `not_run`（跳过，不是失败）。它不挡住其余断言通过后的进程退出 `v13: supervisor: ask_user`。以后即便该断言标绿，也不把这一行写成 `exit_0`，也不代替该进程退出，直到父改 `unattended_continuation` 本身。它只在一跳名字与 stopped 根上 `failed IS NOT NULL` 的拒绝同时成立时才标绿：一次 tick 调用该入口，结果落成 SQL 行，下一次 tick 看见这次 advance，且不依赖人。不按公开函数个数挑选 API。不调用真实 provider，不自动 skip，不复制出口机。

断言：

- `b6_rows_present`
- `fourth_duty_none_or_live_name`
- `unattended_not_claimed_by_loop_alone`
- `quiet_does_not_call_advance`
- `unpaid_progress_calls_advance_once`
- `unpaid_finish_calls_advance_once`
- `second_settlement_no_second_receipt`
- `wait_reject_not_settled`
- `stopped_failed_snap_no_advance`（该 effect 上已存的 jsonb 含非空 `failed`。不发明 snap）
- `stopped_without_failed_key_still_settles`（该 effect 上已存的 jsonb 没有 `failed` 键。不发明 snap）
- `multiple_unpaid_candidates`（两条未付行都还在，且收据臂 SELECT 没有已经只返回其中一条：按第 1 节非零退出，不是 `exit_0`。若 SELECT 已只返回一条：新收据的 `source_effect_id` 等于被允许调用的 `p_effect_id`，另一 id 不增加 `turn/material_spent`）
- `human_pending_does_not_skip_settlement`（未付候选与 human 待应答同时存在：先结算，再返回 `waiting`，不 skip。`v13_advance` 提前返回、消费不了该候选：非零退出，不是 `exit_0`。不替换 advance）
- `planning_does_not_call_advance`
- `monitor_quiet_does_not_call_advance`
- `human_wait_no_skip`
- `workspace_complete_does_not_call_advance`
- `settlement_does_not_dispatch_claimed_workspace`（只绑定调用前已有的 workspace opener `effect_id`。不要求整个调用零 `v13_send_work`）
- `driver_does_not_write_material_spent`
- `unattended_continuation`（没有已点名的一跳入口：非零退出 `v13: supervisor: ask_user`，本行不是 `exit_0`）
- `fake_hop_persists_then_observed`（名字未点明时矩阵行保持 `not_run`，跳过，不是失败，不挡住其余断言通过后的 `v13: supervisor: ask_user`。只在名字与 stopped 根上 `failed IS NOT NULL` 的拒绝同时成立时标绿。该绿不写成 `exit_0`，也不代替进程退出，直到父改 `unattended_continuation` 本身。不依赖人。不调用真实 provider）
- `provider_word_does_not_start_second_machine`
- `recover_not_on_claim_path`
- `recover_return_does_not_enqueue`
- `no_lease_loop`
- `replan_insert_before_stop_only`
- `notify_dto_no_event`
- `observe_no_answer`
- `static_check`
- `no_real_provider`
- `policy_version_still_3`
- `stage_bytes`

`static_check` 扫 `driver.py`：`v13_` 调用超出第 4.7 节即失败。注释里出现名字不算调用。出现 `INSERT INTO effects`、`INSERT INTO events`、`INSERT INTO sessions`、`INSERT INTO artifacts`、`turn/material_spent`、`pg_cron`、API key 字段名即失败。测试文件同样不得包含这四类 `INSERT`。测试文件可以调用活体函数做夹具，包括 `v13_plan_writer`、`v13_complete`、`v13_goal_stop`、`v13_interaction_offer`、`v13_evidence_check`。驱动器路径不可以。

需要新会话的夹具由测试文件调用 `v13_open_session`，显式 `version: 2`，并在第一次 `v13_advance` 之前 `v13_submit_override`，`intent = direct`。不把 `max_cycles = 6` 抄进种子。监督进程不调用这两个函数。

`stage_bytes`：无 `load.py` 改动；第 5.2 节的目录 diff 为空。

提交边界：`v13/goal_supervisor/`，矩阵与台账的本行，README。不含 `load.py`。

提交顺序：`frontier_gap`，然后 `goal_supervise`，然后 `goal_supervisor`。每个实现提交都是路径级 add。禁止 `git add -A`。禁止纳入 `uv.lock`、`prompt-exports/`、调查、stage 1–29、Phase A/B 已有目录、父循环 memory、探针与日志。禁止 force、`reset --hard`、自动 stash、跳 hook。

## 8. 追溯

Phase 0 §7 的归属不改。

| 项 | 归属 | 本计划 |
|---|---|---|
| B4 | C | `frontier_gap`。哈希句先于 D3。载荷不违反活体守卫 |
| B5 | C | `goal_supervisor` 的调用者表。收据写者仍是收据臂。工作区 complete 不调用结算 advance |
| B6 | A；C 声称无人值守前再交表 | `goal_supervisor` README。A 的表不授权该声称 |
| C5 | 等待合同；无人值守 skip 未授权 | `goal_supervise` 的旁路与 `goal_supervisor` 的不 skip。旁路不接入 advance |
| C6 | C | `goal_supervise`。V11 未读，不标闭合 |
| D1 | C | `goal_supervise`。不是 exactly-once。stopped 上不插 |
| D2 | C | `goal_supervise`。无键的 complete 仍可用 |
| D3 | C | `frontier_gap`，与哈希句同一 gate。本规划轮未跑，不得标绿 |
| G3 | C | `goal_supervisor` 消费 `v13_recover_idle`。不改函数，不把它当入队者 |
| G4 | 单 goal 续租与崩溃行在 C；公平、饥饿、soak 在 D | `goal_supervise` 的 hold 与一次租约更新。不自动解除 ambiguous |
| PC-4 | 未实现。本文保持关闭 | 不声称 goal 级配额，不声称无人值守多 spawn 预算 |
| A1–A4、B1、B2、C1–C4、C7、G2 | A | 不重做 |
| G1、C2 子集 | B | 不重做。不重开打开者、接受、互斥、子集 |
| B3 | A 的不做项 | 无目录。C 不重开 |

不得声称：有过 plan 事件即放行；驱动器是收据写者；工作区 complete 已经扣了 material；有循环即无人值守已通；session-local 配额就是 goal 级；V11 或 auto-wake 已闭合；Fake 绿即产品可用；绑定窗在 `plan_arm` 退出码 0 之前已经闭合。

## 9. 开工重读与 ASK_USER

实现先做这些重读。任一停点成立：不写绕过代码，不改 stage 1–29，不加第二份 `v13_advance`，不把该 stage 标成 `exit_0`。

| 重读 | 停点 |
|---|---|
| `v13_control_event_guard` 对 `replan/required` 的载荷 | 不再是恰好 `schema_version`，或不再要求 `source_effect_id`。停。不改守卫来容纳 richer 载荷 |
| 加载后的事件守卫对 `interaction/offered` | 该种类尚未被允许，或允许的载荷键不是第 4.4 节那一闭集。停并 `ASK_USER`，消息 `v13: interaction offer: ask_user`。不改 stage 1–29。不加第二道载荷触发器。不拿掉触发器来让插入成功。`offer_*` 断言留在 gate 里，不得靠跳过这次检查变成 `exit_0` |
| `plan_arm` 里收据候选谓词的副本 | 与 govern `:849-866` 不一致，或工作区 effect 已是候选。后者若要写收据：停并 `ASK_USER`，不改谓词 |
| `v13_plan_writer` 能否产生第 4.1 节的两个 gap | 两个都不能：停并 `ASK_USER`。不裸 INSERT，不改写者 |
| `v13_plan_apply_id` | 不是 text 进、uuid 出，或 STABLE 折叠不能调用它。停并 `ASK_USER`。不另写一份。不得声称 D3 可实现 |
| 加载后的 `v13_recover_idle` | INSERT effect 或调用 advance：停，监督进程不调用 |
| 加载后的 `v13_requeue_stale` | 收回 `infinity` 或 NULL：停并 `ASK_USER`。不发明续租循环 |
| `v13/loop_driver/driver.py` 的一跳入口 | 已接受的 Phase A 没有函数名。不按个数挑选。G3 续行接受项非零退出 `v13: supervisor: ask_user`，不是 `exit_0`。不编辑该文件 |
| 加载后的水位种类，先于夹具 | 夹具字面必须是已加载的水位失效种类，包括该种类不是 `user/message` 的情况。只有识别不出任何失效种类，或谓词对不上已接受的 Phase A 文本，才停并 `ASK_USER`，消息 `v13: frontier gap: ask_user`。steer 以及其它已加载失效种类保持义务中性，不是停点。不插入替代事件种类。这些断言留在 gate 里。字面还没对上之前不是 `exit_0` |
| `WHEN 'tool'` 与结算 snap | 调用前已有的 workspace opener 行被派发或被 `v13_send_work`。停。不把「整个调用零 `v13_send_work`」写成合同。不替换 advance |
| artifact 具名写者 | 没有：`evidence_good_ref` 仍执行，正例不声称已核，不 INSERT。C5、C6、D1、G4 断言仍跑。进程非零退出 `v13: evidence: ask_user`，不是 `exit_0` |
| `v13_should_run` 签名 | 不是一个 uuid 进、布尔出。停 |
| 新函数名与目录名 | 搜索三个函数与三个目录。撞名：停，不静默改名 |
| 任何合同只有再替换 `v13_advance` 才能满足 | 停。第 1 节 |

另外保持未决，不得写成已核：产品库名、产品角色、stannum GRANT、V11、席位常数、stopped 上的 `user/message`、`steer/injected`、真实 provider 授权、PC-4、多 goal 领用查询。

## 10. 留给父复审

本文是候选。父复审之后才决定是否接受。实现在那之前不得开工。本规划轮没有完成父复审，没有把任一 lane 的草稿计数写成通过，没有跑任何 gate。

请父决定是否整组接受下列选择，或退回后重写。实现不得在退回前私自换一套：

- `replan/required` 载荷保持活体闭集。义务身份只在插入者根锁内、授权通过之后派生。自然键是 `replan:{root}:{gap_kind}:{subject_todo_id}:{object_todo_id 或空}`，不含 `plan_id`。同一语义键不插第二条，重放返回原 `event_id`。Python 不调用 `v13_plan_apply_id`。授权先于重放。`no_gap` 与 `stale` 只在还没有旧义务时适用。
- 缺口只有 `dangling_link` 与 `successor_missing`。写者产不出就停，不改写者。
- 工作区 complete 不调用结算 advance。未付 harness 候选由 `v13_harness_settle` 在 `READ COMMITTED` 与授权之后调用已有 `v13_advance`。不直接调用，不替换。
- `interaction/offered` 有具名函数。`source_effect_id` 在 `p_offer` 里校验。授权先于 `interaction_ref` 重放。不接入 advance，监督进程不调用。
- ambiguous 只读 hold。不标 `unknown`，不 cancel，不续成有限租约的 infinity 行。
- 有限租约的一次延长，不是睡眠循环。授权与插入者相同。`lease_until` 为 NULL 时与 `infinity` 一样零更新。根已 stopped 或终态则不调用。
- PC-4 关闭。不声称 goal 级配额。
- 三个目录。只有两个 SQL 键，追加在 `workspace_admit` 之后。无第二份 `v13_advance`。
- 没有具名 artifact 写者时，`evidence_good_ref` 使整个 `goal_supervise` gate 非零退出，不是 `exit_0`。不 INSERT artifacts。C5、C6、D1、G4 断言仍跑，但不能把该 gate 写成通过。

不接受则停。不得在实现里换成另一套控制面。

本规划轮未跑：`UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py`、`UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py`、`UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py`。它们是计划，不是通过。
