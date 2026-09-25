# v13 jieba tokenizer 评估探针（2026-09-25）

**性质**:只测量、不改 v13 主链。本报告为唯一新增文件。零 SQL / 零测试 / 零 gate 改动。
**触发**:`docs/investigations/v13-stannum-0.4-pgembed-adaptation-2026-09-25.md` 里程碑 M2。产出是 M4 裁决材料，不是落地代码。
**环境**:pgembed PG 18.4 + stannum **0.4.0**（探针库 `SELECT extversion` = `0.4.0`）。连接沿 `server.get_server()` / `v13/load.py` 的本机 socket，不碰 16 个 gate 库。
**探针库**:`v13_jieba_probe`。两张表各恰一个 stannum 索引（避开 K4 同列双索引）。测量结束 `DROP DATABASE ... WITH (FORCE)`，不保留。

---

## 0. 一页摘要

- **裁决:不切生产索引。** 中文词级收益是真的（`开源`/`数据库`/`中华人民共和国` 一次成词，子串 `源`/`京`/`人民` 不再命中），但两处会直接打红现有 gate，且 highlight 绑定不对称，不能「只改 reloption」。
- **片假名行为与 0.1.0 记载相反（附 B-B4 结案）。** unicode 把片假名连跑收成一个 token（`タワー`），所以单字 `タ` 对 `東京タワーは電波塔である` miss——这就是 L3「single Katakana miss」。jieba 把片假名（含长音 `ー`）拆成单字，`タ` **命中** doc 3/4/10/11。引号包裹消不掉这个命中（`タ` 与 `"タ"` 命中集相同）。
- **字符 3-gram OR 在 jieba 上全灭（G6 会翻红）。** 查询 `为什么用户无法登录` 的 7 个 3-gram OR，unicode 命中 G6 节点正文 doc 13，jieba 7/7 miss。n-gram 锚与 jieba 是替代不是并存，调查文档 §2.3.2-3 的判断被本探针坐实。
- **四时刻:索引路径内部对称，`v13_extract_spans` 的无绑定 highlight 不对称。** 列变量 + `WHERE body ==>` 的 `stannum.highlight` 跟索引 tokenizer 走（jieba 把 `タ` 标进 `タワー`）。文本字面量调用（extract_spans 的形状）走默认 unicode，同一句里 **不标** `タ`。整段引号短语（`東京タワー`、`开源`）两边标出的字符区间相同。
- **无索引回落（附 B-B5 结案）。** 裸标量 `text ==> text` 永远是默认 unicode comparator：64B 块 miss（K3 形状不变）、`源` hit、`タ` miss。表上已有 jieba 索引时，强制 Seq Scan 的 recheck 绑到该索引 oid，命中集与 Index Scan 逐查询相同——回落 comparator **跟随索引 tokenizer**，不是裸标量那条。
- **治理面可见，但只在 Custom Scan 执行路径上执法。** jieba 索引 `index_stats.analysis_matches=true`、`analysis_detail='jieba 0.7.4 / dict 6855a0736155f3dd / matches'`；unicode 两列 NULL。`\d` 只显示 reloption `tokenizer=jieba`，版本戳不在 `\d` 里，在 `index_analysis` / EXPLAIN `Analysis:`。`jieba_add_word` 后 `matches=false`。Custom Scan 执行发出 `WARNING: stannum index ix_docs_jieba: dictionary drift; REINDEX required`；`stannum.strict_analysis=on` 把同一路径升级为 ERROR。强制 Seq Scan 的 recheck **既不 WARNING 也不 ERROR**。
- **性能（粗）。** 新 backend 首次 jieba 查询 178–224 ms（中位 196 ms），第二次 0.4–0.7 ms；RSS 约 +95 MB（`ps rss` 9 MB → 104 MB）。4000 行建索引：词典冷 220–333 ms，预热后 27 ms，对照 unicode 22 ms。15 行上 EXPLAIN ANALYZE 两边都是 0.01 ms 量级，查询 CPU 无可见回归。
- **`decisions.question` 不切。** DDL 钉 `^[\x20-\x7E]+$`（`v13/schema/v13_core.sql:399`）。英文语料两边 token 逐字相同，切了只有词典税、没有召回差。沿调查文档 M4 既有结论，本探针不改这个判断。

