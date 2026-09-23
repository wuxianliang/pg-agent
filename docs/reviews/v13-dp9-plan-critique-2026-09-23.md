# v13 DP9 计划 Critique —— 对 `docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md` 的聚焦评审

> 评审对象:计划正文(草案 v3,双通道裁决已并入)+ 基线 `prompt-exports/oracle-plan-2026-09-23-145740-dp9-2e23dc-e0c1.md` 的 **Generated Plan** 段(该文件开头的 composed prompt / selected-file dump 仅作上下文,不作为计划内容)。
> 评审日期:2026-09-23。范围:仅 5 类问题(①导出有而计划丢/弱化/泛化;②欠定接缝/未决/矛盾/错引/缺依赖;③代码反证或更简设计可替;④两边都缺的运维/生命周期/失败/可测性;⑤会改变设计或实施顺序的问题)。
> **明确不复核**:已由用户批准的两项(`mgraph_consolidate` 新 kind;B1-scope 冻结=本 DP 不动 manifest/装配),以及两轮裁决后**有意删除**的未选支 DDL(OQ1-B AGE 支、OQ2-B2 支、OQ8-B2 支、OQ11-B 支)。下列每一条都只核验「存活决策的机制、gate、失败行为是否保住 specifics」。
> 代码事实均经 `v13/*.sql` 实地核对(file:line 已复验);未见 `v13/mgraph/` 目录,greenfield 判断成立。

---

## 0.  Executive summary(按严重度排序)

| # | 严重度 | 一句话 |
|---|---|---|
| S1 | 高 | §2.2/附录 C.2 把 `v13_resolve_judgments` 活体钉在 `envelope:623-852`——**错**,活体是 `filter:603`;`typesafe_ask` 活体调用点是 `filter:716`(在 resolve 体内),`filter:329` 才在 `v13_filter_ask` 里。这正是计划自己阻塞点 1 警告的失礼。 |
| S2 | 高 | B1 下读环**没有任何生产调用方**,§3.5 的触发者只写「驱动(会话无活跃 effect)」;导出里唯一说明「扫地不靠 pgmq」的 rationale 被删,`memory_walks/rounds` 无保留策略、无终态。 |
| S3 | 高 | OQ7 把候选池钉成「全会话 episodic 节点」⇒ consolidation 产物永不做锚;而 §3.4⑥「一条 `origin='consolidation'` 的子型边」**未给 src/dst/rel**,DP 头条(远程层首个载体)的可达性未钉也未 gate。 |
| S4 | 中 | `source_at`「来自源事件」但 `transcript_chunks` **没有时间列**,唯一来源是经 FK 回到 `events.at`;计划未点名该 join,而不变量 8 禁 `now()`。 |
| S5 | 中 | `judge_spend` 数的是 `judgment_calls` **行数=ask 批数**,不是问数;README「O(4N+10N) 问计入 512」量与单位都错(≈11 批/新节点 ⇒ ≈46 个节点触顶),且 `calls_used` 应点名取活体返回的 `asked_batches`。 |
| S6 | 中 | fail-loud 不一致:`admission_enabled=true`→V3009,而 `consolidate_mode='every_n'` 静默无效,`nodes_since_consolidate` 永不自增。 |
| S7 | 中 | 重建删除规则两个版本冲突(导出「两端都不是 consolidation 的边」vs 计划「`origin<>'consolidation'` 的边」),只因候选池 episodic-only 才偶然等价;不变量 6 被窄化。 |
| S8 | 中 | 节点 PK 按 `content_hash` + `ON CONFLICT DO NOTHING` ⇒ 同文两行 transcript 折叠,**增量与全量重建可能给出不同 `source_at`**,动摇 D4 字节级相同。 |
| S9 | 中 | 固化 enqueue 闸写成「沿用摘要闸」但实际是 `ready\|claimed\|unknown`,摘要只查 `ready\|claimed`;后果(session 一旦进 `unknown` 墙永不能固化)未记录。 |
| S10 | 中低 | 确定性路由「其余桶保持 `deterministic_floor`」在计划里只剩 CJK/superset 一处置引,E1 手算夹具无法复现。 |
| S11 | 中低 | 快照闸门只覆盖 `question`,未覆盖 `criteria`(ASCII 有 CHECK、属上游内容)。 |
| S12–S15 | 低 | 丢了 3 个函数签名;cgr「bump 一次」不成立;丢 2 条便宜 gate;2 处引用不精确。 |
| S16 | 信息 | 前序 stage gate 结构上不可能加载 mgraph,M4 的回归纪律只护住 `load.py` 一行。 |

