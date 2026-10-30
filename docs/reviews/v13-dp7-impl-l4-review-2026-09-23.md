# dp7 实现验收评审（L4 代行）——M1 economy `57e9205` + M2 summary `ac27750`

> 日期：2026-09-23。性质：父级 Loop Orchestrate 控制器授权的 L4 验收代行评审（ask_oracle 管道故障延续，按先例降级为本地 Review 工作流，如实记录）。评审重点=**B-DP7-1/B-DP7-2 oracle 三角裁决（方案 D）的执行保真**，rubric=裁决 `docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md` §3.5 的 14 检查点 + §4 三条授权登记 + 7 条自报偏差。
> 材料（全部亲读）：裁决全文 397 行；plan `docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md` 全文 1191 行；`git show 57e9205`（6 files +3706）、`git show ac27750`（6 files +5065）；`v13/summary/v13_summary.sql` 全文（2467 行）；`v13/summary/test_summary.py` 结构+关键组全文；`v13/economy/{README.md,test_economy.py 关键组}`；`v13/filter/v13_filter.sql` 关键面（偏差 #1 主张核验）；`v13/load.py`；`prompt-exports/loop-orchestrate-v13-deep-plans-impl-runs.md` turn 13 行（turn 14 尚未落表）。
> 已验证事实（控制器 L1 已核，本轮未复跑）：13 gate 全绿（summary 228 PASS 新增；twophase 118/envelope 368 为全树源扫描 +2 预期；loop 负载抖动后 3/3 复跑绿）；两提交已推 origin/main；diff 范围=v13/economy+summary 五件套+load.py。
> 本轮**独立复验**（不采信 gate 自身断言的部分）：refresh v3 vs economy 加载态 normalized diff（评审者自己提取函数体+归一化+SequenceMatcher，另做去缩进字节比对与函数头比对）。

---

## 0. 结论一览

| 项 | 结论 |
|---|---|
| **M1 economy `57e9205`** | **PASS**（含当时如实登记的 B-DP7-1/B-DP7-2 阻塞与 PG 实机探针证据；C4/G/H/README 抽查全部成立） |
| **M2 summary `ac27750`** | **PASS**（裁决 14 检查点 14/14 满足；7 偏差 7/7 ACCEPT；发现 0 P0 / 0 P1 / 4 P2） |
| **dp7 收官** | **是**（两里程碑交付+裁决执行保真通过） |
| **可否开 dp8** | **可**（附两条轻量收口提醒，见 §6） |

---

## 1. 裁决 §3.5 十四检查点逐条

