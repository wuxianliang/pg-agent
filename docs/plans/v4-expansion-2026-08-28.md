# pg-agent v4 staged expansion plan

## Goal

在不修改 `pg-agent/v1/`、`pg-agent/v2/`、`pg-agent/v3/` 的前提下，规划一组从 v3 PGMQ/sticky-worker runtime 逐阶段演进的 v4 实验。交付物是规划，不是实现；本任务不创建 `pg-agent/v4/`，也不创建任何 stage 文件。

v4 的目标架构是 Postgres-centric agent，并采用 “everything is a plugin” 原则：

- 一个 plugin 是一个 SQL file，可选地配套一个 out-of-DB worker processor；
- plugin 通过 PostgreSQL function `COMMENT` 中的 metadata 注册；
- plugin 不是 JS Cordis runtime，也不是把运行时塞进 Postgres 的 Cordis；
- SQL 负责状态、队列、catalog、工具执行和结果应用；
- Python worker 负责外部模型/embedding/重 SQL processor；
- LLM HTTP 永远不回到 SQL；
- 六个 expansion 严格顺序执行，每个 stage 在自己的数据库中通过 gate 后，才允许开始下一个 stage。

拟定计划文件：

```text
pg-agent/docs/plans/v4-expansion-2026-08-28.md
```

## Background

### 1. 版本边界和不可变基线

两个仓库的职责不同：

- `pgembed/` 提供 embedded PostgreSQL server 和已打包的 extensions；
- `pg-agent/v1/`、`pg-agent/v2/` 是历史实现，只能阅读；
- `pg-agent/v3/` 是 v4 的 runtime baseline，只能复制/覆盖到 v4 自己的目录和数据库，不能直接编辑；
- `pg-agent/server.py`、`pg-agent/pyproject.toml` 也不在本计划的常规修改范围内。

所有 v4 stage 都从 v3 的源码语义复制出自己的 overlay。实现时可以把 `v3/pg_agent_pgmq.sql` 和 `v3/worker.py` 作为只读输入，复制到当前 stage 的工作文件或由 stage loader 读取；任何需要改写的 SQL function、worker class 或 processor 都必须落在 `v4/<slug>/` 或该 stage 的 cumulative overlay 中。禁止通过 import、symlink、in-place replacement 或 monkey patch 修改 v3 文件本身。

每个 stage 使用独立数据库：

| 顺序 | Slug | Database | 目的 |
|---|---|---|---|
| 1 | `plugin_taxonomy` | `agent_v4_plugin_taxonomy` | 统一 COMMENT taxonomy、registry 和 generic queue apply |
| 2 | `sticky_workbench` | `agent_v4_sticky_workbench` | 把 v2 workbench 工具移到 v3 sticky connection |
| 3 | `queue_kinds` | `agent_v4_queue_kinds` | 增加 embed、sql-heavy、human-inbox queue kinds |
| 4 | `subagent_fanout` | `agent_v4_subagent_fanout` | 用 PGMQ groups 做 parent/child fan-out |
| 5 | `session_durability` | `agent_v4_session_durability` | 实验 TEMP 与 per-run schema 两种 session lifetime |
| 6 | `observability_budget` | `agent_v4_observability` | 增加 bounded step metadata、usage 和 budget enforcement |

setup 脚本只能 drop/recreate 自己的 database。不得复用或清理 `agent_v3`、任何 v1/v2 database，或其他 stage 的 database。

### 2. v3 runtime seam

v3 的关键 symbol 和责任如下：

- `v3/pg_agent_pgmq.sql`
  - `agent_runs`、`agent_steps`、`run_state()`；
  - `prepare_llm_request()`、`agent_start()`；
  - `apply_llm_response()`、`emit_step()`；
  - `session_set()`、`session_get()`；
  - `exec_sql_readonly()`；
  - `llm_requests`、`llm_requests_dlq` 和 PGMQ enqueue/apply helpers；
  - 仍保留 SQL-side `http_call_llm()` 和 synchronous `agent_run()` comparison baseline。
- `v3/worker.py`
  - `AgentWorker`；
  - `_run_conns` 和每个 `run_id` 一个 sticky connection；
  - `call_llm()`；
  - LLM call 在 SQL transaction 外执行；
  - apply 和 PGMQ archive 在同一 transaction；
  - visibility timeout replay、read-count DLQ。
- `v3/test_v3.py`
  - `scripted()` 注入 deterministic `llm_fn`；
  - happy path、sticky session、crash-after-read、provider retry、DLQ；
  - 这是 v4 所有 LLM gate 的 mock precedent。

v4 仍保持以下基本流：

```text
agent_start(question)
  -> prepare_llm_request(run_id)
  -> pgmq.send(...)
  -> return run_id

AgentWorker.read_one()
  -> read queue message
  -> Python processor / LiteLLM outside SQL transaction
  -> sticky conn_for(run_id)
  -> apply result in SQL transaction
  -> archive only after apply commits
  -> retain or close run connection
```

v4 不得恢复或调用 v3 的 `http_call_llm()`、`agent_run()` synchronous HTTP loop。Stage A 必须加载一个 v4 runtime guard，在继承 v3 SQL 后把这两个入口替换为明确抛错的 disabled guard，例如：

```text
v4 forbids SQL-side model HTTP; use the out-of-DB worker
```

这不是“测试时不调用”而已，而是运行时禁止调用。v4 worker 的 model、provider、API URI、API key、retry policy 和 timeout 都属于 Python 配置；SQL request payload 只包含 messages、run metadata 和必要的非 secret 参数。

### 3. v2 plugin/workbench precedent

v2 只作为设计参考，不作为可修改代码：

- `v2/pg_agent_workbench_core.sql`
  - `workbench_tools`；
  - `refresh_workbench_tools()`；
  - `render_workbench_tools()`；
  - `_wb_normalize_temp_view_name()`、`_wb_temp_view_oid()`、`_wb_temp_view_columns()`。
- `v2/plugin_brief_query.sql`
  - read-only bounded preview。
- `v2/plugin_temp_views.sql`
  - TEMP VIEW list/columns/create/drop 和 conservative SELECT/WITH validator。
- `v2/plugin_sql_curator.sql`
  - create + comment 的 subtransaction atomicity。
- `v2/pg_agent_data_analysis.sql`
  - `make_da_prompt()` 与 `da_system_prompt()` 的 immutable/stable 分层。
- `v2/pg_agent_rlm.sql`
  - `rlm_spawn()`、`rlm_map()`、`codeact_spawn()` 是 v4 D 要替换的 nested synchronous recursion。
- `v2/setup_db.py`、`v2/test_data_analysis.py`
  - loader 和测试编排参考。

