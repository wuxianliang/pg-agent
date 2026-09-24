# v13 mgraph 装配接线计划(DP9-OQ8 所称「B2」)

> ⚠ 命名消歧:本计划即 DP9 计划 §1.3-OQ8 裁决「属下一张计划」的 **B2(装配接线)**;与 v2 计划 OQ17 的「B2+B3 选对基面」(proximity 对源,已交付)是**同名异物**。本计划全文以「装配接线」称之。

## Goal

把 mgraph 记忆证据(`v13_mgraph_evidence`)接进 v13 装配上下文:manifest 新增 memory_graph 段(含 provenance 标注)、给读环一个生产驱动入口、处理 mgraph_generation 与 manifest freshness 的接线,使「记忆是否真的改善回答」首次可观测。触发条件已由用户决定满足(DP9 §8「evidence 出口出现真实消费者」)。

## Background

### 装配链活体面(改动会碰的 12 处,见 periphery/manifest 文件)

- `v13_assemble_manifest`(活体 periphery:688,单条 WITH 46 CTE):段源 `sec_src` 五分支(goal/history/tools/summary/compaction,periphery:806-849)是加新段主缝;**全量基面 `sec_full`(:850-872,仅 3 分支)是 pressure/ER/compact_hint 的决策面**——新段进不进全量面必须显式裁(不进则经济学结构性看不见它,进则 t_used/bp 追动);`bkind` CASE 未列名的 kind 默认落 `retrieval` 桶吃 `retrieval_cap`(:876-878,:1181-1184)。
- `v13_manifest_validate`(periphery:1458):外层 **12 键恰等**(:1466-1474);section **9 键恰等**硬墙(:1734-1815)——kind 词表 5 值、payload_ref.kind ∈ {goal,blob}(**payload_ref 未锁键集,是唯一松口** :1789-1797)、transform.name 4 值(:1803-1810);`manifest_version` 断言=3(:1475)。
- `v13_render_section_body`(periphery:417-429)**二值 CASE**(blob→artifacts.inline / goal→v13_goals.payload)——mgraph 正文在 `memory_nodes.body` 不在 artifacts,需第三臂或 blob 化落地(refresh 的 blob-land 段先例 periphery:2226-2290)。
- `v13_context_required`(periphery:191-239)十一键;`dec`=answered decisions 计数(:230-231)。**追动键纪律**(DP7 计划 :28):「进 manifest 输入的策略版本必须在 token 有键,漏键=静默用旧 manifest;键集增删=全域恰一次 refresh」。
- token 闭环三处:比较 `v13_context_fresh`(manifest:205-208)→ 触发 advance ② enqueue `context_refresh`(advance.sql:313-316)→ 写回 refresh settle 尾(periphery:2293-2296)。`v13_refresh_context` settle 走 SECURITY DEFINER(periphery:1948-1950)。
- `v13_econ_ver` 词表(economy:226-231):mgraph 行进 assembly 消费集即入 ver。
- 回放:fresh/recompute 是装配内派生模式(validate 词表恰此两值);`exact_replay` 走 `v13_replay` exempt 路径(manifest:915-921)**不过 validate**;spawn_kind 三值 + validate-spawn 前缀身份检查(periphery:45-46,317-320,392-396)。
- manifest 升版先例 v1→v2→v3(DP7 :142-147/DP8):**换体=机械复制加载态最新前驱+增量标注+墓碑注记**;kind 词表两跳纪律(升版文件不前向引用);compat 零迁移(exempt replay 逐字节回放老 artifact)。当前三活体均第 4 代,B2 将是 v5 + `manifest_version` 3→4。
- wire 形态(`v13_render_wire` periphery:434-480):sections 按装配原序渲染带 marker;est 公式单源纪律 `(bytes+divisor-1)/divisor` 三处逐字同式(:507/:894/:990-995),新段必须复用否则 cache_probe 持续落事件。
- **CAND4 闭集被三 stage gate 钉死**(recall/filter/characterize):记忆证据只能进 `sections` 新段,不能进 `query_side.candidates`(OQ8 四依据之一)。
- DP7 已预发布的消费契约(DP7 计划 :163):「degraded=true 时记忆段不得作为可靠召回面——落审计+降级;当前 turn 消息永远直读」。evidence 已内建该闸(mgraph:2519-2531)。
- ACL 缺口:`v13_mgraph_evidence` 只授 recall/resolve(mgraph:2587-2591),而 `v13_assemble_manifest` 授 route/resolve/recall(manifest:937-939)——**route 手直调 assemble 的既有授权面会缺 evidence EXECUTE**。

### evidence 出口与生产入口现状

- `v13_mgraph_evidence(sid,query_hash)`(mgraph:2509-2551,STABLE 零 ask):返回三键 `{rows:[{content_hash,score,body}], skipped, asks}`——**无 provenance/origin/seq**;frontier 哈希在 memory_nodes 无行时 inner join **静默丢弃**(:2547-2548);定位键=当前 generation+活动 policy_version+query_hash+`status='stopped'`(:2538-2545);disabled/degraded 双跳过带 skipped。
- **query 无生产来源**:所有调用方(test/demo)硬编码;`pending_walk` 当年是 manifest 字段设想(DP9 :111「删除 manifest 段/mgraph_gen/pending_walk/manifest v4 的 DDL 与 F7-B2」),其 DDL 被「有意删除不留档」(design 评审 :5 明确不复核)——B2 设计要从零再立。
- walk 生命周期:保留=不清理、会话终态不执法(status 仅 open|stopped,mgraph:1380-1404);walk_id 确定性 md5(sid:qhash:gen:pver)(:1407-1413)。
- 驱动现状:B1 读环无生产入口,resolve_login 手动;transcript 投影 tick 手动(pg_cron 被 cron.database_name 闸,memory README :44-51)——build/read 两路都以 transcript_chunks 为前置。
- demo 侧线索:driver `_dispatch` 对 context_refresh 等 kind 走 fail-loud(demo driver.py:213-229),RPC/ACL 已铺(demo_api_mem.sql:12-19);全栈下 advance ② 每回合 enqueue context_refresh(实测 12 次/会话)——**context_refresh effect 是现成的异步结算车**。

### provenance 数据可得性(实测发现的原始动机)

- `transcript_chunks` **五列无 kind**(memory:18-29);user/llm 区分唯一通道=FK 两跳:`content_hash → transcript_chunks(session_id,seq_from) → events.type`(events.type 开放词表,ix_events_last_user 部分索引在)。
- build 已经在做这个 join 只取了 `e.at` 没带 `type`(mgraph:961-965);`memory_nodes` 行不可变(UPDATE 触发器 V3009)——加列=新 builder_version+重建;episodic `source_hashes` 单元素=chunk 哈希,consolidation ≥2 亲本+consolidation_key 天然可区分。
- 边界:同文本被 user 与 llm 都说出 → 投影 PK (session_id,seq_from) 按事件各一行但同 content_hash 在 memory_nodes 折叠为一节点(OQ4),provenance 在哈希碰撞时不可分辨。
- 原始动机:trial 实证模型幻觉复述(「周六九点」→「周日上午九点」)以 0.824 高分可召回且与用户原话同权进 evidence 行(trial §4)。

### 先例与被裁设计考古

- OQ8=B1 四依据:语料面错配/CAND4 无 spans 语义/§6.2 超集纪律(不改装配就无法用记忆证据做排除)/要动三个活体+manifest 升版。
- **F7 gate 现在断言的正是装配接线的反面**(test_mgraph.py:2295-2318:recall∩graph=∅、needed 无 mem_、OR REPLACE 目标集恰等)——接线后要按新裁决重写这些断言。
- v2 计划 §8 把**锚可达性缺口(锚池方向不对称)**显式挂号给「下一张计划(装配接线或 CJK 路由 supersede)同批裁决」;CJK 三触发条件之一反过来要求「不依赖装配接线可观测」——两线互不阻塞。
- 两份实测(trial/rerun):evidence 词法层命中 0.772-0.900 三正例+负例空集;**边从未被遍历**(全部 depth=1 首轮收束);dec-refresh(不变量 14)两轮都未实测。
- 设计权威单薄:设计文档对记忆图装配只有 §4.4 三层栈一句+§5.2 manifest IR 字段族;无专章——B2 计划要承担设计细化(或先出设计修订)。
- 教程登记点:ch7 §7.3(manifest 指针)/ch10 §10.6(跨度装配,G-ctx5)/ch14 §14.4(三种回放,预取污染身份 :169-172)。

