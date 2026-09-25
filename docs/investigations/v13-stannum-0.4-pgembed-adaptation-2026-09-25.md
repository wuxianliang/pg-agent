# v13 stannum 0.4.0 + pgembed 适配调查（2026-09-25）

**性质**:只分析不开发。本报告为唯一新增文件;零 v13 代码/SQL/gate 改动、零 commit。
**触发**:pgembed 本地 fork 已把捆绑 stannum pin 从 0.3.0(7f58bbe) bump 到 0.4.0(ad4d3b7,LSG4 多字段 BM25F wave),v13 面临「要不要跟、跟到哪一层」的裁决。
**输入**:两份只读事实底稿(`prompt-exports/stannum-pgembed-0.4-findings.md` 外部仓库变化事实、`prompt-exports/v13-touchpoints-inventory.md` v13 触点盘点;均为临时件,本报告自包含不依赖其存续)+ 本报告作者对 v13 主 checkout 的逐文件核实(证据清单见附 A)。外部仓库事实以底稿为准,未独立复跑外部 git;底稿中断言存疑处一律标「待实证」(附 B)。
**先行核实补充**(用户侧,2026-09-25):`score_bound`/`score_bound_indexed` 的 10 参签名在 0.1.0 与 0.4.0 逐字相同(含 REVOKE PUBLIC 模式),v13 各 setup_db.py 的 GRANTS 块升级后仍有效。

---

## 0. 一页摘要

1. **升级跨度实为 0.3.0 → 0.4.0,不是 0.1.0 → 0.4.0**。v13 文档全套钉 0.1.0(DP5 计划、characterize 注记、rag-subagent 台账),但实际环境已跑 0.3.0(`v13/mgraph_assembly/README.md:157` 自述)。0.3.0→0.4.0 对既有单列索引零破坏、SQL 面只增不改(仅加两个 highlight 尾参重载,无默认值),**L0 被动兼容的成本 ≈ 一次全量 gate 重跑 + 版本记载消歧**。
2. **升级动作本身很薄**:pgembed 是 editable 本地 fork(`pyproject.toml:19`),STANNUM_COMMIT 已在 fork 侧 bump;v13 侧只需重建 pgembed bundle(stannum 重编进安装前缀),各 setup_db.py DROP/CREATE 库时 `CREATE EXTENSION`(全链唯一装载点 `v13/characterize/v13_characterize.sql:12`)自动落 default_version 0.4.0。GRANTS/probe 面已核实无需改动。
3. **对底稿「search() 可简化 recall/economy/mgraph 链路」的判断,本报告修正为「不能」**(§2.2):`stannum.search()`/`search_count()` 是无过滤整表 top-k/count 模型,而 v13 全部三个引擎调用点都带额外关系谓词(v13_sources join+superseded 过滤 / session_id / session_id+origin),先 top-k 后过滤不等价于过滤后 top-k。L1 的真实落点是**可观测性三件套**(index_stats/index_health/search_count 探针),不是链路改写。
4. **L2 jieba 是 CJK 线的正解方向但爆炸半径最大**:表级全有全无切换(R1/K4/M1 钉每表恰一 stannum 索引,unicode/jieba 两索引不能并存)、mgraph 3-gram 锚机制须同步改词级、L3/B3/G6/E2 等 gate 期望值重校。jieba 修的是**检索召回质量**(OQ9 遗留、Katakana 边界、n-gram 锚粗糙),**不修 OQ13**(OQ13 是路由权重裁决,正交平面);建议排在 OQ13/OQ14 裁决之后串行,避免两线互踩 mgraph gate。
5. **L3 多列 BM25F 在 v13 现状没有直接落点**(§2.4,本报告新核实):chunks/transcript_chunks/memory_nodes 全是天然单文本列,decisions.question 更被 DDL 钉为 ASCII 英文判断题(`v13/schema/v13_core.sql:398-399`)。多列 BM25F 是**未来 schema 演化的能力储备**(如 chunks 加 title、memory_nodes 加 summary 时),不是即期改造。
6. **最大单点风险 = O2 段错误在 0.4.0 是否复现**。0.3.0 上 1030 词项 `==>` 触发 signal 11(`v13/mgraph_assembly/README.md:156-159` 既有环境阻塞),0.4.0 wave 无专门 segv 修复(仅 fuzz 找到的 field-aware buffer gap)。**建议作为 L0 的第一个探针**:升级后先跑 O2 单测,红则升级本身仍可推进(O2 是已知环境阻塞,gate 有先例处理),但须在新台账记录 0.4.0 下的新事实。

---

## 1. 基线与升级跨度(A)

### 1.1 三方版本现状与时间线

| 组件 | 现状 | 依据 |
|---|---|---|
| stannum(实际运行) | **0.3.0**「P0 agent-features」(search SRF+observability),pgembed 捆绑 pin 7f58bbe,2026-09-24 | `v13/mgraph_assembly/README.md:157`;底稿 §0 |
| stannum(fork 已 bump) | **0.4.0**「LSG4」(多列 BM25F+TINQL 字段组+field-aware highlight),pin ad4d3b7,2026-09-25 | 底稿 §0;`pyproject.toml:19` editable 指向 `../pgembed` |
| pgembed 根包 | 0.3.0rc2 未变(PG18 pre-release);变化全在捆绑内容(新增 pg_partman/pgTAP/pg_jsonschema/pg_typesafe/stannum)与新增子包 `pgembed_stannum` | 底稿 §4;`pyproject.toml:8` `pgembed>=0.3.0rc1` + `[tool.uv] prerelease="allow"` |
| v13 依赖形态 | **纯 SQL,零 Python 引擎客户端**:全部经 psql+PL/pgSQL;pgembed Python 面只有 `v13/load.py:12`(POSTGRES_BIN_PATH)与 `server.py`(get_server/get_uri) | 底稿 §0/§3,已核实 `v13/load.py:1-55` |

