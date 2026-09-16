# V10 三源研究摘要（2026-09-10）

> 编排者注：本文档是 v10-raw.md 设计的三路并行研究产物（contextpipe / poml / pgAgentOS），由只读探针产出，供 Oracle 审核与 v10 写作引用。各节带 file:line 引用可回溯。

## 一、ContextPipe 机制（论文 + Astra 实现）

### 核心机制
- **五阶段管道**：`Plan → Bind → Optimize → Execute → Feedback`。Astra 实现把 Execute 拆为 `Serialize` + 外部 provider dispatch。编排入口 `ContextPipeline::run_with_limit_policy()`：先跑 preliminary Plan/Bind 测真实 token，再 final Plan/Bind、Optimize、Serialize，返回 `PipelineRunOutput` 供外层调用 provider 并回写 Feedback（`Astra/crates/astra-turn-core/src/context/pipeline.rs:130-246`）。
- **数据模型**：`ContextSources` 目录（`sources.rs:180-260`）九字段：`statics/agent/latches/session/turn/external/emergent/working_memory/stats`，对应论文八层生命周期 tier + Feedback 统计层。`PlannedSection { kind, scope, priority, estimated_tokens }` → bind 后 `BoundSection { artifact, actual_tokens }` → optimize 后 `ContextOptimized { sections, messages, tool_schemas, cache_markers, spilled, stats }`。`section_types.rs` 定义 13+ 种 `SectionKind`（数量依论文/代码版本而异，不固定为 13；与 v10-raw §1.4 口径一致）、三级 `CacheScope { Global, Session, None }`。
- **不变式**（论文 §3.7 三 Lemma + 两 Property）：Identity/Constraints 锚定不参与重排；Never-priority section 不被清除；tool-call/result 配对由 artifact 类型保证；`PipelineStats` 是 turn 内唯一可变对象，Feedback 仅在 Execute 成功后写入；turn 级可序列化通过 `ContextSources` 只读快照实现（`pipeline/session.rs:271-290`）。
- **turn 生命周期**：`PipelineSession::run_turn()`（`pipeline/session.rs:271`）组装 sources → pipeline.run() → 外层 provider 调用 → `ContextFeedback` 写入 stats → emergent items 推入下一 turn。RecoveryState（`recovery_state.rs`）在 PTL 错误后升级 tier，连续 3 次触发 `PipelineAbort`。

### 论文中"受数据库启发"的明示点
| 论文位置 | 数据库思想 | 对应机制 |
|---|---|---|
| Abstract (line 15) | "structurally isomorphic to query execution" | 五阶段 pipeline |
| §1 (line 27) | optimizer + catalog + buffer pool + EXPLAIN | 整体架构 |
| §3.8 (line 207) | catalog statistics store | `PipelineStats` reserve 估计 |
| §4 (line 229) | `information_schema.columns` 类比 | `ContextSources` 固定 schema |
| §3.2 (line 127) | histogram-based cardinality estimation | 百分位 reserve 估计 |
| §6.1 (line 280) | shared plan cache across queries | ForkPrefix 前缀共享 |

### 实现形态（压缩/淘汰落地）
- `CompactionTier` 四档阈值 0.60/0.75/0.90（`budget.rs:14-17`），predictive tier 只升不降（`budget.rs:30-33`）。
- TrimSchemas：`prune_tool_schemas()` 按 tier 裁剪；CompactHistory：`compact_tool_results_gated()` 清旧 tool result，受 `max_clear_tokens` 熔断保护；AggressivePrune：`drop_oldest_rounds()`；Spill：`spill_oversized_sections()` 将 ≥10k token section 持久化到 `SpillBackend`，替换为 `SpillReference`，rehydrate fail-open + trace。
- 所有被 gate 阻止的 step 写入 `SkippedOptimization`（审计完整性）。
- 模块：`pipeline.rs / planner.rs / binder.rs / optimizer.rs / serializer/ / feedback.rs / pressure.rs / budget.rs / sources.rs` + `compaction_types.rs / optimize_limits.rs / recovery_state.rs / spill_backend.rs / assembly_trace.rs`。

### 论文与代码偏差
1. Execute 拆为 Serialize + 外部 dispatch（利于 shadow-pipeline 对比）。
2. 论文 8 tier vs 代码 9+ 层（statics 拆分更细）。
3. ForkPrefix（§6.1 parent-child 前缀共享）在代码中未完全对等落地。
4. 论文 §6 mandatory shadow mode；代码无统一 shadow diff checker。
5. 代码 `assembly_trace.rs` 的审计粒度超出论文 EXPLAIN ANALYZE。

### 移植到 pg-agent 的通用骨架 vs 专有耦合
**通用骨架（可直接复用）**：五阶段 pattern；压力公式 `P = (used + reserves) / limit` + tier-gated escalation；`OptimizeLimits` 独立门控 + `SkippedOptimization` 审计；`SpillBackend` trait（可对接 TOAST/temp table/FDW）；percentile digest + EMA 统计子框架；`CacheScope` 三级排序 + 边界 marker；`RecoveryState` 错误回退。

