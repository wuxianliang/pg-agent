# v13 RAG 子代理设计:库内 PL/pgSQL 实现(草案 v1)

> 日期:2026-09-22。状态:**草案 v1,待轮 1 裁决**。
> 输入:① auto_coder-3.0.80 rag 解剖(三路 explore 调查报告,file:line 存底);② pgembed 0.3.0rc2 扩展库存实测;③ v13 设计冻结稿(v2)+ DP1–DP6 已落地现状。
> 定位:v13 的**子系统设计**——RAG 作为「任何 agent 都能调用的能力子代理」。不改 v13 承重件(召回是函数/chunks 三纪律/两阶段 advance/过滤管道/三层记忆),只在其上装箱。

---

## 0. 一句话

RAG 在 pg-agent 中的形态 = **能力子代理**(capability subagent):语料摄取走 effect、检索/过滤/装配逻辑全在库内 PL/pgSQL(判断走 pg_typesafe,外部生成走 effect)、对任何 agent 暴露为三档入口(recall 函数直呼 / `rag.ask` 工具行 / spawn 深检索),回程是**被评分的块**(artifact)而不是日志。pgembed 0.3.0rc2 的插件集**够用且恰好对齐 v13 台账**;唯一物理缺口(CJK 分词)v13 台账已预置 bigram 对策。

---

## 1. 调查输入一:auto_coder-3.0.80 的 rag 解剖

### 1.1 事实(带 file:line,已抽查复核)

| 事实 | 证据 |
|---|---|
| 默认管线**无向量索引**:核心是 LLM 逐文档相关性过滤 | `rag/doc_filter.py` `DocFilter.filter_docs`;`relevant_score = args.rag_doc_filter_relevance`(默认 5 / 0–10 分制) |
| 三阶段 recall→chunk→answer | `rag/long_context_rag.py`(≈3948 行,核心编排类在尾部) |
| 预算三分:full_text ≈0.6 / segment ≈0.3 / buff = 1−两者 | `long_context_rag.py:2892-2897`(已复核:`buff_ratio = 1 - full_text_ratio - segment_ratio`) |
| token 计分块:小文件合并、大文件 >60k tokens 按换行切 | `rag/document_retriever.py:201-399` |
| 可选混合索引(DuckDB VSS + embedding 子客户端 + 随机投影降维),**默认关** | `rag/cache/local_duckdb_storage_cache.py`;`enable_hybrid_index` 默认 False |
| index/ 三级过滤 quick/normal/agentic 均为 LLM 判断 | `index/filter/{quick,normal,agentic}_filter.py` |
| agentic 循环:RAGAgent 注册 `recall` / `todo_read` / `todo_write` 工具,迭代检索 | `rag/agentic_rag.py:121-131` |
| api_server:OpenAI 兼容面(chat/completions、embeddings),LLWrapper 使所有 chat 注入 RAG;无 MCP | `rag/api_server.py` |
| 消费面:RAGFactory→LongContextRAG;Planner 用 `rag.search`;多 RAG 注册表 `rags_config.json` + 项目 `.rag_config/` 提示注入 | `rag/rag_entry.py:15-31`、`rags.py`、`rag/rag_config.py` |
| 全程纯 Python + LLM:无 PG、无 SQL、无事务 | 全仓无 psycopg/SQL 检索 |

### 1.2 可移植性判定:可移植的是**流程形状与参数纪律**,不是代码

| auto_coder 能力 | v13 对应物 | 判定 |
|---|---|---|
| LLM 逐文档相关性过滤(yes/N + 0–10) | **filter 阶段:存在性 Noul 先行 + per-chunk Score(DP6 已落库)** | 同构;评分制映射进 typesafe 信封;批上限/阈值进策略行 |
| 三级过滤(quick/normal/agentic) | recall(T0 TINQL)+ 过滤管道 + 可选 spawn 深检索 | 形态覆盖 |
| 三阶段 recall/chunk/answer | recall→过滤→manifest 装配;**answer(生成)环缺** | 需补第五节 (d) |
| 预算三分比(0.6/0.3/buff) | economy tier 带 + manifest est_tokens | 比例进策略行,量纲关系化 |
| token 计分块器 | chunks 投影(chunker_version 已存在) | 补一个 token 计分块器版本即可 |
| 多格式装载(PDF/docx/ppt/excel/图/OCR) | **PG 外**:解析=effect,产物=artifact | 拓扑改变,职责同(v13 不变式 4:外部 IO 不进事务) |
| conversation→queries(多查询展开) | 缺 | 新增:pg_typesafe 判断件 |
| agentic 多轮循环 | `spawn_subsession` + tools 行(recall/todo) | 复用 §6.8 A17 |
| OpenAI 兼容 serve 面 | 可选;pg_net 已被 P0 排除(§8 台账),若做必须是独立 worker | YAGNI 后置 |
| 多 RAG 注册表(rags_config.json) | `corpora` 行 + 策略行(关系化) | 关系化重写 |

