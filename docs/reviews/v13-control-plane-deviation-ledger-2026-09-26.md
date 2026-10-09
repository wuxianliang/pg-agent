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
