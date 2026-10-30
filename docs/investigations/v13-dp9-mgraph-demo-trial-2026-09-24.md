# v13 DP9 mgraph 记忆机制真实栈实测报告(2026-09-24)

**一句话**:在 Chainlit demo 的真实栈(PG 状态机 + PostgREST + 进程内 shim → DeepSeek,真实判断、真实生成)上跑通了一次完整的 mgraph 记忆生命周期——逐字投影 → build(写)→ 3+1 个查询的读环 → 一次固化;evidence 对三类查询全部命中埋设事实、负例查询正确空手而归;同时暴露出两个结构性发现(全 body AND 候选使 mem_rel 面在真实对话上休眠;含 CJK 的查询恒走 superset 路由)。

---

## 1. 运行形态

| 项 | 值 |
|---|---|
| 库 | `agent_v13_demo_mem`(新建;`SQL_LOAD_ORDER` 全 15 文件加载到 mgraph + demo RPC 层 `demo_api.sql` + 补充 `demo_api_mem.sql`);原库 `agent_v13_demo` 未动 |
| 栈 | Chainlit 2.12.0 headless(:8000,real 模式,持有 pgembed PG + J-A shim :8765)+ PostgREST 16.3(:3000,`PGRST_DB_URI`→新库)+ PG 18.4(unix socket) |
| 判断 | 真实 DeepSeek(`deepseek-chat`)——demo_parse → typesafe_ask → shim → 一次 `/chat/completions`/批 |
| 生成 | 真实 DeepSeek,进程内 `deepseek.chat_completion` |
| 对话驱动 | **app 自己的 driver 函数**(`driver.Driver` + `port_rest.PortREST`,与 Chainlit hub 同一后端链);Chainlit UI 层未驱动——Chainlit 2.12.0 无 testing 模块(装好的包里无 `chainlit/testing`),这是唯一降级,且降的只是 UI 壳:REST 面、demo RPC、状态机、shim、DeepSeek 全部真实 |
| 全栈适配 | ①新增 `demo_refresh_context` RPC + driver 的 `context_refresh` 分支(manifest 换掉 `v13_context_fresh` 后每回合都会路由该 kind);②`settings.py` 支持 `DEMO_SHIM_KEY` env 覆盖(跨进程共享 shim);③driver SYSTEM_PROMPT 加「≤4 句、禁列表」(见 §7 异常 1)。全部在 gitignored 的 demo 树内 |
| 复现工件 | `v13/demo/setup_db_mem.py`、`memdrive_converse.py`、`memdrive_mgraph.py`、`memdrive_phase2.py`、日志 `v13/demo/memtrial/*.log|*.json` |

## 2. 对话摘要

试验会话 `bf2cc453-4fd6-4ff5-adff-5caeb2b4c201`,8 轮中文(埋点:实体 Alice/Bob/Zephyr;因果「因为…所以…」;时间链 周五发布→周六故障→周六九点决策→周日十五点恢复→周一复盘;T6 后期更正 三万→八千 制造潜在矛盾;顺带验证 CJK 路径):

1. T1 团队/实体介绍(Zephyr=面向中小企业运维团队的监控平台)
2. T2 因果+数字:发布未先跑预发三十分钟 → 周六早上大量用户无法登录,约三万受影响(内嵌 `why` 词锚)
3. T3 时间线:Alice 周六九点决定先回滚;when 锚;周日下午三点全部恢复
4. T4 程序性新规:预发三十分钟+工作日白天上线
5. T5 偏好:Bob 偏好中文摘要
6. T6 更正:实际八千,不是三万(重试重复计数)
7. T7 评价问(Alice 处置)
8. T8 收尾(复盘会+要点复述)

回合结果:4/8 `completed`、4/8 `failed/budget_exhausted`——真实判断置信度低于 0.75 阈 → human 路由耗尽 3 个 cycle,是 D16 预告过的状态机行为,不是故障;用户消息不依赖回合成败照常入档。判断面每回合 1-2 批(9-18 问),`context_refresh` effect 结算 12 次(全栈适配分支)。第一轮对话(默认 system prompt)6/8 成功但其 llm 回复触发 §7 异常 1,试验采用第二轮。

## 3. 写路径观察

前置:手动 `v13_rebuild_transcript_chunks(200)`×2(pg_cron 在 stage 库不可用——cron.database_name 闸,memory README 运维纪律②;demo 树无外部调度,**mgraph build 前必须手动投影**,这是全栈下的真实运维形态)。投影后 **12 chunks**(8 user + 4 llm),`freshness = {lag:0, degraded:false, watermark:62}`;花钱前零成本预检(每 body ≤4096B、每段 ≤256B、≤64 段)通过。

策略翻版:INSERT v2(write_enabled=true,write_max_batches=44/write_max_asks=48)→ 双 UPDATE 翻 active——翻版仪式一次成功。

**一次 `v13_mgraph_build(sid, 100)`(12.3s,12 个 ask 批,全成功)**:

