# pg-agent v6：PostgreSQL-DuckDB 临时工作台核心功能开发报告

**日期：** 2026-08-28  
**状态：** 核心实现完成；W1–W9 在 2026-08-28 经可靠性审查修复后整串复跑通过。  
**目标：** 在 v5 基础上，以 PostgreSQL 为中心、以 DuckDB 为库外 worker 内的临时分析工作台，对标 InfiniSQL / InfiniSynapse 的核心工作台功能。  
**版本锁定：** 只使用 `duckdb==1.6.0.dev365`；只支持已验证的 macOS arm64 + CPython 3.12。  
**旧版本边界：** 不修改 v1、v2、v3、v4、v5；不修改 pgembed。

---

## 1. 执行摘要

### 1.1 最终结论

v6 **可以开工，而且核心路线是可行的**，但不能把原先“完整 W1–W9 设计”直接当成已证明方案。经过 v5 代码、DuckDB 开发版和 InfiniSQL 逆向资料的逐步核对，应该把 v6 收敛为一个清楚的核心闭环：

```text
PostgreSQL 表
    ↓ 只读、有界快照
当前 agent run 的 DuckDB 内存会话
    ↓ 注册为命名 source / view
DuckDB SELECT 生成命名临时 view
    ↓ 后续操作复用
有界预览、列信息、定义、列表、删除
```

SQL/PLpgSQL 只做三件事：

1. 读取 agent 当前 run 和参数；
2. 把工作台操作记录到 PostgreSQL，并发送 PGMQ 消息；
3. 在 worker 完成后保存有界结果、恢复 agent 循环。

库外 v6 worker 做三件事：

1. 从允许的 PostgreSQL 源读取数据；
2. 在该 run 的 DuckDB 内存会话中注册、查询和管理临时对象；
3. 把结果和错误回写 PostgreSQL。

模型等待、DuckDB 查询和 PostgreSQL 快照读取都不放进 SQL 函数里同步阻塞。

### 1.2 对标 InfiniSQL 的“核心”是什么

本报告只把以下行为作为 v6 的核心目标：

- 注册一个数据源；
- 给结果起一个名字；
- 后续语句引用这个名字，形成链式分析；
- 查看列和有限结果；
- 查看对象定义；
- 列出当前工作台对象；
- 防止删除仍被依赖的对象；
- 出错时返回清楚的四段式诊断，让 agent 可以修正并继续。

这对应逆向资料中最稳定、最值得复用的功能形状：`register_table`、`execute_infinity_sql`、命名临时结果、后续引用、`list_tables`、`show_create`、列信息、`databaseReturnLimit=500` 和 `{Type, Phase, Problem, Solution}` 错误包装。

v6 **不复制** InfiniSynapse 的 NestJS、SSE、SQLite、task-folder、文件归档、delegate merge 或 Spark/Byzer 后端。v6 的相似之处是“工具和工作台行为”，不是“程序结构”。

### 1.3 第一版的明确范围

第一版必须完成：

1. 每个 `run_id` 一个独立 DuckDB 内存会话；
2. 从 PostgreSQL 白名单表读取注册时刻的只读快照；
3. `wb_duck_register` 注册 source；
4. `wb_duck_query` 用显式 `view_name` 创建命名 TEMP VIEW；
5. 同一 run 中后续查询引用已注册 source/view；
6. `wb_duck_brief_query` 做 1–50 行有界预览；
7. `wb_duck_list`、`wb_duck_columns`、`wb_duck_show_create`、`wb_duck_drop`；
8. DuckDB 查询只允许经过验证的单条只读语句；
9. PGMQ 异步队列、重复消息处理、visibility timeout、DLQ；
10. `temp` 会话丢失时 fail closed；`run_schema` 只作为后续可重放能力；
11. 与 v5 的 prompt、named tool、可见缺件生成机制接通；
12. 全链路测试通过后，才能称为“v6 核心功能完成”。

---

## 2. 逐步审查结果：原计划哪些正确，哪些必须修正

### 2.1 正确的部分

以下判断已经得到代码或本地实测支持，可以保留：

- DuckDB 放在库外 worker，而不是 PostgreSQL backend；
- PostgreSQL 继续作为 agent 状态、队列和元数据的事实源；
- 每个 run 使用独立的 DuckDB `:memory:` 连接；
- v6 继续沿用 v5 的 PGMQ → worker → `apply_queue_result()` 边界；
- SQL 侧工具只入队，不直接执行 DuckDB；
- MVP 使用 PostgreSQL → Python 快照 → DuckDB 本地表；
- 查询会话不加载 DuckDB `postgres` 扩展；
- 用显式 `view_name` 生成 `CREATE TEMP VIEW "name" AS <SELECT>`；
- 后续查询通过同一个 run 的 DuckDB 会话引用前一个 view；
- 结果采用“多取一行判断是否截断”的有界预览；
- 需要把 DuckDB 方言说明放入 prompt，而不是做完整 Spark→DuckDB 翻译器；
- v1–v5 和 pgembed 保持只读；
- 只锁定 `duckdb==1.6.0.dev365`，不在 v6 中混入 1.5.x 或其他开发版。