v4 不复用 v2 的 `workbench_plugin`、`job_handler` 两套 registry，也不把 workbench 调用送进 v2 的 `jobs`/`worker()`。一个 v4 plugin 的定义是“SQL file + optional worker processor”，而不是 JS runtime。

### 4. pgembed 现状和 extension 约束

前六个 stage 的预期 bundle 已足够：

```text
pgmq
pgvector
vectorchord
psql_bm25s
AGE
pg_cron
timescaledb
tigerfs
core PostgreSQL LISTEN/NOTIFY
```

这些 stage 不得因为设计偏好而新增 extension。pgvector 只在 C 的 embedding gate 中作 availability check；PGMQ、普通 PostgreSQL SQL、TEMP/per-run schema、LISTEN/NOTIFY 已覆盖本计划的需求。不要把 `pg_tle` 当作运行依赖；它只能作为未来 packaging option。

如果实现中发现某 stage 真的需要一个当前 bundle 没有的 extension，必须停止该 stage，先完成本文“Hypothetical pgembed change checklist”，再 `make`，再在 `pg-agent` 中 `uv sync`，最后从干净 database 重跑该 stage。不得临时改用禁止的依赖或在 SQL 中绕过缺失能力。

## References

以下引用使用 symbol、文件名和语义 anchor，不使用容易漂移的 line number：

1. `pg-agent/v3/pg_agent_pgmq.sql`
   - `agent_start()`、`prepare_llm_request()`、`apply_llm_response()`、`run_state()`、`emit_step()`、`exec_sql_readonly()`、`session_set()`、`session_get()`。
2. `pg-agent/v3/worker.py`
   - `AgentWorker`、`conn_for()`、`call_llm()`、read/apply/archive loop、visibility timeout 和 DLQ。
3. `pg-agent/v3/test_v3.py`
   - `scripted()`、`test_sticky()`、`test_vt_crash()`、`test_litellm_retries()`、`test_dlq()`。
4. `pg-agent/v3/setup_db.py`
   - `run_psql()`、`get_server()`、`POSTGRES_BIN_PATH`、`agent_v3` 的 drop/create/load/check pattern。
5. `pg-agent/v2/pg_agent_workbench_core.sql`
   - workbench registry、comment validation、TEMP VIEW resolver。
6. `pg-agent/v2/plugin_brief_query.sql`、`pg-agent/v2/plugin_temp_views.sql`、`pg-agent/v2/plugin_sql_curator.sql`
   - plugin 文件边界、structured error、SQL validator、subtransaction。
7. `pg-agent/v2/pg_agent_data_analysis.sql`、`pg-agent/v2/pg_agent_rlm.sql`
   - prompt wrapper 和旧 nested delegation 的 symbol precedent。
8. `pg-agent/v2/setup_db.py`、`pg-agent/v2/test_data_analysis.py`
   - v2 loader/test conventions。
9. `pg-agent/docs/investigations/cordis-workbench-plugins-2026-08-22.md`
   - COMMENT taxonomy 背景、`job_handler` 与 workbench separation、TEMP backend boundary。
10. `pg-agent/docs/plans/v2-workbench-plugins-2026-08-22.md`
    - Goal/Background/References、W-numbered work items、test design、runbook 的文档形状。
11. `pg-agent/docs/reviews/v2-workbench-plugins-plan-review-2026-08-22.md`
    - 本计划必须避免的 defects：load-order contradiction、未说明 `TRUNCATE`/`DELETE`、未定义 mock、无法验证的 atomicity、brittle line-number citation。
12. `pgembed/pgbuild/Makefile`
    - extension list、platform/preload gates、build/install/bundle stamp。
13. `pgembed/tools/generate_bundle_metadata.py`
    - 每个 extension 的 version/source/ref/hash/stem/create/preload metadata。
14. `pgembed/README.md`、`pgembed/.github/workflows/build-and-test.yml`、`pgembed/tests/test_standalone_extensions.py`
    - bundle inventory、CI matrix、standalone extension test surface。

## Non-negotiable rules

### 1. 严格顺序

阶段顺序固定为：

```text
plugin_taxonomy
  -> sticky_workbench
  -> queue_kinds
  -> subagent_fanout
  -> session_durability
  -> observability_budget
```

每个 stage 必须在自己的 setup/test gate 全部通过后，才能开始下一个。失败即停止；不得“先实现后补 gate”，不得跨 stage 共享半成品数据库。

### 2. 固定 cumulative SQL load order

实现时每个 stage 的 setup 都使用同一条无歧义的 cumulative load order，只加载到当前 stage：

```text
(1) v3/pg_agent_pgmq.sql
(2) v4/plugin_taxonomy/v4_runtime_guard.sql
(3) v4/plugin_taxonomy/plugin_taxonomy.sql
(4) v4/sticky_workbench/workbench_core.sql
(5) v4/sticky_workbench/plugin_brief_query.sql
(6) v4/sticky_workbench/plugin_temp_views.sql
(7) v4/sticky_workbench/plugin_sql_curator.sql
(8) v4/queue_kinds/queue_kinds.sql
(9) v4/queue_kinds/plugin_async_tasks.sql
(10) v4/subagent_fanout/subagent_fanout.sql
(11) v4/session_durability/session_durability.sql
(12) v4/observability_budget/observability_budget.sql
```

- A 只加载 (1)–(3)；
- B 只加载 (1)–(7)；
- C 只加载 (1)–(9)；
- D 只加载 (1)–(10)；
- E 只加载 (1)–(11)；
- F 加载 (1)–(12)。

`v4_runtime_guard.sql` 固定紧跟 v3 base，确保后续 setup/test 无法误走 inherited SQL HTTP。任何定义了 COMMENT-registered function 的 SQL file 加载后，setup 必须显式调用 `refresh_plugins()`；失败时不得继续加载后续 plugin。不要在一个地方写“guard 最后加载”而在另一个地方写“guard 先加载”。

### 3. Registry rebuild semantics

`refresh_plugins()` 必须是“validate all, then replace”：

1. 在一个 transaction 中扫描 `pg_proc` 的 function comments；
2. 先在内存/临时 candidate set 中完成所有 metadata、signature、duplicate 和 capability validation；
3. candidate 全部合法后，执行明确的：
   ```sql
   TRUNCATE TABLE plugin_bindings, plugin_packages;
   INSERT ...
   ```
4. `TRUNCATE` 和两张表的 INSERT 在同一个 transaction；
5. 任意 INSERT、FK、comment 或 catalog resolution 错误都会 rollback，因此保留旧 registry；
6. 失败路径不使用“先 DELETE 一部分再返回”，也不允许出现半刷新 registry；
7. 测试 registry refresh 时必须验证失败前后的 row contents 相同，而不是只验证函数抛错。

