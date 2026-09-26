# v13 → stannum 0.4.0 适配面档案（v13 侧）

> 探针产出，2026-09-26。只调研，零改动。所有行号以当前工作树为准。背景报告（使用核查 / 结案）的结论直接引用，不重做。

**已落地前提**：`v13/mgraph/test_stannum_usage.py` 已存在并由 `e6fe89b` 提交（65 断言），`v13/mgraph/README.md:14` 已加指向行。使用核查文档 C 节的第二阶段**已完成**，本档案的 gate 影响分析按「已交付的 65 断言 gate」叠加。

---

## 1. 表形态（四张被 stannum 索引的表）

| 表 | DDL | 列（全部） | 文本列 |
|---|---|---|---|
| `chunks` | `v13/chunks/v13_chunks.sql:141-156` | `source_hash text`、`chunk_no int`、`body text NOT NULL`、`content_hash text`、`chunk_offset bigint`、`corpus text`、`chunker_version text`、`analyzer_version text`、`body_tsv tsvector GENERATED` | **仅 `body`** 自由文本。`corpus`/`chunker_version`/`analyzer_version` 是低基数标签不是语义正文 |
| `transcript_chunks` | `v13/memory/v13_memory.sql:18-28` | `session_id uuid`、`seq_from bigint`、`seq_to bigint`、`body text NOT NULL`、`content_hash text` | **仅 `body`** |
| `memory_nodes` | `v13/mgraph/v13_mgraph.sql:25-45` | `session_id uuid`、`content_hash text`、`body text NOT NULL`、`origin text CHECK(episodic/consolidation)`、`source_hashes text[]`、`source_at timestamptz`、`builder_version int`、`consolidation_key text` | **仅 `body`** |
| `decisions` | `v13/schema/v13_core.sql:393-424` | `decision_id uuid`、`session_id uuid`、`signal text`、`kind text`、`question text`、`criteria jsonb`、`context jsonb`、`answer jsonb`、`provider text`、`model text`、`request_hash text`、`status text`、`created_at`/`answered_at timestamptz` | **仅 `question`**，且被 `CHECK (question ~ '^[\x20-\x7E]+$' …)` 钉成 ASCII（`:398-399`） |

**值得加权/分字段的列：一张都没有。** 没有 title / role / source / summary 类语义列。适配调查已逐表核实并记为「天然单文本列，L3 无即期落点」（`docs/investigations/v13-stannum-0.4-pgembed-adaptation-2026-09-25.md:156-163`）。唯一形态接近的是 `decisions.signal`（路由信号名，如 `'intent'`），但它是枚举身份不是自由文本。

**语言形态**：
- `chunks`：英文为主 + 一条日文混合夹具（`test_characterize.py:364-371`：4 篇 quasar/redshift 英文 + `"東京タワーは電波塔である kohaku"`）。
- `transcript_chunks`：中英混排。夹具 `test_memory.py:442-457`（`東京タワー` + `quasar` + `unrelated interlude`）、`:493`（`"private session text quasarium"`）。生产侧注释明写「记忆语料 CJK 为主」（`v13_memory.sql:30-31`）。
- `memory_nodes`：纯中文为主。G5/G6 夹具 `test_mgraph.py:2712` 用 `"用户无法登录系统因为密码过期"`；A1 用一句英文 `:326`。查询夹具 `为什么用户无法登录`（`:2740`）。
- `decisions`：纯英文（DDL 强制 ASCII）。

**夹具典型行数（都很小，全部是个位到两位数）**：
- `chunks`：5 篇文档 → 每篇 1 chunk（`test_characterize.py:364-371`）。canary 表 3 行 + M2 时序插入 500 行（`test_characterize.py:530`）。
- `transcript_chunks`：每 session 2–3 条 curated 事件，`v13_rebuild_transcript_chunks` 后 1 行/事件（`test_memory.py:462-466`、`:492-495`）。p99 组才上到几十条（`:538-543` 的 `append_loop`）。
- `memory_nodes`：G5/G6 恰 1 行（`test_mgraph.py:2712` `put_nodes(cur, ["用户无法登录系统因为密码过期"])`）；G4 用 2 行（`:2672-2675`）。`put_nodes` 是逐 body 一行（`test_mgraph.py:1446-1458`）。
- `decisions`：1 行量级（`test_memory.py:643-645`）。

> 对适配的含义：所有生产表都 < 100 行，规划器极易选 Seq Scan；jitbag/plan 断言必须 `enable_seqscan=off`（现有 gate 全部如此）。另外因为 `field_weights` 单列即报错，**当前 schema 下 0.4.0 的 BM25F 能力对 v13 零落点**，除非先加第二自由文本列（那是 M5 事件门）。

---

## 2. 四条动态 SQL 的完整谓词形状

