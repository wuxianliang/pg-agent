# v13 DP6 计划评审:过滤管道与三层记忆栈(v13-dp6-filter-memory-plan-2026-09-20.md)

评审日期:2026-09-21。评审:L4 代行(独立全新会话;ask_oracle 通道持续故障,按 loop 先例代行)。一次有界计划评审——仅评审、不实施、不改 plan、不运行任何 gate。

## Context / Scope

- 被审文档:`docs/plans/v13-dp6-filter-memory-plan-2026-09-20.md`(1922 行,首写轮,全文已读)。撰写方未跑内部探针批判,本评审是最先的独立评审。
- 交叉参照(均实读):设计冻结稿 `docs/designs/v13-context-on-pg.md`(487 行全文;§4.4/§4.5/§6.1/§6.5/§9/§10/§11/§12/§13);stepfun 设计审查 F1/F2/F10(本 plan 立法依据);上游 DP1–DP5 plan 的 §1.3/§1.4 DP6 契约行逐条对照(DP1:56/2876;DP2:65/92;DP3:169;DP4:100;DP5:109);DP1 decisions/events DDL(status 词表 line 503、events PK line 138)、DP2 judgment_calls/judgment_templates DDL(line 324/174)、DP4 §3.1bis 锁协议与 ingest/rebuild/gc 锁序(line 193–282/620–795)、DP5 v13_recall_candidates 形态(line 360/68)。
- 评审方法:rubric 五项 PASS/FAIL+证据;四项重点推演(存在性键竞态/批写锁无环/signal 前缀等价/p99 可构造性);机械猎(哈希四面/三值逻辑/签名重复/前向引用/gate 加载边界/jsonb 字面量/_many 批约束)。

## 已核实成立的关键断言(不重复列入 Findings)

- SQL 完整性:全文恰 6 处 `…`,逐处核对均在散文/注释(行 51/91/1269[SQL 注释]/1803/1897/1904),SQL 块内零占位;ASCII `...` 0 处。顶层语句 33(filter)/17(memory)逐条对账成立,13+5+6 个函数签名全树唯一,前向引用分层核过(envelope/assemble 为 LANGUAGE sql 创建期解析,其依赖 `require_filter_templates/candidates_digest/filter_ref/chunk_filter_action` 均先建)。V3006 上游零占用(DP1–5 仅 V3001–V3005)。
- 上游契约消费清单 26 条逐条对照上游 §1.3/§1.4 原文,无失实转述;两处载体级偏差(③digest 非 csh/④needed 新分支落合并层)均已按规范记附 A #3/#4 且论证成立——尤其 #4 的六输入键覆盖论证(tools 行集 revision/needed 体 cgr/模板行集 cgr/语料代数 cgr[DP5 接线]/token.goal/token.recall_ver)完整闭合,无漏报面。
- per-chunk 键的哈希四面同源成立:材料构造(`v13_filter_ref`,IMMUTABLE+64hex 守卫)=写入(`v13_filter_ask` 经 judgment_hash→row_context)=存储(decisions.context 原物)=装配 join(等值比较同一函数输出),零哈希重算/零 GUC。canonical 路径逐字节转发 `v13_group_state`(分支仅两处)。signal 升序=hash 升序论证明确(`'chunk::'` 7 字符定长前缀+hex 字母表,substr(,8) 位次核对无误;`:` 不可能出现在 sha256 hex 内——推演③无碰撞)。
- §4.5/§6.5 张力(联合批态×窄键)按 OQ3 特别法优先+附 A #5 呈报父 loop:可辩护——§4.5 原文自身把 per-chunk 缓存键公式与 `_many` 批并书(设计自己组合了二者),G-ctx4-3(跨 session 复用)在联合键下不可构造;且 per-chunk 键引用与载荷正文之间确为内容寻址确定函数(chunks.body 被 CHECK 钉死为 content_hash 唯一原像),§6.5 所防的静默漂移面在 per-chunk 侧结构性不存在。批间交叉污染归模板版本拥有,与设计键公式字面一致(键公式本身不含批组成——该面是设计的,非 plan 引入)。
- 覆盖面对照 §4.5/§4.4 全条目有落点(§2 映射表逐行核);三层齐:结构化层 stannum on decisions.question、逐字层投影+策展(user/assistant→user/message+llm/message 映射论证成立——worker 生成语义事件唯一族)、水印谓词、文档/记忆语料分区(独立表零 corpus 列);远程层=设计明文「已在本族机制内」零新建,正确。G-ctx4 三断言映射 C1/C2、D1、D2 不弱化;§12 台账逐条在 §7;教程映射(§6)与 ch10/ch13/ch5 承诺逐条对得上。
- 承接面:DP2 五义务全兑(题面/哈希经同族 builder、cache/calls 复用、project_state 任意 jsonb 形状经模板 projection 字面兑现、零第二缓存、身份=信封冻结值);DP4 路径冻结(filter_ref 构造 `context->'chunk'->>'content_hash'` 精确路径)+升序写者契约(consult 循环/fbatch/落行三处 ORDER BY signal);DP5 k_max 结构上界+一页账更新(k=64→4 ask/3 慢路轮、闸关=2 ask 常驻形态,数字自洽);DP3 defaults v2 两点三态经 DP3 校验器天然过(键集/词表核对)+消费集自动非空(F2 gate)。
- p99 可构造性(推演④):builder 只 INSERT transcript_chunks+读 events(FK 检查 FOR KEY SHARE 于既有行,不碰新 append)、零 sessions/chunks 触碰;基线/载入两侧 append 同经 v13_append_event 同一序列化面,比值比较成立;三轮中位=DP4 H1 协议。L2 锁面机理断言补强。K3 复合计划形态已列实施期冒烟且不承正确性(风险 11 回退在档)。
- OQ1–OQ10 逐条可辩护:双 stage 四依据、合并层单 recall 求值、digest 载体、F10 三件套、fail-open 方向论证(F1 只要求逐点表+版本化,方向未裁——plan 的证据装入族类比+装箱兜底论证成立)、sections 不做(manifest v2 缝)、每事件一行、stannum 直取(§7 分层对 CJK 记忆语料同构适用)、worker 契约零改动(goal 哈希钉定读取消键-载荷漂移)。

