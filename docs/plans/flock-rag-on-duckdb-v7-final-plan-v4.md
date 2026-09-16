> **SUPERSEDED — 2026-08-29:** This Oracle v4 draft is replaced by `flock-rag-on-duckdb-final-plan-v4.1.md`. Do not use it for implementation.

# Oracle Plan



# Flock RAG on DuckDB：v7 最终开发计划 v4

> **权威状态**
>
> - `flock-rag-on-duckdb-final-plan-v3.md`：**superseded**，不再作为实施依据。
> - 本文：**Oracle v4 权威开发计划**。
> - 本计划继承 v3 的证据分级、design review 纠正和四仓版本约束；新要求优先覆盖旧设计。
> - 本计划只描述架构、接口、文件影响、验证门和实施顺序，不修改代码。

---

## 1. Summary

v7 在 v6 的基础上增加一个**deployment-scoped、持久化的 Flock RAG 平台**，但不把永久 RAG 数据放入 v6 的 `DuckSessionManager`、`duck_artifacts`、`duck_workbench_sessions` 或 `duck_heavy_requests`。v6 继续负责 run-scoped、临时、内存 DuckDB 工作台；v7 新建独立的 deployment RAG runtime，使用由目标 DuckDB fork 构建的 Python binding、专用持久 DuckDB 文件、deployment owner、RAG 专用队列和新的 Postgres 元数据。Flock C++/SQL 负责 MinerU JSON 的树形解析与持久 catalog、chunk/range、BM25、dense `NEAREST`、multi-vector、候选构造、排序和检索 metrics；pg-agent v7 Python 负责 MinerU 进程接入、deployment/connection/queue 生命周期、LongContextRAG 的查询扩展、LLM relevance filter、TokenLimiter、context/QA prompt、streaming、兼容 facade 以及错误兜底。MinerU、KohakuRAG、duckdb-tachiom、tachiom、mdenseon 的实际契约必须在 Phase 0 读取并冻结；在这些接口冻结前不得臆造 API、模型输入输出 shape 或插件 target 名称。

---

# 2. Current-state analysis

## 2.1 现有 Flock 扩展架构

Flock 当前是 DuckDB C++ extension，入口为：

```text
src/flock_extension.cpp
  → LoadInternal()
      → Config::Configure(loader)
      → Registry::Register(loader)
      → SecretManager::Register(loader)
      → 注册 ParserExtension / OperatorExtension
```

职责关系如下：

| 组件 | 当前职责 |
|---|---|
| `flock_extension.cpp` | DuckDB extension 入口、Flock 自定义 parser/binder hook |
| `Config` | `flock_config` schema、全局 `flock_storage` 文件、模型和 prompt 配置 |
| `Registry` | 统一注册 scalar/aggregate functions |
| `ScalarRegistry` | `llm_complete`、`llm_embedding`、`llm_filter`、fusion 和 metrics 函数 |
| `AggregateRegistry` | `llm_first`、`llm_last`、`llm_rerank`、`llm_reduce` |
| `Model` / `IProvider` | OpenAI、Azure、Ollama、Anthropic 的 completion、embedding、transcription |
| `MetricsManager` | 当前 DuckDB database-level、thread-local invocation metrics |
| `Config::db` | 静态全局 `DatabaseInstance*`，不适合 deployment 并发 RAG |

当前没有以下能力：

- MinerU JSON 解析；
- document/section/node/edge/page/table/image 的持久树形 catalog；
- deployment 级 DuckDB 文件管理；
- BM25 RAG catalog；
- dense vector retrieval；
- DuckDB 2.0 `NEAREST` 驱动的检索函数；
- tachiom multi-vector adapter；
- schema catalog / schema RAG；
- LongContextRAG 的 query expansion、TokenLimiter、context assembly 或 streaming facade。

### 当前可复用代码

可以复用：

- `Registry` 的 extension function 注册模式；
- `src/CMakeLists.txt` / 根 `CMakeLists.txt` 的 DuckDB extension 构建框架；
- `nlohmann::json` 依赖；
- Flock 现有 `FusionRRF` 中的基础 rank-fusion 思路，但不能直接把它当成完整 RAG ranking engine；
- DuckDB 的 `DataChunk`、table function、scalar function、`Value` 和类型系统；
- 当前 metrics 的 provider/API token 统计概念。

不应复用：

- `Config::db` 静态全局状态作为 deployment owner；
- `Config::get_global_storage_path()` 的 `~/.duckdb/flock_storage/flock.db`；
- `StorageAttachmentGuard`；
- `Model` / `IProvider` 作为 mdenseon dense encoder 的抽象；
- `LlmRerank` 作为 auto-coder LongContextRAG 的 relevance/ranking parity 实现；
- `MetricsManager` 的 thread-local invocation context 作为跨 deployment RAG metrics 存储。

`llm_rerank` 当前实现会创建模型、调用 LLM、执行 sliding-window，并根据 LLM 返回的 `flock_row_id` 生成顺序。它不是一个通用的“给定候选和分数后排序”的无副作用引擎，不能冒充 auto-coder.rag 的 relevance filter、score ordering 或 original-document reorder。

---

## 2.2 v6 当前 DuckDB 工作台架构

v6 已建立的是 run-scoped 临时分析链：

```text
wb_duck_* named tool
  → PostgreSQL scheduler function
      → duck_operations / duck_workbench_sessions
      → pgmq: duck_heavy_requests
          → DuckDBWorkerProcessor
              → DuckSessionManager.get_or_open(run_id)
                  → DuckSession(connection=:memory:)
                      → snapshot_table / CREATE TEMP VIEW / preview
          → apply_queue_result()
```

关键现有组件：

| 文件 | 当前责任 |
|---|---|
| `v6/source_ingress/duckdb_ingress.py` | 通过 psycopg2 从 PostgreSQL 读取有界 snapshot，使用 `CREATE TABLE` + `executemany` |
| `v6/session_durability/duckdb_runtime.py` | 创建和管理 run-scoped in-memory DuckDB connection；支持 `temp` 和 `run_schema` replay |
| `v6/queue_bridge/duckdb_processor.py` | 处理 `register/query/brief_query/list/columns/show_create/drop` |
| `v6/dialect_guardrails/duckdb_validation.py` | `extract_statements` + 保守 token scan 的只读校验 |
| `v6/source_ingress/duck_sources.sql` | `duck_workbench_sessions`、`duck_artifacts`、`duck_operations` |
| `v6/queue_bridge/duck_queue.sql` | `duck_heavy_requests`、queue handler 和 `apply_duck_heavy_result()` |
| `v6/duck_tools/duck_tools.sql` | enqueue-only `wb_duck_*` named tools |
| `v6/load.py` | 继承 v3/v4/v5 SQL，并按 stage 累积加载 v6 SQL |

v6 的硬约束：

- DuckDB connection 是 `:memory:`；
- session 状态按 `run_id` 维持；
- `temp` 模式在 worker 丢失后返回 `DUCK_SESSION_LOST`；
- `run_schema` 只按 Postgres 元数据重读 source、重放 view definition，不恢复历史行；
- `duck_artifacts` 只记录临时 source/view 定义；
- `duck_heavy_requests` 是临时工作台操作队列；
- v6 查询 connection 打开后关闭自动安装、自动加载和 external access，且不加载 `postgres`；
- v6 中 PostgreSQL TEMP 和 DuckDB TEMP 互不可见。

### v7 必须明确不复用的 v6 组件

v7 RAG 不得依赖：

```text
DuckSessionManager
DuckSession
duck_workbench_sessions
duck_artifacts
duck_operations
duck_heavy_requests
wb_duck_register
wb_duck_query
wb_duck_brief_query
```

v7 可以复用 agent 的通用运行基础设施，例如 Postgres server、PGMQ、generic result application 或 named-tool dispatch 边界，但必须使用新的 RAG operation metadata、RAG queues、deployment identity 和永久文件语义。

---

## 2.3 已核验的外部事实和证据等级

本计划采用以下证据分级：

| 等级 | 含义 |
|---|---|
| E0 | 未读取、未知或仅为假设，不能作为实现事实 |
| E1 | 已检查源代码、测试或静态契约 |
| E2 | 已在目标 runtime、fixture 或真实服务上运行验证 |
| E3 | 已完成跨仓库集成、回归和性能验收 |

当前事实：

### auto-coder.rag：E2

已现场核验：

- `local_duckdb_storage_cache.py` 使用 `.cache/byzerai_store_duckdb.db`；
- 主要字段为 `_id`、`file_path`、`content`、`raw_content`、`vector FLOAT[]`、`mtime`；
- 使用 `list_cosine_similarity`；
- 默认 similarity `0.1`、top_k `10000`、vector dimension `1024`；
- 代码使用 `json`、`fts`、`vss`；
- `enable_hybrid_index` 默认关闭。

LongContextRAG 的关键模块已定位：

```text
long_context_rag.py
rag_entry.py
rag_config.py
document_retriever.py
relevant_utils.py
token_limiter.py
token_counter.py
token_checker.py
doc_filter.py
conversation_to_queries.py
qa_conversation_strategy.py
llm_wrapper.py
llm_request_timeout.py
types.py
cache/
stream_event/
```

已知行为：

1. query extraction / expansion；
2. document recall；
3. ThreadPoolExecutor + LLM yes/no relevance filtering；
4. relevance score 排序；
5. original-document order 恢复；
6. TokenLimiter：
   - 小文件合并；
   - 大文件切分；
   - 1-based line ranges；
7. context assembly；
8. QA generation；
9. streaming generator；
10. `without_contexts`；
11. timeout/retry/cancel；
12. 中文错误兜底。

公开兼容入口：

```text
RAGManager.search() → List[SourceCode]
stream generator → stream events
```

### DuckDB target fork：E1/E2 gate pending

目标 fork：

```text
/Users/wxl/Projects/duckdb-pgagent
branch: integration/grammar-24919-20260829
tag: duckdb-special-20260829-g1
commit: a1f0ab1911
status: clean
```

已确认：

- 存在 `GrammarExtension`、`GrammarChange`、`active_grammar_extensions`、`duckdb_grammar_extensions()`；
- legacy `ParserExtension` / `AllowParserOverride` 仍然存在；
- `NEAREST` 语法形状来自 DuckDB tests：

```text
INNER JOIN ...
  APPROX | EXACT NEAREST N
  BY DISTANCE | SIMILARITY <expr>
```

- 不写数字时默认 top-1；
- 当前 `APPROX` 可能与 `EXACT` 使用相同执行路径。

目标 fork 必须在目标构建产物上重新运行 NEAREST 测试；不能只引用上游测试或博客。

### duckdb-python-pgagent：E1

当前构建配置：

```text
BUILD_EXTENSIONS=core_functions;json;parquet;icu
```

已确认：

- generated loader 和 `WHOLE_ARCHIVE` 链接存在；
- 当前没有 Flock；
- 当前没有 static Flock tests；
- `fts`、`vss`、tachiom 是否可作为静态 extension target 使用，尚未完成契约盘点；
- mdenseon 是否是 DuckDB extension、native library、Python package 或其他模型接口，尚未冻结。

### MinerU/KohakuRAG/duckdb-tachiom/mdenseon：E0

以下路径已定位，但当前 loaded roots 未包含源码内容，不能把接口名称和数据结构当成事实：

```text
/Users/wxl/Projects/repoprompt-ce-agno
/Users/wxl/Projects/repoprompt-ce-agno/benchmarks/duckrag_wi1/p19_mineru_process.py
/Users/wxl/Projects/repoprompt-ce-agno/benchmarks/duckrag_wi1/p16_mdenseon.py
/Users/wxl/Projects/repoprompt-ce-agno/benchmarks/duckrag_wi1/fixtures
/Users/wxl/Projects/rag/KohakuRAG
/Users/wxl/Projects/bookohakurag/KohakuRAG
/Users/wxl/Projects/duckdb-tachiom
/Users/wxl/Projects/tachiom
```

Phase 0 必须读取这些路径并冻结契约。

### Infinisynapse：E1

参考证据路径：

