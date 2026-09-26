# v13 充分发挥 stannum 0.4.0 —— 利用方案计划（2026-09-26）

> 纯设计交付。本文件落盘即完成：不改代码/SQL/测试，不跑 gate。
> U1/U2 是经本计划批准的后续实施范围；五个提交是其后的执行序列，不是本文件提交的一部分。
> 五项已裁（2026-09-26，见 §6）。本文件可执行，不再待拍板。
> 输入：能力面档案 `docs/investigations/v13-stannum-0.4-capability-dossier-2026-09-26.md`、适配面档案 `docs/investigations/v13-stannum-0.4-fit-dossier-2026-09-26.md`、使用核查 `docs/investigations/v13-stannum-usage-audit-2026-09-26.md`、结案 `docs/plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md`、M3-stop `docs/investigations/v13-m3-stop-why-and-how-to-advance-2026-09-25.md`。引用一律 `文件:行`。
> 重开句只允许被引用：本文件不写 OQ15 重开句，也不写 DP9-OQ3 重开句。形式要求由后续子计划正文自写。

## 0. 执行索引

- §1 定位与边界：本文件是什么、不推翻的硬事实、冻结面。
- §2 候选方案枚举与评估：八个候选（①–⑧）。②④⑤⑧的开放项已裁，见 §6。
- §3 已批准的后续实施：U1a → U1b(乙) → U1c → U2a → U2b，加 U3 链约束。每里程碑给合同、收尾工件、回滚。
- §4 显式不做清单（防未来重复提案）。
- §5 风险与回退汇总。
- §5.1 按里程碑回归矩阵。
- §6 裁决记录。
- §7 三分钟摘要。
- §8 实施顺序。
- §9 文件级影响。

## 1. 定位与边界

### 1.1 本计划是什么 / 不是什么

本文件回答一个问题：**v13 在 stannum 0.4.0（pgembed pin `ad4d3b7`，`pgembed/pgbuild/Makefile:278`）上，还有哪些已交付能力没接满、哪些 0.4.0 新能力值得采纳、按什么顺序落地。**

本文件本身是纯设计交付。落盘即完成，零代码。

U1/U2 改称**经本计划批准的后续实施范围**。五个提交（U1a、U1b、U1c、U2a、U2b）不是本文件提交的一部分，而是其后的执行序列（§8）。实现者不得把「落盘即完成」读成「五个提交可以不做」，也不得把「五个提交」读成「写进本文件的同一次提交」。

本文件**不是**：

- 不是 jieba 整包的实施计划（后续子计划 U3c，见 §3.5；逃逸口已生效，仍由该子计划自己动笔）；
- 不是 CJK 路由重开计划（U3b，条件触发，见 §3.5）；
- 不是 §8 三条触发的测量文书（U3a，只读，见 §3.5）；
- 不是重开文书。本文件**不写** OQ15 重开句，也**不写** DP9-OQ3 重开句。凡涉及 M4/jieba 或路由重开的阶段，形式要求见 §3.5：由该子计划正文自写，本文件的落盘不构成重开。

测量/路由/jieba 的代码**不排进本文件**。本文件把候选评估、组合、排序与约束钉成可执行合同。

### 1.2 不推翻的硬事实（档案已证，直接采用）

| # | 事实 | 证据 |
|---|---|---|
| H1 | 四张被索引表（chunks/transcript_chunks/memory_nodes/decisions）各只有一列自由文本；多列/`field_weights`/BM25F/LSG4/5 参 field highlight 在当前 schema **零落点**；加第二文本列属 M5 事件门，结案明令不发明 | fit 档案 §1 表与「天然单文本列」注（`docs/investigations/v13-stannum-0.4-pgembed-adaptation-2026-09-25.md:156-163`）；结案 `:36` |
| H2 | `search()`/`search_count()` 替换三段式已裁否决：无过滤参数，「先 top-k 后过滤」≠ v13 的「过滤后 top-k」 | fit 档案 §2；适配调查 `:93-103` |
| H3 | transcript_chunks 中英混排、memory_nodes 纯中文 → jieba 是 0.4.0 时代对 v13 真实收益最大的一项；但 M4 有整包先决，重开句由 U3c 子计划正文自写，本文件不写该短语 | 结案 `:28-32`；jieba 探针 §9（`docs/investigations/v13-jieba-canary-probe-2026-09-25.md:391-405`） |
| H4 | 已交付的 65 断言 usage gate（`v13/mgraph/test_stannum_usage.py`，`e6fe89b`）把「零采用」钉成断言：F4 `:983-1018`、F5 `:1012-1018`、F8 `:1031-1033`、V8/V9 `:633-635`、F13 `:1063-1082` 等；任何采纳必须同提交同步这些断言。断言**条数不是合同**，合同是断言 ID | 能力档案附录「现存 gate 冲突点」 |
| H5 | R2/G1/H6 的 `files_through` 源码计数是**位置敏感**的；新增 SQL 文件进 `v13/load.py` 会使前 8/9 个文件位置右移，R2（`test_characterize.py:840-860`）/G1（`test_recall.py:1063-1072`）/H6（`test_filter.py:2544-2547`）全红 | fit 档案「自由发现 2」 |
| H6 | B12：`GRANT EXECUTE ON v13_mgraph_candidates TO v13_recall`（`v13/mgraph/v13_mgraph.sql:1211-1212`）是死授权——INVOKER 链内部依赖（`entities_of`/`entities`/`keywords_of`/`jaccard`）只授 `v13_resolve`（`:1204-1209`），`v13_recall` 直调 42501，错误文本今天含 `v13_mgraph_entities_of`；R8a/R8b 只锁现状（`test_stannum_usage.py:1125-1131`） | fit 档案 §6；使用核查 B.12 |
| H7 | `ix_memory_nodes_stannum`（`v13_mgraph.sql:49`）被检索但无生产 verify；DP9 `:66` 要求 `v13_verify_mgraph` 含 `stannum.verify_index` findings=0。今日缺口只有这一处生产索引 | 使用核查 B.2；`docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md:66` |
| H8 | 0.4.0 行为差异对现有 gate 风险 ≈ 0：v13 调用面（单列、无 `field_weights`、4 参 `highlight`、1 参 `full_score`、text/text `==>`、无字段组 tinql）落在「0.4.0 未改动交集」里 | fit 档案 §9 全表与净结论 |
| H9 | 生产表全部 < 100 行夹具尺度，规划器断言靠 `enable_seqscan=off`；段调优/GUC 调谐在 v13 量级下无实测收益对象 | fit 档案 §1 夹具行数段 |
| H10 | `v13_verify_memory` 的挂法先例 = 手动可调 + gate、owner-only、**不挂 cron**（`v13/memory/v13_memory.sql:163-164`）；cron 计数有断言（chunks 恰一条 `test_chunks.py:1107-1109`、memory 恰两条 `test_memory.py:696-699`）。这两条计数在各自 stage 库，**看不见**后来写进 `v13_mgraph.sql` 的 job | fit 档案 §5 |

### 1.3 冻结面（本文件及后续子计划均不得触碰，除非该子计划自写对应重开句）

