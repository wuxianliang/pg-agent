# Investigation: 为什么 M3 起停下来，以及如何彻底推进剩余任务

## Summary

M3 不是实现失败后停下。适配稿里的「M3 = OQ13 建议裁 B」在写成时已经过时：权威计划前一天已裁 OQ13=D，且 V1/V2 已交付。随后的循环把单通道「本循环不改代码」写成结案 `b097a7c`，于是 M4–M6 被一起关掉。当前问题是三条互不解锁的欠账：CJK 路由今天不能改（§8 三条未测真，重跑不构成触发①已绿）；jieba 可以另立计划正式 supersede OQ15 后整包开工，不必等那三条；M5/M6 仍是事件门，今天只能留台账。

## Symptoms

- 用户要求利用 oracle 裁决后继续开发 M3–M6。
- 循环在 M3 名义上停止：只新增 `docs/plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md`（commit `b097a7c`），零 SQL、零 gate。
- Oracle 单通道裁决 Q1=A Q2=A Q3=A Q4=A：结案记录，不重开 CJK 路由，不切 jieba，不做 BM25F，不做 RRF。
- 用户现在问：当前问题是什么，为什么从 M3 开始就停，怎样才能彻底推进剩余任务。

## Background / Prior Research

### 过程事实（父会话记录，2026-09-25）

- M0–M2 已交付并推送：`a3dc266`（0.4.0 基线）、`f74b455`+`f807b4a`（runbook）、`dc9750f`（jieba 探针）。探针裁决：不切生产索引，除非整包（锚改词级 + L3 重写不放宽 + highlight 绑定新断言 + G6 同提交）；`decisions.question` 不切；3-gram OR 在 jieba 上 7/7 miss。
- 随后的 Loop Orchestrate 把 M3–M6 交给 oracle。完成的 lane（grok-4.7）裁全 A。另两 lane（cursor grok-4.6、codex gpt-5.6-sol）provider_error，没有第二意见。
- 父控制器把该裁决当成终态 success，只跑一轮 Orchestrate 写结案并 push。没有测量 v2 计划 §8 三条重开触发，没有另立 supersede 计划。

### Git 时间线（explore `F6132E72`，2026-09-25；父级尚未逐条 spot-check 行号）

| 文件 | Commit | 日期 | 要点 |
|---|---|---|---|
| v2 计划首次入库 | `21df311` | 2026-09-24 | 创建时已含 OQ13=D（该版 `OQ13=D` 出现 13 次） |
| v2 计划 V2 交付注记 | `2240e93` | 2026-09-24 | 重申 OQ13=D 维持不做 |
| v2 计划 §8 后记 | `f0afbed` | 2026-09-24 | contradicts 边可达性缺口：锚池不对称，T2↔T6 边未落图 |
| stannum 适配调查 | `a3dc266` | 2026-09-25 22:40 | **晚于** OQ13=D，仍写「M3 = OQ13 建议裁 B」 |
| jieba 探针 | `dc9750f` | 2026-09-25 23:22 | §9 不切生产索引，整包才可再议 |
| M3–M6 结案 | `b097a7c` | 2026-09-25 23:38 | Q1–Q4=A，零代码 |

- HEAD = origin/main = `b097a7c`。其后零提交。结案之后没有人改 route 或 anchor。
- 没有任何文件把 §8 三条重开触发标成已满足。`supersedes DP9-OQ3` 只出现在结案里，且是禁止句。`routing_intent_causal` 在 `v13/mgraph/test_mgraph.py` G9 被闭集拒绝（explore 报 :2825-2828，待 pair 复核）。
- 装配计划 `docs/plans/v13-mgraph-assembly-wiring-plan-2026-09-24.md:725` 仍把 CJK 路由记为 v2 §8 三条夹具，且第三条不得依赖该接线。
- 区分：文档「未标满足」≠ 已测量并失败。`f0afbed` 的 contradicts 未落图是触发①的负面证据，不是完整的三条测量。

## Investigator Findings

### F1 — §8 触发①原文；「可遍历」在该计划内无定义

