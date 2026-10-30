# v13 DP9 mgraph v2 修活真实栈重跑验证报告(2026-09-24)

**一句话**:用当前 v2 代码(`21df311` 锚编译器 + `2240e93` 矛盾通路;HEAD 即 `2240e93`)在真实栈上重跑了 v1 同型试验——**偏差台账 #37–#42 的修活从 gate 夹具升级为真实栈证据**:关系判断面从结构性休眠变为活跃(42 对关系封/145 问/32 条 jev 边/23 条 proximity 边,全 v1 为零)、contradicts 通路端到端走通(canonical 单向 19 问、2 过阈落边 origin=jev+decision_id)、B2 对源含矛盾对且固化面完整识别矛盾(T2↔T6:contradiction **1.000**/keep_separate/门正确关闭);**但重跑首发现一个 v2 实现 bug**:build 体内关系信封仍用 3 参形态读已清除的 `typesafe.provider` GUC,种子帽 `write_max_batches=8` 的多信封 tick 在真实 provider 上第二信封必炸 V3002(gate 单批纪律未覆盖),本试验以 `wmb=1` 步进(与 H7 gate 同型)绕过至自然完成;目标矛盾对 T2↔T6 的 **contradicts 边仍未落图**——锚池方向不对称(T6 不在 T2 锚的 top-5,canonical 向从未入问),矛盾语义改经固化面被捕获。

---

## 1. 运行形态

| 项 | 值 |
|---|---|
| 库 | `agent_v13_demo_mem2`(新建;当前 SQL 全 15 文件加载到 mgraph,即 v2 形态;v1 试验库 `agent_v13_demo_mem` 与原库 `agent_v13_demo` 全程未动——对前者仅做只读核查) |
| 栈 | Chainlit 2.12.0 headless(:8000,real 模式,持有 pgembed PG 18.4 + J-A shim :8765,`DEMO_SHIM_KEY` 经 env 共享,值只存 `memtrial2/.shimkey`(0600,gitignored,不打印))+ PostgREST 16.3(:3000,`PGRST_DB_URI`→新库) |
| 判断/生成 | 真实 DeepSeek(`deepseek-chat`);判断经 shim 一批 `/chat/completions`,生成进程内直调 |
| 对话驱动 | 同 v1:app 自己的 driver 链(`driver.Driver` + `port_rest.PortREST`);SYSTEM_PROMPT 已含「≤4 句、禁列表」 |
| v2 新增适配 | ①**RawAsyncTransport**(`mem2_rawtransport.py`):本机某网络层把 python 高层 HTTP 客户端(httpx/urllib)的**回环**流 MITM 成空体 502(curl/裸 socket/出站 HTTPS 不受影响),给 PortREST 注入手搓 HTTP/1.1 传输绕过,PortREST/driver 零改动(§8 异常 1);②build 步进形态 `wmb=1/wma=1`(§8 异常 2 的绕过) |
| 复现工件 | `v13/demo/setup_db_mem2.py`、`mem2_converse.py`、`mem2_mgraph.py`、`mem2_observe.py`、`mem2_rawtransport.py`;日志 `v13/demo/memtrial2/*.log|*.json` |
| 前置阻塞 | pgembed bundle 被并行会话重构建(`make build` 元数据短暂出现又被清理,重试环上第二轮成功 11:38),建库等待 ~50 分钟 |

## 2. 对话(同型复现)

会话 `1195fbca-906e-4b56-9823-e969107b5ab0`,8 轮中文**逐字同 v1**(埋点:实体 Alice/Bob/Zephyr;因果;时间链;T2 三万→T6 八千更正)。判断面 **11 批/99 问,与 v1 完全同数**;回合 3/8 `completed`(T1/T6/T7)、5/8 `budget_exhausted`(v1 为 4/8——本轮 T5 未过 0.75 置信阈,属 D16 已知状态机行为);`context_refresh` 结算 11 次;生成 3 次。投影 **11 chunks**(8 user + 3 llm;v1 为 12——少的是 v1 里复述「三万」的 llm5 回复,本轮 T5 failed 无回复),`freshness={lag:0, degraded:false, watermark:64}`,花钱前零成本预检通过。

