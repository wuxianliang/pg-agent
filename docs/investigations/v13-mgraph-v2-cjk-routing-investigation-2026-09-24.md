# v13 mgraph v2 计划前置调查:CJK 路由升级(2026-09-24)

**性质**:只调查不开发。本报告为唯一新增文件(未跟踪,不提交);零代码改动、零 gate 改动、不 commit。
**触发**:`docs/investigations/v13-dp9-mgraph-demo-trial-2026-09-24.md` 发现 2——真实栈 4/4 walk 全 superset,OQ3 确定性升权规则对含 CJK 段的查询恒不可达。
**并行调查注记(仅此一句)**:另一代理在调查候选发现+矛盾通路(`v13_mgraph_candidates`/cons_pairs/build);本报告不碰那两个主题,唯一交集在 §2.3「修哪个先」。

---

## 0. 一页摘要

- **现状规则表**(§1.1):`v13_mgraph_route` 三态序 jev > superset(CJK) > deterministic;deterministic 内互斥序 why > when > 大写实体 > semantic,被点名桶权重 = `deterministic_floor+1`(偏差 #20),multi_hop/recency 点名子串额外加升;**任意一个 CJK 码点即短路进 superset,意图检测整个不跑**(v13_mgraph.sql:1475-1483)。
- **代价结论**(§2):**当日已实现代价 ≈ 0**——trial 4/4 查询 evidence 全中(0.900/0.852/0.775)、负例正确空手;桶差异化遍历在真实图上**本来就没有东西可走**(零 jev 关系边,唯一先验边=temporal 链+1 条固化边),在 gate 夹具上同样从未被行使过因果/实体桶(E 组只插 temporal/consolidation 边,F9 只行使 semantic 桶)。缺陷是**潜伏的、以关系边存在为前提的**。反直觉点:纯 temporal 图上英文 WHY 升权反而比 superset **少** 2 个可用拉取槽(10 搁浅 vs 8 搁浅)——升权在空桶上是轻微负收益。
- **推荐设计**(§3):**设计 B = 混合语言优先级 + 中文意图锚词表进策略行**(A 是 B 的最小核心,C 图内容词法命中建议否决,D 不改+记录为「v2 若不做候选唤醒」时的可辩护退路)。词表沿 `entity_stopwords` 先例进 mgraph 策略 JSON(不变量 12 只约束数值,字符串数组已有先例),route 保持零 IO/STABLE,零 ask 不变量不动。
- **OQ 草案**(§5):OQ-13(CJK 意图锚与混合语言优先级,建议裁 B)、OQ-14(与候选唤醒的顺序捆绑,建议候选唤醒先行或同批)。OQ3 是 Oracle 裁决,v2 §1.3 必须以**新裁决记录修订**的形式改,不能静默改。
- **报告路径**:`docs/investigations/v13-mgraph-v2-cjk-routing-investigation-2026-09-24.md`(本文件)。

---

## 1. 现状机制图(代码级)

### 1.1 路由确定性规则全表(实码)

`v13_mgraph_route(p_query)`(`v13/mgraph/v13_mgraph.sql:1448-1505`,plpgsql STABLE,零 IO):

| 步骤 | 实码位置 | 规则 |
|---|---|---|
| 读策略 | :1459-1461 | `deterministic_floor`(种子=1);`v_raised := v_floor + 1`(偏差 #20:计划只说「升权」,实施钉 floor+1) |
| CJK 扫描 | :1463-1472 | 逐字符扫**整个查询**,任一码点落入五区间(12352-12543 片假/平假、13312-19903 扩展 A、19968-40959 统一表意、44032-55215 谚文、63744-64255 兼容)→ `v_cjk := true` **EXIT**(首字符命中即止)。五区间=对 `v13_query_segments`(`v13/recall/v13_recall.sql:33-39`)码点表的**内联复制**,非调用 |
| 模式三态 | :1475-1481 | `routing_mode='jev'` → jev;**`ELSIF v_cjk` → superset;ELSE → deterministic**。CJK 判定在意图检测之前短路 |
| 权重底座 | :1482 | 六桶全初始化为 floor(权重全向量六桶全有值——allocate 输入契约,计划 §1.3-OQ3) |
| 主意图互斥 | :1483-1488 | **仅 `v_mode='deterministic'` 时执行**:`position('why' IN lower(q))>0` → causal;ELSIF `'when'` → temporal;ELSIF `cardinality(v13_mgraph_entities(q))>0` → entity;ELSE semantic。互斥序 why > when > 大写实体 > semantic(偏差 #20:防「Why」同时匹配实体形态造成并列) |
| 升权 | :1489-1492 | 主意图桶 := floor+1,其余保持 floor |
| 点名加升 | :1493-1500 | `multi_hop`/`multi-hop` 子串 → multi_hop := floor+1;`recency` 子串 → recency := floor+1(与主意图**叠加不互斥**) |
| 输出 | :1501-1505 | `{mode, weights}`(六键数值) |

大写实体检测 = `v13_mgraph_entities`(`v13_mgraph.sql:660-666`)→ `v13_mgraph_entities_of`(:646-658):段面 `^[A-Z][a-z]+$` 减 `entity_stopwords`——**CJK 段天然不匹配**(OQ10:中文无大写形态,实体抽取对 CJK 是空集,gate D7 直测:test_mgraph.py:1035-1039)。

### 1.2 CJK 段如何强制 superset(缺陷机理)

短路序是关键:模式判定(:1475-1481)在意图检测(:1483-1500)**之前**,且 `ELSIF v_cjk` 分支直接锁死 superset。后果:

- **混合语言查询**(trial Q1 `why Zephyr 无法登录`、Q2 `when 恢复 登录`):查询里明明有 ASCII 意图词 why/when,但因含 CJK 码点,`v_mode='superset'`,意图检测整段被跳过——why→causal、when→temporal、大写实体→entity **永不可达**。
- **纯 CJK 查询**(为什么部署失败):同理 superset;且当前**没有任何中文意图锚词**——即便不短路,deterministic 分支也只有英文规则。
- **纯 ASCII 查询**(why did the deploy fail):正常 deterministic——但**词法锚定在中文节点池上失败**:`v13_mgraph_anchors`(:1649-1672)→ `v13_build_tinql`(全语段 AND 连接,v13_recall.sql:89-92)→ stannum `==>` 谓词扫描,ASCII 段(why/did/fail)在中文正文节点上不命中 → BM25 AND 语义零候选 → walk 无锚。
- 三者合取:**在以 CJK 为主的语料上(DP5/OQ7 的立论前提),确定性升权分支没有一条可达路径**。唯一能走的组合 = 含 CJK 段(可锚定)∧ superset(升权死)。trial 实测 4/4 全 superset 即此。
- 既有逃生门:`routing_mode='jev'`(策略翻版)对 CJK 不短路——六问真问(每查询 +1 ask 批),signal `mem_route::<qhash>::<桶名>@<gen>`(偏差 #15:`<graph>` 槽=桶名,六问才不撞 signal);但 jev 模式与 deterministic 的零费定位冲突,OQ3 裁的就是「默认不调」。

### 1.3 allocate 如何消费 weights

`v13_mgraph_allocate(p_weights)`(`v13_mgraph.sql:1511-1605`,STABLE 纯函数):

1. 输入校验:恰六键数值、非负(:1522-1547);全 0 → 六桶改 1 再分配(:1546-1548,jev 全零回退的 superset 入口)。
2. Hamilton 最大余数:`quota_i = B·w_i^e/Σw^e`(`B=total_graph_budget` 种子 20,`e=probability_exponent` 种子 1.5;:1554-1561);floor 取整,余数降序+**名字升序**补齐(:1562-1575)。
3. 借位:权重>0 而 floor 后=0 的桶,向当前最大且 ≥2 的桶借 1(并列名字升序),借不到 V3009(:1576-1595)。
4. **配额单位 = 该桶可拉取的邻居节点数**(候选扩展次数,Jev-Mem `used[graph]` 语义;非边数非 ask 数——计划 §3.4 Oracle 审核 P1-2)。

消费链(读环 `v13_mgraph_next_action`,:1860):route(:1896)→ `weights` → `allocate(weights)`(:1905)→ 存进 `memory_walks.budgets.quota`(:2139);`primary_bucket(weights)`(权重最大、并列名字升序,:1608-1612)决定锚的 need_g 桶(偏差 #28)与 `v13_mgraph_anchors` 的 bucket 标签(:1907)。jev 模式在 walk 开轮时读六 Noul、低于 `graph_activation_threshold` 归零、全零 → 全 0 向量交 allocate 走 superset(:2178-2201)。

### 1.4 桶→rel 遍历与配额消费后果

- 映射 `v13_mgraph_bucket_rels`(:1389-1402):semantic→{semantic,related_to,redundant_with,contradicts}(固化子型边经此可达);temporal→{temporal};causal→{causes,caused_by};entity→{entity};recency→{temporal}(调用方按 source_at 近者优先);multi_hop→**全部 rel** 仍只扩一跳。
- expand 动作(`v13_mgraph_run_round` 内,:2259-2338):按桶序 **causal,entity,multi_hop,recency,semantic,temporal** 逐桶消费配额;recency 走 `ORDER BY source_at DESC`(:2272-2295),其余走 `structural DESC NULLS LAST, dst_hash ASC`;去重(visited∪pending);邻居被**首个拉它的桶认领**(偏差 #28 先到先得)。配额跨轮持续扣减(存 budgets.quota)。
- **后果(当前图形态)**:jev 关系边为零时,causal/entity 桶配额**整桶搁浅**(无邻可拉,槽位不回收、不转移);可用的只有 multi_hop(全部 rel,含 temporal+固化边)、recency/temporal(temporal 链)、semantic(固化边)。配额内无新邻 → `stop_reason='depth'` 收束(偏差 #24,搜索穷尽语义)。trial 的读环正是这个形态:「BM25 锚定 + 时间邻居」,判断面只剩 traversal/stopping 两族。

### 1.5 实测形态与计划文本的偏差点(与本调查相关者)

| 偏差# | 内容 | 与 CJK 路由的关系 |
|---|---|---|
| #15 | routing signal `<graph>` 槽=桶名(防六问同 signal 碰撞) | 词表方案不触碰 signal 形状;deterministic 模式仍零 mem_route 行 |
| #20 | 升权值=floor+1;主意图互斥 why>when>实体>semantic | 中文锚词必须接进**同一条互斥链**,不能另立并行判定 |
| #24 | 无可扩展邻居 → depth 收束 | 空桶搁浅的安全出口;升权在空桶上不炸、只是浪费 |
| #28 | 锚 need_g 取主桶(并列名字升序);邻居带认领桶 | superset 全并列时主桶=causal(名字序)——锚的 need_g 恒=floor,λ3 项对全体锚同值,排序影响归零 |
| 计划 §1.3-OQ3 文本 | 「CJK 段(`v13_query_segments`)→superset」 | 实施是**内联码点扫描**而非调用分段器(:1463-1472 vs v13_recall.sql:33-39)——语义等价(任一 CJK 字符⟺存在 CJK 段),但两处码点表漂移风险;v2 顺手应改为复用 |
| 计划 §1.4-15 | mem_route signal 必含 mgraph_generation | 不受影响;词表翻版走 policy_version,walk 身份 `(sid,qhash,generation,policy_version)` 天然换新 |

gate 面:E2(test_mgraph.py:1558-1591)= 英文 WHY→causal 严格最大 + CJK「为什么部署失败」→superset 全桶 ≥floor 且 allocate 每桶 ≥1 + CJK walk asked=0;E4 首轮 calls_used=6(1 停止封+5 遍历封);**E 组夹具只插 temporal/consolidation 边**(:1730-1734 仅 1 条 temporal;F9 固化边行使 semantic 桶)——causal/entity 桶的差异化遍历**在 gate 里也从未被行使过**。

---

## 2. 实际代价评估

### 2.1 superset 六桶全 floor、B=20 的配额走向(手算)

种子 `deterministic_floor=1`、`total_graph_budget=20`、`probability_exponent=1.5`。superset 权重全 1:

- `w^e` 全 =1,Σ=6;`quota_i = 20/6 = 3.3̄` → base=3 ×6=18,余 2;
- 余数全并列(1/3)→ 名字升序终裁:causal、entity 各 +1;
- **终配额:causal 4,entity 4,multi_hop 3,recency 3,semantic 3,temporal 3(Σ=20)**。

对照(同 B/e):

| 查询形态 | causal | entity | multi_hop | recency | semantic | temporal | 搁浅槽(当前图形态) |
|---|---|---|---|---|---|---|---|
| superset(CJK,现状) | 4 | 4 | 3 | 3 | 3 | 3 | causal+entity=8 |
| deterministic WHY(英文,causal=2) | 7 | 3 | 3 | 3 | 2 | 2 | causal+entity=10 |
| deterministic WHEN(temporal=2) | 3 | 3 | 3 | 2 | 2 | 7 | causal+entity=6 |
| jev(仅 causal Noul 0.9 过阈) | 20 | 0 | 0 | 0 | 0 | 0 | — |

(WHY 手算:2^1.5=2.828,Σ=7.828;causal quota 7.225→base 7;其余 2.554→base 2;余 3 票给五个并列 0.554 中名字最前的 entity/multi_hop/recency。)

**在 trial 的图(12 节点、11 条 temporal、1 条固化 redundant_with、0 jev 边)上的可用拉取槽**:superset = multi_hop 3 + recency 3 + semantic 3(实际只有 1 条边) + temporal 3 ≈ 10;英文 WHY = 3+3+2+2 = 10(semantic 同样封顶 1)。**反直觉结论:在零关系边的图上,确定性升权不带来任何遍历收益,反而把更多配额押进空桶**(10 搁浅 vs 8 搁浅)——superset 是对「不知道哪桶有货」的合理对冲。这正是 OQ3 把 CJK 绑 superset 的原始直觉(低置信→超集)在**图还很稀疏时**恰好无损的原因。

### 2.2 「单桶升权」在什么图形态下才有真实差异

升权从「无差异」变「有差异」需**同时**满足四个条件:

1. **主意图桶有货**:图上存在 ≥5 个量级的、经该桶 rel(causes/caused_by 等)可达的候选——配额 7 vs 4 的差值要在边际上体现,前排候选须超过 4 个;
2. **B=20 是绑定约束**:walk 因预算收束而非 evidence 早停/搜索穷尽(trial 三个正例全部 `evidence` 早停,预算远未用满);
3. **答案不经词法锚定可达**:目标节点与查询无 token 重叠(改写、指代、概括),只有沿关系边才够得着——trial 三个正例全部被 BM25 直接锚中(0.900/0.852/0.775),这正是**没**满足的条件;
4. **差异化遍历先于停止判据收割**:遍历判断(mem_trav)与停止(mem_stop)的节奏不被 superset 的均匀扩散提前触发 evidence 停。

条件 1 依赖**关系边存在**——当前被候选休眠缺陷卡死(§2.3);条件 3 依赖**查询与正文的词法失配**——BM25(stannum AND tinql)在 CJK 分段下面已经是「短语全含」语义,中文改写查询很容易整段不重合,这一条件在真实使用里**常见**。故:缺陷的真实代价曲线是「关系边密度 × 查询词法失配率」的乘积,当前两项都≈0,已实现代价≈0;两项任一增长后代价显形。

### 2.3 与「候选休眠缺陷」的相互作用(修哪个先)

候选休眠(试验发现 1):build 的关系发现用锚节点**全 body 的 AND tinql**(§3.4⑦),真实对话两条消息互不包含对方全部段 → 候选恒为自身 → 零关系信封 → 零 jev 边(偏差 #12 的实测确认;且 mem_rel_entity 闸结构性不可达)。相互作用矩阵:

| 修法 | 图上有关系边? | CJK 升权可达? | 净效果 |
|---|---|---|---|
| 只修 CJK 路由 | 否 | 是 | **零可观测量**:桶差异化仍无货可走;配额分布变了但都落在 temporal/multi_hop 拉取上;gate 只能证明「路由输出变了」,证明不了「检索变好」 |
| 只修候选唤醒 | 是 | 否 | 英文查询获得差异化遍历;中文查询(主语料)仍 superset 均匀扩散——差异化面存在但主语料不行使 |
| 两个都修 | 是 | 是 | 完整价值:为什么→causal 沿因果边走、何时→temporal 沿链走 |

**结论:候选唤醒是 CJK 路由升级的收益前提(先决),CJK 路由升级是候选唤醒在主语料上的价值放大器(后继)**。单独先行修路由 = 花费 gate/词表工程成本买一个不可观测的改动;两个都进 v2 时应排在候选唤醒之后(或同计划不同 stage)。另注意 gate 侧对称缺口:即便两修,现有 E 组夹具也没有「causal/entity 桶有货」的行使面——v2 需要**新增**差异化遍历行使夹具(插 causes/caused_by/entity 边驱动 walk),否则修完仍是「机制在位、从未被断言」。

### 2.4 诚实结论

- **已实现代价 ≈ 0**:trial 4/4 evidence 全中、负例正确空手;读环退化为「BM25 锚定+时间邻居」但照样命中全部查询。CJK 路由缺陷**今天没有造成任何一次漏答或多花钱**(superset 零 ask,与 deterministic 同费)。
- **潜伏代价真实但条件性**:全部押在「关系边出现 × 查询词法失配」两个前提上;前者被候选休眠卡死,后者在中文改写查询里常见。图一旦成熟(关系边密度上来),superset 的均匀扩散会把预算摊给空桶、把因果/时间问题的遍历优先级抹平。
- **对称的隐性收益**:
  (a) superset 在稀疏图上是**更优**配置(§2.1 搁浅槽对比);(b) 需要 CJK 意图分桶时,`routing_mode='jev'` 是既有逃生门(代价=每查询 1 ask 批/6 问,与 OQ3「默认不调」的零费定位冲突,但机制已在位并有 D12/jev gate 覆盖)。
- **判定**:这不是 P0/P1 级缺陷,是「v2 与候选唤醒捆绑交付的改进项」;单独作为 v2 主菜不成比例。

---

## 3. 替代设计清单

> 每条按任务要求评估:机制/确定性/零 ask 不变量(deterministic 模式 routing asked=0)/策略键形状/词表进 mgraph JSON(不变量 12)/gate 影响与 E2 断言改写。A⊂B(B 含 A 为最小核心);C/D 独立。

### 设计 A:混合语言查询优先级(最小改动,CJK 从「短路」改为「兜底」)

- **机制**:`v13_mgraph_route` 模式判定重排——去掉 `ELSIF v_cjk → superset` 的优先位置,deterministic 意图检测(why/when/大写实体)对**全查询**执行;**未命中任何锚且含 CJK → superset**;未命中纯 ASCII → semantic 主意图(现状)。效果:混合查询 `why Zephyr 无法登录` 恢复 why→causal;纯 CJK 查询仍 superset(没有中文锚)。
- **确定性**:纯函数(查询,策略行),无 IO,STABLE 不变。✅
- **零 ask**:route 不发问,deterministic/superset 双模式 asked=0 不变。✅
- **策略键**:零新键。零词表。
- **gate 影响**:E2 增补一条混合查询断言(`why Zephyr 无法登录`→deterministic causal 最大);CJK superset 断言改用无锚纯 CJK 例(如 `数据库备份策略`,trial Q4 原文)。其余不动。
- **得失**:改动最小(一个分支重排);但**主语料收益残缺**——纯中文「为什么…」仍 superset,而 trial 的 4 个真实查询里 3 个含 ASCII 意图词是埋点巧合,自然中文提问多数不会夹英文 why/when。单独采买价值有限,适合作为 B 的组成部分落地。

### 设计 B:中文意图锚表(推荐)——A + 词表进策略行

- **机制**:在 A 之上,deterministic 意图链插入中文锚词检测,沿用**同一条互斥序**(偏差 #20):`why-词表 ∪ 'why'` > `when-词表 ∪ 'when'` > 大写实体 > semantic;被点名桶=floor+1,multi_hop/recency 点名加升不变。词表仅 causal/temporal 两桶(词表工程见 §4);entity 桶**不做中文锚**(见下)。CJK 判定顺手改为复用 `v13_query_segments`(消除 :1463-1472 的码点表内联复制)。
- **entity 桶中文怎么办**:中文无大写形态,`^[A-Z][a-z]+$` 类形态学锚不存在。选项:(i) **v1 不做,entity 桶对 CJK 保持 semantic 主意图兜底**(推荐——实体语义命中已由候选面 `entity_jaccard` 承载,桶差异化留给英文/jev 模式);(ii) 问句代词锚(「谁/哪个」→entity)——语义上「谁-问句」≈实体查找意图,但置信度低于 why/when 词表,且 Jev-Mem entity 桶语义=实体关系遍历,不是实体命名识别,建议作为 OQ 附件的可选支不进推荐;(iii) 图侧实体词典——同设计 C 的内容依赖,否。
- **确定性**:词表=策略行内容,route 纯函数(查询,活动策略行);翻词表=新 policy_version → walk 身份换新(天然 A/B 面)。✅
- **零 ask**:不新增任何 IO;`v13_mgraph_policy()` 本就在 route 内读(:1459)。✅
- **策略键形状**:`"routing_intent_causal": ["为什么", …]`、`"routing_intent_temporal": ["何时", …]`(text[] 进 mgraph 策略 JSON;空数组=回退现状 superset)。**不变量 12 合规**:该不变量约束「策略**数值**只从 mgraph 行读;函数体不出现 0.60/20/5/0.85 等**字面阈值**」——字符串词表不受数值禁令约束,且已有**先例 `entity_stopwords: []`**(种子 JSON+mgraph.sql:651-653 消费)。读取器 `v13_mgraph_policy()` 的键集全等校验(:209-214)需加两键=新策略版本+读取器同批改。
- **gate 影响与 E2 断言改写**:
  - E2「CJK query is a superset」分句**替换**为:「为什么部署失败」→ deterministic 且 causal 严格最大(与英文 WHY 断言同形,test_mgraph.py:1561-1567 复用);
  - **新增**无锚纯 CJK 例(`数据库备份策略`)→ superset、全桶 ≥floor、allocate 每桶 ≥1、walk asked=0(原 :1568-1591 夹具平移);
  - **新增**混合例(`why Zephyr 无法登录`)→ deterministic causal;
  - 英文 WHY/E4 calls_used=6/E9/D12/shadow frontier 全等**全部不变**(deterministic 模式仍零 mem_route 行;夹具无关系边,配额变化不触断言);
  - 策略形状 gate(A2 族)随键集扩展更新。
- **代价**:route 函数重写一小段+策略版本+读取器键集+E2 改写;词表维护面(§4)。风险:锚词误触发把 wrong-bucket 升权(配额偏斜一格,危害=floor+1 与 floor 的差,轻)。

### 设计 C:CJK 词法最大命中桶(否决倾向)

- **机制**:对六桶分别统计查询段在「该桶 rel 可达子图」上的词法命中数,取 argmax 为 primary。
- **确定性**:❌ **破坏**。routing 变成(查询,策略,**图内容**)的函数——需读 memory_links/memory_nodes;同 (query,generation) 下固化采纳(边插入)会改变 routing 输出;route 从 STABLE 纯函数退化为图依赖查询,E2 断言必须绑图夹具,「同输入同输出」的可再现 gate 形态被破坏。
- **零 ask**:✅(仍是 SQL 计数)但把候选发现的 BM25 语义**复制**进路由——读环第③步本来就是词法锚定,路由再做一遍是双计费。
- **策略键**:需归一化/打分形状键(数值)——键面膨胀且语义含糊。
- **否决理由汇总**:破坏路由纯度(OQ3 把 deterministic 定位为「廉价零 ask 信号,不是检索遍」);与候选发现职能重叠;gate 不可钉。**若要「图内容感知路由」,正名做法是 jev 模式六问**(模型看图答桶),那已经是 OQ3 裁过的备选支。

### 设计 D:不改 + 记录

- **论证(支持面)**:①已实现代价≈0(§2.4);②收益前提(关系边)被候选休眠卡死——修了也无可观测;③B2 未接线,evidence 无消费者,端到端无法 A/B;④词表工程有维护与误触发成本;⑤需要时 `routing_mode='jev'` 逃生门在位。**v2 若不含候选唤醒,选 D 是可辩护的**。
- **论证(反对面)**:①主语料是 CJK(DP5/OQ7 立论),deterministic 路由「存在但对主语料不可达」是常设不自洽;②随图成熟代价显形,晚修要补更多夹具;③修法便宜(设计 B 全部改动面=一个函数段+两策略键+E2 三条断言)。
- **形态**:若选 D,v2 计划 §1.3 以新裁决记录「OQ3-CJK 维持现状+依据+触发条件」(触发=候选唤醒交付∧关系边密度观测达标),并在偏差台账/README 记一行——不能只靠 trial 报告埋钩。

---

## 4. 词表工程

- **覆盖面(建议闭集,≤8 词/桶)**:
  - causal:为什么(口语核心)、为何/缘何/何以(书面)、原因/缘故/成因(名词性)、怎么回事/怎么会(口语短语)。
  - temporal:何时(书面)、什么时候/啥时候(口语)、几点(时刻)、哪天/哪一年(日期)、多久(时长)。
- **歧义误触发(英文先例=OQ3 已接受 substring 语义:`'when' ⊂ 'whenever/whence'` 同阶风险)**:
  - 「几点」⊂「**以下几点**需要注意」——真误触发(非时间意图);缓解:接受(代价=wrong-bucket 一格升权,轻)或删「几点」留「什么时候」;建议 v1 收录并在词表注释记歧义例;
  - 「怎么」**单字组不收**(怎么用=how-to,非 causal)——只收「怎么回事/怎么会」整短语;
  - 「原因」在陈述句(「没有原因」)里出现——routing 只作用于查询文本,陈述性查询少见,风险可接受;
  - 「何」单字禁用;「会」单字禁用(「怎么会」的尾部不可独立成锚)。
- **体积与形状**:总计 ~15 词,两 text[](每词 ≤256B 沿分段纪律);进策略 JSON(`entity_stopwords` 先例);**不进函数体**(热调+单一真相);空数组=现状回退;词表变更=新 policy_version=新 walk(不需数据迁移)。
- **维护纪律**:词表是策略不是代码——上游(Jev-Mem)无此物,属 v13 本地新增,来源标注同 `consolidation_max_body_bytes` 先例(v13 本地护栏,计划 §3.2 注)。

---

## 5. OQ 草案(供 v2 计划 §1.3;OQ3 为 Oracle 裁决,v2 须以「新裁决记录修订」形式记载,不能静默改)

### OQ-13(暂号)CJK 意图锚与混合语言优先级 —— 建议裁决:B(词表+混合优先);备选 A(仅混合优先)/D(不改+记录);C(图内容词法命中)建议否决

- **依据链**:trial 发现 2(4/4 superset,升权不可达,`v13-dp9-mgraph-demo-trial-2026-09-24.md` §4/§8);OQ3 原文「低置信/CJK/缺失绑超集」的语义是**置信度兜底**而非「CJK 不可判」——中文意图词与英文 why/when 同为高置信词法信号,原裁决未排除中文锚,只是 v1 未做;`entity_stopwords` 先例(字符串数组进策略行);主语料 CJK(DP5 §4.8/OQ7 立论同源);已实现代价≈0 与收益前提缺失(§2)支持「与候选唤醒捆绑」而非独立急修。
- **机制**:route 检测序:①routing_mode=jev→jev;②意图锚(latin 子串 why/when+中文词表,同一互斥链,floor+1,multi_hop/recency 点名加升);③未命中∧含 CJK→superset 六桶 floor;④未命中纯 ASCII→semantic。CJK 判定复用 `v13_query_segments`(消内联复制)。entity 桶中文不做(semantic 兜底;「谁→entity」作可选支挂 OQ 附件)。策略键 `routing_intent_causal/temporal: text[]`。
- **零 ask**:deterministic/superset routing asked=0 不变;route 无 IO。
- **Gate**:E2 按 §3-B 改写(替换 CJK-superset 分句+新增无锚/混合两例);A2 族随策略键集扩展;D12/E4/E9/shadow 不变。
- **捆绑条件**:本 OQ 的交付 stage 排在候选唤醒 stage 之后(见 OQ-14);若 v2 无候选唤醒,降级为 D(不改+记录,触发条件写明)。

### OQ-14(暂号)与候选唤醒的顺序 —— 建议裁决:候选唤醒先行或同计划同批,v2 新增差异化遍历行使 gate

- **依据**:§2.3 交互矩阵——零关系边图上路由升级零可观测量,gate 也无法证明「检索变好」;且现有 E 组夹具本就只有 temporal/consolidation 边,causal/entity 桶遍历从未被任何 gate 行使(F9 仅 semantic 桶)。
- **机制**:v2 计划里候选发现唤醒(并行调查主题,本报告不展开)先行/同批;CJK 路由 stage 引用其产物;两 stage gate 各自独立绿。
- **Gate**:v2 新增「差异化遍历行使」夹具:手工插 causes/caused_by/entity/semantic 边,断言 WHY 查询 causal 配额被优先消费、桶认领正确(偏差 #28 面)、superset 对照查询均匀扩散——否则两修之后机制仍「在位但未被断言」。

---

## 6. 参考与证据清单

| 证据 | 位置 |
|---|---|
| OQ3 裁决全文 | `docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md`:77-80(§1.3) |
| 不变量 15(signal 含 generation) | 同上 :145(§1.4) |
| 策略种子 JSON(39 键) | 同上 :281-305(§3.2);实码 `v13/mgraph/v13_mgraph.sql:155-171` |
| allocate/一跳过渡/配额语义 | 同上 §3.4;实码 allocate `v13_mgraph.sql:1511-1605`、bucket_rels :1389-1402 |
| E1/E2/D12 gate | 同上 §5(:432/:439);实码 `v13/mgraph/test_mgraph.py`:1520-1591(E1/E2)、D12(jev 夹具) |
| route 实码 | `v13/mgraph/v13_mgraph.sql:1443-1505`(CJK 扫描 :1463-1472、三态 :1475-1481、意图链 :1483-1500) |
| CJK 码点表(分段器权威) | `v13/recall/v13_recall.sql:13-86`(区间 :33-39) |
| 实体抽取(OQ10,CJK 空集) | `v13/mgraph/v13_mgraph.sql:642-666`;gate D7 `test_mgraph.py:1034-1046` |
| expand/配额消费/jev 权重归零 | `v13/mgraph/v13_mgraph.sql:2259-2338` / :2178-2201 |
| 偏差台账 #15/#18-#28 | `v13/mgraph/README.md` 实现偏差台账 |
| 真实栈实测(4/4 superset、零关系边) | `docs/investigations/v13-dp9-mgraph-demo-trial-2026-09-24.md` §3/§4/§8 |