### 2.2 必须修正的部分

#### 修正 A：v6 不能直接追加新的 queue kind

v4/v5 的 `refresh_plugins()` 对 `queue_kind` 使用封闭集合：

```text
llm | embed | sql_heavy | human_inbox
```

所以 v6 若直接给新函数写：

```json
{"queue_handler":{"queue_kind":"duck_heavy"}}
```

然后调用旧的 `refresh_plugins()`，刷新会失败。

**正确做法：** v6 自己提供一个 overlay 版本的 `refresh_plugins()`，完整保留 v5 的校验逻辑，只把 `duck_heavy` 加入合法集合。不能修改 v4/v5 文件，也不能把 DuckDB 队列伪装成 `sql_heavy`。

#### 修正 B：异步等待不是顶层 `defer`

v5 的 `invoke_named_llm_tool()` 会把函数返回值包装成类似：

```json
{
  "success": true,
  "data": [
    {"wb_duck_query": {
      "success": true,
      "defer": true,
      "wait_kind": "duck_heavy",
      "queue": "duck_heavy_requests",
      "request_id": "..."
    }}
  ]
}
```

`apply_llm_response()` 检查的是 `data[0]` 内工具名对应的嵌套对象，而不是顶层对象是否有 `defer`。

**正确做法：** 每个 `wb_duck_*` 函数只返回与现有 `wb_request_sql_heavy()` 同形状的函数内层结果，并在 COMMENT 中标记 `async=true`。v5 的 named tool 和 apply 函数不改。

#### 修正 C：`apply_queue_result()` 不能写 DuckDB 分支

v4 的 generic dispatcher 已按 queue handler 注册表分发，不应该出现：

```plpgsql
IF queue_name = 'duck_heavy_requests' THEN ...
```

**正确做法：** 注册 `apply_duck_heavy_result()` 为 queue handler，让通用 dispatcher 通过 COMMENT 和 `regprocedure` 找到它。

#### 修正 D：唯一键不等于执行顺序

`request_id` 唯一、`(run_id, op_seq)` 唯一只能防重复，不能自动保证 op2 不会早于 op1 执行。

**正确做法：** PostgreSQL 保存 `last_completed_op_seq`，worker 在每次操作前检查：

```text
op_seq == last_completed_op_seq + 1
```

如果 op2 先到，不能把它永久标记失败，也不能调用 DuckDB；应让消息重新经过 visibility timeout，等待 op1 完成。

#### 修正 E：PGMQ 的 `(queue, msg_id)` 幂等还不够

现有 generic dispatcher 可以处理同一个 PGMQ 消息重复 apply，但如果同一个 `request_id` 因异常生成了另一个 `msg_id`，仅依赖 `(queue,msg_id)` 仍会重复执行。

**正确做法：** 增加第二层 operation 幂等：

```text
request_id
(run_id, op_seq)
```

同一个 request 的新消息必须返回 replay/conflict，而不能再次创建 view 或读取源表。

#### 修正 F：不能宣称 DuckDB 和 PostgreSQL 跨库原子提交

DuckDB 事务和 PostgreSQL 事务不是同一个事务，不能声称：

```text
DuckDB COMMIT + PostgreSQL COMMIT = 分布式原子提交
```

**正确说法：** 两边各自原子，整体通过 request_id、operation 状态、worker 本地 completed cache、PGMQ 重试和 metadata 授权实现最终一致性。

如果 DuckDB 已创建 view、PostgreSQL metadata 尚未提交：

- 当前 worker 可用 `request_id` 缓存结果继续 apply；
- worker 死亡时，`temp` 模式标记 session lost；
- `run_schema` 模式从最后一次 PostgreSQL 已提交定义重放；
- PostgreSQL metadata 未承认的 DuckDB 孤儿对象不能对模型开放。

#### 修正 G：`temp` 和可重放模式不是同一种恢复

v4 的 `run_schema` 只负责 PostgreSQL schema/KV 的耐久性，不会自动保存 DuckDB 内存表。

**正确语义：**

- `temp`：worker 进程内存状态；worker 丢失后返回 `DUCK_SESSION_LOST`，不能静默创建空会话；
- `run_schema`：PostgreSQL 保存 source/view 定义和依赖，worker 重启后重新读取源、重建本地表并重放 view；这是“逻辑重放”，不是历史快照恢复。

第一版可以先实现 `temp`，但在设计上不能把两者混为一谈。

#### 修正 H：不能把 `extract_statements().type == SELECT` 当成只读证明