---

## 2. 调查输入二:pgembed 0.3.0rc2 插件库存与「够不够用」判定

实测:`pgembed/pginstall/{share/postgresql/extension,lib/postgresql}`(darwin/arm64,PG 18.4,bundle recipe `pgembed-postgresql-18-bundle-v2`)。

### 2.1 关键可用集(与 v13 台账对照)

| 扩展 | 版本 | v13 台账关系 |
|---|---|---|
| **stannum** | 0.1.0(设计期 bundle 库存实测口径;**现环境 0.4.0**,以 `pg_extension.extversion` 实测为准——消歧见 `v13/characterize/README.md` 顶部活记载行) | T0 BM25/TINQL 实体;DP5 已刻画(characterize) |
| **vectorchord(vchord)** | 1.1.1 | T1 混合台账触发线;需 `shared_preload_libraries='vchord'` |
| **pgvector(vector)** | 0.8.2 | T1 存储备选;v6 已在用(`CREATE EXTENSION vector`) |
| **pg_typesafe(typesafe)** | 0.0.1 | 库内判断唯一 IO 例外;v13 schema 已启用 |
| **pg_jsonschema** | 0.3.4 | 信封/args 校验(P1 进) |
| **pg_cron** | 1.6.7 | 夜跑/投影/verify_index(P1「扫地僧」);v13 已有降级 NOTICE 路径 |
| **pgmq** | 1.12.0 | 队列;v12/v4 已在用 |
| **psql_bm25s** | 0.4.14 | 台账「被 stannum 替代」——**新事实:它在包内**,保留为 stannum 刻画不过时的同级备胎条款 |
| **pg_partman** | 5.5.0 | 新可用:chunks/events 保留分区策略 |
| contrib 群 | pg_trgm 1.6 / unaccent / fuzzystrmatch / btree_gin / btree_gist / ltree / cube / bloom / citext / dict_xsyn / hstore / pgcrypto … | 模糊/前缀/拼音级兜底 |

### 2.2 缺口

| 缺口 | 影响 | 对策 |
|---|---|---|
| zhparser / pg_jieba / pgroonga | 中文分词 | **v13 §4.6 已预置**:bigram 生成列台账 + `v13_build_tinql` 语言分段;语料 CJK 为主时 stannum 顶 T0 |
| pgai / pgml / 库内嵌入函数 | 嵌入不能库内计算 | 与 v13 §7 T1 原文一致:**「嵌入=派生缓存行(content_hash×model),embed=effect」**——向量外部算好、`vector`/`vchord` 类型存入库 |
| rum / pg_search / pg_similarity | 排名扩展 | 不需要:stannum 超集覆盖(台账既有裁决) |

**判定:够用。** 逐条过 v13 §8 元原则:(a) 替代自写代码——stannum/vectorchord/typesafe 全是;(b) 保 gate 确定性可 mock——typesafe GUC mock 已在 v12 G7/DP5 验证;(c) 不制造第二真相源/第二 IO 通道——无 pg_net 依赖,嵌入走 effect。缺的只有物理上买不到的中文分词,而设计早已绕开(不是本设计的引入风险)。

---

## 3. 设计:RAG 能力子代理

### 3.1 形态选择:为什么是「能力子代理」而不是「嵌在每 agent 里的库」

- jev 调查结论(2026-09-22):**「检索占主导…共享检索是最大单项节省」「子 agent 回程=被评分的块」**——RAG 天然是共享能力,不是每 agent 自带的接线。
- 三档调用粒度(任何 agent = 任何持 tools 可见性的 session,出口收敛于 `v13_visible_tools`):