版本时间线(底稿 §0):e163585(09-19,DP5 开发基线,≈0.1.0 时代)→ 7f58bbe(09-24,0.3.0,**当前环境**)→ ad4d3b7(09-25,0.4.0,**本次适配目标**)。

### 1.2 版本记载矛盾与消歧(升级前第一件事)

v13 自身的版本记载自相矛盾:

- 钉 0.1.0:`v13/characterize/v13_characterize.sql:7-8`(Engine facts 注记)、`v13/characterize/README.md:69-95`(0.1.0 实测记录节)、`docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md:7`(引擎实证注记)、`docs/designs/v13-rag-subagent.md:57`(台账行)。
- 自述 0.3.0:`v13/mgraph_assembly/README.md:157`。

判断:0.3.0 是事实(09-24 mgraph_assembly 交付时环境已换),0.1.0 是 DP5 时代(09-20/22)的历史记载未随环境更新。**消歧动作**:升级到 0.4.0 落地时,统一以 `pg_available_extensions` 的 default_version/installed_version 为准,把上述四处记载更新为 0.4.0 实测(README 的实测记录节按其自身体例「升级若改节点形态随 README 重钉」执行,`v13/characterize/README.md` K1 行先例)。这不是可选的文档洁癖——`v13/characterize/README.md:16` 的升级 runbook 明文要求「扩展版本变更 → 重跑 K3+K5」,版本记载与实测对齐是 runbook 的前置。

### 1.3 升级路径(机械步骤)

```
重建 pgembed bundle(fork 侧 STANNUM_COMMIT 已是 ad4d3b7)
  → stannum 0.4.0 编进 pgembed 安装前缀
  → 各 stage setup_db.py DROP/CREATE 库(既有机制,零改动)
  → v13_characterize.sql:12 CREATE EXTENSION IF NOT EXISTS stannum
    自动落 default_version 0.4.0
  → GRANTS(10 参签名逐字相同,已核实)/probe_extension(pg_available_extensions 查询,版本无关)零改动
  → 全量 gate 重跑(16 个 test_*.py)
```

已确认不需要改的:`CREATE EXTENSION` 无需 VERSION 子句(目标即 default_version);既有库原地升级才需要 `ALTER EXTENSION stannum UPDATE TO '0.4.0'`,而 v13 是 DROP/CREATE 重建模型,不走这条路。旧单列索引在 0.4.0 下无需任何动作(LSG3 原样可读,底稿 §2)。

### 1.4 澄清:v1 五补丁与本次升级无关

v1 的 5 个 SQL bug 补丁(根 `v1/setup_db.py:29-134` PATCHES dict)作用于 v1 时代 SQL 文件,与 stannum/pgembed 均无关;v13 的 `load.py` 不走 PATCHES 机制,升级后**无需摘除也无需核对**。唯一的远期复核点是 PG 主版本变化时其中 `\M` 与 `::regprocedure` 两条 PG 语义补丁(见 §4-R4)。

---

## 2. 分层适配方案(B)

### 2.0 分层总览

| 层 | 内容 | 改 v13 SQL | 改 gate | 依赖裁决 | 建议时点 |
|---|---|---|---|---|---|
| L0 | 被动兼容:升级+复核,零改造 | 无 | 无(重跑而已) | 无 | 立即(M0) |
| L1 | 采用 0.3.0 已有能力:observability 三件套(+search 探针性评估) | 小(可选) | 小 | 无 | M0 后随(M1) |
| L2 | jieba 中文分词 | 大 | 大 | 建议排在 OQ13/OQ14 裁决后 | M2 探针→M4 落地 |
| L3 | 多列 BM25F+TINQL 字段组+field-aware highlight | 无现成落点(schema 先行才有) | 随 schema | 无 | 按需(M5+) |
| L4 | RRF 混合检索(vchord/pgvector) | 新增面 | 新增 gate | T1 触发线(rag-subagent) | 展望(M6) |

### 2.1 L0 被动兼容:只升级不改造

**改什么**:v13 零代码改动。动作=重建 bundle→重建库→重跑 gate→版本记载消歧(§1.2)。

**为什么**:0.3.0→0.4.0 的 SQL 面只增不改(两个 highlight 尾参重载无默认值,旧 1-4 参调用不受影响);单列索引 LSG3 原样可读;`==>`/full_score/verify_index/score_bound 全部签名未动。

**必须复核的清单**(全部是「跑」不是「改」):