已实测：

```sql
WITH x AS (INSERT ... RETURNING ...) SELECT ...;
WITH x AS (COPY ... TO ...) SELECT ...;
```

外层仍可能被识别为 `SELECT`。

**正确做法：** validator 必须同时检查：

1. 恰好一条 statement；
2. 外层类型为 SELECT；
3. 跳过字符串、注释、引用标识符之后做 token 扫描；
4. 拒绝 DML、COPY、DDL、外部连接、扩展加载、配置修改和已知外部读取函数。

这仍不是形式化沙箱，只能描述为“已知副作用阻断 + external access 关闭 + 只运行受控数据”。

#### 修正 I：不能把 PG 类型矩阵写成已完成

目前只证明了有限的 Python `executemany` 路径。JSONB、数组、numeric 精度、timestamptz、UUID、bytea、扩展类型仍需在 pgembed 活库上逐项验证。

**正确做法：** W3 通过前：

- 已验证的类型才允许注册；
- 未验证类型返回 `DUCK_SOURCE_TYPE_UNSUPPORTED`；
- 禁止未知类型静默转成字符串；
- 禁止读取前 N 行就声称注册成功；
- 超预算和中途失败不留下半成品。

#### 修正 J：DuckDB PostgreSQL extension 不进入 MVP 查询路径

DuckDB 的 `postgres` extension 可以连接 PostgreSQL，并且已经测到 filter pushdown；但同一连接加载扩展后，即使再关闭 external access，`postgres_scan` 仍可能继续出网。

所以：

- 查询会话永不 `LOAD postgres`；
- 模型 SQL 永远拒绝 `ATTACH`、`postgres_scan`、`postgres_query`、`postgres_execute`；
- 默认快照使用 Python PostgreSQL 只读连接和 DuckDB `executemany`；
- sidecar 拷贝通道只能作为未来性能实验，不能成为工作台 catalog；
- 不安装 PostgreSQL 侧 `pg_duckdb`。

---

## 3. 版本、平台与依赖事实

### 3.1 锁定事实

v6 只接受：

```text
Python package: duckdb==1.6.0.dev365
DuckDB engine: v2.0.0-alpha38615
Platform: macOS arm64
Python: CPython 3.12
```

这意味着：

- 包名不是 `duckdb==2.0.0`；
- engine 自报 2.0 alpha 不能写成正式 2.0 GA；
- 不自动兼容 1.5.5；
- 不做 Linux、Windows、Intel macOS 或其他 Python 版本矩阵；
- `pg-agent/pyproject.toml` 后续必须加入精确 pin；
- bump 版本前必须重新执行 W2 probe，不能静默升级。

### 3.2 pgembed 决定

本 v6 方案**不修改 pgembed**。

理由：

- DuckDB 是 pg-agent worker 的 Python 依赖，不是 PostgreSQL server extension；
- pgembed 已有 PostgreSQL、PGMQ 和 agent 所需基础能力；
- `pg_duckdb` 会把 DuckDB 带回 PostgreSQL 进程，破坏 v3/v4/v5 已确立的边界；
- DuckDB `postgres` extension 是 worker 侧客户端扩展，不需要修改 pgembed 才能成为可选实验。

允许修改 `pg-agent/pyproject.toml`，因为这是固定 v6 Python 依赖所必需的项目配置，不属于修改 v1–v5 运行代码。

---

## 4. 推荐架构：PostgreSQL 负责事实，DuckDB 负责临时分析

### 4.1 数据流

```text
用户问题
  ↓
v5/v6 SQL prompt assembly
  ↓
LLM 选择 wb_duck_* named tool
  ↓
PostgreSQL scheduler function
  ├─ 从 agent_current_run_id() 获取 run
  ├─ 校验参数
  ├─ 写 duck_operations
  ├─ pgmq.send('duck_heavy_requests', payload)
  └─ 返回 async defer envelope
       ↓
库外 v6 worker
  ├─ 读取 PGMQ
  ├─ 获取/打开当前 run 的 DuckSession
  ├─ 必要时从 PostgreSQL 白名单源做快照
  ├─ 在 DuckDB 执行操作
  ├─ 产生有界结果或错误
  └─ 调用 apply_queue_result(...)
       ↓
PostgreSQL queue handler
  ├─ 幂等检查
  ├─ 更新 operation/artifact/session 状态
  ├─ 写 agent_steps 有界 observation
  └─ 重新入队下一轮 LLM 或结束 run
```

等待 DuckDB 或远程 PostgreSQL 的时间不占用 PostgreSQL 中的同步 agent SQL 调用者。

### 4.2 三种连接必须分开

#### A. PGMQ polling/apply PostgreSQL 连接

只负责读队列和调用 apply。不能执行 DuckDB 查询。

#### B. source PostgreSQL 连接

只负责访问配置允许的源表：