```text
/Users/wxl/ghidra-projects/infinisynapse-reverse
/Users/wxl/ghidra-projects/docs/research/infinisynapse-agent-system
/Users/wxl/ghidra-projects/docs/infinisynapse-how-it-works.md
/Users/wxl/ghidra-projects/infinisynapse-reverse/analysis/infinisynapse-complete-re.md
```

已确认的设计参考：

```text
list_tables
  → show_create
      → register_table
          → execute SQL
```

以及：

```text
schemaContext.md
kpiContext.md
activeContext.md
use_rag_tool
RAG → Schema → SQL
```

这些是功能和流程参考，不是要求复制 JDBC、DatabaseHub、SQLite、SSE 或 Infinisynapse 的内部架构。

---

## 2.4 当前差距矩阵

| 能力域 | 当前状态 | 证据 | v7 目标 | 关闭条件 |
|---|---|---|---|---|
| v7 runtime 生命周期 | 只有 v6 run-scoped in-memory `DuckSession` | E2 | deployment-scoped persistent store，worker 重启可重开同一文件 | deployment restart、owner lease、reader/writer 测试 |
| 连接/文件/owner | v6 无持久文件；连接属于 `run_id` | E1/E2 | 每 deployment 独立 text/schema DuckDB 文件；一个受 lease 保护的 write owner | 多 worker owner fencing、文件锁、恢复测试 |
| RAG queues | 只有 `duck_heavy_requests` | E1 | 新建 RAG ingestion/index/query queue；不使用 v6 queue | duplicate、retry、cancel、DLQ 测试 |
| MinerU tree ingestion | 不存在 | E0 | MinerU JSON → canonical tree → revisioned DuckDB catalog | 真实 MinerU fixtures 全量导入、树不变量通过 |
| document/section/node/edge/page/table/image/metadata | 不存在 | E0 | 全部成为 revision-scoped relational tables | schema contract freeze + round-trip |
| chunk/range | v6 只有 view preview，没有文档 range | E1 | Flock canonical chunk、1-based line/page/node range | range property tests |
| BM25 | auto-coder 使用 FTS，Flock 没有实现 | E2/E1 | Flock managed BM25 index/query | golden BM25 ranking |
| dense retrieval | Flock 没有 mdenseon | E0/E2 | mdenseon adapter + `NEAREST` | shape/dim/batch/error gate |
| multi-vector retrieval | 不存在 | E0 | duckdb-tachiom adapter，稳定 Flock result contract | tachiom API/build/runtime gate |
| score ordering | 当前仅有 `FusionRRF` 和 LLM rerank | E1 | reusable `RagScoringEngine`，支持 retrieval/LLM score fusion、tie-break、document reorder | deterministic ranking tests |
| LongContextRAG | pg-agent v6 没有 v7 facade | E2 | 完整 query expansion → recall → filter → rank → limiter → QA → stream | auto-coder parity suite |
| TokenLimiter | v6 不存在 | E2 | 保留小文件合并、大文件切分、1-based ranges | line/token golden tests |
| schema RAG | 不存在 | E1 | 独立 schema catalog/index/provider/context | DuckDB catalog snapshot + redaction tests |
| schema/text 共存 | 不存在 | E0 | text PDF index 与 schema index 分离，统一 provider contract | route and isolation tests |
| API 安全 | v6 source alias 和 query guardrails 仅针对临时工作台 | E1/E2 | deployment-bound RAG API，不暴露 DSN、文件路径、任意 SQL 或 extension load | adversarial security suite |
| 版本一致性 | Flock CI v1.5.4；v6 wheel 为 `1.6.0.dev365`；target fork 另有 commit | E1/E2 | v7 使用四仓精确版本 manifest，禁止 floating branch | clean rebuild from manifest |

---

# 3. Design

## 3.1 四仓版本和依赖约束

v7 和 v6 使用不同 DuckDB runtime。v6 的 `duckdb==1.6.0.dev365` 继续冻结，v7 不得把该 wheel 当作永久 RAG runtime。

| 仓库 | v7 约束 | 处理方式 |
|---|---|---|
| `pg-agent` | v7 从 v6 基线派生；v6 文件只读 | 新增 `v7/`；不修改 v6 runtime、v6 metadata 或 v6 queue |
| `flock` | 必须与目标 DuckDB fork 的 ABI/API 一致 | 使用目标 fork 构建；不得默认使用当前 `duckdb` submodule 的 floating `main` |
| `duckdb-pgagent` | 固定 `duckdb-special-20260829-g1` / `a1f0ab1911` | branch 只作为 provenance，构建和 CI 以 commit 校验 |
| `duckdb-python-pgagent` | 固定 Phase 0 记录的 clean commit，并由目标 DuckDB fork 构建 | 将 Flock 和 tachiom 作为静态或已验证的 bundled extension；不能回退到 PyPI stock wheel |
| `repoprompt-ce-agno` | 仅作 auto-coder/benchmark/fixture 证据源 | 不作为 v7 runtime dependency |
| `KohakuRAG` / `bookohakurag` | 仅作 MinerU/Kohaku 契约参考 | 不复制其服务、数据库或任务架构 |
| `tachiom` / `duckdb-tachiom` | Phase 0 冻结具体 commit、target 和 API | 在 API 未冻结前不得写 Flock adapter implementation |

### 版本 manifest

Phase 0 必须生成一个只读的 v7 manifest，至少包含：

```text
pg-agent commit
flock commit
duckdb-pgagent commit = a1f0ab1911
duckdb-python-pgagent commit
duckdb engine version
Python version
macOS architecture
mdenseon commit/version
duckdb-tachiom commit
tachiom commit
MinerU contract/version
KohakuRAG contract/version
```

CI 必须在构建前验证 manifest。任何工作树 dirty、commit 不匹配或 runtime version 不匹配都直接失败。

---

## 3.2 两套生命周期和边界

### v6：run-scoped temporary workbench

| 维度 | v6 语义 |
|---|---|
| Identity | `run_id` |
| 生命周期 | 一个 agent run |
| DuckDB connection | `DuckSessionManager` 持有的 `:memory:` connection |
| 文件 | 无永久文件 |
| owner | 当前 worker 进程 |
| 状态 | `duck_workbench_sessions`、`duck_artifacts` |
| queue | `duck_heavy_requests` |
| API | `wb_duck_register/query/brief_query/list/columns/show_create/drop` |
| 失败 | temp worker 丢失 → `DUCK_SESSION_LOST` |
| replay | `run_schema` 只重读 source 并重放 definition |
| 数据归属 | run 内临时 source/view |
| 迁移 | 不迁移到 v7；必须重新注册/重新 ingestion |

### v7：deployment-scoped permanent RAG

| 维度 | v7 语义 |
|---|---|
| Identity | 受控的 `deployment_id`，不能由模型自由指定 |
| 生命周期 | deployment 存续；跨 run、跨 conversation、跨 worker restart |
| DuckDB files | 每个 deployment 至少两个文件：`text` 与 `schema` |
| connection | `DeploymentRagStore` 管理持久文件 connection；reader/writer 连接分离 |
| owner | 由 Postgres lease 和 OS file lock 保护的 RAG worker/service |
| 状态 | Postgres 只存 operation/deployment/manifest；树、chunk、vector 在 DuckDB |
| queue | 新的 RAG queue family，例如 `rag_ingest_requests`、`rag_index_requests`、`rag_query_requests` |
| API | `use_rag_tool`、Python `RAGManager`/`LongContextRAG` facade、Flock RAG SQL functions |
| worker restart | 重新打开同一个文件，校验 schema/index manifest，恢复 deployment owner |
| ingestion failure | DuckDB transaction rollback；旧 active revision 保持可查询 |
| query failure | 不修改 active catalog；返回结构化 `RAG_*` error |
| migration | catalog schema migration 和 revision/index generation migration 独立于 v6 |
| rollback | 停止 owner、备份/恢复 deployment files；不能让旧 binary 原地降级未知 DuckDB file format |

### 强制边界

下列关系必须永远成立：

```text
v6 run_id / DuckSession / duck_artifacts
    ≠
v7 deployment_id / rag.duckdb / RAG catalog
```

```text
PostgreSQL agent run state
    ≠
v7 DuckDB permanent tree/vector data
```

```text
schema RAG physical index
    ≠
text/PDF RAG physical index
```

v7 的部署数据不能存储在：

- `v6/session_durability/duckdb_runtime.py`；
- `v6/source_ingress/duckdb_ingress.py` 创建的临时表；
- `duck_artifacts`；
- `duck_heavy_requests`；
- Flock 当前 `flock_storage` global configuration database。

---

## 3.3 v7 deployment storage、owner 和连接管理

### `DeploymentRagStore`

新增 Python runtime component，建议位于：

```text
pg-agent/v7/rag_runtime/deployment_store.py
```

它是 deployment-scoped manager，不继承或包装 `DuckSessionManager`。

#### 所有状态

```text
deployment_id
text_db_path
schema_db_path
owner_worker_id
owner_lease_generation
text_writer_connection
schema_writer_connection
reader_connections
catalog_schema_version
index_manifest_version
closed
```

#### 文件布局

路径由 operator 配置的 RAG root 和受控 `deployment_id` 生成：

```text
<RAG_ROOT>/<deployment_id>/text/rag.duckdb
<RAG_ROOT>/<deployment_id>/schema/rag.duckdb
<RAG_ROOT>/<deployment_id>/manifest.json
<RAG_ROOT>/<deployment_id>/backups/<generation>/
```

模型、用户输入和普通 named tool 参数不得直接提供文件路径。

#### 打开顺序

1. 由 deployment registry 解析 `deployment_id`；
2. 验证文件路径仍在配置的 RAG root 下；
3. 在 Postgres 获取 deployment owner lease；
4. 获取 text/schema 文件锁；
5. 打开对应 DuckDB 文件；
6. 验证 DuckDB engine、Flock ABI、tachiom backend 和 manifest；
7. 由 Flock `RagCatalog` 执行兼容的 schema migration；
8. 只加载已静态打包且已签名验证的 extension；
9. 关闭 auto-install/autoload/external access；
10. 初始化 read-only reader pool；
11. 将 owner generation 写回 Postgres。

v7 不使用 runtime `INSTALL`/`LOAD` 下载 extension。Flock、FTS、tachiom 必须在 `duckdb-python-pgagent` 构建期静态链接，或者使用 Phase 0 明确验证过的受控本地加载方式。

#### 并发模型

- 每个 deployment 同时只有一个 writer owner；
- query reader 可以并发读取当前 active generation；
- ingestion/index build 在 writer connection 上串行；
- query 不持有 writer lock；
- owner lease 失效时，旧 worker 必须在执行写入前重新检查 generation；
- 旧 owner 不能在新 owner 接管后继续提交；
- worker restart 不丢文件数据，只丢内存连接；
- deployment close 关闭所有 reader/writer connection，但不删除文件。

---

## 3.4 Postgres v7 metadata 和 queue boundary

Postgres 是 v7 的运行编排和 operation source of truth，但不存储 bulk tree rows、全文、embedding 或 raw MinerU JSON。

### Postgres metadata

新增表建议：

#### `rag_deployments`

至少包含：

```text
deployment_id             text primary key
status                    text
storage_root_alias        text
text_db_generation        bigint
schema_db_generation      bigint
owner_worker_id           text
owner_lease_generation    bigint
owner_lease_expires_at    timestamptz
catalog_version           integer
index_manifest_hash       text
created_at                timestamptz
updated_at                timestamptz
```

`storage_root_alias` 是配置 alias，不是任意用户路径。

#### `rag_document_manifests`

只记录：

```text
deployment_id
document_id
source_uri_redacted
source_hash
mineru_contract_version
active_revision
status
last_operation_id
updated_at
```

不记录：

- raw MinerU JSON；
- PDF 内容；
- embedding；
- full document text；
- DSN 或 secret。

#### `rag_operations`

至少记录：

```text
operation_id
deployment_id
operation_kind
idempotency_key
requested_generation
status
payload_reference
result_summary
error
worker_id
started_at
finished_at
created_at
```

`payload_reference` 指向受控 staging/object source；大 JSON 不进入 PGMQ message。

