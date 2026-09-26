# v13 控制面对照裁决：RP-CE / LoopX × pg-agent（2026-09-26）

> W5 交付。回答：repoprompt-ce 与 LoopX 的哪些控制 Agent 运行功能在 v13 一模一样、哪些改变了、哪些完全没有实现。
> 源合同：`prompt-exports/parity-rpce-2026-09-26.md`（F1–F30）、`prompt-exports/parity-loopx-2026-09-26.md`（L1–L41）、`prompt-exports/parity-v13-2026-09-26.md`（V1–V47、R1–R13）。
> 裁决源：R2 §1–§3 与 A15–A21；R3 / R3a / R3b / R3c（`docs/reviews/v13-control-plane-oracle-r3-2026-09-26.md`，R3c 全文同目录）；迁移报告 `docs/analysis/v13-control-plane-migration-2026-09-25.md` §2 与 §0「明确不做」。
> v13 行号是 `SQL_LOAD_ORDER` 最后一次 `CREATE OR REPLACE` 的活体（control → spawn → fanout → triage）。源行号取 D1/D2（2026-09-26 复验）；未裁三项的源侧与全部 v13 锚由本文抽查。
> 编号不要和偏差台账的 F1–F8、D3 残留里的「F19/F20/F22」混用。那些是安装事实或 stage 内部缝，不是本文的 RP-CE F 号。

## 0. 执行摘要

严格合同下，**一模一样 = 0**。v13 不是逐条移植，是已裁换体：核心意图留在函数里，失败模式几乎处处不同。

| 源 | 条数 | 一模一样 | 改变 | 完全没实现 |
|---|---:|---:|---:|---:|
| RP-CE F1–F30 | 30 | 0 | 17 | 13 |
| LoopX L1–L41 | 41 | 0 | 13 | 28 |

| 桶 | RP-CE | LoopX |
|---|---|---|
| 一模一样 | （无） | （无） |
| 改变 | F1 F2 F3 F4 F6 F7 F9 F10 F11 F12 F13 F14 F15 F22 F23 F27 F28 | L8 L9 L10 L11 L12 L14 L15 L18 L31 L33 L34 L35 L37 |
| 完全没实现 | F5 F8 F16 F17 F18 F19 F20 F21 F24 F25 F26 F29 F30 | L1–L7 L13 L16 L17 L19–L30 L32 L36 L38–L41 |

五条最重要的结论：

1. **没有一条源合同连失败模式一起被测试证明等价。** 最近的是 F11：错 `interaction_ref` 会 RAISE、带回当前 ref、零写入（`g_approval.py:56`）。它仍不是一模一样——种类折叠、无自答拒绝、无选项标签。
2. **RP-CE 的控制意图大多有落点（17 条改变）。** 没有落点的是进程内机器：shutdown、多目标 wait、TTL、授权/grant/经纪人、冷恢复、handoff、oversight link（13 条）。epoch/fence 是改变（F12/F13），不是缺函数。
3. **LoopX 的 26 表治理面按「明确不做」整包不搬**（§0：`quota_spends` / `command_receipts` / `outbox` / `leases`，以及六层文件面）。结算四步被拆成三次事务：`v13_complete`（writeback）、advance ⑤（material 收据）、`v13_closeout`（封账）。
4. **确认未裁 3 条：** F4 静默 no-op、F23 release 不把 latch 写成 `released`、已答 `repair_cap` 与 `harness tail gap` 叠用。见 §4。
5. **两条候选不是未裁。** 终态 cancel 返回 `replay` 是 R3 / R3b 写死的。`tool_name` 为空的 routed llm 不能 `complete(cancelled)` 是 R3c「未点名 → unsupported」的字面结果。

## 1. 判定标准

一条源功能只进一个桶。

| 桶 | 标准 | 依据要求 |
|---|---|---|
| 一模一样 | 语义合同逐条等价，**含失败模式**，且有测试证明 | 两侧锚点 + 证明测试 |
| 改变 | 核心控制意图还在，形状或机制不同 | 必须引 R2 §1–§3、R3 链，或迁移 §2 / §0「明确不做」 |
| 完全没实现 | v13 无对应函数、事件或投影 | 裁决不搬的也进此桶，写明依据。不是疏忽清单 |

「改变」不要求失败模式相同。失败模式无条文覆盖的，桶仍是改变，并在 §4 标「未裁偏差候选」。裁决明确不建、且没有替代函数实现该合同的，进「完全没实现」，不进未裁。

证明测试优先 `demo_v13/parity/g_*.py`（StepFun 真实调用，`result_kind` 脚本化）。该目录在 `.gitignore`，与 `demo_v13/` 同例，不是 stage gate。gate 只作补充锚，不替代对照套件。

边界（不另开桶）：

