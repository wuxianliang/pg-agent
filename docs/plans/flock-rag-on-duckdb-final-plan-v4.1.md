# Oracle Plan



# Flock RAG on DuckDB：v4.1 最终权威开发计划

> **权威状态**
>
> - `/Users/wxl/Projects/pg-agent/docs/plans/flock-rag-on-duckdb-final-plan-v3.md`：**superseded**。
> - `/Users/wxl/Projects/pg-agent/docs/plans/flock-rag-on-duckdb-v7-final-plan-v4.md`（Oracle v4 draft）：**superseded**。
> - 本输出：**Oracle v4.1 最终权威计划**，是后续实现、评审和验收的唯一计划依据。
> - 本计划继承 v3/v4 的证据分级、design review 纠正和四仓版本约束。纠正项**并非全部吸收**。证据分级正式定义：E0 未读取/未知/缺失，不得作为实现依据；E1 已检查源码、测试或静态契约；E2 已在本 freeze 的目标 runtime/fixture 上运行（command + exit）。**E3定义为在冻结的四仓pin上完成跨仓库集成/验收**（四仓：pg-agent、flock、duckdb-pgagent、duckdb-python-pgagent）。当前 Phase 0 不是 E3。
> - Oracle v4 计划审查（不改 review 正文）：`/Users/wxl/Projects/pg-agent/docs/reviews/oracle-v4-plan-review-2026-08-29.md`。
> - 独立设计审查（不改 review 正文）：`/Users/wxl/Projects/pg-agent/docs/reviews/flock-rag-on-duckdb-plan-review-2026-08-29.md`。
> - Open-item 权威清单（ABSORBED / PARTIAL / UNRESOLVED）：`/Users/wxl/Projects/pg-agent/docs/plans/flock-rag-v4.1-review-correction-traceability.md`。机器可核对副本：`/Users/wxl/Projects/pg-agent/v7/evidence/corrections_register.json`。UNRESOLVED / PARTIAL 不得当作已吸收，不得据此进入 Phase 1。
> - 本计划只定义实施方案，不修改代码。

# 1. Summary

pg-agent v7 将在 v6 之上新增一套与临时数据工作台完全隔离的、deployment-scoped 持久 Flock RAG 平台。首期固定采用**单一 owner 进程独占打开 deployment live DuckDB 文件**的运行模式：同进程 writer connection 串行执行 ingestion/index/GC，同进程 query-only reader connections 执行直接查询和 `rag_query_requests`；其他进程只能通过私有 owner service IPC 调用，不能直接打开 live 文件。Flock C++/SQL 负责 MinerU JSON 树形 catalog、规范化文本投影、chunk/range、BM25、mdenseon dense、DuckDB `NEAREST`、tachiom multi-vector、候选分数与原文顺序；pg-agent v7 Python 负责 deployment/owner/queue/secret 生命周期、LongContextRAG、LLM relevance filter、TokenLimiter、QA 和 streaming。Streaming 与 deferred queue 明确互斥；内部事实表不重复保存 `deployment_id`，文件通过唯一 store identity 绑定 deployment，对外结果再注入 identity。Legacy cache 的只读探测器前移到 Phase 0，正式 canonical importer 在 Phase 2 完成；Phase 7 只执行生产迁移和 cutover。

# 2. Current-state analysis

## 2.1 当前责任与控制流

### v6 临时 DuckDB 工作台

当前 v6 数据流为：

```text
wb_duck_* named tool
  → PostgreSQL scheduler
  → duck_operations / duck_workbench_sessions
  → pgmq: duck_heavy_requests
  → DuckDBWorkerProcessor
  → DuckSessionManager.get_or_open(run_id)
  → :memory: DuckSession
  → snapshot / TEMP VIEW / query
  → apply_queue_result()
```

其生命周期和持久 RAG 不兼容：

| 维度 | v6 当前语义 |
|---|---|
| Identity | `run_id` |
| Connection | `DuckSessionManager` 管理的 `:memory:` connection |
| 文件 | 无持久文件 |
| 状态 | `duck_workbench_sessions`、`duck_artifacts`、`duck_operations` |
| Queue | `duck_heavy_requests` |
| Owner | 当前临时 worker |
| 重启 | `temp` session 丢失；`run_schema` 仅重放 source/view definition |
| 数据用途 | run 内临时分析，不是永久文档或索引 |

v7 不得调用或扩展以下组件来存放永久 RAG：

```text
DuckSessionManager
DuckSession
duck_workbench_sessions
duck_artifacts
duck_operations
duck_heavy_requests
wb_duck_register/query/brief_query
```

### 当前 Flock

Flock 当前由 `Registry` 注册 LLM scalar/aggregate functions，并使用 `Config`、`Model/IProvider`、`MetricsManager` 等全局或 invocation-scoped 组件。它已有 completion、embedding、fusion 和 `llm_rerank`，但没有：

- deployment-scoped persistent catalog；
- MinerU tree parser；
- document/section/node/edge/page/table/image/metadata；
- canonical text projection 和 range provenance；
- BM25/dense/multi-vector RAG engine；
- schema RAG catalog；
- LongContextRAG；
- 可复用的无 LLM 副作用 scoring/ranking engine。

现有 `llm_rerank` 会调用 LLM 并按模型返回 ID 排序，不能替代 auto-coder 的 relevance filter、score ordering 或 original-document reorder。现有 `Config::db` 和 `flock_storage` 也不能作为 deployment 文件 owner。

### auto-coder.rag

已核验的 auto-coder 路径提供两类基线：

1. `.cache/byzerai_store_duckdb.db` 的简单 DuckDB retrieval：
   - `_id,file_path,content,raw_content,vector FLOAT[],mtime`；
   - `list_cosine_similarity`；
   - 默认 similarity `0.1`、top-k `10000`、dimension `1024`；
   - hybrid index 默认关闭。
2. LongContextRAG 三阶段流程：
   - query extraction/expansion、recall、LLM relevance filter；
   - score ordering、原文顺序恢复、TokenLimiter；
   - context、QA prompt、streaming、timeout/retry/cancel、中文兜底。

v7 应复用这些**外部行为和 golden baseline**，但不复用旧 cache schema 作为新永久 schema。

### DuckDB `NEAREST`

当前选定证据进一步确认：

```text
INNER JOIN <target>
  APPROX|EXACT NEAREST [N]
  BY DISTANCE|SIMILARITY <expression>
```

`nearest_basic.test` 证明：

- `APPROX NEAREST 2 BY SIMILARITY` 支持按左侧每行返回 top-k；
- `EXACT NEAREST 3 BY DISTANCE` 支持显式查询向量；
- 省略数字时默认为 top-1；
- 当前 `APPROX` 与 `EXACT` 结果相同，`APPROX` 只是 informational；
- target 可以是预过滤子查询。

`peg_transformer.hpp` 中的 trampoline 声明是生成代码证据，不是计划中的手工修改点。以上证据仍须在 `/Users/wxl/Projects/duckdb-pgagent` 的固定 commit 和最终 Python binding 上复测。Flock 生成查询时统一显式写入正整数 `N`，包括 top-1，避免产品行为依赖隐式默认值。

## 2.2 v6 与 v7 的生命周期边界

| 维度 | v6 workbench | v7 RAG |
|---|---|---|
| Scope | run-scoped | deployment-scoped |
| 数据寿命 | 临时 | 永久，受 retention 管理 |
| DuckDB | `:memory:` | deployment 专用 text/schema 文件 |
| 文件打开者 | 临时 worker | 唯一 RAG owner 进程 |
| 查询执行者 | 普通 v6 worker | owner 内 query-only reader connection |
| Writer | 临时 session connection | owner 内单一串行 writer connection |
| Queue | `duck_heavy_requests` | `rag_ingest/index/query_requests` |
| API | `wb_duck_*` | `use_rag_tool`、RAG provider、owner IPC |
| 恢复 | session lost/replay definitions | 重开同一文件并恢复 generation |
| 迁移 | 无永久数据 | revision/index/catalog migration |
| 回滚 | 重建临时 session | 停 owner、恢复备份、重启固定旧 runtime |

## 2.3 当前差距矩阵

| 能力域 | 当前状态 | v4.1 目标 | 关闭条件 |
|---|---|---|---|
| v7 runtime 生命周期 | 只有 v6 run-scoped `:memory:` session | deployment-scoped persistent runtime | restart、lease、file lock、generation pin 测试 |
| 查询并发 | 无持久文件并发模型 | 唯一 owner 打开 live 文件；同进程 writer + query-only readers | 8 并发查询、并发 active swap、failover 测试 |
| Query queue | 仅有 `duck_heavy_requests` | `rag_query_requests` 只由 owner 执行 | 非 owner 无法打开文件或消费查询 |
| Streaming/deferred | 无 v7 contract | streaming 走 owner IPC；deferred 走 PGMQ，二者互斥 | 参数验证、事件和 bounded result 测试 |
| MinerU tree ingestion | 不存在 | JSON → tree-preserving revisioned catalog | 真实 fixtures、树不变量、round-trip |
| Range 语义 | 假设式 line range | page/bbox/node/char 为基础；line map 有条件生成并带 `range_origin` | PDF、代码、legacy 三类 golden |
| Legacy importer | 原计划过晚 | Phase 0 probe，Phase 2 canonical importer | baseline 与 canonical import 测试 |
| BM25 | Flock 无实现 | 固定 tokenizer/config 的 persistent index | golden ranking、manifest hash |
| Dense retrieval | mdenseon shape 未冻结 | mdenseon adapter + exact `NEAREST` 默认路径 | weights/tokenizer/dimension gate |
| Multi-vector | tachiom API 未冻结 | duckdb-tachiom adapter | build/index/query E2 gate |
| Candidate ranking | `FusionRRF`/`llm_rerank` 不足 | relation/temp staging + late materialization | 无 full-text candidates JSON 往返 |
| LongContextRAG | v7 不存在 | auto-coder parity pipeline | query/filter/limiter/QA/stream suite |
| Schema RAG | 不存在 | 独立 schema file/catalog/index/provider | snapshot、route、redaction、consistency |
| Credential storage | 无统一 v7 方案 | operator secret registry，仅保存 secret reference | Postgres/DuckDB/queue/log 无明文凭据 |
| Deployment identity | 原计划 facts 重复 `deployment_id` | 每文件唯一 identity，事实表省略 deployment ID | open-time identity mismatch test |
| Query metrics | 原计划可能写 reader DB | query 返回 bounded metrics；owner async sink 写 Postgres | reader 零持久写入、sink failure 测试 |
| Retention/GC | 不完整 | revision/index/raw JSON/backup/metrics 全部有 policy 和 dry-run | pin、dry-run、apply generation fence |
| API/安全 | v6 guardrails 不适用 | deployment-bound API，无 DSN/path/raw SQL/credential | adversarial suite |
| 四仓版本 | runtime 版本分散 | exact commit/build/model/artifact manifest | clean rebuild 和 hash 验证 |

