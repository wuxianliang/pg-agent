# v13 frontier_gap

Phase C 第一段。交付 B4 语义缺口投影与插入，以及 D3 断言。无 advance 替换，无 provider，无监督循环。超级用户夹具不是产品角色证明。Fake 退出码 0 不是产品可用。

## 种子

| 种子 | 值 | 不是 |
|---|---|---|
| `frontier_gap_cap` | 32 | 席位常数 |

第 33 个缺口使 `omitted_count = 1`、`omitted_complete = false`。投影仍零写。插入者 RAISE `v13: replan gap: cap`。

## 开工重读

| 项 | 结论 |
|---|---|
| `replan/required` 载荷 | `v13/control/v13_control.sql:425-428`、`:447-448`。键恰好 `schema_version`。`source_effect_id` 必非 NULL。后续 stage 未替换该触发器 |
| `v13_plan_apply_id` | `(text) RETURNS uuid`，`IMMUTABLE`。STABLE 折叠可以调用。不另写一份。Python 不调用 |
| `v13_plan_current` | 一参。水位种类只有 `user/message`。`p_before_seq` 为 NULL 时投影调用它；非 NULL 时在本函数内按 `seq < p_before_seq` 重折，不改 Phase A |
| `jsonb::text` | PostgreSQL jsonb 对象键按字节序排出。两次独立 `jsonb_build_object` 的 `::text` 相等。不另写序列化器 |
| 写者与 gap kind | `successor_missing`：写者要求 `link.id` 为 uuid 文本，该 kind 不进入实现闭集。`dangling_link`：经写者先 `link_successor` 再提交一份不含目标的 `plan/committed` 可以产生 |
| `v13_recover_idle` | 加载后 `v13/govern/v13_govern.sql:453`。不 INSERT effect，不调用 advance |
| 函数/目录撞名 | 本段三个函数与三个目录在开工时均不存在 |

## 实现闭集

缺口实现闭集只有 `dangling_link`。`blocker`、monitor、streak、attempt、配额都不是缺口。

没有伪造配额账。

## 函数

- `v13_frontier_project(uuid, bigint)` STABLE。零写。`p_before_seq` 为 NULL 表示当前流。返回未截断哈希列、驱动器读的 32 条 `gaps` 前缀、`has_obligation`、`omitted_count`、`omitted_complete`。
- `v13_obligation_open(uuid)` STABLE。零写。只重放 `plan/committed` 与 `todo/delta`。开放位 = 义务行存在且该键仍在当前义务折叠。
- `v13_replan_gap_insert(...)` VOLATILE。唯一插入者。载荷恰好 `{"schema_version":1}`。自然键 `replan:{root}:{gap_kind}:{subject}:{object 或空}`，不含 `plan_id`。授权先于重放。

错误前缀 `v13: replan gap:`。token：`auth`、`stopped`、`terminal`、`no_gap`、`stale`、`canonical`、`cap`、`not_single_tree`。

新函数 `REVOKE ALL FROM PUBLIC`。不写 stannum GRANT。零 tools DML。无第二份 `v13_advance`。

## 加载后 signals 段

6 参 `v13_complete` 的 signals 路径在 `v13/acl/v13_acl.sql:429-438`。该段源文件 SHA-256：

`f6803f8aec2283d5315f921111ef94c725241f64bee740cec8aee47f1d80830a`

经 complete 写出的 `replan/required` 挂真实 effect id，不算义务。

## Gate

`UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py`

断言名按计划 §7.1。

保持未决：产品库名、产品角色、stannum GRANT、V11、席位常数、PC-4、steer 活体字面。

## R0 源码冻结兼容（2026-10-01）

Frontier SQL 与既有功能测试均未修改。为允许已接受的 plan_arm R0 重开，stage_bytes 不再要求整个 plan_arm 对 HEAD 空 diff；改用 `v13.plan_arm.test_plan_arm.r0_source_scope` 对固定 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 的正向证明。删除唯一新增 R0 声明/receipt 哨兵块后，plan_arm SQL 必须与基线 bytes 相同；其它运行时文件和原测试仍被冻结。基线对象缺失则失败，提交前后均有效。此调整不改变 Frontier 哈希/义务语义，也不将 R0 的记账能力归入 Frontier。

R1 把 `v13/loop_driver/driver.py` 从整文件相等改为哨兵还原：去掉 `# R1_SETTLE_ONCE_BEGIN/END` 后必须回到该基线字节。Frontier SQL 仍全等。
