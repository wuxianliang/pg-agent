# v13 Phase B 计划批判（r0 → 送裁前）

> **处置注（2026-09-27，r2 时点）**：本稿是 r0 历史批判，保留原文不回改。处置：①§5「直接修」清单 9 条已全部折入 r1/r2；②§2.7 建议的「未授权+非法游标 → 零行」是**错的**（与游标检查在谓词前的正确顺序矛盾）——正确 gate 见计划 r2 §4.3（未授权与已授权同得 `v13: session log cursor` 逐字同文案），以此为准；③本文「裁决轮名 = R7」已过时——R7/R7b 被 Phase A 会话的 D12 死锁复裁占用，Phase B 动词轮终名 **R8**（`docs/reviews/v13-control-plane-oracle-r8-2026-09-27.md`）；④「preflight 停工态」措辞：R6 已解除 STOP-D11，且 stage 21 已提交（e925ebe）——Phase A 现状是「stage 21 已落、stage 22 catalog 未落」，非 STOP。

身份：correctness & completeness critic，不是共同作者。不重写计划。
对象：`docs/plans/v13-phase-b-workflow-verbs-plan-2026-09-26.md`（r0）对照
`prompt-exports/oracle-plan-2026-09-27-002645-phase-b-workflow-ver-2b64.md` 的三条生成计划
（Oracle 1 grokBuild / Oracle 2 codex / Oracle 3 claude-fable）。组合 prompt 与选区转储不当计划。

不重开（已核对，下文不论证对错）：裁决轮名 = R7（R6 被 `d68f37a` / verdict-R6 占用）；台账从 F25 起（F24 归 R6）；Phase A 的**开工资格**仍是 preflight 停工态，不是「stage 17–20 绿」；用户已拍板的倾向 = 身份去重、极简策略键集、验收天花板 🟡。下面只追这些选择**合并后留下的洞**，不把替代项请回来重裁。

抽查范围（点名接缝，不是全库）：`v13/fanout/v13_fanout.sql` cancel/complete、`v13/control/v13_control.sql` 谓词/hash/守卫/unknown wall、`v13/schema/v13_core.sql` append/policies/角色、`v13/triage/v13_triage.sql` DEFINER 授予、`v13/load.py`、工作区未跟踪的 `v13/seam/v13_seam.sql`、路线图 §3 Phase B / §4 D7·D16、parity F8/F17/F18/F29。

---

## 1. 三通道承重内容：缺失 / 弱化 / 泛化

整合不是空的。探针表、假绿表、Phase A 假设表、文件级影响、身份去重 gate、DEFINER 授予清单、🟡 两格，大体从对应通道活了下来。下面只记**会改变施工或送裁**的丢失。

### Oracle 1（grok）——GUC 施工段没有活下来

计划写「两分支施工段均已写好，裁后机械替换」，§3.2 又写「选 GUC 则按 §1.1 表替换第 4–7 步，其余步骤不变」。这是假的。

grok §3.1 有完整语句序：`v13_control_actor()`（`btrim` + `v13_canonical_uuid`，非法 uuid → `v13: session not found`，不暴露 `invalid input syntax`）、对**旧签名** `CREATE OR REPLACE`、非 human complete **不读** GUC、GRANT 的是 operator/actor/authorized 而不是 2 参/6 参 overload。gate 是 `SET LOCAL` 正例 + 非法 GUC 在非 human 上仍成功。

计划里这些只剩 §1.1 对比格的三行。§3.2 步骤 4–7、步骤 8–9 的 REVOKE/GRANT、§3.4 的「2 参调用 / 6 参正文 / identity arguments」全部是 overload 词汇。选乙之后「其余步骤不变」会去 GRANT 不存在的 overload，gate 也无法机械改写。无预设倾向在正文结构上不成立：甲有施工段，乙没有。

同通道另一处弱化：grok 把 complete 准入钉在「`unknown effect` RAISE **整块之后**、fence/stale/replay **之前**」（活体 `v13/fanout/v13_fanout.sql:324` 与 `:326` 之间）。计划收成「human 块」（§3.2 步 6、§3.4 源码断言）。活体的 human 块在 `:355`，在 stale/replay 返回和 cancelled 分支 `UPDATE`（`:348`）**之后**。按「human 块」插，grok 的插入点就丢了。见 §2.1。