- 使用只读 transaction；
- schema/table 通过 identifier composition；
- 使用白名单；
- 分批读取；
- 凭据不进入队列 payload 或错误消息；
- 完成后关闭或归还池。

#### C. DuckDB run 连接

每个 run 一条内存连接：

```python
duckdb.connect()
```

启动时必须按顺序设置：

```text
autoinstall_known_extensions = false
autoload_known_extensions = false
enable_external_access = false
memory_limit = configured limit
```

之后不加载 `postgres`、不安装扩展、不打开 external access。每个 run 的 DuckDB 连接不能跨 run 共享。

### 4.3 PostgreSQL 是唯一授权 catalog

DuckDB 内部的临时对象不是最终事实源。PostgreSQL 保存：

- 哪些 source/view 属于哪个 run；
- source 来自哪个不透明 source alias；
- view 的定义和依赖；
- operation 的 request_id/op_seq/status；
- 有界列信息和 preview；
- session 状态和 generation。

没有 PostgreSQL metadata 承认的对象，即使暂时存在于 DuckDB，也不能被后续模型操作引用。

---

## 5. v6 核心对象和工具契约

### 5.1 PostgreSQL metadata

建议新增三张表：

#### `duck_workbench_sessions`

至少包括：

```text
run_id primary key
session_mode: temp | run_schema
status: NEW | OPEN | DEGRADED | LOST | TERMINAL
next_op_seq
last_completed_op_seq
worker_id
session_generation
last_error
created_at / updated_at
```

#### `duck_artifacts`

至少包括：

```text
(run_id, artifact_name) primary key
artifact_kind: source | view
artifact_status: ACTIVE | DROPPED | UNAVAILABLE | LOST
source_id / source_schema / source_table
ingest_mode: snapshot
 definition_sql
 depends_on
 columns
 definition_hash
 generation
```

不存批量源行，不存 DSN、密码或 API key。默认不支持同名 replace。

#### `duck_operations`

至少包括：

```text
request_id primary key
run_id
op_seq
op_kind
queue_msg_id
status: QUEUED | RUNNING | SUCCEEDED | FAILED | DLQ | REPLAYED
request_payload
result_summary
error
worker_id
started_at / finished_at
unique (run_id, op_seq)
```

`request_payload` 只存经过限制的 operation 参数，不能存源凭据或完整 provider payload；`result_summary` 必须有大小上限。

### 5.2 七个 named tool

计划提供：

```text
wb_duck_register(brief, source_id, schema_name, table_name, view_name)
wb_duck_query(brief, view_name, query)
wb_duck_brief_query(brief, view_name, limit)
wb_duck_list(brief)
wb_duck_columns(brief, view_name)
wb_duck_show_create(brief, view_name)
wb_duck_drop(brief, view_name)
```

共同规则：

- `brief` 必填且有长度上限，只描述意图，不作为 SQL；
- run 只能由 `agent_current_run_id()`取得；
- LLM 不能传 `p_run_id`；
- 参数错误不创建 operation、不发送 PGMQ；
- 每个工具只入队，绝不执行 DuckDB；
- COMMENT 只注册 `llm_tool`；queue handler 使用另一函数；
- `async=true`、`capability=queue_submit`、`session_scope=run_connection`；
- 返回 v5 能识别的函数内层 defer 对象。

### 5.3 工具语义

#### register

读取允许的 PostgreSQL 表，复制成当前 run 的 DuckDB source。注册是快照，不是 live view。源表后续更新不会改变当前 source；重新注册是另一个明确操作。

#### query

传入一条 DuckDB SELECT 和显式 view name。worker 生成：

```sql
CREATE TEMP VIEW "validated_name" AS <validated_select>
```

成功后才把 artifact 标记 ACTIVE。重复名称默认失败；在证明 `CREATE OR REPLACE` 回滚可以恢复旧 view 前，不开放 replace。

#### brief_query

不创建新 artifact，只读取当前 active source/view；默认 20 行，范围 1–50；取 `limit+1` 以返回 `truncated`。

#### list / columns

返回当前 run 的白名单 artifact 和列定义，不把 DuckDB 内部系统 catalog 全部暴露给模型。

#### show_create

返回 PostgreSQL metadata 保存的 view definition、依赖、generation、columns。对 source 返回 source alias、源表身份和快照列信息。这是与 InfiniSQL `show_create` 对齐的安全近似，不执行远程 `SHOW CREATE`。

#### drop

没有依赖时删除当前 DuckDB 对象并将 metadata 标记 DROPPED；有 active view 依赖时拒绝，不使用 CASCADE，不删除 operation 审计。

---

## 6. DuckDB 查询安全和资源边界

### 6.1 允许的查询

按当前开发版实测，第一版可以允许：

