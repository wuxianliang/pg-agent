# Postgres-Native Agent V11 实现规范草稿

> 状态：基于 v8 冻结基线与 v10 冻结规格的**升级实现规范草稿**，待实现规范审核；未执行实现与运行验收。
> 撰写日期：2026-09-16。唯一交付为本文件；本文件不改变冻结 v8、不改变冻结 v10 规格、不改 v9。
> 效力：完整继承 v8 不变量 1–18 与 v10 不变量 19/20；精确引用 v8/v10 协议；完整定义 v11 增量；MUST/MUST NOT 为待审核合同。
> 定位：v11 是 v8 的**分阶段升级**，终局里程碑在 v8 基座上闭合 Dream-RSI 的 online → offline dreaming → redeploy 环。v11 是叠在 v8 之上的**新规范**，MUST NOT 修改 v8 冻结不变量，MUST NOT 修改 v10 冻结规格。

输入指纹（实际文件 SHA-256，不代表实现 commit）：

- `docs/designs/v8-dev.md`：871 行；`445306132fa01b278d479bc465c9a71c3b241407ec8a88b4d654967856237287`。
- `docs/designs/v10-dev.md`：1098 行；`1bfe744c1c90358813dbeefb66b7e85e0a0e70933c3a3fa0de0f6d41f895a445`。
- `AGENTS.md`：76 行；`45f5d74bdaa19dc9cfbdca39acd65a4056aa610e53d493e612a37ead054ceb1a`。
- Dream-RSI 论文正文提取：`/tmp/dreamrsi.txt`，2238 行（由 `papers/Dream-RSI.pdf` 用 pypdf 提取；数学符号被插入空格，属提取噪声）。下文 `txt:N` 均指该提取件行号，非论文原始页码——凡引用数值/默认值处均已核对「论文未给出」并如实标注。

## 0. 基线、范围与不变量〔D1〕

### 0.1 文档效力与基线冻结

**基线冻结为 `git rev-parse HEAD` = `b3ce055553f6d522a0d597e5066290fe24ab1c6d`**（"v8: merge G13 compat stage (P0C host-independent contract surface) into main"）。

**基线 vs 现状（〔审阅修正〕：已重基线）**：本节基线仍钉在 `b3ce055`；但**审阅时仓库 HEAD 已前进**（实测 2026-09-17：HEAD = `f2dd525`），且 `b3ce055` 之后的 **G12 已作为 commit `605e866`「v8: add dual real-time authz gates, cohort enforcement and A57 removal (G12 gates stage)」合并进 main** —— `v8/gates/`（`__init__.py`/`setup_db.py`/`test_gates.py`）**已被跟踪**，`v8/load.py` 已有 `"gates": 13` 键。**工作区当前 NOT clean（〔审阅修正〕blocking：MED-1 实测更正）**：`git status --short` 实测为 **` M v8/load.py`、`?? docs/designs/v11-dev.md`、`?? v8/concurrency/`** 三行（原文「`git status --short` 现在是干净的（只有未跟踪的 `docs/designs/v11-dev.md`）」与实测不符，已删）。其中 `v8/concurrency/`（`__init__.py`/`setup_db.py`/`test_concurrency.py`）是一个**进行中的 G14「concurrency」stage**，`v8/load.py` 的未提交 hunk 追加 `"concurrency": 13` 键与自述注释「G14 (concurrency) also adds NO SQL: it reuses the frozen gates load」—— 故工作树的 `STAGE_THROUGH` 现有 **14 个 stage 键**（`schema, grant, events, stream, effect, tools, retry, loop, repair, cancel, plugin, compat, gates, concurrency`），**不是 12 个**。原文「撰写本文件时工作区是 dirty 的」「`v8/gates/` 为未跟踪目录」「`v8/load.py` 的 `STAGE_THROUGH` 在 HEAD 与工作区不同」是 **`b3ce055` 时刻**的陈述，**对本仓现状不成立，此处删除**（不再作 present-tense 断言）—— 但「工作区 dirty」这一**方向**在实测下**重新成立**（因 G14 未提交）。相应后果：

- **G12 已落地** ⇒ §10.2 T0 的接入门清单 MUST 含 `v8/gates/` 的门（见 T0 ⑥/⑦），§13.2 第 2 项的矩阵表头**当前已含** `… G10 144 / G11 207 / G13 153 / G12 165 PASS`（G12 在列；G10 由 143 移到 144）。
- **G14 进行中（〔审阅修正〕blocking：MED-1）** ⇒ §10.2 T0 的接入门清单 MUST 也含 `v8/concurrency/` 的门（见 T0 ⑥），且 `v11` 的 `tree` 键 MUST 追加在未提交的 `"concurrency"` 键**之后**（§2.5 落位时序）。`v8/concurrency/` 与 `v8/gates/` 一样**不加任何自己的 SQL**（只复用既有 gates 加载集），故 SQL 槽位仍无争用，但 `STAGE_THROUGH` 字典本身有一个**未提交键**。
- **行号参照系**：全文行号引用以 `b3ce055` 为准；**但八处 internal ordinal 分配点的引用行号实测取自 G12 之后的工作树**（`b3ce055` 上对应 `effect:1276,1459,1702,1853`、`tools:464`、`takeover:352`；`closure:388`/`repair:333` 两版相同），见不变量 22 / §2.1 D7 / T0⑥ / T1⑯ / A.2 各处的〔审阅修正〕注。

**v11 的一切增量以 `b3ce055` 为准，MUST NOT 以工作区（含已合并的 G12）为准**；本文件凡称「G1–G11 + G13 全绿」均指 `b3ce055` 上的 gate 集合，G12 另计（§10 T0）。

冻结基线清单（本文件引用其一，即为其唯一权威）：

- `docs/designs/v8-dev.md` §0「不可妥协的不变量」（L5–24）——18 条，逐字继承。
- `docs/designs/v10-dev.md` §0.3「新增不变量 19–20」（L48–53）——继承；v10 自述该编号「未随 raw 准出成为冻结实现合同」，故 v11 引用其**语义**，不引用其「已冻结」地位。
- v10 §2.1 对象登记表（L134–162）27 行、v10 §6.1 入口清单（L620–641）、v10 §8 明确不做（L958–974）。

冲突效力：冻结 v8 合同优先；v10 范围内语义按 v10 冻结规格；本文件新分配的编号（21–31）为本草稿分配，**待 v11 规范审核冻结，未随任何准出成为冻结实现合同**（沿用 v10-dev.md:50 对 19/20 的同一措辞方式）。本文唯一 schema/协议归属为 §2–§9；验收唯一归 §10/§11；原 v8/v10 字节算法、状态表与锁序不复制、只引用。

### 0.2 继承不变量 1–18（v8）与 19–20（v10）

**本列表内原有「§」引用均指冻结 `v8-dev.md`／`v10-dev.md`，不是本文件同号章节。**

1–18. 逐字继承 `docs/designs/v8-dev.md` L7–24（`session_events` 只追加与无洞 seq；权威控制态非 projection；三类独立 fence；外部 IO 不进事务；稳定 `effect_id`；本地至多一次；unknown 不盲目重放；NOTIFY 仅唤醒；assemble/fold/catalog/grant/policy 绑定 snapshot/cutoff/generation；并行完成顺序不改语义；强制策略失败封闭；插件不绕过 capability API；step/effect 固定 generation/digest/contract version；规范是行为合同；同 `driver_epoch` 单 driver；租户 `workspace_id` ≠ 执行态 `workspace_handle`；每次 seam/route/`ready→dispatch_started` 同事务复验 grant；yield 前 checkpoint 或显式 `workspace/lost`）。MUST NOT 重述、MUST NOT 修改。

19–20. 继承 `docs/designs/v10-dev.md` L52–53 的**语义**：19 = 执行装配与初始 decision seal 原子发布；20 = Bind 不执行外部工作（无网络、无 FDW/dblink、无 live workspace 读取、无 renderer/宿主 handler；缺输入按 `needs_preparation` 返回）。**v11 明确接受 20 的「Bind 不得读 live workspace」**，并将其作为 §5 节点世界建模的硬约束之一。

适用说明：v11 展开的是 v8 不变量 1 与 9 在**树形会话**下的实现结构；v11 不重开 v8 的 canonical/normalize/turn reducer/流完整性任何一条。

### 0.3 新增不变量 21–31

以下编号为本草稿分配，待本规范审核冻结，**未随任何准出成为冻结实现合同**。每条均声明它**禁止**什么。**（引用体例〔审阅修正〕（终轮）：本文件**内部**交叉引用一律用**章节号**（如 §6.2），**刻意不用行号** —— 本文件仍在修订，行号每次改动即失效；凡写成 `file:line` 或 `txt:N` 者一律指**外部冻结文件**（v8/v10 SQL、`v8-dev.md`、`v10-dev.md`、论文提取件），不在此列，MUST NOT 因本节而改动它们。）**

**21. 路径权威（path authority）。** 一个 TREE 会话的上下文顺序由 **leaf → root 的 `parent_entry_id` 路径**决定。`seq` 仅是物理追加序与提交序裁决者，MUST NOT 再被当作上下文顺序。`parent_entry_id` 一经写入不可变（既有 `trg_session_events_append_only`，`v8/schema/v8_schema.sql:190-199` 已保证）；一个 event 可在多条路径中可达（物理共享，非复制）。**禁止**：任何消费方以 `seq` 升序当作 TREE 会话的上下文顺序。

**22. 双 ordinal（dual ordinal）。** semantic 行仍恰好携带两个 ordinal 之一（`session_events_ordinal_class_check`，`v8/schema/v8_schema.sql:164-178` 不动）。LINEAR 模式：调用方提供 `semantic_input_ordinal`，语义与唯一性逐字节不变（`v8/events/v8_append.sql:535-556`；`session_events_public_ordinal`，`schema:182-184`）。TREE 模式：调用方 MUST NOT 提供 `semantic_input_ordinal`（新码 `SEMANTIC_ORDINAL_FORBIDDEN_IN_TREE`），由 DB 在同事务派生 `internal_semantic_ordinal`。**派生公式 MUST 与冻结的八处分配点同款** —— `SELECT coalesce(max(se.internal_semantic_ordinal),0)+1 FROM session_events se WHERE se.session_id = p_session_id`（八处：`v8/effect/v8_effect.sql:1516,1700,1950,2114`、`v8/tools/v8_tools.sql:523`、`v8/cancel/v8_closure.sql:388`、`v8/retry/v8_takeover.sql:410`、`v8/repair/v8_repair.sql:333`；**〔审阅修正〕行号取自 G12 之后的工作树，`b3ce055` 上对应 `effect:1276,1459,1702,1853`、`tools:464`、`takeover:352`**，`closure:388`/`repair:333` 两版相同），在**持会话行锁**下执行。**禁止**：新增任何 `sessions.next_internal_ordinal` 式计数器列 —— 该列会与上述八处成为同一值域的两个写者，`turn/end`（每次 turn 关闭必经 `v8_closure.sql:388`）派生 `max+1` 而不推进计数器，下一次 `v_tree_append` 从计数器取值必然撞 `session_events_internal_ordinal` UNIQUE（`schema:185-187`）。`internal_semantic_ordinal` 在 TREE 下的角色降级为**创建序见证**（= 论文 `CellMeta.seq`，`txt:1029`），并成为重放 Child 规则的排序依据（`txt:268-270`）。

**23. `path_ordinal` 不落库。** 路径序 ordinal = `v_tree_context` 的 `row_number()` 投影，MUST NOT 持久化为列。理由（可直接验证）：同一 event 在每个可达它的 leaf 的上下文中处于不同位置，任何「每会话唯一」的存储列在数学上都无法表达路径序 —— 这正是 BACKGROUND 第 4 点与 v8 唯一性索引相冲的根因。**禁止**：任何「每分支路径序」的存储列。

**24. leaf 游标是追加事件 + 单子节点约束。** CURRENT leaf 是一条 `event_class='audit'` 的追加事件（`event_type='session/leaf'`），MUST NOT 经公开 append facade，MUST NOT 复制任何行；唯一写者 `v_tree_set_leaf` 必须持会话行锁并按 no-hole 纪律从 `sessions.next_seq`（`v8/schema/v8_schema.sql:34`；纪律同 `v8/events/v8_append.sql:951,1092`）分配 `seq`。故「分支」是 O(1) 追加、零 UPDATE（对齐 pi `session-manager.ts:1277-1282` 的 O(1) 叶子移动）。**单子节点约束（重放确定性的前提）**：对 `session_mode='tree'` 的会话，每个**非根** `(session_id, parent_entry_id)` MUST 至多有一个**已录子节点**（**〔审阅修正〕「已录子节点」在此定义为 `event_class <> 'audit'` 的已录子节点** —— 与 D6 索引谓词逐字同义；`session/leaf` 等 audit 行不计入，否则「一个 semantic 子 + N 个 audit 子」会同时满足索引与本文措辞；由部分唯一索引强制，§2.1 D6，其 root 例外位见 D8 `parent_is_tree_root`）——论文的 Child 规则「v≠r 返回 v 的**唯一**已录子节点」（`txt:265-267`）在「一个节点可有多个子节点」的通用树上是无定义的，v11 以结构性约束消灭该歧义，而非依赖 UUID/行序「碰巧」确定。**root 例外（〔审阅修正〕blocking）**：root 可拥有**任意多**个已录子节点 —— 这正是「分支建模为 root 的子节点」（论文 `txt:269,1101`）所要求的结构；`v = r` 时的 `earliest-created` 序由 `internal_semantic_ordinal` 升序确定（§1.4）。原文本把唯一性无条件施于包括 root 子节点在内的所有 `(session_id, parent_entry_id)`，会把已录树压成单链、使 `\|A(T)\| ≡ 2`、批势被结构性封顶在 2，与本条自身、§1.4、§6.2 与论文四处同时冲突，故本版显式给出 root 例外。refinement 建模为 **分支头的子节点**，其单子节点前提由此结构性成立。**禁止**：在 tree 会话中使一个**非根**节点拥有两个已录子节点（root 的多子节点是分支语义的载体，不在此禁列）。**追加父（〔审阅修正〕blocking）**：`v_tree_append` 的父是 root、当前 leaf 或**已录树的任一叶**（§3.2）—— 一个 W 宽批向 W 个不同 frontier 各追加一次，故本条 MUST NOT 以「父 = 单一当前 leaf」表达。

**25. 重放入口是决策层只读纯函数，且负向清单是双向的。** `v_replay_probe` 是决策层只读入口，**零业务/控制写集**逐条对齐 `v10-dev.md:366`：无 step/effect/receipt/manifest/plan/trace/audit、无 latch/emergent/stats/spill/session/lease/fence 变更。**唯一显式例外（〔审阅修正〕blocking；本版收窄口径，全文一致）**：读入口授权合取失败时写的一行**授权拒绝遥测** `authz_denial_audits`（§2.4/§7.4/不变量 31/T4⑧）**不计入**零写集 —— 它不写任何被读对象的业务/控制状态（无 receipt、无 plan/manifest/trace、无 session/lease/fence 变更），故 v10 `:366` 清单中的 `audit` 项在本规范内**收窄为「业务审计」**；`authz_denial_audits` 是拒绝遥测，不是业务审计。此例外是不变量 25 与不变量 31／§2.4／§7.4／T4⑧ 之间冲突的**唯一**解法，MUST NOT 再扩大。同时 MUST NOT 调用 renderer、MUST NOT 重新装配、MUST NOT 重新做授权捕获、MUST NOT 调用任何 evaluator —— 与 `v10-dev.md:365`「与 execution 共用计算核」**刻意相反**，因为内环 oracle 的成本画像只允许读已录结果。**读集边界（双向清单，v10 只列了写集）**：`v11_node_scores`／`v11_node_artifacts`／未揭示节点的 `session_events` payload 对**当前 episode 的消费方**不可读；分数只在节点落入该 episode 的揭示集之后才可见（§7.4）。**禁止**：把「只读」当作「无边界」；把 score 表当作普通可 SELECT 表。

**26. 批合法性 DB 强制，且重放只接受已持久化的合法批。** 批的合法性是可计算判定式 —— distinct id、`|C| ≤ W`、批内 MUST NOT 含父子对、每条已开分支至多一个 frontier、批内 cell 调用前全部合法（论文 `txt:1139-1143,1100-1106`）—— 由 CHECK/触发器强制（§2.1 D8/D9），MUST NOT 仅写在提示词里靠模型自律。`v_replay_probe` **不接受调用方自带的 node id 数组**：它接受一个已持久化、已合法化的 `batch_id`，并在同事务内重算 `A(T)`、对任一非当前合法 cell 稳定拒绝 `REPLAY_CELL_NOT_LEGAL`（§7.3）。**禁止**：为同一操作保留两条 enforcement 不同的并行接口（这正是 A73/A84 的双实现隐患）；以调用方传入的 id 绕过揭示集。

**27. 策略指针唯一（CAS）。** 策略 active 指针**复用 v10 的语义**（`v10-dev.md:136,644-645`），但在 v11 的对象上**重新表述（〔审阅修正〕blocking：第三轮）** —— v11 **没有** `building/active/retired` 状态列：`v11_replay_policies` 是**不可变策略产物**（§2.3/T7e 对它 BEFORE UPDATE OR DELETE 一律拒绝），故该状态词汇无处安放。v11 的等价物是：**唯一 active 槽** `v11_policy_pointer`（`workspace_id` PK）、**CAS**（全量 `expected_active_policy_id + revision`）、**单调 `revision`**、**写者闭集仅三**（`v_policy_stage` 首次建 NULL 空行 / `v_policy_activate` 把非 NULL 目标 CAS 指向某**已写入** `v11_replay_policies` 的行 / `v_policy_revoke_active` 显式置空）。**禁止**：以任一「当前 active」表述的行代替指针（v11 无状态列可反推）；把指针当缓存；**把 `active_policy_id` 指回一个已被 `revoke_active` 置空的旧产物以「恢复」** —— 恢复 MUST 发布**全新** `v11_replay_policies` 行（新 `(workspace_id, generation, policy_version)`），该禁令由**写者闭集仅三 + 命令集**承担，不由状态列承担。

**28. 节点级世界 = 不可变 content-addressed artifact + 世界闭包。** 节点级可恢复状态以不可变 content-addressed artifact 建模；MUST NOT 新增 per-node live handle。每个节点 artifact MUST 携带 `world_closure_digest` 与 `closure_complete`；**闭包不完整或未验证的节点 MUST NOT 被用作分支父节点，也 MUST NOT 被用作重放世界根**。v8 的 `workspace_handles`（`v8/grant/v8_grant.sql:733-751`）仍是 runtime 的单一 live 句柄（一 `(session_id,run_id)` 一 `owner_fence`、一 `generation`、一 checkpoint），v10 不变量 20（`v10-dev.md:53`）禁止 Bind 读 live workspace，v10 §3.7（`:380`）禁止继承 live handle —— 四方一致，v11 不破此墙。**禁止**：把 `workspace_handles` 当 per-node 世界树；把未闭合 artifact 当世界。

**29. 派生 DAG 无损。** 压缩派生以**派生边表**表达（`source_type ∈ {event,node}`），「已消费」= `NOT EXISTS` 集合差（pi-lcm `src/db/store.ts:405-411`），MUST NOT 用可变 flag（MUST NOT 移植 pi-lcm 的 `is_compacted` 就地 UPDATE —— 那违反 v8 不变量 1）。`session_events` 原材料 MUST NOT DELETE/UPDATE。此条与 v10 `CompactHistory` 的减法语义（`v10-dev.md:338-339`，明确「不得生成新摘要或调用模型」）**并存而不冲突**：`CompactHistory` 仍是装配变换，v11 的无损 DAG 是独立的节点级对象。**禁止**：以可变 flag 表达消费；删除原材料。

**30. 揭示集是 episode 级派生状态，不是会话级属性。** 「已揭示」MUST 定义为**该 episode 的状态函数**（**两个集合 MUST 分开命名、MUST NOT 混用**：**已观测节点集 `O`** = 论文 `T^{m,k}_i` 的**节点集** —— 含**全部已揭示节点**（内部节点与叶一并计入），`|O| = |T^{m,k*}_i|`（论文 `txt:242-244`：「the subtree revealed after k completed rounds … only the portion observed by the policy evolves」）；**frontier / 合法 cell 集 `A(T^{m,k}_i) = {r} ∪ leaves(O)`**（论文 `txt:202-203`：`A(T)={r}∪{v∈T : v is a leaf}, where leaves are determined from the currently observed tree`）—— 它是**由 `O` 派生**的边界集，**不是** `O` 本身；`A(·)` 全文只保留此一个语义；**`n_revealed = |O| − 1`** —— 等于论文的 `N = |T^{m,k*}_i| − 1`（`txt:286-292` 的「revealed non-root nodes」），是 `v11_reward` 与 V 公式的入参、也是 T5f 黄金向量的口径（§2.1/§7.2）。**〔审阅修正〕LOW-2 收口（终轮重写）** —— 本条原文写 `O(T) = {r} ∪ {observed leaves}`（`txt:202-203`），即**把 frontier 公式误当成 `O`**：那样 `O` 与 `A(T)` 字面相同（第三轮的改名并没有真正拆开两个符号），且 `n_revealed = |{r} ∪ observed leaves| − 1` 对深度 ≥ 2 的链**不等于** `|T| − 1`（例：`r→a→b` 时 `|{r,b}| − 1 = 1`，而 `|O| − 1 = 2`），与本文件 §2.1/§7.2 的 `n_revealed = N = |T| − 1` 直接冲突。原文的「`A(T)` 含全部叶、`O(T)` 只含已观测叶」这一区分**是错的** —— 论文明确 `A(T)` 的叶**就是**当前**观测**树的叶；正确的区分是「`A(T^{m,k}_i)` 是 `O` 的 **frontier**」。**双集断言（§11 T5j）**：`r→a→b` 且观测树含三节点时，`|O| = 3` ⇒ `n_revealed = 2`，而 `|A(T^{m,k})| = |{r} ∪ leaves(O)| = |{r,b}| = 2` —— frontier 与 `O` **不是同一个集合**。），MUST NOT 定义为「从 root 沿 parent 链可达的节点集」—— 在一次已完成的 rollout 中，每个已录节点都落在某条 root→leaf 路径上，会话级定义会返回**整棵已录树**，即恰好泄漏策略尚未探过的 outcome。`v_tree_revealed`／`v_tree_legal_actions`／`v_replay_probe` 的签名 MUST 含 episode 身份（或由已持久化 `batch_id` 唯一确定之），且 MUST NOT 由调用方指定的 leaf 反推揭示集。**禁止**：会话级 revealed 定义；由调用方 leaf 参数决定可见范围。**（本条的「读时投影」性质与 23 同源：排序/边界两者的权威都在读时，不落库。）**

**31. TREE 会话的租户与授权读边界。** TREE 会话 MUST 有非 NULL `workspace_id`；每个 tree/derived/replay 读入口 MUST 携带授权上下文并按既有合取校验（`v_grant_find_valid`／`v_grant_lock_judge`，`v8/grant/v8_grant.sql:487-534,364-479`），MUST NOT 以会话级或视图级约定代替；拒绝 MUST 落 `authz_denial_audits`（`v8/grant/v8_grant.sql:216-238`）并返回稳定 code；该写入是**授权拒绝遥测**，为不变量 25 零业务/控制写集的**唯一显式例外**（不变量 25 / §12 已同步收窄）。**禁止**：读入口无授权面（`session_events` 自身无 RLS —— `grep -rn 'ROW LEVEL SECURITY' v8/` 仅命中 `slices`/`grants`/`workspace_handles` 三表，`v8/grant/v8_grant.sql:1373-1386`）；以 caller 指定 leaf 读取兄弟分支；以 RLS 替代 slice-membership；把 `sessions.workspace_id` 的 NULL（该列由 `v8/grant/v8_grant.sql:43` `ALTER TABLE sessions ADD COLUMN workspace_id uuid` 加入，**无 NOT NULL**）留作跨租户路径。

### 0.4 首版范围

- 树构建（TREE 模式、leaf 游标、路径投影）、揭示视图、批合法性、决策层只读重放、评分对象、无损派生 DAG、策略版本与 CAS 激活、Dream-RSI 端到端 —— 全部只以**末尾追加新 SQL 文件**的方式落地。
- v8 的 `v_fork_session`（`v8/grant/v8_grant.sql:1231-1361`）与 `v_compat_fork`（`v8/compat/v8_compat.sql:497-551`）**原样保留**，仅作为「跨会话隔离/兼容」路径；v11 只替换「树构建」这一用途。
- 元层（策略作者 agent）**不在系统内**（§9）。
- 每节点 live 文件系统**不做**（§5）；节点世界 = 不可变 artifact + 已录观测。
- v11 不改 v10 规格、不实现 v10（v10 零代码）；凡引用 v10 对象处均为「复用其**语义**，v11 自建等价对象」。

## 1. 核心机制与术语〔D2〕

### 1.1 节点、分支、路径

一个 TREE 会话是一棵挂在**同一条 `session_events` 日志**上的树：

| 概念 | v11 表示 | 来源 |
|---|---|---|
| 节点身份 | `session_events.entry_id`（uuid，稳定树身份，`UNIQUE(session_id, entry_id)`） | 对齐 pi `session-manager.ts:46-51` 的 `{id, parentId}` |
| 父指针 | `session_events.parent_entry_id`（nullable，自引用复合 FK，NULL = 根/线性） | 同上 |
| 创建序 | `internal_semantic_ordinal`（= 论文 `CellMeta.seq`，`txt:1029`） | 不变量 22 |
| 游标 | `session/leaf` audit 事件（`payload.target_entry_id`），CURRENT leaf = `max(seq)` 的 `session/leaf` 事件之 target；无此事件时 leaf = `max(seq)` 的**普通事件**（**〔审阅修正〕blocking：MED-4 —— 「普通事件」= `event_class <> 'audit'` 的已录行**，含建会话时的 root 行 `session/tree_root`（observational，§3.1）；**非 `session/leaf` 的其它 `audit` 行既不算普通事件、也不被当作 semantic**，故 root 行即初始 leaf；fold 语义，对齐 pi `jsonl-storage.ts:109-111`） | 不变量 24 |
| 上下文 | leaf→root 路径，序 = 读时 `row_number()` | 不变量 21/23 |
| 分支 | 改变 leaf 游标（O(1) 追加；**零行复制**、前缀物理共享） | 不变量 24 |

关键性质：**前缀是物理共享的**（同一 event 行被多条路径可达），因此「一次在线 rollout 产生的树」与「重放读取的树」是同一批行，不需要构造步骤。论文把「构造重放模拟器」列为独立阶段（`txt:107-111`）但正文未给任何算法 —— 在日志基底上它退化为**选一个 cutoff**，v11 据此**不把它当独立计算步骤**，而是重定义为一次快照/世代选择（不变量 9 的应用）。

**「分支不便宜，只有重放便宜」**（明写规则）：T1 的分支写是 O(1)，但每次路径读取仍要付一次递归 CTE（§3.4）；T4 的重放便宜，是因为它只读已录结果。MUST NOT 把整个环宣传为免费（对齐 IANT 的 cost-split 陈述）。

### 1.2 三棵树，v11 做哪棵

| 树 | 含义 | v11 处置 |
|---|---|---|
| A. 会话树 | 分支对话历史 | **做**（§3）：pointer-fork，O(1) 分支，路径即上下文 |
| B. 无损压缩 DAG | 可恢复派生节点 | **做**（§4）：派生边表 + drill-back，原材料不删 |
| C. 工作区快照树 | 每节点可恢复文件系统 | **不做 live handle**（§5）：降级为不可变 artifact + 已录观测；可选 CoW/`workspace_handles` 前沿加速器，必须有非 handle 兜底 |

三棵树**不得混为一谈**。特别地：A 的 fork 是 v11 新增的 pointer 语义，MUST NOT 复用 v8 `v_fork_session` 的 COPY 语义（§3.5）；C 在 v8/v10/pi 三处被独立拒绝（`v8/grant/v8_grant.sql:1328-1329` 显式不继承 live handle；`v10-dev.md:53` 与 `:380`；pi `quickstart.md:84` 要求用户自备 checkpoint），v11 不逆势开洞。

### 1.3 「prefix-only」在 v11 下的确切含义

论文的硬约束（`txt:1130-1135`）：「决策只能用已揭示观测、`baseline_score`、legal sets、结构性 meta、helper signals；绝不能用未揭示分数、真实最优、硬编码获胜 cell id、绝对分数目标或内部 trace 数据。」

v11 的实现定义（三件套，缺一不可）：

1. **集合定义** = episode 级派生（不变量 30）：`revealed(episode)` = 该 episode 各轮 `v_replay_probe` 返回的节点集之并 = 不变量 30 的**已观测节点集 `O`**（**不是** frontier `A(T^{m,k})`）；`unrevealed = recorded \ revealed`；`n_revealed = |O| − 1`。
2. **可见性强制** = **权限边界，不只是查询形状**：策略执行体（policy harness）MUST 以**最小权限角色**运行 —— 仅 `EXECUTE` 于 `v_tree_revealed` / `v_tree_legal_actions` / `v_replay_probe` / `v_tree_context` / **`v_node_score_read`** 五个具名函数，**`session_events` 无表级权限**（该角色的表级权限**全部为零**，见 §2.4 的零权限默认拒绝），`v11_node_scores` 的可见性由不变量 25 的读集边界与 §7.4 的授权谓词决定。该角色借用 v8 既有 `v8_worker` 的形状（`LOGIN NOBYPASSRLS`、无业务表 DML，`v8/grant/v8_grant.sql:1364-1386` 邻域），但**表级权限更严**（v11 角色零表级权限、仅五个具名函数的 `EXECUTE`；§2.4）。**在线阶段同款**：在线 rollout（§6.6）不引入第二阶段接口 —— 策略执行体读 `v_tree_legal_actions`（合法集由**在线会话的当前观测子树**派生）、再经 **O 命令 `v_rollout_batch`** 落批；策略角色自身**不得**写 `v11_probe_batches`/`v11_rollouts`（同 `session_events`：无 DML）。**〔审阅修正〕** 三位审阅者独立指出：把整棵树放在同一条 `session_events` 日志里、只用 `v_tree_revealed` 这个**视图谓词**做边界，是一处遗漏即全泄漏（一次普通 `SELECT payload FROM session_events WHERE session_id=<world>` 就能读到终局节点的未揭示 score）。故本版把边界抬到**权限层**：① 最小权限角色（**零表级权限的默认拒绝**，覆盖**全部 v11 表**与 `session_events`；§2.4，并附 `REVOKE SELECT ON session_events, v11_node_scores, v11_node_artifacts` 作兜底）；② **具名读入口** **`v_node_score_read(auth, batch_id, entry_id[]) → Observation[]`** 做逐节点授权（可见 = 该节点在**当前 episode 揭示集**之内，否则稳定拒绝 `SCORE_NOT_REVEALED`、空返回；**其余对 `v11_node_scores` 的直接 SELECT 路径一并以 REVOKE 关闭**，见 §2.4/§7.4 —— 本项在第三轮之前**只被要求、从未被点名**，现补齐）；③ 拒绝落 `authz_denial_audits`（不变量 25 的唯一显式例外，见不变量 25/§12）—— **该稳定拒绝 code 与 audit 行只由上述具名读入口产生**；**裸 `SELECT` 表**不经这些入口，被 PG 权限层直接拒绝（原始 `42501`，**无稳定 code、无 audit 行**，与 §2.4/T5c/T9d 同形）。若实现阶段任意一环延期，MUST 按 §13.3 登记为偏差，MUST NOT 静默降级为「约定」。
3. **重放入口自校验** = 不变量 26：`v_replay_probe` 只接受已持久化的合法 `batch_id`，并在同事务内重算 `A(T)`；任一 cell 非当前合法 → `REPLAY_CELL_NOT_LEGAL`、零返回。

### 1.4 重放转移函数（确定性 Child）

对齐论文 `txt:251-272`，**逐条**：

- `v ≠ r`：返回 `v` 的**唯一**已录子节点（若存在、且尚未揭示；「已录子节点」按不变量 24 定义为 `event_class <> 'audit'`）。单子节点约束（不变量 24）使之唯一 —— 该唯一性只对**非根** `v` 成立，root 走下一行。
- `v = r`：返回 `r` 在揭示集**之外**、**最早创建**的子节点 —— 排序键 = `internal_semantic_ordinal` 升序（= 论文「earliest-created」与 `CellMeta.seq`）。**本行的排序键即要求 `r` 可拥有多个已录子节点**（D6 的 root 例外位，§2.1 D8）；若无该例外，`r` 至多一个子节点，本行退化、`\|A(T)\| ≡ 2`。
- 无已录续接：返回空集。
- 一轮 = 一个非空批；终止于空批、`k = K2`、或揭示集 = 已录集。

这个函数是**纯函数**：给定（完整已录树, 当前揭示子集, 批）→ 下一个揭示子集；无外部 IO、无副作用、无 evaluator 调用。它在 SQL 层是只读入口，在可复现性上等价于一个确定性查询（§7）。

### 1.5 术语固定

| 术语 | 唯一含义 |
|---|---|
| TREE / LINEAR 会话 | `sessions.session_mode` 的闭合域；LINEAR = v8 既有语义逐字节不变，TREE = v11 树语义 |
| 分支 | leaf 游标的追加式移动，**不是** v8 `v_fork_session` 的跨会话复制 |
| 揭示集 / episode | 前者为 §1.3 第 1 条的 episode 级派生集合；后者为一次「策略 × 世界」的重放会话身份 |
| 世界 / world | 一棵已冻结的历史发现树，以 `(world_session_id, world_through_entry)` 定点 |
| 世界集 / world set | 离线评估所覆盖的 t 棵历史树的**冻结枚举**（§8.2）；不全覆盖即失败封闭 |
| 探针 / probe | 一次 `(node, policy)` 的确定性 Child 展开，零执行成本 |
| 在线产出 / probe execution | 一次真实（或 fake）generation-evaluation attempt 的**非 step** 执行路径（§6.4），产出 `v11_node_scores`/`v11_node_artifacts` |
| 在线 rollout / rollout | 论文 loop 的第一阶段：**active 策略**在 `K1` 轮上限内按 `A(T;W)` 选 node batch 并真执行（§6.6）；身份 = `v11_rollouts.rollout_id`（由 `v_rollout_open` 创建并固定 `policy_id`/`w`/`beta`），批的生产者 = O 命令 `v_rollout_batch` |
| 决策层重放 oracle | `v_replay_probe`，与 v10 `inspect_assembly` 刻意区分 |
| 策略 / policy | 不可变版本化产物，key = `(generation, policy_version)` |
| 元循环 / meta loop | online rollout → offline dreaming → redeploy；**策略作者 agent 在系统外** |

