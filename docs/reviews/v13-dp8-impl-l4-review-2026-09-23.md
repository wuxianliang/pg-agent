# dp8 实现验收评审（L4 代行）——dp7 P2 收口 `8c31ccb` + periphery `69e5ebb`

> 日期：2026-09-23。性质：父级 Loop Orchestrate 控制器授权的 L4 验收代行评审（ask_oracle 管道故障延续，按 dp7 先例降级为本地 Review 工作流，如实记录）。dp8 为末个 plan，本评审后循环进入终局。
> 材料（全部亲读）：plan `docs/plans/v13-dp8-periphery-p1-plan-2026-09-20.md` 全文 1245 行（含 v2 对齐修订 A12/A6/A13 与 L4 修复 F6/F8）；dp7 修复权威 `docs/reviews/v13-dp7-impl-l4-review-2026-09-23.md` §修复清单（P2-1/2/3）；`git show 8c31ccb`（1 file +55/−46）与 `git show 69e5ebb`（6 files +4097）；`v13/periphery/v13_periphery.sql` 全文 2382 行；`v13/periphery/test_periphery.py` 全文 1555 行；`v13/periphery/{README.md,setup_db.py}`；`v13/load.py`；copy-source 加载态（`v13_summary.sql`/`v13_economy.sql`/`v13_manifest.sql`/`v13_core.sql`/`v13_recall.sql` 关键面）；`v13/summary/test_summary.py` 修复前后版本；`prompt-exports/loop-orchestrate-v13-deep-plans-impl-runs.md`（turn 14 行在档；turn 15 行尚未落表——本评审属 turn 15）。
> 已验证事实（控制器 L1 已核，本轮未复跑）：14 gate 全绿 exit 0（periphery 128 PASS；twophase 119/envelope 369 树扫描 +1 预期=13 号基线各 +1；loop 无抖动）；两提交已推 origin/main（main 与 origin/main 同步）；diff 范围=summary test+periphery 五件套+load.py+2。
> 本轮**独立复验**（不采信 gate 自身断言的部分）：①四换体（五/六/七/八）+换体二/三对各自复制源的归一化 diff（评审者自己提取函数体+剥注释/剥缩进+unified diff 逐簇核对）；②A5 源码扫描计数独立重算（V3008=34/RAISE=104/errcode=97/bare=7，$$ 46 配平）；③顶层语句机械计数（40）与 CREATE FUNCTION 唯一性（23 零重复）；④check 调用点计数（summary 修复前 176→后 177；periphery 104 check+23 fails_with）；⑤thresholds 列名/DP5 分段器码位常量对加载态逐组核对；⑥token 键谱逐键清点。

---

## 0. 结论一览

| 项 | 结论 |
|---|---|
| **`8c31ccb`（dp7 P2×3 收口）** | **PASS**（P2-1/2/3 三项全部真闭合，1:1 可红，无 check 静默，SQL 零改动） |
| **`69e5ebb`（dp8 periphery）** | **PASS**（SQL 对 plan §3 忠实；换体纪律全对；A–I 断言全强断言；18 偏差 18/18 ACCEPT；发现 0 P0 / 0 P1 / 0 P2，5 条 P3 级注记） |
| **dp8 收官** | **是**——第 14 号 stage 交付完整，附 A #1（token 十一键谱恢复）主呈报项兑现 |
| **可否进终局** | **可**（全量复跑+erratum 汇总呈报；erratum 清单见 §6） |

---

## 1. `8c31ccb`：dp7 L4 P2×3 闭合验证（聚焦）

| # | 修复要求（dp7 修复清单） | 实施核验 | 结论 |
|---|---|---|---|
| P2-1 | O3-③ 恒真占位 → guard 规则 3 测试端镜像（材料 seq 集与 keepc.tail_seq 前缀零交集） | 占位 `check(..., True)` 已删。新断言三臂合取：①`tailb_l` 测试端独立重算（活动 context_budget.keep_tail_turns + canonical_state user/message seq 降序第 keep 名——与 SQL keepc 同式）；②`mat_t` 经 history 段 content_hash 从 artifacts 回取（同 worker 契约路径），断言 `not any(seq < tailb_l)`（前缀零交集=final_trim 后前缀 rounds 全丢的镜像）；③round_drop trace 段在场。可红性成立：任一前缀 round 幸存 ⇒ 其消息 seq<tailb_l ⇒ 红；keep 名不足 ⇒ `tailb_l is not None` 红。失败诊断元组 (keep_l, tailb_l) 在场 | ✅ |
| P2-2 | `if False else` 死代码 → 真旧字节回取断言 | 死代码已删。两步真断言：**锚捕获**（P5 收缩前：活动 context artifact 的 history 段哈希 h0_p + 该哈希 context_section 行 `inline::text` 原字节 pre_bytes_p）；**回取对照**（①本 session 的收缩前 context artifact 仍引用旧哈希——`JOIN effects ON produced_by` session 限定计数恰 1，replay 链可达性；②该哈希行 inline::text 与捕获字节**逐字相等**）。session 限定的论证正确：内容寻址材料跨 session 共享是设计行为（identical fixture⇒同哈希），全局计数不可判归属，produced_by 限定是唯一可判面。红性：artifacts 行被 UPDATE⇒字节不等红；引用被改⇒计数 0 红 | ✅ |
| P2-3 | prepare_round 同体重复定义去重 | 第二定义（影子覆盖者）整段删除；评审者对修复前文件提取两定义体做字节比对：**identical**（同体确认，删除零行为变化） | ✅ |
| 无 check 静默 | — | 静态调用点 176→177（净 +1=P5 一拆二；P2-1 1:1 替换；P2-3 零 check）——与提交信息「基线 227+P5 净增 1=228」自洽；diff 全文仅触三处，无别处削弱 | ✅ |