## Findings(0 P0 / 2 P1 / 5 P2)

### P1-1 `v13_candidates_digest` 摘要的是候选对象全文,不是裁决所指的 content_hash 全集——F2 键语义实现与立法文本不符,且现有 gate 全数测不出

- 位置:§3.1 L1 `v13_candidates_digest`(plan 行 174–179,`jsonb_array_elements_text` 于行 177);对照 OQ4 裁决(plan 行 72–78)、函数自身注释(行 173「排序去重候选 content_hash 全集的 sha256」)、附 A #3、F2 修法原文(stepfun 评审:「hash(query.content_hash, 排序后候选 content_hash 全集)+模板/model/版本」)。
- 问题:`p_candidates` 是 DP5 信封第 20 键 `candidates`——**三键对象数组** `[{content_hash,bm25,spans}]`(DP5 §3.1 OQ3/行 68)。`jsonb_array_elements_text` 对对象元素返回其全文序列化,故 digest 实际材料是**含 bm25 与 spans 的完整对象集**,不是 content_hash 全集。三个后果:
  1. **miss 域比立法宽**:BM25 是语料统计的函数(设计作用力 1:IDF/avgdl 随 ingest 漂移)。语料增长但候选哈希集不变(无关文档推高共享词 IDF)时,同一候选集的 bm25 值漂移 → digest 变 → 存在性键无谓轮换。OQ4/附 A #3 的核心论证「较 csh 更窄:仅候选维度,目录变更不轮换存在性键」**按实现是假的**——对象级 digest 仍会因非候选集维度轮换。
  2. **装配侧存在性行 join 可静默失配**:jud CTE 以 `d.context = {query_content_hash: fc.gh, candidates_digest: fc.dig}` 匹配存在性行,fc.dig 来自装配时点自身 recall 产物。parse 与 settle 之间语料漂移 → 同哈希集不同 bm25 → digest 不等 → 存在性行从 judgments 消费集静默丢失(F3 断言的「恰 existence 一行」在漂移 fixture 下不成立;现有 fixture 均 same-turn 无漂移,测不出)。方向保守(丢失→F1 默认 fail-open 装入,不静默排除),非安全洞,但 DP3 消费集契约的完备性被静默侵蚀。
  3. **gate 语义弱化**:D5 只断言「变→互异/乱序→相等」——对象级 digest 两断言全过;「仅候选维度」无任何断言。C3(F2 轮换)靠新哈希触发,同样过。即:现有 gate 组**全绿地放行错误语义**。