- **Claim:** v2 计划 §8 把 CJK 路由重开写成三条夹具全满足；「可遍历」在该文件只出现一次，没有定义、没有术语表、没有判定式。
- **file:line:** `docs/plans/v13-dp9-mgraph-v2-plan-2026-09-24.md:354`（同文件检索 `可遍历` = 1 处）。同文件 `遍历` 另见 :60、:61、:293，都是别的断言，不是触发①的定义。
- **Quote:** `①图上存在 causes/entity/contradicts 的**实际可遍历边**(V1/V2 交付后可测);②同一中文意图查询在 superset 与 deterministic 两种 routing 下产生**不同配额/扩展节点**;③该差异可在**不依赖 B2 装配接线**的 walk gate 中观测。`
- **同段约束:** 重开必须自写 `supersedes DP9-OQ3`；`v13_query_segments` 只返回段文本；禁改冻结 recall 函数（:354 后半；机制复述 :55；`Gate:本计划零新增路由 gate` 在 :56）。
- **Conclusion:** confirmed（用语未定义）。因此不能把重跑数字直接判成「①已满足」或「①已失败」而不先声明谓词。下面 F2 只排除有正文支撑的读法。

### F2 — 重跑边清单不构成触发①的已完成测量

- **Claim:** 2026-09-24 重跑的 32 条 jev 边被表内三分完；`causes` 与 `entity` 不在落地图；已落的 `contradicts` 没有被 walk 消费。该报告自己维持 §8 台账，没有把①标成已满足。
- **file:line / quote:**
  - `docs/investigations/v13-dp9-mgraph-v2-demo-rerun-2026-09-24.md:33` — `jev 边 | **32**(semantic 27 / caused_by 3 / **contradicts 2**)`。27+3+2=32，三分穷尽。
  - :37 — `causes avg 0.05(0 过)`；`contradicts 19 问 … (2 过阈)`。
  - :41 — `T2↔T6 的 contradicts 问从未发出、边未落图`。
  - :56 — `全部 depth=1、edges_used=0、round 1 即收束`；`遍历扩展从未发生`；`维持 v2 计划 §8 触发台账`。
  - :86 — `T2↔T6 contradicts 边 | 无 | **无**`。
  - :122 — `读环仍 4/4 superset、depth=1、edges_used=0`。
  - 同文件检索 `entity` = 0 处。`entity` 是合法 rel（`v13/mgraph/v13_mgraph.sql:85-86`），不是「类型不存在」。
- **读法裁决:**
  - 合取（三种 rel 都有可走边）：eliminated。`causes`=0，`entity`=0。
  - 「walk 已消费」（`edges_used>0`）：eliminated。四条 walk 全是 0。`test_mgraph.py` 检索 `edges_used` = 0 处，没有任何 gate 把消费记成已发生。
  - 用 `caused_by` 3 条顶替 `causes`：eliminated。触发①写的是 `causes`，不是 `caused_by`。桶映射把两者都放进 causal（`v13_mgraph.sql:1422`），那是代码事实，不是触发文本。
  - 析取 +「行存在且 `neighbors()` 能跟」：open，且未被计划授权。只有 `contradicts` 2 行沾边。计划没有定义「可遍历」。重跑 :56 在承认真边存在的同时仍维持台账。H4（`test_mgraph.py:2952-2961`）只证明夹具上 `neighbors()` 能沿 `contradicts` 走一跳，不是 §8 的图上测量。
- **Conclusion:** eliminated — 「重跑已经满足触发①」。open — 未来计划若把「可遍历」定义成「任一命名 rel 有行且读侧映射能跟」，必须自己写这个定义；不能把 2026-09-24 重跑当成已绿。②③同文件未测（:56 仍是 4/4 superset）。三条要全满足（计划 :354），所以即使弱读法成立也不重开。

### F3 — 没有任何 gate 断言触发①

- **Claim:** 现有 gate 锁的是 OQ13=D 的现状，或夹具级 `contradicts` 一跳，不是 §8 三条。
- **file:line / quote:**
  - E2：`v13/mgraph/test_mgraph.py:1606-1614` — `为什么部署失败` → `r_cjk["mode"] == "superset"`，六桶 `>= floor`，分配每桶 `>= 1`。
  - G9 闭集：`:2792-2797` — `"routing_intent_causal" not in pol_g9`；`:2825-2828` — 注入 `routing_intent_causal=0.8` → `V3009`，`routing_intent key refused by the closed keyset (OQ13=D)`。
  - H4：`:2952-2961` — `contradicts` 已在 semantic 桶；`v13_mgraph_neighbors` 从 canonical src 抵对端。这是计划 :293 的夹具，不是触发①。
  - 装配计划把第三条继续外置：`docs/plans/v13-mgraph-assembly-wiring-plan-2026-09-24.md:725` — `仍是 v2 §8 三条夹具,且第三条必须不依赖本接线`。
