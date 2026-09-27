# v13 Phase C 计划批判（r0 → 送裁前）

> **处置注（2026-09-27，r19 时点更新）**：本稿是对送裁稿 r0 的批判。其发现已由计划 r1 起逐轮折入（r1 直接修清单全部落地；L5 三序/在途映射/slot 端点案等已进 §1 替代项表与分歧一览；锁序/ACL/复活竞态等后续轮次深化）。正文保留为历史记录；仍开放的只有 §1.10 列出的显式裁点（③⑥⑧⑨等），由 R13 记录落裁。本稿不重开已冻项——R4 表达形式、D8（`goal_id=session_id`）、D9 公式骨架、R8 的 F17/F29 合同、R3 失败模式，经逐项核对计划均未重开（D15-A-alt 换体 `v13_state_hash` 案只动排除名单、不动表达形式，属合法后 stage 换体）。§1 裁决面的「草案+替代项+送 R13」结构本身不是缺陷；下面只追**折叠失真、自相矛盾、被码证伪、两边都没盖住的缝**。

身份：correctness & completeness critic，不是共同作者。不重写计划。
对象：`docs/plans/v13-phase-c-governance-projections-plan-2026-09-27.md`（r0）对照
`prompt-exports/oracle-plan-2026-09-27-074444-phase-c-l2-8ebdee-c8aa.md` 的三车道生成稿
（lane 1 = grokBuild 完整稿，计划的基座；lane 2/3 = codex 两份残稿，1242–1853 行与 1855–3474 行）。
组合 prompt 与选区转储不当计划。lane 1 → 计划的整合逐段 diff 过：lane 1 本体几乎逐字存活，计划的新增主要是 §1.0 四分歧一览与四条替代项的折入；因此 §1 只记折入失真与 codex 残稿未存活的内容。

抽查范围（点名接缝，不是全库）：`v13/triage/v13_triage.sql` 的 advance 全体 / prework / recover / `v13_triage_block_explore_spawn`，`v13/spawn/v13_spawn.sql` 的 spawn_subsession / occupancy / v_goal_tree / closeout / tools INSERT，`v13/control/v13_control.sql` 的 json 帮手 / 谓词 / state_hash / 守卫 / unknown 墙，`v13/schema/v13_core.sql` 的 events / policies / append_event / tools / 角色与 GRANT，`v13/loop/advance.sql` 的 route，`v13/economy/v13_economy.sql` 的 recovery_active，`v13/load.py`，母计划 §2.2/§2.3/§3/§4/§5，Phase B 计划 §1.1/§1.2/§3.2/§5.2/§5.3/§8/§10，R8 记录 §2，迁移 §2.6。

---

## 1. 三车道承重内容：缺失 / 弱化 / 泛化

整合不是空的。四分歧里 D15-A（换体 state_hash）、D10-B（order+enabled+deny_action）、窗口时钟（禁 `clock_timestamp()`）、stopped→wait 四条都进了替代项表且归属标注正确；lane 1 的探针表、假绿表、§9 复核章、读点表大体逐字存活。下面只记**会改变裁决材料或施工**的丢失与失真。

### 1.1 L5 排序键：两套既存序都没进裁决面，草案是第三套且与本计划门序自相矛盾

三份互不相同的发言：

- 迁移 §2.6 attention 行（计划 §0.D 自认的 L5 语义源）：`attention_rank` = 输出列，**R1：human > unknown > cancel > duty_cycle=0 > 其余按最近材料事件**，且该行「新裁：**否**」。
- codex 两残稿（lane 2 §L5、lane 3 §5.2）：**unknown > human > cancel**，再可跑/被阻/waiting，`depth ASC, session_id ASC` 收尾。
- 计划草案 §1.7：human 1 > unknown 2 > **goal_stopped 3** > cancel 4 > **quota 5 > capabilities 6 > duty 7**，`depth ASC, session_id ASC` 收尾。