- 裁决把落点指到一个**已存在**的函数，即使失败模式不全 → 改变。F7 无 poll/wait 函数，但迁移 §2.2 把观测落成读行，故不进没实现。
- 裁决写「不建」且没有替代函数实现该合同 → 完全没实现。F5 的租约与 cancel 是别的功能，不算 shutdown。
- 条文点了名、SQL 零命中 → 仍是没实现，标「落点未写」。L26 的 `quota.should_run` 属此，不是未裁。
- 两条已裁规则的组合没有排序 → 桶仍按单条归类，组合本身进 §4 未裁。repair_cap × tail gap 属此。

## 2. RP-CE 对照（F1–F30）

### 2.1 一模一样（0）

空。F11 的错 id 子弹（抛错、带回当前 id、不改状态）与 R3 C4 同形，且 `g_approval.py:56,62` 证明了。整条 F11 还有：按 kind 再检、agent 不能答自己的 `ask_user`、approval 必须是广告选项标签（`AgentRunMCPToolService.swift:1505`；`AgentModeViewModel.swift:10699`）。v13 把六种 kind 折成一条 human，request 恰 `{schema_version, interaction_ref}`（`v13/fanout/v13_fanout.sql:370`）。失败模式不全，不过线。

### 2.2 改变（17）

V 号：F1/F6=V17，F2/F10/F15=V15，F3/F9=V7+V26+V28，F4/F11/F27=V12，F7=V22（只覆盖丢唤醒，不覆盖停车），F12/F13=V8，F14=V5，F22/F23=V29–V32，F28=V3+V4。

