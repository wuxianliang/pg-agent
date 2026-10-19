# v13 控制面偏差台账（2026-09-26）

编号从 P1 起。后裁优先于计划正文。实现差与「计划 vs R3*」冲突分列；冲突不是实现许可。

## 实现差

本期相对 R3 §1–§2、R3a §6、R3b §7 无未授权实现差。下列是安装期探针按已写死默认走完的事实，不是第三种写法。

| # | 事实 | 处置 |
|---|---|---|
| F1 | `artifacts.content_hash` 与 `produced_by` 均存在 | `produced_hashes` 走连接查询；不编译 manifest 链（活体 `sessions` 无 `context_active_artifact` 列，列缺失分支不会被装上） |
| F2 | `jsonb_matches_schema(schema json, instance jsonb)` 真名相符 | 用该签名；schema 参数 `::json` |
| F3 | R1/设计/ch07 无三注解键字面类型 | 用 R3b 默认：`harness_session_ref` 1..256 `[A-Za-z0-9_./:-]+`，`resume_token` 1..512，`partial` boolean |
| F4 | `v13/load.py` 不包外层事务 | stage 17 文件自带 `BEGIN`/`COMMIT` |
| F5 | 活体 `v13_requeue_stale` 含 `mgraph_consolidate` | 换体以 mgraph 加载态为底，不用 twophase 旧体 |
| F6 | 活体 advance ⑤ 不写 `turn_no` | closeout 禁止 `turn_no` 赋值，只把已提交值抄进 `spent` |
| F7 | `v13_effect_id` 含 `v13_cycle_no` | retry 在追加新 `turn/route` 之前 enqueue，身份才能重挂同一行；`turn/route` 在身份计算之后追加。落实 R3b「走现有重挂」，不是改裁 |
| F8 | stage 16 `v13_mgraph_assembly.sql` 已 `GRANT SELECT ON effects TO v13_recall` | stage 17 `REVOKE SELECT ON effects FROM v13_recall`，满足「recall 可读 `human/responded`、不能 `SELECT effects`」。不改 stage 16 文件字节 |

## 计划文档 vs R3*（后裁优先）

| # | 冲突 | 采用 |
|---|---|---|
| C1 | 计划 §3.2.8 / R3 §1：已有未消费 `cancel/requested` → replay 不二插 | R3b：不追加，但仍扫 ready→cancelled；终态才 `replay`，非终态返回 `accepted` |
| C2 | 计划 §3.2.9 / R3 §1：审批 human request 四键，含可选 `prompt` / `interaction_kind` | R3b：恰 `{schema_version:1, interaction_ref}` |
| C3 | 计划 §3.2.11 / R3 §1 C4：「request 无 ref 也拒」 | R3b 应用谓词：仅 `kind=human` 且 succeeded 且 request 含 `interaction_ref` 才跑 one-of。无 ref 的 `{reason}` human 照旧 succeeded，不写 `human/responded` |
| C4 | R3a：`v13_wake_is_satisfied_v1` 标 STABLE | R3b：必须 VOLATILE（`clock_timestamp`） |

## 受制裁例外

| # | 条目 | 理由 |
|---|---|---|
| X1 | `v13/mgraph_assembly/test_mgraph_assembly.py` 的 J3：`len(SQL_LOAD_ORDER) == 16` 改为 `>= 16`，文案改为 “at least 16 files”。仅此一行。`SQL_LOAD_ORDER[:15]` 字节冻结切片不动 | 控制器 2026-09-26 裁决。该断言是注册完整性快照，字面钉死 16 与「新 stage 只追加注册」冲突。`>= 16` 保底语义不变，前缀加载语义零改动。本轮唯一被允许触碰的 stage 1–16 文件 |

## P2 实现差

本期相对 R3 §1 附、§3、§8（含 §8.8）无未授权实现差。下列是安装期事实，不是第三种写法。

| # | 事实 | 处置 |
|---|---|---|
| F9 | 属主角色名未冻结 | 自定 `v13_spawn_owner`（NOLOGIN NOSUPERUSER）。R3c 全文允许实施自定名字 |
| F10 | `repair`/`replan` 的 nudge fingerprint 用 seq 数组文本，不哈希；`children_terminal` 用 sha256 | 按 §8.4 字面，不把 grokBuild「三指纹都哈希」写进来 |
| F11 | 计划 §4.2 仍写 max_turns / reserved 聚合 | 后裁优先：准入按 §8.1 席位三键，不加 `sessions.reserved` |

## P2 计划文档 vs R3*

| # | 冲突 | 采用 |
|---|---|---|
| C5 | 计划 §4.2：准入 = 非终态子孙 max_turns 之和 + requested ≤ 剩余 | §8.1：占用 + requested ≤ max_nonterminal，另加 depth / fanout |
| C6 | §8.2 单数 tool_call_id、tasks_hash、一条 child-created | §8.8：逐子回执、task 走 args.task、返回闭集无 tasks_hash |

## P3 实现差

本期相对 R3c §8.7 / 全文 F 无未授权实现差。下列是安装期事实与已写明收窄，不是第三种写法。

| # | 事实 | 处置 |
|---|---|---|
| F12 | `artifacts.kind` 无 CHECK | 直接用 `worktree_binding`。不 ALTER，不做 latch-only 降级 |
| F13 | latches INSERT-once，不能把 `state` 从 prepared 改成 released | 值闭集仍接受两态；生产路径只在 prepare 的下一格 advance 写 `prepared`。不 UPDATE |
| F14 | 未消费 cancel 缺失时 `complete(cancelled)` 的 RAISE 文案未冻结 | 用 `v13: cancel not pending`。零写。不是新出口 |
| F15 | codex review 把「tool+required 调 cancelled → RAISE 零写」读成未抬墙 | 拒绝。已裁就是该 RAISE；抬墙只走 `complete(unknown)`。不改裁 |

## P3 计划 / ch08 vs R3c（后裁优先）

| # | 冲突 | 采用 |
|---|---|---|
| C7 | 计划 §5.2 / ch08：`allowlist.interruptible` 键 | R3c：`v13_interruptible` 字面量，禁列 / param_spec / 策略行 |
| C8 | ch12：加锁与写入同一全序；「无跨会话锁序」 | R3c F：锁序全部 `session_id` 升序锁完再写；应用序 depth 升、同层 id 升。这是锁细化，不是改扇出语义 |
| C9 | 计划 §5.3「无 binding 拒 claim」可读成 RAISE | R3c：claim 跳过 `requires_worktree` 且无 latch 的行，返回空，不 RAISE |

## P4 实现差

本期相对 R3 §8.7 无未授权实现差。下列是安装期事实与已写明收窄，不是第三种写法。

| # | 事实 | 处置 |
|---|---|---|
| F16 | 审查意见把「无带」读成「信号零行不算超限」 | 拒绝。§8.7 是无带或命中 reject → human。默认 v1 无 cap 带，有 repair/replan 事件即入队 `{reason}` human。不改 v1 带 |
| F17 | 空 fold 若无 user 锚，closeout 因 `origin_user_seq` 不能封账 | 空 fold = 没有非空白 `user/message` 文本。测试用空白文本，closeout `triage_reject`。不改 closeout 逃生名单 |
| F18 | 活体 `v13_needed_judgments` 的 `v13_is_spawn_tool(name, kind)` 在换体重编译时 `kind` 与 OUT 参数歧义 | 只在 stage 20 换体里改成 `tools.kind`。不改 stage 18 文件 |

## P4 计划 / ch04 / R2 vs R3 §8.7（后裁优先）

| # | 冲突 | 采用 |
|---|---|---|
| C10 | 计划 §6.3：`thresholds.action` 仍六值 | §8.7：列保持 `pass|reject`。六值是路由出口。gate 断言 CHECK，不 ALTER |
| C11 | R2 §3.2 `min_child_max_turns` / `max_spawn_depth` | H1 席位：`remaining_turns < 1` 禁 decompose；深度只读 `spawn_budget.max_depth`。不加列、不加 v1 带 |
| C12 | ch04 / R2 §3.4 再次 review 种子含子 direct | 已探索的 review 格走 human（R2 §3.3 + §8.7 一次 explore）。子会话无 override 仍是规则 6 direct，不进该格 |
| C13 | ch01：证据本体是 artifact，`explore/completed` 可选 | §8.7：事件是标记。本期不新增 artifact kind |
| C14 | R2 §1.3 带满 → human 或 reject | §8.7：human request，不 session reject，不写 `interaction_kind` |

