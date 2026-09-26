# v13/memory — DP6 三层记忆栈(逐字层投影 + 水印新鲜度 + 结构化层索引)

Stage 11/11(SQL_LOAD_ORDER 第 11 位,纯末尾追加)。消费 DP1–DP5+filter
十文件;本 stage 库 = `agent_v13_memory`(`files_through('memory')` 前缀
切片,11 文件;stannum 前置探针 fail-closed)。设计:
`docs/designs/v13-context-on-pg.md` §4.4/§9/§10(投影 p99 gate);教程
ch13:58-59/64-79/130-135。gate:`uv run python v13/memory/test_memory.py`
(I–N 六组,退出码 0=通过)。

## 机制

1. **逐字层** `transcript_chunks`(§9 五列逐字):每策展事件一行
   (seq_from=seq_to,OQ8);策展词表=`user/message`+`llm/message` 且
   非空体(assistant=llm/message;tool/result 与编排事件永不入记忆);
   独立表独立索引(文档/记忆语料分区,DP4 契约⑦;零 corpus 列);
   content_hash=`v13_body_hash`(与 chunks 同公式——跨平面内容寻址一致);
   自证 CHECK+FK 源事件;UPDATE 拒(不可变)、DELETE 留给全量重建
   (owner 平面,无 retention 引用面)。
2. **水印新鲜度(F10/OQ5)**:`v13_transcript_watermark`=投影覆盖上界;
   `v13_transcript_freshness`={watermark,max_curated_seq,lag,max_lag,
   degraded}——lag=max 策展非空体 seq−watermark(编排事件与空体均
   不入分母——dp6.1 P1-1 修，尾部空体不再致 watermark 滞留);
   超界 → degraded=true + RAISE NOTICE(运维可见)。**fail-closed**:
   reader `v13_transcript_recall` 只读 transcript_chunks,零 events 回退
   读路径;当前 turn 消息永远经 canonical_state 直读(结构性,零投影
   依赖);**滞后上界**:memory_stack.max_lag_events=16。
