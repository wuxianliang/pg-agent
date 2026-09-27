# v13 stage 28 — attention

`v13_attention` 与 `v13_scheduler_hint` 是 STABLE 投影。零事件、零收据、不改 status。hint 不调用 advance，attention 不调用 hint。秩不是调度队列。

## 返回行数预算

签名 `v13_attention(p_root uuid, p_max_rows integer DEFAULT 512)`。`p_max_rows` 是返回行数预算，范围 1..1024。NULL、小于 1、大于 1024，或 `v_goal_tree` 行数超过该值，都 RAISE `v13: attention limit`，不调 gate、不截断、不分页。

这不是资源上限，也不是资源契约。预算只约束返回行数和 gate 调用数。它不保护 `v_goal_tree` 内部的整树遍历：传 1 仍扫全树，计数超限后才失败。把上限前移到树遍历要另裁。

## 排序

`attention_rank` 从 1 起，只作输出列，不落表。非终态里 human 阻塞最靠前，能跑的排在被阻塞的后面，终态整段沉底。同层用 `session_id` 升序。`goal_stopped` 与 `duty_cycle` 臂留在 CASE 里；本 stage 不读 `goal/stopped`，默认种子下 duty 是 shadow，不会成为 `blocked_by`。

`blocked_by` 来自 `v13_should_run_gate`。`should_run` 是 `blocked_by IS NULL`，不再调布尔包装。

## hint

返回词只有 `run_now`、`wait`、`dont_notify`。第一条可执行语句检查会话存在，未知会话是 `v13: unknown session %`。

终态 → `dont_notify`。未消费 cancel：无 claimed/unknown → `run_now`（ready 不算待结算）；有 claimed/unknown → `wait`。然后才是在途、pending human、`duty_cycle=0`、should-run 假，都是 `wait`。`duty_cycle=0` 且没有未消费 cancel 时 hint 为 `wait`，且不写 `triage/hold`。

分支 3.5 在存在未认领 `tool/call` 且 `v13_spawn_budget_snapshot` 为假时返回 `wait`。这是退避，不是入队许可。无 tool/call 的满树会话仍走 `run_now`。snapshot 是唯一预算逻辑，无锁；hint 两参调用，尾参默认 NULL。缺行、坏键、超 int 范围是 `v13: spawn_budget policy`。环或上行深度超过 64 是 `v13: spawn root cycle`。

守 hint 的 driver 在 stopped（`dont_notify`）期间不会触发停期结算事件。那些事件只属于直接调用 `v13_advance` 的轮次。本 stage 没有 stopped 分支；stage 29 才插入。

## 生产绑定

| 题 | 合同已证明（仓库内 SQL+测试） | 未交付（不得写进验收句） |
|---|---|---|
| L5 | 秩是输出列；双调用零事件；不落表、不成 VIEW | 无产品界面。禁止写成「注意力队列已在调度」 |
| L21 | `v13_scheduler_hint` 可重复调用且零事件；advance 自己会再读 should-run | 仓库不注册 `cron.job`。禁止写成「pg_cron 已在生产调度」 |

driver 合同：仓库外若有 cron，命令必须是读 hint，仅当 `run_now` 才 `v13_advance`。advance 体内的读点就是再判一次。`run_now` 不是入队许可，也不是已经执行。

## 授权

三个函数同事务 `REVOKE PUBLIC` + `GRANT v13_route`。route 对 snapshot 的 EXECUTE 在本 stage 授予。`v13_spawn_owner` 的 snapshot 授权留到 stage 29，与 wrapper 同一事务。