- **Conclusion:** confirmed。触发①没有断言者。

### F4 — 未来计划必须点名的当前行号

- **Claim:** 下列符号仍在这些行，与结案「不改 route / E2 / anchor_terms / 冻结 recall」一致。
- **file:line / quote:**
  - CJK 短路：`v13/mgraph/v13_mgraph.sql:1506-1507` — `ELSIF v_cjk THEN v_mode := 'superset'`。扫描在 :1491-1503（五区间），早于 deterministic 意图链 :1511-1516。函数起 :1475。
  - 桶→rel：`:1417-1428` — `causal`=`causes,caused_by`；`entity`=`entity`；`semantic` 含 `contradicts`。
  - CJK 3-gram：`v13_mgraph_anchor_terms` 起 :3204；CJK 分支 :3230-3237 — `substring(v_seg FROM v_i FOR v_n)`。项来自 `v13_query_segments`（:3216）。
  - 段返回形状：`v13/recall/v13_recall.sql:13` `RETURNS jsonb`；:70-72 只 `jsonb_agg` 段文本。码点类（:34-44）不进返回值。
  - `decisions.question` ASCII：`v13/schema/v13_core.sql:398-399` — 行内 `CHECK (question ~ '^[\x20-\x7E]+$' …)`。命名约束 `v13_decisions_criteria_ascii`（:422-423）是另一列，不要混。
  - G6 命中：`test_mgraph.py:2741` tinql=`为什么用户无法登录`；`:2756-2757` `count(*) == 1`。
- **Conclusion:** confirmed（行号以本次读取为准）。

### F5 — 结案没有把 M4–M6 技术工作写成完成，也没有执行 OQ15 supersede

- **Claim:** `b097a7c` 结案把「本循环不改代码」写成结案，没有写 M4–M6 已完成。
- **file:line / quote:** `docs/plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md`
  - :3 — `本循环零代码结案`；`本结案只绑定本循环`。
  - :18 — `§8 三条触发没有「已满足」记录`；`即便将来出现那种证据，本裁决也不自动升为 Q1=B 或 Q2=B`。
  - :22 — `不要改 v13_mgraph_route`；`E2 保持原样`；`§8 三条触发没有被记成已满足`。
  - :24 — `本文件不是重开文书`；重开计划必须自写 `supersedes DP9-OQ3`；`不要编辑冻结的 v13_query_segments`。
  - :28 — `M4 仍阻塞：整包先决 + 须正式 supersede OQ15。本文件不执行该 supersede。`
  - :32 — `将来的整包不是本循环`。
  - :36 — `触发未到。没有第二自由文本列。`
  - :40 — `T1 未开工。`
- **Conclusion:** confirmed。易误读的只有 :3 的「结案」和 :28 前半「已经满足」（那句满足的是旧阻塞「未裁」，下一句立刻再阻塞）。

### 新计划必须包含的十行

1. 新文件，不改 v2 计划、结案、recall SQL；正文自写 `supersedes DP9-OQ3`（计划 :354，结案 :24）。
2. 先定义「可遍历」，再测量；禁止把 2026-09-24 重跑标成①已绿（重跑 :56 维持台账）。
3. ①按 rel 分开记：`causes`、`entity`、`contradicts`；`caused_by` 不得顶替 `causes`；`edges_used=0` 不得写成已行使。
4. ①的 gate 必须是图上测量，不是 H4 夹具（`test_mgraph.py:2952-2961`）；谓词写进断言名。
5. ②：同一中文意图查询，superset 与 deterministic 的配额/扩展节点不同；现 E2（:1606-1614）锁的是反面，改路由必须同提交改 E2。
6. ③：该差异在不依赖 B2 装配的 walk gate 里可观测（装配计划 :725）。
7. P1-8：新增只读 script helper，码点表与 route :1493-1498 / segments :37-41 同一五区间；不改 `v13_query_segments`（`v13_recall.sql:13,70-72`）。
8. 若加路由词表：同提交改 `v13_mgraph_route` 短路（:1506-1507）和 G9 闭集（:2792-2797、:2825-2828）。
9. jieba/OQ15 是另一张 supersede，不由①解锁：词级锚（:3230-3237）+ L3 重写且不用 OR 放宽 + 新 highlight 绑定断言 + 同提交重写 G6（:2756-2757）；`decisions.question` 的 ASCII CHECK（`v13_core.sql:398-399`）不切。结案 :28 不执行该 supersede。
10. M5/M6 不进这张路由计划（结案 :36、:40）。三条都有 file:line「已满足」记录之前，不改 route。结案 :18：证据出现也不自动把本裁决升成 B。

