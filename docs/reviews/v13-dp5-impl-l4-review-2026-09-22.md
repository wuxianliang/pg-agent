# v13 DP5 实现 L4 验收评审（T0 recall + stannum 刻画）

> 评审者：父级 Loop Orchestrate 的 L4 验收代行。`context_builder` `response_type=review` 三路 Oracle：gpt-5.6-sol 完成（PASS-with-notes / 5P1）；grok-4.6 **provider_error 失败**（`ACP protocol violation: session/set_config_option … malformed model metadata`）；claude-fable-5 **失败**（403 weekly usage limit）。按 dp4 / dp2-fix-dp3 先例降级：以 plan 原文 + 两提交源码独立核验为准，不采信未复核的 Oracle 推断；管道故障记入 §7。
> 被审对象：
> 1. `828556f` `v13: add T0 tsvector recall and TINQL compiler`（6 files +2062/−0）vs 父提交 `28b74ea`
> 2. `1ed9837` `v13: add stannum characterize stage and swap T0 recall definitions`（6 files +1196/−0）
> 评审权威：`docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md`（1469 行；§1.1 九处授权换体、§1.3 OQ1–9、§1.4 DP6 七条、§3 SQL 草案、§4 A–R 断言表+扫描归一化公共口径、v2 对齐节 A10/A10b/A10c）。
> 已采信外部事实（控制器独立复跑，本评审不复跑）：九 gate 全绿（recall A–J / characterize K–R + 前序七 gate）exit 0；两提交已推 origin/main；diff 范围恰为两 stage 五件套 + `v13/load.py` +4 行，上游 SQL 零改动。
> 消费面在档：dp4 chunks（`body_tsv` GIN / extract / corpus 八键 / 退役源过滤 / B5mix 垫层）、dp3 manifest（token 键缝）。
> 先例：上轮 dp4 L4 = **PASS-with-notes**（0 P0 / 3 P1 不阻断 / 8 P2），无 P0 即正确性达标，P1 分阻断/不阻断，可开下一 DP。dp5 plan 循环曾因扫描 gate 未定义归一化打回（P1-1）——本轮核落地强度，不把「plan 字面未要求的 EXPLAIN」回溯成 FAIL。
> 评审日：2026-09-22。

## Verdict

| 提交 | Verdict | 一句话 |
|---|---|---|
| **828556f**（M1 recall） | **PASS-with-notes** | 0×P0 / 1×P1（合规不阻断：validator 九键未授权换体）/ 6×P2。T0 函数族、TINQL、cgr 双 bump、九键 freshness、csh 扩集、信封 20 键、ACL 均在场且可证伪 |
| **1ed9837**（M2 characterize） | **PASS-with-notes** | 0×P0 / 3×P1（测试保真不阻断：M 恒真、O/Q 恒真、K4 错面）/ 6×P2。生产单索引 + canary 分叉 + verify v2 + definition 换体机制在场 |

**DP5 整体：PASS-with-notes** —— 0×P0 / 4×P1 / 12×P2。机制可收口，**携 P1 尾债**。父循环 **可以开 DP6**。

不给无 notes 的 PASS：`v13_manifest_validate` 仍未获 §1.1 封闭清单授权（P1-A，dp4 同缝升级为四处）；M2/O2/Q1 含恒真或跳过承重面（P1-B/C）；K4 未咬「结果=被绑索引语义」（P1-D）。不给 FAIL：无 P0；SQL 机制面与 §3 同构（含 count 随引擎换体、三禁 EXECUTE 形态、setup 探针 fail-closed）；G 组归一化按公共口径落地（上轮 plan 打回项已收）；单索引纪律 / cgr / freshness / 候选冻结 / 签名与 ACL 均可证伪。

---

## 1. 两处边界事项裁定

### #1 `v13_manifest_validate` 九键 OR REPLACE — **REJECT（计划合规）/ 保留机制**

**plan 有无明文。** §1.1 封闭清单「共九处」：① `v13_chunks_generation_bump` ② `v13_context_required` ③ `v13_judgment_envelope` ④ `v13_assemble_manifest` ⑤–⑧ recall / recall_count / extract_spans / verify_chunks ⑨ 既有表零 ADD COLUMN / 零新触发器。全文检索清单与 Size 行「换体 4」（第 8 位）均 **不含** validator。

**谱系（四处缝）。** 相对 dp4 P1-A「§1.1 恰两处应改为三处」：

