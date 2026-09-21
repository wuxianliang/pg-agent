# v13 DP5 plan L4 评审 —— stannum 刻画与 T0 recall(首写轮,代行)

> 评审者:L4 评审代行者(ask_oracle 通道持续故障,按 DP3/DP4 代行先例;独立全新会话)。
> 被审基线:`docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md`(1366 行,首写轮 turn 25)。
> 对照面:设计稿 `docs/designs/v13-context-on-pg.md`(487 行)§4.1/§4.6/§4.7/§4.8/§7/§8/§9/§10/§11/§12/§13/§14;DP1–DP4 plan 全文关键节;stepfun 设计审查 F4/F5;v12/load.py 机制。v13/ 目录尚无实现(DP1–DP4 为已验收 plan,未开工)——「机械复制」类声称按上游 plan 的 SQL 草案原文核对。
> 评审日:2026-09-21。

## Verdict:**有条件过** —— 0×P0,1×P1;P1 为窄幅机械修复,修后即可开工与进 DP6

计划整体质量高:双 stage 裁决、九处授权换体的边界纪律、cgr/csh 推理链、ACL 面逐角色论证、实机实证台账与 gate 设计均经得起对抗性核对。唯一 P1 是三处源码扫描 gate(G1/G2/R2)按字面执行会对**本 plan 自己的 SQL 草案**与**已冻结的 DP4 SQL 注释**亮红——红上加绿(red-on-green),必须先定义扫描归一化。

---

## P1 清单(阻断首写轮通过;修后过)

### P1-1 源码扫描 gate 未定义归一化,按字面执行必红(涉 G1/G2/R2 三组)

- **位置**:§4 G1/G2/R2;§3.1 文件头注释;§3.2 文件头注释;§1.5 不变量 2/7/10 的执法面。
- **问题**(三个独立计数矛盾,全部按「字样子串扫描」口径):
  1. **G1** 断言「SQL_LOAD_ORDER 前 8 号文件**全文**零 `==>` 字样、零 `stannum` 字样」。但:
     - 文件 8 自身草案头部注释即含两词——`-- Zero stannum dependency (invariant 7): this file contains NO '==>' literal (gate G asserts).`(§3.1 文件头,plan 行 ~30);
     - 更硬的:**DP4 已冻结的 SQL 草案注释含 `stannum`**(DP4 plan 行 338「-- 包装;stannum 换 definition 归 DP5)」与行 902「-- …DP5 换 stannum highlight 同 tokenizer…」,均在 ```sql 块内,实施者机械复制)。DP5 自己立法「DP1–DP4 计划文件与其 SQL 文件零改动」(§1.1 硬边界)⇒ 文件 7 落地后必含 `stannum` 字样,且 DP5 无权清除。**G1 的 stannum 半边在正确实施下必然红,且无合法修复路径**(除非改 gate)。
  2. **G2** 断言「第 8 号文件全文零 EXECUTE 关键字」。但文件 8 末尾 ACL 块本身含三处:`REVOKE EXECUTE ON FUNCTION …` 与 `GRANT EXECUTE ON FUNCTION …`×2(§3.1 L9)。
  3. **R2** 断言「`==>` 逐文件计数:1–8 号零、**9 号恰 2**」。但 §3.2 草案按子串计数 ≥6:文件头注释 ×3(`'==>' operator lives in pg_catalog (text==>text … / text==>indexed_query …)`)+ recall v2 注释「所有 ==> 只经 EXECUTE」×1 + 两条 EXECUTE 字符串字面量 ×2。
  - 风险正在于 rubric 第 3 条:gate 红上加绿会逼实施者在压力下临时弱化(「只查可执行语句」的无定义读法)——执法面反而被掏空。
- **修法**(保持强度,三选一或组合;建议组合):
  1. **定义归一化扫描**:strip `--` 行注释与 `/* */` 块注释后再计数——G1/R2 的 `==>` 断言按归一化文本执行(1–8 号零、9 号恰 2,两处 EXECUTE 字符串字面量);G1 的 `stannum` 半边改为归一化文本零 `stannum.` schema 限定引用(散文注释里的 "stannum" 一词本就不是依赖面);
  2. **G2 改扫描形态**:「文件 8 零**动态执行形态**」——正则钉 `RETURN QUERY EXECUTE` / `EXECUTE` 后随字符串字面量起始(`'` 或 `$`),天然排除 GRANT/REVOKE EXECUTE ON;
  3. 顺带把文件 8/9 自己注释里的 `==>`/`stannum` 字样改写成散文(如「bind 算子」「S 扩展」),使文件 9 的**原始**子串计数即恰 2——但注意:DP4 注释清不掉,G1 的 stannum 半边无论如何必须走归一化(或限定名形态),这一点没有替代修法。
