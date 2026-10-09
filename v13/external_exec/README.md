# v13 external_exec

夹具绑定的现存 `p_sid`、`external_executor` version 1、STABLE INVOKER 函数 `v13_external_exec_classify`：允许动词返回七键且 `executed=false`；`source_principal`、未知键、列表外动词、空会话或不存在会话返回两键 `unsupported` 且零写。真正执行仍是既有 parse → advance 的 sql 臂，快照仍是 `controller` / 1。这不是可信产品入口，不是注册身份，不是 task lease。

## 函数

`public.v13_external_exec_classify(p_sid uuid, p_spec jsonb) → jsonb`

`LANGUAGE plpgsql`，`STABLE`，默认 `SECURITY INVOKER`，安装者属主，`SET search_path = pg_catalog, public`。不声明 `STRICT`。`REVOKE EXECUTE` FROM PUBLIC，只 `GRANT EXECUTE` 给 `v13_route`。函数不是 `tools` 行。不调用四个写动词。

允许列表只来自当次 `SELECT value, version FROM v13_policies WHERE name = 'external_executor' AND active` 读到的 `verbs`。

## 七步

命中即返回。失败对象只有 `ok` 与 `reason` 两键。成功对象恰好七键，`executed` 为布尔 `false`。`policy_version` 只出现在成功返回值。

1. `p_spec` 是 SQL NULL，或 `jsonb_typeof` 不是 `object` → shape
2. 对象含键 `source_principal` → unsupported
3. 存在除 `schema_version` 与 `verb` 以外的键 → unsupported
4. 键集不是恰好那两键，或 `schema_version` 不是整数 1，或 `verb` 不是字符串 → shape
5. `p_sid` 是 SQL NULL，或 `sessions` 无该行 → unsupported
6. 读政策。无 active 行 RAISE。value 非法 RAISE。`verb` 不在当次数组 → unsupported
7. 否则七键成功

形状：

```json
{"ok": false, "reason": "shape"}
```

unsupported：

```json
{"ok": false, "reason": "unsupported"}
```

成功（`agentctl_steer`；其余三个只改 `verb`）：

```json
{"schema_version": 1, "ok": true, "classified": true, "executed": false, "verb": "agentctl_steer", "policy_name": "external_executor", "policy_version": 1}
```

## 政策

安装一行 `external_executor` version 1，`active` true，value 字面量：

```text
{"schema_version":1,"verbs":["agentctl_observe","agentctl_steer","agentctl_answer","agentctl_cancel"]}
```

无 active 行：

```text
v13: no active policy row for external_executor (seed lost?)
```

坏 value：

```text
v13: external_executor policy
```

空 `verbs` 数组是 unsupported，不是这条 RAISE。

## 执行

真正执行仍是既有 parse → advance 的 sql 臂。本 stage 只对 `agentctl_steer` 做这条证明。parse 快照仍是 `controller` / 1。分类函数不在这条路径上。绿的 `progressed` 不是 handler 成功，也不是产品入口。

## 非目标

不交付注册身份、trusted bind、task lease。不回答 stage 44 映射或 stage 45。不改 `driver.py`、信封、`v13_advance`。不把 `external_executor` 写入 route 快照。

`setup_db.py` 把一次性库装到 `goal_workflow`。本目录 SQL 不在 setup 里应用。

## Gate

```bash
UV_FROZEN=1 uv run python v13/external_exec/test_external_exec.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```

## 实跑

2026-10-09 `UV_FROZEN=1 uv run python v13/external_exec/test_external_exec.py` 退出码 0（471 checks）。`UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py` 退出码 0（104 checks）。一次性库在打印 `[ok]` 之前已删除。退出码 0 只表示声称句已经在夹具上验证，不是可信产品入口，不是注册身份，不是 task lease。
