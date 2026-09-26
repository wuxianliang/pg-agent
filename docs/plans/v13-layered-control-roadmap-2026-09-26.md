# v13 分层控制路线图（2026-09-26）

> 状态：计划。本轮零 SQL、不改其他文件、不改 `docs/plans/v13-control-parity-tests-plan-2026-09-26.md`。
> 论点（固定）：**v13 = 基础循环（stage 1–20 已交付）；RP-CE = 时–日工作流的范例；LoopX = 工作流之上的天–周治理范例。** 这不是移植项目。
> 尺子（固定，谱系文 §3）：状态唯一家（PG 行）、唯一推进函数（parse+advance）、唯一干预通道（events INSERT）、唯一结算点（complete/closeout）、高层语义全是数据投影。不建第二运行时、不建 `v13_agent_run`。
> 对齐分层：RP-CE **动词级**（控制动词必须在，保证等价，机制可换体）；LoopX **性质级**（结算完备、资格≠奖励、不丢运行、不超售——不搬表）。
> 事实源：parity 裁决 `docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md`；卷宗 `prompt-exports/parity-{rpce,loopx,v13}-2026-09-26.md`；谱系文 `docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md`；迁移 `docs/analysis/v13-control-plane-migration-2026-09-25.md` §0/§2；R2 §1–§3；R3/R3a/R3b/R3c。已裁不重开。冲突只进 §4。

## 0. 执行摘要

```
L2 治理（天–周）  LoopX 是范例，不提供会话内动词     性质级：门、资格、停复、注意力
L1 工作流（时–日） RP-CE 是范例，不提供长期治理       动词级：观察/注入/应答/取消 + 授权/交接
L0 循环（秒–分）   stage 1–16 冻结；17–20 已落子集    唯一推进函数，本路线图不重开
```

一句话：71 条里 **29 条保持已裁换体、29 条永不建、13 条补齐**。补齐全部落在既有函数/事件/投影/策略行上，默认零新表。进程机、文件六层、第二账本不追。

| 层 | 条数 | 补齐 | 保持改变 | 永不建 |
|---|---:|---:|---:|---:|
| L1 RP-CE F1–F30 | 30 | 5 | 16 | 9 |
| L2 LoopX L1–L41 | 41 | 8 | 13 | 20 |
| 合计 | 71 | 13 | 29 | 29 |

三桶读法：

- **已裁换体、不必追失败模式**：F1–F3/F6/F7/F9–F15/F22/F27/F28 与 L8–L12/L14/L15/L18/L31/L33–L35/L37。核心动词或性质已在，形状不同是裁决不是欠账。
- **语义缺口要补**（13）：L1 = F8 多目标观察、F17 授权、F18 授权后读日志、F23 release 写入者、F29 handoff 信封。L2 = L5 注意力投影、L6 窗口资格（禁 `quota/spent|voided`）、L21 调度提示、L26 should-run、L27 handoff 政策门、L29 委托可见性、L32 停/复、L38 能力门。
- **永远不建**：迁移 §0 点名的新表/新列/`v13_agent_run`/`quota_spends`/`command_receipts`/`outbox`/`leases`、把 `decisions.epoch` 当 run generation；加上进程生命周期（F5/F16/F24–F26）、墓碑删除（F19）、grant 经纪人（F20/F21）、oversight link（F30）、LoopX 文件面与相位机（L1–L4/L7/L13/L16/L17/L19/L20/L22–L25/L28/L30/L36/L39–L41）。

重点条目里，F16/F24/F25 **不补函数**：崩溃不丢运行已由墙 + `v13_resolve_unknown` + 租约 + 新 `effect_id` 持有（F28/L33 保持改变）。再造冷恢复或 session claim = 第二套活性。

## 1. 分层模型