grok §5.4 的策略超限测试要求「两条路径只留一条，不要两种都跳过」。计划 §5.3 收成「唯一 active 不允许就记台账跳过」。见 §3.2。

grok Risks 的探针「advance 对未知 type RAISE 则停」被删。今日不会触发：`v13/loop/advance.sql:126` 只读 `llm/message|tool/result`，`control/handoff` 被滤掉而不是 RAISE。探针本身仍该留在 §2 证伪表，否则以后封闭词表会无声打红 advance。

### Oracle 2（codex）——被采纳的那半规格，替换协议不完整

身份去重、极简 `{schema_version, enabled}`、锁后复验、6 参正文镜像旧 proacl、先授权再读 cutoff、双连接同 snapshot 返回原 payload：这些进了草案，不重议。

没进替代项表、因此 R7 看不见的 codex 合同：

| codex 承重句 | 计划里的下落 |
|---|---|
| 空日志 / 负数 / 指向 handoff → `v13: handoff cutoff`；信封 `up_to_seq` 非负 | 草案改成 ≥ −1 且空会话 NULL→−1 **成功写收据**。不是「否决后的替代项」，是第三种行为。见 §2.3 |
| hash 折叠 `event_id`、`turn_no`（仍排除 `at`） | 草案用 state_hash 事件元组 `(seq, type, payload_hash, source_effect_id)`。fable 倾向同草案。字段集不在替代项表 |
| 守卫接受 D7 控制带、extract 直调 `v13_append_event`、不建 DEFINER | §1.2 替代项只有这一句。裁后「按 §1.2 替换」换不掉函数名、`handoff cutoff` 文案、`up_to_seq>=0`、历史行核对、无 emit |
| 回退顺序 25→24→23；git revert **不**卸载已安装库的函数/触发器/索引 | §5.4 写成「策略行与函数随加载序消失」。只对 `setup_db` DROP/CREATE 为真 |
| Phase A 若已造同名 overload、`control/handoff` 行或新控制角色 → 停并重裁 | 只部分落在 §2 证伪 5/6，§8.3 修订协议没有这条 |
| 全局错误表：handoff 事务取消则 `next_seq` 与事件同回滚 | 计划写了 extract 无 EXCEPTION，没写取消/超时的账本断言 |

codex 5.1「未知 session 的旧 cancel 一律改成 `session not found`」**不该**被整合进来。冻结 needle 是 `v13: unknown session %`（`v13_fanout.sql:161`）。计划保留 operator+缺会话原句，这是对的。

### Oracle 3（fable）——该丢的丢了，有一处列合同被静默换掉

正确替换，不要请回草案：

- 真值表把终态判假：会撞 R3 `replay`。计划已放进 D7-alt-status。
- 自答把 `p_actor` 设成 **该 human effect 的 `session_id`**：actor 恒等于 target，直接父永远过不了谓词。与 F17 相反。
- `v13_session_log` 未授权 RAISE：与「不以异常区分存在性」冲突。计划采用零行，理由在 F27，够用。
- 观察列 `wake_pending`：全树没有这个函数。advance/fanout 用的是 `v13_unconsumed_cancel`（`v13_fanout.sql:522`）。计划的 `cancel_pending` 适配表是对的。

弱化：fable §7.1 A4 点名 stage 21 的 `v13_seam_event_guard` 可能与 handoff 守卫重名/误伤。计划 A6 只写 stage 17 WHEN。工作区 seam 守卫实际是 `WHEN (NEW.type = 'worktree/released')`（`v13/seam/v13_seam.sql:387`），不会误伤 `control/handoff`。A6 的停工句应改成「stage 17 **和** seam 守卫的 WHEN 列表」，否则 seam 落地后探针仍只看 control。

### 假绿 / 探针 / Phase A / 文件影响