## 2.4 方案规模判断

这是一个**additive v7 architecture**，不是对 v6 的 targeted patch，也不是重写现有 Flock LLM 功能。必须新增 deployment runtime、persistent catalog、retrieval engine 和 LongContext orchestration；但应保持以下既有路径不变：

- v6 `DuckSessionManager` 与 `wb_duck_*`；
- Flock 现有 `llm_*`、`fusion_rrf`、`llm_rerank`；
- v6 固定 DuckDB Python runtime；
- DuckDB target fork 已有的 `NEAREST` production parser/transformer。

这样既解决生命周期不兼容，也避免形成“永久 RAG 借用临时 session”的平行语义。

# 3. Design

## 3.1 五个 workstreams

全计划固定为以下五条 workstream，不再增加平行工作流：

| Workstream | 范围 | 主要仓库 |
|---|---|---|
| **WS1：证据、版本与目标 runtime** | 契约冻结、四仓 manifest、DuckDB target、Python static build、NEAREST 验证 | 四仓 |
| **WS2：deployment 持久化与 MinerU catalog** | owner-bound files、tree schema、line projection、revision、legacy importer、retention/GC | Flock、pg-agent |
| **WS3：检索、排序与 metrics** | BM25、mdenseon、NEAREST、tachiom、候选 staging、late materialization、metrics | Flock、duckdb-python、pg-agent |
| **WS4：Schema RAG、provider 与安全** | schema snapshot、独立索引、路由、external adapter、secret refs、redaction | Flock、pg-agent |
| **WS5：LongContext、API、队列与发布** | query expansion、LLM filter、TokenLimiter、QA、streaming、deferred queue、failover、cutover | pg-agent、Flock |

## 3.2 仓库依赖图与版本 manifest

### 依赖图

```text
duckdb-pgagent
  fixed: a1f0ab1911 / duckdb-special-20260829-g1
        │
        ├──────────────→ Flock
        │                 persistent catalog/search/scoring/schema
        │
tachiom ─→ duckdb-tachiom ┘
        │
        └──────────────→ duckdb-python-pgagent
                           target DuckDB + static Flock/FTS/tachiom
                                      │
                                      ▼
                                  pg-agent v7
                       owner service / LongContext / queue / API

MinerU/KohakuRAG fixtures ── evidence + ingestion contract ──→ Flock/pg-agent
mdenseon weights/tokenizer ─ dense model contract ───────────→ Flock adapter
auto-coder.rag ───────────── parity/golden baseline ─────────→ pg-agent v7
Infinisynapse evidence ───── schema workflow reference ──────→ schema provider
```

### 四仓硬约束

| 仓库 | v4.1 约束 |
|---|---|
| `pg-agent` | v7 从 v6 SQL 基线派生；不得让 v7 runtime 导入 v6 DuckSession |
| `flock` | 使用目标 DuckDB fork 编译；不得使用 floating DuckDB submodule |
| `duckdb-pgagent` | 固定 `a1f0ab1911`；branch 只作 provenance |
| `duckdb-python-pgagent` | 固定 Phase 0 clean commit；输出与 v6 wheel 分离的 v7 artifact |

外部 MinerU、KohakuRAG、mdenseon、tachiom 仓库是 contract/build dependency 或证据源，不扩大“四仓原子版本约束”的定义。

### Manifest 必备字段

`v7/VERSION_MANIFEST.json` 和 deployment manifest 必须覆盖：

- pg-agent、Flock、duckdb-pgagent、duckdb-python-pgagent commit；
- DuckDB engine version、build flags、Python version、platform/architecture；
- Flock ABI/catalog version；
- MinerU runtime distribution/version；
- MinerU runtime identity：wheel sha256 + `profile_id` + 84-wheel lock closure；container image digest **N/A**（非 OCI runtime；值保持 null，禁止编造 hash）。禁止用 MinerU-Popo floating tag 冒充 parser pin；
- MinerU model identity：HuggingFace repository/revision + `snapshot_manifest_sha256` + file_count + total_bytes；无 single-file weights sha；关键解析配置仍必备；
- canonical MinerU contract version；
- mdenseon package/native runtime version；
- mdenseon model weights SHA-256；
- tokenizer identity、version/hash；
- embedding dimension、dtype、normalization、batch contract；
- tachiom 和 duckdb-tachiom commit；
- tachiom static/loadable artifact SHA-256 和 index format version；
- FTS extension version；
- BM25 tokenizer、stemming、stop-word、case-folding、Unicode normalization 配置及其 hash；
- build artifact/wheel SHA-256。

兼容规则：

- DuckDB/Flock/tachiom ABI 或 catalog format 不匹配：拒绝打开 live store；
- mdenseon weights/tokenizer 或 BM25 config 变化：创建新 index generation，不能复用旧 index；
- MinerU runtime变化：仅影响新 document revision；旧 revision 仍可读；
- 任何 dirty tree、floating branch 或 hash 缺失：release gate 失败。MinerU container image digest 与 single-file weights sha 为 N/A（F-14：非 OCI runtime、非单文件权重）时不按 hash 缺失处理；其它 required hash（wheel、mdenseon、tachiom、BM25、tokenizer）缺失仍即失败。

## 3.3 Deployment storage、owner 和查询并发

### 首期固定模式

首期只实现：

> **Owner-only live-file mode：同一 deployment 的 live text/schema DuckDB 文件只允许唯一 owner 进程打开。**

首期不实现 generation-stamped immutable query snapshot，也不允许 API worker、queue worker、benchmark worker或 CLI 直接打开 live 文件。

一个 RAG owner service 进程可拥有多个 deployment，但首期只有一个 active RAG owner service 进程消费整个 RAG queue family；多 active owner 横向分片不在首期范围。

### 文件布局

```text
<RAG_ROOT>/<deployment_id>/
  .owner.lock
  manifest.json
  text/rag.duckdb
  schema/rag.duckdb
  backups/<backup_generation>/
  result_artifacts/<artifact_id>
```

路径由 operator 配置和受验证的 deployment identity 导出。模型、named tool 和 queue payload 不得提供文件路径。

### 文件内 deployment identity

采用以下统一方案：

- 所有 per-deployment fact tables **省略 `deployment_id`**；
- 每个文件只有一行 `flock_rag_store_meta`，包含：
  - `deployment_id`；
  - `store_kind = text|schema`；
  - `store_uuid`；
  - `catalog_version`；
  - `created_at`；
  - `build_manifest_hash`。
- 外部 `manifest.json` 重复保存同一 identity 和文件 hash；
- 打开文件时同时比对：
  - 期望的 deployment；
  - path-derived identity；
  - `manifest.json`；
  - `flock_rag_store_meta`。
- 任何不一致返回 `RAG_STORE_IDENTITY_MISMATCH`，不允许自动修正。
- Flock search/schema result 从 `flock_rag_store_meta` 注入 `deployment_id`；Python provider 再验证并对外返回。
- document、revision、snapshot、chunk ID 只需在该 deployment 内唯一；跨 deployment 外部 identity 使用 `(deployment_id, provider_kind, local_id)`。

### Owner components

#### `DeploymentRagStore`

Python class，生命周期等于 owner 对某 deployment 的 ownership：

```text
deployment_id
owner_generation
text_store
schema_store
writer_queue
text_writer_connection
schema_writer_connection
text_reader_pool
schema_reader_pool
generation_pins
manifest
closed
```

#### `RagOwnerService`

Python service，拥有：

- operator-controlled Unix domain socket；
- global owner-service lease；
- per-deployment lease和 lock；
- deployment store registry；
- RAG queue consumers；
- direct sync/stream request handlers；
- metrics async sink；
- cancellation registry。

首期 IPC 固定为单机 Unix domain socket：

- socket 位于 `<RAG_ROOT>/.control/rag-owner.sock`；
- operator 创建目录并限制为 owner OS user；
- socket 权限 `0600`；
- API client 不接收 socket path 参数；
- 不支持跨主机 RPC；
- IPC envelope 包含 `request_id`、deployment binding 和 deadline，但不含 credential。

### Connection 模型

每个 deployment：

- 一个 text writer connection；
- 一个 schema writer connection；
- 一个 deployment-level writer queue，串行调度两个文件的持久 mutation；
- 默认每个文件四个 query-only reader connections，operator 可调但首期硬上限为 16；
- DuckDB connection 不在线程之间共享；一个 reader 同时只服务一个请求；
- reader 是**应用层 query-only connection**：
  - 只允许只读 transaction 和 connection-local TEMP staging；
  - 禁止 persistent DDL/DML、`ATTACH`、`INSTALL`、`LOAD`；
  - 与 writer 由同一 owner 进程创建；
  - 不依赖第二个进程以 native read-only mode 打开同一文件。
- Phase 1 必须验证目标 binding 的同进程多 connection、writer/read transaction 和 TEMP staging 行为；不通过则 phase gate 失败，不能临时改成多进程打开文件。

### Generation pin

每个 query 开始时捕获并 pin：

```text
text catalog generation
document active revisions/index generations
schema snapshot generation
owner lease generation
```

后续 recall、LLM filter 后的再 materialization 都显式使用已 pin 的 revision/index ID，不重新解析“当前 active”。因此：

- ingestion 可以建立并激活新 revision；
- 已开始的 query 仍读取旧 revision；
- GC 跳过所有 in-flight generation pins；
- query 完成、失败或取消后释放 pin；
- owner crash 后所有内存 pin 消失，同时也不存在仍在执行的 query，新 owner可安全恢复。

### Owner fencing 和 failover

顺序固定为：

1. candidate owner 获取 deployment `.owner.lock`；
2. 在 Postgres 以 CAS 更新 lease generation；
3. 打开 text/schema 文件；
4. 校验 identity/manifest；
5. 恢复未完成 operation 和 failed generations；
6. 注册可服务状态。