---

## 1. 探针 DDL（可复现）

同语料、两表、各一索引。除 `tokenizer` 外 reloption 一致，并显式钉上 canary 的 `long_tokens` / `max_token_bytes`（`v13/characterize/v13_characterize.sql:17-25` 的三行语料原样在内）。

```sql
CREATE EXTENSION IF NOT EXISTS stannum;

CREATE TABLE docs_jieba (
  doc_no int PRIMARY KEY,
  body   text NOT NULL,
  note   text NOT NULL
);
INSERT INTO docs_jieba (doc_no, body, note) VALUES
  (1, repeat('z', 200), 'canary doc1: 200 z'),
  (2, 'plain english document about quasars and redshift surveys', 'canary doc2 english'),
  (3, '東京タワーは電波塔である', 'canary doc3 katakana+han'),
  (4, '東京タワーは電波塔である kohaku', 'characterize L3 ingest mix'),
  (5, '开源数据库支持全文检索', 'zh short sentence'),
  (6, 'スマートフォンで検索する', 'katakana loan + hiragana'),
  (7, 'BM25 检索与 jieba tokenizer 混用 PostgreSQL', 'mixed zh/en'),
  (8, '中华人民共和国全国人民代表大会常务委员会', 'zh long compound'),
  (9, '錕斤拷甲乙丙丁未登录串测试', 'oov-ish han run'),
  (10, 'タワー', 'katakana run alone'),
  (11, 'タ', 'single katakana'),
  (12, 'カフェラテ', 'katakana loanword'),
  (13, '用户无法登录系统因为密码过期', 'G6 node body'),
  (14, '电磁波塔', 'han near 电波塔'),
  (15, '数据库', 'single dict word');
CREATE TABLE docs_unicode (LIKE docs_jieba INCLUDING ALL);
INSERT INTO docs_unicode SELECT * FROM docs_jieba;
CREATE INDEX ix_docs_unicode ON docs_unicode USING stannum (body)
  WITH (tokenizer='unicode', long_tokens='split', max_token_bytes=64);
CREATE INDEX ix_docs_jieba ON docs_jieba USING stannum (body)
  WITH (tokenizer='jieba', long_tokens='split', max_token_bytes=64);
```

`tokenize` / `ql_parse` 用同一组非默认选项，避免函数默认 `max_token_bytes=256` 和索引的 64 错位：

```sql
SELECT stannum.tokenize($1, $2, 'fold', 'fold', 'split', 64);
SELECT stannum.ql_parse($1, true, $2, 'fold', 'fold', 'split', 64);
```

索引路径命中一律 `SET enable_seqscan=off; SET enable_bitmapscan=off`，EXPLAIN 确认是 `Custom Scan (Stannum Text Search Scan)`。Seq Scan 对照是 `enable_indexscan=off` + `enable_bitmapscan=off`。

G6 3-gram 由查询串按字符滑窗生成（n=3，与 `v13_mgraph_anchor_terms` 的 CJK 分支同形，`v13/mgraph/v13_mgraph.sql:3230-3237`）：

```text
为什么 什么用 么用户 用户无 户无法 无法登 法登录
"为什么" OR "什么用" OR "么用户" OR "用户无" OR "户无法" OR "无法登" OR "法登录"
```

---

## 2. 分词（index / query 共用的分析器）

`string_agg(token, ' | ' ORDER BY ord)`。两边对英文 doc 2 逐 token 相同。差异全在 Han / Katakana。

