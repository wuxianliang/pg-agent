# v13 Phase C 重开计划：根会话阻断分支内结算收据（2026-10-01）

**修订 4；R0 计划合同已按第三轮两路附条件接受的全部前置条款补齐（对应表见 §1），可进入 R0 实施。仅文档：尚未实现、未跑 R0 gate；不是运行时 exit_0。R1/M3 续行仍未获接受、not_run。**

## 1. 授权、现状与复审记录

用户授权："重开计划并允许修改唯一的 v13_advance，先写新计划并复审，再继续 M3"。本计划据此覆盖旧 Phase C §1/§5.2 中禁止编辑 `plan_arm` 的一小部分；历史 Phase 0/A/B/C 计划文件不改写。

基线为 `fb295ac6c7459bb98dac57e37883af549d2d8a4c`，Phase C M2 已提交并推送。其 99-check gate 是历史实现证据，不是本重开计划的验收。2026-10-01 父会话独立探测库 `ll_goal_supervise_34504_465a7b` 已 DROP：

| 根会话上的并存事实 | wrapper 返回 | 同源 receipt | 未付候选 | 阻断 effect |
|---|---|---|---|---|
| succeeded progress harness + human | waiting | 0 | 1 | ready |
| succeeded progress harness + workspace opener | waiting | 0 | 1 | claimed |

探测使用 route policy version 2、具名 open/enqueue/complete/workspace opener、首个 advance 前 direct override，无真实 provider。它证明旧 §4.2/§4.7 的停点，不是 M3 gate 通过。

复审历史（均为计划静态复审，不是测试）：

- `E6CEF891-8452-41B2-B7B8-7F2B54D5E04D`：一条 lane 退回、一条附条件接受。共同否决 JSON settlement marker：两参数 advance 无法证明 wrapper provenance；绕过 early return 也会进入 dispatch。
- `D04FDB4C-DD07-4BB8-BD1D-75B63ABC0DB3`：一条 lane 退回修订、一条附条件接受。R0 收据前移方向可保留；须限制为根调用、完整列出 gate 兼容；R1 单次入口守卫不能证明跨事务 T0，调用 Phase C helper 又形成 Phase A 反向依赖。
- `D03E5C3C-A028-4261-B386-51AE0C61502C`：第三轮两路均附条件接受 R0、无 P0；明确补齐条款即可实施。修订 4 按下表落实所有条件，不声称未进行的第四轮复审，也不把 R0 接受扩展为 R1 接受。

| 第三轮接受条件 | 修订 4 对应条款 |
|---|---|
| 合法 signals 谓词与非法输入保护分开 | §3.2 先验证 object/文本数组，原非阻断臂不改 |
| 根锁→选前驱→effect 锁→全部重读 | §3.1 固定伪代码、§5.1 确定性交错 |
| direct/wrapper 等待逻辑不绕过前序墙 | §2.1 与 §3.4；有效快照夹具 |
| 固定基线与唯一哨兵，可提交前后验证 | §4.3 基线读取命令、块标记及全字节还原 |
| 十条 gate 的条件性失败不能假绿 | §5.2 开工基线与 evidence_good_ref 环境证据 |
| child/root 与 stopped/direct/wrapper 独立证明 | §5.1 分立断言 |
| staged paths、停放草稿、证据状态保护 | §5.3 精确清单与 not_run/exit_0 区分 |
| 提前记账影响下一轮 quota/派发 | §2.1 合同及 §5.1 配额临界点断言 |
| 两个旧 gate 的整目录冻结替换 | §4.3 明确移除相应空 diff 项，换更严格的正向证明 |

旧 `v13/goal_supervisor/**` 草稿已非破坏性停放到已忽略的 `prompt-exports/phase-c-m3-parked-2026-10-01/`，标明“非证据、非起点”。该目录不装载、不测试、不提交。R1 获新合同后从已接受规格重新实现，不能以草稿的 HOLD/skip/非零输出充当验收。

## 2. R0 的唯一行为变化与不变项

### 2.1 明确改变普通 advance 的合同

**普通调用和 wrapper 调用一视同仁：根 `v13_advance` 已进入 ready/claimed 阻断分支时，可在仍然返回 waiting 之前，为合格的当前 harness 前驱幂等补一张收据。它仍不能派发。**