## P5 热修（E2E 遗留授权缝；2026-09-26）

超级用户 gate 看不见 42501：stage 18/20 换体让 resolve/recall 通道（`v13_parse`/`v13_judgment_envelope` → `v13_needed_judgments`）与 route 通道（advance → `v13_triage_project`）调到新 helper，但 GRANT 停在旧调用者上。demo E2E 用超户直调绕开（e2e_report §问题与绕法）。

| # | 事实 | 处置 |
|---|---|---|
| F19 | 授权闭包缺口（探针实跑确认）：`v13_is_spawn_tool` 只授 route（resolve/recall 42501）；`v13_spawn_occupancy` 无任何角色持有（route 的 triage_project 也被拖死）；`v13_triage_project`/`v13_json_keys` 缺 resolve/recall；`v13_triage_owner` 跑 emit 提交期双射触发器缺 `v13_assert_unknown_wall` EXECUTE 与 `effects` SELECT（此前仅 demo 夹具运行时补授）。`v13_policy` recall 已有（envelope:963-996），不动 stage 1 | 只补 GRANT 不改函数体：spawn 文件追授 `v13_is_spawn_tool`+`v13_spawn_occupancy` → 三角色；triage 文件追授 `v13_triage_project`+`v13_json_keys` → resolve/recall；owner 自举两条搬进 triage SQL。gate：test_triage.py 新增 F19 角色通道组（矩阵×三角色+PUBLIC 负例+resolve_login/route_login 直连行为烟+recall SET ROLE 烟+recall 仍拒 SELECT effects+emit 提交期双射路径）。不授任何写函数 |
| F20 | stage 18 死体 `v13_needed_judgments` 仍写歧义谓词（F18 在案） | 本热修不动函数体，维持 F18。死体只在前缀加载可见 |
| F22 | parse 侧潜在缝：活体 `v13_tools_catalog_frozen`（resolve 定义，未被 stage 18+ 换体）仍拒 VOLATILE sql 工具，无 H7 具名例外——spawn_subsession 目录行 enabled=true 时 `v13_parse` 会被拒 | 关闭。stage 22 换体后具名写者对 parse 可见。绑定式按 R9/F26：裸名同域 B′，非 v_qual 代入 |

（F21 预留未用：探针实测 route_login 可直接做 freshen 的 UPDATE sessions，demo 包装走 v13_route_login 属主，无需 postgres 属主捷径。）

## P5 判定（非实现差）：「无信号 progress 无自然停点」= 伪缺口（2026-09-26）

e2e_report §后续④称「无信号 progress 的落回旧 route 没有非封印的自然停点，若产品要多轮 harness 而不调 llm 需要新停点」。核对活体与 R3 链后判**伪缺口**，不改 SQL：

1. 停点已存在且已实现：活体 advance（v13_triage.sql 约 706–711）对未满足 evidence/quota wait 置 `waiting` 并返 `waiting`——零写入、不落 route、不 closeout；approval 同理（约 716–743，入队 human 后停）。
2. 规格明文：R3 §6.2 判定深度——未满足零写入置 waiting，活性靠驱动重调（P2 recover_idle 合同）。
3. 「多轮 harness 不调 llm」是规格内正规形态：wake 满足/审批应答后同函数沿用同一 logical_turn_id、index+1 续传（约 762–791），不轻 llm。
4. max_cycles 逃逸封印（budget_exhausted closeout）是 R3c §8.1 定义的故意出口，不是漏停点。
5. 无信号 progress 无限循环结构上不存在：同 logical_turn_id 第二个不同 source 的 material 收据 RAISE `v13: material ledger`（约 678–693）；每个新逻辑回合计一次 material。
6. waiting 是一等可恢复态：recover_idle（v13_triage.sql:1181 起）的候选/three-reason 谓词不会命中纯 wake-pending 会话（无活跃 effect 且无 children/repair/replan 事件 → 零 nudge），隐式排除与 R3c §8.4 一致。

唯一未被规格覆盖的是「harness 无 wake、无 human 的无条件让出」——现成近似是 `{kind:'event', event_type:'<永不出现的 type>'}`（§6.2 变体一，开放词表精确匹配）。若产品坚持语义化让出，属 R3 修订（新 wake 变体或新返回词，均碰已裁闭集），另开裁决，不随热修。

## Phase A

| # | 事实 | 处置 |
|---|---|---|
| F23 | D13（= parity F4 / R3 C4，与 parity F23 无关）。RP-CE 对未知/已答 interaction id 静默 no-op；v13 按 R3 C4 fail-loud，ref 不等 RAISE 含 submitted=/current= 零写 | R5 裁：不移植。关闭 parity §4 #2 |
| F24 | D11 无事件窗口（R6，≠ parity F24）。条件 4 只认自身事件 `source_effect_id=effect_id` 且 `seq>` 匹配类 anchor；ready/claimed 无自身事件行永不盖章。窗口内 closeout 形状 (C) 仍 RAISE `continuation owed`。重泵实测 **(b) 返回 `waiting`、零新 effect/零新 event/session 仍 waiting**。worker claim 不经 tail_gap 照常推进；行落合格自身事件后自愈 | 接受残留。不改 R3a §7.1、不补指向键、不改 closeout、不搬 PERFORM。(b) 不加幂等守卫、不重排 advance |
| F25 | D12 锁协议（R7，≠ parity F25）。PG tuple lock 无同事务重入豁免：持有者再次 FOR UPDATE 排到等待者之后，与写者已持的 latch 行锁成环（40P01）。守卫改无锁 MVCC 校验；写者保持 latch FOR UPDATE + 两条独立语句。残留仅「无锁旁路直插在写者窗口内先提交→写者 23505 整笔回滚」，生产两调用点同经行锁彼此不可达 | 接受残留。不加咨询锁、不开 R3c 类号、不捕获 23505、不加暂停点。R7b：日程改生产序取锁（sessions→latch），观察点移至 sessions 行等待；pg_locks 断言为 B 对 A xid 的 transactionid ShareLock；禁只锁 latch（FK 倒置成环 40P01）。本日程不动态验证两条语句规则 |
| D12 | 成功 release 后 latch 行仍 `prepared` 是 R5 预期；`released` 不被 claim 消费。投影由 `v13_worktree_state` 折叠 `worktree/released` 事件 | 预期行为，不是实现差 |
| F22 | catalog 缝（D14）。换体前 `v13_parse` 在 catalog 被 `is VOLATILE` 拒绝 | 关闭。stage 22 后具名写者对 parse 可见。指针：绑定式按 R9/F26，裸名同域 B′，非 v_qual 代入 |
| F26 | D14 断言 B 复裁（R9，≠ parity F26）。活体 writer_ok 是裸名解析，限定 `v_qual` 代入为 false，触发停工后落地裸名同域 B′。R10：同域二选一，活体形态 H（三函数 proconfig NULL），换体保持 NULL；投毒预期改为解析层先拦。R11：全库 proname 计数是更早防墙，S 锁死为 `ambiguous across schemas (2)`；夹具 3 双臂。R12：臂 D 改真行 RAISE 且点名 spawn_subsession（writer_ok 体内裸调 named，限定直调真实 writer_ok 在否决型影子下为 false，接受的 fail-closed，不修谓词）；P8a′ 证明分工是源码/OID 硬断言 + 臂 E；前置不成立停工，禁降级记通过。残留 R-1：同名第二函数到不了深检；无第二份工具函数时影子谓词由 schema 限定调用挡住 | 接受残留。不改 writer_ok，不加 SET，不改既有解析 |

## Phase B

