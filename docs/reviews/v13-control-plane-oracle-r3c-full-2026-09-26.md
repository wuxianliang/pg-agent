## Ask Oracle ✅
- Oracle group status: completed
- Oracle group: `B55A6DBC-8BD9-4D8E-9AEA-2C3E0F600D93`

### Oracle
- Status: Completed
- Provider: `grokBuild`
- Model: `grok-4.7-build-fast-xhigh`
- Effective effort: Provider default / not specified
- Chat: `new-chat-1523D0`



# v13 控制面 Oracle R3c（P2 机器形状补裁）

地位与 R3 §6/§7 相同。D1–D3、A15–A21、R3/R3a/R3b 不重开。零新表、零新列、零新 `effects.kind`。下文「属主」= 实施自定的那个 NOLOGIN 角色，不在此冻结名字。

**总判：P2 GO。** H6 取「换掉 RAISE、收据保持 schema_version 1」。H1/H3 是对 R2 §2.3 / 扇出字面的**显式收窄**。

---

## H1 · 预算算术（收窄 R2 §2.3）

**收窄理由：** 活体无 `max_turns`/`reserved`。`turn_budget.max_cycles` 是本 user turn 的路由环上限；`turn_no` 是花费计数。R1.11 禁止 spawn 改 `turn_no`，R3b 确认 ⑤ 不写它。把「剩余」接到 max_cycles 或 turn_no 会把树准入和路由环合成第二本账。**禁止**这条接线。

**替代（每子计 1，不是 max_turns）：** 策略行 `v13_policies` 名 `spawn_budget`，version 1，active，值**恰**两键：`max_nonterminal`（int 1..1000，种子 **8**）、`max_depth`（int 1..16，种子 **4**）。未知键/缺键/越界 → RAISE `v13: spawn_budget policy`。`max_depth` 与 A20 硬门同一键；P4 **不得**另立深度上限。

- `requested` **不是**入参键。`requested = jsonb_array_length(children)`。
- 非终态 = `status NOT IN ('completed','failed','cancelled')`（含 `blocked_unknown`）。
- 根 = 沿 `parent_session_id` 走到 NULL。超过 64 跳或重访 → RAISE `v13: spawn root cycle`。不锁根行。
- `parent_depth` = 父到根的跳数（根为 0）。
- 占用数 = 根的全部**子孙**（不含根）中非终态行数。
- 通过条件：`占用 + requested ≤ max_nonterminal` 且 `parent_depth + 1 ≤ max_depth`。否则 RAISE `v13: spawn budget exceeded` 或 `v13: spawn depth exceeded`，零 INSERT。
- 锁：仅 `v13_spawn_subsession` 调用  
  `pg_advisory_xact_lock(v13_advisory_class('spawn_budget'), hashtext(root::text))`  
  （两参 int 形式）。先持父行锁，再取咨询锁，持到事务结束。count 在锁之后；插完全部子后再数一次，仍超则 RAISE（同事务可见自己的插入）。`v13_fork` / closeout / recover / cancel **不得**取这把锁。
- `v13_advisory_class(name) → int` IMMUTABLE。闭集：`'spawn_budget'→13001`。未知名 RAISE。控制面类号只许 13001–13099，只许改这个函数，禁止哈希得出类号。

失败：策略坏、环、超预算、超深，全部 RAISE，不写子行。并发兄弟靠这把 xact 锁串行，禁止 `sessions.reserved`。

---

## H2 · `v13_spawn_subsession(uuid, jsonb) → jsonb`

**分工：** `v13_fork` 仍是单子原语（插一行、latch、validate-spawn、`forked`）。P2 只换属主，**语义不改、不查预算**（R2：锁只在准入路径）。模型入口只有 `v13_spawn_subsession`：校验 → 锁父 → 咨询锁 → 幂等查找 → 预算 → 循环调用 `v13_fork` → 补事件。禁止复制第二套 INSERT。

**入参恰两键**（未知键 RAISE `v13: spawn args`，零行）：

- `tool_call_id`：文本，`^[A-Za-z0-9_.:-]{1,128}$`
- `children`：数组，长度 ≥1，元素**恰** `{task}`；`task` 为 `char_length` 1..4000 的文本（允许非 ASCII）

禁止出现：`parent`、`cutoff`、`kind`、`count`、`overrides`、`session_id`、`requested`。服务端固定 `kind='fresh_fork'`、`overrides=NULL`、`cutoff=父.next_seq-1`（`next_seq=0` 则 fork 自己的 RAISE，整批回滚）。全体子共用这一 cutoff。

**调用前拒绝（零行）：** 父 status ∉ `{ready,waiting}`；父有未消费 `cancel/requested`（RAISE 文案沿用 `v13: unconsumed cancel/requested`）。

**回执事件**

- 父 `child-created`（权威；`source_effect_id` = 下面的 effect id，非空）恰键：  
  `schema_version:1`、`tool_call_id`、`spawn_kind:'fresh_fork'`、`cutoff`、`tasks_hash`、`children:[{session_id,task}]`（与入参数组同序）、`reservation:{requested,nonterminal_before,max_nonterminal,parent_depth}`（四键 int≥0）。
- 子 `spawn/task`（`source_effect_id` 必须 NULL）恰键：`schema_version:1`、`tool_call_id`、`task`。不写 `user/message`，不改子 `turn_no`，不在本事务 advance 子会话。
- `tasks_hash` = sha256(jsonb 数组文本)，数组=按序 task 字符串。

**返回恰键：** `replay_kind`（`created`|`replay`）、`parent_session_id`、`tool_call_id`、`spawn_kind`、`cutoff`、`children`（uuid 数组）、`tasks_hash`、`reservation`（同上四键）。

**幂等：** 父上已有同 `tool_call_id` 的 `child-created`：`tasks_hash` 相同 → 零写，返回 `replay`（reservation 抄事件原文）；不同 → RAISE `v13: spawn tool_call mismatch`。唯一索引 `(session_id, (payload->>'tool_call_id')) WHERE type='child-created'`。

**effect id：** `v13_spawn_request(tool_call_id, children) → jsonb` IMMUTABLE，唯一键序 `{tool:'spawn_subsession', params:{tool_call_id, children}}`。spawn 与 advance 都用它算 `v13_effect_id(sid,'tool', request)`。`child-created` 写在 handler 内、effect 行插在 handler 返回之后；`cycle_no` 不读 `child-created`，两处 id 相同。

失败模式只有 RAISE（无 `refused` 回执）。经 sql 快路时，现有 `BEGIN/EXCEPTION` 把 RAISE 收成 **failed tool effect、子事务零子**；`spawn/batch` 仍未消费，后续格可重试，`turn_budget` 封顶。不要改这个 EXCEPTION 来「修」重试。

属主 NOLOGIN NOSUPERUSER。三入口 DEFINER + 固定 `search_path`。属主须有函数体传递闭包的表权/EXECUTE；**禁止**把属主做成超级用户来绕过。安装自检：`SET ROLE` 属主调用 `v13_open_session` 成功；`v13_route` 直插 `sessions` 失败。

---

## H3 · 批量扇出（收窄「N 条 tool_call」）

**收窄理由：** 路由一格一个 action，无 tool_call 表；`harness_result/v1` 十键已封，禁止为扇出加键。P2 的 N = **一次** `spawn_subsession` 的 `children` 长度。不是 N 条 effect，也不是 N 次 advance。

| 物 | 落点 |
|---|---|
| 批次权威 | `events.type='spawn/batch'`，`source_effect_id` NULL。恰键 `schema_version:1`、`tool_call_id`、`children`（形状同 H2 入参） |
| 不是 | `decisions.answer`；也不是 effect 身份本身 |
| effect 回声 | advance 用 `v13_spawn_request` 写成 `{tool,params}`，只为 effect_id |
| 回执 | 现有 `tool/result.result` = H2 返回对象。不增加 `tool/result` 顶层键，不在 advance 里写循环 |

**生产者：** `v13_submit_spawn_batch(sid, spec) → bigint`，INVOKER，只授 `v13_route`。持父锁，校验同 H2，追加一条 `spawn/batch`。本 user turn 已有未消费批次 → RAISE。不建子、不取咨询锁。

**未消费：** 同会话、`seq > last_user_seq` 的 `spawn/batch`，且不存在同 `tool_call_id` 的 `child-created`。

