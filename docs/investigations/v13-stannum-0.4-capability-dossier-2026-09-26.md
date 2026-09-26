# stannum 0.4.0 能力面档案（供 v13 利用方案设计引用）

> 探针产出，2026-09-26。证据基线：`/Users/wxl/Projects/stannum` 工作树（0.4.0 实现 2026-09-24/25 落地并推送 `067a557..18bdd8c`）。每条附 `文件:行`。

---

## 1. 多列索引 + field_weights + BM25F

**做什么**：一个 stannum 索引可含 2–16 个 key 列，每列 = 一个 field；`field_weights` 给每列一个正权重，打分走 **BM25F**（`tf* = Σ_f w_f·tf_f`，`len* = Σ_f w_f·len_f`，idf 仍是全语料聚合 df，不做 per-field df）。

**语法**（`docs/designs/lsg4-rfc.md:54-75`、`docs/query-language/fields.md:18-21`）：
```sql
CREATE INDEX docs_search ON docs USING stannum (title, body)
    WITH (field_weights = 'title:3.0,body:1.0');
```

**约束限制**
- reloption 是**字符串**（`postgres/src/options.rs:306-313` 注册，无默认值）。语法层只查 `name:float`、名字唯一、权重有限且 `> 0`；**关系层规则在 `postgres/src/storage/mod.rs:1872-1930`**：
  - 单列索引设 `field_weights` → `ERROR: field_weights applies to multi-column stannum indexes`（:1883）
  - `indnkeyatts > 16` → `ERROR: ... at most 16 key columns`（:1888）
  - key 为表达式（`attnum <= 0`）→ `ERROR: ... reject expression keys`（:1895）
  - 名字必须是索引列的**排列**，缺一不可（:1918-1923 `field_weights names must be a permutation of index columns`）
  - 省略的列默认权重 `1.0`；权重**按索引属性序**存进 `FieldMeta { names, weights }`
- **`ALTER INDEX … SET/RESET (field_weights=…)` 被 ProcessUtility hook 一律拒绝**，报 `REINDEX to change field_weights`（`postgres/src/options.rs:100-150`）——权重同时活在 reloption 和 meta trailer 两处，只改一处会分叉。
- **列改名即失效**：`check_fields` 在每次读 meta 时比对记录的列名，不一致 → `ERROR: the indexed columns changed since the index was built; REINDEX required`（`postgres/src/storage/mod.rs:2273-2310`）。
- 拒绝 INCLUDE 列（初始发布）。
- `amcanmulticol = true`（`postgres/src/am.rs:34`），但注释明确：**只有第一个 key 列进 core 索引路径**，其余列靠 `==>` 子句匹配器和 scan key 自己的属性号回答。

**成本代价**
- 多列索引写 **LSG4** 段（见 §8）；单列索引永远写 LSG3，两者**绝不互相 merge**。
- 字段限定的非位置项需要 **payload-filter cursor**：`df` 是全字段聚合的，所以 postings 本身无法限字段，必须逐个候选解 payload entry 检查 field mask（`docs/designs/lsg4-rfc.md:1019-1026`、`tinql/src/runtime/plan.rs:248-290`）。选择性估计只能用聚合 df 作保守上界。
- 每文档长度表变成 doc-major field 行，payload entry 按字段分组 → 存储与解码开销高于 LSG3（格式差异见 `docs/designs/lsg4-rfc.md:137-230`）。

**benchmark 证据**
- 唯一与本特性直接相关的实测是 **WAND 剪枝率**：`LIMIT 10 / 1200 文档`下，**LSG3 = 112 scored / 1088 pruned，LSG4 = 362 scored / 838 pruned**（`docs/plans/stannum-p0-agent-features-2026-09-22.md:1352`，WI-12 记录）。即 LSG4 的 per-field bounds 让剪枝数下降约 23%——注意这是**多列场景的额外成本**，不是单列收益。
- 正确性 gate（同文件 :1351-1353）：WI-11 workspace 579 green / pg18 46/46 / pg_test 169；WI-12 workspace 582 / pg18 49/49 / pg_test 178；WI-13 pg18 49/49 / pg_test 183/183、`ranked_fuzz --fields` seeds 105/206、`oracle --fields` 16/16。`ranked_fuzz` 的 fields 场景索引就是 `(title, body) WITH (field_weights='title:2.0,body:1.0')`（`postgres/tests/ranked_fuzz.py:606-607`）。
- **没有**多列 vs 单列的吞吐/延迟对比 benchmark。`docs/benchmarks/` 全目录 grep `field_weights|BM25F|LSG4` **零命中**。

**版本/兼容**：0.4.0 新增（`docs/compatibility.md:200-235`）。升级 `ALTER EXTENSION stannum UPDATE TO '0.4.0'` 只加两个 highlight 重载，不碰已有索引。

---

## 2. 字段组 + same-field 短语

**做什么**：TINQL 的 field 维度，把任意子查询（项、布尔、短语、邻近、span 关系、位置过滤器）限制到一个命名字段。

**语法**（唯一形式，`docs/query-language/fields.md:23-48`；grammar `tinql/src/parser/pest_parser/grammar.pest:94-99`；AST `tinql/src/ast.rs:53-61`）
```
title:(beer OR ale)
body:("craft beer")
"My Field":(beer)          -- 非裸名用引号标识符 + 短语转义规则
```
- **`field_head` 是 compound-atomic（`$`）**：`name`、`:`、`(` 必须相邻。`title: (foo)`（带空格）**不是** field 语法，解析成词 `title:` 加一个分组。
- 裸名 = ASCII 字母开头 + 字母/数字/下划线，按 PostgreSQL 非引号标识符规则 ASCII 小写折叠（`TITLE:(beer)` → `title`）；其他拼写必须引号，**逐字节**匹配记录的列名（`build_field_name`，`tinql/src/parser/pest_parser/mod.rs:559-573`）。
- `title:beer` 不带括号仍是**单个词查找**（`:` 是词字符），语义与旧版一致。

