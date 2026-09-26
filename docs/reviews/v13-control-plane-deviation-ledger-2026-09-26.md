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
| F22 | parse 侧潜在缝：活体 `v13_tools_catalog_frozen`（resolve 定义，未被 stage 18+ 换体）仍拒 VOLATILE sql 工具，无 H7 具名例外——spawn_subsession 目录行 enabled=true 时 `v13_parse` 会被拒（探针：needed_judgments 可过、parse 未到 catalog 即被 GUC 拦，未终验）。demo 夹具维持 enabled=false；扇出臂不查目录（advance 直读 tool/call 事件），L3 场景不受影响 | 记录不改。若产品要让 spawn 经 parse 目录可选，需另裁 catalog_frozen 的具名例外（涉 stage 2 契约，须走裁决；不得热修） |

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
