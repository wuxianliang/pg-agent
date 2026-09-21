# v13 DP4: chunks 投影与跨度装配 — 实施计划

> 状态:修复 round 2(turn 24,DP4/8;round 1 后 L4 有条件过——0P0+3P1(supersede↔rebuild 复活/D4 与封闭词表自相矛盾/DP6 批写锁纪律未绑定)+顺手 P2 三项(set_config 恢复兜底/⑧ 边界前置/whole_chunk 空体 belt)全部处置,附 B 记档)。
> 设计输入:`docs/designs/v13-context-on-pg.md` §4.2/§4.7/§7/§8/§9(chunks 切片)/§10(G-ctx2)/§12/§13(冻结禁改)。
> 评审输入:`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md` **F3(P0)**——chunk_offset 列 + 被引用内容保留规则 + 回放 gate,已裁为设计缺口,本 plan 按此立法并在附 A 呈报设计未改。
> 撰写方式注记:context_builder 通道今日不稳(turn 13 两次/turn 18 四次 ACP 故障先例),经 brief 授权由主会话代行撰写,全部基座文档(DP1 §1.3/DP2 §1.4/DP3 §1.4/教程 ch7/设计稿全文/stepfun 评审 F3)已逐一通读并按契约消费;探针批判子会话照 DP3 先例补一轮。

## 0. 执行索引

| 项 | 内容 |
|---|---|
| **Goal** | 把 §4.2 chunks 三纪律(行自证/重摄取同事务/外部只记 hash)+ §4.7 跨度装配(chunk 尺寸解耦、跨度生产者、装配单元族)+ §7 T0 的 chunks 侧(tsvector 起步可运行)+ F3 三修法(chunk_offset 列/被引用保留规则/回放 gate)落成 v13 第 7 个 stage `v13/chunks/`,以 **G-ctx2 全部五断言** + F3 gate + 保留规则 gate 收口 |
| **Done when** | `uv run python v13/chunks/test_chunks.py` 退出码 0(A–J 十组全绿);提交前 DP1 四 stage + DP2 + DP3 gate 全部复跑(各自 stage 库前缀切片,不受本文件影响);收尾工件齐(load.py 第 7 位/README/本 plan 的映射表) |
| **Key files** | `v13/chunks/v13_chunks.sql`(全新增,SQL_LOAD_ORDER 第 7 位纯末尾追加)、`v13/chunks/setup_db.py`、`v13/chunks/test_chunks.py`、`v13/chunks/README.md`;`v13/load.py` 仅追加一行路径与 `STAGE_THROUGH["chunks"]=7`,零改动既有文件 |
| **Dependencies** | 分解表:无(与 DP5 可并行);实际加载依赖 DP1–DP3 全部六文件(本 stage 库加载前缀 7 文件)。DP5(recall)依赖本 DP 的 chunks 存在 |
| **Size** | 单 stage 单里程碑;SQL 一个文件(44 条顶层语句:3 表/23 函数语句[22 新 + 1 OR REPLACE v13_context_required]/9 触发器/3 索引/2 种子 INSERT(4 行:meta 1+policies 3)/1 pg_cron DO 块/3 ACL 语句);gate 一文件十组 50 行断言(含两连接竞争 J 组) |

---

## 1. 定位与边界

### 1.1 本 DP 在 v13 版图中的位置

DP4 是设计 §11 交付排序第 3 条「刻画通过后换 T0 recall definition;chunks 投影 + 三纪律」的 **chunks 半边**:DP1(两阶段 advance)落了推进骨架,DP2(判断信封)落了判断缓存,DP3(manifest 骨架)落了「证明当时发现了什么」的清单平面——但清单里的候选至今只有 goal 自身的 echo(DP3 §3.4 行 1007–1015)。DP4 落**候选的内容平面**:文档语料以 kind='chunk' artifact 落账(ch7 纪律),`chunks` 作为可重建投影承载检索索引(§4.2),跨度装配原语(§4.7)让 manifest 的 candidates.spans 有生产者,F3 三修法让 exact replay 在 chunker 变迁后仍逐字节成立。

与 §11 顺序的关系:§11 把 chunks 排在 stannum 刻画之后,是指 **stannum 索引换 definition 那一步**(归 DP5);§7 T0 明文「语料英文:tsvector 起步」——tsvector 起步路径的 chunks 侧(生成列 + GIN 索引 + T0 跨度提取)是先行形态,不依赖 stannum 一根毫毛,故 DP4 无前置、与 DP5 刻画并行不悖。stannum 本体(索引、绑定矩阵、highlight 同 tokenizer 提取)全部归 DP5,本 plan 只留缝。

**骨架(非全量)**:本 DP 落投影与生产者原语,不落召回函数族(DP5)、不落过滤管道与 per-chunk verdict(DP6)、不落记忆语料 transcript_chunks(§4.4,DP6)、不落 T1/bigram(§12 台账)。manifest 侧零结构改动:DP3 的 candidates 四字段族(content_hash/bm25/spans/decision_id)已立法,DP4 只定义 spans 的**生产者**与形态兑现(doc=chunk content_hash + chunk 内字节坐标,恰为 DP3 OQ4 已裁形态),不改 manifest schema、不加 section kind。

**硬边界(零改动纪律)**:DP1/DP2/DP3 计划文件与其(未来的)SQL 文件零改动。对既有对象的变更恰两处,均为授权缝或纯追加:① **`CREATE OR REPLACE FUNCTION v13_context_required`**(同签名换体、七键扩八键)——DP3 §1.4 DP4 行明文发布的函数替换缝(「函数替换,签名 `(uuid)→jsonb` 不动」);② **对既有表 artifacts/decisions 各追加一个 BEFORE 触发器**(引用端 advisory 锁,L4 并发修正 §3.1bis)——定义在本文件内,不改两表任何既有 DDL/约束/触发器;前缀切片库不加载本文件,DP1–3 库零影响。其余全部是新增对象。

### 1.2 上游契约消费清单(逐条,来源:DP1 §1.3 / DP2 §1.4 / DP3 §1.4)