新 owner不能先在 Postgres 宣告 ownership 后再等待文件锁。文件锁保证旧进程仍存活时新进程不能打开 live 文件。

旧 owner：

- heartbeat 失败或发现 generation 不一致后立即停止接收新请求；
- interrupt readers；
- rollback writer transaction；
- 关闭 connections；
- 释放文件锁；
- 在无法确认 lease 有效时不得提交写 transaction。

新 owner在进程死亡、OS 自动释放锁后接管。直接 IPC client 遇到 owner generation 变化可重新解析 owner并重试一次；streaming 请求不自动重放，以免重复答案。

## 3.4 Streaming、同步与 deferred queue

### 三种互斥模式

`use_rag_tool` 的控制参数固定为：

```text
stream: boolean = false
defer: boolean = false
```

| `stream` | `defer` | 行为 |
|---|---|---|
| `false` | `false` | 通过 owner IPC 同步执行，返回 bounded completed result |
| `true` | `false` | 通过 owner IPC 执行并返回 event stream |
| `false` | `true` | 写入 `rag_query_requests`，立即返回 operation handle |
| `true` | `true` | 参数错误 `RAG_ARGUMENT_ERROR` |

不得在 owner 不可达时把 `stream=true` 静默降级为 deferred。

### Direct streaming path

```text
named tool / Python client
  → RagOwnerClient
  → Unix socket
  → RagOwnerService
  → LongContextRAG
  → bounded event channel
  → caller
```

事件至少包括：

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

约束：

- 只有 direct streaming path 可以返回 `answer_delta`；
- channel 有 backpressure 和 bounded buffer；
- client 断开默认触发 cancellation；
- 首期不提供 stream resume；
- completed/failed/cancelled 必须恰好有一个终止事件。

### Deferred path

```text
use_rag_tool(defer=true)
  → rag_query_requests
  → active RagOwnerService queue consumer
  → non-streaming LongContextRAG
  → rag_operations result
  → inline bounded result 或 artifact reference
```

约束：

- `rag_query_requests` 只由 active owner service 消费；
- deferred execution 内部不得产生或持久化 `answer_delta`；
- 默认 inline result 上限为 256 KiB；
- 超过上限时写入受控 `result_artifacts`，Postgres 只存 artifact reference、size、hash 和 expiry；
- artifact 默认保留七天；
- `get_rag_result(operation_id)` 返回 `pending|completed|failed|cancelled`；
- queue 是 at-least-once，`operation_id/idempotency_key` 保证重复消息不会重复写入或重复生成正式 result；
- queue message 不含 query expansion prompt、secret、raw MinerU JSON 或完整 PDF。

### Queue family

```text
rag_ingest_requests
rag_index_requests
rag_query_requests
rag_ingest_requests_dlq
rag_index_requests_dlq
rag_query_requests_dlq
```

写操作 idempotency key：

```text
deployment_id + document_id + source_hash + requested_revision + operation_kind
```

查询使用 caller-supplied/系统生成的 `request_id` 和独立 operation attempt。

## 3.5 Text catalog、MinerU tree 和 range provenance

### Text store schema

事实表全部省略 `deployment_id`。

| 表 | 核心内容 |
|---|---|
| `flock_rag_store_meta` | 唯一 deployment/store identity |
| `rag_document` | `document_id`、title、source alias/hash、active revision、source ordinal |
| `rag_document_revision` | revision、status、MinerU provenance、raw JSON、parser version |
| `rag_section` | section hierarchy、level、ordinal、page/bbox |
| `rag_node` | node kind、parent/section、ordinal、text、page/bbox/char/range |
| `rag_edge` | contains/parent/next/references/caption/table/image 关系 |
| `rag_page` | 1-based page number、geometry、page text、raw JSON |
| `rag_table` | node/page link、caption、header/rows/markdown/raw JSON |
| `rag_image` | node/page link、asset reference、caption、alt text、bbox/raw JSON |
| `rag_metadata` | key/value/JSON/source |
| `rag_text_projection` | 持久化的 source/normalized/legacy text projection |
| `rag_projection_line` | projection 的稳定 1-based line map |
| `rag_chunk` | canonical retrieval unit 和 range provenance |
| `rag_vector` | chunk/vector role/model/dimension/embedding |
| `rag_index_manifest` | BM25/dense/multi-vector generation 和配置 hash |

### MinerU 基础定位信息

不能假设 MinerU 原生提供源码行号。canonical node/range 的基础定位信息是：

- `page_start/page_end`：外部统一 1-based；
- page-relative `bbox_json`；
- `node_start_id/node_end_id`；
- `projection_id`；
- `char_start/char_end`：0-based、half-open、按 Unicode code point 计数；
- 可选 `line_start/line_end`：1-based、闭区间；
- `range_origin`。

`range_origin` 是闭合集合：

| 值 | 含义 |
|---|---|
| `source_line` | 输入源本身有可信稳定行号，例如代码/纯文本文件 |
| `normalized_line` | 由持久化 normalized text projection 生成的 synthetic line map |
| `page_bbox` | 无可靠线性行映射，只能用 page/bbox/node 定位；line 字段为 NULL |
| `legacy_flat` | 从 auto-coder flat cache 的持久 content/raw_content 生成的兼容行映射 |

### Text projection

`rag_text_projection` 至少包含：

```text
projection_id
document_id
revision
projection_kind
normalization_version
text
text_hash
line_count
created_at
```

`rag_projection_line` 至少包含：

```text
projection_id
line_number
char_start
char_end
page_number?
node_id?
```

约束：

- `line_number` 从 1 开始；
- char range 仍是 0-based half-open；
- normalized text、normalization version、line table 和 hash 原子写入；
- node/chunk 的 line range 只能引用同一 projection；
- normalization 变化必须创建新 document revision或 projection generation；
- 不允许在 query 时对相同文本临时重新切行后冒充持久 source range。

### PDF 与 `SourceCode` compatibility

对于 PDF：

- 如果 MinerU 文本规范化后能形成稳定 projection，使用 `normalized_line`；
- `start_line/end_line` 是 synthetic normalized lines，不是 PDF 原始文件行号；
- 如果只有布局定位，使用 `page_bbox`，公开 line range 为空；
- compatibility facade 若必须返回 `SourceCode.start_line/end_line`，只能对 `normalized_line` 映射，并在 metadata 中同时返回 `range_origin`、page 和 bbox；
- 不得把 PDF synthetic lines 描述为代码文件源码行号。

对于代码/纯文本：

- 有可信源行号时使用 `source_line`；
- TokenLimiter 的 1-based line semantics与现有 `SourceCode` 一致。

对于 legacy cache：

- 使用持久化的 `content/raw_content` 生成 `legacy_flat` projection；
- 不伪造 section/page/bbox/table/image。

### Tree invariants

每个 revision 激活前必须验证：

1. document/revision identity 唯一；
2. section 和 node parent graph 无环；
3. parent/reference 可解析或明确记录 unresolved warning；
4. page number 合法；
5. 同父节点 ordinal 唯一且稳定；
6. bbox 坐标符合 Phase 0 冻结契约；
7. projection char range 合法；
8. line range 与 projection line table一致；
9. `page_bbox` range 的 line 字段为空；
10. table/image引用有效；
11. unknown node 保留原始 JSON；
12. source/raw JSON/parser/manifest hash 一致。

### Revision activation

```text
BUILDING
  → tree validated
  → projection/chunk READY
  → required indexes READY
  → atomic active_revision swap
  → previous revision RETIRED
```

任何 required backend 失败时：

- 新 revision 不激活；
- 旧 revision保持 active；
- 新 revision标记 `FAILED`；
- 除非请求显式启用 fallback，否则不静默改用其他 backend。

## 3.6 Legacy importer

### Phase 0：最小只读 probe

新增最小 probe，仅用于读取旧 auto-coder cache 和建立 baseline：

- 始终以 read-only 打开 `.cache/byzerai_store_duckdb.db`；
- 检查表名、列类型、row count、dimension、NULL 和重复 ID；
- 读取 bounded sample 和固定 golden records；
- 运行旧 `list_cosine_similarity` 查询并保存 expected top-k；
- 记录 `json/fts/vss`、hybrid flag 和 DuckDB version；
- 不创建 v7 catalog；
- 不修改旧文件；
- 不把绝对 file path 或 content 写入普通日志。

输出为 versioned golden fixture/summary，供 Phase 2/3 使用。

### Phase 2：正式 canonical importer

正式 importer 将 legacy row 映射为：

```text
rag_document
rag_document_revision
rag_node(node_kind=legacy_flat)
rag_text_projection(projection_kind=legacy_flat)
rag_projection_line
rag_chunk(range_origin=legacy_flat)
rag_vector
rag_index_manifest
```

规则：

- `_id` 映射为 deployment 内稳定 document ID；
- `file_path` 经过 source policy 脱敏；
- `content/raw_content` 按冻结规则选择 canonical projection；
- vector 仅在 dtype/dimension/model manifest 可证明兼容时导入；
- 不兼容 vector 跳过并要求 re-embed，不做 padding/truncation/reshape；
- 无 MinerU tree 时不伪造 section/page/table/image；
- importer 使用与 MinerU ingestion 相同的 revision transaction 和 active swap。

Phase 7 只调用该 importer 执行生产迁移，不再首次开发 importer。

## 3.7 Retention、GC 和备份

### 默认 policy

| 数据 | 默认保留策略 |
|---|---|
| Active revision | 文档 active 期间永久保留 |
| Retired revisions | 同时保留最近 2 个；且所有退役未满 30 天的 revision 均保留 |
| Failed/BUILDING revision | 无 in-flight operation 时，24 小时后可清理 |
| Raw MinerU JSON | 与所属 revision 同生命周期；active revision 的 raw JSON 不单独删除 |
| READY indexes | 与所属 revision 同生命周期 |
| Failed index generation | 24 小时后可清理 |
| Pre-migration/backups | 保留最近 3 份，并保留所有未满 14 天的备份 |
| Query metrics | Postgres 中保留 30 天 |
| Deferred result artifacts | 保留 7 天 |
| GC audit records | 保留 90 天 |
| Pinned/legal-hold data | 无期限，直到 operator 解 pin |

删除 retired revision 的条件是：

```text
不是 active
不是最近两个 retired revision
退役已超过 30 天
无 generation pin
无 legal hold
无 migration/rollback reference
```

### GC execution

GC 只能由 owner writer queue 执行。Operator API 必须支持：

