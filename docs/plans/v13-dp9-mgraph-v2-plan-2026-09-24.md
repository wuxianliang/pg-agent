# v13 DP9 mgraph v2 —— 图贫瘠修复计划(候选发现唤醒+矛盾通路)

> 状态:**终稿 v1.0**(2026-09-24;Oracle 裁决轮:OQ13–18 全裁+P0×4+P1×8+P2×4 全部折入;单通道 gpt-5.6-sol@xhigh,grok 两 lane 故障)。裁决记录见附录 D;折入对照见附录 C。
> 历史:草案 v0.9(2026-09-24)经 Oracle 裁决**「需返工」**——返工即本 v1.0:四 P0(V3 移出/apply 闭集/B2 对源具体化/写帽口径)+P1×8+P2×4 全部折入;OQ13 裁 D ⇒ **CJK 路由不做**,V3/I 组整体移出,降级 §8 触发台账。
> 上游计划(冻结):`docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md` 终稿 v1.2——M1–M4 已全交付(352 PASS,提交 6bfe366);其 §0/§1.3/§1.4/§1.5/§3/§5/附录骨架为本计划格式权威,其 §1.3-OQ7 与 §3.4-固化① 为**被修订对象**(R2/R3,见 §1.3.7;R1 经裁决**不认**,已撤回)。
> 一手证据(全部已读并逐条核实行号):`docs/investigations/v13-dp9-mgraph-demo-trial-2026-09-24.md`(真实栈实测)、`docs/investigations/v13-mgraph-v2-candidates-contradiction-investigation-2026-09-24.md`(三层根因+12 节点活体+设计清单)、`docs/investigations/v13-mgraph-v2-cjk-routing-investigation-2026-09-24.md`(路由机理+代价+设计 A–D)。
> 实施范围(经裁决落定):①**候选发现唤醒**(OQ15=2 A5/OQ16=1);②**矛盾通路**(OQ17=4:B2 proximity 对源+B3 contradicts 写侧);③CJK 路由经 OQ13=D **不做**(§8 触发台账)。**不碰 B2 装配接线**(属下一张计划,OQ8 裁决维持)。
> 仓库约定:`AGENTS.md`(里程碑全绿→收尾工件→按路径 add→commit→push;一里程碑一提交;不用 `git add -A`)。
> 红线(本次修订):只改本计划文件;不 commit;不开发 SQL/测试。

---

## 0. 执行索引

| 里程碑 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| **V1 候选发现唤醒** | mgraph 本地锚编译器(STABLE)+本地文法守卫+策略 v2(anchor 两键+top_k=5);三调用点换源:候选入口守卫(mgraph:730)、build 侧锚(:1013)、读侧锚(:1649) | G-mg **G 组(G1–G9)**绿;A+D+E+F 全组回归绿;前序 14 stage gate 回归绿 | `v13/mgraph/v13_mgraph.sql`、`test_mgraph.py`、`README.md` | —(本计划首个里程碑) | ~200 行 SQL + ~250 行测试;1 提交 |
| **V2 矛盾通路**(依赖 V1) | 快照先行冻结 mem_rel_contradicts 槽→B3 写侧(第 29 枚模板+pair_questions 四问+**apply_relations 闭集扩 contradicts**)→B2 对源(cons_pairs 改 proximity-derived+digest 规范化)→D11/帽估算/README | G-mg **H 组(H1–H7)**绿;全组回归绿 | 同上 + `QUESTION_SNAPSHOT.md`(既有文件,新增 v13-local 槽位) | V1 | ~150 行 SQL + ~300 行测试;1 提交 |

总计:修改既有三文件(SQL/测试/README)+快照文件加一槽,**零新增文件、零新 stage**;2 次提交(AGENTS.md:一里程碑一提交,G/H 组各自全绿后按路径 add→commit→push)。gate 族沿用 **G-mg**(OQ12),新组字母 **G/H**——A–F 已占(A=M1 暗库、D=M2 写、E=M3 读环、F=M4 固化);B/C 弃用(DP9 计划 §4 曾以「组 C」预留源码扫描,实施折叠进 A7,弃用避歧义)。**I 组已随 OQ13=D 整体移出本计划**(v0.9 的 I1–I6 不进交付);既有 E2 的 CJK superset 断言**原样保留**(OQ13 裁决机制)。

