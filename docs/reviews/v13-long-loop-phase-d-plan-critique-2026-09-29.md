# v13 长循环 Phase D 计划评审（2026-09-29）

评审对象：`docs/plans/v13-long-loop-phase-d-plan-2026-09-29.md`（下称「计划」）。
基线：`prompt-exports/oracle-plan-2026-09-29-194658-v13-phase-d-deep-pla-d194.md` 的生成计划段（标题 `# v13 长循环 Phase D 计划（2026-09-29）` 起）。该标题之前的 composed prompt 只作背景。

方法：对两份全文做逐行 diff；对计划点名的承重缝做定点核查（`v13/spawn/v13_spawn.sql`、`v13/fanout/v13_fanout.sql`、`v13/control/v13_control.sql`、`v13/govern/v13_govern.sql`、全库 `13002`/`13003` 与 `WITH RECURSIVE` 检索）。不做泛化探索，不重开已裁决四项（`accept_second_entry`、`accept_hole`、`exclude C4 multi-lane`、`trigger_not_opener`）。

## 一、导出 → 计划的内容流失

**结论：无实现性内容流失。** 逐行 diff 显示计划相对导出只有四类差异，全部是有意增改：

1. 新增「执行索引」表（导航，无新合同）。
2. `spawn_budget` 种子行号 `:23-24` → `:24-25`（三处一致修正）。已对活体复核：`v13/spawn/v13_spawn.sql:24` 是 `INSERT INTO v13_policies ...`，`:25` 是值行。**修正正确，不得回退。**
3. §10 从「留给父复审」改写为「四项裁决」，保留原选择清单原文。
4. 新增 §11 引用。

导出 §10 的收尾句（「不接受则停…」）在计划 §10 以「上表四项已经裁决…」等价保留，效力未削弱。

## 二、发现（按严重度排序）

### D1（阻断）：`deadlock_retries_at_most_2` 在本设计下结构性不可复现，`fair_driver` gate 按计划文本无法变绿

计划的锁序使 `claim_one` 事务内死锁不可能发生：

- 驱动器拒绝已开事务的连接，事务内只有 `SET TRANSACTION` + `SELECT v13_claim_fair(...)`（§4.7）。
- `v13_claim_fair` 内第一个锁是 `pg_advisory_xact_lock(13002,1)`（§4.2 步 3），取它之前零行锁；等待 13002 的会话不持有任何锁，故不可能构成环。
- 候选选取用 `FOR UPDATE SKIP LOCKED`（步 6）——永不等待行锁。
- 步 9 的 UPDATE 只作用于步 6 已由本事务锁定的那一行——永不等待。

没有任何路径「持有 effect 行锁并等待 13002」（唯一取 13002 的一方总是先取它），因此 40P01 在这条事务里不可达。§7.2 对不可复现的处置是「进程非零退出，消息 `v13: claim fair: ask_user`，本 stage 不是 `exit_0`」——即 **`fair_driver` 里程碑按计划自身条款必然停在 ask_user**，`fair_claim_retries=2` 与重试分支成为不可达死代码，但又被列为必测断言。

**修正建议**：把该断言的证据面从「真实 DB 死锁」改为「驱动器单元注入」——在测试里于 DB-API 层注入一次/两次 `psycopg` 40P01 异常，断言重试恰 2 次、无睡眠、第二次仍失败则抛出。这测的是驱动器重试界（该断言的真实标的），不伪造数据库行为；真实 DB 死锁复现一途保留为「若未来有人在事务里加第二条语句再说」。不改此条，`fair_driver` 无法交付。

### D2（高）：候选语句形状未指定，且「一条 SELECT」「领用与快照都调用 `v13_fair_eligible`」「不在 PL/pgSQL 循环上溯」三约束在现命名函数集下互相矛盾

排序元组第一键 `inflight_claimed` 是**按根聚合**（该根全树 `claimed` 行数），合格判定需要**每候选一次祖先上溯**。但：