四条全部是 `RETURN QUERY EXECUTE` / `EXECUTE` 拼纯字面量 + `$n` 参数（可被全文抽取器比对，`test_stannum_usage.py:28-53` 的 `EXPECTED_SQL` 就是逐字副本）。

| 函数 | 位置 | 谓词（除 `body ==>` 外） | 排序/限制 |
|---|---|---|---|
| `v13_recall` | `v13_characterize.sql:104-112` | `JOIN v13_sources src ON src.source_hash = c.source_hash AND src.superseded_by IS NULL`（**superseded 过滤**，不是 session） | `ORDER BY bm25 DESC, content_hash ASC LIMIT $2`，`bm25 = stannum.full_score(c.ctid)::numeric` |
| `v13_recall_count` | `v13_characterize.sql:125-129` | 同一个 sources join + `superseded_by IS NULL` | 无排序，`count(*)`，不计分 |
| `v13_transcript_recall` | `v13_memory.sql:149-155` | `t.session_id = $1`（**per-session 隔离**） | `ORDER BY bm25 DESC, content_hash ASC LIMIT $2` |
| `v13_mgraph_candidates` | `v13_mgraph.sql:751-757` | `n.session_id = $1 AND n.origin = 'episodic'`（**session + 来源枚举**） | `ORDER BY n.content_hash ASC`（**不按分排序**，打分后在外层 plpgsql 里归一化融合，`:764-781`） |

**能否用 `search()` 替代：不能。** 三条阻塞（适配调查 `:93-103`，与本次核查一致）：
1. `search(index, query, limit, …)` 无过滤参数 → 只能「先 top-k 后过滤」，与 v13 的「过滤后 top-k」不等义（superseded 行占坑、session 语料占比小时整表 top-k 几乎必然空手）。
2. `v13_recall` 的 spans 载荷是字节级契约，被 `test_chunks.py:805-809,1297-1337,1347-1376` 大量钉死；`search()` 的 snippet 窗口语义未实证（截断则反推偏移相对窗口而非原 body）。
3. `v13_recall_count` 同理（sources join + superseded）。

另注意：`v13_mgraph_candidates` 的 `ORDER BY content_hash ASC` 与另三条的 `bm25 DESC` 不同——BM25 只作为 `lexical_norm` 的一个分量进线性融合（`v13_mgraph.sql:764-776`）。任何「换引擎/换打分」方案都不能假设四条同序。

---

## 3. tinql 语法与锚

**三层文法，两个发射器，一个入口守卫。**

| 对象 | 位置 | 发射形态 |
|---|---|---|
| `v13_query_segments` | `v13/recall/v13_recall.sql:13-75` | 码点分类（latin / cjk 五区间 / sep），返回**裸段文本** JSON 数组，不带引号。sep = 任何非 latin 非 CJK 字符（含中文标点 `，。？`）。上限 64 段 / 每段 256 B / 总 4096 B |
| `v13_build_tinql` | `v13/recall/v13_recall.sql:77-81` | `string_agg('"' \|\| s \|\| '"', ' AND ')` → **AND 形**，每段整体引号包裹 |
| `v13_tinql_terms` | `v13/recall/v13_recall.sql:83-119` | 入口守卫：`string_to_array(p_tinql, ' AND ')`，逐段验引号、禁内嵌引号、段 0<len≤256、≤64 段 → 否则 `V3005`。**被 `v13_recall` / `v13_recall_count` / `v13_transcript_recall` 三处 PERFORM** |
| `v13_mgraph_anchor_terms` | `v13/mgraph/v13_mgraph.sql:3201-3237` | **latin 段整项**（`^[A-Za-z0-9]+$`，`:3216`）+ **CJK 段按字符滑窗 n-gram**（`:3221-3233`，`substring(v_seg FROM v_i FOR v_n)`，`v_n` 来自策略键 `anchor_ngram_n`=3，`:3211`），去重保序，`anchor_max_terms`=48 截断（`:3212,3215`）。边界钉死：段长度=n 恰一项，<n 零项 |
| `v13_mgraph_anchor_tinql` | `v13/mgraph/v13_mgraph.sql:3240-3244` | `string_agg('"' \|\| t \|\| '"', ' OR ')` → **OR 形**闭集 |
| `v13_mgraph_anchor_guard` | `v13/mgraph/v13_mgraph.sql:3252-…` | `string_to_array(p_tinql, ' OR ')`（`:3267`），验引号 / 禁内嵌引号 / 段 ≤256 B / 项数 ≤`anchor_max_terms`（`:3269-3288`），再逐字符过白名单（latin ∪ CJK 五码点区间，`:3289-3294`）→ 否则 `V3005`。返回规范化项集供 entity/keyword 子项复用 |

**CJK 3-gram OR 锚的实现位置 = `v13_mgraph.sql:3221-3233`**（`ELSE` 分支的 `substring` 滑窗），由 `v13_query_segments`（`:3213`）喂段。