| # | 具身 | 文件 | 键集 |
|---|---|---|---|
| 1 | CREATE 原体 | `v13/manifest/v13_manifest.sql:249-454` | 七键 |
| 2 | 未授权 OR REPLACE（dp4 P1-A） | `v13/chunks/v13_chunks.sql:929-1121` | 八键 + corpus |
| 3 | 未授权 OR REPLACE（本 DP） | `v13/recall/v13_recall.sql:276-484` | 九键 + `recall_ver≥1` |
| — | 授权清单口径 | dp4 ①② + 上表 2 + 上表 3 | **四处** |

第 8 位实际函数语句 = 新 CREATE 6 + OR REPLACE **5**（清单允 4）。多出的恰是 validator。

**树级纪律。** 形态满足（上游文件零改、同签名换体、前缀库不加载 8 号文件）。封闭清单不满足。README 台账①不能替代权威计划授权。

**换体 diff。** 对照八键体：除 `required_revision` 闭集增 `recall_ver` 并校验 `≥1` 外，顶层键集 / policy / replay / sections / query_side / judgments **逐段同构**。无偷偷改校验器其它面。

**为何必须留。** 八键体把 required_revision 钉死不含 `recall_ver`。token 扩第九键后 E1/I2 真实 settle 必 V3003。无此缝则九键 freshness 链路不可达。

**处置：** 保留实现 + **补 plan erratum**（plan 本轮不动，悬置交父循环收尾）。不回滚。升 P1-A（合规，不阻断 dp6）。

### #2 v2 `v13_visible_files` 未实现 — **ACCEPT**

plan v2 对齐节（`:1371-1469`）明文：「不在 `v13/recall/` / `v13/characterize/` 两里程碑另开实现、不改上文 SQL」。当前仍 `FROM chunks … superseded_by IS NULL` 是正确的。A10b 空召回≠仓库无答案只钉出口语义，D4/E5 合法空不弱化。**不记缺口。**

---

## 2. 5 项自报偏差 — 逐项裁定

源 = recall README 台账①②③ + characterize README 台账①②③。I4 编号与 dp4 I4（UTF-8 恒真）**同名不同义**，本表只裁 plan §4 I 组本 DP 条目。

| # | 偏差 | 裁定 | 台账 | 理由 |
|---|---|---|---|---|
| ① | validator 九键 OR REPLACE | **REJECT（合规）/ 保留机制** | recall ① 保留；**须补 plan erratum** | 见边界 #1。自辩「E1/I2 必要缝」事实成立，不能补授权 |
| ② | extract 参数名保留 `p_terms` | **ACCEPT** | characterize ① 足够 | OR REPLACE 不能改输入参数名；签名 `(text,jsonb)` 与输出 `[[b,e],…]` 不变；载荷改 `{"tinql":…}`（`:28-76`） |
| ③ | verify v2 用 `SET enable_seqscan` 代 `set_config` | **ACCEPT** | characterize ② 足够 | 逐字复制 DP4 v1 三路恢复（`:167-182`）。与 dp4 偏差⑦ / dp2 偏差 #4 同口径（避 G-ctx1-5(b) 全树扫描） |
| ④ | I4 用 `active=false` 造无活动行 | **ACCEPT** | recall ③ 足够 | 策略行 append-only 禁 DELETE；`no active recall_k policy` 与 asm_ver 同姿势（`test_recall.py:1166-1171`）；pgcode `P0001` 因复制体 RAISE 无 ERRCODE——墓碑纪律，不升偏差 |
| ⑤ | CJK `full_score` 可 >1，P2 钉英文 `[0,1]` | **ACCEPT 引擎事实 / P2 文档** | characterize ③ 部分足够 | 排序契约不依赖上界。但同 README Q 表英文式 size 查询 2K 起均值已 >1（`:48-55`），与「英文 ∈[0,1]」并立矛盾——见 P2-7 |
| 附 | 信封 `NULLIF(current_setting(…),'')` | **ACCEPT** | recall ② 足够 | 机械复制 DP2 加载态，优于草案裸 `current_setting`（`v13_recall.sql:533`） |

---

## 3. SQL 对 §3 忠实度