| doc | jieba | unicode |
|---|---|---|
| 1 `z`×200 | 四个 64B 块（末块 8 个 z） | 同左 |
| 2 english | `plain \| english \| document \| about \| quasars \| and \| redshift \| surveys` | 同左 |
| 3 `東京タワーは電波塔である` | `東京 \| タ \| ワ \| ー \| は \| 電波塔 \| て \| あ \| る` | `東 \| 京 \| タワー \| は \| 電 \| 波 \| 塔 \| て \| あ \| る` |
| 5 `开源数据库支持全文检索` | `开源 \| 数据库 \| 支持 \| 全文检索` | `开 \| 源 \| 数 \| 据 \| 库 \| 支 \| 持 \| 全 \| 文 \| 检 \| 索` |
| 6 `スマートフォンで検索する` | `ス \| マ \| ー \| ト \| フ \| ォ \| ン \| て \| 検 \| 索 \| す \| る` | `スマートフォン \| て \| 検 \| 索 \| す \| る` |
| 7 mixed | `bm25 \| 检索 \| 与 \| jieba \| tokenizer \| 混用 \| postgresql` | `bm25 \| 检 \| 索 \| 与 \| jieba \| tokenizer \| 混 \| 用 \| postgresql` |
| 8 长复合 | `中华人民共和国 \| 全国人民代表大会常务委员会` | 20 个单字 |
| 9 OOV 串 | `錕 \| 斤 \| 拷 \| 甲乙丙丁 \| 未 \| 登录 \| 串 \| 测试` | 12 个单字 |
| 10 `タワー` | `タ \| ワ \| ー` | `タワー` |
| 13 G6 正文 | `用户 \| 无法 \| 登录 \| 系统 \| 因为 \| 密码 \| 过期` | 14 个单字 |
| 14 `电磁波塔` | `电磁波 \| 塔` | `电 \| 磁 \| 波 \| 塔` |

平假名两边都是单字（`は/て/あ/る`）。日文汉字 `検索` jieba 没并成词（`検 \| 索`），简体 `检索` 并成一词——词典覆盖的是简体词，不是「Han 一律成词」。

查询侧 `ql_parse`（短语重写，与 tokenize 一致）：

```text
ql_parse('"東京タワー"', jieba)   = "東京 タ ワ ー"
ql_parse('"東京タワー"', unicode) = "東 京 タワー"
ql_parse('"开源"', jieba)         = 开源
ql_parse('"开源"', unicode)       = "开 源"
ql_parse(G6 OR, jieba)            = "为什么" OR "什么 用" OR "么 用户" OR "用户 无" OR "户 无法" OR "无法 登" OR "法 登录"
ql_parse(G6 OR, unicode)          = "为 什 么" OR "什 么 用" OR "么 用 户" OR "用 户 无" OR "户 无 法" OR "无 法 登" OR "法 登 录"
ql_parse('"检索" AND "PostgreSQL"', jieba)   = "检索" AND "postgresql"
ql_parse('"检索" AND "PostgreSQL"', unicode) = "检 索" AND "postgresql"
```

裸词 `quasar` 两边都是空命中：语料是 `quasars`，不是 tokenizer 分歧。对照 `"redshift"` 两边都命中 doc 2。

---

## 3. 行为对照（索引路径命中集）

SQL 模板（两边各跑一遍）：

```sql
SET enable_seqscan = off;
SET enable_bitmapscan = off;
SELECT doc_no FROM docs_jieba   WHERE body ==> :q ORDER BY 1;
SELECT doc_no FROM docs_unicode WHERE body ==> :q ORDER BY 1;
```

EXPLAIN 样例（jieba，`开源`）：

```text
Custom Scan (Stannum Text Search Scan) on docs_jieba
  Index: ix_docs_jieba
  Query: 开源
  Segments: 1
  Analysis: jieba 0.7.4 / dict 6855a0736155f3dd / matches
```

