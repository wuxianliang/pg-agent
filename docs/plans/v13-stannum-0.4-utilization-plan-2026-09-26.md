# v13 充分发挥 stannum 0.4.0 —— 利用方案计划（2026-09-26）

> 纯设计任务。本计划落盘即完成；不改任何代码/SQL/测试，不跑 gate。
> 输入：能力面档案 `docs/investigations/v13-stannum-0.4-capability-dossier-2026-09-26.md`、适配面档案 `docs/investigations/v13-stannum-0.4-fit-dossier-2026-09-26.md`、使用核查 `docs/investigations/v13-stannum-usage-audit-2026-09-26.md`、结案 `docs/plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md`、M3-stop `docs/investigations/v13-m3-stop-why-and-how-to-advance-2026-09-25.md`。引用一律 `文件:行`。

## 0. 执行索引

- §1 定位与边界：本计划是什么、不推翻的硬事实、冻结面。
- §2 候选方案枚举与评估：八个候选（①–⑧），逐个给价值/成本/风险/会翻的 gate/依赖与排序/裁决形式。
- §3 最佳方案：组合 = ②+③runbook 面+④+⑧（本计划交付面，U1/U2）+ ①（后续子计划 U3c，排序钉死）。每里程碑给 gate 设计、收尾工件、回滚。
- §4 显式不做清单（防未来重复提案）。
- §5 风险与回退汇总。
- §6 用户拍板点汇总。
- §7 给用户的三分钟摘要。

## 1. 定位与边界

### 1.1 本计划是什么 / 不是什么

本计划回答一个问题：**v13 在 stannum 0.4.0（pgembed pin `ad4d3b7`，`pgembed/pgbuild/Makefile:278`）上，还有哪些已交付能力没接满、哪些 0.4.0 新能力值得采纳、按什么顺序落地。**

本计划**不是**：

- 不是 jieba 整包的实施计划（那是后续子计划 U3c，见 §3.4）；
- 不是 CJK 路由重开计划（U3b，条件触发，见 §3.4）；
- 不是 §8 三条触发的测量文书（U3a，只读，见 §3.4）；
- 不是重开文书。本计划**不写** `supersedes OQ15`，也**不写** `supersedes DP9-OQ3`；凡涉及 M4/jieba 的阶段，形式要求见 §3.4。

测量/路由/jieba 的实际工作**不排进本计划交付面**，它们是后续子计划；本计划只做候选评估、组合裁决、排序与约束钉死（任务边界）。

### 1.2 不推翻的硬事实（档案已证，直接采用）

| # | 事实 | 证据 |
|---|---|---|
| H1 | 四张被索引表（chunks/transcript_chunks/memory_nodes/decisions）各只有一列自由文本；多列/`field_weights`/BM25F/LSG4/5 参 field highlight 在当前 schema **零落点**；加第二文本列属 M5 事件门，结案明令不发明 | fit 档案 §1 表与「天然单文本列」注（`docs/investigations/v13-stannum-0.4-pgembed-adaptation-2026-09-25.md:156-163`）；结案 `:36` |
| H2 | `search()`/`search_count()` 替换三段式已裁否决：无过滤参数，「先 top-k 后过滤」≠ v13 的「过滤后 top-k」 | fit 档案 §2；适配调查 `:93-103` |
| H3 | transcript_chunks 中英混排、memory_nodes 纯中文 → jieba 是 0.4.0 时代对 v13 真实收益最大的一项；但 M4 有整包先决 + 须计划正文自写 `supersedes OQ15` | 结案 `:28-32`；jieba 探针 §9（`docs/investigations/v13-jieba-canary-probe-2026-09-25.md:391-405`） |
| H4 | 已交付的 65 断言 usage gate（`v13/mgraph/test_stannum_usage.py`，`e6fe89b`）把「零采用」钉成断言：F4 `:983-1018`、F5 `:1012-1018`、F8 `:1031-1033`、V8/V9 `:633-635`、F13 `:1063-1082` 等；任何采纳必须同提交同步这些断言 | 能力档案附录「现存 gate 冲突点」 |
| H5 | R2/G1/H6 的 `files_through` 源码计数是**位置敏感**的；新增 SQL 文件进 `v13/load.py` 会使前 8/9 个文件位置右移，R2（`test_characterize.py:840-860`）/G1（`test_recall.py:1063-1072`）/H6（`test_filter.py:2544-2547`）全红 | fit 档案「自由发现 2」 |
| H6 | B12：`GRANT EXECUTE ON v13_mgraph_candidates TO v13_recall`（`v13/mgraph/v13_mgraph.sql:1211-1212`）是死授权——INVOKER 链内部依赖（`entities_of`/`entities`/`keywords_of`/`jaccard`）只授 `v13_resolve`（`:1204-1209`），`v13_recall` 直调 42501；R8a/R8b 只锁现状（`test_stannum_usage.py:1125-1131`） | fit 档案 §6；使用核查 B.12 |
| H7 | `ix_memory_nodes_stannum`（`v13_mgraph.sql:49`）被检索但无生产 verify；DP9 计划原文要求 `v13_verify_mgraph` 含 `stannum.verify_index` findings=0 | 使用核查 B.2；`docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md:66` |
| H8 | 0.4.0 行为差异对现有 gate 风险 ≈ 0：v13 调用面（单列、无 `field_weights`、4 参 `highlight`、1 参 `full_score`、text/text `==>`、无字段组 tinql）落在「0.4.0 未改动交集」里 | fit 档案 §9 全表与净结论 |
| H9 | 生产表全部 < 100 行夹具尺度，规划器断言靠 `enable_seqscan=off`；段调优/GUC 调谐在 v13 量级下无实测收益对象 | fit 档案 §1 夹具行数段 |
| H10 | `v13_verify_memory` 的挂法先例 = 手动可调 + gate、owner-only、**不挂 cron**（`v13/memory/v13_memory.sql:163-164`）；cron 计数有断言（chunks 恰一条 `test_chunks.py:1107-1109`、memory 恰两条 `test_memory.py:696-699`） | fit 档案 §5 |