---

## 1. 导出有、计划缺失/弱化/泛化的实现性内容

> 只核验「存活决策的机制、gate、失败行为」是否保留 specifics;已删未选支不计。

### 1.1 丢了三枚函数签名(计划 §1.3 / §3.4)

| 导出 | 计划现状 | 影响 |
|---|---|---|
| `v13_mgraph_neighbors(sid, hash, rels[], limit)`,普通 SQL,`ORDER BY structural DESC NULLS LAST, dst_hash ASC`(OQ1-A 接线) | 只剩函数名+排序句,**`rels[]` 与 `limit` 两个入参消失** | §3.4 的「桶→rel 映射」没有单一端口承载;实现者极可能再加一个 `neighbors_all` 变体,直接违反导出 §3.4「只有 `v13_mgraph_neighbors` 知道存储是表还是 AGE」这条已定死决定。**修**:把签名写回 §1.3-OQ1 机制段。 |
| `v13_mgraph_route(query) → {mode, weights}`(OQ3-A 接线) | 未出现,§3.4 只描述行为 | route 阶段的出口契约(谁产 weights、什么形状)没有载体;`routing_mode='jev'` 支也少一个可测入口。 |
| `v13_mgraph_should_stop(walk_id) → {stop, reason}`(OQ2 共同形状) | §3.4 只有四条排序规则 | 停止是「读已落库四条 Noul」的动作面;缺签名则 E4/E5 无法对准一个稳定入口,「缺停止判断不进①②」也无落点。 |

（保留良好的对照:`v13_mgraph_entities(body)→text[]`、`v13_mgraph_candidates`、`v13_mgraph_defaults_action(point,state)`、`v13_mgraph_policy()`、`v13_mgraph_structural_reach(sid,hash,depth)` 均留下。）

### 1.2 丢了两条本来便宜且可执行的 gate

| 导出 gate | 计划 | 为什么可惜 |
|---|---|---|
| OQ4:「`source_hashes` 能在 `transcript_chunks.content_hash` 或(固化节点)`memory_nodes.content_hash` 上找到」 | A/D/F 组均无 | 这是**唯一**验证 OQ4「不建到 chunks 主键/seq 的 FK、只存 content_hash」的断言;没有它,`source_hashes` 可能写入不可解析的值而无人发现。 |
| OQ1-B/共用:`setup 打印 AGE 版本必须等于 pin` | —— | 属已删支,不计。 |

### 1.3 弱化:确定性路由的 floor 规则只剩一个置引点

导出 OQ3-A 原文:「`multi_hop` 与 `recency` 仅在对应桶被主意图点名时才升权,**其余桶保持策略 `deterministic_floor`**」。计划 §3.4 只写「确定性/superset 模式传非负实数」,而 `deterministic_floor:1` 在全文只被 CJK/superset 一处置引(§1.3-OQ3、E2)。后果:E1 的「手算夹具(含小数并列)与名字升序终裁一致」无法复现——Hamilton 分配依赖**六个权重全向量**,计划没有钉死非升权桶取什么值。**修**:把 floor 规则写回 §3.4 第一行。

### 1.4 弱化:`consolidate_mode='every_n'` 自动器语义整体消失

导出 OQ6-A 写明了自动器形态:「只在 `consolidate_mode='every_n'` 且 interval≥1 时,由 owner 函数看 `nodes_since_consolidate`……源码确认后用策略 v2 翻页,不改函数」。计划只剩「v1 仅 `consolidate_mode='manual'` 且 interval=0,无自动计数器」,`nodes_since_consolidate` 在 §3.1 里标注「v1 manual 模式不消费」。方向没错,但见 S6:该键的另一成员值现在既无实现也无 fail-loud。

### 1.5 保留良好、经代码核验属实的关键 specifics(反向确认)

为避免「为具体而具体」的误删,以下导出机制在计划中**完整保留且与代码一致**,不建议改动:

