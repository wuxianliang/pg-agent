# v13/mgraph — DP9 M1 暗库 + M2 写与重建 + M3 读环 B1 + M4 固化 + v2 V1 候选发现唤醒 + v2 V2 矛盾通路

Stage 15/15(SQL_LOAD_ORDER 第 15 位,纯末尾追加)。消费 schema→periphery
全部前序 14 文件;本 stage 库 = `agent_v13_mgraph`(`files_through('mgraph')`
前缀切片,15 文件;stannum 前置探针 fail-closed,形态照 memory/summary)。
设计:`docs/designs/v13-context-on-pg.md` v2 §4.4/§6.1/§6.5/§8。计划:
`docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md`(M1=暗库;M2=写与
重建;M3=读环 B1;M4=固化)+ `docs/plans/v13-dp9-mgraph-v2-plan-2026-09-24.md`
(V1=候选发现唤醒+V2=矛盾通路,均已交付)。gate:
`uv run python v13/mgraph/test_mgraph.py`(G-mg 族 **A+D+E+F+G+H 六组**,退出码
0=通过;write/read 默认关——D/E/G/H 写路径 gate 以「INSERT 新策略版本+翻
active」打开、测毕翻回 v2;固化链不读 write/read 开关,仅 `consolidate_mode=
'manual'` 响亮键执法;G 组锚面纯函数/直调可在默认关下测)。

## 机制(M1 范围;错误码一律 V3009)