测试 fixture 的清理语义必须逐处写明：临时 registry probe 用 `DROP FUNCTION ...`；队列消息用 `SELECT pgmq.purge_queue(queue_name)`；stage reset 用自己的 `DROP DATABASE ... WITH (FORCE)` 后重建；普通 test tables 使用明确的 `TRUNCATE ... RESTART IDENTITY` 或明确的 `DELETE`，不可含糊写“清空”。

### 4. Deterministic model/processor mocks

所有 stage 的自动化 test 都采用 v3/test_v3.py 的注入方式：

- `scripted(script)` 返回一个闭包；
- 每次调用根据计数器返回 script 中的 deterministic JSON response；
- worker 构造器接受 `llm_fn`，不能让测试隐式调用 live provider；
- C 的 embedding 使用注入的 `embed_fn`；
- C 的 sql-heavy 使用注入的 deterministic processor 或固定本地数据库函数；
- F 允许 script item 返回 raw JSON string 或 `{"raw": ..., "metrics": ...}` structured result，并由 worker normalization 统一；
- retry/crash tests 使用显式 fake processor、barrier 或计数器；
- 不使用真实 API key、真实 provider、外部网络或 live model 来证明 gate；
- v3 的 local HTTP stub 只作为历史 precedent，不作为 v4 正常路径；v4 应以 `llm_fn` injection 验证 SQL HTTP 被禁用。

### 5. Model HTTP 和 forbidden dependencies

禁止：

- `pgai`；
- Redis；
- LiteLLM Proxy；
- `postgres-task-queue`；
- Cordis-in-Postgres；
- 把 LLM HTTP 放回 SQL；
- 任何以 SQL function、`pg_net`、`pgsql-http` 或相似方式直接从 PostgreSQL 调 model endpoint。

允许使用 Python 中的 LiteLLM library 作为 out-of-DB call adapter；“LiteLLM”不等于“LiteLLM Proxy”，后者仍然禁止。SQL 不根据 budget、queue kind 或 catalog 来选择 provider/model；SQL 只记录 worker 实际返回的 bounded metadata。

## Proposed v4 folder layout（仅规划，不在 item 1 创建）

```text
pg-agent/
└── v4/
    ├── README.md
    ├── plugin_taxonomy/
    │   ├── README.md
    │   ├── __init__.py
    │   ├── setup_db.py
    │   ├── plugin_taxonomy.sql
    │   ├── v4_runtime_guard.sql
    │   ├── worker.py
    │   └── test_plugin_taxonomy.py
    ├── sticky_workbench/
    │   ├── README.md
    │   ├── __init__.py
    │   ├── setup_db.py
    │   ├── workbench_core.sql
    │   ├── plugin_brief_query.sql
    │   ├── plugin_temp_views.sql
    │   ├── plugin_sql_curator.sql
    │   └── test_sticky_workbench.py
    ├── queue_kinds/
    │   ├── README.md
    │   ├── __init__.py
    │   ├── setup_db.py
    │   ├── queue_kinds.sql
    │   ├── plugin_async_tasks.sql
    │   ├── worker.py
    │   └── test_queue_kinds.py
    ├── subagent_fanout/
    │   ├── README.md
    │   ├── __init__.py
    │   ├── setup_db.py
    │   ├── subagent_fanout.sql
    │   └── test_subagent_fanout.py
    ├── session_durability/
    │   ├── README.md
    │   ├── __init__.py
    │   ├── setup_db.py
    │   ├── session_durability.sql
    │   └── test_session_durability.py
    └── observability_budget/
        ├── README.md
        ├── __init__.py
        ├── setup_db.py
        ├── observability_budget.sql
        ├── worker.py
        └── test_observability_budget.py
```

每个 stage 的 `README.md` 必须至少包含以下固定标题，并记录实现后的实际结果：

```markdown
## Purpose
## Pass gate
## Fail gate
## pgembed change
```

前六个 stage 的 `pgembed change` 预期都写 `No`。如果实现期间发现 extension 缺失，必须把该 stage 标记为 stopped，而不是写成 workaround success。

## Work items（execution index）

| ID | Expansion | 依赖 | Size | 进入下一项的必要 gate |
|---|---|---|---|---|
| W1 | `plugin_taxonomy` | v3 baseline、`pgmq` | L | taxonomy、generic apply、HTTP guard、LLM replay 全通过 |
| W2 | `sticky_workbench` | W1 | L | 六个 workbench tools 在 sticky connection 上完成完整 scripted run |
| W3 | `queue_kinds` | W2、确认 `vector` 可用 | XL | embed/sql-heavy/human wait/resume 全部通过 |
| W4 | `subagent_fanout` | W3 | L | concurrent child、parent wait、exactly-once wake-up 全部通过 |
| W5 | `session_durability` | W4 | L | TEMP loss 与 run-schema persistence 两条 gate 都通过 |
| W6 | `observability_budget` | W5 | L | bounded metrics、budget fail-closed、no secret/no SQL routing 全通过 |

“Size” 是实现工作量估计，不是本 item 的实现授权。W1–W6 必须逐项完成，不能并行开始下一项。

---

## W1 — `plugin_taxonomy`

### Purpose

建立 v4 的单一 COMMENT taxonomy、plugin registry、queue binding 和 queue-message idempotency；把 v3 的 single hardcoded queue apply 改为 catalog-driven generic dispatcher，同时只实现 `llm` processor。

plugin metadata 使用三个 top-level keys：

```json
{
  "plugin": {...},
  "llm_tool": {...},
  "queue_handler": {...}
}
```

- `plugin` 标识 SQL plugin owner；
- `llm_tool` 是可选的 model-visible SELECT-callable tool capability；
- `queue_handler` 是可选的 SQL result apply capability；
- 普通 workbench function 只带 `plugin` + `llm_tool`；
- queue apply function 带 `plugin` + `queue_handler`；
- 如果同一 function 真的需要双重 capability，可以同时带两个 optional keys，但 refresh 必须验证组合合法；
- plugin 的实现单位仍是 SQL file，可选 worker processor，不是 JS runtime。

### Proposed files and symbols

`v4/plugin_taxonomy/plugin_taxonomy.sql` 负责：

- `plugin_packages`
  - `plugin_name text primary key`
  - `metadata jsonb not null`
  - `refreshed_at timestamptz not null default now()`
- `plugin_bindings`
  - `binding_name`
  - `binding_type`（`llm_tool` 或 `queue_handler`）
  - `plugin_name`
  - `fn regprocedure`
  - `queue_name`
  - `queue_kind`
  - `consumer`
  - `metadata`
  - `refreshed_at`