注记（P3，非缺陷）：turn 14 行与 dp7 L4 评审「已验证事实」记 summary gate「228 PASS」，而本提交基线实跑 227——两处记录有一处 off-by-one（代码与断言层无问题，方向只增强）。终局全量复跑以实跑数字钉死，erratum 记一行。

---

## 2. `69e5ebb`：dp8 全面验收（dp1 同标准）

### 2.1 SQL 对 plan §3 忠实度（逐面）

| 面 | 核验 | 结论 |
|---|---|---|
| latches 表+触发器族 | 列集=§5.1/§9 逐字；PK+name 词表 CHECK；BEFORE UPDATE/DELETE 行级 + **BEFORE TRUNCATE 语句级**双触发器（L4 P1-4）同 guard 函数（TG_OP 分支，语句级不触 OLD）；spawn 三列不可变 guard（BEFORE UPDATE OF 三列，非 fork 列不受触——gate A4 双向） | ✅ |
| latch fire（OQ8/F13） | sessions FOR UPDATE（admission 事务锁，同锁序）→回读 adopt→锁内计数≥cap V3008 fail-closed→INSERT ON CONFLICT DO NOTHING→回读返回；保留名 'generation' public 拒；value 必须 object | ✅ |
| generation 真值接管（OQ2） | `v13_generation_effective` latch 优先/无 latch 落活动行+注入 generation_version；refresh 换体七(b) 装配前内联 fire-or-adopt（首触发=首次装配）；**值仍 mock 与 DP3 骨架逐字衔接**（空表 digest='-none-'，gate D6 空会话可比性实测） | ✅ |
| identity/token（OQ1） | 换体二九键材料（+render_policy_version 缺行 RAISE、manifest_version 3、provider/model/digest 改经 generation_effective）；`v13_ident_ver` 单源（sha256{latch,render_policy_version}）；**换体三 token 十一键**——逐键清点：sem/dec/goal/tools_rev/asm_ver/jdef_ver/gen_ver/corpus/recall_ver/econ_ver/ident_ver **恰 11 键**（gate I1 string_agg 字典序恰等）；gen_ver 改经单源（latch 冻结语义，C3 双面实测：pinned 恒 2/unpinned 追 v4） | ✅ |
| goal_hash 前缀感知（换体四） | 锚行法：chain 锚 cut=本会话 parent_cutoff_seq，非 fork 行 cut=NULL 守卫自然止于自身=与 ≤13 号公式逐字节等（gate E6 语义镜像断言）；fork 子逐代上行取首个非空层 max(seq)≤cut；草案 `INTO v_row.content_hash` 笔误改标量（偏差 #4，语义零变化，plan 自注机械自检类） | ✅ |
| fork 壳+validate-spawn（OQ4） | kind 词表/父行 FOR UPDATE/cutoff∈[0,next_seq-1] 越界 V3008；链回走取最新 sem≤cutoff 的 artifact（fresh 不继承）；三列+route_policy 继承；非 fresh 全量复制 latch（fired_at 保真→子 digest=父，B5/E7 字节基础）；fresh 零复制+overrides||进自己 generation latch（generation_version belt 显式 RAISE=机械自检#3 落地）；**validate-spawn**：overrides+身份声称类→V3008（面 1）；子此刻身份 vs **artifact 冻结身份**不等→V3008 不落行（面 2，事务内 RAISE）；fresh 无身份检查（L4 P1-2 注记+E5b 合法相等断言）；forked 事件携身份对+overrides | ✅ |
| render 函数族（OQ3） | wire/receipt/render 三件+**段体单源抽取件 v13_render_section_body**（plan 实施期 +1 件，wire 与 receipt 共用零第二实现）；段渲染按数组原序 plpgsql 循环（plan 机械自检注记落地）；marker='[v13-section:id:cache_scope=…]'（cache_markers 开关）；tools=canonical_state 同源（D3 字节等）；system blocks=列表→blob 按序回取+缺失 fail-closed；**wire 不落库**（D1 重现面：re-derivation==冻结 wire_digest）；receipt est=DP3 整数算术逐字（D5 独立重算对照） | ✅ |
| cache probe（OQ5） | 对账锚=**effect.result->context_artifact_id**（非 sessions 当前指针——F6 竞态免疫实测）；两线（wire_mismatch 可缺省跳过/estimate_gap 容差=max(est×ratio,min)）；usage 缺键 no-op；非 llm/非 succeeded no-op；纯审计零 UPDATE（F5 行级对照）；sid 一次性抽取（机械自检#1） | ✅ |
| shadow（OQ6） | observe 词表封闭 {render_policy,assemble_manifest} 带外 V3008；render 族=wire_digest 等/assemble 族=内容投影（sections+candidates+judgments，剔 policy/required_revision/economics）等；streak=events 最近窗布尔聚合（events.at 列，偏差 #5）；flip=人审双 UPDATE（G6 复测 C4 同链）+auto-flip 源码缺席断言（observe/streak 体零 UPDATE v13_policies） | ✅ |
| 触点 5（OQ7） | intent_gate STABLE 纯读；三源全复用（decisions 既有 intent 行/thresholds 带列名按 DP1 加载态 policy_name·policy_version——与 v13_routes 视图 join 同式/DP5 分段器纯文本段数组⇒段首码位五区间镜像 v13_query_segments 同组常量，零第二分词）；superset-on-doubt 三 basis；actions_enabled=false 记录面；H5 needed 不变性+H6 三重执法（cals 零增量/零 typesafe_ask/provolatile='s'）+H7 thresholds 单源（真 draft→插带→freeze→sessions 指新版本仪式，同 fixture mode 翻转） | ✅ |
| 触点 1（纯消费 DP7） | 零 hint 代码（SQL 全文无 compact_hint 生产面）；README 契约声明段在档；shadow 仪器与 hint/tier flip 两证据面分工注记（G4 词表执法=消费侧确认） | ✅ |
| TRUNCATE/六处计数联动/V3008/纸面加载/前缀切片 | A3 三向（UPDATE/DELETE/TRUNCATE 各 pgcode V3008）；V3008 全部新 RAISE 显式（34 检查点，独立重算恰等）；顶层语句机械计数 **40**（README #16 恰符；附 B 草案 36/37+DROP+invoker GRANT+实施期形态）、CREATE FUNCTION 23 零重复、$$ 46 配平；load.py 第 14 位纯末尾追加+STAGE_THROUGH（I4 恰 14 文件；I5 前缀源零 periphery 对象） | ✅ |