1. **7 项行为契约**(DP5 计划 `docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md:1284` 行 12 清单,0.1.0 时代探针库实测过):bind_query 参数化绑定 / Custom Scan JSON 键名 / highlight 多命中与口音折叠 / verify_index severity 词表 / count 走索引 / fold 后精确 / reloptions 词表。落在 gate 上即 K1/K5/N1-N2/M2/K2 的重跑本体。
2. **K3+K5**:`v13/characterize/README.md:16` 明文的升级复测项(无索引回落默认 comparator / 三禁路径与 EXECUTE 一致性)。README 自述「实测等价 ≠ 禁令撤销」,K5 断言不动,只复跑。
3. **O2 段错误重测**(本层第一个探针,详见 §4-R1):0.3.0 signal 11,0.4.0 wave 无专门修复。
4. **GRANTS/probe 面**:已核实(10 参签名逐字相同),升级后跑通 setup 即证——这是升级的第一道闸,先于任何 gate(`probe_extension` 缺名即 exit 1,GRANTS 签名错即 42501)。
5. **REINDEX 演练**(README runbook 5):REINDEX 后 K2/N1 复跑——0.4.0 的 REINDEX 写段格式对单列索引仍是 LSG3,预期不变,跑一遍即证。

**不做会怎样**:环境已经在漂(fork pin 已 bump,下次任何人重建 bundle 就会落 0.4.0)。不主动做 L0,第一个重建环境的人会在毫无准备的情况下发现全部 gate 处于未验证状态,且 O2 的新事实(复现/消失)无人记录。

### 2.2 L1 采用 0.3.0 已有能力(search / search_count / index_stats / index_health)

#### 2.2.1 `stannum.search()` 对 v13 现有链路:**不能等价替换**(对底稿 §5.2-1 的修正)

0.3.0 的 `stannum.search(index regclass, query text, limit, snippet, begin_tag, end_tag, k1, b)` 一站式 SRF 返回 `(ctid, score, snippet)`,表面上取代三段式(`==>` 扫描 + `full_score(ctid)` + `highlight`)。但逐点对 v13 的三个引擎调用点分析:

| 调用点 | 现有三段式 | search() 能否替换 | 障碍 |
|---|---|---|---|
| `v13_recall`(characterize.sql:95-112) | `==>` + full_score + extract_spans,**外加 `JOIN v13_sources src ON ... AND src.superseded_by IS NULL` 过滤** | **否** | search() 无过滤参数;先 top-k 后 join 过滤会因 superseded 行占坑而漏召回/不足 k |
| `v13_transcript_recall`(memory.sql:151-153 附近) | session_id 限定 + `==>` + full_score,**复合 plan = PK bitmap + score_bound_indexed**(gate K3 钉死,test_memory.py:510-518) | **否** | 同上;且 K3 断言 `"score_bound_indexed" in plan` 的 plan 形状会从 Bitmap Index Scan 变 Function Scan,gate 面也碎 |
| `v13_mgraph_candidates`(mgraph.sql:752-758) | `session_id AND origin='episodic' AND body ==>` + full_score | **否** | 同上;session 语料占比小,先整表 top-k 再过滤几乎必然空手 |

技术上 search() 返回 ctid,可 `FROM stannum.search(...) JOIN chunks USING ctid WHERE ...`,但那是「top-k 后过滤」语义,与 v13 的「过滤后 top-k」不等价(k 语义、召回完整性都变)。**结论:三段式不是历史包袱,是「带关系谓词的限定检索」的必要形态;search() 的无过滤 top-k 模型在 v13 现有链路没有等价落点。**

spans 载荷的次生障碍(即便未来某链路想用 search()):v13 的 spans 机制(`v13_extract_spans`,characterize.sql:29-83)是**载荷而非装饰**——哨兵字符对 chr(1)..chr(8) 挑选、`stannum.highlight` 4 参注入、`position()` 反推、`octet_length` 减标签字节得原始 body 字节区间,被 test_chunks.py 大量字节级断言钉死(:805-809,1297-1337,1347-1376)。search() 的 begin_tag/end_tag 自定义参数理论上可承载同一哨兵法,但有两个**待实证**前提:①snippet 是否窗口截断(截断则反推出的偏移相对窗口而非原 body,机制整体失效;底稿未记录 0.3.0 search() 的 snippet 窗口语义);②search() 的 score 排序 tie-break 是否稳定(v13 的排序契约是「并列 content_hash 终裁」,P1/B2 双跑字节等断言;search() 内部 limit 先截断则并列候选可能在外层重排前已被丢弃)。

#### 2.2.2 `search_count`:同理受限,探针面可用

`search_count(index, query)` 同为无过滤模型,不能替换 `v13_recall_count`(其 SQL 带 sources join+superseded 过滤,characterize.sql:117-131)。可用的位置是刻画/运维探针(无过滤整表计数),价值中等。

#### 2.2.3 真正的 L1 落点:index_stats / index_health(可观测性)

- `stannum.index_stats(index regclass)` 12 列健康聚合(documents/dead_ratio/segments/…/analysis_matches/analysis_detail)、`stannum.index_health` 视图(security_invoker=true)。
- v13 现有可观测面只有 `verify_index` severity 计数(characterize.sql:188-190,verify v2 第八项)和 M2 的 segment_info 时序断言。index_stats 提供的是**段级/死元组级运营指标**,正好补 README runbook 1「索引丢失是性能事件非正确性事件」缺的量化面:dead_ratio 飙升 → REINDEX 触发依据。
- 落点建议:`v13_verify_chunks` 的 detail 里追加 index_stats 摘要列,或 README 运营节新增健康查询示例。**注意 gate 面**:verify v2 的 checks 形状被 envelope/manifest 面 indirect 消费,若动 `v13_verify_chunks` 返回形状须走「版本 2→3」的形状演化先例,不动既有键(增量 JSON 键对 manifest 断言是包容性语义,DP5 计划 §5 行 6 先例);更保守的起步是只在 characterize README 记 runbook 查询、gate 加一条 index_stats 可调用断言(N 组外延),零 SQL 改动。