## 3. 写路径:build 多 tick 实测

策略翻版 v3(write on)。**帽形态偏离**:原方案用种子 `write_max_batches=8`(预计 ~8 tick)——首 tick 在第一个关系信封上即炸 V3002(§8 异常 2,v2 SQL bug),改为 `wmb=1/wma=1` 步进(每连接恰一问,与 H7 gate 同型)。**49 个 tick 全部 `stop_reason=batches` 收步、末 tick `status=ok/pending_nodes=0` 自然完成**(106.2s,~2.2s/tick);watermark 阶梯 0→4→8→18→28→38→48→52→56→60→64、pending 10→0 逐节点推进,rel_cursor 终值=末节点(T8)——**H7 的跨 tick 续跑语义在真实栈成立**(多 tick 提交使 generation 增至 37,见 §8 异常 6)。另:首次 wmb=8 尝试的事务整体回滚零残留(11 节点/0 边→重建),其已发出的 1 个类型信封 ask 被回滚作废(成本记入 §7)。

| 观测 | v2 实测 | v1 对照 |
|---|---|---|
| 类型信封 | 11 批/44 问,全部 answered | 12 批/48 问 |
| 类型赢家 | episodic 5 / semantic 4 / preference 1 / procedural 1 | 6/4/1/1 |
| 关系信封(mem_rel) | **42 个有向对/145 问**(canonical 76 问 + 反向 69 问;27 个无序对,15 对双向、12 对单向) | **0 发出** |
| proximity 边 | **23**(structural 0.183–0.673,均值 0.32) | **0** |
| jev 边 | **32**(semantic 27 / caused_by 3 / **contradicts 2**) | **0** |
| temporal 边 | 10 | 11 |
| build 判断总量 | 49 批/176 问(另 4 批为步进探针预热,决策被复用) | 12 批/12.3s 单调用(自定义帽 44/48) |

**DeepSeek 关系打分有区分度**:semantic 42 问 avg 0.626/max 0.95(**27 过 0.60 阈**);caused_by avg 0.112/max 0.90(3 过);causes avg 0.05(0 过);**contradicts 19 问 avg 0.141/max 0.90(2 过阈)**。锚编译器实测:T2 的 tinql=`"上周五" OR "周五凌" OR … OR "Zephyr" OR …`(latin 整项 + CJK 3-gram OR,k=5)。

### 3.1 T2↔T6 矛盾对解剖(本试验核心问题)

- **mem_rel 面**:T6 在 T2 锚的 top-5 之外(T2 池=T2 自身/T1/llm1/T5/llm6),T2 在 T6 锚池内(lex 0.219)⇒ 仅 T6 锚向(src=t6>dst=t2,**非 canonical**)被问 3 问:semantic **0.9**、causes 0.05、caused_by 0.05——semantic 过阈,**T6→T2 的 semantic jev 边落图**;#40 正确抑制了该方向的 contradicts 入封。canonical 向(src=t2)因从未进锚池**零信号**⇒ **T2↔T6 的 contradicts 问从未发出、边未落图**(v1 是「关系面整体休眠」,v2 变为「锚池方向不对称」——新发现,非回归)。
- **结构面**:proximity 边 T6→T2(structural 0.218)落图;该对**进入 B2 固化对源**(v1 结构性不可能)。
- **固化面**(§5):五问全问,contradiction **1.000**、redundant 0.00、obsolete 1.00、link 1.00、representation **keep_separate**——矛盾语义被如实识别且正确拒绝合并。

### 3.2 落图的两条 contradicts 边(DeepSeek 打分 0.9/0.9,均 canonical、origin=jev、带 decision_id)

| 边 | 语义评价 |
|---|---|
| T8(周一复盘会,「请记住最终…八千」)→ T2(三万) | **真矛盾**,判断正确 |
| T8 → T6(实际八千) | **误报**——两者同持八千,模型对「复述 vs 陈述」过触发 |

