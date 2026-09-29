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