### 1.3 冻结面（本计划及后续子计划均不得触碰，除非该子计划自写对应 supersede）

- `v13_mgraph_route`、E2（`test_mgraph.py:1606-1614`）、G9 闭集（`:2792-2797,:2825-2828`）——受 DP9-OQ3 保护，重开须自写 `supersedes DP9-OQ3`（结案 `:24`；M3-stop `:102-113` 十行之 1/8）。
- `v13_mgraph_anchor_terms` 的 CJK 3-gram 分支（`v13_mgraph.sql:3230-3237`）、L3（`test_characterize.py:495-503`）、G6（`test_mgraph.py:2723-2757`）、生产索引 tokenizer——受 OQ15/结案 `:28-32` 保护，重开须自写 `supersedes OQ15`。
- `decisions.question` 的 ASCII CHECK（`v13/schema/v13_core.sql:398-399`）——三份文档共同引用的不变量，**永不切换**（结案 `:29`）。
- 冻结的 `v13_query_segments`（`v13/recall/v13_recall.sql:13,70-72`）——任何计划不得编辑（M3-stop 十行之 7）。

## 2. 候选方案枚举与评估

八个候选。每个给：价值 / 成本 / 风险 / 会翻的 gate / 依赖与排序 / 裁决形式。

### ① jieba 整包（M4）

- **价值**：0.4.0 时代对 v13 收益最大的一项（H3）。jieba 把中文按词切（`开源数据库` → 2 term 而非 4 单字，能力档案 §9）；memory_nodes 纯中文、transcript_chunks 中英混排（fit §1 语言形态表）；锚从字符 3-gram 滑窗升为词级，锚池语义精度上一个台阶；L3 的单字片假名 miss 反转为命中（过召回）。
- **成本**：一次提交四件（结案 `:32`）：词级锚 + L3 重写（不放宽、禁 OR 宽化）+ 新 highlight 绑定断言 + G6 同提交重写；生产索引 chunks/transcript_chunks/memory_nodes 切 `tokenizer='jieba'`（REINDEX 级）；词典治理进 runbook（探针 §9.7）。运行成本：首查约 100–200 ms 词典加载 + 数 MB~95 MB RSS（探针实测 `:275`）。
- **风险**：3-gram OR 在 jieba 上 7/7 全灭（探针 `:157-168`）→ 不改锚 G6 必红；四时刻不对称（列变量 highlight 跟索引 tokenizer，`v13_extract_spans` 4 参 text 重载走默认 unicode，探针 `:221`）→ 不改 extract_spans 调用形状则「召回有、spans 空」；jieba-rs crate 升级必须 REINDEX（能力档案 §9）；自定义词典非空时自定义扫描拒绝并行 worker。
- **会翻的 gate**：L3（`test_characterize.py:495-503`，单字片假名 miss 断言翻红）；G6 三件（`test_mgraph.py:2723-2757`，`count(*)=1` 变 0）；usage gate P12（reloptions 不再无 tokenizer）/F6（jieba 进生产索引）；若拆新 SQL 文件则 R2/G1/H6 位置计数全翻（H5）。
- **依赖与排序**：M3-stop 文书顺序 = 测量 → 路由计划 → jieba 整包（`:152-157` 之 3：路由计划若落地，jieba 排在其后，避免两线同改 `test_mgraph.py`；测量不是 jieba 前置）。排序论证见 §3.0。
- **裁决形式**：**须后续子计划正文自写 `supersedes OQ15`**（结案 `:24/:28` 的形式要求；本计划不写该短语）；go/no-go 时机留用户拍板（§6-2）。