“一视同仁”仅指两者都调用同一 advance 阻断分支；不改变 snapshot/stale/terminal/unknown/cancel 的判断顺序，也不保证不同前置状态的两次调用均能达到这里。direct 正例独立构造有效 probe/envelope，与 wrapper 的入口状态相同，不用缺失/伪造快照当作普通调用证据。

这不是“普通 advance 完全不变”：material 计入时点会提前，现有 session-local quota 能更早看到它。**因此解除阻断后的下一次 advance，在只差一张收据就耗尽的配额边界上，spawn 或 plan prefix 可以因这张已提交收据而合法等待/不派发；这项派发结果差异是本次明确接受的派生变化。** 不要求将已有收据从 should_run 视野隐藏来复原旧派发。不改 quota 函数、不新增 block、不升策略版本、不声称 goal 级预算。finish 在存在阻断时仅补收据，不 closeout；解除阻断后的普通 advance 才能走原有 finish/归档路径。

允许持久中间状态：同源 receipt 已存在、root 仍 waiting、finish 尚未 closeout、human/workspace 的 status/lease/fence/attempt/result 未变。字节不变的后续臂可能读取到不同的已提交 receipt 事实；“原路径不变”不等于否认这项配额时间差。

### 2.2 唯一修改位置

仅编辑 `v13/plan_arm/v13_plan_arm.sql` 内已存在的 `public.v13_advance(uuid,jsonb)`，在原：

```sql
IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status IN ('ready', 'claimed')) THEN
  -- 本次新增的 root-only receipt bookkeeping 插在此处。
  UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
  RETURN 'waiting';
END IF;
```

不得删除/下移该 waiting 返回，不把它变成可绕过的 dispatch 门。整个文件仍恰好一份该函数替换；“唯一”指 Phase A/C 当前生效的 plan_arm 副本，不抹除 stage 1–29 的历史函数定义。不在别处追加第二份当前替换，也不动态拼 SQL 替换函数。

收据仍由 `v13_advance` 调用已有 `v13_append_event` 写出。本次在同一函数的阻断分支内增加记账位置，原非阻断收据臂保留不动；这不声称只有一处 INSERT/调用文本，而是只有同一个 SQL 函数承担收据写入责任。不得新增 SQL 收据 helper 或外部写者。

### 2.3 保持不变

- `v13/load.py` 全字节不变，表尾仍 stage 38 `goal_supervise`；不新增 SQL stage/key，不重排加载。
- stage 1–29（包括 govern/control）、Phase A/B/C 原计划、工作区 opener/accept/exec、plan writer、fingerprint、recover、should_run、hint、quota、策略均不改。
- `v13/goal_supervise/v13_goal_supervise.sql` 全字节不变；wrapper 的授权、READ COMMITTED、根锁、effect 锁、p_snap 与 effects.result 相等性、skipped_failed 不变。
- `v13/loop_driver/**` 全字节不变。不存在所谓“8 行即可闭合 T0”的实施授权。
- 新增逻辑之外的 advance SQL 保持逐字不变；无阻断时的 spawn、plan prefix、continuation、approval、route、closeout 仍走原路径。
- 不增加参数、JSON marker、GUC、临时状态、表/列/索引/触发器/角色/GRANT/事件族。JSON/hash 相等、current_user 和行锁都不作 wrapper 来源证明。
- 无真实 provider。测试只使用 Fake/DB 夹具；无外部 IO 进入事务。不动共享 stannum 安装。

## 3. R0 冻结算法

### 3.1 适用范围与锁

现有入口锁的是 `sessions.session_id = p_sid`，不是自动映射的根。本次新增逻辑**只在该已锁行 `parent_session_id IS NULL` 时执行**。child 调用不补这张收据、不向上锁根、不扫描整树；其 ready/claimed 分支完全维持旧行为。

固定顺序：`lock sessions[p_sid] → 读取该锁定行的 parent_session_id → 仅 NULL 时选择 predecessor(p_sid) → 若非 NULL 则锁该 effect FOR UPDATE → 重新查询前驱身份及所有 receipt 谓词 → 全满足才 append → 原 UPDATE/RETURN waiting`。前驱选择必须在 session 锁取得后；不存在前驱则直接落入原 waiting，不锁 NULL id。