| 层 | 尺度 | 范例边界 | v13 现状 | 本路线图 |
|---|---|---|---|---|
| L0 | 秒–分 | Codex 管 turn。完备性已判闭合，不重开 | stage 1–16：effect/event/claim/complete/两阶段墙 | 冻结。只许后 stage `CREATE OR REPLACE` |
| L1 | 时–日 | RP-CE 管会话与委托。**不提供**资格账本、should-run、停复、注意力 | stage 17–20 已落单会话动词 + spawn + cancel 扇出 + triage 子集 | 补工作流动词。不把 RP-CE 进程机搬进来 |
| L2 | 天–周 | LoopX 管 goal 活过任何一次执行。**不提供** steer/respond/interrupt | 结算三次事务已在；治理投影几乎未写（L26 落点未写） | 投影优先。最少新结构；新表/新列只经 §4 |

层间只传递有界工作段，上层对下层只用观察/注入/应答/取消的变体（谱系文 §2）。L1 的「授权/交接」是这四动词的准入与出口，不是第五个推进函数。L2 的 should-run 是 advance **入队前读的投影**，不是节拍器，也不是 `v13_agent_run`。

RP-CE 五原语没有一个缺机制（谱系文 §4）：start=开会话或新 effect，steer=事件，interrupt=cancel，respond=human complete，shutdown=租约回收。缺的是操作者在**多会话**上调用这些动词时的准入（F17）和交接物形状（F29）。

LoopX 六层文件不是施工图（迁移 §3 整包不迁）。要保住的是性质：结算完备（已有）、资格与奖励分离（L37 已裁，窗口表达未写）、不丢运行（墙已有）、不超售（`spawn_budget` 已有）。

## 2. 缺口分诊

一条一个桶。依据必须是 R2 §1–§3、R3 链，或迁移 §2/§0。parity「改变/没实现」不等于本表的桶：没实现里有「明确不做」，改变里有未写完的写入者（F23）。

落点只用四类：函数、事件（开放 type，零 DDL）、投影（STABLE，零写入）、策略行（`v13_policies` / `thresholds`，不新表）。

### 2.1 L1 · RP-CE（动词级）

