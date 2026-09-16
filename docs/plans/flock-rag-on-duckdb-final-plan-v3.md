> **SUPERSEDED — 2026-08-29:** This plan is replaced by `flock-rag-on-duckdb-final-plan-v4.1.md`. Do not use it for implementation.

# Oracle Plan



# Flock RAG on DuckDB — 最终执行版 v3

> **权威性声明**
>
> - 本计划吸收了最新现场核验结果，**取代**：
>   `/Users/wxl/Projects/pg-agent/prompt-exports/oracle-plan-2026-08-29-145308-flock-rag-on-duckdb-2e2b.md`
> - 独立设计审查证据：
>   `/Users/wxl/Projects/pg-agent/docs/reviews/flock-rag-on-duckdb-plan-review-2026-08-29.md`
> - Oracle 导出时应保存为新的 v3 文件，例如：
>   `/Users/wxl/Projects/pg-agent/prompt-exports/oracle-plan-2026-08-29-flock-rag-on-duckdb-v3.md`
> - 目标 DuckDB 基线：
>   `duckdb-pgagent` branch `integration/grammar-24919-20260829`，tag `duckdb-special-20260829-g1`，commit `a1f0ab1911`，当前 clean。

标记约定：

- **[已验证]**：已由现场源码、Git 状态或运行调查确认。
- **[Gate]**：必须通过对应阶段的可执行验证才能决定。
- **[设计决定]**：本计划固定的实现边界。

---

## 1. Summary

本项目不是“从零把 auto-coder 改成 DuckDB RAG”，而是把 auto-coder 现有的 **Python 管理型 DuckDB + VSS/FTS + JSONL cache + thread/queue pipeline** 下沉并统一到 Flock 和目标 DuckDB special fork 中。迁移重点是补齐 Flock 当前缺少的 RAG schema migration、事务和索引生命周期、chunk/filter/rerank 兼容实现、可观测性、单写者并发模型、静态 Python 打包及 USER_PROVIDED special repository 分发。首期 pg-agent 使用静态链接 Flock 的受控 wheel；动态 special repository 面向普通 DuckDB 客户端。Flock 的 Model/Prompt 语法优先评估迁移到目标 fork 新增的 `GrammarExtension`，但最终仍由 GrammarExtension、legacy `parse_function`、`parser_override` 的行为矩阵决定，禁止同时维护两条实际执行路径。

---

# 2. 最新现状与真实差距

## 2.1 auto-coder 当前 RAG 数据流

### 已有 DuckDB backend

**[已验证]** `auto-coder 3.0.74` 已有真实 DuckDB RAG 实现：

- 文件：
  `src/autocoder/rag/cache/local_duckdb_storage_cache.py`
- 数据库：
  `.cache/byzerai_store_duckdb.db`
- 已知字段：
  - `_id`
  - `file_path`
  - `content`
  - `raw_content`
  - `vector FLOAT[]`
  - `mtime`
- exact 相似度函数：
  `list_cosine_similarity`
- 当前默认：
  - `similarity = 0.1`
  - `top_k = 10000`
  - `dim = 1024`
- 代码安装或使用：
  - `json`
  - `fts`
  - `vss`

因此，首期持久 embedding 应以 **`FLOAT[]` 兼容优先**；不能把 `DOUBLE[]` 作为无证据默认值。

### 当前检索选择与并发

**[已验证]**

- `document_retriever.py` 仅在 `enable_hybrid_index=True` 时选择 DuckDB/Byzer backend。
- hybrid 默认关闭；迁移不能只替换该条件分支，还必须确认并迁移默认检索路径。
- 当前还有：
  - JSONL speedup cache；
  - 后台 queue thread；
  - multiprocessing parsing；
  - thread-pool insert；
  - thread lock；
  - 无 schema migration。

现有组件的逻辑链路为：

```text
源文件
  → multiprocessing 解析
  → 基于估算 token budget、靠近换行边界的字符分块
  → 后台队列 / thread-pool 插入
  → DuckDB 表与 JSONL speedup cache
  → exact/VSS/FTS 检索
  → 可选 LLM filter
  → relevance-score rerank
  → TokenLimiter 的 LLM 行范围压缩
  → List[SourceCode]
```

具体线程调度顺序、失败重试和结果稳定性仍需 Phase 0 golden test 固化。

### 过滤、重排和 API 语义

**[已验证]**

- 过滤不是 metadata DSL，而是 `ThreadPoolExecutor + LLM yes/no score`。
- rerank 是 relevance score 排序及原文档顺序恢复；没有证据证明存在 cross-encoder。
- Flock 当前 `llm_rerank` 是 listwise sliding-window 算法，**不能直接视为 auto-coder rerank parity 实现**。
- `TokenLimiter` 让 LLM 返回 1-based line ranges；这属于检索后上下文裁剪，不应与摄取 chunker 合并为一个算法。
- 公开 API：
  - `RAGManager.search() -> List[SourceCode]`
  - `stream_chat_oai` generator