- `processed_queue_messages`
  - `queue_name`
  - `msg_id bigint`
  - `run_id`
  - `result_hash`
  - `applied_at`
  - primary key `(queue_name, msg_id)`

提供以下 symbols：

```text
refresh_plugins() returns integer
render_plugin_tools() returns text
list_queue_bindings() returns table
apply_queue_result(queue_name, msg_id, run_id, result jsonb) returns jsonb
apply_llm_result(run_id, result jsonb) returns jsonb
agent_current_run_id() returns text
```

metadata validation 至少包括：top-level `plugin` 存在、plugin name pattern、function 为 public ordinary function、`llm_tool.name = proname`、named args/type map exact match、return type 为 `jsonb`、capability/session scope 合法、queue name/kind/consumer 合法、tool/queue duplicate、`job_handler` 混入时拒绝。

第一版 queue kind taxonomy 预留且验证四种值：

```text
llm
embed
sql_heavy
human_inbox
```

A 只生产 `llm` binding；后三种通过 test-only comment probe 验证 parser 能接受和拒绝非法值，但不在 A 提供真实 processor。

`refresh_plugins()` 的 atomicity 必须按本文固定语义执行：validate all，transaction 内 `TRUNCATE TABLE plugin_bindings, plugin_packages`，再 insert candidate；失败 rollback 并保留旧 registry。不得用模糊的“rebuild catalog”描述代替具体语义。

`apply_queue_result()` 是唯一 generic SQL apply entrypoint：

1. 按 `queue_name` 找 `queue_handler` binding；
2. unknown queue 或 missing handler 时不 archive；
3. 先写入 `processed_queue_messages`；
4. duplicate `(queue_name,msg_id)` 返回 `replayed=true`，不重复调用 handler；
5. 设置 transaction-local current run context；
6. 动态调用 registered `(text,jsonb) -> jsonb` handler；
7. 恢复旧 context；
8. 由 worker 在同一 transaction 中 archive。

其 body 不得出现 `IF kind = 'llm'`、`IF kind = 'embed'` 等 queue-kind-specific branch；queue-specific behavior 必须由注册 handler 提供。

`v4/plugin_taxonomy/v4_runtime_guard.sql` 在 v3 base 后立即加载，覆盖 `http_call_llm()` 和 `agent_run()` 为 disabled guards。v4 worker 改为调用 `apply_queue_result()`，保留 v3 的 sticky connection、visibility timeout、crash replay 和 DLQ 语义。

### Stage database and overlay

- Database：`agent_v4_plugin_taxonomy`。
- Overlay source：只读复制 `v3/pg_agent_pgmq.sql`、`v3/worker.py` 的必要逻辑到 W1 自己的 loader/worker；不编辑 v3。
- Load order：v3 base -> runtime guard -> `plugin_taxonomy.sql`。
- Setup 在 taxonomy file 后调用 `refresh_plugins()`，并检查 production `llm_requests` binding count。
- W1 不依赖新 pgembed extension；`pgmq` 和 core PostgreSQL 足够。

### Pass gate

W1 只有同时满足以下条件才算 pass：

1. 新建 `agent_v4_plugin_taxonomy` 成功，且 setup 不调用 SQL-side model HTTP。
2. v4 runtime guard 直接调用时抛出明确 v4 error；静态检查 worker 不包含对 `http_call_llm`、`pg_net`、`pgsql-http` 的 model-call path。
3. 合法 metadata 能 refresh；malformed JSON、missing `plugin`、wrong return type、wrong arg map、duplicate tool、duplicate queue、invalid kind 都被拒绝。
4. 失败 refresh 后 registry rows 与失败前完全一致。
5. `apply_queue_result()` 中不存在按 queue kind 分支；四种 kind 仅通过 metadata validation/probe 出现。
6. 注入的 deterministic `scripted()` LLM script 经过 generic dispatcher 完成两轮 run，最终 `SUCCESS`。
7. crash-after-read 后 visibility replay 不重复逻辑 `llm` step；duplicate `(queue,msg_id)` apply 返回 replay 且不新增 `agent_steps`。
8. provider transient failure 在 worker-local retry 后仍遵守 apply/archive transaction 和 read-count DLQ。
9. A 的 README 记录 Purpose、Pass gate、Fail gate 和 `pgembed change: No`。

### Fail gate

以下任一情况都失败并停止 W2：

- worker 能绕过 generic dispatcher 直接调用 v3 `apply_llm_response()`；
- SQL HTTP guard 可被正常调用；
- refresh 在失败后留下空 registry或半刷新 registry；
- replay 产生重复 step；
- test 依赖 live model/network；
- 未明确 queue message cleanup 或 archive semantics；
- 修改了 `v3/` 或 v1/v2 文件。

---

## W2 — `sticky_workbench`

### Purpose

把 v2 workbench 的 six SELECT-callable tools 放到 v3 asynchronous loop 中。所有 workbench TEMP VIEW/KV 操作必须发生在 `AgentWorker.conn_for(run_id)` 所持有的 sticky connection；不经过 v2 `jobs`/`worker()`，也不在 caller connection 创建 fixture 后假定 worker 能看见。

六个工具为：

```text
wb_brief_query
wb_temp_view_list
wb_temp_view_columns
wb_temp_view_create
wb_temp_view_drop
wb_sql_curate
```

### Proposed files and symbols

`v4/sticky_workbench/workbench_core.sql` 从 v2 的设计复制并改成 v4 taxonomy，提供共用 resolver：

```text
_wb_normalize_temp_view_name(text)
_wb_temp_view_oid(text)
_wb_temp_view_columns(oid)
```

B 阶段 resolver 只允许当前 backend 的 `pg_my_temp_schema()`：

- unqualified ASCII identifier；
- reject dotted/quoted/empty/overlong name；
- 只接受 regular TEMP VIEW；
- reject TEMP table、permanent view、materialized view、other backend relation；
- 不把 `pg_my_temp_schema() = 0` 当成真实 schema。

`plugin_brief_query.sql` 提供 bounded read-only `wb_brief_query(text, integer default 20)`，返回 columns、rows、row_count、truncated，限制为 1..50，`NULL` limit 采用 20，`SECURITY INVOKER`。

`plugin_temp_views.sql` 提供 list/columns/create/drop，并复用 v2 validator：

- one SELECT/WITH statement；
- no semicolon、SQL comment、NUL；
- reject DML/utility；
- length bound；
- 依靠 PostgreSQL `CREATE VIEW` validation 处理 data-modifying CTE；
- 不加入 EXPLAIN plan walk；
- replacement/drop 的失败行为写明：普通测试 fixture 用显式 `DROP VIEW` 或 stage reset；view replacement failure 在 function subtransaction 中 rollback，不用 `CASCADE` 隐式清理。

