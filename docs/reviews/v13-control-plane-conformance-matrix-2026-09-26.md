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
