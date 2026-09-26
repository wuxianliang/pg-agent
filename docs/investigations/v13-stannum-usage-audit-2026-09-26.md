# v13 对 stannum 0.4.0 的实际使用核查（2026-09-26）

**性质**:只核查、只设计测试。本文件是唯一新增物。零生产 SQL / Python 改动，零 gate 实现，零 commit。
**上一份报告**:[`v13-stannum-0.4-pgembed-adaptation-2026-09-25.md`](v13-stannum-0.4-pgembed-adaptation-2026-09-25.md) 已覆盖升级跨度、L0–L4 分层、M0–M2 交付（版本记载、`index_stats` runbook、jieba 探针）和「不要用 `search()` 换三段式」。本文件不重复那些结论，只回答一件事：0.4.0 的每项能力，v13 **跑起来时**有没有走到。
**结案约束**（测试设计必须守，不在本文件重裁）:[`v13-stannum-0.4-m3-m6-closeout-2026-09-25.md`](../plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md)。生产索引保持 unicode；`decisions.question` 不切分词；不启用 `field_weights` / BM25F；jieba 若再议只接受整包。本设计的探针只允许出现在测试进程里的临时表，测完即 DROP。

## Context / Scope

核查范围是 v13 主树里所有会在 stage 库执行的路径，加上 stannum `0.4.0` 安装脚本的全部 SQL 对象。

| 事实 | 依据 |
|---|---|
| pgembed 捆绑 pin | `pgembed/pgbuild/Makefile:278` `STANNUM_COMMIT := ad4d3b74d9c903d14b32cc000b42d15e2b7ef26b` |
| 本机 stannum 工作树 | `/Users/wxl/Projects/stannum` HEAD `24f5c02`。`git diff ad4d3b7..HEAD -- postgres segment tinql tokenizer` 为空。API 与 pin 一致，多出来的提交只动追踪文档 |
| 扩展版本 | `postgres/stannum.control` `default_version = '0.4.0'`；workspace `Cargo.toml` `version = "0.4.0"`；`stannum.version()` 返回 `CARGO_PKG_VERSION`（`postgres/src/udfs.rs:495-499`） |
| pgembed Python 包版本 | `pgembed/pyproject.toml` 仍是 `0.3.0rc2`。包版本没有跟着 stannum pin 跳。v13 `pyproject.toml:8,19` 是 `pgembed>=0.3.0rc1` + editable `../pgembed` |
| 0.4.0 SQL 增量 | `postgres/sql/stannum--0.3.0--0.4.0.sql` 只新增两个 `highlight` 尾参重载（第 5 参 `field text`，无默认值）。函数**名**集合与 0.3.0 相同（36 个名字，0.4.0 共 41 条 `CREATE FUNCTION`，多出来的是 highlight 重载） |
| 0.4.0 行为增量 | `docs/compatibility.md:200-234`：多列索引、`field_weights`、BM25F、字段组 + same-field 短语、`==>` 按左操作数列收窄、`search()` 可扫多列、单列索引继续写 LSG3、多列写 LSG4 且旧二进制打不开 |
| v13 调用形态 | 纯 SQL。全仓库 Python 对 `stannum.` 的引用只有各 stage `setup_db.py` 的 GRANT 和测试里的 SQL 字符串。没有 `import stannum`，没有 `pgembed_stannum` |

`CHANGELOG.md` 只写到 0.1.0-dev，不能当 0.4.0 的 API 清单。API 以 `postgres/sql/stannum--0.4.0.sql` 为准。

**状态词**（矩阵里只用这些）:

| 状态 | 含义 |
|---|---|
| 生产运行时 | characterize 及之后的 stage 库里，v13 SQL 函数体在被调用时会执行到。测试调用的是同一个函数 |
| 规划器运行时 | v13 源码没有调用文本，计划树里会出现（support / 算子过程 / 选择率） |
| 仅 gate | 只有 `test_*.py` 直接调 stannum。生产函数体没有这条调用 |
| 仅 runbook | 只写在 README 或调查里，SQL 与测试都没有执行 |
| 完全未用 | 生产、gate、runbook 都没有把它当成要执行的步骤。调查文档里提过名字不算使用 |
| GRANT 必要 | `setup_db.py` 授权，源码零调用，但角色执行被改写后的计划时必须有这个 EXECUTE |

「生产运行时」不等于「每个 stage 的测试库都走 stannum」。`CREATE EXTENSION stannum` 的唯一装载点是 `v13/characterize/v13_characterize.sql:15`。`files_through("recall")` 的 8 个文件库里没有这个扩展，`v13_recall` 仍是 tsvector 体。

---

## A. 使用矩阵

### A.1 召回到底从哪条路径进 stannum

`v13/recall/v13_recall.sql` 的 `v13_recall`（121–149 行）和 `v13_recall_count`（151–171 行）是 `body_tsv @@ phraseto_tsquery`。`v13_recall_candidates`（173–217 行）按名字调用 `v13_recall` / `v13_recall_count`，自己没有 `stannum.`。G1（`test_recall.py:1063-1072`）把这件事钉死：recall 文件去注释后 `==>` 与 `stannum.` 都是 0。

characterize 用 `CREATE OR REPLACE` 换掉四个函数，签名不变，所以后面 stage 再调用旧名字就进了新体:

| 换体后的函数 | 位置 | 引擎动作 |
|---|---|---|
| `v13_extract_spans` | `v13_characterize.sql:31-79` | 直接 `stannum.highlight(p_body, open, close, tinql)`，4 参 text 重载（59 行） |
| `v13_recall` | 81–113 行 | 动态 SQL：`stannum.full_score(c.ctid)`（106）+ `chunks.body ==> $1`（110）+ sources 未 superseded 连接 |
| `v13_recall_count` | 115–131 行 | 动态 SQL：同一连接上的 `body ==> $1`（128），不计分 |
| `v13_verify_chunks` | 133–222 行 | `stannum.verify_index('ix_chunks_stannum', true)`（191） |

因此 filter / economy / summary / periphery / mgraph_assembly 里的 `v13_recall_candidates(...)` 在各自 stage 库（都加载过 characterize）走的是 stannum 体。它们的源码扫描仍然是 0 次 `stannum.`：`test_filter.py:2547`、`test_economy.py:550`、`test_periphery.py:377`。这是设计不变量（引擎调用只许出现在收敛文件里），不是「这些 stage 没用 stannum」。

另外两条生产检索不经过 `v13_recall`:

| 函数 | 动态 SQL | 谁被授权调用 | 谁在 SQL 里调用它 |
|---|---|---|---|
| `v13_transcript_recall` | `v13_memory.sql:149-155`：`full_score` + `session_id` 与 `body ==>` | 三角色（239–242 行） | **没有**。全树 SQL 只有定义和 GRANT。调用点全在 `test_memory.py` |
| `v13_mgraph_candidates` | `v13_mgraph.sql:751-757`：`full_score` + `session_id`、`origin='episodic'`、`body ==>` | `v13_recall`（1211–1212，「M3 读环锚复用」）名义有 EXECUTE，**实际不可用**：内部 invoker 依赖 `entities_of`/`entities`/`keywords_of`/`jaccard`（1204–1209）只授 `v13_resolve`。`v13_resolve` 有完整链 | SQL 调用方三处，都只在 resolve 面上可走：`v13_mgraph_build`（1040，写路径）、`v13_mgraph_anchors`（1684）、`v13_mgraph_transition_score`（1802）。后两处是读环函数，EXECUTE 只授 `v13_resolve`（2598、2604），不以 `v13_recall` 执行。以 recall 角色走这条链的读环调用方缺位。G6 的 EXPLAIN 不是这条 SQL（见 B.12） |

