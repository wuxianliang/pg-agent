# v13/filter — DP6 过滤管道(存在性 Noul 先行 + per-chunk Score)

Stage 10/11(SQL_LOAD_ORDER 第 10 位,纯末尾追加)。消费 DP1–DP5 九文件;
本 stage 库 = `agent_v13_filter`(`files_through('filter')` 前缀切片,10 文件)。
设计:`docs/designs/v13-context-on-pg.md` §4.5/§6.1/§10 G-ctx4;评审 stepfun
F1(默认分支)/F2(存在性键候选集维度)——本 stage 立法落地,设计稿未改。
gate:`uv run python v13/filter/test_filter.py`(A–H 八组,退出码 0=通过)。

## 机制

1. **存在性 Noul 先行闸整批**(§4.5/G-ctx4-1):resolve 的 filter 半边先问
   一个 `corpus_exists`(state=查询全文+全候选体),`v13_existence_action`
   按闸带评估(≤0.30 闸关 / ≥0.40 放行 / 中间 review 带→defaults)。闸关
   =「语料无答案」时 per-chunk Score 外部调用 0(1 次调用替代 k 次)。
2. **per-chunk Score**(批 ≤32=信封冻结 `batch_questions`):signal=
   `chunk::<content_hash>` 差分身份;state=`{query, chunks}` 批态投影
   (模板 projection=`["query","chunks"]` 经 `v13_project_state` 执法);
   落行 context=`v13_filter_ref(goal_hash, chunk_hash)`(材料=存储三位一体,
   装配按字段等值 join,零哈希重算/零 GUC/零信封依赖)。
3. **F2 存在性键含候选集维度**:`v13_existence_ref`={query_content_hash,
   candidates_digest};digest=**排序去重候选 content_hash 全集**的 sha256
   (`v13_candidates_digest` 单源,信封侧/装配侧同函数同输入)。重摄取→
   候选集变→digest 变→新键→陈旧「无答案」不复用。**仅候选维度**:
   bm25/spans 不入料(语料统计漂移不轮换存在性键);目录/模板变更也不
   轮换本键(候选不变则闸门语义不变)。
4. **跨 session 缓存/复用**:per-chunk/existence 行直接经 DP2 canonical
   consult 机制落 decisions(status='cached',reused_from=canonical
   request_hash)——零新映射表(DP1 契约)。
5. **F1 默认分支**:`judgment_defaults` v2 填两点三态(OQ6 全 fail-open
   证据装入方向):chunk_score {missing:include, timeout:include,
   review:degrade}/corpus_exists 三态全 include。运行期缺点/缺态=
   `V3006` 响亮(`v13_filter_defaults_action`);trace 的 basis 字段
   ({decision,decision_review,default_timeout,gate_closed,
   default_missing})是 F1 三态的可观测区分面。
6. **体缺守卫(键-态绑定)**:存在性键覆盖冻结候选全集,state 就必须以
   全集体为载荷——任一候选体缺(parse→resolve 窗口内 chunks 行被删)
   →本 pass 整个 filter 面跳过(不问不缓存不消费,过滤行剔出 remaining;
   下一信封自然收敛)。`v13_filter_bodies_present` 守卫 + resolve 内
   态基数 belt 双保险。
7. **批写锁纪律**(DP4 契约①):单事务内全部含 chunk 引用的 decisions
   INSERT 严格按 signal 升序(=hash 升序)——consult 循环/fbatch 构造/
   filter_ask 落行循环三处 ORDER BY signal;与删除端(source→hash 升序)
   复合序无环。DP4 既有触发器逐行取 advisory 锁,零新锁对象。

## 授权换体(§1.1 九处清单;上游文件零改动)

