# v13 控制面覆盖矩阵（2026-09-26）

对照 R3 §2 / §6.5 / §7 / §8（含 §8.7、§8.8）与计划 §3.3 / §4.3 / §5.3 / §6.3。状态只记实跑。

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 1 | R3 §2.12 + R3a §6.5 + R3b §7.1 G-ctx10-logical-turn | ✅ | `v13/control/test_control.py` | 无。2026-09-26 `uv run python v13/control/test_control.py` 退出码 0 |
| 2 | G-ctx10-delivery（delivery_kind 盲读 / interaction_kind 拒 / USER_ACTION 矩阵） | ✅ | 同上 | 无 |
| 3 | wait-lexicon（approval 恰一 human；evidence 未满足零新 effect） | ✅ | 同上 | 无 |
| 4 | G-ctx10-wake（四变体、children_terminal P1 拒、重复 advance 一条 satisfied、stale 先于 schema） | ✅ | 同上 | 无 |
| 5 | G-ctx10-spend（finish/progress 计 1；+signal 计 0；同 id 重放不第二扣） | ✅ | 同上 | 超限 repair 归 P4，本期不测 spawn |
| 6 | G-ctx10-approval-payload / G-ctx10-approval-ref | ✅ | 同上 | 无 |
| 7 | G-wall-session-status / G-cancel-does-not-unwall / G-user-message-keeps-wall | ✅ | 同上 | 无 |
| 8 | G-resolve-clears-overlay（human 例外 waiting；G4 replay/renew） | ✅ | 同上 | 无 |
| 9 | G-closeout-unknown-authority（计数拒、重放短路、state_hash 重算） | ✅ | 同上 | 无 |
| 10 | G-wall-no-parent-write | ✅ | 同上 | 无 |
| 11 | 双射触发器真 COMMIT 正负例 | ✅ | 同上 | 无 |
| 12 | 锁序 complete/requeue/renew 无死锁 | ✅ | 同上 | 无 |
| 13 | SET ROLE v13_recall 可读 human/responded、不能 SELECT effects | ✅ | 同上 | 无 |
| 14 | G-steer-frozen-request | ✅ | 同上 | 无 |
| 15 | G-cancel-requeue | ✅ | 同上 | 无 |
| 16 | C4 `{reason}` human 兼容（succeeded、零 human/responded） | ✅ | 同上 | 无 |
| 17 | pg_jsonschema 0.3.4 装上且 draft-07 date-time 探针在安装事务内 | ✅ | `v13/control/v13_control.sql` 安装 DO + 测试首断言 | 无 |
| 18 | stage 1–15 回归 | ✅ | schema / resolve / loop / twophase / envelope / manifest / chunks / recall / characterize / filter / memory / economy / summary / periphery / mgraph，退出码均 0 | 无 |
| 19 | stage 16 `test_mgraph_assembly.py` | ✅ | J3 改为 `len(SQL_LOAD_ORDER) >= 16`（台账 X1）。2026-09-26 重跑退出码 0 | 无 |
| 20 | R3 §8.6 + §8.8 G-spawn-unique-writer | ✅ | `v13/spawn/test_spawn.py` | 无。2026-09-26 退出码 0 |
| 21 | G-open-session-shape | ✅ | 同上 | 无 |
| 22 | G-sql-write-closed | ✅ | 同上 | 无 |
| 23 | G-spawn-fanout（N 或 0；坏形状整批拒、不烧 claim） | ✅ | 同上 | 无。回执形状按 §8.8，不用 §8.2 的 tasks_hash |
| 24 | G-ctx1-spawn（xact 咨询锁；无外部 IO） | ✅ | 同上 | 无 |
| 25 | 双根互不占席位；墙上子仍占席位 | ✅ | 同上 | 无 |
| 26 | 并发 sibling 无超售；spawn 不改父 turn_no | ✅ | 同上 | 无 |
| 27 | children_terminal wake 正负例；缺失/重复 RAISE | ✅ | 同上 | 无 |
| 28 | recover/nudge 幂等；源码含 SKIP LOCKED | ✅ | 同上 | 无 |
| 29 | 收据 children 两态；children_open 拦 cancel | ✅ | 同上 | 无 |
| 30 | v_goal_tree 列序 / 环 / 深度 | ✅ | 同上 | 无 |
| 31 | stage 1–17 回归 | ✅ | schema…control 全部 `test_*.py` 退出码 0。twophase 在去掉 spawn SQL 的 `set_config` 后重跑退出码 0 | 无 |
| 32 | stage 18 `test_spawn.py` | ✅ | 2026-09-26 `uv run python v13/spawn/test_spawn.py` 退出码 0 | 无 |
| 33 | R3c F cancel 扇出序 / 锁序 / 终态零事件 | ✅ | `v13/fanout/test_fanout.py` | 无。锁序是对祖先优先的细化，不是改扇出语义 |
| 34 | G6 required→cancelled；unsupported 粘性吸收；mutating→unknown 且 cancel 不改它 | ✅ | 同上 | 无。ch08 双语言/op_seq 不在本期重跑，不发明新条 |
| 35 | interruptible 三档负例；complete cancelled 条件矩阵 | ✅ | 同上 | 无 |
| 36 | worktree 三目录 + latch + binding + requires_worktree + claim 跳过 + digest 排除 + fork 不继承 | ✅ | 同上 | 无。`artifacts.kind` 无 CHECK，直接用 `worktree_binding` |
| 37 | cancel_pending 轮询；SQL 无 `pg_terminate_backend` | ✅ | 同上 | 无 |
| 38 | stage 19 `test_fanout.py` | ✅ | 2026-09-26 `uv run python v13/fanout/test_fanout.py` 退出码 0 | 无 |
| 39 | stage 1–18 回归 | ✅ | schema…spawn 全部 `test_*.py` 退出码 0 | 无 |
| 40 | G-triage-action-closed | ✅ | `v13/triage/test_triage.py` | 无。CHECK 仍只有 pass 与 reject。计划「六值」记台账 C10，未 ALTER |
| 41 | G-triage-explore-depth | ✅ | 同上 | 无。explore 零子；explore 的 tool/call 不 spawn |
| 42 | G-triage-evidence-hash | ✅ | 同上 | 无。`explore_evidence_hash` 变 → `request_hash` 变 |
| 43 | G-triage-10a-null-tree | ✅ | 同上 | 无。null 树不点火规则 5–6；根上无 Jev 证据不是 SQL-direct |
| 44 | override 打穿预算 → 零 child + human；已探索仍 review → human；fold cap `{reason}` | ✅ | 同上 | 无。`triage_reject` 不进 closeout 逃生名单 |
| 45 | stage 20 `test_triage.py` | ✅ | 2026-09-26 `uv run python v13/triage/test_triage.py` 退出码 0 | 无 |
| 46 | stage 1–19 回归 | ✅ | schema…fanout 全部 `test_*.py` 退出码 0。同轮 stage 20 退出码 0 | 无 |
| 47 | F19 角色通道 EXECUTE 闭包：四函数 × 三角色 has_function_privilege + PUBLIC 负例 + resolve_login/route_login 直连行为烟（is_spawn_tool/occupancy/json_keys/triage_project/needed_judgments）+ recall SET ROLE 烟 + recall 仍拒 SELECT effects + emit 提交期双射（owner 自举） | ✅ | 2026-09-26 `uv run python v13/triage/test_triage.py` 退出码 0（86 PASS） | 无。台账 F19/F20/F22 |
| 48 | 授权热修后 stage 1–20 全量回归 | ✅ | 2026-09-26 schema…triage 全部 `test_*.py` 退出码 0 | 无 |