| ID | 判 | 落点 | 依据 |
|---|---|---|---|
| F1 | 保持改变 | 已有 `v13_open_session`；续跑=同会话新 effect。不建进程幂等返回 | 迁移 §2.1；R3 §1 附 |
| F2 | 保持改变 | 干预=`steer/injected` + 步 0 七键 `stale`。正文生产者按 R3b 不做；指令走已有 `user/message` | R1.9；迁移 §2.1；R3b §7.3 |
| F3 | 保持改变 | 动词=`v13_cancel`。四值 ACK 不建。第四务见 Phase A R4，不是新动词 | R2 A18；R3c §8.7 |
| F4 | 保持改变 | 维持 C4 RAISE。静默 no-op 不移植。Phase A 只补台账一行 | R3 C4；parity §4 #2；§4 D13 |
| F5 | 永不建 | 无 `v13_shutdown`。停=cancel + 租约过期 | 迁移 §2.1；§0 不建 dormant |
| F6 | 保持改变 | 同 F1。`detach`/超时不进事件 | 迁移 §2.2；R3 §1 附 |
| F7 | 保持改变 | 观察=读行 + `v13_recover_idle`。不建 poll/wait | 迁移 §2.2；R1.7；R3c §8.4 |
| F8 | 补齐 | STABLE `v13_observe(actor, ids[])`：先 F17，任一未授权则零行。不建 waiter；「第一个胜」留驱动重入 | 迁移 §2.2 不建 waiter；缺口=全量授权前的多 id 读 |
| F9 | 保持改变 | 终态 cancel → `replay`，不改回抛错 | R3 §1；R3b 终化 |
| F10 | 保持改变 | 过期句柄不 reactivation。同会话新 effect_id | A15/R1.2；迁移 §2.4 |
| F11 | 保持改变 | ref 不等 RAISE 且含 current。种类不重开。自答拒折进 F17 | R3 C4；R2 §1.2 |
| F12 | 保持改变 | 句柄=`(session_id, effect_id, fence)`。禁把 `decisions.epoch` 当 generation | 迁移 §2.4；§0 |
| F13 | 保持改变 | fence 失配 → `stale`。无 waiter 表 | 迁移 §4 |
| F14 | 保持改变 | 印章即提交；outcome 冲突 RAISE | R2 A16；R3b §7.2 |
| F15 | 保持改变 | advance 步 0 + recover 锁内复验 | 迁移 §2.2；R3c §8.4 |
| F16 | 永不建 | 无 300s TTL，不摘行，不写 dormant。陈旧令牌=fence `stale` | 迁移 §2.4 |
| F17 | 补齐 | 谓词 `v13_control_authorized`：只读 `parent_session_id` + `current_user` 带。不加列、不建 link。接入 cancel / human complete / observe / handoff | 迁移 §2.2 不进第一期；§6 触发已到；§4 D7 |
| F18 | 补齐 | STABLE `v13_session_log`：先 F17 再读 events。不建 transcript 表；文件水合归姊妹篇 | 迁移 §2.2；R1.4 |
| F19 | 永不建 | 不删行。停=cancel | 迁移 §2.2 墓碑不迁 |
| F20 | 永不建 | 不建 grant/指纹类。执行前授权=human 两段 + allowlist | 迁移 §2.3 折叠；§0 零新表；§6 |
| F21 | 永不建 | 不建 presenter FIFO。应答=`v13_complete` | 迁移 §2.2 respond |
| F22 | 保持改变 | latch `worktree` + 三 FS effect。子不继承（与源默认相反，已裁） | R2 A19；R3c §8.7 |
| F23 | 补齐 | 热修：`worktree_release` 成功才 `v13_latch_fire(..., released)`；失败保持 `prepared` | parity §4 #8；R3c 词表有 `released` 无写入者；§4 D12 |
| F24 | 永不建 | 无冷恢复。行在即活。不把活跃行收成 idle | 迁移 §2.4 |
| F25 | 永不建 | 无 session claim、不铸 generation。排他=advance 会话锁；续跑=新 effect_id | 迁移 §2.4 无此栅栏；A15 |
| F26 | 永不建 | 同 F5。无 waiter 可摘 | 迁移 §2.1 |
| F27 | 保持改变 | 六 kind 折叠进 `wait_reason=approval`。amendment 不进 v1 | R2 §1.2；R3 D6/C4/C5 |
| F28 | 保持改变 | `v13_resolve_unknown`。不建 journal。绝不自动重执行 | 迁移 §4；R3 D5 |
| F29 | 补齐 | `v13_extract_handoff`：先 F17，写 `control/handoff`（delivery_id + transcript_hash + up_to_seq）。不产 XML，不替代 `v13_fork` | 迁移 §2.2；R1.4；谱系文 §5.1；§4 D16 |
| F30 | 永不建 | 无 link 表、无 send 账本。indeterminate 优先已吸收进墙 | 迁移 §2.2 |

L1 计数：补齐 5（F8 F17 F18 F23 F29）/ 保持改变 16 / 永不建 9。

### 2.2 L2 · LoopX（性质级）