| 面 | 裁定 | 证据 |
|---|---|---|
| 第 8/9 位纯末尾追加、前缀切片 | **通过** | `v13/load.py:18-39`；I1 `files_through` 7/8 + chunks 库无 `v13_recall` |
| T0 recall/count 纯 SELECT、确定性终裁、退役源 JOIN | **通过** | `v13_recall.sql:121-171`：`body_tsv @@` + `ts_rank` + `ORDER BY 2 DESC, 1 ASC` + `superseded_by IS NULL` |
| 第 8 位三禁 / 零 `stannum.` | **通过** | G1/R2 归一化后 1–8 号 `==>`=0、`stannum.`=0；file8 原始同零 |
| TINQL 三层构造器 | **通过** | segments/build/terms（`:13-120`）；OQ7 引号 AND 文法；A1–A7 含注入族与 A6 异形（裸词 / `"a" OR "b"` / 未闭合 / 段内引号 / NULL） |
| 回析「自产文法」 | **按 plan 字面通过** | OQ7/A6 定义 = 引号段 + ` AND ` 分隔，不是内文 latin/CJK 字符类。Oracle 将 `"a OR b"` 单段可过升 P1 → **驳回**（见 §7） |
| cgr 双 bump（DP1 #59） | **通过** | `v13_recall.sql:219-227` 同函数两条 UPDATE；F1 驱动器 + owner 直插均双计数 |
| token 第九键 `recall_ver` | **通过** | `v13_context_required`（`:229-274`）；I2 八→九失配；I3 bump→fresh=false |
| csh = needed∪recall、信封 candidates | **通过** | MATERIALIZED `rc` + `digest({'needed','recall'})` + 第 20 键（`:521-558`）；D1 20 键恰等 |
| 装配真候选四键 + 显式 ORDER BY | **通过** | qside ← `v13_recall_candidates` ‖ `decision_id:NULL`（`:723-733`） |
| recall/count v2 同步换体（OQ4 附则） | **通过** | `RETURN QUERY EXECUTE` / `EXECUTE … INTO`，串内 `==>` + `USING` 参数化（`v13_characterize.sql:78-128`） |
| extract v2 哨兵 highlight | **机制通过** | 四对哨兵、字节换算、上限 256、全冲突 V3005（`:28-76`）。测试交面见 §4 P |
| verify v2 第八项 | **通过** | version=2、八项、`stannum.verify_index`（`:130-218`）；N3 正负向可红 |
| 单生产索引 + 独立 canary | **通过** | `ix_chunks_stannum` 默认零 WITH；`v13_canary_docs` + split/64B（`:12-26`）；R1 计数 |
| setup 探针 fail-closed | **通过** | `setup_db.py:21-33`：`pg_available_extensions` 无名 `SystemExit(1)`，无降级 |
| ACL / 纸面 BEGIN-COMMIT | **通过** | 六新函数 REVOKE PUBLIC、三角色 EXECUTE、resolve/route SELECT 三表（`:754-761`）；两文件 BEGIN/COMMIT。无 DP3 式 `$$` 配平 gate（P2） |
| §1.1 授权换体封闭性 | **不通过：额外 validator** | 见边界 #1 |
| `v_tmo` 校验但不 SET timeout | **按 OQ5 通过** | #60 执法在驱动层；README 运维契约在场；无 gate 执法（P2） |

---

## 4. A–R 断言强度

标准：1:1 真实可红；无恒真 / covered-by / 伪链路。

### 4.1 828556f · A–J