| 观测 | 值 |
|---|---|
| nodes_inserted | 12(全部 episodic) |
| temporal 边 | 11(source_at 全链重连) |
| proximity 边 | **0** |
| jev 判断边(mem_rel 过阈) | **0** |
| 关系信封(mem_rel ask) | **0 发出**(asks=12 恰等于节点数=类型信封数) |
| stop_reason | null(自然完成,pending_nodes=0) |
| cursor/watermark | watermark=62、rel_cursor=末节点、generation 0→1 |
| mem_type decisions | 48 条(12 节点×4 问)全部 answered |

**类型四问真的在被 DeepSeek 判**(每节点取 noul 最高槽位为赢家):episodic 6、semantic 4、preference 1、procedural 1——与内容语义吻合(T4 新规→procedural、T5 偏好→preference、T1/T5/T7/T8 等陈述句→semantic/episodic 分流)。样例 noul:T2「episodic 0.95」、T4「procedural 0.8」、T5「preference(输给 semantic)但 preference 槽 0.1」——判得有区分度。

**结构性发现 1(本试验最重要)**:零关系封的原因是候选发现用**锚节点全 body 的 AND tinql**(§3.4⑦)。对第一个节点直接跑 `v13_mgraph_candidates` 实证:tinql = `"我在" AND "Zephyr" AND "项目工作" AND …`(9 个短语),返回的**唯一候选是节点自身**(score 5.25),build 侧排除自身后池子恒空 → 真实对话里两条不同消息互不包含对方全部段 → **mem_rel 判断面(semantic/causes/caused_by/entity)在非冗余转录上结构性休眠**。这与偏差台账 #12 的分析一致(该条还推出 mem_rel_entity 闸永不可达),但本试验给出的是真实对话证据:图上唯一先验边只剩 temporal(以及后述 consolidation 边)。矛盾探测(T2 三万 vs T6 八千)因此**从未被问过**——`contradicts` 边为零不是模型判不出,是问题根本没发出。

## 4. 读路径观察

策略翻 v3(read on,write off)。4 个查询各一个 walk(路由 deterministic 模式零 ask;**发现 2:含任意 CJK 段的查询恒 mode=superset**——设计如此(CJK 段→六桶全 floor),但与 lexical AND 组合后,`why/when/大写实体` 的确定性升权对中文转录的混合语言查询**永不可达**,因为纯 ASCII 查询又无法在中文节点上做词法锚定):

| 查询 | 步数 | ask 批 | calls_used | stop_reason | evidence(分数序) | 预期命中? |
|---|---|---|---|---|---|---|
| Q1 `why Zephyr 无法登录` | (前次部分驱动后幂等续跑,0 新步) | 4(累计) | 2 | evidence | **0.900 = T2 因果节点**(唯一命中) | ✅ 正中埋设因果句 |
| Q2 `when 恢复 登录` | 5 | 3 | 3 | evidence | **0.852 = T3 时间线节点**;0.824 = llm5 回复(内含模型自己复述时把「周六九点」写成「周日上午九点」的**幻觉传播**) | ✅ 正中时间线;副发现:幻觉内容同样被高分召回 |
| Q3 `Alice 决定 回滚` | 4 | 2 | 2 | evidence | **0.775 = T3 节点**(唯一命中) | ✅ 实体型命中 |
| Q4 `数据库备份策略`(负例,纯 CJK) | 3 | 1 | 1 | **depth**(搜索穷尽) | **空集**,frontier 0 | ✅ 无关查询正确空手而归 |

读环判断面真实发生:mem_trav 16 条(avg noul 0.794,支持扩展)、mem_stop 16 条(avg 0.333);三个正例都以 `evidence_sufficient` 停止(顶分 0.900/0.852/0.775),负例以 depth 收束——停止机制 behaved。frontier 裁剪到 ≤2 节点(inject_top_k=5 之内)。

值得注意:由于零关系边,读环的「桶→rel 遍历」(causal→causes/caused_by 等)实际上无 thereby 可走——evidence 全部由**词法锚定分数 + temporal 链一跳**支撑。也就是说 B1 读环在真实对话图上退化成「BM25 锚定 + 时间邻居」,判断面只剩 traversal/stopping 两族。

## 5. 固化观察(一次)

`v13_mgraph_consolidate` 步进 4 个 ask 批后 eligible 非空 → `enqueue`(kind=`mgraph_consolidate` effect 入队,worker 走通用 CAS 分支)→ 本试验 worker 以 DeepSeek 生成合并文 → `complete succeeded` → `settle`(fidelity 1 ask)。