- 多类错误会被转换为中文兜底文本。

迁移后：

- Flock native API 使用结构化错误；
- auto-coder compatibility adapter 在既有边界恢复原中文兜底行为；
- 不允许 Flock 核心内部吞错并返回中文字符串。

---

## 2.2 Flock 当前可复用能力与缺口

### 可复用

- `Model` 与 OpenAI/Azure/Ollama/Anthropic provider。
- `llm_embedding` 的 provider、batch、rate limit、usage limit 和 metrics 链路。
- `llm_filter` 的 LLM provider 能力，具体 parity adapter 待提取。
- `llm_rerank` 的 listwise 算法可保留为 Flock 独立能力，但不是默认兼容路径。
- `fusion_*` 可作为低级融合函数。
- SecretManager。
- Model/Prompt 配置及 `flock_storage`。

### 真实缺口

缺口不再描述为“没有 DuckDB vector/FTS 基础”，而是：

1. 没有接管 auto-coder 已有 DuckDB schema 和 index 生命周期。
2. 没有 schema migration。
3. 没有文档/chunk 导入、更新、删除和重建事务。
4. 没有对现有 chunk/filter/rerank/TokenLimiter 的 parity 实现。
5. 没有端到端 RAG search API。
6. 没有单文件多 worker 的单写 owner。
7. 没有 JSONL cache 淘汰/迁移策略。
8. 没有 RAG 指标和 index 状态可观测性。
9. 没有 static Flock wheel。
10. 没有 USER_PROVIDED repository 发布链。

另外：

- `Config::db` 是静态全局指针，新 RAG 代码不得依赖它。
- `MetricsManager` 按 `DatabaseInstance*` 建永久 registry 且使用 thread-local context，新路径需补作用域清理。
- `Model::GetModelDetailsAsJson()` 包含真实 `secret`，不能持久化到 RAG catalog、队列、日志或 release manifest。
- `fusion_rrf` 对缺失 rank 的现有处理不适合直接用于 sparse candidate union；公开函数保持兼容，RAG 使用单独 helper。

---

## 2.3 DuckDB fork、Python fork和 pg-agent

### DuckDB special fork

**[已验证]**

`duckdb-pgagent@a1f0ab1911`：

- special repository 实现及 URL template 与 upstream main 相同。
- 新增真正的：
  - `GrammarExtension`
  - `GrammarChange`
  - `active_grammar_extensions`
  - `duckdb_grammar_extensions()`
- legacy `ParserExtension`、`parse_function` 和 `AllowParserOverride` 行为仍基本同 upstream。

因此，Flock Model/Prompt grammar 的首选评估顺序改为：

1. `GrammarExtension`
2. legacy `parse_function`
3. `parser_override`
4. 必要时 compile-time compatibility bridge

最终选择仍由行为矩阵确定。

### duckdb-python fork

**[已验证]**

`duckdb-python-pgagent` 当前：

- `BUILD_EXTENSIONS=core_functions;json;parquet;icu`
- 存在 generated extension loader。
- 存在 `WHOLE_ARCHIVE` 链接机制。
- 完全没有 Flock。
- 没有 static-link/no-LOAD tests。

Flock 不能仅添加到字符串列表；必须同时：

1. 把 Flock source/extension config 加入 parent DuckDB build。
2. 确保生成 `${flock}_extension` target。
3. 让 generated loader 注册 Flock。
4. 链接 CURL、nlohmann-json 等依赖。
5. 验证连接创建后无需 `INSTALL`/`LOAD`。
6. 使用独立 build identity，不能冒充原始官方 `1.6.0.dev365` wheel。

### pg-agent

**[已验证]**

- 当前 v6 workbench 是 run-scoped 内存 DuckDB。
- 当前 pinned wheel 对 `CREATE EXTENSION REPOSITORY` 报 `ParserException`。
- 当前 runtime 会关闭 autoinstall、autoload 和 external access。
- v6 W1–W9 workbench 已实现，不应被持久 RAG owner 重写。

**[设计决定]**

- 当前临时 `DuckSessionManager` 不管理持久 RAG 文件。
- pg-agent 首期使用新的 static Flock wheel。
- 持久 RAG 使用独立 `RagShardOwner` 和独立 queue。
- 动态 special repository 不作为当前 pg-agent 的运行时依赖。

---

## 2.4 修订后的九维差距矩阵