| 查询 | jieba 命中 | unicode 命中 | 分歧 |
|---|---|---|---|
| `"redshift"` | 2 | 2 | |
| `東京タワー` / `"東京タワー"` | 3, 4 | 3, 4 | 引号不改变命中集 |
| `タ` / `"タ"` | **3, 4, 10, 11** | **11** | L3 单字 miss 在 jieba 下消失 |
| `タワー` / `"タワー"` | 3, 4, 10 | 3, 4, 10 | 整段仍命中 |
| `京` / `"京"` | **∅** | **3, 4** | 子串：unicode 中、jieba 不中 |
| `开源` / `"开源"` | 5 | 5 | 词本身两边都中 |
| `源` | **∅** | **5** | 词内单字 |
| `"源数"` | **∅** | **5** | 跨 jieba 词界 |
| `开源数据库` | 5 | 5 | |
| `スマートフォン` | 6 | 6 | |
| `スマ` | **6** | **∅** | 片假名前缀，方向与 `タ` 相同 |
| `カフェ` | **12** | **∅** | 同上 |
| `カフェラテ` | 12 | 12 | |
| `"检索" AND "PostgreSQL"` | 7 | 7 | v13_build_tinql 混语形 |
| `检索 AND PostgreSQL` | 7 | 7 | |
| `"東京タワー" AND "kohaku"` | 4 | 4 | |
| `中华人民共和国` | 8 | 8 | |
| `人民` | **∅** | **8** | 长词内子串 |
| `錕` | 9 | 9 | 单字 OOV 两边都是独立 token |
| `"z"×64` | 1 | 1 | 64B split 两边都命中 |
| G6 3-gram OR | **∅** | **13** | 见下 |
| `"用户无"` | **∅** | **13** | 单个 3-gram 已分歧 |
| `"为什么"` | ∅ | ∅ | 正文里没有这个窗口，两边都 miss |

逐 gram（`"gram"`，索引路径）：

| gram | jieba | unicode |
|---|---|---|
| 为什么 / 什么用 / 么用户 | ∅ | ∅ |
| 用户无 / 户无法 / 无法登 / 法登录 | ∅ | 13 |

OR 只要一中即中，所以 unicode 命中 doc 13、jieba 全灭。G6 断言 `count(*)=1`（`v13/mgraph/test_mgraph.py:2753-2756`）在 jieba 索引上不成立。

本探针测过的每一对「裸词 vs 引号」，命中集都相同。`v13_build_tinql` 的引号（`v13/recall/v13_recall.sql:79-82`）稳定的是文法（`v13_tinql_terms` 要求引号段），不是片假名 miss。miss 来自 unicode 把片假名连跑收成一个 token；jieba 拆字之后，`"タ"` 照样命中。

---

## 4. 四时刻对称

时刻定义：index = 建索引时的 tokenizer；query = `tokenize`/`ql_parse` 与 `==>`；score = `stannum.full_score(ctid)` 在同一 `WHERE body ==>` 下；highlight 分两条。

### 4.1 索引绑定 highlight（列变量）

```sql
SELECT doc_no, stannum.highlight(body, '<m>', '</m>', :q)
FROM docs_<tok> WHERE body ==> :q ORDER BY 1;
```

与第 3 节命中集一致，标出的区间就是命中 token 的字符覆盖：

```text
jieba  开源     doc 5  <m>开源</m>数据库支持全文检索
unicode 开源     doc 5  <m>开源</m>数据库支持全文检索
jieba  タ       doc 3  東京<m>タ</m>ワーは電波塔である
unicode タ       （tower 文档不在命中集；仅 doc 11 `<m>タ</m>`）
jieba  京       （无行）
unicode 京       doc 3  東<m>京</m>タワーは電波塔である
jieba  "東京タワー"  doc 3  <m>東京タワー</m>は電波塔である
unicode "東京タワー" doc 3  <m>東京タワー</m>は電波塔である
jieba  "检索" AND "PostgreSQL"
       doc 7  BM25 <m>检索</m>与 jieba tokenizer 混用 <m>PostgreSQL</m>
unicode 同上，字符区间相同
```

同一 tokenizer 内：tokenize 出的 query token、命中 doc、highlight 内文、`full_score` 有限值，四者对齐。例如 jieba `タ` 的 score 为 doc 11=1.9079916、doc 10=1.5608503、doc 3=1.0097218、doc 4=0.953603，全是含单字 `タ` 的行。`東京タワー` 两边都是 doc 3 分高于 doc 4（jieba 4.706803 / 4.445206，unicode 4.6721973 / 4.4614563）——排序方向同，分值不同。词级 `开源` 分值差更大（jieba 2.6697762 vs unicode 4.036685），因为 df / 文档长度口径变了。本探针没有构造 score 并列，不回答 tie-break。

### 4.2 无绑定 highlight（extract_spans 的形状）

`v13_extract_spans` 把 body 文本和 tinql 文本传进 `stannum.highlight(p_body, open, close, tinql)`（`v13/characterize/v13_characterize.sql:59`），不是索引列变量。探针用字面量复刻：