- 单条 SELECT；
- CTE 和 recursive CTE；
- FROM-first；
- LIMIT/FETCH FIRST；
- 聚合、窗口函数；
- `QUALIFY`、`PIVOT`、`ASOF JOIN`；
- 已验证的 JSON、VARIANT 和常用分析函数。

“允许”只表示引擎和 validator 通过，仍要受结果、内存和时间预算限制。

### 6.2 必须拒绝的路径

validator 需要拒绝：

```text
INSERT UPDATE DELETE MERGE COPY
CREATE ALTER DROP TRUNCATE
ATTACH DETACH CONNECT DISCONNECT
INSTALL LOAD
CALL PRAGMA SET RESET USE
SECRET EXPORT VACUUM CHECKPOINT
postgres_scan postgres_scan_pushdown postgres_query postgres_execute
read_csv read_csv_auto read_json read_parquet glob httpfs
```

不能简单禁止 `WITH`、`LIMIT` 或 `PIVOT`；这些是合法分析语法。也不能只检查第一个关键字。

### 6.3 查询不是完整沙箱

v6 的安全声明必须诚实：

> v6 通过关闭自动安装/自动加载和 external access，结合已知副作用 token/function 阻断以及受控 source 数据，降低工作台风险；它不是对任意 DuckDB SQL 的形式化安全证明。

因此：

- query session 不加载外部扩展；
- 不允许用户自行改变 DuckDB 配置；
- 不允许本地文件直读；
- 错误信息必须截断和脱敏；
- 未来若要开放文件、live Postgres 或扩展，必须另开 gate。

### 6.4 资源默认值

建议先以 worker 配置固定：

```text
automatic preview: 500 rows, fetch 501
brief preview: default 20, max 50
query text: max 16,000 chars
query timeout: 120 seconds
DuckDB memory: 512 MiB
result_summary: max 256 KiB
source rows/bytes: fixed worker limits
```

这些是 v6 初始配置，不是永远不变的协议；实现后要以实测结果更新 README。

---

## 7. 与 v5 的关系

v6 不是另起一套 agent，也不是重写 v5 的 prompt 或循环。

### 7.1 v5 直接复用的部分

- v5 的 17 个 inherited SQL 路径；
- `assemble_prompt_messages()` 的按 slot 组装；
- 缺件时第一轮可见 agent 回合生成 role/task 等 prompt 部件；
- `wb_store_prompt_part` 的 recipe-global 复用规则；
- `invoke_named_llm_tool()` 的按名调用；
- `apply_queue_result()` 的 generic queue handler 分发；
- PGMQ 的读、visibility timeout、archive 和 DLQ 思路；
- agent_steps、run_state、预算和错误回写风格。

v6 只通过自己的 SQL overlay 和本地 worker 接入 DuckDB，不修改 v5。

### 7.2 v6 新增的部分

- `duck_workbench_sessions`、`duck_artifacts`、`duck_operations`；
- `duck_heavy_requests` 和 DLQ；
- `duck_heavy` queue kind 的 taxonomy overlay；
- DuckSession/DuckSessionManager；
- PostgreSQL source resolver 和 snapshot ingress；
- DuckDB read-only validator；
- 七个 `wb_duck_*` scheduler tools；
- DuckDB 方言 prompt recipe version；
- DuckDB 结果/错误/预算处理器。

### 7.3 prompt 需要告诉模型什么

v6 prompt 不需要重做 POML 引擎，但要把 DuckDB 工作台作为有序 prompt slot 内容注入：

- DuckDB 工具名称和参数；
- `view_name` 是独立参数，不是尾置 `AS name` 物化语法；
- 注册是快照；
- 先 register，再 query，再 preview；
- 同一 run 才能引用自己的 artifacts；
- PostgreSQL sticky TEMP view 和 DuckDB artifact 是两套工作台，互不可见；
- 使用 DuckDB SQL，不假设 Spark/Byzer 函数存在；
- 遇到四段式错误，依据 Solution 修正；
- 一次只发一个异步工作台 action，收到 wait 后等待结果，不猜结果。

高风险方言提示至少包括：

```text
date_format → strftime
get_json_object → json_extract / 路径访问
collect_list → list / array_agg
year/month/day → extract / date_part
split → string_split
explode → unnest
Spark Java regex → DuckDB/RE2 regex 子集
```

策略是“prompt 直接教真实 DuckDB 方言”，不做一个容易产生静默错误的 Spark shim。

---

## 8. 分阶段开工计划与停止条件

每个阶段单独建库，前一阶段不过，不进入下一阶段。目录已创建在 `pg-agent/v6/`。

### W1：`kernel_freeze/`

**目标：** 只读加载 v5 基线。

**实现：**

- 新建 `v6/load.py`；
- 复制 v5 的路径字面量，但路径仍指向 v3/v4/v5；
- 不 `import v5.load`；
- 新建 v6-local worker 基线，不从 v5 runtime import；
- 允许修改 `pg-agent/pyproject.toml` 的精确 DuckDB pin，但不改旧代码。

