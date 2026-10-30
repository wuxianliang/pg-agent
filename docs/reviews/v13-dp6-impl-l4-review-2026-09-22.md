# v13 DP6 实现 L4 验收代行评审（filter 过滤管道 + memory 三层记忆栈）

> 评审对象：`e4c5646`（M1 filter，6 files +3998/−0）+ `29a8a10`（M2 memory，7 files +1204/−2）。
> 评审权威：`docs/plans/v13-dp6-filter-memory-plan-2026-09-20.md`（2042 行；§1.1 九处授权/§1.2 26 契约/§1.3 OQ1–10/§1.5 12 不变量/§3 两 SQL 草案/§4 A–H+I–N 断言表/§5 风险表/v2 对齐节）。
> 通道：ask_oracle 管道故障延续（父控制器在案），按 debt-closure 先例降级；本轮经 engineer 路由重启 `context_builder review` **成功**（主 lane 完整返回，副 lane 仅开场白无结论）。oracle 全部发现（2P0/3P1/3P2）逐条经本会话源码独立核验后采信/降级/驳回——本报告为独立源码核验结论，oracle 结果仅作输入。
> 已核事实（控制器，不复跑）：11 gate 全绿 exit 0（filter 288 / memory 91 + 前序九 gate；twophase 114→116、envelope 364→366 为全树源扫描覆盖新文件的预期 +1/文件）；已推 origin/main；diff 范围=两 stage 五件套+load.py+H4 树生长 4 行，无越界。

## 0. Verdict

| 提交 | verdict | 计数 |
|---|---|---|
| **`e4c5646`**（M1 filter） | **PASS-with-notes** | 0×P0 / 0×P1 / 4×P2 |
| **`29a8a10`**（M2 memory） | **PASS-with-notes（携 1 P1 尾债）** | 0×P0 / 1×P1（plan 草案级，非实施漂移）/ 3×P2 |

不给 FAIL：无 P0；五个 OR REPLACE 经全函数体规范化 diff 对上游加载态逐行核对，canonical 半边逐字保留、20 键集与 csh 公式零变动、全部增量为 §1.1 授权编辑；A–H/I–N 重点断言（C7/C7-4、D6、E5 双形态、F4 三形态恰分、G4 双连接 pg_locks 实证、H1 矩阵、J2/J3、K3）全部在档且可红。不给无 notes 的 PASS：freshness 分母含空体事件为草案自带缺陷（P1-1）；测试错误路径一处 NameError、一处死代码（P2）。

## 1. SQL 对 §3 忠实度（逐项）

