# 第 10 章：RAG 即工具——检索系统的数据库化

> 前置：第 4、6、7、9 章。产出：`v13_recall` 函数族 + 装配清单（G-ctx3 / G-ctx4 / G-ctx5）。
> 对照上游：`v7`（Flock-RAG-on-DuckDB 线的教训）、autocoder 原版/nano 的拆解结论。
> 设计对照：`docs/designs/v13-context-on-pg.md` §4.1 / §4.5–§4.8、§5.2、§7。

## 10.1 这一章要做什么

把一个外部 RAG 系统（auto-coder 系）「直接数据库化」。先看清它由什么组成
（对原版 25k 行的拆解结论）：

| RAG 子系统 | 性质 | 数据库化后 |
|---|---|---|
| 文件摄取 + md5 脏检测 | 确定性算术 | ingest worker + **content_hash 谓词**（= 第 7 章免费得到） |
| 嵌入生成（ByzerLLM/真模型） | 外部 IO | **embed effect**（kind='tool'，闭集不变） |
| chunk 存储 | 状态 | **chunks 投影**（第 7 章三纪律）+ `kind='chunk'` artifacts |
| 词项 / 向量检索 | 查询 | T0 **前** stannum 性格刻画；**召回是函数**（10.4） |
| LLM 相关性过滤 | **语义判断** | **存在性 Noul 先行**，再 per-chunk Score（10.5） |
| token 分配（0.7/0.2/0.1） | 纯算术 | 跨度装配 → context artifact 内嵌 **manifest**（10.6） |
| 分阶段记账（RAGStat） | 观察 | events/effects 自带 usage——**记账免费** |
| 多进程文件锁/失败台账/合并器 | 协调 | **在 PG 里全部蒸发**（行锁/attempt/SQL 聚合） |

两个关键事实决定形状：

1. **约七成代码是协调与记账**——数据库化的最大收益恰恰是这七成在 PG 里蒸发。
2. nano 的向量阶段是装饰性的（similarity=0.1/top_k=10000 近乎全量召回，
   质量来自 LLM 过滤）——**最小路径可以完全不要向量**。承重件（两阶段 /
   过滤 / 清单）不依赖 stannum 一根毫毛；可替换的检索件关在刻画 gate 之后。

## 10.2 流程：四个目录行

```text
工具族（tools 表四行，全部走既有平面）：
  rag_ingest     handler='py'   产 chunk artifacts + 同事务写 chunks 投影
  rag_recall     kind='sql'     definition = v13_recall 一族（不是视图）
  rag_filter     （不是工具）    决策平面：存在性 Noul → per-chunk Score
  rag_assemble   kind='sql'     跨度装配 → context artifact 内嵌 manifest

一个查询的时序（套进第 5 章两阶段）：
user 消息
→ v13_parse
    v13_build_tinql(query_text)          -- 用户文本不得直接成为 TINQL
    v13_recall(...)                      -- recall = 纯 SELECT
    存在性 Noul；缺口则 per-chunk Score  -- resolve 写 decisions + IO
→ v13_advance
    rag_assemble → context artifact      -- 清单是 IR，render 是纯函数
→ llm effect 消费 render(manifest) → 回答
```

可选的 `chunk_embeddings(content_hash, model, dim, vector)` 表：
content_hash × model 键控 = nano jsonl 加速缓存的行形态。
embed 结果是派生数据，永远可从 artifacts 重算——所以它不是第二真相源。
T1 才用到它（vectorchord，台账触发，见 10.3）。

## 10.3 T0 前：stannum 性格刻画

> **数据的真相在哪，在线检索就在哪。** 源与 `kind='chunk'` 在 artifacts；
> 召回扫的是第 7 章的 `chunks` 投影。把向量放第二引擎 = 每次 ingest 维护
> 两份一致性——除非它只是投影。

**性格刻画是 T0 换引擎之前的 stage，不是 T0 本身。** 承重件先用任何能跑绿
的词项检索跑通（英文语料：tsvector 即可）；刻画 gate 全绿之后，才换
`rag_recall` 目录行的 function definition——目录行是数据，流程零改。

