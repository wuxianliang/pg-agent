# v13 控制面 Oracle R5 终裁：Phase A 四题 D11–D14 + 第四务落点（2026-09-26）

- 日期：2026-09-26。触发：路线图 §4 D11–D14 未裁（未裁前对应 stage 不开工）+ Phase A 计划方向审核（用户硬性要求：计划过 Oracle 审核）。
- 轮次：R5 单轮三车道（grokBuild grok-4.7-build-fast-xhigh 主裁决 / codex gpt-5.6-sol@xhigh / openCode kimi-code-plan-cn/k3），三车道在全部六题上收敛，形状差异由控制器按「fail-closed、单源词表、codex 复合返回形硬要求」合并，分叉记 §7。
- 全文：`prompt-exports/oracle-chat-2026-09-26-220141-new-chat-d34409-db94.md`（gitignored）。
- 地位：与 R3/R4 同级。**与路线图 §2.1 F23、§3 Phase A、§4 D11–D14 的倾向文字冲突处，以本文为准**；不重开：零新表零新列、stage 1–20 文件字节冻结、唯一推进函数、events 唯一干预通道、R3 链已冻失败模式（C4 RAISE、终态 `replay`、`v13_interruptible` 闭集）、R4 表达形式。索引、只 RAISE 的守卫触发器、开放事件、STABLE/VOLATILE 函数不是新表。
- 总原则：**凡换体，底稿必须是 stage 20 全量加载后的 `pg_get_functiondef` 活体**；禁止从 control/fanout 等首写文件回贴（会把 stage 18–20 已换体的 `v13_complete`/`v13_advance` 卷回去）。

> **R6 后续（2026-09-27）**：本文 §1 条件 4 的 no-event 分支（「同一快照可见也算」及其后的指向性探针要求与勘误）已由 R6 删除——见 `docs/reviews/v13-control-plane-oracle-r6-2026-09-27.md`。本文其余条款继续有效。

## §0 总表

| 题 | Verdict | 一句理由 |
|---|---|---|
| D11 cap × tail gap | **修订** | 豁免进 `v13_harness_tail_gap` 成立；anchor 复合返回、同 user turn 作用域、盖章即可、closeout ③ 同源四点必须收紧，否则假绿或把活体 fold cap 卡死 |
| D11b | **采纳委托** | `v13_cap_human_answered` 换体委托 anchor；「两处 IN 列表靠 gate 对齐」不采纳 |
| D12 worktree released | **修订，取 (a)** | `v13_latch_fire(..., released)` 在活体是静默空操作，禁止当施工句；`worktree/released` 事件为唯一权威 + 首次转移幂等；否 (a′) |
| D13 F4 静默 no-op | **接受** | 零 SQL，台账 F23；不重开 C4 |
| D14 catalog 例外 | **接受+修订** | 复用活体一对谓词；豁免必须绑定 catalog 已解析的同一 OID；RED 基线是硬前置 |
| 第四务落点 | **修订** | 零新 SQL 动词；分派按 `v13_interruptible(tool_name)`；假 worker gate 只证合同，真接线不进仓库则最高 🟡 |

## §1 D11 — 已答 cap 免除「被该次作答取代的那一条」续传义务

**条文。** 已答 cap 不补 `index+1`。`v13_harness_tail_gap` 原 `EXISTS` 一字不放宽，只追加 `AND NOT v13_tail_gap_cap_exempt(...)`；签名与四处 `PERFORM` 参数不动。禁止：四个调用点各写守卫；先补 index+1 再铸新回合；任一 cap human 豁免全部断链；`ORDER BY ... LIMIT 1` 挑一条放过。

**词表唯一家。** 新 STABLE `v13_cap_answer_anchor(p_sid, p_effect) RETURNS TABLE(anchor_seq bigint, cap_class text)`（codex 硬要求：仅返回 bigint 不算按裁决交付）。`repair_cap`/`replan_cap`/`material_cap` 字面量只住此函数，从 stage 20 活体 `v13_cap_human_answered` 原样抄出。两臂都定位 succeeded human、同 session、`origin_user_seq` 与 `p_effect` 相同、anchor 严格晚于 `p_effect` 的 `effect_done.seq`；臂 (a) anchor=`human/responded.seq`；臂 (b) legacy `{reason}` anchor=该 human 自身 `effect_done.seq`（R3b：此类 human 不写 `human/responded`；anchor 若只认 responded，活体主路径铸新回合会整体消失）。`cap_class ∈ {repair, replan, material}` 规范化；每类至多一行（取该类最早合法 anchor）；类内账本歧义按无豁免处理。无满足者零行。