`ix_decisions_question_stannum`（`v13_memory.sql:158-161`）有索引、有 `verify_index`，没有检索。注释写明消费者是语义决策缓存台账，机制不做。

### A.2 索引与访问方法

五个 stannum 索引，全部单列，除 canary 外没有 `WITH`。

| 索引 | DDL | 选项 | 检索 | verify_index |
|---|---|---|---|---|
| `ix_chunks_stannum` | `v13_characterize.sql:29` | 默认 | 生产：`v13_recall` / `v13_recall_count` | 生产：`v13_verify_chunks`；cron 字符串仍是 `SELECT v13_verify_chunks(true)`（`v13_chunks.sql:1148`），OR REPLACE 后跑的是 v2 |
| `ix_v13_canary` | `v13_characterize.sql:26-27` | `long_tokens=split, max_token_bytes=64` | 仅 gate（K/L/M 组直接查 canary） | 仅 gate（`test_characterize.py:564,586,607`） |
| `ix_transcript_stannum` | `v13_memory.sql:32` | 默认 | 函数体是生产形态，**无 SQL 调用方**，gate 在调 | 生产函数 `v13_verify_memory`（182 行），owner-only，不挂 cron |
| `ix_decisions_question_stannum` | `v13_memory.sql:161` | 默认 | 无检索 | 同上，185 行 |
| `ix_memory_nodes_stannum` | `v13_mgraph.sql:49` | 默认 | 生产：`v13_mgraph_candidates` 及其调用方 | **没有**。全树 `verify_index` 只有上面三处 |

`long_tokens=split` 是 reloption 默认值（`options.rs:257-265`，缺省 `LONG_SPLIT`）。canary 相对生产索引真正不同的只有 `max_token_bytes` 64 对默认 256。

AM `stannum`、operator class `stannum_text_ops`、算子 `pg_catalog.==>` 的 text/text 与 text/`indexed_query` 两个过程（`stannum--0.4.0.sql:581-601`）都在上述谓词上使用。v13 源码写的是 text/text。text/`indexed_query` 与 `bind_query` 由 planner support 改写产生（`v13_characterize.sql:10-12` 的注释，以及 K5 对视图 / 静态 plpgsql / PREPARE 的复测，`test_characterize.py:458-492`）。

### A.3 函数

「生产」列指换体后的 v13 函数体。「gate」列指测试脚本里的直接 SQL，不含「测试调用了 v13_recall 所以间接执行到」。

| 对象 | 状态 | 证据 |
|---|---|---|
| `full_score(tid) → real` | 生产运行时 | 三处动态 SQL：`v13_characterize.sql:106`、`v13_memory.sql:151`、`v13_mgraph.sql:753`。均为 1 参。`score_support` 挂在这个签名上（`stannum--0.4.0.sql:462`），计划里常被改写成 `score_bound*` |
| `full_score(tid, real, real)` | 完全未用 | 0.4.0 仍在。v13 无 3 参调用 |
| `highlight(text, text, text, text)` 4 参，带默认标签 | 生产运行时 | `v13_extract_spans` 59 行，传入的是 plpgsql 变量 `p_body`，不是表列。`highlight_support` 只挂在这个 4 参 text 签名上（`stannum--0.4.0.sql:264-265`）。变量不会按索引 oid 绑定。生产四索引都是默认 tokenizer/fold/256，与 `highlight` 的默认参数一致，所以今天 spans 与索引切分一致。canary 的 64 字节上限不在这条路径上（`v13_recall` 只读 `chunks`） |
| `highlight(..., indexed_query)` 4 参 | 完全未用 | 索引绑定高亮。v13 不调用 |
| `highlight(..., text, field text)` 5 参 | 完全未用 | 0.4.0 新增。无默认值，所以 4 参调用不会误绑到它 |
| `highlight(..., indexed_query, field text)` 5 参 | 完全未用 | 同上 |
| `highlight_ansi` 两个重载 | 完全未用 | |
| `highlight_support(internal)` | 规划器运行时，且 v13 的调用形状吃不到 | 只有当 `highlight` 的第一个参数是扫描里的列时才会改写。`v13_extract_spans` 先把 body 取进变量 |
| `verify_index(regclass, bool)` | 生产运行时（三索引）+ 仅 gate（canary） | 见 A.2。`memory_nodes` 不在内。函数入口 `require_index_select`（`udfs.rs:446-457`）：要表级 SELECT 或 owner |
| `segment_info(regclass)` | 仅 gate | `test_characterize.py:509` 只查 `ix_v13_canary`。生产索引零调用。返回列没有段格式名，看不出 LSG3/LSG4 |
| `index_stats(regclass)` | 仅 runbook | `v13/characterize/README.md:33-132` 有调用示例和 2026-09-25 的实测数字。SQL 与 `test_*.py` 零执行。13 列；`average_length` 被 README 记为实测恒 0.0（64 行），实现是有意写死的 0（`udfs.rs:390-392`） |
| `index_health` 视图 | 仅 runbook | 同节。`security_invoker=true`（`stannum--0.4.0.sql:161-164`）。characterize 及之后的库都有 canary 表，三角色对 canary 无 SELECT（`test_characterize.py:862-872`），所以这三个角色调用该视图会在 canary 那一行失败。示例查询是 owner 视角 |
| `search(...)` / `search_count(...)` | 完全未用 | 适配调查 §2.2 已否决替换。本轮复核：v13 树仍零调用 |
| `score(tid, ...)` / `max_score(tid)` / `score_inspect(...)` | 完全未用 | `score` 与 `max_score` 也挂了 `score_support`，没有 v13 查询会把它们放进计划 |
| `score_bound(text ×2, int ×3, real ×3, text[] ×2)` | GRANT 必要 | 源码零调用。`REVOKE ALL FROM PUBLIC`（`stannum--0.4.0.sql:466`）。12 个 `setup_db.py` 把 EXECUTE 授给三角色。堆打分计划会发出它 |
| `score_bound_indexed(tid, text, int ×3, real ×3, text[] ×2)` | GRANT 必要，且 transcript 计划已实证 | 同上，467 行 REVOKE。`test_memory.py:515-521`：带 `session_id` 的查询计划 JSON 含 `score_bound_indexed`、主键 Bitmap、无 Seq Scan。这是 `v13_transcript_recall` 那条 SQL 的形状，但测试复制了 SQL，没有从函数体抽取 |
| `score_support(internal)` | 规划器运行时 | 上两行的改写入口 |
| `bind_query(text, oid)` / `indexed_query` 类型 | 规划器运行时 | v13 不直接调用。K1/K5 用 EXPLAIN 与三禁路径证明 `==>` 保持绑定 |
| `stannum_text_cmpfunc` / `_indexed` / `_support` / `stannum_text_restrict` | 规划器运行时 | 算子过程与选择率。无 v13 调用文本 |
| `tokenize` / `ql_parse` | 完全未用 | 函数在 0.4.0 里，默认参数就是生产索引的默认 reloption。`docs/designs/v13-context-on-pg.md:661` 仍写「`tokenize()` 待核实」；DP5 计划附 B 已记「已实测存在」。文档漂移，不是运行时缺口 |
| `maybe_quote` | 完全未用 | DP5 已改走全段引号（`v13_build_tinql`，`v13_recall.sql:77-81`） |
| `builtin_stop_words` | 完全未用 | |
| `jieba_add_word` / `jieba_delete_word` / `jieba_dict_version` / `jieba_reload_dict` / 表 `jieba_words` | 完全未用 | 表 `REVOKE ALL FROM PUBLIC`（`stannum--0.4.0.sql:12-17`）。行为记录在 jieba 探针，不在 v13 代码里 |
| `index_analysis(regclass)` | 完全未用 | jieba 探针用过。v13 无 jieba 索引，unicode 索引上这组列是 NULL（README 65–66 行对 `index_stats` 的同类说明） |
| `version()` | 完全未用 | 应返回 `0.4.0`。没有任何 gate 读它 |
| `wal_rmgr_id()` / `logs_removal_horizons` / `index_reads_allowed` | 完全未用 | `wal_rmgr_id` GUC 只在 `shared_preload_libraries` 加载时注册（`wal.rs:64-80`）。pg-agent 的 server 不预加载 stannum。未预加载时 `wal_rmgr_id()` 返回 NULL |
| `amhandler(internal)` | 生产运行时 | `CREATE ACCESS METHOD` 的 handler。只通过 `USING stannum` 到达 |