**advance 切入点：** 只在 sql 臂、`tool='spawn_subsession'`。未消费批次数 ≠ 1 → RAISE `v13: spawn batch missing` 或 `ambiguous`（整笔 advance 回滚，含已写的 `turn/route`）。`param_spec` 必须为 `{}`；`resolve_tool_params` 非空 → RAISE。EXECUTE 的 `$2` = 批次的 `{tool_call_id,children}`（去掉 `schema_version`）。handler 必须是 `v13_spawn_subsession`（裸名或 `public.` 前缀），否则 RAISE `v13: spawn handler`。

预算失败 = H2 的 RAISE → 零子 + failed effect。N 与 0 之外的「部分子」不可提交。

---

## H4 · `v13_recover_idle() → jsonb`

扫出来的是**驱动提示**，不是验收本身。禁止调用 parse / advance / closeout / `send_work`，禁止写 `session/*`、`turn/end`、`turn/material_spent`，禁止改 status，禁止插 effect，禁止取 spawn 咨询锁。子 closeout 事务仍零父事件。

**空闲：** status ∈ `{ready,waiting}`，且无 `ready|claimed|unknown` effect，且 status ≠ `blocked_unknown`。

**三类原因**（可同时成立，各写一条）：

- `children_terminal`：直接子 ≥1，且全部 ∈ 三终态。fingerprint = sha256(按 `session_id` 升序的 `[[id,status],…]` 的 jsonb 文本)。
- `repair` / `replan`：本会话存在对应 `repair/required` 或 `replan/required`。fingerprint = sha256(该 type 全部 `seq` 升序 jsonb 数组文本)。不减「已消费」（无消费标记列）。多一次空 advance 可接受；禁止为它发明消费减法。

**事件 `recover/nudge`：** `source_effect_id` NULL。恰键 `schema_version:1`、`reason`（上三值）、`fingerprint`（64 位小写 hex）。同 `(session_id, reason, fingerprint)` 已存在 → 不二插。部分唯一索引执法。

**锁：** 候选按 `session_id` 升序，`FOR UPDATE SKIP LOCKED`（与 requeue **相反**：丢一拍靠下次 cron，不许和 advance 死锁）。锁内复验谓词。

**返回恰键：** `pending`（仍满足谓词的 uuid，升序）、`nudged`（本调用新插入的 nudge 条数）。第二次指纹不变 → `nudged=0` 且零 effect。

**调用者：** cron/驱动，函数外、提交后，对 `pending` 各做一次 parse+advance。验收由那次 advance 走已有 wake/route/closeout。`children_terminal` 的求值在 stage 18 换掉 P1 的 RAISE（R3a §6.2 已裁，此处只激活）。

---

## H5 · `v_goal_tree(p_root uuid)`

`LANGUAGE plpgsql STABLE`，RETURNS TABLE，不是 VIEW。

列（按此顺序）：`session_id uuid`、`parent_session_id uuid`、`depth int`、`status text`、`spawn_kind text`、`turn_no int`、`is_terminal boolean`。`is_terminal` ⇔ status ∈ 三终态。**不含**预算列、不含终态时间（无列可抄）。

根 depth=0，含根。向下递归 `parent_session_id`。未知根 RAISE `v13: unknown session`。路径重访 RAISE `v13: goal tree cycle`（不返回部分树，无 `cycle_detected` 列）。depth>64 RAISE `v13: goal tree depth`。`RETURN QUERY … ORDER BY depth, session_id`。

EXECUTE 授 recall、resolve、route。只读。

---

## H6 · 收据 `children`（终裁）

**否决 grokBuild（保留 RAISE）。** stage 18 之后父会话真有子；RAISE 不撤，父永远非终态，H1 占用数泄漏，树无法封账。把文案改成 `requires stage 19` 同样否决。

**否决 codex 的 schema_version 2 与 `state_hash` 元素。** 键集没变，不升版，避免双校验器。子印章哈希已在子会话自己的 `session/*` 里；嵌进父收据不进 R3b 的 state_hash 预像（印章 type 排除在预像外），只制造耦合。

**stage 18 `CREATE OR REPLACE v13_closeout`（从已加载函数的 `pg_get_functiondef` 改，禁止凭记忆重写；活体若没有子串 `children require stage 18` 则停）：**

- 删掉该 RAISE。
- 公共前置「无子会话」改为「无非终态**直接**子」。有非终态直接子（含 `blocked_unknown`）→ RAISE `v13: closeout precondition`，尾词 `children_open`。cancel 逃生**也**被这词挡住。P2 不给「子还活着就封父」的出口；等子终态或等 P3 扇出。
- 零直接子 → `children:[]`。全部直接子已终态 → 按 `session_id` 升序填  
  `[{session_id, status}]`，status ∈ 三终态。不要孙行，不要 `state_hash`、`spawn_kind`。
- `schema_version` 保持 1。state_hash 算法一字不改。不写 `turn_no`。
- stage 17 文件与 P1 前缀测试仍是旧 RAISE + 恒 `[]`。只改 stage 18 加载态。

---

## H7 · `mutating` / `write_targets` 存放位

**硬编码在函数体，不进表。** 禁止新列（`v13_tools_meta` 也不行）。禁止放进 `param_spec`（会被推导成 `param::`/`stated::` 信号）。禁止放进 `v13_policies`：R2 扩员 = 改 guard 源码 + 设计 + gate 同发；策略行翻 active 会变成不改代码的扩员后门。

`v13_named_sql_writer(handler text) → jsonb` IMMUTABLE。P2 闭集只有 `v13_spawn_subsession`（裸名与 `public.v13_spawn_subsession`），返回恰  
`{"mutating":false,"write_targets":["artifacts","events","latches","sessions"]}`（目标已按字典序）。其余名字 → NULL。

`v13_fork` 签名是 `(uuid,bigint,text,jsonb)`，**不能**当 sql 工具。不要为它插 `tools` 行。R2 点名保留在注释里，不进这个返回值。ch10 函数：实施时 grep；签名不是 `(uuid,jsonb)→jsonb` 的不要加。

stage 18 换体 `v13_tools_guard`（以活体定义为底）：`kind=sql AND enabled AND provolatile='v'` 时，允许名单之外仍 RAISE。名单内须**同时**：

- 签名 `(uuid,jsonb)→jsonb`，`prosecdef`，`proowner` = 属主
- `proconfig` 的 search_path **恰为** `pg_catalog, public`
- `REVOKE` 已生效：`public` 无 EXECUTE；`v13_route` 有 EXECUTE
- `lower(prosrc)` 不得含 `dblink`、`pg_net`、`copy program`、`lo_import`、`lo_export`、`pg_read_file`、`pg_write_file`
- 返回的 `mutating` 必为 false，`write_targets` **等于**上面四名（不是子集）

`tools` 行本身只有：`name='spawn_subsession'`，`kind=sql`，`handler='v13_spawn_subsession'`，`param_spec='{}'`，`enabled=true`，description 纯 ASCII 且无 `::`。先 REVOKE 再 INSERT（guard 在 INSERT 时查 ACL）。此 INSERT 会拨 `tools_revision`；gate 用相对比较。

---

## F · P3/P4 前向默认（避免再停洞）

已冻的不重复。下列默认在对应 stage 生效；与 ch08 **字面**冲突则停，不改裁。未标「另裁」的，开工时不得再当洞。

**P3 cancel 扇出**

- 应用序：depth 升、同层 `session_id` 升。锁获取序：**全部** `session_id` 升序锁完再写（防死锁）。这是对「祖先优先」的锁细化，不是改扇出语义。
- 每个非终态会话各写一条已冻的 `cancel/requested`（`scope` 仍是 `session`，不改 P1 键集）。终态零事件。返回类型保持 P1 的 text。
- `v13_cancel_pending(sid) → boolean` STABLE，谓词抄 R3b 未消费定义。worker 在每次 `v13_renew_lease` 成功后查它。无 LISTEN、无新队列。SQL 禁止 `pg_terminate_backend`。

**interruptible（与 H7 同一存放纪律）**

