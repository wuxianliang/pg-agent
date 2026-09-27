# v13 Phase C 开发计划：L2 治理投影（stage 26 should_run + stage 27 quota_window + stage 28 attention + stage 29 govern）— R13 终裁版 r42（最终版：40 轮双车道审核 + R13b/R13c 决胜，双通道 APPROVE）

> 状态：**终裁版 r42（最终版，可开工）**。r41 经 R13c 微裁（2026-09-27，stage 26 开工停工两冲突处置：A=`current_setting` 改差集断言（预存 statement_timeout 守卫保留）；B=小题⑥审计豁免双臂分阶段（负臂+源码在 26，正臂行为在 27）——双通道采纳，见 R13 记录 §4；未采纳分支未回填）。其余历史：r0→r40 经 40 轮双车道审核（grokBuild + codex；claude-fable 全程缺席经用户指示双通道收口）；第 40 轮双通道 APPROVE；R13b 决胜（小题③查 operator/小题⑥保留）。开工门槛 = Phase B 全绿（✓ 26/26）+ §9 复核 GO（✓ B1–B14）+ RED（L29）留证（✓）。
> 母计划：`docs/plans/v13-layered-control-roadmap-2026-09-26.md` §2.2 / §2.3 / §2.4 / §3 Phase C / §4 D9·D10·D15 / §5 红线。
> 前序：Phase A 已提交（末笔 `f59058d`）。Phase B 计划 = `docs/plans/v13-phase-b-workflow-verbs-plan-2026-09-26.md`（R8 终裁版 **r11**（最终版））。**Phase B 施工中（r6 时点）**：stage 23 acl（`d33eed9`）与 stage 24 observe（`7b0e53c`）已提交；stage 25 handoff 文件已在工作区、`SQL_LOAD_ORDER` 已注册 25 项（末项 handoff=25）但**未提交**。开工前以 §9 复核时点的仓库为准。
> 硬边界（不重开）：零新表零新列（含物化视图、投影表、概念缓存表，R4）；索引、只 RAISE 的守卫触发器、开放事件、STABLE/VOLATILE 函数不是新表；stage 1–20 SQL 文件字节冻结，行为变更只许后 stage `CREATE OR REPLACE`；events 是唯一干预通道；唯一推进函数是 `v13_advance`，不建第二运行时、不建 `v13_agent_run`；投影不授权（R1.5）；不把 `duty_cycle=0` 当成 L32；不写 `quota/spent|voided`；窗口时钟的**存储列**只用 `events.at`；外部 IO 不进事务；gate = `uv run python v13/<stage>/test_<name>.py` 退出码 0（Fake，不调真实 provider）；`SQL_LOAD_ORDER` 只在末尾追加。

§0.A–§0.D 是脚手架原文（Goal / Background / Open Questions / References），不删不减。可开工规格在 §1 之后；原文里的问号由 §1 给草案，**草案被 R13 改写时以裁决记录为准，实施者不当场另选替代项**。

## 0. 执行索引

验收读法沿母计划 §3 Phase C：性质组闭合 = 自动推进有唯一门（L26）/ 资格可从窗口重算且 ≠ 奖励（L6+L37+L38）/ 可停可复且停 ≠ cancel ≠ 删行（L32）/ 注意力与调度提示无副作用（L5+L21）。结算完备、不丢运行已在 stage 17–20；**不超售 = 无并发复活时成立（终态兄弟复活窗口是既有残留，处置随 §1.10 小题⑨裁定——裁定前不得把「不超售」标为已闭合，r20）**，本阶段不重做。

| Stage | 目录 | 交付 | Done when | 依赖 | 规模 |
|---|---|---|---|---|---|
| 26 | `v13/should_run/` | `v13_should_run_gate` + 布尔包装 `v13_should_run`；**`v13_policy_share`（五行策略锁 DEFINER helper，r35）**；策略行 `should_run`；`v13_advance` 与 `v13_triage_prework` 换体；`trg_sessions_parent_immutable`（小题⑧） | `test_should_run.py` 退出码 0 + 回归 1→25 全绿 + 收尾四件 | **D10-A、D10-B + 小题①⑥⑧**（r20 显式挂接：⑥ 决定 P-tail resolve/failed 行为、⑧ 决定守卫安装）+ Phase B 绿 + §9 GO；裁决前只许探针与文档 | 中 |
| 27 | `v13/quota_window/` | `v13_quota_eligible`；`v13_missing_capabilities`；策略行 `quota_window`、`capabilities`；换体 `v13_should_run_gate` 增加两个 block 门；`v13_material_time_honest` + `trg_material_time_honest`（r32）；窗口部分索引是否建由 L6 裁决 | `test_quota_window.py` 退出码 0 + 回归 1→26 + **小题⑥正臂行为验收（R13c-B）：quota/capability block id 存在、前缀三门不早退、duty<>0、snap.failed 非空、门假 → advance 先 append `resolve/failed` 随后 prework 单 gate 返 waiting、零新 effect、无 triage/hold** | **D9 已裁公式** + **L6 索引已裁（建）** + §1.9 残留已裁 + **D9-material-time 已裁①** + stage 26 | 中 |
| 28 | `v13/attention/` | `v13_spawn_budget_snapshot`（r7）、`v13_attention(p_root, p_max_rows DEFAULT 512)`（r13 签名定稿）、`v13_scheduler_hint(p_sid)`；三函数同事务 REVOKE PUBLIC + GRANT `v13_route` | `test_attention.py` 退出码 0 + 回归 1→27 | **L5 排序键裁决**（r29：R13 记录须显式记「采纳 L5 推荐即接受已披露边界——返回行数预算不限制 `v_goal_tree` 源遍历；或要求前移有界遍历（另裁）」）+ stage 26（加载序上亦在 27 之后，不并行改 `SQL_LOAD_ORDER`） | 小 |
| 29 | `v13/govern/` | `goal/stopped|resumed` + 守卫 + 恰一个部分索引；`v13_goal_fingerprint`；`v13_goal_lifecycle`；`v13_goal_stop` / `v13_goal_resume`；换体 `v13_should_run_gate`、`v13_recover_idle`、`v13_scheduler_hint`、`v13_advance`（L29）；`v13_attention` 增列用 DROP+CREATE（§1.7） | `test_govern.py` 退出码 0 + 回归 1→28 | **D15-A、D15-B、L29 + 小题②③④⑤⑦⑨⑩**（r20 显式挂接）+ stage 25 handoff 契约 + stage 26–28；裁决前只许探针与文档 | 大 |

收尾四件（每 stage 缺一不可，然后才按路径 commit）：该 stage `test_*.py` 退出码 0；回归当时加载序从 stage 1 到本 stage 的全部 gate；`SQL_LOAD_ORDER` 只追加本 stage 一项且 `STAGE_THROUGH` 同键同提交；覆盖矩阵追加行（不预写 ✅）、偏差台账只写 R13 **已分配**的号、该 stage `README.md` 更新。

加载序目标形状（r6 时点：25 项已注册（handoff=25 未提交，注册≠已绿）；本阶段不占 Phase B 的号）：

| 序号 | `STAGE_THROUGH` 键 | 文件 |
|---:|---|---|
| 23–25 | `acl` / `observe` / `handoff` | Phase B，本计划不创建、不改写 |
| 26 | `should_run` | `v13/should_run/v13_should_run.sql` |
| 27 | `quota_window` | `v13/quota_window/v13_quota_window.sql` |
| 28 | `attention` | `v13/attention/v13_attention.sql` |
| 29 | `govern` | `v13/govern/v13_govern.sql` |

台账：F27–F31 与 C15/C16 已由 R8 预分配给 Phase B，正文禁用这些号。Phase C 主题用临时标签 PC-1…PC-8（§10），**正式 F/C/X 号只在 R13 记录里分配**。覆盖矩阵现至 #51 的说法来自脚手架，开工时以矩阵文件末行续号，不重排。

### 0.A Goal（脚手架原文）

为路线图 Phase C（L2 治理投影，补齐 L26/L6/L38/L5/L21/L32/L27/L29，stage 26–29）撰写可开工的开发计划：全部落点为参数化 STABLE 投影 + 开放事件 + 策略行，零新表零新列（R4）；含 D10、D15 未裁题面与草案（送 Oracle R13）；并携带「Phase B 落地后复核指导」章，供 Phase B 施工结束后刷新本计划底稿。

### 0.B Background（脚手架原文）

#### 裁决链与文书定位

- R 链 R1–R12 已全占用，本计划审核轮 = **R13**（记录将落 `docs/reviews/v13-control-plane-oracle-r13-2026-09-27.md`）。三通道 = grokBuild grok-4.7-build-fast-xhigh / codex gpt-5.6-sol@xhigh / claude-fable-5@xhigh；终轮三通道全 APPROVE 才退出循环；每轮新洞折入计划新 revision（先例：Phase B 计划九轮 r0→r9，`docs/reviews/v13-control-plane-oracle-r8-2026-09-27.md` §5 审核轮勘误格式）。
- 覆盖矩阵 `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` 现至 #51；偏差台账 `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` 现至 F26/C14/X1，**F27–F31 + C15/C16 已由 R8 §2 预分配给 Phase B**——Phase C 的台账编号须在 R13 轮分配，不得撞号。
- 计划文书惯例（对齐 Phase B 计划骨架）：四行前言（状态/母计划/前序/硬边界不重开）；§0 执行索引（stage 表：目录/交付/Done when/依赖/规模）；§1 裁决面（题面→真值表→替代项表→生产绑定状态→裁决纪律）；§2 探针证据底座（file:line 活体锚点 + 开工当天重取义务）；各 stage 章（前置/SQL 语句序/Gate/收尾）；全局红线；假绿对照；**跨阶段复核指导**（B 计划 §8 即 Phase A→B 先例：绑定假设表/复核步骤/修订协议）；文件级影响与实施顺序；不做清单；References。
- 批判稿先例：`docs/reviews/v13-phase-b-plan-critique-2026-09-27.md`（处置注 blockquote + 身份声明 + 五节 + 抽查锚）。

#### 活体底座关键锚点（探针快照，2026-09-27；开工前须重取）

- **`v13_advance` 活体 = `v13/triage/v13_triage.sql:561-1000`**（stage 20 换体，加载序 control→spawn→fanout→triage 末位胜；seam/catalog 不再换体）。新 effect 入队全量点：`:737, :787, :811, :827, :842, :858, :889, :934(直插), :968, :970, :981, :986`；子会话派生点 `:648`（`v13_spawn_subsession`）+ `:653` 记账 INSERT。**spawn 批次（:626-662）与 harness 前驱（:664-798）在 duty 门（`v13_triage_prework` :800）之前**——L26「advance 入队前读」的插入位置是裁决题（见 Open Questions）。
- **`duty_cycle`**：非 sessions 列，是策略行 `('triage',1,'{"duty_cycle":1}')`（`v13_triage.sql:3-4`）；读取器 `v13_policy`（`v13/schema/v13_core.sql:731-740`，无 active 行 RAISE fail-closed）；封装 `v13_triage_duty()`（`v13_triage.sql:45-56`，值域 0|1）。消费者 1：`v13_triage_prework` `:372`（=0 → 写 `triage/hold {reason:'duty_cycle'}`（事件守卫 `:229-233` 只许该 reason）→ waiting → 零新 effect）；消费者 2：`v13_triage_hold_blocks_recover` `:553-560`。gate「duty_cycle=0 行为不变」= 这两处行为不得被 L26/L32 改写。
- **`v13_recover_idle` 活体 = `v13_triage.sql:1186-1247`**（覆盖 spawn:508-556 版，差异即 `:1213` duty hold 跳过）。谓词 `status IN ('ready','waiting')` 且无 ready/claimed/unknown effects（`FOR UPDATE SKIP LOCKED`）；nudge = `recover/nudge` 事件（`v13_insert_nudge` `v13/spawn/v13_spawn.sql:189-202`；`ux_events_recover_nudge` `:205-208` 幂等），三类 `children_terminal/repair/replan`；返回 `{pending, nudged}`，不入队不改 status。**L32「stop 后 recover 零 nudge」的最近似物 = `:1213` 这一跳过通道**。
- **路由与 L29**：`v13_route` 活体 = `v13/loop/advance.sql:110`（stage 3，从未换体），路由对象键集 `action/reason/tool/params`，**无** spawn_subsession 布尔键（parity 复核同记）。spawn 走批量路径：advance `:626-639` 聚合未认领 `tool/call` → `:648` 派生 → `:650-652` 合成 route 事件 `{action:'sql', reason:'spawn_fanout', tool:'spawn_subsession'}`。`v13_route` 直选 spawn 被 advance 硬拒（`:880-882`、`:909-911` RAISE `v13: spawn batch-dispatched`）；`v13_triage_after_route`（`:492-512`）triage direct 时改写 `{action:'human', reason:'triage_direct'}`。**到顶现状 = RAISE**：`v13_spawn_subsession` 前置 `:425-426` + 复检 `:456-457` `RAISE 'v13: spawn budget cap'`，掀翻整个 advance 事务；advance 侧派发前无占用预检。L29 = 语义翻转（到顶跳过不 RAISE）——跳过后未认领 `tool/call` 的处置是裁决题。
- **spawn_budget 席位**：策略行 `('spawn_budget',1,'{"max_nonterminal":8,"max_depth":4,"max_fanout":8}')`（`v13_spawn.sql:24-25`，恰三键 ≥1 整数 `:408-413`）；计数 `v13_spawn_occupancy(p_root)` `:159-188`（递归 CTE 数全部非终态后代，不含 root；环/深>64 RAISE）；检查点带咨询锁 `pg_advisory_xact_lock(v13_advisory_class('spawn_budget'), hashtext(root))` `:423`（类号 13001，`:32-41`）。`v13_triage_project` 也读该行写 `remaining_turns/quota_remaining/subtree_reserved`（`v13_triage.sql:145-153, 183-192`）。

#### 策略行与事件表机制事实

- **`v13_policies`**（`v13_core.sql:701-709`）：`name/version/value/active/updated_at`，PK `(name,version)`，部分唯一索引 ux one-active。冻结触发器 `:715-729`：DELETE 全拒；UPDATE 拦 name/version/value 改写、**只放 active 翻转**；**INSERT 新行无守卫（允许）**；既有翻版惯例 = 先 INSERT inactive 再双 UPDATE（`demo_v13/mem2_mgraph.py:126-142`）。`v13_policy(p_name)` STABLE 读 active 行 value，缺行 RAISE。`thresholds` 表全冻结（UPDATE/DELETE 拒 + INSERT 需 draft 父版本）——roadmap 已裁 `thresholds.action` ALTER 不做，Phase C 不碰。
- **events 表**（`v13_core.sql:28-43`，stage 1 后列未动）：`session_id/seq/event_id/type/turn_no/payload/payload_hash/source_effect_id/at`。**`at timestamptz DEFAULT now()` 是唯一时间列，`at` 上无索引**——D9「窗口时钟只用事件行已有时间列」的承重事实；窗口时钟先例：`v13/economy/v13_economy.sql:140-156` `v13_recovery_active` 已用 `events.at` 作 user/message 边界。现有 events 索引 10 个（**9 个部分索引** + 1 个普通索引 `ix_events_source_type`，control `:409`；`ux_events_material` 是其中之一）+ append-only 触发器（UPDATE/DELETE 全拒 `:57-59`）；INSERT 守卫全部 WHEN 限定型，新 type 默认只受 append-only 管。母计划 §4 对 D15 的「允许部分索引」仍是**倾向**（`不开工就停 = 是`，未标 R4 已裁）；部分索引进不进 stage 29 / stage 27，仍是 §1 草案。
- **spent 收据**：`turn/material_spent` payload 恰 `{schema_version, effect_id}`（`v13/control/v13_control.sql:443-446`），`source_effect_id` NOT NULL，每 (session, source effect) 至多一条（`ux_events_material`）；advance ⑤ 写入点活体 `v13_triage.sql:693-698`。**不存在 `turn_spent` 类型；`quota/spent|voided` 未实现（保持永不建）**。聚合 `spent` 只在 closeout 收据 payload（`v13_spawn.sql:760-769, 784-785`），全会话累计非窗口。

#### 读面函数惯例与两把既有尺子

- **读面五惯例**（stage 20/21 后定型）：SECURITY INVOKER 默认；新读面固定 `SET search_path = pg_catalog, public`（triage/seam 系均有，stage 17 control 系旧面无 SET 不回改）；每 stage 尾部一个 GRANT 块（REVOKE FROM PUBLIC → GRANT 最小角色，读面通常只授 `v13_route`，先例 `v13/seam/v13_seam.sql:665-680` + `test_seam.py:384-388` ACL 断言）；常规读面**不加 COMMENT**（文档职责在 README + SQL 头注释）；零写入。
- **`v_goal_tree`**（L5 的输入）：`v13_spawn.sql:467-506`，参数化 STABLE SRF，`p_root uuid` → 7 列 `(session_id, parent_session_id, depth, status, spawn_kind, turn_no, is_terminal)`；unknown root/环/depth>64 RAISE（文案 `v13: unknown session`（无插值，`:479`）/ `v13: goal tree cycle`（`:488`）/ `v13: goal tree depth`（`:492`））；root 自身 depth 0 入集；`is_terminal` 闭集 completed/failed/cancelled。
- **`v13_state_hash`**（L32 的指纹）：`v13_control.sql:362-400`，STABLE 按需计算；材料 `['v1', header, effects, events]`，events 行排除名单**仅三个 `session/*` 终态收据**（`:390`）——**`goal/stopped|resumed`（及 `control/handoff`）不在排除名单**，新增事件会改哈希 → L32 resume 比对基准存在「自激」问题（B 计划 transcript_hash「收据自身排除防自激」的同款镜像，见 Open Questions）。唯一落库点 = closeout 收据 `state_hash` 键（守卫强制 8 键，`v13_control.sql:460`）。
- **pg_cron**：stage 库未装；既有惯例 = `CREATE EXTENSION IF NOT EXISTS` 包守卫 DO 块失败降级 NOTICE（`v13/chunks/v13_chunks.sql:1136-1153`、`v13/memory/v13_memory.sql:213-228`，`cron.database_name` 闸），测试两分支（有则查 `cron.job`，无则断函数手动可调）。stage 28 的 hint gate 应循此惯例（以 §1.7 为准：本阶段**不**装扩展、**不**注册 job，仅保留 `cron.job` 两分支断言）。
- **`SQL_LOAD_ORDER`**（`v13/load.py:17-40`）：现 24 项（…20 triage、21 seam、22 catalog、23 acl、24 observe；**r3**：acl/observe 已随 Phase B 施工提交，手架快照时为 22 项）；Phase B 将追加 25 handoff；Phase C 追加 26 should_run/27 quota_window/28 attention/29 govern；`STAGE_THROUGH` 注册 name→序号。

#### Phase B 交接面（本计划的输入契约，已冻结勿重开）

- stage 25 交付 `handoff_policy` 策略行 `('handoff_policy',1,'{"schema_version":1,"enabled":true}',true)`、`control/handoff` 事件（信封恰四键，身份去重幂等，DEFINER 单写者 `v13_handoff_owner`）、`v13_transcript_hash`（材料排除 `type<>'control/handoff'` 防自激）——stage 29 的 L27 只**消费**该契约（`handoff_policy` 缺/禁则拒），不复制不重述（唯一住所 = B 计划 §1.2/D16/R8）。同身份重放在策略检查之前返回原载荷（B 计划 §1.2/§5.3）。
- stage 23 将 overload `v13_cancel`/`v13_complete`（human 分支）并新增 `v13_control_authorized`/`v13_control_operator`——**会改变 C 计划引用的活体函数形状**，故本计划须携带「Phase B 落地后复核指导」（绑定假设表/复核步骤/修订协议，镜像 B 计划 §8 对 Phase A 的先例）。

### 0.C Open Questions（脚手架原文）

1. **D10-A（门位置）**：`v13_should_run` 读点插在活体 advance 哪个位置？spawn 批次（:648）与 harness 前驱（:664-798）在 duty 门之前——「入队前读，假则零新 effect」若只挂 prework 位则 spawn 批次漏管；若挂会话锁后最前则 human approval/收尾路径是否也该被拦？硬序 `human > unknown > cancel > duty_cycle=0` 的「>」语义（优先级=豁免？顺序=判定序？）需定形。
2. **D10-B（策略行形状）**：should-run 序住策略行的 name/键集草案（`quota_window` 行 `{window_hours, slot_minutes, allowed}` 已由 D9 给形；序行与能力集行的形状未写）。
3. **D15-A（指纹自激）**：resume 比对基准——`goal/stopped` 事件会进 `v13_state_hash` 材料（不在排除名单）；比对「stop 时记录的指纹」需排除停/复自身（参照 B 计划 transcript_hash 的收据自身排除），还是比对「stop 前最后哈希」？指纹存停事件的 payload 键名？
4. **D15-B（事件守卫与索引形状）**：`goal/stopped|resumed` 守卫（参照 `triage/hold` 守卫只许固定 reason 的先例，`:229-233`）允许谁写（open INSERT 还是具名函数）；部分索引形状（`(session_id)` WHERE type IN … 取最后一条的查询形）；「最后一条事件赢」折叠唯一函数体 `v13_goal_lifecycle` 的签名与返回形状。
5. **L29 到顶语义翻转**：从 RAISE `v13: spawn budget cap` 改为「路由不选 spawn（键缺席，不发空对象）」——advance `:648` 前预检失败后，未认领 `tool/call` 留置还是改写？`spawn_fanout` route 事件（`:650-652`）写不写？与 `:880-882` 硬拒、「策略不允许」的判定源（`handoff_policy` 之外还有哪个策略行）需定形。
6. **L6 性能**：窗口计数扫 `turn/material_spent` WHERE `at >= …` 无索引——是否加部分索引（非新表，但须进 SQL 序与裁决面说明）。
7. **L5 rank 序义**：`v13_attention(root)` 输出列 `attention_rank` 的排序键草案（roadmap 只说「只作输出列」未给序）。

### 0.D References（脚手架原文，§12 追加后序文献，不删本表）

- 母计划：`docs/plans/v13-layered-control-roadmap-2026-09-26.md`（§2.2 L2 分诊、§2.3 机制落点、§2.4 公共读面、§3 Phase C 表、§4 D9/D10/D15、§5 红线）
- Phase B 计划：`docs/plans/v13-phase-b-workflow-verbs-plan-2026-09-26.md`（**r11**（最终版）；§1.2 = D16/handoff 契约唯一住所；§8 = 跨阶段复核指导模板）
- 裁决链：R4 `docs/reviews/v13-control-plane-oracle-r4-2026-09-26.md`（表达形式：函数不进表/VIEW）；R8 `docs/reviews/v13-control-plane-oracle-r8-2026-09-27.md`（三通道惯例、台账预分配）；R3 链与迁移 §2.6（L26/L5/L21 语义源）
- 迁移调查：`docs/analysis/v13-control-plane-migration-2026-09-25.md` §2.6/§3；谱系文：`docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md`
- parity：`docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md`

### 0.E 现状分析（在原文之上收束；实施读这节 + §2，行号一律当 2026-09-27 快照）

**（观察）** 活体推进函数在 `v13/triage/v13_triage.sql` 的 `v13_advance(uuid, jsonb)`，因为 `v13/load.py:15-37` 把 triage 排在 spawn 之后，两文件都 `CREATE OR REPLACE` 了 `v13_advance`，后加载者胜。spawn 文件里的同名函数没有 triage 调用，**禁止当底稿**。底稿获取方式只许开工当天 `pg_get_functiondef`，按**语句**定位，禁止按 fanout/spawn/triage 行号回贴（Phase B 已有同一教训）。

**（观察）** 提供的 triage 活体在 stale 返回之后、读 `sessions.status` 之前调用 `v13_bind_worktree_from_prepare`。seam/catalog「不再换体 advance」是脚手架结论，不是本文件重新证明的事实。§9 用 dump 是否仍含 `v13_triage_prework` 与这一调用来证伪。

**（观察）** 会话锁之后的控制序（triage 活体）：快照错配 RAISE → `sessions FOR UPDATE` → probe 不一致则 `'stale'` → worktree bind → 终态 `'terminal'` → unknown 墙（可取消 ready effects）→ 未消费 cancel（可 closeout `'terminal'`）→ 已有 ready/claimed 则 `'waiting'` → 聚合未认领 `tool/call`（约 `:631-642`）→ **`v13_triage_block_explore_spawn`（`:643`，在 spawn IF 之外：待派发调用属 explore 路由即 RAISE `v13: explore spawn`）** → spawn 批次 IF（`:644-662`）：可能 `v13_spawn_subsession` + 写 `turn/route` `spawn_fanout` + INSERT `succeeded` effect + `tool/result` + `'progressed'` → harness 前驱（含 `turn/material_spent` 的存在则跳过、否则追加；finish/reject closeout；wake；approval 入队；continuation 入队）→ `v13_triage_prework` → abandon / context_refresh / turn_budget / judge → `v13_triage_steer` → `v13_route` → `v13_triage_after_route` → spawn/harness 硬拒 → `CASE` 入队或内联 INSERT。

**（推断）** 「入队前」不能是单一早退，也不能只挂在 prework。只挂 prework 则 spawn 批次与 harness 入队已经发生（观察：这两段在 `v13_triage_prework` 调用之前）。挂在会话锁后最前则会挡住 cancel closeout、unknown 墙、在途 human 的早退，以及 harness 的 material 收据和 finish/reject closeout。母计划硬序 `human > unknown > cancel > duty_cycle=0` 与「假则零新 effect」同时成立的读法是：前缀结算保持原样，投影只包住**新 effect 的创建**。这是 §1.1 草案，不是已裁。

**（观察）** `duty_cycle=0` 的零新 effect 范本在 `v13_triage_prework`（`v13_triage.sql:359-397` 一带，duty 分支锚 `:372`）：`v13_triage_duty()=0` 时若本 user turn 尚无 `triage/hold`，经 `v13_triage_emit`（`:194`）写 `reason='duty_cycle'`，然后 `UPDATE sessions SET status='waiting'` **带 `WHERE status IN ('ready','waiting')`**（`:381-382`），`RETURN 'waiting'`（`:383`）。同一函数在 duty 之前还有 `reject` → park 或 `v13_closeout(...,'failed','triage_reject',...)`。`v13_triage_hold_blocks_recover` 为真的条件是 duty 仍为 0 **且** 最近 `triage/hold` 的 seq **大于** `v13_last_user_seq`。因此 duty hold 是**本 turn** 的暂停；新的 `user/message` 会使 recover 重新放行。L32 若复用这条 turn 水位，一条用户消息就会把「停」洗掉。

**（观察）** `v13_route`（`v13/loop/advance.sql` 函数锚 `:110`）只返回 `finish|reject|human|sql|tool|llm`，键为 `action/reason` 加可选 `tool/params`。它没有 spawn 动作。spawn 只走 advance 批量路径；若 route 仍返回 sql+`spawn_subsession`，advance 两处 `RAISE 'v13: spawn batch-dispatched'`。`v13_triage_after_route`（`:492-512`）只改写**这条 route 返回值**，不改批量路径。