- `v13_mgraph_route`、E2（`test_mgraph.py:1606-1614`）、G9 闭集（`:2792-2797,:2825-2828`）——受 DP9-OQ3 保护。重开须由该子计划正文自写 DP9-OQ3 重开句（结案 `:24`；M3-stop `:102-113` 十行之 1/8）。本文件不写该短语。
- `v13_mgraph_anchor_terms` 的 CJK 3-gram 分支（`v13_mgraph.sql:3230-3237`）、L3（`test_characterize.py:495-503`）、G6（`test_mgraph.py:2723-2757`）、生产索引 tokenizer——受 OQ15/结案 `:28-32` 保护。重开须由该子计划正文自写 OQ15 重开句。本文件不写该短语。
- `decisions.question` 的 ASCII CHECK（`v13/schema/v13_core.sql:398-399`）——三份文档共同引用的不变量，**永不切换**（结案 `:29`）。
- 冻结的 `v13_query_segments`（`v13/recall/v13_recall.sql:13,70-72`）——任何计划不得编辑（M3-stop 十行之 7）。

## 2. 候选方案枚举与评估

八个候选。开放项已裁的，裁决形式写定论；细节合同在 §3。

### ① jieba 整包（M4）

- **价值**：0.4.0 时代对 v13 收益最大的一项（H3）。jieba 把中文按词切（`开源数据库` → 2 term 而非 4 单字，能力档案 §9）；memory_nodes 纯中文、transcript_chunks 中英混排（fit §1 语言形态表）；锚从字符 3-gram 滑窗升为词级；L3 的单字片假名 miss 反转为命中。
- **成本**：一次提交四件（结案 `:32`）：词级锚 + L3 重写（不放宽、禁 OR 宽化）+ highlight 绑定断言（若 U2b 已先行，则**扩展 P5b**，不另起平行断言）+ G6 同提交重写；生产索引 chunks/transcript_chunks/memory_nodes 切 `tokenizer='jieba'`（REINDEX 级）；词典治理进 runbook（探针 §9.7）。运行成本：首查约 100–200 ms 词典加载 + 数 MB~95 MB RSS（探针实测 `:275`）。
- **风险**：3-gram OR 在 jieba 上 7/7 全灭（探针 `:157-168`）→ 不改锚 G6 必红；四时刻不对称（列变量 highlight 跟索引 tokenizer，`v13_extract_spans` 4 参 text 重载走默认 unicode，探针 `:221`）→ 不改 extract_spans 调用形状则「召回有、spans 空」；jieba-rs crate 升级必须 REINDEX（能力档案 §9）；自定义词典非空时自定义扫描拒绝并行 worker。
- **会翻的 gate**：L3（`test_characterize.py:495-503`）；G6 三件（`test_mgraph.py:2723-2757`）；usage gate P12 / F6；若拆新 SQL 文件则 R2/G1/H6（H5）。
- **依赖与排序**：M3-stop `:152` 之 1：第一份可写代码的新计划就是 jieba 整包，测量不是它的前置。之 3：路由计划**若落地**，jieba 排在其后，避免两线同改 `test_mgraph.py`。已裁：逃逸口生效（§6-2）。U2b 必须先于 U3c 合并。U3c 与 U3b 永不并行在飞。本文件的五个提交里没有 jieba。
- **裁决形式**：逃逸口已生效。U3c 子计划可在 U1/U2 与 U2b 全绿落盘后起草，不必等 U3a/U3b。防护条款见 §3.0 / §3.5。**U3c 子计划动笔时正文自写 OQ15 重开句。本文件不写该短语，本文件的落盘不构成重开。**

### ② 结构性补洞：B12 已裁乙 + `ix_memory_nodes_stannum` 生产 verify

- **价值**：消两个「名义有、实际无」的合规面缺口（H6/H7）。乙让死授权出账，目录与调用图一致。verify 补洞让图索引损坏能进 verify 报告。
- **成本**：小。两笔独立提交，都在既有 `v13_mgraph.sql` 内，不新建 SQL 文件（H5）。
- **已裁（B12 = 乙）**：删除 `v13_mgraph.sql:1211-1212` 对 `v13_recall` 的授权，并**显式 REVOKE** 收敛存量 ACL。不授四个帮助函数。不新增读环函数。合同见 §3.2。
- **被拒（甲）**：把 `entities_of` / `entities` / `keywords_of` / `jaccard` 再授给 `v13_recall`。读环调用方 `v13_mgraph_anchors`（`:1684`）与 `v13_mgraph_transition_score`（`:1802`）只出现在授给 `v13_resolve` 的块（`:2593-2604`）。甲没有新的合法消费者，权限面变大，读环仍然不通。不采纳。
- **触发式后续（丙）**：只有真实的、以 `v13_recall` 执行的读环调用方被设计并获批时，才连同 `anchors` / `transition_score` 的授权形状一起重裁。调用方与整条 INVOKER 授权闭包同一提交落地。超出本次补洞，且靠近 U3 要改的 `v13_mgraph.sql`。现在不做。
- **verify 范围已裁**：仅 `ix_memory_nodes_stannum`。不变量：每个生产 stannum 索引恰一个 verify wrapper。合同见 §3.3。
- **会翻的 gate**：R8a 必改（今天锁的是 `entities_of` 上的 42501）。P9/P11 的 `not has_verify_mgraph` 在 U1c 必改（交付实现见 §3.3，不是「verify_index 白名单加名」）。G6 只数 `==>`（`test_mgraph.py:2726-2727`），乙不改锚函数体、verify 正文禁止 `==>` → 不翻。R21 只比对 12 份 `setup_db.py` 的 stannum `score_bound*` 块，不扫 `v13_mgraph.sql` 的业务 GRANT → 乙不翻。不新建 SQL 文件 → R2/G1/H6 不翻（H5）。`v13/mgraph_assembly/test_mgraph_assembly.py` 的 `PREFIX_FREEZE["v13_mgraph.sql"]`（当前 `450bc7e4fb581148`）会因字节变化失配，U1b 与 U1c **各自同提交重钉**，不宽化比较式。
- **依赖与排序**：无测量/路由前置。U1b 先于 U1c（同改 `v13_mgraph.sql` 与 `test_stannum_usage.py`，禁并行分支）。
- **裁决形式**：已裁。见 §6-1、§6-5。

### ③ 运维面落地：`index_stats`/`index_health`/段调优 + autovacuum 节奏

- **价值**：把「仅 runbook」的运维面（使用核查 A.3）升格为 runbook 补缺。F9/F10/F11 已钉可用性。增量是权限措辞、生产化参考、调试入口。
- **成本**：小（纯文档）。
- **风险**：过度工程——v13 表 < 100 行（H9）。stannum 侧调优证据来自 100k Wikipedia benchmark，与夹具差 3 个数量级。
- **会翻的 gate**：runbook 面零翻。若落会话 GUC → F13 翻红；若落 `ALTER TABLE ... SET (autovacuum_...)` → schema 变更面。两条都不做。
- **依赖与排序**：无前置。U2a 可与 U1a 并行，单独提交，不插进 U1b/U1c。
- **裁决形式**：runbook 增补采纳（U2a，合同见 §3.4）。GUC/段调优落地显式不做（§4-6）。

### ④ highlight 绑定断言（消使用核查 B.5 风险）