- `v13_complete` 对 `kind='llm'` 且 succeeded **无条件**写 `llm/message`(`v13/schema/v13_core.sql:373`);路由 P0 按 `origin_user_seq=当前 last_user_seq 且 seq 最大`判 finish(`v13/loop/advance.sql:71-73,119`,代码在 :129-130)。OQ6 推翻 kind=llm 的 P0 依据成立。
- `v13_attempt_ok(p_kind,p_attempt)` 在 `v13/schema/v13_core.sql:196`;窄 requeue 改按行 kind 调用(F8)正是必要的,活体 `v13_requeue_stale`(`v13/twophase/v13_twophase.sql:33-86`)把 `'judge'` 硬编码在三处 UPDATE 里。
- `effects_kind_check` 现为六值(core 五值 + summary:27 加 `context_summary`);`effect_attempt_cap` 翻版仪式(`v13/summary/v13_summary.sql:29-39`)「INSERT inactive→双 UPDATE、旧键逐字保留」与计划描述逐字一致。
- `v13_judge_spend`(`v13/economy/v13_economy.sql:202-215`)、`judge_spend_gate` 种子(economy:49-53)、`resolve_fast_path={"max_batches":1,"batch_questions":32}`(core:748)、`ix_decisions_question_stannum` 已在(`v13/memory/v13_memory.sql:161`)、`v13_judgment_defaults_check` 对 point 名**开放**(`v13/manifest/v13_manifest.sql:455-494`,逐点 `jsonb_each`,只校验 `missing/review/timeout` ∈ 四动作)——追加六个 `mem_` point 不会被既有校验器拒,**无隐藏依赖**。
- `v13_enqueue_effect` 缺 cap 键即 RAISE(`v13/schema/v13_core.sql:222-226`),计划的「cap 忘带齐七键」缓解手段真实存在;`v13_enqueue_effect`/`v13_append_event` 已 REVOKE PUBLIC 且仅授 `v13_route`(core:874-897),ACL 负面断言可写。
- 不变量 15(`mem_route` signal 必须含 `mgraph_generation`)**经代码证明是承重的**:`v13_judgment_hash`(`v13/envelope/v13_envelope.sql:579-601`)材料含 `v13_group_state`,而 `mem_routing_*` 投影 `["query"]` ⇒ 代数不在 state 里;`decisions` 唯一键 `(session_id,request_hash)` 且 `ON CONFLICT ... WHERE decisions.answer IS NULL` ⇒ 不含代数则旧答案永不覆盖、`v13_gap` 恒 0。交叉确认 P1-3 折入正确。
- 信封十二键与活体 `v13_summary_envelope`(`v13/summary/v13_summary.sql:184-368`)逐字对齐:`sid,ctx,needed,templates,groups,budget,timeout_ms,candidate_set_hash,provider,model,goal_hash,candidates`;`==>` 只在候选函数 EXECUTE 串也有先例(memory:131 注释「文件 11 源码扫描计数=恰 1」)。
- 设计引用 §8 age 排除(`:458`)、元原则三条(`:462-466`)、触发(`:583`)均核对为真。

---

## 2. 欠定接缝 / 未决 / 矛盾 / 错引 / 缺依赖

### 2.1【S1,高】活体函数世代引用错误,且正是计划自己禁止的失礼

**计划原文**:

- §2.2:「`v13_resolve_judgments(env,max_batches)`(envelope:623-852 活体)」
- 附录 C.2:「直接调用点=各代 `v13_resolve_judgments` 定义体内(**envelope:726 等**)+`v13_filter_ask`(filter:329,**716**……)」
- §3.3:「若 **economy** 换体后不读 goal_hash/candidates……」

**代码事实**(`SQL_LOAD_ORDER` 位置:envelope=5、filter=10、economy=12、summary=13、periphery=14):

| 函数 | 最后一次 OR REPLACE(=活体) | 计划引用 | 判定 |
|---|---|---|---|
| `v13_resolve_judgments` | `v13/filter/v13_filter.sql:603` | envelope:623-852 | **错** |
| └ 其中 `typesafe_ask` 直调 | `v13/filter/v13_filter.sql:716`(在 resolve 体内) | 附录 C.2 归给 `v13_filter_ask` | **错**(716 不在 `v13_filter_ask` 里;`v13_filter_ask` 的是 :329) |
| `v13_judgment_envelope` | `v13/filter/v13_filter.sql:485` | — | 计划未引,无碍 |
| `v13_context_required` | `v13/periphery/v13_periphery.sql:191`(十一键) | economy:332 | **指向死代**(`dec` 语义两代一致:answered 行计数,故实质不错) |
| `v13_assemble_manifest` | `v13/periphery/v13_periphery.sql:688` | — | 计划未引 |
| `v13_manifest_validate` | `v13/periphery/v13_periphery.sql:1458` | — | 计划未引 |