| ID | 源合同（被换掉的形状） | 源锚 | v13 活体 | 证明 | 依据 |
|---|---|---|---|---|---|
| F1 | 活进程幂等返回；失败自 `shutdown`；`existingSessionID` 续同一进程 | `NativeAgentRuntimeContracts.swift:17`；`ClaudeNativeProcessSessionController.swift:378` | `v13_open_session` 总是新行，spec 无 `session_id`（`v13/spawn/v13_spawn.sql:285`） | `g_steer.py:22` 只证两个新 id。幂等续跑标明非测试 | 迁移 §2.1 根/续跑/子拆开；R3 D4 与 §1 附「不接受调用者 session_id」 |
| F2 | 无进程则 `processNotRunning`；在途第二发是 interrupt-style steer | `NativeAgentRuntimeContracts.swift:25`；Controller `:451` | 七键水位不符 → `stale`；claimed 期间 request 不变。`steer/injected` 载荷已注册，P1 无正文生产者 | `g_steer.py:100,102` | R1.9；迁移 §2.1；R3b §7.3「P1 不新增生产者」 |
| F3 | 四值 `acknowledged\|noTurnInFlight\|timedOut\|failed`，不抛；1.5s ACK | Controller `:460`；`InterruptOutcome` `:86` | `v13_cancel`（`v13/fanout/v13_fanout.sql:153`）+ `v13_interruptible`（`:37`）+ `complete(cancelled)`（`:335`）。无 provider ACK | `g_cancel.py:63` | R2 A18；R3c-full:177。routed llm 的 RAISE 是已裁默认，见 §4 |
| F4 | 未知/已答 id：`removeValue` 失败则 **return**，不写线 | Controller `:495-498` | human 成功结算：ref 不等则 RAISE，消息含 `submitted` 与 `current`（fanout `:370-373`） | `g_approval.py:56` 证明的是 RAISE | v13 通道由 R3 C4 冻成 RAISE。**相对 native 静默 no-op 无对照条文，未裁** |
| F6 | `op=start` 总是新 tab；传入 `session_id` 即拒；`detach`/timeout 等待 | `MCPAgentControlToolProvider.swift:179`；`AgentRunMCPToolService.swift:440` | 同 F1。无 MCP 等待策略、无 `detach` | `g_steer.py:19` | R3 §1 附；迁移 §2.2 start 行（等待形状不进事件） |
| F7 | `poll` 立即快照；`wait` 停到 interesting/终态/超时；过期句柄抛恢复说明 | `AgentRunMCPToolService.swift:1009,1155` | 无 poll/wait 函数。落点是读行 + `v13_recover_idle`（spawn `:508`）。无 `[120,300,…]` 超时集 | `g_steer.py:102` 只证水位双检 | 迁移 §2.2 新裁=否；R1.7；R3c §8.4 |
| F9 | 终态 cancel **抛错**，消息含当前 status | `AgentRunMCPToolService.swift:1186-1188` | 根已终态 → `RETURN 'replay'`，零写（fanout `:217-218`） | `g_cancel.py:53` | R3 §1「终态 → replay」；R3b `v13_cancel` 终化。**已裁** |
| F10 | 过期/结束的 run 用同一 `session_id` 再激活；未知 id 不建注册 | `AgentRunMCPToolService.swift:247,1218` | 未知 id：`v13_advance` 抛错且不插入（`g_steer.py:33`）。无 300s 句柄再激活；同会话续跑是新 `effect_id` | `g_steer.py:33,102`。再激活标明非测试 | A15 / R1.2；迁移 §2.4「snapshot expired 不进 status」 |
| F11 | `interaction_id` 必须等于当前 pending；不符带回真 id，零变更 | `AgentRunMCPToolService.swift:1505` | 见 §2.1。种类与自答授权没有 | `g_approval.py:44-63` | R3 C4；R2 §1.2；R3b 审批 request 两键 |
| F12 | 一切 CAS 走 registration+epoch，禁止只按 `session_id` | `DomainAgentRunSessionStore.swift:3-32,:1021` | 句柄 = `(session_id, effect_id, fence)`。`decisions.epoch` 是 bind 相位，不是 run generation | `g_approval.py:49` fence → `stale` | 迁移 §2.4；§0 明确不做「把 `decisions.epoch` 当成 run generation」 |
| F13 | `beginEpoch` 不等则 `.stale`；旧 waiter 同回合 `.epochAdvanced` | `DomainAgentRunSessionStore.swift:350` | fence 失配 → `stale`。无 waiter 表，无 ordinal | 同上 | 迁移 §4「epoch CAS」行 |
| F14 | 同 `commitID` 原样重放；不同 `commitID` 拒绝 | `DomainAgentRunSessionStore.swift:420` | `v13_closeout` 重放已存印章；outcome 冲突 RAISE。无独立 commit id（spawn `:585`） | `g_closeout.py:51,64` | R2 A16；R3b §7.2 重放短路。**已裁** |
| F15 | 停车前再验 epoch / 终态发布失败 / 可行动快照 | `DomainAgentRunSessionStore.swift:629` | advance 步 0 七键；recover 锁内复验。无 per-waiter 超时 | `g_steer.py:102` | 迁移 §2.2；R3c §8.4 |
| F22 | worktree 参数只属于 `start`；绑定先于 provider 启动；`inherit_worktree` 默认真 | `MCPAgentControlToolProvider.swift:194`；`AgentMCPStartWorktreeCoordinator.swift:86` | latch 名 `worktree` + `worktree_prepare\|merge\|release`。子不继承。prepare 的 `tool/result` 被下一格 advance 看见才 `v13_latch_fire` | `g_worktree.py:46-86` | R2 A19；迁移 §2.2；R3c worktree 节 |
| F23 | 绑定前准入变化 → `git worktree remove --force`；`apply` 要 preview 的 `operation_id` | Coordinator `:409,:429` | `worktree_release` complete 成功，latch 仍 `state=prepared`。唯一写入是 prepare 路径的 `'prepared'`（fanout `:146`） | `g_worktree.py:102-105` | 三工具名与 `prepared\|released` 词表是 R3c。**谁把 state 写成 `released` 没有条文，未裁** |
| F27 | kind 六值、responseType 五值；`interaction_id` 出现两次；`amendment` / elicitation | `DomainAgentSessionModels.swift:253`；payload `AgentModeViewModel+Types.swift:431` | 折叠进 `wait_reason=approval`。通道严格 one-of：`response` / `answers` / `skip`。无 amendment | `g_approval.py:44,97` | R2 §1.2；迁移 §2.3；R3 D6 / C4 / C5 |
| F28 | 两段提交；commit 已开始则 indeterminate，**绝不自动重执行**；journal 按 commitID 重放 | `MCPDomainProtectedMutationToolProvider.swift:9`；`DomainMutationJournal.swift:175` | 非 judge 过期 → `unknown` 且抬墙。只有 `v13_resolve_unknown` 能拆（`v13/control/v13_control.sql:831`）。无 journal 表 | `g_unknown.py:28,62` | 迁移 §4；R3 D5。零新表，不建 mutation journal |

### 2.3 完全没实现（13）

这些没有对应函数、事件或投影。依据是「不建 / 不进本期」，不是漏写测试。