## 2. 数据平面与权限〔D2；写集 D3〕

### 2.1 schema 增量

全部增量以「末尾追加新 SQL 文件（`v8/tree/*.sql`）+ 对新文件里的 `ALTER`／新表」落地，**MUST NOT 编辑任何冻结 v8 SQL**。仓内先例：`v8/stream/v8_stream.sql:37-40` 就是用 `ALTER TABLE session_events ADD COLUMN stream_id/chunk_index/observation_ordinal` 给冻结表加列，并被 G9a/G9b 全绿验收。新列一律带 DEFAULT，使既有显式列 `INSERT` 无需改动即通过。

**对冻结表的 ALTER（`D*.sql` 之一，建议 `v11_schema_delta.sql`）**

| # | 增量 | 依据 / 备注 |
|---|---|---|
| D1 | `ALTER TABLE session_events ADD COLUMN entry_id uuid NOT NULL DEFAULT gen_random_uuid(), ADD COLUMN parent_entry_id uuid` | `gen_random_uuid()` 仓内广泛使用（`v8/plugin/v8_plugin.sql:72,121,580`；`v8/tools/v8_tools.sql:517`）。`parent_entry_id IS NULL` = 根/线性 |
| D2 | `CREATE UNIQUE INDEX session_events_entry_id ON session_events(session_id, entry_id)` | 稳定树身份 |
| D3 | `ALTER TABLE session_events ADD CONSTRAINT session_events_parent_entry_fk FOREIGN KEY (session_id,parent_entry_id) REFERENCES session_events(session_id,entry_id) DEFERRABLE INITIALLY DEFERRED` | 复用既有复合 PK 模式（`v8/schema/v8_schema.sql:158`）；DEFERRABLE 使同事务「父后再插子」不受顺序限制 |
| D4 | `ALTER TABLE sessions ADD COLUMN session_mode text NOT NULL DEFAULT 'linear' CHECK (session_mode IN ('linear','tree'))` | 默认 linear ⇒ 既有会话与 `v_fork_session` 子会话语义逐字节不变。**`trg_sessions_initial_row` 只校验既有列**（`v8/schema/v8_schema.sql:48-74`），新列不在其列表 ⇒ 无需改动 |
| D5 | `session_mode` **写一次**：BEFORE UPDATE 触发器，一旦该会话已有任一 `session_events` 行即拒绝修改 | **〔审阅修正〕** `session_mode` 若无此约束则可被 `UPDATE` 自由翻转（该列不在初始行触发器检查列表内），从而让一个 LINEAR 会话被误标为 TREE 或反向。对齐 v8 的 write-once 手法（`effect_requests` 元数据冻结触发器，`v8/schema/v8_schema.sql:291-312`） |
| D6 | `CREATE UNIQUE INDEX session_events_single_child ON session_events(session_id, parent_entry_id) WHERE parent_entry_id IS NOT NULL AND NOT parent_is_tree_root AND event_class <> 'audit'` | 不变量 24 的单子节点约束**只作用于非根节点**：`NOT parent_is_tree_root` 把「root 的直接子节点」排除在唯一性之外，使 root 可开任意多分支（`session/leaf` 等 audit 事件不占子节点位）。**〔审阅修正〕blocking** 原谓词不含 root 例外 ⇒ root 的已录子节点至多一个 ⇒ 已录树退化为单链、`\|A(T)\| ≡ 2`、批势 ≤ 2、b2 并行奖励被结构性封顶 —— 与不变量 24「分支建模为 root 的子节点」、§1.4 v=r 的「earliest-created 子节点」排序键、§6.2「每条已开分支至多一个 frontier」、论文 `txt:269,1101` 四处同时冲突 |
| D7 | **模式门触发器**：BEFORE INSERT ON `session_events`（`session_mode` 经 `NEW.session_id` 查 `sessions` 取得），**四分支**：**(A)** `session_mode='tree'` 且 `semantic_input_ordinal IS NOT NULL` → 拒 `SEMANTIC_ORDINAL_FORBIDDEN_IN_TREE`；**(B)** `session_mode='tree'` 且 `coalesce(current_setting('v11.tree_append', true), '') <> NEW.session_id::text` → 拒 `TREE_FOREIGN_APPEND`；**(B2)**（**〔审阅修正〕blocking：第三轮新增**）`session_mode='tree'` 且 `NEW.parent_entry_id IS NULL` 且**该会话已存在 NULL-parent 行** → 拒 `TREE_SECOND_ROOT`（**只由 `NEW` + 一次子查询判定**，与事务状态无关；理由见下）；**(C)** `session_mode='linear'` 且 `coalesce(current_setting('v11.tree_append', true), '') = NEW.session_id::text` → 拒 `TREE_APPEND_ON_LINEAR_SESSION` | **〔审阅修正〕** 冻结的 `v_append_events` 白名单/ordinal 块（`v8/events/v8_append.sql:485-556`）**只测 event_type，不咨询任何 mode 列**。没有本触发器时：对 TREE 会话调用冻结的 `v_append_events(T, {event_type:'user/message', semantic_input_ordinal:7})` 会被接受，产出一行 `parent_entry_id IS NULL` 的**第二根**，而 `v_tree_context` 沿 `parent_entry_id` 走路 → 该行在**任何路径上都不可达**，真实用户输入被静默丢弃、揭示集出现两个根。本触发器把该状态变成稳定拒绝。**只设分支 (A) 不够（blocking / high 再次收口，两处新审阅缺陷）**：① **observational 追加** —— `public_append_types@v1` 的 `assistant/chunk`、`session/heartbeat` 是 `observational` 类型，而 `session_events_ordinal_class_check`（`v8/schema/v8_schema.sql:164-178`）强制 observational/audit 行**两个 ordinal 皆 NULL**，故分支 (A) 对它们**永不触发**，冻结 facade 仍能往 TREE 会话插出第二个 `parent_entry_id IS NULL` 行；② **冻结 internal-ordinal 写者** —— 八处 `coalesce(max(internal_semantic_ordinal),0)+1` 分配点若被调用于 TREE 会话，写的是 `internal_semantic_ordinal` 而非 `semantic_input_ordinal`，分支 (A) 同样不触发。故加**分支 (B)**：任何写入 `session_mode='tree'` 会话的行，除非同事务内已由 v11 的 tree 派生路径置过该会话的 `v11.tree_append` 标记，一律稳定拒绝 —— 这把「TREE 会话的第二根」整类状态（semantic / observational / internal-ordinal / 直接 DML）压成**事务级**单点强制。标记置入者 = `v_create_tree_session`（写 root 行）、`v_tree_append`、`v_tree_set_leaf`（三者皆同事务 `set_config`）。**但 (B) 单独不足（〔审阅修正〕blocking：第三轮收口）**：`set_config(..., true)` 是**事务作用域**的，同一事务内**后到**的其它写者会继承该标记。**具体反例**：冻结闭包路径 `v8/cancel/v8_closure.sql:390-399` 的 `turn/end` INSERT 用**显式列清单**（不含 `entry_id`/`parent_entry_id`）⇒ `parent_entry_id` 取 DEFAULT NULL，其 ordinal 写的是 `internal_semantic_ordinal`（非 `semantic_input_ordinal`）⇒ 分支 (A) 亦不触发。于是一个**先调 `v_tree_append`/`v_tree_set_leaf`、再在同一事务内走 `v_complete_effect`/turn-end 闭包**的事务，能在 tree 会话里插出**第二个 NULL-parent 行** —— 正是本行理由开头描述的失败（「该行在任何路径上都不可达，真实用户输入被静默丢弃」）。(B) 是**事务状态代理**，不是对「本行是不是根」的判定，故不能单独承担该保证。**故补 (B2)**：把「每 tree 会话至多一个 NULL-parent 行」做成**由 `NEW` + 一次子查询可判定**的 per-row 性质（root 行插入时该行自身尚不可见，故 root 通过；任何后续 NULL-parent 行必被拒），不再依赖事务状态。**残余假设（如实写出）**：`session_events` 的删除/裁剪被 `trg_session_events_append_only` 禁止，故「该会话已存在 NULL-parent 行」单调为真。**(A)+(B)+(B2)+(C) 合起来**才是 §3.1「root 是该会话唯一 `parent_entry_id IS NULL` 事件」的 DB 级执行点。**分支 (C) 的判定形必须可判定（blocking）**：行级 BEFORE INSERT 触发器**只看得见 `NEW`**，无法判定「该行来自 tree 派生路径」；若按字面把该限定词换成「会话模式 + 该列非空」，则**八处冻结 ordinal 分配点的正常路径被全部误伤**——`v8/effect/v8_effect.sql:1516,1700,1950,2114`、`v8/tools/v8_tools.sql:523`、`v8/cancel/v8_closure.sql:388`、`v8/retry/v8_takeover.sql:410`、`v8/repair/v8_repair.sql:333` 全部在 LINEAR 会话上写 `internal_semantic_ordinal`（句式 `SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1`，已逐点核对），每一次 turn/end、tool/result、cancel、repair 都会被拒，零回归门（T0⑥、§10.3）当即可预见地变红。(B)、(B2) 与 (C) 的分工：(B2) **例外地不用 GUC**，只用 `NEW` + 一次子查询；`v_create_tree_session`/`v_tree_append`/`v_tree_set_leaf` 在**同事务内** `set_config('v11.tree_append', session_id::text, true)`，由 (B) 与 (C) 相对 `NEW.session_id::text` 判定（**(C) 因此与 ordinal 无关**，覆盖 tree 派生命令误落在 LINEAR 会话上的情形，含 `session/leaf` audit 行 —— 该行两 ordinal 皆 NULL，旧措辞以 `internal_semantic_ordinal IS NOT NULL` 为条件**永不触发**）—— 这是 v8 既有的**事务局部 GUC 手法先例**（`v8_turn_end_slots_protected()` 的 `v8.slot_protected_write`，`v8/schema/v8_schema.sql:462-480`；原文的 `:291-312` 是 effect 元数据 write-once 触发器，非 GUC 先例，已更正）。**该门必须配正向与负向断言**：**正向 T1 ⑯**：LINEAR 会话跑一次 `v_complete_effect` 路径**触及的六处 ordinal 分配点**后 `internal_semantic_ordinal` 正常推进、无一被 (C) 误拒；**负向**：T1 ⑦（TREE 会话上冻结 `v_append_events` 的 **semantic 与 observational 两种**追加均被拒，不产生 NULL-parent 行）、T2k（TREE 会话上调冻结 internal-ordinal 写者 → `TREE_FOREIGN_APPEND`）、T2l（LINEAR 会话上 `v_tree_set_leaf` → `TREE_APPEND_ON_LINEAR_SESSION`）、**T2n（〔审阅修正〕blocking：同事务混写 —— tree 会话里先 `v_tree_append`，再在同一事务内走冻结闭包路径追加一条 `turn/end` → 第二个 NULL-parent 行 MUST 被 (B2) 以 `TREE_SECOND_ROOT` 拒绝）** |
| D8 | `ALTER TABLE session_events ADD COLUMN parent_is_tree_root boolean NOT NULL DEFAULT false` | **〔审阅修正〕blocking** D6 的 root 例外位。PG 部分索引谓词**不能含子查询**，故「本行的 parent 不是 root 行」无法直接表达，必须落成显式标记：语义 = **本行是某 TREE 会话 root 的直接子节点**。**由 D9 的 BEFORE INSERT 触发器在插入时计算**为 `NEW.parent_entry_id = <本会话 root_entry_id>`（`v_create_tree_session` 写下的 root 行自身恒为 false），MUST NOT 由调用方直接提供 |
| D9 | **root 例外位计算触发器**：BEFORE INSERT ON `session_events`，对 `session_mode='tree'` 且 `parent_entry_id IS NOT NULL` 的行，由触发器**自行计算并覆写** `NEW.parent_is_tree_root := (NEW.parent_entry_id = (SELECT se.entry_id FROM session_events se WHERE se.session_id = NEW.session_id AND se.parent_entry_id IS NULL))`；否则置 false。**MUST NOT 采信调用方/函数传入的值**，调用方显式传入相反值一律被覆写 | **〔审阅修正〕blocking + nit** D8 的列只有 `DEFAULT false`、无 CHECK/触发器，而 D6 的部分唯一索引谓词完全依赖它 —— 任何能 INSERT `session_events` 的写者（v8 既有多个内部写者持 INSERT 权限，如 `v8/events/v8_append.sql`、`v8/grant/v8_grant.sql`，v11 又新增 `v_tree_append`）只要把该位写成 `true`，就**绕过 D6 的单子节点唯一性**（实测：非根第二个 semantic 子节点 flag=false → 拒 `duplicate key ... se_single_child`；同一行 flag=true → 接受）。PG 部分索引谓词不能含子查询，故不能靠索引自证，必须由 BEFORE INSERT 触发器计算（触发器**可以**用子查询取本会话 root 行）。此条把「D8 声明为 MUST 但 DB 不强制」补成实际执行点。T1 加负向向量：直接 INSERT 一行 `parent_is_tree_root=true` 的非 root 子节点 → 被覆写/拒绝 |


**新增表（`v8/tree/` 下；全部 DDL 在 T0 落齐，行为按里程碑追加 —— **〔审阅修正〕** 原文「逐里程碑追加」与 §10.2 T0「全部新表 DDL 骨架一次落齐」矛盾，已更正）**

| # | 表 | 关键列 / 约束 | 语义 |
|---|---|---|---|
| T1 | `v11_tree_bindings` | `PRIMARY KEY (session_id, command_id)`、`request_hash`、`occupied_at` | **第三条 receipt 域**（不变量/§3.2 的裁定见下） |
| T2 | `v11_tree_receipts` | `UNIQUE (session_id, command_id, receipt_key_kind, receipt_key_value)` | 同上 |
| T3 | `v11_node_scores` | `PRIMARY KEY (session_id, entry_id)`、`UNIQUE (session_id, ordinal)`；`score/evaluated/valid/fail_class/error/n_valid/n_total/delta_vs_baseline/delta_vs_parent` | 字段逐一镜像论文 `Observation`（`txt:1034-1036`） |
| T4 | `v11_node_artifacts` | `PRIMARY KEY (entry_id, artifact_id, kind)`；`kind CHECK IN ('workspace_snapshot','generated_artifact','eval_program','proposal','eval_diagnostics')`；`content_sha256/byte_size/media_type/source_refs/parent_artifact_identity/world_closure_digest/closure_complete` | 节点级世界（§5）。对齐 v10 `context_artifacts` 的形状与 provenance 要求（`v10-dev.md:146,551-554`） |
| T5 | `v11_derived_nodes` | `node_id PK`；`UNIQUE (session_id, content_hash)`；无 `parent_id` | 无损 DAG 节点（§4） |
| T6 | `v11_derived_sources` | `PRIMARY KEY (node_id, source_type, source_id)`；`source_type CHECK IN ('event','node')`；**无 FK**；`source_slice_id uuid NOT NULL` | 派生边表（§4.1）。`source_slice_id` 是**〔审阅修正〕**新增：pi-lcm 的无 FK 多态边（`README.md:29`／`src/db/schema.ts:96-102`）不带租户绑定，会导致「一条边命名了消费者不可读的源，drill-back 逐字节返回它」。v11 保留多态（不破坏真 DAG），但把 slice 绑定做成 NOT NULL 列并在 build/expand 双向校验 |
| T7 | `v11_probe_batches` | `batch_id PK`；`episode_id uuid NULL`、`rollout_id uuid NULL`、`session_id`、**`round_no integer NOT NULL`**、**`width integer NOT NULL CHECK (width >= 1)`（**〔审阅修正〕**low：第三轮定义 —— `width` = 该批 cell 数 `|C|`；**终止用的空批不写本表行**，故 `>= 1` 与 §6.6 第 4 条的空批路径不冲突；`|C| ≤ W` 由 §6.2 的 BEFORE INSERT 触发器解析持久 `W` 强制，**不**由本列强制）**、`status CHECK IN ('proposed','revealed','closed')`；**`CHECK (num_nonnulls(episode_id, rollout_id) = 1)`**；**`UNIQUE (episode_id, round_no)`**、**`UNIQUE (rollout_id, round_no)`** | 批。**〔审阅修正〕blocking**：离线批 FK 到 episode、在线批 FK 到 rollout —— 原文本 `episode_id NOT NULL` 使**在线（K1）批无法持久化**（一次 rollout 不是 `(plan, candidate, world)` 重放，无 episode 可指），而 §6.6 又要求在线批只能经本表（不变量 26）。故拆成 `episode_id`/`rollout_id` **二者恰一**（`num_nonnulls = 1`）。**`round_no`（〔审阅修正〕medium）** 是 episode/rollout 作用域内的轮序，定义该 episode 各批的**确定性折叠序**（§7.3；`created_at` 不是确定性序键）。**W 的解析**经 `episode_id → v11_replay_episodes.plan_id → v11_replay_plan.w`（离线）或 `rollout_id → v11_rollouts.w`（在线）。**〔审阅修正〕high**：其目标表（`v11_replay_episodes`/`v11_rollouts`/`v11_replay_policies`/`v11_world_sets`/`v11_replay_plan`/`v11_replay_candidates`）的 **DDL 在 T0 一次落齐**，故「表定义含该列」与「该列/其目标在下一阶段落」MUST NOT 并存；T2/T3/T4/T6 只装配行为 |
| T8 | `v11_probe_cells` | `PRIMARY KEY (batch_id, cell_no)`、**`UNIQUE (batch_id, target_entry_id)`**、`target_entry_id`、`parent_leaf_entry_id`、`worker_slot` | distinct 规则由此唯一约束强制 |
| T9 | `v11_replay_episodes` | `episode_id PK`；**`plan_id uuid NOT NULL REFERENCES v11_replay_plan(plan_id)`**；**`candidate_index integer NOT NULL`**、`policy_id uuid NOT NULL REFERENCES v11_replay_policies(policy_id)`（不是 `policy_version text`）、复合 FK `(plan_id, candidate_index, policy_id) REFERENCES v11_replay_candidates (plan_id, candidate_index, policy_id)`（**〔审阅修正〕** 原文本只以 `(plan_id, candidate_index)` 为复合 FK，而 `policy_id` 是同一候选的**冗余列**，二者可发散、静默把 episode 归给错策略 —— 而 `policy_id` 正是本表声明的「评估了哪个产物」的出处、也是 §7.2 / §8.4 分组的依据；补齐三列后由 FK 强制一致，见 T14）；`world_session_id uuid NOT NULL REFERENCES sessions`；**`world_through_entry uuid NOT NULL`**；`k_star/n_revealed/v_max/reward`；**`UNIQUE (plan_id, candidate_index, world_session_id, world_through_entry)`** | V 公式落表（§7.2）。**〔审阅修正〕blocking：评估剖面从「行内属性」提升为命名对象** —— `(w,k2,b1,b2,numeric_scale,β)` 移到 `v11_replay_plan`（T13），episode 只经 `plan_id` 承载剖面，因此「一次评估」自含系数档、`argmax` 只在**同一 plan** 的候选之间可比。`policy_id` 而非 text 是因为策略以 `UNIQUE(generation, policy_version)` 为键 —— `(genA,'v1')` 与 `(genB,'v1')` 是**不同产物同一文本**，用 text 无法说清评估的是哪一个，`逐位可复现` 无从核验。**唯一键保证「每个 `(策略,世界,系数档,世界集)` 恰一条」**（原文写「每个 `(策略,世界)` 恰一条」对 7 列键为**假陈述**：同一 `(策略,世界)` 上可并存每个 `(w,k2,b1,b2)` 档各一行）；不完整覆盖 → 失败封闭（§8.2）。两项 DDL 级修正：① `world_through_entry` **MUST 为 NOT NULL** —— PG 的 `UNIQUE` 默认视 NULL 互异（未用 `NULLS NOT DISTINCT`），可空列使同一 `(policy,world)` 可插任意多条 `world_through_entry IS NULL` 的行，「恰一条」在 DDL 层不成立；② **β 的载体是 `v11_replay_plan`（T13）而非 episode 行** —— 若把 β 放在 episode 上，同一 `(plan, world)` 可因 β 不同而占多行，`(1/t)` 分母再次失义（§8.2 反例的另一形态）；episode 经 `plan_id` 继承 β，故「每 episode 内 β 固定」结构性成立（§9.3） |
| T10 | `v11_replay_policies` | `policy_id PK`；**`workspace_id uuid NOT NULL`**；`UNIQUE (workspace_id, generation, policy_version)`；**`UNIQUE (workspace_id, policy_id)`**（供 T11 的复合 FK）；`source_bytes/source_hash/created_at`；**immutability 触发器**（对齐 `v8/plugin/v8_plugin.sql:49-60`） | 不可变版本化策略产物。**〔审阅修正〕medium**：加 `workspace_id` 并纳入唯一键 —— 否则 T11 的「同 W 绑定」无机制（CHECK 不能跨表、复合 FK 需要被引用端有匹配唯一键），跨 W `activate` 只能靠约定；本行的键与 §8.1 的 `(workspace_id, generation, policy_version)` 由此统一（**全文以本行为准**） |
| T11 | `v11_policy_pointer` | `workspace_id PK`；`active_policy_id uuid`；**`FOREIGN KEY (workspace_id, active_policy_id) REFERENCES v11_replay_policies (workspace_id, policy_id)`**；`revision bigint NOT NULL DEFAULT 0` | **〔审阅修正〕medium：同 W 绑定落成真正的 DDL**。原文只写「另加复合 FK／CHECK」，而 `v11_replay_policies` 当时**既无 `workspace_id` 列、也无 `(workspace_id, *)` 唯一键**，CHECK 不能引用另一张表 ⇒ 「activate 一个属于**另一个 workspace** 的策略 → 稳定拒绝」**无机制**（v10 要求「跨 W 引用拒绝、非 NULL 目标仅可为同 W 已发布 active 代」，`v10-dev.md:644`）。现由 T10 的 `workspace_id` 列 + `UNIQUE (workspace_id, policy_id)` 与本行的两列复合 FK 共同强制：跨 W 的 `active_policy_id` 在 FK 处即被拒 |
| T12 | `v11_world_sets` | `world_set_id PK`；`frozen_at`、`member_count`、`members jsonb`（有序 `(world_session_id, world_through_entry)` 列表） | 世界集冻结枚举（§8.2）。**创建者 = O 命令 `v_replay_world_set_freeze(auth, command_id, members[]) → world_set_id`**（**〔审阅修正〕blocking：MED-5** —— 原文只有 DDL 行、**无任何创建命令**，端到端只能靠 ad-hoc DML、绕过 receipt 域；冻结时 MUST 在**命令体内**断言 `member_count = |H_t 中 status='closed' 的 v11_rollouts 树数|`，见 §8.2/T9c） |
| T13 | `v11_replay_plan` | `plan_id PK`；`world_set_id uuid NOT NULL REFERENCES v11_world_sets(world_set_id)`；`w integer NOT NULL CHECK (w >= 1)`、`k2 integer NOT NULL CHECK (k2 >= 1)`、`b1 numeric NOT NULL DEFAULT 0 CHECK (b1 >= 0)`、`b2 numeric NOT NULL DEFAULT 0 CHECK (b2 >= 0)`、`numeric_scale integer NOT NULL`、**`beta numeric NOT NULL CHECK (beta >= 0 AND beta <= 1)`**（**〔审阅修正〕medium**：论文把 β clamp 到 `[0,1]`（`txt:180`），而 `k2/w/b1/b2` 皆有 CHECK、唯独 β 无 —— 补齐；校验的是值域，不是默认值）；`revision bigint NOT NULL DEFAULT 0`、`created_at` | **〔判审 graft〕+〔审阅修正〕blocking** 把「一次离线评估」命名为对象**并自含评估剖面**。原文本只有 `(policy_id, world_set_id, revision)`，**不含四个系数**，连「一次评估用哪档系数」都无法唯一确定 ⇒ `V^m` 的分母无定义、`argmax_m V^m` 在比较**不可比**的两个数。本版把 `(world_set_id, w, k2, b1, b2, numeric_scale, beta)` 落在 plan 上；候选策略集见 T14。**β 的宿主是 plan**（§9.3）。**创建者 = O 命令 `v_replay_plan_open(auth, command_id, world_set_id, w, k2, b1, b2, numeric_scale, beta) → plan_id`**（**〔审阅修正〕blocking：MED-5**，原文无创建命令） |
| T14 | `v11_replay_candidates` | `PRIMARY KEY (plan_id, candidate_index)`；`policy_id uuid NOT NULL REFERENCES v11_replay_policies(policy_id)`；**`is_incumbent boolean NOT NULL DEFAULT false`**；`UNIQUE (plan_id, policy_id)`；**`UNIQUE (plan_id, candidate_index, policy_id)`**（供 T9 的三列复合 FK，使 episode 的 `policy_id` 不可能与候选发散）；**部分唯一索引 `UNIQUE (plan_id) WHERE is_incumbent`**（每 plan 至多一个现役候选） | **〔审阅修正〕blocking** 一个 plan 下 M 个候选策略的**显式集合**；`is_incumbent` 由创建命令在 episode 建立时从 `v11_policy_pointer` 解析并落库。论文的 `V^{m*} ≥ V^0` 只依赖「候选集包含当前策略 π^0 = π_t」（`txt:233-236,337-339`）；原文没有任何对象承载该构造，`v_policy_select` 因此可在「候选集不含现役」时静默算出无对象的 `m*`（§7.2/§9.1）。**创建者 = O 命令 `v_replay_candidate_add(auth, command_id, plan_id, candidate_index, policy_id, is_incumbent) → candidate_index`**（**〔审阅修正〕blocking：MED-5**，原文无创建命令；`is_incumbent` 由该命令在建立候选时从 `v11_policy_pointer` 解析并落库） |
| T15 | `v11_rollouts` | `rollout_id PK`；`session_id uuid NOT NULL REFERENCES sessions(session_id)`（在线 TREE 会话）；`policy_id uuid NOT NULL REFERENCES v11_replay_policies(policy_id)`（**创建时由 `v11_policy_pointer` 解析并固定**）；**`w integer NOT NULL CHECK (w >= 1)`**、**`beta numeric NOT NULL CHECK (beta >= 0 AND beta <= 1)`**；`k1 integer NOT NULL CHECK (k1 >= 1)`；`k_done integer NOT NULL DEFAULT 0 CHECK (k_done >= 0)`；`status CHECK IN ('open','closed')` | **〔审阅修正〕high** 论文 loop 第一阶段（策略驱动的在线 rollout，`txt:107-108,208-219`）的落点：`K1` 轮上限 + `rollout_id` 身份，供 §6.6 的在线决策面消费。**〔审阅修正〕blocking + medium：在线 `W` 与 `β` 的宿主** —— 离线剖面在 `v11_replay_plan`，在线没有 plan 行，故 `w`/`beta` 落在本表，**创建时写一次、之后不可 UPDATE**（§6.6；β 角色 1 = 每 episode/rollout 内固定，`txt:1149-1159`）。`policy_id` 亦为创建时固定；`v_rollout_batch` MUST 以本行 `policy_id` 为**唯一策略权威**；它 **MAY 读 `v11_policy_pointer` 但仅用于比较**（不一致 → `ROLLOUT_POLICY_STALE` 零写），MUST NOT 以所读指针作策略权威、MUST NOT 换策略（§6.6 第 3 条；〔审阅修正〕blocking：MED-2） |

**v_replay_probe 的易变等级（**〔审阅修正〕** nit）**：`v_replay_probe` / `v_tree_context` / `v_tree_revealed` / `v_tree_legal_actions` / `v_node_score_read` / `v_derived_expand` 一律 **`STABLE`，MUST NOT 标 `IMMUTABLE`**。理由：函数体读表，PG 只允许 `STABLE`；标 `IMMUTABLE` 会允许规划器跨语句常量折叠与复用结果，破坏 T4 承诺的「同一输入两次调用逐字节相等」。该断言加入 T4 的 grep 门。**〔审阅修正〕medium**：这些 `STABLE` 入口若按不变量 31 需要授权行锁，**取锁子操作 MUST 下沉到 `VOLATILE` 函数**（PG 禁止在 `STABLE` 函数体内 `SELECT … FOR UPDATE`）—— 入口只调用它；见 §7.3。

**v11_reward 是独立的 IMMUTABLE 纯函数（**〔判审 graft〕**）**：`v11_reward(v_max bigint, n_revealed bigint, k_star integer, b1 numeric, b2 numeric, numeric_scale integer) RETURNS numeric`，`IMMUTABLE`、`LANGUAGE sql`，体为论文 V 公式（§7.2）的定点实现，舍入冻结为 **round-half-even 到 `numeric_scale`**（默认 profile 值 6）。**`n_revealed` 的定义（〔审阅修正〕medium：第三轮；终轮与不变量 30 的双集拆分对齐）**：`n_revealed := |O| − 1 = |T^{m,k*}_i| − 1`（`O` = 不变量 30 的**已观测节点集**，`|O| = |T^{m,k*}_i|`），**即论文的 `N`**（`txt:287-295` 的「非根已揭示节点数」）；`v11_reward` **不再做 −1**（若 episode 列改存 `|T|`，则 MUST 在此处减 1 —— 本规范钉死为**存 `N`、不减**，T4 ①/T5f 的逐位黄金向量按此口径）。**T4/T8 的逐位可复现断言因此有一个单点实现可锁**，而不是散落在 `v11_replay_episodes` 的写路径里。**禁止**：把 V 公式只嵌在 episode 写路径里（那样「逐位一致」是对一个可自由 UPDATE 的行做断言）。

**DDL 示意（`v11_schema_delta.sql`；仅示意结构与约束，非可执行迁移——§12 明确本轮不落 DDL）**

```sql
-- D1–D3：对冻结表的 ALTER（先例 v8/stream/v8_stream.sql:37-40）
ALTER TABLE session_events
    ADD COLUMN entry_id        uuid NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN parent_entry_id uuid;
CREATE UNIQUE INDEX session_events_entry_id ON session_events (session_id, entry_id);
ALTER TABLE session_events
    ADD CONSTRAINT session_events_parent_entry_fk
    FOREIGN KEY (session_id, parent_entry_id)
    REFERENCES session_events (session_id, entry_id)
    DEFERRABLE INITIALLY DEFERRED;

-- D4：模式列（默认 linear ⇒ 既有会话语义逐字节不变）
ALTER TABLE sessions
    ADD COLUMN session_mode text NOT NULL DEFAULT 'linear'
    CHECK (session_mode IN ('linear','tree'));

-- D8：root 例外位（不变量 24；PG 部分索引谓词不能含子查询，故需显式标记）
ALTER TABLE session_events
    ADD COLUMN parent_is_tree_root boolean NOT NULL DEFAULT false;

-- D6：单子节点（不变量 24；只约束非根节点，audit 行不占子节点位）
CREATE UNIQUE INDEX session_events_single_child
    ON session_events (session_id, parent_entry_id)
    WHERE parent_entry_id IS NOT NULL
      AND NOT parent_is_tree_root
      AND event_class <> 'audit';

-- D9：root 例外位由触发器计算（不采信调用方；本会话 root 行 = parent_entry_id IS NULL 的那行）
CREATE FUNCTION v11_session_events_root_flag() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_mode text;
BEGIN
    -- LOW-5(a)：与 D9 行 prose 一致，先测 session_mode='tree'（原示意漏该谓词）
    SELECT session_mode INTO v_mode FROM sessions WHERE session_id = NEW.session_id;
    IF v_mode = 'tree' AND NEW.parent_entry_id IS NOT NULL THEN
        NEW.parent_is_tree_root := (NEW.parent_entry_id = (
            SELECT se.entry_id FROM session_events se
             WHERE se.session_id = NEW.session_id AND se.parent_entry_id IS NULL));
    ELSE
        NEW.parent_is_tree_root := false;
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER trg_session_events_root_flag
    BEFORE INSERT ON session_events FOR EACH ROW
    EXECUTE FUNCTION v11_session_events_root_flag();

-- D7：模式门触发器（四分支 A/B/B2/C；session_mode 经 session_id 查 sessions）
CREATE FUNCTION v11_session_events_mode_gate() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_mode text;
BEGIN
    SELECT session_mode INTO v_mode FROM sessions WHERE session_id = NEW.session_id;
    IF v_mode = 'tree' THEN
        IF NEW.semantic_input_ordinal IS NOT NULL THEN
            RAISE EXCEPTION 'v11: SEMANTIC_ORDINAL_FORBIDDEN_IN_TREE';
        END IF;
        IF coalesce(current_setting('v11.tree_append', true), '') <> NEW.session_id::text THEN
            RAISE EXCEPTION 'v11: TREE_FOREIGN_APPEND (session %)', NEW.session_id;
        END IF;
        -- (B2) 每 tree 会话至多一个 NULL-parent 行：只由 NEW + 一次子查询判定，
        --      与事务局部 GUC 无关，封住「同事务内后到的冻结闭包写者插出第二根」。
        --      root 行插入时自身尚不可见，故 root 通过；后续 NULL-parent 行必被拒。
        IF NEW.parent_entry_id IS NULL
           AND EXISTS (SELECT 1 FROM session_events se
                        WHERE se.session_id = NEW.session_id
                          AND se.parent_entry_id IS NULL) THEN
            RAISE EXCEPTION 'v11: TREE_SECOND_ROOT (session %)', NEW.session_id;
        END IF;
    ELSIF v_mode = 'linear'
          AND coalesce(current_setting('v11.tree_append', true), '') = NEW.session_id::text THEN
        RAISE EXCEPTION 'v11: TREE_APPEND_ON_LINEAR_SESSION (session %)', NEW.session_id;
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER trg_session_events_mode_gate
    BEFORE INSERT ON session_events FOR EACH ROW
    EXECUTE FUNCTION v11_session_events_mode_gate();
-- 注：D5（session_mode write-once）与 D7/D9 同为行为触发器，归 T1 落（T0 只建列与索引，§10.2 T0）。

-- T13：一次离线评估的命名对象（自含评估剖面：world_set + 系数档 + β）
CREATE TABLE v11_replay_plan (
    plan_id         uuid PRIMARY KEY,
    world_set_id    uuid NOT NULL REFERENCES v11_world_sets (world_set_id),
    w               integer NOT NULL CHECK (w >= 1),
    k2              integer NOT NULL CHECK (k2 >= 1),
    b1              numeric NOT NULL DEFAULT 0 CHECK (b1 >= 0),
    b2              numeric NOT NULL DEFAULT 0 CHECK (b2 >= 0),
    numeric_scale   integer NOT NULL,
    beta            numeric NOT NULL CHECK (beta >= 0 AND beta <= 1),
    revision        bigint  NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- T14：M 个候选策略（含现役标记；每 plan 至多一个现役）
CREATE TABLE v11_replay_candidates (
    plan_id         uuid NOT NULL REFERENCES v11_replay_plan (plan_id),
    candidate_index integer NOT NULL CHECK (candidate_index >= 0),
    policy_id       uuid NOT NULL REFERENCES v11_replay_policies (policy_id),
    is_incumbent    boolean NOT NULL DEFAULT false,
    PRIMARY KEY (plan_id, candidate_index),
    UNIQUE (plan_id, policy_id),
    UNIQUE (plan_id, candidate_index, policy_id)
);
CREATE UNIQUE INDEX v11_replay_candidates_one_incumbent
    ON v11_replay_candidates (plan_id) WHERE is_incumbent;

-- T9：episode（剖面经 plan_id 继承；world_through_entry 必须 NOT NULL）
CREATE TABLE v11_replay_episodes (
    episode_id           uuid PRIMARY KEY,
    plan_id              uuid NOT NULL REFERENCES v11_replay_plan (plan_id),
    candidate_index      integer NOT NULL,
    policy_id            uuid NOT NULL REFERENCES v11_replay_policies (policy_id),
    world_session_id     uuid NOT NULL REFERENCES sessions (session_id),
    world_through_entry  uuid NOT NULL,
    k_star integer, n_revealed bigint, v_max bigint, reward numeric,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (plan_id, candidate_index, policy_id)
        REFERENCES v11_replay_candidates (plan_id, candidate_index, policy_id),
    UNIQUE (plan_id, candidate_index, world_session_id, world_through_entry)
);

-- T10：不可变版本化策略产物（workspace 绑定纳入唯一键，供 T11 的复合 FK）
CREATE TABLE v11_replay_policies (
    policy_id    uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    generation   text NOT NULL,
    policy_version text NOT NULL,
    source_bytes bytea NOT NULL,
    source_hash  text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, generation, policy_version),
    UNIQUE (workspace_id, policy_id)
);

-- T11：唯一 active 指针（写者闭集仅三；同 W 绑定由复合 FK 强制；revision 单调由 CAS 保证）
CREATE TABLE v11_policy_pointer (
    workspace_id      uuid PRIMARY KEY,
    active_policy_id  uuid,
    revision          bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    last_operator     text,
    last_changed_at   timestamptz,
    last_command_ref  text,
    FOREIGN KEY (workspace_id, active_policy_id)
        REFERENCES v11_replay_policies (workspace_id, policy_id)
);
```

