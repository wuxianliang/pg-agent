# v13 mgraph v2 候选发现 + 矛盾通路深度调查(2026-09-24)

**一句话**:在真实栈实测报告两项结构性发现(候选发现休眠、矛盾通路双重不可达)的基础上,本调查给出代码级根因定位、`agent_v13_demo_mem` 活体只读模拟的替代形态数字、四族候选设计+三族矛盾通路设计的可实现性评估、成本/帽触发表、gate 影响清单与 OQ 草案。**核心结论:子句级放宽(OR 全段/miss 比例 AND)仍接不通 T2↔T6(两者零子句交集),必须降到亚子句粒度(CJK n-gram 短语)OR 单查询——「latin 段整 + CJK 3-gram、top_k=5」形态在本转录上以 59 个 ask 接通 T2→T6(rank 4)且不破任何确定性纪律;矛盾通路推荐「词法预筛对源(依赖候选修活)+ rel 族新增本地 contradicts 问(读侧遍历面已就位)」组合。**

- 调查对象:DP9 mgraph 已交付态(提交 6bfe366,M1–M4,352 PASS)。
- 一手证据:`docs/investigations/v13-dp9-mgraph-demo-trial-2026-09-24.md`(真实栈实测)。
- 红线遵守:试验库全程只读(`SET SESSION CHARACTERISTICS READ ONLY`,全部查询为 SELECT);未动 `agent_v13_demo` 原库;未改任何跟踪文件(本报告为唯一新文件);未 git commit。
- 与并行 CJK 路由调查的交集:仅共用 `v13_query_segments`(recall:13,段化器)与读侧锚定结论一处,路由分桶/升权主题不在本文范围。

---

## 1. 现状机制图(代码级)

### 1.1 候选发现链(锚 tinql → 池 → 截断)

| 步 | 机制 | file:line |
|---|---|---|
| ① 段化 | `v13_query_segments`:按书写系统类切 run(latin=连续字母数字、CJK=连续汉字/假名),分隔符(标点/空格)丢弃;≤64 段、每段 ≤256B、全文 ≤4096B | `v13/recall/v13_recall.sql:13-75` |
| ② 锚 tinql | `v13_build_tinql` = **全部段** `"s1" AND "s2" AND …`(去重不塌缩——重复段保留重复度) | `v13/recall/v13_recall.sql:77-81` |
| ③ 文法守卫 | `v13_tinql_terms`:只接受「引号段 AND 连接」文法,其余 V3005 | `v13/recall/v13_recall.sql:83-119` |
| ④ 入口复检 | `v13_mgraph_candidates` 首行调 `v13_tinql_terms(p_tinql)`(fail-closed,设计 §4.1 三禁) | `v13/mgraph/v13_mgraph.sql:730` |
| ⑤ 池查询 | 单条动态 SQL:`WHERE session_id=$1 AND origin='episodic' AND body ==> $2 ORDER BY content_hash ASC`(谓词驱动 stannum 索引扫描;本文件去注释 `==>` 计数=恰 1,实测复核=1) | `v13/mgraph/v13_mgraph.sql:739-750` |
| ⑥ 计分 | `score = lexical_coef·lexical_norm + entity_coef·entity_jaccard + keyword_coef·keyword_coef·keyword_jaccard + candidate_recency_coef·recency`;`lexical_norm = bm25/max(bm25)`(池内归一化);bm25=`stannum.full_score(ctid)`(在 ==> 命中集上) | `v13/mgraph/v13_mgraph.sql:752-764` |
| ⑦ 截断 | `ORDER BY score DESC, content_hash ASC LIMIT p_k`(`candidate_top_k`=10) | `v13/mgraph/v13_mgraph.sql:765-769` |

### 1.2 build 侧配对过滤链(每节点)

锚=该节点 body 全量 tinql(`v13_mgraph.sql:1013`)→ `v13_mgraph_candidates(p_sid, tinql, top_k)`(:1014)→ **自排除在 build 侧**:`IF v_cand.content_hash = v_node.content_hash THEN CONTINUE`(:1016;候选函数本身不排除自身)→ `lexical_norm ≥ graph_activation_threshold(0.15)` 插 proximity 边(structural=lexical_norm,:1017-1024)→ 每 pair 一封关系信封:`v13_mgraph_pair_questions`(:776-809)=基础三问 semantic/causes/caused_by + **entity 闸**(双方实体集非空且无交集才入问,:803-808)→ 三帽复查(spend/batches/asks,:1036-1041)→ resolve。

