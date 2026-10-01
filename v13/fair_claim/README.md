# v13 fair_claim

Phase D 第一段。交付 `global_concurrency` version 1、`v13_claim_fair`、`v13_fair_eligible`、`v13_fair_snapshot`、路径函数与 BEFORE INSERT 触发器。无驱动器循环，无 provider，无 `CREATE OR REPLACE v13_claim` / 第二份 `v13_advance`。超级用户夹具不是产品角色证明。Fake 退出码 0 不是产品可用。未证明 material 已扣。未证明产品角色。

## 开工重读

| 项 | 结论 |
|---|---|
| `SQL_LOAD_ORDER` 表尾 | 装载前缀止于 `goal_supervise`（stage 38）。本 stage 只追加 `fair_claim` |
| `13002` / `13003` / `global_concurrency` / 六个新函数名 | 装载前 `v13/**/*.sql` 零命中 |
| 活体 `v13_claim` 四臂 | `status='ready'`、`v13_attempt_ok(kind, attempt_no)`、`op_seq IS NULL` 或同 session/scope 的 `min`、`v13_requires_worktree(tool_name)` 且无 `worktree` latch 则跳过 |
| `v13_advisory_class` | 仅 `spawn_budget → 13001` |
| `v13_goal_lifecycle` | `LANGUAGE sql STABLE`，uuid 进、text 出 |
| `v13_reject_bad_harness_request` | 接受夹具 llm 请求：无 `logical_turn_id` 且非 harness 时直接 RETURN，不拒 |
| `effects.created_at` / `lease_until` | 测试 `UPDATE` 可写 |
| stopped 之后 `v13_enqueue_effect` | 成功。gate 只跑 `stopped_root_not_fair_claimed`。公平跳过该行；活体 `v13_claim` 仍可领走。不跑 `stopped_enqueue_raises`。后一条通过只闭合 stopped 这一对；§7.1 其余断言仍须通过才允许整个 fair_claim gate 标 exit_0 |
| `v13_tool_effect_open` | 源码仍含 `not_single_tree`。`prosecdef` 为假（INVOKER） |
| 打开者路径身份 | 打开者路径上触发器嵌套函数的运行时身份是调用时的有效身份 |
| path_guard SET ROLE | path_guard_execute_reaches_recheck 的 SET ROLE 证明只覆盖直接 enqueue 路径 |

`v13/spawn/v13_spawn.sql:24-25` 活体 `spawn_budget` 仍是 `{"max_nonterminal":8,"max_depth":4,"max_fanout":8}`。不是全局帽。

## 种子

| 种子 | 值 | 不是 |
|---|---|---|
| `claimed_cap` | 2 | 产品并发能力；不是 spawn_budget 的 8/4/8 |
| `fair_soak_roots` | 4 | 席位常数 |
| `fair_soak_ticks` | 8 | 多日 tick |
| `fair_claim_retries` | 2 | 只用于 40P01 |
| `fair_snapshot_cap` | 32 | 扫描硬顶 |
| lease 上界 | 600000 ms | 不是活体 `v13_claim` 的上界 |

fair_claim 在政策不存在时插入 claimed_cap=2。这个种子不是产品并发能力证明，也不是 spawn_budget 的 8/4/8。已有不相等行则装载 RAISE，不覆盖。

## 锁与帽

13002 与 13003 是本期咨询锁类号，不写进政策 JSON，不修改 `v13_advisory_class`。`v13_claim_fair` 取 13002；路径函数取 13003。领用不取 13003，不取 13001。

根会话 FOR UPDATE 之后、任何 effect 行锁之前，若 effect 所在会话不是该根，再锁这一把子会话；顺序先根后子，不得反过来，不得再锁第三把会话；不得在已持有 effect 行锁后再锁 sessions。

13002 在会话行锁之前取得；排头的会话锁等待会阻塞所有后续公平领用；活体 v13_claim 不取 13002。

帽不约束活体 `v13_claim`。活体 `v13_claim` 不看 `global_concurrency`。帽只约束 `v13_claim_fair`。

`infinity` 占席且本期不释放。打开者留下的 `claimed` 且 `lease_until = infinity` 计入 `claimed_count`。

有限租约过期后，席位只有在外部调用未改过的 v13_requeue_stale 时才释放；fair_driver 不是这个调用者。

`cap=1` 连续领用残留只指仍回到 ready 的路径，不是过期 claimed 转 unknown，也不是 attempt 耗尽转 failed。`judge` / `mgraph_consolidate` 经未改的 `v13_requeue_stale`（仅 attempt 仍有余量），或 `failed|cancelled` 经 `v13_enqueue_effect` 重挂。种子是 2，夹具不走这条。

64 只是上溯守卫，不是席位，不是 `max_depth`。

## 路径

`trg_effects_workspace_path_lock` 只挂 BEFORE INSERT。`failed|cancelled` 重挂是 `UPDATE effects SET status='ready'`，不触发该闸。这是已知洞，不是已闭合。

跨根 `path_busy` 由 `v13_path_conflict_locked` 在两个连接上复现。两个已提交根上调用打开者仍是 `not_single_tree`。

## Gate

`UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py`

2026-10-01 该命令退出码 0；库 `ll_fair_claim_16948_7cf862`（跑完已 DROP）；96 checks。

断言名按计划 §7.1。本目录 SQL 的退出码 0 允许声称的只有：单库多根下 `v13_claim_fair` 按 in-flight 排序且帽只约束该函数。不声称产品角色、真实 provider、多日运行、活体 `v13_claim` 也遵守帽。