**后果(不只是引用难看)**:

1. 计划的「economy 换体后不读 goal_hash/candidates」假设**对象错**。真正最后换体的是 **filter 代**,而它**确实**消费这两个键:`v13_filter_existence_ref` 在缺 `goal_hash`(非 64hex)或缺 `candidates`(非 array)时直接 V3006(`v13/filter/v13_filter.sql:54-59`),`v13_filter_bodies_present` 遍历 `p_env->'candidates'`(:200-202),resolve 的 `remaining` 尾部无条件调它(:942)。所以正确表述不是「多键无害少键炸」这种对冲,而是:**mgraph 信封必须带 `goal_hash`(64hex)与 `candidates`(`[]`),否则活体 resolve 在 `remaining` 尾部就会炸**。§3.3 的「实现第一步验证」应从「economy」改为「filter 代活体」。
2. 计划 §1.2 阻塞点 1 自己写着「活信封/装配/resolve 的最后函数体在 periphery 加载态,不在 recall 文本里」——§2.2 却把 resolve 活体钉在 envelope 文件,属于同类错误的另一侧(钉在中间代)。实现者若按 envelope:623-852 对齐信封键集,会漏掉 filter 代新增的 `remaining` 语义与两个必带键。

**修**:§2.2 增一张「活体坐标表」,把第 1 步要导出的八个函数逐个给**最后一次 OR REPLACE 的 file:line**(resolve=filter:603、judgment_envelope=filter:485、assemble=periphery:688、validate=periphery:1458、context_required=periphery:191、requeue_stale=twophase:33、effects_kind_check=core:99+summary:27、attempt_cap=summary:33、body_hash=chunks:13、judge_spend=economy:202)。第 1 步「从 periphery 库导出 pg_proc」的指令本身是对的,保留。

### 2.2【S2,高】B1 读环无生产调用方、无生命周期

- OQ8=B1 明确「不改装配/校验器/context_required」⇒ `v13_mgraph_evidence` 在本 DP **零仓库内消费者**。
- §3.5 状态流表的触发者写「驱动(会话无活跃 effect)」,但**驱动是什么**没写:cron job(memory 有 `DO $cron$` 先例,`v13/memory/v13_memory.sql:214-228`)、外部调度器、还是仅测试?导出 OQ2-B1 里唯一回答这个问题的句子——「唤醒不靠 pgmq:这是扫地,不是回合节拍(与 transcript tick 同哲学,`v13/memory/README.md` 运维①)」——在计划中被删掉了。
- 连带缺失:
  - `memory_walks`/`memory_rounds` **无保留/清理策略**。`transcript_chunks` 至少在注释里写明「无 retention 引用面」;walk 按 query 增长,`(session_id,query_hash,mgraph_generation,policy_version)` 每次翻策略都新 walk,行数无上界。
  - **无终态**。`memory_walks.status ∈ open|stopped`,而 `effects.status` 有 `cancelled`、events 有 `cancel/*` 族;会话走到 `completed/failed/cancelled` 时开放中的 walk 怎么办,计划完全没写。
  - M3 的 E 组因此是本 DP 对读环的**唯一**演练——这件事应该明写(「读环在 B1 下无生产入口,E 组是唯一执行面,下一张计划接装配」),而不是让读者自己推。

**修**:§3.5 触发者列改成具名驱动(建议直接沿用 memory 的 cron 降级形态,与 §4 ACL 里「cron 降级照 memory 的 DO $cron$」自洽),补一句 walk/round 保留策略(哪怕结论是「v1 不清理,README 呈报」),并补 cancelled 语义。

### 2.3【S3,高】consolidation 产物不可作锚,且固化边的端点未定