| ID | 源合同 | 源锚 | v13 | 依据 |
|---|---|---|---|---|
| F5 | 可重入 `shutdown`；与启动失败配对 | Controller `:518`；`DomainAgentRunSessionStore.swift:791` | 无 `v13_shutdown`。租约过期与 `v13_cancel` 是别的功能 | 迁移 §2.1「不建 dormant/interrupted；5s drain 不进 schema」 |
| F8 | `session_ids`：先全量授权；wait = 第一个 interesting 胜 | `AgentRunMCPToolService.swift:1049,1155` | 无多目标函数，无 all-or-nothing | 迁移 §2.2「多 id = 驱动循环」，不建 waiter |
| F16 | 终态快照 TTL 300s → 摘记录、waiter `.expired`、元数据 `dormant` | `DomainAgentRunSessionStore.swift:216,:1000` | 无 TTL。恢复不是 steer 再激活 | 迁移 §2.4「snapshot expired 不进 sessions.status」 |
| F17 | 只有直接父能控；失败一律「session not found」 | `DomainAgentSessionOperationAuthorizer.swift:250` | 无 authorizer | 迁移 §2.2 `agent_manage` / link 不进第一期。stage 17–20 未补 |
| F18 | `get_log` / `extract_handoff` 先授权再水合 | `AgentManageMCPToolService.swift:146` | 无这两条 op | 同上 |
| F19 | `cleanup_sessions` ≤256，全有或全无，不删活跃 | `AgentManageMCPToolService.swift:8,:1159` | 不删行 | 迁移 §2.2「墓碑删除不迁；停会话是 cancel」 |
| F20 | `ai_cost` / `external_process` grant、指纹、执行前 `revalidate` | `DomainMutationPolicy.swift:170,:261` | 无 grant 类 | 未映射到函数。审批两段是 F11/F27，不是这套 |
| F21 | FIFO 审批经纪人，五值结果 | `DomainMutationApproval.swift:38` | 无 presenter 队列 | 无函数。demo 驱动器里的超时是进程内的，不是这条 |
| F24 | 冷恢复把活跃 run 收成 idle；坏字节保留、不删 | `AgentSessionRestoreSupport.swift:61` | 无冷恢复。行在即活 | 迁移 §2.4 durable `dormant/active/interrupted` 不建。transcript 规范化无函数 |
| F25 | `claimResumableSession`：活记录、健康、所有权栅栏；持久化失败整笔回滚 | `DomainAgentRunSessionStore.swift:288` | 无 claim。拆墙是 `v13_resolve_unknown`，不铸新回合 | 迁移 §2.4 无此栅栏；`g_unknown.py:86` 记为未实现 |
| F26 | shutdown 一个 actor 回合摘掉全部 waiter；无 handler → dormant，否则 interrupted | `DomainAgentRunSessionStore.swift:791` | 同 F5 | 迁移 §2.1 |
| F29 | `extract_handoff` / fork transcript XML；先授权再水合 | `AgentModeViewModel.swift:20255,21284` | 无 handoff 函数。`v13_fork`（fanout `:920`）是 A17 子会话原语，不产 XML | 迁移 §2.2 不进第一期；R1.4 不采 XML |
| F30 | oversight link：能力不推断、`indeterminate` 压过收据、有界 send | `DomainAgentSessionLinkAuthority.swift:1` | 无 link 表、无 send 账本 | 迁移 §2.2「不建 send 账本；永不持久化保持不持久化」 |

## 3. LoopX 对照（L1–L41）

LoopX **没有** mid-turn interrupt（L31）。v13 的 cancel 来自 RP-CE A18，不是把 L31 原样搬过来。下文「改变」包含这种被裁决翻转的项。

### 3.1 一模一样（0）

空。最近的是 L8 / L14 的「再提交不二次写」。v13 用唯一索引和 `replay` 字，不用 index 回读、不用 `commitID`、不用 `settlement_owed.command`。失败模式不同。

### 3.2 改变（13）

V 号：L8=V5+V19，L9=V1+V14，L10/L11=V8，L12=V10，L14/L15=V5，L18=V1+V2，L31=V7（相对 LoopX 是翻转），L33=V13+V4，L34=V18，L35=V20，L37=V2+V12。

