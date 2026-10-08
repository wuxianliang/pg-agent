# v13 agentctl

Stage 40 只登记一个 STABLE INVOKER 只读工具 `agentctl_observe`。不建 `controller` 政策，不登记写动词。

## 实跑

2026-10-08：

- `UV_FROZEN=1 uv run python v13/agentctl/test_agentctl.py` 退出码 0，577 checks，一次性库已 DROP。
- `UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py` 退出码 0，104 checks，一次性库已 DROP。

## 接口

`v13_agentctl_observe(p_sid uuid, p_spec jsonb) → jsonb`

`search_path` 恰为 `pg_catalog, public`。`REVOKE EXECUTE` FROM PUBLIC，只 `GRANT EXECUTE` 给 `v13_route`。不是 DEFINER。

`p_spec` 键只允许 `{ids}` 或 `{ids, hint}`，`ids` 必填。`ids` 是规范小写 uuid 文本，或这种文本的非空数组。`hint` 缺省、JSON `false`、字符串 `false` 不取 hint。JSON `true` 或字符串 `true` 才取。

形状失败不 RAISE，返回：

```json
{"schema_version":1,"ok":false,"reason":"shape","rows":[],"hints":[],"pointers":[]}
```

成功返回没有 `reason`。`rows` 用活体 `v13_observe` 列名，含 `parent_session_id`，顺序等于输入序。`hints` 元素是 `{session_id, hint}`，只覆盖实际返回的行，顺序同 `rows`。`hint` 文本只可能是 `run_now`、`wait`、`dont_notify`。`pointers` 是已有 `workflow/pointer` 的 `session_id, event_id, seq, payload`，按观察行序、`seq`、`event_id` 排序。缺 pointer 不占位。

未授权（含自己）整批空成功，不取 hint。包装不写事件，不调用 pointer 写者。

## 权限与零写

直接调用不写 `sessions`、`events`、`effects`、`artifacts`、`latches`，不推进 `next_seq`。经 sql 臂执行时，外层仍会写 `turn/route`、tool effect 和成功时的 `tool/result`。那不是 handler 自己的写。

产品政策 `controller` 未交付。路由证明用测试库里的 `agentctl_observe_probe` version 1，随库消失。

## Gate

```bash
UV_FROZEN=1 uv run python v13/agentctl/test_agentctl.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```

这只证明授权范围内的 PG 只读工具，以及 Fake 的 parse → advance → sql 臂。不证明 CE 进程 wait/poll、wake、目标工作流或无人值守。