- **价值**：B.5——`v13_extract_spans` 用 4 参 text `highlight`，参数是 plpgsql 变量不是列（`v13_characterize.sql:59`），`highlight_support` 改写吃不到。今天 spans 与索引切分一致只靠默认参数碰巧等于生产索引 reloption。生产索引一旦改 tokenizer / `max_token_bytes` / `long_tokens`，召回按索引切、spans 按默认切，静默分裂（探针 `:221`）。
- **成本**：小。usage gate 增补 **P5b**。不改 `v13_extract_spans` 函数体。断言条数不写死。
- **风险**：用错重载或纯拉丁夹具会假绿。合同见 §3.4。
- **会翻的 gate**：无既有断言翻。索引 analyzer 日后偏离默认时 P5b 变红是**预期**，逼整包在同一提交里改 `extract_spans` 或扩展本断言。
- **依赖与排序**：无前置。是 jieba 整包「先验证再切」的机制前置（探针 §9.3）。结案 `:32` 约束包内四件缺一不可，不禁止机制预存。
- **裁决形式**：已裁先行。不折进 U3c。U3c 扩展 P5b，不另起平行断言。

### ⑤ `score()` / `score_stop_words auto:zh` 相关性调谐评估

- **价值**：`score()` 可省略极常见词，`score_stop_words` 接受 `auto:zh`（能力档案 §9；`docs/compatibility.md:177-186`）。
- **成本**：中，而且不是 reloption 小改。三条生产动态 SQL 都是 1 参 `full_score`（`v13_characterize.sql:106`、`v13_memory.sql:151`、`v13_mgraph.sql:753`）。**`full_score` 永远忽略 `score_stop_words`**。要用此旋钮必须换成 `score()`。
- **风险**：绝对分值无 gate（使用核查 B.8）；mgraph 的 `lexical_norm` 融合（`v13_mgraph.sql:764-776`）无分值断言（fit 自由发现 3）。夹具 < 100 行（H9），无可测量对象。
- **会翻的 gate**：P0a–P0d 全文相等；P12；K/P/Q 命中集合有真实翻红风险。
- **依赖与排序**：无硬前置。收益无证。
- **裁决形式**：**维持显式不做**。不另立当前评估子计划。重开条件四句见 §4-5，顺序不可跳。

### ⑥ 多列 / `field_weights` / BM25F / LSG4 / 5 参 field highlight

- **价值**：零落点（H1）。
- **成本**：须先发明第二文本列——M5 事件门，结案 `:36` 明令不发明。
- **风险**：即便有第二列，证据面也薄（LSG4 剪枝方向不利；`docs/benchmarks/` 对这三项零命中）。
- **会翻的 gate**（若强做）：F4/F5、P12、K1、R 组计数。
- **依赖与排序**：M5 事件门，无排期。
- **裁决形式**：**显式不做**（§4-1）。结案 Q3=A 已裁。

### ⑦ TINQL 高级语法拓宽（wildcard/regex/range/fuzzy/NEAR/span/positional/boost/slop/`AT LEAST n OF`）

- **价值**：能力存在，但 v13 的 tinql 文法收窄是刻意的（三层文法 + V3005；AND 形与 OR 形互斥，fit §3）。
- **成本**：拓宽 = 拆守卫 + 重写两个发射器 + 全套断言。
- **风险**：守卫是防注入/防 LLM 自由发挥的第一道墙。
- **会翻的 gate**：G7、守卫全部断言、R 组计数。
- **裁决形式**：**显式不做**（§4-3）。

### ⑧ demo_v13 两处潜伏 bug 修复

- **价值**：消两处已坐实的 demo 正确性债。`memdrive_phase2.py:168-171` 把 AND 形 `v13_build_tinql(body0)` 直喂 `v13_mgraph_candidates`，guard 只按 `' OR '` 切（`v13_mgraph.sql:3267`），多段 body 必 V3005；`one()`（`:76-85`）无 try/except。`mem2_observe.py:156` 的 `n_terms` 按 `'` 切，anchor tinql 项是双引号包裹，恒为 1。先修，demo 才能当 jieba 前后的对照基线。
- **成本**：极小。修法已收成单一路径，见 §3.1。不保留「标注 AND 形必失败并跳过」这一支。
- **风险**：低。demo 检索面无 gate。
- **会翻的 gate**：无。
- **依赖与排序**：无前置。排在 U3c 之前。
- **裁决形式**：无需再裁。按 §3.1 执行。

## 3. 已批准的后续实施

### 3.0 组合结论与排序

**组合 = ②（乙 + 仅 memory_nodes verify）+ ③ runbook 面 + ④（P5b 先行）+ ⑧（demo 实路径修复）。** 这是经本计划批准的后续实施范围，不是本文件提交。⑤⑥⑦与 ③的 GUC 落入 §4。① 保持为后续子计划 U3c：逃逸口已生效，本文件仍不交付其代码。

一句话理由：v13 的调用面已落在 0.4.0 未改动交集里（H8），明星新能力在当前 schema 零落点（H1）。「充分发挥」是把漏接面接满，并让 jieba 以整包形态进入队列——不必再等一扇允许继续关着的测量门。

**本范围执行序**（严格串行，禁并行分支）：

```
U1a → U1b(乙) → U1c → U2a → U2b
```

- U2a 纯文档，**可与 U1a 并行**，但单独提交，不得并进 U1b/U1c/U2b。
- U1b 与 U1c 都改 `v13_mgraph.sql`，禁止两支并行分支。
- U1b、U1c、U2b 都改 `test_stannum_usage.py`，禁止并行分支。
- `test_stannum_usage.py` 与 `test_mgraph.py` 共用库名 `agent_v13_mgraph`，各自 DROP/CREATE，这两条不能并行。
- U1/U2 不碰 §1.3 冻结面，也不改 `test_mgraph.py` / `test_characterize.py` 的断言正文（assembly 的 `PREFIX_FREEZE` 哈希除外，见 §3.2）。与 U3b/U3c 无同一编辑区域的设计冲突；文件冲突若发生，是延后 rebase，不是许可并行在飞。

**U3 链**（本裁决已生效，不再「用户再批一次」）：

```
U2b 全绿落盘
    ↓
U3c 可起草（不必等 U3a/U3b；若 U3a 已在飞则先等其落盘）
U3a 可另行测量（证据绑定测量时 commit 与 tokenizer 形态）
    ↓ 三条各自「已满足」且证据与目标代码基线一致
U3b
U3c 与 U3b 永不并行在飞
```

- 推翻的是「测量 → 路由计划 → jieba」这条硬链，不是整包纪律。M3-stop `:152` 之 1 把 jieba 整包列为第一份可写代码的新计划；测量不是它的前置。之 3 只约束：路由计划若落地，两线不得同时改 `test_mgraph.py`。
- U3a 不是 U3c 的前置。若 U3a **已经在飞**，先等其落盘再开 U3c，避免测量基线白测一场再复测。U3a 尚未开工时，不必为了等它而挡住 U3c。
- U3c 若在某次 U3a 之后落地：依赖锚、候选、walk 的测量必须在新 HEAD 上复测。绝对候选集不能跨 tokenizer 复用。触发①（边是否存在、是否被 walk 消费）不依赖分词；触发②比较的是**同一索引**上的配额差，分词是该次测量的常数。U3b 不得消费过期的 pre-jieba 证据。
- U3b 仍必须等待 U3a 对 §8 三条各自留下「已满足」的 file:line，且证据与 U3b 目标代码基线一致。
- 少数意见（维持保守序 + 「U3a 落盘且至少一条未满足」触发器）不构成前置，只留在 §6。

