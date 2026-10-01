# v13 长循环 Phase C 覆盖矩阵（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md` §7。状态从 `not_run` 起。只有对应 gate 退出码 0 之后才写 `exit_0`。不设 `real_authorized_exit_0`。本文不是通过证明。Fake 绿不是产品可用。

| 条目 | 目录 | 允许的声称 | 证据指针 | 状态 |
|---|---|---|---|---|
| frontier_gap gate | `v13/frontier_gap` | B4 投影与插入、D3 与哈希句同一 gate。载荷键恰好 `schema_version`。实现闭集只有 `dangling_link`（写者拒绝空 successor）。没有伪造配额账。不声称产品角色，不声称无人值守，不替换 `v13_advance` | `UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py` 退出码 0；库 `ll_frontier_gap_37578_0f732d`（跑完已 DROP）；58 checks。断言名按 §7.1。同窗口回归均退出码 0：`plan_contract` 93（`ll_plan_contract_37955`）、`plan_read` 11（`ll_plan_read_38082`）、`plan_arm` 43、`loop_driver` 55、`workflow_bind` 8、`real_chain` 24、`workspace_admit` 65（`ll_workspace_admit_38627_e63d68`）、`workspace_exec` 54（`ll_workspace_exec_38745_efe4e0`） | exit_0 |
| goal_supervise gate | `v13/goal_supervise` | C5 旁路（执法在 `v13_interaction_offer`，不插 approval 臂，无人值守 skip 仍未授权）。C6 折叠。D1 政策与投影。D2 检查。未付 harness 结算包装。ambiguous hold。一次租约。不声称产品角色。不替换 `v13_advance`。不声称守卫已闭合 `interaction/offered` 载荷。V11 未读，不得声称 auto-wake 已闭合 | 2026-10-01 `UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py` 退出码 0；库 `ll_goal_supervise_31540_9afbe8`（跑完已 DROP）；99 checks。断言名按 §7.2；增加快照绑定、failed null、当前前驱选择与不回落旧行、waiting user_gate。Oracle `301594C5` 的两项 P1 已修复，见台账 PC-C7/PC-C8。同窗口回归命令均为 `UV_FROZEN=1 uv run python v13/<stage>/test_<stage>.py`，退出码均为 0：`plan_contract` 93（`ll_plan_contract_91941`）、`plan_read` 11（`ll_plan_read_92042`）、`plan_arm` 43（`ll_plan_arm_92150`）、`loop_driver` 55（`ll_loop_driver_92246`）、`workflow_bind` 8（`ll_workflow_bind_92378`）、`real_chain` 24（`ll_real_chain_92488_e8832a`）、`workspace_admit` 65（`ll_workspace_admit_92594_770f28`）、`workspace_exec` 54（`ll_workspace_exec_92719_d05e2d`）、`frontier_gap` 58（`ll_frontier_gap_92952_a1b296`）。各库均已 DROP | exit_0 |
| goal_supervisor gate | `v13/goal_supervisor` | B6 表、G3 监督进程。无 SQL。一跳入口未点名则 `unattended_continuation` 非零 `v13: supervisor: ask_user` | 未跑 | not_run |

## R0 重开实现证据（2026-10-01）

R0 只关闭根会话已进入 `ready`/`claimed` 阻断分支时的 harness material receipt 前移停点；不代表 R1/M3、生产无人值守或真实 provider 可用。实现基线为 `fb295ac6c7459bb98dac57e37883af549d2d8a4c`；去除 `R0_DECL_*` 与 `R0_RECEIPT_*` 两个整行哨兵块后，`v13/plan_arm/v13_plan_arm.sql` 恢复为该基线字节。改后加载的 `public.v13_advance(uuid,jsonb)` SHA-256 为 `e49c4efa9f45ccd0521be96b28d053c16a4e63c3a113285138d96ad8632da87c`。

| R0 项目 | 命令/库 | 实际证据 | 状态 |
|---|---|---|---|
| R0 全量回归 | `UV_FROZEN=1 uv run python v13/<stage>/test_<stage>.py`（以下十条逐条实跑） | `plan_contract` exit 0 / `ll_plan_contract_15579` / 93 checks；`plan_read` exit 0 / `ll_plan_read_15674` / 11；`plan_arm` exit 0 / `ll_plan_arm_79930` / 104；`loop_driver` exit 0 / `ll_loop_driver_80276` / 55；`workflow_bind` exit 0 / `ll_workflow_bind_80401` / 8；`real_chain` exit 0 / `ll_real_chain_80638_345e34` / 24；`workspace_admit` exit 0 / `ll_workspace_admit_80745_8831f1` / 65；`workspace_exec` exit 0 / `ll_workspace_exec_81004_e98227` / 54；`frontier_gap` exit 0 / `ll_frontier_gap_81274_d81dfa` / 59；`goal_supervise` exit 0 / `ll_goal_supervise_82058_2ff211` + owned `ll_r0_gs_82058_cf2a7d` / 172。所有测试库均已 DROP；workspace APFS image 已 detach。 | exit_0 |
| R0 行为范围 | `plan_arm` + `goal_supervise` | root-only；human ready/claimed 与 root workspace claimed 均可幂等补 receipt 后仍 waiting；child 不向上锁 root；signals/ledger/material collision/failed/stale/unknown/cancel/terminal 墙有独立断言；无新增 effect/dispatch。 | exit_0 |
| R0 quota 时点 | `plan_arm` | 已提交 receipt 在 `allowed=1` 时使下一轮 `v13_should_run`/派发合法等待；`allowed=1000000` 对照通过；使用真实 receipt 与合法 human response，未修改 quota/should_run。 | exit_0 |
| R0 实现复审 | Oracle group `FA70C826-BE9B-498C-A493-99E67CA085D7` | 两路均无 P0/P1；一项 P2 已逐行核对并强化夹具，矩阵/台账本行现补齐。复审不是可执行 gate，不赋退出码。 | 无阻塞发现 |

### 实施前十条基线

在修改 plan_arm SQL 前，按上表同一命令模板逐条实际运行；全部 exit 0，全部库已 DROP，workspace APFS image 已 detach：

| stage | 基线 checks | 库 |
|---|---:|---|
| plan_contract | 93 | `ll_plan_contract_40896` |
| plan_read | 11 | `ll_plan_read_41274` |
| plan_arm | 43 | `ll_plan_arm_41581` |
| loop_driver | 55 | `ll_loop_driver_41956` |
| workflow_bind | 8 | `ll_workflow_bind_42323` |
| real_chain | 24 | `ll_real_chain_42531_919f2e` |
| workspace_admit | 65 | `ll_workspace_admit_42722_fae764` |
| workspace_exec | 54 | `ll_workspace_exec_42938_68cd6c` |
| frontier_gap | 58 | `ll_frontier_gap_43483_c5d08f` |
| goal_supervise | 99 | `ll_goal_supervise_43598_6cbb94` |

R1/M3、`goal_supervisor` 保持 `not_run`；R0 不证明 V11 auto-wake、PC-4、产品 operator 权限、真实 provider、multi-goal fairness/soak，也不改写 Phase A 既有真实验收记录。