## Investigation Log

### Phase 1 - 症状与假设

**Hypothesis:**

- H1：M3 这个名字在 stannum 适配调查稿里是过时排期。权威计划早已裁 OQ13=D，且 V1/V2 已交付。所以「从 M3 开始停」首先是里程碑定义碰撞，不是代码红了。
- H2：真正停住后续任务的，是循环把 oracle 的「本循环不授权改冻结裁决」写成了「剩余工作已完成」。用户要的是推进，裁决给的是关闭适配线。
- H3：M4 的技术阻塞是条件式的（整包 + 正式 supersede OQ15），不是绝对不能做。停下来是因为本轮 oracle 拒绝写 supersede，不是因为探针证明 jieba 永远不可用。
- H4：M3 的 CJK 路由重开（§8 三条）可能只是没被测量，不一定未满足。结案没有做这项测量。
- H5：M5/M6 是事件触发。在没有第二文本列、没有词法漏召评估集之前，直接改生产 schema 或上 T1 会违反既有「明确不做」台账。彻底推进的合法形态是新计划，不是在旧循环里偷偷实现。

**Findings:** H1–H3、H5 确认。H4 收紧：触发①不是「可能已满足但没写下来」。重跑不构成已完成测量；合取读法与 walk 已消费读法都不成立。见 Investigator Findings F1–F5。
**Evidence:** 下文 Root Cause 的 file:line。父级抽查：`v13_mgraph.sql:1505-1506` 仍是 `ELSIF v_cjk THEN v_mode := 'superset'`（pair 写的 :1506-1507 偏一行）；计划 `:354`、重跑 `:33`/`:37`/`:56` 与结案 `:28` 与 pair 引用一致。
**Conclusion:** Confirmed。

### Phase 2–4 - 时间线、触发①、推进顺序

**Hypothesis:** 停点要么是 gate 红了，要么是冻结裁决把后续工作一起判死。
**Findings:** gate 没有红。HEAD = `b097a7c`，该提交只加结案，零 SQL。停点是定义碰撞加循环结案。三路 oracle（grok-4.7、grok-4.6、gpt-5.6-sol）一致：jieba 整包不必等 §8 测量；路由实现今天不在序列里；M5/M6 留台账。分歧只在「第一份文书写 jieba 还是写测量」——两者都合法，可并行起草，路由实现不得开写。
**Evidence:** Investigator Findings；结案 `:18` `:28`；计划 `:354`。
**Conclusion:** Confirmed。

## Root Cause

从 M3 起停下来，是两层叠在一起，都不是代码失败。

**第一层：名叫 M3 的工作，在排期写下来之前就已经被裁成反方向。** `docs/investigations/v13-stannum-0.4-pgembed-adaptation-2026-09-25.md` §5 把 M3 写成「OQ13/OQ14 裁决与 mgraph v2」，并写「OQ13 建议裁 B」。那句「建议裁 B」来自 `docs/investigations/v13-mgraph-v2-cjk-routing-investigation-2026-09-24.md` §5 的草案。权威计划 `docs/plans/v13-dp9-mgraph-v2-plan-2026-09-24.md` 在首次入库 `21df311`（2026-09-24）时已经裁 OQ13=D：不改 `v13_mgraph_route`，不加 `routing_intent_*`，E2 原样。V1（OQ15 字符 3-gram）同提交交付，V2 在 `2240e93` 交付。适配稿 `a3dc266` 是次日 22:40 才入库的。所以「从 M3 开始做」在开工前就没有未完成的实现项。活代码仍是这条冻结：`v13/mgraph/v13_mgraph.sql:1505-1506` 在意图链之前执行 `ELSIF v_cjk THEN v_mode := 'superset'`。E2 锁的是反面：`v13/mgraph/test_mgraph.py:1606-1614`，`为什么部署失败` 必须是 superset。