- `v13_interruptible(tool_name) → text` IMMUTABLE。闭集 `required|best_effort|unsupported`。未点名 → `unsupported`。禁止列、禁止 param_spec、禁止策略行。
- `unsupported`：维持 P1（claimed 不动，跑完由 advance 粘性吸收）。`complete(...,'cancelled')` RAISE `v13: interruptible unsupported`。
- stage 19 才把 `v13_complete` 的 `p_status` 加上 `cancelled`。条件：未消费 cancel，且（`best_effort` 或（`required` 且 kind=`llm`）），status=`claimed`，fence 匹配。写 `cancelled`、error NULL、`effect_done`，不写语义半边，不抬墙。
- kind=`tool` 且 `required`：禁止 `complete(cancelled)`，RAISE `v13: mutating interrupt settles unknown`；worker 必须 `complete(unknown)`（P1 已抬墙）。
- `best_effort`：succeeded/failed/cancelled 均可；kind=`tool` 的 unknown 仍只走现有 unknown 出口。

**FS effect = kind `tool`，不是新 kind。** 三个目录名 `worktree_prepare|worktree_merge|worktree_release`，handler `worker:worktree_*`，request 沿用四键 `{tool,params,handler,tools_revision}`，`params` 恰 `{binding_artifact_id}`。事务内不碰文件系统。

**worktree**

- latch 名 `worktree`。value 恰键 `schema_version:1`、`binding_artifact_id`、`state`（`prepared|released`）。
- artifact `kind='worktree_binding'`（若活体 `artifacts.kind` 有 CHECK，stage 19 `ALTER` 加这一值，不改旧文件）。inline 恰键 `schema_version:1`、`root_path`（1..1024）、`base_ref`（1..256）。
- `v13_requires_worktree(name)`：仅 merge 与 release 为 true。prepare 为 false（它自己创建 binding）。**不要**把所有 `kind=tool` 都设成要 binding（会卡死 `send_summary_email`）。这是相对 A19「mutating 无 binding 拒 claim」的收窄默认；若要把「凡外部 mutating harness」都收进来，**P3 开工前另裁**。在此之前 claim 只跳过 `requires_worktree` 且无该 latch 的行（返回空，不 RAISE）。
- prepare 的 `tool/result` 被下一格 advance 看见且尚无 latch → 同事务 `v13_latch_fire`。worker 禁止写 latch。
- stage 19 换体 `v13_fork`：非 fresh 复制 latch 时跳过 `worktree`。fresh 路径本就不复制。签名仍不改。
- `v13_latch_identity_excluded(name)`：P3 只有 `worktree`。换体 `v13_latch_digest` 排除这些名字。无此 latch 的会话 digest 不变。禁止用策略行做排除名单。

**P4**

- `goal/override` 恰键：`schema_version:1`、`intent`（`direct|decompose`）、`source_principal`（`user|operator`）、`reason`（文本 0..256，无则 `""`）。只授 route 的 `v13_submit_override`。同 type 取最大 seq。模型无 `v13_append_event`。
- `thresholds.action` **保持** `pass|reject` 两值。计划里的「六值」指路由 action，禁止 ALTER 去加 direct/decompose。
- 纯函数 `v13_triage_decide(proj jsonb) → text`，返回 `direct|decompose|human|reject|none`。`v13_triage_project(sid)` 组装投影。null 树字段不点火规则 5–6（gate 直接喂 null，不依赖缺父行；FK 下 depth 不会自然为 null）。
- 投影：`task_content_hash=v13_goal_hash`；`task_est_tokens` 用 goal 字节与既有 est 除数，无 goal 则 0；`user_intent_override` 为最后一条 override 的 intent 或 null；`has_mutating_hint` **恒 false**（禁止关键词启发式）；`policy_version` 抄会话；`explore_evidence_hash` 无 `explore/completed` 则为 null。10b：`ancestor_depth`；`n_nonterminal_children`；`remaining_turns = quota_remaining = max_nonterminal − 非终态子孙数`（同 H1，两键必须相等）；`subtree_reserved` = 该占用数。深度只读 `spawn_budget.max_depth`。
- `duty_cycle` 放策略行 `triage`（`{duty_cycle:1}`，0 或 1）。这是行为开关，不是扩员名单，允许进策略。0 → 不建工作：写一次 `triage/hold` `{schema_version:1,reason:'duty_cycle'}`，status=`waiting`，返回 `waiting`。recover 对「最后一条 hold 新于 last user 且 duty 仍为 0」的会话不 nudge。
- 阶梯仍以 R2 §3.2 为准。`direct` 时路由若选出 `spawn_subsession` → 改 human，reason `triage_direct`，零子。`decompose` 不强制 spawn。`human` → 只入队 human。`reject` → closeout failed，`turn_end_reason='triage_reject'`，并入**严格**前置（未付 material / wake / approval 仍须为空）。
- explore：同会话 `llm`，`route.reason='explore'`。本格禁止调用 spawn。标记事件 `explore/completed` 恰键 `schema_version:1`、`evidence_hash`（64 hex）。本 user turn 已有该事件 → 不得第二次 explore，review 走 human。不占 depth、不占 H1 名额。
- fold cap：直接读 `thresholds` 行，signal 名 **恰** `harness.repair_count` / `harness.replan_count`（不造假 decision，不走 `v_routes`）。计数 = 本会话该 type 事件条数。无带或命中 `reject` → human，request **恰** `{reason:'repair_cap'}` 或 `{reason:'replan_cap'}`（与 DP1 `{reason}` human 同形，不走 C4，不写 `interaction_kind`）。不要 session reject。默认 v1 带不改；测试自建新 frozen 策略版本。已答的这两类 human 按 R3a「cap human 已答 → 新 logical turn」执行。`material_cap` P4 仍不生产（超限 material 继续 RAISE）。

**明确仍不做：** `closeout/inbox_residual`、`quota/spent|voided`、G6 新条文（ch08 没有的断言不要编）。

---

## P2 重开：**GO**

H1–H7 的键、谓词、执法点、失败模式已够实现，且不靠再开一轮 Oracle。实施约束：

1. 新 SQL 只在 `v13/spawn/v13_spawn.sql`，一对 `BEGIN/COMMIT`。stage 1–17 文件字节不动。
2. 激活而非重裁：`v13_wake_is_satisfied_v1` 的 `children_terminal` 从 RAISE 改为 R3a §6.2；closeout 只改 H6 那一处。
3. 事件守卫用**新**触发器 `v13_spawn_event_guard`（`spawn/batch`、`child-created`、`spawn/task`、`recover/nudge`）。不要 REPLACE P1 的 `v13_control_event_guard`。
4. 新函数 REVOKE PUBLIC，工作函数 GRANT `v13_route`；`v_goal_tree` 另授 recall/resolve。不授 resolve 调用 spawn。
5. 唯一停工点：活体 closeout / `v13_tools_guard` / `v13_fork` 与上述前提不符（例如找不到 stage 18 那句 RAISE，或 `artifacts.kind` 的 CHECK 无法只靠追加值扩展）。停下来报告，不要换裁。

### Oracle 2
- Status: Completed
- Provider: `openCode`
- Model: `xai/grok-4.7`
- Effective effort: Provider default / not specified
- Chat: `new-chat-oracle-2-63E60C`



# v13 控制面 R3c 补裁（P2 机器形状）

P2 可重开。R2 §2.3 的 turn 算术在零新列下无落点，准入收窄为席位计数；扇出权威是 `tool/call` 事件，不是 harness 结果键。H6 取「无子仍 v1、有子 schema_version 2」，不保留 stage 18 RAISE。下文未写的键即非法。

## 活体锚点

`effects.kind` 五值、`tools` 六列、`sessions` 无 `max_turns`/`reserved`。`turn_no` 只在 `user/message` 上 +1（花费计数，R1.11 禁止 spawn 改它）。`turn_budget.max_cycles` 是 `v13_cycle_no` 的路由环上限，与子会话配额不同量纲。`v13_fork(uuid,bigint,text,jsonb)` 签名不改。咨询锁全树一参，与两参空间不相交。`param_spec` 是判断信号源，不能塞控制元数据。stage 18 只追加文件并 `CREATE OR REPLACE` 活体（加载到 17 之后的 `pg_get_functiondef`），不改 1–17 文件字节。

## H1 · 预算算术（对 R2 §2.3 的显式收窄）

**收窄理由：** 「Σ 每子 max_turns ≤ 根剩余 turn」没有列可读。用 `max_cycles − cycle_no` 会把「本 user turn 还能路由几次」当成「还能生几个子」，正常判断环即可把 fanout 打成 0。`turn_no` 不是上限。结构保留：不预扣、不写 `turn_no`、不写 `turn/material_spent`、聚合查询、失败零子、只在准入路径取两参咨询锁。turn 算术延到将来有列的裁决，P2 不加列。