**通过门：**

- 前 17 个 SQL 路径与 v5 一致；
- v5 prompt、named tool、generic apply 通过 smoke test；
- 无 v1–v5 内容复制；
- 无 SQL-side model HTTP；
- v1–v5/pgembed diff 为空。

**失败停止：** 需要修改旧版本、路径复制成 v6 副本、或基线失败。

### W2：`duckdb_probe/`

**目标：** 固化实际开发版行为。

**必须实测：**

- 精确包/engine/platform；
- connection hardening；
- TEMP VIEW commit/rollback；
- duplicate create；
- `CREATE OR REPLACE` rollback（只记录事实，不预设结论）；
- `extract_statements`；
- DML-in-CTE/COPY-in-CTE；
- `fetchmany` 和 limit+1；
- `interrupt()` 线程/watchdog 行为；
- validator 对字符串、注释和 quoted identifier 的处理；
- 查询连接没有加载 postgres extension。

**通过门：** 所有后续实现依赖的语义有自动化证据。

**失败停止：** 版本/platform 不符、取消不可靠、或硬化设置无法建立。

### W3：`source_ingress/`

**目标：** 证明 PostgreSQL → DuckDB 快照通道。

**实现：**

- `duck_sources.sql` 建立 metadata 表；
- worker source resolver 将 source_id 映射到配置；
- 使用只读 PostgreSQL connection；
- 分批 fetch/load；
- 显式类型映射；
- 超预算/不支持类型结构化失败。

**通过门：**

- bool、整数、浮点、numeric、文本、date、timestamp、timestamptz、UUID、bytea、JSONB、受支持数组完成真实矩阵；
- NULL、边界值、时区通过；
- 注册后更新源表不会改变当前 snapshot；
- 失败不留 DuckDB 半成品；
- payload、steps、error 无凭据。

**失败停止：** 未知类型只能靠静默字符串化、读取被截断却报告成功、或源权限无法收紧。

### W4：`session_durability/`

**目标：** 明确 session 生命周期。

**第一版要求：**

- `temp` 行为先实现；
- `run_schema` 可以作为定义重放实验；
- 同 run 可链式引用；
- 不同 run 完全隔离；
- worker 丢失不能生成空 session。

**通过门：**

- temp loss → `DUCK_SESSION_LOST` → run error；
- run_schema 能按依赖顺序重读源和重放 view；
- 源数据变化被标记为 rehydrated/degraded；
- 子 run 不共享父 artifacts；
- PostgreSQL metadata 不保存 bulk rows。

### W5：`queue_bridge/`

**目标：** 加入 PGMQ DuckDB 队列和通用 apply。

**实现必须成批完成：**

1. `refresh_plugins()` v6 overlay；
2. `duck_heavy_requests`/DLQ；
3. `apply_duck_heavy_result()`；
4. operation gate；
5. v6 worker 的 DuckDB processor；
6. retry/DLQ 处理。

**通过门：**

- 新 queue kind 能 refresh；
- generic dispatcher 无 queue-name 分支；
- op2 先到会等待；
- 同消息重复只 apply 一次；
- 同 request 新消息不重复执行；
- worker 读后崩溃可按 visibility timeout 重放；
- DuckDB commit 后 PG apply 前崩溃有确定语义；
- DLQ 会把 operation 标为 DLQ，不留下永久 QUEUED。

**失败停止：** 只有 SQL queue 没有 worker consumer，或队列执行时会重复创建 artifact。

### W6：`duck_tools/`

**目标：** 把工作台能力变成 v5 named tool。

**通过门：**

- 参数错误不发队列；
- 没有 current run 时拒绝；
- `invoke_named_llm_tool()` 能看到七个名字；
- 返回形状被 `apply_llm_response()`识别为一个 wait；
- worker 执行前 SQL 端没有访问 DuckDB 或源表；
- operation 和 queue send 在同一 PostgreSQL transaction 中。

### W7：`dialect_guardrails/`

**目标：** 只读 validator + DuckDB 方言 prompt。

**通过门：**

- SELECT、CTE、LIMIT、FROM-first、PIVOT 等已验证语法通过；
- DML/COPY-in-CTE、DDL、ATTACH、LOAD、INSTALL、`postgres_*` 和文件函数拒绝；
- 字符串/注释/quoted identifier 中的禁词不误判；
- v6 prompt 显示 DuckDB 工具和方言提示；
- v5 可见缺件生成行为仍然存在；
- v6 不声称完整 Spark/Byzer 兼容。

### W8：`budget_observability/`

**目标：** 资源控制、结果规整、错误脱敏。

**通过门：**