### 2.2 ordinal 权威：before / after

**〔审阅修正〕** 这是 v11 唯一一处「语义权威位移」，逐字写清：

| | LINEAR（不变） | TREE（新） |
|---|---|---|
| 谁提供 semantic ordinal | 调用方，按逻辑输入序单调（`v8/events/v8_append.sql:535-556`） | 调用方 **MUST NOT** 提供（`SEMANTIC_ORDINAL_FORBIDDEN_IN_TREE`）；DB 派生 `internal_semantic_ordinal` |
| 派生公式 | 不适用（公开 space） | 与冻结八处**同一公式** `coalesce(max(internal_semantic_ordinal),0)+1`，持会话行锁 |
| 唯一性载体 | `session_events_public_ordinal`（`schema:182-184`） | `session_events_internal_ordinal`（`schema:185-187`） |
| ordinal 的含义 | 调用方逻辑输入序 | **创建序见证**（= 论文 `CellMeta.seq`），用于 Child 的「earliest-created」排序 |
| 上下文顺序 | ordinal（既有） | **leaf→root 路径**（不变量 21/23）；ordinal 不再是上下文序 |

**消费方迁移注记（破坏性重定位点，必须显式）**：TREE 会话的公开输入（`user/message`、`turn/start`、`agent/inject`）落在 **internal ordinal space**。任何现存或外部消费方以 `semantic_input_ordinal IS NOT NULL` 选取公开 semantic 输入，对 TREE 会话会**静默返回零行**。v11 MUST 在 §13 台账与 README 边界句写明此点；这不是可以「兼容地」糊过去的实现细节（**〔审阅修正〕** 保留该让步并显式声明它）。

**双 ordinal 空间未被合并**：`session_events_ordinal_class_check`（`schema:164-178`）未改；两个部分唯一索引未改；两空间仍互不交叉检查（v8-dev.md 既有）。v11 只改变**TREE 下公开语义输入占用哪个空间**，不改变约束本身。

### 2.3 不可变性与保护触发器

**〔审阅修正〕** v8 的不可变性由**触发器**承载（12 个，例如 `trg_session_events_append_only`，`v8/schema/v8_schema.sql:190-199`；`trg_effect_requests_metadata_immutable`，`schema:291-312`；`trg_plugin_specs_immutable`，`v8/plugin/v8_plugin.sql:49-60`）。v11 的**每一张新表**（15 张）MUST 采纳同一手法（下表逐表覆盖，无遗漏），否则 T 系列「逐位一致」是对任何人可改的数据作断言：

- `v11_replay_policies`：BEFORE UPDATE OR DELETE → 拒（不可变产物）。
- `v11_node_scores`／`v11_node_artifacts`／`v11_derived_nodes`／`v11_derived_sources`／`v11_world_sets`：BEFORE UPDATE OR DELETE → 拒（append-only）。
- **`v11_tree_bindings`／`v11_tree_receipts`：BEFORE UPDATE OR DELETE → 拒（第三条 receipt 域同样 append-only；否则幂等 binding 可被改写）。〔审阅修正〕high：补全遗漏。**
- **`v11_probe_cells`：身份列 append-only + `worker_slot` 受控可写〔审阅修正〕high（终轮）** —— 这一条承担不变量 26：`v_replay_probe` 校验的批组成若可在校验后被 UPDATE，校验即失效。故按**列作用域**落地：身份列 `batch_id`/`cell_no`/`target_entry_id`/`parent_leaf_entry_id` 的任何 UPDATE 与整行 DELETE 一律拒（BEFORE UPDATE／BEFORE DELETE 触发器，镜像 `v11_probe_batches` 同款手法，`v8/schema/v8_schema.sql:462-480`）；**`worker_slot` 是派发期赋值、不属于批组成**，由 §6.3 的 `v_batch_dispatch` 在 `proposed→revealed` 迁移的同一事务内写入一次，非该迁移的 `worker_slot` UPDATE 一律拒。**〔审阅修正〕（终轮）blocking** —— 原文本把本表定为**无条件** append-only，与 §6.3「`v_batch_dispatch` 一次把 ≤W 个 cell 映射到 `worker_slot`」**直接冲突**：`worker_slot` 是本表列（§2.1 T8），故该命令的声明职责在原文下**不可能执行**，T2 中经该命令的 fixture 也无法运行。列作用域既保住不变量 26 的意图（**批组成**不可变），又使派发可写。
- **`v11_replay_plan`／`v11_replay_candidates`：BEFORE UPDATE OR DELETE → 拒（剖面与候选集是冻结对象）。〔审阅修正〕high**（与 T4 ⑪ 的「`beta` / `policy_id` 建立后不可 UPDATE」同款）；**因此 T13 的 `revision bigint DEFAULT 0` 只作创建时字面值，本规范不定义任何 UPDATE 路径**。
- **`v11_rollouts`：闭合迁移触发器〔审阅修正〕high** —— `k_done` 单调不减、`status` 仅 `open→closed`、`status='closed'` 后 `k_done`/`status` MUST NOT 再改（K1 上限与 §6.6 第 3 条的 DDL 层执行点）。**`k_done` 的唯一写者 = `v_rollout_batch`（§6.6 第 3 条）** —— 它在写一条**非空**批的同一事务内把 `k_done` 自增 1；**空批不写批行、也不自增**（§6.6 第 4 条）。**〔审阅修正〕（终轮）blocking** —— 原文本只约束「单调不减」而**未命名任何写者**：若 `k_done` 恒为 0，第 2 个在线非空批重算出 `round_no = 1`，撞 `UNIQUE (rollout_id, round_no)`（§2.1 T7）；且 `k_done = k1`（`k1 >= 1`）**永不可达**，`ROLLOUT_ROUND_LIMIT_REACHED` 永不触发，使 T4e（写 `K1` 个非空批 → 再传第 `K1+1` 个）**必不能通过**。
- `v11_probe_batches`：**身份列 append-only + `status` 闭合迁移**（**〔审阅修正〕blocking：第三轮补** —— 身份列 `episode_id`/`rollout_id`/`session_id`/`round_no` **不可变**：它们定义 §7.3 第 2 条的折叠序与 §6.6 第 7 条的轮计数，`UPDATE v11_probe_batches SET round_no = …` 会重排折叠序、改变 `v_replay_probe` 校验的 `A(T)`（正是不变量 26 禁止的那类变更），`DELETE` 则直接抹掉一轮）。实现：**列作用域 BEFORE UPDATE 触发器 + BEFORE DELETE 触发器**（镜像 `v8_turn_end_slots_protected`，`v8/schema/v8_schema.sql:462-480`）拒绝对四个身份列的任何 UPDATE、以及对该表的任何 DELETE；**`status` 单独**由闭合迁移触发器管（对齐 v8 五状态表手法，`v8/grant/v8_grant.sql:771-803`）：仅 `proposed→revealed` 与 `revealed→closed` 两条边（**〔审阅修正〕（终轮）**：删除原文闭合表的 `proposed→closed` 边 —— 它原被注为「空批即时终止」，但 §11 T7 与 §6.6 第 4 条钉死**空批不写 `v11_probe_batches` 行**，故该边**无任何写者**，从闭合表删除）；其余边 MUST NOT 执行。**禁止**：把整行当作可 UPDATE（那样 `round_no` 可被改写、批组成可在校验后被换）。**状态迁移写者（〔审阅修正〕blocking：LOW-4）** —— 原文定义了三态与闭合迁移表却**未命名任何写者**（`v_rollout_batch`/`v_replay_batch` 只 INSERT `proposed` 行，`v_replay_probe` 零业务写），使 `revealed`/`closed` 两态**不可达**、T7f 的非法迁移门失去对照。本版钉死：`proposed→revealed` 由 `v_batch_dispatch`（§6.3）在同一事务内写入；`revealed→closed` 由离线 `v_replay_settle`（episode 结算）与在线 rollout 关闭路径写入。**空批不写本表行**（§6.6 第 4 条 / §11 T7），故**没有** `proposed→closed` 这条边。
- `v11_replay_episodes`：**身份列在重放开始时插入、结果列恰一次迁移**（见下「episode 生命周期」）。
- `v11_policy_pointer`：可 UPDATE（它就是可变指针），但**写者闭集仅三**（不变量 27），由受控函数而非直接 DML 写入；`revision` 单调（CHECK + CAS）。
- **`session_events` 的保护触发器（D5/D7/D9，§2.1）**：D5（`session_mode` write-once）、D7（模式门）、D9（`parent_is_tree_root` 计算）三者都不在 T0 落；**归 T1**（T0 只建列与索引），见 §10.2 T0 的范围句。

**episode 生命周期（〔审阅修正〕blocking：与「批在重放期 FK 到 episode」的时序冲突）**：原文让 `v11_replay_episodes` 的结果列在**结算时一次性 INSERT**，同时让 `v11_probe_batches.episode_id` 在**重放期** FK 到 episode 行 —— 二者不能同时成立（round 1 时 episode 行尚不存在，批的 FK 目标为空）。裁定：

1. **开启**：O 命令 `v_replay_episode_open(auth, plan_id, candidate_index, world_session_id, world_through_entry, command_id) → episode_id` 在重放开始时**只写身份列**（`plan_id`/`candidate_index`/`policy_id`/`world_session_id`/`world_through_entry`），结果列 `k_star/n_revealed/v_max/reward` 留 NULL；
2. **结算**：O 命令 `v_replay_settle(auth, episode_id, command_id)` 写一次结果列，由 BEFORE UPDATE 触发器强制 `NULL→非 NULL` 的**恰一次**迁移（结果列已非 NULL 再写 → 稳定拒绝 `EPISODE_ALREADY_SETTLED`）；
3. 身份列建立后不可 UPDATE；`reward` 的「写入即定型」改述为「结果列恰一次迁移即定型」。

T4 加该两条命令的验收与负向（重复结算 → 拒）。

### 2.4 权限与 RLS

- **不新增 `session_events` 的 RLS 策略**：v11 无法以 RLS 分离分支（所有分支共享一个 `session_id`），且 v11 不主张 RLS 参与前缀边界。前缀边界 = 不变量 30（episode 级揭示集）+ 不变量 31（逐入口授权）+ §1.3 第 2 条（最小权限角色）。
- **最小权限策略执行体角色**（新角色，命名自定，建议 `v11_policy_runner`）：`LOGIN NOBYPASSRLS`；**机制 = 零表级权限的默认拒绝** —— 该角色**以「无任何表级权限」创建**（PG 中新建角色对既有对象默认无权限），MUST NOT 对其 `GRANT` 任何表级权限（SELECT/INSERT/UPDATE/DELETE 一律无），故对**全部 v11 表**（`v11_tree_bindings`/`v11_tree_receipts`/`v11_node_scores`/`v11_node_artifacts`/`v11_derived_nodes`/`v11_derived_sources`/`v11_probe_batches`/`v11_probe_cells`/`v11_replay_episodes`/`v11_replay_policies`/`v11_policy_pointer`/`v11_world_sets`/`v11_replay_plan`/`v11_replay_candidates`/`v11_rollouts`）以及 v8 的 `session_events` 一律默认拒绝（**〔审阅修正〕（终轮）**：原文只 `REVOKE` 三张表，使 §6.6 第 8 条/§9.3 断言的「无 `v11_replay_*` 表级权限」**无实施点**；现改为覆盖全部表的默认拒绝 + 逐表点名）；另**显式** `REVOKE SELECT ON session_events, v11_node_scores, v11_node_artifacts` 作**兜底**（即使上游误 GRANT 也在本行撤销）；**仅** `GRANT EXECUTE` 于 `v_tree_revealed`/`v_tree_legal_actions`/`v_replay_probe`/`v_tree_context`/**`v_node_score_read`** 五个具名函数；无业务表 DML。**〔审阅修正〕blocking（第三轮）**：原文本只 revoke `session_events`，**从未 revoke 两张 `v11_node_*` 表、也从未点名任何 score 读入口**，故 §1.3 ②/§7.4 的 `SCORE_NOT_REVEALED` 边界**没有实施点**：同一角色要么能直接 `SELECT v11_node_scores`（边界洞），要么拿到裸权限错误而非规范承诺的稳定 code（违反 §1.3 第 2 条末句「任一环延期 MUST 按 §13.3 登记为偏差，MUST NOT 静默降级为约定」）。现补齐具名入口 **`v_node_score_read(auth, batch_id, entry_id[]) → Observation[]`**（**`STABLE`**，逐节点判定可见性；其取锁授权子操作按 §7.3 下沉到 `VOLATILE` 辅助函数），并 `REVOKE SELECT` 关闭两条直接读路径。对齐 `v8_worker` 的既有形状（`v8/grant/v8_grant.sql:1364-1386` 邻域与 G10 gate 契约）。**MUST NOT** 依赖 `GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public` 的毯式授权（`v8/grant/setup_db.py:36` 的既有做法在 v11 里 MUST 收窄为逐函数列举），否则读入口在授权检查之外仍可被调用。
- **`workspace_id` 非空**：TREE 会话创建入口 MUST 校验 `workspace_id IS NOT NULL`（不变量 31）。理由（**〔审阅修正〕**）：`v_grant_lock_judge` 在 session 的 `workspace_id` 为 NULL 时**整条跳过租户合取**（`v8/grant/v8_grant.sql:448-452`；`v_grant_find_valid` 仅当非 NULL 时过滤，`:514`；而该列可空，`v8/grant/v8_grant.sql:43` 无 NOT NULL），于是「无 workspace 的 tree 会话」上一条跨租户 grant 变得可用。
- **读拒绝遥测**：每个 tree/derived/replay **具名读入口** MUST 有稳定拒绝 code 并把拒绝路由进 `authz_denial_audits`（`v8/grant/v8_grant.sql:216-238`）。**（〔审阅修正〕（终轮）：裸 `SELECT` 表不经这些入口，被 PG 权限层直接拒绝 —— 原始 `42501`、无稳定 code、无 audit 行；稳定-coded 拒绝因 REVOKE/默认拒绝而**不可达**，这正是 §1.3 第 2 条末句与 T5c/T9d 的含义。）****〔审阅修正〕** 原文的读入口无任何拒绝码、也无拒绝记录 —— 一旦加上授权（上文）而没有本项，越权探测分支/世界将不留痕，且没有任何 fixture 能断言一次拒绝。**该写入是不变量 25 零业务/控制写集的唯一显式例外**：它是「授权拒绝遥测」，不是被读对象上的业务/控制写，故与 T5b 的「零写集逐条为 0」不冲突（见不变量 25、§7.3 第 4 条、§7.5、§12）。

### 2.5 schema 安装边界与 per-stage 分歧（新偏差 v11-1）

v8 的隐含前提是「一套 schema」。v11 打破它：`agent_v8_tree` 库（**加载全部 16 文件 = 14 个 v8 文件 + `v11_schema_delta.sql` + `v11_tree.sql`**；**〔审阅修正〕low：LOW-3 —— T1 的加载集是 14+2=16，只有 T0 的 `agent_v8_tree_base` 才是 15（14+`v11_schema_delta.sql`）**）里的 `session_events` 有 `entry_id/parent_entry_id`，`sessions` 有 `session_mode`；**其余十四个 stage 库都没有**（工作树 `STAGE_THROUGH` = **14 键**：`b3ce055` 的 12 个 + G12 `gates` + G14 `concurrency`，§0.1；`setup_db.py` 只加载自己的前缀，例如 `v8/events/setup_db.py` 的加载集止于位置 5）。这是必须**登记**的偏差，MUST NOT 假装不存在：台账新增 **v11-1「per-stage schema 分歧」**。

**加载面纪律（**〔审阅修正〕**，A55 类事故的正面处置）**：

- v11 的 SQL 只以**末尾追加**进 `v8/load.py` 的 `SQL_LOAD_ORDER`，新增单一 stage key **`tree`**，其 `STAGE_THROUGH['tree']` MUST 恒等于 `len(SQL_LOAD_ORDER)`。
- **每追加一个 SQL 文件，同一 commit MUST 把 `STAGE_THROUGH['tree']` 提到新全长**，并加一条断言门：`assert len(files_through('tree')) == len(SQL_LOAD_ORDER)`。否则新文件不被 tree stage 加载，其函数/表在加载期不存在 → 该 stage 的门直接 ERROR（这正是 A55 记录的「陈旧计数静默截断加载集」）。
- **落位时序（〔审阅修正〕：MED-1 复核）**：v11 的槽位 = **G12 与 G14 全部合并之后**（**〔审阅修正〕** G12 已于 commit `605e866` 合并，G14 为工作区**未提交**的进行中 stage，§0.1；二者如 `v8/load.py:111-114` 与其 `concurrency` 注释自述**都「不加任何自己的 SQL」**，故 v11 的末尾 **SQL 槽位无争用** —— 但 `STAGE_THROUGH` 字典本身有一个**未提交的 `"concurrency"` 键**，v11 的 `tree` 键 MUST 追加在该键**之后**、绝不复用/覆盖它）。G12 的实际形状 = 就地改 **六个** SQL 文件 `effect`/**`events`**/`tools`/`retry`/`takeover`/`repair` + 新增 `v8/gates/`（无 SQL）。（**〔审阅修正〕blocking：更正 G12 闭包与判据形式**）原文的 G12 描述只列 `effect`/`tools`/`retry`/`takeover`/`repair` **五个**，**漏了 `v8/events/v8_append.sql`** —— G12 同样就地改了它（§A.2 自记 1210→1204 行）；`v8/load.py:111-114` 那条注释（「modifies the existing effect/tools/retry/takeover files in place」）同样**漏列 `events`，该注释本身陈旧**，MUST NOT 以它为 G12 闭包的权威。**裁定**：v11 只**增键**、绝不改既有键值；T0 首步的判据是 **name-set** 断言而非 diff 空断言 —— `git diff --name-only b3ce055 -- 'v8/*.sql'` 的文件集合 MUST **恰等于** G12 的 SQL 闭包 `{v8/effect/v8_effect.sql, v8/events/v8_append.sql, v8/repair/v8_repair.sql, v8/retry/v8_retry.sql, v8/retry/v8_takeover.sql, v8/tools/v8_tools.sql}`，且 v11 自己的 `v8/*.sql` 改动 MUST NOT 出现在该集合里。**原文的「`git diff --stat b3ce055 -- v8/*.sql` 必须为空」在已合并 G12 的本仓上不成立**（实测 6 文件 / 670 insertions / 100 deletions），故 MUST NOT 再以「diff 为空」作判据。
- **stage 实体落在 `v8/tree/`**，与既有**十四个** stage 同构（工作树 `STAGE_THROUGH` = 14 键，§0.1；目录 = `v8/<stage>/`，含 `setup_db.py`）；`load.py` 的 `V8_ROOT` 无需引入 `AGENT_ROOT`。**〔审阅修正〕** 原计划的 `v11/tree/` 会是全仓第一个位于 `v8/` 之外的 SQL，且 `AGENTS.md:20-22` 把 gate 运行方式钉为 `uv run python v8/<stage>/test_<name>.py`。

## 3. 会话语义（分支与路径）〔D2〕

### 3.1 创建 TREE 会话

`v_create_tree_session(auth, driver, workspace_id) → session_id`（O 类，独立 receipt 域）。对 `sessions` 的 INSERT 仍走 `trg_sessions_initial_row`（`v8/schema/v8_schema.sql:48-74`）—— 新列带默认值（`session_mode='linear'`）故该触发器无需改动；本命令在其后显式置 `session_mode='tree'`（同事务内、在写一次约束生效之前），**同事务内先 `set_config('v11.tree_append', session_id::text, true)`**（使 D7 分支 (B) 放行本 root 行，§2.1 D7），并在同事务内写下该树会话的 **root 行**（`session_events` 中 `parent_entry_id IS NULL` 的唯一事件；**〔审阅修正〕blocking：MED-4 —— root 行 MUST 为 `event_class='observational'`、新 `event_type='session/tree_root'`（非 audit），两 ordinal 皆 NULL**。约束推理：`session_events_ordinal_class_check`（`v8/schema/v8_schema.sql:164-178`）强制 semantic 行**恰携带一个 ordinal**、observational/audit 行**两 ordinal 皆 NULL**；而 D7 分支 (A) 禁止 TREE 会话的 `semantic_input_ordinal` ⇒ root 行**不可能是** semantic 行，只能是 observational 或 audit。**也 MUST NOT 是 audit 行**：§3.4/§1.1 的 fold 要求消费方跳过未知 audit event_type（§3.4 的 fold 语义），若 root 是 audit 则**初始 leaf 无 referent**、§3.4 的「`parent_entry_id` = 移动前的当前 leaf」在第一次 `v_tree_set_leaf` 时无对象。`session/tree_root` 是**普通事件**（observational，非 audit），故初始 CURRENT leaf = root 行自身（§1.1/§3.4 的 fold 规则），把其 `entry_id` 作为 `root_entry_id` 一并返回 —— D8/D9 的 `parent_is_tree_root` 判定以它为唯一权威。校验：`workspace_id IS NOT NULL`（不变量 31）、授权合取、驱动 envelope。

### 3.2 TREE 追加

`v_tree_append(auth, session_id, command_id, parent_entry_id, event_type, payload…) → {event_key, seq, entry_id}`（O 类，**单条目、非批**）。

- **结构校验（**〔审阅修正〕**blocking：放宽到「已录树的叶」，使 W 宽批可执行；与 §3.4/§6.2/§6.4/§6.6/不变量 24 联改）**：`parent_entry_id` MUST 存在，且 MUST 属于 `{root} ∪ {当前 leaf} ∪ {已录树的任一叶}`（否则 `TREE_PARENT_NOT_LEAF`）—— 即**父必须是根、当前 leaf、或已录树的任一叶**。放宽的理由：一个 W 宽批（§6.2「每条已开分支至多一个 frontier」、§6.6）的 W 个 cell 可以是 **W 条不同已开分支的 frontier**（互不相同的非根父），第 2..W 次追加若仍硬要求「当前 leaf 或根」，整批永远无法落盘，论文 `b2` 项要奖励的并行就**结构性不可达**。**这不等同于「可向任意已录内部节点追加」**：「已录树的叶」按不变量 24 定义为**无 `event_class <> 'audit'` 的已录子节点**；已有已录（非 audit）子节点的节点既不是叶、又撞 D6，故仍被拒。本命令在持会话行锁下调用 `set_config('v11.tree_append', session_id::text, true)`（同事务），随后按 D6 的**非根**单子节点约束强制；**`parent_is_tree_root` 由 D9 的 BEFORE INSERT 触发器计算（§2.1 D9），本命令 MUST NOT 自行提供该值**；**root 的多子节点是分支语义，MUST NOT 被拒**（不变量 24）。
- **event_type 值域**：复用 `public_append_types@v1`（`v8/events/v8_append.sql:485-498`）**同一值域，值域不变**。
- **ordinal**：拒绝 caller 供 `semantic_input_ordinal`（D7 触发器 + 本命令前置校验）；持会话行锁按不变量 22 的公式派生 `internal_semantic_ordinal`；持会话行锁从 `sessions.next_seq` 分配 `seq`（纪律同 `v8/events/v8_append.sql:951,1092`）→ 保持 seq 无洞。
- **envelope 授权腿（**〔审阅修正〕** 补全）**：MUST 复刻冻结 append 路径的 driver/driver_epoch envelope guard（`v8/events/v8_append.sql:378-385`，`IS DISTINCT FROM` 不符 → 稳定 `DRIVER_EPOCH_STALE`、失败封闭）**与** 显式的 `event_append` 授权前置检查。该 guard 是**唯一**阻止「仅知道 session_id 的调用方往别人的会话里注入事件」的机制 —— 冻结路径的 `event_append` 授权前置只在批次含 `session/heartbeat` 时触发（`v8/events/v8_append.sql:327-329`）。
- **幂等**：按 `event_key` 幂等，复用 `UNIQUE(session_id, event_key)`（`v8/schema/v8_schema.sql:159`）；同 `event_key` 异内容 → `IDEMPOTENCY_CONFLICT`，复用冻结五部分比较域（`v8/events/v8_append.sql:795-801,825-831`）。
- **TREE 下的 semantic 幂等（**〔审阅修正〕** 显式定义，而非静默差异）**：LINEAR 的语义查重键是「ordinal × 完整事件内容」（v8-dev.md §1.2），同一内容换 `command_id`、复用同一 `semantic_input_ordinal` → 稳定 `IDEMPOTENCY_CONFLICT`。TREE 无 ordinal，而 `v_nonstream_event_key` 绑定 `(command_id, batch_item_ordinal)`（`v8/schema/v8_keys.sql:85-97`），故同一内容换 `command_id` 会得到新 `event_key`、被 INSERT 为**第二个静默重复节点**。v11 因此**显式**冻结 TREE 幂等规则：`UNIQUE (session_id, parent_entry_id, payload_hash) WHERE event_class = 'semantic' AND parent_entry_id IS NOT NULL`（**〔审阅修正〕medium：谓词必须用行内可见列** —— `session_events` **没有** `session_mode_tree` 列（`session_mode` 在 `sessions` 上），且 PG 部分索引谓词**不能含子查询**（本文 §2.1 D6/D8 自己已认定），原文的 `WHERE session_mode_tree` 索引**根本建不出来**；而 `parent_entry_id IS NOT NULL` 与「tree 非根行」等价 —— 线性/冻结 append 一律 `parent_entry_id IS NULL`，D1），同内容同父 → 幂等返回既有节点；异内容同父 → 撞 D6（单子节点），稳定 `TREE_PARENT_NOT_LEAF`／`IDEMPOTENCY_CONFLICT` 二择一按既有判定序。**跨路径一致性门**因此**收窄为**：canonicalizer + key 派生两条共享子面（**receipt 语义不可能一致**，见 §3.3 与台账 v11-2）。

### 3.3 receipt 域：三条，不是两条（新偏差 v11-2）

**〔审阅修正〕（blocking）** 原计划同时宣称「复用 `v8_command_adjudicate`」与「独立 receipt 域」—— 二者不可兼得：`v8_command_adjudicate`（`v8/events/v8_append.sql:117`）的 binding 查询是 `WHERE cb.session_id=p_session_id AND cb.command_id=p_command_id`（`:151-152`），**不含 command_kind**；`command_bindings` PK 是 `(session_id, command_id)`、`command_receipts` 唯一键是 `(session_id, command_id, receipt_key_kind, receipt_key_value)`，也都不含 kind；`v8_reject_command`（`:69`）同样只按 `(session_id, command_id)` 写。于是同一 session 上先用 `C1` 调 `v_append_events`、再用 `C1` 调 `v_tree_append`，adjudicator 会命中既有 binding 返回 `binding_replay`/conflict —— 静默重放**线性**命令的 receipt，树追加被吞掉或产出错配 receipt。

**裁定（选 (a)，不打折扣）**：TREE 路径**真正独立** —— 新增自有表 `v11_tree_bindings`（PK `(session_id, command_id)`）与 `v11_tree_receipts`，`v_tree_append`/`v_tree_set_leaf`/`v_tree_*` O 命令只写这两张表，**MUST NOT** 复用 `v8_command_adjudicate`／`v8_reject_command` 的 binding 侧（其幂等语义因此**可复现地不同**，登记为偏差 **v11-2「第三条 receipt 域」**）。给 adjudicator 的键加 `command_kind` 属于编辑冻结 events 文件，被基线约束禁止，故不可选 (b)。

**只读跨域复用检测（〔审阅修正〕blocking：HIGH-1 收口 —— 选 (a) 并补具名拒绝码）**：上句只禁止 tree 命令**写入**线性 receipt 域，**不等于**对「同 session 同 command_id 已在**线性**域占用」视而不见。若不加此检查，`v_append_events(C1)` 与 `v_tree_append(..., C1)` 会**同时成功**（二者写各自的 binding 表，无约束相交），而 §3.2 的 event_key 幂等又会让**同内容**的 tree 调用静默重放线性行、**异内容**的 tree 调用成功插入 —— T1e（§11）断言的「稳定拒绝」将**无任何机制产生**。故钉死：`v_tree_append`／`v_tree_set_leaf`／`v_tree_*` O 命令在写自有表**之前** MUST **只读一次** `command_bindings`／`command_receipts` 的 `(session_id, command_id)`（**只读、不写、不复用 adjudicator 的 binding 侧**）：命中任一已存在的线性 binding/receipt → **稳定拒绝 `CROSS_DOMAIN_COMMAND_ID_REUSE`、零写**（MUST NOT 静默 `binding_replay`、MUST NOT 产出错配 receipt）。该只读检查**不违反**「真正独立」—— 独立的是**写域与幂等语义**，不是「对另一个域的存在无知」。**反向不要求**：线性命令（`v_append_events`）MUST NOT 因存在 tree binding 而被拒 —— 线性域 MUST NOT 咨询 tree 域（否则冻结 events 文件的行为被改）。T1e 是该规则的唯一验收向量。

**仍复用的共享子面（不复制、不重写）**：`v_nonstream_event_key`（键派生）、`v_sha256_hex`（canonical hash 复核）、canonicalizer 管线、`v_grant_find_valid`/`v_grant_lock_judge`（授权）。T1 的跨路径一致性门因此只断言这两条共享子面在两条路径上输出一致（**字节等价门**，镜像 A75 的 golden-vector 手法），不宣称 receipt 语义一致。

### 3.4 leaf 游标与路径投影

`v_tree_set_leaf(auth, session_id, command_id, target_entry_id)`（O 类）：追加一条 `event_class='audit'`、`event_type='session/leaf'` 的叶子游标事件（payload `{target_entry_id}`），非公开 facade、零复制、O(1)。

**leaf 游标与追加父解耦（**〔审阅修正〕**blocking）**：`v_tree_append` 的父是**已录树的任一叶**（§3.2），**MUST NOT** 要求父 = 当前 leaf —— 一个 W 宽批会同时向 W 个不同 frontier 追加，单一游标不可能同时指向它们。游标（`v_tree_context` 用它决定投影哪条路径与「当前分支」的导航态）**不是**批内各 cell 的追加点，后者 = **cell 自身**。游标自身的推进仍按 §1.1 的 fold 规则（无 `session/leaf` 事件时取 `max(seq)` 的普通事件）与 `v_tree_set_leaf` 的显式追加；本规范**不**要求为批内每次追加插入 `session/leaf` 事件。