- 修后 R2 甚至可以加强:归一化计数 + 限定名双重断言,强度不低于原写法。

---

## P2 清单(归实施期;不阻断)

1. **死分支/错误码漂移**:§3.1 L4 `v_pol := v13_policy('recall_k')` 后的 `IF v_pol IS NULL`(及 §3.2 recall v2 的 `v_boosts IS NULL`)是死代码——DP1 的 `v13_policy` 缺行时直接 RAISE(默认 P0001「no active policy row…」),不返回 NULL。缺**行**的实际错误码是 v13_policy 的,不是 V3005;「缺**键**/非法域 V3005」仍然成立。删 NULL 臂或在 README/gate 注记真实路径(C4 负向族不测缺行即可)。
2. **附 B「六个 OR REPLACE」计数过期**:实际八处(§1.1 ①–⑧:bump/context_required/envelope/assemble + extract/recall/recall_count/verify)。§1.1 清单为准,附 B 改数。
3. **K5 绑定矩阵的「先静态对象后索引」单元缺失**:K5 的视图/静态函数 fixture 在 gate 库里创建于索引已在之后,「静态调用建于索引前→索引后建→DDL 无效化重绑」这一格(恰是设计作用力 2 的叙事格)未被行使。建议 K5 加一 fixture:临时表+静态函数先建→再 CREATE INDEX→断言命中(附 B 已实测该行为,钉进去零成本);否则未来版本回归 stale-static 绑定时此格空转。
4. **timeout 执法面注记**:驱动层 SET 只罩 parse(与 settle 经 DP1 驱动纪律);route/resolve 直调 assemble、三角色直调 recall 族的面无上限。README 驱动契约补一句「直调/审计会话须自设 statement_timeout」。
5. **extract_spans v2 丢了 v1 的输入界**:v1 对 terms 有 ≤64 词/词长 ≤256 的 fail-closed(V3004);v2 只校验 `{"tinql":string}` 形状,直调者可传无界 TINQL 进 stannum.highlight。v2 体内补 `PERFORM v13_tinql_terms(v_tinql)`(同界复用,零新文法)。
6. **csh 扩集的 request_hash 维度补一句**:附 A #3 只说「冷缓存」。精确语义:csh 是 effect envelope 语义词段(DP1 §3.6 #3),材料扩集 ⇒ 部署过渡后旧 pending 判断的 request_hash 域不再续用、needed 判断按新 csh 重问一次(DP2 builder 替换同款一次性代价;decisions 的 (session_id, request_hash) 去重域随 csh 收窄,语料变更后同题重问是诚实行为)。写进附 A #3/README,防 DP6 消费时误判缓存缺陷。
7. **I2 的 fixture 形态**:「加载后首个 ② 必不新鲜(八键 active token 失配)」在全新 DROP-CREATE 库里无八键 token 可言——需 owner 直插八键形态 active token 的守卫类 fixture(断言纪律已允许)再断言 ②/refresh/不活活锁。一句话钉明。
8. **B6 语料隔离是词法巧合不是结构隔离**:recall 族无 corpus 谓词,B6 靠查询词唯一化。设计未立 corpus 作用域召回的要求,建议 B6 注记「跨 corpus 词法命中是 by-design,隔离由查询词与 corpus 部署面承担」,或明确这不是 DP5 要立的要求。
9. **R5 表述**:「characterize 库上 DP1 四 stage…全部复跑」按括注的机制落(各 gate 在各自前缀库 + recall gate 在第 9 位库复跑)——DP 各 gate 脚本硬连各自 stage 库,补一句免歧义。
10. **highlight 嵌套标签假设**:哨兵字节换算在 highlight 产出嵌套/交叠标签时会错位;P3 fixture 覆盖常规形态,README 记假设与升级复测(与风险 5/12 合并)。

---

## Rubric 逐项