| # | 事实 | 处置 |
|---|---|---|
| F27 | actor 通道与信任边界（R8-① overload，≠ parity F27）。2 参 `v13_cancel` / 6 参 `v13_complete` 是唯一正文，旧签名纯委托 `actor=NULL`。DB 只验带与亲缘，不证 actor 的网络来源；来源由服务端绑定 | 接受。不读工具 JSON、human result、事件 payload、会话参数。不建 link 表、不加列 |
| F28 | 生产绑定两格（≠ parity F28）。谓词+换体+`test_acl.py` 绿 = 合同已证明；仓库内驱动器在 agent 路径传 actor = 未交付（`demo_v13/` gitignored） | 不得写成「F17 已在生产路径生效」。driver 补丁不进本里程碑 |
| F29 | 读面拒绝=零行不 RAISE（≠ parity F29）。`v13_observe` / `v13_session_log` 授权失败零行，不把「不存在」与「无亲缘」分成两种异常。参数合同错误（重复、NULL 元素、游标 `< -1`）仍 RAISE，且发生在授权前。旧动词 cancel/complete 仍 RAISE，operator 空 actor 缺目标保留活体 needle（C15） | 接受。不把读面改成 RAISE，不把旧动词改成零行 |
| F30 | 前缀窗口非源尾窗（≠ parity F30）。信封四键无 `from_seq`，hash 材料必须是 `seq <= up_to_seq` 的整段前缀。与源合同「最近 N 条」不同，是四键约束下的换体。不产 XML，不截断，不设 `max_events` | 接受。改窗口形状须另裁并升 transcript 版本 v1→v2。不建摘要表 |
| F31 | 收据排除出 transcript 材料（防自激）+ route→emit 直调=受信内部 helper（≠ parity F31）。`type <> 'control/handoff'` 才入 hash。`v13_handoff_emit` / `v13_transcript_hash` 不是 actor 入口；D7 只承诺 `v13_extract_handoff`。直调行为已定义：新身份落收据；同身份撞 `ux_events_handoff_snapshot` 裸 23505；`enabled=false` → `v13: handoff disabled` | 接受。不授 PUBLIC/worker/recall/resolve/spawn_owner。不把直调收成授权错误，也不用 EXCEPTION 吞 23505 |

| # | 冲突 | 采用 |
|---|---|---|
| C15 | D7「可控任意非终态会话」若读进谓词，会把 R3 已冻终态 cancel `replay` 改成 `session not found`。parity F17 字面「失败一律 session not found」与 operator 空 actor 缺目标时的活体 needle 冲突 | 状态中立：谓词不读 status，终态 `replay` 保持。③ 例外：operator 且 actor 空且目标无行保留活体 `v13: unknown session %`（cancel）/`v13: unknown effect %`（complete）；agent 路径与非 operator 空 actor 一律 `v13: session not found` |
| C16 | R4:23「生命周期写面 = 开放事件 + 唯一折叠函数」与路线图 §2.4「交接无读面函数，收据即事件」的张力。交接不是可翻转当前态（对比 stop/resume，折叠函数留在 stage 29 `v13_goal_lifecycle`） | 非生命周期收据澄清。唯一承诺函数 = `v13_transcript_hash`。advance 不调用。不新增 `v13_latest_handoff` / `v13_handoff_state` / 全局 VIEW。路线图 §2.4 维持「收据即事件」 |
| C17 | R13c-A/B：r41 §3.4 `current_setting` 绝对禁词误伤活体预存 `statement_timeout` 守卫臂（advance 恰 1 处，query_canceled 臂）；r41 小题⑥审计豁免正臂在 stage 26 不可达（前缀三门早退先于预检点，duty_cycle 门与预检互斥） | A=差集断言（次数 1+调用文本+臂子串；prework 0；余六词绝对零）；B=双臂分阶段（负臂+源码三合取项/append 位置在 26，正臂行为入 stage 27 done-when，#43 源码在场≠通过）；施工形不动。r42 |

## Phase C

| # | 事实 | 处置 |
|---|---|---|
| PC-1 | 三读点而非单点早退（R13 D10-A）。`v13_should_run` 插在 P-spawn / P-harness 两臂 / P-tail，不在会话锁后一次返回。前缀结算（cancel closeout、unknown 墙、在途 ready/claimed、material、finish/reject、wake）不进门 | 接受。不重排 advance 前缀。假路径 `'waiting'`，读点之后零新 effect |
| PC-2 | duty 默认 shadow（R13 D10-B）。种子 `duty_cycle.effect=shadow`，duty=0 仍先 spawn，再由 prework 写 `triage/hold`。改 block 是新策略版本，不改函数、不搬 hold 写入者 | 接受。不把 `duty_cycle=0` 当成 L32 |
| C18 | R13c-C：r42 小题⑧要求安装 `trg_sessions_parent_immutable` 并见 `v13: parent immutable`，但 stage 18 既有 `trg_sessions_fork_cols_immutable`/`v13_spawn_cols_guard` 已覆 parent_session_id 列（同级 BEFORE 按名序 `fork` 先火，新文案不可达） | 不装新守卫。parent 不可变由既有实例执法：stage 26 行为验收（route/spawn_owner 改 parent → 既有格式串 RAISE 零写 + NULL→非 NULL 臂按可构造性）+ 结构验收（OF 三列/函数/新名不存在）+ 源码（无新触发器无新文案）；stage 1–25 零改动；锁序重裁不触发。r43 |
| PC-3 | 松配额种子不是产品额度（R13 D9）。活动 `quota_window` 为 `window_hours=8760`、`slot_minutes=0`、`allowed=1000000`。上线默认不因配额停跑 | 接受。收紧 = 新版本并翻转 active，不改函数。禁止写成「已配置 24 小时 8 次」 |
| PC-4 | 计次不沿树（R13 D9）。`v13_quota_eligible` 只计本会话 `turn/material_spent`。子会话收据不改变父会话布尔。树上席位仍只由 `spawn_budget` 管 | 接受。不与席位预算混成第二套树计次 |
| PC-5 | hint 不是 ack，本 stage 不注册 cron（R13 L21）。`v13_scheduler_hint` 可重复调用，不写事件、不推进 `next_seq`、不插入 `cron.job`。`run_now` 不是入队许可 | 接受。仓库外 driver 若存在，必须读 hint 且仅 `run_now` 才 `v13_advance`；advance 体内再判一次。禁止写成「pg_cron 已在生产调度」 |
| PC-6 | 秩是注意力不是调度（R13 L5）。`attention_rank` 只作输出列，human 阻塞先于可跑，终态沉底。hint 不是这个秩的第一名。返回行数预算不限制 `v_goal_tree` 源遍历 | 接受。不把秩接到 advance，不建成 VIEW 或投影表。传 1 仍扫全树；前移有界遍历须另裁 |
| PC-7 | fingerprint 不改 `v13_state_hash`（R13 D15-A）。`v13_goal_fingerprint` 是新函数，八词无条件排除；`v13_state_hash` 继续计入五类独有排除。换体 state_hash 替代案已否决 | 接受。stop 必须改变 `v13_state_hash`。不把 `goal/*` 塞进 state_hash 排除名单做绿。`v13_transcript_hash` 仍只排除 `control/handoff` |
| PC-8 | L29 留置 tool/call，直调仍 RAISE（R13 L29、小题⑨）。无并发复活且非 explore 时，到顶 advance 不 RAISE；explore 误用仍 `v13: explore spawn`。终态兄弟被 `user/message` 复活的窗口不承诺零 RAISE，也不承诺绝对不超售 | 接受。不删 `v13_spawn_subsession` 的 cap RAISE，不把该 RAISE 接住当成 skip。复活窗口记 `test_revive_race_backstop`，不标「不超售」已闭合 |

## Stage 40

| # | 事实 | 处置 |
|---|---|---|
| S40-1 | stage 40 只交付 `agentctl_observe` 这一个 STABLE INVOKER 只读工具。不建 `controller` 政策，不登记写动词，不改 stage 1–39 函数 | 接受。路由证明用测试库 `agentctl_observe_probe` version 1，随库消失 |
| S40-D2 | parity §6 R6（`docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md:236`）写 `spawn_subsession` 保持 `enabled=false`。活体 `v13/spawn/v13_spawn.sql:1760` 为 true。这不是已关闭的 F22：F22 是 catalog VOLATILE/parse | 勘误追加，不改 R6 原句，不改 F22 原行。本 stage 保持 true，不把「翻成 true」记作交付。R11 不进这次勘误 |

## Stage 41