**关键文法不对称**：AND 形与 OR 形**互斥**。`v13_mgraph_candidates` 入口只挂 `v13_mgraph_anchor_guard`（`:742`），把 `v13_build_tinql` 的 AND 形送进去必 `V3005`（核查文档 C.2 明文）。这是「四条动态 SQL 里只有 mgraph 一条是 OR」的根因，也是任何「统一 tinql 发射器」方案的第一堵墙。

---

## 4. 会被翻红的既有 gate

### 4.1 L3 — CJK 短语命中 / 单字片假名 miss
`v13/characterize/test_characterize.py:495-503`
- 断言：`v13_recall(v13_build_tinql('東京タワー'), 8)` 行数 ≥ 1；canary doc 3 命中；`v13_build_tinql('タ')` 的 recall **为空**。
- **怎么翻**：切 `tokenizer=jieba` 后 `タ` 命中 doc 3/4/10/11 → 「single Katakana miss」翻红（jieba 探针 `:139`、`:379`）。整段 `東京タワー` 两条保持绿（jieba/unicode 都命中 doc 3/4）。探针结论：单字 miss 是 unicode 把片假名连跑收成一个 token 的物理事实，引号 workaround 摘不掉它（`:170`、`:413`）。

### 4.2 K1 — Custom Scan 钉死
`v13/characterize/test_characterize.py:376-391`
- 断言：`SET enable_seqscan=off` 下手写 `SELECT c.content_hash FROM chunks c WHERE c.body ==> %s` 的计划里有 `Node Type == "Custom Scan"` 且 `Custom Plan Provider == "Stannum Text Search Scan"`、`Index == "ix_chunks_stannum"`，且无 `chunks` 的 Seq Scan。
- **怎么翻**：①给 `chunks` 加第二文本列/改 reloption → 计划形状可能变 Bitmap；②关掉 `stannum.enable_custom_scan`（默认 on，`:152`）→ Custom Scan 消失只剩 bitmap；③把 `v13_recall` 的动态 SQL 改成 `search()` 形态 → provider 变 Function Scan。**K1 只钉手写 SQL，不钉 `v13_recall` 内部带 JOIN 的那条**（核查文档 A.7 已点名这个缺口）。

### 4.3 G6 — 锚查询
`v13/mgraph/test_mgraph.py:2723-2757`（三件事）
1. `norm_g6.count("==>") == 1`（`:2726-2727`）—— 源码计数。
2. 三个 anchor 函数 `pg_get_functiondef` 必须 STABLE、无 `EXECUTE`、无 `==>`、无 PUBLIC grant（`:2728-2739`）。
3. `v13_mgraph_anchor_tinql('为什么用户无法登录')` 驱动 `EXPLAIN (ANALYZE)`：无 `Seq Scan on memory_nodes` 且计划文本含 `stannum`；并且 `count(*) == 1`（`:2749-2757`）。
- **怎么翻**：jieba 索引上 7 个 3-gram OR 全灭 → `count(*)=1` 变 0（探针 `:157-159`、`:168`、`:381`）。必须同提交把 `anchor_terms` 的 CJK 分支改成词级，否则 mgraph 锚池空转。改 `v13_mgraph.sql` 的 `==>` 出现次数也会翻第 1 条。

### 4.4 R 组源码计数（逐文件 `==>` / `stannum.` 出现次数）

| gate | 断言位置 | 计数 |
|---|---|---|
| characterize **R2** | `test_characterize.py:840-860` | `files_through("characterize")` = 9 个文件；前 8 个 `==>`=0 且 `stannum.`=0；**第 9 个（`v13_characterize.sql`）`==>`=2、`stannum.`=3**（去注释）。另 `NORM_FIXTURE` 计数 2/1（`:841-842`），`v13_recall.sql` 原样 0/0（`:858-860`） |
| memory **K4** | `test_memory.py:527-532` | `v13_memory.sql` 去注释 `==>`=1、`stannum.`=3 |
| mgraph **G6** | `test_mgraph.py:2724-2727` | `v13_mgraph.sql` 去注释 `==>`=1 |
| recall **G1** | `test_recall.py:1063-1072` | `files_through("recall")` = 8 个文件，每个 `==>`=0 且 `stannum.`=0 |
| filter **H6** | `test_filter.py:2544-2547` | `v13_filter.sql` 去注释 `==>`=0、`stannum.`=0 |
| economy **A5** | `test_economy.py:546-550` | 同上 0/0 |
| periphery **A5** | `test_periphery.py:376-377` | 同上 0/0 |
| 新 gate **R21** | `test_stannum_usage.py:1211-1221` | 12 个 `setup_db.py` 的 GRANT 块与 `v13/mgraph/setup_db.py:41-47` 逐字相同，且全文不含 `full_score`；更早 8 个 stage 不含 `GRANT USAGE ON SCHEMA stannum` |