- 假绿表从 grok 22 行扩到 24 行，overload 绕过（#2）和 proacl 镜像（#24）是 codex 的，留对了。#20「超限即 RAISE」在极简键集下没有超限。这行现在钉不死任何实现；应改成「消费了 `max_events` / 静默截断 / `allow_empty` 即失败」，而不是保留 grok 的 RAISE 针。
- 探针表（json_int_ok、canonical_uuid、pending 适配、D12 恰一次）基本是 grok 的，且 `v13_json_int_ok` 对负数必假（`v13_control.sql:108-114`，`^[0-9]+$` 且 `BETWEEN 0 AND p_max`）。这行不要删。
- Phase A 协议相对 codex 3.2.2 缺：把 `pg_get_functiondef` 留在仓库外的临时目录（计划只说测试进程）、以及「replay/stale 仍在一切新写者之前」这一条活体形状检查。后者正是 §2.1 要钉的位置。
- 文件影响表在，但 grok 写明 setup_db 抄 triage 的扩展探针与 stannum GRANT。计划 §3.2 有「照 stage 20」，§9 表没有。弱化可接受，只要实施不改成空 setup。

---

## 2. 欠规格、自相矛盾、错引用、缺依赖

### 2.1 complete 准入点与「human 块」互斥，且与 unknown-effect 两句互斥

活体 `v13_complete`（`v13_fanout.sql:305-355`；未跟踪 seam 换体同构，`v13_seam.sql:438-470`）：

1. `:320` 无锁读出 `session_id`（还没有 kind）。
2. `:321-322` 先锁 session 再锁 effect。
3. `:323-325` `v13: unknown effect %`（插值 effect id）。
4. `:326-332` `stale` / `replay` **返回**。
5. `:334-353` `p_status='cancelled'` 分支，`:348` 已 `UPDATE effects` 并写 `effect_done`。
6. `:355` 才是 human 围栏，且仅当 `kind='human' AND succeeded AND request ? 'interaction_ref'`。

计划同时要求：

- 授权在 replay/stale **返回之前**、任何 `UPDATE` 之前；未授权者看不到 stale/replay/C4。
- `kind=human` 的**全部** status 先授权（假绿 #6）。
- actor 非 NULL 且非 human → 统一文案，零写（防 overload 变成通用结算口）。
- §3.4 源码断言：差集只有「human 块+复验段」。

按字面做「human 块」插入，检查落在 `:355`。未授权的 fence 错误仍返回 `stale`（`:326`）；actor 非 NULL 对 tool effect 调 `complete(cancelled)` 会在准入前写完并 `RETURN 'accepted'`。这直接打穿 §1.1 和假绿 #3/#6。

第二对互斥句（§1.1）：

- 「actor 非 NULL 且 effect 不存在 → 统一文案，不泄 `unknown effect`」（codex）。
- 「`unknown effect` 先于授权 RAISE，冻结 needle 不动」（grok）。

同一函数体做不到既先 RAISE 原句、又在 actor 非 NULL 时不 RAISE 原句。6 参正文必须**改** `:323` 那一段，不能只在其后插入。§3.4 的字节差断言与 §1.1 括号句冲突，实施者会二选一且两边都有原文背书。

精确修正（不重写计划，只钉顺序）：

- actor 非 NULL：无锁定位；无行或 kind≠human → `v13: session not found`，零写；不走 `:324` 原句。
- actor NULL 且 kind=human：operator 带失败 → 同一文案；无行仍走 dump 的 `unknown effect`（旧签名 needle）。
- actor NULL 且 kind≠human：不调谓词、不读通道。
- 上述判断必须在 `:326` 之前，因此也在 `:348` 之前。锁已在 `:321` 取得时，这一次检查就是锁后检查；若还要锁前检查，插在 `:320` 与 `:321` 之间，并且复验必须是**下一条** plpgsql 语句，不能并进 `FOR UPDATE` 同一条 SQL（谓词是 STABLE，同一语句内可能被折叠成锁前结果）。
- 源码断言改成「差集 = 锁前定位/准入 + `:323` 的 actor 分支 + 锁后复验」，禁止写「只有 human 块」。

cancel 侧没有这个问题：存在性检查在锁前（`:160`），树锁在 `:204`，tree-changed 在 `:214`。计划的「锁前准入 + 锁后复验」对 cancel 贴得上。不要把 complete 写成同一句「human 块」。

### 2.2 GUC 替换不是机械的，且「只会收窄」不成立