### ② 结构性补洞：B12 裁决落地 + `ix_memory_nodes_stannum` 生产 verify

- **价值**：消两个「名义有、实际无」的合规面缺口（H6/H7）。B12 让「M3 读环锚复用」授权从死变活或从账上移除；verify 补洞让图索引损坏能进 verify 报告（今天全树 `verify_index` 只有 characterize 一处 + memory 两处，mgraph 零）。
- **成本**：小。B12 三选一（甲：补内部授权四函数给 `v13_recall`；乙：移除 `:1211-1212` 死授权；丙：落地以 `v13_recall` 执行的读环调用方，最贵）。verify 补洞 = 在既有收敛文件 `v13_mgraph.sql` 内新增 owner-only 函数 `v13_verify_mgraph`（照 `v13_verify_memory` 形，`v13_memory.sql:163-206,245-247`），不挂 cron（H10）。
- **风险**：选甲扩大 recall 角色权限面（四函数入读环授权）；选丙发明新读环面，超出「补洞」本义；verify 函数新增若挂 cron 会翻 cron 计数断言（H10）——不挂即无此险。
- **会翻的 gate**：R8a/R8b（`test_stannum_usage.py:1125-1131`，现状锁，任何 B12 处置都要同提交改）；P9（usage 核查 C.3：「`verify_index` 只许出现在 `v13_verify_memory`」的白名单断言，落地 `v13_verify_mgraph` 要加名）；G6 只数 `==>`（`test_mgraph.py:2726-2727`），`verify_index` 不含 `==>` → 不翻；不新建 SQL 文件 → R2/G1/H6 不翻（H5）。
- **依赖与排序**：无前置，与测量/路由/jieba 链正交（不碰 `test_mgraph.py`/`test_characterize.py`/route/anchor/L3/G6）。
- **裁决形式**：B12 三选一**须用户拍板**（fit §6 原文「待用户裁决」；§6-1）；verify 补洞范围（仅 `ix_memory_nodes_stannum` vs DP9 `:66` 「两索引」原文）执行时核对，建议最小补洞（§6-5）。

### ③ 运维面落地：`index_stats`/`index_health`/段调优 + autovacuum 节奏

- **价值**：把「仅 runbook」的运维面（使用核查 A.3：`index_stats`/`index_health` 生产与 gate 零执行、只在 README）升格为「runbook + 已 gate 化的可用性现状锁」。F9/F10/F11 已钉可用性（`test_stannum_usage.py:1037-1047` 等），增量是 runbook 补缺：`index_health` 必须 owner 视角（fit 自由发现 7：三角色因 canary 无 SELECT 整视图 42501，R14/R15 已实证，README 示例未标明）；autovacuum 节奏建议（`segmented-storage.md:211-219` 的 `vacuum_index_cleanup=auto` + insert threshold 组合）进 README。
- **成本**：小（纯文档 + 既有断言复核）。
- **风险**：过度工程——v13 表 < 100 行（H9），段调优 GUC（`write_buffer_*`/`max_merge_docs`/`merge_tier_factor`）在 v13 量级无实测收益对象；stannum 侧调优证据来自 100k Wikipedia benchmark（`merge-budget.md:137-154`），与 v13 夹具差 3 个数量级。
- **会翻的 gate**：runbook 面零翻。若落会话 GUC → F13（`test_stannum_usage.py:1063-1082` 钉 6 个 GUC 默认值）翻红；若落 `ALTER TABLE ... SET (autovacuum_...)` → 无 `==>`/`stannum.` 计数翻，但属 schema 变更面，需重跑对应 stage 全 gate。
- **依赖与排序**：无前置。
- **裁决形式**：**拆两半裁决**——runbook 增补采纳（U2a）；GUC/段调优**落地**显式不做（§4-6），F13 的现状锁维持。

### ④ highlight 绑定断言（消使用核查 B.5 风险）