| # | 检查点 | 核验方式（独立） | 结论 | 证据锚点 |
|---|---|---|---|---|
| 1 | 授权先验：README 台账+erratum 三条 | 亲读 summary README §「裁决授权」：E-DP7-1/E-DP7-2/C-DP7-M1 三条原文逐字在档（与裁决 §4 对照一致）；gate P6-readme 断言三键名在场 | ✅ | `v13/summary/README.md`；test L2404-2412 |
| 2 | diff 允许清单恰四项；IF 臂四行逐字 | **评审者独立 diff**（提取两文件 refresh 体→剥缩进/剥注释归一化→SequenceMatcher；另做 IF 臂去缩进字节比对、函数头比对）：差异恰为四簇——①锁集 IN 增 `'summary_accept'`（一行）；②`FOR SHARE`（pricing FOR UPDATE 之后、形状守卫之前，ORDER BY effect_id，零行合法）；③history belt IF 包裹；④tools belt 后（artifact_land 前）summary belt。函数头（签名/SECURITY DEFINER/search_path）逐字节相同。IF 臂四行去缩进后与 economy 原文**逐字相同**（唯一差异=绑定名 `v_hist`→`v_full`，即裁决 §3.2.4 规格代码自带的名字，gate 注释明示）；DECLARE 增 `v_mat/v_sh/v_smat` 为 #3/#4 的必然伴随（裁决规格代码同款）。其余（入口/fence/锁序骨架/守卫全文/complete CAS/tools belt/artifact_land/result 补挂/指针/返回值）归一化后零差异 | ✅ | 本报告 §独立 diff；`v13_summary.sql:2175-2435` |
| 3 | 未变形臂字节身份（actions off+库中 adopted ⇒ IF 臂+全文哈希） | 结构面：(a) actions off 即返回 'full'（`v13_history_action` 首分支）；(c) 非 tail 即 NULL。gate **确实构造了该场景**：L4-3 以「库中有 adopted=true 的 succeeded 行（真实链路产出）+ 翻回 actions off」settle，断言 accepted、history 哈希==sha256(canonical 全文)（测试端自算 full_sha）、零 summary 段 | ✅ | SQL 383-391/717-731；test 2024-2040 |
| 4 | ELSE 非自述；summary 材料不读 rounds[].content_hash | ELSE 臂三处哈希对象全部=单源函数返回值（`v13_history_section_material`/guard 内 `v13_summary_section_material`），manifest 段无正文（sections 只携哈希）；源码检索 (c) 函数体零 `content_hash` 读（仅禁读注释），材料=`rounds[末]->>'body'`→to_jsonb。调度条件=哈希相等非读 action（裁决指定形态） | ✅ | SQL 710-760、2199-2224 |
| 5 | 独立 oracle：O1 自切尾段；guard 负向单测 | O1-4 测试端 Python `tail_seqs` 定界+SQL `jsonb_agg` 限定 seq 自算尾段哈希，**未调任何单源材料函数当 oracle**；guard 负向=真实 adopted 链（schedule→claim→envelope→resolve(mock 0.9)→verdict→complete adopted=true）后 owner 直调 guard，喂「自洽但头切片非后缀」的 manifest ⇒ V3007 'not a true suffix' | ✅ | test 1573-1583、1925-2022 |
| 6 | 不变量 9 负向：自报哈希填错 ⇒ 仍 accepted、落行哈希==body | `drive_summary`/各 fixture 的 rounds[].content_hash 一律故意填 `"0"*64`；O1-1 settle accepted 零 V 码；O1-3 段哈希==sha256(to_jsonb(body)::text)（测试端自算）且 ≠ 自报值；artifacts inline==to_jsonb(body) | ✅ | test 449-460、1552-1571 |
| 7 | span 信源=request 冻结值；O2 失配走 IF 臂 | (a)/(c)/guard 三处均读 `request->>'span_digest'`，result 副本零读；O2：消费后追加 user/message+压力回落（fixture 翻 cooldown 加速），断言 history 哈希回全文（IF 臂）、无 summary 段、fallback.basis='span_stale'（steps=[]）、settle accepted。span_stale 在 action='full' 下可观测（sbasis 第一分支） | ✅ | SQL 560-570、734-749；test 1643-1684 |
| 8 | 锁与并发 | 锁集六名含 summary_accept（独立 diff #1）；FOR SHARE 位次=pricing 后/守卫前（#2），sessions 锁在前=同向零反向路径；gate H1-type：A settle 持锁期间 B 翻 summary_accept 阻塞（lock_timeout 600ms 捕获 LockNotAvailable，<3s）；settle∥settle 零 40P01 由 economy H1 覆盖（refresh 锁骨架逐字相同，FOR SHARE 只加自身 session 行）。README ops 锁序同步更新 | ✅ | test 2355-2401；economy H1 |
| 9 | 回滚完整性 | L4-9：SAVEPOINT+临时毒化 `v13_summary_section_material` ⇒ belt V3007；回滚后断言 effect 回 claimed、artifacts 零残留（计数对照）、sessions 指针不变 | ✅ | test 2040-2102 |
| 10 | ACL | 四 helper+guard REVOKE PUBLIC 逐件断言（L4-10）；guard 对 route/resolve 均 has_function_privilege=false（P4 两向负向）；helper `prosecdef=false`（非 DEFINER）；(a)(b)(c)+span_digest 授三读角色=与装配同面；blob_land/artifacts 直写面=DP3 原状零改 | ✅ | test 2205-2239 |
| 11 | 词表与 M1 读法 | 收缩后 history 9 键/verbatim（O1-4）/64hex（validate 全段执法）/churn=prior+1（O1-4，前版哈希异）；summary 段经 validate v3（O7 正向+8 类负向）；manifest_version=2 断言在档；M1a=1 行/round1 calls 差 0/全程差 1/两轮哈希不等，M1b=2 行均 pre-finalize/差 2/ctx.summary 不等，M1-neg=gap 空/零新增，M2=failed 不误伤；**模板种子显式 epoch='pre-finalize'**（SQL 显式值+L4-12 查库断言，列默认 pre-bind 陷阱规避）。无「检查失败且 decision=2」伪构造 | ✅ | SQL 61-67；test 1143-1370、2342-2354 |
| 12 | （并入 11 的 M1 读法行） | 同上 | ✅ | — |
| 13 | 回退链可落盘 | O3 以 l_eff **二分定界**（largest_le，边界两侧 action 断言可红）逐级构造 spill/round_drop/final_trim 真实 settle（ELSE 臂+guard 过）；①能装下则零②=O3-①（零 compaction 段+steps==[spill]）；不跳级由 guard 规则 3（final_trim⇒前缀 round 已全丢）+validate recipe 闭集负向（[spill,final_trim] 拒收）+O7 双向；O5：goal/tools 全梯字节不变（对照装配哈希逐级相等）。一处恒真占位断言见 P2-1（覆盖面由邻接实断言承载，非假绿） | ✅（附 P2-1） | test 1701-1818、1840-1862 |
| 14 | 前缀回归 | 控制器已核 13 gate 全绿（economy 238/manifest/envelope 等各自前缀库；twophase/envelope +2=全树源扫描预期）；两 gate 自扫描断言对象 ≤各自文件号（H4/P6，token 运行时拼接防自匹配）；economy gate 断言 file12 零前向引用 13 号对象 | ✅ | economy test 1880-1899；summary test 2256-2278、2341-2348 |

