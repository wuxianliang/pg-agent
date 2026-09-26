# v13 characterize —— text-search 刻画与 T0 definition 换体（DP5 stage 9）

Gate: `uv run python v13/characterize/test_characterize.py`（退出码 0 = 通过）

库名 `agent_v13_characterize`。加载前缀九文件。setup **硬前置探针**
`pg_available_extensions` 无名即 exit 非 0（fail-closed，无降级）。

> **当前 installed_version：stannum 0.4.0**（2026-09-25 实测：pgembed 捆绑
> pin ad4d3b7，stage 库 DROP/CREATE 后 `CREATE EXTENSION` 落
> default_version=0.4.0，K–R 八组同日全绿重跑）。历史记载出处：
> 0.1.0 = DP5 刻画时代实测（文末实测记录节），0.3.0 = mgraph_assembly
> 交付时代实装（其 README 自述，未随记载更新）；版本一律以
> `pg_extension.extversion` 实测为准。

## runbook 六件

1. **索引可丢基础行不可丢**：`DROP INDEX ix_chunks_stannum` 不丢 chunks/artifacts
   行。正确性检测 = EXPLAIN 形状 + verify v2 第八项。默认配置下索引丢失是
   **性能事件非正确性事件**（回退 comparator = 最宽配置）。运营健康面
   （dead/段/页，何时该 REINDEX）见「索引健康运营」节。
2. **连接池预热**：新连接有 buffer 重建税。生产连接池应在 attach 后跑一次
   热查询（`SELECT v13_recall('"quasar"', 8)`）再接流量。
3. **fold 毛刺**：M1 数字见 gate 打印。宽松守门 `p99_fold ≤ max(p99_base×10, 200ms)`。
4. **升级**：扩展版本变更 → 重跑 K3（无索引回落）与 K5（三禁路径一致性）。
   0.1.0 实测三禁路径与 EXECUTE 等价，**实测等价 ≠ 禁令撤销**
   （0.4.0 复测 2026-09-25：K3/K5 同绿）。
5. **REINDEX 演练**：`REINDEX INDEX ix_chunks_stannum; REINDEX INDEX ix_v13_canary;`
   然后复跑 K2/N1。基础行不动。何时该 REINDEX 的运营判据（dead_ratio
   阈值线）见「索引健康运营」节。
6. **AGPL 分发审查**：分发本扩展或链接产物前走 AGPL 合规审查；触发 =
   对外分发二进制/镜像含该扩展。

## 索引健康运营（index_stats / index_health）

stannum 0.3.0 起提供 `stannum.index_stats(index regclass)` 健康聚合与
`stannum.index_health` 视图（`index` 首列 + 同构列，自动枚举库内全部
stannum AM 索引）。**三面分工**（互补，勿混用）：

| 面 | 工具 | 回答的问题 |
|---|---|---|
| 正确性 | `verify_index('ix_chunks_stannum', true)`（verify v2 第八项；cron = DP4 `v13-verify-chunks`） | 索引内容**对不对**（error/warning 计数） |
| 运营指标 | `index_stats` / `index_health`（本节） | 索引**健康不健康**（dead/段/页趋势，何时该 REINDEX） |
| 段级明细 | `segment_info`（M2 时序断言消费，见文末实测记录节） | 逐段 generation 时序 |

> **13 列（非旧记「12 列」）**：调查文档 §2.2.3
> （`v13-stannum-0.4-pgembed-adaptation-2026-09-25.md`）记 12 列系计数
> 偏差——0.3.0（demo 库 catalog 实测）与 0.4.0（gate 库实测）签名逐字
> 相同、均 13 列，以本节实测为准。

逐列含义：

| 列 | 含义 |
|---|---|
| `documents` | 索引内活文档数 |
| `dead_documents` | 段 dead-list 记账的死文档数（删除/更新残留；REINDEX 全量重建后归零） |
| `dead_ratio` | `dead_documents / documents`；REINDEX 运营线输入（见下） |
| `segments` | 总段数 = immutable + mutable |
| `immutable_segments` | 已折叠只读段数 |
| `mutable_segments` | 活动可写段数（v13 实测形态恒 1） |
| `next_generation` | 段 generation 分配计数（随 fold/段重建单调上升，与 M2 generation 观测同源） |
| `total_pages` | 索引 blob 总页数（容量趋势输入） |
| `dictionary_pages` | 与字典 extent 相交的页数，**全量口径**：统计所有 immutable 段字典 extent 覆盖页（无论本 backend 是否读过）；与 EXPLAIN `Dictionary Pages Read`（实际 pin 的页）定义不同、设计如此，仅全索引扫描下二者一致（0.4.0 扩展内列注释） |
| `total_length` | 文档总长度（引擎字节计量；均值换算用 `total_length / documents`） |
| `average_length` | **实测恒 0.0**（0.3.0/0.4.0 两库不同语料均然，保留列，勿依赖） |
| `analysis_matches` | jieba 词典分析命中位；仅 jieba tokenizer 索引且带分析 stamp 时非 NULL——v13 现役 unicode 索引恒 NULL（M2 jieba 评估落地后才有观测面） |
| `analysis_detail` | 同上条件的分析详情（jieba 版本/词典指纹/漂移）；本函数恒不 WARNING、不读 strict_analysis |