- **价值**：B.5——生产路径 `v13_extract_spans` 用 4 参 text `highlight`、参数是 plpgsql 变量不是列（`v13_characterize.sql:59`），`highlight_support` 改写吃不到（能力档案 §3 门槛 9：args[0] 必须是扫描里的裸 Var）；今天 spans 与索引切分一致**只靠「默认参数碰巧等于生产索引默认 reloption」**。一旦生产索引改 tokenizer/`max_token_bytes`/`long_tokens`，召回按索引切、spans 按默认切，静默分裂（jieba 探针已在非默认 tokenizer 上实证分裂，探针 `:221`）。新增断言把这条对齐假设变成执法。
- **成本**：小。`test_stannum_usage.py` 增补一条断言：对 `ix_chunks_stannum` 命中行，比对 `v13_extract_spans` 字节区间与**绑定** highlight（经 `bind_query` 的 `indexed_query` 重载，索引持久化 analyzer）推出的区间；unicode 现状下二者相等（现状锁）。既有 P5（usage 核查 C.3）已钉「extract_spans = 默认参数手工 highlight」，本断言是它的绑定侧补全。
- **风险**：低；新增断言不改既有断言。若未来要改 extract_spans 调用形状则另说（那是 jieba 包内决策，探针 §9.3）。
- **会翻的 gate**：无既有断言翻；usage gate 断言数 65 → 66+，README 指向行（`v13/mgraph/README.md:14`）若写计数需同步（当前只写「核查 stannum 使用」，执行时核对）。
- **依赖与排序**：无前置；且是 jieba 整包第 3 件的机制前置（探针 §9.3「highlight 绑定**先验证再切**」）——unicode 下先把比对机制立起来，jieba 包内再交付 jieba 索引形态。结案 `:32` 的「整包同时交付四件」约束的是包内缺一不可，不禁止机制预存；保守读法（折进 jieba 包）列为用户拍板点（§6-3）。
- **裁决形式**：无需 supersede；先行 or 折进 U3c 留用户拍板。

### ⑤ `score()` / `score_stop_words auto:zh` 相关性调谐评估

- **价值**：现成旋钮——`score()` 的 `dense_ratio` 省略极常见词，`score_stop_words` 接受 `auto:zh` 预设过滤中文打分噪声（能力档案 §9 打分侧、`docs/compatibility.md:177-186`）。
- **成本**：中。v13 全用 `full_score`（三处动态 SQL：`v13_characterize.sql:106`、`v13_memory.sql:151`、`v13_mgraph.sql:753`），而 **`full_score` 永远忽略 `score_stop_words`**——要用此旋钮必须换打分函数，三条动态 SQL 全改 + 索引 reloption 变更。
- **风险**：绝对分值无任何 gate 钉死（README 台账只保有限数值和 `content_hash` 终裁，使用核查 B.8）→ 命中集合静默漂移无兜底；mgraph 侧 BM25 是 `lexical_norm` 融合分量（`v13_mgraph.sql:764-776`）且**没有任何 gate 钉分值**（fit 自由发现 3）→ 分布变化静默改变融合结果。v13 语料 < 100 行（H9），无可测量对象，调谐收益不可证。
- **会翻的 gate**：P0a–P0d（动态 SQL 全文相等断言，`full_score` → `score` 文本变即翻）；P12（reloptions 非 NULL 即翻）；K/P/Q 命中集合有真实翻红风险。
- **依赖与排序**：无硬前置，但收益无证、风险是实的。
- **裁决形式**：**显式不做**（§4-5），留触发条件（语料规模 + 标注评估集）；若用户推翻则需先建评估集再另立子计划（§6-4）。

### ⑥ 多列 / `field_weights` / BM25F / LSG4 / 5 参 field highlight

- **价值**：零落点（H1）。四表各一列自由文本；`field_weights` 单列即报错（`storage/mod.rs:1883`）；5 参 field highlight 的 SUPPORT 改写只在多列索引 + 裸列 Var 下发生（能力档案 §3）。
- **成本**：须先发明第二文本列——M5 事件门，结案 `:36` 明令不发明。
- **风险**：即便有第二列，证据面也薄：唯一实测是 WAND 剪枝率且方向不利（LSG4 剪得更少：112 vs 362 scored，能力档案 §1/§10）；`docs/benchmarks/` 对 `field_weights`/BM25F/LSG4 零命中。
- **会翻的 gate**（若强做）：F4/F5（临时探针表是 `field_weights` 唯一合法落点）、P12、K1、R 组计数全翻。
- **依赖与排序**：M5 事件门，无排期。
- **裁决形式**：**显式不做**（§4-1），结案 Q3=A 已裁；无需 supersede。

### ⑦ TINQL 高级语法拓宽（wildcard/regex/range/fuzzy/NEAR/span/positional/boost/slop/`AT LEAST n OF`）

- **价值**：能力存在（能力档案「被忽略候选 1」），但 v13 的 tinql 文法收窄是**刻意的**：三层文法 + 入口守卫 V3005（`v13_recall.sql:83-119`、`v13_mgraph.sql:3252-3294`），AND 形与 OR 形互斥是设计不变量（fit §3 关键不对称）。
- **成本**：拓宽 = 拆守卫 + 重写两个发射器 + 两个入口守卫的全套断言。
- **风险**：守卫是防注入/防 LLM 自由发挥的第一道墙；词典展开类语法（>1,024 项走保守候选 + recheck）在小语料上无收益。
- **会翻的 gate**：G7（AND 形送 mgraph 必 V3005 的文法断言）、守卫全部断言、R 组计数。
- **裁决形式**：**显式不做**（§4-3）。

### ⑧ demo_v13 两处潜伏 bug 修复