**（观察）** `v13_spawn_subsession`：fanout（`:417-419`）与 depth（`:420-422`）检查在咨询锁（`:423`）**之前**，cap 前置（`:425-426`）与复检（`:456-457`）在锁内。`requested > max_fanout` → `v13: spawn budget fanout`；`depth+1 > max_depth` → `v13: spawn budget depth`；`occupancy+requested > max_nonterminal` → `v13: spawn budget cap`；插入后再查一次 occupancy，超过仍 `spawn budget cap`。RAISE 使整个 advance 事务回滚。`v13_advisory_class('spawn_budget')` 返回整数 `13001`（`:32-41`）。

**（观察）** `v13_triage_project` 把 `max_nonterminal - occupancy` 同时写进 jsonb 的 `remaining_turns` 与 `quota_remaining`。这是席位余量，不是 L6 的时间窗。Phase C 不读、不写、不换体这个函数去「接入配额」。

**（观察）** `events.at` 存在且是该表唯一时间列；`at` 上没有索引。`v13_recovery_active` 用 `events.at` 做 user/message 边界，比较对象是 `effects.created_at`，窗口单位是「最近 N 个 user turn」不是 `window_hours`。append-only 触发器拒绝 UPDATE/DELETE。`v13_policies_frozen` 拒绝 DELETE 与 value 改写，允许 INSERT 与 `active` 翻转。

**（观察）** `v13_state_hash` 的 events 排除名单只有 `session/completed|failed|cancelled`。任何新 type 都会改变哈希。closeout 收据把该哈希放在键 `state_hash`。Phase C 不 `CREATE OR REPLACE v13_state_hash`（草案 §1.3 若被 R13 推翻则此句随之改）。

**（观察）** 活体 `v13_advance` 的函数头没有 `SET search_path`（triage 文件中的 `$function$` 体）。`v13_triage_prework` 有 `SET search_path = pg_catalog, public`。换体必须保留 dump 的 owner / prosecdef / provolatile / proconfig / 参数默认值，插入点用 `public.` 限定调用。禁止对换体函数 `REVOKE ALL`（OR REPLACE 保留 ACL）。

**（推断）** Phase B 计划明确不换体 `v13_advance`。若 §9 dump 仍以 triage 体为底（外加文件里已有的 worktree bind），stage 26 的差集相对这份 dump 只增加 §3.2 的块。若 Phase B 或未记载的 seam 换体改了准入语义，停工，不把 C 的读点夹进一份看不懂的底稿。

五机制落点（母计划 §2.3，本阶段没有第六个）：

| ID | 机制 | 对象 |
|---|---|---|
| L26 | 投影 + 推进函数上的读 | `v13_should_run`；advance 入队前读；函数本身不入队、不 closeout |
| L6 L38 | 投影 | `v13_quota_eligible`、`v13_missing_capabilities`；由 L26 的 block 门消费 |
| L5 L21 | 投影 | `v13_attention`、`v13_scheduler_hint`；零写入 |
| L32 L27 | 事件 + 策略行 | `goal/stopped\|resumed`；`handoff_policy` **只消费** Phase B 已写的门 |
| L29 | 推进函数 | 批量派发在到顶时不调用 `v13_spawn_subsession`；不改 `v13_route` 的返回词表 |

stage 26 **不**写停/复查询，**不**调用尚不存在的 `v13_goal_lifecycle`。stage 29 再换体 `v13_should_run_gate` 与 `v13_recover_idle`。这是母计划 stage 表的硬依赖，不是实施者可提前合并的优化。

## 1. 裁决面（Oracle R13）

### 1.0 纪律与三车道分歧一览

- 通道：grokBuild `grok-4.7-build-fast-xhigh` / codex `gpt-5.6-sol@xhigh` / claude-fable-5 `@xhigh`。终轮三通道都 APPROVE 才退出。每轮新洞折进本文件新 revision，不另开平行计划。记录文件：`docs/reviews/v13-control-plane-oracle-r13-2026-09-27.md`（若裁决日不是该日，文件名跟裁决日，本计划改一处指针）。
- 下面每题的「草案推荐」是送裁文本。实施者在裁决前不开工；裁决否决某推荐项时停在该 stage，不就地改用替代项。
- 已裁且本轮不重开：R4 的表达形式（函数/SRF，禁止 VIEW、物化、投影表、概念缓存表）；D8（`goal_id = session_id`，无 registry）；D9 的公式骨架（策略行窗口 × 窗内 `turn/material_spent` 条数，过期滑出窗口，不写 void，无负债，不够则 should-run 为假）；R8 的 F17/F29 合同；R3 失败模式（终态 cancel 仍 `replay`、C4 RAISE、routed llm `unsupported`）。
- D10、D15 在母计划 §4 的「不开工就停」为是，且**没有**「R4 已裁」标记。stage 26 等 D10；stage 29 等 D15。D9 公式已裁，但 `slot_minutes` 语义、部分索引、种子松紧、计次是否含子树是 §1.9 残留，stage 27 等这些残留落裁。
- 生成本稿的三车道在以下七点**实质分歧**（本稿草案取 grokBuild 完整稿立场，codex 两残稿的反对意见已入对应替代项表；R13 对这七点必须显式落裁，缺一不得 APPROVE）：
  1. **D15-A**：新指纹函数（草案）vs 换体 `v13_state_hash` 扩排除名单（codex 两残稿均主张）→ §1.3 替代项 1。
  2. **D10-B**：`gates` 数组带 block|shadow 执法位（草案）vs `order` 数组 + `enabled` 总开关 + `deny_action` 键、硬门定死在代码（codex 残稿）→ §1.2 替代项表末行。
  3. **窗口时钟**：`transaction_timestamp()` 单次捕获 + 保持 STABLE（草案）vs 窗口末端取最新事件 `at`、禁用墙钟（codex 残稿）vs `clock_timestamp()` + VOLATILE（子点）→ §1.9。
  4. **stopped → hint 映射**：`dont_notify`（草案）vs `wait`（codex 残稿；停可复，视为暂态）→ §1.7 替代项表末行。
  5. **hint 在途 effect 映射**：`wait`（草案）vs `dont_notify`（codex lane 3；与第 4 点同为该残稿的两处反转）→ §1.7 L21-alt-busy-dont-notify。
  6. **L5 排序**：草案 CASE vs 迁移 §2.6 R1 序 vs codex 序三序并陈；且草案秩与 §1.2 门数组短路序在 duty↔quota 相对位置相反（是否要求同序一并裁）→ §1.7。
  7. **cap-defer**：整段提前返回（§1.5 草案，不进 harness 段）vs「结算先行」变体（有 finish 前驱时先结算再返回，须重新定义先后）。
- 生产绑定分两格，写进各 stage README。SQL gate 绿只填「合同已证明」那一格。

| 题 | 合同已证明（仓库内 SQL+测试） | 未交付（不得写进验收句） |
|---|---|---|
| L26 | advance 换体后，假分支在库内生效，不依赖 driver 传参 | 无。与 F17 不同，读点在 `v13_advance` 体内 |
| L21 | `v13_scheduler_hint` 可重复调用且零事件；advance 自己会再读 should-run | 仓库不注册 `cron.job`。验收句禁止写「pg_cron 已在生产调度」 |
| L32 | `v13_goal_stop` / `v13_goal_resume` 对 operator 可调用 | 无产品按钮、无 driver 绑定。禁止写「目标已可在 UI 停复」 |
| L29 | 对**非 explore** 的批量派发预算拒绝路径，无并发复活时返回 `waiting` 且不 RAISE（r27 补例外：explore 误用仍由先行的 `v13_triage_block_explore_spawn` 抛 `v13: explore spawn`——小题①）；终态兄弟被 `user/message` 复活的窗口不承诺零 RAISE、也不承诺绝对不超售，见 `test_revive_race_backstop`） | `v13_spawn_subsession` 直调仍 RAISE。禁止写「spawn 函数已不再报 cap」 |

### 1.1 D10-A 门位置与 `>` 的语义

**题面。** `v13_should_run` 在活体 advance 的哪一层阻止新 effect。spawn 批次与 harness 前驱都在 `v13_triage_prework` 之前（**观察**，脚手架锚 `:626-662`、`:664-798`、`:800`）。`human > unknown > cancel > duty_cycle=0` 的 `>` 要定成判定序、豁免，还是 advance 前缀已经占有的执行权。

**草案推荐：三个读点，一个函数，布尔不缓存；`>` = 策略数组上的短路判定序；duty 默认不改写活体 spawn。策略线性化（r33 提出；**r34 改 DEFINER helper——`SELECT ... FOR SHARE` 需 UPDATE 权而 route 对 `v13_policies` 只有 SELECT（第 14 轮同型 P0 勿重犯）**）：新增 VOLATILE **SECURITY DEFINER** `v13_policy_share()`，OWNER=`v13_spawn_owner`（已有表级 UPDATE），`SET search_path = pg_catalog, public, pg_temp`，体内业务名全限定；**五行统一锁集（r35；**r36 修身份漂移——codex[35-1]：锁查询带 `active` 谓词时，翻版事务先灭旧行再启新行、helper 在旧快照选中旧行并等待；提交后 EvalPlanQual 重验跳过旧行，本语句看不见新 active 行即**空手返回未锁当前版本**，线性化失效）：helper 体 = **循环**{①快照读五名当前 active 的 `(name, version)` 身份；②按固定序对这些**精确身份**（`WHERE name = ? AND version = ?`，**不带 active 谓词**）`SELECT ... FOR SHARE`——`name IN ('capabilities','quota_window','should_run','spawn_budget','triage') ORDER BY name`（真实字母序；缺行跳过不 RAISE——gate 自报缺行文案）；③新语句重读 active 身份，与①相等则返回，不等则重试}；REVOKE PUBLIC，只 GRANT `v13_route`；禁止把 `v13_policies` 的 UPDATE 授给 route**。`v13_spawn_batch_allowed` **复用同一 helper**（咨询锁前调用——FOR SHARE 可重入；删「spawn_budget 由 batch_allowed 自锁」）。统一锁序：**session/root → 五行 policy_share → advisory lock → snapshot**（一切路径含 route 直调 wrapper）。stage 26 的 advance 换体在**前缀早退（终态/unknown/cancel/ready-claimed）之后、explore guard（`:643`）之后、`v13_spawn_children` 之前**无条件调用（`v_calls` 为空也调——stage 27 不换体 advance 即可锁到新引入的策略行）；stage 29 换体不得删此调用。**锁协议范围（r39 收口，codex[38-3]）：本协议只覆盖 Phase C 五个治理策略行（`capabilities/quota_window/should_run/spawn_budget/triage`，均由 `v13_policy_share()` 按 name 字母序锁定，wrapper 不自锁任何策略行）；`turn_budget`、`effect_attempt_cap` 等其余策略**不在本协议内**（其翻版竞态如实记录为残留，不承诺线性化——README 同文）；翻版事务多行 UPDATE 必须同序（README 写明 + 跨连接等待 gate：A 持 advance 事务不提交、B 的灭活 UPDATE 在 `pg_locks` 阻塞、A COMMIT 后 B 才成功；乱序翻版不受理）**。gate：route 直调 helper 不 42501；advance 源码 helper 在任一 `v13_should_run` 之前。**

读点（相对 dump 的语句锚，不是行号）：

| 标签 | 锚 | 假时行为 |
|---|---|---|
| P-spawn | `jsonb_array_length(v_calls) > 0` 为真之后、`v13_spawn_subsession`（含其前奏 `v13_spawn_children`，按 dump 实名）**之前**——r6 钉死：读点必须在 `v13_spawn_children` 之前，否则坏形状 RAISE `v13: spawn args` 会落在门后、不在 explore 例外集。与 `v13_triage_block_explore_spawn`（`:643`，聚合之后、spawn IF 之外）的先后**已定（r31 收口）：explore RAISE 保持在门之前，是 `should_run=false` 假路径的唯一例外**——explore 路由的 tool/call 在投影为假时仍 RAISE `v13: explore spawn`，不返回 `'waiting'`；门优先分支已否决（R13 记录） | 不调用 `v13_spawn_subsession`，不写 `spawn_fanout`，不 INSERT effect；**先执行 `UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid AND status IN ('ready','waiting')`（r8：必须带 `session_id` 谓词——不带会误伤全部会话；与 P-harness/P-tail 假路径同谓词，不写 `triage/hold`、不 closeout），再 `RETURN 'waiting'`**（不设旗标、不落入其后 harness 段——否则其后的 finish/reject closeout 会把父会话终态，留置的 tool/call 永不再派发） |
| P-harness | 包住两臂整体，从**臂首**起：approval 臂从其内部 `budget_exhausted` closeout 之前起——门假时该 closeout **随臂跳过**（它是「周期预算耗尽→失败」的新决策不是结算）；continuation 臂从 `IF v_cont` 臂首的 `cycle_no >= max_cycles` budget closeout 之前起（r4：该 closeout 在 `:777` route 之前、与 approval 臂对称）。material 收据、finish/reject `v13_closeout`、wake 记录、未满足 wake 的 `'waiting'` **在判断之前，不包进门**（真结算） | 不入队、不 closeout budget_exhausted；执行 `UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid AND status IN ('ready','waiting')`（r9：与 P-spawn 同句）；`RETURN 'waiting'` |
| P-tail | 换体 prework：`reject` 分支与 `duty=0` 分支保持现在的先后与副作用；**检查位置（r34/r36 定稿）= duty 的 `RETURN 'waiting'` 之后、`IF v_dec='human'` 之前，恰一处无条件 gate**（`v_reason := v13_triage_fold_reason(...)` 留原语句位不提前——gate 假立即 `RETURN 'waiting'`，不调用 fold_reason；与步 5 同文）——假时同句 UPDATE + `RETURN 'waiting'`，则 `v_dec` human/decompose、`v_reason` repair/replan_cap 三条入队出口**与无入队的 `RETURN NULL` 路径**全部被拦（RETURN NULL 不可达 → abandon/context_refresh/budget/judge/steer/route 亦不可达——**不再需要「advance 体内另有 P-tail 检查」，删除该句，单一 gate 不两套并存**） | 假 → `UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid AND status IN ('ready','waiting')` + `RETURN 'waiting'`，**不写 `triage/hold`** |

`>` 的定义（草案）：

- 它是 `should_run` 策略 `gates` 数组的从左到右短路：**第一个 `effect=block` 且条件成立的门获胜**，函数返回该门 id；布尔包装为「获胜 id 为空」。
- 它不是「human 入队豁免配额」，也不是把 advance 前缀重排到 spawn 之前。
- `human_pending`、`unknown_wall`、`unconsumed_cancel` 的**副作用执行权**留在 advance 前缀（早退 / closeout / 墙）。投影把它们算进布尔，供直接调用、attention、hint 使用。advance 在前缀之后才读投影，因此这些门的假**不会**把 cancel closeout 改成 `'waiting'`。
- `duty_cycle` 的**副作用执行权**只留在 `v13_triage_prework` 与 `v13_triage_hold_blocks_recover`。种子里该门 `effect=shadow`：条件成立只供将来的 reason 函数扩展，**不把布尔变成假**。因此默认 `duty_cycle=0` 仍会先 spawn（活体就是 spawn 在 prework 之前，**观察**），然后才写 `triage/hold`。把 shadow 改成 block 必须是新策略版本，且只改变「投影参与之后的新 effect」，不搬移 hold 的写入者。

假路径的返回语义（一旦读点真正看见假；默认种子下 P-spawn 要等 shadow→block 的测试版本或 stage 27 的配额门才看得见）：

- advance 返回词仍只是 `'stale'|'terminal'|'waiting'|'progressed'`。假路径是 `'waiting'`。
- 该次调用创建的 effect 行数为 0（相对读点之后；读点之前的前缀可以取消 ready 行，那不是新 effect）。
- 不 closeout，不新增 `sessions.status` 值，不写第二套 hold 事件。
- prework 之后的 `resolve/failed` 记账事件（`:803-808`，事件非 effect）= **门前审计例外（R13b 已裁：保留）**——它是事务外已发生失败的唯一落库行，且「重取 snap」合同带不回 failed 字段（压掉即永久丢失）。施工形：advance 在**调用 prework 之前**，仅当 `v13_triage_duty()<>0 AND NOT v13_should_run(p_sid) AND snap.failed IS NOT NULL` 时先按原载荷 append 该事件，随后由 prework 单 gate `RETURN 'waiting'`（仍零新 effect）；duty=0 不预写（沿用活体吞掉——duty 分支行为不变）。
- 投影函数零 INSERT/UPDATE/DELETE。

结算仍发生的正例（用来钉住「门没有包住前驱」）：应 `finish` 的 harness 前驱在投影为假时仍 closeout `'completed'` 并返回 `'terminal'`。未消费 cancel 在投影为假时仍走前缀 closeout，返回 `'terminal'`。（两正例的夹具均无未认领 tool/call——有 tool/call 的轮次在 P-spawn 已提前返回，到不了 harness 段。）

**影响面。** stage 26 换体 advance 与 prework；stage 27/29 只换 `v13_should_run_gate` 的门实现与策略版本，不再搬读点。stage 29 的 L29 在同一 P-spawn 读点扩预算预检（ELSIF 分支，§1.5），不新增读点、不设旗标。hint 与 attention 读布尔和获胜门 id，不另写一套序。

**生产绑定。** 读点在 `v13_advance` 内，合同证明即生产路径生效。driver 不能用 hint 跳过 advance 内部的再读（§1.7）。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| D10-A-alt-prework-only | 只在 `v13_triage_prework` 入口读 | spawn 与 continuation 漏管（**观察**：二者在 prework 之前） |
| D10-A-alt-earliest | 会话锁之后、terminal 之前一次早退 | 挡住 cancel closeout、unknown 墙、在途 ready/claimed，并把 material 收据与 finish closeout 一起跳过 |
| D10-A-alt-reorder | 大重排，使所有新 effect 落在唯一 `IF` 之后 | 差集不再可审；duty=0 与 spawn 的相对顺序会被无意改掉。否决后才许改「差集断言」 |
| D10-A-alt-human-exempt | block 门不适用于 `kind=human` 的新入队 | 会让配额耗尽时 triage 仍创建 human effect，布尔不再是唯一门。在途 human 已由前缀保护，不必再豁免「尚未创建」的 human |
| D10-A-alt-cache | 进入 spawn 前算一次布尔，后面复用 | `turn/material_spent` 写在 harness 段中部（**观察**，锚 `:693-698`）。缓存会让同一 advance 后半段看不见刚写下的收据。plpgsql 里每次单独的 SQL 调用会看到本事务已写行；必须现查 |

### 1.2 D10-B 策略行形状与门闭集

**题面。** 序住哪一行、键集、门 id 闭集、block 与 shadow 如何编码，使「改序 = 新版本、不改函数体」对**已实现**的门成立。新门的实现仍要换体（stage 27、29）；这不违反该口号，口号约束的是顺序与 block/shadow，不是闭集扩张。

**草案推荐。**

策略名 `should_run`。种子 version 1、`active=true`：

```json
{
  "schema_version": 1,
  "gates": [
    {"id": "human_pending", "effect": "block"},
    {"id": "unknown_wall", "effect": "block"},
    {"id": "unconsumed_cancel", "effect": "block"},
    {"id": "duty_cycle", "effect": "shadow"}
  ]
}
```

- 顶层键恰为 `gates`、`schema_version`（`v13_json_keys` 字母序，control `:102`）。`schema_version` 为 JSON 整数 1。
- `gates` 是数组，**顺序即判定序**。禁止用 jsonb 对象当序（对象键会被重排）。
- 元素键恰为 `effect`、`id`。`effect` 只许 `block|shadow`。
- 闭集（stage 26 函数会实现的 id）：`human_pending`、`unknown_wall`、`unconsumed_cancel`、`duty_cycle`。
- stage 27 换体后闭集增加 `quota_window`、`capabilities`。stage 29 再增加 `goal_stopped`。当版函数见到未实现 id、重复 id、空 id、未知 effect → `RAISE 'v13: should_run gate'`，零写入。
- 缺行、顶层键不对、`gates` 不是数组、元素不是对象 → `RAISE 'v13: should_run policy'`。直读 `v13_policies`，**不**调用 `v13_policy()`，避免把策略名嵌进 `v13: no active policy row for %`。
- 空数组合法：投影侧没有 block 门（前缀与 duty 副作用仍在）。这是运维显式选择。
- 未知会话：`RAISE 'v13: unknown session %'`，与 `v13_triage_project` 同形。不读 `sessions.status`，终态会话也可以得到「投影未阻塞」的真（终态短路由 `v13_unconsumed_cancel` 自身的 `status NOT IN` 终态谓词（control `:131-141`）与 unknown 谓词承担，不靠读 status 列）。终态早退留在 advance。

条件（每个 id 只有这一处定义）：

| id | 条件为真 |
|---|---|
| `human_pending` | `v13_pending_human(sid)` 为真（**观察**：control `:121`，该函数即 ready/claimed 的 human EXISTS） |
| `unknown_wall` | `sessions.status='blocked_unknown'` 或存在 `effects.status='unknown'` |
| `unconsumed_cancel` | `v13_unconsumed_cancel(sid)`（control `:129`） |
| `duty_cycle` | `v13_triage_duty()=0`。策略坏时让 `v13_triage_duty` 原样 `RAISE 'v13: triage policy'` |
| `quota_window` | stage 27：`NOT v13_quota_eligible(sid)` |
| `capabilities` | stage 27：`v13_missing_capabilities(sid)` 至少一行 |
| `goal_stopped` | stage 29：`v13_goal_lifecycle(sid)='stopped'` **AND sessions 非终态**（r2：终态优先——stop→cancel→closeout 后投影不得仍报 stopped；这是闭集中唯一读 sessions.status 的门，写明例外理由；attention 经 gate 自动同口径，hint 分支 1 终态在前已一致） |

短路：**入口序（r15）**——先 `EXISTS (SELECT 1 FROM sessions WHERE session_id = p_sid)`，不存在即 `RAISE 'v13: unknown session %'`（不读 status、不调 `v13_triage_duty`——否则未知 uuid + 坏 triage 策略会先报 `v13: triage policy`）；然后**两阶段处理**——第一遍完整校验数组（顶层键、元素形状、闭集、id 唯一与非空），第二遍才按序求值：遇到第一个条件为真且 `effect=block` 的元素即返回该 id，后面的门不再算；shadow 为真时继续；全部走完则返回 NULL（允许跑）。单遍实现会在「首个 block 已命中、尾部仍有未知/重复 id」时静默放过坏策略——负例见 §3.4 `test_gate_matrix`。

签名（草案）：

```text
v13_should_run_gate(p_sid uuid) RETURNS text
  STABLE INVOKER
  SET search_path = pg_catalog, public
  -- NULL = 允许；非 NULL = 获胜 block 门 id

v13_should_run(p_sid uuid) RETURNS boolean
  STABLE INVOKER
  SET search_path = pg_catalog, public
  -- 体只有一行：return v13_should_run_gate(p_sid) IS NULL
```

布尔包装是唯一允许的第二符号；序与条件禁止在包装、advance、hint、attention 里再写一遍。attention 要门 id 时调 `v13_should_run_gate`。

stage 27 的策略翻版（同一安装事务，先 INSERT `active=false` 的 version 2，再按 Phase B 的双 UPDATE 先灭 v1 再点亮 v2，避免 `ux_v13_policies_one_active` 的 23505）：在 v1 数组**末尾**追加 `quota_window` 与 `capabilities`，二者 `effect=block`。stage 29 同样追加 `goal_stopped` block。顺序变化的测试用测试自己的 version，测完 ROLLBACK，不改种子 value（value 改写会被冻结触发器拒绝，**观察** `v13_policies_frozen`）。

**影响面。** stage 26 种子 + 函数；27/29 的换体与翻版；attention 的 `blocked_by` 词表与此闭集相同，外加 NULL。

**生产绑定。** 默认种子下 duty 不阻塞投影，现有回归应仍能入队。收紧顺序或把 duty 改成 block 是数据变更，不是热修函数。策略翻版的执行者 = 安装 owner/DBA（`v13_policies` 角色面只授 SELECT，core `:854`；INSERT 与 active 翻转只在表主与超户手上——**观察**）。翻版是运维动作，不进驱动器，不建管理函数（要建则先回 §4 例外四问）；各 stage README 写明翻版由部署 owner/DBA 在独立于 driver/advance 的**单一数据库事务**内**原子**执行（r10：INSERT inactive 新版本 + 旧版灭活 + 新版激活同事务提交；**禁止逐句 autocommit**——旧灭活与新激活之间会出现无 active 行窗口，并发 should-run/quota/hint 调用将 fail-closed RAISE），不由 route/worker/driver 执行。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| D10-B-alt-deny | 种子外加 `explicit_deny` 布尔急停 | 在 L32 之前制造第三套暂停，且没有指纹与 resume |
| D10-B-alt-duty-block | 种子里 duty 就是 block | 改变「duty=0 仍先 spawn」的活体（**观察**）。默认行为测试会红 |
| D10-B-alt-text-array | `gates` 是字符串数组，block/shadow 写死在函数里 | 改 shadow→block 必须改函数，违反「改序/改执法不改体」 |
| D10-B-alt-two-policies | 序一行、执法另一行 | 两行可以拆开翻版，短路序和执法集合会分叉 |
| D10-B-alt-order-deny | （codex 残稿形）`{enabled, order:[], deny_action:'wait'}`，硬门顺序定死在代码 | 硬门定死则「改序=新版本」只对治理门成立、对硬门不成立；`deny_action` 只有 `wait` 一个合法值时是死键；`enabled=false` 是全拒、空 gates 是全放——互补不是重叠，但 stage 26 的行为假路径已由 duty block 的测试版本覆盖，不为它单设第二急停。若 R13 采此形，§1.1 的 duty shadow 机制须改为 `order` 是否含 `duty_cycle` |

### 1.3 D15-A 指纹自激

**题面。** `goal/stopped` 一旦插入就会进入 `v13_state_hash` 的 events 材料（**观察**：排除名单只有三个 `session/*`，control `:390`）。resume 若把「现在的 `v13_state_hash`」与 stop 载荷里的哈希比较，比较恒失败。

**施工形（⑦已按双车道一致推荐收口，r31）：新函数 `v13_goal_fingerprint`，材料 = `v13_state_hash` 的 v1 材料，events 排除名单 = 无条件八词（`session/completed`、`session/failed`、`session/cancelled`、`goal/stopped`、`goal/resumed`、`control/handoff`、`wake/satisfied`、`turn/material_spent`——后三组理由：stopped 会话的合法交接是导出工件不是状态变化（不排除则首个 handoff 收据即漂移、resume 永拒，与 §1.8 冲突）；停前已决工作的结算收尾不应封死 resume。`control/handoff` 与两类结算事件仍留在 `v13_state_hash` 与 `v13_transcript_hash` 各自材料里，B 合同不动）。排除名单在材料里出现**两处**——v_max 计算（control `:377`）与 events 聚合（`:390`）——同构双改。不换体 `v13_state_hash`。** stop 与 resume 载荷记这个指纹，不记裸的 `v13_state_hash`。