策略行 `spawn_budget` v1 active：`{"max_nonterminal":16,"max_depth":4,"max_fanout":8}`，三键皆 JSON 整数 ≥1，缺键/类型错 RAISE `v13: spawn_budget policy`。

- `requested` = 本次 `children` 数组长度，不是 jsonb 预算键，不是每子 turn。
- 被加总 = 预算根的非终态子孙席位。非终态 = `status NOT IN ('completed','failed','cancelled')`（含 `blocked_unknown`）。不含根自己。
- 预算根 = 沿 `parent_session_id` 走到 NULL。环或深度 >64：RAISE `v13: goal tree cycle` / `v13: goal tree depth cap`，不取锁。
- 剩余检查：`nonterminal + requested ≤ max_nonterminal` 且 `parent_depth + 1 ≤ max_depth` 且 `1 ≤ requested ≤ max_fanout`。`parent_depth` 与 H5 同源（对预算根调用 `v_goal_tree` 读父行 `depth`）。失败 RAISE `v13: spawn admission`，尾词 `cap`|`depth`|`fanout`，零 INSERT。
- 锁：父行锁已持之后 `pg_advisory_xact_lock(18018, hashtext(root::text))`。类号规则 = `18000 + 引入 stage`，只许函数体字面量，禁止策略/GUC（翻转会拆互斥）。`hashtext` 原样传入，禁止 `abs`。closeout/recover/cancel 不取此锁。

## H2 · `v13_spawn_subsession` 与 fork

签名 `(uuid, jsonb) → jsonb`。`p_sid` 是父，调用方已持父行锁则重入，否则自锁。模型不可提供 parent/cutoff/kind/session_id/overrides/count/max_turns。

入参闭集：`{schema_version:1, children:[{tool_call_id}]}`。`tool_call_id` 文本 1..128、`^[A-Za-z0-9_./:-]+$`、批内唯一。数组长度见 H1。未知键、空数组、缺键 RAISE `v13: spawn args`，零行。

派生：`kind='fresh_fork'`（不复制 latch，只留 fork 既有的 generation latch；子因此不继承将来的 worktree）。`cutoff = next_seq - 1`，要求 `next_seq ≥ 1`，否则 RAISE `v13: spawn requires prefix`。不改 fork 的 cutoff 检查。父 `status` 必须 `ready|waiting`，否则 RAISE `v13: spawn from wall`（终态与 `blocked_unknown` 都不生）。fork 之后若子 `status <> 'ready'`，spawn UPDATE 为 `ready`（不改 fork 体；`waiting` 不得遗传）。

分工：fork 仍是唯一 INSERT sessions 的原语（属主换体，逻辑不改）。spawn 做准入、幂等、循环调用 fork、写父事件。spawn 不入队、不 `send_work`、不插 effect、不写 `tool/result`（那是 advance 臂）。

父事件 type = `child-created`（R2 字面，不用斜杠）。payload 闭集：`{schema_version:1, tool_call_id, child_session_id, spawn_kind:'fresh_fork', reservation:{nonterminal_before, requested, cap, depth}}`。无 `max_turns`。部分唯一索引 `(session_id, (payload->>'tool_call_id')) WHERE type='child-created'`。

幂等：全有且子行在、`spawn_kind` 相符 → 不写，返回 replay。有无混杂、有事件无行、kind 不符 → RAISE `v13: spawn ledger`，零写。

返回闭集（created/replay 同键）：`{schema_version:1, replay_kind:'created'|'replay', children:[{tool_call_id, session_id, spawn_kind:'fresh_fork'}]}`。顺序 = 对应 `tool/call` 的 `seq`。`replay_kind` 由函数计算，不来自调用者。

## H3 · 批量扇出

**权威 = 事件 `tool/call`，不是 `decisions.answer`，不是 `harness_result`。** R3a 十键 `additionalProperties:false`，往结果里加 tool_calls 即重开 R3a。P2 收窄 R2「llm/harness」为 **仅 llm**：`v13_complete` 在写行前，若 `kind=llm` 且 `p_status=succeeded` 且 result 含 `tool_calls`，校验后同事务按数组序各追加一条 `tool/call`（`source_effect_id`=该 effect）。缺键 = 今天的 llm 路径，零变化。形状坏 = RAISE 零写（不烧 attempt/fence）。harness 结果出现该键仍按未知键拒。worker 不写 sessions。

`tool/call` payload 闭集：`{schema_version:1, id, name:'spawn_subsession', args:{}}`。`id` 规则同 `tool_call_id`。`name` 不符或 `args` 非空对象 → 整批 RAISE。唯一索引 `(session_id, (payload->>'id')) WHERE type='tool/call'`。

advance（会话锁内，步 0/墙/cancel 之后、P0 finish 之前）：本 user turn（`seq > last_user_seq`）未消费的 `tool/call` 合成**一批**。未消费 = 无同 `tool_call_id` 的 `child-created`。零条 → 旧管线。有则**不**走 P0 finish，**不**走通用 sql `EXECUTE`/`EXCEPTION` 吞错臂，直接调 `v13_spawn_subsession`。成功后才写一条 `turn/route`（`{action:'sql', reason:'spawn_fanout', tool:'spawn_subsession', params:{}}`）+ 一条 succeeded tool effect（request 含 `source_effect_id` 与 children，身份仍走 `v13_effect_id`）+ 一条 `tool/result`（既有三键，`result`=函数返回值）。任一步 RAISE = 整笔回滚，零子。返回 `progressed`。

已全消费则不进本臂。禁止 route 再选中该工具：`v13_needed_judgments` 活体排除 `v13_is_spawn_tool`（字面量单源，同 `v13_is_harness_tool`）。若 sql 臂仍命中该名 → RAISE `v13: spawn_subsession is batch-dispatched`，不落 failed effect。

## H4 · `v13_recover_idle`

`v13_recover_idle(p_sid uuid DEFAULT NULL) → jsonb`。NULL = 全表。调用者是驱动/cron；P2 不装 pg_cron、不调 parse/advance/closeout（parse 有判断 IO）。函数幂等，不入队，不改 `status`。

候选（锁外收集，`session_id` 升序，`FOR UPDATE` 后重检，不用 SKIP LOCKED）：`status IN ('ready','waiting')`，无 `unknown|ready|claimed` effect，且命中其一：

- `children_ready`：≥1 直接子且全部终态，且无本代 `recover/idle`。代 = sha256(按 session_id 升序的 `id||status`)。
- `repair_unconsumed` / `replan_unconsumed`：存在该 type 事件，且无 `generation = 该事件 seq` 的 nudge。不把信号标成已消费（P4 才 fold）。

写一条 `recover/idle`：`{schema_version:1, cause, generation}`。`cause` 仅上三值。唯一索引 `(session_id, (payload->>'cause'), (payload->>'generation')) WHERE type='recover/idle'`。不发新 pgmq kind（`v13_send_work` 只认 effect；丢唤醒靠下次扫描）。返回 `{"nudged":n}`。第二次同代：零事件、零 effect。

无子的 `ready` 不是候选（那是等用户）。子会话启动 = 调用方读 H2 回执后再 advance，不是 recover。墙与终态排除。不取 spawn 咨询锁。

## H5 · `v_goal_tree(uuid)`

STABLE SRF，非 VIEW。名字用 A21 字面 `v_goal_tree`。未知根 RAISE `v13: unknown session`。

返回列仅：`session_id uuid, parent_session_id uuid, depth int, status text, spawn_kind text, turn_no int, is_terminal boolean`。无预算列、无终态时间戳。`depth` 相对参数根，根=0。`is_terminal` = 三终态。递归 `sessions.parent_session_id`。环 RAISE `v13: goal tree cycle`（不设标记列）。深度 >64 RAISE `v13: goal tree depth cap`（不截断）。`ORDER BY depth, session_id`。GRANT EXECUTE 给 recall/resolve/route。

## H6 · 收据 `children`（终裁）

驳回「继续 RAISE / 改文案到 stage 19」：stage 18 已在，父有子则永远封不了账，spawn 成死路。驳回 grokBuild「怕动 state_hash」：R3b 的 `state_hash` 不含印章 payload，也不含子行，填 `children` 不改变哈希。P1 gate 只加载到 17，前缀字节不动。

