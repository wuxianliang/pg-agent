# v13 goal_supervisor

Phase C 第三段。交付 B6 表与 G3 监督 tick。无 SQL，无加载键，不复制 B1 出口机，不调用真实 provider，不 import `run_turn`。唯一结算者是 `LoopDriver.settle_once`。超级用户夹具不是产品角色证明。Fake 路径不是产品可用。人可以离开生产终端这一项仍未授权。

`unattended_continuation` 在一跳已点名且 T0 拒绝已证明之后，仍非零退出 `v13: supervisor: ask_user`。不得把矩阵本行写成 `exit_0`。

## B6

Phase A 行名与持久语义所有者不变。「监督进程允许」只写本进程能做的事。loop_driver 的表不授权无人值守。

| 职责 | 持久语义所有者 | 监督进程允许 | 禁止 |
|---|---|---|---|
| identity | `v13_plan_commit_entry` → `v13_open_session` | 不调用。测试夹具才会话 | INSERT session；空 spec |
| enqueue | `v13_advance` 内的新臂，以及活体臂各自的 effect | 不 INSERT effect。结算只经 `settle_once` | 驱动器 INSERT effect；claim 路径上的 `v13_recover_idle`；`v13_spawn_subsession` |
| receipt | advance 里的 harness 收据臂 | 有未付则调用一次 `settle_once` 并接受结果 | 进程写 `turn/material_spent` |
| closeout | 已有 closeout | 终态早退，不走 B1 `terminal` 出口机 | 直接改 session status |
| projection | 已有 STABLE 函数 | 只读 hint/notify/observe/frontier | 把进程缓存当成权威 |
| cancel classification | 已有 cancel / `v13_goal_stop` | 仅第 10 步、且本 tick 未因 human/`skipped_failed` 早退时，才可 `v13_goal_stop` | 自造分类；先 hop 再停 |
| harness observation | 提交后的 SQL 结果 | 无 Fake IO；结算后读未付谓词 | 把观察文件当成控制状态 |
| result_kind | C7 投影；持久形态是 complete 之后的 effect 行 | 不映射 B1 `wait`；接受 advance/`skipped_failed` 词 | 散文成功；`VALIDATED_*` |
| actor | 规划：operator 的 NULL，或直接父。tool/llm complete：显式 NULL。human：非 NULL 亲缘 | 监督 SQL 用 operator 显式 NULL。这不是产品 EXECUTE 角色 | 以 agent 身份自 skip |
| credentials and filesystem | 事务外的进程环境 | 无密钥、无文件系统 IO | 密钥进入请求 JSON；密钥进库 |
| disposition write permission | 具名 SQL | 第 4.7/5.1 节闭集 | 裸 INSERT |
| policy | `v13_policies` 与解析器 | 读冻结行。should_run version 仍是 3 | 改 `judgment_templates` |
| children_terminal observation | `v13_wake_is_satisfied_v1` 的 `children_terminal` 分支起于 `v13/spawn/v13_spawn.sql:793`。函数体没有整份读完 | 允许名单含该只读函数；本 tick 默认不调用 | 把它改成计划门 |
| pointer | `v13_child_pointer` | 本目录允许名单不含它 | INSERT；监督进程调用 |
| fourth-duty | none —— 查找范围：将复制的 `v13_advance` 正文（`v13/plan_arm/v13_plan_arm.sql:332-804`）查找 `fourth`，未出现该词 | 无 | 为填表而新造职责 |
| supervision | 具名 SQL 与已有 advance | `LoopDriver.settle_once` 与允许名单。不 import `run_turn` | INSERT effects/events；把 recover 当入队者；第二份 advance；`v13_harness_settle` |
| lease | `v13_goal_lease_once` | 每个 tick 对传入的一个有限租约至多一次；可零次 | 续租循环；缩短或改写 infinity；编辑打开者 |
| ambiguous hold | `v13_goal_ambiguous_hold` | 只读。有行则 `deliver=false`，跳过 accept/recover/lease/hop | 标 `unknown`；标 `succeeded` 或 `failed`；cancel；清路径 |
| notification | `v13_notify_project` 与政策行 | 读 DTO | outbox；`notify/sent`；exactly-once 声称 |
| observation | `v13_observe_fold` | 只读 | 代答；link 表；send 账本 |
| evidence | `v13_evidence_check` | 测试可调用。监督进程不调用 | INSERT artifacts；把证据焊到 wake |
| replan obligation | `v13_replan_gap_insert` | `omitted_complete` 为真时至多一条；哈希原样来自 `v13_frontier_project` | 模型信号当义务；计数器触发插入；裸 INSERT |

## 点名入口

`LoopDriver.settle_once(sid) -> str`。监督 tick 在任何其它写之前，有未付候选则调用一次。不得再调用 `v13_harness_settle`。`skipped_failed` 立即安全结束本 tick。其它返回词若同一候选仍被 `v13_unpaid_harness_turn` 看见，本 tick 失败，消息恰好 `v13: supervisor: unpaid_remaining`。

这不授权无人值守完成，不证明产品角色，不证明真实 provider，不证明 PC-4 或 V11 auto-wake。控制面 operator NULL 与产品 EXECUTE 角色分开。

## Gate

`UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py`

其它断言通过之后，进程发出 `v13: supervisor: ask_user` 并非零退出。该非零是 `unattended_continuation` 的接受形态，不是整门失败。其它失败仍是那个失败。
