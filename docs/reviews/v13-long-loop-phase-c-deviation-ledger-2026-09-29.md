# v13 长循环 Phase C 偏差台账（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md`。没有偏差就不把未跑的后续 stage 写成偏差。未关闭项不得写进验收句。

| ID | 项 | 状态 | 说明 |
|---|---|---|---|
| PC-C1 | 写者与 gap 闭集 | 已核，按此实现 | 写者拒绝 `link.id` 为 JSON null，故 `successor_missing` 不进入实现闭集。`dangling_link` 经 `link_successor` 再提交不含目标的计划产生。`writer_cannot_produce_gap_stops` 因此不为 `v13: replan gap: ask_user` |
| PC-C2 | 水位种类 | 已核 | 加载后只有 `user/message`。夹具字面用该种类。steer 不进谓词 |
| P2-1 | `v13_frontier_project` 非 NULL seq 水位种类 | 开放，不挡 | 非 NULL `p_before_seq` 分支把失效种类写死 `user/message`。当前无调用者传入非 NULL seq，路径不可达。有调用者传入非 NULL seq 前，该分支须收成与 `v13_plan_current` 同闭集；对不上按 `v13: frontier gap: ask_user` 停 |
| P2-2 | `hash_excludes_counters` 义务条数快照时点 | 开放，不挡 | 义务条数快照在 counter UPDATE 之后才记。可挪到 UPDATE 之前钉住，排除「计数器副作用改变义务条数」的误读 |
| P2-3 | `gap_cap_33` 返回体哈希 | 开放，不挡 | 可加一条：第 33 条时返回体 `::text` 哈希与 `frontier_hash` 不同，防未来驱动器自算哈希 |
| PC-C5 | `interaction/offered` 守卫残留面 | 接受残留（E50A7595） | 守卫现状：`v13/control/v13_control.sql:421-482` WHEN 闭集不含 `interaction/offered`；`events.type` 开放词表，不拒插；无载荷校验；全树零命中。裁决读法：「尚未被允许」=守卫会拒插；开放词表不拒插、无载荷校验，两种失败形态都不成立。§4.4 把全部执法设计在 `v13_interaction_offer` 内；§9 自身禁加触发器与之自洽（workflow/pointer 的触发器是 Phase A §5.5 明文，不反推 C5）。接受残留面：裸 INSERT `interaction/offered` 无载荷校验；该类不在 `v13_goal_fingerprint` 排除名单，裸插会改指纹。不声称守卫已闭合载荷。gate `UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py` 退出码 0 |
| PC-C7 | 结算存储快照绑定 | 已修复并实测 | Oracle `301594C5` 两路共同 P1：仅检查入参 failed 能被删键或置 null 绕过。现根锁后对目标 effect `FOR UPDATE`，要求 `effects.result IS NOT DISTINCT FROM p_snap`，stopped 判断只用绑定后的存储结果。`stopped_failed_snap_binding`、`stopped_failed_null_forgery_rejected`、`stopped_failed_snap_no_advance`、`stopped_failed_null_still_settles` 与无 failed 正例均通过，99-check gate 退出码 0 |
| PC-C8 | 收据候选与活体前驱一致 | 已修复并实测 | Oracle `301594C5` 指出 settle 不得自写胜者。`plan_arm:449` 的活体臂先调用 `v13_harness_predecessor`，选择器 `control:180-194` 已有排序与 LIMIT。本期读函数及 settle 直接消费该选择器，再验证未付谓词，不新增排序。两条物理未付行时仅当前前驱可结算，旧行无收据；前驱已付后不回落旧行。`multiple_unpaid_candidates`、`settled_predecessor_does_not_fall_back` 实测通过 |
| PC-C9 | 未退役 user_gate 通知 | 已修复并实测 | Oracle P2：通知事实不限 selector 的 operator 派发状态。现排除 `done/dropped`，覆盖合法 `runnable -> waiting`（通过写者 todo_delta）与初始 blocked。写者仍拒绝初始 waiting user_gate；没有改 Phase A 写者 |
| P2-C1 | 非 operator 显式 NULL 的隔离测试 | 开放，不挡 | gate 已测试根 UUID actor 拒绝；尚无非 operator 显式 NULL 的角色夹具。SQL 的 operator 检查存在，但当前超级用户测试不声称此角色路径已实跑，不声称产品角色闭合 |