计划的 0.C OQ7 与 §1.7 题面都写「roadmap 只说只作输出列、未给序」——对 roadmap 字面为真，但 roadmap L5 行（:111）与 D10 行（:248）都指迁移 §2.6，而 §2.6 给了 R1 序。草案与 R1 两处冲突未披露：duty 的位次（R1 第 4 先于「其余」；草案第 7 垫底）与「其余」的排序键（R1 按最近材料事件；草案 depth+session_id——codex 残稿反而把「按最近事件」列为已否决替代项）。且草案 CASE 里 quota(5)/capabilities(6) 排在 duty(7) **之前**，与本计划 §1.2 的门数组序（duty 第 4，quota/capabilities 由 stage 27 追加在**末尾**，与 roadmap D10「duty_cycle=0，其后接 D9 窗口与 L38 能力」一致）**方向相反**。草案保留 duty 臂的理由是「测试版本把 duty 改 block 时秩稳定」——但真到那天，秩序与门序不一致本身就是一个没人裁过的语义。R13 应在 R1 序 / codex 序 / 草案序三者并陈下落裁，现替代项表（scheduler-order / turn-desc / null-columns）一个都不覆盖。

### 1.2 L21 hint 的第二处分歧没折入：在途 effect 的映射

lane 3 §5.3：`ready/claimed/unknown effect 存在 → dont_notify`（草案统一 dont_notify），`should-run false → wait`。计划 §1.7 分支 3：在途 effect → `wait`。两车道在**两个**维度上都相反（在途：dont_notify vs wait；stopped：wait vs dont_notify），计划只折了 stopped 那一条（L21-alt-stopped-wait）。「在途即 wait」会让 driver 对在跑会话持续轮询；「在途即 dont_notify」会让 driver 沉默直到 effect 结算。语义差别进 driver 合同，不是措辞。§1.0 的四分歧清单自称「在以下四点实质分歧」，实际至少还有本条、§1.1 的 L5、§1.3 的 slot 三处不在其列；§1.10「缺一题不得 APPROVE」管不到未列出的分歧。

### 1.3 D9 slot：lane 3 的第三个设计被 D9-alt-quantize 顶包

lane 3 §4.2：`window_end` = 该会话最新事件 `at`，**向下归一到 slot 网格**，`window_start = normalized_end − window_hours`，计次仍是逐收据；`slot_minutes` 必须为正且整除窗口，**`slot_minutes=0` 非法**。这是与「最小间隔」（草案）和「按桶计次」（D9-alt-quantize 的字面）都不同的第三个设计。计划的替代项表把 lane 3 折成了 quantize，R13 若想采 codex 案，现文本无可机械替换的形状；且计划种子 `slot_minutes: 0` 在 lane 3 形状下是政策错误——「若 R13 采此案」的连带清单（§1.9 末行）只列了资格 SQL 与 gate 夹具，漏种子行与范围校验。

### 1.4 D15-B：终态会话的停/复，两份 codex 残稿都裁了 RAISE，计划整行缺失

lane 2 D15-B 守卫规则与 lane 3 §6.1/§6.2 都写「终态 session 不接受 stop/resume，RAISE 零写」。计划 §1.4 转移表没有终态行，§6.6 错误表只有「空会话 stop 允许」。终态 stop 在计划草案下会成功写入（指纹可算、转移表不拦），留下一条对终态收据无意义的治理事件。允许或拒绝都行，但现在是**未被任何人裁过的默认允许**。

### 1.5 其余折叠失真与弱化