**不做会怎样**:无正确性影响,纯可观测性缺口(dead_ratio 无量化、段健康无运营视图)。verify_index 已覆盖正确性面。

### 2.3 L2 jieba 中文分词(CJK 主战场的正面解法)

#### 2.3.1 痛点对应关系(jieba 修什么、不修什么)

v13 的 CJK 现状是「默认 unicode tokenizer 逐字切分 Han + 三处自研补丁」:

| 现状痛点 | 位置 | jieba 是否正面解 |
|---|---|---|
| OQ9 遗留:tsvector 对 CJK 零召回(已由 stannum 默认 tokenizer 缓解为「逐字可召回」) | `v13/memory/v13_memory.sql:30-31` 注释 | 部分:词级召回质量优于逐字(短语/复合词的一次命中 vs 逐字 AND) |
| Katakana 连跑成单 token 的 0.1.0 物理边界 → `v13_build_tinql` 全语段引号包裹 workaround | `v13/recall/v13_recall.sql:89-93` | **待实证**(jieba 对 Katakana 连跑的切分行为无记录;若仍连跑,workaround 不能摘) |
| mgraph 锚 3-gram 字符切分(粗糙,anchor_max_terms=48 截断压力) | `v13/mgraph/v13_mgraph.sql:3206-3237` | 是:词级锚词项数大幅少于 3-gram |
| OQ10:entities_of `^[A-Z][a-z]+$` 对 CJK 段天然空集 | `v13/mgraph/v13_mgraph.sql:642-666` | **否**(正则面与 tokenizer 无关) |
| OQ13:CJK 查询路由短路 superset,升权不可达 | `v13/mgraph/v13_mgraph.sql:1475-1481` | **否**(路由权重裁决,与分词正交;见 §6) |
| OQ14:候选唤醒顺序 | 调查报告 §5 | 否 |

#### 2.3.2 爆炸半径(逐项)

1. **表级全有全无,不能增量**:每表恰一 stannum 索引是设计不变量(R1 断言「chunks exactly one stannum index」,test_characterize.py:822-824;M1/G6 同型),同列双索引是 planner 错绑陷阱(K4 实测,characterize README「同列双索引禁令」节)。因此 jieba 切换=对 chunks/transcript_chunks/decisions/memory_nodes **逐表整体切换并重建**,没有「先切一张表试试」的中间态(除 canary:v13_canary_docs 是独立表,天然是第一个试验田)。
2. **查询侧四时刻对称**:0.3.0 的 jieba 是索引/查询/打分/高亮四时刻对称(底稿 §1)。v13 查询构造器 `v13_build_tinql`(全语段引号短语)与 `v13_mgraph_anchor_tinql`(OR 闭集)的输出在 jieba 索引上的语义全部要重验:引号短语查询按 token 位置序列匹配,jieba 分词后 token 序列与逐字序列不同,L3(CJK 短语命中)/B3(CJK 全段命中==tsvector 命中数)/G6(CJK 节点 OR tinql 命中)的期望值全部重校。
3. **n-gram 锚与 jieba 是替代,不是并存**:`v13_mgraph_anchor_terms` 的 3-gram 项在 jieba 索引上大多不命中(索引词元是词不是字符 3-gram)。切 jieba 须同步把 anchor_terms 的 CJK 分支改为 jieba 词级(或 latin 整项 + CJK 整词),`anchor_ngram_n` 策略键语义重定义(可能是 `anchor_tokenizer: unicode|jieba` 新键)。anchor_guard 的字符白名单(五码点区间)不受影响(字符域与切分无关)。
4. **K3 无索引回落语义变**:无索引回落走默认 comparator,tokenizer 配置在索引 reloptions 上,回落 comparator 的 tokenizer 行为是否随索引配置走**待实证**(DP5 K3 的 64B miss 断言在 jieba 下的形态)。
5. **性能面**:jieba 词典每 backend 进程首次解析 ~100ms + 数 MB RSS(底稿 §1),连接池预热的 README runbook 2 要加一条词典预热;索引/查询的 CPU 面要重测(M1 fold 时序断言的数值带)。

#### 2.3.3 与 OQ13/OQ14 延后裁决的关系

- **正交性**:OQ13(建议裁 B:中文意图锚词表+混合语言优先级,`docs/investigations/v13-mgraph-v2-cjk-routing-investigation-2026-09-24.md:197-208`)修的是**路由平面的权重分配**;jieba 修的是**检索平面的召回质量**。OQ13 的裁 B 不依赖 jieba,jieba 不依赖 OQ13。
- **冲突面在 gate 与排期**:OQ13 落地要改写 E2 gate 夹具(test_mgraph.py:1558-1591 区域)与 route 函数;jieba 落地要重校 G6/E2/A2 的 CJK 期望值。两线并行会互踩同一批 gate 文件,**建议串行**:OQ13/OQ14 裁决与 mgraph v2 交付在前,jieba 切换在后(或同批显式协调)。另一个次序理由:OQ13 裁 B 的收益评估以「CJK 检索质量现状」为背景,jieba 落地会改变该背景,先裁后切可避免裁决依据漂移。
- **jieba 不解 OQ13 但解 OQ13 的一个前置焦虑**:CJK 查询的词法信号质量(意图锚词命中)在 jieba 词元化后更稳,裁 B 的词表面(routing_intent_causal/temporal)与 jieba 词元对齐度更高——这是「后切」的又一个理由。