```sql
SELECT stannum.highlight(:body, '<m>', '</m>', :q);
```

| 查询 | 无绑定结果 | 与 jieba 绑定 highlight |
|---|---|---|
| `开源` on doc 5 | `<m>开源</m>数据库支持全文检索` | 字符区间相同 |
| `源` on doc 5 | `开<m>源</m>数据库支持全文检索` | jieba 索引不命中，无绑定却标了 |
| `"東京タワー"` on doc 3 | `<m>東京タワー</m>は電波塔である` | 字符区间相同 |
| `タ` on doc 3 | `東京タワーは電波塔である`（无标签） | jieba 绑定标了 `<m>タ</m>`，无绑定不标 |
| `京` on doc 3 | `東<m>京</m>タワーは電波塔である` | jieba 索引不命中 |
| `"源数"` | `开<m>源数</m>据库支持全文检索` | jieba 不命中 |
| 子查询列 `highlight(b, ..., '开源')` from doc 5 | 与字面量相同，标 `开源` | 这条也没绑到 jieba |

整段引号短语的字符区间碰巧一致（两边都把整段标出来）。单字片假名不一致：jieba 召回命中、extract_spans 拿不到 span。M4 若只切索引、不改 highlight 绑定，`タ` 这类命中会变成「召回有、spans 空」。

---

## 5. 无索引回落（附 B-B5）

### 5.1 强制 Seq Scan（表上仍有 jieba 索引）

```text
Seq Scan on docs_jieba
  Filter: (body ==> '{"index":2139236,"query":"源"}'::stannum.indexed_query)
```

Filter 已经绑到索引 oid。全部 28 条查询的 Seq Scan 命中集与第 3 节 Index Scan **逐条相同**（jieba 与 unicode 各自内部无 path diff）。recheck 跟随索引 tokenizer，不退回默认 unicode。

### 5.2 裸标量（没有任何索引）

```sql
SELECT repeat('z', 200) ==> '"<z×64>"';          -- False
SELECT '开源数据库支持全文检索' ==> '源';          -- True
SELECT '开源数据库支持全文检索' ==> '开源';        -- True
SELECT '東京タワーは電波塔である' ==> 'タ';         -- False
SELECT '東京タワーは電波塔である' ==> '"タ"';       -- False
SELECT '東京タワーは電波塔である' ==> '"東京タワー"'; -- True
SELECT '東京タワーは電波塔である' ==> '京';         -- True
SELECT '用户无法登录系统因为密码过期' ==> :g6_or;   -- True
```

裸标量 = 默认 unicode、默认 `max_token_bytes`（不是 64）。所以：

- K3 的「bound 64B hit / 默认 comparator 64B miss」在 jieba 索引上形状不变：索引（`max_token_bytes=64`）命中 doc 1，标量 miss。
- 裸标量 **不** 跟随 jieba。`源`/`京`/`タ` 的标量结果等于 unicode 列，不等于 jieba 列。
- 「无索引回落」要拆开说：表还在、只是没走 Index Scan → 跟随索引；表达式根本没有索引 → 默认 unicode。K3 测的是第二条。

---

## 6. 性能（粗粒度）

计时 = 客户端 `perf_counter` 包住 `execute+fetch`（含往返）。查询 CPU 另用 EXPLAIN ANALYZE 的 `Execution Time`（不含往返）。新 backend = 新连接。

### 6.1 首次 jieba 使用

查询 `SELECT doc_no FROM docs_jieba WHERE body ==> '开源'`，`enable_seqscan=off`。5 个新 backend：

| rep | jieba 首查 ms | 第二次 ms | rss KB 前→后 | unicode 首查 ms | unicode rss 前→后 |
|---|---|---|---|---|---|
| 0 | 177.815 | 0.394 | 9136→106976 | 2.506 | 9136→14832 |
| 1 | 180.017 | 0.617 | 9136→106960 | 2.171 | 9136→14848 |
| 2 | 196.222 | 0.706 | 9200→107040 | 1.712 | 9152→14864 |
| 3 | 201.666 | 0.641 | 9200→107040 | 2.034 | 9136→14848 |
| 4 | 223.780 | 0.391 | 9168→107168 | 1.863 | 9152→14848 |