| 组 | 裁定 |
|---|---|
| A | **通过**。A2/A3 形状恰等；A4 往返；A5 注入构造性逐字；A6 上限 + 回析异形均 V3005。不是恒真 |
| B | **通过-with-note**。B1 命中集恰等 `body_tsv @@ phraseto` 直查（plan 字面，非顺扫绿的命中证明）；hash/spans 字节对照在场。B1 **未** EXPLAIN GIN——plan B 表不要求（K1 才钉形状）；`@@` 同谓词顺扫也会绿。T0 GIN 可用性已由 dp4 F 组在场。B2 tie 截断包在 `if scores equal` 内，不等则跳过（P2）。B3 CJK 子串零命中真实。B4 退役源仍在盘 + JOIN 过滤（B5mix 读侧）真实。B5 负向 V3005。B6 两 corpus 不串 |
| C | **通过**。C1 matched=3/k=8；C2 400→k=20；C3 4000→k=64；C4 翻版 k=16 + 形状族 V3005。C2/C3 体积 fixture 直调 `v13_ingest_document` 非四步驱动（P2 实务，投影函数仍真） |
| D | **通过-with-note**。D1 20 键 / 19 保留真实。D2 摄取前后 csh 漂移真实。D3「旧信封不变」断言的是 Python 对象未变（恒真半边）；新 parse 候选移动是真的。D4 空 goal。D5 信封不含 TINQL 串 |
| E | **通过-with-note**。E1 `parse→advance waiting→claim→v13_refresh_context` 真链路；四键 + validator。E2「双跑」= 再读同一 active artifact（非两次装配）。E4 新文档路径允许 `candidates 变 OR required_revision 变`（只 token 变也绿）。E5 空候选合法。`check("E1: validator ok", True)` 是「SELECT 未抛」的写法，承重在 SQL |
| F | **通过**。F1 驱动器摄取双 bump + **owner 直插**双 bump（语句级触发器任何路径）。F2 parse 快照→ingest 提交→`v13_advance`==`'stale'`→重 parse 直通 + 无摄取基线。F3 九键下 G2 同型。F4 tools INSERT 只 bump revision、needed `CREATE OR REPLACE`（`pg_get_functiondef` 再执行）bump cgr。F5 两连接：ingest 未提交 ∥ advance 步 0 **不阻塞**；∥ settle 无死锁 |
| G | **通过**（上轮 plan 打回项落地）。`strip_sql_comments` 剥 `--` 与嵌套 `/* */`，保留 `'…'` / `$tag$` / `$$` 串；NORM_FIXTURE 自证：注释内 `==>`/`stannum.` 消失、正文 `==>`=2、`stannum.`=1、串内 `-- nc` 不误剥（`test_recall.py:51-57,90-157,1027-1033`）。前 8 号逐文件计数零。G2 `EXECUTE` 后随 `'/$` 不误伤 `GRANT EXECUTE ON`。G3 README 三禁条目 |
| H | **通过**。三角色正向链 + INSERT 负向 `has_table_privilege` + PUBLIC EXECUTE 拒。H4 九键恰等 TOKEN9 |
| I | **主体通过**。I1 前缀 7/8 + chunks 库无函数 / 八键 token（库存在才连）。I2 **真失配**：手写八键 `context_active_revision`→fresh=false→settle 一次→九键 stored。I3 bump `recall_k`→fresh=false 真实；「截断变化」只断言 `len≤16`——sid_i2 的 quasar 命中本就可能 ≤16，**未证 k_max 64→16 的截断差**（P2）。I4 `active=false` RAISE 真实 |
| J | **通过**。J1 matched=4000 / k 恒 64。J2 README 一页账针 |

### 4.2 1ed9837 · K–R

| 组 | 裁定 |
|---|---|
| K | **部分通过（P1-D）**。K1 EXPLAIN FORMAT JSON + `enable_seqscan=off`：Custom Scan / `Stannum Text Search Scan` / `ix_chunks_stannum` / chunks 无 Seq Scan（对内层 `body ==>` 查询，非 `EXPLAIN v13_recall()`——绑定面等价，ACCEPT）。K2 8 连调 + REINDEX 后再命中。K3/L2 默认 comparator 对 64B 块漏召。**K4** 加第二默认索引后只断言 EXPLAIN「恰绑一」，**未执行查询、未断言结果=被绑索引语义（错面）**——plan K4 第二句未落地。**K5** 三路径与 EXECUTE 命中一致（OQ9 实测等价面在）；无 `force_generic_plan`、无计划形态记录（P2） |
| L | **通过**。L1 64B 精确块命中 doc 1 + EXPLAIN 绑 `ix_v13_canary`。L2 默认 comparator 漏召。L3 「東京タワー」短语命中 / 单字「タ」miss。索引真生效，不是纸面 canary |
| M | **部分通过（P1-B）**。M1 打了两段 500 次 INSERT 的 p99 数字，但 **`mutable_ok` 从未被 `check`**；未观测到 mutable 段仍绿。M2 `check("segment_info readable", True, info1)`：**恒真**；`segment_info` 不存在或抛错则整枝跳过。M3 `count(*) > 0` 而非 plan「fold 后 count==插入数」 |
| N | **通过**。N1 两索引 verify 零 error/warning。N2 REINDEX 后 recall + verify 复绿。N3 version=2、八项、第八项 detail、制造不可解析引用→`reference_resolvable` 红 + `p_raise` V3004。N4 cron 一条或无扩展仍可调 |
| O | **部分通过（P1-C）**。O1 65/200 段 V3005 真。O2 1030 词项 AND 直发 canary：`n_long >= 0` 对成功返回（含 0）**恒真**；无已知命中文档、无「命中集=对照直查」。证明的是「没炸」，不是「无静默漏召」 |
| P | **主体通过-with-note**。P1 命中/排序/双跑/manifest 四键。P2 quasar fixture 英文 `[0,1]`。P3 有数组 + `s≤e` + 哨兵全冲突 V3005；**无人工标注字节对照、未调 `v13_assemble_spans`**（P2）。P4 CJK 短语命中 + count v2>0（相对 T0 零召回的反差在）。P5 空 boosts no-op / 非空 V3005 / token 仍九键。P6 退役源 + cgr 抽样 |
| Q | **部分通过（P1-C）**。6×20 真实摄取并打印表。断言 `hits >= 0` 恒真——召回全空仍绿。查询词放正文**开头**（`:746-748`），与 plan/README「埋中段」不符。`avg_rank` = `1..n` 均值 = `(hits+1)/2`，不是目标词排序位置 |
| R | **主体通过**。R1 chunks 恰一 stannum 索引、canary 恰一、不同表——**生产双索引错绑的结构禁令真咬**。R2 口径同 G1：1–8 零、9 号 `==>` 恰 2 / `stannum.` 恰 3（highlight / full_score / verify_index）；file8/9 原始计数 belt；fixture 复跑。R3 canary owner-only。R4 README 六件。R5 只前缀长度 + recall 冒烟 + 构造器形状，**不是** characterize 库上复跑 A–J / 前序七 gate（控制器已在各自前缀库跑过前序——发布风险低，文案/实现不对齐，P2） |

