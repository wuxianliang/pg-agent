# v13 mgraph_assembly(B2 装配接线,Stage 16)

计划:`docs/plans/v13-mgraph-assembly-wiring-plan-2026-09-24.md`(裁决 §1.5:
Stage 16 尾追加、A4/AF1、B-T1+B-E2、C2 窄、D1 七键、E4、F1)。
库:`agent_v13_mgraph_assembly`(`STAGE_THROUGH["mgraph_assembly"]=16`,
16 文件全量加载)。gate:`uv run python v13/mgraph_assembly/test_mgraph_assembly.py`
(组 J;每里程碑另跑 `uv run python v13/mgraph/test_mgraph.py` A–H)。

## 机制一条

把 mgraph 记忆证据接进装配上下文:manifest 升 v4(`manifest_version` 3→4、
required revision 第十二键 `mgraph_ver`),`memory_graph` 段从**已停** walk 的
evidence 注入(§3.2,W2),工人契约把 walk 步进放在 refresh settle 之前(W3)。

## 运维第一条(错文件编辑防线)

**16 文件库里 `pg_get_functiondef` 才是装配活体。** 换体五函数
(`v13_context_required` / `v13_prefix_identity` / `v13_assemble_manifest` /
`v13_manifest_validate` / `v13_refresh_context`)的加载序最新定义在本
stage 文件;再改 `v13/periphery/v13_periphery.sql` 只影响 ≤14 号库,16 号库
看不见。mgraph 两文件字节不动(`v13/mgraph/v13_mgraph.sql` 的 OR REPLACE
闭集维持 `{v13_mgraph_envelope, v13_requeue_stale}`,F7 原文不改)。

## W1 交付面(J1–J3)