**约束限制**
- 未知字段 → `stannum: unknown field 'nope'`（`tinql/src/runtime/plan.rs:55`、`postgres/src/score.rs:2475`、`postgres/src/operator.rs:753`）。
- 单列索引用 field 语法 → `stannum: field syntax requires a multi-column index`（`postgres/src/score.rs:2509`、`postgres/src/operator.rs:749`）。
- 内层组覆盖外层组；`title:(beer) AND body:(ale)` 是两个字段；`title:(beer OR ale)^2` 可 boost。

**same-field 短语规则**（`docs/query-language/fields.md:66-85`、RFC `docs/designs/lsg4-rfc.md:558-566`、实现 `tinql/src/runtime/plan.rs:568-580`）
- **每个 field 的位置独立，从 0 开始**。短语/邻近/span 只在**同一个 field 内**成立：`"甲 乙"` 匹配「任一单字段内相邻」，**title 里的甲 + body 里的乙 永不匹配**（Lucene 规则）。
- 布尔运算符在**文档层**组合，所以 `title:(甲) AND body:(乙)` 完全合法——受限制的是*位置类*查询，不是项。
- 实现：位置按字段分区，boldi-vigna solver **每字段跑一次再取并集**；interval 不加字段轴。

**`==>` 按左列收窄**（`postgres/src/score.rs:2560-2625`、`postgres/src/operator.rs:729-780`）
- `title ==> 'beer'` 的 scan key 属性号 = 隐式外层 field scope，子句只匹配/打分 title。
- 收窄靠**文本重包裹**实现：`scoped_query_text` 把子句查询包成 `"Title":(beer)`（字段名**总是引号**，因为裸名会被 case-fold 而匹配不上混合大小写列名）。`score_bound_indexed` 的冻结签名不带 field 参数，这条文本是唯一通道，scan scorer 与 planner 投影函数必须推出同一个 key。
- operator 子句里写**别的**字段组 → `ERROR: stannum: this ==> clause answers 'title'; use stannum.search() for 'body'`（`postgres/src/score.rs:2621`、`postgres/src/operator.rs:775`）。
- heap fallback / recheck 只评估左操作数的字段（`customscan.rs:1416` 的 `passes_clause`；`search_recheck` :1618 保持 `true` stub）。

**成本代价**：字段限定项走 payload-filter cursor（见 §1）；短语按字段重复求解。

**benchmark 证据**：`ranked_fuzz --fields`（`postgres/tests/ranked_fuzz.py:203-233, 442-460`）用**每列 regex oracle** 校验字段限定子句——即 `title ==> 'title:(x)'` 的正确性靠 `title ~ regex` 独立证明。该 fuzz 在 0.4.0 phase 3 **发现并修了两个 phase-1 的字段相关缺口**（write-buffer / bitmap 路径）（`docs/plans/...:1353`）。

---

## 3. 五参 field highlight 与 indexed_query 绑定高亮

**做什么**：`stannum.highlight` 增加第 5 参 `field text`，标记只保留在「该文本所属字段」被查询部分覆盖的范围内。

**签名**（`postgres/sql/stannum--0.4.0.sql:83-93, 216-226`；upgrade 脚本 `postgres/sql/stannum--0.3.0--0.4.0.sql:16-38`）——**两个**新重载，**尾参均无默认值**：
```sql
highlight(text, begin_tag text, end_tag text, query text,  field text)      -- IMMUTABLE PARALLEL SAFE
highlight(text, begin_tag text, end_tag text, query indexed_query, field text) -- STABLE  PARALLEL SAFE
```
无默认值是硬约束：PostgreSQL 禁止默认参后跟非默认参，且第 5 参带默认会让 4 参调用产生歧义（`postgres/sql/stannum--0.3.0--0.4.0.sql:8-11`）。

**约束限制**
- `field => NULL` = **单列行为**：field 组**不贡献任何标记**（`postgres/src/highlight_udfs.rs:474-481` 的 pg_test 明确钉住：`title:(needle)` + `field=NULL` → 无 `<b>`）。
  - ⚠️ 这与 RFC 原文不同：RFC §5.11 曾写「多列无 field 时逐字段高亮以换行连接」（`docs/designs/lsg4-rfc.md:1075-1080`），**落地实现改成了 NULL 即单列行为**（`docs/query-language/fields.md:103-105`）。以下游文档 `fields.md` 为准。
- 非 scope 的部分在任何字段名下都正常标记；`title:(needle)` + `field='body'` → 无标记。
- bound 重载：`field` 非 NULL 时**必须是该索引 recorded fields 之一**，否则 `ERROR: stannum.highlight(): unknown field '<x>'`（`postgres/src/highlight_udfs.rs:149-157`）。