**怎么翻**：任何把引擎调用写进新文件、或在 file9/file11/mgraph 里增减一次 `==>` / `stannum.` 的改动都会红。这是「引擎调用收敛点唯一」不变量（不变量 7 同族）的执法面，适配调查 `:218` 明写「禁止为了过 gate 放宽计数或加 OR 分支」。

### 4.5 其他连带
- **K3**（`test_memory.py:499-525`）：断言计划文本含 `score_bound_indexed` + `transcript_chunks_pkey` + `Bitmap Index Scan` + 无 Seq Scan。改成 `search()` 形状即碎。
- **K3/L1/L2**（`test_characterize.py:407-429`）：canary `max_token_bytes=64` vs 默认 256 的差值是「绑定命中 / 标量 miss」的证据源。动 canary reloption 会翻。
- **B3**（`test_recall.py:603-615`）：recall 库的 `v13_recall` 仍是 tsvector 体，与 stannum 路径不同，探针明写**不要**改成 jieba 期望。
- **M1**（`test_memory.py:638-642`）：decisions 索引恰一行。
- **E2 / G9**：路由面，jieba 打不动，但任何改 `v13_mgraph_route` 的计划会同时翻这两个（E2 `test_mgraph.py:1606-1614`、G9 闭集 `:2792-2797,:2825-2828`）。

---

## 5. cron 与巡检面

**调度器 = pg_cron**（`CREATE EXTENSION IF NOT EXISTS pg_cron` 包在 `DO $cron$ … EXCEPTION WHEN OTHERS THEN RAISE NOTICE … RETURN` 里，不可用则降级为外部调度，函数保持手动可调）。

| job | 注册位置 | 命令体 | 频率 |
|---|---|---|---|
| `v13-verify-chunks` | `v13/chunks/v13_chunks.sql:1137-1151`（`cron.schedule` 在 `:1147-1148`） | `SELECT v13_verify_chunks(true)` | `17 3 * * *`（夜跑） |
| `v13-sweep-transcript` | `v13/memory/v13_memory.sql:214-228`（`cron.schedule` 在 `:224-225`） | `SELECT v13_rebuild_transcript_chunks(100)` | `*/5 * * * *` |

**关键缝**：cron job 的命令体是**字符串快照** `SELECT v13_verify_chunks(true)`。characterize 用 `CREATE OR REPLACE FUNCTION v13_verify_chunks` 把第八项 check 换成 `stannum.verify_index('ix_chunks_stannum', true)`（`v13_characterize.sql:133-222`，stannum 项在 `:190-192`、`:211-213`），**签名不变**，所以同一条 cron job 自动升到 v2 面（返回 `version=2`，`:220`）。不需要动 cron。

**`v13_verify_memory` 的挂法 = 不挂 cron**：`v13_memory.sql:163-164` 注释明写「手动可调 + gate；夜跑 cron 扩展不做——DP4 job 保持唯一 verify 面，§7 台账」。函数体 `:165-206`，owner-only（`:245-247` REVOKE 后未授出），内含 5 项 check，其中 ④⑤ 是 `verify_index`（`:181-186`）。触发条件是「第二消费者出现」（DP6 计划 `:1917` 台账）。

**没有任何 job 调 `v13_verify_mgraph`**——该函数不存在（核查文档 B.2）。`ix_memory_nodes_stannum` 被检索但无生产校验。

**cron 面 gate 断言**：chunks 恰一条（`test_chunks.py:1107-1109`）、characterize 恰一条（`test_characterize.py:655-659`）、memory 恰两条按名排序（`test_memory.py:696-699`）。任何新增 stannum 巡检 job 都会翻这三条。

---

## 6. B12 ACL 缺口的完整证据链

**名义授权**：`v13/mgraph/v13_mgraph.sql:1211-1212`
```sql
GRANT EXECUTE ON FUNCTION v13_mgraph_candidates(uuid,text,int)
TO v13_recall;                               -- M3 读环锚复用(同写路径函数)
```

**为什么走不通**：`v13_mgraph_candidates` 是 INVOKER 权能（全树零 DEFINER，`v13_mgraph.sql:18`），其内部依赖四个函数：
- `v13_mgraph_entities_of(text[])` — 调用点 `:749`
- `v13_mgraph_entities(text)` — 调用点 `:770`
- `v13_mgraph_keywords_of(text[])` — 调用点 `:750`
- `v13_mgraph_jaccard(text[],text[])` — 调用点 `:770,771`

这四个 + `v13_mgraph_candidates` 本身在 `v13_mgraph.sql:1204-1209` **只授 `v13_resolve`**：
```sql
GRANT EXECUTE ON FUNCTION
  v13_mgraph_entities_of(text[]), v13_mgraph_entities(text),
  v13_mgraph_keywords_of(text[]), v13_mgraph_jaccard(text[],text[]),
  v13_mgraph_candidates(uuid,text,int),
  v13_mgraph_pair_questions(...), v13_mgraph_apply_relations(uuid), v13_mgraph_build(uuid,int)
TO v13_resolve;                              -- 写路径驱动面(resolve_login)
```

