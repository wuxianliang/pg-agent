# v20 alpha 覆盖矩阵

日期：2026-10-14。权威是设计五的对象、动词和字段，完成标准是 `docs/plans/v20-alpha-2026-10-14.md` 第 11 节。

仓库根实际命令：

```bash
uv run python v20/alpha/test_alpha.py
```

观察结果：退出码 **0**，输出 **62/62**。每个探针是 `v20/alpha/test_alpha.py` 里的同名函数。下表一行一个函数，状态都是 PASS。不把 v13、v15、v23 的 gate 算进这次回归。

## 身份与库

| 探针 | 证明 |
|---|---|
| `unix_socket_only` | 活动 DSN 的 host 以 `/` 开头。TCP 形态的 URI 被 `local_dsn` 拒绝 |
| `worker_role_cannot_connect` | `v20_alpha_worker` 连接失败 |
| `control_role_sees_other_backend_pid` | `v20_alpha_control` 能在 `pg_stat_activity` 里看见另一条连接的 backend pid |
| `run_id_aliases_session` | `start` 的 `run_id` 等于 `session_id`。错开的插入被 `v20_runs_id_aliases_session` 拒绝 |
| `sessions_have_no_workflow_run_id` | `v20_sessions` 没有 `workflow_run_id` |
| `no_workflow_or_plan_or_artifact_tables` | public 里只有 13 张纵向循环表。目录行是 `alpha` / schema 1。没有 workflow、plan、artifact、span、token 表 |
| `child_parent_session` | 子会话 id 是新的，子 run id 等于子 session id。第一笔 `admit_turn` 的 `input_kind` 是 `parent_instruction` |
| `unknown_parent_rejected` | 未知 `parent_session_id` 得到 `Rejected`，不插入 session |

## 纵向链

| 探针 | 证明 |
|---|---|
| `start_is_running_and_pending` | run 为 `running`，operation 为 `pending` 且 `expects_handle`，`input_retained` 为 false，没有 `v20_turns`。未知动词和 `input_artifact_digest` 不写事件 |
| `first_turn_accepted_before_tool` | 同一 run 上，`accept_turn_receipt` 的 `event_id` 早于 `admit_tool` |
| `preview_keeps_operation_pending` | 进度 `publish_snapshot` 更新预览并把 revision 加一。operation 仍 `pending`，`handle_state` 不变，run 仍 `running` |
| `preview_retry_same_snapshot_seq` | 同一个 `snapshot_seq` 再提交不改预览、不改 revision、不写第二笔事件 |
| `smaller_snapshot_seq_does_not_overwrite` | 较小的 `snapshot_seq` 不覆盖已提交的预览和序号 |
| `echo_result_visible_on_next_turn` | 下一轮 Worker 输入看见 `echo` 的 `output.text`。终态结果里的 `saw` 是这条文本 |
| `tool_receipt_does_not_complete_run` | `accept_tool_result` 之后 run 仍 `running`，start operation 仍 `pending`，revision 停在进度快照 |
| `second_tool_does_not_block_first` | 错配的工具回执只归档，两笔都还 `pending`。一笔失败不阻止另一笔完成，run 仍 `running` |
| `bare_progress_twice_fails` | 连续两笔没有工具的 `progress` 把 run 写成 `failed` |
| `final_snapshot_dormant_resumable` | 默认脚本结束时 run `completed`，revision 3，session `dormant` 且 `resumable` 仍 true，句柄 `absent` |
| `replay_same_request_keeps_result` | 相同 start 载荷只有一行。已完成的终态快照重放不改 result |
| `replay_digest_mismatch` | 同一 `request_id`、不同摘要得到 `IdempotencyConflict`，原文保持不变 |
| `io_outside_transaction` | FakeWorker 和 `echo` 回调时控制连接是 `TRANSACTION_STATUS_IDLE` |
| `model_call_inside_transaction_rejected` | 事务开着时 FakeWorker 和 `echo` 抛 `InTransaction` |

## 取消与转向

| 探针 | 证明 |
|---|---|
| `cancel_then_late_t2_archives_only` | 取消之后的 `accept_turn_receipt` 得到 `FenceRejected`。operation 保持 `closed`，run 保持 `cancelled`，归档事件已提交 |
| `complete_then_cancel_stays_completed` | 已完成的 run 再 `cancel` 不改 status、不改 revision、不写 cancel 事件 |
| `admit_after_cancel_rejected` | 取消之后的 `admit_turn` 被拒绝，不插入 turn |
| `steer_from_running_publishes_new_epoch` | 运行中的 `steer` 关上旧 epoch，打开 `steering` 新 epoch。run id 不变，run 仍 `running`。布尔值不能当 revision |
| `steer_cas_one_commits_one_conflicts` | 同一 `expected_revision` 的两笔并发 `steer`，一笔提交，一笔 `RevisionConflict`，只多一个 epoch |
| `old_epoch_t2_does_not_overwrite_new_snapshot` | 旧 epoch 的迟到回执不改新 epoch 的预览和 `snapshot_seq`。旧 operation 保持 `closed`。`accept_turn_receipt` 提交之后、发布之前若另一连接 `steer`，Host 对原 request 发布并得到 `FenceRejected`，新 operation 仍是 `pending` 且结果为空，run 保持 `running` |
| `cleanup_hides_and_rejects_resume` | `list_hidden` 的会话不在 `WHERE NOT list_hidden` 里。再次 cleanup 不写第二笔。之后的 `claim_resume` 和 `steer` 被拒绝 |
| `cleanup_keeps_events_and_transcript` | cleanup 不删除已有 event 和 transcript turn |
| `wait_sees_cleanup_revision` | `LISTEN` 提交之后、权威读之前发生的 cleanup，被这次读看见 |
| `steer_after_cancel_publishes` | 取消之后的 `steer` 打开新 epoch，并把这次 drive 发布到 `completed` |