> **状态**:v1.0(2026-09-24)。两路 context builder 草案已折入;**Oracle 裁决已折入 §1.5**(grokBuild lane 完整;codex lane 因 402 日额度耗尽缺席)——落点裁 **Stage 16**、OQ-A=A4+AF1、OQ-B=B-E2、OQ-C=窄 digest、OQ-D=D1 七键闭集、OQ-E=E4、OQ-F=F1;P0-1~P0-6 六项必改与 P1/P2 已折入正文。附录 A 保留为「若将来 supersede 时的合法增量」存档。W1 可开工。
>
> **交付进度**:W1 ✅(2026-09-24 交付 5f801d5;J1–J3 全绿,mgraph A–H 与前序 15 gate 回归绿,前 15 文件字节冻结由测试内嵌 sha256 钉死;复制漂移 diff 校验零计划外 hunk;偏差台账 #1–#4 见 v13/mgraph_assembly/README.md——含 v13_policies 禁 DELETE 的种子丢失夹具改翻 active 不补行、replay 对比两侧各去 replay 键、envelope/twophase 的 demo 树 gate 误中同 DP9-M1 先例(提交态干净,跑 gate 时临时挪出扫描范围)、characterize O2 的 stannum 0.3.0 段错误系既有环境阻塞且干净树复现)。
> W2 ✅(2026-09-24 交付 b1a1c86;J1–J7 全绿,A–H 与前序 15 gate 回归绿;偏差台账 #5–#8——blob_land 内容寻址去重(ON CONFLICT DO NOTHING)下按 produced_by 计数不稳定改断「材料哈希从未落行」、context_budget 三桶形状守卫须 >0 故用 0.0001、judgment_calls 无 signal 列改 next_action skip + 零调用断言、consolidation 夹具须 consolidation_key(pair_digest 单源))。
> W3 ✅(2026-09-24 交付 c65362d;J1–J9 全绿(139 PASS),A–H 与前序 15 gate 回归绿;偏差台账 #9–#11——J9 SET ROLE 暴露四个既有 INVOKER 链 ACL 缺口按 §1.7 只补 GRANT 不改函数体(route←judgment_calls SELECT;resolve/recall←render_receipt EXECUTE;recall←effects SELECT+ro_reserve/recovery_active EXECUTE)、typesafe GUC 在已花费连接被删且保留前缀下同后端重建被拒改重连(mgraph #17/#19 同源)、锁探针夹具仿 E6 原样(空会话+预置 stop mock);**W4 未触发**:J8 非门禁观测 no_edge/with_edge 两夹具均 edges_used=0、depth=1、段均出现——段证据无差异,附录 A.5 门槛不满足;**B2 范围完结**)。

---

## 0. 执行索引

### 0.1 里程碑

新 gate 组字母 **J**(避免与 mgraph 已占 A/D/E/F/G/H 及弃用的 B/C 冲突;I 故意空置——v2 已把 I 组随 OQ13=D 移出)。gate 命令:`uv run python v13/mgraph_assembly/test_mgraph_assembly.py`(库 `agent_v13_mgraph_assembly`);**每个里程碑另跑 `uv run python v13/mgraph/test_mgraph.py`(A–H),且 `v13/mgraph/v13_mgraph.sql` 与 `test_mgraph.py` 相对本计划开工时字节不变**。

| 里程碑 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| **W1 身份与校验升版** | 新建尾追加 `mgraph_assembly` stage(第 16 文件,单 BEGIN/COMMIT);复制 periphery 活体,`manifest_version` 值 3→4;`v13_context_required` 加第 12 键 `mgraph_ver`;validate v5 允许新 kind/transform 词但**尚不产出段**;refresh 锁集加入 `mgraph` | J1–J3 绿;mgraph A–H 全绿;**前 15 个 SQL 文件字节不变**;periphery 前缀库仍是 v4/十一键(抽查,不改其测试) | `v13/load.py`(两处);`v13/mgraph_assembly/v13_mgraph_assembly.sql`、`setup_db.py`、`test_mgraph_assembly.py`、`README.md` | Oracle 裁决(§1.5,已裁) | 复制约 1.7k 行 + 增量 <80 行 + 测试约 200 行;1 提交 |
| **W2 段注入** | `memory_graph` 单段从**已停** walk 的 evidence 注入;provenance 只读两跳(七键闭集);不进 `sec_full`;未 applied 的该段不进入 `sections[]`;refresh 做 summary 同构 belt(只正向复核);degraded 落审计事件 | J4–J7 绿;A–H+J1–J3 仍绿 | 同上(就地改 W1 复制体,文件内仍只有一份定义) | W1 | 新函数约 200 行 + 复制体增量约 120 行 + 测试约 350 行;1 提交 |
| **W3 生产驱动** | `context_refresh` worker 在**调用 refresh 之前**用 resolve 连接把 `v13_mgraph_run_round` 步进到停(工人侧步数帽 `maximum_jev_calls*6+8`,不进 SQL 函数体);settle 零 walk IO;默认 `read_enabled=false` 时整链 no-op | J8–J9 绿;全组回归绿;前序 15 个 stage gate 在各自前缀库复跑绿 | 同上(SQL 仅当漏 GRANT 时补;主体是测试 + README 工人契约) | W2 | 测试约 200 行 + README;1 提交 |
| **W4 锚池对称性(条件里程碑)** | 仅当 J8 的**非门禁观测**证明遗漏 contradicts 边改变 section 证据时,修复「只在非 canonical 方向发现 pair 时 contradicts 漏问」 | 新组 **K** gate 绿(见附录 A.5);A/D/G/H 回归 | 同 stage 文件/测试,README 偏差台账 | W3;J8 观测触发 | 约 100–250 行 SQL,约 180 行测试 |

总计 3 次提交(W4 条件第 4 次)。gate 族沿用 G-mg,新组字母 J。**每里程碑独立测试→更新收尾工件→按路径 add→commit→push**(AGENTS.md 纪律)。

### 0.2 提交纪律

每个 W 里程碑独立测试、更新收尾工件、按路径暂存、提交并推送;禁止把 W1–W4 合并成一次提交,禁止 `git add -A`/`git add .`。

---

## 1. 定位与边界

### 1.1 OQ8 授权范围

- **直接观察**:DP9-OQ8 明确裁定当时只交付独立 `v13_mgraph_evidence`,把 manifest `memory_graph` 段、mgraph generation、pending walk 和 manifest 升版移交给「下一张计划」;四依据:记忆语料不能并入文档 CAND4/CAND4 无 spans 语义/§6.2 超集纪律/要动三个活体+manifest 升版。(`docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md:106-111`、`:355-371`)
- **设计边界**(OQ8 授权范围内):
  1. 允许在加载态最新位置换体 `v13_context_required`、`v13_prefix_identity`、`v13_assemble_manifest`、`v13_manifest_validate`、`v13_refresh_context` 及裁决所选驱动所需的加载态最新函数。
  2. 不把 graph rows 加入 `v13_recall_candidates`,不修改 CAND4。
  3. 不把 `mem_%` 加入 `v13_needed_judgments`。
  4. 不修改旧 context artifact;只生成 manifest v4 新 artifact。
  5. 不把 `memory_nodes` 变成 artifact 替代品,也不让 exact replay 依赖可重建表。
  6. CJK routing supersede、walk retention、自动 transcript sweep 不因装配接线自动进入范围。

### 1.2 落点:Stage 16(**已裁**,Oracle)

**Oracle 裁决:新建 Stage 16 尾追加**(两 lane 中 codex lane 的方案)。决定性理由:

- **所有权转移先例是 DP8**:装配活体的新版本历来由**新 stage 文件** OR REPLACE 交出,而不是写进前一所有者的文件。M4 已宣布 mgraph 范围完结,F7 把「不换装配体」钉成该 stage 的契约。
- **J3/J7 只保护 periphery 前缀(14 文件)**:若换体写在 mgraph 文件里,`files_through('mgraph')`=15 文件会跑到新装配,A–H 全绿只是「碰巧没断言十一键/version 3」。Stage 16 让这 15 个库在结构上保持 v3/十一键。
- 复制体约 1.7k 行(periphery 的 assemble+validate+refresh+两个身份函数),放进新文件里审,不放进已经含 M1–M4+v2 的 mgraph 文件。

**落地形态(裁决附加参数)**:

- 目录 `v13/mgraph_assembly/`;库 `agent_v13_mgraph_assembly`;`STAGE_THROUGH["mgraph_assembly"]=16`;SQL 文件 `v13_mgraph_assembly.sql` 只含一个 BEGIN/COMMIT。
- **两个 OR REPLACE 闭集**:`v13/mgraph/v13_mgraph.sql` 维持 `{v13_mgraph_envelope, v13_requeue_stale}`——**F7 原文不改,mgraph 两文件字节不动**;新文件的 `CREATE OR REPLACE FUNCTION` 名集合恰为 `{v13_context_required, v13_prefix_identity, v13_assemble_manifest, v13_manifest_validate, v13_refresh_context}`,该文件 `ALTER TABLE` 次数为 0,禁止 DROP FUNCTION 再重建这五个函数。
- 文件内顺序:新函数先 CREATE,再 OR REPLACE 调用方。W1 的 assemble 复制体还没有 `sec_src` 第六支、refresh 还没有 memory belt;W2 就地改这份复制体,禁止第二份同名 OR REPLACE。
- `setup_db.py` 从 `v13/mgraph/setup_db.py` 机械复制,只改 stage 名与库名,保留 stannum fail-closed 探针(已核:mgraph setup 的 DB/STAGE/probe/GRANTS/run_probes 五处)。
- **J7 的字节冻结改为前 15 个 SQL 文件**。periphery 源文件里的 `manifest_version` 3 / 十一键是 14 号库墓碑,**不在 periphery 文件里改**;行号 164/1389/1475 只用来在复制体上定位。
- 新 README 运维第一条:16 文件库里 `pg_get_functiondef` 才是装配活体;再改 periphery 只影响 ≤14 号库。

**共同否定的方案**:就地改 periphery 文件——会让 14 号库行为变掉,逼改上游测试,违反 DP9 §5「前序 gate 变红不准靠改其测试修」。

### 1.3 基座锁定(这些不是 OQ,裁决也不要顺手翻掉)

1. **活体换体位置 = mgraph 文件末尾新事务,前 14 个 SQL 文件字节不动**(若 §1.2 裁 Stage 16 则改为第 16 文件,其余条不变)。活体 `v13_assemble_manifest`/`v13_manifest_validate`/`v13_refresh_context`/`v13_context_required`/`v13_prefix_identity` 都在 periphery;mgraph 今天的 `CREATE OR REPLACE` 闭集只有 `v13_mgraph_envelope` 与 `v13_requeue_stale`(实测 `test_mgraph.py:2316-2319`)。
2. **复制源 = periphery 文件正文**,不是 manifest 里的七键旧体,也不是 `pg_get_functiondef` 回读。manifest `:170-248` 的 `v13_context_required` 是七键加载态,已被 recall/economy/summary/periphery 逐级换掉。实施时用 diff 证明:相对 periphery 活体,只多本计划列出的增量行。
3. **禁止 `DROP FUNCTION` 再重建** assemble/validate/refresh/context_required/prefix_identity。签名不变,OR REPLACE 保留 ACL。
4. **文件内同名定义仍只一份。** W2 就地编辑 W1 复制体,禁止在文件尾再挂一个同名 OR REPLACE。
5. **`v13_econ_ver` 不扩。** 它只罩 `context_tiers` 与 `context_budget`;mgraph 行不是经济学决策行。economy 文件字节冻结。
6. **`query_side.candidates` 不接记忆节点。** CAND4 被 recall/filter/characterize gate 钉死;OQ8 四依据之一。F7 的 `recall_candidates ∩ memory_nodes = ∅` **保持**。
7. **`v13_needed_judgments` 不出现 `mem_`**(DP9 不变量 10)。F7 该断言保持。
8. **不新 effect kind,不改 `v13/loop/advance.sql`。** `context_refresh` 已是每回合的车;trial 实测一会话 12 次。`effects.kind` 活体已含 M4 的 `mgraph_consolidate`;本计划不再 ALTER。
9. **evidence 返回形状不改**(仍三键 rows/skipped/asks)。provenance 放在段材料里,避免 E 组对 evidence jsonb 的全等断言被连带改写。frontier 无节点行则 inner join 丢掉,材料侧同样丢,不发明行。
10. **节点表 / `transcript_chunks` 不加列。** 两者 UPDATE 都失败(`v13_mgraph_nodes_guard` V3009;`v13_transcript_immutable` V3006)。provenance 是读时连接。
11. **新函数一律 STABLE、非 SECURITY DEFINER、零 `typesafe_ask`。** 读策略就不是 IMMUTABLE。唯一仍为 DEFINER 的是被复制的 `v13_refresh_context`。
12. **新 RAISE 用 `V3009`;复制体里的 V3003/V3007/V3008 逐字保留。** 不新造 V3010。kind 词表扩展写进既有 V3003 的 `IN (...)` 里。
13. **若加 token 键,键名是 `mgraph_ver`,单源 `v13_mgraph_asm_ver(uuid)`。** 禁止塞进 `ident_ver`/`econ_ver`/`gen_ver`(DP8 OQ1 已否决 gen_ver 过载)。
14. **默认策略仍是 `read_enabled=false`。** 接线后不翻种子、不升 mgraph v3 键集。行为面测试沿用 D/E 组「INSERT 新版本 + 双 UPDATE 翻 active,组末翻回 v2」。
15. **provenance 不参与排序、不改 `relation_threshold`/`inject_top_k`/锚编译。** 只让它可见。
16. **本计划是计划,不是设计修订。** 教程章节只登记(§7),不改 md 正文。

### 1.4 Open Questions(选项、依据;**均已裁决**——裁决记录见 §1.5,各题「Oracle 裁决」段含决定性理由与附加参数)

#### OQ-A 生产驱动模型与 manifest freeze 时点

**事实基线**

- advance ② context gate 已在不 fresh 时创建并发送 `context_refresh` effect;trial 实测 12 次/会话——现成的异步车。(`v13/loop/advance.sql:304-331`、trial 报告 §1/§2)
- `v13_mgraph_run_round` 每次最多执行一个动作/一个判断信封,写 `memory_walks`/`memory_rounds`;持 `pg_advisory_xact_lock(v13_lock_key(sid,'mgraph-build'))`,**不持 sessions 行锁**;`v13_mgraph_evidence` 只读已停 walk。(mgraph `:1839-2507`、`:2508-2555`)
- manifest freeze 要求 final manifest 只消费 freeze 前完成的精确 evidence;迟到结果不得回写冻结 artifact。(设计 §6.1,`docs/designs/v13-context-on-pg.md:258-281`;机制源=artifacts append-only + `v13_epoch_frozen`)
- `v13_refresh_context` 一进门就 `sessions FOR UPDATE` 并锁策略行,然后才 assemble;refresh **内部**调用 `v13_complete`,成功后才 `blob_land`(effect guard 要求 produced_by 已 succeeded)。walk 必须发生在这次调用**之前**提交,assemble 才能在同一语句快照里看见 decisions 与 stopped walk。(periphery refresh `:1948` 起)
- advance ② 在 enqueue 后直接 `RETURN 'waiting'`,本身不 settle。(`advance.sql:313-326`)

| 选项 | 机制 | 收益 | 代价/风险 |
|---|---|---|---|
| **A1 同步 parse/advance 前游走** | parse 或 advance 内直接把 walk 驱动到 stopped | 当前 turn 一定拿到最新证据 | 把多轮判断和延迟放入回合推进;与 DP9 已否决「读环进 parse/session lock/effect」的边界相冲突;最容易把外部 IO 带入持锁事务。**等于重开 DP9 §8 否决,若 Oracle 选此项须先显式 supersede** |
| **A2 独立后台 pending walk,下一回合消费** | 当前回合先 settle 无图段;后台 effect 完成 walk,revision 变化后下一回合 refresh | 首回合低延迟 | 明确 stale 一拍;DDL 要从零再立(DP9 `:111`「有意删除不留档」);异步完成必须可靠追动 token |
| **A3 sweep tick 驱动** | 外部调度周期性找待跑 query 并推进 walk | 与 transcript tick 运维形态类似 | stage 库无 cron;当回合回答看不见当回合记忆,与 Goal「记忆是否改善回答」错拍 |
| **A4 `context_refresh` claimed effect 内驱动(= 4′)** | worker 先 claim 既有 context_refresh;循环「DB 准备动作→事务外 provider IO→DB 幂等落地/归约」,walk stopped 后调用 `v13_refresh_context` 完成同一 effect | 不增加活跃 effect,天然位于 freeze 前;复用 advance ② 和 single-active 约束;判断 IO 在 sessions 行锁外 | context_refresh 租约更长;工人协议变了:只调 refresh 不先 walk 的工人得到**无记忆段的合法 manifest**(不是坏 manifest);必须严格拆开 DB 事务与 worker 外部 IO |
| ~~walk 写在 `v13_refresh_context` 体内~~ | settle 事务内直接调 run_round | — | **否决**:会话行锁+策略锁跨 HTTP,违反「外部 IO 不进数据库事务」;与 DP1 锁窗冲突。若 Oracle 坚持,先改不变量文本再修订本计划 |

**Oracle 裁决:A4(= 4′)。** 两 lane 收敛于此。依据:同时复用现有 effect 入口、满足 manifest freeze、避免 A1 把判断延迟带进 parse。前提是严格拆开「数据库准备/落地事务」和「worker 外部 IO」;不得把现有 `v13_mgraph_run_round` 原样嵌进 `v13_refresh_context`。

##### OQ-A-Freeze 子裁决

| 选项 | 语义 |
|---|---|
| **AF1 freshness-first** | matching query/generation/policy 的 walk 必须 stopped,才装配并完成 context_refresh;超帽/超时也必须先形成带 stop_reason 的 stopped walk |
| **AF2 stale-one-turn** | 当前 refresh 可在没有 stopped walk 时完成且不含 `memory_graph`;walk 后台完成后,revision 改变再触发第二次 refresh |
| **AF3 artifact 后补丁** | walk 迟到后修改已落 artifact 或 sessions 指针下的 manifest。**禁止**,违反 artifact append-only 和 freeze |

**Oracle 裁决:AF1。** AF1 约束的是**注入谓词**和**参考工人**:`v13_refresh_context` 在 walk 未停、skip、异常、步数帽时仍然完成,段缺席即降级,回合不因此 failed。AF2 仅在实测表明 AF1 端到端延迟不可接受时选用,且必须同选宽 digest(附录 A.3),不得只用 generation。

#### OQ-B memory_graph 段形态与 `sec_full` 经济学可见性

**事实基线**

- section 固定九键;`payload_ref.kind` 只允许 `goal|blob`,但 payload_ref 对象没有统一额外键墙;render 对 blob 从 `artifacts(kind='context_section')` 取不可变正文。(periphery `:417-480`、`:1734-1815`)
- `sec_src` 是实际装配段源(五分支),`sec_full` 目前只含 goal/history/tools(三分支);`press`、ER 和 compact hint 从 `fcls/ford` 的全量基面派生,未进入 `sec_full` 的内容不计入 `t_used/bp/e_base`。(periphery `:806-872`、`:1000-1160`)
- 未列名的 kind 在 `bkind` CASE 中落 retrieval 桶,受 `retrieval_cap` 装箱。(periphery `:876-878`、`:1181-1184`)
- **wire 并不看 `transform.applied`**:`v13_render_wire` 按 sections 数组逐段取 body;只标 `reason=budget` 仍会把正文送进模型。(periphery `:434-480`)

**载体轴**

| 选项 | 收益 | 代价 |
|---|---|---|
| **B-T1 blob 化** | memory material 经 `v13_blob_land(...,'context_section')` 冻结;render 和 exact replay 不依赖 memory_nodes 生存期;payload_ref 词表不扩 | refresh 增加一个 material 重算、hash belt 和 blob 落地步骤 |
| B-T2 新 `payload_ref.kind='memory_graph'` | 不复制 body 到 artifact blob | exact replay 会依赖可重建/可删除的 graph 表;需改 render 第三臂、校验器、ACL;一个 section 又含多个 node,引用形态不自然 |
| B-T3 manifest inline material | 无额外 blob 查询 | 破坏现有 section 指针式 IR;manifest 与 payload 重复放大;refresh belt 无法复用 blob 先例 |

**经济学轴**

| 选项 | 收益 | 代价 |
|---|---|---|
| **B-E1 同时进入 `sec_src` 与 `sec_full`** | memory bytes 进入 pressure、ER、retrieval cap;新证据造成的缓存 churn 可见 | 可能更早升 tier;「注入记忆→压力升→更积极砍 history」的反馈环;「决策基面值恒=v2」注释不再成立 |
| **B-E2 只进 `sec_src`** | 与 summary/compaction 的「派生段不计全量基面」先例同姿;压力与「有没有记忆段」脱钩 | 真实发送给模型的 memory bytes 对 `t_used/bp/e_base` 不可见,经济账低估 |
| B-E3 只把估算计入 `sec_full`、正文另走 `sec_src` | 可调节压力 | 双公式/双来源风险;必须证明估算与 section 字节恒等,否则违背 est 单源纪律 |

**子题**:段个数=每 manifest 一段(`section_id=kind='memory_graph'`);桶=显式 retrieval(与 CASE ELSE 同义,写出来);优先级=LastResort(core/history 先装箱,设计 §6.2 触点 5);预算裁掉之后=从 `sections[]` 去掉(`final_sec` 聚合时过滤,不留在数组里标 skipped——否则 wire 仍注入)。

**Oracle 裁决:B-T1 + B-E2 + 单段 + LastResort + 未 applied 则滤掉。** 决定性理由:`sec_full` 是「要不要压缩 history」的决策基面,summary/compaction 是该决策的产出所以不进基面;memory 是可选召回,放进 `sec_full` 会让「多了一段记忆」同时改掉 history 的 transform,回答差异无法归因;applied 的 memory 已被 `retrieval_cap` 封顶,未 applied 的段不进 wire。est 只能复用 `((bytes + divisor - 1) / divisor)`,不得另建「memory token estimator」。

#### OQ-C 第 12 个 token 键、`pending_walk` 与零时钟

**事实基线**

- `v13_context_required` 是十一键(已实测核实:sem/dec/goal/tools_rev/asm_ver/jdef_ver/gen_ver/corpus/recall_ver/econ_ver/ident_ver);freshness 只比较整个 required JSON 与 `sessions.context_active_revision`。进入 manifest 输入的版本或状态若不进 token,就会静默复用旧 artifact。(periphery `:191-239`、manifest `:205-208`)
- **追动键纪律**(DP7 计划 :28):「进 manifest 输入的策略版本必须在 token 有键,漏键=静默用旧 manifest;键集增删=全域恰一次 refresh」。
- evidence 的身份由当前 query hash、mgraph generation、活动 policy version 和 stopped walk 共同决定;generation 不会在单纯 walk 从 open→stopped 时变化。(mgraph `:1376-1413`、`:2508-2555`)
- DP7 确定性纪律:装配派生不使用时钟或随机,同一数据库状态下两次调用字节相等。(DP7 §1.5 #7)

| 选项 | 形态 | 适用条件 | 风险 |
|---|---|---|---|
| **C1 `mgraph_gen: bigint`** | 仅记录 `v13_mgraph_progress().generation` | 只在 A4+AF1 下安全 | open→stopped 不改 generation;AF2 下 completion 不追动 refresh |
| **C2 `mgraph_ver: 64hex` digest(窄)** | 哈希 `{generation, policy_version}` | 兼容 AF1 与 AF2 | 读取面比单 bigint 稍重;必须 STABLE、零 body 聚合 |
| **C2′ `mgraph_ver: 64hex` digest(宽,草案一)** | 再加 query_hash、read_enabled、transcript freshness、matching walk status/stop_reason/frontier_digest | 主要服务 AF2 | frontier 在 walk 提交时变化;若进 token 而 walk 发生在 revision 写回之后,会立刻 `context_fresh=false` 自激下一轮 refresh |
| C3 pending 时间戳/随机 nonce | 写 `pending_at` 或随机 ID | 无 | 破坏零时钟/确定性;禁止 |
| C4 不加键,依赖现有 `dec` | 让 mem decisions 数量间接触发 refresh | 无 | 缓存全命中或仅状态变化时不可靠;禁止 |

**Oracle 裁决:C2(窄 digest),键名固定 `mgraph_ver`。** 它是第 12 个且唯一新增键。材料钉死为 `jsonb_build_object('generation', gen, 'policy_version', ver)` 后 `digest(…::text)`。`read_enabled`/`inject_top_k` 的翻版就是新的 `(name,version)` 行,已被 `policy_version` 罩住。不把 query_hash 放进键:查询串来自最新 `user/message`,该事件已经推动 `sem`。query 与 walk 身份的错位用「材料按当前串查找、没有 stopped walk 就不注入」处理。**禁止把 frontier 哈希放进 token**(自激论证见 C2′)。

`pending_walk` 不新增表、不写 manifest 时间字段:pending 状态由现有确定性 `memory_walks` 行和 context_refresh effect 表达;material 只消费 stopped walk。若 Oracle 仍要队列表,列只许 `(session_id, query_hash, generation, policy_version, status)`,无时间列(附录 A.1)。

#### OQ-D provenance 实现与同文折叠呈报

**事实基线**

- `transcript_chunks` 五列无 kind;user/llm 区分唯一通道 = `content_hash → transcript_chunks(session_id,seq_from) → events.type` 两跳。(memory `:18-29`、core events DDL)
- build 已经做该 join 但只复制 `events.at`;`memory_nodes` 以 `(session_id,content_hash)` 为主键,同正文的多次 user/llm 出现折叠到一个节点(OQ4/D14)。(mgraph `:940-975`、`:21-52`)
- trial 实证模型幻觉复述以与用户事实相同的召回权重进入 evidence——speaker provenance 对消费方有实际价值。(trial §4 Q2 0.824)

| 选项 | 收益 | 代价 |
|---|---|---|
| **D1 evidence/section 读取时 join** | 零存储迁移;能看见同 hash 的所有 user/llm 来源;旧节点立即可用 | material 生成多一次聚合;必须明确同文折叠口径 |
| D2 `memory_nodes` 加 provenance 列 | 读快、行自包含 | 节点不可变;需 builder_version 升版和全量重建;同正文后续出现新 speaker 时旧行无法更新;「混合类型如何压成一列」需第二次裁决 |
| D3 `transcript_chunks` 加 kind 列 | 投影层直接具备 speaker | 修改 DP6 五列冻结形状、投影版本和测试;memory_nodes 折叠问题仍存在 |
| D4 只标 `origin=episodic|consolidation` | 最小改动 | 无法区分 user/llm,不能解决原始动机 |

**Oracle 裁决:D1。** 附加约束:provenance **不把 `seqs` 全量放进 material**——B-T1 的 blob 会被 `v13_render_section_body` 整段送进 wire;闭集七键见下。provenance 使用有界摘要,不把所有 event 行无限嵌入 manifest:

```text
provenance = {            -- 闭集七键,每次都在
  origin:        episodic | consolidation | null,
  speaker:       user | llm | mixed | consolidation | unknown,
  conflict:      boolean,        -- 仅在 speaker 类多于一种(含意外 type)时为 true
  seq_count:     int >= 0,
  seq_first:     bigint | null,  -- seq_count=0 时为 JSON null
  seq_last:      bigint | null,
  source_hashes: 64hex 数组,字典序、去重;节点不存在则为 []
}
```

呈报口径(两 lane 收敛,Oracle 确认):

1. episodic 节点沿自身 `source_hashes` 查 transcript/events;consolidation 节点 `speaker=consolidation`、`seq_count=0`、`conflict=false`,**不把亲本 user/llm 合成一个说话人**(第二层解释)。
2. 只有 user 来源为 `user`;只有 llm 为 `llm`;两者都有为 `mixed` 且 `conflict=true`。
3. 同文本被 user 和 llm 都说出时,**不得挑一个赢家**,也不得称为密码学 hash collision;口径为「content-address coalescing 导致 speaker 不可分辨」,manifest 明示 `mixed`。
4. 意外的 `events.type`(开放词表第三种):`speaker=unknown`、`conflict=true`,不 RAISE——装配不能因为一条旁路事件型失败。
5. episodic 却没有投影行:`speaker=unknown`、`conflict=false`、`seq_count=0`(段仍可带正文,说话人不明)。
6. `seq_count=0` 时 first/last 为 JSON null;`seq_count=2` 时 first/last 就是那两个 seq 且 first < last。无节点:`origin=null, speaker=unknown, conflict=false, seq_count=0, source_hashes=[]`(只给直接调用/belt,不制造第三种段)。
7. **不把无界 seq 数组塞进 prompt/material**——这是七键闭集替换全量 seqs 的原因:blob 会被 render 整段送进 wire。evidence 的顶层仍只有 `rows/skipped/asks`,provenance 只出现在段材料里。

#### OQ-E 锚池方向不对称是否同批修复

**事实基线**

- v2 重跑:T6→T2 被发现,但 canonical T2→T6 不在 top-5;contradicts 只在 canonical 方向入封,该 pair 没有 contradicts edge,而固化面仍能识别 contradiction=1.0。(rerun §3.1/§9)
- 同重跑 32 条 jev、23 条 proximity 边,但四个查询全部 depth=1、edges_used=0——装配前尚无证据证明扩大 pair pool 会改善最终上下文。(rerun §4)
- v2 计划 §8 把该缺口显式挂号给「下一张计划(装配接线或 CJK 路由 supersede)同批裁决」。(v2 §8)

| 选项 | 收益 | 成本 |
|---|---|---|
| E1 双向候选并集后 canonical pair 去重 | 任一方向 top-k 命中即可产生一次 canonical contradiction ask | 候选与 ask 增长;需重算写帽和活体成本 |
| E2 session 共享候选池/持久审计池 | 可审计所有已发现 pair | 新真相表和清理策略;超出当前定向接线 |
| E3 提高 `candidate_top_k` | 实现最小 | 无法保证对称;ask 成本线性增加,v2 已为成本把默认从 10 降到 5 |
| **E4 本计划只裁不做** | 保持接线范围纯粹;先观察 memory_graph 实际回答增益 | 已知目标 pair 的 contradicts edge 仍可能缺失 |

**Oracle 裁决:E4。** 两 lane 收敛。在 W3 的 end-to-end gate(J8)中固定记录**不导致失败**的观测(edges_used/depth/段是否出现 + 同一查询有边/无边两份夹具的段 `content_hash` 对比);只有该观测证明遗漏 edge 改变 section 证据时,才启用条件 W4。若将来supersede 要求同批实施,只许附录 A.5 的两种窄变体,禁止直接用 E3 代替设计;开工前先用当前会话节点集跑一次对称性计数写进 README。

#### OQ-F 交付边界

| 选项 | 包含 | 不包含 |
|---|---|---|
| **F1 最小生产接线** | 换体五函数、provenance、token、manifest v4、freeze/driver、F7 重写、README/gate | transcript tick 自动化、walk cleanup、CJK routing、tracked demo |
| F2 连带运维自动化 | F1 + transcript/build sweep 与 walk retention | CJK routing、demo |
| F3 demo 升格 | F1/F2 + 将 gitignored demo 适配器转成正式生产 driver | 范围和依赖显著扩大 |

**Oracle 裁决:F1。** 两 lane 收敛。transcript 投影调度和 walk retention 已分别有独立运维台账;装配接线只需在 degraded 或没有 stopped evidence 时可靠降级,不应把调度器升级混进 schema/manifest 升版。demo 树 gitignored,不准进里程碑提交。**附加:因落点裁 Stage 16,「改写 mgraph F7」取消——mgraph 的 `test_mgraph.py` 与 `v13_mgraph.sql` 字节不动;隔离断言改由新 stage 的 J7 再钉一次。**

### 1.5 Oracle 裁决记录(实施前必填)

| 项 | Oracle 选择 | 必须写入的附加参数 |
|---|---|---|
| 落点 | **Stage 16** | 目录 `v13/mgraph_assembly/`;库 `agent_v13_mgraph_assembly`;`STAGE_THROUGH["mgraph_assembly"]=16`;SQL 文件 `v13_mgraph_assembly.sql` 只含一个 BEGIN/COMMIT |
| OQ-A | **A4** | route `v13_claim` → resolve 上 `v13_mgraph_run_round` 每步一事务 → route `v13_refresh_context`。不新 effect kind,不改 advance.sql |
| Freeze | **AF1** | **注入**:仅当 `v13_mgraph_section_status='emit'`(匹配的 walk 已 `stopped`,且 evidence 行非空)才有段。`stop_reason` 不参与过滤,spend/latency/depth/evidence 的已停 frontier 都可以注入。**完成**:skip、异常、步数帽、walk 仍为 open,都照常 settle,段缺席,回合不因此 `failed` |
| OQ-B transport | **B-T1** | `payload_ref.kind='blob'`,`v13_blob_land(effect, mat)` 两参(第三参默认 context_section)。render 两臂不改 |
| OQ-B economics | **B-E2** | 只进 `sec_src`。`sec_full` 不加 UNION。未 applied 的 `memory_graph` 从 `sections[]` 去掉 |
| OQ-C | **C2 窄** | 键名 `mgraph_ver`。材料只有 `generation` 与活动 `mgraph.version`。无 meta 行时 generation=0。无活动 mgraph 策略行才 V3009 |
| OQ-D | **D1** | 闭集七键:`origin,speaker,conflict,seq_count,seq_first,seq_last,source_hashes`。口径按 §1.4 的 speaker 规则 |
| OQ-E | **E4** | 三次提交不含 W4。触发仍是附录 A.5,且先要有 J8 的非门禁观测 |
| OQ-F | **F1** | 新 stage 的 SQL/测试/README + `load.py` 两处 + `v13/mgraph/README.md` 一行指针。不含 tick、walk GC、demo |

若将来 supersede 偏离本次裁决,§3 中标注「裁决分支」的机械增量必须按各 OQ 的替代表(附录 A)更新;不得只改结论而保留不匹配的 gate。裁决已写入 §1.5,W1 可开工。

### 1.6 不变量核对

#### DP9 §1.4 十五条

| DP9 不变量 | 是否触碰 | 守法方式 |
|---|---|---|
| 1. Jev 只产版本化 evidence;动作只读策略 | 触碰消费面 | section 冻结 mgraph policy version、walk identity 和精确 judgment refs;装配是否采用仍由 SQL budget/priority 决定 |
| 2. epoch/freeze | **触碰** | 只消费 stopped walk 在 freeze 前已完成的 decisions;迟到结果只能触发新 revision/new artifact,绝不修改旧 artifact |
| 3. mgraph 函数不锁 sessions、不 append event、不直接 typesafe | 条件触碰 | 新函数全部 STABLE 纯读;session 锁和 degraded audit 只在 `v13_refresh_context`;A4 的 provider IO 在 worker,DB plan/apply 函数零网络 |
| 4. 合并生成只用 mgraph_consolidate | 不触碰 | memory_graph section 只读既有节点,绝不生成节点 |
| 5. graph 外部键为 content_hash、重建可恢复 | 触碰读取 | section 只携 content_hash 和 frozen blob;不把 node PK 写成 artifact FK |
| 6. consolidation 节点/边不被 episodic rebuild 删除 | 不触碰 | provenance 递归只读 `source_hashes` |
| 7. 一 envelope 一 state、batch questions 准确 | 条件触碰 | A4 必须复用现有 mgraph envelope;不得合并不同 action 的 state |
| 8. 哈希材料无 now/lease/水位随机量 | **触碰** | `mgraph_ver` 只含 generation/policy version 的确定值(裁决:窄 digest);effect attempt/fence 不入 revision |
| 9. 节点/边不 bump cgr | 不触碰 | 无模板新增;装配不写 graph |
| 10. needed_judgments 不含 mem_ | 保持 | F7 与 J7 双重断言 |
| 11. 生产 SQL 无 mock/pg_net/dblink 等 | 保持 | 源码扫描;FakeLLM 仅测试侧 |
| 12. mgraph 数值只从策略行读 | 触碰读取 | inject_top_k、read_enabled 等仍经 `v13_mgraph_policy()`;装配不复制数值阈 |
| 13. walk 与回合共用 judge spend | 条件触碰 | A4 继续走同一 judgment_calls/spend;不设 assembly 专用账 |
| 14. mem decisions 造成 dec-refresh 是已知代价 | 触碰并收束 | A4 在同一 claimed refresh 内完成 walk,最终 token 记录完成后的 `dec`;不得依赖 `dec` 替代 mgraph revision |
| 15. mem_route signal 含 generation | 不触碰 | 不改 signal 形状 |

#### DP7 §1.5 十三条

| DP7 不变量 | 是否触碰 | 守法方式 |
|---|---|---|
| 1. 外部 IO 不进数据库事务 | **触碰** | A4 worker 在 plan 事务提交后调用 provider,再以 apply 事务落地;refresh settle 内零网络 |
| 2. single-active effect | 触碰生命周期 | A4 复用现有 context_refresh,不 enqueue 嵌套 effect |
| 3. 语义事件窗零污染 | 触碰 audit | 仅可追加 `audit/memory_degraded`;不得追加 user/llm/tool/turn/end;审计型不进策展词表 |
| 4. summary fail-closed | 不触碰 | summary CTE、belt 与策略逐字继承 |
| 5. tier 语义 | 可能触碰输入 | 若选 B-E1,memory bytes 进入压力,但 tier 算法、bands、hysteresis 不改 |
| 6. manifest 只经 settle 落行 | **触碰** | memory material 只在 refresh complete CAS 接受后 blob/artifact land |
| 7. 装配确定性、零时钟/随机 | **触碰** | revision/material 全 STABLE;排序均有 content_hash/seq 终裁;禁止 pending timestamp |
| 8. token/锁序 | **触碰** | 新增一个 revision 键;refresh 锁集加 mgraph policy 和 mgraph advisory,顺序固定 |
| 9. 哈希/公式同源 | **触碰** | query hash、revision、material、est 各有单源 helper;est 复用现有整数公式 |
| 10. 文档顺序=加载顺序、换体机械复制 | **触碰** | 换体尾追加(或 Stage 16);复制源为加载态最新活体,不是 manifest 文件里的七键旧体 |
| 11. 种子纪律 | 触碰 | 不 UPDATE value;测试翻版用既有仪式 |
| 12. 双登录和最小 ACL | **触碰** | route/resolve/recall 只得必要读/执行;外呼 worker 继续 route 主连接+resolve 副连接 |
| 13. 新 SQL 机械自检 | 触碰 | 参数使用、列存在、函数定义唯一、V3009、顶层语句和 `$...$` 配平全部进 J/K gate |

### 1.7 接口契约

以下「after」以**裁决路径**(Stage 16、A4/AF1、B-T1+B-E2、C2 窄、D1 七键、E4、F1)为准;将来 supersede 改选时按 §1.4/附录 A 替换。

| 接口 | Before | After / 新接口 | 调用方 |
|---|---|---|---|
| `v13_context_required(uuid) -> jsonb` | 十一键 | 同签名,十二键;新增 `mgraph_ver: 64hex` | `v13_context_fresh`、assemble `tok` CTE、refresh 指针写回 |
| `v13_prefix_identity(uuid) -> text` | 材料中 `manifest_version=3` | 同签名,字面升为 4 | assemble、fork/validate-spawn、render identity |
| `v13_assemble_manifest(uuid,int default null) -> jsonb` | manifest v3;五 kind | 同签名,manifest v4;新增一个 `memory_graph` section | refresh、shadow、route/resolve/recall 直调 |
| `v13_manifest_validate(jsonb) -> void` | validator v4,要求 manifest_version=3 | validator v5,要求 v4;required revision 12 键;kind 与 transform 词表各 +1 | refresh |
| `v13_refresh_context(uuid,int,bigint) -> text` | 锁→assemble→validate→complete→现有 blobs→artifact→pointer | 同签名;加入 mgraph freeze lock、memory blob belt、degraded audit | context_refresh worker |
| `v13_render_section_body(uuid,jsonb)` | goal/blob 两臂 | 裁决 B-T1 下签名和两臂**不变** | render/receipt |
| `v13_mgraph_evidence(uuid,text) -> jsonb` | `{rows,skipped,asks}` | **保持签名和返回形状不变**;追加 `GRANT EXECUTE` 给 `v13_route`(今天只授 recall/resolve,实测 mgraph `:2584-2593`) | assemble(route INVOKER)、既有外部消费者 |
| `v13_mgraph_asm_ver(uuid) -> text` | 无 | 新 STABLE 64hex(`sha256({generation,policy_version})`);无活动 mgraph 行 V3009 | context_required |
| `v13_mgraph_turn_query(uuid) -> text` | 无 | 新 STABLE;最新 `events` 中 `type='user/message'` 的 `btrim(payload->>'text')`,无行则 `''`;走 `ix_events_last_user` | worker 循环、material |
| `v13_mgraph_provenance(uuid,text) -> jsonb` | 无 | 新 STABLE;输入 node hash,返回闭集 provenance(§1.4 OQ-D 形状) | section material |
| `v13_mgraph_section_plan(uuid) -> jsonb` | 无 | 新 STABLE;**单一分支表**,返回 `{status, material}`;material 仅在 status='emit' 时为对象,否则 JSON null。status/material 两函数只是它的包装(JSON null 映射成 SQL NULL) | assemble、refresh belt、审计 |
| `v13_mgraph_section_material(uuid) -> jsonb\|null` | 无 | section_plan 包装;只为当前 query/current gen/current policy 的 stopped walk 产 material;无可注入行返回 SQL NULL | assemble `sec_src`、refresh belt |
| `v13_mgraph_section_status(uuid) -> text` | 无 | section_plan 包装;闭集 `emit\|disabled\|degraded\|empty_query\|no_walk\|no_rows`;与 material 同快照(`emit` ⇔ 非 NULL) | assemble 过滤、refresh degraded 审计 |
| `v13_mgraph_run_round(uuid,text,int)` | 一次一步,内部 resolve | 签名和行为不变;A4 时由 worker 在 refresh 调用前循环步进 | worker(resolve 连接)、手动驱动、旧 demo、测试 |
| `v13_recall_candidates(uuid)` | 文档候选 CAND4 | 不变 | assemble query_side |
| `v13_needed_judgments(uuid)` | 回合判断族 | 不变,不含 mem_ | parse/resolve |

新增 material schema(裁决形状):

```text
memory_graph material = {
  query_hash: 64hex,
  generation: bigint,
  policy_version: int,
  rows: [
    { content_hash, score, body, provenance }
  ]
}
```

约束:

- `rows` 按 `score DESC, content_hash ASC`,数量不超过活动策略 `inject_top_k`(evidence 既有截断)。
- material 只在 `rows` 非空且 walk stopped 时非 NULL(`status='emit'`)。
- `memory_graph` section 仍使用九键标准 section,不增第十键;provenance 位于 payload material 内。
- top-level manifest 键集仍为 12 键;升版原因是 section vocabulary、required revision 和 policy schema 变化,不是新增顶层字段。
- `judgment_refs` 为可选审计字段,保留在 material 外由 walk 行自带,不进 manifest——避免把 decisions 表内容搬进 artifact。

`required_revision` 字典序串(J1 断言用这串):

```
asm_ver,corpus,dec,econ_ver,gen_ver,goal,ident_ver,jdef_ver,mgraph_ver,recall_ver,sem,tools_rev
```

validate 外层 12 键串保持不变;section 9 键串保持不变。

ACL(新段末尾,REVOKE PUBLIC 后。**授权按调用角色实测**:`v13_refresh_context` 是 DEFINER,内部调用以属主身份跑,会掩盖缺 GRANT;J8/J9 用 `SET ROLE` 实测正路径,超级用户路径不算通过。重复 GRANT 保持,不先探测「是不是已经有」):

| 对象 | 授予 |
|---|---|
| `v13_mgraph_asm_ver`、`turn_query`、`provenance`、`section_plan`、`section_material`、`section_status`、`evidence` | EXECUTE → route, resolve, recall |
| `v13_mgraph_progress`、`v13_mgraph_policy()`、`v13_body_hash`、`v13_transcript_freshness` | EXECUTE → 同上三角色 |
| `memory_nodes` | SELECT → 同上三角色 |
| `v13_mgraph_evidence` | 补 `v13_route`(原 recall/resolve 保留) |
| `v13_mgraph_run_round` 及 `next_action` | 维持仅 resolve。J9 负向:route 的 EXECUTE 为假 |
| `v13_lock_key` | 不授予 route;只由 DEFINER refresh 以属主调用 |

`memory_walks` SELECT、`transcript_chunks` SELECT 已有 route;缺了仍由 SET ROLE 失败暴露,然后只补 GRANT,不改函数体。

### 1.8 六项张力(选项 / 代价 / 推荐)

**张力 1 — 同步游走 vs refresh 异步车。= OQ-A。** advance/parse 内同步重开 DP9 §8 否决且 advance 事务变长;walk 写 refresh 体内=会话行锁跨 HTTP;4′(claim 后、refresh 调用前、resolve 步进)工人协议变但零新 effect;tick 当回合不可观测;pending_walk 表要新真相表。**裁决:4′(A4)。**

**张力 2 — 段进不进 `sec_full`。= OQ-B 经济学子题。** 进入则 tier/ER/compact_hint 随可选召回涨,形成「注入记忆→压力升→砍 history」反馈;只进 `sec_src`+retrieval 桶则经济学结构性看不见这段但仍占 `retrieval_cap` 可被预算标掉。**裁决:不进(B-E2)。** J7 钉死:同一夹具,有停 walk 与无停 walk,`economics.pressure.t_used` 相同(裁决路径下)。

**张力 3 — `pending_walk` 与 DP7 不变量 7。** 装配 v4 的确定性是「同一快照两次调用字节相等」,不是「墙上时钟两时刻相等」。assemble 读 `enqueued_at` 或「最近一条 pending」会破不变量 7;**禁止**。不建 pending 表,walk 身份继续用 `md5(sid:qhash:gen:pver)`,装配输入只有已提交行。

**张力 4 — manifest freeze 与 walk 晚到。** 设计 §6.1:迟到结果不得回写已冻 manifest;机制源=artifacts 不可变+decisions.epoch 冻在 INSERT+context 行不可 UPDATE。settle 后补写、注入 open 半成品 frontier 均**禁止**;只注入 stopped walk 且 walk 在本次 assemble 之前提交。同一刷新内时序压住不变量 14:`dec` 在 walk 提交后才增加,4′ 把 walk 放在 assemble 前,同一次 settle 写下的 revision 已含 mem 行,不自激。

**张力 5 — 锚池对称是否同批。= OQ-E。** 双向并集再截 k 每锚 ask 上升;共享池改候选调用语义,D/G 夹具全要重看;只升 k 要新策略版本行。装配可观测性不依赖 contradicts 边(trial/rerun 都是词法命中)。**裁决:继续挂号(E4)。**

**张力 6 — 同文 user 与 llm 折叠后不可分辨。= OQ-D 呈报口径。** 节点 PK `(session_id, content_hash)`,同一正文两行 transcript 折叠成一节点。取 `source_at` 较早者当赢家=静默抹掉后说的一方;只标 `unknown`=连分得清的情况也丢掉。**裁决 `speaker ∈ {user,llm,mixed,consolidation,unknown}`+`conflict`(仅多于一种 speaker 类时为 true)+`seq_count/seq_first/seq_last` 有界摘要**;同说话人重复(conflict=false,seq_count>1)与双方同文(mixed)分开。trial 的幻觉样本是**不同**正文(哈希不同),两跳能标成 `llm`;真正不可分辨的是两边说出同一正文。

---

## 2. 现状机制(引用 Background,不重推)

- **加载**:`SQL_LOAD_ORDER` 16 文件,mgraph 第 15、mgraph_assembly 第 16,只许末尾追加(§1.2)。
- **token 闭环**:`v13_context_fresh` 比较 `v13_context_required` 与 `sessions.context_active_revision`(manifest `:205-208`)→ advance ② enqueue `context_refresh`(advance.sql `:313-316`)→ refresh 末尾写回两列指针(periphery `:2293-2296`)。`v13_ctx_ptr_guard` 要求 artifact `kind='context'`。
- **装配活体**在 periphery 一条 SQL 函数、46 CTE;本计划要动的只有 §3 列出的点,其余 CTE 复制后逐字保留。
- **读环**:`next_action` 纯读,动作含 skip/done/stop_spend/stop_latency/ask/bind/score/expand/close;`run_round` 每调用至多一封;evidence 在 disabled 与 degraded 时返回空 rows 且 `skipped` 为 `disabled|degraded`,`asks=0`——与 DP7 消费契约(degraded 时记忆不得当可靠召回,当前 turn 仍走 canonical)一致。
- **query 无生产来源**:`v13_recall_candidates` 用最新 **goal** 文本(recall `:173-242`),那是文档语料面。记忆查询锁定为最新 **user/message 的 `payload->>'text'`**,与 transcript 投影的正文键相同,这样 walk 的词法锚就是用户原句。查询函数仍读 events,避免历史压缩窗口把问题本身裁掉之后 walk 失去锚。实施期用一条夹具确认 canonical 消息里的文本与 events 该列相同(附录 B3)。

---

## 3. 数据模型与 SQL 草案(裁决路径)

本节是裁决路径的实施草案。附录 A 的分支成立时(仅当将来 supersede),以附录替换对应小节,不另发明形状。

### 3.1 新函数

全部放在 mgraph 文件新 `BEGIN` 段的前部,位于任何 OR REPLACE 之前。零动态 SQL、零 `==>`。

**`v13_mgraph_asm_ver(p_sid uuid) RETURNS text`**,STABLE:

- 读 `v13_mgraph_progress(p_sid)` 的 `generation`(无 meta 行时该函数已返回 0,mgraph `:480-500`)。
- 读活动 `mgraph.version`;空则 V3009。
- 返回 `encode(digest(jsonb_build_object('generation', gen, 'policy_version', ver)::text, 'sha256'), 'hex')`。
- 不读 `now()`,不读 walk,不聚合 body。

**`v13_mgraph_turn_query(p_sid uuid) RETURNS text`**,STABLE:

- `SELECT btrim(coalesce(payload->>'text','')) FROM events WHERE session_id=p_sid AND type='user/message' ORDER BY seq DESC LIMIT 1`。
- 无行 → `''`。不 RAISE。

**`v13_mgraph_provenance(p_sid uuid, p_hash text) RETURNS jsonb`**,STABLE(闭集七键,§1.4 OQ-D):

- `p_hash` 非 64hex → V3009。
- 无此节点 → `{"origin":null,"speaker":"unknown","conflict":false,"seq_count":0,"seq_first":null,"seq_last":null,"source_hashes":[]}`(belt,不是第三种段)。
- `origin=consolidation` → `speaker=consolidation`、`seq_count=0`、`conflict=false`;`source_hashes` 抄节点列(已是亲本哈希,不再展开亲本说话人)。
- 否则收集 `transcript_chunks` 中该 session+hash 的 `seq_from` 升序,再取对应 `events.type`:
  - 类型集 = `{user/message}` → `user`,`conflict=false`
  - = `{llm/message}` → `llm`,`conflict=false`
  - 两者都有 → `mixed`,`conflict=true`
  - 空集 → `unknown`,`conflict=false`,`seq_count=0`(episodic 却没有投影行:段仍可带正文,说话人不明)
  - 含其它 type → `unknown`,`conflict=true`
- `seq_count` = 出现次数(含重复正文的每一次);`seq_first`/`seq_last` = 最小/最大 seq,`seq_count=0` 时为 JSON null。
- episodic 的 `source_hashes` 抄节点列。

**`v13_mgraph_section_plan(p_sid uuid) RETURNS jsonb`**,STABLE——**单一分支表**,返回 `{status, material}`:`material` 仅在 `status='emit'` 时为对象,否则 JSON null。`v13_mgraph_section_status` 与 `v13_mgraph_section_material` 只是它的包装(JSON null 映射成 SQL NULL),禁止两套条件写岔。判定顺序锁死:

1. `turn_query` 为 `''` → `empty_query`
2. `NOT read_enabled` → `disabled`(先于 freshness,与 evidence 的判断顺序一致)
3. freshness.degraded → `degraded`(此时**不**读 walk,即使已有 stopped 行)
4. 不存在匹配 `(session, query_hash, current generation, active policy_version, status=stopped)` 的 walk → `no_walk`
5. evidence.rows 为空(含 frontier 被 join 丢光)→ `no_rows`
6. 否则 `emit`

`query_hash = v13_body_hash(turn_query)`,与 walk 身份使用同一哈希函数(next_action 里 `v_qhash := v13_body_hash(v_q)`;OQ8 规定 `query_hash=v13_body_hash(btrim(query))`)。`turn_query` 已经 btrim,禁止再包一层不一致的空白处理。

emit 时 body 的形状(jsonb 对象,§1.7):`{query_hash, generation, policy_version, rows:[{content_hash, score, body, provenance}]}`。`rows` 重新 `ORDER BY score DESC, content_hash ASC`,不依赖 jsonb 数组偶然顺序;`score`/`body`/`content_hash` 来自 evidence 行,不重算分。材料函数不调用 `run_round`,不写表。

### 3.2 段在 manifest 中的形状

仅当 material 非 NULL,`sec_src` 增加这一支(套 summary 那一臂的写法;列与现有支对齐:`section_id, kind, cache_scope, def_prio, content_hash, bytes, gseq, mat, pre_reason`):

```sql
FROM (SELECT v13_mgraph_section_material(p_sid) AS mat) sm
WHERE sm.mat IS NOT NULL
```

- `section_id` = `kind` = `'memory_graph'`
- `cache_scope` = `'Session'`
- `def_prio` = `'LastResort'`
- `content_hash` = `encode(digest(sm.mat::text,'sha256'),'hex')`
- `bytes` = `octet_length(sm.mat::text)`
- `gseq` = NULL,`pre_reason` = NULL
- `mat` = `sm.mat`

`payload_ref` 走既有非 goal 臂:`{kind:blob, content_hash:<与段 content_hash 相同>}`。该臂已经 `digest(mat::text)`,与段 content_hash 同式,validate 的跨字段校验(P0-4,blob 的 content_hash 必须等于段 content_hash,V3007)自然通过。

`final_sec` 的 transform 名 CASE 增加:`section_id='memory_graph'` 且 applied 时 `name='memory_inject'`。skipped 臂的 reason 词表不增(budget / priority_never / disabled / invalid_override 已够)。

`sections` 聚合增加过滤:丢掉 `section->>'kind'='memory_graph'` 且 `transform.applied` 不为 true 的元素。其它 kind 一个不丢。

est:不在材料函数里算。`cls.est_tokens` 使用既有整数式。J4 断言 `est_tokens * divisor >= bytes` 且 `(est_tokens - 1) * divisor < bytes`(bytes>0 时)。

多段化规则:该 kind 在一份 manifest 里至多一段,故 `section_id` 必须等于 `kind`。不产生 `memory_graph:8hex`。

### 3.3 assemble 复制体的增量清单(闭集)

相对 periphery `v13_assemble_manifest`,只允许这些编辑。实施者做完 diff,任何额外 hunk 都是偏差,先改回再提交。

1. 墓碑注释:v4 唯一存活于 ≤14 号库;本函数是 v5,`manifest_version` 4。
2. `fin` 内 `'manifest_version', 3` → `4`(periphery `:1389`)。
3. `sec_src` 按 §3.2 加一支(`:806-849` 五分支之后)。
4. `cls.bkind` 与 `fcls.bkind` 的 CASE 都加上 `WHEN 'memory_graph' THEN 'retrieval'`,放在 `history` 臂之后、`ELSE` 之前。`sec_full` 不加 UNION 支,故 `fcls` 的新臂是死代码,目的是两份 CASE 文本保持平行。
5. `final_sec` 的 `name` CASE 加上 memory_inject 臂。
6. 最外层 `jsonb_agg(section ...)` 的 FROM 加上 §3.2 的过滤。
7. 函数注释标 `[B2]` 于上述各点。`qside`、`jud`、`press`、`erc*`、`hint`、`summary_calc`、`mode`、`tok`、`ident` 零编辑。`tok` 继续调用 `v13_context_required`,十二键自动进入 `required_revision`。

### 3.4 validate 复制体的增量清单(闭集)

1. 墓碑:v4 断言 version 3,唯一存活于 ≤14 号库。
2. `(p_manifest->>'manifest_version')::int IS DISTINCT FROM 3` → `4`(periphery `:1475`)。外层 12 键串不改。
3. `required_revision` 的 string_agg 期望改为 §1.7 的十二键串;增加 `mgraph_ver` 非空且 `~ '^[0-9a-f]{64}$'`,写进同一处 V3003 形状检查。
4. kind 词表 `IN` 列表追加 `'memory_graph'`(仍是原来的 V3003 RAISE)。
5. applied transform 名 `IN` 列表追加 `'memory_inject'`(仍是原来的 V3003 RAISE)。
6. 新的交叉检查(新 IF,ERRCODE V3009):若 `kind='memory_graph'`,则 `cache_scope='Session'`、`payload_ref.kind='blob'`,且 applied 时 `name='memory_inject'`。priority 不锁死(overrides 合法)。
7. 不要求该 kind 必须出现。summary/consumed 的双向检查原样。

手造一份 version=3 的 jsonb 必须被拒(J2)。`v13_replay` 不走 validate(manifest `:915-921` 与 DP7 OQ7)。旧 artifact 的 exact replay 仍返回原字节。

### 3.5 context_required 与 prefix_identity

`v13_context_required`:在 `jsonb_build_object` 的 `ident_ver` 之后加 `'mgraph_ver', v13_mgraph_asm_ver(p_sid)`。十一键的表达式、缺行 RAISE、`gen_ver` 经由 `v13_generation_effective` 的写法逐字保留(periphery `:191-239`,复制源)。

`v13_prefix_identity`:只改 `manifest_version` 字面量 3→4(periphery `:164`)。九键名不变。缺 `render_policy` 仍 V3008。

### 3.6 refresh 复制体的增量清单(闭集)

1. 策略行锁的 `name IN (...)` 加入 `'mgraph'`。仍 `ORDER BY name`。注释写明八名,并指向 periphery README 偏差 #2「同缝扩展、不准删已有名」——`summary_accept` 必须留在名单里。
2. 形状守卫与 generation latch 之后、`v13_assemble_manifest` 之前:

```
PERFORM pg_advisory_xact_lock(public.v13_lock_key(v_sid, 'mgraph-build'));
```

   锁序:sessions → tools_meta → 策略活动行(八名,含 `summary_accept` 与 `mgraph`,`ORDER BY name`)→ pricing → `context_summary` 的 FOR SHARE → **然后** advisory。锁原理:`v13_mgraph_build` 持有的是会话级 `pg_advisory_lock`,`run_round` 与 refresh 用 `pg_advisory_xact_lock`,同一把 `v13_lock_key(sid,'mgraph-build')`,互相排斥;本计划不改 build 的锁。build 与 run_round 不拿 sessions 行锁;它们不会形成「先 advisory 再等 session、同时 refresh 持 session 再等 advisory」的环,前提是本计划不再给任何 `v13_mgraph_*` 加 `FOR UPDATE sessions`。J9 用源码扫描守这个前提。
3. summary belt 整段逐字保留(periphery `:2226-2290` 是模板)。其后、`v13_artifact_land` 之前,仿 summary belt 写 memory belt——**只做正向复核**(预算滤掉发生在 packing 之后,材料函数此时仍返回非 NULL;按「有材料却没段就 V3009」会在 kinds_disabled / retrieval 装不下时误报):
   - manifest 里有 `section_id='memory_graph'`:重算 `v13_mgraph_section_material`,`digest(mat::text)` 必须等于段 `content_hash`;`v13_blob_land(p_effect, mat)`(两参,第三参默认 `context_section`)的返回值必须等于该哈希;否则 V3009。
   - 没有该段:不 land,也不因为材料非 NULL 而 RAISE。no_walk、disabled、degraded、empty_query、no_rows、budget、priority_never、kinds_disabled 都走这里。
   - 「本该出现的段没出现」交给 J4:默认可装下的夹具里,段必须在且 `accepted`。
4. 指针 UPDATE 之后(同一事务即可):若 `v13_mgraph_section_status(v_sid)='degraded'`,`v13_append_event(..., 'audit/memory_degraded', {"basis":"degraded"})`。其它 status 不写事件。事件型不进策展词表。
5. `v13_complete` 的调用位置不挪。belt 仍在 complete 之后,因为 `blob_land` 要求 effect 已 succeeded。材料在 complete 之前的 assemble 里已经算进 manifest;belt 是落地复核,不是第二次决定段在不在。

advisory 持有区间是 assemble+land 的 CPU 时间,不含 HTTP。这段里 build 与新的 walk 会等。可接受,因为 settle 不再发问。

### 3.7 驱动(W3,无新 effect)

无包住整段循环的存储过程。理由:一个函数会把多封 HTTP 放进一个事务和一个 advisory 锁里,回到张力 1 要避开的形态。工人契约写进**新 stage README**,测试用脚本把契约跑一遍(J8)。

契约步骤:

```
route txn:  v13_claim           -- 不进 refresh
resolve:    loop
              q = v13_mgraph_turn_query(sid)     -- 每轮重读
              r = v13_mgraph_run_round(sid, q, elapsed_ms)
              COMMIT                             -- 一轮一事务
            until r.status ∈ {stopped,skipped}
               or r.action ∈ {done,skip}
route txn:  v13_refresh_context(effect, attempt, fence)
              -- 内序不变:锁 → advisory mgraph-build → assemble → validate
              -- → complete → memory belt → 指针 → shadow_observe
              -- → 仅 status=degraded 时 append audit
```

补充七条:

- `elapsed_ms` 由工人从循环起点累计。测试传 0。
- `read_enabled=false`、空 query、freshness degraded:`next_action` 已返回 skip。工人不循环,直接 settle。段不出现。
- walk 抛错或 `stop_spend`:**仍 settle**。失败的 `context_refresh` 会被 advance ② 收成 turn `terminal`——记忆故障不准连坐整回合。段缺席即降级。
- **步数帽(工人侧,不进 SQL 函数体)**:`max_steps = maximum_jev_calls * 6 + 8`。触及帽则停止循环并 settle;walk 若仍是 `open`,不改写成 stopped,段不出现。
- **续租**:循环每步在 route 连接上把本 effect 的租约续上(用 schema 里已有的 renew,与 `v13_claim` 同族;开工时核对签名,不新写 renew)。续租失败则结束循环并 settle。不把 HTTP 放进持有 `mgraph-build` 的事务。
- 工人与材料**只许**通过 `v13_mgraph_turn_query` 取查询串。禁止 effect.request 另带一份 query(今天 request 只有 `goal_hash`)。两处各算各的:walk 提交后、settle 前若新 `user/message` 落入,材料按新串找 walk,找不到则不注入(fail-closed)。不补追写已停的旧 walk。
- 循环终止条件同时看 `status` 与 `action`,因为 skip 路径的返回是 `status=skipped` 且不一定有 stopped 行。
- 第二次循环在 walk 已 stopped 时 `asks=0`(缓存 + `next_action` 的 done)。J8 断言 judgment_calls 零增量,且两次 assemble 的 memory 段 `content_hash` 相同。
- **J8 收尾断言**:settle 之后 `v13_context_fresh(sid)=true`,且 `required_revision.dec` 已包含本次 walk 写入的 `mem_%` 行(walk 在 assemble 前提交,不变量 14 的代价进同一次 revision,不自激)。

### 3.8 并发、丢弃、重复

| 事件 | 行为 |
|---|---|
| 同一 walk 重复 prepare | walk_id 确定性,第二轮 done,零 ask,段哈希不变 |
| walk 中途工人崩溃 | 已提交轮留下;重入 run_round 续跑(M3 幂等,rerun §7.3 已实测跨进程续跑)。未停则段不出现 |
| walk 与 build 并发 | 都要 `mgraph-build` advisory,串行。generation 若在 walk 开始后、停下来之前被 build 推进,walk 行记在旧 generation 上;材料按**当前** generation 查找,于是 `no_walk`,段不出现。下次 refresh 用新 generation 的新 walk_id 再走。不把旧 frontier 装进新代际 |
| settle 中 build 想跑 | refresh 已持有同一 advisory,build 等待到 settle 结束。段与 `mgraph_ver` 使用同一快照的 generation |
| 两份 refresh | single-active 索引不允许 |
| evidence 行的节点被 rebuild 删掉 | inner join 丢掉该行;若丢光则 `no_rows`,不注入。不留悬空哈希 |
| 乱序的 round | 既有 round PK,不改 |

### 3.9 错误与降级(用户可见)

| 条件 | manifest | 回合 | 恢复 |
|---|---|---|---|
| 默认 read off | 无 memory 段 | 与今日相同 | 翻 mgraph 策略版本 |
| degraded | 无段 + 一条 `audit/memory_degraded` + freshness 既有 NOTICE | 历史/工具段照常 | 投影追上,lag≤16(memory 纪律,max_lag_events=16) |
| spend over | 无段(walk 停在 spend 或根本没有 stopped 行) | refresh **成功** | 帽恢复后的下一回合再走 |
| walk 异常 | 工人吞掉并照样 settle;无段 | refresh 成功 | 下一回合重入 run_round |
| 段 belt 哈希不符 | refresh RAISE V3009,effect 可被工人 complete 为 failed | 有机会变成 terminal(advance ②) | 这是程序缺陷不是降级;gate 必须先红 |
| validate 拒 v3 | 手造旧形状失败 | 已落地的旧 artifact 仍可 `v13_replay` | 新 settle 产出 v4。stage 库 DROP-CREATE,不做在线迁移 |
| 空用户消息 | `empty_query`,无段,零 ask | 正常 | — |
| kinds_disabled 含 memory_graph,或 retrieval 预算不够 | 段被滤掉,无 blob | 正常,模型看不见记忆 | 翻 overrides 或加大预算 |

---

## 4. 逐文件影响与实施顺序

### 4.1 文件

| 文件 | 动作 | 依赖 |
|---|---|---|
| `v13/load.py` | 两处:`SQL_LOAD_ORDER` 末尾追加 `V13_ROOT / "mgraph_assembly" / "v13_mgraph_assembly.sql"`;`STAGE_THROUGH` 加 `"mgraph_assembly": 16`(已核:load.py 两处结构恰为此形) | 无 |
| `v13/mgraph_assembly/v13_mgraph_assembly.sql` | 新建:五个新函数(asm_ver/turn_query/provenance/section_plan + status/material 包装);OR REPLACE 五函数(context_required、prefix_identity、assemble、validate、refresh);GRANT/REVOKE。单 BEGIN/COMMIT,零 `ALTER TABLE`。段内先 CREATE 新函数,再 OR REPLACE 调用方 | 无前序文件改动 |
| `v13/mgraph_assembly/setup_db.py` | 从 `v13/mgraph/setup_db.py` 机械复制,只改 DB=`agent_v13_mgraph_assembly` 与 STAGE=`mgraph_assembly`,保留 stannum fail-closed 探针与 GRANTS/run_probes(已核:mgraph setup 的 DB/STAGE/probe/GRANTS/run_probes 五处) | 新 SQL 文件 |
| `v13/mgraph_assembly/test_mgraph_assembly.py` | 新建:J 组;F7 精神的隔离断言(recall∩graph=∅、needed 无 `mem_`、`econ_ver` 函数体、**前 15 个 SQL 文件字节冻结**)由本 stage 的 J7 承担 | 与对应 SQL 同一次提交 |
| `v13/mgraph_assembly/README.md` | 新建:机制一条;运维第一条「16 文件库里 `pg_get_functiondef` 才是装配活体,再改 periphery 只影响 ≤14 号库」;工人双连接契约(步数帽/续租);provenance 七键口径;dec 代价(read 打开后每回合);写帽纪律⑩仍有效且 walk 与回合共 spend;偏差台账 W 系条目;回退段 | 每个里程碑更新一次,与该里程碑同提交 |
| `v13/mgraph/README.md` | 只改「B2 下一张计划」那一行,指向 `v13/mgraph_assembly/` 与本计划。不改 SQL | 每个里程碑 |
| `v13/mgraph/v13_mgraph.sql`、`v13/mgraph/test_mgraph.py` | **字节不动**——F7 原文不改,OR REPLACE 闭集维持 `{v13_mgraph_envelope, v13_requeue_stale}` | — |
| 前 14 个 stage 文件(periphery/manifest/memory/economy/loop/recall/resolve/schema 等) | **不改** | 前缀冻结。periphery 源文件里的 version 3 / 十一键是 14 号库墓碑 |
| 教程三章 | **不改** | §7 只登记 |
| demo 树 | **不改、不提交** | OQ-F 裁决 |

两个 OR REPLACE 闭集(互不侵犯):

- `v13/mgraph/v13_mgraph.sql`:`{v13_mgraph_envelope, v13_requeue_stale}`(现状,F7 已钉)。
- `v13/mgraph_assembly/v13_mgraph_assembly.sql`:`CREATE OR REPLACE FUNCTION` 名集合恰为 `{v13_context_required, v13_prefix_identity, v13_assemble_manifest, v13_manifest_validate, v13_refresh_context}`,W1 起即此集,W2 不增加 OR REPLACE 名;该文件 `ALTER TABLE` 次数为 0;禁止 DROP FUNCTION 再重建这五个函数。

### 4.2 实施顺序

1. **开工门(已过)。** Oracle 裁决已写入 §1.5。若将来 supersede 改选:只应用附录 A 中被点名的那一节,并改 J 组里被附录点名的断言。
2. **实施期检索(W1 之前,结果写进 README 偏差,不靠猜测)。** 在仓库内检索 `'manifest_version', 3`、`IS DISTINCT FROM 3`、十一键串、以及 `test_mgraph.py` 里的 `assemble_manifest`/`context_required`/`OR REPLACE`。已知必改点是 periphery 活体(机械复制进新 stage 文件换体);**mgraph 两文件字节不动**。`test_periphery.py` 的十一键断言跑在 14 号前缀库上,**不准改**。若新 stage 测试自己钉了十一键或 version 3,归入 W1 的测试改动。
3. **W1,一次提交,原子。** 创建新 stage:`load.py` 两处 + `v13_mgraph_assembly.sql`(asm_ver + 五函数 OR REPLACE,但 assemble **还没有** `sec_src` 第六支、refresh **还没有** memory belt)+ `setup_db.py` 机械复制。增量只有:version 字面量、`mgraph_ver`、validate 词表与十二键、refresh 锁名单与 advisory、GRANT。测试 J1–J3。组内若翻了策略,结束时翻回 v2。
   - 可独立验证:16 文件库 `v13_assemble_manifest` 的 version 为 4、sections 仍无 `memory_graph`、`v13_context_required` 键集等于十二键串;periphery 前缀库(不加载新 stage)version 仍为 3;mgraph gate(A–H)仍绿且 mgraph 两文件字节不变。
4. **W2,一次提交,原子。** 就地编辑 W1 复制体(新 stage 文件内),加入 §3.2–§3.6 的段与 belt;新增 provenance/section_plan/turn_query。不要第二份 OR REPLACE。测试 J4–J7。夹具直接 INSERT `memory_nodes` 与 `memory_walks`(frontier 含 content_hash 与 score),walk_id 用 `v13_mgraph_walk_id`,避免为了测段去打完整判断。
5. **W3,一次提交。** 新 stage README 工人契约 + J8–J9(J8/J9 用 `SET ROLE` 实测,P0-6)。SQL 只有在 W2 漏了 GRANT 或 turn_query 时才补。J8 用既有 GUC mock、一步一封、连接用过即弃(README 偏差 #17/#19)。
6. **每个里程碑提交前。** `uv run python v13/mgraph_assembly/test_mgraph_assembly.py` 退出码 0(全组,不只 J);另跑 `uv run python v13/mgraph/test_mgraph.py` 退出码 0 且 mgraph 两文件字节不变。然后 15 个前序 stage 各自 `uv run python v13/<stage>/test_<name>.py`,库是它们自己的 `files_through`。任一红:修新 stage 段或停,**不准改前序测试来消红**。periphery/summary/twophase 在裁决路径下没有 kind/cap 变化,仍跑一遍当作「前缀文件未被误编辑」的证人。
7. **提交。** `git add` 按路径只含 §4.1 表中该里程碑触及的文件。禁止 `git add -A`。信息形如 `v13: add mgraph_assembly stage with manifest v4 identity` / `v13: inject memory_graph section from stopped walks` / `v13: walk memory graph before context refresh settle`。测试全绿 → README 已更新 → add → commit → push。失败即停。不 `--no-verify`,不 force-push。

W1 与 W2 不可以合成一个「复制到一半」的提交:W1 必须能加载并让 A–H 通过。W2 依赖 W1 的复制体已经在文件里。

---

## 5. 里程碑与 gate

命令:`uv run python v13/mgraph_assembly/test_mgraph_assembly.py`,库 `agent_v13_mgraph_assembly`,退出码 0;**每个里程碑另跑 `uv run python v13/mgraph/test_mgraph.py`(A–H)退出码 0,且 mgraph 两文件字节不变**。判断一律 Fake/GUC,不调真实 provider(AGENTS)。

**J1 十二键(W1,OQ-C 推荐)。** `jsonb_object_keys` 的 `string_agg(..., ORDER BY)` 等于 §1.7 那条十二键串。`mgraph_ver` 为 64hex。无 meta 行的新会话:generation 0 下两次调用相等。把 `v13_mgraph_meta.generation` 从 0 改为 1(或走一次真实 build 的代际推进,二选一,选不依赖 ask 的那个)后哈希改变。只翻 mgraph policy version、generation 不变,哈希也改变。活动行被删时 `v13_mgraph_asm_ver` 抛 V3009(测完回滚)。

**J2 version 4 与冻结回放(W1)。** 一次 settle 后的 manifest:`manifest_version=4`,外层键集串仍是 12 键且**不含**顶层 `memory_graph`,validate 通过。手造把 version 改成 3 的同样 jsonb:validate 失败。`v13_replay(artifact)` 的 `replay.mode=exact_replay`,且正文与落地 inline 除 replay 块外一致。同快照连调两次 `v13_assemble_manifest`,`::text` 相等。

**J3 身份字面量(W1)。** `pg_get_functiondef(v13_prefix_identity)` 含 `manifest_version` 与 `4`,不含把 manifest 钉在 3 的旧字面量。settle 后 artifact 里的 `prefix_identity` 等于当场 `v13_prefix_identity(sid)`。源码扫描:mgraph 文件中 `CREATE OR REPLACE FUNCTION v13_assemble_manifest` 出现次数 = 1(连同 envelope/requeue 的既有次数,总 OR REPLACE 名集合 = §4.1 的七名)。

**J4 段形状与 est(W2)。** `read_enabled` 翻开。种一个 episodic 节点 + 匹配的 stopped walk,frontier 一项。assemble 产出恰好一段 `kind=section_id=memory_graph`,`cache_scope=Session`,`priority=LastResort`,`payload_ref.kind=blob` 且哈希等于 `content_hash`,`transform={applied:true,name:memory_inject}`,est 满足 §3.2 不等式。refresh 返回 `accepted` 且 belt 正向复核通过(段在→blob land,哈希相等);refresh 后存在 `kind=context_section` 的 artifact,其 inline 哈希等于段哈希;`v13_render_section_body` 返回的文本含节点 body。`economics.pressure.t_used` 不含这段的 est(与无 walk 对照相等)。**「本该出现的段没出现」由 J4 承担**(belt 只正向复核,P0-3):默认可装下的夹具里段必须在。

**J5 provenance(W2)。** 四夹具,都不经判断 IO;**按字段断言,不按 jsonb 键序全文断言**:

- 仅 user 投影 → `speaker=user`,`conflict=false`,`seq_count=1`,`seq_first=seq_last=该 seq`。
- 仅 llm 投影 → `speaker=llm`。
- 同一 body 的 user 行与 llm 行(两行 transcript,一个节点)→ `speaker=mixed`,`conflict=true`,`seq_count=2` 且 `seq_first<seq_last`。
- `origin=consolidation`、`source_hashes` 两枚、无 transcript 行 → `speaker=consolidation`,`conflict=false`,`seq_count=0`,`seq_first=seq_last=null`。

evidence 的顶层键仍是 `rows/skipped/asks` 三键(无 provenance 键)。rows 顺序 `score DESC, content_hash ASC`。

**J6 缺席与过滤(W2)。** 下列情形 sections 里没有 `memory_graph`,且不产生 context_section blob(除已有 history/tools 外):无 walk;`read_enabled=false`(asks=0);freshness degraded(同时有一条 `audit/memory_degraded`,且无新的 `user/message`/`llm/message`;settle 返回后 `v13_context_fresh=true`,审计事件不自激);`kinds_disabled` 含 `memory_graph`;把 retrieval 比例压到这段 est 放不进(applied 会是 budget)——滤掉后数组中无该段,**settle 照常 `accepted`、belt 不 RAISE**(P0-3)。degraded 夹具要确认 history 段仍在(当前 turn 不靠记忆段)。

**J7 隔离保留(W2,含 F7 精神)。** `v13_recall_candidates` 的 content_hash 与 `memory_nodes` 交集为空。manifest `query_side.candidates` 同样不相交。`pg_get_functiondef(v13_needed_judgments)` 不含 `mem_`。`v13_econ_ver()` 的函数体仍只列出 `context_tiers` 与 `context_budget`。**前 15 个 SQL 文件相对本计划开工时字节不变**(mgraph 两文件在此列内——F7 原文不改;测试可读文件哈希,或 README 记录由提交仪式保证;不准为了哈希去改那些文件)。

**J8 驱动时序(W3)。** 翻开 read。投影一条 user 消息到 transcript,建好节点(可用一次 build 或直接种节点;若用 build,遵守一步一封)。工人循环按 §3.7 跑到 stopped,再 `v13_refresh_context`。段 `query_hash` 等于 `v13_body_hash(v13_mgraph_turn_query(sid))`。再跑一轮循环:`judgment_calls` 不增加,段哈希不变。另一连接在 `run_round` 期间 `v13_append_event` 成功且墙钟 <5s(E6 同款,证明 walk 不持会话行锁)。`judge_spend` 帽置 0 的策略版本:循环得到 spend/skip,随后 refresh 返回 `accepted`,无 memory 段,会话不进入 `failed`。
**收尾断言**:settle 之后 `v13_context_fresh(sid)=true`,且 `required_revision.dec` 已包含本次 walk 写入的 `mem_%` 行;再调一次 assemble,`mgraph_ver` 与 memory 段 `content_hash` 不变。
**非门禁观测**(OQ-E 触发条件核对,**不导致失败**):记录 `edges_used`、`depth`、memory 段是否出现;另用同一查询、一份有 contradicts 边的夹具和一份没有的夹具,记录两段 `content_hash` 是否相同——不相同才允许按附录 A.5 开 W4。

**J9 权限与锁(W3)。** **用 `SET ROLE` 实测正路径**(`v13_refresh_context` 是 DEFINER,内部调用以属主身份跑,会掩盖缺 GRANT;超级用户路径不算通过):`SET ROLE v13_route` 做 claim 与 refresh,`SET ROLE v13_resolve` 做 `run_round`,再分别以 route、resolve、recall 执行 `v13_assemble_manifest` / `v13_mgraph_section_material`。负向:`has_function_privilege` route **不可**执行 `run_round`;recall 不可执行 refresh。新函数 `prosecdef` 为假。新 stage 源码中五个新函数的定义里不出现 `FOR UPDATE`、`v13_append_event`、`typesafe_ask`。refresh 复制体含 `v13_lock_key` 与 `'mgraph-build'`,且该调用位于 `v13_assemble_manifest` 调用之前。

回归:A–H 在每个里程碑全绿。E2 的 CJK→superset 断言原样(OQ13=D,本计划不改 route)。H8 的五参信封断言原样(不碰 envelope 调用点)。

---

## 6. 风险与回退

**回退。** 删掉 mgraph 文件末尾 B2 事务,DROP-CREATE `agent_v13_mgraph`。前 14 个文件未改,它们的库不受影响。mgraph v2 策略键集未改,不存在 v2 那种「旧读取器读新 JSON」问题。已写入的 context artifact 在回退后:validate v4 会拒 `manifest_version=4` 与十二键 `required_revision`。stage 库不迁移。若有人把回退后的 validate v4 指向这些行,表现是 V3003,不是静默装错段。`v13_replay` 仍能读出旧字节。

**不要只翻 active 策略来回退。** 装配行为在函数体里,不在 mgraph 策略 JSON 里。

**错文件编辑。** 加载序上的活体在本计划落地后是 **16 号文件里的复制体**。以后改装配必须改这份复制体。再改 periphery 里的 v4 只会影响 ≤14 号库,16 号库看不见。J3 的「新文件内 OR REPLACE 恰一份」与前缀库抽查就是为了这个。README 运维第一条写明。

**复制漂移。** assemble/validate/refresh 各有千行级。实施纪律:从 periphery 整函数复制,再按 §3.3/§3.4/§3.6 的闭集改。diff 里出现闭集以外的 hunk 就停。不要凭记忆重排 CTE。

**身份升版与 fork。** `prefix_identity` 含 `manifest_version`,3→4 后子会话现算身份不等于父 artifact 上冻结的旧哈希,`v13_fork` 的 validate-spawn 会拒 exact_replay/recompute。stage 库无旧 artifact。demo 库若还指着 v3 artifact,需要在新代码下重新 settle 再 fork。不写迁移函数。

**spend。** read 打开后,每个 `context_refresh` 前多一次 walk。CJK 查询今天走 superset,rerun 里四次查询都是 depth=1、边未被遍历,但仍有 1–6 批评断。这些批进 `v13_judge_spend`,和用户回合共用 512。trial 里已经出现 `budget_exhausted` 把回合打到 human。打开 read 之前按会话帽评估;本计划不改帽的默认值。

**dec 放大。** 同一次 walk 的 `mem_` 行会增加 `dec`。A4 时序下它们进入同一次 revision,不额外再刷。若工人把 walk 放在 refresh **之后**,每个回合会再 enqueue 一次 refresh。J8 的顺序断言就是守这个。README 把「默认双 false 才为零」改成「read 关闭才为零」。

**advisory 范围变宽。** refresh 在无 HTTP 的窗口里持有 `mgraph-build`。build 的 tick 会多等一次装配。不持有会话行锁以外的新层级。

**段体积分。** `inject_top_k` 既有默认下,多行 body 进 retrieval 桶。超帽则整段消失(过滤),不会半段进入 wire。不在本计划加第二道字节帽;节点 body 的 4096 预检仍是 build 的 V3005(README 纪律⑨)。

**jsonb 文本稳定性。** 段哈希使用 `digest(mat::text)`,与 goal/history 相同。不要对材料做 `jsonb_pretty` 或手拼字符串。score 从 evidence 原样放入,不重新 `::numeric` 再格式化。

**F7 被放宽的风险。** 改 OR REPLACE 闭集时,若有人顺手删掉「交集为空」或「needed 无 mem_」,CAND4 隔离就没了。J7 把这两条再断言一次,审查时两处都要在。

**A–H 被十二键误伤。** mgraph 测试跑在 15 文件前缀库上,不受影响(F7 原文不改)。新 stage 自己的测试若曾驱动 advance 直到 context 新鲜,W1 后第一次会多一次 refresh(键集变化的预期后果)。那是行为变化不是失败,除非断言了十一键或「refresh 次数恰为 N」。步骤 2 的检索就是找这些断言。

**degraded 审计重复。** lag 持续期间每次 settle 一条事件。契约是「消费侧落审计」,不是「会话至多一条」。不设静音窗口,避免又引入时钟。

---

## 7. 教程映射(只登记,不改章节)

| 位置 | 登记 |
|---|---|
| ch7 §7.3(`docs/tutorials/v13/chapters/07-artifacts-plane.md` 约 `:60-78`) | `memory_graph` 正文是 `kind=context_section` 的 blob,不是 `chunks` 投影,也不在 `artifacts.inline` 上建 `==>`。索引仍在 `memory_nodes`/`transcript_chunks`。context artifact 只持哈希 |
| ch10 §10.6(`10-rag-as-tools.md` 约 `:152-172`) | 新段仍是那 9 个 IR 字段。`cache_scope=Session`,默认 priority `LastResort`,`payload_ref.kind=blob`。它不是 `query_side` 的候选,没有 spans,不进 CAND4 |
| ch14 §14.4(`14-fork-and-replay.md` 约 `:123-148`) | exact replay 读升级前的 artifact,字节里没有 memory 段,也不重新 validate。recompute/fresh 在新代码下得到 version 4。validate-spawn 比较的 prefix 含 `manifest_version` 4,与 v3 artifact 的冻结身份不一致时拒绝——这是身份声明,不是回放种类混用 |

练习编号不新增。Oracle 裁决并交付后若要改教程正文,另开文档提交,不塞进 W1–W3。

---

## 8. 明确不做

| 项 | 触发(满足才另立计划) |
|---|---|
| CJK 路由(supersede DP9-OQ3) | 仍是 v2 §8 三条夹具,且第三条必须不依赖本接线 |
| 锚池对称 / 放宽 `candidate_top_k` | OQ-E 被判同批时走附录 A.5(W4);否则保持 v2 挂号。rerun 已说明当前数字不可直接当模拟 |
| `query_side.candidates` 收记忆节点 | 不设触发。与 CAND4、OQ8 四依据冲突 |
| 新 effect kind、改 advance ② | 仅当 OQ-A 被判为 A1 时另立 supersede(须先显式 supersede DP9 §8);本计划不实施 |
| `pending_walk` 持久化 | 仅当 OQ-A 被判为 A2;列集以附录 A.1 为上限 |
| walk 写在 refresh 体内 | 与不变量 3、DP1 锁窗冲突。若 Oracle 坚持,先改不变量文本再修订本计划 |
| transcript cron 自动化 | memory README 纪律⑧的原触发(会话数),不因接线提前 |
| walk/round 生命周期清理 | DP9 原触发;本接线不清理 |
| demo / Chainlit 升格 | 产品要在 UI 上看记忆段时。工人契约以 README 为准,demo 自行对齐 |
| 设计文档专章、教程正文改写 | 文档里程碑,不挡 W1 |
| 改 `dec` 定义、改 evidence 三键、改 render 对其它 kind 的过滤 | 无触发。render 全量输出是既有行为 |
| `memory_nodes` 或 `transcript_chunks` 加列 | 仅当读时 join 在闸门上贵到 p99 破 memory 的投影预算;先拿出 EXPLAIN 与计时 |
| 用 provenance 改排序或降权 llm 节点 | 固定评估集证明「同权 llm 复述」伤害回答之后。本计划只让它可见 |
| T1 嵌入、AGE、admission 五问 | DP9 §8 原触发,未变 |
| 在线迁移 v3 artifact → v4 | stage 库 DROP-CREATE。不写 UPDATE(也写不进去) |
| 把 mgraph 放进 `v13_econ_ver` | 仅当记忆段进入 `sec_full` 且因此改变 tier/transform 选择。与裁决的 OQ-B(B-E2)互斥 |
| 第 17 号 SQL stage | 不预留。若 16 号文件无法审查,再考虑搬迁;搬迁仍是 OR REPLACE,不是改 periphery 历史体 |
| `v13_fork` 复制图 | 无触发。fork 不复制 `memory_nodes`/`memory_walks`/`v13_mgraph_meta`,子会话图为空;exact_replay 读父 artifact 已冻 blob;validate-spawn 对 v3/v4 身份不一致的拒绝是身份声明,不是回放种类混用 |
| 把 memory 段放进 `sec_full` | 仅当夹具上 memory 段 `est_tokens` 加上仍被 wire 送出的 history 超过 `budget_tokens`;那次之前不改 `v13_econ_ver`(与 B-E2 互斥) |

---

## 附录 A. Oracle 备选的全部合法增量

未列出的改法视为超范围,回到计划修订,不在实施提交里即兴。

### A.1 OQ-A 不选 A4

**A3 tick。** 删除 W3 的「refresh 之前」契约。改为 README 写明:外部调度重复 `run_round` 直到 stopped;本回合 settle 只看见**已经** stopped 的 walk,否则无段。J8 改为:先走完 walk 并提交,再开一个新回合 settle,段才出现;同一回合内先 settle 后 walk,段仍缺席。不新 SQL 函数。advance 不动。

**A2 pending_walk。** 新表只许这些列:`session_id uuid`、`query_hash text`、`mgraph_generation bigint`、`policy_version int`、`status text CHECK (status IN ('wanted','done'))`,主键四元组不含 status。无 timestamptz。`wanted` 由工人插入,`done` 在 walk stopped 后插入(允许本表 UPDATE status,因为它不是记忆事实)。assemble **不读这张表**。段的有无仍只由 stopped walk 决定。不把 status 放进 `mgraph_ver`。

**A1 进 advance。** 不提供补丁。需要显式 supersede DP9 §8 那一行,且先解决「advance 事务内持锁做判断 IO」与不变量 3/DP1 锁窗的冲突。

### A.2 OQ-B 不选裁决段形态(将来 supersede 时)

**B-T2 第三臂。** `payload_ref` 增加 `kind='memory_graph'`,键 `content_hash` 为材料哈希(材料仍要 blob,否则 render 没有不可变正文——第三臂单独不够)。`v13_render_section_body` 增加一臂,读 `context_section` blob,不读 `memory_nodes`(节点可被重建删掉)。validate 的 payload_ref 词表从二值变三值。这比推荐多两个活体函数,只在 Oracle 明确拒绝「段是普通 blob」时使用。

**B-E1 进入 `sec_full`。** 把 §3.2 的 UNION 支复制进 `sec_full`。J7 对 `t_used` 的断言改为:`t_used` 含 memory est。接受 tier 可能因此上升。`v13_econ_ver` 仍然不改(策略版本没进经济学行;段字节不是政策行)。若 Oracle 同时要求经济学「看见」mgraph 策略版本,那是另一次 token 设计,停工修订,不准顺手改 `v13_econ_ver`。

**B-T3 inline。** 不提供完整草案。破坏 section 指针式 IR 与 refresh belt 复用,选这个等于重开 W2。

**预算 skip 仍留在数组里。** 删掉 `final_sec` 过滤。J6 的预算断言改为:段在,`transform.reason=budget`,且 **render body 仍含节点文本**。README 写明「budget 只是审计,wire 仍注入」。这弱于超集纪律,只有 Oracle 明确接受 wire 副作用才走。

### A.3 OQ-C 不加键

删 `v13_mgraph_asm_ver` 与 context_required/validate 的十二键增量。`prefix_identity` 的 version 4 **保留**(schema 仍变了)。J1 改为:键集串与 periphery 十一键逐字相同。README 运维写明静默窗口:generation 或 mgraph policy version 变化、且 `sem`/`dec`/`goal`/其它键都不变时,active manifest 继续旧段,直到下一次别的键变化。refresh 锁名单里的 `mgraph` **保留**(settle 仍读该行来决定段内容,串行化翻版仍有意义)——若 Oracle 连锁也要去掉,J9 去掉对锁名单的断言即可,这是唯一额外删法。

**C2′ 宽 digest。** 在 `mgraph_ver` 材料里加 query_hash/read_enabled/freshness/walk status/frontier digest。仅当 OQ-A 选 AF2 时成立;必须同时接受「walk 提交若在 revision 写回之后会立刻再失配一次」的自激窗口,并在 README 写明。AF1 下不成立。

### A.4 OQ-D 不选读时 join

**加节点列。** 不在 W2 里做。需要新 `builder_version`、build INSERT 增加 type 聚合、重建语义、以及「混合类型如何压成一列」的第二次裁决。读时 join 已经能表达 mixed;加列不会更诚实。若 Oracle 否决读时 join,W2 停在「段不含 provenance,body 只有 evidence 三字段」,J5 整组删除,张力 6 记入 §8。不准在没写重建方案时 ALTER `memory_nodes`。

**加 transcript.kind。** 不提供草案。memory 文件字节冻结是 §1.3 锁定;要破除须 Oracle 同时改「前缀冻结」那一条。

### A.5 OQ-E 判同批

W4 在 W3 提交并全绿之后单独提交。开工前先用**当前**会话的节点集跑一次对称性计数(T 端 top-k 是否含对端),把数字写进 README,再选下面之一,不准三个都做:

- 并集:对每个锚,候选 = 自身 top-k ∪ 「把我列入 top-k 的对端」,再按分数截到 `candidate_top_k`。`v13_mgraph_candidates` 的 SQL 串与 `==>` 次数保持恰 1。矛盾问仍只在 canonical 方向入封(偏差 #40 不动)。
- 或只升 `candidate_top_k`:新 mgraph 策略版本行,键集不变,只改该值,双 UPDATE 翻版。默认种子 v2 的值保持 5,测试版本才更大。`v13_mgraph_policy` 读取器不动。

W4 的 gate 是新组 **K**(J 不复用):目标对在并集或新 k 下进入关系信封;A/D/G/H 回归;`==>` 源码计数仍为 1。没有这组断言就不许改候选函数。

### A.6 OQ-F 把范围拉大

tick 自动化、demo、walk GC:本附录不写 SQL。拉进范围 = 计划修订一版再实施。F7 若被判「整组保留原闭集、不准 OR REPLACE 装配函数」,则与 §1.3-1 冲突,同样是计划修订(那会迫使装配换体挪出 mgraph 文件)。

---

## 附录 B. 实施期必须验证的未知

| # | 未知 | 怎么验 | 验失败时 |
|---|---|---|---|
| B1 | mgraph 测试是否已经断言十一键、version 3、或 OR REPLACE 只有两名 | 步骤 2 的检索 | 只改 mgraph 测试;periphery 测试不动 |
| B2 | `v13_lock_key(uuid,text)` 对 refresh 的属主可调用 | W1 加载后在 refresh 里调用;函数已在 build/run_round 使用 | 属主本来就能执行自己的函数;若签名不是两参,停工,不要新写一把锁 |
| B3 | canonical 消息的文本是否就是 `payload->>'text'` | 插一条 user/message,比较 `v13_canonical_state` 与 events | 查询函数仍以 events 列为准;只把 README 里的「与 canonical 对齐」改成实测键名 |
| B4 | mgraph 文件末尾形态与五函数零前换体 | 读 mgraph 文件末 30 行;全文件计五个装配函数。**已验:末行是 COMMIT,OR REPLACE 计数=0**——Stage 16 下 mgraph 两文件字节不动,该事实固化为「F7 原文不改」 | 若已有人换过体,复制源改为那个最新定义,墓碑改写 |
| B5 | jsonb 对象 `::text` 在两次调用中稳定 | J2/J4 的字节相等 | 稳定失败则停止使用 `::text` 哈希,改用与 `v13_body_hash` 相同的显式规范串,并在 README 记偏差。不要引入 pretty-print |
| B6 | 手造 v3 manifest 时 economics/render 等块必须过其它层,版本断言才会被打到 | J2 用一次真实 settle 的 jsonb,只改 version 字段 | 断言放在版本检查上,不要依赖更早的键集失败 |
| B7 | route 直调 assemble 在补 GRANT 之前是否确实缺 evidence | W1 末、GRANT 前用 `has_function_privilege` 看一眼(预期 false)。**已验:evidence 今天只授 recall/resolve** | 若已为 true,说明有旁路授权,J9 改成「授权后仍为 true」并在 README 记实际来源;显式 GRANT 仍无害 |

---

## 附录 C. 裁决默认一览

| 题 | 裁决 | 实施章节 | 若将来 supersede |
|---|---|---|---|
| 落点 | **Stage 16 尾追加(已裁)** | §1.2、§4 | supersede 时按 §1.2 的 mgraph 末段形态(需先修订本计划) |
| OQ-A | **A4(=4′)refresh 前、锁外、resolve 步进(已裁)** | §3.7 | A.1 |
| Freeze | **AF1 freshness-first(已裁)** | §1.4 | A.1(AF2 须同选宽 digest) |
| OQ-B | **单段 blob,不进 sec_full,LastResort,未 applied 则不进数组(已裁)** | §3.2–§3.4 | A.2 |
| OQ-C | **加 `mgraph_ver`(窄 digest,已裁)** | §3.1、§3.5 | A.3 |
| OQ-D | **读时两跳;七键闭集(已裁)** | §3.1 | A.4 |
| OQ-E | **不实施(已裁)** | §8 | A.5 = W4 |
| OQ-F | **新 stage + load.py 两处 + mgraph README 指针;不碰 tick/demo/GC(已裁)** | §4、§5 | A.6 |

锁定且不在上表里的决定(裁决也不要顺手翻掉,除非明确点名):前 15 个 SQL 文件中 mgraph 两文件字节不动、其余 13 个不改;load.py 仅两处追加;不 DROP 旧签名、不新 effect kind、不改 evidence 三键、不改 `dec`、不改 `v13_econ_ver`、新函数 STABLE、新 RAISE 为 V3009、组字母 J、默认 read 仍关闭、provenance 不改分数。

## References

- DP9 计划 `docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md`(OQ8 :108-111,§3.6 :359-361,§8 :513)
- v2 计划 `docs/plans/v13-dp9-mgraph-v2-plan-2026-09-24.md`(§8 :354-360)
- 两份实测 `docs/investigations/v13-dp9-mgraph-demo-trial-2026-09-24.md`、`v13-dp9-mgraph-v2-demo-rerun-2026-09-24.md`
- 升版先例 `docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md`(:28 追动键纪律/:142-147 v2 升版/:163 记忆段消费契约)、`v13-dp8-periphery-p1-plan-2026-09-20.md`(v3 升版/exempt replay)
- 设计 `docs/designs/v13-context-on-pg.md`(§4.4 :125-133/§5.2 :202-215/§6.1 freeze/§6.2 触点)、errata E4/E5