`plugin_sql_curator.sql` 提供 `wb_sql_curate(text,text,text default null)`：

- delegate 到 `wb_temp_view_create()`；
- SQL <= 8000 chars；
- note <= 1000 chars、non-NUL；
- null/empty/whitespace note 表示 clear；
- view replacement + COMMENT 在一个 PL/pgSQL subtransaction；
- COMMENT 失败时旧 view 和旧 note 都保留。

B 的 prompt overlay 替换 `prepare_llm_request()` 的 v4 版本，使其组装：

```text
make_system_prompt(max_rows) + render_plugin_tools()
```

model protocol 仍然是 v3 的 `thought/action/action_input/final_answer`，不是 v2 的 `code` protocol。tool observation 的 outer envelope 与 nested tool result 必须分别解析；outer `success=true` 不等于 nested tool success。

### Stage database and overlay

- Database：`agent_v4_sticky_workbench`。
- Overlay source：从只读 v3 base 和 W1 cumulative overlay 复制；v2 workbench SQL 只能作为 input，改写后的文件落在 `v4/sticky_workbench/`。
- Load order：v3 base -> guard -> W1 taxonomy -> B core -> `plugin_brief_query.sql` -> `plugin_temp_views.sql` -> `plugin_sql_curator.sql`。
- 每个注册 tool SQL file 加载后调用 `refresh_plugins()`，但最终 six-tool count 是 B gate，不把不存在的中间 count 写成加载前提。
- 不需 pgembed change；TEMP VIEW 和 core PostgreSQL 足够。

### Pass gate

1. registry 在 B 最终包含 exactly six workbench tool bindings，且 metadata 都是 v4 `plugin` + `llm_tool`，没有 v2 `workbench_plugin`。
2. `render_plugin_tools()` 描述 v3 action protocol、nested envelope、sticky run scope 和 tool capability。
3. deterministic `scripted()` run 在 worker sticky connection 上 create view -> query view -> final。
4. 同一 `run_id` 后续 turn 能看到前一轮创建的 view/KV；另一个 psycopg connection 看不到。
5. caller connection 创建的 TEMP VIEW 不被误认为 worker fixture；测试使用 `conn_for(run_id)` 明确创建 worker-owned fixture。
6. permanent view、TEMP table、invalid identifier、DML/comment/semicolon、bad replacement、dependent drop 都产生 structured error。
7. 所有 workbench functions 为 `SECURITY INVOKER`，且没有通过旧 `worker()` 执行。
8. B README 记录实际 gate 与 `pgembed change: No`。

### Fail gate

任何 workbench tool 通过 SQL HTTP、不同 backend 访问 TEMP、使用 v2 `code` protocol、直接编辑 v2/v3、或在 cleanup/rollback 上没有明确 `TRUNCATE`/`DROP`/subtransaction 语义，均停止 W3。

---

## W3 — `queue_kinds`

### Purpose

在不修改 `apply_queue_result()` generic dispatcher 的前提下，加入三种实际 queue kind：

```text
embed
sql_heavy
human_inbox
```

建立 queue-specific processor、deferred tool、WAITING state 和 human resume；model/provider selection 仍在 Python。

### Proposed files and symbols

`v4/queue_kinds/queue_kinds.sql` 创建：

```text
embed_requests
embed_requests_dlq
sql_heavy_requests
sql_heavy_requests_dlq
human_inbox
human_inbox_dlq
```

并提供 queue handler comments 和：

```text
human_requests
human_inbox_list()
human_answer(request_id, answer, answered_by default null)
```

`human_requests` 至少包括 `request_id`、`run_id`、prompt/context、queue msg id、`OPEN|ANSWERED|CANCELLED`、answer、timestamps、answered_by。所有 transition 都必须锁 row；duplicate answer 是 structured conflict。answer persistence、step emission、next LLM enqueue、inbox archive 要在同一 transaction。

`plugin_async_tasks.sql` 提供：

```text
wb_request_embedding(text)
wb_request_sql_heavy(text, integer default 50, integer default 120000)
wb_request_human(text, text default null)
```

三者都是 `SECURITY INVOKER`、return `jsonb`、`llm_tool.capability='queue_submit'`、`async=true`、`session_scope='run_connection'`。它们只能从 transaction-local `agent_current_run_id()` 取得 run id，不能接受 caller-supplied `run_id`。成功返回 `defer=true`、`wait_kind`、queue/request id。

`wb_request_sql_heavy()` 使用独立 SQL connection，复用 SELECT/WITH validator，但拒绝 `pg_temp`、`wb_temp_view_*`、`session_set`、`session_get` 依赖。SQL-heavy 不能看到 B 的 sticky TEMP state。

v3 `run_state()` 在 v4 overlay 中保持 return columns 不变，但根据 latest relevant step fold 出：

```text
SUCCESS
ERROR
WAITING_HUMAN
WAITING_QUEUE
RUNNING
```

只有 registry 中标记 `async=true` 的 tool 的成功 deferred result 才能 emit `kind='wait'`；任意普通 SELECT 返回 `defer=true` 都不能暂停 run。

worker processor interface 计划为：

```text
process(message: QueueMessage) -> WorkerResult
```

- `llm`：延续 W1 的 injected/scripted LLM 或 Python LiteLLM；
- `embed`：Python `litellm.embedding()`，测试使用 injected `embed_fn`；
- `sql_heavy`：独立 connection + per-request `statement_timeout`；
- `human_inbox`：automated worker 不 poll，由 `human_answer()` 消费。

C 开始前，setup 做 disposable `CREATE EXTENSION vector`/availability check。预期当前 bundle 直接通过；失败则停止并走 pgembed checklist。

### Stage database and overlay

- Database：`agent_v4_queue_kinds`。
- Overlay source：W2 cumulative loader + 只读 v3 worker semantics 的 stage-local copy。
- Load order：v3 base -> guard -> W1 -> B 四个 SQL files -> `queue_kinds.sql` -> `plugin_async_tasks.sql`。
- queue creation 和 queue cleanup 必须明确：fresh setup 用 drop/recreate database；test message cleanup 对每个 queue 使用 `pgmq.purge_queue()`，不是不明示的 DELETE。
- 不需要新 pgembed extension；现有 `pgmq`、`pgvector` 和 core PostgreSQL 足够。

### Pass gate

