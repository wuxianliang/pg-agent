# v13 DP1–DP8 终局交叉覆盖检查报告

> 日期:2026-09-21。执行者:父级 Loop Orchestrate Turn 33(终检迭代,只读核查+报告)。
> 对象:八份已验收 plan(`docs/plans/v13-dp1…dp8…-2026-09-20.md`,合计约 13,000 行)+ 冻结设计稿 `docs/designs/v13-context-on-pg.md`(2026-09-19 v2,487 行)。
> 输入:loop memory(`prompt-exports/loop-orchestrate-v13-deep-plans-runs.md`,turn 0–32)。
> 方法:全量通读九份文档 + 机械搜索;每项结论附证据(`文件 §节:行` 或 gate 编号);疑似缺口先复查「不做/台账/实施期」清单后定性。
> 结论预览:**覆盖矩阵无缺口、无重叠;换体链发现两处 P1(plan 文本级一致性/盲区,均与 DP7 的复制源字面有关,其一已被 DP8 呈报并在 14 号修复,另一处为本轮新确认);gate 总账九条全归属;loop 已达 success 判据,建议附两条一行级修订后收口(或记遗留清单交实施期)。**

---

## 检查 1 · §4–§14 normative 覆盖矩阵

设计稿 §4.1–§4.8 / §5.1–§5.6 / §6.1–§6.7 / §7 / §8 / §9 / §10(G-ctx1–9)/ §11 / §12 / §13 / §14 逐条核对的归属与落点:

