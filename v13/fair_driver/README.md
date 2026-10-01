# v13 fair_driver

Phase D 第二段。交付 `claim_one` 与 4 根 8 tick soak。无 SQL，无加载键，不调用 provider，不构造 FakeLLM。超级用户夹具不是产品角色证明。Fake 退出码 0 不是产品可用。未证明产品角色。未证明 material 已扣。

`claim_one` 是本期 gate 的具名调用者，不是已证明的生产角色。本驱动器不是无人值守监督进程，也不授权离开生产终端。

加速夹具不是多日生产运行。真实多日运营仍未授权。
v13_quota_eligible 使用 transaction_timestamp()，不可注入。本 soak 不证明配额窗口。
fair_claim 在政策不存在时插入 claimed_cap=2。这个种子不是产品并发能力证明，也不是 spawn_budget 的 8/4/8。已有不相等行则装载 RAISE，不覆盖。
公平不写入事件。v13_goal_fingerprint 不改。
活体 v13_claim 不看 global_concurrency。帽只约束 v13_claim_fair。
not_single_tree 仍在打开者里。跨根 path_busy 不经过打开者。
PC-4 保持关闭。
C4 多 lane 不在本期实现。
有限租约过期后，席位只有在外部调用未改过的 v13_requeue_stale 时才释放；fair_driver 不是这个调用者。

## 种子

| 种子 | 值 | 不是 |
|---|---|---|
| `claimed_cap` | 2 | 产品并发能力；不是 spawn_budget 的 8/4/8 |
| `fair_soak_roots` | 4 | 席位常数 |
| `fair_soak_ticks` | 8 | 多日 tick |
| `fair_claim_retries` | 2 | 只用于 40P01 |
| `fair_snapshot_cap` | 32 | 扫描硬顶 |
| lease 上界 | 600000 ms | 不是活体 `v13_claim` 的上界 |

## Gate

`UV_FROZEN=1 uv run python v13/fair_driver/test_fair_driver.py`

2026-10-01 该命令退出码 0；库 `ll_fair_driver_38307_92f44c`（跑完已 DROP）；38 checks。

断言名按计划 §7.2。这条 gate 退出码 0 允许声称的只有：在这 4 根、这 8 tick、这颗种子下，公平函数没有在帽内把第二笔给已经 in-flight 的根，驱动器没有写事件，配额政策没有被拨动。不允许声称生产多日运行已执行。