1. 三个 additional queues、三个 DLQ、对应 queue handler 都注册；`apply_queue_result()` 仍无 kind branch。
2. deterministic injected embedding processor 完成 request；无 SQL HTTP、无 live provider。
3. sql-heavy 在独立 connection 执行，不能读 B 的 TEMP VIEW/KV；timeout 和 structured SQL error 可验证。
4. scripted model 调用 async tool 后只 emit wait，不立即 enqueue next LLM。
5. `run_state()` 正确报告 `WAITING_QUEUE`/`WAITING_HUMAN`，queue/human result 后只 resume 一次。
6. `human_answer()` 对 open request 成功，对 missing/answered request 返回 conflict；answer、apply、archive/enqueue 的 transaction ordering 可验证。
7. duplicate queue result、duplicate human answer、provider replay 都不产生 duplicate logical steps。
8. pgvector availability gate 和 README 的 `pgembed change: No` 记录完成。

### Fail gate

不得把 queue kind 写成 generic dispatcher 的 if/else；不得自动 worker poll human inbox；不得把 SQL-heavy 放在 sticky run connection；不得让 SQL 决定 embedding/model provider；任一失败停止 W4。

---

## W4 — `subagent_fanout`

### Purpose

用 flat PGMQ fan-out 取代 v2 的 synchronous nested `rlm_spawn()`/`rlm_map()`/`codeact_spawn()`。parent 创建 child runs 后立即进入 wait；child 通过 PGMQ group 独立推进；所有 child terminal 后只唤醒 parent 一次。

### Proposed files and symbols

`v4/subagent_fanout/subagent_fanout.sql` 增加：

- `agent_runs.parent_run_id`；
- `agent_runs.depth`、`max_depth`、`run_name`；
- 不增加 mutable `status` column；
- `agent_wait_groups`（wait id、parent、expected count、wait kind、resumed_at）；
- `agent_wait_members`（wait/child unique pair）；
- `agent_wait_deliveries`（wait/child primary key）。

提供：

```text
wb_spawn_agents(prompts jsonb, names jsonb default null)
maybe_resume_parent(child_run_id text)
```

限制：

- prompts 是 1..8 个 non-empty strings；
- names 在 wait group 内 unique；
- parent depth < max_depth 且 absolute cap 4；
- child max steps <= parent max steps 且 hard cap 6；
- child inherit max_rows 和 session mode；
- child creation、wait rows、first PGMQ messages 一 transaction 完成；
- 不进行 nested SQL LLM loop；
- 每个 child 的 `llm_requests` 使用 `x-pgmq-group=child_run_id`。

child terminal apply 后 `maybe_resume_parent()` 必须 lock wait group，按确定的 child sequence 收集 result，使用 `ON CONFLICT DO NOTHING` 写 delivery，直到全部 terminal 才 emit parent tool step、set `resumed_at`、enqueue exactly one parent request。parent sticky connection 不在 child execution 期间保留；continuation 时按 run id 重新 acquire。

### Stage database and overlay

- Database：`agent_v4_subagent_fanout`。
- Overlay source：W3 cumulative SQL/worker behavior + stage-local copy-from-v3 worker loop；不编辑 W3 source 或 v3 source。
- Load order：v3 base -> guard -> W1 -> B -> C -> `subagent_fanout.sql`。
- wait group/member/delivery 是 durable tables；测试 reset 使用明确的 stage database recreation 或 `TRUNCATE` 指定表，不使用隐式 DELETE。
- 不需 pgembed change；PGMQ groups 和 ordinary PostgreSQL constraints 足够。

### Pass gate

1. parent scripted run 创建至少两个 child，且 SQL source 中不存在 nested LLM while/recursive model loop。
2. 两个 worker/processor 能并发处理 child；测试使用 deterministic barrier/ordering control，不能依赖 timing luck。
3. parent 在所有 child terminal 前保持 `WAITING_QUEUE`。
4. child result 按 deterministic child sequence delivered exactly once；child error 作为 parent data，不被吞掉。
5. replayed child result 不重复 parent wake-up 或 parent enqueue。
6. depth、count、malformed prompt、duplicate name 和 max-step limits 都有 negative tests。
7. README 记录 no pgembed change。

### Fail gate

如果 parent 直接在 SQL 内同步等待 child、使用 nested `WHILE` 调 model、duplicate child replay 会重复唤醒、或 child 结果顺序依赖不稳定 wall-clock，停止 W5。

---

## W5 — `session_durability`

### Purpose

显式比较 v2/B 的 connection-scoped TEMP semantics 与 durable per-run schema semantics，不悄悄改变默认行为。W5 完成后默认仍是 `temp`。

### Proposed files and symbols

`v4/session_durability/session_durability.sql` 增加：

```text
agent_runs.session_mode text not null default 'temp'
agent_start_session(question text, max_steps integer default 10, session_mode text default 'temp')
cleanup_run_session(run_id text)
```

合法 mode：

```text
temp
run_schema
```

`temp`：

- session KV 使用已有 TEMP table；
- workbench views 是 current sticky connection 的 TEMP VIEW；
- sticky connection close 后 state 消失；
- 不同 connection/run 不可见。

`run_schema`：

- schema name 只能由 server-generated `run_id` 派生，例如 `agent_run_<32 hex>`；
- caller 不能传 schema identifier；
- run creation、schema creation 在 `agent_start_session()` 的一个 transaction 中完成；
- per-run `agent_session_kv` 存在生成 schema；
- workbench resolver 根据 current run context 和 `session_mode` 选择 TEMP schema 或 run schema；
- public tool names 可以保持 `wb_temp_view_*` 兼容命名，但 prompt/result 必须说明它实际是 run-scoped view 及其 storage mode；
- identifier quoting 必须由 server-side code 完成。

`cleanup_run_session()` 规则：

- 仅 terminal run 可清理；
- idempotent；
- 只影响指定 run；
- ordinary view drop 不使用 CASCADE；
- 只有显式 run schema cleanup 才能考虑受控 `DROP SCHEMA ... CASCADE`；
- worker terminal 后照旧关闭 sticky connection，但 durable run schema 不自动删除。

### Stage database and overlay

- Database：`agent_v4_session_durability`。
- Overlay source：W4 cumulative stack + stage-local copy-from-v3 worker lifecycle；不修改 v3。
- Load order：v3 base -> guard -> W1 -> B -> C -> D -> `session_durability.sql`。
- setup/test 必须分别记录 TEMP fixture 的 connection close 语义和 run-schema fixture 的 explicit cleanup 语义。
- 不需 pgembed change；schema、TEMP、transaction 和 core catalog 足够。

### Pass gate

1. TEMP-mode view/KV 在 sticky connection close 后消失。
2. run-schema view/KV 在原 connection close 后仍存在，新 worker connection 可 resume 同一 run。
3. 其他 run 不能 resolve/query 第一 run 的 schema。
4. invalid mode、caller-supplied/malformed schema identifier、cross-run current context 都被拒绝。
5. `cleanup_run_session()` 只删目标 run、terminal check 生效、重复调用安全。
6. B 的 TEMP default 和 sticky behavior 完全保持。
7. child run 继承 parent session mode，且不会意外共享 schema。
8. README 记录 no pgembed change。