首查中位 196 ms，第二次中位 0.62 ms。RSS 增量约 **+95 MB**（`ps -o rss=`，粗）。对照 unicode 首查约 2 ms、RSS 约 +5.5 MB。只 `tokenize(..., 'jieba')` 的 5 次首用是 176–199 ms、RSS 9168→103904 KB 左右，和查询首用同一量级——暂停在词典解析，不在扫描。

调查文档转述的「约 100 ms、数 MB RSS」偏小。本机实测约 200 ms、约 95 MB RSS。runbook 若写预热，按这个量级写，不要按底稿的「数 MB」。

### 6.2 索引构建

4000 行（6 句语料轮转加 ` #N` 后缀），每次新 backend，`DROP INDEX` 后重建。3 次：

| 路径 | ms |
|---|---|
| jieba 冷（含词典解析） | 333.417 / 230.878 / 220.372 |
| jieba 热（先 tokenize 再 CREATE INDEX） | 26.891 / 26.820 / 28.735 |
| unicode | 24.231 / 21.117 / 22.494 |

热 jieba 比 unicode 大约 5 ms。构建成本的可见部分是首次词典解析，不是 4000 行切分本身。15 行 canary 索引的构建被词典税淹没，不单列。

### 6.3 查询 CPU

同一连接、预热 3 次后 8 次 `EXPLAIN (ANALYZE, TIMING)`，`Execution Time` 中位：

| 查询 | jieba ms | unicode ms |
|---|---|---|
| `开源` | 0.010 | 0.013 |
| `"東京タワー"` | 0.018 | 0.014 |
| `quasar` | 0.010 | 0.008 |
| `タ` | 0.009 | 0.009 |
| G6 OR | 0.035 | 0.043 |

15 行上没有 jieba 查询 CPU 回归。这不是 characterize M1 fold 的 p99 带，不能拿来宣称 fold 守门不用重测。

---

## 7. 治理面

漂移测试之前：

```text
pg_get_indexdef(ix_docs_jieba) =
  CREATE INDEX ix_docs_jieba ON public.docs_jieba USING stannum (body)
  WITH (tokenizer=jieba, long_tokens=split, max_token_bytes='64')
reloptions = {tokenizer=jieba,long_tokens=split,max_token_bytes=64}

\d+ ix_docs_jieba
  Options: tokenizer=jieba, long_tokens=split, max_token_bytes=64
```

`\d` / reloptions **没有** jieba 版本戳。戳在分析元数据里：

```text
index_analysis(ix_docs_jieba):
  recorded_jieba_version=1796
  recorded_dict_fingerprint=7518091570379617245
  runtime 同值
  matches=true
  status=matches
index_analysis(ix_docs_unicode): 身份列全 NULL，matches NULL，status=not applicable

index_stats(ix_docs_jieba):
  documents=15 dead=0 segments=1 total_length=83 average_length=0
  analysis_matches=true
  analysis_detail=jieba 0.7.4 / dict 6855a0736155f3dd / matches
index_stats(ix_docs_unicode):
  documents=15 total_length=116 average_length=0
  analysis_matches=NULL
  analysis_detail=NULL
```

`1796 = 0x0704`，按 `version>>16, (version>>8)&0xff, version&0xff` 印出来就是 EXPLAIN / `analysis_detail` 里的 `0.7.4`。空自定义词典指纹 `6855a0736155f3dd` 与 stannum compatibility 文档冻结的空表指纹一致。`average_length` 仍恒 0.0，与 M1 runbook 注记相同。`SHOW stannum.strict_analysis` 默认 `off`。

漂移（探针库内，不影响其他库）：

```sql
SELECT stannum.jieba_add_word('探针专词', 10, 'n');
-- dict fingerprint 6855a0736155f3dd -> 10b1e8358e032a00
SELECT * FROM stannum.index_analysis('ix_docs_jieba');
-- matches=false, status=dictionary drift; REINDEX required
```

执法只在 **执行了 Custom Scan** 的语句上，一次 backend 一次：

