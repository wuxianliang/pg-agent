# v13 长循环 Phase B 偏差台账（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-b-plan-2026-09-29.md`。没有偏差就不把未跑的后续 stage 写成偏差。未关闭项不得写进验收句。

| ID | 项 | 状态 | 说明 |
|---|---|---|---|
| PB-1 | `advance_does_not_dispatch_tool` 夹具裁决 A′ | 已裁决，按此实现 | Oracle 三路终审 group `DDDACEB6` 一致裁决 A′。计划 §5.1 该断言的夹具前提是文本缺陷：「带 claimed 行进入 `WHEN 'tool'`」按构造不可满足。`plan_arm:399-402` 的 `ready`/`claimed` 臂前门先于 `:749` 的臂。计划引的 govern `:764-773` 是书写时旧行号。不停工、不改计划原文、不替换 `v13_advance`。通过条件是 P∧C∧S。收窄句仍有效：「不把臂前返回算成退出码 0」禁的是未经对照证明的 waiting；通过的是被对照证明的 claimed 门 waiting 三件合取。裸 waiting 与「进不了臂」本身都不是退出码 0 |
| PB-2 | `human_pending` 行文漂移 | 已裁决，以活体为准 | 活体 `v13_pending_human` 在 `v13/control/v13_control.sql:121-128`：`kind='human'` 且 status 属于 `ready`、`claimed`，不含 `unknown`。计划 §4.5 重读前句子含 `unknown`。实现与 `human_pending_rejected` 以活体为准 |
| PB-3 | 行号基线 | 已裁决 | 被测函数是 `v13/plan_arm/v13_plan_arm.sql`。臂前门 `:399-402`。`WHEN 'tool'` `:749`。该臂内 enqueue `:764-776`。`v13/govern/v13_govern.sql:785-788` 不是被测函数 |