- **event_key 派生（**〔审阅修正〕** 必须点名）**：`session/leaf` 的 `event_key` MUST 由既有 `v_nonstream_event_key(session_id, 'session/leaf', command_id, 0, payload_hash)` 派生（`v8/schema/v8_keys.sql:85-97`；`event_type` 是键的段，空间天然不相交）。**MUST NOT 新造第二套键语义**（v8-dev.md §1.2「本节为唯一定义 … MUST NOT 另建第二套键语义」）。**同一 `command_id` 的二次移动**：`event_key` 相同 → 幂等 → 第二次叶子移动被**静默丢弃**（一个难查的「游标不动」故障）。故规范钉死：**一次 leaf 移动 MUST 使用新 `command_id`**；同 `command_id` 重发 → 幂等返回原结果；换 target 而沿用旧 `command_id` → 稳定 `IDEMPOTENCY_CONFLICT`（不是静默折叠）。T1 加该负向门。
- **parent_entry_id 与 D7 标记（**〔审阅修正〕** high + medium）**：本命令与 `v_tree_append` 一样，在**同事务内**先 `set_config('v11.tree_append', session_id::text, true)` —— 该标记使 **D7 的分支 (B)/(C)** 能把「tree 派生命令」与「冻结 facade / 冻结 internal-ordinal 写者」区分开，且**不误伤**八处冻结的 LINEAR ordinal 分配点（§2.1 D7）。**它与 ordinal 无关**：`session/leaf` 行两 ordinal 皆 NULL，旧措辞「使 D7 的模式门在 tree 派生路径上可判定（依赖该列）」把标记说成依赖 ordinal，**已更正** —— D7 分支 (C) 因此按「GUC 标记 = 本会话」判定。**本行 MUST 携带 `parent_entry_id = 移动前的当前 leaf`（并遵守 D3 的复合自引用 FK），MUST NOT 为 NULL** —— 否则该树会话会出现**第二个** `parent_entry_id IS NULL` 行，破坏 §3.1「root 是该会话唯一 NULL-parent 事件」与 D8/D9 的 root 判定。本行是 `event_class='audit'` 行，被 D6 的 `event_class <> 'audit'` 谓词排除，**不占子节点位**。（**〔审阅修正〕low：第三轮更正**）原文写「`parent_is_tree_root` 恒为 false」，**与 D9 的触发器不符**：D9 的判定式是 `NEW.parent_entry_id = 本会话 root 行 entry_id`（**无** `event_class` 测试），而本行的父是「移动前的当前 leaf」—— 当该 leaf 恰为 root 的直接子节点（或 root 自身）时，D9 会算出 **TRUE**，两个陈述不能同真。因 D6 的谓词**两次**排除 audit 行（`parent_entry_id IS NOT NULL` 与 `event_class <> 'audit'`），**该位对 audit 行的取值不影响任何判定**，故本规范只陈述这一点、不再断言其值。
- **fold 语义**：`CURRENT leaf` = `max(seq)` 的 `session/leaf` 事件之 `target_entry_id`；若无该事件，leaf = `max(seq)` 的**普通事件**（= `event_class <> 'audit'` 的已录行；§1.1）。任何 fold `session_events` 的消费方 MUST 显式处理**未知 audit event_type**（不认识的 audit 行跳过、不报错、不当作 semantic、**也不作为 leaf 的「普通事件」候选**）—— v11 在 §2.1 的 `session_events` 消费者注记中声明该规则。**〔审阅修正〕blocking：MED-4** —— 该「跳过」规则**只适用于 audit 行**；root 行是 `event_class='observational'` 的普通事件（`session/tree_root`，§3.1），MUST NOT 被本条跳过，故无 `session/leaf` 事件时初始 leaf 恰为 root 行。
- **可见性**：`session/leaf` 的 payload 使「当前在哪个分支」对任何日志读者可读。v11 的处置：leaf 只经 tree 读入口在授权下 fold；策略执行体角色无 `session_events` SELECT（§2.4），故策略看不到导航态。

`v_tree_context(auth, episode_id, path_leaf_entry_id, through_seq) → (节点集 + path_ordinal)`：单条递归 CTE 沿 `parent_entry_id` 由 leaf 上溯至根、再反序，`path_ordinal = row_number()`。**必须先按不变量 30 从 episode 状态推导可见范围**，MUST NOT 由 caller 指定的 leaf 反推（§1.3 第 2/3 条）。**二/三参数语义（〔审阅修正〕low：第三轮点名）**：`episode_id` 是**可见性的唯一权威**，`path_leaf_entry_id` 是**可选**参数 —— 传 leaf 时它**只选择「投影哪条已揭示路径」**，入口 MUST 先断言该 leaf ∈ revealed(episode)（否则稳定拒绝 `TREE_LEAF_NOT_REVEALED`），**MUST NOT** 用它扩大可见范围。**T1 降级形态（无 episode）**：`episode_id` 可空、`path_leaf_entry_id` 必填，可见范围退化为 session 级 —— 该口径只用于 T1 的结构门、MUST NOT 授予策略执行体角色（偏差 **v11-5**，§13.2 第 3 项）。**`through_seq` / cutoff 是必需参数（**〔审阅修正〕** nit）**：v8 的读相邻契约一律绑显式 cutoff（不变量 9），fork 命令取显式 `p_parent_through_seq`（`v8/grant/v8_grant.sql:1248-1253`）；无 cut 的读入口使「可见多少历史」成为日志当前长度的函数，也让同一会话上的重放跨追加不可复现。

### 3.5 与既有 fork/steps/turns 的交互

- **`v_fork_session`（`v8/grant/v8_grant.sql:1231-1361`）保留不动，但两条硬事实必须写进合同（**〔审阅修正〕** high）**：
  1. **copy-fork 子会话是终态快照、不可再追加**。函数体在事件前缀插入后**没有** `UPDATE sessions SET next_seq`（已核验：该区域仅 grant 拷贝与 `grant_ops_audit`），而 `trg_sessions_initial_row` 把 `next_seq` 钉为 1，故子会话 `max(seq)=N` 而 `next_seq=1`，随后 `v_append_events` 会从 `seq=1` 插入、撞 PK `(session_id, seq)`（`v8/schema/v8_schema.sql:158`），并被防御性 `unique_violation` 处理器误分类为 idempotency/conflict 而非失败（`v8/events/v8_append.sql:1004-1095`）。T1 加**负向向量**：copy-fork 后追加必失败。
  2. **两条 fork 路径 MUST NOT 用于 tree 会话**。两个 fork 的 INSERT 列表都是显式列（`grant:1298-1303`、`v8/compat/v8_compat.sql:520-523`），都**不含** `entry_id`/`parent_entry_id`，故 `entry_id` 取 `DEFAULT gen_random_uuid()`、`parent_entry_id` 全 NULL —— **fork 出的树被静默线性化**（原风险文本称「entry_id 逐字携带」，**该说法已更正为错误**）。**若需要可追加的树子节点**，新增薄 wrapper **`v_tree_fork_child(auth, parent_session_id, through_seq, command_id)`**（落在 T1 的 `v11_tree.sql`，外部实现，无需编辑冻结函数）：① 先查父会话 `session_mode`，**为 `'tree'` 时直接返回稳定拒绝 `FORK_FROM_TREE_SESSION`，不调用冻结函数**；② 否则调用冻结的 `v_fork_session`、取其返回的 `child_session_id`（`:1356-1357` 的 `RETURN jsonb_build_object(..., 'child_session_id', v_child, ...)` 暴露该字段）、再 `UPDATE sessions SET next_seq=(SELECT max(seq)+1 FROM session_events WHERE session_id=child)`，并在 wrapper 内定义 old→new `entry_id` 映射、同步 `v11_node_*` 行。**能力边界（〔审阅修正〕high，如实写出，MUST NOT 留在验收里当已保证）**：该拒绝**只发生在 v11 wrapper 层**；`v_fork_session` 是冻结函数，绕过 wrapper 的直调**不触发**该拒绝，且仍会把子会话静默线性化（其 INSERT 列表 `grant:1291-1293` 只写 `(session_id, driver, workspace_id)`，新列 `session_mode` 走 DEFAULT `'linear'` ⇒ 子会话根本不是 tree 会话，行级触发器没有任何可判定的拒绝条件，D5 的 write-once 触发器也管不到 fork）。原文把「tree 会话上 copy-fork 被拒」直接写成 T1 验收项与 §11 子例 T2i，却**全文没有给出任何实施该拒绝的机制**。
- **`v_compat_fork`（`v8/compat/v8_compat.sql:497-551`）与 `v_fork_session` 语义分叉**（偏差 A84：不重编号 seq、不重派生 internal ordinal、不拷 grant、不传 workspace_id）。**MUST NOT 当作同一合同的第二实现**，也 MUST NOT 用其作为 tree 语义的捷径。
- **copy-fork 不是隔离边界（**〔审阅修正〕** high）**：`v_fork_session` 逐字复制每个 `revoked_at IS NULL` 且 `delegable` 且非 `workspace_exec` 的 grant 的 `slice_id` 与 `constraints`（`:1330-1346`），`delegable` 是无上限的裸布尔（`:133`），拷贝时无收窄；子会话继承父的**完整 recall 范围**。故文档 MUST NOT 把 copy-fork 称作「隔离」；若需要收窄，fork 命令需接受约束收窄白名单并复验，或子会话重新授权。登记为偏差 **v11-3「copy-fork 的读范围放大」**，附一条断言传播范围的门。
- **单活跃 step 不变（**〔审阅修正〕** blocking 的正面处置）**：`steps_one_active_per_session` 是 `steps(session_id) WHERE status NOT IN ('succeeded','failed_terminal','cancelled')` 的**部分唯一索引**（`v8/schema/v8_schema.sql:121-123`），并由 `v_create_step` guard 再次强制（`ACTIVE_STEP_OPEN`，`v8/effect/v8_effect.sql:604-615`）。**因此「一个 tree 会话里跑 W 个并行 step」被冻结索引拒绝**。v11 **不放松该索引**（放松会破 v8 单活跃 step 不变量）。由此得出在线扇出的诚实裁定，见 §6.4。
- **`sessions.next_seq` 仍是唯一计数器**，`v_tree_append`/`v_tree_set_leaf` 是它唯一的两个新写者，且都持会话行锁、按 no-hole 纪律推进（不变量 1 未被削弱）。
- **`workspace_handles` 不入 tree 路径**：v8 的 loop runtime 从不创建 handle（既有事实），v11 也不创建；节点世界的可选 handle 加速器见 §5.3。

## 4. 无损压缩与钻回〔D2〕

### 4.1 模型

派生节点（`v11_derived_nodes`）是**新的派生对象**，血缘完全由派生边表（`v11_derived_sources`）表达，**无 `parent_id` 列**（pi-lcm `PLAN.md:171-173` 的刻意选择：一个 source 可被多个父引用 ⇒ 真 DAG）。`source_type ∈ {'event','node'}`（多态：`event` 指向 `(session_id, entry_id)`，`node` 指向另一 `node_id`），**无 FK**，但 v11 加 `source_slice_id NOT NULL` 并在 build/expand 双向校验（**〔审阅修正〕** 见下）。

- **「已消费」= 集合差**：`NOT EXISTS (SELECT 1 FROM v11_derived_sources ss WHERE ss.source_id = 自身 AND ss.source_type='node')`（pi-lcm `src/db/store.ts:405-411` 的 `NOT EXISTS` 反连接，其注释明写「用 NOT EXISTS 而非 NOT IN，避免 NULL 陷阱」）。**MUST NOT 用可变 flag**：v11 MUST NOT 移植 pi-lcm 的 `is_compacted INTEGER`（那是 `messages` 上的就地 UPDATE，直接违反 v8 不变量 1）。
- **失败派生不落「已完成」**：某派生节点 summarizer 失败时 MUST NOT 建节点、MUST NOT 建边、其 source 仍可被下一次选中（pi-lcm `src/compaction/engine.ts:104-107` 的「不 persist、不 mark compacted」规则）。在 PG 里更强的版本是**一个事务**：建节点 + 建边 + （若要）标记消费，全部或全无；崩溃在中间则 source 仍可选。
- **幂等**：`UNIQUE (session_id, content_hash)` 使构建作业在重试/并发下幂等。**MUST NOT** 移植 pi-lcm 的 `dedup_hash = sha1(role|timestamp|前200字符).slice(0,16)`（`src/db/schema.ts:181-186`）—— 它对「同 role、同毫秒时间戳、前 200 字符相同」的两个真正不同消息会静默丢弃，是不健全的幂等键。
- **并发**：同类构建 MUST 串行化（pi-lcm 的进程内 `Map<string,Promise>` 只在一个 Node 进程内有效，是**不可移植的** workaround）。v11 用 `pg_advisory_xact_lock(hashtext(session_id))` 或租约行。

### 4.2 钻回入口与授权

`v_derived_build(...)`（P 类，构建）与 `v_derived_expand(auth, node_id, through_seq, max_nodes, max_tokens) → 文本`（R 类，drill-back）。`v_derived_expand` 递归 CTE 走边表回到 `session_events` 原行，带 visited 守卫与节点/token 预算（对齐 pi-lcm `src/tools/lcm-expand.ts:13-14,86-89` 的 `HARD_TOKEN_CEILING`/visited 集）。

**逐源授权（**〔审阅修正〕** blocking）**：`v_derived_expand` MUST 在展开时对**每个被披露的源**做 membership 校验（不变量 31），并在**构建时**同样校验闭包完整性。对齐 v10 的读授权契约逐字：`v10-dev.md:217`「artifact 依赖、trace 输入与 emergent 继承来源的**传递闭包**必须逐项满足 membership，不因外层对象可读而豁免」；`:226`「读历史 trace / inspect 返回输入：recall + **每个被披露来源**的对应 capability，按当前权限」；`:911` 把「producer 可读但 consumer 不可读」列为拒绝情形。**拒绝**：一条边命名了消费者不可读的源，drill-back 逐字节返回它（这是 pi-lcm「无 FK 多态边」在 pg-agent 下的直接泄漏面）。

**与 v10 的关系**：v10 的 `recall_context_query` 与 `context_query_registry`（`v10-dev.md:137,238-240`）是**规格上的**登记式只读入口，v10 零代码，v11 MUST NOT 修改 v10 规格。v11 以 `v_derived_expand` 作为该形状的 **v11 实现**：语料作用域按 slice 资源、执行登记的静态参数化 DB-local 只读 SQL、成功与拒绝均零**业务** receipt/audit（对齐 `:238-239`）；**授权拒绝遥测例外仍适用** —— 授权合取失败时写一行 `authz_denial_audits`（§2.4；与 §12 的同一限定词、T6c 的拒绝行一致）。**延期**：把 drill-back 表成一个 `context_query_registry` 条目（`query_id` 唯一权威）是**后续可选**的收敛，不构成 v11 的依赖；登记为 §13 的 deferral。

### 4.3 与 v10 CompactHistory 的并存

v10 `CompactHistory` 是**装配变换**且**减法**：仅保留 profile 指定最近完整组、累计清除 token 不超过 `max_clear_tokens`、下一组超限即停，且逐字禁止「生成新摘要或调用模型」（`v10-dev.md:338-339`）。v11 的无损 DAG 是**独立的节点级对象**，不参与装配变换、不进入 provider wire。**并存而不冲突**：v11 MUST NOT 把派生节点塞进 v10 装配路径，也 MUST NOT 声称 v10 会做检索（`v10-dev.md:964` 明确「不恢复自动 recall」）。两者的关系是「v8/v10 的上下文压缩保持减法；v11 额外提供一条节点级的、可验证授权的钻回通路」。

## 5. 节点世界〔D2〕

### 5.1 裁定：不可变 artifact + 已录观测（不做 live handle）

Dream-RSI 的代价模型默认「世界快照可廉价复制」（`txt:195-197,220-221`：agent 用节点的 saved workspace 起新 attempt）。pg-agent **明确没有**该能力，且这是被冻结契约封死的，不是实现深度问题：

- v8：`v_fork_session` 显式不继承 live handle（`v8/grant/v8_grant.sql:1326-1329`）；不变量 18 只保证 yield 前留 checkpoint。
- v10：不变量 20 禁止 Bind 读 live workspace（`v10-dev.md:53`）；§3.7 禁止继承 live handle（`:380`）。
- pi：文件系统不在会话模型内，`quickstart.md:84` 要求用户自备 checkpoint。

**三方独立拒绝同一处。** v11 的节点世界因此建模为：

1. **不可变 content-addressed artifact**（`v11_node_artifacts`）：`workspace_snapshot`／`generated_artifact`／`eval_program`／`proposal`／`eval_diagnostics` 五 kind；内容以 `content_sha256` 字节复核（**MUST NOT** 信任调用方声明的 hash，对齐 `v10-dev.md:551-554` 的「byte-verified rather than trusting the caller's hash」）；`source_refs` 是有序冻结源身份 + 版本 + 内容摘要 + slice 归属，闭包内**无 live path**。
2. **已录观测**：节点载荷里的 attempt 结果、诊断、score 一律是**已录行**（`v11_node_scores`），不是可重算的活对象。
3. **世界闭包（**〔判审 graft〕**）**：每个 artifact MUST 带 `world_closure_digest` 与 `closure_complete`。**不变量 28**：闭包不完整或未验证的节点 MUST NOT 作为分支父节点、MUST NOT 作为重放世界根。这是「重放世界悄悄引用一个从未真正捕获过的世界」的最强可得防线。

### 5.2 父子差分链（**〔判审 graft〕**）

为避免 artifact-only 模型在每个节点退化为全量拷贝，`v11_node_artifacts` 增 `parent_artifact_identity`：**子节点声明其与父 artifact 的差量**（`kind='workspace_snapshot'` 的 delta），父内容按 `parent_artifact_identity` 解析、逐步回放至具体版本。**约束**：差量链 MUST 无环、MUST 在展开时校验每一跳的 `content_sha256`；任一跳缺失 → `WORLD_DELTA_CHAIN_BROKEN`（不是静默用近似世界）。

**「可恢复节点」的定义（不要含糊）**：v11 的「可恢复」= 「能以字节级可复核的方式重建该节点被录下的 artifact 集合 + 观测集合」，**不是**「能恢复当时的活文件系统」。若某任务要求精确恢复父节点的 live 文件系统，v11 **达不到** —— 这是必须承认的能力边界，写入 §12 与 §13 台账。

### 5.3 可选加速器：`workspace_handles` 分支前沿（须有兜底）

在论文树形成立处（每个非根节点恰有一个已录子节点），**分支前沿本身就是那个可恢复的世界**。故允许一条**可选**路径：以 v8 既有 `workspace_handles`（`v8/grant/v8_grant.sql:733-751`）的 checkpoint/materialize（`:937-987,996-1051`）承载分支前沿，复用其五状态迁移表（`:771-803`）与四项 fail-closed 拒绝（`handle_lost`／`files_missing`／`digest_mismatch`／`checkpoint_not_covering`）。

- **定位**：加速器，**MUST NOT** 是唯一路径；MUST 有非 handle 兜底（§5.1 的 artifact-only）。
- **纪律**：yield 前 MUST 留下覆盖最新已完成执行态的 checkpoint 或显式记 `workspace/lost`（不变量 18）；`WORKSPACE_LOST` MUST NOT 用「旧但 digest 自身正确」的 checkpoint 消解。
- **边界**：它**不**使节点世界成为「每节点一个 handle 的树」；handle 仍是 `UNIQUE(session_id, run_id)` 的单一 owner_fence 链；前沿与节点是一对多的映射，映射表由 v11 侧维护。

## 6. 并行与批量〔D2〕

### 6.1 W 是持久对象属性，不是每调用参数

论文的批约束 `C ∈ A(T;W)`、`|C| ≤ W`（`txt:204-208`），`b2` 项奖励「每轮平均执行的 attempt 数」（`txt:317-320`）。**`W` MUST 存为持久对象属性**：离线经 `episode_id → v11_replay_episodes.plan_id → v11_replay_plan.w` 解析，在线经 `rollout_id → v11_rollouts.w` 解析（§2.1 T13/T15），MUST NOT 是每调用参数（对齐 loopx 的 compute-quota：单条持久数值门控下一步自动动作，与 reward、写批准分离，`docs/quota-allocation.md:1-26`）。**禁止**：把 `W` 当命令行参数传（那样它就不构成 fanout 上限）；**也禁止**在策略产物行（`v11_replay_policies`）上再存一份 `W` —— 那是同一值域的两个写者，与不变量 22 禁止的「第二 ordinal 计数器」同类。**〔审阅修正〕blocking**：原文把 `W` 写成「写进 `v11_replay_policies` 的 profile 内容」，但 §2.1 T10 的 `v11_replay_policies` **既无 profile 列、也无 W**（全 schema 里唯一的 `w` 在 T13 的 `v11_replay_plan`），故原文那条解析链读的是不存在的列；现统一为「离线读 `plan.w`、在线读 `rollout.w`」。

**DDL 不可达（**〔审阅修正〕** medium）**：`v11_probe_batches` 上的**行内** CHECK（无论写在哪一列）都无法引用另一张表里的 `W` —— `width` 只是 `|C|` 的副本（`CHECK (width >= 1)` 并不校验上界，本列的定义见 §2.1 T7）；原文的「`|C|≤W` 由 CHECK 强制」因此**不可兑现**。裁定：
- `v11_probe_batches` 增 `episode_id`/`rollout_id`（**二者恰一**，§2.1 T7），W 经上述两条链之一解析；**该链上的目标表 `v11_replay_episodes`/`v11_rollouts`/`v11_replay_plan`/`v11_replay_policies`/`v11_world_sets` 的 DDL 在 T0 一次落齐**（§2.1 T7、§10.2 T0），故本约束**不产生前向依赖** —— 〔审阅修正〕high）；
- **BEFORE INSERT 触发器**在 `v11_probe_cells` 上解析 `W` 并在 cell 数超限时拒 `BATCH_WIDTH_EXCEEDED`；
- distinct 由 `UNIQUE (batch_id, target_entry_id)` 强制；
- 父子同批与「每已开分支至多一个 frontier」由**关系型谓词触发器**（查询 `parent_entry_id` 祖先关系）强制；
- **`v_replay_probe` 侧做同一判定**（不变量 26），使约束在「谁写批行」之外仍然闭合。

### 6.2 批合法性判定式（DB 强制）

| 规则 | 来源 | 强制点 |
|---|---|---|
| distinct cell id | `txt:1139-1143` | `UNIQUE(batch_id, target_entry_id)` |
| `\|C\| ≤ W` | `txt:204-208` | BEFORE INSERT 触发器（解析持久 W） |
| 批内不得含父子对 | `txt:1100-1106` | 祖先关系触发器 |
| 每条已开分支至多一个 frontier | `txt:1100-1106` | 分支 frontier 触发器 |
| cell 调用前全部合法（**`r` 或任一已观测叶**：每个已开分支至多一个 frontier） | `txt:1100-1106`；`A(T^{m,k}_i) = {r} ∪ leaves(O)`（frontier，叶取自观测树 `O`），`txt:202-203` | `v_replay_probe` 同事务重算 `A(T^{m,k}_i)` |
| 不得含未揭示之外的非 leaf 内部节点 | `txt:265-267` | `v_replay_probe` → `REPLAY_CELL_NOT_LEGAL` |

**追加父 = 批内 cell（**〔审阅修正〕**blocking）**：批内每个 cell 的 probe execution 向**该 cell 自身**追加其子节点（§3.2 的「已录树的任一叶」放宽使之可执行；§6.4/§6.6）；同一批内 W 个不同 cell ⇒ W 条不同 frontier 各追加一次，`UNIQUE(batch_id, target_entry_id)` 保证它们互不相同。**MUST NOT** 把该约束实现为「父 = 会话的单一当前 leaf」。

### 6.3 批一次派发与按 ordinal 折叠

`v_batch_dispatch(auth, batch_id)`（P 类）：一次把 ≤W 个 cell 映射到 `worker_slot`，按 `cell_no`/`dispatch_ordinal` 折叠。**〔审阅修正〕blocking：LOW-4** —— 本命令是 `v11_probe_batches.status` 的 `proposed→revealed` 迁移写者（同事务 UPDATE，须通过 §2.3 的闭合迁移触发器）。**完成顺序仅作观测**：语义结果按 ordinal 折叠，完成时间只是观测字段 —— 逐字对齐 `v8-dev.md:751` 的派发采样规则与不变量 10。**并行规模核算**：规模 k 的批在 `W = max_parallelism` 个 worker 下花 1 个 decision round、`ceil(k/W)` 个 effective sequential rounds（论文操作化，`txt:1003-1013`）。**比较项**：论文的 `V` 第三项是 `N^m/max(1,k^{m,*})`（`txt:295-320`），而实现级 prompt 的 `pareto.reward = pareto.auc − lambda*parallel_penalty`（`txt:1003-1013`）**不是同一个表达式** —— 这是一处真实表述差异，**v11 以论文 §3 的 V 为规范**，prompt 版仅作参考，并记入台账。

### 6.4 在线扇出的诚实裁定（**〔审阅修正〕** blocking）

**问题**：v11 把整棵发现树放在**一个** `session_events` 会话里（分支 = 同日志的 leaf 游标追加）。但每一次真实的 generation-evaluation attempt 在 v8 里是一个 **step**，而 `steps_one_active_per_session`（`v8/schema/v8_schema.sql:121-123`）加 `v_create_step` 的 `ACTIVE_STEP_OPEN`（`v8/effect/v8_effect.sql:604-615`）**拒绝同一会话里的第二个非终态 step**。因此「一个 tree 会话里跑 W 个并行 step」被冻结索引拒绝，而被拒绝的正是 `b2` 项要奖励的并发。

**裁定（选 (a) 并量化代价，不选 (b) 的自我否认）**：

1. **tree 会话里的 attempt 不是 v8 step**，而是 **probe execution**：一次「取节点 world（artifact-only 或 §5.3 前沿）+ 执行一次 generation-evaluation + 记 score/artifact」的受控执行，由 v11 的在线产出入口（§6.5）以 **O 类命令 + 自有 receipt 域** 承载，仅写 `v11_node_scores`/`v11_node_artifacts`/`v11_probe_cells`/`session_events`。（**〔审阅修正〕blocking**：每次 probe execution 的**追加父 = 它自己的 cell**（§3.2 放宽为「已录树的任一叶」），MUST NOT 依赖一个会被 W 个 cell 争夺的单一游标；W 个 cell ⇒ W 条 frontier 各追加一次，§6.2。）
2. **诚实代价（必须写进规范，不得省略）**：probe execution **绕开 v8 的 seal/dispatch/complete 机制**，因此**不享受** v8 的 exactly-once settlement（不变量 5/6/7 的本地至多一次与 unknown 收束**不覆盖** probe attempt）。外部副作用的 exactly-once 本就「取决于 provider 能力」（不变量 6），v11 更进一步：**probe attempt 的正确性由重放可复现性承担，而非由 effect ledger 承担**。这是一条显式的能力让步，登记为偏差 **v11-4「probe execution 不入 effect ledger」**。
3. **为什么不做 (b)**：(b)（每会话 W=1、撤回并行主张）会与论文 `b2` 项直接矛盾，且会使 tree 会话在「扇出」意义上不再是 v8 会话 —— 那是自我否认而非设计。
4. **边界**：probe execution MUST NOT 破坏 v8 层：MUST NOT 创建 step、MUST NOT 写 `effect_requests`/`effect_attempts`/`batches`、MUST NOT 触碰 `steps`/`sessions` 的终态列（除 `next_seq`）；外部 IO 一律在事务外（不变量 4 仍然适用，**且这是最容易被 dream-loop 违反的一条** —— §12 明列）。

### 6.5 在线产出里程碑的必要性（**〔审阅修正〕**）

原文 T1 只说「追加事件」、T3 只做只读重放、T4 直接「落地 `v11_node_scores`/`v11_node_artifacts`」，却**从未命名谁把一次真实执行的 score/artifact 写进行**。隐含依赖冻结的 v8 loop（`v8/loop/runtime.py` 的 claim→assemble→seal→dispatch→complete），而 runtime **从不创建 tree 会话、也不写 node score/artifact**，且它是冻结文件，产者逻辑不可能塞进去。

**裁定**：新增显式里程碑 **T3（在线产出）**，点名产出入口（一个 v11 runtime 模块，只调用既有受控函数 + v11 O 命令），并明确它 **MUST NOT 编辑 `v8/loop/runtime.py`**；同时承认这是**位于执行路径上的新 delta**，登记为偏差 v11-4（与 §6.4 同条）。

### 6.6 在线决策面（策略驱动的 rollout）（**〔审阅修正〕** high）

论文 loop 的**第一阶段**是「current policy guides real-world discovery」（`txt:107-108`），且明确「Both the online and offline phases use this same decision interface」（`txt:208-209`）：**「The rollout allows at most K1 rounds. At round k ≤ K1, the exploration policy chooses a node batch `C^k_t ∈ A(T^k_t;W)`」**（`txt:217-219`）。**原文本没有为这一阶段给出任何规范落点**：§6.4 把在线 attempt 定义为单次**非 step** 的 probe execution（无「谁选节点」、无批、无轮），§6.5 只点名一个 runtime 模块，§9.1 的环图把在线阶段写成「**随机**」执行（与论文的 policy-guided 相反），`K1` 在全设计中出现**一次**（§13.2 的未覆盖项清单），无列、无命令、无验收。裁定如下：

1. **K1 与 rollout 身份落表**：`v11_rollouts`（§2.1 T15）—— `rollout_id`、在线 `session_id`、`policy_id`、`w`、`beta`、`k1`（轮上限）、`k_done`、`status`。
2. **rollout 的开启 = O 命令 `v_rollout_open(auth, session_id, command_id, k1, w, beta) → rollout_id`（〔审阅修正〕blocking）**：它读 `v11_policy_pointer` 指向的 **active 策略产物**（§8.3），把 `policy_id`（连同在线 `w`/`beta`）**创建时固定**写入本行；rollout 期间 MUST NOT 改（§2.3 的 `v11_rollouts` 迁移触发器 + §8.4）。**为什么必须有这条命令**：原文让 `v_rollout_batch` **每次调用**都重读 active 指针（旧第 2 条），于是「rollout 中途一次 `v_policy_activate`」会让同一 rollout 的 `T_t` 由**两个不同策略**写成 —— 与论文「The policy code stays fixed throughout the rollout」（`txt:213`）直接冲突，也使 T8⑧ 的「指针→读数一致」在一个并非单策略的 rollout 上误判为通过。
3. **在线批的生产者 = O 命令 `v_rollout_batch(auth, rollout_id, command_id, cell_entry_ids[]) → batch_id`**：其**策略权威 = rollout 行**的 `policy_id`/`w`（创建时已固定，§6.6 第 2 条）；**〔审阅修正〕blocking：MED-2 措辞收口** —— 原文「**只读 rollout 行** … MUST NOT 每次调用重读 active 指针」与同句「若指针已前移 → `ROLLOUT_POLICY_STALE` 零写」**自相矛盾**：检测指针前移**必须**读 `v11_policy_pointer`，故不可能「不读指针」又「测得指针前移」。本版改为：`v_rollout_batch` **MAY 读 `v11_policy_pointer`，但仅用于与 rollout 行冻结的 `policy_id` 比较** —— 不一致（指针已指向另一产物）→ 稳定拒绝 `ROLLOUT_POLICY_STALE`、**零写**；一致则继续，且策略身份**始终取自 rollout 行**（**MUST NOT** 以所读指针作策略权威、**MUST NOT** 换策略继续），以 **`v_tree_legal_actions(该在线会话的当前观测子树)`** 为合法集（与离线同一 `A(T)` 谓词，只是 `A(T)` 由**在线会话的当前观测子树**而非 episode 揭示集派生），写一行 `v11_probe_batches`（**`rollout_id` 非空、`episode_id` 为空**、`round_no = k_done + 1`，§2.1 T7）+ cells，**并在同一事务把 `v11_rollouts.k_done` 自增 1**（§2.3 的 `v11_rollouts` 段：本命令是 `k_done` 的唯一写者，空批不自增），返回 `batch_id`；消费方随后走 §6.4 的 probe execution（**每个 cell 向它自己追加一个已录子节点**，W 个 cell ⇒ W 条 frontier 各追加一次；§3.2/§6.2）。**在线与离线共用同一 `A(T)` 谓词、同一 `|C|≤W` 触发器、同一 `batch_id`/`Observation` 形状**（论文 `txt:208-209`）—— 这正是「same decision interface」在 v11 的落地。**〔审阅修正〕blocking**：原文本把 `v11_probe_batches.episode_id` 定为 NOT NULL，使**在线批根本无法持久化**（一次 rollout 不是 `(plan, candidate, world)` 重放，无 episode 可指）；现由 §2.1 T7 的 `episode_id`/`rollout_id` 二者恰一解决。
4. **K1 到限**：`k_done = k1` 时，`v_rollout_batch` 对**非空批**稳定拒绝 `ROLLOUT_ROUND_LIMIT_REACHED`；**空批**正常终止并置 `status='closed'`、`k_done` 不减（**〔审阅修正〕low**：空批**不写 `v11_probe_batches` 行** —— 该表 `width >= 1` 只覆盖非空批；空批终止由 `v_rollout_batch` 的专用返回值表达，它只翻 `v11_rollouts.status`，§2.1 T7）（论文 `txt:220-222`「terminates when the policy selects an empty batch or completes K1 decision rounds」）。
5. **redeploy 是可观测事件**：`v_policy_activate` 激活后，**下一次** `v_rollout_open` 写入的 `v11_rollouts.policy_id` MUST 解析到**新的**指针目标；「π_{t+1} 上线」因此不是叙述，而是可断言的指针→读数一致（§9.1 环图的 redeploy 边、T8 ⑧）。
6. **离线批的生产者 = O 命令 `v_replay_batch(auth, episode_id, command_id, cell_entry_ids[]) → batch_id`（〔审阅修正〕blocking）**：与在线**同形**（同一 `A(T)` 谓词、同一 `|C|≤W` 触发器、同一 `Observation` 形状），差别是 `episode_id` 非空而 `rollout_id` 为空，`A(T)` 由 **episode 的揭示集**派生。**原文本没有任何离线批的生产者**：`v_replay_probe`（§7.3）只接受**已持久化、已合法化**的 `batch_id`，而 §1.3 第 2 条又禁止策略执行角色对 `v11_probe_batches`/`v11_rollouts` 做 DML —— 于是**离线 dreaming 的每一轮都无法开始**，`k_star` 与 reward 全不可达。本命令补上该生产者（调用方 = 宿主 dreaming 编排，**不是**策略角色）；其 receipt 域为**自有第三条域**（与 `v_tree_*` 同域纪律，§3.3）。
7. **K2 轮上限（〔审阅修正〕high）**：`v_replay_batch` 在为一个 episode 写批前 MUST 断言该 episode 的**非空批计数** `< plan.k2`（计数 = 该 episode 的 `v11_probe_batches` 行数，`round_no` 连续），否则稳定拒绝 `REPLAY_ROUND_LIMIT_REACHED`、零写（论文 `txt:274`「Replay allows at most K2 decision rounds where each nonempty batch counts as one round」）。**原文只有 `k2` 列、无任何执行点**，故该上限在实现上不存在；T4 加该验收（第 `k2+1` 个非空批被拒）。
8. **历史条件化的如实处置（〔审阅修正〕medium）**：论文让在线策略「with access to the completed discovery history H_{t-1}」（`txt:210-212`），而 v11 的策略执行角色**无 `session_events` 表级权限、亦无 `v11_replay_*` 表级权限**（**由 §2.4 的「零表级权限默认拒绝」强制**，覆盖全部 v11 表；§1.3 第 2 条、§9.3）—— 故 v11 的在线策略是**无历史条件化的**（只看当前在线会话的观测子树与合法集）。这是一处**与论文的行为差异**，如实登记为未覆盖项（§13.2 B 段），MUST NOT 声称已实现 `π_t(H_{t-1})`。
9. **禁止**：把在线阶段实现为「随机选 cell」（与论文 `txt:107-108,217-219` 直接矛盾）；把在线批写成不经 `v11_probe_batches` 的第二条路径（不变量 26 的双接口禁令同样适用于在线）；令 `K1`/`K2` 无对象承载（那使论文两阶段不可验收）；令 `v_rollout_batch` 以每次重读的 active 指针**作策略权威**（那使 rollout 非单策略；本版只允许把该读用于与冻结 `policy_id` 比较，§6.6 第 3 条 / MED-2）。