### 2.2 换体纪律（复制源/锁集/ACL——独立归一化 diff）

| 换体 | 复制源（实施） | 评审者 diff 结果 | 裁定 |
|---|---|---|---|
| 五 assemble v4 | 13 号加载态 v3 | 归一化 753→758 行，**恰两簇**：manifest_version 2→3；尾 SELECT 移入 fin 子查询+`\|\|` 追加 render 键（receipt 在 sections 定稿后同语句求值）。其余逐字（含 DP7 全部 economics/summary 消费面） | ✅ 13 号=该对象加载序最新形态（plan §3.7 表格"12 号"为计划冻结时点快照——若照抄 12 号会丢 summary 面；「最新形态」规则适用正确，偏差 #1） |
| 六 validate v4 | 13 号加载态 v3 | 恰四增量：外层 12 键(+render)/manifest_version 3/render 块层（4 键恰等+词表+64hex+int 下限+V3008）/required_revision 十一键字典序(+ident_ver 64hex)。其余逐字 | ✅ |
| 七 refresh v4 | **13 号终态**（=12 号 v2+belt 增量） | 增量恰四簇：DECLARE 六新变量；**锁集 13 号六名+render_policy=七名**（ORDER BY name FOR UPDATE——保 summary_accept 是必要合并：plan 字面六名系自 12 号推导漏了 13 号新增的 summary_accept，照抄会削弱 DP7 belt 并发序，合并裁量正确，偏差 #2）；[DP8] 外围守卫块（render_policy 强化+generation v2 形状含 blob 实算 digest 校验+latches/cache_probe/shadow_flip/shadow_watch/intent_gate，全 V3008）；generation 内联首发+shadow 尾观察。其余逐字（锁序骨架/守卫全文/belt/artifact_land/指针/返回值） | ✅ 复制源=13 号正确（评审任务问点：**是**——「最新形态」规则适用正确） |
| 八 blob_land | 6 号加载态 | 签名 2→3 参（p_kind DEFAULT 'context_section'，既有调用点零改动）⇒ **DROP+CREATE**（OR REPLACE 加参=新签名重载、旧两参形态存活=双定义陷阱——DROP 正当，偏差 #3）；kind 词表执法+system_block 直插分支（无 partial unique 索引；自证 CHECK 原样适用；重落同哈希可多行=无害已记档） | ✅ |
| 二 prefix_identity | §3.3 全文重写（修复性，非机械） | vs 6 号 diff=planned 增量恰合：generation_effective 三读替换+render_policy_version+manifest_version 3+V3008 化 | ✅ |
| 三 context_required | 12 号加载态（十键体） | vs 12 号 diff **恰两增量**：gen_ver 改经 generation_effective（+V3008）；+ident_ver。corpus/recall_ver/econ_ver 等逐字继承（turn 34 源头修复已在 12 号——附 A #1 的实施侧先行闭合，本 plan 补 ident_ver 成十一键+I1 断言钉死） | ✅ |

**latch_fire/fork REVOKE PUBLIC**（偏差 #10）：plan §3.8 草案 REVOKE 清单确漏两 DEFINER 面（CREATE FUNCTION 默认授 PUBLIC EXECUTE——DEFINER 面漏 REVOKE=越权面）；实施补上且 gate A6 proacl 负向抓获。裁定：实施修复 plan 草案缺陷，正确。

**invoker 链 ACL 补全**（偏差 #11）：OR REPLACE 后 prefix_identity/context_required/render 体内新增子函数调用（generation_effective/ident_ver/render_wire/render_section_body），既有 resolve/recall 的 INVOKER 执行权会因新子函数无 EXECUTE 断裂——按 manifest identity 族授予形态镜像补三角色，防上游行为回归。正确且必要（A6 resolve 保留 identity 族实证）。

### 2.3 A–I 断言强度（1:1 可红？恒真/covered-by/伪链路扫描）

