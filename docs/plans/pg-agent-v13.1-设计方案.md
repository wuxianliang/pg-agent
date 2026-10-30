# pg-agent v13.1 设计方案：Postgres 底座 · DuckDB 数据工作台 · Jev 决策路由

> 版本：v13.1（规划） ｜ 调研与撰写日期：2026-09-21 ｜ 交付物：设计方案文档（技术栈由本方案选定）

## 执行摘要

v13.1 的核心命题是：**pg-agent 不再是一个"什么都自己干"的单体 agent，而是一个由 PostgreSQL 承载状态与记忆、由 Jev 负责任务分流、由三个专业化工作台（数据 / 代码 / 文本）负责执行的系统**。本方案给出的结论是：

- **技术栈选定 Python 3.12+ 为主线**（PostgreSQL 用 `asyncpg`/`psycopg3`，DuckDB 用官方 `duckdb` Python 包，Jev 用 `typesafe-sdk`），前端如需编辑器界面再引入 TypeScript 子项目，不让前端技术栈反向决定后端架构。
- **PostgreSQL 17 作为唯一事实源（single source of truth）**：会话、消息、工作台运行记录、产出物登记、决策审计、向量记忆全部入库。这一路线有成熟先例——Letta 用 Postgres + pgvector 做一等记忆子系统，LangGraph 用 Postgres checkpointer 做会话持久化，Tiger Data 的 Agentic Postgres 则把"分叉、检索、记忆"直接做成了数据库原语 ([InfoQ](https://www.infoq.com/news/2025/12/agentic-postgres-fast-forking/), [VokoForge](https://github.com/VokoForge/ai-insights/blob/main/posts/day-13-frameworks-deep-review.en.md))。
- **DuckDB 以"双模"接入**：默认走**独立嵌入式实例**（每会话一个 DuckDB 连接，隔离性好、可直读 CSV/Parquet/JSON/数据湖）；在同一个 Postgres 实例上同时部署 **pg_duckdb 1.1.x** 扩展，用于对底座自身业务数据的 OLAP 加速 ([MotherDuck](https://motherduck.com/blog/pgduckdb-beta-release-duckdb-postgres/), [Baremon](https://www.baremon.eu/pg-duckdb-postgresql-query-execution/))。
- **Jev 只做"判断"，不做"生成"**：路由层抽象为 `DecisionProvider` 接口，首选实现是 TypeSafe 官方 API（`POST https://api.typesafe.ai/v1/systemone`，模型 `jev-1.13.0`），一次调用并行返回工作台选择（Choice）、澄清需求（Noul）、风险与复杂度（Score），全部带校准概率 ([awesome-jev](https://github.com/valentynkit/awesome-jev-typesafe), [MarkTechPost](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/))。按日 10 万次路由、每次约 700 input tokens 测算，**月成本约 $8.8**，路由成本在架构上可忽略。
- **落地节奏**：v13.1 分四个里程碑（M1 底座与决策接口、M2 数据工作台、M3 代码与文本工作台、M4 路由治理与 shadow 校准），建议先以 shadow 模式运行 Jev 路由一周以上再切换为真实分流——这是 hermes-jev-skills 项目验证过的稳妥路径 ([GitHub](https://github.com/kerpopule/hermes-jev-skills))。

---

## 1. 调研结论：每个设计决策都已有生态先例

在进入方案之前，先把本轮调查的关键事实钉死——v13.1 的每一块积木都不是凭空发明，而是对 2025–2026 年已验证模式的组合。

### 1.1 Jev 是什么，能力边界在哪里

Jev 是 TypeSafe AI（旧金山，前 OpenAI 研究员、RLHF 共同发明人 Diogo Almeida 创立，2026 年 9 月 15 日出 stealth，DCVC 领投 4000 万美元种子轮）发布的第一个 **System One 模型**：不生成任何文本，只返回带校准概率的类型化决策 ([ntorres.dev](https://ntorres.dev/blog/jev-typesafe-system-one-model), [Universal Digital Assistant](https://universaldigitalassistant.com/launches/typesafe-ai-jev/))。它的 API 契约对 pg-agent 的路由场景几乎是量身定做的：

| 属性 | 事实 | 对 v13.1 的意义 |
|---|---|---|
| 端点 | `POST https://api.typesafe.ai/v1/systemone`，请求体为 `model` + `state` + `questions` ([awesome-jev](https://github.com/valentynkit/awesome-jev-typesafe)) | 一个端点承载全部路由判断 |
| 三种原语 | **Choice**（≤255 个选项）、**Score**（2–10 级有序量表）、**Noul**（是/否概率） ([apidog](https://apidog.com/blog/what-is-jev/)) | Choice 选工作台，Noul 判澄清/完成，Score 估风险与复杂度 |
| 并行求值 | 同一请求内所有问题针对同一 state 并行、独立评分，加问题几乎不增加延迟 ([MarkTechPost](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/)) | 一次调用拿齐路由所需的全部信号 |
| 延迟与价格 | 厂商报告 70–500ms 端到端；$0.042/百万 input tokens，output 免费 ([atomicbot](https://atomicbot.ai/blog/what-is-jev)) | 每次任务进入多花 <0.5s、不到千分之一美元 |
| 上下文 | 单请求 64k tokens；state + 最长单个问题 ≤32k ([atomicbot](https://atomicbot.ai/blog/what-is-jev)) | 任务描述 + 附件清单 + 会话摘要远用不满 |
| 接入路径 | 官方 waitlist；OpenRouter（`/api/alpha/decisions`，模型 `typesafe/jev-1.13`）、Vercel AI Gateway、Cloudflare Workers AI 均可绕过 waitlist ([typesafe-jev-examples](https://github.com/rajivkuriakose/typesafe-jev-examples), [awesome-jev](https://github.com/valentynkit/awesome-jev-typesafe)) | v13.1 开发期可先走 OpenRouter |
| SDK | Python `typesafe-sdk`（3.10+）、JS `@typesafe-ai/sdk`；LangChain 有 `langchain-typesafe`，内置 `ModelRouterMiddleware` ([MarkTechPost](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/), [atomicbot](https://atomicbot.ai/blog/what-is-jev)) | 接口形态有官方参照 |

必须钉死的边界有三条。其一，**Jev 不能生成文本**——它不能替 agent 写澄清问题、不能写代码，所以"澄清问题的措辞"仍由主 LLM 生成，Jev 只给出"该不该澄清"的概率 ([DataCamp](https://www.datacamp.com/blog/system-one-models-jev))。其二，**"不会幻觉"只保证不出 schema，不保证判断正确**——校准概率的意义在于可以设阈值：高于阈值自动执行，低于阈值降级或反问 ([apidog](https://apidog.com/blog/what-is-jev/), [explainx](https://explainx.ai/blog/typesafe-ai-jev-system-one-models-launch-2026))。其三，官方性能数字（比 LLM 快 20–200 倍、便宜 40–400 倍）均为厂商自报，第三方独立复测有限，v13.1 应以自己的 shadow 数据为准 ([explainx](https://explainx.ai/blog/typesafe-ai-jev-system-one-models-launch-2026))。

生态中已经出现与 v13.1 设想几乎同构的先例：**jev-agent-skill-router** 用 Jev 的类型化、带置信度决策来路由 agent 的技能选择，弱匹配时拒绝猜测；**hermes-jev-skills** 用 Jev 做逐轮模型路由（约 0.4s/轮）、记忆过滤、技能选择（377 个技能约 2.8s），并且内置 shadow 模式——"先记录决策日志、不实际切换，观察一天再启用" ([awesome-jev](https://github.com/yibie/awesome-jev), [GitHub](https://github.com/kerpopule/hermes-jev-skills))。这两个项目直接验证了"Jev 判断启用哪个工作台"的可行性，其 shadow 模式和隐私脱敏做法（只发任务文本、遮蔽邮箱/电话/token、日志只存决策不存 prompt）将被 v13.1 直接吸收 ([GitHub](https://github.com/kerpopule/hermes-jev-skills))。

### 1.2 Postgres 作为 agent 底座已是被验证的架构

把 agent 的状态、记忆、审计全部放进 Postgres 不是激进选择，而是 2025–2026 年的主流收敛方向。工程评审显示：LangGraph 提供官方 Postgres checkpointer 做会话状态持久化；Letta（前 MemGPT）直接把 core/archival/recall 三层记忆建在 Postgres + pgvector 上，并因此被评价为"唯一把记忆当一等子系统的框架" ([VokoForge](https://github.com/VokoForge/ai-insights/blob/main/posts/day-13-frameworks-deep-review.en.md), [Medium](https://medium.com/@alonjamanjeetsinh77/building-infinite-memory-agents-a-master-guide-to-langgraph-langmem-and-postgres-05b3cabd689b))。Tiger Data 在 2025 年 10 月发布的 Agentic Postgres 更进一步：基于 Fluid Storage 的**零拷贝秒级分叉**让"每个 agent 拿到一份生产数据的隔离副本做实验"成为标准动作，并把混合检索（pgvectorscale 向量 + pg_textsearch 的 BM25）和记忆 API 做成了数据库内建原语 ([InfoQ](https://www.infoq.com/news/2025/12/agentic-postgres-fast-forking/), [Tiger Data](https://www.tigerdata.com/blog/postgres-for-agents))。

对 v13.1 的直接启示有两条。第一，**"底座 = 状态 + 记忆 + 审计 + 队列"四件事可以共用一个 Postgres**，不需要为 agent 单独引入向量库或消息队列（pgvector 覆盖语义检索，`LISTEN/NOTIFY` 或 `FOR UPDATE SKIP LOCKED` 覆盖轻量任务队列）。第二，**分叉（fork）是"安全实验"的终极答案，但属于 v13.2+ 的增强项**——自建 Postgres 没有 Fluid Storage，v13.1 先用 schema 级隔离（每会话独立 schema 或行级安全）实现"够用的隔离"，把数据库分叉写进路线图而非本期范围 ([dev.to](https://dev.to/tigerdata/introducing-agentic-postgres-the-first-free-database-built-for-agents-50i7))。

### 1.3 DuckDB 与 Postgres 的两种结合方式都已生产可用

DuckDB 侧的关键事实是**有两条官方级集成路径，且不互斥**。路径一：**嵌入式 DuckDB**——Python 进程内直接 `import duckdb`，无服务器、零依赖，文件即表（`read_csv` / `read_parquet` / `read_json` 直接查询，含 S3 远程文件），非常适合 agent 的探索式分析循环——text-to-SQL agent 很少一次写对查询，需要"看 schema → 试探 → 报错 → 修正"的快速迭代，DuckDB 的进程内特性让这个循环没有网络开销 ([MotherDuck](https://motherduck.com/blog/langchain-sql-agent-duckdb-motherduck/), [Fastero](https://fastero.com/blog/connect-duckdb-to-dashboards-and-ai-agents))。路径二：**pg_duckdb 扩展**（DuckDB Labs、MotherDuck、Hydra、Neon、Microsoft 联合项目），把 DuckDB 的列式向量引擎嵌进 Postgres 后端，1.0 起视为生产可用，1.1.x 支持 RLS 与视图权限检查；它按语句级通过 planner hook 决定路由，大扫描 + 强聚合走 DuckDB，点查走 Postgres，还能在一条 SQL 里 join 本地表和 S3 上的 Parquet ([MotherDuck](https://motherduck.com/blog/pgduckdb-beta-release-duckdb-postgres/), [Baremon](https://www.baremon.eu/pg-duckdb-postgresql-query-execution/))。

边界也要钉死：DuckDB 是**单机纵向扩展**的分析引擎，不是分布式系统，没有内建多租户和行级安全；单文件同时只允许一个进程持有写锁，标准模式是写 staging 文件再原子改名 ([Basedash](https://www.basedash.com/blog/duckdb-for-bi-when-single-node-analytics-beats-a-cloud-warehouse), [Dataskew](https://dataskew.io/blog/metabase-duckdb-local-analytics/))。pg_duckdb 侧也有已知代价：PostgreSQL 行转 DuckDB 向量有转换税，大结果集（`SELECT *`）会被全量物化再返回，跨界点必须在目标负载上实测 ([Baremon](https://www.baremon.eu/pg-duckdb-postgresql-query-execution/))。这些约束决定了 v13.1 的数据工作台设计：**DuckDB 负责"算"，Postgres 负责"管"**，产出物一律回写 Postgres 登记。

### 1.4 代码执行沙箱与文本工作台的选型空间

代码工作台的执行层，2026 年的选项已经收敛成一条清晰的谱系：**E2B**（Firecracker microVM，硬件级隔离，快照冷启动 5–30ms，Apache 2.0 可自托管，是被引用最多的"让 agent 跑代码"模式）；**Daytona**（Docker 容器，持久工作区，适合跨会话累积环境的项目型任务，但 2026 年 6 月起生产代码库闭源）；**Modal**（gVisor 容器，带 GPU） ([PkgPulse](https://www.pkgpulse.com/guides/e2b-vs-daytona-vs-webcontainers-ai-agent-sandboxes-2026), [Northflank](https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes), [Modal](https://modal.com/resources/best-code-execution-sandboxes-mcp-servers))。对 v13.1 的判断是：**本地受限子进程（无网络 namespace + 资源限额）作为默认实现，E2B 作为不可信代码的升级实现**，两者收敛在同一个 `SandboxProvider` 接口后面。

文本工作台没有同等成熟的"agent 原生"标准件，但编辑器内核的选型空间清晰：块级文档模型（Notion 风格）对应 BlockNote，高度自定义文档模型对应 Lexical，ProseMirror/TipTap 是生态最大的 headless 基础，Markdown 优先则 Milkdown ([eddyter](https://eddyter.com/blogs/best-rich-text-editor-for-ai-agents-2026))。v13.1 的设计要点是**文档模型先于编辑器**：把文档存为 Postgres 里的版本化 JSONB 块结构，编辑器只是这个模型的视图，agent 对文档的每次改写都产生一个可 diff、可回滚的新版本。

---

## 2. 技术栈选型

用户明确"还没定型，方案里帮我选"。选择逻辑围绕一个中心：**pg-agent 的重心在数据与决策，不在前端**。

| 层 | 选型 | 理由与备选 |
|---|---|---|
| 主语言 | **Python 3.12+**（`asyncpg` / `psycopg3` + `duckdb` + `typesafe-sdk`） | DuckDB 的一等公民是 Python；`typesafe-sdk` 要求 Python 3.10+ ([MarkTechPost](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/))；数据分析生态（pandas/Arrow）零成本可用。备选 TypeScript 仅在"编辑器即产品"时才成立 |
| 数据库 | **PostgreSQL 17** + `pgvector`（语义记忆）+ `pg_duckdb 1.1.x`（底座数据 OLAP，可选开启） | pg_duckdb 官方镜像 `pgduckdb/pgduckdb:18-v1.1.1` 可一键起 ([duckdblab](https://duckdblab.org/en/post/pg-duckdb-postgres-analytics/)) |
| 分析引擎 | **嵌入式 DuckDB**（每数据工作台会话一个连接/文件） | 隔离性天然；文件即表；失败不影响底座 ([MotherDuck](https://motherduck.com/blog/langchain-sql-agent-duckdb-motherduck/)) |
| 决策路由 | **Jev**（`jev-1.13.0` 固定版本号，不用 `jev-latest` 跑生产评估） + `DecisionProvider` 抽象 | 版本钉死是可复现评估的前提 ([meetcody](https://meetcody.ai/blog/typesafe-jev-ai-system-one-model/)) |
| 代码沙箱 | 默认**本地受限子进程**；不可信代码切 **E2B microVM**（自托管或托管） | E2B 快照冷启动 5–30ms、按秒计费、可自托管 ([Spheron](https://www.spheron.network/blog/ai-agent-code-execution-sandbox-e2b-daytona-firecracker/)) |
| 编排 | 轻量自研循环（状态在 Postgres），**不引入 LangGraph 作为依赖**；如需图形化编排可后续对齐其 checkpointer 表结构 | 底座已在 Postgres，再叠框架只增加耦合；LangGraph 的 Postgres checkpointer 证明该表结构模式成立 ([Medium](https://medium.com/@alonjamanjeetsinh77/building-infinite-memory-agents-a-master-guide-to-langgraph-langmem-and-postgres-05b3cabd689b)) |
| 观测 | decisions 表内建审计（必选） + **Langfuse 自托管**（可选，Postgres+ClickHouse 栈） | Langfuse MIT 核心、OTel 友好、可完全自托管 ([DigitalApplied](https://www.digitalapplied.com/blog/agent-observability-platforms-langsmith-langfuse-arize-2026)) |
| 前端（后续） | 文本工作台 UI 用 **TipTap/BlockNote** 渲染 documents 表；管理台随意 | 编辑器是文档模型的视图，不反向影响架构 ([eddyter](https://eddyter.com/blogs/best-rich-text-editor-for-ai-agents-2026)) |

这个选型还有一个隐藏收益：**Jev 官方同时维护 Python 与 JS SDK，并提供 LangChain 中间件**（`ModelRouterMiddleware` 正是"从首条用户消息选模型"的官方参考实现） ([atomicbot](https://atomicbot.ai/blog/what-is-jev))。即便未来某个子系统改用 TypeScript，决策层协议（`state` + `questions` 的 JSON 契约）不变，Provider 可以平移。

---

## 3. 总体架构

v13.1 把系统切成五层：**入口层**（会话与任务规范化）、**Jev 决策路由层**（判断启用哪个工作台）、**工作台层**（数据/代码/文本三个专业化执行环境）、**底座层**（PostgreSQL + DuckDB 引擎）、**观测与治理层**（审计、成本、阈值治理）。核心原则是：**路由层无状态，状态全在底座；工作台无记忆，记忆全在底座；Jev 无生成能力，生成全在工作台内的主 LLM**。

![pg-agent v13.1 总体架构](pg-agent-v13.1-assets/01-总体架构.png)

各模块职责如下表，它是后续所有代码结构（包结构、表结构、接口签名）的权威划分：

| 模块 | 职责 | 关键接口 / 载体 | 显式不做什么 |
|---|---|---|---|
| Session Manager | 会话生命周期、任务规范化（TaskEnvelope） | `sessions` / `messages` 表 | 不做路由判断 |
| DecisionProvider（Jev 路由层） | 给定 state 返回类型化决策 | `decide(state, questions) -> answers` | 不生成文本、不执行 |
| 数据工作台 | 文件接入、探索式 SQL、数据集登记、图表/报告产出 | `DataWorkbench` 类 + `datasets` 表 | 不直接写业务库 |
| 代码工作台 | 沙箱执行、测试、构建、制品登记 | `SandboxProvider` + `artifacts` 表 | 不在宿主机裸跑不可信代码 |
| 文本工作台 | 块级文档读写、版本化、diff 审阅 | `documents` 表（JSONB 块 + version 链） | 不做纯聊天（聊天走主循环） |
| 底座服务层 | 记忆读写（pgvector）、审计、队列、检索 | `memories` / `decisions` / LISTEN-NOTIFY | 不含业务逻辑 |
| 观测治理 | 决策日志查询、阈值校准、成本看板 | decisions 视图 + 可选 Langfuse | 不在关键路径上 |

一个关键设计取舍值得展开：**工作台之间不直接通信，一切经由底座**。数据工作台产出一个数据集，动作是"写 DuckDB 文件/视图 + 在 `datasets` 和 `artifacts` 表登记"；文本工作台要写一份基于该数据集的报告，动作是"从 `artifacts` 查到数据集 URI，挂到自己的上下文里"。这让 **hybrid 任务（数据→文本、代码→数据）不需要第四种工作台**，只需要路由层允许顺序激活——后文第 8 节会给出 hybrid 的路由协议。

另一个取舍是**主 LLM 的位置**。Jev 不能生成文本，所以每个工作台内部仍由主 LLM（GPT/Claude/国产模型均可，走 v13 已有的模型层）驱动工具循环；Jev 在这个循环里还承担两个廉价的高频判断：风险门控（工具调用前 Score 风险，高风险阻断，参照 `AutoModeMiddleware` 的做法）与完成判定（Noul：任务目标是否已满足） ([atomicbot](https://atomicbot.ai/blog/what-is-jev))。这两个判断在 v13.1 标记为可选增强，避免范围膨胀。

---

## 4. PostgreSQL 底座设计

### 4.1 数据模型

底座数据模型围绕"一次任务的全生命周期"组织：`sessions` 是会话容器，`messages` 是过程流，`decisions` 是每次 Jev 判断的审计行，`workbench_runs` 是工作台执行记录，`artifacts` 是所有产出物的统一登记表，`memories` 是跨会话记忆，`documents`/`datasets` 是两类特化产出物。

![PostgreSQL 底座核心数据模型](pg-agent-v13.1-assets/03-数据模型.png)

核心表的 DDL 骨架（节选，字段以后续迁移文件为准）：

```sql
CREATE TABLE sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_ref        text NOT NULL,
    active_workbench text,                    -- data | code | text | null
    context_summary text,                     -- 供路由 state 使用的滚动摘要
    created_at      timestamptz DEFAULT now(),
    closed_at       timestamptz
);

CREATE TABLE decisions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   uuid REFERENCES sessions(id),
    kind         text NOT NULL,               -- route | clarify | risk_gate | done_check
    provider     text NOT NULL,               -- jev | openrouter_jev | rule | llm_fallback
    model        text,                        -- jev-1.13.0
    state_hash   text NOT NULL,               -- 只存哈希，不存原文（隐私）
    questions    jsonb NOT NULL,
    answers      jsonb NOT NULL,              -- 含每选项概率分布
    confidence   numeric,
    latency_ms   int,
    created_at   timestamptz DEFAULT now()
);

CREATE TABLE artifacts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     uuid REFERENCES workbench_runs(id),
    kind       text NOT NULL,                 -- file | dataset | document | build
    uri        text NOT NULL,                 -- duckdb://... | file://... | s3://...
    version    int  NOT NULL DEFAULT 1,
    hash       text,
    meta       jsonb DEFAULT '{}'::jsonb
);

CREATE TABLE memories (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope      text NOT NULL,                 -- user | project | session
    scope_ref  text NOT NULL,
    kind       text NOT NULL,                 -- fact | preference | episode
    content    text NOT NULL,
    embedding  vector(1536),
    score      numeric DEFAULT 1.0,           -- 随时间衰减/强化
    updated_at timestamptz DEFAULT now()
);
```

三个设计要点。第一，**`decisions.state_hash` 只存哈希不存原文**——hermes-jev-skills 的隐私实践（日志只存决策不存 prompt）值得照搬：审计能回答"当时为什么这么路由"，但不沉淀用户数据副本 ([GitHub](https://github.com/kerpopule/hermes-jev-skills))。第二，**`artifacts` 是所有工作台的统一交换格式**——任何跨工作台协作都读这张表，这让"数据工作台产出的数据集被文本工作台引用"成为一个查询而非一套 RPC。第三，**`memories.scope` 三级可见性**（session / project / user）对应 Letta 的 core/archival/recall 分层思想，检索时 pgvector 语义搜索 + scope 过滤 ([Medium](https://medium.com/@alonjamanjeetsinh77/building-infinite-memory-agents-a-master-guide-to-langgraph-langmem-and-postgres-05b3cabd689b))。

### 4.2 隔离与安全

v13.1 的隔离分三档，按任务风险逐级启用。**默认档**：所有任务共享一个数据库，行级安全（RLS）按 `user_ref` 隔离——pg_duckdb 1.1.x 已明确支持 Postgres RLS，但安全敏感负载应钉死版本验证，因为其集成行为跨版本有变化 ([Baremon](https://www.baremon.eu/pg-duckdb-postgresql-query-execution/))。**增强档**：每个工作台会话使用独立 schema（`workbench_{run_id}`），任务结束即 drop，实现"够用的隔离"而不需要存储层支持。**远景档（v13.2+）**：如果部署在 Tiger Cloud 或自建类似存储层，用零拷贝 fork 给高风险实验（如 AI 生成的 migration）开完整副本——Tiger 的实测是 750MB 库 fork 不到 5 秒 ([GitHub](https://github.com/surajranaofficial/ai-code-review-swarm))。

任务队列不引入 Redis：用 `LISTEN/NOTIFY` 做唤醒 + `SELECT ... FOR UPDATE SKIP LOCKED` 做抢占，是 Postgres 社区验证过的轻量队列模式，与"底座即一切"的哲学一致。同理，全文检索用 Postgres 内建 tsvector，语义检索用 pgvector，需要 BM25 排序质量时再评估 pg_textsearch（该扩展目前为内存实现，磁盘版仍在开发中） ([InfoQ](https://www.infoq.com/news/2025/12/agentic-postgres-fast-forking/))。

---

## 5. 数据工作台（DuckDB Workbench）

### 5.1 双模架构与生命周期

数据工作台是三个工作台中论证最充分的一个，因为"agent + DuckDB"已有成型的工具循环参照：agent 的典型行为是**看 schema → 试探性查询 → 报错修正 → 逐步收敛**，DuckDB 的进程内、零拷贝读文件特性正是为这个循环而生 ([MotherDuck](https://motherduck.com/blog/langchain-sql-agent-duckdb-motherduck/))。工作台的生命周期为：**接入（ingest）→ 画像（profile）→ 探索（explore）→ 建模（model）→ 登记（register）→ 交付（deliver）**。

接入阶段体现"文件即表"的威力：用户扔进 CSV/Parquet/JSON/JSONL，工作台直接 `read_csv('...', auto_detect=true)` 开始查询，没有建表、没有导入管线；httpfs 扩展让 S3/HTTP 上的文件同样即指即查 ([Fastero](https://fastero.com/blog/connect-duckdb-to-dashboards-and-ai-agents))。每个工作台 run 对应一个独立的 DuckDB 数据库文件（`runs/{run_id}.duckdb`），这既给了 DuckDB 写持久化（中间表、清洗结果），又利用"单写锁"约束天然实现了会话间隔离——另一个会话的写冲突在文件系统层面就不可能发生 ([Dataskew](https://dataskew.io/blog/metabase-duckdb-local-analytics/))。

### 5.2 与 Postgres 底座的双向关系

**向下（分析底座自身数据）**：当任务要分析 pg-agent 自己的运行数据（比如"过去一周路由到代码工作台的任务平均耗时"）时，走 pg_duckdb——`SET duckdb.force_execution = true` 后标准 SQL 即被 DuckDB 引擎接管，对 `workbench_runs`、`decisions` 等大表的扫描聚合可获得数倍加速，且 PostgreSQL 保持访问控制与行可见性的权威 ([rockdata](https://www.rockdata.net/zh-cn/posts/pg_duckdb-quick-start/), [Baremon](https://www.baremon.eu/pg-duckdb-postgresql-query-execution/))。**向上（产出回写）**：分析结论不落 DuckDB 文件就完事——数据集元信息（schema JSON、行数、来源 URI）写入 `datasets` 表，文件本体登记进 `artifacts`，这样文本工作台和后续会话都能发现并引用它。

要显式规避 pg_duckdb 的两个已知坑：其一，**大结果集全量物化**——凡是预计返回大量行的查询，应在 DuckDB 侧先聚合/采样再回传，或落 Parquet 后登记 URI 而非搬运结果集 ([Baremon](https://www.baremon.eu/pg-duckdb-postgresql-query-execution/))；其二，**高精度 numeric 默认被拒绝**（除非显式开启有损转 DOUBLE），金融类数据接入时要先做类型画像 ([Baremon](https://www.baremon.eu/pg-duckdb-postgresql-query-execution/))。这两点都会写进工作台的 `duckdb_profile` 工具（自动输出每列类型、基数、空值率、疑似敏感列），让 agent 在写查询前先看数据画像——这正是 MotherDuck 官方 agent skills 目录强调的"先 inspect 再 query"纪律 ([MotherDuck](https://motherduck.com/blog/from-mcp-to-motherduck-skills-teaching-ai-agents-analytics/))。

### 5.3 工作台工具集（暴露给主 LLM 的工具）

| 工具 | 功能 | 写底座？ |
|---|---|---|
| `data_ingest(path/uri)` | 注册文件为可查询源，返回 profile 摘要 | 写 `datasets`（kind=source） |
| `duckdb_query(sql, limit)` | 执行 SQL，默认 LIMIT 护栏，超阈值自动采样 | 写 `workbench_runs.metrics` |
| `duckdb_profile(table)` | 列类型/基数/空值/敏感列画像 | 否 |
| `dataset_save(name, sql)` | 把查询结果物化为数据集（Parquet + DuckDB 视图） | 写 `datasets` + `artifacts` |
| `chart_render(spec)` | 出静态图（PNG），登记为 artifact | 写 `artifacts` |
| `dataset_publish(id)` | 导出为 Parquet/CSV 供其他工作台或用户下载 | 更新 `artifacts.version` |

规模上限要写进文档：DuckDB 单机纵向扩展，工作集在**数百 GB 以内、并发个位数**时是最优解；超出这个量级（多 TB、多租户高并发、强治理）应路由到外部数仓而非硬撑 ([Basedash](https://www.basedash.com/blog/duckdb-for-bi-when-single-node-analytics-beats-a-cloud-warehouse))。路由层的 `est_complexity` 分数就是干这个的——复杂度 3 的数据任务在路由时就被标记"建议外部计算"。

---

## 6. 代码工作台与文本工作台

### 6.1 代码工作台：SandboxProvider 抽象 + 双实现

代码工作台的核心抽象是 `SandboxProvider`，两个实现按代码可信度切换：**LocalSandbox**（默认，受限子进程：无网络、`rlimit` 限 CPU/内存、临时目录、只读挂载项目副本）用于处理用户自己项目里的可信代码；**E2BSandbox**（Firecracker microVM，硬件级内核隔离）用于执行 LLM 刚生成的、未经验证的代码——E2B 的 Firecracker 隔离能防住针对共享内核的容器逃逸，这正是"跑不可信代码"场景的安全底线 ([Modal](https://modal.com/resources/best-code-execution-sandboxes-mcp-servers), [Northflank](https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes))。

生命周期设计为**会话内持久、会话间登记**：一个代码工作台 run 内，沙箱状态（已装的包、生成的文件）持续累积——这吸收了 Daytona"持久工作区适合项目型任务"的洞察；run 结束时， diff 出的制品（补丁、构建产物、测试报告）登记进 `artifacts`（kind=build），沙箱销毁 ([Northflank](https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes))。E2B 托管版的会话上限（Hobby 1 小时 / Pro 24 小时）和暂停/恢复语义决定了长任务策略：超过 1 小时的 run 用 `artifacts` 中的中间制品做断点，而不是依赖沙箱保活 ([Blaxel](https://blaxel.ai/blog/code-execution-sandboxes-for-ai-agents.html))。

### 6.2 文本工作台：文档模型先行

文本工作台的关键决策是**不先选编辑器，先定文档模型**。文档存为 `documents` 表中的版本化 JSONB 块数组（标题/段落/列表/代码块/表格/引用六种基础块起步），每次 agent 改写生成 `version+1` 的新行并记录 `parent_id`，形成可 diff、可回滚的版本链。这个设计让前端选型变成了纯视图问题：BlockNote 天然是块模型、TipTap/ProseMirror 生态最大、Milkdown 适合 Markdown 优先——v13.1 不接 UI 时，模型和 diff 能力已经可以完整工作 ([eddyter](https://eddyter.com/blogs/best-rich-text-editor-for-ai-agents-2026))。

文本工作台与数据工作台的协作流是 v13.1 的招牌场景：**"基于数据集写报告"**。流程为：Jev 路由判定为 hybrid（先 data 后 text）→ 数据工作台完成分析并登记 `datasets` → 文本工作台启动时把数据集 schema + 关键统计量注入主 LLM 上下文 → 生成报告文档 → `documents` 与源 `datasets` 通过 `artifacts` 建立引用。整条链路没有任何工作台间直连，全部经由底座表完成握手。

---

## 7. Jev 路由层：本方案的核心

### 7.1 DecisionProvider 抽象（用户选定的"抽象接口 + 官方 API 优先"）

路由层定义一个与厂商无关的接口，Jev 是首选实现而非唯一实现：

```python
class DecisionProvider(Protocol):
    async def decide(self, state: dict | str,
                     questions: dict[str, Question]) -> DecisionResult: ...

# 实现优先级：
# 1. TypeSafeJevProvider      —— api.typesafe.ai/v1/systemone（官方 SDK）
# 2. OpenRouterJevProvider    —— openrouter.ai/api/alpha/decisions（绕过 waitlist）
# 3. RuleProvider             —— 本地启发式（附件类型/关键词/文件魔数），离线兜底
# 4. LLMProvider              —— 小模型结构化输出，Jev 不可用时的语义兜底
```

OpenRouter 路径有一个实测过的细节：Jev 是 decisions 模型，`/chat/completions` 会被直接拒绝，必须 POST 到 `/api/alpha/decisions`，且它不出现在默认模型目录里；但响应体与官方 API 同为 `SystemOneResponse` 结构，所以**两个 Provider 之上的代码零改动** ([typesafe-jev-examples](https://github.com/rajivkuriakose/typesafe-jev-examples))。兜底链的意义不只是高可用：Jev 处于 early access，官方明示限流（250k tokens/s、1200 req/min）可能随时调整，且发布当天曾因需求过载短暂无法服务 ([awesome-jev](https://github.com/valentynkit/awesome-jev-typesafe), [Arabian Post](https://thearabianpost.com/typesafe-unveils-decision-focused-ai-model-jev/?srsltid=AU7gw4WmzSz9hqnFVvLeD3-8vgPygo6or88PPM0dludKW_Z3iDgsBAnM))。Provider 选择本身也写进 `decisions.provider`，审计时可以区分"这次是 Jev 判的还是规则判的"。

### 7.2 路由协议：一次调用，四个问题

路由决策的完整协议如下图所示，核心思想是**把"启用哪个工作台"分解为一次 Jev 调用里的四个并行问题**，而不是顺序问四次——Jev 的并行求值特性保证加问题几乎不增加延迟 ([MarkTechPost](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/))。

![Jev 路由决策流程](pg-agent-v13.1-assets/02-路由决策流程.png)

```python
ROUTE_QUESTIONS = {
    "workbench": Choice(
        instructions="这个任务最适合在哪个工作台完成？",
        criteria={
            "data":   "任务是围绕数据文件的探索、清洗、分析、可视化、出数据集",
            "code":   "任务是编写、调试、测试、构建、重构代码，或操作代码仓库",
            "text":   "任务是写作、改写、翻译、摘要、长文档撰写与审阅",
            "hybrid": "任务明确需要两个以上工作台接力（如先分析数据再写报告）",
        }),
    "need_clarify": Noul(
        instructions="现有信息不足以可靠地自动分流，需要向用户追问关键信息"),
    "risk":         Score(instructions="任务若自动执行的操作风险",
                          levels=["只读", "可逆修改", "需确认的修改", "不可逆/对外副作用"]),
    "complexity":   Score(instructions="任务的规模与复杂度",
                          levels=["分钟级", "小时级", "需拆分", "超出单机/单会话能力"]),
}
```

`state` 的组装是路由质量的第一杠杆，v13.1 固定为五元组：**任务原文 + 附件清单（文件名/类型/大小，不传内容）+ 会话滚动摘要 + 历史工作台偏好（从 memories 取的 top-3）+ 环境信号（当前是否有活跃数据集/仓库/文档）**。注意这有意不发送完整历史和文件内容——hermes-jev-skills 的隐私纪律（路由只发当轮、脱敏、截断 3000 字符）直接照搬，敏感特征（邮箱、token、长十六进制串）本地遮蔽后再发 ([GitHub](https://github.com/kerpopule/hermes-jev-skills))。

### 7.3 阈值策略与降级

拿到答案后由本地代码（零成本、零延迟）做三段判定：

| 条件 | 动作 | 理由 |
|---|---|---|
| `need_clarify ≥ 0.6` | **不启动任何工作台**，主 LLM 生成澄清问题 | Jev 不能生成文本，澄清措辞由主 LLM 负责 ([DataCamp](https://www.datacamp.com/blog/system-one-models-jev)) |
| `workbench` 置信度 ≥ τ（默认 **0.75**） | 直接激活，静默路由 | 校准概率的用法就是"高置信自动化" ([apidog](https://apidog.com/blog/what-is-jev/)) |
| 0.5 ≤ 置信度 < τ | 激活首选工作台，但向用户声明"判断为 X，可切换" | 弱匹配不硬猜，参照 jev-agent-skill-router 的"decline weak matches" ([awesome-jev](https://github.com/yibie/awesome-jev)) |
| 置信度 < 0.5 | 退化为澄清（问用户选哪个） | 分布平坦 = 任务本身模糊 |
| `risk ≥ 2` | 任何置信度下都先用户确认 | 阈值按后果分级，不按方便分级 ([meetcody](https://meetcody.ai/blog/typesafe-jev-ai-system-one-model/)) |
| `complexity = 3` | 附加提示"建议拆分/外部资源"，不阻断 | DuckDB 单机边界见 §5.3 ([Basedash](https://www.basedash.com/blog/duckdb-for-bi-when-single-node-analytics-beats-a-cloud-warehouse)) |

阈值 τ 不是拍脑袋常量，而是**用 shadow 数据校准出来的**。v13.1 上线第一周运行 shadow 模式：Jev 照常决策、照常写 `decisions` 表，但不实际切换工作台（沿用 v13 的现有行为）；一周后从 `decisions` 表里按置信度分桶统计人工纠偏率，把 τ 定在"高置信桶的纠偏率 < 5%"的位置。这正是 hermes-jev-skills 的官方建议姿势（"`/jev routing shadow` 先跑一天，日志看着对了再开"），也是 meetcody 给出的 Jev 投产前评估清单中"按概率分桶测校准"的落地 ([GitHub](https://github.com/kerpopule/hermes-jev-skills), [meetcody](https://meetcody.ai/blog/typesafe-jev-ai-system-one-model/))。

### 7.4 成本与延迟预算

按 Jev 官方定价 $0.042/百万 input tokens、output 免费 ([awesome-jev](https://github.com/valentynkit/awesome-jev-typesafe))，每次路由约 700 input tokens（state ~400 + questions ~300）：

| 日任务量 | 路由 tokens/日 | 路由成本/日 | 路由成本/月 | 每次路由延迟（厂商报告） |
|---|---|---|---|---|
| 1,000 | 0.7M | $0.029 | **$0.9** | 70–500ms |
| 10,000 | 7.0M | $0.29 | **$8.8** | 70–500ms |
| 100,000 | 70M | $2.94 | **$88.2** | 70–500ms |

结论：**路由层的成本与延迟在架构上是可忽略项**，这也是 Jev 这类 System One 模型的根本卖点——把"每次任务都要做的小判断"从一次完整 LLM 调用（秒级、贵、还要解析文本）变成一次函数调用 ([ntorres.dev](https://ntorres.dev/blog/jev-typesafe-system-one-model))。真正的成本大头仍在各工作台内部的主 LLM，v13.1 的 `messages.tokens/cost` 字段负责把这部分算清楚。

### 7.5 防"路由器幻觉"的工程护栏

Jev 保证不产出 schema 外的答案，但**保证不了 schema 内的答案是对的**——这是官方和评论者反复强调的区分 ([apidog](https://apidog.com/blog/what-is-jev/), [explainx](https://explainx.ai/blog/typesafe-ai-jev-system-one-models-launch-2026))。v13.1 的护栏有四条：其一，**criteria 文案版本化**——路由质量高度依赖 Choice 里每个选项的判定标准措辞，文案改动走 git review 并在 `decisions.questions` 里留快照；其二，**golden set 回归**——积累 50–100 条"任务 → 正确工作台"的标注样例，每次改 criteria 或升级 Jev 版本（如 `jev-1.13.0` → 新版本）跑回归，这正是官方建议的"冻结代表性测试集 + 钉版本号" ([meetcody](https://meetcody.ai/blog/typesafe-jev-ai-system-one-model/))；其三，**用户纠偏一键回流**——用户手动切换工作台时写一条 `kind=feedback` 的 decisions 行，成为下一轮校准的标注数据；其四，**限流与降级演练**——RuleProvider 必须真的能用（附件类型 + 关键词已能覆盖约六七成明显任务），并定期在测试环境断开 Jev 验证降级链。

---

## 8. 观测、治理与实施路线图

### 8.1 观测：审计是内建的，Langfuse 是可选的

v13.1 的观测分两层。**内建层**（必选）：`decisions` 表本身就是审计系统——每次路由的 provider、问题、答案分布、置信度、延迟都可查；`workbench_runs.metrics` 记录每个工作台的执行统计；基于这两张表做一个简单 SQL 看板（路由分布、置信度直方图、纠偏率、各工作台成本）即可覆盖 80% 的治理需求。**外接层**（可选）：需要 trace 级调试（每个 prompt、每次工具调用、token 成本链）时自托管 Langfuse——它 MIT 核心、Postgres+ClickHouse 栈、OTel 友好，与 pg-agent 的 Postgres 中心哲学兼容，但要意识到它是四个存储系统的运维负担，小团队可以先不上 ([DigitalApplied](https://www.digitalapplied.com/blog/agent-observability-platforms-langsmith-langfuse-arize-2026), [mpiv](https://mpiv.ai/blog/langfuse-vs-braintrust-which-wins-for-agent-observability-2026))。

### 8.2 实施路线图（建议 6–8 周）

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| **M1：底座 + 决策接口**（1–2 周） | Postgres schema 迁移；`DecisionProvider` 接口 + 四个实现；decisions 审计落库；RuleProvider 兜底可用 | 断网状态下 RuleProvider 路由正确率 ≥ 60%（golden set）；每次决策都有审计行 |
| **M2：数据工作台**（2 周） | DuckDB 生命周期、六个工具、pg_duckdb 双模、datasets/artifacts 登记 | 上传 CSV → 自动 profile → 分析 → 产出 Parquet 并登记，全程可在底座追溯 |
| **M3：代码与文本工作台**（2–3 周） | SandboxProvider 双实现；documents 块模型 + 版本链；hybrid 接力流 | 不可信代码在 E2B 中执行；"数据集 → 报告" hybrid 任务端到端跑通 |
| **M4：Jev 上线与校准**（1–2 周） | 接真实 Jev key（官方或 OpenRouter）；shadow 跑 ≥ 1 周；校准 τ；golden set 回归流水线 | shadow 期间高置信桶纠偏率 < 5%；正式启用后 48h 无 P1 路由事故 |

关键纪律：**M4 之前路由由 RuleProvider 承担**——这意味着 v13.1 的代码在 Jev key 到手之前就全部可开发、可测试，Jev 接入是"换一个 Provider 实现 + 校准阈值"，不是架构事件。这直接回应了 Jev 尚在 waitlist 的现实约束 ([Universal Digital Assistant](https://universaldigitalassistant.com/launches/typesafe-ai-jev/))。

### 8.3 风险与开放问题

| 风险 | 等级 | 缓解 |
|---|---|---|
| Jev early access 不稳定（限流调整、曾过载停服） | 中 | 四实现兜底链 + shadow 期验证 ([Arabian Post](https://thearabianpost.com/typesafe-unveils-decision-focused-ai-model-jev/?srsltid=AU7gw4WmzSz9hqnFVvLeD3-8vgPygo6or88PPM0dludKW_Z3iDgsBAnM)) |
| 校准概率未获独立验证 | 中 | 不信任厂商数字，用自己的 golden set 与 shadow 数据测校准 ([explainx](https://explainx.ai/blog/typesafe-ai-jev-system-one-models-launch-2026)) |
| pg_duckdb 行转列成本在大结果集场景反噬 | 低 | §5.2 的两条规避规则写进工作台工具护栏 ([Baremon](https://www.baremon.eu/pg-duckdb-postgresql-query-execution/)) |
| DuckDB 单机边界被超大数据任务击穿 | 低 | `complexity=3` 路由时提示拆分/外部计算 |
| criteria 文案漂移导致路由回归 | 中 | 文案版本化 + 每次修改跑 golden set |
| 生态出现开源平替（DiffusionGemma 复现 Jev 模式已有早期尝试，准确率大致打平） | 观察项 | DecisionProvider 抽象保证可切换，无需改架构 ([explainx](https://explainx.ai/blog/typesafe-ai-jev-system-one-models-launch-2026)) |

开放问题留三个给 v13.2：**数据库 fork**（接入 Tiger Cloud 式零拷贝分叉做安全实验） ([Tiger Data](https://www.tigerdata.com/blog/postgres-for-agents))；**工作台内 Jev 增强**（风险门控 + 完成判定两个高频 Noul，把 agent 循环里的"小判断"也撤出主 LLM） ([atomicbot](https://atomicbot.ai/blog/what-is-jev))；**多工作台并行**（hybrid 目前是顺序接力，并行需要 artifacts 的乐观锁/冲突协议）。

---

## 附录 A：Jev 接入参考代码（M4 用）

```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

class TypeSafeJevProvider:
    """官方 API 实现。OpenRouter 版仅替换 endpoint 为
    https://openrouter.ai/api/alpha/decisions，响应结构相同。"""

    def __init__(self):
        self.client = TypeSafeClient()          # 读 TYPESAFE_API_KEY
        self.model = "jev-1.13.0"               # 钉版本，不用 jev-latest

    async def decide(self, state: dict, questions: dict) -> "DecisionResult":
        r = self.client.system_one(state=state, questions=questions)
        return DecisionResult(
            provider="jev", model=self.model,
            answers=r.answers,                  # 含每选项概率分布与 confidence
            usage=r.usage,
        )

# 调用示例：一次请求拿齐路由四问
result = await provider.decide(
    state={
        "task": "把这份销售 CSV 里的异常订单找出来，画个趋势图，写成一页报告",
        "attachments": [{"name": "sales_q3.csv", "type": "text/csv", "bytes": 2_400_000}],
        "session_summary": "用户是销售运营，过去三次任务都在数据工作台",
        "env": {"active_dataset": None, "active_repo": None},
    },
    questions=ROUTE_QUESTIONS,
)
# result.answers["workbench"].choice      -> "hybrid"
# result.answers["workbench"].confidence  -> 0.9x
# result.answers["need_clarify"].noul     -> 0.08  (无需澄清)
# result.answers["risk"].score            -> 0     (只读)
```

## 附录 B：v13.1 范围界定（防止蔓延）

**做**：Postgres 底座六表、DecisionProvider 四实现、三个工作台的最小可用版、hybrid 顺序接力、shadow 校准流程、内建审计看板。**不做**（明确推迟）：数据库 fork、工作台内 Jev 高频判断（风险门控/完成判定）、工作台并行、编辑器 UI、多用户协作（RLS 只按单用户多会话设计）、Langfuse 外接。每一项推迟都在路线图中有对应位置，防止 v13.1 变成"什么都想要"的版本。

---

*本方案为技术设计文档，涉及的第三方服务定价、限流与功能以各厂商官网当期信息为准；Jev 处于 early access，接入前请以其官方文档复核端点与限额。*