见 §1。另外 §3.3：「连接池用会话级 SET 只会收窄不会放大。」收窄到**上一个请求的 actor** 时，若那个 actor 是下一目标的直接父，cancel/complete 会成功。这是跨请求冒充，不是无害降权。overload 没有这条故障。R7 若选 GUC，裁决正文必须接受它，不能沿用这句当安全论证。

非法 GUC 的 fail-closed 在 §1.1 有一句，但没有 grok 的 `v13_canonical_uuid` 规则。裸 `::uuid` 会抛 `invalid input syntax`，和统一文案不是同一字符串。选乙之前这句必须写进施工段，否则假绿 #7 钉的是另一个错误。

### 2.3 空前缀是第三种设计，且与本草案另一句冲突

用户拍板的是极简键集，不是「空收据合法」。

- grok：有 −1，但种子 `allow_empty=false`，零事件走 `v13: handoff empty`，不写。
- codex：无 −1；空日志 / 负数 / handoff seq → `v13: handoff cutoff`，零写。`up_to_seq` 非负。
- 计划草案：删掉 `allow_empty` 之后仍保留 −1，且 NULL cutoff 在无事件时取 −1 并写收据。同时「空会话传 0 → `v13: handoff watermark`」。

于是同一空会话：不传 cutoff 成功并留下收据，传 0 失败。两条都不是已拍板倾向的推论。信封值域（≥ −1 还是 ≥ 0）要进 R7，不能藏在草案正文里当已决。

### 2.4 身份去重的回读表达式没钉死

用户已选去重。计划写了部分唯一索引表达式，没写 extract 锁内回读必须用**同一套**文本：`payload->>'up_to_seq'`、`payload->>'transcript_hash'`，而不是另一套 `::bigint` 比较或带空格的 canonical。回读错过、索引命中时，无 `ON CONFLICT`、无 EXCEPTION，调用方得到 `23505` 而不是原 payload。§5.3 双连接用例会红，但规格没把 `23505` 定义成「回读写错」而非「可接受的竞态结果」。

`v13_policy()`（`v13_core.sql:731-740`）缺行文案是 `v13: no active policy row for % (seed lost?)`，不是 `v13: handoff policy`。extract 若图省事调用它，gate needle 对不上，还会把策略名泄漏进错误。多条 active 被 `ux_v13_policies_one_active`（`:708`）挡住，§1.2 的「多条 active → handoff policy」在索引建好后不可达。不要用 `v13_policy()` 当 handoff 的错误边界。

### 2.5 DEFINER 属主缺 `SELECT ON events`

`v13_append_event`（`v13_core.sql:70-84`）的 `UPDATE` **总是**给 `status` 赋值。`trg_sessions_unknown_wall` 是 `UPDATE OF status`（`v13_control.sql:613-616`），因此每条 `control/handoff` 都会点火，即使 CASE 没改变状态字。壁函数读 `effects`。计划照 triage 授了 `v13_assert_unknown_wall` 与 `SELECT effects`，这半边是对的。

守卫与 `v13_transcript_hash` 在 DEFINER emit 期间的 `current_user` 是 `v13_handoff_owner`（守卫必须 INVOKER，这点计划写对了）。hash 和 watermark 检查要 `SELECT events`。§1.2 授予清单没有这条。安装后 DO 只查 wall 与 effects。`SET ROLE v13_route` 真 COMMIT 会在这里 42501——gate 能抓，但规格应把授予写上，而不是等红了再补。

codex 带案不建属主，route 已有 `events` SELECT，这条依赖消失。所以「换带案」不是只删 DEFINER，还要删掉一套属主 GRANT、改守卫的 `current_user` 检查。§1.2 那一行替代项不够替换。

### 2.6 `pg_roles.rolsuper(current_user)` 不是 SQL

§1.1 草案把 operator 写成 `pg_roles.rolsuper(current_user)`。`rolsuper` 是 `pg_roles` 的列，不是函数。照抄不能创建。修正：

```sql
EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper)
OR pg_has_role(current_user, 'v13_route', 'USAGE')
```

`USAGE` 而非 `MEMBER` 与今日角色事实一致：`v13_worker` 是 `LOGIN NOINHERIT` 且 `GRANT v13_route TO v13_worker`（`v13_core.sql:842-844`），`v13_route_login` 是 INHERIT 单成员（`:838`）。这句保留。字面集替代项与 `USAGE` **今日**等效（没有第二个 INHERIT 成员），计划这句也对。