| 设计 § | normative 要点 | 归属 DP | 落点(证据) | 状态 |
|---|---|---|---|---|
| §4.1 召回是函数+三禁+canary+受限 compiler+排序 | P0 绑定纪律 | DP5 | 三禁=DP5 不变量 2+gate G/K/R(归一化扫描口径 §4 断言纪律);构造器 OQ7(v13_query_segments/v13_build_tinql/v13_tinql_terms);canary OQ6(专用表);排序不变量 5;G-ctx3 四断言映射表 | 覆盖 |
| §4.2 chunks 三纪律 | P1 | DP4 | 行自证 OQ1(v13_body_hash,附 A #3 载体化);重摄取同事务 §3.3;外部只记 hash=gate C 组;rebuild 保护式重灌 OQ2(附 A #2,字面 truncate 被 F3② 取代);G-ctx2 五断言(A/B+E/E+D/G/H) | 覆盖 |
| §4.3 两阶段 advance+角色分裂+双速+快照复核 | P0 | DP1 | §3.3 v13_resolve_judgments/§3.4 v13_parse/§3.5 v13_advance;三角色 ACL(M1-7/M2-10/M3-12);G-ctx1 五断言 M4;G-ctx8 解析相=M4-K1;快照复核=probe 七键+M3-8/9/18 | 覆盖 |
| §4.4 三层记忆栈 | P1 | DP6(memory stage) | 结构化层=ix_decisions_question_stannum(OQ9);逐字层=transcript_chunks+水印 OQ5/OQ8;分区分索引=独立表(消费清单 #17);远程层=§4.4 明文「不实现」;p99=gate L 组 | 覆盖 |
| §4.5 过滤管道 | P1 | DP6(filter stage)+DP2 | 存在性 Noul 先行=OQ4/F2 立法(v13_existence_ref+candidates_digest,gate C 组);per-chunk Score=OQ3(signal 差分+v13_filter_ref);跨 session=DP2 judgment_cache/reused_from(G-ctx4-3=D2);G-ctx4 三断言 C1/C2/D1/D2;§4.5/§6.5 张力按特别法(附 A #5 呈报) | 覆盖 |
| §4.6 CJK 构造器+bigram 台账 | P1 | DP5 | OQ7(CJK 语段整体短语引用+全引号文法);kohaku fixtures=gate A3/P4;bigram=§7 台账(独立列引擎佐证已实测) | 覆盖 |
| §4.7 高亮跨度装配+chunk 尺寸解耦 | P1 | DP3+DP4+DP5 | spans 形态立法=DP3 OQ4(candidates.spans doc=content_hash);生产者=DP4 OQ6(v13_extract_spans/v13_span_unit/v13_assemble_spans,Oracle 2 四配置=gate I 组);换体=DP5 extract v2(stannum highlight 哨兵,签名/输出冻结=DP4 契约④);尺寸数据答案=DP5 Q 组 | 覆盖 |
| §4.8 刻画 stage | P1 | DP5(characterize stage) | 承重件不依赖 stannum=不变量 7+双 stage OQ2;刻画 gate 六件=K–R 组;runbook 六件=R4;作用力 2 未复现=附 A #1 呈报(实测记档) | 覆盖 |
| §5.1 latch/emergent | P1/P2 | DP8(+DP3 stub 缝) | latches 表+OQ8(INSERT once/admission 非轮 2 CHECK/F13 并发首触发,gate B 组);latch_digest 换体一;emergent=P2 各 plan §7 | 覆盖 |
| §5.2 manifest=IR | — | DP3(+DP5/DP6/DP7 填充) | OQ4 schema(10 外层键/9 section 键);applied/skipped 双分支=transform 两形态(C 组);三回放=OQ5+D 组;查询侧字段族=OQ4(candidates 四键)+DP5 填充(E 组)+DP6 decision_id(F 组) | 覆盖 |
| §5.3 canonical render | 轮 2 裁决 6 | DP7(策略行)+DP8(本体) | render_policy v1 行=DP7 §3.1 种子;函数族三件=DP8 OQ3(v13_render_wire/receipt/render);呈现偏好不立法=DP8 §7 | 覆盖 |
| §5.4 经济(tier/R_o/E(r)/归因) | 轮 2 综合 | DP7 | tier 带 OQ4(轮 2 P0 单调/hysteresis);R_o OQ3(分位+空桶冷启动 fail-safe);E(r) OQ5(v13_pricing+r 三纪律);cache-break 归因=v13_cache_breaks(gate F 组);G-ctx6 按轮 2 修正语义绕行 | 覆盖(G-ctx6 措辞=设计侧遗留,见检查 6) |
| §5.5 反馈统计 | — | DP7 | 失败样本排除=R_o status='succeeded' 谓词+usage 数值防御(gate B2/B5);worker 契约=llm result 携 usage+model(附 A #3) | 覆盖 |
| §5.6 ForkPrefix+shadow | — | DP8 | fork 三种 spawn+validate-spawn+链回走继承=OQ4(gate E 组);cache probe=OQ5(F 组);shadow=OQ6(双跑/streak/人审 flip,G 组);会话树读穿透=激活缝(附 A #3) | 覆盖 |
| §6.1 三 epoch+freeze+四件 | 轮 2 P0 | DP1+DP2+DP3 | 三 epoch=DP3 OQ7;manifest freeze=DP3 OQ3(语句快照+settle 三层锁);快照复核=DP1;版本化路由=DP2(shadow 面)+DP3(exact replay);信封固定=DP1/DP2 | 覆盖 |
| §6.2 六触点 | 轮 2 裁决 8 | 触点1:DP7;触点2:DP7;触点3:砍;触点4:P2;触点5:DP8;触点6:台账 | 触点1=economics.compact_hint(C6 gate,DP8 纯消费=附 A #5/DP7 附 A #9 已裁归属);触点2=summary stage OQ2/OQ8;触点5=DP8 OQ7(H 组,零新调三重执法);3/4/6=各 §7 | 覆盖 |
| §6.3 采样纪律 | P2 | — | DP7 §7 效用遥测不做(触发=反事实评估) | 台账 |
| §6.4 摘要验收回退链八步 | P1 | DP7 | 步1 预算包=OQ6/J3;步2 生成=OQ2 prepare;步3 检查先行=v13_summary_checks(K 组);步4 缓存或一次 Noul=OQ8(L 组);步5 重生成=M 组;步6 固定链三级=O3;步7 CJK=N 组;步8 措辞=O6 | 覆盖(八步逐一) |
| §6.5 判断信封+分片哈希 | — | DP2 | 六件=§2 映射行;分片哈希执法机械+生产全量=OQ4(附 A #4 解读呈报);G-ctx7=C 组四断言 | 覆盖 |
| §6.6 shadow 重路由 | — | DP2 | v13_shadow_reroute(§3.7)+D 组;与 DP8 OQ6 分工(judgment 阈值面 vs assemble/render 策略面) | 覆盖 |
| §6.7 不整合清单 | — | 各 | 生成 IO 在 worker=DP1 不变量 2;answer 不进键/组合置信度=DP2 不变量 3+D5;Jev 覆盖结构校验=β 先行;迟到回写=artifacts append-only;tier/cache scope/marker=DP7 不变量 5;在线 learned policy=DP8 auto-flip 拒 | 覆盖 |
| §7 T0/T1/T2 | — | DP5 | T0 两代=双 stage(recall 第 8 位/characterize 第 9 位);T1/T2=§7 台账(形态照抄) | 覆盖 |
| §8 扩展取舍+元原则 | — | DP1/DP4/DP5 | pg_cron=DP4 OQ7 自辩三条+verify 夜跑、DP6 tick 投影;pg_jsonschema=DP2 OQ3/DP3 OQ6 推迟(台账,设计侧遗留);pg_net/pgsql_http P0 排除=DP1 §7 红线+DP6 §7;stannum runbook=DP5 R4;psql_bm25s/timescaledb/age/vectorchord=台账 | 覆盖 |
| §9 表结构增量 | — | 各 | chunks=DP4(§9 七列+chunk_offset/body_tsv,附 A #1);transcript_chunks=DP6;latches=DP8;judgment_templates=DP2(两表形态);manifest=DP3 artifacts;策略行=v13_policies 载体逐 DP 追加(recall_boosts=DP5 空行留缝;filter 批上限载体=信封 budget 冻结值,DP6 消费清单 #7 注记——载体裁量,非缺口) | 覆盖 |
| §10 G-ctx1–9 | — | 见检查 5 gate 总账 | 九条全归属 | 覆盖 |
| §11 交付排序 | — | 1:DP1/DP2/DP3/DP6;2:DP5;3:DP4+DP5;4:DP7;5:DP8(+DP2 分片机械) | 双 stage 化使「刻画并行→刻画后换体」时序在加载序显式(DP5 §1.1) | 覆盖 |
| §12 YAGNI 台账 | — | 各 §7 | 每份 plan「明确不做」以 §12 为源逐条附触发条件 | 覆盖 |
| §13 教程映射 | — | 各 §6 | ch5=DP1/DP3;ch7=DP3/DP4;ch10=DP3/DP5/DP6/DP7;ch13=DP3/DP6/DP7;ch14=DP3/DP8;ch15=DP6(台账行)+元原则实质面(DP4 OQ7);教程正文零改动=八 plan 共同边界(改教程属后续统一动作,DP1 §6 明示) | 覆盖 |
| §14 轮 2 十问 | — | 并入正文 | 十问裁决全部被对应 DP 承接(1=DP8;2=DP7;3=DP2;4=不做;5=DP7;6=DP7/DP8;7=DP7;8=各;9=各;10=确认) | 覆盖 |

**重叠检查**:同一机制无两 plan 双实现——触点 1 已裁归 DP7(DP8 附 A #5 纯消费);shadow 两平面分工(judgment 阈值=DP2/assemble·render 策略=DP8,OQ6 明示);recall 两表(chunks=DP5 族/transcript=DP6 新函数族);verify 两面(chunks=DP4/memory=DP6);assemble/envelope/token 均为串行换体链非并行实现。**无重叠。**

**矩阵结论:设计 normative 每条有 plan 承接或显式归台账/不做;无缺口。**

---

## 检查 2 · token 键谱总账(v13_context_required 换体链)

沿八 plan 逐环核实(检查清单第 2 项;DP8 附 A #1 扩面):

| 环节 | 键数 | 键集 | 证据 | 判定 |
|---|---|---|---|---|
| DP1 | —(无此函数) | v13_context_fresh 恒 true stub(§1.3 DP3 行留缝) | DP1 §3.5 :1973–1976 | ✓ |
| DP3 | 7 | sem/dec/goal/tools_rev/asm_ver/jdef_ver/gen_ver | DP3 §3.2 :464–497;校验器层 3 键串 :625 | ✓ |
| DP4 | 8 | +corpus(语料代数) | DP4 §3.6 :1246–1288(键 :1281);gate G1 | ✓(七键逐字保留+一处增量) |
| DP5 | 9 | +recall_ver(k 策略版本) | DP5 §3.1 L5 :430–477(键 :472);gate H4/I3 | ✓(八键体逐字复制+一 RAISE 块+一键) |
| DP6 | 9(不触) | 键集零变化;jdef_ver 值域追动(defaults v1→v2);chunk_filter 不入 token(论证=消费清单 #14) | DP6 §1.2 #14;gate F6 | ✓ |
| **DP7** | **8(回归)** | **复制 DP3 §3.2 七键体+econ_ver;丢 corpus(DP4)与 recall_ver(DP5)两键** | DP7 换体一 :459–462「机械复制 DP3 §3.2 加载态原文…键集 7→8」;不变量 8 :179「token 八键」 | **✗ 真丢两键** |
| DP8 | 11(全谱恢复) | DP3 七键逐字+corpus 逐字+recall_ver 逐字+econ_ver(经 v13_econ_ver 单源)+gen_ver(改经 v13_generation_effective,latch 冻结语义)+ident_ver(新,单键合并 latch+render 两追动源) | DP8 换体三 :364–407;gate I1 键串 :1043 `asm_ver,corpus,dec,econ_ver,gen_ver,goal,ident_ver,jdef_ver,recall_ver,sem,tools_rev`(恰 11 键) | ✓ 修复 |

**逐环结论**:
- 「DP7 是否真丢两键」——**是**。DP7 换体一的复制源字面指向 DP3 §3.2(七键体),而非该对象在加载序中的最新形态(DP5 文件 8 的九键体);≥12 号库(economy/summary 两 stage)token 缺 corpus/recall_ver ⇒ 语料变更/召回策略翻版不触发 refresh 的 freshness miss 回归。DP7 自身 gate(E4「token 第八键」)在 12/13 号库内自洽放行;DP4 G1(八键)/DP5 H4(九键)gate 只在其前缀库跑——**前缀库互证不可见**,与 DP8 附 A #1 的判定一致。
- DP8 换体三在 14 号恢复十一键全谱并 gate I1 断言键集;换体五(b) 同步把装配体内 token 归一为单源调用(双写面消除)。**终态库(14 文件)正确**;残留=DP7 文本本身未修正(见 Findings #1)。
- gen_ver 语义变化(DP8 经 latch 内 generation_version,会话级冻结)为显式裁决(OQ2),非回归。
- 附带核实(小项):DP8 换体三草案 sem 谓词 `coalesce(max(seq),0)` 与 DP3 加载态 `-1` 口径差(空会话),DP8 已自旗「实施时逐字对照 DP3 加载态…双保险」(:404–405)——P2 级观察(Findings #3)。

**DP7 12/13 号 assemble 体内 DP5/DP6 增量的存续(前缀库互证盲区,检查清单指定项)**:

- DP5 L7 换体(DP5 §3.1 :562–763):qside candidates ← v13_recall_candidates(goal echo 退役)+`||` 补第四键 decision_id:NULL。
- DP6 墓碑四换体(DP6 §3.1 L7 :1100–1314):rc2/fc 单源 CTE(:1236–1241)、candidates.decision_id 上下文等值 join 填充(:1245–1257)、jud 消费集=候选 decision_id ∪ 存在性行+final_action 真值(:1259–1286)。
- DP7 换体三(:477–498)**字面写「机械复制 DP3 §3.4 加载态原文」**,且增量 (g)「sections/query_side/judgments/replay 块零改」——以 DP3 基线读,则 12/13 号体内 qside 回退 goal echo、decision_id 恒 NULL、jud 回退 final_action='recorded' 占位且无存在性行,即 **DP5/DP6 两级增量在 ≥12 号库的存续无 plan 文本保障**。
- DP7 §3 前言(:226)另有「从上游 stage 文件加载态原文机械复制(比计划文本更权威)」——与换体三的「DP3 §3.4」字面冲突(对 token 同款冲突已被 DP8 附 A #1 证实为真错误)。DP8 §3.7 复制源解析规则(:839–849,「复制源=该对象在加载序中的最新形态」)已把正确规则制度化,其换体链表列出 assemble 链 DP3→DP5→DP6→DP7——**隐含假设 12 号 v2 携带 DP5/DP6 增量**,但该假设只有靠实施者按 DP8 规则(而非 DP7 字面)实施文件 12 才成立。
- **gate 盲区定量**:DP5 E1–E3(candidates=召回集/decision_id 全 NULL/judgments 消费集)只在 8 号库跑;DP6 F1/F2(decision_id 填充/judgments 真值)只在 10 号库跑;DP7 E/O 组断言 economics/三桶/回退链,无一断言 candidates 来源或 decision_id;DP8 I2(:1044)只查 validate v4 词表(kind='summary')+economics 块+render 块。**任何库都不存在「DP5/DP6 assemble 增量在 ≥12 号库存续」的断言。**→ Findings #2(本轮新确认,DP8 附 A #1 只覆盖 token 侧的 corpus/recall_ver,未覆盖本面)。

**信封键谱 DP2 19→DP5 20 逐字**(检查清单指定项):
- DP1 15 键(DP1 §3.2 :1506–1556)→ DP2 19 键(DP2 §3.4 :793–872;gate A9 :1579 逐键枚举;13 键表达式逐字+provider/model 升级 guc_required+4 新键)→ DP3 墓碑二 19 键仅换 goal_hash 表达式(DP3 §3.6 :1301–1392;gate A4 :1478 逐键枚举)→ DP5 20 键(DP5 §3.1 L6 :486–558;gate D1 :1125「19 既有键键集不删不改(逐键枚举)…17 键与 DP2/DP3 形态逐字一致+goal_hash 沿 DP3 换体形态+candidate_set_hash 材料扩集(OQ3 授权变更点,附 A #3)+新键 candidates」)→ DP6 20 键不动、CTE 重排+needed 合并过滤行(DP6 §3.1 L5 :621–735;gate B5 :1715)。**逐字性成立,两处授权变更(csh 扩集/goal_hash 换源)均有附 A 呈报。**
- effect_envelope 剔键集演化:DP1 内部演化至剔 7 键(session_version/max_event_seq/route_policy_name/route_policy_version/tools_revision/tools_catalog/candidate_generation_revision,DP1 §3.2 :1567–1578)→ DP2 同 7 键(timeout_ms/budget 不剔,DP2 §3.5 :941–947)→ DP5/DP6/DP7/DP8 零改动。语义信封 8 键(DP1)→12 键(DP2)→13 键(DP5 起,+candidates 随语义信封进 judge effect request——DP6 消费清单 #2 :38 显式注记)。**一致。**

---

## 检查 3 · 换体链完整性(「复制加载态」纪律)

逐对象换体链(→为 OR REPLACE;数字为 SQL_LOAD_ORDER 文件位):

| 对象 | 链 | 复制源正确性 | 判定 |
|---|---|---|---|
| v13_request_hash(7 参) | DP1→DP2 | DP2 换体仅函数体经 v13_judgment_material,签名逐字 | ✓ |
| v13_judgment_hash(5 参) | DP1→DP2→DP6 | DP6 分支仅 corpus_exists/chunk::% 两处,canonical 逐字节转发(不变量 2+gate D4/H5) | ✓ |
| v13_effect_envelope | DP1→DP2 | 剔 7 键逐字;后继零改动 | ✓ |
| v13_effect_id | DP1→DP2 | `#-` 两路径豁免,非 judge request 逐字节不变(DP2 E4) | ✓ |
| v13_resolve_judgments | DP1→DP2→DP6 | DP6 canonical 半边逐字保留+filter 半边;DP7/DP8 零改动(DP7 验收经其复用) | ✓ |
| v13_judgment_envelope | DP1(15)→DP2 DROP+CREATE(19)→DP3(19,goal_hash 换源)→DP5(20)→DP6(20,合并层) | 逐字链成立(检查 2) | ✓ |
| v13_needed_judgments | DP1→DP2 DROP+CREATE(五列)→DP5/DP6 函数体零改动(过滤行在信封合并层,OQ2) | ✓ | ✓ |
| v13_snapshot / v13_probe | DP1→DP2 DROP+CREATE / DP1→DP3(goal_hash 换源);DP5 OQ1 probe 七键零动 | ✓ | ✓ |
| v13_context_fresh | DP1 stub→DP3 真比较 | ✓ | ✓ |
| **v13_context_required(token)** | DP3(7)→DP4(8)→DP5(9)→**DP7(8,复制源错)**→DP8(11 修复) | **DP7 环 ✗**(检查 2) | ✗→修复 |
| **v13_assemble_manifest** | DP3→DP5→DP6→DP7(12 号 v2,**复制源字面=DP3 §3.4**)→DP7(13 号 v3,复制 v2)→DP8(14 号 v4,复制 13 号加载态) | **DP7 12 号环 ✗ 字面回退风险**(检查 2);DP8 §3.7 规则正确 | ✗(文本级) |
| v13_manifest_validate | DP3→DP7(12 v2)→DP7(13 v3)→DP8(v4) | DP7 复制 DP3 §3.3 = **正确**(DP3 确为 validate 的最新前驱,无人中间改过) | ✓ |
| v13_refresh_context | DP3→DP7(12 号锁集/守卫扩)→DP8(14 号) | DP7 复制 DP3 §3.5 = **正确**(同上) | ✓ |
| v13_parse | DP1→DP7(前置花费闸) | DP7 复制 DP1 §3.4 = **正确**(parse 的最新前驱即 DP1;DP2 明确不替换 parse) | ✓ |
| v13_latch_digest | DP3 stub→DP8 真函数(空集 '-none-' 逐字衔接,gate B5) | ✓ | ✓ |
| v13_prefix_identity | DP3→DP8(材料第九键 render_policy_version=恒九键;generation_effective 换源) | DP3 注释「恒九键」为八键计数笔误,以函数体为准(DP8 附 A #13 勘误) | ✓ |
| v13_goal_hash | DP3→DP8(前缀感知链回走;非 fork 会话逐字节等,gate E6 双库对照) | ✓ | ✓ |
| v13_chunks_generation_bump | DP4→DP5(双 bump:cgr 接线) | ✓ | ✓ |
| v13_recall/recall_count/extract_spans/verify_chunks | DP4(或 DP5 文件 8)→DP5 文件 9 v2 换体(签名/输出冻结) | ✓ | ✓ |
| v13_chunk_referenced | DP4→DP6(decisions 半边等值换载 @>,附 A #6;gate G2 双查等价) | ✓ | ✓ |
| v13_blob_land | DP3→DP8(词表 +system_block) | ✓ | ✓ |

**换体链结论**:唯二断点均在 DP7 文件 12(换体一 token、换体三 assemble 的复制源字面指向 DP3 而非最新加载态);DP7 文件 13 与 DP8 的复制源规则本身正确。DP8 换体三(goal_hash)/换体二(prefix_identity)为全文重写的修复性换体,非复制——合规。

---

## 检查 4 · DP 间契约闭合(双向抽查)

上游 §1.3/§1.4 契约逐条 vs 下游消费清单(重点项):

| 契约 | 发布 | 消费 | 判定 |
|---|---|---|---|
| DP1 #43(request_hash 入 signal) | DP1 §3.6 #43 :2685 | DP2 §1.2 #1(signal 材料首键);DP6 per-chunk signal='chunk::' 差分(不变量 2) | ✓ |
| DP1 #59(语料/索引版本并入 cgr) | DP1 §1.3 :55 | DP4 §1.4 ① 转发 DP5;DP5 §1.2 #2+OQ1(OR REPLACE 双 bump :415–423,gate F 组) | ✓ |
| DP3 OQ1 追动键缝 | DP3 §1.3 OQ1 :57 | DP4 #8(corpus);DP5 #10/OQ8(recall_ver);DP6 #14(chunk_filter 不入+论证);DP7 #23/OQ7(econ_ver);DP8 #10/OQ1(ident_ver 单键合并,附 A #10) | ✓(四代消费全链) |
| DP4 ①–⑨(对 DP5) | DP4 §1.4 :99 | DP5 §1.2 #2/#11–#15+不变量 4(⑨ 退役源过滤)/§1.4 转发 ⑤⑧ | ✓ 九条全承接或显式转发 |
| DP5 ①–⑦(对 DP6) | DP5 §1.4 :109 | DP6 §1.2 #20–#25(①信封 candidates 键单一推导点=合并层;②签名冻结+零直调 extract;③授权前移注记;④digest 对 csh 偏差=附 A #3 呈报;⑤⑥⑦ 转发/兑现) | ✓(一处载体偏差已呈报) |
| DP6 ①–⑥(对 DP7) | DP6 §1.4 :103 | DP7 §1.2 #13–#18(③manifest v2 移交=OQ7 兑现;⑤summary_accept 点=OQ8;⑥一页账 v3) | ✓ |
| DP7 DP8 行(render_policy/latch 零耦合/触点 1) | DP7 §1.4 :160–162+附 A #9 :1069 | DP8 §1.2 #16/#17/#18(OQ1/C4 兑现 identity+token;OQ6 两证据面分工;附 A #5 采纳) | ✓ |
| DP8 四缝(chunk sections render 零改/fork turn-runner/system blocks 真值/latch 消费者+auto-flip) | DP8 §1.4 :126–131 | 终端契约(发布给实施期/后续,无下游 DP)——形态合法;其中「终局交叉覆盖检查」行(:131)即本报告 | ✓ |
| DP2 DP3 行(templates/needed/groups+call_id;exact replay 归属;goal_hash 契约) | DP2 §1.4 :63 | DP3 §1.2 #10/#11/#12(manifest 溯源;v13_replay;墓碑二) | ✓ |
| DP1 DP6 行(reused_from 拆分/复用 resolve 双速) | DP1 §1.3 :56 | DP6 §1.2 #1(canonical 层=DP2 已落,零新映射表;worker 契约零改动) | ✓(所有权向 DP2 漂移已在两 plan 内文档化,无双实现) |
| 触点 1 归属 | loop 分解表 DP8 行 vs DP7 附 A #9 | 控制器 turn-30/31 已裁归 DP7;DP8 纯消费(OQ6/§7) | ✓ 已裁,无双实现 |

**契约闭合结论**:每个 §1.4 发布条目在其声称的下游 plan 消费清单中真实存在;下游为终端(实施期)的契约均显式标注;未发现单向悬空契约。**闭合。**

---

## 检查 5 · gate 总账

| Gate | 归属(分解表) | 断言形态 | 证据 |
|---|---|---|---|
| G-ctx1 | DP1 | M4 逐条映射(G-ctx1-1…5)+M2 单元级 7/8 | DP1 §4 M4 表 |
| G-ctx2 | DP4 | 五断言→A 组(自证)/B 组(重摄取同事务)/E1–E2(rebuild 幂等)/E3–E5+N3(verify)/H1(p99) | DP4 §4 G-ctx2 映射表 |
| G-ctx3 | DP5 | 四断言→K(绑定矩阵)/L(canary)/A(注入)/C+J(count 自适应) | DP5 §4 映射表 |
| G-ctx4 | DP6 | 三断言→C1/C2(先行+闸关零 Score)/D1(二次零调用)/D2(跨 session reused_from)+§4.4 行 p99=L 组 | DP6 §4 映射表 |
| G-ctx5 | DP3 | 四断言→B(全字段)/C(双分支)/D(三回放+确定性);第五断言 est≤预算=C2;DP5 E 组/DP8 E1–E2 复测 | DP3 §4 |
| G-ctx6 | DP7 | 轮 2 修正语义重写(C1–C3 单调/hysteresis、B 组 R_o、D 组 E(r));取代注记双重标注 | DP7 §4 映射表+头部注记 |
| G-ctx7 | DP2 | C1–C4 四断言(测试专用窄模板构造,OQ4) | DP2 §4 C 组 |
| G-ctx8 | DP1+DP7 | 解析相=DP1 M4-K1(kill 点/幂等重推);摘要段=DP7 O 组(回退链全链) | DP1 M4/DP7 §4 |
| G-ctx9 | DP3(条目)+DP1(机制) | DP3 F 组(freeze 迟到不回写/水位弃批/canary 半边);机制=DP1 probe 七键+M3-8/9/18 | DP1 §1.3 注+DP3 F 组 |

- **SQL_LOAD_ORDER 14 位无冲突**:core/resolve/advance/twophase(DP1,1–4)→envelope(5)→manifest(6)→chunks(7)→recall(8)→characterize(9)→filter(10)→memory(11)→economy(12)→summary(13)→periphery(14);各 plan 均纯末尾追加+STAGE_THROUGH 键 5–14,零重复零冲突。
- **stage 库唯一**:agent_v13_{schema,resolve,loop,twophase,envelope,manifest,chunks,recall,characterize,filter,memory,economy,summary,periphery}——14 库名互异。
- **命令形态统一**:`uv run python v13/<stage>/test_<name>.py`(test_schema/test_resolve/test_loop/test_twophase/test_envelope/test_manifest/test_chunks/test_recall/test_characterize/test_filter/test_memory/test_economy/test_summary/test_periphery),退出码 0=通过;每 plan 明写「提交前全部前序 stage 复跑」(AGENTS.md 前置条件 1)。

---

## 检查 6 · 设计侧遗留分歧汇总(供用户决定是否出设计 v3 erratum)

各 plan 附 A 中呈报设计稿的分歧汇总(去重归并;「呈报级」=不改设计、plan 内裁决,已在 loop 备案):

| # | 分歧 | 来源 | plan 侧裁决 | erratum 建议 |
|---|---|---|---|---|
| 1 | **G-ctx6 措辞**(「tier 只升不降跨 turn 成立」)与 §5.4/§14 轮 2 P0 修正直接冲突 | DP1 附 A/DP3 附 A #17/DP7 附 A #6(stepfun F8) | 用户既定默认:不修冻结稿,plan 内绕行(单 Plan 单调+跨 turn hysteresis;取代注记) | **建议 erratum**:§10 G-ctx6 一行改为轮 2 语义(三 plan 三次呈报,唯一 P0 级措辞矛盾) |
| 2 | **作用力 2(generic-plan 回落)在 stannum 0.1.0 未复现**;真实降级面=无索引回落+同列双索引错绑 | DP5 附 A #1(实测记档) | 三禁保留为冻结纪律+纵深防御;gate 断实测面;升级复测项 | 建议 erratum 附注(§1 作用力 2 加「0.1.0 实测:planner support 重写保持绑定」注记) |
| 3 | **fresh·recompute 语义判定式**设计未给;plan 裁 identity 基(版本 bump=recompute,identity 变=fresh) | DP3 附 A #14/#15 | 与 ch14:93/94 语义一致且更细 | 可选 erratum:§5.2 补一句判定式 |
| 4 | **pg_jsonschema**(§8 P1 进)vs 两半边(answer/manifest)推迟+台账 | DP2 附 A #3/DP3 附 A #16 | V3001/V3003 手写族独扛;触发=形状超表达力且第二消费者出现 | 建议 erratum 附注(§8 行加「首版手写校验族,V 码域」) |
| 5 | **§4.5/§6.5 张力**(per-chunk 键 vs 单 state 批联合) | DP6 附 A #5 | §4.5 特别法(lex specialis);内容寻址确定性封死漂移面 | 建议 erratum 一句(§6.5 批约束加「过滤族除外,见 §4.5」) |
| 6 | **F2 存在性键候选集维度**设计 §4.5 未定义 | DP6 附 A #1(stepfun F2) | candidates_digest 载体化立法 | 建议 erratum(§4.5 补键公式) |
| 7 | **F10 水印新鲜度行动语义**设计只定义度量 | DP6 附 A #2(stepfun F10) | fail-closed+滞后上界+当前 turn 直读+消费契约 | 建议 erratum(§4.4 补语义) |
| 8 | **F13 latch 并发首触发**未定;F3 三修法(chunk_offset/保留/回放);F9 latch 交付位置 | DP8 附 A #2/DP4 附 A #1–#2 | OQ8/F3 立法/F9 plan 内消解(stub→真函数接通两说) | 可选 erratum(§5.1/§4.2/§9 增补) |
| 9 | **rebuild 字面「truncate+重灌」**与 F3② 被引用行不可删冲突 | DP4 附 A #2 | 保护式重灌(locked 分流) | 建议 erratum(§4.2 措辞) |
| 10 | **教程 ch4 UNIQUE(request_hash) 全局形态** vs DP1 收窄 (session_id,request_hash)+DP2 canonical 双平面 | DP1 §3.6 #11/DP2 §6 | 两平面各归其位 | 可选 erratum/教程侧统一动作(「教程表形状」项) |
| 11 | 载体裁量群:tier 带=v13_policies(非 thresholds 表);L_eff=context_budget 行(非 meta);(model,source) 桶 source=effects.kind+model 谓词 result 侧;定价目录 active 选择(非 now());filter 批上限=信封 budget;goal_hash 留在 prefix_identity 材料;emergent/effect 溯源两纪律(goal 平面独立表) | DP7 附 A #1/#2/#3/#4、DP6 #7、DP3 附 A #2/#10 | 各附 A 论证在档 | 无需 erratum(载体级,§9 为示意清单) |
| 12 | DP3 自身注释「prefix_identity 材料恒九键」为八键计数笔误(以函数体为准;DP8 落地日恰成九键) | DP8 附 A #13 | 勘误注记 | 无需(计划侧已记) |

---

## 检查 7 · DP8 P1-1/P1-2 修订落点回读(turn 31 出口指定)

L4 第 31 轮 4 P1 在 turn 32 的落点回读(DP8 plan 文本):

| P1(turn 31) | turn 32 修法 | 落点回读 | 判定 |
|---|---|---|---|
| P1-1 goal_hash 递归锚行守卫错 | 锚行改 parent_cutoff_seq(选型理由写明)+无环断言改正 | 换体四 :409–438:链 CTE 以 `cut IS NOT NULL` 判被消费行(无 cutoff 即不再上行,:426–427);「无环=fork 只建新行的构造不变量」注记;选型理由(锚行法 vs 截止元组)写明;gate E6=非 fork 会话与 ≤13 号公式双库对照字节等+fork 子=父@cutoff | ✓ 已落 |
| P1-2 fresh belt 死代码+OQ4 自矛盾 | fresh belt 删除+OQ4/不变量 6/E5 改记录面 | OQ4 :87:「fresh 子必携 generation latch(fork SQL 无条件落)…『fresh 子 latch 空集』不成立;无 overrides 且 cutoff 对齐 settle 点时子身份可与父 artifact 身份相等,为合法形态(L4 P1-2)」——自矛盾已除;E5 :1000 改记录面(forked payload child_identity 在场+合法形态注记断言);§3.4 :546–548 残留一处 `IF…THEN NULL;belt 注记`,文末注 :578–579 自旗「实施期以显式 RAISE 最终化」 | ✓ 已落(残留死语句为自旗 P2,见 Findings #4) |
| P1-3 `::` 优先级解析错 | cast 括号两行+同型零残留+机械自检新增条款 | 实施顺序 §4.2 :1061 机械自检③「cast 作用域显式括号——`::` 优先级高于 `->`,receipt 两行 (v_wire->'k')::text 形态,L4 P1-3」;receipt 体 :652–653 确为括号形态 | ✓ 已落 |
| P1-4 TRUNCATE 语句级触发器缺 | 触发器+六处计数联动(35→36) | §3.1 :211–214 trg_latches_no_truncate BEFORE TRUNCATE FOR EACH STATEMENT;guard TRUNCATE 分支 :201–204;gate A3 :954 TRUNCATE 拒断言;附 B :1149 计数=36 条(触发器 3=行级+语句级+spawn 列),「实施期抽取件落实体则 37」注记 | ✓ 已落 |

**四项 P1 全部落位;turn 32 的「残留扫描零」与文本一致。**

---

## Findings 清单

| # | 级别 | Finding | 证据 | 处置建议 |
|---|---|---|---|---|
| 1 | **P1** | **DP7 token 键谱回归未在其 plan 文本内修正**:换体一(:459–462)与不变量 8(:179)固化「复制 DP3 七键体、键集 7→8」,丢 DP4 corpus/DP5 recall_ver;≥12 号库处于 freshness-miss 回归态,且无任何 gate 断言 corpus/recall_ver 在 ≥12 号库的追动(DP7 E4 只断 econ_ver;DP4 G1/DP5 H4 只在其前缀库)。DP8 附 A #1 已呈报并在 14 号修复(gate I1),终态库正确——残留为 DP7 文本与终态不一致+实施文件 12/13 里程碑期间的过渡回归 | DP7 :459–462/:179;DP8 附 A #1 :1126、换体三 :364–407、gate I1 :1043 | 控制器二选一:(a) turn 34 对 DP7 换体一做一行修订(复制源「DP3 §3.2」→「文件 8 加载态(DP5 九键体)」,不变量 8 同步「十键」);(b) 记遗留清单:实施文件 12 时以 DP8 §3.7 复制源规则为准(其规则已制度化),DP7 字面作废 |
| 2 | **P1** | **DP7 assemble v2 复制源字面=「DP3 §3.4」**:DP5 L7(candidates←v13_recall_candidates/goal echo 退役)与 DP6 墓碑四(decision_id 填充/jud 消费集∪存在性行/final_action 真值)增量在 12/13 号体内的存续无文本保障;与 DP7 §3 前言「上游 stage 文件加载态」自相矛盾;**任何库均无 gate 断言该两级增量的存续**(DP5 E1–E3 在 8 号库、DP6 F1/F2 在 10 号库、DP8 I2 只查 validate 词表/economics/render)——前缀库互证盲区,本轮新确认 | DP7 :477–498((g) :496);DP5 :702–715;DP6 :1236–1286;DP8 §3.7 :839–849+I2 :1044 | 同上二选一:(a) DP7 换体三一行修订(复制源→「文件 10 加载态(DP6 形态)」)+DP8 I 组可加一条断言(14 号库 manifest v3 的 candidates=v13_recall_candidates 产物∧已决候选 decision_id 非 NULL);(b) 记遗留清单(实施纪律以 DP8 §3.7 为准) |
| 3 | P2 | DP8 换体三草案 sem 谓词 `coalesce(max(seq),0)` 与 DP3 加载态 `-1` 空会话口径差;plan 已自旗「实施时逐字对照 DP3 加载态」+双保险(I1 键集+上游 gate 复跑) | DP8 :391–393 vs DP3 :484–487;自旗 :404–405 | 实施期对照纪律已在场;无需改文 |
| 4 | P2 | DP8 fresh-fork 分支残留 `IF…THEN NULL` 死语句(belt);plan 自旗实施期以显式 RAISE 最终化 | DP8 :546–548+注 :578–579 | 实施期收口;无需改文 |
| 5 | P2 | DP7 summary 模板种子/信封模板读取的列名 `version`(vs DP2 加载态 `template_version`)与 latest 视图名「等价形态」;plan 自旗「列面实施期对齐 DP2 §3.1 加载态」 | DP7 :587–597/:647–650 注 | 实施期对齐;无需改文 |
| 6 | P2 | 设计侧遗留分歧群(检查 6 表 #1–#10)——其中 G-ctx6 措辞为唯一 P0 级矛盾,已三次呈报;作用力 2 实测分歧为事实性呈报 | 检查 6 表 | 用户决定是否出设计 v3 erratum;不影响八 plan 的可执行性(绕行/呈报均已在档) |

**P0:零**(无未覆盖 normative、无机制双实现、无 gate 归属冲突、无断裂言)。

---

## Loop 终态建议

对照 loop memory 的 Stop states 与冻结检查:

- **L3**:八份 plan 在约定路径、必备七节齐全 ✓。
- **L4**:八份 plan 均达验证态(turn 12/17/21/24/26/28/30/32 记录在案)✓。
- **终局附加(8 份集体交叉检查无缺口/无重叠)**:本报告覆盖矩阵=**无缺口、无重叠**(检查 1/4/5);换体链两处 P1 均为 **plan 文本级一致性/盲区**(同一根因:DP7 文件 12 两个换体的复制源字面),非机制缺口——终态库(14 文件)经 DP8 修复后正确,且 DP8 §3.7 已把正确复制源规则制度化。

**建议**:loop 达 **success** 终态。收口路径二选一(控制器裁决):
1. **turn 34 微修**(推荐,成本=两行文本+可选一条 gate):DP7 换体一/换体三复制源各一行修订(→文件 8/文件 10 加载态),DP8 I 组可选加一条 candidates/decision_id 存续断言;修后无需重开 L4(机械修正,同 turn-17 cursor「机械修正即可过」先例)。
2. **即时收口+遗留清单**:接受 DP7 字面与 DP8 修复并存(实施纪律以 DP8 §3.7 为准),Findings #1/#2 连同检查 6 的设计侧分歧清单(尤其 G-ctx6 erratum)呈用户后终局。

---

## 附:本报告的核查边界

- 纯文档核查(无 runner);「行号」为各 plan 当前行号(2026-09-20/21 版)。
- 未运行任何 SQL/gate;机械搜索(键集/OR REPLACE/契约编号/G-ctx 映射/库名)覆盖八 plan 全文。
- 本报告不修改任何 plan/设计稿;Findings 处置权归控制器。
