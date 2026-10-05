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

## R0 重开实现偏差与边界（2026-10-01）

R0 已按复审接受计划实现并完成十条 gate；仅声称 DB owner/superuser 确定性夹具下，根 `v13_advance` 在 ready/claimed 阻断分支可为合格当前 harness 幂等补记 `turn/material_spent`，随后仍 waiting。复审 Oracle group `FA70C826-BE9B-498C-A493-99E67CA085D7`：无 P0/P1；P2 ready/claimed 负例夹具曾先改 human blocker，现已重写为显式将 human 置 succeeded、将 harness 前驱置 ready/claimed，并断言选择器返回的唯一活跃阻断行正是该 harness effect。复跑 `plan_arm` exit 0，库 `ll_plan_arm_79930` 已 DROP，104 checks。

R0 十条全量结果、advance 加载后 SHA-256 `e49c4efa9f45ccd0521be96b28d053c16a4e63c3a113285138d96ad8632da87c`、固定基线哨兵块 byte-restore 证明、临时库清理结果见同日覆盖矩阵 R0 小节。历史 PC-C1…PC-C9 与 P2-C1 记录不覆盖。

未关闭边界：R1 已落地（见下节）；M3 监督 tick 已按 §7.2 接受，但 `unattended_continuation` 仍非 `exit_0`。child 不获得 root receipt；unknown/cancel/stale 夹具上若未付仍在则 tick 失败 `v13: supervisor: unpaid_remaining`。普通 advance 的早记账可影响后续 session-local quota/派发；不证明产品角色 EXECUTE、真实 provider、V11/auto-wake、PC-4、产品可用或无人值守完成。无本期 SQL helper、加载器/其他运行时 SQL/goal_supervise SQL 变化；`v13_loop_driver.sql` 与 `load.py` 相对 `fb295ac` 全等。

## R1 点名入口偏差与边界（2026-10-01）

R1 按 `docs/plans/v13-long-loop-phase-c-r1-m3-plan-2026-10-01.md` 实现 `LoopDriver.settle_once`。仅声称：DB owner/superuser 确定性夹具、Phase A 前缀与完整 Phase C 前缀上，该函数是已点名的根结算入口；T0 与 advance 同事务同根锁；无未付则 quiet；有未付则至多一次 `v13_advance`；返回后 IDLE。不声称无人值守完成、产品角色、真实 provider。

无新增 SQL 函数、无 `load.py` 键、不调用 `v13_harness_settle` / `v13_unpaid_harness_turn`。去掉 `# R1_SETTLE_ONCE_BEGIN/END` 后 `driver.py` 恢复 `fb295ac` 字节。stop 先提交的交错夹具必须先成功写出 `goal/stopped` 再放行 waiter；settle 先持锁的负例断言随后 `goal busy`，两条不可互换。

M3 监督进程已按 §7.2 接受：其它断言通过后发出 `v13: supervisor: ask_user`。`unattended_continuation` 不得写成 `exit_0`。

## M3 监督进程偏差与边界（2026-10-01）

M3 按同一计划实现 `v13/goal_supervisor`。仅声称：单 goal、DB owner/superuser 确定性 Fake 夹具下，监督 tick 可以在人不回答时保持 `waiting` 且不为解卡而 skip；结算走 `settle_once`；unknown/cancel/stale 未付则失败 `v13: supervisor: unpaid_remaining`；`skipped_failed` 安全早退。`unattended_continuation` 仍是 ASK_USER，矩阵 `goal_supervisor` 行是 `expected_nonzero` 不是 `exit_0`。

无 SQL、无 `load.py` 键、不调用 `v13_harness_settle`、不 import `run_turn`、不调用真实 provider。`r0_source_scope` 放行的新跟踪文件仅 `v13/goal_supervisor/` 前缀。不得声称人可以离开生产终端、PC-4、V11 auto-wake、unknown/cancel/stale 墙已被 advance 消化。

## UA 预存红线归因（2026-10-06）

基线在 `b1faa27` 实跑（`v13/` 与 `78e77c7` 相同，stannum 0.5.1）。`r0_source_scope` 的前缀断言红：`plan_arm`、`loop_driver`、`frontier_gap`、`goal_supervise`、`goal_supervisor`。`extra` 恰 12 个文件，全在 `v13/goal_supervisor/`、`v13/fair_claim/`、`v13/fair_driver/`。`loop_driver` 是同一断言的第五个调用方。`fair_driver` 当时 38 checks，退出 0。`fair_claim` 的 `stage_bytes` 另红：干净树上 `git diff HEAD -- v13/load.py` 为空，谓词仍要求 diff 含 `fair_claim`，`tail_ok` 为真。父同意按 `frontier_gap` 的干净树分支补上，并只放开该函数相对 `78e77c7` 的差异。

提交②把冻结中心改成三前缀路径闭集、已知文件钉 `78e77c7`、`load.py` 只许表尾规范追加。不改 `load.py` 字节，不改 driver、setup_db、fair SQL。修复后、提交前：`plan_contract` 93、`plan_read` 11、`plan_arm` 104、`loop_driver` 91、`workflow_bind` 8、`real_chain` 24、`workspace_admit` 65、`workspace_exec` 54、`frontier_gap` 59、`goal_supervise` 172，均退出 0。`goal_supervisor` 62 checks 后发出 `v13: supervisor: ask_user`，退出 1。`frontier_gap` 与 `goal_supervise` 自身的 `stage_bytes` 未再变红。`fair_claim` / `fair_driver` 的 `stage_bytes` 比较 `git diff HEAD`，范围含本提交正在修改的 `v13/plan_arm`、`v13/goal_supervisor`、`v13/fair_claim`；`load.py` 的 diff 长度为 0。这两条在本提交成为 HEAD 之后复跑，退出 0 才推送。不得把 `goal_supervisor` 写成 `exit_0`，不得声称无人值守完成。