| ID | 判 | 落点 | 依据 |
|---|---|---|---|
| L1 | 永不建 | 无 registry 表。goal=sessions；资格=策略行（够不够见 D8） | 迁移 §3；§0 |
| L2 | 永不建 | 无 `ACTIVE_GOAL_STATE` 文件。goal=sessions 行 | 迁移 §3 |
| L3 | 永不建 | 无 `runs/*.json`。events 是日志 | 迁移 §3 |
| L4 | 永不建 | 无紧凑 index 文件。公开列约束并进 L5 输出，不单建表 | 迁移 §3；R1.5 |
| L5 | 补齐 | STABLE `v13_attention(root)`：读 `v_goal_tree` + L26。`attention_rank` 只作输出列。零写入、不授权 | 迁移 §2.6；SQL 零 `attention_rank`；§4 D10 |
| L6 | 补齐 | STABLE `v13_quota_eligible`：策略行窗口 × 既有 `turn/material_spent` 重算。**不写** `quota/spent\|voided`，不做窗内冲销 | R3b 明确不做；R3c §8.7；迁移 §3；§4 D9 |
| L7 | 永不建 | 无三档 flock。崩溃释放=租约 + 事务咨询锁 | R3c 锁序；迁移 §3 |
| L8 | 保持改变 | 唯一索引 + `replay`。不建 `command_receipts` | 迁移 §3 |
| L9 | 保持改变 | 身份=`v13_effect_id`。XOR 被否；repair/replan 是事件 | R2 §1.1 |
| L10 | 保持改变 | 三次事务：complete / advance ⑤ / closeout。不合成大事务 | 迁移 §2.5 |
| L11 | 保持改变 | complete 同事务写 status + 语义事件。无状态文件 | 迁移 §2.5 |
| L12 | 保持改变 | material 收据在 advance ⑤，不在 complete | R1.11；R3a §6.4 |
| L13 | 永不建 | 无 `expected_index_digest`。幂等见 L8 | 迁移 §0 不搬 `quota_spends` |
| L14 | 保持改变 | `v13_closeout` 收据重放。不重读外部文件 | R2 A16；R3b §7.2 |
| L15 | 保持改变 | 欠账=`unconsumed` + 续传未还 RAISE。相位机不是列 | 迁移 §2.5；R3b |
| L16 | 永不建 | journal 不搬成表。三值读回已在 resolve | 迁移 §2.5 |
| L17 | 永不建 | 不搬 12 种失败闭集。用已裁 RAISE 子串 | R3b 尾词 |
| L18 | 保持改变 | request 六键；`result_kind` 四值权威；路由不读 `delivery_kind` | R2 §1.1；R3b §7.1 |
| L19 | 永不建 | 不建 lane fence、不新返回词。单活跃=已有唯一索引 + 会话锁 | 迁移 §3 证实不吸收 |
| L20 | 永不建 | 不建 11 种提示表。帽=`effect_attempt_cap`。间隔并进 L21 | 迁移 §2.6 |
| L21 | 补齐 | STABLE `v13_scheduler_hint`：只读 L26，返回 `run_now\|wait\|dont_notify`。pg_cron 调用后必须再判一次才 advance。无 RRULE、无 ack、无常驻心跳 | 迁移 §2.6；ch13 |
| L22 | 永不建 | 无 `scheduler_ack`。陈旧 hint 由步 0 水位 + L26 再判挡住 | 迁移 §2.6；R3b 不新增收据族 |
| L23 | 永不建 | 不建 `BoundedTurnBudget`。步内不 spend 已由 R1.11 持有；超限走已裁 closeout，不改成 ValueError | R3b 逃生前置 |
| L24 | 永不建 | 不建 `[15,30,60]` 相位机。停滞不自动插 `replan/required`（那是第二个推进者）；只让 L26 返回假 | 迁移 §2.6；R1.5 |
| L25 | 永不建 | 无 heartbeat 收据。收据≠执行权已由 R1.5 持有 | 迁移 §0 |
| L26 | 补齐 | STABLE `v13_should_run`，advance 入队前读；假则零新 effect。序住策略行，不建状态列，不搬七态名字 | 迁移 §2.6 **落点未写**；§4 D10 |
| L27 | 补齐 | 不建 plan/runtime/transaction 三存储。F29 读策略行 `handoff_policy` 做前置 | 迁移 §2.2；与 F29 同缺口 |
| L28 | 永不建 | head/receipt 分表不建。id 冲突已由 spawn ledger / fence 承担 | 迁移 §0/§3 |
| L29 | 补齐 | 占用到顶或策略不允许时，路由不选 spawn（键缺席，不发空对象，不加 route 键）。依赖 Phase A R6 | R3c H1；台账目录缝 ≠ parity F22 |
| L30 | 永不建 | 无 peer op。同侪中断会打穿 F17 直接父 | 无映射；与 F17 冲突则不搬 |
| L31 | 保持改变 | 有 `v13_cancel`。相对 LoopX「无中断」是已裁翻转，不改回去 | 迁移 §2.1；R2 A18 |
| L32 | 补齐 | 事件 `goal/stopped\|resumed` + 指纹=`v13_state_hash`。advance/recover 读最后一条。**不等于** `duty_cycle=0`。不加列，不删行，不替代 cancel | parity §4 #9 拒绝等同；§4 D15 |
| L33 | 保持改变 | progress+signal → 同 `logical_turn_id`、index+1。resolve 不铸新回合 | R3a §6.3；迁移 §4 |
| L34 | 保持改变 | `spawn_budget` 席位 + 咨询锁。禁止把 `turn_no` 当树预算 | R3c §8.1 |
| L35 | 保持改变 | 坏 `tool_calls` RAISE、零子。N 或 0 | R2 §2.6；R3c §8.3/§8.8 |
| L36 | 永不建 | 源侧亦无实现。席位已在 L34 | parity L36 |
| L37 | 保持改变 | `wait_reason` 三分。approval ≠ 配额。reward 生产者不另开「已实现」 | R2 §1.2；迁移 §2.6 |
| L38 | 补齐 | STABLE `v13_missing_capabilities` 纯集合差；非空则不入队。`human_reward` 仍无生产者，且不得改已判 run | 迁移 §2.6 |
| L39 | 永不建 | 不建 receipt 相位表。语义见 L8 | 迁移 §0/§3 |
| L40 | 永不建 | 不建 outbox。唤醒=`v13_recover_idle` / 驱动重入 | 迁移 §0；R1.7 |
| L41 | 永不建 | 不建租约表。`effects.fence` 已令旧令牌 `stale` | 迁移 §3 |

