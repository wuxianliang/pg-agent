# v13 agentctl verbs

Stage 41 追加三个 VOLATILE SECURITY DEFINER 写动词，以及只活在本目录 SQL 里的 `v13_named_sql_writer` / `v13_spawn_writer_ok` 替换。不改 `v13/spawn/v13_spawn.sql`。不建表、不加列、不加事件类型。

**正文消费未闭合。退出码 0 不表示 payload.text 已被消费，也不授权「取代 R11」。** 2026-10-08 复核没有找到把 `steer/injected.payload.text` 送进目标后续消费路径的冻结树函数。`v13_session_log`、水位 stale、读回事件行、审计三联都不是消费者。`CONSUMER` 保持未设置。不得把本里程碑写成「D-3 已闭合」。

## 签名

```text
public.v13_agentctl_steer(p_sid uuid, p_spec jsonb)  → jsonb
public.v13_agentctl_answer(p_sid uuid, p_spec jsonb) → jsonb
public.v13_agentctl_cancel(p_sid uuid, p_spec jsonb) → jsonb
```

`LANGUAGE plpgsql VOLATILE SECURITY DEFINER`，`search_path` 恰为 `pg_catalog, public`。属主 `v13_spawn_owner`。`REVOKE EXECUTE` FROM PUBLIC，只 `GRANT EXECUTE` 给 `v13_route`。actor 传给 complete / cancel 的永远是 `p_sid`，不是 NULL。不调用一参 cancel，不调用五参 complete。

形状失败、政策失败、授权失败都是 RAISE，不是 `{ok:false}`。文案分别是 `v13: agentctl args`、`v13: agentctl policy`、`v13: session not found`。政策先于授权。

## 请求键与载荷

| 动词 | 请求键 | 长度 |
|---|---|---|
| steer | `target`, `text` | `text` 先 `btrim`，再按字符 1..1024 |
| answer | `effect_id`, `response`, `target` | `response` 同样 1..1024。无 `skip` |
| cancel | `target` | 无正文 |

UUID 只接受 `v13_canonical_uuid` 为真的小写 8-4-4-4-12。不 trim，不大写折叠。

steer 事件 `steer/injected` 的载荷键恰为 `schema_version`（数字 1）、`text`（btrim 后）、`source_principal`（字面量 `controller`）。返回键恰为 `schema_version`、`caller`、`target`、`event_id`、`seq`。事件行上看不到 caller。

answer 先锁目标 session，再锁 effect。领用后只调用六参 `v13_complete`，status 位置是字面量 `succeeded`。`interaction_ref` 用 `request->'interaction_ref'`，不是 `->>`。返回词不是 `accepted` 就 RAISE `v13: agentctl answer not accepted`。返回键恰为 `schema_version`、`caller`、`target`、`effect_id`、`outcome`。

cancel 只调用两参 `v13_cancel(p_sid, target)`。返回词只接受 `accepted` 或 `replay`。返回键恰为 `schema_version`、`caller`、`target`、`outcome`。

## 三份 jsonb

`mutating` 仍是 false。

| handler | write_targets |
|---|---|
| `v13_spawn_subsession` | `["artifacts","events","latches","sessions"]` |
| `v13_agentctl_steer` | `["events","sessions"]` |
| `v13_agentctl_answer` | `["effects","events","sessions"]` |
| `v13_agentctl_cancel` | `["effects","events","sessions"]` |

`v13_agentctl_observe` 的 named 仍是 NULL。writer_ok 对它为 false。

## 两个窗口

直接调用窗口只包住那一条 `SELECT` 包装。差集等于上表。临时表 `v13_fanout_cancel_tree` 不进差集。

sql 臂窗口里，handler RAISE 被吸收。advance 仍可 `progressed`。调用者 `next_seq` 只因 `turn/route` +1。一条 failed tool effect，没有 `tool/result`。那不是 handler 的 write_targets。

## 政策

`controller` version 1 frozen。`controller_surface` version 1 active。写函数读调用者 session 的 route policy，不读 surface 来授权。`spawn_subsession.enabled` 保持 true。

## Gate

```bash
UV_FROZEN=1 uv run python v13/agentctl_verbs/test_agentctl_verbs.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```

两条命令都退出 0 之后，本目录才可以进入生产者提交。退出码 0 只表示三个写动词、`controller` / 1、`controller_surface` 与 D-3 的身份、授权、零写、watermark 已交付。正文消费未闭合。不得据此声称 stage 42–45、CE 进程控制、wake、真实 provider、无人值守或「D-3 已闭合」已经交付。