| ID | 源合同（被换掉的形状） | 源锚 | v13 活体 | 证明 | 依据 |
|---|---|---|---|---|---|
| L8 | 锁内回读 index；标记已在则 `already_current`，不追加；标记缺失 → `OSError` | `cp/runtime/runtime_projection_writer.py:46` | 终态 `v13_complete` → `replay`（fanout `:330`）；spawn 同 `tool_call_id` 且 task 逐字相等 → `replay`，否则 RAISE `spawn ledger` | `g_spawn.py:169`；`g_closeout.py:51` | 迁移 §3 `command_receipts`「语义证实，表冲突」 |
| L9 | 身份 XOR：`todo_id` 与 `replan_obligation_id` 恰一，否则 `RuntimeError` | `cp/effect_program.py:299` | 身份是 `v13_effect_id`（`v13/schema/v13_core.sql:175`）。`signals` 允许 1..2，repair 与 replan 可同批 | `g_steer.py:77` 同批 repair 仍续传 | R2 §1.1：repair/replan 是事件，不是身份。XOR **被否** |
| L10 | 四步有序：VALIDATION → WRITEBACK → QUOTA_SPEND → CLOSEOUT；先 journal `prepared` | `cp/effect_program.py:171` | 三次事务：complete、advance ⑤、closeout。无 prepared journal。`post_settlement` 未建 | `g_closeout.py:31` | 迁移 §2.5「三笔三次事务，不合成一个大事务」 |
| L11 | 先写 todo，再 `refresh_state_run`；无选中 todo → `ValueError` | `loopx/cli_commands/turn.py:477` | complete 同事务写 status + `effect_done` / 语义事件。无状态文件 fsync | gate `test_control.py` 的 complete 路径；对照套件不重跑文件写回 | 迁移 §2.5 DURABLE_WRITEBACK 行 |
| L12 | spend 有来源、digest、状态准入；失败关闭 | `cp/quota/slot_accounting.py:69`；`spend_commit.py:170` | material 收据在 advance ⑤，不在 complete。无 `expected_index_digest` | `g_closeout.py:70` 未付 material 不能 completed | R1.11；迁移 §2.5；R3a §6.4。LoopX 那些前置谓词没有函数 |
| L14 | closeout 必须重读 writeback；todo 不是 `no_followup` 则不能宣称终态 | `cp/turn_driver/settlement.py:207` | `v13_closeout`：计数前置 + 收据。不重读外部状态文件 | `g_closeout.py:22-51` | R2 A16；R3b §7.2 |
| L15 | 相位机直到 `settled`；`settlement_owed.command` 补收据不再扣 | `cp/quota/settlement.py:168` | 欠账 = 收据 `unconsumed` 五键 + 「续传未还」则 RAISE。closeout 不新扣 | `g_closeout.py:89` | 迁移 §2.5 相位机是投影不是列；R3b unconsumed |
| L18 | `loopx_turn_host_request_v0`；未知字段即错；host 不得从环境推断 | `cp/turn_driver/executor.py:101` | harness request 六键闭集；`result_kind` 四值权威；`delivery_kind` 路由不读 | `g_steer.py:62` | R2 §1.1；R3b §7.1。dsh/codex-cli 选择未建 |
| L31 | **无**中断原语；`cancelled` 只是结算失败种类；`do_not_cancel_on_block` | `cp/effect_program.ts:117`；`interaction_contract.py:1641` | 有 `v13_cancel`。这是相对 LoopX 的翻转，不是漏实现 | `g_cancel.py:38` | 迁移 §2.1 + R2 A18：采用 RP-CE 粘性 cancel，不采用「无中断」 |
| L33 | 中断后续跑，不重启；状态文件字节不变 | `cp/quota/unsettled_host_turn_recovery.ts`；`recovery.py:19` | progress+signal → 同一 `logical_turn_id`、index+1。`resolve` 不铸新回合 | `g_steer.py:66`；`g_unknown.py:83` | R3a §6.3 continue；迁移 §4。无「状态文件字节相同」可断言 |
| L34 | `max_children` 正整数；达到即拒；`mode=multi_subagent` 且 `spawn_allowed is True` | `cp/quota/task_orchestration_admission.py:71` | `spawn_budget` `{max_nonterminal:8, max_depth:4, max_fanout:8}`；`v13_spawn_subsession`（spawn `:318`） | `g_spawn.py:150,207` | R3c §8.1 收窄 R2 §2.3：席位计数，禁止把 `turn_no` 当树预算 |
| L35 | 超限/畸形 → `pre_spawn_rejections`，不部分生成 | `cp/turn_driver/subagent_execution_topology.py:91` | 坏 `tool_calls` RAISE、不烧 claim、零子。N 或 0 | `g_spawn.py:44,56` | R2 §2.6；R3c §8.3 / §8.8 |
| L37 | 配额只决定资格，不决定奖励、写审批、operator gate | `docs/quota-allocation.md:13` | `wait_reason` 三分。approval 是 human，不是配额。无 `operator_gate` / `safe_bypass` / `human_reward` 生产者 | `g_approval.py` 与 `g_wake.py:21` 分列 | R2 §1.2；迁移 §2.6。后三样无函数，不另开一条「已实现」 |

### 3.3 完全没实现（28）

依据分三类。**裁决不搬** = 迁移 §0 / §3 或 R3b/R3c「明确不做」。**无落点** = §2 没有把该合同指到一个已存在的函数。**落点未写** = 条文点了名，SQL 零命中。

