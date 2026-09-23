# v13 实现循环终局 6 条 erratum 悬置项处置裁决报告

> 日期:2026-09-23。性质:父级 Loop Orchestrate 控制器授权的 oracle 裁决会话产出(用户显式授权:对 v13 实现循环终局的 6 条 erratum 悬置项给出处理方案,控制器随后照案执行)。
> 裁决对象:终局呈报(turn 15,`prompt-exports/loop-orchestrate-v13-deep-plans-impl-runs.md`)列出的 6 条 erratum 悬置项。
> 边界遵守:纯只读勘探+本报告;未改任何 plan/代码/README/测试。
> 裁决方式:controller brief 下发 → 本会话独立核实材料(含对终局呈报的三处事实更正)→ **context_builder 管道两路独立 oracle**(ask_oracle 管道故障延续,按 B-DP7-1 先例降级;同份中性 brief、互不知晓)+ 本会话源码核证线为第三路 → 分歧逐条对照源码/文档/评审原文裁定。
> 产出角色:本报告 **§4 即总 erratum 文本汇总**(不另建 ledger 活文档——裁定 D1);四份 plan 文末追加节均指向本报告。

---

## 0. 结论一览

| # | 悬置项 | 终案 | 复跑 gate |
|---|---|---|---|
| **1** | 「恰两处」换体数与加载树不符 | **①+⑤**:dp4/dp5 两份 plan 文末各追加 Erratum 节,追认第三处(validator 八键)/第十处(validator 九键)授权缝(E-DP4-1/E-DP5-1);终局呈报的「dp3 §1.1」指认**更正为 dp4 §1.1**;dp7「七处→八处」已由 E-DP7-1 收口、dp8 六件合规,均不再立法 | 纯 docs,零复跑 |
| **2** | stannum 部署 ACL 授权缺口 | **①+④**:dp5 plan 文末 E-DP5-2 立法「授权落部署面」(蓝本=filter setup_db GRANTS;授权链=dp6 L4 §3.5+本裁决);**唯一回填=v13/characterize/setup_db.py**(recall 禁改——库无 stannum schema,回填必部署期失败)+ characterize gate 增 SET ROLE 真执行断言 | characterize gate 一次 |
| **3** | E-DP7-1/E-DP7-2/C-DP7-M1 | **③+①短指针**:三条全文维持「summary README 裁决授权节 + bdp7-1 oracle 报告 §4」双档为权威,dp7 plan 文末仅加 E-DP7-index 指针(不复述第三份全文) | 零复跑 |
| **4** | DP7 plan 键谱措辞残留 | **①**:dp7 plan 文末 E-DP7-3 订正 §1.2 消费清单 #15(≈:76)「8 键 token」孤立残留(残留定位=该行;正确谱系七→八→九→十→十一);正文 :76/:143/:179/:460-462 全部零改动 | 零复跑 |
| **5** | dp8 N-1/N-2 | **N-1=④**:test_periphery.py A5 文案 + periphery README 偏差#8 标签一行修(归因改 ×4 版,104/97/bare7 计数断言不动);**N-2=③**:记录层闭合(turn 15 全量复跑 228 已钉死,仓库零改动) | N-1:periphery gate 一次;N-2:无 |
| **6** | dp6 plan v2 节 A4/A11 只立法未实现 | **①**:dp6 plan 文末 E-DP6-1 显性化「只立法、依赖对象不在树、终局归属 RP 原生化线」(+E-DP6-2 一行部署 ACL 指针);不实现、不造对象、不记缺口 | 零复跑 |

**带外呈报(不在六条内,建议控制器另行排期)**:dp8 L4 §5(2026-09-23 追加的 Oracle 复核节)已把 69e5ebb 修订为「0P0/**1P1**/3P2/8P3、收官附条件」——F-1(latches 表 SELECT 未授 v13_resolve/v13_recall)P1 必修**在 HEAD(69e5ebb)仍未修**(本会话实证 `v13/periphery/v13_periphery.sql:2341-2342` 仅授 route);终局台账 turn 15 记的是修订前口径。详见 §1.4。

---

## 1. 证据核实(本会话独立复核;含对终局呈报的三处更正)

### 1.1 更正一:「恰两处」的出处是 dp4 plan §1.1,不是 dp3