---

## 2. 七条自报偏差逐项裁定（summary README §「与 plan 的实施偏差」）

| # | 偏差 | 裁定 | 理由 |
|---|---|---|---|
| 1 | 验收信封**十二键**（plan 十键 + `goal_hash`/`candidates`） | **ACCEPT** | 亲核 `v13/filter/v13_filter.sql`（第 10 位加载态）：`v13_resolve_judgments` 无条件调 `v13_filter_bodies_present(p_env)`（:841）→`v13_existence_ref` 对 env 断言 goal_hash 64hex + candidates array，缺即 **V3006**——plan 的十键在实装载 resolve 面上不可执行；P1-5 原则「逐键对齐 resolve 实际消费面」的正确延伸。gate L1 断言十二键恰等集 |
| 2 | 被丢 round 的独立段用 **kind='compaction'**（plan validate v3 词表只 +summary） | **ACCEPT** | 排除法成立：kind='history' 第二段会触发多段化规则把主段改名 `history:8hex`，冻结的 refresh belt 按 `section_id='history'` 取段即断（允许清单禁改 belt）；kind='summary' 撞 guard 规则 3 与 validate「consumed NULL⇒summary 段数 0」。DP3 契约 #7「增 kind 只加行不改结构」的形态；多段化规则（compaction:8hex）同律执法；O7 对四个新 reason/双段均正负向覆盖 |
| 3 | fallback steps 允许 `[]`（basis≠none 且 action='full' 组合） | **ACCEPT** | 裁决 §3.2.5 断言 10 要求 span_stale 在 IF 臂/action='full' 下可观测——若 fallback 仅在梯运行时在场，basis 无处安放。词表闭集执法（'' ∈ {'',spill / spill,drop_rounds / spill,drop_rounds,final_trim}），O2 断言实跑 |
| 4 | O4 的 `reason='summary_unavailable'` 落点=economics.summary.fallback.**basis**（'no_budget' 等）而非 skipped 段 | **ACCEPT** | v1 装配结构性不产 skipped summary 段（guard 规则 3+validate 双向一致排除该形态）；四新 reason 在 validate 词表内（O7 手构造正向过——词表通道保留给未来真实 skipped 段）；预留失败的装配半边可观测性由 fallback trace（J3/O4 断言 basis='no_budget'+steps）完整承载 |
| 5 | 决策基面双轨：pressure/tier/er/hint 用全量候选基面（fcls/ford），装箱/段产额用动作后基面（cls/ordered） | **ACCEPT** | 结构推论成立：动作决策必须以压缩前压力为依据（否则 J1 的 intent 在收缩后消失、O1-7 的反事实对照失去基线）；action='full' 时两基面同材料恒等（与 v2 值一致）。economics.er.hard_window 六键为 M1 已台账项（README 偏差 #1，plan E2 自身「er 6 键」与 OQ7 枚举 5 键不一致的取法），非 M2 新偏差 |
| 6 | J4 的「active manifest 段 hash 集」读作「当前 canonical 消息哈希集」 | **ACCEPT** | target_span 粒度=前缀**消息级**哈希（裁决 §3.2.1(a) 消费谓词同一单源），消息级哈希本来就不在 sections 的 content_hash 集内——plan 措辞的粒度错位；按 canonical 存在性检查保持「span 已变则等下一版 intent」语义且与消费谓词同源（更强）。J4 断言实跑（追加消息 ⇒ NULL） |
| 7 | 采纳 summary decision 并入 manifest.judgments 消费集（final_action='include'） | **ACCEPT** | plan **L5 原文明确要求**（「accept→judgments 消费集…final_action='include'」）；DP6 装配消费集只收 corpus_exists+chunk 是 13 号文件之前的形态。O1/L5 断言 consumed decision 进 judgments 且 epoch='pre-finalize'；不采用态零进（L3 对照） |

