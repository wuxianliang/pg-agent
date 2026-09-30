# v13 长循环 Phase C 覆盖矩阵（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md` §7。状态从 `not_run` 起。只有对应 gate 退出码 0 之后才写 `exit_0`。不设 `real_authorized_exit_0`。本文不是通过证明。Fake 绿不是产品可用。

| 条目 | 目录 | 允许的声称 | 证据指针 | 状态 |
|---|---|---|---|---|
| frontier_gap gate | `v13/frontier_gap` | B4 投影与插入、D3 与哈希句同一 gate。载荷键恰好 `schema_version`。实现闭集只有 `dangling_link`（写者拒绝空 successor）。没有伪造配额账。不声称产品角色，不声称无人值守，不替换 `v13_advance` | `UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py` 退出码 0；库 `ll_frontier_gap_37578_0f732d`（跑完已 DROP）；58 checks。断言名按 §7.1。同窗口回归均退出码 0：`plan_contract` 93（`ll_plan_contract_37955`）、`plan_read` 11（`ll_plan_read_38082`）、`plan_arm` 43、`loop_driver` 55、`workflow_bind` 8、`real_chain` 24、`workspace_admit` 65（`ll_workspace_admit_38627_e63d68`）、`workspace_exec` 54（`ll_workspace_exec_38745_efe4e0`） | exit_0 |
| goal_supervise gate | `v13/goal_supervise` | C5 旁路、C6、D1、D2、未付 harness 结算包装、ambiguous hold、一次租约 | 未跑 | not_run |
| goal_supervisor gate | `v13/goal_supervisor` | B6 表、G3 监督进程。无 SQL。一跳入口未点名则 `unattended_continuation` 非零 `v13: supervisor: ask_user` | 未跑 | not_run |