| 档 | 形态 | 场景 | 外部调用 |
|---|---|---|---|
| (a) `rag.recall` | 单条 SQL 函数(`v13_recall` 的 corpus 包装) | 轻量:要候选块 | 零 |
| (b) `rag.ask` | tools 行 `kind='sql'` | 常规:问题→被评分块+收据 | 过滤判断(typesafe;mock 下零) |
| (c) `spawn_subsession(kind='rag')` | §6.8 A17 spawn 档位 | 深检索:多轮 recall/todo 循环 | 判断 + 可选生成 effect |

### 3.2 职责切分:「尽量 PL/pgSQL」的规范表(本设计的承重表)

| 环节 | 实现位置 | 理由 |
|---|---|---|
| 语料注册、策略行(阈值/三分比/批上限/k 上限) | PL/pgSQL + 数据行 | 调度/策略是行 |
| 摄取(文件读取/PDF/OCR/解码) | **effect worker(Python)** → artifacts | 外部 IO 一律不进数据库事务(不变式 4) |
| chunks 投影 + token 计分块 | PL/pgSQL 生成器 + `chunker_version` | 可重建投影、重摄取同事务(DP4 三纪律) |
| TINQL 编译、召回 | PL/pgSQL + stannum(DP5 已实现) | — |
| 相关性过滤:存在性 Noul 先行 + per-chunk Score | **pg_typesafe 库内判断**(信封+缓存) | 判断 IO 唯一例外;缓存键 per-chunk×query |
| conversation→queries 多查询展开 | pg_typesafe 判断件(新模板行) | 纯判断 |
| 预算装配 + manifest + 审计收据 | PL/pgSQL(DP3) | — |
| 嵌入(T1 触发时) | **effect** → 派生缓存行 | §7 原文:content_hash×model 派生 |
| **answer 生成** | **effect(父侧或子代理回程后)** | 生成不进库;见 §8 待裁决 2 |
| 调度(投影构建/verify_index/保留/夜跑) | pg_cron(缺则 NOTICE 降级,已有先例) | 「不是节拍器」 |
| serve 面(OpenAI 兼容) | YAGNI 后置;若做=独立 worker,**绝不用 pg_net** | §8 台账 P0 排除不动摇 |

### 3.3 表增量(最小)

```text
corpora(name PK, root_ref, policy jsonb, created_at)     -- 语料注册(替代 rags_config.json)
  └ source_hash 纪律沿用 artifacts → chunks(DP4 既有表,corpus 列已存在)

策略行(全住 thresholds,零新表):
  rag.context_budget{full_text,segment,buff}   -- 0.6/0.3/0.4→三分比
  rag.filter{batch_max, relevance_threshold}   -- 映射 auto_coder 的 5/10
  rag.recall{k_max, adaptive_k}                -- 精确 count(*) 自适应(§4.6)
  rag.agentic{max_rounds}                      -- auto_command_max_iterations 的关系化

(T1 触发后)embeddings(content_hash, model, vec vector, embedded_at)
  UNIQUE(content_hash, model)                  -- 派生缓存行;TRUNCATE 可丢(基础行不可丢)
```

### 3.4 PL/pgSQL 函数族(提案名,实现时按 DP 计划定稿)

```text
v13_rag_ask(p_sid uuid, p_question text, p_corpus text) RETURNS jsonb
  -- 编排:conversation→queries(typesafe)→ recall → 存在性 gate → per-chunk Score
  --      → 预算装配 → 收据 artifact。全程库内;判断走信封,零外部 IO(mock 计数=0)
v13_rag_recall(p_corpus text, p_tinql text, p_k int)     -- v13_recall 的 corpus 包装(档 a)
v13_rag_queries_from(p_sid uuid) RETURNS jsonb           -- conversation→queries 判断(新模板)
v13_rag_receipt(p_sid uuid, p_result jsonb) RETURNS uuid -- 被评分块 → artifacts(handoff 载荷)
```

工具行:`rag.ask`、`rag.recall`(kind='sql');`spawn_subsession` 的 `kind='rag'` 档位(WORK 台账具名 VOLATILE 例外)。

### 3.5 子代理合同(复用 v13 控制面信封,零新 primitive)

- **spawn**:父 advance 同事务批量扇出(§6.8 A17);并发防超售用根事务咨询锁——既有约定,不新增。
- **回程 handoff**:artifacts 载荷 + 稳定 `delivery_id` 幂等;被评分块形状 `{chunk_hash, score, span, decision_id}`——正是 manifest 候选行的投影,父侧零新解析。
- **四值 result_kind 复用**:`progress`(还需检索)/`finish`(块已交付)/`wait`(等语料摄取或审批)/`reject`(语料不存在,禁伪装 unknown)。
- **失败纪律**:失败 turn 不进分位样本(§5.5 既有);语料缺答案时存在性 Noul 1 次调用替代 k 次付费(DP6 既有)。

