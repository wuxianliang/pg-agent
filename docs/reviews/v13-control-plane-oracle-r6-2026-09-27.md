# v13 控制面 Oracle R6 终裁：D11 无事件盖章分支复裁（2026-09-27）

> **R7 后续（2026-09-27）**：D12 锁协议经 R7 复裁（守卫无锁）——见 `docs/reviews/v13-control-plane-oracle-r7-2026-09-27.md`。本文 D11 裁决与 §4 GRANT 修正不受影响。

- 触发：Phase A 前置核查（`v13/seam/preflight.md`）触发 STOP-D11——R5 四/五轮要求的 turn/route payload 指向字段在两个 harness 入队臂都不存在，且 new 臂物理不可能（ltid L406 才生成、effect_id 由 enqueue 派生，均晚于 L343 事件写入），与 R3a §7.1 裁定的 payload 闭集 `{action,reason,tool,params}` 互斥。两份已裁条文冲突，复裁。
- 通道：三车道（grokBuild grok-4.7-build-fast-xhigh / codex gpt-5.6-sol@xhigh / claude-fable-5@xhigh）**一致选定候选①**。全文：`prompt-exports/oracle-review-2026-09-27-001721-new-chat-4d2d1b-dc8e.md`（gitignored）。
- 地位：与 R5 同级。**只替换** R5 §1 条件 4 的 no-event 分支、其后的指向性探针勘误、以及 Phase A 计划中依赖该分支的条文（§3.1.7②、§3.3 条件 4 无事件支、§3.7 无事件夹具）。以下不重开：D11 条件 1/2/3/5、D11b、anchor 按类最早/类内并列零行、session+origin 双收窄、wait/material 恒不豁免、D12/D13/D14/第四务、R3a §7.1 payload 闭集与盖章模式、R3b 注册表其余、零新表零新列、stage 1–20 字节冻结。
- preflight §1–§5、§7 的 GO 一并采信：四 gate 预绿；证伪清单四项；closeout ③=(C)（只查 predecessor，不改 closeout）；**PERFORM 搬移不需要**（`p_keep` 已排除被取代链）；state_hash 是排除名单（§3.2 13b 步不触发）；complete/resolve_unknown 无 EXCEPTION 块（resolve 直线可加）。

## §0 总表

| 候选 | Verdict | 一句理由 |
|---|---|---|
| ① 条件 4 只认 has-event 分支 | **选定（修订后）** | 唯一不给冻结 payload 开口子、不落被禁兜底，且经 predecessor/`p_keep` 论证在一切可达路径上与 R5 完整条件 4 行为等价 |
| ② payload 增补指向键 | 拒绝 | 为一个不可达分支修订 R3a §7.1 冻结裁定，波及按「payload 恰为闭集」阅读的既有面与冻结 gate；new 臂两条路都有硬代价（ltid 提前使非 harness 路由也生成 uuid；事件后移反转 continue 臂次序并改崩溃语义） |
| ③ advance 内部变量传入谓词 | 拒绝（不可行记录） | 签名冻结；调用方注入「已铸成」把可证谓词降级为信任参数 |
| ④ events.source_effect_id 列替代 | 拒绝（R5 已否维持） | 入队前该列为 NULL；其语义是「事件由哪条 effect 写入」不是「指向被入队行」。**注意区分**：has-event 分支用该列定义「该行自己的事件」是正常归属关系，不是④ |
| 第五条路 | 无 | 证据源只剩 payload 键（=②）、events 列（=④）、行自身结构证据（=①）三类 |

## §1 选定边界（条件 4 替换条文）

条件 4 改为（替换 Phase A 计划 §3.3 条件 4 全文）：

> 4. 新回合已盖章（不必 succeeded），相对与候选信号匹配的那一行 anchor：同 session、同 `origin_user_seq` 存在 harness effect `n`（判定与 `v13_harness_tail_gap` 相同），`continuation_index=0`、`logical_turn_id` ≠ 候选，且存在事件 `ev`：`ev.session_id = n.session_id AND ev.source_effect_id = n.effect_id AND ev.seq > 该 anchor_seq`。`n.status` 不过滤（ready/claimed/succeeded/failed/cancelled/unknown 一视同仁，但 ready/claimed 行通常无自身事件）。**无自身事件的行永不充当盖章证明**——单凭行可见、插入晚于 anchor、行数、`created_at`、UUID、xmin、route `reason` 或无归属的 `turn/route` 均不计（现有 turn/route 的 `source_effect_id IS NULL`，不属于任何行的自身事件）。至少一行满足即盖章（不是恰一行）。事件类型不设白名单。禁止行数计数、payload 过滤、reason 区分、时间戳/UUID/xmin/快照可见性——**对象改为「不得用它们复活无事件分支」**。不得改回「必须 succeeded」。