**豁免谓词。** 新 STABLE `v13_tail_gap_cap_exempt(p_sid, p_effect) → boolean`，对原 `EXISTS` 扫到的每条候选单独求值，真当且仅当：
1. 候选 `result_kind='progress'`（wait 链恒不豁免）。
2. anchor 返回一行且 **cap_class 与候选信号对应**：`repair`↔`repair/required`、`replan`↔`replan/required`（同一 effect 双信号时匹配其一即豁免整条 index+1 义务）；`material` 恒不豁免；禁止先取「任意种类最早 seq」再滤种类。
3. **相邻性**：同 `origin_user_seq` 内不存在另一条 succeeded harness 的 `effect_done.seq` 严格落在 `(候选.effect_done, anchor)` 开区间。
4. **新回合已盖章，不必 succeeded**：同 session、同 `origin_user_seq` 存在 harness effect：`continuation_index=0`、`logical_turn_id` 与候选不同、排序在 anchor 之后（已有事件则 seq > anchor；尚无事件的 ready/claimed 行同一快照可见也算）；failed/cancelled/unknown/ready/claimed/succeeded 全算。只认 succeeded 会在铸新格与其后 `PERFORM`、新回合失败/进墙的重试格两处重新卡死。
5. 原 tail-gap 条件仍证明旧链无同 logical turn 的 index+1 后继（调用点语义，不在谓词内重复）。

三者（候选链、cap human、新 index-0 harness）必须同一 `origin_user_seq`——后续 user turn 的 cap 或新回合不得免除旧 turn 的 gap。

**D11b（已裁）。** 换体 `v13_cap_human_answered`：函数体 ≡ `EXISTS (SELECT 1 FROM v13_cap_answer_anchor(p_sid, p_effect))`；签名、波动性、调用权限不变。行为收紧：乱序/跨 user turn legacy human 不再跳过续传（gate 显式断言）。

**closeout ③ 同源（强制）。** 实施第一步 `pg_get_functiondef` 活体 `v13_closeout`：严格前置③「续传未还」若直接/间接调 `v13_harness_tail_gap` → 换体即覆盖；若是独立扫描 → stage 21 同批换体委托同一 `v13_tail_gap_cap_exempt`，**豁免逻辑全树至多一个函数体**；若只查最新一条 harness 且最新已是新回合 finish/reject → ③ 已放过，禁止再放宽。④ 逃生前置保持现状。

**调用顺序是实施前义务。** 以 `pg_get_functiondef` 活体 `v13_advance` 为准（triage 文本 666 / 750–768 / 888 / 960 不是同一路径三次重复）。豁免必须在「今天会 RAISE 的那一次调用」上为真；若铸新格在盖章行插入之前就把被取代链算进 gap，允许 stage 21 换体 advance 把这一次 `PERFORM` 移到 cap 决定之后、入队插入之后、返回之前（仍是 callee 级换体，不是四个守卫）。墙分支、ready/claimed 提前返回、cancel 相、step 0 的 R3b 顺序禁止重排。

**Gate（全要）。** 已答且序正确的 repair_cap：铸新格不 RAISE、新 uuid/index 0 保留、新回合 finish 后 advance 不 RAISE、`closeout completed` 成功。未答真断链仍 RAISE 原文案。更早独立断链（开区间有另一 succeeded harness）仍 RAISE。另有未还 wait 仍 RAISE。`replan_cap` 不豁免只有 `repair/required` 的链。`material_cap` 不豁免。双信号+其一 cap 作答：不 RAISE。新回合 failed 后下一格走既有重试而非 tail gap。乱序 legacy human：不跳过、不豁免、写 index+1。cap 已答但新回合尚未铸成（铸新前崩溃）：不豁免仍 RAISE。新 index-0 属后续 user turn：不豁免。新 harness 是同 logical turn 的 index+1：由原后继规则消账，不走豁免。两条独立 gap 只豁免被取代那条。`pg_get_functiondef(v13_cap_human_answered)` 不含 cap 字面量。