- **价值**：消两处已坐实的 demo 正确性债：
  - `demo_v13/memdrive_phase2.py:168-171`：`v13_build_tinql(body0)`（AND 形）直喂 `v13_mgraph_candidates`——`v13_mgraph_anchor_guard` 只按 `' OR '` 切（`v13_mgraph.sql:3267`）且拒内嵌引号，多段 body 必 V3005；`one()`（`:76-85`）无 try/except。当前未触发只因语料偶然（fit §10）；唯一可查日志（`memtrial/phase2_run.log:3`，2026-09-24 00:48）早于 OQ15 guard 交付，不能作「今天不炸」证据。
  - `demo_v13/mem2_observe.py:156`：`n_terms` 按 `'` 切分，而 anchor tinql 的项是双引号包裹（`"上周五" OR ...`）→ 恒为 1。
  另：jieba 整包落地后 demo 观察面（`tinql_head`/候选数）会变；先修可让 demo 成为 jieba 前后的对照基线。
- **成本**：极小（两处本地修复 + 复跑两脚本人工核对）。
- **风险**：低；demo 检索面无 gate 钉（fit §10：无 `v13_recall`/UI 调用方，parity 目录与 stannum 正交）。
- **会翻的 gate**：无。
- **依赖与排序**：无前置；宜排在 U3c 之前（对照基线）。
- **裁决形式**：无需裁决。

## 3. 最佳方案：组合与里程碑

### 3.0 组合结论与排序论证

**组合 = ②（结构补洞）+ ③runbook 面 + ④（highlight 绑定断言）+ ⑧（demo 修复）为本计划交付面（U1/U2）；①（jieba 整包）保持为后续子计划 U3c，排序钉死在测量文书 U3a 与路由计划 U3b 之后；⑤⑥⑦与 ③的 GUC 落入显式不做清单（§4）。**

一句话理由：v13 的调用面已落在 0.4.0 未改动交集里（H8），0.4.0  headline 能力（多列/BM25F/field highlight）在当前 schema 零落点（H1）；「充分发挥」的真义是**把已经在交付但被漏接的面接满**（B12 死授权、图索引 verify 缺口、highlight 对齐假设、运维 runbook、demo 债），并让唯一真实收益项 jieba 以合法形态（整包 + supersede + 正确排序）进入队列。

**排序**（尊重 M3-stop 文书顺序，不改序）：

```
U1a(demo) ─┐
U1b(B12)   ├─ 本计划交付面（互不依赖，按 AGENTS.md 一里程碑一提交；
U1c(verify)┘  建议序 U1a → U1b → U1c → U2a → U2b）
U2a(runbook)─┘
U2b(highlight 断言)─┘
        ↓
U3a 测量文书（只读子计划）→ U3b 路由计划（条件触发）→ U3c jieba 整包
        └────────── 后续子计划链：本计划只排序与钉约束，不交付其实现 ──────────┘
```

- U1/U2 不触碰测量/路由/jieba 的任何冻结面（§1.3），也不改 `test_mgraph.py`/`test_characterize.py`——与 U3a 可并行，与 U3b/U3c 无文件级冲突（U1b/U1c 只动 `test_stannum_usage.py` 的 R8/P9 与 `v13_mgraph.sql` 尾部新增函数，jieba/路由动的是 `v13_mgraph.sql:1505-1506`/`:3230-3237` 与 `test_mgraph.py`/`test_characterize.py`）。
- U3 链内部严格 测量 → 路由计划 → jieba（M3-stop `:152-157` 之 3：避免两线同改 `test_mgraph.py`；任务书顺序）。
- 记录张力备查：M3-stop `:152` 之 1 说「第一份可写代码的新计划 = jieba 整包」（jieba 不必等测量），之 3 说路由计划若落地则 jieba 排其后。本计划采用任务书裁定的保守序；**逃逸口**：若用户在路由计划未落地时批准 jieba 先行，排序约束自动退化为「jieba 与路由计划不得并行在飞」（§6-2）。

### 3.1 U1a —— demo_v13 两处修复（本计划交付）

| 项 | 内容 |
|---|---|
| 做什么 | 修 `demo_v13/memdrive_phase2.py:168-171`：AND 形改走 `v13_mgraph_anchor_tinql`（或对该 probe 显式标注「AND 形必 V3005」并跳过）；修 `demo_v13/mem2_observe.py:156`：`n_terms` 改按 `"` 切分或数 ` OR ` 段数 |
| gate 设计 | demo 无 gate；验证 = 复跑 `mem2_observe.py` / `memdrive_phase2.py` 两脚本 + 人工核对输出（`n_terms` > 1、candidates_probe 不再 V3005）；顺带确认 `demo_v13/setup_db*.py` 三处 GRANT 副本注释（fit §10）仍与 12 份正本一致（R21 不扫这三份，人工核） |
| 改哪些既有断言 | 无 |
| 收尾工件 | demo_v13 对应 README/日志说明更新一行；台账：fit §10 风险表状态在执行后记「已修」 |
| 回滚 | 单提交 revert；零数据面 |
| 提交边界 | 独立提交，只动 `demo_v13/` |