### Queue

v7 新建独立 queue family：

```text
rag_ingest_requests
rag_index_requests
rag_query_requests
rag_ingest_requests_dlq
rag_index_requests_dlq
rag_query_requests_dlq
```

实际 queue 名称在 Phase 0 结合 v7 现有 queue registry 冻结，但必须满足：

- 不使用 `duck_heavy_requests`；
- 不使用 `(run_id, op_seq)` 作为 RAG operation ordering；
- ingestion/index 以 `(deployment_id, document_id, revision, idempotency_key)` 去重；
- query 以 `request_id` 去重；
- queue payload 只含 deployment ID、operation ID、source reference、hash、限制参数；
- 不含 DSN、secret、raw JSON、完整 PDF 内容；
- deployment owner 按 lease 处理写操作；
- query 可在 active generation 上并发执行；
- reindex 不覆盖旧 active generation，直到新 generation 完成。

---

## 3.5 MinerU JSON → tree-preserving DuckDB schema

### 契约冻结原则

Phase 0 必须读取真实 MinerU 输出、`p19_mineru_process.py`、KohakuRAG 两套实现和 fixtures，冻结：

- JSON root 形状；
- document/page/section/node 的 ID 来源；
- block/node 类型枚举；
- bbox 坐标系统；
- page number 是否从 0 或 1 开始；
- table/image asset 引用；
- markdown/text 字段；
- heading hierarchy；
- source line/range 生成规则；
- MinerU version 和 schema version；
- unknown node 的处理方式。

下列 canonical schema 是 v7 的**稳定内部目标形状**。真实 MinerU 字段必须映射到这些列；不能因为某个版本的 JSON 字段不同就把原始字段直接暴露给上层 API。

### Document 层

#### `rag_document`

每个 `document_id` 表示逻辑文档，不直接等于 revision。

| 字段 | 类型 | 说明 |
|---|---|---|
| `deployment_id` | `VARCHAR` | deployment owner |
| `document_id` | `VARCHAR` | 稳定文档 ID |
| `active_revision` | `BIGINT` | 当前 active revision |
| `title` | `VARCHAR` | 规范化标题 |
| `source_uri` | `VARCHAR` | 已脱敏来源标识 |
| `source_hash` | `VARCHAR` | PDF/JSON content hash |
| `language` | `VARCHAR` | 语言，可空 |
| `page_count` | `INTEGER` | 页数 |
| `mineru_version` | `VARCHAR` | 处理版本 |
| `contract_version` | `VARCHAR` | canonical contract version |
| `created_at` | `TIMESTAMP` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 更新时间 |

#### `rag_document_revision`

所有树节点、chunk、vector 都带 revision。

| 字段 | 类型 |
|---|---|
| `deployment_id` | `VARCHAR` |
| `document_id` | `VARCHAR` |
| `revision` | `BIGINT` |
| `status` | `VARCHAR`：`BUILDING` / `ACTIVE` / `RETIRED` / `FAILED` |
| `content_hash` | `VARCHAR` |
| `raw_mineru_json` | `JSON` |
| `parser_version` | `VARCHAR` |
| `created_at` | `TIMESTAMP` |
| `activated_at` | `TIMESTAMP` |

`(deployment_id, document_id, revision)` 为主键。

### Tree 层

#### `rag_section`

| 字段 | 类型 | 说明 |
|---|---|---|
| `deployment_id` | `VARCHAR` | |
| `document_id` | `VARCHAR` | |
| `revision` | `BIGINT` | |
| `section_id` | `VARCHAR` | revision 内稳定 ID |
| `parent_section_id` | `VARCHAR` | root 为 NULL |
| `section_level` | `INTEGER` | heading depth |
| `ordinal` | `INTEGER` | 同级顺序 |
| `title` | `VARCHAR` | |
| `path` | `VARCHAR` | canonical section path |
| `page_start` | `INTEGER` | 1-based |
| `page_end` | `INTEGER` | 1-based |
| `bbox_json` | `JSON` | 可空 |
| `raw_json` | `JSON` | 原始 section |

#### `rag_node`

所有可检索或结构化的 MinerU block 都进入 node。

| 字段 | 类型 |
|---|---|
| `deployment_id` |
| `document_id` |
| `revision` |
| `node_id` |
| `parent_node_id` |
| `section_id` |
| `node_kind` |
| `ordinal` |
| `text` |
| `normalized_text` |
| `page_start` |
| `page_end` |
| `line_start` |
| `line_end` |
| `char_start` |
| `char_end` |
| `content_hash` |
| `raw_json` |

`node_kind` 必须以 Phase 0 的 MinerU/Kohaku contract 为准，至少支持：

```text
heading
paragraph
list
list_item
code
formula
caption
table_ref
image_ref
unknown
```

不能识别的 node 不得静默丢弃；必须保留在 `raw_json`，并标记 `unknown` 或返回明确的 contract warning。

#### `rag_edge`

用于保留 tree 和 cross-reference 关系：

| 字段 | 类型 |
|---|---|
| `deployment_id` |
| `document_id` |
| `revision` |
| `edge_id` |
| `src_node_id` |
| `dst_node_id` |
| `edge_kind` |
| `ordinal` |
| `metadata_json` |

至少覆盖：

```text
contains
parent
next
references
caption_of
table_of
image_of
```

#### `rag_page`

| 字段 | 类型 |
|---|---|
| `page_id` |
| `document_id` |
| `revision` |
| `page_number` |
| `width` |
| `height` |
| `rotation` |
| `page_text` |
| `raw_json` |

`page_number` 对外统一为 1-based；若 MinerU 输入是 0-based，转换只允许发生在 parser boundary。

#### `rag_table`

| 字段 | 类型 |
|---|---|
| `table_id` |
| `document_id` |
| `revision` |
| `node_id` |
| `page_id` |
| `ordinal` |
| `caption` |
| `header_json` |
| `rows_json` |
| `markdown` |
| `raw_json` |

#### `rag_image`

| 字段 | 类型 |
|---|---|
| `image_id` |
| `document_id` |
| `revision` |
| `node_id` |
| `page_id` |
| `ordinal` |
| `asset_ref` |
| `alt_text` |
| `caption` |
| `bbox_json` |
| `raw_json` |

`asset_ref` 必须是受控、可授权的引用，不允许把任意本地路径直接暴露给模型。

#### `rag_metadata`

| 字段 | 类型 |
|---|---|
| `deployment_id` |
| `document_id` |
| `revision` |
| `metadata_key` |
| `metadata_value` |
| `metadata_json` |
| `source` |

metadata 允许保存 MinerU/Kohaku 扩展字段，但不能绕过 canonical schema 直接把扩展字段当作安全的 SQL identifier。

### Retrieval 层

#### `rag_chunk`

Flock 负责生成 canonical retrieval unit。

| 字段 | 类型 |
|---|---|
| `chunk_id` |
| `document_id` |
| `revision` |
| `section_id` |
| `node_start_id` |
| `node_end_id` |
| `page_start` |
| `page_end` |
| `line_start` |
| `line_end` |
| `chunk_ordinal` |
| `text` |
| `normalized_text` |
| `token_count` |
| `content_hash` |
| `active` |

约束：

- line range 一律 1-based、闭区间；
- chunk 不跨 document；
- 默认不跨 section，除非 Phase 0 的 legacy parity 证明必须跨 section；
- 超长 node 可以切分，但必须通过 node/line range 反向定位原文；
- query-time TokenLimiter 可以进一步合并或切分 context，但不能改写 canonical source range。

#### `rag_vector`

| 字段 | 类型 |
|---|---|
| `vector_id` |
| `chunk_id` |
| `document_id` |
| `revision` |
| `vector_role` |
| `model_name` |
| `model_version` |
| `dimension` |
| `embedding` |
| `normalized` |
| `created_at` |

`vector_role` 至少允许：

```text
dense_text
dense_title
dense_section
image
table
```

实际 role 集合必须由 mdenseon 和 tachiom contract freeze 后确定。未知 role 不能被静默映射为 `dense_text`。

#### `rag_index_manifest`

记录每个 revision 的 index generation：

```text
deployment_id
document_id
revision
index_kind              -- bm25 / dense / multi_vector
backend_name
backend_version
dimension
status                  -- BUILDING / READY / FAILED / RETIRED
manifest_hash
created_at
```

查询只能使用 `READY` 且属于 active revision 的 index。

---

## 3.6 MinerU ingestion 算法和原子性

### 输入路径

```text
MinerU process
  → JSON artifact/reference
  → v7 Python source adapter
  → hash/version validation
  → rag_ingest_requests
  → v7 deployment owner
  → Flock flock_rag_ingest_mineru(...)
  → canonical parser
  → tree + chunks + metadata
  → index build
  → active generation swap
```

queue payload 只包含：

```text
deployment_id
document_id
source_reference
content_hash
mineru_contract_version
requested_revision
operation_id
```

### Flock ingestion boundary

新增 Flock table function 或等价 extension function，稳定逻辑接口为：

```text
flock_rag_ingest_mineru(document_id, mineru_json, ingest_options)
    → revision/status/counts/hash
```

具体 DuckDB function kind 由 Phase 1 按 Flock 当前注册模式确定；接口必须满足：

- 接受 bound JSON/value，不拼接用户 SQL；
- 不在 function 内自行提交外部事务；
- 由调用方包在一个 DuckDB transaction 中；
- 失败时所有当前 revision 的 tree/chunk/index 变更回滚；
- 不修改旧 active revision；
- 输出 node、edge、page、table、image、chunk 计数和 warning。

### 树不变量

每次 ingestion 必须验证：

1. document revision 存在且唯一；
2. 至少一个 root section 或明确的无 section 文档模式；
3. section parent 不形成环；
4. node parent 不形成环；
5. 所有 parent/reference ID 可解析，或被明确标记为 unresolved；
6. page number 在 `[1, page_count]`；
7. section/node ordinal 在同一父节点下稳定；
8. node line range 是 1-based 且 `start <= end`；
9. table/image reference 指向真实 node；
10. edge 不产生非法 self-loop，除非 contract 明确允许；
11. `source_hash`、`raw_mineru_json` 和 revision manifest 一致；
12. unknown node 仍有 raw JSON 保留。

### Revision swap

```text
BUILDING revision
  → parse complete
  → chunk complete
  → BM25 index READY
  → dense index READY
  → multi-vector index READY
  → transactionally set active_revision
  → old revision RETIRED
```

如果任一 index backend 失败：

- 不设置新 revision 为 active；
- 保留旧 active revision；
- `rag_operations` 标记失败；
- 返回 `RAG_INDEX_BUILD_FAILED`；
- 不静默降级到另一种 retrieval backend，除非请求明确设置 `allow_backend_fallback=true`，且该选项默认值为 `false`。

---

## 3.7 Flock C++/SQL retrieval engine

### 3.7.1 统一 search output

Flock 对 Python 暴露稳定的 candidate result，不暴露 backend-specific row shape：

```text
flock_rag_search(query, options)
    → candidate_id
      document_id
      revision
      chunk_id
      vector_role
      backend
      retrieval_score
      normalized_score
      rank
      page_start
      page_end
      line_start
      line_end
      section_path
      text
      metadata_json
```

options 至少包含：

```text
retrieval_mode:
    bm25 | dense | multi_vector | hybrid
top_k
min_score / min_similarity
model_name
vector_roles
include_text
include_metadata
timeout_ms
active_revision_only
```

deployment_id 不由模型传入；由当前 `DeploymentRagStore` 绑定。

### 3.7.2 BM25

Flock 负责：

- canonical chunk 的 text normalization；
- BM25 index creation/manifest；
- query tokenization boundary；
- score normalization；
- document/chunk metadata join；
- deterministic tie-break。

如果目标 DuckDB Python 构建可以静态提供目标版本的 FTS，Flock 使用该 FTS 能力；如果 Phase 1 证明 FTS target/API 不稳定，则在 Flock 中提供受控 BM25 implementation。不能在运行时 auto-install FTS。

BM25 的 exact tokenization、stemming、stop-word 和 score 解释必须以 auto-coder baseline 和目标 FTS runtime 的实测结果为准，不能仅按函数名称推断。

