# v13 Phase C 计划证据（2026-09-29）

本文只记录本规划轮重读的行。不是 gate 通过证明。没有跑 `UV_FROZEN=1 uv run python v13/<dir>/test_<name>.py`。没有退出码可以声称通过。没有调用真实 provider。没有改 stage 1–29，没有改 `v13/load.py`。父组 `810F15E6-381F-486E-9A15-1F36F9A47614` 与 `10BD0645-DD7A-4AC5-9A40-C96923DADB32` 都不是接受。缺的 lane 不是零分。父组 `0F41F9D5-D659-43F5-8DA3-D28B8D78885C` 也不是接受。缺的 lane 不是零分。父组 `ED1FCF23-F95D-4FCC-9B2E-54B7F0412662` 与 `4A0BAA9D-159C-4638-BC26-F0AEDC13BF91`、`D6385E6F-190A-4388-BD37-645AADD4BF0D` 都不是接受。缺的 lane 不是零分。父组 `F358297A-C8D9-44BD-980B-98339592CCF2` 与 `B815EE9A-C80A-4204-96FF-25F34F03981A` 都不是接受。kimi 的配额失败不是内容零分。缺的 lane 不是零分。完成 lane 的 P0=0 P1=0 不是接受。其它 lane 没有内容分。这次措辞修补没有再跑 gate，也不是复审通过。

## 重读

| 事实 | 位置 |
|---|---|
| `replan/required` 要求 `source_effect_id` 非 NULL | `v13/control/v13_control.sql:425-428` |
| `replan/required` 载荷键恰好 `schema_version` | `v13/control/v13_control.sql:447-448` |
| signals 路径写入 `{"schema_version":1}` | `v13/acl/v13_acl.sql:435-436` |
| `source_effect_id` 无 FK | `v13/schema/v13_core.sql:37` |
| harness 工具只认 `harness_turn` | `v13/control/v13_control.sql:97-99` |
| harness 前驱 | `v13/control/v13_control.sql:180` |
| 收据候选与写入 | `v13/govern/v13_govern.sql:849-866` |
| signals ledger 比较前驱上的 replan 事件 | `v13/govern/v13_govern.sql:845-852` |
| 两键 human 请求 | `v13/govern/v13_govern.sql:911-912` |
| `WHEN 'tool'` 按 route 新建并 `v13_send_work` | `v13/govern/v13_govern.sql:1137-1168` |
| 指纹排除名单 | `v13/govern/v13_govern.sql:62-65`、`:79-82` |
| `v13_recover_idle()` 零参数，写 nudge，不入队 effect | `v13/govern/v13_govern.sql:453-519` |
| `v13_insert_nudge` 写 `recover/nudge` | `v13/spawn/v13_spawn.sql:193-196` |
| `v13_scheduler_hint` 起于，stopped 返回 `dont_notify`，最后可返回 `run_now` | `v13/govern/v13_govern.sql:534`、`:545-546`、`:576` |
| `v13_requeue_stale` 只收 `lease_until < clock_timestamp()` 的 `claimed`；其它 kind 标 `unknown` | `v13/control/v13_control.sql:1079`、`:1087`、`:1127-1130` |
| `v13_claim` 缺省租约 60000 毫秒 | `v13/schema/v13_core.sql:267-271` |
| `v13_observe` 未授权时 `RETURN` 零行 | `v13/observe/v13_observe.sql:43`、`:86-88` |
| `artifacts.produced_by`，无会话列 | `v13/manifest/v13_manifest.sql:52-59`、`:81-88` |
| `v13_quota_eligible` 只计本 session | `v13/quota_window/v13_quota_window.sql:53`、`:94-99` |
| `SQL_LOAD_ORDER` 末项仍是 govern | `v13/load.py:17-46` |
| L24 不建相位机，停滞不自动插 `replan/required` | `docs/plans/v13-layered-control-roadmap-2026-09-26.md:130` |
| operator 定义 | `v13/acl/v13_acl.sql:74-86` |
| `v13_pending_human` 只计 `ready` / `claimed` | `v13/control/v13_control.sql:121-128` |

`v13/*.sql` 搜索里，`v13_requeue_stale` 的定义只出现在 `twophase`、`mgraph`、`control`。`control` 在 `SQL_LOAD_ORDER` 里晚于前两者。govern 替换的是 `v13_recover_idle`，不是 `v13_requeue_stale`。实现仍须用加载后的 `pg_get_functiondef` 复核。本表不是那次复核。

## 未跑

- `UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py`
- `UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py`
- `UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py`

没有退出码。不得写成通过。

## 本轮命令

规划轮用只读检索与 `git status`。`git status` 显示 `main` 跟踪 `origin/main`，当时工作区无改动。没有跑 stage gate，没有调用 provider。