新函数与活体 tail_gap 同 security 模式：`REVOKE PUBLIC`，只 GRANT 调用链上的 `v13_route`。

## §2 D12 — 取 (a)：`worktree/released` 事件是唯一权威

路线图「release 成功则 `v13_latch_fire(..., released)`」**不予执行**（活体 adopt 分支 + V3008 使照字面为静默 no-op）。(b) 放宽 INSERT-once、(c) 改主键、(a′) 以 `tool/result` 为权威，均不采纳。

**合同。** latch 行永久表达 binding/prepared 事实（不 UPDATE、不插第二行、不再 fire released）；首次成功 release 写开放事件 `worktree/released`；STABLE `v13_worktree_state` 折叠出 released。成功 release 后 latch 行仍 `prepared` 是本裁决预期。

**写者。** VOLATILE helper `v13_record_worktree_released(p_sid, p_effect)`，只做这一件事：仅当该 effect 是本会话 `worktree_release`、`kind=tool`、`status=succeeded` 且 request 的 `binding_artifact_id` 逐字节相等；同 binding 已有事件且 source 相同 → 空操作（**首次转移幂等**——后续同 binding 的独立成功 release 照常 succeeded 结算、写 effect_done/tool/result、不追加第二条事件；否则外部 IO 已成功后被唯一索引打回，制造新 unknown 墙）；同 binding 已有事件且 source 不同 → RAISE 稳定子串 `v13: worktree released` 零写。payload 闭集恰 `{schema_version:1, binding_artifact_id}`。

**调用点恰两个，都在 stage 21 换体里。** ① `v13_complete` release succeeded 分支：replay/stale 提前返回**之后**、status 写成 succeeded **之后**、返回之前（failed/unknown/cancelled 不调；插入点放错会把已裁 replay 打成 RAISE）。② `v13_resolve_unknown` confirmed 把 effect 写成 succeeded 之后对 `worktree_release` 直线调用一次（rolled_back/not_happened 不调；不改 C1 清墙、resolution 闭集、其它写集；若无法直线加上须重排控制流 → 停工，把「confirmed 的 release 投影仍为 prepared」写入 Phase A 台账，禁止顺手重写 resolve——只 complete 写事件会把 required 档中断进墙再 confirmed 拆墙的释放永久停在 prepared，那是 mutating FS 主失败模式）。

**守卫与索引。** 新独立 `BEFORE INSERT` 守卫（沿 spawn 先例，不改 stage 17 守卫函数源文件）：校验 payload 键集恰两键、`schema_version` JSON 数字 1、binding canonical、source 非空且同 session 且是 succeeded 的 `worktree_release` tool effect、payload binding 从 source **冻结 request** 复制（不读 worker result）且与 worktree latch binding 逐字相同；对不上 RAISE 零事件。部分唯一索引 `(session_id, (payload->>'binding_artifact_id')) WHERE type='worktree/released'`。

**勘误（R5 审核轮，控制器追加）：** 上文「写者」原文「同 binding 已有事件且 source 不同 → RAISE」与「首次转移幂等（后续同 binding 的独立成功 release 照常结算不追加事件）」在结算写者路径上不可同时成立——第二次独立成功 release 必然是新 effect（source 不同），照原文会在外部 IO 已成功后把结算打回。澄清（不重开事件权威方案）：结算写者（complete/resolve 调用路径）对该 binding 已有合法 `worktree/released` 事件时**无论 source 是否相同均 no-op**；「不同 source → RAISE `v13: worktree released`」限定于**直接 INSERT 第二条权威事件**的旁路（由守卫触发器执法，唯一索引为最后带层）；写者首次写入须冲突安全（**latch 行锁内重查后 INSERT**：锁 `latches(session_id,'worktree')` 行——资格已保证存在——锁内重查该 binding 事件后决定空操作或 INSERT；禁 SELECT 后裸 INSERT，禁 `ON CONFLICT DO NOTHING` 当竞态方案——BEFORE INSERT 守卫先于冲突裁决执行吸不掉守卫 RAISE；守卫按同一锁序先锁 latch 再查第二事件，锁序与活体不容则停工）。安装前断言的「可证」= 已存在完全符合守卫不变量的同型事件；仅有 succeeded effect 而无事件 → 停安装（禁回填，放行即成静默降回 prepared）。