- 修法:一行改——`FROM (SELECT DISTINCT cand->>'content_hash' AS h FROM jsonb_array_elements(p_candidates) cand) d(h)`;D5 fixture 不变(乱序归一/变互异仍过);**新增一条 gate 行(D 组)**:手工构造仅 bm25 不同的两组 candidates → digest 相等(把 F2 字面「候选集维度」钉成行为断言);附 A #3 的「更窄 miss 域」论证随实现成立。

### P1-2 存在性 ask 的键-态绑定缺口:体缺候选被静默剔出 state(可退化为空 chunks 问),「无答案」在全集键下落缓存——F2 的死法从侧门回流;E6 的「零 ask」断言与此路径矛盾

- 位置:§3.1 L6 resolve filter 半边,存在性 state 构造(plan 行 965–982,`WHERE x.b IS NOT NULL` 于行 982);外层闸守卫(行 ~1040);E6(plan 行 1700)。
- 问题:存在性键 digest 覆盖**冻结候选全集**,但 state 构造以 `x.b IS NOT NULL` 静默丢弃 parse→resolve 窗口内体已缺的候选体(body 按 content_hash 查 chunks 表无行)。键声称覆盖全集、载荷实为真子集——OQ3 那套「键引用与载荷正文是内容寻址确定函数」的辩护**不迁移到存在性 ask**(存在性 state 不是 digest 的确定函数)。失败链:parse 冻结候选 {c1..cn} → 窗口内无引用行被删(E6 自己认定手动 DELETE 是 DP4 合法路径;gc delete 模式未来同理)→ worker 慢路在新快照下 resolve → 存在性以缺 c_i 的 state 问出「无答案」→ 按**全集** digest 落缓存 → c_i 同体重摄取(同 content_hash 返回,如 ops 误删后等体重灌)→ 下一 parse 召回同一候选集 → digest 不变 → **缓存命中陈旧「无答案」→ 闸关 → per-chunk 整批被闸 → 新证据静默消失**。这正是 F2 立法要封死的「不报错,只静默漏召」死法,经体可用性(而非候选集身份)侧门回流;不变量 3 的字面(候选集不变则键不变)被遵守,但其保护意图被击穿。退化形态:窗口内全部候选体被删 → state.chunks=[] 仍照问(纯浪费+全集键下落「无答案」)。
- 附带的 gate 矛盾:E6 断言「全缺口皆体缺 → 零 ask 返回 remaining=0」——按现行代码,存在性行仍在 gap 时走存在性分支照问(外层守卫的 `NOT EXISTS(corpus_exists in gap)` 为假即放行),该断言**仅在存在性已预答(缓存命中)的未声明前提下成立**,fixture 按字面构造会红。
- 修法(与 plan 自己的 per-chunk 纪律同构——fillable 对体缺行「不可填,下一信封自然收敛」):
  1. resolve filter 半边入口加全集体在场守卫:`count(chunks 中在场候选体) = jsonb_array_length(p_env->'candidates')`(与 state 构造同一事务快照求值);任一体缺 → **本 pass 整个 filter 面跳过(存在性不问,不变量 4 的严格先行不被破坏),并把不可填的存在性缺口与体缺 per-chunk 行同口径剔出 remaining**(防 worker/advance ③ 空转;下一信封自然收敛)。守卫与 state 同快照,MVCC 下闭合(快照内一致即键-态一致;可见的体缺才构成洞,守卫恰好拦可见体缺)。
  2. 空候选退化形态由同一守卫覆盖(空集时信封侧 B3 已不产存在性行,双保险)。
  3. E6 重写:声明存在性预答前提,或改断言新守卫路径(体缺 → 零存在性 ask ∧ 零 judgment_cache 行 ∧ remaining 收敛口径)。
  4. **新增 gate 行(C 组)**:parse → 手动 DELETE 一个候选 chunk 行(合法路径)→ resolve → 断言零存在性 ask、零 cache 落行 → 同体重摄取 → 新 parse → 存在性正常问——把键-态绑定钉成行为断言。