根 ready/claimed 分支内，只用 `v13_harness_predecessor(p_sid)` 取得活体当前前驱。它已有明确排序/LIMIT，不在 R0 新造 winner，不扫描所有物理未付行。material collision/same-source 查询必须在 effect 锁后，限制到 p_sid，并且使用重读的行；不使用锁前缓存 status/result。任何状态/身份/归属重读不匹配都零 receipt、waiting。只读选择不更新其它 effect，也不使用 advisory lock。

不得在 stage 32 SQL 调用 stage 38 的 `v13_unpaid_harness_turn` 或其它 Phase C helper，避免逆向加载依赖。

### 3.2 正例谓词

重读后的 effect 必须同时满足：

1. effect 存在，`session_id = p_sid`，仍是 `v13_harness_predecessor(p_sid)` 指向的同一行；
2. kind=tool，`v13_is_harness_tool` 为真，`v13_harness_request_ok` 为真，origin_user_seq 等于 `v13_last_user_seq(p_sid)`，status=succeeded；
3. result_kind=finish，或 result_kind=progress 且无同源 repair/required、replan/required；
4. **仅对合法 signals 使用原臂的规范化谓词；非法类型是新增 R0 块中的安全不匹配。** 先以独立类型守卫确认 result 为 object、signals 缺失或为全元素 string 的 array，然后才调用 jsonb_array_elements_text；不得依赖一条 SQL AND 的短路来保护非法展开。缺键当空数组；JSON null、标量、object、非文本元素均零 receipt/waiting。比较沿用原臂 array_agg ORDER BY，不去重。旧非阻断臂的非法类型错误行为不改，测试不声称它也会安全等待；
5. 不存在同 session 的他源 material receipt：与原臂同样 JOIN events ev 到 effects src（src.effect_id=ev.source_effect_id），要求 ev.session_id=p_sid、ev.type=turn/material_spent、ev.source_effect_id 不同、src.request->>'logical_turn_id' = 当前前驱 request->>'logical_turn_id'。不是从 receipt payload 读 logical_turn_id；NULL 的 `=` 语义原样保留；
6. 同 source_effect_id 尚无 material receipt；
7. 不满足 stopped+stored-failed 禁令：`v13_goal_lifecycle(p_sid) = 'stopped' AND (e.result->>'failed') IS NOT NULL`。

第 7 条包括 false、0、空字符串、非空文本；JSON null 和缺键均不阻断。不得以 Python truthiness/非空字符串取代 SQL 语义。wrapper 在禁令成立时仍根本不调用 advance；直接 advance 在此新分支只承诺不写收据，不能被描述成“零次 advance”。running 根的同样 failed 值不触发这条 stopped-only 禁令。它只约束本次新早退分支；解除阻断后旧原臂仍可能补记，不得把此判断偷偷抄入旧原臂。

任何前置条件不满足，包括新快照下前驱改变、signal 冲突、material 逻辑回合冲突、wait/reject/非 harness/非 succeeded：**该新分支零新增收据，继续原 waiting 返回，不因这些不匹配新增异常**。这是保持阻断时等待行为；不修改原非阻断臂同类冲突的 RAISE。

不要调用 `v13_harness_tail_gap`、plan prefix、任何派发 helper。新分支仅做本节只读检查；不会为对齐原臂而执行其它副作用。意外数据库错误（deadlock、statement timeout、实际约束异常）仍正常失败/回滚，不用 `EXCEPTION WHEN OTHERS` 静默吞错。

### 3.3 唯一允许的新增写入

满足全部条件后，通过原有 append_event 和 material guard 写一条：

- type=`turn/material_spent`；
- session_id=`p_sid`；
- source_effect_id=锁定的当前 harness effect；
- payload 恰为原闭集 `schema_version=1`、`effect_id`。

之后执行原来的 session waiting UPDATE 并 RETURN waiting。允许 append_event 本身正常更新 next_seq 等事件簿元数据；不额外写 plan/todo/wake/resolve/route/tool/call，不 enqueue、不 send_work、不 closeout。所有既有 effect 的 status、attempt、fence、lease、result 不变。

