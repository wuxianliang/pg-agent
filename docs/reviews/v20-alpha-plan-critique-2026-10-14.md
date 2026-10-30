# v20 alpha 计划评审

日期：2026-10-14。对象：`docs/plans/v20-alpha-2026-10-14.md`（下称「计划」）。保真基线：计划本文 + Oracle 对话 `untitled-chat-766632`（三个范围裁定均 A：纵向循环子集表、进程内 `echo`、一个 gate 一次提交）。本评审不重开这三项，也不重开 `expects_handle = true` 的句柄规则本身（仅订正其行号引用，见 3.3）。

核查方式：对计划引用的设计五、章程、v23、v13、`BRIEF.md`、`AGENTS.md` 逐条做了定点核对；对 `v20/experiments/ce_native_d5/` 的 turn/tool 结算顺序做了一次定点核对。未做 broad exploration。

---

## 1. 计划先立后弱或自相矛盾的实现性内容

### 1.1 第一个控制 turn 永不结算（最重的一条）

计划 §6.1 的已提交顺序：`start` 的 T1 插入第一个控制 turn（第 1、4 步），随后 `admit_tool`（第 4 步）→ `accept_tool_result`（第 6 步）→ `admit_turn`（第 7 步）→ `accept_turn_receipt`（第 9 步，结算的是 **admit_turn 那一行** turn）→ 最终 `publish_snapshot`（第 10 步，结算 start 的 **operation**）。全链没有任何一步结算 **start 那一行** `v20_turns`：它永远停在 `status = admitted`，它的响应 activity 也永远不会被写。

这与计划自己冲突：

- 计划 §4.3/§6.1 引用设计五 `:336`：响应 activity 写在校验通过的 T2。第一次 provider 调用的响应（含 `tool_calls` 的回执）没有 T2 落点。
- 计划第 11 节探针 `response_activity_on_t2` 无法对第一轮 provider 调用成立。
- 计划 §5.4 的 `decide` 第 5 条「有未接受的 turn 准入 → `run_now`」：start turn 永远是未接受准入，在 run 到达终态之前 `decide` 恒为 `run_now`，`wait` 语义被架空。

修正（有已跑形状支撑，不是新发明）：`v20/experiments/ce_native_d5/scenario.py:623`–`:675` 的顺序是 `admit_turn` → **`accept_turn_receipt`（回执里带 tool_calls，turn 在此结算）** → `admit_tool` ×N → `accept_tool_result` ×N；`control.py:1889`–`:1944`（`_accept_turn`）在 accept 时把 turn 置 `completed` 并写回执，`_admit_tool`（`control.py:2073`–`:2134`）只核对 turn 的 `run_id`/`epoch_id`，不要求 turn 仍 pending。计划 §5.4 第 4 步应在「对每个工具 `admit_tool`」之前插入对该回执的 `accept_turn_receipt`，§6.1 在第 3、4 步之间补上这一笔 T2。设计五 `:334` 也支持：每个 turn 在自己的校验通过 T2 结算并写响应投影。

### 1.2 锁顺序的引用与正文不符

计划 §5.1：「锁顺序，与设计五 `:347` 一带相同：run，session（`_lock_pair`），然后当前 epoch，然后这次要写的 operation。」

设计五 `:347` 原文是「锁的顺序是 **run、epoch、operation、artifact**。T2 用同一顺序。」全文没有 session 锁这一环；alpha 不建 artifact 表，第四环自然消失。

计划实际引入的 run → session → epoch → operation 顺序本身是合理的（`steer`/`cancel`/`cleanup` 要 CAS `sessions.revision`，必须锁 session），但这是一个**新增环节**，不是「相同」。二选一：改写为「设计五 `:347` 是 run → epoch → operation；alpha 在 run 之后、epoch 之前加 session 锁，因为 steer/cancel/cleanup 要 CAS `sessions.revision`」，或在第 12 节偏差台账加一条。现状的写法会让实现者以为 `_lock_pair` 有设计五依据。

### 1.3 `resolve_handle` 的等待被规定了两遍