#### 2.3.4 词典漂移治理(strict_analysis)

0.3.0 的治理机制:索引盖 jieba 版本戳;jieba-rs 版本漂移 → 每索引每语句一次 WARNING + REINDEX 建议;`stannum.strict_analysis=on` 把「已盖戳但漂移」升级为硬错误。v13 的库生命周期是 setup DROP/CREATE 重建模型,gate 环境漂移窗口≈零;**立法点在生产化/长生命周期库**(若 v13 未来有持久库):strict_analysis 建议进 runbook 而非进 SQL(GUC 属会话/系统面,v13 SQL 面零 stannum GUC 的现状维持)。

**不做会怎样**:CJK 召回维持逐字 AND 质量(短语级一次命中缺失、mgraph 锚 3-gram 截断压力),OQ13 裁 B 落地后中文意图锚的检索支承仍是逐字面。无正确性风险,纯质量缺口延续。

### 2.4 L3 多列 BM25F + TINQL 字段组 + field-aware highlight

**本报告新核实:v13 现有四张被索引表全部是天然单文本列,L3 无即期落点**:

| 表 | 文本列 | 依据 |
|---|---|---|
| chunks | 仅 body(source_hash/chunk_no/content_hash/chunk_offset 均非自由文本) | `v13/chunks/v13_chunks.sql:141-147` |
| transcript_chunks | 仅 body | `v13/memory/v13_memory.sql:18-24` |
| memory_nodes | 仅 body | `v13/mgraph/v13_mgraph.sql:25-31` |
| decisions | 仅 question,且被 DDL 钉 `^[\x20-\x7E]+$`(ASCII 英文判断题,v12 调研结论的 DDL 执法) | `v13/schema/v13_core.sql:393-399`;索引 memory.sql:161 |

**价值面(条件触发)**:

- 多列 BM25F(`USING stannum (col1,col2,...) WITH (field_weights='title:3.0,body:1.0')`)在 schema 演化时才可用:例如 chunks 若未来加 title/metadata 摘要列(v13.1 产物回流可能带,§6)、memory_nodes 若加 consolidation summary 列。届时 field_weights 是纯 reloption,不破「每表恰一索引」不变量(多列索引仍是 1 个 pg_index 行,R1 计数不破)。
- TINQL 字段组(`title:(beer OR ale)`、`==>` 右子句限定到左操作数列)对 filter/resolve 的价值:**v13_filter 是零引擎依赖设计**(H6 钉 file10 `stannum.`==0,test_filter.py:2546-2547;不变量 7 同型钉 file8)。字段限定查询若引入,必须落在既有收敛点(file9 characterize / file15 mgraph)的函数体内,filter/resolve 继续只消费 `v13_recall_candidates` 信封——即 L3 的查询语言面不改变 v13 的「引擎调用收敛」架构,只是收敛点内部的表达力增强(例如 mgraph 锚未来可用 `body:("词" OR ...)` 显式钉列,在多列索引上避免跨字段误命中)。
- field-aware highlight 5 参重载(0.4.0 新增,尾部无默认值):v13 现用 4 参调用**完全不受影响**(characterize.sql:56);多列索引落地后,extract_spans 的哨兵机制理论上可用第 5 参指定字段,但 snippet 窗口语义同 §2.2.1 待实证。

**约束与代价**:field_weights 单列索引上设置即报错;ALTER SET 后 fail-closed 直到 REINDEX;列改名需 REINDEX;LSG4 段格式无法在 pre-0.4.0 二进制打开(§4-R2)。v13 的 DROP/CREATE 重建模型下这些代价都轻(每次重建),真正的约束是「没有第二文本列就没有 BM25F」。

**不做会怎样**:零损失(现状无需求)。风险只是「schema 演化时不知道有这个能力而设计出两张表两个索引的反模式」——本节即记录。

### 2.5 L4 RRF 混合检索(可选展望)

pgembed 新增子包 `pgembed_stannum` 提供 `.hybrid_search(query, vector_column=, query_vector=, limit, candidate_limit, rrf_k=60, weights=(0.4,0.6), seqscan_row_threshold=50_000)`:RRF 在 SQL 内融合——BM25 臂走 `stannum.search`,向量臂走 `<=>`;≥50k 行且无向量索引则 fail-closed 拒绝向量臂 seqscan。**v13 不需要这个 Python 包**(面向 pgembed `get_server()` 嵌入式模型,而 v13 直连既有 PG18.4 实例;底稿 §4 已注);真正可移植的是其 **RRF 融合 SQL 模板**(`_hybrid.py`)。

定位对照 `docs/designs/v13-rag-subagent.md`:T0(stannum BM25)已交付;T1 混合(「vectorchord 1.1.1,T1 混合台账触发线;需 shared_preload_libraries='vchord'」,:58)是台账触发线未开工。若 T1 触发:

- 向量基建已在捆绑内(pgvector 0.8.2 + VectorChord 1.1.1,vchord **requires_preload**——pg-agent 的 server 由 `server.py` get_server 管理,preload 要落 postgresql.conf 配置面,属运维动作+环境重启,须进 runbook);
- RRF 模板落地时注意 §2.2.1 的同款问题:模板 BM25 臂用无过滤 `stannum.search()`,v13 的限定检索场景(sources/session 过滤)须改写模板臂内加 WHERE——模板是起点不是成品;
- psql_bm25s 0.4.14 备胎条款(rag-subagent.md:64)不受影响。

