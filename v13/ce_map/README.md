# v13 ce_map

stage 44 在连续装载 1–43 之后提供 `public.v13_ce_map()`。它是 `LANGUAGE sql`、`STABLE`、`SECURITY INVOKER`、非 `STRICT` 的零参函数，返回 oracle 那一份静态 jsonb。`map` 把父计划 E2 的 CE 原语指到既有 PG 签名，或把 `shutdown` 写成字符串 `unsupported`。调用它不执行这些签名，不读 `external_executor`，不是 CE 会话运行时，不交付 stage 45。

## 函数

`public.v13_ce_map() → jsonb`

| 属性 | 合同 |
|---|---|
| 语言 | `sql`。体只有一条 `SELECT '<jsonb>'::jsonb` |
| 易变性 | `STABLE`。不是 `IMMUTABLE` |
| 安全 | 默认 `SECURITY INVOKER`。源文件不写 `SECURITY DEFINER` |
| `STRICT` | 不写。`proisstrict` 为 false |
| `search_path` | `SET search_path = pg_catalog, public` |
| 属主 | 安装者，等于 `current_user`。不 `ALTER OWNER` |
| EXECUTE | `REVOKE` FROM `PUBLIC`；只 `GRANT` TO `v13_route` |
| 写入 | 零。不读目录，不调用被映射签名 |

安装顺序：`BEGIN`，`CREATE FUNCTION`，`REVOKE`，`GRANT`，函数体外 `COMMENT`，`COMMIT`。不是 `CREATE OR REPLACE`，不是 `IF NOT EXISTS`，无 `INSERT`。

`COMMENT`：

```text
STABLE read; returns the closed static CE primitive map; does not execute or query; not a tools row; does not raise.
```

## 闭集

返回值是下面这一份静态 jsonb，不是目录查询。对象键序不参与比较，数组顺序参与比较。`shutdown` 是 `map.shutdown` 字符串 `unsupported`，不是函数。`v13_agentctl_answer` 不出现。一参 `v13_cancel` 存在但不映射。六参 `v13_complete` 才是 `respondToPermissionRequest`。`lease_owner text` 与 `lease_until timestamptz` 由测试另查，不是 task lease，也不是 stage 42 的建会话路径。

```json
{
  "schema_version": 1,
  "map": {
    "observe_poll": "v13_agentctl_observe(uuid,jsonb)",
    "startOrResume": "v13_enqueue_effect(uuid,text,jsonb,text)",
    "sendUserMessage": "v13_append_event(uuid,uuid,text,jsonb,uuid)",
    "steerUserTurn": "v13_agentctl_steer(uuid,jsonb)",
    "interruptTurn": "v13_cancel(uuid,uuid)",
    "respondToPermissionRequest": "v13_complete(uuid,uuid,integer,bigint,text,jsonb)",
    "shutdown": "unsupported"
  },
  "lease_columns": ["lease_owner", "lease_until"],
  "chains": [
    {"id": "agent_run_poll", "call": "executeWait", "forcePoll": true, "file": "repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift", "lines": "425-426"},
    {"id": "session_link_poll", "call": "executePoll", "file": "repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentSessionLinkMCPToolService.swift", "call_line": 124, "def_line": 366}
  ],
  "notes": {
    "observe_poll": "pg_readonly_state_observe; hint_is_not_wake",
    "startOrResume": "not_stage42_session_create_path; lease_columns_are_not_task_lease"
  },
  "not_claimed": ["worktree_bind", "worktree_merge", "auto_wake", "oracle_lanes", "claimedProcessID", "request_attention", "v13_ce_shutdown", "v13_requeue_stale", "v13_renew_lease"]
}
```

两条链不合并。`chains[0]` 只有 `id`、`call`、`forcePoll`、`file`、`lines`。`chains[1]` 只有 `id`、`call`、`file`、`call_line`、`def_line`，没有 `forcePoll`。键名保持 CE 对照词，不改写成 MCP op 名。

`not_claimed` 是非声称标签。`worktree_merge` 含 routed `confirm_preview` 拒绝，不另开 jsonb 键。worktree 绑定、auto-wake、oracle lanes、`claimedProcessID`、`request_attention` 同样未交付。`v13_requeue_stale` 与 `v13_renew_lease` 不是 shutdown。`v13_ce_shutdown` 不存在。

## 装载

`setup_db.py` 把一次性库装到 `external_exec`。本目录 SQL 不在 setup 里应用。库里因此有 stage 43 的分类函数和 active `external_executor` version 1。这是编号前置，不是功能消费。函数定义与返回值不引用 `external_executor` 或 `v13_external_exec_classify`。

不创建 `v13/workflow_project/`。不把 `not_scheduled` 放进允许集、`approved` 或 `SQL_LOAD_ORDER`。不交付 stage 45。不是 CE 会话运行时。

## Gate

```bash
UV_FROZEN=1 uv run python v13/ce_map/test_ce_map.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```