| 语料 | T0 怎么来 |
|---|---|
| 英文为主 | tsvector 先跑通承重件 → 刻画通过 → 换 `v13_recall` 为 stannum |
| CJK 为主 | stannum 是救命件（tsvector 默认 parser 把「東京タワー」当一个 lexeme，子串零召回）——直接以 stannum 为 T0，**但仍先过刻画 gate** |

刻画 gate 钉的是性格，不是偏好：

```text
✓ fixture 灌入后召回命中
✓ ==> 绑定矩阵：EXECUTE 绑到 stannum IndexScan；
  视图内嵌 / plpgsql 静态 / worker 预备语句直发 —— 三禁路径不得静默回落
✓ tokenizer canary：索引 tokenizer 与默认切分不同的 fixture，召回必须命中
✓ fold 持锁 p99 压测（插入毛刺记运维注记，不进核心路径）
✓ verify_index + REINDEX 演练
✓ >1024 词项展开走保守回查的行为钉断言
```

刻画通过之后的分层（设计 §7）：

| 层 | 形态 | 何时启用 |
|---|---|---|
| **T0（默认）** | 英文：tsvector 起步 → stannum（刻画后）；CJK：stannum（刻画后，救命件） | 默认 |
| **T1** | stannum + vectorchord 混合（RRF 一条 SQL）；嵌入 = 派生缓存行（content_hash × model），embed = effect | 固定评估集证明 lexical 漏召 |
| **T2** | duck worker 批量分析 / 重嵌入（RSI） | **退出在线检索，只做离线** |

T2 的合法性：嵌入是可重建的派生数据（真相 = 源 artifacts），放第二引擎不违反
「不建第二真相源」——它是投影，与第 9 章工作台同构。
**查询要 join 控制态（fresh / 未消费 / 预算）→ PG；一次性批量扫描 → DuckDB，且只在 worker 里。**

## 10.4 召回是函数，不是视图；三禁；`v13_build_tinql`

`==>` 的索引绑定依赖计划上下文：plpgsql 静态 SQL 第 6 次执行起切 generic plan，
预备语句同样；绑定不到索引时回落默认 tokenizer——**不报错，只静默漏召**。
所以召回不是一张视图，是一族函数：

```sql
-- 所有 ==> 只许出现在 v13_recall 一族体内。
-- EXECUTE（或 force_custom_plan）强制每次重规划，
-- 让 TINQL 串以计划期可见形态绑到正确索引列。
CREATE OR REPLACE FUNCTION v13_recall(p_tinql text, p_k int)
RETURNS TABLE(content_hash text, bm25 float, spans jsonb) ...;

-- 用户文本不得直接成为 TINQL。
-- v13_build_tinql：长度 / 通配 / 正则 / fuzzy / 展开上限 / 执行超时全限；
-- 语言分段，CJK 语段一律短语引用——是代码不是字符串。
SELECT v13_recall(v13_build_tinql(p_query_text), p_k);
-- 排序：ORDER BY bm25 DESC, content_hash ASC（并列截断确定性）
```

**三禁**（违反即 G-ctx3 红，不是风格问题）：

1. **视图内嵌 `==>`**
2. **plpgsql 静态 `==>`**
3. **worker 预备语句直发 `==>`**

目录行仍可叫 `rag_recall`、`kind='sql'`、只读角色可跑——那是第 5 章的
recall 权限形状。禁的是绑定路径，不是工具名。

`v13_build_tinql` 是 P1 真活：CJK 常用字在逐字切分下 IDF 趋零，排序会失灵，
但候选池不漏就不死（质量来自过滤层，nano 已证）。精确 `count(*)` 让 k 随
候选规模自适应放宽（策略行）。kohaku fixtures 钉混合查询形状。
bigram 列（`GENERATED ALWAYS AS (v13_cjk_bigram(body)) STORED` + 独立索引）
进第 15 章台账，触发条件是 kohaku 漏召率超阈值——本章不建。

## 10.5 过滤管道：存在性 Noul 先行 + per-chunk Score

默认过滤器按 chunk 缓存，不按「这一批的相对序」缓存：

