# v13 stage 27 — quota_window

资格每次从 `turn/material_spent` 重算。不是奖励，不是负债，不写 `quota/spent` / `quota/voided`。`quota_remaining` 不是本函数。

## 时钟与计次

`v_now` 在 `v13_quota_eligible` 入口捕获一次 `transaction_timestamp()`。窗下界与 slot 间隔都用这个值，比较的存储列只有 `events.at`。函数保持 STABLE。

计次是本会话窗内收据条数，`at` 落在闭区间 `[v_now - window_hours, v_now]`。不沿 `v_goal_tree` 上卷。`slot_minutes` 是最小间隔，不是时间桶：`0` 只看条数；大于 0 时，闭区间 `[v_now - slot_minutes, v_now]` 里已有收据则不合格。未来 `at` 不计入、不占间隔。

同一 advance 里先写收据、后判门，不缓存布尔。advance 仍每次调 `v13_should_run`，gate 现场调 `v13_quota_eligible`。

## 种子

活动 `quota_window` 是松值：`window_hours=8760`，`slot_minutes=0`，`allowed=1000000`。这不是产品额度，也不是「已配置 24 小时 8 次」。收紧 = 新版本并翻转 active，不改函数。翻版由部署 owner/DBA 在单一事务里做（INSERT inactive、灭旧、点亮新版本），禁止逐句 autocommit。

`capabilities.required` 种子是空数组。空数组是「没有额外要求」；缺行是 `v13: capabilities policy`，不是全通过。

## 门

`should_run` version 2 在 stage 26 四门之后追加 `quota_window`、`capabilities`，二者 `effect=block`。`v13_should_run_gate` 只扩闭集和这两支求值。改序仍是新策略版本，不改函数体。

小题⑥正臂在本 stage 行为验收：quota 或 capability 把门打假，前缀三门不早退，`duty<>0`，`snap.failed` 非空，advance 先 append `resolve/failed`，再由 prework 单 gate 返回 `waiting`。零新 effect，无 `triage/hold`。源码在场不等于这臂通过。

## material 时间诚实

`trg_material_time_honest` 是 INVOKER。生产写入（非超级用户、非 `events` 属主）的 `NEW.at` 必须落在 `[clock_timestamp()-60s, transaction_timestamp()]`。成功路径不改写 `at`。表属主和超级用户可以回填测试收据。触发器函数只 REVOKE PUBLIC，不 GRANT。

部分索引 `ix_events_material_spent_at` 是 `(session_id, at) WHERE type = 'turn/material_spent'`，非唯一。