## 7. 评估与回放〔D3〕

### 7.1 评估产物的 kind / digest / provenance

`v11_node_scores` 是系统内**第一个一等的评分/评估对象**（实测：`grep -iE 'score|objective|fitness'` 在 v8 SQL 内为 **0 命中**；`grep -i 'evaluat'` 只命中判定语的 `re-evaluation` 措辞 —— 如 `v8/retry/v8_retry.sql:243,366,1042`、`v8/effect/v8_effect.sql:50,1717,1967`，那是 retry 资格与 constraint 的**重新求值**，不是评估对象；`docs/designs/v10-dev.md` 内 `grep -niE 'score|fitness|objective'` 为空 —— v10 的 `context_stats` 是 usage EMA/百分位，不是 best-of-search 的 reward，`v10-dev.md:507-519`）。字段逐一镜像论文 `Observation`（`txt:1034-1036`）：`branch/attempt/score/evaluated/valid/fail_class/error/delta_vs_baseline/delta_vs_parent/n_valid/n_total`。

- **创建者 MUST 是 O 类命令**（自有 receipt 域、typed key、first-claim、稳定拒绝码），**MUST NOT 由读入口创建**（**〔判审 graft〕** v11-I26 的正面采纳：评估是一等**已录对象**，只能由 O 命令创建，绝不由 read entry 创建）。这同时把 §6.5 的「谁写 score」钉死。
- **成功语义（**〔判审 graft〕**，负向向量）**：`error IS NULL AND fail_class='ok'` 即算成功评估 —— **即使 `valid=false` 或 `n_valid/n_total` 不可用**（论文 `txt:1041-1045`：「不得仅因 valid 为假就判为可修复」）。T4 必须含该负向向量。
- **不可变**：`v11_node_scores` 表级 immutability 触发器；「每个 `(plan, 候选, 世界)` 恰一条」的唯一性在 episode 层（§7.2）；**`β` 的冻结剖面宿主是 `v11_replay_plan`（§2.1 T13、§9.3）**，不在 episode 行上。
- **kind/digest/provenance**：score 行引用其来源 artifact（`v11_node_artifacts.artifact_id`），artifact 带 `content_sha256` 与 `source_refs`；跨表一致性由 `effect_feedback_bindings` 式的**冻结绑定**保证：score 行的 `(session_id, entry_id)` 必须能解析到一个已发布的 artifact 行，否则写入拒绝。

### 7.2 reward 与 episode

- **`v11_reward`**：独立 IMMUTABLE 纯函数（§2.1）。体 = 论文 V：`V = max_v s_v − b1*N + b2*N/max(1,k*)`，`N = |O| − 1 = |T^{m,k*}_i| − 1`（`O` = 不变量 30 的已观测节点集；论文 `txt:287-320`）；`N` 计的是「该轨迹**所代表的** generation-evaluation 请求数」，不是真实执行次数（`txt:287-295`）。**episode 的 `n_revealed` 列即 `N`**（= `|O| − 1` = `|T| − 1`，**不再减 1**；`O` = 不变量 30 的已观测节点集；见 §2.1 的 `v11_reward` 段），T4 ①/T5f/T5j 的逐位黄金向量按此口径。`b1,b2 ≥ 0` 与 `numeric_scale` 由 **`v11_replay_plan` 解析后传入**（§2.1 T13），非每调用参数；round-half-even。**`β` 不进 V 公式** —— 它只经 `_schedule(β)` 影响策略行为（§9.3）。
- **`v11_replay_episodes`**：一行 = 一个 **`(plan, 候选策略, 世界)`** 的一次重放，记 `k_star`、`n_revealed`、`v_max`、`reward`；评估剖面 `(world_set_id, w, k2, b1, b2, numeric_scale, β)` **经 `plan_id` 继承**，不由 episode 自持。**唯一键 `(plan_id, candidate_index, world_session_id, world_through_entry)`**，且 `world_through_entry` MUST NOT NULL（不然 PG 的 `UNIQUE` 视 NULL 互异，「恰一条」在 DDL 层失效）。**〔审阅修正〕blocking** 原文的 7 列唯一键把 `(w,k2,b1,b2)` 纳入键，恰恰**允许**同一 `(policy, world)` 在多个剖面各占一行；而完整性断言只查 `count(distinct world_session_id)`，反例（P 在 {w1,w2} 上按 b1=0、在 {w1} 上按 b1=1）**通过**该断言却被 `1/t` 折叠成一个既非 0 也非 1 的数。**写入者 = O 类命令**：**〔审阅修正〕blocking 生命周期** —— 身份列由 `v_replay_episode_open` 在**重放开始时**插入（批在重放期的 FK 因此有目标），结果列由 `v_replay_settle` **恰一次**写入（BEFORE UPDATE 的 `NULL→非 NULL` 迁移，重复结算 → 拒）；原文「结算事务内一条 INSERT 写入全部列」与「批在重放期 FK 到 episode」时序冲突，已改述（§2.3「episode 生命周期」）。
- **`v11_replay_scores`（视图，**〔判审 graft〕** 必须命名）**：**按 `(plan_id, candidate_index)` 分组**聚合 —— 一个 plan 的候选 `m` 得 `V^m = (1/t)·Σ_i V^m_i`（论文 `txt:321-330` 的精确 `1/t` 形式）。**〔审阅修正〕low：删除「等价地按 `(policy_id, world_set_id, w, k2, b1, b2, numeric_scale, β)` 分组」** —— 两个不同 plan 可以共享同一剖面与同一策略，按剖面分组会**跨 plan 合并**，恰是下一条禁止的事；分组严格用 `(plan_id, candidate_index)`。**覆盖完整性断言（〔审阅修正〕high：必须是 per-candidate）**：视图（或其守卫函数）MUST **对每个 `(plan_id, candidate_index)`** 断言该候选的 episode 世界身份**多重集（bag）逐元素等于** plan 冻结的 `v11_world_sets.members`（世界身份 = §0.4 定义的**有序对**；**〔审阅修正〕blocking：MED-3** —— 原文只查 `count(distinct (world_session_id, world_through_entry)) = member_count`，**不足以**排除「候选的 episode 跑在成员**之外**的世界上」：反例 `WS={w1,w2}`、episode 在 `{w3,w4}` 上，两侧计数同为 2，计数断言**通过**，而 `V^m = (1/2)·Σ V^m_{w3,w4}` **不是** `H_t` 上的平均。故 MUST 用**集合/多重集相等**：对每个 members 元素断言恰一条 episode，**且**无 members 外的 episode —— 等价地，episode 创建入口 MUST 拒绝 `(world_session_id, world_through_entry) ∉ members` 的 episode），**任一方向不等**则**失败封闭**（返回 `REPLAY_COVERAGE_INCOMPLETE`）。**MUST NOT** 只断言计数相等。**反例（plan 级断言会漏）**：候选 m1 在 `{w1,w2}` 有 episode、候选 m2 只在 `{w1}` 有 —— plan 级 `distinct world_session_id = {w1,w2} = member_count = 2` **通过**，而 `V^{m2}` 实为 `(1/2)·V^{m2}_{w1}`，`argmax` 可翻。MUST NOT 把一个部分平均当作 `V^m` 报出，也 MUST NOT 把两个不同 plan（不同世界集或不同系数档）的行平均进同一个 `V^m`。
- **`v_policy_select`（O 命令，**〔审阅修正〕** blocking）**：读 `v11_replay_scores`、在**同一个 `plan_id`** 的候选之间算 `m* = argmax_m V^m`（论文 `txt:337`）、经 `v11_policy_pointer` CAS 激活赢家。**前置条件（〔审阅修正〕blocking：原文缺此条件）**：MUST 先断言 `EXISTS (SELECT 1 FROM v11_replay_candidates WHERE plan_id = :p AND is_incumbent)`，否则稳定拒绝 `NO_INCUMBENT_CANDIDATE`、零激活 —— 论文的 `V^{m*} ≥ V^0` 全部来自「候选集包含当前版本 π^0 = π_t」这一**构造**（`txt:233-236,337-339`），而原文没有任何对象承载它。**禁止**：在候选集不含现役策略时算出 `m*` 并声称单调不退化（那是一个**无对象**的 `V^0`）。**没有这条命令，`V^{m*} ≥ V^0` 的断言是空的** —— 只有 `v11_replay_episodes` 而没有聚合视图与选择命令时，端到端跑完也读不出任何 `V^m`（`m ≥ 1`），π_{t+1} ≡ π_t，单调性只因 `M=1`（`V^0 ≥ V^0`）而真空成立。
- **真空报告规则（**〔审阅修正〕**）**：plane MUST 接受 `M ≥ 2` 的候选策略；当只有 1 个候选时，MUST **如实报告该保证为真空（M=1）**，MUST NOT 把未闭合的环报告为「保证已满足」。**该规则不替代上一条前置条件**：`M ≥ 2` 但**候选集不含现役**时同样 MUST NOT 报「保证满足」，而是 `NO_INCUMBENT_CANDIDATE`。

### 7.3 决策层只读重放 oracle

`v_replay_probe(auth, batch_id) → Observation[]`（R 类；**签名从 `node_entry_ids[]` 改为 `batch_id`**，见不变量 26）。行为：

1. 解析 `batch_id` → 其 `episode_id` → `v11_replay_episodes.plan_id` → `v11_replay_plan.w`（策略 `W` 的**离线宿主**，§6.1/§2.1 T13）；持授权合取（v11 的 `recall` 作用域对该**世界语料**，`§2.4`）。**批的生产者**是 O 命令 `v_replay_batch`（§6.6 第 6 条）：本入口**只消费**已持久化的合法批，MUST NOT 自行建批（不变量 26）。
2. 同事务重算当前 episode 的 `A(T)`（**按 `round_no` 升序折叠该 episode 的已持久化批**，`v11_probe_batches.round_no`，§2.1 T7 —— `created_at` 不是确定性序键）；任一 cell 非当前合法 → `REPLAY_CELL_NOT_LEGAL`、**返回空 `Observation[]`**（**〔审阅修正〕blocking：措辞收口** —— 该批行与 cells 由 §6.6 第 6 条的 `v_replay_batch` 在**先前事务**已持久化，本入口**只拒绝、不回收该批**；「零返回」指的是 **Observation[] 为空**，**不是**「无任何行被持久化」——原文措辞把两者混为一谈。另外原文允许 caller 直接传一个内部节点 id，Child 规则是无条件确定的，会逐字节返回该节点未揭示子节点的 outcome —— 那正是策略本该花一次探针才能学到的信息）。
3. 按 §1.4 的确定性 Child 对每个合法 cell 返回一批 `Observation`（含已录 score，**MUST 读取已录 score，MUST NOT 调用任何 evaluator**，不变量 25）。
4. **零业务/控制写集**（逐条对齐 `v10-dev.md:366`）：无 step/effect/receipt/manifest/plan/trace/audit、无 latch/emergent/stats/spill/session/lease/fence 变更。**唯一例外** = 授权合取失败时的那一行 `authz_denial_audits`（拒绝遥测；不变量 25/§2.4/§7.4）。除该例外外，本入口对本 episode 与两个 `v11_node_*` 表**零写**。

**与 v10 `inspect_assembly` 刻意区分（必须明写）**：`v10-dev.md:365` 逐字说 inspection「与 execution **共用计算核**」、`:364` 说它仍要求来源授权与捕获。那对**内环 oracle 是错的成本画像** —— 内环 oracle 便宜，恰恰因为它只读已录结果。v11 的 oracle **不**共用计算核、**不**调 renderer、**不**重新装配、**不**重新做授权捕获（捕获只在 episode 建立时做一次）。**禁止**：把本入口实现成 v10 `inspect_assembly` 的包装。

**易变等级**：`STABLE`，MUST NOT `IMMUTABLE`（§2.1）。**〔审阅修正〕medium：`STABLE` 与取锁授权子操作的相容性** —— PG 禁止在 `STABLE`（非 `VOLATILE`）函数体内执行 `SELECT … FOR UPDATE`（实测：`ERROR: SELECT FOR UPDATE is not allowed in a non-volatile function`）。而本入口按不变量 31/§2.4 必须走既有合取校验（`v_grant_lock_judge` 取 `FOR UPDATE`，`v8/grant/v8_grant.sql:395-416`）。**故把取锁的授权子操作放进一个 `VOLATILE` 函数，`v_replay_probe`/`v_tree_*`/`v_node_score_read` 这些 `STABLE` 入口只调用它**；直接在本体里做取锁读的写法在运行期必然失败（同一实现换个体却通过）。该约束写入 T4 ⑦ 的 grep 门。

**事务隔离**：`v_replay_probe` **不**宣称可在任意 `READ ONLY` 事务下调用，**也**不宣称「无需任何授权行锁」。（**〔审阅修正〕** 原文的这两句自相矛盾：入口带 `auth`，而 `v10-dev.md:367` 明确「无需推进 lease 不等于无需授权锁；不承诺任意 PostgreSQL READ ONLY 事务可调用含授权行锁的入口」；v8 既有 capability 函数普遍取锁 —— `v8_command_adjudicate` 取 session `FOR UPDATE`，`v8/events/v8_append.sql:131`；`v_grant_lock_judge` 取 `FOR UPDATE`，`v8/grant/v8_grant.sql:395-416`。）裁定：`v_replay_probe` **保留 `auth`**，并在同一事务内**复验 recall 合取**（可行走只读判定路径而不取写锁，但规范 MUST NOT 承诺它在 `READ ONLY` 事务下可用）；§11 的 T4 验收里**删除**「只读事务/只读角色可调用」这一条，改为「授权合取失败 → 稳定拒绝 + 拒绝行 + 零内容返回」。

### 7.4 世界语料的授权与读集边界（**〔审阅修正〕** blocking）

`v11_replay_episodes.world_session_id` 是指向**另一个** `sessions` 行（历史/冻结世界 T_i）的外键，oracle 读该会话的事件。**v11 MUST NOT 复用「绝不重新做授权捕获」这句作为免除授权的理由**。

- **世界绑定到语料 slice**：每个 world MUST 绑定一个 corpus slice，按 v10 的 `slice.spec.context_resources@v1` 词汇（`v10-dev.md:217`）；消费方 MUST 在 oracle 读该世界历史范围之前持有 `recall` + 该世界语料的 membership。
- **不变量 25 的读集边界**：`v11_node_scores`/`v11_node_artifacts` 的可见性 = **该节点在当前 episode 揭示集之内**；揭示集之外 → 不可读（稳定拒绝 `SCORE_NOT_REVEALED`，返回空 `Observation[]`），**不是**「靠调用方自觉不看」。**实施点（〔审阅修正〕blocking：第三轮点名）**：该边界由**具名读入口 `v_node_score_read(auth, batch_id, entry_id[]) → Observation[]`**（`STABLE`，`EXECUTE` 授予策略执行体角色）承担，逐节点判定 episode 揭示集成员资格；**两张 `v11_node_*` 表对策略执行体角色默认拒绝**（§2.4：该角色**零表级权限**，默认拒绝覆盖**全部 v11 表**，并附 `REVOKE SELECT` 兜底），使裸 `SELECT` 路径同样关闭。没有该入口时 T4 ③ 无可调用面、§1.3 ② 无实施点。
- **拒绝落 `authz_denial_audits`**（§2.4；不变量 25 的唯一显式例外，且唯一被允许在读路径上产生的写）—— **该行只由具名读入口产生**；裸 `SELECT` 被 PG 权限层拒绝（`42501`）时不落行（§1.3 第 2 条、§2.4、T5c/T9d）。

### 7.5 逐位可复现（gate 化）

固定 `(policy_id, world_set_id, w, k2, b1, b2, numeric_scale)` 下，重放**逐位可复现**：同一输入两次调用逐字节相等（`v11_reward` 的定点 + round-half-even 是必要条件）。T4 的验收项：
- golden vector：完整输入 canonical bytes + 期望输出 bytes（不只 hash）；
- 同输入两次调用逐字节相等；
- 零业务/控制写集逐条断言（对照 `v10-dev.md:366` 清单）——**并显式断言唯一例外**：授权合取失败恰好产生 **1 行** `authz_denial_audits`（`occurrences` 按既有幂等合并语义递增），且该例外之外清单逐条为 0；
- `v11_reward` 为 `IMMUTABLE` 的 grep 断言 + 舍入向量（含 `numeric_scale` 边界与 half-even 的偶舍入用例）；
- `v_replay_probe` 等读入口为 `STABLE` 的 grep 断言。

## 8. 策略版本与部署〔D3〕

### 8.1 版本化

`v11_replay_policies`：不可变（immutability 触发器），key = `(workspace_id, generation, policy_version)`，内容 = `source_bytes` + `source_hash`（策略程序源码字节，含其依赖声明）；同键异内容 → `POLICY_IDENTITY_CONFLICT`。这直接映射 v10 的不可变装配 profile 形状（`assembly_profiles`，key `(generation, profile_version)`，I 类，`v10-dev.md:140`）与「版本化产物 + 部署 + 回滚」原语 —— v11 复用其**语义**，自建等价表（v10 零代码且不可改）。

### 8.2 覆盖所有历史树（**〔审阅修正〕** high）

论文定义 `V^m = (1/t)·Σ_{i=1..t} V^m_i` 覆盖**全部** t 棵历史树（`txt:321-330`）。v11 据此：

- `v11_world_sets`：一个冻结的枚举（`members` 有序 `(world_session_id, world_through_entry)` 列表 + `member_count`）。**创建者 = O 命令 `v_replay_world_set_freeze(auth, command_id, members[])`（T6；§2.1 T12）—— 冻结时在命令体内断言下述「`member_count = |H_t 已 closed rollout 树|`」**（〔审阅修正〕blocking：MED-5，原文无创建命令）。
- `v11_replay_plan`：一次离线评估的**命名对象，且自含评估剖面** = `(world_set_id, w, k2, b1, b2, numeric_scale, β)`（§2.1 T13）；候选策略集 = `v11_replay_candidates`（T14，含 `is_incumbent`）。**创建者 = `v_replay_plan_open(...)` / `v_replay_candidate_add(...)`（T6；§2.1 T13/T14）**。
- **完整性（〔审阅修正〕high + nit：必须 per-candidate、按世界身份计数）**：`v11_replay_scores` MUST **对每个 `(plan_id, candidate_index)`** 断言该候选的世界身份**多重集等于** `v11_world_sets.members`（**集合/多重集相等，非计数相等** —— **〔审阅修正〕blocking：MED-3**，计数相等会放过「成员之外的世界」的反例：`WS={w1,w2}` 而 episode 在 `{w3,w4}`，二者计数同为 2），否则失败封闭（不回退为部分平均）；跨 plan 的行 MUST NOT 被平均进同一个 `V^m`。原文只断言「该 plan 内」，漏掉「同一 plan 的不同候选覆盖不同世界子集」的反例（详见 §7.2），且按 `world_session_id` 单列计数与本文 §0.4 的世界身份（有序对）不一致。
- **反例（规范内明写；**〔审阅修正〕blocking** 已真正消灭，且消灭方式已改）**：若允许「策略 P 在 {w1,w2} 上按 b1=0 打分、又在 {w1} 上按 b1=1 打分」，选择时的 argmax 就在比较「2 个世界的平均」与「1 个世界的平均」，`t' < t` 的部分运行会静默抬高或压低 `V^m` 而不报错。**原文本宣称它被「唯一键 `(policy_id, world_session_id, world_through_entry, w, k2, b1, b2)` + 完整性断言共同消灭」，这是错的**，三条独立事实：(1) 把 `(w,k2,b1,b2)` 纳入键**恰恰允许**同一 `(policy, world)` 在多个剖面各占一行 —— `(P,w1,·,b1=0)`、`(P,w2,·,b1=0)`、`(P,w1,·,b1=1)` 三行全部合法；(2) 完整性断言只查 `count(distinct world_session_id) = member_count`，上例 distinct world = {w1,w2} = 2 = |WS|，**通过**，于是视图把 3 行按 `1/t` 折叠成一个既非 b1=0 也非 b1=1 的数；(3) `world_through_entry` 可空，PG 的 `UNIQUE` 默认视 NULL 互异，同一 `(policy, world)` 可插任意多条 `world_through_entry IS NULL` 的行。**本版的消灭方式**：剖面提升为命名对象 `v11_replay_plan`（T13），episode 只经 `plan_id` 继承剖面，唯一键收为 `(plan_id, candidate_index, world_session_id, world_through_entry)` 且 `world_through_entry` NOT NULL；视图按 `(plan_id, candidate_index)` 分组、完整性断言 **per-candidate 且按世界有序对计数**；`argmax` 只在**同一 plan** 的候选之间进行。**残余风险（如实写出，不掩饰）**：修正后仍允许 P 在两个**不同世界集/不同系数档**（两个不同 plan）上各跑满 t 个世界，此时若跨 plan 比较就仍不可比 —— v11 以「一次 `v_policy_select` 只接受一个 `plan_id`、跨 plan 比较 MUST NOT 发生」为界，并由 §11 子例 T7h 断言。
- **世界集必须与 H_t 绑定（〔审阅修正〕medium：否则 `(1/t)` 的覆盖是自指的）**：论文的 `V^m` 覆盖**全部 t 棵历史树** `H_t`（`txt:321-330`），而 `v11_world_sets` 是一份**独立冻结的枚举** —— 若允许冻结一个 `member_count < t` 的世界集，上面的完整性断言只与**它自己**的 `member_count` 比较，`V^m` 就只是 `t'` 棵树上的平均，`§8.2/§1.5` 声称的「覆盖所有历史树、不全覆盖即失败封闭」并未对**任何外部对象**成立（T7b 只测 `member_count>1` 时少跑一个世界，测不出这种自指）。故：**世界集冻结时 MUST 断言 `member_count` 等于「当前 `H_t` 中已录 rollout 树（`v11_rollouts` 中 `status='closed'` 的行）的棵数」**（**〔审阅修正〕blocking：MED-5 —— 该断言 MUST 落在 `v_replay_world_set_freeze` 命令体内**，见上；不等 → 稳定拒绝），且**每个外循环周期切一份新的冻结世界集**（`frozen_at`/`member_count` 在该周期内不变）。这与 §9.1 环图的「世界池扩大（`v11_world_sets` 增员）」一致 —— **扩员发生在周期边界**（切新枚举），不是在一份已冻结枚举内就地追加（那会破「冻结」语义）。

### 8.3 激活与回滚

`v_policy_stage` / `v_policy_activate` / `v_policy_revoke_active`（O 类，逐个自有 receipt 域），CAS 语义逐条对齐 `v10-dev.md:644-645`：

- `v11_policy_pointer(workspace_id PK, active_policy_id, revision, last_operator, last_changed_at, last_command_ref)` 是**唯一** active 指针；**v11 无任何状态列**（`v11_replay_policies` 不可变、无 `state`），故「从 `state=active` 行推断」在 v11 中**没有对象可犯** —— 该禁令落为「指针是唯一权威、MUST NOT 缓存」。
- 非 NULL 目标仅可为**同 W、已写入 `v11_replay_policies` 的不可变策略产物行**（同 W 由 T11 的两列复合 FK 在 DDL 层强制；「已发布」在 v11 即「已写入该不可变表」）；**禁止**把 `active_policy_id` 回指一个已被 `revoke_active` 置空的旧产物以「恢复」（v11 无 retired 状态列可查，该禁令由写者闭集仅三 + 命令集承担）—— 恢复 MUST 发布**全新** identity（新 `(generation, policy_version)`）。
- 写者闭集仅三：`v_policy_stage` 首次建空行（NULL/revision=0）；`v_policy_activate` 把非 NULL 目标 CAS 指向一个**已存在的不可变策略产物**（**〔审阅修正〕blocking**：v11 **无 `building→active` 状态迁移可做** —— 策略产物本身不可变，被切换的只是指针）；`v_policy_revoke_active` 的显式置空。后两者在**同一事务**内 CAS 全量 `expected_active_policy_id + revision`，`revision + 1`。
- **禁止**：`fail_build`/readiness 报告/初始化/装配/后台扫描切换指针；自动回滚。
- **锁位（**〔审阅修正〕** medium）**：`v11_policy_pointer` 与 `v11_replay_policies` 未在 v8 八位主锁序（`v8-dev.md:474`）中，取锁而不声明位置是死锁隐患。裁定：**声明为 generation 槽内的 intra-position 子序**（对齐 `v10-dev.md:771` 的「pointer 与 generation 是 generation 槽内的子序」，且「新装配读 active 指针 MUST 先 pointer 再 generation」）；`stage`/`activate`/`revoke_active` **从不取 session 锁**（对齐 v10 的写者集），故不可能与 v8 主序发生环。

### 8.4 每 episode 的策略定型

**不变量补充（〔审阅修正〕LOW-1：该断言实际落在 §10.2 的 T4 ⑩，**不是 T6** —— T6 的验收清单 ①–⑩ 无此项）**：一个 episode 的**策略身份在 episode 创建时固定**，整个 episode 生命期 MUST NOT 改变（禁止指针在 live rollout 中途翻转改变正在评估的策略）。episode 记 `policy_id`（**不可变 FK 列；本表 PK 是 `episode_id`** —— §2.1 T9），不记 `policy_version` 文本（§2.1 T9 的理由）。

## 9. 元循环〔D3〕

### 9.1 环的形状

```
在线 rollout（**策略驱动**：active 策略读 A(T)、K1 轮内选 node batch；真执行；产生 T_t 并追加进 H_t）〔§6.6〕
    ↓  世界池扩大（v11_world_sets 增员）
离线 dreaming（只读已录结果；一个 plan 下 M 个候选策略 × t 个世界；确定性转移；零执行成本）
    ↓  每个 (plan, 候选, 世界) 一行 episode；v11_replay_scores 按 plan 聚合出 V^m
择优（v_policy_select：同一 plan 内 m* = argmax_m V^m；前置断言候选集含现役）→ CAS 激活（v11_policy_pointer）
    ↓
redeploy（π_{t+1} 上线；**可观测**：指针激活后下一次 `v_rollout_open` 实际使用该 policy_id，§6.6/T8⑧）→ 产出 T_{t+1} → 回到第一步
```

**单调不退化**：`V^{m*} ≥ V^0` 只依赖「候选集包含当前版本 π^0 = π_t」这一构造（论文 `txt:337-340`），与存储无关，可原样断言。**但它的断言对象必须是 §7.2 的 `v11_replay_scores` 视图**，必须满足 §7.2 的真空报告规则，且**必须先满足 `v11_replay_candidates` 含 `is_incumbent` 的前置条件**（`txt:233-236,337-339`）—— 原文本逐字承认该保证来自构造，却在数据平面没有任何承载它的对象（`v11_replay_policies` 无「这是现役」表述、`v11_replay_episodes` 不表达候选序号、`v_policy_select` 只做「读视图 + argmax + CAS」），于是 plane 允许「评估 M 个与现役无关的策略」（此时 `V^0` 根本不在集合里，验收项无对象可读），也允许「M≥2 而缺现役」时把真空当保证。**〔审阅修正〕blocking** 本版以 T14 + `v_policy_select` 的 `NO_INCUMBENT_CANDIDATE` 前置拒绝 + §13.2 conformance 新行 + §11 T7g fixture 四处闭合。

### 9.2 策略作者 agent：明确 out of scope（裁定，不是含混）

论文明确 policy-development agent 是一个**固定 LLM**、读重放轨迹与分数来改写可执行策略代码（`txt:186-188,329-334`），**位于系统之外**（与先前 Shepherd 调查结论一致）。

**裁定：v11 只提供 plane，不 host 该环。** 理由（必须写进规范，因为它们同时是硬约束）：

1. **不变量 4**：外部 LLM 调用 MUST NOT 在数据库事务内执行；元层若纳入 runtime，必然要在某处把「LLM 改写策略」与「提交」绑在一起，从而制造事务内外部 IO 的压力点。
2. **v10 §8 非目标**（`v10-dev.md:964,966`）：「不恢复无 step 工作、seal 后补 slot、后台等待态」与「不给 inspection 增 receipt、审计落表或隐式准备」—— 强行纳入会同时踩两条。
3. **能力边界**：v11 提供 `v_policy_select`（plane 的算子）与 `v11_replay_policies`（产物），但**不**提供「从重放评估提出 profile_version n+1」的对象/命令。

**MUST NOT**：在 v11 内新增「元 agent 命令」「元队列」「元等待态」。若未来要纳入，MUST 另立规范并单独审核（对齐 v10 §8 末条「扩大范围必须单独审核」）。

### 9.3 宿主强制的机制级纪律

论文 prompt/策略侧的若干纪律是**机制级**的，v11 把它们变成**宿主强制**，而不是写在提示词里靠模型自律：

| 纪律 | 论文出处 | v11 强制点 |
|---|---|---|
| 前缀-only（不得用未揭示分数/真最优/硬编码 cell id） | `txt:1130-1135` | 不变量 25/30/31 + §1.3 最小权限角色 |
| 批必须合法、无重复 id、≤W | `txt:1139-1143` | 不变量 26 + §6.2 触发器 |
| **（宿主可强制）** 每 episode/rollout 内 β 固定；**（策略侧，宿主不可强制）** 所有阈值走同一个 `_schedule(β)`、绝不可在 `solve()` 内因观测改 β | `txt:1149-1159` | β 是 episode 创建时冻结的 profile 字段，**宿主 = `v11_replay_plan.beta numeric NOT NULL CHECK (beta >= 0 AND beta <= 1)`（离线，§2.1 T13）／ `v11_rollouts.beta`（在线，§2.1 T15）**，两者皆**创建时写一次**，episode/rollout 内经 `plan_id`（或本行）继承（§9.1/§7.2），MUST NOT 由 episode 内观测更新；T4 加「plan/episode 建立后 β 不可 UPDATE（与 `policy_id` 创建时固定同款断言）」验收项。**〔审阅修正〕high**：原文声称 β 是「`v11_replay_episodes` 的列」，但 §2.1 T9 的列清单与唯一键都不含 β，§7.1/§7.2 的「恰一条」措辞也没有承载它的实体 —— 这是 Dream-RSI 前缀-only 三条硬约束中唯一一条被声明为「机制级、由宿主强制」却在数据平面上找不到载体的。本版把宿主钉死在 plan 上：若改放在 episode 行上，同一 `(plan, world)` 可因 β 不同而占多行，§8.2 的 `1/t` 分母会再次失义。**〔审阅修正〕medium（第三轮）：本行只强制前半句** —— 「每 episode/rollout 内 β 固定」由宿主强制（上述 plan/rollout 宿主 + T4 ⑪）；「**所有阈值走同一个 `_schedule(β)`**、绝不在 `solve()` 内改 β」是**策略源码的行为**，v11 既不 host 策略运行（§9.2）、策略执行体角色对策略执行追踪亦无 SELECT，故**宿主不可强制**，MUST NOT 声称已强制；该子项列入 §13.2 第 3 项 B 段未覆盖项（与 meta-agent 外部性并列） |
| 绝不可在 `solve()` 内读 `policy_execution_traces.jsonl` 之类轮间反馈 | `txt:1256-1263` | 轮间反馈是 `v11_replay_*` 表，由 §1.3 角色**无表级权限**（§2.4 的零权限默认拒绝覆盖全部 v11 表） |

**明确不移植的 β 形态**：β 的**角色 2/3**（离线 sweep、跨 cycle 默认值调整）与 `beta_sweep.json` 文件形态（`txt:1160-1165,1169-1188`）是评估 harness 的产物，**不移植**；v11 只移植角色 1（机制级不可变量）。

## 10. 阶段与验收〔D3〕

### 10.1 三重门（对齐 v10 §7.1 形状）

| 三重门 | 必需产物 | 未满足时 |
|---|---|---|
| 规范完成门 | 本文结构/对象/协议/映射/DoD 自洽，随后实现规范审核 | 草稿可交付，不标实现通过 |
| 实现接入门 | v8 实现 commit = `b3ce055`（或其后含 G12 的 commit）、DB/schema 版本、**命名扫描**、闭环证据 | 阻止正式 T0 接入；固定输入计算试验不替代 |
| 功能发布门 | 阶段全部子例、隔离验证、capability 分层报告 | 不发布未验证支持面；不把基础安全推迟到 T8 |

**命名扫描门（**〔判审 graft〕**）**：T0 与 T8 各 MUST 运行一次命名扫描，断言 v11 引入的全部新对象名（**表／列／函数／视图／触发器／约束／索引／角色／event_type／GUC**）与冻结 v8 的 **12116 行** SQL（= **基线 `b3ce055` 的 14 个 SQL 文件逐文件行数之和**；工作树因已合并 G12 为 12686 行，**不作为计数基准**）、v10 的 27 行对象登记表（`v10-dev.md:134-162`）**零碰撞**，并把扫描结果落为工件。**〔审阅修正〕nit：对象类补齐 `视图/触发器/约束`** —— v11 引入了 `v11_replay_scores` 视图与 D5/D7/D9 及 §2.3 的一系列命名触发器、以及 `session_events_*`/`v11_replay_candidates_one_incumbent` 等命名约束/索引，原文的类别清单漏掉它们，扫描便不覆盖。这是**唯一**能机械保证零回归不受命名冲突破坏的检查。

### 10.2 T0–T8

**stage key = 单一 `tree`**（`v8/load.py` 新增键，位置在所有既有文件之后）；`STAGE_THROUGH['tree']` MUST 恒等于 `len(SQL_LOAD_ORDER)`，且每追加一个 SQL 文件同一 commit 提数（§2.5）。所有 gate 的 `setup_db.py` 都 `DROP/CREATE` 自己的库并以 `STAGE='tree'` 加载**全部已注册 SQL**（含全部 14 个 v8 文件）—— 这是「共享路径烟测」得以成立的前提。