## Phase A

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 49 | stage 21 D11 cap×tail-gap 豁免（R6 has-event only）+ D12 `worktree/released` 投影（R7 守卫无锁，R7b 并发日程 sessions→latch） | ✅ | 2026-09-27 `uv run python v13/seam/test_seam.py` 退出码 0 | 无。G10 重泵实测 (b) 返回 `waiting`、零写。并发日程不动态验证两条语句规则（只由源码断言钉住）。`repair_cap`/`replan_cap` 仍在冻结的 `v13_triage_fold_reason`，不是第二份谓词 |
| 50 | stage 17–20 回归 | ✅ | 2026-09-27 control / spawn / fanout / triage 四脚本退出码均 0 | 无 |
| 51 | stage 22 D14 catalog 换体（R9 裸名 B′，R10 形态 H，R11 解析层 S，R12 臂 D fail-closed + 臂 E）+ 第四务假 worker | ✅ | 2026-09-27 `uv run python v13/catalog/test_catalog.py` 退出码 0。回归 control/spawn/fanout/triage/seam 退出码均 0 | 真实接线 🟡，不是 R4 关闭。sql 快路 RAISE 仍在函数体；direct 分类先被 `v13_triage_after_route` 改写成 human，动态路径零子、不触发该 RAISE |

## Phase B

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 52 | stage 23 D7 正例：谓词真值表（route/超户空 actor、直接父、终态子仍真）；2 参 cancel 扇出孙 ready effect；6 参与 route 5 参 human 应答；旧 1 参 cancel；4 实参默认 `NULL::jsonb`；非 human 旧 5 参 spawn_owner 与超户同词同 `effect_done`；旧 5 参 release 仍写 `worktree/released` | ✅ | 2026-09-27 `uv run python v13/acl/test_acl.py` 退出码 0（197 checks） | 驱动器未交付。不得写成「F17 已在生产路径生效」 |
| 53 | stage 23 D7 负例：六类文案全等且不含 uuid；6 参缺 effect / spawn_owner 缺 effect 不走 `unknown effect`；human 自答加伪造 actor 键；未授权终态不是 replay；父调孙零写；worker 42501；operator 传 actor 不升行政；COMMIT 并发日程（2 参 cancel + 6 参 human）锁后复验 | ✅ | 同上 | 无。operator 空 actor 缺目标仍是活体 needle（台账 C15） |
| 54 | stage 1–23 回归 | ✅ | 2026-09-27 schema…catalog 全部 `test_*.py` 加 `v13/acl/test_acl.py` 串行退出码均 0（24 脚本，含 mgraph 两脚本） | 无 |
| 55 | stage 24 F8 全有或全无 / 列契约：父观察子一行且列与 sessions/events 一致；无事件 `last_event_seq=-1`；多子序=输入序；行政 NULL 可观察 U 与 P；抗环境噪声；`SET ROLE v13_route` 成功 COMMIT | ✅ | 2026-09-27 `uv run python v13/observe/test_observe.py` 退出码 0（147 checks） | 无 waiter。驱动器未交付 |
| 56 | stage 24 负例：混合/自身/不存在/空/NULL 数组零行不 RAISE，后续 `[C]` 仍一行；重复 `v13: observe duplicate` 与 NULL 元素 `v13: observe id`；F18 先授权再读：未授权 session_log 零行；游标 `<-1` 在谓词前 RAISE 且与已授权同文案；`p_after_seq=max` 零行；−1/NULL 全文；watermark 前移；两次无写字节等价 | ✅ | 同上 | 不 join effects |
| 57 | stage 24 权限：route 真（含 `SET ROLE v13_route` 成功 COMMIT）；PUBLIC/recall/worker/resolve/spawn_owner 假（42501） | ✅ | 同上 | 不授 recall。recall 的 events SELECT 不收回 |
| 58 | stage 1–24 回归 | ✅ | 2026-09-27 schema…observe 全部 `test_*.py` 串行退出码均 0（25 脚本，含 mgraph 两脚本） | 无 |
| 59 | stage 25 先授权再写 / 身份去重：四键收据与返回逐字相等；`source_effect_id` NULL；NULL cutoff 取最新非 handoff seq；重复 NULL 同 delivery 事件数 1；新事件后第二 delivery；显式旧 cutoff 返第一份；双连接同 snapshot 堵锁醒后同 payload；`SET ROLE v13_route` 真 COMMIT；终态会话可交接且 `session/completed` 进 hash；独立规范字节式重算，不调 helper 自证；`state_hash` 首写变、重放不变 | ✅ | 2026-09-27 `uv run python v13/handoff/test_handoff.py` 退出码 0（240 checks） | 无 XML。不 fork。前缀窗口不是源尾窗（台账 F30） |
| 60 | stage 25 负例：未授权（含非法 cutoff / 禁用策略）只得 `v13: session not found`；空会话 NULL→`handoff empty`、显式 0→`handoff watermark`；守卫属主直插：1.5 / 1.0 / 溢出不泄 22003 / 缺键多键 / schema 字符串 / 非 canonical delivery / 非 64hex / hash 不符 / source 非空；route 直插 `handoff writer`；两索引正交 23505 约束名；策略 disabled / 零 active / 形状错；回读先于策略 | ✅ | 同上 | 物理 DELETE 策略行不测（冻结触发器）。route→emit 直调=受信 helper（台账 F31） |
| 61 | stage 25 F19 属主自举与 Phase B 六动词：安装后 aclexplode 直接 ACL（含 schema CREATE、`digest(text,text)`、`gen_random_uuid`）；emit DEFINER 属主、其余 INVOKER；`blocked_unknown` 上 owner emit COMMIT 墙未 RAISE；`SET ROLE v13_route` 走通 observe / session_log / user/message 注入 / 6 参 complete / 2 参 cancel / authorized / extract 并 COMMIT | ✅ | 同上。六动词结果：observe=ok log=ok inject=ok respond=ok cancel=ok authorized=ok extract=ok | 驱动器未交付。R4:23 非生命周期收据澄清记台账 C16 |
| 62 | stage 1–25 回归 | ✅ | 2026-09-27 schema…handoff 全部 `test_*.py` 串行退出码均 0（26 脚本，含 mgraph 两脚本） | 无 |