| # | 上游契约(原文要点) | 本 plan 消费方式 |
|---|---|---|
| 1(DP1) | 候选集来源缝 = `v13_needed_judgments` 的候选推导(DP1:tools 目录 + fold_state);DP5 的 `v13_recall` 族替换该推导,`candidate_set_hash` 定义不变 | 本 DP 不触碰 needed 推导(chunks 进候选是 DP5 的事);DP4 对 DP5 发布语料代数键与消费契约(§1.4),DP1 #59 硬契约原样转发 |
| 2(DP1) | **硬契约(turn 9,#59)**:DP5 引入的语料/索引版本依赖(chunks/recall 语料)不被函数体 DDL 覆盖——必须并入 cgr 的 bump 面或另立单调键进信封/探针步 0 比对,否则无漏报论证在语料面重开 | DP4 立**另立单调键** `v13_chunks_meta.generation`(语句级触发器维护,任何路径的 chunks DML 必 bump,漏不掉);该键进 `v13_context_required`(DP3 契约),**probe/cgr 侧接线归 DP5**(DP4 时代 needed 推导不消费语料,语料变更不可能改变 candidate_set_hash——零 miss;DP5 换推导时必须把 generation 并入 cgr bump 面或 probe 键集,见 §1.4 DP5 行) |
| 3(DP1) | `v13_policies` 表载体共享:(name,version) 主键 + at-most-one active;读侧单源 `v13_policy()`;追加=新版本行+同事务翻 active | DP4 播三行 v1 active:`chunks_ingest`(chunker 参数)/`span_assembly`(装配单元参数)/`chunk_gc`(GC 模式门);照 DP3 judgment_defaults 先例,种子即校验器输入 |
| 4(DP1) | 双登录强制架构(v13_resolve_login/v13_route_login 单成员;v13_recall/v13_resolve/v13_route NOLOGIN 组);运行角色对表的最小授权矩阵 + 负向权限测试纪律 | DP4 新表对运行角色只授 SELECT(v13_recall;DP6 届时补 v13_resolve);写路径(owner 平面)零运行角色授权,gate H 组负向断言 |
| 5(DP1) | effect ledger:kind ∈ {judge,tool,llm,context_refresh,human};`v13_enqueue_effect(p_sid,p_kind,p_request,p_tool)` 幂等,身份=(kind,request) 推导;claim/complete CAS;`v13_complete` 先行结算后 artifacts 落行同事务可见 succeeded | 摄取驱动器契约(§3.3):ops 在库外读文件 → 经真实 enqueue/claim/complete 获得 succeeded tool effect → 同事务调 `v13_ingest_document`;外部 IO 不进事务(AGENTS.md 不变量 4) |
| 6(DP1) | 每 stage setup 只加载到当前 stage(`files_through` 前缀切片);gate 断言只能引用当前 stage 已加载对象 | `v13/chunks` 为 SQL_LOAD_ORDER 第 7 位纯末尾追加;`STAGE_THROUGH["chunks"]=7`;本 stage gate 引用对象全部 ≤7 号文件;DP1–DP3 各自 gate 在其前缀库复跑不受 8 键 token 影响(其库不加载 7 号文件,token 仍七键) |
| 7(DP2) | needed 推导面自 DP2 起为三处(tools 目录/needed 函数体/judgment_templates 行集),分别由 revision/cgr/行级触发器承接 | 本 DP 不新增 needed 推导面(chunks 不进 needed);DP5 新增召回判断族时按 DP2 该行既有机制承接 |
| 8(DP3) | **`v13_context_required` 是唯一新鲜度源**:chunks 投影落地后,语料版本键(重摄取代数或 corpus 指纹)必须并入其键集(函数替换,签名 `(uuid)→jsonb` 不动)——漏并=语料变更不触发 refresh 的 freshness miss | §3.6:OR REPLACE 换体,七键扩八键(增 `corpus`=v13_chunks_meta.generation);DP3 体逐字保留(三处策略缺行 RAISE 原样),仅追加一 DECLARE/一子查询/一键/一 RAISE;键集变更 ⇒ 旧 active token 全失配 ⇒ 全域恰一次 refresh(DP3 OQ1 既判语义) |
| 9(DP3) | candidates.spans 按 OQ4 形态填充(doc=content_hash);manifest/decisions 仍只记 content_hash,**禁 (source_hash,chunk_no)**(ch7 纪律 3,跨 DP 不豁免) | §3.6 跨度生产者输出形态恰为 `[{doc:<chunk content_hash>, offsets:[[s,e],...]}]`(F3① span 身份=chunk content_hash+chunk 内字节坐标);ingest/rebuild/spans 全部返回值经 gate 源断言不含 source_hash/chunk_no 外泄键 |
| 10(DP3) | artifacts 表已落(ch7 逐字形状):append-only 触发器、produced_by→succeeded effect 守卫、`CHECK(content_hash=encode(digest(inline::text,'sha256'),'hex') AND size=octet_length(inline::text))`;写路径=两个 DEFINER lander(context 两 kind),但 INSERT 面按 ch7 开放(运行角色零授权) | DP4 首次启用 kind='chunk' 写路径:owner 平面经 `v13_ingest_document` 落行(触发器守卫自动生效);**哈希同源硬约束由此成立**——chunk 的 content_hash 必须=artifact 的 content_hash,而后者被 CHECK 钉死为 sha256(inline::text)=sha256(to_jsonb(body)::text),故 chunks 行自证公式取同式(OQ1 裁决,附 A #3) |
| 11(DP3) | blob GC 首版不实现只落策略键(referenced-forever);「被引用即保留」是不变量 4;窗口化 GC 触发=扫描恢复成本实测超标(§12),「DP4+ 语料面一并评估」 | DP4 立chunks 侧保留规则(F3②)并落 `chunk_gc` 策略键(mode='dry-run-only');执行器代码在场但被策略门关闭,与 DP3 blob 侧同构(§7) |
| 12(DP3) | token 追动键缝:任何新进 prefix_identity 材料的输入必须在 token 有键(OQ1 gen_ver 先例);token 键集增删⇒全域恰一次 refresh | corpus 键即本缝的语料版;span_assembly 策略版本**暂不入 token**(DP4 时代装配不消费 spans 进 manifest——DP5 接线时必须并入,§1.4 DP5 行,防 freshness miss) |

### 1.3 Open Questions 裁决(本节为最终权威)

**OQ1 裁决:行自证哈希公式 = `v13_body_hash(body) := encode(digest(to_jsonb(body)::text,'sha256'),'hex')`——与 artifacts CHECK 同源,「sha256(body)」的载体化。**

- 依据:ch7:82「`content_hash text NOT NULL, -- 行自证:写入时 = sha256(body)`」与 ch7:146–147 G-ctx2「且 exists artifacts(content_hash, kind='chunk')」两条若按字面 raw-text 哈希执行,**结构性互斥**——artifacts 的 content_hash 被 DP3 CHECK(消费清单 #10)钉死为 sha256(inline::text),而 kind='chunk' 行的 inline=to_jsonb(body),其 ::text 是带引号与转义的 JSON 串;raw sha256(body) 永远不等于它,exists 断言永不成立。
- 裁决:chunk 的「body」以其 artifact 载体的**规范字节**(to_jsonb(body)::text)为哈希输入;公式收口为单一 IMMUTABLE 函数 `v13_body_hash`,chunks CHECK、ingest、rebuild、gate 四处全经它(哈希同源教训的硬执行)。源文档、切片、跨源同文行全部同式 ⇒ 内容寻址去重与 exists 断言免费成立。
- 代价与边界:jsonb::text 序列化在 PG 大版本间理论可变(风险表 #1);本式钉死于部署版本,升级=重摄取或保留旧行(referenced 行本就不可删)。设计稿字面「sha256(body)」未改,附 A #3 呈报载体化。

**OQ2 裁决:rebuild = 保护式重灌(删无引用行+按活动策略重投影);被引用源锁定(lock),不做字面 truncate。**

- 依据:F3②(已裁)要求被引用 chunk 行不可删;`TRUNCATE` 既绕行触发器又必然杀 referenced 行——设计 §4.2/ch7:86「truncate+重灌」与 F3② 在 chunker 升版场景**直接冲突**(同 source_hash 新旧两代行在 PK (source_hash,chunk_no) 下必然撞键,主键按 §4.2 冻结保留)。
- 裁决三分:① `v13_rebuild_chunks()`:逐源判定——源存在任一被引用行 ⇒ **locked**,跳过(计数呈报);否则删其全部行+按**活动策略**的 chunker 重投影(artifacts 是真相,重切片确定性);② `v13_ingest_document` 对 locked 源:新切片与现存行 (chunk_no,content_hash) 序列全等 ⇒ 幂等 no-op;不等 ⇒ RAISE V3004(retention-locked);③ TRUNCATE 被触发器整体拒绝(§3.1 belt),防绕过保留规则与代数计数。
- 语义后果:rebuild 从「恢复投影完整性」扩为「无引用面的语料升级」;被引用源不随 chunker 升版(其切片 artifact 不可变,exact replay 由 hash→artifact 回取恒成立,F3③ gate 钉之)。逃生缝:同逻辑源新内容=新 source_hash 重摄取(不撞锁);IDF 失真实测超标再迁 content_hash 主键(§4.2 原文预留,台账)。设计字面「truncate+重灌」被保护式重灌取代,附 A #2 呈报。
- 幂等口径:rebuild 跑两次,chunks **表内容**字节级一致(gate E1);`v13_chunks_meta.generation` 允许照常 bump(它是事件计数,不是表内容——ch7:144「跑两次字节级一致」断言对象是投影表)。

**OQ3 裁决:语料代数键 = 单行 meta 表上的单调计数器(重摄取代数),语句级触发器维护;corpus 指纹被弃。**

- 依据:DP3 契约给两选项。指纹(对全表排序取 sha256)每次 ② 都要全表扫——token 在 advance 会话锁内,毫秒级承诺(DP3 OQ1 同款论证)不成立;计数器=单行读。DP3 OQ1「不做 bump 计数器」的论证针对**会话语境生产者面**(枚举生产者易漏、编排事件递增致活锁);语料面无此形状——生产者结构性封闭(只有 chunks 一张表的 DML,语句级触发器对**任何**写入路径生效,包括 psql 手工/COPY),且 bump 不在 advance 路径上(摄取是离线/worker 面),无活锁面。
- 载体:`v13_chunks_meta(singleton PK CHECK, generation bigint)`,种子 (true,0);`AFTER INSERT OR DELETE ... FOR EACH STATEMENT` bump(+1/语句,与行数无关——批量摄取一次一 bump)。幂等重摄取同内容也 bump:保守超集,至多一次多余 refresh,与 DP3 OQ1 straggler 取舍同款记档。
- UPDATE 不进 bump 面:chunks 行不可变(OQ5 触发器拒 UPDATE),语句永不存在;TRUNCATE 被 belt 拒。

**OQ4 裁决:chunk artifact 形态 = 源文档与切片均为 kind='chunk'、一律 inline、摄取时内容寻址去重;源台账 `v13_sources` 单表。**

- 源文档必须 durably 在场(rebuild 重切片的输入),切片必须逐行对应 artifact(纪律 1 的 exists 断言)——两者都是 kind='chunk'(ch7 词表开放,无需新 kind,零 DDL)。粗切(整文档一 chunk)时切片=源,chunk 0 的 content_hash=source_hash,一次落行两用(ch7 7.3 最小形态原样)。
- inline 一律化:v1 拒绝超限文档(RAISE V3004;max_doc_bytes 策略键,默认 1MB)——artifacts 的 ref 路径(ch7「超限一律 ref」)对 chunk 族暂不启用:chunks.body 本就持有正文,若 artifact 走 ref 则库内唯一正本落在投影表,违背「artifacts 是真相」;ref 路径与窗口化 GC 同入台账(§7)。
- 去重是上层选择(ch7 G1:同 hash 共存允许)——摄取函数显式选择去重(EXISTS 跳过),跨源同文共享 artifact 行;投影层仍落双行(§4.2「跨源同文双行由判断缓存按 content_hash 吸收」),两层各司其职。
- `v13_sources(source_hash PK, corpus, artifact_id→artifacts, ingested_at, superseded_by)`:语料归属(corpus)与源→artifact 锚的**唯一住所**——它不是第二真相源(§8 元原则 (c)):内容真相在 artifacts,corpus 归属不存在于任何其他地方。append-only 触发器执法,**单一豁口**=superseded_by NULL→值 的 lineage 标记(L4 P1-1:supersede 后旧源在台账退役,rebuild/GC(delete)/召回面均跳过——否则旧源零行后被当前策略重投影=复活已退役版本,与 B5 矛盾);corpus 冲突(同 hash 异 corpus)摄取时 fail-closed。

**OQ5 裁决:chunks 行不可变(UPDATE 拒);写路径收口为 owner 平面三函数(ingest/rebuild/gc)+ 守卫触发器族;零 SECURITY DEFINER。**

- DP3 用 DEFINER lander 是因为 refresh 在运行角色(route)连接里写;DP4 的写者全部是 owner/ops 连接(摄取驱动器、rebuild、GC、cron——cron job 以 schedule 调用者=owner 身份跑),运行角色零写需求 ⇒ 零 DEFINER、零运行角色 EXECUTE,受控面=「无授权 + 触发器 belt + REVOKE PUBLIC」。比 DP3 更简,防线不少:UPDATE/TRUNCATE 触发器拒、retention 触发器拒、artifact 存在触发器拒、代数 bump 触发器漏不掉、CHECK 行自证。
- 读面:v13_recall 授 SELECT(chunks/v13_sources/v13_chunks_meta)+ 纯读函数 EXECUTE(哈希/跨度族);v13_resolve 的 SELECT 留给 DP6 补(届时才有消费),契约行注明。

**OQ6 裁决:跨度生产者 T0 形态 = ASCII 折叠大小写不敏感的精确子串扫描(字节偏移、fail-closed 有界);装配单元族 = 纯函数 + 版本化策略行;跨 chunk 合并 v1 不做。**

- T0 诚实边界:PG 核心无「词元→字节偏移」原语(ts_headline 只回标记文本,to_tsvector 位置是词位非字节);T0 提取器对 query 词做 ASCII 折叠大小写不敏感的子串扫描(折叠只动 A–Z,字节长度不变 ⇒ 字节偏移对任意非 ASCII 正文精确),stem 不匹配(语料英文时罕见损失)——这是「起步路径可运行」的诚实形态,不虚标召回质量。DP5 的 stannum highlight(与索引同 tokenizer)换入时**签名与输出形态不变**(§1.4 DP5 契约),消费方零改。
- 装配单元族(§4.7「跨度装配不能是唯一单元」+ Oracle 2 四件)落为纯函数 `v13_assemble_spans(units, opts)`+`v13_span_unit(hash,body,s,e,opts)`,确定性管线:重叠/邻近合并(merge_gap_bytes)→ 句段边界吸附(boundary=sentence|line|none:sentence=终止符集 {.,!,?,。,!,?} 其后随空白/换行/EOS 才构成句界、换行恒句界的确定性字符扫描——首写以 line_align 行吸附冒充句段边界,L4 修正)→ 前后文窗口(context_bytes)→ 表格/代码块完整性(table_aware/fence_aware:核在 ``` 配对围栏块内→**扩到整块**;核在行首 '|' 连续段内→**扩到整段**;扩展区与核外块部分相交→钮到块边界外——首写的「栅栏钳位」把块内命中往块内收缩,方向反了,L4 修正)→ UTF-8 前向吸附(窗口算术落多字节字符内部时逐字节前进至前导字节,get_byte 续字节 0x80–0xBF 判定,≤4 步)→ 终界钳位(核恒存活,只钮扩展)。五键全在 `span_assembly` 策略行(版本化,opts 由调用方解析后传入,函数保持 IMMUTABLE 纯度可直接 gate);`mode:'whole_chunk'` 保留整 chunk 装配(跨度不是唯一单元的显式开关)。
- 跨 chunk 合并/跨 chunk 前后文:chunk 可粗(§4.7 的整个论点)使跨 chunk 场景罕见,v1 不做,缝留 DP5(§1.4)。结构级表格/代码块完整(整块/整段扩展)**已入 v1 交付**(首写误入台账,L4 修正——设计 §4.7 Oracle 2 补充是 normative 面,不是可选项)。
- 目标尺寸:策略键 target_bytes 先验 3072(2–4KB 中值);「目标尺寸由刻画 gate 用数据回答」——数据答案归 DP5 刻画 stage(§1.4 DP5 行),DP4 只落参数化与先验,不冒认结论。

**OQ7 裁决:摄取 rides effect ledger(produced_by→succeeded tool effect),驱动器契约四步;verify 的 T0 载体 = 版本化校验函数,pg_cron 按元原则自辩引入。**

- ch7 生产纪律:artifact 的 produced_by 必须指向 succeeded effect(触发器执法,无豁免面)——语料摄取不是例外,驱动器契约:① 库外读文件(外部 IO 不进事务);② ops session + `v13_enqueue_effect(sid,'tool',request,p_tool='v13_ingest_corpus')`(request 携带计划与 doc 字节数审计值,**不携带正文**——正文经参数入 ingest 函数,与「effect request 只携语义词段」纪律一致);③ claim→complete('succeeded');④ **同事务**调 `v13_ingest_document(effect_id, corpus, body[, supersedes])`。gate fixture 走同一条真实链路(断言纪律:fixture 走真实链路,DP1–3 同款)。
- `v13_verify_chunks()`(v1):七项校验——①行自证计数、②投影→chunk artifact 孤儿计数、③源台账孤儿计数、④**引用可回取+投影行在场**(候选 hash 按 kind='chunk' artifact 身份筛:DP3 goal-echo 候选非 chunk 身份不计红——首写全量 context 扫描对 goal echo 恒误报,L4 修正;chunk 身份候选必须 artifact 与 chunks 投影行双在场,F3 回放性质的日常面)、⑤GIN 可用性(**非停用词 canary 'quasar'**——'the' 是 english 停用词会被剥成空 tsquery,首写已修;enable_seqscan 会话局部强制+事后恢复,写死这一种,理由=小表合法 Seq Scan 是成本模型正确行为,不能证明 GIN 病变;gin_clean_pending_list 冲洗)、⑥meta 行在场、⑦**对账反向半边**(被引用的 kind='chunk' artifact 必有投影行;无引用孤儿=supersede 合法残留,report-only)。返回结构化报告;`p_raise=true` 时任一红即 V3004(ops 可见)。DP5 缝:stannum 索引落地时 OR REPLACE 升 v2 增第八项 `verify_index`(amcheck 风格调用)——「verify_index 进 gate+pg_cron 夜跑」在 T0 的载体即本函数,G-ctx2「verify_index 通过」在 DP4 的断言对象=v1 七项全绿,附 A #5 呈报解释。
- pg_cron 自辩(§8 元原则三条):(a) 替代自写代码——夜调度否则要外部守护进程+连接管理+凭据,全是自己写并测试的代码;(b) gate 确定性可 mock——被调度的只是 `SELECT v13_verify_chunks(true)` 一条 SQL,gate 直调函数零守护进程依赖,调度行是数据(**调度是行不是节拍器**:turn 推进仍靠 settle/effect,cron 只扫地不驱动任何推进——§8「不是节拍器」原文的遵守面);(c) 无第二真相源/第二 IO 通道——cron job 只跑本地 SQL。可用性守卫:CREATE EXTENSION 包异常捕获,不可用(pgembed 未预载 shared_preload_libraries 是现实可能,风险 #7)则 NOTICE 降级+外部队列回退(README 记 crontab+psql 等价命令),函数本身始终手动可调。

### 1.4 本 plan 对 DP5–DP8 发布的契约

| DP | 契约 | 形态 |
|---|---|---|
| DP5(recall/刻画/stannum) | ① **语料代数接线(DP1 #59 硬契约的执行点)**:换 `v13_needed_judgments` 推导消费语料时,必须把 `v13_chunks_meta.generation` 并入 cgr 的 bump 面(chunks DML 触发器追加 bump candidate_generation_revision)或 probe 键集扩第八键——二选一写入 DP5 plan 并 gate;漏接=无漏报论证在语料面重开。② T0 起步直接消费 `chunks.body_tsv` GIN 索引;stannum 索引落地时 `v13_verify_chunks` OR REPLACE 升 v2 增 verify_index 项。③ **chunk 目标尺寸的数据答案归你的刻画 gate**(§4.7:BM25 长度归化稀释;DP4 只落 target_bytes 参数与 2–4KB 先验)。④ spans 生产者换 stannum highlight(同 tokenizer)时,`v13_extract_spans` 签名 `(text,jsonb)→jsonb` 与输出 `[[bstart,bend],...]`(字节、chunk 内、非重叠、升序)不变,`v13_assemble_spans` 与消费方零改。⑤ **span_assembly 策略版本必须在装配消费 spans 进 manifest 时并入 token 追动键缝**(DP3 OQ1 同缝)——DP4 时代装配不消费它,故未入 token;你接线那天起漏键=freshness miss。⑥ candidates 数组序 `bm25 DESC, content_hash ASC`(DP3 契约原样)。⑦ 跨 chunk 合并/跨 chunk 前后文窗口的扩展缝在 `v13_assemble_spans` 的 units 形态(chunk_offset 列已备)。⑧ **引用写锁已由本 DP 结构性覆盖**(artifacts kind='context' 触发器对候选 hash 升序 advisory xact lock,§3.1bis):你的候选批量化路径若单事务落多个 context artifact,必须并集升序取锁或拆单引用集事务(锁协议纪律);⑨ **退役源不进召回面(L4 P1-1)**:召回/检索的源枚举必须跳过 `v13_sources.superseded_by IS NOT NULL` 的源——supersede 后旧源残留行(被引用存活)是 retention/exact replay 的历史证据,不是现行语料;漏跳=已退役版本继续被召回(与 rebuild 零复活同族,B5b 断言的读侧半边) | 键/索引消费+函数替换+触发器覆盖 |
| DP6(过滤/记忆栈) | ① **decisions 侧引用路径冻结**:per-chunk 判断的 chunk 身份必须落 `decisions.context->'chunk'->>'content_hash'`(精确路径)——它是 retention 检查(§3.1 `v13_chunk_referenced`)的 decisions 面,路径漂移=被引用行可被误删;届时补该路径的 GIN 索引。**写锁半边已由本 DP 的 decisions 触发器结构性覆盖**(该路径单键 advisory 锁,§3.1bis)——路径漂移不仅误删还会绕锁,冻结升级为双理由硬契约;**批写锁纪律(与 DP5 ⑧ 同款,L4 P1-3)**:单事务批写多条含 chunk 引用的 decisions 时,必须引用集并集升序预锁(或拆单引用集事务)——触发器逐行取锁只保证行内序,行间序是写者契约,否则行序非升序可与删除端(source 升序复合序)成环,「全树无环」论证的叶性前提由此绑定。② `GRANT SELECT ON chunks,v13_sources,v13_chunks_meta TO v13_resolve` 由你补(本 DP 只授 recall——无消费不授权)。③ transcript_chunks(§4.4 记忆逐字层)**不复用本表**:corpus 列隔离、独立表独立索引,水印/tick 全套归你;文档语料与记忆语料分索引是 §4.4 明文 | 路径冻结+授权补充 |
| DP7(经济件) | 无直接耦合:chunks 不进 prefix_identity(生成身份),语料经 required_revision 的 corpus 键已落;候选 est_tokens 沿用 DP3 公式(消费 section/candidates 的既有纪律) | — |
| DP8(latch/render/fork) | 无直接耦合:exact replay 的正文回取走 DP3 blob 冻结与 artifacts(hash→bytes),chunks 行的保留是第二重保险;fork 不触碰语料面 | — |

### 1.5 不变量(全 plan 有效,违反即设计背离)

1. DP1/DP2/DP3 全部不变量原样继承(两相分离/锁内零外部 IO/纯判断 IO 例外唯一/双登录/αβ 语义/行为参数冻结消费/token 与 manifest 同语句快照/冻结即不可变/manifest 只消费内容寻址身份/装配确定性)。本 plan 新读写**零外部 IO**(驱动器在库外读文件,ingest 全本地 SQL);对 DP1–3 对象的变更只限 §1.1 声明的唯一一处 OR REPLACE。
2. **行自证是结构性的,不是 gate 纪律**:chunks CHECK(经 v13_body_hash)+ artifact 存在 BEFORE INSERT 触发器 + produced_by→succeeded 守卫(artifacts 既有)三层在先,任何写入路径(含 owner 手工)都过同一套门;UPDATE 与 TRUNCATE 被触发器拒——修正投影的唯一形态是重摄取/rebuild。
3. **身份纪律**:DP4 的全部对外产出(ingest/rebuild 返回值、spans 生产者输出)只含 content_hash,禁 (source_hash,chunk_no) 外泄(gate C 组源断言);manifest/decisions 侧的「不记主键」由 DP3 校验器与 DP6 路径契约接力,本 DP 立生产者半边。
4. **哈希同源**:chunk/源/切片哈希唯一公式 `v13_body_hash`;语料代数唯一来源 `v13_chunks_meta.generation`(语句级触发器 bump+单调性守卫触发器——手工调低/删除被拒,结构性封死唯一旁路);token 唯一来源 `v13_context_required`(OR REPLACE 后仍唯一,八键)。
5. **确定性**:chunker/提取/装配/verify 全部零时钟零随机零活策略读(策略经参数或调用点解析后传入纯函数);同输入同输出(gate 直调断言);摄取返回的 generation 是事件计数,不参与任何身份哈希。
6. **单调性**:generation 只增不重置;token 八键全单调(sem/dec/goal/tools_rev/asm_ver/jdef_ver/gen_ver/corpus——DP3 七键语义原样+corpus)。
7. **文档顺序=加载顺序**;SQL_LOAD_ORDER 纯末尾追加第 7 位;ACL 全量块在文件真末尾;gate 断言对象全部 ≤7 号文件;DP1–DP3 各 stage gate 在其前缀库不受本文件影响(结构性,files_through 前缀切片)。
8. **owner 平面/运行角色分离**:运行角色对 chunks/v13_sources/v13_chunks_meta 零 DML 零写函数 EXECUTE(gate H 负向);摄取/rebuild/GC/verify 仅 owner(ops 驱动器/cron 以 owner 身份);外部 IO 一律在事务外(驱动器读文件;ingest 函数体内无任何非 SQL 调用)。
9. **引用/删除并发协议(L4 修正)**:写入端(artifacts kind='context' 候选/decisions chunk 键)与删除端(ingest/rebuild/gc delete)经同一 advisory xact 锁命名空间(20260920=content_hash 类;20260921=source_hash 类)协调——删除端 source 升序→该源 hash 升序→先锁后查后删;写入端触发器单引用集升序同锁(**行内序**——单事务批写多条引用行的写者必须引用集并集升序预锁或拆单引用集事务:行间序是写者契约、非触发器保证,「全树无环」论证的叶性前提,§1.4 DP5 ⑧/DP6 ① 立法,L4 P1-3);两端同锁同序(gate J 组两连接竞争断言)。

---

## 2. 输入 § 映射

| 设计原文(冻结) | 本 plan 落点 |
|---|---|
| §4.2 纪律①行自证:`content_hash = sha256(body)` 列;gate 断言自证成立且 `exists artifacts(content_hash, kind='chunk')`;`v13_rebuild_chunks()`(truncate+重灌);verify_index 进 gate+pg_cron 夜跑 | 自证=CHECK 经 `v13_body_hash`(OQ1 载体化);exists=BEFORE INSERT 触发器结构性执法;rebuild=保护式重灌(OQ2,F3② 取代字面 truncate,附 A #2);verify=T0 载体 `v13_verify_chunks` v1 七项+pg_cron 夜跑(OQ7,附 A #5);gate A/E/G 组 |
| §4.2 纪律②重摄取=与新 artifacts 同一事务 delete by source_hash+insert——索引随事务一致,无同步器无失效协议 | `v13_ingest_document` 单事务:land artifact→台账→(locked 分流)→delete 无引用旧行→切片 artifact→投影行;`p_supersedes` 承接「同逻辑源旧版本」的 delete-by-source_hash+台账 lineage 退役标记(零复活,L4 P1-1);插入即可检(GIN 同事务)gate B 组;「外部看不到中间态」双连接断言 |
| §4.2 纪律③外部一律引用 content_hash,不引用 chunks 主键——manifest 与 decisions 只记 hash | 生产者半边:spans/ingest/rebuild 输出形态 gate C 组源断言(§3.5);decisions 面=DP6 路径冻结(§1.4);manifest 面=DP3 校验器既有 |
| §4.2 主键 (source_hash,chunk_no) 保留;跨源同文双行由判断缓存按 content_hash 吸收;IDF 失真超标再迁 content_hash 主键 | 主键原样(§3.1 DDL);跨源同文=artifact 去重+投影双行(OQ4);主键迁移入台账(§7) |
| §4.7 chunk 可粗(整节/整文档),装配单元=被标出的跨度 (doc,offsets) 进 manifest;BM25 长度归化稀释超长文档——目标尺寸由刻画 gate 用数据回答(先验 2–4KB) | chunker 双模式 whole/para(target_bytes=3072 先验,数据答案→DP5 契约③);跨度形态=DP3 OQ4 已裁(doc=chunk content_hash+offsets),生产者 `v13_extract_spans`/`v13_assemble_spans`(OQ6);gate F 组 |
| §4.7 跨度装配不能是唯一单元:可配置前后文窗口、句段边界、表格/代码块完整性、重叠合并(Oracle 2 补充) | `span_assembly` 策略行五键(context_bytes/boundary/merge_gap_bytes/fence_aware/table_aware)+mode='whole_chunk' 整 chunk 开关;句段边界=终止符+换行的确定性吸附、fence/表格=整块扩展、UTF-8 前向吸附(§4.7 Oracle 2 normative 面 v1 全兑现,OQ6;I 组配置 gate) |
| §7 T0:语料英文 tsvector 起步→stannum(刻画后);stannum 本体归 DP5 | chunks.body_tsv 生成列(IMMUTABLE 包装函数)+GIN 索引;检索可运行性 gate F 组;stannum 缝=§1.4 DP5 行②④ |
| §8 pg_cron P1 进(扫地僧:tick/投影构建/verify_index 夜跑;调度是行,不是节拍器——turn 推进仍靠 settle);元原则三条 | 本 DP 只挂 verify 夜跑(OQ7 自辩三条+守卫降级);tick 投影归 DP6 且 §12 有触发条件;不引入任何 cron 驱动的推进面(gate 断言:job 清单仅 verify 一条) |
| §9 表切片:chunks(source_hash, chunk_no, body, content_hash, corpus, chunker_version, analyzer_version)——可重建投影三纪律;transcript_chunks 行归 §4.4(DP6) | §3.1 chunks DDL(§9 七列原样+chunk_offset[F3①]+body_tsv[T0 起步]);transcript_chunks 明确不做(§7) |
| §10 G-ctx2 全部:行自证;重摄取同事务一致(插入即可检);rebuild 幂等;verify_index 通过;p99 events INSERT 无回退 | §4 gate 映射表逐条+A–H 组(五断言分别落 A/B+E/E+D/G/H) |
| §12 YAGNI 台账(本 DP 相关行) | §7 明确不做的源:bigram 列/T1 vectorchord/pg_cron tick 空转/主键迁移等逐条 |
| §13 第 7 章:chunks 投影三纪律入「硬性规定」;manifest 指针 | §6 教程映射(ch7 正文已含三纪律与 G-ctx2 断言块——ch7:141–155;本 DP 兑现,正文零改动) |
| stepfun 评审 F3 三修法(已裁方向) | ①chunk_offset 列→§3.1;②被引用不可删/GC 只清无引用→retention 触发器+`v13_chunk_referenced` 一条 SQL+gc 函数(§3.1/§3.4);③chunker bump+重灌后历史 manifest 逐字节回放成立→gate D 组(hash→artifact 字节回取+被引用源锁+v13_replay 逐字节不变) |

---

## 3. 表/函数 DDL 与 SQL 草案

> 文件:`v13/chunks/v13_chunks.sql`(全新增;SQL_LOAD_ORDER 第 7 位纯末尾追加)。**文件内顺序=加载顺序**(§3.1→§3.8 即物理顺序)。整个文件以 BEGIN/COMMIT 包裹(DP2/DP3 形制:含 OR REPLACE,单事务原子装载)。草案级完整度:列/约束/函数签名/关键语句到位,实施者可直接开写;注释标注纪律出处。**本文件新增的 RAISE 统一 `USING ERRCODE = 'V3004'`(DP1=V3001/DP2=V3002/DP3=V3003 序列顺延,已核 DP1 全文无 V3004 占用);唯一例外=§3.6 复制自 DP3 的四处策略/meta 缺行 RAISE——逐字保留 DP3 原样(无码),换体最小 diff 纪律优先于统一码面**。

### 3.1 哈希/检索/引用原语 + 三表 + 触发器族 + 索引

```sql
BEGIN;

-- =========================================================================
-- DP4 chunks (v13_chunks.sql): chunks projection & span assembly.
-- Design: docs/designs/v13-context-on-pg.md §4.2/§4.7/§7/§8/§9/§10 G-ctx2.
-- Review: stepfun F3 (chunk_offset + retention + replay gate) — legislated
-- here, design doc unchanged (plan 附 A).
-- DP contracts: DP1 §1.3 (row DP4/DP5, #59), DP3 §1.4 (row DP4:
-- v13_context_required key set + spans shape + hash-only identity).
-- File order = load order. Owner-plane writers; zero DEFINER (OQ5).
-- =========================================================================

-- === 哈希原语(OQ1):chunk 体的规范字节 = to_jsonb(body)::text(artifact
--     载体编码);与 DP3 artifacts CHECK 同源——「sha256(body)」的载体化,
--     exists artifacts(content_hash, kind='chunk') 由此结构性可满足。
--     全部消费点(CHECK/ingest/rebuild/gate)只经本函数(哈希同源)。 ===
CREATE FUNCTION v13_body_hash(p_body text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(digest(to_jsonb(p_body)::text, 'sha256'), 'hex')
$$;

-- === T0 分析器(§7):to_tsvector 非 immutable(regconfig 可变),生成列
--     要求 immutable 表达式——显式 cast 钉死配置的包装函数是标准载体。
--     analyzer_version='tsv_english_1' 与此函数一一对应(策略行携带)。 ===
CREATE FUNCTION v13_tsv_en(p_body text) RETURNS tsvector
LANGUAGE sql IMMUTABLE AS $$
  SELECT to_tsvector('english'::regconfig, p_body)
$$;

-- === 引用谓词原语(F3②):被任何 manifest 候选或 decision 引用的
--     chunk hash 不可删。一条 SQL(manifest 面 + decisions 面);
--     decisions 面 = DP6 路径冻结契约(§1.4 DP6 行①):现在检查,
--     生产者落地即自动纳入——保守超集,DP4 时代恒 false 零成本。 ===
CREATE FUNCTION v13_chunk_referenced(p_hash text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM artifacts a
                  WHERE a.kind = 'context'
                    AND a.inline->'query_side'->'candidates'
                        @> jsonb_build_array(
                             jsonb_build_object('content_hash', p_hash)))
      OR EXISTS (SELECT 1 FROM decisions d
                  WHERE d.context->'chunk'->>'content_hash' = p_hash)
$$;
-- 引用检查的索引背书:manifest 候选数组的表达式 GIN(部分索引,kind='context')
CREATE INDEX ix_artifacts_candidates ON artifacts
  USING gin (((inline->'query_side'->'candidates')) jsonb_path_ops)
  WHERE kind = 'context';

-- === 锁协议原语(§3.1bis,L4 并发修正:保留检查/删除的 TOCTOU 与
--     并发撞键闭合)。两命名空间:20260920=content_hash 类(引用/删除
--     协调——写入端与删除端同锁);20260921=source_hash 类(ingest/
--     rebuild/gc 写写互斥,防 (source_hash,chunk_no) 撞键)。hashtextextended
--     双参独立键空间,与 DP1–3 行锁/探针无共享;升序取锁(防死锁)。
--     删除端协议序:source 升序 → 该源 hash 升序 → 先锁后查后删;
--     写入端:单引用集升序(advisory xact 锁随事务释放)。 ===
CREATE FUNCTION v13_adv_xact_locks(p_keys jsonb, p_ns bigint)
RETURNS void LANGUAGE plpgsql VOLATILE AS $$
DECLARE k text;
BEGIN
  IF jsonb_typeof(p_keys) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: lock keys must be a jsonb text array'
      USING ERRCODE = 'V3004';
  END IF;
  FOR k IN SELECT DISTINCT x FROM jsonb_array_elements_text(p_keys) AS x
            ORDER BY 1 LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended(k, p_ns));
  END LOOP;
END $$;

-- 写入端 ①:artifacts 落 context 候选 → 先取候选 hash 锁(与删除端同锁同序;
--     WHEN 谓词便非 context 插入零成本;与 DP3 既有 artifacts 触发器共存,
--     按名字序都在 AFTER 语义前互不干扰)
CREATE FUNCTION v13_artifacts_ref_lock() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE h text;
BEGIN
  FOR h IN SELECT DISTINCT cand->>'content_hash'
             FROM jsonb_array_elements(
                  coalesce(NEW.inline->'query_side'->'candidates',
                           '[]'::jsonb)) cand
            ORDER BY 1 LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended(h, 20260920));
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_artifacts_chunk_ref_lock
  BEFORE INSERT ON artifacts FOR EACH ROW
  WHEN (NEW.kind = 'context')
  EXECUTE FUNCTION v13_artifacts_ref_lock();

-- 写入端 ②:decisions 落 chunk 引用 → 同锁(DP6 路径冻结 §1.4;
--     DP4 时代恒 NULL 零成本;INSERT/UPDATE 双半边——γ' 回填亦覆盖)
CREATE FUNCTION v13_decisions_ref_lock() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE h text;
BEGIN
  h := NEW.context->'chunk'->>'content_hash';
  IF h IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock(hashtextextended(h, 20260920));
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_decisions_chunk_ref_lock
  BEFORE INSERT OR UPDATE ON decisions FOR EACH ROW
  WHEN (NEW.context->'chunk' IS NOT NULL)
  EXECUTE FUNCTION v13_decisions_ref_lock();

-- === 源台账(OQ4):语料归属与源→artifact 锚的唯一住所(corpus 不存在
--     于其他任何地方,非第二真相源)。append-only,单一豁口=superseded_by
--     lineage 标记(L4 P1-1,见列注);corpus 冲突由摄取函数 fail-closed
--     (其余 UPDATE 被 trigger 拒,改归属=重摄取新版本)。 ===
CREATE TABLE v13_sources (
  source_hash   text PRIMARY KEY,         -- = v13_body_hash(源文档全文)
  corpus        text NOT NULL,
  artifact_id   uuid NOT NULL REFERENCES artifacts (artifact_id),
  ingested_at   timestamptz NOT NULL DEFAULT now(),
  superseded_by text DEFAULT NULL         -- lineage 标记(L4 P1-1):supersede 时
                                           -- 由 ingest 同事务指向新 source_hash;
                                           -- 退役源不进 rebuild/GC(delete)/召回面;
                                           -- 不进任何哈希/键(附 B 哈希同源行)
);

CREATE FUNCTION v13_sources_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'v13: v13_sources is append-only (DELETE on %)',
      TG_TABLE_NAME USING ERRCODE = 'V3004';
  END IF;
  -- 单一豁口(L4 P1-1):仅「superseded_by NULL→值、其余列 IS NOT DISTINCT
  -- FROM OLD」放行(三值安全:null 键照常拒);lineage 只增不改不回收
  IF NEW.superseded_by IS NULL
     OR OLD.superseded_by IS NOT NULL
     OR NEW.source_hash IS DISTINCT FROM OLD.source_hash
     OR NEW.corpus      IS DISTINCT FROM OLD.corpus
     OR NEW.artifact_id IS DISTINCT FROM OLD.artifact_id
     OR NEW.ingested_at IS DISTINCT FROM OLD.ingested_at THEN
    RAISE EXCEPTION
      'v13: v13_sources is append-only (only superseded_by NULL->value)'
      USING ERRCODE = 'V3004';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_v13_sources_append_only
  BEFORE UPDATE OR DELETE ON v13_sources
  FOR EACH ROW EXECUTE FUNCTION v13_sources_append_only();

-- === 语料代数(OQ3):单行单调计数器,语句级触发器 bump——任何路径的
--     chunks DML(函数/psql/COPY)都漏不掉;指纹被弃(token 在 advance
--     会话锁内,单行读 vs 全表扫)。UPDATE 不进 bump 面:行不可变,该
--     语句不存在;TRUNCATE 被 belt 拒。 ===
CREATE TABLE v13_chunks_meta (
  singleton   boolean PRIMARY KEY CHECK (singleton),
  generation  bigint NOT NULL DEFAULT 0 CHECK (generation >= 0)
);
INSERT INTO v13_chunks_meta (singleton, generation) VALUES (true, 0);

-- 单调性守卫:代数只增不重置、行不可删(手工调低=token 静默回放旧语料面,
-- 封死);bump 触发器的 +1 UPDATE 天然过门
CREATE FUNCTION v13_chunks_meta_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'v13: v13_chunks_meta row cannot be deleted'
      USING ERRCODE = 'V3004';
  END IF;
  IF NEW.singleton IS DISTINCT FROM true
     OR NEW.generation IS NULL
     OR NEW.generation < OLD.generation THEN
    RAISE EXCEPTION 'v13: chunks generation is monotonic (no reset/lowering)'
      USING ERRCODE = 'V3004';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_v13_chunks_meta_guard
  BEFORE UPDATE OR DELETE ON v13_chunks_meta
  FOR EACH ROW EXECUTE FUNCTION v13_chunks_meta_guard();

-- === chunks 投影(§9 七列原样 + F3① chunk_offset + §7 T0 body_tsv)。
--     主键 (source_hash, chunk_no) 按设计 §4.2 冻结保留;行自证 CHECK
--     (纪律①结构性化);FK→v13_sources(源台账先行)。 ===
CREATE TABLE chunks (
  source_hash      text NOT NULL,
  chunk_no         int  NOT NULL CHECK (chunk_no >= 0),
  body             text NOT NULL,
  content_hash     text NOT NULL,          -- 行自证(经 v13_body_hash)
  chunk_offset     bigint NOT NULL DEFAULT 0
                   CHECK (chunk_offset >= 0),   -- F3①:doc 内字节基偏移
  corpus           text NOT NULL,
  chunker_version  text NOT NULL,
  analyzer_version text NOT NULL,
  body_tsv tsvector GENERATED ALWAYS AS (v13_tsv_en(body)) STORED,
                                            -- §7 T0 起步(生成列吃 IMMUTABLE
                                            -- 包装;stannum 换 definition 归 DP5)
  PRIMARY KEY (source_hash, chunk_no),
  FOREIGN KEY (source_hash) REFERENCES v13_sources (source_hash),
  CONSTRAINT v13_chunks_hash_selfcheck
    CHECK (content_hash = v13_body_hash(body))
);
CREATE INDEX ix_chunks_corpus ON chunks (corpus);       -- rebuild/GC 分域扫
CREATE INDEX ix_chunks_tsv ON chunks USING gin (body_tsv);  -- T0 检索

-- === 守卫触发器族(OQ5:受控写入的四道门) ===

-- 门① 行不可变:修正投影 = 重摄取/rebuild,无 UPDATE 语义
CREATE FUNCTION v13_chunks_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: chunks rows are immutable (% on % %/%)',
    TG_OP, TG_TABLE_NAME, OLD.source_hash, OLD.chunk_no
    USING ERRCODE = 'V3004';
END $$;
CREATE TRIGGER trg_chunks_immutable
  BEFORE UPDATE ON chunks FOR EACH ROW
  EXECUTE FUNCTION v13_chunks_immutable();

-- 门② artifact 存在(纪律①的 exists 半边,结构性):切片体必须以
--     kind='chunk' artifact 在场(真相源;artifacts 侧另有 produced_by
--     →succeeded 守卫与 append-only,DP3 已落)
CREATE FUNCTION v13_chunks_artifact_exists() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM artifacts a
                  WHERE a.content_hash = NEW.content_hash
                    AND a.kind = 'chunk') THEN
    RAISE EXCEPTION
      'v13: chunk %/% has no kind=''chunk'' artifact for %',
      NEW.source_hash, NEW.chunk_no, NEW.content_hash
      USING ERRCODE = 'V3004';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_chunks_artifact_exists
  BEFORE INSERT ON chunks FOR EACH ROW
  EXECUTE FUNCTION v13_chunks_artifact_exists();

-- 门③ retention(F3②):被引用行不可删——引用检查一条 SQL(v13_chunk_referenced);
--     合法删除(rebuild/摄取/未来 GC)以 NOT referenced 预过滤,本触发器是 belt
CREATE FUNCTION v13_chunks_retention() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF v13_chunk_referenced(OLD.content_hash) THEN
    RAISE EXCEPTION
      'v13: chunk %/% is referenced (manifest/decision) and retained (F3)',
      OLD.source_hash, OLD.chunk_no
      USING ERRCODE = 'V3004';
  END IF;
  RETURN OLD;
END $$;
CREATE TRIGGER trg_chunks_retention
  BEFORE DELETE ON chunks FOR EACH ROW
  EXECUTE FUNCTION v13_chunks_retention();

-- 门④ 代数 bump(OQ3):语句级,一行 hot row(摄取是离线/worker 面,
--     不与 events/advance 路径交叠——p99 gate H 断言无回退)
CREATE FUNCTION v13_chunks_generation_bump() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE v13_chunks_meta SET generation = generation + 1 WHERE singleton;
  RETURN NULL;
END $$;
CREATE TRIGGER trg_chunks_generation_bump
  AFTER INSERT OR DELETE ON chunks FOR EACH STATEMENT
  EXECUTE FUNCTION v13_chunks_generation_bump();

-- 门⑤ TRUNCATE 旁路封死:TRUNCATE 不触发行级 DELETE——保护式重灌(OQ2)
--     之外不存在任何 truncate 形态
CREATE FUNCTION v13_chunks_no_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: TRUNCATE chunks is forbidden; use v13_rebuild_chunks()'
    USING ERRCODE = 'V3004';
END $$;
CREATE TRIGGER trg_chunks_no_truncate
  BEFORE TRUNCATE ON chunks FOR EACH STATEMENT
  EXECUTE FUNCTION v13_chunks_no_truncate();
```

### 3.2 策略行种子(v13_policies 载体,DP1 契约 #3)

```sql
-- 单完整 JSON 字面量 + ::jsonb(类型算子层教训;全文件唯一 jsonb 字面量族)
INSERT INTO v13_policies (name, version, value, active) VALUES
('chunks_ingest', 1, $j${"chunker_version":"para_v1","analyzer_version":"tsv_english_1","mode":"para","target_bytes":3072,"max_chunk_bytes":1048576,"max_doc_bytes":1048576}$j$::jsonb, true),
('span_assembly', 1, $j${"mode":"span","context_bytes":256,"merge_gap_bytes":64,"boundary":"sentence","fence_aware":true,"table_aware":true}$j$::jsonb, true),
('chunk_gc',      1, $j${"mode":"dry-run-only"}$j$::jsonb, true);
-- 策略形状在消费点 fail-closed 校验(ingest/rebuild/chunker/span_unit 入口;
--     OQ6/G8 负向),不另建校验器函数(与 DP3 judgment_defaults 不同:无嵌套 schema 面)。
-- 校验式三律(L4 修正):词表判断一律 (x IN (…)) IS NOT TRUE 拒收(三值逻辑
-- 封死——缺 mode/NULL 不再静默放行);数值键分步类型先验(jsonb_typeof=
-- 'number' 先行、后转数值——杜绝 'abc'::bigint 22P02 先于守卫;分步 IF
-- 保证求值序);未知 chunker/analyzer 版本拒收(封闭词表强制)。
-- target_bytes=3072 = §4.7 先验 2–4KB 中值;数据答案归 DP5 刻画 gate。
-- chunker_version/analyzer_version 词表封闭:{para_v1|whole_v1}×{tsv_english_1};
-- boundary 词表 {none|line|sentence}——新版本=新策略行(版本化追加),
-- 旧行留在投影上作 provenance;词表在 ingest/rebuild 入口强制(G8 负向)。
```

### 3.3 chunker + 投影落地 + 摄取(OQ4/OQ7)

```sql
-- === chunker(确定性纯函数;§4.7 尺寸解耦的切片半边):
--     whole_v1=整文档一 chunk(粗上限);para_v1=段落边界聚簇到 target_bytes,
--     ``` 栅栏不劈(fence_aware)、超 max_chunk_bytes 的单段拒(fail-closed,
--     台账:硬劈)。字节偏移(octet_length 口径,F3①);段数上限 4096。 ===
CREATE FUNCTION v13_chunker_slice(p_body text, p_policy jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_mode  text   := p_policy->>'mode';
  v_tgt   bigint;              -- 体内赋值:分步类型先验后转型(DECLARE
  v_max   bigint;              -- 默认值转型会在守卫前抛 22P02,自检修正)
  v_paras text[];
  v_out   jsonb := '[]'::jsonb;
  v_cur   text := '';           -- 累积中的段体
  v_start bigint := 0;          -- v_cur 在 doc 内的字节起点
  v_abs   bigint := 0;          -- 下一待处理段的字节起点
  v_no    int := 0;
  v_fence boolean := false;     -- ``` 栅栏开闭状态(跨段延续)
  v_p text; v_fences int; v_len bigint;
BEGIN
  IF (v_mode IN ('whole','para')) IS NOT TRUE
     OR jsonb_typeof(p_policy->'target_bytes') IS DISTINCT FROM 'number'
     OR jsonb_typeof(p_policy->'max_chunk_bytes') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid chunks_ingest policy shape'
      USING ERRCODE = 'V3004';
  END IF;
  v_tgt := (p_policy->>'target_bytes')::bigint;
  v_max := (p_policy->>'max_chunk_bytes')::bigint;
  IF v_tgt <= 0 OR v_max <= 0 OR v_tgt > v_max THEN
    RAISE EXCEPTION 'v13: invalid chunks_ingest policy shape'
      USING ERRCODE = 'V3004';
  END IF;
  IF v_mode = 'whole' THEN
    IF octet_length(p_body) > v_max THEN
      RAISE EXCEPTION 'v13: doc exceeds max_chunk_bytes (%)',
        octet_length(p_body) USING ERRCODE = 'V3004';
    END IF;
    RETURN jsonb_build_array(jsonb_build_object(
      'chunk_no', 0, 'body', p_body, 'chunk_offset', 0));
  END IF;
  IF p_body = '' THEN
    RAISE EXCEPTION 'v13: empty document rejected (para mode)'
      USING ERRCODE = 'V3004';
  END IF;
  v_paras := string_to_array(p_body, E'\n\n');
  IF coalesce(array_length(v_paras, 1), 0) > 4096 THEN
    RAISE EXCEPTION 'v13: doc exceeds paragraph cap (4096)'
      USING ERRCODE = 'V3004';
  END IF;
  FOR v_p IN SELECT unnest(v_paras) LOOP
    v_len := octet_length(v_p);
    v_fences := (length(v_p) - length(replace(v_p, '```', ''))) / 3; -- 字符口径
                                              -- 计 ``` 出现次数(字符/字节两口径等价:
                                              -- 每次出现恒 3 字符=3 字节;与字节偏移无关)
    IF v_cur = '' THEN
      v_start := v_abs; v_cur := v_p;           -- 开新段
    ELSIF NOT v_fence
          AND octet_length(v_cur) + 2 + v_len > v_tgt THEN
      -- 栅栏闭合且并入超 target:先落当前段再开新段(顺序保持)
      IF v_len > v_max THEN
        RAISE EXCEPTION
          'v13: paragraph exceeds max_chunk_bytes — hard split is YAGNI'
          USING ERRCODE = 'V3004';
      END IF;
      IF octet_length(v_cur) > v_max THEN      -- 单段开新落后未经 ELSE 门,
        RAISE EXCEPTION                       -- 此处补 flush 点上限(尾段同)
          'v13: paragraph exceeds max_chunk_bytes — hard split is YAGNI'
          USING ERRCODE = 'V3004';
      END IF;
      v_out := v_out || jsonb_build_array(jsonb_build_object(
                 'chunk_no', v_no, 'body', v_cur, 'chunk_offset', v_start));
      v_no := v_no + 1;
      v_start := v_abs; v_cur := v_p;
    ELSE
      IF octet_length(v_cur) + 2 + v_len > v_max THEN
        RAISE EXCEPTION
          'v13: paragraph cluster (fenced) exceeds max_chunk_bytes — hard split is YAGNI'
          USING ERRCODE = 'V3004';
      END IF;
      v_cur := v_cur || E'\n\n' || v_p;        -- 栅栏开启强制聚簇
    END IF;
    v_abs := v_abs + v_len + 2;                -- 分隔符 E'\n\n' 恒 2 字节
    v_fence := v_fence <> (v_fences % 2 = 1); -- 布尔不等式(PG 无布尔异或运算符,
                                              -- <> 于 boolean 合法;L4 P0 修正):
                                              -- 段内 ``` 奇数次→翻转
  END LOOP;
  IF v_cur <> '' THEN
    IF octet_length(v_cur) > v_max THEN        -- 尾段落段的上限门(同上)
      RAISE EXCEPTION
        'v13: paragraph exceeds max_chunk_bytes — hard split is YAGNI'
        USING ERRCODE = 'V3004';
    END IF;
    v_out := v_out || jsonb_build_array(jsonb_build_object(
               'chunk_no', v_no, 'body', v_cur, 'chunk_offset', v_start));
  END IF;
  RETURN v_out;
END $$;
-- 纯确定性(零时钟零随机);字节口径一律 octet_length;栅栏判定与 v13_span_unit
-- 的行级状态机同判据(``` 奇数次翻转);上限门覆盖全部三个落段点(开新/聚簇/尾);
-- offset 正确性:v_abs 在循环体末尾才推进——ELSIF 分支内 v_abs=当前段起点,
-- flush 用旧 v_start(累积体真实起点)、新 v_start:=v_abs(新段起点),两者皆准。

-- === 投影落地(ingest 与 rebuild 共用):切片 artifact(内容寻址去重,
--     produced_by=源 artifact 的 effect——重投影同源溯源)+ 投影行。 ===
CREATE FUNCTION v13_project_source(
  p_source_hash text, p_corpus text, p_body text,
  p_produced_by uuid, p_policy jsonb)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE
  v_slices jsonb; s jsonb; v_hash text; v_n int := 0;
  v_ck text := p_policy->>'chunker_version';
  v_ak text := p_policy->>'analyzer_version';
BEGIN
  v_slices := v13_chunker_slice(p_body, p_policy);
  FOR s IN SELECT * FROM jsonb_array_elements(v_slices) LOOP
    v_hash := v13_body_hash(s->>'body');
    IF NOT EXISTS (SELECT 1 FROM artifacts
                    WHERE content_hash = v_hash AND kind = 'chunk') THEN
      INSERT INTO artifacts (content_hash, kind, inline, size, produced_by)
      VALUES (v_hash, 'chunk', to_jsonb(s->>'body'),
              octet_length(to_jsonb(s->>'body')::text), p_produced_by);
    END IF;
    INSERT INTO chunks (source_hash, chunk_no, body, content_hash,
                        chunk_offset, corpus, chunker_version, analyzer_version)
    VALUES (p_source_hash, (s->>'chunk_no')::int, s->>'body', v_hash,
            (s->>'chunk_offset')::bigint, p_corpus, v_ck, v_ak);
    v_n := v_n + 1;
  END LOOP;
  RETURN v_n;
END $$;

-- === 摄取(纪律②的载体;OQ4/OQ7):单事务=源 artifact→台账→locked
--     分流→旧投影行死亡→切片+落行。驱动器契约见 README/§3.3 注;
--     body 由调用方事务外读取后传入(外部 IO 不进事务)。 ===
CREATE FUNCTION v13_ingest_document(
  p_produced_by uuid,          -- succeeded tool effect(ch7 生产纪律)
  p_corpus      text,
  p_body        text,
  p_supersedes  text DEFAULT NULL)   -- 同逻辑源旧版本(旧 source_hash)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_policy jsonb := v13_policy('chunks_ingest');
  v_src text; v_doc jsonb; v_sz bigint; v_aid uuid;
  v_kind text; v_status text;
  v_locked boolean; v_exist jsonb; v_new jsonb := '[]'::jsonb; s jsonb;
  v_gen bigint; v_count int;
BEGIN
  -- 策略形状 fail-closed(三律:词表 IS NOT TRUE 拒收/类型先验后转数值/
  --     封闭词表含 chunker·analyzer 版本;mode↔chunker_version 配对;空文档拒)
  IF v_policy IS NULL OR p_corpus IS NULL OR p_corpus = '' OR p_body IS NULL
     OR octet_length(p_body) = 0
     OR jsonb_typeof(v_policy->'mode') IS DISTINCT FROM 'string'
     OR (v_policy->>'mode' IN ('whole','para')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'chunker_version') IS DISTINCT FROM 'string'
     OR (v_policy->>'chunker_version' IN ('para_v1','whole_v1')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'analyzer_version') IS DISTINCT FROM 'string'
     OR (v_policy->>'analyzer_version' IN ('tsv_english_1')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'max_doc_bytes') IS DISTINCT FROM 'number'
     OR left(v_policy->>'chunker_version',
             length(v_policy->>'mode')) IS DISTINCT FROM v_policy->>'mode' THEN
    RAISE EXCEPTION 'v13: invalid chunks_ingest policy, corpus, or empty body'
      USING ERRCODE = 'V3004';
  END IF;
  -- 溯源 effect:kind='tool' 且 status='succeeded'(artifacts 触发器是 belt)
  SELECT kind, status INTO v_kind, v_status
    FROM effects WHERE effect_id = p_produced_by;
  IF v_kind IS DISTINCT FROM 'tool' OR v_status IS DISTINCT FROM 'succeeded' THEN
    RAISE EXCEPTION 'v13: ingest requires a succeeded tool effect (%)',
      p_produced_by USING ERRCODE = 'V3004';
  END IF;
  -- 尺寸门(v1 chunk artifact 一律 inline;ref 路径入台账)
  v_doc := to_jsonb(p_body); v_sz := octet_length(v_doc::text);
  IF v_sz > (v_policy->>'max_doc_bytes')::bigint THEN
    RAISE EXCEPTION 'v13: doc exceeds max_doc_bytes (%)', v_sz
      USING ERRCODE = 'V3004';
  END IF;
  v_src := v13_body_hash(p_body);
  -- 源 artifact(内容寻址去重=上层选择,ch7 7.4:摄取即选择去重)
  SELECT artifact_id INTO v_aid FROM artifacts
   WHERE content_hash = v_src AND kind = 'chunk' LIMIT 1;
  IF v_aid IS NULL THEN
    INSERT INTO artifacts (content_hash, kind, inline, size, produced_by)
    VALUES (v_src, 'chunk', v_doc, v_sz, p_produced_by)
    RETURNING artifact_id INTO v_aid;
  END IF;
  -- 源台账(corpus 冲突 fail-closed)
  INSERT INTO v13_sources (source_hash, corpus, artifact_id)
  VALUES (v_src, p_corpus, v_aid)
  ON CONFLICT (source_hash) DO NOTHING;
  IF EXISTS (SELECT 1 FROM v13_sources
              WHERE source_hash = v_src AND corpus IS DISTINCT FROM p_corpus) THEN
    RAISE EXCEPTION 'v13: source % already bound to another corpus', v_src
      USING ERRCODE = 'V3004';
  END IF;
  -- 锁协议(不变量 9;TOCTOU 闭合):先 source 类(写写互斥/防撞键)后
  -- hash 类(引用/删除协调),均升序;hash 锁只随 source 锁之后取得 →
  -- 全树无环(§3.1bis 论证)。先锁 → 后检查 → 后删。
  PERFORM v13_adv_xact_locks(
    (SELECT coalesce(jsonb_agg(DISTINCT s ORDER BY s), '[]'::jsonb)
       FROM unnest(ARRAY[v_src, coalesce(p_supersedes, v_src)]) AS s), 20260921);
  PERFORM v13_adv_xact_locks(
    (SELECT coalesce(jsonb_agg(DISTINCT content_hash ORDER BY content_hash),
                     '[]'::jsonb)
       FROM chunks WHERE source_hash IN (v_src, p_supersedes)), 20260920);
  -- retention 锁分流(OQ2):被引用源只允许幂等重摄取
  v_locked := EXISTS (SELECT 1 FROM chunks
                       WHERE source_hash = v_src
                         AND v13_chunk_referenced(content_hash));
  IF v_locked THEN
    SELECT coalesce(jsonb_agg(jsonb_build_object('chunk_no', chunk_no,
                            'content_hash', content_hash)
                              ORDER BY chunk_no), '[]'::jsonb)
      INTO v_exist FROM chunks WHERE source_hash = v_src;
    FOR s IN SELECT * FROM jsonb_array_elements(v13_chunker_slice(p_body, v_policy)) LOOP
      v_new := v_new || jsonb_build_object('chunk_no', (s->>'chunk_no')::int,
                   'content_hash', v13_body_hash(s->>'body'));
    END LOOP;
    IF v_exist IS DISTINCT FROM v_new THEN
      RAISE EXCEPTION
        'v13: source % is retention-locked (F3) and new slicing differs',
        v_src USING ERRCODE = 'V3004';
    END IF;
    SELECT generation INTO v_gen FROM v13_chunks_meta WHERE singleton;
    RETURN jsonb_build_object('source_hash', v_src, 'artifact_id', v_aid,
      'chunk_count', jsonb_array_length(v_new), 'locked', true,
      'unchanged', true, 'generation', v_gen);
  END IF;
  -- 纪律②:旧投影行死亡+新行落账,同一事务(delete 面全无引用——门③ belt 双检)
  DELETE FROM chunks WHERE source_hash = v_src;
  IF p_supersedes IS NOT NULL AND p_supersedes <> v_src THEN
    DELETE FROM chunks WHERE source_hash = p_supersedes
      AND NOT v13_chunk_referenced(content_hash);  -- 被引用旧版本行存活(F3)
    UPDATE v13_sources SET superseded_by = v_src   -- 台账退役标记(L4 P1-1):与
     WHERE source_hash = p_supersedes              -- 旧行死亡同事务;不标记则下次
       AND superseded_by IS NULL;                  -- rebuild 重投影=复活旧版本
  END IF;
  v_count := v13_project_source(v_src, p_corpus, p_body, p_produced_by, v_policy);
  SELECT generation INTO v_gen FROM v13_chunks_meta WHERE singleton;
  RETURN jsonb_build_object('source_hash', v_src, 'artifact_id', v_aid,
    'chunk_count', v_count, 'locked', false, 'unchanged', false,
    'generation', v_gen);
END $$;
```

### 3.4 rebuild + GC + verify(OQ2/OQ7)

```sql
-- === 保护式重灌(OQ2;F3② 取代字面 truncate,附 A #2):逐源——
--     被引用→locked 跳过;无引用→删行+按活动策略重投影。
--     幂等:同策略两次跑,chunks 表内容字节级一致(gate E1;
--     generation 照常 bump——事件计数非表内容)。 ===
CREATE FUNCTION v13_rebuild_chunks(p_corpus text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_policy jsonb := v13_policy('chunks_ingest');
  r record; v_locked boolean; v_produced_by uuid;
  v_total int := 0; v_reprojected int := 0; v_locked_n int := 0;
  v_rows int := 0; v_n int;
BEGIN
  IF v_policy IS NULL
     OR jsonb_typeof(v_policy->'mode') IS DISTINCT FROM 'string'
     OR (v_policy->>'mode' IN ('whole','para')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'chunker_version') IS DISTINCT FROM 'string'
     OR (v_policy->>'chunker_version' IN ('para_v1','whole_v1')) IS NOT TRUE
     OR jsonb_typeof(v_policy->'analyzer_version') IS DISTINCT FROM 'string'
     OR (v_policy->>'analyzer_version' IN ('tsv_english_1')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: invalid chunks_ingest policy shape'
      USING ERRCODE = 'V3004';
  END IF;
  FOR r IN SELECT src.source_hash, src.corpus, (a.inline #>> '{}') AS body,
                  a.produced_by
             FROM v13_sources src
             JOIN artifacts a ON a.artifact_id = src.artifact_id
            WHERE src.superseded_by IS NULL         -- 退役源不重投影(L4 P1-1:
              AND (p_corpus IS NULL OR src.corpus = p_corpus)
                                                   -- supersede 后旧源零行,跳过
            ORDER BY src.source_hash                -- 即零复活;锁协议序不变)
  LOOP
    v_total := v_total + 1;
    -- 锁协议(不变量 9,同 ingest):source 锁 → 该源 hash 锁 → 先锁后查后删;
    -- 逐源升序迭代 + 事务内累积持有 = 复合序(hash 锁只随其 source 锁之后
    -- 取得,全树无环,§3.1bis 论证)
    PERFORM v13_adv_xact_locks(jsonb_build_array(r.source_hash), 20260921);
    PERFORM v13_adv_xact_locks(
      (SELECT coalesce(jsonb_agg(DISTINCT content_hash ORDER BY content_hash),
                       '[]'::jsonb)
         FROM chunks WHERE source_hash = r.source_hash), 20260920);
    v_locked := EXISTS (SELECT 1 FROM chunks
                         WHERE source_hash = r.source_hash
                           AND v13_chunk_referenced(content_hash));
    IF v_locked THEN
      v_locked_n := v_locked_n + 1; CONTINUE;      -- OQ2 锁:证据冻结投影
    END IF;
    DELETE FROM chunks WHERE source_hash = r.source_hash;
    v_n := v13_project_source(r.source_hash, r.corpus, r.body,
                              r.produced_by, v_policy);
    v_reprojected := v_reprojected + 1; v_rows := v_rows + v_n;
  END LOOP;
  RETURN jsonb_build_object('sources', v_total, 'reprojected', v_reprojected,
    'locked', v_locked_n, 'rows_inserted', v_rows,
    'chunker_version', v_policy->>'chunker_version');
END $$;

-- === GC(策略门关闭的执行器):「被引用即保留,GC 只清无引用行」
--     (F3②)的删除半边——v1 策略 mode='dry-run-only',只报告可删面
--     (按 corpus 分组);窗口化 GC 触发=扫描恢复成本实测超标(§12,
--     与 DP3 blob 侧同族)。合法删除路径的预过滤=NOT v13_chunk_referenced,
--     门③ belt 双检。 ===
CREATE FUNCTION v13_chunk_gc(p_dry_run boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_mode text := v13_policy('chunk_gc')->>'mode'; v_n bigint; r2 record;
        v_rc bigint;
BEGIN
  IF jsonb_typeof(v13_policy('chunk_gc')->'mode') IS DISTINCT FROM 'string'
     OR (v_mode IN ('dry-run-only','delete-unreferenced')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: invalid chunk_gc policy mode' USING ERRCODE = 'V3004';
  END IF;
  IF p_dry_run OR v_mode = 'dry-run-only' THEN
    RETURN jsonb_build_object('mode', 'dry-run', 'deletable_by_corpus',
      (SELECT coalesce(jsonb_object_agg(corpus, n), '{}'::jsonb)
         FROM (SELECT corpus, count(*) n FROM chunks c
                WHERE NOT v13_chunk_referenced(c.content_hash)
                GROUP BY corpus) x));
  END IF;
  -- 锁协议(不变量 9;delete 模式离线批量,逐 source 升序同 rebuild;
  --     dry-run 零锁零成本)
  v_n := 0;
  FOR r2 IN SELECT DISTINCT c.source_hash FROM chunks c
             JOIN v13_sources s ON s.source_hash = c.source_hash
            WHERE s.superseded_by IS NULL           -- 退役源残留行(被引用存活)
            ORDER BY c.source_hash LOOP             -- 不进删除面(L4 P1-1)
    PERFORM v13_adv_xact_locks(jsonb_build_array(r2.source_hash), 20260921);
    PERFORM v13_adv_xact_locks(
      (SELECT coalesce(jsonb_agg(DISTINCT content_hash ORDER BY content_hash),
                       '[]'::jsonb)
         FROM chunks WHERE source_hash = r2.source_hash), 20260920);
    DELETE FROM chunks c WHERE c.source_hash = r2.source_hash
      AND NOT v13_chunk_referenced(c.content_hash);
    GET DIAGNOSTICS v_rc = ROW_COUNT;
    v_n := v_n + v_rc;
  END LOOP;
  RETURN jsonb_build_object('mode', 'deleted', 'deleted_rows', v_n);
END $$;

-- === 夜间扫地僧校验器(OQ7):T0 载体七项;DP5 升 v2 增第八项 verify_index。
--     p_raise=true 时任一红即 V3004(ops 可见;pg_cron job 用此形态)。 ===
CREATE FUNCTION v13_verify_chunks(p_raise boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
-- VOLATILE 声明:⑤b 冲洗 gin pending list 是有状态副作用(gin_clean_pending_list
-- 本身 VOLATILE)——STABLE 承诺「扫描内不改库状态」不诚实;校验器每次调用
-- 整体执行一次,无内联/重排风险面
DECLARE
  v_bad_selfcert bigint; v_bad_orphan bigint; v_bad_source bigint;
  v_bad_ref bigint; v_plan text := ''; v_pending int; v_meta boolean;
  v_bad_backref bigint; v_orphan bigint; v_guc text;
  v_checks jsonb := '[]'::jsonb; v_all_ok boolean;
  v_line record;
BEGIN
  SELECT count(*) INTO v_bad_selfcert FROM chunks
   WHERE content_hash IS DISTINCT FROM v13_body_hash(body);        -- ①自证
  SELECT count(*) INTO v_bad_orphan FROM chunks c
   WHERE NOT EXISTS (SELECT 1 FROM artifacts a
                      WHERE a.content_hash = c.content_hash
                        AND a.kind = 'chunk');                       -- ②孤儿
  SELECT count(*) INTO v_bad_source FROM chunks c
   WHERE NOT EXISTS (SELECT 1 FROM v13_sources s
                      WHERE s.source_hash = c.source_hash);         -- ③源台账
  SELECT count(*) INTO v_bad_ref FROM artifacts a
   CROSS JOIN LATERAL jsonb_array_elements(
        coalesce(a.inline->'query_side'->'candidates', '[]'::jsonb)) cand
   WHERE a.kind = 'context'
     AND EXISTS (SELECT 1 FROM artifacts x           -- kind='chunk' 身份筛:
                  WHERE x.content_hash = cand->>'content_hash' -- 仅 chunk 身份的候选
                    AND x.kind = 'chunk')            -- 参与对账(DP3 goal echo
     AND NOT EXISTS (SELECT 1 FROM chunks c          -- 候选非 chunk 身份,不计
                      WHERE c.content_hash            -- ——否则恒误报,L4 修正)
                             = cand->>'content_hash');          -- ④引用可回取+投影行在场(F3)
  SELECT count(*) INTO v_bad_backref FROM artifacts a
   WHERE a.kind = 'chunk'
     AND NOT EXISTS (SELECT 1 FROM chunks c
                      WHERE c.content_hash = a.content_hash)
     AND v13_chunk_referenced(a.content_hash);       -- ⑦对账反向半边:被引用的
                                                    -- chunk artifact 必有投影行
  SELECT count(*) INTO v_orphan FROM artifacts a
   WHERE a.kind = 'chunk'
     AND NOT EXISTS (SELECT 1 FROM chunks c
                      WHERE c.content_hash = a.content_hash);
                                                    -- ⑦ report-only:无引用孤儿
                                                    -- = supersede 合法残留
                                                    -- (artifacts append-only,
                                                    -- 不入 ok 判据)
  -- ⑤GIN 形状:非停用词 canary('quasar'——'the' 是 english 停用词,会被剥
  --     成空 tsquery,首写已修,L4 修正);索引强制写死一种:会话局部
  --     enable_seqscan=off + 事后恢复(小表合法 Seq Scan 是成本模型正确
  --     行为,不能证明 GIN 病变;大 fixture 方案弃——膨胀 gate 且仍计划器依赖)
  -- GUC 恢复兜底(L4 P2-4):EXPLAIN 中途异常 → 恢复 enable_seqscan 后原样
  --     重抛,不依赖引擎子事务 GUC 回滚细节;query_canceled 显式臂(DP1 α
  --     纪律:OTHERS 不捕 57014)
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
  v_pending := gin_clean_pending_list('public.ix_chunks_tsv'::regclass); -- ⑤b 冲洗
  SELECT EXISTS (SELECT 1 FROM v13_chunks_meta WHERE singleton)
    INTO v_meta;                                                    -- ⑥meta 行
  -- 组装 checks 数组(七项;detail 全数化——零文本拼接)并汇总 all_ok
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
                                   'orphan_artifacts_report', v_orphan)));
  v_all_ok := NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_checks) c
                           WHERE NOT (c->>'ok')::boolean);
  IF p_raise AND NOT v_all_ok THEN
    RAISE EXCEPTION 'v13: verify_chunks failed: %', v_checks
      USING ERRCODE = 'V3004';
  END IF;
  RETURN jsonb_build_object('version', 1, 'checks', v_checks,
                            'all_ok', v_all_ok);
END $$;
-- 注①:EXPLAIN 语句内字面量一律用双单引号转义(''english''/''quasar'')——
--     与函数体 $$ 定界零冲突(dollar-quote 嵌套是 42601 载荷面)。
-- 注②:FOR-IN-EXECUTE 拿 EXPLAIN 文本行——引擎行为实测面(附 B 冒烟清单)。
-- 注③:chunks 无 UPDATE 面,①③在结构性上恒 0——保留为 belt(重建/恢复演练)。
```

### 3.5 跨度生产者(§4.7/OQ6;DP3 spans 形态的生产者半边)

```sql
-- === T0 跨度提取:ASCII 折叠大小写不敏感精确子串扫描,字节偏移
--     (折叠只动 A-Z,字节长不变⇒任意非 ASCII 正文偏移精确;stem 不匹配
--     是 T0 诚实边界——DP5 换 stannum highlight 同 tokenizer,签名/形态不变)。
--     有界:词数>64/空词/词长>256 = RAISE(fail-closed);每词命中≤32、
--     总跨度≤256 = 确定性停止(上限非错误)。 ===
CREATE FUNCTION v13_extract_spans(p_body text, p_terms jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  t text; v_fold text; v_terms text[];
  v_char int; v_bstart int; v_bend int; v_hits jsonb := '[]'::jsonb;
  v_occ int; v_from int; v_total int := 0;
BEGIN
  IF p_body IS NULL THEN RETURN '[]'::jsonb; END IF;
  IF p_terms IS NULL OR jsonb_typeof(p_terms) IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_terms) > 64 THEN
    RAISE EXCEPTION 'v13: span terms must be an array of <=64 items'
      USING ERRCODE = 'V3004';               -- 词数门 fail-closed(非截断)
  END IF;
  SELECT coalesce(array_agg(x), '{}') INTO v_terms
    FROM jsonb_array_elements_text(p_terms) AS x;
  v_fold := translate(p_body, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                           'abcdefghijklmnopqrstuvwxyz'); -- ASCII 折叠,字节长不变
  FOREACH t IN ARRAY v_terms LOOP
    t := translate(t, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                      'abcdefghijklmnopqrstuvwxyz');
    IF length(t) = 0 OR length(t) > 256 THEN
      RAISE EXCEPTION 'v13: span term out of bounds' USING ERRCODE = 'V3004';
    END IF;
    v_occ := 0; v_from := 1;
    LOOP
      EXIT WHEN v_occ >= 32 OR v_total >= 256;   -- 命中上限=确定性停止(非错误)
      v_char := position(t in substring(v_fold from v_from));
      EXIT WHEN v_char = 0;
      v_char := v_char + v_from - 1;              -- 全文字符位
      v_bstart := octet_length(left(p_body, v_char - 1)) + 1;  -- 字节位(1 基)
      v_bend := v_bstart + octet_length(t) - 1;
      v_hits := v_hits || jsonb_build_array(jsonb_build_array(v_bstart, v_bend));
      v_total := v_total + 1; v_occ := v_occ + 1;
      v_from := v_char + length(t);
    END LOOP;
  END LOOP;
  -- 升序去重输出;重叠/邻近合并归 v13_assemble_spans 首步(merge_gap=0 即本层语义)
  RETURN (SELECT coalesce(jsonb_agg(span ORDER BY (span->>0)::int), '[]'::jsonb)
            FROM (SELECT DISTINCT span
                    FROM jsonb_array_elements(v_hits) AS span) d);
END $$;

-- === 装配单元落形助手(纯函数;确定性管线,L4 四配置语义修正;字节口径
--     一律 octet_length,行/句/块边界均字节位):
--     ①入界检查(核 [p_s,p_e] ⊆ [1,blen] 且 s≤e;extract 产物天然满足);
--     ②opts fail-closed:分步类型先验(语句序=求值序,杜绝 'abc'::bigint
--       先于守卫)→显式默认→词表 (x IN (…)) IS NOT TRUE 拒收;
--     ③一次行扫描收集块区间:fence 块(行含 ``` 奇数次→翻转;块=开栅栏
--       行首..闭栅栏行尾,未闭合→文尾)与表格段(行首字符 '|' 连续段,
--       段末行含其行尾 \n);行内成对围栏(```x```)不入块——行级配对
--       粒度,v1 记注(DP5 可升字符级);
--     ④核与块相交→扩到整块(**两遍扫描:fence 先于 table**——fence 闭合晚
--       于其内 table 段,构造序不保证外层优先;块内 '|' 行属代码块);
--     ⑤boundary 吸附(核不在块内):sentence=句首/句尾(终止符集
--       {.,!,?,。,!,?},其后随空白/\n/EOS 才构成句界;换行恒句界;
--       字符扫描,regexp_split_to_array 多字节安全);line=行首/行尾;
--       none=跳过;
--     ⑥前后文窗口:v_s-v_ctx / v_e+v_ctx(钳位;块单元跳过——块即
--       完整单元);
--     ⑦扩展不越块:窗口/吸附与核外块部分相交→钮到块边界外(整块含入
--       保留);
--     ⑧UTF-8 前向吸附:端点落多字节字符内部(续字节 0x80–0xBF)→逐
--       字节前进至前导字节(≤4 步;行/句/块界产物天然对齐,本步兜
--       窗口算术);
--     ⑨终界钳位;空区间丢弃(核恒存活——只钮扩展不钮核)。 ===
CREATE FUNCTION v13_span_unit(p_hash text, p_body text,
                              p_s bigint, p_e bigint, p_opts jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_blen  bigint := octet_length(p_body);
  v_s bigint := p_s; v_e bigint := p_e;
  v_ctx bigint; v_boundary text; v_fence boolean; v_table boolean;
  v_lines text[]; v_n int; v_i int; v_off bigint := 0; v_le bigint;
  v_fopen boolean := false; v_fs bigint := 0;
  v_topen boolean := false; v_ts bigint := 0;
  v_blocks jsonb := '[]'::jsonb;
  v_b jsonb; v_bs bigint; v_be bigint;
  v_in_block boolean := false;
  v_chars text[]; v_cn int; v_ci int; v_cb bigint; v_ch text; v_nxt text;
  v_cend bigint; v_start bigint := 1;
  v_s_done boolean := false;
  v_e_done boolean := false;
  v_bytes bytea;
BEGIN
  IF p_s < 1 OR p_e < p_s OR p_e > v_blen THEN
    RAISE EXCEPTION 'v13: span out of bounds' USING ERRCODE = 'V3004';
  END IF;
  -- ② opts fail-closed(分步:类型先验 → 默认 → 词表)
  IF p_opts ? 'context_bytes'
     AND jsonb_typeof(p_opts->'context_bytes') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid span opts (context_bytes)'
      USING ERRCODE = 'V3004';
  END IF;
  v_ctx := coalesce((p_opts->>'context_bytes')::bigint, 0);
  IF v_ctx < 0 THEN
    RAISE EXCEPTION 'v13: invalid span opts (context_bytes)'
      USING ERRCODE = 'V3004';
  END IF;
  IF p_opts ? 'boundary'
     AND jsonb_typeof(p_opts->'boundary') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: invalid span opts (boundary)'
      USING ERRCODE = 'V3004';
  END IF;
  v_boundary := coalesce(p_opts->>'boundary', 'none');
  IF (v_boundary IN ('none','line','sentence')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: invalid span opts (boundary)'
      USING ERRCODE = 'V3004';
  END IF;
  IF (p_opts ? 'fence_aware'
      AND jsonb_typeof(p_opts->'fence_aware') IS DISTINCT FROM 'boolean')
  OR (p_opts ? 'table_aware'
      AND jsonb_typeof(p_opts->'table_aware') IS DISTINCT FROM 'boolean') THEN
    RAISE EXCEPTION 'v13: invalid span opts (aware flags)'
      USING ERRCODE = 'V3004';
  END IF;
  v_fence := coalesce((p_opts->>'fence_aware')::boolean, false);
  v_table := coalesce((p_opts->>'table_aware')::boolean, false);

  -- ③ 行扫描:fence 块与表格段区间收集(构造序=行序=字节升序,免排序)
  v_lines := string_to_array(p_body, E'\n');
  v_n := coalesce(array_length(v_lines, 1), 0);
  FOR v_i IN 1 .. v_n LOOP
    v_le := least(v_off + octet_length(v_lines[v_i]) + 1, v_blen);
    IF v_fence AND (length(v_lines[v_i])
                    - length(replace(v_lines[v_i], '```', ''))) / 3 % 2 = 1 THEN
      IF NOT v_fopen THEN
        v_fopen := true; v_fs := v_off + 1;            -- 开栅栏行首
      ELSE
        v_fopen := false;
        v_blocks := v_blocks || jsonb_build_array(jsonb_build_object(
          's', v_fs, 'e', v_le, 'kind', 'fence'));     -- 闭栅栏行尾
      END IF;
    END IF;
    IF v_table AND substring(v_lines[v_i] from 1 for 1) = '|' THEN
      IF NOT v_topen THEN v_topen := true; v_ts := v_off + 1; END IF;
    ELSIF v_topen THEN
      v_topen := false;
      v_blocks := v_blocks || jsonb_build_array(jsonb_build_object(
        's', v_ts, 'e', v_off, 'kind', 'table'));      -- 段末行行尾(含其 \n)
    END IF;
    v_off := v_le;
  END LOOP;
  IF v_fopen THEN                                      -- 未闭合 fence→至文尾
    v_blocks := v_blocks || jsonb_build_array(jsonb_build_object(
      's', v_fs, 'e', v_blen, 'kind', 'fence'));
  END IF;
  IF v_topen THEN
    v_blocks := v_blocks || jsonb_build_array(jsonb_build_object(
      's', v_ts, 'e', v_blen, 'kind', 'table'));
  END IF;

  -- ④ 核与块相交→整块(**两遍:fence 先于 table**——fence 块闭合晚于其内部
  --    table 段,构造序不保证外层优先,首版扫描序论断错误已修;块内 '|' 行属代码块)
  FOR v_b IN SELECT * FROM jsonb_array_elements(v_blocks) b LOOP
    v_bs := (v_b->>'s')::bigint; v_be := (v_b->>'e')::bigint;
    IF v_b->>'kind' = 'fence' AND v_bs <= p_e AND p_s <= v_be THEN
      v_s := v_bs; v_e := v_be; v_in_block := true; EXIT;
    END IF;
  END LOOP;
  IF NOT v_in_block THEN
    FOR v_b IN SELECT * FROM jsonb_array_elements(v_blocks) b LOOP
      v_bs := (v_b->>'s')::bigint; v_be := (v_b->>'e')::bigint;
      IF v_b->>'kind' = 'table' AND v_bs <= p_e AND p_s <= v_be THEN
        v_s := v_bs; v_e := v_be; v_in_block := true; EXIT;
      END IF;
    END LOOP;
  END IF;

  IF NOT v_in_block THEN
    -- ⑤ boundary 吸附
    IF v_boundary = 'sentence' THEN
      v_chars := regexp_split_to_array(p_body, '');
      v_cn := coalesce(array_length(v_chars, 1), 0);
      v_cb := 0;
      FOR v_ci IN 1 .. v_cn LOOP
        v_ch := v_chars[v_ci];
        v_cend := v_cb + octet_length(v_ch);           -- 本字符末字节位
        v_nxt := CASE WHEN v_ci < v_cn THEN v_chars[v_ci + 1] ELSE '' END;
        IF NOT v_s_done AND v_cend >= v_s THEN
          v_s := v_start; v_s_done := true;            -- 句首候选 ≤ 核首
        END IF;
        IF v_ch = E'\n'
           OR (v_ch IN ('.', '!', '?', '。', '！', '？')
               AND (v_nxt = '' OR v_nxt = ' '
                    OR v_nxt = E'\n' OR v_nxt = E'\t')) THEN
          IF v_cend >= v_e THEN
            v_e := v_cend; v_e_done := true; EXIT;   -- 句尾含终止符/换行
          END IF;
          v_start := v_cend + 1;                       -- 下一句首候选
        END IF;
        v_cb := v_cend;
      END LOOP;
      IF NOT v_s_done THEN v_s := v_start; END IF;     -- 全文一句:句首=1
      IF NOT v_e_done THEN v_e := v_blen; END IF;      -- 核后无句界:句尾=文尾
    ELSIF v_boundary = 'line' THEN
      v_off := 0;
      FOR v_i IN 1 .. v_n LOOP
        v_le := least(v_off + octet_length(v_lines[v_i]) + 1, v_blen);
        IF v_off + 1 <= v_s AND v_s <= v_le THEN v_s := v_off + 1; END IF;
        IF v_off + 1 <= v_e AND v_e <= v_le THEN v_e := v_le; EXIT; END IF;
        v_off := v_le;
      END LOOP;
    END IF;
    -- ⑥ 前后文窗口(钳位)
    v_s := greatest(1, v_s - v_ctx);
    v_e := least(v_blen, v_e + v_ctx);
  END IF;

  -- ⑦ 扩展不越块:部分相交→钮到块边界外;整块含入→保留
  --    (核若与块相交已在 ④成块,故此处只可能钮扩展;核恒存活)
  FOR v_b IN SELECT * FROM jsonb_array_elements(v_blocks) b LOOP
    v_bs := (v_b->>'s')::bigint; v_be := (v_b->>'e')::bigint;
    IF v_s < v_bs AND v_bs <= v_e AND v_e <= v_be THEN
      v_e := v_bs - 1;                                 -- 左缘部分相交
    END IF;
    IF v_bs <= v_s AND v_s <= v_be AND v_be < v_e THEN
      v_s := v_be + 1;                                 -- 右缘部分相交
    END IF;
  END LOOP;

  -- ⑧ UTF-8 前向吸附(⑦ 后 v_s ≤ v_e ≤ blen、v_s ≥ 1,索引安全;
  --    边界检查一律前置 EXIT WHEN——不依赖 AND 短路求值序,L4 P2-5:
  --    PG 不保证布尔表达式求值序,原 AND 组合有越界读风险)
  v_bytes := convert_to(p_body, 'UTF8');
  v_i := 0;
  WHILE v_i < 4 LOOP
    EXIT WHEN get_byte(v_bytes, v_s - 1) NOT BETWEEN 128 AND 191;
    v_s := v_s + 1; v_i := v_i + 1;
  END LOOP;
  v_i := 0;
  WHILE v_i < 4 LOOP
    EXIT WHEN v_e >= v_blen;                    -- 前置边界门(原 v_e < v_blen AND
    EXIT WHEN get_byte(v_bytes, v_e) NOT BETWEEN 128 AND 191;  -- get_byte 型已修)
    v_e := v_e + 1; v_i := v_i + 1;
  END LOOP;

  -- ⑨ 终界与空区间(核存活故非空;belt)
  v_s := greatest(1, v_s); v_e := least(v_blen, v_e);
  IF v_s > v_e THEN RETURN '[]'::jsonb; END IF;
  RETURN jsonb_build_array(jsonb_build_object(
           'doc', p_hash,
           'offsets', jsonb_build_array(jsonb_build_array(v_s, v_e))));
END $$;

-- === 装配单元族(§4.7 Oracle 2 四配置:重叠合并/前后文窗口/句段边界/
--     表格代码块完整;纯函数,opts 由调用方解析策略后传入——IMMUTABLE
--     纪律;DP5/DP6 消费):合并 → span_unit 管线(句段/窗口/块/UTF-8 吸附,
--     见上文);输出恰为 DP3 OQ4 已裁 spans 形态(doc=chunk content_hash
--     + chunk 内字节坐标,1 基,F3① span 身份)。 ===
CREATE FUNCTION v13_assemble_spans(p_units jsonb, p_opts jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  u jsonb; v_hash text; v_body text;
  v_mode text;
  v_ctx bigint; v_gap bigint;
  v_raw jsonb; sp jsonb;
  v_s bigint; v_e bigint; v_ps bigint; v_pe bigint;
  v_out jsonb := '[]'::jsonb;
BEGIN
  -- opts fail-closed(分步:类型先验 → 默认 → 词表 IS NOT TRUE;L4 修正:
  --     缺 mode/词表外值不再静默放行;boundary/fence/table 键在 span_unit
  --     同款校验——opts 原样透传,单一解析源)
  IF p_opts ? 'mode'
     AND jsonb_typeof(p_opts->'mode') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts (mode)'
      USING ERRCODE = 'V3004';
  END IF;
  v_mode := coalesce(p_opts->>'mode', 'span');
  IF (v_mode IN ('span','whole_chunk')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts (mode)'
      USING ERRCODE = 'V3004';
  END IF;
  IF p_opts ? 'context_bytes'
     AND jsonb_typeof(p_opts->'context_bytes') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts (context_bytes)'
      USING ERRCODE = 'V3004';
  END IF;
  v_ctx := coalesce((p_opts->>'context_bytes')::bigint, 0);
  IF p_opts ? 'merge_gap_bytes'
     AND jsonb_typeof(p_opts->'merge_gap_bytes') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts (merge_gap_bytes)'
      USING ERRCODE = 'V3004';
  END IF;
  v_gap := coalesce((p_opts->>'merge_gap_bytes')::bigint, 0);
  IF v_ctx < 0 OR v_gap < 0 THEN
    RAISE EXCEPTION 'v13: invalid span_assembly opts' USING ERRCODE = 'V3004';
  END IF;
  FOR u IN SELECT * FROM jsonb_array_elements(p_units) LOOP
    v_hash := u->>'content_hash'; v_body := u->>'body';
    IF v_hash IS NULL OR v_body IS NULL THEN
      RAISE EXCEPTION 'v13: span unit requires content_hash and body'
        USING ERRCODE = 'V3004';
    END IF;
    IF v_mode = 'whole_chunk' THEN
      -- 跨度装配不是唯一单元:整 chunk 形态显式在场(§4.7)
      IF octet_length(v_body) = 0 THEN CONTINUE; END IF;
                     -- 空体 belt(L4 P2-6):空文档 ingest 已拒,此处防直调
                     -- 可达面产出 [1,0](s>e 非法区间)
      v_out := v_out || jsonb_build_array(jsonb_build_object(
        'doc', v_hash,
        'offsets', jsonb_build_array(
          jsonb_build_array(1, octet_length(v_body)))));
      CONTINUE;
    END IF;
    -- 1) 原始跨度升序去重
    v_raw := (SELECT coalesce(jsonb_agg(x ORDER BY (x->>0)::bigint), '[]'::jsonb)
                FROM (SELECT DISTINCT x
                        FROM jsonb_array_elements(
                          coalesce(u->'spans', '[]'::jsonb)) AS x) d);
    IF jsonb_array_length(v_raw) = 0 THEN CONTINUE; END IF;
    -- 2) 合并(重叠或间隙 ≤ v_gap)成段;逐段落形(窗口/吸附/钮位在 span_unit)
    v_s := NULL; v_e := NULL;
    FOR sp IN SELECT * FROM jsonb_array_elements(v_raw) LOOP
      v_ps := (sp->>0)::bigint; v_pe := (sp->>1)::bigint;
      IF v_s IS NULL THEN
        v_s := v_ps; v_e := v_pe;
      ELSIF v_ps <= v_e + v_gap THEN
        v_e := greatest(v_e, v_pe);
      ELSE
        v_out := v_out || v13_span_unit(v_hash, v_body, v_s, v_e, p_opts);
        v_s := v_ps; v_e := v_pe;
      END IF;
    END LOOP;
    IF v_s IS NOT NULL THEN
      v_out := v_out || v13_span_unit(v_hash, v_body, v_s, v_e, p_opts);
    END IF;
  END LOOP;
  RETURN v_out;
END $$;
-- 跨 chunk 合并/跨 chunk 前后文:v1 不做(OQ6;chunk 可粗使场景罕见),
-- 缝=units 已携带 chunk_offset,DP5 扩展时按 doc 坐标拼接(§1.4 DP5 行⑦)。
```

### 3.6 freshness 缝:v13_context_required 七键扩八键(DP3 契约 #8)

```sql
-- === OQ3 载体落地 + DP3 §1.4 DP4 行的函数替换缝。OR REPLACE 同签名
--     (OID/ACL 不动);DP3 体逐字保留(三处策略缺行 RAISE 原样),
--     仅增:一 DECLARE(v_corpus)/一 RAISE 块/一子查询键。键序:七键后
--     追加 corpus(第八)。键集变更 ⇒ 旧 active token 全失配 ⇒ 全域恰一次
--     refresh(DP3 OQ1 既判语义,gate G3 功能面断言)。 ===
CREATE OR REPLACE FUNCTION v13_context_required(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_asm_ver int; v_jdef_ver int; v_gen_ver int; v_corpus bigint; v_tok jsonb;
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
    'corpus',   v_corpus)                   -- DP4 第八键(语料代数,OQ3)
  INTO v_tok;
  RETURN v_tok;
END $$;
-- 墓碑/复制纪律:本体=DP3 §3.2 v13_context_required(DP3 行 464–497)逐字
-- 复制+四处增量;DP3 文件里的七键体在其前缀 stage 库照常存活——全树唯一
-- 八键体在本文件,无重复定义面(移动=增+删教训:非移动,是授权换体)。
```

### 3.7 pg_cron 夜跑(OQ7;§8 自辩在 §1.3)

```sql
-- === 扫地僧(§8:调度是行,不是节拍器)。可用性守卫:pg_cron 需
--     shared_preload_libraries 预载——pgembed 未预载时 CREATE EXTENSION
--     失败,异常捕获降级为 NOTICE + 外部队列回退(README 记等价 crontab
--     命令);v13_verify_chunks 始终手动可调,正确性零依赖守护进程。 ===
DO $cron$
DECLARE v_ext boolean;
BEGIN
  BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
  EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'v13: pg_cron unavailable (%) — night verify falls back to external scheduler; v13_verify_chunks() stays callable', SQLERRM;
    RETURN;
  END;
  IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'v13-verify-chunks') THEN
    PERFORM cron.schedule('v13-verify-chunks', '17 3 * * *',
                          $job$SELECT v13_verify_chunks(true)$job$);
  END IF;
END
$cron$;
-- job 清单只有 verify 一条(gate G6 断言:零 cron 驱动的推进面)。
-- 嵌套定界符:$cron$/$job$ 与函数体 $$ 三层互不冲突(附 B 配平注记)。
```

### 3.8 stage 四件 + ACL 全量块(文件真末尾)

```sql
-- === ACL(owner 平面/运行角色分离,OQ5;全量块在文件真末尾,零前向引用)===
REVOKE EXECUTE ON FUNCTION
  v13_chunker_slice(text,jsonb), v13_project_source(text,text,text,uuid,jsonb),
  v13_ingest_document(uuid,text,text,text), v13_rebuild_chunks(text),
  v13_chunk_gc(boolean), v13_verify_chunks(boolean),
  v13_span_unit(text,text,bigint,bigint,jsonb),
  v13_artifacts_ref_lock(), v13_decisions_ref_lock()
FROM PUBLIC;                       -- 写/运维面:仅 owner(驱动器/cron 同 owner);
                                   -- span_unit 是内部助手,不出公共面;
                                   -- 两引用锁触发器函数仅触发器调用
                                   -- (CREATE TRIGGER 时校验,无需 EXECUTE 面)
-- v13_adv_xact_locks(jsonb,bigint) 有意不 REVOKE:触发器嵌套调用面
-- (decisions 写者角色不定,嵌套普通函数调用会查 EXECUTE);advisory 锁
-- 是协调原语无数据面权限放大(接受面记注)

GRANT SELECT ON chunks, v13_sources, v13_chunks_meta TO v13_recall;
                                   -- 读面:DP5 recall 消费;DP6 届时补 v13_resolve(§1.4)
GRANT EXECUTE ON FUNCTION
  v13_body_hash(text), v13_tsv_en(text),
  v13_extract_spans(text,jsonb), v13_assemble_spans(jsonb,jsonb),
  v13_span_unit(text,text,bigint,bigint,jsonb)
TO v13_recall, v13_resolve, v13_route;   -- 纯读辅助,三角色共用(DP1 先例)
-- 表 DML:运行角色零授权(默认无)——gate H 组负向断言。

COMMIT;
```

**stage 四件**(照 DP3 §3.8 形制):

- `v13/chunks/v13_chunks.sql`:上文全量;BEGIN/COMMIT 包裹。
- `v13/chunks/setup_db.py`:DROP-CREATE 库 `agent_v13_chunks`(v12/indb/setup_db.py 仪式);`files_through('chunks')` 加载七文件;超级用户连接(DO 块/触发器/策略 INSERT 前置同 DP2/DP3)。
- `v13/chunks/test_chunks.py`:§4 A–H 组;退出码 0=通过;fixture 纪律=真实链路(事件经 v13_append_event、effect 经 enqueue/claim/complete、摄取经驱动器契约四步、manifest 经 DP3 refresh settle)。
- `v13/chunks/README.md`:运维纪律(§4 末尾清单)。
- `v13/load.py`:SQL_LOAD_ORDER 追加 `'chunks/v13_chunks.sql'`(第 7 位);`STAGE_THROUGH["chunks"] = 7`。零改动既有行。

---

## 4. 里程碑与 gate

单里程碑单 stage:`v13/chunks/`。命令形态 `uv run python v13/chunks/test_chunks.py`,退出码 0=通过。**提交前 DP1 四 stage + DP2 + DP3 gate 全部复跑**(各自库前缀切片不加载本文件,防回归的结构性保证;AGENTS.md 前置条件 1)。

**断言纪律(DP1–3 原样沿用)**:fixture 走真实链路——事件经 v13_append_event、effect 经 enqueue/claim/complete 真实调用、摄取经驱动器契约四步(§3.3)、manifest/refresh 经 DP3 真实流程;owner 直插仅限「引用种子」类 fixture(D1/D4,ch7 语义的测试载体),断言其被触发器/校验器拒或成立的两侧都测。

### G-ctx2 原文映射(§10 逐条)

| §10 G-ctx2 原文 | 断言落点 |
|---|---|
| chunks 行自证 | A1–A5(含 ch7:146 exists 断言 A3) |
| 重摄取同事务一致(插入即可检) | B1–B6 |
| rebuild 幂等 | E1–E2(+D4 chunker bump 重灌) |
| verify_index 通过 | E3–E5(T0 载体 v1 七项,附 A #5) |
| p99 events INSERT 无回退 | H1–H2 |

### A 组 · 纪律一:行自证与守卫门

| # | 断言 | 对应 |
|---|---|---|
| A1 | 摄取 fixture 后全表自证:每行 content_hash=v13_body_hash(body)(gate 对照 SQL 直查;与 CHECK 同式) | §4.2 纪律①/ch7:144 |
| A2 | 负向:owner 直插哈希错误行 → v13_chunks_hash_selfcheck V3004;直插哈希正确但 artifact 缺席的行 → 门② V3004 | 纪律①结构性 |
| A3 | exists 断言:每行 EXISTS artifacts(content_hash, kind='chunk')(ch7 原文直查) | ch7:146 |
| A4 | 不可变:UPDATE 任一行 → V3004;TRUNCATE chunks → V3004(门①/门⑤) | OQ5 |
| A5 | 粗切复用:whole 策略下整文档单行,chunk 0 的 content_hash=source_hash,一次 artifact 两用;chunk_offset=0 | ch7 7.3 最小形态 |

### B 组 · 纪律二:重摄取同事务一致

| # | 断言 | 对应 |
|---|---|---|
| B1 | 驱动器契约四步全链:session→enqueue(tool)→claim→complete('succeeded')→同事务 ingest;返回键集恰等 {source_hash,artifact_id,chunk_count,locked,unchanged,generation} | OQ7/ch2 纪律 |
| B2 | 提交后插入即可检:新连接 SELECT body_tsv @@ websearch_to_tsquery('english',…) 命中新行;EXPLAIN 走 ix_chunks_tsv(索引随事务一致) | §4.2 纪律②/F3 |
| B3 | 事务外无中间态:连接 A BEGIN+ingest 未提交 → 连接 B 计数=旧;A ROLLBACK → 零残留、generation 零漂移(bump 触发器随事务回滚;崩溃等价) | ch7:95–101 |
| B4 | 幂等重摄取:同 body 同策略再 ingest → locked=true 路径 unchanged=true(若被引用)或未引用路径表内容不变;generation 允许 bump(事件计数非表内容, OQ2 口径) | OQ2 |
| B5 | supersede:同逻辑源 v2(异 body)摄取携 p_supersedes → 旧源无引用行死亡、新源行在;引用行存活(D 组前置);**lineage 同事务生效**:旧 v13_sources 行 superseded_by=新 source_hash | 纪律②/F3② 交面/L4 P1-1 |
| B5b | **零复活(L4 P1-1)**:B5 后 rebuild(活动策略任意)→ 旧 source_hash 在 chunks 仍零行(未被当前策略重投影复活);GC delete 模式(策略翻 delete-unreferenced 版本行,测后回滚)同跳过退役源;负向:owner 直改 v13_sources(corpus 改动/superseded_by 已非 NULL 再改/任意 DELETE)→ V3004(append-only 单一豁口) | OQ4/L4 P1-1 |
| B6 | corpus 冲突 fail-closed:同 source_hash 异 corpus → V3004 | OQ4 |

### C 组 · 纪律三:外部只记 hash

| # | 断言 | 对应 |
|---|---|---|
| C1a | extract 两级之一(提取级):v13_extract_spans(body,terms) 返回**纯 offsets 数组** `[[s,e],…]`(二元整数数组、升序、1 基字节位;非 {doc,offsets} 对象——首写把两级写混,L4 修正);CJK fixture 断言 v_bstart = octet_length(left(body,n-1))+1 对照(字节位天然落在前导字节) | OQ6/L4(d) |
| C1b | assemble 两级之二(装配级):消费 units[{content_hash,body,spans=offsets 数组}] → 输出键集恰 {doc,offsets};doc=64hex;全文(gate 对两函数全部 fixture 输出)不含 source_hash/chunk_no 键 | ch7:102–110/DP3 契约 #9 |
| C2 | ingest/rebuild/gc 返回值键白名单恰等(计数标量允许;无行级主键外泄) | 纪律③ |
| C3 | 假清单红(ch7:165 练习 4):含 (source_hash,chunk_no) 引用的清单 JSON 无法由 v13_assemble_spans 产生(形态面负向);manifest 侧拒绝归 DP3 V3003 键集封闭(引用不重做) | ch7 练习 4 |

### D 组 · F3:保留规则与回放 gate

| # | 断言 | 对应 |
|---|---|---|
| D1 | 引用存在性单元:v13_chunk_referenced(h) 在 owner 种子 context artifact(候选含 h,produced_by=已 succeed effect)后 =true;对照:未引用 hash → false | F3② 一条 SQL |
| D2 | 被引用行不可删:DELETE 该 chunk → V3004(门③);无引用行 DELETE 成功 | F3② |
| D3 | GC 只清无引用:dry-run 报告恰等无引用行集(按 corpus 分组);策略 dry-run-only 下 gc(false) 仍零删除(负向) | F3②/§12 |
| D4 | **F3③ 回放 gate(核心)**:① para v1(target 3072)摄取 docA/docB,记录 h1(docA 某 chunk content_hash)与 docB 行集/行数;② owner 种子 context artifact(候选含 h1,produced_by=已 succeed effect)→ **先行断言 v13_chunk_referenced(h1)=true**(锁建立);③ 策略翻 v2——**v2 版本行 value 与 v1 仅 target_bytes=512 不同、chunker_version 仍 'para_v1'**(封闭词表内;策略版本≠chunker 串,L4 P1-2:若 v2 行携 'para_v2' 会被 G8 词表拒收、若 (iv) 断言 chunker_version=v2 则永不可满足——原写法两者不可同时成立,故 (iv) 改断 target 512 口径)+rebuild → (i) docA locked 跳过、行原样;(ii) v13_replay(该 artifact) 逐字节不变(DP3 读者函数);(iii) hash→artifact 回取:SELECT artifacts WHERE content_hash=h1 AND kind='chunk' 的 inline::text 与 ② 时逐字节相等;(iv) docB 已按 target 512 重切:行集≠①、行数>①、逐行 chunker_version='para_v1'、chunk_offset 按 512 口径重导(gate 对照 v13_chunker_slice(body, v2 策略) 产物逐行相等) | F3③ 全文/L4 P1-2 |
| D5 | locked 拒异切:对 docA 以 v2 直接 ingest 同 body → v_exist≠v_new → V3004 | OQ2 |

### E 组 · rebuild 幂等 + verify

| # | 断言 | 对应 |
|---|---|---|
| E1 | rebuild 连跑两次:array_agg(to_jsonb(chunks) ORDER BY source_hash,chunk_no) 逐字节相等;locked 计数一致 | ch7:144/G-ctx2 |
| E2 | rebuild 空库/无匹配 corpus:no-op 零错误返回 {sources:0} | 噪声面 |
| E3 | verify 全绿:摄取+引用 fixture 后**七项** {name,ok} 全 true(原六项重定义[④改 chunk 身份筛+投影在场、⑤改非停用词 canary+强制索引]+⑦artifact_backref 新增),all_ok=true,version=1;**goal-echo 对照**:空库+纯 DP3 goal-echo 候选 fixture 跑 verify 亦全绿(chunk 身份筛——首写全量误报已修,L4 修正) | G-ctx2 verify_index(T0 载体,附 A #5)/L4(a)(b) |
| E4 | verify 负向:owner 种子含**chunk 身份** hash 的 context artifact 且该 chunk 投影行已删 → ④红+⑦红+p_raise V3004;goal-echo 候选缺投影行不红(身份筛断言);meta 守卫负向(DELETE/调低 UPDATE meta)归 G4;⑥的可达面=装载期未种子的破损库(不可构造则记注 belt,不虚标) | fail-closed/L4(a) |
| E5 | DP5 缝在场:报告含 version 键(升 v2 挂 verify_index 是 DP5 契约②) | §1.4 DP5 行② |

### F 组 · T0 tsvector 可运行性(§7)

| # | 断言 | 对应 |
|---|---|---|
| F1 | EXPLAIN(COSTS OFF) 英文 websearch 查询(canary=非停用词,如 'quasar'——'the' 是 english 停用词会被剥成空 tsquery,首写已修)计划含 ix_chunks_tsv(Bitmap)Index Scan;**索引强制写死一种:gate 会话 SET enable_seqscan=off**(会话局部、gate 连接即弃;理由=小表合法 Seq Scan 是成本模型正确行为,不能证明 GIN 病变——与 verify ⑤ 同方案同理由,L4 修正) | §7 T0/绑定面 |
| F2 | 检索正确性:英文 fixture 查询命中恰等预期 chunk 集;CJK 查询零命中(断言零命中以钉 T0 边界——CJK 走 stannum 直接路径是设计 §7/§4.8 既裁,README 记) | §7/§4.8 |
| F3 | 提交即可检的索引面:ingest 提交后同语句 EXPLAIN 即用索引(pending list 亦可见;EXPLAIN 同 F1 强制方案) | G-ctx2 |
| F4 | corpus 域隔离:两 corpus 各自检索不串(corpus 列+检索限定);记忆语料真表归 DP6(断言只钉隔离面) | §4.4 分索引前半 |

### G 组 · freshness:corpus 键接线(DP3 契约 #8)

| # | 断言 | 对应 |
|---|---|---|
| G1 | token 八键:键集恰等 {sem,dec,goal,tools_rev,asm_ver,jdef_ver,gen_ver,corpus};七键语义与 DP3 逐字一致(对照 fixture) | DP3 契约 #8/OQ3 |
| G2 | 全域恰一次 refresh:DP3 真实流程(parse→advance→settle)冻结 active token T1 → 摄取新文档(generation+1)→ v13_context_fresh=false → 再 settle → active=T2;无变更再查 fresh=true(恰一次,不活锁) | DP3 OQ1 键集变更语义 |
| G3 | 单调性:任何 chunks DML(无引用行 DELETE 亦然)→ generation+1 → 不新鲜 | OQ3 |
| G4 | RAISE 保留:删 assemble 策略行(后恢复)→ DP3 原文案文 RAISE;**meta 守卫(新增)**:DELETE meta 行→V3004、UPDATE generation 调低→V3004(单调性执法);token 内 'chunks meta row lost' RAISE 保留为 belt(守卫使其不可构造——不可达路径记注,不虚标可达) | 零回归面/OQ3 |
| G5 | 源码零触碰:本文件源断言不含 v13_probe/v13_judgment_envelope/v13_advance 字样(DP1 #59 接线归 DP5 的结构性自查;grep 断言) | 消费清单 #2 |
| G6 | cron 面:pg_cron 在库 → cron.job 恰一条 v13-verify-chunks 且无任何非 verify 项;不在库 → 函数手动可调两分支均断言 | §8 不是节拍器 |
| G7 | token 成本:2k docs 已载后 v13_context_required 直调 <5ms(单行 meta 读;DP3 OQ1 同款承诺) | OQ3 论证 |
| G8 | 策略负向族(fail-closed 三律,L4 修正):mode 为 JSON 数字、chunker_version='para_v2'(未知)、analyzer_version 缺失、max_doc_bytes 为字符串、target_bytes 缺失、boundary='word'(未知)、context_bytes 为字符串 → 各自 V3004(种子翻行方式:新版本行+同事务翻 active,测后回滚;DP1 #3 仪式) | §3.2 三律/L5(a)(b)(c) |

### H 组 · p99 + ACL + 加载

| # | 断言 | 对应 |
|---|---|---|
| H1 | **p99 events INSERT 无回退**:基线(空 chunks)vs 载入(2k docs×~2KB+GIN+代数 bump)各 2000 次 v13_append_event;p99_loaded ≤ max(p99_base×1.25, p99_base+0.5ms);三轮取中位(噪声协议入 README) | G-ctx2 第五断言 |
| H2 | 并发不扰 advance:摄取事务进行中另一连接 advance(② 读 token)不被阻塞(meta 行锁只在 chunks DML 语句内;两连接 fixture) | OQ3/H1 机理面 |
| H3 | ACL 负向:SET ROLE v13_recall → SELECT 三表 ok、INSERT/UPDATE/DELETE/TRUNCATE chunks 权限拒、EXECUTE ingest/rebuild/gc/verify 权限拒;SET ROLE v13_resolve → SELECT chunks 权限拒(DP6 补授前形态,§1.4 注记) | OQ5/不变量 8 |
| H4 | 前缀切片:DP1 M1 库(四文件)无 chunks 表、token 仍七键(files_through 结构断言;与 DP1–3 gate 复跑互证) | 消费清单 #6 |
| H5 | 哈希同源终点:跨源同文两文档 → 两行同 content_hash 异 source_hash;artifact 单行(去重);v13_body_hash('') 与手工式相等 | OQ1/OQ4 |

### I 组 · 装配四配置语义(§4.7 Oracle 2 normative 面;每配置一 gate,L4 修正)

| # | 断言 | 对应 |
|---|---|---|
| I1 | 句段边界:正文中段命中(无换行包裹)→ boundary='sentence' 输出端点=句首/句尾(终止符含入;换行恒句界);fixture 含 CJK 终止符(。)与英文句点两种 | §4.7/OQ6 |
| I2 | fence 整块:核命中在 ``` 围栏块内部(配对闭合)→ 输出=整块(开栅栏行首..闭栅栏行尾);未闭合→至文尾;扩展侵入(核在块外、窗口/吸附部分相交)→钮到块边界外,核存活 | §4.7/L4(b) |
| I3 | 表格整段:核命中在行首 '|' 连续段内 → 输出=整段;'|' 行在 fence 块内时 fence 优先(I2 复合 fixture) | §4.7/L4(b) |
| I4 | UTF-8 前向吸附:context_bytes 窗口端点构造落 CJK 多字节字符内部(v_s-v_ctx 落在续字节)→ 两端点输出均为前导字节位(octet_length(left(…)) 对照);extract 产物 v_bstart 天然前导(C1a 同源) | L4(c)/OQ6 |

### J 组 · 两连接竞争(锁协议,不变量 9;DP2 M2-17 两连接 fixture 先例)

| # | 断言 | 对应 |
|---|---|---|
| J1 | 引用∥删除(已提交引用):连接 A 种子 context artifact(候选含 h1,produced_by=已 succeed effect)提交 → 连接 B rebuild 该源 → h1 行存活(locked 计数+1),表内容与 A 提交前一致 | F3②/锁协议 |
| J2 | 引用∥删除(在途引用):连接 A BEGIN+INSERT context artifact(触发器持 advisory 锁未提交)→ 连接 B rebuild 同 hash 集 → B 阻塞(pg_locks 轮询断言阻塞态)→ A COMMIT → B 苏醒后检查见引用 → 行存活(TOCTOU 闭合的行为面) | L4 并发修正 |
| J3 | ingest∥rebuild 同 source:B rebuild 进行中(持 source 锁未提交)→ A ingest 同 source → A 排队;先后完成;**零 23505 撞键**、终态=恰一代切片(chunker_version 一致、行数=切片数、content_hash 全自证)、verify 全绿;反向次序同断言 | L4 并发修正 |
| J4 | 无死锁冒烟:J1–J3 各跑三轮+双连接并行 ingest 异 source 交错,全部在 statement_timeout 内完成(复合序论证的行为面;超时=红) | §3.1bis 协议序 |

**收尾工件(AGENTS.md)**:SQL 追加进 v13/load.py(第 7 位);stage README 更新;一里程碑一提交(`v13: <祈使句摘要>`,按路径 add)。README 必记运维纪律:①驱动器契约四步与 ops session 复用;②chunker 翻版=新策略行+rebuild(被引用源锁定的接受面与逃生缝);supersede 后旧源台账退役(superseded_by 标记;rebuild/GC(delete)/召回面均跳过——DP5 契约⑨);③保留规则与 GC 策略门+代数单调性守卫(手工改 meta 被拒,守卫触发器执法);④pg_cron 前置/降级与 crontab+psql 等价命令;⑤T0 english 边界(CJK 走 DP5 stannum);⑥p99 度量协议;⑦verify 手动命令(canary 非停用词与 enable_seqscan 强制的理由一并记入);⑧大产物 ref 路径与窗口化 GC 的台账触发条件;⑨锁协议:rebuild/GC(delete)与同源 ingest 排队是预期(持有期=事务尾)、引用端触发器自动取锁、批量候选落行=单引用集纪律;⑩装配四配置语义与策略五键(§3.2)。

---

## 5. 风险与回退

| # | 风险 | 缓解/接受面 |
|---|---|---|
| 1 | jsonb::text 序列化跨 PG 大版本理论可变 → 升级后 rebuild 重算哈希漂移 | 公式钉死部署版本;升级=重摄取新 source_hash 或保留旧行(referenced 行本就不可删);README 记升级纪律;DP3 blob 同式同风险,非本 DP 新增面 |
| 2 | OQ2 锁权衡:被引用源永不随 chunker 升版(引用 referenced-forever ⇒ 实际冻结) | exact replay 优先于语料升级(F3 裁决方向);逃生缝=同逻辑源新内容新 source_hash 重摄取;终极解锁=content_hash 主键迁移(§4.2 预留,台账);风险接受面写入附 A #2 呈报 |
| 3 | 引用检查 containment 的规模(每删除行一次 @> 探测) | ix_artifacts_candidates 表达式 GIN 已背书;rebuild/GC 离线;规模超限再物化引用登记表(台账,与窗口化 GC 同触发族) |
| 4 | 摄取 effect 线性摩擦(ops 要走四步) | 驱动器一次性脚本;ops session 复用;正确性收益(ch7 溯源不变量)压倒仪式成本;README ① |
| 5 | T0 english config 对 CJK 零召回 | 设计 §7/§4.8 既裁(CJK 语料直接 stannum);gate F2 钉边界;不修不改道 |
| 6 | token 第八键 ⇒ 存量 active token 全失配,全域一次 refresh | DP3 OQ1 既判语义(键集增删的既定后果),一次性成本,预期内;gate G2 断言恰一次 |
| 7 | pg_cron 不可用(pgembed 未预载 shared_preload_libraries) | §3.7 守卫降级 NOTICE+外部 crontab 等价命令(README ④);verify 手动可调,正确性零依赖;实施期实机探针确认(附 B 冒烟清单④) |
| 8 | p99 度量噪声造成 gate 抖动 | 三轮取中位+带宽断言(×1.25 或 +0.5ms 取大);协议 README ⑥;带宽取大者避免小基数误红 |
| 9 | 引擎行为假设(BEFORE TRUNCATE 触发器/EXPLAIN 文本行/生成列吃用户 IMMUTABLE 函数/部分表达式 GIN 计划选择) | 全部列入实施期实机冒烟清单(附 B);任一不成立时回退方案:⑤改验证器第五项为「计数对照」、TRUNCATE 门改 RULE 拒绝形态(记载于实施 README,不阻断计划) |
| 10 | DP6 decisions 引用路径漂移 → 被引用行误删 | 路径冻结契约(§1.4 DP6 行①);v13_chunk_referenced 单源消费;建议 DP6 gate 直接调用本函数断言(契约行已写) |
| 11 | 锁协议死锁/持有期(rebuild/gc 逐源持锁至事务尾;并发写者交错) | 复合序论证(hash 锁只随其 source 锁之后取得、source 升序、写入端单引用集叶性,§3.1bis);gate J4 三轮冒烟;rebuild/gc 离线窗口运维注记 README ⑨;advisory 锁与 DP1–3 行锁无共享键空间(hashtextextended 双参) |

---

## 6. 教程映射(§13;正文零改动)

| 章 | 教程承诺(实测行号) | 本 DP 兑现 |
|---|---|---|
| 7.2 | artifacts 表与生产/消费纪律(ch7:26–56;produced_by→succeeded、append-only)——DP3 已落表,本 DP 首次启用 kind='chunk' 写路径,两守卫自动生效 | §3.3(ingest 落 artifact 走触发器门)/B1 |
| 7.3 | chunks 投影 DDL(ch7:72–90:七列+主键)、重摄取同事务 delete+insert(ch7:92–101)、manifest 指针只记 hash(ch7:102–110) | §3.1(七列+chunk_offset+body_tsv)/§3.3/C 组;B3 断言 ch7 事务面原文 |
| 7.4 | 「投影行自证,外部不引用它的主键」(ch7:146–149);跨源同文双行由判断缓存吸收(ch7:88–90) | OQ1/纪律③/H5 |
| 7.5 | G-ctx2 三纪律断言块(ch7:141–155;rebuild 跑两次字节级一致=ch7:144) | A/B/E 组逐条;幂等口径差(OQ2)记附 A #2 |
| 7.6 | 检查点练习 4:假清单引用 (source_hash,chunk_no) 则 gate 红(ch7:165) | C3 |

正文零改动:教程已含三纪律与 G-ctx2 断言——本 DP 是兑现侧;设计 §13 第 7 章行两件(三纪律入硬性规定✓7.5;manifest 指针✓7.3)均已在教程正文在场,无需新增指针。

---

## 7. 明确不做(§12 台账为源;P2/台账项一律不承诺为首版交付)

| 项 | 依据/触发条件 |
|---|---|
| CJK bigram 列(§4.6 升级路径) | kohaku fixture 漏召率超阈值;归 DP5+(GENERATED 列+独立索引+查询侧同函数的路径设计已裁,不在本 DP 实施) |
| T1 vectorchord/RRF 混检(§7) | 固定评估集证明 lexical 漏召;嵌入=派生缓存行(content_hash×model)、embed=effect,全套归 T1 |
| pg_cron tick/空转扫(§12) | 扫描恢复空转成本实测超标;refresh settle 是 effect 驱动;本 DP cron 只挂 verify(gate G6 断言零其他 job);tick 投影归 DP6 且同受 §12 触发 |
| chunks 主键迁 content_hash(§4.2 原文预留) | IDF 失真实测超标;OQ2 锁的终极解锁面 |
| artifact ref 大产物路径 | max_doc_bytes 超限拒(v1 inline 一律化,OQ4);超限语料真实出现时评估(§12 同族) |
| 窗口化 GC 执行器 | chunk_gc 策略键已落(mode=dry-run-only);触发=扫描恢复成本实测超标(DP3 blob 同族,「DP4+ 语料面一并评估」的落点即本行) |
| transcript_chunks/记忆语料(§4.4/§9) | DP6 全套(水印/tick 批量构建/p99 对比);本 DP 只备 corpus 列隔离面(F4) |
| stannum 本体(索引/绑定矩阵/刻画/highlight/verify_index 调用) | DP5;本 DP 留缝=body_tsv T0 起步+verify version 键+spans 签名冻结(§1.4 DP5 行②③④) |
| 跨 chunk 合并/跨 chunk 前后文 | OQ6 边界;chunk 可粗使场景罕见;units 已携 chunk_offset,DP5 扩展缝。(结构级表格/代码块完整**已移入 v1 交付**:fence 整块+表格段扩展,I 组 gate;设计 §4.7 Oracle 2 补充是 normative 面,首写误入台账,L4 修正) |
| 效用遥测/emergent/分片哈希启用/boost 闭环等 §12 其余行 | 与本 DP 无关,不碰 |

---

## 附 A:与设计稿/上游裁决的分歧点清单(供父 loop 复核)

| # | 分歧/裁量 | 论证 |
|---|---|---|
| 1 | chunks 增 chunk_offset 列——设计 §9 列清单无此列 | stepfun F3① 已裁方向(设计缺口):span 身份=(chunk content_hash,起,止) 需 doc 内字节基偏移;本 plan 立法,设计稿未改 |
| 2 | rebuild=保护式重灌(删无引用行+按活动策略重投影;被引用源 locked)取代 §4.2/ch7:86 字面「truncate+重灌」 | F3②(被引用行不可删)与字面 truncate 在 chunker 升版下直接冲突——同 source_hash 新旧两代行在冻结主键 (source_hash,chunk_no) 下必然撞键;三分裁决见 OQ2;幂等口径收窄为「表内容字节级一致」(generation 是事件计数);接受面=被引用源不升级(逃生缝=新内容新 source_hash/主键迁移台账) |
| 3 | 行自证公式=sha256(to_jsonb(body)::text)——设计 §9/ch7:82 字面「sha256(body)」的载体化 | exists artifacts(content_hash,kind='chunk')(纪律①/ch7:146)与 DP3 已落 artifacts CHECK(sha256(inline::text))结构性互斥除非同式;公式收口 v13_body_hash 单源;设计字面未改 |
| 4 | 语料代数=重摄取代数(v13_chunks_meta 单行计数器),非 corpus 指纹 | DP3 契约 #8 给两选项;指纹在 token 消费面(advance 会话锁内)不满足毫秒级承诺;计数器的 bump 面对 chunks 表封闭(语句级触发器盖住一切写入路径),与 DP3 OQ1「不做 bump 计数器」论证的适用域(会话语境生产者)不冲突——论证见 OQ3 |
| 5 | G-ctx2「verify_index 通过」在 T0 的载体=v13_verify_chunks v1 七项(自证/投影孤儿/源台账/引用可回取+投影在场[chunk 身份筛]/GIN 可用性[非停用词 canary+enable_seqscan 强制]/meta 在场/对账反向) | T0 无 stannum 索引可 verify;amcheck 不覆盖 GIN;设计 §4.2「verify_index 进 gate+pg_cron 夜跑」的意图=投影健康的日常校验+夜间自动化,七项是其 T0 忠实形态;stannum 半边=DP5 升 v2(version 键已备,E5);gate 断言对象在此口径下与 §10 一致 |
| 6 | 跨度提取 T0 形态=ASCII 折叠大小写不敏感子串扫描(stem 不匹配) | §4.7「高亮跨度」的正式载体是 stannum highlight(与索引同 tokenizer,DP5);PG 核心无词元→字节偏移原语(ts_headline 只回标记文本);T0 诚实边界以确定性子串扫描担纲,不虚标质量;签名/输出形态冻结使 DP5 换实现零改消费方 |
| 7 | 纪律②的 delete 面收窄:重摄取只删无引用行(被引用源 locked 分流:幂等 no-op 或拒异切) | F3② 与纪律②的交面——被引用源不可能全量 delete by source_hash;locked 源幂等重摄取(同切片)仍畅通,异切拒;supersede 路径同收窄 |
| 8 | v13_sources 增 superseded_by lineage 列——设计 §9 列清单无此列 | L4 P1-1:supersede 后旧源零行,rebuild 按当前策略重投影=复活已退役版本(与 B5 断言矛盾且无 gate 捕获);lineage 显式标记(append-only 单一豁口 NULL→值)+ingest 同事务标记+rebuild/GC(delete)/召回(DP5 契约⑨)三面跳过;设计稿未改 |

**设计矛盾检查:未发现 blocked 级矛盾。**§4.2/§4.7/§7/§8/§9/§10-G-ctx2/§12/§13 的 normative 内容全部有落点(§2 映射表);F3 已按已裁方向立法(附 A #1/#2/#7);其余分歧均为载体化/裁量(附 A #3–#6),设计稿未改,呈报父 loop 复核。

---

## 附 B:全教训自检(turn 1–21,机械执行记录)

| 教训 | 执行记录 |
|---|---|
| **纸面加载模拟记数字**(turn 8/9:42601/42723 两轮) | §3 草案逐块清点(L4 修复后重数):顶层语句 44 = CREATE TABLE 3(chunks/v13_sources/v13_chunks_meta)+ 函数语句 23(新 22:body_hash/tsv_en/chunk_referenced/adv_xact_locks/artifacts_ref_lock/decisions_ref_lock/sources_append_only/chunks_meta_guard/chunks_immutable/chunks_artifact_exists/chunks_retention/chunks_generation_bump/chunks_no_truncate/chunker_slice/project_source/ingest_document/rebuild_chunks/chunk_gc/extract_spans/span_unit/assemble_spans/verify_chunks + OR REPLACE 1:context_required)+ CREATE TRIGGER 9(6 on chunks/v13_sources + meta_guard + artifacts_chunk_ref_lock + decisions_chunk_ref_lock)+ CREATE INDEX 3(ix_chunks_corpus/ix_chunks_tsv/ix_artifacts_candidates)+ 种子 INSERT 2 条 4 行(meta 1+policies 3;首写把总数 40 写成组件和 41,真实语句数 39——口径滑差,本轮以语句计修正)+ DO 1(cron)+ ACL 3(REVOKE 1+GRANT 2);BEGIN/COMMIT 包裹 1 对;$$ 配平 24 块(23 函数体+1 cron DO,后者用 $cron$/$job$ 双层独立定界,与 $$ 零冲突);0 重复定义(v13_context_required 八键体全树唯一存活于本文件,DP3 文件七键体只在其前缀 stage 库);0 省略号(SQL 块内无 …/... 占位,turn 1 教训);前向引用分层 L1 原语 2 函数→L1b chunk_referenced+锁原语 v13_adv_xact_locks+引用锁触发器×2(artifacts/decisions 均前缀文件对象,无前向)→L2 v13_sources+触发器→L3 v13_chunks_meta+守卫→L4 chunks+索引→L5 触发器函数×5+触发器→L6 种子→L7 chunker/project/ingest(锁原语 L1b 已在前)→L8 rebuild/gc→L9 spans(span_unit 先于 assemble_spans;convert_to/get_byte/regexp_split_to_array 全核心面)→L10 verify→L11 context_required→L12 cron→L13 ACL,逐层仅依赖更早层,0 违例 |
| **类型算子层**(turn 7/8:jsonb 字面量/算子层) | 策略种子单完整 JSON 字面量+$j$::jsonb(§3.2 三行,全文件唯一 jsonb 字面量族);digest() 产物一律 encode(…)::hex(v13_body_hash 单点);无 text‖text 进 jsonb(全部 jsonb_build_object/jsonb ‖);数值算子显式 cast((p_policy->>'target_bytes')::bigint、chunk_offset bigint);to_tsvector 显式 'english'::regconfig(IMMUTABLE 包装是生成列硬前提);字节口径一律 octet_length(fence 计数用字符口径,两口径对 ``` 等价已注);引用检查用 jsonb @> containment;verify 声明 VOLATILE(gin_clean_pending_list 是 VOLATILE,STABLE 承诺不诚实——探针批判轮修正);§3.4 注①已标 EXPLAIN 字面量双单引号转义;**布尔异或运算符全文清零**(v_fence 改 <> 不等式——PG 无此运算符,首写函数创建即败,L4 P0 修正;扫描零残留);三值逻辑:全部词表判断 (x IN (…)) IS NOT TRUE 拒收(缺 mode/NULL 不再静默按默认,L4 修正);数值/布尔键分步类型先验(jsonb_typeof 先行、分步 IF 保证求值序——'abc'::bigint 22P02 不可能先于守卫);UTF-8 续字节判定 get_byte(convert_to(body,'UTF8'),i) BETWEEN 128 AND 191(≤4 步,前向吸附);字符拆分 regexp_split_to_array(p_body,'')(多字节安全,句段扫描);canary 非停用词 'quasar'('the' 是 english 停用词,首写已修);span_unit RETURN 括号本轮自检当场抓到一处丢失并修复(记档:重写大块必配平复查) |
| **移动=增+删**(turn 8 #57) | 唯一换体=context_required OR REPLACE 同签名(DP3 明文授权缝,非移动);旧七键体不在本文件任何位置重复(唯一存活形态=DP3 文件,其前缀库照常);无同文件内移动块;span_unit 为原位重设计(签名/体/ACL 两处同步换,grep 无旧签名 (text,text,bigint,bigint,bigint,boolean,boolean) 残留) |
| **gate 不引用未加载对象**(turn 7 #46) | 本 stage=全树第七文件,A–J 组断言对象全部 ≤7 号文件(DP1–3 对象+本文件对象);J 组两连接 fixture 用 pg_locks 轮询断言阻塞态(DP2 M2-17 先例),零守护进程依赖;I 组直调 span_unit/assemble_spans(本文件对象);H4 显式断言前缀切片(DP1 M1 库无 chunks/八键 token);DP1–DP3 各自 gate 的七键断言在其前缀库不受本文件影响——与 G1 八键断言不同库共存,非冲突 |
| **哈希同源**(turn 6 #43 及多轮) | chunk/源/切片哈希唯一来源 v13_body_hash(消费点:CHECK/门②/ingest/rebuild/H5 五处全经它);语料代数唯一来源 v13_chunks_meta.generation,唯一消费点 v13_context_required(其自身即 token 唯一来源);spans 的 doc 键唯一来源=unit.content_hash(v13_body_hash 产物)——零处内联重算哈希公式;**superseded_by(L4 P1-1 新增列)不进任何哈希/键**:source_hash=v13_body_hash(body) 与它无关,token corpus 键=generation(bump 触发器只挂 chunks 表——v13_sources 的 lineage UPDATE 不 bump:退役标记是台账元数据,非投影内容变更) |
| **争议引擎行为实机实证可选**(turn 10/12) | 引擎事实依赖清单(实施期实机冒烟,风险 #9 已配回退):①BEFORE TRUNCATE 语句级触发器;②FOR-IN-EXECUTE 捕获 EXPLAIN 文本行;③生成列吃用户定义 IMMUTABLE 函数(PG12+);④pg_cron 在 pgembed 的可用性(shared_preload_libraries 预载);⑤部分表达式 GIN(jsonb_path_ops)的计划选择;⑥string_to_array/E'\n\n' 字节口径;⑦hashtextextended(text,bigint)(PG11+ 核心)与触发器内 pg_advisory_xact_lock;⑧regexp_split_to_array(s,'') 对多字节字符的拆分;⑨get_byte/convert_to 的 UTF-8 前导字节判定(⑧⑨即 UTF-8 吸附循环的 PG18.4 临时库实证面——本轮可选实机项)。任一不成立均有不影响正确性的回退;不依赖未证实行为承载正确性(守卫降级形态优先) |

---

## References

- 设计冻结稿:`docs/designs/v13-context-on-pg.md`(§4.2/§4.7/§7/§8/§9/§10 G-ctx2/§12/§13;2026-09-19 v2 禁改)。
- 设计审查:`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md` F3(P0,已裁方向;附 A #1/#2/#7 的立法依据)。
- DP1:`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md` §1.3(契约表 DP4/DP5 行+#59 硬契约)/§3.1(enqueue/effects/roles)。
- DP2:`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md` §1.4(DP4/DP5 行)。
- DP3:`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md` §1.4(DP4 行)/OQ1(token 七键)/OQ4(candidates 字段族与 spans 形态)/§3.1(artifacts CHECK 与守卫)/§3.2(v13_context_required 体)。
- 教程:`docs/tutorials/v13/chapters/07-artifacts-plane.md`(7.2–7.6;行号见 §6)。
- 仪式参照:`v12/indb/setup_db.py`、`v12/load.py`(DP1 §3.8/M1 转述;V13 路径)。