### 3.2 U1b —— B12 裁决落地（本计划交付；三选一须用户先拍板，§6-1）

| 项 | 内容 |
|---|---|
| 做什么 | 按用户裁决执行三选一：**甲** 把 `v13_mgraph_entities_of`/`entities`/`keywords_of`/`jaccard` 四函数 EXECUTE 授给 `v13_recall`（`v13_mgraph.sql:1204-1212` 区域就地改）；**乙** 删除 `:1211-1212` 死授权并在注释记「读环调用方缺位，授权随调用方落地再授」；**丙** 落地以 `v13_recall` 执行的读环调用方函数（最重，含 `v13_mgraph_anchors`（`:1684`）/`v13_mgraph_transition_score`（`:1802`）授权面） |
| gate 设计 | 同提交改 `test_stannum_usage.py` R8a/R8b（`:1125-1131`）：选甲 → R8a 改断言「成功且行数 ≥ 1」，新增断言钉「授权面仅限这五函数」（`has_function_privilege` 正向 + 对写路径函数如 `v13_mgraph_build` 的反向 false）；选乙 → R8a 改断言错误文本含 `v13_mgraph_candidates`（42501 落在函数本身而非 `entities_of`）；选丙 → R8a 走新调用方断言成功 + 直调 candidates 仍 42501 |
| 改哪些既有断言 | R8a（必改）；R8b（选甲/丙保持绿作对照）；其余不动 |
| 收尾工件 | `v13/mgraph/README.md` 台账更新（B12 处置结果 + 日期）；`v13/load.py` 不动（不新增 SQL 文件，H5） |
| 回滚 | 选甲 → REVOKE + 断言回退（单提交 revert）；选乙 → 恢复授权行；选丙 → DROP 新函数。均为单提交 revert |
| 提交边界 | 独立提交；回归跑使用核查 C.5 的 8 命令清单 |

### 3.3 U1c —— `v13_verify_mgraph`：图索引生产 verify 补洞（本计划交付）

| 项 | 内容 |
|---|---|
| 做什么 | 在 `v13/mgraph/v13_mgraph.sql` 内（**不新建文件**，H5）新增 owner-only 函数 `v13_verify_mgraph`：含 `stannum.verify_index('ix_memory_nodes_stannum', true)` findings=0（最小补洞）；形状照 `v13_verify_memory`（`v13_memory.sql:163-206`）：手动可调 + gate、REVOKE ALL FROM PUBLIC 后不授出（`:245-247` 先例）、**不挂 cron**（H10）。DP9 `:66` 原文「两索引」的执行时核对：其余 stannum 索引已在 `v13_verify_chunks`/`v13_verify_memory` 面内，不重复挂接（§6-5） |
| gate 设计 | 同提交改 `test_stannum_usage.py` P9 白名单：`verify_index` 允许出现位置从「仅 `v13_verify_memory`」扩为「`v13_verify_memory` + `v13_verify_mgraph`」；P11 保持（能校验 ≠ 已接入的区分仍绿）；mgraph 侧新增一条 gate 断言：owner 调 `v13_verify_mgraph` findings=0、recall 角色调 42501（照 R9/R10 形） |
| 改哪些既有断言 | P9（白名单加名）；G6 `==>` 计数不翻（`verify_index` 不含 `==>`，`test_mgraph.py:2726-2727`）；cron 计数断言不翻（不挂 cron）；R21 不翻（owner-only，不动 12 份 GRANT 块与 demo 三副本） |
| 收尾工件 | `v13/mgraph/README.md` verify 台账记「`ix_memory_nodes_stannum` 已入 `v13_verify_mgraph`」；`v13/load.py` 不动 |
| 回滚 | DROP FUNCTION + P9 回退（单提交 revert）；纯增量、零数据面 |
| 提交边界 | 独立提交；回归跑 8 命令清单 |

### 3.4 U2 —— 运维面 runbook + highlight 绑定断言（本计划交付）

**U2a（纯文档提交）**

| 项 | 内容 |
|---|---|
| 做什么 | `v13/characterize/README.md` 增补三条：① `index_health`/`index_stats` 示例标明**必须 owner 视角**（三角色因 canary 无 SELECT 整视图 42501，R14/R15 实证，消 fit 自由发现 7 的 runbook 缺口）；② autovacuum 节奏建议照抄 `segmented-storage.md:211-219` 组合并注明「v13 夹具尺度下非必要，供生产化时参考」（不落 SQL）；③ 调试入口说明：`stannum.tokenize`/`ql_parse`/`maybe_quote` 是排查 tinql 解析的正规入口（现列 ZERO_FUNCS，不做 gate） |
| gate | 无（纯文档） |
| 收尾工件 | README 本身即工件 |
| 回滚 | revert |