3. **degraded 消费契约**(发布给 DP7+/装配接线者,§1.4 DP7④):
   degraded=true 时记忆层不得作为可靠召回面,消费侧须落审计事件并降级
   ——recall 平面纯 SELECT(DP1 角色分裂)不可写事件,故 DP6 以
   NOTICE+结构化状态+本契约三件套兑现(附 A #9)。
4. **记忆 reader** `v13_transcript_recall(uuid,text,int)→TABLE
   (content_hash,bm25,seq_from)`(签名冻结):入口 `v13_tinql_terms`
   文法守卫(DP5 同族);排序 分值 DESC,content_hash ASC 终裁;
   `==>` 恰 1 次(reader EXECUTE 串;三禁纪律;文件 11 源码计数=恰 1,
   `stannum.` 限定名恰 3=full_score×1+verify_index×2,gate K4)。
5. **结构化层**:`ix_decisions_question_stannum` 建在
   decisions.question(append-only 不可变列=不可变段,零 fold churn;
   §12 台账的语义决策缓存机制不做,索引为使能件,可独立 DROP)。
6. **校验器** `v13_verify_memory`:五项(自证/源事件在/策略行在场/
   两索引 stannum.verify_index findings=0);p_raise=true 红 → V3006。

## 运维纪律(README 必记八条)

- **① tick=扫地僧不是节拍器**:cron 间隔≠duty_cycle;关掉 cron,turn
  推进仍靠 settle(ch13:130-135)。`v13_rebuild_transcript_chunks(100)`
  恒手动可调,正确性零依赖调度。
- **② pg_cron 前置/降级**:pg_cron 受 `cron.database_name` 闸——非该库
  CREATE EXTENSION 被拒(本仓 stage 库常态);降级形态=NOTICE+外部调度
  (crontab 等价:`*/5 * * * * psql $DB -c "SELECT
  v13_rebuild_transcript_chunks(100)"`)。可用库内 job 名
  `v13-sweep-transcript`('*/5')。
- **③ 水印语义**:fail-closed/滞后上界(16)/degraded 消费契约——
  消费者见 degraded=true 必须落审计事件并降级,不得以记忆层为可靠
  召回面。
- **④ 策展词表**:user/assistant=llm/message;新增语义事件族时评估
  入列(改词表=新 builder 版本)。
- **⑤ stannum 双索引**(ix_transcript_stannum=**jieba**(U3c 2026-09-26,
  `WITH (tokenizer=jieba)`；预热/漂移治理见 characterize README)/
  ix_decisions_question_stannum=unicode 不动(ASCII 列零收益))
  与 verify_memory 手动命令:`SELECT v13_verify_memory(true);`。
  引擎 schema 部署授权见 setup_db.py(filter 同款,台账 #7)。
- **⑥ worker 长连接预热注记**(§4.4 原文:连接预热税):stannum 新连接
  buffer 重建——池预热(连接常驻=worker 契约既有形态,DP5 M 组同族)。
- **⑦ p99 度量协议**(gate L 组,DP4 H1 同款):基线(空投影 2000 次
  append 计时)vs 载入(并行 builder+2000 append)→ p99_loaded ≤
  max(p99_base×1.25, p99_base+0.5ms),三轮取中位;噪声带宽取大。
- **⑧ 会话全扫空转的台账触发**(聪明 tick):v1 会话全扫(数量级小);
  触发=会话数实测超标 → ch15:91 台账重开(§7)。**饥饿具体化(dp6.1,
  L4 P2-6)**:rebuild 按 session_id(uuid)升序逐会话耗尽全局 limit——
  持续积压的低 uuid 会话饥饿后续会话(plan 风险 #9「v1 接受会话全扫」
  的具体化);不单独修，随本条台账在阈值触发时与聪明 tick 同批修。

## 明确不做(§7 台账)

远程层(摘要 artifact 引用,§4.4 明文不实现);语义决策缓存机制(§12,
索引已建);记忆 reader 接入信封 candidates/manifest 段(无消费者,OQ5
消费契约已发布);区间合并(相邻事件并段)/每段多事件(OQ8 批量优化);
更聪明 tick/requeue/recover cron jobs(§12 触发未至,附 A #8);
tsv 双引擎/换体缝(OQ9:同签名 OR REPLACE 即换)。

## 实现偏差台账

1. **transcript_immutable 触发器加 `USING ERRCODE='V3006'`**:草案
   RAISE 无 ERRCODE;不变量 10(新 RAISE 统一 V3006)优于草案字面
   遗漏。零行为分叉。
2. **引擎 schema 部署面授权(setup_db.py)**:与 filter stage 同款
   (USAGE+score_bound/score_bound_indexed EXECUTE 三角色)——N2 的
   角色身份 reader 链需要;SQL 文件保持 K4 计数(恰 1/恰 3)。
3. **pg_cron 不可用于 stage 库**:受 cron.database_name 闸(本仓引擎
   事实),N1 走 DP4 G6 同款降级分支断言(builder 手动可调+行为面);
   DO 块与降级 NOTICE 逐字保留,pg_cron 可用环境自动挂 job。
4. **K3 复合计划形态(risk #11 实测)**:`session_id = $1 AND body ==>
   $3` 的计划=PK bitmap(session 谓词绑 transcript_chunks_pkey)+
   `score_bound_indexed` 索引化计分——stannum 机制在场、确定性、零
   Seq Scan,但**不选 Custom Scan**;无 session 谓词的 bind 才驱动
   Custom Scan。gate 断言随升(§5 风险表 #11 预授权);reader 体保持
   草案逐字(索引化计分已背书,无需预过滤改体)。
5. **dp6.1 P1-1:freshness 分母排空体**(L4 §4/§5;plan 草案自带缺陷,
   实施原逐字忠实):草案 v_max(max 策展 seq)不排空体——尾部空体不可
   投影，watermark 永滞其后、lag 永不归零；尾部空体 ≥17 时 degraded=true
   永久谎报(投影实已覆盖全部可投影内容)，DP7+ 消费契约会误禁记忆段。
   修法一行:v_max 查询加 `AND coalesce(e.payload->>'text','') <> ''`
   (与 rebuild 策展口径逐字对齐;lag 语义=「可投影滞后」，可归零;
   watermark 定义不动，单调性不受影响——v_max(非空)≥v_wm 恒成立)。
   gate J1b:尾部空体 fixture → lag=0 ∧ degraded=false(分母不排空体
   则 lag=1≠0 即红)。同轮 J3 直读对照改挑最新 tail(canonical 含
   tail ∧ 投影不含——「canonical 含最新」半边直接钉死,L4 P2-5;fixture
   追加 user 锚推 last_user_seq 使尾部沉淀入 canonical 窗,否则尾部在
   窗外结构性不含;lag 断言 20→21)。

## 回退

删 `v13/memory/` 树+load.py 第 11 位+`DROP DATABASE agent_v13_memory`
即净;transcript_chunks/两索引/策略行可暂留(零消费者)或逐对象 DROP。