- 防漂钉（r32 五类修正——「八词任一出现必不等」不成立：三个 `session/*` 两边都排除）：**八词均不存在**的会话上两函数逐字相等；**仅出现三个 `session/*`** 时仍逐字相等；出现 **fingerprint 独有排除的五类**（`goal/stopped`、`goal/resumed`、`control/handoff`、`wake/satisfied`、`turn/material_spent`）之一后必不等（state_hash 计入、fingerprint 不算）。**八词扩排只作用于 `v13_goal_fingerprint`：`v13_state_hash` 继续计入五类；`v13_transcript_hash` 保持 Phase B 既有规则——仅排除 `control/handoff`，继续计入 goal/wake/material（r32 合同澄清）。**
- stop 在 `sessions FOR UPDATE` 之下先算 fingerprint，再 `v13_append_event`。守卫用同一函数重算与载荷比较（stopped 行 = current=payload 二等，不比 stop_fp；resumed 行 = 先转移后三等——§1.4 r26 同文）。
- resume 的通过条件（r33 与 §6.3 完全同链：**终态（sessions.status）→ busy → 转移 → 指纹**——终态即 `v13: goal lifecycle`，不得进入三等，否则 stop→cancel→closeout 后未排除事件漂移会错报 fingerprint）：非终态无在途且 fold.state='stopped' 时，三等 `v13_goal_fingerprint(sid)` = 载荷 fingerprint = fold.stop_fp，任一不等 → `RAISE 'v13: goal fingerprint'`，零新事件。守卫对 `goal/resumed` 同序同验。
- 停/复事件自身不造成漂移。resume 只比 fingerprint（r31）：除八词排除名单上的事件外，其它状态变化（新的 `user/message`、effect 状态变化、其它事件）才使 fingerprint 漂移、resume 失败；`control/handoff` 只改 `v13_state_hash`，fingerprint 维持停时值，停着交接后 resume **仍成功**。
- 失败后的出口是已有的 cancel / 在途 effect 的 complete，不是 force 位。stop 不阻止 `v13_cancel`，也不阻止已 claimed 行的 `v13_complete`（二者都不读 lifecycle）。
- 载荷键名用 `fingerprint`，不用 `state_hash`。closeout 收据的 `state_hash` 仍只来自 `v13_state_hash`（**观察**：守卫要求 session 收据含该键，control `:460`）。两个名字并列，避免 resume 去比 closeout 哈希。
- 首条 stop 之后 `v13_state_hash` 必须变化（方向断言，与 Phase B handoff 相同的理由：禁止把新 type 塞进排除名单来做绿）。fingerprint 在 stop 前后相同。
- （子题⑦已收口进上方施工形——八词排除集为唯一形，无「若采纳/若否决」分支；`test_child_done_while_parent_stopped` 固定断言 fingerprint 不变且 resume 成功，r31。）

**影响面。** 只有 stage 29。advance 不调用 fingerprint。closeout 不调用 fingerprint。

**生产绑定。** 合同在 SQL。无 UI。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| D15-A-alt-exclude-in-state-hash | 换体 `v13_state_hash`，把 `goal/*` 放进排除名单（**codex 两残稿主张；r17 定性：不可施工，建议 R13 明确否决**——state_hash 须继续计入 `control/handoff`（B 合同），stop→extract 必改恢复基准，与 `test_handoff_after_stop_resume_succeeds` 直接冲突；子题⑦两调事件亦无处置；若强行采纳须重开 B 的 state-hash 方向合同、载荷形状与全部条件测试） | 单一哈希函数的简洁性救不了与 handoff/结算事件排除的复合冲突；采纳即重开多份已裁合同 |
| D15-A-alt-preimage | 只保存 stop 前的 `v13_state_hash`，resume 时无法重算 | 载荷无法被守卫独立重算，伪造哈希只靠调用方自觉 |
| D15-A-alt-ignore-user | fingerprint 再排除 `user/message` | 停着的目标收到新消息仍可 resume，指纹不再代表「状态没变」 |
| D15-A-alt-force | resume 增加 `acknowledge_drift` | 母计划只要求不符则零写，没有第二通道 |
| D15-A-alt-no-handoff-exclude | fingerprint **不**排除 `control/handoff`，改为 §1.8 定「stopped 禁新 handoff」 | 停着的目标不能交接与「停 ≠ 终态、终态都可交接」的取向相損；交接是导出工件，把它当状态变化过严 |

### 1.4 D15-B 守卫、索引、折叠函数、谁可以写

**题面。** `goal/stopped|resumed` 的载荷、写入者、部分索引，以及唯一折叠函数的返回形状。

**草案推荐。**

载荷两 type 相同，键恰三（字母序 `fingerprint`、`reason`、`schema_version`）：

| 键 | 值 |
|---|---|
| `schema_version` | JSON 整数 1 |
| `fingerprint` | `v13_goal_fingerprint` 的 64 位小写 hex |
| `reason` | 字符串，`char_length` 1..256 |

`source_effect_id` 必须 NULL。非 NULL → `v13: goal source`。

转移（最后一条同类事件获胜，但非法转移是 RAISE 不是静默覆盖）：

| 当前折叠 | 新事件 | 结果 |
|---|---|---|
| 无生命周期事件（折叠 = running） | `goal/stopped` | 允许 |
| running（最近为 resumed，或尚无事件） | `goal/stopped` | 允许 |
| stopped | `goal/stopped` | `v13: goal lifecycle`，零写 |
| stopped 且指纹三者一致 | `goal/resumed` | 允许 |
| running | `goal/resumed` | `v13: goal lifecycle`，零写 |
| 终态会话（completed/failed/cancelled） | 任一 | `v13: goal lifecycle`，零写（草案立场，与 codex 两残稿一致：终态的推进语义已由 advance 前缀关闭，停/复无意义） |
| 指纹不一致 | 任一 | `v13: goal fingerprint`，零写 |

**折叠唯一（r24 重构；r26 段首/步 3/步 7 三处同文；r29 语法修正）：`v13_goal_fold(sid) RETURNS TABLE(state text, stop_fp text)`——无 lifecycle 行时恰返回一行 `RETURN QUERY SELECT 'running'::text, NULL::text; RETURN;`（**OUT 参数函数禁带参 `RETURN NEXT ('running', NULL)`——建函数即失败，codex[28-1]**；禁零行——否则裸 `SELECT state` 得 NULL、`state <> 'stopped'` 为 UNKNOWN 跳过分支，零事件直插 resumed 会漏进后续步骤）；有行时 state 仅当该行 type='goal/stopped' 为 stopped，stop_fp = 同一次读出的最后一条 lifecycle 载荷的 fingerprint（resumed 载荷即停时指纹），禁止第二遍查 `goal/stopped`**。公开 lifecycle = 薄包装。**检查序（guard 与 resume 同序，append 前完成 fold 调用）：转移先行——state<>'stopped' 的 resumed（含零事件）与重复 stop → `v13: goal lifecycle`；新行是 `goal/stopped` → 验 `v13_goal_fingerprint(current) = payload fingerprint`（不比 stop_fp，不符 `v13: goal fingerprint`）；仅 state='stopped' 且新行是 resumed → 三等 current=payload=stop_fp（不符同文案）**。advance/recover/gate/hint/attention 仍只经公开 lifecycle。唯一读「最后一条」的地方 = fold 一份：

```text
v13_goal_lifecycle(p_sid uuid) RETURNS text
  STABLE INVOKER
  SET search_path = pg_catalog, public
  -- 'running' | 'stopped'
  -- 无 goal/stopped|resumed 行 → 'running'
  -- 未知会话 → RAISE 'v13: unknown session %'
```

advance、`v13_recover_idle`、`v13_should_run_gate`、stage 29 的 hint 与 attention 只经公开 lifecycle。**`goal/stopped|resumed` 的 `ORDER BY seq` 查询只允许出现在 `v13_goal_fold` 一处（r25 白名单收紧）；guard 与 stop/resume 的 prosrc 只允许 `v13_goal_fold(` 调用、不得自扫**。字符串 `goal/stopped` 只允许出现在：fold、fingerprint 的排除名单、守卫、stop/resume 的 `v13_append_event` type 参数、触发器 WHEN。

写入者：

```text
v13_goal_stop(p_sid uuid, p_reason text) RETURNS jsonb
v13_goal_resume(p_sid uuid, p_reason text) RETURNS jsonb
  VOLATILE INVOKER
  SET search_path = pg_catalog, public
```

- 调用方不传指纹。函数在会话行锁内计算。
- 授权（R13b 已裁：**函数与守卫同调** `v13_control_operator()`——单源行政带：rolsuper 或对 `v13_route` 的 `USAGE`；「今日 route 在带内」是偶然闭包——`v13_spawn_owner`/`v13_triage_owner`/`v13_handoff_owner` 均有 events 写面且在带外，不查则带外直插合法信封即落地）。不扩展 F17 的闭集，父 agent 不能停子会话。非 operator（函数或守卫任一路径）→ `v13: session not found`（不插值 uuid，不读会话）。operator 且会话不存在 → `v13: unknown session %`。
- 锁序（r30 与 §6.2 步 7/§6.3 同文）：授权预检（未锁）→ `sessions FOR UPDATE` → operator 复验（角色在事务内不变，复验仍写上，防授权谓词将来变体）→ `v13_goal_fold` → 终态 → busy → fingerprint → append。
- stop/resume **不修改、不结算、不等待**在途 effect；但必须在会话锁内**准入检查** `EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status IN ('ready','claimed','unknown'))`，命中任一 → `RAISE 'v13: goal busy'` 零写（busy 是准入检查不是扫描动作，r9 措辞统一；含 ready——`v13_claim` 不拿会话锁，只拒 claimed/unknown 拦不住 stop 后新 claim+complete 的指纹漂移；替代：允许停 + 接受漂移后果；或受约束重基通道（新裁决）。
- 守卫 `v13_goal_event_guard` 为 **INVOKER**、BEFORE INSERT、`WHEN NEW.type IN ('goal/stopped','goal/resumed')`，只 RAISE 不改行，**`SET search_path = pg_catalog, public`**，体内表/函数引用 schema-qualified（fingerprint 同款 SET；防调用方 search_path 污染）。不新建 NOLOGIN 角色，不把 stop 做成 DEFINER。route 已能 INSERT events；守卫把「开放 type」收成「形状与指纹合法才能插入」。**共享面（r20 措辞）：守卫与 stop/resume 共享会话锁、终态、busy、载荷与 fingerprint 检查；是否共享 `v13_control_operator()` 授权 = **R13b 已裁共享（⓪ 步）**；lifecycle 事件的 seq 分配契约 = 小题⑩（已裁，见②）**。
- **小题⑩（r20 新增；r21 修正 off-by-one——活体 `v13_append_event` 先 `UPDATE next_seq = next_seq + 1` 再 `RETURNING next_seq - 1` 作 `events.seq`（core `:62-93`），BEFORE INSERT 守卫看到的合法值是 `NEW.seq + 1 = sessions.next_seq`；写 `NEW.seq = next_seq` 会拒掉每一次经 append 的停/复，两车道同判）：分配不变量 = `NEW.seq + 1 = sessions.next_seq` 且 `NEW.turn_no IS NOT DISTINCT FROM sessions.turn_no`**，写入检查序（行锁之后、终态之前），失败文案单列 **`v13: goal seq`** 零写。不推进 `next_seq` 的裸 INSERT（seq=当前 next_seq）不满足不变量、被守卫直接 RAISE 零行——不靠主键冲突当负例。成功 stop/resume 断言：`next_seq` 恰增 1、事件 `seq` = 调用前的 `next_seq`。负例通路收口（r23）：**裸 INSERT 只留一条专门负例（seq=当前 next_seq → `v13: goal seq`）——不推进 next_seq 的直插要么撞②要么撞 PK，到不了后续步骤，禁止把②挪后迁就直插**；其余负例一律经 `v13_append_event` 触发守卫。「只经 `v13_append_event`」是意图（守卫看不见调用栈，复制分配协议的双轨直插与 append 不可区分）；替代 = 自担推进的双轨写口（校验 seq/turn_no + 调用方手动推进，不推荐）。
- 检查序（r41 七步 = ⓪+六步，§6.2 步 4 同指此序）：**⓪ operator（R13b）**——先调 `v13_control_operator()`，假则 `RAISE 'v13: session not found'` 零写（不读会话、不取锁——与函数侧授权预检同位同文案）；**① 行锁**——守卫先 `PERFORM 1 FROM sessions WHERE session_id = NEW.session_id FOR UPDATE`，随后**只取折叠状态值**（转移 RAISE 留在⑥，不在①做）；**② seq/turn_no 不变量（小题⑩；r24 析取修正——r23 的「失败极性 AND 成功极性」组合会让 seq 错但 turn_no 配平的行放行、seq 配平仅 turn_no 错的行先落形状错误）**——`(NEW.seq::numeric + 1) IS DISTINCT FROM sessions.next_seq::numeric **OR** NEW.turn_no IS DISTINCT FROM sessions.turn_no`，**任一**即 `RAISE 'v13: goal seq'` 零写（**禁止 `(NEW.seq + 1)` 裸 bigint 相加或把和写回 bigint**——最大值会溢出报 PG 原生错误绕文案）。负例恰四条（r25 拆分通路）：①seq=当前 next_seq ②seq=bigint 最大 ③seq IS NULL——三条 seq-only 裸 INSERT；④**seq=next_seq-1 且 turn_no 故意错位**（SAVEPOINT 内回滚；append 无法自然产生该组合——它总复制 sessions.turn_no）→ 均以 `v13: goal seq` 在②结束，④不得进入③–⑥（②只在守卫、且在 `v13_append_event` 已推进 `next_seq` 之后评估；stop/resume 不在 append 前自查该等式）；**③ 终态**——`sessions.status` 终态 → `RAISE 'v13: goal lifecycle'` 零写（守卫/stop/resume 三口同查同序；终态与在途并存时文案固定 `v13: goal lifecycle`）；**④ busy**——`EXISTS (SELECT 1 FROM effects WHERE session_id = NEW.session_id AND status IN ('ready','claimed','unknown'))` → `RAISE 'v13: goal busy'` 零写（含 ready：`v13_claim` 不拿会话锁，只拒 claimed/unknown 拦不住 stop 后新 claim+complete 的指纹漂移）；**⑤ 形状/载荷**——**前置（r23，codex[22-1]）：`jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'`（数组/字符串/JSON null 直接 `v13: goal payload`——否则 `v13_json_keys` 会先抛 PG 原生 `cannot call jsonb_object_keys on a non-object`，绕过专属文案）**；`source_effect_id` 必须 NULL（否则 `v13: goal source`）；键集恰三；`schema_version` JSON 整数 1；类型契约 `jsonb_typeof(payload->'reason')='string'` 与 `jsonb_typeof(payload->'fingerprint')='string'`；fingerprint 小写 64 hex 正则；reason 长度 1..256——**本组失败统一 `RAISE 'v13: goal payload'`（r22 专属文案；`v13: goal source` 专 source、`v13: goal fingerprint` 专重算不一致，不得复用/或连）**；**⑥ 转移与指纹重算（r25 先转移后三等——无事件时 stop_fp 为 NULL，先验三等会把零事件 resume 错报 fingerprint）**——先判转移：`state <> 'stopped'` 的 resumed（含零事件）与重复 stop 一律 `v13: goal lifecycle`；**仅当 state='stopped' 且新行是 resumed** 时验三等 `current_fingerprint = payload->fingerprint = fold.stop_fp`，任一不等 → `v13: goal fingerprint`；stopped 行的指纹重算不等同文案。seq/payload/source/fingerprint/busy/lifecycle 六类文案各自单列、负例逐字断言。
- 部分索引（草案推荐要建，因为折叠是每次 should-run / recover 的读，且母计划倾向允许）：

```text
CREATE INDEX ix_events_goal_lifecycle
  ON events (session_id, seq DESC)
  WHERE type IN ('goal/stopped', 'goal/resumed');
```

非 UNIQUE。停、复、再停必须都能插入。

- 折叠**不**套 `v13_last_user_seq`。新 `user/message` 不自动 resume（与 duty hold 的 turn 水位相反，这是故意的）。
- 折叠范围 = **单会话**，不沿 `v_goal_tree` 传播：停 root 不停 children，子会话的 should-run / 窗口独立评估；attention 里父子各一行各算各的（施工形唯一：停复只作用于该 `session_id`，不沿 `v_goal_tree` 传播；树级停不在本计划施工形内，要做须另开裁决并重审 stage 29 差集——r31 措辞定稿）。
- 安装时若已有任一 `goal/stopped|resumed` 行：`RAISE 'v13: goal baseline'` 并列出 session_id 与 seq，不回填、不修史。

**影响面。** stage 29 全文。stage 26–28 的源码断言要证明自己没有这条查询。

**生产绑定。** operator 经 SQL 调用即生效。非 operator 的 42501 与 `session not found` 都要测：无 EXECUTE 的角色是 42501；有 EXECUTE 的非 operator（若活体 proacl 里没有这种角色，则只断言 PUBLIC/worker 无 EXECUTE，并在 README 写明「带内非 operator」依赖 `v13_control_operator` 的定义，用 `SET ROLE` 到一个非 superuser、非 route 成员的 NOLOGIN 测试角色——**只在测试事务里 CREATE，随测试库丢弃，不进安装 SQL**）。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| D15-B-alt-definer | 新建 `v13_goal_owner`，DEFINER 单写者，守卫查 `current_user` | L32 没有 handoff 那种「hash 必须由受信内部 helper 重算、route 直写会绕过策略」的第二写口问题；守卫自己会重算指纹。多一个集群角色要回答的生命周期与 Phase B owner 相同，收益不够 |
| D15-B-alt-parent | 直接父可 stop 子，走 `v13_control_authorized` | F17 闭集已冻，不含 stop。父停子是新动词准入 |
| D15-B-alt-idempotent | 重复 stop 返回原载荷、零新事件（codex 残稿主张返回 `replay`，呼应终态 cancel→replay 先例） | 停没有 delivery 身份；静默成功会掩盖「已经停了」。若 R13 采 replay：须另定「同向重放的返回物形状」并补 gate；`v13: goal lifecycle` 保留给逆向转移 |
| D15-B-alt-rich-lifecycle | `v13_goal_lifecycle` 返回 `TABLE(state, event_seq, state_hash)`，无事件时 `(running,-1,NULL)`（codex 残稿形） | 折叠消费方（gate/recover/hint/attention）只需要 state；暴露 event_seq/state_hash 诱发第二处读事件、绕过「唯一折叠」 |
| D15-B-alt-no-index | 不建部分索引，顺序扫描 | 每次入队前读都扫该会话事件。草案仍把「不建」留作替代，由 R13 勾选；推荐建，因为它不是表 |
| D15-B-alt-open-payload | 无守卫，只靠函数自觉 | route 可 INSERT 任意 jsonb，折叠会读到坏载荷 |
| D15-B-alt-guard-operator | 守卫同查 `v13_control_operator()`，直插与函数走同一授权 | **✅ 已采纳（R13b，双车道一致）**——原「耦合行政带」反对意见被「带外 INSERT 角色已可绕过 + 单源合同」驳倒；基线（不查）废止 |

### 1.5 L29 到顶时批量路径不选 spawn

**题面。** 占用到顶或策略不允许时，advance 的批量派发不调用 spawn，不写空 route，不加 route 键。未认领 `tool/call` 如何处置。`v13_spawn_subsession` 今天 RAISE `v13: spawn budget cap`（以及 fanout、depth 两个兄弟文案）（**观察**）。

**草案推荐。**

- **不换体** `v13_spawn_subsession`、`v13_route`、`v13_triage_after_route`。直调 spawn 仍 RAISE 三个预算文案。`v13: spawn batch-dispatched` 硬拒保持。（r16：原 r2「执行权/INVOKER/补授 advisory_class」段整体删除——已被 DEFINER 方案取代；安装事务不向 `v13_route` 授 `v13_advisory_class`；cap 正例仍以 `SET ROLE v13_route` 调 advance 验证 route 能进 wrapper。）
- 新函数只服务 advance 与 hint（r7：共调 helper 防两份预算逻辑漂移，第 6 轮 codex[2]）：

```text
v13_spawn_budget_snapshot(p_sid uuid, p_requested int, p_root uuid DEFAULT NULL) RETURNS boolean
  STABLE INVOKER
  SET search_path = pg_catalog, public
  -- 无锁纯读：策略校验（缺行/坏键/范围 → v13: spawn_budget policy；未知会话 → v13: unknown session%；
  -- 环/深>64 → v13: spawn root cycle）+ 三道比较（fanout/depth/cap）；requested 走法同 §1.7 分支 3.5。
  -- r10：snapshot **始终自行上行一次**算出 walked_root 与 depth 并做三道比较（occupancy 用 walked_root）；
  -- p_root 非 NULL 时仅断言 walked_root IS NOT DISTINCT FROM p_root，不等 → RAISE 'v13: spawn root cycle'
  -- （锁与比较同根的钉；不跳过父链——depth 只在上行中产生）；hint 两参调用时 p_root 为 NULL 走自带上行

v13_spawn_batch_allowed(p_sid uuid, p_requested int) RETURNS boolean
  VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp -- OWNER TO v13_spawn_owner（r15/r18/r38）
  -- 唯一全链（r38，别处不得另述）：会话 FOR UPDATE → 上行 v_root（unknown/root-cycle 不取咨询锁）
  -- → PERFORM public.v13_policy_share()（策略行全部经 helper；wrapper 自身无 FOR SHARE）
  -- → pg_advisory_xact_lock(v13_advisory_class('spawn_budget'), hashtext(v_root::text))
  -- → v13_spawn_budget_snapshot(p_sid, p_requested, v_root)。
  -- 体内业务名全限定；安装断言：proconfig（pg_temp 末位）+ prosrc（恰一处 v13_policy_share(、零 FOR SHARE、无未限定业务名）
```

hint 的分支 3.5 与 stage 29 的 `v13_spawn_batch_allowed` **共调 `v13_spawn_budget_snapshot`**，禁止两份预算判定逻辑；差异仅锁（hint 无锁快照、advance 锁内终判）。stage 28 时 `v13_spawn_batch_allowed` 尚不存在——snapshot 在 stage 28 先建（hint 用），stage 29 只加 wrapper。

- 真：在与 `v13_spawn_subsession` 逐字相同的咨询锁 `pg_advisory_xact_lock(v13_advisory_class('spawn_budget'), hashtext(v_root::text))`（**r2：uuid 无到 text 的隐式转换，必须 `v_root::text`，锁键与 spawn 同源**）之下调 snapshot：`requested <= max_fanout` 且 `depth+1 <= max_depth` 且 `v13_spawn_occupancy(root)+requested <= max_nonterminal`。root 的走法与 spawn 函数相同（沿 `parent_session_id` 上行，环或深度 >64 → 原样 `RAISE 'v13: spawn root cycle'`，这是数据损坏不是「到顶」）。
- 锁序（r39 定稿）：**唯一全链见 §1.5 函数卡（本处不重述）**——wrapper 自身无任何 `FOR SHARE`，策略行全部经 `v13_policy_share()`；安装断言：wrapper prosrc 恰一处 `v13_policy_share(` 且**不含 `FOR SHARE`**。**配套授权（r16 定稿 ACL 模型，五句断言；r17 分期注：route 的 snapshot 授权在 stage 28（hint 上线时）；spawn_owner 的 snapshot 授权与 wrapper 同一事务，放 stage 29）**：`v13_spawn_budget_snapshot` 的 EXECUTE 同时授 `v13_route`（hint 是 INVOKER 且直调 snapshot——route 无此权限则生产 hint 42501）与 `v13_spawn_owner`（DEFINER 闭包）；`v13_route` 获得 wrapper + snapshot 两函数；worker、PUBLIC、recall、resolve 对两者均不可；route 对 `v13_advisory_class` **不可**执行（DEFINER 下不需要，不授）；安装后 DO 按此五句断言。FOR SHARE 依赖 `v13_spawn_owner` 既有表级 UPDATE（spawn 尾部 `GRANT SELECT, INSERT, UPDATE ON ALL TABLES ... TO v13_spawn_owner`，stage 18 已授）——列级 `UPDATE(active)` 授予叠加无边界意义，省略；wrapper prosrc 断言不含对 `v13_policies` 的 UPDATE。若 R13 要求最小权限面：REVOKE spawn_owner 在 `v13_policies` 上的整表 INSERT/UPDATE 后仅列级授 active，随案裁并同步全部 ACL 断言。若裁回 INVOKER wrapper：须另授 route 最小 UPDATE 列权限并证明不可翻转，不沿用现稿。并发翻版时序（与 §6.4 同序；r40 措辞：调用事务经 `v13_policy_share` 持有五行 FOR SHARE——wrapper 源码仍零 FOR SHARE）：A（route）未提交事务内；B（表主/超户，禁 route）灭活 UPDATE 在 `pg_locks` 阻塞；A 同事务 spawn 按旧 value；A COMMIT 后 B 才成功。parent 链不可变由 stage 26 的 `trg_sessions_parent_immutable` 承担（§2 第 15 项 / §3.2 步 9a；UPDATE 授权面是预期事实，不是停工）；仅 R13 否决小题⑧时 stage 29 重裁锁序。
- 假：上述任一预算比较失败。
- 策略行形状坏、缺行、会话不存在：**RAISE**，与 spawn 现文案一致（`v13: spawn_budget policy` / `v13: unknown session %`），不要把配置错误变成静默跳过。
- 「策略不允许」在本草案里**不新造策略行**。它等于：`v13_should_run` 已为假（含 stage 29 的 stopped、stage 27 的配额与能力差）。triage `direct` **不**额外参与批量跳过（`after_route` 今天就不管批量路径，**观察**）。若 R13 要把 `v13_triage_decide(...)='direct'` 算作不允许，那是替代项，实施者不要自行加。
- advance 在 P-spawn 的判断**用顺序 IF/ELSIF，不用单表达式 OR**（r2：PL/pgSQL 不保证 OR 短路，should_run 为假时不应仍调 VOLATILE 的 batch_allowed）：`IF NOT v13_should_run(p_sid) THEN defer; ELSIF NOT v13_spawn_batch_allowed(p_sid, length) THEN defer; END IF`（r5：读点位置钉死 = explore RAISE（`:643`）之后、`v13_spawn_children`（按 dump 实名）之前——否则坏形状 `v13: spawn args` 会落在门后）。defer = 不写 `spawn_fanout`、不插入空 `params`、不增加 route 键，直接 `RETURN 'waiting'`（§1.1 P-spawn）。
- **defer 即提前返回（唯一活语义）**：P-spawn 见假（should_run 假或预算预检失败）→ 先 `UPDATE public.sessions SET status='waiting' WHERE session_id = p_sid AND status IN ('ready','waiting')`（r8：与 §1.1 P-spawn 同块），再当轮 `RETURN 'waiting'`，**不进 harness 段、不进 prework/route**（活体 spawn 成功同样 `:662` 提前返回——对齐）。harness 结算与入队都留给后续「无未认领 tool/call」的轮次。判别夹具见 `test_defer_with_pending_calls_and_finish`。若 R13 要「结算先行」变体，须重新定义先后、加判别夹具，且不得与提前返回并存。
- 未认领 `tool/call`：**留置**。不改写、不删除、不补 `tool/result`、不插入 failed effect。
- 今天 spawn 成功会在 prework 之前 `RETURN 'progressed'`，duty hold 本来就不会在「有未认领 tool/call」的那一次 advance 里写下（**推断**自控制序）。defer 后同样不写 hold，与「这条路径到不了 prework」一致。
- 咨询锁必须在预检里拿到。只做无锁快照然后仍调用 spawn，竞态下 spawn 仍会 RAISE，翻转不成立。预检为真且同一事务内接着调用 spawn 时，锁可重入。**并发边界（r17 诚实化；r19 断言语义与 §6.4 同句）：根咨询锁不冻结 occupancy 的全部增量写者——`v13_append_event(...,'user/message')` 可把已终态（completed/failed）子会话复位 `ready` 且不取该锁，预检与 spawn 复检之间的「终态兄弟复活」可能触发 spawn 复检 RAISE。处置：该残留由 spawn 复检背板兜底——gate 以「捕获并断言 SQLERRM 精确等于 `v13: spawn budget cap`、父事务回滚、进程退出码 0」的方式记录（预期路径，非 gate 失败，也不得被 advance 吞成 waiting）；L29 声明 = 消除常见翻版/同锁窗口，不承诺并发下零 RAISE 或绝对不超售。**复检之后至本事务 COMMIT 之前仍可静默超售——「不超售」性质存在既有残留，处置 = §1.10 小题⑨（r19 新增，R13 显式裁定：接受残留+台账，或另立后续阶段修复；纳入同锁域须动冻结面 append/user 路径）。**