| # | 事实 | 处置 |
|---|---|---|
| S41-1 | stage 41 交付三个 DEFINER 写动词、冻结 `controller` / 1、`controller_surface` / 1。`v13_named_sql_writer` 与 `v13_spawn_writer_ok` 只在新 SQL 文件里替换。`v13/spawn/v13_spawn.sql` 字节未改 | 接受。本次提交不是「D-3 已闭合」，也不是「S2 全链 gate 已满足 D-3」 |
| S41-2 | 2026-10-03 双车道复访，父签认关闭。本次扩 `v13_named_sql_writer` 不重开 spawn 档 | 接受。不改 F22 |
| S41-D3 | `steer/injected.payload.text` 未被消费。`CONSUMER` 未设置。九个非消费者是 `v13/control/test_control.py:516-524`、`demo_v13/parity/g_steer.py:98`、`v13/plan_contract/test_plan_contract.py:459-460`、`v13/resolve` canonical state、`v13/envelope/v13_envelope.sql:519,551`、`v13/memory/v13_memory.sql:113-127`、`v13/triage/v13_triage.sql:161-164`、`v13/observe/v13_observe.sql:130-171` 的 `v13_session_log`、`v13_triage_steer` 名字碰撞。读回事件行、审计三联、watermark/stale、`actl_chain_full` 都不是消费 | 未关闭。不发明消费者。不改 memory、triage、envelope 或水位谓词。L4 仍要求加入 `steer/injected` 字面前先 `ASK_USER`。不写「已取代 R11」 |

## Stage 42

| # | 事实 | 处置 |
|---|---|---|
| S42-1 | stage 42 只新增 STABLE INVOKER 函数 `v13_macro_suggestion`。场景是 Fake 四次 advance，词序列 `waiting`、`progressed`、`waiting`、`waiting`。`controller` / 1 只消费不重定义。`driver.py` 哨兵外字节未改 | 接受。不是无人值守，不是真实 provider，不交付 stage 43–45，不闭合 D-3 |
| S42-2 | `suggested_should_run` 丢弃。`admitted` 由 `v13_should_run AND v13_quota_eligible` 重算。缺会话不调用两个谓词。函数零写 | 接受。形状与 missing 是三键 jsonb，不 RAISE |
| S42-3 | human pending 的停止不是任务解决。stage 45 不交付。`read_file_py` 是 subject 读取，不是控制文件，也不是 file sink | 接受。不 skip、不 complete、不 cancel 那条 human effect |
| S42-4 | 计划 §3.8 写保留 `"agentctl_verbs": 42` 不连续负例。活体尾已经是 `goal_workflow: 42`，该替换先撞上 `duplicate stage number`（编号唯一先于连续编号）。合成替换改为 44，needle 仍是 `stage number is not the next contiguous value` | 接受。不改 `r1_load_append_ok` 检查顺序，不放宽 `r0_source_scope` |

## Stage 43

| # | 事实 | 处置 |
|---|---|---|
| S43-1 | 只新增 STABLE INVOKER 分类函数与 `external_executor` version 1。执行证明是一条 `agentctl_steer` 的既有 sql 臂。不是可信产品入口。 | 接受。不是注册身份，不是 task lease |
| S43-2 | 动词列表只来自当次 active value。函数体不写四个名字。shape 与 unsupported 是两键 jsonb、零写。两条 RAISE 文案按终裁。`policy_version` 只在成功返回值，且等于读到的行。 | 接受 |
| S43-3 | D-A.1 的政策版本不靠改信封实现。parse 快照仍是 `controller` / 1。无身份列，无控制文件。 | 接受 |
| S43-4 | 合成负例从 `external_exec`/43 前移到 `ce_map` / `v13_ce_map.sql` / 44。`"goal_workflow": 43` 会先撞 duplicate stage number，故改为 45，needle 仍是连续编号那句。不改 `r1_load_append_ok` 的检查顺序，不放宽 `r0_source_scope`。 | 接受。不改 `r1_load_append_ok` 的检查顺序，不放宽 `r0_source_scope` |

## Stage 44

| # | 事实 | 处置 |
|---|---|---|
| S44-1 | 生产新增只有零参 STABLE INVOKER SQL 函数 `v13_ce_map()`。无 `tools` 行，无政策行，无 `INSERT`。不是 CE 运行时 | 接受 |
| S44-2 | 返回值是 oracle 闭集。`shutdown` 是字符串 `unsupported`。返回值无 `v13_agentctl_answer`。两链不合并，session-link 无 `forcePoll` | 接受。`notes` 两值各含一个分号，`cmap_prosrc_one_select` 只放行这两处，其余分号仍失败。`worktree_merge`（含 routed `confirm_preview` 拒绝）不进 jsonb 新键 |
| S44-3 | `to_regprocedure` 与 `information_schema.columns` 分开。一参 cancel 存在但不映射。六参 complete 是格子。`lease_owner` 是 `text`，`lease_until` 是 `timestamp with time zone`。列不是 task lease，也不是 stage 42 的建会话路径 | 接受 |
| S44-4 | `load_stage(..., "external_exec")` 与 `files_through` 使 43 在库里，函数定义与返回值都不引用 `external_executor` 或 `v13_external_exec_classify`。装载前置不是功能消费 | 接受 |
| S44-5 | 合成负例从 `ce_map`/44 前移到 `not_scheduled` / `v13_not_scheduled.sql` / 45。哨兵不进 `approved`、允许集或 `SQL_LOAD_ORDER`。不创建 `workflow_project`。`"external_exec": 44` 与 `"agentctl_verbs": 44` 改为 45，因为否则先撞重复编号。`"goal_workflow": 45` 不动。不改 `r1_load_append_ok` 的检查顺序，不放宽 `r0_source_scope` | 接受。不改 `r1_load_append_ok` 的检查顺序，不放宽 `r0_source_scope` |

## Controller thin cut

| # | 事实 | 处置 |
|---|---|---|
| TC-1 | 六词纯函数，固定优先级；repair/replan 是内存事实。`blocked_unknown` 在序号前进且无 human 时落 `run_now`，不新增词 | 接受。不扫描 SQL。不引入 `capability_action_required` |
| TC-2 | 信封 → `v13_parse` → 一次 `v13_advance` → sql `agentctl_steer` | 接受。不是 FakeLLM tool_calls |
| TC-3 | observe 证明目标身份、序号前进、`last_event_type=steer/injected`；无 serve/complete | 接受。正文只由测试读 `events`。不闭合 S41-D3 |
| TC-4 | 精确两个新文件放行；loader 不变；无 stage 45；不声称 provider 或无人值守 | 接受。gate 只装载一次 stage 41；各场景以不同 mock model 名隔离全库 judgment_cache 的 UUID 回答，不改生产缓存或 SQL |

## Stage 40 (`ce_run`) 实施期偏差与裁决

**最新阻塞记录（2026-10-17，覆盖下方旧执行状态）：** 最终工作树复制并核对 SHA-256 后在隔离 workspace/PGDATA 顺序执行 47 清单，前 7 条 exit 0（CE 16/16 组、665），第 8 条 economy H1 期望 `accepted` 的断言 exit 1，剩余 39 条及 goal-supervisor 三模式未运行。原始 receipt 未打印；唯一一次有界诊断因观察器误查 `v13_claim(text)` 而失败，真实签名为 `v13_claim(text,integer)`，receipt 在异常前未写证据，不能编造观察值/根因。只读检查验证 PG 18.4/Stannum 0.4.0，未执行结算或额外 gate。精确环境等价性、冻结哈希、旧进程仅确认非运行而非退出码、诊断缺口及全部工件路径见 `prompt-exports/w4-economy-h1-handoff-20261017.md`。未降级共享环境、未修改冻结业务测试/SQL/授权/v20；无提交/推送，根因未明前不恢复 complete47，也未达到协调者集成 Oracle 审核边界。

本节记录计划 §7、§10.5、§10.6、§10.7 的 Stage 40 约束。2026-10-17 第 7 轮 `UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py` 实跑 exit 0，16/16 组、517 断言，wake 期望恢复为权威 `[1,1,1,2]`。此前采用错误 `[1,1,2,3]` 的第 5/6 轮及顺序回归 CE 行不计有效验收。完整 47 条在第 11 条 fair_driver exit 1 后停止，剩余 36 条未运行；W4/Stage 40 仍未完成。命令/退出码/检查数/原始失败输出见 `prompt-exports/w4-ce-run-actual-results-2026-10-17.md`。