### 2.7 session_log 游标放在谓词之后，制造存在性神谕

§1.3：先谓词（假则零行），再 `< -1` RAISE `v13: session log cursor`。observe 把重复/NULL 元素放在授权**前**，因为那是参数合同、不依赖会话是否存在。游标 `< -1` 同样不依赖会话。放在谓词后：未授权+`−2` 零行，已授权子会话+`−2` RAISE。持有 EXECUTE 的调用方能以此区分「无亲缘/不存在」和「有亲缘」。这与 F27「不以异常区分存在性」冲突。handoff 把非法 cutoff 放在授权失败之后（§5.3），同一计划两套顺序。

修正：游标形状检查在谓词之前，文案不含 uuid；`p_after_seq = max` 仍是授权后的零行。§4.3 没有「未授权 + 非法游标仍零行、且不出现 cursor 文案」这一条，神谕现在连 gate 都没钉。

### 2.8 引用

| 计划说法 | 实际 |
|---|---|
| `v13_cancel` fanout:153、`v13_complete` fanout:305 | 对 |
| `v13_append_event` schema:62 | 对（体到 `:91`） |
| `v13_state_hash` control:358-402 | 函数从 `:362` 起；排除名单在 `:376-390`。差 4 行，不改结论 |
| `v13_pending_human` control:121 返回 boolean | 对。适配表的 uuid 分支是未来探针，不是今日事实 |
| complete proacl 含 spawn_owner | preflight §7.2 对 complete 成立。来源不是 fanout 的 GRANT 块（`:1040-1060` 只授 worktree 谓词），而是 `v13_spawn.sql:1735` `GRANT EXECUTE ON ALL FUNCTIONS` + 之后 `CREATE OR REPLACE` 保留 ACL。cancel 同理很可能也有，仍以当日 `proacl` 为准，不要把「预期 spawn_owner」写成 fanout 里有一行 GRANT |
| 路线图 Phase B L214–222 | 表在该段附近，验收句与三 stage 依赖没引错 |
| parity F17「失败一律 session not found」 | 对（parity:92）。operator 缺会话保留 `unknown session %` 是对冻结 needle 的例外，裁决正文必须点名，否则与源合同字面冲突 |

---

## 3. 被代码证伪，或被更简单事实替换

### 3.1 「load.py 现 20 项 / stage 21/22 SQL 仍零行」已被工作区证伪

HEAD（`56450d9`）的 `SQL_LOAD_ORDER` 止于 triage=20。工作区 `v13/load.py` 已修改：末项是未跟踪的 `v13/seam/v13_seam.sql`，`STAGE_THROUGH["seam"]=21`。该文件 692 行，`CREATE OR REPLACE` `v13_complete`（`:419`），`v13_record_worktree_released` 恰一次，位于 succeeded + tool + `worktree_release`、且在 `effect_done` 之后（`:590-594`）。无 `EXCEPTION`。`v13_cancel` 未换体。无 `v13/catalog/`，无 `test_seam.py`。

所以：

- §8 的停工闸仍然对：末项不是已绿 catalog，stage 23 不开工。不要把这份 seam 当成 Phase A 绿，也不要把它当成「不存在」。
- A1 的写作时证据「load.py 现 20 项」只对 HEAD 为真。复核步骤 1 必须以工作区为准。
- D12「恰一次、在 succeeded 尾」与这份未跟踪换体一致；与 HEAD 的 fanout 体不一致（零次）。存在性分支仍要，不能预写死「底稿里没有」。
- seam 末尾已 `GRANT v13_record_worktree_released TO v13_route, v13_spawn_owner`（`:687`）。A8 在这份文件落地后会过；在 HEAD 上函数不存在。协议写「不符则停」是对的，基线句要改。

这不把 Phase A 重开成「已实现」。停工态不变。变的是「零行」这句事实。

### 3.2 策略负例的跳过分支被触发器证伪