- 无直接子：与 P1 逐字节相同，`schema_version=1`，`children=[]`。
- 有直接子：任一非终态 → 任何 outcome RAISE `v13: closeout precondition`，尾词 `children_open`（含 cancel/预算逃生；P2 不扇出，不能把活子树封进父终态）。全部终态 → `schema_version=2`，其余收据键不变。`children` = 直接子对象数组，按 `session_id` 文本升序，元素闭集 `{session_id, status}`，`status` 仅三终态。不含孙、不含 `state_hash`、禁 null。
- 不变量：`schema_version=1` ⇔ `children=[]`；`=2` ⇔ 非空对象数组。不符 RAISE。
- advance 的 finish/reject/逃生臂在调 closeout 前若存在非终态直接子：不调用 closeout、不 RAISE 给驱动（否则重试风暴），`status` 非墙则置 `waiting`，返回 `waiting`。子齐后由 H4 nudge + 下一次 advance 封账。

## H7 · `mutating` / `write_targets` 落点

**函数体字面量，不进策略行、不扩 `v13_tools_meta`、不进 `param_spec`。** 策略翻转是变相 `UPDATE tools` 扩员，且不 bump revision。`param_spec` 会被推导成 `param::`/`stated::` 信号。

单源 `v13_volatile_sql_exception(oid) → boolean`：仅当 proname=`v13_spawn_subsession`、签名 `(uuid,jsonb)→jsonb`、`provolatile='v'`、DEFINER、`search_path` 钉死、属主=专用 NOLOGIN、PUBLIC 无 EXECUTE、EXECUTE 只在 `v13_route`、`prosrc` 不含 `dblink`/`pg_net`/`COPY PROGRAM`/`lo_import`/`lo_export` 时为真。`v13_is_spawn_tool(name,kind)` IMMUTABLE，唯一字面量。扩员 = 改这两函数 + 设计 + gate，禁止 `UPDATE tools` 扩员。

`mutating=false` 不存数据：名字在闭集内即该声明。`write_targets` 不存行：`v13_sql_write_targets(name) → text[]`，`spawn_subsession → {sessions,events,latches}`，其余 NULL。NULL + VOLATILE = 拒（这就是零列下的「缺键」）。guard 与目录冻结函数（活体名实施时 `pg_get_functiondef` 核对，注释里的 `v13_tools_catalog_frozen` 为准；找不到则停，不要只改 guard）都调同一谓词，禁止两份名单。`spawn_subsession` 行：`kind=sql`，`handler=v13_spawn_subsession`，`param_spec='{}'`，`enabled=true`。`param_spec <> '{}'` → guard RAISE。

## F · P3/P4 前向默认（避免再停洞）

| 项 | 状态 | 裁定 |
|---|---|---|
| cancel 扇出写什么 | 已冻语义 | 每会话一条既有 `cancel/requested`（`scope` 仍 `'session'`，不新增 scope）。锁序 = `v_goal_tree` 的 `depth, session_id`。终态子孙跳过。 |
| `interruptible` | 未冻存放 | 同 H7：`v13_interruptible(name)→text` 字面量，缺省 `unsupported`。禁止策略行。required=看到 `cancel/requested` 后 settle cancelled；unsupported=complete 仍 `accepted`，结果事件留着，advance 的 cancel 相封 `cancelled` 且不消费该结果；best_effort=未打断则同 unsupported。mutating 中断 settle `unknown` 并调已有抬墙 helper。 |
| FS effect 的 kind | 未冻，被五值逼死 | **`kind=tool`**，`tool_name` ∈ `worktree_prepare\|worktree_merge\|worktree_release`。外部 IO 走现有 a2。禁止新 kind，禁止 sql（sql 零外部 IO）。 |
| worktree latch 值 | 未冻 | `{schema_version:1, path_hash:64hex}`。`artifacts.kind` 若不容 `worktree_binding` 则 **latch-only**（P3 开工先查 CHECK；要内容寻址再另裁）。子不复制（fresh_fork 已保证）。 |
| prefix 排除 worktree | 未冻机制 | stage 19 `OR REPLACE v13_latch_digest`：排除字面量 `ARRAY['worktree']`。无该 latch 的会话 digest 逐字节不变。 |
| 无 binding 拒 claim | 未冻名单 | `v13_requires_worktree(name)` 字面量，种子空。空 = 无人被拒；测试名写进 stage 19 函数体。 |
| 第四务线协议 | 未冻 | fake **轮询** `cancel/requested`。不发明 LISTEN 协议。真 worker 线协议 P3 不挡。 |
| `goal/override` payload | 半冻 | `{schema_version:1, intent:'direct'\|'decompose', source_principal:'user'\|'operator', reason?}`。`reason` 0..256 可缺。未知键拒。唯一写者 `v13_goal_override(...)`。模型路径不写。 |
| Jev Choice | 半冻 | 信号名 `triage`，`kind=choice`，选项恰 `direct/decompose/human`。映射在函数里，**不扩** `thresholds.action`（活体只有 `pass/reject`；计划「六值」指路由出口，不是该列）。 |
| 10a/10b 落点 | 未冻 | `v13_triage_features(sid)→jsonb`，键=R2 §3.1 闭集。缺失为 JSON null，null 不点火。不建表。 |
| explore | 半冻 | 同会话 `kind=llm`，request 加 `{explore:true, tools:['session_stats']}`。不 spawn、不占 depth/席位。只读靠 worker 契约，SQL 不第二套执法。 |
| fold cap | 未冻存放 | 策略行 `harness_fold_cap` `{"repair":3,"replan":3}`（可调上限，不是身份闭集）。超限 → human，不 RAISE。这是 R2 §1.3，不是被否的 material 身份错误。 |
| `min_child_max_turns` | 接不上 | 与 H1 同一收窄：P4 硬门改读 `spawn_budget` 的 depth/席位，不发明 turn 列。 |
| 第四务真线协议、artifact kind 要内容寻址 | — | **P3 开工前另裁**仅当拒绝 latch-only 或拒绝轮询。否则按上表默认，不必再叫 Oracle。 |

P2 顺手履行已裁、不算新洞：`v13_complete` 去掉 `children_terminal requires stage 18`；`v13_wake_is_satisfied_v1` 按 R3a §6.2 评估（直接子、全终态、缺失/非直接子/重复 RAISE）。complete 仍不评估「是否已满足」。

## 文件与顺序

只新增 `v13/spawn/`（`v13_spawn.sql` 一对 `BEGIN/COMMIT`、`setup_db.py`、`test_spawn.py`、README），`SQL_LOAD_ORDER` 末尾追加。同事务内顺序：策略行 → 谓词/索引/事件守卫扩 type → 属主+INSERT 触发器+fork 换属主 → `v13_open_session` → spawn 函数 → complete 投影与 wake 启用 → advance 臂与 park → closeout H6 → `v_goal_tree` + recover → guard/冻结谓词 → tools 行（会 bump `revision`，gate 用相对比较）。触发器与三函数必须同事务，否则 18 的库上直插会红而函数尚未就位。

实施前核对：活体 advance/complete/closeout/needed_judgments/目录冻结函数名。冻结函数找不到、或 needed 无法加名字过滤而不改语义 → 停，不要平行做第二份推导。

## 风险

H6 的 v2 只出现在「有直接子」的印章上；无子路径与 `state_hash` 算法不动。1–17 前缀不加载 stage 18。不要把 H1 收窄「修回」`max_cycles`。

## 裁决

**GO。** 六洞与 H6 分歧已闭，P2 不必再等 Oracle。P3/P4 按 F 表默认可开工；仅当拒绝 latch-only 或拒绝轮询第四务时才另裁。

### Oracle 3
- Status: Completed
- Provider: `codex`
- Model: `gpt-5.6-sol`
- Effective effort: `xhigh`
- Chat: `new-chat-oracle-3-6D69FB`



# 1. Summary

R3c resolves H1–H7 and freezes the remaining P3/P4 machine contracts. P2 is **GO with one explicit narrowing**: the live schema has no subtree-turn reservation or `max_turns` projection, and `turn_budget.max_cycles` is an intra-user-turn route-loop limit, so stage 18 will not misuse either as a lifetime spawn budget. Instead, P2 admits children against an existing-policy active-descendant cap, protected by the required two-argument root advisory lock. Spawn requests, receipts, tool-call discovery, recovery wakeups, tree projection, child closeout receipts, and tool metadata all receive closed shapes. P2 remains additive except for the deliberate stage-18 sessions write gate and the stage-18 closeout extension from `children=[]` to direct-child receipt objects.