RED 基线（写 stage 29 SQL 之前，记入该 stage README，不进仓库的 dump 目录即可）：在 stage 28 库上把 `spawn_budget` 翻到 `max_nonterminal` 小于将要请求的子树规模，advance **必须**仍 `RAISE 'v13: spawn budget cap'`。复现不了就停，不要把已经不会 RAISE 的行为再「修」一遍。

**影响面。** 只换 stage 29 的 advance（底稿是 stage 26 换体之后的 dump，不是 triage 文件）。stage 18 文件字节不动。

**生产绑定。** 批量路径的跳过随 advance 换体生效。直调 RAISE 仍在，文档必须把两句话分开写。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| L29-alt-consume | 到顶时写 failed effect + `tool/result` 错误，吃掉 tool/call | 合成第二条工具结局；母计划要求键缺席，不是改写调用 |
| L29-alt-fallthrough | 跳过 spawn 后继续 prework/route，父会话照常入队 | 未认领 tool/call 每轮都排在最前，父会话会在 cap 期间反复入队，烧 `max_cycles` |
| L29-alt-raise-delete | 删掉 `v13_spawn_subsession` 里的 RAISE，改返回空 jsonb | 直调与重放测试依赖该文案；空对象正是母计划禁止的 |
| L29-alt-triage-direct | `decide='direct'` 也算不允许 | 扩大「策略不允许」到一条批量路径今天没有的耦合；需单独裁决才加 |
| L29-alt-status-only | 只翻转 `spawn budget cap`，depth/fanout 仍 RAISE | 三个比较都是「预算拒绝」。只翻转 cap 会让 fanout 越界仍掀翻事务，性质只补了一半 |

### 1.6 L6 窗口索引

**题面。** `turn/material_spent` 上没有 `(session_id, at)` 可用的索引（**观察**：`ux_events_material` 是 `(session_id, source_effect_id)` 的部分唯一索引；`events.at` 无索引）。每次 should-run 都可能按 `at` 过滤。加不加部分索引。

**草案推荐：加，且只加这一个。**

```text
CREATE INDEX ix_events_material_spent_at
  ON events (session_id, at)
  WHERE type = 'turn/material_spent';
```

它不是表、不是物化、不带 payload、不记录 spent/voided。放在 stage 27 的 SQL 序里，守卫与函数之后、GRANT 之前。`pg_get_indexdef` 断言谓词与键。

**影响面。** 只 stage 27。不改 `ux_events_material`。

**生产绑定。** 索引随安装生效，无 driver。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| L6-alt-none | 不加索引，接受每次顺序扫该 type | 读点在每轮 advance 的多个入队前，且 stage 27 之后配额门默认开启。部分索引便宜，又被 R4 允许（索引 ≠ 表） |
| L6-alt-full | `CREATE INDEX ON events (session_id, at)` 不带 WHERE | 把所有 type 的 `at` 编进索引，超出窗口查询 |
| L6-alt-summary | 窗内计数缓存表 | R4 概念缓存表，禁止 |

### 1.7 L5 `attention_rank` 与 L21 hint

**题面。** `v13_attention(p_root)` 的输出列与排序。`v13_scheduler_hint` 三个词如何从投影得出。hint 与 cron 的关系。母计划 L5/D10 行均指迁移 §2.6 为语义源，而 §2.6 已写 R1 序：`human > unknown > cancel > duty_cycle=0 > 其余按最近材料事件`（该行标注「新裁：否」）。三序并陈送裁：迁移 R1 序 / codex 序（unknown > human > cancel，其后可跑/被阻/waiting）/ 本草案 CASE（human > unknown > goal_stopped > cancel > quota > capabilities > duty）。另：本草案秩与 §1.2 门数组短路序在 duty↔quota 的相对位置**相反**（门数组 duty 第 4、quota 第 5+；秩 duty 第 7）——已裁：attention 秩是操作者可见度的独立排序，**不要求与门判定序同序**（R13 记录分歧 6）。

**草案推荐。**

`v13_attention` 是 STABLE INVOKER SRF，`SET search_path = pg_catalog, public`。列序固定：

```text
attention_rank bigint
session_id uuid
parent_session_id uuid
depth int
status text
spawn_kind text
turn_no int
is_terminal boolean
should_run boolean
blocked_by text
```

- 行集 = `v_goal_tree(p_root)` 的每一行再加投影列。**返回行数预算（r28 标题定稿——不称资源契约/上限；遍历成本边界未闭合，如实声明并留 R13 另裁）**：签名 `v13_attention(p_root uuid, p_max_rows int DEFAULT 512)`；`p_max_rows` 是**返回行数预算**（r26 命名降级定稿——不保护 `v_goal_tree` 内部整树遍历/物化成本，调用方传 1 仍扫全树；范围 1..1024，超上限同 RAISE `v13: attention limit`；README/验收不得描述为资源上限）。**把上限前移到树遍历（有界读，产出 p_max_rows+1 行即败）= API/冻结面变更，留 R13 另裁；本阶段补大树成本回归（≥500 终态节点的 root 一次调用的耗时记录，不做硬阈值断言）。**先物化 `v_goal_tree` 结果并计数——`p_max_rows` 为 NULL、< 1、> 1024 或行数 > 上限时 RAISE `v13: attention limit`（fail-closed，**不调 gate、不截断、不分页**）；上限在逐行 `v13_should_run_gate` 之前生效（gate 调用数 ≤ 上限）。**边界声明（诚实降级）**：上限约束**返回行数与 gate 调用数**，不保护 `v_goal_tree` 内部的全树遍历/物化成本（遍历仍整树扫描；源头流式/分页属 API 扩张，须 R13 另裁，本计划不预写）；README 同文。未知 root、环、深度 >64 让 `v_goal_tree` 原样 RAISE（**观察**：`v13: unknown session`（无插值）/ `v13: goal tree cycle` / `v13: goal tree depth`）。
- `is_terminal` 直接用树函数的列，禁止在 attention 里再写一份终态字面量。
- `blocked_by` = `v13_should_run_gate(session_id)`（NULL 表示该行投影允许跑）。
- `should_run` = `blocked_by IS NULL`。禁止再调一次布尔包装以免双路径；若包装是唯一允许的第二符号，这里只用 gate。
- **stage 28 不读** `goal/stopped`，不调用 lifecycle（函数尚不存在；即使 stage 序上 29 在后，28 的源码也不得预写查询）。
- stage 29 要把 lifecycle 显示出来时：**DROP FUNCTION v13_attention(uuid, integer) 然后 CREATE**（保留 `p_max_rows` 参数与默认值）增加列 `lifecycle text`，同一事务内重新 GRANT。禁止在 stage 28 预留 NULL 列。PostgreSQL 的 OR REPLACE 不能改 OUT 列集合；预留列等于预写折叠形状。
- `attention_rank` 从 1 起，与返回顺序一致。排序键（1 = 最该被看见），全是输出序，不落列：

```text
is_terminal ASC
CASE blocked_by
  WHEN 'human_pending' THEN 1
  WHEN 'unknown_wall' THEN 2
  WHEN 'goal_stopped' THEN 3
  WHEN 'unconsumed_cancel' THEN 4
  WHEN 'quota_window' THEN 5
  WHEN 'capabilities' THEN 6
  WHEN 'duty_cycle' THEN 7
  ELSE 8
END ASC
depth ASC
session_id ASC
```

stage 28 还不会产生 `goal_stopped`，该臂是死分支，留在 CASE 里以便 29 只改函数体、不改这组秩。若 29 用 DROP+CREATE 改列，CASE 可以同时保留。`duty_cycle` 在默认 shadow 下不会成为 `blocked_by`；臂留着，是为了测试版本把 duty 改成 block 时秩稳定。

这是操作者注意力，不是调度队列。能跑的非终态节点排在被阻塞节点之后。终态整段沉底。hint **不是**这个秩的第一名。

`v13_scheduler_hint(p_sid uuid) RETURNS text`，STABLE INVOKER，同一 search_path。**第一条可执行语句 = 会话存在性检查（r14，codex[13-2]）：`sessions` 无 `p_sid` 即 RAISE `v13: unknown session %`，之后才读 status/effects/策略**——否则未知会话会被 duty/策略读取截获成 `wait` 或 `v13: triage policy`，违反错误合同。返回词闭集 `run_now|wait|dont_notify`。第一个命中的分支获胜：

| 顺序 | 条件 | 词 |
|---|---|---|
| 1 | `status IN ('completed','failed','cancelled')` | `dont_notify` |
| 1.5 | `v13_unconsumed_cancel(sid)` 为真（r10 活性补丁，第 9 轮 codex[5]：否则 stop→cancel 后 hint 永远 dont_notify、cancel 永无法 closeout——死锁）：无 claimed/unknown 在途 → `run_now`（driver 调 advance，前缀完成 cancel closeout 返回 terminal）；有待结算在途 → `wait` |
| 2 | stage 29 起：`v13_goal_lifecycle(sid)='stopped'` | `dont_notify` |
| 3 | **实现用显式 IF/ELSIF 顺序，禁止单表达式 OR（r24，codex[23-2]——PG 不保证 OR 子式求值序，在途时坏策略可能先抛策略错误）**：先测在途 ready/claimed/unknown 或 pending human → `wait`；再测 duty=0 → `wait`；再调 `v13_should_run` 假 → `wait` | `wait` |
| 3.5 | 存在未认领 `tool/call` 且 `v13_spawn_budget_snapshot(p_sid, requested)` 为假（r7：hint 与 stage 29 的 `v13_spawn_batch_allowed` **共调同一无锁 STABLE snapshot**，禁止两份预算逻辑；错误合同同款——缺行/坏键 → `v13: spawn_budget policy`；未知会话 → `v13: unknown session %`；环/深>64 → `v13: spawn root cycle`；走法：`requested` 与 advance 的 `v_calls` 同义——`seq > v13_last_user_seq` 且无匹配 `child-created`；root/depth 同 spawn 上行；三道比较 fanout/depth/cap；差异仅锁——hint 无锁快照、advance 锁内终判） | `wait`（退避，不是入队许可；README 写明；另写：守 hint 的 driver 在 stopped（dont_notify）期间不会触发停期结算事件——它们只属直接调用 `v13_advance` 的轮次，r6） |
| 4 | 其余（投影允许、duty=1、无在途 effect、非终态、未停） | `run_now` |

stage 28 的函数体**没有**第 2 行。stage 29 只许 OR REPLACE 增加第 2 行（返回类型仍是 text）。**组合优先级（r12，两处同文）**：分支表自上而下即优先级——终态 > **未消费 cancel（无 claimed/unknown → `run_now`；有 claimed/unknown → `wait`；ready 不算待结算）** > stopped > 分支 3（在途 / pending_human / `duty_cycle=0`（独立条件，不并进 should_run）/ should_run 假）> 预算退避（3.5）> `run_now`。若 R13 对两处映射分别采纳反转组合，须同时落组合序，否则停着会话上的 claimed/approval 会被永久沉默。

- `run_now` 的意思是「可以再调一次 advance」，不是已经执行，也不是可以跳过 advance 内部读点。
- hint 不是 ack：无事件、无收据、无 `scheduler_ack`、无心跳行。
- 连续两次调用：events 行数与 `sessions.next_seq` 不变，返回词相同。
- **不** `CREATE EXTENSION pg_cron`，**不**插入 `cron.job`。脚手架里的扩展降级惯例本阶段不沿用到「装上 cron」；沿用的只有测试两分支：若 `to_regclass('cron.job')` 非空，断言本 stage 没有插入 job；若为空，跳过该查询，函数测试照跑。driver 合同写在 README：cron 命令若存在于仓库外，必须是「读 hint → 仅当 `run_now` 才 `v13_advance`」；advance 体内的读点就是「再判一次」。SQL 里没有 `pg_sleep`。
- 未知会话 RAISE `v13: unknown session %`。

**影响面。** stage 28 两函数；stage 29 换 hint、重建 attention。成本：受 `p_max_rows`（默认 512，fail-closed）约束的 gate 调用数 × 门条件查询；终态行的门条件不读事件（human/cancel 谓词短路），非终态行各一次策略行读。`v_goal_tree` 内部整树遍历成本不在上限保护内（§1.7 边界声明）；分页/源头限制须另裁。

**生产绑定。** 见 §1.0 表。两格必须出现在 README。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| L5-alt-scheduler-order | 秩 = 可跑优先、阻塞沉底，供 cron 挑第一名 | 与 hint 合成第二调度器。注意力与提示是两个函数 |
| L5-alt-turn-desc | 在 depth 之前用 `turn_no DESC` | 母计划没给活动优先；多一个键就要在测试里制造同 depth 不同 turn 的夹具，而草案的 `session_id` 已经全序 |
| L5-alt-null-columns | stage 28 就返回 `lifecycle NULL` | 预写折叠形状；OR REPLACE 又改不了列，预留并不能减少 29 的 DROP |
| L5-alt-r1-order | 迁移 §2.6 R1 字面序：human > unknown > cancel > duty > 其余按最近材料事件 | 「最近材料事件」要读事件时钟（`at` 无索引）；duty 在 shadow 下不可见，第 4 位常空转；与门数组序同构性最好 |
| L5-alt-unknown-first | codex 残稿：unknown > human > cancel，再可跑/被阻/waiting | 与迁移 R1 的 human-first 冲突；同样属「输出序非门序」立场 |
| L21-alt-cron-row | 安装时注册每分钟 job，命令里再判 should-run | 仓库内调度器 = 第二运行时的入口。母计划写的是「pg_cron 若调用，必须再判」，不是「本 stage 去注册」 |
| L21-alt-hint-equals-should-run | 假 → `dont_notify`，真 → `run_now`，没有 `wait` | 配额窗外与终态无法区分，driver 会把暂时阻塞当成永久沉默，或把终态当成可重试 |
| L21-alt-stopped-wait | stopped → `wait` 而非 `dont_notify`（**codex 残稿立场——三通道分歧点**） | 支持方论点：停可复，是暂态不是终态，driver 应保留轮询。草案反驳：resume 只由 operator 发起，driver 轮询停在浪费；且与「stop 后 recover 零 nudge」的取向矛盾。R13 显式落裁 |
| L21-alt-busy-dont-notify | 在途 effect → `dont_notify` 而非 `wait`（**codex lane 3 立场**；与 stopped→wait 同为该残稿的两处反转） | 支持方论点：在跑会话轮询是浪费，结算事件才是唤醒源。草案反驳：在途 effect 可能长期挂起（approval），`dont_notify` 会让 driver 永久沉默。与 stopped 映射一并裁 |

### 1.8 L27 增量澄清

**题面。** Phase B stage 25 已规定 `v13_extract_handoff` 与 `v13_handoff_emit` 都读 `handoff_policy`：缺行或形状错 → `v13: handoff policy`；`enabled=false` → `v13: handoff disabled`；同身份重放在策略检查之前返回原载荷（B 计划 §1.2，**该计划是契约住所**）。stage 29 的「handoff 缺政策则拒」还要新写什么。

**草案推荐：不新写门。** stage 29 做回归断言，外加两条耦合负例：

- stop 不调用 extract，不产生 `control/handoff`，不翻转 `handoff_policy`。
- 目标处于 stopped 时，政策仍 enabled 的 extract **仍成功**（停 ≠ 终态，但 Phase B 允许终态交接；停更不应该比终态更禁）。政策 disabled 时新身份仍是 `v13: handoff disabled`，与是否 stopped 无关。
- 缺政策、形状错、disabled、同身份重放，各至少一条，文案与零写要求与 B 计划 §5.3 相同。实施者从 stage 25 测试抄夹具形状，不重写哈希字节式。
- 若 §9 发现 `v13_extract_handoff` 或 `v13_handoff_emit` 的 prosrc **没有** `v13_policies` / `handoff_policy`：停工回报 R13，**禁止**在 stage 29 补第二套策略读取器。

**影响面。** 只增加 `test_govern.py` 的回归段与 README 的一句「L27 无新函数」。无新 SQL 对象。

**生产绑定。** 沿用 Phase B 两格（extract 的 route COMMIT 已证明 / driver 未交付）。stage 29 不把该格改成已交付。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| L27-alt-stop-blocks-handoff | stopped 时 extract 拒绝 | 母计划 L27 是政策行前置，不是生命周期前置。两套拒绝会让「缺政策」与「已停」共用或分裂文案，B 的合同要重开 |
| L27-alt-rewrite | stage 29 再包一层 `v13_extract_handoff` | 第二份政策门，假绿温床 |
| L27-alt-skip-tests | 既然 B 测过，C 不测 | 换体 recover/advance/should-run 之后无人再跑 handoff 负例 |

### 1.9 D9 残留（公式已裁，这四件未裁）

D9（R4）已定：STABLE 重算；窗内 `turn/material_spent` **条数**；滑出窗口即失去资格；不撤回事件；无负债；不够则 should-run 为假；时钟用事件上已有的时间列。以下是公式里仍缺的语义。

**草案推荐。**

策略名 `quota_window`，version 1 active：

```json
{
  "schema_version": 1,
  "window_hours": 8760,
  "slot_minutes": 0,
  "allowed": 1000000
}
```

键恰四：`allowed`、`schema_version`、`slot_minutes`、`window_hours`。整数规则用 `v13_json_int_ok`（control `:108`；因此 JSON `1.0` 不合法）。范围：`window_hours` 1..87600，`slot_minutes` 0..5256000 且 `slot_minutes <= window_hours * 60`，`allowed` 0..2147483647。越界 → `v13: quota policy`。

资格（`v13_quota_eligible(p_sid uuid) RETURNS boolean`，STABLE）：

- 计次：`events` 中 `session_id = p_sid AND type = 'turn/material_spent' AND at >= v_now - make_interval(hours => window_hours) AND at <= v_now` 的行数（r4 上界：直接 INSERT 可显式给未来 `at`，不设上界则未来收据提前占用额度且永续计入）。**时钟（r2 修订，R13 必裁子点）**：`v_now` = 函数入口**单次捕获**的时间值存局部变量，窗口下界与 slot 间隔两个比较共用——草案 = `transaction_timestamp()`（与 `events.at` 默认 `now()` 同族同事务冻结，函数保持 STABLE）；替代 = `clock_timestamp()` + 函数改 VOLATILE（真墙钟，但与母计划 D9「STABLE 重算」字面冲突，须 R13 明示放行）。禁用裸 `clock_timestamp()` 直填比较式（同函数两次取值不同瞬间 + STABLE 语义冲突）。
- `slot_minutes = 0`：只看计次。`count < allowed` 为真。`allowed = 0` 恒假。
- `slot_minutes > 0`：再要求不存在该会话一条 `turn/material_spent` 其 `at` 介于 **闭区间 `[v_now - make_interval(mins => slot_minutes), v_now]`**（r26 边界统一——旧文开区间与总窗口的 `>=` 下界规则矛盾；现在两处同为包含下界）。这是**最小间隔**，不是按槽位合并计数。
- 边界：`at` 恰好等于下界的行计入窗口（`>=`）。
- 范围是**本会话**，不沿 `v_goal_tree` 上卷。子会话各自的收据各自计。树上的席位仍只由 `spawn_budget` 管。
- 比较瞬间只用计次条目定义的 `v_now`（单次捕获局部变量）；被比较的存储值只用 `events.at`。不用 `effects.created_at`，不用 `turn_no`，不用 closeout 收据里的 `spent.material_count`（那是全会话累计，**观察** spawn 文件里 closeout 的 `spent` 对象），不用裸 `clock_timestamp()` 直填比较式。
- 缺行或形状错：`RAISE 'v13: quota policy'`。不要把缺行当成「无限额度」（那是 fail-open）。
- 种子把 `allowed` 与 `window_hours` 放到回归碰不到的松值。真正的产品额度是后续策略版本，不是本 stage 偷偷选一个 8。测试用自己的紧版本（`allowed=0` 或 `allowed=1` 加夹具收据）证明假路径。

能力策略 `capabilities` version 1（r19 形状规则补全）：顶层键恰为 `required`、`schema_version`；`schema_version` 为 JSON 整数 1；`required` 为文本数组、元素非空不含 `'::'`——多余键、版本非 1、`required` 非数组（字符串/对象）、元素非字符串均 → `RAISE 'v13: capabilities policy'` 零写（四类负例进 §4.4）：

```json
{"schema_version": 1, "required": []}
```

```text
v13_missing_capabilities(p_sid uuid) RETURNS TABLE (name text)
  STABLE INVOKER
  SET search_path = pg_catalog, public
```

- 被减数（要求）= 政策 `required` 文本数组，元素含重复即政策错误（不静默去重）；元素必须是非空文本且不含 `'::'`（与工具名语法同一方向）。
- 减数（已有）= `tools.name WHERE enabled`。会话 id 只用于「会话必须存在」，不参与过滤（目录是全局的，**观察** `tools` 无 session 列）。
- 返回要求减去已有，按 name 升序。空要求 → 零行。
- `human_reward` 不进种子，函数源码不出现该字面量，不插入 tools 行，不 UPDATE decisions。测试把 `human_reward` 放进 required 的新版本时，它作为缺失名返回，advance 不入队，已有 effect/decision 行数不变。
- 安装探针：`tools.name` 与 `tools.enabled` 不存在 → `RAISE 'v13: capabilities baseline'` 停工。禁止改从 events 猜一套减数。
- 缺策略行：`RAISE 'v13: capabilities policy'`。与「required 为空数组」不同：空数组是合法的「没有额外要求」。

**影响面。** stage 27 两函数、两策略行、should_run 翻版、§1.6 的索引。

**生产绑定。** 松种子意味着上线后默认不因配额停跑。README 写明：收紧 = 新 `quota_window` 版本并翻转 active，不改函数。禁止把松种子描述成「已配置 24 小时 8 次」。

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| D9-alt-quantize | `slot_minutes` 把收据折成时间桶，一桶算一条（桶计次） | 要另外规定网格原点（epoch 对齐还是会话创建对齐）；与下行 lane 3 案不同物 |
| D9-alt-slot-grid | （**codex lane 3 形**）`window_end` = 最新事件 `at` 向下归一到 slot 网格，`window_start = normalized_end − window_hours`；计次仍逐收据；`slot_minutes` 必须为正且整除窗口（`=0` 非法——本计划种子 `slot_minutes:0` 在此形下是政策错误） | 与 D9-alt-event-now（只换时钟）不同：这是第三种 slot 语义。若 R13 采此案，连带改四件：资格 SQL、§4 gate 夹具、种子行、范围校验 |
| D9-alt-event-now | 禁止 `clock_timestamp()`，窗口末端 = 最新事件 `at`，源码不得出现 `clock_timestamp()/now()`（**codex 残稿立场——三通道分歧点**） | 支持方论点：严格「只用事件列」，会话空闲时窗口不滑走。草案反驳：会话越闲下界越往过去跑，旧收据更不容易滑出，资格更严，与「墙钟窗口」相反；D9 的 `window_hours` 是墙钟长度。`clock_timestamp()` 不是新存储列。若 R13 采此案：整段资格 SQL 重写、§4 的窗口 gate 用例改夹具，且 stage 27 前须再裁「空闲会话的资格语义」 |
| D9-alt-tree | 计次上卷整棵 `v_goal_tree` | 与 `spawn_budget` 的席位混成两套树预算。函数参数是单会话 |
| D9-alt-tight-seed | 种子 `window_hours=24, allowed=8, slot_minutes=0` | 现有长测试里的 harness 收据可能超过 8，回归红了分不清是门写错还是种子过紧。紧值放测试版本 |
| D9-alt-events-minus | 能力减数 = 本会话事件里出现过的 tool 名 | 「用过」≠「目录里启用」。L38 是入队前的能力差。目录不存在才停工 |

### 1.9bis D9-material-time 子题（r32 新增，R13 必裁）

`v13_material_time_honest` 触发器是新增的**生产写路径约束**（事务龄 >60s 的合法 material 写入会失败），且带「唯一 writer」替代——二选一必须落裁：**① 采用 INVOKER 时间守卫**（生产写入满足 `NEW.at ∈ [v_wall-60s, v_txn]`；保留表属主/超户测试回填豁免）；**② 禁止 raw material INSERT，material 事件只经唯一具名 writer**（写口收敛）。落裁前 stage 27 不开工（§1.10 清单含此题）。

### 1.10 裁决记录模板（R13 记录文件用，不在本文件填结果）

裁决终态（r41）：九题、七分歧、十小题、时钟子点与 §1.9bis **已全部落裁**（R13 记录 §0 + R13b 补记）：①explore RAISE 先行（唯一假路径例外）②终态停/复 → `v13: goal lifecycle` ③**查 operator（R13b）**④会话级停复⑤busy 含 ready|claimed|unknown 且终态先于 busy⑥**`resolve/failed` 保留（R13b，门前审计例外）**⑦八类排除集⑧stage 26 装 `trg_sessions_parent_immutable`⑨接受复活超售残留并入台账⑩numeric 析取 seq 不变量；L5 附言 = 采纳推荐即接受「返回行数预算不限制源遍历」边界；窗口时钟 = 单次 `transaction_timestamp()` + STABLE；D9-material-time = **①时间守卫**。未采纳分支与「若 R13 采…」条件施工语句已从正文删除；替代项表保留为裁决史。

## 2. 探针证据底座

开工当天、写该 stage SQL 之前重取。历史锚只供对照。dump 放仓库外临时目录，不提交。底稿一律 `pg_get_functiondef`，禁止从 `v13/triage/v13_triage.sql` 或 `v13/spawn/v13_spawn.sql` 回贴 advance。