### Fail gate

如果默认值无意变成 `run_schema`、schema 名可由 caller 注入、connection close 后 TEMP state 仍伪装存在、或 cleanup 使用没有边界的 CASCADE，停止 W6。

---

## W6 — `observability_budget`

### Purpose

为每个 execution step 增加 bounded non-secret metadata，并在 SQL 中执行明确的 token/cost budget gate；model routing、provider choice 和 usage extraction 仍归 Python worker。

### Proposed files and symbols

`v4/observability_budget/observability_budget.sql`：

- 给 `agent_steps` 增加 `meta jsonb not null default '{}'`；
- 保持 `payload` 形状，确保 `fold_messages()` 只消费既有 `llm`/`tool` rows；
- 给 `agent_runs` 增加 nullable `max_total_tokens bigint`、`max_cost_usd numeric(20,8)`；
- `emit_step()` 增加 optional metadata 参数，同时保留已有调用兼容；
- 提供 `run_budget()`、`record_budget_step()`、`apply_queue_failure()`。

允许的 bounded metadata 示例：

```json
{
  "queue": "llm_requests",
  "queue_kind": "llm",
  "msg_id": 42,
  "worker_id": "worker-1",
  "attempts": 3,
  "duration_ms": 3120.5,
  "model": "deepseek-chat",
  "provider": "openai",
  "input_tokens": 850,
  "output_tokens": 120,
  "total_tokens": 970,
  "cost_usd": 0.00042
}
```

禁止写入 `agent_steps.meta`：

- API key、authorization header；
- full prompt 或 full provider response；
- unbounded object；
- filesystem path；
- 任何 secret。

每次 successfully applied LLM result：

1. emit normal `llm` step with normalized worker metrics；
2. insert `kind='budget'` row，写 delta/cumulative/limits/exceeded；
3. budget exceeded 时 emit `error`，不执行 tool，不 enqueue next request；
4. 未超限才继续 final/tool flow。

如果 active hard budget 需要 usage，但 provider result 没有 usage，必须 fail closed 为 structured `budget_unavailable`，不能把 unknown 当作 zero。失败 provider attempts 在 retry exhausted 后可由 `apply_queue_failure()` 记录，但不得制造 duplicate logical LLM step。

`v4/observability_budget/worker.py` 提供 `call_llm_with_metadata()` 或等效接口，normalize raw string/structured scripted result/LiteLLM usage/model/provider/attempts/duration/cost。SQL 不能根据剩余 budget 改 model/provider；SQL 只能记录 Python 已选的实际 model/provider。

### Stage database and overlay

- Database：`agent_v4_observability`。
- Overlay source：W5 cumulative stack + stage-local copy-from-v3 worker plus W6 metrics normalization；不修改 v3。
- Load order：v3 base -> guard -> W1 -> B -> C -> D -> E -> `observability_budget.sql`。
- `agent_steps` metadata test cleanup 使用自己的 fresh database 或明确 `TRUNCATE agent_steps, agent_runs ...`；不得只 DELETE 一部分导致 budget aggregate 混入旧 run。
- 不需 pgembed change；普通 JSONB/numeric/timestamp 足够。

### Pass gate

1. LLM、SQL、embedding、human-related steps 的 metadata 都 bounded 且无 secret/full prompt。
2. deterministic scripted result with synthetic usage 写出正确 `budget` row；`run_budget()` 与 rows 相符。
3. token/cost exceed 会 terminal error，不留下下一条 queue message。
4. active budget + missing usage fail closed。
5. retry attempts 进入 metadata，但不会重复 logical LLM step。
6. SQL 中无 model/provider routing decision。
7. F README 记录 no pgembed change，且 cumulative final run 可从 W1 到 W6 复跑。

### Fail gate

任何 secret/full prompt 落库、budget unknown 当作 zero、budget exceed 后仍执行 tool/enqueue、或 SQL 根据 budget 选择 provider/model，均失败。

## Test design

### 1. Common harness

每个 stage 至少有：

```text
README.md
setup_db.py
test_<slug>.py
```

setup/test 应仿照 `v3/setup_db.py` 和 `v3/test_v3.py`：

- 使用 `pgembed.POSTGRES_BIN_PATH`；
- 使用 `server.get_server()` singleton；
- `run_psql()` 设置 `ON_ERROR_STOP=1`；
- setup 只 drop/create 自己的 DB；
- test 的 main 可先调用自己的 `setup_db.main()`，保证从 fresh state 开始；
- 每项 assertion 输出稳定名字和 detail；
- finally 中关闭 psycopg connections、worker、local fake processor/barrier；
- stage test 失败时立即返回 non-zero，不自动进入下一 stage。

### 2. Mock contract

统一定义一个 stage-local 或 shared copied helper：

```python
def scripted(script):
    state = {"n": 0}
    def fn(messages, **kwargs):
        i = min(state["n"], len(script) - 1)
        state["n"] += 1
        item = script[i]
        return item if isinstance(item, str) else json.dumps(item)
    fn.state = state
    return fn
```

W6 扩展为：

```text
str -> raw model text
{"raw": "...", "metrics": {...}} -> normalized WorkerResult
```

测试必须注入 `llm_fn`/processor；不可通过 `openai.api_uri`、`set_llm_gucs()` 或 SQL HTTP 触发 model。若需要验证 inherited path 被禁用，直接调用 guarded `http_call_llm()` 并 assert clear error，不启动 HTTP server。

### 3. Required assertions

每个 stage test 除自身 gate 外，还要检查：

- SQL HTTP guard；
- no forbidden dependency import/reference in v4 normal path；
- queue archive only after apply；
- duplicate replay behavior；
- structured outer/nested observation where applicable；
- deterministic cleanup semantics；
- source immutability（实现后用 git diff 检查 `v1/`、`v2/`、`v3/` 未变）。

### 4. Test data cleanup matrix

| 数据 | cleanup |
|---|---|
| stage database | setup 时仅 `DROP DATABASE <own_db> WITH (FORCE)` 后 `CREATE DATABASE` |
| PGMQ test messages | 对每个指定 queue 调用 `pgmq.purge_queue()` |
| ordinary test table | 明确 `TRUNCATE ... RESTART IDENTITY` |
| registry probe function | `DROP FUNCTION`，在 `finally` 恢复原 comment |
| wait/budget rows | fresh DB 或显式列出表的 `TRUNCATE`；不得隐式混用 DELETE |
| TEMP VIEW | 当前 connection 中显式 `DROP VIEW`，或关闭 connection |
| run schema | 只调用 `cleanup_run_session(target_run)` |
| worker sticky conns | `AgentWorker.close()`，并在测试中验证 TEMP destruction |

