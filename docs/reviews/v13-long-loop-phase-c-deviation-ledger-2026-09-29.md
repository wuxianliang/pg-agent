# v13 长循环 Phase C 偏差台账（2026-09-29）

对照 `docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md`。没有偏差就不把未跑的后续 stage 写成偏差。未关闭项不得写进验收句。

| ID | 项 | 状态 | 说明 |
|---|---|---|---|
| PC-C1 | 写者与 gap 闭集 | 已核，按此实现 | 写者拒绝 `link.id` 为 JSON null，故 `successor_missing` 不进入实现闭集。`dangling_link` 经 `link_successor` 再提交不含目标的计划产生。`writer_cannot_produce_gap_stops` 因此不为 `v13: replan gap: ask_user` |
| PC-C2 | 水位种类 | 已核 | 加载后只有 `user/message`。夹具字面用该种类。steer 不进谓词 |
| P2-1 | `v13_frontier_project` 非 NULL seq 水位种类 | 开放，不挡 | 非 NULL `p_before_seq` 分支把失效种类写死 `user/message`。当前无调用者传入非 NULL seq，路径不可达。有调用者传入非 NULL seq 前，该分支须收成与 `v13_plan_current` 同闭集；对不上按 `v13: frontier gap: ask_user` 停 |
| P2-2 | `hash_excludes_counters` 义务条数快照时点 | 开放，不挡 | 义务条数快照在 counter UPDATE 之后才记。可挪到 UPDATE 之前钉住，排除「计数器副作用改变义务条数」的误读 |
| P2-3 | `gap_cap_33` 返回体哈希 | 开放，不挡 | 可加一条：第 33 条时返回体 `::text` 哈希与 `frontier_hash` 不同，防未来驱动器自算哈希 |