- **恒真扫描**：`check(` 全检索逐条过目——**零恒真占位**（与 dp7 对照：P2-1 类占位无）；`fails_with` 均带 needle+多数带 pgcode，期望失败未抛即 AssertionError（不存在「失败未发生仍过」形态）。
- **B2 并发双连接**：threading.Barrier+两真实连接同 (sid,name) 异值 fire→恰一行（count,count DISTINCT)=(1,1)+两连接回读同值。红性：无 sessions 锁/无 ON CONFLICT 回读⇒双行或线程异常（results 缺键即炸）。
- **E 组**：E1 逐字节（内容剥 replay 键——replay 块在 replay() 语义下必然覆写，剥键是「与父逐字节相同」的正确读法）+forked 身份对（parent==child==artifact 冻结值）；E2 三 kind spawn_kind/payload/指针三面互异；E4 四负向（post-freeze latch/tools bump（SAVEPOINT 保护回滚）/overrides+exact/cutoff 过覆盖 artifact 落新 goal）全 V3008+子行计数零；E5b 无 overrides fresh==父 artifact 身份（确定性 fixture，合法相等的正面钉死=L4 P1-2 落地）。
- **F 组**：F1 恰一条（expected==est_f 实测值/actual==0）；F4 伪造 wire_digest 与 estimate_gap **叠加恰两条**（顺序断言）；F5 三表计数+result 行级对照；F6 complete 后真 settle 换指针→probe 仍读旧 artifact est（result 锚非指针）。
- **G 组**：G2/G3 双向（同值 true/差异 false——G3 差异经 budget 真咬装箱裁段构造，非手改投影）；G5 streak 窗口布尔聚合+归零（专用 name/version 99 免回滚；直插 events 为纯查询语义测试，observe 真事件路径由 G2/G3 覆盖）；G6 flip=C4 同链复测+auto-flip 源码缺席。
- **I 组**：I1 十一键 string_agg **恰等**+逐键非空；I3 mv3 拒 v2 形状（V3003）+手落 legacy v2 artifact 逐字节回放（exempt 路径）；I5 前缀源扫描零 periphery 对象；**I6 真语料链路**：tool effect→claim→complete→`v13_ingest_document` 真实摄取→settle→manifest candidates==live recall 输出（剥 decision_id 增键，非空）→已决候选 decision_id 非 NULL→judgments final_action==live `v13_chunk_filter_action` 真值（非占位）。
- **伪链路**：未发现 covered-by 对照（H5 两态独立调用、F2/F6 独立 effect、G3 对照经真差异源）；fixture 全走真实链路（refresh settle/claim/complete/append_event/policy 翻版仪式）。

### 2.4 十八条自报偏差逐项裁定（README 台账）

| # | 偏差 | 裁定 | 依据（评审者独立核） |
|---|---|---|---|
| 1 | 换体七复制源=13 号终态（plan 表格 12 号） | **ACCEPT** | §2.2 diff：13 号 refresh v3 本体=12 号 v2+belt；最新形态规则正文优先于表格快照 |
| 2 | 锁集七名（保 summary_accept+增 render_policy） | **ACCEPT** | diff 实证七名；plan 字面六名会删 summary_accept 削弱 DP7 belt——合并是「同缝扩展」意图的正确读法 |
| 3 | blob_land 三参 DROP+CREATE；system_block 直插 | **ACCEPT** | OR REPLACE 加参=重载双定义陷阱；既有调用点经 DEFAULT 零改动；ACL 重授（§3.8+gate A6） |
| 4 | goal_hash INTO 标量化 | **ACCEPT** | record 字段不可作 INTO 目标（PG 语法事实）；语义零变化；plan 自注机械自检类 |
| 5 | shadow_streak 用 events.at | **ACCEPT** | events 时间列=at（dp7 economy 台账同款列名修正先例） |
| 6 | intent_gate 对齐加载态（thresholds policy_name/version；DP5 纯文本段数组⇒段首码位） | **ACCEPT** | 亲核 v13_core.sql thresholds 列名+v13_routes join 同式；v13_recall.sql v13_query_segments 返回 jsonb 文本段数组（单类游程，仅非 sep 段入列）且五码位区间逐组相同——首字符判段类=段类，零第二分词成立 |
| 7 | PG18 词法（'['::text 消歧/括号） | **ACCEPT** | 在文件；plan 附 B 类型算子层纪律同向 |
| 8 | A5 纸面检查点 34/104/97/bare7 | **ACCEPT（附注记）** | 独立重算恰等；**注记**：bare 7 的归因标签笔误（实为 context_required×4+refresh×2+blob_land×1；台账写 ×3+validate×1——validate 全部带 ERRCODE）。计数断言本身正确，P3 文档级 |
| 9 | A12 files_cutoff 不落列 | **ACCEPT** | plan v2 节自述「执法侧立法、不改 SQL 字面」+「不适用」；v13 无 file pointer/epoch/git tips 数据源；SQL 内注记+README 台账双在档 |
| 10 | latch_fire/fork 补 REVOKE PUBLIC | **ACCEPT** | §2.2 专项核；plan 草案缺陷由 gate 负向抓获后修——正确闭环 |
| 11 | invoker 链 ACL 补全 | **ACCEPT** | OR REPLACE 引入子函数调用的必然伴随；防 resolve/recall 既有权断裂；A6 实证 |
| 12 | est=已落地 blob 段 | **ACCEPT** | receipt 体读 artifacts 回取段体（与 wire 同源）；首次装配当前材料未落不计——「新字节不命中缓存」语义自洽；F 组两步 settle 构造窗实证；纯审计面无正确性影响 |
| 13 | generation 翻版×pricing 耦合（同批补 v13_pricing） | **ACCEPT** | C2 fixture 实证：新 model 无定价行⇒er.e_base NULL⇒validate V3007 fail-loud；README ③ 运维流程入档（fail-loud 方向正确，纪律呈报） |
| 14 | I6 fixture 对齐（decision_id 增键剥键/64hex request_hash/模板行） | **ACCEPT** | 在 gate；DP5/DP6 上游形态的对齐项 |
| 15 | I4 形态=装载切片+上游在场；13 gate 复跑为 gate 外仪式 | **ACCEPT** | AGENTS.md 前置条件结构使然；控制器已核 14 gate 全绿（本轮已验证事实） |
| 16 | 纸面计数 40/23 零重复/$$ 配平 | **ACCEPT** | 机械重数恰 40/23/0/配平（评审者脚本复核） |
| 17 | G3 差异经 budget 真咬 | **ACCEPT** | gate 实文核（budget_tokens 64 装箱裁段→sections 真差异） |
| 18 | C6 负向需未 pin 会话 | **ACCEPT** | OQ2 语义正面证据（pinned 由 latch 兜底不读活动行）；gate 用新会话（未 pin）实测 |