| 对象 | 历史锚（2026-09-27） | 实施时要确认的性质 |
|---|---|---|
| `v13_advance(uuid,jsonb)` | triage `:561-1000` | 含 `v13_triage_prework`、`v13_bind_worktree_from_prepare`、`turn/material_spent`、`spawn_fanout`、两处 `spawn batch-dispatched`；INVOKER；无把异常收成 `waiting` 的 EXCEPTION；proconfig 按 dump 保留 |
| 入队点 | `:737 :787 :811 :827 :842 :858 :889 :934 :968 :970 :981 :986` | 用语句重新点名：approval enqueue、continuation enqueue、prework 内 human/llm、abandon、context_refresh、budget human、judge、steer 所触发的 enqueue、route CASE 的 tool/llm/human、sql 臂的 INSERT effect。stage 26 不必逐臂包住，P-tail 的 prework 检查必须挡在 steer/route 之前 |
| `v13_triage_prework` | `:359-397` 一带，duty 分支锚 `:372` | duty=0 写 `triage/hold` 且 reason 只许 `duty_cycle`；返回 `'waiting'` |
| `v13_triage_duty` | `:45-56` | 只读策略 `triage`，值域 `'0'\|'1'` |
| `v13_triage_hold_blocks_recover` | `:553-560` | duty=0 且 hold seq > `v13_last_user_seq` |
| `triage/hold` 守卫 | `:229-233` | reason 必须等于 `duty_cycle`；本阶段不改 WHEN 列表 |
| `v13_recover_idle` | triage `:1186-1247` | 含 duty 跳过；返回 jsonb `pending`/`nudged`；SKIP LOCKED；**lifecycle 读必须在 `FOR UPDATE SKIP LOCKED` 之后，不得锁外先读** |
| `v13_triage_block_explore_spawn` | 本体 `:516-533`；advance 调用 `:643`（spawn IF 之外、先于一切 spawn 门） | explore 路由的待派发调用在任何投影状态下仍 RAISE `v13: explore spawn`（§1.1 例外集）；实施时确认它与 P-spawn 读点的先后与 §1.1 一致 |
| `v13_spawn_subsession` | spawn 函数内 cap 前置与复检，脚手架 `:425-426`、`:456-457` | 三个 RAISE 文案仍在；本阶段不换体；**fanout/depth 在锁前（`:417-422`）、cap 在锁内——`v13_spawn_batch_allowed` 把三检查都放进同一咨询锁是有意扩展（非逐字镜像），预检锁序须与 spawn 函数兼容且锁可重入** |
| `v13_advisory_class` | `:32-41` | `'spawn_budget'` → `13001` |
| `v13_spawn_occupancy` | `:159-188` | 非终态后代计数，不含 root |
| `v_goal_tree(uuid)` | `:467-506` | 7 列与终态闭集 |
| `v13_insert_nudge` / `ux_events_recover_nudge` | `:189-208` | 幂等冲突只吞该约束名 |
| `v13_state_hash` | control `:362-400` | 排除名单仍只三 `session/*` |
| `turn/material_spent` 守卫 | control `:444-446` | 键恰 `effect_id`,`schema_version` |
| events 形 | schema `:28-43`、`:48-49`、`:57-59` | `at` 存在；UPDATE/DELETE RAISE；无 `at` 索引 |
| `v13_policies` / frozen / `v13_policy` | `:701-740` | INSERT 允许；value 改写拒绝 |
| `v13_route` | `v13/loop/advance.sql:78-162`（函数锚 `:110`） | 返回词无 spawn |
| `v13_recovery_active` | economy `:141-155` | 使用 `events.at`；**不是** `window_hours` 的实现样本 |
| `SQL_LOAD_ORDER` | `v13/load.py:17-40` 与 `STAGE_THROUGH` | 复核日末项必须是已绿的 handoff=25，否则不追加 26 |

**证伪即停（不发明兜底）：**

1. dump 的 advance 不含 `v13_triage_prework`，或含会吞 `v13: spawn budget cap` 的 EXCEPTION。（活体唯一 EXCEPTION 块只包 sql 臂的 `EXECUTE`（`:921-932`），今日吞不到 cap；探针保留为防回归。）
2. `v13_triage_duty` 值域已不是 0|1，或 duty=0 不再写 `triage/hold`。
3. `events.at` 不存在或类型不是 timestamptz。
4. append-only 触发器不再拒绝 `events` 的 UPDATE/DELETE（指纹与「滑出窗口不改历史」都依赖它）。
5. `v13_policies_frozen` 拒绝 `should_run` / `quota_window` / `capabilities` 的 INSERT。原样记录 RAISE，不改触发器。
6. 同名函数探针**按 stage 参数化（r16）**：各 stage 只检查**本 stage 新增对象**不预存在——stage 26：`v13_should_run`、`v13_should_run_gate`、`v13_policy_share`、`v13_sessions_parent_immutable`、`trg_sessions_parent_immutable`；stage 27：`v13_quota_eligible`、`v13_missing_capabilities`、`v13_material_time_honest`、`trg_material_time_honest`；stage 28：`v13_spawn_budget_snapshot`、`v13_attention`、`v13_scheduler_hint`；stage 29：`v13_goal_fold`、`v13_goal_lifecycle`、`v13_goal_fingerprint`、`v13_goal_stop`、`v13_goal_resume`、`v13_spawn_batch_allowed`——且**断言前序对象存在且形状正确**（不因自身合法前置产物自阻）。
7. 已存在 `type IN ('goal/stopped','goal/resumed')` 的行（stage 29）：列 session/seq 后 RAISE `v13: goal baseline`。
8. `v13_state_hash` 已变成白名单，或排除名单已含 `goal/stopped`。停工报事实（换体替代案已否决——R13 记录）。
9. 加载序末尾不是已绿 handoff（25），又没有台账书面弃权写明「stage 26 底稿 = stage N dump」。不把 26 编成 23。
10. 长度断言：全库已核查**只有** `>=16` 类放宽断言（`v13/mgraph_assembly/test_mgraph_assembly.py:375`），无 `==20/==22`。本条降为防回归探针：若后续提交引入等值断言，停并请例外，不在 Phase C 改历史测试；出现在 `v13/load.py` 自身或后 stage 可改文件里的，按既有 `>=` 精神放宽，与对应 stage 同提交。
11. `blocked_unknown` 会话上 append 一条非 lifecycle 普通事件导致 unknown 墙 RAISE：stage 29 停工报事实，不改墙。探针在安装 stop 函数**之前**、独立事务里直接 `v13_append_event` 做（r4：不能经 stop 函数走——busy 含 unknown 后它先 `v13: goal busy`，那不是墙故障）；失败则 ROLLBACK 探针数据。配套断言：blocked_unknown 会话上 stop 的预期 = `v13: goal busy`。
12. Phase B 符号缺失：`v13_control_operator()`、`v13_control_authorized(uuid,uuid)`、`v13_extract_handoff`、`v13_handoff_emit`、`handoff_policy` 活动行。缺失则对应 stage 停，不在 C 里补做 B。
13. `v13_pending_human` 的返回类型不再是 boolean。停，不重写 human 查询。
14. 活体 advance 对未知 event type RAISE（脚手架记「今日只读 `llm/message|tool/result`，开放 type 不 RAISE」，锚 `v13/loop/advance.sql:126` 是 **route 的过滤**，不是全库保证）。实施时在 dump 的 advance/route/守卫 WHEN 列表上确认 `goal/stopped` 不会被既有守卫误伤。误伤则停，报 WHEN 列表，不改 stage 17/20/21/25 的守卫文件。
15. （安装义务，非证伪——r15 移出「证伪即停」）`parent_session_id` 写口授权面：`v13_route` 与 `v13_spawn_owner` 均有 sessions 的 UPDATE，`parent_session_id` 无列级保护——这是**预期事实**，不停工；执法由 stage 26 的 `trg_sessions_parent_immutable` 承担（§3.2 步 9a）。安装前只核对授权面事实与函数/触发器名尚未存在（与 §3.1 步 3 同句，r19）；「fork INSERT 不误伤、改 parent 必 RAISE」的行为断言在 §3.2 步 9a 安装之后与 `test_parent_immutable` 里做。若 R13 否决小题⑧（守卫），则 stage 29 的 root-walk/锁序须重裁（§1.10）。

**允许的适配（写入该 stage README，不是证伪）：**

| 探针 | 适配 |
|---|---|
| advance dump 比 triage 文件多出 Phase A/B 插入 | 以 dump 为准；差集只增加本计划的块 |
| `v13_pending_human` 仍为 boolean | 直接用 |
| prework 除 advance 外还有调用者 | 换体保持原签名与默认行为；新检查只在原 `RETURN NULL` 与入队之前，调用者多一次 STABLE 读 |
| `transaction_timestamp`（同 now() 族，恒可用）| 按草案单次捕获；若 R13 改选 D9-alt-event-now 或 clock+VOLATILE，整段资格重写后才能安装；**禁止改回裸 clock_timestamp 直填比较式** |
| 测试库没有可复制的 harness continuation 夹具 | 仍须造最小前驱（见 §3.4），不把该用例降级成只做源码 grep |

探针失败：进程退出码非 0，不进入 `CREATE OR REPLACE` 段。

## 3. Stage 26 `v13/should_run/`

### 3.1 前置

1. R13 对 D10-A 与 D10-B 已有采纳项；§9 复核 GO；加载序以 handoff=25 结尾。
2. 当日 dump：`v13_advance`、`v13_triage_prework`、`v13_triage_duty`、`v13_pending_human`、`v13_unconsumed_cancel`。
3. §2 证伪 1、2、5、6、9、10、12（operator 函数）先跑（r18 收窄）；**§2 第 15 项在写 SQL 前只核对授权面事实与触发器名字尚未存在——「fork INSERT 不误伤、改 parent 必 RAISE」的行为断言在步 9a 安装之后与 test_parent_immutable 里做，不在安装前停工。**
4. 全文检索 `v13_triage_prework(` 的调用点。预期只有 advance。若有第二调用点，README 列出，换体不得改变「duty=0 仍写 hold」的返回合同。

### 3.2 SQL 序（`v13/should_run/v13_should_run.sql`，单事务）