- 五函数清单（§6.1「五个函数」）里没有任何根解析 / in-flight 计数函数。全库检索确认：`v13/` 下 8 个文件各自内嵌 `WITH RECURSIVE`，**没有共享的 root resolver**；`v13_spawn_occupancy`（spawn `:169` 一带）有自用上溯但计划明令禁调。
- PostgreSQL 锁子句不能与 `GROUP BY` / 聚合同层共存（PG 文档 Locking Clauses 的限制清单）。因此 §4.2 步 6 的「一条 `SELECT … ORDER BY … FOR UPDATE OF e SKIP LOCKED LIMIT 1`」必须把 per-root 计数放进子查询/CTE、外层只留 join + 锁——单条语句可行，但形状唯一且不平凡，计划的 §9 重读清单里没有对应的语法/形状探针。
- 若把合格谓词内联进同一条 CTE（为排序反正要做上溯），则领用**没有**调用 `v13_fair_eligible`，违反 §4.3「领用与快照都调用它」；若改为每候选行调用 `v13_fair_eligible(e.effect_id)`（其内部各自上溯），则排序所需的上溯被做两遍，且这就是「对每个 effect 上溯」只是藏在函数调用里——与 §4.2 步 6 的禁令语意相抵。

**修正建议**（二选一，写进 §4.2/§4.3，并给 §9 加一行形状探针）：

- 甲：增加第六个具名函数（如 STABLE `v13_fair_root(p_sid uuid) RETURNS uuid`，含 64/环守卫），claim / eligible / snapshot 共用；排序聚合用 CTE 包住、外层锁 `e`。消除三处各写一份上溯的漂移面。
- 乙：明文允许 claim 单语句内联递归谓词、放弃「领用调用 eligible」的字面，改用「同库同数据下 claim 可选集与 `v13_fair_eligible` 逐行等价」的对照断言钉住一致。

### D3（高）：`static_check` 的 UPDATE 白名单与 soak 夹具自相矛盾；`effects +5` 计数有未写明的前置

- §4.7：测试文件的 `UPDATE effects SET created_at` / `SET lease_until` 「只能出现在第 7 节点名的那两条断言的辅助 SQL 里」。但 **§7 从未点名是哪两条**，而 §4.9 的 soak（`test_fair_driver.py`，另一份文件）自己要求 `T1<T2<T3<T4` 与 tick 7「晚于 T4」的 created_at 改写（§4.8 明说夹具用这句 UPDATE）。按字面执行，soak 的夹具 UPDATE 违反 static_check。
- §4.9「effects 增量等于 5」要求 tick 7 入队产生**新 effect_id**。`v13_enqueue_effect` 的身份是 `v13_effect_id(p_sid, p_kind, p_request)`（control `:904-905`）：同 sid、同 kind、同 request 只会命中 `failed` 重挂分支（UPDATE，行数不变，`created_at` 不变），增量是 +4 不是 +5。计划没写「request 必须与 R1 原行不同（如加 nonce）」。

**修正建议**：在 §7.1/§7.2 分别点名允许 UPDATE 的断言（`tie_oldest_created_at`、`requeue_wall_unchanged_frees_cap`、soak 夹具各自成条），soak 夹具明确「四次入队的 request 互不相同且 tick 7 的新行 request 亦不同」。

### D4（高）：路径第二道闸只挂 BEFORE INSERT，`v13_enqueue_effect` 的 failed→ready 重挂是 UPDATE，绕过闸门

`v13_enqueue_effect` 的重挂分支是 `UPDATE effects SET status='ready' …`（control `:929-933`），不触发 `trg_effects_workspace_path_lock`。时序：根 A 的带 `workspace_root` 的 tool effect 处于 `failed`；根 B 的 INSERT 在触发器复检时看不到 A 行（failed 不在忙集 `{ready,claimed,unknown}`）→ 放行；A 侧随后重挂回 `ready`（无闸）→ 两根出现重叠 ready。§4.6 只声称覆盖「插入路径与直接调用」，全文没有一处提到重挂路径。

注意：把触发器扩成 `BEFORE UPDATE OF status` 会改变既有重挂路径的行为（重挂可能被别的根的忙行 RAISE 掉），这不是编辑 `v13_enqueue_effect` 字节，但属行为面变更，与已裁决的 `trigger_not_opener` 不冲突（不碰打开者），却需要父明确点头，不能实现时顺手加。