- OQ7 机制钉死:「池=本会话**全部 episodic 节点**,不得按到达顺序缩小池」。
- ⇒ consolidation 节点**永不进候选池**,只能靠遍历抵达。
- 而 §3.4 固化⑥只说「fidelity 通过才插节点+一条 `origin='consolidation'` 的子型边」——**src/dst/rel 三个都没给**。本 DP 的定位却是「设计 §4.4 三层栈第三层(远程层)的首个具体实现载体」(§1.1)。载体造出来了却没说怎么被读到,这是本条 DP 最大的未定接缝。
- 附带:`memory_links` 的 PK 是 `(session_id,src_hash,dst_hash,rel,origin)`。若固化边用 `rel=semantic`,之后一次 jev 关系问在同一 pair 上会产生 `(…,'semantic','jev')` 另一行——两者可共存,不是冲突;但 `rel` 闭集与 §3.4 的桶→rel 映射必须和固化边用的 rel 一致,否则束展开时会出现映射表外的 rel。

**修**:在 §3.4⑥钉死 `(src,dst,rel)`,并在 F 组加一条「从 episodic 锚出发的 walk 能/不能抵达 consolidation 节点」的显式断言(二者必居其一,不能留空)。

### 2.4【S4,中】`source_at` 的来源路径未点名

`transcript_chunks` 列为 `session_id, seq_from, seq_to, body, content_hash`——**没有时间列**(`v13/memory/v13_memory.sql:18-32`)。事件时间只能经复合 FK `(session_id, seq_from) → events(session_id, seq)` 取 `events.at`(core 的 events 表,`at timestamptz NOT NULL DEFAULT now()`)。计划只说「`source_at` 来自源事件」「时间特征只用从源事件复制的 `source_at`」,而不变量 8 禁 `now()`。实现者若不知道这条 join,要么犯规要么卡住。

**修**:§3.4 写路径⑤改成「`source_at := (SELECT e.at FROM events e WHERE e.session_id=… AND e.seq=t.seq_from)`」,并在 D 组加一条 `source_at = events.at` 的等值断言。

### 2.5【S5,中】花费计数单位错误,量级差 ~4×

`v13_judge_spend`(`v13/economy/v13_economy.sql:202-215`)数的是 `judgment_calls` **行数**——`v13_resolve_judgments` 每次 `typesafe_ask` 插一行,`question_count` 只是行内字段。所以 `session_asks_cap:512` 数的是 **ask 批数**,不是问数。

计划 §1.3-OQ2 的运维注记写「首建 **O(4N+10N) 问**会计入 session_asks_cap=512」:

- 单位错:该帽数批不数问。
- 量级错:每个新 episodic 节点花 **1 个类型信封 + ≤`candidate_top_k`=10 个关系信封 = ≤11 批**(关系信封 3–4 问仍是 1 批)。512 批 ≈ **46 个新节点**触顶,不是按问数算出来的十几个。
- 计划自己的 P1-2 裁决(`calls_used` 计批)与 `judgment_calls` 语义一致、是对的,但它**没点名取哪个返回键**。活体 resolve 返回 `asked_questions` 与 `asked_batches` 两个键(`v13/filter/v13_filter.sql:952-958`)——实现者极可能抓错。

**修**:README 注记改为「每新节点 ≤11 ask 批,`session_asks_cap=512` ⇒ ≈46 节点触顶」;§1.3-OQ2/§3.4 写明 `calls_used += (resolve 返回)->>'asked_batches'`。

### 2.6【S6,中】fail-loud 纪律不一致

- OQ5:`admission_enabled=true` ⇒ build RAISE V3009、零节点零 ask(已裁,保留)。
- `consolidate_mode` 是闭集(summary 侧 §3.2 形状校验「mode 闭集」),但其非 v1 成员 `'every_n'` **既无实现也不报错**;同时 `nodes_since_consolidate` 列存在却永不自增。
- 对照:`routing_mode='jev'`/`routing_shadow=true` 是**真有实现**的(OQ3 机制)。于是计划里出现三类策略键:真有实现的、保留但响亮的、保留但静音的——没有说明分类规则。

**修**:要么让非 `'manual'` 的 `consolidate_mode` 与 admission 同向 V3009,要么在 §3.2 明写「该键 v1 为纯数据、无消费方,翻值不报错也不动作」,并给出 §7 触发行的对应表述。

### 2.7【S7,中】重建删除规则两个版本互相矛盾

| 来源 | 规则 |
|---|---|
| 导出 §3.4 定死表 | 「DELETE 仅 `origin='episodic'` 的节点,以及**两端都不是 consolidation 节点**的边」 |
| 计划 §3.5 | 「DELETE episodic 节点与 **`origin<>'consolidation'`** 的边」 |