| # | 核对面 | 结论 |
|---|---|---|
| 1 | 存在性 Noul 先行闸门（C 组序） | **通过**。resolve filter 半边序=existence 缺口优先→`v13_filter_gate_open` 三态→per-chunk；C1 calls 行序断言在档 |
| 2 | per-chunk Score 跨 session 缓存；`candidates_digest`=DISTINCT content_hash 排序 sha256（bm25/spans 不入料防漂移） | **通过**。`v13_candidates_digest` 单源（信封侧/装配侧同函数同输入）；D5 变集互异/乱序归一、D6 仅候选维度断言真咬「对象全文入料」回归 |
| 3 | F1/F2 立法 | **通过**。judgment_defaults v2 两点三态（先插 inactive→双 UPDATE 翻）+`v13_filter_defaults_action` V3006 运行期 fail-closed；`v13_existence_ref` 含 digest（F2 字面载体化，附 A #3 载体偏差在案） |
| 4 | F10 fail-closed + 滞后上界 + 当前 turn 直读 + 上一 turn 可召回 | **通过（含 1 尾债）**。reader 零 events 回退路径；max_lag=16；当前 turn=canonical_state 结构性；J2/J3 行为断言。**例外=P1-1：freshness 分母含空体策展事件（§4）** |
| 5 | bodies_present 守卫（体缺零 ask 零缓存）+ 态基数 belt | **通过**。守卫+belt 双保险；C7-3/C7-4 断言钉死（见 §2） |
| 6 | 三层记忆栈（投影/水印单调/分区） | **通过**。transcript_chunks 五列逐字+自证 CHECK+FK+UPDATE 拒；I3 watermark 单调；独立表独立索引（零 corpus 列） |
| 7 | 单索引纪律 | **通过**。M1 恰一（pg_index 计数）；decisions 索引落 memory 文件=§1.1 授权⑨ |
| 8 | ACL 链 | **通过**。H1 三角色矩阵+filter_ask 双角色负向+PUBLIC 14 函数逐件 False；N2 SELECT/EXECUTE 正向+四 DML+TRUNCATE 负向+rebuild/verify 双重负向。无放水（resolve→filter_ask 正向由 H3 resolve_login 全链间接覆盖，成立） |
| 9 | 纸面加载 19 CF / 0 TRIGGER / 无重复签名 | **通过**。H5（19/5/0/无重复+种子 4I+3U+2IDX+1R+5G+BEGIN/COMMIT 配对）、N3（1T/2I/6F/1TRG/1I/1DO/1R+2G）钉进断言 |
| 10 | 前缀切片 10/11 位 | **通过**。load.py 第 10/11 位+STAGE_THROUGH；H4/N3 双向断言（filter 库无 memory 对象/characterize 库无 filter 对象，条件执行+结构注记） |
| 11 | 五 OR REPLACE 机械复制 | **通过**。规范化 diff：judgment_hash 唯一增量=group_state→row_context；envelope=rc/tmpl 前移+fg/frows+needed UNION+groups NOT IN（20 键/csh 零动）；resolve=canonical 逐字（仅缩进/换行排版）+NOT IN 腰带×2+filter 半边；assemble=rc2/fc+qside 填充+jud 换体；chunk_referenced=@> 等价换载。**零未授权漂移** |
| 12 | 批 ≤32（batch 条款） | **通过**。v_bs=信封冻结 `batch_questions`；fbatch LIMIT v_bs；E2 k=64→⌈64/32⌉=2 批数字呈报 |
| 13 | α/β/calls/γ'/read-back/no-progress 与 DP2 家族 | **通过**。`v13_filter_ask` 逐字同款；上游加载态确认 `EXECUTE format('SET LOCAL …')`+`NULLIF(…,'')` 本就是 DP2 原文——草案 set_config/裸 cast 为草案失真，实施取上游家族形态（偏差 #1/#4 见 §3） |

## 2. A–H / I–N 断言强度（dp1 同标准，重点 9 项）

| 断言 | 结论 |
|---|---|
| **C7 键-态绑定** | **真钉死**。C7-1 毒化 parse 零消费/零 calls；C7-3 DELETE 后 resolve：failed=false、remaining=0（过滤行剔出）、**零存在性 ask ∧ 零 existence cache 行**（`judgment_cache WHERE signal='corpus_exists' AND request_hash IN (decisions…)`=0——直接钉「不问不缓存」）；C7-4 同体重摄取→digest 逐字节复等→resolve 后 **existence asked exactly once**——若 ③ 曾在全集键下落缓存则此处为 0，「陈旧无答案回流封死新证据」死法被恰好钉住。belt（竞态窗）无直测但为纵深防御，plan 未要求 |
| **D6 仅候选维度** | **真咬**。同 content_hash 集、bm25 互换+spans 变化两组→digest 相等；实现若改对象全文入料此行即红（bm25 5.0≠原值）。与 D5 变集互异/乱序归一互补 |
| **E5 α 双形态** | **与 dp1/dp2 家族一致**。引擎事实（pg_typesafe HTTP 等待不可被 statement_timeout 中断，probe 实证 08006）+DP1 turn 7 #45(b) 裁决：E5-a 挂起 socket+50ms<5000ms→断言 fail-loud 上抛且 pgcode∉{None,V3001}；E5-b 触发器持 advisory 锁阻塞 calls 落行+pg_cancel→**57014 直测+未被吞为 failed=true 返回+零新 calls**。V3001 β 路径由 E4/C5-1 保。引擎支持中断后升回（README 注） |
| **F4 毒化三形态** | **可红，恰分成立**。三独立 fixture+全行 `all()` 断言+`bases_f4 == ({missing},{timeout},{review})` 词表划分断言；F4-1 manifest 侧 decision_id 全 NULL+judgments 仅 existence 同场。注：①用「批预算 1 截断」替代草案字面「毒化 settle」制造 missing 态——毒化下 parse fail-loud（C7-1 已证）无法 settle，草案字面不可执行，行为面（零 per-chunk 行）等价，可接受 |
| **G4 批写锁纪律** | **两连接 pg_locks 实证在档**。writer A resolve 持 advisory 锁未提交→B rebuild 于 pg_locks 呈 `NOT granted`→A commit 后 B 苏醒+引用行存活；三轮 writer∥ingest 交错零 40P01；多源冒烟（writer∥跨双源 rebuild）断言 w ok ∧ r 重试收敛（40P01 fail-loud+3 次幂等重试）——与 plan「不硬断零死锁」口径一致。**一处 P2：`test_filter.py:2157` `bC.rollback()` 未定义变量（应为 `bconn`）——错误路径 NameError 掩盖诊断（§4 P2-1）** |
| **H1 三角色+PUBLIC** | **无放水**。见 §1#8 |
| **J2 上一 turn 可召回** | **钉死**。多轮 fixture：turn1 已投影+turn2 未投影→reader 命中 turn1 文本；lag≤max_lag ∧ degraded=false |
| **J3 超界不谎报** | **钉死（一处 P2 弱化点）**。20 事件不 build→lag=20>16→degraded=true+NOTICE 捕获（conn.notices）+reader 仅返回已投影前缀（新文本零命中）+投影恰 1 行。P2：当前 turn 直读对照挑的对象是 head（第一条，投影亦含）而非最新 tail——「canonical 含最新消息」半边靠「投影恰 1 行」间接推出，未直接钉（§4 P2-5） |
| **K3 复合计划随升** | **成立**。§5 风险 #11+附 B 原文预授权（「若 Custom Scan 不被选择……断言随升」）；实测 `session_id=$1 AND body==>$3` 计划=PK bitmap+`score_bound_indexed` 零 Seq Scan；升格断言（无 Seq Scan+双索引背书）强于原字面（Custom Scan），reader 体保持草案逐字无需预过滤改体 |