| # | 事实/偏差 | 处置与证据边界 |
|---|---|---|
| S40-P1 | P1 退役旧 Stage 40–44 与 controller thin cut，共 22 文件；旧 #86–#91 不能作为新实现通过证明 | 接受。单一 Stage 40 `ce_run` 收口；矩阵旧行标记 `P1 退役`，不保留旧 gate 等价性 |
| S40-1 | `run_id=session_id` 是 headless 身份，不是 CE app/agent_manage 身份 | 接受。README 只声明 headless 范围，不宣称完整产品等价 |
| S40-2 | start 的 root/child 创建必须经唯一私有 `v13_ce_insert_session(uuid,uuid,bigint) RETURNS uuid` bridge；既有 sessions owner trigger 仍保留，超级用户直接 INSERT 也应被拒绝 | §10.5 裁决。helper 只做 INSERT/RETURNING；授权、父锁、cutoff 在外层 start。setup 要核验 helper owner/ACL、直调 42501、宿主不能 SET ROLE owner；第 7 轮 probe 4/10 已验证 |
| S40-3 | child cutoff 不是 spawn 样板的近似值，而是父锁内 `next_seq−1` 的包含上界；父 `next_seq=0` 必须零写 `parent_prefix_empty`；同 request replay 不重算 cutoff | §10.5 裁决。第 7 轮 probe 4 已验证真实双连接串行、cutoff 与异常整体回滚 |
| S40-4 | caller 不能取 SECURITY DEFINER 的 `current_user`；需识别真实 `SET ROLE` 身份，否则 session_user，并区分 route/operator、self/parent、recall 读面 | 接受。非超级用户宿主是产品角色测试前提；第 7 轮 probe 10 的四类非超级用户 LOGIN/SET ROLE 已验证 |
| S40-5 | wait 不是全局一次消费：固定八键返回携带 `wake_id`，每个 waiter 自携 `after_wake_id`；steering wake 优先 actionable snapshot，普通 snapshot 不能吞 steering | 接受并明确为 CE 与全局消费的偏差；第 7 轮 probe 6 已验证；self-origin 仍 interrupted，仅隐藏正文；reactivation wake 属旧 epoch |
| S40-6 | active steer 同 epoch queued follow-up；旧 ready/claimed effect 可以真实结算但 driving token 禁止旧 publication；terminal steer 才新 epoch | 接受。不能把所有 steer 记成换 epoch，也不能声称 provider 被中断；第 7 轮 probe 8 已验证 |
| S40-7 | cancel 是单 run 清槽并同步 sessions/CE；`session/cancelled` 与 `cancel/requested` 均保持严格事件格式，真实 actor/request 审计由独立 CE 审计事件持久化，防止 terminal steer 恢复 ready 后旧取消墙重现；不调用旧 `v13_cancel` 的递归子树语义，子 run 不受影响 | 接受为 CE/session 控制结算边界。它不终止事务外 claimed provider；迟到 receipt 按 tokens 结算/stale/unknown；第 7 轮 probe 7/13 已验证 |
| S40-8 | 正常 T2 必须原子提交 receipt、后继 admit/promotion、publish；禁止 accept 单独 COMMIT 留下 running 空队列 | §10.4 P1 处置。第 7 轮 probe 12/15 已验证真实锁屏障、全 T2 回滚及丢 COMMIT 响应存储重放 |
| S40-9 | 旧 LLM tool_calls 若未准入对应 operation，只做派生输入中的 `superseded` 普通历史投影；不伪造 tool result、不执行孤儿工具；已准入 operation 仍结算 | 接受。投影从既有 events/effects 来源连接，不裸读 CE operations；第 7 轮 probe 8/14 已验证 |
| S40-10 | `tools.param_spec` 是提问模板，不是参数 schema；本阶段 schema 仅私有固定 `spawn_subsession/{task}` 闭集，Fake adapter 返回 simulated 结果且不创建 session | §10.6 裁决。不能清空 params 绕过 validator，也不能开放所有 enabled tools；第 7 轮 probe 14 已验证 |
| S40-11 | worker 每轮独立短事务调用 `v13_ce_requeue_stale()` 包装，内部委托未修改的 `v13_requeue_stale()`，其作用域是全库；ce_wait 不触发回收；worker 停止无人重启不承诺自动回收 | 接受为部署/运行偏差。不能改写冻结函数或声称 scoped recovery；第 7 轮 probe 13 已验证另一 run 的过期 effect 也回收到 unknown |
| S40-12 | unknown 没有 CE 恢复入口；steer/respond/admit/promotion 继续被会话级 unknown wall 阻断 | 接受。临时库 DROP/rebuild 不是生产恢复证明；不能以夹具销毁绕过偏差 |
| S40-13 | 专用数据库必须收回宿主/继承角色的 TEMPORARY 与 public schema CREATE，避免 temp/public 同名对象遮蔽 SECURITY DEFINER 依赖；不泛化到其他 stage 库 | 接受为显式部署前提。schema owner 为受信超级用户且不与宿主共用；第 7 轮 probe 10/16 已验证真实 ACL 与精确生命周期 |
| S40-14 | 单 run 单 CE driver 是部署纪律，不是数据库结构强制；scoped claim 防重复但不提供生产多 worker 接管保证 | 接受。README 不写成高可用 worker/agent_manage 证明 |
| S40-15 | 保留 generation/continuity/related_follow_up/unrelated/expired/superseded 字段没有六动词 producer | 接受。reserved 夹具只能标 reserved，不计入覆盖矩阵的运行时能力 |
| S40-16 | Fake-only、无真实 provider/socket/网络；外部 IO 必须在事务外，连接在 T1/T2 间 IDLE | 接受。helper 已完整实现且 import-safe；第 7 轮 16 组通过，47 条回归受下述 S40-19 阻断 |
| S40-17 | 真实 route 直调冻结 `v13_requeue_stale()` 因 pgmq schema USAGE 失败；新增 `v13_ce_requeue_stale()` 受限 CE SECURITY DEFINER 宿主入口，route-only，返回 `{schema_version:1,ok:true,recovery:<原计数json>}`，仅委托原函数 | 接受 §10.7 接缝。独立短事务、全库作用域、不写 CE snapshot/revision/wake；不改旧 role/pgmq/base ACL，不新增控制动词；并入既定 `native_acl_roles`、`native_io_boundary`、`native_unknown_vs_archive`，第 7 轮已验证 |
| S40-18 | 冻结边界独立只读审计：23 条顶层语句逐条相等、39 个既有受保护函数体全等；`run()` 三个 `r0_*` 调用来自既有 `a2cabf1`；driver 剥离后全等、load 纯尾追加、phase_d 39 个 SQL 零失配 | 记录为源码冻结证据，不作为数据库 gate 通过；maintenance probe 第 7 轮通过，47 条回归/W4 仍阻塞 |
| S40-19 | 顺序回归第 11 条 `UV_FROZEN=1 uv run python v13/fair_driver/test_fair_driver.py` exit 1：`stage_bytes: (78432, 926)`；`test_stage_bytes` 定义于 219 行、断言 222 行、main 537 行调用，DB setup 前失败 | 原始三行输出与 7 个具体 diff 路径在实跑记录。检查要求 STAGE_PATHS 与 load.py 相对 HEAD 全空，撞上 P1 退役/冻结适配/文档脏树；不改冻结测试、不暂存/提交绕过。第 12–47 条全部未运行，协调者另行处理计划冲突；本轮停止回归 |
| S40-20 | W4 曾误把 reactivation wake 期望从 `[1,1,1,2]` 改为 `[1,1,2,3]` 并错误称符合计划 | 已恢复权威旧 epoch 期望；原始第 4/5/6 轮及顺序回归 CE 输出保留并标注错误解释/无效验收，不能据 exit 0 追认通过。SQL owner 修正 wake_epoch 与 sessions=ready 在 promotion 前的顺序后，第 7 轮正确期望实跑通过；不补算已停止的 47 条序列 |
| S40-21 | 外部 `/Users/wxl/Projects/PiSwift` 于 2026-10-17 12:54:56 被 `git pull` 自 bfccb32（2026-09-27，冻结 driver 合同基线）快进到 0f44e03：`createAgentSession` 变 `async throws`、`toolExecutionEnd` 四元组变五元组，v99 全新构建下冻结 driver 编译失败；主检出同晨全部绿证据均在 pull 之前且其构建缓存已被作废 | 经用户裁决回滚 PiSwift 至 bfccb32（detached，原分支指针保留 0f44e03）；随后 v99 序列 #30 pi_parity、#31 pi_ports 全绿。冻结 driver 适配 0f44e03 不并入本里程碑，留作独立后续变更；证据 `prompt-exports/w4-v99-attempt01-piswift-0f44e03/` |
| S40-22 | `~/.duckdb/extensions/v1.5.5/osx_arm64` 钉版扩展缓存（sitting_duck/duck_block_utils）从未落地，read_tools duck/ring 面按 skip 语义 exit 2；此前所有 read_tools 证据均未真跑 duck 面 | 实跑被批准的 `v13/read_tools/duck_bringup.py`：INSTALL FROM community、两个扩展 sha256 钉版校验通过、loaded=true；随后 #36 首次真跑 duck 面与 E4 嵌套全量全绿。证据 `prompt-exports/w4-v99-attempt02-duck-absent/` |
| S40-23 | economy H1 根因至今未建立；序列内红绿交替（红：§2.3 隔离序列、complete47 attempt-04；绿：prior、attempt-02/03、两次隔离复测、v99 三次序列） | 不改断言、不调环境、不追认历史红灯；v99 预提交三次序列内均绿，作为本里程碑通过证据；根因留作后续独立诊断（原单次有界复现授权已用尽） |
| S40-24 | 提交后净树复验首红（#30 pi_parity `historical_frozen`）：里程碑提交使 §10.8 body-only 适配过的 `v13/pi_ports/test_pi_ports.py`、`v13/read_tools/test_read_tools.py` 进入 committed_names 而被旧检查拒绝——设计缺口而非越界改动；首红前 #1–29 全绿 | §10.12 修正：`run_guard` 体内本地具名集合恰放行该两文件（字节由各自 pin 基线 4436cd8/30cdfd6 证明）；其余 frozen-prefix/`v8/` 已提交改动仍拒。修正后重跑、追加修复提交、同一 49 项清单净树复验后推送；证据 `prompt-exports/w4-v99-postcommit-20261017/` |
| S40-25 | 第二次净树复验 #36 read_tools 首红：E4 嵌套的 pi_parity（byte-stable）、pi_ports/workspace_admit/plan_arm（经 `r0_source_scope` 保护字节断言）连环红；根因为 piswift driver 对收尾 `agentSettled` 事件的采集竞态——捕获时 trace 15 行变脏（基线 14 行），postcommit2 顶层 #30 采到、嵌套跑未采到，跨进程字节不一致 | §10.13 修复：driver `agentSettled` 加 `finishSeq == nil` 守卫（恒 14 行 == 基线）；`r0_source_scope` 对 driver 具名豁免 + 精确字节证明（恰一处批准改动，其余偏差仍拒）；竞态残迹按基线恢复；单条实跑 pi_parity exit 0 且 trace 自愈回基线。追加修复提交、同清单净树复验后推送；证据 `prompt-exports/w4-v99-postcommit2-20261017/` |