| 维度 | auto-coder 当前实现 | Flock 当前实现 | v3 目标 |
|---|---|---|---|
| 数据模型 | DuckDB 表已有 `_id,file_path,content,raw_content,vector FLOAT[],mtime` | 无 RAG catalog | 保留兼容字段；增加 schema migration、collection/index/model metadata；额外规范化结构由 Phase 0 契约决定 |
| 索引 | 已安装/使用 VSS、FTS；具体 DDL和持久化待复测 | 无索引生命周期 | VSS/FTS 通过 Phase 1 gate 才复用；exact 永远保留；FTS失败则实现 parity lexical fallback |
| 检索 | `list_cosine_similarity`；默认 0.1/10000/1024；hybrid 条件启用 | 无端到端检索 | exact/vector/hybrid 与旧 score、threshold、排序一致；ANN 为可选后端 |
| 分块 | 估算 token budget、靠近换行的字符范围 | 无 chunking | 只实现实际旧算法；不预先引入额外 Markdown/recursive profiles |
| 持久化 | DuckDB 文件 + JSONL speedup；无 migration | `flock_storage` 仅存 Model/Prompt | 新 `flock_rag` schema；旧 DB 只读导入；JSONL退出生产路径 |
| 过滤 | ThreadPoolExecutor + LLM yes/no score | 有 `llm_filter`，无 RAG pipeline | 抽取共享 provider执行器并保持旧 filter score、并发上限和结果顺序；不增加 metadata DSL |
| 重排 | relevance score 排序与原顺序恢复；无 cross-encoder证据 | listwise sliding-window `llm_rerank` | 单独实现 auto-coder parity rerank；现有 `llm_rerank` 保持独立能力 |
| 异步/并发 | queue thread、多进程解析、thread-pool insert、thread lock | provider batching；存在全局 DB/metrics状态 | 解析可并行，所有写入汇聚单 writer；pg-agent 每 shard 单 owner；取消不留部分事务 |
| API | `RAGManager.search()->List[SourceCode]`、generator、中文兜底 | SQL LLM API，无 RAG API | 原生 result-specific SQL API + 完整 auto-coder adapter；不输出长期 NULL score列 |

---

# 3. Design

## 3.1 五个 Workstreams

| Workstream | 职责 | 主要阶段 |
|---|---|---|
| **WS1：契约、迁移与兼容** | auto-coder golden、旧 DB/JSONL 导入、`SourceCode`/generator/错误兼容、cutover | 0、3、4、7 |
| **WS2：DuckDB/Flock 运行时** | GrammarExtension 矩阵、Flock 2.0 build、显式 DB context、static wheel | 1、2 |
| **WS3：RAG 数据与检索** | schema migration、摄取、chunk、exact/VSS/FTS、filter、rerank、TokenLimiter | 3、4 |
| **WS4：分发与供应链** | USER_PROVIDED repository、签名、依赖 manifest、yank/denylist/rollback | 1、5 |
| **WS5：pg-agent 运行与验收** | 单写 owner、queue、read consistency、worker故障、全量质量/性能验收 | 6、7 |

---

## 3.2 核心设计决定

### 数据和迁移

- RAG 数据位于当前 RAG 持久 DuckDB 文件的本地 `flock_rag` schema，不写入全局 `flock_storage`。
- 迁移使用新的 side-by-side 文件，例如 `.cache/byzerai_store_flock.db`；旧 `.cache/byzerai_store_duckdb.db` 在回滚窗口内只读保留。
- 必须保留旧字段和 `FLOAT[]` 语义。
- 不预设 immutable document versioning；只有 Phase 0 证明旧 API 存在历史版本或 snapshot 语义时才增加。
- 索引是可重建派生数据，导入时重建，不复制 opaque VSS/FTS index 文件。

### VSS/FTS Gate

VSS 或 FTS 只有同时满足以下条件才能成为正式 backend：

1. 对 `a1f0ab1911` 有可构建 artifact。
2. 能执行 auto-coder 当前实际 DDL/查询。
3. 关闭并重开 DuckDB 文件后 index 可用。
4. 增量插入、删除、rebuild 行为可验证。
5. 能静态链接到 `duckdb-python-pgagent`。
6. generated loader 注册成功且无需 `LOAD`。
7. 动态发布时有明确的 dependency version/source/fingerprint。
8. 升级或坏版本时可重建/回滚。

Gate 结果：

- VSS 失败：发布 exact `list_cosine_similarity` backend，不宣称 ANN。
- FTS 失败：若 `enable_hybrid_index=True` 属于必需 parity，则实现 Flock-managed lexical fallback；否则不得宣称 hybrid 完成。
- 动态 Flock 不允许在加载时静默联网安装依赖。

### Embedding 类型

- parity 默认使用 `FLOAT[]`。
- `llm_embedding` 的现有公开返回类型继续保持 `LIST(DOUBLE)`。
- 摄取时只允许在写入边界执行一次 `DOUBLE → FLOAT` 转换；查询不得逐行 cast。
- 只有 Phase 1 证明目标 VSS/相似度函数不支持 `FLOAT[]`，或质量 gate 失败，才允许迁移到 `DOUBLE[]`；此时必须新 schema version 和全量 rebuild。

### 单写者

每个持久 RAG shard：

- 同一时刻只有一个进程 owner。
- 只有 owner 打开 live DuckDB 文件。
- 所有写入在一个 writer connection 上串行提交。
- parsing、chunking、embedding 可以并行，但 worker 只返回 staged result，不能自行打开数据库。
- 同进程并发读取仅在 Phase 1 MVCC gate 通过后启用。
- 其他进程如需读取，只能访问 checkpoint 后的不可变 snapshot，首期不支持 live replica。