| ID | 源合同要点 | 源锚 | 依据 |
|---|---|---|---|
| L1 | registry 是资格源不是账本；重复 id → `ValueError` | `cp/projects/registry.py:40` | 裁决不搬。无项目 registry。`v13_policies` 不是这张表 |
| L2 | `ACTIVE_GOAL_STATE.md` + fsync，不是 rename | `loopx/state_refresh.py:797` | 裁决不搬。goal = sessions 行（迁移 §3） |
| L3 | `runs/*.json` 后回读 `index.jsonl`，缺标记即失败 | `runtime_projection_writer.py:40` | 裁决不搬。events 不是这组列 |
| L4 | 消费者只读紧凑 index，不读私有载荷 | `cp/runtime/run_history.py:21` | 无此投影 |
| L5 | attention 队列无副作用；权威是逐 goal should-run | `cp/work_items/attention_queue.py:94` | 无 attention 函数。`v_goal_tree`（spawn `:467`）是树，不是此队列。迁移 §2.6 的 `attention_rank` 输出列，SQL 零命中 |
| L6 | `spent_slots` 从窗口重算；`quota_slot_voided` 是唯一冲销 | `slot_accounting.py:1028`；`void_commit.py:17` | 裁决不搬。R3b-full:213 与 R3c「明确仍不做 `quota/spent\|voided`」 |
| L7 | 三档 `flock` + `.ts-effect.lock`；死进程释放，无过期锁回收 | `loopx/file_lock.py:77` | 无此锁策略。行锁 / 咨询锁是另一套（R3c 锁序），不实现这三档 |
| L13 | `execute=True` 必须带 `expected_index_digest` | `spend_commit.py:192` | 裁决不搬 `quota_spends`。无 digest 函数 |
| L16 | journal 文件名就是 `turn_key`；`replay_blocked`；`resolve_prepared` 读回不重执行 | `journal_store.py:20`；`settlement.py:287` | 迁移 §2.5「不把 journal 文件搬成表」。读回三值进了 `v13_resolve_unknown`（F28），不是本 journal |
| L17 | 12 个有类型的结算失败种类 | `effect_program.ts:108` | 无此闭集。v13 用自己的 RAISE 子串 |
| L19 | 每 lane 一个在执行 Turn；第二者 `turn_lane_in_flight`，带持有者回读 | `lane_fence.py:1` | 无此拒绝。既有 `ux_v13_effects_single_active` 是另一不变量（迁移 §3 证实、不吸收表） |
| L20 | 11 种 host 失败 + 有界重试提示（提示，不是进程内 sleep） | `host_failure.py:12` | 无此表。`effect_attempt_cap.tool=3` 是帽，不是提示表 |
| L21 | 无常驻心跳；外部 cron 问 `should-run`，只拿 `scheduler_hint` | `scheduler_hint.py:1` | 迁移 §2.6「pg_cron 是扫地僧不是节拍器」。无 RRULE |
| L22 | `scheduler_ack` / `heartbeat_commit` 是配额中性行；陈旧 hint 不得静默 ack | `scheduler_ack.py:272` | 无 ack 事件 |
| L23 | `BoundedTurnBudget` 违规是 `ValueError` 不是 disposition；managed step 不得当场 spend | `loop_controller.py:297` | 无此合同。`max_cycles` 与 `continuation_index` 是别的界 |
| L24 | monitor 相位 `[15,30,60]`；连续 2 次停滞 → `autonomous_replan_obligation` | `monitor_wait.py:13` | 无相位机。`replan/required` 是信号事件，不是这条 |
| L25 | 收据匹配 `quota_should_run` 且 `(goal, agent, run_id)`；冲突即错 | `heartbeat_receipt.py:21` | 无此收据 |
| L26 | 状态序 `blocked_health > operator_gate > … > paused`；paused 则一切自动推进为假 | `should_run.py`；`states.py:7` | **落点未写。** 迁移 §2.6 写「advance 读 `quota.should_run`」。v13 SQL 零 `should_run` |
| L27 | handoff mode 的 plan/runtime/transaction 分裂；两种一等来源 | `handoff_mode.py`；`delivery_contract.py:37` | 无函数。与 F29 同缺口 |
| L28 | head 与 receipt 分读；复用 operation id 而请求不同 → identity mismatch | `authority_store.ts`；`command_receipt.ts:1` | 裁决不搬。不是 L8 的 `replay` |
| L29 | 仅 `multi_subagent` 且 `spawn_allowed` 且 `max_children>0` 才投影 delegation context | `delegation_context.py` | 无此键。缺席 vs 空对象的区别没有 |
| L30 | peer 请求不改优先级、不中断；响应恒 `execution_interrupted:false` | `peers.py:20` | 无 peer op |
| L32 | `stop\|resume` + `--expected-state-fingerprint`；stop → `goal_stopped` | `cli_commands/goal_lifecycle.py:25` | 无指纹停/复。`duty_cycle=0`（`v13_triage_duty`，triage `:45`）是另一把闸，条文没有把二者等同 |
| L36 | steward 分配规范化；容量文档原子写 | `steward_executor/allocation.py:63` | README 标明无实现。无函数 |
| L38 | `missing_required_capabilities` 纯集合差；`human_reward` 只追加、不改已判 run | `capability_gate.py:59` | 无函数。迁移 §2.6 说 reward 保持开放事件，没有生产者 |
| L39 | command receipt 相位 `applied\|recovered\|replayed`；只读历史载荷 | `command_receipt.ts:1` | 裁决不搬（§0 / §3）。语义侧见 L8，表不建 |
| L40 | 两相 outbox，`prepared\|committed`，序号封顶 | `local_authority_shadow_outbox.ts:72` | 裁决不搬。唤醒是 `v13_recover_idle` / 驱动重入，不是 outbox |
| L41 | 租约 fencing token 单调；软 claim 不是硬排斥 | `task_lease_lifecycle.ts:79` | 裁决不搬表。`effects.fence` 已能让旧令牌 `complete` 得 `stale`（迁移 §3「证实，不吸收表」）。租约生命周期本身无函数 |