| # | 对象 | 形态 |
|---|---|---|
| 1 | `v13_judgment_hash` | OR REPLACE:group_state 改经 `v13_row_context` 族分发(canonical 逐字节不变;分支仅 corpus_exists/chunk::% 两处) |
| 2 | `v13_judgment_envelope` | OR REPLACE(第 4 次换体):rc/tmpl 前移+fg 模板守卫+frows 过滤行并入 needed+groups 仅 canonical;20 键集零增删,csh 公式不变 |
| 3 | `v13_resolve_judgments` | OR REPLACE:canonical 半边逐字+NOT IN 腰带;filter 半边新增;remaining 闸感知/体缺感知;返回含 gate_open |
| 4 | `v13_assemble_manifest` | OR REPLACE:rc2/fc 单源物化;qside candidates decision_id 填充;jud 消费集+final_action 真值 |
| 5 | `v13_chunk_referenced` | OR REPLACE:decisions 半边 ->> 提取改 @> containment(语义逐字节等价,G2 双查断言) |
| 6 | chunks/decisions 各追加一索引 | ix_chunks_content_hash(非唯一)/ix_decisions_chunk_ref(GIN)——纯追加,可独立 DROP |
| 7 | `v13_policies` 两行族种子 | chunk_filter v1 / judgment_defaults v2(先插 inactive 再双 UPDATE 翻 active) |
| 8 | `judgment_templates` 两族行 | corpus_exists/chunk_score v1(epoch='pre-finalize',经版本父表 draft→内容行→freeze) |
| 9 | decisions 追加 stannum 索引 | ix_decisions_question_stannum——**由 memory stage 落**(第 11 位;§4.4 结构化层) |

## 运维纪律(README 必记七条)

- **模板/策略 authoring**:两族模板经版本父表(draft→内容行→freeze);
  任何模板/judgment_defaults/chunk_filter 变更=新版本行;**filter defaults
  points 必须在 active 行**——运行期缺=V3006 fail-closed。chunk_filter 与
  chunk_score rubric 配套同批翻版。
- **闸门语义**:带值(≤hi 闸/≥lo 放行/中间 review)/三态 fail-open
  (missing/timeout/review 全不闸——证据装入族)/闸关→路由照常 intent
  驱动(无 chunk 上下文=设计既定形态,过滤不承载路由)。
- **缓存键形态**:per-chunk=hash(题面/criteria, chunk.content_hash,
  query.content_hash, provider/model);存在性={goal_hash, candidates_digest}。
  重摄取→新候选集→存在性重问(F2)。
- **批写锁纪律**:resolve 内部已按 signal 升序;直调批写 per-chunk
  decisions 的第三方代码必须同序或拆事务(DP4 契约①)。
- **翻版纪律**:chunk_filter 版本不入 token v1(只影响 final_action/trace
  派生);judgment_defaults 翻版追动 jdef_ver→全域恰一次 refresh。
- **mock 仅测试**(G-ctx1-5):provider/model/mock 均测试面 GUC。
- **一页账**(DP7 经济件输入基线):canonical(1)+存在性(1)+⌈k/32⌉;
  k=8→3 ask(1 快路+2 慢路轮)、k=64→4 ask(1+3);闸关=2 ask 即止;
  全命中恒 0。

## 实现偏差台账(与 plan §3 草案字面差异;行为零分叉)