**U2b（highlight 绑定断言，单提交）**

| 项 | 内容 |
|---|---|
| 做什么 | `test_stannum_usage.py` 增补断言：对 `ix_chunks_stannum` 命中行，`v13_extract_spans` 字节区间 == 绑定 highlight（`bind_query` 的 `indexed_query` 重载，走索引持久化 analyzer）推出区间。unicode 现状下二者相等——这是**现状锁**，把 B.5 的「默认参数碰巧对齐」变成执法 |
| gate 设计 | 新断言进 mgraph usage gate（65 → 66+）；不动既有 65 条；与 P5（默认参数手工 highlight 比对）并存，分别锁「extract=默认 highlight」与「extract=绑定 highlight」 |
| 改哪些既有断言 | 无 |
| 收尾工件 | `v13/mgraph/README.md:14` 指向行若含计数则同步；README 台账记 B.5 风险状态 = 已锁 |
| 回滚 | 删断言（单提交 revert） |
| 依赖 | 若用户拍板折进 U3c（§6-3），本里程碑取消，断言由 jieba 包按探针 §9.3 交付 |

### 3.5 U3 —— 后续子计划链（本计划只排序与钉约束，**不交付**其实现）

| 子计划 | 触发与前置 | 形式要求（逐字约束） | 与本计划的关系 |
|---|---|---|---|
| **U3a 测量文书**（只读） | 无前置，可随时开工 | 先定义「可遍历」（v2 计划 `:354` 无定义，M3-stop F1），再按 `causes`/`entity`/`contradicts` 分开记；禁止把 2026-09-24 重跑标成①已绿（重跑 `:56` 维持台账）；`caused_by` 不得顶替 `causes`；`edges_used=0` 不得写成已行使（M3-stop 十行之 2/3/4） | 本计划不动笔 |
| **U3b 路由实现计划** | U3a 对 §8 三条各自留下「已满足」的 file:line 才可动笔 | 正文自写 `supersedes DP9-OQ3`；先做 P1-8 只读 script helper（码点五区间与 route `:1493-1498` 同表），不改冻结的 `v13_query_segments`；同提交改 `:1505-1506` 短路、E2（`test_mgraph.py:1606-1614`）、G9 闭集（`:2792-2797,:2825-2828`）（M3-stop 十行之 1/5/6/7/8） | 本计划不动笔、不写该短语 |
| **U3c jieba 整包** | 用户 go/no-go（§6-2）；若 U3b 落地则排其后 | **U3c 子计划动笔时，正文必须自写 `supersedes OQ15`**（结案 `:24/:28` 的形式要求）。**本计划不写该短语；本计划的落盘不构成对 OQ15 的 supersede。** 包内四件缺一不可（结案 `:32`）：词级锚（`v13_mgraph.sql:3230-3237`）、L3 重写不放宽禁 OR 宽化（`test_characterize.py:495-503`）、新 highlight 绑定断言（若 U2b 先行则扩展为 jieba 索引形态）、G6 同提交重写（`test_mgraph.py:2756-2757`）；生产索引与锚一起切；`decisions.question` 不切（`v13_core.sql:398-399`）；不改 route/E2/G9 | 本计划不动笔、不写该短语 |

## 4. 显式不做清单（防未来重复提案）

1. **多列/`field_weights`/BM25F/LSG4/5 参 field highlight 生产化**——四表各一列自由文本，零落点（H1）；加列是 M5 事件门，结案 `:36` 明令不发明。
2. **`search()`/`search_count()` 替换三段式**——无过滤参数，「先 top-k 后过滤」与 v13「过滤后 top-k」不等义，已裁否决（fit §2；适配调查 `:93-103`）。
3. **TINQL 高级语法拓宽**（wildcard/NEAR/span/boost/slop/`AT LEAST n OF` 等）——文法收窄 + V3005 入口守卫是刻意设计（fit §3），拓宽即拆守卫。
4. **`decisions.question` 切任何非默认形态**——ASCII CHECK（`v13_core.sql:398-399`）是三份文档共同引用的不变量，结案 `:29` 明令永不切换。
5. **`score()`/`score_stop_words auto:zh` 生产调谐**——v13 全用 `full_score`（忽略该 reloption），语料 <100 行无可测量对象，分值漂移无 gate 兜底（fit 自由发现 3）；触发条件：语料规模量级跃升 + 有标注评估集，另立评估子计划。
6. **GUC/段调优落地**（`write_buffer_*`/`max_merge_docs`/`merge_tier_factor`/autovacuum 参数进 SQL）——v13 量级无收益对象（H9），F13 钉默认值是有意现状；建议只进 runbook（U2a）。
7. **`shared_preload_libraries='stannum'`/`wal_rmgr_id`/standby 面**——pg-agent 不预加载、无 standby 拓扑；V8/V9（`test_stannum_usage.py:633-635`）已把未预加载钉成现状；且升级/预加载动作在 pgembed 仓库不在本仓库（fit 自由发现 8）。
8. **把 `index_stats` 塞进 `v13_verify_chunks` 返回 JSON**——改变 version=2 的 checks 形状，使用核查 C.4 明令禁止。
9. **给 `v13_transcript_recall` 发明生产调用方 / 给 decisions 索引发明检索消费者**——使用核查 C.4 明令；机制不做是设计（`v13_memory.sql:158-161` 注释）。
10. **为新函数发明新 SQL 文件**——R2/G1/H6 位置敏感计数是第一堵墙（H5）；新函数就地放入既有收敛文件。

