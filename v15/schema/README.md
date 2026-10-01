# v15 stage 1 · schema

Gate: `uv run python v15/schema/test_schema.py`（退出码 0 = 通过）

库名 `agent_v15_schema`。这是前缀 gate 库，不是合运行时。合运行时只在 `SQL_LOAD_ORDER` 十二个文件都加载之后。

`setup_db.py` 先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库，再重建集群角色，然后 `CREATE DATABASE` 并 `load_stage(..., "schema")`。角色语句不在 `v15_schema.sql` 里。加载结束后 `v15_bootstrap` 改为 `NOLOGIN`。

## 内容

- schema `v15` 与 `jaz`，属主 `v15_owner`
- §3 的 21 张表，含终态 CHECK、`invoke_events` 只追加、`llm_messages` 不可改、清单单例
- `v15_on_phase` 桩，返回 `{"contract":1,"action":"proceed"}`
- `v15_assert_manifest()` 与 `v15_assert_invoke_manifest(uuid)` 真检查
- `v15_span_open`、`v15_next_runnable()`、`v15_current_scratch_schema()`
- 四个治理 handler 桩与 `hook_defs` 行
- `v15_scratch_guard`（`ddl_command_end`）与 `v15_scratch_sql_drop`（`sql_drop`）

## 角色

| 角色 | 登录 | 关系 |
|---|---|---|
| `v15_bootstrap` | 仅装载期间，结束后 `NOLOGIN` | 无运行时成员 |
| `v15_owner` | `NOLOGIN` | 不是 `v15_repl` 的成员 |
| `v15_worker` | 可登录 | `GRANT v15_repl`，`INHERIT FALSE, SET TRUE` |
| `v15_repl` | `NOLOGIN` | 不是 `v15_worker` 的成员 |
| `v15_hook_governance_{iterations,depth,io,statement}` | `NOLOGIN` | 无成员 |

## 清单种子

stage 1 装载插入恰好一行。数值是种子，不是论文默认值；合同只要求四项 `>= 1` 且 `manifest_digest` 与 §8.5 的 `jsonb::text` 重算一致。

| 列 | 种子 |
|---|---|
| `max_iterations` | 10 |
| `max_depth` | 8 |
| `max_io_attempts` | 3 |
| `max_statement_ms` | 30000 |

## 本 stage 不证明

转移函数、模型面包装、配置折叠、切分器、语句执行、IO 与子树。那些是 stage 2 起的 gate。