同一 root 的并发 advance 由 session 行锁串行化；二次调用看到已付收据，零新 receipt。若既有 receipt 触发器被发现会派发/入队，停止 R0，不修改触发器规避。

### 3.4 不解锁的分支

terminal、stale snapshot、unknown/blocked_unknown、cancel 的判断顺序与正文不动；它们仍可能在 ready/claimed 之前返回。root 下某个 child 的 workspace hold 也不等于 root 的 ready/claimed effect：测试不得混为一谈。R0 正例均把 blocker 放在 root。

未知墙/cancel 之后仍未消费不证明收据成功。后续 M3 除 `skipped_failed` 外发现同一候选未消费，必须报真实失败，不能把 waiting 解释成成功。原关闭谓词和 stopped 指纹纪律不变。

## 4. 源码保护、允许路径与旧 gate 兼容

### 4.1 基线指纹

基线 commit 见 §1。规划时文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| plan_arm/v13_plan_arm.sql | b1f0c24e840edc2d1c09b59c19994df0e9be5d8b5ed9b8de287ea557ac6786c0 |
| loop_driver/driver.py | 1fd88f70ffff1593680e63c4f67fb046f0ffa8bcd5127cbe0f99f083361d6a98 |
| goal_supervise/v13_goal_supervise.sql | 712391374cdbefb4ba017b74ba77fa54779da135d9ba364c196a3881756449a5 |

这是**文件哈希**，不是加载后 pg_get_functiondef 哈希。实现 gate 在临时库加载前后另记录函数哈希。不得混用两种证据。

### 4.2 R0 实现提交唯一允许路径

1. `v13/plan_arm/v13_plan_arm.sql`：只在根 ready/claimed 新块及必要局部变量声明处增加逻辑。
2. `v13/plan_arm/test_plan_arm.py`：保留全部既有测试，新增 R0 direct advance 与源码边界测试。
3. `v13/plan_arm/README.md`：说明新的阻断记账时点。
4. `v13/goal_supervise/test_goal_supervise.py`：保留既有 wrapper 测试，增加 R0 组合正负例；仅按下文修正 stage_bytes。
5. `v13/goal_supervise/README.md`：说明 wrapper 未改但所调用 advance 新能力及未解残留。
6. `v13/frontier_gap/test_frontier_gap.py`：**只改源码冻结检查**，保留其函数测试/数据/断言，不改任何 Frontier SQL/语义。
7. `v13/frontier_gap/README.md`：仅记录 stage_bytes 兼容 R0，不改既有 Frontier 能力声称。
8. Phase C 的 `conformance-matrix` 与 `deviation-ledger` 两文件：新增 R0 行；不把历史 M1/M2 的通过库名、计数、旧函数哈希覆盖成新值。

不纳入 goal_supervisor、loop_driver、load.py、uv.lock、历史计划、调查或探针。新 gate 所需帮助代码优先置于现有 test 文件，不为测试便利引入运行时依赖。

### 4.3 stage_bytes 不是删目录白名单

当前 frontier_gap 和 goal_supervise 的 `git diff HEAD -- ...` 会因为合法 plan_arm 改动变红；goal_supervise 还保护 frontier_gap 测试目录。因此必须在 R0 同一个提交中同步以上第 4/6 项，不靠先提交使 diff 为空，也不跳过旧 gate。

- 所有未授权路径仍要求无源码变化。加载器、stage 1–29、loop_driver、workspace SQL/exec、goal_supervise SQL、frontier_gap SQL 与基线一致。
- 对 plan_arm SQL，用命名块边界提取新 R0 块和新声明，去掉这些新增区域后的字节必须与基线 SQL 相等；旧原臂完全不动。边界唯一、插入位置唯一、函数定义数量为一。不得用“目录在名单里”替代这条正向证明。
- 对 test 文件，用函数边界检查：原有功能测试及入口调度保留，只有 `test_stage_bytes`/源码核对帮助代码可改并可增加 R0 测试。frontier_gap 的功能测试必须逐字保留；goal_supervise 仅允许追加 R0 测试调用，不删除或降低既有断言。
- 测试读取本计划钉住的基线 commit 与当前文件进行比对，不只比 HEAD，因此提交前后均有效。没有该 git 基线对象则 gate 明确失败，不默认为“干净”。读取只涉及受保护的已跟踪文件，不吸入工作区其它未跟踪文件。
- `goal_supervise` 中“装载它自己的 SQL 前后 advance 哈希相等”的保护不删除，因它的 SQL 根本不改；只为新 plan_arm 装载结果增加 R0 哈希记录。当前测试如果只有装载后的同值比较，应补成真实重载前后比较而非声称旧保护已充分。