### A.4 授权

12 个 `setup_db.py` 的 GRANT 块逐字相同，不是 13 个，也**不包含** `full_score`:

`characterize`、`filter`、`memory`、`economy`、`summary`、`periphery`、`mgraph`、`mgraph_assembly`、`control`、`spawn`、`fanout`、`triage`。

```sql
GRANT USAGE ON SCHEMA stannum TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION
  stannum.score_bound(text,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.score_bound_indexed(tid,text,integer,integer,integer,real,real,real,text[],text[])
TO v13_recall, v13_resolve, v13_route;
```

代表位置：`v13/characterize/setup_db.py:20-30`，`v13/mgraph/setup_db.py:38-47`。注释写明原因：`full_score` 对 PUBLIC 有 EXECUTE，schema 没有 USAGE，两个 `score_bound*` 被 REVOKE 成 owner-only。角色执行 recall 链会 42501，所以授权放在部署面，不放进 SQL 文件（R 组禁止 9 号文件里出现第 4 个 `stannum.`）。

没有这块 GRANT 的 8 个 stage：`schema`、`resolve`、`loop`、`twophase`、`envelope`、`manifest`、`chunks`、`recall`。它们的加载前缀还没 `CREATE EXTENSION`，授不了。

`full_score` 不是死授权，它根本不在 GRANT 列表里。`score_bound*` 也不是死授权：transcript 形状的计划会执行 `score_bound_indexed`，没有 EXECUTE 的角色会 42501。没有 v13 源码调用点，这是预扫的误判来源。

角色与继承（`v13_core.sql:835-848`）:

| 角色 | 属性 | stannum 能力 |
|---|---|---|
| `v13_recall` / `v13_resolve` / `v13_route` | NOLOGIN | 直接被 GRANT。能执行换体后的检索（还要有对应 v13 函数的 EXECUTE 和表 SELECT） |
| `v13_resolve_login` / `v13_route_login` | LOGIN，默认 INHERIT，单成员 | 继承所属组的 schema USAGE 和 `score_bound*` EXECUTE |
| `v13_worker` | LOGIN **NOINHERIT**，同时是 resolve 与 route 的成员 | 不 `SET ROLE` 时没有 schema USAGE，也没有 v13 函数 EXECUTE。`SET ROLE v13_route` 之后与 route 相同。gate 不把 worker 当受背书的隔离形态 |
| owner / 装扩展的超级用户 | | 全部可执行。`v13_verify_chunks` 与 `v13_verify_memory` 只留给 owner（`v13_chunks.sql:1153-1159` 撤销后未授出；`v13_memory.sql:245-247`） |
| `v13_spawn_owner` / `v13_triage_owner` | 更后的 stage 才创建 | 不在 GRANT 名单里 |

E-DP5-2（`test_characterize.py:875-886`）只证明 `v13_recall` 角色能跑通 `v13_recall` 且命中 ≥ 1。它不证明另外五个角色，也不打印内部计划。

### A.5 GUC

v13 SQL 与测试都不 `SET stannum.*`。跑的是默认值。`enable_custom_scan` 默认 true（`customscan.rs:40,107-113`），K1 依赖这个默认：关掉之后 Custom Scan 不再出现，只剩 bitmap 路径（GUC 说明：off 时留下 bitmap，recheck 也不做）。

| GUC | 默认 | v13 |
|---|---|---|
| `stannum.enable_custom_scan` | true，userset | 未设置。K1 的 Custom Scan 靠默认开 |
| `stannum.strict_analysis` | false，userset | 未设置。只对已盖 jieba 戳的索引有意义 |
| `stannum.experimental_vacuum_merge_strategy` | `auto` | 未设置 |
| `stannum.write_buffer_bytes` | 1 MiB | 未设置。fold 行为的来源之一，M2 只观测 canary 的 `segment_info` |
| `stannum.write_buffer_docs` | 512 | 同上 |
| `stannum.build_segment_docs` | 32768 | 未设置 |
| `stannum.max_merge_docs` | 1024 | 未设置 |
| `stannum.max_segments` | 目录硬上限（最大 128） | 未设置 |
| `stannum.merge_tier_factor` | 8（合法 2–64） | 未设置 |
| `stannum.wal_rmgr_id` | 仅 preload 时存在，postmaster | v13 不预加载。会话里这个名字应当不存在 |

### A.6 索引选项、分词器、段格式

reloption 定义在 `postgres/src/options.rs:197-327`。

| 选项 | 默认 | v13 生产索引 | 备注 |
|---|---|---|---|
| `tokenizer` | `unicode` | 不写，即 unicode | `whitespace` 全树未用。`jieba` 只在探针库出现过，结案要求生产不切 |
| `case_folding` / `accent_folding` | `fold` | 不写 | |
| `long_tokens` | `split` | 不写。canary 写了 `split`，与默认相同 | |
| `max_token_bytes` | 256 | 不写。canary 写 64 | K3 用这个差值证明「绑定索引命中 / 标量比较漏召」 |
| `graphemes` | `emoji` | 不写 | |
| `position_gaps` | `preserve` | 不写 | |
| `k1` / `b` | 1.2 / 0.75（`bm25.rs:24-25`） | 不写 | `full_score(tid)` 用索引上的这对值 |
| `field_weights` | 未设置 | 不写 | **0.4.0 新增**。单列上设置即报错。结案 M5：不要在 v13 表上设置 |
| `score_stop_words` | 未设置 | 不写 | 注释写明 `full_score` 忽略这份名单 |
| `initial_segment_count` / `target_segment_count` / `max_mutable_segment_size` / `max_merged_segment_size` / `dead_percent_threshold` | 有默认 | 不写 | 源码注释：TIN DDL 兼容项，Stannum 忽略 |

段格式（`docs/compatibility.md:224-230`）:

| 格式 | v13 |
|---|---|
| LSG1 / LSG2 | 只读旧段。v13 的 DROP/CREATE 库不会产生 |
| LSG3 | 单列索引的写入格式。五个 v13 索引都是单列，写入的是 LSG3 |
| LSG4 | 多列索引才写。v13 没有多列索引，运行时零 LSG4 |

`segment_info` 的列是 `ordinal, kind, root_block, docs, dead_docs, sum_doc_lengths, total_pages, generation`（`stannum--0.4.0.sql:507-518`），没有格式名。要证明二进制真能写 LSG4，只能建一张临时多列表。

### A.7 已有 gate 实际钉住了什么