### 3.1 U1a —— demo_v13 两处修复（后续实施）

单一路径。不保留「标注 AND 形必 V3005 并跳过」。

| 项 | 内容 |
|---|---|
| 做什么 | `demo_v13/memdrive_phase2.py:168-171`：第二参改为 `v13_mgraph_anchor_tinql(body0)` 的返回值。返回 NULL、空串、或 0 项时**不调用** `v13_mgraph_candidates`，`candidates_probe_n` 记 0。有项则把 OR 形 tinql 照旧喂给 candidates。不给 `one()`（`:76-85`）加总括 try/except——那会吃掉真 V3005。空结果在 Python 侧短路，不把空串送进 guard。`demo_v13/mem2_observe.py:156`：tinql 为空则 `n_terms = 0`，否则 `n_terms = tinql.count(" OR ") + 1`。项由 `string_agg(..., ' OR ')` 产生，guard 禁止项内引号，项内不会出现带空格的 ` OR `。不要按 `"` 或 `'` 切 |
| gate 设计 | demo 无 gate。复跑两个脚本自带的库，不进 §5.1 的八命令。人工核对：`n_terms` **等于**该条 tinql 的 OR 段数（单段拉丁 body 的正确值就是 1，禁止写成无条件 `n_terms > 1`）；fit §10 那条含多个 ` OR ` 的观察串必须 `> 1`；phase2 不再出现 V3005；`candidates_probe_n` 为整数；日志里的 anchor tinql 为 OR 形。顺带看三份 `demo_v13/setup_db*.py` 的 stannum GRANT 副本仍与 12 份正本一致。本提交不改它们。R21 不扫这三份 |
| 改哪些既有断言 | 无 |
| 收尾工件 | 只限源码。不提交 `memtrial` / `memtrial2` 生成日志。不回改日期化 fit dossier（§10 保持历史快照；「已修」由 demo 源码与复跑证明，不写进调查文档）。若 `demo_v13` 有 README，可记一行修复说明 |
| 回滚 | 单提交 revert；零数据面 |
| 提交边界 | 独立提交，只动 `demo_v13/`。回归 = §5.1 U1a 行 |

### 3.2 U1b —— B12 乙：显式撤销死授权（后续实施）

已裁乙。不是三选一。

| 项 | 内容 |
|---|---|
| 做什么 | 在 `v13/mgraph/v13_mgraph.sql` 的 ACL 块：删除 `:1211-1212` 的 `GRANT EXECUTE ON FUNCTION v13_mgraph_candidates(uuid,text,int) TO v13_recall` 及「M3 读环锚复用」注释。在 resolve 的 GRANT（`:1204-1209`）之后，同一块内显式 `REVOKE EXECUTE ON FUNCTION v13_mgraph_candidates(uuid,text,int) FROM v13_recall`。保留已有的 `REVOKE ... FROM PUBLIC`（`:1196-1202`，已含 candidates）与对 `v13_resolve` 的 GRANT。不改四个帮助函数、不改三个 anchor 函数的 ACL。替换注释不得含 `==>` 或 `stannum.`。注释定稿：「读环调用方缺位：anchors 与 transition_score 只授 v13_resolve。candidates 对 v13_recall 的预授已撤；将来以该角色执行的调用方出现时，与整条 INVOKER 授权闭包同一提交再授。」 |
| 为什么必须 REVOKE | PostgreSQL ACL 是持久状态。测试库 DROP/CREATE 时，删掉 GRANT 行就表现为权限消失。已有库重载修改后的 SQL **不会**因为源码少了一行而撤掉旧授权。只删 GRANT、PUBLIC 或第二处 GRANT 仍在时，`v13_recall` 仍进得了 candidates，R8a 仍报 `entities_of`，乙未生效。显式 REVOKE 让重复加载收敛到同一状态 |
| gate 设计 | 同提交改 `test_stannum_usage.py`。**R8a**：`v13_recall` 直调 candidates 得到 `42501`，错误文本含函数名子串 `v13_mgraph_candidates`（不再是 `v13_mgraph_entities_of`）。只匹配函数名子串，不匹配整句英文，以免 locale 翻红。**R8b**：不改。`v13_resolve` 同参数成功且行数 ≥ 1。**R8c**（新 ID，不重排 R9 以后）：`has_function_privilege('v13_recall', 'v13_mgraph_candidates(uuid,text,int)', 'EXECUTE')` 为 false；同一询问对 `v13_resolve` 为 true。这是布尔矩阵的全部必钉项。不要加「recall 对四个帮助函数无 EXECUTE」——那可能在默认 PUBLIC 下为假，而本里程碑禁止为了让它变假去 REVOKE 帮助函数。源码侧：`v13_mgraph.sql` 中不得再出现把 candidates GRANT 给 `v13_recall` 的语句。实施时若删 GRANT 并 REVOKE 之后 recall 仍为 true，同一提交找到残留的 PUBLIC 或第二处 GRANT 并 REVOKE，直到 R8c 为 false；仍然不要动四个帮助函数和三个 anchor 函数。实施前 grep `v13_mgraph_candidates` 的 GRANT/`proacl` 快照；若某测试把 recall 对 candidates 钉成 true，把那个文件加进本提交 |
| 改哪些既有断言 | R8a（必改）。R8b 保持。G6、R21、`==>` 计数不改。新增 R8c |
| 收尾工件 | `v13/mgraph/README.md`：不存在 recall 侧调用方，预授已撤；未来调用方落地时必须同时设计完整 INVOKER ACL 闭包。`v13/load.py` 不动。`v13/mgraph_assembly/README.md` 第 9 条现文是 J9 的四个 INVOKER 补 GRANT，不引用 B12；未引用则不改该 README。`PREFIX_FREEZE["v13_mgraph.sql"]` 同提交重钉为新 sha256 前 16 位（`hashlib.sha256(path.read_bytes()).hexdigest()[:16]`），比较式不宽化。实施前再 grep `450bc7e4fb581148`，确认没有第二处钉死；当前只有 `test_mgraph_assembly.py` |
| 回滚 | 单提交 revert：恢复 GRANT 行、去掉本提交的 REVOKE、哈希回到本提交前。这恢复的是「入口可执行、内部仍在 `entities_of` 失败」的旧状态，**不是**一条可用的生产读环。不要把回滚写成恢复可用路径 |
| 提交边界 | 独立提交。文件：`v13_mgraph.sql`、`test_stannum_usage.py`、`v13/mgraph/README.md`、`test_mgraph_assembly.py` 的冻结哈希。回归 = §5.1 U1b 行。不与 U1c 合并 |

### 3.3 U1c —— `v13_verify_mgraph`：只补 `ix_memory_nodes_stannum`（后续实施）

范围已裁定论，不再「执行时核对」。

**不变量**：每个生产 stannum 索引恰由一个 verify wrapper 所有，无重复、无遗漏。

| 索引 | 唯一生产 wrapper |
|---|---|
| `ix_chunks_stannum` | `v13_verify_chunks` |
| `ix_transcript_stannum` | `v13_verify_memory` |
| `ix_decisions_question_stannum` | `v13_verify_memory` |
| `ix_memory_nodes_stannum` | `v13_verify_mgraph`（本里程碑新增） |