**明确替换而非同时保留矛盾断言：** frontier_gap/goal_supervise 中针对 plan_arm 的整目录 `git diff HEAD` 空差异项，以及 goal_supervise 针对 frontier_gap 测试目录的空差异项，从原列表移出，改由上述固定基线正向证明覆盖。不是要求合法修改同时保持空 diff。loop_driver/workspace/real_chain/plan_contract/plan_read/workflow_bind 等未授权目录仍不动。

机械比较规范：使用 `git cat-file -e fb295ac6c7459bb98dac57e37883af549d2d8a4c^{commit}` 验证对象，用 `git show fb295ac6c7459bb98dac57e37883af549d2d8a4c:<path>` 读取原始 bytes。源码新增声明用唯一独立整行哨兵 `-- R0_DECL_BEGIN` / `-- R0_DECL_END`；新增阻断代码用 `-- R0_RECEIPT_BEGIN` / `-- R0_RECEIPT_END`。每对恰好一次、不得嵌套、基线无此标记。声明块限 advance DECLARE 区，receipt 块限原 ready/claimed IF 内原 UPDATE/RETURN 之前。删除两对哨兵及其内部完整行后，全 SQL bytes 必须与基线相等，不做格式化、空白归一化或字符串语义猜测。R0 块额外扫描禁止派发调用和 root 映射/Phase C helper，块被挪位即失败。

源码冻结测试须在提交前全跑、提交后再次跑 plan_arm/frontier_gap/goal_supervise 三个 gate。提交后再次跑不是用提交掩盖红项；提交前已全绿。固定基线对象缺失、读取失败或边界不唯一均退出非零。

## 5. R0 验收：先测再记，再提交推送

### 5.1 新增断言（全部必跑）

- `r0_root_human_ready_receipt`、`r0_root_human_claimed_receipt`：progress/finish 两种均覆盖；返回 waiting，同源收据 +1，human 不改状态、不回应。
- `r0_root_workspace_claimed_receipt`：通过具名 opener 产生 root 的 claimed/infinity 行；harness 收据 +1；该 workspace 行的完整状态/lease/fence/attempt/result 不变；同 effect tool/call 不增加。
- `r0_direct_advance_receipt`：无 marker 的普通合法 advance 同样补记，不是 wrapper 特权。
- `r0_no_dispatch`：上述阻断调用无新 effect，除 receipt 无其它新事件类型，无 send_work 调用（静态可达面 + 既有工作队列证据），不调用 plan prefix、closeout 或改变 todo。
- `r0_idempotent_same_source`、`r0_two_connections_one_receipt`：两连接确定性锁交错后仅一张同源收据；不得靠 sleep 猜测胜者。
- `r0_stopped_failed_wrapper`、`r0_stopped_failed_direct`、`r0_running_failed_direct` 分开：wrapper stopped+false/0/空串/文本确实零 advance；direct stopped 同值允许调用但新块零 receipt/waiting；direct running 不触发该禁止。null/缺键 stopped 下可补记。零 advance 需可靠调用计数/事务内测试仪表验证，不以 receipt=0 代替；测试仪表不改变产品 SQL、不外带事务写入。
- `r0_current_predecessor_only`：两条物理未付，按活体选择器只付当前；不自行遍历历史；旧 origin、不属于 p_sid、非 harness、wait/reject、ready/claimed/failed 的前驱不付。`r0_effect_lock_recheck` 用两连接制造先选 effect 再等待其锁、锁持有者改变 status 后提交的交错；通过锁等待状态观测而非固定 sleep，重读后必须零 receipt/waiting。
- `r0_signals_mismatch_waits`：signals JSON/事件不一致时零 receipt、不因新增逻辑 RAISE；无效 JSON 类型也不产生新异常；原非阻断臂原样。
- `r0_material_collision_waits`：同 logical turn 他源已有 receipt 时零新 receipt、仍 waiting、无 effect。合法具名函数构造能构造的夹具；额外负例仅限隔离回滚中的 effects UPDATE，不禁用触发器。
- `r0_child_advance_unchanged`：child ready/claimed 调用不消费 root 或 child 的新前移 receipt，不锁 root，不改变旧返回行为；检查 p_sid 自身 parent_session_id，禁止先 map_root 再检查。另一连接先锁 root，child advance 在有限 lock_timeout 内完成，root/child receipt 数和 effects 保持不变（child 原 waiting status 更新除外）。
- `r0_unknown_cancel_terminal_stale_unchanged`：前序墙/快照/终态仍挡住新分支，收据不增加。未知墙 fixture 满足既有 drift 不变量，不以原有错误冒充本次回归。
- `r0_no_blocker_old_path`：没有经历 R0 提前记账的对照场景，progress/finish/approval/continuation/spawn/plan 路径维持原回归；不将它误用于已提前耗账的下一轮。
- `r0_quota_time_honesty`、`r0_next_turn_quota_boundary`：receipt 提前计入现有 session-local material 账；在已有 quota policy 的临界点，用真实 harness 收据耗账，阻断事务记账后合法解除 blocker，下一 advance 的 should_run/spawn 或 plan prefix 可以等待/零派发。测试可只读现有 quota 函数观察，新增 advance 块不调用/修改它；不伪造 duty_cycle=0、不改策略实现、不声称 PC-4。
- `r0_source_scope`、`r0_no_forward_dependency`：§4 源码保护、无新函数/加载键、stage 32 可独立加载，无 Phase C helper 反向引用。

