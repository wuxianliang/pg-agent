# v13 Phase C 计划 Oracle R13 裁决记录（2026-09-27）

> 触发：`docs/plans/v13-phase-c-governance-projections-plan-2026-09-27.md` 送裁稿（r0→r40，共 40 轮审核、两车道累计折入 150+ 条发现；批判稿 `docs/reviews/v13-phase-c-plan-critique-2026-09-27.md` 先行）。
> 通道：grokBuild `grok-4.7-build-fast-xhigh` / codex `gpt-5.6-sol@xhigh`。**claude-fable 第三通道本会话缺席**（全程未上线）——终判为双通道一致 APPROVE；如需严格三通道可在补一轮 claude 车道后修订本记录（不阻塞下列已收敛项）。
> 终态：第 40 轮 **双车道 APPROVE**（codex 首次 APPROVE 于第 39 轮；grok 曾于第 16/19 轮两次给出条件性 APPROVE 后因新折入项复检 REVISE）。
> 不重开：R4 表达形式、D8、D9 公式骨架、R8 F17/F29/D16、R3 失败模式——全程未重开。

## §0 裁定表

**已收敛（两车道推荐恒定一致，随本记录生效；生效前计划不开工）：**

| 题 | 采纳 |
|---|---|
| D10-A | 三读点（P-spawn/P-harness/P-tail）+ 布尔不缓存；`>` = gates 短路序；duty 种子 shadow；P-spawn 假即提前返回（status 更新带 session_id 谓词）；harness 前缀结算（material/finish/reject/wake）不进门；budget_exhausted closeout 属新决策随臂跳过 |
| D10-B | `should_run.gates[]` 数组 + `block\|shadow`；两阶段处理（先完整校验再短路）；入口序 = 会话存在性先行 |
| D15-A | 新函数 `v13_goal_fingerprint`（不换体 `v13_state_hash`）；八词无条件排除集（session 三 + goal 两 + control/handoff + wake/satisfied + turn/material_spent）；先转移后指纹（终态即 lifecycle 不进三等）；换体 state_hash 替代案**否决**（不可施工） |
| D15-B | 三键载荷 `{schema_version, fingerprint, reason}`；六步检查序（行锁→seq/turn_no 不变量→终态→busy→载荷（jsonb_typeof 类型契约+非对象前置）→转移/指纹）；`v13_goal_fold` 内部函数（基数=1、stop_fp 一次读出）；INVOKER 守卫；部分索引 `ix_events_goal_lifecycle`；会话级停复（树级不在施工形内） |
| L29 | `v13_spawn_batch_allowed` DEFINER wrapper（唯一全链：会话锁→上行→policy_share→advisory→snapshot）+ `v13_spawn_budget_snapshot` 无锁 STABLE 唯一预算逻辑；到顶提前返回、tool/call 留置；fanout/depth/cap 三轴都翻转；直调 spawn 仍 RAISE |
| L6 | 建 `ix_events_material_spent_at`；本会话计次；slot=最小间隔（0 合法）；未来 at 不计入 |
| L5/L21 | 草案 CASE（不要求与门数组同序）；终态与 stopped→`dont_notify`；在途→`wait`；hint 分支 1.5（未消费 cancel 活性补丁）+ 3.5（预算退避，共调 snapshot）；`p_max_rows`=返回行数预算 1..1024（不保树遍历成本——**L5 附言：采纳即接受该边界，或前移另裁**） |
| L27 | 不新写门；只回归 Phase B 契约 + transcript_hash 跨阶段钉（goal/* 不进 transcript 排除名单） |
| 窗口时钟 | `v_now` = 入口单次 `transaction_timestamp()`，函数保持 STABLE；否决 event-now / clock+VOLATILE / slot-grid |
| 小题① | explore RAISE 保持在 P-spawn 之前（唯一假路径例外；施工形唯一） |
| 小题② | 终态 stop/resume → `v13: goal lifecycle` 零写 |
| 小题④ | 会话级停复（施工形唯一） |
| 小题⑤ | busy 含 ready\|claimed\|unknown；终态先于 busy（并存文案=lifecycle） |
| 小题⑦ | fingerprint 排除两类结算事件（八类固定） |
| 小题⑧ | stage 26 安装 `trg_sessions_parent_immutable`（parent 链不可变由守卫承担；否决则 stage 29 锁序重裁） |
| 小题⑨ | 接受终态兄弟复活超售残留并入台账；总验收只声明「无并发复活且非 explore 时不 RAISE」 |
| 小题⑩ | seq/turn_no 不变量 = numeric 析取（`(NEW.seq::numeric+1) IS DISTINCT FROM next_seq::numeric OR NEW.turn_no IS DISTINCT FROM sessions.turn_no` → `v13: goal seq`）；禁 bigint 加法；「只经 append」是意图不作裁项 |
| 策略线性化 | `v13_policy_share()` DEFINER helper：三步循环（快照读身份→按 name 字母序锁精确 (name,version) 不带 active→重读相等否则重试）；五行 = capabilities/quota_window/should_run/spawn_budget/triage；**范围只覆盖此五行（turn_budget/effect_attempt_cap 等不在内，残留如实记录）**；advance 在 IF v_calls 之外无条件调用 |
| material 时间诚实 | **§1.9bis 二选一：两车道均推荐①**（INVOKER 触发器 `v13_material_time_honest`：`NEW.at ∈ [clock-60s, transaction_timestamp()]` 两瞬时合同、七臂 gate）；②唯一 writer 为替代 |

**R13b 决胜轮（2026-09-27，同通道微裁；经用户指示由 Oracle 裁决剩余分歧）：**

| 题 | 裁定 | 决胜过程 |
|---|---|---|
| 小题③ | **查**（双车道一致） | grokBuild 翻转：其「今日 route 在带内」的闭包被驳——INSERT 面含 `v13_spawn_owner`/`v13_triage_owner`/`v13_handoff_owner`（均带外），DEFINER 写路径 `current_user` 即这些属主，不查则带外直插合法信封即落地；D16 类比被纠正（handoff 守卫拒非属主裸 INSERT，route→emit 只调函数）。施工形：守卫检查序新增 ⓪ 步（行锁前先调 operator，假则 `v13: session not found` 零写不读会话）；`D15-B-alt-guard-operator` 转为已采纳 |
| 小题⑥ | **保留**（双车道一致） | grokBuild 翻转：已钉合同是「重取 snap 再 advance」而 failed 非 probe 字段，压掉即永久丢失事务外已发生失败的唯一落库行；duty=0 活体吞掉行为保持不变。施工形：advance 在 prework 调用前预检（`duty<>0 AND NOT should_run AND snap.failed` → 先 append `resolve/failed` 再由 prework 门返回 waiting；仍零新 effect；duty=0 不预写） |

## §1 施工期硬门（缺一不开工）

1. ~~两项拍板~~ **已满足**（R13b 决胜，上表）；计划终裁版 **r41** 已出（`docs/plans/v13-phase-c-governance-projections-plan-2026-09-27.md`，未采纳分支已删）。
2. Phase B 全绿 + §9 复核 GO（B1–B14 无一条走进「不符时」；基线以复核时点为准——写作期内已三次漂移：acl=23→observe=24→handoff=25 注册未提交）。
3. RED（L29 cap RAISE）已复现并记入 stage 29 README。
4. ~~第三通道~~ **已收口**（用户 2026-09-27 指示：由现有双通道裁决并收口，claude-fable 缺席记录在案不阻塞；如后续要求可在该车道补一轮终检，不重开已收敛项）。

## §2 残留清单（如实记录，不承诺闭合）

- 终态兄弟复活（completed/failed→ready）导致的超售窗口：spawn 复检后至 COMMIT 前可静默超售（小题⑨接受；修复须动冻结面 append/user 路径）。
- `turn_budget`/`effect_attempt_cap` 等非五行策略的翻版竞态（锁协议范围外）。
- attention 树遍历成本无界（返回行数预算不保护；前移有界遍历须另裁）。
- Phase B 并行施工：stage 25 handoff 文件已在工作区未提交（末笔 7b0e53c=observe）——注册≠已绿。

## §3 文档落地

- 计划：`docs/plans/v13-phase-c-governance-projections-plan-2026-09-27.md`（r42 终裁版——含 R13c 两处验收口径修正）。
- 批判稿：`docs/reviews/v13-phase-c-plan-critique-2026-09-27.md`（r19 时点处置注已更新）。
- 台账：Phase C 编号（PC-1…PC-8 及新增主题）随各 stage 收尾分配；F27–F31/C15/C16 归 Phase B 不撞号。
- 审核导出：`prompt-exports/oracle-review-2026-09-27-*.md`（gitignored，各轮全量）。

## §4 R13c 微裁（2026-09-27，双通道；stage 26 开工停工两冲突）

- 触发：stage 26 实施者按合同停工——当日 dump 与 r41 两处条文不可同时满足（停工报告全文在会话记录；证伪清单零命中、语句锡无漂移）。
- **A（current_setting）**：绝对禁词误伤预存守卫——活体 advance 恰 1 处 `current_setting('statement_timeout', true)` 在唯一 EXCEPTION 的 query_canceled 臂（triage 底稿自带）。裁定：改差集断言（次数=1、调用文本逐字、臂语句文本仍为子串；prework=0；其余六词绝对零）；不删臂不写死行号。双通道采纳（grok 精确句入计划）。
- **B（小题⑥正臂不可达）**：前缀三门（unknown/blocked_unknown、unconsumed_cancel、任一 ready/claimed）早退先于预检点，duty_cycle 门与预检条件互斥 → stage 26 无夹具可达正臂。裁定：双臂分阶段——负臂行为（duty=0 不预写）+ 源码断言（三合取项与 resolve/failed append 均在 prework 调用点前）在 stage 26；正臂行为验收入 stage 27 done-when；#43 注明源码在场≠正臂通过。施工形（预检代码）不动。双通道采纳。
- 台账：C17（见偏差台账）。
- 导出：`prompt-exports/oracle-review-2026-09-27-203023-*.md`。
- **C（parent 守卫文案不可达）**：r42 复工后第三停工——stage 18 既有 `trg_sessions_fork_cols_immutable`（BEFORE UPDATE OF parent_session_id,... → `v13_spawn_cols_guard`）按名序先火，小题⑧新触发器的 `v13: parent immutable` 永不可达。裁定（双通道采纳，grok 精确句）：**不装新守卫**，执法者保持既有实例；行为（route/spawn_owner×IS DISTINCT FROM×格式串全等×NULL→非 NULL 臂按可构造性，不 RAISE 则停工）+ 结构（OF 三列/函数/新名不存在）+ 源码（无新触发器无新文案）三段验收；九处条文清扫（§0/§1.5/裁决终态/探针表/§2-15/§3.1-3/§3.2-9a/test_parent_immutable/§4.2-10）+ 头部 r43；台账 C18。锁序重裁不触发（不可变执法已在位）。导出：`...-205305-*.md`。
