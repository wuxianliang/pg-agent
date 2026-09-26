# v13 Phase A 开发计划：修地基（stage 21 seam + stage 22 catalog）— R5 终裁版 r2

> 状态：**现行版 r7（2026-09-27，可开工）**：R5 终裁 + 五轮审核 APPROVE + R6（D11 无事件分支窄化）+ R7（D12 锁协议死锁复裁：守卫无锁）。裁决记录：`docs/reviews/v13-control-plane-oracle-r5-2026-09-26.md`、`...r6-2026-09-27.md`、`...r7-2026-09-27.md`；前置核查：`v13/seam/preflight.md`。审核导出：`prompt-exports/oracle-review-2026-09-2*.md`（五轮）与 `oracle-review-2026-09-27-*.md`（R6/R7）。。
> 母计划：`docs/plans/v13-layered-control-roadmap-2026-09-26.md` §3 Phase A、§4 D11–D14、§5 红线。
> 本文件替换 2026-09-26 骨架；R5 与路线图倾向文字冲突处以 R5 为准（路线图已同日同步，含 §2.3）。
> 硬边界（不重开）：零新表零新列（R4 扩写含物化视图/投影表）、stage 1–20 SQL 文件字节冻结、唯一推进函数、events 唯一干预通道、R3 链已冻失败模式（C4 RAISE、终态 `replay`、`v13_interruptible` 闭集）。索引、只 RAISE 的守卫触发器、开放事件、STABLE/VOLATILE 函数不是新表。

## 0. Goal 与交付物

| Stage | 目录 | 交付 |
|---|---|---|
| 21 | `v13/seam/` | D11 cap×tail-gap 豁免（含 D11b 委托 + closeout ③ 同源）、D12 `worktree/released` 事件 + `v13_worktree_state` 投影、路线图 R5 条目（children_terminal 端到端 gate）、D13 台账行（零 SQL） |
| 22 | `v13/catalog/` | D14 catalog 具名 VOLATILE 例外（OID 绑定）、第四务假 worker 合同 gate + demo 驱动器补丁（gitignored） |

验收读法（路线图 Phase A，已按 R5 同步）：**续传不再被已答 cap 卡死；首次成功 release 写 `worktree/released`、latch 仍 `prepared`、`v13_worktree_state` 折叠 `released`；第四务有驱动合同；`children_terminal` 能走完 advance；parse 能看见具名 sql 工具。**

全程零新表零新列；`SQL_LOAD_ORDER` 只在末尾追加两项（21 seam、22 catalog）；换体一律 `CREATE OR REPLACE` 且底稿 = **stage 20（含）全量加载后的 `pg_get_functiondef` 活体**（全树每函数只有一份活体；control/spawn/fanout/triage 的行号是历代文件，不是并行调用点）。

## 1. R5 终裁摘要（本计划的施工依据）