所以 `v13_recall` 直调 → `42501`，错误文本含 `v13_mgraph_entities_of`（新 gate R8a 实证：`test_stannum_usage.py:1128-1129`）。

**内部 invoker 依赖清单**（`v13_mgraph_candidates` 体 `:730-782` 内）：
| 依赖 | 行 | 授权面 |
|---|---|---|
| `v13_mgraph_anchor_guard` | `:742` | 零 PUBLIC grant（G6 `:2735-2739` 断言），靠 owner/函数调用方继承 |
| `v13_mgraph_policy` | `:743` | 读 `v13_policies`，三角色有 SELECT（`test_economy.py:553-557`） |
| `v13_mgraph_entities_of` | `:749` | **仅 `v13_resolve`** ← 断点 |
| `v13_mgraph_keywords_of` | `:750` | **仅 `v13_resolve`** ← 断点 |
| `v13_mgraph_entities` | `:770` | **仅 `v13_resolve`** ← 断点 |
| `v13_mgraph_jaccard` | `:770-771` | **仅 `v13_resolve`** ← 断点 |
| `v13_query_segments` | `:773` | IMMUTABLE，PUBLIC 可执行 |
| `stannum.full_score` / `==>` | `:753,755` | PUBLIC EXECUTE + schema USAGE（12 个 setup_db 的 GRANT 块） |

**读环调用方三处，全部只在 resolve 授权面**：
| 调用方 | 行 | 性质 | EXECUTE 授给 |
|---|---|---|---|
| `v13_mgraph_build` | `v13_mgraph.sql:1040` | 写路径 | `v13_resolve`（`:1209`） |
| `v13_mgraph_anchors` | `:1684` | **读环** | 仅 `v13_resolve`（`:2593-2609`，具体 `:2598`） |
| `v13_mgraph_transition_score` | `:1802` | **读环** | 仅 `v13_resolve`（`:2604`） |

后两处是读环函数，**没有授给 `v13_recall`**，所以「以 `v13_recall` 执行读环」的调用方在树上根本不存在。`:1211-1212` 是一条死授权。同族先例 = 装配交付时 J9 暴露的四个 INVOKER 链 ACL 缺口（`v13/mgraph_assembly/README.md` 第 9 条）。待用户裁决：补内部授权 / 移除死授权 / 落地 recall 侧读环调用方。**R8a/R8b 只锁现状，不改 GRANT**（`test_stannum_usage.py:1125-1131`）。

---

## 7. M4 / jieba 先决的逐字要求

### 7.1 结案文档的整包先决（原文）
`docs/plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md:28-32`：
> 「旧阻塞『OQ13/OQ14 未裁或 mgraph v2 未交付』已经满足，而且裁决是 D；那不再是阻塞。M4 仍阻塞：**整包先决 + 须正式 supersede OQ15**。本文件不执行该 supersede。」
> 「不切生产索引。chunks / transcript_chunks / memory_nodes / decisions 的生产索引保持 unicode。`decisions.question` 永不切换。`v13_mgraph_anchor_terms` 保持 CJK 字符 3-gram。」
> 「将来的整包不是本循环。那一包要同时交付：**词级锚、L3 重写且不用 OR 放宽、一条新的 highlight 绑定断言，以及同一次提交里重写的 G6。**」

`:14-15`（动笔前核对）：「OQ15 已交付为字符 3-gram，策略键为 `anchor_ngram_n=3`」「jieba 探针 §9 的裁决是不切生产索引；将来若再议，只接受整包，不接受先改 reloption」。

### 7.2 jieba 探针 §9 的七条整包要求（原文）
`docs/investigations/v13-jieba-canary-probe-2026-09-25.md:391-405`：
1. **anchor 同切** — 3-gram 在 jieba 上整段 OR 零命中，不改锚函数 G6 必红。
2. **L3 重写，不放宽** — 断言应改成「单字片假名命中含该字的文档」并写明这是**过召回**，禁止用 OR 把新旧行为都判绿。
3. **highlight 绑定先验证再切** — 必须有一条「jieba 索引命中行的 `v13_extract_spans` 字节区间 = 绑定 highlight 区间」的新断言；做不到就改 `extract_spans` 调用形状，而不是关掉 spans 检查。
4. **引号 workaround 留着** — 它守 tinql 文法，不守片假名 miss。
5. **`decisions.question` 不在包内。**
6. **排期仍串在 OQ13/OQ14 之后**（注意：结案 `:28` 已宣布这条旧阻塞解除，但探针 §9.6 是更早的原文，两条的关系由结案的「权威顺序」段 `:5-7` 裁定）。
7. **治理写进 runbook，不写进 SQL。**