**`highlight_support` 改写条件**（`postgres/src/highlight_udfs.rs:293-393`）——这是关键，**只有 4 参形式被注册了 SUPPORT**：
```sql
ALTER FUNCTION stannum.highlight(text,text,text,text) SUPPORT stannum.highlight_support;  -- :397
ALTER FUNCTION stannum.highlight_ansi(text,int,text) SUPPORT stannum.highlight_support;   -- :399
```
改写链路逐条门槛：
1. 请求必须是 `SupportRequestSimplify`，`root`/`fcall` 非空；
2. 函数名只能是 `highlight`（query 位置 3）或 `highlight_ansi`（位置 2）；
3. `args[query_position]` 必须存在且**类型为 text**（传 `indexed_query` 已绑定 → 直接 unhandled）；
4. `args[0]`（document）必须 `single_varno`（单一 Var）；
5. 该 RTE 必须是 `RTE_RELATION`；
6. 收集同层 `==>` 子句：query 为 NULL Const 时用 `combined_query` 把多个常量子句 OR 成一个常量；非常量则**只保留第一个**；
7. 取索引：`binding.bound`（第一个已绑定子句的索引）或 `bind_to_index(root, document)`；**取不到就 unhandled**；
8. `bound_operand(query, index)` 必须成功；
9. **字段归属只在 `highlight` 且 document 是裸 Var 时发生**：`column_field_name`（:231-256）按 Var 的 `varattno` 在 `indkey` 中的位置选出字段名；表达式 / 外表 / 单列索引 → `None`；
10. 命中则把 FuncExpr 的 funcid 换成 bound 重载（`bound_overload`，:278-291，按 `field.is_some()` 追加 text 参数），并把 field 名作为 text Const **追加到 args 末尾**。

**即**：`SELECT stannum.highlight(title, '<b>','</b>', NULL) FROM docs WHERE title ==> 'x'` 在**多列索引**上会被自动改写成 5 参 bound 形式并自动带上 `'title'`。**5 参 text-query 形式本身没有 SUPPORT**，不会被改写，用的是默认 tokenizer 设置。

**成本代价**：改写后函数从 `IMMUTABLE` 变 `STABLE`（需开 AccessShareLock 读索引 meta）。

**benchmark 证据**：与 Lead 的参考 oracle——235/235 查询/状态对**完全一致**，HTML/ANSI 逐字节比对，零差异，高亮排除列表为空（`docs/compatibility.md:106-111`，Lead revision `0e29dbe5...`，extension `tin` 1.0.3，PG18，5000 fixture 行 + 边界行）。字段维度由 `oracle --fields` 16/16 覆盖（`docs/plans/...:1353`）。

---

## 4. `search()` / `search_count()`

**签名**（`postgres/sql/stannum--0.4.0.sql:473-501`，实现 `postgres/src/search.rs:379-447`）：
```sql
stannum.search(index regclass, query text, limit int DEFAULT 10,
               snippet text DEFAULT 'html', begin_tag text DEFAULT '<mark>',
               end_tag text DEFAULT '</mark>', k1 real DEFAULT NULL, b real DEFAULT NULL)
  RETURNS TABLE (ctid tid, score real, snippet text)   -- VOLATILE PARALLEL UNSAFE
stannum.search_count(index regclass, query text) RETURNS bigint  -- VOLATILE PARALLEL UNSAFE
```

**做什么**：绕过 planner 的独立打分入口，返回 `(ctid, score, snippet)`。`limit <= PRUNE_MAX_K(4096)`（`postgres/src/score.rs:544`）走 `pruned_top_k`，失败/超限回落 `exhaustive_rows`。

**约束限制**
- **无过滤参数**：没有 WHERE/过滤形参，只有 index + query + limit + 渲染 + k1/b。要过滤必须回表自 join（返回的是 `ctid`，不是行）。
- `query` 为 NULL → ERROR；`limit < 0` → ERROR；`limit = 0` 提前返回空但仍校验 query/mode/BM25 参数。
- **要求 segmented 索引**（LDP2 页布局）：`ERROR: stannum.search() requires a segmented stannum index`。legacy zero-page 索引不可用。
- **snippet 模式**：`'none' | 'html' | 'ansi'`，其他值 ERROR。多列索引 snippet 要求每个 key 列都是 text 兼容类型（text/varchar/bpchar/name），否则提示改用 `snippet => 'none'`（`postgres/src/search.rs:39-100`）。
- 多列 snippet 渲染规则（`postgres/src/search.rs:337-372`、`docs/query-language/fields.md:87-101`）：单个**顶层** Field 组命名的字段 > 第一个有匹配的字段 > 第一个非 NULL 列的纯文本；全 NULL → snippet 为 NULL。`title:(x) OR body:(y)` 没有顶层 wrapper（`top_level_field_name` 只认根 `Field`/`Boost{Field}`）。
- **权限**：走 `require_stannum_index` → `validate_stannum_index` + **`require_index_select`**（`postgres/src/udfs.rs:398-444`）：需要表级 SELECT 或Owner（`pg_read_all_data` / 角色继承均可），**列授权与 RLS 不够**，且表启用 RLS 时直接 `ERROR: index diagnostics require ownership or SELECT without row security`。
- 需要 `stannum` AM 索引，非 stannum regclass → ERROR。

**exact-count 路径**
- `search_count`：`build_standalone_scorer` → `matching_tids()` → `visible_tid_pairs()`，逐候选做可见性判定，返回**精确**计数（非估算），并带同样的权限/segmented 门槛。
- 另一条精确计数路径是 **Count 自定义扫描节点**：`EXPLAIN ANALYZE` 显示 `Count Strategy: page bitmaps` 或 `scalar`；稠密布尔项（占用页平均 ≥4 tuple）用页掩码 + popcount，稀疏/位置查询走 scalar（`docs/architecture/segmented-storage.md:258-268`）。`SET stannum.enable_custom_scan = off` 可切回 PG bitmap 路径做对照（:286-287）。