**18/18 ACCEPT，无隐性偏差遗漏**（评审者另独立扫描：render_policy 守卫从 13 号弱形（renderer 非空串）强化为三条件词表=plan (a) 指定增量；probe/observe/fork 全部新 RAISE V3008；策略种子单字面量纪律；`v13_render_wire` 第三参 DEFAULT 非重载——均与 plan 一致或为授权增量）。

### 2.5 附 A #1 交叉核实（plan 循环终检项）

**文件 14 的 token 键谱恰十一键**：`v13_context_required` jsonb_build_object 逐键清点={sem,dec,goal,tools_rev,asm_ver,jdef_ver,gen_ver,corpus,recall_ver,econ_ver,ident_ver}，gate I1 以 string_agg 字典序恰等断言（`asm_ver,corpus,dec,econ_ver,gen_ver,goal,ident_ver,jdef_ver,recall_ver,sem,tools_rev`）+逐键非空。**同时核实**：corpus/recall_ver 在 12 号实施文件内已在场（turn 34 源头修复）——DP7 的回归已先于本 plan 在实施侧闭合，本 plan 补 ident_ver 成十一键+I1 钉死；**DP7 plan 文本的「键集 7→8/八键」措辞与实态不符**，属文档侧残留，应入终局 erratum 清单（见 §6）。

---

## 3. 发现清单

**P0：无。P1：无。P2：无。**

| # | 级 | 位置 | 发现 | 建议 |
|---|---|---|---|---|
| N-1 | P3（注记） | `test_periphery.py` A5 注释 / README 偏差 #8 | bare-RAISE 归因标签笔误：实为 context_required×4+refresh×2+blob_land×1；台账写「context_required×3+validate×1」（validate 全部带 ERRCODE）。计数断言（104/97/7）本身正确 | 终局 erratum 记一行即可（可选顺手改注释） |
| N-2 | P3（注记） | turn 14 行/dp7 L4 评审 vs `8c31ccb` 提交信息 | summary gate PASS 计数记录出入：dp7 时点记录「228」，本提交「基线实跑 227+净增 1=228」——静态调用点 176→177 证净增 1 成立，则 dp7 时点实跑应为 227，两处记录有一处 off-by-one（记录层，非代码层） | 终局全量复跑以实跑数钉死；erratum 记一行 |
| N-3 | P3（注记） | `v13_periphery.sql` refresh v4 守卫块 | 外围行（latches/cache_probe 等）值转型失败落入共享 EXCEPTION 处理器→报 V3007「economics policy rows malformed」（标签错位，fail-loud 方向不变）——DP7 judge_spend_gate/fastpath_tiers 同块先例 | 台账已含（结构继承）；如需精确标签可后续把 [DP8] 守卫拆独立 BEGIN/EXCEPTION（不必须） |
| N-4 | P3（已记档） | receipt est | 首次出现段（prior_missing⇒churn=0）当次 settle 不计 est（blob 未落）；下一 settle 起计入——README #12 已实证记档，纯审计无正确性影响 | 无动作（台账在档） |
| N-5 | P3（已记档） | blob_land system_block 分支 | 同哈希重落可产生多行（无 partial unique 索引；join 按哈希+digest 按列表序，无害）——README #3 已记档 | 无动作（台账在档） |

---

## 4. 裁定

1. **`8c31ccb`：PASS**——dp7 L4 P2-1/2/3 三项全部真闭合（真断言/可红/去重/无静默），SQL 零改动，gate 复跑绿。dp7 遗留测试层尾巴清零（P2-4 为可选项，dp7 已裁定记台账即可，维持）。
2. **`69e5ebb`：PASS**——dp8 全规格落地保真：§3 九面全部在档且强断言；换体纪律（复制源=最新形态/七名锁集/ACL 补洞）三处裁量全部正确且必要；A–I 128 checks 无恒真/无伪链路；18 偏差 18/18 ACCEPT；0 P0/0 P1/0 P2（5 条 P3 级注记，其中 2 条建议入 erratum、3 条已台账在档）。
3. **dp8 收官：是**——第 14 号 stage 交付完整；附 A #1 主呈报项（token 十一键谱恢复）兑现且 I1 钉死；F9/F13 消解在档；触点 1 纯消费 DP7 契约声明在档。**v13 十四 stage 全部落成。**
4. **可否进终局：可。** 建议终局清单：
   - 全量复跑 14 gate（顺带以实跑数钉死 N-2 的 summary 计数出入）；
   - erratum 汇总呈报，并入：①E-DP7-1/E-DP7-2/C-DP7-M1 三条（dp7 评审 §6 遗留）；②**DP7 plan 文本 token 键谱措辞**（「键集 7→8/八键」与 12 号实施实态十键/14 号十一键不符——附 A #1 文档侧残留）；③N-1（A5 归因标签）与 N-2（PASS 计数出入）各一行；④dp7 P2-4（guard 规则 3 孤儿 trace 深度，已裁定记台账）维持不动。
5. **回退条件核对**：无弱化断言假绿痕迹（本轮独立 diff 四换体+计数重算+调用点计数三方交叉，均与自报一致）。