- timeout 调用 `interrupt()`，事务 rollback；
- memory limit 失败可识别；
- preview/result summary 有大小上限；
- Decimal、日期、UUID、bytes、数组、非有限浮点可安全转换；
- DSN/password/token 不进入错误、日志、queue 或 agent_steps；
- operation 审计有界；
- DuckDB budget 不绕过 v5 LLM token/cost budget。

### W9：`integration/`

**目标：** 全链路核心验收。

**必须跑通：**

1. v5 prompt 缺件 → 可见首轮生成 → 存储 → 再检索；
2. 模型按名调用 `wb_duck_register`；
3. PostgreSQL 表快照进入 DuckDB；
4. 查询创建命名 view；
5. 第二个查询引用第一个 view；
6. brief/list/columns/show-create/drop；
7. 依赖 view 阻止错误 drop；
8. 同 run 可见、跨 run 不可见；
9. PostgreSQL sticky TEMP 与 DuckDB artifact 互不可见；
10. temp worker loss；
11. run_schema hydrate；
12. duplicate/out-of-order/retry/DLQ；
13. source type rejection；
14. timeout/memory/result bounds；
15. 静态检查 v1–v5/pgembed 无修改；
16. SQL 无模型 HTTP；
17. worker 不直接调用 v5 `apply_llm_response()`。

只有 W9 全部通过，才将 `v6/README.md` 状态改为“核心功能完成”。

---

## 9. 推荐文件布局

当前已建立目录 README；后续实现按以下边界落文件：

```text
pg-agent/
├── pyproject.toml                    # 只增加精确 duckdb pin
├── v6/
│   ├── README.md
│   ├── load.py
│   ├── kernel_freeze/
│   │   ├── README.md
│   │   ├── worker.py
│   │   ├── setup_db.py
│   │   └── test_kernel_freeze.py
│   ├── duckdb_probe/
│   │   ├── README.md
│   │   └── test_duckdb_probe.py
│   ├── source_ingress/
│   │   ├── README.md
│   │   ├── duck_sources.sql
│   │   ├── duckdb_ingress.py
│   │   ├── setup_db.py
│   │   └── test_source_ingress.py
│   ├── session_durability/
│   │   ├── README.md
│   │   ├── duckdb_runtime.py
│   │   ├── setup_db.py
│   │   └── test_session_durability.py
│   ├── queue_bridge/
│   │   ├── README.md
│   │   ├── duck_queue.sql
│   │   ├── duckdb_processor.py
│   │   ├── setup_db.py
│   │   └── test_queue_bridge.py
│   ├── duck_tools/
│   │   ├── README.md
│   │   ├── duck_tools.sql
│   │   ├── setup_db.py
│   │   └── test_duck_tools.py
│   ├── dialect_guardrails/
│   │   ├── README.md
│   │   ├── duck_prompt.sql
│   │   ├── duckdb_validation.py
│   │   ├── setup_db.py
│   │   └── test_dialect_guardrails.py
│   ├── budget_observability/
│   │   ├── README.md
│   │   ├── duckdb_results.py
│   │   ├── duckdb_errors.py
│   │   ├── duck_budget.py
│   │   ├── setup_db.py
│   │   └── test_budget_observability.py
│   └── integration/
│       ├── README.md
│       ├── setup_db.py
│       └── test_v6.py
└── docs/analysis/
    └── v6-infinisql-core-development-2026-08-28.md
```

### 文件边界原则

- SQL 文件只负责 PostgreSQL metadata、scheduler、COMMENT、queue handler 和 prompt recipe；
- Python 文件负责 DuckDB、source 连接、validator、结果和错误；
- worker 文件负责队列消费和 apply 编排；
- 测试文件必须同时包含成功和失败门；
- 不把 v4/v5 SQL 复制进 v6；只读路径由 loader 指向旧文件。

---

## 10. 失败处理、回滚与迁移

### 10.1 临时会话丢失

```text
temp worker loss
  → DUCK_SESSION_LOST
  → session LOST
  → run ERROR
  → 用户重新启动一个 run
```

不静默创建空 DuckDB，会避免模型看到一个和此前状态不同但名字相同的工作台。

### 10.2 可重放会话

`run_schema` 只重放已存定义：

```text
PostgreSQL metadata
  → 重新读取 source
  → 按依赖顺序创建 DuckDB source
  → 按定义顺序重建 view
  → 标记 rehydrated/degraded
```

源表已经变化时，不能把新结果称为旧快照；若源或定义不可用，应将 artifact 标记 unavailable，而不是伪造成功。

### 10.3 v6 回滚

v6 使用独立数据库：

```text
agent_v6_kernel_freeze
agent_v6_duckdb_probe
...
agent_v6_integration
```

回滚步骤：

1. 停止 v6 worker；
2. 停止接收 v6 新 run；
3. 切回 v5 数据库和 v5 worker；
4. 不把 v6 queue 交给 v5 worker；
5. 不把 v6 queue COMMENT 加载到 v5 数据库；
6. 保留或删除独立 v6 数据库，按审计要求处理。