条件 4 括号勘误（第三轮）：R5 §1 条件 4「尚无事件的 ready/claimed 行同一快照可见也算」与收紧后的施工读法冲突时，以「只认探针证得的、严格晚于该 anchor 的插入（括号证据）」为准；「同一快照可见」只表示未提交新行可算，不把 anchor 之前已存在的 ready/claimed 算进盖章；不得改回「必须 succeeded」。（第四轮补：括号证据是**指向该 harness 行**的 turn/route——探针字段逐行关联，其 seq 严格晚于该 anchor；用户回合里另有一条更晚的 route、且无事件 index-0 恰有一行，不算盖章；存在性 + 行数计数不是关联证据。）

**投影。** STABLE `v13_worktree_state(p_sid) → text`：无 latch 行 → NULL（孤立事件也是 NULL）；有 latch 无 binding 相等事件 → `prepared`；有匹配事件 → `released`；结构性歧义账本 → RAISE 不按 recency 猜。latch 行 `state` 字段不参与投影。

**边界。** claim/digest/fork 零改动；released 本期不被 claim 消费（「released 后禁 claim」另裁，不得顺手加）；无 binding 仍拒 claim；gate 锁「投影 released 时 claim 结果与只有 prepared latch 的既有结果相同」。`v13_worktree_latch_ok` 词表保留 `released`（词表函数成为投影专用；`test_fanout.py:459/467` 直接 fire released 测 digest 排除，词表保留即不需改）；全树生产代码不得读 `latches.value->>'state'='released'` 作状态判断。`worktree/released` 进既有 `state_hash` 事件段不设排除；stage 19/20 测试文件字节不动，新断言只进 stage 21 测试。

**安装前断言。** 既有 worktree latch 行若 `value->>'state'='released'` 且无可证成功 release 事实 → 中止安装、报 session/binding；不回填、不静默投影回 prepared。

**Gate。** prepare 仍写 `prepared` 且投影 `prepared`。release succeeded：恰一条事件、投影 `released`、latch 仍 `prepared`。失败与 unknown：零事件投影 `prepared`。第二次 complete 为 `replay`、事件数仍 1。同 binding 第二个 source RAISE。同 binding 第二次独立成功 release：succeeded 结算、零新事件、投影保持 released。confirmed 的 release：投影变 `released`（若走了停工条款则改记台账不假绿）。`not_happened` 保持 `prepared`。子会话不继承该事件。

## §3 D13 — 接受

零 SQL，不换函数，不进 stage 21/22 失败条件。台账下一行用 **F23**（F21 保留未用；F22 仍只表示 catalog 缝）；事实列写明这是 **parity F4 / R3 C4**、与 parity F23（worktree 写入者）无关。条文：native `removeValue` 静默 return 不移植；错 `interaction_ref` 维持 C4 RAISE（含 submitted/current，零写）。关闭 parity §4 #2 → 「R5 已裁：不移植」。仅产品明确要求「重复 respond 不报错」才允许另开 Oracle 重开 C4；实现阶段禁止把 RAISE 改 return。

## §4 D14 — 接受（OID 绑定修订）

`v13_tools_catalog_frozen` VOLATILE 分支改为调用活体一对：handler 按 catalog 既有规则解析到**唯一 OID** 后，`v13_named_sql_writer(handler)` 非 NULL **且** `v13_spawn_writer_ok` 对**同一已解析 OID** 及元数据为真，才跳过这一条通用 VOLATILE RAISE（子串 `is VOLATILE` 不变）。禁止：文本名先行放行再二次解析；仅 `named_sql_writer` 非 NULL 即放行；捕获 `writer_ok` 异常继续；为 catalog 写更松副本。豁免后 schema-qualify、签名、`handler_digest`、frozen 一致性、ACL/search_path 照旧全跑。不建 `v13_volatile_sql_exception(oid)`；不换 guard（guard 已是这对的调用方）；不把 `spawn_subsession` 改回 `enabled=false`；不 `UPDATE tools`。

