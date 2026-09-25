# v13 控制面覆盖矩阵（2026-09-26）

对照 R3 §2 / §6.5 / §7 与计划 §3.3。状态只记实跑。P2–P4 不在本期。

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