### API与错误

- native SQL API 按 vector、lexical、hybrid、reranked 结果分别返回实际 score 列，不使用长期 always-NULL 占位。
- auto-coder adapter 保持 `RAGManager.search()`、`List[SourceCode]` 和 `stream_chat_oai` generator。
- native API 抛结构化错误；compatibility adapter 才转换为既有中文兜底文本。

---

## 3.3 主要新增组件

| 组件 | 类型和职责 | 生命周期 |
|---|---|---|
| `RagCatalog` | C++ service；schema migration、entries、index状态、幂等operation | 每个 `DatabaseInstance`，显式传入 context |
| `RagIngestService` | C++ service；chunk、embedding验证、事务提交 | 每次 ingest operation |
| `RagSearchService` | C++ service；exact/VSS/FTS、hybrid、稳定排序 | 每次查询 |
| `LegacyRagPipeline` | C++/adapter层；auto-coder filter、score rerank、TokenLimiter parity | 每次 search |
| `AutoCoderRagAdapter` | Python adapter；保持公开 API和generator | auto-coder RAGManager生命周期 |
| `RagShardOwner` | pg-agent Python service；lease、单writer、read pool、文件所有权 | 每 shard 一个进程 owner |
| `FlockBuildManifest` | 生成的只读兼容信息 | 每个 static/dynamic artifact |

RAG C++ 路径不得通过 `Config::db` 获取数据库；调用方必须提供当前 `ClientContext` 或 `DatabaseInstance`。

---

## 3.4 仓库依赖

```text
auto-coder 3.0.74
  └─公开 API / golden / 旧 DuckDB+JSONL importer
       ↓
flock
  ├─RAG core
  ├─GrammarExtension 或选中的兼容 parser 路径
  ├─static extension objects
  └─signed loadable artifact
       ↓                         ↓
duckdb-python-pgagent        flock_special repository
  └─generated loader             └─普通 DuckDB 客户端
       ↓
pg-agent v6
  └─RagShardOwner + PGMQ
       ↑
duckdb-pgagent@a1f0ab1911
  ├─GrammarExtension
  ├─special repository
  └─统一 ABI / URL template
```

四仓产物共享一份 compatibility manifest，至少包含：

- DuckDB commit/tag。
- engine version。
- Python package build identity。
- Flock version/build ID。
- parser mode。
- static/repository install mode。
- RAG schema version。
- embedding physical type。
- VSS/FTS backend版本。
- target platform。
- artifact SHA-256 和签名 fingerprint。

---

# 4. 八阶段执行计划

## Phase 0：契约与 golden 冻结

### 入口

- auto-coder、Flock、两个 fork 和 design review 可只读访问。
- 旧 `.cache/byzerai_store_duckdb.db` 只读打开。
- 记录所有仓库 HEAD、branch、tag、status、submodule SHA。

### 工作

1. 冻结旧 DuckDB：
   - 实际表名和完整 DDL；
   - `duckdb_indexes()`；
   - VSS/FTS 创建、更新、查询语句；
   - JSONL cache格式、失效条件和优先级。
2. 冻结九维契约：
   - chunk边界；
   - threshold/top-k；
   - hybrid开关；
   - filter yes/no score；
   - rerank score与原顺序恢复；
   - TokenLimiter的1-based line ranges；
   - `SourceCode`字段；
   - generator yield顺序；
   - 中文兜底文本。
3. 建立固定 corpus 和 mock model响应。
4. 若 auto-coder 无法运行，进入 degraded inventory：
   - 静态 AST/API/schema/test inventory；
   - 不反序列化不可信 pickle；
   - 每条结论标记 confirmed/inferred/unknown。

### 出口

- `RAG-CONTRACT-003`、`RAG-SCHEMA-003`、`RAG-API-003`、`RAG-MIGRATION-003` 完成。
- 旧 exact/hybrid/filter/rerank/chunk/error golden 可重复。
- degraded 模式允许进入 Phase 1/2，但禁止通过 Phase 4 parity 和 Phase 7 cutover。

---

## Phase 1：目标 fork 技术 Gate

### 入口

- Phase 0 至少达到 degraded 出口。
- `duckdb-pgagent@a1f0ab1911` 和 `duckdb-python-pgagent` 可构建。

### 工作

1. **Grammar 行为矩阵**
   - 优先实现最小 Model/Prompt `GrammarExtension` probe。
   - 与 legacy `parse_function`、`parser_override` 比较。
   - 遍历目标 fork实际接受的 DEFAULT/FALLBACK/STRICT设置。
   - 记录 callback计数、AST、错误、事务副作用和 `duckdb_grammar_extensions()`。
2. **VSS/FTS Gate**
   - artifact/build；
   - 实际旧 DDL；
   - persistence/reopen；
   - insert/delete/rebuild；
   - static linking；
   - dynamic dependency发布。
