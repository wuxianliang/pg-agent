# v13 上下文平面设计:Context on Postgres

> 状态:**草案 v2**(2026-09-19)。
> 输入:pgembed 新增 stannum/pg_typesafe 的功能画像、v13 教程 16 章、
> ContextPipe(VLDB'26 ADS)与 POML(Microsoft)两篇论文、Oracle 两轮裁决。
> 裁决状态:**轮 1 已完成**(gpt-5.6-sol / claude-fable-5 双通道);
> **轮 2 已完成**(ContextPipe×Jev 整合复核——ask_oracle 通道故障,经 agent_run
> 会话以同血统模型 cursor:gpt-5.6-sol@xhigh 代行;十五点改写已并入 §5/§6/§14)。
> 本文与教程冲突时:教程是讲解、本文是设计;实现规范冻结后以冻结稿为准。

## 0. 一句话

**上下文不是管线产物,也不是视图树,而是一份版本化的执行收据(context artifact + 装配清单);
谓词负责发现当前候选,manifest 负责证明当时发现了什么,artifact 负责固化实际交给模型的内容,
effect 负责跨事务执行;Jev 只产不可变、带版本的语义证据,动作授权独占于版本化 SQL 策略,
机器(排序/门控/装箱/渲染)永远是确定性的。**

## 1. 作用力(先于设计的事实)

关于运行环境,不关于偏好:

1. **BM25 是语料统计的函数**:IDF/avgdl 随 ingest 漂移,同一 SELECT 换个时刻换一批结果——
   视图只能尽力再生,永远不是审计来源。
2. **`==>` 的索引绑定依赖计划上下文**:plpgsql 静态 SQL 第 6 次执行起切 generic plan,
   预备语句同样;绑定不到索引时回落默认 tokenizer,**不报错,只静默漏召**。
3. **行锁只在事务内活着**,且 `FOR UPDATE` 与 FK 检查的 `FOR KEY SHARE` 互斥——
   持会话锁做 1.3–1.6s 的库内判断调用期间,连 `INSERT INTO events`(用户发言、cancel)
   都被挂起:这不是延迟问题,是干预面停摆。
4. **判断调用有成本且答案可缓存**;provider 前缀缓存按字节计费——
   一字节变化使后续前缀全部重算;排序同时影响注意力(lost-in-the-middle)。
5. **概率无恒等式**;Jev 数学弱、CJK 判断劣化、无生成能力。
6. **stannum 是 dev software**:fold/merge 持 meta 锁(插入毛刺)、新连接重建 buffer index、
   CJK 逐字切分、>1024 词项展开走保守回查、ranked 剪枝仅平坦 AND/OR、AGPL。
7. **崩溃可落在任何指令边界;外部 IO 与事务无原子性;队列 at-least-once。**
8. **压缩不是无条件省钱**(ContextPipe 实测):token −30% 但缓存命中 95.3→86.2、
   fresh 翻倍,盈亏平衡 cached/fresh 价格比 r\*≈0.145。

## 2. 底座能力画像

### 2.1 stannum(Lead fork,Rust/pgrx,dev software)

`CREATE INDEX ... USING stannum (col)` 后:`col ==> 'TINQL'` 谓词(词项/通配/正则/fuzzy
+ Boolean + 短语/邻近/span + boost)、BM25(`full_score/score/max_score/score_inspect`)、
并发下精确 `count(*)`、`highlight()`(与索引同 tokenizer)、`verify_index`(amcheck 风格)、
索引随行同事务提交(WAL)。限制见作用力 6。

### 2.2 pg_typesafe(C+libcurl,pre-alpha)

Jev(System One)原语的 SQL 化:Noul(是/否概率)、Choice(单选)、Score(rubric)、
ask(混编);`_many` 批处理(32/批、4 并发);GUC 含 `mock_response`(离线确定性)。
v12 G7 实测:`v12_decide_in_db` 一条 SQL 完成整个 decide,9 问 $0.000042,
库内调用持锁 1.3–1.6s。已裁不变量演化:**纯判断 IO(幂等/可缓存/廉价)可进事务
(且必须移出会话锁,见 §4.3);生成 IO 永远在 worker。**

## 3. 两篇论文的取与舍

| 取 | 舍 |
|---|---|
| ContextPipe:五段纯度边界、分位数预留、tier 阶梯(进 thresholds)、波动率排序、applied/skipped 双分支审计、SessionLatches、EmergentContext、缓存经济学、ForkPrefix、shadow 思想 | 自建管线 runtime(v13 用事务/函数/行得到同构物)、其 stats 子系统(用 SQL 派生,不建第二真相源) |
| POML:三遍渲染边界(manifest=IR / Writer=序列化器)、样式=版本化 render 策略行 | 标记语言、模板引擎(SQL 就是)、LSP/预览工具(远期可作 v13_explain 呈现层) |

映射:Plan=fold_state+策略行(STABLE 函数)、Bind=两阶段 advance 的解析相、
Optimize=装配 SQL+manifest、Execute=序列化+llm effect、Feedback=events/effects 自带 usage。
**两篇论文在应用层自建的管线,v13 用数据库原语直接得到;缺的只是 §5 的零件。**

### 3.1 三读法尺子(控制面完备判据;2026-09-21 控制面 R2 终裁新增)

控制面是否完备,用同一把尺子量:**每个读法的控制动词组(turn / 会话委托 / goal)都能在
同一组核心原语(effects/events/sessions/thresholds + parse+advance+settle)上闭合,
且不需要新的执行机制**。反面=为层次建服务——v11 已拒第二套调度面,v13 不重开。

同尺三行(R2 §4;裁决存证 `docs/reviews/v13-control-plane-oracle-r2-2026-09-21.md`):

| 尺 | 落点 |
|---|---|
| 动作闭集 | 四值不是 action;spawn=tools.kind='sql' 分派;triage 分类映射 llm/human/sql;**信封枚举不是动词,CASE 它的代码才是**(动作空间权威在教程 ch04,本文只引用不复制) |
| 谁在锁内写 sessions | 仅 advance 变更相(持父 FOR UPDATE)+ guard 具名闭集;worker/harness/子进程否 |
| 回执 | 库内动作=同事务事件+行;外部 IO=effect claim/settle |

推论:建会话只有一个动词实现(`v13_spawn_subsession`);repair 走事件不另造会话;
explore 首版同会话(不占深度=不是子会话)——三题在同一组原语上咬合(§6.8)。

## 4. 承重件(轮 1 已裁,双通道一致)

### 4.1 召回是函数,不是视图(P0 绑定纪律)

- 所有 `==>` 只许出现在 `v13_recall` 一族函数体内,经 EXECUTE(或 force_custom_plan)
  强制每次重规划,让 TINQL 串以计划期可见形态绑定到正确索引列。
- **三禁**:视图内嵌 `==>`、plpgsql 静态 `==>`、worker 预备语句直发 `==>`。
- 用户文本不得直接成为 TINQL——经受限 compiler(`v13_build_tinql`,长度/通配/正则/
  fuzzy/展开上限/执行超时全限)。
- Gate:EXPLAIN 只钉形状(FORMAT JSON 出现 stannum IndexScan、chunks 无 Seq Scan);
  **tokenizer canary**——索引 tokenizer 与默认切分不同的 fixture,召回必须命中,回落即红。
- 排序 `ORDER BY bm25 DESC, content_hash ASC`,并列截断确定性。

### 4.2 chunks 是可重建投影,三纪律(P1)

物化专用 chunks 行表(artifacts.inline 表达式索引被否:多 kind JSON 容器、绑定脆弱、
immutable 表上死 chunk 永久稀释 IDF):

1. **行自证**:`content_hash = sha256(body)` 列;gate 断言自证成立且
   `exists artifacts(content_hash, kind='chunk')`;`v13_rebuild_chunks()`(truncate+重灌);
   verify_index 进 gate + pg_cron 夜跑。
2. **重摄取=与新 artifacts 同一事务 delete by source_hash + insert**——索引随事务一致,
   无同步器、无失效协议。
3. **外部一律引用 content_hash,不引用 chunks 主键**——行会随重摄取死亡,
   manifest 与 decisions 只记 hash。

主键 `(source_hash, chunk_no)` 保留;跨源同文双行由判断缓存按 content_hash 吸收,
IDF 轻微失真实测超标再迁 content_hash 主键。

### 4.3 两阶段 advance(P0)

- **解析事务**(不碰会话锁):快照内 LEFT JOIN decisions 算缺口 →
  `pg_advisory_xact_lock(hash(查询×候选集))` → typesafe_ask 补齐 →
  `INSERT ... ON CONFLICT DO NOTHING` → 提交。并发重复解析付款被消灭。
- **变更事务**:FOR UPDATE 会话行,毫秒级,建 effect/路由/预算扣减——原五步原样。
- 同一 `v13_resolve_judgments()` 两种调用者:advance 内(上限=策略行,**单位是批**,
  默认 ≤1 批即 ≤32 问)与 worker 慢路(分批无上限)。双速=同一函数在两双手里。
- 角色分裂:recall 纯 SELECT(只读角色)、resolve 写 decisions+IO(写角色)、route 持锁变更。
- Gate:mock 下两连接实测「解析相期间 events INSERT 不被阻塞」;持锁时长断言;
  全命中零外部调用;生产断言 `typesafe.mock_response IS NULL`;
  resolve 超时不落行、事件计数防重试风暴(「放弃零 Jev 调用」的预算形态)。

### 4.4 三层记忆栈(P1,否决 events 直索引)

1. **结构化层**:stannum 建在 `decisions.question` 上(小、静、ASCII、低 churn——理想负载)。
2. **逐字层**:`transcript_chunks(session_id, seq 区间, body)` 投影表,tick 批量构建、
   可重建、构建时策展(只收 user/assistant);新鲜度=水印谓词(投影 max(seq) vs events
   max(seq))。**文档语料与记忆语料分区/分索引。**
3. **远程层**:摘要 artifact 是长程记忆的检索对象,已在本族机制内。

Gate:p99 events INSERT 延迟有/无投影构建对比断言;worker 长连接(连接预热税记运维注记)。

### 4.5 过滤管道:存在性 Noul 先行 + per-chunk Score(P1)

- 缓存键 per-chunk(`hash(问题, chunk.content_hash, query.content_hash)` + provider/model
  + rubric/answer schema 版本)⇒ 默认过滤器用 per-chunk Score/Noul(`_many`);
  **全集 Choice 与逐 chunk 缓存语义冲突**,仅留给「相对序本身是问题」的重排。
- 顺序:先一个**存在性 Noul** 闸住整批花费(语料无答案时 1 次调用替代 k 次),
  再逐 chunk Score。
- 跨 session 缓存:拆「规范答案缓存」与「本 session 使用记录」(reused_from 映射),
  复用旧行不把判断所有权留在旧 session。

### 4.6 CJK:构造器是 P1 真活,bigram 进台账

- 逐字切分下常用字 IDF 趋零——排序失灵是物理的,但候选池不漏就不死
  (质量来自过滤层,nano 已证)。精确 `count(*)` 让 k 随候选规模自适应放宽(策略行)。
- `v13_build_tinql(query_text)`:语言分段、CJK 语段一律短语引用——是代码不是字符串,
  gate 用 kohaku fixtures 钉混合查询形状。
- bigram 升级路径(台账):`GENERATED ALWAYS AS (v13_cjk_bigram(body)) STORED` 列 +
  独立 stannum 索引(独立列天然消歧绑定)+ 查询侧同一函数;
  代价明示:变换列 highlight 映射不回原文,CJK 退化为整 chunk 装配。
  触发条件:kohaku fixture 漏召率超阈值。

### 4.7 高亮跨度装配解放 chunk 尺寸(P1 红利)

chunk 可以粗(整节/整文档:BM25 文档统计更稳、行数更少),装配单元是被标出的跨度
`(doc, offsets)` 进 manifest。注意 BM25 长度归化稀释超长文档——目标尺寸由刻画 gate
用数据回答(先验 2–4KB)。跨度装配不能是唯一单元:可配置前后文窗口、句段边界、
表格/代码块完整性、重叠合并(Oracle 2 补充)。

### 4.8 stannum 性格刻画 stage(P1 排序纪律)

- **承重件(两阶段/压缩/过滤/五件套)不依赖 stannum 一根毫毛;可替换件关在刻画 gate 后。**
- 语料英文为主:tsvector T0 先跑通承重件,stannum 刻画完换 recall 函数 definition
  (目录行是数据,流程零改)。语料 CJK 为主:kohaku 类语料下 stannum 是救命
  (tsvector 默认 parser 把「東京タワー」当一个 lexeme,子串零召回)——直接 stannum T0,
  但仍先过刻画 gate。
- 刻画 gate 内容:fixture 灌入、`==>` 在 EXECUTE/视图/预备语句下绑定矩阵实测、
  fold 持锁 p99 压测、verify_index + REINDEX 演练、>1024 展开回落行为钉断言。

## 5. 五件套上下文平面(轮 2 综合,**待 Oracle 复核**)

> ContextPipe 的目录/清单/渲染/经济/反馈,关系化。多数层是既有表的视图;
> 新增的是两个概念件(latch/emergent)与三条经济学。

### 5.1 目录:生命周期即视图

ContextPipe 8 层(Immutable/Per-agent/Latched/Per-session/Per-turn/External/Emergent/
Feedback)多数映射到既有表(meta、tools、sessions、events、artifacts)。新增两表:

```sql
latches(session_id, name, value, fired_at)     -- INSERT once;UPDATE/DELETE 被触发器拒;
                                               -- 参与前缀身份哈希(§5.6;版本化
                                               -- latch 名单内,worktree 默认排除)
emergent(session_id, kind, content_hash, payload, expires_turn, consumed_at)
                                               -- UNIQUE(content_hash) 写时去重;
                                               -- CHECK 行数 ≤ cap(fail-closed 不静默丢);
                                               -- 消费=assemble 时 watermark 谓词
                                               --   (expires_turn > 当前 turn AND 未消费)
```

latch 语义:首触发即冻结(模型选择、缓存 scope 资格)——mid-session 漂移即隐性
cache-break,「一次性 DDL」的关系形态。emergent 语义:turn 中途发现(工具结果触发
新技能、预取完成)安全带入下一 turn:TTL=下一 turn、hash 去重、上限。
**轮 2 已裁:latch 为 P1 进核心**(保护 prefix identity);**emergent 表 P2 延后**
——出现首个真实 producer 再进。执法修正:跨行数量上限不能用 CHECK,由 admission
函数+事务锁执法;消费用 `target_turn + manifest membership` 表达,不用破坏性
`consumed_at`(失败重试不得丢数据)。

### 5.2 清单:manifest = IR

context artifact 内嵌装配清单,每 section:

```
(kind, cache_scope[Global/Session/None], priority[Never/First/Normal/LastResort],
 content_hash, est_tokens, payload_ref, churn 计数)
+ 查询侧:query_artifact_id、候选 content_hash/bm25/命中跨度/decision_id
+ applied 与 skipped 变换都落行(带原因)——审计两分支
```

三种「回放」显式区分:**exact replay**(读旧 manifest/context)、**recompute**
(旧策略×新语料)、**fresh fork**(新策略×当下语料)——不得混称。

### 5.3 渲染:render 是纯函数,呈现是策略行

`render(manifest, render_policy_version, provider) → wire bytes`。
per-model 呈现偏好(markdown/xml、列表样式、caption 形态)是版本化策略行——
POML 的 Writer 关系化:加 provider=加策略行+一个序列化器,装配逻辑不动。
**轮 2 已裁:首版只留一种 canonical render**;provider policy 只处理协议约束与
cache marker,模型呈现偏好在匹配评估证明收益前不进(臆断不立法)。

### 5.4 经济:压力、分位、缓存价

- tier 阶梯 = thresholds 路由带:`context_pressure BETWEEN lo AND hi → tier`
  (Normal/TrimSchemas/CompactHistory/AggressivePrune);压力是 fold_state 的 derived
  (T_used=Σest_tokens、L_eff 来自 meta、**R_o=percentile_cont over 该 (model,source)
  桶历史 llm effect usage**,p75 稳态/p95 恢复)。**轮 2 P0 修正:只升不降仅在
  单次 Plan 内成立**(同一 Plan 取 max(raw, predicted, recovery floor));跨 turn
  永久单调会让一次高压永久锁死 AggressivePrune——跨 turn 用 hysteresis/cooldown
  受控降级。0.60/0.75/0.90 只作 shadow seed,本地校准后才动作。
- 压缩前算 **E(r) = fresh + r·cached**:r 来自带生效区间的
  provider/model/account/cache-class 定价目录(manifest 记录 r 来源版本);
  OpenRouter 路由不确定时**不得用猜测的 r 决定压缩**——只按硬窗口与安全策略行动。
  r<r\*≈0.145 时压缩亏钱(ContextPipe 实测盈亏平衡点,写进默认策略注释)。
  注意 E(r) 只是输入成本代理,未覆盖摘要调用、输出与延迟;r 错误翻转的是账单
  选择,不影响正确性。
- cache-break 归因 = 逐 section content_hash 对上一 turn manifest diff——一条 SQL,
  不是启发式。

### 5.5 反馈:统计免费,失败不污染

usage 已在 events/effects;失败 turn 只写失败记录不进分位样本
(effect status 谓词)——防「prompt too long 恢复循环」被非响应样本毒化分位数。

### 5.6 ForkPrefix 关系化 + shadow 即查询

- fork 继承 context artifact + **前缀身份哈希**(system blocks+tool schemas+model+
  名单内 latches 的 canonical bytes SHA-256);**参与前缀身份的 latch 取版本化 latch
  名单,`worktree` latch 默认排除**(2026-09-21 R2/A19 修订,消除「所有 latch 参与」
  与 worktree 排除的矛盾);validate-spawn gate 拒绝破坏缓存身份的 fork
  (如 thinking 预算被 clamp 到不同档);cache probe=对比实际 cache_read 与携带估计,
  落一条审计事件。
- shadow 演出:新旧策略双跑 assemble,diff 两份 manifest,零 diff N turn 后 flip
  ——manifest 是行,这只是一个查询。

## 6. ContextPipe × Jev 整合(轮 2 已裁)

### 6.1 版本化证据与动作授权边界(原「边界原则」,轮 2 改写)

> **Jev 只产不可变、带版本的语义证据;版本化 SQL 策略独占动作授权;
> manifest 固化「证据 + 策略版本 + 最终动作」。**

类型化概率只让**已落库证据**可被确定性消费,并不让远端模型本身确定。
原提法「所有判断在解析相完成」已删——意图判断、摘要验收、答案效用分别发生在
Bind 前、变换后、Execute 后,不可能处于同一解析相。

**三个 epoch(最小不变量,轮 2 P0)**:

1. `pre-bind`:仅已有 intent 等前置信号;
2. `pre-finalize`:绑定后相关性、候选/摘要验收等动作承重判断;
3. `post-execute`:效用遥测——**只能影响后续 turn**。

配套四件:
- **manifest freeze**:final manifest 只消费 freeze 前状态为 complete 的精确
  `decision_id`;缺失、超时、review 带一律走版本化默认分支;迟到结果留在原
  request/epoch 下,仅供完全相同信封复用,**不得回写已冻结 manifest**。
- **快照复核**:解析事务记录会话事件水位(session_version/max_event_seq)与
  goal_hash、candidate_set_hash;变更事务拿锁后复核,不一致即弃批重解析——
  否则旧用户意图/旧候选集的答案会被用于新 turn。
- **版本化路由**:raw answer 不可变;threshold/policy 追加版本不覆盖;
  exact replay 用 manifest 中的旧 verdict,shadow reroute 才用新阈值重释 raw answer。
- 请求信封固定 template/model/schema/policy version。

### 6.2 六触点(轮 2 裁决)

| # | 触点 | 裁决 | 形态 |
|---|---|---|---|
| 2 | 摘要验收 | **P1 首版留**(摘要变换进首版时必须同时进) | SQL 选目标/LLM 生成/**确定性检查先行**/Jev 只验语义保真,不过阈值绝不采用 |
| 5 | 意图门控 Bind | **P1 条件留**(仅复用既有 intent 行;为此新调 Jev 则 P2) | 只软门控可选且昂贵的外部 source;低置信/CJK/缺失→绑超集,不得排除规则、当前消息、必要历史、工具配对 |
| 1 | 压缩优先级 | **P1 shadow-first** | 静态 priority 保留为硬类(保护级/可恢复性/结构约束),另加 `semantic_compact_hint`,仅在同可压缩类内且压力跨 tier 时参与候选顺序;goal_hash 必须是版本化目标 artifact |
| 4 | 效用遥测 | **P2 弱标签实验** | 有预算的分层采样(§6.3);未经反事实评估不得驱动线上策略 |
| 6 | 预取排序 | **P2 台账** | 长目标树+下一查询候选可预测才有收益;SQL 构造有界候选,Jev 可选重排,预取仍由 worker 执行 |
| 3 | Emergent 在线 triage | **砍在线路径** | overflow 是容量/并发控制问题:确定性 admission policy(TTL/kind 优先级/大小/时间/显式拒绝事件);Choice 必选一不能表达「全不要」,Noul 解决不了并发超卖,Jev 不可用时 overflow 仍须可处理 |

性价比排序:**2 > 5(仅复用时)> 1 > 4 > 6 > 3**。六触点都不是 v13 承重件 P0。

### 6.3 效用遥测的采样纪律(P2)

`P(used|present)` 不是因果效用:冗余 section、隐式使用、共同来源都会混淆。
当「免费真值」用会奖励善于被 Jev 看出表面重合的 section,而非真正必要的 section。

- 仅采样成功 Execute;失败/重试/恢复 turn 不采;
- 按 `section kind × tier × pressure band` 分层;稳定 hash 抽样,从 2% turn 起步;
  每采样 turn ≤2 个可选 section、≤1 个 `_many` 批;
- 阈值附近、首次出现 (answer_hash, section_hash, rubric_version) 与新 kind 过采样;
  记录 inclusion probability,离线加权纠偏;
- 配离线负对照与 section-removal 配对评估——否则只能称「Jev 认为有支持关系」,
  不能称效用;
- 每 session/每日/每策略版本硬预算;未经 held-out 校准不进线上 priority 或 Bind。

### 6.4 摘要验收回退链(P1 规范)

1. SQL 先判本轮是否允许 summary,并**预留「生成+验收」完整预算包**——预留失败
   直接 drop/spill,生成与 Jev 都不调;
2. 生成摘要 artifact;
3. **零模型成本检查先行**:非空、确实缩短、受保护 ID/路径/数字/工具配对仍在、
   结构合法、未超预算——失败不调 Jev;
4. 通过后查缓存或调一次 fidelity Noul:accept band 采用;review/reject/缺失/
   超时不采用;
5. 仅当预先允许第二个完整预算包时重生成一次并重验——不能只重问相同摘要;
6. 仍失败按固定链:spill/clear 可恢复工具结果 → drop oldest 完整可压缩 round →
   策略允许的最终裁剪;全部写 applied/skipped trace;
7. CJK 摘要在专门 fixture 校准前,Jev 不单独放行——只可附加拒绝信号;
8. 措辞纪律:**放弃分支零「新增」Jev 调用**,不是绝对零成本
   (已超时/失败的调用可能已计费)。

### 6.5 判断请求信封(原「递归件」,轮 2 砍完整递归)

「判断请求也怕 churn」成立,但不推出再建一套 Plan/Bind/Optimize/Feedback。
保留信封六件:template/version、canonical projected state、question batch、
budget/timeout、request_hash+provider/model、usage+provenance。
usage 属于一次 batch/call,不复制到每条 decision 重复计费。

> 「所有 LLM 调用走同一条管线」修正为:**所有生成调用走上下文装配管线;
> 所有 Jev 判断走统一 judgment resolver;二者共享 artifact/effect/审计/版本纪律,
> 不共享优化器。**

**分片哈希(P1 条件启用,启用门槛 P0)**:全量 request_hash 是安全默认
(正确但命中率低);观测到缓存损失后才启用投影分片。启用时:
- 读取声明放不可变 `judgment_template_version`(模板/题型/criteria/answer schema/
  允许暴露的 state projection/provider/writer/canonicalization 版本);
- 请求行物化精确 projected state;request_hash 由**实际发送给 pg_typesafe 的同一
  payload builder** 生成——decision 只记引用,不复制声明(防漂移);
- **最小可见性执法:未声明字段根本不进请求**——不是审计思维,是封死;
- Gate:改未声明字段→projected bytes 与 hash 不变;改声明字段→变化;
  未声明字段放 canary→出站 payload 中不存在;hash 输入与实际 payload 逐字同源;
- **批处理约束**:一个 typesafe_ask 的所有问题共享同一 state——不同 projection
  的问题按 projection 分批(_many 并发)或整批用联合投影按联合 payload 哈希;
  **不得发送联合 state 却按题局部分片复用答案**。

### 6.6 shadow 重路由的适用边界

判断是缓存行 ⇒ 新阈值带对历史 decisions 重放=JOIN,**零新增 API 成本**
(非零计算成本;不能补出新模板、新输入或反事实质量标签)。
限定:同模板、同输入语义、raw answer 完整时才成立。

### 6.7 不整合清单(轮 2 扩充)

tier/压力/预留分位(算术,SQL 地盘)、cache-break 归因(hash diff 已确定)、
摘要生成(LLM 地盘)、section 排序(缓存正确性来源)、组合置信度(无恒等式)、
**Jev 决定 cache scope/marker、Jev 覆盖结构校验、protected sections 硬删除、
在线 learned policy、迟到结果修改已冻结 manifest**。

通用整合姿势:**SQL 先短路确定情形,Jev 只裁不确定带**;每个模板配语言、
校准与漂移 gate。

### 6.8 控制面信封族(2026-09-21 控制面 R2 终裁,A15)

> 动作空间权威在教程 ch04 的 `v_routes` 动作闭集——本文只交叉引用、不复制
> (信封枚举不是动词,CASE 它的代码才是)。裁决存证:
> `docs/reviews/v13-control-plane-oracle-r2-2026-09-21.md`(下称 R2)。

信封族全住 `artifacts.kind` + pg_jsonschema + `tools.input_schema`,零新表零新列(R1 共识 1)。

**(i) harness_result 四值 result_kind 合同(A15)**

分层词表(规范,R2 §1.1):

| 层 | 字段 | 词表 | 谁读 |
|---|---|---|---|
| harness 原始输出 | `candidate_kind` | 开放(harness 土话) | 仅合同校验器 |
| **settle 分派键(权威,持久化)** | `harness_result.result_kind` | **四值** `progress\|finish\|wait\|reject` | `v13_complete` / 下一格 parse+advance / `v_routes` 消费侧 |
| 对照注释 | `delivery_kind` | LoopX 六值,可空 | 审计/对照/人;**路由不读** |
| fold 信号 | `events.type` | `repair/required`、`replan/required`(开放词表,ch01) | 后续 triage / recover_idle / attention |

四值是相对复核缝 B 三值(finish/reject/wait)的**新增立法**(加 `progress`):
无 progress 则 VALIDATED_PROGRESS 只能误用 wait(语义相反)。

语义表(规范,R2 §1.2):

| `result_kind` | advance 行为 | material spend(同 logical_turn_id ≤1 次) | 可伴随事件 |
|---|---|---|---|
| `progress` | 不终结,下一格 parse+advance | **是,除非同批存在 repair/required 或 replan/required**(真进展不附修复信号;防「progress+repair」双义) | 可带 repair/replan |
| `finish` | 走验收门;过则 closeout completed | 是 | 禁止 repair/replan |
| `wait` | 零新 harness/llm/tool effect;`wait_reason=approval` 时恰建一个 human effect | 否 | 可带 repair/replan |
| `reject` | closeout failed | 否 | 禁止把 unknown 伪装成 reject |

- `wait_reason ∈ {approval|evidence|quota}` **normative**(进 pg_jsonschema;缺省非法)。
  approval 的 wake=human settle;evidence/quota 必带**机器可判定 wake condition**
  (事件类型/not_before/artifact 到达/子终态),缺失 → `v13_complete` 拒收。
- `USER_ACTION` 不设独立 result_kind:并入 `wait+wait_reason=approval`;该 turn 若出现
  `delivery_kind=USER_ACTION_REQUIRED` 则**必须**同时 `result_kind=wait` 且
  `wait_reason=approval`,审批 interaction_ref 必填,缺则拒收。两条 gate 并存不矛盾
  (§10):信封校验在 settle 入口(`v13_complete`),路由盲读在校验通过之后——
  `delivery_kind` 其余值乱填/置空不影响分派与建 effect。
- `VALIDATED_COMPLETION`(delivery 对照)仍须过 session acceptance gates,harness
  不得单方面 closeout;candidate→accepted 验证链保留(§6.1「版本化 SQL 策略独占动作授权」)。
- **wait 三层消歧(教程必修)**:`sessions.status='waiting'`(会话等外部)≠ advance 返回
  `'waiting'`(本格已建 effect)≠ `result_kind=wait`(本格零新 harness/llm/tool
  effect,`wait_reason=approval` 时恰建一个 human)。
- repair/replan 异步 fold:repair/required → 下一格路由既有 `sql`(库内修复)或 `human`
  (超限);replan/required → 路由既有 `llm`(重 triage/编排)或 `human`。上限=thresholds 行
  (`harness.repair_count`/`harness.replan_count` 信号,按 ch04 既有信号命名风格)+ 本会话
  事件计数 fold,带满 → human 或 reject;recover_idle 可把未消费 repair/replan 视为
  可恢复工作输入,不建修复状态机。gate 见 §10 G-ctx10 族。

**(ii) harness_request / 续跑 / 审批两段(R1 共识 2/3)**:续跑=新 effect_id+新冻结
request(同 effect_id 换 request 再 attempt 被禁);审批两段=harness effect 以
succeeded+需审批信号终态化 → human effect → 续跑 effect(mode=resume)。
合同细则见教程 ch07/ch12。

**(iii) handoff 信封(R1 共识 4)**:artifacts 载荷+稳定 `delivery_id` 幂等(重复投递
不得二次注入);transcript 存 manifest/hash 引用,不复制正文;不采 XML。

**(iv) spawn 档位(交叉引用,A17)**:`tools` 行 `spawn_subsession` `kind='sql'` +
`v13_tools_guard` 具名 VOLATILE 例外 + 父 advance 同事务批量扇出;与 `v13_fork` 同一
primitive,sessions 唯一写路径。并发 sibling 争根预算的防超售:spawn 准入前先取
**根事务咨询锁** `pg_advisory_xact_lock(<spawn_budget 类号>,
hashtext(root_session_id))` 再算准入(两参形式分 lock class,与 §4.3 解析相
hash(查询×候选集) 咨询锁互不串扰;ch01/ch13 sessions DDL 无 reserved 列,
单语句 CAS 方案作废。仅 spawn 准入路径持此锁,closeout/recover 不得取;
不加 root **行**锁序——咨询锁是锁图中的命名节点,预算写路径按同一 root
key 取锁,顺序一致无环)。合同细则见 ch06/ch14 与 DP1 A17 修订。

**(v) triage(交叉引用,A20)**:信号集分 10a/10b 两级最小集 + 单一 `goal/override`
事件(载荷 `intent ∈ {direct,decompose}`)+ module 数后置(首版不进;§11 步骤 3 后
先加 `candidate_source_count`,版本化 module_key 存在后才加 `candidate_module_count`)。
细则见 ch01/ch04/ch05/ch13 与 A20;`thresholds.action` 闭集不变(§3.1)。

**(vi) P1 控制面机器形状（2026-09-26 R3/R3a/R3b，stage 17）**

生产者是目录行 `harness_turn`（`kind=tool`）。request 六键闭集：`tool`、`params`、`handler`、`tools_revision`、`logical_turn_id`、`continuation_index`。唯一盖章点是 `v13_advance`（已持 session 锁、`v13_enqueue_effect` 之前）。续传不经 `v13_route`：advance 在锁内直接入队下一枚 harness，并先写 `turn/route`，payload 恰 `{action:tool, reason:harness_continuation, tool:harness_turn, params:{}}`。

`harness_result/v1` 十键闭集住策略行 `harness_result_schema`（draft-07，`pg_jsonschema`）。`wake` 四变体严格 one-of。`v13_wake_is_satisfied_v1` 为 VOLATILE（`not_before` 用 `clock_timestamp()`，不用 `now()`）。三注解键默认（R1/设计无字面类型）：`harness_session_ref` 1..256、字符集 `[A-Za-z0-9_./:-]+`；`resume_token` 1..512；`partial` boolean。三者可缺席、禁 null，与 `delivery_kind`、`content_hash` 一并盲读。

closeout 收据顶层键：`schema_version`、`origin_user_seq`、`spent`（`turn_no` / `cycle_no` / `max_cycles` / `material_count`）、`produced_hashes`、`children`（P1 恒 `[]`）、`unconsumed` 五数组、`state_hash`、`turn_end_reason`。`state_hash` 是 jsonb 数组 `::text` 的 sha256；印章三 type 不进第四段。活体 ⑤ 不写 `turn_no`，closeout 禁止对 `turn_no` 赋值，只抄已提交值。

P1 边界：`children_terminal` 在 schema 通过后仍 RAISE `children_terminal requires stage 18`；未满足的 evidence/quota wait 保持 `waiting`，唤醒者是驱动重调；fold cap、`closeout/inbox_residual`、steer 正文、`quota/spent` 不在 stage 17。

## 7. 检索分层(T0/T1/T2 重排)

| 层 | 形态 | 触发 |
|---|---|---|
| T0 | 语料英文:tsvector 起步→stannum(刻画后);语料 CJK:stannum(刻画后,救命件) | 默认 |
| T1 | stannum + vectorchord 混合(RRF 一条 SQL);嵌入=派生缓存行(content_hash×model),embed=effect | 固定评估集证明 lexical 漏召 |
| T2 | duck worker 批量分析/重嵌入(RSI) | 退出在线检索,只做离线 |

## 8. 扩展取舍台账

| 扩展 | 裁决 | 理由 |
|---|---|---|
| pg_jsonschema | P1 进 | effect args/result、decision answer、manifest 形状校验;schema 版本化不可变 |
| pg_cron | P1 进(扫地僧) | tick/投影构建/verify_index 夜跑;调度是行;**不是节拍器**——turn 推进仍靠 settle |
| pg_net / pgsql_http | **P0 排除** | 第二 IO 通道=effect 纪律旁路(无 fence/lease/unknown);无 mock;v1 之死的复活形态。台账写明:**库内 IO 例外有且仅有 pg_typesafe 纯判断** |
| timescaledb | 排除(台账) | 此规模无可替之物;触发:events 量级与保留窗口真实出现 |
| age | 排除(台账) | lineage/目标树是递归 CTE 两行的事;第二查询语言的税 |
| vectorchord | T1 触发(台账) | 见 §7 |
| psql_bm25s | 被替代 | stannum 是其超集(索引化、事务一致) |

**元原则(写进第 15 章)**:扩展进核心仅当三条全满足——(a) 替代掉仓库否则要自己
写并测试的代码;(b) 保住 gate 的确定性与可 mock;(c) 不制造第二真相源或第二 IO 通道。

stannum runbook:索引可丢、基础行不可丢(artifacts 是真相);连接池预热、fold 毛刺、
升级、REINDEX 演练、AGPL 分发审查。

## 9. 表结构增量汇总

既有骨架不动(sessions/events/effects/decisions/thresholds/tools/artifacts/meta…)。
增量:

```
chunks(source_hash, chunk_no, body, content_hash=sha256(body), corpus,
       chunker_version, analyzer_version)      -- 可重建投影,三纪律
transcript_chunks(session_id, seq_from, seq_to, body, content_hash)  -- 记忆逐字层,水印
latches(session_id, name, value, fired_at)     -- INSERT once(P1 进核心,轮2 已裁)
emergent(...)                                  -- TTL+去重+上限(P2 延后;admission 函数执法)
judgment_templates(版本化模板+projection 声明) -- 判断请求信封(轮2 新增)
manifest(context artifact 内嵌 jsonb)          -- §5.2 字段族
策略行:context_budget 三桶配比 / filter 批上限 / tier 阈值带 / E(r) 的 r /
        render_policy(版本化) / recall_boosts(建但为空,留缝)
```

## 10. Gate 清单(草案)

```
G-ctx1 两阶段:mock 下两连接实测解析相不阻塞 events INSERT;持锁时长断言;
              全命中零外部调用;并发重复解析仅一次付款(advisory lock)
G-ctx2 投影:chunks 行自证;重摄取同事务一致(插入即可检);rebuild 幂等;
              verify_index 通过;p99 events INSERT 无回退
G-ctx3 召回:==> 绑定矩阵(EXECUTE/视图/预备语句)全绿;tokenizer canary;
              TINQL 注入被拒(fail-closed 信封);count 自适应 k 生效
G-ctx4 过滤:存在性 Noul 先行;同 query×chunk 二次零外部调用(mock 计数);
              per-chunk 缓存跨 session 复用(reused_from 正确)
G-ctx5 清单:manifest 含 §5.2 全字段;applied/skipped 双分支;三种回放可区分;
              ORDER BY 确定性(并列截断不抖)
G-ctx6 经济:tier 只升不降=单 Plan 内单调,跨 turn 走 hysteresis/cooldown
              受控降级(§5.4);R_o 分位数计算正确;E(r) 分支可观测
G-ctx7 分片哈希:声明路径外字段变化不击穿缓存;声明与实际读取无漂移(待设计)
G-ctx8 崩溃:解析相中途 kill→事务回滚→advance 幂等重推;摘要验收不过→drop 回退链
G-ctx9 证据/动作:manifest freeze 后迟到 decision 不得回写;水位不一致弃批重解析;
              分片哈希 canary(启用时)——未声明字段不出现在出站 payload
G-ctx10-envelope 信封校验(路由前):USER_ACTION_REQUIRED 必伴 result_kind=wait+
                wait_reason=approval+interaction_ref,缺任一 → v13_complete 拒收
G-ctx10-delivery 路由盲读(校验通过后):其余 delivery_kind 值乱填/置空,同
                result_kind 下 v_routes 输出与是否建 effect 逐字节相同。
                两条 gate 并存不矛盾:校验在 settle 入口,盲读在校验之后
G-ctx10-wait-lexicon:三层 wait 各自断言——result_kind=wait 的 turn 零新
                harness/llm/tool effect(wait_reason=approval 时恰建一个 human
                effect);advance='waiting' 的 turn 恰有一个 ready|claimed;
                sessions.status='waiting' 的会话 wake 前零自动推进
G-ctx10-wake:wait_reason=approval 的 wake=human settle;evidence/quota wait 必带
              机器可判定 wake(事件类型/not_before/artifact 到达/子终态),
              缺失 → v13_complete 拒收
G-ctx10-spend:同 logical_turn_id material 次数=1;progress+repair/replan 同批零
              spend;超限 repair 后零新 spawn、走 human/reject。
              stage 17 标注:超限 repair 不在本期(归 P4)。本期只断言 finish 与无
              signal 的 progress 各记 1、同批 signal 记 0、同 source 重放不第二扣、
              另一 effect 复用同一 logical_turn_id 时 RAISE 且收据仍为 1
G-ctx10-logical-turn:首枚六键 idx0;ready 期间二次 advance 零新行;failed 后同
              route 同 effect_id fence+1;material 后新 uuid idx0;续传不经 route,
              reason=harness_continuation
G-ctx10-wake 增补:四变体正负例;children_terminal P1 拒收;重复 advance 恰一条
              wake/satisfied;stale/replay 先于 schema 错误
G-closeout(A16):三终结事件的收据五字段(spent/produced hashes/children 汇总/
              unconsumed/state_hash)、session 终态与预算终态同一事务;closeout
              本身不再扣预算;子 closeout 不持子锁写父事件;前置 fail-closed——
              active effect=0/unknown=0/pending human=0/子树全终态,任一不满足
              → 终态不落(ch12 cancel 路径同前置复用)
G-sql-write-closed:具名闭集外 VOLATILE sql 工具 enable → 红;write_targets 缺键而
              VOLATILE → 红;prosrc 含 IO 通道(dblink/pg_net/COPY PROGRAM)→ 红;
              UPDATE tools 扩 guard 名单被拒(扩员=guard 源码+设计修订+部署 gate 同发)
G-ctx1-spawn:spawn 全程在 advance 变更相事务内(父 FOR UPDATE 已持;零入队、
              禁止 worker 在 claim 窗口写控制面);持锁时长上限沿用 G-ctx1 毫秒级
              口径,超限改函数/索引、不得改回队列「自愈」;不加多会话锁序
              (spawn 只用已持父行锁;禁止持 child 锁再锁 parent)
G-spawn-unique-writer:非名单函数/角色 INSERT sessions → 拒;harness fake 自插
              sessions → 红;批量子同属唯一写路径(经 v13_spawn_subsession 同事务)
G-spawn-fanout:N tool_call 一格建 N 子;每子回执四件套(child 行+forked 事件+
              child-created 事件+reservation 载荷)同事务,缺任一 → 红;预算不足
              全不建(fail-closed 零部分建);并发 sibling 压测无超售;同 source
              tool_call id 重放返回同一 child(request hash 匹配,不匹配 → 拒)
G-triage-action-closed:thresholds.action 仍属闭集;explore_then_retry/orchestrate/
              decompose 永不出现;Jev Choice 三值(direct/decompose/human)+策略标签
              explore_then_retry 只作 decision context/策略标签,不是第四分类;
              override=decompose 映射既有 llm 编排(工具面含 spawn),不新增动词
G-triage-review-band:再次 review(已探索过)→ 版本化默认策略行——种子=根
              human/子 direct,永不默认 decompose(ch04 §4.5)
G-triage-explore-once:根上 review 带且未探索过 → 恰一次同会话只读 explore
              (零 spawn、不占 ancestor_depth/subtree_reserved);已探索仍
              review 带 → 版本化默认(ch04 §4.5)
G-triage-explore-depth:超深(depth≥max_spawn_depth)零 explore child;P2 explore
              child 走完整 spawn 准入(depth+1,超深不豁免);首版同会话 explore
              零 spawn、不占 ancestor_depth/reserved
G-triage-evidence-hash:explore_evidence_hash 变 → request_hash 变 → 新 decision 行;
              不复用旧 verdict;不改写 candidate_set_hash(探索证据不是召回结果)
G-triage-10a-null-tree:10a 树字段 null 不点火(null≠0);根+无 override 不得静默
              direct(走 human);超时/缺失 decision 不落行,根→human、depth≥1→
              direct、零 child;override 打穿硬安全 → 零 child+human/waiting
```

## 11. 交付排序

1. **承重件先行**(不依赖 stannum):两阶段 advance、过滤管道(存在性 Noul +
   per-chunk Score)、**全量 request_hash(安全默认)+ 判断信封**、manifest 骨架
   (含 freeze/水位复核/三 epoch);
2. **stannum 性格刻画 stage**(并行):fixture/绑定矩阵/fold 压测/REINDEX 演练;
3. 刻画通过后换 T0 recall definition;chunks 投影 + 三纪律;
4. 五件套经济学件(tier 带/分位/E(r))与**摘要验收链(触点 2)**;
5. latch(轮 2 已裁 P1 进核心)、intent 软门控(仅复用既有 intent 行)、
   压缩 hint shadow-first;分片哈希=观测到缓存损失后条件启用;
6. T1 vectorchord、bigram、boost 闭环、语义决策缓存——全部台账触发。

**控制面修订(A15–A21,2026-09-21 R2 终裁)与上述承重件步骤并行推进、不互相
阻塞**(实施顺序见 R2 §9);其中 triage 的 candidate module 数信号**不得早于
步骤 3**(T0 recall+chunks 投影)——步骤 3 后先加 `candidate_source_count`(纯 SQL
聚合已落行,禁新解析相 IO),版本化 module_key 存在后才加 `candidate_module_count`
(§6.8(v))。

## 12. YAGNI 台账(附触发条件)

| 项 | 触发条件 |
|---|---|
| boost 反馈环闭环 | 离线 held-out 指标证明收益 + 词项自查可用(stannum tokenize() 待核实)或漂移 canary |
| CJK bigram 列 | kohaku fixture 漏召率超阈值 |
| 全集 Choice 重排 | 相对序本身成为问题的用例出现 |
| 语义决策缓存(decisions.question 近义检索+Noul 等价确认) | 判断缓存费用成为账单大头 |
| 工具目录检索 | 目录摘要装不进 decide 上下文那天 |
| T1 vectorchord | 固定评估集证明 lexical 漏召 |
| timescaledb / age | events 规模/图遍历需求真实出现 |
| 预取排序(触点 6) | ch13 长目标树落地且下一查询可预测 |
| 效用遥测上线驱动策略(触点 4) | 反事实评估(section-removal 配对)证明信号质量 |
| Emergent 表 + 在线 triage | 首个真实 mid-turn producer 出现(triage 永远走确定性 admission) |
| 分片哈希 | 全量哈希下缓存损失实测超标 |
| pg_cron tick | 扫描恢复的空转成本实测超标 |
| LoopX 六值升格 result_kind | 闭集修订触发:delivery_kind 审计链在实践中无人写(退化),或 progress+repair 零扣被用于免费进展刷 turn(R2 §7 复访条件) |
| rich rubric 9 项进 triage 硬路由 | 首版仅 Choice{direct,decompose,human}+confidence;rubric 项先作 shadow/中间带特征,判别力经实测证明后升格 |
| candidate_module_count 进 triage 信封 | 版本化 module_key 存在;先决=步骤 3 后先加 candidate_source_count(§11) |
| explore 走 spawn(只读 explore child) | P2:同会话 explore 不敷用(隔离/并行需求实测);升格走完整 spawn 准入(depth+1,超深不豁免) |
| v_goal_tree/看板物化 | 查询 p95 超标(A21 先参数化 STABLE SRF,非 VIEW 非物化) |

## 13. 教程修改清单(16 章映射)

- **第 5 章**:advance 改两事务;三角色分工入文;G-ctx1 断言。
- **第 7 章**:chunks 投影三纪律入「硬性规定」;manifest 指针。
- **第 10 章**:T0 前插「stannum 性格刻画」;「召回是函数」+三禁;装配清单 schema;
  存在性 Noul 先行+per-chunk Score;跨度装配与 chunk 尺寸解耦;v13_build_tinql。
- **第 13 章**:tick=pg_cron 扫地僧;预取排序进台账。
- **第 14 章**:ForkPrefix 关系化(前缀身份哈希/validate-spawn/cache probe);
  三种回放语义。
- **第 15 章**:扩展取舍台账+元原则三条;本文指针。

## 14. 轮 2 裁决记录(十问全部已答,结论并入正文)

1. latch P1 进核心(护 prefix identity);emergent 表 P2 延后——admission 函数+
   事务锁执法上限(非 CHECK),消费用 target_turn+manifest membership(非破坏性
   consumed_at)→ §5.1。
2. tier「只升不降」仅在单次 Plan 内;跨 turn hysteresis 受控降级;0.60/0.75/0.90
   只作 shadow seed → §5.4。
3. 分片哈希:声明放不可变 judgment_template_version;最小可见性执法(未声明字段
   不进请求);批处理约束(共享 state);启用门槛 P0 → §6.5。
4. 采样:2% turn 起步、分层、≤2 section、≤1 批、inclusion probability 纠偏、
   离线负对照 → §6.3。
5. 回退链八步:完整预算包预留→确定性检查先行→一次验收→至多一次完整重试→
   固定降级链;「零新增调用」≠绝对零成本 → §6.4。
6. 首版只留单一 canonical render;呈现偏好在评估证明收益前不立法 → §5.3。
7. r 来自带生效区间的定价目录,manifest 记来源版本;路由不确定时不用猜测 r
   决定压缩;r 错误翻转账单不翻正确性 → §5.4。
8. 性价比:2>5(仅复用)>1>4>6>3;首版只承诺摘要验收(+复用 intent 软门控)→ §6.2。
9. 最好整合=「SQL 短路确定情形,Jev 只裁不确定带」+每模板语言/校准/漂移 gate;
   必须拒绝:Jev 决定 tier/cache scope/marker/物理排序/硬预算/protected 硬删除/
   在线 learned policy/迟到回写 manifest → §6.7。
10. §6 已按十五点改写;可升级为「已裁」:证据/动作分离、三 epoch、manifest
    freeze、摘要验收链、软 intent、有界压缩 hint、效用遥测 P2、在线 triage
    排除、分片哈希条件启用、判断信封取代递归、shadow 重路由边界。

**遗留开放项**(非阻断):stannum `tokenize()` 自查函数是否存在(关系 boost 台账);
r 定价目录的维护流程;效用遥测反事实评估的 fixture 设计。

---

## 附:裁决记录

| 轮 | 日期 | 通道 | 状态 | 要点 |
|---|---|---|---|---|
| 1 | 2026-09-19 | gpt-5.6-sol(xhigh) | 完成 | 总裁决「执行收据」;manifest/两阶段/chunks 三纪律/三层记忆栈/per-chunk Score/H 扩展表 |
| 1 | 2026-09-19 | claude-fable-5(max) | 完成 | 「召回是函数+三禁+canary」;承重件与可替换件分离;highlight 解放 chunk 尺寸;boost 留缝;pg_cron 扫地僧;元原则 |
| 2 | 2026-09-19 | agent_run·cursor:gpt-5.6-sol@xhigh(代行:ask_oracle 通道故障,MCPToolExecutionCancelledError×6) | 完成 | 边界改写为「证据/动作分离」+三 epoch+manifest freeze;触点 2 首版留/5 条件留/1 shadow-first/4 降 P2 弱标签/3 砍在线/6 台账;分片哈希条件启用;判断信封取代递归;tier 单调性 P0 修正;latch P1/emergent P2;render 首版单一;E(r) 定价目录 |