L2 计数：补齐 8（L5 L6 L21 L26 L27 L29 L32 L38）/ 保持改变 13 / 永不建 20。

L6 的**表和事件族仍永不建**；计入补齐的只是窗口资格投影。用户口径「R2 已禁 quota/spent」对应的条文是 R3b/R3c「明确仍不做」，外加迁移 §3「触发前做=第二套账本」。R2 正文禁的是新表与预扣，不是这组事件名。

### 2.3 补齐项的机制落点

13 条补齐都指向五机制之一，没有第六个。

| ID | 机制 | 具体对象 | 不做的事 |
|---|---|---|---|
| F23 | 1 状态在行 | 既有 latch + `v13_latch_fire` | 不新表；不重开 A19 |
| F17 | 1+3 | 谓词读 `parent_session_id`；拒绝时零事件 | 不加列；不建 link |
| F8 F18 L5 L6 L21 L26 L38 | 5 投影 | STABLE 函数，零写入 | 不建 waiter / ack / 紧凑 index 表 |
| F29 L32 L27 | 3 事件 + 5 策略行 | `control/handoff`、`goal/stopped\|resumed`；`handoff_policy` | 不产 XML；不扩 status |
| L29 | 2 推进函数 | 路由不选 spawn | 不加 route 键 |
| L26 的读 | 2 | advance 入队前读 `v13_should_run` | 函数本身不入队、不 closeout |

## 3. 分期路线

依赖序 A → B → C。一期 = 一个 stage = 一次按路径 commit。新 SQL 只追加 `SQL_LOAD_ORDER`（现 20 项）。换体以 `pg_get_functiondef` 活体为底，不改 stage 1–20 文件字节。测试 Fake，不调真实 provider。外部 IO 不进事务。

目录名是计划约定，不是裁决。

### Phase A · 修地基

不新增动词。闭合 L1/L2 承重缝。验收读法：**续传不再被已答 cap 卡死；release 词表有写入者；第四务有驱动合同；`children_terminal` 能走完 advance；parse 能看见具名 sql 工具。**

| stage | 目录 | 内容 | gate 要点 |
|---|---|---|---|
| 21 | `v13/seam/` | D11、D12 热修 + R5 端到端 | 见下 |
| 22 | `v13/catalog/` | D14 catalog 换体 + R4 合同 | 见下 |

三条未裁的处置（先裁再写 SQL；D13 无 SQL）：

