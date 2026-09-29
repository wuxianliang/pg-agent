# v13 长循环 Phase A 覆盖矩阵（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md` §7 / §8。状态从 `not_run` 起。只有对应 gate 退出码 0 之后才写 `exit_0`。本文不是通过证明。Fake 绿不是产品可用。

| 条目 | 目录 | 允许的声称 | 证据指针 | 状态 |
|---|---|---|---|---|
| plan_contract gate | `v13/plan_contract` | A1 写者、A2 状态机与绑定载荷、A4 前奏与入口已在一次性库跑通。不声称 advance 臂、绑定窗、产品角色、ingress 等于 start-goal | `UV_FROZEN=1 uv run python v13/plan_contract/test_plan_contract.py` 退出码 0；库 `ll_plan_contract_86792`（跑完已 DROP）；93 checks | exit_0 |
| A1 | `plan_contract`；臂在 `plan_arm` | 写者、水位、以及 advance 前缀已有。不声称 `should_run` 被改过，不声称绑定窗已闭合 | `plan_contract` 与 `plan_arm` 均退出码 0。`should_run` version 仍是 3 | exit_0 |
| A2 | `plan_contract`；锁内绑定在 `plan_arm` | 状态机与锁内绑定已有。绑定窗仍未闭合 | `plan_arm` 退出码 0 的 `bind_once` / `reenable_binds_new_effect`。不声称并发窗已闭合 | exit_0 |
| A3 | `plan_read` | 库存与前沿已在一次性库跑通。LIMIT 不是扫描硬顶。不声称派发门、产品角色、material 已扣 | `UV_FROZEN=1 uv run python v13/plan_read/test_plan_read.py` 退出码 0；库 `ll_plan_read_46262`（跑完已 DROP）；11 checks。断言 `inventory_33` 的 `rows_examined=32` | exit_0 |
| A4 | `plan_contract` | 前奏零 INSERT；入口拒绝空 spec 并转发显式 version。不得声称 ingress 已等于 start-goal | 同上 | exit_0 |
| B1 | `loop_driver` | 不得声称五出口已交付 | 无 | not_run |
| B2 | `loop_driver` | 不得声称四层组装已交付 | 无 | not_run |
| B3 | 无目录 | 不实现。C/D 不得重开 | 无 SQL、无目录 | not_run |
| B4 | Phase C | 不实现。gap 投影尚未存在 | 无 | not_run |
| B5 | Phase C | 不实现。驱动器不是收据写者 | 无 | not_run |
| B6 | `loop_driver` | 不得声称所有权表已交，更不得声称无人值守 | 无 | not_run |
| C1 | `workflow_bind` | 不得声称政策行或解析器已交付 | 无 | not_run |
| C2 | `workflow_bind` | 合同未交。子集不在 A | 无 | not_run |
| C3 | `workflow_bind` / `real_chain` | 不得声称指针函数或生产调用已交付 | 无 | not_run |
| C4 | `real_chain` | 不得声称摘录引用已交付。多 lane 不建 | 无 | not_run |
| C5 | `loop_driver` | 不实现自动 skip | 无 | not_run |
| C6 | Phase C | 不实现。V11 未读 | 无 | not_run |
| C7 | `loop_driver` | 不得声称投影已交付 | 无 | not_run |
| D1 | Phase C | 不实现 | 无 | not_run |
| D2 | Phase C | 不实现 | 无 | not_run |
| D3 | Phase C | 不实现。哈希句之前不得标绿 | 无 | not_run |
| G1 | Phase B | 不交付 | 无 | not_run |
| G2 `fake_exit_0` | `real_chain` | 不得声称 Fake 门已绿 | 无 | not_run |
| G2 `real_authorized_exit_0` | `real_chain` | 不得声称真实验收已跑。本行与 Fake 行分开 | 无 | not_run |
| G3 | Phase C | `v13_recover_idle` 未改 | 无 | not_run |
| G4 | Phase C / D | 不实现。PC-4 不开工 | 无 | not_run |
| plan_read gate | `v13/plan_read` | A3 库存与前沿零写。不声称 `v13_selected_todo` / `v13_plan_gate` 已交付 | 同上。断言：`zero_write`；`inventory_33`；`inventory_32`；`inventory_0`；`horizon_caps`；`gap_inserts_nothing`；`text_cap`；`empty_plan`；`child_reads_root_stream` | exit_0 |
| plan_arm gate | `v13/plan_arm` | 唯一一份 `v13_advance` 替换已在一次性库跑通。不声称绑定窗已闭合，不声称产品角色 | `UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py` 退出码 0；库 `ll_plan_arm_16921`（跑完已 DROP）；43 checks。断言名按 §7.3。结算扫描全部绑定行 | exit_0 |
| loop_driver gate | `v13/loop_driver` | 无 | 无 | not_run |
| workflow_bind gate | `v13/workflow_bind` | 无 | 无 | not_run |
| real_chain gate | `v13/real_chain` | 无 | 无 | not_run |