**Astra 专有耦合（需替换）**：SectionKind 中的 RuntimeIdentity/RuntimeVolatile/DeferredTools/WorkingMemory 是 Astra 运行时概念 → pg-agent 换 schema/table/query plan/extension 语境；ProviderCachePolicy/PromptCacheProtocol 绑定 LLM provider → 换 PG plan cache 策略；MemoryEntry + Memoria → 换 PG 内存表/扩展知识库；ContextChannelProvider trait 是 Astra bridge 逃逸口 → 换 extension hook；PipelineSession 的 emergent/recovery/latch 语义需重绑到 PG session/transaction 生命周期。

**结论**：ContextPipe 的"数据库灵感"本质是 **catalog + optimizer + statistics + EXPLAIN** 四件套，与 PG 内核哲学天然契合；需重新设计的是 section 目录本体和 cache marker 的 provider 协议层。

## 二、POML 提示词标记语言（论文 + 实现）

### 标签语言模型（三遍渲染）
- **Reader 层**：`poml/packages/poml/file.tsx:258` `PomlFile.react()` 将 XML 源码解析为 React 元素树，处理 `{{...}}` 模板、`<let>` 变量、`<include>` 引入。
- **IR 生成层**：`poml/packages/poml/index.ts:35` `reactRender()` 将 React 树序列化为 IR 字符串（带自定义标签的 XML）。
- **Writer 层**：`index.ts:78` `write()` 交给 `EnvironmentDispatcher`（`writer.ts:612`），按 `presentation` 分派到 MarkdownWriter/JsonWriter/YamlWriter 等，产出富文本或带 speaker 的消息列表。
- 论文 §6 三遍渲染架构（Parser → React/IR → Writer）与实现一致。

### 组件体系
- 注册机制：`component(name, options)(renderFn)` 注册到全局单例 `ComponentRegistry`（`base.tsx:714`）。
- ~37 个内置组件：基础结构（`<p>/<b>/<list>/<code>/<h>` 等，essentials.tsx）；数据（`<document>/<table>/<img>/<webpage>/<folder>/<tree>`）；意图（`<role>/<task>/<example>/<stepwise-instructions>/<output-format>`）；消息（`<system-msg>/<human-msg>/<ai-msg>/<conversation>`）。
- 组件 API：接收 `PropsBase` 派生 props（speaker/syntax/charLimit/tokenLimit 等）返回 React 元素，渲染委托 `presentation.tsx` 的 `Markup.*/Serialize.*/Free.*/MultiMedia.*`。

### 扩展性（关键问题：第三方能否加标签？）
**可以，但仅限 Node.js 侧。** 添加新标签需要：① 用 `component('NewTag', ['alias'])(props => ReactElement)` 定义；② 启动时 import 注册；③ 若产出非标准 IR 标签需在 `writer.ts` 对应 Writer 加分支；④ 更新 `assets/componentDocs.json` 与 docs 供 IDE/LSP。
**限制**：Python SDK（`python/poml/api.py`）不暴露注册 API，只调 Node CLI；全局单例注册/卸载需防状态污染。

### 论文与实现偏差
37 组件/283 属性接近论文快照；`<stylesheet>` 同时支持内嵌与外部 JSON；Python SDK 已远超论文 96 行。

### 评估：pg-agent 作为插件向 POML 添加数据库标签
- **推荐挂载点：components 层**（reader 层应保持通用解析；components 层为领域扩展设计）。
- 做法：`components/database.tsx` 注册 `<schema>/<query-result>/<migration>` 等；render 函数内部调 pg-agent API 取数，委托 `presentation.tsx` 既有 presentation 输出。
- **坑**：① Writer 耦合（新标签特殊序列化需改 writer.ts）；② ComponentRegistry 全局单例（多租户并发需谨慎）；③ Python 盲区（Python 用户看不到新标签，除非 Node 桥接）；④ IR 语义膨胀（评估是否通用 `<DataObject>+syntax` 即可）。

## 三、pgAgentOS 要素盘点

### 要素清单（6 schema）
| 要素 | 承载 | 核心表/机制 |
|---|---|---|
| 多租户身份 | `aos_auth` | `tenant`、`principal`（用户/agent/service）；`set_tenant()` 写 session `set_config` 供 RLS 消费（`sql/schemas/02_aos_auth.sql:47-58`） |
| 执行追踪 | `aos_core` | `run`（原子执行单元，`parent_run_id` 嵌套）、`event`（不可变审计）、`job`（原生异步队列，`poll_job()` + `FOR UPDATE SKIP LOCKED`）、`model`（LLM 注册表，含 context_window/endpoint/api_key_env）（`01_aos_core.sql:24-101`） |
| Persona 版本化 | `aos_persona` | `persona`（指针）+ `version`（不可变快照，含 system_prompt/model_id/params）；`get_effective_params()` 用 `model.default_params || persona.params` JSONB 合并（`03_aos_persona.sql:17-84`） |
| 工具注册表 | `aos_skills` | `skill`（定义，含 input/output JSON Schema）+ `impl`（`plpgsql`/`http`/`function` 三类）（`04_aos_skills.sql:16-73`） |
| Agent 运行时 | `aos_agent` | `agent` → `conversation` → `turn` → `step`；`memory` 为 conversation 级 KV，`store_memory()/recall_memory()` ACID 读写（`05_aos_agent.sql:16-199`） |
| RAG 知识 | `aos_rag` | `collection` → `document`（生成式 tsvector）→ `chunk`（vector(1536)+ivfflat）；`add_document()` 自动 enqueue；`search()` 向量/全文分支（`06_aos_rag.sql:16-156`） |