## 3. 九项自报偏差逐项裁定

| # | 偏差 | 裁定 |
|---|---|---|
| 1 | `SET LOCAL` 家族（filter_ask 两处） | **接受**。上游加载态（envelope resolve_judgments）本就是 `EXECUTE format('SET LOCAL…')`——草案 set_config 为失真；且 H6/K4 banned-literals 扫 `set_config` 字面量，进 SQL 即破扫描断言。事务局部语义等价；DP2/DP4/DP5 家族先例 |
| 2 | E5 α 降级（#45(b)） | **接受**（§2 已核双形态） |
| 3 | tmpl CTE 增补 question/criteria 两列 + `NULLIF(f->'criteria','null')` | **接受且必要**。fg 守卫/frows 消费 question/criteria 而草案 tmpl 四键不含——草案缺陷；NULLIF 还原 SQL NULL 保 needed 省 criteria 键形态（DP2 json-null 坑家族） |
| 4 | 落行循环 ORDER BY signal + fbatch 别名 s.value + jud `"row"` 引号 | **接受且必要**。ORDER BY=不变量 7 三处纪律的第三处（附 B 已自检要求、草案函数体漏写）；另两处为草案引用/保留字错误（裸加载即报错） |
| 5 | **引擎 schema 授权落 setup_db.py** | **裁定：setup_db 承载是 dp6 范围内唯一合法落点；缺口定性 DP5 面；记 plan erratum 悬置清单（父循环统一收口），不作 dp7 首工作项**（专节见 §3.5） |
| 6 | ACL 链闭包纯追加（existence_action→recall、defaults_action→recall+route） | **接受**。invoker 链（trace 三角色→chunk_filter_action→两函数）的结构必要项=H1「trace 三角色 ✓」的执法前提；纯追加、无 PUBLIC 放水（逐件负向在档）；H5 把 5 GRANT 钉进纸面断言 |
| 7 | K3 断言随升 | **成立**（§2 已核） |
| 8 | fixture 注记（全局缓存键隔离 / E2 k=64 版本化翻行 / advance 时序探针化） | **接受**。独立 token+corpus 隔离是 D2 设计面（缓存全局键）的正确 fixture 卫生；翻行走分配器+测毕还原（cgr 相对比较纪律） |
| 9 | transcript_immutable 补 V3006 | **接受**。不变量 10（新 RAISE 统一 V3006）优于草案字面遗漏；I2 断言 pgcode='V3006' 直接消费 |

另有两处实施裁量随报随受（不列偏差）：信封 `timeout_ms` 键与 calls 列的 `NULLIF(…,'')` 空串防御（行为等价强化）；memory README #3 pg_cron stage 库常态走降级分支（cron.database_name 闸，DP4 G6 同款先例，N1 行为面等价断言保底）。

### 3.5 偏差 5 特别裁定