1. DO 安装前：`to_regprocedure` 确认新名字（含 `v13_policy_share()`）不存在；`triage` 活动行存在；advance 源码含 `v13_triage_prework` 与 `v13_bind_worktree_from_prepare`；prework 源码含 `duty_cycle`。失败 `RAISE 'v13: should_run baseline'`。
1b. `CREATE FUNCTION public.v13_policy_share() RETURNS void`——PL/pgSQL、VOLATILE、**SECURITY DEFINER**、`SET search_path = pg_catalog, public, pg_temp`、体内业务名全限定；**函数体 = §1.1 三步循环原文（r39 逐字贴入）**：①快照读五名当前 active 的 `(name, version)` 身份；②按固定序对这些**精确身份**（`WHERE name = ? AND version = ?`，不带 active 谓词）`SELECT ... FOR SHARE`——`name IN ('capabilities','quota_window','should_run','spawn_budget','triage') ORDER BY name`（真实字母序；缺行跳过不 RAISE——gate 自报缺行文案）；③新语句重读 active 身份，与①相等则返回，不等则重试；`ALTER OWNER TO v13_spawn_owner`；`REVOKE EXECUTE FROM PUBLIC`；`GRANT EXECUTE TO v13_route`。安装后 DO 断言：`prosecdef=true`、owner=v13_spawn_owner、proconfig 精确含 search_path（pg_temp 末位）、`aclexplode` 上 route 有 EXECUTE 且 PUBLIC 无；**helper prosrc 源码断言：含重读循环、锁语句无 `AND active`、`ORDER BY name`、五名集合**（wrapper 的「恰一处 policy_share( 且零 FOR SHARE」断言在 stage 29（步 15 DO + survives_govern），不放 stage 26——彼时 wrapper 不存在）。
2. `CREATE FUNCTION v13_should_run_gate(uuid)`，§1.2。只实现四个 id。
3. `CREATE FUNCTION v13_should_run(uuid)`，一行包装。
4. INSERT `should_run` version 1 active，值用 §1.2 的种子。插入前断言 name 未占用。
5. `CREATE OR REPLACE v13_triage_prework(uuid)`：底稿 = dump。文本差只有**一段**（r35）：duty 的 `RETURN 'waiting'` 之后、`IF v_dec='human'` 之前的无条件 should-run gate（**`v_reason := v13_triage_fold_reason(...)` 留在原语句位不提前——gate 为假立即 `RETURN 'waiting'`，不调用 fold_reason**；假则同句 UPDATE + `RETURN 'waiting'`，不写 `triage/hold`）。`reject` 与 duty 分支字节保持 dump。原「RETURN NULL 前第二处检查」删除（单一 gate 覆盖三条出口与 RETURN NULL 路径）。
6. `CREATE OR REPLACE v13_advance(uuid, jsonb)`：底稿 = dump。文本差：①**无条件 `PERFORM public.v13_policy_share()`，插入点 = explore guard 的 PERFORM（`:643`）之后、`IF jsonb_array_length(v_calls) > 0` 之前（IF 外——空 v_calls 的 harness 入队与 prework/route 入队也要持锁，r35 grok[34-1]）**；②P-spawn 读点 = `IF NOT public.v13_should_run(p_sid) THEN defer; END IF`（IF 内、`v13_spawn_children` 前；`v13_spawn_batch_allowed` 是 stage 29 对象不得引用；不设旗标）；defer 体内 = `UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid AND status IN ('ready','waiting')`（必须带 session_id 谓词）+ `RETURN 'waiting'`，不写 `triage/hold`；③**P-harness 两臂臂首各一处 `v13_should_run` 调用（r36，grok[35-2]——「恰一处」会放走 approval/continuation 出口：P-spawn 在 v_calls IF 内且成功即 progressed、与 harness 不同路，无 tool/call 时根本不执行；continuation 的 route/enqueue 在 prework 之前，单 gate 挡不住）：approval 臂从其 budget closeout 前、continuation 臂从 budget closeout/route 前，臂内各自调用、禁止跨 material 复用缓存**；④**审计豁免预检（R13b）**：调用 prework 之前，`IF v13_triage_duty()<>0 AND NOT public.v13_should_run(p_sid) AND p_snap->>'failed' IS NOT NULL THEN` 按原 `:803-808` 载荷 append `resolve/failed`（这是第四处 should_run 调用；duty=0 不预写）；⑤steer/route 前不另调；**P-tail 仅由步 5 的 prework 单一 gate 承担——advance 在该预检与 prework 之后不再有任何 `v13_should_run`**。DECLARE 不新增局部量。不重排前缀，不移动 material 写入，不改返回词，不加 search_path（除非 dump 已有）。
7. 步骤 5 与 6 同一事务。安装后 DO：`has_function_privilege('v13_route', ...)` 对两个**旧**函数仍为真（OR REPLACE 不得丢 GRANT）。
8. `REVOKE EXECUTE` FROM PUBLIC 只针对两个新函数。GRANT 只给 `v13_route`。不授 worker / recall / resolve / spawn_owner / PUBLIC。
9. **安装 `trg_sessions_parent_immutable`（步 9a，r15 全合同）**：先 `CREATE FUNCTION v13_sessions_parent_immutable() RETURNS trigger`——**INVOKER、`SET search_path = pg_catalog, public`、仅当 `OLD.parent_session_id IS DISTINCT FROM NEW.parent_session_id` 时 `RAISE 'v13: parent immutable'`、否则 `RETURN NEW`，随后 `REVOKE EXECUTE FROM PUBLIC`、不 GRANT（r20：与 goal guard 同句，点火无需 EXECUTE；保留默认 PUBLIC 与红线冲突）**；再 `CREATE TRIGGER trg_sessions_parent_immutable BEFORE UPDATE OF parent_session_id ON sessions FOR EACH ROW EXECUTE FUNCTION v13_sessions_parent_immutable()`。基线断言：两对象名不存在；安装后断言 `pg_get_triggerdef` 含 `BEFORE UPDATE OF parent_session_id`、fork 的 INSERT 建边路径不受影响。除本触发器外无 COMMENT、无其他触发器、无索引、无 GUC。小题⑧采纳是 stage 26 硬依赖（§1.10）。

`setup_db.py`：数据库名 `agent_v13_should_run`。照 triage/seam 的嵌入式 Postgres 与 `load_stage(server, db, 'should_run')`。扩展探针若 triage 的 setup 有，照抄调用方式，不新造加载器。

### 3.3 状态流

- 触发：driver 或测试调用 `v13_advance`。投影本身没有触发器。
- 数据：策略行 → `v13_should_run_gate` → 布尔 → advance 的三个读点。同一事务里 harness 若已写下 `turn/material_spent`，后面的调用看得到；stage 26 的四门不读该事件，这条「现查」是给 stage 27 留的不变量。
- 执行上下文：调用者的后端，会话锁已持有（advance 在读点之前已经 `FOR UPDATE`）。无后台 worker，无队列。
- 观察者：返回文本；`effects` 行数；`events` 类型计数；`sessions.status`。
- 乱序：投影不写入，重复调用结果由策略与前缀状态决定。策略翻版在别的事务提交后，下一条 SQL 才看得见（READ COMMITTED）。同一 advance 内不翻版。
- 中断：`statement_timeout` / 客户端 cancel 回滚整笔 advance，包括已经执行的 material 追加。下一笔 advance 的 material 写入是「尚无则写」（**观察**：活体 `IF NOT EXISTS ... turn/material_spent`），重试不会少收据。
- 假路径不写事件，所以与 duty=0 的可观察差别是：有没有 `triage/hold`。测试必须同时看返回词和该 type 的行数，禁止只看 `'waiting'`。

### 3.4 Gate（`uv run python v13/should_run/test_should_run.py`）

夹具水准：用 `v13_route` 的 `SET ROLE` 跑至少一条会写账的 advance（超户绿不算这条）。快照构造从**当时最新 stage 测试**里已有的 probe/envelope 帮手复制，不新定义一套 snap 键。下面每个名字是测试脚本里的一个函数，`main` 顺序调用，任一失败则退出码 1。

**探针与 RED**

- `test_install_markers`：`to_regprocedure('v13_should_run(uuid)')` 与 `v13_should_run_gate(uuid)` 非空；`provolatile='s'`；`prosecdef=false`；`proconfig` 含 `search_path=pg_catalog, public`。
- `test_policy_share_contract`（r35）：签名 `(void) RETURNS void`、VOLATILE、SECURITY DEFINER、owner=v13_spawn_owner、proconfig 精确含 `search_path=pg_catalog, public, pg_temp`（末位）；`aclexplode`：route 有 EXECUTE、PUBLIC 无；`SET ROLE v13_route` 直调成功（不 42501）。
- `test_policy_share_flip_blocks`（r37 定稿日程——stage 26 只打 **helper**（wrapper 尚不存在），grok[36-2]/codex[36-2]）：①源码断言（stage 26）：helper prosrc 含重读循环、锁语句无 `AND active`、`ORDER BY name`、五名集合——wrapper 的断言移 stage 29；②行为臂（r39/r40 时序定稿——**B 先持、A 后堵**；本臂与 §6.4 的 A 先持方向相反，按箭头顺序施工，勿互相照抄）：B 同一事务先 INSERT `should_run` version 2（active=false）、UPDATE 灭活 version 1 后**停住不提交**；A（`SET ROLE v13_route`，显式事务）再调 helper → 堵在 `should_run` v1 的 FOR SHARE 上；**此时第三条连接（未提交）对 `spawn_budget` 的 UPDATE 不阻塞（`pg_locks` 只见 A 等 v1——锁序钉；观察一完成第三条连接立即 ROLLBACK）**；B 激活 v2 并 COMMIT；A 解阻重试后持有 **version 2** 的 FOR SHARE（身份漂移循环钉）；**反向竞态：C 对 version 2 的灭活 UPDATE 阻塞至 A COMMIT**；③锁序反转钉（stage 29 补；r38 前置修正——A 若仍堵在 `capabilities` 首行，B 对 `spawn_budget` 的首条不阻塞）：A 以 `SET ROLE v13_route` 调 `v13_spawn_batch_allowed` **返回后事务保持不提交**（五行 FOR SHARE 已持有）→ B 第一条语句 = `spawn_budget` 灭活 UPDATE → 该语句在 `pg_locks` 阻塞；wrapper prosrc 恰一处 `v13_policy_share(` 且零 `FOR SHARE`（步 15 DO + `test_policy_share_survives_govern`）。**
- `test_red_note`：README 记录「安装前 `to_regprocedure` 为空」已在安装 DO 里作为 baseline。脚本只断言安装 DO 的文案函数存在性，不重复制造未安装库。

**直接调用矩阵 `test_gate_matrix`**

- 活动种子、普通 ready 会话、无 human、无 unknown、无 cancel、duty=1：gate NULL，布尔真。
- 同一会话插入 ready human：获胜 id `human_pending`，布尔假。再把该 effect 打成 succeeded 或删不掉就换新会话：回到真。不读 status 做终态拒绝——completed 会话若无其它门，布尔仍真。
- `blocked_unknown`（或一枚 unknown effect，用现有测试造墙的方法）：`unknown_wall`。
- 写入一条 `cancel/requested` 且会话非终态：`unconsumed_cancel`。
- duty 翻到 0（新 triage 版本，双 UPDATE，SAVEPOINT）：默认种子下 gate 仍 NULL（shadow）。这是 shadow 的钉。
  - 未知 uuid（**正常 triage 策略与坏 triage 策略各一条，r14**）：文案 `v13: unknown session %`，含该 uuid（坏策略下也不得先报 `v13: triage policy`）。
- 策略 v2 把 `human_pending` 与 `unconsumed_cancel` 都设为 block，夹具同时满足两者：数组里谁在前，谁是返回 id。再翻一版对调顺序，返回 id 对调。函数体在两次调用之间不做 OR REPLACE（断言 `pg_proc.oid` 不变）。ROLLBACK 回种子。
- 坏尾负例（r6）：策略数组首位是条件成立的 block 门、尾部追加未知 id（或重复 id）→ 仍 `RAISE 'v13: should_run gate'`（两阶段校验的钉，不允许短路掩盖损坏策略）。

**duty 行为不变 `test_duty_unchanged`**

- 默认 should_run 种子，triage duty=0，无未认领 tool/call，无 ready effect：advance 返回 `'waiting'`；`triage/hold` 恰一条且 reason `duty_cycle`；effect 行数不变；status `waiting`。再 advance 一次：hold 仍一条（活体的 EXISTS 幂等）。
- 对照 duty=1：不写 `triage/hold`。
- `v13_recover_idle`：duty=0 且 hold 新于 last user seq 时，该会话 nudged 增量 0。这是换体不得碰 recover 的行为钉，stage 26 不换 recover。

**前缀高于投影 `test_cancel_not_blocked_by_projection`**

- should_run 版本把 `duty_cycle` 改成 block，同时 triage duty=0，并且已有未消费 cancel、无 claimed、无未终态子会话：advance 返回 `'terminal'`，会话 `cancelled`，存在 `session/cancelled`。若门被错误地放到前缀之前，结果会是 `'waiting'` 且未 closeout。ROLLBACK 策略。

**spawn 读点（r12 夹具前提：调用前断言不存在 `status IN ('ready','claimed')` 的 effect——活体在聚合 tool/call 与 P-spawn 之前就对 ready/claimed 早退 waiting，同形结果会盖住门的行为；unknown 会落 blocked_unknown，测红不是假绿）**

- **`test_spawn_suppressed_when_duty_block`**（r7 补 status 断言）

- 造一个能被 stage 18 测试接受的未认领 `tool/call`（载荷过 `v13_spawn_event_guard`：`spawn_subsession`、单 `task`、合法 id；**route reason 非 explore**）。父会话有 user/message（spawn 要求 `next_seq>=1`，**观察**）。
- 策略 A：duty=0 且 duty 门为 **shadow**（默认）。advance **仍 spawn**（子会话增加或 `spawn_fanout` 出现，返回 `'progressed'`）。这是「默认不改变 duty=0 先 spawn」的钉。预算须足够，否则这个对照无效，测试失败而不是跳过。
- 策略 B：同一夹具形状，duty=0 且 duty 门为 **block**。advance 返回 `'waiting'`；**`sessions.status='waiting'` 且无 `triage/hold`、无关会话 status 不变（r9）**；子会话数不变；无新 `spawn_fanout`；无新 effect；`tool/call` 行还在。harness 段无前驱时不会 closeout。
- `test_explore_raise_survives_gate`（本目录 `test_should_run.py` 的 main 清单内，r10 落位）：存在未认领且 route reason = explore 的 tool/call，should_run 为假时 advance 仍先 RAISE `v13: explore spawn`、零 effect、零 `turn/route`（§1.1 唯一例外；防换体把误用 RAISE 静默改成 waiting；无条件反转分支已删，r31）。
- `test_bad_spawn_shape_suppressed`（r7）：形状非法（过不了 `v13_spawn_children` 的形状检查）且 should_run 为假 → 返回 `'waiting'`、零新 effect、SQLERRM 不是 `v13: spawn args`（读点在 spawn_children 之前的钉）；同一形状且 should_run 为真 → 仍 RAISE `v13: spawn args`。源码断言 `v13_should_run` 调用出现在 `v13_spawn_children` 之前。

**结算不被门吞掉 `test_finish_closeout_despite_block`**

- 最小 harness 前驱：本会话一条 succeeded 的 `harness_turn` tool effect，`v13_harness_request_ok` 为真（control `:143`），`result_kind=finish`，origin 等于当前 last user seq，无 open children，无 ready/claimed。duty 门 block 且 duty=0（或任何能让 `v13_should_run` 为假的已实现 block——此夹具用 duty block）。advance 返回 `'terminal'`，status `completed`。若有人把整个 harness 段包进门里，此用例失败。

**审计豁免 `test_resolve_failed_audit_exemption`（R13b；R13c-B 双臂分阶段）**：stage 26 只验**负臂行为**——duty=0 时该预检不写 `resolve/failed`（事件零行，duty 分支行为不变的钉）；**源码验收**：预检的三个合取项（`v13_triage_duty()<>0` / `NOT public.v13_should_run(p_sid)` / `p_snap->>'failed' IS NOT NULL`）与 THEN 分支的 `resolve/failed` append 都位于 prework 调用点之前。**正臂行为（门假+duty<>0+snap.failed → 先 append resolve/failed 随后 prework 单 gate 返 waiting、零新 effect、无 triage/hold）写入 stage 27 的 done-when**——stage 26 无夹具可达（前缀三门早退先于预检点，duty_cycle 门与预检条件互斥），不得造非真门夹具。（r41 的双臂同阶段验收按 R13c-B 废止。）

**入队被挡住 `test_continuation_suppressed`**

- 前驱 `result_kind=progress`，且已有该 effect 的 `repair/required`（因此 `v_cont` 为真、`v_cand` 为假，**观察** advance 里这两个布尔的定义）。无 ready/claimed。duty block + duty=0。advance 返回 `'waiting'`；不存在新的 `continuation_index = 旧+1` 的 harness effect；**无新 `turn/route`（harness_continuation）事件**（活体该臂先写 route 再入队（`:777-779` → `:787`），门必须从 route 追加之前包起（§1.1 P-harness）；**无关会话 status 不变、无 `triage/hold`（r9）**）。会话不终态、**本会话 `status='waiting'`（r10）**。`repair/required` 行数不变。

**prework 入队 `test_prework_enqueue_blocked`**

- 无 tool/call、无 harness 前驱、duty=1，夹具使 `v13_triage_decide` 返回 `human` 或 `decompose`（用现有 `goal/override` 事件，**观察** `v13_submit_override` 的 intent 闭集 `direct|decompose`）。默认种子：advance 会入队（effect 数增加）或返回 waiting 且有 human/llm effect。stage 26 在 duty=1 且四门都不 block 时投影恒真——**唯一能在无 cancel、无 human、无 unknown、duty=1 时为假的已实现门不存在**。处理：本函数在 stage 26 **只做源码断言**（prework 源码在**三条入队出口的共同入口**出现 `v13_should_run`——含 `v_reason` repair/replan_cap 支，r33），行为假路径改由 §4 的 `allowed=0` 覆盖，README 写明「prework 行为假路径的证明在 stage 27」。**stage 27 对应函数（写死名）：`test_quota_blocks_prework_enqueue` + 新增 `test_quota_blocks_repair_replan_enqueue`（v_reason=repair_cap/replan_cap 夹具 + `allowed=0` → advance `'waiting'` 零新 effect）**。禁止删断言。

**`test_parent_immutable`（r14）**：并发/直改 `parent_session_id` → RAISE `v13: parent immutable`（含 route 与 spawn_owner 身份）；改 `status` 等其他列仍成功（守卫只锁该列）；fork 的 INSERT 建边路径不受影响。

**源码差集 `test_source_delta`**

- 测试进程保留安装前 dump（临时文件，不入库）。`v13_advance` 的 prosrc 与 dump 的差集只含：恰一处 `v13_policy_share()` 调用（**`IF jsonb_array_length(v_calls) > 0` 之外**、explore 后、任一 `v13_should_run` 之前）与**恰四处 `v13_should_run` 调用（r41）：P-spawn 一处 + approval 臂一处 + continuation 臂一处 + 审计豁免预检一处（prework 前，R13b）**；advance 在 prework 之后无任何 `v13_should_run`（P-tail 单 gate 只在 prework 内）；不含 `v_defer_spawn` 与 `v13_spawn_batch_allowed`（stage 29 对象）。`v13_triage_prework` 差集只含恰一处 gate（`IF v_dec='human'` 之前）。
- 换体后 `v13_advance` 的 prosrc 中，`current_setting` 的出现次数与当日 dump 相同，为 1。这一次调用的文本是 `current_setting('statement_timeout', true)`，且 dump 中唯一 EXCEPTION 的 query_canceled 臂语句文本仍整段留在换体后的 prosrc 中。断言比较出现次数、该调用文本，以及该臂语句文本仍作为子串存在。`v13_triage_prework` 换体后的 prosrc 中 `current_setting` 的出现次数为 0。`goal/stopped`、`goal/resumed`、`v13_goal_lifecycle`、`quota/spent`、`quota/voided`、`v13.control_actor` 在两函数 prosrc 中出现次数都为 0。（R13c-A：预存起时守卫臂不是预实现，差集不得新增也不得清洗；其余六词仍绝对零。）
- 新函数 prosrc 不含 `INSERT`、`UPDATE`、`DELETE`、`v13_append_event`。
- 新 SQL 文件不含 `CREATE TABLE`、`CREATE VIEW`、`MATERIALIZED`、`ALTER TABLE`、`LISTEN`、`pg_terminate_backend`、`pg_sleep`。
- `v13_should_run` 的 prosrc 不含门 id 字面量（字面量只在 gate 函数）。
- 包装与 gate 对 worker、PUBLIC、recall、resolve 的 `has_function_privilege` 为假；对 `v13_route` 为真。`SET ROLE v13_route` 调用布尔成功。

**回归 `test_regression_note`：** 脚本自身不调用别的 stage；setup 或 CI 说明要求先跑 1→25。本 stage 的退出码脚本在本目录测试全绿后，由实施者按仓库既有回归方式跑此前全部 `test_*.py`。若仓库没有统一 runner，逐个 `uv run python` 当时 `STAGE_THROUGH` 里每个目录的 `test_*.py`，全部退出码 0。

### 3.5 收尾

- `v13/load.py`：末尾追加 should_run→26，与本目录同一次 commit。
- 矩阵追加行：直接调用真/假、shadow duty、cancel 仍 terminal、spawn 在 block 下被抑制、finish 仍 closeout、零写入、GRANT。不写 ✅ 直到该次提交的测试已经绿；提交信息里的矩阵行与实跑一致。
- 台账：只写 R13 分配的号。主题 PC-1 = 三读点而非单点早退；PC-2 = duty 默认 shadow。
- README：读点表、返回语义、`>` 的定义、生产绑定一格（库内已生效）、不预写停/复。
- 提交信息方向：`v13: gate new effects with should_run`。回退 = revert 该提交。不 `git add -A`。

### 3.6 错误与边界

| 操作 | 失败 | 传播 | 留下的状态 |
|---|---|---|---|
| 策略形状坏 | `v13: should_run policy` | 抛出，advance 回滚 | 调用前 |
| 未知门 id | `v13: should_run gate` | 同上 | 调用前 |
| 未知会话 | `v13: unknown session %` | 同上 | 无行 |
| duty 策略坏 | `v13: triage policy` | 原样 | 调用前 |
| 假 | 无异常 | `'waiting'` | 无新 effect；defer 时 tool/call 还在 |

空会话（无事件）直接调布尔：四门里 human/unknown/cancel 为假，duty 按策略，通常真。advance 对这种会话是否还能入队，保持 dump 行为（投影真则不动）。

## 4. Stage 27 `v13/quota_window/`

### 4.1 前置

1. R13 对 L6 与 §1.9 已采纳；**§1.9bis 已裁①时间守卫（R13 记录 + R13b）**。D9 公式不再讨论。
2. stage 26 已在加载序中，`v13_should_run_gate` 身份仍是 `(uuid) RETURNS text`。
3. §2 证伪 3、4、5 重跑。确认 `turn/material_spent` 载荷守卫仍是两键。
4. 不换体 stage 26 的 advance。只换 gate 函数。

### 4.2 SQL 序（`v13/quota_window/v13_quota_window.sql`，单事务）

1. DO：`events.at` 存在；`ix_events_material_spent_at` 尚不存在；`quota_window` 与 `capabilities` 名字未占用；`v13_should_run_gate` 源码尚不含这两个 id（防止重复安装半截）。失败 `v13: quota baseline`。tools 列探针失败则 `v13: capabilities baseline`。
2. INSERT 两枚种子，形状 §1.9，均 active。
3. `CREATE FUNCTION v13_quota_eligible(uuid)`。源码比较的时间列只有 `events.at`。出现 `quota/spent`、`quota/voided`、`effects.created_at`、`turn_no` 即安装后源码断言失败（函数仍按草案写，断言在测试里）。
4. `CREATE FUNCTION v13_missing_capabilities(uuid)`。
5. `CREATE FUNCTION v13_material_time_honest() RETURNS trigger`（§1.9bis 已裁①） INVOKER `SET search_path = pg_catalog, public` + `REVOKE EXECUTE FROM PUBLIC`（不 GRANT），再 `CREATE TRIGGER trg_material_time_honest BEFORE INSERT ON events FOR EACH ROW WHEN (NEW.type = 'turn/material_spent') EXECUTE FUNCTION v13_material_time_honest()`（规则与基线断言见 §4.3 r29/r30 两瞬时合同与七臂；不改 stage 17 既有守卫；安装前断言两名不存在）。
6. 若 L6 采纳项是「加索引」：`CREATE INDEX ix_events_material_spent_at ...`（§1.6）。若采纳项是不加：本步不存在，测试改为断言该索引不存在。两支不要写成运行时 if。以裁决后的**一个** SQL 文件为准，替代项不留在安装脚本里。
7. 翻 `should_run` 到下一 version：复制上一活动数组并在末尾追加两个 block 门。双 UPDATE。旧 version 行保留。
8. `CREATE OR REPLACE v13_should_run_gate(uuid)`：底稿 = 当日 dump（stage 26 体）。差集只增加两个 id 的求值分支。未知 id 仍 RAISE。包装函数不换。
9. REVOKE PUBLIC + GRANT `v13_route` 于两个新函数（触发器函数**仅 §1.9bis 裁①时存在**——裁②随步 5 改写，不引用该触发器名，r34）。换体函数不 REVOKE ALL。
10. 无 COMMENT、无新表、无事件写入。

数据库名 `agent_v13_quota_window`。

### 4.3 状态流

- 资格每次从事件重算。收据滑出窗口后下一次调用变真，历史行还在。
- 无负债列、无负计数。`allowed=0` 是恒假，不是欠账。
- 能力差不写 tools、不写 decisions。
- 与奖励的边界：函数不读 `wait_reason`，不产生 `human_reward`。`wait_reason=quota` 的 harness 语义保持 stage 17 原样（**观察**：harness schema 里 wait_reason 含 `quota`，那是等待原因，不是配额账本）。本 stage 不把窗口资格写进 harness 结果。
- **material 时间诚实守卫（r26 新增；r27 规则定稿并落 §4.2 步 5——`events.at` 可由 INSERT 指定、route 有 events INSERT、stage 17 守卫不验时间：回填历史 at 可把收据滑出窗口绕过资格门）。规则：INVOKER 触发器函数（禁 DEFINER——current_user 恒属主检查恒放行），当 `current_user` 非 rolsuper 且非 events 表属主（生产写入面；不区分 at 显式/默认——行级触发器无法区分）时，`NEW.at` 必须满足 **`NEW.at >= v_wall - interval '60 seconds' AND NEW.at <= v_txn`**（r29 两瞬时合同，grok[28-1]+codex[28-2]：触发器入口**各捕获一次** `v_wall := clock_timestamp()`、`v_txn := transaction_timestamp()`——**下界用墙钟**（transaction_timestamp 冻结于事务开始，长事务等 61s 后插 at=事务开始的收据提交时已滑出窗口却过旧检查）、**上界用事务钟**（与资格函数 `v_now` 同源——纯 clock 上界会放行 `at ∈ (transaction_timestamp(), clock]` 的收据：资格计次与 slot 看不见、同事务 should_run 被绕过）。**禁止**：两次独立 `clock_timestamp()` 对拍、触发器内用同一 clock 做双侧、STABLE/DEFINER。违者 `RAISE 'v13: material time'` 零写；成功路径 `RETURN NEW` 不改写 `NEW.at`；安装断言 `provolatile='v'`、`prosecdef=false`、`SET search_path`，`pg_get_functiondef` 源码断言钉在**同一 IF 的可执行式** `NEW.at >= v_wall - interval '60 seconds' AND NEW.at <= v_txn`（两变量入口各赋值一次；**禁止只匹配注释或未使用标识符——死赋值同样绿**；恰 60s 只做源码断言——INSERT 表达式里的 clock 恒早于触发器内的 clock，黑盒对拍必然抖动）。替代（须裁）：禁一切 raw INSERT、material 事件只经唯一 writer。gate：`test_material_backfill_rejected` **七臂（余量化，各自独立事务，全部夹具先过 stage 17 守卫、唯一变量 `at`）**：①route `at = transaction_timestamp() - interval '30 hours'` → 精确拒零行；②route `at = clock_timestamp() + interval '60 seconds'` → 拒；③**`SET ROLE v13_route` 的新事务（r31）、省略 `at`（默认 now()=txn，事务龄远小于 60s）→ 落行且 `at` 等于 `transaction_timestamp()`**（route 放行臂的黑盒钉——超户执行则触发器对 route 一律拒绝也全绿）；④route `at = clock_timestamp() - interval '90 seconds'` → 拒；⑤**(txn, clock] 缝臂**：route BEGIN（**先 `SET LOCAL statement_timeout=0`**，r31）→ `pg_sleep(5)` → INSERT `at = transaction_timestamp() + interval '1 second'` → 精确 `v13: material time` 零行（r30，grok[29-1]：`<= v_txn` 上界的黑盒钉——否则只测 `<= clock` 也能全绿）；⑥超户 30h 行 → 插入成功且 at 原样（测试通道）；⑦长事务：route BEGIN（`SET LOCAL statement_timeout=0`）→ `pg_sleep(61)` → INSERT `at=transaction_timestamp()` → 拒。**其余直插夹具（滑出/slot 下界/future-at）走超户通道且必须「INSERT 成功、行仍在」之后才断言资格**（route 被 RAISE 时「不计入」真空为真）。**

### 4.4 Gate（`test_quota_window.py`）

- `test_seed_shape`：活动 `quota_window` 四键与松值；`capabilities.required` 为 JSON 空数组；`should_run` 活动数组末尾两门为 block，且前四门与 stage 26 种子相同。
- `test_eligible_zero_receipts`：新会话、松种子，布尔真。
- `test_allowed_zero`：SAVEPOINT 内翻 `quota_window` 到 `allowed=0`，布尔假；events 数不变。ROLLBACK 后恢复真。
- `test_count_uses_events_at`（r22 滑出夹具重写，codex[21-03]——旧夹具自相矛盾：窗内两条仍在，加窗外一条不会「恢复」）：主断言用**独立会话**——直插一条合法 `turn/material_spent`（`at = transaction_timestamp() - interval '30 hours'`，payload/source 过守卫），**但 seq 必须经测试专用的原子分配步骤取得（同事务推进 `sessions.next_seq`、复制 `turn_no`、取旧值为 seq、填合法 payload_hash），禁止留下未被分配器承认的 seq（r23，codex[22-3]——否则下一次 append 撞 PK）**；不要 UPDATE `at`；`window_hours=48, allowed=1` → 假；**同一事务原子翻 `window_hours=24`** → 真（同一历史收据滑出窗口、未被修改）。另保留：两条窗内收据 + `allowed=2` → 假（计次钉）。
- `test_slot_spacing`（r26 加下界命中臂）：`slot_minutes=60`、已有一条刚写入的收据、`allowed` 很大：假；`slot_minutes=0` 对照真；**收据 `at` 恰 = v_now - 60min（下界命中）→ 假（闭区间钉）**。
- `test_material_backfill_rejected`：见 §4.3 **七臂**（r31 全列）——①route `at = transaction_timestamp() - 30h` 拒；②route `at = clock_timestamp() + 60s` 拒；③**`SET ROLE v13_route` 的新事务、省略 `at`** → 落行且 `at = transaction_timestamp()`（放行臂必须 route 身份——超户绕触发器仍成功，假绿复现）；④route `at = clock_timestamp() - 90s` 拒；⑤route（`SET LOCAL statement_timeout=0`）`pg_sleep(5)` 后 `at = transaction_timestamp() + 1s` → 精确 `v13: material time`；⑥超户 30h 行仍在且 `at` 不改写；⑦route（同超时设置）`pg_sleep(61)` 后 `at = transaction_timestamp()` 拒；附源码断言同一 IF 可执行式 `NEW.at >= v_wall - interval '60 seconds' AND NEW.at <= v_txn`。
- `test_slot_longer_than_window_rejected`：`slot_minutes` 大于 `window_hours*60` → `v13: quota policy`，无新事件。
- `test_json_one_point_zero`：`window_hours` 用 JSON `1.0` → 政策错误（`v13_json_int_ok` 拒绝非整数文本）。
- `test_other_session_not_counted`：会话 B 的收据不改变会话 A 的布尔。
- `test_no_tree_rollup`：父会话 0 条、子会话很多条，父仍按松种子为真。
- `test_missing_policy`：把活动行翻成 inactive 且不点亮新行（SAVEPOINT）：`v13: quota policy`。禁止 DELETE（冻结触发器）。
- `test_capabilities_policy_shape`（r19 四类负例）：多余键 / `schema_version=2` / `required` 为字符串或对象 / 元素非字符串 → 各一条 `v13: capabilities policy` 零写。
- `test_capabilities_empty_required`：零行。
- `test_capabilities_difference`：required 含一个启用中的真实工具名（`session_stats` 或 `spawn_subsession`，以目录为准）加 `no_such_tool`。返回恰 `no_such_tool`。`spawn_subsession` 若 enabled（**观察** spawn 文件末尾 INSERT enabled true），它不在返回集。
- `test_capabilities_duplicate_rejected`：数组两个相同名字 → 政策错误。
- `test_human_reward_does_not_mutate`：required = `["human_reward"]`。返回该名。effects、decisions 行数不变。全库 `pg_proc.prosrc` 本 stage 新函数不含 `human_reward`。种子 value 不含该字符串。
- `test_shadow_falls_through`：duty=0（shadow）+ quota block（`allowed=0` 测试版本）→ 获胜 id `quota_window`（shadow 为真时继续评估后继 block 的钉）。
- `test_quota_blocks_route_enqueue`：无 tool/call、无 harness 前驱、decide=none（本应走 `v13_route` 入队的夹具）、`allowed=0`：advance `'waiting'`、零新 effect、无新 `turn/route`（**覆盖 prework `RETURN NULL` 路径——r34 单一 gate 在 v_dec 分支前拦截，RETURN NULL 不可达**）。
- `test_quota_blocks_repair_replan_enqueue`（r33/r34 落位）：`v_reason=repair_cap` 与 `replan_cap` 各一条夹具 + `allowed=0` → advance `'waiting'`、零新 effect、无 `triage/hold`（第三出口钉）。
- `test_unknown_session`：两函数都是 `v13: unknown session %`。
- `test_quota_blocks_prework_enqueue`：这是 §3.4 留下的行为证明。duty=1，无 tool/call，无 harness，override 或 decide 路径在 `allowed` 很大时会入队。同一夹具 `allowed=0`：返回 `'waiting'`；effect 数不变；无新 `turn/route`；无 `triage/hold`（duty 不是 0）。ROLLBACK 后再 advance，effect 数增加。`SET ROLE v13_route`。
- `test_quota_does_not_block_finish`：finish 前驱 + `allowed=0` 仍 `'terminal'` / completed。
- `test_quota_sees_receipt_same_advance`：若能构造「本 advance 前半写了 material、后半才入队」且 allowed 等于写后的条数：后半不入队。做不到稳定夹具则 README 记「现查不缓存」只由源码断言支撑：advance 源码仍是每次调用 `v13_should_run`，gate 源码现场调用 `v13_quota_eligible`，没有局部 boolean 穿过 material 写入。
- `test_order_data_not_body`：配额与能力同时失败（`allowed=0` 且 required 含不存在的名字）。默认序获胜 id `quota_window`。对调两门的 should_run 版本后获胜 id `capabilities`。`v13_should_run_gate` 的 oid 不变。
- `test_index`：按裁决断言 `pg_get_indexdef('ix_events_material_spent_at')` 含 `turn/material_spent` 与 `session_id` 与 `at`，且是非唯一。文件与 prosrc 不含 `quota/spent`、`quota/voided`。
- `test_future_at_not_counted`（r4；r24 同分配纪律）：直插一条守卫形状合法、`at = now() + interval '1 hour'` 的 `turn/material_spent`，**seq 经与滑出夹具同一套测试专用原子分配步骤取得（推进 next_seq、复制 turn_no、合法 payload_hash），或整段包 SAVEPOINT 回滚并断言 next_seq 恢复**：不计入资格、不占间隔；下界与上界同钉。
- `test_acl`：route 可执行；worker、PUBLIC、recall、resolve、spawn_owner 不可。一条 `SET ROLE v13_route` 调用 `v13_quota_eligible` 成功。
- 源码：两函数 STABLE、INVOKER、search_path 固定；无 INSERT/UPDATE/DELETE；SQL 文件无 VIEW/TABLE/LISTEN。
- 回归 1→27。

### 4.5 收尾

加载序追加 27。矩阵行：窗内计次、allowed=0、间隔、不跨会话、能力差、human_reward 不改已判行、finish 仍结算、索引、松种子说明。台账主题 PC-3 = 松种子不是产品额度；PC-4 = 计次不沿树。README 写清 `slot_minutes` 是间隔不是分桶，以及 `quota_remaining` 不是本函数。提交方向：`v13: recompute quota window and missing capabilities`。

### 4.6 错误与边界

缺政策、坏整数、slot 长于窗口：`v13: quota policy` 或 `v13: capabilities policy`，advance 整笔回滚。收据 0 条且 allowed>0 且 slot=0：真。工具表为空且 required 非空：全部缺失，should-run 假，不 RAISE（减数源在，只是空集）。工具表结构缺失：安装期停工，不是运行期把减数当成空。

## 5. Stage 28 `v13/attention/`

### 5.1 前置

1. R13 对 L5 / L21 的采纳项已写入本文件 revision。
2. `v_goal_tree(uuid)` 仍是 7 列 STABLE。`v13_should_run_gate(uuid)` 存在。
3. 不换体 should-run，不读 goal 事件。

### 5.2 SQL 序（`v13/attention/v13_attention.sql`，单事务）

1. DO：三对象名（`v13_spawn_budget_snapshot`、`v13_attention`、`v13_scheduler_hint`）不存在；`v_goal_tree` 的 `pg_get_function_result` 仍含 `is_terminal`。失败 `v13: attention baseline`。
2. `CREATE FUNCTION v13_spawn_budget_snapshot(p_sid uuid, p_requested int, p_root uuid DEFAULT NULL)` STABLE（r10 签名定稿：预算判定唯一逻辑体；stage 28 先建供 hint 两参调用（尾参默认），stage 29 wrapper 三参调用；GRANT/REVOKE 与 to_regprocedure 身份统一为 `(uuid, integer, uuid)`）。
3. `CREATE FUNCTION v13_attention(p_root uuid, p_max_rows int DEFAULT 512)`，§1.7 列与 ORDER BY；实现限定（r14）：**先物化 `v_goal_tree` 结果并计数——超限或非法值即 RAISE（不得零行返回）——再逐行 gate**（不用单条普通 SELECT 实现）。禁止写 events。每次对树上会话调用 `public.v13_should_run_gate`。
4. `CREATE FUNCTION v13_scheduler_hint(uuid)`，§1.7 的 stage 28 分支（**第一条可执行语句 = 会话存在性检查**，§1.7 r14；已含分支 1.5 未消费 cancel；无 lifecycle；分支 3.5 调 snapshot）。
5. 对**三个函数** `REVOKE EXECUTE FROM PUBLIC` + `GRANT EXECUTE TO v13_route`（r8：snapshot 不授则 `SET ROLE v13_route` 调 hint 在嵌套调用 42501；留 PUBLIC 则 worker 可直调假绿）。
6. 无索引、无策略行、无 cron、无 COMMENT。

数据库名 `agent_v13_attention`。

### 5.3 状态流

纯读。树上 N 个会话 = N 次 gate 调用，无缓存表。并发新事件要下一次调用才进入 STABLE 快照。hint 与 attention 不互相调用（避免把秩当成调度）。`duty_cycle=0` 且**无未消费 cancel** 时 hint 为 `wait`（r11：有未消费 cancel 且无 claimed/unknown 时分支 1.5 优先返回 `run_now`，例外见 §1.7），即使 gate 因 shadow 返回 NULL。

### 5.4 Gate（`test_attention.py`）

- `test_unknown_root`：`v13: unknown session`（树函数的文案；活体无百分号插值（`:479`），测试用 `LIKE 'v13: unknown session%'`，不要发明第三句）。
- `test_attention_limit`（r13；r18 补 1024）：512 行成功返回（`v13_spawn_owner` 直插子会话造大树）；513 行 → `v13: attention limit`；`p_max_rows` NULL / 0 / 负数 / **> 1024** → 同文案（fail-closed；上限是调用方预算非全局资源保护——README 同文）；超限零 gate 调用只做源码顺序断言（计数在 gate 之前，r14）。
- `test_hint_unknown_precedes_bad_policy`（r15）：SAVEPOINT 内激活畸形 triage 策略后对未知 uuid 调 hint → 仍精确 `v13: unknown session %`（不得先报 `v13: triage policy`）、零写。
- `test_single_root`：一行，`attention_rank=1`，`depth=0`，列与 `sessions` 及 `v_goal_tree` 一致，`blocked_by` NULL，`should_run` 真。
- `test_rank_human_before_runnable`：根 ready；直接子有 ready human。子的 rank 小于根（更靠前），子 `blocked_by=human_pending`。终态孙（若造得出 completed 子）的 rank 大于一切非终态。同层用 `session_id` 升序，断言稳定。
- `test_rank_not_stored`：`information_schema.columns` 无 `attention_rank`。两次调用 events 数相同，返回行字节级相同（json 聚合比较即可）。
- `test_hint_matrix`：
  - 新 ready 会话、duty=1、无 effect：`run_now`。
  - 同一会话 duty=0（**夹具无未消费 cancel**，r11）：`wait`，且不写 `triage/hold`（hint 不是 advance）；另有 duty=0 + 未消费 cancel + 无 claimed/unknown → `run_now`（分支 1.5 例外的钉）。
  - ready human：`wait`。
  - `allowed=0`：`wait`。
  - **在途 + 坏后继策略（r24）：有 ready effect 且 triage 策略畸形 → 仍 `wait`（不得先抛 `v13: triage policy`——IF/ELSIF 顺序的钉）。**
  - 非根会话超 cap（只读快照）→ `wait`；预算恢复后同会话 → `run_now`（分支 3.5 的钉；**超 cap 夹具必须带未认领 tool/call**——无 tool/call 的满树会话按分支 4 仍 `run_now`，加一条对照钉合取条件）。
  - hint 错误文案（r6 分期）：stage 28 只钉字面量 `v13: spawn_budget policy` / `v13: unknown session %` / `v13: spawn root cycle`（与活体 `v13_spawn_subsession` 同文案——此时 `v13_spawn_batch_allowed` 尚不存在）；fanout/depth/cap 三组各一条超限 → 均 `wait`。stage 29 再加参数化等价测试：同会话同策略同 requested 下，hint 与 `v13_spawn_batch_allowed` 的错误类别/文案与允许判断逐项一致。
  - closeout 到 completed 之后：`dont_notify`。
  - 词不在三元闭集之外。无 `run_now` 以外的同义词。
- `test_hint_not_ack`：调用两次，`next_seq` 不变，无 `scheduler_ack`，无新 events。
- `test_hint_then_advance_rechecks`：hint 返回 `run_now` 之后，在**同一测试事务外**先提交一个 `allowed=0` 的翻版，再 advance：零新 effect。证明 hint 不是入队许可。若测试框架难以跨事务，用两个连接：A 读到 `run_now`，B 翻策略并 COMMIT，A 再 advance 必须看到假。A 的第一次 hint 与 advance 不要包在会挡住 B 的长事务里。
- `test_no_cron_job`：`cron.job` 不存在则跳过查询；存在则断言本库 `cron.job` 行数在调用 hint 前后不变（本 stage 不插 job）。
- `test_source`：两函数 prosrc 无 `goal/stopped`、`pg_sleep`、`LISTEN`、`INSERT`、`UPDATE`、`cron.schedule`。`provolatile='s'`。SQL 文件无 `CREATE EXTENSION`、无 VIEW。
- `test_acl_route`：`SET ROLE v13_route` 成功调用 hint 与 attention；worker 与 PUBLIC 为 42501；**snapshot 三断言（r8）：route 可执行、worker/PUBLIC/recall/resolve/spawn_owner 不可、`provolatile='s'`**。
- `test_attention_large_tree_cost`（r28 夹具形状钉）：1 个 root + ≥500 个 `completed` **直接子**（depth=1、总行数 ≤512，避免深度链在 64 层 `goal tree depth` 误判）——`v13_attention(root)` 成功返回且行数 ≥500 **之后**才记录耗时（不断言阈值）；`goal tree depth` / `attention limit` 异常不算通过。README 写明「返回行数预算不保树遍历成本，传 1 仍扫全树」。
- 回归 1→28。

### 5.5 收尾

加载序 28。矩阵：秩的 human 优先与终态沉底、hint 四分支、双调用零事件、hint 之后翻策略 advance 仍受门约束、无 cron 行。台账 PC-5 = hint 不是 ack、本 stage 不注册 cron；PC-6 = 秩是注意力不是调度。README 写 driver 合同（`run_now` 才 advance，advance 内再判）、两格生产绑定、§1.7 边界声明（`p_max_rows` = **返回行数预算**，不保 `v_goal_tree` 遍历成本，传 1 仍扫全树——不得称资源上限/契约）。提交方向：`v13: add attention rank and scheduler hint`。

## 6. Stage 29 `v13/govern/`

### 6.1 前置

1. D15-A、D15-B、L29、L27 已采纳。
2. RED：§1.5 的 cap RAISE 在 stage 28 库复现并写进 README。
3. §2 证伪 7、8、11、12、14、**§2 第 15 项安装义务（守卫已在 stage 26 装好且生效——r17 称谓）**。
4. `handoff_policy` 活动行存在；extract 源码含政策读取，否则停工（§1.8）。
5. 底稿改为**当时** dump 的 advance、recover_idle、should_run_gate、scheduler_hint，不是 stage 26 计划文本。

### 6.2 SQL 序（`v13/govern/v13_govern.sql`，单事务）

1. DO baseline：无历史 `goal/stopped|resumed`；`v13_state_hash` 排除名单仍只三词（若 R13 采纳 D15-A-alt-exclude-in-state-hash，本步改按该裁决的安装前形态断言）；`v13_control_operator` 存在。失败 `v13: goal baseline`。
2. `CREATE FUNCTION v13_goal_fingerprint(uuid)` STABLE `SET search_path = pg_catalog, public`，体内表/函数 schema-qualified。材料与 `v13_state_hash` 相同，排除名单 = **无条件八词**（r31，§1.3 施工形同文：session 三词 + goal 两词 + control/handoff + wake/satisfied + turn/material_spent），在材料里出现两处（v_max 与 events 聚合）都要扩。未知会话同一文案。（若 R13 采纳换体 state_hash 方案：本步不存在，改为 `CREATE OR REPLACE v13_state_hash` 扩排除名单，两处同扩；但 state_hash **不得**排除 `control/handoff`——那是 fingerprint 独有的排除；且载荷改恰两键并同步 guard/stop/resume 返回值与测试。）
3. `CREATE FUNCTION v13_goal_fold(p_sid uuid) RETURNS TABLE(state text, stop_fp text)` STABLE `SET search_path = pg_catalog, public`——合同 = §1.4「折叠唯一」段首整句（无 lifecycle 行恰返回一行 `RETURN QUERY SELECT 'running'::text, NULL::text; RETURN;`——OUT 参数函数禁带参 RETURN NEXT（r29）、禁零行、state 仅该行 type='goal/stopped' 为 stopped、stop_fp 只取同一次读出的最后一条载荷 fingerprint、禁二遍扫）。未知会话 `RAISE 'v13: unknown session %'`。随后 `CREATE FUNCTION v13_goal_lifecycle(uuid)` STABLE，体只能 `SELECT state FROM v13_goal_fold(p_sid)`（薄包装）。
4. `CREATE FUNCTION v13_goal_event_guard()` INVOKER `SET search_path = pg_catalog, public`，§1.4 检查序（r41：⓪ operator → ① 行锁 → ②–⑥；⓪ = `v13_control_operator()` 假则 `v13: session not found` 零写，不读会话）。
5. `CREATE TRIGGER` BEFORE INSERT WHEN type 属于这两词。不修改已有触发器。
6. `CREATE INDEX ix_events_goal_lifecycle`（若 D15-B 采纳「不建索引」，本步删除且测试反断言）。
7. `CREATE FUNCTION v13_goal_stop` 与 `v13_goal_resume`。锁序（r30 三口同序，§1.4/§6.3 同文）：授权预检 → `FOR UPDATE` → **operator 复验** → `SELECT state, stop_fp FROM public.v13_goal_fold(p_sid)` → 终态 → `v13: goal lifecycle` → 在途任一 → `v13: goal busy`（stop 与 resume 都适用，子题⑤）→ fingerprint（stopped 验 current=payload；resumed 验三等，§1.4 r26 先转移后指纹）→ `public.v13_append_event(..., NULL source)`。无 EXCEPTION。
8. 翻 `should_run` 版本，末尾追加 `goal_stopped` block。
9. `CREATE OR REPLACE v13_should_run_gate`：差集只增加该 id，条件 = **先判 `sessions.status NOT IN ('completed','failed','cancelled')`，再调** `public.v13_goal_lifecycle(p_sid)='stopped'`（终态行不扫停/复事件，§1.2 终态优先）。禁止在 gate 函数里再写 `ORDER BY seq` 扫事件。
10. `CREATE OR REPLACE v13_recover_idle()`：底稿 dump。差集只在现有 `v13_triage_hold_blocks_recover` 判断旁增加 `v13_goal_lifecycle(v_sid)='stopped'` 则 `CONTINUE`。两支判断都保留，不合成一个布尔。duty 函数不改。
11. `CREATE OR REPLACE v13_scheduler_hint(uuid)`：在分支 1.5（未消费 cancel，stage 28 已含）之后、分支 3 之前插入 stopped → `dont_notify`（若 R13 采纳 L21-alt-stopped-wait 则按裁定）。组合优先级摘要（与 §1.7 同文）= 终态 > 未消费 cancel（无 claimed/unknown → `run_now`；有 → `wait`；ready 不算）> stopped > 分支 3（在途 / pending_human / `duty_cycle=0` / should_run 假）> 预算退避 > `run_now`。
12. `DROP FUNCTION v13_attention(uuid, integer)` 然后 `CREATE FUNCTION v13_attention(p_root uuid, p_max_rows int DEFAULT 512)`（r14/r19：**必须带 DEFAULT 512**；条件表逐字 = `p_max_rows` NULL、`< 1`、**`> 1024`**、或行数超上限 → RAISE `v13: attention limit` 且不调 gate）：先物化 `v_goal_tree` 结果并计数，再加 `lifecycle text` 列。秩的 CASE 保留 §1.7。同一事务 GRANT。`test_govern.py` 对重建后函数重测（r20 形状：单行树上 `v13_attention(root, 1025)` 直接 `v13: attention limit`——不得用插 1025 行的方式（那会先撞 513 上限，漏写 `>1024` 检测不出）；另测默认单参可解析、512 行成功、513 行 RAISE。
13. `CREATE FUNCTION v13_spawn_batch_allowed(uuid, int)` **VOLATILE SECURITY DEFINER `SET search_path = pg_catalog, public, pg_temp`，`ALTER OWNER TO v13_spawn_owner`（r39）**：**严格遵循 §1.5 函数卡的唯一全链，本处不重述。**同事务授权（r16 五句模型）：`GRANT EXECUTE ON v13_spawn_batch_allowed(uuid, int) TO v13_route`；`GRANT EXECUTE ON v13_spawn_budget_snapshot(uuid, integer, uuid) TO v13_spawn_owner`（route 侧授权已在 stage 28 完成）。
14. `CREATE OR REPLACE v13_advance`：底稿为当日 dump（已含 stage 26 读点、status 更新块与审计豁免预检）。差集：P-spawn 判断改顺序 IF/ELSIF（先 `public.v13_should_run` 后 `public.v13_spawn_batch_allowed(p_sid, jsonb_array_length(v_calls))`），任一假 → **逐字继承 §1.1 P-spawn 的 status 更新块**（`UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid AND status IN ('ready','waiting')`）+ `RETURN 'waiting'`（不写 spawn_fanout、不插空 params、不进 harness 段）。**不得删 `v13_policy_share()` 调用与审计豁免预检（`test_govern` 断言前者在 `IF jsonb_array_length` 之外、任一 `v13_should_run` 之前；后者在 prework 调用之前）**。「结算先行」变体已否决（分歧 7）。不改 spawn 函数。不写空 route。
15. REVOKE PUBLIC + GRANT：fingerprint、fold、lifecycle、stop、resume、attention、hint 给 `v13_route`（**fold 必授——stop/resume/guard 是 INVOKER，route 身份下无 EXECUTE 则真实调用 42501，超户测试假绿，r25**）；wrapper 与 snapshot 按 §1.5 r16 五句模型（route：wrapper+snapshot；spawn_owner：snapshot；其余假；route 对 advisory_class 假）；**`v13_goal_event_guard` `REVOKE EXECUTE FROM PUBLIC`、不另授运行角色（parent 守卫已在 stage 26 同句收口；点火无需 EXECUTE，保留默认 PUBLIC 与红线冲突）**。安装后 DO 断言（r38 全集）：wrapper `prosecdef=true`、owner=v13_spawn_owner、五句 ACL、**proconfig 精确含 `search_path=pg_catalog, public, pg_temp` 且 pg_temp 末位、prosrc 无未限定业务名（能区分 `pg_catalog.hashtext(` 与裸 `hashtext(` 的表达式查 sessions/v13_policies/hashtext/v13_advisory_class/v13_spawn_budget_snapshot/pg_advisory_xact_lock）、恰一处 `v13_policy_share(` 且可执行文本零 `FOR SHARE`（test_govern.py 同断言，r38）**。
16. 安装后 DO：活动 should_run 含 `goal_stopped`；索引定义匹配；advance 源码含 `v13_spawn_batch_allowed`；`v13_spawn_subsession` 源码仍含 `v13: spawn budget cap`（确认没换体）。
17. 无 COMMENT。无新角色。无 `v13_latest_handoff`。无 VIEW。

数据库名 `agent_v13_govern`。

### 6.3 状态流

- stop（r31 与 §1.4/§6.2 步 7 逐字同文）：授权预检 → `FOR UPDATE` → operator 复验 → `v13_goal_fold` → 终态（`v13: goal lifecycle`）→ busy（`v13: goal busy`）→ 生命周期转移（重复 stop 同 lifecycle 拒）→ fingerprint（stopped 验 current=payload）→ 一条事件 → 折叠变 `stopped` → 此后 should-run 假 → advance 在读点 `'waiting'` 且零新 effect → recover 跳过 nudge。status 保持原值。**门前结算不受 stop 约束**：finish/reject closeout、cancel closeout、material、wake 照常——前提是本轮无未认领 tool/call（有则 P-spawn 提前返回，见 `test_defer_with_pending_calls_and_finish`）。
- resume（与 stop **完全同链**，r32 补终态——否则 stop→cancel→closeout 的未排除事件漂移会让 resume 先报 fingerprint 而非 lifecycle）：授权预检 → `FOR UPDATE` → operator 复验 → `v13_goal_fold` → **终态（`v13: goal lifecycle`）** → busy（`v13: goal busy`）→ 转移（重复 stop、以及 state 非 stopped 的 resume 含零事件 → `v13: goal lifecycle`）→ fingerprint（stopped 行验 current=payload；resumed 行三等 current=payload=stop_fp，不符 `v13: goal fingerprint`）→ append。
- resume：仅当折叠为 stopped 且指纹未漂移。成功后折叠 `running`，hint 可以回到 `run_now`，advance 恢复入队。
- 并发：两连接同时 stop，会话锁串行；第二连接 `v13: goal lifecycle`，事件恰一条。stop 与 advance：谁先拿到会话锁谁先走完；**两跳收敛**：stop 推进 `next_seq` 后，持旧快照的 advance 先在 probe 处拿 `'stale'`，**重取快照重试后**才在读点看见 stopped → `'waiting'`。gate 断言按两跳写，不写「后到的 advance 直接看见停事件」。
- recover 与 stop：SKIP LOCKED 下，recover 没锁到的行不计；锁到之后读折叠。允许「nudge 已提交、随后 stop」的历史 nudge 留在日志里。stop 之后的新 recover 对该会话 `v13_insert_nudge` 的返回和为 0。
- 客户端 cancel：用测试专用、仅 `WHEN type IN ('goal/stopped','goal/resumed')` 的阻塞 BEFORE INSERT 触发器，在 append 已更新 `next_seq` 分配之前或之后卡住（实现时阻塞点放在守卫之后难控制——放在测试触发器里 `pg_sleep` 只存在于测试安装的函数，测完 DROP）。断言整笔回滚：事件数与 `next_seq` 回到调用前。测完必须 DROP 该触发器，即使断言失败也用 `finally` 路径 DROP。该 `pg_sleep` 不得出现在 `v13/govern/*.sql`。
- L29：到顶 → 不调用 spawn → 先 status 更新块（同 §1.1）再 `'waiting'`（不进 harness 段）；tool/call 留置；harness 结算/入队留给无未认领 tool/call 的轮次。直调 `v13_spawn_subsession` 仍 RAISE。**门前结算名单不含 budget_exhausted closeout**（它是新决策不是结算，门假时随臂跳过，§1.1 r3）；finish/reject/cancel 前缀与 material/wake 照常。
- L27：无新状态。回归只读 Phase B 行为。

### 6.4 Gate（`test_govern.py`）

**指纹**

- `test_goal_fold_empty_row`（r29）：空会话 `v13_goal_fold` 恰一行 `('running', NULL)`、`v13_goal_lifecycle` 得 `running` 非 NULL。
- `test_fingerprint_equals_state_hash_without_goal_events`（r31 三断言；r32 五类口径）：①排除名单内任一 type 都不存在的会话（可含 `goal/override`）上两函数逐字相等；②仅有 `session/completed` 的会话上仍相等（session/* 两边都排除）；③五类独有排除各插一条（goal 两词/control/handoff/wake/material）→ 必不等；仅 `session/completed` 时仍相等（r32 口径）。
- `test_stop_changes_state_hash_not_fingerprint`：stop 前记 `h0=v13_state_hash`、`f0=fingerprint`。stop 后 `v13_state_hash <> h0`，fingerprint = f0，且 fingerprint <> 新的 state_hash。
- `test_stop_payload`：返回 jsonb 与事件 payload 相等；键恰三；`source_effect_id` NULL；`schema_version` 为 JSON 数字 1；reason 与参数相同；父/子会话数不变；effects 数不变；status 不变；无 `cancel/requested`；无 `control/handoff`；**成功路径分配断言（r22）：`sessions.next_seq` 恰增 1、事件 `seq` = 调用前的 `next_seq`（小题⑩不变量的正例钉）。**

**转移与授权 `test_lifecycle_transitions`**

- 首次 stop 后 `v13_goal_lifecycle='stopped'`。
- 再次 stop：`v13: goal lifecycle`，事件数不变。
- 无 stop 时 resume：同一文案，零写。
- 终态（closeout 后）stop / resume：`v13: goal lifecycle`，零写（§1.4 转移表终态行）。
- 漂移：stop 之后再 `v13_append_event` 一条普通事件（用 route 能写的既有 type，例如不破坏守卫的类型；若所有既有 type 都有守卫，就改为追加 `user/message`）。resume → `v13: goal fingerprint`，无 resumed 行，折叠仍 `stopped`。
- 无漂移 resume：折叠 `running`，事件两条，两枚 fingerprint 相同。
- 非 operator（函数路径）：`v13: session not found`，不含 uuid，零写。operator 未知 uuid：`v13: unknown session %`。**守卫路径同验（R13b）：`SET ROLE v13_spawn_owner`（带外、有 events INSERT 面）直插①–⑥全合法的信封 → 同样 `v13: session not found` 零写（⓪ 的钉）；`SET ROLE v13_route`（带内）经函数 stop 的成功路径不变。**
- `SET ROLE v13_worker`：对 stop 无 EXECUTE（42501）。`SET ROLE v13_route`（route 在 operator 带内，**观察** Phase B D7/R8：operator 带 = rolsuper ∨ 对 `v13_route` USAGE；route 自身满足）stop 成功并 COMMIT。这是 F19 式的真提交，不是只在超户下成功。
- 伪造负例通路（r22，codex[21-02]）：**除专门的 `v13: goal seq` 负例（裸 INSERT seq=当前 next_seq）外，形状/source/终态/指纹负例统一经 `v13_append_event` 触发守卫**（裸 INSERT 在已有事件的会话上无法同时过 ② 与 PK——seq=next_seq 撞 ②、seq=next_seq-1 撞 PK）。文案归组（r23 拆开，逐字断言）：`source_effect_id` 非空 → `v13: goal source`；reason 空串/多一键/`schema_version` 非 JSON 整数 1/`jsonb_typeof` 非 string/payload 非对象（数组/字符串/null）/fingerprint 非 `^[0-9a-f]{64}$` → 各一条 `v13: goal payload`；**fingerprint 负例用合法 64 位小写 hex 且与 `v13_goal_fingerprint` 重算不等** → `v13: goal fingerprint`（到⑥）。以上均经 append 触发。**原始 INSERT 旁路验证（r25 前置钉死——唯一失败点必须是⑥的指纹重算）**：SAVEPOINT 内复制分配器（`next_seq`+1、取旧值作 seq、复制 turn_no）后 INSERT 一条 `type='goal/stopped'`、①–⑤全满足、fingerprint 合法 64hex 且与重算不等的行（会话 running、无在途）——期望精确 `v13: goal fingerprint`；`ROLLBACK TO SAVEPOINT` 后断言 `next_seq` 与事件行数恢复入口值、零残留。**resumed 绕过负例（r25 新增，codex[23-1] 的正钉）**：stop 后追加一条普通事件（改 fingerprint）→ SAVEPOINT 内按分配器直插 `goal/resumed`，fingerprint = **新的** `v13_goal_fingerprint`（①–⑤全过、与 payload 相等）但 ≠ fold.stop_fp → 精确 `v13: goal fingerprint`，回滚后复原。负例四条见 §1.4②（三条 seq-only 裸 INSERT + 一条 turn_no 单错位 SAVEPOINT 用例）；**`seq = next_seq - 1` 且 turn_no 对齐的直插会过②进入③–⑥（BEFORE 行触发器先于 PK）——该正向通路只由旁路验证与 resumed 绕过负例覆盖，不是 seq 负例**。不要只断言「有异常」。

**advance / recover `test_stop_blocks_enqueue_not_cancel`**

- stopped、duty=1、原本会入队的夹具：advance `'waiting'`，effect 数不变，status **仍不是** cancelled/completed。
- 在途 claimed human（r3 改主路径）：**有在途（ready/claimed/unknown）→ stop 先 `v13: goal busy` 拒；结算完成（无在途）后再 stop 才成功**。stop 成功后的新在途**在 advance 生产路径上**不可达（门挡新入队、claim 只消费已有 ready）；route 直调 enqueue/直接 INSERT 仍可造成在途，其后 resume 依漂移与否得 `v13: goal busy`（在途仍在）或 `v13: goal fingerprint`（在途已结算且事件入材料）——该路径不断言单一文案（README 与 §1.4 同句，r6）。
- `test_stop_max_cycles_not_failed`：stopped + continuation 前驱 + `cycle_no` 已达 `max_cycles` + **无未终态子会话且无未认领 tool/call**（否则 `v13_park_open_children` 或 P-spawn 先返回，坏锚也绿）→ advance `'waiting'`、不 closeout failed（budget_exhausted 随臂跳过的钉，§1.1 r4）。
- `test_explore_raise_survives_gate`（stage 26 与 stage 29 各一条，r9 落位）：存在未认领 explore 路由 tool/call 时，即使 `v13_should_run` 为假（stage 26）或预算到顶（stage 29），advance 仍先 RAISE `v13: explore spawn`、零 effect 零 route（防换体把误用 RAISE 静默改成 waiting；r31 条件反转分支已删）。
- `test_stop_busy_matrix`（r4）：ready-only、claimed-only、unknown-only 三夹具各自 stop → `v13: goal busy` 零写；blocked_unknown 会话 stop → 同样 busy（不是墙文案）。
- 终态负例（r23 改经 append 触发）：closeout 终态的会话上经 `v13_append_event` 写 `goal/stopped` → `v13: goal lifecycle`（③在④前）；**终态 + unknown 残留 effect 的同路径 → 同文案**（终态先于 busy）。
- `test_child_done_while_parent_stopped`（夹具无未认领 tool/call，r7）：父停期间子会话终态（或父有 progress 前驱）→ 下一次 advance 写下 `wake/satisfied`（或 `turn/material_spent`）→ **固定断言（r31）：fingerprint 不变、resume 成功**（八词排除集唯一形）。
- `test_hint_matches_batch_allowed`（r7，stage 29 参数化等价）：同会话同策略同 requested 下，坏政策/未知会话/环的 SQLERRM 一致；超 fanout、depth、cap 时 `snapshot` 假且 hint=`wait`；预算足、should_run 真、无未认领 tool/call 时 hint=`run_now`。
- `test_stopped_hint_dont_notify`（r7）：非终态 stopped → hint=`dont_notify`（返回值断言，非源码 grep）；resume 且其余条件满足后回 `run_now`。**r16 补一条：`SET ROLE v13_route` 调 hint 成功（route 需 snapshot 直调权的生产钉）；r17 再补：夹具非终态、未停、带未认领 tool/call（必须进入分支 3.5 才真正调 snapshot）；安装后 DO 用 `aclexplode` 断言 route 对 `v13_spawn_budget_snapshot(uuid,integer,uuid)` 有 EXECUTE 且 PUBLIC 没有。**
- `test_revive_race_backstop`（r19 定稿，advisory 屏障——行更新握手在 MVCC 下会死锁，两车道同判）：夹具子会话 `completed`/`failed`，复活前 `occupancy + requested <= max_nonterminal`（如 `max = occupancy_before + requested`），复活后 `>`。协调连接用**会话级** `pg_advisory_lock`/`pg_advisory_unlock` 预持 release key（r20：signal 与 release 用两个**新** key，均不得等于 `(13001, hashtext(v_root::text))`——复用会与 A 已持的事务咨询锁死锁或重入不阻塞）；A 连接 `SET ROLE v13_route` 调 advance——测试先 COMMIT 一个仅测试库使用的 **VOLATILE** `v13_spawn_occupancy` 包装（首次调用按真实 SQL 计数后**只调 `pg_advisory_xact_lock`** 取 signal key 并阻塞在 release key 上；测试经 `pg_locks` 确认 A 已到点，让 B 复活子会话并 COMMIT，再释放 A；包装随后返回计数前旧值；第二次起真实计数）。断言：**测试捕获 SQLERRM 精确等于 `v13: spawn budget cap`（预期路径，非 gate 失败）**、父事务回滚后子会话数与 tool/call 行数不变、进程退出码 0、该 RAISE 不被 advance 吞成 `'waiting'`。`finally` 在未中止的连接恢复原函数体并断言 `provolatile='s'`、恢复测试对象后 COMMIT；不在 FOR SHARE 上 pg_sleep。
- `test_stopped_cancel_liveness`（r10，端到端；r11 夹具细化）：夹具固定无 claimed/unknown、无未终态子会话；stop → `v13_cancel` → **重取 snap** 再 advance（停/取消各推一次 next_seq，旧 snap 只会先 stale）→ `'terminal'`/cancelled（前缀结算优先于停门）；closeout 之后下一跳 hint=`dont_notify`；stop→cancel 后、advance 前 hint=`run_now`（分支 1.5）。
- `test_handoff_after_stop_resume_succeeds`（r5，端到端）：stop → extract handoff（`transcript_hash`/`delivery_id` 变、`v13_goal_fingerprint` 不变）→ resume 成功。
- `test_stop_then_finish_settles`：stopped + finish 前驱（无未认领 tool/call）→ advance `'terminal'`、completed（门前结算钉）。
- `test_stop_busy_rejected`：存在 claimed 在途 effect 的会话 stop → `v13: goal busy`、零写（R13 子题⑤草案分支）。
- `test_terminal_gate_priority`：stop → cancel → closeout 终态后，`v13_should_run_gate` 不返回 `goal_stopped`（终态优先，§1.2 条件表）；attention 终态行 `blocked_by` NULL。
- stop 正例夹具一律带一条 `user/message`（空会话的 prework reject 沿用既有 `origin_user_seq=-1` RAISE，不当作 waiting 正例）。
- 未消费 cancel + stopped：advance 仍可走到前缀并终态 cancel（前缀在读点之前）。若夹具同时会在前缀 closeout，期望 `'terminal'`。这与「停 ≠ cancel」不冲突：cancel 动词仍在，stop 自己不发 cancel。
- recover：造出会 nudge 的 children_terminal 或 repair 条件，先确认 stop 前 nudged 增加（或幂等键下一次为 0 但至少函数走到 insert 分支——若唯一索引让第二次为 0，用**新的** fingerprint 条件：新子会话状态组合）。stop 之后 `v13_recover_idle` 的 nudged 增量是 0，且无新 `recover/nudge`。
- duty=0 且**未** stop：recover 跳过行为与 stage 26 相同（仍跳过）。duty=0 的 hold 文案不变。停止不是 `duty_cycle=0` 的别名：duty=1 且 stopped 时不写 `triage/hold`。

**折叠唯一 `test_single_fold_body`**

- `v13_goal_lifecycle` 的体 = `SELECT state FROM v13_goal_fold(...)`（薄包装断言，r25）；**唯一性（r26 改正向过滤——合取子串会把正确带排除名单 + ORDER BY seq 的 `v13_goal_fingerprint` 误伤打红）：对 `type IN ('goal/stopped','goal/resumed')` 做**正向过滤**（含 `= ANY`）且配 `ORDER BY seq` 的 prosrc 只有 `v13_goal_fold`；fingerprint 的 NOT IN 排除名单字面量不算自扫**；gate/recover/hint/attention/stop/resume/guard 含 `v13_goal_fold(` 或 `v13_goal_lifecycle(` 调用、无自扫。允许 `goal_stopped` 门 id 字面量在 gate。**空会话钉（r26）：无任何事件的会话 `v13_goal_lifecycle` 返回 `running` 而非 NULL（fold 基数=1 的钉）；未知会话仍 `v13: unknown session %`。**
- attention 列比 stage 28 多 `lifecycle`，且 stopped 行上该列等于 `'stopped'`，`blocked_by='goal_stopped'`（无更早的 block 时），rank 使用该 id 的臂（比 `quota_window` 靠前：造一个 stopped 子与一个 quota 兄弟，**夹具（r6）：`allowed=1`、停子零收据（命中 `goal_stopped`）、quota 兄弟恰一条窗内收据（命中 `quota_window`）、同 depth**，断言停的秩更小）。

**L29 `test_cap_skips_spawn`**

- RED 已记录。GREEN（r13 前提：调用前断言 NOT EXISTS `status IN ('ready','claimed')` 的 effect；unknown 独立断言不落墙）：父会话一条合法未认领 tool/call（夹具 route reason 非 explore），`spawn_budget` 翻到 `max_nonterminal=1` 且已有一个非终态子会话占满，或把 `max_nonterminal` 调到小于 `occupancy+requested`。advance 返回 `'waiting'`，**异常文案不出现**；**父会话 `status='waiting'` 且无 `triage/hold`、无关会话 status 不变（r8）**；子会话数不变；无 `spawn_fanout`；tool/call 仍在；无新 effect。cap 用例以 `SET ROLE v13_route` 实跑（验证 §1.5 执行权修正后的 ACL，含 snapshot 嵌套调用）。
- `test_spawn_budget_flip_blocks`（r13；r14 单序）：连接 A 以 `SET ROLE v13_route` 开事务调 `v13_spawn_batch_allowed` 且不提交；连接 B 以表主/超户 INSERT 收紧后的新版本并双 UPDATE 灭活当前 active 行——阻塞点必须是对该 active 行的 UPDATE（`pg_locks` 验证，FOR SHARE 的钉；B 不得用 route——`v13_policies` 对 route 只授 SELECT，42501 会假红）；A 在未提交事务内调 `v13_spawn_subsession`，结果与旧 value 一致；A COMMIT 后 B 的 UPDATE 才成功。不存在「翻版在预检后提交而 advance 仍见旧值」的分支（已删）。
- 对照：预算充足且 should_run 真：仍 `'progressed'` 且有子会话（证明不是把 spawn 整个拆掉）。
- `test_direct_spawn_still_raises`：同一到顶夹具直接 `v13_spawn_subsession` → `v13: spawn budget cap`。
- `test_fanout_skip`（r13 同前提：调用前无 ready/claimed effect、非 explore tool/call）：`requested` 大于 `max_fanout`（两条 tool/call，政策 `max_fanout=1`）时 advance 不 RAISE `spawn budget fanout`，零子会话、本会话 `status='waiting'`。
- `test_depth_skip`（r10，与 fanout 对称；r11 夹具前置；r12 加同前提）：**非 explore 的未认领 tool/call**、父深度满足 `depth+1 > max_depth`、should_run 真、duty=1、无 claimed、**调用前无 ready/claimed effect**；断言 `SET ROLE v13_route` 的 advance 为 `waiting`、零子会话、无 `spawn_fanout`、本会话 `status='waiting'`；直调 `v13_spawn_subsession` 仍 RAISE `v13: spawn budget depth`。
- `test_bad_policy_still_raises`（r13 同前提）：`spawn_budget` 活动行换成缺键的新版本，advance RAISE `v13: spawn_budget policy`，不是 `'waiting'`。
- 源码：advance 在跳过路径不包含新的 `jsonb_build_object('action','sql','reason','spawn_fanout'` 副本（该对象只留在原成功臂）。`v13_route` 的 oid 与 hash 相对 stage 28 dump 不变（未换体）。
- `test_defer_with_pending_calls_and_finish`（r3，判别夹具；r12 加同前提：调用前无 ready/claimed effect）：cap 或 should_run 假 + 未认领 tool/call + finish 前驱 → advance `'waiting'`、**父会话 `status='waiting'` 且无 `triage/hold`、无关会话不变（r8）**、父会话**非终态**、无 `spawn_fanout`、无任何 closeout、tool/call 仍在（提前返回语义的钉；「结算先行」已否决——分歧 7）。
- `test_stale_then_waiting_after_stop`：stop 后持旧 snap 的 advance → `'stale'`；重取快照重试 → `'waiting'` 零新 effect。
- `test_policy_share_survives_govern`（r36/r39）：①advance 的 prosrc 断言 `v13_policy_share()` 调用仍在 `IF jsonb_array_length` 之外、explore 之后、唯一 P-spawn `v13_should_run` 之前（防换体删除）；②**wrapper 断言（r39，与步 15 DO 同款）**：`v13_spawn_batch_allowed` 可执行文本恰一处 `v13_policy_share(`、零 `FOR SHARE`（注释不算）。
- `test_cap_defer_continuation`（r21；r22 夹具三固定，两车道同判）：**非 explore 的合法未认领 `tool/call`（数量确定触发 `v13_spawn_budget_snapshot=false`）+ `v13_should_run=true` + 会话非 blocked_unknown 且无 ready/claimed/unknown effect**，另有 `v_cont=true` 前驱（`repair/required` 已写）→ 提前返回 `'waiting'`、无 continuation effect、无 `harness_continuation` route、无任何 closeout、无 `spawn_fanout`、本会话 `status='waiting'`（缺任一前置会把前缀早退/P-harness 拦截误读成 cap 分支——该行为来自 §6.2 步 14 P-spawn 的提前 RETURN，不是 P-harness 条件的隐式变化；README 同句）。

**L27 `test_handoff_policy_regression`**

- 复制 stage 25 的最小成功 extract（route COMMIT）在**未停**会话上仍成功。
- SAVEPOINT 内把 `handoff_policy` 翻到 `enabled=false`：新 cutoff 得 `v13: handoff disabled`。零 active 行：`v13: handoff policy`。同身份重放仍返回原 payload（若已有收据）。
- stop 之后、政策仍真：extract 仍成功，且 stop 调用本身没有增加 handoff 行。
- **跨阶段钉（r2）**：stop 之后 NULL cutoff 的 `v13_transcript_hash` 必须变化、新 delivery 的 `delivery_id` 不同——`goal/stopped|resumed` **不进** Phase B 的 transcript 排除名单（B 合同只排除 `control/handoff`，本阶段不改该名单；防止未来有人把 goal/* 塞进排除名单做绿）。
- 这些失败路径 `next_seq` 的增量只来自成功的 stop/extract，失败调用本身为零增量。

**索引与权限**

- `test_index_def` 匹配谓词与 `seq DESC`。
- lifecycle / fingerprint 对 route 可执行；worker 不可。
- 双连接 stop：第二连接失败，事件 1 条。

**回归** 1→29，含 stage 25 的 handoff 测试文件整份退出码 0（不只是上面的缩小回归）。

### 6.5 收尾

加载序 29，至此 29 项。矩阵：指纹方向、转移、授权文案、stop 不改 status、recover 零 nudge、cancel 仍可用、cap 跳过且直调仍 RAISE、tool/call 留置、handoff 回归、折叠只在一个函数。台账 PC-7 = fingerprint 不改 `v13_state_hash`；PC-8 = L29 留置 tool/call、直调仍 RAISE（**无并发复活时、非 explore 路径不 RAISE（explore 例外见小题①）；复活窗口不承诺零 RAISE/绝对不超售**）。parity 文档加「Phase C 状态」节，不改 2026-09-26 的 13/29/29 计数表；把 L26、L6、L38、L5、L21、L32、L27、L29 标成已补并指向本 stage。母计划 D10/D15 行只在 R13 记录已经存在的那次提交里改成「已裁」，与裁决记录同提交或紧随其后，不在 SQL 提交里偷偷改倾向。提交方向：`v13: add goal lifecycle and skip spawn at cap`。

### 6.6 错误与边界

| 情况 | 结果 |
|---|---|
| 重复 stop / 过早 resume（非终态且无在途时） | `v13: goal lifecycle`，零写 |
| stop/resume 时存在 ready/claimed/unknown 任一在途 | `v13: goal busy`，零写（§1.4 r5；终态与在途并存时文案 = `v13: goal lifecycle`） |
| 状态已变（**非终态**下，r33） | `v13: goal fingerprint`，零写；折叠保持 stopped |
| 终态 stop/resume（含无在途、指纹已漂） | `v13: goal lifecycle`，零写（终态先于指纹——§1.3 r33 同链） |
| 非 operator | `v13: session not found` |
| reason 空 | 守卫在 `v13_append_event` 内部、行可见之前 RAISE，异常回滚故 `next_seq` 净增 0、零写 |
| 到顶 | `'waiting'`，tool/call 留置 |
| 预算政策损坏 | RAISE，与静默跳过区分 |
| 空会话 stop | 允许（fingerprint 可算，**观察** `v13_state_hash` 对无事件会话有定义：events 聚合为 `[]`）。resume 随后允许，直到别的事件出现 |

## 7. 全局红线（每 stage 收尾）

1. 新关系只有策略行（既有表上的 INSERT）与 events 上的开放 type。索引只在裁决采纳的那几条部分索引上出现，名字与本文件一致。
2. stage 1–20 文件字节不动。Phase A/B 的 SQL 文件本阶段不改。换体底稿是当日 dump。
3. 唯一推进函数仍是 `v13_advance`。`v13_should_run` 不入队、不 closeout、不改 status。hint 不调用 advance。
4. 投影不授权：attention 的真与 hint 的 `run_now` 都只表示可以再读或再调 advance。
5. `duty_cycle=0` 的写入者仍是 prework 的 `triage/hold`。lifecycle 不用 turn 水位。
6. 不写 `quota/spent`、`quota/voided`。不把 `turn_no`、`decisions.epoch`、`quota_remaining` 当成窗口余额或停复标志。
7. 外部 IO、`pg_sleep`、`LISTEN`、`pg_terminate_backend`、`pg_cron` 注册不进入 stage SQL。
8. 每个 stage：本目录测试退出码 0，回归此前全部 stage，按路径 add，一次提交。禁止 `git add -A`、force-push、`--no-verify`。
9. 架构审计：无控制表、无物化、无影子状态；亲缘判断不在本阶段复制（不读 `parent_session_id` 做第二套 F17）；指纹函数只有 `v13_goal_fingerprint` 一份排除逻辑。
10. 换体保留 ACL。新函数默认 REVOKE PUBLIC，只 GRANT `v13_route`，除非 §6.2 写了别的对象。**例外（r21/r28/r34 与步 9a/步 15/§4.2 步 5 同句）：触发器函数（`v13_sessions_parent_immutable`、`v13_goal_event_guard`、`v13_material_time_honest`——**末者仅 §1.9bis 裁①时存在**）只 `REVOKE EXECUTE FROM PUBLIC`、不 GRANT 任何运行角色（点火无需 EXECUTE）；wrapper/snapshot 按 §1.5 五句 ACL；**policy_share 的 ACL 只以 §1.1 r35 为准（REVOKE PUBLIC + 仅 GRANT route）**。**

## 8. 假绿对照

| # | 假绿样子 | 钉 |
|---|---|---|
| 1 | 只在 prework 调用 should_run，spawn 仍发生 | `test_spawn_suppressed_when_duty_block` |
| 2 | 会话锁后立即 return，cancel 不再 closeout | `test_cancel_not_blocked_by_projection` 期望 terminal |
| 3 | 门包住 finish closeout | `test_finish_closeout_despite_block` |
| 4 | duty=0 默认不再 spawn | 策略 A 对照必须 `'progressed'` |
| 5 | 假路径也写 `triage/hold`，和 duty 无法区分 | 配额假路径断言 hold 行数为 0 |
| 6 | 布尔在 spawn 前算一次，后面复用 | 源码断言每次入队前调用；禁止跨 material 的局部缓存 |
| 7 | 改序必须改函数才变获胜门 | `test_gate_matrix` / `test_order_data_not_body` 期间 oid 不变 |
| 8 | 用 `v13_policy()` 读行，缺行文案带策略名 | 断言 SQLERRM 是 `v13: should_run policy` 或 quota/capabilities 专用句 |
| 9 | 窗口用 `effects.created_at` 或 closeout `material_count` | 源码断言与「别的会话 / 子树不计」 |
| 10 | 写入 `quota/spent` 让计次变简单 | 源码与 events 类型计数 |
| 11 | `allowed` 种子很紧，回归红了再把断言放宽 | 种子必须是 §1.9 的松值；紧值只在 SAVEPOINT |
| 12 | 能力减数找不到就当成空，全部缺失或全部具备 | 安装探针停工 vs 空 `required` 零行，两条都测 |
| 13 | `human_reward` 顺手插 tools 或改 decision | 行数断言 |
| 14 | attention 把 rank UPDATE 进某表，或建成 VIEW | `information_schema` 与 SQL 文件断言 |
| 15 | hint 插 cron 或写事件当 ack | `cron.job` 行数与 `next_seq` |
| 16 | `run_now` 之后不再看策略 | 两连接：先 hint 后翻 `allowed=0` 再 advance |
| 17 | 三处各写一份 `SELECT ... goal/stopped ORDER BY seq` | `test_single_fold_body` |
| 18 | 为了 resume 能过，把 `goal/*` 放进 `v13_state_hash` 排除名单 | `h_after <> h_before` 且（草案案下）禁止换体 state_hash；若 R13 采纳换体案，方向断言改为「stop 不改哈希」且须证 closeout 收据语义随之回归 |
| 19 | stop 时顺手 cancel 或改 status | effect 与 status 断言 |
| 20 | 重复 stop 返回成功 | 必须 `v13: goal lifecycle`（R13 若采 replay 替代则按裁定改钉） |
| 21 | 到顶仍调用 spawn，把 RAISE 接住当成 skip | 禁止 EXCEPTION 收 `spawn budget cap`；直调测试仍看见 RAISE |
| 22 | 到顶时写空 `params` 或失败 tool/result | 事件类型计数与 effect 数 |
| 23 | 从 triage 文件回贴 advance，丢掉 stage 26 读点或 worktree bind | 相对当日 dump 的差集 |
| 24 | `REVOKE ALL` 换体 advance，route 不能再推进 | 安装后 privilege 断言 + 回归 stage 20 |
| 25 | L27 再写一个政策函数，B 的重放顺序被改掉 | 无新函数；同身份重放在 disabled 时仍返回旧载荷 |
| 26 | stage 26 源码已含 `v13_goal_lifecycle` | `test_source_delta` |
| 27 | 用 `quota_remaining` 当窗口 | 源码不含该键；不换体 `v13_triage_project` |
| 28 | 部分索引建成无 WHERE 的全表索引 | `pg_get_indexdef` |
| 29 | 超户 stop 当 operator 合同 | `SET ROLE v13_route` 的真 COMMIT |
| 30 | defer 之后继续 route，cap 期间 effect 数上升 | `test_cap_skips_spawn` 的 effect 数 |
| 31 | P-harness 只包 enqueue，假路径写孤立 `turn/route`（harness_continuation） | `test_continuation_suppressed` 的事件计数断言 |
| 32 | explore 路由 tool/call 在门为假时被改成 waiting（吞掉误用 RAISE） | `test_explore_raise_survives_gate` |
| 33 | cap-defer 后 continuation 仍入队烧预算（或裁决后未按选定分支写断言） | defer 提前返回的 effect/事件计数断言 |
| 34 | 终态会话 stop 成功写入无意义治理事件 | 转移负例（终态 → `v13: goal lifecycle`） |
| 35 | 有在途 effect 时 stop，结算后 resume 永拒、目标永久 stopped | `test_stop_busy_rejected` / 漂移分支断言 |
| 36 | stop→cancel→终态后投影仍报 goal_stopped（三读面不一致） | `test_terminal_gate_priority` |
| 37 | wrapper 不是 DEFINER/属主不能锁策略行时 route 身份 cap 用例 42501；或 route 意外获得 advisory_class EXECUTE | `SET ROLE v13_route` 的 cap 实跑 + 安装后五句 ACL 断言 |
| 38 | quota 函数两次取时钟不同瞬间 / STABLE 内裸 clock_timestamp | 源码断言单次捕获局部变量 |
| 39 | stopped + max_cycles 被 budget_exhausted closeout 打成终态，resume 永拒 | `test_stop_max_cycles_not_failed` |
| 40 | cap 留置会话 hint 落 run_now，driver 空转；或 3.5 分支 requested/root 走法与 advance 不一致误判 | `test_hint_matrix` 的非根超 cap / 预算恢复两臂 |
| 41 | wrapper 体内未限定业务名（`FROM sessions`/`hashtext(` 裸用）或 pg_temp 未排末位 | proconfig/prosrc 断言（r18） |
| 42 | **仅 §1.9bis 裁①；裁②则本行随具名 writer 重写，不得再要求 `trg_material_time_honest`**。超户滑出绿 + route 未来插不进，或 (txn, clock] 缝/route 放行臂未钉，误当守卫已证明 | `test_material_backfill_rejected` **七臂**（txn-30h / clock+60s / **SET ROLE route** 新事务省略 at / clock-90s / (txn,clock] 缝（statement_timeout=0）/ 超户行仍在且 at 不改写 / 61s 长事务）+ 源码可执行式断言 |
| 43 | 门假时 resolve/failed 被吞（唯一审计落库行丢失），或 duty=0 误预写 | 负臂（duty=0 不预写）+ 源码三合取项/append 位置在 stage 26；**正臂行为 stage 27（R13c-B）——源码在场不等于正臂行为通过** |

## 9. Phase B 落地后复核指导

stage 26 的硬前置。Phase B 收尾后、写 stage 26 SQL 前执行。结果写进台账一段（号由 R13 分配），不改 F17 四动词合同，不改 D16 信封。

当前事实（r6）：`v13/load.py` 已注册 25 项（末项 handoff=25，文件在工作区**未提交**；已提交末笔 = observe=24）。**注册≠已绿**：B1 复核仍须 handoff 已提交、`v13/handoff/` 四件齐且 stage 1→25 全部 gate 实跑退出码 0。下表「期望」是 Phase B 完成后的产出。

### 9.1 绑定假设

| # | 假设 | 写作时证据 | 不符时 |
|---|---|---|---|
| B1 | 加载序长度 25，末项 `handoff`=25，其前为 `observe`=24、`acl`=23；handoff **已提交**且 1→25 实跑绿 | r6 时点：25 项已注册、handoff 文件在工作区**未提交**（已提交末笔 = observe=24 `7b0e53c`）。注册≠已绿 | 末项不是已提交且已绿的 handoff → 不追加 should_run |
| B2 | `v13_cancel(uuid,uuid)` 是唯一正文，`v13_cancel(uuid)` 是 `actor=NULL` 的包装 | Phase B §3.2 | 签名不同 → 停。本阶段不调用 cancel 换体，但 stop 的文案风格要与之并存 |
| B3 | `v13_complete` 六参正文 + 五参包装；D12 调用仍在；无吞 `session not found` 的 EXCEPTION；proacl 仍含 route 与 dump 中的其它真实调用方 | Phase B §1.1、§8 A3 | 出现 DEFINER 或吞异常 → 停 |
| B4 | `v13_control_operator()` 与 `v13_control_authorized(uuid,uuid)` 存在，operator 用 `USAGE` 不用 `MEMBER` | Phase B §1.1 | 缺失 → stage 29 停，不重写一套行政带 |
| B5 | `handoff_policy` version 1 active，值含 `schema_version` 与 `enabled=true` | Phase B §1.2 | 缺行 → stage 29 停 |
| B6 | `v13_extract_handoff(uuid,uuid,bigint)`、`v13_handoff_emit`、`v13_transcript_hash`、守卫、**恰两个**部分唯一索引（名称以 B 计划 §5.2 步 9 落地为准）存在；emit 为 DEFINER 且 owner 是 `v13_handoff_owner` | Phase B §1.2/§5.2 | 缺一则停 |
| B7 | extract 与 emit 的 prosrc 含政策读取，且同身份回读在策略检查之前 | Phase B §1.2 控制流/§5.3 | 不符 → L27 不在 stage 29 补门，停工请裁 |
| B8 | `v13_state_hash` 排除名单仍只三个 `session/*`，且未被 Phase B 换体 | 本文件 **观察** control `:390`；B 计划说不换体 | 已含 `control/handoff` 或 `goal/*` → stage 29 停 |
| B9 | advance 未被 Phase B 换体；dump 含 `v13_triage_prework` | B 计划 §1.1 接入闭集（「不接 `v13_advance`」）与 §5.3 源码断言；B 的文件清单没有 advance 换体 | 若 B 为别的原因换了体，以 dump 为底，但准入语义变化则停 |
| B10 | `events.at`、append-only、`v13_policies_frozen` 与脚手架一致 | schema **观察** | 见 §2 证伪 |
| B11 | 无 `goal/stopped\|resumed` 历史行 | 开放词表，B 不写这两 type | 有则 stage 29 baseline 失败 |
| B12 | `v13_route` 返回词表仍无 spawn；`v13_spawn_subsession` 仍 RAISE cap | **观察** | 已被改掉 → L29 的 RED 不成立，停 |
| B13 | stage 1–20 文件哈希与 Phase B 复核时的冻结哈希一致；Phase B 只新增 acl/observe/handoff 与 load.py 末尾三项 | 母计划红线 | C 的提交不得再改这些路径 |
| B14 | 测试夹具：造 snap / user message / harness 前驱的帮手在 triage 或更新的 stage 测试里可找到 | 未知具体函数名 | 开工时打开最新 `test_*.py` 确认帮手名，写进 stage 26 README。找不到就停，不新造第二套信封 |

### 9.2 复核步骤

1. 读 `v13/load.py` 的列表长度与末五项。
2. 实跑 stage 1→25 全部 `test_*.py`。handoff 测试不存在 = Phase B 未绿 = 停。
3. 在 handoff 全量库 dump：advance、prework、recover_idle、state_hash、spawn_subsession、route、control_operator、control_authorized、extract、emit、transcript_hash、duty、pending_human、unconsumed_cancel。记录 owner、prosecdef、provolatile、proconfig、identity、ACL。
4. 列出 events 上全部触发器的 WHEN。确认没有守卫把 `goal/stopped` 算进别的 type 列表。
5. `SELECT type, session_id, seq FROM events WHERE type IN ('goal/stopped','goal/resumed')` 必须空（**不要**用 `LIKE 'goal/%'`——既有 `goal/override` 是 triage 白名单事件（triage `:199`），`LIKE` 会恒非空误判「污染」）。
6. 活动策略名列表含 `triage`、`spawn_budget`、`handoff_policy`，且不含 `should_run`（尚未安装）。
7. 对 stage 1–20 与 Phase A/B SQL 做哈希抽样或 `git diff`，证明本工作区没有顺手修改。
8. 填 §9.1。只有全部「不符时」都未触发，才 GO。

### 9.3 修订协议

- 只差 dump 比 triage 文件多了已记载的 worktree / D12 调用：不改本计划，stage 26 按 dump 插块。
- 差在 advance 签名、search_path 被依赖、EXCEPTION 处理器、亲缘列、state_hash 形状、守卫误伤：停工，把 dump 写进台账请 R13 补裁。实施者不改真值表迁就。
- Phase B 若把 `v13_advance` 换体并改变了 spawn 与 prework 的相对顺序：D10-A 的三个锚作废，回 R13，不在开工日重写锚点。
- 任何修订不把 L32 收成 `duty_cycle=0`，不把窗口收成 `quota/spent` 事件，不增加表或列。
- 复核 GO 之后若又有人改加载序：推倒 B1，重跑本节。

## 10. 文件级影响与实施顺序

| 文件 | 动作 | 时机 |
|---|---|---|
| `v13/should_run/{v13_should_run.sql,setup_db.py,test_should_run.py,README.md}` | 新 | stage 26 原子提交 |
| `v13/quota_window/` 四件 | 新 | stage 27 |
| `v13/attention/` 四件 | 新 | stage 28 |
| `v13/govern/` 四件 | 新 | stage 29 |
| `v13/load.py` | 每 stage 末尾恰追加一项 | 与该 stage 同提交，禁止一次追加四项 |
| 覆盖矩阵 | 每 stage 追加行，不重排、不预写 ✅ | 同提交 |
| 偏差台账 | R13 分配号之后才追加。主题：PC-1 三读点；PC-2 duty shadow；PC-3 松配额种子；PC-4 计次不沿树；PC-5 hint 不注册 cron；PC-6 秩≠调度；PC-7 fingerprint 增量排除；PC-8 L29 留置且直调仍 RAISE | 该事实出现的 stage |
| parity 文档 | 追加 Phase C 状态节，不改旧计数表 | stage 29 或每个补齐项落地的那次 |
| 母计划 D10/D15 行 | 标已裁并指向 R13 记录 | 仅与 R13 记录同批或其后，且裁决已写明采纳项 |
| `docs/reviews/v13-control-plane-oracle-r13-<date>.md` | 裁决记录 | 裁决轮，零 SQL |

不改：`v13/schema`、`control`、`spawn`、`fanout`、`triage`、`loop`、`economy` 及其余 stage 1–25 的 SQL 文件；不新建 VIEW；不改 `demo_v13/`（gitignore 与否都不进本里程碑）。

**实施顺序**

1. ~~R13 审核循环~~ **已完成**（r40 双通道 APPROVE + R13b 决胜；裁决全落、零 SQL 约束解除）。
2. Phase B 全绿后执行 §9。可与第 1 步的后几轮并行，但 GO 与 APPROVE 都齐了才进第 3 步。
3. stage 26：探针 → SQL → `test_should_run.py` → 回归 1→25 → 收尾四件 → 一次 commit + push。
4. stage 27：同样，回归 1→26。`test_quota_blocks_prework_enqueue` 与 `test_quota_blocks_repair_replan_enqueue` 必须存在且绿，补上 stage 26 故意留下的行为洞（r34）。
5. stage 28：回归 1→27。不与 27 并行改 `load.py`。
6. stage 29：先记 RED，再 SQL，再 gate，回归 1→28 且单独再跑 stage 25 handoff 测试。
7. 总验收只汇总已跑 gate：`v13_should_run` 为假时 advance 零新 effect；`v13_quota_eligible` 与能力差可独立调用；hint 双调用零事件；stop 后 recover 零 nudge、resume 后 hint 可为 `run_now`；到顶 advance 不 RAISE 且直调仍 RAISE（**非 explore 路径、无并发复活时；explore 误用例外见小题①；复活窗口见 `test_revive_race_backstop`，不承诺零 RAISE/绝对不超售，r18/r27**）；handoff 缺政策仍拒。不新增跨 stage 大提交，不把 cron、UI、driver 写成已交付。

步骤 3–6 每步单独可装：后一 stage 的 `load_stage` 会加载前一项。禁止在 26 的 SQL 里引用 `v13_quota_eligible` 或 `v13_goal_lifecycle`。

## 11. 不做清单

steer 正文；`closeout/inbox_residual`；`material_cap` 生产者；`thresholds.action` 的 ALTER；把 `v13_triage_project.quota_remaining` 改成窗口余额；reward / `human_reward` 生产者；`quota/spent|voided` 事件或账本表；should-run 状态表；attention 物化；scheduler 状态表、RRULE、ack、心跳；`v13_agent_run`；第二推进函数；把 hint 或 attention 接到 advance 里当写入前的授权；`pg_cron` 行；GUC；新会话列；新 effect status；用 `duty_cycle=0` 实现 L32；用 cancel 实现 stop；stop 时修改/结算/等待在途 effect 或 closeout（busy 是锁内准入检查不是扫描，§1.4 r9）；resume 的 force 位；父 agent 停子会话；改 F17 闭集；重写 handoff 哈希或政策键；XML / 文件水合；把 `v13_spawn_subsession` 的 RAISE 删掉；给 `v13_route` 增加 spawn 键；空 route 对象；`v13_latest_handoff`；改 `v13_state_hash`（草案案下；若 R13 采纳换体案则以裁定为准）；改 unknown 墙；改 stage 1–25 测试里的长度断言（除非 §2 第 10 条允许的那一类，且不在冻结文件里）；把 LoopX 七态名字做成枚举；进程内节拍器。

## 12. 参考文献（追加，不替换 §0.D）

- 本计划送裁记录（待写）：`docs/reviews/v13-control-plane-oracle-r13-2026-09-27.md`
- 三通道与台账预分配格式：`docs/reviews/v13-control-plane-oracle-r8-2026-09-27.md`
- 覆盖矩阵：`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md`
- 偏差台账：`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md`
- Phase B 复核报告（若 §9 另有书面记录，沿用 B 对 A 的写法）：实施时落 `docs/reviews/`，不在本计划里预填结论
- 活体锚文件：`v13/triage/v13_triage.sql`、`v13/spawn/v13_spawn.sql`、`v13/control/v13_control.sql`、`v13/schema/v13_core.sql`、`v13/loop/advance.sql`、`v13/economy/v13_economy.sql`、`v13/load.py`
- 本计划裁决记录：`docs/reviews/v13-control-plane-oracle-r13-2026-09-27.md`（§0 收敛表 + R13b 补记）

---

**开工条件（同时成立才写 SQL）：** ~~R13 全通道 APPROVE + 终裁版~~ **已满足**（r40 双通道 APPROVE + R13b 决胜 + 本终裁版 r41）；**§9 复核 GO**（B1–B14 无一条走进「不符时」——Phase B 全绿且 handoff=25 已提交）；**RED（L29）已复现并记入 stage 29 README**。在此之前，`v13/should_run`、`v13/quota_window`、`v13/attention`、`v13/govern` 目录不应出现。第三通道（claude-fable）缺席：经用户 2026-09-27 指示由双通道收口，如后续要求可在该车道补一轮终检（不重开已收敛项）。