| 阶段 | 目录 / 门 / 数据库 | 范围 | 独立价值（为什么它自己就值得做） | 验收要点 |
|---|---|---|---|---|
| **T0** 基线固化与 schema 增量 | `v8/tree/test_base.py` / `agent_v8_tree_base` | 冻结基线 `b3ce055`；`v11_schema_delta.sql`（§2.1 **D1–D9** + T1/T2 两张 receipt 表 + **全部新表的完整 DDL 骨架**：`v11_tree_bindings`/`v11_tree_receipts`/`v11_node_scores`/`v11_node_artifacts`/`v11_derived_nodes`/`v11_derived_sources`/`v11_probe_batches`/`v11_probe_cells`/`v11_replay_policies`/`v11_world_sets`/`v11_replay_plan`/`v11_replay_candidates`/`v11_replay_episodes`/`v11_policy_pointer`/`v11_rollouts` —— **只建表/列/约束/索引 + immutability 触发器骨架**；**〔审阅修正〕low：D5（`session_mode` write-once）、D7（模式门）、D9（`parent_is_tree_root` 计算）这三个 `session_events` 行为触发器归 T1 落**（T0 只建它们依赖的列/索引，故 T1 ⑦ 的模式门 fixture 依赖 T1 而非 T0），**行为函数与视图归各自里程碑**）；`load.py` 追加 + `STAGE_THROUGH['tree']`。**〔审阅修正〕high：依赖单向** —— 全部 FK 目标表在 T0 一次落齐，`v11_probe_batches.episode_id`/`rollout_id` 的外键与 T2 的 W 解析触发器因此从 T0 起即有目标表，MUST NOT 出现「表定义含该列」与「该列在下一阶段落」并存 | 一次**零行为变化**的增量：既有 runtime 逐字节不变，仅多出未被使用的列与空表/空函数 | ①**共享路径烟测门（**〔审阅修正〕** blocking）**：在 tree 库（含全部 15 文件）内实跑一次 `v_append_events` 线性追加、一次 `v_fork_session`、一次 `v_complete_effect` **路径触及的六处 ordinal 分配点**、一次 `v_compat_fork` —— 证明 ALTER 之后**热路径**仍通（这是「旧门全绿」**不能**证明的：旧门的库从来没有这些列）；②`assert len(files_through('tree')) == len(SQL_LOAD_ORDER)` + **全部 15 张 v11 新表可装载**（`\dt` 断言，含 FK 目标表 `v11_replay_policies`/`v11_replay_episodes`/`v11_rollouts`/`v11_world_sets`）；③**G12 SQL 闭包 name-set 断言（**〔审阅修正〕**blocking）**：`git diff --name-only b3ce055 -- 'v8/*.sql'` 的文件集合 MUST **恰等于** G12 六文件闭包 `{effect, events, repair, retry, takeover, tools}`（§2.5），且 v11 自身的 `v8/*.sql` 改动 MUST NOT 出现其中（**原文的「diff --stat 为空」判据在已合并 G12 的本仓上不成立**，已更正）；④**命名扫描门**；⑤**「树即数据」薄切片**：树可作为纯数据被查询（无 runtime 参与）—— 该断言的**具体形式**在 T1 建立 `v_tree_context` 后补全，T0 只断言「结构可装载」；⑥**G1–G11 + G13 + G12 + G14** 全量重跑绿（**〔审阅修正〕** G12 已作为 `605e866` 合并（`v8/gates/test_gates.py` + 它对 effect/**events**/tools/retry/takeover/repair **六个** SQL 文件的就地改动），G14 为工作区进行中的 `v8/concurrency/test_concurrency.py`（未提交，§0.1）；二者皆「不加自己的 SQL」，故 T0 门清单 MUST 含 G12 **与 G14**（G14 若尚未合并则按其 gate 现状运行并在 §13.3 登记，MUST NOT 静默略过），MUST NOT 再写「`b3ce055` 上无 `gates` 键、G12 无门可跑」）；⑦在**冻结基线 `b3ce055`** 上另跑一次 G1–G11 + G13，证明 v11 增量不依赖 G12/G14。**MUST NOT** 把「旧门测试无需改动即通过」当作兼容性证据 |
| **T1** TREE 模式与 pointer-fork | `v8/tree/test_tree.py` / `agent_v8_tree` | `v_create_tree_session` / `v_tree_append` / `v_tree_set_leaf` / `v_tree_context` / `v_tree_revealed` / `v_tree_legal_actions`（后三者在本阶段仅到 epoch-0 的**降级形态**，episode 绑定在 T4 补全；**〔审阅修正〕blocking：该降级形态取的是不变量 30 禁止的 session 级口径，已登记为偏差 v11-5（§13.2 第 3 项），且 `GRANT EXECUTE` 给策略执行体角色只在 T4 生效 —— T1 阶段该降级视图 MUST NOT 授予该角色**）；`v_tree_fork_child`（§3.5 的 v11 侧 wrapper：tree 父会话拒绝 + 冻结函数零改动） | 「O(1) 分支 + 前缀物理共享 + 路径即上下文」本身就是一个可独立使用的原语 | ①同一 **root** 分叉两次、各追加若干事件后：**前缀物理共享**（`session_events` 行数 = 唯一 event 数，零复制行）；②两条路径各自 `path_ordinal` 正确且互不相同，共享前缀段完全一致；③**seq 无洞**（全表 seq 连续覆盖 1..max）；④**零 UPDATE/DELETE**（前后表行数增量 == append 次数、`max(seq)` 增量 == append 次数）；⑤caller 供 `semantic_input_ordinal` → `SEMANTIC_ORDINAL_FORBIDDEN_IN_TREE`；⑥LINEAR 会话行为逐字节不变（对照 `v8/events/v8_append.sql` 既有输出）；⑦**模式门负向**：TREE 会话上调冻结 `v_append_events` **带公开 ordinal（semantic）与不带 ordinal（observational，如 `session/heartbeat`）两种** → 均稳定拒绝（不是静默第二根，D7 分支 (A)/(B)）；`session_mode` 已有事件后再改 → 拒绝；**`v_tree_set_leaf` 落在 LINEAR 会话 → `TREE_APPEND_ON_LINEAR_SESSION`（D7 分支 (C)）；TREE 会话上调冻结 internal-ordinal 写者 → `TREE_FOREIGN_APPEND`（分支 (B)）；调用方直接 INSERT 一行 `parent_is_tree_root=true` 的非 root 子节点 → 被 D9 覆写/拒绝**；⑧**单子节点负向（非根节点）**：同一**非根**节点插两个子节点 → 拒；**正向**：root 连开 k 个分支 → 全部接受、`\|A(T)\|` 势 = k+1（不变量 24 的 root 例外，§2.1 D8）；**W 宽批可执行性（〔审阅修正〕blocking）**：对 k 条不同已开分支的 frontier **各** `v_tree_append(parent = 该 frontier)` 一次（父 ∈ 已录树的叶，§3.2），断言**全部接受、无一报 `TREE_PARENT_NOT_LEAF`**，且不依赖任何游标移动；⑨**leaf event_key 幂等**：同 `command_id` 重发 → 幂等；换 target 用旧 `command_id` → `IDEMPOTENCY_CONFLICT`（不是静默游标不动）；⑩**ordinal 交织门（**〔审阅修正〕** blocking）**：交替调用 `v_tree_append` 与一次冻结的 `turn/end` 追加（`v8/cancel/v8_closure.sql:388` 路径），断言 `internal_semantic_ordinal` 序列**无洞且严格递增**；⑪**envelope guard 门**：driver/driver_epoch 不符 → `DRIVER_EPOCH_STALE` 零落盘；⑫**byte-equivalence 门（**〔判审 graft〕**）**：两条 append 路径在 canonicalizer 与 key 派生两条共享子面上输出一致；⑬**copy-fork 门**：copy-fork 后向子会话追加必失败（已知负向，§3.5 硬事实 1）；**tree 父会话上 fork 被 `v_tree_fork_child` 拒绝** —— 拒绝发生在 **v11 wrapper 层**，冻结 `v_fork_session` 零改动；绕过 wrapper 直调冻结函数时该拒绝**不生效**（能力边界如实写出）；⑭kill-at-every-boundary：leaf 追加 / ordinal 派生 / seq 分配各点注入崩溃，断言 `next_seq` 不产生洞或跳过；⑮结构检查：**v11 自身**对 v8/v10 冻结文件零改动（相对 v11 的父 commit 的 `git diff`；G12 的既有改动按 §10.2 T0③ 的 name-set 断言排除，**MUST NOT** 以 `b3ce055` 为 diff 端点）；⑯**D7 正向门（**〔审阅修正〕** high）**：LINEAR 会话实跑一次 `v_complete_effect` **路径触及的六处 ordinal 分配点**（`v8/effect/v8_effect.sql:1516,1700,1950,2114`、`v8/tools/v8_tools.sql:523`、`v8/cancel/v8_closure.sql:388` 路径；**行号取自 G12 后工作树，`b3ce055` 对应 1276/1459/1702/1853、464**），断言 `internal_semantic_ordinal` **正常推进、无一被 D7 分支 (C) 误拒**（这是 §2.1 D7 采用会话级 GUC 标记的直接验收向量）；⑰**初始 leaf = root 行（〔审阅修正〕blocking：MED-4）**：`v_create_tree_session` 之后、任何 `session/leaf`/`v_tree_append` 之前，fold `session_events` 得到的 CURRENT leaf MUST **恰为 root 行**（`event_class='observational'`、`event_type='session/tree_root'`、`parent_entry_id IS NULL`）；断言该行**不是** audit（不被 §3.4 的「未知 audit 跳过」规则吞掉）且**不是** semantic（D7 分支 (A) 禁其 ordinal）。**若实现把 root 行写成未知 audit 类型，本门必红**（初始 leaf 无 referent）。对应 §11 子例 T1f |
| **T2** 揭示视图与批合法性 | `v8/tree/test_probe.py` / `agent_v8_tree_probe` | `v11_probe_batches` / `v11_probe_cells`（**表/列在 T0 建**，本阶段装配行为与约束）+ §6.2 全部触发器（`\|C\|≤W` 的 W 解析读 **T0 已建**的 `v11_replay_episodes`/`v11_replay_plan`（离线链）与 `v11_rollouts`（在线链），**无前向依赖**；W 的**取值语义**在 T3 落）；`v_batch_dispatch` 的折叠逻辑。**〔审阅修正〕high：里程碑依赖单向** —— 原文本让 T2 的触发器引用 T4/T6 才创建的对象，T2 的门无法装载 | 可计算的批合法性判定式 + 揭示视图边界，独立于 Dream-RSI 也可被任何 branch-explore 运行时复用 | ①`A(T^{m,k}) = {r} ∪ leaves(O)`（frontier）逐项断言；②逐项拒绝：重复 cell id、`\|C\|>W`、批内父子同批、同分支双 frontier、同 `(episode_id, round_no)` 或 `(rollout_id, round_no)` 重复 各返回稳定码；③折叠与 v8-dev.md:751「按 ordinal 折叠、完成时间仅作观测」一致（不变量 10）：打乱完成顺序 → 语义结果不变 |
| **T3** 在线产出与并行原语 | `v8/tree/test_node.py` / `agent_v8_tree_node` | **在线产出入口**（v11 runtime 模块，只调用既有受控函数 + v11 O 命令）；`v11_node_scores` / `v11_node_artifacts`（含 `parent_artifact_identity` / `world_closure_digest` / `closure_complete`）；`W` 持久对象属性语义 + `v11_probe_batches` 的 **W 离线链（`episode_id → v11_replay_plan.w`）与在线链（`rollout_id → v11_rollouts.w`）**解析（**表在 T0 建**）；probe execution（**非 step**，§6.4）；**在线 rollout 决策面（§6.6）：`v_rollout_open` + `v_rollout_batch` O 命令 + `v11_rollouts`（K1 上限、`rollout_id`、`w`/`beta` 创建时写一次）** | 系统内**首个一等评分/评估对象**（v8 与 v10 都没有）；且它是一个持久的、受策略约束的 fanout 上限原语（全仓目前不存在：`grep -niE 'fanout\|max_parallel\|parallelism\|branch_count\|refine_count'` 在 `v8/` 与 `v10-dev.md` 内为空） | ①score 写入者是 O 命令（读入口创建 → 拒）；②成功语义负向：`error IS NULL AND fail_class='ok'` 即使 `valid=false` 仍算成功；③`n_valid/n_total` 不可用不改变成功判定；④**世界闭包负向**：`closure_complete=false` 的节点作为分支父/世界根 → 稳定拒绝；⑤`parent_artifact_identity` 差量链展开逐跳 `content_sha256` 复核，断链 → `WORLD_DELTA_CHAIN_BROKEN`；⑥probe execution 的边界断言：不创建 step、不写 `effect_requests`/`effect_attempts`/`batches`、不触碰 step/session 终态；⑦外部 IO 在事务外（FakeLLM/FakeTool）；⑧规模 k 的批在 W 个 worker 下 1 个 decision round、`ceil(k/W)` 个 effective sequential rounds；⑨**在线决策面（§6.6，**〔审阅修正〕** high）**：同一策略产物在线与离线走**同一入口形状**（同一 `A(T)` 谓词 + 同一 `\|C\| ≤ W` 触发器 + 同一 `batch_id`/`Observation` 形状）；`K1` 到限后第 `K1+1` 个**非空**批被 `ROLLOUT_ROUND_LIMIT_REACHED` 稳定拒绝，而**空批**在限内正常终止并置 `status='closed'`；**`v_rollout_open` 创建时把 `policy_id`/`w`/`beta` 写一次（之后不可 UPDATE）；`v_rollout_batch` 以 rollout 行为**唯一策略权威**（MAY 读 `v11_policy_pointer` 仅作比较；指针前移 → `ROLLOUT_POLICY_STALE` 零写、不换策略，§6.6 第 3 条 / MED-2）**；**批内 W 个 cell 的 probe execution 各以其自身为追加父（§3.2/§6.2/§6.4），全部落盘、无一 `TREE_PARENT_NOT_LEAF`** |
| **T4** 决策层只读重放 oracle | `v8/tree/test_replay.py` / `agent_v8_tree_replay` | `v_replay_probe` + §1.4 确定性 Child；episode 身份与 per-episode reset（新派生视图游标，签名显式零写）；`v11_replay_episodes`；`v11_reward`（IMMUTABLE，冻结 `numeric_scale` + round-half-even）；`v_tree_revealed`/`v_tree_legal_actions` 的 **episode 级**形态；**`v_replay_episode_open` / `v_replay_settle`（episode 生命周期，§2.3）与 `v_replay_batch`（离线批生产者 + K2 门，§6.6 第 6/7 条）**；**具名 score 读入口 **`v_node_score_read(auth, batch_id, entry_id[]) → Observation[]`**（`STABLE`）与最小权限角色 **`v11_policy_runner`** 的创建（含其**逐函数** `GRANT EXECUTE` 清单 = `v_tree_revealed`/`v_tree_legal_actions`/`v_replay_probe`/`v_tree_context`/`v_node_score_read`，与该角色对**全部 v11 表** + `session_events` 的**零表级权限默认拒绝**（仅五个具名函数 `EXECUTE`；§2.4 的逐函数清单；并附 `REVOKE SELECT ON session_events, v11_node_scores, v11_node_artifacts` 兜底）；§2.4/§7.4/T4③/T5c —— **〔审阅修正〕blocking：HIGH-2 —— 原文只创建/GRANT、未归任何里程碑，现归 T4、落在 `v8/tree/v11_replay.sql`**）。**〔审阅修正〕nit：plan 行的来源** —— T4 的 fixture **直接 INSERT 一行 `v11_replay_plan`**（DDL 骨架在 T0 落齐，`world_set_id` 指向一行 `v11_world_sets`；**该直接 INSERT 是 T4 的测试脚手架；生产路径的创建者是 T6 的 `v_replay_plan_open`，见 §8.2/MED-5**）；plan/candidate 的**行为**（`v11_replay_scores`、`v_policy_select`）在 T6 装配，故 T5a/T5h 引用 `plan_id` 不构成里程碑倒置 | 一个「只读已录结果的确定性模拟器」原语，脱离 Dream-RSI 也可用于任何 replay/回归/影子评估 | ①**黄金向量**：固定**一个 `plan_id`**（其剖面 = `world_set_id + w + k2 + b1 + b2 + numeric_scale + β`，§2.1 T13）下重放逐位可复现（同输入两次调用逐字节相等）；②**零业务/控制写集**逐条对照 `v10-dev.md:366`，并显式列出唯一例外（授权失败 → 恰 1 行 `authz_denial_audits`，§7.3 第 4 条）；③**读集边界（〔审阅修正〕blocking）**：经 `v_node_score_read` 请求揭示集之外的 score → `SCORE_NOT_REVEALED`、空返回；**且裸路径同样关闭**：策略执行体角色 `SELECT … FROM v11_node_scores`/`v11_node_artifacts`，以及 `SELECT … FROM v11_replay_policies`/`v11_probe_batches`（**覆盖全部 v11 表**的默认拒绝抽检）→ **原始 PostgreSQL 权限错误（`42501`）、无稳定 code、无 audit 行**（REVOKE/默认拒绝生效的负向 fixture），score 不由任何第二读入口暴露；④**非法 cell**：传一个内部节点 id / 未揭示之外的节点 → `REPLAY_CELL_NOT_LEGAL`（不是「传 id 就展开」）；⑤**episode 级揭示集**：一次 rollout 完成后，会话级定义会返回整棵树，episode 定义只返回已探节点 —— 断言两者不同；⑥`v11_reward` 为 `IMMUTABLE` 的 grep 门 + half-even 向量；⑦`v_replay_probe`/`v_tree_*` 为 `STABLE` 的 grep 门 + **取锁授权子操作位于 `VOLATILE` 函数内的 grep 断言**（§7.3：PG 禁 `STABLE` 体内 `SELECT … FOR UPDATE`，否则运行期报错）；⑧授权合取失败 → 稳定拒绝 + `authz_denial_audits` 行 + 零内容（**不是**「只读角色可调用」）；⑨**不调 evaluator/renderer**：实现体 grep 断言无 render/serialize/evaluator 调用；⑩episode 的 `policy_id` 在创建时固定，episode 内不可变；⑪**剖面与 β 不可变（**〔审阅修正〕** high）**：`v11_replay_plan`/`v11_replay_episodes` 建立后 `beta` **与** `policy_id` 同样 MUST NOT 被 UPDATE（断言同款）；**每个 `(plan_id, candidate_index)` 上 episode 的世界身份多重集 MUST 等于 `v11_world_sets.members`**（**per-candidate** + **集合/多重集相等**，非计数相等；〔审阅修正〕blocking：MED-3，§7.2/§8.2）；⑫**剖面不可混算（**〔审阅修正〕** blocking）**：同一策略在两个不同 `plan_id`（不同世界集或不同系数档）上各跑一遍 → 视图 MUST NOT 把两批数据平均进同一个 `V^m`（§8.2 反例的修正后形态）；⑬**episode 生命周期（**〔审阅修正〕** blocking）**：`v_replay_episode_open` 只写身份列、`v_replay_settle` 恰一次写结果列；重复结算 → `EPISODE_ALREADY_SETTLED` 拒；批的 FK 在重放期即可满足（无「结算前无 episode 行」死结）；⑭**离线批生产者与 K2（**〔审阅修正〕** high）**：`v_replay_batch` 是唯一的离线批生产者（策略角色无 DML、不能建批）；第 `k2+1` 个非空批 → `REPLAY_ROUND_LIMIT_REACHED` 零写；⑮**`A(T)` 折叠序（**〔审阅修正〕** medium）**：同一 episode 的批按 `round_no` 升序折叠；同 `round_no` 重复 → 撞 `UNIQUE(episode_id, round_no)` 拒；**批的身份列不可变（〔审阅修正〕blocking）**：`UPDATE v11_probe_batches SET round_no = …` 与对该表的 `DELETE` 均被 §2.3 的列作用域触发器稳定拒绝（不变量 26 的读时校验不能被事后换序/删行击穿） |
| **T5** 无损派生 DAG 与钻回 | `v8/tree/test_derived.py` / `agent_v8_tree_derived` | `v11_derived_nodes` / `v11_derived_sources`（含 `source_slice_id`）、`v_derived_build`、`v_derived_expand` | 可恢复压缩本身独立可交付，且与 v10 `CompactHistory` 的减法语义并存不冲突 | ①drill-back 从派生节点递归 CTE 回到 `session_events` 原行、按原 `payload_hash` 逐字节返回；②visited 守卫 + 节点/token 预算生效；③**失败派生不落「已完成」**：summarizer 失败 → 零节点零边，原材料仍可被再次选中；④**逐源授权**：一条边命名了消费者不可读的源 → drill-back 拒绝（不是逐字节返回）；⑤`NOT EXISTS` 集合差 = 「已消费」，MUST NOT 用 flag（schema 断言无 `is_compacted` 式列）；⑥幂等：同 `(session_id, content_hash)` 重试不产生第二条；⑦**消融门（**〔判审 graft〕**，ACM 模板）**：保留写入、仅移除检索路径，断言产生可测的准确率差（`agentic-context-management/src/configs/runtime.py:18-26` 的 `re_mem_noquery` 模板） |
| **T6** 策略版本化、激活与选择 | `v8/tree/test_policy.py` / `agent_v8_tree_policy` | `v11_replay_policies` / `v11_policy_pointer` / `v11_world_sets` / `v11_replay_plan` / `v11_replay_scores` 视图 / `v_policy_stage` / `v_policy_activate` / `v_policy_revoke_active` / `v_policy_select` / **`v_replay_world_set_freeze` / `v_replay_plan_open` / `v_replay_candidate_add`（§8.2 的三个创建者；〔审阅修正〕blocking：MED-5 —— 原文只有 DDL 行、无创建命令）** | 「版本化产物 + CAS 激活 + 确定性离线评估」三者组合本身就是一个可回滚的配置/策略发布面，独立于 Dream-RSI 也可用于任何 A/B 与灰度 | ①`v10-dev.md:644-645` 的指针不变量逐条**落为 v11 对象**（§8.3）：唯一 active 指针、CAS 全量 `expected_active_policy_id + revision`、禁自动回滚、**禁把 `active_policy_id` 回指已撤销的旧产物**（v11 无 retired 状态列，「回指 retired」落为「恢复 MUST 发布全新 identity」）、**禁从状态列推断**（v11 无状态列，故该禁令无对象可犯）；②**跨 W 拒绝**：activate 一个属于另一个 workspace 的策略 → 稳定拒绝（由 T10 的 `workspace_id` 列 + `UNIQUE (workspace_id, policy_id)` 与 T11 的两列复合 FK **在 DDL 层强制**，不再是约定）；③**覆盖完整性**：世界集未全跑（候选的世界身份多重集 ≠ `v11_world_sets.members`，**按集合/多重集相等判**、不是计数相等；MED-3）→ `v11_replay_scores` 返回 `REPLAY_COVERAGE_INCOMPLETE`（不是部分平均）；④`v_policy_select` 算出 `m*` 并 CAS 激活；⑤**真空报告**：`M=1` 时如实报告「保证为真空」，MUST NOT 报告「保证满足」；⑥`v11_replay_policies` immutability 触发器；⑦`v11_probe_batches.status` 闭合迁移表（未列迁移 MUST NOT 执行）；⑧锁位断言：`stage`/`activate`/`revoke_active` 从不取 session 锁；⑨**候选集含现役（**〔审阅修正〕** blocking）**：候选集不含 `is_incumbent` → `v_policy_select` 稳定拒绝 `NO_INCUMBENT_CANDIDATE`、**零激活**（MUST NOT 报 `V^{m*} ≥ V^0`）；每 plan 至多一个现役（部分唯一索引）；⑩**plan 自含剖面**：`v11_replay_plan` 缺 `(world_set_id, w, k2, b1, b2, numeric_scale, β)` 任一项即无法建 plan；跨 plan 比较 MUST NOT 发生；⑪**创建者显式（〔审阅修正〕blocking：MED-5）**：`v11_world_sets`/`v11_replay_plan`/`v11_replay_candidates` MUST 各由 `v_replay_world_set_freeze`/`v_replay_plan_open`/`v_replay_candidate_add` 创建（无 ad-hoc DML 路径，§7.1 的「一等对象由 O 命令创建」规则）；`v_replay_world_set_freeze` 冻结时对 `member_count = |H_t 已 closed rollout 树|` 断言、不等 → 稳定拒绝（= T9c 的执行点） |
| **T7** 节点世界（可选加速器） | `v8/tree/test_world.py` / `agent_v8_tree_world` | §5.1 的 artifact-only 世界（已由 T3 建表，本阶段补全闭包校验与差量链回放）；§5.3 的 `workspace_handles` 前沿加速器 | 给了 Dream-RSI「每个节点一个世界」在 pg-agent 上的**可行近似**，同时不破 live-handle 墙 | ①artifact-only 路径全绿（无 handle 也能跑通一次 replay）；②加速器路径：yield 前 checkpoint 覆盖最新已完成执行态或显式 `workspace/lost`；四项 fail-closed 拒绝各 ≥1 负向；③加速器**必须有非 handle 兜底**：禁用加速器后同一 episode 仍可重放（结果一致或按规范明确降级）；④`WORKSPACE_LOST` 不得用「旧但 digest 自身正确」的 checkpoint 消解 |
| **T8** Dream-RSI 端到端（**终局里程碑**） | `v8/tree/test_loop.py` / `agent_v8_tree_loop` | 串起 online rollout → 版本化策略 → offline dreaming → redeploy；`v11_replay_scores` + `v_policy_select` 的端到端闭合 | 端到端环本身 | ①**单调不退化**：`V^{m*} ≥ V^0`，断言读自 `v11_replay_scores` 视图，且**前置**断言候选集含现役（`is_incumbent`；缺则 `NO_INCUMBENT_CANDIDATE`，不得报满足）；②`M ≥ 2` 的候选集被接受；`M=1` 时报真空；③端到端复测 T4 的零写集（重放世界全程只读）；④策略版本血缘可回溯（每次激活 revision 单调）；⑤**命名扫描门**（第二次）；⑥**全量回归**：T0–T7 全部门 + G1–G11 + G13 + G12 + **G14**（**〔审阅修正〕LOW-3：G12 已 `605e866` 合并、在列，原「+ G12 若已落」的条件式已删**；**〔审阅修正〕（终轮）**：**G14（`v8/concurrency/`，工作区进行中，§0.1）** 与 T0⑥ 同款 —— 若尚未合并则按其 gate 现状运行并在 §13.3 登记，MUST NOT 静默略过；本项门清单**继承 T0⑥ 的集合**，原文本漏列 G14 已补）；⑦四件收尾工件齐备（§13.2）；⑧**redeploy 是可观测事件（**〔审阅修正〕** high）**：`v_policy_activate` 之后**下一次** `v_rollout_open` 写入的 `v11_rollouts.policy_id` MUST 等于新激活的指针目标（指针→读数一致），而非仅出现在叙述里；且**该 rollout 中途指针再前移时**，其 `v_rollout_batch` MUST 以 `ROLLOUT_POLICY_STALE` 拒绝（rollout 单策略，§6.6 第 3 条）；该次在线 rollout 的 `K1` 轮与批形状与离线同款（§6.6） |

### 10.3 里程碑文件所有权与零回归义务

**只许该阶段改**；未列出的既有文件一律不动（对齐 `v8-p1-grant-generation-p0c-plan-2026-09-16.md` 的「文件所有权」段）。

