# v13 loop_driver

Phase A 第四段。交付 B1 五出口、B2 四层文本组装、B6 所有权表与静态检查、C7 投影与驱动器映射。FakeLLM/FakeTool，外部 IO 在事务外。本目录不宣称真链端到端完成，不证明产品角色，不授权无人值守。

## harness_result_schema 重读（开工门）

本目录开工时重读了整份 `harness_result_schema`，与活体一致，无停点。行号：

- `v13/control/v13_control.sql:32-33` — `v13_policies` 行 `harness_result_schema` version 1，`active`。
- `:41` — `result_kind` 枚举四值 `progress|finish|wait|reject`。
- `:42` — `wait_reason` 枚举 `approval|evidence|quota`。
- `:43-58` — 可选键（`result_kind`、`wait_reason` 之外另有 8 个）：`delivery_kind`、`harness_session_ref`、`resume_token`、`interaction_id`、`partial`、`content_hash`、`signals`、`wake`；连同 `result_kind` 与 `wait_reason` 共 10 键。投影的键层闭集就是这 10 个。
- `:56-71` — `wake` 的 oneOf 四形：`event`、`not_before`、`artifact`、`children_terminal`。
- `:72-88` — allOf 条件：`progress` 禁 `wait_reason`/`wake`/`interaction_id`；`finish|reject` 另禁 `signals`；`wait` 必带 `wait_reason`；`approval` 必带 `interaction_id` 禁 `wake`；`evidence|quota` 必带 `wake` 禁 `interaction_id`；`delivery_kind=USER_ACTION_REQUIRED` 联动 `wait+approval+interaction_id`。
- `:97-99` — `v13_is_harness_tool`：name=`harness_turn` 且 kind=`tool`。
- `:118-124` — `v13_pending_human`。
- `:172-186` — `v13_harness_predecessor`。

投影 `v13_harness_result_project`（本目录 SQL 唯一对象，STABLE）只强制键层：闭集 10 键、缺 `result_kind` 失败、`result_kind` 四值、`wait_reason` 出现时三值；缺席保持缺席；散文/非对象/空对象失败且不映射成 `reject`；失败计入尝试上界、不调用 complete。allOf 条件约束由 `v13_complete` 内的 `v13_validate_harness_result_v1` 执法（`v13/acl/v13_acl.sql:381-386`），投影不重复实现。

## B6

B1 出口只调用已有动词或什么都不调用。本表不授权无人值守；Phase C 声称无人值守之前必须再交一次。

| 职责 | 持久语义所有者 | 驱动器允许 | 禁止 |
|---|---|---|---|
| identity | `v13_plan_commit_entry` → `v13_open_session` | 传显式 version | 驱动器 INSERT session；空 spec |
| enqueue | `v13_advance` 内的新臂，以及活体臂各自的 effect | 按 B1 调用 advance | 驱动器 INSERT effect；claim 路径上的 `v13_recover_idle`；驱动器调用 `v13_spawn_subsession` |
| receipt | advance 里的 harness 收据臂 | 发起含有候选的结算调用并接受结果 | 驱动器写 `turn/material_spent` |
| closeout | 已有 closeout | `terminal` 出口走该路径 | 驱动器直接改 session status |
| projection | 本节 STABLE 函数 | 只读 | 把驱动器缓存当成权威 |
| cancel classification | 已有 cancel / `v13_goal_stop` | A 的链不调用 cancel | 驱动器自造分类 |
| harness observation | 提交后的 SQL 结果 | 事务外观察 IO，再提交给具名 SQL | 把观察文件当成控制状态 |
| result_kind | C7 投影；持久形态是 complete 之后的 effect 行 | 映射四个字面 | 散文成功；默认缺字段；`VALIDATED_*` |
| actor | 规划：operator 的 NULL，或直接父。tool/llm complete：显式 NULL。human：非 NULL 亲缘 | 测试超级用户走 operator NULL | 以 agent 身份自 skip |
| credentials and filesystem | 事务外的进程环境 | Fake 路径无密钥。真实验收从环境读 | 密钥进入请求 JSON；密钥进库 |
| disposition write permission | 具名 SQL | 调用闭集 | 裸 INSERT |
| policy | `v13_policies` 与解析器 | 读冻结行 | 改 `judgment_templates` |
| children_terminal observation | `v13_wake_is_satisfied_v1` 的 `children_terminal` 分支起于 `v13/spawn/v13_spawn.sql:793`。函数体没有整份读完 | 只读 | 把它改成计划门；为它调用 recover_idle |
| pointer | `v13_child_pointer` | 只有 `v13/real_chain/chain.py` 在创建子会话的 advance 提交之后调用 | 本目录允许名单不含它；`plan_arm` 不调用；禁止 INSERT |
| fourth-duty | none —— 查找范围：将复制的 `v13_advance` 正文（`v13/plan_arm/v13_plan_arm.sql:332-804`）查找 `fourth`，未出现该词 | 无 | 为填表而新造职责 |