| 题 | 裁决 | 施工要点 |
|---|---|---|
| D11 | 修订 | 豁免进 `v13_harness_tail_gap`（原 EXISTS 一字不放宽，只追加 `AND NOT`）；anchor 复合返回 `(anchor_seq, cap_class)` **按类最早**；候选/cap/新回合三者同 `origin_user_seq` 且全扫描以 `session_id=p_sid` 收窄；新回合**盖章即可不必 succeeded**（无事件 ready/claimed 只认插入晚于 anchor 的行）；closeout 严格前置③与 tail-gap 共用同一豁免谓词 |
| D11b | 采纳委托 | `v13_cap_human_answered` 换体 ≡ `EXISTS(anchor(...))`；签名/波动性/**原 ACL** 不变；乱序与跨 user turn 的 legacy human 都不再跳过续传（收紧，gate 双断言） |
| D12 | 取 (a) 修订 | `worktree/released` 事件为 released 唯一权威；latch 行永久 `prepared`；**首次转移幂等**（结算写者对已有合法事件无论 source 均 no-op；「不同 source RAISE」只由守卫对直接 INSERT 旁路执法）；写者恰两个调用点；冲突安全首次写入；投影 `v13_worktree_state` |
| D13 | 接受 | 零 SQL；台账 F23（deviation ledger 编号，≠ parity F23）；关闭 parity §4 #2 |
| D14 | 接受+OID 绑定 | catalog VOLATILE 分支调活体一对谓词，**同一行一次解析出的唯一 OID** 同时传两谓词；RED 基线为硬前置；不建 `v13_volatile_sql_exception(oid)` |
| 第四务 | 修订 | 零新 SQL 动词；分派键 `v13_interruptible(tool_name)`；假 worker gate 只证合同；真接线不进仓库最高 🟡 |

## 2. 探针证据底座（骨架已复核的活体锚点）

- **D11**：活体 `v13_harness_tail_gap(p_sid, p_keep)` 首写 `v13/control/v13_control.sql:196`（RAISE 文本 `:223`），spawn:1101/1321/1393、fanout:584/804/876、triage:666/888/960 只 `PERFORM`，从未换体。续传跳过臂 triage:750-768（`v_cap_new := v13_cap_human_answered(p_sid, v_pred)`）；谓词 triage:525-560（STABLE sql；臂 (a) `interaction_kind∈三 cap 且 human/responded.seq > 前驱 effect_done.seq`；臂 (b) legacy `{reason:repair_cap|replan_cap}` 无 seq 锚）。**活体 advance 先 PERFORM tail_gap（triage:666）后算 cap（:750）——RAISE 先于 cap 判断**。
- **D12**：`state='prepared'` 唯一写入 `v13_bind_worktree_from_prepare`（fanout:146-149）由 advance 调（fanout:512/triage:593）；`'released'` 只在词表 `v13_worktree_latch_ok`（fanout:85）与 test_fanout.py:459,467；`v13_latch_fire` adopt 分支 periphery:283-285（已有值即返回）；latches PK `(session_id,name)` + INSERT-once 触发器 V3008（periphery:20-35）→ UPDATE/二次 INSERT 结构性被拒。**test_fanout.py:459/467 是「直接 fire released 值测 digest 排除」的词表测试（本会话已读原文），词表保留 `released` 即不需改动。**
- **D14**：`v13_tools_catalog_frozen` 在 `v13/resolve/v13_resolve.sql:192`（stage 2 STABLE plpgsql，从未换体）；VOLATILE 拒 :221-225；仅 `kind='sql' AND enabled` 校验（:202）。调用链 `v13_parse`(economy:353) → `v13_judgment_envelope`(filter:485) → catalog(filter:590)。单源一对：`v13_named_sql_writer`(spawn:42-50 IMMUTABLE) + `v13_spawn_writer_ok`(spawn:1657-1680)，guard 调用点 spawn:1636-1639。`v13_volatile_sql_exception`/`v13_sql_write_targets` 全树 0 命中（H7 点名函数未建成——R5 裁：不另造名，复用现成一对）。**stage 18 INSERT 目录行 enabled=true（`v13_spawn.sql:1757-1760`，照 R3c H7）；「enabled=false」是 demo 夹具行为（台账 F22 已记），且 F22 探针的 parse 路径「未到 catalog 即被 GUC 拦，未终验」。**
- **路线图 R5 条目**：children_terminal 求值器 stage 18 已激活（spawn:783，臂 :792-814）；wake 臂在历代 advance 都调过（control:1257-1267 / spawn:1145-1151 / fanout:628-634 / triage:709-716）；recover 已有 children_terminal nudge（V22）。缺口 = 无端到端实证；**生产者只有驱动器**（SQL 不合成 harness 结果，路线图 §3 已裁）。
- **第四务**：`v13_cancel_pending`（fanout:23 STABLE）已 GRANT route/worker（fanout:1027-1053）；`v13_interruptible`（fanout:37-44，只点名 `fanout_required`/`fanout_best_effort`，空名走 ELSE=unsupported）。驱动器续租点 demo_v13/driver.py:288/402/512/546。
- **工程**：`SQL_LOAD_ORDER` 现 20 项止于 triage（load.py:10-33）；stage 骨架惯例 = setup_db.py（DB=`agent_v13_<stage>`、DROP/CREATE、`load_stage(s, DB, "<stage>")`、pg_jsonschema/stannum 探针）+ `test_*.py` 独立脚本（退出码 0=通过，无文件内回归——回归另行全跑）。台账 3 列 `| # | 事实 | 处置 |`，F 编号现至 F22（F21 保留），C 至 C14。

## 3. Stage 21 `v13/seam/`

### 3.1 实施前置（**已执行，见 `v13/seam/preflight.md`**；下列为义务清单与实测结果）

1. `pg_get_functiondef` 取 stage 20 全量加载后的唯一活体：`v13_harness_tail_gap`、`v13_cap_human_answered`、`v13_closeout`、`v13_advance`、`v13_complete`、`v13_resolve_unknown`（每函数只有一份活体）。
2. **证伪停工清单（仅限动摇裁决的不符；下列之外的差异走各节授权分支，不叫证伪）**：`tail_gap` 或 cap 谓词两臂不存在/形状不符；`latch_fire` adopt 分支 + V3008 不再使 released fire 成为静默空操作；catalog 不是这条 VOLATILE 拒绝；`v13_interruptible` 闭集已变。
3. 核查 closeout 严格前置③「续传未还」的实现形状（R5 §1 强制）：调 tail_gap（直接/间接）→ 免改；独立扫描 → 同批换体委托 `v13_tail_gap_cap_exempt`；只查最新 harness → 已放过，禁再放宽。
4. 核查活体 advance 的 tail_gap `PERFORM` 位置 vs cap 决定/入队插入的先后（R5 §1 调用顺序义务）：若铸新格在盖章行插入前把被取代链算进 gap，本次换体把**那一次** `PERFORM` 移到 cap 决定之后、入队插入之后、返回之前。墙分支/ready-claimed 提前返回/cancel 相/step 0 的 R3b 顺序禁止重排。
5. **D12 开工前置（R5 风险 11）**：换体 `v13_complete` 之前，stage 17–20 全部 gate 先实跑全绿。
6. 安装前历史断言（见 §3.2 第 1 步 DO 块规格）。
7. **D11 括号证据探针（已执行）**：实测两臂 `turn/route` payload 键集均恰 `{action,reason,tool,params}`，new 臂 ltid 在 L406 才生成——指向字段不存在且物理不可能。触发 R6；**R6 裁定删除无事件盖章分支，不停工、不补键、不改语句序**。三禁（行数计数/未证得 payload 过滤/时间戳·UUID·xmin·快照可见性）继续有效，对象改为「不得用它们复活无事件分支」。

### 3.2 文件与 SQL 语句序

```
v13/seam/v13_seam.sql（单文件，loader 事务内执行，按序）:
 1. DO 安装前断言（两部分，建索引/守卫之前）：
    a. 既有 worktree latch 行 value->>'state'='released'：仅当该 binding 已存在完全符合
       §3.5 守卫全部不变量的 worktree/released 事件时放行（投影保持 released）；
       仅有 succeeded release effect 而无事件 → RAISE 中止并列出 session/binding
       （R5 禁回填；放行即成「静默降回 prepared」）。
    b. 追溯校验全部既有 type='worktree/released' 事件（开放事件名，stage 21 前可能已有手工行）：
       键集恰两键、schema_version JSON 数字 1、binding 非 NULL 且 canonical、source 同 session
       且 succeeded 的 worktree_release tool effect、payload binding == source 冻结 request binding
       == latch binding、(session_id,binding) 无重复；任一不符 RAISE 列出 session/binding/source。
    两条都不回填、不修史。
 2. CREATE FUNCTION v13_cap_answer_anchor(p_sid uuid, p_effect uuid)
    RETURNS TABLE(anchor_seq bigint, cap_class text) STABLE
 3. CREATE OR REPLACE v13_cap_human_answered（委托 anchor；签名/波动性/ACL 不变）
 4. CREATE FUNCTION v13_tail_gap_cap_exempt(p_sid uuid, p_effect uuid) RETURNS boolean STABLE
 5. CREATE OR REPLACE v13_harness_tail_gap（活体底稿；原 EXISTS 逐字节保留 + AND NOT 豁免）
 6. ~~closeout 换体~~：preflight 判 (C)（只查 predecessor、不调 tail_gap）→ **零改动**
 7. ~~advance 换体~~：preflight 证 `p_keep` 已排除被取代链（PERFORM 搬移不需要）且 wake 求值器已接 → **零改动**（仅当施工中发现其他核查项不符才回到本步）
 8. CREATE FUNCTION v13_record_worktree_released(p_sid uuid, p_effect uuid)  -- VOLATILE
 9. CREATE UNIQUE INDEX ux_events_worktree_released ON events(session_id,
    (payload->>'binding_artifact_id')) WHERE type='worktree/released'
    （索引表达式与守卫用同一套 canonical binding 文本）
10. CREATE FUNCTION v13_seam_event_guard() + CREATE TRIGGER（独立 BEFORE INSERT 守卫，沿 spawn 先例；
    不改 stage 17 守卫；含「NEW.source ≠ 既有行 source → RAISE v13: worktree released」；
    **R7：全程无锁**——全部校验普通 MVCC 读，不锁 latch/事件行、不取咨询锁）
11. CREATE FUNCTION v13_worktree_state(p_sid uuid) RETURNS text STABLE
12. CREATE OR REPLACE v13_complete（活体底稿 + release succeeded 分支调用写者；
    写者调用置于会把异常收成 unknown/replay/stale 的 EXCEPTION 处理器之外，或处理器内原样再抛）
13. （直线可加则）CREATE OR REPLACE v13_resolve_unknown（confirmed 分支调用写者，同一异常块义务；
    否则停工条款见 §3.5）
13b.~~条件换体~~：preflight 证 `v13_state_hash` 是排除名单（`worktree/released` 自动折入）→ **不触发**
14. GRANT 闭包（见 §3.7 末）
```

`v13/seam/setup_db.py`：DB=`agent_v13_seam`，DROP/CREATE，`load_stage` 至 seam，pg_jsonschema/stannum 探针（照 stage 20 惯例）。`v13/seam/test_seam.py` + `README.md`。

### 3.3 D11 — 函数规格

**`v13_cap_answer_anchor(p_sid, p_effect) RETURNS TABLE(anchor_seq bigint, cap_class text)`**，STABLE：
- cap 字面量（`repair_cap`/`replan_cap`/`material_cap`）只住此函数，**从 stage 20 活体 `v13_cap_human_answered` 原样抄出**（禁止凭记忆重打；gate 断言全树只此一处字面量）。
- 两臂都要求：定位 `status='succeeded'` 的 human effect；`session_id=p_sid`；`origin_user_seq` = `p_effect.origin_user_seq`；anchor 严格 > `p_effect` 的 `effect_done.seq`。
  - 臂 (a)：`interaction_kind ∈ 三 cap` 且存在 `human/responded`（source=该 human）→ anchor = `human/responded.seq`。
  - 臂 (b)：legacy request `{reason: repair_cap|replan_cap}`（无 interaction_ref）→ anchor = 该 human 自身 `effect_done.seq`（R3b：此类不写 human/responded；**这是活体主路径，改读 responded 会把铸新回合静默取消**）。
- 返回：每个满足的 cap_class 至多一行（该类最早合法 anchor）；`cap_class ∈ {repair, replan, material}`；无满足零行。**类内最早 anchor_seq 并列两行 → 该类零行（无豁免），禁 `DISTINCT ON` 任取；歧义不 RAISE（保持 tail_gap 原文案）。**

**`v13_tail_gap_cap_exempt(p_sid, p_effect) → boolean`**，STABLE，五条件同时成立才真（相邻性与盖章都**相对与候选信号匹配的那一行 anchor**，不是任意类最早；匹配到多类时任一匹配类满足即整条豁免；`material` 行不参与）：
1. 候选 `result_kind='progress'`；wait 链恒不豁免（写进谓词体，不进注释）。
2. anchor 有行且 cap_class 与候选信号对应：`repair`↔`repair/required`、`replan`↔`replan/required`（双信号匹配其一即豁免整条 index+1 义务）；`material` 恒不豁免。
3. 相邻性：`session_id=p_sid` 且同 `origin_user_seq` 内，不存在另一条 succeeded harness 的 `effect_done.seq` 严格落在 `(候选.effect_done, 该 anchor_seq)` 开区间。
4. 新回合已盖章（不必 succeeded），相对同一行匹配类 anchor（R6 条文）：同 session、同 `origin_user_seq` 存在 harness effect `n`（判定与 `v13_harness_tail_gap` 相同），`continuation_index=0`、`logical_turn_id` ≠ 候选，且存在事件 `ev`：`ev.session_id = n.session_id AND ev.source_effect_id = n.effect_id AND ev.seq > 该 anchor_seq`。`n.status` 不过滤（ready/claimed/succeeded/failed/cancelled/unknown 一视同仁，但 ready/claimed 行通常无自身事件）。**无自身事件的行永不充当盖章证明**——单凭行可见、插入晚于 anchor、行数、`created_at`、UUID、xmin、route `reason` 或无归属的 `turn/route` 均不计（现有 turn/route 的 `source_effect_id IS NULL`，不属于任何行的自身事件）。至少一行满足即盖章（不是恰一行）。事件类型不设白名单。禁止行数计数、payload 过滤、reason 区分、时间戳/UUID/xmin/快照可见性（对象=不得复活无事件分支）。不得改回「必须 succeeded」。
5. 原 tail-gap 条件仍证明旧链无 index+1 后继（调用点语义，不重复）。

**所有候选/anchor/盖章扫描一律 `session_id=p_sid AND origin_user_seq=...` 双下界**（防跨 session 同序号干扰）。

**换体 `v13_harness_tail_gap`**：原 EXISTS 子查询逐字节保留；diff 只许出现 `AND NOT v13_tail_gap_cap_exempt(v_sid, <候选>)`；签名/返回/`PERFORM` 调用参数不动。

**换体 `v13_cap_human_answered`（D11b）**：函数体 ≡ `EXISTS (SELECT 1 FROM v13_cap_answer_anchor(p_sid, p_effect))`；签名、STABLE、**原 ACL** 不变（`CREATE OR REPLACE` 不清权限，禁 `REVOKE ALL`）。行为收紧显式进 gate：乱序 legacy human（effect_done.seq ≤ 前驱）与**跨 user turn** legacy human（seq 更晚但 `origin_user_seq` 不同）都不跳过续传、不豁免、走 index+1。

### 3.4 D11 — closeout ③ 同源

按 §3.1.3 核查结果三选一，**豁免逻辑全树至多一个函数体**（`v13_tail_gap_cap_exempt`）。**preflight 实测判 (C)**：只查 predecessor 一行（`v13_harness_predecessor` LIMIT 1）、不调 tail_gap → **closeout 零改动**；窗口内 `continuation owed` 照报是 R6 接受的 fail-loud（见 §3.7 G10）。计数前置、保险带、④ 逃生前置、state_hash 算法一字不动。

### 3.5 D12 — `worktree/released` 事件

**合同。** latch 行永久表达 binding/prepared 事实（不 UPDATE、不插第二行、不再 fire released）；首次成功 release 写开放事件 `worktree/released`；STABLE `v13_worktree_state` 折叠出 released。成功 release 后 latch 行仍 `prepared` 是 R5 预期。

**写者 `v13_record_worktree_released(p_sid, p_effect)`**（VOLATILE），路径真值表（按序判定；稳定子串不进结算写者）：

| 前置 | 动作 |
|---|---|
| 资格不满足：非本会话 / `kind≠tool` / 工具名≠`worktree_release` / `status≠succeeded` / 冻结 request 的 `binding_artifact_id` 与该会话 worktree latch binding 不逐字节相等（**对照 latch，不对照将写载荷**） | 空操作返回，不 RAISE |
| 资格满足，且该 binding 已存在合法 `worktree/released` 事件（**source 相同或不同**） | 空操作返回——首次转移幂等；第二次独立成功 release 照常 succeeded 结算、写 effect_done/tool/result、零新事件 |
| 资格满足，尚无该 binding 事件 | **latch 行锁内重查后 INSERT（R7 两条语句规则）**：语句 1 = `SELECT ... FROM latches WHERE session_id=p_sid AND name='worktree' FOR UPDATE`（资格已保证该行存在；在调用点已持锁之后执行）；语句 2 = **新语句**重查该 binding 事件，已有（source 任意）→ 空操作，仍无 → INSERT 恰一条。**禁止把事件读取并进语句 1（JOIN/CTE）**——READ COMMITTED 下事件侧停在语句起始快照，等锁醒来看不见对方已提交事件，法定日程反被打成 23505。**禁 `ON CONFLICT DO NOTHING`**；禁锁不存在的事件行；禁在写者内捕获吞掉 `v13: worktree released`；`23505` 与该子串都不得进会收成 unknown/replay/stale 的 EXCEPTION（preflight：两调用点无 EXCEPTION 块天然成立；禁为此补捕获/重试） |

payload 闭集恰 `{schema_version:1, binding_artifact_id}`；`source_effect_id` = 该 effect。

**「不同 source → RAISE `v13: worktree released`」只由守卫对直接 INSERT 旁路执法**（见下），结算写者永不 RAISE 该子串；唯一索引为最后带层。

**调用点恰两个**：
1. 换体 `v13_complete`：release succeeded 分支，位于 replay/stale 提前返回**之后**、status 写成 succeeded **之后**、函数返回之前。failed/unknown/cancelled 不调。
2. 换体 `v13_resolve_unknown`：confirmed 把 effect 写成 succeeded 之后对 `worktree_release` 直线调用一次。rolled_back/not_happened 不调；C1 清墙、resolution 闭集、其它写集不动。**若无法直线加上、必须重排 resolve 控制流 → 停工**，把「confirmed 的 release 投影仍为 prepared」写入 Phase A 台账，gate 对应断言改记台账不假绿。

**异常块义务（两调用点同）**：先读活体 `v13_complete`/`v13_resolve_unknown` 的 `EXCEPTION` 块；写者调用及其守卫 RAISE 必须位于会把异常收成 `unknown`/`replay`/`stale` 的处理器**之外**，或在处理器内把 `v13: worktree released` 原样再抛（收进 unknown 会把坏释放/唯一冲突做成新墙）。

**守卫 `v13_seam_event_guard`**（独立 BEFORE INSERT 触发器，WHEN 限 `type='worktree/released'`，只 RAISE 不改行；**R7：全程无锁**——不取任何 `FOR UPDATE`/`FOR SHARE`/`FOR NO KEY UPDATE`/`FOR KEY SHARE`、不 `LOCK TABLE`、不取 `pg_advisory_*`、不用 NOWAIT/SKIP LOCKED，不调会锁该 latch 的函数；R5 锁序停工句由 R7 关闭，不得把锁加回）：payload 键集恰两键；`schema_version` JSON 数字 1；binding canonical uuid；source 非空、同 session、是 succeeded 的 `worktree_release` tool effect；payload binding 从 source **冻结 request** 复制（不读 worker result）且与 worktree latch binding 逐字相同（latch INSERT-once 使 binding 不可变，无锁读无陈旧）；**同 binding 已有事件且 `NEW.source_effect_id` ≠ 既有行 source → RAISE `v13: worktree released` 零写**。违者零事件。串行旁路得具名 RAISE；并发旁路/旁路×写者由部分唯一索引以 23505 拒绝（最后带层，见 F25）。

**部分唯一索引** `(session_id, (payload->>'binding_artifact_id')) WHERE type='worktree/released'`（表达式与守卫同一套 canonical binding 文本）。

**投影 `v13_worktree_state(p_sid) → text`** STABLE：无 latch 行 → NULL（孤立事件也是 NULL）；有 latch 无 binding 相等事件 → `prepared`；有匹配事件 → `released`；结构性歧义 → RAISE 不按 recency 猜。latch 行 `state` 字段不参与投影。

**边界**：claim/digest/fork 零改动；released 本期不被 claim 消费（「released 后禁 claim」另裁不得顺手加）；无 binding 仍拒 claim；`v13_worktree_latch_ok` 词表保留 `released`；`worktree/released` 进既有 state_hash 事件段不设排除（若活体是白名单 → §3.2 第 13b 步换体）；stage 19/20 测试文件字节不动（test_fanout.py:459/467 为词表+digest 测试，不需改）；全树生产 SQL 禁读 `latches.value->>'state'='released'` 作状态判断（gate grep 断言）。

### 3.6 路线图 R5 条目 — children_terminal 端到端（gate 主导，SQL 仅在核查不过时换体）

只读全量加载后**那一份**活体 `pg_get_functiondef(v13_advance)`（wake 臂「四处行号」是历代文件；活体只有一份）。**preflight 实测：求值器已接（wait/evidence|quota 臂调 `v13_wake_is_satisfied_v1`）且 PERFORM 搬移不需要（`p_keep` 已排除被取代链）→ 本项零 SQL**；触发 §3.2 第 7 步的条件是「被取代链实际被算进 gap」（§3.1.4 原文），不是「调用物理在插入前」。**禁止改四个源文件、禁止把四代函数体并成一份。**

```
场景（fake，不调真实 provider；夹具不得遗留未还的 progress+signals 断链——
wait 链恒不豁免，tail_gap 会先于 wake 臂 RAISE，e2e 会红在错误的层）：
驱动器(测试)对 harness effect 交 p_result = {result_kind:'wait', wait_reason:'evidence',
  wake:{kind:'children_terminal', child_session_ids:[c1,...]}} → complete succeeded
→ advance：求值器判未满足 → 停泊 waiting、零新 effect
→ 直接子 c1..cN 全部 closeout 终态
→ v13_recover_idle：children_terminal 指纹 nudge（既有 V22）
→ 再 advance：恰一条 wake/satisfied（部分唯一索引保证）→ 同 logical_turn_id 续传 index+1
负例：非直接子 → 求值器 RAISE（R3a §6.2 已裁，必须进 gate）；
      缺失 id/重复 id → 只断言活体已有行为；活体不 RAISE 则记事实入台账，本 stage 不改求值器
```

### 3.7 GRANT 闭包与 Stage 21 gate

**GRANT 闭包**：
- `v13_cap_answer_anchor` / `v13_tail_gap_cap_exempt`：与活体 tail_gap 同 security/search_path；`REVOKE PUBLIC` 后只 GRANT `v13_route`。
- `v13_cap_human_answered` 是换体：保持原 ACL，禁 `REVOKE ALL`。
- `v13_record_worktree_released`：以 preflight §7.2 活体 ACL 为准——`v13_complete`/`v13_resolve_unknown` 均 INVOKER，EXECUTE 只在 `{postgres, v13_route, v13_spawn_owner}`（`v13_worker`/`v13_resolve` 为假，rolinherit=false）→ 新写者授给 `v13_route`（+`v13_spawn_owner` 若其调用链到达）；**禁授 `v13_worker`/`v13_resolve`/PUBLIC（那是对活体闭包的放宽）**；gate 加 `has_function_privilege` 断言（写者对 route 真、对 worker/resolve/public 假）。
- `v13_worktree_state`：只 GRANT `v13_route`；本 stage 不授 `v13_worker`（claim 路径不读它）。

**gate**（`uv run python v13/seam/test_seam.py`，退出码 0）：

*D11 组*（R5 §1 全文 + 审核轮增补）：
- 已答且序正确 repair_cap 四连：铸新格不 RAISE / 新 uuid+index 0 / 新回合 finish 后 advance 不 RAISE / `closeout completed` 成功。
- 未答真断链仍 RAISE 原文案；更早独立断链仍 RAISE；另有未还 wait 仍 RAISE。
- `replan_cap` 不豁免只有 `repair/required` 的链；`material_cap` 不豁免。
- **按类最早锁死**：同 origin 内较早 `material_cap`、较晚合法 `repair_cap`、候选带 `repair/required` → 选 repair 类 anchor 并豁免（防全局 `ORDER BY LIMIT 1` 假绿）。
- **臂 (a)（human/responded）与臂 (b)（legacy {reason}）各一正例**。
- **同类最早 anchor 并列** → 该类零行、无豁免、仍 RAISE。
- 双信号+其一 cap 作答不 RAISE；新回合 failed 后走既有重试非 tail gap。
- cap 已答但新回合未铸成（铸新前崩溃）：**两层断言**——谓词级 `v13_tail_gap_cap_exempt = false`；advance 层记名实测（被取代链此时是 predecessor/`p_keep`，tail_gap 不报，fail-loud 落在 closeout `v13: closeout continuation owed`；若夹具坚持断 tail_gap 文案，须另造非 predecessor 候选=「更早独立断链」既有夹具）；再 advance 恰铸一条 index-0；**同 origin、cap 已答，但 anchor 之前已存在另一 logical_turn_id 的无事件 ready/claimed index-0 且本次未铸新行 → 仍 RAISE**。
- 新 index-0 属后续 user turn 不豁免；**跨 user turn legacy human（seq 更晚但 origin_user_seq 不同）→ 不跳过、不豁免、写 index+1**（与乱序例并列双断言）。
- 新 harness 是同 logical turn index+1 走原后继规则；两条独立 gap 只豁免被取代那条。
- **R6 盖章/窗口组**（替换原「无事件盖章五夹具」，全部相对匹配类 anchor）：
  - **W1 主路径自愈**：cap 已答→advance 铸新 index-0（新 uuid/idx 0）→生产 claim/complete 落自身 effect_done（`seq>anchor`）→再 advance 不 RAISE + 谓词直调 true + `closeout completed` 成功。
  - **G2**：finish 的 effect_done 与 failed 结局各一正例（豁免真、advance 不 RAISE）。
  - **G3 failed 重试边界**：failed index-0 有自身事件 `seq>anchor`、旧链无 index+1 → 豁免真，下一次 advance 走既有失败重试臂不 RAISE tail gap；**活体若对 failed 结局不写自身事件 → 本条停工记台账，禁为盖章改 complete 写集**。
  - **G4**：anchor 前无事件 index-0（无 post-anchor 自身事件）→ 谓词 false；p_keep≠该链时 RAISE 原文案。
  - **G5**：anchor 后有正常 turn/route（source NULL，含 `harness_continuation`/`side_effect_tool` 两 reason）但行无自身事件 → false。
  - **G6**：旧无事件行仍在 + 新行有自身事件 `seq>anchor` → 豁免（不得因两行失败）。
  - **G7**：两条 post-anchor index-0 都无自身事件 → false 仍 RAISE。
  - **G8**：自身事件 `seq <= anchor` → false；他行事件、source NULL 事件不计。
  - **G9 未铸成**：无任何 index-0 → 谓词 false；`tail_gap(p_keep=断链)` 不因本链 RAISE、`tail_gap(p_keep=旁观者)` RAISE 原文案；再 advance 恰铸一条 index-0。
  - **G10 残留窗口硬断言**：cap 已答 + 新 index-0 ready/claimed 零自身事件 → 谓词 false；`tail_gap(p_keep=旧链)` 不因本链 RAISE、旁观者 RAISE；非逃逸 closeout RAISE `v13: closeout continuation owed`；重泵 advance 实测分支**记名写死**（(a) RAISE 零新行 / (b) 返回零新行 / (c) 再铸 index-0，三支据实固定，禁写成永久宽松断言；均附零写断言：零新 effect/零新 event/status·fence·request/session 不变；(c) 记台账，不加幂等守卫不重排）。
  - **G11 自愈**：G10 库上 complete 该 index-0 为 finish → 豁免真、advance 不 RAISE、`closeout completed` 成功。
  - **G12 worker 推进独立性**：窗口 RAISE/返回后，ready/claimed 行仍可被 worker 正常 claim/complete，不依赖新的 advance 成功。
- **跨会话诱饵**：会话 A 留未偿 gap；会话 B 同 `origin_user_seq` 具备合法 cap anchor 与 anchor 后 index-0 盖章 → A 的 `v13_cap_human_answered` 为假、tail-gap 仍按原文案 RAISE，B 的事实不影响 A（同时覆盖 anchor 与盖章两扫描面）。
- 源码断言：cap 字面量全树只出现在 `v13_cap_answer_anchor`（`pg_get_functiondef` 抓取，不只查旧函数）。

*D12 组*：
- prepare 仍写 `prepared` 且投影 `prepared`；release succeeded 恰一条事件、投影 `released`、latch 仍 `prepared`；失败与 unknown 零事件投影 `prepared`。
- 第二次 complete 为 `replay`、事件数仍 1。
- **「第二个 source 直接 INSERT」（绕过写者）** → RAISE 含 `v13: worktree released`、事件数仍 1。
- **「第二次独立成功 release」**（新 effect 走 `v13_complete`）→ 返回 succeeded、事件数仍 1、投影保持 `released`。
- **并发 gate（R7 日程）**：连接 A `BEGIN` 后**只**对 `latches(session,'worktree')` 执行 `FOR UPDATE` 并持有（**不锁 sessions 行**，否则 B 停在会话锁上）；连接 B 对另一条合格 `worktree_release` 调 `v13_complete`——A 提交前 B 必须停在该 tuple 锁上（`pg_locks` 对 A 的 transactionid ShareLock granted=false），不得先返回；A 在已持行锁内直接 INSERT 一条符合守卫全部不变量的 `worktree/released`（source=另一条已成功 effect；守卫无锁校验不重锁，**此 INSERT 必须成功不得 40P01**）；A `COMMIT`；B 获锁后以**新语句**重查、见事件、空操作、返 `succeeded`；事件仍 1 行、零 `v13: worktree released`、零 23505、零 40P01；第三条合格 effect 再调一次 complete 仍 succeeded 事件仍 1。`lock_timeout` 只判等待失败；禁「锁外先查无事件再让对方插入」当通过条件、禁生产函数暂停点。
- **异常块结构断言**（两函数都查；resolve 若已走 §3.5 停工则跳过该函数）：`pg_get_functiondef` 里 `v13_record_worktree_released` 的调用不在把 `23505` 或消息 `v13: worktree released` 收成 `unknown`/`replay`/`stale` 的 `EXCEPTION` 分支中；语法上必须留在块内时，该分支须有对该子串的 `RAISE` 再抛。直接 INSERT 负例不代替本条。
- **源码断言（R7 锁协议）**：守卫函数体不出现 `FOR UPDATE`/`FOR SHARE`/`FOR NO KEY UPDATE`/`FOR KEY SHARE`/`LOCK TABLE`/`pg_advisory_`/`NOWAIT`/`SKIP LOCKED`；写者函数体出现对 `latches` 的 `FOR UPDATE`，不出现 `pg_advisory_`/`ON CONFLICT`，且事件重查不在含 `FOR UPDATE` 的同一条语句内。
- **守卫负例组**（直接 INSERT 逐项，每例稳定 RAISE 且事件数不变）：缺键/多键；`schema_version` 为字符串 `"1"`；非 canonical uuid；source 空/跨 session/非 succeeded/非 tool/非 `worktree_release`；payload binding ≠ source 冻结 request；request binding ≠ latch binding。
- **孤立事件不使无 latch 会话变 released**（投影 NULL）。
- confirmed 的 release 投影变 `released`（停工条款触发则改记台账）；`not_happened` 保持 `prepared`；子会话不继承该事件。
- 投影 released 时 claim 结果与只有 prepared latch 的既有结果相同。
- **迁移 gate**（stage 20 基库加载 seam）：历史 released latch 无合法事件 → 安装失败报 session/binding；历史 malformed 同型事件 → 安装失败；已有合法匹配事件 → 安装成功且投影仍 released。
- **state_hash 运行时断言（方向必须正确）**：固定其余账本，记 `h_before` → 写入唯一合法 `worktree/released` → 断言 `h_after <> h_before`（类型被折进 hash 才对；写成「前后一致」会把排除名单测绿）；同一账本快照重复调用 `v13_state_hash` 稳定且与 closeout 存储值一致；重算不因未知类型 RAISE。

**源码断言组**：`v13/seam/*.sql` 无 UPDATE latches、无第二行 INSERT、无生产路径读 latch state 作判断；**`v13_tail_gap_cap_exempt` 盖章扫描只查 `source_effect_id = n.effect_id` 与 `ev.seq > anchor_seq`，函数体不出现 payload 取键（`->>'effect_id'`/`->>'logical_turn_id'`/`harness_effect_id`）、无事件行计数、reason 区分**（R6）。

*回归*：stage 1–20 全部 gate 重跑全绿（含 §3.1.5 的开工前置绿）。

### 3.8 Stage 21 收尾工件（缺一不可，然后才 commit）

`SQL_LOAD_ORDER` 追加 seam；覆盖矩阵加 Phase A 段（stage 21 行）；偏差台账 Phase A 段：**F23**（D13）+ **F24**（R6：D11 无事件窗口窄化，≠ parity F24）+ **F25**（R7：D12 锁协议死锁复裁——守卫无锁、写者两条语句规则、23505 残留接受，≠ parity F25）+ D12 预期行为行（「成功 release 后 latch 行仍 prepared 是 R5 预期；released 不被 claim 消费」）+ 若触发 §3.5 停工条款的 confirmed-release 台账行 + §3.6 缺失/重复 id 的事实行（如活体不 RAISE）+ G10(c) 分支若发生的记录行；`v13/seam/README.md`（机制映射 + gate 清单）；parity 裁决文档 §4 #2 行状态改「R5 已裁：不移植」、§6 建议第 3 项标注已裁。

## 4. Stage 22 `v13/catalog/`

### 4.1 RED 基线（硬前置，写任何换体 SQL 之前）

`test_catalog.py` 自建两个库：`agent_v13_catalog_base`（加载至 stage 21）跑基线探针；`agent_v13_catalog`（加载至 stage 22）跑换体后 gate。

| # | 探针（base 库，非超级用户） | 预期 | 不符时 |
|---|---|---|---|
| P1 | `SET ROLE v13_route; SELECT v13_tools_catalog_frozen()` | RAISE 命中 `spawn_subsession` 的 `is VOLATILE` | GREEN → 停 stage 22 查活体；42501/handler 不可解析/revision·digest/schema-qual 错 → 停（不是预期 RED） |
| P2 | 真实 `v13_parse` 路径一次（**须构造真正到达 catalog 的场景**：F22 探针曾「未到 catalog 即被 GUC 拦，未终验」） | 同上 RED | 不可达 catalog → 停工报事实（缝可能仅存于夹具层，D14 的 parse 可见性目标需复访） |
| P3 | `pg_get_functiondef(v13_needed_judgments)` 含 `v13_is_spawn_tool` | 含 | 不含 → 停工（candidate_set_hash 另一裁） |
| P4 | **先按 §4.2 补两谓词 GRANT**（base 库 42501 是缺 EXECUTE，不是谓词分叉），再比 `v13_spawn_writer_ok` 在 `SET ROLE v13_route` 与 `v13_resolve` 下返回值 | 同值 | 返回值因 `current_user` 分叉 → 停工，禁写更松副本 |
| P5 | `v13_named_sql_writer` IMMUTABLE；`v13_spawn_writer_ok` 无写副作用可被 STABLE 调用 | 是 | 否 → 停工 |
| P6 | tools 行 `spawn_subsession` 活体 enabled 状态（stage 前缀库） | =true（stage 18 INSERT `v13_spawn.sql:1757-1760` 照 R3c H7；「enabled=false」是 demo 夹具行为，F22 已记） | =false → 先与台账 F22 对账，禁 `UPDATE tools` |
| P7 | 记录两谓词活体 identity arguments 与返回类型（`pg_get_function_identity_arguments`；现均为 `(text)`，spawn:1751-1752 GRANT 行佐证） | 记录在案 | 签名非预期/无法记录 → 停工（不改签名、禁 overload） |

### 4.2 D14 换体公式

`CREATE OR REPLACE v13_tools_catalog_frozen`（活体底稿，仅 VOLATILE 分支改动）：

```
kind='sql' AND enabled AND provolatile='v' 的行：
  1. 按 catalog 既有规则把 handler 解析到唯一 OID/regprocedure（歧义 fail-closed）
  2. v13_named_sql_writer(handler) 非 NULL
  3. v13_spawn_writer_ok(同一已解析 OID 及元数据) 为真
  → 三者同时成立才跳过这一条通用 VOLATILE RAISE（子串 is VOLATILE 逐字节不变）
豁免后：schema-qualify、签名、handler_digest、frozen 一致性、ACL/search_path 照旧全跑
数据流约束（按活体 (text) 签名落成可执行式，禁改签名/禁 overload/禁在 catalog_frozen 写函数名字面量）：
  v_handler := 该 catalog 行 handler 文本；
  v_oid := catalog 既有规则唯一解析（歧义 fail-closed）；
  v_qual := 只由该 OID 现拼：quote_ident(nspname)||'.'||quote_ident(proname)||'('||
            pg_get_function_identity_arguments(v_oid)||')'（反查 pg_proc/pg_namespace；
            示例签名不是源码，禁止把函数名/参数类型字面量写进 v13_tools_catalog_frozen）；
  断言 A（跳过 RAISE 之前）：to_regprocedure(v_qual) = v_oid 且 v13_named_sql_writer(v_handler)
            非 NULL——闭集判定只有这一次 named_sql_writer 调用，无 proname 比对；
  断言 B（同前）：读活体 v13_spawn_writer_ok，写出它对入参文本做的解析表达式；
            入参为 v_qual 时该表达式的结果必须是 v_oid。函数体做不到（剥 schema、
            只比裸名、再按 search_path 解析）→ 停工（禁改 writer_ok 解析、禁剥限定名、
            禁在 catalog 里另写一份校验）；
  两断言都在「跳过这条 VOLATILE RAISE」的判定之前求值，任一失败 fail-closed；
  shadow 反例（§4.4）必须在这条绑定链上失败；豁免被劫持 = §5.6「OID 绑定无法闭合」
  停工，不是调 search_path。
禁止：文本名先行放行再二次 search-path 解析；仅 named_sql_writer 非 NULL 即放行；
      捕获 writer_ok 异常当可继续；名单外任何新字面量
```

GRANT：`v13_named_sql_writer`/`v13_spawn_writer_ok` 幂等 `REVOKE PUBLIC` → GRANT `v13_recall`/`v13_resolve`/`v13_route`；不授 `v13_worker`（除非调用链证明）。不建 `v13_volatile_sql_exception(oid)`；不换 guard；不动 tools 行。

### 4.3 第四务合同（gate 证明，零 SQL 动词）

假 worker 只调：claim →（事务外 fake IO，**带调用计数器**）→ `v13_renew_lease` → `v13_cancel_pending` → `v13_interruptible` → `v13_complete`。分派表（R5 §5）：

| `v13_interruptible(tool_name)` | kind | 动作 |
|---|---|---|
| `unsupported`（含空/NULL tool_name 的 routed llm） | 任意 | 不动；允许随后正常 `complete(succeeded)`；粘性 cancel 归 advance |
| `best_effort` | 任意（含 tool） | `complete(cancelled)` → 立即返回 |
| `required` | `llm` | `complete(cancelled)` → 立即返回 |
| `required` | `tool` | `complete(unknown)` → 立即返回（既有抬墙；会话状态按活体抬墙机制落位，先对活体 status 字面） |
| `required` | `judge`/`human`/`context_refresh` | 不动；允许正常结算；禁「保险性 unknown」 |

边界：检查在 renew 成功后、正常 complete 前；命中后**零后续 provider IO**（计数器断言）；第四务 complete 后立即退出禁二次结算；**用本次 renew 后的新 fence**；每次成功 renew 都复查；谓词查询失败 ≠ false（fail-closed 停止本次正常结算）；`complete` 返 `replay`/`stale` → 停止不另造结算。**分派键是 `v13_interruptible(tool_name)` 不是 kind=llm**（R5 风险 8）。跟踪只进 Python 内存或 `pg_temp`。

### 4.4 Stage 22 gate（`uv run python v13/catalog/test_catalog.py`，退出码 0）

*D14 组*：base 库 P1–P7 全部符合预期（预期 RED 断言为「RAISE 且含子串」，不是退出失败）；换体后 enabled 的 `spawn_subsession` 不再因 VOLATILE 失败；临时插名单外 VOLATILE sql 工具行仍因同一子串 RED（测后清理）；`v13_needed_judgments` 工具集仍不含 `spawn_subsession`；sql 快路臂命中该名仍 RAISE `batch-dispatched` 零子；扇出臂仍是唯一产子路径；`SET ROLE v13_route` 与 `v13_resolve` 各跑真实 catalog/parse 绿（超级用户绿不算数）；**`has_function_privilege` 断言**：两谓词对 route/resolve/recall 为真、对 PUBLIC 与 `v13_worker` 为假；**同名不同 schema / search_path shadow 函数反例**（豁免不得被 shadow 劫持）；源码 grep 断言具名名单只住在两谓词函数体。

*第四务组*：renew 失败零 cancel 结算且不读谓词；renew 成功 + pending=false → 正常 succeeded；cancel 在本次 renew 前可见 → 结算为表中 cancelled/unknown 而非 succeeded 且**其后零 provider IO**；cancel 在读后才出现 → 已发生 succeeded 不追溯；best_effort → cancelled（tool 的 best_effort 也是 cancelled 不是 unknown）；required+llm → cancelled；required+tool → `complete(unknown)` 且既有抬墙生效；required+judge/human/context_refresh → 正常结算不 unknown；unsupported + pending → 仍可 succeeded；空 tool_name llm 上 `complete(cancelled)` → 既有 RAISE（负例，假 worker 正路径不得这么调）；第四务 complete 后无第二次正常 complete；**fence 场景**：第四务用 renew 后新 fence，旧 fence 只得 `stale` 且不得随后再结算；**第四务 `complete` 返 `replay` 与 `stale` 各一场景**：立即退出、零第二次 complete；谓词查询失败 fail-closed；两次 renew 场景每次都复查；`v13/catalog/*.sql` 无 LISTEN/NOTIFY、无 `pg_terminate_backend`、无 `v13_worker_fourth_duty` 类判定函数、无永久跟踪关系（源码断言）。

*回归*：stage 1–21 全部 gate 全绿。

### 4.5 demo 证据与验收状态（🟡 纪律）

`demo_v13/driver.py` 四处续租点（288/402/512/546）打第四务补丁——**gitignored，不进里程碑 commit**。Phase A 验收实跑该循环一次、退出码 0（非交互 shell 需 `source ~/.zshrc` 取 STEPFUN key）。验收状态表（R5 §5，codex 案）：

| 证据 | 可声明状态 |
|---|---|
| 只有 SQL 谓词 | 未实现 |
| + test_catalog.py 假 worker 全绿 | 合同已证明，真实接线未交付 |
| + gitignored driver 本机实跑退出码 0 | 环境级验证，最高 **🟡** |
| + 进仓库可部署复现的 worker 接线通过实跑 | 才可 ✅ 关闭 R4 |

**Phase A 目标句不得写「R4 真 worker 第四务已完成」**，除非第四档证据在库。stage 22 README 两格并记（fake gate ✅ / 真实接线 🟡）。

### 4.6 Stage 22 收尾工件

`SQL_LOAD_ORDER` 追加 catalog；覆盖矩阵 Phase A 段（stage 22 行，第四务按上表如实标）；台账 Phase A 段关闭 **F22**（catalog 缝：D14 交付后具名写者对 parse 可见）；`v13/catalog/README.md`（换体公式 + 第四务合同 + 验收两格）。

## 5. 全局红线（每 stage 收尾检查）

1. 零新表零新列（含物化视图/投影表/概念缓存表，R4）；本计划全部交付物 = 函数（STABLE/VOLATILE）+ 开放事件 + 部分索引 + 只 RAISE 守卫触发器。
2. stage 1–20 文件字节冻结；换体只 `CREATE OR REPLACE` 且底稿 = 活体 `pg_get_functiondef`（全树每函数一份活体，禁从历代文件回贴、禁合并四代函数体）；换体前后签名/owner/security/search_path/GRANT 逐项比对；**D12 开工前置：换体 `v13_complete` 前 stage 17–20 gate 先全绿（§3.1.5）**。
3. 外部 IO 不进事务；第四务/harness 结果/worktree FS 全在驱动器；SQL 不杀进程。
4. gate 全绿才 commit：该 stage `uv run python v13/<stage>/test_*.py` 退出码 0 + 回归此前全部 stage。按路径 `git add`；禁 `git add -A`；禁 force-push；禁 `--no-verify`。
5. 每期收尾架构审计（R4）：无概念性控制表/物化投影/影子状态源；新增读面必须是函数；新增写面归入既有事件/策略/具名函数路径。
6. 停工条款汇总（任一触发即停，按 R5–R7 报事实不自行改裁）：§3.1.2 证伪清单命中（preflight 已核 GO）；§3.2.1 安装前断言 RAISE；§3.5 resolve 无法直线加调用（preflight 已核可行）；**R7 已解除守卫锁序停工——再给守卫加 latch 锁或咨询锁 = 越界停工；若残余死锁仍现，附 pg_locks+CONTEXT 复裁**；G3 活体 failed 结局无自身事件；§4.1 P1–P7 任一不符；§4.2 OID 绑定后置断言无法闭合。§3.1.7 的原停工点已由 R6 解除。

## 6. R5 假绿风险对照（实施时逐条自检）

R5 §6 十二条已全部内嵌为上文的硬边界/gate 行：①closeout ③ 同源（§3.1.3/§3.4）；②盖章即可（§3.3 条件 4）；③按类 anchor（§3.3 + §3.7 按类最早 gate）；④双信号匹配其一（§3.3 条件 2）；⑤臂 (b) 用自身 effect_done（§3.3）；⑥complete 插入点在 replay 之后 + 异常块义务（§3.5）；⑦resolve confirmed 调用点（§3.5）；⑧分派键 interruptible(tool_name)（§4.3）；⑨batch-dispatched 锁 sql 快路（§4.4）；⑩投影函数+跟踪 pg_temp（§4.3）；⑪换体底稿纪律 + D12 开工前置 stage 17–20 先绿（§5.2）；⑫文档字面同步（路线图 §2.1 F23/§2.3/§3/§4 D12、本计划、台账、覆盖矩阵——路线图已同日改，含 §2.3 与验收句）。

审核轮增补的承重修正（r2–r5 已并入）与复裁（R6/R7）：……（原文不变）……D12 锁协议（R7）：守卫无锁 MVCC 校验 + 写者两条独立语句规则（防 READ COMMITTED 语句快照 23505）+ 并发日程零 40P01。

## 7. 不做清单（Phase A 范围外，防夹带）

steer 正文、`closeout/inbox_residual`、`quota/spent|voided`、`material_cap` human 生产、G6 新条文、`thresholds.action` ALTER、「released 后禁 claim」、`v13_volatile_sql_exception(oid)` 新谓词、L32 停/复、F8/F17/F18/F29、D7/D10/D15/D16 对应 stage。closeout/advance 的任何非 §3.1.3/§3.1.4 指明的分支改动。

## 8. References

- R5 终裁（含审核轮勘误）：`docs/reviews/v13-control-plane-oracle-r5-2026-09-26.md`（本计划唯一裁决依据）
- 审核轮导出（gitignored）：`prompt-exports/oracle-review-2026-09-26-230451-*.md`（第一轮）、`prompt-exports/oracle-review-2026-09-26-231354-*.md`（第二轮）
- 路线图：`docs/plans/v13-layered-control-roadmap-2026-09-26.md`（§3 Phase A、§4、§5；D12 字面已按 R5 同步含 §2.3）
- R4：`docs/reviews/v13-control-plane-oracle-r4-2026-09-26.md`；R3 链：`docs/reviews/v13-control-plane-oracle-r3-2026-09-26.md`（§6.3/§7.1/§7.2/§8）
- parity 裁决：`docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md` §4 #2/#8/#10、§6 R4/R5/R6
- 台账：`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md`（F13/F21/F22、格式）
- 裁决全文（gitignored）：`prompt-exports/oracle-chat-2026-09-26-220141-new-chat-d34409-db94.md`