## Phase C

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 63 | stage 26 直接调用真/假与 duty shadow：ready 会话 gate NULL；ready human → `human_pending`；`blocked_unknown`/unknown effect → `unknown_wall`；未消费 cancel → `unconsumed_cancel`；duty=0 默认种子仍 NULL；改序不改函数 oid；坏尾仍 `v13: should_run gate` | ✅ | 2026-09-27 `uv run python v13/should_run/test_should_run.py` 退出码 0（194 checks） | 无。驱动器未交付 |
| 64 | cancel 前缀高于投影：duty block 且 duty=0 时未消费 cancel 仍 `'terminal'`/`cancelled` | ✅ | 同上 | 无 |
| 65 | spawn 读点：duty shadow 仍 `'progressed'`；duty block 返回 `'waiting'`、零新 effect、无 `triage/hold`、tool/call 留置；explore 假路径仍 `v13: explore spawn` | ✅ | 同上 | 无 |
| 66 | finish closeout 不被门吞：duty block 且 duty=0 时 harness finish 仍 `'terminal'`/`completed` | ✅ | 同上 | 无 |
| 67 | 投影零写入；GRANT 只给 `v13_route`；`v13_policy_share` DEFINER 五行锁；审计负臂 duty=0 不预写 `resolve/failed`；parent 不变由既有 `trg_sessions_fork_cols_immutable` 执法 | ✅ | 同上 | 正臂行为在 stage 27（源码在场≠通过）。不另装 parent 守卫 |
| 68 | stage 1–26 回归 | ✅ | 2026-09-27 schema…should_run 全部 `test_*.py` 串行退出码均 0（27 脚本，含 mgraph 两脚本） | 无 |
| 69 | stage 27 窗内计次、allowed=0、slot 间隔、不跨会话、不沿树；松种子不是产品额度 | ✅ | 2026-09-27 `uv run python v13/quota_window/test_quota_window.py` 退出码 0（226 checks） | 松种子不是「已配置 24 小时 8 次」（台账 PC-3）。计次不沿树（PC-4） |
| 70 | 能力差、human_reward 不改已判行、finish 仍结算、索引、GRANT 只给 `v13_route` | ✅ | 同上 | 触发器函数只 REVOKE PUBLIC，不 GRANT |
| 71 | 小题⑥正臂：quota 与 capability 门假、前缀三门不早退、duty<>0、snap.failed 非空 → 先 append `resolve/failed` 再 waiting、零新 effect、无 `triage/hold`；material 时间诚实七臂 | ✅ | 同上 | 源码在场≠正臂通过。本行是行为实测 |
| 72 | stage 1–27 回归 | ✅ | 2026-09-27 schema…quota_window 全部 `test_*.py` 串行退出码均 0（28 脚本，含 mgraph 两脚本） | 无 |
| 73 | stage 28 秩：human 阻塞先于可跑，终态沉底；同层 `session_id` 升序；`attention_rank` 不落列；双调用字节相同且零事件 | ✅ | 2026-09-27 `uv run python v13/attention/test_attention.py` 退出码 0（156 checks） | 秩是注意力不是调度（台账 PC-6）。返回行数预算不保树遍历 |
| 74 | hint 闭集 `run_now`/`wait`/`dont_notify`：duty=0 且无 cancel → `wait` 且不写 hold；未消费 cancel 无 claimed/unknown → `run_now`；在途+坏策略仍 `wait`；fanout/depth/cap 超限 → `wait`，满树无 tool/call 仍 `run_now`；终态 `dont_notify` | ✅ | 同上 | hint 不是 ack，不注册 cron（PC-5） |
| 75 | 双调用 `next_seq` 不变、无 `scheduler_ack`、无新 events；`cron.job` 不存在则跳过；hint 之后翻 `allowed=0`，advance 仍 `waiting` 且零新 effect | ✅ | 同上 | 禁止写成「pg_cron 已在生产调度」 |
| 76 | GRANT 只给 `v13_route`；snapshot route 可执行，worker/PUBLIC/recall/resolve/spawn_owner 不可且 `provolatile=s`；大树 501 行成功并记录耗时、不断言阈值 | ✅ | 同上。501 行约 96ms | spawn_owner 的 snapshot 授权留 stage 29 |
| 77 | stage 1–28 回归 | ✅ | 2026-09-27 schema…attention 全部 `test_*.py` 串行退出码均 0（29 脚本，含 mgraph 两脚本） | 无 |
| 78 | stage 29 指纹方向：无排除事件时 `v13_goal_fingerprint` = `v13_state_hash`；仅 `session/*` 仍相等；五类独有排除必不等；stop 改变 state_hash、不改变 fingerprint | ✅ | 2026-09-27 `uv run python v13/govern/test_govern.py` 退出码 0（228 checks） | 不换体 `v13_state_hash`（台账 PC-7） |
| 79 | 转移与授权：重复 stop / 过早 resume / 终态 → `v13: goal lifecycle`；漂移 → `v13: goal fingerprint`；在途 → `v13: goal busy`（终态先于 busy）；非 operator → `v13: session not found`；`SET ROLE v13_route` 真 COMMIT；stop 不改 status | ✅ | 同上 | 无 UI。禁止写成「目标已可在 UI 停复」 |
| 80 | stop 后 recover 零 nudge；cancel 仍 closeout `'terminal'`；duty=0 未停时 recover 跳过不变；stopped 不写 `triage/hold` | ✅ | 同上 | 停 ≠ `duty_cycle=0` |
| 81 | 到顶批量路径 `'waiting'`、tool/call 留置、无 `spawn_fanout`；直调仍 `v13: spawn budget cap`；fanout/depth 同翻转且直调仍 RAISE；explore 到顶仍 `v13: explore spawn`；复活窗口捕获 cap RAISE 且不被吞成 waiting | ✅ | 同上 | 无并发复活且非 explore 时不 RAISE。复活窗口不承诺零 RAISE 或绝对不超售（台账 PC-8） |
| 82 | handoff 回归：未停 extract 成功；`enabled=false` → `v13: handoff disabled`；零 active → `v13: handoff policy`；同身份重放返回原载荷；stop 不增加 handoff 行；NULL cutoff 的 hash 与 delivery 在 stop 后变化（`goal/*` 不进 transcript 排除名单） | ✅ | 同上。stage 25 `v13/handoff/test_handoff.py` 回归退出码 0（240 checks） | 不新写门。驱动器未交付 |
| 83 | 折叠只在 `v13_goal_fold`；`v13_goal_lifecycle` 薄包装；空会话 `running` 非 NULL；attention 增 `lifecycle` 列，stopped 行 `blocked_by=goal_stopped` 且秩先于 quota 兄弟 | ✅ | 同上 | 索引 `ix_events_goal_lifecycle` 非 UNIQUE |
| 84 | stage 29 `test_govern.py` | ✅ | 2026-09-27 `uv run python v13/govern/test_govern.py` 退出码 0（228 checks） | RED 基线记 `v13/govern/README.md`（HEAD `8678ebf`，`v13: spawn budget cap`） |
| 85 | stage 1–29 回归 | ✅ | 2026-09-27 schema…govern 全部 `test_*.py` 串行退出码均 0（30 脚本，含 mgraph 两脚本） | 无 |