这些断言是真的，但它们钉的对象要分开看。新测试补的是右列缺口，不是重写左列。

| 已有断言 | 它证明的 | 它没证明的 |
|---|---|---|
| K1 `test_characterize.py:376-391` | 手写 `SELECT ... FROM chunks WHERE body ==>` 在 `enable_seqscan=off` 下是 Custom Scan，provider `Stannum Text Search Scan`，Index `ix_chunks_stannum` | `v13_recall` 内部那条带 JOIN、`full_score`、`ORDER BY`、`LIMIT` 的动态 SQL |
| K3 `test_memory.py:499-525` | 测试里复制的 transcript SQL 计划含 `score_bound_indexed` | 复制文本与 `pg_get_functiondef` 是否仍一致 |
| G6 `test_mgraph.py:2742-2757` | `session_id AND origin AND body ==>` 的计划不是 `memory_nodes` 上的 Seq Scan，且文本含 `stannum` | 同谓词加上 `full_score` 的那条 `v13_mgraph_candidates` 动态 SQL |
| L3 `test_characterize.py:495-503` | `v13_recall` 对「東京タワー」有命中、对单字片假名无命中 | 命中来自 Index/Custom Scan 而不是 Seq Scan 上的算子过滤 |
| E-DP5-2 | `v13_recall` 角色执行 `v13_recall` 能返回行 | 其他角色；内部节点类型 |
| R2 / K4 / G1 / H6 / A5 | 源码计数：引擎调用只出现在指定文件 | 运行时计划 |
| M2 | canary 上 `segment_info` 可读，generation 随插入增长 | 四个生产索引的段；LSG 版本 |
| N 组 / `v13_verify_memory` | `verify_index` 对 chunks、canary、transcript、decisions 在测试夹具下 findings=0 | `ix_memory_nodes_stannum` |

`EXPLAIN SELECT * FROM v13_recall(...)` 只能看到 plpgsql 的 Function Scan。动态 SQL 的计划要另取。这是 C 节抽取器存在的原因。

---

## B. 缺口与风险

1. **检索函数跑了，计划形状没有钉在函数体上。** K1/K3/G6 解释的是手写或复制的 SQL。`v13_recall` 多一个 sources 连接和 `ORDER BY full_score LIMIT`，计划可以跟 K1 的单表 Custom Scan 不同，现有 gate 仍绿。`v13_transcript_recall` 连一个 SQL 调用方都没有，K 组绿只说明测试在调它。

2. **`ix_memory_nodes_stannum` 被检索、不被 verify。** DP9 计划原文要求 `v13_verify_mgraph` 对两索引做 `verify_index`（`docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md:66`）。实现里没有这个函数，`verify_index` 的全部 SQL 调用是 characterize 一处加 memory 两处。图索引损坏不会进 verify 报告。

3. **`ix_decisions_question_stannum` 只有校验没有查询。** 与「机制不做」的注释一致，不是意外。风险是 runbook/设计文把它说成结构化层已经接上 stannum（`docs/designs/v13-context-on-pg.md:127`）。索引在，检索不在。

4. **`index_stats` / `index_health` 停在 README。** M1 的交付就是 runbook，没有 gate。示例数字（128 文档、dead_ratio 0）会随库重建失效，README 自己也这么写。`average_length` 恒 0 是实现写死的，不是样本巧合。三角色跑 `SELECT * FROM stannum.index_health` 会因为 canary 无 SELECT 而整视图失败；README 的权限段写了 all-or-nothing，示例没有标明必须是 owner。

5. **高亮没有绑到索引。** 生产路径用 4 参 text `highlight`，参数是变量。默认参数碰巧等于生产索引默认 reloption，所以 unicode/fold/256 下 spans 是对的。一旦生产索引改 `tokenizer`、`max_token_bytes` 或 `long_tokens`，`v13_extract_spans` 仍按函数默认切，召回按索引切。jieba 探针 §4 已经在非默认 tokenizer 上看到这种分裂。0.4.0 的 5 参 field 重载完全没进这条路径。当前默认配置下这不是错，是一条没有测试锁住的对齐假设。

6. **`score_bound*` 的 GRANT 容易被看成死授权。** 源码零调用是事实，死授权不是。transcript 形状的计划执行 `score_bound_indexed`（K3）。chunks 上的 Custom Scan 可能在 C 里打分、不进入这两个 SQL 函数。两种计划对 EXECUTE 的需求不同，今天没有一条断言把「没有 GRANT 就 42501」和「Custom Scan 不需要 GRANT」分开。

7. **预扫的 GRANT 计数需要更正。** 是 12 个 stage 不是 13 个；GRANT 的函数是 `score_bound` 与 `score_bound_indexed`，没有 `full_score`。`full_score` 靠 PUBLIC EXECUTE + 上面的 schema USAGE。

8. **0.3 → 0.4 对当前 v13 调用面的实际暴露。** 单列、无 `field_weights`、4 参 `highlight`、1 参 `full_score`、text/text `==>`。这些签名 0.4.0 没改。会踩到 v13 的差异是行为而不是签名：
   - same-field 短语规则改的是**带字段组**的位置查询。v13 的 tinql 是不带字段前缀的引号段（`v13_build_tinql`）。单列索引上左操作数已经唯一，这条新规则没有第二个字段可误配。
   - `==>` 按左列收窄同样要多列才有区别。
   - BM25F 只在记录了字段权重的多列索引上发生。五个 v13 索引仍是单列 BM25，`k1=1.2`、`b=0.75`。
   - 5 参 `highlight` 无默认值，旧调用不会变重载。
   - 绝对分值没有被 gate 钉死（README 台账 ③：只保证有限数值和 `content_hash` 终裁）。0.4 若在单列上改了打分常数，K/P/Q 的命中集合仍可能全绿。本核查没有把「分值与 0.1.0 表一致」当成使用证据。
   - O2 的 1030 词项段错误在 0.4.0 已记录为未复现（`v13/characterize/README.md:150-153`）。那是一次实测，不是一条会在每次建库时重跑的版本断言。

9. **版本字符串可以与二进制能力脱节。** 没有任何 gate 读 `pg_extension.extversion` 或 `stannum.version()`。M0 的记载在 README 和 SQL 注释里，下次 bundle 漂了，K 组仍可能绿。pgembed 包版本 `0.3.0rc2` 也不携带 stannum pin；pin 在 Makefile。

10. **文档漂移（不影响正确性，核查时会误导）。**
    - `docs/designs/v13-context-on-pg.md:661`：`tokenize()` 仍是「待核实」。函数自 0.1.0 就在，v13 确实没调用它。
    - 同文件 92 行把 EXPLAIN 预期写成「stannum IndexScan」。实测节点是 Custom Scan（K1 已按实测钉，设计文未改）。
    - 适配调查 §2.2.3 写 `index_stats` 12 列。README 已改成 13 列并注明那是计数偏差。以 README 和 `stannum--0.4.0.sql:153-158` 为准。
    - `v13/mgraph_assembly/README.md` 与 characterize README 顶部已改到 0.4.0。DP5 计划第 7 行保留 0.1.0 原文并加了消歧注，这是有意的历史行。

11. **recall 库与「现环境」不是同一个运行时。** 只跑 `test_recall.py` 时，`v13_recall` 是 tsvector，CJK 短语的期望与 characterize 的 L3 相反是正常的。把 G1「零 `stannum.`」读成「v13 召回不用 stannum」是错的。把它读成「recall 文件禁止出现引擎名」是对的。

