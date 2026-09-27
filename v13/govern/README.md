# v13 stage 29 — govern

`goal/stopped|resumed` 是会话级停复。停不等于 cancel，也不改 status。`v13_goal_fingerprint` 不换体 `v13_state_hash`。到顶时批量路径不调用 spawn，直调仍 RAISE。

## RED（L29，翻转前）

复核报告 `docs/reviews/v13-phase-c-phase-b-recheck-2026-09-27.md` §4。时点 HEAD `8678ebff879917c1069e88d4abc2cef8cdc761d3`（`8678ebf`）。库 `agent_v13_pc_recheck`，加载序止于 handoff；advance 仍是 triage 末代。`spawn_budget` 翻到 `max_nonterminal=1`，占用已是 1。

三句话分开：

- 非 explore 批量路径：`v13_advance` 仍调用 `v13_spawn_subsession`，SQLSTATE `P0001`，message_primary **`v13: spawn budget cap`**。SAVEPOINT 回滚后 tool/call 仍在，`child-created` 为 0。留置是整笔回滚，不是跳过。
- 直调 `v13_spawn_subsession`：同一文案。源 `v13/spawn/v13_spawn.sql` 前置比较与插入后复检。本 stage 不换体该函数。
- explore 臂：到顶先 **`v13: explore spawn`**，不到 cap。守卫在 spawn IF 之外。本 stage 保持这条 RAISE。

本 stage 之后，非 explore、无并发复活时，到顶 advance 返回 `waiting` 且不 RAISE。直调仍 RAISE。explore 误用仍 RAISE。终态兄弟被 `user/message` 复活的窗口不承诺零 RAISE，也不承诺绝对不超售（`test_revive_race_backstop`）。

## 停复

`v13_goal_stop` / `v13_goal_resume` 是 INVOKER。守卫 `v13_goal_event_guard` 同序：⓪ `v13_control_operator()` 假则 `v13: session not found`（不读会话）→ 行锁 → seq/turn_no 不变量 → 终态 → busy → 载荷 → 先转移后指纹。折叠只有 `v13_goal_fold`。公开面 `v13_goal_lifecycle` 是薄包装。空会话返回 `running`，不是 NULL。

指纹排除八词：三个 `session/*`、`goal/stopped`、`goal/resumed`、`control/handoff`、`wake/satisfied`、`turn/material_spent`。`v13_state_hash` 与 `v13_transcript_hash` 不改。stop 改变 state_hash，不改变 fingerprint。

停复不沿 `v_goal_tree` 传播。在途 `ready|claimed|unknown` 拒 `v13: goal busy`。终态先于 busy，文案是 `v13: goal lifecycle`。

## 生产绑定

| 题 | 合同已证明（仓库内 SQL+测试） | 未交付（不得写进验收句） |
|---|---|---|
| L32 | operator 可调用 `v13_goal_stop` / `v13_goal_resume`；`SET ROLE v13_route` 真 COMMIT | 无产品按钮、无 driver 绑定。禁止写成「目标已可在 UI 停复」 |
| L29 | 非 explore 批量路径、无并发复活时，到顶返回 `waiting` 且不 RAISE；tool/call 留置；直调仍 RAISE | 禁止写成「spawn 函数已不再报 cap」。复活窗口见上 |
| L21 | stopped → `dont_notify`；resume 后其余条件满足可回 `run_now` | 仓库不注册 `cron.job`。禁止写成「pg_cron 已在生产调度」 |
| L27 | 不新写门。handoff 缺政策 / `enabled=false` 仍拒。`goal/*` 不进 transcript 排除名单 | 驱动器未交付 |

driver 合同：仓库外若有 cron，命令必须是读 hint，仅当 `run_now` 才 `v13_advance`。advance 体内再判一次。守 hint 的 driver 在 `dont_notify` 期间不会触发停期结算；那些事件只属于直接调用 `v13_advance` 的轮次。

`run_now` 不是入队许可。attention 的 `lifecycle` 列不是授权。

## 授权与锁

`v13_spawn_batch_allowed` 是 DEFINER，属主 `v13_spawn_owner`。全链：会话 `FOR UPDATE` → 上行 → `v13_policy_share()` → 咨询锁 → `v13_spawn_budget_snapshot`。wrapper 自身无 `FOR SHARE`。route 有 wrapper 与 snapshot；spawn_owner 有 snapshot；worker / PUBLIC / recall / resolve 对两者均无；route 对 `v13_advisory_class` 无 EXECUTE。

`v13_policy_share` 只锁五行：`capabilities` / `quota_window` / `should_run` / `spawn_budget` / `triage`。`turn_budget` 与 `effect_attempt_cap` 不在协议内。

带内非 operator 依赖 `v13_control_operator`：rolsuper，或对 `v13_route` 的 `USAGE`。测试库里的 NOLOGIN 角色只在测试事务创建，不进安装 SQL。

## 索引

`ix_events_goal_lifecycle` 是 `(session_id, seq DESC)` 的部分索引，`WHERE type IN ('goal/stopped', 'goal/resumed')`，非 UNIQUE。