```text
dry-run
apply
```

Dry-run 输出：

- deployment/store generation；
- 候选 revision/index/raw JSON/backup/artifact；
- 估算 rows/bytes；
- retention rule 和删除原因；
- pin/hold 阻塞项；
- plan hash 和 expiry。

Apply 必须携带 dry-run 的 plan hash 和 expected generation；store generation、active revision或 pin 集变化后拒绝执行，要求重新 dry-run。

文件内 revision/index/raw JSON 清理使用 writer transaction。Backup/artifact 文件删除使用两阶段状态：

1. 在 metadata 标记 `DELETE_PENDING`；
2. 删除文件并验证；
3. 标记 `DELETED`；
4. crash 后根据状态幂等恢复。

### Backup

Catalog migration、index format migration和生产 cutover前：

1. owner进入 maintenance；
2. 停止新 query；
3. 等待或取消 in-flight pins；
4. checkpoint；
5. 关闭 text/schema connections；
6. 复制并 hash 文件与 manifest；
7. 重新打开并验证；
8. 执行 migration。

非 owner CLI 不得直接复制仍被打开的 live 文件。

## 3.8 Retrieval、ranking 与 late materialization

### Flock SQL API

新增 additive APIs；不修改现有 `llm_*`：

| API | 类型 | 责任 |
|---|---|---|
| `flock_rag_health()` | table function | ABI/catalog/backend/manifest health |
| `flock_rag_ingest_mineru(...)` | table function | JSON → revisioned tree/projection/chunk |
| `flock_rag_recall(query, options)` | table function | 返回 candidate IDs、scores、ordinals，不返回全文 |
| `flock_rag_rank_staged(options)` | table function | 从 connection-local candidate stage 排名 |
| `flock_rag_search(query, options)` | convenience table function | 简单检索，内部 recall/rank 后再 materialize |
| `flock_schema_extract_snapshot(options)` | table function | 读取当前 DuckDB catalog |
| `flock_schema_ingest_snapshot(...)` | table function | 写入 schema store |
| `flock_schema_list_tables(options)` | table function | 受控 catalog list |
| `flock_schema_show_create(relation)` | table function | 返回规范化 DDL/metadata |

所有 options 使用受验证 JSON schema；未知安全或 backend 选项不得静默忽略。

### Candidate stage

取消上一版 `candidates_json` full-text round trip。每个 reader connection 一次只处理一个 query，并建立 connection-local TEMP candidate stage，固定字段：

```text
candidate_id
document_id
revision
chunk_id
document_ordinal
chunk_ordinal
source_query_ordinal
bm25_score?
dense_score?
multi_vector_score?
llm_relevance_score?
page_start/page_end
line_start/line_end
range_origin
```

明确不包含：

- chunk text；
- raw MinerU JSON；
- embedding；
-完整 metadata JSON。

TEMP stage 仅存在于当前 query-only reader connection，不写 persistent file。Flock ranking function只读取固定内部 stage，不接受模型或用户提供 arbitrary table name。

### LongContext retrieval/materialization 顺序

```text
1. Flock recall：IDs/scores/ordinals only
2. TEMP stage
3. Flock preliminary dedup/fusion/rank
4. 截断到 bounded LLM-filter candidate cap
5. materialize 这些候选的文本供 Python relevance filter
6. Python 返回 candidate_id + relevance score
7. 更新 TEMP stage 中的 relevance score
8. Flock final scoring/document ordering
9. 截断 final context candidate set
10. late materialize 最终文本、range、section/page metadata
11. Python TokenLimiter/context assembly
```

这样只有通过 preliminary rank cutoff 的文本进入 Python，且返回 Flock 的只有 ID 和 score，不会把所有 full text 序列化进 JSON。

### `RagScoringEngine`

Flock C++/SQL 新增无 LLM 副作用的 scoring engine：

1. 校验 NULL、NaN 和 backend score direction；
2. 按 backend manifest 规范化 score；
3. 跨 expanded query 按 candidate ID 去重；
4. 保存最佳来源 query 和 backend trace；
5. 使用 weighted score、RRF 或冻结的 multi-vector fusion；
6. 接收 Python 提供的 `llm_relevance_score`；
7. 计算 document-level score；
8. 决定 document 顺序；
9. document 内恢复 source/document/chunk ordinal；
10. 使用稳定 tie-break：

```text
combined_score DESC
document_score DESC
document_ordinal ASC
chunk_ordinal ASC
candidate_id ASC
```

`llm_rerank` 不参与该流程。

### BM25

BM25 index manifest必须记录：

- tokenizer；
- stemming；
- stop words；
- case folding；
- Unicode normalization；
- field weights；
- backend/version；
- config hash。

如果目标 Python binding 可静态提供已验证的 FTS，则复用；否则才实现 Flock-owned BM25。两条路径不能同时作为未显式选择的默认实现。

### Dense 和 `NEAREST`

`IDenseEmbeddingBackend` 的稳定边界是：

```text
text batch + model config
  → vectors + dimension + dtype + normalization + model/tokenizer identity
```

mdenseon 的实际 API、模型 shape、线程安全、batch 和设备策略在 Phase 0/1 冻结。

NEAREST 规则：

- Flock 总是显式写入 `N`；
- `N` 必须在配置的 `1..max_candidate_cap` 内；
- 首期默认使用 `EXACT`；
- `APPROX` 仅在目标 fork E2 benchmark 证明存在独立执行路径和收益后才能启用；
- distance/similarity 在 Flock boundary 统一成“越高越好”的 normalized score；
- dimension 与 index manifest 不匹配时返回 `RAG_VECTOR_DIMENSION_MISMATCH`；
- 不做 silent reshape。

### tachiom multi-vector

`IMultiVectorIndex` 稳定边界：

```text
build(revision, vector rows, options)
search(query vectors, options)
retire(index generation)
```

Phase 0/1 必须冻结真实：

- extension target/artifact；
- vector role/model shape；
- index build/query API；
- distance/similarity semantics；
- update/delete/rebuild；
- transaction、connection和thread safety；
-与 `NEAREST` 的关系。

Gate 未通过时：

- `multi_vector` 返回 `RAG_MULTI_VECTOR_UNAVAILABLE`；
- BM25/dense 可独立发布；
- 默认不静默 fallback。

## 3.9 Query metrics

Query-only reader 不写 `rag_query_metrics` 或任何 persistent DuckDB table。

### Query path

每次 query 返回 bounded metrics object，最大序列化大小默认 8 KiB，包含：

```text
request_id
owner_generation
text/schema generation
query expansion count
backend candidate counts
deduplicated/preliminary/final counts
backend/filter/context/QA latency
token counts
first-token/total latency
cancelled/error class
```

不包含 raw query、prompt、document text、secret 或完整路径。

### Async persistence

`RagOwnerService` 把 metrics summary 投递到 bounded in-memory `RagMetricsSink`：

```text
query handler
  → bounded metrics object returned to caller
  → async sink queue
  → Postgres rag_query_metrics
```

规则：

- sink 不阻塞或改变 query 成功结果；
- 按 `(request_id, attempt)` 幂等 upsert；
- out-of-order completion 使用 attempt/completed timestamp 归并；
- queue 满时丢弃 observability record并增加进程级 dropped counter；
- owner crash 可丢失未 flush metrics，这是允许的 degraded mode；
- 不回写 text/schema DuckDB；
- metrics retention 默认 30 天。

## 3.10 Schema RAG、provider 与 credential

### 独立物理 store

Schema RAG 使用：

```text
<RAG_ROOT>/<deployment_id>/schema/rag.duckdb
```

不得与 text/PDF chunk、vector 或 BM25 index 共享物理表或 index namespace。

事实表同样省略 `deployment_id`：

```text
schema_snapshot
schema_relation
schema_column
schema_key
schema_relationship
schema_sample
schema_profile
schema_index_manifest
```

每个 query pin 固定 `snapshot_id/index_generation`，不读取半完成 snapshot。

### Catalog extraction

Flock 直接读取目标 DuckDB 已验证的：

```text
information_schema
duckdb_tables()
duckdb_columns()
duckdb_constraints()
duckdb_views()
duckdb_dependencies()
```

实际函数/view 名以目标 fork E2 验证为准。

外部数据库通过 pg-agent v7 Python controlled adapter：

```text
operator source binding
  → resolve secret reference
  → allowlisted metadata connection
  → normalize schema snapshot
  → Flock schema_ingest_snapshot
```

不复制 JDBC、DatabaseHub 或 Infinisynapse 的数据库服务层。

### Secret registry

统一使用 pg-agent/operator secret registry。Postgres、DuckDB、queue 和 manifest 只保存 opaque secret reference。

适用范围：

- external schema adapter credential；
- MinerU source/object store/API credential；
- LLM provider key；
- 如有必要，受控 model registry credential。

新增内部 resolver contract：

```text
resolve(secret_ref, purpose, deployment)
  → ephemeral credential
```

约束：

- secret reference 必须绑定 deployment、purpose 和 policy；
- queue 只传 `source_binding_id`，不传 secret ref 或明文；
- credential 只在 owner 进程按需解析；
- 不写磁盘、metrics、error、prompt 或 DuckDB；
- Flock SQL function不接受 credential、DSN、token或 secret ref；
- Flock仅接收已经规范化的数据或本地模型配置；
- v7 LongContext LLM 调用使用 operator registry，不复用 Flock旧 `llm_*` secret flow；
- 现有 Flock LLM APIs 保持原行为，但不进入 v7 RAG pipeline。

### Schema context

| Context | Owner | 生命周期 |
|---|---|---|
| `schemaContext.md` | schema provider生成 | schema snapshot generation |
| `kpiContext.md` | operator/application配置 | deployment |
| `activeContext.md` | Python conversation state | conversation/run |

Schema snapshot只有在完整 READY 后才能原子发布新的 `schemaContext` version。

### Provider 路由

统一 provider contract：

```text
search(request) → RagSearchResult
stream(request) → StreamEvent iterator
health() → RagHealth
```

路由模式：

- `schema_first`：表、列、join、KPI、SQL、relationship；
- `text_first`：PDF、章节、文档说明；
- `hybrid`：分别查询两个物理 provider，再在 Python context budget 层合并；
- `auto`：Python deterministic intent classifier，不能绕过权限。

每个 candidate保留 `provider_kind=text|schema`，不得把 schema relation当成普通 PDF chunk。