3. **FLOAT Gate**
   - exact score与旧 `FLOAT[]`一致；
   - 验证 index/函数无逐行 cast。
4. **Static loader Gate**
   - 把 test Flock加入 extension config和`BUILD_EXTENSIONS`；
   - generated loader实际包含 Flock；
   - no-LOAD test。
5. **并发 Gate**
   - 同进程 writer+reader；
   - 两进程竞争；
   - crash/checkpoint/reopen；
   - migration lock。
6. **special repository Gate**
   - explicit key、fingerprint、tamper、wrong version、URL template。

### 出口

关闭以下 ADR：

- `GRAMMAR-003`
- `VECTOR-FTS-003`
- `VECTOR-STORAGE-003`
- `STATIC-LINK-003`
- `CONCURRENCY-003`
- `DISTRIBUTION-003`

且：

- parser/grammar只有一条最终执行路径；
- VSS/FTS后端选择已机械确定；
- static Flock no-LOAD probe通过；
- 每 shard的reader数量已冻结，失败时为1；
- 无目标 API/CMake target未决项。

---

## Phase 2：Flock 2.0兼容和 static wheel

### 入口

- Phase 1 ADR完成。
- DuckDB ABI锁定到 `a1f0ab1911`。

### 工作

1. 按 `GRAMMAR-003`：
   - 优先迁移 Model/Prompt 到 `GrammarExtension`；
   - 若 gate不通过，保留 legacy或override；
   - 删除另一执行路径。
2. Flock CMake/CI切换到目标 commit。
3. 消除新路径对 `Config::db` 的依赖。
4. 给 metrics invocation增加 RAII清理。
5. 增加不含 secret 的 model identity。
6. 抽取 shared embedding executor，但保持 `llm_embedding`兼容。
7. 将 Flock加入真实 Python fork：
   - extension config；
   - build list；
   - generated loader；
   - whole-archive；
   - CURL/JSON依赖。
8. 生成新的 custom wheel identity和 build manifest。
9. 更新 `DuckSessionManager` 的版本检查，不再仅硬编码官方 wheel版本。
10. workbench validator拒绝所有网络型 `llm_*` 和 `flock_rag_*` 任意 SQL调用。

### 出口

- loadable Flock在目标 CLI加载成功。
- static wheel连接后无需 `INSTALL`/`LOAD` 即可使用 Flock。
- `duckdb_grammar_extensions()` 在采用 GrammarExtension 时显示 Flock。
- 原有 Model/Prompt、LLM、fusion、metrics回归通过。
- pg-agent既有 W1–W9 workbench suite在custom wheel上全部重跑通过。
- static wheel不会被误标为原始 `1.6.0.dev365` artifact。

本阶段的 Flock grammar、CMake、Python loader、target SHA和CI必须原子验证。

---

## Phase 3：RAG schema、导入与摄取

### 入口

- Phase 2通过。
- Phase 0 schema/API契约已冻结。
- `FLOAT[]`和VSS/FTS决策已完成。

### 工作

1. 创建本地 `flock_rag` schema和 migration table。
2. 至少保留旧字段：
   `_id,file_path,content,raw_content,vector,mtime`。
3. 额外 collection/model/index字段放在 catalog表中；除非 Phase 0证明需要，不引入不可见的 immutable document history。
4. 实现旧 DB只读批量 importer。
5. JSONL只用于迁移校验；迁移完成后不再作为事实源。
6. 将旧 chunk算法下沉到Flock。
7. shared embedding executor写入 `FLOAT[]`，校验：
   - count；
   - dimension=1024或collection配置；
   - finite值；
   - cosine零向量。
8. ingest顺序：
   - DB事务外解析/chunk/embedding；
   - staged result进入单writer；
   - 一个事务写数据和index状态。
9. 实现 request ID幂等和 index状态：
   `BUILDING/READY/STALE/FAILED`。

### 出口

- 旧/新记录数、字段、content hash、vector dimension一致。
- exact score绝对误差不超过 `1e-6`。
- close/reopen后数据和index catalog一致。
- provider、chunk或DB失败不留下部分行。
- 重复导入幂等。
- secret、DSN和原始Authorization不进入表、错误或metrics。
- schema migration可重复执行。

---

## Phase 4：检索、filter、rerank 与 API parity

### 入口

- Phase 3持久化和exact基础通过。
- Phase 0不再处于 degraded状态，或本阶段只能标记 provisional。

### 工作

1. 实现 exact `list_cosine_similarity` parity：
   - 默认 similarity `0.1`；
   - top_k `10000`；
   - dim `1024`；
   - 稳定 tie-break。
2. 按 Phase 1决策接入VSS。
3. hybrid默认仍关闭；启用时接入通过gate的FTS或Flock lexical fallback。
4. 实现旧 LLM filter：
   - bounded concurrency；
   - yes/no score；
   - 输入和输出顺序兼容。
5. 实现旧 relevance-score rerank和原顺序恢复。
   - 不将现有 `llm_rerank`滑动窗口替代此逻辑。
   - 不虚构 cross-encoder或`rerank_score`。