**benchmark 证据**
- 页掩码计数：synthetic count mix 中位 **2,551.8 → 10,443.8 q/s（4.09×）**，5/5 pair 改善；Wikipedia count mix **6,112.1 → 6,264.4 q/s（基本不变，+2.49%）**（`docs/benchmarks/page-bitmap-counts.md:97-98,126`）。
- 100k Wikipedia 本地对比：Lead 0.39 count q/s（5 次中位），Stannum **1,458.45 count q/s / 644.79 mixed q/s**，同机 4CPU/4GiB，伴随约 20 updates/s（`docs/benchmarks/README.md:126-142`）。作者自标 preliminary。
- 流式无序搜索的生命周期证据：335 个 standby 快照答案零错误（1 次预期 recovery conflict），766 次 ranked 比较覆盖 66,437 行（`docs/benchmarks/streaming-search.md:44-48`）。

**版本/兼容**：`search()`/`search_count()` 是 **0.3.0** 引入（WI-3，`docs/plans/...:1340`）；**0.4.0 才支持多列索引**（WI-12，:1352），带 `snippet=>'none'` 降级模式。

---

## 5. `index_stats` / `index_health` / `segment_info`

**签名与列含义**

`stannum.segment_info(index regclass)`（`postgres/sql/stannum--0.4.0.sql:507-522`，实现 `postgres/src/udfs.rs:274-310`）—— 逐段一行：
| 列 | 含义 |
|---|---|
| `ordinal` | 目录内序号 |
| `kind` | `'immutable'` / `'mutable'`（写缓冲） |
| `root_block` | 段链起始页 |
| `docs` / `dead_docs` | 文档数 / 已死文档数（**死数只在 VACUUM 识别后才进 dead list**，DELETE 本身不填） |
| `sum_doc_lengths` | 该段 token 总长 |
| `total_pages` | 占用页数 |
| `generation` | 世代号（per-backend reader cache 的键；REINDEX 改 identity，世代绝不重用） |

`stannum.index_stats(index regclass)`（`postgres/src/udfs.rs:333-405`）：`documents`（= Σ(docs−dead)）、`dead_documents`、`dead_ratio`、`segments`、`immutable_segments`、`mutable_segments`、`next_generation`、`total_pages`、`dictionary_pages`、`total_length`、**`average_length`（恒为 `0.0`，保留列）**、`analysis_matches`、`analysis_detail`。
- `dictionary_pages` 的语义有专门的列注释：= 所有 immutable 段 dictionary extent **覆盖**的页数（不管本后端是否读过），与 `EXPLAIN` 的 `Dictionary Pages Read`（本次 scan 实际 pin 的页）**设计上不同**，只有全索引扫描时才相等（`postgres/sql/stannum--0.4.0.sql:165`）。
- `average_length = 0.0` 是显式决定：dead 文档下的均值定义未定，v1 宁可报 0 也不报误导性均值（`postgres/src/udfs.rs:396-398`）。

`stannum.index_health` **视图**（`postgres/sql/stannum--0.4.0.sql:161-164`）：`WITH (security_invoker = true)`，对每个 stannum 索引 `CROSS JOIN LATERAL index_stats(c.oid)` 一行。**非 segmented 索引返回 0 行**（`index_stats` 早退）。

**权限要求**（三者共用，`postgres/src/udfs.rs:415-444`）：表级 SELECT 或表 Owner；`pg_read_all_data` 与角色继承都被 PG 的 ACL 检查覆盖；**列授权与 RLS 均不足**；表启用 RLS 时报错 `index diagnostics require ownership or SELECT without row security`。`index_health` 用 `security_invoker` 让视图按调用者身份评估，非 Owner 只能看到自己有 SELECT 权的索引。

**适用场景**
- `segment_info`：看段数是否逼近 `max_segments`、`dead_docs` 是否该触发 VACUUM、写缓冲是否长期不 fold。
- `index_stats`：一次性的健康快照（dead_ratio 阈值、页数增长、analysis drift）。
- `index_health`：全库巡检一条 SQL。
- `verify_index(index, heap_check => false)`（`postgres/src/udfs.rs:446-470`）是另一档：返回 `(severity, location, message)`，空 = 一致；`severity='error'` 一律 `REINDEX`，`warning` 多数 `VACUUM` 可解（完整操作员手册见 `docs/architecture/segmented-storage.md:564-588`）。它持 index + table 的 `ShareLock`（standby 上 `AccessShareLock`），所以插入/fold/merge/VACUUM 会等它。

**v13 现状锚点**：`v13/mgraph/test_stannum_usage.py:1037-1047` 已断言 `index_stats('ix_chunks_stannum')` 的 `average_length == 0` 且 `analysis_matches IS NULL`；`index_health` 的行集合**必须恰好等于那 5 个索引**（F10）；`segment_info` 的 `kind ⊆ {immutable, mutable}`（F11）。

---

## 6. GUC 族调优语义

全部注册于 `postgres/src/storage/mod.rs:64-175` + `postgres/src/customscan.rs:107-116` + `postgres/src/storage/wal.rs:65-80`。除 `wal_rmgr_id` 外**全部 `GucContext::Userset`**（可 `SET` 在会话/事务级）。

