# pg-agent v6 · PostgreSQL-DuckDB 临时工作台

状态：**W1–W9 核心功能已实现并通过整串 gate**。

v6 的目标是在 v5 的“PostgreSQL 负责状态和队列、库外 worker 负责等待外部服务”基础上，加入一个由 DuckDB 驱动的临时数据分析工作台。功能目标参考 InfiniSQL / InfiniSynapse 的核心行为，但不复制其 NestJS、SSE、SQLite、task-folder 或 delegate 架构。

## 版本和平台边界

- Python 依赖只允许：`duckdb==1.6.0.dev366+ga1f0ab1911`（本地 fork wheel，`[tool.uv.sources]` 指向兄弟仓库文件）
- 只支持已验证的平台：macOS arm64、CPython 3.12
- DuckDB identity：`pragma_version()` 的 `library_version=v1.6.0-dev13823`、`source_id=a1f0ab1911`
- Wheel SHA-256：`fa4ba6fb193e98d9273d494d1255393a4df33b8d6890fbbcdd65b064b3c15ad9`
- 不使用 DuckDB 1.5.x，不等待或假设 DuckDB 2.0.0 GA，不做 Linux/Windows 矩阵
- DuckDB 运行在 v6 worker 进程中，不运行在 PostgreSQL backend 内
- PostgreSQL 是 agent 状态、队列、元数据和权限的事实源
- pgembed 暂不修改；PostgreSQL 侧不安装 `pg_duckdb`
- `run_schema` 仍是 PostgreSQL `duck_workbench_sessions.session_mode`，不是 DuckDB schema

## 核心功能范围

1. 从 PostgreSQL 白名单表读取有界只读快照到当前 run 的 DuckDB 内存会话。
2. 将一条经过验证的 DuckDB `SELECT` 保存为显式命名的临时 view。
3. 后续操作可以在同一 run 中引用此前的 source/view，形成链式分析。
4. 提供有界预览、列信息、列表、show-create 和受依赖保护的删除。
5. SQL 侧工具只校验参数、写操作元数据并发送 PGMQ；DuckDB 查询全部在库外 worker 执行。
6. 对 DuckDB 解析、绑定、执行、超时、内存和源数据错误返回统一的可行动错误。
7. 通过 request_id、op_seq、PGMQ visibility timeout 和 DLQ 处理重复、乱序和 worker 崩溃。

## 明确不在 v6 核心版

- DuckDB PostgreSQL extension 作为默认查询连接或 live catalog
- `ATTACH`、`CONNECT`、`postgres_scan`、`postgres_execute`
- 本地 CSV/Parquet/JSON 直读
- `DIRECT_QUERY`、`SAVE`、ET/ML、可视化、LLM UDF、shell
- Spark/Byzer 到 DuckDB 的完整翻译器
- 完整 POML 引擎
- 多 worker 下的自动内存会话亲和路由
- DuckDB 与 PostgreSQL 的分布式原子提交
- 子 agent 自动共享父 agent 的 DuckDB artifacts

## 阶段顺序

| 阶段 | 目录 | 目的 | 是否允许进入下一阶段 |
|---|---|---|---|
| W1 | `kernel_freeze/` | 只读加载 v5，证明基线不被复制或修改 | W1 gate 通过 |
| W2 | `duckdb_probe/` | 锁定 wheel、平台、连接硬化、事务和取消事实 | W2 gate 通过 |
| W3 | `source_ingress/` | PostgreSQL 快照和类型矩阵 | W3 gate 通过 |
| W4 | `session_durability/` | temp 会话、可选定义重放和跨 run 隔离 | W4 gate 通过 |
| W5 | `queue_bridge/` | `duck_heavy_requests`、handler、幂等、DLQ | W5 gate 通过 |
| W6 | `duck_tools/` | 7 个 enqueue-only `wb_duck_*` 工具 | W6 gate 通过 |
| W7 | `dialect_guardrails/` | 只读 validator 和 DuckDB 方言提示 | W7 gate 通过 |
| W8 | `budget_observability/` | 超时、内存、结果大小和脱敏 | W8 gate 通过 |
| W9 | `integration/` | 全链路核心功能验收 | W9 gate 通过后才称 v6 核心版完成 |

每个阶段使用独立数据库 `agent_v6_<stage>`。任一 gate 失败即停止，不用 fallback 版本、不跳过失败阶段、不把“代码已写”当作“功能已验证”。

## 重要实现边界

- v6 loader 只能按路径读取 v3/v4/v5 的 17 个 inherited SQL 文件，不能 import v5，也不能复制这些文件。
- v5 的 `invoke_named_llm_tool()`、嵌套 defer envelope、`apply_queue_result()` 保持不变。
- v6 必须用自己的 overlay 扩展 `refresh_plugins()` 的合法 queue kind，加入 `duck_heavy`；不能修改 v4/v5 文件。
- DuckDB 查询连接打开后立即关闭自动安装、自动加载和 external access，并且永不加载 `postgres` 扩展。
- `temp` 模式中 worker 进程丢失意味着 `DUCK_SESSION_LOST`，不能静默创建一个空会话。
- `run_schema` 只表示从 PostgreSQL 元数据重读源并重放 view 定义，不表示恢复历史数据快照。
- grammar extension 默认关闭。启用时每个新连接都要重新 `LOAD` 本地 unsigned demo 扩展，然后立刻 `SET enable_external_access=false`；不 `INSTALL`，不把 grammar 状态写入数据库。
- `LOAD` 发生在 `DuckSessionManager` 的 `_manager_lock` 内，现有 query `interrupt()` 覆盖不到它。

详细计划和逐阶段审查见：