6. 实现 TokenLimiter的1-based line ranges parity。
7. 增加 native result-specific SQL API。
8. 实现 `AutoCoderRagAdapter`：
   - `RAGManager.search()`；
   - `List[SourceCode]`；
   - `stream_chat_oai` generator；
   - 中文兜底错误。
9. 移除生产路径对旧 backend和JSONL cache的依赖。

### 出口

- 九维差距逐项关闭。
- exact fixture的ID和排序完全一致。
- hybrid、filter、rerank、TokenLimiter满足golden。
- vector、lexical、hybrid、reranked API无长期NULL score列。
- VSS若启用：
  - recall@100 ≥ 0.99；
  - nDCG@10相对下降 ≤ 0.5%；
  - 100k chunk下p95至少优于exact 2倍；
  - 否则保持exact。
- auto-coder公开API、generator和错误兼容测试全部通过。

---

## Phase 5：USER_PROVIDED special repository

### 入口

- Phase 2 loadable artifact稳定。
- Phase 1 special repository和依赖gate通过。
- 兼容 manifest冻结。

### 工作

1. 建立 `flock_special` HTTPS prefix。
2. 使用显式 pinned RSA-2048 public key。
3. 通过 target fork：
   - `ExtensionUrlTemplate`
   - `ExtensionFinalizeUrlTemplate`
   生成实际路径。
4. 发布 Flock及通过gate的VSS/FTS依赖，或明确发布无外部依赖的exact/lexical variant。
5. 生成 signed release manifest。
6. 实施：
   - immutable artifact；
   - key rotation overlap；
   - yank；
   - signed denylist；
   - known-good pin；
   - static/dynamic rollback。
7. ordinary clean client验证：
   `CREATE EXTENSION REPOSITORY → INSTALL → LOAD`。
8. community和legacy custom endpoint不再作为vNext默认。

### 出口

- clean target CLI可由显式key安装并加载。
- install info显示：
  - `REPOSITORY`
  - `USER_PROVIDED`
  - `flock_special`
  - 正确fingerprint。
- wrong key、tamper、origin mismatch、wrong ABI、yanked version均失败。
- 坏版本回滚runbook实际演练。
- 当前 pg-agent测试不依赖动态仓库。

---

## Phase 6：pg-agent 持久 RAG owner

### 入口

- Phase 2 static wheel通过。
- Phase 3/4 RAG core可用。
- `CONCURRENCY-003`关闭。

### 工作

1. 新增独立 `flock_rag_requests` queue，不复用临时工作台的持久连接。
2. 新增 `RagShardOwner`：
   - PostgreSQL advisory lock；
   - owner generation；
   - lease/heartbeat；
   - 单writer connection；
   - gated同进程read pool。
3. 默认一个 `default` shard；collection到shard映射创建后不可在线改变。
4. 所有 auto-coder/pg-agent写请求经owner提交。
5. parsing/embedding worker不得打开RAG文件。
6. read request等待 `required_commit_seq` 可见。
7. 失去lock、lease或generation时：
   - 停止领取；
   - 中断未提交事务；
   - 关闭所有DuckDB连接；
   - fail closed。
8. 新增专用 enqueue-only RAG tools。
9. 继续保持：
   - 临时 `DuckSessionManager`；
   - `duck_heavy_requests`；
   - workbench artifacts
   与 persistent RAG完全隔离。

### 出口

- 同一 shard任何时刻只有一个进程打开 live 文件。
- 双worker竞争只有一个owner成功。
- 旧generation无法在failover后commit。
- duplicate/out-of-order operation不重复写入。
- read-after-write满足commit sequence。
- workbench SQL不能调用Flock provider或persistent RAG API。
- static wheel不触发扩展下载。
- owner crash/restart/checkpoint/reopen测试通过。

---

## Phase 7：迁移、切换与最终验收

### 入口

- Phase 0不再degraded。
- Phase 3–6通过。
- static/dynamic rollback均演练完成。

### 工作

1. 全量导入旧 DuckDB。
2. 重建VSS/FTS或fallback索引。
3. shadow search比较新旧结果。
4. 暂停旧写入，导入final delta。
5. 切换 `RAGManager` 到新adapter。
6. 旧 DB只读保留。
7. post-cutover mutation写入中立journal。
8. 跑完整：
   - correctness；
   - quality；
   - performance；
   - concurrency；
   - security；
   - bad-release；
   - crash/restart矩阵。
9. design agent依据review文件独立复核。

### 出口

- auto-coder九维行为全部由Flock/DuckDB承载。
- 旧 backend和JSONL cache不在生产读写路径。
- exact/hybrid/filter/rerank/token limiter达到冻结golden。
- pg-agent满足单owner约束。
- static wheel和special repo产物均可回滚。
- mutation journal可将cutover后的写入重放回旧接口。
- 旧 DB仅在回滚窗口结束后才允许归档或删除。

---

# 5. 关键文件影响

