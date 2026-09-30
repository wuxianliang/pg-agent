# v13 长循环 Phase B 覆盖矩阵（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-b-plan-2026-09-29.md` §5。状态从 `not_run` 起。只有对应 gate 退出码 0 之后才写 `exit_0`。不设 `real_authorized_exit_0`。本文不是通过证明。Fake 绿不是产品可用。

| 条目 | 目录 | 允许的声称 | 证据指针 | 状态 |
|---|---|---|---|---|
| workspace_admit gate | `v13/workspace_admit` | C2 子集政策行、打开者、结果接受、路径互斥、截断形状已在一次性库跑通。`advance_does_not_dispatch_tool` 的通过是 P∧C∧S，不是「进入 WHEN 'tool'」，也不是裸 waiting。不声称产品角色，不声称 material 已扣，不声称无人值守，不替换 `v13_advance` | `UV_FROZEN=1 uv run python v13/workspace_admit/test_workspace_admit.py` 退出码 0；库 `ll_workspace_admit_73789_c79e24`（跑完已 DROP）；65 checks。同窗口回归均退出码 0：`plan_arm` 43（`ll_plan_arm_66047`）、`loop_driver` 55（`ll_loop_driver_66169`）、`workflow_bind` 8（`ll_workflow_bind_66306`）、`real_chain` 24（`ll_real_chain_66432_1ffad5`）。此前同工作树：`plan_contract` 93（`ll_plan_contract_2997`）、`plan_read` 11（`ll_plan_read_3100`）。断言名按 §5.1。`advance_does_not_dispatch_tool`：P=`waiting`/会话 `waiting`/行仍 `claimed`/行集不变/send_work 写入空；C=新 effect 且 send_work 写入；S=门在 `WHEN 'tool'` 前且 oid 不变 | exit_0 |
| C2 子集 | `workspace_admit` | `workspace_tool_subset` version 1。标签只有 `read_only` 与 `workspace_edit`。四个 read 名字不在这行。`workflow_template` v1 不改。explore 仍 RAISE | 同上。断言 `policy_seed_idempotent` / `workflow_template_v1_unchanged` / `read_names_absent_from_policy` / `read_only_rejects_edit_write_bash` / `explore_spawn_still_raises` | exit_0 |
| G1 准入 | `workspace_admit` | 打开者与互斥、截断形状已有。执行面在 `workspace_exec`，本行不声称文件字节已落地 | 同上。断言 `open_claims_without_increment` / `path_busy_same_path` / `path_busy_prefix` / `path_busy_overlapping_roots` / `result_cap_plus_one` / `result_over_cap_rejected` | exit_0 |
| workspace_exec gate | `v13/workspace_exec` | 未跑。不声称 edit/write/bash/grep/find/ls 已在文件系统上执行 | 无 | not_run |