12. **「M3 读环锚复用」授权不可用，recall 角色的读环调用方缺位。** `GRANT EXECUTE ON v13_mgraph_candidates TO v13_recall`（`v13_mgraph.sql:1211-1212`）在 INVOKER 链上走不通：`entities_of` / `entities` / `keywords_of` / `jaccard`（1204–1209）只授 `v13_resolve`。`v13_recall` 直调即 42501，错误文本含 `v13_mgraph_entities_of`。SQL 调用方三处（1040 `v13_mgraph_build`、1684 `v13_mgraph_anchors`、1802 `v13_mgraph_transition_score`）都只在 `v13_resolve` 的授权面上可走；anchors / transition_score 是读环函数，并不授给 `v13_recall`。与装配交付时 J9 暴露的四个 INVOKER 链 ACL 缺口同族（`v13/mgraph_assembly/README.md` 第 9 条）。待用户裁决：补内部授权、移除这条死授权，或落地以 `v13_recall` 执行的读环调用方。本 gate 只锁现状（R8a/R8b），不改 GRANT。

---

## C. 测试设计

第二阶段只新增一个 gate 脚本，并在 mgraph README 加一行指向它。不改 `SQL_LOAD_ORDER`，不改任何 `v13_*.sql`，不改 12 个 GRANT 块，不改生产索引，不把 jieba / `field_weights` 写到 chunks、transcript_chunks、memory_nodes、decisions、canary 上。

### C.0 放哪、怎么接

| 项 | 值 |
|---|---|
| 文件 | `v13/mgraph/test_stannum_usage.py` |
| 运行 | `uv run python v13/mgraph/test_stannum_usage.py`，退出码 0 为通过 |
| 库 | `agent_v13_mgraph`。脚本开头调用 `v13.mgraph.setup_db.main()`，与 `test_mgraph.py` 一样 DROP/CREATE 并加载到 stage `mgraph`（15 个 SQL 文件）。这一前缀同时含 chunks、transcript、decisions、memory_nodes 四个生产索引和 canary |
| `load.py` | 不改 |
| 新 SQL | 不需要。临时对象全部在测试连接里 `CREATE` / `DROP` |
| 夹具风格 | 独立脚本，自带与 `test_characterize.py:42-66` 同形的 `check` / `fails_with`。不要 import `test_mgraph.py` |
| 会话 GUC | 与 characterize 的 `guc()` 相同：`search_path = public, pg_catalog`，`typesafe.provider=mock`，`typesafe.model=jev-mock`。除此以外不 `SET stannum.*`，除非某条断言正在测「关掉 custom scan」 |
| README | `v13/mgraph/README.md` 加一行：本 stage 还有 `test_stannum_usage.py`，核查 stannum 使用，不改图语义 |

mgraph 是第一个同时拥有四条生产引擎路径的 stage。放到 characterize 会缺 transcript 与 memory_nodes；放到 triage 只能多看到两个本来就没有 stannum GRANT 的 owner 角色，不值得把 20 个文件的装载算进这条 gate。

### C.1 计划抽取（所有 EXPLAIN 断言的共同做法）

`EXPLAIN` 一个 plpgsql 函数调用看不到内部 `EXECUTE`。对下面四个函数各做一次：

- `v13_recall(text,int)`
- `v13_recall_count(text)`
- `v13_transcript_recall(uuid,text,int)`
- `v13_mgraph_candidates(uuid,text,int)`

步骤：

1. `SELECT pg_get_functiondef(oid)`，用 `regprocedure` 钉死签名，避免同名重载。
2. 在函数体里找执行动态 SQL 的那一处：`RETURN QUERY EXECUTE` 或 `FOR ... IN EXECUTE` 或单独的 `EXECUTE`。
3. 只接受由单引号字面量经 `||` 拼出来的 SQL。`''` 是转义后的一个引号。遇到标识符、函数调用、`$tag$` 美元引号就失败（当前四个体都是纯字面量拼接）。
4. 把拼好的 SQL 规范化空白后，与下表做**全文相等**。相等说明连上的库就是这份源码，而不是一份手写复制。

| 函数 | 拼好后的 SQL（空白可折叠，其余逐字） |
|---|---|
| `v13_recall` | `SELECT c.content_hash, stannum.full_score(c.ctid)::numeric AS bm25, v13_extract_spans(c.body, jsonb_build_object('tinql', $1)) FROM chunks c JOIN v13_sources src ON src.source_hash = c.source_hash AND src.superseded_by IS NULL WHERE c.body ==> $1 ORDER BY bm25 DESC, c.content_hash ASC LIMIT $2` |
| `v13_recall_count` | `SELECT count(*) FROM chunks c JOIN v13_sources src ON src.source_hash = c.source_hash AND src.superseded_by IS NULL WHERE c.body ==> $1` |
| `v13_transcript_recall` | `SELECT t.content_hash, stannum.full_score(t.ctid)::numeric AS bm25, t.seq_from FROM transcript_chunks t WHERE t.session_id = $1 AND t.body ==> $3 ORDER BY bm25 DESC, t.content_hash ASC LIMIT $2` |
| `v13_mgraph_candidates` | `SELECT n.content_hash AS h, n.body AS b, n.source_at AS at, stannum.full_score(n.ctid)::numeric AS s FROM memory_nodes n WHERE n.session_id = $1 AND n.origin = 'episodic' AND n.body ==> $2 ORDER BY n.content_hash ASC` |

5. 对拼好的 SQL 跑 `EXPLAIN (FORMAT JSON)`，参数用下面的夹具。外层再 `EXPLAIN` 一次 `SELECT * FROM <函数>(...)`，只断言节点类型是 Function Scan。这把「外层解释看不到内部计划」写成明示断言，避免以后有人用外层 EXPLAIN 冒充内部证据。

统计计数在事务提交时才刷出。读 `pg_stat_user_indexes.idx_scan` 或 `pg_stat_user_functions.calls` 的顺序是：读基线 → 执行 → `COMMIT` → 新事务里再读。增量在提交前看，会误判成没走到索引。

`track_functions` 由超级用户 `SET track_functions = all`（SUSET）。pgembed 的测试连接是超级用户。设置之后要新事务才稳定计数。

### C.2 夹具

全部用 owner 连接，提交后再做计划与计数。

**Chunks。** 沿 `test_characterize.py` 的 `succeed_tool` + `ingest_doc`：建 session，`v13_append_event` 一条 `user/message`，`v13_enqueue_effect(..., 'tool', ..., 'v13_ingest_corpus')`，`v13_claim` / `v13_complete` 成 succeeded，再 `v13_ingest_document(eid, 'docs', body)`。两篇 body 就够：

- `quasar formation in high redshift surveys`
- `東京タワーは電波塔である kohaku`

查询串用 `v13_build_tinql`。英文查询 `"quasar"` 的拼装结果是 `"quasar"`。CJK 短语用 `東京タワー`。

**Transcript。** 另一 session。`v13_append_event` 一条 `llm/message`，payload `{"text": "private session text quasarium"}`。`SELECT v13_rebuild_transcript_chunks(100)`。tinql 用 `v13_build_tinql('quasarium')`。

**Memory nodes。** owner 直接插入一行（表的 CHECK 要求 hash 自证、episodic 必须有 `source_at`、`source_hashes` 至少一个元素）:

```sql
INSERT INTO memory_nodes (
  session_id, content_hash, body, origin, source_hashes, source_at, builder_version)
VALUES (
  :sid, v13_body_hash(:body), :body, 'episodic',
  ARRAY[v13_body_hash(:body)], now(), 1);
```