### 5.2 精确命令清单

以下是 **本计划的十条回归命令**，不是宣称 v13 全仓库 43 个脚本已跑。每条退出码必须实际为 0；plan_arm 在自己的装载前缀运行，goal_supervise 在完整 38-stage 前缀运行：

```bash
UV_FROZEN=1 uv run python v13/plan_contract/test_plan_contract.py
UV_FROZEN=1 uv run python v13/plan_read/test_plan_read.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py
UV_FROZEN=1 uv run python v13/workflow_bind/test_workflow_bind.py
UV_FROZEN=1 uv run python v13/real_chain/test_real_chain.py
UV_FROZEN=1 uv run python v13/workspace_admit/test_workspace_admit.py
UV_FROZEN=1 uv run python v13/workspace_exec/test_workspace_exec.py
UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py
UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py
```

开工先确认这十条命令在未实施 R0 的当前基线环境仍可退出 0。M2 已实跑 `evidence_good_ref`：具名写者为 `v13_artifact_land(uuid,text,jsonb)`，记录在已提交 goal_supervise README；它不是未解决的历史预期非零。若本次环境缺失该写者/扩展而触发旧 gate 的 SystemExit(1)，停止处理环境/根因，不删正例、不吞失败、不将其排除后继续宣称十条全绿。R1 的预期非零项不在这十条命令内。

临时库已存在即拒绝，不 DROP 原库；不使用 `agent_v13_%`；仅 DROP 本次创建的库。保留每条命令的退出码/库名/实际断言数/清理结果；失败也记录真实原因。若环境被共享扩展换装破坏，停止报告，不擅自换装。

### 5.3 提交

规划接受只提交本计划文件（文档提交不冒充运行时 gate）。R0 实现另一个提交，严格按 AGENTS 顺序：十个 gate 全绿 → 新增 R0 矩阵/台账行并更新三个 README → 精确路径 add → staged diff/凭据复查 → commit → push origin main。

矩阵全路径为 `docs/reviews/v13-long-loop-phase-c-conformance-matrix-2026-09-29.md`；台账为 `docs/reviews/v13-long-loop-phase-c-deviation-ledger-2026-09-29.md`。R0 实现行初始 not_run，只有实际 gate 退出 0 后转 exit_0。计划合同的接受不是运行时接受。提交前 `git diff --cached --name-only` 必须精确属于 §4.2，拒绝历史计划、停放草稿、prompt-exports、探针或凭据；M1/M2 历史证据行需逐字保留。Python 测试 fixture/helper 允许新增；禁止的 helper 指运行时 SQL 收据写者，不禁止测试组织代码。