二者对「一条 `origin='jev'/'temporal'/'proximity'` 但碰着 consolidation 节点的边」结论相反。今天它们只因候选池 episodic-only(S3)而偶然等价——**等价是偶然的,不是设计的**。而计划的措辞恰恰把不变量 6「consolidation 来源节点与边不在 episodic 重建里删除」窄化成了「origin 字段=consolidation」。

**修**:采用导出那条按端点判定的规则(它才真正实现不变量 6),并把 D4 从「consolidation 夹具行还在」加强为「consolidation 夹具行**及其所有关联边**还在」。

### 2.8【S8,中】content_hash 去重使增量/全量重建可能不一致

- 节点 PK `(session_id, content_hash)` + `ON CONFLICT DO NOTHING`。
- 两行 `transcript_chunks` 正文相同(同一句 user/message 重复出现完全可能)⇒ 折叠成一个节点,存活者 `source_at` = **先到者**。
- 全量重建按 watermark 序重灌,顺序确定;增量路径的「先到」取决于 tick 时序。于是 `source_at` 可能不同 ⇒ temporal 邻接对可能不同 ⇒ D4「temporal 边集合字节级相同」在含重复正文的夹具下可红。
- 两份文档都没有「同文折叠」的裁定。

**修**:§3.4 写路径⑤写明裁定(建议「同 `content_hash` 保留 `(source_at, seq_from)` 最小者」,并让 `source_hashes` 收齐全部来源),D 组加一个重复正文夹具。

### 2.9【S9,中】固化 enqueue 闸与所引先例不符,后果未记

计划 §3.4④:「enqueue 仅 route 角色,且会话上已有 `ready|claimed|unknown` 时返回 NULL」,并在 §6 风险表写「调度闸:已有 ready|claimed|unknown 返回 NULL」。但 §1.2 复用清单与 §3.4 都把它描述成「沿用摘要闸」——`v13_summary_schedule` ① 实际只查 `status IN ('ready','claimed')`(`v13/summary/v13_summary.sql:307-309`)。

计划的更强版本其实**更正确**(与 advance ① 的 `ready|claimed|unknown` 阻塞面一致,`v13/loop/advance.sql:261-264`),但必须:

- 把先例从「摘要闸」改成「advance ① 的单活跃+unknown 墙」;
- 记录后果:**session 一旦落了 `unknown` effect(v13 无 ch12 显式 resolve),该会话永久不能再固化**。这个代价在 §6 风险表里没有对应行。

### 2.10【S10,中低】见 §1.3(确定性 floor)。

### 2.11【S11,中低】快照闸门漏 `criteria`

`judgment_templates.criteria` 是上游内容且有 ASCII 强制(`v13_decisions_criteria_ascii`,core:422-424;`v13_jt_noul_shape`,envelope:72)。附录 B 的槽位契约与 A3 闸门都只对 `question` 做文本全等。现有 noul 种子 `criteria` 均为 NULL(envelope:939-965),但 Jev-Mem 的 Noul 模板若带澄清文本,这些文字会变成**自拟**——正是快照闸门要防的事。**修**:附录 B 契约加「`criteria` 非 NULL 时同槽逐字+sha256」,A3 断言随之扩展。

### 2.12 引用不精确两处(低)

- §2.2「manifest v3+三种回放(periphery:127-164,manifest:915-920)」:`periphery:127-164` 确是 `v13_prefix_identity` 且 `manifest_version 3` ✓;但三种回放/分叉 kind 是 `exact_replay|recompute|fresh_fork`,在 `v13/periphery/v13_periphery.sql:45,318`;`manifest:915-920` 是 `v13_replay`,**只产出 `exact_replay`** 一种。
- §1.3-OQ7「`==>` 次数闸门钉死」:memory 先例给的是确切数「文件 11 源码扫描计数=**恰 1**」(`v13/memory/v13_memory.sql:131`)。计划应给同一量级的确定数,否则闸门无法实现。

---

## 3. 代码反证 / 非任务必需 / 可被更简设计替代

### 3.1 无「计划细节被代码反证」的硬冲突

逐条核验后,计划的机制性主张与代码一致,未发现需要推翻的条目。最接近反证的是 §2.1 的活体坐标(属引用错误,非设计错误)与 §2.5 的单位错误(属运维注记错误,非策略设计错误)。