# 2. Current-state analysis

- `v13/schema/v13_core.sql` owns the control-plane base:
  - `sessions` has `parent_session_id`, `parent_cutoff_seq`, `turn_no`, `status`, and route-policy identity, but no `max_turns` or reservation column.
  - `events` is append-only with an open `type` vocabulary and `source_effect_id`.
  - `effects.kind` is closed to `judge|tool|llm|context_refresh|human`; no new kind may be added.
  - `tools` has no `mutating`, `write_targets`, or `interruptible` columns.
  - `v13_policies` is the existing versioned JSON policy carrier and is the only suitable no-schema-change location for control metadata.
  - `v13_tools_meta` is a numeric catalog-generation counter; it must not become a JSON metadata store.
- `v13/loop/advance.sql` holds the only progression loop. Its SQL fast path executes a registered `(uuid,jsonb)->jsonb` handler while holding the session lock, then creates a succeeded `tool` effect and `tool/result` event in the same transaction.
- `v13/periphery/v13_periphery.sql` owns `v13_fork`, latch inheritance, fork identity validation, and the existing child-side `forked` event. `v13_fork` currently does not write a parent receipt.
- `v13/twophase/v13_twophase.sql`, later replaced by the mgraph stage, owns stale-lease recovery. Stage 18 must not replace the live mgraph recovery body with the older twophase body.
- `turn_budget.max_cycles` and `v13_cycle_no()` count route cycles within the current user turn. `sessions.turn_no` counts user messages/turns. Neither is a valid subtree lifetime reservation.
- `v13_send_work()` only sends effect messages `{kind:'effect',id}`. It cannot directly wake a session without changing its message contract.
- Stage 17 closeout keeps `children=[]` and rejects child-bearing closeout with a stage-18 guard. P2 must decide whether to remove that guard; it does so below.

The spawn call chain after R3c is:

```text
completed orchestrator effect
  → effects.result.tool_calls
  → v13_route / v13_advance recognizes only spawn_subsession calls
  → existing SQL fast-path handler invocation
  → v13_spawn_subsession(parent, params)
  → shared fork primitive
  → child sessions + child forked events
  → parent child/created events
  → existing succeeded tool effect + tool/result
  → later recover_idle / parse / advance
```

All spawn writes remain inside one PostgreSQL transaction. No worker-side control-plane write and no external filesystem or network operation is introduced by P2.

# 3. Design

## H1 — Spawn admission arithmetic

### Ruling

R2 §2.3 is narrowed for P2 from lifetime-turn reservation to **active descendant slot admission**. This is necessary because the live schema contains no `max_turns`/reservation field and `turn_budget.max_cycles` has a different semantic scope.

### Policy carrier

Add one active row to existing `v13_policies`:

```text
name    = spawn_budget
version = 1
value   = {
  "max_active_descendants": 16,
  "max_batch_children": 32
}
```

The row is append-only under the existing policy trigger. Missing, malformed, or inactive policy is fail-closed.

### Exact arithmetic

- `requested` = number of entries in `p_spec.children`.
- Each nonterminal descendant contributes exactly **one active slot**.
- Nonterminal statuses are every status except `completed|failed|cancelled`; `blocked_unknown` therefore consumes a slot.
- Resolve `root_session_id` by recursively following `parent_session_id` from the parent.
- Under the root advisory lock, compute:

```text
used      = count(descendants of root where status NOT IN terminal statuses)
remaining = max_active_descendants - used
admit iff requested >= 1
      and requested <= max_batch_children
      and requested <= remaining
```

- The parent itself is not counted when it is the root; a non-root parent is already counted as a root descendant.
- No `turn_no`, `v13_cycle_no()`, `turn_budget.max_cycles`, or hidden reservation is read or modified.
- Child termination frees its active slot; P2 does not reserve future turns for a child.

This is a deliberate R2 §2.3 narrowing: P2 prevents concurrent sibling oversubscription but does not claim a lifetime turn/quota guarantee. A future lifetime-turn budget requires a separately defined persisted projection and is not silently inferred from `turn_no`.

### Lock allocation

All spawn-budget admission paths use:

```text
pg_advisory_xact_lock(13018, hashtext(root_session_id::text))
```

`13018` is the permanent v13 spawn-budget lock class: `13` identifies the v13 control plane and `018` identifies stage-18 spawn admission. No other current advisory-lock path uses this two-argument class. The lock is acquired before the aggregate query and before any child insert.

### Failure behavior

- Parent terminal or `blocked_unknown`: raise, zero writes.
- Policy missing/malformed: raise, zero writes.
- Batch over 32, empty, duplicate, or over remaining slots: raise, zero child rows/events.
- Concurrent sibling admission: serialized by the root lock; the second transaction recomputes `used` after waiting and either admits or raises.
- Parent `turn_no` is unchanged.

## H2 — `v13_spawn_subsession` input, output, and shared primitive

### New callable

```text
v13_spawn_subsession(p_parent uuid, p_spec jsonb) → jsonb
```

It is `SECURITY DEFINER`, owned by the dedicated control-plane NOLOGIN owner, has a fixed `search_path`, is not executable by `PUBLIC`, and is granted only to `v13_route`.

### Input closed set

Top-level keys must be exactly:

```text
{
  "schema_version": 1,
  "children": [
    {
      "tool_call_id": string,
      "kind": "exact_replay" | "recompute" | "fresh_fork",
      "overrides": object | null
    }
  ]
}
```

Rules:

- `children` is a non-empty array of at most 32 objects.
- `tool_call_id` is ASCII, length 1–256, matching `[A-Za-z0-9._:-]+`, and unique within the batch.
- `overrides` must be `null` unless `kind='fresh_fork'`; non-object values are rejected.
- `parent_session_id`, `cutoff_seq`, `fence`, `prefix_identity`, quota, and status are forbidden input keys.
- The server derives the parent, current cutoff (`parent.next_seq - 1`), root, identity, latch behavior, and policy state.
- A parent with `next_seq=0` cannot spawn because no valid nonnegative fork cutoff exists.

### Output closed set

```text
{
  "schema_version": 1,
  "replay_kind": "created" | "replayed",
  "parent_session_id": uuid,
  "root_session_id": uuid,
  "requested": integer,
  "active_before": integer,
  "active_after": integer,
  "remaining_after": integer,
  "children": [
    {
      "tool_call_id": string,
      "session_id": uuid,
      "kind": "exact_replay" | "recompute" | "fresh_fork",
      "cutoff_seq": integer
    }
  ]
}
```

The child array is sorted lexicographically by `tool_call_id` for deterministic receipts.

### Idempotency

- Parent `child/created` events are the idempotency records.
- Add a partial unique index on `(session_id, payload->>'tool_call_id')` for `type='child/created'`.
- Each receipt event stores the canonical child-spec SHA-256 as `request_hash`.
- All IDs absent: create the complete batch and return `replay_kind='created'`.
- All IDs present with matching hashes: return the existing child IDs and `replay_kind='replayed'`; do not call the fork primitive.
- Mixed existing/new IDs or any hash mismatch: raise; do not partially create.
- Missing child row, malformed receipt, or duplicate receipt is a data-integrity error and raises.

### Shared fork path

Introduce one private helper, not a second progression loop:

```text
v13_fork_one(parent, cutoff, kind, overrides, source_tool_call_id, request_hash)
```

- `v13_fork` keeps its existing public signature and calls the helper with the source fields absent.
- `v13_spawn_subsession` calls the same helper after admission and idempotency checks.
- The helper owns child-row creation, latch inheritance, context-artifact validation, identity validation, and the child `forked` event.
- `v13_spawn_subsession` alone owns parent `child/created` events and batch receipt construction.
- Existing direct `v13_fork` event payload shape remains unchanged when no spawn source is supplied.

## H3 — Batch tool-call protocol

### Canonical storage

Tool calls are read from the existing succeeded orchestrator effect:

```text
effects.result.tool_calls
```

The already-existing `llm/message` event mirrors the same result, but `effects.result` is authoritative for dispatch. No new table, column, or effect kind is added.

Each tool call must be exactly:

```text
{
  "id": string,
  "name": "spawn_subsession",
  "args": {
    "schema_version": 1,
    "kind": "exact_replay" | "recompute" | "fresh_fork",
    "overrides": object | null
  }
}
```

`tool_calls` must be a non-empty array of unique IDs. P2 accepts a result only when every call in the array is `spawn_subsession`; mixed tool names are unsupported and raise rather than silently dropping calls.