1. **repair_cap × tail gap（D11，优先）。** 活体：已答 cap → 新 uuid、index 0，advance 跳过续传臂（`v13_cap_human_answered`，triage）；更老的 progress+signals 若无 index+1，`v13_harness_tail_gap` 仍 RAISE。只能 `closeout(..., cancelled)` 逃生。**倾向：已答 cap 免除被取代链的续传义务**（tail gap 把「该 `logical_turn_id` 已被 cap 新回合取代」视为已还）。不选「先补 index+1」——那与「跳过续传臂」矛盾，把已裁的新回合变成死锁。gate：已答后 advance 不 RAISE、可 `closeout completed`；未答真断链仍 RAISE；1–20 字节不动。
2. **F23 latch（D12）。** **倾向：`worktree_release` 成功才 `v13_latch_fire(..., state=released)`；失败/unknown 保持 `prepared`。** 不重开 A19。gate：成功翻 `released`；失败仍 `prepared`；prepare 仍写 `prepared`；无 binding 仍拒 claim。
3. **F4 静默 no-op（D13）。** **倾向：不移植。** C4 RAISE 已冻。台账一行即可，不新开 Oracle，零 SQL。除非产品要「重复 respond 不报错」才重开 C4——本路线图不推荐。

**R4 真 worker 第四务。** 谓词 `v13_cancel_pending` 已在（fanout），生产循环没有。库内无常驻 worker。落点=驱动器（事务外）在每次 `v13_renew_lease` 成功后读该谓词：`best_effort` 或 required+llm → `complete(cancelled)`；tool+required → `complete(unknown)`；`unsupported` → 不 cancelled。无 LISTEN、无新队列、无 `pg_terminate_backend`（R3c §8.7；残留 R8）。stage 22 gate 用假 worker 锁死顺序。`demo_v13/` 在 gitignore，驱动器补丁不进里程碑 commit，但 Phase A 验收必须实跑该循环一次、退出码 0。否则 R4 只是纸面。

**R5 `children_terminal` 生产者。** 求值器在 stage 18 已激活；缺口是没有一条 advance 路径被端到端证明。**生产者只有驱动器**（把 `wake.kind=children_terminal` 放进 harness 结果，事务外）。SQL 不合成 harness 结果——合成=第二个真相，advance 会变成编排器。stage 21：若活体 advance 未调用求值器则换体接上；gate 用假结果证明停泊 → 子齐 → 恰一条 `wake/satisfied` → 续传 index+1；非直接子仍 RAISE。

**R6 catalog 缝（台账 F22，不是 parity F22）。** `v13_tools_catalog_frozen` 仍拒 VOLATILE，故 `spawn_subsession` 保持 `enabled=false`，扇出走 `tool/call` 不走目录。**倾向（D14）：换体该函数，具名写者闭集（`v13_named_sql_writer` 非 NULL）对 parse 可见；闭集外仍拒。** 不改 stage 2 字节。gate：enabled=true 时 parse 不因 VOLATILE 失败；名单外仍红。

### Phase B · L1 工作流动词

吃掉 §2.1 的补齐，F23 已在 Phase A，不重复。验收读法：**动词组闭合 = 观察（含多 id 全量授权）/ 注入 / 应答 / 取消 / 授权 / 交接。** 后四者里注入、应答、取消已在 stage 17–20；本期闭合授权、多目标观察、交接。

| stage | 目录 | 补齐 | 硬依赖 | gate 要点 |
|---|---|---|---|---|
| 23 | `v13/acl/` | F17 | D7；Phase A 绿 | 直接父可 cancel 子；孙/自身/无关同一不可区分错误且零写；工具参数里的 actor 不被采信；operator 角色按 D7 |
| 24 | `v13/observe/` | F8 F18 | stage 23 | 多 id：任一未授权则零行，不泄露存在；单 id 读 events 先授权；不建 waiter；超时不进 schema |
| 25 | `v13/handoff/` | F29 | D16；stage 23 | 先授权再写恰一条 `control/handoff`；无 XML；文件内容不进载荷；不 INSERT 子会话（fork 仍是唯一子原语） |

### Phase C · L2 治理投影