## 5.1 auto-coder

### 已确定

- `src/autocoder/rag/cache/local_duckdb_storage_cache.py`
  - 提取旧 schema/index/import契约。
  - 最终由Flock adapter替代生产存储操作。
- `src/autocoder/rag/document_retriever.py`
  - 默认与hybrid分支统一切向Flock。
  - 保持 `enable_hybrid_index` 默认和语义。
- `src/autocoder/common/rag_manager/**`
  - Phase 0定位 `RAGManager.search()`、`stream_chat_oai`、`SourceCode`、TokenLimiter和错误兜底的实际文件。
  - 不保留长期双backend选择。

### 新增

- auto-coder侧 Flock adapter。
- 旧 DuckDB/JSONL importer，仅作为迁移工具。

---

## 5.2 Flock

### 现有关键文件

- `src/flock_extension.cpp`
- `src/include/flock_extension.hpp`
  - 按 `GRAMMAR-003`采用 GrammarExtension、legacy或override之一。
- `src/custom_parser/query_parser.cpp`
- `src/include/flock/custom_parser/query_statements.hpp`
  - 保持 Model/Prompt语义；清理孤立 `CreateDuckStatement`。
- `src/core/config/config.cpp`
- `src/include/flock/core/config.hpp`
  - 新RAG显式context；不依赖`Config::db`。
- `src/functions/scalar/llm_embedding/implementation.cpp`
- `src/include/flock/functions/scalar/llm_embedding.hpp`
  - 抽取shared embedding executor。
- `src/functions/aggregate/llm_rerank/implementation.cpp`
  - 只保留现有listwise能力；不能替代auto-coder parity rerank。
- `src/functions/scalar/fusion_rrf/implementation.cpp`
  - 公开语义保持；RAG sparse fusion使用独立helper。
- `src/model_manager/model.cpp`
- `src/include/flock/model_manager/{model,repository}.hpp`
  - non-secret identity；显式DB lookup。
- `src/include/flock/metrics/manager.hpp`
- `src/metrics/metrics.cpp`
  - RAII context和RAG metrics。
- `src/registry/{registry,scalar,aggregate}.cpp`
  - 注册新增RAG函数。
- `CMakeLists.txt`
- `Makefile`
- `.github/workflows/MainDistributionPipeline.yml`
  - vNext不再使用显式DuckDB `v1.5.4` CI。
- `.gitmodules`
  - 仅描述跟踪branch，不能作为实际build SHA证据。

### 计划新增

- `src/include/flock/rag/types.hpp`
- `src/include/flock/rag/catalog.hpp`
- `src/rag/catalog.cpp`
- `src/include/flock/rag/ingest.hpp`
- `src/rag/ingest.cpp`
- `src/include/flock/rag/search.hpp`
- `src/rag/search.cpp`
- `src/include/flock/rag/legacy_pipeline.hpp`
- `src/rag/legacy_pipeline.cpp`
- `src/functions/table/rag.cpp`
- `src/include/flock/registry/table.hpp`
- `src/registry/table.cpp`

仅在 Gate 选中时新增 VSS/FTS adapter；否则实现 exact/lexical fallback，不创建空抽象层。

---

## 5.3 DuckDB fork

目标仓库：

- `/Users/wxl/Projects/duckdb-pgagent`

关键类型：

- `GrammarExtension`
- `GrammarChange`
- `active_grammar_extensions`
- `duckdb_grammar_extensions()`
- legacy `ParserExtension`
- `AllowParserOverride`
- `ExtensionRepositoryManager`
- `ExtensionHelper`

默认策略：

- 优先只新增Flock grammar/extension regression tests。
- special repository和URL template与upstream一致，默认不修改。
- 只有可复现的fork regression阻塞Phase 1时才修改DuckDB源码，并与回归测试原子提交。
- Phase 0证据包必须记录这些类型的实际文件路径，不能凭名称推断。

---

## 5.4 duckdb-python fork

关键文件：

- `/Users/wxl/Projects/duckdb-python-pgagent/CMakeLists.txt`
- `/Users/wxl/Projects/duckdb-python-pgagent/cmake/duckdb_loader.cmake`
- 实际 extension config和wheel version文件，路径在Phase 0固定。

修改：

- Flock加入parent DuckDB extension config。
- `BUILD_EXTENSIONS`加入Flock及通过Gate的静态依赖。
- generated loader注册Flock。
- `WHOLE_ARCHIVE`保留。
- 链接Flock依赖。
- 增加 no-LOAD/static grammar/RAG smoke tests。
- 生成custom wheel build identity。

---

## 5.5 pg-agent

### 修改

- `v6/session_durability/duckdb_runtime.py`
  - custom wheel manifest检查；
  - 保持内存workbench，不接管持久RAG。
- `v6/dialect_guardrails/duckdb_validation.py`
  - 拒绝所有可触发provider网络的Flock函数和`flock_rag_*`。
- `v6/load.py`
  - 追加RAG metadata/queue/tool SQL；
  - 保持 inherited文件只读和COMMENT后refresh。