- 计划 §5.1：`resolve_handle` 在事务外等到 `wait` 同款超时（默认 2 秒）后重读，仍 `pending` 则返回 `{state: "pending"}`。
- 计划 §5.4 第 2 步：`resolve_handle` 返回 `pending` 后 Host 再 `wait` 一次、再解析，仍 `pending` 才返回 `wait`。

叠加后同一路径最多等约 4 秒，且探针 `pending_handle_returns_wait_not_forever` 无法同时钉住两种语义。二选一：等待逻辑只放在 `resolve_handle` 内（Host 拿到 `pending` 直接返回 `wait`），或 `resolve_handle` 不等待、由 Host 等一次。前者与 §5.1 的四态描述更自洽。

### 1.4 错误表里 `Rejected` 的例外条款没有着落

计划 §7：`Rejected` 的「是否写库」一栏是「否，**除非设计五要求只追加归档事件**」。计划没有指明哪些 `Rejected` 情形要求只追加归档事件；设计五里「只追加归档事件」的行为属于迟到 T2（计划已单列 `FenceRejected`），不属于 `Rejected`。要么列出具体情形，要么删掉这个例外，否则 gate 无法判定该写还是不该写。

---

## 2. 欠规约的接缝

### 2.1 哪些动词写 `v20_operations` 行，计划全文未说

计划 §4.1 说 `v20_operations` 管「幂等、fence、句柄等待」，§6.4 的重放语义（同 `request_id` 返回已提交行）依赖 operation 行的存在，但计划从未说哪些动词插行。设计五是明确的：`:325` 只有六个准入动词（`start` / `claim_resume` / `steer` / `respond` / `admit_turn` / `admit_tool`）在 T1 插 pending operation；`:369` `poll` 只读、`wait` 只 LISTEN + 读权威 revision，都不插行；`:337` `record_provider_handle` 沿用本次调用的 `request_id`，不另开 operation（计划 §8 对此一致）。计划应照写这一句，否则 `poll`/`wait` 是否参与幂等重放、`request_id` 由谁生成都是实现者的自由发挥。

### 2.2 `recover_owner` 的「旧 pid 已死」如何判定

计划 §6.2 以「旧 pid 已死」为前提，`owner_backend_pid` 是调用方后端 pid。计划未写判定机制。若用 `pg_stat_activity`，要回答：`v20_alpha_control` 只是 LOGIN 角色，对其他后端的可见性是否够用（pid 列可见，但要在 gate 里实证，而不是假设）；以及 owner 连接已关闭但 Host 进程持另一条连接存活的竞态——此时旧 pid 已死，`recover_owner` 会把一个仍有主在跑的 run 置 `expired`。计划 §3.5 说「一个 Host 进程驱动它自己持有的 run」，但 fence 是按后端 pid 而非按进程。alpha 至少要写死：判定 SQL 是什么、由哪个角色执行、上述竞态在本切片是否接受（接受则记入台账）。

### 2.3 `claim_resume` 的正向前提有缺口，`resume_after_cancel_publishes` 落在缺口里

计划 §6.2 只给了两条负向规则：`resumable` 不为 true（或 terminal 且不可恢复）→ `Rejected`；run 仍 `running`/`waiting_for_input` 且 pid 仍活 → `AlreadyActive`。但第 11 节有探针 `resume_after_cancel_publishes`：`cancel` 之后 run 是 `cancelled`、session 不是 `terminal`、`resumable` 仍为 true（§6.3 明确 cancel 不改 `resumable`）。这个状态既不命中 `Rejected` 也不命中 `AlreadyActive`，计划没有说它能否恢复、恢复后 run 状态是什么。同理 `completed`/`failed` 的 run 能否 `claim_resume` 也未规定。必须把正向前提写成闭集（例如：仅当 `resumable = true` 且 run ∈ {`expired`, `cancelled`, `completed`, `failed`} 且 owner 不活），否则探针无法实现。

### 2.4 哪些动词发 NOTIFY 没有规定