### 3.7.3 dense vector 与 `NEAREST`

Flock 增加独立 dense encoder abstraction，不修改 `Model` / `IProvider`：

```text
IDenseEmbeddingBackend
    encode(texts, model_config)
        → vectors + model/dimension metadata
```

原因：当前 `IProvider` 是 completion/embedding/transcription provider，不适合强行承载 mdenseon 的未知 native/API shape。

DuckDB SQL builder 使用目标 fork 已确认的语法族：

```text
INNER JOIN ... APPROX|EXACT NEAREST [N]
BY DISTANCE|SIMILARITY <expr>
```

具体表达式、参数位置、是否要求括号和 vector operand 类型必须由目标 fork 的 tests 冻结。实现不得按照博客或旧 fork 猜测语法。

规则：

- 配置了 `top_k > 1` 时显式产生 `N`；
- 默认 top-1 时不强行添加未经验证的数字语法；
- `DISTANCE` 和 `SIMILARITY` 必须在 Flock boundary 统一成 `normalized_score`；
- `APPROX` 是否真正近似只以目标 fork 的执行计划和结果测试为准；
- 当前可能 `APPROX == EXACT`，不得在产品文档中声称已获得 approximate speedup；
- vector dimension 必须与 `rag_index_manifest` 和 query vector 一致；
- dimension mismatch 返回 `RAG_VECTOR_DIMENSION_MISMATCH`。

### 3.7.4 mdenseon

mdenseon 的以下内容在 Phase 0/1 关闭前必须冻结：

- import/build 方式；
- native 或 Python API；
- 输入是单字符串、batch、token IDs 还是结构化对象；
- 输出是单 vector、多个 vector 还是 role map；
- dtype；
- dimension；
- normalization；
- batch size；
- timeout/cancel；
- model lifecycle；
- CPU/GPU/thread safety。

v7 只保留一个稳定 Flock boundary：

```text
encode(text_batch, model_config)
    → {vectors, dimension, model_version, normalized}
```

mdenseon 的实际调用可由 Flock C++ adapter 或 v7 Python adapter 承担，取决于 Phase 0 发现的真实 API。该决策必须在 Phase 1 写入 manifest；不能同时实现两套隐式路径。

如果 mdenseon shape 与 auto-coder 现场的 `1024` 维不一致，必须：

- 记录实际 shape；
- 明确 compatibility mapping；
- 重新生成 baseline；
- 不通过截断、padding 或静默 reshape 假装兼容。

### 3.7.5 duckdb-tachiom multi-vector

`tachiom` 和 `duckdb-tachiom` 的 API/模型 shape 尚未读取，不设计假 API。Phase 0 必须冻结：

- extension target 名；
- static/loadable 形式；
- vector storage shape；
- 多向量 role/field 命名；
- index build API；
- query API；
- score/distance semantics；
- update/delete/rebuild；
- transaction/connection safety；
- 是否支持 `NEAREST`；
- 是否能与 Flock 的 persistent table/index manifest 共存。

Flock 提供稳定 adapter seam：

```text
IMultiVectorIndex
    build(revision, vector_rows, options)
    search(query_vectors, options)
    drop_or_retire(generation)
```

实际 tachiom API 只能在 adapter 内部使用。pg-agent 和 Flock SQL 的公共结果不得暴露 tachiom 私有对象。

如果 tachiom gate 未通过：

- P3 multi-vector 不得标记完成；
- dense/BM25 可以独立验收；
- `retrieval_mode=multi_vector` 返回 `RAG_MULTI_VECTOR_UNAVAILABLE`；
- 不得静默退回 dense，除非调用方显式允许 fallback。

---

## 3.8 Reusable scoring/ranking engine

当前 `fusion_rrf` 和 `llm_rerank` 不足以承接 LongContextRAG。新增：

```text
RagScoringEngine
RagCandidate
RagRankedCandidate
```

### 输入

每个 candidate 至少包含：

```text
candidate_id
document_id
chunk_id
document_ordinal
chunk_ordinal
bm25_score?
dense_score?
multi_vector_score?
llm_relevance_score?
page_start/page_end
line_start/line_end
```

### 排序步骤

1. 按 backend 分别过滤无效值、NULL 和 NaN；
2. 将各 backend score 转为明确的 normalized score；
3. 对多 query expansion 结果按 `candidate_id` 去重；
4. 保留最佳 score 和来源 query；
5. 按配置执行 weighted sum、RRF 或 multi-vector fusion；
6. 如果有 Python 返回的 LLM relevance score，作为显式输入，不在 Flock 内调用 LLM；
7. 计算 document-level score；
8. 先决定 document 顺序；
9. 在同一 document 内按原始 `document_ordinal`、`chunk_ordinal`、line range 稳定排序；
10. 应用 top-k 和上下文预算前的 candidate cap；
11. 输出稳定 tie-break：

```text
combined_score DESC
document_score DESC
document_ordinal ASC
chunk_ordinal ASC
candidate_id ASC
```

### Flock API

增加一个可复用的 ranking function/table function：

```text
flock_rag_rank_candidates(candidates_json, options)
    → ranked candidate rows
```

它只执行分数和顺序计算，不做 LLM HTTP，不读取 conversation，不生成 QA prompt。

这条路径与 `llm_rerank` 分离：

- `llm_rerank` 保持现有用户行为；
- `RagScoringEngine` 面向结构化 candidate；
- 两者不互相调用；
- 不能为了复用 `llm_rerank` 而改变现有 LLM aggregate function 的输入输出。

---

## 3.9 RAG metrics

现有 `MetricsManager` 仍服务当前 Flock LLM functions。RAG 增加显式 context 的 metrics manager：

```text
RagInvocationContext
RagMetricsManager
```

每个 invocation 显式传入：

```text
deployment_id
request_id
document_generation
query_hash
```

记录：

```text
query_expansion_count
bm25_candidate_count
dense_candidate_count
multi_vector_candidate_count
deduplicated_candidate_count
llm_filter_input_count
llm_filter_accept_count
final_context_count
backend_latency_us
filter_latency_us
token_count
first_token_latency_us
total_latency_us
cancelled
error_type
```

默认不保存原始 query、prompt、secret、PDF 内容。query 只保存不可逆 hash，除非 operator 明确开启审计模式。

metrics 可以：

- 作为 search result 的 bounded `metrics` object 返回；
- 写入 DuckDB `rag_query_metrics`，按 deployment retention 清理；
- 由 pg-agent 发送 summary 到现有 observability 层。

不要把 RAG metrics 放入当前 thread-local `MetricsManager` 的静态 context；RAG query 会跨 Python future、DuckDB reader 和 LLM calls。

---

## 3.10 Schema RAG

### 物理隔离

schema RAG 使用独立的：

```text
<RAG_ROOT>/<deployment_id>/schema/rag.duckdb
```

不得与 text/PDF 的 `rag_document`、`rag_chunk` 或 vector index 共用同一物理 index。可以共享同一个 deployment owner，但必须有独立 catalog、index manifest 和 ranking namespace。

### Schema canonical catalog

至少覆盖：

#### `schema_snapshot`

```text
snapshot_id
source_kind               -- duckdb_local / controlled_external
source_alias
database_name
schema_name
captured_at
catalog_hash
status
```

#### `schema_relation`

```text
snapshot_id
relation_id
schema_name
relation_name
relation_kind             -- table / view / materialized_view / sequence
comment
row_estimate?
create_sql
```

#### `schema_column`

```text
snapshot_id
relation_id
ordinal
column_name
logical_type
nullable
default_expression
comment
```

#### `schema_key`

```text
snapshot_id
relation_id
key_kind                  -- primary / unique / foreign
constraint_name
column_names_json
referenced_relation_id?
referenced_columns_json?
```

#### `schema_relationship`

```text
snapshot_id
source_relation_id
source_columns_json
target_relation_id
target_columns_json
relationship_kind
confidence
```

#### `schema_sample`

```text
snapshot_id
relation_id
sample_json
sample_policy
redaction_status
```

#### `schema_profile`

```text
snapshot_id
relation_id
column_name
null_fraction
distinct_estimate
min_value_redacted?
max_value_redacted?
profile_status
```

样本和 profile 默认关闭或强脱敏；不得把敏感列值直接送入 schema RAG。

### Schema source API

Flock 直接读取 DuckDB：

```text
information_schema
duckdb_tables()
duckdb_columns()
duckdb_constraints()
duckdb_views()
duckdb_dependencies()
```

实际 catalog view 名称必须以目标 DuckDB fork 为准。

外部数据库只允许经过受控 adapter：

- source alias 来自 deployment configuration；
- schema/table allowlist；
- identifier 使用参数化 identifier composition；
- 不使用 JDBC；
- 不引入 DatabaseHub；
- 不接受模型提供 DSN；
- 不把外部数据库连接直接交给模型 SQL。

Flock 提供：

```text
flock_schema_list_tables()
flock_schema_show_create(relation_name)
flock_schema_extract_snapshot(options)
flock_schema_ingest_snapshot(snapshot_json)
```

`flock_schema_extract_snapshot()` 只针对当前受控 DuckDB connection；外部 adapter 将规范化结果交给 `flock_schema_ingest_snapshot()`。

### `schemaContext.md` / `kpiContext.md` / `activeContext.md`

| Context | owner | 生命周期 |
|---|---|---|
| `schemaContext.md` | v7 schema provider 生成；Flock 提供 catalog 数据 | snapshot generation |
| `kpiContext.md` | operator/application 配置 | deployment |
| `activeContext.md` | pg-agent Python conversation/session | conversation/run |

更新流程：

```text
schema snapshot 成功
  → Flock catalog/index READY
  → Python 生成新的 schemaContext
  → 原子替换 context version
  → 后续 query 绑定 snapshot_id
```

不能在 snapshot 未完成时部分更新 `schemaContext.md`。`activeContext.md` 不写入永久 RAG tree，除非用户显式保存。

### Schema-first / text-first / hybrid 路由

`use_rag_tool` 和 Python facade 支持：

```text
auto
schema_first
text_first
hybrid
```

路由规则：

1. 显式 mode 优先；
2. `schema_first`：
   - 用户要求表、列、字段、join、KPI、SQL、数据关系；
   - 先查 schema catalog，再决定是否调用 text RAG；
3. `text_first`：
   - 用户要求文档内容、说明、PDF、章节或自然语言知识；
   - 先查 text/PDF RAG；
4. `hybrid`：
   - 同时需要业务定义和实际表结构；
   - 分别查询两个物理 provider，再按 context budget 合并；
5. `auto`：
   - 由 Python deterministic classifier 先判定；
   - query expansion 可以补充 intent，但不能绕过权限。

不同 provider 的 candidate 必须保留 `provider_kind`，不能把 schema relation 当成普通 PDF chunk。

---

## 3.11 LongContextRAG parity

### Python 组件边界

建议新增：

```text
pg-agent/v7/long_context/
```

组件：

```text
query_extraction.py
document_retriever.py
relevance_filter.py
token_limiter.py
context_assembler.py
qa_strategy.py
streaming.py
compat.py
```

它们以 auto-coder 已核验模块为 parity source，但不复制其 DuckDB storage implementation。

### 端到端流程

```text
user/conversation query
  → query extraction
  → query expansion
  → route: schema/text/hybrid
  → Flock candidate recall
      BM25 + dense + multi-vector
  → candidate deduplication
  → Python LLM relevance filter
  → Flock score/rank/document reorder
  → Python TokenLimiter
  → context assembly
  → QA prompt
  → LLM request
  → streaming generator
```

### Query extraction / expansion

Python 实现必须保留 auto-coder 的外部行为：

- 原始 query；
- extracted sub-queries；
- expanded queries；
- query-to-candidate trace；
- timeout；
- cancellation；
- expansion failure fallback。

扩展失败时：

- 记录 `RAG_QUERY_EXPANSION_FAILED`；
- 使用原始 query 进行一次 bounded recall；
- 不无限重试；
- 如果原始 recall 也失败，返回中文可行动错误。

### Document recall