`list_tables → show_create → register_table → execute SQL` 中：

- `register_table` 只把受权 relation descriptor加入 active schema context；
- 不复制表数据到 schema RAG；
- `execute SQL` 仍由现有受授权、带 guardrail 的 SQL tool执行；
- `use_rag_tool` 不新增 arbitrary SQL 参数。

## 3.11 LongContextRAG parity

### 完整流程

```text
conversation/query
  → Python query extraction/expansion
  → text/schema/hybrid route
  → Flock ID/score-only recall
  → preliminary ranking
  → bounded text materialization
  → Python LLM relevance filter
  → Flock final ranking/original-document reorder
  → final late materialization
  → Python TokenLimiter
  → context assembly
  → QA prompt
  → LLM sync/stream
```

### Query expansion

- 保留原 query 和 expanded query trace；
- expansion有独立 deadline；
- expansion失败时记录 `RAG_QUERY_EXPANSION_FAILED`，使用原 query执行一次 bounded recall；
- 不无限重试；
- cancel event传播到 retrieval和LLM。

### LLM relevance filter

- 使用 bounded `ThreadPoolExecutor`；
- worker count和 prompt/schema 由 Phase 0 auto-coder contract冻结；
- future结果按 candidate stable key重排，不按完成顺序；
- 只重试 transport、429、5xx；
- auth、invalid schema、无法解析的 model response不重试；
- Python只把 candidate ID和 relevance score回传 Flock；
- `llm_rerank` 不作为替代实现。

### TokenLimiter

必须保留：

- 小文件合并；
- 大文件按 token budget切分；
- deterministic truncation；
- 1-based闭区间；
- token counter错误传播；
- document/range稳定顺序。

范围解释：

- `source_line`：与代码/文本真实行一致；
- `normalized_line`：PDF synthetic normalized lines；
- `page_bbox`：无 line range，只通过 page/bbox/node引用；
- `legacy_flat`：旧 cache projection 的兼容行。

TokenLimiter不得把 `page_bbox` range伪造成 line range。

### `without_contexts`

固定语义：

```text
without_contexts=true
  → 不执行 text/schema recall
  → 不执行 relevance filter
  → 不执行 TokenLimiter context assembly
  → contexts=[]
  → 可以继续执行无上下文 QA
```

### Compatibility facade

保持：

```text
RAGManager.search() → List[SourceCode]
LongContextRAG stream generator
```

适配：

- `SourceCode` source/content/range；
- stream event；
-中文 error；
- legacy default similarity/top-k/dimension；
- PDF synthetic line通过 metadata明确 `range_origin`；
- compatibility mode的 top-k `10000` 仅用于旧接口，不作为 model-facing named tool默认上限。

## 3.12 API、错误和取消

### Named tool

`use_rag_tool` 参数：

```text
query
mode = auto|schema_first|text_first|hybrid
retrieval_mode = bm25|dense|multi_vector|hybrid
without_contexts
top_k
timeout_ms
stream
defer
```

禁止参数：

- deployment override；
- DSN；
- DuckDB file path；
- secret/token；
- raw SQL；
- extension name/path；
- arbitrary source table name。

响应形状：

| 模式 | 响应 |
|---|---|
| direct sync | completed answer、bounded contexts、metrics |
| direct stream | StreamEvent iterator |
| deferred | accepted operation ID、poll contract |
| invalid stream+defer | structured argument error |

### Error taxonomy