### 示例（2026-09-25 实测于 `agent_v13_characterize`，stannum 0.4.0；数值为 fixture 示例形态，库重建后以新读数为准）

示例保持 **owner 视角**。全库视图谁来跑、三角色为何失败，见下文「index_health 执行者」
（R14/R15）。下列 `documents` / `total_pages` 是当时 fixture 读数，不是运营基线；本节不另写会过期的数字。

单索引全景（13 列建议 `\x` 展开）：

```sql
\x on
SELECT * FROM stannum.index_stats('ix_chunks_stannum'::regclass);
```

```text
-[ RECORD 1 ]---+-------------------
 documents          | 128
 dead_documents     | 0
 dead_ratio         | 0
 segments           | 2
 immutable_segments | 1
 mutable_segments   | 1
 next_generation    | 2
 total_pages        | 13
 dictionary_pages   | 1
 total_length       | 2701
 average_length     | 0
 analysis_matches   |
 analysis_detail    |
```

（analysis 两列为空 = NULL：unicode 索引无分析 stamp，属正常态而非缺数据。）

全库横向直接 `SELECT * FROM stannum.index_health;`（多 `index` 首列，自动
枚举全部 stannum 索引——characterize 库即 `ix_v13_canary` +
`ix_chunks_stannum`）。巡检常用投影：

```sql
SELECT index, documents, dead_documents, dead_ratio,
       segments, immutable_segments, mutable_segments, next_generation
FROM stannum.index_health
ORDER BY dead_ratio DESC;
```

```text
      index       | documents | dead_documents | dead_ratio | segments | immutable_segments | mutable_segments | next_generation
------------------+-----------+----------------+------------+----------+--------------------+------------------+-----------------
 ix_v13_canary    |      1004 |              0 |          0 |        2 |                  1 |                1 |               2
 ix_chunks_stannum|       128 |              0 |          0 |        2 |                  1 |                1 |               2
```

### dead_ratio → REINDEX 运营建议线

| 带 | 判据 | 动作 |
|---|---|---|
| 绿 | `dead_ratio < 0.10` | 例行巡检（v13 gate 生态正常态实测 = 0） |
| 黄 | `0.10 ≤ dead_ratio < 0.30` | 记趋势；同看 `segments`/`total_pages` 是否同步膨胀，排查大批 supersede/删除写入 |
| 红 | `dead_ratio ≥ 0.30`，或 `dead_documents` 绝对值持续上涨 | 计划内 REINDEX → 走 runbook 5 演练（REINDEX 后复跑 K2/N1，基础行不动） |

红线 0.30 为 v13 运营约定（借 PG b-tree 死元组 ~30% 经验线；stannum 未内置
阈值）。**dead_ratio 高不是正确性事件**——正确性仍由 `verify_index` 守
（runbook 1 / verify v2 第八项）；REINDEX 是空间/性能回收动作（与 runbook 1
「索引丢失是性能事件非正确性事件」同一条判据轴）。

### 权限面（部署注意）

- `index_stats` 走 `require_index_select`：owner 或**表级 SELECT**（RLS 不认）。
- `index_health` 带 `security_invoker=true`：以**调用方**身份执行——调用方
  须对库内**每一个** stannum 索引满足上述权限，一个不可读即整体报错
  （all-or-nothing fail-closed，防 superuser owner 视图绕权）。
- 全库视图的推荐执行者、与单索引 `index_stats` 的分界，见下节。不要把上面两条读成
  「只要对某一张表有 SELECT 就能跑全库视图」。

### index_health 执行者

推荐执行者是**数据库 owner**（全库视图）。也可以由诊断角色执行，但该角色必须对
**所有** stannum 底表持有不受 RLS 限制的表级 SELECT。列授权不够；表启用 RLS 时诊断拒绝
（引擎报 `index diagnostics require ownership or SELECT without row security`），
不能靠行级策略放行。

