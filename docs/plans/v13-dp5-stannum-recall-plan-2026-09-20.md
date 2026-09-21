# v13 DP5: stannum 刻画与 T0 recall — 实施计划

> 状态:首写轮(turn 25,DP5/8;L3 七节全,待控制器 L3+L4)。
> 设计输入:`docs/designs/v13-context-on-pg.md` §4.1/§4.6/§4.7(BM25 长度归化刻画面)/§4.8/§7/§8(stannum runbook+verify_index)/§9(recall_boosts 策略行切片)/§10(G-ctx3)/§12/§13(第 10 章)(冻结禁改)。
> 评审输入:`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md` **F4(P0,反向提示:stannum 侧刻画不得重蹈「零刻画却承重」——刻画 gate 六件必须真实执行,runbook 全落)/F5(P0,k 上界与 (k,tier)→延迟账在 DP5 范围:②一页账+首版 k 硬上限本 plan 立法;①解析相花费闸、③哪些 tier 允许快路超 1 批记 DP7 缝)**。
> 撰写方式注记:**context_builder 通道 ACP 故障(MCPToolExecutionCancelledError,与 turn 13×2/turn 18×4/turn 22 同型),经 brief 授权由主会话代行撰写**;全部基座文档(DP1 §1.3/#59/§3.2/§3.5、DP2 §1.4/§3.4、DP3 §1.3/OQ1/OQ4/§1.4/§3.4/校验器层 6、DP4 全文含 §1.4 契约①–⑨/§3.1–§3.8、设计稿全文、stepfun F4/F5、教程 ch10 全文、ch1 events 表、v12 payload 惯例)已逐一通读并按契约消费;探针批判子会话照 DP3/DP4 先例补一轮(见文末执行记录)。
> 引擎实证注记:stannum 0.1.0 + PG18.4(pgembed)临时探针库已于本轮实机盘点与行为实测(API 面/索引选项/绑定机制/降级面/canary 物理/REINDEX/fold 段),全部事实记 §1.3 OQ6/OQ7/OQ9 与附 B;探针库 `v13_dp5_probe` 用毕即删(环境复原)。

## 0. 执行索引

| 项 | 内容 |
|---|---|
| **Goal** | 把 §4.1(召回是函数+三禁+canary+确定性排序)、§4.6(v13_build_tinql 受限构造器+CJK 短语引用+k 自适应)、§4.8(刻画 stage:承重件不依赖 stannum/刻画完换 definition)、§7(T0 分层:tsvector 起步→stannum 刻画后)落成 **两个 stage**:`v13/recall/`(SQL_LOAD_ORDER 第 8 位,tsvector T0+信封/装配接线+cgr 接线)与 `v13/characterize/`(第 9 位,stannum 刻画+换 definition),以 **G-ctx3 全部四断言** + 刻画 gate 六件 + DP1 #59 语料代数接线 gate 收口 |
| **Done when** | `uv run python v13/recall/test_recall.py` 退出码 0(A–J 十组全绿)且 `uv run python v13/characterize/test_characterize.py` 退出码 0(K–R 八组全绿);提交前 DP1 四 stage + DP2 + DP3 + DP4 gate 全部复跑(各自 stage 库前缀切片,不受本两文件影响);收尾工件齐(load.py 第 8/9 位/两 stage README/本 plan 映射表) |
| **Key files** | `v13/recall/v13_recall.sql`(全新增,第 8 位纯末尾追加)、`v13/recall/setup_db.py`、`v13/recall/test_recall.py`、`v13/recall/README.md`;`v13/characterize/v13_characterize.sql`(全新增,第 9 位)、`v13/characterize/setup_db.py`、`v13/characterize/test_characterize.py`、`v13/characterize/README.md`;`v13/load.py` 仅追加两行路径与 `STAGE_THROUGH["recall"]=8`、`STAGE_THROUGH["characterize"]=9`,零改动既有文件 |
| **Dependencies** | 分解表:DP4(chunks 存在);实际加载依赖 DP1–DP4 全部七文件(两个新 stage 库分别加载前缀 8/9 文件)。DP6(过滤/记忆栈)消费本 plan 的信封 candidates 键与 v13_recall 签名契约(§1.4) |
| **Size** | 两 stage 两里程碑;SQL 两个文件(stage 8:14 条顶层语句=函数 10[新 6+换体 4]+种子 INSERT 1(2 行)+ACL 3;stage 9:9 条顶层语句=EXTENSION 1+表 1+种子 1+索引 2+换体 4);gate 两文件十八组(A–J/K–R,含两连接与压测 fixture) |

---

## 1. 定位与边界

### 1.1 本 DP 在 v13 版图中的位置

DP5 是设计 §11 交付排序第 2–3 条的**检索半边**:DP4 落了 chunks 投影与跨度生产者,但 manifest 的 candidates 至今是 goal echo(DP3 §3.4 行 1001–1016 的「DP4/DP5/DP6 填充缝」注释在场),解析相的候选推导至今只有 tools 目录(DP1 §1.3)。本 DP 落**候选的检索平面**:①受限查询构造器 `v13_build_tinql`(§4.6 P1 真活);②`v13_recall` 函数族(§4.1 召回是函数+三禁);③tsvector T0 起步与 stannum 刻画后的 definition 换体(§4.8/§7);④候选推导接线(信封 csh 材料+manifest query_side 双落点)与 DP1 #59 语料代数接线;⑤刻画 gate 六件与 stannum runbook(§8)。

**双 stage 裁决(OQ2)**:`v13/recall/`(第 8 位)交付 tsvector T0——零 stannum 依赖、零 `==>` 字样,在无 stannum 环境可全绿(「承重件不依赖 stannum 一根毫毛」的字面兑现);`v13/characterize/`(第 9 位)交付 stannum 刻画 gate 与 definition 换体(§11「刻画 stage 先行/并行→刻画通过后换 T0 recall definition」的时序在 stage 序上显式成立——第 9 位加载即换,第 9 位 gate 即刻画;DP6+ 前缀加载即得已刻画 plane,恰是 §7 T0「stannum(刻画后)」的库形态)。两个里程碑两次提交(AGENTS 一里程碑一提交)。

**骨架(非全量)**:本 DP 不落过滤管道与 per-chunk 判断(§4.5 归 DP6——存在性 Noul/per-chunk Score/跨 session 缓存/reused_from);不落 transcript_chunks 记忆语料(§4.4 归 DP6);不落 T1 vectorchord/RRF/embed 缓存行与 T2 duck(§7/§12,只记触发条件);不落 bigram 列(§4.6/§12,台账);不落 boost 消费(§9,建空策略行留缝);不落 chunk section 生产者(DP6:候选→过滤→段)。

**硬边界(零改动纪律)**:DP1–DP4 计划文件与其(未来的)SQL 文件零改动。对既有对象的变更全部为**授权换体或纯追加**,共九处,均有上游明文授权缝:①`CREATE OR REPLACE FUNCTION v13_chunks_generation_bump()`(DP4 §3.1 定义;DP1 #59/DP4 契约① 的语料接线执行点);②`CREATE OR REPLACE FUNCTION v13_context_required(uuid)`(DP4 §3.6 八键体;DP3 OQ1 追动键缝——本 DP 扩九键,见 OQ8);③`CREATE OR REPLACE FUNCTION v13_judgment_envelope(uuid)`(DP2 §3.4 十九键体+DP3 墓碑二;DP1 §1.3「候选集来源缝」的 DP5 替换点);④`CREATE OR REPLACE FUNCTION v13_assemble_manifest(uuid,int)`(DP3 §3.4;其 §1.4 DP5 行的填充缝);⑤–⑧`CREATE OR REPLACE FUNCTION v13_recall/v13_recall_count/v13_extract_spans/v13_verify_chunks`(分别为本 plan 新建函数的同签名换体×2、DP4 §3.5 定义[签名/输出不变,DP4 契约④]、DP4 §3.4 定义[升 v2 增第八项,DP4 契约②/E5]);⑨对既有表零 DDL(无 ADD COLUMN、无新触发器)。前缀切片库不加载本两文件,DP1–4 库零影响(结构性,files_through)。

### 1.2 上游契约消费清单(逐条,来源:DP1 §1.3 / DP2 §1.4 / DP3 §1.4 / DP4 §1.4)

| # | 上游契约(原文要点) | 本 plan 消费方式 |
|---|---|---|
| 1(DP1) | 候选集来源缝 = `v13_needed_judgments` 的候选推导(DP1:tools 目录+fold_state);**DP5 的 v13_recall 族替换该推导,candidate_set_hash 定义不变(对推导结果全集取 hash)** | 推导替换落在信封层(OQ3):csh 材料=needed∪recall 候选(jsonb object digest);「定义不变」=「对推导结果全集取 hash」的公式形态不变,推导结果全集自 DP5 起扩含召回候选(附 A #3);v13_needed_judgments 判断问题集不动(召回判断族归 DP6,附 A #4) |
| 2(DP1) | **硬契约(turn 9,#59)**:换 v13_needed_judgments 推导消费语料时,必须把语料/索引版本依赖并入 cgr 的 bump 面或另立单调键进信封/探针步 0 比对,否则无漏报论证在语料面重开 | **选「并入 cgr bump 面」(OQ1)**:OR REPLACE `v13_chunks_generation_bump` 在 bump `v13_chunks_meta.generation` 后同函数 bump `v13_tools_meta.candidate_generation_revision`;gate F 组(generation/cgr 双计数同步+parse→ingest→advance='stale'+任意路径 DML 含 owner 直插);DP2 §1.4 先例(模板行集 DML bump cgr)证明数据面 bump cgr 是既有形状 |
| 3(DP1) | probe 七键无漏报论证:csh/needed_count 是 needed 派生不直接比对;needed=f(tools 行集,函数体,模板行集)由 revision/cgr/cgr 覆盖 | DP5 后推导面={tools 行集,函数体,模板行集,**语料代数**}→{revision,cgr,cgr,**cgr**};probe/snap_of **零改动**(七键不变);信封函数体/envelope 换体不 bump cgr(部署面,与 DP2/DP3 换体先例同界,OQ1 边界注) |
| 4(DP1) | v13_policies 载体:(name,version) 主键+at-most-one active;读侧单源 `v13_policy()`;追加=新版本行+同事务翻 active | 播两行 v1 active:`recall_k`(k 自适应+timeout)/`recall_boosts`(空,§9 留缝);种子即校验器输入(消费点 fail-closed,DP4 先例);k 策略版本进 token 第九键(OQ8) |
| 5(DP1) | 双登录强制架构(v13_resolve_login/v13_route_login 单成员;运行角色最小 ACL+负向权限测试) | 新函数 EXECUTE 授三角色(纯读链);**SELECT ON chunks/v13_sources/v13_chunks_meta TO v13_resolve,v13_route 由本 plan 落位**——DP4 §1.4 DP6 行②原文「届时才有消费(由 DP6 补)」,本 plan 的信封(parse 在 resolve 下)/装配(settle 在 route 下)换体创造了第一消费点,授权随消费点前移,DP6 无需再补此半边(§1.4 DP6 行注记);gate H 组负向 |
| 6(DP1) | 每 stage setup 只加载到当前 stage;gate 断言只能引用当前 stage 已加载对象 | 两个新 stage 分别第 8/9 位纯末尾追加;stage 8 gate 引用对象 ≤8 号文件;stage 9 gate 引用 ≤9 号;DP1–4 各 gate 在其前缀库复跑不受换体影响(文件 8/9 不加载) |
| 7(DP2) | needed 推导面三处(tools 目录/needed 函数体/judgment_templates 行集)由 revision/cgr/cgr 承接;「DP5 新增召回判断族=新增模板族行+needed 新分支(函数体 DDL 自动 bump cgr)」 | 机制面照单接收(任何 needed/envelope 体 DDL 经 event trigger 分支 2/部署纪律承接);**模板族行与 needed 分支按分解表权威收窄至 DP6**(§4.5 归 DP6;附 A #4);本 plan 只落推导面接线 |
| 8(DP2) | 信封 19 键体(DP2 §3.4 重建+DP3 goal_hash 换体)单语句单快照;M2-9 为包含性断言(追加键合法、删改不合法) | OR REPLACE 扩 20 键:新增 MATERIALIZED CTE `rc`+csh 材料扩集+追加 `candidates` 键;**键集 19 键不删不改,表达式层面=17 键逐字保留+goal_hash 沿 DP3 换体形态+candidate_set_hash 材料扩集(OQ3,本 plan 的授权变更点)+新增 candidates 键=20 键**(墓碑纪律,§3.1 注);gate D 组做键集包含性+新键形态断言 |
| 9(DP3) | candidates 四字段族 {content_hash,bm25,spans,decision_id} 已立法;**candidates 的 content_hash/bm25 由 v13_recall 族产出进装配;数组序钉 bm25 DESC, content_hash ASC;manifest 不内嵌 TINQL**;校验器层 6 要求候选行键集恰等四键(bm25/spans 值可空、键必须在;content_hash 64hex;spans typed array) | 装配换体:qside candidates ← `v13_recall_candidates(p_sid)`(三键行)‖ `{'decision_id':null}`(补第四键,校验器兼容);聚合内显式 ORDER BY (bm25)::numeric DESC, content_hash ASC;信封与 manifest 均不内嵌 TINQL 串(只记产物,附 A #5);gate E 组 |
| 10(DP3) | token 追动键缝:任何进 manifest 输出的输入必须在 token 有键(asm_ver/jdef_ver/gen_ver/corpus 先例);键集增删⇒全域恰一次 refresh | `recall_k` 策略版本进 token 第九键 `recall_ver`(OQ8:k 变截断⇒manifest 变,漏键=freshness miss——与 asm_ver 同类);`span_assembly` 版本不入(DP4 契约⑤的触发条件=「装配消费 spans 进 manifest」——本 DP 的候选级 spans 是命中证据、不消费 span_assembly 策略,⑤缝转发 DP6);键集八→九⇒恰一次 refresh(gate I 组,DP4 G2 同型) |
| 11(DP4) | 契约②:T0 直接消费 chunks.body_tsv GIN;stannum 落地时 v13_verify_chunks OR REPLACE 升 v2 增 verify_index 项(E5 已断 version 键在场) | T0=phraseto_tsquery 组合+ts_rank 排序值(OQ4);verify v2 第八项=stannum.verify_index('ix_chunks_stannum',true) 的 error/warning 计数(附 B 冒烟:severity 词表);gate N 组断言 version=2+八项全绿 |
| 12(DP4) | 契约③:chunk 目标尺寸的数据答案归 DP5 刻画 gate(先验 3072 已落策略) | 尺寸刻画面 gate Q 组:6 档尺寸 fixture→命中数/bm25 均值/排序位置数据表→README 记数据答案+翻版流程(不自动翻策略);gate Q 组 |
| 13(DP4) | 契约④:spans 生产者换 stannum highlight 时签名 `(text,jsonb)→jsonb` 与输出 `[[b,e],…]`(字节、chunk 内、非重叠、升序)不变,消费方零改 | OR REPLACE `v13_extract_spans`:哨兵 highlight 体(哨兵对四选一确定性选择;字节换算公式两行;上限 256 确定性停止);载荷约定从「词数组」换 `{"tinql":…}` 对象(签名/输出不变;载荷是 recall 家族内部约定,外部消费者=v13_assemble_spans 不调 extract,零改——附 A #6);gate P 组 |
| 14(DP4) | 契约⑨:召回源枚举必须跳过 `v13_sources.superseded_by IS NOT NULL`;契约⑥ candidates 数组序;契约⑧ 候选批量化引用锁纪律 | recall v1/v2 与 count 的 FROM 均 `JOIN v13_sources src ON … AND src.superseded_by IS NULL`(§1.5 不变量 7);⑥见 #9;⑧本 DP 零 context artifact 批量写(装配经 DP3 refresh 单 artifact——DP3 既有路径),纪律转发 DP6(§1.4) |
| 15(DP4) | 驱动器契约四步(外部 IO 不进事务)+fixture 纪律=真实链路 | gate fixture 语料一律经 DP4 驱动器四步摄取;manifest 经 DP3 refresh settle 真实链路;事件经 v13_append_event;parse/advance 经 DP1 真实函数 |

### 1.3 Open Questions 裁决(本节为最终权威)

**OQ1 裁决:cgr 接线 = 并入 cgr bump 面(OR REPLACE v13_chunks_generation_bump 追加第二条 UPDATE);probe/snap_of/envelope 键集零改动。**

- 依据:DP1 #59 给两选项。选 bump 面的理由:(a) cgr 语义即「candidate generation revision」——候选推导面的版本计数;DP5 后推导面四源(tools 行集/needed 函数体/模板行集/语料代数)由 revision+cgr×3 覆盖,DP2 §1.4 已立「模板行集(数据面)DML bump cgr」先例,语料是同型第三源,不引入新键种;(b) 备选「probe 键集扩第八键」需同时改 envelope(记录 corpus 键)+snap_of(投影)+probe(比对)三处,且造成 manifest token(八键含 corpus)与 probe(七键不含)的不对称——改动面与论证面双输;(c) 成本:每次 chunks DML 语句两条单行 UPDATE(v13_chunks_meta+v13_tools_meta);摄取是 owner 离线面,不与 events/advance 路径交叠;advance 步 0 probe 的 v13_tools_meta 读是 MVCC SELECT,与 bump 的行写不阻塞;DP3 settle 三层冻结锁序(sessions→tools_meta→策略行)与本 bump 只在 tools_meta 行互斥——短暂阻塞无环(ingest 不持 sessions/策略行;settle 不持 chunks/meta 行;ingest 的 artifacts 写是 insert-only 无争用面),gate F 组双连接断言。
- 无漏报论证(DP5 版):needed/候选推导 = f(tools 行集, needed 函数体, judgment_templates 行集, 语料代数)。tools 列变更→行级触发器 bump revision;needed 体 DDL→event trigger 分支 2 bump cgr;模板行 DML→DP2 行级触发器 bump cgr;chunks 任何路径 DML(函数/psql/COPY/owner 直插)→语句级触发器 bump generation **与 cgr**。probe 七键比对检出全部四源 ⇒ parse→advance 窗口的语料变更=保守弃批重解析,零静默消费。反向(cgr 变而推导不变,如无引用行 DELETE)→保守弃批,与 DP1 既有取舍同款记档。
- 边界注:信封/装配/needed 的**函数体漂移(部署面)不 bump cgr**——OR REPLACE 不触 tools 行、不触 chunks 行;这与 DP2(canonicalization 换体)/DP3(goal_hash 换体)/DP4(context_required 换体)先例同界:代码部署在 stage 加载/DROP-CREATE 世界结构性重建,不存在「同 turn 中途换体」的生产路径;数据面(语料/目录/模板)才是 mid-turn 可变面,已全覆盖。

**OQ2 裁决:双 stage——v13/recall/(第 8 位,tsvector T0)与 v13/characterize/(第 9 位,stannum 刻画+换 definition);§1.1 已述。**

- 依据:§11 时序「刻画 stage(并行)→刻画通过后换 T0 recall definition」在单文件单 stage 内不可表达(文件加载即换,时序被吞);双 stage 使「承重件先绿(第 8 位 gate 无 stannum 可跑)→刻画 gate(第 9 位)→此后库形态=已换体 plane(DP6+ 前缀)」显式成立。DP6 若并行开写:其消费面=第 8 位形态,以 v13_recall 族签名契约为准(definition 无关性,§1.4 DP6 行②)。
- 教程 ch10.3「换 rag_recall 目录行的 function definition——目录行是数据,流程零改」的 v13 承载=「v13_recall 族签名冻结+第 9 位文件 OR REPLACE 换体」;不落 tools 表行(附 A #9:sql handler 签名纪律 `(uuid,jsonb)` 与 v13_recall `(text,int)` 不兼容,强行注册扭曲 guard;四行画景的四个角色已由 effect 驱动器/决策平面/refresh settle/函数族四机制分别承载)。

**OQ3 裁决:候选推导替换落在信封层(envelope OR REPLACE 扩 20 键);v13_needed_judgments 判断问题集零改动。**

- 形态:新增 MATERIALIZED CTE `rc`(=v13_recall_candidates(p_sid),单语句快照内与 needed/ctx 同点);csh 材料=`digest({'needed':…,'recall':rc}::text)`;追加第 20 键 `candidates`(**parse 时冻结的召回候选**——k/matched 派生值入 csh 材料不入键;DP6 的 per-chunk needed **必须消费此键**,禁止重跑 recall 重推导:单一推导点=哈希同源纪律的推导版)。
- 论证:(a) DP1 契约字面「v13_recall 族替换该推导」的落点=候选推导,而 needed 的判断问题集不含召回判断(§4.5 归 DP6)——在 DP5 动 needed 只会制造空判断分支;(b) csh 双消费(信封/装配)共用 `v13_recall_candidates` 单一来源,不同事务各自快照,漂移面=快照差(诚实审计:manifest 记 settle 时发现了什么,token corpus 键保证语料变更触发 refresh);(c) 锁域不回归:锁键=v13_lock_key(sid,csh) 已折 sid,信封候选随语料/查询变化自然进入键材料,「并发重复解析仅一次付款」语义保持(gate F 组)。
- 信封不内嵌 TINQL(DP3「manifest 不内嵌 TINQL」同型:只记产物不记中间串,推导可从 goal 文本+代码复现)。

**OQ4 裁决:T0(v1)排序值=ts_rank 确定性实数(诚实载体:排序用途,非 BM25 语义);stannum(v2)bm25=stannum.full_score(ctid) 实测 real∈[0,1]。两代同签名 (text,int)→TABLE(content_hash text, bm25 numeric, spans jsonb),并列截断一律 content_hash ASC 终裁。**

- ts_rank(body_tsv, tsquery) 确定性、无参数漂移;README/gate 注记「T0 bm25 列是词法排序值」不虚标 BM25(诚实边界纪律);v2 换 stannum 真分(实测可用,`full_score(ctid)` 每行一次)。排序确定性:两代 ORDER BY 都显式 `分值 DESC, content_hash ASC`,并列截断不抖(G-ctx5 同型;gate B/P 组双跑字节等断言)。
- **count 必须随引擎换体**(OQ4 附则):v1 count=tsvector 精确 count;v2 若仍用 tsv count,则 count 人口(k 自适应基数)与 recall 人口(==> 匹配集)分叉(CJK:tsv count≈0 而 ==> 命中>0,k 恒 k_base 自适应失效)——**v13_recall_count 在第 9 位同步 OR REPLACE 为 ==> 形态**(EXECUTE count;实测 count 走索引且 fold 后精确 51/51)。

**OQ5 裁决:k 策略=`recall_k` v1 {"k_base":8,"widen_ratio":0.05,"k_max":64,"timeout_ms":800};公式 k=least(k_max, greatest(k_base, ceil(matched×widen_ratio)));F5② 一页账+首版硬上限本 plan 立法,F5①③ 记 DP7 缝。**

- k_max=64 论证(§4 末一页账的 gate 载体):per-chunk Score(DP6)32 问/批、实测 1.3–1.6s/批往返 → k=64 ⇒ ⌈64/32⌉=2 批=快路 1 批+慢路 1 批(≈1 个 effect 往返);F5 的 k≈2000→十几轮悬崖被硬上限结构性封死;k=8(k_base)⇒ 1 批全快路。放宽 k_max=DP7 裁量(须重开一页账+tier 快路超批裁决,F5③)。
- timeout_ms:§4.1「执行超时全限」的载体。引擎事实(DP1 #60):函数体内 set_config 不治理嵌套语句——**执法在驱动层**:parse 驱动调用信封前 `SET statement_timeout` ≤ timeout_ms(recall 在信封内执行被同一上限罩住);策略行携带值+recall_candidates 入口校验(缺键/非法域 V3005 fail-closed);超时结局=query_canceled→解析事务整体失败→G-ctx8 幂等重推(响亮失败零静默回落;非 typesafe_ask,α 分类法不适用,README 记)。
- 解析相 per-session/每日判断花费闸(F5①)记 DP7 缝(经济件,§1.4 DP7 行)。

**OQ6 裁决:生产 chunks stannum 索引=默认配置(零 WITH 选项)单索引 `ix_chunks_stannum`;tokenizer canary 用专用 fixture 表(非默认配置索引),绝不与生产索引同列共存。**

- 依据(实测):默认回退 comparator(text==>text)=最宽配置(unicode 切分+case fold+accent fold+long truncate+emoji retain)——默认配置索引下「索引丢失」是性能事件非正确性事件,正确性检测交 EXPLAIN 形状断言(K1)+verify v2;canary 需要语义分叉(索引配置≠默认),载体=`v13_canary_docs` 表+`WITH (long_tokens='split', max_token_bytes=64)` 索引(实测:64 字节精确块查询 bound 命中/默认回退漏召)。
- **同列双 stannum 索引禁令(实测立法)**:两索引并存时 planner 恰绑其一(实测绑错即错结果)——生产列恰一 stannum 索引(gate R 结构断言);§4.6 bigram「独立列天然消歧绑定」的引擎佐证与前置纪律。
- CJK:默认 unicode 切分已 Han/Hiragana 逐字(实测);**Katakana 连跑成单 token(实测 東|京|タワー)**——单字 Katakana 子串查询 miss 是 0.1.0 物理边界(README+gate P 钉边界);查询侧 CJK 语段一律短语引用(OQ7 构造器)对连跑免疫。

**OQ7 裁决:查询构造器三层纯函数——`v13_query_segments`(分段)/`v13_build_tinql`(发射)/`v13_tinql_terms`(自产文法回析);输出=全语段引号包裹 AND 连接;注入免疫=构造性(输出语法形状封闭),非校验拒绝。**

- 分段规则(确定性,零策略读):字符三分类——ASCII 字母数字=latin;CJK 码区(U+3040–30FF/U+3400–4DBF/U+4E00–9FFF/U+AC00–D7AF/U+F900–FAFF)=cjk;**其余一切字符(空白/标点/引号/操作符字符)=分隔符**;同类连续段为一个语段(CJK 语段=整体一个短语段=「CJK 语段一律短语引用」的构造形态);上限:查询 4096 字节/语段 256 字节/64 语段,超限 RAISE V3005(fail-closed;§4.1 长度/展开上限);通配/正则/fuzzy **构造性不存在**(分段器只产词,操作符字符全是分隔符——「全限」的构造性形态,负向 fixture 钉输出无操作符面)。
- 发射:`"语段" AND "语段" …`——**全语段一律引号包裹**(含 latin 单词):引号内是字面短语,TINQL 关键字词(and/or/not 等)被引号免疫;语段文本不可能含引号/空格/' AND '(分隔符归类保证)⇒ 文法封闭可回析、零转义面。空/空白查询→''(合法空,零候选,不 RAISE——空 goal 是合法态)。
- 回析:只接受自产文法(逐段 `^".*"$`+段内无引号+' AND ' 分隔),异形 RAISE V3005——v13_recall 入口的 fail-closed 信封(G-ctx3「TINQL 注入被拒」的函数面);往返断言 tinql_terms(build_tinql(q))=segments(q)(gate A 组)。kohaku fixtures 钉混合查询形状(gate A/P 组)。
- 引擎佐证:stannum.maybe_quote 实测语义=多 token 才加引号——本构造器弃用 maybe_quote 改全引号(注入论证需要统一形状;引号单 token 是合法短语形态,实测 '"東京"' 短语查询命中)。

**OQ8 裁决:token 第九键 `recall_ver`=(SELECT version FROM v13_policies WHERE name='recall_k' AND active);缺行 RAISE 与 asm_ver/jdef_ver 同姿势;键集八→九⇒全域恰一次 refresh(DP3 OQ1 既判语义)。**

- 依据(DP3 契约 #10 追动键缝):k 决定 manifest candidates 的截断(k_max/k_base/widen 任一翻版→同语料同 goal 而 manifest 候选数变)——漏键=freshness miss(旧 active token 仍匹配→manifest 停旧版)。与 asm_ver(装配策略版本)完全同类的「推导参数版本」键。
- `recall_boosts` 版本**不入 v1 token**:空数组对输出零影响(构造性 no-op,gate P 组字节等断言);非空启用之日(§12 台账)按同缝并入(新键或并入 recall_ver)——「进 manifest 输出的输入必须在 token 有键」的纪律以「该输入 v1 不进输出」收口。`span_assembly` 版本同理不入(DP4 契约⑤缝转发 DP6,消费清单 #10)。

**OQ9(引擎实证台账)裁决:作用力 2 的「第 6 次执行切 generic plan→回落默认 tokenizer」在 stannum 0.1.0+PG18.4 未复现——三禁保留为冻结 DDL 纪律+纵深防御,gate 断言面改为实测降级面。附 A #1 呈报,设计稿禁改。**

- 实测:planner support 函数把 `col ==> <任意表达式>`(含 Param、含 force_generic_plan)改写为 `col ==> stannum.bind_query(<expr>, <index oid>)`——参数化路径保持绑定;DDL 无效化使索引后建的静态调用也被重绑。**实测复现的降级面两个**:①无 stannum 索引时回落 text==>text 默认 comparator(索引配置非默认时语义分叉=canary 物理);②同列双索引 planner 恰绑其一(绑错即错结果)。gate K/L 组按此断言;三禁的审计理由(作用力 1:BM25 是语料统计的函数,视图只能尽力再生)与未来引擎版本回归设计描述的可能性(实施期复测项)不受影响。

### 1.4 本 plan 对 DP6–DP8 发布的契约

| DP | 契约 | 形态 |
|---|---|---|
| DP6(过滤/记忆栈) | ① **信封 `candidates` 键=parse 时冻结的召回候选**(形态 [{content_hash,bm25,spans}] 三键数组;manifest 面四键含 decision_id 由装配补):per-chunk needed 必须消费此键,**禁止重跑 recall 重推导**(单一推导点;csh 已覆盖其身份);召回判断族模板行+needed 新分支由你落(DP2 §1.4 机制的消费点),epoch='pre-finalize'(DP3 OQ7)。② **v13_recall 族签名冻结 (text,int)→TABLE(content_hash text, bm25 numeric, spans jsonb)**;载荷约定:extract_spans 的 p_query 在 tsv 世代=词数组、stannum 世代={"tinql":…}(调用方=recall 家族内部,你不得直调 extract 跨约定)。③ SELECT ON chunks/v13_sources/v13_chunks_meta TO v13_resolve **已由本 plan 落位**(DP4 §1.4 你的行②半边提前),勿重复授;v13_recall 角色授权照旧。④ k_max=64 是你 per-chunk 批预算的**结构上界**(⌈k/32⌉ 批;放宽=DP7 裁量);存在性 Noul 缓存键的候选集维度(stepfun F2)消费 csh 材料(needed∪recall 已入哈希)。⑤ span_assembly 策略版本在你**段级消费 v13_assemble_spans 进 manifest sections 那天**并入 token 追动键缝(DP4 契约⑤转发;候选级命中跨度不触发)。⑥ 候选批量化引用锁纪律(DP4 契约⑧):单事务落多个含 chunk 引用的 context artifact/decisions 时引用集并集升序预锁或拆单引用集事务。⑦ transcript_chunks 独立表独立索引(§4.4),不搭 chunks 便车 | 键/签名/授权冻结+缝转发 |
| DP7(经济件) | ① recall_k.timeout_ms/k_max/widen_ratio 与一页账(§4 末表)是经济件输入;**解析相 per-session/每日判断花费闸(F5①)与「哪些 tier 允许快路超 1 批」(F5③)由你立法**——本 plan 只立 k 硬上限与延迟账,不越权。② k_max 放宽=新版本行+重开一页账(README 流程)。③ 判断成本核算读 judgment_calls(DP2 契约原样);召回零判断调用(DP5 面),费用账从你起算 | 策略行消费+缝立法 |
| DP8(latch/render/fork) | 无直接耦合:前缀身份材料不含语料与 k;exact replay 正文回取走 DP3 blob/artifacts(候选 content_hash→chunks 行保留是 DP4 retention 第二重保险);render 消费 manifest 含真候选后零新依赖 | — |

### 1.5 不变量(全 plan 有效,违反即设计背离)

1. DP1–DP4 全部不变量原样继承(两相分离/锁内零外部 IO/纯判断 IO 例外唯一/双登录/αβ 语义/token 与 manifest 同语句快照/冻结即不可变/manifest 只消费内容寻址身份/装配确定性/行自证/重摄取同事务/外部只记 hash/锁协议/退役源过滤)。本 plan 全部新读写**零外部 IO**(纯 SQL 检索);对既有对象的变更只限 §1.1 九处授权换体;`v13_advance`/`v13_complete`/`v13_enqueue_effect`/resolve 族/needed 语义零改动。
2. **三禁(§4.1 冻结纪律)**:所有 `==>` 只许出现在 `v13_recall` 函数族体内且经 EXECUTE 动态执行;视图内嵌 `==>`、plpgsql 静态 `==>`、worker 预备语句直发 `==>` 一律禁止(生产面;gate fixture 演示对象除外且测后即弃)。执法=源码扫描(归一化口径=剥 `--` 行注释与 `/* */` 块注释后扫描,§4 断言纪律;加载文件 `==>` 只许在第 9 位文件的 v13_recall v2/count v2 两条 EXECUTE 字符串字面量,逐文件计数=R2)+行为断言(EXECUTE 形态 EXPLAIN 每次 Custom Scan+canary 命中;实测降级面呈报,附 A #1)。
3. **用户文本不得直接成为 TINQL**:唯一缝=v13_build_tinql(构造性免疫,OQ7);v13_recall 入口经 v13_tinql_terms 文法守卫 fail-closed(V3005);信封与 manifest 不内嵌 TINQL。
4. **退役源不进召回面(DP4 契约⑨)**:recall v1/v2/count 的源枚举一律 `JOIN v13_sources src ON src.source_hash=c.source_hash AND src.superseded_by IS NULL`(gate B 组;B5b 读侧半边)。
5. **排序确定性**:`ORDER BY 分值 DESC, content_hash ASC` 全落点(recall 返回、信封 candidates、manifest candidates 聚合内显式 ORDER BY——聚合内钉序,DP3 实施注记 (a2) 同款);并列截断不抖。
6. **确定性**:构造器/recall/count/candidates 零时钟零随机零活策略读(k/timeout 经策略行单次读取后为参数;策略形状 fail-closed);同输入同输出(gate 直调断言);token 第九键只读策略版本(单调域)。
7. **承重件不依赖 stannum(§4.8)**:第 8 位文件零 `==>`、零 `stannum.` 限定引用(归一化口径,gate G1;草案注释已散文化,原始口径亦零);第 8 位 gate 在无 stannum 库可全绿;stannum 面(索引/换体/刻画)全部关在第 9 位 gate 后。
8. **单 stannum 索引纪律(OQ6)**:chunks 表恰一个 stannum 索引;canary 索引只在专用 fixture 表;bigram 未来走独立列(§4.6 原文,引擎佐证)。
9. **哈希同源**:csh 材料单点(envelope);goal 查询文本单点(v13_goals 活动行 payload->>'text');k 单点(recall_k 策略);候选单点(v13_recall_candidates——信封与装配共用,禁第二实现);token 单点(v13_context_required,九键)。
10. **文档顺序=加载顺序**;第 8/9 位纯末尾追加;stage 8 gate 引用 ≤8 号文件对象、stage 9 ≤9 号;DP1–4 各 gate 在前缀库复跑不受换体影响(结构性);新 RAISE 统一 `USING ERRCODE='V3005'`(DP1–4=V3001–V3004 序列顺延,已核无占用);**唯一例外**=复制体的既有 RAISE 与 V 码逐字保留(墓碑纪律优先于统一码面,DP4 同款)。

---

## 2. 输入 § 映射

| 设计原文(冻结) | 本 plan 落点 |
|---|---|
| §4.1 所有 ==> 只许出现在 v13_recall 函数族体内,经 EXECUTE(或 force_custom_plan)强制每次重规划 | v2 体=RETURN QUERY EXECUTE(每次新计划→绑定 planner 当前最优索引;实测 bind_query 机制);三禁=不变量 2;gate K/R 组 |
| §4.1 三禁:视图内嵌/plpgsql 静态/worker 预备语句直发 | 不变量 2;源码扫描(归一化,gate G/R)+行为演示(gate K5,实测注记附 A #1);README 纪律 |
| §4.1 用户文本经受限 compiler v13_build_tinql(长度/通配/正则/fuzzy/展开上限/执行超时全限) | OQ7 三层构造器(4096B/256B/64 段上限=长度+展开;操作符构造性不存在=通配/正则/fuzzy);timeout_ms=OQ5 驱动层;gate A 组+G 组 |
| §4.1 排序 ORDER BY bm25 DESC, content_hash ASC 并列截断确定性 | 不变量 5;OQ4 两代载体;gate B/P 组双跑字节等 |
| §4.1 Gate:EXPLAIN 只钉形状(FORMAT JSON 出现 stannum IndexScan、chunks 无 Seq Scan)+tokenizer canary(索引 tokenizer 与默认切分不同的 fixture,召回必须命中,回落即红) | K1(EXPLAIN FORMAT JSON:Node Type=Custom Scan+Custom Plan Provider='Stannum Text Search Scan'+Index=ix_chunks_stannum;enable_seqscan=off 会话局部强制——DP4 verify ⑤ 同方案同理由;**「stannum IndexScan」的 0.1.0 实测形态=Custom Scan**,附 A #1);K6/L 组 canary(专用表+split 索引+64B 精确块查询:EXECUTE 命中/默认 comparator 漏召) |
| §4.6 逐字切分下常用字 IDF 趋零——质量来自过滤层,候选池不漏就不死 | README 论证载体;count 自适应放宽的动机注记;k 硬上限(OQ5)防「池不漏」被无限放宽反噬 |
| §4.6 精确 count(*) 让 k 随候选规模自适应放宽(策略行) | recall_k 策略行+公式(OQ5);v1 tsv count/v2 ==> count(OQ4 附则);gate C/J 组 |
| §4.6 v13_build_tinql 语言分段、CJK 语段一律短语引用——是代码不是字符串;gate 用 kohaku fixtures 钉混合查询形状 | OQ7(连续 CJK 段=整体引号短语);kohaku fixture(東京タワー+quasar 混合)gate A 组(v1)与 P 组(v2 实索引命中) |
| §4.6 bigram 升级路径只记台账(触发:kohaku 漏召率超标) | §7 台账行(路径=独立列+独立索引+查询侧同函数,§4.6 原文;同列双索引禁令的引擎佐证已实测) |
| §4.7 BM25 长度归化稀释超长文档——目标尺寸由刻画 gate 用数据回答(先验 2–4KB) | Q 组尺寸刻画面(6 档 fixture→数据表→README 数据答案+人工翻版流程;DP4 契约③的消费点) |
| §4.8 承重件不依赖 stannum;可替换件关在刻画 gate 后;tsvector T0 先跑通,刻画完换 recall 函数 definition;CJK 直接 stannum 但仍先过刻画 gate | OQ2 双 stage+不变量 7;CJK 语义=CJK 语料部署以第 9 位为 T0(tsvector 对 CJK 子串零召回是 DP4 F2/设计既裁物理,第 8 位 gate B 钉边界不修) |
| §4.8 刻画 gate 内容:fixture 灌入、==> 绑定矩阵(EXECUTE/视图/预备语句)实测、fold 持锁 p99 压测、verify_index+REINDEX 演练、>1024 展开回落行为钉断言 | K 组(绑定矩阵+EXPLAIN 形状)/L 组(canary)/M 组(fold p99+segment_info 观测)/N 组(verify_index+REINDEX+verify v2)/O 组(>1024:编译器 64 段上限挡用户面+引擎面直测保守回查正确性) |
| §7 T0(默认):英 tsvector 起步→stannum 刻画后;CJK stannum 刻画后 | 双 stage 即 T0 两代;T1/T2 只记触发(§7) |
| §7 T1(stannum+vectorchord RRF 一条 SQL;嵌入=派生缓存行 content_hash×model,embed=effect)只记触发条件(固定评估集证明 lexical 漏召)不实现 | §7 台账行(嵌入缓存行形态+embed=effect 纪律照抄入台账,零实现) |
| §8 stannum runbook:索引可丢基础行不可丢/连接池预热/fold 毛刺/升级/REINDEX 演练/AGPL 分发审查 | characterize README 六件全落+新连接 buffer 重建预热注记;gate R 组断言 README 在场条目清单;索引丢失=性能事件非正确性事件(OQ6 论证)亦入 README |
| §8 verify_index 进 gate+pg_cron 夜跑(DP4 已立载体) | verify v2 第八项(N 组);cron job 零新增(DP4 job 调 v13_verify_chunks(true) 自动升 v2 面——「调度是行」的零改动红利);gate R 组断言 job 清单仍恰一条 |
| §9 策略行切片:recall_boosts(建但为空,留缝) | 种子 {"boosts":[]};v2 体消费:空⇒零影响(P 组字节等),非空 V3005 拒(未实证语法,台账触发);版本不入 token(OQ8) |
| §10 G-ctx3 全部四断言 | §4 G-ctx3 映射表(A/C/G/K/L 组逐条) |
| §12 YAGNI 台账(本 DP 相关行) | §7 明确不做逐条(台账为源) |
| §13 第 10 章:T0 前插刻画/三禁/装配清单 schema/存在性 Noul 归 DP6/v13_build_tinql | §6 教程映射(正文已在场零改动;兑现对照表) |
| stepfun F5(k 上界与延迟账在 DP5 范围) | OQ5+§4 末一页账表+J 组;F5①③→DP7 缝(§1.4) |
| stepfun F4(Jev 层刻画缺位的反向提示) | 刻画 gate 六件全部真实执行(M 组真压测/N 组真演练/O 组真断言);runbook 六件全落;零「纸面刻画」 |

---

## 3. 表/函数 DDL 与 SQL 草案

> 文件一:`v13/recall/v13_recall.sql`(全新增;SQL_LOAD_ORDER 第 8 位纯末尾追加);文件二:`v13/characterize/v13_characterize.sql`(第 9 位)。**文件内顺序=加载顺序**。两文件各以 BEGIN/COMMIT 包裹(DP2–DP4 形制:含 OR REPLACE,单事务原子装载)。草案级完整度:列/约束/函数签名/关键语句到位,实施者可直接开写;注释标注纪律出处。**新 RAISE 统一 V3005;复制体的既有 RAISE/V 码逐字保留**(不变量 10)。

### 3.1 文件一 `v13/recall/v13_recall.sql`(第 8 位;tsvector T0+接线;零 stannum 依赖)

```sql
BEGIN;

-- =========================================================================
-- DP5 recall (v13_recall.sql): T0 tsvector recall + TINQL compiler +
-- envelope/assemble wiring + cgr corpus wiring.
-- Design: docs/designs/v13-context-on-pg.md §4.1/§4.6/§4.7/§4.8/§7/§8/§9/
-- §10 G-ctx3. Contracts: DP1 §1.3 (#59), DP2 §1.4, DP3 §1.4, DP4 §1.4 ①-⑨.
-- File order = load order. Zero dependency on the text-search extension
-- (invariant 7): this file contains no bind-operator literals and no
-- extension-qualified calls, in code or in comments (gate G asserts).
-- =========================================================================

-- === L1 查询构造器(§4.6 受限 compiler;纯文本,零引擎依赖) ===
-- 分段器:字符三分类(ASCII 字母数字=latin / CJK 码区=cjk / 其余=分隔符);
-- 同类连续段=一语段;CJK 语段整体一个短语段(「CJK 语段一律短语引用」的
-- 构造形态)。上限 fail-closed:查询 4096B / 语段 256B / 64 语段(V3005)。
-- 通配/正则/fuzzy 构造性不存在:操作符字符全部是分隔符,分段器只产词。
-- 边界注:Latin-1 变音字母(é 等)按分隔符归类(ASCII 词界;语料英文为
-- 主的 T0 假设下可接受,README 记;变音语料真实出现时评估扩类)。
CREATE FUNCTION v13_query_segments(p_query text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_chars text[]; v_n int; v_i int; v_ch text; v_cp int;
  v_class text; v_cur_class text := 'sep'; v_cur text := '';
  v_texts text[] := '{}'; v_cnt int := 0;
BEGIN
  IF p_query IS NULL OR p_query = '' THEN RETURN '[]'::jsonb; END IF;
  IF octet_length(p_query) > 4096 THEN
    RAISE EXCEPTION 'v13: query exceeds max bytes (4096)'
      USING ERRCODE = 'V3005';
  END IF;
  v_chars := regexp_split_to_array(p_query, '');
  v_n := coalesce(array_length(v_chars, 1), 0);
  FOR v_i IN 1 .. v_n LOOP
    v_ch := v_chars[v_i];
    v_cp := ascii(v_ch);
    IF v_ch ~ '[a-zA-Z0-9]' THEN
      v_class := 'latin';
    ELSIF (v_cp BETWEEN 12352 AND 12543)   -- U+3040..30FF 仮名(平/片)
       OR (v_cp BETWEEN 13312 AND 19903)   -- U+3400..4DBF 漢字拡張A
       OR (v_cp BETWEEN 19968 AND 40959)   -- U+4E00..9FFF CJK 統合漢字
       OR (v_cp BETWEEN 44032 AND 55215)   -- U+AC00..D7AF ハングル音節
       OR (v_cp BETWEEN 63744 AND 64255)   -- U+F900..FAFF 康熙互換漢字
    THEN
      v_class := 'cjk';
    ELSE
      v_class := 'sep';
    END IF;
    IF v_class = v_cur_class THEN
      v_cur := v_cur || v_ch;
    ELSE
      IF v_cur_class <> 'sep' THEN
        IF octet_length(v_cur) > 256 THEN
          RAISE EXCEPTION 'v13: query segment exceeds max bytes (256)'
            USING ERRCODE = 'V3005';
        END IF;
        v_texts := v_texts || v_cur; v_cnt := v_cnt + 1;
        IF v_cnt > 64 THEN
          RAISE EXCEPTION 'v13: query exceeds max segments (64)'
            USING ERRCODE = 'V3005';
        END IF;
      END IF;
      v_cur := v_ch; v_cur_class := v_class;
    END IF;
  END LOOP;
  IF v_cur_class <> 'sep' THEN
    IF octet_length(v_cur) > 256 THEN
      RAISE EXCEPTION 'v13: query segment exceeds max bytes (256)'
        USING ERRCODE = 'V3005';
    END IF;
    v_texts := v_texts || v_cur; v_cnt := v_cnt + 1;
    IF v_cnt > 64 THEN
      RAISE EXCEPTION 'v13: query exceeds max segments (64)'
        USING ERRCODE = 'V3005';
    END IF;
  END IF;
  RETURN (SELECT coalesce(jsonb_agg(t ORDER BY ord), '[]'::jsonb)
            FROM unnest(v_texts) WITH ORDINALITY AS u(t, ord));
END $$;

-- 发射器:全语段引号包裹 AND 连接。引号内=字面短语(TINQL 关键字词被
-- 免疫);语段不可能含引号/空格/' AND '(分隔符归类保证)⇒ 文法封闭、
-- 零转义面、注入构造性免疫(OQ7)。空/空白查询 → ''(合法空)。
CREATE FUNCTION v13_build_tinql(p_query text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(string_agg('"' || s || '"', ' AND '), '')
    FROM jsonb_array_elements_text(v13_query_segments(p_query)) AS s
$$;

-- 回析器:只接受自产文法(quoted AND form);异形 RAISE V3005——
-- v13_recall 入口的 fail-closed 信封(G-ctx3 注入被拒的函数面)。
CREATE FUNCTION v13_tinql_terms(p_tinql text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_parts text[]; v_n int; v_i int; v_inner text;
  v_texts text[] := '{}';
BEGIN
  IF p_tinql IS NULL THEN
    RAISE EXCEPTION 'v13: tinql must not be NULL' USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN '[]'::jsonb; END IF;
  v_parts := string_to_array(p_tinql, ' AND ');
  v_n := array_length(v_parts, 1);
  FOR v_i IN 1 .. v_n LOOP
    v_inner := v_parts[v_i];
    IF length(v_inner) < 2
       OR left(v_inner, 1) <> '"'
       OR right(v_inner, 1) <> '"'
       OR position('"' in substring(v_inner FROM 2 FOR length(v_inner) - 2)) > 0
    THEN
      RAISE EXCEPTION
        'v13: tinql not in emitted grammar (quoted segments joined by AND)'
        USING ERRCODE = 'V3005';
    END IF;
    v_inner := substring(v_inner FROM 2 FOR length(v_inner) - 2);
    IF octet_length(v_inner) = 0 OR octet_length(v_inner) > 256 THEN
      RAISE EXCEPTION 'v13: tinql segment out of bounds'
        USING ERRCODE = 'V3005';
    END IF;
    v_texts := v_texts || v_inner;
  END LOOP;
  IF array_length(v_texts, 1) > 64 THEN
    RAISE EXCEPTION 'v13: tinql exceeds max segments (64)'
      USING ERRCODE = 'V3005';
  END IF;
  RETURN (SELECT coalesce(jsonb_agg(t ORDER BY ord), '[]'::jsonb)
            FROM unnest(v_texts) WITH ORDINALITY AS u(t, ord));
END $$;

-- === L2 recall v1(§7 T0:tsvector 起步;§4.1 函数族签名在此冻结) ===
-- bm25 列的 T0 载体=ts_rank 确定性实数(排序用途,非 BM25 语义——诚实
-- 边界;v2 换 stannum 侧 full_score)。排序 ORDER BY 2 DESC, 1 ASC=输出列
-- 引用(与 SELECT 值恒一致;并列由 content_hash ASC 终裁,截断不抖)。
-- 退役源过滤(DP4 契约⑨):JOIN v13_sources ... superseded_by IS NULL。
-- belt:p_k∈[1,1024](k 策略钳制在调用侧)。
CREATE FUNCTION v13_recall(p_tinql text, p_k int)
RETURNS TABLE(content_hash text, bm25 numeric, spans jsonb)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_segs jsonb; v_seg text; v_q tsquery;
BEGIN
  IF p_tinql IS NULL OR p_k IS NULL OR p_k < 1 OR p_k > 1024 THEN
    RAISE EXCEPTION 'v13: v13_recall args out of bounds'
      USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN; END IF;
  v_segs := v13_tinql_terms(p_tinql);
  v_q := NULL;
  FOR v_seg IN SELECT jsonb_array_elements_text(v_segs) LOOP
    v_q := CASE WHEN v_q IS NULL
              THEN phraseto_tsquery('english'::regconfig, v_seg)
              ELSE v_q && phraseto_tsquery('english'::regconfig, v_seg) END;
  END LOOP;
  RETURN QUERY
  SELECT c.content_hash,
         ts_rank(c.body_tsv, v_q)::numeric,
         v13_extract_spans(c.body, v_segs)
    FROM chunks c
    JOIN v13_sources src
      ON src.source_hash = c.source_hash AND src.superseded_by IS NULL
   WHERE c.body_tsv @@ v_q
   ORDER BY 2 DESC, 1 ASC
   LIMIT p_k;
END $$;

-- 精确 count(k 自适应的基数;§4.6「并发下精确 count(*)」的 T0 形态=
-- MVCC 精确计数)。v2 世代在第 9 位文件同步换体(OQ4 附则:count 人口
-- 必须与 recall 人口同引擎,否则 CJK 下 k 自适应失效)。
CREATE FUNCTION v13_recall_count(p_tinql text) RETURNS bigint
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_segs jsonb; v_seg text; v_q tsquery;
BEGIN
  IF p_tinql IS NULL THEN
    RAISE EXCEPTION 'v13: tinql must not be NULL' USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN 0; END IF;
  v_segs := v13_tinql_terms(p_tinql);
  v_q := NULL;
  FOR v_seg IN SELECT jsonb_array_elements_text(v_segs) LOOP
    v_q := CASE WHEN v_q IS NULL
              THEN phraseto_tsquery('english'::regconfig, v_seg)
              ELSE v_q && phraseto_tsquery('english'::regconfig, v_seg) END;
  END LOOP;
  RETURN (SELECT count(*) FROM chunks c
            JOIN v13_sources src
              ON src.source_hash = c.source_hash AND src.superseded_by IS NULL
           WHERE c.body_tsv @@ v_q);
END $$;

-- === L3 集成点:候选推导的单一来源(信封与装配共用;哈希同源) ===
-- 读活动 goal 文本(v13_goals 活动行 max(seq);payload->>'text' ——v12
-- convention 实证);构造 TINQL;count→k 自适应(OQ5 公式);返回
-- {k, matched, candidates}(k/matched 入 csh 材料、candidates 冻结入
-- 信封第 20 键)。timeout_ms 在此校验(fail-closed),消费在驱动层
-- (DP1 #60:函数内 set_config 不治理嵌套语句;README 驱动契约)。
CREATE FUNCTION v13_recall_candidates(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_txt text; v_tinql text; v_pol jsonb;
  v_kb numeric; v_wr numeric; v_kmax numeric; v_tmo numeric;
  v_cnt bigint; v_k int;
BEGIN
  SELECT coalesce(g.payload->>'text', '') INTO v_txt
    FROM v13_goals g
   WHERE g.session_id = p_sid
   ORDER BY g.seq DESC LIMIT 1;
  v_tinql := CASE WHEN coalesce(v_txt, '') = '' THEN ''
                  ELSE v13_build_tinql(v_txt) END;
  IF v_tinql = '' THEN
    RETURN jsonb_build_object('k', 0, 'matched', 0, 'candidates', '[]'::jsonb);
  END IF;
  v_pol := v13_policy('recall_k');
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol->'k_base') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'widen_ratio') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'k_max') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'timeout_ms') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid recall_k policy shape'
      USING ERRCODE = 'V3005';
  END IF;
  v_kb := (v_pol->>'k_base')::numeric; v_wr := (v_pol->>'widen_ratio')::numeric;
  v_kmax := (v_pol->>'k_max')::numeric; v_tmo := (v_pol->>'timeout_ms')::numeric;
          -- 分步类型先验后显式 cast(->> 取 text 再 ::numeric——DP4 §3.2
          -- 三律同款;上方 jsonb_typeof 先验已挡非 number 键的 22P02)
  IF v_kb < 1 OR v_wr < 0 OR v_kmax < v_kb OR v_tmo <= 0 THEN
    RAISE EXCEPTION 'v13: invalid recall_k policy values'
      USING ERRCODE = 'V3005';
  END IF;
  v_cnt := v13_recall_count(v_tinql);
  v_k := least(v_kmax::int, greatest(v_kb::int, ceil(v_cnt * v_wr)::int));
  RETURN jsonb_build_object(
    'k', v_k,
    'matched', v_cnt,
    'candidates', (SELECT coalesce(jsonb_agg(
        jsonb_build_object(
          'content_hash', r.content_hash,
          'bm25', r.bm25,
          'spans', jsonb_build_array(jsonb_build_object(
                     'doc', r.content_hash, 'offsets', r.spans)))
        ORDER BY r.bm25 DESC, r.content_hash ASC), '[]'::jsonb)
      FROM v13_recall(v_tinql, v_k) AS r));
END $$;

-- === L4 cgr 语料接线(DP1 #59 硬契约的执行点;OQ1 选 bump 面) ===
-- OR REPLACE 换体(同签名;DP4 §3.1 定义、触发器已挂,触发器无需重建):
-- 在 bump 语料代数后,同一函数把 candidate_generation_revision 一并 +1
-- ——候选推导面第四源(语料代数)并入 cgr,probe 七键论证在语料面闭合。
-- 双单行 UPDATE:摄取是 owner 离线面;与 settle 的 tools_meta 冻结锁只
-- 在该行互斥(短阻塞无环,OQ1 论证);与 advance 步 0 probe 的 MVCC 读
-- 不阻塞。
CREATE OR REPLACE FUNCTION v13_chunks_generation_bump() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE v13_chunks_meta SET generation = generation + 1 WHERE singleton;
  UPDATE v13_tools_meta
     SET candidate_generation_revision = candidate_generation_revision + 1
   WHERE singleton;                        -- DP5: DP1 #59 语料代数并入 cgr
  RETURN NULL;
END $$;

-- === L5 token 第九键(DP3 OQ1 追动键缝;OQ8) ===
-- OR REPLACE 同签名换体:DP4 §3.6 八键体逐字复制 + 一 DECLARE(v_rk_ver)
-- + 一 RAISE 块 + 一键(recall_ver,第九)。k 决定 manifest 候选截断,
-- 版本追动漏键=freshness miss(asm_ver 同类);键集八→九 ⇒ 全域恰一次
-- refresh(DP3 OQ1 既判,gate I 组)。span_assembly/boosts 不入(OQ8)。
CREATE OR REPLACE FUNCTION v13_context_required(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_asm_ver int; v_jdef_ver int; v_gen_ver int; v_corpus bigint;
        v_rk_ver int; v_tok jsonb;
BEGIN
  SELECT version INTO v_asm_ver FROM v13_policies
   WHERE name = 'assemble_manifest' AND active;
  IF v_asm_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active assemble_manifest policy (seed lost?)';
  END IF;
  SELECT version INTO v_jdef_ver FROM v13_policies
   WHERE name = 'judgment_defaults' AND active;
  IF v_jdef_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active judgment_defaults policy (seed lost?)';
  END IF;
  SELECT version INTO v_gen_ver FROM v13_policies
   WHERE name = 'generation' AND active;
  IF v_gen_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active generation policy (seed lost?)';
  END IF;
  SELECT generation INTO v_corpus FROM v13_chunks_meta WHERE singleton;
  IF v_corpus IS NULL THEN
    RAISE EXCEPTION 'v13: chunks meta row lost (seed dropped?)';
  END IF;
  SELECT version INTO v_rk_ver FROM v13_policies
   WHERE name = 'recall_k' AND active;
  IF v_rk_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active recall_k policy (seed lost?)';
  END IF;
  SELECT jsonb_build_object(
    'sem',      coalesce((SELECT max(seq) FROM events
                           WHERE session_id = p_sid
                             AND type IN ('user/message','llm/message',
                                          'tool/result')), -1),
    'dec',      (SELECT count(*) FROM decisions
                  WHERE session_id = p_sid AND answer IS NOT NULL),
    'goal',     v13_goal_hash(p_sid),
    'tools_rev',(SELECT revision FROM v13_tools_meta WHERE singleton),
    'asm_ver',  v_asm_ver,
    'jdef_ver', v_jdef_ver,
    'gen_ver',  v_gen_ver,                  -- DP3 第七键(逐字保留)
    'corpus',   v_corpus,                   -- DP4 第八键(逐字保留)
    'recall_ver', v_rk_ver)                 -- DP5 第九键(OQ8)
  INTO v_tok;
  RETURN v_tok;
END $$;
-- 墓碑纪律:八键体唯一存活于本树 ≤7 号文件的库;九键体全树唯一存活于
-- ≥8 号文件的库(非移动,授权换体——DP4 §3.6 同款注记)。

-- === L6 信封换体(DP1 §1.3 候选集来源缝;OQ3) ===
-- OR REPLACE 同签名:DP3 §3.6 十九键体逐字复制 + 三处增量:①新增
-- MATERIALIZED CTE rc(单语句快照纪律:rc 与 needed/ctx 同点求值);
-- ②candidate_set_hash 材料扩集(needed∪recall——「对推导结果全集取
-- hash」公式不变,全集扩含召回候选,附 A #3);③追加第 20 键 candidates
-- (parse 时冻结的召回候选,DP6 per-chunk needed 的唯一消费点)。
-- 不内嵌 TINQL(附 A #5);k/matched 入 csh 材料不入键。
CREATE OR REPLACE FUNCTION v13_judgment_envelope(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  WITH runtime AS MATERIALIZED (
    SELECT v13_guc_required('typesafe.provider') AS provider,
           v13_guc_required('typesafe.model') AS model),
  ctx AS MATERIALIZED (
    SELECT v13_canonical_state(p_sid) AS c),
  needed AS MATERIALIZED (
    SELECT coalesce(jsonb_agg(
             CASE WHEN n.criteria IS NULL THEN
               jsonb_build_object('signal', n.signal, 'kind', n.kind,
                                  'question', n.question,
                                  'template_name', n.template_name)
             ELSE
               jsonb_build_object('signal', n.signal, 'kind', n.kind,
                                  'question', n.question, 'criteria', n.criteria,
                                  'template_name', n.template_name)
             END ORDER BY n.signal), '[]'::jsonb) AS n
      FROM v13_needed_judgments(p_sid) n),
  tmpl AS MATERIALIZED (
    SELECT coalesce(jsonb_object_agg(t.template_name, jsonb_build_object(
             'version', t.template_version, 'kind', t.kind,
             'projection', t.projection,
             'answer_schema_version', t.answer_schema_version)), '{}'::jsonb) AS t
      FROM v13_template_latest t),
  groups AS MATERIALIZED (
    SELECT coalesce(jsonb_agg(jsonb_build_object('projection_key', s.pkey,
                                                 'state', s.state)
                              ORDER BY s.pkey), '[]'::jsonb) AS g
      FROM (SELECT DISTINCT
              v13_projection_key(
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS pkey,
              v13_project_state(
                (SELECT c FROM ctx),
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS state
              FROM jsonb_array_elements((SELECT n FROM needed)) nr) s),
  wm AS MATERIALIZED (
    SELECT (SELECT next_seq FROM sessions WHERE session_id = p_sid) AS sv,
           coalesce((SELECT max(seq) FROM events
                      WHERE session_id = p_sid), -1) AS mes),
  pol AS MATERIALIZED (
    SELECT route_policy_name AS rpn, route_policy_version AS rpv
      FROM sessions WHERE session_id = p_sid),
  rc AS MATERIALIZED (                       -- DP5:召回候选(parse 快照冻结)
    SELECT v13_recall_candidates(p_sid) AS r)
  SELECT jsonb_build_object(
    'sid', p_sid,
    'ctx', (SELECT c FROM ctx),
    'needed', (SELECT n FROM needed),
    'templates', (SELECT t FROM tmpl),
    'groups', (SELECT g FROM groups),
    'timeout_ms', current_setting('typesafe.timeout_ms', true),
    'budget', v13_policy('resolve_fast_path'),
    'candidate_set_hash',
      encode(digest(jsonb_build_object(
        'needed', (SELECT n FROM needed),
        'recall', (SELECT r FROM rc))::text, 'sha256'), 'hex'),
    'goal_hash', v13_goal_hash(p_sid),
    'provider', (SELECT provider FROM runtime),
    'model',    (SELECT model FROM runtime),
    'route_policy_name',     (SELECT rpn FROM pol),
    'route_policy_version',  (SELECT rpv FROM pol),
    'tools_revision', (SELECT revision FROM v13_tools_meta WHERE singleton),
    'tools_catalog',  v13_tools_catalog_frozen(),
    'candidate_generation_revision',
      (SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton),
    'session_version', (SELECT sv FROM wm),
    'max_event_seq',   (SELECT mes FROM wm),
    'needed_count', jsonb_array_length((SELECT n FROM needed)),
    'candidates', (SELECT r->'candidates' FROM rc));
$$;
-- 实施纪律:从 v13/envelope/v13_envelope.sql 加载态原文机械复制(比计划
-- 文本更权威,DP3 风险 #1 同款),仅按上块注释的三处增量编辑。

-- === L7 装配换体(DP3 §1.4 DP5 行填充缝;契约 #9) ===
-- OR REPLACE 同签名:DP3 §3.4 全体逐字复制,唯一增量=qside 的 candidates
-- 表达式(goal echo 退役,由 v13_recall_candidates 单一来源供给);
-- 聚合内显式钉序 (bm25)::numeric DESC, content_hash ASC;|| 补第四键
-- decision_id:NULL(DP3 校验器层 6 恰四键要求);jud 消费集谓词
-- (cand->>'decision_id' IS NOT NULL)自动过滤 NULL ⇒ judgments 仍 []。
-- manifest 不内嵌 TINQL(本函数只消费 candidates 数组)。
CREATE OR REPLACE FUNCTION v13_assemble_manifest(p_sid uuid,
                                                  p_policy_version int DEFAULT NULL)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
WITH pol AS MATERIALIZED (
  SELECT p.version,
         (p.value->>'budget_tokens')::int        AS budget,
         (p.value->>'est_bytes_per_token')::int  AS divisor,
         p.value->'priority_overrides'           AS prio_ovr,
         p.value->'kinds_disabled'               AS kinds_off,
         (SELECT q.version FROM v13_policies q
           WHERE q.name = 'judgment_defaults' AND q.active) AS jdef_ver
  FROM v13_policies p
  WHERE p.name = 'assemble_manifest'
    AND p.version = coalesce(p_policy_version,
        (SELECT q.version FROM v13_policies q
          WHERE q.name = 'assemble_manifest' AND q.active))
), tok AS MATERIALIZED (
  SELECT v13_context_required(p_sid) AS t
), ident AS MATERIALIZED (
  SELECT v13_prefix_identity(p_sid) AS pid
), cs AS MATERIALIZED (
  SELECT v13_canonical_state(p_sid) AS c
), pri AS MATERIALIZED (
  SELECT s.context_active_artifact AS aid, a.inline AS m
  FROM sessions s LEFT JOIN artifacts a ON a.artifact_id = s.context_active_artifact
  WHERE s.session_id = p_sid
), pri_sec AS MATERIALIZED (
  SELECT ps->>'section_id' AS section_id, ps->>'content_hash' AS content_hash,
         (ps->>'churn')::int AS churn
  FROM pri, jsonb_array_elements(
         CASE WHEN jsonb_typeof(pri.m->'sections') = 'array'
              THEN pri.m->'sections' ELSE '[]'::jsonb END) ps
), sec_src AS MATERIALIZED (
  SELECT 'goal'::text AS section_id, 'goal'::text AS kind,
         'Session'::text AS cache_scope, 'First'::text AS def_prio,
         v13_goal_hash(p_sid) AS content_hash,
         octet_length(coalesce((SELECT g.payload::text FROM v13_goals g
                           WHERE g.session_id = p_sid
                        ORDER BY g.seq DESC LIMIT 1), '')) AS bytes,
         coalesce((SELECT max(seq) FROM v13_goals
                    WHERE session_id = p_sid), -1) AS gseq,
         NULL::jsonb AS mat
  UNION ALL
  SELECT 'history','history','Session','Normal',
         encode(digest(coalesce((cs.c -> 'messages')::text, ''), 'sha256'),
                'hex'),
         octet_length(coalesce((cs.c -> 'messages')::text, '')),
         NULL::bigint, cs.c -> 'messages'
  FROM cs
  UNION ALL
  SELECT 'tools','tools','Global','First',
         encode(digest(coalesce((cs.c -> 'tools')::text, ''), 'sha256'),
                'hex'),
         octet_length(coalesce((cs.c -> 'tools')::text, '')),
         NULL::bigint, cs.c -> 'tools'
  FROM cs
), cls AS MATERIALIZED (
  SELECT r.*,
         CASE WHEN (pol.prio_ovr ->> r.kind)
                   IN ('First','Normal','Never','LastResort') IS TRUE
              THEN pol.prio_ovr ->> r.kind
              ELSE r.def_prio END AS eff_priority,
         ((r.bytes + pol.divisor - 1) / pol.divisor)::int AS est_tokens,
         CASE coalesce(pol.prio_ovr ->> r.kind, r.def_prio)
           WHEN 'First'      THEN 1
           WHEN 'Normal'     THEN 2
           WHEN 'Never'      THEN 3
           WHEN 'LastResort' THEN 4
         END AS prank,
         CASE WHEN (pol.prio_ovr -> r.kind) IS NOT NULL
               AND (pol.prio_ovr ->> r.kind)
                   IN ('First','Normal','Never','LastResort') IS NOT TRUE
              THEN 'invalid_override'
              WHEN coalesce(pol.prio_ovr ->> r.kind, r.def_prio) = 'Never'
              THEN 'priority_never'
              WHEN pol.kinds_off @> to_jsonb(r.kind)
              THEN 'disabled'
              ELSE NULL END AS pre_skip,
         CASE WHEN r.section_id = 'goal'
              THEN jsonb_build_object('kind','goal','seq', r.gseq)
              ELSE jsonb_build_object('kind','blob','content_hash',
                encode(digest(coalesce(r.mat::text, ''), 'sha256'), 'hex'))
         END AS payload_ref
  FROM sec_src r, pol
), packed AS MATERIALIZED (
  SELECT c.section_id,
         sum(c.est_tokens) OVER (ORDER BY c.prank, c.section_id
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_incl
  FROM cls c
  WHERE c.pre_skip IS NULL
), ordered AS MATERIALIZED (
  SELECT c.*,
         (p.section_id IS NULL) AS prior_missing,
         coalesce(p.content_hash, '') AS prior_hash,
         coalesce(p.churn, 0)          AS prior_churn,
         k.run_incl
  FROM cls c
       LEFT JOIN packed k ON k.section_id = c.section_id
       LEFT JOIN pri_sec p ON p.section_id = c.section_id
), final_sec AS MATERIALIZED (
  SELECT jsonb_build_object(
    'section_id',  o.section_id,
    'kind',        o.kind,
    'cache_scope', o.cache_scope,
    'priority',    o.eff_priority,
    'content_hash',o.content_hash,
    'est_tokens',  o.est_tokens,
    'payload_ref', o.payload_ref,
    'churn',       CASE WHEN o.prior_missing THEN 0
                        WHEN o.content_hash IS DISTINCT FROM o.prior_hash
                        THEN o.prior_churn + 1 ELSE 0 END,
    'transform',   CASE
                     WHEN o.pre_skip IS NOT NULL THEN
                       jsonb_build_object('applied', false,
                                          'reason', o.pre_skip)
                     WHEN o.run_incl > pol.budget THEN
                       jsonb_build_object('applied', false,
                                          'reason', 'budget')
                     ELSE
                       jsonb_build_object('applied', true, 'name',
                         CASE o.section_id WHEN 'goal'   THEN 'verbatim'
                                           WHEN 'history' THEN 'verbatim'
                                           ELSE 'catalog_digest' END)
                   END
  ) AS section, o.prank, o.section_id
  FROM ordered o, pol
), goal_addr AS MATERIALIZED (
  SELECT coalesce((SELECT jsonb_build_object('kind','goal','seq',g.seq,
                              'content_hash',g.content_hash)
                     FROM v13_goals g WHERE g.session_id = p_sid
                 ORDER BY g.seq DESC LIMIT 1),
                  'null'::jsonb) AS a
), qside AS MATERIALIZED (
  SELECT jsonb_build_object(
    'query_artifact_id', (SELECT a FROM goal_addr),
    'candidates', (SELECT coalesce(jsonb_agg(
                     c || jsonb_build_object('decision_id', NULL)
                       ORDER BY (c->>'bm25')::numeric DESC,
                                c->>'content_hash' ASC), '[]'::jsonb)
                     FROM jsonb_array_elements(
                            v13_recall_candidates(p_sid) -> 'candidates') c)
                   -- DP5 填充缝兑现:goal echo 退役;单一来源=
                   -- v13_recall_candidates(哈希同源);|| 补第四键
                   -- decision_id:NULL(DP3 校验器层 6 恰四键);聚合内
                   -- 钉序=不变量 5;manifest 不内嵌 TINQL
  ) AS q
), jud AS MATERIALIZED (
  SELECT coalesce(jsonb_agg(jsonb_build_object(
    'decision_id',    d.decision_id,
    'epoch',          d.epoch,
    'request_hash',   d.request_hash,
    'template_name',  d.template_name,
    'template_version', d.template_version,
    'raw_verdict',    d.answer,
    'final_action',   'recorded'
  ) ORDER BY d.decision_id), '[]'::jsonb) AS j
  FROM decisions d
  WHERE d.answer IS NOT NULL
    AND d.status IN ('answered','cached')
    AND d.decision_id::text IN (
    SELECT cand->>'decision_id'
    FROM qside, jsonb_array_elements(qside.q->'candidates') cand
    WHERE cand->>'decision_id' IS NOT NULL)
), mode AS MATERIALIZED (
  SELECT CASE
           WHEN pri.m IS NULL THEN 'fresh'
           WHEN (pri.m->>'prefix_identity')
                IS DISTINCT FROM (SELECT pid FROM ident) THEN 'fresh'
           ELSE 'recompute'
         END AS m
  FROM pri
)
SELECT jsonb_build_object(
  'manifest_version', 1,
  'session_id', p_sid,
  'turn_no',   (SELECT turn_no FROM sessions WHERE session_id = p_sid),
  'prefix_identity', (SELECT pid FROM ident),
  'policy',    jsonb_build_object(
                 'assemble_version',   (SELECT version FROM pol),
                 'budget_tokens',      (SELECT budget FROM pol),
                 'est_bytes_per_token',(SELECT divisor FROM pol),
                 'judgment_defaults_version', (SELECT jdef_ver FROM pol)),
  'required_revision', (SELECT t FROM tok),
  'sections',  (SELECT coalesce(jsonb_agg(section ORDER BY prank, section_id),
                             '[]'::jsonb)
                  FROM final_sec),
  'query_side',(SELECT q FROM qside),
  'judgments', (SELECT j FROM jud),
  'replay',    jsonb_build_object('mode', (SELECT m FROM mode),
                                  'prior_artifact_id', (SELECT aid FROM pri)));
$$;
-- 实施纪律:从 v13/manifest/v13_manifest.sql 加载态原文机械复制,仅换
-- qside 的 candidates 表达式(唯一增量;其余 CTE 与外层逐字不动)。
-- required_revision 在本库=九键 token(键集变化⇒恰一次 refresh,gate I)。

-- === L8 策略种子(v13_policies 载体,DP1 契约 #4;单完整 JSON 字面量) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('recall_k',      1, $j${"k_base":8,"widen_ratio":0.05,"k_max":64,"timeout_ms":800}$j$::jsonb, true),
('recall_boosts', 1, $j${"boosts":[]}$j$::jsonb, true);
-- recall_k:k 自适应+执行超时上限(OQ5;k_max=64=F5 首版硬上限,一页账
--   见 §4 末);recall_boosts:§9「建但为空,留缝」——v2 体消费空态零影响
--   (gate P 字节等),非空 V3005 拒(boost 语法 0.1.0 未实证,§12 台账)。
--   种子即校验器输入(recall_candidates 入口 fail-closed,DP4 先例)。

-- === L9 ACL 全量块(文件真末尾;不变量 10) ===
REVOKE EXECUTE ON FUNCTION
  v13_query_segments(text), v13_build_tinql(text), v13_tinql_terms(text),
  v13_recall(text,int), v13_recall_count(text), v13_recall_candidates(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_query_segments(text), v13_build_tinql(text), v13_tinql_terms(text),
  v13_recall(text,int), v13_recall_count(text), v13_recall_candidates(uuid)
TO v13_recall, v13_resolve, v13_route;
             -- 纯读链三角色(DP1 先例):信封在 resolve(parse)下执行、
             -- 装配在 route(settle/refresh DEFINER 内以 owner,直调面仍授)
             -- 直查在 recall——invoker 语义下三角色都需要 EXECUTE 面
GRANT SELECT ON chunks, v13_sources, v13_chunks_meta TO v13_resolve, v13_route;
             -- DP4 §1.4 DP6 行②的半边前移:resolve 半边=本 plan 信封换体(parse 在
             -- resolve 下)创造的第一消费点;route 半边=**本 plan 装配换体创造的
             -- 新授权**(DP4 该行原文只提 resolve——assemble_manifest 换体后消费
             -- chunks,refresh settle 的 DEFINER 内以 owner 跑、直调面在 route,
             -- 授权随消费点);DP6 无需再补此半边(其 v13_resolve 消费直接成立)

COMMIT;
```

### 3.2 文件二 `v13/characterize/v13_characterize.sql`(第 9 位;stannum 刻画+换 definition)

```sql
BEGIN;

-- =========================================================================
-- DP5 characterize (v13_characterize.sql): stannum extension + production
-- index + canary fixture + definition swap (recall/recall_count/extract_spans
-- v2 bodies) + verify v2 (8th check). Gate = test_characterize.py (K-R).
-- Engine facts verified on pgembed PG18.4 + stannum 0.1.0 (2026-09-21
-- probe; see plan §1.3 OQ6/OQ7/OQ9 + 附 B): the bind operator lives in
-- pg_catalog (unindexed-text fallback IMMUTABLE / indexed_query bound
-- form STABLE); planner support rewrites any expr to bind_query(expr, oid);
-- Custom Scan provider = 'Stannum Text Search Scan'; default comparator =
-- unicode/fold/fold/truncate/retain (most permissive).
-- =========================================================================

CREATE EXTENSION IF NOT EXISTS stannum;
-- 无降级守卫:刻画 stage 的存在前提就是 stannum;不可用=加载响亮失败
-- (fail-closed)。setup_db.py 硬前置探针(pg_available_extensions)先拦。

-- === canary fixture 表(OQ6:专用表,绝不与生产索引同列共存——实测
--     同列双 stannum 索引 planner 恰绑其一=错结果)。种子含 canary 文档
--     (>64B 连续 run:64B 精确块查询 bound 命中/默认回退漏召)、普通英文
--     文档、CJK 文档(kohaku 面)。 ===
CREATE TABLE v13_canary_docs (
  doc_no int PRIMARY KEY,
  body   text NOT NULL
);
INSERT INTO v13_canary_docs VALUES
 (1, repeat('z', 200)),
 (2, 'plain english document about quasars and redshift surveys'),
 (3, '東京タワーは電波塔である');

CREATE INDEX ix_v13_canary ON v13_canary_docs
  USING stannum (body) WITH (long_tokens='split', max_token_bytes=64);

-- === 生产索引(OQ6:默认配置;chunks 表唯一 stannum 索引——单索引纪律,
--     gate R 结构断言恰一;默认配置下索引丢失=性能事件非正确性事件,
--     正确性检测=EXPLAIN 形状断言 K1+verify v2 第八项) ===
CREATE INDEX ix_chunks_stannum ON chunks USING stannum (body);

-- === spans 生产者 v2(DP4 契约④:签名 (text,jsonb)→jsonb 与输出
--     [[b,e],…](字节、chunk 内、非重叠、升序)不变;消费方零改。
--     载荷约定换为 {"tinql":…}(recall 家族内部约定,外部消费者=
--     v13_assemble_spans 不调本函数,附 A #6)。实现=stannum.highlight
--     哨兵法(实测:highlight(text,begin,end,query text) IMMUTABLE,
--     多命中/tokenizer 一致含口音折叠与短语)⇒ 本函数保持 IMMUTABLE
--     (DP4 v1 同波动度)。哨兵对确定性四选一(chr(1,2)..chr(7,8) 内
--     第一对正文不含的;四对全含→RAISE 响亮,不静默错位)。字节换算:
--     tagged 内第 p 字符(其前 t 个 1 字节哨兵)在原文字节位=
--     octet_length(left(tagged,p-1))+1-t;span 末=末字符末字节。上限
--     256=确定性停止(v1 同款)。 ===
CREATE OR REPLACE FUNCTION v13_extract_spans(p_body text, p_query jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_tinql text; v_open text; v_close text; v_i int;
  v_tagged text; v_from int; v_cpos int; v_epos int;
  v_tags int := 0; v_total int := 0;
  v_bstart bigint; v_bend bigint;
  v_out jsonb := '[]'::jsonb;
BEGIN
  IF p_body IS NULL THEN RETURN '[]'::jsonb; END IF;
  IF p_query IS NULL OR jsonb_typeof(p_query) IS DISTINCT FROM 'object'
     OR jsonb_typeof(p_query->'tinql') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: stannum span query must be {"tinql":<string>}'
      USING ERRCODE = 'V3005';
  END IF;
  v_tinql := p_query->>'tinql';
  v_open := NULL;
  FOR v_i IN 1 .. 4 LOOP
    IF position(chr(v_i * 2 - 1) IN p_body) = 0
       AND position(chr(v_i * 2) IN p_body) = 0 THEN
      v_open := chr(v_i * 2 - 1); v_close := chr(v_i * 2); EXIT;
    END IF;
  END LOOP;
  IF v_open IS NULL THEN
    RAISE EXCEPTION
      'v13: body contains all highlight sentinels (spans unavailable)'
      USING ERRCODE = 'V3005';
  END IF;
  v_tagged := stannum.highlight(p_body, v_open, v_close, v_tinql);
  v_from := 1;
  LOOP
    EXIT WHEN v_total >= 256;
    v_cpos := position(v_open IN substring(v_tagged FROM v_from));
    EXIT WHEN v_cpos = 0;
    v_cpos := v_cpos + v_from - 1;
    v_epos := position(v_close IN substring(v_tagged FROM v_cpos + 1));
    EXIT WHEN v_epos = 0;
    v_epos := v_epos + v_cpos;
    v_bstart := octet_length(left(v_tagged, v_cpos)) + 1 - (v_tags + 1);
    v_bend := octet_length(left(v_tagged, v_epos - 1)) - (v_tags + 1);
    IF v_bstart >= 1 AND v_bend >= v_bstart THEN
      v_out := v_out || jsonb_build_array(jsonb_build_array(v_bstart, v_bend));
      v_total := v_total + 1;
    END IF;
    v_tags := v_tags + 2;
    v_from := v_epos + 1;
  END LOOP;
  RETURN v_out;
END $$;

-- === recall v2(§4.8 刻画完换 definition;签名冻结 (text,int)→TABLE 三列;
--     DP4 契约④同型:换 definition 消费方零改)。所有 bind 算子只经 EXECUTE
--     (不变量 2;USING 参数化——实测 bind_query($1,oid) 机制下绑定保持,
--     且 EXECUTE 每次新计划=绑定 planner 当前最优索引)。full_score(ctid)
--     实测 real∈[0,1];排序 分值 DESC, content_hash ASC 并列终裁;退役源
--     过滤⑨。boost 留缝:只接受空数组(分步 IF 求值序纪律——jsonb typeof
--     先验后再 jsonb_array_elements);非空 V3005(语法未实证,§12 台账)。 ===
CREATE OR REPLACE FUNCTION v13_recall(p_tinql text, p_k int)
RETURNS TABLE(content_hash text, bm25 numeric, spans jsonb)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_boosts jsonb;
BEGIN
  IF p_tinql IS NULL OR p_k IS NULL OR p_k < 1 OR p_k > 1024 THEN
    RAISE EXCEPTION 'v13: v13_recall args out of bounds'
      USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN; END IF;
  PERFORM v13_tinql_terms(p_tinql);   -- 自产文法守卫(fail-closed 信封)
  v_boosts := v13_policy('recall_boosts');
  IF v_boosts IS NULL
     OR jsonb_typeof(v_boosts->'boosts') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: invalid recall_boosts policy shape'
      USING ERRCODE = 'V3005';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_boosts->'boosts')) THEN
    RAISE EXCEPTION
      'v13: recall_boosts must stay empty until boost landing (§12 台账)'
      USING ERRCODE = 'V3005';
  END IF;
  RETURN QUERY EXECUTE
    'SELECT c.content_hash, '
 || 'stannum.full_score(c.ctid)::numeric AS bm25, '
 || 'v13_extract_spans(c.body, jsonb_build_object(''tinql'', $1)) '
 || 'FROM chunks c JOIN v13_sources src '
 || 'ON src.source_hash = c.source_hash AND src.superseded_by IS NULL '
 || 'WHERE c.body ==> $1 '
 || 'ORDER BY bm25 DESC, c.content_hash ASC LIMIT $2'
    USING p_tinql, p_k;   -- ORDER BY 输出列别名:单次求值(v1 的 ORDER BY 2 同
                          -- 款;full_score 虽 IMMUTABLE,别名引用免双算)
END $$;

-- === recall_count v2(OQ4 附则:count 人口与 recall 人口同引擎——
--     tsv count 对 CJK≈0 而 bind 算子命中>0,k 自适应会失效;实测 count 走
--     索引且 fold 后精确)。同上:EXECUTE+USING+退役源过滤。 ===
CREATE OR REPLACE FUNCTION v13_recall_count(p_tinql text) RETURNS bigint
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_cnt bigint;
BEGIN
  IF p_tinql IS NULL THEN
    RAISE EXCEPTION 'v13: tinql must not be NULL' USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN 0; END IF;
  PERFORM v13_tinql_terms(p_tinql);
  EXECUTE 'SELECT count(*) FROM chunks c '
       || 'JOIN v13_sources src ON src.source_hash = c.source_hash '
       || 'AND src.superseded_by IS NULL '
       || 'WHERE c.body ==> $1'
    INTO v_cnt USING p_tinql;
  RETURN v_cnt;
END $$;

-- === verify v2(DP4 契约②/E5:version 1→2,七项逐字保留+第八项
--     stannum.verify_index;pg_cron 夜跑 job 零新增——DP4 job 调本函数,
--     自动获得 stannum 面)。第八项 severity 词表 0.1.0 干净样本=0 行,
--     按 error/warning 计红(词表实证=实施期冒烟项,附 B)。 ===
CREATE OR REPLACE FUNCTION v13_verify_chunks(p_raise boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_bad_selfcert bigint; v_bad_orphan bigint; v_bad_source bigint;
  v_bad_ref bigint; v_plan text := ''; v_pending int; v_meta boolean;
  v_bad_backref bigint; v_orphan bigint; v_guc text;
  v_stan_bad bigint;
  v_checks jsonb := '[]'::jsonb; v_all_ok boolean;
  v_line record;
BEGIN
  SELECT count(*) INTO v_bad_selfcert FROM chunks
   WHERE content_hash IS DISTINCT FROM v13_body_hash(body);
  SELECT count(*) INTO v_bad_orphan FROM chunks c
   WHERE NOT EXISTS (SELECT 1 FROM artifacts a
                      WHERE a.content_hash = c.content_hash
                        AND a.kind = 'chunk');
  SELECT count(*) INTO v_bad_source FROM chunks c
   WHERE NOT EXISTS (SELECT 1 FROM v13_sources s
                      WHERE s.source_hash = c.source_hash);
  SELECT count(*) INTO v_bad_ref FROM artifacts a
   CROSS JOIN LATERAL jsonb_array_elements(
        coalesce(a.inline->'query_side'->'candidates', '[]'::jsonb)) cand
   WHERE a.kind = 'context'
     AND EXISTS (SELECT 1 FROM artifacts x
                  WHERE x.content_hash = cand->>'content_hash'
                    AND x.kind = 'chunk')
     AND NOT EXISTS (SELECT 1 FROM chunks c
                      WHERE c.content_hash = cand->>'content_hash');
  SELECT count(*) INTO v_bad_backref FROM artifacts a
   WHERE a.kind = 'chunk'
     AND NOT EXISTS (SELECT 1 FROM chunks c
                      WHERE c.content_hash = a.content_hash)
     AND v13_chunk_referenced(a.content_hash);
  SELECT count(*) INTO v_orphan FROM artifacts a
   WHERE a.kind = 'chunk'
     AND NOT EXISTS (SELECT 1 FROM chunks c
                      WHERE c.content_hash = a.content_hash);
  v_guc := current_setting('enable_seqscan');
  BEGIN
    PERFORM set_config('enable_seqscan', 'off', false);
    FOR v_line IN EXECUTE
      'EXPLAIN (COSTS OFF) SELECT 1 FROM chunks WHERE body_tsv @@
         websearch_to_tsquery(''english''::regconfig, ''quasar'')' LOOP
      v_plan := v_plan || v_line."QUERY PLAN";
    END LOOP;
  EXCEPTION
    WHEN query_canceled THEN
      PERFORM set_config('enable_seqscan', v_guc, false);
      RAISE;
    WHEN OTHERS THEN
      PERFORM set_config('enable_seqscan', v_guc, false);
      RAISE;
  END;
  PERFORM set_config('enable_seqscan', v_guc, false);
  v_pending := gin_clean_pending_list('public.ix_chunks_tsv'::regclass);
  SELECT EXISTS (SELECT 1 FROM v13_chunks_meta WHERE singleton)
    INTO v_meta;
  SELECT count(*) INTO v_stan_bad                       -- ⑧ stannum(DP5)
    FROM stannum.verify_index('ix_chunks_stannum'::regclass, true)
   WHERE severity IN ('error', 'warning');
  v_checks := jsonb_build_array(
    jsonb_build_object('name','self_cert','ok', v_bad_selfcert = 0,
      'detail', jsonb_build_object('violations', v_bad_selfcert)),
    jsonb_build_object('name','artifact_exists','ok', v_bad_orphan = 0,
      'detail', jsonb_build_object('violations', v_bad_orphan)),
    jsonb_build_object('name','source_ledger','ok', v_bad_source = 0,
      'detail', jsonb_build_object('violations', v_bad_source)),
    jsonb_build_object('name','reference_resolvable','ok', v_bad_ref = 0,
      'detail', jsonb_build_object('violations', v_bad_ref)),
    jsonb_build_object('name','index_usable',
      'ok', position('ix_chunks_tsv' in v_plan) > 0,
      'detail', jsonb_build_object('pending_flushed', v_pending)),
    jsonb_build_object('name','meta_present', 'ok', v_meta,
      'detail', jsonb_build_object('generation',
        (SELECT generation FROM v13_chunks_meta WHERE singleton))),
    jsonb_build_object('name','artifact_backref', 'ok', v_bad_backref = 0,
      'detail', jsonb_build_object('referenced_orphans', v_bad_backref,
                                   'orphan_artifacts_report', v_orphan)),
    jsonb_build_object('name','stannum_verify_index', 'ok', v_stan_bad = 0,
      'detail', jsonb_build_object('index', 'ix_chunks_stannum',
                                   'findings', v_stan_bad)));
  v_all_ok := NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_checks) c
                           WHERE NOT (c->>'ok')::boolean);
  IF p_raise AND NOT v_all_ok THEN
    RAISE EXCEPTION 'v13: verify_chunks failed: %', v_checks
      USING ERRCODE = 'V3004';
  END IF;
  RETURN jsonb_build_object('version', 2, 'checks', v_checks,
                            'all_ok', v_all_ok);
END $$;
-- 注:本函数是 DP4 v1 的逐字复制+两处增量(DECLARE v_stan_bad/⑧ 计数与
-- 检查行/version 1→2);既有 RAISE 保持 V3004(DP4 码面,不变量 10 例外)。
-- 零 ACL 增量:全部 OR REPLACE 保留既有 ACL;canary 表 owner-only 默认
-- (刻画 fixture 面,运行角色零授权——gate R 负向)。

COMMIT;
```

### 3.3 stage 四件与 load.py

照 DP3/DP4 §3.8 形制,两 stage 各四件:

- `v13/recall/`:SQL=§3.1 全文;`setup_db.py`(DROP-CREATE 库 `agent_v13_recall`;`files_through('recall')` 加载八文件;超级用户连接,策略 INSERT 前置同 DP2–DP4);`test_recall.py`(§4 A–J 组);`README.md`(运维纪律,§4 末清单)。
- `v13/characterize/`:SQL=§3.2 全文;`setup_db.py`(**硬前置探针**:`SELECT 1 FROM pg_available_extensions WHERE name='stannum'`,失败打印回退指引并退出非 0——fail-closed,呼应文件头无降级纪律;然后 DROP-CREATE 库 `agent_v13_characterize`,`files_through('characterize')` 九文件);`test_characterize.py`(§4 K–R 组);`README.md`(stannum runbook 六件+刻画数据答案载体)。
- `v13/load.py`:SQL_LOAD_ORDER 追加 `'recall/v13_recall.sql'`(第 8)与 `'characterize/v13_characterize.sql'`(第 9);`STAGE_THROUGH["recall"] = 8`、`STAGE_THROUGH["characterize"] = 9`。零改动既有行。

---

## 4. 里程碑与 gate

两里程碑两 stage:命令形态 `uv run python v13/recall/test_recall.py` / `uv run python v13/characterize/test_characterize.py`,退出码 0=通过。**提交前全部前序 stage gate 复跑**(各自库前缀切片不加载本两文件,防回归的结构性保证;AGENTS 前置条件 1):里程碑 1 前跑 DP1 四 stage+DP2+DP3+DP4;里程碑 2 前另跑 recall stage。

**断言纪律(DP1–4 原样沿用)**:fixture 走真实链路——语料经 DP4 驱动器四步摄取(库外读文件→enqueue tool effect→claim→complete→同事务 ingest)、事件经 v13_append_event、parse/advance 经 DP1 真实函数、manifest 经 DP3 refresh settle 真实链路(context_refresh effect→claim→v13_refresh_context);owner 直插仅限「负向/守卫」类 fixture(两侧都测)。三禁演示对象(gate 自建视图/静态函数/预备语句)是 **gate fixture**,测后 DROP——生产面源码扫描独立断言零 `==>`(归一化口径,见下)。**源码扫描归一化口径(G1/G2/R2 三处一致)**:扫描前先剥注释——`--` 行注释(至行尾)与 `/* */` 块注释(PostgreSQL 嵌套语义);字符串字面量(`'…'` 与 `$tag$…$tag$`/`$$…$$`)内的 `--`/`/*` 不当注释剥(串是执法面:R2 的 `==>` 计数就落在 EXECUTE 字符串字面量上)——再对归一化文本计数/匹配。执法面=代码+字符串字面量;注释散文不是依赖面(DP4 冻结注释行 338/902 的裸 "stannum" 一词因此不命中)。归一化器行为由对照 fixture 自证(G1 定义,R2 复跑)。

### G-ctx3 原文映射(§10 逐条)

| §10 G-ctx3 原文 | 断言落点 |
|---|---|
| `==>` 绑定矩阵(EXECUTE/视图/预备语句)全绿 | K1–K5(EXECUTE 恒绿+EXPLAIN 形状;视图/静态/预备三禁 fixture 演示+源码扫描执法;0.1.0 实测注记附 A #1) |
| tokenizer canary | K6/L(canary 专用表+split 索引;EXECUTE 命中/默认回退漏召=回落即红的行为半边) |
| TINQL 注入被拒(fail-closed 信封) | A 组注入族+G2(构造性免疫负向) |
| count 自适应 k 生效 | C 组+J 组(公式/边界/k_max 硬上限) |

### A 组 · TINQL 构造器(§4.6;纯函数直调)

| # | 断言 | 对应 |
|---|---|---|
| A1 | 空输入(NULL/''/纯空白)→segments='[]'、build_tinql=''(合法空,零候选;不 RAISE) | OQ7 |
| A2 | 英文多词:'how do quasars form' → '"how" AND "do" AND "quasars" AND "form"'(逐词引号,AND 连接——形状恰等断言) | OQ7 |
| A3 | kohaku 混合:'東京タワーの高さ quasar' → '"東京タワーの高さ" AND "quasar"'(CJK 连续段=整体一个引号短语;助詞「の」属 CJK 码区并入段) | §4.6 短语引用 |
| A4 | 往返:v13_tinql_terms(v13_build_tinql(q)) 与 v13_query_segments(q) 逐字节相等(多 fixture 含混合/CJK-only/重复词;**发射串的 stannum 语法接受性=P1/P4 经实索引覆盖**——第 8 位无 stannum,本组只证文法封闭) | OQ7 |
| A5 | 注入族负向(全部不 RAISE、输出形状封闭):'x" OR 1=1 --' → 引号剥离后纯词形态;'a AND b' 字面 → 两段(引号免疫关键字);'a*b /re/ ~fuzzy' → 操作符字符全成分隔词;断言各 fixture 输出恰等预期串(构造性免疫的逐字证据) | G-ctx3 注入/OQ7 |
| A6 | 上限族负向(V3005):4097 字节查询;257 字节单语段(无分隔连续);65 段;回析器异形输入(裸词/'"a" OR "b"'/未闭合引号/段内引号/NULL)各 V3005 | §4.1 全限 |
| A7 | 确定性:同输入三连调字节等;操作符字符集抽查(引号/括号/斜杠/波浪号/脱字符/<>等)在输出零出现(全 fixture 聚合断言) | 不变量 6 |

### B 组 · recall v1(T0 tsvector;§7)

| # | 断言 | 对应 |
|---|---|---|
| B1 | 英文语料(驱动器四步摄取≥3 文档)查询命中集恰等预期(对照 SQL 直查 body_tsv@@phraseto);content_hash 全 64hex;spans=[[s,e],…] 字节升序非重叠(octet_length(left(body,s-1))+1 对照=DP4 C1a 同源) | §4.1/DP4 契约④输出形态 |
| B2 | 排序确定性:构造并列 fixture(两 chunk 同 ts_rank、异 body——词序置换对即得:'quasar alpha' vs 'alpha quasar',ts_rank 词频/权重型与词序无关而 body_hash 异)→ 输出序 bm25 DESC,content_hash ASC;双跑字节等;LIMIT 截断在并列处由 content_hash 终裁 | §4.1 并列截断 |
| B3 | CJK 边界钉(不修):'京'子串查询在 tsv 路径零命中(逐字不可达——设计 §7/§4.8 既裁 CJK 走 stannum;DP4 F2 同款边界);整 run 查询(「東京タワー」)按 english parser 语义如实断言(可命中含该整 token 的 chunk) | §7 T0 诚实边界 |
| B4 | 退役源过滤⑨:supersede 场景(DP4 B5 同链路)后,旧源独有关键词查询零返回(信封 candidates/manifest candidates 同断言) | DP4 契约⑨/B5b 读侧 |
| B5 | 负向:recall(NULL,8)/('',8)/(t,0)/(t,1025)/tinql_terms 非自产文法先拒 → V3005;count('')=0 | fail-closed |
| B6 | corpus 不串:两 corpus 语料各自查询命中不越界(F4 隔离面的 recall 侧;查询词唯一化 fixture) | §4.4 前半 |

### C 组 · count 自适应 k(§4.6/G-ctx3)

| # | 断言 | 对应 |
|---|---|---|
| C1 | 小语料(匹配 3):v13_recall_candidates→k=k_base(8)、matched=3 | OQ5 公式 |
| C2 | 放宽:灌 400 匹配文档(widen_ratio=0.05→ceil(400×0.05)=20)→ k=20;候选数恰 20、序=分值序 | §4.6 |
| C3 | 硬上限:灌 4000 匹配(×0.05=200)→ k=k_max=64 截断(J 组一页账的 gate 面) | F5② |
| C4 | 策略翻版生效(DP1 #3 仪式:新版本行 k_max=16+同事务翻 active,测后回滚)→ k≤16;负向形状族(k_base 字符串/k_max<k_base/缺 timeout_ms/widen_ratio 负数)→ V3005 | OQ5 fail-closed |

### D 组 · 信封换体(OQ3)

| # | 断言 | 对应 |
|---|---|---|
| D1 | 20 键恰等:19 既有键键集不删不改(逐键枚举;M2-9 包含性);表达式层面=17 键与 DP2/DP3 形态逐字一致+goal_hash=v13_goal_hash 同源(DP3 形态)+candidate_set_hash 为 OQ3 扩集材料;新键 candidates 形态见 D3 | DP2 #8/墓碑 |
| D2 | csh 材料扩集:同 needed、异语料(摄取前后两 parse)→ csh 不等;同语料同 goal 两 parse → csh 相等 | 契约 #1 |
| D3 | candidates 冻结形态:[{content_hash,bm25,spans}] 三键数组、序=分值序;parse 后语料变更→旧信封 candidates 不变(冻结语义;新 parse 才换) | OQ3/DP6 消费面 |
| D4 | 空 goal(无 user/message)→ candidates=[]、k=0、csh 材料 recall 分量确定;解析相不炸 | OQ3 合法空 |
| D5 | 信封零 TINQL 串(源断言:envelope 输出全文不含 build_tinql 产物特征——引号 AND 形态;附 A #5) | DP3 同型 |

### E 组 · 装配换体+manifest(契约 #9)

| # | 断言 | 对应 |
|---|---|---|
| E1 | refresh settle 真实链路(context_refresh effect→claim→v13_refresh_context)→ manifest.query_side.candidates=召回集(非 goal echo);四键恰等{content_hash,bm25,spans,decision_id};decision_id 全 NULL;V3003 校验器过(settle 内已执法+直调复核) | DP3 契约/校验器层 6 |
| E2 | 数组序:聚合内显式 ORDER BY——构造分值并列 fixture→manifest candidates 序稳定(content_hash 终裁);双跑 manifest 字节等(确定性) | 不变量 5/G-ctx5 同型 |
| E3 | judgments 仍 [](decision_id NULL 被消费集谓词滤出);manifest 全文零 TINQL;bm25=numeric(v1=ts_rank 值域) | 契约 #9 |
| E4 | recompute 语义:摄取新文档→② 检出(corpus 键)→refresh→新 manifest candidates 含新文档;exact replay(v13_replay 旧 artifact)候选原字节不变(冻结) | DP3 OQ5/DP4 G2 复测 |
| E5 | 空候选(goal 文本无分段)→ candidates=[]、manifest 仍合法(校验器过) | 边界 |

### F 组 · cgr 语料接线(DP1 #59;OQ1)

| # | 断言 | 对应 |
|---|---|---|
| F1 | 双计数同步:摄取一批(驱动器)→ v13_chunks_meta.generation+1 且 v13_tools_meta.candidate_generation_revision+1(相对比较——加载期 bump 不计入,DP1 M2-14 同型);owner 直插 chunks 行(带 artifact 的合法 fixture)亦双 bump(语句级触发器任何路径) | OQ1 |
| F2 | 弃批重解析:parse→E1(记 cgr=g1)→摄取(提交)→advance(E1)→'stale';重 parse→E2→advance 直通;无摄取窗口 advance 直通(基线) | #59/无漏报 |
| F3 | manifest freshness 复测:DP4 G2 同型(摄取→② 不新鲜→settle→新 active;无变更再查 fresh=true 恰一次)——九键 token 下的复跑 | DP4 G2/键集变化 |
| F4 | 回归面:tools 目录变更照旧 bump revision(既有 DP1 面不受换体影响);needed 体 CREATE OR REPLACE(测试内换体+还原)照旧 bump cgr(DP1 分支 2 存活) | 契约 #3 |
| F5 | 锁面:摄取事务(持 meta/tools_meta 行锁未提交)∥另一连接 advance 步 0 probe 读 v13_tools_meta 不阻塞(pg_locks/MVCC 断言);∥settle 只短阻塞不死锁(双连接 fixture,statement_timeout 内完成) | OQ1 锁论证 |

### G 组 · 三禁源码+引擎无关性(§4.1/§4.8)

| # | 断言 | 对应 |
|---|---|---|
| G1 | 源码扫描(归一化):SQL_LOAD_ORDER 前 8 号文件按归一化口径(剥 `--` 行注释与 `/* */` 块注释后扫描;公共口径见 §4 断言纪律)断言零 `==>` 字样、零 `stannum.` schema 限定引用(第 8 位=tsvector T0,承重件不依赖 stannum 的字面兑现;散文注释里的裸 "stannum" 一词——含 DP1–4 冻结注释——不是依赖面,故 stannum 半边按限定名执法)。归一化器自证 fixture(gate 内建对照文件,只扫描不执行):`-- c==>y stannum.` 行注释与 `/* b==>y stannum. */` 块注释归一化后零残留;正文 `x ==> y` 计数;同行 `SELECT concat('-- nc', (p ==> q));` 断言串内 `--` 不误剥(误剥则该行 `==>` 丢失即红);`stannum.highlight(z)` 计数——归一化后恰 `==>`=2、`stannum.`=1 | 不变量 7 |
| G2 | 注入构造性:第 8 号文件(归一化口径同 G1)零**动态执行形态**——正则钉 `EXECUTE` 后随(可跨空白)字符串字面量起始:`'` 或 `$` 定界(涵盖 `RETURN QUERY EXECUTE`/`EXECUTE … INTO`)——静态 ACL 的 `REVOKE/GRANT EXECUTE ON` 后随 ` ON` 天然不命中(动态 SQL 全在第 9 位:recall v2/count v2 全 USING 参数化,形态归 R2;verify v2 的 `FOR … IN EXECUTE` 常量串继承 DP4 v1 逐字,无参数面);用户文本零进动态串(EXECUTE 串全静态骨架 ‖ 拼接,附 B 机械猎) | §4.1 |
| G3 | 三禁 README 纪律在场(纪律文本条目断言);worker 预备语句面=v13 worker 契约文档引用(零 worker SQL 在库) | §4.1 三禁 |

### H 组 · ACL(不变量 10/DP1 双登录)

| # | 断言 | 对应 |
|---|---|---|
| H1 | SET ROLE v13_recall:EXECUTE 六新函数 ok;SELECT chunks/v13_sources/v13_chunks_meta ok(DP4 既有);INSERT/UPDATE chunks 拒(DP4 既有回归) | §1.2 #5 |
| H2 | SET ROLE v13_resolve:EXECUTE v13_recall_candidates/envelope 链 ok;SELECT chunks 三表 ok(本 plan 新授);INSERT/UPDATE chunks 拒 | §1.2 #5 |
| H3 | SET ROLE v13_route:同 H2 形态(route 侧装配直调面);PUBLIC 负向:未 SET ROLE 直调六新函数权限拒 | 不变量 10 |
| H4 | token 九键:SET ROLE 下 v13_context_required 键集恰等 {sem,dec,goal,tools_rev,asm_ver,jdef_ver,gen_ver,corpus,recall_ver}(对照 fixture) | OQ8 |

### I 组 · 加载边界+freshness(OQ8)

| # | 断言 | 对应 |
|---|---|---|
| I1 | 前缀切片:DP4 库(files 1–7)token 仍八键、无 recall 函数(files_through 结构断言);DP1–4 gate 复跑互证 | 契约 #6 |
| I2 | 键集八→九恰一次 refresh:加载后首个 ② 必不新鲜(八键 active token 失配)→settle 一次→此后无变更 fresh=true(不活锁) | DP3 OQ1 |
| I3 | recall_ver 追动:recall_k 翻版本行(k_max 16,C4 的 fixture 复用)→ ② 检出→refresh→manifest candidates 截断变化(≤16);回滚后复原 | OQ8 漏键反证 |
| I4 | 缺行 RAISE:删 recall_k 活动行(后恢复)→ token RAISE 'no active recall_k policy'(与 asm_ver 同姿势;九键体增量断言) | OQ8/DP4 G4 同型 |

### J 组 · k 硬上限+延迟账(F5②)

| # | 断言 | 对应 |
|---|---|---|
| J1 | C3 场景数字呈报:matched=4000/k 恒 64 断言(硬上限拦 widen——F5「k≈2000 十几轮」悬崖不可达的结构证明) | F5② |
| J2 | README 一页账在场(条目断言:k→批数→快/慢路往返→量级四行表;k_base 8=1 批全快路/k_max 64=2 批 1 往返/128 越界形态仅示意);放宽 k_max=DP7 裁量注记 | F5②/F5③→DP7 |

### K 组 · 绑定矩阵(G-ctx3 第一断言;§4.8;实测面=OQ9)

| # | 断言 | 对应 |
|---|---|---|
| K1 | EXPLAIN 形状:EXPLAIN (FORMAT JSON) 召回查询(会话局部 enable_seqscan=off+事后恢复,DP4 verify ⑤ 同方案)→ 节点 Node Type='Custom Scan' ∧ Custom Plan Provider='Stannum Text Search Scan' ∧ Index='ix_chunks_stannum';chunks 无 Seq Scan(设计字面「stannum IndexScan」的 0.1.0 实测形态=Custom Scan,附 A #1;**形态词钉死 0.1.0 实测——stannum 升级若改节点形态,断言随 README⑨ 升级复测重钉,不做 OR 宽化**[宽化会把绑定退化漏检成绿]) | §4.1 钉形状 |
| K2 | EXECUTE 恒绿:v13_recall(v2 已载)对生产 fixture 与 canary 表 fixture 全命中;8 连调+REINDEX 后再调(rebind;附 B 实测先例) | §4.8 矩阵 |
| K3 | 无索引回落红:零 stannum 索引的临时表上,canary 查询(64B 精确块)经 text==>text 默认 comparator 漏召(直调 stannum_text_cmpfunc 断言 f;对照 bound 命中 t)——回落语义分叉的实测证据 | OQ9 降级面① |
| K4 | 同列双索引歧义红:canary 表加第二 stannum 索引(默认配置)→ canary 查询 planner 恰绑其一(EXPLAIN 显示单 Index)→ 结果=被绑索引语义(错面);测后 DROP 还原;立法面=生产列恰一(gate R1) | OQ9 降级面②/OQ6 |
| K5 | 三禁 fixture 演示(gate 自建测后 DROP):视图内嵌 ==>(CREATE VIEW)/plpgsql 静态 ==>(参数化函数,8 连调含 force_generic_plan 会话)/预备语句(PREPARE+8×EXECUTE 同会话)——**0.1.0 实测:三路径 canary 均命中(绑定保持)**,断言改为「三路径结果与 EXECUTE 一致性+EXPLAIN 计划形态记录」;**实测等价≠禁令撤销**(作用力 1 审计理由+冻结纪律;实施期 stannum 升级复测项,附 A #1) | §4.1 三禁/OQ9 |

### L 组 · tokenizer canary(G-ctx3 第二断言)

| # | 断言 | 对应 |
|---|---|---|
| L1 | canary 命中:canary 表 EXECUTE 形态查询 64B 精确块(repeat('z',64))→ 命中 doc 1;EXPLAIN 绑 ix_v13_canary | §4.1 canary |
| L2 | 回落即红:同一查询经默认 comparator(stannum_text_cmpfunc 直调)→ f(漏召)——「索引 tokenizer 与默认切分不同的 fixture,召回必须命中,回落即红」的行为半边 | §4.1 |
| L3 | CJK 切分实证:unicode 默认(生产索引)下「東京タワー」短语查询命中 CJK 文档;单字 Katakana「タ」miss(连跑成单 token 的 0.1.0 物理边界钉断言,README 记) | OQ6/附 B |

### M 组 · fold 持锁 p99 压测(§4.8/ch10.3)

| # | 断言 | 对应 |
|---|---|---|
| M1 | 基线 vs fold:**前置=stannum.segment_info 观测确认 mutable 段在场且增长(折叠活动面已激活——fold 阈值 0.1.0 未文档化,以观测为准,未激活则加灌直至激活并记数字)**;然后 canary 表基线 INSERT×500 计时 p99 与 fold 活跃期再×500 → p99 对比+数字呈报;宽松守门(p99_fold ≤ p99_base×10 或绝对 <200ms 取大——记运维注记非硬红线,超界红=真病变) | ch10.3「记运维注记」 |
| M2 | segment_info 观测:段结构含 immutable+mutable、generation 随插入递增(数字呈报);verify_index 前后绿 | 附 B 实测 |
| M3 | count 精确性:fold 后 count(*)==插入数(实测 51/51 复验) | §4.6 |

### N 组 · verify_index+REINDEX 演练(§4.8/§8;DP4 契约②)

| # | 断言 | 对应 |
|---|---|---|
| N1 | verify_index 直调:ix_chunks_stannum 与 ix_v13_canary 各零 error/warning 行;severity 词表观测记档(干净样本=0 行) | §8 |
| N2 | REINDEX 演练:REINDEX 两索引→K2 canary/生产 fixture 复命中→N1 复绿(索引可丢可重建;基础行=chunks/artifacts 不动) | §8 runbook |
| N3 | verify v2:version=2;八项 {name,ok} 全 true、all_ok=true;第八项 detail={index:'ix_chunks_stannum',findings:0};负向:制造 tsv 面破损(删无引用 chunks 行)→ 对应项红+p_raise V3004(既有面回归) | DP4 契约②/E5 |
| N4 | cron 零新增:cron.job 恰一条 v13-verify-chunks(DP4 既有;job 调 v13_verify_chunks(true) 自动升 v2 面——调度是行的红利);pg_cron 不可用分支照 DP4 G6 | §8 |

### O 组 · >1024 展开回落(§4.8/作用力 6)

| # | 断言 | 对应 |
|---|---|---|
| O1 | 编译器面:65 段已拒(A6);构造 1000+ 段用户输入 → V3005(用户面不可达引擎展开路径) | §4.1 展开上限 |
| O2 | 引擎面直测(fixture 直发,绕过 build_tinql):1030 词项 AND 形态 TINQL 经 EXECUTE 于 canary/生产表 → 返回正确(保守回查无错)、无静默漏召(命中集=对照直查)、时延数量级记录;行为钉断言(0.1.0:成功返回) | §4.8 钉断言 |

### P 组 · stannum v2 全链(§7 T0 换 definition;流程零改)

| # | 断言 | 对应 |
|---|---|---|
| P1 | G-ctx3 全量复跑于 v2:B1/B2/E 组等价物(命中集/排序/并列/manifest/信封)全绿——**换 definition 流程零改的字面兑现**(目录行是数据的库形态) | §4.8/ch10.3 |
| P2 | bm25=full_score:值域 [0,1] 实数、列类型 numeric 同 v1;排序 tie 由 content_hash 终裁 | OQ4 |
| P3 | spans v2:highlight 哨兵产出的 [[s,e],…] 与人工标注 fixture 对照(字节/升序/非重叠);v1 形态兼容(消费方 v13_assemble_spans 直调 v2 输出零改——DP4 F 组复跑同款);哨兵冲突负向(正文预埋 chr(1..8) 全对的 fixture→V3005 响亮) | DP4 契约④ |
| P4 | CJK:kohaku 混合语料(摄取)「東京タワー」短语命中(CJK 救命件实证——v1 零召回对照);单字 Katakana 边界(L3 同型);count v2 对 CJK>0 且 k 自适应生效(v1 count≈0 反差断言) | §4.6/OQ4 附则 |
| P5 | boosts 留缝:空数组 recall 输出与非 boost 调用字节等(构造性 no-op);recall_boosts 种子行在场;负向:填非空数组→V3005;版本不入 token(键集仍九键) | §9/OQ8 |
| P6 | 退役源过滤⑨在 v2:B4 等价物(EXECUTE 串内 JOIN 过滤);cgr 接线在 v2 库复测(F 组抽样) | 契约⑨ |

### Q 组 · 尺寸刻画面(§4.7/DP4 契约③)

| # | 断言 | 对应 |
|---|---|---|
| Q1 | 数据表产出:6 档尺寸(512B/1K/2K/4K/8K/16K)×各 20 文档(查询词埋中段,驱动器摄取)→ 每档命中数/bm25 均值/目标词排序位置表(gate 打印+README 数据答案载体) | §4.7 数据回答 |
| Q2 | 结论载体:README 记数据答案+翻版流程(数据支持≠3072 时:chunks_ingest 新版本行+rebuild 的 ops 流程;**不自动翻策略**);target_bytes 参数与 3072 先验仍在 DP4 策略行(本 DP 只交数据) | DP4 契约③ |

### R 组 · 结构断言+源码+收口(不变量 7/8)

| # | 断言 | 对应 |
|---|---|---|
| R1 | 单索引结构:chunks 表 stannum 索引恰一(pg_index/pg_am 计数断言);canary 表恰一;两表不同表 | OQ6 |
| R2 | 源码扫描(归一化,口径同 G1——剥 `--` 行注释与 `/* */` 块注释后扫描):前 9 号文件逐文件计数断言——`==>`:1–8 号零、9 号恰 2(恰=v13_recall v2 与 v13_recall_count v2 两条 EXECUTE 字符串字面量,别处零);`stannum.` 限定名:1–8 号零、9 号恰 3(extract v2 的 stannum.highlight 调用/recall v2 串内 stannum.full_score/verify v2 的 stannum.verify_index 调用)。belt:两份 DP5 文件原始(未归一化)计数同断言——8 号 `==>` 与 `stannum.` 均零、9 号 `==>` 恰 2(两文件注释字样已散文化);1–7 号只走归一化口径(DP4 冻结注释含裸 "stannum" 词,不可改)。归一化器自证 fixture 同 G1 复跑 | 不变量 2/7 |
| R3 | canary 表 ACL:SET ROLE v13_recall/resolve/route → SELECT v13_canary_docs 拒(owner-only 刻画面) | §3.2 注 |
| R4 | runbook 收口:characterize README 六件条目在场断言(索引可丢基础行不可丢/连接池预热[新连接 buffer 重建税]/fold 毛刺[M1 数字引用]/升级[stannum 版本变更复测 K3/K5]/REINDEX 演练[N2 命令]/AGPL 分发审查);K–Q 全绿=刻画通过(判定行) | §8/F4 |
| R5 | 定义后回归:characterize 库上 DP1 四 stage+DP2+DP3+DP4+recall 各 gate 全部复跑(前缀切片库互证+第 9 位库上 recall gate 复跑=换体后流程零改的行为总证明) | Done when |

**收尾工件(AGENTS.md,两里程碑各一次)**:SQL 追加进 v13/load.py(第 8/9 位);两 stage README 更新;一里程碑一提交(`v13: <祈使句摘要>`,按路径 add)。`v13/recall/README.md` 必记:①k 策略形状/公式/k_max 硬上限与一页账(F5② 表)/放宽流程(DP7 裁量);②驱动契约:parse 驱动 SET statement_timeout≤recall_k.timeout_ms(#60 引擎事实;超时=query_canceled→解析事务失败→幂等重推,零静默回落);③三禁纪律文本(视图/静态/预备;worker 预备语句面=worker 契约文档);④T0 边界(CJK 子串零召回走第 9 位;变音字母分隔符边界;ts_rank 非 BM25 诚实注记);⑤注入免疫构造性论证(输出语法封闭);⑥ACL 面(三角色+resolve/route SELECT 新授的依据)。`v13/characterize/README.md` 必记:①runbook 六件(R4 清单+命令);②tokenizer canary 机制(split 索引 64B 块/默认回退最宽配置/索引丢失=性能事件论证明);③同列双索引禁令与 bigram 独立列路径;④fold 毛刺数字(M1)与连接池预热;⑤verify v2 第八项与 cron 零新增;⑥>1024 回落行为与编译器上限双层;⑦尺寸刻画面数据答案(Q1 表)与翻版流程;⑧AGPL 分发审查触发条件;⑨0.1.0 实测记录索引(附 A #1/K5 的等价性注记与升级复测项)。

**F5② 一页账(README/gate J2 载体)**:

| k | per-chunk 批数 ⌈k/32⌉(DP6 起) | 快路批 | 慢路批(effect 往返) | 量级(实测 1.3–1.6s/批) |
|---|---|---|---|---|
| 8(k_base) | 1 | 1 | 0 | 快路内,零往返 |
| 32 | 1 | 1 | 0 | 同上 |
| **64(k_max)** | 2 | 1 | 1 | ≈1 往返 |
| 128(越界形态,仅示意) | 4 | 1 | 3 | ≈3 往返 |

结论:首版 k_max=64 把 F5 的「k≈2000→十几轮」悬崖结构性封死;DP5 面零判断调用(召回是纯 SQL,费用账自 DP6 per-chunk 起);放宽 k_max=DP7 裁量(须重开此表+F5③ tier 快路超批裁决);解析相 per-session/每日判断花费闸(F5①)归 DP7 立法。

---

## 5. 风险与回退

| # | 风险 | 缓解/接受面 |
|---|---|---|
| 1 | **stannum 0.1.0 与设计作用力 2 的分歧**(generic plan 不回落;实测 K5 三禁路径等价)——未来版本行为回归设计描述时,gate K3/K5 断言面失效 | 三禁保留为冻结纪律(审计理由不变);附 A #1 呈报;README 升级复测项(stannum 版本变更→重跑 K 组);断言写成「实测记录+一致性」而非假行为 |
| 2 | 同列双 stannum 索引歧义(实测错绑错结果) | 单索引纪律(R1 结构断言);canary 专用表;bigram 未来独立列(§4.6 原文);运维 README 禁令 |
| 3 | full_score 跨事务漂移(BM25 统计随语料/fold 漂移——作用力 1 既知) | 排序并列 content_hash 终裁;审计以 manifest 固化为准(候选快照进 artifact);gate E4 exact replay 字节不变;README 记「同查询异时刻分值可漂移是设计已知,不是缺陷」 |
| 4 | stannum 不可用(非 pgembed 环境/未打包) | 第 8 位 stage 无 stannum 可全绿(承重件);第 9 位 fail-closed 响亮失败(setup 前置探针);生产回退=停用第 9 位(留 T0 tsvector——英文语料正确性完整,CJK 语料不可用即不可用,诚实边界) |
| 5 | highlight 哨兵与正文控制字符冲突 | 四对哨兵确定性选择;全冲突→V3005 响亮(正文含 chr(1..8) 全对的病态 chunk;摄取面不拦——DP4 零改动,接受面=响亮失败+README 记);P3 负向 |
| 6 | envelope 20 键/九键 token 的既有断言回归 | DP1–4 gate 在前缀库跑(结构性零影响);D1/H4/I1 断言新形态;DP2 M2-9 包含性语义(追加合法)在 D1 复测 |
| 7 | recall_k 缺行/畸形致 refresh 全域炸(九键 RAISE) | 种子即装载;fail-closed 是特性(与 asm_ver 同姿势);I4 断言;README ops 纪律(翻版=新行+翻 active,禁删 active 行) |
| 8 | count 双扫描成本(count+top-k 两遍索引) | k_max=64 封顶;数量级记 README;超标台账(count 近似——设计要求精确 count,不进首版) |
| 9 | 编译器变音字母边界(é=分隔符)切窄召回 | 语料英文为主的 T0 假设;README 记;变音语料真实出现时评估扩类(台账族) |
| 10 | Katakana 连跑单字 miss(0.1.0 物理) | 短语引用免疫主体;边界钉断言(L3/P4);bigram 台账可解;README |
| 11 | 双 stage 并行开发的 DP6 消费漂移 | §1.4 DP6 行:签名冻结+信封 candidates 键契约+第 8 位形态为消费面(definition 无关) |
| 12 | 引擎行为依赖清单(stannum 面):bind_query 参数化绑定/Custom Scan JSON 键名/highlight 多命中与口音折叠/verify_index severity 词表/count 走索引/fold 后精确/reloptions 词表 | **全部已于本轮探针库实测**(附 B);实施期复测项仅 severity 词表(干净样本外)与 K5 升级复测;stannum 函数 schema 限定名已实测(`stannum.` 前缀) |

---

## 6. 教程映射(§13;正文零改动)

| 章 | 教程承诺(实测行号) | 本 DP 兑现 |
|---|---|---|
| 10.1 | 拆解结论:七成协调蒸发;承重件不依赖 stannum;可替换件关在刻画 gate 后(ch10:26–28) | 双 stage 结构+不变量 7(gate G1/R2);R4 判定行 |
| 10.2 | 工具族四行画景+查询时序(parse 内 build_tinql→recall→过滤;assemble)(ch10:33–54) | 时序兑现:build_tinql/recall(第 8 位)/信封接线(parse 面过滤归 DP6——ch10:50–51 的存在性 Noul/per-chunk Score 是 §4.5=DP6,教程时序图按 DP6 完成后全真);四行画景的实现归置注记(附 A #9:ingest=驱动器+effect[DP4]、recall=函数族[本 DP]、filter=决策平面[DP6]、assemble=refresh settle[DP3]) |
| 10.3 | 刻画 gate 六条(ch10:70–84) | K/L/M/N/O 组逐条;T0/T1/T2 分层表(ch10:86–90)→§2 映射+§7 台账 |
| 10.4 | 召回是函数+三禁+v13_build_tinql 全限+CJK 短语引用+kohaku(ch10:92–130) | §3.1 L1/L2+不变量 2+gate A/G/K/R;签名 (p_tinql,p_k) 教程草形→冻结 |
| 10.5 | 过滤管道(存在性 Noul 先行+per-chunk Score+跨 session) | 不做(DP6;§7)——ch10:192「存在性 Noul 归 DP6」的 plan 侧落点=§1.4 DP6 行① |
| 10.6 | 装配清单 schema+跨度装配+三种回放 | manifest 候选填充(E 组;sections/schema=DP3 已落);跨度装配=DP4 已落+本 DP spans v2;三回放=DP3 已落(E4 复测) |
| 10.7–10.8 | 逐段解释+G-ctx3/G-ctx4/G-ctx5 断言块(ch10:195–239) | G-ctx3=本 DP(A/C/G/K/L);G-ctx4=DP6;G-ctx5=DP3(E 组复测);摄取回响(B4/⑨) |
| 10.9 | 练习 1(三禁再造 canary 必红)/2(过滤)/3(清单)/4(T2 可选) | 练习 1=K3/L/K5(实测注记);2=DP6;3=E 组;4=台账(T2 离线) |
| 10.10–10.11 | vN 对照+内在合理性 | 本 plan §1/§2 论证引用;正文零改动 |

教程正文已含全部 normative 内容——本 DP 是兑现侧;§13 第 10 章行(T0 前插刻画/三禁/装配清单 schema/存在性 Noul[其归 DP6 的注记]/v13_build_tinql)全部在场,零新增指针需求。

---

## 7. 明确不做(§12 台账为源;P2/台账项一律不承诺为首版交付)

| 项 | 依据/触发条件 |
|---|---|
| T1 vectorchord 混检/RRF 一条 SQL | 固定评估集证明 lexical 漏召;嵌入=派生缓存行(content_hash×model)、embed=effect——形态照抄入台账(§7 原文),零实现 |
| CJK bigram 列(GENERATED v13_cjk_bigram+独立索引+查询侧同函数) | kohaku fixture 漏召率超阈值;**必须独立列**(同列双索引歧义已实测);0.1.0 单字 Katakana 边界(L3)是其动机面之一 |
| boost 反馈环闭环 | 离线 held-out 指标+词项自查可用或漂移 canary;**tokenize() 已实测存在**(附 B)——台账行「stannum tokenize() 待核实」半边可关闭(§14 遗留开放项);boost 语法本身 0.1.0 未实证,非空态 V3005 |
| 语义决策缓存(decisions.question 近似检索+Noul 等价) | 判断缓存费用成为账单大头 |
| 全集 Choice 重排/跨 chunk 合并/window GC 执行器/主键迁移/artifact ref 路径 | DP4 §7 台账原样(⑦缝保留:units 已携 chunk_offset) |
| pg_cron 新 job/tick | verify job 已挂(DP4),v2 自动覆盖 stannum 面;tick 归 DP6 且 §12 触发 |
| 过滤管道/存在性 Noul/per-chunk Score/transcript_chunks 记忆栈/chunk section 生产者 | §4.5/§4.4=DP6(分解表权威);§1.4 DP6 行转发 |
| 解析相判断花费闸/快路超批 tier 裁量/k_max 放宽 | F5①③=DP7 立法面(§1.4 DP7 行);本 plan 只立硬上限+一页账 |
| psql_bm25s | §8:被 stannum 替代(超集),不装 |
| recall 引擎第三形态/工具目录注册 rag_recall 行 | 附 A #9(sql handler 签名纪律;四角色已由平面机制承载);目录行画景的「definition 可换」精神由签名冻结+OR REPLACE 换体承载 |

---

## 附 A:与设计稿/上游裁决的分歧点清单(供父 loop 复核)

| # | 分歧/裁量 | 论证 |
|---|---|---|
| 1 | **作用力 2 机制在 stannum 0.1.0 未复现**:实测 planner support 把任意表达式(含 Param、force_generic_plan)改写为 bind_query(expr,oid) 保持绑定;DDL 无效化使索引后建的静态调用重绑;真实降级面=无索引回落(默认 comparator 语义分叉)+同列双索引错绑 | 设计稿禁改;三禁保留为冻结 DDL 纪律(作用力 1 的审计理由——「视图只能尽力再生,永远不是审计来源」——不受影响)+纵深防御(EXECUTE 每次新计划=绑定 planner 当前最优,静态路径缓存单选);gate K3/K4/L 断言实测降级面,K5 记录三禁路径的 0.1.0 等价性+升级复测项;「stannum IndexScan」的实测形态=Custom Scan(Stannum Text Search Scan),K1 按实测断言 |
| 2 | cgr 接线选「并入 bump 面」(非 probe 第八键) | DP1 #59 二选一的裁量:OQ1 三点论证(cgr 语义/改动面/成本);probe/snap_of/envelope 键集零动 |
| 3 | csh 材料扩集(needed∪recall 入哈希) | 「candidate_set_hash 定义不变(对推导结果全集取 hash)」的读法:公式不变、推导全集扩含召回候选;哈希值变化=旧信封失命中冷缓存(DP2 builder 替换先例同款可接受) |
| 4 | DP2 §1.4「DP5 新增召回判断族=新增模板族行+needed 新分支」收窄至 DP6 | 分解表权威(§4.5 归 DP6);DP5 只落推导面接线;cgr 承接机制照旧(DP2 行的机制面全消费) |
| 5 | 信封/manifest 均不内嵌 TINQL 串 | DP3「manifest 不内嵌 TINQL」的同型延伸(只记产物;TINQL 可由 goal 文本+代码确定重现);k/matched 入 csh 材料不入键(派生值随语料确定) |
| 6 | v13_extract_spans v2 载荷从「词数组」换 `{"tinql":…}` | DP4 契约④字面(签名/输出不变)满足;载荷是 recall 家族内部约定(唯一外部消费者 v13_assemble_spans 不调 extract——DP4 §3.5 事实);调用方随 definition 同文件换体,零跨约定面 |
| 7 | T0 bm25 列=ts_rank 确定性实数(非 BM25 语义) | §7 T0「tsvector 起步」的诚实载体:排序+并列截断确定性是 normative 面,BM25 数值语义归 v2(full_score);README/gate 注记不虚标 |
| 8 | token 第九键 recall_ver(八→九) | DP3 追动键缝新实例(OQ8:k 决定 manifest 候选截断);键集变化⇒全域恰一次 refresh(DP3 OQ1 既判);boosts/span_asm 不入(各自触发条件未至,缝转发) |
| 9 | ch10.2 工具族四行不落 tools 表注册(rag_recall 不注册 kind='sql' 行) | sql handler 签名纪律=「(session_id uuid, params jsonb)」(DP1 #23 统一),v13_recall (text,int) 不兼容——强行注册被 v13_tools_guard 拒或扭曲;注册还会把 param/stated 判断信号灌进 needed(目录推导面污染);四角色已由 effect 驱动器(DP4)/函数族(本 DP)/决策平面(DP6)/refresh settle(DP3)承载;「目录行是数据,流程零改」的精神由签名冻结+OR REPLACE 换体承载 |
| 10 | canary 载体=专用 fixture 表(非生产索引加 WITH 选项) | 实测:同列双 stannum 索引 planner 恰绑其一;canary 需非默认配置索引,与生产默认配置索引同列必歧义;专用表隔离;生产默认配置下索引丢失=性能事件(正确性检测=EXPLAIN 形状+verify v2) |
| 11 | 生产 stannum 索引=默认配置(零 WITH) | 默认回退 comparator=最宽配置(实测),默认索引下「无索引回落」语义等价——正确性风险最小化;CJK 需求已由 unicode 默认切分覆盖(Han/Hiragana 逐字);非默认配置的收益面(变音语料 accent_fold 等)未见需求,台账 |

**设计矛盾检查:未发现 blocked 级矛盾。**§4.1/§4.6/§4.7/§4.8/§7/§8/§9/§10-G-ctx3/§12/§13 的 normative 内容全部有落点(§2 映射表);唯一的设计-引擎分歧(作用力 2 机制)是实测事实呈报(#1),纪律面照设计执行,不构成矛盾;stepfun F4/F5 的 DP5 落点全部承接(F4=刻画 gate 真实执行+runbook 六件;F5②=k_max+一页账、F5①③=DP7 缝)。

---

## 附 B:全教训自检(turn 1–24,机械执行记录)

| 教训 | 执行记录 |
|---|---|
| **引擎争议实机实证可选(turn 10/12;本轮已做)** | 2026-09-21 pgembed PG18.4+stannum 0.1.0 探针库(`v13_dp5_probe`,用毕即删)实测清单:①扩展可用(stannum 0.1.0/typesafe 0.0.1);②`==>` 算子注册于 **pg_catalog**(text==>text[stannum_text_cmpfunc,IMMUTABLE,回退形态]/text==>stannum.indexed_query[STABLE,绑定形态]);③函数面(schema `stannum.` 限定):bind_query(query,index oid)/full_score(ctid[,k1,b])/max_score/score 族(term_add/term_replace 不能双非 NULL)/highlight(text,begin,end,query text)【IMMUTABLE;indexed_query 形态 STABLE】/tokenize(存在!——§14 遗留开放项「tokenize() 是否存在」关闭;参数词表:tokenizer∈{unicode,whitespace}/case_folding∈{preserve,fold}/accent_folding∈{preserve,fold}/long_tokens∈{truncate,discard,split}/max_token_bytes/graphemes∈{discard,emoji,retain}/position_gaps∈{collapse,preserve})/ql_parse/maybe_quote(多 token 才引号——本 plan 弃用改全引号,OQ7)/verify_index(index regclass,heap_check bool)→TABLE(severity,location,message)(0 行=干净)/segment_info(fold 段可观测:immutable+mutable,generation 随插递增);④索引 `USING stannum (col)`+WITH 选项(reloptions 记录);⑤默认回退 comparator=unicode+fold+fold+truncate+retain(最宽;café≡cafe 命中、emoji 命中);⑥unicode 切分:東|京|タワー|高|さ|333m|で|す(Han/Hiragana 逐字、Katakana 连跑、alnum 连跑);⑦planner support 把任意表达式改写 bind_query(expr,oid)——**参数化与 force_generic_plan 下保持绑定**;EXPLAIN FORMAT JSON:Node Type=Custom Scan+Custom Plan Provider='Stannum Text Search Scan'+Index+Query;⑧实测降级面:无索引→text==>text 默认 comparator(split 索引 canary:64B 块 bound 命中/回退漏召);同列双索引→恰绑其一(错绑错结果);⑨未复现:generic plan 回落/静态 stale-plan(DDL 无效化重绑);⑩REINDEX 后 recall/verify 绿;fold 后 count 精确(51/51);highlight 哨兵(多命中/口音折叠加亮 'cafe'→café/短语「東京」) |
| **纸面加载模拟记数字(turn 8/9)** | §3.1(第 8 位)顶层语句 14=CREATE FUNCTION 10(新 6:query_segments/build_tinql/tinql_terms/recall/recall_count/recall_candidates+换体 4:chunks_generation_bump/context_required/judgment_envelope/assemble_manifest)+INSERT 1(2 行)+REVOKE 1+GRANT 2;BEGIN/COMMIT 1 对;$$ 配平 10 块;0 重复定义(四个换体均为全树唯一新形态存活:八键 token 唯一存活于 ≤7 号库、九键于 ≥8 号库——非移动,授权换体);§3.2(第 9 位)顶层语句 9=CREATE EXTENSION 1+CREATE TABLE 1+INSERT 1+CREATE INDEX 2+OR REPLACE 4(extract_spans/recall/recall_count/verify_chunks);$$ 配平 4 块;0 省略号(全部 SQL 块完整);前向引用分层:L1 纯文本三函数(query_segments 先;build_tinql/tinql_terms 只依赖 L1)→L2 recall v1(L1+DP4 extract_spans[7 号已载])→L3 count v1→L4 candidates(L1–L3+v13_goals/v13_policy[6/1 号])→L5 bump 换体(7 号表+1 号表)→L6 token 九键(6 号函数体依赖+7 号表+策略)→L7 envelope(5 号对象+L4)→L8 assemble(6 号全 CTE 对象+L4)→L9 种子→L10 ACL 真末尾;第 9 位:EXTENSION→表+种子→索引→extract v2(stannum schema)→recall v2→count v2→verify v2(stannum+索引在前);逐层仅依赖更早层,0 违例 |
| **类型算子层(turn 7/8)** | 策略种子单完整 JSON 字面量+$j$::jsonb(§3.1 L8,两行,全文件唯一 jsonb 字面量族);数值显式 cast(v_kmax::int/ceil(v_cnt*v_wr)::int/ts_rank()::numeric/full_score()::numeric/(c->>'bm25')::numeric);tsquery 组合=值级 &&(phraseto_tsquery 显式 'english'::regconfig);EXECUTE 全 USING 参数化(字符串仅静态骨架 ||,零用户文本拼接;''tinql'' 双单引号转义与 $$ 定界零冲突——DP4 注①同款);词表/键存在校验分步 IF 求值序(v2 boosts 的 typeof 先验后再 array_elements);jsonb ‖ 仅对象‖对象(qside 四键补全);ascii()/octet_length/position()/left() 字节口径换算公式两行(bstart/bend,§3.2 已推导并双例验证 ASCII+CJK);digest 产物 encode hex(csh 材料);布尔判断无三值穿透(上限/域校验全部显式 IF,无 NOT IN) |
| **移动=增+删(turn 8 #57)** | 六个 OR REPLACE 均同签名换体(非移动,零 DROP):旧形态不在本两文件任何位置重复(八键 token/十九键信封/echo 装配/v1 recall 族/词数组 extract/verify v1 的唯一存活形态=上游文件,其前缀 stage 库照常);canary 表与生产索引为纯新增 |
| **gate 不引用未加载对象(turn 7 #46)** | stage 8 gate(A–J)断言对象全部 ≤8 号文件;stage 9 gate(K–R)≤9 号;I1 显式断言前缀切片(DP4 库八键 token/无 recall 函数);K/L 的 canary/临时表对象在 9 号文件或 gate 自建(测后 DROP);三禁演示对象=gate fixture(R2 源码扫描不将其计入生产面) |
| **哈希同源(turn 6 #43)** | csh 材料单点(envelope rc CTE);候选单点(v13_recall_candidates——信封 rc/装配 qside 两消费共一源,零第二实现);k 单点(recall_k 行);goal 文本单点(v13_goals 活动行);token 单点(context_required 九键);TINQL 单点(v13_build_tinql——recall 入口只接自产文法,回析器守卫);哨兵单点(extract v2 内四对确定性选择) |
| **新写 SQL 自检五项(turn 3+)** | 参数全用:六新函数全部参数参与(含 v_tmo 域校验消费);列存在:全部引用列在 DP1–4 DDL 在档(chunks 七列+chunk_offset/v13_sources.superseded_by/v13_policies.active/v13_tools_meta.cgr);语法:EXECUTE USING/unnest WITH ORDINALITY/string_to_array 形态已核;RAISE 全 V3005(复制体 V3001–V3004 逐字保留);块末分号:14+9 语句逐一(纸面模拟过) |

---

## References

- 设计冻结稿:`docs/designs/v13-context-on-pg.md`(§4.1/§4.6/§4.7/§4.8/§7/§8/§9/§10 G-ctx3/§12/§13;2026-09-19 v2 禁改)。
- 设计审查:`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md` F4/F5(本 plan 承接面:§1.3 OQ5/§4 末一页账/§1.4 DP7 行)。
- DP1:`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md`(§1.3 契约+#59/§3.2 needed/envelope 原体/§3.5 probe/§3.6 #60)。
- DP2:`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md`(§1.4/§3.4 信封十九键体)。
- DP3:`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md`(§1.4/OQ1 追动键缝/OQ4 字段族/§3.4 装配体+校验器层 6)。
- DP4:`docs/plans/v13-dp4-chunks-projection-plan-2026-09-20.md`(§1.4 契约①–⑨/§3.1–§3.8 全部基座)。
- 教程:`docs/tutorials/v13/chapters/10-rag-as-tools.md`(全文;ch1 events 表)。
- 引擎实证:stannum 0.1.0+PG18.4 探针库(2026-09-21;附 B 清单;探针库用毕即删)。
- 仪式参照:`v12/load.py`(run_psql/files_through)、`v12/indb/setup_db.py`、DP2–DP4 各 §3.8/§3.3 形制。