即 contradicts 的判断质量为 1 真 1 误(2/2 过阈落图,阈值不筛选语义正确性)。

## 4. 读路径(4 查询对照)

策略翻 v6(read on)。路由 4/4 `superset`(CJK 规则,OQ13=D 维持);各查询一个 walk,首轮锚=lexical top-k(截到 beam=5),**全部 depth=1、edges_used=0、round 1 即收束**——真边(32 jev+23 proximity)存在但 superset 模式下 DeepSeek 的 evidence_sufficient 判定首轮即真,遍历扩展从未发生(与 v1 同形;差异化遍历的行使仍待 CJK 路由,维持 v2 计划 §8 触发台账)。

| 查询 | v2 evidence(分数序) | v1 对照 | 命中 |
|---|---|---|---|
| Q1 `why Zephyr 无法登录` | **0.772=T2 因果节点**;0.382 llm7;0.179 T1;0.153 llm1;0.149 llm6(5 项) | 0.900=T2(唯一) | ✅ 同目标;frontier 更满(锚 OR 池宽化) |
| Q2 `when 恢复 登录` | **0.900=T3 时间线**;0.825 llm6;0.692 llm7 | 0.852=T3;0.824=llm5(幻觉复述) | ✅;本轮无 llm5(T5 failed),幻觉传播样本缺位 |
| Q3 `Alice 决定 回滚` | **0.852=T3**;0.674 llm7;0.413 T7;…(5 项) | 0.775=T3 | ✅ |
| Q4 `数据库备份策略`(负例) | 空集,frontier 0,`depth` 收束,1 批 | 同 | ✅ 正确空手而归 |

判断面:读环 17 批(Q1 6/Q2 4/Q3 6/Q4 1);Q1 顶分 0.772<`evidence_sufficient_min` 0.85 仍以 `evidence` 停——停止由 DeepSeek 停止问 Noul 决定,非分数阈(v1 0.900 停在同因;行为注记,非故障)。

## 5. 固化(一次)

B2 对源(proximity-derived)= **15 对**(含 T2↔T6;v1 相邻对 11、不含矛盾对)。步进 9 次(一步一封,9 对五问)后首个 eligible 出现 → enqueue(`mgraph_consolidate` effect)→ worker 以 DeepSeek 生成 → settle(fidelity 1 ask)。

- **选中对:(T1 用户消息, llm1 模型复述)**——与 v1 同一个「真正冗余」对(冗余家族判定一致);priority 序 [contradiction, redundant, link] 中其 subtype=redundant 压过其余 merge 类对(如 T3‖llm7 subtype=link)。
- 五问:redundant **0.85**(恰过阈)、link 0.9、contradiction 0.05、obsolete 0.05、representation=**merge**(≥0.85)——与 v1 逐值同分。
- 产物(body 由 DeepSeek 生成):「Zephyr是面向中小企业运维团队的监控平台,Alice任后端工程师,Bob任产品经理。」;fidelity **0.95** → **adopted**;固化边 1 条 `redundant_with`(origin=consolidation)。
- **T2↔T6 在固化面被问**(§3.1):contradiction 1.000/keep_separate——生成门(contradiction<0.85 才许 merge)正确关闭,**矛盾对以两个独立节点保留**,这正是更正语义在当前图上的正确沉淀形态。
- 另 8 个被问对中:T2‖T4 与 T3‖llm7 为 keep_separate 低冗余(门关);llm6‖T8 merge+obsolete 0.85(eligible,subtype=link,输给 priority)。

## 6. v1 ↔ v2 对照总表