### 1. 可直接开工 —— **PASS**
- 两文件 SQL 草案完整(无省略号占位;envelope/assemble 全体内联+「从加载态机械复制」纪律,比复制 plan 文本更权威——DP3 风险 #1 同款);setup_db/test/README 四件形态齐;load.py 追加方式与 v12 实机制吻合(SQL_LOAD_ORDER/STAGE_THROUGH/files_through 均在 v12/load.py 实核)。
- OQ1–O9 全裁决且附依据;附 A 十一项分歧呈报;附 B 自检(14/9 顶层语句、分层依赖、V 码、jsonb 字面量、EXECUTE USING)抽核一致。
- 前向引用核验通过:文件 8 内 L1→L9、文件 9 内 EXTENSION→表→索引→换体,逐层仅依赖更早层/≤7 号文件对象(对照 DP1–DP4 草案逐一定位核实)。

### 2. 覆盖面 —— **PASS**
- §4.1:三禁(不变量 2+G/K/R)✓;canary(K6/L,专用表+split 索引,回落即红的行为半边 L2)✓;EXPLAIN 形状(K1 钉 0.1.0 实测形态 Custom Scan 且明拒 OR 宽化——宽化会把绑定退化漏检成绿,判断正确)✓;排序确定性(不变量 5+两代 ORDER BY 显式+聚合内钉序+双跑字节等)✓。
- §4.6:CJK 短语引用=构造形态(连续 CJK 段整体一个引号段,OQ7;A3「東京タワーの高さ quasar」逐字核对码区分类正确——の(U+306E)在 12352–12543 内并入段)✓;kohaku fixtures(A3/P4)✓;count 自适应 k(OQ5 公式+C1–C4/J,数值例核验:3→8、400→20、4000→64 截断均与公式一致)✓。
- §4.8 六件全落:fixture 灌入(K 组,经 DP4 驱动器四步)✓;绑定矩阵(K1–K5,含 P2-3 的加强建议)✓;fold 持锁 p99(M1/M2,segment_info 观测前置——fold 阈值未文档化的诚实处理)✓;verify_index+REINDEX(N1–N3)✓;>1024 回落(O1/O2 双层:编译器 64 段上限+引擎面直测钉行为)✓;外加 §4.7 尺寸刻画面(Q,DP4 契约③)。
- §7:T0 两代=双 stage 的字面兑现(第 8 位零 stannum 依赖/第 9 位加载即换体);T1/T2 只记触发(§7 台账,嵌入缓存行形态+embed=effect 纪律照抄)✓。
- §8:runbook 六件 R4 逐条+README 清单断言;cron 零新增(N4,「调度是行」红利论证核验成立——DP4 job 调 v13_verify_chunks(true),v2 换体自动覆盖);「索引可丢=性能事件非正确性事件」的论证(默认回退=最宽配置,实测)成立 ✓。
- §10 G-ctx3 四断言映射表逐条有 gate 落点 ✓;ch10 映射(§6)与 §13 对照零缺口 ✓;§12 不做(§7)逐行有触发条件 ✓。

### 3. gate 可执行不弱化 —— **FAIL(P1-1;余皆强)**
- 绑定矩阵执法:K3/K4/L2 用**语义分叉 fixture**(64B 精确块:bound 命中/回退漏召)断言实测降级面——未来 stannum 任何绑定回归(无论经 generic plan 还是别的路径)都会翻结果成红;R1 单索引结构断言+源码扫描为 belt;README 升级复测项闭环。执法充分。
- canary 物理已实测成立(专用表避免同列双索引歧义——歧义本身是实测立法,OQ6/附 A #10)。
- k 自适应+硬上限+延迟账落点齐:C3/J1 数字呈报、§4 末一页账表(k→批数→往返→量级,F5② 悬崖结构性封死的算术核验成立:64/32=2 批)。
- 除 P1-1 的三组扫描外,断言均可执行且不弱化(负向族、双连接、相对比较计数、守卫 fixture 纪律沿用)。

### 4. 不越界 —— **PASS**
- T1/bigram/boost 闭环/语义缓存只台账(§7);boost 非空 V3005 拒(语法未实证不虚标)✓。
- DP1–DP4 语义面只经授权缝:八处 OR REPLACE 全同签名(与上游草案逐一比对:recall (text,int)→TABLE 三列两代一致、count(text)、extract (text,jsonb)、verify(boolean)、context_required(uuid)、envelope(uuid)、assemble(uuid,int DEFAULT NULL)、bump trigger 函数);对既有表零 DDL ✓;复制体的 V 码保留(verify v2 的 V3004)✓。
- 前缀切片结构性零影响论证成立(DP1–4 gate 在各自库不载文件 8/9;八键 token 唯一存活于 ≤7 号库——与 DP4 同款墓碑注记)。

### 5. 承接面健康 —— **PASS**
- DP1 #59 cgr 并入 bump 面(OQ1 三点论证+无漏报论证四源闭合+反向保守弃批记档;probe 七键零改——七键清单与 DP1 §3.5 原文核对一致;锁面分析独立复核:ingest 事务持自身 effect 行+bump 行,与 settle 的 sessions→tools_meta→策略→(refresh 自身 effect 行)无共享 effect 行,无环成立;F5 双连接实证)。
- DP4 ①–⑨ 逐条:①F 组 ②N 组 ③Q 组 ④P3(签名/输出核验一致)⑤缝转发 DP6 的条件辨析(候选级 spans≠消费 span_assembly 策略)成立 ⑥E2 ⑦台账 ⑧转发 DP6 行⑥ ⑨三体内 JOIN superseded_by IS NULL 全在场。
- DP3 填充缝(E 组,goal echo 退役——DP3 §3.4 qside 原文核对,填充缝注释就在彼处)+token 第九键(OQ8;八键体与 DP4 §3.6 原文逐字比对,增量恰为一 DECLARE/一 RAISE/一键)。
- DP2 信封 20 键包含性:19 键键序/表达式与 DP2 §3.4+DP3 墓碑二(goal_hash 换 v13_goal_hash)合成形态逐键比对一致;唯一变更点=csh 材料扩集(见下)。
- stepfun F4:作「反向提示」消费可辩护——F4 的修复主体(pg_typesafe 刻画镜像)不在 DP5 范围,DP5 侧的六件真执行+runbook 全落是对称性要求的本半边;建议控制器确认 F4 的 typesafe 半边在后续 DP 有归属(非本 plan 阻断项)。F5:②本 plan 立法(一页账+硬上限)、①③DP7 行明文转发 ✓。

---

## 机械猎结果(六项)

| 项 | 结果 |
|---|---|
| EXECUTE 全 USING | **过**。recall v2 `EXECUTE … USING p_tinql, p_k`;count v2 `EXECUTE … INTO v_cnt USING p_tinql`;verify v2 的 `FOR … IN EXECUTE 'EXPLAIN…'` 为常量串无参数面(继承 DP4 v1 逐字)。动态串全部静态骨架‖拼接,零用户文本入串;`''tinql''` 转义与 `$$` 定界无冲突。 |
| 签名重复/前向引用 | **过**。八处换体同签名;每函数在每个前缀世界唯一存活形态;两文件内分层无前向(附 B 分层清单逐项核实)。 |
| 三值逻辑 | **过**。新代码无 NOT IN;策略形状校验 `jsonb_typeof IS DISTINCT FROM` NULL-安全;jud 消费集 `IN`+谓词滤 NULL(继承 DP3);`IF EXISTS(jsonb_array_elements(…))` 空=FALSE 语义正确。 |
| 哈希同源(csh 写读四面) | **过**。写=信封 rc CTE 单点;读四面全读存储值零重算:v13_snap_of 投影(DP1 行 1615)/v13_lock_key(行 1667)/effect envelope 语义段投影/probe 不读 csh(七键蕴含)⇒ 材料扩集只动写侧,无双实现。k/matched 入材料不入键与草案一致。 |
| jsonb 字面量 | **过**。策略种子 $j$…$j$::jsonb 单完整字面量(DP1 turn 8 教训形态);`'[]'::jsonb` 默认;分步 typeof 先验后 ::numeric(DP4 三律同款)。 |
| TINQL 转义/maybe_quote 双重转义 | **过**。弃 maybe_quote(实测多 token 才引号)改全引号;分段器把引号/空白/操作符字符全归分隔符 ⇒ 语段不含引号与 ' AND ' ⇒ 文法封闭零转义面;回析器 `position('"' in …)>0` 拒段内引号、`length<2`/首尾引号拒异形;往返 A4 可字节等(两 side 均位置序 jsonb 数组)。注入族 A5 逐 fixture 手推形状封闭成立。 |

---

## 重点推演

### 1. 作用力 2 未复现的处置 —— **安全**
- 处置结构:三禁保留为冻结 DDL 纪律(作用力 1 的审计理由独立于绑定机制)+ gate 改打实测降级面 + 附 A #1 呈报设计分歧(设计稿禁改)。这是对「引擎事实与设计叙述分歧」的标准处置形态。
- 未来版本回归设计描述(视图/静态/预备语句回落默认 tokenizer)时 gate 能否捕获:**能**。K5 的 canary fixture 是语义分叉的(64B 精确块:split 索引 bound 命中/默认回退漏召)——三禁路径任一回落 ⇒ 查询结果与 EXECUTE 对照不一致 ⇒ 红;K3/K4 断言的两个实测降级面(无索引回退/同列双索引错绑)与 R1 结构断言覆盖其余绑定病变;G/R 源码扫描为纵深 belt。**K1 拒绝 OR 宽化**的判断正确(宽化恰会把绑定退化漏检成绿)。
- 唯一空格:P2-3(先静态对象后索引的重绑格未行使)——补一个 fixture 即闭合,不改变结论。

### 2. csh 材料扩集对 DP1 时代哈希稳定性的影响 —— **不破坏,代价一次性且已披露**
- 旧信封 artifact:冻结不可变,旧 csh 原样存活 ✓。
- 水位免疫性(DP1 #3 的本意):新材料(needed∪recall)不含编排事件 ⇒ 编排事件仍不改 csh/effect 身份 ✓。
- 锁键去重:同推导同 csh 仍去重;语料分叉的两 parse 本就不是重复解析,各自付款后 decisions 层 (session_id,request_hash) 仍按需去重 ✓。
- 旧会话重 parse:材料公式变化 ⇒ 同状态新 csh ⇒ 旧 pending 判断的 request_hash 域不续用、needed 重问一次(部署过渡一次性;DROP-CREATE 世界无 mid-turn 换体)。附 A #3 以 DP2 builder 替换先例收口——先例核实成立(DP2 needed 形状扩展同样改 csh 值)。**语料变更⇒csh 变⇒同题重问**则是 DP5 起的常态语义,对 DP6 per-chunk 判断是正确方向(判断身份应含候选集);见 P2-6 的措辞补强。

---

## 附:复制忠实度核验记录(评审过程实地比对)

- 信封 19 键体:DP2 §3.4 SELECT 键序/表达式 + DP3 墓碑二 goal_hash——与 DP5 §3.1 L6 草案逐键一致;唯一增量=rc CTE/csh 材料/candidates 键 ✓。
- 装配体:DP3 §3.4 qside(goal echo 原文在 DP3 行 1001–1016,填充缝注释在场)与 jud CTE 逐字比对 DP5 草案一致;唯一增量=qside candidates 表达式+`|| decision_id` ✓。
- token:DP4 §3.6 八键体与 DP5 九键草案逐行比对,增量恰三处 ✓。
- bump:DP4 §3.1 原体单 UPDATE;DP5 换体追加第二条 UPDATE;触发器已挂(AFTER INSERT OR DELETE FOR EACH STATEMENT,OR REPLACE 保 OID)✓。chunks 无 UPDATE 面(chunks_immutable),「任何路径 DML」口径成立。
- verify v2:与 DP4 v1 全文比对,增量恰两处(DECLARE v_stan_bad+⑧行+version 2);V3004 保留 ✓。
- extract_spans v2:签名/输出形态/IMMUTABLE/256 上限与 DP4 契约④一致;哨兵字节换算公式独立复推(ASCII+CJK、跨 span 计数)正确;载荷约定换 tinql 对象——v1 无生产消费者(DP4 草案内零调用点,实核),调用方随同文件换体,零跨约定窗口 ✓。
- ACL:v13_recall 角色存在于 DP1 §3.1 DO 块;SELECT chunks 三表对 v13_recall 为 DP4 既有;resolve 半边前移有据(envelope invoker 链:resolve 执行信封→recall_candidates→SELECT chunks,不授则 parse 拒);route 半边有真实消费面——DP3 G4 已授 assemble 直调 EXECUTE 给 route/resolve(读面),换体后不授即断 ✓。V3005 无占用(DP1–4 逐文件 grep:V3001–V3004 各归其主)✓。
- 机制名:STAGE_THROUGH/files_through 与 v12/load.py 实文一致 ✓。

**探针事实(附 B)不可独立复验**(探针库已删);其内部一致性好,且 K/L/M/N/O 组在实施期实测同一行为——伪事实会在 gate 期响亮暴露,附 B 已自列实施期复测项(severity 词表/K5 升级复测)。接受。

## 静态核验

- 被审文档基线:`docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md`,1366 行,全文 8 段读完(1–240/241–500/501–760/761–1020/1021–1280/1281–1366)。
- 对照实读:设计稿 §4.1–§4.8/§7/§8/§10–§13;DP1(#59/#60/§3.1 v13_policy+DO 块角色/§3.3 lock_key/§3.5 七键探针/§3.6 effect envelope/probe 原文);DP2(§1.4/§3.4 十九键体全文/ACL);DP3(OQ1/OQ4/§3.4 qside+jud 原文/§3.5 DEFINER 面/G4/附 A);DP4(§1.4 ①–⑨/§3.1 bump/§3.4 verify v1 全文/§3.5 extract v1 全文/§3.6 八键体全文/ACL 行 1334/SQL 注释行 338·902);stepfun F4/F5 原文;v12/load.py 机制。
- 本评审未改动任何文件(本文件为新增);未运行任何 DDL/gate;探针库未重建。