**七条全部 ACCEPT，无隐性偏差遗漏**（评审者另独立扫描：economics/validate/ACL/锁序/模板/defaults 追点均照 plan；econ 键集、cap v1 五值逐键保留、defaults 变量化锚定等均已核）。

---

## 3. M1 economy 面（非裁决面）抽查

- **C4 fixture 校准（l_eff 1000→4000）**：成立。注释在档给出定量论证——l_eff=1000 时 history est(≈517)+p95 R_o(39) ⇒ bp≈5560… 加 T_used 全量 ≈6380 越过 6000 带沿 ⇒ raw=TrimSchemas，毁灭 C4 的「raw=Normal 而 effective=CompactHistory」对照面；l_eff=4000 ⇒ bp≈1595（带下约 2.4× 余量）。**断言本身未削弱**（base Normal→recovery turn floored CompactHistory/basis=recovery_floor→干净轮消退→单源 false，两向齐全）。根因=fixture 漂移非 SQL 错，与 turn 13 记录一致，裁定正当。
- **G 组驱动仪式**：G1 补齐完整链（②route context_refresh→settle→**recycle**（provider/model GUC 消耗后新后端重设）→重解析（全缓存命中）→单次 advance 达 llm 路由面）；mock noul=0.1 规避默认 reject 带的动机在档；G2 预答信号经 gap join 消费、缺口转 judge effect（慢路原路径）；G5 信封作用域 mock（mock_for_env 排除被 gap 排除的信号）。仪式复杂度源于库内 GUC/mock 机制，非伪链路。
- **H 组**：H1 settle∥翻版阻塞方向+manifest 记旧版；settle∥settle 零 40P01（全新 session 修 claim 抢空问题）；H3 五件 OR REPLACE 签名/ACL 保留+上游回归抽样（DP3 D4/C1/F1 族）；H4 加载边界+纸面计数+自扫描防自噬。
- **economy README 台账**：机制/运维纪律/一页账 v3/偏差台账 7 条（含 hard_window 六键、band_of/tier_rank 单源、events.at 列名修正）齐备；B-DP7-1/B-DP7-2 当时如实记 blocked+PG 实机探针（V3003 复现）——与后续裁决链自洽。头部「M2 阻塞未解裁」为 M1 时点快照，终局 docs 收口时可加一行指针（见 §6 提醒，非缺陷）。

---

## 4. 断言强度抽查（dp1 同标准）

- **恒真/covered-by/伪链路扫描**：全文检索 `check(` 调用，逐条抽查高风险位。命中 1 处恒真占位（P2-1）；P5 有一处被死代码弱化的断言（P2-2）；未发现 covered-by 伪链路（对照组/反事实对照均独立构造：O1-6/O1-7/O5 用同库 actions-off 对照装配，非 prior-turn 比较——恰是裁决 §3.2.5 对断言 7 的告诫）。
- **K1 全链真实性**：schedule（真守卫链）→`v13_claim`→span_source（按 content_hash 从 artifacts 回取 history blob 选成员=worker 契约真形态）→checks→envelope→`v13_resolve_judgments`（mock GUC 单问单批）→decision 单查→verdict→`v13_complete('succeeded')`；effect_done 事件断言在场、语义族零增（P1 聚合+K1 单点双层）。无手捏中间态。
- **O3 二分定界可红性**：`largest_le` 在 [100,200000] 上二分，边界两侧 action 断言（spill↔full 等邻接态不等）——ladder 或 (a) 词表回归任一处错即红。
- **P5 确定性/exact replay**：同输入双调 `v13_assemble_manifest` 字节等（含收缩态）；同态重 settle accepted；`v13_replay` 返回 exact_replay+source_artifact。旧字节回取断言偏弱（P2-2）。

---

## 5. 发现清单与修复清单