### 4.3 用户点名咬合点（摘要）

| 点 | 裁定 |
|---|---|
| G 扫描归一化（上轮打回项） | **落地且强**：剥注释 / 嵌套块 / 串内不误剥 / NORM_FIXTURE 自证 / G1 与 R2 同函数同口径 |
| K 绑定矩阵 + R 单索引 | **R1 咬生产禁令**；K4 只咬「恰绑一」，不咬错结果面（P1-D） |
| F cgr 并入 | **真链路**：DML bump + owner 直插 + parse→ingest→stale + needed DDL + 双连接 |
| I 九键 freshness | **I2/I4 真**；I3 bump→fresh=false 真，截断差弱 |
| B T0 是否走 GIN | 命中集 = 同谓词直查（plan B1）；无 EXPLAIN/seqscan off。正确性不依赖 GIN；性能面未钉（P2） |
| L canary | **真生效**（bound 命中 / 默认漏召 / EXPLAIN 绑 canary 索引） |
| N / O / Q | N 强；O2/Q1 恒真（P1-C） |

---

## 5. 修复清单（暂停后下一轮可用）

### P1（不阻断 dp6；建议 dp6 并行或 erratum 先收）

1. **P1-A** plan erratum（plan 不动，本条悬置）：§1.1 九处之外明文授权 `CREATE OR REPLACE FUNCTION v13_manifest_validate` 两次同步换体（八键 corpus / 九键 recall_ver）。权威=plan，不是 README ①。不改 SQL。
2. **P1-B** `test_characterize.py:492-568`：M2 删 `check(..., True, …)`；强制 `segment_info` 观测 mutable 段在场且 generation 递增，未激活则失败或加灌至激活；M3 改为 fold 后 `count(*)==插入数`。
3. **P1-C** O2：1030 词项查询须含已知命中文档，命中集对照直查（零命中要红）。Q1：查询词埋中段；每档断言 hits=20（或明确允许的非零下界）；`avg_rank` 改为目标词在结果中的位次，禁止 `1..n` 自平均；删 `hits >= 0`。
4. **P1-D** K4：EXPLAIN 识别所选 default/split 索引后 **执行** 64B 查询，断言命中/漏召与该索引语义一致（绑 default ⇒ 漏召；绑 split ⇒ 命中 doc 1）；测后 DROP。R1 保持。

### P2（可随 dp6 / README）