`body` 用 `为什么用户无法登录`。查询用 `v13_mgraph_anchor_tinql` 对同一串的返回值（OR 形，过 `v13_mgraph_anchor_guard`）。不要把 `v13_build_tinql` 的 AND 形送进 `v13_mgraph_candidates`，入口会 V3005，那是 G7 已经钉的文法，不是本 gate 的对象。

**Decisions。** 不插入、不查询生产函数。本 gate 只证明没有检索调用方，并用 owner 的 `verify_index` 证明索引可读。

### C.3 断言

每条都是 `check(label, ...)`。失败即非 0 退出。`[info]` 可以打印计划，但不能代替断言。

#### ① 版本现实

| id | 验证什么 | 怎么验 | 预期 |
|---|---|---|---|
| V1 | 装上的扩展是 0.4.0 | `SELECT extversion FROM pg_extension WHERE extname='stannum'` | `'0.4.0'` |
| V2 | 默认版本也是 0.4.0，不是旧库残留 | 在 `postgres` 库查 `pg_available_extensions.default_version`，name=`stannum` | `'0.4.0'` |
| V3 | 二进制自报版本与 catalog 一致 | `SELECT stannum.version()` | `'0.4.0'` |
| V4 | 服务器是 PG 18 | `current_setting('server_version_num')::int` | `>= 180000` 且 `< 190000` |
| V5 | pgembed 包版本仍是仓库记载的 rc，不把包版本误当成 stannum pin | `importlib.metadata.version('pgembed')` | `'0.3.0rc2'` |
| V6 | 0.4.0 的两个新重载真在这个库里 | `pg_proc` 中 `nspname='stannum'` 且 `proname='highlight'` 的 `pg_get_function_identity_arguments` | 集合里同时有 `text, text, text, text, text` 和 `text, text, text, stannum.indexed_query, text`。4 参那两个也在。合计 4 个 highlight |
| V7 | 5 参重载可调用，且 `field` 为 NULL 时与 4 参相同（`stannum--0.3.0--0.4.0.sql:13-15` 的单列行为） | owner：`highlight('beer', '<b>', '</b>', 'beer', NULL)` 与 `highlight('beer', '<b>', '</b>', 'beer')` | 两者相等，且都含 `<b>` |
| V8 | 未预加载 WAL rmgr | `SELECT stannum.wal_rmgr_id()` | NULL |
| V9 | `stannum.wal_rmgr_id` 这个 GUC 名字不存在 | `current_setting('stannum.wal_rmgr_id')` | 失败，错误文本含 `unrecognized` |
| V10 | custom scan 默认开着，测试没有偷偷关掉 | `current_setting('stannum.enable_custom_scan')` | `'on'` |
| V11 | strict_analysis 保持默认关 | `current_setting('stannum.strict_analysis')` | `'off'` |

V7 用字面量，不建多列索引。它证明新重载被装进了这个集群，不证明 v13 在用它。

#### ② 运行时证据

先做 C.1 的全文相等（断言 id P0a–P0d，四个函数各一条）。然后：

| id | 验证什么 | 怎么验 | 预期 |
|---|---|---|---|
| P1 | `v13_recall` 的内部计划走 stannum，不是 chunks 顺序扫描 | `enable_seqscan=off`，EXPLAIN JSON 拼好的 SQL，参数是 `"quasar"` 与 `8` | 节点里有 Custom Scan，`Custom Plan Provider` = `Stannum Text Search Scan`，`Index` = `ix_chunks_stannum`。没有 `Relation Name` = `chunks` 的 Seq Scan。计划文本（`json.dumps`）含 `full_score` 或 `score_bound` |
| P2 | 函数调用本身会动到这个索引，而不只是一条长相像的 SQL | `enable_seqscan=off`，提交夹具后读 `ix_chunks_stannum` 的 `idx_scan`，再 `SELECT * FROM v13_recall(:tinql, 8)`，提交后再读。同时 `track_functions=all`，看 `score_bound`、`score_bound_indexed`、`stannum_text_cmpfunc` 的 `calls` 增量 | `idx_scan` 增量 ≥ 1，**或者** 三个函数的 calls 增量之和 ≥ 1。两个都是 0 则失败。返回行 ≥ 1，且每行 `bm25` 是有限数（非 NaN、非 Inf）。打印计划与计数到 `[info]`，断言只看这两个条件 |
| P3 | `v13_recall_count` 同样不顺序扫描 chunks | EXPLAIN 拼好的 count SQL，`enable_seqscan=off` | 无 chunks 上的 Seq Scan。计划含 `ix_chunks_stannum`，或含 Custom Scan provider `Stannum Count`，或含 `Stannum Text Search Scan`。三者至少其一。执行 `v13_recall_count` 的结果 ≥ 1，且与 `v13_recall` 在 k=1024 下的行数相同 |
| P4 | CJK 短语经生产函数命中，单字片假名不命中 | `v13_recall(v13_build_tinql('東京タワー'), 8)` 与 `v13_build_tinql('タ')` | 短语行数 ≥ 1；单字行数为 0。这是现状锁（unicode），不是 jieba 后的期望 |
| P5 | spans 来自 4 参 highlight，且与默认参数调用一致 | 取 P2 返回的一行，用 `content_hash` 读 `chunks.body`，比较 `v13_extract_spans(body, jsonb_build_object('tinql', tinql))` 与手工 `stannum.highlight(body, chr(1), chr(2), tinql)` 再按 extract 的哨兵算法不必重做：直接断言 spans 是 jsonb 数组，且 `stannum.highlight` 用 chr(1)/chr(2) 的结果里，标签位置推出的区间等于 spans。body 不含 chr(1)..chr(8) | spans 非空数组；两个区间序列相等 |
| P6 | transcript 函数体的计划就是 K3 那种复合计划 | EXPLAIN JSON 拼好的 transcript SQL，`enable_seqscan=off`，参数 sid / k=8 / tinql | 文本含 `score_bound_indexed`、`transcript_chunks_pkey`、`Bitmap Index Scan`。不含 `"Node Type": "Seq Scan"`。然后真正 `SELECT * FROM v13_transcript_recall(...)`：行数 ≥ 1，`idx_scan(ix_transcript_stannum)` 或 `score_bound_indexed.calls` 在提交后增量 ≥ 1 |
| P7 | 另一个 session 看不到这条 transcript | 第二个 sid 调 `v13_transcript_recall` | 0 行。这是在确认 P6 走的是带 `session_id` 的那条 SQL，不是整表 `search()` |
| P8 | mgraph 候选函数的动态 SQL 走索引并且算了分 | EXPLAIN 拼好的 candidates SQL，`enable_seqscan=off` | 无 `Seq Scan on memory_nodes`。计划文本含 `stannum`，且含 `full_score` 或 `score_bound`。执行 `v13_mgraph_candidates(sid, anchor_tinql, 10)` 行数 ≥ 1。提交后 `ix_memory_nodes_stannum.idx_scan` 或对应 score 函数 calls 增量 ≥ 1 |
| P9 | decisions 索引不在任何函数的执行串里 | 对 `pg_proc` 中 `pronamespace` 为 public、`proname` 以 `v13_` 开头的每个 `pg_get_functiondef` 做子串搜索 | 没有 `question ==>`，没有 `ix_decisions_question_stannum` 出现在 `v13_verify_memory` 以外的函数里。`v13_verify_memory` 的定义里有这一处 verify，允许 |
| P10 | decisions 索引本身是活的 stannum 索引 | owner：`SELECT count(*) FROM stannum.verify_index('ix_decisions_question_stannum', true) WHERE severity IN ('error','warning')` | 0 |
| P11 | memory_nodes 索引同样能 verify，尽管没有生产校验函数 | owner 对 `ix_memory_nodes_stannum` 做与 P10 相同的计数 | 0。这条把「能校验」和「已接入 verify」分开：P11 绿、而 P9 的扫描里仍然没有 `v13_verify_mgraph` |
| P12 | 四个生产索引都是单列、默认 reloption | `pg_index.indnatts` 与 `pg_class.reloptions`，amname=`stannum`，relname 为四个生产索引 | `indnatts=1`。`reloptions` 为 NULL，或不含 `tokenizer`、`field_weights`、`jieba`。canary 的 reloptions 恰好是 `long_tokens=split` 与 `max_token_bytes=64`，且不含 `tokenizer` |
| P13 | 外层 EXPLAIN 不是内部证据 | `EXPLAIN (FORMAT JSON) SELECT * FROM v13_recall(:tinql, 8)` | 有 Function Scan，没有 Custom Scan。与 P1 对照 |