**不做会怎样**:T1 线维持台账态,零影响。

---

## 3. gate 影响矩阵(C)

底稿 §6 的风险排序为骨架(已逐条核实其 file:line,见附 A),叠加各层适配的 gate 改动:

### 3.1 底稿 §6 风险排序(复核后照录)

| 风险级 | gate | 钉死的 stannum 面 |
|---|---|---|
| 🔴 极高 | test_characterize.py(K–R 八组) | K1 Custom Scan 节点形态(:384-390)/K3 无索引回落 miss(:409-420)/K4 同列双索引错绑(:432-453)/K5 三禁路径(:454-500)/L3 CJK 短语+Katakana miss(:499-504)/M2 segment_info 列名(:509-521)/N1-N2 verify severity 词表(:564-618)/O2 1030 词项(**0.3.0 已知段错误**,:672-690)/P1-P2 排序+值域(:696-702)/P3 highlight 哨兵 spans(:712-723)/Q1 六档尺寸(:807-810)/R1-R2 索引唯一+**逐文件 `==>`/`stannum.` 源码计数**(:822-860)/E-DP5-2 SET ROLE(:875-880) |
| 🔴 极高 | test_memory.py | K3 `"score_bound_indexed" in plan`+Bitmap Index Scan(:504-518)/K4 file11 计数 1/3(:530-532)/M1 决策索引恰一(:640-641) |
| 🔴 极高 | test_mgraph.py | G6 OR 形 tinql 驱动 stannum 谓词+CJK 命中(:2749-2756)/索引清单(:315)/F7 候选不相交(:2297-2303) |
| 🟠 高 | test_recall.py | B1 spans 字节回验(:570-578)/B2 排序并列(:589-596)/B3 CJK 命中数(:603-615) |
| 🟠 高 | test_chunks.py | spans→assemble 字节级断言(:805-809,1297-1337,1347-1376) |
| 🟠 高 | test_filter.py / test_economy.py / test_periphery.py / test_mgraph_assembly.py / test_manifest.py | 间接受力(H6 file10 `stannum.`==0 :2546-2547;候选四键形状 manifest:688-691——**bm25 值不入 candidate_set_hash,分值漂移不打红 manifest**) |
| 🟡 中 | 全部 setup_db.py | probe_extension(7 处)+GRANTS(8 处)10 参签名——已核实 0.4.0 逐字相同,此闸预期绿 |

### 3.2 各层叠加的 gate 改动

| 层 | gate 改动 | 性质 |
|---|---|---|
| L0 | **零改动**,16 gate 全量重跑 | 复核 |
| L1(observability) | 起步零改动(README runbook 查询);若 gate 化则 N 组外延加 index_stats/index_health 可调用断言 | 增量断言 |
| L1(若强推 search()) | R2 file9 计数 2/3 重钉、memory K3 plan 断言重写、chunks spans 断言整体重写——**不建议**(§2.2.1) | 主动变更不变量 |
| L2(jieba) | L3/B3/G6/E2/A2 期望值重校;anchor_terms 机制改写连带 mgraph 锚族断言;K3 回落形态复验;M1 fold 数值带重测;canary WITH 面扩 tokenizer 维度 | 大面积期望值重校 |
| L3(多列) | R1/R2/M1 索引清单随 schema 演化重钉;新 gate 断言 field_weights 生效与单列报错 | 随 schema |
| L4(RRF) | 新增 T1 gate,不动现有 | 新增 |

### 3.3 设计不变量声明(重要)

**R2/K4/H6 的逐文件 `==>`/`stannum.` 源码计数钉死是设计不变量,不是可以绕过的实现细节**:file9=2/3、file11=1/3、file1-8/10=0 是「引擎调用收敛点唯一」架构(不变量 7 同族)的执法面。因此任何采用 search() / 改动引擎调用形态的方案(如 L1 强推、L4 模板)都是**主动变更不变量,须显式修 gate + 改记载**,按既有先例(K1「随 README 重钉,不做 OR 宽化」,characterize README 0.1.0 实测节)的纪律执行——修改 gate 断言值必须伴随架构记载更新,禁止为了过 gate 放宽计数或加 OR 分支。

---

## 4. 关键风险与未决问题(D)