`ix_v13_canary` 不进生产映射，保持仅 gate。decisions 无检索消费者是设计（`v13_memory.sql:158-161`），校验留在 `v13_verify_memory`，不重复挂接。

DP9 `:66`（2026-09-23）写的是 `v13_verify_mgraph` = 自证 + 悬空边 + 策略行 + 两索引 `stannum.verify_index` + 源码无 `cypher(`。该行点名的 stannum 索引只有 `ix_memory_nodes_stannum`。「两索引」的历史数量**不**构成今天再挂第二个 `verify_index` 的要求，也不发明索引。自证 / 悬空边 / 策略行 / `cypher(` 是非 stannum 关系检查，不能塞进 `stannum.verify_index`，本里程碑不实现；若将来要补，另立，不进本函数。

核查 C.4「不要给 `ix_memory_nodes_stannum` 补生产 `verify_index`」限定的是第二阶段 gate 的实施范围（P11 只在测试里直调）。本里程碑是该禁令的刻意后续，不构成冲突。C.4 另一条仍然有效：不要把 `index_stats` 塞进任何 verify JSON。

| 项 | 内容 |
|---|---|
| 做什么 | 在 `v13/mgraph/v13_mgraph.sql` 内（**不新建文件**，不改 `v13/load.py`，H5）新增 `v13_verify_mgraph`。实施前读 `v13/memory/v13_memory.sql:163-206` 并逐项复制接口，不另发明 repair。已读定论，实施时若该段未漂移则照此写，漂移则以该段为准、不另设计：签名 `v13_verify_mgraph(p_raise boolean DEFAULT true) RETURNS jsonb LANGUAGE plpgsql VOLATILE`。`p_raise` 的含义与 memory 相同：检查未全绿且 `p_raise` 时 RAISE，错误体带 checks。它**不**控制 heap_check——memory 把 `verify_index` 第二参写死 `true`，本函数同样写死 `true`，不要把 `p_raise` 误转成第二参。返回 envelope 只许 `version` / `checks` / `all_ok`，`version = 1`。checks 元素只许 `name` / `ok` / `detail`。唯一 check：`name = 'memory_nodes_verify_index'`，`detail = {"findings": n}`，与 memory 的 `transcript_verify_index` / `decisions_verify_index` 同构。不要复制 self_cert / source_events / policy_present，不要加 `index_stats`。预期新增调用只有 `stannum.verify_index('ix_memory_nodes_stannum'::regclass, true)`，`severity IN ('error','warning')` 计数为 findings。`SECURITY INVOKER`（文件既有约定：全树零 DEFINER）。`REVOKE EXECUTE ... FROM PUBLIC` 与函数定义同一提交；不 GRANT 给 `v13_recall` / `v13_resolve` / `v13_route`。新建函数默认 PUBLIC EXECUTE，漏撤由 recall 的 42501 断言抓住。ERRCODE 用本 stage 既有 V3009（`v13/mgraph/README.md` 机制段「错误码一律 V3009」），不引进 memory 的 V3006，也不发明第三码。消息前缀 `v13: verify_mgraph failed:`。`verify_index` 抛出的 SQL 错误原样传播；warning/error findings 进入 checks，不被吞掉，也不伪造成功 |
| 锁 | `verify_index(..., true)` 拿表和索引的 ShareLock，可能与 insert/fold/merge/VACUUM 互等。函数同步执行，只允许 owner/superuser 手动调用。建议低写入时段。不设后台任务、不设重试循环、**不挂 cron**。查询取消或事务回滚释放锁，不写持久状态，不留「部分完成」标记。SQL 错误直接返回调用方，由操作者重试 |
| 正文禁记 | 函数正文和注释不得出现 `==>`，不得出现 `ix_decisions_question_stannum`。G6 只数去注释后的 `==>` 恰 1；`verify_index` 本身不含 `==>`。`stannum.verify_index` 这五个字必须出现（这是调用，不是绕过）。禁止为了保住 `stannum.` 计数而动态拼名 |
| gate 设计 | **先读再改，改法已按当前交付源码定论**（`test_stannum_usage.py:887-909`）。P9 不是「`verify_index` 只许出现在 `v13_verify_memory`」的白名单。当前合取是：全 public `v13_*` 无 `question ==>`；`ix_decisions_question_stannum` 只出现在 `v13_verify_memory`；`v13_verify_mgraph` 不得存在；`v13_verify_memory` 含该索引名。P11 是 `n_mn == 0 and not has_verify_mgraph`。禁止按旧计划文字「给白名单加名」。改法：① 保留 `bad_question` 与 `bad_index`（decisions 扫描的判定对象不改）。② 删掉 P9 与 P11 的 `not has_verify_mgraph`——函数存在是本里程碑的目标，留着一落地就红。③ P9 在保留 decisions 扫描的同时，增加四索引→三 wrapper 的 **verify_index 调用**唯一映射（上表）。映射对象是 `stannum.verify_index` 的调用点，**不是**索引名在任意函数体里的任意出现——`ix_memory_nodes_stannum` / `ix_chunks_stannum` 出现在 CREATE INDEX 或检索 SQL 里不算违反。不要把 decisions 那条「名字只许出现在一个函数」推广到另外三张索引，否则 candidates/build 会误红。`ix_v13_canary` 不进映射。`v13_verify_chunks` 必须留在允许集合里。④ P11 重命名为「底层 verify 可用」：owner 直调 `stannum.verify_index('ix_memory_nodes_stannum', true)` findings=0 保持。删掉「能校验 ≠ 已接入」这句——wrapper 落地后该命题不成立。⑤ 新增，不塞进 P9 的 decisions 扫描：owner 调 `v13_verify_mgraph(false)` 时 `all_ok`、唯一 verify_index check 的 findings=0、报告恰覆盖 `ix_memory_nodes_stannum`；`v13_recall` 调 `v13_verify_mgraph(false)` 得到 `42501`，错误文本含函数名子串 `v13_verify_mgraph`（对象是包装函数，不是 `verify_index` 直调）。不新增「recall 直调 `verify_index` 必失败」——R10 已证明角色对表有 SELECT 时直调可成功。形状可照 R9 的 `role_fails`，匹配子串用函数名，不照抄整句 `permission denied`。⑥ 新增：mgraph 库上若 `pg_extension` 有 `pg_cron`，则 `cron.job` 的 jobname 与 command 都不得引用 `v13_verify_mgraph`；扩展不在则沿 `test_memory.py` N1 的降级语义打印 note、**不失败**。不修改 chunks/memory 已有 job 数量断言（那些断言在各自 stage 库，本函数不挂 job 就不会碰到）。⑦ `pg_get_functiondef`：包装函数恰一次 `stannum.verify_index`，且只引用 `ix_memory_nodes_stannum`；正文与注释无 `==>`、无 `ix_decisions_question_stannum`。实施前再 grep `v13_verify` / `proname` 计数 / `has_function_privilege` 闭集；除 P9/P11 已点名的 `not has_verify_mgraph` 外，若还有字面禁止新函数名或禁止第三处 `verify_index` 的断言，同提交改允许集合，集合必须含 chunks、memory、mgraph 三处。grep `v13_mgraph.sql` 的 `stannum.` 计数断言；若有，同提交改计数，禁止拼名绕过 |
| 改哪些既有断言 | P9（删「函数不得存在」，保留 decisions 扫描，加调用点映射）。P11（删「函数不得存在」，保留底层 findings=0，改名说明）。不改 G6 的 `==>` 计数、不改 cron 计数断言、不改 R21、不改 12 份与 demo 三份 `setup_db.py` |
| 收尾工件 | `v13/mgraph/README.md`：覆盖映射上表；`ix_memory_nodes_stannum` 已入 `v13_verify_mgraph`；DP9 `:66` 未点名的第二个 stannum 对象记「不发明」；关系检查（自证/悬空边/策略行/`cypher(`）不在本函数。`PREFIX_FREEZE["v13_mgraph.sql"]` 再次同提交重钉（U1b 之后的新哈希），不宽化。assembly README 第 9 条仍不引用 verify 缺口则不改。`v13/load.py` 不动 |
| 回滚 | DROP FUNCTION + 断言回退 + 哈希回到本提交前（单提交 revert）。纯增量、零数据面、无 REINDEX |
| 提交边界 | 独立提交，不与 U1b 合并。回归 = §5.1 U1c 行 |

