# DP3 · v13 manifest 骨架与三 epoch/freeze — 实施计划

> 日期:2026-09-20。分解来源:`prompt-exports/loop-orchestrate-v13-deep-plans-runs.md`(权威分解表 DP3 行;turn 1–17 教训全部携带;turn 12 用户裁决「全部跑完、不再设检查点」)。
> 基座:DP1 已验证(`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md`,3092 行,12 turn 双通道过)、DP2 已验证(`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md`,1744 行,5 turn 过)。冻结设计稿 `docs/designs/v13-context-on-pg.md`(2026-09-19 v2,禁改)。
> 成稿方式注记:本轮 context_builder 通道不稳(本日多次 ACP 故障,loop memory turn 1/13 先例),按父控制器 brief 授权**代行撰写**——勘察输入来自前次中断会话固化的 scaffold(其 Background/References/Open Questions 已逐条对本会话复核:DP1 §1.3/行 1973–1976/2284–2296/1991、DP2 §1.4/§3.2/§3.4/附 A #3、教程 ch5/ch7/ch10/ch13/ch14 引行全部实地重读核实,行号在文中标注)。成稿后经一轮只读探针批判(五面:SQL 机械/契约/设计矛盾/推演/gate 可执行性):5 发现中 2 项修复(epoch 触发器 belt 总量化/envelope 墓碑与 F5 错误点机械强化)、2 项按设计成立(query_side 空值语义即 OQ4/A4 19 键枚举补齐)、1 项经原文核实为误读(所称 epoch 触发器置 NULL 路径在原代码不存在——仅 IS NOT NULL 分支赋值;仍顺带加固);另自抓自修 2 处(sections 聚合内 ORDER BY 钉死/计数消歧)。待控制器 L3+双通道 L4。
> 修复 round 1 注记(turn 19):L4 双通道一致 FAIL(O1=gpt-5.6-sol 3P0+6P1;O2=grok-4.6 2P0+7P1),本轮修并集:预算装箱重写(Never/disabled 先标定不进装箱、含自身运行和判定、首段可 skip、自身超限必 skip)、SQL 完整化(mode CTE 补 FROM pri+墓碑二 envelope 函数体整段贴入——「引用不复制」退役)、section 键集字典序修正(churn 先于 content_hash)、exact replay 内容保全(section 正文内容寻址 blob 冻结+judgments 记 raw_verdict/模板版本/final_action+消费集反向收敛)、V3003 校验七层封闭(键集/类型/词表/64hex/null 三值逻辑穿透封死)、逐判断点默认动作 schema 落地(引设计审查 F1)、prefix identity 换源 generation 策略行(typesafe GUC=判断身份非生成身份)、goal/artifact 不变量(事件 FK+自证 CHECK+SECURITY DEFINER 受控写入+加载期回填)、epoch 真冻结(禁 UPDATE+悬挂模板引用 fail-closed)、settle 双行锁封闭快照窗口、gate 十六处对齐(window_20→verbatim/jdef_ver 键/D2·D3 换 identity 基 fixture/C2 可构造化/G4 全函数矩阵等;引设计审查 F11 于 blob 体积与保留)。
> 修复 round 2 注记(turn 20):L4 双通道仍 FAIL(O1 3P0+7P1;O2 1P0+7P1,多项收敛),本轮修并集——**P0×3**:transform 校验布尔反转修正(CASE 改「违规时 RAISE」形态+applied/skipped 两分支精确键集+applied jsonb_typeof 层,P0-1)/token 增 gen_ver 第七键(generation 翻版必追动 freshness+DP8 latch 同键缝+A6 独立 fixture+D3 改经 ② 真触发,P0-2)/DEFINER lander 伪造面封死(撤运行角色 EXECUTE+settle 收窄为 SECURITY DEFINER 窄入口+体内受信 schema 限定名+指针守卫覆盖 INSERT,P0-3);**P1×10**:锁序(全库冻结序=sessions→tools_meta→三策略活动行→effects[complete 内序,DP1 行 412–416 已核实];O1 提案序 effect→sessions 与 DP1 冻结序相反、恰成 AB-BA,故弃并论证+新增 F6 并发双 gate)/judgment_defaults 校验器接线 settle 守卫/judgments complete 谓词/epoch 防伪造(NULL 分支强制 pre-bind)+E4 重写与 B4 对齐/prank 非法 override cls 层 pre_skip+守卫前置/prefix_identity 去 strip_nulls+tools_meta 缺行 RAISE/V3003 全量 USING ERRCODE+错误码契约写死(OQ6)/inline 超限移至 complete 前/G1 对照面改「除 replay 块」/blob_land 补 succeeded belt+G4 owner 分离断言;设计冻结契约三处(fresh·recompute 语义/pg_jsonschema/G-ctx6)维持 plan 内裁决、附 A #15–17 呈报。

## 0. 执行索引

| 项 | 内容 |
|---|---|
| **Done when** | `uv run python v13/manifest/test_manifest.py` 退出码 0(A–G 七组断言全绿);提交前 DP1 四 stage gate(schema/resolve/loop/twophase)与 DP2 gate(envelope)全部复跑通过(各 stage 库不加载 DP3 文件,`files_through` 前缀切片——防回归的结构性保证,AGENTS.md 前置条件 1);附 B 全教训自检数字在档 |
| **Key files** | 新增 `v13/manifest/{v13_manifest.sql, setup_db.py, test_manifest.py, README.md}`;`v13/load.py` 追加(SQL_LOAD_ORDER 末尾一行 + `STAGE_THROUGH["manifest"]=6`) |
| **Dependencies** | DP1 契约 §1.3 DP3 行(v13_context_fresh 缝/goal_hash 来源接管);DP2 契约 §1.4 DP3 行(judgment 溯源/exact replay 归属/信封 19 键) |
| **Size** | 单 stage 单里程碑;SQL 一个文件(约 45 个顶层对象:2 表/21 函数/7 触发器/4 索引/3 ALTER/策略种子/加载期回填);gate 一文件七组(A–G,F6 并发锁序组为本轮新增)44 行断言 |

## 1. 定位与边界

### 1.1 本 DP 在 v13 版图中的位置

DP3 是设计 §11 交付排序第 1 条「承重件先行」的 manifest 骨架半边:两阶段 advance(DP1)与判断信封(DP2)已把「发现候选」与「判断缓存」落成行,DP3 把**「证明当时发现了什么」**落成行——context artifact 内嵌装配清单(manifest=IR,§5.2)+ 三 epoch 最小不变量与 manifest freeze(§6.1 配套四件的前两件;快照复核已由 DP1 落,版本化路由已由 DP2 落,请求信封固定已由 DP1/DP2 落)。同时承接 DP1 留给 DP3 的两个缝:`v13_context_fresh` stub 激活(required_revision vs active_revision)与 `goal_hash` 来源接管(版本化目标 artifact 最小实现,§6.2 触点 1 的承重半边)。

**骨架(非全量)**:本 DP 落 manifest 的结构与纪律,不落语料面——chunks 投影(DP4)、召回与 bm25(DP5)、过滤 verdict 与 candidates.decision_id(DP6)、经济学消费(DP7)、render/latch/fork(DP8)都以字段缝或函数替换缝承接(§1.4)。查询侧字段族(bm25/跨度/decision_id)在骨架里**以空值/空数组形态在场**,G-ctx5 断言字段族存在与词表,不断言语料生产者;judgments 同理——manifest 只记**被本版 sections/candidates 实际消费**的判断(消费集反向收集),骨架零消费 ⇒ judgments=[],完整判断历史留在 decisions/judgment_calls 查询面(DP2 provenance)。

**硬边界(零改动纪律)**:DP1/DP2 计划文件与(未来的)SQL 文件零改动。对既有对象的全部变更限定三形态:

1. `CREATE OR REPLACE` 换函数体(签名/OID/ACL 不动):`v13_context_fresh(uuid)`、`v13_probe(uuid)`、`v13_judgment_envelope(uuid)`——三者均「其余逐字保留、只换目标表达式」(§3.6 墓碑纪律);
2. `ALTER TABLE ... ADD COLUMN`(可空或带默认,零表重写):sessions 两列(context_active_artifact 带 FK→artifacts)、decisions 一列、judgment_templates 一列;
3. `CREATE TRIGGER` 挂既有表(events/decisions/sessions——goal 投影/epoch 回填与冻结/指针守卫)——新触发器对象,不碰既有触发器。新建表(v13_goals/artifacts)自身的触发器/约束/索引不限此形态。

`v13_advance` 函数体**不改**(DP1 §1.3 明文);② 分支的行为激活完全由 `v13_context_fresh` 换体达成——DP1 当年正是为此把 ② 写成对 stub 的调用(DP1 行 2284–2296,已核实)。

### 1.2 上游契约消费清单(逐条,来源:DP1 §1.3 契约表 DP3 行 + DP2 §1.4 契约表 DP3 行)

| # | 上游契约(原文要点) | 本 plan 消费方式 |
|---|---|---|
| 1 | `v13_context_fresh(p_sid)`(M3 恒 true stub,DP1 行 1973–1975)是 ② context gate 的实现缝,DP3 换成 required_revision vs active_revision 比较;签名 `(uuid)→boolean` 不动 | §3.2:OR REPLACE 换体 = `v13_context_required(p_sid)` 与 `sessions.context_active_revision` 的比较;advance ② 分支(DP1 行 2284–2296)零改动即激活——not-fresh → enqueue `context_refresh`(request 只携 goal_hash)→ send_work → waiting;failed/cancelled(含 attempt 封顶)→ terminal(该分支 DP1 已写好,DP3 的 worker 失败路径正好消费) |
| 2 | `goal_hash` 在 DP1=最近 user/message payload::text 的 sha256(probe 内联,DP1 行 1990–1993;信封内联同式);DP3 版本化目标 artifact 平面落地后接管其来源;goal_hash 是水位键非缓存键 | §3.1:v13_goals 投影表(每 user/message 一行,content_hash=sha256(payload::text),**与 DP1 公式逐字节相等**)+ 单一来源函数 `v13_goal_hash`;probe 与 envelope 两处内联计算都换调它(§3.6 墓碑一/二)——三处计算 → 一处来源(哈希同源教训) |
| 3 | advance 五步序与 ② 分支行为已冻结;**DP3 不得改 v13_advance 函数体** | 全 plan 遵守;④ llm 分支 request 仍为 `{route}`(DP1 行 2479–2483)——manifest 与 llm effect 的挂接走 §1.3 OQ3 裁决的 settle 侧路径 |
| 4 | effect kind 词表含 `context_refresh`;effect_attempt_cap 种子含 context_refresh:3(DP1 行 853–854 已核实);requeue_stale 对过期 claimed 的 context_refresh→unknown 墙(DP1 #13 分流,冻结) | 零改动消费:refresh worker 失败走 complete('failed') → ② terminal 分支(attempts_exhausted);lease 过期走 unknown 墙(ch12 域,README 注记);cap=3 即 refresh 的尝试上界 |
| 5 | 单活跃 effect 索引 `ux_v13_effects_single_active`(DP1 §3.1):同 session 至多一个 ready/claimed effect | **结构性地钉住 in-flight llm 的 manifest**:llm effect 存在期间 context_refresh 不可 enqueue(① 阻塞 + 唯一索引双保险)——llm worker 读到的 active manifest 必是路由时那份(§1.3 OQ3 论证) |
| 6 | G-ctx9「水位不一致弃批重解析」机制由 DP1 实现并测试(probe 七键,步 0);**G-ctx9 gate 条目归属 DP3(manifest 语境复测)** | §4 F 组:probe 换源后复测(goal 键来自 goal 平面)+ manifest 语境三断言(迟到 decision 不回写/水位弃批/canary 半边引用) |
| 7 | canonical_state=messages/derived/tools 投影,语义窗=「已沉淀历史(seq≤last_user_seq)∪ 当前 turn 自己的机器事件」,straggler 不进当前 turn 投影(DP1 #14/#25/不变量 7) | manifest 的 history 段 content 直接消费 `v13_canonical_state`(零重复实现,哈希同源);§3.2 论证 straggler 对 freshness 的影响 = 保守超集(至多一次多余 refresh,无正确性影响) |
| 8 | decisions:UNIQUE(session_id,request_hash);status∈open/answered/cached/failed;answer-once;命中=answer 非空∧status∈answered/cached | manifest.judgments 块照此谓词取「freeze 时已 complete 的精确 decision_id」;迟到=open 行后补答或新信封重问——都留在原 request/epoch 下(§3.1 epoch 列) |
| 9 | 每 stage setup 只加载到当前 stage(files_through 前缀切片);DP1 四 stage 与 DP2 stage 库不加载 DP3 文件 | v13/manifest 为 SQL_LOAD_ORDER 第 6 位纯末尾追加;`STAGE_THROUGH["manifest"]=6`;DP1/DP2 gate 复跑即回归证明 |
| 10(DP2) | 判断段的 manifest 溯源 = envelope 的 `templates`/`needed`/`groups` 键 + `judgment_calls.call_id`(manifest 引用 call_id 而非复制 usage) | manifest.judgments 每行记 decision_id+epoch+request_hash+template_name/template_version+**raw_verdict(answer 原文)**+final_action(P0-4②:非只 digest——旧裁决可重演);judgments 只收**被本版 sections/candidates 消费的** decisions(反向收集;骨架空集);call 级溯源经 decisions.call_id(DP2 provenance 列)JOIN judgment_calls——manifest 零 usage 复制(§1.5 不变量 5) |
| 11(DP2) | **exact replay 用 manifest 旧 verdict 归 DP3 实现**;DP2 的 v13_shadow_reroute 只是 shadow 面 | §3.7 `v13_replay(artifact_id)`:读旧 artifact 原字节 + 旧 verdict 原文,永不重跑 assemble;**内容保全半边(P0-4)**:history/tools 正文在 settle 时以内容寻址 blob 冻结于 artifacts 平面(kind='context_section',部分唯一索引天然去重),payload_ref 指 blob——语料/目录变化后旧 manifest 的被引用正文仍可原字节回取;与 shadow reroute(新阈值重释 raw answer)的分界写进 README |
| 12(DP2) | DP1 的 goal_hash 来源替换契约原样有效;形态=键/列引用,无 schema 变更 | 墓碑二只换 envelope 的 goal_hash 值表达式,19 键集与其余表达式逐字不动(M2-9 包含性断言不受扰) |
| 13(DP2) | pg_jsonschema 的 manifest 校验半边与 DP3 共享评估(DP2 OQ3/附 A #3) | §1.3 OQ6 裁决:不引入扩展,V3003 手写校验族 + 台账触发条件(与 DP2 answer 半边同构) |

### 1.3 Open Questions 裁决(scaffold 七项,本节为最终权威)

**OQ1 裁决:revision 载体 = sessions 行上的 jsonb「revision token」对,双侧同函数,零 bump 触发器。**

- 载体:`sessions.context_active_revision jsonb`(上次冻结时的 token 快照,初始 NULL=恒不新鲜)+ 派生函数 `v13_context_required(p_sid)`(单条 SELECT 语句、单快照)产出当前 required token。`v13_context_fresh` = 两者比较(jsonb 全等)。
- token 键集(骨架七键,全部单调;**P0-2 增 gen_ver**):`sem`(语义事件族 max(seq)——族=user/message、llm/message、tool/result,与 canonical_state 消费的族一致)、`dec`(该 session 已答 decisions 计数:answer IS NOT NULL)、`goal`(活动 goal 的 content_hash)、`tools_rev`(v13_tools_meta.revision)、`asm_ver`(assemble_manifest 策略活动版本号)、`jdef_ver`(judgment_defaults 策略活动版本号——默认分支是装配输入,版本追动必须触发 refresh,漏键=freshness miss)、`gen_ver`(generation 策略活动版本号——prefix_identity 的材料源是 generation 行,翻版(provider/model/system_blocks_digest 变)若不追动 freshness,则 fresh 仍真、**旧 prefix_identity 被继续用**;缺行 RAISE 与 asm_ver/jdef_ver 同姿势)。**追动键缝(DP8)**:任何新进 prefix_identity 材料的输入必须在 token 有键——latch 落地时其版本并入同一键缝(扩 gen_ver 语义或增独立键);「进身份不进 token」=freshness miss 的结构性防线(风险 2);token 键集增删 ⇒ 旧 active token 全失配 ⇒ 全域恰一次 refresh(manifest_version 追动)。
- **不做 bump 计数器的论证**:bump 纪律要求枚举全部「改上下文」的生产者并在其事务内递增——漏一个是 freshness miss(静默用旧 manifest),多一个是活锁(编排事件若递增,turn/route/effect_done 每次 advance 都触发 → ② 永不新鲜 → context_refresh 无限循环)。派生 token 无 bump 面:漏掉的生产者只要进不了 canonical_state/manifest 输入就无须进 token;进得去的(语义事件/decisions/goal/tools/装配·默认分支·生成身份三族策略版本)七键已全覆盖。代价是每次 ② 做索引读(sem 走 §3.1 部分索引 O(log n)、dec 走 decisions 的 (session_id,request_hash) 唯一索引前缀、goal/tools/策略各一次单行读)——② 本就在 advance 会话锁内,毫秒级本地读与不变量 3 相容(DP1 步 0 探针同量级)。
- straggler(跨 turn 迟到语义事件,seq 高于当前窗):`sem` 取族内 max(seq) 不加窗谓词 = 保守超集——straggler 落地会多触发一次 refresh(装配仍按 canonical_state 的窗滤掉它,manifest 字节不变),收敛无活锁;精确谓词(套 origin 窗)每次 ② 都要重算窗,成本与收益不成比例。**取舍记档:超集换简单,至多一次多余 refresh。**
- `dec` 计数含一切 epoch(装配侧才过滤,见 OQ7)——post-execute 行落地至多触发一次 refresh 且 manifest.judgments 按 epoch 如实记录、sections 零消费(骨架内 sections 不消费任何 verdict),「post-execute 只能影响后续 turn」由消费侧结构性成立。

**OQ2 裁决:版本化目标 artifact = 独立投影表 `v13_goals`,事件溯源;hash 与 DP1 逐字节相等。**

- 形状:`v13_goals(session_id, seq, content_hash, payload)`,PK (session_id,seq),append-only 触发器执法;`trg_events_goal`(events AFTER INSERT,WHEN type='user/message')同事务投影一行。每个 user/message = goal 的一个版本(内容寻址 content_hash=sha256(payload::text));活动 goal = max(seq)。
- **不落 artifacts 表 kind='goal' 的论证**:ch7 的 artifacts 纪律是 produced_by NOT NULL REFERENCES effects + 「指向非 succeeded effect 的插入被拒」(ch7:46-47 消费/生产纪律)——goal 的生产者是**用户事件**,不是 effect;塞进 artifacts 要么伪造 effect 溯源、要么弱化 ch7 不变量,两者都比一张小投影表贵。教程 ch13:20 的「goal→sessions 控制行(新增 0)」语义以「活动 goal 可由 session 行派生(max seq)+ token 携 goal 键」实现,不加冗余 sessions goal 列(避免第二真相源,§8 元原则 (c))。
- 字节相等:`v13_goal_hash(p_sid)` = 活动 goal 的 content_hash,无 goal 时 = sha256(''::text) 的 hex——与 DP1 probe 的 coalesce 公式(DP1 行 1990–1993)逐字节相等。**gate 硬断言相等**(A 组),水位跨 DP3 边界零漂移;effect 身份族里 goal_hash 是语义词段,字节相等 ⇒ judge/llm effect 身份不因换源而变。
- 来源接管:probe 与 envelope 的 goal_hash 内联表达式换调 `v13_goal_hash`(§3.6 墓碑一/二,各自「其余逐字保留」)。§6.2 触点 1 的「goal_hash 必须是版本化目标 artifact」由此闭环:压缩 hint(DP7)保护的是有版本、可寻址的 goal 行,不是一条事件尾巴。
- **不变量执法(O1 P1-8,本轮补齐)**:① 加载期回填——§3.1 末尾 `INSERT ... SELECT` 把既有 user/message 事件投影进 v13_goals(stage 库 DROP-CREATE 为空操作;共享库升级面不丢版本);② 溯源 FK+自证——`v13_goals` 加 `(session_id,seq) REFERENCES events(session_id,seq)`(events 主键在档,DP1 §3.1)与 `CHECK (content_hash = encode(digest(payload::text,'sha256'),'hex'))`,artifacts 加 `CHECK (inline IS NULL OR (content_hash = sha256(inline::text) AND size = octet_length(inline::text)))`——哈希/尺寸自证,写入路径外的篡改不可落行;③ 受控写入——`v13_goal_project` 触发器函数 `SECURITY DEFINER`(search_path 钉死+体内受信 schema 限定名),artifacts 写入只经 `v13_artifact_land`/`v13_blob_land` 两个 DEFINER 落行函数;运行角色**零直接 INSERT 权限且零直接 EXECUTE**(P0-3:双 lander 不授任何运行角色——唯一落行路径=§3.5 `v13_refresh_context`(SECURITY DEFINER 窄入口)体内,经 kind/session 校验+策略守卫+装配+manifest validator+complete CAS 之后才落;G4 负向+owner≠运行角色分离断言)——route 被攻破也不能伪造 goal/artifact 行、不能伪造 context 再挪 sessions 指针(指针守卫并覆盖 INSERT,§3.1;残余面=挪向旧合法 artifact,token↔manifest 错配由 ② 结构性自愈)。

**OQ3 裁决:freeze 点 = context_refresh worker 的 settle 事务;④ llm effect 与 manifest 的挂接走单活跃约束 + settle 侧 provenance,不动 advance。**

- freeze 语义(§6.1 原文):「final manifest 只消费 freeze 前状态为 complete 的精确 decision_id;缺失、超时、review 带一律走版本化默认分支;迟到结果留在原 request/epoch 下,仅供完全相同信封复用,不得回写已冻结 manifest」。落点:**装配事务的语句快照即 freeze 面**——`v13_assemble_manifest` 单条 SQL 语句(全部 CTE 共享同一语句快照,DP2 turn 7 #47 单快照纪律同款),required token 在语句内计算并内嵌进 manifest;settle 事务把 `manifest->'required_revision'` 原样写入 sessions(单一来源,零独立重算——哈希同源)。**快照窗口封闭(O1 P1-11/F4 + P1-4,本轮重写)**:settle 在装配前依全库冻结锁序取三层行锁(sessions → tools_meta → 三族策略活动行[assemble_manifest/generation/judgment_defaults,`ORDER BY name` 定序])——append_event/advance/complete 持 sessions 行锁、目录 bump 持 tools_meta 行锁、策略翻版持旧活动行锁,三者在 settle 提交前都被阻断 ⇒ settle 事务内策略守卫/装配/token/身份四读同版——READ COMMITTED 下语句级快照仍逐句更新,但**被锁行在 settle 提交前不可变(锁行即定版,非锁快照)**,装配与其后 blob 冻结/指针写看到的会话域/目录域/策略域状态一致;effect 行锁由 `v13_complete` 在 CAS 点取得。**全库锁序(冻结,本 plan 立法)**:`sessions → v13_tools_meta → 策略活动行 → effects`(末跳=DP1 已冻结的全树统一序 sessions→effect,DP1 行 412–416,已核实)。**settle 不在入口取 effect 行锁的论证(P1-4①,与 O1 提案序相反)**:O1 所称「complete 路径先 effect 后 session」与 DP1 代码相反——complete 明文先 sessions 后 effects;若 settle 按提案序 effect→sessions,恰与 complete 的 sessions→effect 构成经典 AB-BA(提案序引入它要防的死锁,故弃);入口的 effect 读是无锁 advisory 读(kind/session 校验),从读到 CAS 之间他方 complete 由 CAS 兜底('stale'/'replay' 零写返回,TOCTOU 良性);DP1 全树无任何 effect→sessions 路径(claim/renew_lease/requeue_stale 只触 effects 单族,已核实)——现有序无环,F6 双并发 gate(settle∥settle / settle∥complete)实证零 40P01;blob 重算哈希≠manifest 段哈希的不可能路径仍留 V3003 belt(§3.5)。语句快照之后落地的 decision 物理上不在 manifest 里,token 也不含它 ⇒ 下一次 ② 必检出 ⇒ 新一版 manifest 消费之。「不得回写」由 artifacts append-only 触发器结构性执法。
- 为什么不是 ④ 建 llm effect 时:④ 在 `v13_advance` 体内(DP1 零改动纪律直接排除);且不必要——`ux_v13_effects_single_active`(契约 #5)保证 llm effect ready/claimed 期间同 session 无任何新 effect 可建,context_refresh 也一样 ⇒ **llm worker 在 claim 后读到的 sessions.context_active_artifact 必然就是路由决策那一刻的 active manifest**(advance ② 通过后才可能到 ④;④ 到 worker claim 之间 active 指针不可移动)。挂接的审计落点:llm worker 的 result 携带 `context_artifact_id`(worker 契约),经 DP1 v13_complete 的 llm 分支(p_result ∥ origin_user_seq,DP1 行 469–475 已核实)自动流进 llm/message 事件与 effect 行——日志里「这次生成消费了哪份 manifest」是事件级可查的,零 DP1 改动。
- 若 DP8 的前缀经济学需要把 artifact_id 钉进 llm request 字节:DP8 有缝(§1.4 DP8 行)——render 落地时经 worker 契约或 v13_route 输出扩展补;DP3 已在 result/event 侧落全量 provenance。
- 「版本化默认分支」的最小立法(O1 P1-6,引设计审查 F1):**逐判断点默认动作 schema 本 DP 冻结**——策略行 `judgment_defaults`(版本化追加不覆盖):`{"points":{"<判断点名>":{"missing":"<动作>","timeout":"<动作>","review":"<动作>"}},"actions":["include","exclude","degrade","fail"]}`;骨架种子 points={} 空表(无天然判断门控段),`v13_judgment_defaults_check` 校验器执法形状(键集恰等/状态三元组恰等/动作词表封闭,gate B7 直调),token 的 `jdef_ver` 键保证版本追动触发 refresh;DP6(per-chunk Score/存在性 Noul)/DP7(摘要验收)落真段时填 points 值与消费臂——F1 所指「流量最大的过滤点无缺省动作」自此有唯一版本化载体。section 级实例同时在场:§3.4 的 priority_overrides/Never/disabled/预算四种 skip 原因即 transform 级默认分支。

**OQ4 裁决:manifest jsonb schema(外层 10 键、section 9 键,manifest_version=1)。**

```
manifest(外层,键集封闭——校验拒绝未知键):
  manifest_version: 1
  session_id / turn_no:                装配快照的会话锚(turn 来自 sessions.turn_no,确定性)
  prefix_identity:                     sha256(canonical bytes{provider,model,system_blocks_digest,
                                       tools_revision,tools_digest,goal_hash,latch_digest,
                                       manifest_version})——§5.6 前缀身份的骨架半边。
                                       **材料来源=版本化 generation 策略行**(O1 P1-7:typesafe.*
                                       GUC 是判断(Jev)身份不是生成身份,不入材料);system_blocks
                                       骨架 '-none-'(DP8 render 落真值);latch 项 = v13_latch_digest
                                       stub;goal_hash 留在材料的成本记附 A #10
  policy: {assemble_version, budget_tokens, est_bytes_per_token,
           judgment_defaults_version}   装配所据两条策略行的版本化快照(4 键)
  required_revision:                   七键 token(语句内计算,见 OQ1;含 gen_ver——P0-2)
  sections: [ section ... ]            骨架三 kind:goal(Session,First)/history(Session,Normal)/
                                       tools(Global,First);DP4–DP7 增 kind 只加行不改结构
  query_side: {query_artifact_id, candidates:[...]}
                                       骨架:query=活动 goal 地址对象;单 echo 候选(见下)
  judgments: [ {decision_id, epoch, request_hash, template_name, template_version,
                raw_verdict, final_action} ... ]
                                       **只收被本版 sections/candidates 实际消费且 complete 的 decisions**
                                       (answer 非空∧status∈answered/cached——P1-6;反向收集;骨架零消费 ⇒ []);每行记 answer 原文与模板
                                       版本(P0-4②:旧裁决可重演,非只 digest),final_action 词表
                                       {recorded,include,exclude,degrade,fail}(骨架消费集空,
                                       词表与校验先行,DP6/DP7 填真值);按 decision_id 排序;
                                       exact replay 的旧 verdict 载体
  replay: {mode, prior_artifact_id}    mode∈{fresh,recompute};exact_replay 只出现在
                                       v13_replay 的返回视图(其 replay 块被 || 覆盖——语义写死
                                       见 OQ5),装配产物永不为 exact_replay
section(9 键):
  section_id(kind 同名)/kind/cache_scope∈{Global,Session,None}/priority∈{Never,First,Normal,LastResort}
  /content_hash/est_tokens/payload_ref/churn/transform
  payload_ref 形态:jsonb 判别对象 {kind:'goal',seq} | {kind:'blob',content_hash}——
                   goal 指 v13_goals 不可变行;history/tools 指 settle 时冻结的内容寻址
                   blob(artifacts kind='context_section',P0-4①:被引用正文永可原字节回取,
                   内容寻址天然去重);旧 {kind:'canonical_state'} 形态退役(指当前态,
                   语料变化后重放漂移——P0-4 所修)
  transform:{applied:true,name:'verbatim'|'catalog_digest'}
            |{applied:false,reason:'budget'|'priority_never'|'disabled'|'invalid_override'}
            ——applied/skipped 双分支落行,两分支键集精确恰等({applied,name} /
            {applied,reason},P0-1);invalid_override=非法 priority_overrides 值专属
            (cls 层 pre_skip:不进装箱/applied、priority 字段回退 def_prio——P1-8;
            settle 守卫前置 RAISE,该 reason 仅直调装配可产出=可审计 skip 记录);
            首版 transform 名与哈希材料一致(history='verbatim';真窗口是 DP7 的
            新 transform 名+新策略版本行)
candidates 字段族(§5.2 查询侧 + §4.7 跨度形态,DP3 立法,DP4/5/6 填充):
  {content_hash,            -- 候选内容身份(永远 content_hash,禁 chunk 主键——ch7 纪律 3)
   bm25,                    -- 骨架 NULL(召回未落地);DP5 填 numeric
   spans,                   -- '[]'::jsonb 空数组在场;DP4/5 填 [{doc:<content_hash>,
                            --   offsets:[[start,end],...]}](doc=内容寻址,非 (source_hash,chunk_no))
   decision_id}             -- 骨架 NULL;DP6 填 per-chunk verdict 的 decision_id——
                            -- 此键即 judgments 消费集的反向收集入口
est_tokens 确定性公式:((octet_length(段规范字节) + est_bytes_per_token - 1)
                      / est_bytes_per_token)——整数算术,无 numeric 往返;公式随策略行
                      est_bytes_per_token 版本化(DP7 换真 tokenizer=新版本行+recompute 语义自动成立)
churn 计数:对上一版 manifest(sessions.context_active_artifact 指向的行)按 section_id
           对齐:**无前版 ⇒ 0(首版未发生变动)**;有前版且 content_hash 变 ⇒ prior.churn+1;
           不变 ⇒ 0——与 C1 断言字面一致(O1 gate 对齐项)。「连续版本里第几次变动」,
           cache-break 归因(§5.4 一条 SQL diff)与波动率排序(DP7)的输入
```

- ORDER BY 确定性:sections 按 (priority 权 First=1/Normal=2/Never=3/LastResort=4, section_id) 全序——显式四值 CASE(O2 P1:LastResort 独立权值;非法 override 值在 cls 层即 pre_skip='invalid_override' 不进装箱,其行 prank 虽 NULL 但永不进 applied——P1-8:收口不靠 validate;settle 策略守卫对 overrides 值词表前置 RAISE,见 OQ3);候选数组序留给 DP5(bm25 DESC, content_hash ASC 届时进其 plan)。**装箱(P0-1 重写)**:Never/disabled 段**先标 skip、不进装箱**;其余候选按上述全序求「含自身运行和」run_incl,run_incl>budget 即 skip(reason='budget')——等价于 running_applied+est_tokens>budget,自身 est>budget 必 skip,**首段可被 skip**(旧 pre_cum 谓词两缺陷就此封死);applied 集合恒为候选的连续前缀(run_incl 单调不减),并列不抖。
- 装配产物零时间戳、零随机、零活策略读(策略经版本参数进来)——同 DP1 v13_snapshot 的确定性纪律。

**OQ5 裁决:三种回放的最小可区分实现 = replay 块字段 + 只读读者函数;recompute 不落库。**

- `v13_replay(p_artifact uuid)`:纯读旧 context artifact 原字节,返回 `manifest ∥ {replay:{mode:'exact_replay',source_artifact}}`——**永不重跑 assemble**(ch14:92「不重跑 assemble」原文);旧 verdict = manifest.judgments 原样(freeze 时固化的 raw_verdict 原文+模板版本+final_action)。**`||` 覆盖语义写死(O2 P1-3)**:jsonb `||` 按顶层键右胜——返回视图的 `replay` 块**覆盖**原 manifest 自带的 `{mode,prior_artifact_id}`,这是设计意图(视图标注赢)而非事故;该视图**不进 validate、不可 settle**(settle 只走 refresh,validate 只执法装配产物),README 与 D1 注记同步。**内容保全(P0-4③)**:sections 的 payload_ref 指 blob(或 v13_goals 行)——语料/目录/阈值变化后,旧 replay 的被引用正文逐字节可回取、judgments 原文与动作逐字不变(G10 断言)。与 shadow reroute 的分界(DP2 §3.7):exact replay 不触新阈值、不重释 raw answer。
- `v13_assemble_manifest(p_sid, p_policy_version DEFAULT NULL)`:NULL=活动版本(唯一可 settle 的形态);给定旧版本号 = recompute(旧策略×当下语料,再 assemble,ch14:93)——**只读返回,不写 sessions/artifacts**(settle 写路径只走 refresh,且只以 NULL 调用;若以钉定版本 settle 会造成「token 说 v2、sections 是 v1」的错配,结构性封死)。
- mode 判定(装配时,**identity 基**——O1 gate 对齐项):prior 不存在 或 本次 prefix_identity ≠ prior.prefix_identity → `fresh`;否则 → `recompute`。策略版本 bump(budget/est 变)不动 identity 材料 ⇒ 判 `recompute` 非 `fresh`(版本 bump 是「同身份重装配」;旧「版本不等即 fresh」判据作废);fresh fork 由 §5.6 语义自然成立:identity 材料不含 token,只有生成身份/目录/latch/goal 变才变;「recompute 前缀身份可继承」(ch14:93)同样自然成立。D2/D3 fixture 按此重造。
- G-ctx5「三种回放可区分」的可断言签名:D 组三 fixture 断言 (mode, policy.assemble_version, prior_artifact_id, prefix_identity) 四元组在三种回放下互异;exact replay 另有「迟到 decision 落地后字节不变」(freeze 纪律的直接推论,F 组复测)。

**OQ6 裁决:pg_jsonschema 不引入;manifest 形状校验 = V3003 手写族,与 DP2 answer 半边同构。**

- 论证:DP2 OQ3 已裁 answer 半边由 V3001 族独扛,触发条件「答案形状超三族」未至;manifest 半边同理由——骨架形状(10 外层键/9 section 键/封闭词表)完全在手写 CHECK 的表达力内,且 V 码族 fail-closed、可 mock、零扩展依赖(§8 元原则三条全过)。`v13_manifest_validate(p_manifest)` 在 settle 的 artifact 落行前执法,**校验封闭(O1 P1-5,本轮逐层补齐)**:外层/section/policy/required_revision/replay/judgments 行/candidate 行七层键集恰等;JSON 类型与非空(jsonb_typeof/IS NULL);词表(cache_scope/priority/epoch/final_action/transform.name/transform.reason/payload_ref.kind/replay.mode);hash 格式(content_hash/prefix_identity/request_hash 一律 `~ '^[0-9a-f]{64}$'`);数值域(churn/est_tokens≥0、budget≥0、divisor>0、turn_no≥0、version=1 用 IS DISTINCT FROM);**null 枚举三值逻辑穿透全数封死**——一切枚举判断改 `IN (...) IS NOT TRUE` / IS DISTINCT FROM 形态(DP2 criteria 列卫同款;旧 `NOT x IN (...)` 对 NULL 静默放行的路径清零);jsonb_object_keys 只在 jsonb_typeof='object' 确认后的独立 IF 中调用(SQL OR 不保证短路,顺序求值纪律);section_id=kind 同名、非空。违规一律 RAISE 且显式 `USING ERRCODE='V3003'`(P1-10 全量挂码——旧版码只在消息文本,β/驱动按 SQLSTATE 分流时捕不到)。**错误码契约(写死,取「统一 V3003+明示原生码边界」)**:①词表/键集/形状/null 层=validate 族两函数全部 RAISE+settle 策略形状守卫+settle 哈希漂移/inline 超限 belt,一律 USING ERRCODE='V3003';②epoch 悬挂模板引用=V3002(DP2 溯源族,沿用);③类型焙劣输入(`::int`/`::boolean` 转换失败等)以原生错误码(22P02 等)响亮失败、纪律触发器(append-only/epoch 冻结/指针守卫/produced_by 守卫/lander kind)保留默认 P0001——三层各管各面,fail-closed 全覆盖,README 同文。
- 台账触发条件(与 DP2 §7 同款,进本 plan §7):manifest 形状演化出手写族表达力(嵌套 schema、条件依赖、跨字段约束)且第二消费者出现(render/外部审计)时,pg_jsonschema 进核心,schema 版本化不可变(§8 表行原话)。两半边届时同批评估。

**OQ7 裁决:三 epoch = decisions.epoch 列 + 模板列默认 + INSERT 触发器回填;post-execute 零生产者。**

- `ALTER TABLE decisions ADD COLUMN epoch text NOT NULL DEFAULT 'pre-bind' CHECK (epoch IN ('pre-bind','pre-finalize','post-execute'))`——DP1/DP2 既有判断全部路由面向(v13_route 消费),默认值即正确语义;旧行零回填(stage 库 DROP-CREATE,无存量)。
- `ALTER TABLE judgment_templates ADD COLUMN epoch text NOT NULL DEFAULT 'pre-bind'`(同 CHECK);`trg_decisions_epoch`(BEFORE INSERT ON decisions):NEW.template_name 非空 ⇒ epoch 取模板行声明的值(索引单行读),NULL(DP1 时代形态)⇒ 默认 'pre-bind';**模板行缺失(非空引用不存在的模板/版本)⇒ RAISE V3002 fail-closed,不静默回退 'pre-bind'**(O1 P1-10——旧 belt 的 coalesce 回退路径退役;DP2 needed 族先行拒是第一层,本触发器拦手拼 INSERT 的悬挂引用为第二层);**调用方显式 epoch 值一律忽略(P1-7 防伪造)**:NULL 分支无条件置 'pre-bind'(手工 INSERT 带显式 'post-execute' 不可达)——post-execute 行必引用声明该 epoch 的模板(触发器结构保证,无第三来源)。DP6 冻结 per-chunk 模板时声明 'pre-finalize'(装配承重判断),DP7 触点 4 声明 'post-execute'——**epoch 是模板属性,不是调用方属性**,消除「同题异 epoch」的口径漂移。
- 「迟到结果留在原 request/epoch 下」:decisions 行的 epoch 在 INSERT 时固化,answer 后补(B9 冲突填充形态)不改 epoch——结构性满足;「仅供完全相同信封复用」= DP1/DP2 既有 (session_id,request_hash) 命中谓词,零新机制。
- post-execute 生产者缺位 ⇒ 该值在骨架内只出现在词表与校验里,且必经模板声明落地(任何 decisions 行的 epoch 都来自模板行或 'pre-bind' 缺省——E4 防伪造断言);「只能影响后续 turn」的执法 = sections 零消费 verdict(骨架)+ DP6/DP7 落消费段时按 epoch 过滤(§1.4 契约行明文)。`dec` token 键不过滤 epoch(OQ1 已论证:至多一次多余 refresh,无语义泄漏)。
- **epoch 真冻结(O1 P1-10)**:`trg_decisions_epoch_freeze`(BEFORE UPDATE OF epoch ON decisions)无条件 RAISE——epoch 只许 INSERT 期经触发器落定,任何事后改写(含词表内改写)被拒;E1 断言改为「UPDATE epoch 任意值(含词表内值)全拒」。「迟到结果留在原 request/epoch 下」由此双重成立:answer 可后补(answer_once 允许 NULL→非NULL),epoch 永不可动。

### 1.4 本 plan 对 DP4–DP8 发布的契约

| DP | 契约 | 形态 |
|---|---|---|
| DP4(chunks 投影) | **`v13_context_required` 是唯一新鲜度源**:chunks 投影落地后,语料版本键(重摄取代数或 corpus 指纹)必须并入其键集(函数替换,签名 `(uuid)→jsonb` 不动)——漏并 = 语料变更不触发 refresh 的 freshness miss;candidates.spans 按 OQ4 形态填充(doc=content_hash);manifest/decisions 仍只记 content_hash,禁 (source_hash,chunk_no)(ch7 纪律 3,跨 DP 不豁免) | 函数替换+字段填充 |
| DP5(recall) | candidates 的 content_hash/bm25 由 v13_recall 族产出进装配(或经 DP4 投影);candidates 数组序钉 `bm25 DESC, content_hash ASC`(§4.1 并列截断确定性在 manifest 侧的同型);manifest 不内嵌 TINQL;语料/索引版本并入 cgr 的 DP1 #59 硬契约原样有效 | 数据填充 |
| DP6(过滤管道) | candidates.decision_id = per-chunk verdict 的 decision_id;过滤模板必须 epoch='pre-finalize'(经 trg_decisions_epoch 自动落行);判断溯源 = manifest.judgments + decisions.call_id → judgment_calls(DP2 §1.4 原样,manifest 零 usage 复制;judgments 行=complete-only:`answer IS NOT NULL AND status IN ('answered','cached')`——P1-6 谓词已立于 §3.4;missing/timeout/review 的默认动作**不进 judgments**(raw_verdict=null 会被 validate 拒),其 trace 载体=你的段/候选级消费段设计,被引用而未完成的 decision 由谓词自动滤出);「跨 session 复用」读 canonical 层,manifest 记本 session 视角;judgment_defaults.points 填 per-chunk Score/存在性 Noul 两点(missing/timeout/review 三态各配动作,F1);candidates.decision_id 落地后 judgments 消费集自动非空(§3.4 反向收集,零结构改动) | 模板行+引用 |
| DP7(经济件) | est_tokens 公式版本随 assemble_manifest 策略行(换公式=追加版本行,recompute 语义自动成立);tier/E(r)/R_o 消费 sections[].est_tokens 与 judgment_calls.usage;post-execute epoch 生产者归触点 4(弱标签纪律 §6.3 全文有效);摘要段 kind='summary' 新增 section kind + §6.4 回退链逐步落 transform.applied/skipped(本 plan 的 transform 结构即其审计载体);judgment_defaults.points 填摘要验收点(§6.4-4 fail-closed:review/reject/缺失/超时不采用;settle 已接线校验器——非法 active 行 refresh 即 V3003,非测试纪律,P1-5);真窗口=新 transform 名+新策略版本行(首版 verbatim,O2 P1-1) | 策略行+新 kind |
| DP8(latch/render/fork) | **`v13_latch_digest(uuid)` 是 latch 前缀身份缝**:DP3 stub 返回 '-none-',DP8 函数替换(表本体归 DP8;替换时 latch 版本必须并入 token 追动键缝——OQ1 gen_ver 同缝,P0-2:进 prefix_identity 材料的输入必须在 token 有键,否则 latch 变化不触发 refresh);**generation 策略行(provider/model/system_blocks_digest)DP8 接管填真值**(DP3 种子 mock——O1 P1-7 换源的最小落地;render_policy_version 与之合流时经版本行迁移);canonical render = render(manifest, render_policy_version, provider) 纯函数,消费本 plan 的 manifest 结构,**经 payload_ref 回取 blob 正文**(P0-4 内容保全面);fork/exact replay/validate-spawn/cache probe 消费 artifacts 行 + prefix_identity;若前缀经济学需 llm request 钉 artifact_id,DP8 在 render 落地时经 worker 契约或 v13_route 输出扩展补(OQ3 已留缝);system blocks 正文 blob(若 render 需要)沿 v13_blob_land 形态扩展;goal 排序对 identity 成本的实价见附 A #10 | 函数替换+消费 |

### 1.5 不变量(全 plan 有效,违反即设计背离)

1. DP1/DP2 全部不变量原样继承(两相分离/锁内零外部 IO/纯判断 IO 例外唯一/双登录/αβ 语义/行为参数冻结消费);本 plan 新读写全部发生在 refresh settle 事务(worker 的 route 连接)与 gate 内,**零外部 IO**——装配是确定性本地 SQL(设计 §0:装配不属生成 IO;llm 生成仍在 worker)。
2. 对既有对象的变更只限 §1.1 三形态(OR REPLACE 换体/ADD COLUMN/新触发器);`v13_advance`、`v13_complete`、`v13_enqueue_effect`、resolve 族、envelope 语义零改动。
3. **token 与 manifest 同语句快照**:required_revision 在装配单条语句内计算并内嵌;settle 写 sessions 只取 `manifest->'required_revision'`。任何第二处独立重算 token 都是漂移源(哈希同源教训的 token 版)。settle 的四层行锁(sessions→tools_meta→三策略活动行;effect 行锁在 complete CAS 点)先于装配(全库锁序与论证见 OQ3——P1-4),语句间窗口封闭;token 七键(含 gen_ver)与 prefix_identity 的 generation 材料在锁内同版。
4. **冻结即不可变**:context artifact 与 section blob 无 UPDATE/DELETE 路径(触发器执法);迟到 decision 只进下一版 manifest;`v13_replay` 永不重跑 assemble;recompute 永不落库写 sessions/artifacts。**被引用即保留**:manifest/blob 的 GC 只清无引用行(引设计审查 F3/F11——保留窗口=策略行,首版不实现 GC 只落策略键,§7)。
5. manifest 只消费内容寻址身份:sections/candidates 记 content_hash;payload_ref 只指不可变正文(v13_goals 行/内容寻址 blob);judgments 记 decision_id(+request_hash+raw_verdict+模板版本+final_action),且只收本版实际消费集(O1 收敛);call 级溯源经 JOIN,零 usage 复制(DP2 契约 #10)。
6. 装配确定性:零时间戳/零随机/零活策略读;同输入两调字节相等(G-ctx5 第四断言的支撑);sections 全序 (prank First=1/Normal=2/Never=3/LastResort=4, section_id),预算截断取**装箱候选**的全序前缀(Never/disabled 先标 skip 不进装箱;run_incl>budget 即 skip,首段可 skip,自身超限必 skip;非法 priority_overrides 值在 cls 层即 pre_skip='invalid_override'——不进装箱/applied、priority 字段回退默认,P1-8,settle 守卫对词表前置 RAISE)。
7. epoch 词表封闭三值,模板属性经触发器固化于行且 UPDATE 被禁(真冻结);悬挂模板引用 fail-closed;post-execute 在本 DP 零生产者(结构性「只能影响后续 turn」)。
8. 新写 SQL 自检(turn 3 教训,实施期机械执行):参数全用、列存在、类型算子层显式(int 算术不做隐式 numeric 往返、jsonb 种子单完整字面量+::jsonb、digest() 一律 encode 成 hex)、块末分号、ACL 全量块在文件真末尾;SECURITY DEFINER 函数(v13_goal_project/v13_artifact_land/v13_blob_land)一律 SET search_path 钉死+体内受信 schema 限定名(public.,双层)+REVOKE PUBLIC;EXECUTE 面:refresh_context 仅授 v13_route,goal_project/双 lander **零运行角色**(分别经触发器与 refresh_context 体内可达——伪造面封死,G4)。函数四件=v13_goal_project/v13_artifact_land/v13_blob_land/v13_refresh_context(末者为 settle 窄入口,P0-3)。

---

## 2. 输入 § 映射

| 设计原文(冻结) | 本 plan 落点 |
|---|---|
| §5.2 每 section 字段族 (kind, cache_scope[Global/Session/None], priority[Never/First/Normal/LastResort], content_hash, est_tokens, payload_ref, churn 计数) | §3.4 manifest.sections[].9 键(OQ4);词表原样;cache_scope 骨架三段各得其所(goal/history=Session,tools=Global)——scope 的经济学执法(前缀缓存分组)归 DP7/DP8,字段与值先落 |
| §5.2 查询侧:query_artifact_id、候选 content_hash/bm25/命中跨度/decision_id | §3.4 query_side 块;骨架=goal 地址+单 echo 候选;bm25/spans/decision_id 空值在场(DP4/5/6 契约行) |
| §5.2 applied 与 skipped 变换都落行(带原因)——审计两分支 | transform 双形态(OQ4);预算截断/Never 优先级/禁用 kind 三种 skip 原因;G-ctx5 第二断言 → C 组 |
| §5.2 三种「回放」显式区分,不得混称 | OQ5 裁决全节;D 组三 fixture(identity 基 mode 判定:版本 bump=recompute,identity 变=fresh);「exact replay 用清单里的旧 verdict,不拿新阈值重释 raw answer(那是 shadow reroute)」写进 README 与 §6 映射;被引用正文 blob 冻结使旧 replay 逐字节可回取(P0-4/G10) |
| §6.1 三 epoch(pre-bind/pre-finalize/post-execute 最小不变量) | OQ7 裁决全节(decisions.epoch+模板列+触发器) |
| §6.1 manifest freeze:final manifest 只消费 freeze 前状态为 complete 的精确 decision_id;缺失、超时、review 带一律走版本化默认分支;迟到结果留在原 request/epoch 下,仅供完全相同信封复用,不得回写已冻结 manifest | OQ3(语句快照=freeze 面+settle 三层行锁窗口封闭+artifacts/blob 不可变)+ OQ7(epoch 固化+真冻结)+ 装配的默认分支机制(OQ3 末段/judgment_defaults);F 组 G-ctx9 复测 |
| §6.1 快照复核(DP1 已落) | 消费清单 #6:probe 换源(goal 平面)后 F 组复测;七键零增删 |
| §6.1 版本化路由(raw answer 不可变;exact replay 用 manifest 旧 verdict,shadow reroute 才用新阈值重释 raw answer) | DP2 已落 shadow 面;DP3 落 exact replay 半边(OQ5)——§6.6 分工闭环 |
| §6.1 请求信封固定 template/model/schema/policy version | envelope 已固定(DP1/DP2);DP3 增量:prefix_identity 固化**生成身份**(generation 策略行的 provider/model/system_blocks_digest)+tools/latch/goal/manifest_version 的身份材料(OQ4;typesafe GUC 不入——判断身份≠生成身份) |
| §5.1 latch 参与前缀身份哈希(§5.6 ForkPrefix);表本体归 DP8 | `v13_latch_digest(uuid)` stub '-none-' 进 prefix_identity 材料;DP8 函数替换(§1.4 DP8 行);emergent 表 P2 不做(§7) |
| §4.7 命中跨度 (doc,offsets) 进 manifest 字段族;chunk/chunks 表本体归 DP4,DP3 定义字段与引用形态 | OQ4 candidates.spans 形态(doc=content_hash 内容寻址,offsets=[[s,e],...] 数组);跨度不是唯一单元/句段边界/重叠合并 = DP4/DP5 装配侧扩展点,字段形态先立 |
| §9 表结构增量:manifest(context artifact 内嵌 jsonb) | §3.1 artifacts 表(ch7 逐字形状,本 DP 首次落地——DP1 M1 未含)+ inline 载 manifest;既有骨架不动原则 = 对 sessions/decisions/judgment_templates 只 ADD COLUMN |
| §10 G-ctx5:manifest 含 §5.2 全字段;applied/skipped 双分支;三种回放可区分;ORDER BY 确定性(并列截断不抖) | §4 B/C/D/E 组逐条;ch10:225–230 的第五断言(est_tokens ≤ 策略行预算)入 C 组 |
| §10 G-ctx9(manifest 语境复测):manifest freeze 后迟到 decision 不得回写;水位不一致弃批重解析;分片哈希 canary(启用时)未声明字段不出现在出站 payload | §4 F 组;canary 半边 = manifest 键集封闭校验(未知键 V3003 拒收)+ judgments 从 decisions/calls 派生不触原始 state(DP2 C3 已执法出站 payload 半边,DP3 引用不重做) |
| §13 教程映射:第 7 章 manifest 指针、第 10 章装配清单 schema(教程正文零改动) | §6;边界=只落实现不改教程 |
| §12 明确不做(emergent/T1/render 呈现偏好等台账项) | §7 全表(台账为源) |
| §6.2 触点 1(goal_hash 必须是版本化目标 artifact) | OQ2(v13_goals 平面+goal_hash 接管);压缩 hint 本体是 DP7 shadow-first,不做 |
| 设计 §11 交付排序第 1 条「manifest 骨架(含 freeze/水位复核/三 epoch)」 | 本 plan 全体 |

---

## 3. 表/函数 DDL 与 SQL 草案

> 文件:`v13/manifest/v13_manifest.sql`(全新增;SQL_LOAD_ORDER 第 6 位纯末尾追加)。**文件内顺序=加载顺序**(§3.1→§3.7 即物理顺序)。整个文件以 BEGIN/COMMIT 包裹(DP2 形制:本文件含 ALTER TABLE 与 OR REPLACE,单事务原子装载;DP1 四文件无事务包裹,前缀切片加载不受影响——`files_through` 逐文件执行,本文件自身的 BEGIN/COMMIT 自洽)。
> 草案级完整度:列/约束/函数签名/关键语句到位,实施者可直接开写;注释标注纪律出处。

### 3.1 goal 平面 + artifacts 表 + 既有表增量

```sql
-- === goal 平面(OQ2):版本化目标 artifact 最小实现。每个 user/message
--     = goal 的一个版本;内容寻址 content_hash=sha256(payload::text),
--     与 DP1 probe 的 goal_hash 公式(DP1 行 1990–1993)逐字节相等——
--     gate A2 硬断言。事件溯源(不落 artifacts:produced_by 效应溯源
--     纪律与用户事件溯源是两种纪律,见 OQ2 论证)。append-only;事件 FK
--     +哈希自证 CHECK(P1-8):行与源事件一对一,写入路径外的篡改不可落行。 ===
CREATE TABLE v13_goals (
  session_id   uuid NOT NULL,
  seq          bigint NOT NULL,             -- 源事件 seq(版本号=编年)
  content_hash text NOT NULL,               -- sha256(payload::text) hex
  payload      jsonb NOT NULL,              -- 源事件 payload 原样
  PRIMARY KEY (session_id, seq),
  FOREIGN KEY (session_id, seq) REFERENCES events (session_id, seq),
  CONSTRAINT v13_goals_hash_selfcheck
    CHECK (content_hash = encode(digest(payload::text, 'sha256'), 'hex'))
);

CREATE FUNCTION v13_goals_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: v13_goals is append-only (% on % seq %)',
    TG_OP, TG_TABLE_NAME, OLD.seq;
END $$;
CREATE TRIGGER trg_v13_goals_append_only
  BEFORE UPDATE OR DELETE ON v13_goals
  FOR EACH ROW EXECUTE FUNCTION v13_goals_append_only();

-- goal 投影触发器:与源事件同事务(append_event 的 UPDATE sessions 已持
-- 会话行锁,本 INSERT 走另一表,零锁序增量)。WHEN 谓词在触发器层过滤,
-- 非用户事件零开销。**SECURITY DEFINER(P1-8/P0-3)**:v13_goals 对运行角色零
-- INSERT 权限且本函数零运行角色 EXECUTE(触发器专用),投影经 owner 身份
-- 落行——route 被攻破也不能伪造 goal 版本;search_path 钉死+体内受信
-- schema 限定名双层(DEFINER 卫生,不变量 8)。
CREATE FUNCTION v13_goal_project() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
BEGIN
  INSERT INTO public.v13_goals (session_id, seq, content_hash, payload)
  VALUES (NEW.session_id, NEW.seq,
          encode(digest(NEW.payload::text, 'sha256'), 'hex'), NEW.payload);
  RETURN NEW;                               -- AFTER 触发器,返回值不参与
END $$;
CREATE TRIGGER trg_events_goal
  AFTER INSERT ON events FOR EACH ROW
  WHEN (NEW.type = 'user/message')
  EXECUTE FUNCTION v13_goal_project();

-- 加载期回填(P1-8):既有 user/message 事件投影进 v13_goals(stage 库
-- DROP-CREATE 为空操作;共享库升级面不丢版本)。ON CONFLICT DO NOTHING 幂等。
INSERT INTO v13_goals (session_id, seq, content_hash, payload)
SELECT e.session_id, e.seq,
       encode(digest(e.payload::text, 'sha256'), 'hex'), e.payload
  FROM events e WHERE e.type = 'user/message'
ON CONFLICT DO NOTHING;

-- 活动 goal 的内容哈希:goal_hash 唯一来源(OQ2)。无 goal 时与 DP1 的
-- coalesce 公式字节相等(sha256(''::text) 的 hex)——水位零漂移。
CREATE FUNCTION v13_goal_hash(p_sid uuid) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce((SELECT g.content_hash FROM v13_goals g
                    WHERE g.session_id = p_sid
                 ORDER BY g.seq DESC LIMIT 1),
                  encode(digest(''::text, 'sha256'), 'hex'));
$$;

-- === artifacts 表(ch7:26-36 逐字形状 + P1-8 自证 CHECK;本 DP 首次落地
--     ——DP1 M1 未含,DP2 只落判断族)。纪律:不可变、内容寻址、produced_by
--     效应溯源、inline 阈值是数据(ch7「放 meta」——meta 表未建,阈值落
--     assemble 策略行,语义等价可调,映射注记 §6)。本 DP 两种 kind:
--     'context'=完整 manifest;'context_section'=section 正文 blob(内容
--     寻址去重=P0-4①;被引用即保留,不变量 4)。 ===
CREATE TABLE artifacts (
  artifact_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_hash text NOT NULL,          -- sha256(inline::text)
  kind         text NOT NULL,          -- 开放词表;本 DP:'context'/'context_section'
  inline       jsonb,                  -- manifest 内嵌(§5.2)/ section 正文
  ref          text,                   -- 大产物外部指针(本 DP 不用,缝保留)
  size         bigint NOT NULL,        -- octet_length(inline::text)
  produced_by  uuid NOT NULL REFERENCES effects (effect_id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT v13_artifacts_selfcheck
    CHECK (inline IS NULL OR
           (content_hash = encode(digest(inline::text, 'sha256'), 'hex')
            AND size = octet_length(inline::text)))
);
CREATE INDEX ix_artifacts_content ON artifacts (content_hash);
CREATE INDEX ix_artifacts_kind ON artifacts (kind, created_at DESC);
-- blob 去重仲裁索引(P0-4①):content_section 行内容寻址唯一——未变
-- section 零新行;ON CONFLICT 推断目标(v13_blob_land)
CREATE UNIQUE INDEX uq_artifacts_context_section
  ON artifacts (content_hash) WHERE kind = 'context_section';

CREATE FUNCTION v13_artifacts_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: artifacts is append-only (% on %)',
    TG_OP, TG_TABLE_NAME;
END $$;
CREATE TRIGGER trg_artifacts_append_only
  BEFORE UPDATE OR DELETE ON artifacts
  FOR EACH ROW EXECUTE FUNCTION v13_artifacts_append_only();

-- produced_by 必须指向 succeeded effect(ch7 纪律;settle 顺序配合:
-- v13_complete 先行——同事务内已可见 status='succeeded',§3.5)
CREATE FUNCTION v13_artifacts_effect_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_status text;
BEGIN
  SELECT status INTO v_status FROM effects WHERE effect_id = NEW.produced_by;
  IF v_status IS DISTINCT FROM 'succeeded' THEN
    RAISE EXCEPTION 'v13: artifact produced_by must reference a succeeded effect (%)',
      NEW.produced_by;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_artifacts_effect_guard
  BEFORE INSERT ON artifacts FOR EACH ROW
  EXECUTE FUNCTION v13_artifacts_effect_guard();

-- === 既有表增量(§1.1 形态二:ADD COLUMN,零重写) ===
ALTER TABLE sessions
  ADD COLUMN context_active_revision jsonb,      -- 上次冻结的 token(OQ1)
  ADD COLUMN context_active_artifact uuid
    REFERENCES artifacts (artifact_id);          -- 非空⇒存在(FK);kind='context'
                                                 -- 由下行守卫执法(O2 P1-2)

-- 指针守卫(O2 P1-2+P0-3):活动指针只许指 kind='context' 的行——悬空/错类
-- 指针在写点被拒(gate G1 负向:指 blob 行被拒/指随机 uuid 撞 FK/置
-- NULL 允许——复位面)。**覆盖 INSERT 不只 UPDATE(P0-3)**:sessions 行
-- 新建时带错类指针同样被拒——UPDATE 面只守已存行,INSERT 是同等写点;
-- 守卫只验 kind,任意伪造已由 lander 收口封死(零 EXECUTE),残余面=
-- 挪向旧合法 artifact,token↔manifest 错配由 ② 自愈。
CREATE FUNCTION v13_ctx_ptr_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_kind text;
BEGIN
  IF NEW.context_active_artifact IS NOT NULL THEN
    SELECT kind INTO v_kind FROM artifacts
     WHERE artifact_id = NEW.context_active_artifact;
    IF v_kind IS DISTINCT FROM 'context' THEN
      RAISE EXCEPTION 'v13: context_active_artifact must reference kind=''context'' (%)',
        NEW.context_active_artifact;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_sessions_ctx_ptr_guard
  BEFORE INSERT OR UPDATE OF context_active_artifact ON sessions
  FOR EACH ROW EXECUTE FUNCTION v13_ctx_ptr_guard();

ALTER TABLE decisions
  ADD COLUMN epoch text NOT NULL DEFAULT 'pre-bind'
    CHECK (epoch IN ('pre-bind','pre-finalize','post-execute'));

ALTER TABLE judgment_templates
  ADD COLUMN epoch text NOT NULL DEFAULT 'pre-bind'
    CHECK (epoch IN ('pre-bind','pre-finalize','post-execute'));

-- epoch 回填触发器(OQ7):模板属性优先,DP1 时代行(template_name NULL)
-- 落默认。INSERT 期一次索引单行读,resolve 面零额外权限(已有 SELECT)。
-- 悬挂模板引用 fail-closed(O1 P1-10):不静默回退 pre-bind——DP2 needed
-- 族先行拒是第一层,本处第二层(拦手拼 INSERT 的悬挂引用)。
-- 调用方显式 epoch 一律忽略(P1-7 防伪造):NULL 分支无条件置 'pre-bind'
-- ——手工 INSERT 带显式 'post-execute' 不可达;post-execute 行必引用
-- 声明该 epoch 的模板(无第三来源)。
CREATE FUNCTION v13_decisions_epoch_fill() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_epoch text;
BEGIN
  IF NEW.template_name IS NOT NULL THEN
    SELECT epoch INTO v_epoch FROM judgment_templates
       WHERE template_name = NEW.template_name
         AND template_version = NEW.template_version;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'v13: decisions references missing template % v%',
        NEW.template_name, NEW.template_version
        USING ERRCODE = 'V3002';
    END IF;
    NEW.epoch := v_epoch;   -- 模板行在档:取其 epoch(NOT NULL 列)
  ELSE
    NEW.epoch := 'pre-bind';  -- P1-7:忽略调用方显式值,强制缺省
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_decisions_epoch
  BEFORE INSERT ON decisions FOR EACH ROW
  EXECUTE FUNCTION v13_decisions_epoch_fill();

-- epoch 真冻结(O1 P1-10):epoch 只许 INSERT 期落定,UPDATE OF epoch 全拒
CREATE FUNCTION v13_epoch_frozen() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v13: decisions.epoch is frozen at insert (%)', OLD.decision_id;
END $$;
CREATE TRIGGER trg_decisions_epoch_freeze
  BEFORE UPDATE OF epoch ON decisions
  FOR EACH ROW EXECUTE FUNCTION v13_epoch_frozen();

-- 语义事件族部分索引:token 的 sem 键与 history 段窗口共用
-- (user/message 已有 ix_events_last_user;本索引补全三族 max(seq) 读)
CREATE INDEX ix_events_semantic ON events (session_id, seq)
  WHERE type IN ('user/message','llm/message','tool/result');
```

### 3.2 装配策略行 + freshness 缝

```sql
-- === 策略种子三行(DP1 v13_policies 载体追加,DP1 §1.3 DP7 行同款纪律:
--     (name,version) PK + at-most-one active;追加=新版本行+同事务翻
--     active,旧版本留档——recompute 的「旧策略」来源即此)。种子单完整
--     JSON 字面量 + 显式 ::jsonb(turn 8 机械教训:禁 text 拼接进 jsonb)。 ===
INSERT INTO v13_policies (name, version, value, active) VALUES
 ('assemble_manifest', 1,
  '{"budget_tokens": 8192,
    "est_bytes_per_token": 4,
    "priority_overrides": {},
    "kinds_disabled": [],
    "inline_max_bytes": 1048576,
    "blob_retention": "referenced-forever"}'::jsonb, true),
  -- budget_tokens:装箱候选 est_tokens 运行和上限(ch10:231「est_tokens ≤
  --   策略行预算」的载体);est_bytes_per_token:est 公式除数(版本化);
  -- priority_overrides:{kind:priority} 测试与运维覆写(Never 的载体);
  -- kinds_disabled:skip 原因 'disabled' 的候选 kind 集;
  -- inline_max_bytes:ch7 inline 阈值(meta 未建,落策略行,§6 注记);
  -- blob_retention:section blob 保留窗口策略键(引设计审查 F11;首版
  --   唯一值=被引用永留——GC 不做,§7;换窗口=新版本行)
 ('generation', 1,
  '{"provider": "mock",
    "model": "mock-1",
    "system_blocks_digest": "-none-"}'::jsonb, true),
  -- 生成身份(prefix_identity 的材料源,O1 P1-7:typesafe GUC 是判断身份
  --   非生成身份,不入材料);骨架值=mock/占位,DP8 render 落真值接管
  --   (§1.4 DP8 行;fail-closed:行缺失/键 NULL → prefix_identity RAISE;版本翻动经 token.gen_ver 追动 freshness——P0-2)
 ('judgment_defaults', 1,
  '{"points": {},
    "actions": ["include", "exclude", "degrade", "fail"]}'::jsonb, true);
  -- 逐判断点默认动作 schema(O1 P1-6,引设计审查 F1):points 键=判断点
  --   名,值={missing,timeout,review}→动作(词表=actions);骨架空表,
  --   DP6(per-chunk Score/存在性 Noul)/DP7(摘要验收)填值;形状由
  --   v13_judgment_defaults_check 执法(§3.3),版本经 token.jdef_ver 追动

-- === required token(OQ1):单条 SELECT、单语句快照。七键全单调(含
--     gen_ver——P0-2:prefix_identity 材料源=generation 策略行,翻版必
--     追动 freshness,漏键=旧身份被继续用)。
--     plpgsql 只为容纳策略缺行时的响亮失败(sql 语言体无 RAISE)。 ===
CREATE FUNCTION v13_context_required(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_asm_ver int; v_jdef_ver int; v_gen_ver int; v_tok jsonb;
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
    'gen_ver',  v_gen_ver)                -- P0-2:第七键
  INTO v_tok;
  RETURN v_tok;
END $$;

-- === freshness 缝激活(消费清单 #1):OR REPLACE 换体,签名/OID/ACL 不动
--     (DP1 已 GRANT v13_route)。active NULL(新会话)恒不新鲜——首次
--     ② 即触发首轮装配。 ===
CREATE OR REPLACE FUNCTION v13_context_fresh(p_sid uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT v13_context_required(p_sid) IS NOT DISTINCT FROM
         (SELECT context_active_revision FROM sessions
           WHERE session_id = p_sid);
$$;
COMMENT ON FUNCTION v13_context_fresh(uuid) IS
  'DP3: required_revision (v13_context_required) vs sessions.context_active_revision. design §5.2/§6.1.';
```

### 3.3 前缀身份 + manifest 校验

```sql
-- === latch 缝(§5.1/§5.6):stub 常量,DP8 函数替换(§1.4 DP8 行)。
--     与 DP1 对 DP3 的 context_fresh stub 同一手法——缝即常量函数。 ===
CREATE FUNCTION v13_latch_digest(p_sid uuid) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT '-none-'::text $$;
COMMENT ON FUNCTION v13_latch_digest(uuid) IS
  'DP8 seam: latches join prefix identity here (design §5.1/§5.6).';

-- === 前缀身份(§5.6 骨架半边):sha256 over canonical jsonb::text。
--     材料不含 token(recompute 可继承身份,ch14:93);tools_digest 复用
--     canonical_state 的 tools 投影(哈希同源,零第二实现)。
--     **生成身份换源(O1 P1-7)**:provider/model 从版本化 generation 策略
--     行读(fail-closed:行缺失/键 NULL → RAISE),不再读 typesafe GUC
--     ——GUC 是判断(Jev)身份;system_blocks_digest 骨架 '-none-'
--     (DP8 render 落真值)。goal_hash 留在材料的成本记附 A #10。哈希材料
--     键集恒九键(全部经显式非空检查——strip_nulls 移除,P1-9:静默丢
--     NULL 键=哈希输入漂移面;tools_meta 缺行 RAISE 与 generation 同姿势)。 ===
CREATE FUNCTION v13_prefix_identity(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_mat jsonb; v_gen jsonb; v_trev int;
BEGIN
  SELECT value INTO v_gen FROM v13_policies
   WHERE name = 'generation' AND active;
  IF v_gen IS NULL OR v_gen->>'provider' IS NULL
     OR v_gen->>'model' IS NULL
     OR v_gen->>'system_blocks_digest' IS NULL THEN
    RAISE EXCEPTION 'v13: no active generation policy (seed lost?)';
  END IF;
  SELECT revision INTO v_trev FROM v13_tools_meta WHERE singleton;
  IF v_trev IS NULL THEN
    RAISE EXCEPTION 'v13: v13_tools_meta singleton row missing';  -- P1-9
  END IF;
  SELECT jsonb_build_object(                    -- 去 strip_nulls(P1-9):
    'provider',  v_gen->>'provider',            -- 九键材料经上方显式非空
    'model',     v_gen->>'model',               -- 检查结构性非空,哈希输入
    'system_blocks_digest', v_gen->>'system_blocks_digest',
    'tools_rev', v_trev,
    'tools_digest', encode(digest(
      coalesce((v13_canonical_state(p_sid) -> 'tools')::text, ''),
      'sha256'), 'hex'),
    'goal_hash', v13_goal_hash(p_sid),
    'latch_digest', v13_latch_digest(p_sid),
    'manifest_version', 1))
  INTO v_mat;
  RETURN encode(digest(v_mat::text, 'sha256'), 'hex');
END $$;

-- === manifest 形状校验(OQ6):V3003 手写族,七层键集恰等(G-ctx9 canary
--     半边:未声明字段根本不进 manifest)+ 词表 + 类型 + 64hex + 数值域;
--     null 枚举穿透全数封死(IN ... IS NOT TRUE / IS DISTINCT FROM 形态,
--     DP2 criteria 列卫同款)。求值顺序纪律:jsonb_object_keys 只在
--     jsonb_typeof='object' 确认后的独立 IF 中调用(SQL OR 不保证短路)。
--     settle 的落行前执法。**全部 RAISE 显式 USING ERRCODE='V3003'(P1-10
--     ——SQLSTATE 可捕获,消息文本仅人读);transform 分支键集精确恰等+
--     「违规时 RAISE」形态(P0-1:旧 CASE 产违规条件却套 IS NOT TRUE,合法
--     {applied:true,name:'verbatim'} 被拒、非法放行,布尔反转已修)**。 ===
CREATE FUNCTION v13_manifest_validate(p_manifest jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE s jsonb; j jsonb; c jsonb; k text;
BEGIN
  IF p_manifest IS NULL OR jsonb_typeof(p_manifest) IS DISTINCT FROM 'object'
  THEN
    RAISE EXCEPTION 'v13: manifest must be a jsonb object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  -- [层 1] 外层键集恰等(字典序串见附 B 类型算子层复核)
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_manifest) k)
     IS DISTINCT FROM
     'judgments,manifest_version,policy,prefix_identity,query_side,'
     'replay,required_revision,sections,session_id,turn_no' THEN
    RAISE EXCEPTION 'v13: manifest top-level key set mismatch (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (p_manifest->>'manifest_version')::int IS DISTINCT FROM 1
     -- IS DISTINCT FROM:null 安全——旧 <> 形态对缺失键静默放行(O1 P1-5)
     OR p_manifest->>'session_id' IS NULL
     OR p_manifest->>'session_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     OR (p_manifest->>'turn_no')::int IS NULL
     OR (p_manifest->>'turn_no')::int < 0
     OR p_manifest->>'prefix_identity' IS NULL
     OR p_manifest->>'prefix_identity' !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: manifest anchor/identity shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  -- [层 2] policy 块(4 键)
  IF jsonb_typeof(p_manifest->'policy') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.policy must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_manifest->'policy') k)
     IS DISTINCT FROM
     'assemble_version,budget_tokens,est_bytes_per_token,'
     'judgment_defaults_version'
     OR (p_manifest->'policy'->>'assemble_version')::int IS NULL
     OR (p_manifest->'policy'->>'assemble_version')::int < 1
     OR (p_manifest->'policy'->>'judgment_defaults_version')::int IS NULL
     OR (p_manifest->'policy'->>'judgment_defaults_version')::int < 1
     OR (p_manifest->'policy'->>'budget_tokens')::int IS NULL
     OR (p_manifest->'policy'->>'budget_tokens')::int < 0
     OR (p_manifest->'policy'->>'est_bytes_per_token')::int IS NULL
     OR (p_manifest->'policy'->>'est_bytes_per_token')::int <= 0 THEN
    RAISE EXCEPTION 'v13: manifest.policy shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  -- [层 3] required_revision 块(七键,含 gen_ver——P0-2)
  IF jsonb_typeof(p_manifest->'required_revision') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.required_revision must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'required_revision') k)
     IS DISTINCT FROM 'asm_ver,dec,gen_ver,goal,jdef_ver,sem,tools_rev'
     OR (p_manifest->'required_revision'->>'sem')::bigint IS NULL
     OR (p_manifest->'required_revision'->>'sem')::bigint < -1
     OR (p_manifest->'required_revision'->>'dec')::bigint IS NULL
     OR (p_manifest->'required_revision'->>'dec')::bigint < 0
     OR p_manifest->'required_revision'->>'goal' IS NULL
     OR p_manifest->'required_revision'->>'goal' !~ '^[0-9a-f]{64}$'
     OR (p_manifest->'required_revision'->>'tools_rev')::int IS NULL
     OR (p_manifest->'required_revision'->>'tools_rev')::int < 0
     OR (p_manifest->'required_revision'->>'asm_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'asm_ver')::int < 1
     OR (p_manifest->'required_revision'->>'jdef_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'jdef_ver')::int < 1
     OR (p_manifest->'required_revision'->>'gen_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'gen_ver')::int < 1 THEN
    RAISE EXCEPTION 'v13: manifest.required_revision shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  -- [层 4] replay 块(exact_replay 只存在于 v13_replay 视图,不进校验)
  IF jsonb_typeof(p_manifest->'replay') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.replay must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'replay') k)
     IS DISTINCT FROM 'mode,prior_artifact_id'
     OR (p_manifest->'replay'->>'mode') IN ('fresh','recompute') IS NOT TRUE
  THEN
    RAISE EXCEPTION 'v13: manifest.replay shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  -- [层 5] sections:非空数组,每段 9 键恰等 + 词表/64hex/数值域
  IF jsonb_typeof(p_manifest->'sections') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_manifest->'sections') = 0 THEN
    RAISE EXCEPTION 'v13: manifest.sections must be a non-empty array (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR s IN SELECT jsonb_array_elements(p_manifest->'sections') LOOP
    IF jsonb_typeof(s) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section must be an object (V3003)'
      USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(s) k)
       IS DISTINCT FROM
       'cache_scope,churn,content_hash,est_tokens,kind,payload_ref,'
       'priority,section_id,transform' THEN
      -- 字典序修正(P0-3):churn 先于 content_hash(h<o)——旧串全绿 fixture 皆红
      RAISE EXCEPTION 'v13: section key set mismatch for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (s->>'cache_scope') IN ('Global','Session','None') IS NOT TRUE
       OR (s->>'priority') IN ('Never','First','Normal','LastResort') IS NOT TRUE
       OR s->>'section_id' IS NULL OR length(btrim(s->>'section_id')) = 0
       OR s->>'section_id' IS DISTINCT FROM s->>'kind'
       OR s->>'content_hash' IS NULL
       OR s->>'content_hash' !~ '^[0-9a-f]{64}$'
       OR (s->>'churn')::int IS NULL OR (s->>'churn')::int < 0
       OR (s->>'est_tokens')::int IS NULL OR (s->>'est_tokens')::int < 0 THEN
      RAISE EXCEPTION 'v13: section vocabulary/hash violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    -- payload_ref 判别对象:goal⇒seq(≥-1);blob⇒64hex(词表封闭,DP4–DP8
    -- 增 kind 时同步扩词表+manifest_version)
    IF jsonb_typeof(s->'payload_ref') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section payload_ref must be an object for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (s->'payload_ref'->>'kind') IN ('goal','blob') IS NOT TRUE
       OR (CASE WHEN s->'payload_ref'->>'kind' = 'goal'
                THEN (s->'payload_ref'->>'seq')::int IS NULL
                     OR (s->'payload_ref'->>'seq')::int < -1
                ELSE s->'payload_ref'->>'content_hash' IS NULL
                     OR s->'payload_ref'->>'content_hash' !~ '^[0-9a-f]{64}$'
           END) IS TRUE THEN
      RAISE EXCEPTION 'v13: section payload_ref shape violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    -- transform:typeof 先行两独立 IF(jsonb_object_keys 禁止进 OR 链——
    -- SQL OR 不保证短路);分支键集精确恰等+词表,CASE 产**违规条件**、
    -- 外层 IS TRUE 才 RAISE——与 payload_ref 同款「违规时 RAISE」形态
    -- (P0-1:旧形态 CASE 内违规条件却套 IS NOT TRUE,布尔反转——合法
    -- {applied:true,name:'verbatim'} 被拒、非法放行,已修)。
    IF jsonb_typeof(s->'transform') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section transform must be an object for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF jsonb_typeof(s->'transform'->'applied') IS DISTINCT FROM 'boolean' THEN
      -- jsonb_typeof 同时拒缺键(NULL)与非布尔类型(字符串 'true' 焙劣)
      RAISE EXCEPTION 'v13: section transform.applied must be boolean for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (CASE WHEN (s->'transform'->>'applied')::boolean
             THEN (SELECT string_agg(k, ',' ORDER BY k)
                     FROM jsonb_object_keys(s->'transform') k)
                  IS DISTINCT FROM 'applied,name'
                  OR (s->'transform'->>'name')
                     IN ('verbatim','catalog_digest') IS NOT TRUE
             ELSE (SELECT string_agg(k, ',' ORDER BY k)
                     FROM jsonb_object_keys(s->'transform') k)
                  IS DISTINCT FROM 'applied,reason'
                  OR (s->'transform'->>'reason')
                     IN ('budget','priority_never','disabled','invalid_override')
                     IS NOT TRUE
        END) IS TRUE THEN
      RAISE EXCEPTION 'v13: section transform shape violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
  -- [层 6] query_side:键集恰等 + 候选行四键恰等(值可空,骨架无生产者)
  IF jsonb_typeof(p_manifest->'query_side') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.query_side must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'query_side') k)
     IS DISTINCT FROM 'candidates,query_artifact_id'
     OR jsonb_typeof(p_manifest->'query_side'->'candidates')
        IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: query_side field family missing (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR c IN SELECT jsonb_array_elements(
             p_manifest->'query_side'->'candidates') LOOP
    IF jsonb_typeof(c) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: candidate must be an object (V3003)'
      USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(c) k)
       IS DISTINCT FROM 'bm25,content_hash,decision_id,spans'
       OR c->>'content_hash' IS NULL
       OR c->>'content_hash' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(c->'spans') IS DISTINCT FROM 'array' THEN
      RAISE EXCEPTION 'v13: candidate shape violation (V3003)'
      USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
  -- [层 7] judgments:消费集行,7 键恰等;词表封闭(骨架恒 [],形状先行)
  IF jsonb_typeof(p_manifest->'judgments') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: manifest.judgments must be an array (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR j IN SELECT jsonb_array_elements(p_manifest->'judgments') LOOP
    IF jsonb_typeof(j) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: judgment row must be an object (V3003)'
      USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(j) k)
       IS DISTINCT FROM
       'decision_id,epoch,final_action,raw_verdict,request_hash,'
       'template_name,template_version'
       OR j->>'decision_id' IS NULL
       OR j->>'request_hash' IS NULL
       OR j->>'request_hash' !~ '^[0-9a-f]{64}$'
       OR (j->>'epoch') IN ('pre-bind','pre-finalize','post-execute') IS NOT TRUE
       OR j->>'raw_verdict' IS NULL
       OR (j->>'final_action')
          IN ('recorded','include','exclude','degrade','fail') IS NOT TRUE
       -- 模板对约束:(name NULL) ⟺ (version NULL);在档时 version≥1
       -- (DP2 decisions 列约束同款;DP1 时代行可入消费集时不破形状)
       OR NOT (  (  j->>'template_name' IS NULL
                  AND j->>'template_version' IS NULL )
              OR (  j->>'template_name' IS NOT NULL
                  AND (j->>'template_version')::int IS NOT NULL
                  AND (j->>'template_version')::int >= 1 ) ) THEN
      RAISE EXCEPTION 'v13: judgment row shape violation (V3003)'
      USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
END $$;

-- === 逐判断点默认动作校验器(OQ3 末段/O1 P1-6,引设计审查 F1):执法
--     judgment_defaults 策略行形状——键集恰等{points,actions};actions
--     词表恰等四值;每点三态键集恰等{missing,timeout,review}且动作在
--     词表内。null 穿透同封(IS NOT TRUE)。骨架 gate B7 直调;**settle 面
--     已接线(§3.5 策略守卫 PERFORM 调用——P1-5:非法 defaults 被 active
--     后 refresh 在装配前即拒,结构性执法,不靠测试纪律)**;DP6/DP7
--     的策略追加消费侧同调(fail-closed 先于装载)。 ===
CREATE FUNCTION v13_judgment_defaults_check(p_value jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE v_pt text; v_act jsonb;
BEGIN
  IF p_value IS NULL OR jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: judgment_defaults must be a jsonb object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_value) k)
     IS DISTINCT FROM 'actions,points' THEN
    RAISE EXCEPTION 'v13: judgment_defaults key set mismatch (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_value->'actions') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_value->'actions') <> 4
     OR NOT (p_value->'actions')
         @> '["include","exclude","degrade","fail"]'::jsonb THEN
    RAISE EXCEPTION 'v13: judgment_defaults actions vocabulary violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_value->'points') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: judgment_defaults.points must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR v_pt, v_act IN SELECT key, value FROM jsonb_each(p_value->'points') LOOP
    IF jsonb_typeof(v_act) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: judgment_defaults point % must be an object (V3003)', v_pt
      USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(v_act) k)
       IS DISTINCT FROM 'missing,review,timeout'
       OR (v_act->>'missing')
          IN ('include','exclude','degrade','fail') IS NOT TRUE
       OR (v_act->>'timeout')
          IN ('include','exclude','degrade','fail') IS NOT TRUE
       OR (v_act->>'review')
          IN ('include','exclude','degrade','fail') IS NOT TRUE THEN
      RAISE EXCEPTION 'v13: judgment_defaults point % shape violation (V3003)', v_pt
      USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
END $$;
```

### 3.4 `v13_assemble_manifest` —— 装配(单语句单快照)

```sql
-- === 装配(OQ3/OQ4/OQ5):单条 SQL 语句(MATERIALIZED CTE 族,DP2
--     turn 7 #47 单快照纪律)——required token 与全部 section 内容同
--     语句快照,freeze 面原子。p_policy_version NULL=活动版本(唯一可
--     settle 形态);给定旧版本号=recompute(只读返回,OQ5)。
--     确定性:零时间戳/零随机/策略经版本参数;装箱(P0-1 重写):Never/
--     disabled 先标 skip 不进装箱,候选按全序求含自身运行和,超预算即
--     skip(首段可 skip,自身超限必 skip,applied 恒为候选连续前缀)。 ===
CREATE FUNCTION v13_assemble_manifest(p_sid uuid, p_policy_version int DEFAULT NULL)
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
  SELECT v13_prefix_identity(p_sid) AS pid  -- 单次调用,外层与 mode 同源
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
  -- 骨架三段(DP4–DP7 只在此 UNION ALL 增臂,结构不动);单一材料列 mat:
  -- content_hash/est/payload_ref/settle 的 blob 冻结四面同材料(哈希同源)
  SELECT 'goal'::text AS section_id, 'goal'::text AS kind,
         'Session'::text AS cache_scope, 'First'::text AS def_prio,
         v13_goal_hash(p_sid) AS content_hash,
         octet_length(coalesce((SELECT g.payload::text FROM v13_goals g
                           WHERE g.session_id = p_sid
                        ORDER BY g.seq DESC LIMIT 1), '')) AS bytes,
         coalesce((SELECT max(seq) FROM v13_goals
                    WHERE session_id = p_sid), -1) AS gseq,
         NULL::jsonb AS mat               -- goal 材料即 v13_goals 行(payload_ref 指 seq)
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
  -- 分层一(P0-1+P1-8):有效优先级/est/显式四值 prank;Never/disabled
  -- 先标定(pre_skip,不进装箱);**非法 override 值 cls 层即 pre_skip=
  -- 'invalid_override'**(键在档而值词表外才触发:不进装箱/applied、
  -- eff_priority 回退 def_prio 保持词表内;settle 守卫另在装配前 RAISE
  -- ——双层,不靠 validate 收口;其行 prank 虽 NULL 但被 skip,NULLS
  -- LAST 仅影响 skip 行输出序);payload_ref:goal→v13_goals 行,其余→
  -- 内容寻址 blob(P0-4①,与段 content_hash 恒等)
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
  -- 分层二(P0-1 重写):装箱候选(pre_skip IS NULL)按全序求**含自身**
  -- 运行和 run_incl。run_incl>budget ⇔ running_applied+est>budget ⇒
  -- skip;自身 est>budget 必 skip;est≥0 ⇒ run_incl 单调不减 ⇒ applied
  -- 恒为候选连续前缀(截断语义)。旧 pre_cum(不含自身、含 Never/disabled)
  -- 的两处缺陷就此封死。
  SELECT c.section_id,
         sum(c.est_tokens) OVER (ORDER BY c.prank, c.section_id
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_incl
  FROM cls c
  WHERE c.pre_skip IS NULL
), ordered AS MATERIALIZED (
  SELECT c.*,
         (p.section_id IS NULL) AS prior_missing,  -- 首版 churn=0(gate 对齐)
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
    'candidates', (SELECT coalesce(jsonb_agg(c ORDER BY c->>'content_hash'),
                                   '[]'::jsonb)
                     FROM (SELECT jsonb_build_object(
                             'content_hash', ga.a->>'content_hash',
                             'bm25',  NULL,
                             'spans', '[]'::jsonb,
                             'decision_id', NULL) AS c
                             -- DP4/DP5/DP6 填充缝:bm25/spans/decision_id
                             -- 形态立法见 OQ4(doc=content_hash,§4.7);
                             -- 骨架 echo 候选仅 goal 自身
                             FROM goal_addr ga
                            WHERE ga.a ? 'content_hash') c)
  ) AS q
), jud AS MATERIALIZED (
  -- 消费集反向收集(P0-4②/O1 P1-9):只收本版 sections/candidates 实际
  -- 引用的 decisions(candidates.decision_id 的 IN 集;DP6 落消费段时
  -- sections 侧引用并入同一集)。完整判断历史留 decisions/judgment_calls
  -- 查询面;长 session 的 manifest 不再无界增长。每行记 raw_verdict 原文
  -- +模板版本+final_action(骨架消费集空,'recorded' 为词表占位且不可达,
  -- DP6 填真值)。文本 IN 比较:uuid::text 与 candidate 存值同形,零 cast 面。
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
    -- P1-6 complete 谓词(DP1 v13_gap 命中条件逐字同款——契约 8;jsonb-null
    -- 边界与 DP1 面一致不另立):被引用而未完成的 decision(missing/timeout/
    -- review)滤出 judgments——raw_verdict=null 不可能进 manifest(refresh
    -- 不因默认分支炸);其默认动作的 trace 载体=段/候选级(DP6/DP7 契约行)
    AND d.decision_id::text IN (
    SELECT cand->>'decision_id'
    FROM qside, jsonb_array_elements(qside.q->'candidates') cand
    WHERE cand->>'decision_id' IS NOT NULL)
), mode AS MATERIALIZED (
  -- identity 基判定(O1 gate 对齐):prior 缺失或 prefix_identity 变 ⇒
  -- fresh;否则(含策略版本 bump)⇒ recompute。FROM pri 补齐(P0-2:
  -- 旧体引用 pri 无 FROM,不可解析)
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
                                  'prior_artifact_id', (SELECT aid FROM pri))
);
$$;
```

> 实施注记:(a) **装箱分层**(P0-1 重写):`cls` 先标定 Never/disabled/非法 override(P1-8:pre_skip='invalid_override',不进装箱/applied,eff_priority 回退默认)并显式四值 prank;`packed` 对候选按全序求**含自身**运行和 run_incl,`run_incl>budget ⇔ running_applied+est>budget` 即 skip——首段可被 skip(旧 pre_cum 缺陷一)、自身 est>budget 必 skip(缺陷二)、Never/disabled 不再占用预算(缺陷三);est≥0 ⇒ run_incl 单调不减 ⇒ applied 集合恒为候选的连续前缀。(a2) **sections 数组序在聚合内显式钉死**(`jsonb_agg(section ORDER BY prank, section_id)`)——CTE 自身的 ORDER BY 不保证传递进外层聚合,聚合内 ORDER BY 是唯一确定性形态(turn 8 类型/算子层教训的同族:不依赖引擎未承诺行为);prank NULL 的段(非法 override,P1-8)已被 cls 层 pre_skip,排 NULLS LAST 仅影响 skip 行输出序。(b) `final_sec` 的 transform 三分支对应 OQ3 的「版本化默认分支」实例;`sec_src.mat` 单一材料列:content_hash/est/payload_ref/settle 的 blob 冻结四面同材料(哈希同源)。(c) 空 goal(无 user/message)时 goal 段 content_hash=sha256('')——与 token.goal 同源(v13_goal_hash 单一来源)。(d) est 公式整数算术 `((bytes+div-1)/div)`(类型算子层教训:无 numeric 往返、无隐式 cast);除数≤0 由 settle 守卫前置拦截(V3003,F5(iii));直调装配遇非法策略行以 22012 除零响亮失败(文档化边界)。(e) `kinds_off @> to_jsonb(kind)` 为 jsonb 数组包含判断,种子 `[]` 恒 false。(f) `ident`/`mode` 共用单次 prefix_identity 调用(CTE 单点,哈希同源);mode 判定 identity 基:策略版本 bump 不动 identity 材料 ⇒ recompute(旧「版本不等即 fresh」判据作废,附 A #14)。(g) `jud` 只收消费集(骨架恒空)且 **complete-only**(P1-6:answer 非空∧status∈answered/cached,DP1 v13_gap 同款);final_action 骨架值 'recorded' 为词表占位,消费集空 ⇒ 不可达,DP6 落消费段时改真实动作;jud 的 IN 集用文本比较(uuid::text),零 cast 面。

### 3.5 `v13_artifact_land`/`v13_blob_land`/`v13_refresh_context` —— 落行器与 settle(worker 入口)

```sql
-- === 落行函数两件(P1-8/P0-3 受控写入):artifacts 对运行角色零直接 INSERT
--     且零直接 EXECUTE——写入只经 SECURITY DEFINER 落行器,而落行器唯一
--     可达路径=v13_refresh_context(SECURITY DEFINER 窄入口)体内(P0-3:
--     旧版直授 v13_route EXECUTE——route 可用任意 succeeded effect 伪造
--     context 再挪指针,已封死);search_path 钉死+体内受信 schema 限定名
--     (public.)双层+REVOKE PUBLIC+零运行角色授权(§3.7,G4 owner 分离)。
--     守卫触发器仍挂表(纵深防御:owner 路径与任何未来直写路径同受执法)。 ===
CREATE FUNCTION v13_artifact_land(p_effect uuid, p_kind text, p_inline jsonb)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE v_art uuid; v_status text;
BEGIN
  IF p_kind IS DISTINCT FROM 'context' THEN
    RAISE EXCEPTION 'v13: v13_artifact_land only lands kind=''context''';
  END IF;
  SELECT status INTO v_status FROM public.effects WHERE effect_id = p_effect;
  IF v_status IS DISTINCT FROM 'succeeded' THEN    -- belt(触发器同执法)
    RAISE EXCEPTION 'v13: artifact produced_by must reference a succeeded effect (%)',
      p_effect;
  END IF;
  v_art := gen_random_uuid();
  INSERT INTO public.artifacts (artifact_id, content_hash, kind, inline, size,
                         produced_by)
  VALUES (v_art,
          encode(digest(p_inline::text, 'sha256'), 'hex'),
          p_kind, p_inline, octet_length(p_inline::text), p_effect);
  RETURN v_art;
END $$;

-- section blob 落行(P0-4①):内容寻址 upsert——uq_artifacts_context_section
-- 天然去重(未变 section 零新行);返回 content_hash(与 manifest 段哈希
-- 恒等,refresh 的 belt 断言消费)。**succeeded belt 与 artifact_land 同款
-- (P1-13:不裸信触发器——owner 路径自带同判)**。
CREATE FUNCTION v13_blob_land(p_effect uuid, p_inline jsonb)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE v_h text; v_status text;
BEGIN
  SELECT status INTO v_status FROM public.effects WHERE effect_id = p_effect;
  IF v_status IS DISTINCT FROM 'succeeded' THEN
    RAISE EXCEPTION 'v13: artifact produced_by must reference a succeeded effect (%)',
      p_effect;
  END IF;
  v_h := encode(digest(coalesce(p_inline::text, ''), 'sha256'), 'hex');
  INSERT INTO public.artifacts (artifact_id, content_hash, kind, inline, size,
                         produced_by)
  VALUES (gen_random_uuid(), v_h, 'context_section', p_inline,
          octet_length(coalesce(p_inline::text, '')), p_effect)
  ON CONFLICT (content_hash) WHERE kind = 'context_section' DO NOTHING;
  RETURN v_h;
END $$;

-- === refresh settle(OQ3/P0-3):claim 后由 worker 在 route 连接单事务调用。
--     **SECURITY DEFINER 窄入口(P0-3)**:对 v13_route 只暴露本函数——
--     入参仅 (effect,attempt,fence),manifest 恒为体内装配+validate 产物,
--     零注入面;落行器零运行角色 EXECUTE,唯一可达=本函数体内。
--     顺序:入口校验(kind/session)→ fence belt → 三层行锁(sessions→
--     tools_meta→三策略活动行;effect 行锁在 complete CAS 点——全库锁序
--     与论证见 OQ3)→ 策略形状守卫(含 judgment_defaults 校验器接线,
--     P1-5)→ 装配(读)→ validate → inline 超限(与 validate 同点,
--     complete 前——P1-11)→ complete(CAS 权威)→ blob 冻结 → artifact
--     落行 → result 补挂 → sessions 指针。全部本地读写,零外部 IO(不变量
--     1)。重试幂等:complete 返 'stale'/'replay' 时早期返回——artifact
--     INSERT 未发生,零双写。 ===
CREATE FUNCTION v13_refresh_context(p_effect uuid, p_attempt int, p_fence bigint)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE v_row effects; v_sid uuid; v_manifest jsonb; v_art uuid; v_out text;
        v_budget int; v_div int; v_inline_max bigint;
        v_ovr jsonb; v_off jsonb;
        v_hist jsonb; v_tools jsonb; v_hh text; v_th text; v_mh text;
BEGIN
  SELECT * INTO v_row FROM public.effects WHERE effect_id = p_effect;
                                              -- advisory 读(无锁):kind/
                                              -- session 校验用;CAS 权威在 complete
  IF v_row.effect_id IS NULL THEN
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  IF v_row.kind IS DISTINCT FROM 'context_refresh' THEN
    RAISE EXCEPTION 'v13: refresh settle on non-context_refresh effect %', p_effect;
  END IF;
  v_sid := v_row.session_id;   -- session 恒取自 effect 行:零调用方注入面

  -- fence belt(P0-3 窄入口可读性;权威 CAS 仍在 complete):claimed 行的
  -- attempt/fence 不匹配 → 直接 'stale'(与 complete 结论一致,仅前移);
  -- 终态行不过此 belt,走完整流程由 complete 判 'replay'(F5(i) 幂等面)
  IF v_row.status IS NOT DISTINCT FROM 'claimed'
     AND (v_row.attempt_no IS DISTINCT FROM p_attempt
          OR v_row.fence IS DISTINCT FROM p_fence) THEN
    RETURN 'stale';
  END IF;

  -- 三层行锁先行(OQ3/P1-4):sessions(阻断并发 append_event/advance/
  -- complete——DP1 全树序 sessions 先行)→ tools_meta(阻断并发目录 bump)
  -- → 三族策略活动行(阻断并发翻版;name 序定序加锁,并发 settle 同序)
  -- ——此后策略守卫/装配/token/身份四读同版(锁行即定版,论证 OQ3);
  -- effect 行锁不在此取(全库锁序 sessions→…→effects,OQ3 论证)
  PERFORM 1 FROM public.sessions WHERE session_id = v_sid FOR UPDATE;
  PERFORM 1 FROM public.v13_tools_meta WHERE singleton FOR UPDATE;
  PERFORM 1 FROM public.v13_policies
   WHERE name IN ('assemble_manifest','generation','judgment_defaults')
     AND active
   ORDER BY name FOR UPDATE;

  -- 策略形状守卫(F5(iii) 全键扩,P1-5/P1-8):数值三键+overrides 形状与
  -- 值词表+kinds_disabled 形状+judgment_defaults 校验器接线——一切在装配
  -- 前 RAISE V3003(22012 除零路径在 settle 面不可达;非法 defaults 不再
  -- 能「被 active 且 refresh 成功」;非法 override 不再只靠 validate 收口;
  -- 直调装配的文档化边界见 §3.4 注 d)
  SELECT (value->>'budget_tokens')::int,
         (value->>'est_bytes_per_token')::int,
         (value->>'inline_max_bytes')::bigint,
         value->'priority_overrides',
         value->'kinds_disabled'
    INTO v_budget, v_div, v_inline_max, v_ovr, v_off
   FROM public.v13_policies WHERE name = 'assemble_manifest' AND active;
  IF v_div IS NULL OR v_div <= 0 OR v_budget IS NULL OR v_budget < 0
     OR v_inline_max IS NULL OR v_inline_max <= 0
     OR jsonb_typeof(v_ovr) IS DISTINCT FROM 'object'
     OR (SELECT bool_or((o.value #>> '{}')
             IN ('Never','First','Normal','LastResort') IS NOT TRUE)
           FROM jsonb_each(v_ovr) o) IS TRUE
     OR jsonb_typeof(v_off) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: assemble_manifest policy shape invalid'
      USING ERRCODE = 'V3003';
  END IF;
  PERFORM public.v13_judgment_defaults_check(
    (SELECT value FROM public.v13_policies
      WHERE name = 'judgment_defaults' AND active));  -- P1-5 接线

  -- 装配(读面;语句快照即 freeze 面,token 内嵌)
  v_manifest := public.v13_assemble_manifest(v_sid, NULL);  -- NULL=活动版本,唯一 settle 形态
  PERFORM public.v13_manifest_validate(v_manifest);         -- V3003 fail-closed

  -- inline 超限先行于 complete(P1-11:与 validate 同点——失败路径不经
  -- 「succeeded 再回滚」;整体事务回滚 ⇒ effect 回 claimed,worker 契约
  -- complete('failed') 或 lease 过期 unknown 墙接管,G2 断言零 complete)
  IF octet_length(v_manifest::text) > v_inline_max THEN
    RAISE EXCEPTION 'v13: manifest exceeds inline_max_bytes (route to ref: DP4+)'
      USING ERRCODE = 'V3003';
  END IF;

  -- 结算先行(DP1 v13_complete:CAS/终态重入守卫/claimed 前置/effect_done;
  -- effect 行锁在此取得——DP1 冻结全树序 sessions→effect 的第二跳)
  v_out := public.v13_complete(p_effect, p_attempt, p_fence, 'succeeded',
              jsonb_build_object(
                'required_revision', v_manifest->'required_revision',
                'sections', jsonb_array_length(v_manifest->'sections')));
  IF v_out IS DISTINCT FROM 'accepted' THEN
    RETURN v_out;                       -- 'stale'/'replay':零写返回(幂等)
  END IF;

  -- section blob 冻结(P0-4①):history/tools 正文经内容寻址落行(去重);
  -- 材料重取自 canonical_state——三层行锁保证与装配快照同材料;belt:重算
  -- 哈希≠manifest 段哈希 ⇒ V3003(锁失效的不可能路径,防御性)。goal 段
  -- 无 blob:v13_goals 行即不可变正文(P1-8)。
  v_hist  := public.v13_canonical_state(v_sid) -> 'messages';
  v_tools := public.v13_canonical_state(v_sid) -> 'tools';
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'history';
  v_hh := public.v13_blob_land(p_effect, v_hist);
  IF v_hh IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: history blob hash drift vs manifest section'
      USING ERRCODE = 'V3003';
  END IF;
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'tools';
  v_th := public.v13_blob_land(p_effect, v_tools);
  IF v_th IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: tools blob hash drift vs manifest section'
      USING ERRCODE = 'V3003';
  END IF;

  -- artifact 落行(DEFINER 受控写入)+ result 补挂 + sessions 指针(OQ1/OQ3)
  v_art := public.v13_artifact_land(p_effect, 'context', v_manifest);
  UPDATE public.effects SET result = coalesce(result,'{}'::jsonb) ||
           jsonb_build_object('context_artifact_id', v_art)
   WHERE effect_id = p_effect;
  UPDATE public.sessions
     SET context_active_revision = v_manifest->'required_revision',
         context_active_artifact = v_art
   WHERE session_id = v_sid;
  RETURN 'accepted';
END $$;
```

> 顺序论证:validate 与 inline 超限都在 complete **之前**(P1-11——失败路径不经「succeeded 再回滚」,effect 保持 claimed);artifact/blob 落行在 complete 之后——v13_artifacts_effect_guard 读同事务内已可见的 status='succeeded'(若守卫先行会拒 claimed 行,ch7 纪律的字面执法,ch7:46-47;DEFINER 落行器内置同款 belt,blob_land 同判——P1-13)。**窄入口与锁序(P0-3/P1-4)**:本函数是 settle 唯一入口且 SECURITY DEFINER(体内受信 schema 限定名)——运行角色可传仅 (effect,attempt,fence),manifest 零注入面;三层行锁+effect 锁(complete 内)的全库一致序与「不先行取 effect 锁」论证见 OQ3;F6 双并发 gate 实证零 40P01
>
> **refresh worker 契约(SQL 侧;进程移植不在本 DP,DP1 §7 同款)**:worker 以 v13_route_login 连接 `v13_claim(worker, lease_ms)` 领 kind='context_refresh' → `v13_refresh_context(effect_id, attempt_no, fence)`;返回 'accepted' 即毕;**装配异常(V3003/其他)不得吞**——捕获后 `v13_complete(effect, attempt, fence, 'failed', {code})`:DP1 ② 的 failed/cancelled 分支(attempt 封顶 attempts_exhausted → turn/end → session failed)正好消费,事件链可审计;worker 不重试不重装配(下一次 advance 或人工 ch12 域)。claim 后到 settle 前的崩溃 = lease 过期 → requeue_stale 的 context_refresh→unknown 墙(DP1 #13 冻结分工;refresh 虽幂等,墙是既有纪律,ch12 显式 resolve 是唯一出口)。worker 连接无需 SET typesafe.*(settle 面零 GUC 消费——prefix_identity 已换源 generation 策略行,O1 P1-7;parse/resolve 链的 GUC 纪律属 DP1/DP2 面,与本 worker 无涉)。

### 3.6 墓碑:probe 与 envelope 的 goal_hash 换源

```sql
-- 【墓碑一】v13_probe:OR REPLACE 换体——DP1 §3.5 定义逐字保留,仅
-- goal_hash 值表达式换 v13_goal_hash(p_sid)(coalesce 内联公式退役)。
-- 七键零增删;字节相等性由 gate A2 断言。ACL 不动(OR REPLACE 保 OID/
-- 授权)。
CREATE OR REPLACE FUNCTION v13_probe(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'session_version', s.next_seq,
    'max_event_seq', coalesce((SELECT max(seq) FROM events
                                WHERE session_id = p_sid), -1),
    'goal_hash', v13_goal_hash(p_sid),
    'route_policy_name',     s.route_policy_name,
    'route_policy_version',  s.route_policy_version,
    'tools_revision', (SELECT revision FROM v13_tools_meta WHERE singleton),
    'candidate_generation_revision',
      (SELECT candidate_generation_revision FROM v13_tools_meta
        WHERE singleton))
  FROM sessions s WHERE s.session_id = p_sid;
$$;

-- 【墓碑二】v13_judgment_envelope:OR REPLACE 换体——DP2 §3.4 定义
-- (v13_envelope.sql 内 19 键版)逐字复制,仅 goal_hash 值表达式换
-- v13_goal_hash(p_sid)。**P0-2:函数体整段贴入(引用不复制退役)**
-- ——本块在计划内即完整可纸面解析;实施期从 v13/envelope/
-- v13_envelope.sql 文件原文复制(加载后真实存在,比计划文本更权威),
-- 同样仅换 goal_hash 行。manifest gate 以 19 键集 + goal_hash=
-- v13_goal_hash 复测(M2-9 包含性断言同型)。diff 示意:
--   DP2 原文: 'goal_hash', encode(digest(coalesce(
--                (SELECT payload::text FROM events
--                  WHERE session_id = p_sid AND type = 'user/message'
--                  ORDER BY seq DESC LIMIT 1), ''), 'sha256'), 'hex'),
--   DP3 换体: 'goal_hash', v13_goal_hash(p_sid),
-- 其余(runtime/ctx/needed/tmpl/groups/wm/pol 七 MATERIALIZED CTE 与外层
-- 19 键 build)零改动。
CREATE OR REPLACE FUNCTION v13_judgment_envelope(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  WITH runtime AS MATERIALIZED (
    -- provider/model fail-closed(turn 14 P1):冻结值=实际执行身份,未配置
    -- 即 V3002——缓存键永不记 NULL 身份(默认值变化后的错误跨 session 复
    -- 用被结构性封死;DP1 逐字 current_setting(...,true) 表达式由此收紧,
    -- 附 A #13)
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
             -- DISTINCT 于 (pkey,state) 整行去重:同声明的族共享一组(§6.5
             -- 批处理约束的分组粒度=projection 内容,非模板身份)。注(勘误
             -- turn 14):模板缺失的 needed 行在此**并非静默滤除**——缺失时
             -- projection 实参为 SQL NULL,v13_project_state 对 NULL 声明
             -- RAISE(V3002)——与 needed 的 fail-closed RAISE 同向双层,
             -- v13_group_state 再拒第三层;本 CTE 无静默路径。
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
      encode(digest((SELECT n FROM needed)::text, 'sha256'), 'hex'),
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
    'needed_count', jsonb_array_length((SELECT n FROM needed)));
$$;
```

> 移动=增+删审计:两处墓碑均为 OR REPLACE 同签名换体——旧内联公式**不在本文件任何位置重复出现**(其唯一存活形态=v13_goal_hash 函数体),无 turn 8 #57 式重复定义面;DP1/DP2 文件里的原定义不动(前缀 stage 用原定义,manifest stage 后定义覆盖,OR REPLACE 同 OID)。

### 3.7 回放读者 + ACL 全量块

```sql
-- === exact replay 读者(OQ5):纯读,永不重跑 assemble;返回视图附加
--     replay 标注(装配产物内 mode 永不为 exact_replay——三种回放
--     可区分的字段面)。**|| 覆盖语义写死(O2 P1-3)**:jsonb || 顶层键
--     右胜——视图的 replay 块覆盖原 manifest 的 {mode,prior_artifact_id},
--     设计意图(视图标注赢);返回视图不进 validate、不可 settle(settle
--     只走 refresh,OQ3)。被引用正文经 payload_ref 回取 blob(P0-4③)。 ===
CREATE FUNCTION v13_replay(p_artifact uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT a.inline || jsonb_build_object(
           'replay', jsonb_build_object('mode', 'exact_replay',
                                        'source_artifact', a.artifact_id))
  FROM artifacts a
  WHERE a.artifact_id = p_artifact AND a.kind = 'context';
$$;

-- === ACL 全量块(文件真末尾;DP1/DP2 矩阵增量,逐条理由见注释)。
--     18 件新函数全量 REVOKE PUBLIC(G4 逐件断言;触发器函数 EXECUTE
--     仅建触发器时校验,REVOKE 是卫生面不改运行行为)。 ===
REVOKE EXECUTE ON FUNCTION
  v13_goal_hash(uuid), v13_context_required(uuid), v13_prefix_identity(uuid),
  v13_latch_digest(uuid), v13_manifest_validate(jsonb),
  v13_judgment_defaults_check(jsonb),
  v13_assemble_manifest(uuid,int), v13_refresh_context(uuid,int,bigint),
  v13_artifact_land(uuid,text,jsonb), v13_blob_land(uuid,jsonb),
  v13_replay(uuid),
  v13_goals_append_only(), v13_goal_project(), v13_artifacts_append_only(),
  v13_artifacts_effect_guard(), v13_decisions_epoch_fill(),
  v13_epoch_frozen(), v13_ctx_ptr_guard()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_goal_hash(uuid), v13_context_required(uuid), v13_prefix_identity(uuid),
  v13_latch_digest(uuid), v13_assemble_manifest(uuid,int),
  v13_replay(uuid)
TO v13_route, v13_resolve, v13_recall;         -- 读面三角色
GRANT EXECUTE ON FUNCTION
  v13_refresh_context(uuid,int,bigint), v13_manifest_validate(jsonb)
TO v13_route;          -- settle 窄入口+只读校验器(P0-3:双 lander 不授任何
                       -- 运行角色——owner-only,唯一落行路径=refresh_context
                       -- DEFINER 体内,直调伪造面封死;G4 owner≠运行角色分离)
GRANT EXECUTE ON FUNCTION v13_canonical_state(uuid)
TO v13_route;          -- 增量授予(DP1/DP2 已授 resolve/recall 面;装配读面:
                       -- canonical_state 是 history/tools 段与 blob 冻结的
                       -- 单一材料来源,只读 STABLE,零权力升格)。
                       -- v13_guc_required 不增授 route:prefix_identity 已
                       -- 换源 generation 策略行(O1 P1-7),settle 面零 GUC
                       -- 消费;parse/resolve 链的既有授权(DP1/DP2)不受扰。
-- judgment_defaults_check:骨架零运行消费者,不授任何运行角色(DP6/DP7
--   落消费臂时随其面追加);gate 以超级用户直调(B7);settle 以 owner 身份体内调用,不需授权(P1-5 接线)。
GRANT SELECT ON v13_goals, artifacts TO v13_route, v13_resolve, v13_recall;
-- INSERT 零授予(P1-8 受控写入):v13_goals 经 v13_goal_project(DEFINER
--   触发器)投影;artifacts 经 v13_artifact_land/v13_blob_land(DEFINER)
--   落行;运行角色直接 INSERT 一律拒绝(G4 负向)。
-- sessions 新列无列级 GRANT 需求(表级 UPDATE 已覆盖 v13_route;指针守卫
-- 触发器随 invoker 执行,读 artifacts 已授;epoch 冻结触发器零额外权限)。
```

### 3.8 stage 四件

- `v13/manifest/setup_db.py`:DROP-CREATE 库 `agent_v13_manifest`(v12 仪式);`files_through('manifest')` 加载六文件;超级用户连接(ALTER/触发器/策略 INSERT 同 DP2 前置);末尾 import 复用 `v13/resolve/setup_db.py` 两个部署探针(坏 endpoint 契约核对 + 57014 可交付性,DP1 #36/#45 形制)。
- `v13/manifest/test_manifest.py`:§4 断言族;独立可跑脚本,退出码 0=通过(仓库纪律,非 pytest)。
- `v13/manifest/README.md`:六条运维纪律(§5 收尾)。
- `v13/load.py`:SQL_LOAD_ORDER 末尾追加 `manifest/v13_manifest.sql`;`STAGE_THROUGH["manifest"]=6`。

---

## 4. 里程碑与 gate

单里程碑单 stage:`v13/manifest/`。命令形态 `uv run python v13/manifest/test_manifest.py`,退出码 0=通过。**提交前 DP1 四 stage + DP2 gate 全部复跑**(其库不加载 DP3 文件,前缀切片——防回归的结构性保证;AGENTS.md 前置条件 1)。

**断言纪律(DP1/DP2 原样沿用)**:fixture 走真实链路——事件经 `v13_append_event`、decisions 经 mock parse(`SET typesafe.provider='mock'` 全程)、effect 经 enqueue/claim 真实调用、settle 经 `v13_refresh_context`;禁止手拼 manifest/hand-hash 注入。gate 只引用本 stage 已加载对象(本 stage=全树六文件,无移位问题)。连接统一 SET typesafe.provider/model(fail-closed 前置)。策略版本分配器同 DP2(`next_policy_version()`=coalesce(max(version),0)+1,测试内 SQL;追加经真实 INSERT+同事务翻 active,旧版本留档)。

### A 组 · goal 平面与 freshness 缝激活

| # | 断言 | 对应 |
|---|---|---|
| A1 | goal 投影:user/message 经 append_event 落地 → v13_goals 同事务多一行(content_hash=sha256(payload::text));非用户事件零行;UPDATE/DELETE 被拒(append-only 触发器);自证 CHECK 负向:绕过投影手 INSERT 伪造 content_hash → 拒;加载期回填幂等:fixture 后重放 §3.1 回填语句 → 零新行(共享库升级面) | OQ2/P1-8 |
| A2 | **字节相等(A 组主断言)**:三 fixture——(i) 有 user/message 的会话:`v13_goal_hash(sid)` = `encode(digest((最后 user/message 的 payload)::text,'sha256'),'hex')`(DP1 原公式对照计算);(ii) 空会话:= sha256(''::text) 的 hex;(iii) 多轮 user/message:= 最后一轮的 hash(版本递进) | OQ2/水位零漂移 |
| A3 | probe 换源回归:七键齐备;goal_hash=v13_goal_hash;其余六键行为与 DP1 一致(相对断言:disable 一 tool → tools_revision 动;freeze 新模板版本 → cgr 动) | 墓碑一 |
| A4 | envelope 换源回归:19 键逐键枚举与集合相等(机械断言,非计数):sid/ctx/needed/candidate_set_hash/goal_hash/provider/model/route_policy_name/route_policy_version/tools_revision/tools_catalog/candidate_generation_revision/session_version/max_event_seq/needed_count(DP1 15 键)+ templates/groups/timeout_ms/budget(DP2 增 4);goal_hash=v13_goal_hash;墓碑二的实施复源=v13/envelope/v13_envelope.sql 文件原文(加载后真实存在,比计划文本更权威),仅换 goal_hash 行 | 墓碑二/契约 12 |
| A5 | freshness 语义:新会话(无 artifact)→ `v13_context_fresh`=false;token 七键齐备(含 gen_ver——P0-2);② 真分支激活:parse 后 advance → context_refresh effect(request 仅 {goal_hash})+ send_work + 'waiting';claim + `v13_refresh_context` → 'accepted';再 parse+advance → ② 通过,进 ⑤③④ 路由(八分支表正常);settle 产物 replay.mode='fresh'(prior 缺位——identity 基判定的首版形态,OQ5) | OQ1/契约 1 |
| A6 | token 单调语义(逐键独立 fixture,相对断言):append llm/message(origin=当前锚)→ sem 动;mock parse 落答 → dec 动;新 user/message → sem/goal 双动;目录 DDL → tools_rev 动;追加 assemble_manifest v2+翻 active → asm_ver 动;追加 judgment_defaults v2+翻 active → jdef_ver 动;追加 generation v2+翻 active → gen_ver 动(**P0-2 独立 fixture**——与 B6 的 identity 面分立验证:同一翻版既动 gen_ver 又变 prefix_identity,两断言不同面)(七键全覆盖) | OQ1 |
| A7 | straggler 超集:注入跨 turn 迟到 tool/result(origin=旧锚,seq 高)→ token.sem 动 → 一次 refresh;装配产物 history 段 content_hash 与 straggler 前一字节相等(canonical_state 窗滤除,manifest 不受污染) | OQ1 取舍记档 |
| A8 | 单活跃钉住:预置 ready llm effect → advance ① 'waiting';② 不可达(context_refresh 无法 enqueue——ux_v13_effects_single_active 结构性) | OQ3/契约 5 |

### B 组 · G-ctx5 断言一:manifest 含 §5.2 全字段

| # | 断言 | 对应 |
|---|---|---|
| B1 | 装配产物 10 外层键恰等(OQ4 清单);manifest_version=1;turn_no/session_id 正确;policy 块 4 键(assemble_version/budget_tokens/est_bytes_per_token/judgment_defaults_version);required_revision 7 键(含 gen_ver);**零时间戳键**(键集断言蕴含) | §5.2/OQ4 |
| B2 | sections 三段各 9 键;kind∈{goal,history,tools};cache_scope goal/history=Session、tools=Global;priority goal/tools=First、history=Normal;content_hash 非空 64hex;payload_ref 形态:goal 段={kind:'goal',seq}、history/tools 段={kind:'blob',content_hash=段 content_hash}(P0-4①);transform.name∈{verbatim,catalog_digest} 且 history='verbatim'(O2 P1-1);est_tokens>0 且=((octet_length+div-1)/div) 对照重算 | §5.2/ch10:157-169 |
| B3 | 查询侧:query_artifact_id=活动 goal 地址;单 echo 候选四字段族在场(content_hash/bm25/spans/decision_id——值可空,键必须在);spans='[]' typed array | §5.2/§4.7 字段族 |
| B4 | judgments 消费集收敛(O1 P1-9):fixture 先 mock parse 落 ≥2 答(对照 SQL 直查 decisions 计数>0)→ 装配产物 judgments=**[]**(零消费⇒空集,收敛性正向断言);完整判断历史经 decisions⋈judgment_calls 可查(对照计数相等);**complete 谓词在场(P1-6)**:源码扫描 v13_manifest.sql 装配体含 `answer IS NOT NULL` 与 `status IN ('answered','cached')`(DP1 M2-10 源码扫描纪律同型——骨架消费集空,谓词功能面 DP6 落 decision_id 后自动激活);missing/timeout/review 默认动作不进 judgments(raw_verdict=null 会被 validate 拒——refresh 不因默认分支炸的结构性保证),其段级 trace 载体归 DP6/DP7(契约行已立法);行形状 7 键 {decision_id,epoch,request_hash,template_name,template_version,raw_verdict,final_action} 以手工构造合法 manifest 直调 v13_manifest_validate 正向通过(B5 反向配套);**零 usage 键**(键集断言) | §6.1/DP2 契约 10 |
| B5 | 校验 fail-closed(O1 P1-5 七层封闭,直调 validate 的纯函数测试):**正向(P0-1 回归面)**:合法三段(goal/tools={applied:true,name:…}/history='verbatim')+四种 skip({applied:false,reason:'budget'|'priority_never'|'disabled'|'invalid_override'})直调 validate 必过——旧版合法 applied 行被布尔反转拒收;顶层多一键/缺一键→V3003;section 层:缺键/多键/词表外 cache_scope·priority/**applied 分支缺 name/skipped 分支缺 reason(分支键集恰等,P0-1)**/applied 却带 reason/非 applied 却带 name/transform 名·reason 词表外/**applied 为字符串 'true'(jsonb_typeof 层焙劣)**/空 sections/payload_ref 非法 kind·content_hash 非 64hex→V3003;**null 穿透四形态**:cache_scope=NULL、priority=NULL、churn=NULL、manifest_version 缺失——全 V3003(三值逻辑封死的回归面);policy 层:缺 judgment_defaults_version/除数 0/预算负→V3003;required_revision 层:六键(无 gen_ver 旧形态,P0-2)/goal 非 64hex→V3003;replay 层:mode='exact_replay'(装配产物面)→V3003;judgments 行:缺 raw_verdict/final_action 词表外/epoch 词表外/模板对不成对→V3003;candidate 行:缺 spans 键/content_hash 非 64hex→V3003;64hex:prefix_identity 大写或 63 位→V3003;**全部 V3003 以 SQLSTATE 断言(P1-10:USING ERRCODE 已挂,非仅消息文本)** | OQ6/G-ctx9 canary 半边 |
| B6 | prefix_identity(O1 P1-7 换源):64hex;**generation 策略行 v2(model 变)→ identity 变;SET typesafe.model='other' → identity 不变**(判断身份不入生成身份——换源正负两向);同状态两调相等;latch 与 system_blocks stub 在位(pg_get_functiondef 双查 '-none-');generation 行缺失(DELETE 后直调)→ 响亮失败 | §5.6/§5.1 缝 |
| B7 | judgment_defaults 校验器(OQ3 末段/O1 P1-6,引设计审查 F1):种子行 v1 过 v13_judgment_defaults_check(正向);三点负向:缺状态键(仅 {missing,timeout})/动作词表外('skip')/顶层多键→V3003;追加合法 points={'score_v1':{missing:'exclude',timeout:'exclude',review:'degrade'}} v2 翻 active → 过校验且 token.jdef_ver 动(A6 联动);**接线断言(P1-5)**:追加非法 points(动作词表外)v2 翻 active → 在 claim 的 refresh effect 上调 v13_refresh_context → 装配前 RAISE V3003(settle 强制校验,不靠 B7 直调纪律);还原 v3(=v1 值) | F1/OQ3 |

### C 组 · G-ctx5 断言二:applied/skipped 双分支 + 预算

| # | 断言 | 对应 |
|---|---|---|
| C1 | 常态:三段全 applied,transform.name∈{verbatim,catalog_digest} 且 history='verbatim'(与哈希材料一致——O2 P1-1);churn 首版全 0(与实现字面一致,O1 gate 对齐项) | §5.2 |
| C2 | 预算截断(P0-1 重写,可构造 fixture——预算由 fixture 内 est 公式计算,勿写死常数):全序=[goal,tools,history](goal/tools 同 First,section_id 决胜;history Normal)。v2a budget=goal.est → applied 恰={goal},tools/history reason='budget',applied 和=goal.est≤budget;v2b budget=goal.est+tools.est−1 → applied 恰={goal}(差 1 即 skip 边界);v2c budget=goal.est+tools.est → applied={goal,tools},history 'budget';v2d budget=0(fixture 保证 est≥1)→ **三段全 skip(首段可被 skip+自身超限必 skip——旧 pre_cum 两缺陷的回归面)**;各 fixture 断言 applied 集为候选连续前缀+applied est 运行和≤budget;还原 v3(=v1 值) | ch10:231「est_tokens ≤ 策略行预算」 |
| C3 | Never:v2' priority_overrides={"history":"Never"} → history 段 skipped(reason='priority_never'),priority 字段='Never';**Never 不占预算**:同 budget 下叠加 Never 覆写的 applied 集与不叠加时相同(Never 段 est 不进 run_incl——P0-1 断言) | §5.2 词表 |
| C4 | disabled:v2'' kinds_disabled=["tools"] → tools 段 skipped(reason='disabled') | OQ3 默认分支实例 |
| C5 | churn:两次 refresh 间 append llm/message → history 段 content_hash 变且 churn=1,goal 段不变且 churn=0;再一版不变 → churn 归 0 | §5.2/§5.4 输入 |
| C6 | 非法 override(P1-8):追加 v_inv priority_overrides={"history":"ASAP"} 翻 active → (i) refresh settle 策略守卫在装配前 RAISE V3003;(ii) 直调 v13_assemble_manifest(sid,NULL) → history 段 transform={applied:false,reason:'invalid_override'}、priority 字段='Normal'(def_prio 回退,词表内)、**不进装箱**(同预算对照下 goal/tools 的 applied 集与 C1 相同——非法段不占预算);(iii) 还原 v3(=v1 值) | P1-8/OQ4 |

### D 组 · G-ctx5 断言三+四:三种回放可区分 + ORDER BY 确定性

| # | 断言 | 对应 |
|---|---|---|
| D1 | **exact replay**:v13_replay(artifact) 返回 = artifact.inline ∥ replay 标注;**|| 覆盖语义断言(O2 P1-3)**:返回视图的 replay 块恰为二键 {mode:'exact_replay',source_artifact}(原 {mode,prior_artifact_id} 被覆盖——设计意图);judgments=旧 verdict 原文原样(骨架空集,键集断言);**随后落地新 decision → replay 输出逐字节不变**(freeze 纪律直接推论,F1 复测其因果面) | ch14:92/§5.2 |
| D2 | **recompute(同版本形态)**:prior settle 于 v1 后语料前进(append llm/message)→ `v13_assemble_manifest(sid, 1)`(prior 同一版本,不追加行)→ mode='recompute'、policy.assemble_version=1、sections 反映当下语料;**sessions 指针与 artifacts 行数零变化**(只读);**recompute(版本 bump 形态)**:追加 v2(改 budget,identity 材料未动)→ 直调 assemble(sid,1) 与 settle v2 → mode 均='recompute'(版本 bump≠fresh,O1 gate 对齐) | ch14:93 |
| D3 | **fresh fork(identity 基,O1 gate 对齐)**:追加 generation v2(model 变)→ parse+advance → ② 真分支触发 context_refresh(**gen_ver 追动经 token 的功能面直接验证——P0-2:不许手搓 settle,fresh 必须由 freshness miss 真实驱动**)→ claim+settle → mode='fresh'、prior_artifact_id=旧 artifact、prefix_identity≠前版(身份材料动是唯一 fresh 面——§5.6);对照:仅改 assemble 预算(identity 未动,asm_ver 动)→ 同经 ② 触发 settle → mode='recompute'(D2 已断其直调面)——ch14「recompute 前缀身份可继承」的正负两向 | ch14:94/§5.6 |
| D4 | 确定性:同输入连续两次直调 v13_assemble_manifest(sid,NULL) → 逐字节相等;并列构造(tools 与 goal 同 First)→ 序恒 (prank,section_id);预算并列截断(两段同 est 同余量)→ 取 section_id 小者,两轮一致 | G-ctx5 第四断言 |

### E 组 · 三 epoch 机制

| # | 断言 | 对应 |
|---|---|---|
| E1 | decisions.epoch 默认 'pre-bind'(mock parse 全行);**真冻结(O1 P1-10)**:UPDATE epoch 全拒——词表内值('pre-finalize')与词表外值各一负向(trg_decisions_epoch_freeze 先于词表 CHECK,UPDATE 一律 RAISE) | OQ7 |
| E2 | 模板回填:freeze (t9,v1,epoch='pre-finalize') → 该族判断落行 → decisions.epoch='pre-finalize';DP1 时代形态(template_name NULL 手工行)→ 'pre-bind' | OQ7 |
| E3 | epoch 固化:answer 后补(B9 冲突填充形态:预置 open 行后 mock 填)→ epoch 不变 | §6.1「留在原 epoch 下」 |
| E4 | post-execute 防伪造+结构性排除(P1-7;**与 B4 对齐——旧文「judgments 如实记录」与 B4 骨架空集断言相悖,已改**):(i) 手工 INSERT decisions(template_name NULL,显式 epoch='post-execute')→ 落行 epoch='pre-bind'(触发器强制,调用方显式值被忽略);(ii) 带 template_name 指向 'pre-bind' 模板的 INSERT → epoch 落 'pre-bind'(epoch 是模板属性非调用方属性)——post-execute 行必引用声明该 epoch 的模板,骨架无该模板 ⇒ 不可构造,词表在场即可;(iii) 骨架消费集恒空(candidates.decision_id 恒 NULL)⇒ 任何已答行不进 judgments;**sections 三段 content_hash 与该行存在与否无关**(对照组:删该行重装配 → sections 逐字节不变——「只能影响后续 turn」在骨架的成立形态;「如实记录进 judgments」留 DP6 消费面) | §6.1 epoch 3 |

### F 组 · G-ctx9 复测(manifest 语境)

| # | §10 原文 | 断言做法 |
|---|---|---|
| F1 | manifest freeze 后迟到 decision 不得回写 | settle 得 artifact M₁;随后 mock parse 落新答(或 B9 后补)→ M₁.inline 逐字节不变(artifacts UPDATE/DELETE 触发器拒收负向)+ judgments 不含新行(骨架恒 [],键集断言);**M₁ 被引用正文可回取**(payload_ref→blob 原字节,G10 因果面);下一次 refresh → M₂ judgments 仍 [](消费集空;DP6 落消费段后此处改「判入」断言);**同信封复用**:新答行被完全相同信封的 v13_gap 命中 | §6.1 freeze |
| F2 | 水位不一致弃批重解析 | probe 换源后复测 DP1 M3-8 同型:parse → 注入新 user/message → advance 'stale' 零 effect;重 parse 正常;goal 键来源=goal 平面(A2 已证字节面) | §6.1 快照复核 |
| F3 | 分片哈希 canary(启用时)未声明字段不出现在出站 payload | DP2 C3 同型 canary 于本 stage 库重跑(judgment 出站半边);DP3 新增半边:B5 键集恰等(未知顶层键 V3003)+ sidecar 注入 canonical_state(pg_get_functiondef 快照/OR REPLACE 探针版,DP2 C3 技法)→ manifest::text 全文无 canary 值(sections 摘要化 + judgments 派生面零泄漏);还原定义后再装配不受扰 | §6.5/DP2 C3 引用 |
| F4 | freeze 面的语句快照原子性 | 并发注入复测(DP2 A9/M2-17 技法):连接 A 事务内调 v13_assemble_manifest,连接 B 其间 commit 新 decision → A 返回不含该行 **且 token.dec 不含之**(语句快照蕴含);A 提交后重调 → 含之;**(iv) settle 窗口竞态(O1 P1-11)**:连接 A 显式事务逐句复演 settle(三层行锁→assemble→complete('succeeded')→blob 落行→指针写;超用户直调逐句复演,窄入口不改变锁面),期间连接 B 以 v13_append_event 提交 llm/message——**B 阻塞于 sessions 行锁直至 A 提交**(窗口封闭正向断言);A 提交后 `v13_context_fresh`=false(B 事件已推 token)→ 下一次 ② refresh 收敛;A 事务内 blob 哈希 belt 恒等(零 V3003) | OQ3 |
| F5 | settle 幂等与失败路径 | (i) 重复 settle:再次 v13_refresh_context(同 attempt/fence)→ 返 'replay',artifacts 行数不增、sessions 指针不变;(ii) 旧令牌:伪造 (attempt+1,fence) → 'stale' 零写;(iii) 装配失败(V3003 前置,F5 修正):追加非法策略版本 v4(est_bytes_per_token=0——v13_policies 无形状 CHECK,非法行可装载)→ settle 的策略形状守卫在装配前 RAISE V3003(除零 22012 在 settle 面不可达——O2 P1-5)→ worker 契约捕获后 complete('failed') → DP1 ② 分支 attempts_exhausted → session failed(turn/end 恰 1);还原 v5(=v1 值);README 第二条同步策略形状纪律(新版本行必带合法数值键+overrides 值在词表内+judgment_defaults 过校验器);还原策略后新 user/message 复位 ready(M3-16 复位面) | §3.5/契约 4 |
| F6 | **全局锁序与并发死锁(P1-4,双 gate+策略翻版)**:全库冻结序=sessions→tools_meta→三策略活动行(name 序)→effects(complete 内,DP1 行 412–416)。(i) settle∥settle:两连接以相同 (attempt,fence) 并行调 v13_refresh_context(真实 claim 的 refresh effect)→ 零 40P01;恰一 'accepted'、另一 'replay';'context' 行恰 +1、sessions 指针恰一次推进、blob 零新行(内容同——内容寻址去重);(ii) settle∥complete:连接 A refresh_context 与连接 B 直调 v13_complete(同 attempt/fence,'failed')并行 → 零 40P01;先取 sessions 锁者先行,后到方 'replay'/'stale';终态唯一且与落行一致(B 赢 ⇒ 零 artifacts 行;A 赢 ⇒ B 'replay')——无「succeeded 却零 artifact/指针」撕裂态;(iii) settle∥策略翻版:连接 A settle 期间连接 B 追加 assemble v2+翻 active → B 阻塞于策略行锁至 A 提交,A 的 manifest 策略版本=旧版一致(守卫与装配同版);B 提交后 ② 触发新一版 | P1-4/OQ3 |

### G 组 · 机制、加载与 ACL

| # | 断言 | 对应 |
|---|---|---|
| G1 | artifacts 纪律:append-only(UPDATE/DELETE 拒);produced_by 指向 claimed effect 的 INSERT 被拒(守卫负向——直写与 DEFINER 落行器 belt 同执法);context artifact 的 produced_by=succeeded refresh effect;size=octet_length(inline::text)、content_hash=sha256(inline::text) 对照重算;**对照列钉死(O2 P1-6/P1-12 修正)**:两次零变化 settle 的 'context' 行,`inline - 'replay'` 逐字节相等(manifest 规范内容零漂移;replay.prior_artifact_id 携随机 artifact_id 两次必异——三列逐字相等不可达,旧断言已改,与 §3.7「replay 块覆盖不进 validate」语义对齐);各行自身 content_hash/size 对照重算成立(行内自洽);artifact_id/created_at 允许不同;**指针负向(O2 P1-2)**:context_active_artifact 指 blob 行(kind 不符)→ 守卫拒;指随机 uuid → FK 拒;置 NULL → 允许(复位面) | ch7 G1/G7 节选 |
| G2 | inline 超限:追加 v_tiny(inline_max_bytes=64)→ refresh(大 history fixture)→ RAISE V3003(SQLSTATE 断言)且位于 validate 同点、complete 之前(P1-11)→ 整体回滚:**零 complete、effect 仍 claimed**(status 直查+零 effect_done/零 result 写)、零 artifacts/blob 新行;worker 契约随后 complete('failed') 路径可达;还原 | ch7 阈值 |
| G3 | epoch 回填 fail-closed(O1 P1-10):decisions INSERT 带 template_name 指向不存在版本 → RAISE V3002(不静默回退 'pre-bind'——DP2 needed 族先行拒为第一层,本触发器拦手拼 INSERT 为第二层);template_name NULL(DP1 时代形态)→ 'pre-bind' | §3.1 |
| G4 | ACL 全函数矩阵(O1 P1-11):**REVOKE PUBLIC 逐件断言**——§3.7 清单 18 件新函数(11 运行+7 触发器函数)has_function_privilege(PUBLIC,…)=false;SET ROLE v13_route → EXECUTE refresh_context/manifest_validate/canonical_state/assemble/replay ✓、**双 lander(artifact_land/blob_land)✗ 与 v13_goal_project ✗(P0-3:owner-only,直调伪造面封死)**、**INSERT v13_goals/artifacts 直写 ✗(P1-8 受控写入)**、经 refresh settle 全链落行 ✓;**owner≠运行角色分离(P1-13)**:has_function_privilege(部署 owner,双 lander+goal_project,'EXECUTE')=true 且 v13_route/v13_resolve/v13_recall 三角色均 false(goal_project 三角色 EXECUTE 逐件负向);SET ROLE v13_resolve → EXECUTE refresh_context/artifact_land ✗、SELECT v13_goals/artifacts ✓、EXECUTE assemble/replay ✓(读面);v13_judgment_defaults_check 对三运行角色均 ✗(骨架零消费者;settle 以 owner 体内调用,不受授权面影响);OR REPLACE 三件 ACL 保留抽查(has_function_privilege 与 DP1/DP2 授权一致) | §3.7/DP1 M3-12 同型 |
| G5 | 双登录:v13_route_login 直连 → refresh settle 全链 ✓;SET ROLE v13_resolve → ERROR(非成员);has_function_privilege('v13_resolve','v13_refresh_context(uuid,integer,bigint)','EXECUTE')=false | DP1 双登录架构 |
| G6 | 加载序:files_through('manifest') 恰六文件序;DP1 四 stage 与 DP2 setup(各自库)不含 v13_manifest.sql(路径断言);本文件 BEGIN/COMMIT 自洽(加载后 artifacts/v13_goals 与函数族在档抽查) | 契约 9 |
| G7 | 纸面加载模拟对账(附 B 数字):test 内静态断言 v13_manifest.sql 源文:CREATE FUNCTION 总数=21(18 新建+3 OR REPLACE)、CREATE TRIGGER 总数=7、同签名重复=0(正则扫描)、策略 INSERT(三行组)末分号在、加载期回填 INSERT 在档 | turn 8/9 教训 |
| G8 | llm 消费 provenance:claim llm effect(路由 P5 fixture)→ worker 契约 result 带 context_artifact_id=活动 artifact → complete → llm/message 事件 payload 含该键(DP1 p_result∥origin 通道);effect.result 同 | OQ3 挂接 |
| G9 | 回合收据与全链:构造「user/message → parse → advance(refresh)→ settle → advance → … → finish」全链走通(terminal);finish 后追加一次 refresh(llm/message 落地 → sem 动 → ② 触发 → settle)→ 末 manifest 的 history 含本回合 llm/message;refresh 不耗 cycle(turn/route 计数对照) | §5 风险 6 正面化 |
| G10 | **blob 冻结与内容保全(P0-4③)**:settle₁ 后记录 M₁ 各段 blob 的 inline 原字节;随后 append llm/message(变 history)+disable 一 tool(变目录)+追加 assemble v2(变阈值)→ settle₂;断言:① M₁ 的 replay 输出与变异前逐字节相等(含 judgments 空集);② M₁ history 段 payload_ref→blob 行 inline 仍为**旧**字节且 content_hash=旧段哈希;M₂ 对应 blob 为新字节(content_hash=新段哈希)——内容寻址分版并存;③ settle₂ 新增 blob 行数=内容变化段数(history 1;tools 变另计)——未变段零新行(去重);④ 再一次零变化 settle → blob 行数零增(引设计审查 F11 的体积 gate 形态;保留窗口=blob_retention 策略键) | P0-4/附 A #11 |

---

## 5. 风险与回退

| # | 风险 | 缓解/接受面 |
|---|---|---|
| 1 | 墓碑二的 envelope 逐字复制走样(19 键最敏感对象) | 实施纪律=从 v13/envelope/v13_envelope.sql 原文机械复制仅换一行;**计划内函数体已整段贴入(P0-2),纸面解析可行**;A4 键集+goal_hash 同源断言;manifest stage 复跑 DP2 断言子集(A4/B 组键集) |
| 2 | token 七键漏未来输入(freshness miss) | 键集=骨架 manifest 全部输入的显式清单(OQ4 结构对照);**进 prefix_identity 材料的输入必须在 token 有键(gen_ver 即 P0-2 先例;DP8 latch 走同一键缝,§1.4)**;DP4 语料键/DP7 新 kind 按契约行并入;评审面:新 section kind 必须答「其输入在 token 哪个键里」 |
| 3 | required token 的 dec 计数随 session 长度线性 | 索引前缀扫,骨架量级毫秒;DP7 经济件可换 (count,max(answered_at)) 双键或维护列(届时代价明示);README 记优化缝 |
| 4 | refresh settle 与 append_event 的 sessions 行锁竞争 | 两者都走 sessions 行锁,串行毫秒级(与 DP1 advance 同量级);单行单序无死锁面(锁序见风险 11);F4(iv) 已测 settle 窗口封闭;F6 实证 settle∥settle/settle∥complete 零 40P01 |
| 5 | llm worker 忘带 context_artifact_id(契约而非结构) | G8 断言 + README worker 契约清单;DP8 render 落地时升格为 request 内钉(缝已留) |
| 6 | 每回合末尾多一次 refresh(llm/message 落地必动 sem) | 接受并正面化:末 manifest=该回合的 context 收据(fork/replay 的锚);装配是本地毫秒级 SQL,不耗 turn cycle(G9);DP7 若证明浪费可加「finish 在途短路」策略键(数据动作,不动 advance) |
| 7 | inline 超限 RAISE 位于 validate 同点、complete 之前(P1-11——失败路径不经「succeeded 再回滚」) | 整体事务回滚=effect 保持 claimed,worker 契约 complete('failed') 或 lease 过期 unknown 墙接管(G2 断言零 complete);README 运维:inline_max_bytes 与 budget_tokens 联动校验(部署期探针可加);接受面=配置事故响亮失败 |
| 8 | goal 投影触发器的权限面 | v13_route 是 append 唯一授权面,投影经 DEFINER 触发器落行(P1-8);测试以真实角色直跑(G4/G5) |
| 9 | blob 全量快照的存储增长(每变更 section 一份全量拷贝;引设计审查 F11) | 内容寻址去重(未变段零新行,G10③④);保留窗口=blob_retention 策略键已落(首版 referenced-forever);「被引用即保留」是不变量 4;DP7 tier/摘要落地后段体积自然收缩;附 A #11 呈报裁剪边界 |
| 10 | SECURITY DEFINER 面(goal_project/artifact_land/blob_land/refresh_context 四件——末者为 settle 窄入口,P0-3) | search_path 钉死+体内受信 schema 限定名(public.)双层+REVOKE PUBLIC(不变量 8);EXECUTE 面:refresh_context 仅 v13_route,其余三件零运行角色(lander 经 refresh 体内、goal_project 经触发器——G4 owner 分离断言);函数体固定表/固定列零动态 SQL;owner=部署角色(生产最小 owner 可后续收紧,记缝) |
| 11 | settle 三层行锁的锁序(sessions→tools_meta→三策略活动行;effect 锁在 complete) | 与 DP1 冻结全树序(complete 内 sessions→effect,行 412–416)一致;settle 若按 O1 提案先取 effect 锁恰与 complete 成 AB-BA(论证 OQ3,提案序弃);DP1 全树无 effect→sessions 路径(claim/renew/requeue 只触 effects);三策略行 name 序加锁,并发 settle 同序;锁内零外部 IO(不变量 1);F4(iv) 断言窗口封闭+F6 双并发 gate 实证 |
| 12 | generation 策略行骨架值 mock(O1 P1-7 换源的最小落地) | fail-closed:行缺失/键 NULL → prefix_identity RAISE(B6 负向)、版本行缺失 → token 亦 RAISE(P0-2);**版本翻动经 token.gen_ver 追动 freshness(A6/D3 功能面)**;DP8 接管填真值+latch 并同一键缝(§1.4);mock 值不进任何 effect 身份(仅 manifest.prefix_identity 消费) |

**回退**:删 `v13/manifest/` 树 + `v13/load.py` 一行 + DROP 库 `agent_v13_manifest` 即完全回退;DP1/DP2 stage 库与文件零改动(前缀切片)。共享库(若有)加载过本文件:重跑 DP1 四文件+DP2 文件即恢复 probe/envelope 原定义(OR REPLACE 同 OID 后定义覆盖);新增表/列/触发器可暂留(零消费者)或逐对象 DROP(清单=§3 全对象表)。

**收尾工件(每里程碑,AGENTS.md)**:SQL 追加进 `v13/load.py` 的 SQL_LOAD_ORDER(纯末尾第 6 行)+`STAGE_THROUGH["manifest"]=6`;stage README 六条运维纪律:①refresh worker 契约(claim→settle→异常转 failed);②策略版本化纪律(assemble_manifest/generation/judgment_defaults 三族追加=新版本行+同事务翻 active;改 est 公式必新版本;新版本行必带合法数值键+overrides 值在词表内+judgment_defaults 过校验器——形状错在 settle 守卫 V3003);③exact replay 与 shadow reroute 分界一字诀(旧 verdict vs 新阈值重释);④goal_hash 单一来源纪律(禁内联重算);⑤generation/judgment_defaults 策略纪律(生成身份与默认分支是版本化数据,改动=新版本行;settle 面零 GUC 依赖);⑥回退清单。一里程碑一提交(`v13: <祈使句摘要>`,按路径 add,禁 `git add -A`)。

---

## 6. 教程映射(§13;正文零改动)

| 章 | 教程承诺(实测行号) | 本 DP 兑现 |
|---|---|---|
| ch7(artifacts 平面) | manifest 指针(ch7:102-108「清单与 decisions 只记 content_hash」);完整 schema 在 ch10 展开(ch7:153-154);produced_by→succeeded 消费/生产纪律(ch7:46-47) | artifacts 表首次落地(ch7:26-36 逐字形状+自证 CHECK);kind='context' 内嵌 manifest;两条纪律触发器执法;content_hash-only 身份进 candidates/judgments;section 正文 blob(kind='context_section',内容寻址去重+被引用即保留——引设计审查 F11 的 blob 平面形态) |
| ch10(rag-as-tools) | 装配清单 schema(ch10:157-169=§5.2 逐字同构);G-ctx5 断言(ch10:225-230 五条);「required_revision vs active_revision 不匹配→context_refresh effect→waiting(第 10 章展开)」——**教程承诺的 context_refresh worker 装配语义在 ch10 从未展开**(ch10:46-47 只到「llm effect 消费 render(manifest)」) | **DP3 立法点**:refresh worker 的装配/settle 语义(§3.5)= 教程欠账的最小实现;G-ctx5 五条全落 B/C/D 组(第五条 est≤预算=C2) |
| ch5(turn-and-advance) | ② context gate(ch5:80-81)与「形态从七张表的管线降为一个 revision 比较」(ch5:126-127) | 缝激活(A5);「一个比较」=token 全等(OQ1 载体裁决,附 A 分歧 1) |
| ch13(long-running-goals) | goal→sessions 控制行(新增 0)(ch13:20) | 活动 goal 派生自 sessions+goal 平面投影,零冗余控制列(附 A 分歧 2) |
| ch14(fork-and-replay) | 三种回放表(ch14:90-104)+「exact replay 用清单里的旧 verdict,不拿新阈值重释 raw answer」(ch14:101-103) | v13_replay/装配 mode 判定(identity 基)/OQ5 全节;D 组;blob 回取使旧 replay 逐字节可重演(P0-4) |

教程正文零改动(边界);实现与教程冲突时以冻结设计稿为准(设计稿头部裁决)。

---

## 7. 明确不做(§12 台账为源;P2/台账项一律不承诺为首版交付)

| 项 | 依据/触发条件 |
|---|---|
| emergent 表 + 在线 triage | §12:首个真实 mid-turn producer 出现;设计 §5.1/轮 2 裁决 P2 延后 |
| T1 vectorchord 检索/bigram 列/boost 反馈环 | §12 台账三项:固定评估集证明漏召/kohaku 漏召超标/held-off 指标——全在 DP4/DP5 侧 |
| 全集 Choice 重排/语义决策缓存 | §12:相对序成为问题/判断缓存费用成账单大头(DP6 域) |
| 工具目录检索/timescaledb/age | §12 触发未至 |
| 预取排序(触点 6)/效用遥测上线驱动策略(触点 4 的线上半边) | §12+§6.2;post-execute **生产者**归 DP7(本 DP 只立 epoch 载体) |
| pg_jsonschema 引入 | OQ6 裁决:V3003 手写族;触发=形状超手写表达力且第二消费者出现(与 DP2 answer 半边同批评估) |
| render(manifest→wire bytes)本体 | DP8(§5.3 首版单一 canonical render);本 DP 的 manifest 结构即其输入 |
| latch 表本体/validate-spawn/cache probe | DP8(§1.4 缝:v13_latch_digest 替换点) |
| ForkPrefix 的 fork 执行面 | DP8;本 DP 落 prefix_identity 材料与 exact replay 读者 |
| 压缩/摘要链(§6.4)/tier/E(r)/R_o | DP7;summary kind 与回退链的 transform 载体已备(OQ4) |
| est_tokens 真 tokenizer | 除数公式版本化(OQ4);DP7 换公式=新策略版本行 |
| chunks 投影/召回/bm25/跨度生产 | DP4/DP5/DP6(§1.4 契约行);本 DP 只立字段形态与 token 消费缝 |
| pg_cron tick | §12:扫描恢复空转成本实测超标;refresh settle 是 effect 驱动,tick 无生产者 |
| CJK 摘要校准/分片哈希启用 | DP2 已裁条件启用;manifest 侧零新启用面 |
| blob GC/保留窗口执行器 | blob_retention 策略键已落(唯一值 referenced-forever);「被引用即保留」是不变量 4;窗口化 GC 的触发=扫描恢复成本实测超标(§12 同族),DP4+ 语料面一并评估 |
| system blocks 正文 blob | generation.system_blocks_digest 骨架 '-none-';正文随 DP8 render 落地(§1.4 DP8 行沿 v13_blob_land 形态扩展) |

---

## 附 A:与设计稿/上游裁决的分歧点清单(供父 loop 复核)

| # | 分歧/裁量 | 论证 |
|---|---|---|
| 1 | required_revision 载体=复合 jsonb token 而非标量整数(教程 ch5「一个 revision 比较」的形态裁量) | 教程/设计未定载体类型;七键异质输入(事件 seq/计数/hash/版本号×3)无可比单一 int,压成标量必引入 bump 计数器纪律面(livelock/miss 双向风险,OQ1 论证);命名保留 required/active |
| 2 | goal 平面=独立 v13_goals 投影表而非 artifacts kind='goal' | produced_by 效应溯源 vs 用户事件溯源两种纪律(ch7:46);伪造 effect 或弱化不变量都比小表贵;ch13「sessions 控制行(新增 0)」以派生+token 键满足 |
| 3 | freeze 点=refresh settle 而非 ④ llm effect 创建;llm request 不内嵌 artifact_id | advance 零改动纪律 + 单活跃索引结构性钉住(OQ3 论证);provenance 走 result/llm-message 通道(DP1 p_result∥origin 既有机制零改动);DP8 缝已留 |
| 4 | recompute 的 asm_ver token 键记活动版本而非钉定版本 | token 是「所需状态」的水位非 manifest 自述;recompute 永不 settle(OQ5),错配结构性不可达 |
| 5 | est_tokens=字节/除数 整数公式 | 确定性与版本化优先;真 tokenizer 是 DP7 的数据动作 |
| 6 | inline 阈值落 assemble_manifest 策略行而非 meta 表 | meta 表未建(DP1 M1 无);「阈值是数据」的 ch7 语义等价保真;呈报父 loop |
| 7 | 每回合末尾固定多一次 refresh | sem 单调蕴含;接受并重构为「回合 context 收据」(§5 风险 6);不动 advance 是前提 |
| 8 | epoch 由模板列经触发器落 decisions(而非 resolve 侧显式赋值) | DP2 文件零改动;模板属性口径消除同题异 epoch;G3 悬挂引用 fail-closed(V3002,不回退) |
| 9 | prefix_identity 材料换源=generation 策略行(typesafe GUC 出列) | GUC 配置的是判断(Jev)provider/model,非生成模型(O1 P1-7);生成身份必须是版本化数据才能进 §5.6 身份哈希;mock 种子值是骨架最诚实值,DP8 接管 |
| 10 | goal_hash 保留在 prefix_identity 材料(每 user turn 新身份的缓存成本) | 身份完备性优先:goal 段渲染进前缀,漏列=身份不完备(prefix cache 错命中比 miss 贵);成本=每 user turn 一次 identity 追动,实价取决于 DP8 render 序(goal 若排前缀尾部则仅尾部重算)——缝记 DP8,剔除被拒 |
| 11 | blob=section 全量快照(非增量/分块) | 引设计审查 F11:内容寻址去重免费获得;全量拷贝成本=每变更段一份(历史段逐 turn 一份),O(n²) 累积上界由保留窗口策略键约束;分块/增量 blob 留 DP4+ 语料面一并评估——骨架三段全量足够且可审计 |
| 12 | judgments 骨架空集(消费集驱动) | O1 P1-9 收敛裁决的必然推论:骨架 sections/candidates 零 verdict 消费;行形状/词表/校验/G-ctx9 语义全部先行落地,DP6 落 decision_id 后自动非空;完整判断历史从未离开 decisions/judgment_calls |
| 13 | history 首版 transform 名='verbatim'(非 window_20) | O2 P1-1:首版哈希材料与装配字节一致(无窗口),真窗口=DP7 新 transform 名+新策略版本行;名不虚标 |
| 14 | mode 判定=identity 基(策略版本 bump ⇒ recompute) | ch14:93 语义:recompute=同前缀身份重装配;fresh=身份变(§5.6);预算/除数变化不动 identity 材料,判 fresh 会使「版本 bump」与「fork」混称——违 §5.2 三态区分 |
| 15 | fresh·recompute 语义 vs 设计 §5.2 措辞(O1 设计冻结契约冲突 1,本轮呈报) | 设计 §5.2 只立法「三种回放显式区分」,未给 mode 判定式;plan 裁决 identity 基(identity 不变仅策略版本变=recompute;identity 变=fresh,§5.6 ForkPrefix 语义)不违 normative 且更细:设计措辞「recompute=旧策略×当下语料」(ch14:93)蕴含「同身份」——身份变时旧策略×新身份已是新前缀=fresh fork(§5.6);映射:ch14:93 recompute↔plan recompute、ch14:94 fork↔plan fresh、exact replay↔v13_replay 视图;维持 plan 裁决(与 #14 同源,呈报父 loop 复核) |
| 16 | pg_jsonschema(设计 §8 P1 进 vs plan OQ6 排除)(O1 设计冻结契约冲突 2,本轮呈报) | 呈报:V3003 手写七层封闭已覆盖 manifest 半边(键集恰等×7/词表/64hex/数值域/null 穿透封死),jsonschema 半边(嵌套 schema/条件依赖/跨字段约束)推迟到 DP6/DP7 消费面(第二消费者出现时)再评估——OQ6 台账触发条件不变;不改设计,呈报父 loop |
| 17 | G-ctx6 设计稿内部矛盾(§5.4 vs §14)(O1 设计冻结契约冲突 3) | DP3 无 G-ctx6 gate、无 tier 面(预算装箱≠tier),plan 不受其影响;维持用户既定默认(不改冻结稿;loop memory turn 1 后裁决记录);DP7 落 G-ctx6 时按 §5.4/§14 已裁语义并标注措辞被轮 2 取代 |

**设计矛盾检查:未发现 blocked 级矛盾。**设计稿 §5.2/§6.1/§9/§10-G-ctx5/G-ctx9 的 normative 内容全部有落点(§2 映射表);与 DP1/DP2 契约零冲突(§1.2 消费清单逐条)。设计冻结契约三处措辞冲突(fresh·recompute 语义/pg_jsonschema/G-ctx6)以附 A #15–17 呈报,维持 plan 内裁决、设计稿不改(用户既定默认;turn 20 收敛处置)。

## 附 B:全教训自检(turn 1–17,机械执行记录)

| 教训 | 执行记录 |
|---|---|
| **纸面加载模拟记数字**(turn 8/9:42601/42723 两轮) | 对 §3 修后草案逐块清点:CREATE TABLE 2(v13_goals/artifacts);CREATE TRIGGER 7(trg_v13_goals_append_only/trg_events_goal/trg_artifacts_append_only/trg_artifacts_effect_guard/trg_sessions_ctx_ptr_guard/trg_decisions_epoch/trg_decisions_epoch_freeze);ALTER TABLE 3;CREATE INDEX 4(ix_artifacts_content/ix_artifacts_kind/uq_artifacts_context_section/ix_events_semantic);CREATE FUNCTION 新建 18(v13_goals_append_only/v13_goal_project/v13_goal_hash/v13_context_required/v13_latch_digest/v13_prefix_identity/v13_manifest_validate/v13_judgment_defaults_check/v13_assemble_manifest/v13_artifact_land/v13_blob_land/v13_refresh_context/v13_replay/v13_artifacts_append_only/v13_artifacts_effect_guard/v13_ctx_ptr_guard/v13_decisions_epoch_fill/v13_epoch_frozen)+ OR REPLACE 3(v13_context_fresh/v13_probe/v13_judgment_envelope)= **21**;策略 INSERT 1 语句三行组(单完整字面量+::jsonb,末分号目检);加载期回填 INSERT 1;BEGIN/COMMIT 包裹 1 对。**同签名重复 0**(逐名核对;OR REPLACE 非重复定义);前向引用层级:goal_hash 先于 context_required/prefix_identity/assemble ✓、context_required 先于 context_fresh/assemble ✓、latch_digest 先于 prefix_identity ✓、prefix_identity 先于 assemble(ident CTE)✓、validate/judgment_defaults_check 先于 refresh_context ✓、artifact_land/blob_land 先于 refresh_context ✓、blob land 的 ON CONFLICT 目标索引 uq_artifacts_context_section 先建 ✓、sessions FK 列在 artifacts 之后 ✓、mode CTE 的 FROM pri 已补(P0-2,全部 CTE 可解析)✓、全部表/列先于消费者 ✓(assemble 的 sql 体创建期解析约束满足);**round 2 编辑零新增顶层对象**(gen_ver/fence belt/守卫扩/限定名均为体内改动;trg_sessions_ctx_ptr_guard 扩 INSERT 事件,触发器计数不变;refresh_context[DEFINER] 体内引用的 assemble/validate/complete/双 lander/judgment_defaults_check 均先建于其前——文件内序已核) |
| **类型算子层**(turn 7/8:jsonb 字面量/算子层) | 策略种子单完整 JSON 字面量+::jsonb(§3.2 三行组,全文件唯一 jsonb 字面量赋值族);无 text‖text 进 jsonb(refresh/replay 的 ‖ 是 jsonb‖jsonb);digest() 产物一律 encode(...,'hex');est 公式纯 int 算术((bytes+div-1)/div,无 numeric 往返);jsonb 键存在用 `?`/`@>`,值比较用 ->> 后 IS DISTINCT FROM/IS NOT DISTINCT FROM(NULL 安全,DP1 turn 5 P0-1b 同款);manifest 七层键集校验用 string_agg(ORDER BY k) 字符串全等——规避数组比较的算子面;**字典序逐串复核(P0-3)**:section 九键串='cache_scope,churn,content_hash,est_tokens,kind,payload_ref,priority,section_id,transform'(churn<content_hash:h<o——旧串全合法 fixture 皆红);顶层/policy/required_revision/replay/judgments 行/candidate 行五串同法复核在档;**枚举判断一律 IN(...) IS NOT TRUE / IS DISTINCT FROM**(null 穿透封死,DP2 criteria 同款);jsonb_object_keys 只在 typeof 确认后的独立 IF 调用(OR 不保证短路);jud 的 IN 集文本比较(uuid::text),零 cast 面;count(*) 的 bigint 经 jsonb_build_object 进数值(与 DP2 usage 同形);**round 2**:prefix_identity 去 jsonb_strip_nulls(九键材料全经显式非空检查——键集恒定,P1-9);transform 校验 CASE 产违规条件+外层 IS TRUE(与 payload_ref 同款「违规时 RAISE」,旧 IS NOT TRUE 布尔反转已修——P0-1)+分支键集 string_agg 恰等;applied 用 jsonb_typeof 拒字符串 'true'(焙劣);jud 谓词 answer/status 双条件前置;守卫 bool_or((o.value #>> '{}') IN 词表 IS NOT TRUE)对 jsonb-null 值也命中;G1 对照用 jsonb `- 'replay'` 键删除算子;**EXCEPTION↔ERRCODE 对应表(P1-10)**:V3003(显式 USING)=validate 25 处+defaults 校验器 6 处+settle 守卫与 belt 4 处;V3002=epoch 悬挂引用 1 处(沿用 DP2);其余 RAISE(入口校验/lander kind/纪律触发器族)保留默认码——契约见 OQ6 |
| **移动=增+删**(turn 8 #57) | 墓碑一/二/三均为 OR REPLACE 同签名换体(非移动);旧内联 goal_hash 公式在全树唯一存活形态=v13_goal_hash 函数体(§3.6 注);无同文件内移动块 |
| **gate 不引用未加载对象**(turn 7 #46) | 本 stage=全树第六文件,gate 断言对象全部 ≤6 号文件;G6 显式断言前缀切片(DP1/DP2 库不含本文件);DP1 M3-2「context_fresh 恒真」断言属 DP1 stage 库(不加载本文件)——与 A5 真分支断言不同库不互扰 |
| **哈希同源**(turn 6 #43 及多轮) | goal_hash 唯一来源 v13_goal_hash(消费:probe/envelope/token/prefix_identity 四处全经它);token 唯一来源 v13_context_required(**七键含 gen_ver**——P0-2;消费:context_fresh 比较侧+assemble 内嵌侧,两消费点均为 jsonb 全等/内嵌,token 增键后零列级消费点需同步);prefix_identity 唯一来源 ident CTE 单点(装配外层与 mode 同源);sections 的 tools/history 内容复用 v13_canonical_state 单点——content_hash/est/payload_ref/settle 的 blob 冻结四面同材料(sec_src.mat);verdict 记 raw 原文(digest 列退役,P0-4②);est 与 content_hash 同源字节(同一 octet_length 材料) |
| **争议引擎行为实机实证可选**(turn 10/12) | 本 DP 零新增争议引擎面:无 event trigger、无 WHEN OTHERS 吸收、无超时分类、无 57014 归因;引擎语义依赖仅 OR REPLACE 保 OID/ACL(PG 文档行为,DP2 已用同款)、触发器同事务可见性(READ COMMITTED 标准语义,DP1 effect 守卫同型)、SECURITY DEFINER 触发器随 owner 执行/触发器 EXECUTE 建后不复检(PG 文档行为,REVOKE PUBLIC 卫生面不改运行)、ON CONFLICT 部分索引推断(文档化语法)——无可实证清单,如实记「无」;若实施期对 DEFINER/ON CONFLICT 面有疑,沿 DP1 本地探针库仪式实证 |

---

## References

- 设计冻结稿:`docs/designs/v13-context-on-pg.md`(§4.7/§5.1/§5.2/§5.6/§6.1/§6.2/§9/§10/§12/§13;2026-09-19 v2 禁改)。
- DP1:`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md`(§1.3 契约表/§1.4 不变量/§3.1 M1/§3.5 advance ②/§4 M3 gate;行号引用:1973-1976/2284-2296/1990-1993/469-475/853-854/2479-2483)。
- DP2:`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md`(§1.4 契约/§1.5 不变量/§3.2 calls-cache-provenance/§3.4 19 键信封/§3.7 shadow/附 A #3)。
- 教程:ch5:55-109/126-127、ch7:20-59/95-154、ch10:140-263、ch13:14-43、ch14:85-114(均实地复核)。
- 设计审查(今日):`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md`(F1 判断点默认分支/F3 被引用内容保留/F11 artifact 存储经济——本轮 P1-6/P0-4 处置的引证源)。
- loop memory:`prompt-exports/loop-orchestrate-v13-deep-plans-runs.md`(分解表 DP3 行/turn 1-17 台账/turn 12 用户裁决)。
- 惯例参照:`docs/plans/v12-jev-pgembed-minimal-plan-2026-09-18.md`(stage 四件/命令形态/收尾纪律)。