**RED 基线（硬前置，换体前、非超级用户、stage 21 前缀库）。** 直调 `v13_tools_catalog_frozen()` 必 RAISE 且命中 `spawn_subsession` 的 `is VOLATILE`；再走一次真实 `v13_parse` 路径同样 RED。42501/handler 不可解析/revision·digest/schema-qual 错不得误判为预期 RED；旧体已 GREEN → 停 stage 22，先查谁改了活体，不船空豁免。`pg_get_functiondef(v13_needed_judgments)` 须含 `v13_is_spawn_tool`（不含则停工——candidate_set_hash 属另一裁）；`v13_spawn_writer_ok` 对 `v13_route` 与 `v13_resolve` 须同值（SET ROLE 实测；依赖 `current_user` 分叉 → 停工）；`v13_named_sql_writer` 须 IMMUTABLE、`v13_spawn_writer_ok` 无写副作用可被 STABLE 调用（否则停工）。

**GRANT。** 两谓词 `REVOKE PUBLIC` 后 GRANT `v13_recall`/`v13_resolve`/`v13_route`（幂等）；不授 `v13_worker` 除非调用链证明 worker 执行到 catalog。gate 至少 `SET ROLE` 到 `v13_route` 与 `v13_resolve` 各跑一次真实 catalog/parse；超级用户跑绿不算数。

**换体后 gate。** enabled 的 `spawn_subsession` 不再因 VOLATILE 失败；名单外 VOLATILE sql 仍因同一子串失败；`v13_needed_judgments` 工具集仍不含 `spawn_subsession`；sql 快路臂命中该名仍 RAISE `batch-dispatched` 零子（parse 看见具名写者 ≠ route 可当普通 sql 工具执行）；扇出臂仍是唯一产子路径；源码 grep 断言名单只住在这两个函数体里。

## §5 第四务 — 驱动器 renew 后检查，零新 SQL 动词

不新增 `v13_worker_fourth_duty` 或任何会 complete 的 SQL 动词；无 LISTEN/NOTIFY、无新队列、无 `pg_terminate_backend`；`v13_cancel_pending` 与 `v13_interruptible` 只读不换体。第四务属于持有真实外部 IO 生命周期的 worker/driver（A18）。

**合同。** 每次 `v13_renew_lease` 成功之后、正常 complete 之前：读 `v13_cancel_pending`（查询失败 ≠ false，fail-closed 停止本次正常结算）→ 假则正常路径；真则 `v13_interruptible(tool_name)` 分派：

| `v13_interruptible(tool_name)` | kind | 动作 |
|---|---|---|
| `unsupported`（含 `tool_name` 空/NULL 的 routed llm） | 任意 | 不动，允许随后正常 `complete(succeeded)`；粘性 cancel 归 advance |
| `best_effort` | 任意（含 tool） | `complete(cancelled)` → 立即返回 |
| `required` | `llm` | `complete(cancelled)` → 立即返回 |
| `required` | `tool` | `complete(unknown)` → 立即返回（走既有抬墙） |
| `required` | `judge`/`human`/`context_refresh` | 不动，允许正常结算；禁止「保险性 unknown」（judge 进墙与已裁非 mutating 回收相撞） |

分派键是 `v13_interruptible(tool_name)` **不是 kind=llm**：空名 routed llm 是 `unsupported`，对它调 `complete(cancelled)` 必须仍是既有 RAISE（parity §4 #3 已冻），假 worker 正路径不得这么调。命中后不再发新 provider IO；第四务 complete 后立即退出禁止二次结算；用当前 renew 后有效 fence；每次成功 renew 都复查；`complete` 返回 `replay`/`stale` → 停止不另造结算。假 worker 只调 claim、renew、两谓词、complete；跟踪只进测试进程内存或 `pg_temp`，禁止永久关系。

**验收状态表。**

| 证据 | 可声明状态 |
|---|---|
| 只有 SQL 谓词 | 未实现 |
| + 假 worker gate（stage 22 测试全绿） | 合同已证明，真实接线未交付 |
| + gitignored `demo_v13/driver.py` 本机实跑退出码 0 | 环境级验证，最高 **🟡** |
| + 进仓库、可部署复现的 worker 接线并通过实跑 | 才可 ✅ 关闭 R4 |