1. **两表图承载(OQ1=A)**:`memory_nodes`(PK `(session_id,content_hash)`,
   无 corpus 列、无指向 chunks 主键/seq 的 FK——OQ4;`content_hash` 自证
   CHECK=`v13_body_hash(body)`;origin∈episodic|consolidation;
   `source_hashes` text[] 全 64hex(guard 触发器承载,PG CHECK 不容子查询);
   consolidation 形状:source_hashes≥2 且 consolidation_key 必填,
   `ux_memory_nodes_consolidation_key` 部分唯一索引;episodic 必填
   `source_at`)+ `memory_links`(PK `(session_id,src_hash,dst_hash,rel,origin)`;
   rel 九值闭集 semantic|causes|caused_by|entity|temporal|proximity|
   contradicts|redundant_with|related_to;origin∈jev|temporal|proximity|
   consolidation;`CHECK(origin<>'jev' OR decision_id IS NOT NULL)`(OQ11
   不放宽);两端悬空由校验器查(M2 落地)。**零图扩展 DDL**(OQ1:AGE 不进
   运行时;源码 `cypher(` 计数=0)。行不可变:节点/边 UPDATE 触发器拒 V3009;
   DELETE 仅 owner(零授权面,留给 M2 重建)。
2. **索引**:stannum 单索引 `ix_memory_nodes_stannum`(body;M2 候选函数
   经它做 TINQL 谓词扫描,去注释源码绑定算符计数=恰 1——EXECUTE 串,
   memory 先例同款确切数)+ 一跳两向 btree `ix_memory_links_src/dst
   (session_id,src/dst_hash,rel)`(邻居函数 M3 落地,索引先行)。
3. **meta 与固化队列**:`v13_mgraph_meta`(每会话至多一行,build 首写;
   初值语义 generation=0/watermark=-1/rel_cursor=NULL/
   nodes_since_consolidate=0;读取器 `v13_mgraph_progress(uuid)` 对无行
   会话返回同组初值——A8 的断言面)+ `memory_consolidations`(固化队列,
   PK `(session_id,consolidation_key)` 同 key 至多一行——重试语义由
   effect attempt 承载;status∈queued|generating|adopted|rejected;
   「rejected 可审计」的载体;M4 消费)。
4. **策略行 `mgraph` v2**(§3.2 种子逐键 **41 键**;V1 就地升版(1→2):
   +`anchor_ngram_n=3`/`anchor_max_terms=48`,`candidate_top_k` 10→5
   (OQ15/OQ18;读取器键集全等串与类型域数组同批——**v1/v2 键集不兼容**,
   旧读取器读 v2 JSON 即 V3009;回退=恢复 v1 SQL+重建 stage,不能只翻
   active 标记);含 `write_max_asks=64`;
   `consolidate_max_body_bytes=32768` 为 v13 本地护栏非上游默认)。
   读取器 `v13_mgraph_policy()` fail-closed:键集漂移/类型域违例/权重
   五数和≠1/priority 非三值排列 → V3009;**「保留但响亮」键执法**:
   `admission_enabled=true`(OQ5)或 `consolidate_mode≠'manual'` → V3009
   (v1 无实现即配置错误,读取时炸;M2 build 只经本读取器取值)。
   函数体零动作阈字面量(0/1 域界与数组形状常数除外;anchor 域=
   非负/正整数,沿 v_nznint/v_posint 既有两档)。
5. **六族 mem_* 模板(29 枚)**:type×4(投影 `["body"]`)/rel×5
   (`["left","right"]`,含 v2 V2 `mem_rel_contradicts` v13-local 槽——题面
   为 v2 计划 §3.4 冻结候选原文,携带 criteria 对按组合规则 v1 拼接)/routing×6
   (`["query"]`)/stopping×4
   (`["query","evidence"]`)/traversal×4(`["query","candidate","path"]`)/
   cons×6(四 Noul+representation choice 闭集 `keep_separate|merge|promote|
   uncertain`+fidelity `["source","summary"]`)。题面=**入库快照**
   `QUESTION_SNAPSHOT.md`(上游 URL+commit `81574eb…`+每槽逐字+
   sha256;组合规则 v1 版本化写在快照头部:noul=instructions+' TRUE if: '
   +true+' FALSE if: '+false,choice 保留 criteria,`candidates[{index}]`
   钉 index=0;闸门对组合后 question 文本全等——A3)。draft→内容行→
   freeze 仪式照 summary/filter 先例;epoch='pre-finalize' 显式;
   noul 族 criteria=NULL(上游 true/false 文本已并入 question——缓存键
   含组合后字节)。
6. **judgment_defaults 追点 v4**(`$dp9def$` DO 块照 summary `$dp7def$`
   形态):既有 chunk_score/corpus_exists/summary_accept 三 point 逐字
   保留,**新增且仅新增六个 mem_ point**(翻后共九——A4):
   mem_relation/mem_type/mem_cons/mem_stopping/mem_routing 三态全
   exclude;mem_traversal 三态全 degrade(OQ11:写/固化 exclude、读
   degrade、缺停止不提前停)。读取器 `v13_mgraph_defaults_action(point,
   state)` 缺点/缺态 → V3009;限定 mem_ 前缀 point。
7. **信封构造器 `v13_mgraph_envelope(sid,state,questions)→jsonb`**:
   键集对齐活体 summary 信封十二键(sid,ctx,needed,templates,groups,
   budget,timeout_ms,candidate_set_hash,provider,model,goal_hash,
   candidates);groups 恰一元素(一信封=一 state,全部问题共享同一
   projection,不变量 7);**batch_questions=问题数(1..32,不照抄摘要
   信封的 1)**——A9 夹具:四问类型信封恰一批 ask(judgment_calls 一行
   question_count=4);candidates 恒 `[]`、goal_hash 恒带(filter 代活体
   `v13_existence_ref`/`v13_filter_bodies_present` 必读);needed 行对
   criteria=NULL 的 noul 模板省略 criteria 键(既有 filter 先例,decisions
   的 noul CHECK 拒 jsonb null);provider/model 经 GUC fail-closed;
   `candidate_set_hash`=本批 signal 集合+state 的 sha256。**M2 加宽**:
   5 参重载 `v13_mgraph_envelope(sid,state,questions,provider,model)`
   (同文件新签名+3 参 OR REPLACE 委托体,A9 三参面/ACL 不变)——
   `typesafe.provider` 是占位符 GUC,首次判断 IO 加载 typesafe 库时被
   清除且前缀保留不可重设(一条连接一旦 ask 过就再也无法构造信封),
   build 循环「信封→resolve→信封」必须在起点一次捕获并显式传参
   (偏差台账 #11)。
8. **ACL(M1 面)**:recall/resolve/route 三角色对四表 SELECT;resolve=
   INSERT 节点/边+UPDATE memory_consolidations(settle 面,M4)+EXECUTE
   envelope/defaults 读取器;route=INSERT/UPDATE memory_consolidations
   (队列写入面,M4);策略读/进度读三角色;rebuild/verify/DELETE/表 DML
   其余面仅 owner;零 `SECURITY DEFINER`。M2–M4 各自追加其函数面
   (walk/round 表与 build/route/run_round/enqueue/settle 的 EXECUTE 授权
   随里程碑落)。
9. **源码扫描闸门(A7+M2 复扫)**:`typesafe_ask`/`v13_append_event`/
   `FOR UPDATE`/`mock_response`/`cypher(` 对本文件计数全 0(判断 IO 只经
   `v13_resolve_judgments`;本 stage 不碰会话锁);绑定算符去注释计数
   =恰 1(候选函数 EXECUTE 串,memory K4 同款 stripper)。
10. **实体/关键词/相似度(OQ10/OQ7 系数面)**:`v13_mgraph_entities_of(
    segs)`=`^[A-Z][a-z]+$` 减 `entity_stopwords`(锚定 ASCII 类,CJK 段
    天然不匹配不 RAISE;段面函数供锚项复用——V1 起 anchor 面经
    `v13_mgraph_anchor_terms` 去重保序,body 面仍全段(同源分段器、
    重复度口径不同));`v13_mgraph_keywords_of(segs)`=
    latin 段频次顶 `keyword_cap`(并列 token 升序);`v13_mgraph_jaccard
    (a,b)`=集合交并比,空并集=0。
11. **候选发现 `v13_mgraph_candidates(sid,tinql,k)`(OQ7;v2 V1 锚形态=
    A5)**:签名三参,`p_tinql` 必须来自 `v13_mgraph_anchor_tinql`——入口
    `v13_mgraph_anchor_guard` 本地文法守卫(引号短语 **OR** 闭集,非法输入
    V3005 fail-closed 不降级裸扫;recall 三函数字节不变,v2 计划 R2 修订
    OQ7 守卫面)把用户文本挡在 EXECUTE 串之外;锚编译器 `v13_mgraph_anchor_
    terms/tinql`(均 STABLE,经读取器取 n/max 两键,禁 IMMUTABLE——策略
    翻版必须能改变锚形态)=latin 段整项+CJK 段按字符 n-gram
    (`anchor_ngram_n=3`;段长=n 恰一项、<n 零项;0=全段 OR 语义退化),
    去重保序,超 `anchor_max_terms=48` 保序截断,空锚→空串→空集零 ask;
    CJK n-gram 项对 entity/关键词子项天然中性(不匹配 ASCII 字符类)。
    谓词驱动 stannum 索引扫描(禁裸表扫描后算分),池=本会话全部
    episodic(consolidation 不作锚);
    `score = lexical_coef·lexical_norm + entity_coef·entity_jaccard +
    keyword_coef·keyword_jaccard + candidate_recency_coef·recency`,
    lexical_norm=bm25/max(bm25)(池内归一化),recency=1/(1+Δsource_at 秒/
    halflife);并列 score DESC,content_hash ASC;同事务内同池两次调用
    字节级相同(D1/G7)。
12. **写路径 `v13_mgraph_build(sid,limit)`(§3.4①–⑨)**:①write 关→
    skipped:disabled 零写;②admission 真→V3009(读取器「保留但响亮」
    执法);③freshness.degraded→skipped:degraded;④整次 build 会话级
    `pg_advisory_lock(v13_lock_key(sid,'mgraph-build'))`(结束释放,异常
    路径解锁后重抛);⑤watermark 后按 seq 升序插 episodic 节点
    (ON CONFLICT 折叠保 source_at 最早者;source_at=events.at 经
    (session_id,seq_from) 回查);⑥先 DELETE 本会话 temporal 边再按
    source_at ASC,content_hash ASC 全量重连;⑦从 rel_cursor 之后按首现
    seq 推进:每节点类型信封(四 Noul 一 state,只记录)→anchor_tinql→candidates
    取对(锚自身除外),每 pair 一封关系信封(`v13_mgraph_pair_questions`
    =entity 闸单一事实源;v2 V2:canonical 方向(src<dst)加第四问
    mem_rel_contradicts,反向不加——request_hash 携带 pair ctx,双向入封
    会以不同哈希重复问同一 signal,违反「同一无序 pair 恰一套 signal」与
    同 signal 单行纪律),lexical_norm≥graph_activation_threshold 插
    proximity 边(structural=lexical_norm);帽(spend.over/
    write_max_batches/write_max_asks;计数=judgment_calls 行增量=每封发出
    即+1 含失败批)任一用尽→停在断点,resolve failed→停且该节点不标记
    完成;⑧apply_relations;⑨收尾一律先推 rel_cursor 到「类型+关系问
    全部落账」末节点再推 watermark 至其首现 seq,两列同批;generation
    仅图内容有净变化时 +1。
13. **`v13_mgraph_apply_relations(sid)`(§3.4⑧)**:扫本会话已答
    `mem_rel::` 行,各 rel 独立过 relation_threshold 才插边,ON CONFLICT
    DO NOTHING,不镜像反向;重入零 ask(迟到 decision 只补插未写过的边)。
    v2 V2:允许关系闭集=semantic/causes/caused_by/entity/**contradicts**
    (Oracle P0-2——算法不变仅扩闭集);contradicts signal 端点由
    `v13_mgraph_pair_questions` 保证 canonical(小,大)hash 序,边方向
    =signal 端点序——同一无序 pair 恰一套 signal 一条边(单向遍历不对
    称已裁接受,对端经词法锚定可达)。
14. **`v13_mgraph_rebuild(sid)`(§3.5)**:按端点删除(全部 episodic 节点
    +两端都不是 consolidation 节点的边——固化节点及其关联边幸存)→
    watermark=-1 且 rel_cursor=NULL 两列一起复位→build(无界 limit);
    同 key 咨询锁栈式重入;write 关/degraded 时 V3009 拒绝(偏差 #13)。
    毒化重建零调用:全局 judgment_cache 使全部信封 gap=0,failed=false、
    asked=0,temporal/jev/proximity 边集合字节级复现(D4)。
15. **读环 B1(M3,OQ2)**。`memory_walks`/`memory_rounds` 在本里程碑建
    (walk 唯一 `(session_id,query_hash,mgraph_generation,policy_version)`,
    status∈open|stopped;round PK `(walk_id,round)`)。驱动面
    `v13_mgraph_run_round(sid, query, elapsed_ms)`:每调用至多一封
    `v13_resolve_judgments`(mock 单批纪律,偏差 #19);逻辑轮在
    `memory_rounds` 收口。每轮事务取
    `pg_advisory_xact_lock(v13_lock_key(sid,'mgraph-build'))`,与 build
    的会话级同 key 锁互斥。零 effect、零 `resolve/failed`、不
    `FOR UPDATE sessions`。
16. **路由 `v13_mgraph_route(query)→{mode,weights}`(OQ3)**。确定性:
    主意图互斥 why>when>大写实体>semantic,被点名桶权重 =
    `deterministic_floor+1`,其余六桶保持 floor;`multi_hop`/`recency`
    仅查询点名(`multi_hop`/`multi-hop`/`recency`)时升到同一高度。
    CJK 段(与 `v13_query_segments` 同一码点区间)→ mode=superset,
    六桶都停在 floor,routing asked=0。`routing_mode='jev'` 才把六问
    放进 walk(signal `mem_route::<qhash>::<桶>@<generation>`,偏差 #15);
    低于 `graph_activation_threshold` 的 Noul 归零,全 0 走 allocate
    的 superset。shadow 在 walk 已 stopped 且 spend 有余量时另发一封,
    不改 frontier、不计入 `calls_used`。
17. **`v13_mgraph_allocate(weights)`**:Hamilton 最大余数,并列终裁序
    causal,entity,multi_hop,recency,semantic,temporal。全 0→六桶改 1
    再分配。权重>0 且 floor 后为 0 的桶向当前最大且 ≥2 的桶借 1;
    借不到 V3009。配额=该桶可拉的邻居节点数,和=`total_graph_budget`。
18. **一跳与停止**。邻居只来自 `v13_mgraph_neighbors(sid,hash,rels[],
    limit)`(出边;`structural DESC NULLS LAST, dst_hash ASC`)。桶→rel:
    semantic→{semantic,related_to,redundant_with,contradicts},
    temporal→{temporal},causal→{causes,caused_by},entity→{entity},
    recency→{temporal}(调用方再按 source_at 近者优先),multi_hop→全部
    rel 仍只扩一跳。过渡分用 §3.4 单式;Jev 分量缺失则丢掉该 λ。
    首轮锚=`v13_mgraph_candidates` 的 lexical top-k,再截到 beam。
    `v13_mgraph_should_stop(walk_id)→{stop,reason}`:四条停止 Noul 缺
    任一则不进 evidence/continue,硬顶照常;latency 由 run_round 在收轮
    时用驱动传入的 elapsed 写。`read_enabled=false` 或 freshness
    degraded → evidence 空集、零 ask、带 skipped。
19. **evidence `v13_mgraph_evidence(sid, query_hash)`(OQ8=B1)**。定位
    当前 generation + 活动 policy 的 stopped walk,按 score DESC,
    content_hash ASC 取 ≤`inject_top_k`。无 walk → 空集零 ask。不进
    `recall_candidates`,不改装配。
20. **固化链(M4,OQ6/§3.4①–⑥;v2 V2 B2 对源改 proximity-derived)**。选对=`v13_mgraph_cons_pairs`
    (同会话 `memory_links.origin='proximity'` 边、两端均 episodic → 按
    (source_at ASC,content_hash ASC) 规范化为无序对 (early,late) → 去重;
    digest=v13_mgraph_pair_digest(early,late)——v1 相邻对方向一致 ⇒
    字节级不变,决策缓存不失效;时间相邻但零词法激活的对不再进对源;
    排除仅 status='adopted');**诚实语义:这是由已落库的激活 proximity
    对(lexical_norm≥graph_activation_threshold 才插边)衍生的固化候选,
    不是所有历史关系封的审计池**——若产品要求覆盖低于阈值的已问对,
    须另建关系候选审计表(v2 计划 §7 停止条件);五问一封=`v13_mgraph_cons_questions`
    (redundant/contradiction/obsolete/link 四 Noul+representation
    choice,投影 ["left","right"],signal `mem_cons::<pair_digest>::
    <aspect>`,pair_digest=v13_body_hash(src||'>'||dst));生成门=
    `v13_mgraph_cons_gate`(choice∈{merge,promote} ∧ 所选概率 ≥
    consolidation_choice_min ∧ contradiction<consolidation_threshold;
    缺任一判断=exclude;obsolete 只作证据);子型=`v13_mgraph_cons_subtype`
    (priority 序首个 noul≥relation_threshold 的方面,无过阈者退 link)。
    resolve 侧 `v13_mgraph_consolidate(sid,limit)` 驱动发问(每调用至多
    一封真实 ask,一步一封同 #17/#19;eligible 报告在返回值)。
21. **生成升级 kind=`mgraph_consolidate`(M4)**。kind CHECK 第七值+
    `effect_attempt_cap` v3(七键,本键 cap=2,仪式照 summary)+窄
    `v13_requeue_stale`(活体 OR REPLACE,基底=periphery 库 pg_proc 导出
    活体,与 twophase:33 逐字一致):本 kind 与 judge 同待遇(cap 内回
    收 ready 只 fence+1、超 cap failed+lease_exhausted+唤醒),cap 判定
    按行 kind 调 `v13_attempt_ok(kind,attempt_no)`;其余 kind 行为字节
    不变(仍 unknown 墙)。三者与全链同一加载事务(禁先扩 CHECK 后补
    cap)。route 侧 `v13_mgraph_consolidate_enqueue(sid)`:入口失败收敛
    sweep(generating 行对应 effect 已死→rejected)→单活跃闸
    (ready|claimed|unknown→NULL,与 advance ① 同面)→按 priority 序选
    最高 eligible 对→队列行 INSERT(queued;rejected→queued 翻回=显式
    重入队)→`v13_enqueue_effect`(request 只含 purpose/left_hash/
    right_hash/consolidation_key/policy_version 五键)→行转 generating;
    worker 走 `v13_claim`/`v13_complete`(通用 CAS 分支:只有
    effect_done,零 llm/message、零 turn/end、零 resolve/failed,路由
    不 finish——F2)。resolve 侧 `v13_mgraph_consolidate_settle(
    effect_id)`:读 effect.result→确定性检查(非空、字节≤
    consolidate_max_body_bytes、两枚亲本哈希仍在;失败→rejected+
    body_hash 回填零 fidelity ask)→fidelity 信封(投影
    ["source","summary"],source=两亲本正文换行拼接)→include(≥
    consolidation_choice_min,见台账 #31)才插 consolidation 节点
    (source_hashes=两亲本、source_at=较晚者、consolidation_key)+固化
    边(src=left_hash,dst=产物哈希,rel=子型映射,origin=
    'consolidation')+行 adopted;非 include→rejected;幂等:
    adopted/rejected 行二次 settle 零 ask;settle 探测 effect 非
    succeeded 即 rejected。图变更段持 mgraph-build 同 key 事务级咨询锁。
    产物=远程层首批实现:检索对象是节点 content_hash,只经 semantic
    桶遍历可达,不作候选锚(F9)。

## 运维纪律(README 必记)

- **① 部署暗,翻开才走判断**:`write_enabled=false`+`read_enabled=false`
  (与 Jev-Mem 代码默认一致,`jev_mem_config.py:12-13`);默认双 false 下
  零 mem_ decision 落库、零装配影响。翻开=新 (name,version) 策略行+同事务
  翻 active(M2+ 的行为面就位后才可翻)。
- **② dec-refresh 注记(不变量 14)**:任何 `mem_%` 行落 decisions 会使
  活体 `v13_context_required` 的 `dec` 计数变化 → 下一次装配 token 失配
  一次 refresh(已知代价,不改 dec 定义);默认双 false 下零发生。同族:
  本 stage 模板种子在加载事务内逐模板 bump cgr(29 内容行+29 freeze=58,
  A5 断言 ≥29;实测恰 58)——在途回合一次 stale 失配,既有语义,重解析
  零 ask。
- **③ unknown 嘣注记(M4 已实施)**:固化 enqueue 闸面=会话已有
  `ready|claimed|unknown` 时返回 NULL(与 advance ① 同面,强于摘要闸的
  ready|claimed)。**代价:会话一旦落 unknown 墙,v1 永不能再固化**;
  清墙后恢复(运维动作),`consolidate_mode=manual` 下不调度。
- **④ candidate_set_hash 同列异义**:mgraph 信封的 csh=signal 集合+state
  的 sha256,**不是**文档召回的候选集摘要;既有按 judgment_calls 该列
  分组的花费分析会把两流混在一起(计划 §3.3 P2 注记;不改列,读侧自辨)。
- **⑤ stannum 前置**:本 stage 建索引依赖 characterize 已建 stannum
  扩展;setup_db.py 探针 fail-closed(缺扩展即退出码非 0,不加载)。
- **⑥ 题面快照是权威**:`QUESTION_SNAPSHOT.md`(上游 URL+commit+克隆
  日期+MIT 版权行+每槽逐字与 sha256)。`/tmp` 克隆仅抄录来源(本仓抄录
  时已与 codeload 该 commit tarball `diff` 验证逐字同);`/tmp` 失效时从
  commit 重取,摘不到对应槽则闸门保持红。题面漂移=新模板 version,旧
  决策自然失配(只费钱)。
- **⑦ 写帽预估(M2 已实施,OQ2;v2 V1 双口径改写)**:`judge_spend` 数
  judgment_calls 行=ask 批数;A5 3-gram k=5 下每新 episodic 节点 ≤6 批
  (1 类型封+≤5 关系封,k=candidate_top_k=5);`write_max_batches=8` 是
  **每次 build tick 的实际截断**——逻辑首建是**跨 tick 总量**(12 节点
  中文转录活体实测 59 ask≈8 tick,由 rel_cursor 续跑消化),
  `write_max_asks=64` 为单次调用累计帽,该形态下不成为主限制;
  session_asks_cap=512 与用户回合/读 walk 共享:**≈104 新节点=活体平均
  估计(≈4.9 ask/节点),非硬上界**;每节点硬上界=6 封,写路径隔离时
  保守上界≈512/6≈**85 节点**(k=10 饱和池旧估计≈46 适用于上调 k 后的
  最坏形态);开启 write 前按 transcript 规模评估/上调会话帽;失败批也
  计数(与 spend 行数同口径)。
- **⑧ provider 占位符与连接纪律(M2 实测)**:`typesafe.provider` 是
  占位符 GUC,连接上首次判断 IO 加载 typesafe 库时被清除、且 typesafe
  前缀已保留不可重设——**一条连接一旦 ask 过就再也无法构造任何信封**
  (v13_guc_required V3002)。build 在起点一次捕获 provider/model 并对
  本次调用内全部信封显式传参(5 参重载);**驱动侧应每 tick 用新连接跑
  build**(pg_cron 每次任务运行即新连接);已花费的连接上 build 会在
  捕获点响亮失败,不静默重键缓存。
- **⑨ 超长正文 fail-closed**:节点 body >4096 字节或段 >256 字节时
  `v13_query_segments` 抛既有 V3005(entities/tinql/candidates 全经它);
  不另造上限,与 OQ8 读面「超长仍由 v13_query_segments 抛既有 V3005」
  同向。上线前按 transcript 正文分布评估。
- **⑩ 读环步进(M3)**:`run_round` 每次调用至多一封。驱动循环到
  `next_action` 报 done。provider/model 在该 walk 第一次发问前捕获进
  `budgets`;已花费的连接上开新 walk 时,回退读本会话最近一条
  `judgment_calls` 的 provider/model(GUC 已被清除)。elapsed 由驱动
  累计传入,latency 只在收轮时比较。

## 明确不做(M4 后余项与 §8 台账)

- admission 五问(OQ5 不做;键 true→V3009);`consolidation_interval`
  自动计数(代码默认 0,论文附录「每 20 写」不采用);AGE(§8 台账三
  条件);B2 装配接线(下一张计划);walk/round 生命周期清理(保留策略
  =不清理,触发=下一张计划);自动固化调度(v1 manual,driver 显式调
  consolidate/enqueue/settle);**CJK 路由升级(v2 OQ13=D 不做:route/
  意图链/权重零改动,CJK→superset 语义维持 DP9-OQ3,两个
  routing_intent 策略键不进键集;重开条件=v2 计划 §8 三条夹具式触发,
  重开时须新计划显式 supersede DP9-OQ3)**。

## 实现偏差台账(M1 实施与计划的偏差,逐条)

1. **上游行号坐标漂移**:计划(§2.1/§3.3/附录 B)引用
   `jev_questions.py:284-427`、`memory_builder.py:308-315` 等行号,与
   所钉 commit `81574eb` 实际文件布局不符(jev_questions.py 实 163 行,
   函数位于 :44-157;common_words 实 :304-307)——计划行号出自探查时
   的工作坐标。快照按**实际 file:line** 抄录;槽位内容与计划清单完全
   一致(27 上游槽);`/tmp/Jev-Mem-main` 与 codeload 该 commit tarball
   `diff` 逐字同(验证于 2026-09-23)。
2. **组合规则 v1 由 M1 钉定**:计划只要求「组合规则写进快照头并版本
   化」;具体拼接形式(noul=instructions+' TRUE if: '+true+' FALSE if: '
   +false;choice 保留 criteria 闭集对象;`candidates[{index}]` 钉
   index=0)为本实施钉定并写入快照头版本化——后续改动=新规则版本。
3. **mem_cons_fidelity 题面为 v13 本地拟定**:计划槽位清单=27 上游槽;
   fidelity(OQ6 新增模板)无上游原文,题面仿 summary_fidelity 形态拟定,
   快照标注 `v13-local`。
4. **source_hashes 元素校验进触发器**:PG 不允许 CHECK 约束内子查询;
   64hex 元素校验由节点 guard 触发器承载(INSERT 校验+UPDATE 拒绝合一,
   均 V3009;A1 的 content_hash 自证仍是 CHECK)。
5. **新增 `v13_mgraph_progress(uuid)` 读取器**:计划 M1 函数清单未列;
   为使 A8 的 rel_cursor/watermark **初态语义**可断言而加(无行=初值
   {generation:0,watermark:-1,rel_cursor:null});M2 build 落行后复用。
6. **defaults 读取器限定 mem_ 前缀**:计划只要求缺点/缺态 V3009;实施
   加 `mem_` 前缀纪律(非 mem point 调用即 V3009)——mgraph 自己的缺省
   面,防误读 chunk_score 等他人 point。
7. **A5 cgr 断言方式**:计划「相对加载前增加 ≥1」;实施以 scratch 库
   (`files_through('periphery')` 前缀切片)测 cgr_pre、主库测 cgr_post,
   断言差 ≥28(每模板内容行至少一次;实测恰 56=28 内容行+28 freeze,
   行级触发器逐模板 bump 的直接验证)。scratch 库用后即 DROP。
8. **A9 断言按活体 resolve 返回形状**(periphery 代):{failed,gate_open,
   remaining,cache_hits,asked_batches,asked_questions,readback_rejects};
   断言 asked_batches=1/asked_questions=4/remaining=0/failed=false +
   judgment_calls 恰一行 question_count=4。
9. **信封 needed 行 criteria 省键**:criteria=NULL 的 noul 模板在
   needed 行省略 criteria 键(filter 既有 CASE 先例;decisions 的
   `v13_decisions_noul_shape` 拒 jsonb null)——对齐既有形态,零行为
   分叉,机制段第 7 条记明。
10. **新增 `v13_mgraph_pair_questions(src,dst,left,right)`(M2)**:计划
    函数清单未列;entity 闸(双方实体集非空且无交集才入问)做成独立
    纯函数=单一事实源+D7 直测面;build 消费同一函数。
11. **信封构造器 5 参重载+3 参委托体(M2)**:`typesafe.provider` 占位
    符在首次判断 IO 时被清除且不可重设(保留前缀)——build 循环必须
    起点一次捕获显式传参。同文件新增 5 参签名+对 3 参面 CREATE OR
    REPLACE 换体为委托(§1.2-1「活函数替换只允许在本文件」合规;
    M1 三参调用面/A9 断言/ACL 经 OID 保留均不变,5 参面另授 resolve)。
12. **mem_rel_entity 在写路径结构性不可达(M2 发现)**:候选发现用全
    body 的 AND tinql(§3.4⑦ 钉死),匹配候选的 token 集⊇锚 token 集
    ⇒ 候选实体集⊇锚实体集 ⇒ 交集非空 ⇒ entity 问永不入封。闸逻辑在位
    并经 pair_questions 直测(空侧/不相交两侧正反向);模板与 signal
    形状保留,未来窄查询面(M3 锚/词法放宽)出现即活。
    **V1 后记(2026-09-24)**:候选发现已换 A5 锚(latin 整项+CJK
    3-gram,OR 池),匹配候选不再蕴含锚 token 集,不相交实体对经真实
    build 得到 entity 问(G8)——原不可达推导失效;条目留档不改写。
13. **rebuild 在 write 关或 degraded 时 V3009 拒绝(计划未言明)**:
    rebuild→build 若 build skip 会留下「已删未建」的空图;取 fail-closed
    拒绝优于静默删库。D16 的复位态观察改用 spend 帽 0 夹具(内层 build
    正常进入、仅零 ask,复位值可断言)。
14. **D9 崩溃窗以「提交后删边」模拟**:单事务 build 内不存在「decisions
    已提交、apply 未做」窗口(两者同事务);被测机制=apply 幂等重入零
    ask——夹具先正常 build,再提交一次 DELETE jev 边模拟该窗,重入
    apply 断言边复原且 judgment_calls 零增量。
15. **D12 routing signal 的 `<graph>` 槽=桶名**:§1.5 形状
    `mem_route::<query_hash>::<graph>@<generation>` 中 `<graph>` 取
    semantic/temporal/causal/entity/multi_hop/recency 六桶名——若取
    图名常量,六问会在同一 signal 上碰撞(信封构造器拒重复 signal);
    代数仍入每份 signal(不变量 15),翻代即六份全换 request_hash。
16. **M1 索引注释一处更新(M2 编辑)**:原注释「本文件 `==>` 出现次数
    =0——候选函数 M2 才落」在 M2 落地后失真,改为「去注释源码计数=恰
    1」;注释内出现不计入 stripper 计数(memory K4 同款)。
17. **测试侧 mock 精确批纪律(D 组)**:GUC mock 单值只能精确回答一个
    ask 批形状(答案多键=V3001),而 build 每调用可发多封——D 组以
    write_max_batches=write_max_asks=1「步进」驱动(每次调用恰一个真实
    ask,预测下一信封=v13_gap 感知全局缓存;filter Conns 先例,连接
    ask 过即 recycle)。帽耗尽/续跑语义在此纪律下被真实走查。
18. **`run_round(sid, query, elapsed_ms)`(M3)**:计划正文把签名写成
    `(sid, p_elapsed_ms)`(强调 elapsed 是 latency 的唯一写入点)。查询
    文本是 walk 身份与信封 state 的另一半,无法从 query_hash 还原,故
    作为第三参。walk 行不另存 query 正文。
19. **读环一步一封(M3,同 #17)**:GUC mock 仍只能答一个批形状。
    `run_round` 每次只执行 `v13_mgraph_next_action` 给出的一个动作
    (一封 ask,或一次不计 ask 的 score/bind/expand/close)。逻辑轮在
    `memory_rounds` 收口;beam=5 的首轮 `calls_used=6`(5 遍历封+1
    停止封)。生产 provider 若要在一事务里问完一轮,把 next_action
    循环放进同一次调用即可,本里程碑不这么做。
20. **确定性升权值与主意图互斥(M3)**:计划只说「升权 / 其余保持
    floor」,没钉升多少。实施取升权桶 = `deterministic_floor+1`。
    主意图互斥序 why > when > 大写实体 > semantic,保证 WHY 查询的
    causal 严格最大(「Why」本身也匹配实体形态,若不互斥会并列)。
    `multi_hop`/`multi-hop`/`recency` 子串才把对应桶升到同一高度。
21. **`max_latency_ms` 允许 0(M3)**:M1 读取器把它放进 ≥1 正整数,
    E7 要求策略值 0(第一轮提交后即停)。同文件把该键挪到 ≥0 整数
    组;种子 15000 不变,A2 仍绿。
22. **信封丢掉非整数 `typesafe.timeout_ms`(M3)**:扩展默认值是时长
    串 `30s`。`judgment_calls.timeout_ms` 是 int,原样写入会把整批
    ask 打成 22P02(读环在 set mock 之后才构造信封,库已加载,GUC
    已是 `30s`;写路径每封都在新连接上、库尚未加载,所以 M2 没撞上)。
    非 `^[0-9]+$` 的值写成 JSON null;纯数字原样保留。
23. **E5 的 failed_timeout 由夹具种入(M3)**:本仓 pg_typesafe 的 HTTP
    等待不可被 statement_timeout 打断(setup 探针 sqlstate=08006,
    与 DP1 #45(b) / filter README #2 同族)。闸门断言的是 apply 分支:
    夹具插入 `judgment_calls.status='failed_timeout'` 且 payload 含
    邻居的部分 traversal signal。该节点不再补问;被覆盖的 signal=
    `default_timeout`,同节点没有 call 行的 signal=`default_missing`;
    该 call_id 对 `calls_used` +1 一次。无伪造 Noul,无无 decision
    的 jev 边。引擎能投递 57014 后可改成真超时。
24. **无可扩展邻居时以 depth 收束(M3)**:停止四问不命中、配额内又
    没有新邻居时,若保持 open 会空转。实施写 `stop_reason='depth'`、
    status=stopped(搜索穷尽,不是 `maximum_depth` 计数器)。frontier
    保留已收束的束。
25. **walk 身份是 md5 uuid(M3)**:`md5(sid:qhash:generation:policy)::uuid`。
    同一键永远同一 walk_id,traversal/stop signal 在第一封之前就可
    计算(E5 预种 call 行靠这个)。不是 `gen_random_uuid()`。
26. **structural NULL 不是伪 Noul(M3)**:supports 存在时,
    `(coalesce(structural,0)+supports)/2` 参加 λ5;supports 缺失则
    整段 λ5 丢掉。0 只表示这条边没有结构分。
27. **邻居 EXPLAIN 在单边夹具上可能走 dst btree(M3)**:
    `enable_seqscan=off` 时规划器对 `(session_id, dst_hash, rel)` 做
    session_id+rel 的 skip scan,再过滤 src_hash。两条 OQ1 btree 都在;
    闸门断言计划不是 `Seq Scan on memory_links`。
28. **锚的 need_g 取主桶(M3)**:首轮锚没有入边。`need_g` 用权重最大
    的桶(并列名字升序)。扩展出去的邻居带上认领它的桶(桶序
    causal…temporal,先到先得)。
29. **enqueue 的 apply 再读面=route 侧 SELECT decisions(M4)**:计划
    §3.4③ 的 apply(只读 decisions)与 ④入队按 M1 预授 ACL 面拆开——
    consolidate(resolve)只发问并返回 eligible 报告(队列 INSERT 在
    route),enqueue 内部重放同一 gate(`v13_mgraph_cons_gate` 单一
    事实源)。为此 M4 ACL 追授 `GRANT SELECT ON decisions TO
    v13_route`(计划 §4 ACL 清单未列;替代方案=队列 INSERT 落 resolve
    侧,与 M1 预授的「队列写入面=route」矛盾)。
30. **consolidate 一步一封(M4,同 #17/#19)**:GUC mock 单批形状限制;
    `v13_mgraph_consolidate` 每调用至多一封真实 ask(缓存命中的对零
    ask 连续处理),stop_reason='step'。生产 provider 要一次调用内问完
    全部对=把步进循环放进驱动,机制不变。
31. **fidelity include 判据绑定 consolidation_choice_min(M4)**:计划未
    钉 fidelity noul 的 include 阈;不变量 12 禁函数体字面阈、种子又无
    专用键 → 取固化提交置信键 consolidation_choice_min(0.85)为
    fidelity include 下限(summary 先例=自有 accept.lo;需独立阈=新
    策略版本加键)。
32. **settle 的 body_hash 语义(M4)**:采纳行=产物哈希(覆盖此前拒绝
    尝试的记录);拒绝行 COALESCE 保留首次可哈希尝试文本的哈希;无
    文本(如 complete failed)保持 NULL。计划只说「settle 时回填,仅作
    审计」。
33. **窄 requeue 基底=periphery 库 pg_proc 活体(M4)**:pg_get_functiondef
    导出后修改——(a1)/(a1') 的 kind 谓词 `='judge'` 改 `IN ('judge',
    'mgraph_consolidate')`、cap 判定改按行 kind 调 v13_attempt_ok,
    其余语句逐字保留;计数器语义不变(reclaimed_ready 现含 mgraph
    行);ACL 经 OR REPLACE 保留。
34. **enqueue 的 post-enqueue 三分支(M4)**:`v13_enqueue_effect` 返回
    id 后按行状态分流:ready|claimed→generating;succeeded→不重复
    enqueue 返 NULL(settle 待跑,queue PK 幂等权威);failed/cancelled
    (重挂被 cap 拒)→行收敛 rejected 返 NULL。计划只裁了超 cap→
    rejected;complete-后-settle-前的 succeeded 窗口由此保护。推论:
    effect 已 succeeded 而 settle 拒绝(确定性检查/fidelity)后,同
    turn 内不可再生成——重试身份随 effect(request 五键闭集无 attempt
    位),跨 turn 或翻 policy_version 才有新 identity;worker 主动重试
    (complete failed→重挂→attempt 2)不受影响(F11 (c)/(d))。
35. **子型无过阈者退 link(M4)**:三个 Noul 方面无一 ≥
    relation_threshold 时子型取 link(→related_to)——被 choice 门放行
    的对必有合并关系,产物至少 related_to。计划未言明无过阈者的落点。
36. **选对池=episodic 相邻对(M4)**:`v13_mgraph_cons_pairs` 只枚举
    episodic 节点按 (source_at ASC, content_hash ASC) 的相邻对(与
    temporal 边同序——「source_at 近、哈希序」的最小实现);
    consolidation 节点不作对员(与「不作候选锚」同向)。consolidation
    节点的 source_at=两亲本较晚者,新节点插入后可与既有对员再成对,
    由 adopted 排除面闸住同 key 重复。
37. **transition_score 锚源同批切换(V1)**:计划 §3.2 就地表只列三
    调用点(candidates :730/build :1013/anchors :1649);实测
    `v13_mgraph_transition_score`(mgraph:1772 一带)也以
    `v13_build_tinql(p_query)` 直喂 `v13_mgraph_candidates`——新守卫
    fail-closed 拒 AND 形 tinql,不换源则 E 组读环回归结构性红。由
    「A+D+E+F 全组回归必须仍绿」红线推导为必改面,同批就地切换(仍属
    R2/OQ16 锚源修订的完整实施,非范围扩张)。
38. **守卫字符白名单=发射域内联(V1)**:计划只列「通配/正则/fuzzy
    →V3005」;实施具体化为段内逐字符白名单(latin [A-Za-z0-9] ∪ CJK
    五区间,与 `v13_query_segments` 同一权威码点表内联——route 内联先例
    同款;空白/操作符/任意其它符号一律拒);词项上限按裸分片数判
    (去重前),去重保序返回「规范化项集」。
39. **负值域执法在整数正则先炸(V1)**:读取器对负整数(如
    `anchor_ngram_n=-1`)在 `!~ '^[0-9]+$'` 处即抛「must be an
    integer」,先于「>=0」域检查——fail-closed 语义等价(仍 V3009),
    G9 断言按实际消息钉定。
40. **contradicts 只在 canonical 方向入封(V2)**:计划 §1.5/OQ17 只钉了
    signal 端点 canonical(小,大)与「双向边=双份 ask 不采」;但
    request_hash 携带 pair ctx(正反信封 ctx 互换⇒不同哈希),若
    pair_questions 双向都返回 contradicts 问,反向信封会以新哈希重问
    同一 signal——双份 ask+同 signal 双 decision 行,直接碰 D5 的
    「每 signal 恰一行」既有 gate。实施取:仅 p_src<p_dst 时入封,每无序
    pair 恰问一次。连带计数修正:计划 §6.2 的「12×4=64」未考虑该交互,
    实测 D11 计数=4×4 类型+6×4 canonical+6×3 反向=**58**(P2-4 以实测
    为准);封问数面=canonical 向 4–5 问、反向 3–4 问(批数不变)。
41. **B2 选对重写为 proximity-derived(V2,OQ17 裁决)**:对源从 v1 相邻对
    改为「origin='proximity' 边两端均 episodic,按 (source_at ASC,
    content_hash ASC) 规范化为无序对 (early,late) 去重」,输出加
    ORDER BY early(确定性;v1 无显式序);F 组固化夹具补插生产形状
    proximity 边(put_nodes prox 参数);时间相邻但零词法激活的对不再
    进对源(语义收窄已裁)。
42. **H7 以 write_max_asks=1 步进(V2)**:GUC mock 为精确键匹配(实测
    多余键即 failed;#17 同族),单次 build 调用内发多封须每封独立 mock,
    不可行——跨 tick 续跑在 write_max_batches=8 帽在位下以 wma=1 步进
    走查(每次调用恰 1 ask≤8、cursor 逐节点推进);>1 真实 ask/调用需真
    provider 面(demo)。另:快照槽 mem_rel_contradicts 为 v13-local 且
    携带 criteria 对——快照解析器改为「3 块 noul 槽一律按组合规则 v1
    拼接」,fidelity 单块本地槽不受扰。

## 回退

删 `v13/mgraph/` 树+`v13/load.py` 第 15 位(两行)+`DROP DATABASE
agent_v13_mgraph` 即净;前 14 stage 文件字节不变。模板种子对共享库的
cgr bump 无法撤(与 summary 先例同);暗库默认双 false 零消费者,
`judgment_defaults` v4 的六个 mem_ point 可随库丢弃,无持久化用户数据
迁移(stage 库 DROP-CREATE)。

**V1 面回退补充(v2 计划 §7)**:策略种子可退 A2 语义
(`anchor_ngram_n=0`,命中语义退化,**不与旧 AND 编译器字节一致**——
P2-2 已裁不要求)但**不可退 AND 形态**——AND 编译器已被 V1 替换,完全
恢复须代码级回退(一里程碑一提交,V1 可独立 revert);mgraph v2 键集
与 v1 读取器不兼容,回退=恢复 v1 SQL+重建 stage 库,不能只翻 active
标记;整体回退=stage 库 DROP-CREATE,前序 14 stage 文件字节不变。

**V2 面回退补充(v2 计划 §7)**:第 29 枚模板种子与既有 28 枚同批
bump cgr(不可撤,同运维②);contradicts decision 在旧代码下不被
apply(闭集不含)但不破 schema,cons_pairs 回退=代码级(前 v1 相邻对
语义);canonical contradicts 单向边的遍历不对称已裁接受(P1-3),对端
经词法锚定可达;一里程碑一提交,V2 可独立 revert+重建 stage 库。