计划 §5.1 定义了信道 `v20_alpha_run_changed` 与载荷格式，但全文只有 §6.3 的 `cleanup` 写了「提交后 NOTIFY」。`cancel`、`steer`、`recover_owner`、终态 `publish_snapshot` 是否 NOTIFY 未写。`wait_sees_cleanup_revision` 只覆盖 cleanup；`lost_notify_seen_on_timeout` 证明超时兜底存在，不能替代发送方的规定。写成一句通则即可（例如：凡推进 `runs.revision` 的提交都发）。

### 2.5 `input_kind` 的确定时点

计划 §6.1 第 7 步「`input_kind` **将是** `host_continue`」用了将来时。`WorkerRequest.input_kind` 在构建请求时就必须是定值，且 `input_digest` 依赖它。应写死：`input_kind` 在 `admit_turn` 的 T1 载荷里确定并随 operation 落库。

### 2.6 `progress` 无工具分支的循环终止条件

计划 §5.4 第 5 步：回执 `progress` 且无工具 → 发进度快照，operation 保持 `pending`，run 保持 `running`——然后回到第 3 步再调 FakeWorker。FakeWorker 是纯函数，输入不变则回执不变，此分支是无界循环。给定的两个脚本（默认、`needs_input`）都不会走进这个分支，所以不阻塞本 gate；但计划应写一句终止规则（例如：连续两次 `progress` 且 `snapshot_seq` 之外无任何状态变化则 Host 返回 `wait`，或计次上界后 `failed`），否则 §5.4 第 5 步是一个写了但无法安全执行的路径。

---

## 3. 被设计文档或代码证伪的细节（附精确修正）

### 3.1 「schema.sql 有 22 张表」→ 23 张

计划 §2：实验的 `schema.sql`「有 22 张表，与设计五 `:65`–`:303` 同形」。实际：`v20/experiments/ce_native_d5/schema.sql` 有 **23** 个 `CREATE TABLE`，设计五的 SQL 块也是同样 23 张、名称与顺序一一对应；该 SQL 块的范围是 `:64`–`:309`（`:303` 只是最后一张 `v20_plan_artifacts` 的起始行）。修正：23 张，范围 `:65`–`:309`。计划 §4.1 与参考节引用的表区间 `:65`–`:266` 同样偏窄——`:266` 之后还有 `v20_events` 的索引与 transcript 各表 DDL，计划 §4.1 自己收的 `v20_transcript_turns`、`v20_transcript_activities` 就在 `:266` 之后，应改 `:65`–`:309`。

### 3.2 `v20_events` 的 session_id 索引在设计五 `:277`，不是 `:266`

计划 §4.1：「`v20_events` 仍建设计五 `:266` 那个 `session_id` 索引。」`:266` 是 `CREATE TABLE v20_events (`；索引 `CREATE INDEX v20_events_session_id_idx` 在 `:277`。

### 3.3 句柄规则在设计五 `:325`，不是 `:323`（仅订正引用，规则本身不重开）

设计五 `:323` 是幂等性的引入句；「只有 `start`、`claim_resume`、`steer`、`respond` 进入句柄等待……`admit_turn` 和 `admit_tool` 设 `expects_handle = false`」在 `:325` 中部。计划的规则陈述与设计五一致，行号应改 `:325`。

### 3.4 「设计五 `:531` 允许按刀实现 / 不要求每刀一次提交」的出处落空

设计五 `:531` 只是 `## 8. 实现顺序` 的标题行。「前一刀没绿，不开始下一刀」在 `:533`；四刀清单在 `:535`–`:538`；§8 全文没有任何关于提交（commit）的句子。「不按刀提交」的真实依据是 `AGENTS.md:16`（一个里程碑一次提交）与章程 `:996`（不按概念扩张 stage）——计划 §3 同时引了这两条，删掉对 `:531` 的虚假归因即可，结论不变。

### 3.5 章程 `:19` 不是「决策 1」

计划 §2 与参考节：「章程 `:19`、决策 1：不扩展 v13 stage 目录……」。章程 `:19` 是「v20 保留 v13 的 agent core」项目符号列表里的一行（`- session/run、event、effect/tool invocation；`）。该内容的散文形式在 `:33`；编号的「决策 1」（`1. v20 独立于 v13，不做 v13 stage 45。`）在 `:1192`（§13）。