## Stage 40

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 86 | 旧 Stage 40 `agentctl_observe` | P1 退役 | 旧 `v13/agentctl` 已删除；不作为 ce_run 证据 | 不保留旧实现通过证明；由单一 Stage 40 `ce_run` 收口 |

## Stage 41

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 87 | 旧 Stage 41 agentctl 写动词/controller | P1 退役 | 旧 `v13/agentctl_verbs` 已删除；不作为 ce_run 证据 | 不保留旧实现通过证明；`steer/respond/cancel` 由 ce_run 新入口重新验证 |

## Stage 42

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 88 | 旧 Stage 42 `goal_workflow` | P1 退役 | 旧 `v13/goal_workflow` 已删除；不作为 ce_run 证据 | 不保留 workflow/无人值守等价性结论 |

## Stage 43

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 89 | 旧 Stage 43 `external_exec` | P1 退役 | 旧 `v13/external_exec` 已删除；不作为 ce_run 证据 | 不保留 external executor/task lease 等价性结论 |

## Stage 44

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 90 | 旧 Stage 44 `ce_map` | P1 退役 | 旧 `v13/ce_map` 已删除；不作为 ce_run 证据 | 不保留静态映射等价性结论 |

## Stage 40 freeze amendment

The dirty-tree compatibility exception is validator-only: exact named path exclusions plus body-only comparison for the four pinned guard files. Signatures/decorators, module comments, unrelated functions, SQL, setup, and runtime assertions remain frozen; negative mutation evidence is required. Baseline commit/parent evidence and the explicit `protected_dirty` rationale are in plan §10.8. This amendment is not a Stage 40 gate result.

Legacy validation logs: `prompt-exports/stage40-final-*.log`. Eleven affected legacy scripts completed after the final validator edit; CE validation is pending independent runtime-review corrections and is not claimed here.

## Controller thin cut

| # | 条文 | 状态 | 测试落点 | 缺口 |
|---|---|---|---|---|
| 91 | Controller thin cut | P1 退役 | `v13/loop_driver/controller.py` 与 vertical test 已删除；不作为 ce_run 证据 | 不保留旧 controller 六词或多入口等价性结论 |

## Stage 40 (`ce_run`, 新实现)

