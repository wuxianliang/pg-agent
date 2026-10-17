# Investigation: epoch/operation 对 v13 改成 CE 式 agent_run 的启发

日期：2026-10-14。只读调查，不改产品代码。

## Summary

这句话成立的是控制身份：一个 session 对应一个稳定 run（`run_id = session_id`），epoch 序号限定当前执行资格，一次准入是一行 operation，同一未关闭 epoch 可以有多行。T2 在资格仍有效时只结算自己那一行，不关 epoch；资格失效时把该行归档，提交成功后再拒绝。关 epoch 是 steer、cancel、claim_resume 的另一条转移。这些转移应写成 PL/pgSQL。v13 的 `claimed` / `unknown`、稳定外部幂等键，以及 judge、human、harness，留在这套转移旁边。v20 alpha 证明了身份和围栏，没有证明库内转移。

## Symptoms

- v13 的耐久身份是 `sessions` 加一条 `effects` 队列（`judge` / `tool` / `llm` / `context_refresh` / `human`），循环是找出 effect 再 advance。
- CE 的控制身份是 session、epoch、`runID = sessionID`、transcript 与控制回执分开，推进靠 steer / claim resume，不是 effect 队列。
- v20 alpha 把这套身份做成了表，并用探针跑通了 epoch 围栏和 T2 归档；动词却在 Python，不是 PL/pgSQL。
- 用户要的不是再写一个 Python 控制面，而是：v13 能不能改成 CE 式 `agent_run` / `agent_manage`，由库内转移原生控制一条基础 agent loop。

## Background / Prior Research

两边源码都在工作区：`pg-agent` 与 `repoprompt-ce`。本轮不做仓库外的 git / 网络考古。设计五已经把 CE 落盘结构翻成表（`docs/designs/v20-ce-native-design-5-2026-10-13.md`）。

## Hypotheses

1. 这句话对齐的是 CE 的 session/epoch 身份，不是 CE 的工具登记或 WorkspaceContext。它能启发「`agent_run` 只做 T1、事务外 IO、T2」，转移留在 PL/pgSQL。
2. v20 已经允许同一 epoch 里多行 operation（`admit_turn` 与 `admit_tool`）。「不要 effect 队列」不等于「一个 epoch 只能有一行」。v13 的并行工具可能仍要多行，但身份不再是 effect。
3. T2 结算或归档解决迟到回执，解决不了 v13 的 `claimed` / `unknown`（IO 中途崩溃）。启发里必须把这两件事分开。
4. 把 v13 的 `v13_advance` / `v13_complete` 整机换成这句话，会丢掉 judge、human、workflow resolve 这些 effect 种类。基础 loop 只需要其中一小部分。
5. Python 控制面（v20 alpha 的 `control.py`）不是这句话要带回 v13 的东西。

## Investigator Findings

只读核对，2026-10-14。五条探针的行号都用本人再读过一遍。产品代码未改。

### 1. v13 steer 只追加 `steer/injected`

- **Claim:** `v13_agentctl_steer` 只追加 steer/injected，没有 epoch 关闭，也没有下一次准入。
- **Verdict:** qualified
- **Evidence:** 函数体 `v13/agentctl_verbs/v13_agentctl_verbs.sql:61-137`。唯一业务写是 `:129` 的 `v13_append_event(v_target, v_event, 'steer/injected', v_payload)`。调用者锁的是 `sessions` 行（`:107-111`），身份是 session，函数里没有 epoch、effect 入队或 advance。`v13_append_event`（`v13/schema/v13_core.sql:68-83`）会把目标会话的 `next_seq` 加一；`steer/injected` 不是 `user/message`，所以 `turn_no` 和 `status` 不变。写进去的是 `events`，不是 `effects`。
- **Consequence:** 基础 loop 若仍用这个 steer，库里只多一条已记录事件；要让 `agent_run` 原生推进，steer 得自己关闭当前 epoch 并写下一条准入。

### 2. 一个 epoch 可以同时装下 start、admit_turn、admit_tool