| 观测 | v1(6bfe366 代码) | v2 重跑(21df311+2240e93) |
|---|---|---|
| episodic 节点 | 12 | 11(对话回合成功率差) |
| 关系信封发出 | **0**(全 body AND ⇒ 池恒空) | **42 对/145 问** |
| jev 边 | **0** | **32**(semantic 27/caused_by 3/contradicts 2) |
| proximity 边 | **0** | **23**(0.183–0.673) |
| T2↔T6 被问 | 从未(任何面) | mem_rel:仅非 canonical 向 3 问;**mem_cons:5 问全**(contradiction 1.000) |
| T2↔T6 contradicts 边 | 无 | **无**(锚池方向不对称;非 v1 的结构性休眠) |
| contradicts 边(全图) | 0 | 2(1 真 1 误报,均 0.9) |
| build 形态 | 1 调用/12 ask/12.3s(帽 44/48) | **49 tick 自然完成**/49 ask/106.2s(wmb=1 步进;种子帽 8 在真实栈炸 V3002) |
| 读环三正例顶分 | 0.900/0.852/0.775 | 0.772/0.900/0.852(命中同目标) |
| 读环 frontier 构成 | 1–2 项(词法+temporal 一跳) | 3–5 项(词法锚池宽化;边仍未被遍历) |
| 固化对源 | 相邻对 11(矛盾对不可能入源) | **proximity-derived 15(矛盾对在源)** |
| 固化选中 | (T1,llm1) redundant 0.85/merge/fidelity 0.95 | 同对、逐值同分 |
| 判断总量(全程) | 47 批/311 问 + 11 生成 ≈58 HTTP(两轮对话) | **91 批/~405 问 + 4 生成 ≈96 HTTP**(单轮对话;含 4 批步进探针与 1 批回滚作废) |

**修活裁定**:偏差 #37/#38(锚编译器)——**实证成立**;#40(canonical contradicts 单向入封)——**机制实证成立**(19 问恰 canonical 向、同 signal 恰一行、过阈落边带 decision_id),但目标对的可达性受锚池方向性制约(新边界);#41(B2 对源)——**实证成立**(矛盾对入源且固化面正确处理);#42/H7(跨 tick 续跑)——**语义实证成立**(cursor/watermark 阶梯推进至自然完成),**但种子帽的真实多信封 tick 形态被 V3002 bug 否决**(需一行 SQL 修复+gate 补真实多信封覆盖,见 §8 异常 2)。

## 7. 成本

| 项 | 值 |
|---|---|
| 判断 HTTP 批 | **92**(对话 11 + 回滚作废 1 + 步进探针 4 + build 49 + 读环 17 + 固化 9 + settle 1);落库 91 行/~405 问 |
| 生成 | 4(对话 3 + 固化合并 1) |
| **DeepSeek 总调用** | **≈96 次 HTTP**(deepseek-chat 计价 <¥1 量级) |
| 墙钟 | 对话 ~29s;build 106.2s(49 tick);读环 ~37s;固化+settle ~24s;observe 只读 |
| 红线核对 | 对话单轮 8 轮;build 循环至自然完成(1 次回滚重启);4 查询各一 walk;固化恰一次;总量与预计 ~100 一致 |

## 8. 异常与偏差