- `docs/analysis/v6-infinisql-core-development-2026-08-28.md`
- `docs/analysis/v6-duckdb-workbench-2026-08-28.md`（前期调查原始记录）

## 当前验证结果

2026-08-28 在本地环境完成 W1→W9 顺序复跑，全部通过：

```text
W1 kernel_freeze          passed
W2 duckdb_probe            passed
W3 source_ingress          passed
W4 session_durability      passed
W5 queue_bridge             passed
W6 duck_tools               passed
W7 dialect_guardrails       passed
W8 budget_observability     passed
W9 integration              passed
```

运行环境固定为 `duckdb==1.6.0.dev366+ga1f0ab1911` / `library_version=v1.6.0-dev13823` / `source_id=a1f0ab1911` / macOS arm64 / CPython 3.12。

## Grammar extension（opt-in，默认关闭）

这是本地 demo unsigned native 扩展，**不是**已签名生产插件。SHA-256 只保证与 pinned bytes 一致。启用即在 worker 进程加载 native code。

Extension 路径默认：

`/Users/wxl/Projects/duckdb-pgagent/build/reldebug/test/extension/loadable_grammar_extension_demo.duckdb_extension`

Extension SHA-256：`fce89a46632a3ff3b98f75bc7f9bafb7c663e5b31d3cc0453d012ce4c8986393`

配置在 `DuckSessionManager` 构造时冻结（读 env 一次）。之后改 env 无效，直到重启 worker。

| 变量 | 含义 |
|---|---|
| `PG_AGENT_DUCKDB_GRAMMAR_ENABLED` | 缺省关闭。`1/true/yes/on` 启用；`0/false/no/off` 关闭。其它非空值是配置错误。 |
| `PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_PATH` | 仅启用时使用。缺省为上面的 demo 路径。 |
| `PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_SHA256` | 仅启用时使用。必须 64 hex。缺省为上面的 digest。 |
| `PG_AGENT_DUCKDB_GRAMMAR_FEATURES` | 仅启用时使用。必须恰好 `pipe_query_syntax`。 |
| `PG_AGENT_DUCKDB_GRAMMAR_ENABLE_EXTERNAL_ACCESS` | 与 ENABLED 同一套布尔 token。true **始终拒绝**（含 grammar 关闭时）。 |
| `PG_AGENT_DUCKDB_GRAMMAR_NATIVE_TEST` | 仅测试。`1` 时运行真实 extension 集成；缺省 skip。marker 打开而文件缺失则失败。 |

启动时（启用）会 hash 一次；每个新连接 `LOAD` 前再 hash 一次。`allow_unsigned_extensions` 不是用户配置，只在启用分支传给 `duckdb.connect`。

Prompt：静态 `agent_system` v3 不含 pipe 广告。worker 只在该 run 已有 live DuckSession 且 capability 确认 `pipe_query_syntax` 时追加一条 system 消息。第一次 LLM 可能还看不到 `|>`。

关闭 grammar：停 worker，unset/`=0` `PG_AGENT_DUCKDB_GRAMMAR_ENABLED`，清 path/hash/features/native-test，重启。不会碰扩展文件，不会 `LOAD`。

回滚旧 wheel：只关 grammar **不够**（disabled 也校验 fork identity）。恢复 `pyproject.toml`/`uv.lock` 中的 `duckdb==1.6.0.dev365`，`uv sync --locked`，并恢复 identity 常量。

Streamlit demo（`v6/workbench_demo`）不注入配置，走进程 env；默认关闭。

当前版本仍是核心功能实验版：`temp` 会话丢失会终止 run；`run_schema` 是重读源数据后的逻辑重放；不支持 PIVOT、文件直读、live PostgreSQL catalog、多 worker 自动亲和和跨引擎原子提交。

## 常驻 worker 配置

实际 worker 入口已经接入 `DuckDBWorkerProcessor`，并轮询 `duck_heavy_requests`。source alias 由受控 JSON 配置提供，不进入 PGMQ 或模型参数：

```bash
PG_AGENT_DB=agent_v6_integration \
PG_AGENT_DUCK_SOURCES='{
  "agent_db": {
    "uri": "postgresql://...",
    "allowed_tables": [["public", "sales"]],
    "max_rows": 100000,
    "max_bytes": 67108864
  }
}' \
uv run python v6/kernel_freeze/worker.py
```

没有配置 source alias 时，worker 仍能处理纯 DuckDB metadata/query 队列，但 `wb_duck_register` 会结构化返回 `DUCK_SOURCE_NOT_FOUND`。

## 审查后可靠性修复

2026-08-28 完成一次针对 v6 的 Oracle 代码审查，并修复：

- 实际常驻 worker 注入 DuckDB processor 和 source resolver；
- temp session 关闭、owner 丢失后 fail closed，不静默打开空会话；
- operation 数据库级 claim、过期 lease 和 apply 侧 op_seq 顺序门；
- 同进程 DuckDB commit 后、PG apply 前的完成结果缓存；
- worker/apply 两侧 drop 依赖复核；
- artifact 同名重建完整更新 metadata 和 generation；
- run_schema hydrate 复用完整 validator 并校验 definition hash；
- list/columns 使用稳定 JSON object 协议；
- brief query 使用 timeout/interrupt；source PostgreSQL 读取设置 statement/lock timeout；
- 真实 AgentWorker 消费、真实 DLQ、malformed poison message 和乱序 apply 测试。

当前安全模型是**单一可信数据库角色**。`pg_agent.current_run_id` 是运行时上下文，不是多租户认证机制；如未来开放给不可信 SQL 用户，必须另做角色/owner/RLS 授权层。