### 3.6 章程 `:100`–`:104` 的 disposition 闭集漏了 `failed`

五个值实际在 `:101`–`:105`（`:100` 是代码栅栏行），引用区间恰好漏掉 `failed`。改 `:100`–`:106` 或 `:101`–`:105`。

### 3.7 章程 `:265`–`:279` 的事务边界区间截断了禁止清单

T1→IO→T2→NOTIFY 的切割在 `:270`–`:273` 没问题，但「事务持有期间禁止调工具/调 provider/等待 Host/Tool plugin 直接 COMMIT」的禁止块实际到 `:283`；引到 `:279` 截止在禁止块中间。改 `:265`–`:283`。

### 3.8 计划对 Oracle 引用的「修正」有一条方向反了

计划 §3：「Oracle 引用的章程 `:1009`、`:1111` 和 `AGENTS.md:15` 各偏一行，正文改按上面核对过的行号。」逐条核对结果：

- `:1009` → `:996`：**修正成立**。`:1009` 是 `### 10.2 不冻结集成接缝` 标题；「不按概念无限追加 stage」在 `:996`。
- `AGENTS.md:15` → `:16`：**修正成立**。「一个里程碑一次提交」在 `:16`。
- `:1111` → `:1112`：**修正错误，是 Oracle 对、计划改错了**。`:1111` 正是 `### M3：WorkspaceContext + Investigation Surface` 标题行；`:1112` 是空行。计划 §3（「章程 `:1112` 把 WorkspaceContext 放在 M3」）应回退为 `:1111`。

### 3.9 `BRIEF.md` 只有 21 行；`:119`–`:120` 的归属要消歧

计划权威顺序第 5 条：「`report.json` 的 `missing` 与 `extra` 为空（该文约 `:119`–`:120`）」。`v20/experiments/ce_native_d5/BRIEF.md` 全文 21 行；`report.json:119`–`:120` 确实就是 `"missing": []` 与 `"extra": []`。若「该文」指 `report.json` 则内容正确，但上一条与下一条引的都是 `BRIEF.md`，读起来像指 `BRIEF.md`。把「该文」改成「`report.json`」即可。`BRIEF.md:1`–`:21` 与 `:5`–`:6`（`ce_facades_r2` 换 `run_id`）的引用本身核对无误。

### 3.10 `v23/setup_db.py:19`–`:27` 各偏一到数行

计划 §9 两处引用。实际：`local_dsn` 定义与 Unix socket 断言在 `:20`–`:28`（`:19` 是空行）；DROP/CREATE 在 `:105`–`:106`；「worker 角色不能连接」探针在 `:90`–`:96`（`_probe_permissions` 内）。形状描述本身与代码一致，只是行号需改。

### 3.11 计划与实验的 turn 结算顺序相反，且未给理由

计划裁定 6 说实验「可以当对照」。对照结果（见 1.1）：实验是 accept→admit，计划是 admit→（永不 accept）。计划没有说明为什么偏离已跑通的形状。按 1.1 的修正对齐实验顺序后，此条消解；若坚持计划现序，则需要在计划里说明第一控制 turn 的结算点在哪。

---

## 4. 计划未覆盖且阻塞本切片的事项

### 4.1 gate 连接角色与 setup 角色的分工

计划 §9 规定角色 `v20_alpha_control`（LOGIN，无 DELETE）与 `v20_alpha_worker`（NOLOGIN，无 CONNECT），但未写 gate 自己用哪个身份跑：建库、建表、授权必须是 owner/超级用户连接，动词探针必须走 `v20_alpha_control` 连接（否则「写权限靠角色」这条从未被证明），`worker_role_cannot_connect` 需要第三次以 worker 身份尝试连接。v23 的 `_probe_permissions`（`v23/setup_db.py:31`–`:96`）已有这个三段式，计划只说「做法对齐」，但没把「探针必须用受限角色连接」写成要求。写进 §9 或 §11 一句话即可。

### 4.2 `recover_owner` 的 liveness 依赖（见 2.2）

`pg_stat_activity` 的权限问题是真实的部署依赖：如果受限角色看不到其他后端，`recover_owner_alive_pid_rejected` 与 `recover_owner_expires_run` 两个探针都无法实现。这必须在 W0（角色与 schema）阶段就验证，不能留到 W4。