### 3.4 U2 —— runbook + highlight 绑定断言（后续实施）

**U2a（纯文档提交；可与 U1a 并行，不得并进别的提交）**

| 项 | 内容 |
|---|---|
| 做什么 | `v13/characterize/README.md` 增补三条。① `index_health`：推荐数据库 owner 执行全库视图；或由对所有 stannum 底表具有不受 RLS 限制的表级 SELECT 的诊断角色执行。视图不是硬编码 owner-only；三角色失败是因为没有 canary 表 SELECT（R14/R15）。示例保持 owner 视角并指向 R14/R15，不写会过期的 documents/pages 数字。单索引 `index_stats('ix_chunks_stannum')` 在角色具备该表 SELECT 时仍可能成功，不要与全库视图混为一谈。② autovacuum：照抄 `segmented-storage.md:211-219` 的 `vacuum_index_cleanup=auto` + insert threshold 组合，标题标明这是**生产化参考**。v13 夹具库不执行这些 `ALTER TABLE`，也不 `SET stannum.*`。F13 继续锁 6 个 GUC 默认值。③ `stannum.tokenize` / `ql_parse` / `maybe_quote` 是排查 tinql 的正规入口（现列 ZERO_FUNCS，不做 gate）。诊断非默认索引时必须传入与目标索引一致的 tokenizer/options，不能把默认 unicode 输出当成 jieba 索引行为 |
| gate | 无 |
| 收尾工件 | README 本身 |
| 回滚 | revert |

**U2b（P5b，已裁先行；不折进 U3c）**

| 项 | 内容 |
|---|---|
| 做什么 | 在 `test_stannum_usage.py` 增补 **P5b**。不重排 P6 以后的编号。不改 `v13_extract_spans` 函数体，不改任何 SQL。夹具 = 本文件已有的 chunks 命中行 `BODY_CJK = "東京タワーは電波塔である kohaku"`（`:108`，含多字节；P4 已要求该 tinql 命中 ≥ 1）。绑定目标固定 `ix_chunks_stannum`。禁止用 `BODY_EN` / `quasar` 充当这条锁——拉丁词在 jieba 与 unicode 下可以逐字相同，切索引后仍可能假绿 |
| 调用形状 | 只许 4 参 `indexed_query` 重载：`stannum.highlight(body, chr(1), chr(2), stannum.bind_query(tinql, 'ix_chunks_stannum'::regclass))`。禁止用 5 参 field 形式（尾部 `field text`，无默认值，单列索引没有 recorded field）和 4 参 text 形式充当这条锁。4 参 text 是 P5 的锁（默认 tokenizer），继续保留，不替换 |
| 比较 | 复用 P5 的哨兵解析 `pg_temp.v13_usage_highlight_spans`（标签 `chr(1)` / `chr(2)`，按**字节**偏移还原区间）。两边都非空。比较完整有序 `(start_byte, end_byte)` 序列，不只比较数量或渲染文本。body 不含 `chr(1)`…`chr(8)`（P5 的 `no_sent`）。unicode 现状下两边相等——这是现状锁。索引 analyzer 偏离默认时变红是预期 |
| 位置 | P5 之后、P6 之前，在 P2 的 `measure()` / `idx_scan` / `track_functions` 窗口之外，避免碰 F14 的 calls 增量。`highlight`、`full_score`、`bind_query` 不在 F14 必须为 0 的名单里，仍然不要放进那个窗口 |
| 实施前 scratch | 先在 scratch session 验证：`bind_query(text, oid)` 直调可行（EXECUTE 没有被收成不可用）、`indexed_query` 重载 highlight 可调用、哨兵区间与 `v13_extract_spans` 在这条 CJK 夹具上一致。`[info]` 打印两边区间后再把相等钉进 `check("P5b", ...)`。打不通就停，不要改用 4 参 text 或 5 参充数 |
| 断言计数 | **不写死「65→66」**。合同是 ID `P5b` 存在且按上式比较。`v13/mgraph/README.md:14` 今天只写「核查 stannum 使用」，不要补一个会过期的条数。若工作树已经写了条数，改成实际条数 |
| 与 U3c | U3c 扩展本条（夹具/预期改成能区分 jieba 与默认 unicode），不新增平行第三条断言。U2b 提交时 extract_spans 不动 |
| 改哪些既有断言 | 无。P5 保持 |
| 收尾工件 | README 台账记 B.5 = 已由 P5b 锁住（unicode 现状；analyzer 分叉时变红是预期） |
| 回滚 | 删 P5b（单提交 revert） |
| 提交边界 | 独立提交。回归 = §5.1 U2b 行 |

### 3.5 U3 —— 后续子计划链（本文件只排序与钉约束，不交付其实现）

| 子计划 | 触发与前置 | 形式要求 | 与本文件的关系 |
|---|---|---|---|
| **U3a 测量文书**（只读） | 无前置，可随时开工。不是 U3c 的前置 | 先定义「可遍历」（v2 计划 `:354` 无定义，M3-stop F1），再按 `causes`/`entity`/`contradicts` 分开记；禁止把 2026-09-24 重跑标成①已绿（重跑 `:56` 维持台账）；`caused_by` 不得顶替 `causes`；`edges_used=0` 不得写成已行使（M3-stop 十行之 2/3/4）。每份证据绑定测量时 commit 与 tokenizer 形态（unicode 3-gram 或 jieba 词级）。U3c 若在其后落地，依赖锚/候选/walk 的项目在新 HEAD 复测 | 本文件不动笔 |
| **U3b 路由实现计划** | U3a 对 §8 三条各自留下「已满足」的 file:line，且证据与目标代码基线一致，才可动笔。不得使用 pre-jieba 的过期证据 | 正文自写 DP9-OQ3 重开句。本文件不写该短语。先做 P1-8 只读 script helper（码点五区间与 route `:1493-1498` 同表），不改冻结的 `v13_query_segments`；同提交改 `:1505-1506` 短路、E2（`test_mgraph.py:1606-1614`）、G9 闭集（`:2792-2797,:2825-2828`） | 本文件不动笔、不写该短语 |
| **U3c jieba 整包** | **GO：批准在 U2b 全绿落盘后起草并实施。** 不必等 U3a/U3b。若 U3a 已在飞，先等其落盘再开 U3c。与 U3b 永不并行在飞。少数意见的触发器不构成前置（§6） | **动笔时正文必须自写 OQ15 重开句。本文件不写该短语，本文件的落盘不构成重开。** 包内四件缺一不可（结案 `:32`）：词级锚（`v13_mgraph.sql:3230-3237`）、L3 重写不放宽禁 OR 宽化（`test_characterize.py:495-503`）、扩展 P5b 为 jieba 索引形态（不另起平行断言）、G6 同提交重写（`test_mgraph.py:2756-2757`）；生产索引与锚一起切；`decisions.question` 不切（`v13_core.sql:398-399`）；不改 route/E2/G9 | 本文件不动笔、不写该短语 |