## 允许 SQL 闭集

控制动词 17 项（`driver.py` 的 `ALLOWED_CONTROL_SQL`）：`v13_plan_prelude`、`v13_plan_admit`、`v13_plan_commit_entry`、`v13_plan_writer`、`v13_plan_current`、`v13_selected_todo`、`v13_plan_gate`、`v13_plan_inventory`、`v13_plan_horizon`、`v13_harness_result_project`、`v13_submit_override`、`v13_advance`、`v13_complete`、`v13_goal_stop`、`v13_should_run`、`v13_scheduler_hint`、`v13_wake_is_satisfied_v1`（只读）。

不含 `v13_child_pointer`、`v13_workflow_resolve`；不调用 `v13_open_session`、`v13_spawn_subsession`、`v13_recover_idle`、`v13_insert_nudge`、`v13_goal_resume`、`v13_cancel`。tool/llm 的 complete 用 5 参（显式 NULL）。本目录不要求 `workflow_bind` 已装。

闭集之外的三类用法（记入偏差台账，请父裁决）：

1. **claim 路径**：驱动器在 complete 同一事务内对**即将 complete 的那个 effect** 做作用域领取——`UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, lease_owner=…, lease_until=… WHERE effect_id=… AND status='ready' RETURNING attempt_no, fence`。与活体 `v13_claim`（`v13/fanout/v13_fanout.sql:266`）的 UPDATE 体、各 stage 测试的 `settle` 夹具同形；静态检查把这条 UPDATE 冻结为驱动器源内恰好出现一次。不用 `v13_claim` 本体，因为它领的是**全局**最老 ready 行，与本目录按会话伺服的 pump 语义不合（一库多会话时会领走别人的 effect）。B6 的 enqueue 行点名驱动器存在 claim 路径（只禁其上的 `v13_recover_idle`）。领取行与先读到的 servable 行不符（已被并发领走）时回滚放弃；`claim_lost_gives_up_no_complete` 用钩子在 peek 与 claim 之间模拟并发领取。claim 路径上不调用 `v13_recover_idle`。
2. **只读投影**：`v13_probe`（构造 advance 快照，`v13/manifest/v13_manifest.sql:830`）、`v13_goal_lifecycle`、`v13_plan_map_root`、`v13_plan_todo_fold`（needs_human 谓词）。零写。
3. **夹具水暖**：`snap_of` 里 `UPDATE sessions SET context_active_revision = v13_context_required(...)`，与 stage 测试既有 `snap_of` 相同的同步步，不是控制语义。

驱动器读「需要人」用 §5.4 谓词（fold 里 `user_gate|user_action|blocker` 且 status ∈ `pending|runnable|blocked`），不依赖 `v13_selected_todo` 的排除结果——绑定后的 human effect 仍处于待应答时 `selected_todo` 为 0 行，但 B1 判定顺序要求它先于 wait 命中 `user_action`。

## 迟到 complete

`v13/control/v13_control.sql:300-304` 是 fence 不一致返回 `stale`、终态返回 `replay`（同文 `v13/acl/v13_acl.sql:459-469` 的 5 参包装传 `NULL::uuid`）。仍处 `claimed` 的迟到 complete 不自动是 `replay`。`stale` 不归档为成功；`replay` 由调用者带确定性 `apply_id` 重放（`plan_arm` 的结算前缀已实现归档重放）。

## B1 出口与 T0
判定顺序：terminal → stopping → `user_action`（需要人：§5.4 谓词，`user_gate|user_action|blocker` 且 status ∈ `pending|runnable|blocked`，或 dispatch=`operator`）→（`repair`/`replan`/`capability_adapter_handoff` 等非出口词 → wait）→ wait 条件（门假 / `should_run` 假 / hint ∈ `wait|dont_notify` / human_pending / 无 provider 候选）→ provider（门真 ∧ `should_run` 真 ∧ hint=`run_now` ∧ dispatch=`provider`）→ 其余 wait。非出口词只压 provider，不压 human 出口。