每个 expanded query 调用 Flock `flock_rag_search()`：

- 每 query 有独立 candidate cap；
- 全局 candidate cap；
- candidate 使用 `(deployment_id, document_id, revision, chunk_id)` 去重；
- query expansion 顺序不影响最终 tie-break；
- 不允许无上限 top_k；
- backend 选择由 route/options 决定；
- `multi_vector` unavailable 不静默 fallback。

### LLM relevance filter

Python 复现 auto-coder 的 filter 语义：

- bounded `ThreadPoolExecutor`；
- 并发数由 `RagConfig` 控制；
- 每个 candidate 使用独立 timeout；
- 只重试 transport/429/5xx；
- 不重试 auth、schema、invalid response；
- yes/no 和 score 的解析遵循 Phase 0 冻结的 auto-coder prompt/schema；
- filter 返回顺序按 candidate stable key 恢复，而不是 future 完成顺序；
- 单个 candidate 失败可按配置标记 rejected 或整体失败，默认使用 legacy behavior；
- 不能将 `llm_rerank` C++ aggregate function 作为替代。

### Score ordering / original-document reorder

流程固定为：

```text
retrieval candidates
  → LLM relevance score
  → Flock RagScoringEngine
  → document-level grouping
  → original-document order restoration
  → chunk/range output
```

Document order 的来源优先级：

1. MinerU canonical node/chunk ordinal；
2. source file/document ordinal；
3. stable `document_id` tie-break。

同一 document 的 context chunk 默认按原始顺序输出，不按 LLM 完成顺序输出。

### TokenLimiter

Python 保留 auto-coder 的 exact semantics，Phase 0 从以下模块和测试冻结默认参数：

```text
token_limiter.py
token_counter.py
token_checker.py
rag_config.py
```

必须支持：

- 小文件合并；
- 大文件按 token budget 切分；
- 1-based、闭区间 line ranges；
- 源文件内容和 range 的一致性；
- context budget 超限时的 deterministic truncation；
- 文档优先级与 chunk 优先级；
- 不把 0-based internal offset 暴露为 public range；
- token counter 失败时返回结构化错误，不静默使用字符数替代，除非 legacy contract 明确如此。

### Context assembly

每个 context item 至少带：

```text
source_id/document_id
file_path_or_document_label
section_path
page_start/page_end
line_start/line_end
content
retrieval_score
relevance_score?
```

文件路径和 document label 经过脱敏策略；不能把原始本地路径作为可执行工具输入。

### QA prompt

QA prompt 留在 Python：

- 使用 `qa_conversation_strategy.py` 的实际 prompt/role/format contract；
- 由 Python 注入 contexts、query、conversation history；
- Flock 不生成 prompt；
- Flock 不发送 LLM HTTP；
- 无 context 时必须明确告诉 QA 层“没有可用上下文”，不能伪造引用。

### `without_contexts`

精确定义：

```text
without_contexts=true
  → 不执行 text/schema candidate recall
  → 不执行 LLM relevance filter
  → 不执行 TokenLimiter context assembly
  → 仍可执行无上下文 QA generation
  → 返回 contexts=[]
```

如果旧 auto-coder contract 对 `without_contexts` 有不同语义，以 Phase 0 实际代码和测试为准，并由 compatibility facade 保持外部行为。

### Streaming

新增 Python internal event adapter，外部事件名继承 auto-coder `stream_event/` contract。

至少需要：

```text
query_started
query_expanded
retrieval_completed
contexts_ready
answer_delta
completed
failed
cancelled
```

如果旧 consumer 只支持 token/error/done，则由 `compat.py` 转换，不改变 Flock SQL output。

---

## 3.12 API contract

### Flock public SQL APIs

新增 API 为 additive，不修改现有 LLM 函数签名。

| API | 类型 | 用途 |
|---|---|---|
| `flock_rag_health()` | scalar/table function | 检查 catalog、engine、backend、manifest |
| `flock_rag_ingest_mineru(document_id, mineru_json, options)` | table function 或等价 extension function | JSON → revisioned tree/chunk |
| `flock_rag_search(query, options)` | table function | BM25/dense/multi/hybrid recall |
| `flock_rag_rank_candidates(candidates_json, options)` | table function | candidate scoring/order |
| `flock_schema_list_tables(options)` | table function | 受控 DuckDB catalog |
| `flock_schema_show_create(relation_name)` | scalar/table function | 安全 DDL/metadata |
| `flock_schema_extract_snapshot(options)` | table function | 读取当前 DuckDB catalog |
| `flock_schema_ingest_snapshot(snapshot_json, options)` | table function | 写入独立 schema RAG file |

所有 options 使用受控 JSON schema；未知 option 必须返回 `RAG_ARGUMENT_ERROR`，不能静默忽略关键安全参数。

### Python provider contract

建议新增 protocol：

```text
RagProvider.search(request) -> RagSearchResult
RagProvider.stream(request) -> Iterator[StreamEvent]
RagProvider.health() -> RagHealth
```

请求至少包含：

```text
query
route_mode
without_contexts
top_k
retrieval_mode
timeout_ms
conversation_id?
```

`deployment_id` 从 provider instance/config 绑定，不由模型作为自由字段传入。

### Compatibility facade

`pg-agent/v7/compat/` 提供：

```text
RAGManager.search() -> List[SourceCode]
LongContextRAG.stream() -> existing-compatible generator
```

适配：

- `SourceCode` 字段；
- source/range 命名；
- stream events；
- error class；
- `rag_config` 默认值；
- legacy `top_k=10000`、similarity `0.1`、dimension `1024` 的兼容行为。

如果新 Flock backend 无法保持 legacy 结果，必须在 compatibility facade 中显式报告版本差异，而不是静默改变排序。

### `use_rag_tool`

model-facing named tool 只允许访问 deployment-bound provider：

```text
use_rag_tool(
    query,
    mode,
    without_contexts,
    top_k,
    retrieval_mode,
    stream,
    timeout_ms
)
```

它不能接收：

- DSN；
- DuckDB file path；
- extension name；
- raw SQL；
- arbitrary table path；
- secret；
- `deployment_id` override。

`use_rag_tool` 的 deferred path 使用 v7 `rag_query_requests`；不能返回 v6 `duck_heavy_requests` envelope。

---

## 3.13 Error handling、timeout、retry 和 cancellation

### Error code

Flock 和 Python 使用统一前缀：

```text
RAG_ARGUMENT_ERROR
RAG_CONTRACT_ERROR
RAG_TREE_INVALID
RAG_DOCUMENT_NOT_FOUND
RAG_REVISION_NOT_READY
RAG_INDEX_BUILD_FAILED
RAG_BM25_UNAVAILABLE
RAG_DENSE_UNAVAILABLE
RAG_MULTI_VECTOR_UNAVAILABLE
RAG_VECTOR_DIMENSION_MISMATCH
RAG_SCHEMA_SOURCE_FORBIDDEN
RAG_SCHEMA_SNAPSHOT_FAILED
RAG_QUERY_TIMEOUT
RAG_LLM_TIMEOUT
RAG_CANCELLED
RAG_DEPLOYMENT_NOT_FOUND
RAG_OWNER_CONFLICT
RAG_STORAGE_MIGRATION_FAILED
RAG_STORAGE_CORRUPT
RAG_QUEUE_ERROR
```

Python 对外保持四段 envelope：

```text
{
  "success": false,
  "Type": "...",
  "Phase": "Resolution|Ingestion|Retrieval|Context|QA|Queue",
  "Problem": "...",
  "Solution": "..."
}
```

引擎错误必须：

- 长度截断；
- 脱敏 DSN、token、local secret、文件绝对路径；
- 保留 error class 和 phase；
- 不能只回传 DuckDB 原始 exception text。

### Retry

| 失败 | 默认行为 |
|---|---|
| JSON syntax/contract/tree invariant | 不重试 |
| DuckDB bind/type/schema error | 不重试 |
| source hash mismatch | 不重试 |
| owner lease conflict | 等待/重新 claim，一次 bounded retry |
| transient index backend unavailable | bounded retry |
| LLM 429/5xx | 使用 legacy retry policy |
| LLM auth/invalid response | 不重试 |
| query timeout | 取消当前 connection operation，不自动重复完整 query |
| worker crash | queue visibility timeout 后由新 owner 重放 operation |
| duplicate request | 返回已有 operation result，不重复写入 |

### Cancellation

Python 必须维护一个 request deadline 和 cancellation event：

```text
deadline = monotonic_now + timeout
cancel_event
```

取消路径：

1. 标记 Postgres operation `CANCEL_REQUESTED`；
2. 调用 Flock/DuckDB reader connection interrupt；
3. 取消 LLM futures；
4. 停止 streaming generator；
5. 不修改 active revision；
6. ingestion/index 的 partial generation 保持 `BUILDING/FAILED`，由 cleanup 回收；
7. 下次查询只能读取上一份 `READY` active generation。

---

## 3.14 Flock C++/SQL 与 pg-agent v7 Python 职责表

| 能力 | Flock C++/SQL | pg-agent v7 Python |
|---|---|---|
| DuckDB extension registration | 负责 | 不负责 |
| persistent text/schema catalog schema | 负责定义、创建、迁移 | 调用 health/migration boundary |
| deployment file path resolution | 不负责 | 负责，且由 operator allowlist 绑定 |
| deployment owner lease | 不负责 | 负责，使用 Postgres/OS lock |
| DuckDB connection pool/lifecycle | 提供 connection-safe APIs | 负责 connection 创建、关闭、reader/writer 角色 |
| MinerU JSON acquisition | 不负责 | 负责 MinerU process、artifact reference、hash、queue |
| MinerU JSON contract validation | canonical parser 负责 | source-level envelope validation |
| JSON → document/section/node/edge/page/table/image/metadata | 负责 | 不复制 parser |
| tree invariant checking | 负责 | 消费结构化错误 |
| canonical chunk/range | 负责 | 不重新定义 source range |
| BM25 index/query | 负责 | 选择 retrieval mode、传 options |
| mdenseon adapter | 负责稳定 dense boundary；实际实现位置由 gate 决定 | 负责模型配置和 fallback policy |
| `NEAREST` query generation | 负责 | 不拼接 NEAREST SQL |
| tachiom adapter | 负责稳定 multi-vector result boundary | 负责选择是否请求 multi-vector |
| candidate dedup | 可由 Flock 提供基础能力 | 负责跨 query expansion 的 orchestration |
| score normalization/fusion/ranking | 负责 | 传入 LLM relevance score |
| original-document reorder | 负责 canonical order 计算 | 保持结果顺序、转换 legacy object |
| Flock query metrics | 负责 retrieval/index metrics | 负责 LLM/filter/QA/stream metrics |
| query extraction/expansion | 不负责 | 负责 |
| LLM relevance filter | 不负责；Flock 禁止 LLM HTTP | 负责 |
| TokenLimiter | 不负责 final context budget | 负责 |
| small-file merge / large-file split | 不负责 query-time context policy | 负责，保留 legacy semantics |
| context assembly | 不负责 | 负责 |
| QA prompt | 不负责 | 负责 |
| conversation history | 不负责 | 负责 |
| streaming generator | 不负责 | 负责 |
| `without_contexts` orchestration | 不负责 | 负责 |
| retry/timeout/cancel policy | 提供 query interrupt boundary | 负责全局 deadline 和 LLM cancel |
| schema catalog extraction | 直接读取 DuckDB catalog | 负责外部 adapter、allowlist 和调用流程 |
| schema RAG index | 负责 catalog/index/ranking | 负责 route 和 context update |
| `schemaContext.md` | 提供 canonical catalog rows | 负责渲染和版本替换 |
| `kpiContext.md` | 不负责业务配置 | 负责 operator config |
| `activeContext.md` | 不负责 conversation state | 负责 ephemeral context |
| SQL tool dispatch | 不负责 | 负责 named tool / queue / apply |
| security boundary | extension function 做参数和 read/write 限制 | deployment auth、path/secret/queue policy |
| v6 temporary workbench | 不改 | v7 不调用 v6 session manager |

---

# 4. File-by-file impact