P1 如果在 0.4.0 上因 JOIN 而不是 Custom Scan、但仍是 `ix_chunks_stannum` 上的 Bitmap + `score_bound_indexed`、且没有 chunks Seq Scan：把断言改成这条析取，并在 `[info]` 写下实际 provider。不要为了变绿去删「无 Seq Scan」。不要改成「有 stannum 这个词就算过」。析取只允许两种：K1 那种 Custom Scan，或 K3 那种 Bitmap + `score_bound_indexed` 且 Index 名是 `ix_chunks_stannum`。

#### ③ 0.4.0 特性：是否被 v13 走到

这一组判定「使用」，不把未采用的特性做成生产行为。临时表用完在同一个测试里 DROP。

| id | 特性 | 判定 | 怎么验 | 预期 |
|---|---|---|---|---|
| F1 | 单列 `==>` + 1 参 `full_score` + 4 参 `highlight` + `verify_index` | 已使用 | P1–P8、P10 | 那些断言绿 |
| F2 | Custom Scan / `enable_custom_scan` 默认开 | 已使用（chunks 无过滤时）；transcript 复合谓词走 bitmap | P1 与 P6 的节点类型不同是预期，不要合成一个节点名 | P1 为 Custom Scan；P6 为 Bitmap + `score_bound_indexed` |
| F3 | `score_bound_indexed` | 已使用（规划器发出） | P6 | 计划含该名字，且无 GRANT 时见 R 组 |
| F4 | `field_weights`、多列 BM25F、LSG4、5 参 field highlight 的绑定形式 | 未用于任何 v13 表 | P12，加上：`CREATE TABLE v13_usage_probe (title text, body text)`；`CREATE INDEX ... USING stannum (title, body) WITH (field_weights='title:3,body:1')`；插入一行 `('lager','beer ale')`；`SELECT title ==> 'title:(lager)'` 为真，`SELECT title ==> 'body:(lager)'` 为假；`DROP TABLE` | 临时索引建得成；两个布尔与上表一致。四个生产索引的 `indnatts` 仍是 1。失败信息若是「单列不能设 field_weights」，说明临时索引用错了列数，修测试不要改生产 DDL |
| F5 | 单列上设 `field_weights` 必须失败 | 生产不会走到，引擎应拒绝 | 在另一张单列表上 `CREATE INDEX ... WITH (field_weights='body:1.0')`，然后 DROP 表 | 建索引失败 |
| F6 | `tokenizer=jieba`、`jieba_*`、`strict_analysis`、`index_analysis` | 未用于生产索引 | P12 不含 jieba。不在本 gate 建 jieba 索引（词典加载和结案范围都不属于这条使用核查） | reloptions 无 `jieba`。`current_setting('stannum.strict_analysis')` 仍是 off |
| F7 | `tokenizer=whitespace` 及其余未写的 reloption | 未设置 | P12 | 生产 reloptions 为 NULL |
| F8 | `search` / `search_count` | 未使用 | 源码：`files_through('mgraph')` 去注释后不含 `stannum.search`。运行时：P2/P6/P8 的计划不含 `Function Scan` on `search` | 零匹配 |
| F9 | `index_stats` | 未接入 verify，函数可用 | owner 对 `ix_chunks_stannum` 调 `index_stats` | 返回恰好 1 行；`documents >= 1`；`average_length = 0`；`analysis_matches` 与 `analysis_detail` 都是 NULL。不要把 README 里的 128 / 13 页写进断言 |
| F10 | `index_health` | 未接入生产函数；owner 能看全库 | owner `SELECT index::text FROM stannum.index_health` | 集合等于五个索引名：四个生产 + `ix_v13_canary` |
| F11 | `segment_info` 在生产索引上 | 生产函数不调；本 gate 只确认生产索引也能读 | owner 对 `ix_chunks_stannum` 调 `segment_info` | 至少 1 行；`kind` 取值属于 `{immutable, mutable}` 这组（以实际返回的小写文本为准，打印 `[info]`）。不断言 generation 的具体数字 |
| F12 | LSG3 | 单列索引的写入格式，无 SQL 列可直接读 | P12 的 `indnatts=1` 加上 compatibility 规则即「这些索引写 LSG3」。F4 的临时多列索引是 LSG4 的存在性证明，不把它留在库里 | P12 与 F4 都绿，且 F4 之后 `pg_class` 里没有 `v13_usage_probe` |
| F13 | GUC 族（除 V10/V11/V9 已覆盖的） | 未设置 | `current_setting` 对 `write_buffer_docs`、`write_buffer_bytes`、`max_merge_docs`、`build_segment_docs`、`max_segments`、`merge_tier_factor`、`experimental_vacuum_merge_strategy` | 分别是 `512`、`1048576`、`1024`、`32768`、`128`、`8`、`auto`。`max_segments` 的默认是源码里的 `MAX_SEGMENTS` 常量 128（`storage` 模块硬上限）。若实值不是 128，打印实值并失败，不要改源码去凑 |
| F14 | `tokenize` / `ql_parse` / `maybe_quote` / `builtin_stop_words` / `score` / `max_score` / `score_inspect` / `highlight_ansi` | 未使用 | 在 P2 的 `track_functions` 窗口里，这些 `proname` 的 calls 增量是 0。另：`files_through('mgraph')` 去注释后不含这些限定名 | 增量为 0，源码扫描为 0。`highlight` 与 `full_score` 不在这张「必须为 0」的名单里 |

F4 是唯一允许出现 `field_weights` 的地方，而且表名以 `v13_usage_probe` 开头，测试结束无条件 DROP。它不修改结案所保护的五张表（含 canary）。

#### ④ 权限

在 mgraph 库里做。每个 `SET ROLE` 放在 `SAVEPOINT` 里，失败用 `fails_with` 回滚到保存点，然后 `RESET ROLE`。预期的 SQLSTATE 一律是 `42501`，除非另注。

先建一个只用于本测试的角色，用完 `DROP ROLE`：

```sql
CREATE ROLE v13_usage_schema NOLOGIN;
GRANT USAGE ON SCHEMA stannum TO v13_usage_schema;
-- 故意不 GRANT score_bound / score_bound_indexed
GRANT SELECT ON chunks, v13_sources, transcript_chunks, memory_nodes, decisions
  TO v13_usage_schema;
```