**修正建议**：默认按「已知洞」写进本期台账（与本计划对 `accept_hole` 的处理同风格）；父若要堵，须在 §4.6 增补 `BEFORE UPDATE` 变体的显式条款与对应断言（含重挂被 path_busy 打断的负例）。

### D5（中）：§4.3「必须调用活体函数，不得抄一份名单」与活体代码不符——`op_seq` 臂与 `status='ready'` 不是函数

活体 `v13_claim`（fanout `:266-303`）体内，四条对齐臂中只有 `v13_attempt_ok` 与 `v13_requires_worktree` 是可调用函数；`status='ready'` 与 `op_seq` 臂（`op_seq IS NULL OR op_seq = (SELECT min(op_seq) … same session_id, same mutation_scope, status <> 'succeeded')`，`:277-281` 一带）是**内联 SQL**，没有任何活体函数可调。`v13_fair_eligible` 只能复刻这段文本——恰是 §4.3 明文禁止的「抄一份」。§9 重读行（「新函数不得少掉 `v13_attempt_ok`、`op_seq`、`v13_requires_worktree`」）又默认了复刻。两处打架。

**修正建议**：把 §4.3 改写为「凡活体以函数表达的谓词必须调用原函数；`status` 与 `op_seq` 两臂只能复刻 SQL 文本，并以断言钉住等价（同库同数据下，新谓词的可选集与活体 claim 子查询的可选集一致）」。

### D6（中）：帽席位的崩溃回收在生产面无 owner

有限租约过期后，`claimed` 行只有在**有人调用** `v13_requeue_stale` 时才变 `unknown` 释放席位。本期：fair driver 禁调 requeue；`goal_supervisor` 的名单只写了禁 claim/enqueue/advance，没写谁拥有 requeue；A/B/C 亦未点名生产 requeue 调用者。多 goal 下一次 worker 崩溃 = 席位被占 + 会话被墙，直到运维手动 requeue。§4.4 只把 `infinity` 行写成残留，没把「过期有限租约等 requeue」的**触发责任**写成残留。

**修正建议**：不新增交付，但必须在 `fair_claim`/`fair_driver` README 与台账把「席位释放依赖外部 requeue 调用、本期无生产 owner」写成已知洞；或父指认 Phase C 监督进程为 owner（若是，补一行依赖说明，不改名单）。

### D7（中）：INVOKER 链 ACL 依赖未入「保持未决」清单

新函数全部 INVOKER、`REVOKE EXECUTE FROM PUBLIC`（§4.2）。`v13_claim_fair` 调用 `v13_goal_lifecycle`，而后者已 `REVOKE FROM PUBLIC` 且只 `GRANT` 给 `v13_route`（govern `:1191`、`:1201`）。gate 以超级用户跑不会暴露；将来任何非 `v13_route` 的工人角色调 `v13_claim_fair` 会在链上断 EXECUTE。这与 v13 B2 交付时记过的「INVOKER 链 ACL 缺口」同类。计划把「产品角色」列为未决，但没点出**新函数的 callee ACL 是其组成部分**。

**修正建议**：§9「保持未决」清单加一行：「`v13_claim_fair` 的生产执行角色需同时持有 `v13_goal_lifecycle`（及 `v13_attempt_ok`、`v13_requires_worktree`）的 EXECUTE；本期不 GRANT」。

### D8（低）：行号与事实的可精确修正项

- **`v13_claim` 的 fanout 区间是 `:266-303`，不是 `:266-297`**：`$function$;` 收在 `:303`，`:305` 已是 `v13_complete` 的 CREATE。§3 以「行号以本节为准」立信，此端点应改（起点 `:266` 正确；覆盖 schema 侧 `:266-294` 未复核）。
- `v13_goal_lifecycle` 是**已落地的 stage 29 函数**（govern `:129-135`，`LANGUAGE sql STABLE`，`v13_goal_fold` 薄包装），不是 A/B/C 前置。§4.2/§9 的条件式（「若它是 VOLATILE…」）可以现在就收口为 STABLE；§6 把它列入 A/B/C 前缀依赖无害但易误导。`hashes_unmodified` 含它是对的。
- `v13_reject_bad_harness_request`（control `:159-176`）对「无 `logical_turn_id`/`continuation_index` 键且工具名非 `harness_turn`」的请求**直接 RETURN**：soak 的 `kind='llm'` 夹具可构造。§9 该停点已可预先记录为「不触发」，保留重读无妨。
- 全库无 `13002`/`13003` 使用；`v13_advisory_class`（spawn `:32-38`）只映射 `spawn_budget→13001`、其余 RAISE——计划硬编码 13002/13003 与「不修改 `v13_advisory_class`」的组合成立，§9 撞名停点会通过。