fake gate 只证合同不证生产；Phase A 目标句不得写「R4 已完成」除非第四档在库。stage 22 README 两格并记；覆盖矩阵/摘要如实标 🟡。

## §6 三通道指名的假绿风险（实施对照清单）

1. tail gap 与 closeout ③ 是两套扫描 → 只换 tail gap 时 advance 不 RAISE 而 `closeout completed` 仍红；为绿整段放宽会把 `harness_reject` 的未还 wait 一并放掉。已并入 §1 closeout 同源强制。
2. 证人要求新回合 succeeded 与 triage 调用位置冲突（铸新格后段、失败/unknown 重试格新行非 succeeded）→ §1 条件 4 盖章即可。
3. 「最早一条 cap」抢种类（最早是 material_cap 则匹配的 repair 永不豁免）→ §1 anchor 按类返回。
4. 双信号要求两个 cap 都作答 → 与跳过臂「整条 index+1 一次丢掉」不一致；§1 条件 2 匹配其一豁免整条。
5. legacy 臂改读 `human/responded` → 活体主路径铸新回合静默消失；§1 臂 (b) 用自身 effect_done.seq。
6. D12 唯一索引惩罚写错位置的 replay → §2 调用点 ① 位置硬规定。
7. 只 complete 写 released → required 中断进墙再 confirmed 拆墙的释放永久 prepared；§2 调用点 ②。
8. 第四务按「llm 就 cancelled」→ 空名 routed llm 撞已裁 RAISE，粘性 cancel 反而到不了 advance；§5 分派键。
9. D14 让 parse 看见 spawn 后 sql 快路成第二生产者 → §4 换体后 gate 锁 `batch-dispatched` 零子。
10. 假 worker 跟踪表 / `v13_worktree_state` 做成表或视图 → 直接违反 R4；投影保持函数、跟踪测试进程内。
11. stage 21 换体 `v13_complete` 底稿漂移 → 活体 pg_get_functiondef 为底，签名/owner/security/search_path/GRANT 逐项比对，stage 17–20 全量回归是 D12 开工前置，不是普通回归建议。
12. 文档旧字面形成第二施工指令 → 路线图 §2.1 F23、§3 Phase A、§4 D12、Phase A 计划、偏差台账、覆盖矩阵统一改为事件投影三句（latch 永远 prepared；首次成功 release 写 `worktree/released`；`v13_worktree_state` 折叠 released）。

## §7 分叉与少数意见存档

- anchor 返回形状：grokBuild 主文 `p_kind 参数 + bigint`，codex 复合 `(anchor_seq, cap_class)` 且明言「仍实现为 bigint 不算按裁决交付」。控制器取复合返回 + 按类最早行（同时满足 grokBuild 条件 1「禁止先取任意种类最早再滤」）。
- 第四务验收：grokBuild「本机实跑退出码 0 记 ✅」vs codex「gitignored 实跑最高 🟡」。控制器取 codex（更严，防把环境级证据写成交付）；grokBuild 意见存档，复访触发=出现进仓库的 worker adapter。
- D11 豁免条件排序：kimi 要求「wait 链与 material_cap 恒不豁免」进谓词体不进注释——已并入 §1 条件 1/2。
- D14 波动性探针（`v13_spawn_writer_ok` 可否被 STABLE 调用）：codex 提出，控制器并入 §4 RED 基线前置。
- grokBuild D11 条件 3 允许「尚无事件的 ready/claimed 行在同一快照里可见也算」盖章——与 codex 条件 7「第一条 succeeded harness」并存时取宽者（盖章即可），因窄者在重试格重新卡死（风险 2）。

## §8 证据等级与边界

- 事实源：Phase A 骨架计划探针锚点（file:line 均经主会话复核）、路线图、parity 裁决、R3 链、R4、stage 20 活体（`test_fanout.py:440-479`、`load.py` 等本次抽查）。
- 本轮未做：任何 SQL 改动、代码提交、`v13_closeout`/`v13_advance` 活体全文核查（列为 stage 21 实施第一步义务，非假设）。
- Phase A 可据此开工；D7/D10/D15/D16 不在本轮，对应 stage 仍不开工。
