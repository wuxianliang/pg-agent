# v13 real_chain

Phase A 第六段，也是最后一段。交付第 4 节整段序列、G2 的 Fake 门、本链 read 注册、C4 首期 `effect_id` 加有界摘录，以及 `v13_workflow_resolve` / `v13_child_pointer` 的唯一生产调用。

Fake 退出码 0 不是产品可用。真实 provider 验收不是本 gate。本目录不证明产品角色，不交付 G1，不建多 lane，不授权无人值守。

## Gate

`UV_FROZEN=1 uv run python v13/real_chain/test_real_chain.py`

真实验收（本里程碑不设置授权，不跑正路径）：

`UV_FROZEN=1 uv run python v13/real_chain/accept_real_provider.py`

授权信号只有 `V13_REAL_PROVIDER_AUTHORIZATION=1`。未设置或不是 `1`：非零退出，消息 `v13: real provider not authorized`，零网络。正路径不在本 gate 的通过条件里。

## 序列

`chain.py` 调用 `loop_driver`，不复制出口机，不调用 `v13_spawn_subsession`。四段正文来自 `v13_workflow_resolve('workflow_template', 1)`，按 `assertion`、`assembly`、`judgment`、`workflow` 交给驱动器，不拼成一行。

子会话只由活体 advance 的 spawn 臂创建。那次 advance 提交之后，只有 `chain.py` 调用 `v13_child_pointer`。参数来自子行 `parent_session_id`、`v13_plan_map_root`、已绑定的 `todo_id`、根最大 `events.seq`。不 INSERT。

子 read 的 complete 不走 `LoopDriver.serve`。`serve` 会在 complete 同一事务里再 advance 子会话。子上没有 `user/message`，read 前缀在 effect 已存在时返回 NULL，随后 `v13_triage_prework` 因 `fold_empty` 走 `reject`，`v13_closeout` 因 `origin_user_seq < 0` RAISE，摘录会随事务回滚。因此子 advance 提交之后，chain 做与驱动器同形的作用域领取，再调 5 参 `v13_complete`，不在子上结算。摘录超过 1024 字符则不 complete、不截断。根上的归档 advance 只走 `LoopDriver._settlement_advance`。

## C4 重读

落点仍在活体 complete，没有停点。`v13_is_harness_tool` 只在 name 为 `harness_turn` 时为真（`v13/control/v13_control.sql:97-99`）。`v13_complete` 只对 harness 工具调用 `v13_validate_harness_result_v1`（`v13/acl/v13_acl.sql:381-386`）。成功时 `UPDATE effects SET result = p_result`（`:411`）。`read_file_py` 不是 `harness_turn`。本 gate 不改这些旧行，不把摘录改成跳过。

## 种子

`default` version 2 复制活体 version 1 的带，再追加重读到的 8 条 read 带，然后冻结。四行工具按 name 幂等插入：`read_pi`、`read_file_swift`、`read_file_py`、`read_duck`。不 UPDATE 已存在且不一致的行。不停用 `spawn_subsession`。不把 `max_cycles=6` 写进产品种子。不写 stannum GRANT。

## B6

所有权表仍在 `v13/loop_driver/README.md` 的 `## B6`。pointer 行已经写明生产调用者只有本文件。本里程碑不改那张表（前一段目录）。本交付不授权无人值守。

## 断言名

`prelude_zero_insert`；`open_session_version_2`；`child_inherits_version_2`；`override_before_parse`；`admission_before_io`；`plan_commit_on_root`；`selected_one_provider_todo`；`arm_bind_then_io_after_commit`；`spawn_only_from_live_arm`；`spawn_call_not_harness_projected`；`one_child_pointer`；`child_read_file_py_only`；`child_read_effect_not_tool_call`；`deny_edit_write_bash`；`c7_four_kinds_and_prose`；`receipt_by_advance`；`archive_todo_delta_done`；`excerpt_on_effect_not_prompt_exports`；`plan_artifact_not_committed_via_complete`；`explore_still_raises`；`spawn_subsession_not_disabled`；`single_tree`；`four_layers_from_resolver`；`real_provider_script_refuses`。