### 3.6 与 v13 承重件的关系:零改动名单

不动:召回是函数不是视图 / chunks 三纪律 / 两阶段 advance / 过滤管道(存在性先行+per-chunk) / 三层记忆 / 四值信封 / effect 纪律。新增仅:corpora 行、rag 档位工具行、answer 环收据、queries 模板行、(触发后)embeddings 表。

---

## 4. Gate 草案(挂 v13 gate 族,命名待定稿)

```text
G-rag1 摄取→投影:effect 产物 → artifacts → chunks 幂等;重摄取同事务一致;
                 token 分块器 chunker_version 行自证;verify_index 通过
G-rag2 过滤装箱 :rag.ask 任何 agent 可呼;mock 下外部调用计数=0;
                 同 query×chunk 二次零付费;跨 session 复用 reused_from 正确
G-rag3 子代理   :spawn 准入(根咨询锁)实测;回程 handoff 幂等(delivery_id 重复不二次注入);
                 四值分派全绿;父 wait→子全终态唤醒恰一次
G-rag4 agentic  :recall→todo→recall 循环达 max_rounds 行为;失败 turn 不污染分位
G-rag5(触发) T1:嵌入派生行 content_hash×model 复用;RRF 一条 SQL;固定评估集证明 lexical 漏召
```

每 stage 交付形态沿用既有约定:`v13/rag_<stage>/setup_db.py + test_*.py + SQL`,加载序进 `v13/load.py`。

---

## 5. 交付排序(里程碑;每步全绿→提交→推送,AGENTS.md)

| 步 | 内容 | 依赖 |
|---|---|---|
| M1 | corpora + 摄取 effect → chunks(+token 分块器) | DP4 既有 |
| M2 | `rag.ask`/`rag.recall` 装箱:G-rag2 | DP5/DP6 既有 |
| M3 | spawn kind='rag' 档位 + agentic 循环:G-rag3/4 | §6.8 A17 落地 |
| M4 | answer 环收据 + conversation→queries | 裁决 2 |
| M5(触发) | T1 嵌入派生行 + RRF | G-rag5 触发条件 |

---

## 6. YAGNI / 后置台账(附触发条件)

| 项 | 触发条件 |
|---|---|
| OpenAI 兼容 serve 面 | 出现非 pg-agent 消费者;实现=独立 worker,绝不用 pg_net |
| OCR / 多模态装载 | 语料出现扫描件且真实检索需求 |
| pgroonga/zhparser 引入 | bigram 路径在 kohaku 类 fixture 上漏召超阈值(§4.6 既有触发) |
| reranker | 固定评估集证明 RRF 序仍不够 |
| duck RSI 批量分析(T2) | v13.1 duck_text 工作台落地后 |

---

## 7. 与既有计划的关系声明(需裁决)

- **flock-rag-on-duckdb v4.1**:其「在线检索」职责被本设计覆盖(T0/T1 全在库内);v4.1 建议降级为 **T2-only**(离线批量分析/重嵌入)。是否降级**待裁决**——v4.1 是已过审的计划,本设计不擅自取代。
- **v13.1 workbench 平面**:`duck_text` 工作台与本设计 T2 对齐,界面不冲突;`corpora` 与 `workbenches` 是否共享注册面见待裁决 4。
- **v12/v8 既有**:tools/effect/queue 面全部复用,零新机制。

---

## 8. 待裁决问题(轮 1,P0)

1. **档位完整性**:`rag.ask` 是否必须走独立会话?还是工具行直落库(零会话)即可,spawn 只留给深检索?(提案:两档并存,以会话是否产生区分)
2. **answer 环归属**:RAG 子代理内闭环生成,还是回程被评分块由父生成?(提案:默认回程父侧生成;子代理生成仅作为可选工具行——jev「回程=被评分块」)
3. **flock v4.1 关系**:确认降级 T2-only?
4. **corpora 与 v13.1 workbenches 关系**:合并注册面还是两张表?
5. **T1 嵌入表**:台账触发(提案),还是直接进核心?(v13 §7 原文倾向触发)

---

## 裁决记录

(轮 1 待填)