### S40 dirty-tree freeze amendment

Guard compatibility is limited to explicitly named function bodies/path exclusions. `protected_dirty` is allowed only in the parity/ports/read-tools guard bodies so those guards can recognize the other amended guard files; it does not allow arbitrary dirty paths. The four pinned baselines and parent/file evidence are recorded in plan §10.8. Full 47-script and post-commit validation remain coordinator-owned.

Final legacy evidence is preserved in `prompt-exports/stage40-final-*.log`; CE gate validation is pending the independent runtime-review corrections and must be run once afterward.

## Stage 40 预提交全绿记录（2026-10-17，v99）

按用户指令在 `v99` 分支/worktree 续跑 FDFAED98 的 W4 收尾：主检出当前工作树 272 个冻结集文件逐文件 SHA-256 核对后 port 进 v99；依赖输入以真实拷贝落地；PGDATA 用被证明过的 pinned pgembed 785aa58（隔离 prefix、PG 18.4、Stannum 0.4.0）全新 initdb；node v24.13.1、go 1.24.5、swift 6.3.2 在场。顺序 runner（`prompt-exports/w4-v99-runner.py`）独立执行 47 条 + goal_supervisor 两探针，逐条恢复 pi_parity trace，首个无效即停。两次被保留的阻断尝试（S40-21 PiSwift 漂移、S40-22 duck 扩展缺席）处置后，最终序列 49 项全部有效：47 条 exit 0（CE 16/16 组、665 检查；read_tools 首次真跑 duck 面与 E4 嵌套全量；economy H1 序列内绿）、`--unattended-continuation` exit 1（ask_user 拒绝尾部）、`bad-args` exit 2（建库前 usage）。完整命令/退出码/耗时/日志/冻结清单：`prompt-exports/w4-v99-precommit-20261017/`。后续按计划 §8.1.6：消费集成静态 Oracle review → 提交前人工核对 plan_arm 受保护 diff → 按路径提交 → 同一 49 项清单净树复验 → push origin v99。

## Stage 41 (registry) 偏差台账

2026-10-18 P1 修复前历史预提交序列 `prompt-exports/w4-registry-precommit3-20261018/`：
48 脚本 exit 0，goal_supervisor 两额外探针 exit 1（ask_user 拒绝尾部）/2
（仅 usage），50 项全部符合预期，每条后 trace 精确恢复。registry 独立与 E4
嵌套均 16/16、473 checks；CE 665、plan_arm 104、fair_claim 137、goal_supervisor 74。
完整命令/路径/退出码见 registry README 与原始 results.json。
历史首次序列在第 16 项中断；第二次在第 17 项因 ignored runner 错误要求 FAIL
标记为最后一行而中断，实际 exit 1 且尾部 ask_user 正确。仅修 runner 的尾部识别后
从第 1 项重跑，不过滤或拼接序列。默认 parity 的 node_modules plane skip 如实记录，
不作 strict/all-plane 证明。集成静态 review 已完成，设计中单 revision 缓存残留
已修正；另发现 setup 字符串库名连接使用旧角色、与 TestDatabase 临时角色不一致的
P1；Oracle 追加裁决纳入本里程碑，已修复并补八项真实身份/精确错误探针，独立 registry 16/16、481 checks。修复后 precommit4-p1 从第 1 项完整重跑 50 项均符合预期（48×0 + 1/2），每项 trace 恢复，独立与 E4 registry 均 16/16、481；原始记录 prompt-exports/w4-registry-precommit4-p1-20261018/results.json。上一轮 50 项仅为修复前历史；未暂存/提交/净树复验/推送。
review 导出：`prompt-exports/oracle-review-2026-10-18-145510-untitled-chat-e8a84c-9ab2.md`。