依赖链：auth → core → persona → skills → agent → rag，跨 schema 外键严格分层。

### 成熟度
- **设计完整**：RLS 全覆盖（逐表 tenant isolation 深至 chunk 级，`sql/rls/rls_policies.sql`）；不可变触发器保护 event/version（`sql/triggers/immutability_triggers.sql:13-20`）；job 队列 `FOR UPDATE SKIP LOCKED` 正确范式；tests 覆盖 8 核心路径。
- **半成品**：RAG embedding 仅 enqueue 无 worker；skills `impl_type='http'` 无 executor；admin role 只有列无逻辑；persona version 无 diff/rollback；`run.parent_run_id` 无 cascade 逻辑。
- **占位**：`agent.config`/`conversation.metadata` jsonb 有字段无业务；`send_message()` 的问题应记为**并发编号/幂等缺口**，撤销“3 条 DML 因而非原子”的归因：函数内语句处于调用事务中，原子性不等于并发 turn 编号与重发去重合同完备（`05_aos_agent.sql:149-170`；按 2026-09-16 第三轮复审更正）。

### 对 v10 的取舍建议
**值得融入**：① Persona → Version 不可变快照（conversation 启动记录 version_id，精确回放当时 prompt/model/params）；② `get_effective_params()` JSONB 合并（SQL 层配置分层）；③ `set_tenant()` + RLS 租户隔离（session 级 set_config 被 policy 消费）；④ run → event → job 三层执行模型；⑤ `poll_job()` 锁语义。
**应抛弃**：① RAG 整套（管道不完整，与外部 pipeline 路线冲突）；② skills impl_type='http'（DB 存 HTTP endpoint 当工具既不安全也不可观测）；③ principal.role 字段（无配套授权逻辑的虚假安全）；④ "每个 thought 都是行"的 Glass Box 叙事（无 reasoning trace 表支撑）。

### "DB 即内核"体现点
`run`+`parent_run_id` 使执行成为 SQL 可遍历 DAG；`event` 触发器强制不可变审计；`set_tenant()` 把租户上下文压缩为 session 变量被 RLS 消费；`store_memory()` 用 `ON CONFLICT DO UPDATE` 实现 ACID KV；`search()` 纯 SQL 混合检索。

## 四、v8 历史审查摘要（原 P2/nit 标签，来自 v8-dev-l4-final-verdict-2026-09-10.md）

> 历史标签不代表当前冻结规范缺口；现状以 871 行冻结 v8-dev 正文及 v10-raw §7.2 对账为准。以下 F-03/F-04/R11 已由冻结正文闭合，保留历史摘要仅供追踪，不得回流为新缺陷断言。

- F-03（历史 P2，已由冻结正文闭合）：旧摘要“grant 有效性谓词缺 slice 撤销传播”；现 v8-dev §2.1 已含撤销传播/等效检查、租户与 membership、锁/CAS 及 seal/dispatch 双门。v10 从 P0 验证新入口适用路径，不重开规范缺口。
- F-04（历史 P2，已由冻结正文闭合）：旧摘要“canonical JSON 允许多实现、golden vectors 未强制”；现 v8-dev §1.3 冻结唯一 JCS profile，§6 Conformance 10 已强制 vectors。v10 继承并增加 assembly/render 验收。
- F-07（P2）：workspace_handle 状态闭合图与正文对齐
- F-08（P2/nit）：transition_wait/sleep receipt 表行、§5.2 引用集合核对
- F-09/F-10（nit）：step 级 code 命名层级注记、§2.1 seam 清单点名 route 解析
- R11（历史摘要，已由冻结正文闭合）：v8-dev §3.1/§3.1.1/§3.1.2 已排除无 effect 的持久化 planned step，当前只验不得重新引入；§3.2.1 规则 4/5 已闭合，混合 `not_retry_eligible` 与 `budget_exhausted` 为 `FAILED_TERMINAL`，全部 terminal failure reason 为 `budget_exhausted` 才是 `FAILED_RETRY_BUDGET_EXHAUSTED`。旧屏障疑问与笼统 code 判读不再是当前残留。

v8 关键基线（供对照）：18 条不可妥协不变量（§0）；四平面 history/control/projection/workspace（§2）；双运行时 native/dsh-compat + 规范化行为 ABI（§1）；插件世代 + capability API（invariant 12/13）；assemble/fold/catalog/grant/policy 绑定 snapshot/cutoff/generation（invariant 9）。