- `v6/queue_bridge/duckdb_processor.py`
  - 不直接打开RAG文件；只组合独立RAG processor入口。
- `v6/README.md`
  - 区分temporary workbench与persistent RAG owner。

### 新增

- `v6/rag_bridge/rag_metadata.sql`
- `v6/rag_bridge/rag_queue.sql`
- `v6/rag_bridge/rag_tools.sql`
- `v6/rag_bridge/rag_database.py`
- `v6/rag_bridge/rag_processor.py`
- `v6/rag_bridge/rag_errors.py`

---

# 6. 修订后的高风险

| 风险 | 控制措施 |
|---|---|
| GrammarExtension语义与旧Model/Prompt不一致 | Phase 1三路径行为矩阵；只允许一条执行路径；用`duckdb_grammar_extensions()`验收 |
| VSS/FTS在target fork不可发布或不可持久化 | 完整artifact/reopen/static-link Gate；VSS失败用exact，FTS失败实现lexical parity fallback |
| static wheel与当前官方wheel身份混淆 | custom package/build identity和manifest；重新跑v6 W1–W9 |
| 多进程直接打开同一RAG文件 | 每shard advisory lock + generation + lease + 单owner；其他进程禁止打开 |
| Flock CURL绕过DuckDB external access | workbench validator denylist；provider只允许专用RAG owner调用 |
| 已签名但逻辑错误的版本 | immutable artifact、yank、signed denylist、known-good pin、进程重启回滚 |
| auto-coder无法运行 | degraded inventory可推进机制工作，但阻止Phase 4正式parity及Phase 7切换 |
| FLOAT精度或index兼容问题 | 旧FLOAT为默认；一次性边界cast；DOUBLE只能由量化Gate批准 |
| `Config::db`和metrics生命周期泄漏 | 新RAG显式context；RAII metrics；多DB/load-unload测试 |
| JSONL与DuckDB形成长期双事实源 | JSONL只用于导入校验；cutover后从生产路径删除 |
| rerank错误复用 | auto-coder score-rerank单独实现；Flock listwise rerank保持独立 |
| 回滚丢失cutover后写入 | 中立mutation journal；旧DB只读保留至回滚窗口结束 |

---

# 7. 立即下一步：只读盘点与验证

在任何源码修改前，按以下顺序执行：

1. **登记权威文档**
   - 读取design review。
   - 将旧Oracle计划标记为superseded。
   - 记录本v3导出路径。

2. **锁定仓库身份**
   - auto-coder、Flock、DuckDB fork、Python fork分别记录：
     - branch；
     - HEAD；
     - tag；
     - clean状态；
     - submodule SHA。
   - 特别确认Flock submodule实际SHA，不从`.gitmodules branch=main`推断。

3. **只读检查旧RAG数据库**
   - 以read-only方式打开 `.cache/byzerai_store_duckdb.db`。
   - 导出：
     - schema；
     - table names；
     - indexes；
     - extension状态；
     - vector维度分布；
     - row count；
     - NULL/NaN/重复ID情况。
   - 不执行index rebuild或写入。

4. **完整追踪auto-coder调用**
   - `enable_hybrid_index`全部引用。
   - `similarity/top_k/dim`默认值传播。
   - VSS/FTS DDL和query。
   - JSONL cache读写优先级。
   - chunk/filter/rerank/TokenLimiter实际文件。
   - `RAGManager.search`和`stream_chat_oai`异常路径。

5. **定位目标fork Grammar API**
   - 记录 `GrammarExtension`、`GrammarChange`、注册点、系统表和测试目录的精确路径。
   - 建立Model/Prompt行为矩阵用例，不改实现。

6. **检查真实Python static build**
   - 确认Flock应如何进入extension config。
   - 确认`${ext}_extension` target生成规则。
   - 确认generated loader输出位置。
   - 确认wheel version/build metadata来源。

7. **产出Phase 0证据包**
   - 九维契约表。
   - old DB schema/index快照。
   - parser/grammar矩阵。
   - VSS/FTS gate清单。
   - static-link gate清单。
   - 精确touched-files列表。
   - normal/degraded状态。

---

# 8. 首期明确不做

1. 当前官方 `duckdb==1.6.0.dev365` wheel中的动态 special repository安装。
2. 多进程直接读写同一个live RAG DuckDB文件。
3. 新的 `CREATE RAG`、`SEARCH RAG`自定义语法。
4. auto-coder原实现没有的metadata filter DSL。
5. 无证据的cross-encoder rerank。
6. 额外Markdown/recursive chunker profiles。
7. 未通过Gate的HNSW/IVF/VSS声明。
8. 永久保留JSONL和DuckDB双写。
9. 在线re-shard、跨region复制和live read replica。
10. 完整WASM RAG及Linux/Windows发布矩阵。
11. 模型任意SQL直接调用Flock provider或persistent RAG。
12. community或legacy `custom_extension_repository` 作为vNext默认分发路径。