# v13 长循环 Phase D 覆盖矩阵（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-d-plan-2026-09-29.md` §7。状态从 `not_run` 起。只有对应 gate 退出码 0 之后才写 `exit_0`。不设 `real_authorized_exit_0`。本文不是通过证明。Fake 绿不是产品可用。

| 条目 | 目录 | 允许的声称 | 证据指针 | 状态 |
|---|---|---|---|---|
| fair_claim gate | `v13/fair_claim` | 单库多根下 `v13_claim_fair` 能结算；多根公平领用按 in-flight 排序且帽只约束 `v13_claim_fair`。不声称产品角色、真实 provider、多日运行、活体 `v13_claim` 也遵守帽、生产无人值守 | 2026-10-01 `UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py` 退出码 0；库 `ll_fair_claim_16948_7cf862`（跑完已 DROP）；96 checks。断言名按 §7.1；stopped 分叉走 `stopped_root_not_fair_claimed`（enqueue_ok）。gate 在恢复 stannum 0.4.0 pin（dylib+control）后实跑，跑完已恢复 0.5.0 现场。Fake 绿不是产品可用 | exit_0 |
| fair_driver gate | `v13/fair_driver` | 4 根 8 tick soak：成功领用序列 R1、R2、R3、R4、R1；帽内不把第二笔给已 in-flight 的根。不声称多日生产运行、配额窗口、活体 `v13_claim` 遵守帽 | 未跑 | not_run |