1. **python 回环 HTTP 被 MITM 成 502(环境级)**:httpx/urllib 的回环 HTTP 流被本机某网络层拦截代答(空体 502、无 Server 头、echo 服务器证实请求未达);curl、裸 socket、出站 HTTPS 不受影响;`dangerouslyDisableSandbox` 亦复现,非工具沙箱。绕过=RawAsyncTransport(手搓 HTTP/1.1)。v1(00:40,Claude Code shell)无此现象——今日环境变化,来源未定位。
2. **v2 SQL bug(重跑首发现,建议 P0 修复)**:`v13_mgraph_build` 体内**类型信封已用 5 参显式传参(v13_mgraph.sql:1029)但关系信封仍是 3 参(:1069)**——3 参委托体读 `typesafe.provider` GUC,而该占位符在同连接首次判断 IO 加载 typesafe 库时被清除(README ⑧)⇒ `write_max_batches≥2` 的 tick 在第二个信封上必炸 V3002。gate 未覆盖原因:D/H 组单批纪律(wmb/wma=1)使每连接恰一问,且 GUC mock 路径不加载库;v1 真实栈零候选从未进入该分支。修复=1069 行改 5 参(一行);修复前真实栈只能 wmb=1 步进。
3. **观测查询模式 bug(沿自 v1)**:signals 是 `mem_rel::<h>::<h>::<rel>`(冒号),v1 `memdrive_mgraph.py` 与本试验初版用 `mem\_rel\_%`(下划线转义)LIKE——全部空结果。v1 报告 §3 的聚合数字实际来自 phase2 的无转义查询,当时未察觉模式差异;本试验以 `mem2_observe.py` 修正重取(§3 全部数字为修正后值)。
4. **v1 收尾翻版疑点(只读核查)**:v1 两脚本收尾均为 `bump_policy({})`——只复制 active 值,不可能把 read 翻回 false;现查 `agent_v13_demo_mem` 策略史 v1–v4:v4 active 双 false。推定 v1 收尾有脚本外手工翻版(报告「已翻回 v4」与库态一致但与脚本行为不符)。本试验驱动收尾显式 `{"write_enabled":false,"read_enabled":false}`(v7 active 双 false 已核)。
5. **budget_exhausted 5/8**(v1 4/8):回合成功率波动属 D16 已知;连带 llm 回复 3 条(v1 4 条)、节点 11(v1 12),v1 的「llm5 幻觉复述被高分召回」样本本轮缺位。
6. **generation 随 tick 增长**:多 tick 提交使 `v13_mgraph_meta.generation` 从 0 增至 37(每次有净变化的提交 +1;v1 单调用=1)。walk 身份含 generation,读环在 build 后立刻执行故匹配;固化后 generation 再变,旧 walk 的 evidence 出口按设计失效(M3 语义,非故障)。
7. **contradicts 判断质量**:2 过阈边中 1 误报(T8→T6,两者同持八千)——阈值筛置信不筛语义;contradicts avg 0.141 说明多数对被正确低分。
8. **pgembed bundle 并行重构建**阻塞建库 ~50 分钟(外部事件,重试环成功后继续);PG 生命周期随持有进程(setup 进程退出即停),起栈次序调整为 Chainlit 先行。

## 9. 局限

- **T2↔T6 contradicts 边未落图的原因是抽样性的锚池方向不对称**,不是机制缺口:canonical 侧锚(T2)的 top-5 恰不含对端。OQ15 调查的模拟(T2→T6 rank 4)基于 v1 的 12 节点转录与本轮 11 节点池归一化差异不可直接对比;k=5 的方向不对称是 3-gram 词法的固有形态,是否调 k/加对称补问属新计划裁决。
- wmb=1 步进使「每 tick 多信封截断」的真实形态未被行使(被异常 2 否决);tick 数(49)≠ 信封数上限的帽行为未观测。
- 读环仍 4/4 superset、depth=1、edges_used=0:真边对检索的增量价值在本轮未被行使(OQ13=D 的既知边界)。
- 单会话单次 build;rebuild 幂等、多 generation walk 并发未测;dec-refresh 注记(不变量 14)未实测。
- 固化只跑到首个 eligible(9/15 对);T2↔T6 的固化判定已取得,但其余 6 对未问。

## 10. 收尾状态

- `agent_v13_demo_mem2` 保留备查:11 episodic + 1 consolidation 节点、10 temporal + 23 proximity + 32 jev(含 2 contradicts)+ 1 固化边;策略 v7 active 双 false(mgraph 暗库默认形态);固化队列 1 行 adopted。
- v1 库 `agent_v13_demo_mem`(只读核查过策略史)与 `agent_v13_demo` 全程零写入。
- Chainlit/PostgREST 已停;pgembed PG 仍在跑(便于复查;`uv run python server.py stop` 可停)。
- demo 树内新增/改动文件全部 gitignored;仓库跟踪文件零改动;未 commit。本报告为工作区新文件(未跟踪,不提交)。