- **D15-A 换体案的采纳注不完整**：codex 两残稿的载荷是恰两键 `{schema_version, state_hash}`（无 `reason`）。计划 §1.3 的采纳注只说「载荷键名回改为 `state_hash`」，没说 `reason` 去留——照字面执行会得到一个三键混合形，既不是草案也不是 codex 案。
- **L27 丢了一枚 pin**：lane 3 §6.6 要求断言「lifecycle 事件**不被** handoff transcript hash 排除」（即 stop 改变 `v13_transcript_hash`，与 B 合同「只排除 control/handoff」一致）。计划 §1.8/§6.4 的 L27 清单没有它。没有这枚钉，以后有人「修好」transcript_hash 对 goal/* 的敏感性时会无声改 B 的合同。
- **锁序探针块丢失**：lane 3 §2.4（spawn 预检咨询锁序与 `v13_spawn_subsession` 兼容；recover 的 lifecycle 读在 `FOR UPDATE SKIP LOCKED` 之后）未进 §2 探针表。§6.2 步 10 的实现位置隐含满足后者，但探针义务没了。
- **§0.E 的 duty 描述被改弱**：lane 1 原文「`UPDATE sessions SET status='waiting'` 且 `status IN ('ready','waiting')`」，计划删成无条件 UPDATE。§1.1 P-harness 又要求「WHERE 与 duty 相同（仅 ready|waiting）」——前后两节对同一行活体代码的描述不一致（活体实测带 WHERE，`v13_triage.sql:381-382`）。
- **D10-B-alt-order-deny 的反驳写错**：「`enabled=false` 总开关与『空 gates 数组=显式全放』语义重叠」——全拒与全放是互补不是重叠；且反驳没接上 codex 形的最强论点：`enabled=false` 给了 stage 26 一条**行为可测的假路径**（lane 3 的 `test_false_returns_waiting_without_effect_or_status_write` 就靠它），而计划的 gates 形在 stage 26 没有可触发的假（§3.4 自认「唯一能为假的已实现门不存在」，行为证明被推给 stage 27）。替代项保留是对的，反驳重写才不误导 R13。
- lane 3 的「多 active 行」负例被 `ux_v13_policies_one_active`（core :708-709）结构性否证，计划没抄——这是对的，不回请。

## 2. 欠规格、自相矛盾、错引用、缺依赖

### 2.1 `v13_triage_block_explore_spawn`：活体 advance 里已有一个 spawn 硬门，三车道与计划全体缺席

`v13_triage.sql:516-533` 定义、`advance` 在 `:643` 无条件 `PERFORM`：存在「未认领 `tool/call` 且其源 effect 的 route reason = `explore`」→ `RAISE 'v13: explore spawn'`。它在 `:644` 的 `IF jsonb_array_length(v_calls) > 0` **之外、之前**。后果：

- P-spawn 锚（§1.1）在 `:644` 之内、`:648` 之前——explore RAISE 永远先于 should-run 门点火。should_run 为假（或 stage 29 的 cap-defer）时，只要待派发的 tool/call 是 explore 路由，advance 仍 RAISE，而不是返回 `'waiting'`。「假路径是 `'waiting'`」与「该次调用零新 effect」对这个子集不成立。
- §2 探针表的入队点清单（:737/:787/…）与 §0.E 的控制序都没有它；它是 RAISE 门不是入队点，但它是 D10-A/L29 的直接邻居。
- §6.4 `test_cap_skips_spawn` 的夹具若恰好用 explore 路由的 tool/call 会红得莫名其妙；反过来，不点名它，实施者无法回答「P-spawn 放 :643 之前还是之后」。

精确修正（钉，不改设计）：§1.1 P-spawn 锚写明与 `:643` 的相对先后（建议门在 explore RAISE **之前**——治理否决不 RAISE；或显式裁「explore 拒绝对所有门优先」并写进假路径例外集）；§2 探针表加一行。

### 2.2 P-harness 只包 enqueue 调用，continuation 臂的 `turn/route` 漏在门外

活体 continuation 臂（`v13_triage.sql:776-787`）：先 `PERFORM v13_append_event(..., 'turn/route', {action:'tool', reason:'harness_continuation', ...})`（`:777-779`），**再** `v13_enqueue_effect(..., 'tool', ..., 'harness_turn')`（`:787`）。§1.1 P-harness「仅包住两处 `v13_enqueue_effect`」按字面实施会把 `:777` 的 route 追加留在门外：假路径每轮 advance 写一条无 effect 配对的 `turn/route`（harness_continuation），不是零事件。approval 臂（:726-748）没有 route 写，只有 continuation 臂漏。§3.4 `test_continuation_suppressed` 断言 effect 数与 repair/required 行数，**没断言** `turn/route` 行数；§8 假绿表无此行（#5 只钉 `triage/hold`）。修正：P-harness 的 continuation 包法从 `:777` 的 append 之前开始（approval 臂从 enqueue 前即可），并把「假路径无新 `turn/route`」写进该用例。

### 2.3 §1.5 与 §6.2 步 14 对 cap-defer 的 harness 入队说法矛盾

§1.5：「`v_defer_spawn` 之后仍执行 harness **结算**……跳过 harness **入队**。然后 `RETURN 'waiting'`」。§6.2 步 14：stage 29 差集「**只**把 P-spawn 的条件扩成 `NOT should_run OR NOT batch_allowed`」。按步 14 的差集，P-harness 的门仍只看 `v13_should_run`——cap-defer 时 should_run 为真，approval/continuation 照常入队，与 §1.5「跳过 harness 入队」直接冲突。两种行为都站得住（跳过：cap 期不烧 continuation 预算；不跳：harness 结算线与 spawn 席位是两套预算，不该连坐），但必须二选一并写进步 14 的差集；§6.4 现有 cap 用例（裸 tool/call、无 harness 前驱）抓不到这个差别，需加「cap-defer + 待 continuation 前驱」夹具。

### 2.4 §9.2 步 5 的复核查询会恒失败

`SELECT ... WHERE type LIKE 'goal/%'` 把既有的 `goal/override`（triage emit 白名单第一类，`v13_triage.sql:199`；§3.4 的 override 夹具也在用它）算进「历史 goal 生命周期行」。任何用过 override 的库上复核步 5 都非空 → 误判「Phase B 污染」。§2 证伪 7 写的是对的（`type IN ('goal/stopped','goal/resumed')`），步 5 改成同一谓词。

### 2.5 D15-B 双写口的授权不对称没有摆进裁决面

§1.4：stop/resume 函数内查 `v13_control_operator()`；守卫（INVOKER）明示「`current_user` 不限死」。`v13_goal_fingerprint` 又 GRANT 给 `v13_route`（§6.2 步 15）→ route 可自算指纹直插一条完全合法的 `goal/stopped`，绕过函数侧的 operator 检查。「直插与函数插入走同一套检查」因此不成立：函数多一道授权。今日授权拓扑下这不放大权限（events INSERT 只授 `v13_route`（core :866）与 `v13_triage_owner`（triage :35）；后者唯一的 DEFINER 写口 `v13_triage_emit` 白名单三类不含 `goal/*`（:199），且 operator 带本来就 = rolsuper ∨ 对 `v13_route` USAGE），但「授权：只 `v13_control_operator()`」的表述与守卫行为不符，且替代项表缺「守卫同查 operator」这一行——这才是与 D15-B-alt-definer 对偶的完整选项集。另：§6.2 步 15「guard 不 GRANT 给 PUBLIC 以外（触发器函数属主执行）」机制写错——触发器函数不需要 EXECUTE 授权，INVOKER 触发器以点火语句的调用者身份跑；改成「guard 不单独 GRANT」。

### 2.6 引用与事实修正（细目在抽查锚）

- 门条件表（§1.2）说「终态会话也可以得到投影未阻塞的真」——成立，但靠的是 `v13_unconsumed_cancel` 自身的终态短路（control :131-140 的 `status NOT IN (...)`）与 unknown 谓词，值得写一句，否则读者会去查 sessions.status。
- §0.E「`v13_spawn_subsession` 在咨询锁内：fanout/depth/cap 三检查」不准确：活体 fanout（:417-419）与 depth（:420-422）在咨询锁（:423）**之前**，只有 cap 前置（:425-426）与复检（:456-457）在锁内。§1.5 的 `v13_spawn_batch_allowed` 把三者都放进锁内是改变了锁序覆盖面（无害，但应写明这不是逐字镜像）。
- §9.1 B9 的证据列写「B 计划 §10 不做清单」——「不换体 advance」的明文实际住在 B 计划 §1.1 接入闭集（「不接 `v13_advance`」）与 §5.3 源码断言；§10 没有这句。复核者按 B9 去 §10 找会扑空。
- 小一号但都在承重句上：`turn/material_spent` 守卫实际 :444-446（计划 :443-446）；events 表 :28-43（计划 :28-41）；`ix_events_last_user` :48-49（计划 :49-51）；`SQL_LOAD_ORDER` :17-40（计划 :15-37，22 项结论对）；`v13_recovery_active` :141-155（计划 :140-156）；`v13_advisory_class` :32-41（计划 :35-41）。

## 3. 被代码证伪，或被更简单事实替换

1. **「现有 events 索引 10 个（含 7 个部分索引）」（§0.B）被目录证伪**：10 个里 **9 个**部分索引 + 1 个全索引（`ix_events_source_type`，control :409）。部分索引是多数派这件事反而加强 §1.6 的「加部分索引不突兀」论证，数字要改对。
2. **§2 证伪 1 的 EXCEPTION 担心已被活体限定**：advance 唯一的 `EXCEPTION` 块（:921-932）只包 sql 臂的 `EXECUTE` 工具调用，吞不到 `spawn budget cap`（该 RAISE 在批量路径，且直选 spawn 在 :879-881 已硬拒）。探针保留，但「证伪即停」的触发概率可由实施者预知为零。
3. **§2 证伪 10 的长度断言不存在**：全库无 `len(SQL_LOAD_ORDER)==20/22`；唯一断言是 `v13/mgraph_assembly/test_mgraph_assembly.py:375` 的 `>= 16`，本就是 §2 允许的「>= 精神」。该条可降为「已知无，无需例外」。
4. **append-only 的准确形状**：`trg_events_append_only` 是 `BEFORE UPDATE OR DELETE`（core :57-59），INSERT 不受它管——计划表述对，但 §1.4 守卫的存在理由应写成「INSERT 侧零约束，新 type 默认裸奔」，而非笼统「append-only」。
5. codex 两残稿的 L29「继续后续 advance 路径」已被计划收进 L29-alt-fallthrough 并给了烧 `max_cycles` 的反驳——驳回成立（活体 post-prework 各臂入队即 RETURN，未认领 tool/call 会每轮重入队）。**但**该替代项没标 codex 归属、没进 §1.0 必裁清单；§1.10 的九题规则能兜住 L29 整题，实践风险低，记录失真仍要修。

## 4. 两边都没盖住的边界

1. **stop 不沿树传播**：折叠是单会话函数，停 root 不停 children；子会话继续跑、继续烧自己的窗口。父停子跑时 recover 对父跳过（✓）、对子照旧；attention 里父子各一行各算各的。「停父是否停树」三车道与计划都没问——若答案是否，README 与 L32 验收句要写「停是会话级」；若答案是是，§1.4 的折叠与守卫都要换形状（递归谓词），这是会改变 stage 29 差集的问题，不是措辞问题。
2. **attention 成本无界**：`v13_attention` 对树上每节点调一次 `v13_should_run_gate`，每次门调用读策略行 + 若干 effects/events EXISTS。大树（数百节点）× 每轮 driver 轮询 = 无界的扇出读。无上限、无分页、无「只对非终态算门」的短路（终态行也算一遍门再沉底）。两侧都没提。
3. **策略翻版的生产执行者不明**：§1.9/§4.5 说「收紧 = 新版本并翻 active」，但 `v13_policies` 只授了 SELECT（core :854），INSERT/UPDATE 只在表主/超户手上。「运维显式选择」经哪个角色落地、要不要一个具名管理函数，两边都没写（这是既有纪律的继承缺口，但本计划第一次把「翻版」写成运维动作，就该写执行者）。
4. **stop 与并发 advance 的两跳收敛**：stop 推 `next_seq` → 持锁后在 probe 处的 advance 先拿 `'stale'`，重试才见 stopped。§6.3 写「后到的 advance 看见停事件」——按字面验收会写错断言（实际是 stale→retry→waiting）。
5. **`resolve/failed`（:803-808）是事件不是 effect，且在 prework 之后**：假路径下它被 P-tail 一并压掉。「前缀结算保持原样」的豁免清单（material 收据、finish/reject closeout、wake、cancel）没列它——一条失败记账被治理门吞掉是否可接受，值得一句显式裁定（压掉它同时意味着 `p_snap->>'failed'` 的语义在假路径下消失）。
6. **取消/超时只剩半句**：§6.3 的阻塞触发器夹具盖了 stop append 的回滚；advance 被门拦在 `'waiting'` 时 driver 侧「等多久算停住」无人认领——这或许属 driver 合同，但 README 两格里该有一句。

## 5. 答案会改变设计或顺序的问题（随 R13 一并送裁）

下列不是重开已送裁题：1–3 是现有裁决题的**可施工性**，4–6 是折入时新冒出或被漏列的分歧，7 是 D15-B 选项集的完整性。

1. **P-spawn 与 `:643` explore RAISE 的先后**（§2.1）：门先则 explore 工具调用在治理否定时不再 RAISE；explore 先则「假=waiting」有永久例外。二者改 §1.1 锚与 §3.4/§6.4 断言集。
2. **P-harness 包法的起点**（§2.2）：从 continuation 臂 `:777` 的 route 追加之前包，还是接受假路径写孤立 `turn/route`。改 §3.2 步 6 差集与测试断言集。
3. **cap-defer 时 harness 入队跳不跳**（§2.3）：§1.5 与 §6.2 步 14 二选一；选「跳」则 P-harness 条件加 `v_defer_spawn`，并加夹具。
4. **L5 三序并陈**（§1.1）：迁移 §2.6 R1 / codex unknown-first / 草案；并裁定 attention CASE 与 should_run 门数组序是否必须同序（草案现状是相反的）。
5. **hint 的在途 effect 映射**（§1.2）：wait（草案）vs dont_notify（codex lane 3）。与 stopped→dont_notify/wait 是同一张分支表，应一次裁完。
6. **终态会话 stop/resume**（§1.4）：RAISE（codex 两残稿）还是允许（计划默认）；选定后转移表与 §6.6 错误表各加一行。
7. **守卫是否同查 `v13_control_operator()`**（§2.5）：不查则把「授权只函数侧、直插不受限」写进裁决记录；查则守卫多一次带内调用。

不需要 R13、应在改计划时直接修（不改变任何通道选择）：§1.3 采纳注补 `reason` 去留；§1.9 D9-alt-quantize 改写成 lane 3 的端点网格归一案（或另列一案）；§1.7 题面披露迁移 §2.6 R1；§0.E 补 duty 的 WHERE 子句；§2.6 的引用修正六条；§3.1 的索引计数；§9.2 步 5 谓词；§6.2 步 15 的 guard GRANT 句；§6.3 的 stale 两跳句；§1.9「去重后若仍有重复」改「含重复即政策错误」。

---

## 抽查锚（供对账，不是新规格；行号 = 2026-09-27 工作区）

**`v13/triage/v13_triage.sql`**

- `v13_advance` :561-1003。会话锁 :577；stale :580-586；worktree bind :592（stale 后、status 读前 ✓）；终态 :595-597；unknown 墙 :598-610（返 waiting）；cancel :611-626（可 closeout terminal）；ready/claimed :627-630（**UPDATE 无 status 谓词**）；`v_calls` 聚合 :633-642；**`v13_triage_block_explore_spawn` :643（IF 外、先于一切 spawn 门）**；spawn IF :644-662（`v13_spawn_subsession` :648、`spawn_fanout` :649-651、succeeded effect :652-657、`tool/result` :658-661、`'progressed'` :662）；`turn/material_spent` 写入 :693-698（IF NOT EXISTS 幂等）；approval human 入队 :737（臂内 budget_exhausted closeout 先于入队）；continuation：`turn/route` 追加 **:777-779**、入队 :787（**route 在入队前**）；prework 调用 :800；`resolve/failed` :803-808（事件无 effect）；abandon :811；context_refresh :828；budget human :842；judge :858；steer :870；route :874；after_route :875；sql+spawn 硬拒 :877-881 / :906-910；CASE 前 `turn/route` :908；sql 臂 EXCEPTION 块 :921-932（只包 EXECUTE）；sql 臂直插 effects :932 一带；tool/llm/human 臂 :946-990。
- `v13_triage_block_explore_spawn` 本体 :516-533（STABLE，RAISE `'v13: explore spawn'`）。
- `v13_triage_prework` :359-397：reject :365-370；duty :372-383（hold emit :376-379、UPDATE **带** `status IN ('ready','waiting')` :381-382、RETURN 'waiting' :383）；enqueue human/llm :385-389；fold_reason :391-393；RETURN NULL :394。`SET search_path` 有（:361）。
- `v13_triage_hold_blocks_recover` :553-560 ✓（duty=0 且 max hold seq > last_user_seq）。
- `v13_recover_idle` :1186-1247：SKIP LOCKED 选行、锁后再验 :1207-1213、duty 跳过 :1213、`{pending,nudged}` 返回。
- `v13_triage_emit` :194-204：DEFINER、owner `v13_triage_owner`（:206）、白名单 `goal/override|triage/hold|explore/completed`（:199）。triage/hold 守卫 :226-233（恰两键、reason 只许 duty_cycle、current_user 必须 triage_owner :209-211）。
- duty 策略行 :3-4；`v13_triage_duty` :45-56（RAISE `'v13: triage policy'`）；`v13_triage_project` 同写 `remaining_turns`/`quota_remaining` :186-187。

**`v13/spawn/v13_spawn.sql`**：`spawn_budget` 行 :24-25；`v13_advisory_class` :32-41（13001 ✓）；`v13_spawn_occupancy` :159-188（`'v13: spawn root cycle'` :183）；`v13_insert_nudge` :189-202（只吞 `ux_events_recover_nudge`）；`v13_spawn_subsession`：形状检查 :407-414、fanout :417-419、depth :420-422（**锁前**）、咨询锁 :423、cap 前置 :425-426、复检 :456-457；`v_goal_tree` :467-506（unknown 无插值 :479、cycle :488、depth :492、ORDER BY depth,session_id）；closeout 收据 `spent.material_count` :763-767（全会话累计）、`state_hash` 键 :773；tools INSERT `spawn_subsession` enabled :1757-1760。

**`v13/control/v13_control.sql`**：`v13_json_keys` :102-106（字母序 ✓）；`v13_json_int_ok` :108-114（`^[0-9]+$` 拒 1.0 与负数 ✓）；`v13_pending_human` :121-127（ready/claimed human ✓）；`v13_unconsumed_cancel` :129-141（**终态短路**：sessions.status NOT IN 终态 ✓）；`v13_harness_request_ok` :143 ✓；`v13_state_hash` :362-400（排除名单**两处**：v_max :377 与 events 聚合 :390——fingerprint 函数两处都要扩）；material 守卫 :444-446（恰两键 ✓）；session 收据 8 键 :460-462 ✓；unknown 墙 = 双射检查（非禁写）：effects 触发器 :609-612、sessions `UPDATE OF status` 约束触发器 :613-616，RAISE `'v13: unknown wall bijection (session %)'`；`ix_events_source_type` :409（events 唯一**非**部分索引）。

**`v13/schema/v13_core.sql`**：events :28-43（`at timestamptz NOT NULL DEFAULT now()` :40，at 上无索引 ✓）；`ix_events_last_user` :48-49；append-only `BEFORE UPDATE OR DELETE` :57-59；`v13_append_event` :62-93（**status 恒在 SET 列表** :79-81 → 每条事件点火 unknown 墙，双射成立故不 RAISE ✓）；`v13_policies` :701-707 + one-active :708-709 + frozen :715-729（拒 DELETE 与 value 改写、放 active 翻转与 INSERT ✓）+ `v13_policy` :731-740（缺行文案 `'v13: no active policy row for % (seed lost?)'` ✓）；`tools` :581-593（name PK、enabled :593 ✓）；角色：`v13_route` NOLOGIN :822、`v13_route_login` LOGIN :836、`v13_worker` LOGIN NOINHERIT :842；`GRANT INSERT ON events` 只到 `v13_route`（:866）与 `v13_triage_owner`（triage :35）；`v13_policies` 只授 SELECT（:854）。

**其余文件**：`v13/loop/advance.sql` route :110-162、type 过滤 :126、无未知 type RAISE ✓；`v13/economy/v13_economy.sql` `v13_recovery_active` :141-155（窗口 = 最近 N 个 user turn 的 `events.at` 边界、比较 `effects.created_at`，**不是** window_hours ✓）；`v13/load.py` :17-40 共 22 项、末三 triage/seam/catalog ✓；长度断言只有 `v13/mgraph_assembly/test_mgraph_assembly.py:375` 的 `>= 16`。

**文档**：迁移 §2.6 attention 行（:140）「R1：human > unknown > cancel > duty_cycle=0 > 其余按最近材料事件」「新裁：否」；roadmap L5 行 :111 与 D10 行 :248（「序用迁移 §2.6 已写的硬门……其后接 D9 窗口与 L38 能力」）、D9 行 :247 有「R4 已裁」、D10 :248 / D15 :253「不开工就停 = 是」且无 R4 标 ✓、Phase C 表 :230-233、§2.3 五机制 :159-164；Phase B 计划 §1.2（四键信封、同身份重放先于策略检查、`handoff_policy` 行 ✓）、§5.2 步 9 两索引名 `ux_events_handoff_delivery` / `ux_events_handoff_snapshot` ✓、§3.2 cancel/complete 主从签名 ✓、§1.1 operator 带 = rolsuper ∨ `pg_has_role(...,'v13_route','USAGE')` ✓、「不换体 advance」明文在 §1.1 接入闭集与 §5.3（**不在** §10）；R8 §2 预分配 F27–F31 + C15/C16 ✓；矩阵末行 #51、台账末 F26/C14/X1 ✓。