- **唯一合法落点：是。** (a) filter H6「零 `stannum.` 限定名」与 memory K4「恰 3」两源码扫描断言把 SQL 文件落点结构性封死——`GRANT … stannum.score_bound` 必然引入限定名；(b) v2 修订纪律「既有 gate 一律不弱化」禁止改断言放行；(c) §1.1 硬边界禁改 DP5 上游文件（characterize SQL 是语义上最贴切落点但 dp6 无权触碰）；(d) `run_probes` 部署面先例同位（`setup_db.py:34` `run_psql(s, DB, GRANTS)`）。
- **缺口定性：DP5 面，属实且为新发现。** dp5 引入 stannum 引擎依赖但仅 full_score 有 PUBLIC EXECUTE——schema 无 USAGE、score_bound/score_bound_indexed 为 owner-only ACL；dp5 L4 review（2026-09-22）无此缺口在档（其 ACL 断言面未覆盖「角色身份执行引擎链」形态）。dp6 的 trace→recall_candidates→recall 链第一次踩到（42501）。
- **处置：记入 plan erratum 悬置清单，父循环统一收口；不宜作 dp7 首工作项。** 理由：dp7=经济件（一页账/花费闸/sections），部署 ACL 与其不同纵面；该缺口影响全部已有 stage 的 `load_stage` 生产装载路径（角色跑 reader/trace 链即 42501），非 dp7 前置依赖；塞进 dp7 会把跨 stage 部署债卷进经济件里程碑。建议收口形态（父循环裁量）：characterize 追加一段部署面 SQL（或 load.py 统一 GRANT 段）+ dp5 gate 补「角色身份执行引擎链」断言，随 P1-1 修复轮（dp6.1）或独立工单落地。dp6 两个 setup_db 的 GRANTS 块届时可直接引用为蓝本。

## 4. 发现摘要（P0×0 / P1×1 / P2×6）

| 级 | # | 一句话 |
|---|---|---|
| P1 | P1-1 | `v13_transcript_freshness` 分母（`max(seq)` of 策展事件）不排空体——尾部空体事件不可投影，watermark 永滞其后，lag 永不归零；尾部空体 ≥17 时 degraded=true **永久谎报**（投影实已覆盖全部可投影内容），DP7+ 消费契约会误禁记忆段。plan 草案自带缺陷、实施逐字忠实（`v13_memory.sql:101-124` vs 草案 §3.2 同款）；方向 fail-safe、无当前消费者，故不阻断收口 |
| P2 | P2-1 | `test_filter.py:2157` 错误路径 `bC.rollback()` 未定义（应 `bconn`）——G4 rebuild 失败时 NameError 掩盖根因诊断（断言仍会红，不影响判定正确性） |
| P2 | P2-2 | `test_filter.py:1805-1816` 死代码：`ok_trace` 空 for + `dj` 死赋值（F2 trace 对照真断言在其后有效存在）；且对照循环 `if t_h:` 缺失即跳过——judgments 有 decision_id 而 trace 无对应行时不红 |
| P2 | P2-3 | `v13_filter.sql` 尾部「OR REPLACE 五件 ACL 经 OID 保留」注释块整段重复两遍（COMMIT 前），紧审计尾部应去重 |
| P2 | P2-4 | `v13_assemble_manifest` qside 标量子查询与 `v13_chunk_filter_action` 两处 `LIMIT 1` 无 `ORDER BY`（草案继承）——同 signal 多世代 decision 行（session 中途 provider/model 换代）下 manifest 字节 planner-dependent；建议 `ORDER BY answered_at DESC, decision_id` 或按当前信封身份过滤 |
| P2 | P2-5 | J3「当前 turn 直读」对照对象错位：断言 canonical 含 head（投影亦含）而非最新 tail——「canonical 含最新」半边仅由「投影恰 1 行」间接推出，未直接钉 |
| P2 | P2-6 | `v13_rebuild_transcript_chunks` 按 uuid 升序逐会话耗尽全局 limit——持续积压的低 uuid 会话饥饿后续会话；plan 风险 #9「v1 接受会话全扫」的具体化，随「聪明 tick」台账处置（阈值触发时同批修） |