视图**不是**硬编码 owner-only。`security_invoker=true`，按调用方身份逐索引调
`index_stats`：一个底表不可读，整条查询失败。三角色（`v13_recall` / `v13_resolve` /
`v13_route`）失败，是因为没有 canary 表 `v13_canary_docs` 的 SELECT，不是因为视图只允许
owner。指向 `v13/mgraph/test_stannum_usage.py` 的 **R14** / **R15**：R14 是
`v13_recall` 查 `stannum.index_health` 得到 permission denied；R15 是 owner 看到全部索引行。
canary 表对三角色无 SELECT 由 characterize 的 R3 钉死（`test_characterize.py`）；R14 只
实证 recall，另外两角色同样过不了 canary 那一行。上文示例保持 owner 视角；本节不写会
过期的 `documents` / `total_pages` 数字。

不要和单索引 `index_stats` 混为一谈。角色对该表有表级 SELECT 时，
`index_stats('ix_chunks_stannum')` 仍可能成功（R12：`v13_recall` 可读 chunks 上的单索引
统计）。同一角色查 canary 索引则失败（R13）。单索引成功不等于全库视图可跑。

## autovacuum（**生产化参考**，夹具库不执行）

标题即边界：本节只是**生产化参考**。v13 夹具库不执行这些 `ALTER TABLE`，
也不 `SET stannum.*`。F13（`v13/mgraph/test_stannum_usage.py`）继续锁 6 个 GUC 默认值
（`write_buffer_docs` / `write_buffer_bytes` / `max_merge_docs` /
`build_segment_docs` / `max_segments` / `merge_tier_factor`）。不要把下面的表级参数写进
夹具 DDL，也不要在会话里改这 6 个 GUC。

组合照抄 stannum pin `ad4d3b7` 的
`docs/architecture/segmented-storage.md:211-219`（本仓库没有该文件；同 pin 的
`docs/compatibility.md` 不含这组参数）。插入为主或混合负载上，可预测维护节奏用
`vacuum_index_cleanup = auto` 加上插入阈值（并把普通 vacuum 阈值一并钉死）。示例表名
`documents` 是上游写法，不是 v13 关系：

```sql
ALTER TABLE documents SET (
  vacuum_index_cleanup = auto,
  autovacuum_vacuum_insert_threshold = 1000,
  autovacuum_vacuum_insert_scale_factor = 0,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_vacuum_scale_factor = 0
);
```

PG 17/18 在 `vacuum_index_cleanup = auto` 跳过 bulk deletion 时仍会调用
`amvacuumcleanup`，插入触发的 autovacuum 因此能排空 deferred merge，不必等表有更新。
阈值按负载调整；服务器须保持 `autovacuum` 与 `track_counts` 开启。这是上游对生产表的
建议，不是本仓库夹具的执行步骤。

## tokenizer canary

专用表 `v13_canary_docs` + `WITH (long_tokens='split', max_token_bytes=64)`。
64B 精确块：bound 命中 / 默认回退漏召。**绝不与生产索引同列共存**。

## tinql 调试入口（tokenize / ql_parse / maybe_quote）

`stannum.tokenize` / `stannum.ql_parse` / `stannum.maybe_quote` 是排查 tinql 的正规
入口。三者在 `ZERO_FUNCS`（`v13/mgraph/test_stannum_usage.py`）；F14 只锁生产路径
零调用，**不做**这三个函数的输出 gate。切分或查询重写对不上索引时直接调它们，不要
从召回结果反推 tokenizer。

- `tokenize`：文本切成哪些 term。
- `ql_parse`：查询串如何解析、短语如何重写。tinql 对不上索引时先看这里。
- `maybe_quote`：一段文本是否需要加引号。生产建查询走 `v13_build_tinql` 的全段引号，
  不调用本函数；调试仍用它，不要另写引号规则。

诊断**非默认**索引时，必须传入与目标索引一致的 tokenizer 与 options
（`tokenizer` / `long_tokens` / `max_token_bytes` 等）。函数默认是 `tokenizer='unicode'`、
`max_token_bytes=256`。**不要把默认 unicode 输出当成 jieba 索引行为。** 生产索引今天是
默认 unicode；canary（`long_tokens='split'`，`max_token_bytes=64`）已经和函数默认不一致
——查哪张索引，就传哪张索引的 reloption。

## 同列双索引禁令