```text
request_hash = hash(问题, chunk.content_hash, query.content_hash)
             + provider/model + rubric/answer schema 版本
```

顺序是闸门，不是品味：

1. **先一个存在性 Noul** 问「这批语料里有没有答案」。语料无答案时
   1 次调用替代 k 次 Score。
2. 通过后再 **逐 chunk Score**（`_many`，32/批）。
3. **全集 Choice 与逐 chunk 缓存语义冲突**——只留给「相对序本身是问题」
   的重排（台账，不是默认）。

跨 session 复用拆两行：规范答案缓存（按 `content_hash` 吸收）与本 session
使用记录（`reused_from` 映射）。复用旧行不把判断所有权留在旧 session。

这是第 4 章决策平面在检索上的原样应用：判断即行、`ON CONFLICT DO NOTHING`、
全命中零外部调用（第 5 章 G-ctx1 的同一句，单位换成 query × chunk）。

## 10.6 装配清单 schema 与跨度装配

`rag_assemble` 的产物是一份 **context artifact**（第 7 章的指针在这里兑现）。
清单是 IR，不是「把 top-k 正文拼进 prompt」：

```text
每 section：
  kind,
  cache_scope      ∈ {Global, Session, None},
  priority         ∈ {Never, First, Normal, LastResort},
  content_hash,                    -- 纪律 3：不写 chunks 主键
  est_tokens,
  payload_ref,
  churn 计数
查询侧另记：
  query_artifact_id,
  候选 content_hash / bm25 / 命中跨度 / decision_id
applied 与 skipped 变换都落行（带原因）——审计两分支
```

`render(manifest, render_policy_version, provider) → wire bytes` 是纯函数。
首版只留一种 canonical render；加 provider = 加策略行 + 一个序列化器，
装配逻辑不动。

**跨度装配与 chunk 尺寸解耦。** chunk 可以粗（整节 / 整文档：BM25 文档统计
更稳、行数更少）；装配单元是被标出的跨度 `(doc, offsets)` 进 manifest，
不是整行 body。BM25 长度归化会稀释超长文档——目标尺寸由刻画 gate 用数据
回答（先验 2–4KB）。跨度不是唯一单元：可配置前后文窗口、句段边界、
表格 / 代码块完整性、重叠合并。0.7/0.2/0.1 仍是策略行上的预算带，
读它的是装跨度的 SQL，不是切 chunk 的参数。

三种回放（exact replay / recompute / fresh fork）显式区分，不得混称——
语义在第 14 章展开；本章 gate 只要求清单字段让三种回放**可区分**。

## 10.7 逐段解释

- **召回是函数**：`==>` 绑错不报错、只漏召，所以绑定路径必须每次重规划。
  三禁是这条物理事实的 DDL 形态；`v13_build_tinql` 是用户文本与 TINQL 之间
  的唯一缝——长度 / 通配 / 正则 / fuzzy / 展开 / 超时全限，CJK 语段短语引用。
- **刻画在 T0 之前**：承重件不依赖 stannum。英文 tsvector 可以先绿；
  CJK 把 stannum 当救命件，也仍先过绑定矩阵 / tokenizer canary /
  fold 压测 / verify_index。换引擎 = 换目录行 definition。
- **存在性 Noul 是闸门**：语料里没有答案时，k 次 Score 是纯浪费。
  过闸之后的 per-chunk Score 才吃 `_many` 批处理与逐 chunk 缓存。
- **清单是 IR**：模型看见的是 render(manifest)，审计看见的是清单行
  （含 skipped）。跨度进清单，所以 chunk 尺寸不再等于装配单元。
- **新鲜度免费**：源 artifact 变了 → 第 7 章同事务重灌投影 → 旧 hash
  对 recall 不可见。v9 的「freshness 是谓词不是管线」原样适用。
- **v7 的教训不是「DuckDB 不行」**：是「别为 RAG 建第二真相源」+
  「别在跑通 loop 之前冻结证据体系」。刻画 → T0 →（台账）T1 → 离线 T2
  就是对这个教训的程序化。