投影优先。验收读法：**性质组闭合 = 自动推进有唯一门（L26）/ 资格可从窗口重算且≠奖励（L6+L37+L38）/ 可停可复且停≠cancel≠删行（L32）/ 注意力与调度提示无副作用（L5+L21）。** 结算完备、不丢运行、不超售已在 17–20，不重做。

| stage | 目录 | 补齐 | 硬依赖 | gate 要点 |
|---|---|---|---|---|
| 26 | `v13/should_run/` | L26 | D10；Phase A 绿 | advance 入队前读；假 → 零新 effect、不写第二 status；投影本身零写入；改序=新策略版本，不改函数体 |
| 27 | `v13/quota_window/` | L6 L38 | D9；stage 26 | 窗口外不计入资格；源码零 `quota/spent` 与 `quota/voided`；能力差非空则不入队；reward 仍无生产者 |
| 28 | `v13/attention/` | L5 L21 | stage 26 | `attention_rank` 不落表列；hint 不是 ack；连续两次调用零事件；pg_cron 路径再判一次才 advance |
| 29 | `v13/govern/` | L32 L27 L29 | D15；stage 25；R6 | stop 后 recover 零 nudge、advance 零新 effect；指纹不符零写；`duty_cycle=0` 行为不变；handoff 缺政策则拒；到顶时路由不选 spawn |

凡要新表或新列的项不得偷偷进上表，必须先有 §4 裁决改倾向。

每期收尾（缺一不可，然后才 commit）：该 stage `test_*.py` 退出码 0；回归 stage 1 至本 stage 全部 gate；`SQL_LOAD_ORDER` 只追加；覆盖矩阵、偏差台账、该 stage `README.md` 已更新。台账里的 F22 是 catalog 缝，不要写成 parity 的 worktree F22。

## 4. 新决策（D7 起）

不重开 D1–D6、A15–A21、R3 链已冻失败模式（终态 `replay`、routed llm `unsupported`、XOR 否、零新表默认、不建 `v13_agent_run`、不把 `duty_cycle=0` 当成 L32）。下表是本路线图未覆盖或与「落点未写」相接的分叉。倾向不是裁决。未裁前对应 stage 不开工。

| D | 题 | 倾向 | 影响面 | 不开工就停 |
|---|---|---|---|---|
| D7 | F17 谁能控谁。不加 sessions 列放哪 | 谓词 + 已有 `parent_session_id`。actor 只来自调用方会话 id（服务器传入），不读工具参数。`current_user` 为控制角色则可控任意非终态会话（同 D4 带层）。agent actor 只能控直接子且非自身。拒绝文案一律不可区分（与源合同同形）。自答 human 同一谓词拒绝 | stage 23 接入 cancel / human complete / observe / handoff。不建 link 表（F30 仍永不建） | 是 |
| D8 | goal registry 用 sessions+policies 够不够 | 够。`goal_id=session_id`（PK 即拒重复）。资格=策略行（`spawn_budget` / `triage` / 新 `quota_window`）。账本=events。不建 registry 表。`requires_parent_approval` 折进 D7，不另开列 | L1 永不建得以成立；L6/L26 的策略行有住所 | 否（默认按此开工；要表则停） |
| D9 | 窗口资格，且不写 `quota/spent\|voided` | STABLE 重算：策略行 `{window_hours, slot_minutes, allowed}` × 窗内 `turn/material_spent` 条数。过期=滑出窗口，不撤回事件。窗内冲销不做（那才需要 void 事件，仍禁）。无负债：不够则 L26 返回假，不记负 | stage 27。不改 `turn_no`（R1.11 / R3b 禁 closeout 赋值） | 是 |
| D10 | should-run / attention 是投影还是策略行 | 函数 STABLE 只读；**优先序住策略行**（版本化，改序不改函数，同 R2 §3.4 改种子）。序用迁移 §2.6 已写的硬门：human > unknown > cancel > `duty_cycle=0`，其后接 D9 窗口与 L38 能力，不搬 LoopX 七态名字。`attention_rank` 只是 `v13_attention` 的输出列。advance 读函数，函数不授权 | stage 26/28。不扩 `sessions.status` | 是 |
| D11 | repair_cap × tail gap | 已答 cap 免除被取代链的续传义务。不选先补 index+1 | stage 21 换体 `v13_harness_tail_gap`（或它的豁免谓词） | 是 |
| D12 | F23 谁把 latch 写成 `released` | release 成功才 `v13_latch_fire`；失败保持 `prepared` | stage 21。不重开 A19 | 是 |
| D13 | F4 静默 no-op | 不移植。台账一行。零 SQL | 无 stage。不重开 C4 | 否（文档即可） |
| D14 | R6 catalog 缝 | 具名 sql 写者对 parse 可见；其余 VOLATILE 仍拒。不把 `enabled=false` 当架构 | stage 22 换体 `v13_tools_catalog_frozen`。台账 F22 ≠ parity F22 | 是 |
| D15 | L32 停/复放哪。不加列 | 开放事件 `goal/stopped\|resumed`，指纹=已有 `v13_state_hash`。不符则 RAISE 零写。stop 不扫 claimed、不 closeout、不删行。resume 只追加事件。与 `duty_cycle=0` 并列，不等同 | stage 29。recover_idle 与 advance 入队前读最后一条 | 是 |
| D16 | F29 信封键集 | 迁移 §2.2 字面：`{schema_version:1, delivery_id, transcript_hash, up_to_seq}`。不采 XML（R1.4）。不含水合文件。不升成第二 transcript | stage 25。文件字节归姊妹篇 | 是 |