| GUC | 默认 | 域 | 语义与适用负载 | 证据 |
|---|---|---|---|---|
| `stannum.write_buffer_docs` | 512 | 1..1,000,000 | 缓冲文档数上限；调小 → 更早 fold、更多更小的段。短文档先撞这个 | `segmented-storage.md:45`；`storage/mod.rs:126-137` |
| `stannum.write_buffer_bytes` | 1,048,576 | **1,024..67,108,864** | 编码 forward-record 字节上限。单个超大文档允许超限（作为一个 record，在下一个 insert 前 fold）。2.8 KiB/record 时 ≈365 文档而非 ≈1460 | `segmented-storage.md:46,51-57`；`storage/mod.rs:110-120` |
| `stannum.max_merge_docs` | 1,024 | 0..i32::MAX | 一个插入后端一次 fold 内普通 merge 可重写的**输入文档总数**（含级联）。超预算的 merge 等 VACUUM。**`0` = 推迟所有预算内 merge**（目录可增长，VACUUM 无预算兜底）。索引构建期不受限 | `segmented-storage.md:135-139,147-151`；`storage/mod.rs:121-132` |
| `stannum.build_segment_docs` | 32,768 | 1..10,000,000 | `CREATE INDEX`/`REINDEX` 每段文档数。**只约束构建内存**；调小 → 段更多 | `segmented-storage.md:44`；`storage/mod.rs:138-148` |
| `stannum.max_segments` | 128（**磁盘硬上限**） | 1..128 | 软上限。超限时 merge 最小的 `entry_count - max_segments + 1` 个（通常 2 个）；insert 只在剩余预算内做，否则留给 VACUUM。**只有 128 条目磁盘上限会强制无预算 merge**。低于 128 可让预算内 merge 更早发生、留出 `128 - max_segments` 次 fold 余量 | `segmented-storage.md:141-159`；`storage/mod.rs:149-159` |
| `stannum.merge_tier_factor` | 8 | **2..64** | 段按文档数分 tier（`factor^t .. factor^(t+1)-1`）；最低的满 tier 凑够 `factor` 个就 merge 成下一 tier 一个。低于 2 每次 fold 都 merge（故 clamp 到 2） | `segmented-storage.md:128-133`；`storage/mod.rs:88-89,160-175` |
| `stannum.experimental_vacuum_merge_strategy` | `auto` | `auto`/`direct`/`reconstruct` | 实验对照开关。`auto` 当前等价 `direct`（无密度启发式）；`reconstruct` 强制全量校验 + 整源记录解码；**超大聚合输入无论何值都回落 legacy fallback**。选定时打 DEBUG1 说明 | `docs/benchmarks/vacuum-final-integration.md:18-24`；`storage/mod.rs:81-87,105-118` |
| `stannum.enable_custom_scan` | `on` | bool | 关掉则 `==>` 查询走 PG bitmap 路径（该路径也不做任何 recheck）。用于 plan 对照/回归 | `segmented-storage.md:286-287`；`customscan.rs:107-116` |
| `stannum.strict_analysis` | `off` | bool | 把「已盖戳但 jieba 分析漂移」的索引从 WARNING 升级为 **ERROR**；未盖戳的 legacy jieba 索引仍只 WARNING 且可用 | `docs/compatibility.md:160-164`；`storage/mod.rs:98-108` |
| `stannum.wal_rmgr_id` | 128（`RM_MIN_CUSTOM_ID`） | `RM_MIN_CUSTOM_ID..RM_MAX_CUSTOM_ID` | **`GucContext::Postmaster`**，只在 `shared_preload_libraries` 预加载时才定义/生效；必须 primary 与所有 standby 一致且不被其他扩展占用 | `storage/wal.rs:39,65-80` |

**调优证据（写路径）**
- fold 上限从 16,384 docs / 4 MiB 降到 512 docs / 1 MiB：**最差 insert 2,909.452 ms → 149.356 ms（19.5×）**，压力下 895.725 → 178.990 ms（5.0×）；最差 update 304.459 → 137.456 ms（默认）/ 1,098.025 → 303.068 ms（压力）。代价：读者 count/ranked p99 高 1.7%/1.1%，吞吐低 2.6%；旧上限那组最差 insert/update 是 427.382/404.776 ms（即再降 2.9×）（`docs/benchmarks/merge-budget.md:137-154`）。
- buffer index 每 MiB 记录约 **11 ms** 构建成本：512 docs/1.69 MB → 21.3/17.9 ms；1,460/4.23 MB → 54.7/46.2 ms；4,096/11.18 MB → 144.9/110.1 ms（第 2/3 次语句）。字典 memo 打补丁后在 `new` 状态移除 40% 中位 count 延迟、30% 中位 ranked 延迟、+16% 吞吐（`docs/benchmarks/buffer-index.md:95-101,137-141`）。
- 可预测的维护节奏建议（插入为主/混合负载）：`vacuum_index_cleanup = auto` + `autovacuum_vacuum_insert_threshold = 1000` + `autovacuum_vacuum_insert_scale_factor = 0` + `autovacuum_vacuum_threshold = 1000` + `autovacuum_vacuum_scale_factor = 0`（`segmented-storage.md:211-219`）。

---

## 7. `wal_rmgr_id` / `shared_preload_libraries` 与 WAL removal horizons

**机制**（`docs/architecture/recovery-and-parallel.md:36-146`）
- generic WAL 只回放页镜像/增量，**不带快照信息**，所以回放时不会产生 standby recovery conflict。两个 stannum 操作会移除 standby 旧快照可能还需要的页：(1) 页复用（pending list 在 primary 上按 xmin 保护，回放没有）；(2) merge/VACUUM 重写发布丢掉可见条目的目录。
- 解法：自定义 WAL resource manager 记录 **removal horizon**。唯一记录类型 `XLOG_STANNUM_RECLAIM (xl_info 0x00)`，内容 = 关系定位符 + `snapshotConflictHorizon`（仍可能引用待释放页的最新 xid）。
- **发射点**：`drain_pending` 在把 pending run 标 FREE **之前**立即发一条。horizon 在目录**发布后**由 `write_meta` 重读 next xid **重盖**（因为发布前另一个事务可能先拿到该 id 并先于发布提交），完全对标 nbtree `_bt_log_reuse_page` 的 `safexid`。
- **回放**：redo 调 `ResolveRecoveryConflictWithSnapshot(horizon, isCatalogRel, locator)`，在后续 generic 记录释放页**之前**取消/等待冲突查询。`max_standby_streaming_delay` / `hot_standby_feedback` 语义不变。
- 写 buffer 页另有一层：standby `view` 记录 meta page 的 LSN，拒绝任何由更晚记录写入的 buffer 页，等到对应 meta 记录回放后重试（仅活性，不影响正确性）。