| 阶段 | 新建文件（本阶段独占） | 允许修改的既有文件 | 零回归义务（每阶段同款，不得豁免） |
|---|---|---|---|
| T0 | `v8/tree/__init__.py`、`v8/tree/v11_schema_delta.sql`、**`v8/tree/setup_db.py`（T0 独占创建；`DB=agent_v8_tree_base`、`STAGE='tree'`）**、`v8/tree/test_base.py` | `v8/load.py`（**仅**末位追加条目 + 新增 `tree` 键；**既有键值零改动** —— `b3ce055` 上 12 键，工作树另含 G12 `gates`、G14 `concurrency`，共 14 键，§0.1；`tree` 键 MUST 追加在 `concurrency` 之后）、`v8/README.md`（新增 stage 行 + 运行命令）、矩阵、台账 | ①G1–G11 + G13 + G12 + G14 全量实跑为 0；②`len(files_through('tree')) == len(SQL_LOAD_ORDER)`；③共享路径烟测（T1a–T1d）全绿；④**name-set 断言（〔审阅修正〕blocking）**：`git diff --name-only b3ce055 -- 'v8/*.sql'` 集合 **恰等于** G12 六文件闭包，且无 v11 自身的 `v8/*.sql` 改动（§2.5、§10.2 T0③） |
| T1 | `v8/tree/v11_tree.sql`、`v8/tree/test_tree.py` | `v8/load.py`（追加 + `tree` 提数）、`v8/README.md`、矩阵（**不改 row 11**）、台账、**`v8/tree/setup_db.py`（T0 建，后续阶段仅改其 `DB=` 字面值）** | ①T0 全部门 + G1–G11 + G13；②tree stage 加载集断言；③**v11 自身**对 v8/v10 冻结文件零改动（相对 v11 父 commit 的 `git diff`；G12 既有改动见 T0③ 的 name-set 断言） |
| T2 | `v8/tree/v11_probe.sql`、`v8/tree/test_probe.py` | 同上 | 同上（T0/T1 全部门回归） |
| T3 | `v8/tree/v11_node.sql`、`v8/tree/runtime_probe.py`（v11 runtime 模块）、`v8/tree/test_node.py` | 同上；**`v8/loop/runtime.py` 只读、MUST NOT 编辑** | 同上；另断言 probe execution 不触碰 `steps`/`effect_requests`/`effect_attempts`/`batches` |
| T4 | `v8/tree/v11_replay.sql`（含 `v_replay_probe`/`v11_reward`/**`v_node_score_read`** 与最小权限角色 **`v11_policy_runner`** 的创建，§2.4/§7.4）、`v8/tree/test_replay.py` | 同上 | 同上（**〔审阅修正〕blocking：HIGH-2** —— score 读边界与策略角色的**实施点在此**；T3 的 `v11_node_scores`/`v11_node_artifacts` 表由本阶段的 `v_node_score_read` + **§2.4 的零表级权限默认拒绝（覆盖全部 v11 表，并附三张表的显式 `REVOKE SELECT`）** 保护） |
| T5 | `v8/tree/v11_derived.sql`、`v8/tree/test_derived.py` | 同上 | 同上 |
| T6 | `v8/tree/v11_policy.sql`（含 `v_replay_world_set_freeze`/`v_replay_plan_open`/`v_replay_candidate_add` 三个创建者，§8.2/MED-5）、`v8/tree/test_policy.py` | 同上 | 同上 |
| T7 | `v8/tree/v11_world.sql`、`v8/tree/test_world.py` | 同上 | 同上 |
| T8 | `v8/tree/test_loop.py` | 同上 + Closeout 汇总 | ①T0–T7 全部门 + G1–G11 + G13 + G12 + **G14** **全量**实跑为 0（**〔审阅修正〕LOW-3**：原「+ G12 若已落」条件式已删；**〔审阅修正〕（终轮）**：G14 与 T0⑥/T8⑥ 同款，未合并则按其 gate 现状运行并在 §13.3 登记）；②命名扫描门；③四件收尾工件齐备 |

**`v8/tree/setup_db.py` 单一归属（〔审阅修正〕nit）**：九阶段共用**同一个** `v8/tree/setup_db.py` —— **它由 T0 独占创建、后续阶段只许改其 `DB=` 一行字面值**（避免原文「九个阶段各自独占同一路径」的矛盾）。各阶段 DB 名：T0 `agent_v8_tree_base`、T1 `agent_v8_tree`、T2 `agent_v8_tree_probe`、T3 `agent_v8_tree_node`、T4 `agent_v8_tree_replay`、T5 `agent_v8_tree_derived`、T6 `agent_v8_tree_policy`、T7 `agent_v8_tree_world`、T8 `agent_v8_tree_loop`（`STAGE` 恒为 `'tree'`）。

**命名空间纪律**：T1–T8 各自追加 SQL 文件时，`STAGE_THROUGH['tree']` MUST 在同一 commit 提数（§2.5）；**任一阶段不得新建第二个 stage key**（单一 `tree` 键 = 单一加载集，避免「哪个 stage 加载哪些文件」的分歧）。

## 11. fixture 清单〔D3〕

所有子例共享以下维度；下表的覆盖值替换默认值，因此不是省略输入/写集/恢复的测试标题。

固定底座 F：`W=2`、`S=s`、`T=t`、driver active / 无 cancel / 有效 claim；固定 logical history；世界集 `WS = {w1, w2}`（t=2）。

F 的冻结 profile（= `v11_replay_plan` 的一行，§2.1 T13）：`world_set_id = WS`、`k2=3`、`b1=0`、`b2=1`、`numeric_scale=6`、**`β=1`（论文未给默认值，此为本 fixture 的固定取值；属 §13.2 未覆盖项）**、`w=2`（= F 的固定 `W`；**〔审阅修正〕LOW-5(b)：原 `W_max=4` 全文无定义，改为 T13 剖面必需的 `w` 列**）、漂移容差 0。

命令域：`C1`/`C2` = 不同 command_id；`C1×2` = 全 payload 原样重发同 ID。**tree 命令与 v8 session 命令**共享 `session_id` 但**独立 receipt 域**（§3.3）—— 子例 **`T1e`** 专测「同 session 同 command_id 跨路径」必须**稳定拒绝 `CROSS_DOMAIN_COMMAND_ID_REUSE`**，不是静默 `binding_replay`（**〔审阅修正〕** 原引用名 `M1` 与 §13.3 台账的缺陷号 M1 相撞，且 §11 表里从未有该行；现改名 `T1e` 并补入下表）。

**标签说明（**〔审阅修正〕** nit：T5g 缺口收口）**：本表**无 `T5g` 标签** —— 原 `T5g`（`v_policy_select` 候选集子例）属 **T6** 对象、T4 阶段不存在，已并入 **T7i**（见 T7i 行的迁移注）。子例编号**不重排**（`T5h`/`T5i` 保持原标签），以免与 §13.3 台账的 M1 及本文其它引用相撞。

| 子例 / 阶段 | 固定输入与命令序列 | 断言 |
|---|---|---|
| T1a / T0 | tree 库内 `v_append_events` 线性追加一次 | 与 `b3ce055` 行为逐字节相同；`session_events` 行数 +1 |
| T1b / T0 | tree 库内 `v_fork_session` 一次 | 前缀复制成功；子会话 `max(seq)=N`、`next_seq=1`（负向事实被**断言**为已知，不是意外） |
| T1c / T0 | tree 库内 `v_complete_effect` **路径触及的六处 ordinal 分配点** | 六处全部成功；`internal_semantic_ordinal` 连续 |
| T1d / T0 | tree 库内 `v_compat_fork` 一次 | 语义与 `v_fork_session` **不同**且被显式记录（A84 一致性断言） |
| T1e / T1 | 同一 session 上先用 `C1` 调 `v_append_events`、再用 **同一 `C1`** 调 `v_tree_append` | **稳定拒绝 `CROSS_DOMAIN_COMMAND_ID_REUSE`**（§3.3 的只读跨域检测：命中线性 binding/receipt ⇒ 零写；第三条 receipt 域不被线性 receipt 命中），**不是**静默 `binding_replay`；零跨域 receipt 写入（B5/§3.3 的**唯一**验收向量） |
| T1f / T1 | `v_create_tree_session` 后、任何 `session/leaf`/`v_tree_append` 之前，fold 该会话的 `session_events` | CURRENT leaf **恰为 root 行**（`event_class='observational'`、`event_type='session/tree_root'`、`parent_entry_id IS NULL`）；该行非 audit、非 semantic；root 是**普通事件**故初始 leaf 有 referent（MED-4） |
| T2a / T1 | **root** 分叉两次 + 各追加 2 事件。**可执行序列（〔审阅修正〕blocking）**：`v_tree_append(root→b1)` → `v_tree_append(b1→b1′)` → `v_tree_append(root→b2)` → `v_tree_append(b2→b2′)`（第 3 步父 = root、第 4 步父 = b2，均 ∈ **已录树的叶**，§3.2；**MUST NOT** 要求「父 = 当前 leaf」） | 前缀物理共享（行数 = 唯一 event 数）；`path_ordinal` 两条互异且前缀段一致；seq 无洞；零 UPDATE/DELETE；**root 连开 k 个分支全部接受，`\|A(T)\|` 势 = k+1**（D6 root 例外位的正向向量）；**四步全部成功、无一报 `TREE_PARENT_NOT_LEAF`** |
| T2b / T1 | LINEAR 会话跑既有 fixture | 输出逐字节不变 |
| T2c / T1 | TREE 会话上调 `v_append_events`：①带 `semantic_input_ordinal`（semantic）；②不带 ordinal（observational，如 `session/heartbeat`） | ①`SEMANTIC_ORDINAL_FORBIDDEN_IN_TREE`；②`TREE_FOREIGN_APPEND`；**两者皆无第二个根**（`parent_entry_id IS NULL` 行仍恰 1 条） |
| T2d / T1 | `session_mode` 写一次约束 | 已有事件后改 mode → 拒绝 |
| T2e / T1 | **非根**节点插两个子节点 / **root** 连开 k=3 个分支 | 前者被单子节点约束拒绝；**后者全部接受**、`\|A(T)\|` 势 = 4（不变量 24 的 root 例外，负向与正向成对） |
| T2f / T1 | `v_tree_set_leaf` 同 `command_id` 重发 / 换 target 同 ID | 前者幂等、后者 `IDEMPOTENCY_CONFLICT` |
| T2g / T1 | 交织 `v_tree_append` 与冻结 `turn/end` 追加各 3 次 | `internal_semantic_ordinal` 无洞、严格递增（**八处分配点同一公式**） |
| T2h / T1 | envelope driver/epoch 不符 | `DRIVER_EPOCH_STALE` 零落盘 |
| T2i / T1 | copy-fork 后向子会话追加；`v_tree_fork_child` 的 tree 父会话拒绝；绕过 wrapper 直接调冻结 `v_fork_session` | 追加失败（已知负向）；**wrapper 路径 → 稳定 `FORK_FROM_TREE_SESSION`**；**直调路径 → 该拒绝不生效**（能力边界被**断言**，不是被当作保证，§3.5） |
| T2j / T1 | kill-at-every-boundary（leaf / ordinal / seq 三点） | `next_seq` 不产生洞或跳过 |
| T2k / T1 | TREE 会话上调冻结的 internal-ordinal 写者（`v_complete_effect` 路径） | `TREE_FOREIGN_APPEND` 零落盘（不产生第二个 NULL-parent 行；D7 分支 (B)） |
| T2l / T1 | LINEAR 会话上调 `v_tree_set_leaf` | `TREE_APPEND_ON_LINEAR_SESSION` 零落盘（D7 分支 (C)；该行两 ordinal 皆 NULL，旧条件永不触发） |
| T2m / T1 | 直接 INSERT 一行 `parent_is_tree_root=true` 的**非 root** 子节点 | 被 D9 覆写为 false（或拒绝）；D6 单子节点约束仍生效，该位不得被用来绕过 |
| T2n / T1 | **同一事务**内：tree 会话先 `v_tree_append`（置 `v11.tree_append` GUC），再走冻结闭包路径追加一条 `turn/end`（`v8/cancel/v8_closure.sql:390-399` 形态，显式列清单 ⇒ `parent_entry_id` 取 NULL、ordinal 为 `internal_semantic_ordinal`） | 第二个 NULL-parent 行被 **D7 分支 (B2)** 以 `TREE_SECOND_ROOT` **稳定拒绝**（GUC 已被同事务置过，故 (B) 会放行 —— 该负向向量正是为 (B) 的漏洞而设，§2.1 D7） |
| T3a / T2 | `A(T^{m,k}) = {r} ∪ leaves(O)`（frontier）全集枚举 | 与派生视图一致；且断言 `A(T^{m,k}) ≠ O`（frontier 是 `O` 的边界集，不变量 30） |
| T3b / T2 | 重复 cell id / `\|C\|=W+1` / 批内父子 / 同分支双 frontier | 稳定码各自拒绝 |
| T3c / T2 | 合法批，两提交序（打乱完成顺序） | 语义结果不变（不变量 10）；`ceil(k/W)` 折算正确 |
| T4a / T3 | 在线产出入口执行一次（FakeLLM/FakeTool） | score/artifact 行由 O 命令创建；无 step/effect/batch 行；外部 IO 在事务外 |
| T4b / T3 | `valid=false` 但 `error IS NULL AND fail_class='ok'` | 仍算成功评估 |
| T4c / T3 | `closure_complete=false` 的节点作分支父/世界根 | 稳定拒绝 |
| T4d / T3 | 差量链断一跳 | `WORLD_DELTA_CHAIN_BROKEN` |
| T4e / T3 | 在线 rollout：`v_rollout_open`（`K1` 轮）→ 写 `K1` 个非空批 → 再传第 `K1+1` 个非空批；另跑一次空批 | 第 `K1+1` 个非空批 → `ROLLOUT_ROUND_LIMIT_REACHED`；空批 → `status='closed'`、`k_done` 不减（§6.6 第 4 条） |
| T4f / T3 | rollout 进行中 `v_policy_activate` 换指针，再调 `v_rollout_batch` | `ROLLOUT_POLICY_STALE` 零写（rollout 单策略、`policy_id`/`w`/`beta` 创建时固定，§6.6 第 2/3 条）；`v_rollout_open` 新建的 rollout 才用新 `policy_id`（T8⑧） |
| T5a / T4 | 固定 `plan_id`（剖面 = `world_set_id + w/k2/b1/b2 + numeric_scale + β`）重放两次 | 逐字节相等；golden 保存完整输入/输出 bytes。（**〔审阅修正〕** 原「同一 plan 内 `count(distinct world_session_id) = member_count`」是**视图级**断言、依赖 T6 的 `v11_replay_scores` 视图，已**移入 T6 组**（T7b/T7j）；T4 只断言重放逐位可复现。**该 `plan_id` 行由 T4 的 fixture 直接 INSERT**（§10.2 T4 范围句；plan 的**行为**在 T6），故不构成里程碑倒置） |
| T5b / T4 | 清点全部写集（正常重放）与授权失败变体 | 正常重放：与 `v10-dev.md:366` 清单逐条为 0；授权失败变体：除唯一例外（恰 1 行 `authz_denial_audits`）外逐条为 0 |
| T5c / T4 | 请求揭示集之外的 score（经 `v_node_score_read`）；以及裸 `SELECT` 两张 `v11_node_*` 表（策略执行体角色） | 经具名入口：`SCORE_NOT_REVEALED`、空返回；裸路径：**原始 PostgreSQL 权限错误（`42501`），无稳定 code、无 audit 行**（REVOKE/默认拒绝生效；**与 T9d 同形**；§1.3②/§2.4/§7.4，〔审阅修正〕blocking） |
| T5d / T4 | 传一个内部节点 id / 未允许的 cell | `REPLAY_CELL_NOT_LEGAL` |
| T5e / T4 | 一次 rollout 完成后对比会话级定义 vs episode 级定义 | 前者返回整棵树、后者只返回已探节点（**断言不同**） |
| T5f / T4 | `v11_reward` half-even 向量（含 `numeric_scale` 边界与偶舍入） | 与手算逐位一致 |
| T5h / T4 | 离线 dreaming 一轮：`v_replay_episode_open` → `v_replay_batch` → `v_replay_probe` → `v_replay_settle` | 批在 episode 行创建后即可持久化（FK 满足，无时序死结）；`v_replay_settle` 恰一次；**重复结算 → `EPISODE_ALREADY_SETTLED` 拒**；策略执行角色**不能**建批（无 DML，`v_replay_batch` 是唯一生产者） |
| T5i / T4 | 同一 episode 连写 `k2+1` 个非空批 | 第 `k2+1` 个被 `v_replay_batch` 稳定拒绝 `REPLAY_ROUND_LIMIT_REACHED`、零写（K2 上限，§6.6 第 7 条） |
| T5j / T4 | 深度 2 链 `r→a→b`，观测树 = 全部三节点（`O = {r,a,b}`） | **两个集合被钉开**：`\|O\| = 3` ⇒ `n_revealed = \|O\| − 1 = 2`（= 论文 `N = \|T^{m,k*}_i\| − 1`）；而 `\|A(T^{m,k})\| = \|{r} ∪ leaves(O)\| = \|{r,b}\| = 2` —— `A(T^{m,k})` 是 `O` 的 **frontier**，**不是** `O`（不变量 30、§6.2）。若把 `O` 误定义为 `{r} ∪ observed leaves`（终轮之前的写法），`n_revealed` 会是 `1 ≠ 2`，本门必红 |
| T6a / T5 | `v_derived_expand` 回原行 | 按原 `payload_hash` 逐字节返回 |
| T6b / T5 | summarizer 失败一次 | 零节点零边；原材料仍可再次选中 |
| T6c / T5 | 边指向不可读的源 | drill-back 拒绝 + 拒绝行 |
| T6d / T5 | 同 `(session_id, content_hash)` 重试 | 不产生第二条 |
| T6e / T5 | `re_mem_noquery` 式消融 | 保留写入、移除检索路径 → 可测的准确率差 |
| T7a / T6 | `activate` 目标属于另一个 workspace | 稳定拒绝 |
| T7b / T6 | 世界集只跑了一个世界 | `REPLAY_COVERAGE_INCOMPLETE`（该候选的世界身份多重集 ≠ `v11_world_sets.members`；MED-3：按集合/多重集相等判） |
| T7c / T6 | `activate`/`revoke` 两提交序共享 `expected` 指针 | 唯一赢家；后者 CAS 失配稳定拒绝；revision 单调 |
| T7d / T6 | `stage`/`activate`/`revoke_active` 的锁轨迹 | 从不取 session 锁；pointer→generation 子序 |
| T7e / T6 | `v11_replay_policies` 上 UPDATE | immutability 触发器拒绝 |
| T7f / T6 | `v11_probe_batches.status` 非法迁移（合法迁移写者：`v_batch_dispatch`→`revealed`、`v_replay_settle`/rollout 关闭→`closed`，LOW-4）；以及身份列（`round_no`/`episode_id`/`rollout_id`/`session_id`）的 UPDATE 与整行 DELETE | 前者被闭合迁移表拒绝；后者被 §2.3 的列作用域不可变触发器拒绝（**〔审阅修正〕blocking**） |
| T7g / T6 | 候选集**不含**现役（无 `is_incumbent`） | `v_policy_select` 稳定拒绝 `NO_INCUMBENT_CANDIDATE`、零激活；视图 MUST NOT 报 `V^{m*} ≥ V^0`（论文 `txt:233-236,337-339` 的构造未被满足） |
| T7h / T6 | 同一策略在两个不同 `plan_id`（不同世界集 / 不同 b1 档）上各跑满 t 个世界 | 视图按 `plan_id` 分组，**MUST NOT 把两批平均进同一个 `V^m`**；一次 `v_policy_select` 只接受一个 `plan_id`（§8.2 反例的修正后形态） |
| T7i / T6 | `M=1`、`M=3`（均含 `is_incumbent`）与 `M=3` 但**缺** `is_incumbent` 三种候选集（**〔审阅修正〕** 原 `T5g / T4` —— `v_policy_select` 是 T6 对象，T4 阶段不存在，已移入本组） | 前者报真空、次者算出 `m*`、后者 → `NO_INCUMBENT_CANDIDATE` 零激活 |
| T7j / T6 | 同一 plan 的两个候选覆盖**不同世界子集**（m1 覆盖 `{w1,w2}`、m2 只覆盖 `{w1}`）；**及 MED-3 向量**：候选在 `{w3,w4}` 上跑、`members = {w1,w2}` | 完整性断言 MUST 按 `(plan_id, candidate_index)` 判 → m2 → `REPLAY_COVERAGE_INCOMPLETE`（**不得**因 plan 级 `distinct = member_count` 放行；§7.2 的 per-candidate 反例）；MED-3 向量计数与 `member_count` **同为 2**，只靠计数相等会放行，MUST 因**集合/多重集相等**判失败 → `REPLAY_COVERAGE_INCOMPLETE` |
| T8a / T7 | 禁用加速器后同一 episode 重放 | 与启用加速器一致或按规范明确降级 |
| T8b / T7 | 加速器 yield / `WORKSPACE_LOST` 四拒绝各一 | fail-closed；不得用旧 checkpoint 消解 |
| T9a / T8 | 端到端：online → dreaming → select → redeploy | `V^{m*} ≥ V^0` 读自视图；零写集复测；血缘可回溯 |
| T9b / T8 | 命名扫描 | 与 v8 **12116 行（`b3ce055`）** + v10 27 行登记表零碰撞 |
| T9c / T8 | 冻结一个 `member_count < t` 的世界集（`t` = 已 `closed` 的 rollout 树数） | `v_replay_world_set_freeze` 冻结时 MUST 断言 `member_count = t`，不等 → 稳定拒绝（世界集与 `H_t` 绑定，§8.2；断言落在该命令体内，MED-5）；断言 `(1/t)` 的分母不是世界集自指 |
| T9d / T8 | 在线阶段的**历史条件化**负向：策略角色经**具名读入口**触达在线历史；以及**裸 `SELECT`** `v11_replay_*`/`session_events` | 经具名入口：授权合取失败 → **稳定拒绝 + `authz_denial_audits` 行**；**裸路径：原始 PostgreSQL 权限错误（`42501`），无稳定 code、无 audit 行**（REVOKE/默认拒绝使稳定-coded 拒绝**不可达**，**与 T5c 同形**）；**如实记录**该阶段无 `π_t(H_{t-1})`（§6.6 第 8 条，§13.2 B 段） |

**所有子例当前报告状态均为未运行**，上表数字为预期而非结果。每个 crash 点用独立连接观察提交可见性，不能只检查调用返回；同 ID 响应丢失与新 ID 业务重试分别报告。

## 12. 明确不做〔D1〕

- **不修改 v8 的 18 条不变量、冻结 v8 SQL（14 文件，`b3ce055` 上 12116 行）、v10 冻结规格、v9，或 v1–v9 任何代码。** v11 的全部能力以在 `v8/load.py` 末尾追加新文件的方式落地。
- **不新增 `sessions.next_internal_ordinal`（或任何同类计数器列）**；不修改八处既有的 `max(internal_semantic_ordinal)+1` 分配点。
- **不新增 path-relative ordinal 存储列**（不变量 23）。
- **不放松 `steps_one_active_per_session`**、不放松 `v_create_step` 的 `ACTIVE_STEP_OPEN`、不改 `v_session_finalize` 的单末步派生。
- **不给 `session_events` 增加 RLS 策略**，也不以 RLS 声称承担分支隔离；分支边界 = episode 级揭示集（不变量 30 的 `O`）+ 逐入口授权（`v_node_score_read` 等）+ 最小权限角色（该角色**零表级权限**，对**全部 v11 表**与 `session_events` 一律默认拒绝，并附 `session_events`/`v11_node_scores`/`v11_node_artifacts` 的显式 `REVOKE SELECT` 兜底，§2.4）。
- **不把 `v_fork_session`（或 `v_compat_fork`）当作树构建原语**；不声称 copy-fork 是隔离边界；不声称 fork 后 `entry_id` 被逐字携带。
- **不新增 per-node live handle**；不使 `workspace_handles` 变成「每节点一个 handle 的树」；不继承 live handle（v8/v10/pi 三方一致的墙）。
- **不恢复自动 recall**、不把无损 DAG 塞进 v10 装配路径、不改 v10 `CompactHistory` 的减法语义。
- **不给 inspection / 读入口增加 receipt、业务审计落表或隐式准备**；重放 oracle 对**被读对象**是真零写。**唯一例外（全文一致）**：授权拒绝遥测行 `authz_denial_audits`（不变量 25/§2.4/§7.4）—— 它不是业务审计，且不含 receipt/plan/manifest/trace；**该例外只在具名读入口的授权合取失败时产生**，裸 `SELECT` 被权限层拒绝（`42501`）时不产生任何行（§1.3 第 2 条、§2.4、T5c/T9d）。
- **不在 Bind 或任何重放路径执行网络、foreign table/dblink、live workspace 读、renderer 或宿主 handler**（v10 不变量 20）。
- **不在事务内做外部 IO**（v8 不变量 4）—— 这是 dream-loop 最容易被违反的一条，凡「离线 dreaming 作业」的实现 MUST 把 LLM/工具调用放在事务外（FakeLLM/FakeTool 亦同）。
- **不设 `plan_grid`/`GridPlan` 的替代（〔审阅修正〕medium：接受偏差，如实登记）**：论文的 `plan_grid` 返回 `GridPlan(branch_count=W, refine_count=R)`，由 runner 约束 `1 ≤ W ≤ context.hard_max_branch_count`、`0 ≤ R ≤ context.hard_max_refine_count`（`txt:1194-1245`）。v11 **不移植**该抽象（§A.1 的理由：substrate 产物非机制），但也**未提供任何替代的每周期结构上界** —— 对「一个策略在一个周期内可开多少 root 分支（`branch_count`）/每条分支可深化多少（`refine_count`）」，v11 只有**间接**的**轮**上限（在线 `K1`、离线 `K2`），**不是**分支/深度上限。故 v11 允许策略无界地开分支或深化单条分支；此差异**接受并登记**（§13.2 B 段），MUST NOT 声称已实现论文的网格上界。
- **不 host 元层策略作者 agent**；不新增元 agent 命令/队列/等待态（§9.2）。
- **不引入 pgAgentOS RAG、http-skill、无授权逻辑的 role 列、glass-box thought 叙事或 poll_job 第二队列**；不默认消费 v9 pack、不搬 ctx 控制表/PGMQ/apply 协议。
- **不做在线权威 artifact 驱逐**；销毁仅显式受控离线流程。
- **不在 v11 内解决 probe execution 的 exactly-once**（§6.4 的诚实让步），也不把该让步包装成「已保证」。
- **MUST NOT 移植 pi-lcm 的 `is_compacted` 就地 UPDATE、`dedup_hash` sha1 截断式幂等键、`MAX(seq)+1` 分配器、单文件 DB、进程内互斥**；**MUST NOT 移植 ACM 的位置式身份（列表切片）、LLM-in-the-read-path 检索、`'lossless'` 一词的无限定用法**；**MUST NOT 移植 Dream-RSI 的 `attempt_*/` 目录布局、`beta_sweep.json` 文件形态、`GridPlan`/`plan_grid` 的冻结网格抽象、进程内 `question.*` 对象接口、§4 的具体资源配置数值**（论文未给机制层默认值）。
- **本轮不写生产代码、补丁、可执行 DDL/迁移**，不宣称未执行的测试、spike 或 runtime gate 已通过。
- 扩大上述范围必须单独审核对 step/seal/取消/unknown/switch/generation drain 的影响。

## 13. 开发路线与收尾工件〔D3〕

### 13.1 四层回归框架（**〔判审 graft〕**，v11 的 DoD 模板）

| 层 | 要求 | 可验证形式 |
|---|---|---|
| **加载面** | 所有 v11 SQL 只以**末尾追加**进 `SQL_LOAD_ORDER`；`STAGE_THROUGH['tree']` 恒等于 `len(SQL_LOAD_ORDER)`；**既有键值零改动**（`b3ce055` 上 12 键；工作树另含 G12 `gates`、G14 `concurrency`，共 **14** 键，§0.1） | `assert len(files_through('tree')) == len(SQL_LOAD_ORDER)`；`git diff` 证明既有键未变 |
| **编辑面** | 不编辑任何 v8 冻结 SQL；schema 改动全部以 `ALTER`/新表写在新文件里（先例 `v8/stream/v8_stream.sql:37-40`）；新列一律带 DEFAULT，使既有显式列 INSERT 无需改动 | **v11 自身**的 `git diff --name-only <v11 父 commit> -- 'v8/*.sql'` 为空（新文件为 untracked；G12 的既有改动按 §10.2 T0③ 的 name-set 断言排除 —— **MUST NOT** 以 `b3ce055` 为端点作「diff 为空」断言，见 §2.5）；实跑共享路径烟测门（**不能只靠 DDL 断言**） |
| **门面** | 每个里程碑 MUST 全量重跑**该 stage 的全部 gate**（`AGENTS.md:26`），退出码 0 才算通过；MUST NOT 在未实跑下声称通过（`AGENTS.md:32`） | 每里程碑的实测输出 |
| **工件面** | 每里程碑四件收尾工件齐备（§13.2） | 逐项核对 |

### 13.2 四件收尾工件（AGENTS.md:27-31，逐里程碑硬性）

1. **`v8/load.py` 注册**：新增 SQL 追加进 `SQL_LOAD_ORDER`，`STAGE_THROUGH['tree']` 提数（§2.5）。
2. **`docs/reviews/v8-p0ab-conformance-matrix-2026-09-16.md` 更新**：
   - 表头逐 gate 计数行追加 v11 gate 计数（**〔审阅修正〕** 该表头在**当前 HEAD 已含** `… G10 144 / G11 207 / G13 153 / G12 165 PASS`（G12 已随 `605e866` 合并、**在列**；`b3ce055` 时刻的表头为 `… G10 143 / G11 207 / G13 153`、无 G12）。v11 MUST NOT 改动这些既有数字；**G14（`v8/concurrency/`，工作区进行中，§0.1）尚未产生计数行** —— v11 MUST NOT 编造其数字，T8 的全量回归按其 gate 现状运行并在 §13.3 登记）；
   - **新增 Dream-RSI conformance 行**：`replay 确定性/零写集`、`批合法性`、`策略指针 CAS`、`V 逐位复现`、`episode 级前缀-only`、**`候选集含现役（V^{m*} ≥ V^0 的构造前提）`**（**〔审阅修正〕** 原计划只泛泛说「覆盖矩阵已更新」；末项为 blocking 修复 §7.2/§9.1/§2.1 T14 的 conformance 落点）；
   - **row 11（fork 切点）现状为 🟡，T1 MUST 保持 🟡** 并在 T1 验收里**显式断言「本次不改动 row 11 状态」** —— 该缺口属 G10/G13，不由 v11 转绿（fork 命令本体随 G10、验收孪生随 G13）。
3. **`docs/reviews/v8-p0ab-deviation-ledger-2026-09-16.md` 更新**（A 段续块，按既有格式）：
   - **v11-1**：per-stage schema 分歧（tree 库独有的 `session_events`/`sessions` 列）；
   - **v11-2**：第三条 append 路径 `v_tree_append` 与冻结 `v_append_events` 的受控双实现（与 A73/A84 同类，缓解 = 单条目非批 + 复用共享子操作 + byte-equivalence 门 + **只读跨域复用检测：同 `(session_id, command_id)` 已在另一域占用 → 稳定拒绝 `CROSS_DOMAIN_COMMAND_ID_REUSE`，§3.3/HIGH-1**）；
   - **v11-3**：copy-fork 的读范围放大（`delegable` 无上限、拷贝不收窄）；
   - **v11-4**：probe execution 不入 effect ledger（§6.4 的诚实让步）+ 在线产出入口是执行路径上的新 delta；
   - **v11-5**（**〔审阅修正〕blocking：第三轮新增**）：**T1 的降级 revealed / legal-actions 形态** —— T1 阶段 `v_tree_revealed`/`v_tree_legal_actions` 只能取 **session 级**口径（不变量 30 **明确禁止**的「root 可达整棵已录树」定义），episode 绑定在 T4 才补全。按 §1.3 第 2 条末句这 MUST **登记为偏差**（此前未登记）；且该降级视图 **MUST NOT** 授予策略执行体角色（`v_node_score_read`/`v_tree_revealed`/`v_tree_legal_actions` 对该角色的 `GRANT EXECUTE` **只在 T4 生效**），T1 的降级形态仅供 T1 自身的结构门使用；
   - **Dream-RSI 未覆盖项**（B 段）：live workspace 恢复、`K1`/`K2`/`W`/`b1`/`b2`/`M` **数值**（论文未给机制层默认值；`K1` 的**机制**由 §6.6 + T15 承载、`K2` 的**机制**由 §6.6 第 7 条（`v_replay_batch` 的轮计数门）承载 —— 二者只余**数值**未覆盖）、`V` 与 `pareto.reward` 的表述差异、meta-agent 外部性、**在线阶段无历史条件化 `π_t(H_{t-1})`（§6.6 第 8 条）**、**`branch_count`/`refine_count` 无每周期上界且 `plan_grid` 无替代（§12）**、**「所有阈值走同一个 `_schedule(β)`」不可由宿主强制（§9.3 β 行第 2 半句）**、grid 抽象拒绝。
4. **`v8/README.md` 更新**：stage 表在 G13 之后新增一行（`v8/tree/`，含 DB 名与运行命令）；运行命令清单追加一条；P0C/已知边界句相应更新。

### 13.3 审阅缺陷处置台账（blocking / high 逐条）

**已 RESOLVE（改设计了）**：

| # | 缺陷 | 处置位置 |
|---|---|---|
| B1 | `sessions.next_internal_ordinal` 与八处冻结分配器冲突 | 不变量 22（**删除该列**，改同一 `max()+1` 公式）+ T1 ⑩交织门 |
| B2 | W 宽扇出被 `steps_one_active_per_session` 拒绝；无在线 rollout 里程碑 | §6.4 裁定（a）+ 偏差 v11-4 + T3 里程碑 + §6.5 |
| B3 | 冻结 append 未做 mode 门 → 静默第二根 | §2.1 D7 触发器（**四分支 A/B/B2/C**；第二根由分支 (B) 覆盖 semantic / observational / internal-ordinal 三路，并由 **第三轮新增的 (B2)** 覆盖「同事务 GUC 已被置过、后到的冻结闭包写者」一路）+ **§2.1 D7 行的模式门理由** + T1 ⑦ + T2c/T2k/T2l/**T2n**（**〔审阅修正〕** 原引「不变量 21 注」不存在 —— 不变量 21 只谈路径权威 —— 已改为 D7 行理由；并补 D9 覆写门 T2m） |
| B4 | T0 零回归是空断言（v11 文件不被既有 stage 加载） | §10.2 T0 ①**共享路径烟测门**；删除「旧门测试无需改动即通过」作为证据 |
| B5 | `v_tree_append`「复用 adjudicator」与「独立 receipt 域」自相矛盾 | §3.3 裁定 (a)：自有 `v11_tree_bindings`/`v11_tree_receipts`；偏差 v11-2；T1 ⑫只断言共享子面 |
| B6 | V^m 聚合对象缺失、无选择命令、单调性真空 | §7.2 `v11_replay_scores` 视图（**按 `plan_id` 分组**）+ `v_policy_select`（**含 `NO_INCUMBENT_CANDIDATE` 前置拒绝**）+ 真空报告规则；T6/T8 |
| B7 | 离线评估无全历史覆盖保证（**本版以另一形态复发**：把 `(w,k2,b1,b2)` 纳入唯一键恰**允许**同一 `(policy, world)` 在多剖面各占一行；完整性断言只查 `distinct world_session_id`，反例可**通过**断言却被 `1/t` 折叠；`world_through_entry` 可空使「恰一条」在 DDL 层失效；`argmax` 跨剖面比较不可比） | **已解决（改设计）**：§8.2（反例段重写）+ §2.1 T9/T13/T14（剖面提升为 `v11_replay_plan`、episode 唯一键收为 `(plan_id, candidate_index, world_session_id, world_through_entry)`、`world_through_entry NOT NULL`）+ §7.2（按 `(plan_id, candidate_index)` 分组、完整性 **per-candidate** 且按世界有序对计数）+ T5a/T7h；**残余风险**（跨世界集/跨系数档的两个 plan）由「一次选择只接受一个 `plan_id`」界定 |
| B8 | 前缀-only 无权限边界 + oracle 不校验 cell 合法性 | §1.3 第 2/3 条 + 不变量 25/26/30/31 + §7.3 步骤 2 + §2.4 + T4 ③④ + T5c/T5d |
| B9 | 树读入口无授权 | 不变量 31 + §2.4 + §7.4 + §11 T4⑧ |
| B10 | 重放入口接受调用方 cell 数组（双接口） | 不变量 26（签名改 `batch_id`）；§7.3 |
| B11 | score 是普通无保护表 | 不变量 25 读集边界 + §7.4 + T4 ③ |
| B12 | 重放读另一会话内容无授权 | §7.4 世界绑定语料 slice + recall membership + `authz_denial_audits` |
| B13 | 派生 DAG 无逐源授权 | §4.1 `source_slice_id NOT NULL` + §4.2 双向校验 + T6c |
| B14 | **D6 单子节点唯一索引把已录树压成链**：谓词不排除 root ⇒ root 至多一个子节点 ⇒ 多分支不可达、`\|A(T)\| ≡ 2`、批势 ≤ 2、W 宽扇出与 b2 并行奖励被结构性封顶 | §2.1 D6（加 `NOT parent_is_tree_root` 例外）+ D8（新列 `parent_is_tree_root`）+ 不变量 24（root 例外改写）+ §1.4 两条注 + T1 ⑧ + T2a/T2e 正向向量 |
| H1 | 前缀-only 只是函数谓词 | 同 B8/B9 |
| H2 | fork 子会话不可追加 / `entry_id` 被随机化 / 树被线性化 | §3.5 两条硬事实 + wrapper + T2i；更正原风险文本 |
| H3 | 揭示集定义是会话级而非 episode 级 | 不变量 30 + §1.3 + T5e |
| H4 | copy-fork 读范围放大被称作隔离 | §3.5 + 偏差 v11-3 |
| H5 | RLS 无法分离分支、租户检查可跳过 | §2.4（tree 会话 `workspace_id` 非空、收窄逐函数授权）+ 不变量 31 + §12（不给 session_events 加 RLS） |
| H6 | 零写集承诺与里程碑表不一致（**本版以另一形态复发**：不变量 25／§7.3 第 4 条／§12 的「无 audit…真零写」与不变量 31／§1.3 第 2 条／§2.4／§7.4／T4⑧ 的「拒绝落 `authz_denial_audits`」直接互斥，且 T4⑧ 与 T5b 在同一实现上互斥） | **部分解决 + 显式例外**：不变量 25 把「零写集」收窄为**零业务/控制写集**，`authz_denial_audits` 作为唯一**授权拒绝遥测**例外被显式排除，并在 §2.4／§7.3 第 4 条／§7.5／§12／T4②／T5b 逐处对齐；§7.1/§7.2（写由 O 命令承担）+ 偏差 v11-4 |
| H7 | `v_tree_append` 缺 envelope guard 与授权腿 | §3.2 + T1 ⑪ + T1 ⑫ |
| H8 | 无 immutability 触发器、reward 可 UPDATE、批 status 无迁移表 | §2.3 全部 |
| H9 | `session/leaf` 的 `event_key` 未定义、二次移动被静默折叠 | §3.4（点名 `v_nonstream_event_key` + 新 `command_id` 规则）+ T2f |
| H10 | TREE 丢失 ordinal 语义幂等 | §3.2（显式 TREE 幂等键）+ §3.3 收窄一致性门 + 偏差 v11-2 |
| H11 | `\|C\|≤W` DDL 不可达 + 指针无锁位 | §6.1 触发器 + §8.3 锁位（generation 槽 intra-position 子序） |
| H12 | T0 断言 G1–G13 与「`v8_append.sql` 零改动」在基线上不成立 | §10.2 T0 ⑥（G1–G11 + G13 + **G12**）+ ③（**name-set 断言**，见 §2.5）+ ⑦（**冻结基线 `b3ce055`** 上另跑 G1–G11 + G13） |
| H13 | `STAGE_THROUGH['tree']` 只写一次 | §2.5 + §13.1 加载面 + T0 ② |
| H14 | 「末尾追加」与未完成的 G12 争槽位 | §2.5 落位时序（**〔审阅修正〕** G12 已于 `605e866` 合并且不含 SQL，槽位无争用）+ T0 ③ |
| H15 | 路径约定 `v11/tree/` 不匹配全仓 `v8/<stage>/` | §2.5（落在 `v8/tree/`） |
| H16 | 两项新偏差未登记 | §13.2 第 3 项（v11-1/v11-2/v11-3/v11-4） |
| H17 | T1↔T4 之间无产者 | §6.5 + T3 里程碑 + 偏差 v11-4 |
| H18 | 收尾工件未落到具体行 | §13.2 第 2/3/4 项（矩阵新行、row 11 保持 🟡、README 新 stage 行） |
| H19 | T3 读入口的确定性与生产者 | §7.1（O 命令创建）+ T4a |
| H20 | **D7 模式门触发器第二分支不可实现**（行级 BEFORE INSERT 只看得见 `NEW`，无法判定「该行来自 tree 派生路径」）；去掉该限定词又会误伤八处冻结 ordinal 分配点（每次 turn/end、tool/result、cancel、repair 写事件被拒，零回归门当即可预见变红） | §2.1 D7 改用**会话级 GUC 标记** `v11.tree_append`（事务局部 GUC 先例 = `v8.slot_protected_write`，`v8/schema/v8_schema.sql:462-480`）并落成**四分支 (A)/(B)/(B2)/(C)**（**〔审阅修正〕** 分支 (B) 覆盖 observational 追加与冻结 internal-ordinal 写者两路，但它是**事务级代理**（`set_config(...,true)` 被同事务后到写者继承）；**第三轮新增的 (B2)** 补上「同事务内 GUC 已置、后到的冻结闭包写者插出第二根」这一路（`TREE_SECOND_ROOT`，由 `NEW` + 子查询判定）；(C) 覆盖 `session/leaf` 误落 LINEAR 会话）+ §3.1/§3.2/§3.4 同事务 `set_config` + **T1 ⑦ / T1 ⑯ 正向门 / T2c/T2k/T2l/T2n** |
| H21 | **T2 的表与触发器外键指向 T4/T6 才创建的对象**（里程碑依赖倒置；W 本身要到 T3/T6 才有值，T2 的门无法装载） | §10.2 T0（**全部新表 DDL 骨架在 T0 一次落齐**，含 `v11_replay_policies`/`v11_replay_episodes`/`v11_world_sets`）+ T0 ② 加「15 张新表可装载」断言 + T2/T3 范围句 + §2.1 T7 + §6.1 各自的同一句话 |
| H22 | **T1 ⑬／T2i 断言「tree 会话上 copy-fork 被拒」，但全文没有任何实施该拒绝的机制**（触发器看不到 fork 上下文；`v_fork_session` 的 INSERT 列表不含 `session_mode`） | §3.5 增 `v_tree_fork_child` wrapper：**在 v11 wrapper 层**对 tree 父会话返回稳定 `FORK_FROM_TREE_SESSION`，冻结函数零改动；**能力边界如实写出**（绕过 wrapper 直调则不生效）+ T1 ⑬ + T2i |
| H23 | **β 是不变量式强制项，但 schema 无承载列、唯一键也不含它**（§9.3 称其为 `v11_replay_episodes` 的列，§2.1 T9 的列清单与唯一键都没有） | §2.1 T13 增 `beta numeric NOT NULL CHECK (beta >= 0 AND beta <= 1)`（**宿主 = `v11_replay_plan`**，避免同一 `(plan,world)` 因 β 不同占多行）／ T15 增在线 `beta`（**宿主 = `v11_rollouts`**，〔审阅修正〕补在线宿主）+ §7.1/§7.2/§9.3 措辞对齐 + T4 ⑪（β 与 `policy_id` 同款不可 UPDATE） |
| H24 | **论文「策略驱动的在线 rollout」阶段无规范落点**：K1、在线批、redeploy 执行点全缺；§9.1 环图把在线阶段写成「随机」（与 `txt:107-108` 相反），`redeploy` 无入口让 π_{t+1} 影响在线执行 | **新 §6.6**（在线决策面：`v_rollout_batch` O 命令 + `K1`/`k_done` + `same decision interface`）+ §2.1 T15 `v11_rollouts` + §9.1 环图改「策略驱动/可观测 redeploy」+ T3 ⑨ + T8 ⑧ |
| H25 | **V^m 的聚合范围未钉死**：唯一键不含 `world_set`/系数档；T9 的「每个 (策略,世界) 恰一条」对 7 列键为**假陈述**；视图分母无定义；`v11_replay_plan` 不含四个系数，连「一次评估」都无法唯一确定 | §2.1 T9/T13（剖面提升为命名 plan、episode 键收为 `(plan_id, candidate_index, world_session_id, world_through_entry)`、`world_through_entry NOT NULL`）+ §7.2（按 `(plan_id, candidate_index)` 分组 + **per-candidate 完整性、世界按有序对计数**）+ §8.2 反例段重写 + T4 ①/⑪/⑫ + T7h/T7j |
| H26 | **`V^{m*} ≥ V^0` 依赖「候选集包含现役策略」这一构造，而该构造无对象、无约束、无 fixture** | §2.1 T14 `v11_replay_candidates`（`candidate_index` + `is_incumbent` + 每 plan 至多一个现役的部分唯一索引）+ §7.2 `NO_INCUMBENT_CANDIDATE` 前置拒绝 + §9.1 + §13.2 conformance 新行 + T7i/T7g |
| M1 | `v11_replay_policies` 无 immutability、指针可跨 W、episode 用 `policy_version text` | §2.1 T9/T10/T11 + §8.1 + §8.4 + T7a/T7e |
| M2 | T3「只读事务/无需授权锁」与 `auth` 参数矛盾 | §7.3（保留 `auth`、删该验收、删除 `READ ONLY` 承诺） |
| M3 | 读入口无 cutoff/bound | §3.4 `through_seq` 必需 + `v_derived_expand` 的 `through_seq` |
| M4 | 读路径无拒绝遥测 | §2.4 + 不变量 31 |
| M5 | TREE semantic 行挤占 internal 空间 | §2.2 消费方迁移注记（显式声明为破坏性重定位点） |
| N1 | `v_replay_probe` 易变等级未固定 | §2.1（`STABLE`，禁 `IMMUTABLE`）+ T4 ⑦ |

**〔审阅修正〕第二轮（本轮 REPAIR 后）修复另计** —— 这些不占上表 B/H/M/N 编号，正文一律以〔审阅修正〕标注：`W` 的 schema 归宿（§6.1 + T13/T15）、在线批与离线批的**生产者**（§6.6 第 2/3/6 条）、**episode 生命周期**（§2.3 + §7.2）、**K2 上限执行点**（§6.6 第 7 条）、**rollout 单策略固定**（§6.6 第 3 条 + T15）、**世界集与 `H_t` 绑定**（§8.2）、`v11_replay_policies` 的 workspace 绑定与 pointer 复合 FK（T10/T11）、§2.3 的**六表可变性规则补全**、**D9 root 例外位触发器**、T14/T9 的**三列复合 FK**、命名扫描的 12116 行与对象类、以及 §0.1 的**基线重述**。

**〔审阅修正〕第三轮（TARGETED REPAIR）修复另计** —— 同样不占上表编号，正文以〔审阅修正〕标注：**T0 判据改为 G12 SQL 闭包 name-set 断言，且 G12 闭包补入 `v8/events/v8_append.sql`**（§2.5、§10.2 T0③、§10.3 T0④、T1⑮、§10.3 T1③、§13.1 编辑面 —— 原「`git diff --stat b3ce055 -- v8/*.sql` 为空」在已合并 G12 的本仓**不成立**）；**§3.2 的追加父放宽为「root / 当前 leaf / 已录树的任一叶」**（使 W 宽批可执行；联改不变量 24、§3.4、§6.2/§6.4/§6.6、T1⑧、T2a、T3⑨）；**D7 增分支 (B2) `TREE_SECOND_ROOT`**（由 `NEW` + 子查询判定，封住事务局部 GUC 被同事务后到写者继承所致的第二根；负向 fixture T2n）；**`v11_probe_batches` 身份列不可变**（§2.3 列作用域触发器 + §7.3 措辞收口 + T4⑮/T7f）；**具名 score 读入口 `v_node_score_read` + `REVOKE SELECT ON v11_node_scores, v11_node_artifacts`**（§1.3②/§2.4/§7.4 + T4③/T5c）；**不变量 27/§8.3 去 v10 状态词汇**（v11 无状态列，`building→active`/`retired` 无人承载）；**§9.3 β 行拆为「宿主可强制 / 策略侧不可强制」两半**；**`n_revealed := |T|−1` 定义**（§2.1/§7.2）；**偏差 v11-5**（T1 降级 revealed 口径，且降级视图不授予策略角色）；**`v_tree_context` 二/三参数语义点名**；**§3.4 删除「`parent_is_tree_root` 恒为 false」**（与 D9 判定式不符）；**`width = |C|` 定义 + 空批不写行**；**T5g 标签缺口与 T5a/T5h 的 plan 行来源**；以及五处引用行号更正（`v8_append.sql:131`、`:378-385`、`grant:1356-1357`、`v8-dev.md:751` 保持、`txt:213`）。

**〔审阅修正〕第四轮（RESIDUAL REPAIR）修复另计** —— 同样不占上表编号，正文以〔审阅修正〕标注，修复第三轮遗留的 13 项残余缺陷：**HIGH-1**（§3.3 增「只读跨域复用检测」→ `CROSS_DOMAIN_COMMAND_ID_REUSE`；T1e/T1f 与 §11 命令域句同步）；**HIGH-2**（`v_node_score_read` + `v11_policy_runner` 角色创建归 **T4**、落 `v8/tree/v11_replay.sql`，§10.2 T4 范围句 + §10.3 T4 行）；**MED-1**（§0.1 改实测「工作区 NOT clean」+ G14/`v8/concurrency/` 与 14 键；§2.5/§10.3/§13.1 的 12 键计数与落位时序同步；T0 门含 G14）；**MED-2**（§6.6 第 3 条 + T15 + T3⑨ + §6.6 第 9 条：`v_rollout_batch` MAY 读指针仅作比较）；**MED-3**（§7.2/§8.2 的覆盖断言由计数相等改为集合/多重集相等；T4⑪/T6③/T7b/T7j 同步）；**MED-4**（root 行 = `event_class='observational'`、`event_type='session/tree_root'`；§3.1/§1.1/§3.4 + T1⑰ + T1f）；**MED-5**（命名 `v_replay_world_set_freeze`/`v_replay_plan_open`/`v_replay_candidate_add` 三个创建者，`member_count = |H_t|` 断言落在 freeze 命令体内；§2.1 T12/T13/T14 + §8.2 + §10.2 T6⑪ + §10.3 T6 行 + T9c）；**LOW-1**（§8.4 交叉引用改指 T4 ⑩、`policy_id` 改述为不可变 FK）；**LOW-2**（不变量 30 揭示集改用 `O`；**终轮重写**：原改为 `O(T) = {r} ∪ {observed leaves}` 仍把 **frontier 公式**误当作 `O`，终轮拆为 `O`（= 已观测节点集，`txt:242-244`）与 `A(T^{m,k}) = {r} ∪ leaves(O)`（frontier，`txt:202-203`），并给 `n_revealed = |O| − 1` 与 T5j 双集断言）；**LOW-3**（§2.5 的 15→16 文件 + §10.2 T8⑥/§10.3 T8 删「+ G12 若已落」条件式）；**LOW-4**（`v11_probe_batches.status` 迁移写者 = `v_batch_dispatch`→`revealed`、`v_replay_settle`/rollout 关闭→`closed`；§2.3/§6.3/T7f）；**LOW-5**（D9 示意补 `session_mode='tree'` 谓词；`W_max=4` 改为 T13 必需的 `w=2`）；**LOW-6** 折入 MED-5；**LOW-7** 经核为报告元数据不准（文档本身未重复该错引，无改动，见下）。

**〔审阅修正〕第三轮 REBUT（不改设计）**：(1)「`v8-dev.md:751` 应为 `:750`」—— **不成立**：实测 `grep -n '按 ordinal 折叠' docs/designs/v8-dev.md` = `751`，原文引用正确，保留。(2)「`grant:1355` 的 RETURN 在 `:1361-1365`」—— **审阅者的行号亦不准确**：实测 `grep -n child_session_id v8/grant/v8_grant.sql` = `1357`，`RETURN jsonb_build_object` 起于 `1356`；原文的 `:1355` 同样错，已改为 **`:1356-1357`**（既非 `:1355` 也非 `:1361-1365`）。(3) **第四轮**：原第三轮报告把子例 **`T7f` 记为一个错误的行号**（该行号实为 §11 的 `T5c`）—— 该子例断言**确实存在**于 **§11 的 `T7f` 行**，属**报告元数据不准**、**非文档缺陷**；文档本身**未重复**该错引（`T7f` 在正文出现处均正确），故 **LOW-7 无改动（REBUT）**。**〔审阅修正〕（终轮）：本条内的行号引用已按 §0.3 的引用体例改为章节引用。**

**已 REBUT（不改设计，给出理由）**：

| # | 缺陷 | 反驳理由 |
|---|---|---|
| R1 | 「`v_replay_probe` 应为 `IMMUTABLE` 纯函数」 | **不接受**：函数体读表，PG 只允许 `STABLE`；标 `IMMUTABLE` 会破坏逐位可复现性。见 §2.1 末条 |
| R2 | 「采纳 (b) 每会话 W=1、撤回并行主张」 | **不接受**：与论文 `b2` 项（`txt:317-320`）直接矛盾，且使 tree 会话在扇出意义上不再是 v8 会话 —— 是自我否认而非设计。见 §6.4 第 3 条 |
| R3 | 「为 `v_tree_append` 复用 `v8_command_adjudicate` 并靠 `command_kind` 区分」 | **不接受**：给 adjudicator 的键加 `command_kind` 属编辑冻结 events 文件，被基线约束禁止。见 §3.3 |
| R4 | 「把 leaf 游标移出公开日志、做成 CAS 控制态列」 | **部分反驳**：v11 保留追加式游标（不变量 24）以维持 append-only 与 pi `LeafEntry` 的形状；泄漏面由 §3.4 的可见性处置（最小权限角色无 `session_events` SELECT）与 `session/leaf` 的 fold 规则闭合。若实现证明该面不可闭合，再评估控制态列 |
| R5 | 「`v_tree_context` 由调用方指定 leaf 以读兄弟分支」 | **反驳**：这正是要禁止的泄漏面。入口 MUST 从 episode 状态推导可见范围（不变量 30） |
| R6 | 「inspection 复用 v10 全量计算核」 | **反驳**：`v10-dev.md:365` 的成本画像对**内环** oracle 是错的；v11 的 oracle 只读已录结果。见 §7.3 |
| R7 | 「把元 agent 纳入 runtime 以便闭环」 | **反驳**：会同时违反不变量 4 与 `v10-dev.md:964,966`。见 §9.2 |
| R8 | 「`v_fork_session` 的 COPY 语义可直接作树构建」 | **反驳**：O(prefix) 复制 + seq 重编号（`v8/grant/v8_grant.sql:1304`）+ 不继承 live handle（`:1326-1329`），对树扇出是错误成本画像。见 §1.2/§3.5 |

### 13.3.1 移交人工 L4 的待核项

**本节是最后一轮自动对抗式审阅（第四轮之后的终轮）的收口。以下各项如实列出本轮**未能在真实环境验证**或**未解决**的残余，移交人工实现规范审核（Oracle L4）。本节**不**宣称文档已验证、已冻结或已完整。**

**A. 本轮已改设计、但**未**在真实环境验证的项**

1. **揭示集双集拆分（不变量 30）**：`O`（已观测节点集，论文 `txt:242-244`）与 `A(T^{m,k}) = {r} ∪ leaves(O)`（frontier，论文 `txt:202-203`）已拆开，`n_revealed = |O| − 1` 已在 §2.1/§7.2/§11 T5j 对齐。**该拆分是规范级推理，T5j 未运行**（§11 全部子例状态均为未运行）；人工审核 MUST 复核「`T^{m,k}_i` 的节点集 = 已观测节点集」这一解释与论文一致。
2. **裸路径拒绝的形态（§1.3 第 2 条 / §2.4 / T5c / T9d）**：本轮钉死「**具名读入口** → 稳定 code + `authz_denial_audits` 行；**裸 `SELECT`** → 原始 `42501`、无稳定 code、无 audit 行」。该分工**未**在任何 PostgreSQL 实例上实测；人工审核 MUST 复核：在默认拒绝/`REVOKE` 下，读入口自身写 `authz_denial_audits` 的路径仍可执行、且裸路径错误码确为 `42501`。
3. **策略执行角色的授权机制（§2.4）**：本轮把「只 `REVOKE` 三张表」改为「**角色零表级权限的默认拒绝**，覆盖全部 v11 表 + `session_events`，仅五个具名函数 `EXECUTE`」。该机制的**实施点**是 `v11_policy_runner` 的创建语句（归 T4），**本轮只写规范、未写 DDL**。人工审核 MUST 确认「新建角色对既有对象默认零权限」这一假设在目标 PG 版本、schema `USAGE` 与 `PUBLIC` 默认授权形态下成立；若否，须回到**逐表显式 `REVOKE`** 的清单形态。
4. **§0.1 工作树快照的时效性**：§0.1 记录的「`HEAD` + `git status --short` 实测行」在**并发 stage 工作**下持续漂移 —— 本轮 pass 进行期间，实测已与所记值不同（并发 G-stage 目录与若干被改 SQL 文件发生变化）。本轮**未**追改 §0.1 的快照值：追改会在下一次并发提交后立即再次失效（与 §0.3 的引用体例、第四轮 MED-1 是同一教训）。人工 L4 复核时 MUST 自行 `git rev-parse HEAD` + `git status --short` 重新实测，MUST NOT 以 §0.1 的所记快照当作当前事实。

**B. 本轮**未解决 / 未强制**的项（与 §13.2 第 3 项 B 段、§12 同源，此处只点名、不重复全文）**

- live workspace 恢复；`K1`/`K2`/`W`/`b1`/`b2`/`M` 的**数值**（机制已由 §6.6 / T13 / T15 承载，数值论文未给）；meta-agent 外部性（§9.2）；在线阶段**无**历史条件化 `π_t(H_{t-1})`（§6.6 第 8 条）；`branch_count`/`refine_count` **无每周期上界**且 `plan_grid` 无替代（§12）；「所有阈值走同一个 `_schedule(β)`」**不可由宿主强制**（§9.3 β 行第 2 半句）。
- 本轮**未新增偏差**（v11-1…v11-5 不变，§13.2 第 3 项），也**未新增不变量**（21–31 不变）。
- 本轮的四项 LOW 内容项（`proposed→closed` 无写者、`v_derived_expand` 的零 audit 限定词、§1.3 的第五个 `EXECUTE`、T8 门清单的 G14）**均已改**，无遗留 LOW。

**C. 状态诚实声明**

- 本草案已历**四轮**自动对抗式审阅/修复（第 1–2 轮见上表与「第二轮」段，第 3–4 轮见各〔审阅修正〕段），**终轮为第五次自动 pass**；**尚未冻结、尚未实现、未执行任何 fixture / 回归 / 验收**。
- 本节的「已改设计」只表示规范文字已改，**不等于**已实现、已验证或已通过。§11 全部子例状态为**未运行**；§13.4 只是文档自查、不是运行报告。
- 人工 L4 必须在本草案上**独立复核**，MUST NOT 以本节或 §13.3 的 RESOLVE 记录作为通过依据。

### 13.4 DoD 自查（仅文档自查，不是运行报告）

| 组 | 逐项检查与证据 | 结论 |
|---|---|---|
| A 结构 | A1 章号 0–13 + 附录齐备；A2 不变量 21–31 各声明「禁止什么」；A3 数据平面 §2 覆盖全部新表/新列/新触发器；A4 命令分类（O/P/R）显式；A5 锁位声明 §8.3；A6 crash/回归框架 §13.1；A7 收尾工件 §13.2；A8 缺陷台账 §13.3；A9 无可执行 DDL（全部 `ALTER`/`CREATE` 为示意，本文件不含可运行迁移） | 结构检查完成，协议待 L4 关闭 |
| B 来源 | B1 每条 v8/v10 引用均带 `file:line` 且已核对实际文件（**八处 ordinal 分配点行号已标注 G12 后工作树 vs `b3ce055` 的差异**；`12435` 已改为 `b3ce055` 实测 `12116`；**第三轮另更正 `v8_append.sql:131`、`:378-385`、`grant:1356-1357`、`txt:213` 四处引用，并保留 `v8-dev.md:751`（实测正确）**）；B2 Dream-RSI 引用带 `txt:N` 并标注提取噪声；B3 兄弟项目引用带 `file:line`；B4 未覆盖项在 §12 与台账 B 段列明；B5 无「未验证即断言」 | 结构检查完成 |
| C 防回归 | C1 不变量 1–20 未改；C2 冻结 v8 14 文件零编辑；C3 三处硬墙（路径序不落库 / 无 live handle / 元层外部）显式让步；C4 单一 `tree` stage 与提数纪律；C5 per-stage schema 分歧已登记；C6 双/三实现风险已登记；C7 命名扫描门；C8 copy-fork 两硬事实已写；C9 加载序落位时序；C10 现有 gate 数字不改 | 防回归静态检查完成，协议待 L4 关闭 |
| D 范围 | D1 不修改冻结面；D2 不 host 元层；D3 不新增 live handle；D4 不给 inspection 加写；D5 不在事务内 IO；D6 不移植 pi-lcm/ACM 的不健全机制；D7 不引用论文未给的默认值；D8 本轮不写生产代码；D9 不报未运行通过；D10 五条偏差已登记（v11-1…v11-4 + 第三轮新增 v11-5） | 范围/结构检查完成 |
| E 运行 | 接入/命名证据、全部 fixture、capability 分层报告见 §10/§11 | **结构检查完成；实现、spike、隔离与运行验收均未执行** |

### 13.5 收尾诚实声明

**v11-dev 实现规范草稿完成，基于 `b3ce055` 冻结基线与冻结 v10 规格，待实现规范审核；未执行任何实现、运行、fixture 或验收。** 本文件不修改冻结 v8、不修改 v10 规格、不修改 v9；新增不变量 21–31 为本草稿分配，未随任何准出成为冻结实现合同。§11 全部子例状态为**未运行**；§13.4 只是文档自查，不是运行报告。

## 附录 A 来源映射

### A.1 采纳 / 拒绝总表

| 来源 | 采纳（v11 落点） | 拒绝（理由） |
|---|---|---|
| **Dream-RSI**（预印本；`/tmp/dreamrsi.txt`） | 两阶段 loop（`txt:208-209`）；树 = (parent, 创建序, payload, score, evaluated, fail_class) 的**数据**而非活对象（`txt:193-200`）；`A(T)={r}∪leaves(O)`（frontier/合法 cell 集；`txt:202-203`）；批 `\|C\|≤W`（`txt:204-208`）；确定性 Child 规则（`txt:265-272`）；`V = max_v s_v − b1*N + b2*N/max(1,k*)`（`txt:295-320`，以论文版为准）；选择规则与单调不退化（`txt:321-340`）；前缀-only 硬约束（`txt:1130-1135`）；批合法性（`txt:1139-1143,1100-1106`）；成功语义（`txt:1041-1045`）；Observation 字段（`txt:1034-1036`）；β 角色 1（`txt:1149-1159`） | `attempt_*/` + `eval/score.json` + `error.txt` 节点 sidecar 布局（`txt:943-983`，文件系统特有）；`trace_pool/`、`beta_sweep.json`、`policy_execution_traces.jsonl`、`history_dir/r####_*/`（`txt:1169-1266`，落盘约定 → 表/视图）；frozen trace 的 `trace_branch_count/refine_count` 文件形态（`txt:1206-1212` → cutoff/generation）；`GridPlan`/`plan_grid`/`GridPlanningContext` 的冻结 branch×attempt 网格（`txt:1190-1245`，substrate 产物非机制；**v11 亦未提供替代的每周期 branch/refine 上界，已登记为接受偏差，§12**）；`question.*` 进程内对象接口（`txt:1107-1132`，宿主便利层）；meta-agent（`txt:186-188,329-334`，系统外）；β 角色 2/3 与 sweep 文件形态（`txt:1160-1188`）；§4 全部配置数值（论文未给机制层默认值）；`pareto.reward`（`txt:1003-1013`，与论文 V 不同表达式，仅作参考并记台账） |
| **pi**（`/Users/wxl/Projects/pi`） | `SessionEntryBase {id, parentId, type, …}` 的行形状（`packages/coding-agent/src/core/session-manager.ts:46-51`）；leaf 作为**追加**（`packages/agent/src/harness/types.ts:404-407` + `jsonl-storage.ts:109-111`）；branch 是 O(1) 指针移动（`session-manager.ts:1277-1282`）；上下文 = leaf→root 路径 + 之后套窗口（`session-manager.ts:403-439`）；压缩作为一等**节点**而非 side table 的结构理由（`session-manager.ts:970-975`）；`/tree` vs `/fork` vs `/clone` 的「同会话指针移动 vs 新会话复制」切分 | `_rewriteFile` 截断重写（`session-manager.ts:898-908`，非 append-only）；`leafId = 最后一行` 的隐式 leaf 派生（`session-manager.ts:877-896`，PG 下 seq 序不是游标）；8 位 hex 局部 id（`:217-224`，跨会话不唯一）；timestamp 子序（`:1255-1262`，PG 有精确 seq）；目录编码 cwd 的布局与 list/resume UX（`:461-474`）；`git-checkpoint` 的内存 `Map`（`examples/extensions/git-checkpoint.ts:20-27`，v11 用 artifact + 可选 handle 前沿）；pi 的**减法**压缩（无 derivation edge、无 drill-back）—— 那是 pi-lcm/ACM 的位置 |
| **pi-lcm**（`/Users/wxl/Projects/pi-lcm`） | 派生边表 `summary_sources(summary_id, source_type, source_id, seq)`、**无 `parent_id`**、多态 source（`src/db/schema.ts:96-102` + `PLAN.md:171-173`）；「已消费」= `NOT EXISTS` 集合差（`src/db/store.ts:405-411`）；失败派生不落「已完成」（`src/compaction/engine.ts:104-107`）；drill-back 是**回读到保留行**而非重新摘要（`src/tools/lcm-expand.ts:106-108`）；visited 守卫 + token/节点预算（`lcm-expand.ts:13-14,86-89`）；`assembleSummary` 的确定性 budget 装配（`src/compaction/assembler.ts:9-75`） | `is_compacted` 就地 UPDATE（`src/db/schema.ts` → 违反 v8 不变量 1）；`dedup_hash = sha1(role\|ts\|200字符).slice(0,16)`（`src/db/schema.ts:181-186`，不健全幂等键）；`MAX(seq)+1` 分配器（`src/db/store.ts:135-146`，v8 已有 ordinal 权威）；WAL/`busy_timeout`/`wal_checkpoint`（单文件 SQLite 关切）；一项目一 DB 文件（`src/db/connection.ts:15-17`）；进程内 promise 链互斥（`src/compaction/engine.ts:31`，跨进程无效 → v11 用 advisory lock）；FTS5 外部内容表 + 三触发器 + LIKE 兜底（SQLite 特有 → PG tsvector/GIN）；`minMessagesForCompaction` + 「返回 null 让 Pi 默认压缩」的扩展回落语义；README 的 7/43/259（per-node 记账，非实测周期索引 —— 只移植 O(log N) 性质） |
| **ACM**（`/Users/wxl/Projects/agentic-context-management`） | `summary_id` 间接 + 派生投影引用回真相（`src/history.py` 的 `compress_range` 只动 `messages`、不动归档）；引用应**out-of-band**（ACM 被迫用 `[summary_id: N]` 内联文本只是因为没有 schema ⇒ PG 用边表）；agent-native 决策作为**已录的一等动作**（`src/runner.py:559-580`）；`re_mem_noquery` 消融模板（`src/configs/runtime.py:18-26`）；peak-token 作为**资源轴**（`src/evaluator.py:1365-1378`） | 位置式身份（列表切片，`src/history.py:7-8,106`）；文件系统 sidecar 归档；「lossless」一词的无限定用法（从不销毁 ≠ 可取回；`README.md:45` vs 序列化丢键 `src/runner.py:483-489`）；LLM-in-the-read-path 检索（`src/runner.py:593-637`，非确定不可重放）；`load_snapshot` 覆写 `raw_messages`（`src/history.py:114-116`，证伪其「append-only mirror」）；训练/蒸馏管道 |
| **Dolt / DoltLite**（`/Users/wxl/Projects/doltlite`、`/Users/wxl/Projects/doltgresql`） | **REFS, NOT COPIES**：branch 是命名指针（`src/chunk_refs.h:16-20`）；commit 是带 parent **列表**的不可变节点（`src/doltlite_commit.h:13-24`）；ref 表自身版本化（`src/chunk_refs.h:48-49`）—— 映射到 v11 的 O(1) 分支与「revision 单调的指针」 | prolly 树 / 内容定义分块（`src/prolly_hash.c:48`、`prolly_chunker.h:14-15`：v8 事件已 append-only，无可再分块）；单文件 chunk store 格式；detached-HEAD 拒绝（`src/doltlite_checkout.c:1167`，git 人体工学）；`dolt_branch/dolt_checkout` SQL 面与 `dolt_branch_control` ACL（v8 已有 grant/白名单，加第二套权限系统是回归风险） |
| **loopx**（`/Users/wxl/Projects/loopx-nooa-agent-session-layer`） | run-bound reward overlay 作为一等对象（`docs/state-interaction-model.md:84`，形状 `{recorded_at, decision, reward, reason_summary, follow_up}`）；compute quota 作为**持久**策略门控、与 reward/approval 分离（`docs/quota-allocation.md:1-26`）→ v11 的持久 `W` | 其六层控制面的具体表结构（v11 复用 v8 控制态，不引入第二套调度面） |
| **ICM / MCE / RLM / Memoria / memvid / cowtree** | ICM：装配 manifest 的可读 Inputs 表想法（`README.md:84`）→ v11 的 profile 可读化（后续可选）。cowtree：CoW 快照作为**可选**加速器（`src/cowtree/fs.py:68,79`，APFS `clonefile` / reflink） | ICM 五层 token 预算与「目录即架构」；MCE 的双层优化与单论文经验数字（`README.md:41,54`）——只借「每迭代一个版本化 skill 产物 + 作者写权限边界」的想法；RLM 的 CodeAct REPL 执行模型（**〔审阅修正〕** 原引 `README.md:26` 在 `/Users/wxl/Projects/rlm` 树内**无法证实**（无任一 README 的第 26 行指 CodeAct），已删除该行号，拒绝理由不变）；Memoria 的 MatrixOne DDL `CREATE SNAPSHOT`/`data branch`（`memoria-git/src/service.rs:531-540,651-700`，借他人引擎的用法模式，非机制）；memvid 单文件 `.mv2`（`MV2_SPEC.md:7`）；cowtree 作为**唯一**路径（`README.rst:60-61` 明示非 CoW 文件系统上失败 ⇒ v11 只作加速器，必须有兜底） |