`wait` 不吞 T0：complete 之后的结算 advance 总在 complete 同一事务内发出（除非 T0 禁止）。T0 纪律：已 stopped 的根上，顶层 snap 的 `failed` 键非 null（含 JSON false、0、非空文本）时驱动器不调用 `v13_advance`；键缺失与 JSON null 不在禁令内。这是驱动器纪律，不写进 advance 自检。stopped 根上不写 plan/todo。

`stopping` 只见 `v13_goal_stop`；session status 词表不新增 `stopping`。

尝试上界留在进程内：`attempts_used` 加测试日志，不写进 effect 行，不新增事件种类（计划 §5.2 明文；复审建议持久化被拒）。complete 的 allOf 缝由 `allof_seam_complete_rolls_back` 盖住：键层合法但 allOf 非法的载荷让 `v13_complete` RAISE，整事务回滚，effect 回到 `ready`，连接仍可用。

## settle_once（R1）

点名的根结算入口是 `LoopDriver.settle_once(sid) -> str`。它不是 `run_turn`，不调用 FakeLLM/FakeTool，不 `serve`/`v13_complete`。根锁、T0 重读与至多一次 `v13_advance` 在同一未提交事务里；无合格未付前驱则 quiet 返回 `waiting`。已 stopped 且存储 `failed` 非 null（含 false/0/文本）返回 `skipped_failed` 且零 advance。返回词是结算/advance 闭集加 `skipped_failed`，不是 B1 的 `wait`。返回后连接必须 IDLE。Phase A 前缀（stage 33）没有 `v13_unpaid_harness_turn` / `v13_harness_settle`。这不授权无人值守，不证明产品角色。

## 断言名

`static_scan_found_files`；`static_check`；`claim_update_frozen_once`；`no_sessions_status_write`；`no_recover_idle`；`no_direct_spawn`；`no_closed_set_leak`；`not_exit_words_pinned`；`b6_table_complete`；`c7_four_kinds_project`；`c7_invalid_fail_no_reject`；`c7_wait_reason_absent_stays`；`c7_single_stable_function`；`c7_key_layer_not_allof`；`unit_terminal`；`unit_stopping`；`unit_user_action_fold`；`unit_user_action_dispatch`；`unit_wait_conditions`；`unit_provider`；`unit_upstream_words`；`unit_upstream_never_beats_order`；`unit_t0_discipline`；`exit_wait`；`exit_wait_no_requeue`；`decisions_row_count_unchanged`；`override_before_parse`；`workflow_id_does_not_spawn`；`exit_user_action`；`user_action_decisions_unchanged`；`exit_provider`；`provider_requeue_one_advance`；`exit_terminal`；`exit_stopping`；`unknown_exit_words_map_to_wait`；`unknown_words_decisions_unchanged`；`stopped_failed_snap`；`stopped_failed_snap_zero`；`stopped_failed_snap_text`；`stopped_failed_snap_null`；`stopped_absent_failed_key_advances`；`t0_settlement_advance`；`complete_settle_same_txn`；`io_outside_txn`；`pump_llm_completed`；`pump_exit_wait`；`pump_decisions_unchanged`；`retry_bound_2`；`c7_prose_missing_key_fail_no_complete`；`harness_project_served_archived`；`harness_wait_not_archived`；`allof_seam_complete_rolls_back`；`claim_lost_gives_up_no_complete`；`four_layers`。

R1 追加：`named_entry_is_settle_once`；`settle_once_not_run_turn`；`phase_a_prefix_driver_has_no_unpaid_helper`；`r1_sessions_for_update_once_in_sentinel`；`r0_source_scope`；`phase_a_prefix_has_no_unpaid_helper`；`quiet_does_not_call_advance`；`connection_idle_after_settle_once`；`r1_unpaid_predicate_matches_predecessor`；`unpaid_progress_calls_advance_once`；`t0_same_txn_root_lock`；`second_settlement_no_second_receipt`；`unpaid_finish_calls_advance_once`；`wait_reject_not_settled`；`stopped_failed_snap_no_advance`；`stopped_without_failed_key_still_settles`；`stopped_failed_null_still_settles`；`human_ready_claimed_settles_then_waits`；`waiting_with_unpaid_remaining_unknown`；`waiting_with_unpaid_remaining_cancel`；`waiting_with_unpaid_remaining_stale`；`r1_open_transaction_fails_zero_sql`；`r1_advance_raise_rolls_back_idle`；`r1_next_settle_relocks_after_rollback`；`r1_child_fails_zero_advance`；`stop_advance_interleave_stop_wins`；`stop_advance_interleave_settle_holds`。

超级用户夹具不是产品角色证明。Fake 退出码 0 不是产品可用。