v5 不需要理解 v6 的 DuckDB queue。

---

## 11. 最终验收标准

v6 核心版必须同时满足：

### 功能

- 能注册 PostgreSQL 白名单表；
- 能在 DuckDB 中建立命名 view；
- 能链式查询；
- 能返回有限预览、列信息、列表和定义；
- 能保护依赖关系；
- 错误可以指导 agent 修正。

### 架构

- SQL 不等待 DuckDB 或模型 HTTP；
- DuckDB 只在库外 worker；
- 每个 run 隔离；
- PostgreSQL 保存事实和审计；
- PGMQ 是唯一新增队列；
- 没有 Redis、Celery、LiteLLM Proxy 或 pg_duckdb 作为运行时必需组件。

### 安全

- query session 不加载 postgres extension；
- external access 在连接创建时关闭；
- DML-in-CTE/COPY-in-CTE 不会绕过 validator；
- source 访问有 allowlist；
- 凭据不进入模型可见内容；
- 结果和错误有界、脱敏。

### 可靠性

- visibility timeout 可重试；
- duplicate message 不重复 apply；
- duplicate request 不重复执行；
- op_seq 乱序不会破坏工作台；
- DLQ 会留下明确终态；
- DuckDB/PostgreSQL 不声称分布式原子提交；
- temp loss 和 replayable drift 有公开、可测试的语义。

### 版本边界

- Python 包精确为 `duckdb==1.6.0.dev365`；
- 只测试 macOS arm64 + CPython 3.12；
- v1–v5 无修改；
- pgembed 无修改；
- 未通过的阶段不得向后跳过或用其他 DuckDB 版本替代。

---

## 12. 开工建议

下一步不是同时写九个阶段，而是严格按以下顺序：

1. 修改 `pg-agent/pyproject.toml`，加入精确 DuckDB pin；
2. 实现 W1 loader 和 v6-local baseline worker；
3. 运行 W1 gate；
4. 实现 W2 probe，先证明版本和连接安全边界；
5. W2 通过后再写 PostgreSQL source ingress；
6. 完成 W3 类型矩阵后才进入 session 和 queue；
7. W5 的 SQL handler、worker processor 和测试必须一起落地；
8. 最后再把工具注册到 v5 prompt，并进行全链路验证。

**不要**先写完整 DuckDB worker 再补安全；不要先做 `postgres` live catalog；不要先做 SAVE、文件读取、ET/ML、图数据库或多 worker；不要为了“看起来像 InfiniSQL”而复制它的外围架构。

v6 的成功标准不是“功能最多”，而是：

> PostgreSQL 仍然掌握事实和进度，DuckDB 能可靠地作为每个 agent run 的临时分析工作台，模型可以用少量清楚的工具完成注册、查询、链式分析和有界查看，而且任何失败都不会把数据库或 worker 长时间卡住。


---

## 13. 实施完成记录（2026-08-28）

W1–W9 已按顺序实现并在独立数据库中通过，随后完成 Oracle 代码审查和 P0/P1 修复，再次整串复跑：

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

实施期间新增并确认的事实：

1. `TIMESTAMPTZ` 结果读取需要 Python `pytz`，已作为显式依赖锁定。
2. psycopg2 在当前环境可能把 `uuid[]` 返回为 PostgreSQL array text，已做受控转换；未知类型仍 fail closed。
3. PIVOT 在 `1.6.0.dev365` 虽能执行，但 `extract_statements()` 展开为 `CREATE + SELECT`，不满足 v6 单 statement 安全门，因此核心版禁止 PIVOT。
4. source 和 view 必须按 DuckDB catalog 类型分别删除；`DROP VIEW IF EXISTS` 对已存在 table 仍会报类型错误。
5. DuckDB commit 与 PostgreSQL apply 仍不是分布式原子提交；实现采用 operation claim、完成缓存、run_schema 重放和 temp fail-closed。
6. 实际常驻 worker 已接入 DuckDB processor，并通过 `AgentWorker.pump_once()` 全路径测试，不再只是直接调用 processor 的实验。
7. apply handler 在 PostgreSQL 事实源边界再次检查 op_seq，不能跳过前序 operation。
8. malformed queue message 会进入 DLQ；Duck operation 同步收敛为 `DLQ`。

仍然接受的限制：

- 只支持 macOS arm64 / CPython 3.12 / `duckdb==1.6.0.dev365`；
- 单一可信数据库角色，不提供多租户 SQL 身份隔离；
- temp worker loss 终止 run；run_schema 重放读取当前源数据，不恢复历史快照；
- 不支持 live PostgreSQL catalog、文件直读、PIVOT、多 worker 自动 session affinity 或跨引擎原子提交。