```text
EXPLAIN (ANALYZE) SELECT doc_no FROM docs_jieba WHERE body ==> '开源';
-- Custom Scan ... Analysis: jieba 0.7.4 / dict 6855a0736155f3dd / drift
-- WARNING:  stannum index ix_docs_jieba: dictionary drift; REINDEX required

SET stannum.strict_analysis = on;
EXPLAIN (ANALYZE) SELECT ... ==> '开源';
-- ERROR:  stannum index ix_docs_jieba: dictionary drift; REINDEX required
```

同一漂移索引、强制 Seq Scan、`strict_analysis=on`：

```text
Seq Scan on docs_jieba
  Filter: (body ==> '{"index":2139236,"query":"开源"}'::stannum.indexed_query)
-- 返回 doc 5，无 WARNING，无 ERROR
```

所以：诊断面（`index_analysis` / `index_stats` / EXPLAIN `Analysis:`）漂移可见；WARNING 与 `strict_analysis` 硬错误只挂在 Custom Scan 执行路径。小表被规划成 Seq Scan 时，漂移索引仍可出结果。M4 runbook 不能写成「strict_analysis=on 则任何语句都 fail-closed」。

---

## 8. 与 v13 主链对照（M4 时谁会被打动）

| gate | 现断言 | 本探针里对应的差异 | 会被打动吗 |
|---|---|---|---|
| **L3** `test_characterize.py:499-504` | `"東京タワー"` 命中生产 + canary doc 3；`タ` 的 recall 为空 | 整段两边都命中 doc 3/4。`タ`/`"タ"` unicode 只命中纯单字 doc 11，jieba 命中含 `タワー` 的 doc 3/4/10 | **会。** 生产索引改 jieba 后 L3「single Katakana miss」翻红。短语命中那两条可保持 |
| **B3** `test_recall.py:603-615` | `v13_recall('"京"')` 空；整段命中数 = english `phraseto_tsquery` 计数 | recall 阶段的 `v13_recall` 仍是 tsvector（`v13/recall/v13_recall.sql:121-148`），不读 stannum tokenizer。探针里 **stannum unicode** 对 `京` 是命中（doc 3/4），jieba 是 miss——这和 B3 的 tsvector 空命中不是同一条路径 | **不会**被 reloption 打动。不要把 B3 改成 jieba 期望。characterize 换体后的 stannum recall 若另写子串断言，unicode 与 jieba 方向相反，须单独重校 |
| **G6** `test_mgraph.py:2749-2756` | 3-gram OR tinql 驱动 stannum，CJK 节点 `count=1` | 同形 OR：unicode 命中 doc 13，jieba 0 行。4/7 个 gram 在 unicode 命中、jieba 全灭 | **会翻红**，除非同一次改写 `v13_mgraph_anchor_terms` 的 CJK 分支（词级，不再滑窗 3-gram） |
| **E2** `test_mgraph.py:1601-1626` | CJK 码点短路进 superset | `v13_mgraph_route` 只扫码点，不调用 tokenizer | **不会** |
| **A2** `test_mgraph.py:364-396` | mgraph v2 策略行 / 种子 JSON | 不读索引。SQL 注释里的「A2 全段 OR」是 n=0 字符串退化（G1 测），也是纯字符串函数 | **不会** |
| **K3** `test_characterize.py:409-420` | canary 索引（split/64）命中 64B 块；标量 `repeat('z',200) ==>` 为 False | jieba 与 unicode 索引都命中 doc 1；标量仍 False。ASCII `z` 的切分两边相同 | **不会**，只要 canary 的 `long_tokens`/`max_token_bytes` 不动。tokenizer 名字本身不改变这条 |
| **M1** `test_memory.py:640-641` | `ix_decisions_question_stannum` 恰一行 | 英文 token 两边相同；该列 DDL 禁止非 ASCII | **不会**，前提是这张索引保持 unicode、保持一张。characterize 的 fold 数值带本探针没重跑；15 行查询 CPU 无回归，但冷 backend 200 ms 词典税不能混进 fold 计时窗。M4 若切 chunks 索引，fold 带要重测，不能用本节代替 |