| # | 事实/偏差 | 处置与证据边界 |
|---|---|---|
| S41R-1 | 全局时钟取代每 scope 寻址计数；meta 降级诊断 | 接受；探针 3/4/9/10 对账、单调与历史证明 |
| S41R-2 | `tools_revision` 第二 fence 入 hash | 接受；探针 9/16；tools 无历史时间轴 |
| S41R-3 | 读面两角色 recall/route，resolve 拒绝 | 有意收窄，非旧三角色读面同构；探针 13 |
| S41R-4 | caller/read_ok 复刻 CE 形态但零 `v13_ce_*` 调用 | 接受；探针 1/13 |
| S41R-5 | 上行 cap 32 + 环截断，与下行 cap 64/RAISE 不同 | 有意读面 fail-closed；探针 8；环仅静态防御证明，不冒充运行时环覆盖 |
| S41R-6 | claim 加键留设计 §11.5，fair_claim SIX 不动 | 消费侧后续提案，本阶段不强制 worker 钉版 |
| S41R-7 | 注册事件推进 max_event_seq，令在途 advance stale | 有意安全方向；探针 14 只验证 probe 键变化，不跑 advance |
| S41R-8 | `v13_interruptible()` 函数优先，profile 为覆盖面 | profile 本阶段无消费者；SQL 注释/README 与静态探针 |
| S41R-9 | unresolved 入 hash | 诊断差异即世界差异；探针 11 |
| S41R-10 | prompt_section 形状缓议 | 仅 object，留首个消费者定型；探针 12 |
| S41R-11 | p_rev 负数 RAISE / 0 空注册面 / 大于时钟钳制 | tools 始终当前；探针 10 |
| S41R-12 | ce_run registration_generation 映射仍可选 | 本阶段零触碰，留消费侧提案 |
| S41R-13 | 六守卫精确适配，含 fresh-file 差集与 fair_claim 原有合取保留；validate_delta 名白名单显式增加公开 `v13_scope_chain`。两处旧 plan_arm 负例（ce_run:40→41、旧 future not_scheduled:41）变异不变，因 registry:41 撞号，reason 改为 `duplicate stage number`。首次 50 项在第 16 项 goal_supervisor cached-only 路径中断。 | Oracle 2026-10-18 裁决：allow() 合并 cached+untracked，goal_supervisor 直接传 cached-only；r1_load_append_ok 仅在 tracked 前缀全无时保留 CE 单 SQL 例外并新增精确 registry tuple+固定四文件全部 is_file 例外，不修改 tracked。纯内存 13 案例含四个缺文件、各单文件、错文件名、未知 stage、CE 存在/缺失；merged 与 cached-only 定向验证通过，plan_arm 104 checks。goal_supervisor 调用点、r0_source_scope 不变；P1 前完整重跑 50 项符合预期。追加 P1：原字符串入口选固定旧角色，与对象临时角色不同；删除 ROLE_ALIASES，对象使用 database.roles、字符串使用 _role_names(name)，None 省略 user、显式角色直通，失败原样传播。四 wrapper/default route/None-owner/显式 plain/缺 server 文案八项真实连接检查均绿，closing+idle 且只查身份，native_static_setup 31 checks、总 481。CE setup 与既有 r1 守卫不动；修复后提交前完整 50 项符合预期，见 precommit4-p1 results.json；提交后净树同清单证据在最终 closeout report 记录，不预填成功。 |

## Stage 42 (registry Phase 2) 偏差台账

本节独立于已退役的 Stage 42 goal_workflow。Oracle review
`untitled-chat-9347AA` 已先读取再处置；原始导出为
`prompt-exports/oracle-chat-2026-10-19-002613-untitled-chat-9347aa-da5a.md`。
收尾 agent 按协调交接权限不暂存、提交或推送，不把脏树验收写成 post-commit receipt。
最新实现提交前结果 S42R-11：完整离线隔离 51 项通过；S42R-12 记录已推送
实现提交后的净树复验。文档 follow-up 仍由父协调 agent 处理，AGENTS 全任务
要求未被取消。

| # | 事实/偏差 | 处置与证据边界 |
|---|---|---|
| S42R-1 | 计划初始 event_current ACL 未含 recall；canonical 当前读链在 recall 身份下需要该谓词 | 增加 recall 的 `v13_effect_context_event_current(uuid,bigint)` EXECUTE；不授 effect_current 或任何 pin 表/列权限。consumer 实际 recall canonical 读取与 ACL 正反例验收；resolve 仍不能读 registry context。 |
| S42R-2 | 实际 current tool spawn 的 `fork -> prefix_identity -> canonical_state` 在 spawn_owner 下同样需要 event_current | 仅增加该窄 EXECUTE；实际创建 child、spawn effect succeeded 和 child-created receipt，并 SET LOCAL ROLE spawn_owner 执行 canonical chain。superseded 不 spawn，legacy 保留。spawn_owner 既有 global claim EXECUTE 来自 Stage 20，不是本轮扩权；effect_current/pin 表仍拒。 |
| S42R-3 | W4 govern 首红是 `flip update blocked by share` 的锁观察断言；独立原样复跑 228 checks 通过，不能声称稳定复现业务锁错误 | query-text 观察可能选中观察器/其他 backend；改为准确 updater PID，要求 pg_blocking_pids 与未授予 transactionid lock 同时成立。修正后 228 checks 通过。r0_source_scope 对固定基线精确重建两处批准改动；fair_claim/fair_driver/frontier_gap/goal_supervise/goal_supervisor/workspace_admit/plan_arm/parity/ports/read_tools 仅增加具名 guard 兼容，不开放任意 govern 改动。 |
| S42R-4 | 任意 scope 注册/退役或 tools 变化均全局失效；meta 不是 freshness source | 接受 global blast radius，双连接 writer 提交后旧 pin/event/advance stale；逻辑 judge effect 身份不随 registry 水位变化。MATERIALIZED 锁屏障证明一条 envelope 语句读取同一旧双标量，下一语句见新双标量；snap 不重读 clock。tools 不提供历史时间轴。 |
| S42R-5 | exact payload guard 禁止向 tool/repair/human payload 加 pin 锚；共有 completion 不能以 definer 身份绕过 current_user 授权 | 用 owner-only append-only side tables 绑定精确 attempt/fence；capture 失败连同 effect/events/sequence/mapping 整体回滚，missing/malformed false。human 六键名字和值、tool/call/repair 负例保持。completion common implementation 保留 INVOKER；新增七参无默认值，旧五/六参兼容。 |
| S42R-6 | 计划 §4.2 要求 fair SIX 改 SEVEN，但原 fair_claim/fair_driver gate 仅安装 Stage 39 前缀 | 保留前缀 SIX，不修改冻结 claim SQL；overlay consumer 独立证明 SEVEN 与 owner/fair、route/global 身份和 route fair 42501。worker gate 证明短事务/双 fences/三元 cache/IDLE Fake IO/独立 strict completion 协议，不冒充新生产 worker 或真实 provider parity。 |
| S42R-7 | 51 项验收前四次中断，不得拼接成成功序列 | attempt1 #4 CE 因同时运行独立临时库 gate 的全局角色清理碰撞失败；随后严格串行。attempt2 #10 fair_claim 的 stage_bytes 拒绝 govern 观察修正；按 S42R-3 精确适配后从 #1 重跑。attempt3 #14 frontier_gap 同一精确例外缺失而停止，连同另两处同型静态守卫一起适配并验证。attempt4 #16 goal_supervisor 的同型 frozen 路径拒绝 govern 修正；精确路径适配后静态验证，再执行用户限定的最后一次完整序列，不再扩大 scope。保留 acceptance1/acceptance2/acceptance3/acceptance4 原始 results.json，每项 trace bytes/mode 恢复；最终序列结果另记。 |
| S42R-8 | Oracle 怀疑 trigger/FK qualified catalog strings 和 superseded fixture | 实际 PG 18.4 catalog 安装/闭集通过；当前 superseded fixture 是 pinned，legacy 单列。落实实际 spawn_owner 调用、human 六键精确值及 function_acl mutation 负例。历史默认 parity 的 node_modules toolchain_absent 不算 strict/all-plane 证明；历史 chain-cycle 仍只有静态防御覆盖。 |
| S42R-9 | 最终序列 #30 pi_parity exit 1；外部 PiSwift 当前 HEAD 为 `a73c391ce1d891b7b6f8f37a8508f184a31703e3`，冻结 driver 编译失败：main.swift:233 缺 throws 调用的 try，:310 toolExecutionEnd 四元组与当前五元组不匹配 | 480.16 秒后真实编译失败，非 600 秒 timeout；不因与 S40-21 症状相似就声称依赖提交相同。用户限定最后一轮、不扩大 scope，故不回滚/修改 PiSwift、不改冻结 driver、不再重跑。#1–29 符合契约（27×0 与 expected 1/2），#31–51 未运行；W5/W6 完整验收红，提交前条件不满足。 |

历史首红 receipt：`prompt-exports/w5-phase2-final-20261019/results.json`（30 条实际
执行记录），同目录 manifest.json/head.txt/逐项日志；全部 51 项实际状态见
`v13/registry/README.md`。goal_supervisor frozen 路径修正后的静态验证通过，
最终序列 #16 74 checks、#19 govern 228 checks 均 exit 0，未出现真实冲突；
未授任意 frozen 例外。30 条 `trace_restored=true`，pg.jsonl SHA-256
`3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`、
mode 0644，tracked traces 无 diff。独立 consumer 289 / registry 16组485
均 exit 0，但不补算被中止序列 #39/#51。文档已据实收尾，未暂存、提交、
推送或做 post-commit 复验；四次前序中断仍保留，不拼接成全绿。

### S42R-10：旧 PiSwift 隔离预验证受依赖 fetch 阻断