- **Claim:** 一次准入是一行 operation；同一 epoch 可以同时有 start、admit_turn、admit_tool。`accept_tool_result` 之后 run 仍在跑。
- **Verdict:** confirmed（「一个 epoch 只能有一行」这种读法被证伪）
- **Evidence:** `v20/alpha/schema.sql:96-112` 的 `v20_operations.epoch_id` 只是可空外键，没有按 epoch 唯一。动词检查同时允许 `start`、`admit_turn`、`admit_tool`（`:98-99`）。epoch 唯一的是 `(session_id, ordinal)`（`:93`）。start 在新 epoch 上插一行 `start`（`v20/alpha/control.py:562-574`）。同一 `epoch_id` 再插 `admit_turn`（`:868-872`，主机侧 `v20/alpha/host.py:132-144`）和 `admit_tool`（`control.py:966-970`，`host.py:249-258`）。每次准入一次 `_insert_op`（`:311-322`）。`_v_accept_tool_result`（`:990-1033`）只把该 operation 和 tool invocation 标成完成；函数里没有 `UPDATE v20_runs`。能进入结算的前提是 run 已经在 `running` 或 `waiting_for_input`（`:35`、`:1010`）。
- **Consequence:** 基础 loop 把「一次准入一行」当成行规约；同一个未关闭 epoch 里可以有多行工具准入。v13 的单活跃 effect 索引（`v13/schema/v13_core.sql:128-129`）装不下这种并行。

### 3. `claimed` / `unknown` 与 T2 归档不是同一类失败

- **Claim:** fence / `origin_user_seq` 与 claimed/unknown 是一类；T2 要么结算当前 epoch，要么归档。两者不能并成一件事。
- **Verdict:** qualified。失败类不同：confirmed。「T2 结算的是当前 epoch」：qualified。
- **Evidence:** `effects.status` 含 `ready/claimed/succeeded/failed/unknown/cancelled`（`v13/schema/v13_core.sql:112-113`）。`claimed` 是租约中的活跃行，进入单活跃索引（`:128-129`），claim 时 `fence` 加一（`:269-272`）。`unknown` 是墙：入队遇到它直接 RAISE（`:246-247`）；lease 耗尽时 judge 走可结算的 `failed`，其余 kind 走 `unknown` 且不自动重放（`v13/twophase/v13_twophase.sql:20-24`、`:57-61`）。`origin_user_seq` 是创建时的迟到完成锚点（`v13_core.sql:105-108`）。`v13/twophase/README.md:14` 只写运维口径，不定义这些词。v20 的匹配结算完成的是当前 operation：回执在 epoch 仍当前、行仍 pending、run 仍可跑时把该行标成 `completed`（`control.py:914-930`、`:1010-1022`），不关 epoch。不匹配则 `_fence` 把 pending 行改成 `archived`、写事件、提交、再拒绝（`:456-466`、`:1010-1011`）。关 epoch 是另一条路：steer / claim_resume 走 `_open_follow`，先 `_close_epoch` 再把旧 pending 改成 `closed`（`:591-592`、`:631-649`）。`request_id` 不符时只追一条 archive 事件并原样返回，行仍是 pending（`:1002-1006`）。
- **Consequence:** 基础 loop 用 epoch 序号决定这一行是完成还是归档；`claimed` 租约和 `unknown` 墙仍要单独留给已经发出去的外部 IO。

### 4. CE 的 loop 控制与会话管理是两套 op

- **Claim:** `agent_run` 的 start/poll/wait/cancel/steer/respond 是 loop 控制；`agent_manage` 是会话管理。一个 session 对应一个 run，epoch 往前走。
- **Verdict:** qualified
- **Evidence:** `AgentRunMCPToolService.swift:417-441` 把六个 op 分到 start、wait（poll 强制不阻塞）、cancel、steer、respond。start 拒绝调用方传入的 `session_id`，总是新开会话（`:455-457`）。`AgentManageMCPToolService.swift:194-222` 是目录、日志、交接、建会话、恢复、停止、清理、置顶。`stop_session` 在会话仍活跃时取消当前 run（`:1138-1141`）。无头启动把 `runID` 设成 `sessionID`（`DirectHeadlessProviderCoordinator.swift:206-207`）并 `beginEpoch`（`:211`）。epoch 仍挂在同一 `sessionID` 上，`ordinal` 取 `nextEpochOrdinal` 再递增（`DomainAgentRunSessionStore.swift:373-398`）。v20 用表把这个别名写死：`session_id` 唯一，`run_id = session_id`（`v20/alpha/schema.sql:67-79`）；steer 不新建 run，只把 epoch 序号加一（`control.py:596-614`、`:648-649`）。
- **Consequence:** 基础 loop 的库内转移对齐那六个 `agent_run` op：session 与 run 同一个耐久 id，epoch 序号单调前进。建会话、恢复、清理、目录和置顶留在 loop 外。

