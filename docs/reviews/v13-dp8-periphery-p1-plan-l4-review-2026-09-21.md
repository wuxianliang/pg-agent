# v13 DP8 计划评审:外围 P1 件(latch/canonical render/ForkPrefix·shadow/触点 5/触点 1 消费)(v13-dp8-periphery-p1-plan-2026-09-20.md)

评审日期:2026-09-21。评审:L4 代行(独立全新会话;ask_oracle 通道持续故障,按 loop 先例代行)。一次有界计划评审——仅评审、不实施、不改 plan、不运行任何 gate。

## Context / Scope

- 被审文档:`docs/plans/v13-dp8-periphery-p1-plan-2026-09-20.md`(1150 行,首写轮,全文已读)。撰写方未跑内部批判,本评审是最先的独立评审。
- 交叉参照(均实读):设计冻结稿 `docs/designs/v13-context-on-pg.md`(487 行全文;§5.1/§5.3/§5.6/§6.2/§9/§10/§11/§12/§13/§14 重点节);stepfun 设计评审 F9(:77–81)/F13(:101–105);上游 plan 逐条对照——DP1(fork 两列 :120–121、events 开放词表 :129–132、thresholds 种子 :1060–1070、llm request 恒 {route} :2484–2486、complete llm 形状校验 :446–451);DP3(prefix_identity 函数体 :531–560 实读、注释「恒九键」:533、replay 块 {mode,prior_artifact_id} :105、context_artifact_id 挂接 :73、G8 :1547、风险 5 :1561);DP4(§1.4 契约 #8 七键扩八键 :43、授权清单 :30);DP5(硬边界九处换体清单 :31、L5 九键体 :425–476、gate H4 九键集 :1166、I3/I4);DP6(九处授权清单 :31、工程纪律 :153、§1.4 DP7 行 :103);DP7(机制面 token 七键 :28、换体一 :459–462、换体三 (f)(g) :495–497、不变量 8 token 八键 :179、gate E4 第八键 :870、render_policy 种子 :265–269、附 A #9 触点 1 归属 :附 A、附 A #3 worker 契约 :64、OQ7 :142–162)。
- 评审方法:rubric 五项 PASS/FAIL+证据;五项重点推演(token 十一键修复闭合性/latch 冻结与模型升级/fork 读穿透裁决/shadow flip 人审偏离/validate-spawn gate 形态);机械猎(换体链完整性/三值/签名重复/前向引用/哈希同源——identity 四材料逐项)。

## 已核实成立的关键断言(不重复列入 Findings)

- **附 A #1(DP7 token 键谱回归)实存,且是本 plan 最高价值的发现**:键谱演化链逐环实证——DP3 函数体八键(含 manifest_version;注释「恒九键」为计数笔误,附 A #13 成立,:531–560 实读)→ DP4 OR REPLACE 七键扩八键(+corpus,:43)→ DP5 扩九键(+recall_ver,:425–476,gate H4 断九键)→ DP6 九处授权清单不含 context_required(不触,:31)→ **DP7 换体一「机械复制 DP3 §3.2 加载态原文…七键表达式逐字不动…键集 7→8」(:459–462)+不变量 8「token 八键」(:179)+gate E4「第八键」(:870)——corpus/recall_ver 两键在 ≥12 号库丢失**。后果分析成立(语料 generation bump / recall_k 翻版不再触发 refresh=freshness miss);「DP7 自身 gate 在 12/13 号库内自洽放行、前缀库互证不可见」的盲区论证成立。修复面闭合:换体三十一键全谱(逐键复制源标注)、换体五(b) 装配体内联 token 归一单源(双写面消除,风险 1)、gate I1 键集恰等、墓碑注记、I4 前缀库互证——**修复件齐**;呈报姿势(控制器+终局交叉检查清单)正确。
- **OQ2 generation 真值接管成立**:依据链三项(§5.1 latch 点名「模型选择」/ch14.5 安全绳「进行中会话继续旧版本」/DP3 行为身份材料源但未定会话作用域)逐条对得上;首触发=首次装配的时点语义经 settle 内联 fire-or-adopt 落地;C2(mid-session 翻版已 pin 会话身份字节不变+fresh 不变)直证安全绳;「行=目录真值,latch=会话作用域冻结投影」的二元表述消解了 brief 的「接管真值来源」歧义;值仍 mock 的机制/数据二分(附 A #11)与 DP3 骨架值逐字衔接(D6)。
- **OQ3 render 三件族成立**:纯函数族/wire 不落库(F11 的对偶兑现:manifest+blobs+render 版本三元组可重现,gate D1)/tools 与 tools_digest 同投影同材料(D3)/renderer 词表执法/protocol_only 归 driver;sections 通用渲染对 chunk sections 的「落地日零改」与 DP5 §1.4 DP8 行原文一致(消费清单 #14)。
- **OQ4 fork 壳的范围裁定安全**:两条前缀不焊(ch14.1)以不变量 3 钉死;「父子 seq 命名空间错位(父 100 事件/子首消息 seq=1)非机械换源」的论证具体且对;advance/route/complete/resolve 零改动维持冻结纪律;激活缝(§1.4 前缀窗语义包)发布完整;附 A #3 呈报姿势妥。
- **OQ5 probe 走 worker 契约面成立**:DP3 先例核实(context_artifact_id 本就是 worker 契约 result 键经 complete 流进 effect/事件行,:73/G8);对账锚=effect.result 免疫「complete 与 probe 之间 refresh 换指针」竞态(F6);「每次 llm 完成都对账」=首检+漂移巡检的合并形态;与 DP7 附 A #3 worker 契约(llm result 携 usage+model)同面衔接,单侧扩记 cache_read_input_tokens+wire_digest 与 DP1 complete 形状校验(只要求 text 非空,:446–451)兼容。
- **OQ6 shadow 仪器成立**:词表封闭 {render_policy,assemble_manifest} fail-closed(G4);内容投影剔除 policy/required_revision/economics(版本号自异)的设计正确;tier flip 证据面归 DP7 校准流程=附 A #9 的消费侧确认(两证据面并行不混);flip=人审仪式+auto-flip 入台账(§6.7 法源),偏离已呈报(附 A #6)。
- **OQ7 触点 5 v1 不武装的论证成立**:三重执法(STABLE+源码扫描+cals 零增量)+thresholds 单源(H7 改带翻转)+needed 集不变性(H5)结构齐;四不排除以「v1 零绑定+信封链零调 gate」结构性满足;激活三前提(§1.4)对实施期发布。
- **触点 1 纯消费兑现**:DP7 附 A #9 原文核实(turn-29 brief 落机制、建议 DP8 改消费、turn-30/31 brief 采纳);本 plan 零 hint 代码,§1.2 #18/§2/§7 三处一致。
- **OQ8/F9/F13 立法齐**:INSERT once=PK+触发器拒+ON CONFLICT adopt+admission(锁内计数,fail-closed 非 CHECK=轮 2 逐字)+保留名 generation+fired_at 不进 digest;F9 的 plan 内消解(stub 常量自 6 号文件进材料=身份钩子每 turn 在场,表本体第 14 位=交付步)成立且呈报;F13 修法建议(ON CONFLICT DO NOTHING+回读+gate 双连接恰一行同值)逐字落地 B2。
- **承接面**:消费清单 23 条逐行读上游原文对照(其中 #2/#3/#4/#5/#7/#8/#10/#12/#16/#18/#21/#22/#23 全文级核对,余一致),转述无失实;附 A 14 项分歧的裁决与呈报姿势均可辩护。
- 机械面:14 个新函数名全树零撞名(grep 实证);八换体各恰一处(附 B);V3008 全库未用(DP1–7=V3001–V3007 实证);manifest 外层 12 键/required_revision 11 键字典序串逐串复核正确;A–I 九组 56 断言计数核对(6+5+6+7+8+6+6+7+5);附 B 35 顶层语句算术核对;六策略行种子+generation 翻版仪式与 DP2/DP5 先例一致;A5 源码扫描口径承 DP5;ACL 双登录分派与 DP1/DP2 角色面吻合(OR REPLACE ACL 保留+A6)。

## Findings(0 P0 / 4 P1 / 12 P2)

### P1-1 换体四 v13_goal_hash 递归 CTE 守卫错位——「逐代上行」永不发生,fork 身份链全线失据

- 位置:§3.3 换体四(plan :404–424)递归项 `WHERE c.cut IS NOT NULL` + 锚行 `SELECT p_sid, NULL::bigint, 0`。
- 问题:锚行 cut 恒 NULL,而递归项守卫作用于**被消费行** c——首轮工作表={锚行},c.cut IS NULL ⇒ 递归项产出空 ⇒ 链={自身},逐代上行对一切会话(含 fork 子)永不发生。后果:fork 子(无 own goal)得 sha256('') 而非父@cutoff goal ⇒ 子 identity ≠ artifact 身份 ⇒ validate-spawn 对 exact/replay 恒拒——E1(逐字节回读)、E4-④(goal 漂移负向)、E6 第二半(fork 子=父@cutoff goal)全部红。与换体四自述链规则(「自身 goals 优先(最深),逐代上行取首个非空层」)自相矛盾。附注:注释「FK 保证无环」亦不成立(FK 只保证父存在;无环来自「fork 只建新行」的构造不变量,建议改注)。
- 修法:锚行 cut 改为 `(SELECT parent_cutoff_seq FROM sessions WHERE session_id = p_sid)`——非 fork 根 cut=NULL 自然止于自身(与 ≤13 号公式逐字节等,E6 前半保持),fork 子 cut=c 上行且每代 cut=该代子链的截止(守卫语义同时转正:「链行无 cutoff 即不再上行」);或等价地删守卫改 `WHERE s.parent_session_id IS NOT NULL`(树根自然终止)。二选一,E6 双半均绿。

### P1-2 fresh fork 的 belt 是死代码,且 OQ4 的结构性论证与自家 fork SQL 矛盾——E5 按字面必红

- 位置:§3.4 v13_fork(plan :547–551 fresh 分支 belt `IF v_art IS NOT NULL AND v_child_ident = v_art_ident`)+ OQ4 validate-spawn 段(:87「fresh 子 latch 空集 digest='-none-'」)+ gate E5(:989「无 overrides 的 fresh 也过(identity≠结构性)」)。
- 问题:(a) v_art 仅在 `p_kind IS DISTINCT FROM 'fresh_fork'` 分支赋值(:491–508),fresh 分支恒 NULL ⇒ belt 条件恒假,永不可触发;(b) 结构性论证不成立——fork SQL 的 fresh 分支**无条件**给子会话落 generation latch(:523–531),故「fresh 子 latch 空集 digest='-none-'」为误:父只含 generation latch(典型:仅一次 settle、无手动 latch)且 cutoff 对齐 settle 点时,子 latch_digest=父、goal_hash(P1-1 修复后)=父、tools/render_policy/manifest_version 同 ⇒ **子 identity=父 artifact 身份**,「identity≠」非结构性;(c) 因此 E5 的第二 fixture(无 overrides fresh 断言 identity≠)对正确实现打红。设计面核对:§5.6 只要求 validate-spawn 拒「破坏缓存身份的 fork」——fresh 同身份=同前缀=缓存命中,无害,不需拒。
- 修法(推荐):删 belt 死代码;OQ4 论证改写为「fresh 子必携 generation latch(父此刻生效值为基底);无 overrides 且 cutoff 对齐 settle 点时子身份可与父 artifact 身份相等——同身份=同前缀缓存命中,无害;validate-spawn 对 fresh 无身份检查(设计原文)」;E5 改为断言:fork 过+overrides 进 forked 事件与子 generation latch+身份记录面(forked payload 的 child_identity),可另加注记断言「同身份可能性=合法」。(不推荐反向修法:如实实现 belt 对父 active artifact 身份比较——会把无 overrides 的合法 fresh 拒掉,与 E5 冲突更深。)

### P1-3 v13_render_receipt 的 octet_length 取参有转型优先级错误——settle 全线运行时炸

- 位置:§3.5 receipt(plan :641–642)`octet_length(v_wire->'system'::text)` 与 `octet_length(v_wire->'tools'::text)` 两行。
- 问题:`::` 优先级高于 `->`,表达式解析为 `octet_length(v_wire -> ('system'::text))` = octet_length(jsonb)——该函数不存在(42883)。receipt 经换体五(a) 进**每次** settle ⇒ C/D/E/G/I 全组凡走真实 settle 链路的断言首跑即炸。
- 修法:显式括号——`octet_length((v_wire->'system')::text)`、`octet_length((v_wire->'tools')::text)`(段体行 :646–648 的 `(SELECT jsonb_build_object(...)::text)` 已是正确形态,仅这两行漏括号)。

### P1-4 gate A3 断言「TRUNCATE 拒」与草案 DDL 矛盾——行级守卫触发器不触 TRUNCATE

- 位置:§3.1(仅 `BEFORE UPDATE OR DELETE … FOR EACH ROW` 触发器,:205–206)+ §4.1 A3(:943「TRUNCATE 拒(latches 属 guard 触发器面)」)。
- 问题:PostgreSQL 行级 UPDATE/DELETE 触发器对 TRUNCATE 不触发;无语句级 TRUNCATE 触发器时 TRUNCATE latches 静默成功 ⇒ A3 按字面必红(而 INSERT-once 执法面存在旁路)。
- 修法:§3.1 补 `CREATE TRIGGER trg_latches_no_truncate BEFORE TRUNCATE ON latches FOR EACH STATEMENT EXECUTE FUNCTION v13_latches_guard()`(guard 体对 TRUNCATE 形态的 RAISE 消息用 TG_OP='TRUNCATE' 自然成立;顶层语句计数 35→36,附 B 同步);或删 A3 的 TRUNCATE 半句(不推荐——弱化一次性执法)。

## P2(实施期处置;不阻断)

1. §1.1「六件 OR REPLACE/换体:prefix_identity/context_required/goal_hash/assemble/validate/refresh+blob_land 词表扩」漏计换体一 v13_latch_digest(且 blob_land 实为 OR REPLACE 换体);§3.7 表与附 B 计八件——授权清单枚举以 §3 为准补齐 §1.1。
2. B5「fired_at 变化(直改 owner fixture)」不可执行——守卫触发器对 owner 同样生效,UPDATE 恒 V3008;改用双会话不同 fired_at 同 (name,value) 对照 digest 等(等价覆盖同一断言语义)。
3. F1 fixture 尺寸须使 est > 1280 tokens 量级(差额须越 `max(est×0.2, 1024)` 的 min_tokens 下限);gate 设计注记,防小 fixture 下「差一截却不落事件」的意外红。
4. v13_intent_gate 草案列名 `route_policy_name/route_policy_version` 与 DP1 thresholds 实际列 `policy_name/policy_version`(:1060–1070 实读)不符——已有「实施时对齐」注记,建议直接改草案消除双名。
5. OQ3/§3.5「est 公式=DP3 逐字」措辞:同除数同取整式,但聚合粒度不同(receipt 对总字节一次取整,DP3 逐段取整求和)——receipt est 是新量(前缀估计),措辞改「同除数同式、前缀聚合」即可;D5 手工对照口径同步注明。
6. receipt 段字节计为 {id,body}(不含 marker)——估计量自洽即可,README/gate 注明口径。
7. OQ1「键集 10→11」的基数叙述:10=意图谱系(DP7 若正确携载应为 9+econ_ver=10),实际 DP7 产物为 8——加半句澄清,防交叉检查时对不上账。
8. cap 语义注记:settle 内联首发不过 admission 计数(保留名豁免,合法),故表行数可达 17(16 手动+generation);风险 7「fork 复制在 cap 内(父集≤cap)」应改「父集≤cap+1」。README 记 cap=「外部 fire 上限」非「行数上限」。
9. v13_latch_fire 对不存在 sid 走 FK 23503 而非 V3008——可接受(fail-closed),README 记一笔或入口加显式检查。
10. 风险 4「tolerarance」拼写;§3.5 注记「实施期机械自检#1」编号与 §4.2 五项清单的对应关系核对一遍。
11. **附 A #1 交叉检查建议扩面**:除 corpus/recall_ver 外,把 DP7 12/13 号 assemble/validate 体内 DP5(query_side candidates 的 decision_id 填充)与 DP6(judgments 消费集/final_action 真值、过滤 trace)增量的存续一并纳入对照——DP7 换体三引用「机械复制 DP3 §3.4 加载态原文」+增量 (g)「sections/query_side/judgments/replay 块零改」存在按 DP3 原文体解读的歧义;若按误读复制,上述增量在 ≥12 号库静默丢失,而上游 gate 前缀库互证(I4)对此结构性盲(DP7 自身 gate 断言面在 economics/summary,不覆盖 DP5/DP6 装配内部)。
12. DP3 风险 5 曾建议「DP8 render 落地时(artifact 钉缝)升格为 request 内钉」——本 plan 取 worker 契约面(附 A #7 论证成立),建议在附 A #7 点名与 DP3 该建议的偏离承接(目前仅 #5 隐含),防交叉检查漏账。

## Rubric 裁定(逐项)

1. **可开工(SQL 完整;OQ 九项可辩护):PASS(有条件)**。SQL 草案对新对象列/约束/签名/关键语句齐,换体五至八以「机械复制+标注增量」形态与本系列 plan 惯例一致;OQ1–OQ9 全部有裁决+依据链,无一悬空。条件=P1-1/2/3 修毕(三处草案 SQL 逻辑/类型缺陷会使「实施者可直接开写」的承诺失真)。
2. **覆盖:PASS**。§5.1 全条目(表/触发器/admission 非轮-2-CHECK/身份参与/冻结语义/target_turn+membership 消费形态立法零代码+无生产者不立)/§5.3(render 纯函数族/canonical 唯一/词表执法/cache marker/呈现不立法)/§5.6(继承+四材料身份映射+validate-spawn+probe+shadow)/触点 5 全裁面(软门控立法+绑超集+四不排除+三重不新调)/触点 1 纯消费/generation 接管/ch14 §6 逐节映射(v1 断言 vs 激活缝明示)/§12 台账+新增五项——逐条对得上。
3. **gate 可执行:修订后 PASS**。结构面(真实链路 fixture/断言对象 ≤14 号/源码扫描口径/翻版回滚)承 DP1–7 纪律;rubric 点名六件全在(拒 clamp=E4③/probe 事件=F1F4/flip 零 diff N turn=G5/并发恰一行同值=B2/needed 不变性=H5/I1 全谱)。修订前四处内部矛盾:A3(P1-4)与 E5 第二 fixture(P1-2)按字面必红;E1/E4④/E6 依赖的 goal_hash(P1-1)与 settle 全链依赖的 receipt(P1-3)会使大半 gate 组炸——四处修复后 56 断言形态全部可执行。
4. **不越界:PASS**。emergent/预取/效用遥测/呈现偏好立法/协议适配层/wire 落库/auto-flip/会话树读穿透全部 §7 不做+触发条件在档;八换体全部落在 brief 授权集(换体四件+增量链五至八)内,goal_hash 换体四属授权集且为 fork 可用的必要最小例外;上游语义面只经约定缝消费。
5. **承接:PASS**。DP3 四缝(latch digest 缝 #7/generation 真值接管 #8/llm request 钉缝 #5/render 消费 #11+token 追动 #10)全兑现;DP7 两行(render_policy 行消费+落地日 identity/token 追动 #16、触点 1 归属=附 A #9 纯消费 #18)全兑现;DP5 无耦合注记(#14)/DP4 blob 消费(#13)/DP2 shadow 分工(#6)/DP6 纪律制度化(#22/#20)逐条语义确认。

## 重点推演结论(控制器指定五项)

1. **token 十一键全谱修复闭合性(跨库互证)**:闭合。演化链 7(DP3)→8(DP4+corpus)→9(DP5+recall_ver)→不动(DP6)→8(DP7 回归,plan 文本+不变量+gate 三处自洽地错)逐环实证;DP8 修复三件套(换体三全谱+换体五(b) 单源归一+I1 键集恰等)+墓碑+双保险(上游 gate 前缀库复跑)设计正确。唯一残留=DP7 plan 文本与实施文件本身仍带回归(≥12 号库世界),本 plan 呈报进终局交叉检查正确且必要;按 P2-11 扩面后(含 DP7 assemble 体内 DP5/DP6 增量存续)交叉面才完整。
2. **latch 首触发冻结 vs 模型升级路径**:OQ2 已显式回答且呈报——已 pin 会话 mid-session 翻版:身份/ token/缓存身份全不动(C2 直证);未 pin 会话:下次首装配取新行;**换模型的关系化通道=fresh fork 的 spawn_overrides(新会话)**,「翻 latch 被拒」正是 §5.1「mid-session 漂移即隐性 cache-break」的执法目的,非缺陷。呈报三处在档(OQ2 依据链/§1.4 已 pin 不受影响行/附 A #11)。
3. **fork「读穿透=命名空间错位」裁决安全性**:安全。论证具体(子 last_user_seq 语义窗对父前缀 seq 的错位会把前缀误判为未来事件),非搪塞;设计 §13-ch14 映射只点名 ForkPrefix 关系化+三种回放,视图是教程讲解件;advance/route/complete 冻结维持;激活=producer 门控(emergent 同款),缝清单发布(§1.4)。附 A #3 呈报。
4. **shadow flip 人审仪式与设计「零 diff N turn 后 flip」的偏离**:已呈报(附 A #6)。§6.7「在线 learned policy」拒项覆盖「策略凭自身观察翻自身」的自动路径成立;streak/ready 是查询非动作(G6 源码断言零策略 UPDATE),翻版走运维仪式+校准=翻版本体;偏离语义(设计句可读作自动)已点名。
5. **validate-spawn 在没有 spawn 实现时的 gate 形态**:两者兼备且自洽——v13_fork 本身就是本 plan 落地的 spawn 壳函数(事务内 RAISE=不落行),E4 四负向/E5 全部是纯 SQL 直调断言,零外部 spawn/worker 依赖;P1-2 修复后 E5 语义与实现一致。

## 机械猎记录

- **换体链完整性**:§3.7 复制源表五对象逐链核对(assemble:DP3→DP5→DP6→DP7 12→DP7 13,复制源=13 号加载态 ✓;validate 同链 ✓;refresh:DP3→DP7 12 ✓;blob_land:DP3(6 号) ✓;identity 族 §3.3 全文重写 ✓)——「最新加载态」规则把 DP6:153 纪律制度化,恰是 DP7 事故(#12)的防线;发现 §1.1 枚举计数不一致(P2-1)。
- **三值**:fork/shadow_observe/intent_gate 的词表判断全部 `IN(...) IS NOT TRUE` 形态 ✓;validate v4 null 穿透封死声明承 DP3 层纪律 ✓;render_wire 的 system_blocks null 分支静默空数组(缺键→[] 而非 RAISE)——由 settle 守卫(换体七(a) 形状执法)前置兜住,可接受。
- **签名重复**:14 新名全树 grep 零命中 ✓;八换体各恰一处(附 B) ✓;v13_render_wire 第三参带 DEFAULT 非重载 ✓。
- **前向引用**:render_section_body 为实施期抽取件(已注记+附 B 计数);其余文件内序=依赖序 ✓;对上游引用全部 ≤13 号 ✓。
- **哈希同源(identity 四材料)**:§5.6 公式「system blocks+tool schemas+model+latches」→ 九键映射逐项核对(system_blocks_digest/tools_rev+tools_digest/provider+model/latch_digest,另有 goal_hash/render_policy_version/manifest_version 为 v13 超集,OQ1 以「canonical bytes 清单的关系化」说明);latch_digest 单源(identity 材料+ident_ver 共消费) ✓;tools_digest 与 wire tools 同 canonical_state 投影(D3) ✓;est 除数同源 ✓;token 双写面归一(换体五(b)) ✓;ident_ver 内 latch 与 render_policy 版本同查询面 ✓。
- 附 B 五项机械自检与三处已注记收口(probe 双子查询/belt RAISE 化/段体抽取)核对在案;P1-3 的括号与 P1-1 的锚行修正建议补入机械自检③「类型算子层」与②清单。

## 裁定与出口

- **Verdict:修订后通过(REVISE-THEN-PASS)**。0 P0 / 4 P1 / 12 P2。四个 P1 全部是草案 SQL/gate 断言的自洽性缺陷(单点单行量级修法),不动架构、不动覆盖面、不动上游契约消费、不动任何 OQ 裁决。修复后本 plan 达到可开工线。
- **可进入终局交叉覆盖检查:是**——建议 P1 修毕(一处一行量级,半小时内)后即启动;不必重走本轮评审(修法均在案,修订可自查)。交叉检查清单必含:①附 A #1(DP7 token 键谱,按 P2-11 扩面至 assemble/validate 体内 DP5/DP6 增量存续);②八 plan 键谱总账(token/manifest 外层/section/policy 块/信封/replay 各键集的跨 DP 演化终值对照表);③本 plan P1-1/P1-2 的修订落点(goal_hash 链规则/fresh 身份语义)回读确认。