## 5. 风险与回退汇总

| 里程碑 | 主要风险 | 回滚 |
|---|---|---|
| U1a | 无 gate 面；修错只影响 demo 输出 | 单提交 revert |
| U1b | 选甲扩大 recall 权限面；R8a 改判若文本断言写错即红 | 单提交 revert（REVOKE/恢复授权行/DROP 新函数） |
| U1c | P9 白名单漏改即红；误挂 cron 翻三处计数断言（H10） | 单提交 revert（DROP FUNCTION）；零数据面 |
| U2a | 纯文档，数字示例随库重建失效（README 自述性质） | revert |
| U2b | 绑定 highlight 的构造形态若与 extract_spans 哨兵算法不一致则断言误红——执行时先 `[info]` 打印再钉 | 删断言 revert |
| U3 链 | 全部封存在后续子计划；本计划不承担其实现风险 | 不适用 |

全局回退特征：U1/U2 不碰生产索引、不碰 reloption、不碰既有检索函数体 → **无 REINDEX 级回滚**，全部单提交 revert 可解。

## 6. 用户拍板点汇总

| # | 拍板点 | 选项 | 本计划建议 |
|---|---|---|---|
| 1 | **B12 处置**（U1b 前置） | 甲：补内部授权（四函数授 `v13_recall`）；乙：移除死授权 `:1211-1212`；丙：落地 recall 侧读环调用方 | 甲（成本最小、让既有授权名义成实；丙留作读环真正消费时再议） |
| 2 | **jieba go/no-go 时机**（U3c 前置） | 批准动笔 U3c 子计划 / 继续冻结；以及是否在 U3b 未落地时动用逃逸口（§3.0）让 jieba 先行 | 维持排序（测量→路由计划→jieba）；go 时机由用户按价值/成本（§2-①）判断 |
| 3 | **U2b 先行 or 折进 U3c** | U2b 独立先行（机制预存，unicode 现状锁）/ 折进 jieba 整包一次交付 | 先行（探针 §9.3「先验证再切」的字面顺序；结案 `:32` 约束包内四件，不禁止机制预存） |
| 4 | **候选⑤是否推翻** | 维持不做 / 另立评估子计划 | 维持不做（§4-5） |
| 5 | **U1c verify 范围** | 仅 `ix_memory_nodes_stannum` / 按 DP9 `:66`「两索引」原文覆盖 | 最小补洞（仅 mgraph 索引；其余已在 verify 面内） |

## 7. 给用户的三分钟摘要

**结论**：v13 已经把 stannum 0.4.0 的「不变交集」用满（H8），0.4.0 的明星新能力（多列/BM25F/field highlight）在四张单列文本表上零落点——所以「充分发挥」不是追新，而是**补漏 + 上锁 + 排序**。

**做什么（本计划交付面，五个小提交）**：修 demo 两处已坐实的 bug（AND 形误喂 candidates、`n_terms` 恒 1）；裁决 B12 死授权（推荐补内部授权，请您拍板）；给 `ix_memory_nodes_stannum` 补生产 verify（DP9 `:66` 的欠账）；把 `index_health` 的 owner 限制和 autovacuum 建议写进 runbook；新增一条 highlight 绑定断言，把「spans 与索引切分碰巧一致」变成执法。

**排队什么（后续子计划，本计划不动笔）**：测量文书（定义并测 §8 三条）→ 路由计划（须自写 `supersedes DP9-OQ3`）→ jieba 整包（须自写 `supersedes OQ15`，本计划不写该短语）。jieba 是 0.4.0 时代对 v13 唯一真实的大收益（中文词级锚），但整包先决和排序都不能省。

**明确不做什么**：多列/BM25F（无第二文本列，M5 事件门）、`search()` 替换（谓词不等价，已裁）、TINQL 拓宽（收窄是刻意的）、`decisions.question`（永不切）、score 调谐与 GUC 调优（百行语料无可测量对象）。

**需要您拍板五件事**：B12 三选一、jieba go/no-go 时机、highlight 断言先行还是折进 jieba 包、score 调谐维持不做、verify 最小范围。见 §6。