四条明确：

1. 不退回「必须 succeeded」——R5 风险 2 仍关闭：失败/进墙重试格靠失败行自己的事件盖章。
2. 无事件行永不盖章；R5 四/五轮「指向性 turn/route 探针」分支整体删除。
3. anchor 之前已存在的无事件 index-0 不算；它若后来获得 `seq > anchor` 的自身事件，按已生效的 has-event 分支算（**不加**「行出生必须晚于 anchor」——那又需要一个插入探针。fable P2 存档：该支可被「anchor 前兄弟行 + 迟到事件」伪证，若要收紧须另开裁决，本裁决不裁）。
4. turn/route 键集、continue 先 route 后 enqueue、new 臂 L343/L406/L408 次序、重试臂先 enqueue 后 route、closeout 形状 (C)、PERFORM 位置——全部不改。

## §2 行为边界

- **parity #10 主路径仍闭合**：铸新格当次 `p_keep`=被取代链 → gap 扫描看不到 → 不 RAISE；新回合 finish 落自身事件（`seq > anchor`）→ 条件 4 真、predecessor 变为 finish 行 → 下次 advance 不 RAISE、`closeout completed` 成功。
- **cap 已答但未铸成（铸新前崩溃）**：谓词 false。被取代链此时仍是 predecessor 即 `p_keep` → **tail_gap 不报**；fail-loud 落在 closeout `v13: closeout continuation owed`（≠ tail_gap 文案——原计划该负例断错层，已修正为两层断言）。崩溃后下一次 advance 仍可铸新。
- **failed 后重试格**：failed 行有自身事件（`seq > anchor`）→ 豁免真；重试行同 ltid index+1 走原后继/重试臂。**若活体对 failed 结局不写自身事件 → 该正例停工记台账，禁为盖章改 `v13_complete` 写集。**
- **残留窗口（ready/claimed 零自身事件）**：谓词 false，且按活体**不可达触发**——predecessor 排序 `max(seq) DESC NULLS LAST` 使无事件新行赢不过有事件旧链，三处 PERFORM 的 `p_keep` 都=当时 predecessor=旧链，旧链被排除出候选 → tail_gap 根本不被问到。窗口内非逃逸 closeout 仍 RAISE `continuation owed`（形状 (C) 接受）。worker claim/complete 不经 tail_gap，行照常推进；行落自身事件后窗口结束自愈。唯一推理依赖「advance 三处读的 predecessor 与 `v13_harness_predecessor` 同一排序」由 gate W2 实测钉住；实测相反则回退「如实记录+台账」读法，禁改兜底。
- 重泵观测三分支（RAISE 零新行 / 返回零新行 / 再铸 index-0）据实**硬编码写死**进 gate，不得写成「均算通过」的永久宽松断言；(c) 记台账，stage 21 不加幂等守卫、不重排 advance。

## §3 gate 修订（合并三通道；替换计划 §3.7「无事件盖章五夹具」组）

主路径与盖章组：**W1 主路径自愈**（cap 已答→铸新→生产 claim/complete 落自身 effect_done→再 advance 不 RAISE + 谓词直调 true + closeout completed）；**G2** finish 的 effect_done 与 failed 结局各一正例；**G3 failed 重试边界**（豁免真、下一 advance 走既有重试臂；活体 failed 无自身事件则停工记台账）；**G4** anchor 前无事件 index-0 → false（p_keep≠该链时 RAISE 原文案）；**G5** anchor 后有 turn/route（source NULL，含两种 reason）但行无自身事件 → false；**G6** 旧无事件行仍在 + 新行有自身事件 → 豁免（不得因两行失败）；**G7** 两条 post-anchor index-0 都无自身事件 → false 仍 RAISE；**G8** 自身事件 `seq <= anchor` → false（他行事件、source NULL 事件不计）。