至少包含：

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
RAG_STORE_IDENTITY_MISMATCH
RAG_OWNER_CONFLICT
RAG_OWNER_UNAVAILABLE
RAG_SCHEMA_SOURCE_FORBIDDEN
RAG_SCHEMA_SNAPSHOT_FAILED
RAG_SECRET_REFERENCE_INVALID
RAG_QUERY_TIMEOUT
RAG_LLM_TIMEOUT
RAG_CANCELLED
RAG_STORAGE_MIGRATION_FAILED
RAG_STORAGE_CORRUPT
RAG_QUEUE_ERROR
```

公开错误继续使用：

```text
success
Type
Phase
Problem
Solution
```

并执行：

- credential、DSN、绝对路径、token、prompt截断和脱敏；
- 中文 Problem/Solution兜底；
- 保留 phase和可行动 recovery；
- 不原样透传 DuckDB/HTTP exception。

### Cancellation

统一使用 monotonic deadline 和 cancel event：

1. direct client cancel/disconnect 或 deferred cancel request触发；
2. owner标记 request/operation；
3. interrupt当前 reader connection；
4. cancel LLM futures；
5. 停止 stream；
6. 释放 generation pin；
7. 不修改 active revision；
8. ingestion partial generation标记 failed并由 GC清理。

## 3.13 Flock C++/SQL 与 pg-agent v7 Python 职责表

| 能力 | Flock C++/SQL | pg-agent v7 Python |
|---|---|---|
| Extension/function registration | 负责 | 不负责 |
| Persistent text/schema catalog | 定义、迁移、验证 | owner调用并管理文件 |
| Deployment path | 不负责 | 从 operator root和deployment解析 |
| 文件 identity | 读写 store meta并注入结果 | 校验 path/manifest/store identity |
| Owner lease/file lock | 不负责 | 负责 |
| Writer/reader connection | 提供 connection-safe函数 | 创建、池化、关闭、线程绑定 |
| Queue消费 | 不负责 | owner service独占消费 |
| MinerU执行/获取 | 不负责 | 负责 source/runtime binding（wheel + 本地 model snapshot）；非 OCI container |
| MinerU credential | 不接收 | secret registry解析 |
| JSON → tree | 负责 | 不复制 parser |
| Tree invariants | 负责 | 消费结构化错误 |
| Page/bbox/node/char range | 负责 | 保持不改写 |
| Normalized text/line map | 负责生成和持久化 | TokenLimiter消费 |
| Canonical chunk | 负责 | 不重新定义 source range |
| Legacy probe | 不负责 | Phase 0只读 probe |
| Canonical legacy import | 负责 catalog boundary | Python读取旧 cache并调Flock |
| BM25 | 负责 | 选择模式/配置 |
| mdenseon | 稳定 backend boundary；实际adapter按gate | 负责模型配置和runtime调度 |
| `NEAREST` SQL | 负责 | 不拼接 |
| tachiom | 负责稳定 adapter/result | 负责启用/fallback policy |
| Candidate staging | 读取 TEMP relation | 创建并填充 ID/score-only stage |
| Score normalization/ranking | 负责 | 提供 LLM relevance score |
| Original-document reorder | 负责 | 保持顺序并转 legacy object |
| Text materialization | 排名后按ID join | 控制 materialization cutoff |
| Retrieval metrics | 返回 bounded metrics | 汇总 LLM/QA并async写PG |
| Metrics persistence | 不在reader写 | owner async sink写Postgres |
| Query expansion | 不负责 | 负责 |
| LLM relevance filter | 不负责 | 负责 |
| TokenLimiter | 不负责 final context budget | 负责 |
| QA prompt/conversation | 不负责 | 负责 |
| Streaming | 不负责 | owner Python generator/IPC |
| Deferred result | 不负责 | queue/operation/artifact |
| Schema DuckDB catalog | 直接读取 | 调用和授权 |
| External schema adapter | 不持有credential | 受控adapter和secret resolver |
| Schema index/ranking | 负责 | route/context version |
| Secret storage | 不存、不接收 | operator secret registry |
| Retention facts/eligibility | 提供catalog和in-file GC能力 | policy、dry-run、owner调度、backup |
| v6 workbench | 不改 | v7禁止调用其session |

## 3.14 Acceptance 与 quality/performance baseline

### Phase 0 baseline corpus

至少包括：

- auto-coder legacy DuckDB cache的固定 read-only sample；
- `p16_mdenseon.py` 和 `fixtures/p16-mdenseon.json`；
- `p19_mineru_process.py` 对应真实 MinerU fixtures：origin-shape golden 在 `v7/tests/fixtures/range_trio/`（PDF/code/legacy 三种 `range_origin`，fixture E2，非 live MinerU 重跑）；
- KohakuRAG文档/tree fixtures；
- 小PDF、大PDF、多页、table/image/unknown block：unsatisfied / later corpus（range trio fixture E2 不覆盖该多样性）；
- 代码/纯文本 source-line fixture；
- schema fixture：table/view/PK/FK/comment/sample/profile；
- text/schema hybrid queries。

### 功能质量门

| 指标 | 门槛 |
|---|---|
| Tree invariants | 100% |
| MinerU unknown node保留 | 100% |
| Page/bbox/node/char round-trip | 无非预期丢失 |
| `range_origin` | 每个公开 range都有合法来源 |
| Line range | 非NULL时100%为1-based闭区间并可回投影 |
| Legacy simple top-1 | golden fixture 100%一致或有显式批准的版本差异 |
| BM25 ranking | 固定 tokenizer/config 下满足 golden |
| Dense dimension | 100%匹配manifest |
| Document reorder | 同文档顺序100%稳定 |
| Duplicate ingestion | 不产生第二个active revision |
| Cancelled ingestion | 不激活partial generation |
| Schema redaction | adversarial suite零敏感值泄漏 |
| Deployment isolation | A/B、v6/v7、text/schema完全隔离 |
| Stream terminal event | 每请求恰好一个 |
| Deferred events | 永不包含 `answer_delta` |
| Reader persistence | query-only reader零持久写入 |
| Credential storage | Postgres/DuckDB/queue/log零明文credential |

### 并发与 failover 门

- 同一 deployment 8 个并发 direct query；
- 同时执行一个 writer index build或active revision swap；
- 所有已开始 query保持 pin 的旧 generation；
- 新 query看到新 generation；
- owner进程 kill 后文件锁释放；
- standby取得新 generation并重开文件；
- stale owner无法提交；
- deferred message visibility timeout后由新 owner幂等恢复；
- 任何非 owner进程打开 live file 的测试必须失败。

### 性能门

在固定 macOS arm64、CPython 3.12、目标 DuckDB和manifest模型下记录：

- legacy probe/import；
- MinerU tree parse；
- projection/line-map/chunk生成；
- BM25 build/query；
- mdenseon throughput；
- EXACT/APPROX NEAREST；
- tachiom build/query；
- preliminary ranking与late materialization bytes；
- schema snapshot；
- LLM filter；
- first-token/total latency；
- reader pool并发；
- file size、memory peak、restart和backup时间。

默认门槛：

- simple retrieval p95 不超过 Phase 0同机 baseline的 `1.25x`；
- owner IPC的本地额外 p95开销不超过20 ms，且不超过核心非LLM检索耗时的20%；
- ingestion/index memory peak不超过可比 baseline的 `1.5x`；
- initial recall不得 materialize full text；
- LLM filter前materialized candidate数量不超过冻结的 filter cap；
- disabled multi-vector不得明显增加 dense-only path开销；
- `APPROX` 未证明独立加速前不作为默认；
- 所有 query受 candidate、token、timeout和result-size上限约束。

## 3.15 首期明确不做

首期不包括：

- generation-stamped immutable query snapshot模式；
- 多个 active owner进程分片或跨主机owner RPC；
- 非 owner进程打开deployment live DuckDB；
- streaming经PGMQ传输；
- `stream=true` 与 `defer=true` 同时使用；
- stream断线续传；
- query reader写 DuckDB metrics；
- 把永久RAG放入v6 DuckSession/duck artifacts/temporary queue；
- 自动迁移v6 workbench artifacts；
- PostgreSQL内嵌`pg_duckdb`；
- arbitrary `ATTACH/CONNECT/INSTALL/LOAD`；
- runtime网络下载extension；
- model提供DSN、path、secret或raw SQL；
- Flock SQL接收明文credential；
- 复制JDBC/DatabaseHub；
- 多租户完整RLS；首期是operator-bound deployment owner模型；
- tachiom/mdenseon未冻结API的假实现；
- embedding truncation/padding/reshape；
- 把`APPROX`宣传为已加速；
- 把`llm_rerank`改造成RAG ranking；
- 将PDF synthetic line称为源码行；
- 在Phase 7首次开发legacy importer。

# 4. File-by-file impact

以下路径均为仓库相对路径。Phase 0 必须核对外部仓库实际 layout；只允许调整落盘路径，不允许改变组件边界。

## 4.1 pg-agent

### 权威文档

| 文件 | 变更 | 依赖 |
|---|---|---|
| `docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md` | 保存本计划并标记authoritative | 无 |
| `docs/plans/flock-rag-on-duckdb-final-plan-v3.md` | 添加superseded banner，指向v4.1 | v4.1文档 |
| `docs/plans/flock-rag-on-duckdb-v7-final-plan-v4.md` | 添加superseded banner，指向v4.1 | v4.1文档 |
| `docs/plans/flock-rag-v4.1-review-correction-traceability.md` | Phase 0 纠正追踪清单（review finding → v4.1 section）。Open items remain (PARTIAL / UNRESOLVED); 机器可核对：`v7/evidence/corrections_register.json` | 两份 review、v4.1 |
| `docs/reviews/oracle-v4-plan-review-2026-08-29.md` | 不改review内容；只由v4.1链接 | 无 |
| `docs/reviews/flock-rag-on-duckdb-plan-review-2026-08-29.md` | 不改review内容；只由v4.1链接 | 无 |

### 明确不修改的 v6 文件

```text
v6/session_durability/duckdb_runtime.py
v6/source_ingress/duckdb_ingress.py
v6/queue_bridge/duckdb_processor.py
v6/queue_bridge/duck_queue.sql
v6/duck_tools/duck_tools.sql
v6/dialect_guardrails/duckdb_validation.py
v6/load.py
```

新增 architecture test 阻止 v7 runtime导入这些 session/queue模块。

### v7 SQL 与 loader

| 文件 | 变更 | 原因/依赖 |
|---|---|---|
| `v7/load.py` | 累积加载v6 SQL基线和v7新增SQL；独立stage数据库 | 依赖全部v7 SQL |
| `v7/rag_catalog/rag_metadata.sql` | `rag_deployments`、`rag_document_manifests`、`rag_operations`、`rag_source_bindings`、context metadata | Phase 6 |
| `v7/rag_catalog/rag_observability.sql` | `rag_query_metrics`、`rag_gc_runs`、retention pins/policies | metrics/GC |
| `v7/rag_queue/rag_queue.sql` | 三类queue/DLQ、claim/idempotency/result/cancel | owner service |
| `v7/rag_tools/rag_tools.sql` | `use_rag_tool`、`get_rag_result`、cancel、operator ingestion/GC contracts | queue/owner client |
| `v7/rag_prompt/rag_prompt.sql` | text/schema/hybrid routing和工具约束 | provider/API |

### Owner runtime

| 文件 | 变更 |
|---|---|
| `v7/rag_runtime/deployment_store.py` | `DeploymentRagStore`、text/schema connection和generation pin |
| `v7/rag_runtime/owner_lease.py` | global/per-deployment lease、generation fencing、file lock |
| `v7/rag_runtime/owner_service.py` | 唯一owner service、queue consumer、direct sync/stream handler |
| `v7/rag_runtime/owner_client.py` | API侧Unix socket client；禁止直接开DuckDB |
| `v7/rag_runtime/ipc.py` | bounded sync/stream IPC envelope、backpressure、cancel |
| `v7/rag_runtime/operation_store.py` | operation attempt/idempotency/result/artifact |
| `v7/rag_runtime/metrics_sink.py` | bounded async Postgres metrics sink |
| `v7/rag_runtime/manifest.py` | 四仓、模型、tokenizer、artifact和store identity验证 |
| `v7/rag_runtime/errors.py` | `RAG_*` taxonomy、中文兜底、脱敏 |
| `v7/rag_runtime/cleanup.py` | retention eligibility、generation-safe GC、staging cleanup |
| `v7/rag_runtime/backup.py` | owner maintenance、checkpoint、close/copy/hash/restore |

### Secret 和 source binding

| 文件 | 变更 |
|---|---|
| `v7/secrets/resolver.py` | pg-agent/operator secret registry adapter |
| `v7/secrets/redaction.py` | credential/DSN/path/prompt error redaction |
| `v7/mineru/contracts.py` | MinerU/Kohaku canonical contract、range mapping。Phase 0 先落地最小 identity 常量模块（wheel/snapshot/profile_id/PDF golden）；source adapter 与 ingest 仍 Phase 2 |
| `v7/mineru/source_adapter.py` | source binding、secret resolution、hash和artifact读取 |
| `v7/mineru/ingest_scheduler.py` | 创建无raw JSON/credential的ingest operation |
| `v7/mineru/replay.py` | 基于source reference重放，不依赖v6 artifacts |

### Migration 与 retention

| 文件 | 变更 |
|---|---|
| `v7/migration/legacy_cache_probe.py` | Phase 0最小read-only probe和golden生成 |
| `v7/migration/legacy_cache_importer.py` | Phase 2正式`legacy_flat` canonical importer |
| `v7/migration/catalog_migration.py` | catalog/index version migration orchestration |
| `v7/migration/gc.py` | operator dry-run/apply、plan hash和generation fence |
| `v7/migration/cutover.py` | Phase 7生产迁移/cutover；不实现新import逻辑 |

### Provider、retrieval 和 schema

| 文件 | 变更 |
|---|---|
| `v7/provider/contracts.py` | provider/search/stream/health/result shapes |
| `v7/provider/flock_provider.py` | owner-local Flock recall、stage、rank、materialization |
| `v7/provider/router.py` | auto/schema-first/text-first/hybrid |
| `v7/provider/candidate_stage.py` | connection-local ID/score TEMP relation |
| `v7/schema_rag/catalog_adapter.py` | DuckDB/local与受控external schema adapters |
| `v7/schema_rag/schema_provider.py` | snapshot/index/provider |
| `v7/schema_rag/context_builder.py` | schema/kpi/active context versioning |
| `v7/schema_rag/redaction.py` | comments/default/sample/profile脱敏 |
| `v7/schema_rag/sql_workflow.py` | list/show/register/execute choreography |

### LongContext

| 文件 | 变更 |
|---|---|
| `v7/long_context/config.py` | parity defaults、caps、timeouts |
| `v7/long_context/query_extraction.py` | extraction/expansion/fallback |
| `v7/long_context/document_retriever.py` | recall、preliminary rank和bounded materialization |
| `v7/long_context/relevance_filter.py` | bounded LLM yes/no/score filtering |
| `v7/long_context/token_limiter.py` | source/normalized/page/legacy range-aware limiter |
| `v7/long_context/context_assembler.py` | bounded context/citation assembly |
| `v7/long_context/qa_strategy.py` | prompt、conversation、without-context behavior |
| `v7/long_context/streaming.py` | event generator和terminal semantics |
| `v7/long_context/long_context_rag.py` | 端到端pipeline |
| `v7/long_context/compat.py` | `RAGManager.search()`、`SourceCode`和legacy stream facade |

### Tests 和 benchmark

| 文件/目录 | 变更 |
|---|---|
| `v7/tests/test_version_manifest.py` | commit/model/tokenizer/artifact hash |
| `v7/tests/test_owner_lifecycle.py` | lock、lease、failover、非owner open失败 |
| `v7/tests/test_query_concurrency.py` | reader pool、writer swap、generation pin |
| `v7/tests/test_stream_defer_contract.py` | 互斥、events、bounded deferred result |
| `v7/tests/test_legacy_cache_probe.py` | read-only和golden |
| `v7/tests/test_legacy_importer.py` | canonical `legacy_flat` import |
| `v7/tests/test_mineru_tree.py` | tree/page/bbox/node/unknown/raw JSON |
| `v7/tests/test_range_provenance.py` | 四类`range_origin` |
| `v7/tests/test_retrieval_contract.py` | BM25/dense/multi/NEAREST |
| `v7/tests/test_late_materialization.py` | TEMP stage无全文、materialization cap |
| `v7/tests/test_long_context_parity.py` | auto-coder parity |
| `v7/tests/test_schema_rag.py` | snapshot、routing、redaction、consistency |
| `v7/tests/test_secret_handling.py` | DB/queue/log无明文 |
| `v7/tests/test_queue_idempotency.py` | duplicate/retry/DLQ/cancel |
| `v7/tests/test_retention_gc.py` | dry-run、pin、generation fence |
| `v7/tests/test_security.py` | path/DSN/raw SQL/extension/credential attacks |
| `v7/tests/benchmarks/` | quality/performance baselines |

### Build metadata

| 文件 | 变更 |
|---|---|
| `v7/constraints-macos-arm64.txt` | target binding、MinerU/mdenseon/tachiom runtime约束 |
| `v7/VERSION_MANIFEST.json` | 完整build/model/artifact manifest |
| `v7/README.md` | lifecycle、owner模式、API、retention、rollback、不做项 |
| 根 `pyproject.toml` | 仅增加v7 optional/build dependencies；不得改变v6 DuckDB pin |

## 4.2 Flock

### 新增 headers

```text
src/include/flock/rag/catalog.hpp
src/include/flock/rag/mineru_tree.hpp
src/include/flock/rag/text_projection.hpp
src/include/flock/rag/chunker.hpp
src/include/flock/rag/embedding_backend.hpp
src/include/flock/rag/multi_vector_backend.hpp
src/include/flock/rag/search.hpp
src/include/flock/rag/scoring.hpp
src/include/flock/rag/schema_catalog.hpp
src/include/flock/rag/metrics.hpp
src/include/flock/rag/retention.hpp
src/include/flock/rag/functions.hpp
src/include/flock/registry/rag.hpp
```

职责分别对应 catalog、MinerU tree、range/line projection、chunk、mdenseon、tachiom、recall、staged ranking、schema、bounded metrics、GC和function registration。

### 新增 implementations

```text
src/rag/catalog.cpp
src/rag/migration.cpp
src/rag/mineru_tree.cpp
src/rag/text_projection.cpp
src/rag/chunker.cpp
src/rag/embedding_backend.cpp
src/rag/multi_vector_backend.cpp
src/rag/search.cpp
src/rag/scoring.cpp
src/rag/schema_catalog.cpp
src/rag/metrics.cpp
src/rag/retention.cpp
src/rag/functions.cpp
src/registry/rag.cpp
```

### 修改构建和 registry

| 文件 | 变更 |
|---|---|
| `src/include/flock/registry/registry.hpp` | 添加`RagRegistry`入口 |
| `src/registry/registry.cpp` | 注册RAG/schema functions |
| `src/CMakeLists.txt` | 编译全部RAG sources和已冻结backend |
| 根 `CMakeLists.txt` | target DuckDB校验、tachiom/mdenseon/FTS build flags |
| `.github/workflows/MainRagDistributionPipeline.yml` | target-fork v7 build、static integration和manifest gate |

### 新增测试

```text
test/sql/rag/catalog.test
test/sql/rag/mineru_tree.test
test/sql/rag/text_projection.test
test/sql/rag/range_origin.test
test/sql/rag/revision_activation.test
test/sql/rag/bm25.test
test/sql/rag/nearest_dense.test
test/sql/rag/multi_vector.test
test/sql/rag/staged_ranking.test
test/sql/rag/late_materialization.test
test/sql/rag/schema_catalog.test
test/sql/rag/retention.test
test/cpp/rag/
```

### 明确不修改

```text
现有 Config/flock_storage ownership
现有 Model/IProvider completion contract
现有 llm_rerank contract
现有 MetricsManager thread-local contract
现有 custom parser model/prompt statements
```

RAG 使用独立类型，不把上述组件扩展成 deployment runtime。

## 4.3 duckdb-pgagent

基线计划不修改 production parser/transformer。

必须在固定 target fork执行：

```text
test/sql/join/nearest/nearest_basic.test
```

并验证：

- explicit `APPROX/EXACT NEAREST N`；
- implicit top-1 engine behavior；
- distance/similarity；
- prefiltered subquery target；
- batch left-side queries；
- target Python binding中行为一致。

`src/include/duckdb/parser/peg/transformer/peg_transformer.hpp` 是 generated declaration，不手工编辑。

若 target fork现有 NEAREST regression test失败，则 Phase 1 阻塞并单独提交“production parser/transformer修复 + regression test”；不得在 Flock/Python用字符串重写掩盖。该条件性修复不属于默认 v4.1 文件改动清单。

## 4.4 duckdb-python-pgagent

实际 test/build目录名由 Phase 0核对，但已知入口的变更为：

| 文件 | 变更 |
|---|---|
| `CMakeLists.txt` | 固定DuckDB source/commit；接入Flock、FTS、tachiom等target |
| `cmake/duckdb_loader.cmake` | 显式source override，禁止floating source |
| generated extension loader | 构建生成，不手工编辑；验证`WHOLE_ARCHIVE`保留symbols |
| `pyproject.toml`/build metadata | 输出与v6分离的v7 wheel/artifact |
| Python static tests | Flock health、NEAREST、FTS、tachiom、同进程多connection/TEMP staging |
| CI/build profile | 校验engine/extension/model manifest和artifact hash |

必须验证：

```text
import duckdb
version/commit identity
flock_rag_health
EXACT NEAREST
APPROX NEAREST conformance
Flock catalog/search functions
same-process writer/readers
connection-local candidate stage
```

## 4.5 外部仓库

以下仓库首期作为只读 contract/build dependency，不计划修改：

```text
repoprompt-ce-agno
rag/KohakuRAG
bookohakurag/KohakuRAG
tachiom
duckdb-tachiom
```

如果 Phase 0 证明 duckdb-tachiom 需要修复才能与目标 DuckDB ABI工作，该修复必须成为单独 gate和固定 artifact hash，不能在 Flock中复制其实现。

# 5. Risks and migration

## 5.1 单 owner 是吞吐瓶颈和单点

首期为保证 DuckDB文件正确性，选择单 active owner service。风险是：

- 所有 deployment query/ingestion集中在一个进程；
- owner故障时 direct stream中断；
- long-running writer可能增加排队。

缓解：

- 同进程reader pool；
- writer和reader分离；
- query generation pin；
- bounded queue和timeouts；
- OS lock + lease failover；
- direct stream不自动重放；
- 多owner/immutable snapshot作为后续版本议题，不在首期暗中引入。

## 5.2 DuckDB target 和 static extension ABI

DuckDB、Flock、FTS和tachiom版本不一致可能导致无法打开文件或symbol缺失。所有构建以exact commit和artifact hash为准。旧binary不得原地打开新格式文件；rollback必须恢复对应旧备份。

## 5.3 mdenseon/tachiom未知契约

在真实API、weights、tokenizer、vector shape和artifact未升级到E1/E2前不得实现猜测adapter。tachiom gate失败不阻塞BM25/dense独立完成，但multi-vector不能标记完成。

## 5.4 PDF range误导

MinerU不保证源码行号。所有PDF引用必须携带`range_origin`；`normalized_line`只是persisted normalized projection的synthetic line。没有稳定投影时只返回page/bbox/node，不能填充伪line。

## 5.5 Secret 泄漏

Secret resolver、external adapter和LLM wrapper是主要风险点。CI必须扫描：

- queue payload；
- Postgres rows；
- DuckDB facts；
- manifest；
- logs/errors/metrics；
- stream events。

任何明文credential出现都视为release blocker。

## 5.6 Retention误删可查询generation

GC必须检查active revision、in-flight generation pin、legal hold、migration reference和dry-run generation。删除后不得让未完成query找不到materialization内容。

## 5.7 v6 → v7 migration

默认不迁移：

```text
duck_artifacts
duck_workbench_sessions
duck_operations
duck_heavy_requests
```

需要进入永久RAG的数据必须重新经过：

```text
PDF/source
  → MinerU
  → canonical JSON
  → v7 ingestion