**最新实跑（2026-10-17，v99 预提交全绿）：** 全部 47 条保留脚本独立顺序执行 exit 0，goal_supervisor 两探针按契约 exit 1（ask_user 拒绝尾部）/exit 2（建库前 usage）；CE 16/16 组、665 检查、零独立失败；read_tools 首次真跑 duck 面与 E4 嵌套全量。环境、两次阻断尝试（PiSwift pull 漂移经用户裁决回滚至 bfccb32；duck 钉版扩展经 duck_bringup 落地）与完整证据见偏差台账 S40-21/S40-22 与计划 §2.4、`prompt-exports/w4-v99-precommit-20261017/`。下表 16 组行与逐组计数保留历史口径（最新为 665 检查）。提交后净树复验两次首红：先 pi_parity historical_frozen（§10.12 缺口，台账 S40-24），修复提交后 read_tools E4 嵌套连环红（piswift driver settled 竞态，§10.13，台账 S40-25）；两次均按 §8.1.6 修正后重跑。

**历史阻塞记录（2026-10-17，已被上述 v99 全绿覆盖，不抹去）：** 最终工作树与隔离副本逐文件 SHA-256 相等；完整 47 条清单顺序执行前 7 条 exit 0，CE 实际 16/16 组、665 检查；第 8 条 economy H1 `out_a == 'accepted'` exit 1，余下 39 条及 goal-supervisor 三模式未运行。原失败未打印 receipt；单次独立诊断又在观察器错误函数签名查询处失败，未捕获 receipt，根因未明。只读版本检查不是 gate。新的完整命令/输出与冻结基线：`prompt-exports/w4-final-precommit-20261017/`；诊断及全部路径：`prompt-exports/w4-economy-h1-handoff-20261017.md`。下表的旧检查数保留历史，不代表最终 665 检查的逐组计数；新 CE 各组原始输出以 `04-v13-ce_run-test_ce_run.log` 为准。没有全量/最终 nested trace/goal-supervisor 验收，也未达集成 Oracle review、提交或推送条件。

以下是计划 §8.2 的 16 组具名覆盖映射；maintenance 包装并入第 10、11、13 组。2026-10-17 第 7 轮 `UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py` 实跑 exit 0，16/16 组、517 断言，采用权威旧 epoch reactivation wake 期望 `[1,1,1,2]`。第 5/6 轮及顺序回归中的 CE 行采用错误期望，原始输出保留但不计有效验收。**仅新 gate 通过，完整里程碑仍阻塞**：47 条回归在第 11 条 fair_driver `test_stage_bytes:222` exit 1（78432/926 diff bytes）后停止，剩余 36 条未运行，不据历史结果补算通过。证据：`prompt-exports/w4-ce-run-actual-results-2026-10-17.md`。第 1–16 组检查数依次为 `48/3/3/48/7/37/16/31/36/90/23/34/31/66/26/18`。

| 探针 | 覆盖范围 | 状态 | 证据/缺口 |
|---|---|---|---|
| 1 `native_load_untouched` | Stage 1–39 字节、函数/表/ACL 基线与 ce_run 前后差异 | 新 gate 通过 | 48 检查；仅精确 R0 例外，不扩大冻结豁免 |
| 2 `native_plan_arm_closed_set` | 四文件闭集、缺失/extra.py/越界 stage 负例 | 新 gate 通过 | 第 7 轮实际通过；各组检查数见本节首段 |
| 3 `native_frozen_driver_bytes` | R1 sentinel、哨兵外 base 字节、无 controller/第二 advance | 新 gate 通过 | 第 7 轮实际通过；各组检查数见本节首段 |
| 4 `native_start_identity` | 12 入口中的 start 身份、私有 helper、parent/next_seq−1 cutoff、并发 request 与异常回滚 | 新 gate 通过 | 48 检查；真实 parent cutoff/双连接/非超级用户 |
| 5 `native_poll_pure` | READ ONLY、零 revision/wake 写、expired 授权边界 | 新 gate 通过 | 第 7 轮实际通过；各组检查数见本节首段 |
| 6 `native_wait_cursor` | 八键、steering 优先、epoch 追踪、每 waiter 游标、通知丢失重读；self-origin 仅隐藏 `snapshot.steering_message` 正文仍返回 interrupted/wake 游标 | 新 gate 通过 | 37 检查；wake 期望 `[1,1,1,2]`；`superseded` 仅 reserved 夹具 |
| 7 `native_cancel_scope` | 单 run cancel、同步 sessions/CE、追加严格格式的本 session `session/cancelled` 与 `cancel/requested` 事件、由独立 CE 审计事件持久化真实 actor/request、claimed late receipt、子 run 不受影响 | 新 gate 通过 | 16 检查；这是 CE/session 控制结算，不终止事务外 claimed provider；不调用旧 `v13_cancel` 子树语义 |
| 8 `native_steer_paths` | active queued steer、旧 ready/claimed driving 归档、terminal 复活/CAS/use_respond | 新 gate 通过 | 31 检查；旧 ready/claimed 真实结算与复活 |
| 9 `native_respond_once` | human/CE interaction、one-of、一次消费、两通道续跑 | 新 gate 通过 | 第 7 轮实际通过；各组检查数见本节首段 |
| 10 `native_acl_roles` | route/recall/worker/operator、SET ROLE、TEMP/public CREATE、helper owner 例外；maintenance route-only 非超级用户 ACL | 新 gate 通过 | 90 检查；四类真实 LOGIN/SET ROLE/maintenance ACL |
| 11 `native_io_boundary` | T1/claim/T2 IDLE、scoped discovery/claim、queued promotion、maintenance 全库短事务 requeue 边界 | 新 gate 通过 | 23 检查；不证明多 worker 接管 |
| 12 `native_receipt_fences` | request/replay/stale、两种锁交错、accept 前崩溃导致全 T2 回滚 | 新 gate 通过 | 34 检查；真实阻塞屏障、全 T2 回滚、丢 COMMIT 回应重放 |
| 13 `native_unknown_vs_archive` | late known receipt、tokens 失配、unknown wall、各 enqueue 阻断；维护回收后的 unknown 墙 | 新 gate 通过 | 31 检查；真实租约回收/unknown 回执；unknown 无 CE 恢复 |
| 14 `native_operation_handoff` | 同 epoch 多 operation、工具闭集/schema、孤儿 tool 投影、Fake spawn 不建 session | 新 gate 通过 | 66 检查；缺键/schema/envelope/来源/index/id 与原样 task |
| 15 `native_snapshot_once` | publication replay/CAS、interaction_pending、精确 respond/instruction 消费 | 新 gate 通过 | 26 检查；新 publication 不得覆盖 interaction |
| 16 `native_static_setup` | Fake-only、无网络/pg_sleep、库名/OID cleanup、创建失败不误删 | 新 gate 通过 | 18 检查；精确 name/OID 生命周期与 import-safe |