---

## References

- plan：`docs/plans/v13-dp8-periphery-p1-plan-2026-09-20.md`（§1.3 OQ1–OQ9/§3.1–3.8/§4 A–I/附 A/附 B/v2 对齐修订/L4 修复）
- dp7 修复权威：`docs/reviews/v13-dp7-impl-l4-review-2026-09-23.md` §5 修复清单
- 实现：`v13/periphery/v13_periphery.sql`（2382 行）/`test_periphery.py`（1555 行，128 checks）/`README.md`（六条运维纪律+契约声明+18 项台账）/`setup_db.py`；`v13/load.py` 第 14 位
- 复制源加载态：`v13/summary/v13_summary.sql`（13 号）/`v13/economy/v13_economy.sql`（12 号）/`v13/manifest/v13_manifest.sql`（6 号）/`v13/schema/v13_core.sql`（thresholds）/`v13/recall/v13_recall.sql`（分段器）
- 背景：`prompt-exports/loop-orchestrate-v13-deep-plans-impl-runs.md` turn 14 行（turn 15=本轮）

---

## 5. Oracle 复核（2026-09-23 追加；本节修订 §0/§4 部分结论）

> **渠道如实记录**：首次 `ask_oracle`（mode=review）调用返回 `MCPToolExecutionCancelledError`（与本日 ACP 故障先例同型），重试成功。oracle 三角返回两份独立意见（grok-4.6 @xhigh / grokBuild grok-4.7-build-fast-xhigh），**分歧显著**：前者「维持原判」+3 条 P3 补充（E-DP8-1/2/3）；后者主张推翻「0 P1/0 P2」并提出 4 P1+4 P2+3 P3。评审者对每条主张逐条实证（read_file/git/grep + PG 语义推演）后裁定如下。
>
> **本节修订 §0/§4 的结论**：`69e5ebb` 发现计数由「0 P0/0 P1/0 P2+5 P3」修订为 **0 P0 / 1 P1 / 3 P2 / 8 P3**；dp8 收官由「是」修订为**附条件**（先修 P1）；「可进终局」修订为**修复提交+定向复跑后可**。`8c31ccb` PASS 不受影响。

### 5.1 逐条实证裁定