以下是计划中的目标文件。Phase 0 需要核对外部仓库实际路径；如果某个目标仓库当前使用不同的 source layout，只允许做路径映射，不改变上述组件边界。

## 4.1 pg-agent

### 不修改的 v6 文件

| 文件/目录 | 处理 |
|---|---|
| `v6/session_durability/duckdb_runtime.py` | 保持 v6 生命周期；v7 不导入 |
| `v6/source_ingress/duckdb_ingress.py` | 保持临时 snapshot 语义 |
| `v6/queue_bridge/duck_queue.sql` | 不添加永久 RAG queue |
| `v6/duck_tools/duck_tools.sql` | 不添加 RAG tool |
| `v6/load.py` | 保持 v6 stage/load 行为 |
| `v6/README.md` | 只在另有 v7 文档时不改；不得把 v7 描述混入 v6 |
| `v6/dialect_guardrails/duckdb_validation.py` | 不承担 v7 persistent RAG SQL policy |

### 新增 v7 loader 和 Postgres SQL

| 文件 | 变更 | 依赖 |
|---|---|---|
| `pg-agent/v7/load.py` | 新增 v7 累积 SQL load order；复用 v6 SQL path manifest，但不导入 v6 runtime | v7 SQL 文件 |
| `pg-agent/v7/rag_catalog/rag_metadata.sql` | 新增 `rag_deployments`、`rag_document_manifests`、`rag_operations`、schema/context metadata | v7 loader |
| `pg-agent/v7/rag_queue/rag_queue.sql` | 新建 RAG queue/DLQ、operation claim、idempotency、result handler | metadata SQL |
| `pg-agent/v7/rag_tools/rag_tools.sql` | 注册 `use_rag_tool` 及 operator-only ingestion/index enqueue contract | queue SQL、named-tool taxonomy |
| `pg-agent/v7/rag_prompt/rag_prompt.sql` | 新增 schema/text/hybrid route instructions、DuckDB/Flock tool contract | rag tools、provider output |

v7 loader 必须：

- 明确列出 v6 inherited SQL 与 v7 appended SQL；
- 对新增 COMMENT plugin 文件执行 refresh；
- 不修改 v6 `STAGE_THROUGH`；
- 每个 v7 stage 使用独立 `agent_v7_*` database；
- `ON_ERROR_STOP=1`；
- 不把 `rag_*` tables 和 `duck_*` tables 混为同一 operation schema。

### 新增 deployment runtime

| 文件 | 变更 |
|---|---|
| `pg-agent/v7/rag_runtime/deployment_store.py` | `DeploymentRagStore`、持久 text/schema file open、reader/writer connection、manifest check |
| `pg-agent/v7/rag_runtime/owner_lease.py` | Postgres lease、generation fencing、OS file lock |
| `pg-agent/v7/rag_runtime/operation_store.py` | RAG operation claim、idempotency、status、retry/DLQ metadata |
| `pg-agent/v7/rag_runtime/errors.py` | `RAG_*` error taxonomy、脱敏和中文 envelope |
| `pg-agent/v7/rag_runtime/worker.py` | v7 RAG queue consumer；不得实例化 `DuckSessionManager` |
| `pg-agent/v7/rag_runtime/cleanup.py` | failed generation、stale lease、temporary staging 清理 |
| `pg-agent/v7/rag_runtime/manifest.py` | 四仓版本、Flock ABI、catalog/index manifest 校验 |

### MinerU ingress

| 文件 | 变更 |
|---|---|
| `pg-agent/v7/mineru/contracts.py` | Phase 0 冻结的 MinerU/Kohaku canonical contract、version/hash |
| `pg-agent/v7/mineru/source_adapter.py` | MinerU JSON 获取、source reference、content hash、脱敏 |
| `pg-agent/v7/mineru/ingest_scheduler.py` | 创建 `rag_ingest_requests`，不把 raw JSON 放入 queue |
| `pg-agent/v7/mineru/replay.py` | 根据 source reference 重放 ingestion；不重放 v6 artifacts |

### Provider 和 schema RAG

| 文件 | 变更 |
|---|---|
| `pg-agent/v7/provider/contracts.py` | `RagProvider`、search request/result、stream event、health contract |
| `pg-agent/v7/provider/flock_provider.py` | 通过 Flock SQL/table functions 调用 text/schema backend |
| `pg-agent/v7/provider/router.py` | `auto/schema_first/text_first/hybrid` route |
| `pg-agent/v7/schema_rag/catalog_adapter.py` | 直接读取受控 DuckDB catalog；外部 DB 只通过 allowlisted adapter |
| `pg-agent/v7/schema_rag/schema_provider.py` | schema list/show-create/register/context retrieval |
| `pg-agent/v7/schema_rag/context_builder.py` | `schemaContext.md`、`kpiContext.md`、`activeContext.md` versioning |
| `pg-agent/v7/schema_rag/redaction.py` | sample/profile/comment 脱敏 |
| `pg-agent/v7/schema_rag/sql_workflow.py` | `list_tables → show_create → register_table → execute SQL` 的 tool choreography |

### LongContextRAG

| 文件 | 变更 |
|---|---|
| `pg-agent/v7/long_context/query_extraction.py` | query extraction/expansion |
| `pg-agent/v7/long_context/document_retriever.py` | 调 Flock recall、跨 expanded query 去重 |
| `pg-agent/v7/long_context/relevance_filter.py` | bounded LLM yes/no/score filter、legacy timeout/retry |
| `pg-agent/v7/long_context/token_limiter.py` | legacy 小文件合并、大文件切分、1-based ranges |
| `pg-agent/v7/long_context/context_assembler.py` | candidate → bounded contexts |
| `pg-agent/v7/long_context/qa_strategy.py` | QA prompt、conversation history、no-context behavior |
| `pg-agent/v7/long_context/streaming.py` | stream generator 和 event adapter |
| `pg-agent/v7/long_context/long_context_rag.py` | 端到端 pipeline |
| `pg-agent/v7/long_context/compat.py` | `RAGManager.search()` / `SourceCode` / legacy stream facade |
| `pg-agent/v7/long_context/config.py` | 从 auto-coder parity 冻结的配置和 budget |

### 测试

| 文件/目录 | 变更 |
|---|---|
| `pg-agent/v7/tests/test_manifest.py` | 四仓版本和 runtime 校验 |
| `pg-agent/v7/tests/test_deployment_lifecycle.py` | restart、owner lease、reader/writer |
| `pg-agent/v7/tests/test_mineru_tree.py` | 真实 MinerU/Kohaku fixtures、树不变量 |
| `pg-agent/v7/tests/test_retrieval_contract.py` | Flock output contract、BM25/dense/multi |
| `pg-agent/v7/tests/test_long_context_parity.py` | auto-coder golden parity |
| `pg-agent/v7/tests/test_schema_rag.py` | schema snapshot、route、redaction |
| `pg-agent/v7/tests/test_queue_idempotency.py` | duplicate、retry、DLQ、cancel |
| `pg-agent/v7/tests/test_security.py` | DSN/path/SQL/secret/external access 攻击用例 |
| `pg-agent/v7/tests/benchmarks/` | quality/performance baseline |

### 依赖和 lock 文件

| 文件 | 变更 |
|---|---|
| `pg-agent/v7/constraints-macos-arm64.txt` | 记录 target-built DuckDB Python binding、mdenseon、tachiom 版本 |
| `pg-agent/v7/VERSION_MANIFEST.json` | 只读构建 manifest；不是运行时 user config |
| 根 `pyproject.toml` | 仅在需要新增 v7 optional extra 时修改；不得改变 v6 的 `duckdb==1.6.0.dev365` 约束 |
| `pg-agent/v7/README.md` | v7 lifecycle、API、queue、migration、unsupported scope |

---

## 4.2 Flock

### 新增 RAG headers

建议目录：

```text
src/include/flock/rag/
```

| 文件 | 变更 |
|---|---|
| `catalog.hpp` | `RagCatalog`、schema version、active revision、migration contract |
| `mineru_tree.hpp` | canonical JSON parser、tree node/edge/page/table/image types、invariant validation |
| `chunker.hpp` | node → canonical chunk/range |
| `embedding_backend.hpp` | `IDenseEmbeddingBackend` stable boundary |
| `multi_vector_backend.hpp` | `IMultiVectorIndex` stable boundary；tachiom adapter contract |
| `search.hpp` | `flock_rag_search` bind/output/request types |
| `scoring.hpp` | `RagCandidate`、`RagScoringEngine`、tie-break/document reorder |
| `schema_catalog.hpp` | DuckDB catalog extraction/normalized schema snapshot |
| `metrics.hpp` | explicit `RagInvocationContext` 和 RAG metrics |
| `rag_functions.hpp` | table/scalar function declarations 和 registration entry points |

### 新增 RAG implementations

建议目录：

```text
src/rag/
```

| 文件 | 变更 |
|---|---|
| `catalog.cpp` | persistent text/schema catalog initialization、migration、manifest |
| `mineru_tree.cpp` | MinerU canonical parser、revision insert、tree invariant |
| `chunker.cpp` | section/node/page-aware chunk creation |
| `embedding_backend.cpp` | mdenseon stable adapter；实际 backend 由 Phase 0/1 冻结 |
| `multi_vector_backend.cpp` | duckdb-tachiom adapter；未通过 gate 时返回明确 unavailable |
| `search.cpp` | BM25、dense `NEAREST`、multi-vector、hybrid result |
| `scoring.cpp` | score normalization、fusion、dedup、document reorder |
| `schema_catalog.cpp` | `information_schema` / `duckdb_*` extraction |
| `metrics.cpp` | RAG metrics aggregation/persistence |
| `functions.cpp` | Flock SQL/table function bind/init/execute |
| `migration.cpp` | catalog schema/index manifest migrations |

### Registry/CMake 修改

| 文件 | 变更 | 依赖 |
|---|---|---|
| `src/include/flock/registry/rag.hpp` | 新增 `RagRegistry` | RAG functions |
| `src/registry/rag.cpp` | 注册 RAG/schema functions | RAG implementations |
| `src/include/flock/registry/registry.hpp` | 增加 RAG registry entry point | `rag.hpp` |
| `src/registry/registry.cpp` | `Registry::Register()` 中添加 RAG registry | `rag.cpp` |
| `src/CMakeLists.txt` | 将新 RAG source 加入 extension target；实际 source list 以仓库当前文件为准 | all Flock RAG sources |
| 根 `CMakeLists.txt` | 添加 v7 target/profile、target DuckDB source validation、可选 tachiom/mdenseon build flags | target fork |
| `.github/workflows/MainRagDistributionPipeline.yml` | 新增 v7 target-fork build/test workflow；不替换当前 v1.5.4 distribution workflow | four-repo manifest |
| `src/flock_extension.cpp` | 只有在 registry 或 extension load 需要显式 RAG initialization 时才修改；默认不把 deployment path 写入 extension global state | catalog initialization |

### 明确不修改或不复用的 Flock 文件

| 文件 | 原因 |
|---|---|
| `src/include/flock/core/config.hpp` | `Config` 是 global model/prompt storage，不是 deployment RAG store |
| `src/core/config/config.cpp` | 不把 RAG 文件放进 `flock_storage` |
| `src/include/flock/model_manager/model.hpp` | mdenseon 不强行接入 completion provider |
| `src/model_manager/model.cpp` | 保持现有 LLM model resolution |
| `src/include/flock/functions/aggregate/llm_rerank.hpp` | 不改变现有 aggregate contract |
| `src/functions/aggregate/llm_rerank/implementation.cpp` | 不拿现有 LLM rerank 冒充 RAG ranking |
| `src/include/flock/metrics/manager.hpp` | 现有 metrics 继续服务旧 LLM functions |
| `src/metrics/metrics.cpp` | RAG 使用新的显式 context metrics |
| `src/custom_parser/query_parser.cpp` | RAG 不需要扩展现有 `CREATE/UPDATE/GET MODEL/PROMPT` parser |
| `src/include/flock/custom_parser/query_statements.hpp` | 不把 RAG ingestion 伪装成现有 custom SQL |
| `src/include/flock/secret_manager/secret_manager.hpp` | MinerU/RAG deployment credentials 不进入 Flock model secret manager |