## 4. 显式不做清单（防未来重复提案）

1. **多列/`field_weights`/BM25F/LSG4/5 参 field highlight 生产化**——四表各一列自由文本，零落点（H1）；加列是 M5 事件门，结案 `:36` 明令不发明。
2. **`search()`/`search_count()` 替换三段式**——无过滤参数，已裁否决（fit §2；适配调查 `:93-103`）。
3. **TINQL 高级语法拓宽**（wildcard/NEAR/span/boost/slop/`AT LEAST n OF` 等）——文法收窄 + V3005 是刻意设计（fit §3）。
4. **`decisions.question` 切任何非默认形态**——ASCII CHECK（`v13_core.sql:398-399`）永不切换（结案 `:29`）。
5. **`score()` / `score_stop_words auto:zh` 生产调谐**——维持显式不做。不另立当前评估子计划。评估集不存在。重开条件四句，顺序不可跳：① 先有真实过滤语义下的标注查询集；② 再定义 recall 排名指标和 mgraph 融合结果指标；③ 在 shadow/临时索引上比较 `full_score` 与 `score`，不能直接改生产动态 SQL；④ 评估证明收益，且能给 K/P/Q 增加分值或排序兜底 gate 之后，才允许另立实施计划。在那之前不改三处 `full_score`，不设 `score_stop_words`，不改 P0 动态 SQL。百行夹具不满足第 ① 句。语料量级跃升单独不够。
6. **GUC/段调优落地**（`write_buffer_*` / `max_merge_docs` / `merge_tier_factor` / autovacuum 参数进 SQL）——v13 量级无收益对象（H9），F13 钉默认值是有意现状；建议只进 runbook（U2a），夹具库不执行。
7. **`shared_preload_libraries='stannum'` / `wal_rmgr_id` / standby 面**——pg-agent 不预加载、无 standby；V8/V9 已钉未预加载；升级动作在 pgembed 仓库（fit 自由发现 8）。
8. **把 `index_stats` 塞进 `v13_verify_chunks` 或任何 verify JSON**——改变 checks 形状，使用核查 C.4 明令禁止。U1c 同样禁止。
9. **给 `v13_transcript_recall` 发明生产调用方 / 给 decisions 索引发明检索消费者**——使用核查 C.4 明令；机制不做是设计（`v13_memory.sql:158-161`）。
10. **为新函数发明新 SQL 文件**——R2/G1/H6 位置敏感（H5）。新函数就地放入既有收敛文件。

## 5. 风险与回退汇总

| 里程碑 | 主要风险 | 回滚 |
|---|---|---|
| U1a | 无 gate 面。若用总括 try/except 或按引号切 `n_terms`，demo 基线是假的 | 单提交 revert |
| U1b | ACL 迁移：只删 GRANT 不撤存量权限，重载后 recall 仍可进入 candidates，R8a 仍报 `entities_of`。缓解：显式 REVOKE + R8c。R8a 若仍匹配 `entities_of` 或匹配整句英文，会假红或假绿。改 `v13_mgraph.sql` 失配 assembly `PREFIX_FREEZE`，同提交重钉，不宽化 | 单提交 revert。恢复的是「入口可执行、内部仍失败」，不是可用读环 |
| U1c | 误改 P9 的 decisions 扫描（`question ==>` / `ix_decisions_question_stannum` 只许 memory）会翻已交付绿 gate，或把「名字只许出现在一函数」推广到 chunks 而误红。新函数漏 REVOKE 则 recall 的 42501 断言红——这是抓住漏撤的手段，不是额外故障。ShareLock：深度 verify 可能堵住写维护；只手动、低峰、取消即释放、错误不吞。误挂 cron 时，chunks/memory 的 job 计数断言看不见 mgraph 库的新 job，必须靠本里程碑自己的 cron 断言。冻结哈希同 U1b，再钉一次 | 单提交 revert（DROP FUNCTION）。零数据面 |
| U2a | 纯文档。把 `index_health` 写成硬编码 owner-only，或写会过期的 documents/pages 数字 | revert |
| U2b | 5 参 field 形式或 4 参 text 形式充当这条锁会锁错东西。纯拉丁夹具在 jieba 下假绿。`bind_query` 直调若不可行，硬钉会误红。缓解：CJK 夹具、4 参 `indexed_query`、scratch + `[info]` 再钉 | 删 P5b revert |
| U3 链 | 本文件不承担实现。排序风险：U3c 与 U3b 并行在飞；U3a 已在飞时抢开 U3c，测量白做；U3b 消费 pre-jieba 证据。只有未来 U3c 承担 REINDEX 级迁移 | 不适用本文件 |

全局回退：U1/U2 不改生产索引 reloption、不改表数据、不改既有检索函数体 → **无 REINDEX、无数据迁移**。全部单提交 revert 可解。REINDEX 只属于未来的 U3c。

### 5.1 按里程碑回归矩阵

不要把同一组八命令复制到每个里程碑。使用核查 C.5 的八命令是为「不改任何 `v13_*.sql`」设计的（该节写明改了 SQL 就超出该设计）。U1b/U1c 改了 SQL，单提交回归用三件套；八命令留到总集成，并补上会装载 `v13_mgraph.sql` 的后 stage。

`test_stannum_usage.py` 与 `test_mgraph.py` 共用 `agent_v13_mgraph`，禁并行。

| 里程碑 | 必跑 |
|---|---|
| U1a | `demo_v13/mem2_observe.py`、`demo_v13/memdrive_phase2.py`，可丢弃库。人工核对 OR 形、OR 段数、候选数。不跑八命令。不提交生成日志 |
| U1b | 三件套，串行：`uv run python v13/mgraph/test_stannum_usage.py`；`uv run python v13/mgraph/test_mgraph.py`；`uv run python v13/mgraph_assembly/test_mgraph_assembly.py`。assembly 必跑，因为 `PREFIX_FREEZE` |
| U1c | 同上三件套，串行。usage 与 mgraph 不并行 |
| U2a | 无运行 gate |
| U2b | `uv run python v13/mgraph/test_stannum_usage.py`。只改测试，不要求重跑全部生产 stage |
| U1/U2 总集成 | 下面八命令，再加 assembly / control / spawn / fanout / triage。共用库的脚本串行 |

八命令（使用核查 C.5）：

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

后 stage（U1b/U1c 改了会被这些库装载的 SQL；总集成时跑，不代替上面的单提交三件套）：

```bash
uv run python v13/mgraph_assembly/test_mgraph_assembly.py
uv run python v13/control/test_control.py
uv run python v13/spawn/test_spawn.py
uv run python v13/fanout/test_fanout.py
uv run python v13/triage/test_triage.py
```

提交前若 grep 到 `v13/**/test_*.py` 里还有 `v13_mgraph_candidates` 的 GRANT/`proacl` 快照，把那个测试加进对应里程碑的回归。不把「全量 v13 gate」写成每个里程碑的合同。