oracle 报告的两项 P0 经核验**驳回**：(a)「ON CONFLICT 落行可给异质材料行填答案」——request_hash 七参已钉 context/signal/kind/question/criteria/provider/model，「different material」结构性不可能，template_version 不入哈希为 DP2 家族逐字继承形态，answer 补齐正是 F4② 迟到答案语义；(b) 空体 watermark 项——属实但降为 P1-1（如上）。「低 seq 会话饥饿」降为 P2-6（plan 已裁 v1 接受）。

## 5. 修复清单（P1/P2 分级，供恢复后使用）

**P1（dp6.1 修复轮，或父循环并入部署面收口工单）：**
1. `v13/memory/v13_memory.sql` `v13_transcript_freshness`：`v_max` 查询加 `AND coalesce(e.payload->>'text','') <> ''`（与 builder 策展口径对齐；lag 语义回归「可投影滞后」，可归零；watermark 定义不动——单调性不受影响，v_max(非空)≥v_wm 恒成立）。
2. `test_memory.py` 补断言：尾部空体事件 fixture（I1 已有中间空体，追加「以空体结尾的会话」）→ rebuild 后 lag=0 ∧ degraded=false——把死法钉进 gate。

**P2（随下次触碰两文件的提交顺手清，不必单开轮）：**
1. `test_filter.py:2157` → `bconn.rollback()`。
2. `test_filter.py:1805-1816` 删死代码；F2 对照循环改「judgments 有 decision_id 而 trace 无对应行→check False」。
3. `v13_filter.sql` COMMIT 前重复注释块删一份。
4. qside/chunk_filter_action 两处 `LIMIT 1` 补 `ORDER BY`（或信封身份过滤）；F5 断言可加「多世代行确定性」用例。
5. J3 对照改挑最新 tail（canonical 含 tail ∧ 投影不含）。
6. 饥饿面随聪明 tick 台账（不单独修）。

**悬置移交（非 dp6 代码债）：**
- 偏差 5 部署面缺口 → plan erratum 悬置清单/父循环统一收口（§3.5：characterize 或 load.py 层收口+dp5 gate 补断言；两 setup_db GRANTS 块为蓝本）。
- plan v2 对齐节 A4（bootstrap_done 论域闸）/A11（file veto）为「只立法不实现」状态，其依赖对象（`v13_file_vetoes`、bootstrap_done 状态面）不在 v13 现树——归属 RP 原生化线消费，与 dp6 两提交无关，不构成缺口；移交父循环在 DP7+ 或 RP 线接线时对账。

## 6. 收口与 dp7 裁定

- **dp6 收口：收口**（携 1 P1 尾债+6 P2 清单）。P1-1 为 plan 草案级缺陷（实施忠实）、fail-safe 方向、无当前消费者；修复一行+一断言，不构成回退两提交的理由。AGENTS 里程碑纪律已满足（11 gate 全绿、load.py 第 10/11 位、两 README 台账、按路径提交推送、无 --no-verify）。
- **可否开 dp7：可以。** 理由：(a) dp7 消费的契约面全部就绪——§1.4① calls 含过滤族逐 ask 行、②chunk_filter/judgment_defaults 经济件输入、③sections 输入面（candidates.decision_id/judgments.final_action/trace basis/v13_assemble_spans+spans）、④memory reader 签名冻结三列+freshness 五键+degraded 契约、⑤摘要验收点缝、⑥一页账基线（k=0/8/32/64 四行+闸关 2 ask 形态）；(b) P1-1 修复只动 freshness 内部分母口径，签名与返回键零变动，对 dp7④ 契约零扰动；(c) 无未闭合 P0/P1 实施缺陷。

## 7. 方法与材料

通读 plan 全文 2042 行（§0–§7+附 A/附 B+v2 对齐节）；`git show` 两提交全 hunk；`v13_filter.sql`/`v13_memory.sql` 全文对照 §3.1/§3.2 草案逐段核对；五个 OR REPLACE 用规范化 diff（剥注释/空行）对上游加载态（envelope/recall/chunks 三文件）逐行比对；两 README+两 setup_db+load.py 全文；test_filter.py 重点段（C5–C7/D5–D6/E1–E8/F1–F7/G1–G5/H1–H6 全读）+test_memory.py 全文（I/J/K/L/M/N）；dp5 L4 review grep 复核 ACL 缺口无在档；debt-closure review 尾部核先例格式。未复跑测试（控制器已核 11 gate exit 0）。oracle（gpt-5.6-sol）8 项发现全部定位到源码行核验：2 驳回、1 降级采纳（P1-1）、5 采纳/降级为 P2；grok lane 无结论不采信。