`v13_policies_frozen`（`v13_core.sql:715-729`）只拦 DELETE 和 name/version/**value** 改写。`active` 翻转是注释写明的唯一合法 UPDATE。`ux_v13_policies_one_active` 只禁**同时**两条 active，不禁「先灭 v1 再点 v2」。

§5.3「唯一 active 不允许则跳过，不得改成 UPDATE 种子」把两件不同的事捏在一起：改 value 会被冻结触发器拒绝；翻 `active` 是合法切换。跳过会丢掉 `enabled=false` 负例。修正：SAVEPOINT 内 `INSERT` v2 且 `active=false`，再只 UPDATE `active`，然后 ROLLBACK。不要跳过，也不要 UPDATE value。

### 3.3 其它已由代码定死、计划多写了「可能」的

- stage 17 守卫 WHEN 不含 `control/handoff`（`v13_control.sql:475-481`）。A6 的「可能误伤」对 control 守卫不成立；对未来 seam 守卫才需要看 WHEN。见 §1 fable。
- `v13_json_keys` 是 `ORDER BY k`（`v13_control.sql:102-106`）。四键探针序就是字母序 `delivery_id, schema_version, transcript_hash, up_to_seq`。探针留着，但不要再写成未定。
- `v13_pending_human` 今日就是 boolean（`:121`）。uuid 分支保留为停工探针即可。
- fable 的 `wake_pending`、effect 自身当 actor、谓词拒绝终态：见 §1，不要进草案。
- codex 把旧 cancel 的 `unknown session` 统一成 `session not found`：会打红冻结测试。计划没采纳，保持。

### 3.4 回退句被 PostgreSQL 事实证伪

§5.4「策略行与函数随加载序消失」只对下次 `setup_db` 重建为真。已执行过 stage 25 事务的库，git revert 不会 `DROP FUNCTION` / `DROP TRIGGER` / `DROP INDEX`，也不会删除 `control/handoff` 行。`CREATE ROLE` 是集群级的，`DROP DATABASE` 也不丢 `v13_handoff_owner`。codex 5.5 写了这句，整合时丢了。修正就这一句：回退不负责卸载已安装库；卸载是另一次显式迁移，且不得 `DELETE` 收据事件。回退顺序必须 25→24→23，否则 observe/extract 还指向已撤掉的谓词。

---

## 4. 两边都没盖住的边界

1. **属主生命周期。** grok/计划创建 `v13_handoff_owner`，没写谁在失败安装、revert、换带案之后删角色。角色跨库残留时，下一次 `IF NOT EXISTS` 会复用一个 GRANT 已被人改过的属主。codex 不建角色，所以也没写。选 DEFINER 就必须有「角色只由 stage 25 创建、GRANT 以安装后 DO 为闭包、换带案时角色留着但不再使用」三句，否则测试库绿、共享集群脏。
2. **`append_event` 的 status 赋值会点火 wall。** 计划写「extract 不改 `sessions.status`」。存储值对非 `user/message` 不变（`:80-83`），但 `SET status` 仍会触发 `UPDATE OF status`。DEFINER 成功路径因此依赖 wall 闭包。三通道都没把「点火 ≠ 改值」写成事实。属主缺权时失败模式是提交期 42501，不是 `handoff writer`。
3. **取消与超时。** codex 有一句「事务取消则 `next_seq` 与事件同回滚」。计划没写 `statement_timeout` / 客户端取消。无 EXCEPTION 时这是自动的，但 gate 没有「取消后 events 行数与 `next_seq` 回到调用前」的用例。幂等回读若在 emit 之后才做，取消窗口不存在；若有人把回读放进 EXCEPTION 里吞 `23505`，取消语义和去重语义会缠在一起。规格应禁止用 EXCEPTION 把 `23505` 收成「返回旧收据」。
4. **可测试性：行政带与冻结测试的角色通道。** spawn_owner 经历史 `GRANT ALL FUNCTIONS` 持有 cancel/complete EXECUTE，但不是 operator。换体后它对 human/cancel 从「能写」变成 `session not found`（若 2 参/6 参已镜像授予）或 42501（若没镜像）。§2 证伪 8 的 grep 是对的，但没写 grep 的判定是「成功期望」而不只是「出现过调用」。历代死体里的 `SET ROLE v13_spawn_owner` 不算冻结依赖。这条两边都只有半句。
5. **observe 的 `pending_human` 读 `effects`。** 授权段不读 events 是钉了的；快照段调 `v13_pending_human` 会读 effects。route 有 SELECT，所以 `SET ROLE v13_route` 能过。没人写：若适配函数对已授权会话 RAISE，错误原样传播（grok §4.3 有这句，计划 §1.3 丢了）。今日 boolean EXISTS 不 RAISE，所以不是当前故障，但是适配表的失败行为。

---

## 5. 答案会改变设计或顺序的问题（送 R7）

下列不是重开已拍板项。1–2 是现有送裁题的**可执行性**；3 是合并时新冒出来的值域；4–5 是裁决正文必须点名、否则实施顺序会停的句子。

1. **D7 通道不能以「采纳 §1」结案，除非 GUC 施工段先补进计划。** 现在选乙无法机械替换。补齐之前，R7 若写「选 GUC」，stage 23 仍须停工改计划。选甲则现有 §3.2/§3.4 可直接当规格。无论选哪，裁决要显式接受或拒绝：会话级 GUC 泄漏 = 错误 actor 的直接子仍可被写（§2.2），不是「只会收窄」。
2. **D16 写口不能以「采纳 codex 带案」一句话结案。** 带案还绑定：无新角色、extract 直写 `v13_append_event`、守卫查控制带、历史行按守卫核对而不是「有行即停」、以及下面第 3 条的值域。只删 DEFINER、留下 −1 和 `v13_handoff_emit`，两套规格会焊在一个函数里。
3. **空前缀 / `up_to_seq` 值域。** 三选一，都会改 stage 25 gate 与守卫： (a) 草案现状，NULL 在空会话写出 `up_to_seq=-1` 收据，显式 0 失败； (b) grok 旧行为，−1 合法但种子拒绝空收据、零写； (c) codex，无 −1，空日志即 `handoff cutoff`。极简键集已经否掉 (b) 的 `allow_empty` 键，并没有选 (a) 或 (c)。不裁这个，身份去重的「同身份」对空会话没有定义。
4. **C15 必须出现在裁决正文，不能只出现在计划草案。** 路线图 D7 字面是「可控任意非终态会话」。草案谓词不读 status，终态 cancel 仍 `replay`，终态日志/交接仍允许。否掉 C15 会同时改 R3 失败模式和 F18/F29。替代项 D7-alt-status 已在表里；R7 要点名采纳或否决，不能沉默带过。
5. **operator + actor 空 + 会话不存在，保留活体 `v13: unknown session %`。** 这与 parity F17「一律 session not found」字面冲突，也是 stage 1–20 冻结 needle。裁决若只写「所有拒绝同一字符串」而不写这个例外，stage 23 回归必红，实施者不得当场改 needle。

不需要 R7、应在改计划时直接修（不改变通道/值域选择）：§2.1 的 complete 插入顺序与源码断言；§2.4 的回读表达式与禁止 EXCEPTION 吞 `23505`；§2.5 的 `SELECT ON events`；§2.6 的 `rolsuper` 语法；§2.7 的游标前移；§3.1 的「零行」基线句；§3.2 的策略翻转负例；§3.4 的回退句；假绿 #20 的空针。

---

## 抽查锚（供对账，不是新规格）

- cancel 存在性 `:160`，树锁 `:204-214`，终态 `replay` `:216-218`，`unknown session %` `:161`。
- complete 锁 `:321-322`，unknown effect `:324`，stale/replay `:326-332`，cancelled 写 `:348`，human 围栏 `:355`。seam 同构：`:438`、`:441`、`:470`、D12 `:594`。
- state_hash 排除名单仅三 `session/*`（`v13_control.sql:376-390`）。`control/handoff` 会进 hash。计划的方向断言成立。
- `v13_json_int_ok` 拒负数（`:108-114`）。`v13_canonical_uuid` 小写 hex（`:116-118`）。`gen_random_uuid()::text` 在 PostgreSQL 上是小写，探针仍要跑，不要预判为假。
- policies：INSERT 不被冻结触发器拒绝；翻 active 合法；同时双 active 不合法。
- 角色：worker NOINHERIT 入 route；route_login INHERIT 入 route。`USAGE` 把 worker 排除出行政带，这句与代码一致。
- 加载序：HEAD 20 项；工作区 21 项止于未绿 seam。catalog 不存在。
