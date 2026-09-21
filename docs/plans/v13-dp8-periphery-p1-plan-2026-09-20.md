# DP8:v13 外围 P1 件(latch/canonical render/ForkPrefix·shadow/触点 5/触点 1 消费)实施计划

> 状态:首写(2026-09-21,loop turn 31/DP8-8)。
> 设计输入:`docs/designs/v13-context-on-pg.md`(冻结)§5.1(latch,P1 进核心)/§5.3(canonical render)/§5.6(ForkPrefix+shadow 即查询)/§6.2 触点 1(P1 shadow-first,**消费 DP7 契约**)与触点 5(P1 条件留,仅复用)/§9(latches 切片)/§10(gate 切片)/§12(YAGNI 台账)/§13(教程映射)/§14 轮 2 裁决 1。
> 评审输入:`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md` **F9(P1,本 plan 范围内消解+呈报)**、**F13(P2,已裁方向:ON CONFLICT DO NOTHING+回读采用——本 plan 立法)**。
> 基座:DP1–DP7 七份已验收 plan(十三 stage 前缀库);直接地基=DP3 §1.4 DP8 行(latch digest 缝/generation 行真值接管/render 消费/llm request 钉缝)、DP7 §1.4 DP8 行(render_policy 行 v1 已立+落地日 identity/token 追动/触点 1 归属裁定=其附 A #9)、DP5 §1.4 DP8 行(无耦合注记)。
> 撰写方式注记:context_builder 通道延续本日 ACP 故障先例(loop turn 13×2/18×4/22/25/27/29,MCPToolExecutionCancelledError),按父控制器 brief 授权**代行撰写**;全部上游契约与机制面经一手勘探核实(§1.2 逐条列 file:line 级来源)。
> **G-ctx6 绕行注记(用户既定默认)**:设计 §10 G-ctx6 原措辞已被 §5.4/§14 轮 2 取代——与 DP7 同款绕行,本 plan 零触碰 tier 面,不重开。

## 0. 执行索引

| 项 | 内容 |
|---|---|
| **Goal** | 把 §5.1 latches 表(INSERT once/触发器拒/并发首触发 adopt/admission 上限)、§5.3 首版单一 canonical render(render 纯函数+render_policy 版本进前缀身份与 token 追动)、§5.6 ForkPrefix 关系化(v13_fork 三种 spawn+validate-spawn 前置执法+cache probe 审计对账)与 shadow 即查询(双跑 diff/零 diff N turn/人审 flip 仪式)、§6.2 触点 5(仅复用既有 intent 行的软门控立法+shadow v1)、§6.2 触点 1(消费 DP7 附 A #9 契约,零重实现),加上 **DP3 generation 策略行真值接管**(会话级首触发冻结)落成 v13 第 14 个 stage `v13/periphery/`;并修复 DP7 换体事故造成的 token 键谱回归(corpus/recall_ver 丢失——附 A #1,主呈报项) |
| **Done when** | `uv run python v13/periphery/test_periphery.py` 退出码 0(A–I 九组全绿);提交前 DP1–DP7 **全部十三个** stage 的 gate 在各自前缀库复跑通过(AGENTS.md 前置条件 1);收尾工件齐(load.py 第 14 位/README/一里程碑一提交) |
| **Key files** | `v13/periphery/v13_periphery.sql`(全新增,SQL_LOAD_ORDER 第 14 位纯末尾追加)+`v13/periphery/{setup_db.py,test_periphery.py,README.md}`;`v13/load.py` 追加一行 |
| **Dependencies** | 分解表:DP3;实际加载依赖 DP1–DP7 全部十三文件(前缀库)。上游零改动:v12 既有文件、v13 一至十三号 SQL 文件(尚未实施——实施期由本 plan 授权清单内的 OR REPLACE/ALTER 在 14 号文件内换体) |
| **Size** | 1 里程碑 1 stage 1 提交;SQL 一个文件(36 条顶层语句;实施期段体单源抽取件落实体则 37——附 B 计数);gate 一个文件(A–I 九组 56 断言) |

---

## 1. 定位与边界

### 1.1 本 DP 在 v13 版图中的位置

DP8 是设计 §11 交付排序第 5 条「latch(轮 2 已裁 P1 进核心)、intent 软门控(仅复用既有 intent 行)、压缩 hint shadow-first」的整块落地,补齐 §5 五件套的最后两块半:**渲染**(render 本体+策略行激活;策略行 v1 canonical 已由 DP7 立壳,本 plan 落函数体与身份/token 接线)与 **§5.6 ForkPrefix/shadow**;并把 DP3 立的三个骨架缝换成真值:`v13_latch_digest` stub→真函数、generation 策略行 mock 骨架→会话级首触发冻结机制、system_blocks_digest '-none-'→blob 落地机制。触点 1(压缩 hint)按 loop turn-30 裁定**纯消费 DP7 §1.4/附 A #9 契约**,本 plan 零重实现(§1.3 OQ6)。

- **`v13/periphery/`(第 14 位)**——外围 P1 平面,纯 SQL 零外部 IO:latches 表+触发器族+fork/probe/shadow/intent-gate 函数族+identity/token/render 换体链(六件 OR REPLACE/换体:prefix_identity/context_required/goal_hash/assemble/validate/refresh+blob_land 词表扩)。
- **两件事不要焊在一起(ch14.1 原文)**:本 plan 只落 **ForkPrefix 平面**(provider 前缀缓存的身份);**会话树 fork 的读穿透**(v_prefix_events 视图/canonical_state 前缀窗/预算继承)是另一条前缀的机制,零触碰(§1.3 OQ4 裁决+§7)。

**硬边界**:零改动 v12 既有文件;零改动 v13 一至十三号 SQL 文件的文本;对既有对象的全部变更限定 §3 标注的授权清单(六件 OR REPLACE 换体+两处 ALTER/ADD+一处词表扩+策略行追加);`v13_advance`/`v13_parse`/`v13_complete`/`v13_resolve_judgments`/`v13_envelope` **零改动**(frozen 面,§1.3 OQ4 的论证基座)。

### 1.2 上游契约消费清单(逐条,来源:DP1 §1.3 / DP2 §1.4 / DP3 §1.4 / DP4 §1.4 / DP5 §1.4 / DP6 §1.4 / DP7 §1.4 对 DP8 行 + 机制面勘探)

| # | 契约(来源) | 本 plan 落点 |
|---|---|---|
| 1 | DP1 §1.3 DP8 行:「无直接耦合;latch 参与前缀身份,不影响解析/变更两相」 | latch 全部新面(latches 表/fire/fork 复制)零进 parse/advance/complete;identity 消费点=prefix_identity(DP3 面,本 plan 换体)——两相纪律结构性维持 |
| 2 | DP1 sessions fork 两列 `parent_session_id/parent_cutoff_seq`(DP1:120–121「fork 留缝(ch14/DP8)」) | v13_fork 写入这两列+新增第三列 `spawn_kind`(§3.1);三列不可变触发器(ch14.5「一次写入永不改」) |
| 3 | DP1 events.type 开放词表(DP1:129–132;append_event 五参签名 DP1:465 用例) | 新事件类型 `forked`/`audit/cache_probe`/`audit/shadow_obs` 零 DDL 进开放词表;全部经 v13_append_event 落行 |
| 4 | DP1 #20:v13_complete 对非 llm/tool/judge kind 零语义事件;llm 分支 result 形状校验只要求 text 非空(DP1:446–451) | probe/shadow/render 零触 complete;worker 契约单侧扩记(result 增 usage.cache_read_input_tokens/wire_digest 键)——DP7 附 A #3 同款「result 增键零上游改动」先例 |
| 5 | DP1 ④ llm effect request 恒 `{route:{action,reason}}`(DP1:2484–2486,DP7 附 A #3 勘定) | **llm request 钉缝裁决(OQ5)**:DP3 留缝「render 落地时经 worker 契约或 route 输出扩展补」——本 plan 取 worker 契约面(llm worker 调 v13_render(sid) 取 wire bytes;result 回携 wire_digest+context_artifact_id),advance 零改动,request 形状零改 |
| 6 | DP2 §1.4 DP8 行:fork 继承语境下 decisions 是 session 作用域不重放;fork 后判断重问成本由 canonical 缓存吸收(fork 的判断重放上限=缓存命中率,无需新机制);shadow flip 分析可消费 v13_shadow_reroute 的 current/shadow 对照列 | 零新机制(不建跨 session 判断重放);§1.3 OQ6 记 shadow 分工:judgment 阈值面=DP2 v13_shadow_reroute(已存在),assemble/render 策略面=本 plan v13_shadow_observe——两平面各自零新增 API 成本 |
| 7 | DP3 §1.4 DP8 行:**`v13_latch_digest(uuid)` 是 latch 前缀身份缝**:DP3 stub 返回 '-none-',DP8 函数替换(表本体归 DP8;替换时 latch 版本必须并入 token 追动键缝——OQ1 gen_ver 同缝) | §3.3 换体一:v13_latch_digest 真函数(空集 '-none-' 与 stub 逐字衔接);token 追动=ident_ver 第十一键(OQ1) |
| 8 | DP3 generation 策略行:provider/model/system_blocks_digest 从版本化行读(fail-closed 行缺失/键 NULL→RAISE);骨架值 mock/'-none-'(DP3:447–451「DP8 render 落真值接管」) | OQ2 真值接管:行 v2(机制真值:system_blocks 列表+blob 落地+latch 会话级冻结);**值仍 mock**(ops 翻 v3 才切真 provider——数据真值归运维,附 A #11) |
| 9 | DP3 §1.4 DP8 行(llm request 钉缝)+OQ3:DP3 已在 result/event 侧落全量 provenance(context_artifact_id 经 result 流进 llm/message 与 effect 行) | probe 的对账锚=effect.result->context_artifact_id(零新 provenance 面);wire_digest 比对用同通道 |
| 10 | DP3 token 追动键缝:「进 prefix_identity 材料的输入必须在 token 有键——latch 落地时其版本并入同一键缝(扩 gen_ver 语义或增独立键);键集增删⇒全域恰一次 refresh」(DP3 OQ1) | OQ1:独立键 ident_ver(=sha256{latch_digest,render_policy_version},单键覆盖两个新材料输入——附 A #10 裁量);键集 10→11(恢复谱系,见 #12) |
| 11 | DP3 OQ4/OQ5:manifest 结构(exact replay 的 replay 块覆盖语义/`v13_replay` 永不重跑 assemble/identity 基 mode 判定/钉定版本=只读 recompute 不 settle) | fork 的 exact_replay 子会话继承 artifact 指针后经 v13_replay 逐字节回读(gate E1);shadow 的双跑=钉定版本只读 assemble(OQ5 原文形态) |
| 12 | **DP4 §3.6/DP5 L5 机制面(本 plan 勘探核实)**:token 第八键 `corpus`(DP4,§3.6 八键体)、第九键 `recall_ver`(DP5 OQ8,§3.1 L5 九键体+gate H4 九键集断言);**DP7 换体一「机械复制 DP3 §3.2 加载态原文…键集 7→8」(DP7:459–462)与不变量 8「token 八键」未携带 corpus/recall_ver——≥12 号库的 token 回归(turn 34 已在 DP7 源头修正,本行呈报留档)** | §3.3 换体三:context_required 十一键全谱恢复(DP3 七键逐字+corpus 逐字+recall_ver 逐字+econ_ver(经 DP7 单源函数 v13_econ_ver)+ident_ver);gate I1 断言十一键集恰等——**修复面,附 A #1 主呈报项** |
| 13 | DP4 §1.4 DP8 行:exact replay 正文回取走 DP3 blob/artifacts;chunks 保留是第二重保险;fork 不触语料面 | render 的 section 正文源=blob/goal payload_ref(DP3 冻结面);fork 零语料触碰 |
| 14 | DP5 §1.4 DP8 行:无直接耦合;前缀身份材料不含语料与 k;render 消费 manifest 含真候选后零变化(candidates 不进 sections——render 按段渲染,chunk sections 落地日自动进段,render 零改) | §3.3 render sections 通用渲染(payload_ref 判别);§1.4 对实施期发布「chunk sections 落地日 render 零改」确认 |
| 15 | DP6 §1.4 DP8 行:①fork 后 per-chunk 判断重问由 canonical 缓存吸收(G-ctx4-3 证据面)②exact replay 消费旧 verdict 零新依赖(v13_replay)③render 消费 manifest 时 judgments/candidates 的 filter 字段即上游形态;prefix_identity 零耦合(filter/memory 不进身份材料) | 零动作(语义确认);render 的 judgments 段不进 wire(判断是证据不是呈现内容——§5.3 纪律注记) |
| 16 | DP7 §1.4 DP8 行:**render_policy 行已立**(v1 canonical,DP7:265–269 种子原文)——「DP8 落 canonical render 函数时消费本行;**render 落地日 render_policy 版本必须并入 prefix_identity 材料+token 追动键**;呈现偏好不立法(臆断不立法,§5.3)」 | OQ1/OQ3 全额兑现:材料第九键 render_policy_version+token ident_ver+render 函数族消费该行(renderer='canonical' 词表执法) |
| 17 | DP7 §1.4 DP8 行(latch):manifest v2 economics 块与 latch 零耦合(latch 进 prefix_identity 不进 economics);tier 不消费 latch | latch/identity 面与 economics 块零交叠(§1.5 不变量 4 的双向面);tier 面零触碰 |
| 18 | DP7 附 A #9(触点 1 归属裁定):DP7 已落 shadow-first 机制(hint 记录面 economics.compact_hint+硬类保护);「建议控制器把 DP8 brief 改为消费本 plan §1.4/触点 1 契约,避免双实现」——turn-30/31 brief 已采纳 | **纯消费**:hint 生产/记录/硬类保护/flip 证据门槛全部沿用 DP7;本 plan 零 hint 代码(§1.3 OQ6 记分工与 flip 证据面);shadow 仪器(OQ6)与 hint flip 的关系=证据面互补注记,不越权 |
| 19 | DP7 worker 契约(llm result 携 usage+model;附 A #3) | probe 的 usage 消费基础;本 plan 单侧扩记 cache_read_input_tokens+wire_digest(README worker 契约清单扩两键,DP1 result 形状校验零上游改动) |
| 20 | DP6 OQ5/附 A #9 先例:审计事件的落点裁量(recall 平面纯 SELECT 不可写事件→消费契约后移) | probe/shadow 的审计事件由**有事件写权的面**落(route 面:probe 函数/settle 内 observe)——先例的镜像适用 |
| 21 | DP2 v13_policy(name) 单源读+策略翻版仪式(INSERT inactive→双 UPDATE 同事务翻 active)(DP1 §1.3 载体契约) | 本 plan 六行新策略(latches/cache_probe/shadow_flip/shadow_watch/intent_gate)+generation v2 全走同仪式;读侧一律 v13_policy() |
| 22 | DP6 工程纪律(:153):「OR REPLACE 大体从上游 stage 文件**加载态原文机械复制**(比计划文本更权威),仅按标注增量编辑」 | §3.8 全部换体的复制源解析规则+增量链完整性断言(gate I 组)——DP7 违例(#12)的防线制度化 |
| 23 | DP1 thresholds 表=route intent 带载体(DP1:1060–1070 种子;route_policy 两列锚定)(DP7 附 A #1:thresholds 表归 route intent 带) | 触点 5 的置信带判定**只读 thresholds 表**(与 route 同一真相源,零第二 band 定义——gate H7) |

### 1.3 Open Questions 裁决(本节为最终权威)

**OQ1 裁决:identity/token 增量形态——prefix_identity 材料恒九键(八+render_policy_version),token 恒十一键(全谱恢复+ident_ver 单键合并 latch 与 render 两个追动源);manifest_version 2→3。**

- **材料第九键**:`render_policy_version`(int,活动行版本,fail-closed 缺行 RAISE——与 provider/model 同姿势)。DP3 函数体现行八键 {provider, model, system_blocks_digest, tools_rev, tools_digest, goal_hash, latch_digest, manifest_version}(DP3:531–560 实读;DP3 注释「恒九键」为计数笔误,以函数体为准)——DP8 落地日恰成九键,DP7 §1.4「render_policy 版本必须并入 prefix_identity 材料」就此兑现。
- **token 第十一键 `ident_ver`** = `encode(digest(jsonb_build_object('latch', v13_latch_digest(p_sid), 'render_policy_version', <活动版本>)::text,'sha256'),'hex')`(单源函数 v13_ident_ver,prefix_identity 与 context_required 共消费零复制)。DP3 OQ1 对 latch 给了二选一(「扩 gen_ver 语义或增独立键」)——**取独立键**(附 A #10:gen_ver 承载生成行版本的单一语义,塞入 latch/render 会把「版本号」键变成「摘要」键,破坏单调域表述与逐键可读性;单键合并 latch+render 的论证:两者都是「进身份材料、非策略版本号」的输入,digest 键是 goal(身份型)键的同族先例)。非单调键与 goal 同族:键集比较是 jsonb 全等非序比较,单调性非正确性前提(DP3 OQ1 全部键「单调」是性质描述非执法面)。
- **键集增删的既定语义照用**:10→11(恢复+新增)⇒ 旧 active token 全失配 ⇒ 全域恰一次 refresh(DP3 OQ1);manifest_version 2→3(外层 12 键+render 块,校验器 v4——§3.8);材料含 manifest_version ⇒ 每会话身份随升版恰动一次。
- **DP7 键谱回归修复(消费清单 #12,附 A #1)**:context_required 换体按全谱十一键书写——sem/dec/goal 三键表达式自十三号加载态逐字复制,corpus/recall_ver 自八号加载态逐字复制,econ_ver 经 DP7 单源函数 v13_econ_ver() 调用(零公式复制),gen_ver 改经 v13_generation_effective(OQ2)。gate I1 断言键集 string_agg 恰等十一键字典序串。

**OQ2 裁决(生成模型真值接管):策略行=目录与默认值(唯一配置面);会话级钉住=首 settle 自动 fire 的 `generation` latch(值=当时活动行快照);prefix_identity 经单源函数 v13_generation_effective 读「latch 优先、无 latch 落活动行」。**

- 依据链:(a) §5.1 latch 语义原文「首触发即冻结(模型选择、缓存 scope 资格)——mid-session 漂移即隐性 cache-break」——模型选择是 latch 的点名用例;(b) ch14.5 redeploy 安全绳「新策略=新版本行;**进行中会话继续旧版本,新会话拿新版本——热切换不需要 quiesce**」,拿新版本走的必须是 fresh fork——若每会话每次装配都读活动行,生成行翻版会把全部在途会话的身份打碎(全量隐性 cache-break),安全绳失效;(c) DP3 已把 generation 行定为身份材料源,但未定会话作用域——latch 是现成的会话作用域冻结件。
- 机制:`v13_generation_effective(p_sid)`→jsonb(STABLE):有 latch('generation') 返回 latch 值(含 generation_version);无则读活动行+注入 generation_version。settle(refresh 换体增量 b)在装配前内联 fire-or-adopt:`INSERT INTO latches … SELECT … ON CONFLICT DO NOTHING` 后回读(与 v13_latch_fire 同姿势,但 settle 持锁内联走直插——public 函数对 'generation' 保留名拒绝,防外部预钉)。**首触发=首次装配**,「首触发即冻结」的时点语义就此落地。
- 与 latch 冻结语义的关系(逐字回答 brief 的裁决要求):生成行翻版(mid-session)对已 pin 会话——identity 不变(latch 值不变)、token 不追动(gen_ver=latch 内 generation_version,恒定)、零 refresh、缓存身份保住;对未 pin 会话(从未装配)——下次首装配取新行。**会话级模型选择=把 generation 行快照进 latch,策略行直配=目录真值;两者不矛盾:行是源,latch 是会话作用域的冻结投影。** spawn_overrides(fresh fork 专用,OQ4)直接改写子会话的 generation latch 值——「换 model/thinking 档」的关系化形态。
- **值仍 mock**:generation v2 种子 {provider:'mock', model:'mock-1', system_blocks:[], system_blocks_digest:'-none-'}——机制真值(结构/校验/blob 通道/latch 冻结)全落地,数据真值(真实 provider/model/系统块正文)归 ops 翻 v3(README 仪式),与 DP3 骨架值逐字衔接(空表 digest='-none-'——identity 空会话可比性,gate D6)。

**OQ3 裁决(render v1 canonical):render 是纯函数族三件(v13_render_wire/v13_render_receipt/v13_render),wire=canonical jsonb {system,tools,sections};wire 不落库;render 块 4 键进 manifest v3;cache marker=每段确定性段界标记;provider policy=protocol_only(协议适配归 driver,呈现偏好不立法)。**

- `v13_render_wire(p_sid, p_manifest, p_render_ver)`→jsonb:system=generation v2 列表→system_block blob 按序回取(artifacts 内容寻址);tools=canonical_state(sid)->'tools' 投影(**与 tools_digest 同源同材料**——identity 与 wire 的 tools 面零第二实现,gate D3);sections=manifest 全序 (prank,section_id) 每段 {id, marker, body}:body 经 payload_ref 判别回取(blob→context_section inline;goal→v13_goals payload::text)。**cache_markers:true 的语义**(render_policy v1 种子键)= 段界确定性标记串(含 section_id 与 cache_scope 字样)进 body 装配——前缀稳定性的显式信号位,非 provider 私有协议。
- `v13_render_receipt(p_sid, p_manifest)`→jsonb 4 键 {renderer:'canonical', render_policy_version, wire_digest(=sha256(wire::text)), stable_prefix_est_tokens}:**携带估计的冻结点**(OQ5 消费)。est=system+tools 字节数+churn=0 段 body 字节数,同一 est 公式(整数算术,(bytes+div-1)/div,除数=assemble_manifest 策略行 est_bytes_per_token——DP3 契约零改)。装配 v4 在 sections 定稿后调 receipt,以 `render` 键并入 manifest(外层第 12 键)。
- `v13_render(p_sid, p_render_ver DEFAULT NULL)`→jsonb:读 sessions.context_active_artifact→inline→render_wire(worker 面;钉版本=shadow 面,OQ6)。**wire 不落库**(F11 经济纪律,附 A #12):每 turn 一份完整 wire 拷贝=最大的未入账 token 消耗;纯函数+内容寻址 blob+manifest render 块(含 wire_digest)⇒ bytes 恒可确定性重现,「artifact 固化实际交给模型的内容」以 (manifest+blobs+render 版本) 三元组兑现,gate D1 断言重现字节等。
- **driver 适配边界**:wire bytes=v13_render(sid)::text(jsonb canonical 序列化,PG 键序规范化——DP3 prefix_identity 同款确定性依赖,无新引擎争议);DeepSeek/OpenAI 等协议映射归 driver(README worker 契约),v13 不立法 per-provider 呈现(§5.3 轮 2 裁决 6 逐字)。

**OQ4 裁决(fork v1=ForkPrefix 平面的 spawn/replay 壳;会话树读穿透+预算继承+turn-running 子会话=激活条件门控的不做项,附 A #3)。**

- **`v13_fork(p_parent, p_cutoff, p_kind, p_overrides DEFAULT NULL)`→uuid**(SECURITY DEFINER,search_path 钉死;EXECUTE 归 v13_route;签名=ch14.7 练习三元组+第四可选参——超集注记,附 A #8):①kind 词表 {exact_replay,recompute,fresh_fork} 执法;②父行 FOR UPDATE+cutoff∈[0,父 next_seq-1] 越界 V3008;③继承 artifact 解析=**链回走**:从父 context_active_artifact 沿 manifest.replay.prior_artifact_id 回走,取最新的 required_revision.sem≤cutoff 者(exact_replay 无覆盖者→V3008 响亮);fresh_fork 不继承(NULL);④建子行(parent 两列+spawn_kind+route_policy 继承父值);⑤**latch 复制**:exact/recompute 全量复制父 latch 行(fired_at 保真,fresh_fork 零复制+overrides 落进自己的 generation latch);⑥validate-spawn 前置执法(下条);⑦exact/recompute 子行 context_active_artifact=解析所得、context_active_revision=其 required_revision;⑧`forked` 事件(payload:{kind,parent,cutoff,artifact,parent_identity,child_identity,overrides});⑨返回子 id。**fork 体零父 events 扫描**(源码断言 gate E9——「O(1) 两列写入」的除事件结构证明;链回走深度=refresh 链长度,注记非事件量)。
- **validate-spawn(ch14.3 三件套之二,提交前执法=事务内 RAISE 即不落行)**:对身份声称类 kind ∈ {exact_replay, recompute}:子会话此刻计算身份 `v13_prefix_identity(child)` vs **继承 artifact 冻结时记录的 prefix_identity**——不等即 V3008(覆盖一切漂移源:父 freeze 后新 latch、tools 目录 bump、goal 漂移、overrides 误携;比较锚=artifact 非父当前态——「声称的是那份缓存身份」的语义精确化)。对 fresh_fork 无身份检查(设计原文:validate-spawn 拒「破坏缓存身份的 fork」;fresh 同身份=同前缀缓存命中,无害)——fresh 子必携 generation latch(fork SQL 无条件落,父此刻生效值为基底),「fresh 子 latch 空集」不成立;无 overrides 且 cutoff 对齐 settle 点时子身份可与父 artifact 身份相等,为合法形态(L4 P1-2;gate E5 改记录面断言)。**overrides 合法性**:p_overrides IS NOT NULL 且 kind≠fresh_fork → V3008(「thinking 预算 clamp 到不同档却声称 exact replay」的关系化拒绝面)。
- **cutoff 语义边界(gate E 组负向,README 明示)**:exact_replay 要求 cutoff 对齐 settle 点——若 cutoff 与覆盖 artifact 的 sem 之间存在 user/message(该消息属未来 settle),子会话 goal_hash(前缀感知)>artifact 冻结时 goal ⇒ 身份不等 ⇒ V3008。这是 fail-closed 的正确行为(该 cutoff 无「当时的」context 可声称),非缺陷。
- **不做面(§7+附 A #3)**:v_prefix_events 视图、canonical_state/goal 投影/transcript/token sem 的前缀窗改写、预算继承(ch13 递归聚合)、父子并行/读穿透/ALTER 探针 gate(ch14.6 G7 会话树半边)。论证:①设计 §5.6/§13-ch14 映射只点名 ForkPrefix 关系化+三种回放语义,会话树视图是教程 ch14.2 机制;②turn-running 子会话需要 canonical_state 语义窗重设计——子会话自身 last_user_seq 与父前缀事件的 seq **命名空间错位**(父 100 事件/子首消息 seq=1,「seq≤last_user_seq」谓词把父前缀误当未来事件丢弃),非机械换源;③advance/route 的 events 直读面(finish 扫描/origin 锚定)全部需要改写=违反 advance 冻结纪律。激活条件:首个真实 fork 子会话 turn-runner(dream worker/RSI 层)出现——emergent 同款 producer 门控。
- **子会话 v1 语义=spawn+replay 壳**:可读(v13_replay 逐字节)、可审计(forked 事件)、可对账(cache probe 于其首个 llm);不可推进 turn(advance 面未改写——README 明示,误用即普通空会话行为,非静默错数据:其 canonical_state 为空,装配产出空 history 的合法 manifest)。

**OQ5 裁决(cache probe):worker 契约面的显式函数 `v13_cache_probe(effect_id)`;估计=settle 冻结的 render.stable_prefix_est_tokens;实际=effect.result->usage->cache_read_input_tokens;差额超容差→`audit/cache_probe` 审计事件;纯审计零状态变化。**

- **为什么 worker 契约面而非 events 触发器**(附 A #7):DP1 v13_complete 冻结不可改;DP3 先例(context_artifact_id)就是 worker 契约面+gate 断言;触发器面(probe 塞进 complete 事务)会加深持锁事务,且 effect_done 载荷定位 effect 需要拼接——契约面最简且 gate 可测(gate F 全组走真实 complete 后调 probe)。
- 对账锚=**effect.result->context_artifact_id**(DP3 已落 provenance,消费清单 #9)——probe 读该 artifact 的 manifest.render 块,天然免疫「complete 与 probe 之间 refresh 换指针」竞态(不读 sessions 当前指针)。
- 两条对账线:(i) **wire 完整性**:result->wire_digest(本 plan 单侧扩记的 worker 契约键,缺省跳过)≠ render.wire_digest → 事件 basis='wire_mismatch'(worker 实发字节≠结算时冻结字节——隐性 cache-break 的行级证据);(ii) **缓存命中估计**:|usage.cache_read_input_tokens − stable_prefix_est_tokens| > max(est×tolerance_ratio, min_tokens) → 事件 basis='estimate_gap'(容差键随 cache_probe 策略行)。usage 缺键→no-op 零事件(worker 契约记「应携;缺失=无对账面,不是错样本」——DP7 R_o 同款措辞纪律)。非 llm/非 succeeded→no-op。**每次 llm 完成都对账**——「第一次 llm」(ch14.3)是子集,持续对账免费获得首检+漂移巡检;「估计错不改正确性」=probe 体零 UPDATE 零重试(结构性,gate F6)。
- fresh fork 允许 miss=不做失败判定(纯审计形态自然成立;v1 fresh 壳无 llm,语义注记进 README)。

**OQ6 裁决(shadow 即查询):仪器=`shadow_watch` 策略行(名集封闭 v1 {render_policy, assemble_manifest})+settle 尾部 v13_shadow_observe(钉定版本只读双跑)+events 载体 `audit/shadow_obs`+v13_shadow_streak 就绪查询;flip=人审仪式(INSERT 已在场+双 UPDATE 翻 active),auto-flip 拒。**

- 依据:§5.6「shadow 演出:新旧策略双跑 assemble,diff 两份 manifest,零 diff N turn 后 flip——manifest 是行,这只是一个查询」;DP3 OQ5 钉定版本=只读 recompute 面(不 settle)——双跑的第二个 assemble 就是这个既有形态,零新写入面。**观察事件进 events**(append-only 日志平面,零新表——「manifest 是行=一个查询」的载体纪律);streak=对 (name,version) 最近连续观察的布尔聚合查询。
- **双跑可表达域 v1 收窄为 {render_policy, assemble_manifest}**(fail-closed,词表外 name→V3008):render 族=render(sid) vs render(sid, shadow_ver) 的 wire_digest 等;assemble 族=assemble(sid) vs assemble(sid, shadow_ver) 的**内容投影**等(sections+candidates+judgments——剔除 policy/required_revision/economics 观察块,否则版本号自身永不相等)。context_tiers 动作 flip 的证据面**不在本仪器**(其 shadow=DP7 actions_enabled:false 的记录面+校准流程,双跑 diff 在 actions off 时恒等——无信息量);此为 DP7 附 A #9 契约的消费侧确认:hint/tier flip 走 DP7 校准证据门槛,render/assemble 族 flip 走本仪器,两证据面并行不混。
- **flip 不自动**(§6.7 在线 learned policy 拒绝项的边界执法:策略凭自身观察翻自身=自学习):ready=v13_shadow_streak 返回 {streak,ready}(阈值=shadow_flip 策略行 min_zero_diff_turns v1=10);翻版=运维仪式(README:观察面复核→双 UPDATE 翻 active→身份/token 追动链路自然触发(C4 同链));台账项:auto-flip(触发=人审仪式误操作成本实测超标)。
- 生产 v1 种子 `shadow_watch {targets:[]}`(空表=零观察零事件——仪器交付+gate fixture 演练后回滚,不预置假 watch)。

**OQ7 裁决(触点 5 意图软门控):v1=立法+纯读判定函数+shadow(actions_enabled:false)+三重「不新调」执法;实际绑定不武装,激活契约对实施期发布。**

- 法条(§6.2 触点 5 裁决原文逐条入法):①只软门控可选且昂贵的外部 source;②低置信/CJK/缺失→绑超集;③不得排除规则、当前消息、必要历史、工具配对;④仅复用既有 intent 行,为此新调 Jev 则 P2 不做。
- `v13_intent_gate(p_sid)`→jsonb {mode, basis, actions_enabled}:**STABLE 纯读**(结构性不可写);输入三源全复用——intent 行=decisions 最新 signal='intent'∧answer 非空∧status∈answered/cached(当前 turn 语义=latest,壳面注记);置信带=thresholds 表(消费清单 #23,与 route 同一真相源,gate H7 改带行→mode 翻转证明单源);CJK 判定=goal 活动行文本经 DP5 分段器(v13_query_segments 的 cjk 段存在即 CJK——DP5 契约复用,零第二分词)。mode∈{superset, narrow_eligible}:缺失/低置信/CJK→superset(basis=missing/low_confidence/cjk);高置信非 CJK→narrow_eligible。**v1 actions_enabled=false:mode 只是记录,narrow 不产生任何绑定效果。**
- 为什么 v1 不武装(附 A #4):①v13 的 manifest sections 尚无可选外部段(chunk sections=DP6 OQ7→实施期缝,candidates 不进 sections——DP5 §1.4);②对 candidates 的意图收窄在无语料-intent 分类账时与 k 截断策略(recall_k)不可区分=重复立法;③提前收窄的失败方向是 F2 族静默证据丢失——superset-on-doubt 的保守面优先。激活契约(§1.4 发布):intent_gate v2 翻 enabled 必须同批定义确定性收窄规则+可选段词表+needed 不变性断言的前置满足(chunk sections 落地)。
- **「不新调」三重执法**(gate H):STABLE+源码扫描(intent_gate 体零 typesafe_ask,DP5 G2 归一化口径同款)+judgment_calls 计数零增量(fixture 前后对照)。**needed 集不变性断言**:gate 行在场/缺失两态,信封 needed 数组字节等(gate H5——v1 结构性成立:信封链零调 gate;断言防实施期接线走样)。

**OQ8 裁决(latch 执法细节):PK=INSERT once 结构执法;UPDATE/DELETE/TRUNCATE 触发器拒(V3008;TRUNCATE=BEFORE TRUNCATE 语句级触发器,行级触发器不触 TRUNCATE——L4 P1-4);并发首触发=ON CONFLICT DO NOTHING+回读采用(F13);跨行上限=admission(sessions 事务锁内计数)+fail-closed RAISE(轮 2 裁决「非 CHECK」逐字);消费面零破坏性 consumed_at(v1 无消费者——manifest membership 形态随激活面立)。**

- `latches(session_id, name, value, fired_at)` 列集=§5.1/§9 逐字;PK(session_id,name);name 词表 `^[a-z][a-z0-9_]{0,62}$`(无 '::'——与 signal 命名空间不撞,DP1 #48 同型纪律);'generation' 为 settle 保留名(public fire 拒,V3008)。
- `v13_latch_fire(sid,name,value)→jsonb`(SECURITY DEFINER,route):sessions FOR UPDATE(admission 事务锁——与 settle/advance 同锁同序,全库锁序不变量零新增面)→已有即回读返回(adopt)→计数≥latches.max_per_session(策略行 v1=16)→V3008(不静默丢)→INSERT ON CONFLICT DO NOTHING→回读返回(F13 双连接恰一行、同值——gate B3)。
- `v13_latch_digest(sid)`(换体一):`coalesce(sha256(jsonb_agg({name,value} ORDER BY name)::text), '-none-')`——**fired_at 不进材料**(时间戳非内容身份;fork 复制保 fired_at 而子会话 digest 与父相等=前缀身份继承的字节基础);空集 '-none-' 与 DP3 stub 逐字衔接(未 pin 会话身份可比性)。
- 消费语义(轮 2「非破坏性」的 v1 落地):latch 的消费=identity 材料+fork 复制,均读不写;target_turn+manifest membership 的消费表达**无生产者不立**——首个 latch 消费者(如 cache scope 资格)落地时按 §5.1 原文形态立,当前零代码(§7)。

**OQ9 裁决(单 stage):`v13/periphery/` 第 14 位,一文件一 gate 一里程碑一提交。** 依据:①分 stage 的正交性依据在此不存在——latch/render/fork/probe/shadow/intent 共享同一换体链(prefix_identity/context_required/assemble/validate/refresh)与同一身份语义,拆开=五处 OR REPLACE 链重复走一遍(DP7 双 stage 的 OQ1 论据反向成立);②brief 明文「你的 stage=v13/periphery/(第 14 位)」;③失败半径同族(纯 SQL 零外部 IO);④AGENTS.md 一里程碑一提交由单里程碑满足。

### 1.4 本 plan 对实施期与后续发布的契约

| 消费方 | 契约 | 形态 |
|---|---|---|
| 实施期(chunk sections 落地日,DP6 OQ7 缝) | render 零改:sections 通用渲染(payload_ref 判别),chunk 段=纯数据进 manifest 即进 wire(DP5 §1.4 DP8 行的兑现确认);intent_gate v2 武装的三前提(OQ7 激活契约) | 确认+激活契约 |
| 实施期(fork turn-runner 激活日,OQ4 缝) | 前缀窗语义包:v_prefix_events 视图+canonical_state/goal/token sem 前缀命名空间重设计+预算继承(ch13)+advance/route events 读面改写——独立工作包,附 A #3;spawn 壳语义与 forked 事件载荷为稳定接口 | 缝清单 |
| 实施期(真实 provider 接入日) | generation v3 翻版仪式(INSERT v3 真值→双 UPDATE 翻 active);system blocks 正文经 v13_blob_land('system_block',…) owner 落地→digest 重算→v3 同批;已 pin 会话不受影响(OQ2 安全绳) | 流程文本(README) |
| 后续(latch 首个消费者) | 消费表达=target_turn+manifest membership(§5.1 轮 2 原文,非破坏性 consumed_at);latch 词表新名走 v13_latch_fire | 台账+规则 |
| 后续(auto-flip) | 触发条件=人审 flip 仪式误操作成本实测超标;v1 拒(§6.7) | 台账项 |
| 终局交叉覆盖检查(loop 收口) | 附 A #1(DP7 token 键谱回归)建议列入交叉检查清单——本 plan 已修,但 DP7 plan 文本与十三号实施文件需对照核实(corpus/recall_ver 在 12/13 号 assemble/token 体内的存续) | 呈报项 |

### 1.5 不变量(全 plan 有效,违反即设计背离)

1. **DP1–DP7 全部不变量原样继承**(两相分离/锁内零外部 IO/纯判断 IO 例外唯一/双登录/αβ 语义/token 与 manifest 同语句快照/冻结即不可变/manifest 只消费内容寻址身份/装配确定性/行自证/重摄取同事务/外部只记 hash/全库锁序 sessions→tools_meta→策略活动行→effects/退役源过滤/三禁/批写锁纪律/零活策略读)。本 plan 全部新读写零进 parse/advance/complete/resolve。
2. **latch 一次性**(§5.1 逐字):INSERT once(PK)+UPDATE/DELETE/TRUNCATE 触发器拒+并发首触发 ON CONFLICT adopt(F13)+上限 admission+事务锁 fail-closed(非 CHECK,轮 2);fired_at 不进 digest;保留名 'generation' settle 专用。
3. **两条前缀不焊**(ch14.1):本 plan 只落 ForkPrefix 平面;会话树读穿透零触碰(v13_canonical_state/v13_advance/v13_route/v13_complete 零改动);goal_hash 的前缀感知是 identity 需求的最小例外(非 fork 会话逐字节等——gate E6 回归钉死)。
4. **进 identity 材料的输入必须在 token 有键**(DP3 追动键缝):render_policy_version→ident_ver;latch_digest→ident_ver;generation 会话快照→gen_ver(latch 内版本);**economics 块与 latch/identity 零交叠**(DP7 §1.4 双向);tier 不消费 latch。
5. **render 确定性**:render 族零时钟/零随机/策略经版本参数或单源读;同 manifest 两调字节等(gate D1);wire 不落库(重现=manifest+blobs+render 版本,gate D1');呈现偏好不立法(§5.3)。
6. **validate-spawn fail-closed**:身份声称的比较锚=继承 artifact 的 prefix_identity;一切漂移源(latch/tools/goal/overrides/kind)拒绝且不落行(事务 RAISE);fresh fork 无身份检查(同身份=缓存命中无害——L4 P1-2)。
7. **probe 纯审计**:零 UPDATE/零重试/零状态变化;估计错翻的是账单归因不翻正确性(ch14.3 逐字);usage 缺失=no-op 非错误。
8. **flip=人审仪式**;auto-flip=§6.7 拒绝项;streak/ready 是查询不是动作。
9. **触点 5 复用面最小**:零新 Jev(STABLE+零 ask 源码扫描+cals 零增量三重执法);superset-on-doubt;核心四不排除(needed 集不变性断言);v1 不武装。
10. **文档顺序=加载顺序**;periphery=第 14 位纯末尾追加;gate 断言对象 ≤14 号;**OR REPLACE 大体从加载态机械复制**(DP6 :153 纪律)——换体源解析规则+增量链完整性断言(gate I)是本 plan 对该纪律的制度化。
11. **V3008 族**(DP1–7=V3001–V3007 序列顺延,已核实 V3008 全库未用):本 plan 全部新 RAISE 显式 USING ERRCODE='V3008';新 DEFINER 面(v13_fork/v13_latch_fire)search_path 钉死+体内受信 schema 限定名+REVOKE PUBLIC。
12. **双登录**:fork/fire/probe/observe/render(工作面)=route 手;intent_gate/streak/render(shadow 分析面)=recall 面(DP2 shadow_reroute 先例);resolve 零新授权;PUBLIC 负向全覆盖。

---

## 2. 输入 § 映射

| 设计原文(冻结) | 本 plan 落点 |
|---|---|
| §5.1 latches(session_id,name,value,fired_at) INSERT once;UPDATE/DELETE 被触发器拒;参与前缀身份哈希 | §3.1 表+触发器;§3.3 换体一 digest;OQ1 材料/追动 |
| §5.1 轮 2 已裁:latch 为 P1 进核心(保护 prefix identity);emergent 表 P2 延后 | 本 plan=第 14 位交付即「进核心」兑现;emergent §7 不做 |
| §5.1 执法修正:跨行数量上限由 admission 函数+事务锁执法(非 CHECK);消费用 target_turn+manifest membership(非破坏性 consumed_at) | OQ8 全节;消费面无生产者不立(§7+§1.4) |
| §5.1 latch 语义:首触发即冻结(模型选择、缓存 scope 资格)——mid-session 漂移即隐性 cache-break,「一次性 DDL」的关系形态 | OQ2(生成模型=首触发冻结的会话级落地)+OQ8;gate C2(mid-session 翻版已 pin 会话身份字节不变) |
| §5.3 render(manifest, render_policy_version, provider)→wire bytes;render 是纯函数,呈现是策略行 | OQ3 函数族三件(wire/receipt/render);render_policy 行=DP7 已立 v1,本 plan 消费 |
| §5.3 首版只留一种 canonical render;provider policy 只处理协议约束与 cache marker;模型呈现偏好在匹配评估证明收益前不进 | OQ3:renderer='canonical' 词表执法(非 canonical→V3008);cache_markers=true=段界标记;protocol_only=协议适配归 driver;偏好不立法(§7) |
| §5.6 fork 继承 context artifact+前缀身份哈希(system blocks+tool schemas+model+latches 的 canonical bytes SHA-256) | OQ1 九键材料(=该 canonical bytes 清单的关系化:provider/model/system_blocks_digest/tools_rev+tools_digest/goal_hash/latch_digest/render_policy_version/manifest_version);OQ4 fork 继承 |
| §5.6 validate-spawn gate 拒绝破坏缓存身份的 fork(如 thinking 预算 clamp 到不同档) | OQ4:overrides+身份声称类 kind→V3008;比较锚=artifact;gate E4/E5(ch14 检查点练习 2 的关系化) |
| §5.6 cache probe=对比实际 cache_read 与携带估计,落审计事件 | OQ5;gate F(差一截→恰一条事件) |
| §5.6 shadow 演出=双跑 assemble,diff 两份 manifest,零 diff N turn 后 flip(manifest 是行=一个查询) | OQ6;gate G(等/不等两向+streak 归零+flip 仪式演练) |
| §6.2 触点 1(P1 shadow-first):semantic_compact_hint 仅同可压缩类内且压力跨 tier 时参与;静态 priority 硬类保留;goal_hash=版本化目标 artifact | **纯消费 DP7**(附 A #9 兑现):hint 生产/记录/硬类/flip 证据门槛全在 DP7 §1.4/economics.compact_hint;本 plan 零 hint 代码;goal_hash 版本化=DP3 v13_goals(DP1 §1.3 #2 已闭环) |
| §6.2 触点 5(P1 条件留,仅复用):只软门控可选且昂贵的外部 source;低置信/CJK/缺失→绑超集,不得排除规则/当前消息/必要历史/工具配对 | OQ7 全节;gate H(含 needed 不变性+零新调执法) |
| §9 表结构增量:latches(session_id,name,value,fired_at) | §3.1 逐字 |
| §9 策略行:render_policy(版本化) | DP7 已立 v1;本 plan 消费+第九材料键+ident_ver 追动(兑现「版本化」的身份面) |
| §10 gate 切片:分解表 DP8 行=validate-spawn/cache probe/shadow flip 断言;G-ctx5 三种回放可区分的 fork 语境复测 | §4 E/F/G 组+I4;G-ctx5 主体归 DP3(D 已落),本 plan 复测 fork 继承语境(E1/E2) |
| §12 YAGNI 台账(emergent/预取/效用遥测/在线 triage/分片哈希等) | §7(台账为源;本 plan 新增台账项:auto-flip/fork turn-runner/intent v2 武装/system blocks 真值/latch 消费者) |
| §13 第 14 章:ForkPrefix 关系化(前缀身份哈希/validate-spawn/cache probe);三种回放语义 | §6 教程映射(ch14 逐节;正文零改动,README 指针) |
| §14 轮 2 裁决 1(latch P1/emergent P2/admission/非破坏性消费) | OQ8 法源 |
| stepfun F9(latch「进核心」与交付排序第 5 步矛盾) | **plan 内消解**(附 A #2):身份保护自 DP3 stub 常量进材料即每 turn 结构性在场(第 6 号文件起);表本体+真值第 14 位落地=交付排序第 5 步的实现位置;两说并存的根因是设计散文未区分「身份钩子在核心」与「表本体交付步」,本 plan 以 stub→真函数换体把两说接通——呈报父 loop 备案 |
| stepfun F13(并发首触发冲突策略未定) | OQ8 立法+gate B3(两连接恰一行、回读同值) |
| ch14 教程(G7 探针门/检查点练习 1–4) | §6 逐条映射(哪些 v1 断言、哪些激活门控) |

---

## 3. 表/函数 DDL 与 SQL 草案

> 文件:`v13/periphery/v13_periphery.sql`(全新增;SQL_LOAD_ORDER 第 14 位纯末尾追加)。**文件内顺序=加载顺序**(§3.1→§3.9 即物理顺序)。整个文件以 BEGIN/COMMIT 包裹(DP2–DP7 形制,含 ALTER/OR REPLACE,单事务原子装载)。草案级完整度:列/约束/签名/关键语句到位,实施者可直接开写;注释标注纪律出处。**实施纪律:§3.7 全部换体的复制源=上游 stage 文件加载态(非计划文本——DP6 :153 原文),逐标注增量编辑;§4 gate I 组断言增量链完整性。**文档内顺序即加载顺序(§3.1→§3.8)。

### 3.1 latches 表+触发器+sessions 增列

```sql
BEGIN;

-- === latches(§5.1/§9 逐字列集;P1 进核心,轮 2 裁决 1) ===
--   INSERT once = PK 结构执法;UPDATE/DELETE/TRUNCATE 触发器拒(TRUNCATE=语句级触发器,L4 P1-4);并发首触发 adopt(OQ8/F13);
--   上限=admission(v13_latch_fire 体内 sessions 锁内计数,非 CHECK——轮 2 执法修正)。
CREATE TABLE latches (
  session_id uuid NOT NULL REFERENCES sessions (session_id),
  name       text NOT NULL,
  value      jsonb NOT NULL,
  fired_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, name),
  CHECK (name ~ '^[a-z][a-z0-9_]{0,62}$')   -- 无 '::'(与 signal 命名空间不撞,DP1 #48 同型)
);

CREATE FUNCTION v13_latches_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'TRUNCATE' THEN
    RAISE EXCEPTION 'v13: latches are INSERT-once (TRUNCATE on %)',
      TG_TABLE_NAME USING ERRCODE = 'V3008';
  END IF;
  RAISE EXCEPTION 'v13: latches are INSERT-once (% on % %/%)',
    TG_OP, TG_TABLE_NAME, OLD.session_id, OLD.name
    USING ERRCODE = 'V3008';
END $$;
CREATE TRIGGER trg_latches_immutable BEFORE UPDATE OR DELETE ON latches
  FOR EACH ROW EXECUTE FUNCTION v13_latches_guard();
--   TRUNCATE 执法(L4 P1-4):行级 UPDATE/DELETE 触发器不触 TRUNCATE——补语句级触发器;
--   guard 体 TRUNCATE 分支不触 OLD(语句级无行),RAISE 形态经 TG_OP 自然成立。
CREATE TRIGGER trg_latches_no_truncate BEFORE TRUNCATE ON latches
  FOR EACH STATEMENT EXECUTE FUNCTION v13_latches_guard();

-- === sessions 第三 fork 列(ch14.4/14.6「在 spawn 行上可区分」;DP1 两列已留缝) ===
--   三列不可变(ch14.5「一次写入永不改」);sessions 其余列 UPDATE 不受触。
ALTER TABLE sessions ADD COLUMN spawn_kind text
  CHECK (spawn_kind IN ('exact_replay','recompute','fresh_fork'));
-- 注:CHECK 随列加(非 DEFERRABLE),NULL=非 fork 会话——词表执法不依赖触发器。

CREATE FUNCTION v13_spawn_cols_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.parent_session_id IS DISTINCT FROM OLD.parent_session_id
     OR NEW.parent_cutoff_seq IS DISTINCT FROM OLD.parent_cutoff_seq
     OR NEW.spawn_kind IS DISTINCT FROM OLD.spawn_kind THEN
    RAISE EXCEPTION 'v13: fork columns are write-once (session %)', OLD.session_id
      USING ERRCODE = 'V3008';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_sessions_fork_cols_immutable
  BEFORE UPDATE OF parent_session_id, parent_cutoff_seq, spawn_kind ON sessions
  FOR EACH ROW EXECUTE FUNCTION v13_spawn_cols_guard();
```

### 3.2 策略行种子(v13_policies 载体;单完整 JSON 字面量+::jsonb——DP2/DP6/DP7 纪律)

```sql
-- === 六行新种+generation v2 翻版(同事务 INSERT+双 UPDATE 翻 active——仪式同款) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
  ('latches', 1, '{
    "max_per_session": 16,
    "note": "admission 上限(OQ8):v13_latch_fire 在 sessions 事务锁内计数,超限 V3008 fail-closed 不静默丢(轮 2 执法修正:非 CHECK)"
  }'::jsonb, true),
  ('cache_probe', 1, '{
    "tolerance_ratio": 0.20, "min_tokens": 1024,
    "note": "容差键:|actual-est| > max(est*tolerance_ratio, min_tokens) 落 audit/cache_probe 事件;纯审计零重试(ch14.3)"
  }'::jsonb, true),
  ('shadow_flip', 1, '{
    "min_zero_diff_turns": 10,
    "note": "连续零 diff 观察数达标才 ready;flip=人审双 UPDATE 仪式(auto-flip=§6.7 拒);校准=翻版"
  }'::jsonb, true),
  ('shadow_watch', 1, '{
    "targets": [],
    "note": "观察名集封闭 {render_policy, assemble_manifest}(词表外 V3008);生产 v1 空表=零观察;gate fixture 临时加目标后回滚"
  }'::jsonb, true),
  ('intent_gate', 1, '{
    "actions_enabled": false,
    "bands_source": "thresholds:intent",
    "note": "触点 5 v1 shadow(OQ7):仅复用 decisions 既有 intent 行+thresholds 带;激活三前提见 DP8 §1.4;low/CJK/missing=superset"
  }'::jsonb, true),
  ('generation', 2, '{
    "provider": "mock", "model": "mock-1",
    "system_blocks": [], "system_blocks_digest": "-none-",
    "note": "DP8 真值接管(OQ2):机制落地(列表+blob 通道+latch 冻结),值仍 mock 与 DP3 骨架逐字衔接;真实 provider/正文=ops 翻 v3(README 仪式);空表 digest=-none-"
  }'::jsonb, false);
UPDATE v13_policies SET active = false WHERE name = 'generation' AND version = 1;
UPDATE v13_policies SET active = true  WHERE name = 'generation' AND version = 2;
-- 翻版⇒gen_ver 追动⇒全域恰一次 refresh(DP3 OQ1 语义,预期内——gate C3 复用此链)
```

### 3.3 identity/token 函数族(换体一/二+新函数)

```sql
-- === 换体一:v13_latch_digest(DP3 §3.3 stub→真函数;空集 '-none-' 逐字衔接) ===
--   fired_at 不进材料(时间戳非内容身份;fork 复制后子会话 digest=父——前缀身份继承的字节基础)。
CREATE OR REPLACE FUNCTION v13_latch_digest(p_sid uuid) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce(encode(digest(
    (SELECT jsonb_agg(jsonb_build_object('name', name, 'value', value) ORDER BY name)
       FROM latches WHERE session_id = p_sid)::text, 'sha256'), 'hex'),
    '-none-')
$$;
-- 墓碑注记:stub 常量体唯一存活于 ≤6 号文件库;真函数全树唯一存活于 ≥14 号文件库
--   (授权换体,DP5 §3.1 L5 同款注记)。

-- === 生成真值单源(OQ2):latch 优先、无 latch 落活动行;返回含 generation_version ===
CREATE FUNCTION v13_generation_effective(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_latch jsonb; v_ver int;
BEGIN
  SELECT value INTO v_latch FROM latches
   WHERE session_id = p_sid AND name = 'generation';
  IF v_latch IS NOT NULL THEN RETURN v_latch; END IF;   -- 会话级冻结(首触发即冻结)
  SELECT version INTO v_ver FROM v13_policies
   WHERE name = 'generation' AND active;
  IF v_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active generation policy (seed lost?)'
      USING ERRCODE = 'V3008';                            -- DP3 同姿势 fail-closed
  END IF;
  RETURN (SELECT jsonb_set(value, '{generation_version}', to_jsonb(v_ver), true)
            FROM v13_policies WHERE name = 'generation' AND active);
END $$;

-- === 换体二:v13_prefix_identity(材料第八键 render_policy_version⇒恒九键;manifest_version 3) ===
--   与 DP3 §3.3 逐字对照的增量:provider/model/system_blocks_digest 改读
--   v13_generation_effective(latch 感知);+render_policy_version 键(缺行 RAISE);
--   manifest_version 2→3。九键全部显式非空检查(去 strip_nulls 纪律逐字继承)。
CREATE OR REPLACE FUNCTION v13_prefix_identity(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_mat jsonb; v_gen jsonb; v_trev int; v_rver int;
BEGIN
  v_gen := v13_generation_effective(p_sid);
  IF v_gen IS NULL OR v_gen->>'provider' IS NULL
     OR v_gen->>'model' IS NULL
     OR v_gen->>'system_blocks_digest' IS NULL THEN
    RAISE EXCEPTION 'v13: no effective generation identity (seed lost?)'
      USING ERRCODE = 'V3008';
  END IF;
  SELECT revision INTO v_trev FROM v13_tools_meta WHERE singleton;
  IF v_trev IS NULL THEN
    RAISE EXCEPTION 'v13: v13_tools_meta singleton row missing'
      USING ERRCODE = 'V3008';                           -- DP3 P1-9 同姿势
  END IF;
  SELECT version INTO v_rver FROM v13_policies
   WHERE name = 'render_policy' AND active;
  IF v_rver IS NULL THEN
    RAISE EXCEPTION 'v13: no active render_policy (seed lost?)'
      USING ERRCODE = 'V3008';
  END IF;
  SELECT jsonb_build_object(
    'provider',  v_gen->>'provider',
    'model',     v_gen->>'model',
    'system_blocks_digest', v_gen->>'system_blocks_digest',
    'tools_rev', v_trev,
    'tools_digest', encode(digest(
      coalesce((v13_canonical_state(p_sid) -> 'tools')::text, ''),
      'sha256'), 'hex'),
    'goal_hash', v13_goal_hash(p_sid),
    'latch_digest', v13_latch_digest(p_sid),
    'render_policy_version', v_rver,
    'manifest_version', 3)
  INTO v_mat;
  RETURN encode(digest(v_mat::text, 'sha256'), 'hex');
END $$;

-- === token 第十一键单源(OQ1):覆盖 latch_digest 与 render_policy_version 两个追动源 ===
CREATE FUNCTION v13_ident_ver(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_ld text; v_rver int;
BEGIN
  v_ld := v13_latch_digest(p_sid);          -- 与 identity 材料同源零复制
  SELECT version INTO v_rver FROM v13_policies
   WHERE name = 'render_policy' AND active;
  IF v_rver IS NULL THEN
    RAISE EXCEPTION 'v13: no active render_policy (seed lost?)'
      USING ERRCODE = 'V3008';
  END IF;
  RETURN encode(digest(jsonb_build_object(
    'latch', v_ld, 'render_policy_version', v_rver)::text, 'sha256'), 'hex');
END $$;

-- === 换体三:v13_context_required(十一键全谱——**DP7 键谱回归修复面,附 A #1**) ===
--   键谱与各键表达式出处(实施纪律:逐键与加载态对照):
--     sem/dec/goal/tools_rev/asm_ver/jdef_ver —— DP3 §3.2 加载态逐字(七键);
--     corpus —— DP4 §3.6 加载态逐字(第八键);
--     recall_ver —— DP5 §3.1 L5 加载态逐字(第九键,缺行 RAISE 同姿势);
--     gen_ver —— 改经 v13_generation_effective( latch 内版本,冻结语义);
--     econ_ver —— DP7 §3.1 v13_econ_ver() 单源调用(零公式复制);
--     ident_ver —— 本文件 v13_ident_ver(第十一键)。
--   全部活动行缺失 RAISE(V3008,与 asm_ver 同姿势);单条 SELECT/单快照纪律保持。
CREATE OR REPLACE FUNCTION v13_context_required(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_asm int; v_jdef int; v_gen int; v_corpus bigint; v_rk int;
        v_econ text; v_tok jsonb;
BEGIN
  SELECT (SELECT version FROM v13_policies WHERE name='assemble_manifest' AND active),
         (SELECT version FROM v13_policies WHERE name='judgment_defaults' AND active),
         (SELECT generation FROM v13_chunks_meta WHERE singleton),
         (SELECT version FROM v13_policies WHERE name='recall_k' AND active)
   INTO v_asm, v_jdef, v_corpus, v_rk;
  v_gen := (v13_generation_effective(p_sid)->>'generation_version')::int;
  v_econ := v13_econ_ver();
  IF v_asm IS NULL OR v_jdef IS NULL OR v_gen IS NULL
     OR v_corpus IS NULL OR v_rk IS NULL OR v_econ IS NULL THEN
    RAISE EXCEPTION 'v13: required_revision inputs missing (policy/meta seed lost?)'
      USING ERRCODE = 'V3008';
  END IF;
  SELECT jsonb_build_object(
    'sem',  (SELECT coalesce(max(seq),0) FROM events
              WHERE session_id = p_sid
                AND type IN ('user/message','llm/message','tool/result')),  -- DP3 族词表
    'dec',  (SELECT count(*) FROM decisions
              WHERE session_id = p_sid AND answer IS NOT NULL),
    'goal', v13_goal_hash(p_sid),
    'tools_rev', (SELECT revision FROM v13_tools_meta WHERE singleton),
    'asm_ver',  v_asm, 'jdef_ver', v_jdef, 'gen_ver', v_gen,
    'corpus',    v_corpus, 'recall_ver', v_rk, 'econ_ver', v_econ,
    'ident_ver', v13_ident_ver(p_sid))
  INTO v_tok;
  RETURN v_tok;
END $$;
-- 注:sem 谓词/dec 谓词实施时逐字对照 DP3 加载态(含部分索引口径);此处草案以语义等价
--   形态书写,gate I1 键集断言+上游 gate 复跑(行为不变性)双保险;草案 coalesce(max(seq),0) 与 DP3 加载态空会话 -1 的口径差即属此对照面,以加载态为准(终检 P2 #3)。
-- 墓碑注记:DP7 十键体(九键基+econ_ver,缺 ident_ver——turn 34 已修 corpus/recall_ver 复制源回归)随 12 号文件落库后,本换体为 +ident_ver 增量替换;
--   十一键全谱全树唯一存活于 ≥14 号文件库。

-- === 换体四:v13_goal_hash 前缀感知(非 fork 会话逐字节等——gate E6) ===
--   链规则:自身 goals 优先(最深),逐代上行取首个非空层该层内 max(seq);
--   无任何 goal=sha256('') hex(DP1/DP3 公式逐字)。
--   锚行选型(L4 P1-1 二选一,取锚行法):锚 cut=本会话 parent_cutoff_seq——非 fork 行
--   cut=NULL,守卫(判被消费行:无 cutoff 即不再上行)自然止于自身,与 ≤13 号公式逐字节等;
--   fork 子 cut=c 逐代上行,链行 cut=该代子链截止(父层 goals ≤ fork cutoff,E6 后半)。
CREATE OR REPLACE FUNCTION v13_goal_hash(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_row record;
BEGIN
  WITH RECURSIVE chain(sid, cut, depth) AS (
    SELECT p_sid,
           (SELECT parent_cutoff_seq FROM sessions WHERE session_id = p_sid),
           0
    UNION ALL
    SELECT s.parent_session_id, s.parent_cutoff_seq, c.depth + 1
      FROM sessions s JOIN chain c ON s.session_id = c.sid
     WHERE c.cut IS NOT NULL          -- 被消费行无 cutoff(非 fork 行)即不再上行;
                                      -- 无环=fork 只建新行的构造不变量(FK 只保证父存在)
  )
  SELECT g.content_hash INTO v_row.content_hash
    FROM v13_goals g
    JOIN chain c ON g.session_id = c.sid
   WHERE (c.sid = p_sid)              -- 自身层无 cutoff 约束
      OR (c.cut IS NOT NULL AND g.seq <= c.cut)
   ORDER BY c.depth ASC, g.seq DESC LIMIT 1;
  RETURN coalesce(v_row.content_hash,
    encode(digest(''::text, 'sha256'), 'hex'));   -- DP1 coalesce 公式逐字
END $$;
-- scope 注:identity 需求的最小例外(OQ4);canonical_state/transcript 零触碰。
```

### 3.4 latch fire+fork+validate-spawn

```sql
-- === v13_latch_fire(OQ8;route 手;DEFINER——sessions 锁内 admission) ===
CREATE FUNCTION v13_latch_fire(p_sid uuid, p_name text, p_value jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pgcrypto AS $$
DECLARE v_existing jsonb; v_cnt int; v_cap int;
BEGIN
  IF p_name = 'generation' THEN
    RAISE EXCEPTION 'v13: latch name ''generation'' is settle-reserved'
      USING ERRCODE = 'V3008';
  END IF;
  IF p_value IS NULL OR jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: latch value must be a jsonb object (%)', p_name
      USING ERRCODE = 'V3008';
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = p_sid FOR UPDATE;  -- admission 事务锁
  SELECT value INTO v_existing FROM latches
   WHERE session_id = p_sid AND name = p_name;
  IF v_existing IS NOT NULL THEN
    RETURN v_existing;               -- F13:首触发已冻结,回读采用(adopt)
  END IF;
  v_cap := (v13_policy('latches')->>'max_per_session')::int;
  SELECT count(*) INTO v_cnt FROM latches WHERE session_id = p_sid;
  IF v_cnt >= v_cap THEN
    RAISE EXCEPTION 'v13: latch cap reached for % (%/%); admission refused',
      p_sid, v_cnt, v_cap USING ERRCODE = 'V3008';   -- fail-closed 不静默丢(轮 2)
  END IF;
  INSERT INTO latches (session_id, name, value)
  VALUES (p_sid, p_name, p_value)
  ON CONFLICT (session_id, name) DO NOTHING;         -- F13:并发首触发
  SELECT value INTO v_existing FROM latches
   WHERE session_id = p_sid AND name = p_name;        -- 回读采用(竞争败者读胜者值)
  RETURN v_existing;
END $$;

-- === v13_fork(OQ4;ch14.7 练习签名+第四可选参;validate-spawn=事务内 RAISE=不落行) ===
CREATE FUNCTION v13_fork(p_parent uuid, p_cutoff bigint, p_kind text,
                         p_overrides jsonb DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pgcrypto AS $$
DECLARE v_parent sessions%ROWTYPE; v_child uuid; v_art uuid; v_man jsonb;
        v_prior uuid; v_child_ident text; v_art_ident text; v_gen jsonb;
BEGIN
  IF (p_kind IN ('exact_replay','recompute','fresh_fork')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: fork kind must be exact_replay|recompute|fresh_fork'
      USING ERRCODE = 'V3008';
  END IF;
  IF p_overrides IS NOT NULL AND p_kind IS DISTINCT FROM 'fresh_fork' THEN
    -- validate-spawn 面 1:身份声称类 spawn 携 overrides=「clamp 却声称复用」(ch14.3)
    RAISE EXCEPTION 'v13: spawn overrides require fresh_fork (kind=%)', p_kind
      USING ERRCODE = 'V3008';
  END IF;
  SELECT * INTO v_parent FROM sessions WHERE session_id = p_parent FOR UPDATE;
  IF v_parent.session_id IS NULL THEN
    RAISE EXCEPTION 'v13: fork parent % not found', p_parent USING ERRCODE = 'V3008';
  END IF;
  IF p_cutoff IS NULL OR p_cutoff < 0 OR p_cutoff >= v_parent.next_seq THEN
    RAISE EXCEPTION 'v13: fork cutoff % out of bounds [0,%]',
      p_cutoff, v_parent.next_seq - 1 USING ERRCODE = 'V3008';
  END IF;

  -- 继承 artifact 链回走:最新 required_revision.sem ≤ cutoff 者(fresh 跳过)
  IF p_kind IS DISTINCT FROM 'fresh_fork' THEN
    v_art := v_parent.context_active_artifact;
    WHILE v_art IS NOT NULL LOOP
      SELECT inline INTO v_man FROM artifacts WHERE artifact_id = v_art;
      IF v_man IS NULL THEN
        RAISE EXCEPTION 'v13: artifact chain broken at %', v_art
          USING ERRCODE = 'V3008';                    -- 数据缺损响亮
      END IF;
      EXIT WHEN (v_man->'required_revision'->>'sem')::bigint <= p_cutoff;
      v_prior := NULLIF(v_man->'replay'->>'prior_artifact_id', '')::uuid;
      v_art := v_prior;
    END LOOP;
    IF v_art IS NULL THEN
      RAISE EXCEPTION 'v13: no context artifact covers cutoff % (align to a settle point)',
        p_cutoff USING ERRCODE = 'V3008';
    END IF;
    v_art_ident := v_man->>'prefix_identity';         -- 声称锚=artifact 冻结身份
  END IF;

  -- 子行(parent 两列+spawn_kind+route_policy 继承)
  INSERT INTO sessions (status, route_policy_name, route_policy_version,
                        parent_session_id, parent_cutoff_seq, spawn_kind)
  VALUES (v_parent.status, v_parent.route_policy_name, v_parent.route_policy_version,
          p_parent, p_cutoff, p_kind)
  RETURNING session_id INTO v_child;

  -- latch 复制(非 fresh 全量;fresh 零复制+overrides 落自己的 generation latch)
  IF p_kind IS DISTINCT FROM 'fresh_fork' THEN
    INSERT INTO latches (session_id, name, value, fired_at)
    SELECT v_child, name, value, fired_at
      FROM latches WHERE session_id = p_parent;
  ELSE
    v_gen := v13_generation_effective(p_parent);      -- 父此刻的生效值作基底
    IF p_overrides IS NOT NULL THEN
      IF jsonb_typeof(p_overrides) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'v13: overrides must be an object' USING ERRCODE = 'V3008';
      END IF;
      v_gen := v_gen || p_overrides;                  -- clamp/换档的关系化形态(进身份值)
    END IF;
    INSERT INTO latches (session_id, name, value)
    VALUES (v_child, 'generation', v_gen);
  END IF;

  -- validate-spawn 面 2:身份声称类——子此刻身份 vs artifact 冻结身份
  v_child_ident := v13_prefix_identity(v_child);
  IF p_kind IS DISTINCT FROM 'fresh_fork' THEN
    IF v_child_ident IS DISTINCT FROM v_art_ident THEN
      RAISE EXCEPTION
        'v13: validate-spawn rejected: identity drift for % fork (child=%, artifact=%)',
        p_kind, v_child_ident, v_art_ident USING ERRCODE = 'V3008';
    END IF;
  END IF;
  -- (L4 P1-2:fresh 分支无身份检查——fresh 必携 generation latch(fork SQL 无条件落);
  --   无 overrides 且 cutoff 对齐 settle 点时子身份可与父 artifact 身份相等,
  --   同身份=同前缀缓存命中,无害;设计只要求拒「破坏缓存身份的 fork」。)

  -- 继承指针+forked 事件(payload=身份对账的行级审计面)
  IF p_kind IS DISTINCT FROM 'fresh_fork' THEN
    UPDATE sessions
       SET context_active_artifact = v_art,
           context_active_revision = v_man->'required_revision'
     WHERE session_id = v_child;
  END IF;
  PERFORM v13_append_event(v_child, gen_random_uuid(), 'forked',
    jsonb_build_object('kind', p_kind, 'parent_session_id', p_parent,
      'cutoff', p_cutoff, 'artifact_id', v_art,
      'parent_identity', v_art_ident, 'child_identity', v_child_ident,
      'overrides', p_overrides), NULL);
  RETURN v_child;
END $$;
-- 注(草案级 belt 收口):fresh 分支的 generation_version belt 以显式 RAISE 形态最终化
--   (实施期机械自检#3:IF NOT (v_gen ? 'generation_version') THEN RAISE)。
```

### 3.5 render 函数族+cache probe

```sql
-- === v13_render_wire(OQ3:纯函数;sections 通用渲染,chunk sections 落地日零改) ===
CREATE FUNCTION v13_render_wire(p_sid uuid, p_manifest jsonb,
                                p_render_ver int DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_pol jsonb; v_gen jsonb; v_blocks jsonb := '[]'::jsonb;
        v_tools jsonb; v_secs jsonb;
BEGIN
  IF p_render_ver IS NULL THEN
    v_pol := v13_policy('render_policy');
  ELSE
    SELECT value INTO v_pol FROM v13_policies
     WHERE name = 'render_policy' AND version = p_render_ver;
  END IF;
  IF v_pol IS NULL OR v_pol->>'renderer' IS DISTINCT FROM 'canonical' THEN
    RAISE EXCEPTION 'v13: unknown renderer (V3008)' USING ERRCODE = 'V3008';
  END IF;
  v_gen := v13_generation_effective(p_sid);
  IF jsonb_typeof(v_gen->'system_blocks') IS DISTINCT FROM 'null' THEN
    SELECT coalesce(jsonb_agg(b.inline #>> '{}' ORDER BY o.ord), '[]'::jsonb)
      INTO v_blocks
      FROM jsonb_array_elements(v_gen->'system_blocks') WITH ORDINALITY o(h, ord)
      LEFT JOIN artifacts b
        ON b.content_hash = o.h->>'content_hash' AND b.kind = 'system_block';
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_gen->'system_blocks') o(h)
               LEFT JOIN artifacts b ON b.content_hash = o.h->>'content_hash'
                                     AND b.kind = 'system_block'
               WHERE b.content_hash IS NULL) THEN
      RAISE EXCEPTION 'v13: system block blob missing for %', p_sid
        USING ERRCODE = 'V3008';                       -- fail-closed:正文缺失不静默
    END IF;
  END IF;
  v_tools := coalesce(v13_canonical_state(p_sid) -> 'tools', '[]'::jsonb);
  -- tools 与 tools_digest 同源同材料(identity 面零第二实现,gate D3)
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'id',     s->>'section_id',
           'marker', '[v13-section:' || s->>'section_id' ||
                      ':cache_scope=' || s->>'cache_scope' || ']',  -- cache_markers:true
           'body',   CASE s->'payload_ref'->>'kind'
                       WHEN 'blob' THEN
                         (SELECT b.inline #>> '{}' FROM artifacts b
                           WHERE b.content_hash = s->'payload_ref'->>'content_hash'
                             AND b.kind = 'context_section')
                       WHEN 'goal' THEN
                         (SELECT g.payload::text FROM v13_goals g
                           WHERE g.session_id = p_sid
                             AND g.seq = (s->'payload_ref'->>'seq')::bigint)
                     END)
           ORDER BY s->>'section_id'), '[]'::jsonb)
    INTO v_secs
    FROM jsonb_array_elements(p_manifest->'sections') s;
  -- 注:sections 数组本身已按 (prank, section_id) 全序落库(DP3/DP7 装配序);渲染序=数组序,
  --   ORDER BY section_id 仅作聚合稳定性 belt——实施期改为按数组原序遍历(plpgsql 循环),
  --   保守等价,避免 jsonb_agg 对输入序的隐式依赖(记入机械自检)。
  RETURN jsonb_build_object('system', v_blocks, 'tools', v_tools,
                            'sections', v_secs);
END $$;

-- === v13_render_receipt(OQ5 携带估计的冻结点;est 公式=DP3 逐字整数算术) ===
CREATE FUNCTION v13_render_receipt(p_sid uuid, p_manifest jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_wire jsonb; v_div int; v_stable_bytes bigint := 0; s jsonb;
BEGIN
  v_wire := v13_render_wire(p_sid, p_manifest);
  v_div := (v13_policy('assemble_manifest')->>'est_bytes_per_token')::int;
  v_stable_bytes := v_stable_bytes
    + coalesce(octet_length((v_wire->'system')::text), 0)
    + coalesce(octet_length((v_wire->'tools')::text), 0);
  FOR s IN SELECT * FROM jsonb_array_elements(p_manifest->'sections') LOOP
    IF (s->>'churn')::int = 0 THEN
      v_stable_bytes := v_stable_bytes +
        octet_length(coalesce((SELECT jsonb_build_object(
          'id', s->>'section_id',
          'body', v13_render_section_body(p_sid, s))::text), ''));
    END IF;
  END LOOP;
  RETURN jsonb_build_object(
    'renderer', 'canonical',
    'render_policy_version',
      (SELECT version FROM v13_policies WHERE name='render_policy' AND active),
    'wire_digest', encode(digest(v_wire::text, 'sha256'), 'hex'),
    'stable_prefix_est_tokens',
      ((v_stable_bytes + v_div - 1) / v_div)::int);   -- DP3 est 公式逐字
END $$;
-- 注:v13_render_section_body 为 render_wire 的段体单源抽取(wire 与 receipt 共用,
--   零第二实现——实施期把 wire 的 CASE 体抽为该函数,本草案以共用注记表达)。

-- === v13_render(worker 面;钉版本=shadow 面) ===
CREATE FUNCTION v13_render(p_sid uuid, p_render_ver int DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_man jsonb;
BEGIN
  SELECT a.inline INTO v_man FROM artifacts a
   WHERE a.artifact_id = (SELECT context_active_artifact
                             FROM sessions WHERE session_id = p_sid);
  IF v_man IS NULL THEN
    RAISE EXCEPTION 'v13: no active context artifact for %', p_sid
      USING ERRCODE = 'V3008';
  END IF;
  RETURN v13_render_wire(p_sid, v_man, p_render_ver);
END $$;

-- === v13_cache_probe(OQ5;route 手;纯审计零状态变化——gate F6) ===
CREATE FUNCTION v13_cache_probe(p_effect uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_kind text; v_status text; v_result jsonb; v_man jsonb;
        v_est int; v_actual bigint; v_tol numeric; v_min int;
BEGIN
  SELECT kind, status, result INTO v_kind, v_status, v_result
    FROM effects WHERE effect_id = p_effect;
  IF v_kind IS DISTINCT FROM 'llm' OR v_status IS DISTINCT FROM 'succeeded'
    THEN RETURN NULL; END IF;                         -- no-op:非目标形态
  SELECT a.inline INTO v_man FROM artifacts a
   WHERE a.artifact_id = (v_result->>'context_artifact_id')::uuid;
  IF v_man IS NULL OR v_man->'render' IS NULL THEN
    RETURN NULL;   -- 无 provenance/无 render 面:无对账面(README worker 契约记)
  END IF;
  IF v_result->>'wire_digest' IS NOT NULL
     AND v_result->>'wire_digest' IS DISTINCT FROM
         v_man->'render'->>'wire_digest' THEN
    PERFORM v13_append_event(
      (SELECT session_id FROM effects WHERE effect_id = p_effect),
      gen_random_uuid(), 'audit/cache_probe',
      jsonb_build_object('basis', 'wire_mismatch', 'effect_id', p_effect,
        'expected', v_man->'render'->>'wire_digest',
        'actual', v_result->>'wire_digest'));
  END IF;
  v_actual := NULLIF(v_result->'usage'->>'cache_read_input_tokens', '')::bigint;
  IF v_actual IS NOT NULL THEN
    v_est := (v_man->'render'->>'stable_prefix_est_tokens')::int;
    v_tol := (v13_policy('cache_probe')->>'tolerance_ratio')::numeric;
    v_min := (v13_policy('cache_probe')->>'min_tokens')::int;
    IF abs(v_actual::numeric - v_est) > greatest(v_est * v_tol, v_min) THEN
      PERFORM v13_append_event(
        (SELECT session_id FROM effects WHERE effect_id = p_effect),
        gen_random_uuid(), 'audit/cache_probe',
        jsonb_build_object('basis', 'estimate_gap', 'effect_id', p_effect,
          'expected_tokens', v_est, 'actual_tokens', v_actual));
      RETURN jsonb_build_object('probed', true, 'event', true);
    END IF;
  END IF;
  RETURN jsonb_build_object('probed', true, 'event', false);
END $$;
-- 注:两次 v13_append_event 的 sid 子查询改一次性 DECLARE 抽取(实施期机械自检#1:
--   参数全用/重复读消除);usage 缺键=no-op 零事件(「缺失=无对账面,不是错样本」)。
```

### 3.6 shadow 仪器+触点 5 判定函数

```sql
-- === v13_shadow_observe(OQ6;settle 尾调用;词表封闭 fail-closed) ===
CREATE FUNCTION v13_shadow_observe(p_sid uuid) RETURNS void
LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_targets jsonb; v_name text; v_active int; v_shadow int;
        v_man jsonb; v_eq boolean;
BEGIN
  v_targets := v13_policy('shadow_watch')->'targets';
  IF v_targets IS NULL THEN RETURN; END IF;
  FOR v_name IN SELECT jsonb_array_elements_text(v_targets) LOOP
    IF (v_name IN ('render_policy','assemble_manifest')) IS NOT TRUE THEN
      RAISE EXCEPTION 'v13: shadow watch name % outside v1 vocabulary', v_name
        USING ERRCODE = 'V3008';
    END IF;
    SELECT version INTO v_active FROM v13_policies
     WHERE name = v_name AND active;
    SELECT max(version) INTO v_shadow FROM v13_policies
     WHERE name = v_name AND NOT active;
    IF v_shadow IS NULL OR v_shadow <= v_active THEN CONTINUE; END IF;
    SELECT a.inline INTO v_man FROM artifacts a
     WHERE a.artifact_id = (SELECT context_active_artifact
                              FROM sessions WHERE session_id = p_sid);
    IF v_man IS NULL THEN CONTINUE; END IF;
    IF v_name = 'render_policy' THEN
      v_eq := encode(digest(v13_render_wire(p_sid, v_man)::text,'sha256'),'hex')
           = encode(digest(v13_render_wire(p_sid, v_man, v_shadow)::text,'sha256'),'hex');
    ELSE  -- assemble_manifest:内容投影等(剔 policy/required_revision/economics——版本自身永不相等)
      v_eq := v13_shadow_projection(v13_assemble_manifest(p_sid))
           = v13_shadow_projection(v13_assemble_manifest(p_sid, v_shadow));
    END IF;
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'audit/shadow_obs',
      jsonb_build_object('name', v_name, 'active_version', v_active,
        'shadow_version', v_shadow, 'content_equal', v_eq));
  END LOOP;
END $$;

-- 内容投影单源(sections+candidates+judgments;两分支同函数零漂移)
CREATE FUNCTION v13_shadow_projection(p_manifest jsonb) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object('sections', p_manifest->'sections',
           'candidates', p_manifest->'query_side'->'candidates',
           'judgments', p_manifest->'judgments')
$$;

-- === v13_shadow_streak(就绪查询;「manifest 是行=一个查询」) ===
CREATE FUNCTION v13_shadow_streak(p_name text, p_version int) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  WITH obs AS (
    SELECT (payload->>'content_equal')::boolean AS eq, created_at
      FROM events
     WHERE type = 'audit/shadow_obs'
       AND payload->>'name' = p_name
       AND (payload->>'shadow_version')::int = p_version
     ORDER BY created_at DESC
     LIMIT (v13_policy('shadow_flip')->>'min_zero_diff_turns')::int)
  SELECT jsonb_build_object('streak', count(*) FILTER (WHERE eq),
           'observations', count(*),
           'ready', count(*) >=
             (v13_policy('shadow_flip')->>'min_zero_diff_turns')::int
             AND bool_and(eq))
    FROM obs
$$;

-- === v13_intent_gate(OQ7;STABLE 纯读=零新 Jev 的结构性执法半边) ===
CREATE FUNCTION v13_intent_gate(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_answer jsonb; v_conf numeric; v_hit boolean; v_cjk boolean;
        v_mode text; v_basis text;
BEGIN
  SELECT answer INTO v_answer FROM decisions
   WHERE session_id = p_sid AND signal = 'intent'
     AND answer IS NOT NULL AND status IN ('answered','cached')
   ORDER BY created_at DESC LIMIT 1;               -- 仅复用既有 intent 行(触点 5 前提)
  IF v_answer IS NULL THEN
    v_mode := 'superset'; v_basis := 'missing';
  ELSE
    v_conf := NULLIF(v_answer->>'confidence','')::numeric;
    SELECT EXISTS(
      SELECT 1 FROM thresholds t JOIN sessions s ON s.session_id = p_sid
       WHERE t.route_policy_name = s.route_policy_name
         AND t.route_policy_version = s.route_policy_version
         AND t.signal = 'intent' AND t.action = 'pass'
         AND v_conf >= t.lo AND v_conf < t.hi) INTO v_hit;
    -- 带读侧=thresholds 表(与 route 同一真相源;列名/锚定实施时对齐 DP1 §3.3 加载态)
    v_cjk := EXISTS(SELECT 1 FROM v13_query_segments(
                 coalesce((SELECT g.payload->>'text' FROM v13_goals g
                            WHERE g.session_id = p_sid
                            ORDER BY g.seq DESC LIMIT 1), '')) seg
                 WHERE seg->>'class' = 'cjk');
    -- CJK 判定复用 DP5 分段器(零第二分词;返回形状实施时对齐 DP5 §3.1)
    IF v_cjk THEN       v_mode := 'superset'; v_basis := 'cjk';
    ELSIF v_hit IS NOT TRUE THEN
                        v_mode := 'superset'; v_basis := 'low_confidence';
    ELSE                v_mode := 'narrow_eligible'; v_basis := 'confident';
    END IF;
  END IF;
  RETURN jsonb_build_object('mode', v_mode, 'basis', v_basis,
    'actions_enabled',
      (v13_policy('intent_gate')->>'actions_enabled')::boolean);
END $$;
-- v1 actions_enabled=false:mode 是记录不是动作(零绑定效果);激活契约见 §1.4。
```

### 3.7 换体五至八:assemble/validate/refresh/blob_land 增量链

> **复制源解析规则(本 plan 制度化,消费清单 #22)**:每个换体的复制源=**该对象在加载序中的最新形态**(=实施后磁盘上 1–13 号 SQL 文件的最终态),非任何计划文本。逐对象链:
>
> | 对象 | 换体链(→为 OR REPLACE) | 14 号复制源 |
> |---|---|---|
> | v13_assemble_manifest | DP3→DP5→DP6→DP7(12 号 v2)→DP7(13 号 v3) | 13 号加载态 |
> | v13_manifest_validate | 同上链(词表两跳:v2/v3) | 13 号加载态 |
> | v13_refresh_context | DP3→DP7(12 号锁集/守卫扩) | 12 号加载态 |
> | v13_blob_land | DP3→(DP7 消费未改) | DP3/6 号加载态 |
> | v13_prefix_identity / v13_context_required / v13_goal_hash / v13_latch_digest | 见 §3.3 | §3.3 已全文重写(修复性) |

```sql
-- === 换体五:v13_assemble_manifest v4(机械复制 13 号加载态+以下增量,其余逐字不动) ===
-- (a) manifest_version 2→3;外层追加 'render' 键 = v13_render_receipt(p_sid, <装配中 manifest>)
--     ——在 sections 定稿/预算装箱之后求值(单语句单快照纪律:receipt 为 STABLE 调用,
--        与装配同语句快照);receipt 内含 est/除数读取(装配策略行,同源)。
-- (b) required_revision 表达式改调 v13_context_required(p_sid) 单源
--     ——替换内联重算(哈希同源教训:token 双写面归一;语句快照语义不变,STABLE 同快照)。
-- (c) prefix_identity 调用零改(换体二自动生效,九键材料)。
-- (d) est 公式/装箱/economics/summary 消费面零改(DP3/DP7 逐字继承)。

-- === 换体六:v13_manifest_validate v4(机械复制 13 号加载态+以下增量) ===
-- (a) 外层键集串改 12 键字典序:
--     'economics,judgments,manifest_version,policy,prefix_identity,query_side,
--      render,replay,required_revision,sections,session_id,turn_no'
-- (b) manifest_version 断言 IS DISTINCT FROM 3 拒收(v2 产物只在 ≤13 号库;exempt
--     replay 不走 validate——DP7 OQ7 语义继承)。
-- (c) 新增 render 块层(4 键恰等):{renderer(词表{'canonical'}),
--     render_policy_version(int≥1),wire_digest(64hex),stable_prefix_est_tokens(int≥0)};
--     null 枚举穿透封死(IN ... IS NOT TRUE / IS DISTINCT FROM——DP3 层纪律逐字)。
-- (d) required_revision 层键集串改十一键字典序:
--     'asm_ver,corpus,dec,econ_ver,gen_ver,goal,ident_ver,jdef_ver,recall_ver,sem,
--      tools_rev'

-- === 换体七:v13_refresh_context(机械复制 12 号加载态+以下增量;顺序骨架逐字保留) ===
-- (a) 策略形状守卫扩(装配前 RAISE V3008,fail-loud):
--     · generation v2 形状:provider/model 非空串;system_blocks 为 64hex 数组;
--       system_blocks_digest∈64hex∪{'-none-'},且与 blob 实算 digest 相等
--       (读 artifacts kind='system_block' 重算——settle 锁内读,append-only 一致);
--     · render_policy 形状:renderer='canonical'/'cache_markers' boolean/
--       provider_policy='protocol_only'(词表执法);
--     · latches/cache_probe/shadow_flip/shadow_watch/intent_gate 形状(非装配输入族,
--       同点 fail-loud 检查——DP7 (b)「守卫面=装配输入+配置错误前置」同款)。
-- (b) 装配前 'generation' latch 内联首发(fire-or-adopt):
--     INSERT INTO latches(session_id,name,value)
--       SELECT p_sid,'generation',jsonb_set(value,'{generation_version}',
--         to_jsonb(version),true) FROM v13_policies
--        WHERE name='generation' AND active
--        ON CONFLICT (session_id,name) DO NOTHING;
--     (settle 已持 sessions 行锁=admission 锁;adopt 语义=已有 latch 时零动作;)
--     (随后 v13_generation_effective 读到 latch——首次装配即首触发冻结,OQ2 时点语义。)
-- (c) 锁集第四层策略活动行 name 集扩为六名:
--     ('assemble_manifest','context_budget','context_tiers','generation',
--      'judgment_defaults','render_policy') ORDER BY name FOR UPDATE
--     (render_policy 进装配输入(identity 材料)——其翻版必须与 settle 串行化,
--      DP7 五名集的同缝扩展;全库锁序不变量零新增层级)。
-- (d) 尾部(settle 提交路径内、指针写之后):PERFORM v13_shadow_observe(p_sid);
--     (观察事件与 settle 同事务——events append-only,无锁序新增面。)

-- === 换体八:v13_blob_land(机械复制 6 号加载态;唯一增量=kind 词表 +'system_block') ===
--   语义:system blocks 正文=内容寻址 blob(owner 落地,双 lander 零运行角色纪律不动);
--   自证 CHECK(inline hash/size)随 lander 原样适用于新 kind。
```

### 3.8 ACL 块(文件真末尾;DP1 双登录纪律)

```sql
REVOKE ALL ON TABLE latches FROM PUBLIC;
GRANT SELECT ON TABLE latches TO v13_route;   -- INSERT/UPDATE/DELETE 零授权:
                                              -- 唯一写路径=DEFINER(v13_latch_fire/fork/settle 内联)
REVOKE ALL ON FUNCTION
  v13_latches_guard(), v13_spawn_cols_guard(),
  v13_latch_digest(uuid), v13_generation_effective(uuid),
  v13_prefix_identity(uuid), v13_ident_ver(uuid),
  v13_context_required(uuid), v13_goal_hash(uuid),
  v13_render_wire(uuid,jsonb,int), v13_render_receipt(uuid,jsonb),
  v13_render(uuid,int), v13_cache_probe(uuid),
  v13_shadow_observe(uuid), v13_shadow_projection(jsonb),
  v13_shadow_streak(text,int), v13_intent_gate(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_latch_fire(uuid,text,jsonb), v13_fork(uuid,bigint,text,jsonb),
  v13_cache_probe(uuid), v13_shadow_observe(uuid),
  v13_render(uuid,int), v13_render_wire(uuid,jsonb,int),
  v13_render_receipt(uuid,jsonb),
  v13_generation_effective(uuid), v13_latch_digest(uuid)
TO v13_route;      -- 工作/写入面:settle·worker·fork·fire 全在 route 手
GRANT EXECUTE ON FUNCTION
  v13_intent_gate(uuid), v13_shadow_streak(text,int),
  v13_render(uuid,int)
TO v13_recall;     -- 分析/审计面(DP2 shadow_reroute 先例);resolve 零新授权
COMMIT;
-- 注:换体一至八(OR REPLACE)的 ACL 保留断言随 gate A6;DEFINER 面(fork/fire)
-- search_path 已钉死+体内受信 schema 限定名(public.)双层。
```

---

## 4. 里程碑与 gate

单里程碑单 stage:命令形态 `uv run python v13/periphery/test_periphery.py`,退出码 0=通过。**提交前 DP1–DP7 全部十三个 stage gate 在各自前缀库复跑**(AGENTS.md 义务;上游库不加载 14 号文件,结构性零影响——gate I5 互证)。

**断言纪律(DP1–7 原样沿用)**:fixture 走真实链路——事件经 v13_append_event、parse/advance 经 DP1 真实函数、manifest 经 refresh settle 真实链路、effect 经 claim/complete 真实结算;策略翻版经 INSERT+双 UPDATE 仪式(测毕回滚);源码扫描用 DP5 §4 归一化口径(剥 `--` 行注释与 `/* */` 块注释)。

**gate 断言对象 ≤14 号文件**;涉及 DP7 对象(economics 块/render_policy 行)时只读消费不断言其内部。

### 4.1 gate 组(A–I 九组,56 断言:A6+B5+C6+D7+E8+F6+G6+H7+I5)

#### A 组 · 加载/形状/ACL/源码扫描

| # | 断言 | 对应 |
|---|---|---|
| A1 | 加载:十四文件前缀库装载退出 0;六行新策略各 v1 active=true+generation v2 active(v1 留档不可改);sessions.spawn_kind 列在场(开放词表三值);jsonb 单字面量+::jsonb(归一化扫描零 text||text 进 jsonb 列) | OQ9/种子纪律 |
| A2 | 翻版仪式:generation v2→v3(mock 同值)演练→双 UPDATE 翻→v13_policies_frozen 拒改 value;测毕双回滚 | 消费清单 #21 |
| A3 | latch 触发器:UPDATE/DELETE 任一行→V3008;TRUNCATE 拒(trg_latches_no_truncate 语句级触发器→V3008——行级触发器不触 TRUNCATE,L4 P1-4) | OQ8 |
| A4 | spawn 列不可变:UPDATE parent_cutoff_seq/spawn_kind→V3008;非 fork 列(status/turn_no)UPDATE 不受触 | ch14.5 |
| A5 | 源码扫描(归一化):14 号文件零 `==>`、零 `stannum.` 限定、零 `typesafe_ask`(承重件不依赖/零新 Jev 面三重);全部新 RAISE 显式 USING ERRCODE='V3008'(计数恰等) | 不变量 11 |
| A6 | ACL:SET ROLE v13_route→fire/fork/probe/observe/render EXECUTE ok+SELECT latches ok;v13_recall→intent_gate/streak/render ok+INSERT latches 拒;resolve→新函数全拒;PUBLIC 未 SET ROLE 直调全拒;OR REPLACE 八件 ACL 保留 | 不变量 12 |

#### B 组 · latch 族(§5.1/OQ8/F13)

| # | 断言 | 对应 |
|---|---|---|
| B1 | INSERT once:同 (sid,name) 第二次直插→PK 冲突;v13_latch_fire 重复调→回读采用现有值(返回值与首行等) | §5.1 |
| B2 | 并发首触发(F13):两连接同时对同 (sid,name) fire→恰一行、两连接回读同值(ON CONFLICT DO NOTHING+回读);连接 B 不抛错 | F13 逐字 |
| B3 | admission 上限:第 17 枚 fire→V3008 fail-closed(非静默丢);16 枚内全成 | 轮 2 执法修正 |
| B4 | 保留名:public v13_latch_fire(name='generation')→V3008;settle 内联首发合法 | OQ8 |
| B5 | digest:同 latch 集两调字节等;fired_at 变化(直改 owner fixture)不改 digest(时间戳非材料);空集='-none-'(与 DP3 stub 逐字——前缀库衔接断言) | OQ8 |

#### C 组 · generation 真值/identity/token(OQ1/OQ2)

| # | 断言 | 对应 |
|---|---|---|
| C1 | 首 settle 自动首发:装配后 latches 含 name='generation'(值=活动行快照含 generation_version);同一会话二次 settle 零新行(adopt) | OQ2 |
| C2 | mid-session 翻版安全绳:已 pin 会话(已 settle)→generation 翻 v3(异 provider)→该会话 v13_prefix_identity 字节不变+v13_context_fresh 仍 true(gen_ver=latch 内版本恒定,零 refresh 风暴);新会话首 settle 取 v3 | OQ2/ch14.5 |
| C3 | 未 pin 会话翻版追动:未装配会话→翻 v3→② 检出不新鲜→refresh(键集/generation_version 链路) | OQ1 |
| C4 | render_policy 翻版追动:翻 v2(同值)→identity 变(材料第九键)+token ident_ver 变→refresh 一次;测毕回滚 | DP7 §1.4 兑现 |
| C5 | latch 追动:已 settle 会话 fire 新 latch→ident_ver 变→② 检出→refresh;identity 同步变(latch_digest 材料) | OQ1 |
| C6 | prefix_identity 九键材料(jsonb 结构断言:逐键在场与类型);负向:毁活动 generation/render_policy 行→RAISE V3008(测毕还原) | OQ1/DP3 同姿势 |

#### D 组 · render(OQ3)

| # | 断言 | 对应 |
|---|---|---|
| D1 | 纯函数确定性:同 sid 三连调 v13_render 字节等;wire 重现:v13_render_wire(sid, artifact.inline) 与 settle 时 receipt 的 wire_digest 恒等(不落库纪律的可重现而) | OQ3 |
| D2 | wire 结构:{system,tools,sections} 键集恰等;sections 每段 {id,marker,body} 三键;marker 含 section_id+cache_scope(cache_markers:true) | OQ3 |
| D3 | tools 同源:render.tools 序列化字节=identity 材料 tools_digest 的输入字节(同 canonical_state 投影——单源断言) | OQ3/哈希同源 |
| D4 | system blocks 通道:owner 经 v13_blob_land('system_block') 落两块→generation v3(列表+digest 实算)翻版→render.system 两块按序;settle 守卫:tamper blob 内容→digest 校验 RAISE;列表指向缺失 blob→render RAISE(fail-closed);测毕回滚 v2 | OQ2/OQ3 |
| D5 | render 块进 manifest v3:外层 12 键;render 4 键(wire_digest 64hex/est≥0);est 与 est 公式一致(手工对照同除数) | 换体五/六 |
| D6 | 空表衔接:system_blocks=[] 的会话 digest='-none-'(与 DP3 骨架逐字——identity 空会话可比性) | OQ2 |
| D7 | 钉版本:render_policy v2(改 marker 形态)→v13_render(sid,2) wire_digest≠v1——shadow 双跑的可差异面 | OQ6 前置 |

#### E 组 · fork/validate-spawn/ch14 映射(OQ4)

| # | 断言 | 对应 |
|---|---|---|
| E1 | exact_replay@settle 点:父 settle 后取其 artifact.required_revision.sem=cutoff→fork→子继承指针;v13_replay(子 artifact).inline 与父 artifact.inline **逐字节等**(ch14.6「与父逐字节相同」);forked 事件在场(payload 含身份对) | §5.6/ch14 |
| E2 | 三种 spawn 可区分:同 cutoff 三 kind 三子行——spawn_kind 互异+forked payload kind 互异+exact/recompute 继承指针 vs fresh 无指针;recompute 与 exact 的差异面=spawn_kind 声明(v1 壳语义,README 注记) | ch14.4 不得混称 |
| E3 | 越界/无覆盖:cutoff=next_seq→V3008 零行;cutoff 早于首 settle 且 kind=exact_replay→V3008 零行(无覆盖 artifact) | OQ4 |
| E4 | 身份漂移拒绝四负向:①父 freeze 后 fire 新 latch→fork exact→V3008;②tools 目录 bump(bump 面 fixture)→fork exact→V3008;③overrides+exact_replay→V3008;④cutoff 落在覆盖 artifact 后的 user/message 之后(同批 settle 前)→V3008(goal 漂移);全部零子行 | validate-spawn/ch14.3 |
| E5 | fresh fork:overrides={"model":"mock-9","thinking_budget":"high"}→过;overrides 进 forked 事件+进子 generation latch 值(关系化 clamp);身份记录面=forked payload 的 child_identity 在场;无 overrides 的 fresh 也过,注记断言:无 overrides+cutoff 对齐 settle 点时子身份可与父 artifact 身份相等(同身份=缓存命中,合法——L4 P1-2) | ch14.7 练习2 |
| E6 | goal_hash 前缀感知回归:非 fork 会话与 ≤13 号库公式逐字节等(同 fixture 双库对照);fork 子(无 own goal)=父@cutoff 的 goal | 换体四 |
| E7 | 冻结隔离:fork 后父追加事件+父 fire 新 latch→子 identity/子 latch 集不变(ch14.7 练习4 改写形态——latch 本体不可改,漂移源=父后续 fire) | ch14.5 |
| E8 | O(1) 结构:源码断言 v13_fork 体零 `FROM events`(除 append 调用)——fork 成本与父事件量无关的除事件结构证明 | ch14.6 |

#### F 组 · cache probe(OQ5)

| # | 断言 | 对应 |
|---|---|---|
| F1 | 差额:complete llm effect(result 携 context_artifact_id+usage.cache_read_input_tokens=0)→v13_cache_probe→恰一条 audit/cache_probe 事件 basis=estimate_gap(expected/actual 在场) | §5.6 |
| F2 | 干净:|actual-est|≤容差→零事件返回 {probed:true,event:false} | OQ5 |
| F3 | usage 缺键→no-op 零事件零异常;非 llm/非 succeeded→no-op | OQ5 |
| F4 | wire 完整性:result.wire_digest 伪造≠render.wire_digest→basis=wire_mismatch 事件(与 estimate_gap 可叠加恰两条) | OQ5 |
| F5 | 纯审计:probe 前后 sessions/effects/artifacts 零变化(行级对照)——「估计错不翻正确性」的结构性断言 | ch14.3 |
| F6 | 对账锚竞态免疫:complete 后手动 refresh 换指针→probe 仍读 artifact 内 render 块(经 result 锚非 sessions 当前指针) | OQ5 |

#### G 组 · shadow 仪器(OQ6)

| # | 断言 | 对应 |
|---|---|---|
| G1 | 生产形态:shadow_watch targets=[]→settle 零观察事件 | OQ6 |
| G2 | render 族双跑:fixture 置 targets=['render_policy']+v2(同输出变体)→settle→audit/shadow_obs content_equal=true;v2 改 marker 形态→false;测毕回滚 | §5.6 |
| G3 | assemble 族双跑:assemble_manifest v2(同值 fixture)→content_equal=true(内容投影剔版本自异);差异 fixture→false | §5.6 |
| G4 | 词表:targets=['context_tiers']→V3008(带外 fail-closed;tier flip 证据面归 DP7 校准流程——附 A #9 消费侧) | OQ6 |
| G5 | streak:连造 10 条 equal 观察→ready=true;插入一条 false→归零(最近窗布尔聚合);回滚 fixture | OQ6 |
| G6 | flip 仪式:render_policy 真翻 v2→identity/token 追动链复测(C4 同链复跑)→测毕回滚;auto-flip 不存在(源码扫描零策略 UPDATE in streak/observe) | 不变量 8 |

#### H 组 · 触点 5(OQ7)

| # | 断言 | 对应 |
|---|---|---|
| H1 | 缺失:无 intent 行→{mode:superset,basis:missing} | §6.2 触点5 |
| H2 | 低置信:conf<0.75(fixture)→superset/low_confidence | §6.2 |
| H3 | CJK:goal 文本含 CJK 段(kohaku fixture)→superset/cjk(即使高置信) | §6.2 |
| H4 | 高置信非 CJK→narrow_eligible/confident+actions_enabled:false 在场(v1 零绑定效果的记录面) | OQ7 |
| H5 | **needed 集不变性**:有/无 gate 行两态,v13_judgment_envelope(sid)->'needed' 字节等(信封链零调 gate 的结构性钉死) | OQ7 |
| H6 | 零新调三重:gate 前后 judgment_calls 计数等;归一化扫描 intent_gate 体零 typesafe_ask;STABLE 属性断言(pg_proc.provolatile='s'——不可写结构性) | §6.2 前提 |
| H7 | thresholds 单源:改 intent pass 带 lo(0.75→0.90)→同 fixture mode 翻转 narrow→superset(证明带判定无第二真相);测毕还原 | 消费清单 #23 |

#### I 组 · 增量链完整性+回归(DP7 修复面)

| # | 断言 | 对应 |
|---|---|---|
| I1 | **token 十一键集恰等**:string_agg(jsonb_object_keys ORDER BY)='asm_ver,corpus,dec,econ_ver,gen_ver,goal,ident_ver,jdef_ver,recall_ver,sem,tools_rev'——**DP7 键谱回归(corpus/recall_ver)的修复断言面(附 A #1)**;逐键非空 | 换体三 |
| I2 | manifest v3:validate v4 词表含 kind='summary'(DP7 链标记)+economics 块层在场+render 块层恰 4 键——三上游 DP 的装配链标记全部在场 | 换体链 |
| I3 | manifest_version 3 产物拒 v2 形状(validate 负向);v13_replay 对 v2 老 artifact 逐字节回放(exempt 路径——DP7 OQ7 语义) | 换体六 |
| I4 | 前缀库互证:DP1–7 十三 stage gate 各自前缀库复跑全绿(AGENTS.md;上游库零 14 号对象——加载边界结构性) | OQ9 |
| I5 | files_through 切片:periphery 库装载恰 14 文件;≤13 号库无 latches 表/spawn_kind 列/v13_render(结构断言) | 加载边界 |
| I6 | DP5/DP6 装配增量存续:14 号库 manifest v3 的 query_side.candidates=v13_recall_candidates 产物(goal echo 零残留)∧已决候选 decision_id 非 NULL∧judgments 行 final_action 真值面(非占位)——前缀库互证盲区的行为断言(终检 P1 #2:DP5 E1–E3/DP6 F1–F2 只在 8/10 号库跑) | 换体五 |

**收尾工件(AGENTS.md)**:SQL 追加进 `v13/load.py`(第 14 位)+`STAGE_THROUGH["periphery"]=14`;stage README 更新;一里程碑一提交(`v13: <祈使句摘要>`,按路径 add,禁 `git add -A`)。`v13/periphery/README.md` 必记:①fork 子会话 v1=spawn/replay 壳语义(不可推进 turn;激活缝 OQ4/§1.4);②llm worker 契约扩记(request 构造=v13_render(sid)::text;result 携 context_artifact_id+wire_digest+usage.cache_read_input_tokens);③generation/system blocks 真值运维流程(翻 v3 仪式+blob 落地);④flip 人审仪式+streak 查询用法;⑤intent_gate 激活三前提;⑥probe 容差键校准流程。

### 4.2 逐文件影响与实施顺序

| 文件 | 变更 | 依赖/顺序 |
|---|---|---|
| `v13/periphery/v13_periphery.sql` | 全新增(§3.1→§3.8 即物理顺序) | 前置:一至十三号文件全部加载 |
| `v13/load.py` | SQL_LOAD_ORDER 追加 `'periphery/v13_periphery.sql'`(第 14)+STAGE_THROUGH | 零改既有行 |
| `v13/periphery/setup_db.py` | 新增(DROP-CREATE 库 `agent_v13_periphery`;files_through 前缀 14 文件;owner 连接) | DP1–7 setup 同形 |
| `v13/periphery/test_periphery.py` | 新增(A–I 九组) | 断言纪律见 §4 头 |
| `v13/periphery/README.md` | 新增(六条运维纪律+四流程) | — |

实施顺序(文件内即加载序):表/触发器/列→策略种子→identity/token/goal_hash→latch_fire/fork→render 族/probe→shadow/intent→换体五至八→ACL。**实施期机械自检(五项,turn 3 教训)**:①参数全用(probe 双 sid 子查询收平);②列存在(spawn_kind/context_active_*);③类型算术层(est 纯 int 除法/tolerance numeric/digest encode hex/jsonb ? 键查/IS DISTINCT FROM 全量/cast 作用域显式括号——`::` 优先级高于 `->`,receipt 两行 (v_wire->'k')::text 形态,L4 P1-3);④同签名唯一定义(八换体各恰一处,OR REPLACE 链非双定义);⑤纸面加载模拟(顶层语句计数/CREATE FUNCTION 唯一性/前向引用零/`$$` 配平)。

---

## 5. 风险与回退

| # | 风险 | 缓解 | 回退 |
|---|---|---|---|
| 1 | **DP7 键谱回归修复引入新回归**(十一键体与 13 号装配体内联 token 的双写面) | 换体五(b)把装配体内 token 归一为 v13_context_required 单源调用(双写面消除);I1 键集断言+上游 gate 复跑双保险 | 删 14 号文件+load.py 行+DROP 库即完全回退;≥13 号库不受影响 |
| 2 | fork 链回走深度(refresh 链长=回合数) | 链长=每会话 settle 次数,量级毫秒/步;README 记优化缝(artifact 链物化 prior 指针索引) | 同上 |
| 3 | render 对 blob/goal 回取的体积(wire 每次全量装配) | wire 不落库(零存储);render 仅 worker 调用一次/turn+settle 时 receipt(收 digest 不收 bytes) | 传输体积记 README;超限=optimizer 台账 |
| 4 | probe 估计失准(容差外的正常波动→噪声事件) | 容差键版本化(翻版校准);事件纯审计零动作;min_tokens 下限防小数噪声 | 关闭面=cache_probe 翻 tolerarance 1.0(事实禁用,行仍在) |
| 5 | shadow observe 增 settle 成本(每 watched 名一次双跑) | v1 targets=[] 生产零成本;gate fixture 演练后回滚;成本面=每目标一次只读 assemble(本地 ms) | targets 清空即零 |
| 6 | fork 壳语义误用(子会话被当 turn-runner) | README ①明示;子会话 canonical_state 为空→装配产出空 history 合法 manifest(非静默错数据);不可变 spawn 列防语义漂移 | — |
| 7 | latch 复制体积/上限(16 枚/会话) | 上限即上限;fork 复制在 cap 内(父集≤cap);超限 fork→V3008 响亮 | 翻 latches 策略 |
| 8 | ident_ver 单键合并 latch+render(未来第三输入进键需再动键集) | 键集增删=全域恰一次 refresh(DP3 既判);新输入进材料优先并入 ident_ver 材料对象(键集形状不变——DP7 econ_ver 扩集友好形态同款) | — |
| 9 | worker 契约扩记不被执行(driver 不携 usage.cache_read/wire_digest) | probe 的 no-op 形态(缺失=无对账面非错误);G/F 组断言契约面存在;README ②钉死 | 契约执行率记 README 运维面 |
| 10 | intent_gate 的 latest-intent 行非当前 turn 锚(v1 壳精度) | v1 不武装(actions_enabled=false)零生产影响;激活契约(§1.4)要求重锚定;H 组断言记录面 | — |

**回退总则**:删 `v13/periphery/` 树+`v13/load.py` 一行+DROP 库 `agent_v13_periphery` 即完全回退;对 1–13 号对象的所有变更都在 14 号文件内(OR REPLACE 语义:删文件重载即还原上游形态);共享库(若有)加载过本文件:重跑一至十三号即恢复上游函数形态。

---

## 6. 教程映射(§13;正文零改动,README 指针)

| 章·节 | 教程承诺(ch14 实测行号) | 本 DP 兑现 |
|---|---|---|
| 14.1 | 两件不焊:会话树 fork(日志前缀)vs ForkPrefix(缓存身份)(ch14:29–31) | OQ4 范围裁定的法源;本 plan 只落 ForkPrefix 平面(§1.5 不变量 3) |
| 14.2 | 会话树最小形态:两列+v_prefix_events 视图,assemble 读视图(ch14:34–50) | **不做**(OQ4 论证/§7);DP1 两列已在;视图+读穿透=激活缝(§1.4);README 指针 |
| 14.3 | 前缀身份哈希公式(system blocks+tool schemas+model+latches canonical bytes SHA-256);三件套(哈希/validate-spawn/cache probe)(ch14:59–85) | 换体二九键材料(公式的字节清单关系化);OQ4 validate-spawn;OQ5 probe;gate E/F 逐条 |
| 14.4 | 三种回放不得混称+对比表+exact replay 用旧 verdict(ch14:91–105) | spawn_kind 三值+forked 事件;exact replay 逐字节(E1);DP3 OQ5 mode 判定零改;shadow reroute 分工注记(OQ6) |
| 14.5 | 前缀-only 硬边界/ForkPrefix 另一条前缀/latch P1 理由/redeploy 安全绳(ch14:107–129) | 三列不可变触发器(A4);latch 进身份(材料键);安全绳=OQ2 generation latch(C2 直证) |
| 14.6 | G7 探针门:ForkPrefix 三条+三种回放四条+会话树五条(ch14:137–163) | ForkPrefix/回放七条=gate E 组 v1 断言;会话树五条(O(1)/读穿透/预算/并行/ALTER)=激活缝(§1.4 契约+§7)——README 明示哪些 v1 未断言 |
| 14.7 | 练习 1(v13_fork 签名/O(1))2(validate-spawn/probe)3(dream 三 kind)4(破坏性实验)(ch14:165–176) | 1=签名超集注记(附 A #8)+E8;2=E4/E5+F 组;3=E2(纯 SQL+mock);4=改写形态 E7(latch 不可变,漂移源=父后续 fire) |
| 14.8–9 | v8 拷贝式 fork 被拒/反事实/被拒替代(ch14:178–225) | 零拷贝(指针继承);反事实的行级证据=probe 事件+identity 对账(forked payload) |
| ch5/ch13 交叉 | latch 触点引用(ch14:26)/预取污染身份(ch13:93) | latch 表落地补齐 ch5 前向引用;预取=§7 台账(不进装配零污染面) |

---

## 7. 明确不做(§12 台账为源+本 plan 裁量)

| 项 | 依据/触发条件 |
|---|---|
| Emergent 表+在线 triage(触点 3) | §5.1/§14-1:P2,首个真实 mid-turn producer 出现(triage 永远确定性 admission) |
| 会话树读穿透+预算继承+父子并行 gate(v_prefix_events/canonical_state 前缀窗/advance 改写) | OQ4 裁定:激活=首个 fork turn-runner;命名空间错位非机械换源(附 A #3) |
| fork 子会话 turn-running | 同上(advance/route events 读面冻结纪律) |
| 呈现偏好立法(per-model render 策略) | §5.3/轮 2 裁决 6:匹配评估证明收益前不进;renderer 词表执法拒非 canonical |
| render 的 provider 协议适配层 | protocol_only:DeepSeek/OpenAI 映射归 driver(README 契约);v13 不立法 |
| wire bytes 落库 | OQ3/附 A #12:F11 经济纪律;(manifest+blobs+render 版本)可重现即达标 |
| intent 软门控实际绑定(触点 5 武装) | OQ7:激活三前提(§1.4);v1 记录面+零新 Jev 执法 |
| 语义压缩 hint 的生产/flip(触点 1) | **DP7 附 A #9 归属**:hint 机制/记录/硬类/证据门槛全在 DP7;本 plan 零 hint 代码(shadow 仪器与 hint flip=两证据面并行不混,OQ6) |
| context_tiers 动作 flip 走 shadow 双跑 | OQ6:actions off 时双跑恒等无信息量;证据面=DP7 校准流程(README) |
| auto-flip(策略凭观察自翻) | §6.7 在线 learned policy 拒;触发=人审仪式误操作成本实测超标(台账) |
| latch 消费者(target_turn+manifest membership) | §5.1 轮 2 形态已立法零代码;激活=首个消费者(如 cache scope 资格) |
| generation 真实 provider/model/system blocks 正文 | 数据真值归运维(附 A #11):机制已落地,值=ops 翻 v3 仪式(README) |
| 效用遥测(触点 4)/预取排序(触点 6)/分片哈希启用/T1/bigram/boost 闭环/语义决策缓存 | §12 台账原文;触发条件逐条在档(DP5/DP6/DP2 转发) |
| chunk sections 段级装配 | DP6 OQ7→实施期缝(§1.4 契约:render 零改已确认) |
| probe 的自动归因下探(逐段字节 diff) | v1 basis 两值;逐段 diff=cache probe 深化(触发=estimate_gap 事件量实测超标) |

---

## 附 A:与设计稿/上游裁决的分歧点清单(供父 loop 复核)

| # | 分歧/裁量 | 本 plan 裁决 | 呈报 |
|---|---|---|---|
| 1 | **DP7 token 键谱回归(主呈报项)**:DP7 换体一「机械复制 DP3 §3.2 加载态…键集 7→8」(DP7:459–462)与不变量 8「token 八键」——未携带 DP4 第八键 corpus(DP4 §3.6)与 DP5 第九键 recall_ver(DP5 §3.1 L5/gate H4);≥12 号库的 token 丢两键=语料/召回策略变更不触发 refresh 的 freshness miss 回归;DP7 自身 gate 断言「八键」在 12/13 号库内自洽放行,前缀库互证不可见 | 本 plan 换体三恢复全谱+ident_ver=十一键;I1 断言;装配体内联 token 归一单源(风险 1);**DP7 plan 文本与实施文件需对照修正(corpus/recall_ver 在 12/13 号 assemble/token 体内存续)——建议列入终局交叉覆盖检查清单** | 控制器+交叉检查 |
| 2 | stepfun F9(latch「进核心 P1」vs 交付排序第 5 步) | **plan 内消解**:身份保护自 DP3 起 stub 常量进 prefix_identity 材料即每 turn 结构性在场(六号文件起生效);表本体+真值接管第 14 位落地=第 5 步的实现位置;两说并存的根因=设计散文未区分「身份钩子在核心」与「表本体交付步」——stub→真函数换体把两说接通 | 呈报备案(F9 归属兑现) |
| 3 | ch14.2 会话树视图(v_prefix_events+读穿透)vs 本 plan fork=spawn 壳 | 设计 §5.6/§13-ch14 映射只点名 ForkPrefix 关系化;读穿透需 canonical_state 语义窗重设计(父子 seq 命名空间错位——非机械换源)+advance/route 改写(违反冻结纪律);激活=producer 门控(emergent 同款);§1.4 发布激活缝清单 | 呈报+缝发布 |
| 4 | 触点 5 v1 不武装(brief 未明写武装时点;§6.2 只裁「P1 条件留」) | 可选外部段不存在(chunk sections 未落地)+无语料-intent 分类账时收窄=k 截断重复立法+提前收窄的失败方向是 F2 族静默丢证;三重执法+激活契约补而武装 | 呈报 |
| 5 | 触点 1 归属(loop 分解表 DP8 行含触点 1 vs DP7 附 A #9 建议改消费) | 采纳 DP7 建议(控制器 turn-30/31 brief 已改):纯消费零重实现;shadow 仪器覆盖 {render_policy,assemble_manifest} 族,hint/tier flip 证据面归 DP7 校准流程——两证据面并行不混 | 已采纳,备案 |
| 6 | flip 不自动(设计「零 diff N turn 后 flip」可读作自动) | §6.7 拒在线 learned policy:策略凭自身观察翻自身=自学习;ready 查询+人审仪式;auto-flip 入台账 | 呈报 |
| 7 | probe 走 worker 契约面而非 events 触发器/complete 改写 | complete/advance 冻结;DP3 context_artifact_id 先例=契约面+gate 断言;触发器面加深持锁事务 | 裁量 |
| 8 | v13_fork 签名四参(ch14.7 练习三元组) | 第四可选参 p_overrides DEFAULT NULL——默认形态=练习签名(超集不破坏);validate-spawn 的 clamp 拒绝面需要它 | 裁量(超集注记) |
| 9 | v13_goal_hash 换体(前缀感知)——非 fork 会话零回归承诺 | identity 需求的最小例外;E6 双库对照钉死字节等;canonical_state/transcript 零触碰(不变量 3) | 裁量 |
| 10 | ident_ver 单键合并 latch+render(DP3「扩 gen_ver 或增独立键」二选一) | 独立键+单键合并两输入(材料对象可扩——DP7 econ_ver 扩集友好形态同款);gen_ver 语义纯净化(latch 内版本) | 裁量 |
| 11 | generation v2 值仍 mock(brief「接管真值来源」的真值歧义:机制 vs 数据) | 机制真值全落地(结构/校验/blob/latch 冻结);数据真值归 ops(DP3 骨架值逐字衔接;README 仪式);mock 种子=gate 可跑+升级零惊吓 | 呈报(语义澄清) |
| 12 | wire 不落库(§0「artifact 固化实际交给模型的内容」的可读面) | F11:每 turn 一份完整 wire 拷贝=最大的未入账 token 消耗;(manifest+blobs+render 版本)三元组可重现+wire_digest 在场=固化承诺的等价兑现;D1 断言重现 | 呈报(读法澄清) |
| 13 | DP3 prefix_identity 注释「材料恒九键」vs 函数体八键 | 以函数体为准(八键计数笔误);DP8 落地日恰成九键(render_policy_version)——注释与实态在本 plan 后自洽 | 呈报(勘误) |
| 14 | latch value 立法为 jsonb object(设计未定类型) | 结构化值进 digest;标量清包 {"v":...};CHECK 不加(上游无 CHECK 先例,形状在 fire 入口执法) | 裁量 |

**设计矛盾检查:未发现 blocked 级矛盾。**§5.1/§5.3/§5.6/§6.2 触点 1+5/§9/§10 切片/§12/§13 的 normative 内容全部有落点(§2 映射表);G-ctx6 绕行为用户既定默认(头部注记);唯一跨 plan 缺陷(DP7 键谱)在修复面内闭合(附 A #1)。

---

## 附 B:全教训自检(turn 1–30,机械执行记录)

| 教训 | 本 plan 执行 |
|---|---|
| **纸面加载模拟记数字**(turn 8/9) | §3 草案对象:第 14 号文件顶层语句 **36 条**(实施期若将 render 段体单源抽取件落实体则 37):CREATE TABLE 1+ALTER 1+触发器函数 2+触发器 3(latches 行级+latches TRUNCATE 语句级+spawn 列,L4 P1-4)+策略 INSERT 1(六行同语句)+翻版双 UPDATE 2+CREATE FUNCTION 新 12(generation_effective/ident_ver/latch_fire/fork/render_wire/render_receipt/render/cache_probe/shadow_observe/shadow_projection/shadow_streak/intent_gate;+1 实施期抽取件 render_section_body)+OR REPLACE 8(latch_digest/prefix_identity/context_required/goal_hash/assemble/validate/refresh/blob_land)+ACL 4(REVOKE 表 1+REVOKE 函数 1+GRANT route 1+GRANT recall 1)+BEGIN/COMMIT 2;`$$` 配平=每函数恰一对;同签名唯一定义(八换体各恰一处,OR REPLACE 链非双定义——DP6/DP7 同款注记) |
| **同签名唯一定义**(turn 9 #57/42723) | 上表已计;v13_render_wire 第三参带 DEFAULT(非重载——单定义默认参) |
| **前向引用**(turn 8) | 14 号为零终端文件(无 15 号);对上游引用全部 ≤13 号(§3.7 复制源表逐对象列链);文件内序=依赖序(render_receipt 在 wire 后;fork 在 latch_digest/context 无环) |
| **类型算子层**(turn 7/8) | est 纯 int 除法((bytes+div-1)/div,DP3 逐字);tolerance numeric 字面量+::numeric;digest() 产物一律 encode(...,'hex');jsonb 键存在用 ?/值比较 ->> 后 IS DISTINCT FROM;null 枚举三值逻辑封死(IN...IS NOT TRUE——validator v4 增量逐字继承 DP3 层纪律);abs() 入参 numeric 显式 cast;策略种子单完整字面量+::jsonb |
| **移动=增+删**(turn 8 #57) | 零移动场景(纯新文件);OR REPLACE 语义=替换非复制;v13_latch_digest stub 的唯一存活形态=6 号文件库(墓碑注记在换体一处);DP7 十键体唯一存活形态≤13 号库(墓碑注记在换体三处) |
| **gate 不引用未加载对象**(turn 7 #46) | gate 断言对象全部 ≤14 号;对 DP7 对象只读消费;I5 前缀切片断言上游库零本文件对象 |
| **哈希同源**(turn 2 等) | latch_digest 单源(identity 材料+ident_ver 材料共消费);ident_ver 与 prefix_identity 的 render_policy 版本同查询面;render tools 与 tools_digest 同 canonical_state 投影(D3);goal 链单源(goal_hash);est 公式与 DP3 同除数同式;token 双写面归一(换体五(b):装配体内联改单源调用) |
| **新写 SQL 自检**(turn 3 教训) | §4.2 实施期五项(参数全用/列存在/类型算子层/唯一定义/纸面加载模拟);草案内已自查三处并注记收口:probe 双 sid 子查询收平(§3.5 注)、fork 的 generation_version belt 以显式 RAISE 最终化(§3.4 注)、render_wire 段体抽取共用(§3.5 注) |
| **引擎争议实机实证可选**(turn 10/25) | 本 plan 零引擎争议断言:jsonb canonical 键序=DP3 prefix_identity 已依赖的既有事实(零新依赖);fork「O(1)」以源码结构断言(E8)非计时断言(计时面归会话树激活包);无 stannum/typesafe 新行为面——**本轮无需实机探针**(与 DP2/DP6 同界) |

---

*(完——DP8/8;八份 plan 齐后进入终局交叉覆盖检查,附 A #1 建议列入其清单。)*

## v2 对齐修订(2026-09-21)

> 日期:2026-09-21。本轮**只追加本节**,上文一字不删、不改写。
> 对齐输入(只读):
> - `docs/analysis/repoprompt-native-on-v13-feasibility-v2-2026-09-21.md`(v2 主文档:§1 I-file-1 / §2.1 sessions `files_cutoff` / §4 render·三回放 / §5 G-file-replay / §7 冲突登记)
> - `docs/reviews/repoprompt-native-context-oracle-r1-r3-2026-09-21.md`(裁决记录 D2/D5;D5 末格=fork cutoff 公式)
> 纪律:与 v2 冲突的原文以 `ERRATUM:` 行标注并指向 v2 §7 对应行;既有 gate 一律不弱化(含 E 组 fork/validate-spawn / C 组 identity / D 组 render receipt / B5 latch digest / 不变量 1 零外部 IO / 不变量 6 validate-spawn fail-closed);新增断言只加不减。本轮不 invent 新里程碑实现、不改 SQL 代码。
> 编号铁律:本文件只用 **A12**(latch/fork `files_cutoff`)、**A6**(latch 前缀身份哈希输入不含文件内容)与 **A13**(render 只读 artifact bytes)。不要写 A14 / A2 / A3 / A1 / A4 / A5 / A7–A11(那些归其他计划)。**A12 全局=latch/fork**,不得复用于其他语义。DP3 已在 manifest/file-section 面登记 A6/A13 同口径;本 DP 登记 **DP8 执法/render/latch 输入侧**。

### 对齐总表(v2 条款 → 本计划改动点 → 换体登记)

| # | v2 条款 | 本计划改动点 | 换体登记 |
|---|---|---|---|
| A12 | §2.1 sessions `files_cutoff`;D5 fork 冻结公式;G-file-replay 三回放;I-file-1 子会话不得越世代 | sessions 增 `files_cutoff`;exact/recompute **exact** 复制父值并**冻结**;fresh fork 采用最新已发布 epoch;子会话 recall 不得越过 cutoff 世代;三回放语义落文件面(与 DP3 已登记同口径),DP8 记 **fork 执法侧** | 不适用(执法侧立法,不改上文 SQL 字面;OQ4 spawn_kind / validate-spawn 不删) |
| A6 | I-file-1 身份三元组;文件经 artifact hash 进 manifest | latch 的前缀身份哈希输入**不含文件内容**;`v13_latch_digest` / prefix_identity 材料=latch 的 name,value(fired_at 已排除);文件字节/路径/stat/epoch/HEAD 不进 latch digest | 不适用(输入论域收窄;OQ8 {name,value} 与 fired_at 排除不删) |
| A13 | §4 R6 render 只读 artifact bytes;I-file-1+I-file-4 只读已冻结行 | `render` / canonical render 只读 artifact bytes,**禁开源路径**(与 DP3 A13 同口径;本 DP=render 函数业主,OQ3 `v13_render_wire` / `v13_render`) | 不适用(纯函数输入约束;OQ3 签名/三件套不删) |

### A12 / latch·fork files_cutoff · 三回放执法侧

v2 §2.1:sessions 增 `files_cutoff jsonb {git_head, worktree_id, max_file_epoch}`(**spawn/fork 时冻结;fork 复制父值**);**不加 ws_revision**(D2 裁决)。Oracle D5 末格:`fork 时 files_cutoff={tips.git_head, worktree_id:null, max(pointer.source_epoch)} 冻结`。§5 G-file-replay:**exact 不发 FS effect;recompute 允许 register;fresh fork 新 cutoff**;把重读 FS 标 exact→红。§1 I-file-1:进 manifest/render/exact replay 的字节必须已冻结;子会话不得看见 cutoff 之后的文件世代。§7 行「ch01「模型可见 ⟺ 已落行」」=增量适用到文件字节;「v13 §4.3 / G-ctx1」=增量适用到 FS/git(零锁内 IO)。

**与 DP3 的分工**(同口径,不开第二套三回放):DP3 A6 已在 manifest/file-section 面立法三种回放;本 DP 记 **fork 执法侧**(OQ4 `v13_fork` / spawn_kind / validate-spawn / 子会话 recall·render·identity 读面)。三回放语义落文件面(与 DP3 已登记同口径)。

**本计划改动点**(只立法,不改上文 SQL 草案字面、不 invent 新里程碑):

sessions 增 `files_cutoff jsonb {git_head, worktree_id(null), max_file_epoch}`。列随会话写入一次即冻结(与 spawn 三列同「一次写入永不改」纪律);fork 写入后子行不可 UPDATE。**不加 ws_revision**。

既有三种 spawn_kind(`exact_replay` / `recompute` / `fresh_fork`)的 **files_cutoff 执法**:

1. **exact**(`exact_replay`):fork = **exact** 复制父值并**冻结**(copy parent `files_cutoff` verbatim and freeze)。子会话 recall/render/identity 不得越过 cutoff 世代(不得看见该 cutoff 之后的文件世代)。**zero live FS**(exact 不发 FS effect;把重读 FS 标 exact→红)。
2. **recompute**:同一份继承而来的冻结 cutoff(enforcement side=父值 **exact** 复制并**冻结**,与 exact 同 cutoff)。register effects allowed(worker 可建 `file_register`);assemble still no lock-inner FS(装配持锁内零 FS/git,与不变量 1 / G-ctx1 同向)。
   【L4 标注(F6)】「worker 可建 `file_register`」**已废止**。现行口径:advance/system SQL 可 enqueue `file_register`; worker 只执行与 fenced settle。recompute *mode* 允许消费/等待已入队的 register,不授权 worker INSERT/enqueue effects。
3. **fresh fork**(`fresh_fork`):does NOT inherit the parent's stale cutoff(不是一份过期父 cutoff 的拷贝)。**fresh fork** 采用最新已发布 epoch 作为新 cutoff:`max_file_epoch` = latest published corpus/pointer epoch;`git_head` from tips;`worktree_id` null unless a worktree is bound。Oracle D5 公式即此冻结点:`fork 时 files_cutoff={tips.git_head, worktree_id:null, max(pointer.source_epoch)} 冻结`。v2 §2.1 字面「fork 复制父值」适用于 exact/recompute;fresh 走 D5 新 cutoff,不复制 stale parent。
fork 复制父 `files_cutoff` 仅适用于 exact_replay/recompute;fresh_fork 必须从最新已发布 epoch 生成并冻结新 cutoff,不继承父 cutoff。

G-file-replay 执法侧对照:exact 不发 FS effect;recompute 允许 register;fresh fork 新 cutoff。子会话 recall 不得越过 cutoff 世代(迟到/乱序收据不越 cutoff——后续 G-file-cutoff 只加不减)。

`ERRATUM:` OQ4 约 L84–88 / §3.4 `v13_fork` 约 L524–529「建子行(parent 两列+spawn_kind)」+「latch 复制:exact/recompute 全量复制父 latch 行」——原文只复制 latches 与 `parent_cutoff_seq`/`spawn_kind`,**从未提及 `files_cutoff`**。原文 spawn-kind 词表 / validate-spawn(身份声称类 kind 比 artifact 冻结身份) / latch 复制 / `parent_cutoff_seq` 越界 V3008 **一字不删**;本条增量登记 sessions `files_cutoff` 的 fork 冻结与三回放执法。指向 v2 §7 行「ch01「模型可见 ⟺ 已落行」」(增量适用到文件字节;子会话可见=cutoff 内已落行)与「v13 §4.3 / G-ctx1」(exact 零 live FS;recompute 装配零锁内 IO)。

`ERRATUM:` §3.1 约 L218–223 `ALTER TABLE sessions ADD COLUMN spawn_kind` + 三列不可变触发器(`parent_session_id`/`parent_cutoff_seq`/`spawn_kind`)——原列与触发器不删;未来 R0a/`files_cutoff` 列写入后同「一次写入永不改」,不得把「只增 spawn_kind」读成「fork 无需冻结文件世代」。指向同一 v2 §7 行「ch01「模型可见 ⟺ 已落行」」。

既有 gate 不动:E 组 fork(E1 exact_replay 逐字节 / E2 三种 spawn 可区分 / E3 越界零行 / E4 validate-spawn 四负向 / E5 fresh fork overrides / E6 goal_hash 回归 / E7 冻结隔离 / E8 O(1) 结构) / A4 spawn 列不可变 / 不变量 6 validate-spawn fail-closed——一律不删不弱化。后续 G-file-replay / G-file-cutoff 只加不减。

### L4 修复(2026-09-21)

> 本小节只追加、不删 A12 上文。F6/F8 为 L4 终审 FAIL 并集修复。既有 gate 一律不弱化(E 组 fork / A4 spawn 列不可变 / 不变量 6 / D 组 render / 不变量 1)。

**F6 · effect 创建者**

A12 原句「register effects allowed(worker 可建 `file_register`)」**已废止**。现行口径:**advance/system SQL 可 enqueue `file_register`; worker 只执行与 fenced settle**。G-file-replay 「recompute 允许 register」收窄为:recompute *mode* 允许消费/等待已由 advance/system SQL 入队的 `file_register`,不授权 worker 自建/enqueue。装配持锁内零 FS/git(不变量 1 / G-ctx1)不弱化。

**F8 · fork cutoff 措辞**

fork 复制父 `files_cutoff` 仅适用于 exact_replay/recompute;fresh_fork 必须从最新已发布 epoch 生成并冻结新 cutoff,不继承父 cutoff。

### A6 / latch 前缀身份哈希 · 输入不含文件内容

v2 §1 I-file-1:模型可见身份=`(ws_id, canonical_path, content_hash)`;stat 禁作身份/缓存键/replay 键;进 prefix 身份的字节必须已冻结为 artifact。DP3 已在 manifest 面登记「文件经 content_hash 进段、stat 不进 prefix_identity」;本 DP 登记 **latch 输入侧**。§7 行「ch01「模型可见 ⟺ 已落行」」=身份材料=已落行,不是活文件字节。

**本计划改动点**(只立法,不改上文 SQL 草案字面):

1. latch 的前缀身份哈希输入**不含文件内容**。`v13_latch_digest` / prefix_identity 材料闭集=latches 的 **name,value**(OQ8 / §3.3;`fired_at` already excluded——时间戳非内容身份,B5 已钉)。File bytes / paths / stat / epoch / HEAD **must not be latch digest inputs**。
2. 文件经 artifact hash 进 manifest,不直接进 latch。`kind='file'` 的 `content_hash` 走 DP3 段/`payload_ref`,不经 `v13_latch_fire` 把正文或路径塞进 latch `value`。
3. OQ1 九键材料(`provider`/`model`/`system_blocks_digest`/`tools_rev`/`tools_digest`/`goal_hash`/`latch_digest`/`render_policy_version`/`manifest_version`)保持;九键无一是文件正文。不得把 `files_cutoff` / `git_head` / `max_file_epoch` / 源路径写进 latch digest 或 prefix_identity 材料。

`ERRATUM:` OQ8 约 L117 / §3.3 约 L278–283 `v13_latch_digest`=`sha256(jsonb_agg({name,value} ORDER BY name))`+「**fired_at 不进材料**」——{name,value} 闭集与 fired_at 排除**不删**;本条收窄读法:不得把 latch `value` 读成可携带文件正文/路径/stat/epoch/HEAD 的身份输入,也不得把文件字节解作 digest 材料。指向 v2 §7 行「ch01「模型可见 ⟺ 已落行」」(身份材料=已落 latch 行的 name,value,不是 FS 字节)。

`ERRATUM:` OQ1 约 L65 九键材料清单——键集不删不扩文件键;不得把「latch_digest 进身份」读成「文件内容进身份」。指向同一 v2 §7 行「ch01「模型可见 ⟺ 已落行」」。

既有 gate 不动:C 组 identity(C1 首 settle 首发 / C2 mid-session 翻版安全绳 / C3 未 pin 追动 / C4 render_policy 追动 / C5 latch 追动 / C6 九键材料) / B5 digest(fired_at 不改 digest;空集='-none-') / 不变量 2 latch 一次性 / 不变量 4 进 identity 的输入必须在 token 有键——一律保留。后续若加「latch value 禁文件字节」探针,只加不减。

### A13 / canonical render · 只读 artifact bytes

v2 §4 R6:`render` 只读 artifact bytes;三种回放显式标注。I-file-1 + I-file-4:`parse/advance/recall/visibility/manifest/render` 只读已冻结行;所有 FS/git IO 发生在 effect worker。DP3 A13 已在 manifest 消费面登记同口径(「render 本体仍归 DP8」);本 DP 是 render 函数业主(OQ3 `v13_render_wire` / `v13_render` / `v13_render_receipt`)。§7 行「ch01「模型可见 ⟺ 已落行」」+「ch07「文件=artifacts」」+「v13 §4.3 / G-ctx1」。

**本计划改动点**(只立法,不改上文 SQL 草案字面):

`render` / canonical render **只读 artifact bytes**,**禁开源路径**。输入闭集=已冻结 context artifact / `kind='file'` artifact / section blob / system_block blob(经 `payload_ref` / content_hash 回取 artifacts 行);不得 open/stat/readpath 源文件,不得把 `normalized_path` 或 `payload_ref` 当读盘句柄。OQ3 三件套签名(`v13_render_wire` / `v13_render_receipt` / `v13_render`)与「wire 不落库」不删;读论域收窄为已冻结行。I-file-1 + I-file-4 字面落到本函数族:parse/advance/recall/visibility/manifest/render 只读已冻结行。

`ERRATUM:` OQ3 约 L79 / §3.5 约 L615–628 `v13_render_wire`「body 经 payload_ref 判别回取(blob→context_section inline;goal→v13_goals payload::text)」——回取形态与纯函数签名不删;不得把 payload_ref / 段 `normalized_path` 读成源路径 open。canonical render 只读 artifact bytes,**禁开源路径**。指向 v2 §7 行「ch01「模型可见 ⟺ 已落行」」与「ch07「文件=artifacts」」(模型侧=artifacts)以及「v13 §4.3 / G-ctx1」(零锁内 FS/git IO)。

`ERRATUM:` OQ3 约 L81 `v13_render`「读 sessions.context_active_artifact→inline→render_wire(worker 面)」——worker 面调用不授权打开源路径;worker 若需新文件字节必须先 register/settle 成冻结行,render 仍只读已落 artifact。指向同一组 v2 §7 行。
【L4 标注(F6)】「worker … register/settle」不授权 worker 自建/enqueue `file_register`。现行口径:advance/system SQL 可 enqueue `file_register`; worker 只执行与 fenced settle。render 仍只读已落 artifact。

既有 gate 不动:D 组 render(D1 纯函数确定性+wire 重现 / D2 wire 结构 / D3 tools 同源 / D4 system blocks 通道 / D5 render 块进 manifest+receipt est / D6 空表衔接 / D7 钉版本) / 不变量 1 装配零外部 IO / 不变量 5 render 确定性——一律不删不弱化。后续若加锁内 open 探针(G-ctx1-file),只加不减。