### 文档

建议新增：

```text
docs/rag/architecture.mdx
docs/rag/mineru-tree.mdx
docs/rag/retrieval.mdx
docs/rag/schema-rag.mdx
docs/rag/long-context.mdx
```

现有 `docs/hybrid-search.mdx` 只在需要说明新的 RAG scoring 和现有 fusion 区别时追加链接，不重写现有 fusion 语义。

---

## 4.3 duckdb-pgagent

目标 fork 当前已经包含 NEAREST 和 grammar extension 相关能力，因此 v7 默认不修改其生产源代码。

| 文件/目录 | 处理 |
|---|---|
| 已有 `NEAREST` grammar/transformer files | Phase 1 只复测；除非 target regression，默认不改 |
| existing NEAREST SQL tests | 以 target commit 为基线执行并保存结果 |
| `src/parser/peg/grammar/statements/load.gram` | 不修改；它与 NEAREST 无关 |
| `src/main/extension/extension_repository_manager.cpp` | 不修改；v7 不使用 runtime extension installation |
| `src/function/table/system/duckdb_extension_repositories.cpp` | 不修改 |
| `src/include/duckdb/main/extension_helper.hpp` | 不修改；不通过 `INSTALL/LOAD` 装 RAG backend |
| `src/include/duckdb/parser/parsed_data/load_info.hpp` | 不修改 |

如果目标 fork 的 NEAREST test 在实际 v7 build 中失败，必须在该 fork 内以“production parser/transformer 修复 + regression test”原子提交；不能在 Flock 或 Python 层通过字符串改写掩盖 engine bug。

---

## 4.4 duckdb-python-pgagent

实际路径必须在 Phase 0 读取；以下是已知构建入口的目标影响。

| 文件 | 变更 |
|---|---|
| `CMakeLists.txt` | 增加目标 DuckDB source/commit 校验；将 Flock static target、tachiom target 以及 Phase 0 冻结的 FTS/vector targets 接入 Python binding |
| `cmake/duckdb_loader.cmake` | 增加 `FLOCK_SOURCE_PATH`、`TACHIOM_SOURCE_PATH` 等明确 source override；禁止默认使用 floating source |
| generated extension loader source | 由构建生成，不手工编辑；验证 Flock/tachiom 被 `WHOLE_ARCHIVE` 保留 |
| `pyproject.toml` 或 build metadata | 锁定 CPython/平台/build artifact；不能让 v7 安装回 PyPI stock DuckDB |
| `test/` 或现有 Python test directory | 新增静态 Flock load、RAG function、NEAREST、FTS/tachiom smoke tests |
| `v7` build profile | 构建一个与 v6 wheel 分离的 target runtime |

构建完成后必须验证：

```text
import duckdb
SELECT version()
SELECT flock_rag_health()
SELECT ... NEAREST ...
SELECT ... flock_rag_search(...)
```

如果 Flock/tachiom 只能作为 loadable extension 而不能静态链接，必须在 Phase 1 重新评估；默认不接受 runtime 网络安装或模型可控的 `LOAD path`。

---

# 5. Risks and migration

## 5.1 API 和模型 shape 未知

### 风险

- mdenseon 可能不是当前猜测的 vector API；
- tachiom 可能使用不同的 table/index shape；
- MinerU JSON 版本可能有不同的 page/block hierarchy；
- KohakuRAG 可能有额外的 node identity/range 语义。

### 处理

Phase 0 将所有未知项列为 E0，读取真实源码、fixture 和运行脚本后升级为 E1/E2。任何 required contract 未冻结，相关 phase 不得通过。不得为了提前实现而引入猜测版接口。

---

## 5.2 DuckDB 2.0 alpha/file compatibility

目标 engine 是指定 fork/commit，不是 v6 的 `1.6.0.dev365` wheel，也不是等待未来 GA。

风险：

- DuckDB persistent file format 与旧 binary 不兼容；
- `APPROX` 可能没有 approximate implementation；
- FTS/VSS/tachiom target 在 Python build 中的 static link 不完整；
- `NEAREST` parser 在目标 fork 与上游测试有差异。

处理：

- v7 runtime 只允许 manifest 中的 exact engine；
- 每次 catalog migration 之前停止 writer 并制作 deployment file backup；
- 不允许旧 binary 直接打开未知新 file；
- rollback 采用“停 owner → 恢复 backup → 启旧 runtime”，不做原地 downgrade；
- `APPROX` 的性能声明必须由 benchmark 证明。

---

## 5.3 MinerU tree 数据丢失

风险：

- unknown block 被丢弃；
- section hierarchy 断裂；
- page 从 0-based 错转 1-based；
- table/image 只保留文本，丢失结构；
- source revision 更新覆盖旧 active 数据。

处理：

- raw MinerU JSON 存在 DuckDB revision；
- unknown node 保留 `raw_json`；
- 所有 tree invariants 在 transaction 内验证；
- 新 revision 只有在全部 index READY 后才 active；
- active pointer swap 前旧 revision 不动；
- 真实 fixtures 做 round-trip 和 count/hash 校验。

---

## 5.4 v6/v7 生命周期混淆

风险：

- v7 worker 误调用 `DuckSessionManager`；
- deployment RAG 数据误写进 `duck_artifacts`；
- v7 query 误发到 `duck_heavy_requests`；
- run restart 时把 deployment file 当成 run temporary state；
- v6 temp data 被错误宣传为可迁移。

处理：

- v7 package 对 v6 session modules 做 architecture test；
- grep/import guard 禁止 v7 runtime 导入 `v6.session_durability.duckdb_runtime`；
- queue names、metadata tables、API names 全部独立；
- integration test 同时创建一个 v6 run 和一个 v7 deployment，验证两者 catalog 完全不可见。

---

## 5.5 schema RAG 数据泄露

风险：

- sample/profile 暴露敏感值；
- schema comments 中包含 secret；
- external adapter 接受 arbitrary DSN；
- `show_create` 返回包含 credential 的 SQL；
- schema RAG 与 text RAG 混合后把内部表结构送给不应看到的 conversation。

处理：

- deployment allowlist 和 role policy；
- schema snapshot 默认不写 raw sample；
- comment、default expression、URI、secret pattern 脱敏；
- schema provider 返回 `snapshot_id` 和 access policy；
- `schemaContext.md` 更新前通过 redaction；
- model 不可提交 deployment/path/DSN；
- 所有 schema actions 记录 audit metadata。

---

## 5.6 LLM relevance 和 streaming 非确定性

风险：

- ThreadPoolExecutor 完成顺序导致结果不稳定；
- relevance filter timeout 后候选次序变化；
- stream 被取消后 QA 状态不一致；
- token budget 截断与 legacy 行号不一致。

处理：

- futures 结果按 stable candidate key 重排；
- ranking 在 Flock deterministic；
- TokenLimiter 使用 golden line-range tests；
- 所有 request 使用单一 monotonic deadline；
- cancel 后只保留 bounded status，不写半成品 context；
- 外部 compatibility facade 不改变旧 stream event shape。

---

## 5.7 迁移策略

### v6 → v7

默认**不迁移**：

- v6 `duck_artifacts` 是临时 run artifact；
- v6 snapshot rows 没有 permanent document revision；
- v6 `duck_workbench_sessions` 不具备 deployment identity；
- v6 `duck_heavy_requests` 不具备 RAG generation semantics。

如果需要把 source 变为永久 RAG 数据，必须重新走：

```text
source/PDF
  → MinerU
  → canonical JSON
  → v7 rag_ingest
```

### auto-coder legacy DuckDB cache

提供显式、一次性的 read-only importer：

```text
.cache/byzerai_store_duckdb.db
  → legacy importer
  → rag_document / rag_document_revision
  → rag_node / rag_chunk
  → dense vector manifest
```

规则：

- 不修改旧 `.db`；
- `_id` 映射为稳定 `document_id`；
- `file_path` 经过脱敏/allowlist；
- `content`/`raw_content` 进入 document/chunk；
- `vector FLOAT[]` 只有 dimension 与 manifest 匹配才导入；
- 旧 cache 没有 MinerU tree 时，导入为 `legacy_flat` document；
- 不伪造 section/page/table/image；
- `enable_hybrid_index=false` 的旧行为保留在 compatibility facade；
- importer 失败不影响 v7 deployment active data。

### v7 catalog migration

使用 DuckDB 内部的 `flock_rag_schema_meta`/manifest 表记录：

```text
catalog_version
migration_id
migration_checksum
index_format_version
```

迁移规则：

1. writer exclusive；
2. backup；
3. additive schema migration；
4. data validation；
5. index rebuild；
6. manifest swap；
7. 失败则 rollback transaction 或恢复 backup；
8. reader 只能看到旧或新完整 generation，不能看到中间状态。

---

# 6. Acceptance、quality 和 performance baseline

## 6.1 功能验收

### Flock C++/SQL

必须通过：

- MinerU JSON canonical parser；
- document/section/node/edge/page/table/image/metadata 全部可落库；
- unknown node 保留 raw JSON；
- parent/edge 无非法环；
- revision active swap；
- duplicate ingestion idempotency；
- failed ingestion 不破坏旧 active revision；
- BM25 result contract；
- dense result contract；
- target `NEAREST` exact/approx syntax；
- vector dimension mismatch；
- multi-vector tachiom adapter；
- deterministic scoring/ranking；
- schema catalog snapshot；
- schema show-create/list-tables；
- RAG metrics。

### pg-agent v7

必须通过：

- deployment file creation/reopen；
- worker restart 后数据仍可检索；
- owner lease fencing；
- reader/writer 并发；
- ingestion/index/query queue；
- duplicate and replay；
- timeout/retry/cancel；
- `use_rag_tool` 权限边界；
- text-first/schema-first/hybrid route；
- schemaContext atomic update；
- LongContextRAG parity；
- `without_contexts`；
- stream generator；
- 中文错误兜底。

### 生命周期隔离

必须验证：

```text
v6 run A cannot see v7 deployment data
v7 deployment cannot see v6 DuckSession
v7 deployment A cannot see deployment B
text index cannot answer from schema index without explicit hybrid route
```

---

## 6.2 Quality baseline

Phase 0 先生成 golden baseline，至少使用：

- auto-coder legacy DuckDB fixture；
- `p16_mdenseon.py` 与 `fixtures/p16-mdenseon.json`；
- `p19_mineru_process.py` 生成或引用的 MinerU fixtures；
- KohakuRAG 真实样例；
- schema fixture：table、view、primary key、foreign key、comment、sample/profile；
- 小文档、大文档、多页 PDF、table/image 混合文档。

验收指标：

| 指标 | 目标 |
|---|---|
| tree round-trip | canonical 可重建，节点/page/table/image/hash 无非预期丢失 |
| tree invariants | 100% 通过 |
| legacy simple retrieval top-1 | golden fixture 100% 一致，或差异必须有解释和版本记录 |
| vector dimension | 100% 与 manifest 匹配 |
| BM25 golden ranking | top-k 顺序满足冻结 expected result |
| original-document reorder | 同一 document 内 range 顺序 100% 稳定 |
| line range | 100% 为 1-based、闭区间、可回到原文 |
| schema redaction | secrets/sample policy 测试 0 泄露 |
| duplicate ingestion | 不产生重复 active revision |
| cancelled operation | 不产生 active partial generation |
| stream compatibility | 旧 consumer 能正确收到 done/error/token events |
| 中文 error fallback | 所有公开错误都有 Problem + Solution |

---

## 6.3 Performance baseline

所有 baseline 在锁定的 macOS arm64、CPython 3.12、目标 DuckDB commit、固定 CPU/thread 配置下运行。

必须测量：

- legacy flat cache import；
- MinerU tree ingestion；
- chunk generation；
- BM25 index build；
- dense embedding throughput；
- `EXACT NEAREST` latency；
- `APPROX NEAREST` latency；
- tachiom multi-vector build/search；
- hybrid fusion；
- schema snapshot；
- LongContext candidate filter；
- first-token latency；
- total QA latency；
- memory peak；
- persistent file size；
- restart/open/migration time。