| id | 角色 | 语句 | 预期 |
|---|---|---|---|
| R1 | `v13_recall` | `SELECT count(*) FROM v13_recall(:tinql, 8)` | 成功，≥ 1。复现 E-DP5-2，并确认 mgraph 库的 GRANT 同样生效 |
| R2 | `v13_resolve`、`v13_route` | 同上 | 成功，≥ 1。这两个角色在 `v13_recall.sql:760-761` 有 EXECUTE |
| R3 | `v13_route_login` | 同上（继承，不 `SET ROLE`） | 成功，≥ 1 |
| R4 | `v13_resolve_login` | 同上 | 成功，≥ 1 |
| R5 | `v13_worker` | 同上，不 `SET ROLE` | 失败 42501 |
| R6 | `v13_worker` | `SET ROLE v13_route` 之后再查 `v13_recall` | 成功，≥ 1。测完 `RESET ROLE` |
| R7 | `v13_recall` | `SELECT * FROM v13_transcript_recall(:sid, :tinql, 8)` | 成功，≥ 1 |
| R8a | `v13_recall` | `SELECT * FROM v13_mgraph_candidates(:sid, :anchor, 10)` | 失败 42501，错误文本含 `v13_mgraph_entities_of`。现状锁：名义授权不可用（见 B.12） |
| R8b | `v13_resolve` | 同上，同一参数 | 成功，≥ 1。获授角色下函数路径真实可用 |
| R9 | `v13_recall` | `SELECT v13_verify_chunks(false)` 与 `SELECT v13_verify_memory(false)` | 两条都 42501（owner-only） |
| R10 | `v13_recall` | `stannum.verify_index('ix_chunks_stannum', true)` 过滤 error/warning 的计数 | 成功，0。角色有 chunks 的 SELECT，`verify_index` 对 PUBLIC 仍可执行 |
| R11 | `v13_recall` | `stannum.verify_index('ix_v13_canary', true)` | 失败 42501（无 canary SELECT） |
| R12 | `v13_recall` | `stannum.index_stats('ix_chunks_stannum')` | 成功，1 行，`documents >= 1` |
| R13 | `v13_recall` | `stannum.index_stats('ix_v13_canary')` | 失败 42501 |
| R14 | `v13_recall` | `SELECT count(*) FROM stannum.index_health` | 失败 42501。这就是 README 示例对三角色不成立的运行时证据 |
| R15 | owner | `SELECT count(*) FROM stannum.index_health` | 成功，5 |
| R16 | `v13_usage_schema` | 执行 P6 那条 transcript 形状的 SQL（`enable_seqscan=off`）：`SELECT stannum.full_score(t.ctid) FROM transcript_chunks t WHERE session_id=:sid AND body ==> :tinql LIMIT 8` | 失败 42501，错误文本含 `score_bound`。这证明 K3 的计划确实要 EXECUTE，GRANT 不是死的 |
| R17 | `v13_usage_schema` | `SELECT stannum.version()` | 成功，`'0.4.0'`。有 USAGE 即可，不需要 score_bound |
| R18 | `v13_usage_schema` | `SET enable_seqscan=off` 后只做 `SELECT 1 FROM chunks WHERE body ==> :tinql`（SELECT 列表里**没有** `full_score`） | 记录结果，但断言分成两支且只允许已写明的那支：成功则 `[info]` 写「Custom Scan 不调用 score_bound SQL 函数」；失败则必须是 42501 且文本含 `score_bound`。禁止第三种结果。这条不改 GRANT |
| R19 | `v13_recall` | `SELECT has_function_privilege('v13_recall', 'stannum.score_bound(text,text,int,int,int,real,real,real,text[],text[])', 'EXECUTE')` 以及对 `score_bound_indexed(tid,text,int,int,int,real,real,real,text[],text[])` 的同一询问 | 两者都是 true |
| R20 | `v13_worker` | 对这两个函数的 `has_function_privilege`（当前用户，不 SET ROLE） | 两者都是 false |
| R21 | 源码 | 读 12 个 `setup_db.py` 的 GRANT 块 | 与 `v13/mgraph/setup_db.py:41-47` 逐字相同，且全文不含 `full_score`。8 个更早的 `setup_db.py` 不含 `GRANT USAGE ON SCHEMA stannum` |

R16 是「GRANT 必要」的直接证据。R18 允许两支，是因为 Custom Scan 与 bitmap 对 `score_bound` 的依赖在源码层不能先猜死；两支都是有信息的结果，别的结果（例如语法错误）不是。

#### ⑤ 回归范围

本 gate 不改 SQL。回归的目的只是确认第二阶段没有顺手改到被计数断言钉住的文件。

提交前必须重跑（同一 stage，以及本报告引用其源码计数的 gate）:

```bash
uv run python v13/mgraph/test_stannum_usage.py
uv run python v13/mgraph/test_mgraph.py
uv run python v13/characterize/test_characterize.py
uv run python v13/memory/test_memory.py
uv run python v13/recall/test_recall.py
uv run python v13/filter/test_filter.py
uv run python v13/economy/test_economy.py
uv run python v13/periphery/test_periphery.py
```

`test_mgraph.py` 与新 gate 共用库名 `agent_v13_mgraph`，各自在 `main` 里 DROP/CREATE，不能并行。

不必为这条 gate 重跑 control / spawn / fanout / triage：它们不新增 stannum 调用，只重复同一块 GRANT。R21 用读文件覆盖了那 12 份副本。

若第二阶段改了任何一个 `v13_*.sql` 或 `setup_db.py`，先停。那已经超出本设计。源码计数会红的位置是：

- characterize R2：9 号文件 `==>` 恰 2、`stannum.` 恰 3（`test_characterize.py:843-860`）
- memory K4：11 号文件 `==>` 恰 1、`stannum.` 恰 3（`test_memory.py:526-532`）
- mgraph G6：去注释后 `==>` 恰 1（`test_mgraph.py:2724-2727`）
- recall G1、filter、economy、periphery 的零 `stannum.`

### C.4 第二阶段不要做的事

- 不要把 `index_stats` 塞进 `v13_verify_chunks` 的返回 JSON。那会改变 version=2 的 checks 形状。
- 不要给 `ix_memory_nodes_stannum` 补生产 `verify_index`。P11 只在测试里直接调。
- 不要给 `v13_transcript_recall` 找一个生产调用方。P6 只证明函数体被执行时走索引。
- 不要把 decisions 的查询加进任何 v13 函数。
- 不要把 F4 的临时索引留在 `v13_*.sql` 里。
- 不要为了让 P1 好写去改 `v13_recall` 的动态 SQL。
- 不要重跑 jieba 质量矩阵，不要改 L3 / G6 / B3 的期望。

## Recommendations

第二阶段按 C 节实现 `v13/mgraph/test_stannum_usage.py` 并重跑「⑤ 回归范围」里的 8 个命令。实现时以 P0 的函数体全文相等为第一闸：抽不出与表中相同的 SQL，就不要改用一份手写 SQL 继续往后测。

本核查对「有没有落到实处」的结论是：单列 `==>`、1 参 `full_score`、4 参 `highlight`、chunks 的 `verify_index`、以及规划器改写出来的 `score_bound_indexed`，在 characterize 之后的库里是真路径。0.4.0 新增的多列 / `field_weights` / 5 参 field highlight / LSG4，以及 0.3.0 已有的 `search`、`index_stats`、`index_health`、jieba，都还没有进入这条路径。`index_stats` 与 `index_health` 只在 runbook 里。`ix_decisions_question_stannum` 只被校验。`ix_memory_nodes_stannum` 被检索，没有生产校验。