末句 `:405`：「部分切（只切 memory_nodes、不切 chunks）在第 1–3 条没完成前同样不成立：G6 就在 memory_nodes 上。」

### 7.3 探针核心结论
- **3-gram OR 7/7 miss**：查询 `为什么用户无法登录` 的 7 个 3-gram，unicode 命中 doc 13，jieba **全灭**（`:14`、`:157-159`、`:168`）。其中 4/7 个 gram 在 unicode 命中（逐 gram 表 `:162-167`）。
- **片假名反向**：jieba 把片假名（含长音 `ー`）拆单字 → `タ` 命中 doc 3/4/10/11；unicode 收成一个 token `タワー` → 只命中纯单字 doc 11（`:13`、`:139`）。引号摘不掉（`"タ"` 与 `タ` 命中集相同，`:170`）。
- **四时刻不对称**：列变量 highlight 跟索引 tokenizer；`v13_extract_spans` 的 4 参 text 重载（`v13_characterize.sql:59`，传的是变量不是列）走默认 unicode。单字片假名场景下「召回有、spans 空」（`:221`）。
- **`decisions.question` 不切**：DDL `^[\x20-\x7E]+$`（`v13_core.sql:398-399`），英文 token 两边逐字相同（`:19`、`:387`）。
- **性能**：jieba 首查 178–224 ms（中位 196）、RSS +95 MB；调查稿「~100 ms + 数 MB」偏小（`:275`）。4000 行建索引冷 220–333 ms、热 27 ms vs unicode 22 ms（`:280-287`）。查询 CPU 15 行上无回归（`:291-301`）。
- **治理**：版本戳只在 `index_stats.analysis_detail` / `index_analysis`，`\d` 看不到（`:319-340`）；`WARNING` 与 `strict_analysis` 硬错误**只挂 Custom Scan 执行路径**，强制 Seq Scan 的 recheck 不执法（`:351-371`）。

### 7.4 OQ15 supersede 的原文要求
结案 `:24`（M3 段，同款句式适用于 OQ15）：「本文件不是重开文书。不要把本文件读成已经取代 DP9-OQ3。未来若另立重开计划，须由那份计划自己写出 **`supersedes DP9-OQ3`** 这一短语」。M3-stop 文档 `:104` 复述为「正文自写 `supersedes DP9-OQ3`（计划 :354，结案 :24）」，并把 jieba/OQ15 单列为「另一张 supersede，不由①解锁」（`:112`）。

**没有文件写 `supersedes OQ15`** —— 这是 M4 的硬闸。M3-stop 文档 `:34` 明确：`supersedes DP9-OQ3` 只出现在结案里且是禁止句。

---

## 8. M3 stop 文档「如何推进」要点

`docs/investigations/v13-m3-stop-why-and-how-to-advance-2026-09-25.md` 的 Recommendations（`:152-157`）：

1. **第一份可写代码的新计划 = jieba 整包**，明文 supersede OQ15，一次提交。**不写** `supersedes DP9-OQ3`。同提交交付四件：`v13_mgraph_anchor_terms` CJK 分支改词级（`:3230-3237`）、L3 改成「单字片假名命中含该字的文档」并标明过召回（禁 OR 宽化）、新断言「jieba 命中行上 `v13_extract_spans` 字节区间 = 绑定 highlight 区间」、G6 的 `count(*)=1`（`test_mgraph.py:2756-2757`）改成词级 OR 命中。**生产索引与锚一起切**。`decisions.question` 不切（`v13_core.sql:398-399`）。不改 `v13_mgraph_route`、E2、G9 对 `routing_intent_*` 的拒绝。
2. **并行的只读文书**：定义并测量 §8 三条。先定义「可遍历」，再按 `causes`/`entity`/`contradicts` 分开记；禁止把 2026-09-24 重跑标成①已绿。②③在重跑 `:56` 仍是 4/4 superset；这份文书测不到「已满足」就停。不改 route。
3. **路由实现计划今天不写**。要等测量文书对三条各自留下「已满足」的 file:line，再另立计划，正文自写 `supersedes DP9-OQ3`，先做 P1-8 只读 helper，再同提交改 `:1505-1506` 短路、E2（`:1606-1614`）和 G9 闭集（`:2825-2828`）。**jieba 提交排在路由计划后面**，避免两线同改 `test_mgraph.py`。测量本身不是 jieba 的前置。
4. **M5/M6 维持结案台账**：不发明第二文本列，不设 `field_weights`，不配 vchord，不把无过滤 `search()` 抄进主链。

**新计划必须包含的十行**（`:102-113`）另含：不改冻结的 `v13_query_segments`（`v13_recall.sql:13,70-72`）；`edges_used=0` 不得写成已行使；`caused_by` 不得顶替 `causes`；谓词写进断言名。

---