| Oracle 主张 | 提出者 | 实证核验 | 裁定
|---|---|---|---|
| **P1-1**：latches 表权限缺 resolve/recall——6 号（manifest.sql:930-935）把 `prefix_identity/context_required/latch_digest/assemble_manifest` EXECUTE 授给 route/resolve/recall；14 号换体后这些 **INVOKER** 函数经 `v13_generation_effective/latch_digest/ident_ver` 读 `latches`（4 个 DEFINER 仅 latch_fire/fork/refresh/blob_land），而 latches 只授 route SELECT（:2342） | grokBuild | **CONFIRMED（代码级）**：`SET ROLE v13_resolve/v13_recall; SELECT v13_prefix_identity(sid)` → `permission denied for table latches`。偏差 #11「invoker 链补全」只补了子函数 EXECUTE、漏了表 SELECT 半边——OR REPLACE 打断了 6 号既有授予的**运行时**能力。gate 不可见：全部 gate 以 owner 跑；A6 对 resolve 只查 `has_function_privilege` 权限位（位为 True，链断在表权限） | **采信，P1**。修复=一行 `GRANT SELECT ON latches TO v13_resolve, v13_recall`（只读，符合两角色设计）+A6 增 resolve 真执行断言（非权限位） |
| **P1-2**：system_block 无 ON CONFLICT 直插+render/守卫的 `jsonb_array_elements LEFT JOIN artifacts ON content_hash` 扇出——同正文双落（如客户端超时重试）后按 README ③ 顺序算 digest（join 同款扇出）→ digest 与重复一致 → 守卫过 → wire.system 同块出现多次、身份冻结该重复 | grokBuild | **CONFIRMED**（:451-456 join+agg 扇出、:2318-2329 直插分支）。注意守卫可抓「digest 先算、重复后落」序（重算≠存值 V3008）；漏的是「重复先落、digest 后算」序（README 规定顺序恰是后者）。后果=wire 重复系统块+自洽身份，非存量数据损坏 | **采信但降 P2**：需运维重试误步+规定顺序才触发；修复廉价（`(content_hash) WHERE kind='system_block'` 部分唯一索引+ON CONFLICT DO NOTHING）。我报告 N-5「无害」**撤销**——对 system_block 聚合路径不成立（context_section 有 ON CONFLICT 无此面） |
| **P1-3**：fork 子会话 `v13_render` 的 goal 臂 `WHERE g.session_id=p_sid AND g.seq=payload_ref.seq`——继承 manifest 的 goal 段 seq 是**父会话**命名空间 → 子会话查无行 body=NULL → 子会话重算 wire_digest≠artifact 冻结值（blob 段按哈希不受影响） | grokBuild | **CONFIRMED**（:437-442 goal 臂 session 限定；goal_hash 换体四走链而 render_section_body 不走）。但 plan OQ4 的「子会话 v1 语义=spawn+replay 壳」只承诺 replay 逐字节/审计/probe，**未承诺子会话 render**；v1 子会话无 llm 无 worker 调用面 | **采信但降 P2**：激活缝债（fork turn-runner 落地日必炸：worker 按 README ② 契约调 `v13_render(sid)`），违背附 A #12「(manifest+blobs+render 版本) 三元组可重现」的跨会话读法。修复=goal 臂走 goal_hash 同链（自身无行上行父层 seq≤cutoff）+激活包补「子 render==冻结 wire_digest」gate |
| **P1-4**：generation 守卫仅在 digest≠'-none-' 时做 blob 在场+实算比较——非空 system_blocks 配 '-none-' 过形状检查、跳过比较 → 身份称 '-none-' 而 wire 有真块（不同系统块配置共享前缀身份=缓存碰撞面） | grokBuild | **CONFIRMED**（守卫块 `IF ... IS DISTINCT FROM '-none-' THEN` 包裹）。种子行自洽，仅手写运维翻版可触发；fail-open 于本应 fail-loud 的守卫 | **采信但降 P2**：dp7 P2-4 同类（防御纵深缺口、装配器/种子结构性产不出）；修复=『-none-' 仅当数组长度 0 放行』一行 |
| **P2-A**：probe 仅 wire_mismatch 且 usage 缺/容差内时——事件已落、返回仍 `{event:false}`（`event:true` 只在 gap 分支 RETURN）；F4 因同时触发 gap 未读返回值 | 双方（grok-4.6=E-DP8-2 P3；grokBuild=P2） | **CONFIRMED**（probe 体两 PERFORM 后仅 gap 分支带 event:true 返回） | **P3**：v1 无返回值消费者（纯审计）；一行修复（任一事件写过即 true）+F4 伴生断言。erratum 记 E-DP8-2 |
| **P2-B**：streak=窗内 true 计数非尾部连续长度；G5 第二态 streak==9（最新 false 时尾部连续=0）、「归零」的只是 ready | grokBuild | **CONFIRMED**（`count(*) FILTER (WHERE eq)` 实现+gate 期望 9 双向一致）。plan G5 原文自注「(最近窗布尔聚合)」——实现与 plan 自洽，字段名易误读 | **P3**：ready 是唯一消费门且语义正确；README 钉字段定义或改尾部连续式。**我报告 §2.3「streak 归零」措辞不准，勘误**（归零的是 ready）。erratum 记 E-DP8-3（含 streak 按 (name,version) 全局聚不按 sid 的串窗注记——v1 仪器语义，人审前需按会话过滤） |
| **P2-C**：N-3 升 P2（外围行转型失败落 V3007『economics』handler） | grokBuild | 事实 CONFIRMED（共享 EXCEPTION 块）；但 DP7 对 judge_spend_gate/fastpath_tiers 同块同款先例、fail-loud 方向不变 | **维持 P3**（结构继承+呈报分歧；如需精确标签拆独立 BEGIN/EXCEPTION） |
| **P2-D**：settle 内联首发与 fork 复制均不计 admission 上限——先 16 枚 public fire 再首 settle ⇒ generation 成第 17 行；已 settle 会话的公开配额实际 15 非 16；fork 复制亦无上限检查 | grokBuild | **CONFIRMED**（refresh 内联 INSERT 无计数；fork 复制无计数）。有界：每会话至多 17（public fire 在 ≥16 即拒，fail-closed 方向）；plan §3.7(b)/OQ2 未规定内联路径计额，risk 7「父集≤cap」假设被 17 打破一档 | **P3**：有界+安全方向+配额语义微瑕；台账记「generation 是否占额」的语义澄清项 |
| **P3-A**：latch value 可携文件字节/路径无探针（A6 输入闭集） | grokBuild | 属实；plan v2 明文「后续若加探针，只加不减」 | **采信 P3**（计划内残留，登记） |
| **P3-B**：A6 proacl 负向把 NULL 当未授——漏 REVOKE 时 proacl=NULL（默认 PUBLIC EXECUTE）经 coalesce '{}' 不命中 → 假绿；且五函数中仅 3 个有 resolve 真负向覆盖 | grokBuild | **CONFIRMED**（当前库内 REVOKE 均已执行故无活洞；系测试健壮性缺口） | **采信 P3**：修=去 coalesce 或对 NULL 判 default-EXECUTE；fork/observe 补 SET ROLE 负向 |
| **P3-C**：我报告 §2.1「SQL 全文无 compact_hint 生产面」措辞错——14 号 assemble 的 hint CTE 在产 compact_hint（13 号机械复制件） | grokBuild | **CONFIRMED** | **勘误**：正确表述=「零**新增** hint 代码，hint CTE 为 13 号机械复制（DP7 机制），触点 1 纯消费成立」 |
| N-4 机制精确化：首 settle 时 churn=0 段 body 读空（非整段不计——id 包装字节仍计） | grokBuild | 属实（低估计入 id 包装） | 措辞精确化，分级不变 |
| 8c31ccb P2-2/P2-3「不背书」 | grokBuild | 材料缺口所致（oracle 仅见 test_summary 切片）；评审者已对 `git show 8c31ccb` 全 diff 亲验（§1） | **以 §1 实证为准，维持闭合判定** |
| A12「对齐完成」表述偏满 | 双方（grok-4.6 亦提） | 属实：v1 按 plan 授权延期，但 §2.1/偏差 #9 的 ✅ 易读成「文件世代执法已落地」 | erratum 记 E-DP8-1：『立法登记≠列/执法落地；exact/recompute 的 files_cutoff 冻结与 fresh 新 cutoff=R0a 激活缝，v1 fork 行无物理锚』 |

### 5.2 修订后发现清单（替代 §3）

**P0：0。P1：1。P2：3。P3：8。**