## Stage 41 (registry, 新实现)

2026-10-18 预提交最终完整顺序回归：48 脚本 exit 0，goal_supervisor
`--unattended-continuation` exit 1（ask_user 拒绝尾部）、`bad-args` exit 2
（建库前仅 usage），共 50 项全部符合预期。每项独立执行
`UV_FROZEN=1 uv run python <path> [args]`，逐条恢复 parity trace。
完整路径/命令/退出码见 `v13/registry/README.md`；原始记录为
`prompt-exports/w4-registry-precommit4-p1-20261018/results.json`。
P1 修复后 registry 独立 gate 与 E4 嵌套均 exit 0、16/16、481 checks、零独立
用例失败；字符串入口真实身份八项全绿；CE 665、plan_arm 104、fair_claim 137、
goal_supervisor 74。read_tools exit 0。上一轮 precommit3（473 checks）仅为
修复前历史证据；提交后同清单净树复验/推送尚待执行，不预填结果。

下表按落地计划 §9.2 全 16 探针逐项映射设计 §11 第 3 项（§11.3）接受断言。
“补充”表示 §11.3 没有独立对应断言，明确列出权威落点，不冒称直接覆盖。
检查数为本次独立 registry 日志的具名组计数，不含其调用的内部自证断言计数。

| §9.2 探针 | checks / 实跑 | 设计 §11.3 断言映射 | 证据边界/缺口 |
|---|---|---|---|
| 1 `native_load_untouched` | 49 / PASS | 纯增量、零既有对象改动、loader 尾追加；ACL 矩阵 | Stage 1–39 与 CE SQL/setup/README 字节钉；CE test 仅 loader-tail hunk；三表/八函数/零序列 delta，既有对象/角色/ACL 不变 |
| 2 `native_plan_arm_closed_set` | 3 / PASS | 纯增量边界；闭集负例为计划 §5.3/§9.2 补充 | 执行真实闭集及缺文件/extra.py/未来尾/重复/连续性负例；Oracle registry 四文件例外的 13 纯内存案例随 r1 校验执行 |
| 3 `native_register_happy` | 9 / PASS | 时钟单调，仅成功分配 +1 | 三 kind 四键返回；触发器夹具验证事件/clock/meta 先于行；meta 对事件 max revision 对账 |
| 4 `native_retire_no_gap` | 4 / PASS | retire 唯一 UPDATE、同事务 register+retire 无空档 | 两事件 revision 恰差 1，严格半开区间，from 可见/to 不见 |
| 5 `native_already_live_not_live` | 12 / PASS | 两结构化零写且时钟不动 | 重复调用精确返回身份/键；clock/meta/行/事件/session fingerprint 全等 |
| 6 `native_frozen_matrix` | 21 / PASS | frozen 全列名单（含 registration_id）、退役唯一 UPDATE | 八不可变列、DELETE、NULL/重复/倒退退役均拒；宿主拒直接 UPDATE，属主运维退役可达 |
| 7 `native_one_live_concurrency` | 4 / PASS | at-most-one live、成功调用才推进时钟 | 双连接真实阻塞屏障，一胜一 already_live，仅一 revision；23505 唯一索引背板 |
| 8 `native_chain` | 6 / PASS | chain 环截断与 depth cap | 根/叶→根、32/33 深链实跑；环分支仅源码 path guard 静态证明，未伪造不可达环，运行时环覆盖为明确缺口 |
| 9 `native_context_determinism` | 30 / PASS | 两独立连接同 (scope,rev) 逐字节/hash 等 | 近端遮蔽、排序/provenance；后续祖先注册不改旧 child bytes，live 可见；不依赖诊断 meta |
| 10 `native_as_of_boundaries` | 12 / PASS | as_of 边界、p_rev <0/=0/>clock 三边界、revision 0 空面 | N-1/N/M-1/M；负数 RAISE、零面但 tools 当前、未来值钳制到 current bytes |
| 11 `native_unresolved` | 16 / PASS | unresolved 不 RAISE | 缺依赖/传递缺依赖/依赖环/补齐与排序；hash 入参单改 unresolved 即变 hash，原 A/B 行不变 |
| 12 `native_value_shape` | 135 / PASS | §11.3 无独立 shape 条目；补充设计 §4.5 与计划 §9.2 | 全负例/1 MiB/非 service depends_on/上限正例；拒绝前后全状态相等 |
| 13 `native_acl_roles` | 130 / PASS | route 写、recall+route 读、resolve/PUBLIC 拒、clock 零角色；规范空形 vs 已知空形 | 真实 LOGIN/SET ROLE、表 DML/SELECT、全部函数 resolve 42501；actor self/parent/越界分支、十键逐键比较 |
| 14 `native_events_and_probe` | 8 / PASS | §11.3 无独立事件/probe 条目；补充设计 §4.2 与计划 §6.3/§9.2 | 精确 type/payload/scope/NULL source；两 stale fence 前移、其余五键不变；不跑 advance |
| 15 `native_static_setup` | 31 / PASS | §11.3 无独立生命周期条目；补充计划 §9.2 与设计 §4.2 种子纪律 | 四 wrapper 字符串入口真实临时身份、默认 route、None=owner、显式 plain 直通、缺 server 精确文案（closing+idle、只查身份）；import-safe/无网络无 sleep、name/OID/失败不误删/cleanup 保留原异常、种子缺失写读 RAISE；profile 静态注释不是消费能力 |
| 16 `native_tools_revision` | 11 / PASS | p_rev=0 注册空面但 tools 当前；补充设计 §4.4 双 fence | enabled/disabled 六键原样输出；旧 rev 仍见新 tools，tools_revision/hash 同步变化；不证明历史 tools 时间轴 |