- **fail-closed 细节**：空内容不产 placeholder 向量（nano 的做法）——
  空 chunk 拒绝入库，错误信封带原因。TINQL 注入同样 fail-closed。

## 10.8 硬性规定与 gate

```text
G-ctx3（召回）断言：
✓ 所有 ==> 只出现在 v13_recall 一族；EXECUTE 的 EXPLAIN (FORMAT JSON)
  出现 stannum IndexScan，chunks 无 Seq Scan
✓ 三禁：视图内嵌 / plpgsql 静态 / worker 预备语句直发 ==> ——
  tokenizer canary 不得静默漏召（回落即红）
✓ 用户文本经 v13_build_tinql：超限 / 注入 fail-closed 信封；
  kohaku fixtures 钉混合查询形状（CJK 语段短语引用）
✓ ORDER BY bm25 DESC, content_hash ASC，并列截断不抖
✓ count(*) 自适应 k 生效

G-ctx4（过滤）断言：
✓ 存在性 Noul 先行：语料无答案时 Score 外部调用 = 0（mock 计数）
✓ 同 query × chunk 二次过滤零外部调用
✓ per-chunk 缓存跨 session 复用（reused_from 指向规范行，所有权不留在旧 session）

G-ctx5（清单）断言：
✓ manifest 含 10.6 全字段（kind / cache_scope / priority / content_hash /
  est_tokens / payload_ref / churn + 查询侧 hash / bm25 / 跨度 / decision_id）
✓ applied 与 skipped 双分支都落行
✓ 三种回放可区分（字段能分开 exact replay / recompute / fresh fork）
✓ 装配单元是跨度 (doc, offsets)，不是 chunks 主键、也不等于 chunk 行宽
✓ est_tokens ≤ 策略行预算

摄取（第 7 章 G-ctx2 在检索路径上的回响）：
✓ 同源重 ingest 与新 artifacts 同一事务重灌投影
✓ 源文件变更后，旧投影行对 v13_recall 不可见
```

## 10.9 检查点练习

1. 实现 `v13_build_tinql` + `v13_recall`：kohaku 混合查询的 TINQL 形状
   有断言；只读角色可跑；`ORDER BY bm25 DESC, content_hash ASC`。
   再造三禁：把同一 `==>` 放进视图、放进 plpgsql 静态 SQL、经由预备语句
   直发——tokenizer canary 必须红，不得静默漏召。
2. 过滤管道：先造「语料无答案」——存在性 Noul 拒绝后 Score 调用计数 = 0。
   再造同 query × chunk 第二次过滤，外部调用仍为 0。
3. `rag_assemble` 写出 10.6 的清单字段；applied / skipped 都有行。
   改策略行预算带，断言装入的跨度变化、chunk 行本身不必重切——
   **跨度装配与 chunk 尺寸解耦**。
4. （可选）T2 演练：chunk 水化进 duck worker 做离线重嵌入。记录数字——
   这是「何时值得离开在线检索」的经验数据，不是 T0 的前置。

## 10.10 回到 vN 对照

- `v7/evidence/contracts/auto_coder_longcontext.md`：原版配置的冻结调查
  （含 relevant_score 类默认 2 vs CLI 5 的矛盾）——v13 只有一个权威：策略行。
- `v6/queue_bridge`：T2 投影的同步机制前身（enqueue-only + 快照）。
- 第 7 章 chunks 三纪律是本章召回的地表；第 5 章三角色是
  `v13_recall`（SELECT）/ 过滤（resolve）/ assemble（route 之后的 sql 动作）
  的权限形状。

## 10.11 内在合理性：前因后果

**作用力。** 先列事实——它们关于运行环境，不关于任何设计偏好：
**`==>` 绑错不报错**，只静默漏召——generic plan 与预备语句都会让索引
绑定离开计划期可见的 TINQL 串。**BM25 是语料统计的函数**，IDF 随 ingest
漂移，视图不能当审计来源。**检索质量的真实来源是语义过滤**——对照实验里
相似度阈值低到近乎全量召回、top_k 放到一万，答案质量不掉，因为把关的是
逐 chunk 的相关性打分。**判断调用有成本**：语料里没有答案时 k 次 Score
是纯浪费。**嵌入是派生数据**：换模型、改分块参数都要整批重算。
**在线检索必须同时看到控制态**：chunk 能否进入回答，取决于源文件是否已变、
本 turn 是否已消费、token 预算还剩多少。**stannum 是 dev software**：
fold 持 meta 锁、新连接重建 buffer index、CJK 逐字切分、>1024 展开走
保守回查——可替换件，不是承重件。