| # | 风险/未决 | 判断 | 处置 |
|---|---|---|---|
| R1 | **O2 段错误 0.4.0 是否复现**:0.3.0 上 1030 词项 `==>` signal 11(后端崩溃),`v13/mgraph_assembly/README.md:156-159` 记为既有环境阻塞;0.4.0 wave 9 提交无专门 segv 修复(仅 fuzz 找到的 field-aware buffer gap) | 底稿 §3 明示无修复;**待实证** | **L0 第一个探针**:升级后单跑 O2 断言(其余 gate 前置)。复现→升级照常推进(O2 已有「已知环境阻塞」台账先例),新台账记 0.4.0 事实;消失→摘 W4 台账 |
| R2 | **LSG4 无盘上降级**:多列索引段格式 LSG4 无法在 pre-0.4.0 二进制打开,无降级路径 | 单列索引永远写 LSG3,v13 现状零暴露;L3 落地后降级=回退二进制前必须 DROP 多列索引或整库重建 | L3 runbook 必载;v13 DROP/CREATE 模型下降级即重建,风险受控 |
| R3 | **jieba 词典漂移**:jieba-rs 版本变化 → 已建索引词元域漂移 | 0.3.0 已有治理(版本戳+WARNING+strict_analysis 硬错误) | gate 环境零风险(库重建模型);生产化时 strict_analysis 进 runbook(§2.3.4) |
| R4 | **PG 主版本升级级联**:pgembed 捆绑件全部 BUILT_FOR_POSTGRES_MAJOR=18;PG 若升 19,pgrx 全家重编+捆绑面重验 | 底稿 §4 | 远期;届时 v1 五补丁仅 `\M` 与 `::regprocedure` 两条需复核(v1/setup_db.py PATCHES,PG 语义层) |
| R5 | **底稿存疑断言**(附 B):search() snippet 窗口语义、tie-break 稳定性、jieba 对 Katakana 行为、K3 回落与 tokenizer 的关系 | 全部标「待实证」 | 各自层落地前探针;jieba 先在 canary 表探针(§2.3.2-1) |
| R6 | **版本记载漂移重演**:0.1.0→0.3.0 的环境漂移无记载同步,这次 0.4.0 若不消歧会三度重演 | 已判 | M0 收尾工件含四处记载更新(§1.2);建议 characterize README 增「当前 installed_version」一行作活记载 |

---

## 5. 建议排期(里程碑序列;每步全绿才进下一步,沿 AGENTS.md 惯例)

- **M0 = L0 被动兼容(立即,单里程碑提交)**
  1. 重建 pgembed bundle → 抽查 `SELECT default_version FROM pg_available_extensions WHERE name='stannum'` = 0.4.0;
  2. **O2 探针先行**(§4-R1);
  3. 16 gate 全量重跑(characterize 八组全跑,防回归);
  4. 版本记载消歧四处 + characterize README 活记载行(§1.2、§4-R6);
  5. 收尾:本调查所在目录无需矩阵;README 更新即工件。
  *产出:升级落地 + 全绿基线 + O2 新事实。*
- **M1 = L1 可观测性(可与 M0 同批或紧随;独立小里程碑)**
  index_stats/index_health 进 characterize README runbook(+可选 N 组外延断言)。零 SQL 改动起步。
  *可与 M0 并行开发、但提交排在 M0 全绿之后。*
- **M2 = jieba 评估探针(独立里程碑,不动 v13 主链)**
  canary 表(v13_canary_docs 独立表,或临时探针库——DP5 探针库 `v13_dp5_probe` 用毕即删先例)上:jieba tokenizer 建索引、CJK/Katakana/混语查询行为实测、四时刻对称验证、性能面(词典解析/查询 CPU)。**产出是裁决材料,不是代码**。
  *依赖:无;与 mgraph v2 计划(OQ13/OQ14 线)可并行——探针不碰 gate。*
- **M3 = OQ13/OQ14 裁决与 mgraph v2(mgraph 线既有序,非本报告新增)**
  OQ13 建议裁 B(意图锚词表+混合语言优先级);OQ14 候选唤醒先行或同批。
- **M4 = jieba 落地(依赖:M2 探针结论 + M3 交付后串行,§2.3.3)**
  逐表切换(chunks/transcript/memory_nodes;decisions.question 是 ASCII 英文,**不切**)、anchor_terms 词级化、gate 期望值重校(L3/B3/G6/E2/A2/K3/M1)。一个大里程碑或按表拆分(先 memory_nodes——mgraph 锚主战场,后 chunks),每步全绿。
  *阻塞条件:OQ13/OQ14 未裁或 mgraph v2 未交付,则 M4 不动。*
- **M5 = L3 多列 BM25F(schema 演化触发,按需)**
  触发=某表获得第二个自由文本列(v13.1 产物回流若带 title/summary)。届时 field_weights+字段组 gate 一体化交付。
- **M6 = L4 RRF 混合检索(T1 触发线,展望)**
  触发=rag-subagent T1 台账行启动;vchord preload 运维面+模板臂内过滤改写(§2.5)。

依赖图:M0 → M1(可并行开发);M2 独立;M3(既有线)→ M4;M5/M6 事件触发。

---

## 6. 与既有计划的关系

- **DP9 mgraph v2 / OQ13 / OQ14**(`docs/investigations/v13-mgraph-v2-cjk-routing-investigation-2026-09-24.md`):OQ13 建议裁 B(中文意图锚词表进策略行+混合语言优先级,:197-208),与 OQ14(候选唤醒先行/同批,:209-213)捆绑。**本报告的 L2 与其正交但排期耦合**:jieba 修检索召回质量,OQ13 修路由权重;两者都要动 test_mgraph.py 的 CJK 夹具(E2/G6/A2),故 M4 排在 M3 后(§2.3.3)。OQ13 裁 B 的词表(routing_intent_causal/temporal)在 jieba 词元化后对齐度更高,是「先裁后切」的附注理由。
- **DP9 mgraph v2 图贫瘠修复**(memory:v13-dp9-mgraph-m2):锚池机制(anchor_terms/anchor_tinql/anchor_guard)是 M4 jieba 落地时改动最大的 v13 自研件(§2.3.2-3);canonical signal 单向入封等既有教训不受本次升级影响。
- **v13.1 workbench plane**(`docs/designs/v13.1-workbench-plane.md`、`docs/plans/v13.1-workbench-plane-plan-2026-09-21.md`):文本/代码产物回流 v13 chunks/recall(:68,T2 离线批量投影定位),在线 RAG 已裁不走 duck(T0/T1 仍是 stannum/tsvector+vectorchord,:213)。**对本报告的含义**:①代码语料回流后,chunks 的 token 形态(标识符/长 token)会抬高 long_tokens/max_token_bytes 配置面的重刻画需求(canary WITH 面正是既有试验田)——属 L0 复核项的延伸而非新层;②L3 多列 BM25F 的最可能触发源就是 v13.1 回流产物带结构化字段(title/kind/summary)时;③分发审查沿 stannum AGPL 先例(plan :585 已引用)。
- **v13-rag-subagent**(T0/T1/T2 分层):T0 已交付;本报告 L4 与其 T1 触发线对齐(§2.5);psql_bm25s 备胎条款不动。
- **v8 及更早版本**:零关联(stannum 是 v13 才引入的依赖面;v1 五补丁澄清见 §1.4)。