### D9（低）：`omitted_complete` 是派生键

`omitted_count` 只有 0/1 两值，`omitted_complete` 在 1 时恒假、在 0 时未规定（按意应恒真）。闭集里多一个无独立信息的键。可整键删除（并同步 §7.1 `snapshot_cap_33` 断言），或写死两态真值表。不删也不影响正确性。

### D10（低，可测性）：双连接阻塞类断言在「无睡眠」纪律下缺协调手段

`path_busy_two_roots_two_connections`、`two_fair_claimers_respect_cap`、`skip_locked_does_not_wait` 都要求「等 B 确实阻塞后再推进 A」。计划只禁 `pg_sleep`，没给替代协调（轮询 `pg_locks`/`pg_stat_activity` 直到 B 出现等待事件，或用条件变量/线程 join 的有界轮询）。建议在 §7 公共纪律加一句「阻塞确认用 `pg_locks` 有界轮询，不用定时睡眠」，避免实现者各自发明。

## 三、会实质改变设计或实现顺序的问题

1. **D2 甲/乙**：根解析是第六函数还是内联 CTE？决定函数清单、volatility 标注、`v13_fair_eligible` 的角色，以及 fair_claim SQL 的最终形状——实现第一行 SQL 前必须定。
2. **D1**：40P01 断言改为注入式，还是删除并 README 记录？不改则 `fair_driver` 里程碑必然停在 ask_user，顺序上它会卡死整个 Phase D 收尾。
3. **D4**：重挂绕闸是记台账（默认）还是扩 `BEFORE UPDATE` 触发器（需父点头的既有路径行为变更）？
4. **D6**：生产 requeue（席位回收）owner 是 Phase C 监督进程、未来工人，还是明确「暂无、记洞」？影响 README/台账措辞与 Phase 间依赖声明。
5. **D7**：`v13_claim_fair` 的生产执行角色是否随本期一并指认 ACL 依赖（不 GRANT、只记录），还是完全并入「产品角色未决」？
6. `v13_claim_fair` 是否被视为活体 `v13_claim` 的**将来替代**（工人逐步迁移）？若是，`accept_hole` 的洞是时限性的，README 与矩阵的措辞从「永久洞」改为「迁移前洞」，但不改变本期实现。

## 四、复核通过、无需改动的承重点（备查）

- 计划对活体 `v13_claim` 的谓词描述（全局 ready 池、`ORDER BY created_at`、`FOR UPDATE SKIP LOCKED LIMIT 1`、四条过滤臂、无 session/root 过滤）与 fanout `:266-303` 正文一致；`RETURNING` 恰五键，公平版六键 = 五键 + `root_session_id`，自洽。
- `v13_complete` 五参签名（`p_effect, p_attempt, p_fence, p_status, p_result DEFAULT NULL`，fanout `:305`）支持 soak 的 `v13_complete(..., 'failed', NULL)` 用法。
- 13002/13003 无撞号；`v13_advisory_class` 单映射；spawn 种子行号修正（`:24-25`）经活体核对正确。
- 计划未把导出的任何实现性内容删弱（见第一节）。

## 五、结论

计划总体可直接进入实现准备，但 D1 不修则 `fair_driver` 按自身条款不可交付；D2/D3 是实现第一天就会撞上的合同内矛盾；D4/D5 是一句话可修的对齐错误；D6/D7 属于必须落墨的已知洞与未决项。以上均不触碰四项已裁决与 Phase 0/A/B/C 约束。