| # | 级 | 位置 | 发现 | 修复 |
|---|---|---|---|---|
| **F-1** | **P1** | `v13_periphery.sql` ACL 段（:2341-2342） | latches 表 SELECT 未授 v13_resolve/v13_recall——6 号授予的 identity/assemble 族 EXECUTE 在 14 号换体后运行时断裂（INVOKER 链读 latches 被拒）；gate 全 owner 跑+A6 权限位检查双盲区 | **必修**：`GRANT SELECT ON latches TO v13_resolve, v13_recall;` + A6 增 SET ROLE 真执行断言（resolve 真调 prefix_identity 空/未 pin 会话） |
| F-2 | P2 | blob_land system_block 分支+render_wire/守卫 join | 同哈希双落（运维重试）扇出重复进 wire 与身份（自洽）；『-none-' 与重复序两漏洞互补 | `(content_hash) WHERE kind='system_block'` 部分唯一索引+ON CONFLICT DO NOTHING（或聚合前 DISTINCT） |
| F-3 | P2 | `v13_render_section_body` goal 臂 | fork 子会话 render 的 goal 正文读空（session 限定不随链上行）→子 wire_digest≠artifact 冻结值；激活缝日 worker 契约即断 | goal 臂走 goal_hash 同链；fork 激活包补「子 render==冻结 wire_digest」gate |
| F-4 | P2 | refresh generation 守卫 | system_blocks 非空+digest='-none-' 过守卫（fail-open）→身份与 wire 失配（缓存碰撞面） | 『-none-' 仅当数组长度 0 放行 |
| F-5 | P3 | `v13_cache_probe` 返回值 | 仅 wire_mismatch（usage 缺/容差内）时事件已落而返回 event:false | 任一事件写过即 true；F4 伴生断言（erratum E-DP8-2） |
| F-6 | P3 | `v13_shadow_streak` | streak=窗内 true 计数（非尾部连续）；全局按 (name,version) 聚不按 sid | README 钉字段定义/人审按会话过滤（erratum E-DP8-3） |
| F-7 | P3 | refresh 守卫共享 handler | 外围行转型失败报 V3007『economics』（标签错位，fail-loud 不变） | 可选拆独立 BEGIN/EXCEPTION（=原 N-3，维持） |
| F-8 | P3 | settle 内联首发/fork 复制 | 不计 admission 上限（有界 17、fail-closed 方向；已 settle 会话公开配额实际 15） | 台账澄清 generation 占额语义 |
| F-9 | P3 | est 首现段 | 首 settle 低估（body 读空、id 包装仍计）——原 N-4 措辞精确化 | 台账在档（README #12） |
| F-10 | P3 | A5/README#8 归因标签 | bare 7=context_required×4+refresh×2+blob_land×1（非 ×3+validate×1）——原 N-1 | erratum 一行 |
| F-11 | P3 | PASS 计数记录 | turn 14 记 228 vs 本轮基线 227（记录层 off-by-one）——原 N-2 | 终局全量复跑钉死 |
| F-12 | P3 | A6 proacl 检查 | NULL proacl 语义洞+fork/observe 无 SET ROLE 负向 | 修 coalesce 语义+补两负向 |
| F-13 | P3 | latch value 输入闭集 | 文件字节/路径可进 value（无探针；plan 授权后置） | 激活日加探针（只加不减） |
| — | P3 | 本报告 §2.1 措辞 | 「无 compact_hint 生产面」→「零新增 hint 代码（13 号复制件在产）」；§2.3「streak 归零」→「ready 归零」 | 本节已勘误 |

### 5.3 修订裁定（替代 §4 条 2-4 的相应部分）

1. `8c31ccb`：**PASS 维持**（oracle 无实质反驳；P2-2/3 的「不背书」系其材料缺口，本报告 §1 已全 diff 实证）。
2. `69e5ebb`：**实质 PASS、收官附条件**——架构/换体纪律/断言强度/18 偏差裁定全部维持；但 **F-1（P1）必须先修**（一行 GRANT+A6 真执行断言），**建议同批顺手 F-2/F-4（各一行级）与 F-5（一行）**，F-3 登记进 fork 激活缝清单（§1.4 工作包）。
3. **dp8 收官：附条件达成**——修复提交（`v13: close dp8 L4 P1 ACL + P2 guards` 类）+periphery gate 复跑绿后即收官；修复面为 ACL/守卫小改，不触冻结面，上游 gate 结构性零影响（I5 边界不动）。
4. **可进终局：修复提交后可。** erratum 清单在 §4 原单基础上并入：E-DP8-1（A12 立法≠落地）/E-DP8-2（probe 返回值）/E-DP8-3（streak 语义与全局窗）/F-10/F-11/F-12 各一行；DP7 plan 键谱措辞与 E-DP7 三条维持。
5. 复核程序注记：本轮为「评审→oracle 双审→逐条实证」三层；oracle 分歧的两端（全维持 vs 全推翻）均未被整份采信，最终分级以代码级实证为准——F-1 为双盲区（owner 跑 gate+权限位检查）实例，记入 loop 教训：**ACL 类验收必须含 SET ROLE 真执行，权限位断言不充分**。

---

## References（Oracle 复核增补）

- Oracle 渠道：ask_oracle mode=review（首次 MCPToolExecutionCancelledError，重试成功）；两意见全文存档于会话记录
- F-1 实证：`v13/manifest/v13_manifest.sql:930-943`（6 号 EXECUTE 授予）/`v13/schema/v13_core.sql:854-856`（表 SELECT 基面）/`v13/periphery/v13_periphery.sql:2341-2342`（latches 仅 route）/DEFINER 清单（:277/:314/:1949/:2311）
- F-2 实证：`v13_periphery.sql:451-456`（join 扇出）/`:2318-2329`（直插分支）/守卫 digest 重算块
- F-3 实证：`v13_periphery.sql:437-442`（goal 臂）对照换体四 goal_hash 链式
- F-4 实证：refresh 守卫 `IS DISTINCT FROM '-none-'` 包裹块