### Dispatch algorithm

1. `v13_complete` continues to store the full LLM result; the existing non-empty `text` requirement remains.
2. `v13_route` checks the current-turn succeeded LLM result for `tool_calls` before its normal “latest `llm/message` means finish” branch.
3. It validates every call and returns the existing action vocabulary:

```text
{action:'sql', reason:'spawn_subsession',
 tool:'spawn_subsession',
 params:{schema_version:1, children:[...]}}
```

4. The existing SQL fast path invokes `v13_spawn_subsession` once with the flattened child array.
5. The existing fast path then creates one succeeded `tool` effect and one `tool/result` event containing the spawn receipt.
6. Child rows, child events, parent receipt events, the tool effect, and `tool/result` are one transaction.

Thus N valid calls produce N children, while any validation, budget, lock, fork, or receipt failure rolls back all N and produces no child or tool-result writes.

## H4 — `v13_recover_idle`

### New callable

```text
v13_recover_idle(p_limit integer DEFAULT 64) → jsonb
```

It is a route-owned, volatile, idempotent sweep. It does not parse, route, enqueue, or create effects.

### Parent child-terminal wake

For each eligible nonterminal parent:

- Parent must not be `blocked_unknown`.
- Parent must have no `ready|claimed|unknown` effects.
- A direct child must have a current terminal status and exactly one matching `session/completed`, `session/failed`, or `session/cancelled` event.
- If no matching parent marker exists, append:

```text
type    = child/terminal
payload = {
  "schema_version": 1,
  "child_session_id": uuid,
  "child_status": "completed" | "failed" | "cancelled",
  "child_terminal_seq": integer
}
```

- Add a partial unique index preventing a second `child/terminal` marker for the same parent and child.
- Set parent `sessions.status='ready'` if it was `waiting`; leave `ready` unchanged.
- Do not write a parent event from the child closeout transaction.

### Repair/replan wake

- `repair/required` and `replan/required` are unconsumed when no later `turn/route` event has the same `source_effect_id`.
- If an eligible idle session has any such signal, set it to `ready`; do not append a second marker.
- The next advance route event uses the signal’s `source_effect_id`, making consumption observable and idempotent.
- A signal on a wall, terminal session, or session with active effects is not consumed or cleared.

### Return shape and invocation

Return exactly:

```text
{
  "schema_version": 1,
  "parents_marked_ready": integer,
  "child_notifications": integer,
  "repair_wakes": integer,
  "replan_wakes": integer,
  "session_ids": [uuid...]
}
```

Lock eligible parent sessions in ascending `session_id`, recheck predicates after lock acquisition, and process at most `p_limit` parents. The caller is an external cron/driver sweep that invokes parse plus advance for returned sessions. P2 deliberately uses **status plus durable marker**, not `pgmq`, because `v13_send_work()` is effect-only and adding a session-message protocol would be a second wake contract.

## H5 — `v_goal_tree(root)`

### Signature and columns

```text
v_goal_tree(p_root uuid)
RETURNS TABLE (
  session_id         uuid,
  depth              integer,
  parent_session_id  uuid,
  status              text,
  spawn_kind         text,
  turn_no            integer,
  terminal_seq       bigint,
  terminal_at        timestamptz
)
STABLE
```

No budget column is exposed because P2’s admission unit is an active descendant slot, not a turn reservation.

### Read and validation algorithm

- Require `p_root` to exist and have `parent_session_id IS NULL`; otherwise raise.
- Recursive CTE follows `sessions.parent_session_id`.
- Maintain a UUID path array.
- If a child already occurs in the path, raise `v13: session tree cycle`; do not return a partial tree.
- `terminal_seq`/`terminal_at` come from the matching `session/<status>` event, or are null for nonterminal rows.
- Return root at depth 0.
- Stable order is `depth ASC, session_id ASC`.

The function is read-only and does not acquire advisory locks or repair malformed parent pointers.

## H6 — Child closeout receipt

### Verdict

Take the codex position with a compatibility-preserving refinement:

- P2 removes the stage-18 rejection.
- `children` remains a top-level array under `schema_version=1`; no schema-version bump is required because P1 already defines the field as an array and P1 no-child receipts remain byte-for-byte unchanged.
- Child entries have exactly three keys:

```text
{
  "session_id": uuid,
  "status": "completed" | "failed" | "cancelled",
  "state_hash": 64-character lowercase SHA-256
}
```

### Closeout behavior

- A parent with no direct children continues to emit `children: []`.
- A parent with direct children locks those child rows in ascending ID order and requires every child to be terminal.
- It reads each child’s closeout seal and copies its `state_hash`.
- Any nonterminal child, missing seal, malformed hash, or duplicate child ID raises before the parent writes its terminal events.
- The parent children array is sorted by `session_id`.
- The existing parent `state_hash` algorithm remains unchanged; the durable `child/terminal` events already included in the parent event stream make child completion observable.
- The P1 gate expecting `closeout children require stage 18` remains valid only when loading stage 17. Stage-18 tests replace it with child receipt assertions.

## H7 — Tool metadata location

### Verdict

Store control metadata in an existing `v13_policies` row named `tool_control_allowlist`; do not extend `tools`, `v13_tools_meta`, or `param_spec`.

Stage-18 version-1 value contains only:

```text
{
  "spawn_subsession": {
    "mutating": false,
    "write_targets": ["artifacts", "events", "latches", "sessions"],
    "interruptible": "unsupported"
  }
}
```

`write_targets` is sorted, unique, and must be a subset of the closed set `{sessions,events,latches,artifacts}`. `mutating=false` means no external side effect; it does not mean the SQL handler is read-only.

### Guard behavior

`v13_tools_guard` permits the VOLATILE exception only when all conditions hold:

- tool name is `spawn_subsession`;
- handler is exactly `v13_spawn_subsession`;
- signature is `(uuid,jsonb)->jsonb`;
- policy entry exists and has the exact `mutating=false` and write-target shape;
- function is `SECURITY DEFINER`, fixed-search-path, owned by the control owner, has no `PUBLIC` execute privilege;
- source scan contains no filesystem/network/program execution primitive;
- tool row is enabled.

Any other VOLATILE SQL tool, missing policy entry, policy drift, or handler mismatch raises. The policy row is audit metadata; the guard and handler both revalidate the exact closed exception, so merely inserting a future policy version cannot silently authorize another function.

# 4. P3/P4 forward sweep

## P3 stage 19

| Area | Status | R3c machine ruling |
|---|---|---|
| Cancel fanout | Partly frozen | `v13_cancel` locks sessions ancestor-first, then same-depth `session_id ASC`; appends at most one `{schema_version:1,scope:'session'}` `cancel/requested` event per nonterminal descendant; cancels ready effects only; claimed/unknown remain unchanged; terminal descendants are skipped. One transaction, no parent lock after child lock. |
| Cancel idempotency | Frozen in principle | Existing per-session unconsumed-cancel predicate remains the source of truth; repeat call returns replay and performs no second event. |
| `interruptible` location | Not frozen | Extend `tool_control_allowlist` entries with `interruptible: required|best_effort|unsupported`; missing entry is claim-denied, not implicit unsupported. |
| Worker fourth duty | Not frozen | Worker checks cancel at claim, heartbeat, and before complete. `required` must acknowledge/abort; `best_effort` attempts abort then reports outcome; `unsupported` finishes and advance absorbs the sticky cancel. SQL must never call `pg_terminate_backend`. |
| Mutating interruption | Frozen semantically | A mutating tool interrupted after external commit becomes `unknown`, calls `v13_raise_unknown_wall()` in the same transaction, and cannot be rewritten by cancel. |
| FS effect kind | Not frozen | Use existing `effects.kind='tool'`; tool names are `worktree_prepare`, `worktree_merge`, and `worktree_release`. No FS effect kind is added. |
| FS request shape | Temporary default | Exact request top-level keys: `{tool, params, handler, tools_revision}`; `params` is `{schema_version:1, operation:'prepare'|'merge'|'release', worktree_id, binding_hash|null}`. Handler performs FS work outside SQL. |
| Worktree latch | Not frozen | Existing `latches` row name `worktree`; value exactly `{schema_version:1, worktree_id}`. `worktree` is excluded from prefix identity. |
| Binding artifact | Not frozen | Existing `artifacts` row with `kind='worktree_binding'`; inline exactly `{schema_version:1, worktree_id, binding_ref, binding_hash}`. `binding_hash` is lowercase SHA-256. No binding means claim skips/rejects the worktree tool. |
| Fork inheritance | Frozen direction | `v13_fork` must not copy `worktree` latch or binding artifact to a child. |
| Prefix identity | Frozen direction | `v13_latch_digest` excludes `name='worktree'`; all other latch identity rules remain unchanged. |
| Separate Oracle round | Not required | These defaults are sufficient for stage-19 implementation; validate actual `artifacts` columns before writing the stage file. If they differ, stop implementation rather than add a table/column. |