### 5. v20 没有 PL/pgSQL；归档先提交再拒绝

- **Claim:** 写这些转移的仍应是 PL/pgSQL。v20 alpha 的 schema 零 `CREATE FUNCTION`。`_fence` 先提交归档再抛错，而 PL/pgSQL 的 RAISE 会把同一事务回滚。
- **Verdict:** qualified。零函数：confirmed。先提交再拒绝：confirmed。「仍应是 PL/pgSQL」是目标，不是 v20 已经做到的事。
- **Evidence:** `v20/alpha/schema.sql` 全文 189 行，无 `CREATE FUNCTION` / `LANGUAGE plpgsql`。文件头的 `DO $$`（`:4-13`）只建角色。全部转移在 Python。`_fence`（`control.py:456-466`）先 `commit()`，再给错误打上 `committed = True`，然后 raise。`_tx` 只在 `committed` 为假时 rollback（`:114-123`），所以归档留下。函数体内的 RAISE 会中止调用方事务，同一函数里刚做的 `UPDATE … status = 'archived'` 会一起消失。
- **Consequence:** 转移仍写成库内过程；围栏归档必须先成为已提交的行，拒绝另行报出。一个函数里「改成 archived 再 RAISE」保不住这条归档。

### 6. 这句话对 v13 基础 loop 教什么

耐久身份从「session 拥有一条 effect 队列」改成「session 与 run 同一 id，epoch 序号是围栏，一次准入一行 operation」。原生能控制基础 loop 的，是 `agent_run` 那六个 op 在库里的转移；工具回执在 epoch 仍当前时完成该行并让 run 继续，epoch 已换则把该行归档并先提交。`effects.kind` 仍是 `judge/tool/llm/context_refresh/human`（`v13_core.sql:99-100`）。这句话覆盖的基础 loop 只覆盖对话推进和工具准入；judge、human、context_refresh 仍留在这套转移之外。

## Investigation Log

### Phase 1 - 分诊
**Hypothesis:** 问题是架构映射，不是一次回归。证据在 v13 核心表、v20 alpha 的准入/围栏、设计五对 CE 的翻译，以及 CE 的 `agent_run` / `agent_manage` 入口。
**Findings:** 报告已建。下一步交给 context builder，再交给 pair。
**Evidence:** `v13/schema/v13_core.sql` 的 `sessions` 与 `effects`；`docs/designs/v20-ce-native-design-5-2026-10-13.md` 第 1–2 节；`v20/alpha/schema.sql` 无函数。
**Conclusion:** 进入 Phase 2。

### Phase 2 - context builder
**Hypothesis:** 相关面是 v13 的 effect 队列与 steer、v20 alpha 的 operation/epoch、CE 的 `agent_run` / `agent_manage`。
**Findings:** 选择集覆盖设计五、章程切片、v13 核心与 `v13_advance`、alpha 的 schema/control/host，以及 CE 的 session store 与两个 MCP service。Oracle 对话 `v13-ce-control-investiga-A4B4F3` 给出初稿。初稿未写入本文件。
**Evidence:** 选择集中的上述文件。
**Conclusion:** 进入 Phase 3，由 pair 按行核对五条探针。

### Phase 3 - pair 核对
**Hypothesis:** 见上文 Hypotheses 1–5。
**Findings:** pair 写入 `## Investigator Findings`。五条探针的结论是 qualified 或 confirmed，没有一条被整句推翻。产品代码未改。
**Evidence:** 本文件 Findings 第 1–6 节。
**Conclusion:** 进入抽查与合成。Findings 原文保留。

