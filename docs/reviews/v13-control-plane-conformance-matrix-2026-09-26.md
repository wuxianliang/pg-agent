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