### 5. Gate recording

每个 stage README 在实现后记录：

- command；
- database；
- pass/fail count；
- failed gate 的具体编号；
- 是否触发 pgembed change；
- 若失败，禁止开始下一 stage。

顶层 `v4/README.md` 在 item 2 才创建，记录六阶段累计 order、database、run commands、SQL HTTP prohibition、pgembed decision 和 pg_tle future-only status。

## Hypothetical pgembed change checklist（前六 stage 预期不执行）

只有当某一 stage 的 setup 明确证明当前 bundle 缺少必要 extension，才执行以下顺序：

1. **Stop the stage**
   - 保留失败日志和缺失 extension 的 exact `CREATE EXTENSION`/symbol check；
   - 不修改 v4 设计来绕过；
   - 不引入 pgai、Redis、LiteLLM Proxy、postgres-task-queue、Cordis-in-Postgres；
   - 不把 HTTP model call 放进 SQL。
2. **Modify extension inventory**
   - 在 `pgembed/pgbuild/Makefile` 的 extension list、对应 build/install block、platform gates、preload gates 中加入目标；
   - 使用已有 build convention，不手写未经 pin 的下载逻辑。
3. **Add bundle metadata**
   - 在 `pgembed/tools/generate_bundle_metadata.py` 的 `EXTENSIONS` dict 增加 version、source/ref、sha256、stem、create name、preload name、requires_preload 等完整 metadata；
   - 若 public API 或 metadata exposure 需要，更新 `pgembed/src/pgembed/__init__.py` 和相关 server lifecycle surface。
4. **Add verification**
   - 更新 `pgembed/README.md` 的 user-facing inventory；
   - 更新 `pgembed/.github/workflows/build-and-test.yml` 的 static/runtime/OS matrix；
   - 增加或更新 `pgembed/tests/test_standalone_extensions.py` 及必要的 bundle metadata/build tests；
   - 明确 preload extension 的 server startup test。
5. **Build pgembed first**
   - 在 pgembed root 执行 `make`；
   - 确认 wheel/bundle metadata、standalone tests、CI-equivalent checks 通过；
   - 不在 pg-agent 中使用未安装的 extension。
6. **Install into pg-agent**
   - 回到 `/Users/wxl/Projects/pg-agent`；
   - 执行 `uv sync`，确认新 pgembed wheel 已进入该 environment；
   - 重启 embedded server，避免旧 bundle process 继续运行。
7. **Restart the stopped stage**
   - drop/recreate 该 stage 自己的 database；
   - 从固定 cumulative load order 重跑 setup；
   - 重新执行原 gate；
   - README 记录真实的 pgembed change，而不是预填 No。
8. **pg_tle boundary**
   - `pg_tle` 不属于前六 stage 的 required extension；
   - 只在未来 packaging/distribution 设计中单独评估，不能作为本计划 blocker。

## Runbook（实现完成后的运行方式）

以下命令只在 item 2 实现 v4 文件之后执行；当前 item 1 不创建这些目录。

### 1. Prepare environment

```bash
cd /Users/wxl/Projects/pg-agent
uv sync
```

确保 `uv sync` 使用的 `pgembed` 是当前 bundle；不要设置会把 model HTTP 导回 SQL 的 GUC。worker 的 API/model 参数应由 stage-local Python CLI/config 注入，测试默认使用 deterministic mock。

### 2. Run one stage setup smoke check

每个 `setup_db.py` 都必须创建自己的 database、按固定 cumulative load order 加载 SQL、在每个 registered SQL file 后 refresh registry，并执行 object/extension checks：

```bash
uv run python -m v4.plugin_taxonomy.setup_db
uv run python -m v4.sticky_workbench.setup_db
uv run python -m v4.queue_kinds.setup_db
uv run python -m v4.subagent_fanout.setup_db
uv run python -m v4.session_durability.setup_db
uv run python -m v4.observability_budget.setup_db
```

setup 命令必须按顺序运行；在前一条失败时停止。setup 只负责自己的 DB，不能 drop 其他 stage DB。

### 3. Run stage tests

每个 test module 复用 v3 的 pattern，在 main 中先确保自己的 setup 已完成，或文档明确要求先运行对应 setup；推荐命令：

```bash
uv run python -m v4.plugin_taxonomy.test_plugin_taxonomy
uv run python -m v4.sticky_workbench.test_sticky_workbench
uv run python -m v4.queue_kinds.test_queue_kinds
uv run python -m v4.subagent_fanout.test_subagent_fanout
uv run python -m v4.session_durability.test_session_durability
uv run python -m v4.observability_budget.test_observability_budget
```

推荐的严格执行方式是每个 stage 先运行 setup，再运行 test；test 仍可在自己的 main 中调用 setup 以防止单独执行时使用脏 database。每项 test 返回 non-zero 就停止，不运行后续 module。

### 4. Stage-specific verification order

```text
W1: setup -> taxonomy refresh/validation -> scripted LLM -> replay/DLQ -> gate
W2: setup -> tool refresh count -> sticky workbench scripted run -> isolation/validator -> gate
W3: setup -> vector check -> embed/sql-heavy/human processors -> wait/resume/replay -> gate
W4: setup -> concurrent children -> parent wait/wake -> replay/limits -> gate
W5: setup -> temp close test -> run_schema reconnect test -> cleanup/isolation -> gate
W6: setup -> synthetic metrics -> budget totals/limits -> secret/routing audit -> gate
```

### 5. Final cumulative verification

六个 stage 全部实现后，按 W1 到 W6 再跑一遍：

```text
uv sync
all six setup commands in order
all six test commands in order
git diff -- pg-agent/v1 pg-agent/v2 pg-agent/v3
git diff -- pgembed
```

预期 v1/v2/v3 和 pgembed diff 均为空；唯一例外是确实触发并完成了本文 pgembed checklist。最终检查还必须确认：

- v4 SQL 没有 model HTTP；
- worker 所有模型调用都在 SQL transaction 外；
- processor work 完成后才 apply/archive；
- every stage README 有 gate evidence；
- `pg_tle` 只被描述为后续 packaging option。

## Implementation stop boundary for item 1

本 item 只写入：

```text
pg-agent/docs/plans/v4-expansion-2026-08-28.md
```

本 item 不创建 `pg-agent/v4/`，不创建 database，不运行 expansion，不修改任何 `v1/`、`v2/`、`v3/` 文件，也不修改 pgembed。执行到本文件写入完成即停止。