1. **timeout 冻结用 `EXECUTE format('SET LOCAL …')` 不用
   `set_config(...)`**(plan 草案写 set_config):DP1 G-ctx1-5(b) 对
   `v13/**/*.sql` 全树扫 `set_config` 子串(test_twophase),DP2/DP4/DP5
   同款家族偏差(envelope README 台账 #3 先例)。`SET LOCAL` 与
   `set_config(...,true)` 同为事务局部,语义等价。
2. **E5/C5-1 α 超时形态按 #45(b) 降级**:本仓 pg_typesafe HTTP 等待不可
   被 statement_timeout 中断(resolve/setup_db.py probe_timeout 实证,
   sqlstate=08006);DP1 turn 7 #45(b) 家族裁决=已声明分类的超时以 V3001
   β 路径兑现。gate 断言:malformed→failed_validation 行+failed=true
   (E4/C5-1);挂起 socket 远端错误 fail-loud 上抛(E5-a);未声明分类的
   pg_cancel→query_canceled 上抛(E5-b)。引擎支持中断式 HTTP 后升回
   failed_timeout 直测。
3. **tmpl CTE 增补 question/criteria 两列**:plan 草案的 fg 守卫与 frows
   题面取数消费 `templates->…->'question'/'criteria'`,而 DP5 载入态
   tmpl 只携 version/kind/projection/answer_schema_version——增量②③
   的结构必需项;needed UNION 臂加 `NULLIF(f->'criteria','null'::jsonb)`
   还原 SQL NULL(DP2 json-null 坑家族纪律,README 台账 #1 先例)。
4. **filter_ask 落行循环显式 ORDER BY signal**:不变量 7 三处 ORDER BY
   的第三处(草案正文要求、§3.1 函数体漏写);批写锁纪律的落行半边。
5. **per-chunk fbatch 聚合别名 s.value**:草案 `jsonb_agg(g.value …)` 引用
   子查询内别名(加载报错);语义同构。
6. **jud CTE 行别名 "row"**:ROW 为 PG 保留字,草案 `AS row` 加载报错;
   引号包裹,零语义差。
7. **引擎 schema 部署面授权(setup_db.py)**:角色对 `stannum.full_score`
   有 PUBLIC EXECUTE,但引擎 schema 无 USAGE、内部 `score_bound`/
   `score_bound_indexed` 带显式 owner-only ACL(DP5 characterize 面
   缺口——其 gate 未覆盖角色身份执行引擎链的形态)——角色执行的
   trace→recall_candidates→recall 链 42501。H1 矩阵要求角色链可执行、
   H6 要求第 10 号 SQL 零引擎限定名,故 `GRANT USAGE ON SCHEMA stannum`+
   两函数 EXECUTE 落 **setup_db.py 部署面**(run_probes 同位先例),
   SQL 文件零引擎依赖。**呈报父 loop:该缺口属 DP5 面,建议后续统一收口。**
8. **ACL 链闭包(SQL 内)**:trace(三角色)→chunk_filter_action→
   `v13_existence_action`/`v13_filter_defaults_action` 的 invoker 链要求
   两函数对三角色可执行(计划 L11 只授 resolve/route;existence_action
   补授 v13_recall,defaults_action 补授 v13_recall+v13_route)。计划
   H1「trace 于三角色 ✓」的结构性必要项,纯追加。
9. **gate fixture 注记**:canonical/per-chunk 缓存是**全局**键(跨 session
   同 goal+语料即命中——D2 的设计面),故 A–H 各 case 用独立 token+corpus
   隔离;E2 的 k=64 fixture 经 recall_k k_base→64 版本化翻行(测毕还原)
   ——widen_ratio 0.05 下 64 文档只给 k=8,翻行是达到 k_max 的最短路径。
10. **advance 时序注记**:parse 落行后 context 必 stale(②),judge effect
    在 refresh settle 之后才建——E1/E2 的 worker 夹具先 settle 再以
    with_current_probe 探针化推进(DP1 既有驱动面形态,非新缝)。

## 会话/连接纪律(测试面)

`typesafe.provider` 是 placeholder GUC(pg_typesafe 未注册该名):只能在
**未加载扩展库**的连接上写(即该连接首次 typesafe_ask 之前),会话域
(`set_config(..., false)`)跨事务存活;mock_response/timeout_ms/endpoint/
model 为注册 GUC,任意时刻可写。gate 的 helper 全部按此纪律(新连接/
recycle 后才设 provider)。

## 回退

删 `v13/filter/` 树+load.py 第 10 位+`DROP DATABASE agent_v13_filter` 即净;
共享库重跑 DP1–5 文件恢复 envelope/resolve/assemble/judgment_hash/
chunk_referenced 旧定义;新增索引/策略行/模板行可暂留(零消费者)或逐对象
DROP。禁删 canonical 审计数据(judgment_cache/judgment_calls/decisions)。
