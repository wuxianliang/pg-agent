# v13 DP9 —— Jev-Mem 多关系记忆图(mgraph)计划

> 状态:**终稿 v1.2**(2026-09-23;五轮评审闭环:第一通道 grok-4.7 裁决 → 第二通道 claude-opus-1m 交叉背书 → design 代理评审 S1–S16 → Oracle 审核轮 P0×1+P1×9+P2×5 → **Oracle 复核轮(续会话)折入复核+新擉 P1×6+P2×4 全部折入**。§1.3 为最终权威)。裁决记录见附录 D。
> 分解来源:用户指令——把 Jev-Mem(github.com/libingzheren/Jev-Mem)代码逻辑实现在 v13 的 Postgres 中;图结构考虑 pgembed 已打包的 age 插件或递归查询;设计决策与实施方案用 Oracle 裁决。
> 设计输入(冻结禁改):`docs/designs/v13-context-on-pg.md` v2、`docs/designs/v13-errata-2026-09-21.md`、`docs/designs/v13.1-workbench-plane.md`。
> 惯例参照:`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md`(§0/§1/§4/§5 骨架权威)、`v13-dp8-periphery-p1-plan-2026-09-20.md`(§1.3 裁决格式)、`v13-dp6-filter-memory-plan-2026-09-20.md`(投影+模板族先例)、`v13-dp7-economics-summary-plan-2026-09-20.md`(验收带先例)。
> 仓库约定:`AGENTS.md`(里程碑全绿→收尾工件→按路径 add→commit→push;一里程碑一提交;不用 `git add -A`)。
> 调研基线:五路探查(2026-09-23)蒸馏于 §2;题面权威=入库的 `v13/mgraph/QUESTION_SNAPSHOT.md`(上游 URL+commit+每槽 sha256),**不是** `/tmp/Jev-Mem-main`(克隆仅是抄录来源;`/tmp` 失效时从所钉 commit 摘抄,摘不到 M1 保持红)。

---

## 0. 执行索引

| 里程碑 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| **M1 暗库** | 表/策略行/六族模板/defaults 追点/ACL 就位,行为全关;**只许 `CREATE TABLE`,不许 `CREATE EXTENSION age`** | `uv run python v13/mgraph/test_mgraph.py` A 组绿;schema→periphery 全部前序 gate 绿 | `v13/mgraph/v13_mgraph.sql`(表+种子段+**信封构造器 v13_mgraph_envelope**——A9 依赖,Oracle 复核 P2)、`QUESTION_SNAPSHOT.md`、`setup_db.py`、`test_mgraph.py`、`README.md` 骨架、`load.py` +1 行 | 槽位 1–14 已加载;stannum 由 characterize 建好;`transcript_chunks` 在 | ~600 行 SQL + ~250 行测试 |
| **M2 写与重建** | episodic 投影+确定性结构边+关系判断边+幂等重建 | D 组绿(含毒化零调用重建) | 同文件追加 build/apply/candidates/rebuild | M1;resolve_login 可用 | ~400 行 |
| **M3 读环(B1)** | 确定性路由+预算分配+逐轮一跳+证据充分性停止+evidence 出口(零 effect、零 resolve/failed) | E 组绿 | 同文件追加 route/allocate/run_round/should_stop/evidence | M2 | ~450 行 |
| **M4 固化** | 五问+生成升级(新 kind `mgraph_consolidate`)+fidelity 门+consolidation 节点(远程层首批);**不含装配改动(B2 已裁出本 DP)** | F 组绿 | 同文件追加 consolidate 链+kind/cap/窄 requeue(同事务) | M3;summary 先例 | ~450 行 |

总计:1 个新 stage(`v13/mgraph`,SQL_LOAD_ORDER 第 15 槽)、4 次提交、与 DP6 同阶 + 一条 DP7 形态的验收链。测试只留已裁分支,不保留可切换的未选支骨架(Oracle 轮 1 整体(1))。