### Phase 4 - 抽查与 oracle 合成
**Hypothesis:** Findings 的行号可以直接写进结论。
**Findings:** 语义成立。三处行号要改用抽查结果：`RUNNABLE` 在 `v20/alpha/control.py:34`（Findings 写了 `:35`）；无头 `beginEpoch` 调用在 `DirectHeadlessProviderCoordinator.swift:222`（Findings 写了 `:211`，`:206-207` 的 `runID = sessionID` 无误）；`stop_session` 取消活跃 run 在 `AgentManageMCPToolService.swift:1143-1146`（Findings 的 `:1138-1141` 是停前的目标检查）。选择集补了 `v13/twophase/v13_twophase.sql:1-70`、`agent_run.start` 拒绝外来 `session_id` 的 `:445-464`、`stop_session` 的 `:1125-1150`。Oracle 在同一对话里把原话收成一条规约。
**Evidence:** 本轮对 Findings 所引区间的直接阅读。
**Conclusion:** 可以写 Root Cause。

## Root Cause

原话要改的是 v13 的控制身份，不是把 `effects` 换个表名。今天 v13 的耐久工作单元是 session 上的一条 effect 队列：种类固定为 `judge` / `tool` / `llm` / `context_refresh` / `human`（`v13/schema/v13_core.sql:99-100`），同一 session 至多一个 `ready` 或 `claimed` 行（`:128-129`）。循环是领出这个 effect 再 `v13_advance`。CE 无头路径把 `runID` 设成 `sessionID`（`DirectHeadlessProviderCoordinator.swift:206-207`），在同一 session 上 `beginEpoch`（`:222`），epoch 的 `ordinal` 取 `nextEpochOrdinal` 再递增（`DomainAgentRunSessionStore.swift:373-384`）。v20 alpha 把这个别名写成表约束 `run_id = session_id`（`v20/alpha/schema.sql:67-79`）。

能指导 v13 基础 loop 的规约是：

> 以 `session_id = run_id` 为稳定控制身份，以当前 epoch 和 run 的 owner generation 限定执行资格。PL/pgSQL 原子执行准入、切换与关闭。每笔新准入按 `request_id` 固化输入、epoch 和 owner。T1 提交后才做事务外 IO。T2 核验请求关联与执行资格，只结算自己的 operation，或把不能接受的回执持久记下且不覆盖当前快照。局部 turn 或 tool 完成不得自动终结 run。

### 原话里要改写的三处

**一次准入是一行，一个 epoch 可以有多行。** `v20_operations.epoch_id` 只是可空外键，没有按 epoch 唯一（`schema.sql:96-112`）。epoch 唯一的是 `(session_id, ordinal)`（`:93`）。start 在新 epoch 上插入 `start`（`control.py:562-574`）。同一 `epoch_id` 再插入 `admit_turn`（`:868-872`，主机 `host.py:132-144`）和多行 `admit_tool`（`control.py:966-970`，`host.py:249-258`）。每次准入一次 `_insert_op`（`:311-322`）。v13 的单活跃索引装不下这种并行。

**T2 结算的是当前 operation，不是当前 epoch。** 匹配且行仍为 `pending`、run 仍在 `RUNNABLE`（`control.py:34`，即 `running` / `waiting_for_input`）时，accept 把该 operation 标成 `completed`（turn：`:924-930`；tool：`:1015-1022`）。`accept_tool_result`（`:990-1033`）没有 `UPDATE v20_runs`。关 epoch 是另一条路：`_open_follow` 先 `_close_epoch`，再把旧 pending 改成 `closed`，然后 ordinal 加一（`:591-596`）。steer 与 claim_resume 走这条路（`:648-649`、`:672-673`），不新建 run。`respond` 把新 operation 插进当前 epoch，把 run 从 `waiting_for_input` 改回 `running`，不推进 ordinal（`:686-705`）。`cancel` 在 run 仍可跑时把 status 改成 `cancelled`，关闭 epoch，pending 改成 `closed`，不改 run id，也不把 session 标成不可恢复（`:726-739`）。`RESUME_OK` 等于 `TERMINAL_RUN`，其中含 `cancelled`（`:35-36`），之后的恢复仍走 `_open_follow`。