- 「恰两处」全仓检索(docs/plans+docs/reviews+v13+prompt-exports)仅命中:`docs/plans/v13-dp4-chunks-projection-plan-2026-09-20.md` §1.1(:30)——「对既有对象的变更恰两处…①CREATE OR REPLACE FUNCTION v13_context_required(同签名换体、七键扩八键)…②对既有表 artifacts/decisions 各追加一个 BEFORE 触发器;其余全部是新增对象」;及 dp4 L4 边界#2、dp5 L4 边界#1、chunks README 台账⑨对其的引述。
- dp3 plan §1.1(:26-30)无该措辞:其列出的是**三个**换函数(v13_context_fresh/v13_probe/v13_judgment_envelope,「三形态」之形态一),且未被任何后位 stage 突破——dp3 plan 本轮零触碰。
- 实际悬置两笔,均为 L4 已裁定「保留机制+补 plan erratum、悬置交父循环」而至今未落 plan 的授权:
  - **dp4**:§1.1「恰两处」之外,实现另有第三处 `CREATE OR REPLACE v13_manifest_validate`(v13_chunks.sql:929,八键+corpus≥0)——dp4 L4 边界#2/P1-A「权威=plan,不是 README ⑤」;chunks README 台账⑨在档。
  - **dp5**:§1.1「共九处」封闭清单(①–⑨,见 dp5 L4 边界#1 逐项)不含 validator;第 8 位实现多一处九键换体(v13_recall.sql:276,+recall_ver≥1)——dp5 L4 边界#1/偏差①「须补 plan erratum」;recall README 台账①在档。
- 对照组(不立法):dp7 §1.1(:56)「七处 OR REPLACE」被第 8 处突破——已由 E-DP7-1 经 oracle 裁决收口(summary README「裁决授权」节+bdp7-1 §4 在档);dp8 §1.1 六件换体+latch_digest(DP3 §1.4 DP8 行预授权)实现合规(blob_land DROP+CREATE=dp8 L4 偏差#3 ACCEPT)。
- 加载树生产 SQL 的 `CREATE OR REPLACE FUNCTION` 终态分布(本会话清点):文件5=5/6=3/7=2/8=5/9=4/10=5/11=0/12=5/13=3/14=7(文件号=SQL_LOAD_ORDER 序位)——全部落在各 plan 授权清单+上述两笔待追认+E-DP7-1 已追认范围内。

### 1.2 更正二:键谱残留定位=dp7 plan §1.2 消费清单 #15(:76)「8 键 token」

- dp8 L4 §4-4 所指「『键集 7→8/八键』措辞」的具体行=dp7 plan :76:「OQ7:manifest v2(11 外层键+economics 块+7 键 policy+**8 键 token**+…)」——按 DP3 七键+econ_ver 误算 8,漏 DP4 corpus 与 DP5 recall_ver。
- 同 plan 其余键谱表述均已是正确谱(即 :76 是**孤立残留**):OQ7 裁决 :143「required_revision 10 键(加载态基九键+econ_ver)」;不变量 8 :179「token 十键(…turn 34 修订)」;换体一注释 :460-462「复制源=文件 8 九键体…键集 9→10…DP8 已在其 14 号恢复十一键全谱(turn 33 终检 P1 修正)」;E1 :867/E4 :870。且 :93 声明 OQ 裁决节「本节为最终权威」。
- 键谱谱系(dp8 L4 §2.5 实证+gate I1 恰等断言):DP3 七键 → DP4 +corpus 八 → DP5 +recall_ver 九 → DP7 文件12 +econ_ver 十 → DP8 文件14 +ident_ver 十一(={sem,dec,goal,tools_rev,asm_ver,jdef_ver,gen_ver,corpus,recall_ver,econ_ver,ident_ver})。
- 终局呈报称「plan 循环终检附 A #1 指 DP8 14 号文件恢复十一键」——附 A #1(token 十一键谱恢复)实为 **dp8 plan** 的附 A 主呈报项(dp7 plan 附 A 是「分歧点清单」14 条,无键谱项);dp7 plan 内对 DP8 恢复十一键的指认在 :462(正确句)。

### 1.3 更正三:部署期 ACL 现状=五带二缺,且 recall 的「缺」是正确状态

- 五处已带同款 GRANTS 块:`v13/{filter,memory,economy,summary,periphery}/setup_db.py`——`GRANT USAGE ON SCHEMA stannum TO v13_recall,v13_resolve,v13_route` + `GRANT EXECUTE ON FUNCTION stannum.score_bound(...),stannum.score_bound_indexed(...) TO 同三角色`,位置=load_stage 之后、run_probes 之前(蓝本=filter,其注释写明「授予放部署面(setup_db,run_probes 同位),不进 SQL 文件」)。
- `v13/characterize/setup_db.py` 未带(main 只有 probe→DROP/CREATE→load_stage→run_probes)——characterize 是 stannum 扩展首次出现的库(文件 9;`stannum.full_score/highlight/verify_index` 限定名各一,dp5 L4 R2 口径「9 号恰 3」与本次 grep 一致),是**唯一需要回填的库**。
- `v13/recall/setup_db.py` **禁止回填**:第 8 位前缀库零 stannum 依赖(recall README 不变量 7「本 stage 零依赖 text-search 扩展」;v13_recall.sql 全文 0 个 stannum 引用,本次 grep 实证)——对不存在的 schema 执行 GRANT USAGE 将在部署期失败,recall gate 会由绿变红。终局呈报材料中「两 setup_db GRANTS 块=收口蓝本」表述正确,但若读成「recall/characterize 都要回填」则对 recall 一半不成立,本报告显式钉死。
- 角色链需要该 ACL 的调用面在 filter(10)/memory(11) 起的 stage 库才存在(trace/reader 链),五个库均已带块——故 14 gate 全绿与缺口定性「影响生产装载路径」并存,当前无红 gate、无已破生产路径;回填 characterize 是补全「扩展首次出现的库」的自洽性+为 SET ROLE 真执行断言提供落点。

### 1.4 带外发现(超出六条,呈报不越权):dp8 L4 §5 修订节未被终局呈报携带

dp8 L4(`docs/reviews/v13-dp8-impl-l4-review-2026-09-23.md`)§5「Oracle 复核(2026-09-23 追加;本节修订 §0/§4 部分结论」:

- 69e5ebb 发现计数由「0P0/0P1/0P2+5P3」修订为 **0P0/1P1/3P2/8P3**;dp8 收官=**附条件**(先修 P1);可进终局=**修复提交+定向复跑后可**。
- **F-1(P1,必修,HEAD 未修)**:latches 表 SELECT 未授 v13_resolve/v13_recall——14 号换体后 6 号授予的 identity/assemble 族 EXECUTE 在 INVOKER 链上运行时断裂;修复=一行 `GRANT SELECT ON latches TO v13_resolve, v13_recall` + A6 增 SET ROLE 真执行断言。本会话实证:`v13_periphery.sql:2341-2342` 仅 `GRANT SELECT ON TABLE latches TO v13_route`;git HEAD=69e5ebb,无修复提交。
- 同节还登记 E-DP8-1(A12 立法≠落地)/E-DP8-2(probe 返回值)/E-DP8-3(streak 语义)三条追加 erratum 与 F-2..F-13,并立法教训「ACL 类验收必须含 SET ROLE 真执行,权限位断言不充分」。
- 终局台账 turn 15 记录的是修订前口径(「0P0/0P1/0P2…5 条 P3 注记无必修」),六条悬置清单未携带 §5 修订。**本裁决不越权处置 F-1 等**——建议控制器在执行本方案后立即排期 dp8 L4 §5.3-3 规定的「修复提交」(F-1 必修;建议同批 F-2/F-4/F-5 一行级顺手件)+periphery gate 复跑。该教训已反哺本报告项2 的 SET ROLE 断言裁定(D3)。

### 1.5 其余基线事实(复核通过,供执行者免重查)

- 项3:E-DP7-1/E-DP7-2/C-DP7-M1 三条逐字登记于 `v13/summary/README.md`「## 裁决授权:第 8 处 OR REPLACE(refresh 换体)」(:15 起,含条件回退条款);裁决原文=`docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md` §4;该裁决自身声明「plan 冻结不改」。
- 项5-N1:实际归因=context_required×4+refresh×2+blob_land×1(validate 的 RAISE 全部带 ERRCODE、零 bare;dp8 L4 §3 N-1/§5.2 F-10);现标签在 `v13/periphery/test_periphery.py:385-388` 与 `v13/periphery/README.md:78`(偏差#8);计数断言 `raises==104 and errcoded==97` 正确不动。
- 项5-N2:turn 14 台账记 228;dp8 期 8c31ccb 首次复跑呈「基线 227+净增 1=228」(静态调用点 176→177 证净增 1);turn 15 全量复跑 14 gate 全绿、summary 228 钉死。仓库内无 227 口径残留(227 仅在 dp8 L4 N-2/F-11 注记行,属评审档案,不改)。
- 项6:v13 全树(72 文件)零 `bootstrap_done`、零 `v13_file_vetoes`(本会话检索实证);dp6 L4 §5 悬置移交原文:「A4(bootstrap_done 论域闸)/A11(file veto)为『只立法不实现』状态…归属 RP 原生化线消费,与 dp6 两提交无关,不构成缺口;移交父循环在 DP7+」;消费方=RP 原生化线(docs/analysis/repoprompt-native-on-v13-feasibility-v2-2026-09-21.md 与 v13.1 方案)。dp6 plan v2 节自述(:1980)「本轮不 invent 新里程碑实现、不改 SQL 代码」+编号铁律(:1981)。
- 先例:dp5 L4 边界#2 对 v2 `v13_visible_files` 未实现裁 ACCEPT(plan v2 节明文「不在两里程碑另开实现」)、不记缺口——项6 同型但 dp6 v2 节的「改动点」列读感更接近本 plan 范围,故加文末显性化(见 §3-6 理由)。

---

## 2. Oracle 三角记录

### 2.1 三路执行情况

| 路 | 模型/渠道 | 状态 | 结论摘要 |
|---|---|---|---|
| R1 | context_builder 管道·grok-4.6 @xhigh(chat `v13-erratum-处置裁决-D94839`) | ✅ 完整 | 六条全收口零回滚;项1 双 plan 文末追认;项2 落 characterize 部署面+recall 禁改(其「元发现 P1」独立指出 recall 库无 stannum);项3 指针;项4 文末订正不就地改;项6 归属 RP 线;另建 ledger 文件 |
| R2 | 同次分组请求·grokBuild grok-4.7-build-fast-xhigh(chat `v13-erratum-处置裁决-oracle--EE7E8F`,与 R1 同 brief 互不知晓) | ✅ 完整 | 同样四份 plan 文末+characterize GRANTS+SET ROLE 断言+N-1 标签修;项3 主张全文复本进 plan;反对另建 ledger 活文档;独立复核 recall 禁改并给出 SET ROLE 断言的停机条件(红因非 42501 族即停) |
| R3 | 本会话源码核证线(全部 file:line 亲读+grep 清点) | ✅ | 两路共识逐条复核通过;两处初判与复核(见 D4);三项终局呈报更正(§1.1-1.3);带外发现 dp8 L4 §5(§1.4) |

(注:ask_oracle 直连管道本日仍延续 MCPToolExecutionCancelledError 故障,按 B-DP7-1 先例降级为 context_builder 分组管道,一次分组请求产出两条独立 lane——与 dp8 L4 §5 的复核渠道同型,如实记录。)

### 2.2 三路一致点(经本会话源码复核通过)

1. 六条全部可收口:零回滚、零 plan 正文改动、零 gate 断言弱化。
2. 「恰两处」锚点在 dp4 §1.1 非 dp3 §1.1;dp3/dp8 plan 本轮零触碰。
3. 项1 两笔 validator 换体授权**必须落 plan**(dp4/dp5 L4 原文「权威=plan,README 台账不能替代」),形态=文末追加,正文原句保留。
4. 项2 授权落点=部署面 setup_db;蓝本=filter GRANTS 块;唯一回填=characterize;**recall 禁改**(库无 stannum schema);GRANT 不进 SQL 文件(会破 filter H6/memory K4/R2 扫描断言);load.py 本轮不动。
5. 项4 残留在 dp7 plan :76;正文(含 :460-462 的 9→10 正确句)零改动;以 OQ7 裁决节为权威。
6. N-1=标签一行修(104/97 计数不动);N-2=记录层闭合零仓库改动。
7. 项6 立法保持、归属 RP 线显性化、不实现对象、不记缺口。

### 2.3 分歧与裁定

| # | 分歧 | 各方立场 | 裁定+证据 |
|---|---|---|---|
| **D1** | 总 erratum 文档形态(⑤) | R1:另建 `docs/reviews/v13-erratum-ledger-2026-09-23.md` 索引表;R2:不另建(「会与 plan 文末抢权威」),裁决报告自身落盘即索引 | **裁定=R2**。本报告 §0/§4 即总索引与文本汇总,单一事实源;四份 plan 的 erratum 节+本报告互指,不再生第三份可漂移文件(仓库单源纪律)。R1 的索引表内容已吸收进本报告 §0 |
| **D2** | 项3 在 dp7 plan 的形态 | R1:短指针(不复述全文);R2:三条全文逐字复本进 plan(「plan 入口读者不必跳转」) | **裁定=R1 短指针**。全文已有双档(bdp7-1 §4+summary README 逐字),第三份复本=漂移面×3;指针一次跳转+条件回退条款引用即封住「§1.1 七处」的入口误读;单源纪律优先于跳转成本 |
| **D3** | characterize SET ROLE 真执行断言 | 两路均要求;本会话核证其法源强度 | **裁定=纳入执行(与 GRANTS 同提交 B)**。法源三重:dp6 L4 §5 处方原文「+dp5 gate 补断言」;dp8 L4 §5.3-5 教训立法「ACL 类验收必须含 SET ROLE 真执行,权限位断言不充分」;「只加不减」纪律。附 R2 停机条件:断言红且红因非 42501 族(如缺 chunks SELECT)即停手报告,本提交只允许蓝本 GRANTS(+E-DP5-2 授权的同面追加) |
| **D4** | 两路引用的 dp8 L4「F-1..F-13/E-DP8-*」 | 本会话初判为幻觉引注(§0-§4 实读仅 N-1..N-5)→ 复核 dp8 L4 :137-206(§5 追加节)后**撤回初判** | F-*/E-DP8-* 真实存在于 dp8 L4 §5;两 lane 的引注采信。教训入档:**「未读到的段落」先于「对方幻觉」假说**——先例纪律「只采信经复核的事实」双向生效(既不采信未复核的 oracle 主张,也不轻断 oracle 幻觉)。F-1 等系带外项,呈报不越权(§1.4) |
| **D5** | N-1 提交拆分 | R1:test+README 同一笔(stage 内单一主题);R2:test 归代码提交、README 归 docs 提交 | **裁定=R1**。仓库先例=stage 五件套(含 README)随里程碑同提交;AGENTS「docs 提交不混代码」约束的是 docs/ 目录文档;periphery README 是 stage 工件,与 test 同笔+同次 gate 复跑覆盖两者 |

---

## 3. 六条终案(形态+理由+执行面)

### 3.1 项1——dp4/dp5 两笔 validator 换体授权落 plan

**形态=①(两份 plan 文末各一节)+⑤(本报告收录对照与更正)。** 不选②(冻结正文不改弱,追加即可达 L4 要求的「权威=plan」);不选③(两份 L4 均已明文裁定要补 plan erratum,维持 ③=把已裁定的 P1-A 再悬置一轮);不动 SQL(④ 不适用——机制必须保留,dp4 L4「无此缝则 G2 真链路必 V3003」、dp5 L4「无此缝则 E1/I2 不可达」)。
误导面:未来读者以 §1.1 封闭清单做审计基线,会把两处机制上不可删的换体判成越权。修订风险:文末追加,零正文触碰。
执行面:只改两份 plan 文末;纯 docs 零复跑;chunks/recall README 台账保持(记录层,已准确)。

### 3.2 项2——stannum 部署 ACL:立法落 dp5 plan 文末+characterize 回填+真执行断言

**形态=①(E-DP5-2)+④(setup_db 回填+gate 断言)。** 落点法源:dp6 L4 §3.5「唯一合法落点=部署面」(filter H6/memory K4 扫描断言封死 SQL 内授权;§1.1 禁改上游 SQL);缺口定性=DP5 面;「不宜作 dp7 首工作项」的前提(dp7 未完成)已消灭,终局即收口时点。授权链=dp6 L4 §3.5+§5 悬置移交+本裁决。
唯一回填=characterize(扩展首次出现的库,尚缺蓝本块);**recall 禁止回填**(§1.3);五个已带块的不动;load.py 本轮不统一(共享装载器需对无扩展前缀做存在性守卫,超出一行修,记不做)。
误导面:只读 dp5 SQL 的部署者会漏 USAGE/EXECUTE,角色链 42501;正文改 ACL 章节会碰冻结 SQL 草案,故立法落文末+部署面一行。
执行面:见 §5 提交 B(含 SET ROLE 断言与停机条件,裁定 D3)。

### 3.3 项3——E-DP7 三条:双档为权威,plan 加短指针

**形态=③+①短指针(E-DP7-index)。** 全文已双档(bdp7-1 §4 裁决原文+summary README 逐字复本含条件回退);再抄第三份=漂移面(裁定 D2)。误导面=dp7 §1.1「七处」对 plan 入口读者仍像「refresh 换体越权」——短指针(声明突破已经 oracle 裁决收口+权威副本两处路径+推翻条款)即封住,零复述。
执行面:只改 dp7 plan 文末;README/oracle 报告零改;零复跑。

### 3.4 项4——dp7 plan :76「8 键 token」孤立残留:文末订正

**形态=①(E-DP7-3,与 E-DP7-index 同节)。** 不选②:本轮约束正文零改;且就地改摘要行会制造「冻结正文被改过」假信号(:93 已立 OQ 节为最终权威,:143 本来就正确)。不选纯⑤:既然项3 已决定在 dp7 文末加节,同节订正近乎零成本,把修正放在被误导读者的入口处。
执行面:只改 dp7 plan 文末;:76/:143/:179/:460-462/:867/:870 全部零改动;零复跑。

### 3.5 项5——N-1 标签一行修;N-2 记录闭合

**N-1=④**:只改 check 文案与 README 标签(计数布尔式 `raises==104 and errcoded==97` 不动——动了才是弱化)。**N-2=③**:turn 15 全量复跑已把 228 钉死为终局口径,227 仅存于 dp8 L4 评审注记(历史档案,不改——改了反而抹掉当时的记录);本报告 §0 记一行闭合。
执行面:见 §5 提交 C。

### 3.6 项6——A4/A11 只立法:文末显性化+RP 线归属

**形态=①(E-DP6-1)+③。** 不实现、不造对象(④ 反向);不升级为缺口(dp6 L4 已裁「不构成缺口」,先例=dp5 L4 边界#2)。与 dp5 visible_files 案的差别:dp6 v2 节「改动点」列读感接近本 plan 范围而对象从未落地,且移交句指向的「DP7+」已全部交付完——不在 plan 文末盖章,后来读者会把已结束的移交读成 v13 仍欠一个 stage。文末一节把「只立法/对象不在树/归属 RP 线/接线只加不减」钉死,误导面即闭合。
执行面:只改 dp6 plan 文末(顺带 E-DP6-2 一行部署 ACL 指针);零复跑。

---

## 4. 可粘贴 erratum 文本全文(执行者直接照贴)

### 4.1 `docs/plans/v13-dp4-chunks-projection-plan-2026-09-20.md` 文末

```markdown

## Erratum（实施期裁决，2026-09-23）

> 追加节，正文零改动。权威链：dp4 L4 边界#2 / P1-A
> （docs/reviews/v13-dp4-impl-l4-review-2026-09-22.md）→ 本节追认；
> 实施提交 `7b619ab`；终局裁决 docs/reviews/v13-impl-erratum-resolution-2026-09-23.md 项1。

E-DP4-1（§1.1 封闭清单漏计第三处换体；正文原句保持）：

§1.1「对既有对象的变更恰两处」未计实现必要缝：
`CREATE OR REPLACE FUNCTION v13_manifest_validate`（同签名；
`required_revision` 闭集七键→八键（+`corpus`），并校验 `corpus ≥ 0`；
其余段落与七键原体同构）。具身=`v13/chunks/v13_chunks.sql`（八键体）；
DP3 源文件 `v13/manifest/v13_manifest.sql` 零改动，前缀库不加载第 7 号
文件、七键体照常。无此缝则 token 扩 `corpus` 后真实
parse→advance→settle 必 V3003（gate G2）。封闭清单按本节补计为三处；
权威=本节+实施文件，`v13/chunks/README.md` 台账⑨为记录层。本节范围
止于 corpus 八键；`recall_ver` 九键同步见 dp5 plan 文末 Erratum（E-DP5-1）。
```

### 4.2 `docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md` 文末（一节两条）

```markdown

## Erratum（实施期裁决，2026-09-23）

> 追加节，正文零改动。权威链：dp5 L4 边界#1/偏差①
> （docs/reviews/v13-dp5-impl-l4-review-2026-09-22.md）、dp6 L4 §3.5+§5
> （docs/reviews/v13-dp6-impl-l4-review-2026-09-22.md）→ 本节追认；
> 实施提交 `828556f`/`1ed9837`（validator 九键）、`e4c5646`/`29a8a10`
> （部署 ACL 蓝本）；终局裁决 docs/reviews/v13-impl-erratum-resolution-2026-09-23.md 项1/项2。

E-DP5-1（§1.1「共九处」漏计 validator 九键换体；正文原句保持）：

§1.1 ①–⑨封闭清单未列 `v13_manifest_validate`。第 8 位文件
`v13/recall/v13_recall.sql` 另有同签名 OR REPLACE：
`required_revision` 八键→九键（+`recall_ver`，校验 `recall_ver ≥ 1`），
其余段落与八键体同构。谱系：DP3 原体七键 → DP4 第三处八键
（E-DP4-1）→ 本处九键；DP7 文件 12/13、DP8 文件 14 对同一函数的再跳
在各自 plan 授权清单内（至文件 14 为十一键，含 `ident_ver`），不在
本节重开。无此缝则 E1/I2 真实 settle 必 V3003。封闭清单按本节补计
为十处；权威=本节+实施文件，`v13/recall/README.md` 台账①为记录层。

E-DP5-2（stannum 部署 ACL：授权落部署面；SQL 文件内授权结构性封死）：

dp5 引入 stannum 引擎依赖（第 9 位 characterize 起生效；第 8 位
recall 零依赖=其 README 不变量 7）。引擎侧仅 `full_score` 有 PUBLIC
EXECUTE；stannum schema 未授 USAGE、`score_bound`/`score_bound_indexed`
为 owner-only——角色身份执行的引擎限定调用链 42501。授权与收口：

- 落点=部署面 `setup_db.py`（`load_stage` 之后、`run_probes` 同位），
  不进 SQL 文件：filter H6「零 `stannum.` 限定名」/memory K4「恰 3」
  扫描断言封死 SQL 内授权；本 plan §1.1 硬边界禁改上游 SQL。
- 蓝本=`v13/filter/setup_db.py` GRANTS 块（`GRANT USAGE ON SCHEMA
  stannum` + `GRANT EXECUTE ON FUNCTION stannum.score_bound(...) /
  stannum.score_bound_indexed(...)`，角色 `v13_recall, v13_resolve,
  v13_route`）。filter/memory/economy/summary/periphery 五处已带同款
  块，保持原样。
- 终局追认的唯一回填=`v13/characterize/setup_db.py`（扩展首次出现
  的库）。`v13/recall/setup_db.py` 禁止回填——第 8 位前缀库无
  stannum schema，GRANT 将在部署期失败。
- gate 侧：characterize gate 增 SET ROLE 真执行断言（权限位断言
  不充分——dp8 L4 §5.3-5 教训）；若真执行暴露蓝本外的引擎函数
  ACL 需求，同面（setup_db）追加，仍不进 SQL。
```

### 4.3 `docs/plans/v13-dp6-filter-memory-plan-2026-09-20.md` 文末（一节两条）

```markdown

## Erratum（实施期裁决，2026-09-23）

> 追加节，正文与 v2 对齐节既有 inline `ERRATUM:` 行零改动。权威链：
> dp6 L4 §5 悬置移交（docs/reviews/v13-dp6-impl-l4-review-2026-09-22.md）
> → 本节收口；实施提交 `e4c5646`/`29a8a10`；终局裁决
> docs/reviews/v13-impl-erratum-resolution-2026-09-23.md 项6/项2。

E-DP6-1（v2 对齐节 A4/A11 只立法；依赖对象不在 v13 树；终局归属 RP 线）：

A4（`bootstrap_done` 论域闸：file corpus 存在性 Noul 仅
`bootstrap_done=true` 后允许）与 A11（`v13_file_vetoes(p_sid)` 人
veto，deselect 高于超集）维持 v2 节立法原文：只立法、不实现、不改
SQL。v13 现树（14 stage 全交付后）零 `bootstrap_done`、零
`v13_file_vetoes`（检索实证）——不构成 dp6 两提交的实施缺口；DP7/
DP8 亦未实现。终局归属：消费与对账归 RP 原生化线
（docs/analysis/repoprompt-native-on-v13-feasibility-v2-2026-09-21.md
及 v13.1 线），接线时按 v2 节既有 `ERRATUM:` 行对账、只加不减。
先例同型：dp5 L4 边界#2 对 `v13_visible_files` 未实现裁 ACCEPT、
不记缺口。

E-DP6-2（部署 ACL 指针）：

stannum schema/函数部署期 ACL 的定性与授权见 dp5 plan 文末
Erratum（E-DP5-2）。本 DP 两 `setup_db.py` 的 GRANTS 块是蓝本实例，
不是授权源；本 DP SQL 零改动。
```

### 4.4 `docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md` 文末（一节两条）

```markdown

## Erratum（实施期裁决，2026-09-23）

> 追加节，正文零改动、不新授权。权威链：
> docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md §4、
> docs/reviews/v13-dp8-impl-l4-review-2026-09-23.md §2.5/§4/§5 → 本节；
> 终局裁决 docs/reviews/v13-impl-erratum-resolution-2026-09-23.md 项3/项4。

E-DP7-index（指针，不复述全文）：

§1.1「七处 OR REPLACE」被文件 13 对 `v13_refresh_context` 的第 8 处
换体（文件 13 第 3 处）突破——矛盾为数学结构性，已经控制器核实+
用户授权+三路 oracle 裁决（方案 D）收口，plan 正文按该裁决冻结不改。
三条登记原文（E-DP7-1/E-DP7-2/C-DP7-M1）与条件回退条款的权威副本：
①docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md §4；
②`v13/summary/README.md`「裁决授权：第 8 处 OR REPLACE（refresh
换体）」节。L4 检查点 1（授权先验）已在实施验收通过。若该授权被
推翻：回退=summary 消费延期（M2 记 blocked/deferred），不得弱化
O1/O3 断言假绿。

E-DP7-3（§1.2 消费清单 #15「8 键 token」孤立残留；正文原句保持）：

§1.2 #15 行内「8 键 token」为残留误算（按 DP3 七键+`econ_ver` 计 8，
漏 DP4 `corpus` 与 DP5 `recall_ver`）。本 plan 权威谱以 OQ 裁决节
（§1.3 开头声明「本节为最终权威」）为准：OQ7=`required_revision`
10 键（加载态基九键+`econ_ver`）；不变量 8=token 十键（turn 34
修订）；换体一注释=复制源文件 8 九键体、键集 9→10、DP8 已在 14 号
恢复十一键全谱；E1/E4 同谱。正确谱系：DP3 七键 → DP4 +corpus 八 →
DP5 +recall_ver 九 → 本 plan 文件 12 +econ_ver 十 → DP8 文件 14
+ident_ver 十一（{sem,dec,goal,tools_rev,asm_ver,jdef_ver,gen_ver,
corpus,recall_ver,econ_ver,ident_ver}；dp8 gate I1 `string_agg`
字典序恰等钉死）。#15 后半「chunk_filter 不入 token」语义不受影响。
```

### 4.5 N-1 标签替换文本（提交 C 用，两处同义）

`v13/periphery/test_periphery.py` A5 段 check 文案替换为（布尔式不动）：

```python
        check("A5: RAISE/errcode paper checkpoint (104/97; bare 7 = verbatim "
              "copies: context_required per-input ×4 + refresh entry ×2 + "
              "blob_land produced_by ×1; validate RAISEs all carry ERRCODE)",
              raises == 104 and errcoded == 97, (raises, errcoded))
```

`v13/periphery/README.md` 偏差#8 括号内标签替换为：

```text
（裸 7 条=机械复制体逐条在案：context_required 每输入 ×4+refresh 入口 ×2+blob_land ×1；validate 的 RAISE 全部带 ERRCODE、不计入 bare）
```

（34/104/97 三个计数数字两处均保持。）

### 4.6 N-2 记录条（落本报告，仓库零改动）

```text
E-DP8-N2（记录层闭合，不改仓库）：
  循环台账 turn 14 记 summary gate 228 PASS；dp8 期 8c31ccb 提交信息
  写「基线实跑 227+净增 1=228」（静态 check( 调用点 176→177 证净增 1）。
  终局 turn 15 全量复跑 14 gate 全绿、summary=228，以实跑为准钉死。
  仓库内无 227 口径残留（227 仅存于 dp8 L4 N-2/F-11 评审注记，属历史
  档案不改）。授权：dp8 L4 §3 N-2/§5.2 F-11。
```

---

## 5. 执行清单（文件级；提交拆分+复跑；按 AGENTS.md 纪律）

三笔提交相互独立；顺序建议 A→B→C（B/C 可并行准备）。每笔：改完→跑该笔触碰的 gate（退出码 0）→按路径逐项 `git add`→`git status` 复查→`git commit -m "v13: <祈使句摘要>"`→`git push origin main`。任一笔 gate 红即停在该笔，不推进后续。禁 `git add -A`/`--no-verify`/force-push。

### 提交 A —— docs only（零复跑）

```bash
git add docs/plans/v13-dp4-chunks-projection-plan-2026-09-20.md
git add docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md
git add docs/plans/v13-dp6-filter-memory-plan-2026-09-20.md
git add docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md
git add docs/reviews/v13-impl-erratum-resolution-2026-09-23.md
git commit -m "v13: append 2026-09-23 implementation errata to dp4-dp7 plans"
```

内容=§4.1–4.4 四节 erratum 追加+本报告落盘。**不得**把 `docs/reviews/v13-dp2*.md` 等 9 份既有未跟踪 L4 评审卷进本笔（其提交处置不在本次范围）。

### 提交 B —— characterize 部署 ACL（代码；gate 复跑一次）

改动：
1. `v13/characterize/setup_db.py`：`load_stage` 之后、`run_probes` 之前插入 filter 蓝本 GRANTS 块+`run_psql(s, DB, GRANTS)`（注释写「DP5 部署面，蓝本=filter setup_db；E-DP5-2 授权」）。
2. `v13/characterize/test_characterize.py`：增一条 SET ROLE（`v13_resolve` 或 `v13_recall` 至少一路）真执行召回链断言，`finally` RESET ROLE；既有断言只加不减（含 R 组「9 号 `stannum.` 恰 3」扫描）。**停机条件**：断言红且红因非 42501 族（如缺 chunks SELECT）→ 停手报告，本笔只允许蓝本两条 GRANT（+E-DP5-2 授权的同面追加）。

```bash
uv run python v13/characterize/test_characterize.py   # 退出码 0 后：
git add v13/characterize/setup_db.py
git add v13/characterize/test_characterize.py
git commit -m "v13: grant stannum deploy ACL on the characterize database"
```

不 add：recall/filter/memory/economy/summary/periphery 的 setup_db（recall 禁改，其余五处已带不动）。

### 提交 C —— periphery N-1 标签（代码+stage README；gate 复跑一次）

改动：`v13/periphery/test_periphery.py` A5 check 文案 + `v13/periphery/README.md` 偏差#8 标签（§4.5 文本；104/97/bare7 计数与断言布尔式不动）。

```bash
uv run python v13/periphery/test_periphery.py   # 退出码 0 后：
git add v13/periphery/test_periphery.py
git add v13/periphery/README.md
git commit -m "v13: correct periphery A5 bare-RAISE attribution"
```

### 呈报项（不在本波，建议控制器排期）

dp8 L4 §5.3-3 规定的「修复提交」：F-1 必修（`GRANT SELECT ON latches TO v13_resolve, v13_recall;` 一行入 `v13_periphery.sql` §3.8 ACL 块+A6 增 SET ROLE 真执行断言）+建议同批 F-2/F-4/F-5 一行级件+periphery gate 复跑——该修复在 HEAD(69e5ebb) 未落，dp8 收官的附条件未达成。E-DP8-1/2/3+F-10/F-11/F-12 已由 dp8 L4 §5 自行登记，随 9 份评审文档归档即可。

---

## 6. 不做清单

- **plan 正文零改动**：dp4「恰两处」、dp5「共九处」、dp6 v2 节 A4/A11 与既有 inline `ERRATUM:`、dp7 §1.1「七处」/:76「8 键 token」/:460-462「9→10」等全部原句保留；只允许文末追加节。
- **不改 dp3/dp8 plan**：「恰两处」锚点不在 dp3；dp8 六件换体维持 L4 合规结论。
- **不改任何 SQL 函数体**；不把 GRANT 写进任何 `*.sql`（会破 filter H6/memory K4/characterize R 组扫描断言）。
- **不给 `v13/recall/setup_db.py` 加 GRANT**（第 8 位库无 stannum schema，部署期必失败）。
- **不改 `v13/load.py`**；不删/不并 filter/memory/economy/summary/periphery 五处既有 GRANTS 副本。
- **不弱化任何 gate 断言**（A5 104/97、R 组恰 3、O1/O3、M1a/M1b/M1-neg）；断言只加不减。
- **不回滚** validator 八/九键换体、refresh 第 8 处换体；不撤回 A4/A11/v2 立法。
- **不实现** `bootstrap_done`/`v13_file_vetoes`/`v13_visible_files`。
- **不在 dp7 plan 复述 E-DP7-1/E-DP7-2/C-DP7-M1 第三份全文**（双档为权威+短指针）。
- **不另建 ledger 活文档**（本报告即总索引与文本汇总——裁定 D1）。
- **不处置** 9 份未跟踪 L4 评审文档的提交；**不处置** F-1/F-2..F-13/E-DP8-*（带外呈报项，另波）。
- 不 `git add -A`/`git add .`；不 `--no-verify`；不 force-push `main`。
- 本裁决轮自身只写本报告，不改任何 plan/代码/README/测试。

## References

- 终局台账：`prompt-exports/loop-orchestrate-v13-deep-plans-impl-runs.md`（turn 13/13b/14/15）
- 先例裁决：`docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md`（§4 授权登记原文/结构范本）
- L4 评审：`docs/reviews/v13-dp4-impl-l4-review-2026-09-22.md`（边界#2/P1-A）、`v13-dp5-impl-l4-review-2026-09-22.md`（边界#1/偏差①/边界#2）、`v13-dp6-impl-l4-review-2026-09-22.md`（§3.5/§4 P1-1/§5 悬置移交）、`v13-dp7-impl-l4-review-2026-09-23.md`、`v13-dp8-impl-l4-review-2026-09-23.md`（§2.5/§3 N-1 N-2/§4/§5 Oracle 复核修订节）
- plans：`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md`（§1.1 :26-30）、`v13-dp4-…md`（§1.1 :30）、`v13-dp5-…md`（§1.1）、`v13-dp6-…md`（v2 节 :1977-2019）、`v13-dp7-…md`（:56/:76/:93/:143/:179/:460-462/:867/:870）、`v13-dp8-…md`（§1.1 :26-31）
- 代码/工件：`v13/load.py`（SQL_LOAD_ORDER/STAGE_THROUGH）；`v13/{filter,memory,economy,summary,periphery}/setup_db.py`（GRANTS 块）；`v13/recall/README.md`（不变量 7）；`v13/recall/v13_recall.sql`（0 stannum）/`v13/characterize/v13_characterize.sql`（full_score/highlight/verify_index 各一）；`v13/summary/README.md`（裁决授权节）；`v13/chunks/README.md`（台账⑨）；`v13/periphery/{README.md #8,test_periphery.py:379-388}`；`v13/periphery/v13_periphery.sql:2341-2342`（F-1 实证）
- oracle 三角：R1 grok-4.6 @xhigh（chat `v13-erratum-处置裁决-D94839`）/ R2 grokBuild grok-4.7-build-fast-xhigh（chat `v13-erratum-处置裁决-oracle--EE7E8F`）——context_builder 分组管道同份中性 brief 两路独立；R3=本会话源码核证线