窗口组：**G9 未铸成**（无任何 index-0 → 谓词 false；`tail_gap(p_keep=断链)` 不因本链 RAISE、`tail_gap(p_keep=旁观者)` RAISE 原文案；再 advance 恰铸一条 index-0）；**G10 残留窗口硬断言**（cap 已答 + 新 index-0 ready/claimed 零自身事件 → 谓词 false；`tail_gap(p_keep=旧链)` 不因本链 RAISE、旁观者 RAISE；非逃逸 closeout RAISE `continuation owed`；重泵 advance 实测分支记名写死 + 零写断言（零新 effect/零新 event/status·fence·request/session 不变）；(c) 支记台账）；**G11 自愈**（G10 库上 complete 该行为 finish → 豁免真、advance 不 RAISE、closeout completed 成功）；**G12 worker 推进独立性**（窗口 RAISE/返回后 ready/claimed 行仍可被 worker 正常 claim/complete，不依赖新的 advance 成功）。

源码断言：`v13_tail_gap_cap_exempt` 盖章扫描只查 `source_effect_id = n.effect_id` 与 `ev.seq > anchor_seq`；函数体不出现 payload 取键（`->>'effect_id'`/`->>'logical_turn_id'`/`harness_effect_id`）、不出现无事件行计数、不出现 reason 区分。

按类最早、臂 (a)/(b) 各一正例、类内并列零行、双信号、跨 user turn、同 turn index+1、两条独立 gap、跨会话诱饵、cap 字面量只住 anchor：原样保留。

## §4 GRANT 闭包修正（fable P1，文案对齐活体，不重开 D12）

preflight §7.2：`v13_complete`/`v13_resolve_unknown` 均 INVOKER，EXECUTE 只在 `{postgres, v13_route, v13_spawn_owner}`；`v13_worker`/`v13_resolve` 为假（`rolinherit=false`，成员关系不带 EXECUTE）。计划原句「结算侧 v13_worker…须有 EXECUTE」照写即是 ACL 放宽。修正：`v13_record_worktree_released` 授给 `v13_route`（+`v13_spawn_owner` 若其调用链到达）；**禁授 `v13_worker`/`v13_resolve`/PUBLIC**；gate 加 `has_function_privilege` 断言（写者对 route 真、对 worker/resolve/public 假）。`v13_cap_human_answered` 保持原 ACL；`v13_worktree_state` 只 GRANT `v13_route`。

## §5 台账 F24

| # | 事实 | 处置 |
|---|---|---|
| F24 | D11 无事件窗口（R6，≠ parity F24）。条件 4 只认「自身事件 `source_effect_id=effect_id` 且 `seq>` 匹配类 anchor」；ready/claimed 无自身事件行永不盖章。窗口内 predecessor 仍是旧链、`p_keep` 排除该链（tail_gap 不可达触发）；closeout 形状 (C) 仍 RAISE `continuation owed`；重泵观测据实记 (a) RAISE 零新行 / (b) 返回零新行 / (c) 再铸 index-0；worker claim 不经 tail_gap 照常推进；行落合格自身事件后自愈 | 接受残留。不改 R3a §7.1、不补指向键、不改 closeout、不搬 PERFORM；(c) 不在 stage 21 加守卫。禁用清单不变 |

## §6 文档落地（已完成）

1. 本记录新增；R5 记录顶部追加 R6 链接注（原文保留为历史）。
2. Phase A 计划 §3.1.7/§3.3/§3.4/§3.6/§3.7/§3.8/§5.6/头部 按 R6 修订（r6）。
3. 路线图 D11 摘要句改「新回合有自身 post-anchor 事件即盖章（不必 succeeded）；无自身事件的 ready/claimed 行不盖章（R6）」。
4. `v13/seam/preflight.md` 末尾追加 R6 后续状态（原 STOP-D11 是 R5 条文下的有效结论，探针事实不改写）。

## §7 分叉与存档

- 窗口描述：grokBuild「重泵并不必然 RAISE」vs fable「不可达（predecessor/p_keep 论证）」——合并取 fable 论证为裁定理由、grokBuild 的「实测记名」为 gate 义务（推理依赖被 W2 钉住，实测相反回退记录读法）。
- codex：重泵断言不得写成永久宽松（已并入 G10）；preflight 追加注记不回写历史（已并入 §6.4）。
- fable P2 两条存档（复访触发）：①has-event 支可被「anchor 前兄弟行 + 迟到事件」伪证——收紧须另开裁决（改「最早自身事件 seq > anchor」）；②R6 前计划缺反 payload 探针复活的源码断言——已并入 §3 源码断言，不再是缺口。
- ② 若未来另案重开才需：键名、生成提前 vs 写入后移、R3a §7.1 修订句、recall/envelope/candidate_set_hash/冻结 gate 读面核查。本裁决不授权。