---

## 附 A. 本报告核实的证据清单(主 checkout,file:line)

- `v13/characterize/v13_characterize.sql`:7-8(0.1.0 注记)/12(CREATE EXTENSION 唯一装载点)/23-24(canary WITH long_tokens/max_token_bytes)/26(ix_chunks_stannum 默认)/29-83(extract_spans 哨兵机制,highlight 4 参在 :56)/95-112(v13_recall 三段式+sources join)/103(full_score)/107,125(`==>` 两处)/117-131(recall_count 带 join 过滤)/186-190(verify_index 第八项)
- `v13/characterize/setup_db.py`:22-30(GRANTS 10 参双函数)/37-45(probe_extension fail-closed)
- `v13/characterize/README.md`:16(升级复测 K3+K5)/69-95(0.1.0 实测记录)
- `v13/characterize/test_characterize.py`:384-390(K1)/409-420(K3/L2)/430-453(K4)/672-690(O2)/696-702(P1/P2)/822-860(R1/R2 逐文件计数)
- `v13/memory/v13_memory.sql`:18-24(transcript_chunks DDL)/30-32(OQ9 注释+索引)/161(decisions 索引)
- `v13/memory/test_memory.py`:504-518(K3 plan)/530-532(K4 计数)/640-641(M1)
- `v13/mgraph/v13_mgraph.sql`:25-31(memory_nodes DDL)/49(索引)/752-758(candidates 三段式)/1474-1483(route 三态短路)/3206-3237(anchor_terms n-gram)/3240-3244(anchor_tinql OR)/3246-3310(anchor_guard 白名单)
- `v13/mgraph/test_mgraph.py`:2749-2756(G6)
- `v13/recall/v13_recall.sql`:33-40(五区间码点表)/89-93(build_tinql 引号包裹)
- `v13/schema/v13_core.sql`:393-399(decisions DDL,question ASCII CHECK)
- `v13/chunks/v13_chunks.sql`:141-147(chunks DDL)
- `v13/load.py`:12(pgembed import)/16-33(SQL_LOAD_ORDER 16 文件)
- `pyproject.toml`:8,19(pgembed pin+editable fork);`v13/**/test_*.py` 共 16 个 gate
- `docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md`:7(0.1.0 实证注记)/1283-1284(行为依赖清单行 12)
- `docs/designs/v13-context-on-pg.md`:40-45(§2.1 stannum API 面)
- `docs/designs/v13-rag-subagent.md`:57-58(stannum 0.1.0/vchord T1)/64(psql_bm25s 备胎)
- `docs/designs/v13.1-workbench-plane.md`:68,213(产物回流/在线 RAG 已裁)
- `docs/investigations/v13-mgraph-v2-cjk-routing-investigation-2026-09-24.md`:197-213(OQ13/OQ14)
- `v13/mgraph_assembly/README.md`:156-159(W4:O2 段错误 0.3.0 signal 11)

## 附 B. 底稿存疑断言与待实证清单

| # | 断言来源 | 内容 | 状态 |
|---|---|---|---|
| B1 | 底稿 §5.2-1 | 「recall/economy/mgraph 的 `==>`+full_score+highlight 链路可简化(换 search())」 | **本报告否决**(§2.2.1):三链路均带关系谓词,search() 无过滤模型不等价;economy/summary/periphery/mgraph_assembly 本就零直连(只消费候选信封),无链路可简化 |
| B2 | 底稿 §1(未记录) | search() 的 snippet 是否窗口截断(截断则哨兵反推 spans 机制不可承载) | 待实证 |
| B3 | 底稿 §1(未记录) | search() score 排序 tie-break 稳定性(v13 排序契约=并列 content_hash 终裁) | 待实证 |
| B4 | 底稿 §1(未记录) | jieba tokenizer 对 Katakana 连跑的切分行为(决定 build_tinql 引号 workaround 能否摘除) | 待实证(M2 探针) |
| B5 | 底稿 §1(未记录) | 无索引回落 comparator 与 tokenizer 的关系(jieba 索引下 K3 的 64B miss 形态) | 待实证(M2 探针) |
| B6 | 底稿 §5.3-1 | 「v13 setup_db.py 的 5 个 SQL bug 补丁升级后需逐条核对是否上游修复」 | **已消解**:触点盘点 §2 澄清五补丁在 v1 PATCHES、与 v13/stannum/pgembed 无关;无需核对 |
| B7 | 底稿 §4 | pgembed_stannum 子包「要求 PG18」及 standalone wheel 语义 | 采信(不影响 v13:v13 不 import 该包);v13 直连实例模型下仅 RRF SQL 模板有移植价值 |