- `v13_mgraph_asm_ver(uuid)`:token 第十二键单源,STABLE,
  `sha256({generation, policy_version})` 窄 digest;无活动 mgraph 行 V3009;
  无 meta 行 generation=0。材料钉死两键:不放 query_hash(该事件已推 `sem`)、
  禁止 frontier 哈希(walk 提交在 revision 写回后会自激下一轮 refresh,§1.4 C2')。
- `v13_context_required` 十二键(十一键逐字 + `mgraph_ver`);
  `v13_prefix_identity` 九键不变,`manifest_version` 字面量 3→4。
- `v13_manifest_validate` v5:断言 version 4;required_revision 十二键串 +
  `mgraph_ver` 64hex;kind 词表 +`memory_graph`;applied transform 名
  +`memory_inject`。外层 12 键串 / section 9 键串不改。手造 version=3 必被拒
  (V3003);旧 artifact 走 `v13_replay` exempt 路径不进 validate。
- `v13_refresh_context`:策略行锁名单八名(七名 + `mgraph`,ORDER BY name,
  `summary_accept` 必须留在名单);generation latch 之后、assemble 之前
  `pg_advisory_xact_lock(v13_lock_key(sid,'mgraph-build'))`(锁序最末;
  与 build 的会话级锁、run_round 的 xact 锁互斥)。W1 尚无 memory belt /
  degraded audit(W2 就地加)。
- ACL:`v13_mgraph_asm_ver` REVOKE PUBLIC + 三角色;`v13_mgraph_evidence`
  补 `v13_route`(原 recall/resolve 保留);progress/policy/body_hash/
  freshness 显式三角色(重复 GRANT 保持)。`run_round`/`next_action` 维持仅
  resolve;`v13_lock_key` 不授予 route。
- 前 15 个 SQL 文件字节冻结(J3 内嵌 sha256 表;mgraph 两文件在列——F7 精神
  由 J7 再钉一次)。

## W2 交付面(J4–J7)

- 五个新函数(§3.1,均 STABLE 零副作用):`v13_mgraph_turn_query`(最新
  user/message 的 btrim 文本,无行返 '',走 events 不走 canonical);
  `v13_mgraph_provenance`(七键闭集:origin/speaker/conflict/seq_count/
  seq_first/seq_last/source_hashes;同文折叠=mixed+conflict,意外 type=
  unknown+conflict 不 RAISE,consolidation 不展开亲本,无节点=belt 形);
  `v13_mgraph_section_plan` 单一分支表(判定顺序锁死:empty_query →
  disabled → degraded(不读 walk)→ no_walk → no_rows → emit);
  `section_status`/`section_material` 两包装(JSON null ↔ SQL NULL,
  禁止两套条件)。
- assemble 复制体就地增量(§3.2/§3.3 闭集):sec_src 第六支
  (`memory_graph` 单段,Session/LastResort,blob 化 payload_ref);
  `cls`/`fcls` 两份 bkind CASE 平行加 `WHEN 'memory_graph' THEN
  'retrieval'`(fcls 侧是死代码,保持文本平行);final_sec 加
  `memory_inject` 臂;sections 聚合过滤未 applied 的 memory_graph 段
  (其它 kind 一个不丢——预算裁掉的段不留在数组里,wire 看不到)。
- validate 交叉检查(§3.4⑥):kind=memory_graph ⇒ cache_scope=Session、
  payload_ref.kind=blob、applied 时 name=memory_inject(V3009;priority
  不锁死)。
- refresh memory belt(§3.6③,summary belt 后、artifact_land 前):段在
  →重算材料 digest 恒等 + blob_land 两参落行复核;段不在→不 land、
  不因材料非 NULL 而 RAISE(P0-3 只正向复核);degraded 审计(§3.6④,\n  指针后 shadow_observe 后):仅 status=degraded 落一条
  audit/memory_degraded,审计型不进策展词表、不推 sem/dec。
- 材料不进 `sec_full`(B-E2):J4 断言同夹具有/无 walk 的
  economics.pressure.t_used 恒等。
- est 复用既有整数式:J4 断言 est*divisor ≥ bytes 且 (est-1)*divisor <
  bytes,不另建 memory token estimator。
- 隔离保留(J7=F7 精神再钉):recall/query_side 候选与 memory_nodes
  不相交;needed_judgments 无 mem_;econ_ver 函数体仍只列
  context_tiers/context_budget;前 15 文件字节冻结复断言。

## 身份升版注意(fork/replay)

`prefix_identity` 含 `manifest_version`(3→4):子会话现算身份不等于父
artifact 冻结的旧哈希,`v13_fork` 的 validate-spawn 拒 v3/v4 不一致——这是
身份声明,不是回放种类混用。stage 库 DROP-CREATE,无在线迁移;exact replay
读升级前 artifact 仍返回原字节。

## 实现偏差台账(W 系)

1. **W1 测试夹具无法 DELETE 模拟种子丢失**:`v13_policies` 有 append-only
   触发器(禁 DELETE)。J1 的「活动行被删 → V3009」改用「翻 active=false
   不补后继行」模拟同一读面,断言不变(V3009)。
2. **J2 replay 对比口径**:manifest 自带 `replay` 键(fresh/recompute),
   `v13_replay` 会覆盖它。J2 断言为「两侧各去 `replay` 键后相等」+
   `source_artifact` 指向自身,即计划「除 replay 块外一致」的逐字义。
3. **envelope/twophase gate 在本工作区的既有红(环境)**:两组 gate 用
   `V13.rglob("*.sql")` 扫源码断言「无 mock_response」,会扫进 gitignored
   的 demo 树(`v13/demo/sql/demo_api.sql` 合法使用 `typesafe.mock_response`
   GUC)。该红在无本计划改动的干净树上同样出现(stash 验证),与 Stage 16
   无关。处理:跑这两组 gate 时把 `v13/demo` 临时移出扫描范围、跑完移回
   (demo 内容零字节改动、永不进提交)。
4. **characterize O2 在本机段错误(环境阻塞,既有)**:O2 的 1030 词
   `==>` 查询触发 stannum 0.3.0(pgembed 0.3.0rc2/PG18.4)扩展段错误
   (signal 11,后端崩溃),干净树同样复现,与本计划无关(characterize
   stage 自交付未改)。W1 提交时 characterize 其余断言全绿、O2 因该环境
   崩溃不可达;待 stannum 修复后复跑。
5. **J6d/J6e blob 断言口径**:`v13_blob_land` 对 context_section 是内容寻址
   去重(ON CONFLICT DO NOTHING),tools 内容跨会话相同→首个 effect 持有
   该行,按 produced_by 计数天然不稳定。断言改为「memory 材料哈希从未落成
   context_section artifact」(精确对应计划「不产生 memory blob」)。
6. **J6e retrieval 比例不能置 0**:refresh 的 context_budget 形状守卫要求
   三桶均 >0。夹具用 retrieval=0.0001(+history=0.5499 保持和 1.0):
   retrieval_cap=floor(effective_budget*0.0001)=0,预算裁照样生效。
7. **J6b asks=0 断言面**:judgment_calls 无 signal 列(信号在 decisions);
   且 LIKE 'mem\_%' 与 psycopg2 参数插值冲突。断言改为
   next_action 返回 skip(skipped=disabled)+ 该会话 judgment_calls 零行。
8. **J5 consolidation 夹具须带 consolidation_key**:memory_nodes 的
   `v13_mn_consolidation_shape` CHECK 要求 origin=consolidation 时
   consolidation_key 非空;夹具用 `v13_mgraph_pair_digest(两亲本哈希)`
   单源取值(与 M4 固化产物同式)。

## 回退

删 `v13/load.py` 两处追加 + 删本目录,DROP `agent_v13_mgraph_assembly`。
前 15 个文件未动,前序库不受影响。已写入的 v4 context artifact 在回退后由
validate v4 拒(V3003,非静默);`v13_replay` 仍能读出旧字节。不要只翻
active 策略来「回退」——装配行为在函数体里,不在 mgraph 策略 JSON 里。

## 待办(W3 预告,本 README 随各里程碑同提交更新)

- W3:工人双连接契约(J8–J9)——步数帽 `maximum_jev_calls*6+8`、续租、
  SET ROLE 实测 ACL。