> **实施进度**:V1 ✅(2026-09-24 交付;G1–G9 全绿,A+D+E+F 全组回归绿——G-mg 共 408 PASS;前序 14 stage gate 回归全绿(2927 PASS,twophase/envelope 跑前暂挪 gitignored demo 树、跑完恢复);策略种子就地升 v2(41 键)+三函数 STABLE+四调用点换源(含 transition_score 第四调用点——计划 §3.2 表未列,「E 组回归必须绿」红线推导,台账 #37);偏差台账 #37–#39+#12 后记见 v13/mgraph/README.md)。
> **V2 ✅(2026-09-24 交付;v2 计划范围完结)**:H1–H7 全绿,A–G 全组回归绿——G-mg 共 444 PASS;前序 14 stage gate 回归全绿(2927 PASS,twophase/envelope 跑前暂挪 gitignored demo 树、跑完恢复)。交付面:快照先行新增 mem_rel_contradicts v13-local 槽(29 槽,三块本地槽按组合规则 v1 拼接)+第 29 枚模板(实测 cgr 58)+pair_questions 第四问(canonical (小,大) hash 序端点)+apply_relations 闭集扩 contradicts(P0-2)+cons_pairs 重写为 proximity-derived(P0-3,诚实语义句入 README 机制 20)。实施修正两条(台账 #40/#42):①contradicts 问仅在 canonical 方向(src<dst)入封——request_hash 携带 pair ctx,双向入封会以不同哈希双问同一 signal(违 D5 每 signal 单行与 OQ17「恰一套 signal/双份 ask 不采」),连带 D11 计数实测=58 非 §6.2 预估的 64(P2-4 以实测为准);②H7 以 write_max_asks=1 步进走查 batches=8 帽下续跑(GUC mock 精确键匹配,单调用内多封不可行,#17 同族)。CJK 路由 OQ13=D 维持不做,重开条件见 §8。

---

## 1. 定位与边界

### 1.1 修什么(三连调查,两连实施)

真实栈实测(demo trial)在 12 节点中文转录上暴露三个结构性缺陷,共同后果是「图上除 temporal 链与固化边外一无所有」:

1. **候选发现休眠**(trial §3 发现 1;**v2 修,V1**):build 侧关系发现用锚节点**全 body 的 AND tinql**(mgraph:1013→recall:77-81 全段 AND);`v13_query_segments` 对 latin 切**单词**段、对 CJK 切**子句**段(recall:13-75,粒度不对称),stannum 引号段=有序短语匹配 → 两条互不包含对方全部子句的消息 AND 命中集={节点自身},build 侧自排除(mgraph:1016)后配对池**结构性恒空** → 零关系信封、零 jev 边、mem_rel 面在非冗余转录上从未发出(偏差台账 #12 的实测确认)。英文 gate 夹具全是词序置换句(D 组 p4 系列),单词段全交叉包含,AND 恒可中——**休眠在测试面上不可见**。
2. **矛盾通路双重不可达**(调查 §1.4;**v2 修,V2**):①候选休眠 ⇒ 矛盾对(T2 三万/T6 八千)从未进同一关系信封;②`v13_mgraph_cons_pairs` 只枚举**相邻对**(`b.rn = a.rn + 1`,mgraph:2692-2704,偏差 #36),T2(位置 3)与 T6(位置 8)相隔 5 位结构性不可能被选。且全链无「两 episodic 节点间 contradicts 边」的产生机制——`contradicts` 边只能由固化子型映射产生且指向**产物节点**(README 机制 20/21),强矛盾又被生成门正确拦住(OQ6:contradiction≥0.85 不入队)⇒ **更正语义在当前图上没有任何沉淀出口**。读侧 `v13_mgraph_bucket_rels` 的 semantic 桶却已含 `contradicts`(mgraph:1393)——只缺写侧。
3. **CJK 路由短路**(trial §4 发现 2;**v2 不修,OQ13=D**):`v13_mgraph_route` 的模式判定(mgraph:1475-1481)在意图检测(:1483-1488)**之前**,任一 CJK 码点(内联五区间扫描 :1463-1472)即 `ELSIF v_cjk → superset` 锁死 → 混合语言查询的 why→causal/when→temporal/大写实体→entity 永不可达;实测 4/4 walk 全 superset。已实现代价≈0(evidence 全中、superset 零 ask、稀疏图上 superset 反而搁浅更少),缺陷是潜伏的、以关系边存在为前提的。**Oracle 裁 D:不改**——重开条件见 §8(三条夹具式触发)。

**不碰 B2**:evidence 出口仍无消费者(下一张计划,OQ8 维持;trial §8 同判)。

### 1.2 基座沿用与 v2 触碰面

1. **新树只追加(DP9 §1.2-1)**:recall/memory/filter/summary/periphery 等前序 stage 文件**字节不变**——特别是 `v13_build_tinql`/`v13_tinql_terms`/`v13_query_segments`(recall stage,冻结),v2 在 `v13_mgraph.sql` 内新增本地锚编译器+本地文法守卫。全部改动落在 mgraph **自有文件**:`v13_mgraph.sql`(就地编辑既有函数段+文件末尾追加 v2 新增段)、`test_mgraph.py`、`README.md`、`QUESTION_SNAPSHOT.md`(新增 v13-local 槽位)。先例:#11(同文件 5 参重载)、#16(M2 编辑 M1 注释)。
2. **`==>` 源码计数=恰 1(A7)**:候选函数的池 EXECUTE 串(mgraph:739-750)`n.body ==> $2` **字节不变**——v2 改的是传入的 tinql(OR 形)与入口守卫,不是查询串。新锚编译器/守卫**零 `==>`、零第二动态绑定点**。**纪律(Oracle P0/P1 强化):既有函数一律在原定义处就地编辑,不得在文件尾追加同名 OR REPLACE 形成两个源码绑定点**;新增函数/模板/种子行才走文件末尾追加。A7 复扫全文自动执法。
3. **TINQL 三禁(设计 §4.1,精神照搬)**:正文/查询文本不得直拼 EXECUTE(锚 tinql 经本地纯计算函数产出、经守卫校验、经 USING 参数化);引号短语闭集文法(OR 连接);长度/数量上限(段 ≤256B 沿既有 V3005 域,按 UTF-8 字节;词项上限 `anchor_max_terms` 进策略行)。通配/正则/fuzzy 仍禁。
4. **策略数值只从 mgraph 行读(不变量 12)**:新数值键仅 `anchor_ngram_n`/`anchor_max_terms`;`candidate_top_k` 默认 10→5(OQ18)。**`routing_intent_causal`/`routing_intent_temporal` 不进键集**(OQ13=D,Oracle P1-6);`consolidation_window` 不加(OQ17 不采 B1)。函数体零新字面动作阈(形状域校验除外)。
5. **volatility 纪律(Oracle P1-1)**:锚编译器/守卫经 `v13_mgraph_policy()` 读活动策略 ⇒ 一律 **STABLE**(不得标 IMMUTABLE——只要函数读策略就不是仅由输入决定;错误声明可能让 planner/预编译计划缓存旧策略结果,破坏「策略翻版改变锚/walk 身份」)。不改签名加显式策略参数的替代方案不采。
6. **零 `SECURITY DEFINER` / 外部 IO 不进事务**:v2 新函数全普通属性、零新判断 IO 面——contradicts 问进既有关系信封(同 state 同批,resolve 角色同一 `v13_resolve_judgments` 路径);route 零 IO 不变(本计划根本不动 route)。测试继续 FakeLLM/GUC mock。
7. **策略种子演进方式(Oracle P1-6 认可)**:种子行**就地升版**(version 1→2,键集 39→41;同批改读取器期望键集与类型域数组,mgraph:209-214 一带)。理由:读取器单键集 fail-closed,双行并存须按版本分叉校验,破坏「键集漂移→V3009」简单性;stage 库 DROP-CREATE 无升级路径需求。**兼容性警示(Oracle Risks)**:v1/v2 键集不兼容——旧读取器读 v2 JSON 即 V3009;回退=恢复 v1 SQL+重建 stage,**不能只翻 active 标记**。

### 1.3 Open Questions 裁决(Oracle 轮,2026-09-24;本节为最终权威)

> 格式沿用 DP9 §1.3(DP8 先例):裁决+依据链+机制+gate;已否决支线保留一行备查。编号续 DP9 OQ1–OQ12 用 OQ13–OQ18:CJK 调查暂号 OQ-13/OQ-14 原号保持;候选+矛盾调查 OQ-A/B/C/D 顺接为 OQ15/16/17/18(附录 A.1)。

**OQ13 CJK 意图锚与混合语言优先级 —— 裁决:(4) D,不改 CJK 路由,记录触发条件。**
依据:DP9-OQ3 冻结文本明确写「CJK 段(`v13_query_segments`)→superset 六桶 ≥`deterministic_floor`、routing asked=0」,没有「意图未命中才 superset」的条件;真实栈 4/4 superset 证明的是当前规则生效,不能单独证明冻结文本原本允许 fallback 重排;v0.9 的「置信度兜底而非 CJK 不可判」是**新的解释,不是冻结文本明载**(附录 B.6 的披露由此被证实必要);已实现代价≈0 也支持不急修。
机制:v2 **不修改** `v13_mgraph_route`(模式判定序/CJK 短路/意图链/权重全保持)、**不新增**两个 routing_intent 策略键、**保留** CJK→superset 语义与零 ask;E2 既有 CJK superset 断言**原样保留**(不平移、不改写);README 机制 16 句不改,只增 deferred 说明(§6.3)。未来若采纳设计 A/B,必须在新计划中显式写成「**supersedes DP9-OQ3 routing branch**」,不能以再解释方式折入;重开入口=§8 三条夹具式触发条件 + P1-8 接口注记。
Gate:本计划零新增路由 gate;E2 原断言保留。
已否决:(1) A 混合优先级/(2) B 词表——冻结文本不含 fallback 语义,须正式 supersede 才可重开;(3) C 图内容词法命中——调查已否决(破坏路由纯函数性,正名做法=jev 六问,OQ3 既有备选支)。

**OQ14 与候选唤醒的顺序捆绑 —— 裁决:(1) 候选唤醒先行,CJK 路由后置;不要求同批提交。**
依据:交互矩阵(零关系边时路由升级零可观测量,gate 只能证明「路由输出变了」证明不了「检索变好」);A5 直接产生关系信封/关系边,构成未来路由收益的前提;现有 E 组夹具只有 temporal/consolidation 边,causal/entity 桶遍历从未被行使。
机制:候选唤醒(V1)必须先于任何未来 CJK 路由变更;**V3/I 组整体移出本计划**;G4/G5(修活+读锚)绿后才允许另立 CJK 路由计划;未来路由计划禁止在候选唤醒交付前单独提交路由改动。V2 与未来路由计划的先后是发布顺序选择而非硬依赖(差异化遍历行使夹具可独立插边)。
Gate:无(本计划内);未来计划的 gate 以 §8 触发条件为入口。

**OQ15 候选发现锚形态 —— 裁决:(2) A5:latin 段整项+CJK 3-gram,单条 OR 查询,`candidate_top_k=5`。**
依据:活体数字——A2 OR 全段仅平均池 3.7/44 封,T2↔T6 仍不通;A3/A4 受零子句交集限制;2-gram/k=10 覆盖 18/20 但 96 ask;**3-gram/k=5:池 5.8/47 关系封/59 总 ask/T2→T6 rank 4/14 矛盾对/负例干净/纯 CJK 读锚从 0 变有效命中**(df 实测:`三万`4/`八千`3/`受影响`5——稀有共享 n-gram 正是矛盾/主题对判别信号,BM25 天然加权)。
机制:`anchor_ngram_n=3`、`anchor_max_terms=48`、`candidate_top_k=5`;latin 段保持整段,CJK 段**按字符**切 n-gram,去重保序生成引号短语 OR 串。**边界钉死(Oracle P1-2):段长度=n 产生恰一个 n-gram,不得按「长度大于 n」实现**(否则恰三字的 CJK 段零锚项);长度<n 零项;词项超 `anchor_max_terms` 时去重保序保留前 N。**volatility=STABLE**(P1-1,§1.2-5)。n=0 退化为全段 OR——是**命中语义退化**(新编译器去重保序,与旧 AND 编译器保留重复度的字节输出不同,不要求一致;Oracle P2-2)。空 body/query→空串→candidates 空集零 ask。确定性口径:**同一 body/query+同一活动策略快照→相同 terms→相同 tinql→相同谓词输入**(非跨策略版本的全局不可变;策略翻版后新 policy version 允许新锚形态/新 walk 身份)。计分/截断链零改动(n-gram 项对 entity/关键词子项天然中性)。
Gate:G1(确定性+策略翻版敏感性+n=0 语义退化)、G2(n−1/n/n+1 边界+混合段+字节/字符不混淆)、G4/G5(修活+读锚)、G7(D1 保留条件)、G8(D7 改写)、G9(策略形状)。
已否决:(1) A2 子句 OR(修近重复不修矛盾对;保留为 n=0 退化档);(3) A3 miss 比例 AND(每锚 N 次扫描+子句粒度判死);(4) 维持现状(与目标冲突)。A1/A4 经调查判死并入讨论,不占选项位。

**OQ16 锚编译器归属与文法版本 —— 裁决:(1) mgraph 本地编译器+mgraph 本地守卫。**
依据:recall 三函数属文档语料面且前序文件字节冻结;把 OR/n-gram 文法追加到 recall 破坏「新树只追加」纪律,并使文档召回与记忆候选共享一个不再单一的文法;mgraph 自增受限 compiler/guard 是最小面。
机制:`v13_mgraph_candidates` 入口从 `v13_tinql_terms` 切换到本地 guard(**返回规范化项集**,供 entity/关键词子项复用);build 调用点(:1013)与 `v13_mgraph_anchors` 调用点(:1649)同批切换到本地 anchor compiler;动态 SQL、`USING p_sid,p_tinql`、计分、排序和返回列不变;**就地编辑原定义处,不得文件尾追加同名 OR REPLACE**(§1.2-2);**编译器/守卫/candidates/build/anchors 五个面同一提交**(R2 条件)。guard 只接受引号短语 OR 闭集,非法输入抛 V3005 fail-closed,不降级为裸表扫描;文法版本随 mgraph 策略行版本化。
Gate:G3(守卫负例闭集)、G6(`==>` 恰 1+无第二动态绑定点+EXPLAIN 索引扫描)。
已否决:(2) recall 追加新函数(跨 stage 追加违纪+语料面错置)。

**OQ17 矛盾通路对源与沉淀出口 —— 裁决:(4) B2+B3;B1 不采作主支。**
依据:相邻对 11 个不含 T2/T6;时间窗至少 w=5 才覆盖但 45 对稀释大量无关对且 w 是对「更正距离」的硬编码猜测;A5 词法池衍生 30 对含目标矛盾对;读侧 semantic 桶已受 `contradicts` 只缺写侧;OQ6 生成门语义表明「矛盾关系边」与「合并生成」本就是两个不同动作。
机制:
- **B2 对源=proximity-derived(完整定义,Oracle P0-3)**:同 session、两端均 episodic、`memory_links.origin='proximity'` 的边集合 → 按 `(source_at ASC, content_hash ASC)` 规范化为无序对 (early,late) → 去重 → 排除 adopted(调用方按队列行判定,现状语义)。**诚实语义(必须写入 README 机制 20)**:这是「由**已落库的激活 proximity 对**衍生的固化候选」,**不是「所有曾经发出过关系问的候选对」的审计池**——proximity 边只在 `lexical_norm≥graph_activation_threshold` 时插入;若产品要求覆盖低于阈值的已问对,须另建关系候选审计表,不是本定向方案应隐含承担的行为(停止条件见 §7)。
- **B2 digest**:`early=min by (source_at ASC, content_hash ASC)`,`digest=v13_mgraph_pair_digest(early,late)`;v1 相邻对天然 early→late,**digest 字节级不变**(决策缓存不失效的必要条件);同一无序 proximity 对恰一 consolidation key;rejected 仍可重入队、adopted 才永久排除;consolidation 节点不参与对源。
- **B3 写侧(Oracle P0-2)**:`v13_mgraph_pair_questions` 增 `mem_rel_contradicts`(noul,投影 `["left","right"]`);**`v13_mgraph_apply_relations` 必须把 `contradicts` 加入允许关系闭集——算法不变,仅扩闭集**(v0.9「零改动」表述不成立:现函数 signal 校验只接受 semantic/causes/caused_by/entity 四种,不加闭集则 contradicts 边落不了库,H3 必红)。其余语义保持:过 `relation_threshold` 才插边;`origin='jev'`+decision_id 非空属本 session;`ON CONFLICT DO NOTHING`;不改已有边。
- **contradicts canonical signal(Oracle P1-3,采推荐第 1 种)**:仅对 contradicts 信号规范化端点,同一无序 pair 只有一套 signal/一条边。规范化键=**content_hash 字典序取 (小,大)**——纯函数零 IO、不扩 `pair_questions` 签名(D7 直测面不动);与 B2 digest 的 (source_at,content_hash) 序**相互独立**(signal 身份与 consolidation_key 是两个命名空间,不要求同序)。已知代价:canonical 单向边的遍历不对称(从 hash 大端出发不能经出边到达对端)——接受;对端自身可经词法锚定到达,与 proximity 单向语义同族。备选(双向边=两套 signal+双份 ask)不采,理由:contradicts 无 causes/caused_by 那样的方向语义,重复两次不增加信息。
- **双门分离(最终语义)**:`mem_rel_contradicts≥relation_threshold`→可插 jev contradicts 边;`mem_cons_contradiction≥consolidation_threshold`→cons_gate 禁 merge/promote effect。**「拦得住合并、留得下矛盾边」**。`v13_mgraph_cons_gate`/`v13_mgraph_bucket_rels` 均零改动(semantic→contradicts 映射已存在,mgraph:1393)。
Gate:H1–H7(§5)。
已否决:(1) B1 时间窗(稀释+硬编码猜测;不加 `consolidation_window` 键)。

**OQ18 写帽与默认参数 —— 裁决:(1) 维持 64/8/512 三帽,默认 `candidate_top_k` 10→5。**
依据:3-gram/k=5 活体总 ask 59 较 k=10 的 80 更适合现有开销面;写帽/session 帽/游标续跑机制已在位,不值得为实验数据把 `write_max_asks` 提到 96。
机制:策略 v2 `candidate_top_k=5`;`write_max_batches=8`/`write_max_asks=64`/`session_asks_cap=512` 不变。**口径修正(Oracle P0-4)**:59 是**逻辑首建的跨 tick 总量**——`v13_mgraph_build` 单次调用以 `write_max_batches=8` 先行截断,由 `rel_cursor` 跨约 8 个 tick 续跑完成;`write_max_asks=64` 是单次调用内的累计帽,在该形态下不成为主限制。**≈104 节点是活体平均估计(≈4.9 ask/节点),不是硬上界**;k=5 下每节点硬上界=1 类型封+5 关系封=6 封,写路径隔离时的保守上界≈512/6≈**85 节点**;session 帽还与用户回合/读 walk 共享(Oracle P1-7)。README 双口径改写见 §6.3。
Gate:D8 复用;D11 扩展+H7(跨 tick 续跑断言)。

### 1.3.7 冻结裁决修订记录(R1–R3 裁定)

DP9 §1.3 为 Oracle 轮 1 终审权威。v2 登记 的三条修订经 Oracle 裁定如下:

| # | 被修订的冻结文本 | 裁定 | 条件/处置(全部已折入) |
|---|---|---|---|
| R1 | DP9 §1.3-**OQ3**(「CJK 段→superset 六桶 ≥floor、routing asked=0;英文子串 WHEN/WHY/大写实体…」) | **不认(撤回)** | OQ3 冻结文本明确「CJK 段→superset」,无 fallback 条件;再解释不能替代正式 supersede。v1.0 处置:V3/I 组整体移出、E2 原样保留、route 不改、README 只增 deferred 说明;重开须新计划显式「supersedes DP9-OQ3」+§8 触发条件 |
| R2 | DP9 §1.3-**OQ7**(「`p_tinql` 必须经 `v13_build_tinql`→`v13_tinql_terms` 产出」) | **认,有条件** | 已登记为 OQ15/16 对 OQ7 的正式修订(非静默改 recall)。条件(全部折入):①volatility=STABLE(P1-1→§1.2-5/OQ15 机制);②guard 返回形状精确定义=规范化项集(OQ16 机制);③candidates/build/anchors 三调用点+编译器/守卫同一提交(OQ16 机制/R2 条件)。OQ7 其余全部不动:签名三参、谓词驱动禁裸扫、`==>` 恰 1、插完再计分/池=全会话、D4 temporal 字节级/proximity 快照限、不镜像、「同池两次调用字节级相同」保留条件 |
| R3 | DP9 §3.4-固化①(「选对:source_at 近、哈希序」;实施=相邻对,偏差 #36) | **认 B2 版本,有条件** | 条件(全部折入):①B2=proximity-derived 对源+诚实语义句(P0-3→OQ17 机制);②digest 以 early/late 规范化且 v1 相邻 key 字节级不变(OQ17 机制);③apply_relations 关系闭集扩 contradicts(P0-2→OQ17 机制)。OQ6 生成门/fidelity/queue PK/子型映射/产物不作锚全部不动;B3 是新增沉淀出口,不修改 OQ6 |

非裁决文本登记(随交付更新,不改原条目):偏差台账 #12 追加后记「V1 交付后 entity 闸修活,原不可达推导失效」;README 机制 16 句**不改**(R1 撤回),只增「CJK 路由维持 DP9-OQ3;重开条件见 v2 计划 §8」deferred 行。

### 1.4 不变量核对表(v2 触碰面逐条)

| 不变量(DP9 §1.4 编号/基座条目) | v2 是否触碰 | 处置 |
|---|---|---|
| 新树只追加(前序 stage 文件字节不变) | 触碰(方式合规) | 全部改动在 mgraph 自有文件;recall 三函数零改动(§1.2-1) |
| `==>` 源码去注释计数=恰 1 | 触碰(有陷阱) | 池 EXECUTE 串字节不变;新函数零 `==>`/零第二绑定点;就地编辑纪律(§1.2-2);G6 执法 |
| TINQL 三禁(设计 §4.1) | 触碰(等价继承) | 引号短语 OR 闭集+256B 段限(字节)+词项上限;USING 参数化(§1.2-3);G3 |
| 12 策略数值只从 mgraph 行读、函数体零字面阈 | 触碰(新增键) | 仅 anchor 两键+top_k 默认值;routing/窗口键不进(§1.2-4);G9 |
| 2 零 `SECURITY DEFINER` | 不触碰 | v2 新函数全普通属性 |
| 外部 IO 不进事务 | 不触碰 | 零新判断 IO 面(§1.2-6) |
| 1 动作谓词只读策略行/defaults | 不触碰 | 边插入阈/门控零改动 |
| 3 mgraph 函数不碰会话锁/append_event/typesafe_ask | 不触碰 | v2 函数无新 IO/锁面 |
| 5 毒化重建零调用(`failed=false`∧asked=0) | 不触碰 | 锚 builder 纯计算,重放同键缓存命中;D4 回归保留 |
| 7 一信封=一 state;batch_questions=问题数 | 触碰(问数面) | pair 封 3–4 问→4–5 问,同 state 同批,批数不变;上限 32 内 |
| 8 哈希材料不含 now() 等 | 不触碰 | canonical digest 输入仍是哈希+定序键 |
| 9 模板种子加载事务内 bump cgr | 触碰(常规) | 第 29 枚同纪律;计数以实测为准(56→58,P2-4) |
| 10 `v13_needed_judgments` 不含 `mem_` | 不触碰 | F7 回归保留 |
| 11 源码无 mock_response/set_config/pg_net/dblink/COPY PROGRAM | 不触碰 | A7 复扫 |
| 13 游走与回合共用 judge_spend;write_max_asks 帽 | 触碰(口径面) | 帽值不动;执行口径=每 tick 截断+游标续跑(OQ18 机制);H7 |
| 14 mem_% 落 decisions 的 dec-refresh 已知代价 | 不触碰 | 关系封数量上升=更多 mem_ 行,语义不变 |
| 15 mem_route signal 含 mgraph_generation | 不触碰 | route/signal 零改动(OQ13=D) |

### 1.5 接口契约(v2 触碰面)

| 边界 | v2 动作 |
|---|---|
| `v13_mgraph_candidates(p_sid, p_tinql, p_k)` | 签名不变;入口守卫换 `v13_mgraph_anchor_guard`(返回规范化项集);EXECUTE 串不变 |
| `v13_mgraph_route(p_query)` | **不改**(OQ13=D) |
| `v13_mgraph_pair_questions(...)` | 返回集 +1 问(mem_rel_contradicts,**canonical (小,大) hash 序端点**);仍是问集/entity 闸单一事实源;签名不变 |
| `v13_mgraph_cons_pairs(p_sid)` | 对源重写为 proximity-derived;返回列不变 |
| `v13_mgraph_apply_relations(sid)` | **算法不变;允许关系闭集扩 `contradicts`**(P0-2) |
| 新函数 | `v13_mgraph_anchor_terms(body)`、`v13_mgraph_anchor_tinql(body)`、`v13_mgraph_anchor_guard(p_tinql)`——均 **STABLE**、零 IO、不访问图 |
| signal 表(DP9 §1.5) | 新增一行:`mem_rel_contradicts` noul `["left","right"]` `mem_rel::<小hash>::<大hash>::contradicts`(canonical 端点);其余形状零改动 |
| 策略行 | 种子升 v2(41 键):+`anchor_ngram_n=3`/`anchor_max_terms=48`;`candidate_top_k=5`;**不加** routing_intent_*/consolidation_window;读取器键集/类型域同批 |
| effects/kind/cap/requeue/route/装配/校验器/context_required/`v13_needed_judgments`/前序 stage 全部 | **不碰** |

---

## 2. 根因与证据基线(浓缩;全量见两份调查)

### 2.1 候选休眠三层根因(代码级,行号已核实)

| 层 | 机制 | 位置 |
|---|---|---|
| 根因层 | `v13_query_segments` 段化粒度不对称:latin=**单词**段、CJK=**子句**段;stannum 引号段=**有序短语**匹配(活体:`"用户受影响"`→3 节点、乱序→0) | recall:13-75(码点表 :33-39) |
| 文法层 | `v13_build_tinql` 全段 AND → 锚查询=「候选必须包含锚的每一个子句」 | recall:77-81;守卫 recall:83-119 只认 AND 文法 |
| 自排除层 | build 侧 `IF v_cand.content_hash = v_node.content_hash THEN CONTINUE` | mgraph:1016 |

英文 gate 全绿的原因:D 组夹具全是词序置换句(单词段全交叉包含)——休眠在测试面上不可见;偏差 #12 从同根因推出 mem_rel_entity 写路径结构性不可达。

### 2.2 活体实验关键数字(12 节点中文转录,只读库 `agent_v13_demo_mem`)

| 形态 | 平均池 | 关系信封 | 总 ask | 矛盾对(全集 20) | T2→T6 |
|---|---|---|---|---|---|
| AND 全段(现状) | 0.0 | 0 | 12 | 0 | ✗ |
| OR 全段子句(A2) | 3.7 | 44 | 56 | 2(仅回声对) | ✗ |
| AND-miss ≥25%/34%/50% | 0.1–1.2 | 1–14 | 13–26 | 0–1 | ✗ |
| 2-gram OR k=10 | 7.3 | 84 | 96 | 18/20 | ✓(rank 6) |
| **3-gram OR k=5(裁决采用)** | **5.8** | **47** | **59** | **14/20** | **✓(rank 4)** |
| 3-gram OR k=10 | 5.8 | 68 | 80 | 18/20 | ✓(rank 4) |

读侧同修:`为什么用户无法登录`(纯 CJK)现状 AND=**0**→3-gram top-5=[#3(19.9),#7(15.0)] 正中 T2;`受影响用户到底多少`→矛盾簇全体;负例`数据库备份策略`→0 保持干净。固化对源:相邻(现状)11 对不含 T2-T6;时间窗 w=5→45 对(稀释);**词法预筛(3-gram k=5 池去重)→30 对含 T2-T6**。

### 2.3 CJK 路由:机理与代价结论(OQ13=D 的依据)

- 机理:模式三态(jev > **CJK→superset** > deterministic)在意图检测之前(mgraph:1475-1481 vs :1483-1488);CJK 扫描是五区间**内联复制**(:1463-1472,对 recall:33-39 的漂移风险)。
- 配额手算(B=20,e=1.5):superset→causal 4/entity 4/multi_hop 3/recency 3/semantic 3/temporal 3;英文 WHY→7/3/3/3/2/2。**反直觉**:零关系边图上英文 WHY 搁浅 10 槽 vs superset 搁浅 8——升权在空桶上是轻微负收益,这是 OQ3 原始直觉在稀疏图上恰好无损的原因。
- 代价判定:已实现代价≈0;潜伏代价=「关系边密度 × 查询词法失配率」乘积,前者被候选休眠卡死、后者中文改写查询常见。**调查与 Oracle 同判:非 P0/P1 级,不与候选唤醒捆绑急修(OQ13=D);V1/V2 交付后按 §8 触发条件重开。**

---

## 3. SQL 草案(函数级;全码实施时落,此处钉签名与机制)

### 3.1 新函数(V1 段追加;均 STABLE——经 `v13_mgraph_policy()` 读策略,Oracle P1-1)

```sql
-- 亚子句锚项:latin 段整项 + CJK 段按字符切 n-gram(anchor_ngram_n;0=关=全段 OR 语义)
-- 边界:段长度=n → 恰一个 n-gram;长度<n → 零项;去重保序;超 anchor_max_terms 保序截断
CREATE FUNCTION v13_mgraph_anchor_terms(p_body text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$ ... $$;
-- OR 形 tinql:引号短语以 ' OR ' 连接;空项返回空字符串
CREATE FUNCTION v13_mgraph_anchor_tinql(p_body text) RETURNS text
LANGUAGE plpgsql STABLE AS $$ ... $$;
-- 本地文法守卫:引号段 OR 闭集;段 ≤256B(UTF-8 字节)/词项 ≤anchor_max_terms;
-- AND 形/裸词/内嵌引号/通配/正则/fuzzy → V3005;返回规范化项集(candidates 复用)
CREATE FUNCTION v13_mgraph_anchor_guard(p_tinql text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$ ... $$;
```

有效不变量:`同一 body/query + 同一活动策略快照 → 相同 terms → 相同 tinql → 相同候选谓词输入`(非跨策略版本全局不可变)。

### 3.2 既有函数就地编辑(原定义处;避免 `==>`/绑定点双计——§1.2-2)

| 函数 | 位置 | 改动 |
|---|---|---|
| `v13_mgraph_candidates` | :730 守卫行 | `v13_tinql_terms(p_tinql)` → `v13_mgraph_anchor_guard(p_tinql)`;池 EXECUTE(:739-750)/计分(:752-764)/截断(:765-769)零改动 |
| `v13_mgraph_build` | :1013 | `v13_build_tinql(v_node.body)` → `v13_mgraph_anchor_tinql(v_node.body)`;自排除(:1016)/proximity(:1017-1024)/三帽(:1036-1041)/游标收尾零改动 |
| `v13_mgraph_anchors` | :1649 | `v13_build_tinql(p_query)` → `v13_mgraph_anchor_tinql(p_query)`;其余零改动 |
| `v13_mgraph_pair_questions` | :776-809 | 基础三问→四问(+`mem_rel_contradicts`,signal 取 **canonical (小,大) hash 序**端点);entity 闸 CASE 不动;签名不变 |
| `v13_mgraph_cons_pairs` | :2692-2704 | 对源重写(proximity-derived,§3.5);返回列不变;排除条件(仅 adopted,调用方)不变 |
| `v13_mgraph_apply_relations` | M2 段 | **算法不变;允许关系闭集 semantic/causes/caused_by/entity → +`contradicts`**(P0-2) |
| `v13_mgraph_policy` | :209-214 一带 | 期望键集字符串+类型域数组 +2 键(同批,fail-closed) |
| `v13_mgraph_route` | — | **不改**(OQ13=D) |

### 3.3 策略种子 v2(就地升版;39→41 键)

```json
"candidate_top_k": 5,
"anchor_ngram_n": 3,
"anchor_max_terms": 48
```

(其余 38 键值不变;**不加** `routing_intent_*`/`consolidation_window`。)形状校验:anchor 两键=非负/正整数域。同批:读取器键集全等串、类型域数组、测试 `set_active("mgraph", 1)`→2 引用、A2/G9 期望 JSON。

### 3.4 模板与快照(V2 第一步:快照先行冻结,Oracle P1-5)

第 29 枚模板 `mem_rel_contradicts`:kind noul、epoch pre-finalize、投影 `["left","right"]`、writer/wire/canon=`v13_resolve`/1/1、criteria=NULL(noul 族)。**题面冻结候选(进快照新槽,标注 `v13-local`,先例 #3;sha256 在写槽时计算,A3 对组合后 question 文本全等)**,按 v1 组合规则(noul=instructions+' TRUE if: '+true+' FALSE if: '+false)与 rel 族风格拟定:

- instructions:`Compare \`new_memory.content\` with \`candidates[0].content\`. Do these two observations make claims that cannot both be true at the same time?`
- criteria_true:`The two accounts assert mutually exclusive facts, quantities or outcomes.`
- criteria_false:`The accounts are consistent, unrelated, or one merely elaborates the other.`

快照槽冻结**必须先于模板 seed 修改**(实施顺序步 4→5);加载事务内 cgr bump 既有纪律(实测 56→58,P2-4 以观测为准)。

### 3.5 B2 对源与 canonical signal 伪码

```
cons_pairs(sid):                                       -- proximity-derived(裁决定义)
  对源 = SELECT ... FROM memory_links l
         WHERE l.session_id=sid AND l.origin='proximity'
           AND 两端均 episodic(memory_nodes)            -- 不是"所有历史关系封"的审计池(诚实语义)
  规范化 = 按 (source_at ASC, content_hash ASC) 取 (early, late);无序去重
  digest = v13_mgraph_pair_digest(early, late)          -- v1 相邻对方向一致 ⇒ 字节级不变
  排除 = queue 行 status='adopted' 的 consolidation_key(调用方,现状语义)

pair_questions(src, dst, ...):                          -- contradicts canonical signal(P1-3 第 1 种)
  (lo, hi) = (least(src,dst), greatest(src,dst))        -- content_hash 字典序
  signal = 'mem_rel::' || lo || '::' || hi || '::contradicts'
  -- 同一无序对恰一套 signal/一条边;单向遍历不对称=已裁接受的代价
```

---

## 4. 逐文件影响与实施顺序

**文件清单(Oracle P2-1 口径)**:修改既有 `v13_mgraph.sql`/`test_mgraph.py`/`README.md` 三文件;`QUESTION_SNAPSHOT.md` 为**既有快照文件新增 v13-local 槽位**;零新增文件、零新 SQL stage;`v13/recall/v13_recall.sql`、`v13/load.py`、`v13/mgraph/setup_db.py` 及一切前序 stage/装配/manifest 文件**不变**。

**实施顺序(Oracle 8 步映射;步 0 已完成=本 v1.0 折入)**:

| Oracle 步 | 内容 | 归属 |
|---|---|---|
| 1 | 修改计划并冻结裁决结果 | ✅ 本 v1.0(此步完成前不改 SQL) |
| 2 | 补齐 V1 接口与策略设计(返回形状/错误码/volatility;固定 3/48/5;keyset+测试 helper)——先以策略形状与纯函数边界测试独立验证 | V1 |
| 3 | 实现 V1:追加 compiler/guard+三调用点就地切换;唯一动态 `==>` 保持;G 组+A–F 回归。**G1/G2/G6 先绿,才接受 G4 修活数字** | V1 |
| 4 | 冻结 V2 题面快照(v13-local 槽+sha256+全等验证)——**先于模板 seed 修改** | V2 首步 |
| 5 | 实现 B3 写侧:模板版本/题面/freeze 列表+pair_questions 同批;**扩 apply_relations 闭集**;阈值/decision_id/origin/ON CONFLICT 语义保持;H3/H5 | V2 |
| 6 | 实现 B2 对源与 digest 规范化:cons_pairs 改 proximity-derived;canonicalize;**验证 v1 相邻 digest 字节级不变**;H1/H2/H4+队列唯一性回归。**停止条件**:若实际需求坚持「所有发出过的关系问都可固化」,在此步停下重新设计持久化候选池,不得用 proximity 边伪装满足 | V2 |
| 7 | 更新 D11(52→64)/帽估算/运维文档;验证每封仍一批(问数非批数变化);验证 A5-k5 多 tick 续跑 | V2 |
| 8 | 完整回归:G/H 全绿;**保留旧 E2 CJK superset**;前序 14 stage gate 全绿;源码扫描确认前序文件零字节改动、mgraph 内 `==>` 恰 1 | 每里程碑+收尾 |

AGENTS.md 纪律:V1(G 组全绿→收尾工件→按路径 add→commit→push);V2 同;提交信息 `v13: <祈使句>`(如 `v13: wake mgraph candidate discovery with sub-clause CJK n-gram anchors`、`v13: open mgraph contradiction path (proximity pair source + jev contradicts edges)`)。

---

## 5. 里程碑与 gate(G-mg 新组 G/H;命令不变:`uv run python v13/mgraph/test_mgraph.py`,退出码 0=通过)

> **E2 处置(OQ13=D/P0-1)**:既有「CJK query is a superset at or above the floor」断言**原样保留**——不改写、不平移为 deterministic 断言;英文 WHY 断言族同样不变。测试中全部活动 mgraph policy 版本引用随种子升 v2(P1-6)。

### V1 候选发现唤醒(G 组)

| # | 断言 |
|---|---|
| G1 | 编译器确定性与策略敏感性:同 body+**同活动策略快照**两次调用 terms/tinql 全等(纯 CJK/混合/纯 latin);**策略翻版(n 或 max_terms 变)→同 body 输出改变**(P1-1);n=0→命中语义退化为全段 OR(断言语义面,**不与旧 AND 编译器字节比对**,P2-2);截断=去重保序前 N |
| G2 | n-gram 边界(P1-2):段长度 n−1→零项;长度 n→**恰一项**;长度 n+1→两项;混合 latin/CJK(latin 整项不切);UTF-8 字节长与字符数不混淆(段 256B 限按字节,n-gram 按字符切) |
| G3 | 守卫 fail-closed:合法 OR 短语串通过;AND 形/裸词/内嵌引号/通配/正则/fuzzy/超 256B 段/超 `anchor_max_terms`→V3005 |
| G4 | 修活(核心):零子句交集+共享稀有 3-gram 夹具(模拟 T2/T6 型)——池含目标对、关系信封发出;零共享 n-gram 负例→池空零封(负例干净) |
| G5 | 读锚同修:纯 CJK 查询在 CJK 图上 `v13_mgraph_anchors` 非空(现状结构性红);无关查询仍空 |
| G6 | 纪律复扫:`==>` 去注释=恰 1;函数定义无第二动态绑定点;`enable_seqscan=off` 下候选计划仍走 stannum;A7 五项全 0 |
| G7 | D1 保留条件:同池两次调用字节级相同(同事务+同活动策略);D2 并列 hash 升序仍绿 |
| G8 | D7 改写:混合对不问 entity(不变);不相交实体对**问**(修活后合法,替代「build 侧 entity 问=0」全局断言);台账 #12 后记 |
| G9 | 策略 v2 形状:键集全等(41 键,含 anchor 两键、**不含** routing 键);坏形(缺键/错型/越域)→V3009;A2 期望 JSON 更新 |

### V2 矛盾通路(H 组)

| # | 断言 |
|---|---|
| H1 | 选对修活(P1-4):夹具经**真实 A5 build** 产出目标 proximity 边(或插入与生产形状一致的 proximity 边)→非相邻 T2/T6 型 proximity 对被选中;**无 proximity 边的普通 episodic 对不被选中**(负断言);冗余回声相邻对(A5 下有 proximity 边)仍被选——**语义收窄已裁**:时间相邻但零词法激活的对不再进对源 |
| H2 | 规范化 digest:同一无序 proximity 对恰一 key;**v1 相邻对 digest 字节级不变**(缓存不失效);queue PK 单行(F6 回归) |
| H3 | contradicts 写侧(P0-2):apply 允许闭集含 contradicts——mock 高 noul→`origin='jev'`+decision_id 非空边落库;既有四 rel(signal 语义/causes/caused_by/entity)回归不受扰;**canonical signal**:A→B/B→A 双向候选只产生一套 contradicts signal/一条边(P1-3) |
| H4 | 读侧可达:semantic 桶一跳遍历 contradicts 边抵对端(从 canonical src 出发;bucket_rels 零改动面首次行使) |
| H5 | 双门语义:强矛盾对零 consolidation effect(F1 回归)+contradicts jev 边独立存在——「拦得住合并、留得下矛盾边」;cons_gate 零改动 |
| H6 | 模板/快照:第 29 枚 A3 全等(v13-local 槽+sha256);cgr 增量以实测为准(预期 56→58,P2-4);D11 计数 52→64;帽/游标/续跑断言不动 |
| H7 | 跨 tick 续跑(P0-4 口径):A5 夹具全量首建在 `write_max_batches=8` 下经 rel_cursor **多次 build 调用**完成——每次调用 ≤8 ask、累计=预期总量、signal 增量非空无重复(不断言单次调用完成全部 ask) |

---

## 6. 成本与运维

### 6.1 三帽触发表(ask 批数单位;口径修正=Oracle P0-4/P1-7)

**执行口径**:下表「首建 ask」=**逻辑首建的跨 tick 总量**——build 每次调用以 `write_max_batches=8` 截断,由 rel_cursor 续跑消化;`write_max_asks=64` 为单次调用累计帽,该形态下不成为主限制。「触顶规模」的 ≈104 是**活体平均估计非硬上界**;k=5 每节点硬上界=1 类型封+5 关系封=6 封,写路径隔离时保守上界≈512/6≈**85 节点**;session 帽与用户回合/读 walk 共享。

| 形态 | 首建 12 节点 ask(跨 tick 总量) | tick 数(帽 8) | 64 单调用帽 | session 帽 512 触顶规模 |
|---|---|---|---|---|
| AND(现状) | 12 | 2 | 远未触 | ≈512 节点(1/节点) |
| A2 OR 子句 | 56 | 7 | 未触 | ≈110 节点 |
| **A5 3-gram k=5(裁决采用)** | **59** | **8** | **未触** | **≈104(活体平均)/≈85(保守上界)** |
| A5 3-gram k=10 | 80 | 10 | 单调用不触(跨 tick 消化) | ≈76 节点 |
| A5 2-gram k=10 | 96 | 12 | 同上 | ≈64 节点 |
| 最坏(k=10 饱和池) | ≤132 | 17 | 同上 | ≈46 节点(k=10 上界,README ⑦ 既有估计) |

固化侧追加:B2 对源本转录 30 对×1 封(consolidate 一步一封、p_limit=10/调用,driver 分摊);B3 使关系封问数 3–4→4–5(批数不变)。

### 6.2 D11 夹具改法

词序置换夹具(p4 系列)在 AND 下池已全量(单词段全包含)→A5 **不改变其池**,「4×4 类型+12×3 对=52」计数在问题集不变时保持;B3 加第四问→4×4+12×4=**64**,计数断言改一字,帽/续跑/游标断言全部不动。「新增 signal 无重复=增量非空」断言与形态正交,保留。k=5 默认下夹具池=3<5 不受截断影响。

### 6.3 README 运维注记更新点

- **⑦ 写帽预估重写(双口径,P1-7)**:`write_max_batches=8` 是每次 build tick 的实际截断;A5-k5 的 59 ask 是**多 tick 总量**(约 8 tick,rel_cursor 续跑);`write_max_asks=64` 为单次调用帽;≈104 节点=活体平均估计(≈4.9 ask/节点),**非硬上界**——每节点最大 1 类型封+5 关系封=6 封,写路径隔离保守上界≈512/6≈85;session 帽与用户回合/读 walk 共享。
- **机制 11**:锚形态改 A5;明示 recall 三函数不变。
- **机制 20**:固化对源改 proximity-derived;**诚实句**:「由已落库的激活 proximity 对衍生的固化候选,不是所有历史关系封的审计池」。
- **新增 apply 闭集说明**:apply_relations 允许关系含 contradicts(写侧面)。
- **模板计数 28→29、cgr 56→58**:以实际测试观测为准(P2-4)。
- **新增 R1 deferred 说明**:CJK 路由维持 DP9-OQ3;重开条件见 v2 计划 §8。
- **删除 v0.9 的 I 组/词表运维描述**(不属本计划)。
- **#12 后记**(V1):台账追加「V1 交付后 entity 闸修活,原不可达推导失效」,不改原条目。

---

## 7. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| **策略 v1/v2 键集不兼容**(Oracle Risks) | 读取器 fail-closed(旧读取器读 v2 JSON→V3009) | **回退=恢复 v1 SQL+重建 stage,不能只翻 active 标记**;新增 contradicts decision 在旧代码下不被 apply 但不破 schema;严格回滚仍走完整 stage 回退 |
| **B2 语义局限**(proximity≠全部已问对) | 诚实语义句进 README/机制 20;Oracle 步 6 停止条件:需求坚持全量已问对→停下重设计持久化候选池,不得用 proximity 边伪装 | 另立计划(审计表) |
| n-gram 池随语料膨胀(df 上升)→信封量增长 | `candidate_top_k` 每节点硬上界(≤1+k=6);三帽表 §6.1;H7 | 策略降 k;`anchor_ngram_n=0` 退 A2 语义 |
| OR 形 tinql 与 stannum 文法漂移 | 守卫 fail-closed(V3005);G3 负例闭集 | 守卫收紧=代码修复 |
| canonical 单向 contradicts 边的遍历不对称 | 已裁接受的代价(P1-3);对端经词法锚定自身可达;H4 断言 canonical src 方向 | 改双向=新裁决(双份 ask) |
| A5 后关系封数量上升→mem_ 行增多→dec-refresh 频率上升 | 不变量 14 既有语义;README 已记 | 关 write |
| 模板 cgr bump 不可逆 | 既有语义(与 DP9 种子同) | — |
| digest 规范化破坏 v1 相邻缓存 | early/late 与 v1 相邻对方向一致=字节级不变(H2 断言) | — |
| **回退面诚实声明** | 种子可退 A2(n=0,语义退化)**不可退 AND**——AND 形态被 V1 替换后完全恢复须代码级回退 | 一里程碑一提交,可独立 revert;整体回退=stage 库 DROP-CREATE,前序 14 stage 文件字节不变 |

---

## 8. 明确不做(沿 DP9 §8 台账;*为 v2 新增/修订条目)

| 项 | 触发 |
|---|---|
| ***CJK 路由升级(OQ13=D 不做;设计 A–D 全文见 CJK 调查 §3 与 v0.9 OQ13 记录)** | **三条夹具式触发条件全满足方可新计划重开(Oracle P2-3)**:①图上存在 causes/entity/contradicts 的**实际可遍历边**(V1/V2 交付后可测);②同一中文意图查询在 superset 与 deterministic 两种 routing 下产生**不同配额/扩展节点**;③该差异可在**不依赖 B2 装配接线**的 walk gate 中观测。重开时必须显式「**supersedes DP9-OQ3**」,并先解决接口问题(Oracle P1-8):`v13_query_segments` 只返回段文本不返回 script 类——需新增只读 script 判定 helper 或 mgraph-local helper(基于同一权威码点表),禁改冻结 recall 函数,gate 验证边界行为一致。词表/代词锚/多语种扩展皆属该未来计划范畴 |
| **B2 装配接线**(manifest memory_graph 段/mgraph_gen/pending_walk/manifest v4) | 下一张计划(OQ8 维持);触发=evidence 出口出现真实消费者 |
| **T1 嵌入/余弦恢复** | 固定评估集证明词法漏召(设计 §7)。*v2 后新增观察:纯 ASCII 查询对纯中文正文词法失配仍无锚(latin 整项不 n-gram),属 T1 范畴不在 v2 修 |
| **admission 五问** | DP9 §8 原触发 |
| **consolidation_interval 自动化** | DP9 §8 原触发 |
| **关系候选审计表**(全量已问对的持久化) | 仅当产品要求覆盖低于 activation 阈值的已问对(§7 停止条件) |
| A1/A3/A4 候选形态 | 调查判死(§2.2);无触发 |
| walk/round 生命周期清理 | DP9 §8 原触发(下一张计划) |
| E2 CJK superset 断言族/E4/E9/D12/shadow 面 | **保留原样**(OQ13=D;v0.9 的「平移改写」随 V3 移出作废) |

---

## 附录 A. OQ 编号映射与说明

续 DP9 OQ1–OQ12,本计划用 OQ13–OQ18:CJK 调查暂号 **OQ-13/OQ-14 原号保持**(两报告互引零翻译);候选+矛盾调查 **OQ-A/B/C/D 顺接为 OQ15/16/17/18**。弃用「v2 前缀」:DP9 编号空间为裸数字,前缀造成同族分叉。gate 族沿用 G-mg(OQ12)新组 G/H(I 组随 OQ13=D 移出)。

## 附录 B. 输入矛盾点与口径差异披露(v0.9 登记+v1.0 裁决结果注)

1. **OQ3 文本 vs 实施**:OQ3 写「CJK 段(`v13_query_segments`)→superset」(暗示调用分段器),实施是内联码点扫描(mgraph:1463-1472)。语义等价但机制漂移——v1.0 裁决后 v2 不动 route,漂移留待未来计划(P1-8 接口注记已入 §8)。
2. **README ⑦ ≈46 节点 vs 调查 ≈104**:上界(k=10 饱和)vs 实测(k=5 平均)之差;v1.0 按 P0-4/P1-7 改为**双口径**(平均≈104+保守上界≈85+tick 语义)。
3. **demo trial 写帽口径**:trial 用自定义行(write_max_asks=48)非种子 64;v1.0 统一为**种子值+多 tick 口径**。
4. **D7「build 侧 entity 问=0」/偏差 #12**:非调查与冻结文本的矛盾,是 V1 必然触动的既有 gate;G8 改写+台账后记处置。
5. **两份调查相互一致性**:零矛盾(「候选先决/CJK 放大器」、修订必要性、B2 不属 v2 三点完全一致)。
6. **「superset=置信度兜底」的再解释**:v0.9 已标注为调查单方解释;**Oracle R1 裁「不认」证实该披露必要**——v1.0 撤回 R1,V3/I 组移出。

## 附录 C. Oracle 裁决折入对照表

| 裁决项 | 内容 | 折入落点 |
|---|---|---|
| P0-1 | V3/I 组违反 OQ3 冻结 | §0(I 组移出)/§1.3-OQ13(D)/§5 E2 处置/§8 触发台账 |
| P0-2 | apply_relations 闭集不相容 | §1.3-OQ17 机制/§1.5/§3.2/H3 |
| P0-3 | B2 无持久「已发关系封」来源 | §1.3-OQ17 proximity-derived 定义+诚实句/§3.5/§7 停止条件/H1 |
| P0-4 | 59 ask 与 write_max_batches=8 语义不一致 | §1.3-OQ18 机制/§6.1 口径/H7/§6.3 README ⑦ |
| P1-1 | IMMUTABLE 与策略读取冲突 | §1.2-5/§1.3-OQ15/§3.1/G1 |
| P1-2 | n-gram 边界未钉死 | §1.3-OQ15 机制/G2 |
| P1-3 | contradicts 对称性未决 | §1.3-OQ17 canonical (小,大) hash 序/H3 |
| P1-4 | H1 池来源须可观测 | H1(真实 A5 build 产边+负断言) |
| P1-5 | 模板缓存身份须先行冻结 | §3.4/实施顺序步 4→5 |
| P1-6 | 策略 key set 同步 | §1.2-4/§3.3/G9/§5 测试版本引用 |
| P1-7 | 三帽估算非硬上界 | §6.1/§6.3 README 双口径 |
| P1-8 | 复用 v13_query_segments 接口需重设计 | §8 CJK 条目(未来计划) |
| P2-1 | 文件范围叙述不一致 | §4 文件清单口径 |
| P2-2 | n=0 是语义退化 | G1 |
| P2-3 | R1 触发条件模糊 | §8 三条夹具式条件 |
| P2-4 | 模板/cgr 计数须实测 | §3.4/H6/§6.3 |

## 附录 D. Oracle 裁决记录

| 轮 | 日期 | 通道 | 状态 | 要点 |
|---|---|---|---|---|
| v2 裁决轮 | 2026-09-24 | ask_oracle plan 模式:lane1 **gpt-5.6-sol@xhigh**(codex)完成;lane2 grokBuild grok-4.7-build-fast-xhigh **provider_error**(模型不在发现集);lane3 cursor grok-4.6 **provider_error**(ACP 参数选择失效)——**单通道完成** | 完成(单 lane;总裁决「需返工」→返工即本 v1.0) | OQ13=(4)D/OQ14=(1)/OQ15=(2)A5/OQ16=(1)/OQ17=(4)B2+B3/OQ18=(1);R1 不认、R2/R3 认有条件;P0×4+P1×8+P2×4 全部折入(附录 C);返工范围局部可控,A5/B2+B3/两表架构维持,不需要扩大到 recall 或装配层 |