**第二层：循环把「本循环不授权」写成了适配线关闭。** 用户要求裁决后继续开发 M3–M6。完成的那一条 oracle lane 裁 Q1–Q4 全为 A；另两 lane provider_error。父控制器按合同只写了 `docs/plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md`（`b097a7c`）并推送。结案自己写的是「本循环零代码结案」「本结案只绑定本循环」（`:3`），以及「M4 仍阻塞：整包先决 + 须正式 supersede OQ15。本文件不执行该 supersede。」（`:28`）。它没有写 M4–M6 技术上已完成。易误读的是「结案」这两个字，和 `:28` 前半「旧阻塞已经满足」——满足的是「OQ13 未裁」，下一句立刻再用 OQ15 整包把 M4 堵住。`:18` 还写明：将来即使出现 §8 证据，也不自动把该裁决升成 Q1=B。

**当前剩下的不是一个 M3，是三条互不解锁的欠账。**

1. **CJK 路由。** 重开条件在计划 `:354`：三条夹具全满足，且新计划自写 `supersedes DP9-OQ3`，并先加只读 script helper，不改冻结的 `v13_query_segments`。「可遍历」在该计划只出现一次，没有定义（F1）。2026-09-24 重跑不能当成①已绿：jev 边 32 = semantic 27 + caused_by 3 + contradicts 2（重跑 `:33`）；`causes` 过阈 0（`:37`）；该报告没有 `entity`；四条 walk 全是 depth=1、`edges_used=0`，并写明维持 §8 台账（`:56`）。用 `caused_by` 顶替 `causes` 不成立。没有任何 gate 断言触发①（F3）。所以路由实现今天不能开工。
2. **jieba。** 探针 §9 禁止只改 reloption。G6 的 3-gram OR 在 jieba 上 7/7 miss。锚仍是字符滑窗：`v13_mgraph.sql:3230-3237`。结案已宣布「等 OQ13/OQ14」这条旧阻塞解除。§8 三条只门控路由 supersede，不门控 OQ15 supersede。jieba 可以另立计划整包开工，不必等测量。
3. **M5/M6。** 没有第二自由文本列，就没有 BM25F（结案 `:36`）。T1 未开工（`:40`）。今天做实现就是发明触发。

## Recommendations

1. **第一份可写代码的新计划：jieba 整包，明文 supersede OQ15，一次提交。** 不写 `supersedes DP9-OQ3`。同提交交付：`v13_mgraph_anchor_terms` 的 CJK 分支改为词级（`:3230-3237`）、L3 改成「单字片假名命中含该字的文档」并标明过召回、禁止 OR 宽化、新断言「jieba 命中行上 `v13_extract_spans` 字节区间 = 绑定 highlight 区间」、G6（`test_mgraph.py:2756-2757` 的 `count(*)=1`）改成词级 OR 命中。生产索引与锚一起切。`decisions.question` 不切（`v13/schema/v13_core.sql:398-399`）。不改 `v13_mgraph_route`、E2、G9 对 `routing_intent_*` 的拒绝。
2. **并行的只读文书：定义并测量 §8 三条。** 先定义「可遍历」，再按 `causes` / `entity` / `contradicts` 分开记。禁止把重跑标成①已绿。②③在重跑 `:56` 仍是 4/4 superset，这份文书测不到「已满足」就停。不改 route。
3. **路由实现计划今天不写。** 要等测量文书对三条各自留下「已满足」的 file:line，再另立计划，正文自写 `supersedes DP9-OQ3`，先做 P1-8 helper，再同提交改 `:1505-1506` 的短路、E2（`:1606-1614`）和 G9 闭集（`:2825-2828`）。结案 `:18` 不会自动授权这一步。若这条路由计划真的落地，jieba 提交排在它后面，避免两线同改 `test_mgraph.py`。测量本身不是 jieba 的前置。
4. **M5/M6 维持结案台账。** 不发明第二文本列，不设 `field_weights`，不配 vchord，不把无过滤 `search()` 抄进主链。

## Preventive Measures

- 适配排期引用另一条线的 OQ 时，以该线终稿的裁决字母为准，不引用调查草案的「建议裁」。`a3dc266` 的 §5 在 `21df311` 之后仍写「建议裁 B」，是这次停点的文档根。
- 循环结案必须把「本循环停止」和「技术工作完成」写成两句。`b097a7c` 的「结案」被读成 M3–M6 做完了，但 `:28` 写的是 M4 仍阻塞。
- 冻结裁决只由新计划里的字面 supersede 短语改。再解释、结案、重跑数字都不能代替。
- 单通道 oracle（另两 lane provider_error）可以关闭一个循环，不能被写成永久技术终裁。下一份计划要自己复裁，不能把 `b097a7c` 的 Q=A 当成自动升格。