`v13/load.py` 无变更不是漏收尾，而是本计划无新增 SQL 文件/键。任何功能 gate 红即停，不能先提交来消除 stage_bytes 差异。R0 提交不包含任何 M3 草稿。

## 6. R1/M3：明确保留的未决合同，不授予实施通过

**R0 通过只关闭 root ready/claimed 无法付收据这一个停点，不等于 M3 或 Phase C 完成。**

此前候选 `v13.loop_driver.driver.LoopDriver.run_turn(sid, first=False, stop_requested=False, max_serves=1)` 尚不能成为已接受的 M3 入口：

- 返回是 `(word, attempts_used)`，不是单个出口词；max_serves=1 限制最多一次 serve，不保证 advance 只有一次（入口、serve 后 settlement、provider requeue 各可能一次）。
- stopped+stored-failed 入口前检查与这些 advance 分属多个事务。检查后另一连接提交 stop 的竞态仍需同事务根锁证明；不能凭一条提前 return 声称覆盖整个入口。
- Phase A driver 不能无条件调用仅 stage 38 才存在的 `v13_unpaid_harness_turn`，否则 Phase A 单独装载回归断裂。
- quiet、唯一结算者、request_stop、人等待、claimed hold、归档/closeout 及新候选产生的时序需要一套明确的入口合同；不能同 tick 先 wrapper 付旧候选再 run_turn 多次结算，却声称“仅一次”。

**本版不修改 loop_driver，不点名获准 import 的一跳入口，不降低原 `unattended_continuation` 断言。** R1 设计仍需另一个被接受的增补计划；之后才继续 M3 实现。该增补必须包括：

1. 与每次 advance 同事务的根锁下 T0 重读；两连接 stop/advance 交错测试；不得跨 IO 持有事务或锁。
2. Phase A 前缀与完整 Phase C 前缀都可运行的加载合同；精确列出变更的函数、Python 方法、READ_HELPERS 与旧 gate，不用“8 行以内”替代语义证明。
3. 每 tick 唯一结算者、最多一次 IO hop、真实返回形状、依赖显式注入、独立连接 IDLE 证明；不得直接复制 B1 出口机。
4. wrapper 返回后：`skipped_failed` 立即安全返回，零 lease/recover/replan/hop；除此之外同一候选仍在就失败，包括 unknown/cancel/stale，不能把 waiting 视作成功。
5. human ready/claimed/unknown 的返回必须结束 tick且不消费 request_stop；request_stop 不能先执行 hop 再停；hold 不 accept/recover/lease/hop；replan 相对顺序只冻结一处。
6. 新 SQL EXECUTE 权限与 control_operator 身份判定分开证明；本期只有 DB owner/superuser Fake 夹具，不声称产品 operator 可执行。
7. 旧 M3 断言保留，正向 fake_hop 真实落库并被下一 tick 观察；unknown 墙若仍未解必须显式残留，不冒充无人值守完成。

状态用语：R1 的整个 gate **当前是 not_run**（草稿已停放，未实现）；`expected_nonzero` 只描述按旧合同运行无人值守续行项的预期，**不是一条已运行的证据**。假如实际运行有其它真实失败，记录该失败，不能用预期 ASK_USER 覆盖它。

## 7. 允许声称与停止条件

R0 通过后只能声称：单根、DB owner/superuser 确定性夹具下，已完成且合格的 harness 在 root ready/claimed 阻断时可幂等记 receipt，human/workspace 未被绕过派发。**receipt 写入只证明 material 记账，不证明 blocker 解除、goal 可派发、M3 续行成功或 finish 已 closeout。** 仍不能声称产品角色、真实 provider、V11/auto-wake、PC-4、多 goal 公平/并发帽/多日 soak、生产无人值守可用。

若实现需要修改旧 receipt guard/权限/加载次序、改变其它 advance 分支、把 child root 锁混在一起、吞掉意外异常、或扩大允许路径，则停止并更新计划复审。既有 gate 的失败不得通过删除断言、临时先提交、使用假退出码或跳过 hook 消除。

**修订 4 已落实第三轮 R0 附条件接受的全部条款；可提交本计划并按独立里程碑实施 R0。未实现/未跑测试的状态保持不变。R1 没有随着 R0 继承接受。**