## 6. 裁决记录

2026-09-26 已裁。不再保留待选项。相对原稿推荐，两处被推翻：B12 从甲改为乙；jieba 从保守序改为逃逸口生效。

| # | 项 | 最终裁决 |
|---|---|---|
| 1 | B12 | **乙。** 删除 `v13_mgraph.sql:1211-1212`；显式 `REVOKE EXECUTE ON FUNCTION v13_mgraph_candidates(uuid,text,int) FROM v13_recall`，使存量库重载收敛。保留 resolve 的既有 GRANT 与 PUBLIC 的既有 REVOKE。不改四个帮助函数的 ACL。甲移入被拒（无 recall 消费者，扩大权限面）。丙移入触发式后续（真有 recall 侧调用方时，与整条 INVOKER 闭包同一提交再裁）。回滚不恢复可用读环 |
| 2 | jieba 时机 | **逃逸口生效。** U3c 子计划可在 U1/U2 与 U2b 全绿落盘后起草，不必等 U3a/U3b。若 U3a 已在飞，先等其落盘再开 U3c。U3c 与 U3b 永不并行在飞。U3a 证据必须绑定测量时 commit 与 tokenizer 形态。本文件不写 OQ15 重开句，由 U3c 子计划动笔时自写。少数意见（kimi，不采纳，留痕）：维持保守序（测量→路由计划→jieba），并把动笔触发器钉为「U3a 落盘且 §8 三条至少一条未满足」 |
| 3 | U2b | **先行。** unicode 现状锁单独提交。4 参 `indexed_query` highlight，夹具必须含 CJK。不折进 U3c；U3c 扩展 P5b |
| 4 | 候选⑤ | **维持显式不做。** 不另立评估子计划。重开见 §4-5 四句 |
| 5 | verify 范围 | **仅 `ix_memory_nodes_stannum`。** 不变量：每个生产 stannum 索引恰一个 verify wrapper。不按 DP9 `:66`「两索引」重复挂接，不发明索引 |

## 7. 三分钟摘要

**结论**：v13 已经把 stannum 0.4.0 的不变交集用满（H8）。明星新能力在四张单列文本表上零落点。充分发挥是补漏、上锁、排序。五项已裁，本文件可执行。

**后续实施（五个小提交，不是本文件的提交）**：修 demo 两处 bug——走 `v13_mgraph_anchor_tinql` 实路径，空锚记 0，`n_terms` 按 ` OR ` 段数，不吞 V3005。B12 **已裁乙**（原稿推荐甲，本裁决推翻）：删死授权并显式 REVOKE，不补四个帮助函数。给 `ix_memory_nodes_stannum` 补唯一的生产 verify wrapper，不挂 cron，不重复挂接已有索引。runbook 写清 `index_health` 的权限和 autovacuum 只是生产化参考。P5b 先行，把「spans 与索引切分碰巧一致」变成执法；夹具用 `東京タワー`，不用拉丁词充数。

**排队什么（本文件不动笔）**：jieba 整包可以在 U2b 全绿后另立子计划，**不必再等测量和路由**——这是第二处推翻（原稿推荐保守序）。不得与路由计划并行；U3a 若已在飞则先等它落盘。路由计划仍要等三条「已满足」且证据对得上目标 commit。两份重开句都由各自子计划正文自写，本文件不写。

**明确不做什么**：多列/BM25F、`search()` 替换、TINQL 拓宽、`decisions.question`、score 调谐（四句重开条件未满足就不另立评估计划）、GUC 落地。

## 8. 实施顺序

1. **更新本利用方案**，把五项选择写成裁决并消掉二选一。本修订即该步。
2. **U1a 原子提交**：两个 demo 文件。跑两脚本，不提交生成日志，不回改日期化调查文档。
3. **U1b 原子提交**：显式 REVOKE、改 R8a、新增 R8c、更新 mgraph README、重钉 `PREFIX_FREEZE["v13_mgraph.sql"]`。跑 usage、mgraph、mgraph_assembly，串行。
4. **U1c 原子提交**：新增 owner-only verify wrapper、覆盖映射 / 权限 / 无 cron gate、README、再次重钉冻结哈希。重复三件套。不与 U1b 合并。
5. **U2a 独立文档提交**：只改 characterize README。可提前到与 U1a 并行，不得并进第 3、4 步。
6. **U2b 原子提交**：scratch 验证后新增 P5b 和 README 状态。跑 usage gate。
7. **U1/U2 总集成**：§5.1 的八命令加 assembly/control/spawn/fanout/triage。共用库的脚本串行。
8. **U2b 全绿后另立 U3c 子计划并按整包实施。** 不必等 U3b，也不必等尚未开工的 U3a。若 U3a 已在飞，先等其落盘再开 U3c。U3c 与 U3b 永不并行。动笔时自写 OQ15 重开句；本文件不写。
9. **U3a 在明确 commit 上测量**，文书写明 tokenizer 形态。只有三条均「已满足」且证据与目标代码基线一致时，才允许另立 U3b。U3c 若落在某次测量之后，依赖锚/候选/walk 的项目在新 HEAD 复测；U3b 不得消费过期证据。

## 9. 文件级影响

| 文件 | 后续实施内容 | 依赖/顺序 |
|---|---|---|
| `docs/plans/v13-stannum-0.4-utilization-plan-2026-09-26.md` | 五项裁决、里程碑合同、回归矩阵。本修订已写入 | 最先；已完成 |
| `demo_v13/memdrive_phase2.py` | candidates 输入改为 anchor OR 形；空锚记 0、不调用 | U1a |
| `demo_v13/mem2_observe.py` | `n_terms` 按 ` OR ` 段数 | 与上一文件同一 U1a 提交 |
| `v13/mgraph/v13_mgraph.sql` | U1b 删除 `:1211-1212` 并显式 REVOKE；U1c 另提交新增 verify wrapper 与 PUBLIC REVOKE | 两个独立提交，不合并 |
| `v13/mgraph/test_stannum_usage.py` | U1b 改 R8a、新增 R8c；U1c 改 P9/P11、新增 wrapper/cron/42501 断言；U2b 新增 P5b | 随各里程碑原子提交，禁并行分支 |
| `v13/mgraph/README.md` | B12 乙、verify 覆盖映射、P5b 状态 | 分别随 U1b / U1c / U2b |
| `v13/mgraph_assembly/test_mgraph_assembly.py` | 只重钉 `PREFIX_FREEZE["v13_mgraph.sql"]`，不宽化比较式，不改断言逻辑 | U1b 一次，U1c 再一次 |
| `v13/mgraph_assembly/README.md` | 第 9 条现不引用 B12/verify。未引用则不改 | 核对即可 |
| `v13/characterize/README.md` | U2a 权限、生产化参考、调试入口 | 独立纯文档提交 |
| `v13/load.py` | **不改** | 保持位置敏感计数 |
| 12 个 `v13/*/setup_db.py` 与三份 `demo_v13/setup_db*.py` | **不改** | R21 保持原样 |
| `v13/mgraph/test_mgraph.py` | U1/U2 **不改**断言，只跑回归 | 不碰冻结 G6/route 面 |
| 日期化 investigation/closeout 文档 | **不回改** | 保持历史证据快照 |