**资格失效的归档，和 `request_id` 错配，也不是同一条写。** owner 或 epoch 对不上、且行仍 pending 时，`_fence` 把该行改成 `archived`，写事件，先 `commit()`，再抛 `FenceRejected` 并标 `committed = True`（`:456-466`）。`_tx` 只在 `committed` 为假时 rollback（`:114-123`）。行已经不是 pending 时，`_fence` 不改 status，只追加归档事件。`request_id` 不符时只追加一条 archive 事件并返回，行保持 pending（turn：`:907-910`；tool：`:1002-1006`）。steer 关掉的旧行是 `closed`，迟到回执不能把它们改成 `archived`。

### 必须留在旁边的 v13 机制

epoch 归档回答的是「这个回执还能不能写进当前执行」。`claimed` 回答的是「谁拿走了执行资格」：claim 把行改成 `claimed` 并把 `fence` 加一（`v13_core.sql:269-272`）。`unknown` 回答的是「外部副作用可能已经发生，不能盲重放」：重挂遇到 `unknown` 直接 RAISE（`:246-247`）；lease 耗尽时 judge 在 cap 内回到 `ready`，超 cap 变成可结算的 `failed`，其余 kind 变成 `unknown`（`v13/twophase/v13_twophase.sql:20-24`、`:39-61`）。重挂不换 `idempotency_key`（`v13_core.sql:260-262`）。新的 `request_id` 表示一次新的耐久准入；它不能单独成为更换外部幂等键的理由。结果未知时先走核对或 `unknown`，不能靠换 ID 再执行一次。

`v13_agentctl_steer` 的唯一业务写是 `v13_append_event(..., 'steer/injected', ...)`（`v13/agentctl_verbs/v13_agentctl_verbs.sql:129`）。该类型不是 `user/message`，所以 `turn_no` 和 `status` 不变（`v13_core.sql:72-81`），也不入 `effects`。库里多一条事件，不等于下一次 provider 调用已经换了输入。

基础 loop 到此为止：入口 T1 提交，事务外取得 provider handle，`admit_turn` → Worker → `accept_turn_receipt`，有工具则 `admit_tool` → Tool → `accept_tool_result`，工具结果进入下一次 turn，再由快照发布写下 run 的状态。成功终点是最终回执已接受且入口快照已提交。`needs_input` 停在 `waiting_for_input`，由 `respond` 续上。judge、context_refresh、human 亲缘与授权、harness 的 approval / evidence / quota、plan、workflow、spawn，仍由活体 `v13_advance` / `v13_complete` 承担（`v13/plan_arm/v13_plan_arm.sql` 的活体函数，`v13/acl/v13_acl.sql` 的 human 校验，`v13/control/v13_control.sql` 的 harness `result_kind`）。本调查没有把这些读成基础 loop 的一部分。

### 已排除的读法

- 「一个 epoch 只能有一行 operation。」`schema.sql:96-112` 与同一 epoch 上的 start / admit_turn / admit_tool 排除了它。
- 「T2 结算当前 epoch。」匹配 T2 完成的是 operation；关 epoch 的是 `_open_follow` 和 cancel。
- 「`claimed` / `unknown` 可以并进 T2 归档。」二者回答的失败不同。归档表示失去对当前 epoch 的发布权；`unknown` 表示外部副作用未知。
- 「用这句话替换整个 `v13_advance` / `v13_complete`。」那两个函数还承载 judge、human、harness、plan 与 spawn。
- 「把 `control.py` 搬回 v13 就完成了 PL/pgSQL。」`schema.sql:4-13` 的 `DO $$` 只建角色，全文没有 `CREATE FUNCTION`。`_fence` 的先提交再拒绝是要保留的可观察结果；函数体内 `UPDATE` 成 `archived` 再 `RAISE` 会把归档一起回滚。

## Recommendations