## 4. 观察到的行为差异

套件把差异打成 `note`，不当失败。十条对裁决的归类如下。

| # | 观察 | 套件 | 状态 |
|---|---|---|---|
| 1 | `demo_open_session` 总是新 id，无幂等续跑 | `g_steer.py:34` | **已裁。** R3 §1 附；迁移 §2.1 |
| 2 | 错 `interaction_ref` RAISE 且含 `current=`，不是静默 no-op | `g_approval.py:57` | **R5 已裁：不移植。** 台账 F23（= parity F4 / R3 C4，≠ parity F23） |
| 3 | routed llm（`tool_name` 空）`complete(cancelled)` → `interruptible unsupported` | `g_cancel.py:81` | **已裁，不是未裁。** R3c-full:179-180：未点名 → `unsupported`；`complete(cancelled)` RAISE。活体 `v13_interruptible` 只点名 `fanout_required` / `fanout_best_effort`（fanout `:37-44`），空名走 ELSE |
| 4 | mutating `fanout_required` 工具不能 `complete(cancelled)`，须 `complete(unknown)` | `g_cancel.py:110` | **已裁。** R2 A18；R3c-full:182；fanout `:337` |
| 5 | 已终态根 cancel 返回 `replay`，不抛含 status 的错 | `g_cancel.py:54` | **已裁，不是未裁。** R3 §1；R3b 终化；fanout `:217-218`。源侧抛错在 `AgentRunMCPToolService.swift:1186-1188` |
| 6 | closeout 重放收据，无独立 commitID | `g_closeout.py:64` | **已裁。** R3b §7.2 印章即提交；迁移 §4 |
| 7 | 无 300s TTL，无 `claimResumableSession` | `g_unknown.py:83,86` | **已裁为不建**（F16/F25），不是未裁的行为分叉 |
| 8 | `worktree_release` 完成，latch 仍 `prepared` | `g_worktree.py:105` | **未裁偏差候选（F23）。** R3c 词表含 `released`，并指定 prepare → `v13_latch_fire`。没有指定 release 的写入者，也没有说「不得翻转」。活体只在 fanout `:146` 写 `'prepared'` |
| 9 | 无 fingerprint stop/resume；`duty_cycle=0` 只是邻近闸 | `g_triage.py:65` | **已裁为不建**（L32）。没有条文把 duty hold 当成 L32 |
| 10 | 已答 `repair_cap` 铸新 `logical_turn_id` index 0，下一格 advance RAISE `harness tail gap` | `g_triage.py:168` | **未裁偏差候选。** 两条已裁规则的组合没有排序 |

第 10 条的叠用，活体是：

- R3a §6.3 / R3c fold cap：已答 cap human → 新 uuid、index 0。`v13_cap_human_answered`（`v13/triage/v13_triage.sql:534`）为真时，advance **跳过**续传臂（triage `:750-752`）。
- R3b：更老的 progress+signals 若没有 index+1 后继，`v13_harness_tail_gap` RAISE（`v13/control/v13_control.sql:196-223`）。禁止挑最近一条掩盖断链。
- 结果：新逻辑回合已经入队并被 complete 成 finish，旧 progress+repair 的 index+1 仍欠着。下一格不能 closeout，只能逃生 `v13_closeout(..., 'cancelled', 'cancel')`（`g_triage.py:173`）。

没有条文说「cap 已答则取消续传义务」，也没有说「先补 index+1 再铸新 id」。

## 5. 测试覆盖与复现

非交互 shell 不读 `~/.zshrc`。

```bash
source ~/.zshrc
export DEEPSEEK_API_KEY=$STEPFUN_API_KEY \
       OPENAI_API_URI=$STEPFUN_CODING_PLAN_API \
       OPENAI_MODEL=step-3.7-flash
uv run --project demo_v13 python demo_v13/parity/parity_all.py
```

`parity_all.py` 建一次 `agent_v13_parity`（stage 20），按 `g_steer` → `g_approval` → `g_cancel` → `g_unknown` → `g_closeout` → `g_spawn` → `g_worktree` → `g_triage` → `g_wake` 跑。单组可单独跑，会自建库。备用模型 `step-3.5-flash-2603` / `step-3.5-flash`。

W4 记录：`step-3.7-flash` 两连绿，编排器独立复跑 9/9，共三次全绿。本文件不复跑。每次 harness/llm 回合一次真实 StepFun 调用；`result_kind`、`tool_calls`、审批决定是脚本，不解析模型。