验收边界：默认 parity exit 0，但 node_modules plane 报 toolchain_absent skip；
未要求/未启用 PI_PARITY_REQUIRE_ALL，不宣称 strict/all-plane 通过。设计 §11.4
worker-parity、§11.5 消费侧 claim 加键/advance 第八键/双标量强制钉版/superseded
均为后续提案，不属于本阶段运行时覆盖。首次第 16 项 cached-only 首红与第二次
第 17 项 runner 尾部误判保留在 README/台账，不把中止序列拼成全绿。

## Stage 42 (registry Phase 2, 新实现)

当前结论（2026-10-19，S42R-11）：W5/W6 测试/文档验收 PASS；离线隔离完整
51 项全部符合契约，逐项 trace restore。下方 RED 为保留的历史尝试，最新 receipt
与覆盖结果见本节末。未暂存/提交/推送，未做 post-commit 净树复验。

本节不覆盖旧 Stage 42 goal_workflow 退役行。计划
`docs/plans/v13-registry-phase2-2026-10-18.md` §5 的 15 个验收面由独立
`v13/registry/test_consumer.py` 承载；具名测试函数与 gate 标签对照如下。
2026-10-19 独立 consumer 实跑 exit 0、289 checks
（`/tmp/v99-consumer-final.log`），独立 registry exit 0、16/16 groups、485
checks、零 independent_case_failures（`/tmp/v99-registry-final2.log`）。
完整 51 项序列结果在本节末另列，不以独立运行或旧 Stage 41 结果补算。

| 计划 §5 gate | 状态 | 实际测试落点与证据 | 边界/缺口 |
|---|---|---|---|
| `native_claim_pin` | PASS | `native_claim_complete`：global 六键、fair SEVEN、CAS/pin、失败零 pin、触发器失败 rollback、缺 seed P0001 | fair prefix gate 仍装 Stage 39/SIX，见 S42R-6 |
| `native_worker_protocol` | PASS | 同名函数：route/global 与 owner/fair 两线，exact lookup/context、三元 cache、registry/tools writer 提交后 rollback、IDLE Fake IO、另事务 strict completion | 协议验收，不是新生产 worker；不调用网络/provider |
| `native_strict_complete` | PASS | `native_claim_complete`：accepted/replay/token stale、NULL/负数 22023、missing P0001、revision stale、旧 pin 仍 accepted | token 检查优先，不用当前 clock 拒绝已领取结算 |
| `native_legacy_complete` | PASS | `native_claim_complete`：旧五/六参、unpinned、pinned legacy mapping；既有 CE gate 独立回归 | CE 七键与无 pin 平行面保持，不声称 CE registry generation 集成 |
| `native_event_pin_atomicity` | PASS | 同名函数：mapping 失败恢复 effect/events/next_seq，duplicate/immutable、reclaim exact attempt/fence、missing/malformed false；payload guards 负例 | fault injection 在隔离库事务内 rollback，不改生产 guard |
| `native_route_projection` | PASS | `native_w4_projection`、`native_plan_signal_evidence`：current llm finish；superseded llm/tool result 不驱动；origin_user_seq 过滤 | current tool result 仍不直接 finish，保持既有 route 语义 |
| `native_tool_call_projection` | PASS | `native_w4_tool_parse`、`native_actual_tool_spawn`：current 实建 child/spawn succeeded/child-created，旧 call 零 child、不计 scheduler/triage；legacy 保留 | spawn_owner 实际 canonical 链执行，非只有 ACL 元数据 |
| `native_repair_replan_projection` | PASS | `native_w4_control`、`native_plan_signal_evidence`：current continuation/material/cap/seam/fold/closeout/recover，superseded 无驱动；frontier synthetic 保留 | loaded pg_proc 检查有效定义，不以被覆盖源码代替 |
| `native_human_cap_projection` | PASS | `native_w4_human`：current 释放 cap、旧 response 不释放；精确六键名字和值 | human payload 未新增 revision/anchor |
| `native_parse_closeout` | PASS | `native_w4_tool_parse`、`native_w4_control`：旧 resolve failure 不耗 retry；无 source synthetic 仍计；旧 receipt 不阻终态 | append-only 审计不删除 |
| `native_global_freshness` | PASS | `native_freshness`、`native_statement_snapshot`：unrelated register/retire、tools 双 fences、meta 诊断、judge effect identity 不变 | 接受全局 blast radius；tools 无历史轴 |
| `native_envelope_snapshot_consistency` | PASS | `native_freshness`、`native_statement_snapshot`：21-key/eight-key、advance stale、MATERIALIZED 双连接屏障、延后 snap 投影旧双标量、下一语句读新双标量 | 不声称跨事务共用物理 snapshot |
| `native_acl` | PASS | `native_claim_complete`、`native_acl_closure`：全部宿主表/列零权、global/fair/strict/context 正反例、recall 和 spawn_owner canonical 实调 | S42R-1/2 仅补 event_current；effect_current/pin 表不授 recall/spawn_owner |
| `native_lock_barriers` | PASS | 同名函数：准确 PID + pg_blocking_pids + pg_locks；writer clock/session 等待时别 scope claim 可提交；completion session/effect；fair advisory/root/child/effect NOWAIT 零半写 | 不用 sleep 推断；govern query-text 观察另作精确 PID 修正 |
| `native_overlay_static` | PASS | `native_acl_closure` 与 setup validators：prefix/前 39/loader 41/CE、两表/11 新签名/21 replacement 闭集；roles/seq/DB/schema/function/table ACL 和 columns/indexes/constraints/triggers mutation 负例 | prefix hash `e5222e1499001f3a734292d8456d2b431fcfcd2a5862952bfcc38137caee34d4`；无新 loader stage |