用户随后授权查找保留旧版本、隔离验证 parity/ports，再从头执行 51 项。
实际仓库 `/Users/wxl/Projects/PiSwift` 是 clean main/a73c391；没有旧本地
branch，但 tag `v0.87.1` 精确指向历史基线
`bfccb32f2d6318b75519b2c1790e7e66e133f5da`。该版 SDK 非 throws、事件四元组
与冻结 driver 相符，不需从多个未知 branch 猜选。保留 remote branches 并未
被切换或改写。建立 `/tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift` detached
worktree，活动 checkout 不动。

硬编码 filesystem dependency 不支持 SwiftPM mirror（尝试被 manifest
校验拒绝后已撤销），改用 ignored PATH wrapper 的真实 Swift
`--package-path` 入口指向临时 package。Sources 逐字节/hash 校验；副本
Package.swift 只替换 PiSwift 路径，tracked driver/manifest 与外部源码零改动。
预验证 parity exit 1：SwiftPM 更新 MacPaw/OpenAI 仓库时 GitHub TLS
`SSL_ERROR_SYSCALL`，不是原 #30 API 错误复现，也不是旧版可运行证明。
按用户任一非预期失败即停，未重试、未改解析策略，ports 未跑、完整 51 项未启动。

证据 `prompt-exports/w5-piswift-compat/`：preflight-results.json、pi_parity.log、
swift-invocations.jsonl、environment-before/after.json、prepare/verify/wrapper。
trace 已恢复原 SHA-256/0644；活动 HEAD/status 前后相同且 clean，独立旧
worktree clean，冻结 Sources/manifest hashes 未变。W5/W6 与提交前条件仍
不满足（此为历史尝试结论）；此前 Oracle 已验证修正保留，未重审，未暂存/commit/push。

### S42R-11：本地锁文件与缓存离线解阻，完整 51 项通过

用户授权继续离线调查，不改活动 checkout、Package.swift、冻结 driver 或外部源码。
旧 tag 的 Package.resolved 为 version 3、25 pins；OpenAI 固定 revision
`4ed3ea99ff9dfd2a760509ddb31020f4b153ef93` 与活动 `.build/checkouts/OpenAI`
HEAD 相同，裸库 `.build/repositories/OpenAI-f436e9d2` 的 cat-file 返回 commit。
pg-agent 两套既有 build caches 已有依赖 checkout/repository，不需复制活动缓存。
将旧锁文件复制到 ignored 临时 package，保留副本唯一的依赖路径替换，wrapper
仅追加真实 Swift `--disable-automatic-resolution --skip-update`。初次离线 release
build exit 0（472.93 秒），不再触发失败的依赖 update；未修改冻结测试断言。

预验证依次 parity → ports 均 exit 0，trace bytes/mode 均恢复；证据
`prompt-exports/w5-piswift-compat/offline-results.json` 及 offline-pi_parity/ports
日志、offline-build1.log、swift-invocations.jsonl。然后从 #1 一次串行跑完 51 项，
receipt `prompt-exports/w5-phase2-offline51-20261019/results.json` 有 51 条，
全部 valid/trace_restored=true；49 项 exit 0，#17/#18 契约预期 exit 1/2，
runner exit 0，总 item 用时 951.81 秒。不拼接此前 red/独立运行；逐项退出码、
隔离环境和重跑命令见 registry README 的 Offline Isolation Acceptance。

本序列 registry 16/16 groups、485 checks、零 independent failures；consumer
289 checks；govern 228、goal_supervisor 74、plan_arm 104、CE 665、fair_claim 137
及 read_tools E4（487.54 秒，含嵌套 registry/parity/ports）全部通过。
计划 §5 所有 consumer 验收面有本次 item 51 证据，不遗留锁序夹具红项；
goal_supervisor frozen 入口与 govern 精确观察修正无冲突。S42R-1 recall canonical
链的 event_current EXECUTE 仍仅窄授，不授 effect_current 或 pin 表/列。

最终 trace SHA-256/0644 与前述相同且 tracked diff 为空；verify.py 再次证明
活动 PiSwift main/a73c391 和独立 v0.87.1/bfccb32 worktree clean、冻结原始
Sources/manifest hash 不变。默认 parity 仍报告 node_modules 缺失，未启用
PI_PARITY_REQUIRE_ALL，不冒充 all-plane/真实 provider 证明。Oracle 已读并落实的
actual spawn_owner、human 六键、function_acl mutation 修正保持；catalog qualification
和 pinned fixture 经实测不复现问题，无新 Oracle review、无扩大运行时 scope。

W5/W6 测试/文档前置条件满足。父协调会话 get_log 核实原“不 commit/push，review
后处理”是协调 agent 对收尾 agent 的权限边界，并非用户取消全任务提交要求。计划
§7 已更正：收尾 agent 只交付验收工件；实现提交已推送，文档 follow-up 仍由父
协调 agent 依 AGENTS 处理。保留 S42R-9/10 历史失败，不以本次成功改写历史。

### S42R-12：已推送实现提交的 post-commit 净树验收

实现提交 `937a864115694373250417daa374b05fad64267b` 已由父协调 agent 成功
推送到 `origin/v99`（`5be562d..937a864`）。本收尾 agent 未暂存、commit 或
push 文档；仅在该 HEAD 上复验。`git status --porcelain=v1
--untracked-files=no` 在运行前后均为空。沿用旧 PiSwift tag `v0.87.1` 的
detached worktree、锁文件与本地缓存离线隔离，从 #1 严格串行执行完整 51 项：
receipt `prompt-exports/w5-phase2-postcommit-20261019/results.json` 有 51 行，
49 项 exit 0，#17/#18 预期 exit 1/2，runner exit 0；每行
`valid=true`、`trace_restored=true`，总 item 用时 911.44 秒。逐项 manifest、
日志、HEAD/净树与 `verify-after.json` 保存在同一 receipt 目录。

trace SHA-256 `3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`、
mode 0644；PiSwift `verify.py` 仍证明活动 `a73c391`、旧 worktree `bfccb32`
和冻结 Sources/manifests clean/unchanged。默认 parity 因缺失 `node_modules`
平面仍是环境限制，未启用 `PI_PARITY_REQUIRE_ALL`，不作 all-plane 或真实
provider 声明。Oracle findings 已读并按 S42R-1/2/3/8 处置；本轮没有 runtime、
测试逻辑或 runner 修正，也没有新的 scope。

## Stannum 0.5.1 Upgrade Deviations (2026-10-19)

| 编号 | 事实与处置 | 边界 |
|---|---|---|
| ST051-1 | Phase3 #26 旧版本锁与实际 0.5.1 冲突；用户明确授权独立升级 U | 首轮 RED 保留；U 后重新锁定 Phase3 基线，不拼接部分绿 |
| ST051-2 | Oracle 提议的 capabilities 顶层键与实际 API 不符 | 改用实际 contract_version、engine.name/format；engine.version=0.5.0 是合同目标，不要求它等于 0.5.1 |
| ST051-3 | usage run01 新 V12/V13、P 组绿，旧 F5 要求单列权重拒绝而红 | 源码 storage/mod.rs::envelope_fields 固定单列权重1.0；run02 F5 验合法 body:1.0 命中/verify、F5b/c 验零权重和 ALTER 拒绝，全77绿；生产索引不加权重 |
| ST051-4 | 固定历史源码冻结会拒绝授权升级 | 对九个最终完整文件 SHA-256 精确锁定（路径/哈希见独立升级报告），确认普通文件与历史Git模式后恢复固定93d05f1字节继续原证明；无整路径豁免，内容/执行位/符号链接变异与版本回退仍拒绝 |
| ST051-5 | 0.4→0.5 catalog delta 小但存储格式不兼容 | 生产停写/备份/干净关闭/重启/ALTER/普通REINDEX/verify，replica重建、rollback restore；本轮只新建stage库，不执行生产迁移 |
| ST051-6 | 实施审查发现内容哈希不能覆盖文件类型/模式，且 ExceptionGroup 不能容纳中断 | 普通文件/历史Git模式检查及执行位/符号链接负例通过；BaseExceptionGroup 保留中断与清理错误，九文件台账已纠正 |
| ST051-7 | U 独立完整51项 run01 全符合契约，908.70s | 49×0、预期1/2，每项trace恢复；registry485/consumer289及最终PiSwift verify绿；不替代Phase3两轮，历史RED不删 |