## 9. 0.4.0 行为差异对现有 gate 的风险

0.4.0 的 SQL 面**只增不改**（两个 `highlight` 尾参重载，无默认值 → 旧 1-4 参调用不受影响；适配调查 `:79`）。会踩到 v13 的差异**全是行为，不是签名**（核查文档 B.8，`:225-231`）：

| 0.4.0 行为 | v13 暴露 | 对现有断言的影响 |
|---|---|---|
| **same-field 短语规则**（Lucene 同场规则，作用于**带字段组**的位置查询） | v13 的 tinql 是**不带字段前缀**的裸引号段（`v13_build_tinql` / `v13_mgraph_anchor_tinql`） | **零**。单列索引上左操作数已唯一，没有第二个字段可误配 |
| **`==>` 按左操作数列收窄** | 同样要多列索引才有区别 | **零**。五个 v13 索引全是 `indnatts=1`（新 gate P12 / F12） |
| **BM25F + `field_weights`** | 只发生在记录了字段权重的多列索引上 | **零**。五个索引仍是单列 BM25，`k1=1.2`、`b=0.75` |
| **5 参 field `highlight`** | v13 用 4 参 text 重载 | **零**。无默认值 → 旧调用不会误绑（新 gate V6/V7 已实证 4 参与 5 参 field=NULL 相等） |
| **LSG4 段格式** | 多列才写 LSG4 | **零**。单列继续写 LSG3，0.3.0 建的索引读不变；旧二进制打不开 LSG4 的风险 v13 现在不承担 |
| **`XX000` 拒绝** | 单列设 `field_weights` 报错；跨字段 `title ==> 'body:(lager)'` 报错 | **不是风险而是新 gate 的断言**：`test_stannum_usage.py:995`（`pgcode == "XX000"` 且错误含 `this ==> clause answers`）、`:1013-1017`（`pgcode="XX000"`，文本含 `multi-column`）。F4 的临时多列探针表 `v13_usage_probe` 用完即 DROP（`:1006`） |
| **绝对分值** | 0.4 若在单列上改打分常数 | **未钉死**。README 台账只保证有限数值和 `content_hash` 终裁；K/P/Q 命中集合仍可能全绿。本核查没有把「分值与 0.1.0 表一致」当使用证据 |
| **`tokenize`/`ql_parse` 改 STABLE + PARALLEL UNSAFE** | v13 零调用 | 零 |
| **O2 的 1030 词项段错误** | 0.4.0 已记录为未复现 | 那是一次实测，不是每次建库重跑的版本断言（README `:150-153`） |

**净结论**：0.4.0 的 0.4-wave 行为差异对 v13 现有 gate 的风险 ≈ 0，因为 v13 的整个调用面（单列、无 `field_weights`、4 参 `highlight`、1 参 `full_score`、text/text `==>`、无字段组 tinql）正好落在「0.4.0 未改动的交集」里。已交付的 65 断言 gate 把这一点写成了明示断言（P12/F4/F5/V6/V7）。

---

## 10. demo 面

`demo_v13/` 的检索面**很窄，没有 UI**，只有三处脚本内的 SQL 调用 + 一处授权注释：

| 位置 | 调什么 | 风险 |
|---|---|---|
| `demo_v13/mem2_observe.py:149-153` | `v13_mgraph_anchor_tinql(body)` → `v13_mgraph_candidates(sid, tinql, 5)`，读 `lexical_norm` | **中**。实证输出（`memtrial2/observe_log.json`）就是 3-gram OR 形：`"上周五" OR "周五凌" OR "五凌晨" OR "Zephyr" OR "的登录" OR …`。jieba 整包落地后这条观察脚本的 `tinql_head` / `n_terms` / 候选数会变。附带一个既有小 bug：`n_terms` 按 `'` 切分而不是 `"`，恒为 1（`:156`） |
| `demo_v13/memdrive_phase2.py:168-171` | **`v13_build_tinql(body0)`（AND 形）直接喂 `v13_mgraph_candidates`** | **高（潜在）**。`v13_mgraph_anchor_guard` 只按 `' OR '` 切（`v13_mgraph.sql:3267`）且拒内嵌引号（`:3278`），AND 形必 `V3005`。而 `one()`（`:76-85`）无 try/except。**当前是否触发取决于 node0 的 body 是否单段**：demo 语料含中文标点（`memdrive_converse.py:42`、`mem2_converse.py:43`），`v13_query_segments` 把标点当 sep → 多段 → AND 形。唯一可查的日志 `memtrial/phase2_run.log:3`（`candidates_probe_n=1`）时间戳 2026-09-24 00:48，**早于** OQ15 guard 交付，是陈旧运行，不能作为「今天不炸」的证据 |
| `demo_v13/mem2_mgraph.py:215-219` | 读策略键 `anchor_ngram_n` / `candidate_top_k` / `write_max_*` 打进日志 | **低**。只回显数值，不断言。jieba 整包若改键名（调查文档 `:138` 提过可能新增 `anchor_tokenizer`）需同步 |
| `demo_v13/setup_db.py:108-116`、`setup_db_b2.py:76-80`、`setup_db_mem.py:51-55` | 三处同位复制 stannum GRANT 块 | **中**。这三份是 `v13/*/setup_db.py` 12 份之外的手工副本，不在 R21 的扫描范围（R21 只扫 `v13/<stage>/setup_db.py`）。注释 `:109-111` 明写缺这条时 resolve 通道经 `v13_judgment_envelope → v13_recall` 调 `stannum.full_score` 会 `permission denied for schema stannum`。任何 GRANT 面改动要同步这三份 |