**推导。** 绑错会静默漏召 ⇒ 召回必须是函数，经 EXECUTE 每次重规划；
视图 / 静态 SQL / 预备语句直发是三禁，不是风格。用户文本会带通配与正则 ⇒
中间加 `v13_build_tinql`，CJK 语段短语引用，超限 fail-closed。
stannum 可替换且有性格 ⇒ T0 之前插刻画 stage；英文 tsvector 可以先绿，
CJK 把 stannum 当救命件也仍先过 gate；换引擎只换目录行 definition。
质量来自过滤、过滤是语义判断、判断有成本 ⇒ 先一个存在性 Noul 闸住整批，
再 per-chunk Score 吃逐条缓存；全集 Choice 与这条缓存语义冲突，不进默认。
装配要证明「当时发现了什么、实际交给模型什么」⇒ context artifact 内嵌
manifest（IR），applied / skipped 双分支落行。高亮跨度是 `(doc, offsets)` ⇒
chunk 可以粗，装配单元与行宽解耦。检索要 join 控制态 ⇒ `v13_recall` 以
`kind='sql'` 住在真相所在的库、同事务只读；跨库 join 等于把一致性问题
请回来，批量扫描才去 DuckDB，且只在 worker 里。摄取并发会失败 ⇒ 脏检测
是 content_hash 谓词，重灌与新 artifacts 同一事务（第 7 章纪律 2）。

**反事实。** 让向量住进第二引擎并当真相（不是投影），失败时序：
第 1 步，ingest 事务在 PG 提交成功——新 chunk 落库、旧投影随源文件变更
按第 7 章纪律 2 重灌；第 2 步，向第二引擎的同步在此刻失败（worker
崩溃、网络断开），PG 侧已提交，无物可回滚；第 3 步，在线检索继续查
第二引擎：已删除的内容照常返回、新内容查不到，且不一致是静默的；
第 4 步，用户拿到过时回答，复盘要跨两个系统对账。若补一个同步器兜底：
队列、重试、对账三件套随之而来——刚蒸发的协调复杂度被原样重建在库外。

把 `==>` 放进视图或 plpgsql 静态 SQL：第 6 次执行切 generic plan，
TINQL 串不再以计划期可见形态绑定，回落默认 tokenizer——gate 若只看
「有没有返回行」会绿，tokenizer canary 才红。跳过存在性 Noul 直接
逐 chunk Score：语料无答案时付 k 次款，缓存帮不上——问题变了，hash
全变。把整行 chunk 当装配单元：要么切细（行数爆、BM25 统计不稳），
要么切粗（超长文档被长度归化稀释，又把表格 / 代码块从中间切断）。

**被拒替代。** 其一，**专用向量库做第二真相源**：ingest 与索引更新构成
跨系统双写，双写必有不一致窗口，还多出一个运维面；在「嵌入可重算」
的力下它至多提供投影，而投影不需要新真相源。T1 的 vectorchord 停在
台账里，直到固定评估集证明 lexical 漏召。其二，**用消息队列作摄取的
真相源**：at-least-once 下队列不持久、不判重。其三，**整体引入外部
RAG 系统**：判断、预算、审计全部让渡给黑盒——同题打分无法命中缓存，
清单从 IR 变成别人代码里的拼接，事后无法 SELECT 复盘。其四，
**召回写成视图 / 静态 SQL / 预备语句**：静默漏召，三禁就是对它的拒绝。
其五，**跳过刻画把 stannum 焊进 T0**：承重件被一件 dev software 的
fold 毛刺与 tokenizer 回落绑死；正确顺序是承重件先绿，刻画再换 definition。
