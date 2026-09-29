# v13 长循环 Phase A 偏差台账（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md`。没有偏差就不把未跑的后续 stage 写成偏差。未关闭项不得写进验收句。

| ID | 项 | 状态 | 说明 |
|---|---|---|---|
| L1 | `v13_plan_apply_id` version nibble = 8 | 选择，未当偏差关闭 | 摘要是 SHA-256 前 16 字节。variant 按 RFC 4122（`10xxxxxx`）。RFC 4122 没有 SHA-256 版本号，version 5 被定义为 SHA-1，所以 nibble 用 8，不冒充 SHA-1。父若退回，停，不另造比较器 |
| L2 | 空事件流水位 | 选择，未当偏差关闭 | 没有最大 `seq` 时 `plan_commit` RAISE `waterline`。不发明 `-1` 哨兵 |
| L3 | version 2 种子不在本 stage | 未关闭，按计划后置 | `explicit_version_binds_column` 用夹具 `default` version 99 证明入口转发显式 version。version 2 产品种子留给 `real_chain`，避免本 SQL 先插入一份不一致的冻结体 |
| L4 | `steer/injected` | 未关闭 | 谓词只有 `user/message`。本 stage 不插入该字面。加进谓词之前必须 `ASK_USER` |
| L5 | 产品角色 / stannum / PC-4 / 产品库名 | 未关闭 | 超级用户夹具不是证明。新 SQL 不写 stannum GRANT |
| L6 | 超级用户裸 INSERT | 已知洞，不是产品路径 | 形状合法的裸 INSERT 可绕过水位。不 REVOKE 旧授权。驱动器静态检查在 `loop_driver` |
| L7 | 绑定窗 | 未关闭 | `plan_arm` 退出码 0 之前不得声称已闭合 |
| L8 | Fake 绿 | 不是产品可用 | `plan_contract` 与 `plan_read` 退出码 0 只证明对应目录合同 |
| L9 | 空库存 `omitted_complete` | 选择，未当偏差关闭 | 0 条的三个计数是 0。`omitted_count = 0` 时 `omitted_complete = true`，包括空库存；`= 1` 时为 false。不把「全 0」读成布尔 false |
| L10 | gap 的未退役 | 选择，未当偏差关闭 | 当前成员里 `blocker` 且 status 不是 `done` 或 `dropped`。指向成员集外的 `successor`/`resume` 边也是 gap。父若要求 `done` 仍算缺口，停，不改成静默放行 |
| L11 | `v13_selected_todo` / `v13_plan_gate` | 未关闭，按 §7.2 后置 | 本目录只交库存与前沿。派发读留给 `plan_arm`。本 stage 不声称这两个函数已交付 |
| L12 | claim 路径用的作用域 UPDATE | 偏差，请父裁决 | 17 项闭集未列任何 claim 动词，但 B6 enqueue 行点名驱动器存在 claim 路径（只禁其上的 `v13_recover_idle`），且 complete 要求 effect 处于 `claimed`。驱动器在 complete 同一事务内对即将 complete 的那个 effect 做领取 UPDATE（与活体 `v13_claim` 体、stage 测试 `settle` 夹具同形）。不用 `v13_claim` 本体：它领全局最老 ready 行，与本目录按会话伺服的 pump 不合。领取与先读到的不符时回滚放弃 |
| L13 | 只读投影 `v13_probe`/`v13_goal_lifecycle`/`v13_plan_map_root`/`v13_plan_todo_fold` | 偏差，请父裁决 | 构造 advance 快照与 needs_human 谓词需要。零写，不属控制动词。`snap_of` 里同步 `context_active_revision` 的 UPDATE 是仓库既有夹具水暖 |
| L14 | `needs_human` 不用 `v13_selected_todo` | 选择，未当偏差关闭 | B1 判定顺序要求 `user_action` 先于 wait 命中；human effect 绑定后 `v13_selected_todo` 为 0 行，改用 §5.4 谓词直读 fold（`user_gate|user_action|blocker` 且 status ∈ `pending|runnable|blocked`） |
| L15 | `repair`/`replan`/`capability_adapter_handoff` 的判定位置 | 选择，未当偏差关闭 | 作为 upstream_word 建议在 terminal/stopping/**user_action 之后**、wait 条件之前折叠成 `wait`，零插入；不压 human 出口（首轮复审 P0，已改）。若父要求排在 wait 条件之后，改一行判定序即可，不改出口面 |
| L16 | 尝试上界不持久化 | 选择，按计划 §5.2 关闭 | 成本计数（provider 调用次数）只留在进程内 `attempts_used` 加测试日志，不新增 plan/cost 事件。这与领取序号 `effects.attempt_no` 无关：claim UPDATE 的 `attempt_no=attempt_no+1` 是活体领取围栏协议（v13_claim 体同形），`RETURNING` 值进 `v13_complete`；静态检查把它冻结为驱动器源内恰一处，不会扩散成成本落库。复审建议把成本计数写成 attempt 列被拒（计划 §5.2 明文）；无人值守不在本相位 |