## P2(实施期处置;不阻断)

1. **「共八处」清单记账不实**(§1.1,plan 行 31):⑥称 chunks/decisions「各追加一个索引」,而 §3.2 另有 `ix_decisions_question_stannum ON decisions`(行 1533)——对既有表的第三个索引追加,未入清单。变更本身是 §4.4 明文指派(纯追加、性能件可独立 DROP),非实质越界;修法:清单改「九处」或单列第⑨项,防后续评审按八处封闭清单对账失配。
2. **「复合序无环」断言过强**(消费清单 #15,plan 行 51;推演②结论):对 ingest 成立(hash 锁单批 `DISTINCT ORDER BY` 全局升序,DP4 行 642–647);对 rebuild/gc **不严格成立**——两者单事务内逐源循环取锁(DP4 行 727–728/776–777),hash 序逐源重启,全局非单调。理论环可构造:写者升序持 {b..z},rebuild 持源 S1 之 z 求 S2 之 b → 互等 → 40P01。缓解三重(40P01 fail-loud 非静默;resolve/rebuild 均幂等可重试;gc v1=dry-run-only 零锁),且这是 DP4 上游性质、DP6 写者侧纪律(升序)已是契约唯一正确形态。修法:G4 增补 writer∥rebuild 多源交错冒烟,或该句措辞降级为「与 ingest 端复合序无环;rebuild/gc 端为上游遗留面,40P01 幂等重试兜底」+README 运维注记。
3. **freshness 分母含空体策展事件**(§3.2 `v13_transcript_freshness`):`type IN ('user/message','llm/message')` 的 max(seq) 计入空体事件,而 builder 永久跳过空体(`coalesce(...,'')<>''`)→ 尾部空体事件的会话 lag 恒≥1 不收敛(max_lag=16 下需 17 连发才降级,后果 cosmetic 但语义不洁)。修法:`max_curated_seq` 加与 builder 同款非空体过滤。
4. **附 B 自检行与 SQL 自相矛盾**:附 B 称「全部词表判断走显式 IF(零 NOT IN 裸用)」,而 L6 信封/resolve 有两处 `NOT IN ('chunk_score','corpus_exists')` 字面(名称过滤,上游保证 template_name 非 NULL,安全)。修法:自检行措辞收窄为「策略动作词表判断走显式 IF;族名过滤用 NOT IN(操作数非 NULL 由 DP2 needed 形状保证)」。
5. **信号命名空间保留未声明**:`v13_row_context` 两分支占用 `corpus_exists` 与 `chunk::%` 前缀;未来 canonical 族若同名,`chunk::` 分支有 64hex fail-closed 拦截,`corpus_exists` 分支无守卫(会静默换 context 材料、canonical 哈希漂移)。模板种子是受控部署面,现险为零。修法:README/§1.4 契约加一句两名称保留声明即可。

## Rubric 裁定(逐项)

| # | Rubric | 裁定 | 证据要点 |
|---|---|---|---|
| 1 | 可直接开工 | **FAIL(经 P1 修复后 PASS)** | SQL 完整性本身全过(6 处省略号全在散文/注释、33/17 语句可执行级、签名/前向引用/字面量/V 码核清);OQ1–OQ10 全部可辩护。但 P1-1 的 F2 核心构件实现与裁决语义不符、P1-2 缺守卫——两处各一行级修正+两条 gate 行,不伤结构。 |
| 2 | 覆盖 §4.5+§4.4+G-ctx4+p99+教程+§12 | **PASS** | §2 映射表逐行对得上:存在性先行闸/per-chunk Score via _many(per-chunk Noul=同机械异模板行,零代码缝台账,defensible)/全集 Choice=设计自留重排/跨 session reused_from(经 DP2 机制,D2)/三层齐/分区(独立表零 corpus 列)/G-ctx4 三断言 C1C2·D1·D2/p99 L1/§6 教程/§7 台账全表。 |
| 3 | gate 可执行不弱化 | **有条件 PASS** | 十四组总体可执行且不弱化(mock 计数=judgment_calls 行数、毒化联立 failed=false∧asked=0、F1 三形态 basis 区分、J2 上一 turn、L1=DP4 H1 协议)。例外两处随 P1 修:E6 前提未声明;「仅候选维度」无断言(D5 现有形态放行对象级 digest)。 |
| 4 | 不越界 | **PASS** | 摘要验收→DP7(§1.4⑤)、latch→DP8(§1.4 DP8)不抢;八处授权清单逐条可辩护(①经 DP2「同一族机制」强制、②③④⑤上游契约明文、⑥⑦⑧纯追加/预留缝);§4.5/§6.5 张力经 OQ3 特别法+附 A #5 呈报(可辩护:§4.5 自身并书 per-chunk 键与 _many,G-ctx4-3 在联合键下不可构造)。记账瑕疵见 P2-1(非实质越界)。 |
| 5 | 承接面健康 | **PASS** | DP2 五义务全兑(needed 分支载体偏差记附 A #4,六输入键覆盖论证闭合);DP4 两纪律兑现(升序三处 ORDER BY signal+路径冻结);DP5 k_max+一页账自洽;DP3 消费集+defaults v2 全兑。 |

## 重点推演结论(控制器指定四项)

1. **存在性键×候选集竞态(①)**:信封内键与态同源冻结,重摄取不改变本 pass 的键——竞态不在键而在**态的体可用性**:体缺候选被静默剔出 state,全集键下落缓存 → P1-2(含 MVCC 快照论证与修法)。
2. **批写锁×DP4 锁协议(②)**:DP6 写者升序纪律正确且是 DP4 契约唯一形态;与 ingest 端(单批升序)复合序无环成立;rebuild/gc 端逐源重启升序存在理论环(上游性质,fail-loud+幂等重试+v1 dry-run 缓解)→ P2-2。
3. **signal 前缀等价(③)**:无碰撞——content_hash=sha256 hex([0-9a-f]),`:` 结构性不可现;`'chunk::'` 7 字符定长前缀+substr(,8) 位次核对无误;残余仅未来命名纪律 → P2-5。
4. **tick×append p99(④)**:可构造——builder 只触 transcript_chunks+events 既有行(FOR KEY SHARE),零 sessions/chunks 面;两侧 append 同序列化面,比值比较成立;K3 复合计划已列实施期冒烟不承正确性。

## 机械猎记录

哈希四面同源:per-chunk 四面成立、canonical 逐字节转发成立;存在性四面有一处语义偏差(P1-1)。三值逻辑:IS DISTINCT FROM/IS TRUE 全面使用;两处残余(NOT IN 操作数上游保证非 NULL;noul NULL 穿落 review 带——β 校验前置封)P3 级不立案。签名重复:0。前向引用:0(sql 函数创建期解析依赖序逐层核过)。gate 加载边界:clean(≤10/≤11;H4/N3 切片断言)。jsonb 字面量:种子 5 处单完整字面量+::jsonb。_many 批约束:逐投影分批(存在性批/chunk 批各自单投影共享 state)符合 §6.5 批形态;键窄态联合张力经 OQ3+附 A #5 呈报(可辩护)。

## 裁定与出口

**verdict:有条件过(0 P0 / 2 P1 / 5 P2)。** 两 P1 均为一行级修正+gate 行增补,不伤架构、不动 §1.4 契约面;修复并自证(新增两条 gate 行的 fixture 构造说明)后即可开工,无需全量重审(控制器按 diff 复核 P1 修法即可)。

**是否可进 DP7:可以并行启动。** 两 P1 均封闭在存在性闸门机制内部,不触及 DP7 消费的任何 §1.4 契约(judgment_calls 计数面、chunk_filter/defaults 策略行、sections 输入面[candidates.decision_id/judgments/trace/spans]、memory reader 签名、k_max 一页账基线)。DP7 开工前提只是本 plan 的 P1 修法经控制器确认入文。

## 静态核验

- 被审文档基线:`docs/plans/v13-dp6-filter-memory-plan-2026-09-20.md` 1922 行,全文已读(4 段)。本评审未改动该文件。
- 交叉参照实读:设计稿 487 行全文;stepfun 评审 134 行全文;DP1–DP5 的 DP6 契约行及其 DDL/锁协议/信封形态节选;引用行号均来自上述实读。
- 未运行任何 DDL、gate 或 runtime 探针;未加载任何数据库。