**不预加载的损失**
1. **standby 退回 heap fallback**（`reference path`），segmented 读取路径不可用——索引在 standby 上**不被选择性读取**，靠 regex 顺序扫描兜底（仍正确，但慢）。planner 和 executor 都问 `storage::index_reads_allowed`（`recovery-and-parallel.md:31-34`）。
2. primary 不写 `RECLAIM` 记录 → 无 horizon 保护。meta page 的 `FLAG_REMOVAL_HORIZONS` 只在 rmgr 已注册且关系 WAL-logged 时置位；**没有预加载的 primary 最后写过的索引，standby 会一直保持 heap fallback 直到被有预加载的 primary 重写**。
3. **PostgreSQL 只在 preload 时注册自定义 rmgr**，遇到未注册管理器的记录会**恢复失败**——所以该设置必须在任何 `RECLAIM` 记录写出之前**全集群一致**。
4. hot standby 上的 jieba 自定义词典从 WAL 可见表行读，不静默替换为内置词典（`docs/compatibility.md:166-169`）。

**诊断函数**（`postgres/sql/stannum--0.4.0.sql:141-147, 316-322, 650-654`）
- `stannum.index_reads_allowed(index regclass) → bool`（VOLATILE PARALLEL SAFE）
- `stannum.logs_removal_horizons(index regclass) → bool`
- `stannum.wal_rmgr_id() → int`，**未预加载时返回 NULL**

**部署要求**：`shared_preload_libraries = 'stannum'` 于 primary **和每个**回放其 WAL 的 standby；`wal_rmgr_id` 全集群一致且不与其他扩展冲突。

**证据**：`postgres/tests/postings_lifecycle.py` 在 standby 上持 REPEATABLE READ 快照，同时 primary 强制 fold/merge/deferred merge/delete/VACUUM/页复用，每轮与**同一快照内的 heap regex 扫描**比对；契约是**零错误答案**：feedback 开或无限延迟时每个快照都能答，有限延迟且无 feedback 时冲突可取消查询。另测了带 recovery 期快照的 standby 提升、standby 上的索引打分、primary 崩溃恢复（`RECLAIM` 记录作为 no-op 回放）。

---

## 8. LSG3 / LSG4 段格式兼容矩阵

来源：`docs/compatibility.md:224-235`、`docs/architecture/segmented-storage.md:488-509`、`docs/designs/lsg4-rfc.md:419-455,583-600`。

| 场景 | 行为 |
|---|---|
| 单列索引（0.3.0 或 0.4.0 建） | **永远写 LSG3**（`Format::CURRENT` 永久停在 `Lsg3`；LSG4 只由 field-aware builder 入口写，`field_count >= 2` 才传 `Lsg4`） |
| 0.4.0 读 LSG1/LSG2/LSG3 | 全部可读，字节布局**从未改动**，fixture 逐字节相同；升级绝不重写 LSG3 |
| 多列索引 | 写 **LSG4**：magic `LSG4` + `layout_revision`(必须=1) + `field_count`(1..16) + `field_total` u64le×N；长度表变 doc-major field 行，payload 按字段分组位置，postings bounds 带 per-field max/min |
| LSG3 段 × LSG4 段 merge | **被拒绝**；一个索引绝不混两种段 |
| **pre-0.4.0 二进制打开 LSG4 索引** | **打不开，fail closed**：段 magic 拒绝 + meta fields trailer 拒绝（meta 解码器不接受尾部字节） |
| 带 fields trailer 的索引在 0.4.0 之前 | 同样打不开；与 jieba analysis stamp 同形的「已接受的回滚限制」 |
| 磁盘降级 | **不存在**。回滚 = 恢复备份，或在 drop extension version 后用旧二进制 REINDEX |
| page-special version | 保持 **2**；未知 meta trailer tag fail closed |
| upgrade 脚本 | `ALTER EXTENSION stannum UPDATE TO '0.4.0'`，**只加两个 `stannum.highlight` 重载**，无其他 on-disk 变更 |
| 世代耗尽 | 报错要求 REINDEX，绝不 wrap 复用 reader-cache 键（`segmented-storage.md:132-133`） |
| `MAX_FIELDS = 16` | 对 `layout_revision 1` 冻结；扩到 32 走 revision 2，读者拒绝未知 revision |
| LSG1 段的 ranked 扫描 | 无 block bounds → **每个候选都打分**（不剪枝）；`verify_index` 给 warning（`segmented-storage.md:573`） |

**格式体积证据**：LSG3 相比 LSG2 让 100k Wikipedia 索引**缩小约十分之一**且剪枝能力不变（`CHANGELOG.md`）。LSG4 相对 LSG3 的体积开销**无实测数字**。

---

## 9. jieba 分词器（0.4.0 侧 API 与索引选项）

