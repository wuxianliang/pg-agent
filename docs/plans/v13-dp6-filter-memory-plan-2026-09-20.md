# v13 DP6: 过滤管道与三层记忆栈 — 实施计划

> 状态:修复轮 1(turn 28;L4 裁定 2P1+5P2,已并入 2P1+4P2:P1-1 digest 摘要材料改候选 content_hash 全集[D6 防回归]、P1-2 存在性键-态体缺守卫[C7/E6]、九处授权清单、G4 writer∥rebuild 死锁冒烟注记、附 B NOT IN 对齐、信号名保留声明;L3 七节全)。
> 设计输入:`docs/designs/v13-context-on-pg.md` §4.5(过滤管道)/§4.4(三层记忆栈)/§6.1(默认分支)/§6.2(触点边界)/§9(transcript_chunks 切片)/§10(G-ctx4+投影 p99)/§11/§12/§13(冻结禁改)。
> 评审输入:`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md` **F2(P0,已裁)**——存在性 Noul 缓存键必须含候选集维度(本 plan 立法+附 A #1 呈报设计未改);**F10(P1,DP6 范围内裁决)**——记忆栈水印新鲜度语义(fail-closed+滞后上界+当前 turn 直读,附 A #2);**F1(P0)**——过滤点默认分支表(judgment_defaults.points 填充义务,DP3 留给本 plan)。
> 撰写方式注记:context_builder 通道延续本日 ACP 故障先例(turn 13×2/18×4/22/25),经 brief 授权由主会话代行撰写;全部基座文档(DP1 全文 3092 行含 §1.3 契约表/§3.1–§3.6/§4/§5、DP2 全文 1744 行含 §1.4 DP6 行/§3.1–§3.9、DP3 全文 1658 行含 §1.4 DP6 行/OQ1/OQ4/§3.2–§3.5/校验器、DP4 全文 1564 行含 §1.4 DP6 行①–③/§3.1bis 锁协议、DP5 全文 1367 行含 §1.4 DP6 行①–⑦/§3.1–§3.2、设计稿全文、stepfun 评审全文、教程 ch10/ch13/ch5/ch15 相关节)已逐一通读并按契约消费。
> 用户裁决携带(loop memory turn 12):DP2–DP8 连跑到底、不再设检查点;验收线=双通道 L4 无 P0/P1。

## 0. 执行索引

| 项 | 内容 |
|---|---|
| **Goal** | 把 §4.5 过滤管道(存在性 Noul 先行闸整批[F2 立法:缓存键含候选集维度]+per-chunk Score+跨 session 缓存/reused_from+judgment_defaults.points 填充[F1])与 §4.4 三层记忆栈(结构化层 stannum 建在 decisions.question/逐字层 transcript_chunks 投影+F10 水印语义/分区分索引)落成 **两个 stage**:`v13/filter/`(SQL_LOAD_ORDER 第 10 位)与 `v13/memory/`(第 11 位),以 **G-ctx4 全部三断言** + F1 毒化默认分支 gate + F2 陈旧无答案 gate + F10 上一 turn 可召回性 gate + 投影 p99 gate 收口 |
| **Done when** | `uv run python v13/filter/test_filter.py` 退出码 0(A–H 八组全绿)且 `uv run python v13/memory/test_memory.py` 退出码 0(I–N 六组全绿);提交前 DP1 四 stage+DP2+DP3+DP4+DP5(两 stage)gate 全部复跑(各自库前缀切片,不受本两文件影响);收尾工件齐(load.py 第 10/11 位/两 README/映射表) |
| **Key files** | `v13/filter/v13_filter.sql`(全新增,第 10 位纯末尾追加)、`v13/filter/{setup_db.py,test_filter.py,README.md}`;`v13/memory/v13_memory.sql`(全新增,第 11 位)、`v13/memory/{setup_db.py,test_memory.py,README.md}`;`v13/load.py` 仅追加两行路径与 `STAGE_THROUGH["filter"]=10`、`STAGE_THROUGH["memory"]=11`,零改动既有文件 |
| **Dependencies** | 分解表:DP2/DP4/DP5;实际加载依赖 DP1–DP5 全部九文件(两 stage 库分别加载前缀 10/11 文件)。DP7(经济件)/DP8(latch/render)消费本 plan §1.4 契约 |
| **Size** | 两 stage 两里程碑;SQL 两文件(filter:34 条顶层语句=新函数 14+OR REPLACE 5+索引 2+种子 7+ACL 4+BEGIN/COMMIT;memory:17 条顶层语句=表 1+索引 2+函数 6+触发器 1+种子 1+DO 1+ACL 3+BEGIN/COMMIT);gate 两文件十四组(filter A–H/memory I–N,含两连接锁竞争、毒化三形态、p99 对比) |

---

## 1. 定位与边界

### 1.1 本 DP 在 v13 版图中的位置

DP6 是设计 §11 交付排序第 1 条「承重件先行」的最后一块:**过滤管道**(存在性 Noul+per-chunk Score)与 §11 清单未单列、但分解表权威指派给 DP6 的 **§4.4 三层记忆栈**。上游五 plan 已把地基打完:DP1 两阶段 advance+decisions 缓存面、DP2 判断信封+judgment_cache/calls/templates 族、DP3 manifest 骨架(judgment_defaults 策略行+epoch+消费集)、DP4 chunks 投影+锁协议+decisions chunk 引用路径冻结、DP5 信封 `candidates` 第 20 键(召回候选 parse 时冻结)+v13_recall 族签名冻结。DP6 落**判断的消费半边**:召回候选 → 存在性闸门 → per-chunk 评分 → candidates.decision_id/judgments 接线;以及**记忆的投影半边**:transcript_chunks 逐字层+水印+结构化层索引。

**双 stage 裁决(OQ1)**:`v13/filter/`(第 10 位)交付过滤管道;`v13/memory/`(第 11 位)交付三层记忆栈。依据:(a) 两个子系统输入面正交——filter 消费 DP2/DP3/DP5 契约(信封/缓存/装配),memory 消费 DP1 events/sessions+DP4 pg_cron 载体+DP5 刻画后库形态,互不依赖、可独立回退;(b) gate 剖面不同——filter 的 G-ctx4 走 mock 计数/毒化/跨 session,memory 的 p99 走两连接计时,合并会互相污染 fixture;(c) AGENTS 一里程碑一提交,两里程碑两 stage(DP5 双 stage 先例);(d) 分解表明文「若记忆栈分 stage 你裁决并写明」——本 plan 裁决分,先 filter(承重件)后 memory(§4.4 P1 件)。两 stage 库各自前缀切片(10/11 文件),DP1–5 各 gate 结构性不受扰。

**骨架(非全量)**:filter 不落 chunk manifest sections(候选→过滤→**段**的段半边——§5.2 section 结构只支持 section_id=kind 同名单段[DP3 校验器层 5],多 chunk 段需 manifest_version 2+校验器重做,分解表未指派给 DP6,缝发布给 DP7+,OQ7/附 A #5);memory 不落远程层(摘要 artifact 引用,§4.4 明文「不实现」)、不落语义决策缓存机制(§12 台账;结构化层只建索引留缝,OQ9)、不落更聪明的 tick/ch13 四 job 全景(requeue/recover 仍归驱动,附 A #8)。触点 5(intent 软门控)DP6 **零新增**——仅复用既有 intent 行的语义已由 DP1 落,为此新调 Jev 是 P2(§6.2 已裁,不做);触点 2(摘要验收)归 DP7(§7)。

**硬边界(零改动纪律)**:DP1–DP5 计划文件与其(未来的)SQL 文件零改动。对既有对象的变更全部为**授权换体、纯追加或契约预留缝**,共九处:①`CREATE OR REPLACE v13_judgment_hash`(DP2 §3.5 形态;分支分发,canonical 路径逐字保留);②`CREATE OR REPLACE v13_judgment_envelope`(DP5 §3.1 L6 二十键体;CTE 重排+needed 过滤行合并层,键集 20 键不动);③`CREATE OR REPLACE v13_resolve_judgments`(DP2 §3.6 体;canonical 半边逐字保留+filter 半边新增);④`CREATE OR REPLACE v13_assemble_manifest`(DP3 §3.4+DP5 L7 体;qside candidates 的 decision_id 填充+jud 消费集/final_action 真值);⑤`CREATE OR REPLACE v13_chunk_referenced`(DP4 §3.1 体;decisions 半边改 jsonb containment 等价形态以吃 GIN 索引——DP4 契约「届时补该路径的 GIN 索引」的使能半边,行为逐字节等价,附 A #6);⑥对既有表 chunks/decisions 各**追加一个索引**(ix_chunks_content_hash 非唯一——body 按哈希查找的读路径索引;ix_decisions_chunk_ref GIN——DP4 契约预留缝;零 DDL/约束改动,附 A #7);⑦`v13_policies` 表追加两行族种子(chunk_filter v1/judgment_defaults v2 翻 active——DP3 契约「DP6 填 points 值」的落点);⑧judgment_templates 追加两族行(corpus_exists/chunk_score,经 DP2 版本父表机制,epoch='pre-finalize'——DP3 契约预留列);⑨decisions 表追加 stannum 索引 ix_decisions_question_stannum(§4.4 结构化层明文指派;§3.2 memory 文件落——纯追加性能件可独立 DROP,单索引纪律;补计入授权清单,防按封闭清单对账失配)。前缀切片库不加载本两文件,DP1–5 库零影响(结构性,files_through)。

### 1.2 上游契约消费清单(逐条,来源:DP1 §1.3 / DP2 §1.4 / DP3 §1.4 / DP4 §1.4 / DP5 §1.4)

| # | 上游契约(原文要点) | 本 plan 消费方式 |
|---|---|---|
| 1(DP1) | **DP6 行:per-chunk Score 的慢路复用 `v13_resolve_judgments`(同一函数双速);「规范答案缓存 vs 本 session 使用记录」的 reused_from 拆分由 DP6 在 decisions 之上加映射,不改 DP1 列;DP1 唯一性=(session_id,request_hash),跨 session 复用的全局 canonical 层不改 DP1 约束语义** | 慢路=DP6 换体后的同一 `v13_resolve_judgments`(canonical 半边 DP2 形态逐字保留+filter 半边;worker 契约零改动——仍是 claim→resolve(env,1) 循环);canonical 层=DP2 已落的 judgment_cache+reused_from 列,**本 plan 零新增映射表**(per-chunk 行直接经 DP2 机制落 cached/reused_from,G-ctx4-3 由既有机制兑现);DP1 复合唯一性零改动 |
| 2(DP1) | effect_request 只携语义词段(v13_effect_envelope 剔水位七键);judge effect 随 request 携带语义信封(含 needed/candidates——DP5 增键不在剔除表) | filter 行进 needed → 随语义信封进 judge effect request(体量增量 k×~200B,§5 风险表记);worker 慢路从 request->'envelope' 取 candidates/needed,零活表重推导;v13_effect_envelope/v13_effect_id **零改动**(无新豁免路径) |
| 3(DP1) | 双登录强制架构;三角色最小 ACL+负向权限测试纪律 | filter 面:新函数按角色发放(纯构建器/trace=三角色;resolve 内部件=v13_resolve;§3.1 L10);memory 面:transcript_chunks 运行角色只 SELECT、DML 零授权(owner/cron 平面,DP4 chunks 同构);gate H/N 组负向断言 |
| 4(DP1) | v13_policies 载体:(name,version) PK+at-most-one active;追加=新版本行+同事务翻 active;读侧单源 v13_policy() | 播 chunk_filter v1(active)/judgment_defaults v2(先插 inactive 再双 UPDATE 翻 active——turn 10 #64 fixture 顺序纪律)/memory_stack v1(active);种子即校验器输入(消费点 fail-closed V3006) |
| 5(DP1) | 每 stage setup 只加载到当前 stage(files_through 前缀切片);gate 断言只能引用当前 stage 已加载对象 | filter=第 10 位、memory=第 11 位纯末尾追加;filter gate 断言对象 ≤10 号文件、memory ≤11 号;DP1–5 各 gate 在其前缀库复跑不受换体影响(结构性) |
| 6(DP1) | α 超时分类门(query_canceled∧外层声明 statement_timeout 才吸收)/β 只捕 V3001/受检者事件落变更相 | filter 族的每次 typesafe_ask(存在性批/per-chunk 批)经同一 α/β 块(v13_filter_ask 内,字面同 DP2 §3.6);失败调用落 judgment_calls(failed_timeout/failed_validation);resolve/failed 审计事件路径不变(变更相/complete) |
| 7(DP2) | **DP6 行:per-chunk Score/Noul 必须经同一族机制——v13_question_wire/v13_request_hash(rubric=criteria 进材料;answer schema 版本来源=模板列)+judgment_cache+judgment_calls;`v13_project_state` 对任意 jsonb state 形状工作(不绑定 canonical_state——per-chunk 的 state=chunk 投影);不另建第二 canonical cache;provider/model=信封冻结值** | 全部照单:题面/哈希经 v13_question_wire+七参 v13_request_hash(签名逐字不动);缓存/账本=judgment_cache/judgment_calls(per-chunk 行 signal='chunk::<content_hash>'——DP1 #43 signal 入材料模式的家族版,per-chunk 身份由 signal 差分);批态=构建 {'query','chunks'} 后经 v13_project_state(模板 projection='["query","chunks"]'——「state=chunk 投影」的字面兑现);零第二缓存;身份=信封冻结值(经 v13_guc_required,缓存键永不记 NULL 身份) |
| 8(DP2) | needed 推导面三处(tools 目录/needed 函数体/模板行集)由 revision/cgr/cgr 承接;「新增判断族=新增模板族行+needed 新分支(函数体 DDL 自动 bump cgr)」 | 两族模板行走 DP2 版本父表机制(append-only+freeze+行级 cgr 触发器,§3.1 L9 种子);「needed 新分支」落点=信封合并层(OQ2 裁决——v13_needed_judgments 函数体**零改动**,理由:per-chunk 行必须消费信封 rc 冻结候选(DP5 契约①「禁止重跑 recall」),而 needed_judgments 无候选入参;无漏报论证不破:推导输入面=tools 行集(revision)+needed 体(cgr)+模板行集(cgr)+语料代数(cgr,DP5 接线)+goal(token.goal 键)+k 策略(token.recall_ver 键)全覆盖,信封体漂移=部署面(DP2/3/4/5 换体同界) |
| 9(DP2) | 信封单语句单快照(turn 7 #47);M2-9 包含性断言(追加键合法) | DP6 信封换体保持单条 SQL+MATERIALIZED CTE(rc 提前、needed 合并、groups 过滤——CTE 重排不动单快照结构性);20 键集零增删(仅 needed 内容扩) |
| 10(DP2) | (γ)/(γ') 双站复校+no-progress 执法(付费批零落行=failed=true);canonical first-wins+read-back | filter 族的 cache upsert/decisions 落行走同一 γ/γ'/read-back/no-progress(v13_filter_ask 内逐字同款);per-chunk 批整批被 γ' 拒 → landed=0 → failed=true EXIT |
| 11(DP2) | judgment_calls/criteria/模板声明位纪律(writer='v13_resolve' CHECK 钉死/ASCII 题文/jsonb null 封死) | 两族种子全过列卫(question ASCII/criteria 形状随 kind/writer='v13_resolve'/provider·model NULL/wire·canon=1);gate A 组断言 |
| 12(DP3) | **DP6 行:candidates.decision_id=per-chunk verdict 的 decision_id;过滤模板必须 epoch='pre-finalize'(经 trg_decisions_epoch 自动落行);judgments=complete-only(answer 非空∧status∈answered/cached);missing/timeout/review 的默认动作**不进 judgments**(raw_verdict=null 会被 validate 拒),其 trace 载体=你的段/候选级消费段设计;judgment_defaults.points 填 per-chunk Score/存在性 Noul 两点(F1);candidates.decision_id 落地后 judgments 消费集自动非空** | decision_id 经 §3.1 L8 装配换体填充(上下文 join,见 #13);两族模板 epoch='pre-finalize' 显式 INSERT(decisions.epoch 经 DP3 触发器自动固化);jud 消费集=候选 decision_id ∪ 存在性行(候选非空时,§3.1 L8);默认动作 trace 载体=**v13_filter_trace**(候选级:decision_id/action/basis∈{decision,gate_closed,default_missing,default_timeout}——本 plan 的消费段设计,F1 毒化三形态 gate 的断言面);judgment_defaults v2 填两点(chunk_score {missing:include,timeout:include,review:degrade}/corpus_exists {missing:include,timeout:include,review:include},OQ6 方向论证) |
| 13(DP3) | manifest 只消费内容寻址身份;校验器七层封闭(candidate 行恰四键/judgments 行七键/词表) | 装配 join 键=decisions.context 的 content_hash 字段(不重算哈希、不读 GUC——decision 的 context 即哈希材料本体,单源);candidates 四键形状不动(仅 decision_id 值非空化);judgments 行七键/final_action∈{recorded,include,exclude,degrade,fail} 词表内真值 |
| 14(DP3) | token 追动键缝:进 manifest 输出的输入必须在 token 有键;jdef_ver 随 defaults 翻版追动 | judgment_defaults v1→v2 翻 active → jdef_ver 1→2 → 全域恰一次 refresh(DP3 OQ1 既判语义,gate 断言);chunk_filter 策略版本**不入 token v1**(其值只影响 final_action/trace 的派生,不影响 sections 字节/哈希材料——candidates/judgments 的内容=decisions 行,decisions 由 dec/token.goal 键追动;gate 断言:翻 chunk_filter 版本不触发 refresh;若未来 sections 消费 action 排序,按同缝并入,§1.4 DP7 行) |
| 15(DP4) | **DP6 行①:decisions 侧引用路径冻结——chunk 身份必须落 `decisions.context->'chunk'->>'content_hash'`(retention 检查面+触发器锁面);批写锁纪律:单事务批写多条含 chunk 引用的 decisions 必须引用集并集升序预锁(或拆单引用集事务)** | per-chunk 行 context 形状立法:`{'query_content_hash':…,'chunk':{'content_hash':…}}`(v13_filter_ref 单源构造——材料=存储=join 键三位一体,§1.5 不变量 6);批写锁纪律兑现:resolve 全部 per-chunk INSERT 严格按 signal 升序迭代(consult 循环 ORDER BY signal/fbatch ORDER BY signal)——signal='chunk::'||hash 的字典序=hash 升序 ⇒ 逐行取锁即并集升序(与删除端 source→hash 升序复合序无环,DP4 §3.1bis 论证同款);gate G 组两连接实证 |
| 16(DP4) | DP6 行②:GRANT SELECT ON chunks,v13_sources,v13_chunks_meta TO v13_resolve(届时补) | **已由 DP5 落位(DP5 §1.4 契约③:信封换体创造的消费点前移授权)**——本 plan 勿重复授,消费清单记档;route 半边亦由 DP5 落位 |
| 17(DP4) | DP6 行③:transcript_chunks 独立表独立索引,不搭 chunks 便车;§4.4 文档/记忆语料分区 | §3.2 独立表(零 corpus 列——记忆语料即独立分区)+独立 stannum 索引;与 chunks 表零共享(除 v13_body_hash 哈希公式同源——跨平面内容寻址一致性) |
| 18(DP4) | 锁协议命名空间(20260920=content_hash 类/20260921=source 类);v13_adv_xact_locks;删除端协议序 | per-chunk decisions 的引用锁由 DP4 既有触发器(trg_decisions_chunk_ref_lock)自动逐行取得——本 plan 零新锁对象、零新命名空间;写者契约=升序迭代纪律(#15) |
| 19(DP4) | 驱动器契约四步(外部 IO 不进事务)/fixture 走真实链路 | filter/memory gate 语料一律经 DP4 驱动器四步摄取;manifest 经 DP3 refresh settle 真实链路;事件经 v13_append_event;parse/advance 经 DP1 真实函数 |
| 20(DP5) | **DP6 行①:信封 candidates 键=parse 时冻结的召回候选([{content_hash,bm25,spans}] 三键);per-chunk needed 必须消费此键,禁止重跑 recall 重推导(单一推导点);召回判断族模板行+needed 新分支由你落,epoch='pre-finalize'** | per-chunk/existence 行在信封合并层自 rc CTE(单一调用单一快照)派生(§3.1 L5);resolve/装配零处调 v13_recall*——体查找按 content_hash(chunks 表,content-addressed 确定性);「needed 新分支」落点=信封合并层(OQ2,#8);epoch ✓ |
| 21(DP5) | DP6 行②:v13_recall 族签名冻结;extract_spans 载荷约定跨世代不同——不得直调 | 本 plan 零调用 v13_recall 族/extract_spans(候选消费走信封键);memory reader 是**新函数族**(v13_transcript_recall),不碰 chunks 面 |
| 22(DP5) | DP6 行④:k_max=64 是 per-chunk 批预算的结构上界(⌈k/32⌉ 批);存在性 Noul 缓存键的候选集维度(stepfun F2)消费 csh 材料 | k≤64 结构继承(rc 冻结);F2 键载体=**candidates_digest**(排序去重候选哈希全集的 sha256,OQ4 裁决——较 csh 更窄:仅候选维度,目录变更不轮换存在性键;单源函数 v13_candidates_digest,信封侧/装配侧同函数同输入);与 DP5 提示「消费 csh 材料」的偏差记附 A #3 |
| 23(DP5) | DP6 行⑤:span_assembly 策略版本在你段级消费 v13_assemble_spans 进 manifest sections 那天并入 token(候选级命中跨度不触发) | DP6 不产 chunk sections(OQ7)——⑤缝保持休眠,转发 DP7+(§1.4 DP7 行);候选级 spans 已在 candidates 键内(DP5),本 plan 零消费变化 |
| 24(DP5) | DP6 行⑥:候选批量化引用锁纪律(DP4 契约⑧转发) | #15 兑现 |
| 25(DP5) | DP6 行⑦:transcript_chunks 独立表独立索引 | #17 兑现 |
| 26(DP5) | 一页账:费用账自 DP6 per-chunk 起;k_max 放宽=DP7 裁量 | DP6 更新一页账(§4 末):存在性 +1 ask;canonical(1)+existence(1)+⌈k/32⌉;k=8→2 asks、k=64→4 asks(1 快路+3 慢路轮) |

### 1.3 Open Questions 裁决(本节为最终权威)

**OQ1 裁决:双 stage——`v13/filter/`(第 10 位)与 `v13/memory/`(第 11 位)。** §1.1 已述四点依据(a 正交/b gate 剖面/c 一里程碑一提交/d 分解表授权)。次序:filter 先(§11 交付排序第 1 条承重件),memory 后。memory stage 依赖刻画后库形态(stannum 0.1.0 可用且已过 DP5 刻画 gate)——第 11 位前缀加载即得(≥10 号文件库全含 9 号)。

**OQ2 裁决:per-chunk needed 分支落在信封合并层,envelope OR REPLACE(第三次换体);v13_needed_judgments 函数体零改动。**
- 形态:信封 CTE 重排为 runtime→ctx→**rc**→tmpl→**fg/frows**(过滤行:rc 候选×两族模板,DISTINCT ON content_hash 去重)→**needed**(v13_needed_judgments 基族 ∪ frows,signal 升序聚合,CASE 省 criteria 键形态与 DP2/DP5 逐字同构)→groups(**仅 canonical 行**——template_name NOT IN ('chunk_score','corpus_exists'))→wm→pol;外层 20 键零增删,csh 公式不变(needed 内容自然扩入)。
- 论证:(a) DP5 契约①禁止重跑 recall——过滤行必须消费同一 rc 求值(合并层单点满足;塞进 needed_judgments 会造成 recall 双求值且无候选入参缝);(b) 无漏报论证(DP6 版):needed(含过滤行)=f(tools 行集,needed 体,模板行集,语料代数,goal,k 策略)——六输入分别由 revision/cgr/cgr/cgr(DP5 接线)/token.goal/token.recall_ver 覆盖,probe 七键检出不变;信封体漂移=部署面(DP2/3/4/5 换体同界:stage 加载世界结构性重建,无 mid-turn 换体生产路径);(c) needed_judgments 零改动保 DP1 #59 事件触发器分支 2 的既有语义面。消费清单 #8/附 A #4。

**OQ3 裁决:per-chunk 批态与缓存键的载体——signal 差分身份 + 批态含体 + 键材料=内容寻址引用;§6.5 批处理约束与 §4.5 per-chunk 键的张力按特别法优先(§4.5),附 A #5 呈报。**
- 载体:per-chunk signal=`chunk::<content_hash>`(DP1 #43「signal 入哈希材料」的家族版——同模板同题面异 chunk 由 signal 差分行);批态=`{'query':<goal 全文>,'chunks':[{content_hash,body}×≤32]}`(经 v13_project_state 按 chunk_score 模板 projection='["query","chunks"]' 执法——DP2 契约「state=chunk 投影」的字面兑现);per-chunk 键材料(DP2 七参 builder 的 p_context 位)=`v13_filter_ref(goal_hash, chunk_hash)`=《query_content_hash+chunk.content_hash 引用对象》——§4.5 字面「hash(问题, chunk.content_hash, query.content_hash)+provider/model+rubric/版本」的载体化(criteria 经题面 wire 进材料,answer_schema_version 经 DP2 OQ2 的 γ/γ' 复校承重)。
- 张力:§6.5 批约束明文「不得发送联合 state 却按题局部分片复用答案」;而 §4.5 明文 per-chunk 键+`_many` 批——一次 typesafe_ask 单 state 的 API 形状下,per-chunk 键必然「批态联合、键局窄」。裁决:**§4.5 为过滤族的特别法**(lex specialis),理由:(a) §4.5 的键公式是设计对过滤族的显式 normative 裁决,G-ctx4-3(跨 session 复用)在联合键下不可构造(per-chunk 是唯一满足 gate 的形态);(b) §6.5 所防的是 canonical 投影面的「哈希面≠可见面」漂移——per-chunk 的键引用与载荷正文之间是**内容寻址的确定函数**(chunks.body 被 CHECK 钉死为 content_hash 的唯一原像,跨事务不可漂移),§6.5 要防的静默漂移面结构性不存在;(c) 批间交叉污染是模板质量参数,由模板版本拥有(换 rubric=冻结新版本=新哈希世代)。§4.5/§6.5 的字面冲突不构成 blocked(特别法读法自洽),呈报父 loop(附 A #5)。

**OQ4 裁决:存在性 Noul 缓存键的候选集维度=candidates_digest(排序去重候选 content_hash 全集的 sha256),单源函数 v13_candidates_digest;不用信封 csh。**
- 依据:(a) F2 修法原文「hash(query.content_hash, 排序后候选 content_hash 全集)+模板/model/版本」——candidates_digest 是其逐字载体(摘要材料=三键候选对象 [{content_hash,bm25,spans}] 的 content_hash 键集,bm25/spans 不入——语料统计漂移[IDF/avgdl 随 ingest 变]与候选序均不轮换本键,D6 行为断言);csh(needed∪recall)超集于候选(目录/模板变更也轮换存在性键)——保守 miss 面扩大且与 F2 语义不精确对齐;(b) **装配侧可单源重建**:信封侧对 env->'candidates' 计算、装配侧对自身 v13_recall_candidates 产物计算——同函数同输入(DP5 信封/装配共用 recall 的同款单源纪律),judgments 消费集的存在性行 join 因此无需信封在场(DP3 契约「manifest 记本 session 视角」兑现);用 csh 则装配侧不可重建(needed 重推导=整信封),存在性行无法入消费集。(c) 与 DP5 提示「消费 csh 材料」的偏差=载体级(维度收窄到 F2 字面),记附 A #3。
- 键材料(存在性):`v13_existence_ref(env)`={'query_content_hash': env->>'goal_hash', 'candidates_digest': v13_candidates_digest(env->'candidates')}——候选集随重摄取变化 ⇒ digest 变 ⇒ 新键 ⇒ **陈旧「无答案」不复用**(F2 立法核心,gate C 组);目录/模板变更不轮换本键(候选不变则闸门语义不变——比 csh 更精确的 miss 域)。

**OQ5 裁决(F10):记忆栈新鲜度=fail-closed(投影只读)+滞后上界(策略行)+当前 turn 消息永远直读(canonical_state 平面结构性满足)+降级可观测(结构化状态+NOTICE);「落审计事件」的消费半边=已发布契约。**
- fail-closed:v13_transcript_recall **只读 transcript_chunks**(零 events 回退读路径——第二读取路径被结构性排除);新鲜度谓词 v13_transcript_freshness 返回 {watermark,max_curated_seq,lag,max_lag,degraded},lag=max 策展事件 seq−watermark(仅 user/message+llm/message 族——编排事件不入分母,否则 turn/route/effect_done 永久推高 lag)。
- 滞后上界:memory_stack 策略行 max_lag_events(v1=16);超界 → degraded=true + RAISE NOTICE(运维可见);消费契约(发布给 DP7+/装配接线者):degraded=true 时记忆层不得作为可靠召回面,消费侧须落审计事件并降级——**recall 平面纯 SELECT(DP1 角色分裂)不可写事件**,F10「落审计事件」在无消费者的 DP6 以 NOTICE+结构化状态+已发布消费契约三件套兑现,附 A #9 呈报。
- 当前 turn 直读:判断平面的 v13_canonical_state 本就直读 events(语义消息窗)——当前 turn 消息永不依赖投影,结构性满足;gate J 组断言(ctx.messages 含当前 turn ∧ 投影不含)。
- 上一 turn 可召回性(F10 gate):lag≤max_lag ⇒ 上一 turn 的策展行可被 reader 召回;lag>max_lag ⇒ degraded=true 且 reader 仅返回已投影前缀(不谎报完整)。

**OQ6 裁决(F1 方向):过滤两点默认动作全部 fail-open(证据保全方向)。**
- chunk_score:{missing:'include', timeout:'include', review:'degrade'};corpus_exists:{missing:'include', timeout:'include', review:'include'}(闸门语义映射:include=不闸/proceed,exclude=闸/skip per-chunk)。
- 论证:设计仅有的两处已裁方向——摘要验收 fail-closed(不采用)/intent 门控 fail-open(绑超集);过滤属**证据装入**族(与 intent 同族):候选池不漏就不死(§4.6),判断缺失时静默排除=作用力 2 批判的「不报错,只静默漏召」同种死法;fail-open 的代价(全候选装入)由 manifest 装箱(DP3 run_incl>budget 即 skip)确定性兜底——退化为 T0-recall 行为(bm25 序截断),证据零丢失。review 带(score 置信不足)→ 'degrade'(装入但降序——未来 sections 半边的 Normal 优先级语义,§1.4 DP7 行);闸门三态全 include=不闸(存在性不确定时放行 per-chunk——多花 k 次调用、不静默丢证据)。三态区分兑现:status='failed' 行在档=timeout 态(问过未答),零行=missing 态(v13_chunk_filter_action 的 basis 字段),review=已答在带——F1 毒化三形态 gate 逐点断言(G-ctx F 组)。
- defaults v2 经 v13_judgment_defaults_check 形状校验(DP3 校验器零改动——points 键集恰 {missing,review,timeout}/动作词表恰四值,v2 天然过);运行期缺点=V3006 fail-closed(v13_filter_defaults_action,配置错误响亮)。

**OQ7 裁决:chunk manifest sections(候选→过滤→段)不做,缝发布 DP7+。** 依据:(a) 分解表 DP6 行设计输入=§4.5+§4.4,段级装配消费非所指派(DP5 §1.4⑤为条件句「在你段级消费…那天」);(b) DP3 校验器层 5 钉死 section_id=kind 同名 ⇒ 单 kind 单段——多 chunk 段需 manifest_version 2+校验器重做+全序键设计,是独立工作包;(c) DP6 的 manifest 侧义务止于 DP3 契约:candidates.decision_id+judgments 消费集+final_action 真值(§3.1 L8)。span_assembly token 缝随 sections 一起保持休眠(消费清单 #23)。附 A #5/#10。

**OQ8 裁决:记忆逐字层 v1=每策展事件一行(seq_from=seq_to),策展=type IN ('user/message','llm/message') 且 payload->>'text' 非空。** 设计「只收 user/assistant」的 v13 事件词表映射:assistant=llm/message(worker 生成语义事件的唯一族;tool/result 是机器产物不入记忆);§9 五列形状逐字落(session_id,seq_from,seq_to,body,content_hash),content_hash=v13_body_hash(body)(DP4 公式同源——跨平面内容寻址一致);区间合并(相邻事件并段)是批量优化,v1 不做(台账);空体跳过(零召回价值);FK(session_id,seq_from)→events(投影行不可超越源事件);UPDATE 拒(行不可变)/DELETE 留给全量重建(owner 平面);tick 载体=cron job v13-sweep-transcript '*/5' 调 v13_rebuild_transcript_chunks(100)(ch13:58-59 逐字形态),pg_cron 不可用守卫降级(DP4 §3.7 同款),builder 恒手动可调。

**OQ9 裁决:结构化层=stannum 索引建在 decisions(question)(默认配置,单索引纪律),语义决策缓存机制不做(§12 台账)。** decisions.question 是 append-only 不可变列(DP1 身份列冻结)——段不可变、零 fold churn,设计「理想负载」论证的结构兑现;索引在 memory stage 落(≥10 号库已含 stannum);消费者=未来语义决策缓存(台账触发,§7)。逐字层引擎=**stannum(刻画后)**:记忆语料以会话语言为主(本仓实际负载 CJK 重)——§7 分层规则「语料 CJK:stannum(刻画后,救命件)」对记忆语料同构适用;tsvector 起步对 CJK 记忆零召回=交付一个玩具;第 11 位前缀已过 DP5 刻画 gate,直接 stannum 是 §7 既裁路径。reader=v13_transcript_recall,签名 (uuid,text,int)→TABLE(content_hash text, bm25 numeric, seq_from bigint),`==>` 只在其体内经 EXECUTE(三禁纪律;文件 11 的源码扫描计数=恰 1,DP5 R2 同款口径);canary/绑定断言复用 DP5 K 组形态(§4 N 组)。

**OQ10 裁决:worker 契约零改动;settle 面保持零 GUC 消费。** resolve 换体后慢路 worker 仍是 claim→resolve(env,1)→renew→complete 循环(DP1 契约 #1 兑现);filter 族的 goal 文本经 v13_goal_text(sid, goal_hash) **哈希钉定读取**(v13_goals 按 content_hash 取行——parse 与 worker 之间 goal 前进时,旧 goal_hash 仍解析出旧文本,键与载荷不漂移;content-addressed 确定性);装配 join 走 decisions.context 字段(零哈希重算、零 GUC)——DP3「refresh worker 无需 SET typesafe.*」注记保持成立。

### 1.4 本 plan 对 DP7–DP8 发布的契约

| DP | 契约 | 形态 |
|---|---|---|
| DP7(经济件) | ① **判断成本核算自 filter 起**:judgment_calls 现含存在性批/per-chunk 批(逐 ask 一行,payload 体积在档);F5① 解析相 per-session/每日花费闸立法时消费 calls 计数(含 filter 族)。② **chunk_filter 策略行(gate_closed_hi/gate_open_lo/score_include_lo/score_conf_lo)与 judgment_defaults points 是经济件输入**,翻版=新行;chunk_filter 版本不入 token(消费清单 #14 论证)——若你的 sections/tier 消费 action 排序,按 DP3 追动键缝并入。③ **chunk manifest sections(段级装配)的完整输入面已就绪**:candidates.decision_id+judgments.final_action+v13_filter_trace(basis 含默认分支)+v13_assemble_spans(DP4)+spans(候选级,DP5)——sections 落地那天 span_assembly 版本入 token(DP5 契约⑤转发至此);manifest_version 2+校验器多段化是你的范围(OQ7 裁决移交)。④ **memory reader 消费缝**:v13_transcript_recall/freshness(签名冻结 (uuid,text,int)→TABLE 三列/{watermark,max_curated_seq,lag,max_lag,degraded});记忆段进 manifest 时按 degraded 契约落审计事件(OQ5 的消费半边)。⑤ judgment_defaults 摘要验收点(触点 2)照 DP3 契约由你填;k_max 放宽=你重开一页账(DP5 契约;本 plan §4 末已更新至存在性+1 形态)。⑥ 一页账(§4 末表)是你的经济件输入基线 | 表/函数/策略行引用 |
| DP8(latch/render/fork) | ① fork 后 per-chunk 判断重问由 canonical 缓存吸收(content-addressed 跨 session——DP2 §1.4 DP8 行逻辑在 filter 族原样成立,G-ctx4-3 即其证据面)。② exact replay:manifest candidates 的 decision_id/judgments 的 raw_verdict+final_action 已冻结——v13_replay 消费旧 verdict 零新依赖;被引用 chunk 行由 DP4 retention 保留(F3②)。③ render 消费 manifest 时 judgments/candidates 的 filter 字段即上文;prefix_identity 零耦合(filter/memory 不进身份材料) | 语义说明+字段引用 |

### 1.5 不变量(全 plan 有效,违反即设计背离)

1. DP1–DP5 全部不变量原样继承(两相分离/锁内零外部 IO/纯判断 IO 例外唯一/双登录/αβ 语义/行为参数冻结消费/token 与 manifest 同语句快照/冻结即不可变/manifest 只消费内容寻址身份/装配确定性/行自证/重摄取同事务/外部只记 hash/锁协议/退役源过滤/三禁/cgr 无漏报/单 stannum 索引纪律)。本 plan 新读写:filter 族判断调用发生在解析事务 resolve 体内(纯判断 IO,已离开会话锁);memory 构建在 owner/cron 平面(零运行角色 DML);对既有对象的变更只限 §1.1 九处。
2. **per-chunk 身份四面同源**(哈希同源教训的过滤族版,本 plan 重点自检项):写入=v13_filter_ask 的 cache/decisions INSERT(经 v13_judgment_hash→v13_row_context→v13_filter_ref);读取=v13_gap/consult(同一 v13_judgment_hash);材料构造=v13_filter_ref(goal_hash, chunk_hash) 单一 IMMUTABLE 函数;存储=decisions.context=该函数输出原物。存在性键四面同构:v13_existence_ref(env) 单源(信封侧哈希/装配侧 join 重建经 v13_candidates_digest 同函数同输入)。**canonical 族的哈希路径逐字节不变**(v13_row_context 对非过滤 signal 严格转发 v13_group_state——分支仅 signal='corpus_exists' 与 'chunk::%' 前缀两处)。signal 命名空间保留:`corpus_exists` 与 `chunk::` 前缀为过滤族保留名——未来 canonical 模板族不得启用同名 signal(`chunk::` 分支有 64hex fail-closed 拦截;`corpus_exists` 分支无形态守卫,同名将静默换 context 材料、canonical 哈希漂移)。
3. **存在性键含候选集维度(F2 立法)**:候选集任何变化(重摄取/退役/换 chunker 重切)→candidates_digest 变→存在性键变→陈旧「无答案」不复用;gate C 组是该不变量的行为断言。存在性键覆盖冻结候选全集,存在性 state 就必须以全集体为载荷——任一候选体缺,本 pass 整个 filter 面跳过(不问不缓存不消费,过滤行剔出 remaining;入口守卫 v13_filter_bodies_present+态基数 belt 双保险,键-态绑定),gate C7/E6 是其行为断言。
4. **顺序=存在性严格先行**:任何 per-chunk ask 之前,存在性批必已不在缺口(问过或缓存命中);闸门三态(missing/timeout/review)全 fail-open(不闸)——per-chunk 永不因闸门不确定而被跳过。
5. **per-chunk 装入方向 fail-open(OQ6)**:missing/timeout→include(装箱兜底)、review→degrade、闸关(已答且确信无)→exclude(闸是完成了的判断证据,优先于 per-chunk 缺省);三态可区分(basis 字段)且经版本化 defaults(jdef_ver 追动)。
6. **decisions.context=哈希材料原物**:per-chunk 行 context 恰为 v13_filter_ref 输出('chunk'->'content_hash' 路径=DP4 冻结路径);存在性行 context 恰为 v13_existence_ref 输出;装配 join 只按 context 字段等值——零哈希重算、零 GUC、零信封依赖(哈希同源由「材料=存储」结构性保证)。
7. **批写锁纪律(DP4 契约①)**:单事务内全部含 chunk 引用的 decisions INSERT 严格按 signal 升序(=hash 升序)迭代——consult 循环/fbatch 构造/落行循环三处 ORDER BY signal;逐行升序取锁与删除端(source 升序→hash 升序)复合序无环。
8. **信封单语句单快照不回归**:合并层在 CTE 内完成(rc 单次求值,过滤行派生不自 rc 之外取数);20 键集与 canonical 键表达式逐字不动;groups 仅 canonical 行(过滤族组态在 resolve 侧构建,信封不携体——judge effect 体积不随 k×body 膨胀)。
9. **记忆 fail-closed**:v13_transcript_recall 只读 transcript_chunks;watermark/lag/degraded 只经 v13_transcript_freshness 单源;当前 turn 语义由 canonical_state 直读(结构性,零投影依赖);超界降级可观测(NOTICE+结构化状态)且消费契约已发布。
10. **文档顺序=加载顺序**;filter=第 10 位、memory=第 11 位纯末尾追加;ACL 全量块在文件真末尾;gate 断言对象 filter ≤10 号、memory ≤11 号文件;新 RAISE 统一 `USING ERRCODE='V3006'`(DP1–5=V3001–V3005 序列顺延,已核无占用);唯一例外=复制体的既有 RAISE 与 V 码逐字保留(墓碑纪律优先,DP4/DP5 同款)。
11. **种子纪律**:jsonb 一律单完整字面量+显式 ::jsonb 或 jsonb_build_*;策略翻 active 经「INSERT inactive→双 UPDATE 翻」(turn 10 #64);模板经版本父表 draft→内容行→freeze;cgr/revision 断言一律相对比较。
12. **零 worker/驱动契约变更**:慢路仍是 resolve(env,1) 循环+renew_lease;parse 出口七键 schema 逐字段不变(新键只进 resolve 直调返回);v13_advance/v13_complete/v13_enqueue_effect/v13_effect_* 零改动。

---

## 2. 输入 § 映射

| 设计原文(冻结) | 本 plan 落点 |
|---|---|
| §4.5 缓存键 per-chunk(hash(问题, chunk.content_hash, query.content_hash)+provider/model+rubric/answer schema 版本) | signal='chunk::<hash>' 差分身份+七参 builder 的 p_context=v13_filter_ref(query_content_hash=goal_hash, chunk.content_hash);provider/model=信封冻结值(DP2 v13_guc_required fail-closed);rubric=criteria 经题面 wire 入材料;answer_schema_version 经 DP2 OQ2 γ/γ' 复校承重(模板列 provenance);gate D 组 |
| §4.5 默认过滤器用 per-chunk Score/Noul(_many) | v1 交付 chunk_score(score 族)——ch10:142 的 normative 流水线;per-chunk Noul=同机械不同模板族行(信号前缀区分,防 needed signal 撞行),零代码缝(§7 台账);_many 批=≤batch_questions(信封冻结 budget=32)行/批 |
| §4.5 全集 Choice 与逐 chunk 缓存语义冲突,仅留给「相对序本身是问题」的重排 | 不做(§12 台账);v13_filter_trace/judgments 记录逐 chunk verdict,重排消费面留缝 |
| §4.5 顺序:先一个存在性 Noul 闸住整批花费(语料无答案时 1 次调用替代 k 次),再逐 chunk Score | resolve 换体的 filter 半边:存在性批(1 问,state=查询全文+全候选体)严格先行→v13_filter_gate_open 三态评估(missing/timeout/review 全不闸,已答确信无→闸)→per-chunk 批;G-ctx4-1=闸关时 per-chunk 外部调用 0(mock 计数);OQ4 键;gate C 组 |
| §4.5(评审 F2 立法)存在性键含候选集维度:hash(query.content_hash, 排序后候选 content_hash 全集)+模板/model/版本——重摄取后陈旧「无答案」不复用 | v13_existence_ref={query_content_hash, candidates_digest};digest=sha256(排序去重候选哈希全集)单源函数;gate C 组 F2 断言(摄取新文档→存在性重问);附 A #1 呈报设计未改 |
| §4.5 跨 session 缓存:拆「规范答案缓存」(judgment_cache,DP2 已落)与「本 session 使用记录」(reused_from 映射),复用旧行不把判断所有权留在旧 session | per-chunk/existence 行直接经 DP2 canonical consult 机制落 decisions(status='cached',reused_from=canonical request_hash,call_id NULL,session_id=本 session);G-ctx4-3=跨 session 复用 reused_from 正确;零新映射表(DP1 契约 #1) |
| §4.4 结构化层:stannum 建在 decisions.question 上(小、静、ASCII、低 churn) | ix_decisions_question_stannum(默认配置,单索引纪律);不可变列=不可变段;消费者=语义决策缓存(§12 台账,不做机制);gate N 组 verify_index |
| §4.4 逐字层:transcript_chunks(session_id, seq 区间, body) 投影表,tick 批量构建、可重建、构建时策展(只收 user/assistant) | §3.2 表+每事件一行(OQ8)+v13_rebuild_transcript_chunks(增量,幂等,ON CONFLICT DO NOTHING)+cron job v13-sweep-transcript '*/5' 载体(DP4 §3.7 守卫降级);策展=user/message+llm/message 且非空体;gate I 组 |
| §4.4 新鲜度=水印谓词(投影 max(seq) vs events max(seq));(评审 F10 已裁)fail-closed+滞后上界(策略行)+当前 turn 消息永远直读不投影+上一 turn 可召回性 gate | OQ5 全节:watermark/freshness 单源函数;fail-closed reader;memory_stack.max_lag_events=16;degraded+NOTICE+消费契约;gate J 组(含 F10 上一 turn 可召回性断言);附 A #2 |
| §4.4 文档语料与记忆语料分区/分索引 | 独立表独立索引(DP4 契约⑦;零 corpus 列);哈希公式同源(v13_body_hash)保跨平面内容寻址一致 |
| §4.4 远程层:摘要 artifact 引用(不实现) | §7 不做(§4.4 明文) |
| §4.4 Gate:p99 events INSERT 延迟有/无投影构建对比断言;worker 长连接(连接预热税记运维注记) | gate L 组(DP4 H1 协议:p99_loaded≤max(×1.25,+0.5ms),三轮取中位);README 运维注记(连接池预热/stannum 新连接 buffer 重建税,DP5 M 组同族) |
| §6.1 缺失、超时、review 带一律走版本化默认分支(F1:流量最大的过滤点无缺省动作=设计缺口) | judgment_defaults v2 两点三态(OQ6 方向);v13_filter_defaults_action 运行期 fail-closed(V3006);trace 的 basis 字段三态可区分;gate F 组毒化三形态逐点断言 |
| §6.2 触点 5(intent 门控)仅复用既有 intent 行,为此新调 Jev 则 P2 | DP6 零新增(§7);intent 复用语义已由 DP1 落 |
| §6.2 触点 2(摘要验收) | 归 DP7(§1.4⑤;§7) |
| §9 表切片:transcript_chunks(session_id, seq_from, seq_to, body, content_hash)——记忆逐字层,水印 | §3.2 五列逐字+自证 CHECK+FK;reused_from=DP2 已落列(per-chunk 行启用) |
| §10 G-ctx4:存在性 Noul 先行;同 query×chunk 二次零外部调用(mock 计数);per-chunk 缓存跨 session 复用(reused_from 正确) | §4 G-ctx4 映射表(C1/C2、D1、D2) |
| §10(§4.4 行)投影 p99 | L 组 |
| §11 交付排序第 1 条(过滤管道承重件) | filter stage 即该件的过滤半边 |
| §12 YAGNI 台账(全集 Choice 重排/语义决策缓存/效用遥测/emergent 等) | §7 逐条(台账为源) |
| §13 教程映射:第 10 章(存在性 Noul 先行+per-chunk Score);第 5 章相关 | §6(ch10:129–146/219–222/243–244;ch13:53–61/130–135 tick;ch5:19–22 三来源;正文零改动) |

---

## 3. 表/函数 DDL 与 SQL 草案

> 文件一:`v13/filter/v13_filter.sql`(全新增;SQL_LOAD_ORDER 第 10 位纯末尾追加);文件二:`v13/memory/v13_memory.sql`(第 11 位)。**文件内顺序=加载顺序**。两文件各以 BEGIN/COMMIT 包裹(DP2–DP5 形制:含 OR REPLACE,单事务原子装载)。草案级完整度:列/约束/函数签名/关键语句到位,实施者可直接开写;注释标注纪律出处。**新 RAISE 统一 `USING ERRCODE='V3006'`(DP1–5=V3001–V3005 序列顺延,已核无占用);复制体的既有 RAISE 与 V 码逐字保留**(不变量 10 例外)。实施纪律:三个 OR REPLACE 大体(envelope/resolve/assemble)从上游 stage 文件**加载态原文机械复制**(比计划文本更权威,DP3/DP5 先例),仅按本节标注的增量编辑。

### 3.1 文件一 `v13/filter/v13_filter.sql`(第 10 位;过滤管道)

```sql
BEGIN;

-- =========================================================================
-- DP6 filter (v13_filter.sql): existence-Noul gate + per-chunk Score +
-- cross-session reuse + judgment_defaults.points (F1/F2/F10 legislation).
-- Design: docs/designs/v13-context-on-pg.md §4.5/§4.4(structured layer)/
-- §6.1/§9/§10 G-ctx4. Review: stepfun F1/F2. Contracts: DP1 §1.3 row DP6,
-- DP2 §1.4 row DP6, DP3 §1.4 row DP6, DP4 §1.4 row DP6 ①, DP5 §1.4 ①-⑥.
-- File order = load order. Error code family: V3006.
-- =========================================================================

-- === L1 键材料构建器(哈希同源单源;四面=材料构造/哈希/存储/装配 join) ===

-- 候选集摘要(F2 立法核心):排序去重候选 content_hash 全集的 sha256。
-- p_candidates 为 DP5 三键对象数组 [{content_hash,bm25,spans}]——材料只
-- 取 cand->>'content_hash',bm25/spans 不入(对象全文入料会令语料统计漂移
-- [IDF/avgdl 随 ingest 变]轮换存在性键,违背 F2「候选集维度」;gate D6
-- 防回归)。信封侧(env->'candidates')与装配侧(自身 v13_recall_candidates
-- 产物)同函数同输入——单源(DP5 信封/装配共用 recall 的同款纪律)。
CREATE FUNCTION v13_candidates_digest(p_candidates jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(digest((SELECT coalesce(jsonb_agg(h ORDER BY h), '[]'::jsonb)
                          FROM (SELECT DISTINCT cand->>'content_hash' AS h
                                  FROM jsonb_array_elements(p_candidates) cand) d(h))::text,
                 'sha256'), 'hex');
$$;

-- per-chunk 键材料/decisions.context 原物:query 引用(goal_hash)+
-- chunk 引用(DP4 冻结路径 context->'chunk'->>'content_hash' 的构造半边)。
-- 材料=存储三位一体:resolve 落行原物存储,装配按字段等值 join,零哈希重算。
CREATE FUNCTION v13_filter_ref(p_goal_hash text, p_chunk_hash text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p_goal_hash IS NULL OR p_goal_hash !~ '^[0-9a-f]{64}$'
     OR p_chunk_hash IS NULL OR p_chunk_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION
      'v13: filter ref requires 64hex goal_hash and chunk_hash'
      USING ERRCODE = 'V3006';
  END IF;
  RETURN jsonb_build_object(
    'query_content_hash', p_goal_hash,
    'chunk', jsonb_build_object('content_hash', p_chunk_hash));
END $$;

-- 存在性键材料(F2:候选集维度):query 引用+候选集摘要。
CREATE FUNCTION v13_existence_ref(p_env jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p_env IS NULL OR p_env->>'goal_hash' IS NULL
     OR p_env->>'goal_hash' !~ '^[0-9a-f]{64}$'
     OR p_env->'candidates' IS NULL
     OR jsonb_typeof(p_env->'candidates') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION
      'v13: existence ref requires envelope goal_hash and candidates keys'
      USING ERRCODE = 'V3006';
  END IF;
  RETURN jsonb_build_object(
    'query_content_hash', p_env->>'goal_hash',
    'candidates_digest',  v13_candidates_digest(p_env->'candidates'));
END $$;

-- 行上下文族分发(不变量 2:canonical 路径逐字节不变——分支仅两处)。
CREATE FUNCTION v13_row_context(p_env jsonb, p_signal text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_hash text;
BEGIN
  IF p_signal = 'corpus_exists' THEN
    RETURN v13_existence_ref(p_env);
  END IF;
  IF p_signal LIKE 'chunk::%' THEN
    v_hash := substr(p_signal, 8);
    IF v_hash !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION
        'v13: chunk signal must carry a 64hex content_hash (%)', p_signal
        USING ERRCODE = 'V3006';
    END IF;
    RETURN v13_filter_ref(p_env->>'goal_hash', v_hash);
  END IF;
  RETURN v13_group_state(p_env, p_signal);   -- canonical:DP2 原样转发
END $$;

-- 过滤族模板在岗守卫(信封合并层消费;fail-closed:族缺失即 parse 响亮失败,
-- 不静默过滤关闭——DP2 needed 族守卫的同族纪律)。
CREATE FUNCTION v13_require_filter_templates(p_templates jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF p_templates IS NULL
     OR p_templates->'corpus_exists' IS NULL
     OR p_templates->'corpus_exists'->>'kind' IS DISTINCT FROM 'noul'
     OR p_templates->'corpus_exists'->>'question' IS NULL
     OR p_templates->'chunk_score' IS NULL
     OR p_templates->'chunk_score'->>'kind' IS DISTINCT FROM 'score'
     OR p_templates->'chunk_score'->>'question' IS NULL
     OR p_templates->'chunk_score'->'criteria' IS NULL THEN
    RAISE EXCEPTION
      'v13: frozen filter templates corpus_exists/chunk_score missing or incomplete'
      USING ERRCODE = 'V3006';
  END IF;
END $$;

-- goal 文本哈希钉定读取(OQ10):按 content_hash 取 v13_goals 行的 payload
-- 文本——parse 与 worker 之间 goal 前进时,旧 goal_hash 仍解析出旧文本
-- (content-addressed 确定性,键与载荷不漂移)。空 goal=空串。
CREATE FUNCTION v13_goal_text(p_sid uuid, p_goal_hash text) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce((SELECT g.payload->>'text' FROM v13_goals g
                    WHERE g.session_id = p_sid
                      AND g.content_hash = p_goal_hash
                    ORDER BY g.seq DESC LIMIT 1), '');
$$;

-- === L2 默认分支/闸门/动作(§6.1+F1+F2 消费面) ===

-- 默认动作读取(F1:版本化缺省的唯一运行期入口):缺点/缺态=V3006 响亮
-- (配置错误,不静默回退——F1 所防的「实现者临场决定」被结构性封死)。
CREATE FUNCTION v13_filter_defaults_action(p_point text, p_state text)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE v_pt jsonb;
BEGIN
  v_pt := v13_policy('judgment_defaults')->'points'->p_point;
  IF v_pt IS NULL OR jsonb_typeof(v_pt) <> 'object' THEN
    RAISE EXCEPTION
      'v13: judgment_defaults missing point % (config error, append a new version)',
      p_point USING ERRCODE = 'V3006';
  END IF;
  IF v_pt->>p_state IS NULL THEN
    RAISE EXCEPTION
      'v13: judgment_defaults point % missing state %', p_point, p_state
      USING ERRCODE = 'V3006';
  END IF;
  RETURN v_pt->>p_state;
END $$;

-- 存在性判定→动作:闸带(<=hi 闸/>=lo 放行/中间=review 带走 defaults)。
-- 策略形状 fail-closed(分步类型先验→显式 cast→域校验,DP4 三律)。
CREATE FUNCTION v13_existence_action(p_answer jsonb) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_pol jsonb; v_hi numeric; v_lo numeric; v_noul numeric;
BEGIN
  v_pol := v13_policy('chunk_filter');
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol->'gate_closed_hi') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'gate_open_lo') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid chunk_filter policy shape'
      USING ERRCODE = 'V3006';
  END IF;
  v_hi := (v_pol->>'gate_closed_hi')::numeric;
  v_lo := (v_pol->>'gate_open_lo')::numeric;
  IF v_hi < 0 OR v_lo > 1 OR v_hi >= v_lo THEN
    RAISE EXCEPTION 'v13: invalid chunk_filter policy values'
      USING ERRCODE = 'V3006';
  END IF;
  v_noul := (p_answer->>'noul')::numeric;
  IF v_noul <= v_hi THEN RETURN 'exclude'; END IF;
  IF v_noul >= v_lo THEN RETURN 'include'; END IF;
  RETURN v13_filter_defaults_action('corpus_exists', 'review');
END $$;

-- 闸门开否(OQ6:missing/timeout/review 全 fail-open 不闸;已答确信无→闸)。
CREATE FUNCTION v13_filter_gate_open(p_env jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE v_ans jsonb;
BEGIN
  SELECT d.answer INTO v_ans FROM decisions d
   WHERE d.session_id = (p_env->>'sid')::uuid
     AND d.signal = 'corpus_exists'
     AND d.context = v13_existence_ref(p_env)
     AND d.answer IS NOT NULL AND d.status IN ('answered','cached')
   LIMIT 1;
  IF v_ans IS NULL THEN
    RETURN v13_filter_defaults_action('corpus_exists', 'missing') <> 'exclude';
  END IF;
  RETURN v13_existence_action(v_ans) <> 'exclude';
END $$;

-- 可填 per-chunk 缺口计数(remaining 的闸感知口径):signal 可解析且体在
-- (content-addressed 查找,ix_chunks_content_hash 背书)。体缺行=不可填
-- (parse→resolve 窗口内重摄取已杀无引用行;下一信封自然收敛)。
CREATE FUNCTION v13_filter_fillable(p_env jsonb) RETURNS int
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN (SELECT count(*) FROM jsonb_array_elements(v13_gap(p_env)) g
           WHERE g.value->>'signal' LIKE 'chunk::%'
             AND EXISTS (SELECT 1 FROM chunks c
                          WHERE c.content_hash = substr(g.value->>'signal', 8)));
END $$;

-- 全集体在场守卫(存在性键-态绑定):存在性键覆盖冻结候选全集,其 state
-- 就必须以全集体为载荷——任一候选体缺(parse→resolve 窗口内 chunks 行被
-- 删:手动 DELETE/gc delete 皆 DP4 合法路径)→ resolve filter 面本 pass
-- 整体跳过:存在性不问不缓存不消费(全集键下问出的是缺体「无答案」,会
-- 经缓存回流封死同体重摄取后的新证据——F2 死法侧门)、过滤行剔出
-- remaining;下一信封自然收敛。空候选集恒过(信封 B3 已不产存在性行,
-- 双保险)。查找语义与存在性 state 构造同款(chunks 按 content_hash)。
CREATE FUNCTION v13_filter_bodies_present(p_env jsonb) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_env->'candidates') cand
                      WHERE NOT EXISTS (SELECT 1 FROM chunks c
                                         WHERE c.content_hash =
                                               cand->>'content_hash'));
$$;

-- 单候选终局动作(F1 trace 的芯;装配 judgments/未来 sections 共用):
-- 已答→score 带(conf 低=review 带→defaults.review;score>=include_lo→
-- include;否则 exclude);行在未答(status failed/open)=timeout 态;
-- 无行→闸证据优先(存在性已答确信无→exclude),再→defaults.missing。
-- basis 词表:{decision,decision_review,default_timeout,gate_closed,
-- default_missing}——F1 三态的可观测区分面。
CREATE FUNCTION v13_chunk_filter_action(p_sid uuid, p_goal_hash text,
                                        p_candidates_digest text,
                                        p_chunk_hash text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE d record; v_pol jsonb; v_score numeric; v_conf numeric;
        v_lo numeric; v_conf_lo numeric; v_ans jsonb;
BEGIN
  v_pol := v13_policy('chunk_filter');
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol->'score_include_lo') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'score_conf_lo') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'gate_closed_hi') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'gate_open_lo') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid chunk_filter policy shape'
      USING ERRCODE = 'V3006';
  END IF;
  v_lo := (v_pol->>'score_include_lo')::numeric;
  v_conf_lo := (v_pol->>'score_conf_lo')::numeric;
  IF v_lo < 0 OR v_lo > 3 OR v_conf_lo < 0 OR v_conf_lo > 1 THEN
    RAISE EXCEPTION 'v13: invalid chunk_filter policy values'
      USING ERRCODE = 'V3006';
  END IF;
  SELECT * INTO d FROM decisions
   WHERE session_id = p_sid AND signal = 'chunk::' || p_chunk_hash
     AND context = v13_filter_ref(p_goal_hash, p_chunk_hash)
   LIMIT 1;
  IF FOUND AND d.answer IS NOT NULL THEN
    v_conf  := (d.answer->>'confidence')::numeric;
    v_score := (d.answer->>'score')::numeric;
    IF v_conf < v_conf_lo THEN
      RETURN jsonb_build_object('decision_id', d.decision_id,
        'action', v13_filter_defaults_action('chunk_score', 'review'),
        'basis', 'decision_review');
    ELSIF v_score >= v_lo THEN
      RETURN jsonb_build_object('decision_id', d.decision_id,
        'action', 'include', 'basis', 'decision');
    ELSE
      RETURN jsonb_build_object('decision_id', d.decision_id,
        'action', 'exclude', 'basis', 'decision');
    END IF;
  ELSIF FOUND THEN
    RETURN jsonb_build_object('decision_id', NULL::uuid,
      'action', v13_filter_defaults_action('chunk_score', 'timeout'),
      'basis', 'default_timeout');
  END IF;
  SELECT a.answer INTO v_ans FROM decisions a
   WHERE a.session_id = p_sid AND a.signal = 'corpus_exists'
     AND a.context = jsonb_build_object('query_content_hash', p_goal_hash,
                                        'candidates_digest', p_candidates_digest)
     AND a.answer IS NOT NULL AND a.status IN ('answered','cached')
   LIMIT 1;
  IF v_ans IS NOT NULL AND v13_existence_action(v_ans) = 'exclude' THEN
    RETURN jsonb_build_object('decision_id', NULL::uuid,
      'action', 'exclude', 'basis', 'gate_closed');
  END IF;
  RETURN jsonb_build_object('decision_id', NULL::uuid,
    'action', v13_filter_defaults_action('chunk_score', 'missing'),
    'basis', 'default_missing');
END $$;

-- 候选级过滤 trace(DP3 契约「默认动作的 trace 载体=你的候选级消费段设计」
-- 的落点;F1 毒化 gate 的断言面;DP7 sections/运维的输入)。
CREATE FUNCTION v13_filter_trace(p_sid uuid)
RETURNS TABLE(content_hash text, decision_id uuid, action text, basis text)
LANGUAGE plpgsql STABLE AS $$
DECLARE v_gh text; v_dig text; v_cands jsonb; r record; v_a jsonb;
BEGIN
  v_cands := v13_recall_candidates(p_sid)->'candidates';
  v_gh := v13_goal_hash(p_sid);
  v_dig := v13_candidates_digest(v_cands);
  FOR r IN SELECT cand->>'content_hash' AS h
             FROM jsonb_array_elements(v_cands) cand LOOP
    v_a := v13_chunk_filter_action(p_sid, v_gh, v_dig, r.h);
    content_hash := r.h;
    decision_id  := (v_a->>'decision_id')::uuid;
    action       := v_a->>'action';
    basis        := v_a->>'basis';
    RETURN NEXT;
  END LOOP;
END $$;

-- === L3 过滤族 ask 宏(存在性批与 per-chunk 批共用;α/β/calls/cache/
--     γ'/落行与 DP2 §3.6 逐字同款;行序=signal 升序=hash 升序——不变量 7) ===
CREATE FUNCTION v13_filter_ask(p_env jsonb, p_state jsonb, p_rows jsonb,
                               p_label text) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  v_sid uuid := (p_env->>'sid')::uuid;
  v_payload jsonb; v_resp jsonb; v_usage jsonb; v_t0 timestamptz;
  v_hash text; v_canon jsonb; v_valid boolean; v_call uuid;
  v_tmpl jsonb; v_asked int := 0; v_landed int := 0; v_rejects int := 0;
  r record;
BEGIN
  v_payload := jsonb_build_object('state', p_state, 'questions',
    (SELECT jsonb_object_agg(q->>'signal',
                    v13_question_wire(q->>'kind', q->>'question', q->'criteria'))
       FROM jsonb_array_elements(p_rows) q));
         -- 同一 builder(DP2 不变量 2):题面同出 v13_question_wire;
         -- state=批态原物(chunk 投影,经 v13_project_state 于调用侧执法)
  IF p_env->>'timeout_ms' IS NOT NULL THEN
    PERFORM set_config('typesafe.timeout_ms', p_env->>'timeout_ms', true);
  END IF;
  v_t0 := clock_timestamp();

  -- (α) ask 边界【DP2 §3.6 α 分类门逐字】
  BEGIN
    v_resp := typesafe_ask(v_payload->'state', v_payload->'questions');
  EXCEPTION
    WHEN query_canceled THEN
      IF coalesce(current_setting('statement_timeout', true), '0')
           IN ('0', '0ms') THEN
        RAISE;
      END IF;
      INSERT INTO judgment_calls (session_id, candidate_set_hash,
                                  projection_key, payload, payload_hash,
                                  provider, model, question_count,
                                  timeout_ms, latency_ms, status, error)
      VALUES (v_sid, p_env->>'candidate_set_hash', p_label, v_payload,
              encode(digest(v_payload::text, 'sha256'), 'hex'),
              p_env->>'provider', p_env->>'model',
              jsonb_array_length(p_rows), (p_env->>'timeout_ms')::int,
              (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
              'failed_timeout', SQLSTATE);
      RETURN jsonb_build_object('asked', 0, 'landed', 0, 'rejects', 0,
                                'failed', true);
    WHEN OTHERS THEN
      RAISE;
  END;
  v_usage := v_resp->'usage';

  -- (β) 校验先行【DP2 §3.6 β 逐字:只捕 V3001;malformed 拒收整批】
  BEGIN
    IF jsonb_typeof(v_resp->'answers') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: response needs an answers object'
        USING ERRCODE = 'V3001';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(v_resp->'answers') k
                WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_rows) q
                                   WHERE q->>'signal' = k)) THEN
      RAISE EXCEPTION 'v13: response contains unknown answer signals'
        USING ERRCODE = 'V3001';
    END IF;
    FOR r IN SELECT q->>'signal' AS signal, q->>'kind' AS kind,
                    q->>'criteria' AS criteria
               FROM jsonb_array_elements(p_rows) q LOOP
      PERFORM v13_validate_answer(r.kind, v_resp->'answers'->r.signal,
                                  r.criteria);
    END LOOP;
  EXCEPTION WHEN SQLSTATE 'V3001' THEN
    INSERT INTO judgment_calls (session_id, candidate_set_hash,
                                projection_key, payload, payload_hash,
                                provider, model, question_count, timeout_ms,
                                usage, latency_ms, status, error)
    VALUES (v_sid, p_env->>'candidate_set_hash', p_label, v_payload,
            encode(digest(v_payload::text, 'sha256'), 'hex'),
            p_env->>'provider', p_env->>'model',
            jsonb_array_length(p_rows), (p_env->>'timeout_ms')::int,
            v_usage,
            (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
            'failed_validation', 'V3001: ' || SQLERRM);
    RETURN jsonb_build_object('asked', 0, 'landed', 0, 'rejects', 0,
                              'failed', true);
  END;

  -- 成功调用落行
  INSERT INTO judgment_calls (call_id, session_id, candidate_set_hash,
                              projection_key, payload, payload_hash,
                              provider, model, question_count, timeout_ms,
                              usage, latency_ms, status)
  VALUES (gen_random_uuid(), v_sid, p_env->>'candidate_set_hash', p_label,
          v_payload, encode(digest(v_payload::text, 'sha256'), 'hex'),
          p_env->>'provider', p_env->>'model',
          jsonb_array_length(p_rows), (p_env->>'timeout_ms')::int,
          v_usage,
          (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
          'succeeded')
  RETURNING call_id INTO v_call;

  -- canonical upsert + read-back + (γ') 复校 + decisions 落行
  -- (DP2 §3.6 步 5 逐字;context=v13_row_context 族分发——过滤行=ref 原物)
  FOR r IN SELECT q->>'signal' AS signal, q->>'kind' AS kind,
                  q->>'question' AS question, q->>'criteria' AS criteria,
                  q->>'template_name' AS tname
             FROM jsonb_array_elements(p_rows) q LOOP
    v_hash := v13_judgment_hash(p_env, r.signal, r.kind, r.question,
                                r.criteria);
    v_tmpl := p_env->'templates'->r.tname;
    INSERT INTO judgment_cache (request_hash, signal, kind, answer,
                                provider, model, template_name,
                                template_version, answer_schema_version,
                                call_id)
    VALUES (v_hash, r.signal, r.kind, v_resp->'answers'->r.signal,
            p_env->>'provider', p_env->>'model', r.tname,
            (v_tmpl->>'version')::int,
            (v_tmpl->>'answer_schema_version')::int, v_call)
    ON CONFLICT (request_hash) DO NOTHING;
    SELECT c.answer INTO v_canon FROM judgment_cache c
     WHERE c.request_hash = v_hash;
    v_valid := true;
    BEGIN
      PERFORM v13_validate_answer(r.kind, v_canon, r.criteria);
    EXCEPTION WHEN SQLSTATE 'V3001' THEN
      v_valid := false;
    END;
    IF NOT v_valid THEN
      v_rejects := v_rejects + 1;
      v_asked := v_asked + 1;
      CONTINUE;
    END IF;
    INSERT INTO decisions (session_id, signal, kind, question, criteria,
                           context, answer, provider, model, request_hash,
                           status, answered_at, template_name,
                           template_version, answer_schema_version,
                           reused_from, call_id)
    VALUES (v_sid, r.signal, r.kind, r.question, r.criteria,
            v13_row_context(p_env, r.signal),
            v_canon, p_env->>'provider', p_env->>'model', v_hash,
            'answered', now(), r.tname, (v_tmpl->>'version')::int,
            (v_tmpl->>'answer_schema_version')::int, NULL, v_call)
    ON CONFLICT (session_id, request_hash) DO UPDATE
      SET answer = EXCLUDED.answer
      WHERE decisions.answer IS NULL;
    v_asked := v_asked + 1;
    v_landed := v_landed + 1;
  END LOOP;
  RETURN jsonb_build_object('asked', v_asked, 'landed', v_landed,
                            'rejects', v_rejects, 'failed', false);
END $$;

-- === L4 墓碑一:v13_judgment_hash OR REPLACE(DP2 §3.5 体;唯一增量=
--     v13_group_state 改经 v13_row_context——canonical 信号逐字节不变,
--     分支仅 corpus_exists/chunk::% 两处,不变量 2) ===
CREATE OR REPLACE FUNCTION v13_judgment_hash(p_env jsonb, p_signal text,
                            p_kind text, p_question text, p_criteria jsonb)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE v_item jsonb;
BEGIN
  SELECT n INTO v_item
    FROM jsonb_array_elements(p_env->'needed') n
   WHERE n->>'signal' = p_signal;
  IF v_item IS NULL THEN
    RAISE EXCEPTION 'v13: signal % is absent from envelope', p_signal
      USING ERRCODE = 'V3002';
  END IF;
  IF v_item->>'kind' IS DISTINCT FROM p_kind
     OR v_item->>'question' IS DISTINCT FROM p_question
     OR v_item->'criteria' IS DISTINCT FROM p_criteria THEN
    RAISE EXCEPTION 'v13: hash arguments drift from frozen envelope for %',
      p_signal USING ERRCODE = 'V3002';
  END IF;
  RETURN v13_request_hash(p_signal, p_kind, p_question, p_criteria,
         v13_row_context(p_env, p_signal),
         p_env->>'provider', p_env->>'model');
END $$;

-- === L5 墓碑二:v13_judgment_envelope OR REPLACE(DP5 §3.1 L6 二十键体的
--     DP6 形态;实施纪律:从 v13/recall/v13_recall.sql 加载态原文机械复制,
--     按【DP6】标注的四处增量编辑:①rc/tmpl CTE 前移;②fg 守卫;③frows
--     过滤行合并进 needed;④groups 过滤 canonical 行。20 键集零增删。) ===
CREATE OR REPLACE FUNCTION v13_judgment_envelope(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  WITH runtime AS MATERIALIZED (
    SELECT v13_guc_required('typesafe.provider') AS provider,
           v13_guc_required('typesafe.model') AS model),
  ctx AS MATERIALIZED (
    SELECT v13_canonical_state(p_sid) AS c),
  rc AS MATERIALIZED (                       -- 【DP6①】自 wm/pol 前移
    SELECT v13_recall_candidates(p_sid) AS r),
  tmpl AS MATERIALIZED (
    SELECT coalesce(jsonb_object_agg(t.template_name, jsonb_build_object(
             'version', t.template_version, 'kind', t.kind,
             'projection', t.projection,
             'answer_schema_version', t.answer_schema_version)), '{}'::jsonb) AS t
      FROM v13_template_latest t),
  fg AS MATERIALIZED (                       -- 【DP6②】过滤族模板在岗守卫
    SELECT v13_require_filter_templates((SELECT t FROM tmpl)) AS g),
  frows AS MATERIALIZED (                    -- 【DP6③】过滤行(消费 rc 冻结
    SELECT coalesce(jsonb_agg(f ORDER BY f->>'signal'), '[]'::jsonb) AS f -- 候选;DISTINCT ON
      FROM ((SELECT jsonb_build_object(           -- content_hash 去重=跨源
                     'signal', 'corpus_exists',   -- 同文一行,判断缓存语义)
                     'kind', (SELECT t FROM tmpl)->'corpus_exists'->>'kind',
                     'question',
                       (SELECT t FROM tmpl)->'corpus_exists'->>'question',
                     'criteria',
                       (SELECT t FROM tmpl)->'corpus_exists'->'criteria',
                     'template_name', 'corpus_exists') AS f
              FROM fg
             WHERE jsonb_array_length(
                     coalesce((SELECT r FROM rc)->'candidates',
                              '[]'::jsonb)) > 0)
            UNION ALL
            (SELECT DISTINCT ON (cand->>'content_hash')
                    jsonb_build_object(
                     'signal', 'chunk::' || (cand->>'content_hash'),
                     'kind', (SELECT t FROM tmpl)->'chunk_score'->>'kind',
                     'question',
                       (SELECT t FROM tmpl)->'chunk_score'->>'question',
                     'criteria',
                       (SELECT t FROM tmpl)->'chunk_score'->'criteria',
                     'template_name', 'chunk_score') AS f
               FROM fg,
                    jsonb_array_elements(
                      coalesce((SELECT r FROM rc)->'candidates',
                               '[]'::jsonb)) cand
              ORDER BY cand->>'content_hash'))) s),
  needed AS MATERIALIZED (                   -- 【DP6③】基族 ∪ 过滤行(signal
    SELECT coalesce(jsonb_agg(               -- 升序聚合;CASE 省 criteria 键
             CASE WHEN x.criteria IS NULL THEN   -- 形态与 DP2/DP5 同构)
               jsonb_build_object('signal', x.signal, 'kind', x.kind,
                                  'question', x.question,
                                  'template_name', x.template_name)
             ELSE
               jsonb_build_object('signal', x.signal, 'kind', x.kind,
                                  'question', x.question, 'criteria', x.criteria,
                                  'template_name', x.template_name)
             END ORDER BY x.signal), '[]'::jsonb) AS n
      FROM (SELECT signal, kind, question, criteria, template_name
              FROM v13_needed_judgments(p_sid)
             UNION ALL
            SELECT f->>'signal', f->>'kind', f->>'question', f->'criteria',
                   f->>'template_name'
              FROM jsonb_array_elements((SELECT f FROM frows)) f) x),
  groups AS MATERIALIZED (                   -- 【DP6④】仅 canonical 行(过滤
    SELECT coalesce(jsonb_agg(jsonb_build_object('projection_key', s.pkey, -- 族的组态
                                                 'state', s.state)      -- 在 resolve 侧构建,
                              ORDER BY s.pkey), '[]'::jsonb) AS g        -- 信封不携体)
      FROM (SELECT DISTINCT
              v13_projection_key(
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS pkey,
              v13_project_state(
                (SELECT c FROM ctx),
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS state
              FROM jsonb_array_elements((SELECT n FROM needed)) nr
             WHERE (nr.value->>'template_name')
                   NOT IN ('chunk_score','corpus_exists')) s),
  wm AS MATERIALIZED (
    SELECT (SELECT next_seq FROM sessions WHERE session_id = p_sid) AS sv,
           coalesce((SELECT max(seq) FROM events
                      WHERE session_id = p_sid), -1) AS mes),
  pol AS MATERIALIZED (
    SELECT route_policy_name AS rpn, route_policy_version AS rpv
      FROM sessions WHERE session_id = p_sid)
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

-- === L6 墓碑三:v13_resolve_judgments OR REPLACE(DP2 §3.6 体的 DP6 形态;
--     canonical 半边逐字保留[组选择/批选择加 NOT IN 腰带],filter 半边新增。
--     实施纪律:从 v13/envelope/v13_envelope.sql 加载态原文机械复制+增量。) ===
CREATE OR REPLACE FUNCTION v13_resolve_judgments(p_env jsonb,
                                                 p_max_batches int DEFAULT 1)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_sid    uuid := (p_env->>'sid')::uuid;
  v_bs     int;
  v_asked  int := 0; v_batches int := 0; v_hits int := 0;
  v_rejects int := 0;
  v_landed int := 0;
  v_failed boolean := false;
  v_rem    int;
  v_gap    jsonb; v_pkey text; v_state jsonb;
  v_batch  jsonb; v_payload jsonb; v_resp jsonb; v_usage jsonb;
  v_hash   text; v_canon jsonb; v_valid boolean; v_call uuid;
  v_tname  text; v_tmpl jsonb; v_res jsonb;
  v_t0     timestamptz; v_err text; r record;
  v_goal   text; v_fstate jsonb; v_frows jsonb; v_label text;
BEGIN
  IF p_max_batches IS NULL OR p_max_batches < 1 THEN
    RAISE EXCEPTION 'v13: p_max_batches must be >= 1 (unbounded = caller loop)';
  END IF;
  v_bs := (p_env->'budget'->>'batch_questions')::int;
  IF v_bs IS NULL OR v_bs < 1 THEN
    RAISE EXCEPTION
      'v13: envelope budget.batch_questions missing or invalid (%)', v_bs
      USING ERRCODE = 'V3002';
  END IF;

  IF jsonb_array_length(v13_gap(p_env)) > 0 THEN
    PERFORM pg_advisory_xact_lock(
      v13_lock_key(v_sid, p_env->>'candidate_set_hash'));
  END IF;

  LOOP
    v_gap := v13_gap(p_env);
    EXIT WHEN jsonb_array_length(v_gap) = 0 OR v_batches >= p_max_batches;

    -- (1) canonical consult(DP2 逐字;context 经 v13_row_context 族分发)
    FOR r IN SELECT g.value AS q FROM jsonb_array_elements(v_gap) g
              ORDER BY g.value->>'signal' LOOP
      v_hash := v13_judgment_hash(p_env, r.q->>'signal', r.q->>'kind',
                                  r.q->>'question', r.q->'criteria');
      v_canon := NULL; v_valid := false;
      SELECT c.answer INTO v_canon FROM judgment_cache c
       WHERE c.request_hash = v_hash;
      IF FOUND THEN
        BEGIN
          PERFORM v13_validate_answer(r.q->>'kind', v_canon, r.q->'criteria');
          v_valid := true;
        EXCEPTION WHEN SQLSTATE 'V3001' THEN
          v_valid := false;
        END;
      END IF;
      IF v_valid THEN
        v_tname := r.q->>'template_name';
        v_tmpl := p_env->'templates'->v_tname;
        INSERT INTO decisions (session_id, signal, kind, question, criteria,
                               context, answer, provider, model, request_hash,
                               status, answered_at, template_name,
                               template_version, answer_schema_version,
                               reused_from, call_id)
        VALUES (v_sid, r.q->>'signal', r.q->>'kind', r.q->>'question',
                r.q->'criteria', v13_row_context(p_env, r.q->>'signal'),
                v_canon, p_env->>'provider', p_env->>'model', v_hash,
                'cached', now(), v_tname, (v_tmpl->>'version')::int,
                (v_tmpl->>'answer_schema_version')::int, v_hash, NULL)
        ON CONFLICT (session_id, request_hash) DO UPDATE
          SET answer = EXCLUDED.answer
          WHERE decisions.answer IS NULL;
        v_hits := v_hits + 1;
      END IF;
    END LOOP;

    v_gap := v13_gap(p_env);
    EXIT WHEN jsonb_array_length(v_gap) = 0 OR v_batches >= p_max_batches;

    -- (2) canonical 组选择(DP2+腰带:仅 canonical 行——过滤族组态不进信封
    --     groups,其 projection pkey 与 canonical 族无碰撞但显式排除防依赖)
    SELECT min(v13_projection_key(
             p_env->'templates'->(g.value->>'template_name')->'projection'))
      INTO v_pkey
      FROM jsonb_array_elements(v_gap) g
     WHERE (g.value->>'template_name')
           NOT IN ('chunk_score','corpus_exists');

    IF v_pkey IS NOT NULL THEN
      -- (3)-(8) canonical 批(DP2 §3.6 逐字;批选择加同款 NOT IN 腰带)
      SELECT gg->'state' INTO v_state
        FROM jsonb_array_elements(p_env->'groups') gg
       WHERE gg->>'projection_key' = v_pkey;
      IF v_state IS NULL THEN
        RAISE EXCEPTION 'v13: group state % missing from envelope', v_pkey
          USING ERRCODE = 'V3002';
      END IF;
      SELECT jsonb_agg(q ORDER BY q->>'signal') INTO v_batch
        FROM (SELECT g.value AS q FROM jsonb_array_elements(v_gap) g
               WHERE (g.value->>'template_name')
                     NOT IN ('chunk_score','corpus_exists')
                 AND v13_projection_key(
                       p_env->'templates'->(g.value->>'template_name')
                       -> 'projection') = v_pkey
               ORDER BY g.value->>'signal' LIMIT v_bs) s;
      v_payload := jsonb_build_object('state', v_state, 'questions',
        (SELECT jsonb_object_agg(q->>'signal',
                      v13_question_wire(q->>'kind', q->>'question',
                                        q->'criteria'))
           FROM jsonb_array_elements(v_batch) q));
      IF p_env->>'timeout_ms' IS NOT NULL THEN
        PERFORM set_config('typesafe.timeout_ms', p_env->>'timeout_ms', true);
      END IF;
      v_t0 := clock_timestamp();
      BEGIN
        v_resp := typesafe_ask(v_payload->'state', v_payload->'questions');
      EXCEPTION
        WHEN query_canceled THEN
          IF coalesce(current_setting('statement_timeout', true), '0')
               IN ('0', '0ms') THEN
            RAISE;
          END IF;
          INSERT INTO judgment_calls (session_id, candidate_set_hash,
                                      projection_key, payload, payload_hash,
                                      provider, model, question_count,
                                      timeout_ms, latency_ms, status, error)
          VALUES (v_sid, p_env->>'candidate_set_hash', v_pkey, v_payload,
                  encode(digest(v_payload::text, 'sha256'), 'hex'),
                  p_env->>'provider', p_env->>'model',
                  jsonb_array_length(v_batch),
                  (p_env->>'timeout_ms')::int,
                  (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
                  'failed_timeout', SQLSTATE);
          v_failed := true; EXIT;
        WHEN OTHERS THEN
          RAISE;
      END;
      v_usage := v_resp->'usage';
      BEGIN
        IF jsonb_typeof(v_resp->'answers') IS DISTINCT FROM 'object' THEN
          RAISE EXCEPTION 'v13: response needs an answers object'
            USING ERRCODE = 'V3001';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(v_resp->'answers') k
                    WHERE NOT EXISTS (SELECT 1
                                        FROM jsonb_array_elements(v_batch) q
                                       WHERE q->>'signal' = k)) THEN
          RAISE EXCEPTION 'v13: response contains unknown answer signals'
            USING ERRCODE = 'V3001';
        END IF;
        FOR r IN SELECT q->>'signal' AS signal, q->>'kind' AS kind,
                        q->>'criteria' AS criteria
                   FROM jsonb_array_elements(v_batch) q LOOP
          PERFORM v13_validate_answer(r.kind, v_resp->'answers'->r.signal,
                                      r.criteria);
        END LOOP;
      EXCEPTION WHEN SQLSTATE 'V3001' THEN
        GET STACKED DIAGNOSTICS v_err = MESSAGE_TEXT;
        INSERT INTO judgment_calls (session_id, candidate_set_hash,
                                    projection_key, payload, payload_hash,
                                    provider, model, question_count,
                                    timeout_ms, usage, latency_ms, status,
                                    error)
        VALUES (v_sid, p_env->>'candidate_set_hash', v_pkey, v_payload,
                encode(digest(v_payload::text, 'sha256'), 'hex'),
                p_env->>'provider', p_env->>'model',
                jsonb_array_length(v_batch), (p_env->>'timeout_ms')::int,
                v_usage,
                (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
                'failed_validation', 'V3001: ' || v_err);
        v_failed := true; EXIT;
      END;
      INSERT INTO judgment_calls (call_id, session_id, candidate_set_hash,
                                  projection_key, payload, payload_hash,
                                  provider, model, question_count,
                                  timeout_ms, usage, latency_ms, status)
      VALUES (gen_random_uuid(), v_sid, p_env->>'candidate_set_hash', v_pkey,
              v_payload, encode(digest(v_payload::text, 'sha256'), 'hex'),
              p_env->>'provider', p_env->>'model',
              jsonb_array_length(v_batch), (p_env->>'timeout_ms')::int,
              v_usage,
              (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
              'succeeded')
      RETURNING call_id INTO v_call;
      v_landed := 0;
      FOR r IN SELECT q->>'signal' AS signal, q->>'kind' AS kind,
                      q->>'question' AS question, q->>'criteria' AS criteria,
                      q->>'template_name' AS tname
                 FROM jsonb_array_elements(v_batch) q LOOP
        v_hash := v13_judgment_hash(p_env, r.signal, r.kind, r.question,
                                    r.criteria);
        v_tmpl := p_env->'templates'->r.tname;
        INSERT INTO judgment_cache (request_hash, signal, kind, answer,
                                    provider, model, template_name,
                                    template_version, answer_schema_version,
                                    call_id)
        VALUES (v_hash, r.signal, r.kind, v_resp->'answers'->r.signal,
                p_env->>'provider', p_env->>'model', r.tname,
                (v_tmpl->>'version')::int,
                (v_tmpl->>'answer_schema_version')::int, v_call)
        ON CONFLICT (request_hash) DO NOTHING;
        SELECT c.answer INTO v_canon FROM judgment_cache c
         WHERE c.request_hash = v_hash;
        v_valid := true;
        BEGIN
          PERFORM v13_validate_answer(r.kind, v_canon, r.criteria);
        EXCEPTION WHEN SQLSTATE 'V3001' THEN
          v_valid := false;
        END;
        IF NOT v_valid THEN
          v_rejects := v_rejects + 1;
          v_asked := v_asked + 1;
          CONTINUE;
        END IF;
        INSERT INTO decisions (session_id, signal, kind, question, criteria,
                               context, answer, provider, model, request_hash,
                               status, answered_at, template_name,
                               template_version, answer_schema_version,
                               reused_from, call_id)
        VALUES (v_sid, r.signal, r.kind, r.question, r.criteria, v_state,
                v_canon, p_env->>'provider', p_env->>'model', v_hash,
                'answered', now(), r.tname, (v_tmpl->>'version')::int,
                (v_tmpl->>'answer_schema_version')::int, NULL, v_call)
        ON CONFLICT (session_id, request_hash) DO UPDATE
          SET answer = EXCLUDED.answer
          WHERE decisions.answer IS NULL;
        v_asked := v_asked + 1;
        v_landed := v_landed + 1;
      END LOOP;
      v_batches := v_batches + 1;
      IF v_landed = 0 THEN
        v_failed := true; EXIT;      -- no-progress(DP2 步(8) 逐字)
      END IF;
    ELSE
      -- (9) DP6 filter 面:存在性先行 → 闸 → per-chunk 批(OQ3/OQ4)
      -- 【体缺守卫(键-态绑定)】候选全集体在场(v13_filter_bodies_present,
      -- 与存在性 state 构造同款查找):任一体缺 → 本 pass 整个 filter 面
      -- 跳过——存在性不问(全集键下缺体问出的「无答案」会经缓存回流,
      -- 封死同体重摄取后的新证据)、per-chunk 不问(不变量 4 存在性严格
      -- 先行不破)、过滤行剔出 remaining(不问不缓存不消费;下一信封
      -- 自然收敛,防 worker/advance ③ 空转)。
      IF NOT v13_filter_bodies_present(p_env) THEN
        EXIT;   -- 体缺守卫:filter 面本 pass 不可填
      END IF;
      IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_gap) g
                      WHERE g.value->>'signal' = 'corpus_exists')
         AND (NOT v13_filter_gate_open(p_env)
              OR v13_filter_fillable(p_env) = 0) THEN
        EXIT;   -- 闸关或无可填 chunk 行:per-chunk 不可填,零 ask 终止(防
      END IF;    -- worker 空转;remaining 同口径,advance ③ 不再建 judge effect)
      v_goal := v13_goal_text(v_sid, p_env->>'goal_hash');
      LOOP
        EXIT WHEN v_batches >= p_max_batches;
        v_gap := v13_gap(p_env);
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_gap) g
                    WHERE g.value->>'signal' = 'corpus_exists') THEN
          -- 存在性批:1 问;state=查询全文+全候选体(排序去重)
          v_fstate := (SELECT v13_project_state(
                         jsonb_build_object(
                           'query', v_goal,
                           'chunks', coalesce(jsonb_agg(
                             jsonb_build_object('content_hash', x.h,
                                                'body', x.b)
                               ORDER BY x.h), '[]'::jsonb)),
                         p_env->'templates'->'corpus_exists'->'projection')
                        FROM (SELECT DISTINCT cand->>'content_hash' AS h,
                                     (SELECT c.body FROM chunks c
                                       WHERE c.content_hash =
                                             cand->>'content_hash'
                                       ORDER BY c.source_hash, c.chunk_no
                                       LIMIT 1) AS b
                                FROM jsonb_array_elements(
                                       p_env->'candidates') cand) x
                       WHERE x.b IS NOT NULL);
          -- 键-态 belt:态体基数必须等于冻结候选去重基数(右值为信封冻结
          -- 数据的纯计算,零活表读)——READ COMMITTED 下守卫与 state 构造
          -- 是两条语句级快照,竞态窗内体缺时 WHERE b IS NOT NULL 退化为静默
          -- 丢行(即 P1-2 死法);belt 拦下,视同守卫:退出过滤循环,外层
          -- 守卫以新快照复拦后整体终止,本 pass 不问不缓存。
          IF jsonb_array_length(coalesce(v_fstate->'chunks', '[]'::jsonb))
             <> (SELECT count(DISTINCT cand->>'content_hash')
                   FROM jsonb_array_elements(p_env->'candidates') cand) THEN
            EXIT;  -- 态缺体(竞态 belt):filter 面本 pass 不可填
          END IF;
          v_frows := (SELECT coalesce(jsonb_agg(
                        g.value ORDER BY g.value->>'signal'), '[]'::jsonb)
                        FROM jsonb_array_elements(v_gap) g
                       WHERE g.value->>'signal' = 'corpus_exists');
          v_label := 'corpus_exists';
        ELSIF v13_filter_gate_open(p_env) THEN
          -- per-chunk 批:≤v_bs 行(signal 升序=hash 升序,不变量 7)
          v_frows := (SELECT coalesce(jsonb_agg(
                        g.value ORDER BY g.value->>'signal'), '[]'::jsonb)
                        FROM (SELECT g.value
                                FROM jsonb_array_elements(v_gap) g
                               WHERE g.value->>'signal' LIKE 'chunk::%'
                                 AND EXISTS (SELECT 1 FROM chunks c
                                              WHERE c.content_hash =
                                                    substr(g.value->>'signal',
                                                           8))
                               ORDER BY g.value->>'signal'
                               LIMIT v_bs) s);
          EXIT WHEN jsonb_array_length(v_frows) = 0;
          v_fstate := (SELECT v13_project_state(
                         jsonb_build_object('query', v_goal, 'chunks', c.ch),
                         p_env->'templates'->'chunk_score'->'projection')
                        FROM (SELECT coalesce(jsonb_agg(
                                 jsonb_build_object(
                                   'content_hash',
                                     substr(q->>'signal', 8),
                                   'body',
                                     (SELECT c2.body FROM chunks c2
                                       WHERE c2.content_hash =
                                             substr(q->>'signal', 8)
                                       ORDER BY c2.source_hash, c2.chunk_no
                                       LIMIT 1))
                                   ORDER BY q->>'signal'), '[]'::jsonb) AS ch
                                FROM jsonb_array_elements(v_frows) q) c);
          v_label := 'chunk_score';
        ELSE
          EXIT;                      -- 闸关:per-chunk 不可填
        END IF;

        v_res := v13_filter_ask(p_env, v_fstate, v_frows, v_label);
        v_asked   := v_asked   + coalesce((v_res->>'asked')::int, 0);
        v_rejects := v_rejects + coalesce((v_res->>'rejects')::int, 0);
        v_landed  := coalesce((v_res->>'landed')::int, 0);
        v_batches := v_batches + 1;
        IF (v_res->>'failed')::boolean OR v_landed = 0 THEN
          v_failed := true; EXIT;    -- α/β 族或 no-progress(DP2 同款)
        END IF;
      END LOOP;
    END IF;
  END LOOP;

  -- remaining(闸感知+体缺感知口径):canonical 行 +(守卫过时)存在性缺口
  -- +(闸开时)可填 chunk 行;守卫不过→存在性缺口与全部过滤行剔出
  -- (本 pass 不可填,不问不缓存不消费;下一信封自然收敛,防 worker/
  -- advance ③ 空转)
  v_rem := (SELECT count(*) FROM jsonb_array_elements(v13_gap(p_env)) g
             WHERE g.value->>'signal' NOT LIKE 'chunk::%'
               AND g.value->>'signal' <> 'corpus_exists');
  IF v13_filter_bodies_present(p_env) THEN
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(v13_gap(p_env)) g
                WHERE g.value->>'signal' = 'corpus_exists') THEN
      v_rem := v_rem + 1;
    END IF;
    IF v13_filter_gate_open(p_env) THEN
      v_rem := v_rem + v13_filter_fillable(p_env);
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'asked_questions', v_asked, 'asked_batches', v_batches,
    'cache_hits', v_hits, 'readback_rejects', v_rejects,
    'remaining', v_rem, 'failed', v_failed,
    'gate_open', v13_filter_gate_open(p_env));
END $$;
-- worker 慢路契约零改动(DP1 §1.3 DP6 行):claim→resolve(env,1)→renew→
-- complete 循环原样;canonical consult 在每 pass 前置(过滤行缓存命中含内);
-- parse 出口七键 schema 不变(remaining/gate_open 只经 resolve 直调返回,
-- parse 仍只复制 asked/remaining/failed 族——B2/B8 键集断言不受扰)。

-- === L7 墓碑四:v13_assemble_manifest OR REPLACE(DP3 §3.4+DP5 L7 体的
--     DP6 形态;实施纪律:从 v13/recall/v13_recall.sql 加载态原文机械复制,
--     仅按【DP6】标注的三处增量编辑:①rc2/fc 两 CTE;②qside candidates 的
--     decision_id 填充;③jud 消费集+final_action 真值。其余 CTE 逐字不动。) ===
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
         encode(digest(coalesce((cs.c -> 'tools')::text, ''), 'sha256'), 'hex'),
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
), rc2 AS MATERIALIZED (                     -- 【DP6①】候选/digest 单源物化
  SELECT v13_recall_candidates(p_sid)->'candidates' AS cands
), fc AS MATERIALIZED (                      -- 【DP6①】goal_hash/digest 单点
  SELECT v13_goal_hash(p_sid) AS gh,
         v13_candidates_digest(v13_recall_candidates(p_sid)
                               ->'candidates') AS dig
), qside AS MATERIALIZED (                   -- 【DP6②】decision_id 填充:
  SELECT jsonb_build_object(                 -- 上下文等值 join(零哈希重算/
    'query_artifact_id', (SELECT a FROM goal_addr), -- 零 GUC/零信封依赖,
    'candidates', (SELECT coalesce(jsonb_agg(     -- 不变量 6)
                     c || jsonb_build_object('decision_id',
                       (SELECT d.decision_id FROM decisions d
                         WHERE d.session_id = p_sid
                           AND d.signal = 'chunk::' || (c->>'content_hash')
                           AND d.context =
                                 v13_filter_ref(fc.gh, c->>'content_hash')
                           AND d.answer IS NOT NULL
                           AND d.status IN ('answered','cached')
                         LIMIT 1))
                       ORDER BY (c->>'bm25')::numeric DESC,
                                c->>'content_hash' ASC), '[]'::jsonb)
                     FROM jsonb_array_elements((SELECT cands FROM rc2)) c, fc)
  ) AS q
), jud AS MATERIALIZED (                     -- 【DP6③】消费集=候选 decision_id
  SELECT coalesce(jsonb_agg(row ORDER BY row->>'decision_id), -- ∪存在性行;
             '[]'::jsonb) AS j               -- final_action 真值(DP3 词表内)
  FROM (SELECT jsonb_build_object(
             'decision_id',    d.decision_id,
             'epoch',          d.epoch,
             'request_hash',   d.request_hash,
             'template_name',  d.template_name,
             'template_version', d.template_version,
             'raw_verdict',    d.answer,
             'final_action',   CASE
               WHEN d.signal = 'corpus_exists'
                 THEN v13_existence_action(d.answer)
               ELSE (v13_chunk_filter_action(p_sid, fc.gh, fc.dig,
                        d.context->'chunk'->>'content_hash'))->>'action'
             END) AS row
          FROM decisions d, fc
         WHERE d.answer IS NOT NULL
           AND d.status IN ('answered','cached')
           AND ( d.decision_id::text IN (
                  SELECT cand->>'decision_id'
                    FROM qside,
                         jsonb_array_elements(qside.q->'candidates') cand
                   WHERE cand->>'decision_id' IS NOT NULL)
              OR ( d.signal = 'corpus_exists'
                   AND d.context = jsonb_build_object(
                         'query_content_hash', fc.gh,
                         'candidates_digest',  fc.dig)))) s
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

-- === L8 墓碑五:v13_chunk_referenced OR REPLACE(DP4 §3.1 体的等值换载:
--     decisions 半边 ->>'…'=' 改 '->''chunk'' @> {content_hash}' ——语义
--     逐字节等价(行内 chunk 恒为恰一键对象,由 v13_filter_ref 构造半边
--     钉死),jsonb_path_ops GIN 可吃;artifacts 半边逐字不动。DP4 契约
--     「届时补该路径的 GIN 索引」的使能半边,附 A #6。) ===
CREATE OR REPLACE FUNCTION v13_chunk_referenced(p_hash text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM artifacts a
                  WHERE a.kind = 'context'
                    AND a.inline->'query_side'->'candidates'
                        @> jsonb_build_array(
                             jsonb_build_object('content_hash', p_hash)))
      OR EXISTS (SELECT 1 FROM decisions d
                  WHERE d.context->'chunk'
                        @> jsonb_build_object('content_hash', p_hash));
$$;

-- === L9 索引(§1.1 形态⑥:纯追加,零 DDL/约束改动) ===
-- 体按哈希查找的读路径索引(过滤面热路径;k≤64 次/resolve;DP4 建表时
-- content_hash 无索引——非唯一,跨源同文双行合法)
CREATE INDEX ix_chunks_content_hash ON chunks (content_hash);
-- DP4 契约「届时补该路径的 GIN 索引」:decisions.context->'chunk' 子对象
-- 的 containment 探测(v13_chunk_referenced 消费面背书)
CREATE INDEX ix_decisions_chunk_ref ON decisions
  USING gin ((context->'chunk')) WHERE context->'chunk' IS NOT NULL;

-- === L10 种子(版本父表机制,DP2 §3.8 先例;cgr 断言一律相对比较) ===
INSERT INTO v13_judgment_template_versions (template_name, template_version)
VALUES ('corpus_exists', 1), ('chunk_score', 1);

INSERT INTO judgment_templates (template_name, template_version, kind,
                                question, criteria, answer_schema_version,
                                projection, provider, model, writer,
                                wire_version, canon_version, epoch) VALUES
('corpus_exists', 1, 'noul',
 'Given `state.query` (the user request) and `state.chunks` (the retrieved passages), does the corpus contain information that can answer the request?',
 NULL, 1, '["query","chunks"]'::jsonb, NULL, NULL, 'v13_resolve', 1, 1,
 'pre-finalize'),
('chunk_score', 1, 'score',
 'Given `state.query` (the user request), rate how relevant the passage in `state.chunks` keyed by this question signal is to answering the request.',
 jsonb_build_array(
   'Not relevant: unrelated to the request.',
   'Marginally relevant: touches the topic but does not help answer.',
   'Relevant: supports a partial answer.',
   'Directly relevant: contains content that directly answers the request.'),
 1, '["query","chunks"]'::jsonb, NULL, NULL, 'v13_resolve', 1, 1,
 'pre-finalize');

UPDATE v13_judgment_template_versions SET state='frozen'
 WHERE template_name IN ('corpus_exists','chunk_score')
   AND template_version = 1;
   -- freeze 触发器检查内容行在场(✓ 均已插)+行级 cgr ×2

INSERT INTO v13_policies (name, version, value, active) VALUES
('chunk_filter', 1,
 '{"gate_closed_hi":0.30,"gate_open_lo":0.40,"score_include_lo":2,"score_conf_lo":0.50}'::jsonb,
 true);
   -- 闸带/评分带(OQ6;v1 与 chunk_score v1 四级 rubric 配套:翻版=两行同批)

-- judgment_defaults v2:填 F1 两点(OQ6 方向;DP3 契约「DP6 填值」)。
-- 翻 active 顺序=turn 10 #64 纪律:先 INSERT inactive→双 UPDATE 翻;
-- jdef_ver 1→2 ⇒ 全域恰一次 refresh(DP3 OQ1 既判语义,gate 断言)。
INSERT INTO v13_policies (name, version, value, active) VALUES
('judgment_defaults', 2,
 '{"points":{"chunk_score":{"missing":"include","timeout":"include","review":"degrade"},"corpus_exists":{"missing":"include","timeout":"include","review":"include"}},"actions":["include","exclude","degrade","fail"]}'::jsonb,
 false);
UPDATE v13_policies SET active=false
 WHERE name='judgment_defaults' AND version=1;
UPDATE v13_policies SET active=true
 WHERE name='judgment_defaults' AND version=2;

-- === L11 ACL 全量块(文件真末尾;不变量 10) ===
REVOKE EXECUTE ON FUNCTION
  v13_candidates_digest(jsonb),
  v13_filter_ref(text,text), v13_existence_ref(jsonb),
  v13_row_context(jsonb,text), v13_require_filter_templates(jsonb),
  v13_goal_text(uuid,text), v13_filter_defaults_action(text,text),
  v13_existence_action(jsonb), v13_filter_gate_open(jsonb),
  v13_filter_fillable(jsonb), v13_filter_bodies_present(jsonb),
  v13_chunk_filter_action(uuid,text,text,text),
  v13_filter_trace(uuid), v13_filter_ask(jsonb,jsonb,jsonb,text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_candidates_digest(jsonb),
  v13_filter_ref(text,text), v13_existence_ref(jsonb),
  v13_row_context(jsonb,text), v13_require_filter_templates(jsonb),
  v13_goal_text(uuid,text),
  v13_chunk_filter_action(uuid,text,text,text),
  v13_filter_trace(uuid)
TO v13_recall, v13_resolve, v13_route;
             -- 纯读/审计/装配链三角色(trace=审计面;chunk_filter_action=
             -- 装配 jud CTE 与 trace 共用;row_context 在 judgment_hash
             -- 链上——三角色既有 judgment_hash 消费面同款)
GRANT EXECUTE ON FUNCTION
  v13_filter_defaults_action(text,text), v13_existence_action(jsonb),
  v13_filter_gate_open(jsonb), v13_filter_fillable(jsonb),
  v13_filter_bodies_present(jsonb),
  v13_filter_ask(jsonb,jsonb,jsonb,text)
TO v13_resolve;
             -- resolve 内部件(ask 宏含 typesafe_ask 调用链——与 DP2
             -- typesafe ACL 只授 resolve 同界);existence_action 亦被
             -- 装配消费——route 侧经 assemble_manifest体内调用(装配函数
             -- 为三角色 EXECUTE,体内链随 invoker)——补授 route:
GRANT EXECUTE ON FUNCTION v13_existence_action(jsonb) TO v13_route;
-- OR REPLACE 五件 ACL 经 OID 保留,不重授(judgment_hash/resolve=三角色/
-- resolve 既有面;envelope/assemble=三角色;chunk_referenced=DP4 既有面)。

COMMIT;
```

### 3.2 文件二 `v13/memory/v13_memory.sql`(第 11 位;三层记忆栈)

```sql
BEGIN;

-- =========================================================================
-- DP6 memory (v13_memory.sql): transcript verbatim layer (§4.4) + watermark
-- freshness (F10) + structured layer stannum index on decisions(question).
-- Design: docs/designs/v13-context-on-pg.md §4.4/§9/§10 (p99 gate). Tutorial
-- ch13:58-59 (tick), ch13:64-79 (sweeper, not metronome). Contracts: DP4 ①③
-- (independent table/index), DP5 (post-characterize stannum library).
-- File order = load order. Owner-plane builders; zero DEFINER (DP4 OQ5 同构).
-- =========================================================================

-- === 逐字层投影表(§9 五列逐字;独立表独立索引=文档/记忆语料分区,
--     DP4 契约⑦;v1 每策展事件一行 seq_from=seq_to,OQ8)。行不可变
--     (UPDATE 拒);DELETE 留给全量重建(owner 平面——无 retention 引用面,
--     记忆行不被 manifest/decisions 引用)。自证 CHECK+FK 源事件。 ===
CREATE TABLE transcript_chunks (
  session_id   uuid NOT NULL REFERENCES sessions (session_id),
  seq_from     bigint NOT NULL CHECK (seq_from >= 0),
  seq_to       bigint NOT NULL CHECK (seq_to >= seq_from),
  body         text NOT NULL CHECK (octet_length(body) > 0),
  content_hash text NOT NULL,
  PRIMARY KEY (session_id, seq_from),
  FOREIGN KEY (session_id, seq_from) REFERENCES events (session_id, seq),
  CONSTRAINT v13_transcript_hash_selfcheck
    CHECK (content_hash = v13_body_hash(body))
);

-- 记忆语料索引(stannum 默认配置,单索引纪律;OQ9:记忆语料 CJK 为主,
-- 刻画后直接 stannum=§7 既裁路径;tsvector 对 CJK 记忆零召回=玩具)
CREATE INDEX ix_transcript_stannum ON transcript_chunks USING stannum (body);

CREATE FUNCTION v13_transcript_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION
    'v13: transcript_chunks rows are immutable (% on % %/%)',
    TG_OP, TG_TABLE_NAME, OLD.session_id, OLD.seq_to;
END $$;
CREATE TRIGGER trg_transcript_immutable
  BEFORE UPDATE ON transcript_chunks
  FOR EACH ROW EXECUTE FUNCTION v13_transcript_immutable();

-- === 水印(OQ5):投影覆盖上界(仅策展族事件计入分母——编排事件
--     (turn/route/effect_done)永不投影,计入则 lag 恒涨永降级) ===
CREATE FUNCTION v13_transcript_watermark(p_sid uuid) RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT coalesce(max(seq_to), -1) FROM transcript_chunks
   WHERE session_id = p_sid;
$$;

-- 新鲜度谓词(F10 的载体):lag=max 策展 seq−watermark;超界→degraded
-- +NOTICE(运维可见);消费契约(§1.4 DP7④):degraded=true 时消费侧
-- 不得以记忆层为可靠召回面,须落审计事件并降级——recall 平面纯 SELECT
-- (DP1 角色分裂)不可写事件,附 A #9。
CREATE FUNCTION v13_transcript_freshness(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_wm bigint; v_max bigint; v_lag bigint; v_cap jsonb; v_n int;
BEGIN
  SELECT coalesce(max(seq_to), -1) INTO v_wm FROM transcript_chunks
   WHERE session_id = p_sid;
  SELECT coalesce(max(seq), -1) INTO v_max FROM events
   WHERE session_id = p_sid AND type IN ('user/message','llm/message');
  v_lag := v_max - v_wm;
  v_cap := v13_policy('memory_stack');
  IF v_cap IS NULL
     OR jsonb_typeof(v_cap->'max_lag_events') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid memory_stack policy shape'
      USING ERRCODE = 'V3006';
  END IF;
  v_n := (v_cap->>'max_lag_events')::int;
  IF v_n < 0 THEN
    RAISE EXCEPTION 'v13: invalid memory_stack policy values'
      USING ERRCODE = 'V3006';
  END IF;
  IF v_lag > v_n THEN
    RAISE NOTICE
      'v13: transcript projection lag % exceeds max_lag_events % for session % (memory recall degraded)',
      v_lag, v_n, p_sid;
  END IF;
  RETURN jsonb_build_object('watermark', v_wm, 'max_curated_seq', v_max,
    'lag', v_lag, 'max_lag', v_n, 'degraded', v_lag > v_n);
END $$;

-- === tick 批量构建(ch13:58-59 逐字形态:每 tick 至多 100 行):增量
--     (seq>watermark 的策展事件,空体跳过)、幂等(ON CONFLICT DO
--     NOTHING)、确定性(session_id 升序逐会话;v1 会话全扫——空转成本
--     台账触发项,§7)。可重建=DELETE 后重跑(owner 平面)。 ===
CREATE FUNCTION v13_rebuild_transcript_chunks(p_limit int DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_rows int := 0; v_n int; v_wm bigint; r record;
BEGIN
  IF p_limit IS NULL OR p_limit < 1 THEN
    RAISE EXCEPTION 'v13: rebuild limit must be >= 1'
      USING ERRCODE = 'V3006';
  END IF;
  FOR r IN SELECT e.session_id, max(e.seq) AS mseq
             FROM events e
            WHERE e.type IN ('user/message','llm/message')
            GROUP BY e.session_id
            ORDER BY e.session_id
  LOOP
    EXIT WHEN v_rows >= p_limit;
    SELECT coalesce(max(t.seq_to), -1) INTO v_wm
      FROM transcript_chunks t WHERE t.session_id = r.session_id;
    IF r.mseq <= v_wm THEN
      CONTINUE;                      -- 该会话已投影到头
    END IF;
    INSERT INTO transcript_chunks (session_id, seq_from, seq_to, body,
                                   content_hash)
    SELECT e.session_id, e.seq, e.seq, e.payload->>'text',
           v13_body_hash(e.payload->>'text')
      FROM events e
     WHERE e.session_id = r.session_id
       AND e.type IN ('user/message','llm/message')
       AND e.seq > v_wm
       AND coalesce(e.payload->>'text', '') <> ''
     ORDER BY e.seq
     LIMIT least(p_limit - v_rows, 100)
    ON CONFLICT (session_id, seq_from) DO NOTHING;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_rows := v_rows + v_n;
  END LOOP;
  RETURN jsonb_build_object('rows_projected', v_rows);
END $$;

-- === 记忆召回 reader(签名冻结 (uuid,text,int)→TABLE 三列,§1.4 DP7④):
--     只读 transcript_chunks(F10 fail-closed——零 events 回退读路径);
--     per-session 隔离(记忆是会话私有面);==>' 只在本函数族体内经
--     EXECUTE(三禁;文件 11 源码扫描计数=恰 1);入口 v13_tinql_terms
--     自产文法守卫(DP5 同款);排序 分值 DESC,content_hash ASC 终裁。 ===
CREATE FUNCTION v13_transcript_recall(p_sid uuid, p_tinql text, p_k int)
RETURNS TABLE(content_hash text, bm25 numeric, seq_from bigint)
LANGUAGE plpgsql STABLE AS $$
DECLARE v_cnt bigint;
BEGIN
  IF p_tinql IS NULL OR p_k IS NULL OR p_k < 1 OR p_k > 1024 THEN
    RAISE EXCEPTION 'v13: v13_transcript_recall args out of bounds'
      USING ERRCODE = 'V3006';
  END IF;
  IF p_tinql = '' THEN RETURN; END IF;
  PERFORM v13_tinql_terms(p_tinql);           -- fail-closed 信封(G-ctx3 同族)
  RETURN QUERY EXECUTE
    'SELECT t.content_hash, '
 || 'stannum.full_score(t.ctid)::numeric AS bm25, t.seq_from '
 || 'FROM transcript_chunks t '
 || 'WHERE t.session_id = $1 AND t.body ==> $3 '
 || 'ORDER BY bm25 DESC, t.content_hash ASC LIMIT $2'
    USING p_sid, p_k, p_tinql;
END $$;

-- === 结构化层(§4.4:stannum 建在 decisions.question——append-only
--     不可变列=不可变段,零 fold churn 的「理想负载」;消费者=语义决策
--     缓存,§12 台账,机制不做) ===
CREATE INDEX ix_decisions_question_stannum ON decisions USING stannum (question);

-- === 记忆面校验器(v13_verify_chunks 同族;手动可调+gate;夜跑 cron 扩展
--     不做——DP4 job 保持唯一 verify 面,§7 台账) ===
CREATE FUNCTION v13_verify_memory(p_raise boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_bad bigint; v_orphan bigint; v_pol boolean;
  v_ts_bad bigint; v_dq_bad bigint;
  v_checks jsonb; v_all_ok boolean;
BEGIN
  SELECT count(*) INTO v_bad FROM transcript_chunks
   WHERE content_hash IS DISTINCT FROM v13_body_hash(body);   -- ①自证
  SELECT count(*) INTO v_orphan FROM transcript_chunks t
   WHERE NOT EXISTS (SELECT 1 FROM events e
                      WHERE e.session_id = t.session_id
                        AND e.seq = t.seq_from);               -- ②源事件在
  SELECT EXISTS (SELECT 1 FROM v13_policies
                  WHERE name = 'memory_stack' AND active)
    INTO v_pol;                                               -- ③策略行在场
  SELECT count(*) INTO v_ts_bad                               -- ④transcript 索引
    FROM stannum.verify_index('ix_transcript_stannum'::regclass, true)
   WHERE severity IN ('error','warning');
  SELECT count(*) INTO v_dq_bad                               -- ⑤decisions 索引
    FROM stannum.verify_index('ix_decisions_question_stannum'::regclass, true)
   WHERE severity IN ('error','warning');
  v_checks := jsonb_build_array(
    jsonb_build_object('name','self_cert','ok', v_bad = 0,
      'detail', jsonb_build_object('violations', v_bad)),
    jsonb_build_object('name','source_events','ok', v_orphan = 0,
      'detail', jsonb_build_object('violations', v_orphan)),
    jsonb_build_object('name','policy_present','ok', v_pol,
      'detail', jsonb_build_object('name', 'memory_stack')),
    jsonb_build_object('name','transcript_verify_index','ok', v_ts_bad = 0,
      'detail', jsonb_build_object('findings', v_ts_bad)),
    jsonb_build_object('name','decisions_verify_index','ok', v_dq_bad = 0,
      'detail', jsonb_build_object('findings', v_dq_bad)));
  v_all_ok := NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_checks) c
                           WHERE NOT (c->>'ok')::boolean);
  IF p_raise AND NOT v_all_ok THEN
    RAISE EXCEPTION 'v13: verify_memory failed: %', v_checks
      USING ERRCODE = 'V3006';
  END IF;
  RETURN jsonb_build_object('version', 1, 'checks', v_checks,
                            'all_ok', v_all_ok);
END $$;

-- === 策略种子(滞后上界,F10) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('memory_stack', 1, '{"max_lag_events":16}'::jsonb, true);

-- === tick=扫地僧(ch13:58-59;调度是行不是节拍器——turn 推进仍靠
--     settle,DP4 §3.7 守卫降级同款;builder 恒手动可调,正确性零依赖) ===
DO $cron$
DECLARE v_ext boolean;
BEGIN
  BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
  EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'v13: pg_cron unavailable (%) — transcript sweep falls back to external scheduler; v13_rebuild_transcript_chunks() stays callable', SQLERRM;
    RETURN;
  END;
  IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'v13-sweep-transcript') THEN
    PERFORM cron.schedule('v13-sweep-transcript', '*/5 * * * *',
                          $job$SELECT v13_rebuild_transcript_chunks(100)$job$);
  END IF;
END
$cron$;
-- 本 stage 库 cron.job 恰两条(DP4 verify + 本 transcript sweep);
-- ch13 四 job 全景的 requeue/recover 仍归驱动(§12 YAGNI 触发未至,附 A #8)。

-- === ACL 全量块(文件真末尾) ===
REVOKE EXECUTE ON FUNCTION
  v13_transcript_watermark(uuid), v13_transcript_freshness(uuid),
  v13_transcript_recall(uuid,text,int),
  v13_rebuild_transcript_chunks(int), v13_verify_memory(boolean),
  v13_transcript_immutable()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_transcript_watermark(uuid), v13_transcript_freshness(uuid),
  v13_transcript_recall(uuid,text,int)
TO v13_recall, v13_resolve, v13_route;
             -- 读面三角色(未来装配/审计消费;recall=reader 主消费面)
GRANT SELECT ON transcript_chunks TO v13_recall, v13_resolve, v13_route;
-- 写/运维面(v13_rebuild_transcript_chunks/v13_verify_memory):仅 owner
-- (cron job 以 owner 身份跑;DP4 chunks 同构);transcript_chunks DML 对
-- 运行角色零授权(gate N 组负向);触发器函数 REVOKE 后仅属主可挂。

COMMIT;
```

### 3.3 stage 四件与 load.py

照 DP3/DP4/DP5 §3.8 形制,两 stage 各四件:

- `v13/filter/`:SQL=§3.1 全文;`setup_db.py`(DROP-CREATE 库 `agent_v13_filter`;`files_through('filter')` 加载十文件;超级用户连接,事件触发器/角色/策略 INSERT 前置同 DP2–DP5;末尾 import 复用 `v13/resolve/setup_db.py` 两个部署探针);`test_filter.py`(§4 A–H 组);`README.md`(机制+运维纪律,§4 末清单)。
- `v13/memory/`:SQL=§3.2 全文;`setup_db.py`(DROP-CREATE 库 `agent_v13_memory`;`files_through('memory')` 加载十一文件;**stannum 前置探针**(DP5 characterize 同款:`SELECT 1 FROM pg_available_extensions WHERE name='stannum'`,失败打印回退指引退出非 0——记忆 stage 依赖 stannum,fail-closed);`test_memory.py`(§4 I–N 组);`README.md`。
- `v13/load.py`:SQL_LOAD_ORDER 追加 `'filter/v13_filter.sql'`(第 10)与 `'memory/v13_memory.sql'`(第 11);`STAGE_THROUGH["filter"] = 10`、`STAGE_THROUGH["memory"] = 11`。零改动既有行。

---

## 4. 里程碑与 gate

两里程碑两 stage:命令形态 `uv run python v13/filter/test_filter.py` / `uv run python v13/memory/test_memory.py`,退出码 0=通过。**提交前全部前序 stage gate 复跑**(各自库前缀切片不加载本两文件,防回归的结构性保证,AGENTS.md 前置条件 1):里程碑 1(filter)前跑 DP1 四 stage+DP2+DP3+DP4+DP5 两 stage;里程碑 2(memory)前另跑 filter stage。

**断言纪律(DP1–DP5 原样沿用)**:fixture 走真实链路——语料经 DP4 驱动器四步摄取、事件经 v13_append_event、parse/advance 经 DP1 真实函数、manifest 经 DP3 refresh settle 真实链路、mock 判断经 `SET typesafe.provider='mock'` 全程;「零外部调用」毒化法联立 `failed=false` ∧ ask 计数=0(DP1 P1-8);外部调用计数=judgment_calls 行数(mock 计数);cgr/revision/策略断言一律相对比较;模板/策略版本分配器(=coalesce(max(version),0)+1,测试内 SQL;测毕还原);连接统一 SET typesafe.provider/model(fail-closed 前置)。**mock 构建器扩展(DP6)**:在 DP2「按 kind 生成合法答案」之上加逐 signal 覆写——existence 答案按 fixture 钉 noul 值(0.10/0.35/0.85 三档供闸门三态)、chunk_score 按 fixture 钉 score/confidence(供评分带与 review 带);mock 只存在于测试 Python(G-ctx1-5 同规)。

### G-ctx4 原文映射(§10 逐条)

| §10 G-ctx4 原文 | 断言落点 |
|---|---|
| 存在性 Noul 先行(语料无答案时 Score 外部调用=0,mock 计数) | C1(先行序)/C2(闸关零 Score——主断言)/C3(F2 陈旧无答案不复用) |
| 同 query×chunk 二次零外部调用(mock 计数) | D1 |
| per-chunk 缓存跨 session 复用(reused_from 正确) | D2 |
| §4.4 行:p99 events INSERT 延迟有/无投影构建对比 | L 组 |

### A 组 · 模板/策略/defaults(F1 载体)

| # | 断言 | 对应 |
|---|---|---|
| A1 | 两族种子:corpus_exists v1(noul/criteria NULL/题文逐字硬编码对照)/chunk_score v1(score/四级 criteria 逐字)均 frozen、epoch='pre-finalize'、projection='["query","chunks"]'、provider/model NULL、writer='v13_resolve';freeze 相对 bump cgr(内容行×2+freeze×2);追加同版本内容行 ✗(insert_guard) | §3.1 L10 |
| A2 | judgment_defaults v2:active 行=v2;`v13_judgment_defaults_check(v2)` 直调过(两点三态恰等/词表四值);token jdef_ver=2;手插缺 state 键 v3 → check 拒 V3003(DP3 校验器既有面,测毕还原) | OQ6/DP3 契约 |
| A3 | chunk_filter 形状 fail-closed:缺 gate_open_lo/值为字符串/hi≥lo/conf_lo>1 各形态 → v13_existence_action/v13_chunk_filter_action 直调 V3006(种子翻行构造,测后回滚) | §3.1 L2 |
| A4 | defaults 运行期 fail-closed:手插缺 chunk_score 点的 defaults v3 翻 active → `v13_filter_defaults_action('chunk_score','missing')` → V3006;还原 v4(=v2 值) | §3.1 L2/F1 |

### B 组 · 信封集成(OQ2)

| # | 断言 | 对应 |
|---|---|---|
| B1 | 过滤行在场:语料+goal fixture → envelope.needed 含 corpus_exists 恰一行+chunk::<h> 每候选恰一行(=rc.candidates 去重集);needed_count 相应;全部 signal(base∪filter)互异 | §3.1 L5 |
| B2 | 跨源同文去重:两源摄取同体文档 → 过滤行恰一份;manifest candidates 仍两行(DP5 面不动,记注) | 内容寻址 |
| B3 | 空候选:无 goal(空会话)→ 过滤行零条(存在性不问——空集闸门无意义,OQ/附 A #12);DP5 D4 等价面复测(k=0/candidates=[]) | §3.1 L5 |
| B4 | groups 仅 canonical:groups 数组零过滤族 pkey;canonical 组与 DP5 形态一致(对照 fixture:模板 projection='["*"]' 的组态原样) | §3.1 L5 |
| B5 | 20 键集恰等(M2-9 包含性);csh 吸收过滤行:同语料同 goal 两 parse → csh 相等;摄取新文档 → csh 变(DP5 D2 扩展复测) | 不变量 8 |
| B6 | candidates 键与直调 `v13_recall_candidates(sid)->'candidates'` 逐字节相等(合并层未重推导的行为证明——单一推导点) | DP5 契约① |
| B7 | 模板守卫直调:手构缺 chunk_score 的 tmpl jsonb → v13_require_filter_templates → V3006;生产面种子恒在(append-only)记注 belt | §3.1 L1 |

### C 组 · 存在性闸门(G-ctx4-1+F2)

| # | 断言 | 对应 |
|---|---|---|
| C1 | 先行序:mock 存在性=确信有(noul 0.85)→ resolve 直调:calls 行序 existence 批先于一切 chunk_score 批(按 created_at/call_id 序断言);返回 gate_open=true | §4.5 顺序 |
| C2 | **闸关零 Score(G-ctx4-1 主断言)**:mock 存在性=确信无(noul≤0.30)→ resolve:existence 恰 1 calls 行、chunk_score calls=0、asked=1、failed=false、remaining=0(闸感知)、gate_open=false;decisions:corpus_exists 一行+chunk:: 零行 | §4.5/OQ4 |
| C3 | **F2 陈旧无答案不复用**:①摄取 docA(无答案)→ parse(mock 无)→ existence 落 no+cache 行;②摄取 docB(有答案)→ cgr bump → advance 'stale' → 重 parse:candidates 含 B → digest 变 → existence 新 hash → miss → 重问(mock 有)→ 闸开 per-chunk 开跑;断言 existence cache 行恰 2(两世代)、decisions 两行 context 的 digest 互异 | F2/OQ4 |
| C4 | 同 query×corpus 存在性缓存命中:C3② 后重 parse(毒化)→ failed=false ∧ existence 零 ask;gate_open=true(消费缓存行) | OQ4 |
| C5 | 闸门三态 fail-open:①超时形态(挂起 socket+statement_timeout='50ms'<typesafe.timeout_ms='5000',DP2 B10 同款)→ existence 缺 → gate_open=true → per-chunk 照跑;②review 带(noul 0.35∈(0.30,0.40))→ defaults review='include' → gate_open=true;③确信无 → false(C2 已证);④翻 defaults v3(review='exclude')→ review 带闸关(版本化缺省的数据动作面,测毕还原) | OQ6 |
| C6 | 闸带策略负向:A3 的 hi≥lo 形态在 gate_open 直调面复测 V3006 | §3.1 L2 |
| C7 | **键-态绑定(体缺窗口不落陈旧「无答案」)**:①摄取语料+goal → parse(毒化,零消费);②手动 DELETE 一个候选 chunk 行(DP4 合法路径——零引用行);③resolve 直调:零存在性 ask、零 judgment_cache 落行、过滤行剔出 remaining;④**同体重摄取**(同 content_hash 返回)→ 重 parse(candidates 复原 ⇒ digest 不变 ⇒ 存在性键不变)→ resolve(mock 存在性=确信有)→ 存在性**正常问**(calls 恰 1)——④ 若零 ask 即 ③ 已在全集键下落缓存(陈旧「无答案」回流),断言恰好钉死该死法 | P1-2/F2/OQ4 |

### D 组 · per-chunk 缓存(G-ctx4-2/3)

| # | 断言 | 对应 |
|---|---|---|
| D1 | **同 query×chunk 二次零外部调用(G-ctx4-2)**:同 session 重 parse(毒化)→ failed=false ∧ asked=0 ∧ 零新 calls/decisions/cache;cache_hits=缺口数 | §4.5/G-ctx4 |
| D2 | **跨 session 复用(G-ctx4-3)**:session B 重放逐字节同 user payload+同语料 → 毒化下 parse:per-chunk decisions 全 status='cached'、reused_from=canonical request_hash(与 A 库 cache 行 join 相等)、call_id NULL、session_id=B;B 的 (session_id,request_hash) 唯一性不受扰;cache/calls 行数零增 | §4.5/DP1 契约 |
| D3 | 内容重摄取同 hash:docA 同 body 重摄取(supersede 链路)→ 同 content_hash → 同 per-chunk 键 → 毒化下零 ask(内容寻址语义;退役源过滤由 DP5 B4 保证候选面) | §4.5 |
| D4 | 键敏感性直调(四面同源 fixture):v13_request_hash 七参——换 chunk 后缀/换 goal_hash 各互异、同参两调字节等;v13_filter_ref 手构形态与 decisions.context 存档逐字节相等(材料=存储);v13_row_context('chunk::'||h) 输出=filter_ref(目标形态) | 不变量 2 |
| D5 | 存在性键敏感性:v13_candidates_digest——候选集变→互异;同集乱序输入→相等(排序归一);v13_existence_ref 手构 env(同 goal 异 candidates)→互异 | OQ4 |
| D6 | **仅候选维度(防回归)**:手工构造同 content_hash 集、仅 bm25/spans 不同的两组 candidates → v13_candidates_digest 相等——把 F2 字面「候选集维度」钉成行为断言(对象全文入料的实现此行红;与 D5 变集互异/乱序归一互补) | OQ4/F2 |

### E 组 · resolve 集成(双速/预算/边界)

| # | 断言 | 对应 |
|---|---|---|
| E1 | 快路预算与慢路 handoff(DP1 双速契约):k=8 语料 → parse₁:canonical 恰 1 ask(预算 1)→ advance ③ judge effect(request 携 needed 含过滤行+candidates)→ 测试双连接模拟 worker(claim→resolve(env,1)→renew_lease 循环):existence 轮+chunk 轮(8≤32)共 2 轮 → complete('succeeded') → 重 parse+advance 直通路由;calls 总数=3(canonical+existence+chunk) | DP1 §1.3 |
| E2 | 慢路分批(>32):k=64 语料(4 档×16 文档等宽)→ 快路 1+慢路 3(existence 1+chunk ⌈64/32⌉=2)→ 数字呈报(一页账对照);每轮 renew true;fence 失配 false | DP1 契约/一页账 |
| E3 | no-progress(per-chunk):预置污染 judgment_cache 行(per-chunk hash、answer 对 criteria 非法)+同批干净行 → ask 成功但 read-back γ' 拒干净行(混合批)或纯污染批整拒 → landed=0 → failed=true EXIT;DP2 B13 同族(计数口径:每调用从 0) | DP2 步(8) |
| E4 | β 拒收:mock malformed(score 越界/confidence 缺失)→ 'failed_validation' calls 行(usage 落)、零 decisions/cache、failed=true、解析事务正常返回 | DP2 β |
| E5 | α 形态:挂起 socket+声明 statement_timeout → 'failed_timeout' calls 行+failed=true;未声明分类的 pg_cancel_backend → 上抛 query_canceled(DP2 B10 同款双形态) | DP2 α |
| E6 | 体缺守卫与 remaining 剔出口径:parse(毒化零消费)后 DELETE 无引用 chunk 行(DP4 合法路径)→ resolve 直调:全集体在场守卫拦下——**零存在性 ask ∧ 零 judgment_cache/judgment_calls 落行 ∧ failed=false**;remaining 剔出存在性缺口与全部过滤行(体缺感知剔出口径);全缺口皆体缺同形态(remaining=0 不空转;空 chunks 退化由 B3+守卫双保险);存在性从未被缺体问出(C7 为其窗口侧) | §3.1 L6/P1-2 |
| E7 | canonical 优先序:canonical 缺口与过滤缺口并存 → 每轮 canonical 先问(预算共享);canonical 清空后过滤面启动 | §3.1 L6 |
| E8 | parse 出口回归:三出口键集与类型逐字段=DP1 七键(remaining/gate_open 不进 parse 出口);resolve 直调返回含 gate_open(jsonb_typeof='boolean') | DP1 契约/DP2 B8 |

### F 组 · manifest 接线+F1 毒化(装配换体)

| # | 断言 | 对应 |
|---|---|---|
| F1 | decision_id 填充:mock 全链(refresh settle)→ candidates 四键恰等;已决候选 decision_id 非 NULL(与 decisions join 相等);**include 与 exclude verdict 均入消费集**(decision_id 都非空) | DP3 契约 |
| F2 | judgments 消费集自动非空(DP3 契约):epoch='pre-finalize'(逐行)、raw_verdict 原文、final_action∈{include,exclude,degrade}(与 v13_filter_trace 逐行对照相等);existence 行在场(action=include/exclude);v13_manifest_validate 绿(settle 已执法+直调复核);零 usage 键 | DP3 契约 |
| F3 | 闸关面:C2 场景 settle → candidates decision_id 全 NULL;judgments 恰 existence 一行(action='exclude');校验器绿;sections 三段不受扰(DP3 C1 复测) | OQ4 |
| F4 | **F1 毒化三形态逐点断言**:①missing——毒化(mock NULL+坏 endpoint)下 settle(decisions 零 per-chunk 行)→ trace 全行 action='include'/basis='default_missing';②timeout——预置 per-chunk status='failed' 行(answer NULL,手插合法载体)→ trace basis='default_timeout'/action='include';③review——mock 低置信(confidence<0.50)→ trace basis='decision_review'/action='degrade';三形态 basis 恰分(F1 可观测区分面);manifest 侧:①的 candidates decision_id 全 NULL+judgments 仅 existence | F1/OQ6 |
| F5 | 确定性:同输入两次直调 v13_assemble_manifest 字节等;trace 双跑字节等 | DP3 D4 同族 |
| F6 | jdef_ver 追动与 chunk_filter 不追动:defaults v3(=v2 值)翻 active → ② 不新鲜→refresh 恰一次(功能面);chunk_filter v2(=v1 值)翻 active → ② 仍新鲜(不入 token,消费清单 #14 的行为面);测毕双回滚 | DP3 OQ1/#14 |
| F7 | DP3 回归面子集:settle 幂等('replay')/迟到 decision 不回写(M₁ 字节不变)/exact replay(v13_replay 旧 verdict 含 filter 行)——G1/D1/F1(DP3)等价物在 filter 库复测 | DP3 契约 |

### G 组 · 锁/保留/GIN(不变量 7+DP4 契约)

| # | 断言 | 对应 |
|---|---|---|
| G1 | retention:per-chunk decision 落行后 `v13_chunk_referenced(h)`=true;DELETE 该 chunk 行 → V3004(门③);无引用行删除畅通(DP4 D2 复测形态) | DP4 契约①/F3② |
| G2 | 等值换载回归:v13_chunk_referenced 直调:恰一键 chunk 对象的 decisions fixture → 与旧式 `context->'chunk'->>'content_hash'=h` 提取逐行为等(对照 SQL 双查);无 chunk 键/非对象 context 行不命中;artifacts 半面(DP4)行为不变 | 附 A #6 |
| G3 | GIN 背书:会话局部 enable_seqscan=off(DP4 verify ⑤ 同方案)→ containment 查询 EXPLAIN 含 ix_decisions_chunk_ref(Bitmap Index Scan) | §3.1 L9 |
| G4 | 批写锁纪律(两连接,DP4 J 组同族):连接 A 直调 resolve(mock 大缺口,持多 hash advisory 锁未提交)→ 连接 B rebuild 同源 → B 排队(pg_locks 轮询断言)→ A 提交后 B 苏醒、检查见引用、行存活;**升序无环冒烟**:A(resolve:hash 升序逐行)∥B(ingest:source→hash 升序)交错三轮零 40P01(statement_timeout 内);**writer∥rebuild 多源死锁冒烟注记**:「复合序无环」对 ingest 端成立(单批 DISTINCT ORDER BY 全局升序);rebuild/gc 单事务内逐源循环取锁(DP4 §3.1bis)——hash 序逐源重启、全局非单调,理论环可构造(writer 升序持 b..z ∥ rebuild 持源 S1 之 z 求源 S2 之 b → 40P01);冒烟=A(resolve)∥B(跨双源 rebuild)交错,断言面=40P01 fail-loud 非静默 ∧ 双方幂等重试后收敛(**不硬断零死锁**——上游遗留面;gc v1=dry-run-only 零锁不在面内) | DP4 契约①/不变量 7 |
| G5 | ix_chunks_content_hash:同 content_hash 跨源双行 → body 相等;体查找 LIMIT 1 带序(source_hash,chunk_no)确定性(双跑同行) | §3.1 L9 |

### H 组 · ACL/回归/加载

| # | 断言 | 对应 |
|---|---|---|
| H1 | ACL 矩阵:SET ROLE v13_recall → EXECUTE trace/构建器族 ✓、filter_ask ✗;v13_resolve → EXECUTE filter_ask/gate_open/fillable/bodies_present/defaults_action ✓、trace ✓;v13_route → EXECUTE existence_action/chunk_filter_action ✓(装配链)、filter_ask ✗;PUBLIC 逐件负向(has_function_privilege) | §3.1 L11 |
| H2 | OR REPLACE 五件 ACL 保留抽查:judgment_hash/resolve_judgments 三角色(DP2 面)、envelope/assemble 三角色(DP2/DP3 面)、chunk_referenced 属主(DP4 面)——has_function_privilege 与上游一致 | 不变量 10 |
| H3 | 双登录:v13_resolve_login 直连 → mock 全链 parse(含过滤面)✓;v13_route_login → EXECUTE filter_ask ✗ ∧ SET ROLE v13_resolve → ERROR;refresh settle 全链(route_login)✓(装配 join 零 GUC——settle 连接无需 SET typesafe.*) | DP1 双登录/OQ10 |
| H4 | 前缀切片:DP5 库(九文件)无过滤函数/无 filter 行 needed(pg_proc/键集断言);DP1–DP5 全部 gate 复跑绿(runner 注记) | 契约 #5 |
| H5 | 纸面加载模拟对账(附 B 数字):test 内静态断言 v13_filter.sql 源文——CREATE FUNCTION 总数=19(新 14+OR REPLACE 5)、CREATE TRIGGER=0、同签名重复=0(正则)、种子 INSERT 末分号在 | turn 8/9 教训 |
| H6 | 源码扫描(归一化口径,DP5 G1 同款):第 10 号文件零 `==>`、零 `stannum.` 限定名(filter=零引擎依赖) | DP5 不变量 7 同族 |

### I 组 · 投影纪律(逐字层)

| # | 断言 | 对应 |
|---|---|---|
| I1 | 策展:builder 后 transcript_chunks 恰含 user/message+llm/message 行;tool/result/turn·route/effect_done 零行;空体事件跳过;per-event 行 seq_from=seq_to | OQ8 |
| I2 | 自证与守卫:手插错 hash 行 → CHECK 拒;UPDATE 拒(触发器);owner DELETE+重跑 → 同行集回归(可重建);FK:投影行 seq 恒在 events(结构性,记注 belt) | §3.2 |
| I3 | 增量/幂等/上限:追加事件 → builder 恰新增行;重跑 rows_projected=0 零新行;limit 2 分两跑投 3 行;watermark 单调只增 | ch13:58-59 |

### J 组 · 水印与 F10

| # | 断言 | 对应 |
|---|---|---|
| J1 | fail-closed:append llm/message 不 build → reader 查该文本零命中(投影外不可见——零 events 回读路径);freshness lag=1、degraded=false | OQ5 |
| J2 | **上一 turn 可召回性(F10 gate 主断言)**:多轮 turn fixture,上一 turn 消息已投影 → reader 命中上一 turn 文本;lag≤max_lag_events ∧ degraded=false | F10 |
| J3 | 超界降级:追加 20 策展事件不 build → lag=20>16 → degraded=true ∧ NOTICE 捕获(psycopg diagnostics/notices 列表断言);reader 仅返回已投影前缀(新文本零命中,不谎报);**当前 turn 直读对照**:v13_canonical_state(ctx).messages 含最新消息而投影不含(判断平面不经投影的结构性证明) | F10/OQ5 |
| J4 | 策略负向:memory_stack 手插缺键 v2 翻 active → freshness V3006;无 active 行 → v13_policy RAISE(DP1 面);测后回滚 | §3.2 |

### K 组 · 记忆检索(reader)

| # | 断言 | 对应 |
|---|---|---|
| K1 | 命中与排序:英文+CJK 混合 fixture(kohaku 同款语料)→ 短语命中(東京タワー 逐字切分);ORDER BY 分值 DESC,content_hash ASC 并列终裁双跑字节等;k 边界(0/1025/NULL → V3006;'' → 零行;非法文法 tinql → V3005 守卫拒) | OQ9/DP5 同族 |
| K2 | per-session 隔离:session B 的文本对 A 的 reader 零命中(记忆=会话私有面) | §3.2 |
| K3 | 绑定形态:会话局部 enable_seqscan=off → EXPLAIN (FORMAT JSON) Node Type='Custom Scan'+Index=ix_transcript_stannum(DP5 K1 同形断言;session 谓词+==> 复合计划=实施期冒烟项,附 B) | OQ9 |
| K4 | 源码扫描(归一化):第 11 号文件 `==>` 恰 1(reader EXECUTE 串)、`stannum.` 限定名恰 3(full_score×1+verify_index×2) | DP5 R2 同款 |

### L 组 · p99(§4.4 gate)

| # | 断言 | 对应 |
|---|---|---|
| L1 | **p99 events INSERT 有/无投影构建对比**:基线(空投影,2000 次 v13_append_event 计时)vs 载入(预置 pending 策展事件,连接 A 循环 v13_rebuild_transcript_chunks,连接 B 并行 2000 次 append 计时)→ p99_loaded ≤ max(p99_base×1.25, p99_base+0.5ms);三轮取中位(噪声协议 README,DP4 H1 同款) | §4.4 |
| L2 | 构建零 events 阻塞:builder 进行中 append 即时返回(builder 零 sessions/chunks 触碰——锁面机理断言) | §3.2 |

### M 组 · 结构化层与校验器

| # | 断言 | 对应 |
|---|---|---|
| M1 | ix_decisions_question_stannum 在场且唯一(pg_index 计数=1——单索引纪律);mock parse 落 decisions 行(索引在场)成功(插入烟测,时延记数不硬断言,README 运维注记) | §4.4/OQ9 |
| M2 | v13_verify_memory:五项全绿 all_ok=true;负向:memory_stack 翻 inactive → ③红+p_raise V3006(测后回滚);stannum.verify_index 两索引 findings=0 | §3.2 |

### N 组 · cron/ACL/加载

| # | 断言 | 对应 |
|---|---|---|
| N1 | cron 面:pg_cron 在库 → cron.job 恰两条(v13-verify-chunks+v13-sweep-transcript)且零其他;job 体=`SELECT v13_rebuild_transcript_chunks(100)`(行为面手动等价调用);不可用分支照 DP4 G6(NOTICE 降级+函数手动可调) | ch13:58-59/附 A #8 |
| N2 | ACL:SET ROLE 三角色 → SELECT transcript_chunks ✓/EXECUTE reader·freshness·watermark ✓/INSERT·UPDATE·DELETE·TRUNCATE ✗/EXECUTE rebuild·verify ✗;PUBLIC 负向 | §3.2 |
| N3 | 前缀切片与对账:filter 库(十文件)无 transcript 对象;DP1–5+filter 全 gate 复跑(runner 注记);纸面模拟对账(附 B 数字) | 契约 #5 |

**F5② 一页账更新(DP5 契约⑥:费用账自 DP6 起;DP7 经济件输入基线)**:

| k(候选数) | canonical | 存在性 | per-chunk 批 ⌈k/32⌉ | 总 ask | 快路 | 慢路轮(worker) |
|---|---|---|---|---|---|---|
| 0(空候选) | 1 | 0 | 0 | 1 | 1 | 0 |
| 8(k_base) | 1 | 1 | 1 | 3 | 1 | 2 |
| 32 | 1 | 1 | 1 | 3 | 1 | 2 |
| **64(k_max)** | 1 | 1 | 2 | 4 | 1 | 3 |

注:全命中(缓存)恒零 ask;**闸关时=1(canonical)+1(existence)即止**——「语料无答案时 1 次调用替代 k 次」的常驻形态(重 parse/跨 session 全命中 C2/C4);首轮冷缓存 k=64 为 4 ask≈3 慢路轮(≈4×1.3–1.6s),较 DP5 表(+存在性 1 ask)——差异呈报 §1.4 DP7⑤;mock 单价=v12 G7 实测 9 问 $0.000042 量级。放宽 k_max=DP7 裁量(DP5 契约②原样)。

**收尾工件(AGENTS.md,两里程碑各一次)**:SQL 追加进 v13/load.py(第 10/11 位);两 stage README;一里程碑一提交(`v13: <祈使句摘要>`,按路径 add,禁 `git add -A`)。`v13/filter/README.md` 必记:①两族模板 authoring(draft→内容行→freeze;任何模板/defaults/chunk_filter 变更=新版本行;filter defaults points 必须在 active 行——运行期缺=V3006);②闸门语义(带值/三态 fail-open/闸关→路由照常 intent 驱动,无 chunk 上下文);③缓存键形态(per-chunk/存在性两键+digest;重摄取→新候选集→存在性重问——F2);④批写锁纪律(resolve 内部已按 signal 升序——直调批写 per-chunk decisions 的第三方代码必须同序或拆事务,DP4 契约①);⑤chunk_filter/judgment_defaults 翻版纪律(与模板 rubric 配套同批);⑥mock 仅测试(G-ctx1-5);⑦一页账表(§4 末)。`v13/memory/README.md` 必记:①tick=扫地僧不是节拍器(cron 间隔≠duty_cycle;关掉 cron settle 仍推进——ch13:130-135);②pg_cron 前置/降级与 crontab 等价命令;③水印语义(F10:fail-closed/滞后上界/degraded 消费契约——消费者落审计事件);④策展词表(user/assistant=llm/message;新增语义事件族时评估入列);⑤stannum 双索引(transcript/decisions.question)与 verify_memory 手动命令;⑥worker 长连接预热注记(§4.4 原文:连接预热税——stannum 新连接 buffer 重建,池预热,DP5 M 组同族);⑦p99 度量协议;⑧会话全扫空转的台账触发(聪明 tick)。

### 4.1 逐文件影响与实施顺序

| 文件 | 变更 | 依赖/顺序 |
|---|---|---|
| `v13/load.py` | SQL_LOAD_ORDER 追加 filter(第 10)/memory(第 11)两行+STAGE_THROUGH 两键 | DP1–5 九文件已存在后 |
| `v13/filter/v13_filter.sql` | §3.1 全部(单事务 BEGIN…COMMIT) | DP1–5 全绿后 |
| `v13/filter/setup_db.py`/`test_filter.py`/`README.md` | 新增 | SQL 注册后 |
| `v13/memory/v13_memory.sql` | §3.2 全部 | filter stage 全绿后(第 11 位;stannum 前置探针) |
| `v13/memory/setup_db.py`/`test_memory.py`/`README.md` | 新增 | 同上 |

实施顺序(每里程碑内部工序;每步可独立纸面验证):1. DP1–5(或含 filter)全绿前置;2. load.py 注册;3. filter:先落 L1–L2 构建器/闸门/动作族→L3 ask 宏→三个 OR REPLACE 大体(机械复制+增量)→L8-L9 换载与索引→种子→ACL;4. setup+gate(A–H);复跑前序全 gate;提交;5. memory:表+索引+守卫→水印/新鲜度/构建器→reader→结构化层+校验器→策略+cron→ACL;6. setup+gate(I–N);复跑;提交。

---

## 5. 风险与回退

| # | 风险 | 缓解 | 回退 |
|---|---|---|---|
| 1 | 三大换体(envelope/resolve/assemble)机械复制走样 | 实施纪律=从上游 stage 文件加载态原文复制+按【DP6】增量标注编辑;B/E/F 组键集与 DP2/DP5 对照 fixture;DP1–5 gate 前缀库复跑互证 | stage 库重建(BEGIN/COMMIT 不留半态);共享库重跑 DP1–5 文件恢复旧定义 |
| 2 | canonical 哈希回归(judgment_hash 分支) | 不变量 2:分支仅 corpus_exists/chunk::% 两处,canonical 严格转发 group_state;D4 直调+DP2 B14 同族 fixture 在 filter 库复测;H5 源码断言 | 修分支守卫;canonical 行零失命中是硬边界 |
| 3 | §4.5/§6.5 批态张力(键窄态联合)的语义争议 | OQ3 特别法论证+附 A #5 呈报;交叉污染=模板质量参数(版本=新世代);calls payload 全档可归因 | 若父 loop 裁 §6.5 优先:降级=存在性批保留+per-chunk 改单问单批(费用 ×k,一页账重开)——不改键形态 |
| 4 | 存在性 state 体量(k×body≈64×3KB) | k_max=64 封顶;payload 体积在 judgment_calls 可观测;超限语料真实出现→策略收紧(台账) | 闸门 state 改截断体(策略键)——新版本行 |
| 5 | needed 含 k 行的 envelope/judge effect 体积膨胀 | k_max 封顶(≈k×200B+candidates ≈k×300B);README 记量级;DP7 花费闸消费 | 无正确性面;分批信封=未来 DP |
| 6 | 闸感知 remaining 与 advance ③ 交互(闸关零 judge effect) | E 组行为断言:闸关→直接 ④ 路由(intent 驱动,无 chunk 上下文=设计既定形态——过滤不承载路由);「闸关即升级 human」若需→DP7 策略 | 无需回退 |
| 7 | memory p99 噪声 | DP4 H1 协议(三轮中位/带宽取大);README 协议 | 放宽至 ×1.5 需 plan 修订 |
| 8 | decisions stannum 索引插入税 | 判断速率=turn 级(低);M1 烟测记数;不可变列=不可变段(零 fold churn) | 索引 DROP 即回退(结构化层无消费者) |
| 9 | transcript tick 会话全扫空转 | v1 接受(数量级小);触发=会话数实测超标→聪明 tick(§12 台账/ch13:89) | 手动调 builder;降频 cron 行 |
| 10 | defaults/chunk_filter 配置错误 | 运行期 V3006 fail-closed(响亮);README ops 纪律;A3/A4/J4 负向 | 修策略新版本行 |
| 11 | reader 复合谓词(session+==>)计划形态 | K3 EXPLAIN 断言;实施期实机冒烟(附 B);不成立→reader 改预过滤子查询形态(计划纪律,断言随升) | 不依赖未证行为承正确性 |
| 12 | GIN/索引维护税(每 per-chunk INSERT) | 量级低(每批 ≤32);G3/G5 断言索引在场与正确性 | 索引可独立 DROP(性能件) |
| 13 | worker 长连接预热(stannum buffer 重建税) | README 运维注记(§4.4 原文);池预热(连接常驻=worker 契约既有形态) | — |
| 14 | 整体回退 | 删 v13/filter/+v13/memory/ 树+load.py 两行+DROP agent_v13_filter/agent_v13_memory 即净;共享库:重跑 DP1–5 文件恢复 envelope/resolve/assemble/judgment_hash/chunk_referenced 旧定义;新增表/索引/策略行/模板行可暂留(零消费者)或逐对象 DROP(清单=§3 全对象表);禁删 canonical 审计数据(judgment_cache/judgment_calls/decisions) | 删树即净 |

---

## 6. 教程映射(§13;正文零改动)

| 章 | 教程承诺(实测行号) | 本 DP 兑现 |
|---|---|---|
| ch10.1 表 | LLM 相关性过滤=语义判断:**存在性 Noul 先行**,再 per-chunk Score(ch10:18) | 两族模板+resolve filter 面;G-ctx4-1 |
| ch10.2 四行画景 | rag_filter(**不是工具**)——决策平面:存在性 Noul→per-chunk Score(ch10:36);查询时序 parse 内过滤(ch10:44) | 过滤住在 needed/resolve/decisions 平面(零 tools 行——DP5 附 A #9 裁决的同族面);时序=parse 内 resolve filter 面 |
| ch10.5 | per-chunk 缓存键公式(ch10:134-135 逐字=§4.5);顺序是闸门不是品味(ch10:138-144);跨 session 拆两行(ch10:146) | §3.1 L1/L6;C/D 组;judgment_cache+reused_from(DP2 面) |
| ch10.8 | 「存在性 Noul 是闸门」(ch10:194-195);跳过闸门=语料无答案时付 k 次款(ch10:298-299) | C2/C3;一页账闸关行 |
| ch10.7 G-ctx4 断言块 | ch10:219-222 三条 | §4 G-ctx4 映射表逐条 |
| ch10.9 练习 2 | 先造「语料无答案」——存在性拒绝后 Score 计数=0;再造二次过滤零调用(ch10:243-244) | C2/D1(gate 化) |
| ch13.1/13.2 | scheduler tick=pg_cron 扫地僧(ch13:28);transcript 投影构建 job(ch13:58-59 逐字:v13-sweep-transcript '*/5' v13_rebuild_transcript_chunks(100)) | §3.2 cron DO 块+builder;N1 |
| ch13.2/13.5 | tick 不是节拍器/关掉 cron settle 仍推进/连续两次扫地零新 effect(ch13:64-79,130-135) | README①+N1;builder 幂等(I3)——零新 effect 语义=幂等重入 |
| ch5.1/5.8 | 三来源同语义(先 parse 再 advance;tick 为第三来源,ch5:19-22);幂等 SQL(ch5:222-230) | resolve/advance 成对契约不变;transcript tick 只扫地不推进(零 effect) |
| ch15 | 更聪明的 tick 台账(ch15:91) | §7(触发未至) |

教程正文已含 §4.5/§4.4 的 normative 内容(10.5 全文/ch13 tick 形态)——本 DP 是兑现侧;§13 第 10/13 章行全部在场,零新增指针需求。

---

## 7. 明确不做(§12 台账为源;P2/台账项一律不承诺为首版交付)

| 项 | 依据/触发条件 |
|---|---|
| 全集 Choice 重排 | §12:相对序本身成为问题的用例出现(OQ3 的被拒半边;judgments/trace 已记逐 chunk verdict 供其消费) |
| 语义决策缓存机制(decisions.question 近似检索+Noul 等价确认) | §12:判断缓存费用成为账单大头;结构化层索引已建(OQ9——机制落地时零 DDL) |
| 效用遥测(触点 4) | §12/§6.2 P2;post-execute 生产者归 DP7(DP3 契约) |
| emergent 表/在线 triage(触点 3) | §12/轮 2 已裁 P2 延后 |
| chunk manifest sections/段级装配(span 级 payload_ref/多段全序) | OQ7:DP3 校验器 section_id=kind 单段约束⇒manifest_version 2+校验器重做=独立工作包;分解表未指派;缝=trace/candidates.decision_id/judgments+DP4 spans+DP5 契约⑤(随 sections 转发 DP7+,含 span_assembly token 缝) |
| per-chunk Noul 族(逐 chunk 是/否) | §4.5「Score/Noul」的 Score 半边=ch10 normative 流水线;Noul 族=同机械异模板行(信号前缀区分防撞),零代码缝;触发=二段过滤(闸→粗筛→精筛)真实需求 |
| transcript 区间合并(相邻事件并段)/每段多事件 | OQ8:批量优化;触发=记忆行数实测超标 |
| 记忆 reader 的 tsv 双引擎/引擎换体缝 | OQ9:直接 stannum(刻画后);换引擎=同签名 OR REPLACE(DP5 definition-swap 先例),不预建双形态 |
| memory recall 接入信封 candidates/manifest 段 | 无消费者(OQ5 消费契约已发布);触发=DP7+ 记忆段装配 |
| 更聪明的 tick/ch13 requeue·recover cron jobs | §12 触发未至(扫描空转超标);驱动周期调 v13_requeue_stale 仍是 DP1 README 既有形态;附 A #8 |
| verify 夜跑 cron 扩展(记忆面并入 v13-verify-chunks) | v13_verify_memory 手动+gate;触发=第二消费者出现(与 DP2 pg_jsonschema 台账同族) |
| 摘要验收(触点 2)/intent 新调 Jev(触点 5) | 归 DP7/§6.2 已裁(仅复用既有 intent 行) |
| transcript/记忆语料的窗口化 GC、bigram、T1、boost | DP4/DP5 台账原样(触发条件各自在档) |
| pg_net/pgsql_http 等第二 IO 通道 | §8 P0 排除(不变量 1 继承) |
| v13_parse/v13_advance/v13_complete/enqueue/claim/effect 族函数体 | 零改动(硬边界;§1.1) |

---

## 附 A:与设计稿/上游裁决的分歧点清单(供父 loop 复核)

| # | 分歧/裁量 | 论证 |
|---|---|---|
| 1 | **F2 立法**:存在性 Noul 缓存键含候选集维度(v13_existence_ref={query_content_hash,candidates_digest})——设计 §4.5 未定义该键 | stepfun F2(P0)已裁方向(「hash(query.content_hash, 排序后候选 content_hash 全集)+模板/model/版本」);本 plan 逐字载体化;gate C3=陈旧「无答案」不复用的行为断言;设计稿未改(用户既定默认) |
| 2 | **F10 裁决**:水印新鲜度=fail-closed+滞后上界(策略行)+当前 turn 永远直读+上一 turn 可召回性 gate——设计 §4.4 只定义度量未定义行动 | stepfun F10 修法原文;OQ5 全节;gate J 组;「落审计事件」的载体裁量见 #9 |
| 3 | F2 键载体=candidates_digest,非 DP5 行文提示的 csh | DP5 §1.4④「消费 csh 材料」意图=F2 维度自信封可用;digest 对 F2 字面更精确(仅候选维度——目录/模板变更不轮换存在性键),且装配侧可单源重建(消费集 join 必需;csh 含 needed 不可重建);F2 语义两载体均满足,digest 的 miss 域更窄 |
| 4 | 「needed 新分支」落点=信封合并层,v13_needed_judgments 函数体零改动 | DP2/DP5 行文「needed 新分支(函数体 DDL 自动 bump cgr)」的机制意图(needed 族行+模板行)全兑现;载体改合并层的理由:单一 recall 推导(DP5 契约①)+needed_judgments 无候选入参缝;无漏报论证不破(六输入键覆盖,消费清单 #8);cgr 的「函数体 DDL」半边因 needed 体未动而未被使用——输入面键覆盖替代 |
| 5 | **§4.5/§6.5 张力**:per-chunk 键(窄引用)vs 批态(联合体)——§6.5「不得发送联合 state 却按题局部分片复用答案」与 §4.5 per-chunk 键+_many 在单 state API 下不可同时字面满足 | OQ3:特别法优先(§4.5 是过滤族的显式 normative 裁决;G-ctx4-3 在联合键下不可构造);内容寻址确定性(chunks.body=hash 唯一原像,CHECK 钉死)封死 §6.5 所防的漂移面;交叉污染=模板版本拥有的质量参数;呈报父 loop,若裁 §6.5 优先则 per-chunk 改单问单批(费用重开) |
| 6 | v13_chunk_referenced OR REPLACE(decisions 半边 ->> 提取改 @> containment) | DP4 对象的授权换体:语义逐字节等价(行内 chunk 恒恰一键对象,v13_filter_ref 构造半边钉死);DP4 契约「届时补该路径的 GIN 索引」的使能半边(G3 计划断言);DP4 gate D1/D2 在其前缀库照常(其库加载旧定义),filter 库 G2 双查等价断言 |
| 7 | chunks/decisions 各追加一索引(ix_chunks_content_hash/ix_decisions_chunk_ref) | DP4/DP1 表的纯追加(零 DDL/约束/触发器改动);前者=过滤面体查找读路径(DP4 建表未含——content_hash 非唯一,跨源同文合法双行);后者=DP4 契约预留缝;均为性能件可独立 DROP |
| 8 | cron job 1→2(本 stage 库挂 v13-sweep-transcript) | DP4 G6「恰一条」是其前缀库断言(结构互证);ch13:53-61 四 job 全景中 requeue/recover 仍归驱动(§12「pg_cron tick」YAGNI 触发未至——F9 所指两说按分解表交叉件行「pg_cron→DP4(verify_index 夜跑)+DP6(tick 投影)」裁定:DP6 只挂投影构建);N1 断言恰两条 |
| 9 | F10「落审计事件」的消费半边=NOTICE+结构化 degraded+已发布消费契约 | recall 平面纯 SELECT(DP1 角色分裂:v13_recall 无 events 写权)——降级审计事件不可能由 reader 落;DP6 无记忆段消费者;DP7+ 接线装配时按 §1.4 DP7④ 契约落 events(义务已发布);NOTICE 提供运维即时可见 |
| 10 | chunk manifest sections 不做(OQ7) | DP3 校验器层 5 section_id=kind 钉死单段——多 chunk 段需 manifest_version 2+七层校验器重做+全序键,独立工作包;分解表 DP6 行未含 §5.2/§4.7 段级消费;DP5 契约⑤(条件句)随 sections 转发 DP7+;DP3 契约的 manifest 侧义务(decision_id/消费集/final_action)已全兑现 |
| 11 | 过滤两点 defaults 全 fail-open(OQ6) | F1 只要求逐点表+版本化(方向未裁);plan 裁证据装入族 fail-open(intent 门控同族;装箱兜底;静默排除=作用力 2 同种死法);review→degrade 的降序语义为 sections 半边预留;P2 可调(数据动作翻版) |
| 12 | 空候选时不问存在性 | 设计未明(§4.5 闸门语义预设非空批);空集「无答案」是恒真式,问=纯浪费;B3 断言零过滤行 |

**设计矛盾检查:未发现 blocked 级矛盾。**§4.5/§4.4/§6.1/§6.2/§9/§10-G-ctx4/§12/§13 的 normative 内容全部有落点(§2 映射表);F2/F10 按评审已裁方向立法(附 A #1/#2);唯一的设计内部张力(§4.5 vs §6.5)以特别法读法自洽(附 A #5),不构成 blocked;与 DP1–DP5 契约零冲突(§1.2 消费清单逐条,两处载体级偏差 #3/#4 已呈报)。

## 附 B:全教训自检(turn 1–26,机械执行记录)

| 教训 | 执行记录 |
|---|---|
| **纸面加载模拟记数字**(turn 8/9) | §3.1(filter)逐语句清点:顶层语句 **34**=BEGIN 1+CREATE FUNCTION 14(candidates_digest/filter_ref/existence_ref/row_context/require_filter_templates/goal_text/defaults_action/existence_action/gate_open/fillable/bodies_present/chunk_filter_action/filter_trace/filter_ask)+OR REPLACE 5(judgment_hash/judgment_envelope/resolve_judgments/assemble_manifest/chunk_referenced)+CREATE INDEX 2(ix_chunks_content_hash/ix_decisions_chunk_ref)+种子 7(模板 versions INSERT+templates INSERT+freeze UPDATE+chunk_filter INSERT+defaults v2 INSERT+双 flip UPDATE)+REVOKE 1+GRANT 3+COMMIT 1;§3.2(memory)顶层语句 **17**=BEGIN 1+CREATE TABLE 1+CREATE INDEX 2+CREATE FUNCTION 6(transcript_immutable/watermark/freshness/rebuild_transcript_chunks/transcript_recall/verify_memory)+CREATE TRIGGER 1+种子 INSERT 1+DO 1+REVOKE 1+GRANT 2+COMMIT 1;同签名 CREATE 全文件唯一(14 新名全树首现;OR REPLACE 五件复用旧名,无第二份裸 CREATE);前向引用分层:L1 构建器(candidates_digest→filter_ref/existence_ref 调 digest 先建;row_context→group_state=DP2 已载)→L1b(goal_text→v13_goals=DP3 已载)→L2(defaults_action→v13_policy=DP1 已载;existence_action→defaults_action 先建 ✓;gate_open→existence_ref/existence_action 先建 ✓;fillable→gap=DP1 已载;bodies_present→chunks 表=DP1 已载;chunk_filter_action→filter_ref/existence_action/defaults_action 先建 ✓;trace→recall_candidates=DP5/goal_hash=DP3/chunk_filter_action 先建 ✓)→L3(filter_ask:plpgsql 晚绑定→judgment_hash 在其后位合法;question_wire/validate_answer/lock_key=DP1/DP2 已载)→L4-8(judgment_hash→row_context 先建 ✓;envelope=LANGUAGE sql 创建期解析——guc_required/canonical_state/needed_judgments/recall_candidates/template_latest/projection_key/project_state/goal_hash/tools_catalog_frozen/v13_policy/require_filter_templates 全部先建或上游 ✓;resolve=plpgsql;assemble=LANGUAGE sql——context_required/prefix_identity/candidates_digest/filter_ref/chunk_filter_action/existence_action 先建 ✓;chunk_referenced=sql 纯列)→L9 索引(表已载)→L10 种子(父表先插→内容行[insert_guard 读父行 ✓]→freeze)→L11 ACL 真末尾(14+5 签名全先建);memory:表→索引→immutable→trigger→watermark→freshness(→watermark+v13_policy 先建)→rebuild(→v13_body_hash=DP4 已载)→recall(→tinql_terms=DP5 已载;EXECUTE 串运行期)→decisions 索引→verify(stannum.=扩展运行期)→种子→DO(→rebuild 先建)→ACL 真末尾;$$ 配平:filter 19 函数体+memory 6 函数体+1 DO($cron$/$job$ 双层独立定界,DP4 §3.7 同款);BEGIN/EXCEPTION/IF/LOOP/CASE/FOR 配平逐函数过(α/β/γ' 块结构=DP2 同型);0 省略号(SQL 块内无 … 占位) |
| **类型算子层**(turn 7/8) | jsonb 一律单完整字面量+::jsonb 或 jsonb_build_*(种子 5 处:chunk_filter/defaults v2/memory_stack/templates×2 的 projection);digest() 产物一律 encode hex;signal 前缀用 LIKE 'chunk::%'+substr(signal,8)(字节位确定,7 字符前缀已核:c-h-u-n-k-:-: );策略形状校验分步类型先验(jsonb_typeof='number' 先行→显式 ::numeric/::int→域校验,DP4 三律);三值防御(IS DISTINCT FROM/IS NOT TRUE 于词表判断——existence_action/gate_open 的带比较显式 IF);(p_env->>'timeout_ms')::int NULL 安全;jsonb @> containment(v13_chunk_referenced 换载)对非对象左值安全返回 false;DISTINCT ON 与 ORDER BY 起始表达式一致(frows 去重臂);jsonb_object_agg 对重复 signal 键最后胜出(去重上游已保唯一);策略动作词表判断走显式 IF(零 NOT IN 裸用于词表);族名过滤 NOT IN ('chunk_score','corpus_exists')(三处字面:信封 groups×1+resolve 组选择/批选择×2——操作数非 NULL 由 DP2 needed 形状保证,非三值裸用面);数值算子显式 cast;题文 ASCII(种子两题文含反引号/无撇号——'question signal' 措辞避开所有格转义);csh/candidates_digest 材料的 jsonb::text 规范化由 PG 保证(库内自洽,DP1 同基础) |
| **移动=增+删**(turn 8 #57) | 五处 OR REPLACE 均同签名换体(非移动):旧形态唯一存活于上游文件(其前缀库照常);DP2 的 canonical resolve 半边在 DP6 体内逐字保留(批选择加 NOT IN 腰带=增,非删);无同文件重复定义;信封 CTE 重排=授权换体(DP4 context_required 九键体同款注记);零 DROP 语句 |
| **gate 不引用未加载对象**(turn 7 #46) | filter gate(A–H)断言对象全部 ≤10 号文件;memory gate(I–N)≤11 号;H4/N3 显式断言前缀切片(DP5 库无过滤对象/filter 库无 transcript);fixture 全走真实链路(DP4 驱动器/DP1 函数/DP3 settle);两连接 fixture 用 pg_locks 轮询(DP2 M2-17/DP4 J 组先例) |
| **哈希同源(重点自检项:存在性 Noul 键与 per-chunk 键四面)** | per-chunk:①写入=v13_filter_ask 的 cache/decisions INSERT(经 v13_judgment_hash→v13_row_context→v13_filter_ref);②读取=v13_gap/canonical consult(同一 v13_judgment_hash);③材料构造=v13_filter_ref 单一 IMMUTABLE 函数(64hex 守卫);④存储/装配 join=decisions.context=该函数输出原物(等值 join,零哈希重算/零 GUC/零信封依赖)。存在性:①写入=filter_ask(同链→v13_existence_ref);②读取=gap/consult 同函数;③构造=v13_existence_ref(调 v13_candidates_digest 单源——材料=候选 content_hash 全集,三键对象取键、bm25/spans 不入[D6];四面同源在 digest 改后复核:写入/材料/存储/join 同函数同输入);④存储/join=decisions.context 原物+装配侧 digest 重建(同 v13_candidates_digest 同输入——单源双站)。canonical 面:row_context 严格前缀守卫(chunk::%/corpus_exists 两分支之外逐字节转发 group_state)——DP2/DP5 既有行零失命中;七参 v13_request_hash 签名与材料常量零改动;mock 构建器跟随 needed 现行题文(不硬编码)。fixture=D4/D5 直调;契约=§1.4 DP7 |
| **gate 可执行性**(turn 13/18/22 反复面) | C3(两世代存在性)构造序:摄取→parse→摄取→stale→重 parse——全真实链路;E1 双连接 worker 模拟=DP1 K2 形制;E3 污染 cache 行预置=v13_judgment_hash 预算(DP2 B13 同法);F4② 手插 status='failed' 行(INSERT decisions answer NULL——answer-once 触发器允许,合法载体);J3 NOTICE 捕获=psycopg3 connection.info/notices 列表(实施期确认 API 形态,附 B V0);L1 两连接计时=DP4 H1 形制;全部策略翻版 fixture 走分配器+测后还原 |
| **新写 SQL 自检五项**(turn 3+) | 参数全用:14 新函数逐个过(row_context 双参均用/require_filter_templates 单参/bodies_present 单参/trace 单参含循环消费);列存在:全部引用列在 DP1–5 DDL 在档(decisions 十七列含 epoch/provenance 五列;judgment_templates epoch 列=DP3 ALTER;chunks content_hash/source_hash/chunk_no;v13_policies 四列;v13_goals 四列;events 八列);语法:EXECUTE USING/GET DIAGNOSTICS/CONTINUE WHEN/部分索引 ON CONFLICT 目标(transcript PK)已核;RAISE 全 V3006(复制体 V3001/V3002/V3004 逐字保留);块末分号:33+17 语句逐一(纸面模拟过) |
| **引擎争议实机实证可选**(turn 10/12/25) | 实施期实机冒烟清单:①transcript stannum 索引+session 谓词+==> 的复合计划形态(K3——若 Custom Scan 不被选择,reader 改预过滤形态,断言随升);②decisions stannum 索引插入税(M1 记数);③GIN 部分表达式索引(context->'chunk' WHERE …)计划选择(G3);④RAISE NOTICE 自 STABLE 函数的客户端可见性(J3——psycopg notices API);⑤jsonb @> 对非对象左值返回 false(语义复核);⑥cron.schedule 幂等守卫(DP4 已验复跑)。任一不成立均有不影响正确性的回退(§5 风险表);不依赖未证实行为承正确性 |

**V0 未知项(实施期先行)**:(a) DP1–5 落地代码与本稿引用的签名逐一对账(真相源=各 plan 草案,代码未落地——以落地码为准修正);(b) mock_response 是否透传 usage(DP2 V0(b) 继承);(c) filter stage 库加载期 cgr 实际 bump(DROP needed 不发生——本文件零 DROP;模板内容行×2+freeze×2)——断言相对,打印供人审;(d) psycopg notices API 形态(J3);(e) transcript stannum 索引建索引时长(大 events fixture)——setup 计时打印。

---

## References

- 设计冻结稿:`docs/designs/v13-context-on-pg.md`(§4.4/§4.5/§6.1/§6.2/§9/§10 G-ctx4+§4.4 gate/§11/§12/§13;2026-09-19 v2 禁改)。
- 设计审查:`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md` F1(默认分支表)/F2(存在性键候选集维度)/F10(水印新鲜度)——本 plan 附 A #1/#2/#9 的立法依据。
- DP1:`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md`(§1.3 契约表 DP6 行/#43/#59/§3.1–§3.6/worker 契约)。
- DP2:`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md`(§1.4 DP6 行/§3.1–§3.9 模板两表·builders·γ/γ'·ACL)。
- DP3:`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md`(§1.4 DP6 行/OQ1 追动键缝/校验器/§3.2–§3.5 settle·defaults)。
- DP4:`docs/plans/v13-dp4-chunks-projection-plan-2026-09-20.md`(§1.4 DP6 行①–③/§3.1bis 锁协议/v13_body_hash/pg_cron 载体/H1 p99 协议)。
- DP5:`docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md`(§1.4 DP6 行①–⑦/§3.1 信封二十键体/§3.2 刻画/一页账/R2 扫描口径)。
- 教程:`docs/tutorials/v13/chapters/10-rag-as-tools.md`(10.5/10.7/10.9;行号见 §6)、`13-long-running-goals.md`(13.2/13.5)、`05-turn-and-advance.md`(5.1/5.8)。
- loop memory:`prompt-exports/loop-orchestrate-v13-deep-plans-runs.md`(分解表 DP6 行/turn 1–26 台账/turn 12 用户裁决)。
- 惯例参照:`docs/plans/v12-jev-pgembed-minimal-plan-2026-09-18.md`(stage 四件/命令形态/收尾纪律);`v12/load.py`(files_through 形制)。

## v2 对齐修订(2026-09-21)

> 日期:2026-09-21。本轮**只追加本节**,上文一字不删、不改写。
> 对齐输入(只读):
> - `docs/analysis/repoprompt-native-on-v13-feasibility-v2-2026-09-21.md`(v2: §1 I-file-2 / I-file-6 / §4 R6 / §5 G-file-open / G-file-secret(+veto) / G-cjk-file / §7)
> - `docs/reviews/repoprompt-native-context-oracle-r1-r3-2026-09-21.md`(裁决记录:I-file-2 开放世界;I-file-6 deselect 是确定性 veto,超集不得加回)
> 纪律:与 v2 冲突的原文以 `ERRATUM:` 行标注并指向 v2 §7 对应行;既有 gate 一律不弱化(含 A–H 过滤组 / I–N 记忆组 / C 组 F2 存在性键 / G-ctx4 先行+缓存 / OQ4 candidates_digest / 闸门三态 fail-open);新增断言只加不减。本轮不 invent 新里程碑实现、不改 SQL 代码。
> 编号铁律:本文件只用 **A4**(过滤消费侧 I-file-2)与 **A11**(人 veto)。**禁止用 A12**(A12=latch/fork,归 DP8)。

### 对齐总表(v2 条款 → 本计划改动点 → 换体登记)

| # | v2 条款 | 本计划改动点 | 换体登记 |
|---|---|---|---|
| A4 | I-file-2 开放世界:`bootstrap_done=false` 禁 file 存在性 Noul;`no` 不得短路为「仓库无答案」 | **过滤消费侧**落位:file corpus 存在性 Noul 仅 `bootstrap_done=true` 后允许;开放世界期间过滤器不得以「语料无答案」跳过整批 per-chunk Score;`no` 只证「已注册子集不足」。与 DP2 信封分工:DP2 管问题生成/缓存世代,本 DP 管过滤器消费侧执行——不开第二套语义 | 不适用(消费侧论域闸/短路禁令增补;信封题文与缓存世代仍归 DP2) |
| A11 | I-file-6 人 veto:`v13_file_vetoes(p_sid)` 单源;deselect 高于超集;G-file-secret(+veto) | `must_include ∩ veto = ∅`;人工 `file_deselect` 事件折叠为确定性 veto,优先级高于过滤缺省超集 / 装配 must-include / bootstrap 补漏;再入选必须有新的 `file_select` 事件;deselect 的秘密路径被超集加回=P0 | 不适用(veto join 单源登记;不过滤另写第二份 veto 谓词) |

### A4 / I-file-2 · 过滤消费侧:存在性 Noul 闸门条件化

v2 §1 I-file-2 + §7 行「v13 §4.5 存在性 Noul 先行 | erratum(论域)」:仅 `bootstrap_done=true` 后先行;开放世界期间「已注册子集是否足够」的 no 不得短路为「仓库无答案」。G-file-open:`bootstrap_done=false` 时 file 存在性 Noul 计数=0;子集不足的 no 不短路整批。裁决记录:DP2 信封已登记 I-file-2(问题生成/缓存世代/论域闸);DP5 已登记 recall 出口同纪律;本 DP 登记 **过滤器消费侧同纪律**。

**与 DP2 信封的分工**(不开第二套语义):

| 平面 | 归属 | 本 DP 不另开 |
|---|---|---|
| 问题文本 / needed 是否含 file 存在性问 | DP2 | 不另写题文、不另开「仓库有无答案」问 |
| 缓存世代 / 封闭绑定 / 旧答案不跨 epoch | DP2 | 不另开存在性缓存键、不另开短路定义 |
| 过滤器是否执行该问、`no` 是否跳过整批 Score | **本 DP** | 消费 DP2 已立法的信封;误带该问仍不得据此跳过整批 |

**本计划改动点**(只立法,不改上文 SQL 草案字面、不改 OQ4 `v13_existence_ref` / `candidates_digest`):

1. **论域闸(消费侧)**:file corpus 的存在性 Noul 仅在 `bootstrap_done=true` 后允许;`bootstrap_done=false`(开放世界)期间过滤器不得对该论域执行存在性 Noul(即使信封误带该问,消费侧计数必须为 0、不得据此动作)。
2. **不得跳过整批**:开放世界期间过滤器**不得以「语料无答案」跳过整批** per-chunk Score。闸门不确定 / 开放世界禁问 / 信封无该问——三条都继续走 per-chunk,与上文「闸门三态(missing/timeout/review)全 fail-open(不闸)」同方向,本条把「语料无答案」短路从开放世界划出。
3. **`no` 语义**:该问的 `no` 只证「已注册子集不足」,不得短路为「仓库无答案」、不得替代 k 次 Score。封闭世界(`bootstrap_done=true`)后,file 存在性 Noul 才允许先行;即便先行,`no` 仍只证封闭绑定内的已注册子集不足,不是全库穷尽。
4. **封闭绑定消费**:封闭语义绑定 `(ws_id, corpus_epoch, files_cutoff, secret/admission policy 版本)` 由 DP2 立法;本 DP 执行时任一变化即 miss(不复用旧「无答案」)。本 DP 不另开绑定键。

`ERRATUM:` §1 Goal 约 L13「存在性 Noul 先行闸整批」+ 不变量 4 约 L111「顺序=存在性严格先行」+ §2 映射约 L130「先一个存在性 Noul 闸住整批花费(语料无答案时 1 次调用替代 k 次)」——若被解读为无条件承接设计 §4.5「语料无答案时 1 次调用替代 k 次」:论域收窄为仅封闭世界(`bootstrap_done=true`)后对 file corpus 先行;开放世界禁 file 存在性 Noul,过滤器不得以「语料无答案」跳过整批 per-chunk Score;`no` 只证「已注册子集不足」。指向 v2 §7 行「v13 §4.5 存在性 Noul 先行」(增加论域条件:仅 bootstrap_done=true 后先行;**erratum(论域)**)。

`ERRATUM:` 同上「语料无答案」若被读成「去扫全库」或「仓库无答案」——遵守 v2 §7 行「v13 §6.7 / §6.2 触点 3」(全库扫触发禁 Noul);问题文本锁在 DP2 已立法的「已注册子集是否已足够」,本 DP 不开第二套语义。

既有 gate 不动:A–H 过滤组 / I–N 记忆组 / C 组 F2 存在性键含候选集维度 / C3 两世代存在性 / G-ctx4 先行+同 query×chunk 二次零外部调用 / OQ4 `candidates_digest` 单源 / 闸门三态 fail-open(不闸) / 不变量 4「存在性批必已不在缺口」对**封闭世界 file Noul 与非 file 论域**继续有效——一律不删不弱化。开放世界 file 面的「不执行该问、不跳过整批」只加不减。

### A11 / I-file-6 · 人 veto 高于超集(`must_include ∩ veto = ∅`)

v2 §1 I-file-6:veto 由事件折叠(`v13_file_vetoes(p_sid)` 单源函数),T0/过滤/装配/bootstrap 一律不得加回。I-file-3 同句:人 deselect 是确定性 veto,优先级高于一切超集。Oracle 记录:deselect 是确定性 veto,超集不得加回。G-file-secret(+veto):deselect 的秘密路径不被超集/bootstrap 加回(违=P0)。G-cjk-file:`must_include∩skipped=∅` 不弱化;本条是过滤/装配 join 上的 `must_include ∩ veto = ∅`。

**单源**(字面冻结;不过滤另写):

```
v13_file_vetoes(p_sid)
  = fold(file_deselect) − fold(后续 file_select)
```

- 人工 deselect = `file_deselect` 事件折叠,确定性 veto。
- 再入选必须有新的 `file_select` 事件;无新 select ⇒ 路径留在 veto 集。
- 过滤缺省超集、装配 must-include、bootstrap 补漏——三路**一律不得把 veto 路径加回**。
- `must_include ∩ veto = ∅`:must-include 与 veto 相交即违约(不得用 must-include 覆盖 deselect)。

**本计划改动点**(只立法,不改上文 SQL 草案字面):

1. **过滤 join 读单源**:过滤器对 file 路径的入选/超集扩展必须 `¬ v13_file_vetoes(p_sid)`。不得另写第二份 veto 谓词、不得在 chunk_filter / defaults / 超集规则里重折事件。
2. **must-include 不得压过 veto**:装配 / 过滤 must-include 与 veto 交必须为空。相交 ⇒ 该路径保持 veto(skipped 理由走 file 面 veto,不进 applied)。
3. **bootstrap 补漏同禁**:`corpus_bootstrap` / 名字优先补漏不得把已 deselect 路径加回已注册闭包的可见超集。
4. **与秘密扫描耦合(P0)**:deselect 的秘密路径被超集或缺省方向加回=**P0**,引用 v2 `G-file-secret-veto`(表名 `G-file-secret(+veto)`)。秘密扫描 fail-closed 与 veto 同向:blocked 路径不可见;deselect 后再被超集加回比「从未扫到」更坏——把已否决的秘密路径送回模型。
5. **再入选合同**:只有新的 `file_select` 事件才能把路径移出 `v13_file_vetoes`;select 不自动恢复 blocked_secret(秘密门仍是注册门,I-file-3)。

`ERRATUM:` 无直接改写上文 chunk_filter / defaults / 超集 / G-ctx4 的冲突句——本条是 file 面 veto join 的正向登记(v2 §1 I-file-6)。若把过滤缺省超集、装配 must-include、或 bootstrap 补漏读成「可把 deselect 路径加回」,以 `v13_file_vetoes(p_sid)` 单源 + `must_include ∩ veto = ∅` 为准;指向 v2 §7 无对应改写行(§7 未列 veto 冲突——本条不发明冲突,只钉单源与优先级)。秘密路径加回另指 v2 §5 `G-file-secret(+veto)`(违=P0),与 §7 行「v13 §4.4 语料三分」(禁 ws 硬切非 file;file 面 veto 不得借超集绕过)同向。

既有 gate 不动:A–H / I–N / C 组 F2 / G-ctx4 / OQ4 / 记忆真表 / 文档与记忆分索引——一律不删不弱化。G-cjk-file `must_include∩skipped=∅` 不弱化。后续 G-file-secret(+veto) / veto join 探针只加不减。