`decisions.question` 不切，复述调查文档 M4 既有结论：列被 `CHECK (question ~ '^[\x20-\x7E]+$')` 钉成 ASCII 英文判断题（`v13/schema/v13_core.sql:398-399`）。本探针英文 doc 2 两边 token 相同，没有 CJK 收益可换。切它只增加首次词典解析税。

---

## 9. 对 M4 的裁决

**不切。** 条件不满足之前，chunks / transcript_chunks / memory_nodes / decisions 的生产索引保持默认 unicode。

若将来要切，只接受 **整包**，不允许「先改 reloption、gate 以后再说」：

1. **anchor 同切。** `v13_mgraph_anchor_terms` 的 CJK 3-gram 在 jieba 索引上整段 OR 为零命中（第 3 节）。不改锚函数，G6 必红，mgraph 锚池空转。
2. **L3 重写，不放宽。** 单字片假名 miss 是 unicode 连跑 token 的物理事实，不是可保留的不变量。切 jieba 后断言应改成「单字片假名命中含该字的文档」，并写明这是过召回（`タ` 命中 `タワー`），不是质量提升。禁止用 OR 把新旧行为都判绿。
3. **highlight 绑定先验证再切。** 整段引号短语的字符区间两边一致，`v13_build_tinql` 的常见查询也许 spans 仍对。单字片假名已经实测不一致。M4 必须有一条「jieba 索引命中行的 `v13_extract_spans` 字节区间 = 绑定 highlight 区间」的新断言；做不到就改 extract_spans 的调用形状，而不是关掉 spans 检查。
4. **引号 workaround 留着。** 它守的是 tinql 文法，不守片假名 miss。摘掉它不能恢复 unicode 的单字 miss，也不能阻止 jieba 的单字命中。
5. **`decisions.question` 不在包内。**
6. **排期仍串在 OQ13/OQ14 之后**（调查文档 §2.3.3）。本探针不改变这个次序：jieba 改的是召回 token，不改 route() 的码点短路。
7. **治理写进 runbook，不写进 SQL。** 版本戳看 `index_stats.analysis_detail` / `index_analysis`，不要看 `\d`。`strict_analysis` 只在 Custom Scan 执行路径 fail-closed；小表 Seq Scan 不会。预热按约 200 ms、约 95 MB RSS 写，不按底稿的「数 MB」。

部分切（只切 memory_nodes、不切 chunks）在第 1–3 条没完成前同样不成立：G6 就在 memory_nodes 上。

---

## 10. 待实证清单推进

| # | 内容 | 本探针之后 |
|---|---|---|
| 附 B-B4 | jieba 对片假名连跑的切分；引号 workaround 能否摘 | **结案。** jieba 拆成单字（含 `ー`），unicode 收成一个 token。单字 miss 在 jieba 下消失且引号摘不回来。workaround 因文法保留，不因片假名保留 |
| 附 B-B5 | 无索引回落 comparator 与 tokenizer 的关系；K3 64B miss 在 jieba 下的形态 | **结案。** 裸标量 = 默认 unicode，64B miss 形状不变。Seq Scan recheck = 绑定索引 tokenizer，命中集与 Index Scan 相同 |
| 附 B-B2 | `search()` snippet 是否窗口截断 | **未测。** 与 jieba 正交，仍待实证 |
| 附 B-B3 | `search()` score tie-break | **未测。** 本探针 `full_score` 无并列，不回答 |
| R3 | 词典漂移 WARNING + `strict_analysis` | **部分推进。** 诊断列与 Custom Scan 路径按文档工作；Seq Scan recheck 不执法。见 §7 |

---

## 11. 测量边界

- 行为语料 15 行，构建计时 4000 行。查询 CPU 是粗数字，不是 fold p99。
- 没执行 `v13_recall` / `v13_mgraph_anchor_tinql` / `v13_extract_spans` 函数体（那些在 gate 库里）。对照用的是同形 SQL：引号段、3-gram OR、highlight 字面量。
- 没碰 `agent_v13_*`。没改 stannum / pgembed 源码。
- 漂移用 `jieba_add_word('探针专词')` 制造，词不在语料里，只改指纹、不改既有切分。该写入随 `DROP DATABASE` 消失。