### 4.3 `claim_resume` 前置状态闭集（见 2.3）

`resume_after_cancel_publishes` 是第 11 节已列探针，其前置条件在 §6.2 无定义，属于「探针已承诺、语义未写」的硬缺口。

### 4.4 取消与在途 FakeWorker 的所有权

§6.3/§6.4 覆盖了 cancel 与迟到 T2 的提交侧交互，但没写 Host 侧责任：`cancel` 提交时 Host 正在事务外跑 FakeWorker，回执回来后 `accept_turn_receipt` 吃 `FenceRejected`，Host 应把它当作正常终止（返回 `stop`/`failed`）还是向上抛？`Host.drive` 的单线程守卫与 `cancel` 由另一连接发起的关系也没写（`drive` 在进行中时，`cancel` 是否允许、是否会与 `drive` 的下一笔 T1 竞争 run 锁——锁顺序 1.2 已含 run 锁，行为可推，但计划应明说）。不写这条，`cancel_then_late_t2_archives_only` 的 Host 侧断言没有依据。

---

## 5. 回答后会改变设计或实现顺序的问题

1. **第一控制 turn 的结算点**（同 1.1）：采用实验的 accept→admit 顺序，还是给 start turn 另设结算点？这决定 §5.4 第 4 步、§6.1 全链、以及 `response_activity_on_t2` / `two_turns_one_transcript_turn` 三个探针的写法，应在 W2 之前定死。
2. **`claim_resume` 的可恢复状态闭集**（同 2.3）：`cancelled`、`completed`、`failed` 是否可恢复？答案直接改变 §6.2 的规则文本和 `resume_after_cancel_publishes` 的预期，并影响 `cancel` 是否真的要「不改 `resumable`」。
3. **`depends_on_request_id` 是否把 `archived`/`closed` 的 operation 算进「最近一条」**：`recover_owner` 把 pending operation 改为 `archived` 后，`claim_resume` 按 §5.1 取「同一 session、`attempt_seq` 更小、`expects_handle = true` 的最近一条」——若这条刚被 `archived` 且句柄被置 `absent`，`resolve_handle` 会落到更早的 `present` 句柄或空句柄。两种解释（计入/不计入）都讲得通，但给出的恢复后起始句柄不同，属于应在 W5 之前从设计五 `:325` 一带确认、或明示为 alpha 自定行为的问题。

---

## 附：已核对无误、不应因本评审删改的内容

- v23 常量块（`v23/worker.py:12`–`:18`）与 `storage_safe_json`（`:72`）；`WorkerRequest`/`TurnReceipt` 字段清单及 alpha 两个可空字段的增量性。
- `v13/loop_driver/driver.py:17`–`:19`（IO 在事务外）与 `:429`–`:434`（`take_exit` 的 provider 分支丢弃 advance 结果词，反例成立）；`test_loop_driver.py:625`–`:628`（Fake 回调时 IDLE 断言）。
- 章程 `:3`–`:4`（未冻结）、`:236`–`:250`（§4.3 建议性最小对象，含 workflow 与 artifacts）、`:463`–`:489`（`WorkerRequest → TurnReceipt`，类名在 `:468`）、`:959`–`:990`（M1 链）、§14 待讨论问题（§14.1 = `:1206`，§14.5 = `:1210`）。
- `BRIEF.md:1`–`:21`、`:5`–`:6`；设计五 `:48`–`:58`（身份规则 5 在 `:54`）、`:119`（`run_id = session_id` CHECK）、`:336`、§7 句柄交错探针（`:483`–`:488` 等）、§8 四刀（`:533`、`:535`–`:538`）。
- `needs_input` 时 operation 标 `completed`（设计五 `:333`/`:361`，计划 §5.4 第 6 步一致）；`snapshot_seq` 在 operation 行上、重试与小 seq 语义（设计五 `:222`/`:333`）；`record_provider_handle` 不另开 operation、与 `publish_snapshot` 两种顺序均可（设计五 `:337`，计划 §5.4 第 9 步一致）。