**P0：无。P1：无。**

| # | 级 | 位置 | 发现 | 建议 |
|---|---|---|---|---|
| P2-1 | P2 | `v13/summary/test_summary.py:1808-1809` | `check("O3-③: no level skip — prefix rounds all dropped (guard rule)", True)` 为**恒真占位**——标签声称验证不跳级，实际无条件真。实质覆盖存在（O3-① 零 compaction 段+steps==[spill]；guard 规则 3 settle 内执法；O7 recipe 闭集负向拒 [spill,final_trim]），非假绿，但违反「1:1 可红/禁恒真」红线且标签误导 | 改为实断言：对 m_t 直接测试端重算 final_trim 材料 seq 集，断言其与 keepc.tail_seq 之前缀零交集（guard 规则 3 的测试端镜像）；或删行并入前一条标签 |
| P2-2 | P2 | `v13/summary/test_summary.py:2184-2196` | P5 的「旧 history blob 原字节可取」断言被 `... if False else ...` 死代码结构弱化为「source artifact 行存在==1」；注释承诺的字节级回取（旧 blob==收缩前全文）未实际断言。结构上由内容寻址+零 UPDATE 路径保证，风险低 | 改为：取 replay source artifact 的 history 段 content_hash，断言 artifacts 中该哈希行 inline 与消费前 full canonical 的 jsonb_agg::text 相等（或至少哈希==full_sha） |
| P2-3 | P2 | `v13/summary/test_summary.py:379-447` | `prepare_round` 同体**重复定义**（第二定义影子覆盖第一定义）；无害但属残留死代码 | 删除其一 |
| P2-4 | P2 | `v13/summary/v13_summary.sql:880-905`（guard 规则 3） | 防御纵深缺口：action='spill' 时 guard 不拒绝孤儿 `compaction_round_drop` trace 段（仅要求 round_drop/final_trim 时对应 trace 在场、禁 final_trim trace 于非 trim）；validate 也不做 steps↔compaction 段对应检查。装配器结构性产不出该形态，belt 独立信源可再进一步 | （可选）guard 规则 3 补一行：action='spill' ⇒ 零 compaction 段；或 validate 校验 steps 与 compaction 段计数对应 |

**修复清单**：P2-1/P2-2/P2-3 建议随 dp8 turn 或终局收口一并处理（纯测试层，SQL 零改，改后复跑 summary gate）；P2-4 可选（记台账即可）。

---

## 6. 裁定

1. **M1 `57e9205`：PASS。** M2 `ac27750`：PASS。两提交均可作为 dp7 里程碑定案。
2. **dp7 收官**：是——方案 D 全规格（§3.2.0-3.2.6）落地保真，裁决 14 检查点全过，7 偏差全部有据可依且台账在档，无 P0/P1。
3. **可否开 dp8：可。** 两条轻量收口提醒（不阻塞）：
   - 终局 turn 的 loop 级 erratum 悬置清单（HANDOFF §四）应并入 E-DP7-1/E-DP7-2/C-DP7-M1 三条（README 已载原文，清单侧同步即可）；
   - dp8 brief 按 plan 附 A #9 建议消费本 plan §1.4/触点 1 契约（compact_hint flip 门槛），避免双实现；P2-1/2/3 测试层小修可搭 dp8 turn 顺手做。
4. **回退条件核对**：裁决的条件回退（授权被推翻 ⇒ M2 记 blocked/弱化断言假绿）未触发——O1 十项/O2/O3/O5 均以强断言实跑通过，无弱化痕迹。

---

## References

- 裁决：`docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md`（§3.2 实现规格/§3.4 M 组读法/§3.5 检查点/§4 授权登记）
- plan：`docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md`（§3.1/§3.2/§4 A–P 组/附 A #9/#13）
- 实现：`v13/summary/v13_summary.sql`（helper 四件 374-936/assemble v3 944-1699/validate v3 1709-2162/refresh v3 2175-2435/ACL 2439-2467）；`v13/summary/test_summary.py`；`v13/summary/README.md`
- M1：`v13/economy/v13_economy.sql`、`test_economy.py`、`README.md`
- 偏差 #1 法源核验：`v13/filter/v13_filter.sql`（v13_existence_ref :51-65/v13_resolve_judgments 内 :841）
- 背景：`prompt-exports/loop-orchestrate-v13-deep-plans-impl-runs.md` turn 13（L52）；HANDOFF §四 erratum 清单