### 3.2 一处「任务不要求」的过度规格

§3.5 重建段要求「毒化下第二次 rebuild:`failed=false`、asked=0、**temporal 边集合字节级相同**(proximity 只在同索引快照无并发写入的双 rebuild 下要求相同——OQ7)」。这条本身是对的且与 OQ7 裁决一致,保留。但注意它与 S8 的交互:在含重复正文的会话上,temporal 字节级相同**依赖**同文折叠裁定。建议把 S8 的裁定写成 D4 的前置条件,而不是留作实现细节。

### 3.3 一处可被既有更简设计完全替代的计划细节

**`write_max_asks`(默认 64)作为「独立 ask 帽」的必要性存疑,但结论不是删除,而是改名与改单位说明。**

- `judge_spend_gate` 已按 `judgment_calls` 行数封顶(批数),`session_asks_cap=512`。
- `write_max_asks=64` 同样是批数,且小于 512 ⇒ 单次 build 内它先触发;跨 build 仍由 session 帽收口。
- 所以它不是「第二套账」(不变量 13 仍成立),只是**单次 build 的节流帽**,与 `write_max_batches`(每 tick 节流,默认 8)是同一族。计划把两者并列为「P1-1 独立上界」+「每 tick 节流」,容易读成两套计数。
- **修**:在 §3.2 种子注释里把三个帽的关系一句话说清——`maximum_jev_calls`(一次 read walk,批)、`write_max_batches`(每 tick,批)、`write_max_asks`(每次 build,批),共同下游是同一个 `judge_spend`(批)。不新增键、不改语义,只消歧。

---

## 4. 导出与计划都缺失的:所有权 / 生命周期 / 失败 / 取消 / 可测性

| 缺失项 | 现状 | 建议最小补法 |
|---|---|---|
| **读环驱动者所有权** | 见 S2。导出有「扫地不靠 pgmq」一句,计划连这句都没留 | §3.5 触发者具名 + §4 ACL 的 cron 降级段对应 |
| **walk/round 保留策略** | 无。按 query 与策略版本无界增长 | v1 明写「不清理」并进 README 运维纪律;或按 `status='stopped'` + 龄期删 |
| **会话取消语义** | `effects.status` 有 `cancelled`、events 有 `cancel/*`;`memory_walks.status` 无 cancelled,计划零提及 | §3.5 加一行:会话 `cancelled/completed` 时开放 walk 不再驱动(或不驱动即自然停止),固化 effect 走 `v13_requeue_stale` 既有墙 |
| **迟到 decision 与 walk 的关系** | 不变量 11 说「迟到 decision 只允许随后的 apply 补插从未写过的边,不 UPDATE 旧边,`status='stopped'` 的 walk 不因迟到信号重开」——已覆盖,好 | 无需补 |
| **`mgraph_consolidate` effect 的取消/失败可见性** | §3.5 失败表有「固化生成失败 → cap+窄 requeue」;但**没有**「effect 被 cancel 后 pending 行怎么办」 | 失败表加一行:cancelled ⇒ 该 `consolidation_key` 留 pending,不重问同正文(与 rejected 同规) |
| **ACL 负面断言缺口** | A6 只断言 recall INSERT 失败、resolve `append_event` 失败、route `typesafe_ask` 失败;而 OQ6 机制**依赖**「resolve 无 enqueue 权限」 | A6 补两条:resolve EXECUTE `v13_enqueue_effect` 失败、resolve EXECUTE `v13_mgraph_consolidate_enqueue` 失败(两者在 core:874-897 已 REVOKE PUBLIC+仅授 route,断言零成本) |
| **BM25 必须走索引计划** | `stannum.full_score(ctid)` 只在行经 stannum 索引可达时可用(先例 `v13/characterize/v13_characterize.sql:103`、`v13/memory/v13_memory.sql:138` 的 reader);计划只说「`==>` 只在候选函数 EXECUTE 串」 | §3.4 候选函数补一句「必须由 TINQL 谓词驱动 stannum 索引扫描,不得对 `memory_nodes` 做裸表扫描后算分」;并注意 OQ1 的 `enable_seqscan=off` gate 若在同一 session 上跑,别顺手把候选函数也钉死 |
| **cgr bump 计数** | 见 S13 | 见 S13 |
| **E4 的预算口径可测性** | E4 已钉「计数单位=批:一轮含 1 停止封+≤束宽 5 遍历封」,好;但缺「首轮后 `calls_used` 恰等于 6」的正向数 | E4 加一条确定值断言,防单位回退 |