## 恢复

| 探针 | 证明 |
|---|---|
| `recover_owner_expires_run` | owner 连接关闭后，`recover_owner` 把 run 写成 `expired`，generation 加一，session `interrupted`，`resumable` 仍 true。pending operation 变成 `archived`，没有 attempt 的句柄变成 `absent`。不改写 backend pid |
| `recover_owner_alive_pid_rejected` | pid 仍活时 `recover_owner` 为 `AlreadyActive`，generation 和 revision 不变 |
| `claim_resume_keeps_ids_and_advances_epoch` | 从 `completed` 恢复：同一 session id 和 run id，ordinal 加一，run 回到 `running`，continuity 不变。不插入 workflow |
| `claim_resume_rejects_running_without_recover` | run 仍在跑且 pid 活着是 `AlreadyActive`。pid 已死但还没 recover 是 `Rejected`。两种都不写新 epoch |
| `related_follow_up_keeps_continuity` | `related_follow_up` 不增加 `continuity_generation` |
| `unrelated_bumps_continuity` | `unrelated` 把 session 和新生 epoch 的 continuity 加一 |
| `two_claim_resume_one_wins` | 两笔并发 `claim_resume`，一笔提交并写上自己的 backend pid，另一笔 `AlreadyActive` |
| `late_receipt_after_recover_archives` | recover 之后的回执得到 `FenceRejected`。operation 保持 `archived`，run 保持 `expired` |
| `cancel_during_worker_returns_failed` | Worker 还在事务外时，另一条连接可以 `cancel`。drive 返回 `failed` 且不再发终态快照，run 保持 `cancelled`。同时的第二笔 drive 得到 `Rejected` |

## 等待与输入

| 探针 | 证明 |
|---|---|
| `needs_input_then_respond_completes` | `decide` 的优先级成立。`needs_input` 脚本先停在 `waiting_for_input`，句柄被收成 `absent`。随后的 `respond` 跑到 `completed` |
| `respond_rejected_unless_waiting` | run 是 `running` 或已经 `completed` 时，`respond` 被拒绝，不插入新 operation |
| `wait_listens_before_read` | 钩子顺序是 listen 然后 read。`pg_listening_channels()` 包含 `v20_alpha_run_changed` |
| `wait_sees_commit_from_before_listen` | `LISTEN` 之前已提交的 revision 被后面的权威读看见，不等待超时 |
| `lost_notify_seen_on_timeout` | 等待期间没有 NOTIFY 的 revision 更新，超时后的重读仍然看见 |
| `wait_connection_idle` | 等待期间主连接和 listen 连接都没有打开的事务 |

## 句柄

| 探针 | 证明 |
|---|---|
| `start_expects_handle_and_no_depends_on` | start operation `expects_handle`，`handle_state` 为 `pending`，`depends_on_request_id` 为空 |
| `no_handle_starts_worker` | 空句柄立即启动 Worker，输入里的 `provider_handle` 是空 |
| `record_handle_present_without_changing_run` | `record_provider_handle` 把句柄写成 `present` 并留下 attempt。run 仍 `running`，revision 不变 |
| `handle_before_snapshot_and_snapshot_before_handle` | 先句柄后快照、先快照后句柄，当前句柄都留下。先快照不把句柄收成 `absent`。后到的 record 不改已完成 operation 的 status 和 result |
| `smaller_attempt_seq_does_not_overwrite_current_handle` | 同一 epoch 里较小的 `attempt_seq` 会写 attempt，不覆盖当前句柄 |
| `old_epoch_handle_does_not_overwrite_current` | 旧 epoch 的迟到句柄会写 attempt，不覆盖当前句柄 |
| `claim_resume_depends_on_earlier_handle` | recover 之后那条 `archived` 且 `present` 的 operation，被下一笔 `claim_resume` 依赖。`resolve_handle` 返回它的句柄 |
| `present_handle_is_in_next_worker_input` | `steer` 之后的 Worker 输入带上一条已关闭但仍 `present` 的句柄 |
| `absent_does_not_wait` | 上一条句柄已是 `absent` 时，`resolve_handle` 不等待，Worker 立刻启动且句柄为空 |
| `pending_handle_returns_wait_not_forever` | 依赖的句柄仍 `pending` 时，drive 只等 `resolve_handle` 的那一次，返回 `wait`，不调用 Worker |
| `completed_without_attempt_becomes_absent` | 终态快照明确没有句柄、且没有 attempt 行时，`handle_state` 变成 `absent` |

## 对话投影

| 探针 | 证明 |
|---|---|
| `request_activity_on_t1` | `start` 和 `admit_turn` 各写一条 user/request。此时还没有 assistant |
| `response_activity_on_t2` | assistant/response 出现在 `accept_turn_receipt`，文本是回执 result 的规范 JSON |
| `two_turns_one_transcript_turn` | 默认循环的两笔控制 turn 指向同一条 transcript turn |
| `transcript_has_no_control_turn_id` | `v20_transcript_turns` 没有 `control_turn_id` |
