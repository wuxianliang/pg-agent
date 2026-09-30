# v13 长循环 Phase A 覆盖矩阵（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md` §7 / §8。状态从 `not_run` 起。只有对应 gate 退出码 0 之后才写 `exit_0`。本文不是通过证明。Fake 绿不是产品可用。

| 条目 | 目录 | 允许的声称 | 证据指针 | 状态 |
|---|---|---|---|---|
| plan_contract gate | `v13/plan_contract` | A1 写者、A2 状态机与绑定载荷、A4 前奏与入口已在一次性库跑通。不声称 advance 臂、绑定窗、产品角色、ingress 等于 start-goal | `UV_FROZEN=1 uv run python v13/plan_contract/test_plan_contract.py` 退出码 0；库 `ll_plan_contract_86792`（跑完已 DROP）；93 checks | exit_0 |
| A1 | `plan_contract`；臂在 `plan_arm` | 写者、水位、以及 advance 前缀已有。不声称 `should_run` 被改过，不声称绑定窗已闭合 | `plan_contract` 与 `plan_arm` 均退出码 0。`should_run` version 仍是 3 | exit_0 |
| A2 | `plan_contract`；锁内绑定在 `plan_arm` | 状态机与锁内绑定已有。绑定窗仍未闭合 | `plan_arm` 退出码 0 的 `bind_once` / `reenable_binds_new_effect`。不声称并发窗已闭合 | exit_0 |
| A3 | `plan_read` | 库存与前沿已在一次性库跑通。LIMIT 不是扫描硬顶。不声称派发门、产品角色、material 已扣 | `UV_FROZEN=1 uv run python v13/plan_read/test_plan_read.py` 退出码 0；库 `ll_plan_read_46262`（跑完已 DROP）；11 checks。断言 `inventory_33` 的 `rows_examined=32` | exit_0 |
| A4 | `plan_contract` | 前奏零 INSERT；入口拒绝空 spec 并转发显式 version。不得声称 ingress 已等于 start-goal | 同上 | exit_0 |
| B1 | `loop_driver` | 五出口与判定顺序已在一次性库跑通；T0 结算 advance 在 complete 同事务（txid 对相等）；stopped 根 `failed` 非 null（含 false/0/文本）时零 advance，键缺失与 JSON null 放行。不得声称心跳已按计划选下一项（真链在 `real_chain`） | `UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py` 退出码 0；库 `ll_loop_driver_62098`（跑完已 DROP）；55 checks。断言 `exit_*`/`unit_*`/`t0_settlement_advance`/`complete_settle_same_txn`/`stopped_failed_snap{,_zero,_text,_null}`/`provider_requeue_one_advance`。stannum 环境注：STN3 并行线 09-30 03:23 换了 pgembed 的 stannum 产物；gate 在恢复 0.4.0 pin（dylib+control）后实跑，跑完已恢复 STN3 现场 | exit_0 |
| B2 | `loop_driver` | 四层文本组装（assertion/assembly/judgment/workflow 有序四段，不合并单行，不写回）已跑通。模板数据在 `workflow_bind`，本 stage 用夹具文本，不调用 `v13_workflow_resolve` | 同上。断言 `four_layers`/`io_outside_txn`（layer_names 有序四段） | exit_0 |
| B3 | 无目录 | 不实现。C/D 不得重开 | 无 SQL、无目录 | not_run |
| B4 | Phase C | 不实现。gap 投影尚未存在 | 无 | not_run |
| B5 | Phase C | 不实现。驱动器不是收据写者 | 无 | not_run |
| B6 | `loop_driver` | 所有权表（README `## B6` 15 行，含 fourth-duty=none）与静态检查已交付。不授权无人值守；Phase C 声称前必须再交表 | 同上。断言 `b6_table_complete`/`static_check`/`no_recover_idle`/`no_direct_spawn`/`no_closed_set_leak`。claim 路径偏差见台账 L12/L13 | exit_0 |
| C1 | `workflow_bind` | 政策行 `workflow_template` version 1 与 STABLE 解析器已交付。返回四段文本，不合并单行。不声称 `judgment_templates` 被复用 | `UV_FROZEN=1 uv run python v13/workflow_bind/test_workflow_bind.py` 退出码 0；库 `ll_workflow_bind_47316`（跑完已 DROP）；8 checks。断言 `resolve_v1` / `judgment_templates_untouched` | exit_0 |
| C2 | `workflow_bind` | 合同在同一政策行（labels / allowed_tools / parent_tools / chain）。子集交付不在本行（Phase B）。explore 仍 RAISE。不 UPDATE tools | 同上。断言 `label_does_not_open_explore` / `no_tool_flag_update` | exit_0 |
| C3 | `workflow_bind` / `real_chain` | 函数 `v13_child_pointer` 已交付。生产调用者不在本行，留在 `real_chain`。不改 `v13_session_log` | 同上。断言 `one_pointer` / `pointer_not_transcript` / `session_log_unchanged` / `root_waterline_unchanged` | exit_0 |
| C4 | `real_chain` | 不得声称摘录引用已交付。多 lane 不建 | 无 | not_run |
| C5 | `loop_driver` | 不实现自动 skip | 无 | not_run |
| C6 | Phase C | 不实现。V11 未读 | 无 | not_run |
| C7 | `loop_driver` | 投影（STABLE `v13_harness_result_project`，闭集 10 键、四值 `result_kind`、三值 `wait_reason`、散文/缺键失败不映射 reject）与驱动器映射已跑通。可选键名单已重读活体（行号在本目录 README）。不重复实现 allOf（由 `v13_complete` 内验证执法） | 同上。断言 `c7_four_kinds_project`/`c7_invalid_fail_no_reject`/`c7_wait_reason_absent_stays`/`c7_prose_missing_key_fail_no_complete`/`harness_project_served_archived` | exit_0 |
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
| loop_driver gate | `v13/loop_driver` | B1/B2/B6/C7 在一次性库跑通（三轮 Oracle 复审：首轮 P0×1 加一批 P1 全改；第二轮 codex 通过；第三轮三路通过后余项亦全改）。不声称真链端到端，不声称产品角色，不授权无人值守。Fake 绿不是产品可用 | `UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py` 退出码 0；库 `ll_loop_driver_62098`（跑完已 DROP）；55 checks。回归：`plan_contract` 93、`plan_read` 11、`plan_arm` 43 同日全绿 | exit_0 |
| workflow_bind gate | `v13/workflow_bind` | C1/C2/C3 在一次性库跑通。不声称工具子集、explore 已改、生产调用已接、产品角色。Fake 绿不是产品可用 | `UV_FROZEN=1 uv run python v13/workflow_bind/test_workflow_bind.py` 退出码 0；库 `ll_workflow_bind_47316`（跑完已 DROP）；8 checks。回归：`plan_contract` 93、`plan_read` 11、`plan_arm` 43、`loop_driver` 55 同日全绿 | exit_0 |
| real_chain gate | `v13/real_chain` | 无 | 无 | not_run |