**索引选项**（`postgres/src/options.rs:57-61, 226-235`）：
```sql
CREATE INDEX ... USING stannum (body) WITH (tokenizer = 'jieba');
```
- 枚举值 `unicode | whitespace | jieba`；`jieba` 是 **stannum 特有、无 TIN 对应**的扩展（`docs/compatibility.md:24,57`）。
- `graphemes` 选项在 jieba 下**无效**（segmenter 不产独立 emoji/symbol token）。
- `stannum.tokenize(text, tokenizer => 'jieba', ...)` 与 `stannum.ql_parse(query, tokenizer => 'jieba', ...)` 同样接受。
- 确定性由 `Cargo.lock` 里钉住的 jieba-rs 版本保证；**升级该 crate 必须 REINDEX**（分词可能变）。

**行为**：`开源数据库` → 两个 term `开源`/`数据库`（而非 4 个单字 token）；跨多词的查询词重写成相邻短语，与 `unicode` 的多 token 词同样处理；非 Han 段按 jieba 整段分析（与 UAX#29 在标点桥接 ASCII 上有差异，`can't` → `can` + `t`），但索引与查询两侧同一 pipeline，匹配保持一致。内置词典首次使用约 **100 ms 一次性暂停 + 数 MB RSS**。

**词典治理 SQL**（`docs/compatibility.md:127-175`、`postgres/src/dict.rs:285-345`）：
- `stannum.jieba_words(word text PK, freq int >= 0, tag text)`，`REVOKE ALL FROM PUBLIC`；**必须**用函数而非直接 DML。
- `stannum.jieba_add_word(word, freq DEFAULT 0, tag DEFAULT NULL)`（upsert）、`stannum.jieba_delete_word(word)`（幂等）、`stannum.jieba_dict_version() → bigint`（SipHash-1-3 内容指纹，按位保留的有符号 bigint；十六进制显示用 `lpad(to_hex(...),16,'0')`）、`stannum.jieba_reload_dict()`、`stannum.index_analysis(index)`、`stannum.builtin_stop_words('zh'|'en'|'auto')`。
- 约束：word 非空、≤256 UTF-8 字节、无 Unicode 空白；freq 非负（0 = 让 jieba 选默认频）。**只有 superuser 与 `pg_database_owner` 成员**可变更或强制重载（invoker-run + 显式 Rust 授权检查）。
- 变更立即使其他后端缓存失效；abort/savepoint 丢弃未提交词典；重载失败保留旧词典并传播 ERROR。
- **CREATE INDEX / REINDEX 会给 jieba 索引盖 runtime jieba version + 词典指纹戳**；漂移每索引每语句一条 WARNING（建议 REINDEX），`strict_analysis = on` 把「已盖戳但漂移」升级为 ERROR。
- **自定义词典非空的 jieba 索引，v1 自定义扫描拒绝并行 worker**（含同关系的竞争 bitmap/heap 路径）——词典快照不经 DSM 传递。

**打分侧**：`score_stop_words` 接受 `auto` / `auto:zh` / `auto:en`（大小写不敏感选择子，可与字面 CSV 混用）；只有产生**恰好一个** index-analyzer token 的预设词被保留；**`score()` 遵守该 reloption，`full_score()` 永远忽略**（`docs/compatibility.md:177-186`）。`score_inspect` 对 segmented 索引用持久化 analyzer，对其诊断性非 segmented 回退用全新 reloption pipeline。

---

## 10. `benchmarks/` 实测数字：与本任务相关的部分

**直接相关（0.4.0 特性）**
- **WAND 剪枝率**（LSG4 BM25F bounds，WI-12）：`LIMIT 10 / 1200 docs`，**LSG3 = 112 scored / 1088 pruned，LSG4 = 362 scored / 838 pruned** → `docs/plans/stannum-p0-agent-features-2026-09-22.md:1352`。**注意方向**：LSG4 剪得更少。
- **正确性 gate**（同文件 :1351-1354）：workspace 14 suites green、pg18 unit **49/49**、pg_test **183/183**、clippy `-D warnings`、fmt、release install + `extension_upgrade`（4 条升级路径、指纹相等、LSG3 索引仍可读）、`ranked_fuzz` default + `--fields` seeds **105/206**、`postings_lifecycle`、`oracle --fields` **16/16**；推送 `067a557..18bdd8c`。
- **无任何** `docs/benchmarks/*.md` 提及 `field_weights` / `BM25F` / `LSG4` / 多列（grep 零命中）。多列索引的**性能证据只有剪枝率那一行**。

**间接相关（写路径 / GUC）**
- `docs/benchmarks/merge-budget.md:137-154`：fold 上限下调 → 最差 insert **2,909.452 → 149.356 ms（19.5×）**；读者 p99 +1.7%/+1.1%，吞吐 −2.6%。
- `docs/benchmarks/buffer-index.md:95-101,137-141`：buffer index 构建 ~**11 ms/MiB**；512 docs=21.3 ms、1,460=54.7 ms、4,096=144.9 ms（首次语句）；字典 memo 补丁 → 中位 count −40%、中位 ranked −30%、吞吐 +16%。
- `docs/benchmarks/vacuum-final-integration.md:18-24`：`experimental_vacuum_merge_strategy` 三值语义；local integration 463 core unit + 117 PG tests ×(17,18) + Python harness 79 tests。

**间接相关（读路径 / count）**
- `docs/benchmarks/page-bitmap-counts.md:97-98`：synthetic count mix **2,551.8 → 10,443.8 q/s（4.09×）**；Wikipedia **6,112.1 → 6,264.4 q/s**（≈不变）。
- `docs/benchmarks/README.md:126-142`：100k Wikipedia 本地 Lead vs Stannum，count **0.39 vs 1,458.45 q/s**，mixed 644.79 q/s（作者标注 preliminary：Lead 5 次中位、Stannum 每负载 1 次，非交替对跑）。
- `docs/benchmarks/streaming-search.md:44-48`：335 standby 快照答案零错误；766 ranked 比较 / 66,437 行。
- `docs/compatibility.md:106-111`：高亮与 Lead `tin` 1.0.3 **235/235 完全一致**（47 查询 × 5 变更状态）。

