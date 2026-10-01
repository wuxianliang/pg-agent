# v13 goal_supervise

Phase C 第二段。交付 C5 旁路、C6 折叠、D1 政策与投影、D2 检查、未付 harness 结算包装、ambiguous hold、一次租约。无文件系统执行，无 advance 替换。超级用户夹具不是产品角色证明。Fake 退出码 0 不是产品可用。无人值守 skip 仍未授权。V11 未读，不得声称 auto-wake 已闭合。

## 开工重读

| 项 | 结论 |
|---|---|
| 事件守卫 `interaction/offered` | `v13/control/v13_control.sql:421-482`。WHEN 闭集不含该类。`events.type` 开放词表，不拒插，无载荷校验。全树零命中。父裁决（E50A7595）：该 §9 停点不成立。执法在 `v13_interaction_offer` 内。接受残留面见台账 PC-C5 |
| human 两键 | `plan_arm` 副本 `schema_version`、`interaction_ref`。无 options、无 timeout |
| artifact 列 | `artifacts.artifact_id`、`produced_by`，无会话列。具名写者 `v13_artifact_land(uuid,text,jsonb)`，只落 `kind='context'` |
| hint 签名 | `v13_scheduler_hint(uuid) RETURNS text`，三值 `run_now` / `wait` / `dont_notify` |
| stop 根锁 | `v13/govern/v13_govern.sql:252-255` 锁 `sessions.session_id = p_sid FOR UPDATE`。本期写函数映射到根后锁同一行，effect 锁排在根锁之后 |
| 收据前驱 | `v13/plan_arm/v13_plan_arm.sql:449` 调用 `v13_harness_predecessor`；选择器在 `v13/control/v13_control.sql:180-194`，先选当前前驱，再检查是否未付。候选读与结算均调用它，不自行挑旧未付行 |
| requeue | 加载后活体是 `v13/mgraph/v13_mgraph.sql:2716` 的 `CREATE OR REPLACE`（control `:1079` 被其后键替换）。选择 `status='claimed' AND lease_until < clock_timestamp()`。`infinity` 与 NULL 不满足 `<`，不收回。`pg_get_functiondef` SHA-256：`b2ea18edcae6597121536435847208852b86724830eaee07a79caab8761fec70` |

## 种子

| 种子 | 值 |
|---|---|
| `observe_return_cap` | 4 |
| `evidence_refs_cap` | 4 |
| `offer_options_cap` | 4 |

## 函数

- `v13_unpaid_harness_turn(uuid)` STABLE。只返回活体 `v13_harness_predecessor` 选中的合格未付行，不加 LIMIT、不加 ORDER。未付 = 尚无同源 `turn/material_spent`。物理上仍有旧未付行不意味着它是当前前驱；当前前驱结算后不会回落到旧行。
- `v13_harness_settle(uuid, uuid, uuid, jsonb)` VOLATILE。根锁之后用加载后的 `v13_harness_predecessor` 唯一选当前候选；不在此处重写排序/LIMIT。`p_snap` 必须与该 effect 的 `effects.result` 完全相等，驱动器原样复制该 jsonb，不增删 `failed` 或 `route`。已 stopped 且存储 `failed` 非 null 时返回 `skipped_failed`，不调用 advance；否则同一事务调用已有 `v13_advance`。不替换 advance。
- `v13_interaction_offer(uuid, uuid, uuid, jsonb)` VOLATILE。返回 `event_id`。不插 approval 臂。监督进程不调用。
- `v13_observe_fold(uuid, uuid)` STABLE。零写。授权失败 RAISE，不把 `v13_observe` 空返回当成没有事实。
- `v13_notify_project(uuid)` STABLE。零写。不插 `notify/sent`，不建 outbox。不是 exactly-once。
- `v13_goal_ambiguous_hold(uuid)` STABLE。只读 claimed 的工作区打开者行。
- `v13_goal_lease_once(uuid, uuid, uuid)` VOLATILE。与 `v13_goal_stop` 相同，先锁根 `sessions` 行，再锁目标 effect；有限租约一次延长 60 秒。infinity 与 NULL 零更新。
- `v13_evidence_check(uuid, uuid, jsonb)` STABLE。监督进程不调用。

错误前缀：`v13: interaction offer:`、`v13: observe fold:`、`v13: harness settle:`、`v13: goal lease:`、`v13: evidence:`。

新函数 `REVOKE ALL FROM PUBLIC`。不写 stannum GRANT。零 tools DML。无第二份 `v13_advance`。

## C5

合法的人等待是非终态 `waiting`。本期不实现自动 skip。无人值守 skip 仍未授权。旁路不接入 advance。

## 收尾证据

`v13_harness_settle` 的候选选择与 `v13_harness_predecessor` 对齐；多条物理未付行不会由 settle 另选胜者。存储快照绑定、stopped+failed 跳过、`failed: null` 仍结算、通知的 blocked/waiting 门状态均由 gate 覆盖。监督进程仍不直接调用 `v13_advance`。

## Gate

`UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py`

断言名按计划 §7.2。

2026-10-01 实跑退出码 0，99 checks；库 `ll_goal_supervise_31540_9afbe8` 已 DROP。同窗口九个回归 gate 均退出码 0，命令与库名见 Phase C 覆盖矩阵。

## R0 重开兼容与新增测试（2026-10-01）

以上是 M2 历史记录。R0 不修改本目录 SQL、wrapper 授权/快照绑定/skipped_failed，也不新增加载键。变化来自唯一 plan_arm advance 的 root ready/claimed 分支：可补记当前 harness 收据，随后仍 waiting；human/claimed workspace 不被绕过派发。unknown/cancel/terminal/stale 墙仍可能先返回，不能将这类 waiting 当收据成功。

stage_bytes 用固定 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 正向证明替代 plan_arm/frontier 测试目录的空 diff 条件，不移除其它运行时文件保护。本目录 SQL bytes 保持基线相同，并真正重载自身 SQL、比较加载前后 advance/fingerprint/recover/should_run/hint 函数哈希。

新增 R0 测试在独立随机 `ll_r0_gs_*` 库中累计加载到 stage 38，根夹具 version 2、首 advance 前 direct override。只清理本次创建的库；并发使用 pg_blocking_pids 确认锁等待后放行，轮询间隔不是胜者依据。验证：root human ready/claimed 的 progress/finish、workspace 完整行不变、同源收据且队列零增长、两连接只付一次、effect 等锁后重读、child 不上锁 root。stopped/failed 的 wrapper 零 advance 用独立库 track_functions 统计并在 rollback/flush 后读取，另有 null/缺键调用一次的正对照，不以 receipt=0 冒充零调用。

R0 结果见覆盖矩阵的单独行。它不修改 M1/M2 历史证据，不证明 M3、产品 operator EXECUTE 权限、V11、PC-4 或生产无人值守。