**没有** `v13_recall` / `v13_extract_spans` / `v13_transcript_recall` 的 demo 调用方，也没有检索 UI（`app.py` / `driver.py` / `shim.py` 全文无命中）。`demo_v13/parity/` 是控制面对照（approval/cancel/closeout/spawn/steer/triage/unknown/wake/worktree），与 stannum 正交。

---

## 我注意到但上面没问的

1. **`test_stannum_usage.py` 已经落地了，但两份背景报告都写成「第二阶段待实现」。** `e6fe89b`（2026-09-26）交付 65 断言，`v13/mgraph/README.md:14` 已接线。使用核查文档 C 节说「不改 `SQL_LOAD_ORDER`」——实际也没改。下游设计 agent 若按「C 节待实现」排期会重复劳动。

2. **`files_through` 计数是**位置敏感**的，不是内容敏感的。** R2/G1 的断言形如「第 9 个文件 `==>`=2」。任何人往 `v13/load.py` 的 `SQL_LOAD_ORDER` 插一个新文件，前 8/9 个的位置全部右移 → R2/G1/H6 全红，即使内容没动。适配方案若新增 SQL 文件（例如 M4 的词级锚若拆新文件），第一堵墙是 `load.py:17` 而不是 gate。

3. **`v13_mgraph_candidates` 的 `ORDER BY n.content_hash ASC` 与另三条不同序。** BM25 只是 `lexical_norm` 的一个分量（`v13_mgraph.sql:764-776`）。任何「统一四条检索函数」或「换打分后端」的方案如果把四条当同构处理，会在 mgraph 侧静默改变融合结果——而且 mgraph 这条**没有任何 gate 钉绝对分值**（G4/G5/G6 只钉候选池成员资格）。

4. **`v13_verify_chunks` 的 version=2 checks 形状是隐式契约。** 核查文档 C.4 说「不要把 `index_stats` 塞进 `v13_verify_chunks` 的返回 JSON，那会改变 version=2 的 checks 形状」。适配调查 `:115` 建议的「detail 里追加 index_stats 摘要列」与之**直接冲突**——两条文档给了相反建议，且都没说 manifest/envelope 面到底消费哪些键。这是未裁的缝。

5. **`decisions.question` 的 ASCII CHECK 是 v13 全树唯一一处「DDL 执法语言形态」的约束**（`v13_core.sql:398-399`）。它同时是三份文档（jieba 探针 `:19,:387`、M3-stop `:112`、结案 `:29`）共同引用的不变量。如果 v13.1 产物回流要给 chunks 加 title/summary 列（适配调查 `:167` 提过），**没有任何对应的 CHECK 会阻止非 ASCII 落进去**——新建列时要显式决定是否复制这道执法。

6. **`v13_usage_probe` 临时表是 F4/F5 的唯一 `field_weights` 落点，且依赖 `XX000`。** `test_stannum_usage.py:977-1018`。这是一个**行为断言而不是能力断言**：若 stannum 后续版本把「跨字段查询被拒」改成「返回 false」，F4 的 `foreign_ok` 分支会静默走 `returned {val!r}` 路径并 FAIL——这是好的（fail-loud），但下游若升级 stannum 要知道 F4 是版本耦合的。

7. **`stannum.index_health` 对三角色必然失败**，因为 canary 表 `v13_canary_docs` 对三角色无 SELECT（`test_characterize.py:862-872` R3 三条断言），而视图是 `security_invoker=true`（`stannum--0.4.0.sql:161-164`）。R14/R15 已实证（owner 看 5 行、recall 角色 42501）。characterize README 的示例查询没标明必须 owner——这是 runbook 缺口，不是代码缺口。

8. **`pgembed` 包版本 `0.3.0rc2` 与 stannum pin `ad4d3b7`（0.4.0）脱节**（pin 在 `pgembed/pgbuild/Makefile:278`）。V5 断言把这个事实钉住了，但它意味着「升级 stannum」的动作在 pgembed 仓库而不在 pg-agent 仓库——pg-agent 侧任何「换 stannum 版本」的方案都无法在本仓库内完成。