**每节点信封数公式 = 1(类型封)+ |{c ∈ candidates(top_k) : c ≠ self}| ≤ 1 + top_k = 11**。

### 1.3 固化选对链

`v13_mgraph_cons_pairs`(mgraph:2692-2704):同会话 episodic 按 `source_at ASC, content_hash ASC` 编号,**只枚举相邻对 `b.rn = a.rn + 1`**(与 temporal 边同序;台账 #36)→ 排除仅 `status='adopted'`(consolidate 循环内 :2830-2834)→ 五问一封(redundant/contradiction/obsolete/link 四 Noul + representation choice,signal `mem_cons::<pair_digest>::<aspect>`,`pair_digest = v13_body_hash(src||'>'|| dst)` 有向拼接,:2683-2686)→ 生成门 `v13_mgraph_cons_gate`(:2763-2797):choice∈{merge,promote} ∧ 所选概率 ≥ consolidation_choice_min(0.85)∧ **contradiction < consolidation_threshold(0.85)**(矛盾过阈即使 choice=merge 也不入队,OQ6)。

### 1.4 休眠根因的代码级定位(三层叠加)

1. **段化粒度不对称(根因层)**:`v13_query_segments` 对 latin 按空格切成**单词**段,对 CJK 按标点/系统切换切成**子句**段。英文正文段=`Iris`/`packed`/`van`;中文正文段=`日志复核后实际只有八千用户受影响`(整子句)。stannum 引号段=**有序短语匹配**(活体验证:`"用户受影响"`→3 节点、`"受影响用户"`→2 节点、乱序 `"影响用户受"`→0)。
2. **AND 文法层**:`v13_build_tinql` 把全部段 AND 起来 → 锚查询=「候选必须包含锚的每一个子句」。两条不同消息互不包含对方全部子句 ⇒ AND 命中集={节点自身}。
3. **自排除层**:build :1016 排除自身后配对池恒空。

英文 gate 全绿的原因:D 组夹具全是**词序置换句**(PB1/PB2=`Dana Eric Grace Hope shipped the crate.` 词序互换,D2/D10/D11 同族)——单词级段全交叉包含,AND 恒可中,**休眠在测试面上不可见**。偏差台账 #12 已从同根因推出 mem_rel_entity 写路径结构性不可达(候选 token 集 ⊇ 锚 token 集 ⇒ 实体集交集非空 ⇒ entity 问永不入封)。

矛盾通路双重不可达:①候选休眠 ⇒ T2/T6 从未进同一关系封(mem_rel 四问无 contradicts 成员,本来也问不出);②cons_pairs 只取相邻对,而 T2(位置 3)与 T6(位置 8)相隔 5 位,结构性不可能被选——`contradicts` 边只能由固化子型映射产生且指向**产物节点**(README §21),强矛盾又被生成门反向拦住(≥0.85 不入队)⇒ **更正语义在当前图上没有任何沉淀出口**。

---

## 2. 活体实验(只读,库 `agent_v13_demo_mem`,会话 bf2cc453)

12 episodic 节点(8 user + 4 llm,按 source_at 序编号 #1–#12;#3=T2 因果+三万,#7=llm5 三千回声,#8=T6 八千更正,#9=llm6 八千回声,#12=T8 收尾含八千)。矛盾对全集(含「三万」×含「八千」节点的有序对)= 20。实验用每段独立 `==> '"seg"'` 查询求精确命中集(与 stannum 短词语义逐段等价),替代形态再以**单条 OR 查询 + `stannum.full_score` BM25 排序**复刻 candidates 真实行为。

### 2.1 休眠复现(控制组)

| 节点 | 段数 | AND 候选数 | 非自身候选 |
|---|---|---|---|
| 全部 12 节点 | 3–12 | 各=1(自身) | **各=0** |

总配对 0、关系信封 0、jev 边 0——与实测报告 §3 逐项吻合。T2 与 T6 的段交集=**空**(T2 段如 `约三万用户受影响` 是完整子句,T6 段如 `日志复核后实际只有八千用户受影响` 无一相同)。

### 2.2 子句级替代形态(段粒度不变,只改连接词/筛选)

| 形态 | 平均池 | 关系信封 | 总 ask(12 类型+关系) | 矛盾对命中 | T2→T6 |
|---|---|---|---|---|---|
| AND 全段(现状) | 0.0 | 0 | 12 | 0 | ✗ |
| OR 全段子句 | 3.7 | 44(k=10) | 56 | 2(仅 #8↔#9) | ✗ |
| OR top-3/5 稀有段优先 | 0.2–0.9 | 3–11 | 15–23 | 0–1 | ✗ |
| OR top-3/5 最长子句优先 | 1.0–2.5 | 12–30 | 24–42 | 0–2 | ✗ |
| AND-miss ≥25%·n | 1.2 | 14 | 26 | 1 | ✗ |
| AND-miss ≥34%/50%·n | 0.1 | 1 | 13 | 0 | ✗ |

**结论:子句级任何放宽都接不通 T2↔T6**——两者零子句交集,只有回声对(#8↔#9,措辞同源)能被词法接通。

### 2.3 亚子句粒度(CJK 段→n-gram 短语;latin 段保持整词)

单条 OR 查询(latin 段整 + CJK 段切 n-gram),BM25 排序截 top-k(复刻 candidates 计分链):

| 形态 | 平均池 | 关系信封 | 总 ask | 矛盾对 | T2→T6(名次) |
|---|---|---|---|---|---|
| 2-gram OR,k=3 / k=5 | 7.3 | 24 / 48 | 36 / 60 | 6 / 13 | ✗ / ✗(rank 6) |
| 2-gram OR,k=10 | 7.3 | 84 | 96 | **18/20** | ✓(rank 6) |
| **3-gram OR,k=5** | 5.8 | **47** | **59** | **14/20** | **✓(rank 4)** |
| 3-gram OR,k=10 | 5.8 | 68 | 80 | 18/20 | ✓(rank 4) |

- T2 在 3-gram/k=5 下的 top-5 池:`[llm5(#7), T4(#5), T8(#12), T6(#8)]`——因果对(T4 新规)、数字对(T8 收尾)、**矛盾对(T6)**同时接通,排序语义合理(BM25 对稀有词天然加权:df(`三万`)=4、df(`无法登录`)=2)。
- 关键词 df 实测:`三万`4、`八千`3、`受影响`5、`回滚`4、`无法登录`2——稀有共享 n-gram 正是矛盾/主题对的判别信号。
- T2 的 2-gram OR 查询=65 词项/522 字符;3-gram 更短。需策略键设词项上限(见 §3-A5)。

### 2.4 读侧锚定(同一函数受同一根因影响)

| 查询 | 段数 | AND 命中(现状) | 3-gram OR top-5 |
|---|---|---|---|
| `为什么用户无法登录`(纯 CJK) | 1 | **0(锚休眠)** | [#3(19.9), #7(15.0)] ✅正中 T2 |
| `why Zephyr 无法登录`(混合) | 3 | 1(试验 Q1 同型,靠埋词) | [#3, #7, #1, #2] |
| `受影响用户到底多少`(纯 CJK) | 1 | **0** | [#9, #8, #12, #3, #7] ✅矛盾簇全体 |
| `数据库备份策略`(负例) | 1 | 0 | **0** ✅负例保持干净 |

实测报告里 Q1–Q3 命中依赖查询里**恰好埋了正文中逐字出现的短语**;纯 CJK 自然查询在现状下锚恒空(整查询=1 个长短语段)。同一 n-gram 形态一并修复读锚,且负例不误中。

### 2.5 固化对源模拟(矛盾通路第二重)

| 对源 | 对数(12 节点) | 含 T2-T6 | 每对成本 |
|---|---|---|---|
| 相邻对(现状 w=1) | 11 | ✗(结构性) | 1 封×5 问 |
| 时间窗 w=2/3/4/**5** | 21/30/38/**45** | w≥5 才 ✓ | 同上 |
| 词法预筛(3-gram k=5 池去重) | **30** | ✓ | 同上 |

T2(位置 3)↔T6(位置 8)距离 5:时间窗须 w≥5 才覆盖,代价是 45 对里绝大多数非冗余/非矛盾(稀释);词法预筛 30 对天然聚焦在已判过关系的对上。

---

## 3. 替代设计清单

> 每条评:机制 / 确定性(D4 字节级) / 索引纪律(候选必须由 TINQL 谓词驱动 stannum 扫描,禁裸表扫描;`==>` 源码恰 1 次闸门) / SQL 可实现性 / 参数进策略 JSON 的形状。
> **冻结基座硬约束**:`v13_build_tinql`/`v13_tinql_terms` 在 recall stage(前序文件字节冻结,计划 §1.2-1「新树只追加」)——任何新文法(OR/n-gram)**不能 OR REPLACE 既有二函数**,只能在 `v13_mgraph.sql` 内新增 mgraph 本地锚编译器(纯函数)+ 本地文法守卫,三禁精神(用户文本不直拼 EXECUTE、引号短语闭集、长度/数量上限)照搬。

### A. 候选发现

**A1 top-k 段降苛(OR of top-k 子句)** — 机制:取 k 个「词法权重」最高子句 OR。确定性✓(选择准则需全序可再现,如 df 升序/长度降序/字典序);索引纪律✓(单 `==>` OR 查询);可实现性✓(df 需预扫或维护,见 A5 注)。**实验判死**:稀有优先池太小(avg≤0.9),最长优先接到的仍是近重复对,T2↔T6 两判皆✗——只适合近重复检测,不值得单独立项。

**A2 OR 合集(全段 OR)** — 机制:全部段 OR 单查询,BM25 排序截 top-k。确定性✓;索引纪律✓;可实现性✓(新本地 builder,如 `v13_mgraph_anchor_tinql(body) OR 形`)。数字:池 3.7、信封 44、T2↔T6 ✗(零子句交集)。**修活近重复/回声对,不修矛盾对**;作为 A5 的退化档(策略键把 ngram 关掉)保留价值。

**A3 允许 miss 比例的 AND(≥α·n 段命中)** — 机制:每段独立查询求命中集,候选=命中数 ≥ ⌈α·n⌉ 者。确定性✓;索引纪律△(N 条单段查询,每条仍谓词驱动,`==>` 源码计数仍 1——循环体单 EXECUTE 串;但每锚 N 次索引扫描,I/O 放大);可实现性△(stannum 文法无 min-should,单条布尔式需 OR-of-AND 组合爆炸,不可取;只能 N 查询循环)。数字:α=0.25 → 14 信封、T2↔T6 ✗。**判死理由与 A1/A2 同:子句粒度接不通零交集对**;且每锚 N 次扫描违反「单谓词驱动」的执行经济性,不推荐。

**A4 每段独立锚定合并去重** — 机制:每段一次 candidates 式查询,结果并集后统一计分。命中集与 A2 **数学等价**(OR=并集),纯执行形态差异(N 查询 vs 1 查询),I/O 严格更差;唯一独立价值=可与「每段各自的 bm25」做别的加权,无证据需要。**不单独立项,并入 A2 讨论。**

**A5(推荐)亚子句锚项:latin 段整 + CJK 段 n-gram 短语,OR 单查询,BM25 排序截 top-k** —
- 机制:新纯函数(建议名 `v13_mgraph_anchor_terms(body)`/`v13_mgraph_anchor_tinql(body)`)在 mgraph 文件内:CJK 段(长度>n)切 n-gram,latin 段保持整词,去重保序,OR 连接;`v13_mgraph_candidates` 的守卫从 `v13_tinql_terms` 换成本地文法守卫(引号短语 OR 连接闭集);查询仍单条 `body ==> $2`,计分/截断链零改动。
- 确定性:n-gram 展开是 body 的纯函数;BM25 池内归一化不变;并列 `score DESC, content_hash ASC` 不变;**D4 不受影响**(D4 只钉 temporal 边字节级;proximity 本来只要求同索引快照双 rebuild 相同——n-gram/bm25 在同语料下可再现)。「同池两次调用字节级相同」(D1 内)保留条件=锚 builder 确定性 + 同事务(now() 只经 recency 项进入,现状已然)。
- 索引纪律:✓ 单 `==>` 谓词驱动索引扫描,源码计数保持恰 1。
- SQL 可实现性:✓(活体已用裸 SQL 全链验证,文法探测确认 OR/短语/full_score 全可用;通配/正则/fuzzy 仍禁)。
- 参数形状(进策略 JSON,新版本行):`anchor_ngram_n`(int,0=关=退化为 A2;建议 3)、`anchor_max_terms`(int,建议 48;T2 的 3-gram 展开约 40 词项,522 字节的 2-gram 65 词项需截断规则=保序前 N)、`candidate_top_k` 复用(建议默认 10→5,见成本)。
- 数字依据:3-gram/k=5 → 59 ask(单次 build 帽 64 内)、T2→T6 rank 4、矛盾对 14/20、负例干净、读锚同修。

### B. 矛盾通路

**B1 时间窗 k 近邻(cons_pairs 扩窗)** — 机制:相邻对改 `|rn_i − rn_j| ≤ w`(或 source_at 时间窗)。确定性✓(枚举仍全序);可实现性✓(一个 CTE 改动);成本:对数 11→45(w=1→5),**本转录需 w≥5 才含 T2-T6**,每对 1 封×5 问。优点:零依赖、可独立先做;缺点:稀释严重(45 对大多无关),且 w 是对「更正距离」的硬编码猜测(本轮对话更正隔 4 轮,长对话可能更远)。参数:`consolidation_window`(int,默认 1=现状)。

**B2 词法预筛对(池衍生,依赖 A5 修活)** — 机制:consolidation 候选对=build 已发关系封的无序去重对(即 A5 池的 (a,b) 对,按 (source_at, content_hash) 规范化为 (早,晚))。**必须补规范哈希**:现 `pair_digest = hash(src||'>'||dst)` 有向,池是双向的,不规范化则同一对两把 key → 双重固化(违 queue PK 语义)。确定性✓;可实现性✓(读 memory_links 的 proximity/jev 边或重放锚池);与固化五问/fidelity/queue PK 相容(五问 state 只吃两 body;PK 唯一性靠规范化 digest 保)。数字:本转录 30 对含 T2-T6。优点:与 A5 同源、对=「已判过关系的对」零额外词法成本、天然聚焦;缺点:强依赖 A5 落地。

**B3 rel 族新增 contradicts 问(jev contradicts 边)** — 机制:`v13_mgraph_pair_questions` 基础三问 → 四问(新增 v13 本地模板 `mem_rel_contradicts`,先例=mem_cons_fidelity 台账 #3);`v13_mgraph_apply_relations` 本就 rel 无关扫描 `mem_rel::` 过阈插边,contradicts 边自动落 `origin='jev'`。**读侧已就位**:`v13_mgraph_bucket_rels` semantic 桶含 `contradicts`(mgraph:1393),jev contradicts 边今天就能被 walk 遍历——缺的只是写侧产不出。可实现性✓;模板+题面=本地拟定进 QUESTION_SNAPSHOT(v13-local 标注);缓存键新增一族 signal。这是**更正语义的沉淀出口**:强矛盾对(T2/T6)即使被固化生成门正确拦下(≥0.85 不 merge),contradicts 边仍让读环「一跳可达对方」、让 v2 的固化优先级能点名矛盾对。成本:每关系封 3–4 问 → 4–5 问(每封仍是 1 ask 批)。

**B4(推荐)B2+B3 组合** — 对源=池衍生(B2),沉淀=rel contradicts 问(B3);B1 时间窗作为 A5 未落地时的独立过渡项。gate 新增:矛盾夹具(三万/八千型)选对命中、contradicts 边插入+semantic 桶遍历可达、规范化 digest 单行。

---

## 4. 成本模型

### 4.1 信封量公式与实测点

`每节点信封 = 1 类型封 + min(candidate_top_k, |池(锚)|−1) 关系封`(entity 问不加封,只加封内问数);固化 `每对 = 1 封×5 问`;读 `每 walk ≈ 6 封(beam 5 + 停止 1)`。实测(12 节点转录):AND 12 / A2 56 / **A5-3gram-k5 59** / A5-2gram-k10 96。池随语料增长(词项 df 随 n 上升)→ 信封量次线性增长,`candidate_top_k` 是每节点硬上界(≤1+k)。

### 4.2 三帽触发表(ask 批数单位;种子值 write_max_batches=8、write_max_asks=64、session_asks_cap=512[economy:50]、day_asks_cap=8192)

| 形态 | 首建 12 节点 ask | write_max_batches=8 → tick 数 | write_max_asks=64 | session_asks_cap=512 触顶规模 |
|---|---|---|---|---|
| AND(现状) | 12 | 2 | 远未触 | ≈512 节点(1/节点) |
| A2 OR 子句 | 56 | 7 | 未触 | ≈110 节点(≈4.7/节点) |
| **A5 3-gram k=5** | **59** | **8** | **未触(余 5)** | **≈104 节点(≈4.9/节点)** |
| A5 3-gram k=10 | 80 | 10 | **触顶→游标断点续跑**(D11 语义已覆盖) | ≈76 节点 |
| A5 2-gram k=10 | 96 | 12 | 触顶→续跑 | ≈64 节点 |
| 最坏(k=10 饱和池) | ≤132 | 17 | 触顶 | ≈46 节点(README ⑦ 既有估计=上界,仍成立) |

固化侧追加:B2 池衍生对源本转录 30 对 ×1 封(consolidate 一步一封、p_limit=10/调用,driver 分摊);B3 使关系封问数 3–4→4–5(批数不变)。

### 4.3 首建大 transcript 运维评估句(供 README ⑦ 改写)

「A5 形态下每新节点平均 ≈5 个 ask 批(1 类型+≈4 关系),session_asks_cap=512 ⇒ ≈100 新节点触顶、write_max_asks=64 ⇒ 每次build约13节点一批;**首建大 transcript 必须以驱动循环分多次 build 消化 pending_nodes=0**(游标断点续跑语义不变),开启 write 前按 transcript 规模评估/上调会话帽与 write_max_asks;池量随语料增长,candidate_top_k 是唯一每节点硬闸。」

### 4.4 D11 夹具改法

- 词序置换夹具(p4 系列)在 AND 下池已全量(单词段全包含)→ **A2/A5 不改变其池**,「4×4 类型 + 12×3 对 = 52」计数**在问题集不变时保持**;若 B3 加第四问 → 4×4+12×4=**64**,计数断言改一字,帽/续跑/游标断言全部不动。
- D11 的「新增 signal 无重复=增量非空」断言与形态正交,保留。
- 若采纳 k=5 默认:夹具池=3<5 不受截断影响,无需改。

---

## 5. gate 影响清单

| gate | 现断言 | v2 影响 | 处置 |
|---|---|---|---|
| D1 | 唯一 jev 边/decision_id/列集;**同池两次调用字节级相同** | PB1/PB2 词序置换在 OR 下池不变→jev 断言绿;字节级相同**保留条件**:锚 builder 纯函数确定性+同事务(现状 now() 仅入 recency,前提未变) | 保留,建议加「锚 tinql 确定性」夹具(同 body 两次 builder 输出全等) |
| D2 | 低阈零 jev 边/temporal 在/proximity 有分/并列 hash 升序 | n0/n1/n2 同词袋→bm25 相等→并列断言在 OR 下仍成立(latin 段不 n-gram) | 保留 |
| D7 | CJK 实体={};混合对不问 entity;**build 侧 entity 问=0** | pair_questions 直测面不变;**build 侧全局零断言在 A5 下可能破**(不相交实体对可入池→entity 问合法发出) | 改为「对指定对」断言(混合对不问、不相交对问),或夹具改单词共现;台账 #12 的不可达推导随之作废——entity 闸修活,需新增正向 gate |
| D10 | causes 过阈仅一条边不镜像 | apply 链零改动,池不变 | 保留 |
| D11 | 帽/游标/续跑/52 计数 | 见 §4.4:计数仅在 B3 加问时 52→64;其余不动 | 微改 |
| D13/D14 | source_at 回查/同文折叠 | 与锚形态正交 | 保留 |
| D16 | 成功路径 cursor/watermark | 不变 | 保留 |
| E 组锚定 | 英文夹具(`alpha beacon` AND 可中) | 不变;**新增建议 gate**:纯 CJK 查询在 CJK 图上锚非空(现状活体 AND_hits=0,结构性红) | 新增 |
| E3/E4/E9 | 束/停止/evidence | 不变 | 保留 |
| F 组选对 | 2 节点会话相邻对 | B1 扩窗在 n=2 无新对→现有夹具全活;B2 池衍生需新夹具(≥3 节点+池命中对);规范化 digest 单行断言 | 新增 |
| F9 | semantic 桶可达 consolidation 节点 | 不变;B3 后可加 contradicts 边遍历 gate | 保留+新增 |
| A7 源码扫描 | `==>` 去注释=恰 1 等 | A5 保持单 EXECUTE=1;**新本地锚编译器不得含第二处 `==>`** | 保留 |
| 不变量 12 | 函数体零动作阈字面量 | n/k/词项上限全进策略 JSON;文法上限(段长 256B 等)沿用既有 V3005 域 | 保持 |

---

## 6. OQ 草案(供搬进 v2 计划 §1.3)

**OQ-A 候选发现锚形态(修活主裁决)**
选项:(1) A2 子句 OR——最小改动,修近重复不修矛盾对;(2) **A5 n-gram 混合 OR 单查询(推荐:3-gram、top_k=5)**——59 ask/单 build 帽内、T2→T6 rank 4、读锚同修、负例干净;(3) A3 miss 比例 AND——N 次扫描+子句粒度判死,不推荐;(4) 维持现状接受休眠(与 v2 目标冲突)。
依据:§2.2/§2.3 活体数字;#12 台账;英文夹具盲区机理。
机制:mgraph 本地 `v13_mgraph_anchor_terms/tinql` 纯函数+本地文法守卫(冻结 recall 不可动);`==>` 源码恰 1;策略键 `anchor_ngram_n`/`anchor_max_terms`/`candidate_top_k`。
gate:D1 保留条件、D7 build 侧改写、E 新增 CJK 锚非空 gate、A7 复扫。

**OQ-B 锚编译器归属与文法版本**
选项:(1) mgraph 本地编译器+本地守卫(推荐:不碰冻结文件,文法版本随 mgraph 策略行版本化);(2) 在 recall 追加新函数(跨 stage 追加,违反「新树只追加」最小面原则,且 recall 是文档语料面)。
依据:计划 §1.2-1、设计 §4.1 三禁(受限 compiler 精神=引号短语闭集+上限,不是绑定在具体函数名)。
机制:守卫拒绝 OR/n-gram 之外一切(通配/正则/fuzzy 仍禁);QUSTION_SNAPSHOT 式版本化不适用(非题面),版本进策略行。

**OQ-C 矛盾通路对源+沉淀出口**
选项:(1) B1 时间窗 w(独立可先做,w≥5 才覆盖本轮矛盾对,45 对稀释);(2) **B2 池衍生对(依赖 OQ-A,30 对含 T2-T6,零额外词法成本)**;(3) **B3 rel 族本地 contradicts 问→jev contradicts 边(读侧 bucket_rels 已含 contradicts,只缺写侧)**;(4) 推荐 B2+B3 组合,B1 作过渡。
依据:§1.4 双重不可达推导、§2.5 数字、固化生成门对强矛盾的正确拦截(沉淀只能靠边不靠合并)。
机制:pair_questions 四问+本地模板;apply_relations 零改动(rel 无关);pair_digest 规范化(早,晚)防双 key;固化五问/fidelity/queue PK 相容性已核。
gate:F 新增(矛盾夹具选对/contradicts 边插入/semantic 桶遍历/规范化单行);D11 计数 52→64(若加问)。

**OQ-D 写帽与默认参数**
选项:(1) 维持 64/8/512+top_k 10→5(A5-k5 59 ask 单 build 内,触顶规模 ≈104 节点);(2) top_k 维持 10+write_max_asks 升 96(2-gram 全覆盖 18/20 矛盾对,但 96>64 必触顶走续跑);(3) 双档:默认 k=5、运维档 k=10。
依据:§4.2 三帽表;README ⑦ ≈46 节点估计在 k=10 饱和下仍为上界。
机制:纯策略行翻版,无代码面;首建 runbook 句进 README(§4.3)。
gate:D11 夹具微改(§4.4);D8 帽断言复用。

---

## 7. 结论速览

- **休眠根因**:`v13_query_segments` 的 latin/CJK 粒度不对称(单词 vs 子句,recall:13)× `v13_build_tinql` 全段 AND(recall:77)× build 自排除(mgraph:1016)——三层叠加使非冗余转录上配对池结构性恒空;英文 gate 夹具(词序置换句)对此天然免疫。
- **矛盾通路**:候选休眠(问不出)+ cons_pairs 相邻对(mgraph:2703)选不出——且全链无「两 episodic 节点间的 contradicts 边」产生机制;读侧 semantic 桶却已可遍历 contradicts(mgraph:1393),只缺写侧。
- **推荐组合**:OQ-A(2) 3-gram OR 单查询 k=5 + OQ-C(4) 池衍生对源 + rel contradicts 本地问;单次 build 59 ask 在 64 帽内,T2→T6 rank 4,负例保持空手。
- 全部实验可复现:试验库只读在位,`v13_mgraph_candidates`/`==> OR`/`full_score` 均可直接重放本报告数字。