**benchmark 脚本**：`benchmarks/query_shapes.py`（宽布尔 + SQL 集成 + 独立成员性检查）、`benchmarks/run.py`（campaign/profile 驱动）、`benchmarks/insert_latency.py`、`benchmarks/merge_costs.py`、`benchmarks/foreground_writes.py`、`benchmarks/vacuum_cleanup.py`、`benchmarks/sustained.py`。**没有任何脚本接受多列/字段参数**（grep `field` 在 `benchmarks/query_shapes.py` 零命中）；字段维度只在 `postgres/tests/ranked_fuzz.py --fields` 与 `benchmarks/oracle.py --fields` 里。

---

## 被忽略的候选（上面 1–10 未列，但 v13 可能用得上的能力）

1. **TINQL 全套高级语法，v13 目前零采用**：wildcard/regex/range/fuzzy 词典展开（>1,024 项走保守候选 + 行文本 recheck，`segmented-storage.md:245-247`）、`AT LEAST n OF [...]` / `ALL OF`、proximity `NEAR/n`、span relations、positional filters（`IN FIRST/LAST n%`）、boost `^n`、`CONTAINS`、slop `"..."~n`。文档：`docs/query-language/terms.md`、`alternatives.md`、`proximity.md`、`span-relations.md`、`positional-filters.md`、`boost.md`。
2. **`stannum.highlight_ansi(text, wrap_to, query)` + bound 重载**（`postgres/sql/stannum--0.4.0.sql:98-106, 231-239`）——v13 `ZERO_FUNCS` 里显式钉为零使用（`v13/mgraph/test_stannum_usage.py:77-81`）。TUI/CLI 场景可能比 HTML 更合适。
3. **`stannum.score_inspect(index, query, dense_ratio, term_add, term_replace)` → `(term, weight)`**（`postgres/sql/stannum--0.4.0.sql:424-437`）——调 `score_stop_words` / `term_add` / `term_replace` 的诊断入口。
4. **`stannum.max_score(ctid)` 与 6 参 `stannum.score(ctid, dense_ratio, k1, b, term_add, term_replace)`**——v13 只用 `full_score`。`score()` 的 `dense_ratio` 会省略极常见词，`full_score()` 不会；这是现成的相关性调谐旋钮。
5. **Count 自定义扫描节点**（`Count Strategy: page bitmaps`）——精确计数的另一条路，不必引入 `search_count()` 的 SRF。
6. **`stannum.tokenize` / `ql_parse` / `maybe_quote` / `builtin_stop_words`**——全在 v13 `ZERO_FUNCS` 里。`ql_parse` 是调试 TINQL 解析/分词的唯一正规入口。
7. **`score_stop_words` reloption 与 `auto:zh` / `auto:en` 预设**——中文语料的打分噪声过滤，且**不需要重建匹配行为**（只影响 `score()`，`full_score()` 忽略）。
8. **TIN 兼容 reloption（接受但忽略 + WARNING）**：`initial_segment_count`、`target_segment_count`、`max_mutable_segment_size`、`max_merged_segment_size`、`dead_percent_threshold`（`docs/compatibility.md:34-47`、`postgres/src/options.rs:462-479`）——如果 v13 的 DDL 要从 TIN 移植，这些能直接吃下但不产生任何行为。
9. **`stannum.index_reads_allowed` / `stannum.logs_removal_horizons`**（§7）——如果 v13 将来上 standby，这两个是唯一的状态探针。
10. **`pg_stat_progress_create_index` 子相位**（`heap scan` / `segment flush` / `final merge-finish`，注意 **blocks 列分母在命令中途从 heap blocks 切成 blob pages**，`segmented-storage.md:71-84`）——长 REINDEX 的进度观测。
11. **`postgres/tests/*.py` 五个 Python harness**：`ranked_fuzz.py --fields`、`observability.py`、`extension_upgrade.py`、`postings_lifecycle.py`、`search_srf.py`——v13 侧的 `test_stannum_usage.py` 之外，可复用的独立验收资产。

---

## 附：v13 采纳 0.4.0 时的现存 gate 冲突点

`v13/mgraph/test_stannum_usage.py` 当前把「零采用」钉成了断言，采纳任何一项都需同步改这些断言：
- `F8`（:1031-1033）断言 `stannum.search` **不出现**在源码与所有执行计划里；
- `F4`（:983-1010）断言 5 个生产索引**全部** `indnatts = 1`，且 `body ==> 'body:(lager)'` 形式必须报 `XX000`；
- `F5`（:1012-1018）断言单列 + `field_weights` 必须报 `multi-column` 错；
- `V8`/`V9`（:633-635）断言 `stannum.wal_rmgr_id()` 为 NULL 且 `current_setting('stannum.wal_rmgr_id')` 报 unrecognized（即**未预加载**）；
- `V6`（:624）断言 `highlight` 恰好 4 个重载且类型集合等于 `HIGHLIGHT_TYPES`（已含 5 参两种，此项实际已兼容 0.4.0）；
- `F13`（:1063-1082）断言 6 个 GUC 全为默认值、`experimental_vacuum_merge_strategy ∈ {auto, Auto}`；
- `F10`/`F11`/`F9` 断言 `index_health` 行集合恰好是那 5 个索引、`segment_info.kind ⊆ {immutable,mutable}`、`average_length == 0`。
