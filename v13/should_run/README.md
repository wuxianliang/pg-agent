# v13 stage 26 — should_run

新 effect 的唯一投影门。函数不入队、不 closeout、不改 status。不写停/复，不调用 `v13_goal_lifecycle`。

## 读点

一个函数，布尔不缓存。`>` = `should_run.gates` 从左到右短路：第一个条件成立且 `effect=block` 的门获胜。`shadow` 不把布尔变成假。

| 标签 | 位置 | 假时 |
|---|---|---|
| P-spawn | explore RAISE 之后、`v13_spawn_children` 之前，且仅当 `v_calls` 非空 | `status='waiting'`（带 `session_id`）后返回，不 spawn |
| P-harness | approval 臂与 continuation 臂各自臂首，budget closeout 之前 | 同上，不入队、不写孤立 `turn/route` |
| P-tail | `v13_triage_prework` 里 duty 的 `RETURN 'waiting'` 之后、`IF v_dec='human'` 之前 | 同上，不写 `triage/hold` |

`v13_policy_share()` 在 explore 之后、`IF jsonb_array_length(v_calls) > 0` 之外无条件调用。锁序只覆盖 `capabilities` / `quota_window` / `should_run` / `spawn_budget` / `triage`。`turn_budget`、`effect_attempt_cap` 不在协议内。

前缀（终态、unknown 墙、未消费 cancel、在途 ready/claimed）不进门。material 收据、finish/reject closeout、wake 也不进门。explore 路由的 tool/call 在门之前仍 RAISE `v13: explore spawn`，这是假路径的唯一例外。

## 返回

假路径返回 `'waiting'`，读点之后零新 effect，不 closeout，不写第二套 hold。`duty_cycle` 种子是 `shadow`：默认 duty=0 仍先 spawn，再由 prework 写 `triage/hold`。改成 block 是新策略版本，不改函数。

`resolve/failed` 预检在 prework 调用之前，仅当 `duty<>0 AND NOT should_run AND snap.failed IS NOT NULL`。stage 26 只钉负臂（duty=0 不预写）和源码位置。正臂行为在 stage 27；源码在场不等于正臂通过。

prework 三条入队出口的行为假路径也在 stage 27（`test_quota_blocks_prework_enqueue`、`test_quota_blocks_repair_replan_enqueue`）。本 stage 只断言共同入口上的那一处 gate。

## 生产绑定

读点在 `v13_advance` 体内，库内已生效。driver 不能用 hint 跳过 advance 的再读。策略翻版由部署 owner/DBA 在单一事务里做（INSERT inactive、灭旧、点亮新版本），禁止逐句 autocommit。不由 route/worker/driver 执行。

parent 链在 UPDATE 上不可变，执法者是 stage 18 的 `trg_sessions_fork_cols_immutable` / `v13_spawn_cols_guard`，文案 `v13: fork columns are write-once (session %)`。本 stage 不另装守卫。

快照键复制 `v13/catalog/test_catalog.py` 的 `v13_probe` + `{snap, envelope, remaining, failed, abandon}`，不另造信封。安装前 `to_regprocedure` 为空，由安装 DO 的 `v13: should_run baseline` 钉住。