建议门槛：

- 新实现相对 Phase 0 baseline 的简单检索 p95 不超过 `1.25x`；
- 目标 fixture 上 top-1 parity 必须保持；
- multi-vector 不得在未启用时增加明显的 dense-only path；
- ingestion/index 的 memory peak 不超过 baseline `1.5x`；
- 所有 query 和 filter 都受 timeout/candidate/context budget 约束；
- `APPROX` 只有在 target fork 实测优于 EXACT 且质量门通过后才能作为默认优化；
- 若无法给出稳定绝对吞吐，使用同机同数据的相对 baseline，不以未测机器上的绝对数字宣称 SLO。

---

# 7. 首期明确不做

v7 首期不包括：

- 修改 pgembed；
- PostgreSQL 内嵌 `pg_duckdb`；
- 把永久 RAG 放入 v6 DuckSession；
- 把 v6 `duck_artifacts` 转成永久 catalog；
- live PostgreSQL catalog 作为模型-facing DuckDB SQL；
- 任意 `ATTACH`、`CONNECT`、`INSTALL`、`LOAD`；
- 模型直接提交任意 DuckDB SQL；
- runtime 网络下载 Flock、tachiom、FTS 或其它 extension；
- 任意用户提供 DSN、文件 path 或 secret；
- 自动把 v6 temporary source 升级成 permanent document；
- 完整 Spark/Byzer/InfiniSQL SQL translation；
- ET/ML、visualization、shell、quack server；
- 自动多 worker memory-session affinity；
- 跨 DuckDB/PostgreSQL 的分布式原子提交；
- 多租户 RLS 完整方案；首期只支持单一可信 deployment owner model；
- MinerU 未冻结的新 JSON 版本兼容；
- tachiom API 未通过 gate 时的假实现；
- mdenseon shape 未冻结时的截断、padding、reshape；
- “APPROX 一定快于 EXACT”的产品承诺；
- `llm_rerank` 改造成 RAG ranking function。

---

# 8. Implementation order

## Phase 0 — Evidence audit and contract freeze

### 入口

- v3 计划、design review、v6 investigation notes 可读取；
- 四仓工作树路径可访问；
- 当前 target DuckDB fork commit 已知；
- auto-coder/Kohaku/tachiom/mdenseon 路径已定位。

### 工作

1. 读取并标记 `flock-rag-on-duckdb-final-plan-v3.md` 为 superseded；
2. 读取 design review，建立“review correction → v4 design decision”清单；
3. 盘点四仓当前 commit、branch、dirty 状态；
4. 读取 MinerU/KohakuRAG 真实 JSON、parser、fixtures；
5. 读取 `p16_mdenseon.py`、fixture、mdenseon package/native entry；
6. 读取 duckdb-tachiom/tachiom source、CMake、tests、model/vector shape；
7. 读取 auto-coder LongContextRAG 全部关键模块和配置默认值；
8. 读取 Infinisynapse schema/RAG evidence；
9. 在 target fork 上验证 NEAREST grammar/transformer/tests；
10. 冻结 canonical MinerU schema mapping、mdenseon adapter shape、tachiom adapter shape、stream event compatibility；
11. 生成四仓 version manifest 和 unknown/gate register。

### 出口

- 所有 P2/P3/P5 required unknown 从 E0 提升到 E1；
- mdenseon 和 tachiom 有真实 API shape；
- MinerU canonical mapping 有真实 fixture；
- target NEAREST test 通过；
- 明确 duckdb-python static build target；
- 没有通过 Phase 0 的 backend 不进入下一阶段实现。

---

## Phase 1 — Target DuckDB/Flock Python runtime build

### 入口

- Phase 0 manifest 已冻结；
- target fork clean 且为 `a1f0ab1911`；
- Flock/tachiom/mdenseon build strategy 已确定。

### 工作

1. 让 Flock 使用目标 DuckDB fork，而不是当前 floating submodule；
2. 将 Flock extension 接入 `duckdb-python-pgagent`；
3. 将 Phase 0 确认的 FTS/vector/tachiom targets 接入 static/generated loader；
4. 验证 `WHOLE_ARCHIVE` 不丢 Flock/tachiom symbols；
5. 增加 Flock health smoke function；
6. 在 Python binding 中运行 target `NEAREST` tests；
7. 验证 external access hardening 后不会发生 runtime install/load；
8. 固化 wheel/build artifact 的 engine version、ABI、extension manifest。

### 出口

- 一个可重建的 v7 Python runtime；
- `SELECT flock_rag_health()` 能执行；
- `NEAREST` exact/approx 查询能在目标 binding 执行；
- Flock/tachiom/FTS backend 能被静态或受控加载；
- 与 v6 `duckdb==1.6.0.dev365` 环境完全分离。

> **必须原子落地：** Flock build integration、duckdb-python loader、target runtime manifest 和 smoke tests 必须一起通过；不能先发布只有部分 extension 的 Python binding。

---

## Phase 2 — Flock persistent catalog and MinerU tree ingestion

### 入口

- Phase 1 runtime 可运行；
- MinerU canonical contract 已冻结。

### 工作

1. 实现 text/schema catalog schema versioning；
2. 实现 document/revision/tree tables；
3. 实现 MinerU JSON parser；
4. 实现 tree invariant validation；
5. 实现 canonical chunk/range；
6. 实现 raw JSON 保留；
7. 实现 ingestion function/table function；
8. 实现 revision generation、active swap、failed cleanup；
9. 对真实 MinerU/Kohaku fixtures 执行 round-trip；
10. 增加 schema migration tests。

### 出口

- 真实 MinerU JSON 可进入 DuckDB；
- document/section/node/edge/page/table/image/metadata 全部有可验证记录；
- chunk/range 可定位回原始文档；
- ingestion duplicate、failure、restart 通过；
- 旧 active revision 在新 revision 失败时保持可读。

> **必须原子落地：** catalog schema、parser、ingestion API、active revision swap 和 tree tests 必须一起落地。

---

## Phase 3 — BM25、dense、NEAREST、multi-vector 和 ranking

### 入口

- Phase 2 有 READY revision/chunk；
- mdenseon/tachiom contracts 已冻结。

### 工作

1. 实现 BM25 index/manifest；
2. 接入 mdenseon dense encoder；
3. 实现目标 fork 的 `NEAREST` query builder；
4. 验证 distance/similarity normalization；
5. 接入 tachiom multi-vector adapter；
6. 实现 `flock_rag_search`；
7. 实现 candidate dedup 和 multi-query merge；
8. 实现 `RagScoringEngine`；
9. 实现 original-document reorder；
10. 实现 RAG retrieval metrics；
11. 对 auto-coder fixture 建立 simple retrieval parity；
12. 对 `APPROX` 和 `EXACT` 建立独立 latency/quality baseline。

### 出口

- BM25/dense/multi-vector 各自可独立运行；
- hybrid search output contract 固定；
- score/rank deterministic；
- `llm_rerank` 未被调用；
- tachiom 未通过时明确返回 unavailable，而不是静默 fallback；
- quality/performance baseline 有记录。

---

## Phase 4 — Schema RAG 和统一 provider contract

### 入口

- Phase 1 runtime、Phase 3 Flock search contract 可用；
- DuckDB catalog API 已在目标 fork 验证。

### 工作

1. 建立独立 schema DuckDB file；
2. 实现 `schema_*` canonical tables；
3. 实现 `information_schema` / `duckdb_*` extraction；
4. 实现受控外部 DB adapter；
5. 实现 `list_tables`、`show_create`、`register_table` workflow；
6. 实现 schema index/ranking；
7. 实现 schema/text provider separation；
8. 实现 `schemaContext.md`、`kpiContext.md`、`activeContext.md` versioning；
9. 实现 `auto/schema_first/text_first/hybrid` route；
10. 加入 redaction、permission 和 snapshot consistency tests。

### 出口

- schema/text 物理 index 分离；
- schema snapshot 具有明确 snapshot ID 和 catalog hash；
- schema context 不在半成品 snapshot 上更新；
- schema-first 和 text-first 不互相泄露；
- RAG provider contract 固定。

---

## Phase 5 — LongContextRAG parity

### 入口

- Phase 3 retrieval output stable；
- Phase 4 provider route stable；
- auto-coder LongContextRAG golden behavior 已冻结。

### 工作

1. 实现 query extraction/expansion；
2. 实现 multi-query recall；
3. 实现 bounded LLM relevance filter；
4. 将 relevance score 传入 Flock ranking；
5. 实现 document reorder；
6. 实现 TokenLimiter；
7. 实现 context assembly；
8. 实现 QA strategy 和 prompt；
9. 实现 `without_contexts`；
10. 实现 timeout/retry/cancel；
11. 实现 stream event adapter；
12. 实现 `RAGManager.search()` 和 legacy `SourceCode` facade；
13. 运行 auto-coder parity suite。

### 出口

- 三阶段 LongContextRAG flow 可端到端运行；
- 小文件合并、大文件切分、1-based line range parity 通过；
- LLM filter completion order 不影响最终顺序；
- streaming、cancel、without_contexts 通过；
- 中文 error fallback 通过；
- facade 能被现有调用方按兼容形状使用。

---

## Phase 6 — v7 deployment runtime、queues 和 named RAG API

### 入口

- Phase 2–5 的 core/provider contracts stable；
- Postgres v7 metadata schema 已确定。

### 工作

1. 创建 `rag_deployments`、`rag_document_manifests`、`rag_operations`；
2. 创建独立 RAG queue family 和 DLQ；
3. 实现 deployment owner lease/generation fencing；
4. 实现 persistent text/schema file open/reopen；
5. 实现 ingestion/index/query operation handlers；
6. 实现 duplicate/replay/order/claim；
7. 实现 v7 `use_rag_tool`；
8. 实现 operator-only document ingest scheduler；
9. 实现 result application 和 run resume boundary；
10. 集成 Python `LongContextRAG` 与 deployment store；
11. 加入 deployment A/B、worker restart、old owner fencing tests；
12. 验证 v7 runtime 不导入和不调用 v6 session components。

### 出口

- deployment restart 后数据仍存在；
- active generation 查询不中断；
- stale owner 不能提交；
- queue duplicate 不重复 ingestion；
- v7 queue 与 `duck_heavy_requests` 完全分离；
- named tool 不暴露 DSN/path/secret/arbitrary SQL；
- v6 和 v7 同时运行时状态隔离。

> **必须原子落地：** Postgres metadata、RAG queue、owner lease、worker handler、`use_rag_tool` 必须一起落地；否则 queue 中的 operation 会进入无法恢复的状态。

---

## Phase 7 — Migration、benchmark、security 和 release gate

### 入口

- Phase 6 完成；
- 所有 component tests 已通过；
- 四仓 manifest clean。

### 工作

1. 执行 auto-coder legacy cache opt-in importer；
2. 执行 catalog schema migration/backup/restore；
3. 运行真实 MinerU corpus；
4. 运行 BM25/dense/multi/hybrid quality benchmark；
5. 运行 LongContextRAG answer/stream baseline；
6. 运行 schema RAG redaction/security suite；
7. 运行 owner failover、queue DLQ、cancel、timeout；
8. 运行 memory/file-size/latency benchmark；
9. 从 clean checkout 重建四仓；
10. 验证 v6 原有测试和 Flock existing LLM/fusion tests 无回归；
11. 生成 release manifest、known limitations 和 rollback runbook。

### 出口

只有以下全部成立，才可以将 v7 RAG 标记为 release-ready：

- E3 end-to-end gate 通过；
- Flock C++/SQL、pg-agent Python、DuckDB target、duckdb-python target 版本完全匹配；
- v6 全部回归通过；
- 真实 MinerU fixtures 和 legacy compatibility parity 通过；
- persistence/restart/rollback 通过；
- security suite 无高优先级泄露；
- performance baseline 在门槛内；
- `v6`、`v7` 生命周期和 queue boundary 被测试证明；
- 文档明确列出首期不做项和 tachiom/mdenseon 的实际支持 shape。