1. 若改 v13，新增一组 PL/pgSQL 转移，对应 `agent_run` 的六个 op，而不是改 `v13_agentctl_steer` 的事件类型。`start` 创建新 session、同 id 的 run、initial epoch 和入口 operation，并拒绝调用方传入的 `session_id`（CE 侧现行为 `AgentRunMCPToolService.swift:455-457`）。`steer` 在 CAS 成功后原子关闭旧 epoch、把旧 pending 改成 `closed`、ordinal 加一、写下一条入口 operation（对照 `control.py:589-649`）。`respond` 在原 epoch 插入回答 operation（对照 `:675-718`）。`cancel` 关闭当前 epoch 并把 pending 改成 `closed`，不更换 run id（对照 `:720-739`）。`poll` / `wait` 只读已提交快照。
2. `agent_manage` 保持在 loop 外：目录、日志、交接、建会话、恢复、停止、清理、置顶。`resume_session` 调用与 `claim_resume` 相同的库内转移（对照 `control.py:651-673`）。`stop_session` 在会话仍活跃时取消当前 run（`AgentManageMCPToolService.swift:1143-1146`），保留自己的目标检查，不把名字收成 `agent_run.cancel`。
3. 内部 admit / accept 与快照发布是库内合同，不增加 MCP op。工具回执只完成自己的 operation。run 状态由快照发布改写。不要把 alpha 的「同一 expects_handle 上第二轮工具即失败」（`host.py:240-241`）写成基础 loop 的规则。
4. 围栏拒绝的 PL/pgSQL 函数正常返回结构化结果（目标行已是 `archived` 或保持 `closed`，并已追加归档事件）。调用方 `COMMIT` 成功之后，再映射成协议拒绝。不要在同一函数里 `UPDATE` 成 `archived` 再 `RAISE`。不要把 `Control.execute` 套一层 SQL 名字后搬回来。
5. 恢复时的新 operation 使用新 `request_id`。同一逻辑副作用的外部 `idempotency_key` 保持稳定，沿用 `v13_core.sql:260-262` 的重挂不换键。两套身份都留下。
6. 执行领取、租约耗尽、`unknown` 墙留在 epoch 归档旁边，语义沿用 `v13_requeue_stale`（`v13/twophase/v13_twophase.sql:39-61`）。judge 可按 cap 重放；tool / llm / human / context_refresh 的失联 claim 进入 `unknown`。archived 不表示「未执行」或「可以再跑」。
7. 单活跃 effect 索引（`v13_core.sql:128-129`）不能作为基础 loop 的并行约束。同一 epoch 的多行工具 operation 要能各自结算。
8. 这一步不搬设计五的 workflow、artifact、plan 表，不搬 alpha 的 13 张表和 Python 动词正文，也不把 `owner_backend_pid` 的存活检查（`control.py:666-668`）当成完整的跨进程所有权合同。Python 留在 T1 提交之后，做 provider 与工具 IO。

## Preventive Measures

- 声称「库内转移已经原生控制基础 loop」之前，分层记录覆盖：状态模型、已安装函数的 language / owner / EXECUTE、表 GRANT（Host 不能直接 `UPDATE` 控制状态）、假 Worker 链、真实执行。alpha 的 62 条探针只覆盖第一层里的身份和围栏。
- steer 的通过条件是 Worker 读到的下一次输入已经换成新正文。观察到一条 `steer/injected` 不算通过。
- 同时测两个顺序：T1 已提交而 T2 未到；T2 已开始而 steer 或 cancel 先提交。迟到回执不得覆盖新快照。`closed` 行不得被改回 `archived`。`request_id` 错配不得改掉仍 pending 的目标行。
- 围栏用例在断言协议拒绝之前，先确认归档行已经对另一个连接可见。函数返回之后、调用方提交之前，不得对外声称归档已耐久。
- 把崩溃分成三档分别做探针：IO 之前崩溃（pending 仍在，可按规则重试）、副作用已经发生而 T2 未提交（走租约与 `unknown`，不靠归档假装没发生）、T2 已提交而响应丢失（重放返回已有结果，不再做 IO）。
- 同一 epoch 内两笔工具各自结算，第一笔完成不阻塞第二笔，任一笔成功都不把 run 标成 `completed`。
- 新 operation 的 `request_id` 变了，外部幂等键仍与被重试的逻辑动作相同。结果未知时，换 `request_id` 不能绕过 `unknown`。
- 报告里把基础 loop 和仍留在 `v13_advance` 的 judge、human、harness、plan、spawn 分开写。未实现的职责保持未实现。