D8 若被改成「要 registry 表」，L1 从永不建改为 §4 例外，Phase C 不得先开工。其余倾向被否时，只停对应 stage。

## 5. 不变量与红线

1. 五机制不可违反。观察是投影，不是 poll 函数。资格是 advance 入队前的读，不是第二个循环。交接是一条事件，不是 fork 的替身。
2. 零新表、零新列是默认。例外只经 §4 改倾向之后。策略行与开放事件不算新表。
3. stage 1–20 文件字节冻结。行为变更只许后 stage `CREATE OR REPLACE`。`SQL_LOAD_ORDER` 只在末尾追加。
4. 外部 IO 不进事务。第四务、harness 结果、worktree FS 都在驱动器。SQL 不杀进程（无 `pg_terminate_backend`）。
5. 投影不授权（R1.5）。`v13_attention` / hint / should-run 的假不得被驱动器无视；真也只表示「可以再调 advance」，不表示已经执行。
6. 不把 `duty_cycle=0` 写成 L32，不把 `decisions.epoch` 写成 run generation，不把 `turn_no` 写成树预算或窗口余额。
7. gate 全绿才 commit：该 stage `uv run python v13/<stage>/test_*.py` 退出码 0，并回归此前全部 stage。按路径 `git add`。禁止 `git add -A`。禁止 force-push。禁止 `--no-verify`。
8. 测试用 Fake / 直接 SQL。parity 套件（真实 StepFun，gitignore）不是 gate，只可作 Phase A R4 的驱动器验收。

## 6. 与既有待办线

| 线 | 关系 |
|---|---|
| v13.1 工作台 / DP10 | 不在当前 v13 控制面 stage 里，也不在本路线图。选台与 duck 执行不改控制动词；本路线图不给工作台排 stage。 |
| `docs/designs/v10-dev.md` | 冻结规格。grant / generation / 插件世代缺口留在 v8/v10。F20 因此永不建，不在 v13 控制面重开 grant 类。 |
| v8 P0C | pinned DSH 真实 IO 半边，与控制动词正交。wrapper 深度已裁（谱系文 §4）；P0C 不阻塞 Phase A–C。 |
| `repoprompt-native-on-v13-feasibility-v2` | 姊妹篇，文件与上下文收集。F18/F29 只读 events 与 hash，不水合文件，不重叠 I-file。 |

不在本路线图开工的，还有：steer 正文（R3b 已不做）、`closeout/inbox_residual`、`material_cap` 生产者、G6 新条文、`thresholds.action` ALTER。这些是已裁残留，不是新缺口。