chunks 表恰一个 text-search 索引（生产默认配置）。两索引并存时 planner
恰绑其一（绑错即错结果）。bigram 未来走**独立列**。

## verify v2

第八项 `stannum_verify_index`：`verify_index('ix_chunks_stannum', true)` 的
error/warning 计数。cron job 零新增（DP4 `v13-verify-chunks` 调本函数自动升 v2）。
verify 体用 `SET enable_seqscan` 不用 `set_config`（避开 G-ctx1-5(b) 全树扫描）。

## >1024 展开

编译器 64 段上限挡用户面；引擎面 1030 词项 AND 直测保守回查（0.1.0 成功返回；
0.4.0 亦绿，2026-09-25 实测 `[info] O2 1030-term hits=[500001] dt=0.063s`）。

## 尺寸刻画面

6 档 × 20 文档（查询词埋中段；avg_rank = 目标词在各结果 chunk 内的
起始字节均值，本机 Q1）：

| size | hits | bm25_mean | avg_rank |
|---|---|---|---|
| 512B | 20 | 0.3965 | 252.5 |
| 1K | 20 | 0.8418 | 509.0 |
| 2K | 20 | 0.9987 | 1021.0 |
| 4K | 20 | 1.0363 | 2045.0 |
| 8K | 20 | 1.0241 | 4093.0 |
| 16K | 20 | 0.9937 | 8188.5 |

2K 起均值进入平台（**无 [0,1] 上界承诺**，见台账 ③）。3072 先验落在平台上，
本轮不翻 `chunks_ingest.target_bytes`。数据支持 ≠ 3072 时：新版本行 +
`v13_rebuild_chunks()`，**不自动翻策略**。

## 台账

- **① extract 参数名**：OR REPLACE 不能改输入参数名（PG：`p_terms`）。v2 体仍用
  `p_terms jsonb`，载荷约定改为 `{"tinql":…}`。签名 `(text,jsonb)` 不变。
- **② verify SET 非 set_config**：逐字复制 DP4 v1 的 `SET enable_seqscan` 路径，
  避开 G-ctx1-5(b) 对 `set_config` 的全树扫描。
- **③ full_score 值域**：**只保证 finite numeric + 排序并列 content_hash 终裁**，
  无任何语言的全局 [0,1] 承诺（L4 P2-10 收口）。英文 fixture 亦已 >1
  （Q 表 4K 档 1.0363）；CJK 短语实测 3.37。gate P2 的 [0,1] 断言仅限
  quasar 小文档 fixture，不外推。
- **④ L4 §5 尾债收口**（2026-09-22，
  `docs/reviews/v13-dp5-impl-l4-review-2026-09-22.md`，仅测试面 SQL 零改动）：
  M2 删 `check(...,True)` 恒真枝，改强制观测（segment_info 必在、mutable 段在场、
  generation 随插入递增、fold 批后 immutable+mutable 共存、verify 前后绿）；
  M3 改 fold 后 count==插入数（本机 1003/1003）；O2 改已知命中文档+命中集
  对照直查（1030 词项 AND 命中恰 {500001}，零命中即红）；Q1 查询词埋中段+
  每档断言 hits==20+avg_rank 改目标词结果内字节位次（禁 1..n 自平均）；
  K4 补执行面错咬（EXPLAIN 识别所绑索引后执行 64B 查询：绑 default ⇒ 漏召
  doc 1 / 绑 split ⇒ 命中 doc 1；测后 DROP 复原）。

## 0.1.0 实测记录（历史：DP5 时代实测；现环境版本见顶部活记载行）

- Custom Scan / `Stannum Text Search Scan`（K1 钉死，升级若改节点形态随 README 重钉，不做 OR 宽化）
- 降级面：无索引回落默认 comparator；同列双索引错绑（K4 实测 planner 绑 split 索引，
  命中 doc 1；绑 default 时漏召——两分支均断言）
- segment_info 段时序（M2 实测）：首条 insert 即开 mutable 段；mutable 攒 ~512 docs
  折叠成新 immutable 段（种子 immutable 原地保留）；generation=段内变更计数，随每条
  insert +1（3 种子 gen1 → +500 后 mutable gen500 → fold 批后
  immutable(512,gen2)+mutable(488,gen1001)）
- K5 三禁路径 0.1.0 命中保持绑定（升级复测项）
- Katakana 连跑成单 token；查询侧 CJK 语段一律短语引用

## 回退

删 `v13/characterize/` + `v13/load.py` 第 9 位。第 8 位 T0 tsvector 仍可全绿。