5. B1 对 `v13_recall` 内层 `body_tsv @@` 补 `enable_seqscan=off` + EXPLAIN 含 `ix_chunks_tsv`（belt；非 plan 字面欠债）。
6. B2 用必并列 fixture 去掉 `if` 跳过；I3 复用 C4 的 4000 匹配语料断言翻版前后候选数 64→16。
7. D3 冻结改为重读已返回信封对象的持久化副本（或注明「值语义、非再查库」）；E2 两次 `v13_assemble_manifest`；E4 主断言改为新 `content_hash` ∈ 新 candidates。
8. K5 会话 `force_generic_plan` + 记录三路径 EXPLAIN 形态（升级复测项）。
9. P3 人工标注 ASCII/CJK 字节期望 + `v13_assemble_spans` 消费链。
10. README ③ / Q 表：取消全局英文 `[0,1]`；只保证 finite numeric + 哈希终裁。Q 表 2K+ 均值>1 已与「英文 [0,1]」冲突。
11. R5 收窄文案为「冒烟」或在 characterize 库入口复跑 recall gate；parse 驱动 `statement_timeout≤timeout_ms` 加取消结局测试。
12. C2/C3 体积路径在 README 台账「直调 ingest 非四步」；`recall_k` 显式整数 + `k_max≤1024`；可选纸面 `$$` 配平。

### 明确不修 / 已驳回

- 回滚 validator 九键：E1/I2 必断。
- 把 `v13_tinql_terms` 接受 `"a OR b"` 单引号段打成 P1：OQ7/A6 文法即引号+AND，A6 已拒 `"a" OR "b"`。
- 把 B1 无 EXPLAIN 打成 FAIL：plan B1 字面是命中集对照。
- 本 DP 实现 `v13_visible_files`：v2 节禁止。
- 因 `full_score>1` 做截断/归一化。
- 因 `p_terms` 参数名 DROP/重建 extract。
- 把 R1 已立法的单索引再要求生产表双索引常驻。

---

## 6. 可否开 DP6

**可以开。** dp6 消费的本 DP 缝均在场且未被两提交破坏：

| dp6 契约（plan §1.4） | 本两提交状态 |
|---|---|
| ① 信封 `candidates` = parse 时冻结的三键数组；禁重跑 recall | 在场（`v13_recall.sql:521-558`）；D3 新 parse 才换 |
| ② 签名 `(text,int)→三列` 冻结；extract 载荷内部约定 | 在场（v1 `:121` / v2 `:78`）；p_terms 签名不变 |
| ③ SELECT ON chunks/sources/meta 已授 resolve/route | 在场（`:760-761`）；H2/H3 |
| ④ `k_max=64` 结构上界 | 在场（种子 + C3/J1） |
| ⑤ csh 覆盖 needed∪recall | 在场（OQ3 材料）；span_assembly 缝转发未入 token |
| ⑥ span_assembly 版本缝转发 | plan 已保留；本 DP 候选级 spans 不触发 |
| ⑦ 批量引用锁纪律转发 | 本 DP 零多引用写事务；DP4 触发器背板仍在 |

建议顺序：P1-A erratum 与 P1-B/C/D 测试补丁可并行于 dp6 开工；K4 错面最好在任何「第二索引」实验前收。

---

## 7. 方法与 Oracle 分歧

| 来源 | 结果 | 本报告处置 |
|---|---|---|
| Oracle 1（gpt-5.6-sol） | PASS-with-notes；5P1/6P2；可开 dp6 | **采纳** validator 未授权换体、M2 恒真、O2/Q1 弱、K4 缺错面、G 归一化通过、F/I/L/N 真链路、五偏差中 ②③④⑤ ACCEPT。**驳回** 将 `v13_tinql_terms` 未限内文字符类升 P1（plan 文法=引号+AND，A6 已覆盖 `"a" OR "b"`）。**降** P3 无金标为 P2（哨兵负向在场；对照 dp4 I2 含而非精确起止先例）。K5 缺 `force_generic_plan` 落 P2 非并入 P1 |
| Oracle 2（grok-4.6） | **失败**（ACP `set_config_option` malformed model metadata） | 降级：不重试、不采信空结果 |
| Oracle 3（claude-fable-5） | **失败**（403 weekly quota / kimi） | 同降级 |

独立核验：通读 dp5 plan §1.1–1.5 / §3 草案职责 / §4 A–R + 断言纪律归一化口径 / v2 A10 三款；`v13_recall.sql` 构造器/T0/五处 OR REPLACE/ACL；`v13_characterize.sql` 扩展/canary/四换体/verify v2；`test_recall.py` A–J（含 NORM_FIXTURE、F1 owner、F2 stale、I2 八键失配、I4 active=false）；`test_characterize.py` K–R（含 K4 恰绑一、M2 `True`、O2 `>=0`、Q1 `>=0`、R1/R2 计数）；两 README 台账；`load.py` +4；`setup_db.py` 探针；dp4 L4 格式与 P1-A 先例。未复跑测试。

```