---

## 5. 会改变设计或实施顺序的问题(需用户/裁决回答)

1. **B1 下读环的生产驱动是谁?**(S2)若答案是「本 DP 不接、仅测试」,M3 的性质应从「读环」改记为「读环机制+零生产入口」,`memory_walks` 的保留问题也随之从「必须设计」降为「下一张计划」。若答案是「cron 扫地」,M1 就要带 `DO $cron$` 段,与 §4 ACL 对齐。**这一条改变 M1/M3 的内容与顺序。**
2. **consolidation 节点要不要做候选锚?**(S3)若「要」,OQ7 的池定义必须从「全部 episodic 节点」改成「全部节点」,并连带影响 S7 的重建规则与 D4;若「不要」,必须明写「产物只能靠遍历抵达」并加对应 gate。**这一条改变 OQ7 已裁机制的措辞与 F 组。**
3. **固化边的 `(src,dst,rel)` 是什么?**(S3)决定 `rel` 闭集与桶→rel 映射是否要扩展,也决定产物可达性。
4. **Jev-Mem 的 Noul 模板是否带非 NULL `criteria`?**(S11)决定 `QUESTION_SNAPSHOT.md` 契约要不要扩、以及 M1 能否一次到位(附录 B 说「停用词表可先 `[]`」,但没说 criteria 能不能先 NULL——**不能**凭空造)。
5. **`write_max_asks` 的单位与「先于 session 帽」的断言口径?**(S5/3.3)D11 要断言它先触发,就必须把 `session_asks_cap` 在夹具里调低;不调低时 64<512 也先触发,但表述容易误导。需确认 D11 夹具的帽值。
6. **非 v1 的 `consolidate_mode` 要不要 fail-loud?**(S6)与 OQ5 已裁的 admission 处理同向与否,影响 §3.2 形状校验与一条 gate。

---

## 6. 附:前序 gate 的结构性说明(S16,信息级)

每个 stage 的 `setup_db.py` 都只加载 `files_through(<stage>)`,因此 periphery/summary/twophase 的 gate **结构上不可能**加载 `v13_mgraph.sql`。M4「periphery/summary/twophase gate 同批必跑」实际只护住 `load.py` 那一行追加。值得注意的是 `v13/summary/test_summary.py:502` 对活动 cap 行做**六键全等**断言——它永远不会因为 DP9 而红(因为它不加载 mgraph),但要把这件事写进 README/计划备注:**若 summary gate 变红,绝不是靠改 summary 测试去修**(前序 stage 文件字节冻结)。同理,DP9 的 cap v3 七键只在 mgraph 库内生效。

---

## 7. 建议的最小修改清单(按优先级)

1. §2.2 加「活体坐标表」,改正 resolve/context_required 的 file:line;§3.3 的「economy 换体」改为「filter 代活体必读 goal_hash/candidates」。(S1)
2. §3.5 触发者具名 + walk/round 保留与 cancelled 语义;§1.1 明写读环在 B1 下无生产入口。(S2)
3. §3.4⑥ 钉死固化边 `(src,dst,rel)`;OQ7 池定义补一句 consolidation 节点不作锚;F 组加可达性断言。(S3)
4. §3.4 写路径⑤ 点名 `events.at` join;D 组加等值断言。(S4)
5. README 运维注记与 §1.3-OQ2 的单位/量级改正;`calls_used` 取 `asked_batches`。(S5)
6. §3.2 统一三类策略键(实现中/保留但响亮/保留但静音)的处理。(S6)
7. §3.5 重建规则改回「按端点判定」,D4 加强。(S7)
8. §3.4 补同文折叠裁定,D 组加重复正文夹具。(S8)
9. §3.4④/§6 把先例改成 advance ①,并记录 unknown 墙的永久阻塞代价。(S9)
10. §3.4 恢复 `deterministic_floor` 规则;附录 B/A3 扩到 `criteria`;§1.3 补三枚签名;不变量 9「一次」改「≥一次」;A6 补两条 ACL 负面断言;§2.2 两处引用精确化。(S10–S15)