- 选中对:(T1 用户消息, llm1 模型复述)——**真正冗余的相邻对**,选对面正确(cons_pairs 只取 source_at 相邻对,T2/T6 矛盾对因不相邻结构性不可能被选)。
- 五问答案:redundant **0.85**(恰过 0.85 阈)、link 0.9、contradiction 0.05、obsolete 0.05、representation=**merge**(置信 0.85 ≥ consolidation_choice_min)——门通过。
- 产物节点(body 由 DeepSeek 生成):「Zephyr是面向中小企业运维团队的监控平台,Alice负责后端,Bob负责产品。」——质量合格,保真 fidelity noul **0.95** → adopted。
- 固化边:1 条 `redundant_with`(origin=consolidation);产物作为 consolidation 节点不作候选锚(F9 语义)。
- 队列表 `memory_consolidations`:1 行 adopted,body_hash=产物哈希(#32 语义)。

## 6. 成本

| 项 | 值 |
|---|---|
| judgment_calls 批数(=shim HTTP=DeepSeek 判断调用) | **47 批 / 311 问**,全部 succeeded |
| └ 对话两轮 | 14 + 11 = 25 批 |
| └ build | 12 批(全类型封) |
| └ 读环 | 10 批(Q1 4 + Q2 3 + Q3 2 + Q4 1) |
| 生成调用 | 11 次(对话 6+4 + 固化合并 1) |
| **DeepSeek 总调用** | **≈58 次 HTTP** |
| 墙钟 | 对话 ~35s + ~22s;build 12.3s;读环 4 查询 ~7s;固化+settle ~6s;全程(含建库/起栈)约 15 分钟 |
| 判断缓存 | 全局 request_hash;同型重复问零费(回合间 state 变化所以每回合重新问,符合 DP2 语义) |

规模感:12 节点转录的一次全生命周期 ≈ 58 次小 prompt 调用,deepseek-chat 计价下成本可忽略(<¥1 量级);写帽(write_max_asks)在真实转录上远未吃紧(12/48)。

## 7. 异常与计划偏差

1. **第一轮对话的 llm 回复触发 V3005 预检拦截**:一条 1899B 回复 >64 段(模型用了编号列表)。为不烧一笔注定失败的 build,加了零成本预检(段数/段长/body 长),并用收紧的 SYSTEM_PROMPT(≤4 句禁列表)重跑对话(第二轮全部回复 ≤64 段)。**这本身是发现:mgraph 的分段上限对「爱列点的模型回复」是真实约束,上线前要么约束生成风格,要么接受 build fail-closed**。
2. **budget_exhausted 回合**:4/8 回合因真实判断低置信走 human→预算封顶(D16 已知)。对记忆试验无影响(user/message 照常策展入投影),但说明 demo 的 human 自动 succeed 策略在全栈真实判断下回合成功率 ~50-75%。
3. **驱动脚本两次 Python 侧崩溃**(evidence 返回形状按 dict 处理实为 `{rows:[…]}`;`memory_consolidations` 无 `subtype` 列)——零 DB 侧损伤;walk 身份确定性 + build cursor 语义让续跑完全幂等(Q1 的 walk 跨进程崩溃后续跑 steps=0 直接收口)。这反过来实测了 M3 的幂等设计。
4. **对话未走 Chainlit UI**:2.12 无 testing 模块;后端链与 app.py hub 完全同代码(driver/port)。UI 层在全栈库上可启动(headless 实测起过,shim/PostgREST 连通),只是没有浏览器端对话回放。
5. 试验库中留有三个会话(两次对话 + 一次 401 失败的残骸),mgraph 观测全部取自试验会话;残骸无消费者。

## 8. 局限

- **B2 未接线**:evidence 现在无消费者——不进 `recall_candidates`、不改装配,读路径只经 `v13_mgraph_evidence` 出口观察;「记忆是否真的改善回答」在本试验中不可见(需要 B2 + 对照)。
- **mem_rel 面未在真实转录上发生**(§3 发现 1):关系判断质量(尤其 contradiction 检测)只在 gate 测试里被 mock 验证过,本试验中一次都没问出去;图的语义结构 ≈ temporal 链 + 1 条固化边。
- **确定性路由升权未被真实行使**:4 个 walk 全部 superset(CJK 规则);why/when/实体分桶的差异化遍历在中文语料上当前形态不可达。
- **矛盾修正链未被考验**:T2/T6 的潜在 contradiction 既没有关系问(零对)也不可能是固化相邻对——更正语义在当前图里只能靠读环词法命中两个节点各自呈现。
- 单会话、单次 build;rebuild 幂等、multi-generation、走环并发(interference with build 锁)未测;build 后未再驱动回合,dec-refresh 注记(不变量 14:mem_ 决策使下一次装配 token 失配一次)未实测。
- 成本上限:总调用 ≈58,在「适度」红线内(对话 2×8 轮因重跑略超「≤10 轮」字面,判断侧 25 批中 14 批属被 V3005 淘汰的第一轮;build/每查询/walk/固化均各一次)。

## 9. 收尾状态

- `agent_v13_demo_mem` 保留(策略已翻回 v4 双 false;mgraph 暗库默认形态);原库 `agent_v13_demo` 全程未动。
- Chainlit/PostgREST 已停;pgembed PG 仍在跑(便于复查:`uv run python server.py stop` 可停)。
- demo 树内新增/改动文件全部 gitignored;仓库跟踪文件零改动;未 commit。本报告为工作区新文件(未跟踪,不提交)。