## P4 stage 20

| Area | Status | R3c machine ruling |
|---|---|---|
| Triage context | Not frozen | Use one `decision.context` JSON object with exactly 11 keys: `task_content_hash`, `task_est_tokens`, `user_intent_override`, `has_mutating_hint`, `policy_version`, `explore_evidence_hash`, `ancestor_depth`, `n_nonterminal_children`, `remaining_turns`, `quota_remaining`, `subtree_reserved`. Tree-dependent fields are JSON null when unavailable; null never means zero. |
| 10a sources | Default | `task_content_hash` = latest user payload SHA-256; `task_est_tokens` = deterministic payload byte estimate using active assemble divisor; `policy_version` = session route-policy version; `has_mutating_hint` = conservative match against enabled tools whose allowlist says `mutating=true`; missing evidence hash is null. |
| 10b sources | Narrowed default | `ancestor_depth` and `n_nonterminal_children` come from `v_goal_tree`; `subtree_reserved` is the active descendant count used by H1; `remaining_turns` and `quota_remaining` are null because no live lifetime-turn/quota projection exists. Any rule requiring either null field must fail closed to `human`. |
| Override event | Frozen shape | `goal/override` payload exactly `{schema_version:1,intent:'direct'|'decompose',source_principal:'user'|'operator',reason?:ASCII text}`. Unknown keys reject; model-originated writes reject. Same type uses the highest sequence. |
| Jev output | Frozen vocabulary | Existing `decisions` row with signal `triage`, kind `choice`, answer exactly `{choice:'direct'|'decompose'|'human',confidence:number}`. No rubric fields and no new decision kind. |
| Thresholds | Not frozen | Keep `thresholds.action` limited to existing `pass|reject`; `direct`, `decompose`, and `human` are decision values, never threshold actions. Triage bands remain half-open and policy-version frozen. |
| Fold cap | Not frozen | Seed `harness.repair_count` and `harness.replan_count` bands `[0,3)`→`pass`, `[3,Infinity)`→`reject`. Counts are current-user-turn signal-event counts. At reject, no new repair/replan work is spawned; route to human or reject according to the existing closed action. |
| Explore | Frozen direction, request shape default | Same-session `effects.kind='llm'`; request contains exactly the existing `route` plus `{explore:{mode:'read_only',tools_revision,tools:[enabled names]}}`. Tool list includes only entries whose allowlist has `write_targets=[]`; explore never calls `spawn_subsession` and never creates a child. |
| Explore evidence | Default | `explore_evidence_hash` is the lowercase SHA-256 of the succeeded explore artifact/result; absent artifact means null. Changed evidence produces a new decision request hash. |
| Action ladder | Frozen | Apply R2 priority 1–7 exactly; hard depth/budget gates precede override, override never bypasses safety, root without Jev evidence cannot silently become SQL-direct, and child-depth default direct remains valid only when all non-null safety inputs pass. |
| Separate Oracle round | Required before P4 only for quota semantics | P4 may implement null-safe fail-closed behavior now, but a full non-null `remaining_turns`/`quota_remaining` contract requires a separate decision before enabling quota-based decompose behavior. |

# 5. File-by-file impact

## Stage-18 files

### `v13/spawn/v13_spawn.sql`

Add, in one transaction:

- `spawn_budget` policy row.
- `tool_control_allowlist` policy row.
- Parent child-event and batch-idempotency indexes.
- `v13_fork_one` private helper.
- `v13_spawn_subsession`.
- `v13_open_session` and the dedicated control-owner setup required by R3 D4.
- `sessions` insert guard, after all stage-16 data/fixtures have loaded.
- `v13_goal_tree`.
- `v13_recover_idle`.
- `v13_tools_guard` replacement with the named VOLATILE exception.
- `v13_fork` replacement preserving its public signature and existing non-spawn behavior.
- `v13_closeout` replacement enabling direct-child receipts.
- `v13_route`/`v13_advance` replacements for `effects.result.tool_calls` spawn dispatch.
- ACL revocations/grants for all new or replaced functions.

Dependencies: create policy rows and private helper before inserting the spawn tool; install the sessions insert guard only after prior-stage seed data is loaded; replace closeout before tests exercise parent termination.

### `v13/spawn/setup_db.py`

Create the stage-18 database and load through `STAGE_THROUGH['spawn']`, following the existing setup pattern. Ensure test-role connections exercise the current-user insert guard rather than superuser bypass.

### `v13/spawn/test_spawn.py`

Cover H1–H7, including:

- root lock concurrency and no oversubscription;
- exact request/response key rejection;
- all-or-zero batch behavior;
- same source tool-call replay and mismatched replay rejection;
- direct `sessions` insert rejection;
- `v13_open_session` root shape;
- child tree cycle rejection;
- child terminal recovery marker idempotence;
- repair/replan readiness;
- parent closeout child receipt;
- named SQL VOLATILE exception and all other VOLATILE rejection;
- stage-18 regression for stage 17 no-child closeout.

### `v13/spawn/README.md`

Record the H1 narrowing explicitly: active descendant slots are not lifetime turn reservations. Document lock class `13018`, external `recover_idle` invocation, and the absence of a session-level pgmq wake message.

### `v13/load.py`

Append only:

- `spawn/v13_spawn.sql` to `SQL_LOAD_ORDER`;
- `STAGE_THROUGH['spawn']=18`.

Do not modify stage-1–16 load entries.

## Existing files intentionally not modified

- `v13/schema/v13_core.sql`
- `v13/loop/advance.sql`
- `v13/periphery/v13_periphery.sql`
- `v13/twophase/v13_twophase.sql`
- stage-1–16 tests and fixtures

Stage 18 uses `CREATE OR REPLACE` in its new tail file; it does not rewrite the historical source files.

# 6. Risks and migration

- **Direct session creation becomes breaking at stage 18.** All stage-18-and-later fixtures and callers must use `v13_open_session`; stage-1–16 files remain unchanged and are tested only through their earlier load prefixes.
- **Closeout receipts gain child items only for sessions with children.** No-child receipts remain schema-version 1 and retain `children=[]`; consumers must accept the new three-key child entries.
- **Existing sessions require no data migration.** Existing root rows have null parent/fork fields and remain valid. New indexes are additive. Existing sessions are not backfilled with child or budget events.
- **Policy misconfiguration fails closed.** Missing `spawn_budget` or `tool_control_allowlist` prevents spawn rather than allowing unbounded creation.
- **The H1 narrowing is a semantic limitation.** P2 does not promise that a child has a fixed number of future turns. Enabling that promise requires a later quota/reservation decision and must not be inferred from `turn_no`.

# 7. Implementation order

1. Add stage-18 transaction wrapper and load-order entry; verify stage 1–16 prefix loading remains unchanged.
2. Install the dedicated control owner, policy rows, and policy-shape checks.
3. Add child receipt/idempotency indexes and `v13_goal_tree`.
4. Add the shared fork helper; replace `v13_fork` without changing its signature or existing direct-fork semantics.
5. Add `v13_spawn_subsession`, including request validation, root lock, active-slot arithmetic, idempotency, batch rollback, and parent receipts.
6. Add `v13_open_session`, ownership changes, and the current-user sessions insert trigger.
7. Replace `v13_tools_guard`; insert the `spawn_subsession` catalog row only after the handler and policy are valid.
8. Replace closeout to emit direct-child receipt objects while preserving the P1 no-child receipt.
9. Replace route/advance to consume validated `effects.result.tool_calls` through the existing SQL fast path; keep the action vocabulary unchanged.
10. Add `v13_recover_idle` and its child-terminal marker logic.
11. Add stage-18 tests for H1–H7 and run stage 1–17 regression.
12. Run the complete stage-18 gate. **P2 is GO only when all tests pass, direct writes are rejected, and no child-bearing closeout can produce a partial receipt.**