Oracle findings 已逐项核对：actual catalog 不复现 qualification 拒装，superseded
fixture 已 pinned 并单列 legacy；实际 spawn_owner、human 六键、function_acl
mutation 已执行。fair 前缀 SIX/overlay SEVEN 的安装范围差异与窄 ACL 决策见
台账 S42R-1–S42R-8。协调交接限定收尾 agent 本轮不 commit/push，未提供 post-commit receipt。

### 历史 51 项顺序尝试：RED（2026-10-19）

goal_supervisor frozen 路径精确适配后，从 #1 执行最后一次完整清单。
#1–29 均符合契约：27 项 exit 0；#17 unattended exit 1、FAIL/ask_user
尾部符合预期；#18 bad-args exit 2、建库前 usage 符合预期。
#16 goal_supervisor 74 checks、#19 govern 228 checks 均 exit 0，没有观察到
二者真实冲突。#30 pi_parity 在 480.16 秒后 exit 1，非超时：外部 PiSwift
HEAD `a73c391ce1d891b7b6f8f37a8508f184a31703e3` 与冻结 driver 的
`createAgentSession` throws / `toolExecutionEnd` 四元组合同不兼容。
按首红即停和用户不再开新轮要求，#31–51 均未运行，未修改外部依赖或 driver。

全部 51 项逐项实际退出码/未运行状态见 `v13/registry/README.md` 的
“Phase 2 Final Sequence Result”；原始 30 项 receipt 为
`prompt-exports/w5-phase2-final-20261019/results.json`，同目录保存 manifest、
HEAD 和逐项日志。30 项均 `trace_restored=true`，pg.jsonl SHA-256 为
`3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`、
mode 0644，tracked traces 无 diff。上表 PASS 仅代表独立 consumer 289 的
覆盖结果；独立 registry 485 也不补算为最终序列 #39/#51 通过。
**W5/W6 完整验收未完成，提交前条件不满足。** 文档已据实收尾；无暂存、
提交、推送或净树复验。外部编译阻塞记录于 S42R-9。

2026-10-19 后续兼容预验证仍 RED（S42R-10）：找到保留 tag
`v0.87.1/bfccb32` 与历史冻结 API 相符，创建独立 detached worktree，
未切换活动 PiSwift main。用 ignored 工具 PATH wrapper + Swift
`--package-path` 构建临时 package（Sources 字节相同，仅副本依赖路径变更）。
parity exit 1：SwiftPM 更新 MacPaw/OpenAI 时 GitHub TLS 连接失败，尚未证明
旧版本 driver 编译/运行通过。按用户任一非预期失败即停，ports 未运行，新的
51 项序列未启动。trace bytes/mode 已恢复；活动 HEAD/status、独立 worktree
及冻结源码/manifest 未变，证据在 `prompt-exports/w5-piswift-compat/` 的
preflight-results/environment-before/environment-after JSON 和日志。
不覆盖或拼接先前结果，不把静态 API 兼容推断计为 gate PASS；当时 W5/W6 仍未完成。

### 最新离线隔离 51 项顺序验收：PASS（2026-10-19）

用户随后要求继续离线缓存调查。旧 tag Package.resolved 的 25 pins 有本地缓存，
OpenAI 固定提交 `4ed3ea99ff9dfd2a760509ddb31020f4b153ef93` 在活动 checkout
与裸库均存在；pg-agent 两个既有构建缓存已足够。锁文件复制到 ignored package
副本，使用 `--disable-automatic-resolution --skip-update` 后 release build exit 0，
472.93 秒；parity → ports 独立预验证均 exit 0，trace 均恢复。

随后同一隔离环境从 #1 串行执行原 50 + consumer：**51/51 符合契约**，
49 项 exit 0，#17 unattended exit 1（FAIL/ask_user），#18 bad-args exit 2
（建库前 usage），runner exit 0。全部逐项退出码见 README “Offline Isolation
Acceptance”，原始证据 `prompt-exports/w5-phase2-offline51-20261019/results.json`
含 51 条执行记录；同目录 manifest/head/51 份日志，总 item 用时 951.81 秒。
51 项均 valid/trace_restored=true，同一 trace SHA-256/0644 且无 tracked diff。
这是独立完整序列，不补算旧首红或独立运行。

本序列 #39 registry：16/16 groups、485 checks、零 independent failures；
#51 consumer：289 checks，覆盖本节全部 15 个计划 §5 验收面；#19 govern 228、
#16 goal_supervisor 74、#32 plan_arm 104、CE 665、fair_claim 137 均通过。
#36 read_tools E4 在 487.54 秒后 exit 0，含嵌套 registry/parity/ports。
真实锁序屏障、event 原子/畸形、actual spawn 和双连接 snapshot 没有遗留测试红项；
goal_supervisor frozen 入口与 govern 精确观察修正无冲突。

隔离重现步骤与工具路径见 registry README。活动 PiSwift clean main/a73c391、
旧 detached v0.87.1/bfccb32 worktree clean，原 frozen Sources/manifest hash 不变，
见 `prompt-exports/w5-piswift-compat/environment-before.json`、`environment-after.json`、
`swift-invocations.jsonl` 与 `offline-results.json`。默认 parity 仍跳过 node_modules
缺失平面，未启用 PI_PARITY_REQUIRE_ALL；不声称 all-plane 或真实 provider 验证。
Oracle 已读处置沿用上文，无新 review、无新增运行时 scope。

W5/W6 测试与文档前置条件已满足；收尾 agent 不暂存/提交/推送。父协调会话
get_log 已核对，原话是协调 agent 对收尾 agent 的权限边界，不是用户全局覆盖，
来源与职责已更正于计划 §7。父协调 agent review 后负责路径/凭据暂存审查、提交、
提交后净树复验及 v99 推送；AGENTS 全任务要求仍有效，不宣称已提交里程碑。