对照脚本覆盖的是改变桶的一部分，不是没实现桶。

| 脚本 | 证明的改变 | 只记观察、不当通过 |
|---|---|---|
| `g_steer.py` | F2 冻结信封、F10 未知 id 零插入、F15 水位 `stale`、L18 六键、L33 index+1 | F1 幂等续跑；F10 过期再激活 |
| `g_approval.py` | F11/F27 错 ref RAISE、零写、字节拷贝 | F4 静默 no-op |
| `g_cancel.py` | F9 `replay`、V26 扇出、V28 三档 | F3 四值 ACK；F5 shutdown |
| `g_unknown.py` | F28 / V3 / V4 拆墙 | F16 TTL；F25 claim |
| `g_closeout.py` | F14 / L14 / L15 收据重放与未付 | 无 commitID（已裁） |
| `g_spawn.py` | L34 席位、L35 零部分子、V23 直接求值 | L36 steward |
| `g_worktree.py` | F22 prepare→latch、V32 claim 跳过 | F23 不翻 `released` |
| `g_triage.py` | L37 的阶梯侧（V34–V40）、`repair_cap` 入队 | L32 指纹；第 10 条 tail gap |
| `g_wake.py` | V11 三变体、V22 nudge | L6 void；L21 RRULE；L26 should-run |

完全没实现的 F5/F8/F16–F21/F24–F26/F29/F30 与 L1–L7/L13/L16/L17/L19–L30/L32/L36/L38–L41 **故意没有通过测试**。套件若为它们写绿，就是在测一个不存在的函数。

stage 17–20 gate（`uv run python v13/<stage>/test_*.py`）覆盖 V1–V41 的 SQL 合同，用 fake，不覆盖本文的源对照，也不覆盖 §4 的未裁组合。

## 6. 残留与后续

R1–R13 是 D3 已记录的未做项。它们造成的对照缺口如下。不改台账。

| 残留 | 造成的对照缺口 | 与未裁的关系 |
|---|---|---|
| R1 `closeout/inbox_residual` 不写事件 | L15 的欠账只在收据 `unconsumed` 里 | 已裁不写（R3b）。不是未裁 |
| R2 无 `quota/spent`·`voided` | L6 整条没实现 | 已裁禁止写 |
| R3 `material_cap` human 不生产 | 超限 material 仍 RAISE。与第 10 条不是同一条：第 10 条的 `repair_cap` **会**生产 | 已裁 P4 不生产 `material_cap` |
| R4 无生产 worker 轮询 `v13_cancel_pending` | F3 没有进程内第四务。谓词有，循环没有 | 已知残留。套件直接调谓词（`g_cancel.py:47`） |
| R5 `children_terminal` 无 advance 生产者 | 套件直接调函数（`g_spawn.py`）或只测 nudge（`g_wake.py:114`） | 已知残留，不是新分叉 |
| R6 目录缝（D3 称 F22，**不是**本文 F22） | `spawn_subsession` 行保持 `enabled=false`；扇出走 `tool/call` 事件 | 台账已记「记录不改」。与 worktree F22 无关 |
| R7 `v13_needed_judgments` 旧谓词（D3 称 F20，**不是**本文 F20） | 不影响本文 F20（grant 类本来就没有） | 不升格 |
| R8 无 `pg_terminate_backend` | 与 A18「核心不杀进程」一致 | 不是缺口 |
| R9 不新增 G6 条文 | F3 的四值 ACK 没有 gate | 已裁不编 ch08 没有的断言 |
| R10 `thresholds.action` 仍 `pass\|reject` | triage 六值只在路由出口 | 已裁禁止 ALTER |
| R11 steer 正文未写 | F2 只保住冻结信封，没有消息正文 | 已裁 P1 不做 |
| R12 `artifacts.kind` 无 CHECK | `worktree_binding` 字面写入 | 不改变 F23 的未裁点 |
| R13 无「无条件让出」 | 无源功能对应 | 台账判伪缺口。不进对照桶 |

建议只把三件未裁送出去，不要把已裁项再开一轮：

1. **repair_cap × tail gap（优先）。** 会把一个已答的 fold 卡死，只能 cancel 逃生。需要一句排序：cap 已答是否免除续传义务，还是必须先补 index+1。这是 Oracle 或台账级，不是注释能收的。
2. **F23 latch。** 词表有 `released`，没有写入者。需要一句：`worktree_release` 成功是否 `v13_latch_fire(..., state=released)`，以及失败的 release 是否保持 `prepared`。适合短裁决，不必重开 A19。
3. **F4 静默 no-op。** **R5 已裁：不移植**（台账 F23）。C4 已经冻了 RAISE。native `removeValue` 静默返回不移植。

F9 的 `replay` 与 routed llm 的 `unsupported` 不要记成未裁。它们和源合同不同，但条文已经选择了 v13 侧的失败模式。