### A.2 固定冻结锚点索引（供审核复核）

| 引用点 | 路径 / 行 | 用途 |
|---|---|---|
| 不变量 1 只追加 + 无洞 seq | `v8/schema/v8_schema.sql:34`（`next_seq`）、`:135-199`（`session_events` + append-only 触发器） | §0.2、§2.2 |
| 双 ordinal 与两个部分唯一索引 | `v8/schema/v8_schema.sql:164-178,182-187` | §2.2 |
| `semantic_input_ordinal` 权威 | `v8/events/v8_append.sql:535-556` | §2.2 |
| 公开白名单 | `v8/events/v8_append.sql:485-498` | §3.2 |
| envelope driver/epoch guard | `v8/events/v8_append.sql:378-385` | §3.2 |
| 七步 append | `v8/events/v8_append.sql:252-1210`（`b3ce055`）／`:252-1204`（工作树，G12 后） | §3.2 |
| 八处 internal ordinal 分配 | `v8/effect/v8_effect.sql:1516,1700,1950,2114`；`v8/tools/v8_tools.sql:523`；`v8/cancel/v8_closure.sql:388`；`v8/retry/v8_takeover.sql:410`；`v8/repair/v8_repair.sql:333`（**行号取自 G12 后工作树；`b3ce055` 对应 `effect:1276,1459,1702,1853`、`tools:464`、`takeover:352`，`closure:388`/`repair:333` 两版相同**） | 不变量 22 |
| 单活跃 step 索引 | `v8/schema/v8_schema.sql:121-123`；`v8/effect/v8_effect.sql:604-615` | §6.4 |
| `v_fork_session` | `v8/grant/v8_grant.sql:1231-1361`（INSERT 列表 `:1298-1303`、`row_number` `:1304`、无 live handle `:1326-1329`、grant 拷贝 `:1330-1346`） | §3.5 |
| `v_compat_fork` | `v8/compat/v8_compat.sql:497-551` | §3.5 |
| `workspace_handles` + 五状态 + materialize | `v8/grant/v8_grant.sql:733-751,771-803,937-987,996-1051` | §5.3 |
| RLS（仅三表） | `v8/grant/v8_grant.sql:1373-1386` | §2.4 |
| `authz_denial_audits` | `v8/grant/v8_grant.sql:216-238` | §2.4 |
| `v_grant_lock_judge` / `v_grant_find_valid` | `v8/grant/v8_grant.sql:364-479,487-534` | 不变量 31 |
| 租户合取可跳过（`IS NULL`） | `v8/grant/v8_grant.sql:448-452`；`workspace_id` 可空 `:43` | §2.4 |
| ALTER 冻结表先例 | `v8/stream/v8_stream.sql:37-40` | §2.1 |
| 八位主锁序 | `v8-dev.md:474` | §8.3 |
| 派发采样/ordinal 折叠 | `v8-dev.md:751` | §6.3 |
| 加载序 / stage 计数 | `v8/load.py:18-74,76-109,112-114` | §2.5 |
| 不可变性触发器先例 | `v8/plugin/v8_plugin.sql:49-60` | §2.3 |
| `v_nonstream_event_key` | `v8/schema/v8_keys.sql:85-97` | §3.4 |
| v10 不变量 19/20 | `v10-dev.md:52-53` | §0.2 |
| v10 指针 CAS | `v10-dev.md:136,644-645` | §8.3 |
| v10 `context_artifacts` | `v10-dev.md:146,551-564` | §5.1 |
| v10 `recall_context_query` | `v10-dev.md:137,238-240` | §4.2 |
| v10 inspection / 零写集 | `v10-dev.md:359-369`（`:365` 共用计算核、`:366` 零写集） | §7.3 |
| v10 读授权 | `v10-dev.md:217,226` | §4.2、§7.4 |
| v10 锁序（pointer/generation 子序） | `v10-dev.md:771` | §8.3 |
| v10 非目标 | `v10-dev.md:958-974` | §12 |

### A.3 v11 对 v10 的关系（一句话）

**v10 是 v8 `assemble` 内部展开的装配平面（零代码）；v11 是 v8 会话/日志底座上的树、重放与策略平面（同样零代码）。两者都继承 v8 的 18 条不变量、都不修改对方；v10 的 19/20 与 v11 的 21–31 都是各自草稿分配的待审核编号。v11 不依赖 v10 的实现，只在语义上复用其「不可变版本化产物 + 唯一 CAS 指针 + 登记式只读入口 + 内容寻址 artifact + 逐源授权闭包」这套词汇。**