> **实施进度**:M1 ✅(2026-09-23 交付;A1–A9 全绿 169 PASS,前序 14 gate 回归全绿——twophase/envelope 的本地红系未入库 demo 树(v13/demo/ 整树 gitignored,aa106b7)被全树扫描误中,提交态干净;实施偏差九条见 v13/mgraph/README.md 偏差台账,含上游行号按钉死 commit 校正)。
> M2 ✅(2026-09-23 交付;A+D 241 PASS,前序 14 gate 回归全绿;偏差台账 #10–#17 见 v13/mgraph/README.md——含 typesafe provider 占位符陷阱的 5 参信封重载、GUC mock 单批形状限制的 write_max_batches=1 步进驱动、mem_rel_entity 写路径结构性不可达改经 pair_questions 直测)。
> M3 ✅(2026-09-23 交付;A+D+E 277 PASS,前序 14 gate 回归全绿;偏差台账 #18–#28 见 v13/mgraph/README.md——读环一步一封、确定性升权 = floor+1 且主意图互斥、max_latency_ms 允许 0、timeout_ms 非整数丢弃、E5 的 failed_timeout 由夹具种入)。

---

## 1. 定位与边界

### 1.1 版图位置

DP9 = 记忆区的关系投影层:DP6 `transcript_chunks`(逐字层)的下游消费者、设计 §4.4 三层栈第三层(远程层=摘要 artifact)的**首个具体实现载体**(consolidation 节点即远程层检索对象)、设计 §12 台账「语义决策缓存」的相邻件(结构化层索引 `ix_decisions_question_stannum` 已在,本 DP 不动它)。文档语料面(chunks/recall/CAND4)不碰(OQ8=B1;B2 已裁出本 DP,属下一张计划)。

判断链全部复用:模板注册→`v13_judgment_envelope` 形态→`v13_resolve_judgments`(只调用不换体)→`judgment_cache`(全局)/`judgment_calls`→`decisions`。Jev 只产不可变带版本证据;插边/分预算/停止/采纳合并全部由版本化策略行 `mgraph` 在 SQL 里授权(设计 §6.1 证据/动作分离)。

### 1.2 基座裁决(本计划替实现者定死;Oracle 轮 1 已确认,除注明外)

1. **新树只追加**:先前 stage SQL 文件保持原字节;活函数替换只允许在 `v13_mgraph.sql` 内 `CREATE OR REPLACE`,且替换源必须是 periphery 库 `pg_proc` 活体(M4 的窄 requeue 是唯一触碰;装配/校验器/context_required **不碰**——OQ8=B1)。
2. **零 `SECURITY DEFINER`**(与 `v13/memory/v13_memory.sql` 头部纪律同构)。
3. **零新执行机制**:不建第二队列、不改 `v13_advance` 五步、图遍历不进会话锁。
4. **错误类 = `V3009`**(核验:V3001–V3008 已被答案形状/信封/清单/chunks/recall/filter·memory/summary/periphery 占用,`v13/periphery/v13_periphery.sql` 含 V3008×43 处)。
5. **部署默认暗**:`write_enabled=false`、`read_enabled=false`(与 Jev-Mem 代码默认一致,`jev_mem_config.py:12-13`);翻开才走判断。
6. **剧集 v1 = 一行 `transcript_chunks`(一次策展事件)= 一个 episodic 节点**;不移植 LLM episode segmenter(`episode_segmenter.py:80-183` 属 worker 侧)。
7. **外部引用列只存 `content_hash`(64 hex)**;`seq` 只留在投影内部做水印,不进 `memory_links`、不进 effect request、不进 manifest。
8. **T0 用词法分,不用余弦**:嵌入留在设计 §7/§12 的 vectorchord 触发之后(OQ7=A)。
9. **题面不赝造,权威=入库快照**:实现第一步从 Jev-Mem 上游(所钉 commit)抄入 `QUESTION_SNAPSHOT.md`(上游 URL+commit+每槽 sha256);`/tmp` 克隆只是抄录便利,失效时从 commit 摘抄对应行,摘不到则 M1 闸门保持红;停用词表允许先 `[]`(多抽不假抽),不因此卡 M1(Oracle 轮 1 整体(2))。
10. **`consolidation_interval` 整数不进种子**:代码默认 0(`jev_mem_config.py:45`),v1 种子 `consolidate_mode='manual'`、interval=0;论文附录「每 20 写」**不得进种子也不得当降级路径**,快照或 README 只可记一句「论文附录写 N,代码默认 0,v1 不采用」(Oracle 轮 1 整体(2))。

**复用不新造**:`judgment_templates` 生命周期(draft→freeze→cgr bump)、`v13_resolve_judgments`、`v13_lock_key`、`v13_judge_spend`、`v13_body_hash`、`v13_goal_hash`、`v13_guc_required`、`v13_projection_key`、`v13_query_segments`(CJK 判定)、`v13_summary_schedule` 的空闲闸形态、`v13_rebuild_transcript_chunks` 的幂等重建形态、`v13_verify_memory` 的校验器形态、策略翻版仪式(INSERT inactive→双 UPDATE 翻 active)、DP1 毒化零调用断言(`failed=false` 且 asked=0)。

**阻塞点(设计必须绕开的五个)**:
1. 活信封/装配/resolve 的最后函数体在 periphery 加载态,不在 recall 文本里——按 recall 文件整段重写会把 DP6–DP8 退回去。
2. `jev_questions.py` 题面原文不在仓库——自拟英文题面会把判断缓存键钉在赝本上(快照闸门防)。
3. 一跳之间夹着判断提交,不能收成一条递归 CTE 或一条 AGE VLE——遍历天然逐轮。
4. 复用 `kind='judge'` 做后台游走:失败结算写 `resolve/failed` 吃掉本 turn `resolve_retry`;复用 `kind='llm'` 做固化生成:`v13_complete` 无条件写 `llm/message`(`v13_core.sql:373`),路由 P0 对「origin=当前 last_user_seq 且 seq 最大」判 `finish`(实码 `advance.sql:126-131` 的 `v13_route` IF 支;:71-73/:119 为注释——Oracle 审核 P2-1 校准),合并正文会进逐字投影——**故固化生成走新 kind `mgraph_consolidate`**(OQ6)。
5. 后台 effect 占单活跃槽(`ux_v13_effects_single_active`),advance ① 会把会话打成 `waiting`——读环因此零 effect(OQ2=B1),固化 effect 受调度闸约束(OQ6)。

### 1.3 Open Questions 裁决(Oracle 轮 1,2026-09-23;本节为最终权威)

> 格式沿用 DP8 §1.3。每项:裁决+依据链+机制;已否决支线保留一行依据备查,其 DDL/函数体/gate 不进仓库。

**OQ1 图承载 —— 裁决:A(两表+索引化一跳 JOIN);AGE 不进运行时。**
依据:设计 §8 已排除 age(第二查询语言),进核心须同时满足元原则 (a)(b)(c);本读环是「一轮一跳+轮间判断」,VLE/最短路用不上(§2.4);pin=1.8.0-rc0(`e43dc1a`)仍开放 #2465/#2179/#2486,#2551/#2517 在 pin 之后;「已打包」只说明能 `CREATE EXTENSION`,不是准入。
机制:只建 `memory_nodes`/`memory_links`、`ix_memory_nodes_stannum`、`(session_id,src_hash,rel)` 与 `(session_id,dst_hash,rel)` btree;`v13_mgraph_neighbors(sid,hash,rels[],limit)` 普通 SQL,`ORDER BY structural DESC NULLS LAST, dst_hash ASC`(**唯一知道存储形态的端口**——桶→rel 过滤经 rels[] 入参承载,禁另造变体函数);`v13_mgraph_structural_reach(sid,hash,depth)` 仅调试用 STABLE SRF(深度读 `maximum_depth`,非 VIEW 非物化),热路径禁止调用;`v13_verify_mgraph`=自证+悬空边+策略行+两索引 `stannum.verify_index` findings=0+源码无 `cypher(`。
Gate:`enable_seqscan=off` 时邻居计划含上述 btree;并发同 PK 只留一行。
**AGE 台账触发(三条同时,取代含糊的「图遍历需求出现」,写进 §8)**:①热路径变为无逐跳判断的变长展开或最短路,且一跳 JOIN 的 p95 实测不够;②pin 含 #2465/#2179/#2486/#2551/#2517(或等价新 pin);③刻画 gate 能钉确定性结构断言(不钉 EXPLAIN 原文)、单真相、无双写,并重过 §8 元原则三条。
已否决:B(AGE 图)——元原则「EXPLAIN 可钉」「单一真相」不成立+pin 缺陷。

**OQ2 检索环事务位置 —— 裁决:B1(无 effect 驱动分轮);A 维持否决;B2 删除。**
依据:A 把 `maximum_jev_calls` 与 `max_latency_ms=15000` 放进 `v13_parse`:突破设计 §4.3 快路「默认 ≤1 批」,解析事务拉长后步 0 几乎必 stale,同轮咨询锁覆盖整段游走(注:parse 本就不持会话锁,「G-ctx1 events INSERT 必红」不作为依据);B2 的 ready|claimed 命中单活跃索引,advance ① 把用户回合打成 waiting(阻塞点 5);若 effect 不占该槽,它就不再是 effect——「只唤醒不占槽」的裁剪 effect 同样不采纳。
机制:无 mgraph 游走 kind、不改 `v13_advance`、读路径不写 `resolve/failed`;`resolve_login` 驱动循环 `v13_mgraph_run_round(sid, p_elapsed_ms)`(elapsed 由驱动累计传入——latency 判定的唯一写入点,Oracle 审核 P1-3)直到 stop/预算;**每轮事务先取 `pg_advisory_xact_lock(v13_lock_key(sid,'mgraph-build'))`——与 build 的会话级 `pg_advisory_lock`(§3.4④)同 key 跨级互斥,读写不并发;可见性口径=未提交半截不可见、已提交前缀可读且自洽(Oracle 审核 P1-8+复核 P2;E3 全等以锁内为前提)**;每轮独立事务:`v13_resolve_judgments(env,1)` 后 `apply_round`;停止入口=`v13_mgraph_should_stop(walk_id)→{stop,reason}`(读已落库四条 Noul 与策略阈值,四条排序规则见 §3.4);路由入口=`v13_mgraph_route(query)→{mode,weights}`;**`calls_used` 计「批」(ask 信封数)且失败批也计 +1**(活体失败路径先插 judgment_calls 再 EXIT、不加 asked_batches,filter:727-760 区段——Oracle 审核 P1-3;spend 侧 judge_spend 数 judgment_calls 行,失败已计,两侧口径因此一致);**spend over/帽尽/超 latency 由 run_round 写 stop_reason(spend|calls|latency)并 status='stopped'(不空转)**;15s 在两轮之间由调用方 `clock_timestamp()` 对 `max_latency_ms` 比较(不靠 statement_timeout 代替;语句超时仍按 DP1 α);崩溃重跑=已提交轮次+`UNIQUE(walk_id,round)`;walk 身份 `(session_id,query_hash,mgraph_generation,policy_version)`,翻策略即新 walk。
Gate E6(仅 B1):游走期间 effects 行数与 `resolve/failed` 不变;并发 `v13_append_event` <5s;本函数不持该 session 元组锁。
写路径与读路径同一分轮机制;写路径不受 `maximum_jev_calls` 约束(该键只限一次 read walk),花费帽=**每次 build 独立 ask 帽 `write_max_asks`(默认 64 批;与 write_max_batches 同族节流帽,非第二套账——三帽关系见 §3.2 注)**+`write_max_batches`(每 tick 节流,默认 8,缺口下次 tick 继续)+既有 `judge_spend_gate`(不变量 13);运维注记:`judge_spend` 数 judgment_calls **行=ask 批数**(每新 episodic 节点 ≤11 批:1 类型封+≤10 关系封),session_asks_cap=512 ⇒ **≈46 新节点触顶**;开启 write 前按 transcript 规模评估/上调 session 帽(README);**calls_used/write 帽计数=每封发出即 +1(含失败批,与 judge_spend 数 judgment_calls 行同口径;`asked_batches` 仅计成功批,filter:952-958,不作帽计数源——Oracle 审核 P1-3)**。

**OQ3 routing 信号源 —— 裁决:A(确定性 SQL 先行+六问模板预注册默认不调用)。**
依据:设计 §6.2 触点 5「为此新调 Jev 即 P2;低置信/CJK/缺失绑超集」;六条 routing 是新调用,只用于软门控可选检索面。
机制:仍种子并冻结 `mem_routing_*` 六模板(与 DP6/DP7 一样会扩大主信封 templates 并在加载时 bump cgr 一次;**禁止为过滤它们去 OR REPLACE `v13_judgment_envelope`**);`routing_mode='deterministic'`、`routing_shadow=false`;CJK 段(`v13_query_segments`)→superset 六桶 ≥`deterministic_floor`、routing asked=0;英文子串 WHEN→temporal、WHY→causal、大写实体形态→entity,否则 semantic;`multi_hop`/`recency` 仅主意图点名才升权,**其余未被升权的桶一律保持策略 `deterministic_floor`(权重全向量六桶全有值——allocate/E1 手算夹具的输入契约)**;`routing_mode='jev'` 才把六问放进 walk;shadow 只在该 walk 已停止且 `judge_spend` 有余量时发问,`final_action='recorded'`,**不计入 `calls_used`**,allocate/stop/frontier 不读。
Gate:默认英文 WHY 查询 asked 无 `mem_route::` 前缀;CJK 六桶预算≥1 且 routing asked=0;`routing_mode='jev'` 夹具才出现六条 decision;**shadow 前后 frontier JSON 全等**。

**OQ4 节点身份 —— 裁决:B(PK `(session_id,content_hash)`;无 corpus 列)。**
依据:episodic 正文是会话私有面(`v13_transcript_recall` 按 session 过滤),全局 PK 漏一条可见性连接就串会话;判断缓存全局、边落本会话,与 DP2「全局 cache+session decisions」同构;设计 §4.2 外部只引用 content_hash;DP6 记忆表无 corpus 列先例。
机制:无 corpus 列、无指向 `transcript_chunks` 主键/seq 的 FK;`body` 复制策展正文;`source_hashes` 含来源 `content_hash`;**边 `decision_id` 只能是本 session 的 decisions 行**;同文异会话=两行节点+一条 cache;重建后哈希不变。删除全局 PK 与可见性表方案。

**OQ5 admission 五问 —— 裁决:A(不做,只占策略键)。**
依据:v1 无消费者;开关打开却未装实现=配置错误,与 `v13_filter_defaults_action` fail-closed 同向;预先播种无调用方的模板只会再扩大主信封 templates。
机制:不建 `mem_admit_*`;`admission_enabled=false`;该键为 true 时 build **RAISE V3009**,零节点零 ask。Gate:默认 build 无 admit 前缀;翻 true 后抛 V3009。触发(§8):花费账单 admission 成可见大头,或产品要求「不该记的不进图」。

**OQ6 固化接线 —— 裁决:A(新模板族+图内产物节点);生成 effect 禁止 `kind=llm`,新 kind `mgraph_consolidate`。**
依据:`summary_fidelity` 问的是 span 保真,不是「两段记忆可否合并」——谓词不同必须新模板;设计 §6.4 确定性检查先行、失败不调 Jev、不重问同一正文;`v13_complete` 对 kind=llm succeeded **无条件**写 `llm/message`(`v13_core.sql:373`),路由 P0 对 origin=当前 last_user_seq 且 seq 最大者判 finish(实码 `advance.sql:126-131` 的 `v13_route`;:71-73/:119 为注释)——合并正文会进 canonical/逐字投影(P0);`context_summary` 能避开语义事件但是另一条管线且占 `v13_summary_schedule` 日帽。
机制:
- 模板六枚:`mem_cons_redundant/contradiction/obsolete/link`(Noul)+`mem_cons_representation`(choice 闭集 keep_separate|merge|promote|uncertain)+`mem_cons_fidelity`(Noul,投影 `["source","summary"]`),`epoch='pre-finalize'`,投影禁 `["*"]`。
- v1 仅 `consolidate_mode='manual'` 且 interval=0,无自动计数器;并列序只读 `consolidation_priority`;`contradiction≥consolidation_threshold` 时即使 choice=merge 也不入队。
- 生成 kind=**`mgraph_consolidate`**:`effects_kind_check` 与 `effect_attempt_cap` 新版本**同一事务**(七键齐全,旧六键逐字保留,本键 cap=2,仪式照 summary:22-93);`v13_complete` **不改**(非 judge/tool/llm→只有 effect_done);`v13_requeue_stale` 只允许在本文件按**活体** OR REPLACE:该 kind 与 judge 同待遇,cap 内回收 ready(只 fence+1,attempt_no 不动),超 cap failed+`lease_exhausted`+wake,**其余 kind 字节级保持现状**。
- enqueue 仅 route 角色,且会话上已有 `ready|claimed|unknown` 时返回 NULL;request 只含 `{purpose:'mgraph_consolidate',left_hash,right_hash,consolidation_key,policy_version}`;worker 交 `{text}`。
- 确定性检查失败则零 fidelity ask;fidelity 非 include 不插节点;rejected 不重问同一正文(重试必须新正文);原文节点与 `origin=consolidation` 的边不 DELETE;产物=远程层第一批实现,检索对象是节点 content_hash。
Gate F2 追加:零 `llm/message`、零 `turn/end`、零 `resolve/failed`,路由不因此 finish。
已否决:B(复用 summary_fidelity)——谓词不同,缓存会串 request_hash 空间。

**OQ7 候选发现 T0 —— 裁决:A(stannum+池内归一化 BM25)。**
依据:记忆语料以 CJK 为主,设计 §4.8 下 tsvector 对 CJK 是空池(「東京タワー」例);槽位 9(characterize)在槽位 15 之前;BM25 随 IDF 漂移(作用力 1),不能当审计真相。
机制:`==>` 只出现在候选函数的 EXECUTE 串,**本文件源码计数=恰 1**(memory 先例同款确切数,memory:136 注释形态);**候选函数签名 `v13_mgraph_candidates(p_sid, p_tinql text, p_k int)`——p_tinql 必须经 `v13_build_tinql`→`v13_tinql_terms` 产出(memory reader 同族;用户文本不得直拼 EXECUTE——设计 §4.1 三禁,Oracle 审核 P1-7)**;候选函数必须由 TINQL 谓词驱动 stannum 索引扫描,**禁裸表扫描后算分**(评审 4 补);候选函数的 EXPLAIN 断言与 OQ1 邻居 gate 分会话跑(enable_seqscan=off 不顺手钉候选函数);视图/静态 SQL/预备语句仍禁;系数只读策略行;**全部本批 episodic 行插入之后再计分,池=本会话全部 episodic 节点,不得按到达顺序缩小池;consolidation 节点不作候选锚(只经遍历可达,见 §3.4⑥/F9)**;分数公式与种子系数(lexical 2/entity 2/keyword 1/recency 0.25、halflife 86400)同草案;过渡分余弦项同换 `lexical_norm`。
**durable 且 D4 字节级比对的结构边只有 `temporal`**(`source_at ASC,content_hash ASC` 相邻对);**proximity 只在「无并发写入的同一索引快照上连续两次 rebuild」下要求相同**;关系 apply 只插该 rel 自己过阈的边,**不镜像** causes↔caused_by。
Gate:同池两次调用字节级相同;并列哈希小者先出;`==>` 次数闸门钉死。
已否决:B(body_tsv)——CJK 零召回。

**OQ8 候选进上下文 —— 裁决:B1(独立 evidence 函数);B2 不属于本 DP(不进 M4 可选分支)。**
依据:设计 §4.4 文档/记忆语料分区;并进 recall_candidates 会把记忆节点交给 chunk 过滤并改 csh;CAND4 闭集无 spans 文档语义;B1 不改装配,就不可能用记忆证据排除当前消息/规则/工具配对(§6.2 超集纪律);B2 要换活体 assemble/validate/context_required 并升 manifest——属下一张计划。
机制:只提供 `v13_mgraph_evidence(sid,query_hash)`;`query_hash=v13_body_hash(btrim(query))`;空查询返回空集零 ask;超长仍由 `v13_query_segments` 抛既有 V3005,不另造上限;返回 ≤`inject_top_k`,序 `score DESC,content_hash ASC`;**`read_enabled=false` 或 freshness.degraded 时返回空证据、零 ask、带 `skipped`(disabled|degraded)**(读路径与 build 同跳过——P1 修正)。
Gate:recall_candidates 与图节点哈希交集为空;`v13_needed_judgments` 不含 `mem_`;前序 stage 文件哈希不变。删除 manifest 段/mgraph_gen/pending_walk/manifest v4 的 DDL 与 F7-B2。

**OQ9 预算策略行 —— 裁决:种子 JSON 采纳但删除 `type_label_min`;不建类型标签视图。**
依据:该键不是 `jev_mem_config.py` 默认值,v1 又没有任何动作读类型标签——留在种子里会逼实现者发明过滤器;四条类型 Noul 仍是证据(§6.1:证据可落库,动作另由策略授权);`consolidate_max_body_bytes=32768` 是 v13 本地护栏(对齐 `summary_accept.checks.max_body_bytes` 量级,非 Jev-Mem 默认值),检查需要它,保留并注明来源。
机制:活动行与删键后 JSON 全等;权重和=1;形状违例 `v13_mgraph_policy()` RAISE V3009;第二 active 行被拒;函数体不写 0.60/20/5/0.85 等动作阈(0/1 域校验除外);`maximum_jev_calls` 只约束一次 read walk;**写路径受三帽:write_max_asks(每次 build)+write_max_batches(每 tick)+judge_spend(会话/日),同 ask 批单位,共同下游 judge_spend**——Oracle 审核 P1-9 与 §3.2/不变量 13/D11 对齐;类型四 Noul 照常落库,v1 无谓词读它们。

**OQ10 实体抽取 —— 裁决:A(SQL 英文正则+CJK 空集)。**
依据:B 把实体交给 Jev——CJK 判断更差(作用力 5)且写路径调用翻倍;C 把生成 IO 放进写路径多一趟 effect;抽取是纯投影;年正则有捕获组缺陷不移植。
机制:`v13_mgraph_entities` 只匹配 `^[A-Z][a-z]+$` 减 `entity_stopwords`;CJK 段返回 `'{}'` 不跑正则不 RAISE;`mem_rel_*::entity` 仅当两侧实体集都非空且交集为空才进 needed;关键词只取 `[A-Za-z0-9]+` 频次顶 `keyword_cap`,CJK 段不贡献;停用词表可先 `[]`。Gate D7 维持。

**OQ11 缺省三态 —— 裁决:A(写/固化 exclude,读 degrade,停止缺失不提前停)。这不是 fail-open。**
依据:设计 §6.1 缺失/超时/review 走版本化默认分支,默认分支不是「当成 yes」;插边和合并是动作,没有证据不得授权(与 summary_accept 全 exclude 同向);读路径已有结构分,MAGMA 回退对应物=该结构项,不是伪 Noul;停止也是动作——缺停止信号不得宣称证据够,也不得提前放弃,硬顶是 SQL 短路(§6.7)。
机制:恰好六个 point:`mem_relation`、`mem_type`、`mem_cons`、`mem_traversal`、`mem_stopping`、`mem_routing`。前三+routing 三态=exclude;traversal 三态=degrade(丢该 λ 分量,其余正权重重归一;全部分量都缺则分数 0 仍留 frontier 按 content_hash 排;basis 记 `default_*`);stopping 三态 exclude 的含义=**不参与停止**,硬顶照常;review **不建 human effect**;迟到 decision 只允许随后的 apply 补插从未写过的边,不 UPDATE 旧边,`status=stopped` 的 walk 不因迟到信号重开;读取器缺 point/缺态 RAISE V3009;**禁止伪造 0.5,禁止放宽 `CHECK(origin<>'jev' OR decision_id IS NOT NULL)`**(B 支的 CHECK 放宽删除)。

**OQ12 闸门族 —— 裁决:A(新族 `G-mg`)。**
依据:G-ctx10-* 已被控制面占用;续号与未写完的控制面闸门冲突;名字不改变 DDL。
机制:README 交叉引用(崩溃重跑≈G-ctx8 精神、已写边不回写≈G-ctx9);断言编号只用 G-mg/组 A–F;不新增 G-ctx11。

### 1.4 不变量(违反即设计背离)

1. Jev 只产带模板版本的 evidence 行;插边、分预算、停止、采纳合并的谓词只读 `v13_policy('mgraph')` 与 `judgment_defaults`。
2. 三 epoch:本 DP 动作承重判断全部 `pre-finalize`;`post-execute` 不回写节点/边/已冻 manifest;缺判断走默认分支,不回填伪概率。
3. 任何 `v13_mgraph_*` 函数不 `FOR UPDATE sessions`、不调 `v13_append_event`、不调 `typesafe_ask`;判断 IO 只出现在 resolve 角色调用的 `v13_resolve_judgments` 里。
4. 生成(合并后新正文)只以 `mgraph_consolidate` effect 存在,由测试驱动或 worker `v13_complete` 交回;**禁止 kind=llm / context_summary**(P0)。
5. 图的外部键=content_hash;重建 episodic 投影 DELETE 后重灌,关系判断走 `judgment_cache`,毒化端点下 `failed=false` 且本轮 asked=0。
6. `consolidation` 来源节点与边不在 episodic 重建里删除(正文来自生成,不是投影)。
7. 一个信封=一个 state;一对节点关系题可同批;不同 pair、或「类型题 vs 关系题」分多次 `v13_resolve_judgments`;**每个 mgraph 信封的 `batch_questions`=该信封问题数(同 state,上限 32)**——不得照抄摘要信封的 1,否则四题拆四次 ask 提前耗尽 calls=10(P1)。
8. 哈希材料不含 `now()`/`created_at`/lease/水位/mock GUC;时间特征只用从源事件复制的 `source_at`。
9. 节点/边 DML 不 bump cgr、不改 probe 七键;模板种子在**加载事务内**经行级触发器逐模板 bump(每个 INSERT 与 freeze 各一次;cgr 探针/在途回合只见一次失配——Oracle 审核 P2-3 校准)。
10. `v13_needed_judgments` 源码在本 stage 加载后仍不含 `mem_`。
11. SQL 源码不含 `mock_response`/`set_config`/`pg_net`/`dblink`/`COPY PROGRAM`。
12. 策略数值只从 `mgraph` 行读;函数体不出现 0.60/20/5/0.85 等字面阈值(形状校验的类型域除外)。
13. **游走与用户回合共用 `v13_judge_spend`,每轮先查,over 则零 ask;禁建第二花费账;禁为游走预留整包调用数饿死回合**;**写路径另受独立 `write_max_asks` 帽(每次 build 的 ask 批数,含失败批),防首建大 transcript 吃穿 session_asks_cap 封死用户回合**(P1-1)。
14. **`mem_%` 行落 decisions 不改活体 `v13_context_required` 的 `dec` 计数定义**——落行会触发下一次装配 token 失配一次 refresh,属已知代价,README 写明;默认双 false 下零发生(P1)。
15. **`mem_route` signal 的 `<graph>` 份必须包含 mgraph_generation**(`<graph> ::= <图名>@<mgraph_generation>`):v13_gap 是 signal 级吸收,signal 不含代数则翻代后同 query 的 routing 判定被 gap=0 吸收、复用旧答案,图增长对 routing 永不生效(交叉确认 P1-3;不变量 15)。

### 1.5 接口契约

| 边界 | 现状所有权 | DP9 碰它的条件 |
|---|---|---|
| `v13_needed_judgments` | 路由五问+工具参数 | 不碰 |
| `v13_resolve_judgments` | 唯一 ask/缓存/落行 | 只调用不换体 |
| `v13_advance`/probe 七键 | 回合推进 | 不碰 |
| `v13_recall_candidates`/CAND4/装配/校验器/context_required | 文档语料/清单 | 不碰(B2 属下一张计划) |
| `transcript_chunks` | 逐字投影 | 只读,当 episodic 源 |
| `effects.kind`+cap | 六值 | M4 扩第七值 `mgraph_consolidate`(OQ6) |
| `v13_requeue_stale` | judge 回 ready/其余 unknown 墙 | M4 窄 OR REPLACE(活体,仅 mgraph_consolidate 加入 judge 待遇) |

判断族 signal 形状(signal 是稳定判断身份,进 decisions.signal 与缓存键):

| 模板族 | kind | 投影 | signal 形状 |
|---|---|---|---|
| `mem_type_episodic/semantic/procedural/preference` | noul×4 | `["body"]` | `mem_type::<node_hash>::<label>` |
| `mem_rel_semantic/causes/caused_by/entity` | noul | `["left","right"]` | `mem_rel::<src>::<dst>::<rel>` |
| `mem_routing_`+六名 | noul | `["query"]` | `mem_route::<query_hash>::<graph>@<mgraph_generation>` |
| `mem_trav_relevance/relation_usefulness/new_information/supports` | noul | `["query","candidate","path"]` | `mem_trav::<walk_uuid>::<node_hash>::<aspect>` |
| `mem_stop_sufficient/missing/contradiction/continue` | noul | `["query","evidence"]` | `mem_stop::<walk_uuid>::<round>::<aspect>` |
| `mem_cons_*`(OQ6) | noul/choice | `["left","right"]` 或 `["source","summary"]` | `mem_cons::<pair_digest>::<aspect>` |

`pair_digest = v13_body_hash(src_hash || '>' || dst_hash)`(输入已是哈希,稳定)。

---

## 2. 证据基线与输入映射

### 2.1 Jev-Mem 可移植核心(源码快照 commit=main@2026-09-23)

- **可移植**:六组问题模板全文(`jev_questions.py:284-427`);确定性候选发现公式(`jev_mem_policies.py:502-526`);最大余数预算分配(`:594-618`);检索环控制序(routing→allocate→anchors→{stop→propose→traversal→score→beam}→top_k,`jev_mem_retrieval.py:19-198`);关系插边阈与方向语义(`:578-591`);固化五问+非破坏合并+升级阈(memory_builder.py:228-292);过渡分五元组+新近度调整;配置默认值(`jev_mem_config.py:12-47`)。
- **不可移植(§8 台账)**:非 Jev 重排器(LoCoMo 过拟合:Mel↔Melanie `query_engine.py:1452-1456`、dia_id+50、会话号表 `:169-182`);死代码 `_multi_stage_entity_retrieval`(:1860-1981)/`decompose_and_answer_multi_hop`(:1982-2108,零调用方);`get_adaptive_params` 八类型表(:371-475,英文 only);benchmark 全家;mock_encoder;进程内 LRU/JSONL 审计/客户端 CallBudget(由 judgment_cache/judgment_calls/策略帽替代);LLM episode segmenter。
- **CJK 全盲台账**:`\b[A-Z][a-z]+\b` 系正则、英文停用词/月/星期表、`\w+` 切分、`question.lower()` 子串意图——全部进 §8 触发台账。

### 2.2 v13 接缝(复用面)

decisions 平面(session 唯一+answer 一次写+ASCII 题面,`v13_core.sql:393-440`);全局 `judgment_cache`+`judgment_calls`(envelope:152-191);模板 draft→freeze→cgr bump(envelope:14-88,136-146);**批=一次 `typesafe_ask(state,questions)`**,无 ask_many;mock GUC 非空短路/NULL 关/`typesafe_last_request()` wire 可断言;`v13_resolve_judgments(env,max_batches)`(活体=**filter 代** `v13/filter/v13_filter.sql:603`,其 typesafe_ask 直调在 :716;envelope:623-852 是中间代——见下方活体坐标表)两参咨询锁 `v13_lock_key(sid,csh)`(resolve:410-420);`v13_recall_candidates` 单一候选来源+recall_k(recall:173-217,751);`transcript_chunks`+水印+`v13_transcript_recall`(memory:18-165);filter 三态先例(filter:117-144,1238-1245);CAND4(filter:963);manifest v3+三种回放语义(fresh/recompute=mode CTE;exact_replay=`v13_replay` manifest:915-920;spawn_kind 三值 periphery:45,318);summary 验收带 v3 全套 API(summary:22-368);`judge_spend_gate`(economy:49-53,202);`v13_context_required` 的 `dec` 键=活体 periphery:191(economy:332 为死代,语义同为 answered decisions 计数);effects 六 kind+single-active+enqueue/claim/complete fence(core:96-390;llm 分支无条件写 `llm/message`:373);requeue judge-only 回 ready、其余 unknown 墙(twophase:36-86);策略行翻版仪式(core:701-744);latches/前缀身份(periphery:15-170)。

**活体坐标表(实施第 1 步导出对象;最后一次 OR REPLACE 所在处,评审 S1 更正)**:

| 函数/约束 | 活体 file:line |
|---|---|
| `v13_resolve_judgments` | filter:603(typesafe_ask 直调 :716) |
| `v13_filter_ask`(另一直调点) | filter:329 |
| `v13_judgment_envelope` | filter:485 |
| `v13_assemble_manifest` | periphery:688 |
| `v13_manifest_validate` | periphery:1458 |
| `v13_context_required` | periphery:191(十一键;`dec`=answered decisions 计数,两代语义一致) |
| `v13_requeue_stale` | twophase:33(全树唯一定义) |
| `effects_kind_check` | core:99+summary:27(六值) |
| `effect_attempt_cap` 活动行 | summary:33(六键仪式) |
| `v13_body_hash` | chunks:13 |
| `v13_judge_spend` | economy:202 |
| `v13_attempt_ok` | core:196 |

### 2.3 既有裁决约束

设计 §8 age 排除(`:458`)+元原则三条(`:462-466`)+触发(`:583`);A21 递归=STABLE SRF 非 VIEW 非物化(R2:245,268);§6.1 证据/动作分离+manifest freeze+三 epoch;§6.2 触点 5;§6.7 不整合清单;§4.3 快路批上限;作用力 3(持锁不堵 events);v13.1 三区 corpus+零继承注册+远程层未实现(=DP9 固化产物的立法空间);errata E1/E2;DP6 记忆语料独立表先例。

### 2.4 AGE 外查(2026-09-23)

pgembed 0.3.0rc2(wuxianliang fork,PG18.4)已打包 AGE 钉 PG18/v1.8.0-rc0(commit e43dc1a12b),免 preload、Apache-2.0、musl 也带。1.8.0 能力:自动 vertex/edge-endpoint 索引、属性 GIN/BTree 表达式索引、VLE 内部执行器(固定选择性)、shortest_path SRF。缺陷:pin 后才修 VACUUM FULL 陈旧 TID(#2551,2026-08-26)与每行内存泄漏(#2517,2026-09-14);仍开放 #2465/#2179/#2486/#2520。成熟度:ASF 活跃、4.8k star。形态错配:Jev-Mem 遍历=有界逐轮一跳,非 VLE/最短路。

### 2.5 输入§映射(设计条款/Jev-Mem 代码 → 本计划落点)

| 来源 | 落点 |
|---|---|
| 设计 §4.4 三层栈·第三层 | §1.1(远程层=consolidation 节点)、OQ6 |
| 设计 §6.1 证据/动作分离+freeze | §1.4 不变量 1/2、OQ9/OQ11 |
| 设计 §6.2 触点 5 | OQ3 |
| 设计 §6.4 摘要回退链精神 | §3.4 固化(rejected 不重问同正文) |
| 设计 §6.5 批共享 state | 不变量 7、§3.3 信封构造器 |
| 设计 §6.6 shadow 重路由 | §3.1(旧边不重写;阈值变=新策略重放 raw answer) |
| 设计 §6.7 不整合清单 | §8 |
| 设计 §7 T0/T1 | OQ7 |
| 设计 §8 元原则 | OQ1(AGE 台账三条件) |
| 设计 §12 语义决策缓存台账 | §1.1(DP9 不动 ix_decisions_question_stannum) |
| `jev_questions.py` 全部模板 | §3.3 题面槽位+快照闸门 |
| `jev_mem_policies.py:502-526` 候选发现 | OQ7 公式 |
| `jev_mem_policies.py:594-618` 预算分配 | §3.4 allocate |
| `jev_mem_retrieval.py:19-198` 读环 | OQ2=B1+§3.4 停止/过渡 |
| `memory_builder.py:228-292` 固化 | OQ6+§3.4 固化链 |
| `jev_mem_config.py:12-47` 默认值 | OQ9 种子 JSON |

---

## 3. 数据模型与 SQL 草案

### 3.1 表(OQ1=A 形态)

**`memory_nodes`**

| 列 | 约束 |
|---|---|
| `session_id` | FK→sessions |
| `content_hash` | `CHECK = v13_body_hash(body)`,64 hex |
| `body` | `octet_length>0` |
| `origin` | `episodic \| consolidation` |
| `source_hashes` | text[],元素 64 hex,consolidation 时 `cardinality>=2` |
| `source_at` | episodic 必填(复制源事件时间);consolidation=两亲本较晚者 |
| `builder_version` | int=活动 mgraph version |
| `consolidation_key` | text 可空;合并节点必填,`UNIQUE(session_id,consolidation_key)` 部分索引 |
| PK | `(session_id,content_hash)` |

无 seq 列、无 corpus 列、无指向 chunks 主键的 FK;UPDATE 触发器拒绝;DELETE 仅 owner(不 GRANT)。

**`memory_links`**

| 列 | 约束 |
|---|---|
| `session_id`,`src_hash`,`dst_hash` | 64 hex;不建重建会坏的强 FK;校验器查悬空 |
| `rel` | 闭集 `semantic\|causes\|caused_by\|entity\|temporal\|proximity\|contradicts\|redundant_with\|related_to` |
| `origin` | `jev\|temporal\|proximity\|consolidation` |
| `decision_id` | uuid 可空,须属本 session;`CHECK (origin<>'jev' OR decision_id IS NOT NULL)`(OQ11 裁决:不放宽) |
| `structural` | numeric 可空,结构边确定性分 |
| `policy_version` | 写入时 mgraph version |
| PK | `(session_id,src_hash,dst_hash,rel,origin)` |

UPDATE 拒绝;Jev 边只插不改写;阈值变了用新策略版本**重放 raw answer**(§6.6 语义),v1 apply 只读当前策略不自动重写旧边,旧边留待 episodic 重建;**关系 apply 不镜像 causes↔caused_by**(OQ7 裁决)。

**`memory_walks`/`memory_rounds`**:walk 唯一 `(session_id,query_hash,mgraph_generation,policy_version)`,列 frontier jsonb/budgets jsonb/calls_used/nodes_used/edges_used/depth/stop_reason/status∈open|stopped;round PK `(walk_id,round)`,重放已存在 round 返回原 frontier_out 不再扩展(重复投递吸收点);`status=stopped` 不因迟到信号重开。

**`v13_mgraph_meta`**(每会话一行;**初值 watermark=-1、rel_cursor=NULL——Oracle 复核 P1**):`session_id` PK、`generation bigint`、`transcript_watermark bigint`、`rel_cursor text` 可空(=最近一个「类型问+关系问全部落账」的 episodic 节点 content_hash——写路径缺口续跑游标,Oracle 审核 P0;为空=从未发问)、`nodes_since_consolidate int`(v1 manual 模式不消费);generation 在一次 build **结束时**有行变化才 +1(不在每行触发器里 +1;B1 下不进 context token);**cursor 与 watermark 同一批提交:正常完成与帽尽同一路径——build 收尾一律先把 cursor 推到「类型+关系问全部落账」的最后一个节点(全部完成=本次末节点;帽尽=断点),再把 watermark 推到该节点对应 transcript seq(游标前缀语义,watermark 永不越过未发问节点——Oracle 复核 P1 闭环)**。

**`memory_consolidations`(固化队列表,Oracle 审核 P1-4+复核 P1)**:`(session_id, consolidation_key)` PK(**同 key 至多一行——无「新正文新行」,重试语义由 effect attempt 承载**);`consolidation_key=pair_digest`;列 `status ∈ queued|generating|adopted|rejected`、`effect_id uuid` 可空、`body_hash text` 可空(settle 时回填,仅作审计记录)、`decided_at`;**这是「rejected 可审计」的载体——effects.status 闭集(ready|claimed|succeeded|failed|unknown|cancelled,core:14-15)无 rejected**;**失败收敛:驱动侧固化 sweep 在 enqueue 前检查 generating 行对应 effect 终态——failed/cancelled/超 cap→行置 rejected(谁落状态:下一次 sweep 或 settle 探测 effect 非 succeeded 即 rejected;不建 abandoned 第四态——Oracle 复核 P1)**;选对排除条件=仅 `status='adopted'`(rejected 允许重新入队:行回 queued,重走 enqueue——被永久跳过的只有已采纳对);worker 重试(新正文)在 effect attempt 循环内,不换 queue 行。

**结构边(无 Jev)**:`temporal`=同会话 episodic 按 `source_at ASC,content_hash ASC` 连相邻对(D4 字节级 durable);`proximity`=候选分≥派生门槛(`lexical_norm>=graph_activation_threshold`)时插,`structural` 记该 lexical_norm(门槛用已有键;相同性只在同索引快照无并发写入的双 rebuild 下要求——OQ7 裁决)。

### 3.2 策略行与默认分支

`mgraph` v1 种子(OQ9 裁决后;函数只读此行,放宽=新 (name,version) 行+同事务翻 active):

```json
{
  "relation_threshold": 0.60, "candidate_top_k": 10,
  "total_graph_budget": 20, "probability_exponent": 1.5,
  "graph_activation_threshold": 0.15, "beam_width": 5, "maximum_depth": 5,
  "maximum_nodes": 30, "maximum_edges": 200, "maximum_jev_calls": 10,
  "max_latency_ms": 15000,
  "transition_weights": [0.25, 0.35, 0.15, 0.15, 0.10],
  "transition_recency_coef": 0.10,
  "evidence_sufficient_min": 0.85, "missing_stop_hi": 0.40,
  "contradiction_stop_hi": 0.40, "continue_min": 0.40,
  "consolidation_threshold": 0.85, "consolidation_choice_min": 0.85,
  "consolidation_priority": ["contradiction", "redundant", "link"],
  "lexical_coef": 2, "entity_coef": 2, "keyword_coef": 1,
  "candidate_recency_coef": 0.25, "candidate_recency_halflife_s": 86400,
  "keyword_cap": 15, "write_enabled": false, "read_enabled": false,
  "admission_enabled": false, "routing_mode": "deterministic",
  "routing_shadow": false, "write_max_batches": 8,
  "consolidate_mode": "manual", "consolidation_interval": 0,
  "deterministic_floor": 1, "inject_top_k": 5,
  "entity_stopwords": [],
  "consolidate_max_body_bytes": 32768,
  "write_max_asks": 64
}
```

(`consolidate_max_body_bytes` 来源=v13 本地护栏,对齐 summary 检查量级;**三帽同为 ask 批数单位**:`maximum_jev_calls`(一次 read walk)/`write_max_batches`(每 tick)/`write_max_asks`(每次 build),共同下游=同一 `judge_spend`(批)——非第二套账(评审 3.3 消歧);`maximum_jev_calls` 计数单位=批/ask 信封数,非问数——与 Jev-Mem CallBudget 调用数语义一致(交叉确认 P1-2);**`consolidate_mode` 非 'manual' 值与 admission 同向 RAISE V3009**(v1 无实现即配置错误,评审 S6;三类策略键纪律=真有实现的/保留但响亮的/闭集成员,无「保留但静音」类);`nodes_since_consolidate` 列保留、v1 不自增。)

形状校验(权重 5 个和为 1、阈值∈[0,1]、计数正整数、interval≥0、mode 闭集、priority 数组为三值排列)违例→`v13_mgraph_policy()` RAISE V3009。`judgment_defaults` 追点=在既有 point(chunk_score/corpus_exists,filter:1240;summary_accept,summary 侧)**之外新增且仅新增 OQ11 六个 mem_ point**(翻后共九 point),翻版 DO 块照 `$dp7def$` 形态;读取器 `v13_mgraph_defaults_action` 缺点/缺态 RAISE V3009。

### 3.3 判断族注册(不动 needed)

仪式:父表 draft→内容行→freeze;`epoch='pre-finalize'` 显式写入(列默认 pre-bind);projection 禁 `["*"]`;writer/wire/canon=`v13_resolve`/1/1;题面在 SQL 里=入库快照对应槽,闸门文本全等。

题面槽位(源行号;文字只来自 `QUESTION_SNAPSHOT.md`):关系四问 `jev_questions.py:336-353`;固化五问 `:356-379`;routing 六问 `:382-396`;stopping 四问 `:399-413`;traversal 四问 `:416-427`;类型四 Noul `:314-333`;停用词表 `memory_builder.py:308-315`。

信封构造器 `v13_mgraph_envelope(sid,state jsonb,questions jsonb)→jsonb` 键集**对齐活体 `v13_summary_envelope`**(summary:176-368):`sid,ctx,needed,templates,groups,budget={batch_questions},timeout_ms,candidate_set_hash,provider,model,goal_hash,candidates`;candidates 恒 `[]`;`candidate_set_hash`=本批 signal 集合+state 的 sha256(不是文档召回 csh;**P2 注记:与文档召回 csh 同列异义,既有按该列分组的花费分析会混流——README 运维注记写明,不改列**);groups 恰一元素;provider/model 经 `v13_guc_required`;**`batch_questions`=该信封问题数(同 state,上限 32),不照抄摘要的 1**(不变量 7/P1)。实现第一步验证:periphery 库对活体 `v13_resolve_judgments` 做一次成功空批调用(gap=0);**filter 代活体必读 `goal_hash`(须 64hex)与 `candidates`(须 array),缺任——即 V3006**(`v13_existence_ref` filter:51-59、`v13_filter_bodies_present` :200-202、resolve `remaining` 尾部 :942 无条件调用——函数名按实码,Oracle 审核 P2-2 校准)——故 mgraph 信封恒带 goal_hash 与 candidates=[](非可选,非「多键无害」)。

### 3.4 算法

**allocate `v13_mgraph_allocate(weights)→jsonb`**(纯/STABLE/无 IO):桶闭集字典序即并列终裁序 `causal,entity,multi_hop,recency,semantic,temporal`;确定性/superset 模式传非负实数,jev 模式传六 Noul(低于激活阈改 0);全 0→superset 六桶=1,否则 RAISE V3009;Hamilton 最大余数:quota=B·w^e/Σw^e,floor+小数降序+名字升序补齐;权重>0 桶 base=0 时从当前最大且≥2 的桶借 1(并列名字升序),借不到 RAISE V3009(仅 B<激活桶数;种子 20/6 不会);返回六键整数和=B。**配额单位=该图型可拉取的邻居节点数(候选扩展次数,Jev-Mem used[graph] 语义;非边数非 ask 数——Oracle 审核 P1-2 钉死)**。

**一跳过渡**:邻居只来自 `v13_mgraph_neighbors`,桶→rel 映射:semantic→{semantic,related_to,redundant_with,contradicts}(**固化子型边经此桶可达**);temporal→{temporal};causal→{causes,caused_by};entity→{entity};recency→{temporal}(source_at 近者优先);multi_hop→全部 rel 仍只扩一跳(深度由 walk.depth 计)。Jev 分量缺失且默认 degrade:该 λ 分量剔除、其余正权重重归一后点积;全缺→分数 0 仍留 frontier 按 content_hash 排;basis 写 round 行,不写 0/0.5 冒充。束:`score DESC,content_hash ASC` 取 beam_width;计入 nodes/edges/depth/calls_used(**每封发出即 +1,含 failed_timeout/failed_validation,缓存命中不加——与 OQ2/不变量 13/E5 同口径,Oracle 复核 P2**);任一硬顶→stop_reason=nodes|edges|depth|calls|latency。

**停止**(证据齐时):①sufficient≥evidence_sufficient_min ∧ missing<missing_stop_hi ∧ contradiction<contradiction_stop_hi→`evidence`;②否则 continue<continue_min→`continue`;③否则硬顶满→硬顶名;④否则 go。缺停止判断不进①②(OQ11:不参与停止,硬顶照常);两条件同时成立取 `evidence`。

**写路径 `v13_mgraph_build(sid,limit)`**:①write_enabled 假→`{skipped:'disabled'}` 零写;②admission_enabled 真→V3009;③freshness.degraded 真→`{skipped:'degraded'}` 零写;④咨询锁升级:驱动对**整次 build**取会话级 `pg_advisory_lock(v13_lock_key(sid,'mgraph-build'))`(结束释放);run_round 每轮的 `pg_advisory_xact_lock` 同 key 与之互斥(同 key 跨级互斥);**可见性口径:已提交前缀可读(节点/边/cursor/watermark 同批提交,读者见到的必是自洽前缀),未提交半截不可见——Oracle 复核 P2 措辞**;⑤watermark 后 transcript 行插 episodic 节点 ON CONFLICT DO NOTHING;**`source_at := events.at`**(经 `(session_id,seq_from)` 复合 FK 回查 `events.at`——transcript 无时间列,评审 S4;不变量 8 禁 now() 的唯一合规路径);**同 content_hash 折叠保留 source_at 最早者(等价按 seq 升序首现),增量与全量重建同序处理故字节级可再现(评审 S8)**;⑥**全部本批行插入后**:先 DELETE 本会话 `origin='temporal'` 边,再按 `source_at ASC,content_hash ASC` 全量重连(新节点落在两旧节点之间时旧跨接边必须消失——Oracle 审核 P1-1;D4 断言此集合),计分池=本会话全部 episodic(OQ7);⑦**发问从 rel_cursor 之后按插入序推进(Oracle 审核 P0)**:每节点先类型信封(四 Noul 一 state)→resolve→只记录;然后对该节点 body 先 `v13_build_tinql`→经 `v13_mgraph_candidates(p_sid, p_tinql, candidate_top_k)` 取对(调用点口径同 OQ7 签名——**不得把 body 直拼进 `==>`**,Oracle 复核 P1),每 pair 一封关系信封(entity 问仅在双方实体集非空且无交集时加入);spend.over、write_max_batches(每 tick)或 write_max_asks(每次 build 独立批帽)任一用尽→停在断点;**无论正常完成还是帽尽,收尾一律先把 rel_cursor 推到「类型+关系问全部落账」的最后一个节点(全部完成=本次末节点),再推 watermark——两列同批提交(Oracle 复核 P1 成功路径闭环)**;⑧`v13_mgraph_apply_relations`:扫本会话 `mem_rel::` answered 行,各 rel 独立过阈才插边 ON CONFLICT DO NOTHING(不镜像反向);⑨**watermark=rel_cursor 对应 transcript seq(与 cursor 同批,永不越过未发问节点)**,generation 同批。apply 与 resolve 分离=「decisions 已提交、边未写」崩溃窗:重入 apply 不 ask;build 重入:插入从 watermark 起、发问从 cursor 起,零重复 ask。

**读路径(B1)**:read_enabled 假或 degraded→evidence 空集零 ask 带 skipped(OQ8);真:驱动循环 `v13_mgraph_run_round(sid, p_elapsed_ms)`,每轮事务:①取 build 同款咨询锁(OQ2 机制);②open walk→`v13_mgraph_route`→allocate;③**首轮锚=`v13_mgraph_candidates`(同写路径函数,lexical top-k over episodic;consolidation 不作锚——Oracle 审核 P1-2)**;④对当前束候选发信封(每候选一封,state 含该候选正文)→resolve→apply_round→`v13_mgraph_should_stop`;⑤spend over/帽尽/超 latency→run_round 写 stop_reason(spend|calls|latency)与 status='stopped'(不空转)。**过渡分公式(系数只读种子,Oracle 审核 P1-2+复核 P1 单式化)**:`score = (λ₁·lexical_norm + λ₂·relevance + λ₃·need_g·relation_usefulness + λ₄·novelty + λ₅·(structural+supports)/2) / Σλ`,`score_adj = (score + transition_recency_coef·r·recency)/(1+transition_recency_coef·r)`(与 Jev-Mem 公式(25)同构,**唯一形态——乘法式已废**);符号定义:`r`=routing 的 recency 桶权重(确定性模式=主意图升权值,jev 模式=mem_route recency Noul);`need_g`=候选所经图桶 g 的 routing 权重;`recency = 1/(1+Δsource_at 秒数/candidate_recency_halflife_s)`(**halflife 键已是秒,勿再乘 86400——Oracle 复核 P1**);λ 下标映射=(lexical,relevance,use×need,novelty,support),写死于 §3.4 本处(§3.2 注指向此处);**候选发现分同块钉死(OQ7 公式入正文)**:`cand_score = lexical_coef·lexical_norm + entity_coef·entity_jaccard + keyword_coef·keyword_jaccard + candidate_recency_coef·recency`,lexical_norm=池内 bm25/max(bm25);**timeout/missing 判据(Oracle 审核 P1-3)**:apply 查该 signal 的 `judgment_calls.status='failed_timeout'`→basis=default_timeout;无 call 行→default_missing;`query_hash=v13_body_hash(btrim(query))`;evidence 出口以「当前 mgraph_generation+活动 policy_version」定位唯一 stopped walk,取 score DESC,content_hash ASC 前 ≤inject_top_k(无 walk→空集零 ask)。

**固化**:①选同会话、未被 consolidation_key 覆盖的节点对(source_at 近、哈希序,limit);②五问一封(同一 left/right state;representation 与四 Noul 同投影可同批);③apply 只读 decisions:**子型映射写死 contradiction→contradicts、redundant→redundant_with、link→related_to;obsolete 只作证据不入队不插边(不进 priority 数组——Oracle 审核 P1-5)**;choice∈{merge,promote} ∧ choice 概率≥consolidation_choice_min ∧ contradiction<consolidation_threshold 才允许生成;④入队:queue 行(queued)→route 侧 `v13_mgraph_consolidate_enqueue` 建 `mgraph_consolidate` kind effect(**幂等唯一权威=queue PK:同 key 行 queued/generating→不重复 enqueue;effect_id 用 `v13_enqueue_effect` 返回值,不自行推导——活体 `v13_effect_id` 还拼 last_user_seq/cycle_no,Oracle 复核 P2**),会话已有 ready|claimed|unknown 时返回 NULL(**闸面与 advance ① 一致(advance:261-264),强于摘要闸的 ready|claimed(summary:307-309)——评审 S9 更正先例;代价:会话一旦落 unknown 墙,v1 永不能再固化,README 运维注记**),queue 行→generating;⑤worker 交 {text} 后,**resolve 侧 `v13_mgraph_consolidate_settle(effect_id)`**(driver 在 resolve_login 调——route 只 enqueue/complete,resolve 只发问/插节点,角色交接 Oracle 审核 P1-4):读 effect.result→确定性检查(非空、字节≤consolidate_max_body_bytes、两枚亲本哈希仍在)失败→queue 行 rejected+body_hash 回填,零 fidelity ask→fidelity 信封→include 才插节点+固化边+queue adopted;非 include→rejected;**settle 幂等:adopted/rejected 行二次 settle 零 ask**;worker 重试(新正文)由 effect attempt 语义承载,cap 内重试不需新 queue 行(重试即新正文);⑥固化边 `(src=left_hash, dst=新节点 content_hash, rel=子型 contradicts|redundant_with|related_to, origin='consolidation')`(评审 S3;consolidation 节点不作候选锚,只经 semantic 桶遍历可达——远程层产品的 v1 读取路径)。

### 3.5 状态流、并发、失败

| 触发 | 路径 | 角色与事务 |
|---|---|---|
| owner/cron 或测试 | build | resolve_login,多事务,每批一次 resolve |
| 驱动(owner/cron tick 或测试;**B1 读环 v1 无生产入口——扫地非回合节拍,唤醒不靠队列,与 transcript tick 同哲学;下一张计划接装配**,评审 S2) | read rounds | resolve_login,每轮一事务 |
| 空闲调度 | consolidate | route_login enqueue(kind=mgraph_consolidate);worker complete |
| 用户 advance | 不进 mgraph 函数 | probe 七键不变 |

**walk/round 生命周期(v1)**:保留策略=不清理(README 呈报;行数按 query×策略版本无界增长,触发清理=下一张计划);会话终态(completed/failed/cancelled)时开放 walk 不再驱动;固化 effect 被 cancel ⇒ 队列行由 sweep/settle 收敛为 rejected(§3.1 失败收敛规则;不新起同 key 入队,重新入队=显式操作)。

乱序:round n+1 在 n 未提交时因 PK 与 frontier 读不到 n,不跳轮。重复:ON CONFLICT 与 round PK。丢弃:驱动崩溃重跑,缓存命中,边不双插。水位:build 不写 sessions/events,不打 stale 在途 advance;模板种子在加载事务内经行级触发器逐模板 bump(探针只见一次失配——Oracle 审核 P2-3);**mem_% 落 decisions 会使活体 context_required 的 dec 计数变化→下一次装配 token 失配一次 refresh(已知代价,不改 dec 定义——不变量 14;默认双 false 下零发生,README 运维纪律写明)**。

| 失败 | 行为 |
|---|---|
| 无冻结模板 | 信封 RAISE V3009,零行 |
| 策略缺键/坏形 | RAISE V3009 |
| ask 超时且调用方已声明 statement_timeout | resolve 返回 failed=true;judgment_calls 记 **failed_timeout**(活体状态名);apply 按该信号 timeout 默认;不写 resolve/failed |
| 未声明 57014 | 活体 α 上抛,本轮事务回滚 |
| V3001 坏答案 | resolve 子事务零落行 failed=true;不插边 |
| spend over | 跳过零 ask |
| 两构建并发 | 咨询锁串行;锁内 ON CONFLICT |
| 固化生成失败 | mgraph_consolidate effect failed 走 cap+窄 requeue(超 cap failed+lease_exhausted+wake);不插节点 |
| freshness degraded | build 与 read 同跳过 |

**重建**:owner `v13_mgraph_rebuild(sid)` DELETE 全部 episodic 节点 + **两端都不是 consolidation 节点的边**(按端点判定——不变量 6 的完整实现,比 origin 字段判定宽,评审 S7)→**watermark 置 -1 且 rel_cursor 置 NULL(两列一起复位——Oracle 复核 P1)**→build;毒化下第二次 rebuild:failed=false、asked=0、temporal 边集合字节级相同(前置:同文折叠裁定,§3.4⑤;proximity 只在同索引快照无并发写入的双 rebuild 下要求相同——OQ7);固化节点**及其所有关联边**不变。

### 3.6 装配接线(已裁)

OQ8=B1:本 DP 不改装配/校验器/context_required;记忆证据只经 `v13_mgraph_evidence` 出口。B2(manifest memory_graph 段/mgraph_gen/pending_walk/manifest v4)**已裁出本 DP**,属下一张计划——相关 DDL 与 gate 不进仓库。

---

## 4. 逐文件影响与实施顺序

| 文件 | 动作 | 原因 | 顺序 |
|---|---|---|---|
| `v13/load.py` | SQL_LOAD_ORDER 追加 mgraph/v13_mgraph.sql;STAGE_THROUGH["mgraph"]=15 | 追加纪律 | 与 M1 SQL 同一提交 |
| `v13/mgraph/v13_mgraph.sql` | 新文件:两表+索引、策略、六族模板、defaults、函数、ACL、可选 cron;M4 段含 kind/cap/窄 requeue | 全部行为 | M1→M4 逐段追加保持可加载 |
| `v13/mgraph/QUESTION_SNAPSHOT.md` | 上游 URL+commit+每槽 sha256+英文原文逐字;未填测试红 | 题面不赝造 | M1 前 |
| `v13/mgraph/setup_db.py` | files_through('mgraph');stannum 探针;超时探针沿用 resolve 形态 | 独库 agent_v13_mgraph | M1 |
| `v13/mgraph/test_mgraph.py` | G-mg 组 A–F | 闸门 | 随里程碑加断言 |
| `v13/mgraph/README.md` | 阶段 15、库名、命令、机制、运维(含 dec-refresh 注记)、不做、回退 | 样板=memory README | 每里程碑更新 |
| `v13_requeue_stale`/effects CHECK/cap | M4 在新文件:kind 第七值+cap 七键+窄 requeue(活体 OR REPLACE,仅 mgraph_consolidate 加入 judge 待遇,其余 kind 字节不变) | OQ6 | 与首次 enqueue 同事务 |
| advance.sql/resolve/envelope/memory/装配族/设计稿/教程 | 字节不变 | 追加纪律 | — |

**ACL**(文件末尾,列举式 REVOKE;Oracle 复核 P1 补 settle 面):recall=SELECT 图+EXECUTE neighbors/evidence/allocate/policy 读;resolve=INSERT 节点/边/walk/round+EXECUTE build/envelope/apply/run_round/**v13_mgraph_consolidate_settle+SELECT effects(读 result)+UPDATE memory_consolidations**,无 append_event 无 enqueue;route=EXECUTE consolidate_enqueue+SELECT 图+**memory_consolidations INSERT/UPDATE**(队列写入面);rebuild/verify/DELETE 仅 owner;cron 降级照 memory 的 DO $cron$(不可用 NOTICE,函数仍手调)。

**源码扫描闸门**(组 C,对 v13_mgraph.sql):`typesafe_ask`=0;`v13_append_event`=0;`FOR UPDATE`=0;`mock_response`=0;`cypher(`=0。**typesafe_ask 全树真实分布(终版,Oracle 审核 P2-2 校准)**:直接调用点=①各代 `v13_resolve_judgments` 定义体内(resolve/envelope/filter 三代;活体在 **filter:716**);②`v13_filter_ask`(filter:**329**;DP6 既有形态)。advance/core 的命中均为注释;`v13/demo/sql/demo_api.sql` 仅注释且不入 SQL_LOAD_ORDER。闸门只对 v13_mgraph.sql 断言=0,效力不变。

**实施顺序**(七步):
1. **验证活体(只读)**:periphery 库导出 `v13_resolve_judgments`/`v13_assemble_manifest`/`v13_manifest_validate`/`v13_context_required`/`v13_requeue_stale`/`effects_kind_check`/活动 cap 键集/`v13_body_hash`/`v13_judge_spend` 定义;确认摘要信封对活 resolve 零缺口;确认无第二处 requeue_stale。
2. **题面快照**:从上游 commit 抄入 QUESTION_SNAPSHOT.md(文件头记 URL+commit+克隆日期);摘不到停在本步;停用词可先 `[]`;论文间隔数字只记注一句。
3. **M1 原子提交**:load.py+两表/索引/策略/模板/defaults/ACL/**信封构造器 v13_mgraph_envelope(A9 依赖)**+A 组+README 骨架;种子同文件 BEGIN/COMMIT 包住(memory 同形);**只 CREATE TABLE,不 CREATE EXTENSION age**。
4. **M2**:build/apply/rebuild+D 组;write 仍默认关,测试用「INSERT 新版本+翻 active」打开测完翻回。
5. **M3**:route/allocate/round/stop/evidence+E 组(仅 B1 形态)。
6. **M4**:固化链 F 组;kind=mgraph_consolidate+cap 七键+窄 requeue 与首次 enqueue 同一事务(禁先扩 CHECK 后补 cap);跑 periphery/summary/twophase 全部 gate。
7. 每步 `files_through('mgraph')` 可加载;不保留 AGE 支骨架。

Oracle 落笔前可先做:第 1–2 步+策略行/模板族/defaults 读取器/信封构造器(与存储无关件)。

---

## 5. 里程碑与 gate(G-mg 族)

命令:`uv run python v13/mgraph/test_mgraph.py`(退出码 0=通过);库 `agent_v13_mgraph`;提交前跑本 stage+全部前序 gate;毒化零调用断言 `failed=false` ∧ asked=0(DP1 §4 纪律)。

**M1 暗库(A 组)**

| # | 断言 |
|---|---|
| A1 | 两表+两 btree+stannum 索引在;哈希自证 CHECK 拒坏哈希;UPDATE 节点/边 V3009;无 `cypher(` |
| A2 | mgraph v1 活动,键与 §3.2 JSON 全等;权重和=1 |
| A3 | 六族模板 frozen、epoch=pre-finalize、投影非 `["*"]`;题面与快照全等(**question 与 criteria(非 NULL 时)均逐字+sha256,评审 S11**);noul 族 criteria 按 v13 形状为 NULL——Jev-Mem 的 true/false 文本按快照组合规则并入 question |
| A4 | judgment_defaults 活动行=既有 point(chunk_score/corpus_exists/summary_accept)**之外新增且仅新增六个 mem_ point**(翻后共九;Oracle 审核 P1-6);缺态调用 V3009 |
| A5 | `pg_get_functiondef(v13_needed_judgments)` 不含 `mem_`;cgr 相对加载前增加 **≥1**(行级触发器逐模板 bump,N 模板 N 次同加载事务——评审 S13 更正「恰一次」表述) |
| A6 | recall INSERT 节点失败;resolve EXECUTE v13_append_event 失败;route EXECUTE typesafe_ask 失败(enqueue 类负面断言在 F10——函数 M4 才存在,Oracle 审核 P1-6) |
| A7 | 源码扫描 §4 五项 |
| A8 | 暗库:M1 加载后 decisions/effects/节点/边零新增(模板种子除外);**rel_cursor=NULL、watermark 未动**(游标初态,Oracle 审核 P0) |
| A9 | mgraph 信封 `batch_questions`=信封问题数(非 1)——夹具:四问类型信封恰一批(不变量 7/P1) |

**M2 写与重建(D 组)**

| # | 断言 |
|---|---|
| D1 | 开 write 后英文两节点 mock Noul≥阈→一条 jev 边,decision_id 非空且属本 session,边列只有哈希 |
| D2 | 低于阈→零 jev 边;temporal 边在且 decision_id 空 |
| D3 | V3001→零 jev 边、failed=true、节点仍在(节点不是判断的副作用) |
| D4 | 重建+毒化:asked=0、failed=false、**temporal 边集合字节级相同(前置:同文折叠裁定)**;proximity 仅同索引快照双 rebuild 相同;**consolidation 夹具节点及其全部关联边还在(按端点删除规则,评审 S7)** |
| D13 | source_at 与源事件 `events.at` 等值(经 (session_id,seq_from) 回查,评审 S4) |
| D14 | 重复正文夹具:同 body 两 transcript 行→单节点、source_at=较早者;重建后仍单节点同值(评审 S8) |
| D15 | write_enabled=false→build 返回 skipped:disabled,零写零 ask;翻开后正常(M2 收口,Oracle 审核 P1-6 拆位) |
| D5 | 两连接同时 build:decisions 每 signal 一行;第二连接锁后零 ask |
| D6 | build 期间另一连接 v13_append_event 成功且墙钟<5s |
| D7 | CJK 正文实体={};混合串不问 entity 关系;semantic 关系仍可问 |
| D8 | spend 帽置 0 的新策略版本:build skipped=spend,asked=0 |
| D9 | 杀掉「decisions 已写、apply 未做」事务后重入 apply:边补齐且 asked=0 |
| D10 | causes 过阈而 caused_by 未过→仅一条 causes 边(不镜像) |
| D11 | write_max_asks 耗尽→build 返回带缺口计数;**rel_cursor 停在最后完成节点且 watermark 未越过它**;下次 build 从 cursor 续问零重复 ask(夹具:第二次 build **新增的 decisions signal 均为首次未覆盖的节点/对——增量非空且无重复**,Oracle 复核 P1 措辞);夹具把 session_asks_cap 调低于 write_max_asks 后断言 write 帽先触发(默认 64<512 也先发,但显式夹具防误读) |
| D16 | 成功路径:两节点全问完(未触帽)→rel_cursor=末节点、watermark=其 seq(不为 NULL);重建夹具→watermark=-1 且 rel_cursor=NULL(Oracle 复核 P1) |
| D12 | **夹具先 routing_mode='jev' 问完 routing 六问,再翻 mgraph_generation**(确定性模式不产 mem_route 行——Oracle 复核 P1):翻代后同 query 的 mem_route signal 代数份变化→新 decision 行且 request_hash 不同,不复用旧 routing 答案(不变量 15) |

**M3 读环(E 组,仅 B1)**

| # | 断言 |
|---|---|
| E1 | allocate:手算夹具(含小数并列)与名字升序终裁一致;和=B;激活桶≥1 |
| E2 | 确定性 WHY→causal 权重最大;CJK→六桶≥deterministic_floor 且 routing asked=0;shadow 前后 frontier JSON 全等 |
| E3 | 束并列小 content_hash 先入;两次 round 的 frontier JSON 全等(**锁内单连接前提——Oracle 审核 P1-8**) |
| E4 | mock 充分/缺失/矛盾满足①→stop_reason=evidence;只拉低 continue→continue;**calls 耗尽→calls 且不再 ask(计数单位=批;首轮后 calls_used 恰=6:1 停止封+5 遍历封——评审 4 补正向数)** |
| E5 | timeout 默认:无伪造 Noul、无无 decision 的 jev 边、frontier 仍含结构邻居;**basis 判据=该 signal 的 judgment_calls.status='failed_timeout'→default_timeout;无 call 行→default_missing;失败批 calls_used 也 +1(Oracle 审核 P1-3)** |
| E6 | B1:游走全程 effects 计数不变、resolve/failed 不变、并发 append_event<5s、本函数不持该 session 元组锁 |
| E7 | max_latency_ms=0 策略版本:第一轮后 run_round 写 stop_reason=latency 且 status='stopped'(elapsed 由驱动传入——写入点钉死,Oracle 审核 P1-3) |
| E9 | 成功路径:当前 mgraph_generation+活动 policy_version 的 stopped walk 按 score DESC,content_hash ASC 取 ≤inject_top_k;无 walk→空集零 ask(Oracle 审核 P2-5) |
| E8 | read_enabled=false 或 degraded→evidence 空集零 ask带 skipped |

**M4 固化(F 组)**

| # | 断言 |
|---|---|
| F1 | contradiction 过阈→零生成 effect |
| F2 | merge∧概率过阈∧contradiction 未过→恰一个 `mgraph_consolidate` effect;**零 llm/message、零 turn/end、零 resolve/failed,路由不因此 finish**(P0 断言) |
| F3 | 确定性检查失败→零 fidelity decision |
| F4 | fidelity exclude→零新节点;两亲本仍在 |
| F5 | fidelity include→新 content_hash、source_hashes 两枚、原文边还在 |
| F6 | 第二次 consolidate 同 key:asked=0,节点不双插 |
| F7 | recall_candidates 与新节点哈希交集为空;`v13_needed_judgments` 不含 mem_;前序 stage 文件哈希不变 |
| F8 | cap 七键齐全(旧六键逐字);租约过期 mgraph_consolidate 回 ready 且 fence+1、attempt 不动;超 cap→failed+lease_exhausted+wake;其余 kind 的 requeue 行为字节不变;**窄 requeue 替换体的 cap 判定按行 kind 调 `v13_attempt_ok(kind,attempt_no)`(core:196),不硬编码 'judge'**(交叉确认 P2) |
| F9 | 可达性:从 episodic 锚出发的 walk 夹具能经 semantic 桶(related_to/redundant_with/contradicts 子型)抵达 consolidation 节点(评审 S3;consolidation 不作锚,但产物可读) |
| F10 | resolve EXECUTE v13_enqueue_effect 失败;resolve EXECUTE v13_mgraph_consolidate_enqueue 失败(has_function_privilege 断言;core:874-897 仅授 route——评审 S14+Oracle 审核 P1-6 挪位) |
| F11 | 队列表:settle 幂等(adopted/rejected 行二次 settle 零 ask);rejected 行 body_hash 回填;worker 重试走 effect attempt(新生成即新正文);obsolete 高分不入队零 effect(Oracle 审核 P1-4/P1-5) |

回归纪律:M1 提交前跑 schema…periphery;M2–M4 同;M4 因 kind/cap/requeue 改动,periphery/summary/twophase gate 同批必跑。**结构注记(评审 S16):各 stage gate 只加载 files_through(本 stage),前序 gate 结构上不加载 mgraph——回归护住的是 load.py 追加与既有行为零回归;若 summary/periphery gate 变红,绝不靠改其测试修(前序文件字节冻结)**。

---

## 6. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| mem_% 落 decisions→活体 dec 计数变→装配 token 失配一次 refresh | 不变量 14:不改 dec 定义;默认双 false;README 运维注记 | 关 write/read |
| 模板加载 bump cgr,在途回合一次 stale | 既有语义;重解析零 ask;README 写明 | 回退=丢弃 stage 库(bump 无法撤) |
| 归一化 BM25≠余弦,边集与论文数字不可比 | 系数显式进策略;闸门钉确定性不钉论文分数 | 新策略版本改系数 |
| 复用 llm/judge kind 的诱惑 | 不变量 4+OQ6 kind=mgraph_consolidate;F2 断言零 llm/message | — |
| cap 忘带齐七键 | ALTER CHECK/cap/requeue 与首次 enqueue 同事务;enqueue 缺键 RAISE;翻版后立刻 enqueue 夹具 | 翻回旧 cap 版本(先清该 kind ready 行) |
| 单活跃槽被固化 effect 堵回合 | 调度闸:已有 ready\|claimed\|unknown 返回 NULL(闸面与 advance ① 一致);**代价:unknown 墙后 v1 永不能固化(README 运维注记)** | consolidate_mode=manual 不调度;清墙后恢复 |
| 题面快照与上游漂移 | 闸门文本全等+文件头记 commit | 新模板 version,旧决策自然失配(只费钱) |
| 固化正文无法零外部调用再生 | 重建不删 consolidation 行;D4/F 闸锁住 | 手工删指定 consolidation_key |
| 活体 resolve 比摘要信封更严 | 实现第一步空批调用验证 | 补键,不改 resolve |
| 写路径池语义漂移(按到达顺序缩小池) | OQ7 裁决:插完再计分,池=本会话全部 episodic;gate 同池两次调用字节级相同 | — |
| 首建大 transcript 吃穿 session_asks_cap 封死用户回合 | 独立 write_max_asks 帽(P1-1)+README 运维评估注记;D11 闸 | 上调策略版本帽 |
| 整体回退 | 新目录+load.py 一行+DROP DATABASE agent_v13_mgraph | 前 14 stage 文件哈希不变 |

无持久化用户数据迁移(stage 库 DROP-CREATE)。

---

## 7. 教程映射(只登记不改)

| 位置 | 登记 |
|---|---|
| ch13 tick/扫地僧 | mgraph build 与 transcript sweep 同哲学:cron 非节拍器,关掉 advance 仍靠 settle |
| ch10 召回 | 文档 T0 仍 v13_recall;记忆图不进 recall_candidates(OQ8=B1) |
| ch7/设计 §4.4 | 图=记忆区关系投影;远程层首批产物=consolidation 节点 |
| ch15/设计 §8 | age 留台账,触发=OQ1 三条件(变长展开需求+pin 含五修复+元原则重审) |

不改教程正文、不改 `docs/designs/v13-context-on-pg.md`。

---

## 8. 明确不做(台账+触发)

| 项 | 触发 |
|---|---|
| LoCoMo 重排、Mel↔Melanie、dia_id 加分、会话号表、get_adaptive_params 表 | 不移植,无触发 |
| 死代码两函数、mock_encoder、评测脚手架、内存 LRU、JSONL 审计、客户端 CallBudget | 由 judgment_cache/judgment_calls/策略帽替代 |
| 英文实体/关键词/意图正则的 CJK 能力、bigram 列 | kohaku 漏召超设计 §4.6 阈值 |
| admission 五问热路径 | 花费账单成可见大头,或产品要求「不该记的不进图」 |
| consolidation_interval 自动计数 | 快照确认源码整数后策略 v2(论文附录数字只记注) |
| T1 嵌入、余弦恢复 | 固定评估集证明词法漏召(设计 §7) |
| **AGE 进核心** | **OQ1 三条件同时**:①热路径变无逐跳判断的变长展开/最短路且一跳 JOIN p95 实测不够;②pin 含 #2465/#2179/#2486/#2551/#2517(或等价);③刻画 gate 钉结构断言/单真相/无双写+元原则重审通过 |
| **B2:manifest memory_graph 段/mgraph_gen/pending_walk/manifest v4/装配活体改动** | 属下一张计划(OQ8 裁决);触发=本 DP 的 evidence 出口出现真实消费者 |
| 效用遥测驱动 λ、在线 learned 遍历、Jev 决定 cache scope/排序/停止动作 | 设计 §6.3/§6.7;反事实评估前不做 |
| 预取、emergent、改 needed_judgments、第四 corpus 字面量 | 设计 §12/硬约束 |
| 递归 CTE 或 VLE 作为热路径 | 轮间判断屏障在;调试 SRF 除外 |
| 读环进 v13_parse、会话锁、effect(OQ2-B2 游走形态) | 已否决;除非重开并改设计 §4.3 |
| 生产 SQL 出现 mock GUC | 硬约束 7 |
| 为过滤 mem_routing 模板 OR REPLACE v13_judgment_envelope | OQ3 裁决禁止 |

---

## 附录 A. 裁决执行表(Oracle 轮 1;对应原 14 项分歧点)

| # | 项 | 裁决 | 落点 |
|---|---|---|---|
| 1 | OQ1 图承载 | A;AGE 仅台账三条件 | §1.3-OQ1、§8 |
| 2 | OQ2 读环 | B1;A 维持否决;B2 删除 | §1.3-OQ2 |
| 3 | OQ3 routing | A;shadow 不计 calls_used | §1.3-OQ3、E2 |
| 4 | OQ4 节点身份 | (session_id,content_hash),无 corpus 列 | §1.3-OQ4、§3.1 |
| 5 | OQ5 admission | 不做;键 true→V3009;不预种子模板 | §1.3-OQ5 |
| 6 | OQ6 固化 | A,**推翻 kind=llm**,新 kind mgraph_consolidate(cap 七键+窄 requeue 同事务,complete 不改) | §1.3-OQ6、F2/F8 |
| 7 | OQ7 候选 | A+插完再计分/池=全会话/D4 只 temporal 字节级/proximity 快照限/不镜像反向边 | §1.3-OQ7、D4/D10 |
| 8 | OQ8 进上下文 | B1;B2 逐出本 DP | §1.3-OQ8、§3.6、F7 |
| 9 | OQ9 种子 | 采纳,**删 type_label_min**,不建标签视图;consolidate_max_body_bytes 保留注明来源 | §3.2 |
| 10 | OQ10 实体 | A;不移植年正则 | §1.3-OQ10 |
| 11 | OQ11 三态 | A(写/固化 exclude、读 degrade、缺停止不提前停);不伪造概率、不放宽 jev 边 CHECK | §1.3-OQ11 |
| 12 | OQ12 闸门 | G-mg 新族 | §5 |
| 13 | 固化并列序 | 确认:只在 consolidation_priority 数组,函数不写死 | §3.2/§3.4 |
| 14 | 重建不删 consolidation | 确认:DELETE 仅 episodic 节点 + **两端都不是 consolidation 节点的边**(按端点判定,与 §3.5/D4 同句——Oracle 审核 P2-4 同步) | §3.5 |

**Oracle 盲区五条(P0×1+P1×4)处置**:①P0 kind=llm→mgraph_consolidate(OQ6/F2);②P1 dec 计数→不变量 14+README 注记;③P1 读路径 degraded 同跳过→OQ8 机制/E8;④P1 batch_questions=问题数→不变量 7/A9;⑤P1 共用 judge_spend 每轮先查→不变量 13。

**第二通道交叉确认(2026-09-23,claude-opus-1m@xhigh;条件已全部执行)**:①typesafe_ask 分布断言更正(§4/附录 C.2)→已改;②`mem_route` signal 含 mgraph_generation→不变量 15/§1.5/D12;③写路径独立帽+计数单位钉死→write_max_asks 种子键/OQ2 机制/E4/D11。另收 P2×2:candidate_set_hash 同列异义注记(§3.3);窄 requeue 按行 kind 查 cap(F8)。

**设计评审轮(2026-09-23,design 代理;存证 `docs/reviews/v13-dp9-plan-critique-2026-09-23.md`,S1–S16 全部处置)**:S1 活体坐标表(§2.2)+filter 代必读 goal_hash/candidates(§3.3);S2 读环驱动具名+walk 生命周期(§3.5)+B1 无生产入口明写;S3 固化边三元组+可达性 F9+池注 consolidation 不作锚;S4 source_at=events.at 回查(§3.4⑤/D13);S5 批数单位/≈46 节点量级/asked_batches 键(§1.3-OQ2);S6 consolidate_mode 非 manual 同向 V3009(§3.2 注);S7 重建按端点判定(§3.5/D4);S8 同文折叠裁定(§3.4⑤/D14);S9 enqueue 闸先例更正 advance ①+unknown 墙代价(§3.4④/§6);S10 deterministic_floor 全向量规则(§1.3-OQ3);S11 criteria 入快照+A3 扩展(附录 B);S12 三枚签名回写(OQ1/OQ2 机制);S13 cgr≥1 措辞(A5);S14 两条 ACL 负面断言(A6);S15 引用精确化(§2.2);S16 回归结构注记(§5)。无推翻项;「未发现需推翻的计划机制」结论存证。第二通道对 §1.4 建议的第十五条已采纳为不变量 15。

## 附录 B. 题面快照槽位(QUESTION_SNAPSHOT.md 契约)

文件头:上游 repo URL+commit+克隆日期+**MIT License 版权行保留**;每槽=模板名+源 file:line+**instructions 与 criteria(true/false 文本)各自逐字+sha256**;v13 noul 形状 criteria=NULL——Jev-Mem 的 true/false 文本按**快照头部版本化的组合规则**并入单条 ASCII question(组合后字节即缓存键的一部分,闸门对组合后 question 做全等);闸门对 judgment_templates.question 做文本全等;**权威=本入库文件**(`/tmp` 克隆仅抄录来源,失效时从 commit 摘抄,摘不到 M1 红);停用词表(common_words,`memory_builder.py:308-315`)同快照进策略 `entity_stopwords`(可先 `[]`)。

## 附录 C. 对导出基线的核验修正(2026-09-23)

1. 导出提议错误类 V3008——核验 `v13/periphery/v13_periphery.sql` 已占 43 处 → DP9 用 V3009。
2. 导出称「全树 typesafe_ask 只在 resolve 定义文件」——核验终版(Oracle 审核 P2-2):直接调用点=①各代 `v13_resolve_judgments` 体内(活体 filter:716);②`v13_filter_ask`(filter:329)。advance/core 命中为注释;demo 仅注释不入加载序。闸门只断言 v13_mgraph.sql=0。
3. 导出 OQ9 JSON 无 `consolidate_max_body_bytes` 而固化算法用到 → 并入种子(32768,来源 summary 护栏,注明)。
4. requeue judge-only、manifest v3、effects 六 kind、judgment_cache 全局——核验属实。
5. Oracle P0(llm kind 污染)与 P1×2(dec 计数、batch_questions)——已对 `v13_core.sql:373`、`advance.sql:126-131`(实码;:71-73/:119 为注释——Oracle 审核 P2-1 校准)、economy context_required 核验属实后折入。
6. **Oracle 审核轮更正(2026-09-23,见附录 D)**:P0 写路径 ask 游标(rel_cursor,§3.1/§3.4⑦⑨/D11);P1×9——temporal 全量重连/读环公式与锚与单位/失败批计数与 timeout-missing 判据/固化队列表与角色交接/子型→rel 映射/A 组拆里程碑/TINQL 构造器接线/build-read 共锁/OQ9 三帽句;P2×5——finish 谓词实码 advance:126-131、v13_existence_ref 正名、filter:716 归属、cgr 行级措辞、附录 A#14 同步。全部断言经代码复验后折入。
7. **Oracle 复核轮更正(2026-09-23,续会话)**:P1×6——cursor/watermark 初值与成功路径闭环(§3.1/§3.4⑦⑨/重建/D11/D16);队列表 PK 单行化+失败态收敛(rejected,无第四态)+选对排除仅 adopted(§3.1);settle 的 ACL 面(resolve 读 effects/UPDATE 队列,route 写队列)(§4);过渡分单式化+符号定义+halflife 秒制+候选分入正文(§3.4);D12 改 jev 夹具;candidates 三参调用点(§3.4⑦)。P2×4——计数残留清理(§3.4 过渡句/§3.5 failed_timeout)、锁可见性口径(已提交前缀可读)、信封构造器入 M1 交付(§0/§4)、effect_id 用 enqueue 返回值(§3.4④)。

## 附录 D. Oracle 裁决记录

| 轮 | 日期 | 通道 | 状态 | 要点 |
|---|---|---|---|---|
| 1(规划生成) | 2026-09-23 | context_builder Oracle 组:lane1 cursor/grok-4.6 **failed**(provider_error:malformed modern model config option);lane2 grokBuild/grok-4.7-build-fast-xhigh 完成 | 完成(单 lane) | 实施规格基线(prompt-exports/oracle-plan-2026-09-23-145740-dp9-2e23dc-e0c1.md) |
| 1(设计裁决) | 2026-09-23 | ask_oracle Oracle 组:lane1 cursor/grok-4.6 **failed**(同 provider_error);lane2 grokBuild/grok-4.7-build-fast-xhigh 完成 | 完成(单 lane) | 十二 OQ 全裁+14 分歧确认+盲区五条;总裁决**有条件通过**,条件已全部折入 |
| 1(交叉确认,用户指定) | 2026-09-23 | agent_run·claudeCode:opus[1m]:xhigh(第二通道;claude-fable-5 通道 403 配额耗尽改用 opus-1m) | 完成 | 十二项裁决全部维持、零推翻、无新 P0;P1×4(写路独立帽/calls 计批/signal 含代数/扫描断言更正)+P2×2 已折入;总裁决**有条件背书**,条件①②③已执行 |
| 1(设计评审) | 2026-09-23 | design 代理(step-5-preview;对照导出基线+代码实地复核) | 完成 | S1–S16 全部处置入计划(附录 A 处置清单);无推翻项;存证 docs/reviews/v13-dp9-plan-critique-2026-09-23.md |
| 2(Oracle 审核,用户指定) | 2026-09-23 | ask_oracle review 模式:lane1 cursor/grok-4.6 **failed**(inactivity watchdog,第四次同通道故障);lane2 grokBuild/grok-4.7-build-fast-xhigh 完成(选区 16 文件/188k tokens 全量供给) | 完成 | 总裁决**有条件通过**;P0×1(写路径 ask 游标)+P1×9+P2×5,承重断言经代码复验后全部折入(附录 C.6);架构裁决全部维持 |
| 2(Oracle 复核,续会话) | 2026-09-23 | ask_oracle review 模式续 chat(选区刷新至 v1.1):lane1 cursor/grok-4.6 **failed**(第五次);lane2 grok-4.7 完成 | 完成 | 总裁决**有条件通过**;折入复核确认 P0/P1-1/P1-5/P1-6/P1-9/P2 落对;新擉 P1×6(成功路径不推 cursor、队列 PK 冲突、settle ACL、公式两式不等、D12 夹具、candidates 调用点)+P2×4,全部折入(附录 C.7) |

> 双通道补裁完成(用户 2026-09-23 指定):裁决=第一通道 grok-4.7 产出+第二通道 claude-opus-1m 独立复核背书,两者不同血统。P0 结论另由代码直接核验背书(`v13_core.sql:373`/`advance.sql:126-131` 实码/economy context_required)。