```

## 5.8 auto-coder legacy cache migration

迁移流程：

1. Phase 0 read-only probe建立golden；
2. Phase 2 canonical importer完成并测试；
3. Phase 7 operator选择目标deployment、执行dry-run；
4. owner创建backup；
5. importer写入BUILDING revision；
6. tree/projection/chunk/vector验证；
7. required index READY；
8. active swap；
9. 旧cache保持只读不修改；
10. cutover后按runbook验证simple retrieval和LongContext。

## 5.9 v7 catalog rollback

Rollback固定为：

1. 停止新operation；
2. drain/cancel queries；
3. owner关闭connections；
4. 验证目标backup manifest/hash；
5. 恢复text/schema文件和deployment manifest；
6. 启动匹配旧build manifest的owner runtime；
7. 重新建立Postgres generation/owner state；
8. 执行health和golden query。

禁止使用旧binary对新DuckDB文件执行in-place downgrade。

# 6. Implementation order

全计划固定为八个 phase：Phase 0 到 Phase 7。

## Phase 0 — Evidence、baseline 和 contract freeze

**Workstreams：WS1，支持 WS2–WS5**

### 入口

- v3、v4 draft和两份design review可读取；
- 四仓和外部证据路径已定位；
- target DuckDB commit已知；
- legacy auto-coder cache和fixture可访问。

### 工作

1. 将v3和v4 draft标记为superseded，保存v4.1权威文档。
2. 建立review correction到v4.1 section的追踪清单。
3. 记录四仓commit、branch、dirty状态和build入口。
4. 实现最小`legacy_cache_probe.py`：
   - read-only打开；
   - 冻结schema、dimension、golden rows和simple retrieval结果；
   - 不写入旧cache。
5. 读取MinerU/KohakuRAG真实JSON、parser、fixtures，冻结：
   - node types；
   - page/bbox坐标；
   - text normalization；
   - table/image引用；
   -可否形成稳定line projection。
   - DuckRAG P19-S 为历史记录（非本机 live E2）；入树 PDF golden 为 fixture E2；Phase 0 不重跑 MinerU。
6. 读取mdenseon脚本、fixture和真实runtime，冻结weights/tokenizer/dtype/dimension/batch/thread model。
7. 读取tachiom/duckdb-tachiom source、CMake和tests，冻结artifact/index/query契约。
8. 读取auto-coder LongContext配置、prompt、events、TokenLimiter和retry默认值。
9. 读取Infinisynapse schema流程证据。
10. 在target fork运行NEAREST tests。
11. 生成包含MinerU/model/tokenizer/tachiom/FTS配置的完整manifest。
12. 冻结owner-only live-file模式和candidate TEMP staging技术契约。

### 出口

- Legacy golden baseline已生成；
- MinerU/mdenseon/tachiom required contract从E0升级到E1。MinerU 的 required contract 即 E1 contract freeze：OCI container digest 与 single-file weights sha 为 N/A（F-14：非 OCI runtime、非单文件权重），不计入 required unknown hash；range trio 验收为 fixtures E2（`v7/tests/fixtures/range_trio/`，非 live parse）；
- Option B（2026-08-30，F-14）：live MinerU execution 不是 `phase0_pass` predicate；`live_mineru_runtime` gate 保持诚实 blocked，直到 operator 在本机重配 runtime。JSON ingest contract 仍按 E1 允许实现；live parse 在 gate 解除前禁止；
- target NEAREST达到E2；
- line-range mapping规则冻结；
- static build targets明确；
- 任一required unknown未关闭时，相关backend不能进入实现。
- Canonical Phase 0 evaluator：`v7/gates/phase0_evaluator.py`。`phase0_pass` / blocker IDs / classes / structured reasons 必须与 evaluator 输出完全相等。Live NEAREST（in-repo log + target unittest binary hash/size/fields）在未验证时产生稳定 blocker `nearest_target_e2_unverified`；historical `nearest_e2.json` 不得当作 live E2。
- Final release evaluator：`v7/gates/release_evaluator.py`。`release_gate.would_pass` / `release_ready` 要求 Phase 0 **并且** Phase 1–7 **并且** E3。不得把 `phase0_pass` 直接当作 release。当前 Phase 0 下 Phase 1–7 与 E3 均为 NOT_STARTED。
- Reasons 为 `{blocker_id, blocker_class, code, details}` 闭集，禁止 free-form unmodeled reason strings。Probe 路径脱敏：错误构造时用 structured `paths=` tokenization；generic sanitizer 仅为 bounded defense-in-depth，`main()` 将未知异常映射为 `unexpected error`。

## Phase 1 — Target DuckDB/Flock Python runtime

**Workstream：WS1**

### 入口

- Phase 0 manifest冻结；
- target fork clean且commit匹配；
- Flock/tachiom/FTS构建策略明确。

### 工作

1. 将Flock编译基线切到target DuckDB fork。
2. 接入duckdb-python static/generated loader。
3. 接入已冻结的FTS和tachiom targets。
4. 验证`WHOLE_ARCHIVE`保留symbols。
5. 增加`flock_rag_health()`最小health入口。
6. 在最终Python binding运行NEAREST conformance。
7. 验证同进程writer和多个query-only readers。
8. 验证reader connection-local TEMP candidate stage。
9. 验证reader persistent DDL/DML、`ATTACH/INSTALL/LOAD`被阻止。
10. 固化wheel和extension artifact hashes。

### 出口

- 可重建的v7 binding；
- Flock health可执行；
- EXACT NEAREST可执行；
- APPROX行为已记录但不默认启用；
- 同进程connection模型通过；
- v7 artifact与v6 wheel完全分离。

> **原子落地：** target DuckDB、Flock static integration、loader、manifest和smoke tests必须一起合入。

## Phase 2 — Persistent catalog、MinerU tree、canonical importer 和 GC core

**Workstream：WS2**

### 入口

- Phase 1 runtime稳定；
- MinerU canonical contract和range规则冻结；
- Legacy probe/golden可用。

### 工作

1. 实现`flock_rag_store_meta`和文件identity校验。
2. 实现text/schema catalog versioning。
3. 实现document/revision/section/node/edge/page/table/image/metadata。
4. 实现text projection、line table和四类`range_origin`。
5. 实现MinerU JSON parser和tree invariants。
6. 实现canonical chunk/range。
7. 实现revision BUILDING/READY/ACTIVE/RETIRED/FAILED。
8. 实现raw MinerU JSON和provenance。
9. 实现正式legacy canonical importer。
10. 实现revision/index/raw JSON retention eligibility。
11. 实现in-file GC和operator dry-run plan shape。
12. 用真实MinerU/Kohaku/legacy fixtures做round-trip。

### 出口

- MinerU和legacy cache都能进入统一canonical catalog；
- PDF不依赖虚构source lines；
- Facts表不重复deployment ID；
- store identity mismatch会阻止打开；
- ingestion failure不破坏旧active revision；
- dry-run能准确列出revision/index/raw JSON候选。

> **原子落地：** catalog schema、identity、parser、projection、activation和tests必须一起合入。

## Phase 3 — BM25、dense、NEAREST、multi-vector、staged ranking

**Workstream：WS3**

### 入口

- Phase 2有READY revision/chunk；
- mdenseon/tachiom contract已冻结；
- TEMP staging在最终binding通过。

### 工作

1. 实现BM25 index和tokenizer config manifest。
2. 接入mdenseon并验证weights/tokenizer/hash。
3. 实现显式N的EXACT NEAREST query path。
4. 记录APPROX conformance，不作为默认。
5. 接入duckdb-tachiom adapter。
6. 实现ID/score-only `flock_rag_recall`。
7. 实现connection-local candidate stage。
8. 实现preliminary dedup/fusion/ranking。
9. 实现bounded text materialization。
10. 实现LLM score输入后的final rank和document reorder。
11. 实现simple `flock_rag_search` facade。
12. 实现bounded retrieval metrics。
13. 对legacy golden进行simple retrieval parity。
14. 建立EXACT/APPROX/tachiom质量与性能baseline。

### 出口

- BM25、dense和multi-vector可分别验证；
- 无full-text candidates JSON往返；
- LLM filter前只materialize bounded candidates；
- ranking deterministic；
- `llm_rerank`未被调用；
- tachiom不可用时返回明确错误。

## Phase 4 — Schema RAG、provider、secret 和 route

**Workstream：WS4**

### 入口

- Phase 3 search/ranking contract稳定；
- 目标DuckDB catalog APIs已验证；
- operator secret registry adapter可用。

### 工作

1. 实现独立schema store identity/catalog。
2. 实现snapshot/relation/column/key/relationship/comment/sample/profile。
3. 实现DuckDB `information_schema/duckdb_*` extraction。
4. 实现受控external adapter和source binding。
5. 确保adapter只从secret registry解析credential。
6. 实现list/show-create/register-table workflow。
7. 实现schema index和ranking。
8. 实现统一RAG provider contract。
9. 实现auto/schema-first/text-first/hybrid route。
10. 实现schema/kpi/active context versioning。
11. 实现redaction和snapshot generation pin。
12. 执行schema权限与泄漏测试。

### 出口

- text/schema物理store和index分离；
- Flock SQL不接收credential；
- Postgres/DuckDB只保存secret reference；
- schemaContext只在READY snapshot后更新；
- route保留provider identity和权限。

## Phase 5 — LongContextRAG parity

**Workstream：WS5**

### 入口

- Phase 3 retrieval稳定；
- Phase 4 provider/route稳定；
- auto-coder parity contract冻结。

### 工作

1. 实现query extraction/expansion。
2. 实现multi-query ID/score recall。
3. 实现preliminary rank和bounded materialization。
4. 实现bounded LLM relevance filter。
5. 将ID/LLM score写回candidate stage。
6. 实现Flock final ranking/document reorder。
7. 实现final late materialization。
8. 实现range-origin-aware TokenLimiter。
9. 实现context assembly。
10. 实现QA prompt和conversation strategy。
11. 实现`without_contexts`。
12. 实现timeout/retry/cancel。
13. 实现stream generator和compat events。
14. 实现`RAGManager.search()`/`SourceCode` facade。
15. 运行auto-coder parity suite。

### 出口

- 三阶段LongContext流程端到端完成；
- PDF synthetic lines和代码source lines正确区分；
- future完成顺序不影响结果；
- `without_contexts`、stream和cancel通过；
- 中文error fallback通过。

## Phase 6 — Owner runtime、queues、IPC、metrics sink 和 named API

**Workstreams：WS2、WS4、WS5**

### 入口

- Phase 2–5 core contracts稳定；
- Postgres metadata/queue schema冻结；
- owner-only connection model已在Phase 1验证。

### 工作

1. 创建RAG metadata、source binding、metrics和retention tables。
2. 创建三类queue和DLQ。
3. 实现global/per-deployment owner lease。
4. 实现OS file lock和generation fencing。
5. 实现`DeploymentRagStore`、writer queue和reader pools。
6. 实现Unix socket owner service/client。
7. 让ingest/index/query queues只由active owner消费。
8. 实现direct sync、direct stream和deferred三种模式。
9. 强制`stream && defer`失败。
10. 实现bounded deferred inline result和artifact reference。
11. 实现metrics bounded result和Postgres async sink。
12. 实现operation duplicate/retry/cancel/recovery。
13. 实现`use_rag_tool`、`get_rag_result`和cancel。
14. 实现backup、GC dry-run/apply operator API。
15. 验证v7 runtime不导入v6 DuckSession。
16. 执行deployment A/B、v6/v7、text/schema隔离测试。

### 出口

- 只有owner进程打开live files；
- `rag_query_requests`由owner执行；
- streaming只走IPC；
- deferred永不返回`answer_delta`；
- failover后新owner重开同一文件；
- stale owner不能提交；
- reader不写query metrics；
- secrets不进入queue、DB、log或Flock SQL。

> **原子落地：** metadata、queue、owner lease、IPC、handlers和named tool必须一起合入，避免产生无法处理或无法恢复的operation。

## Phase 7 — Production migration、benchmark、security 和 release gate

**Workstreams：WS1–WS5**

### 入口

- Phase 0–6全部通过；
- canonical legacy importer已在Phase 2完成；
- 四仓和model/artifact manifest clean；
- backup/rollback runbook已演练。

### 工作

1. 对目标deployment执行legacy import dry-run。
2. 执行pre-cutover backup。
3. 使用已有canonical importer完成生产迁移。
4. 对真实MinerU corpus执行ingestion/index。
5. 执行BM25/dense/multi/hybrid质量benchmark。
6. 执行LongContext answer、line/range和stream baseline。
7. 执行schema redaction/security suite。
8. 执行owner kill/failover、queue retry/DLQ、cancel和timeout。
9. 执行retention dry-run和受控apply。
10. 测量memory、file size、IPC、latency、restart、backup/restore。
11. 从clean checkout重建四仓和model artifacts。
12. 验证v6测试和Flock既有LLM/fusion tests无回归。
13. 生成最终release manifest、known limitations和rollback runbook。

### 出口

只有以下全部满足，v7 RAG才可标记release-ready：

- E3跨仓集成完成（E3定义为在冻结的四仓pin上完成跨仓库集成/验收；当前Phase 0不是E3）；
- exact四仓、MinerU、mdenseon、tokenizer、tachiom、FTS manifest匹配；
- owner-only live-file约束被测试证明；
- MinerU tree、legacy importer、LongContext parity通过；
- stream/defer contract通过；
- secrets和schema安全suite无高优先级问题；
- retention/GC/backup/rollback通过；
- 性能门达标；
- v6无回归；
- 文档明确列出首期不做项和所有未关闭backend限制。