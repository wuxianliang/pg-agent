# v13 长循环 Phase D 偏差台账（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-d-plan-2026-09-29.md`。没有偏差就不把未跑的后续 stage 写成偏差。未关闭项不得写进验收句。

| ID | 项 | 状态 | 说明 |
|---|---|---|---|
| PD-H1 | 帽的洞 | 接受残留（`accept_hole`） | 活体 `v13_claim` 不取 13002，不读 `global_concurrency`，帽满之后仍可领走。帽只约束 `v13_claim_fair`。不建触发器拦所有 `ready→claimed` |
| PD-H2 | 重挂绕过路径闸 | 接受残留 | `v13_enqueue_effect` 的 `failed\|cancelled` 重挂是 `UPDATE effects SET status='ready'`，不触发只挂 BEFORE INSERT 的 `trg_effects_workspace_path_lock`。不把触发器扩成 `BEFORE UPDATE OF status` |
| PD-H3 | `cap=1` 连续领用残留 | 接受残留 | 只指仍回到 `ready` 的路径：`judge` / `mgraph_consolidate` 经未改的 `v13_requeue_stale`（attempt 仍有余量），或 `failed\|cancelled` 经 `v13_enqueue_effect` 重挂。种子是 2，夹具不走这条 |
| PD-H4 | 13002 队头阻塞 | 接受残留 | 13002 在会话行锁之前取得。排头的会话锁等待会阻塞所有后续公平领用。活体 `v13_claim` 不取 13002 |
| PD-H5 | infinity 占席 | 接受残留 | 打开者留下的 `claimed` 且 `lease_until = infinity` 计入 `claimed_count`。本期不释放、不续租、不调用 `v13_goal_lease_once` |
| PD-H6 | 有限租约释放依赖外部 requeue | 接受残留 | 有限租约过期后，席位只有在外部调用未改过的 `v13_requeue_stale` 时才释放。`fair_driver` 不是这个调用者 |
| PD-H7 | 打开者仍 `not_single_tree` | 指定行为 | 两个已提交根上调用打开者仍 RAISE `not_single_tree`。跨根 `path_busy` 不经过打开者 |
| PD-H8 | 未证明产品角色 | 开放，不挡 | 本期不给 `v13_claim_fair` GRANT。超级用户夹具不证明生产可运行。`claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色 |
| PD-H9 | 第二份路径谓词漂移 | 接受残留 | `v13_path_conflict_locked` 是第二份路径谓词。打开者体内扫描保持 Phase B 原文，不抽取、不替换。两份谓词可能漂移 |
