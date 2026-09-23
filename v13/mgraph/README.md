# v13/mgraph — DP9 M1 记忆图暗库(两表+策略行+六族模板+defaults 追点+ACL;行为全关)

Stage 15/15(SQL_LOAD_ORDER 第 15 位,纯末尾追加)。消费 schema→periphery
全部前序 14 文件;本 stage 库 = `agent_v13_mgraph`(`files_through('mgraph')`
前缀切片,15 文件;stannum 前置探针 fail-closed,形态照 memory/summary)。
设计:`docs/designs/v13-context-on-pg.md` v2 §4.4/§6.1/§6.5/§8。计划:
`docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md`(M1=暗库;M2 写与
重建、M3 读环 B1、M4 固化由后续里程碑追加)。gate:`uv run python
v13/mgraph/test_mgraph.py`(G-mg 族 A 组,退出码 0=通过)。

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
2. **索引**:stannum 单索引 `ix_memory_nodes_stannum`(body;候选发现
   M2 落地,本文件 `==>` 次数=0)+ 一跳两向 btree `ix_memory_links_src/
   dst (session_id,src/dst_hash,rel)`(邻居函数 M2 落地,索引先行)。
3. **meta 与固化队列**:`v13_mgraph_meta`(每会话至多一行,build 首写;
   初值语义 generation=0/watermark=-1/rel_cursor=NULL/
   nodes_since_consolidate=0;读取器 `v13_mgraph_progress(uuid)` 对无行
   会话返回同组初值——A8 的断言面)+ `memory_consolidations`(固化队列,
   PK `(session_id,consolidation_key)` 同 key 至多一行——重试语义由
   effect attempt 承载;status∈queued|generating|adopted|rejected;
   「rejected 可审计」的载体;M4 消费)。
4. **策略行 `mgraph` v1**(§3.2 种子逐键 39 键,含 `write_max_asks=64`;
   `consolidate_max_body_bytes=32768` 为 v13 本地护栏非上游默认)。
   读取器 `v13_mgraph_policy()` fail-closed:键集漂移/类型域违例/权重
   五数和≠1/priority 非三值排列 → V3009;**「保留但响亮」键执法**:
   `admission_enabled=true`(OQ5)或 `consolidate_mode≠'manual'` → V3009
   (v1 无实现即配置错误,读取时炸;M2 build 只经本读取器取值)。
   函数体零动作阈字面量(0/1 域界与数组形状常数除外)。
5. **六族 mem_* 模板(28 枚)**:type×4(投影 `["body"]`)/rel×4
   (`["left","right"]`)/routing×6(`["query"]`)/stopping×4
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
   `candidate_set_hash`=本批 signal 集合+state 的 sha256。
8. **ACL(M1 面)**:recall/resolve/route 三角色对四表 SELECT;resolve=
   INSERT 节点/边+UPDATE memory_consolidations(settle 面,M4)+EXECUTE
   envelope/defaults 读取器;route=INSERT/UPDATE memory_consolidations
   (队列写入面,M4);策略读/进度读三角色;rebuild/verify/DELETE/表 DML
   其余面仅 owner;零 `SECURITY DEFINER`。M2–M4 各自追加其函数面
   (walk/round 表与 build/route/run_round/enqueue/settle 的 EXECUTE 授权
   随里程碑落)。
9. **源码扫描闸门(A7)**:`typesafe_ask`/`v13_append_event`/
   `FOR UPDATE`/`mock_response`/`cypher(` 对本文件计数全 0(判断 IO 只经
   `v13_resolve_judgments`;本 stage 不碰会话锁;M1 零行为函数)。

## 运维纪律(README 必记)

- **① 部署暗,翻开才走判断**:`write_enabled=false`+`read_enabled=false`
  (与 Jev-Mem 代码默认一致,`jev_mem_config.py:12-13`);默认双 false 下
  零 mem_ decision 落库、零装配影响。翻开=新 (name,version) 策略行+同事务
  翻 active(M2+ 的行为面就位后才可翻)。
- **② dec-refresh 注记(不变量 14)**:任何 `mem_%` 行落 decisions 会使
  活体 `v13_context_required` 的 `dec` 计数变化 → 下一次装配 token 失配
  一次 refresh(已知代价,不改 dec 定义);默认双 false 下零发生。同族:
  本 stage 模板种子在加载事务内逐模板 bump cgr(28 内容行+28 freeze=56,
  A5 断言 ≥28;实测恰 56)——在途回合一次 stale 失配,既有语义,重解析
  零 ask。
- **③ unknown 墙注记(M4 预记)**:固化 enqueue 闸面=会话已有
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
- **⑦ 写帽预估(M2 预记,OQ2)**:`judge_spend` 数 judgment_calls 行
  =ask 批数;每新 episodic 节点 ≤11 批(1 类型封+≤10 关系封),
  session_asks_cap=512 ⇒ ≈46 新节点触顶;开启 write 前按 transcript
  规模评估/上调会话帽;独立 `write_max_asks=64`(每次 build)+`write_
  max_batches=8`(每 tick)两帽防首建吃穿封死用户回合。

## 明确不做(M1 范围外=M2–M4 里程碑;§8 台账另见计划)

- **M2**:episodic 投影 build/apply/rebuild、确定性结构边(temporal/
  proximity)、关系判断边、候选发现(TINQL→stannum,`==>` 计数=恰 1)、
  `v13_mgraph_neighbors`、rel_cursor/watermark 推进、写路径三帽。
- **M3**:route/allocate/run_round/should_stop/evidence(读环 B1,零
  effect 驱动分轮;walk/round 表随本里程碑落)。
- **M4**:固化链(五问+representation choice+fidelity)、kind
  `mgraph_consolidate`+cap 七键+窄 requeue(活体 OR REPLACE)、enqueue/
  settle、consolidation 节点=远程层首批。
- admission 五问(OQ5 不做;键 true→V3009);`consolidation_interval`
  自动计数(代码默认 0,论文附录「每 20 写」不采用);AGE(§8 台账三
  条件);B2 装配接线(下一张计划);walk/round 生命周期清理(保留策略
  =不清理,触发=下一张计划)。

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

## 回退

删 `v13/mgraph/` 树+`v13/load.py` 第 15 位(两行)+`DROP DATABASE
agent_v13_mgraph` 即净;前 14 stage 文件字节不变。模板种子对共享库的
cgr bump 无法撤(与 summary 先例同);暗库默认双 false 零消费者,
`judgment_defaults` v4 的六个 mem_ point 可随库丢弃,无持久化用户数据
迁移(stage 库 DROP-CREATE)。
