# v13 plan_read

Phase A 第二段。交付 A3：STABLE 库存与前沿。零写，不入队。不替换 `v13_advance`，不 `CREATE OR REPLACE` `v13_plan_current`。`v13_selected_todo` 与 `v13_plan_gate` 不在本目录；§7.2 的交付是库存与前沿，派发读留给 `plan_arm`。

超级用户夹具不是产品角色证明。本目录不证明产品库名、产品角色、stannum GRANT、PC-4，也不证明 material 已扣。

## 种子帽

这些数字是 Phase A 种子，不是 LoopX 64/8/5，也不是 `spawn.sql` 的深度 64。不得静默修改。

| 种子 | 值 |
|---|---|
| inventory_scan_cap | 32 |
| inventory_return_cap | 32 |
| horizon_items | 4 |
| horizon_relations | 4 |
| horizon_gaps | 1 |
| item_text_cap | 1024 |
| 规划 provider 尝试 | 2 |
| 摘录字符帽 | 1024 |

两个库存帽相等。函数不用 `LIMIT 32` 冒充扫描硬顶。循环纳入 32 行后只再取紧接着的 1 行做探测，探测行不进入载荷，也不增加 `rows_examined`。`omitted_count` 因此只是 0 或 1，不是剩余总数。

## 本 stage 的选择

- 空库存的三个计数是 0。`omitted_count = 0` 时 `omitted_complete = true`，包括 0 条。`omitted_count = 1` 时为 false。没有第三态。
- 当前成员只来自 `v13_plan_current` 的 `canonical.todos`。水位失效后折叠里还有旧 todo，库存仍是空。不扫描成员集之外的历史来做精确总数。
- 顺序是该计划事件的 `events.seq`，再 `todo_id` 的 uuid 字节序。写者已经要求数组按这个字节序排好。返回的 id 是这个序的前 32，不是「行数看起来对」。
- `item_text_cap` 用 `char_length` / `left(..., 1024)`，与写者拒绝 `char_length > 1024` 的同一把尺。1024 字原文原样返回。
- gap 的「未退役 blocker」是当前成员里 `task_class = blocker` 且 status 不是 `done` 或 `dropped`。指向不在当前成员集中的 `successor`/`resume` 边也是 gap。两者按 `seq` 再 uuid 字节序取第一条。gap 投影零 INSERT，不写 `replan/required`。
- relation 是载体属于当前成员的 `successor`/`resume` 边，最多 4，另有省略标志。
- 子会话调用读的是根流。子上的 `workflow/pointer` 或形状合法的 `plan/committed` 不改变根的当前计划。
