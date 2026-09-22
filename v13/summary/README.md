# v13/summary — DP7 M2:摘要链执行与消费平面

> **状态（2026-09-22）：M2 交付。** 本 stage 是 dp7 plan（`docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md`）的第二个里程碑；实现按 B-DP7-1/B-DP7-2 oracle 三角裁决（`docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md`，方案 D）执行——裁决与 plan 冲突处以裁决为准，非冲突面照 plan。gate：`uv run python v13/summary/test_summary.py`（exit 0 = 通过）。

## 交付面（第 13 位纯末尾追加）

- `effect kind` 扩 `context_summary`（append-only 词表；`v13_complete` 走通用 CAS 分支，零语义事件——DP1 #20）。
- `effect_attempt_cap` v2（全六键；v1 五值逐字保留 + `context_summary:2`）。
- `summary_accept` 策略行（预算包/验收带/CJK/检查参数；`packs_reserved=1`）。
- `summary_fidelity` noul 模板（**epoch 显式 `pre-finalize`**——列默认是 `pre-bind`，B-DP7-2 裁决 §3.4 fixture 纪律；三步仪式 draft→内容行→freeze）。
- `judgment_defaults` 追点 `summary_accept`（missing/timeout/review 三态全 exclude——fail-closed，§6.4-4）。
- 函数六件：`v13_span_digest` / `v13_summary_checks` / `v13_summary_envelope` / `v13_summary_verdict` / `v13_summary_schedule` + 单源材料四件（`v13_history_action` / `v13_history_section_material` / `v13_summary_section_material` / `v13_history_belt_guard`）。
- OR REPLACE 三件再跳：assemble v3（summary 段+history 收缩+回退链+economics.summary 块）、validate v3（kind=summary/compaction、transform 词表、belt 跨字段执法）、refresh v3（双模式 belt，见下）。

## 裁决授权：第 8 处 OR REPLACE（refresh 换体）

E-DP7-1/E-DP7-2/C-DP7-M1 三条 erratum 原文（裁决 §4；plan 冻结不改）：

```text
E-DP7-1(授权漏计,plan 冻结不改):
  plan §1.1「七处 OR REPLACE」与不变量 9、§3.2(iii)、OQ2 步 4、O1 冲突:
  后四者要求 settle 落 summary blob 并在 adopted/回退时改 history 段字节,
  唯一落行点=v13_refresh_context 体内 v13_blob_land(lander 零运行角色,
  无第二合法落行面)。实施侧授权文件 13 对 v13_refresh_context 做第 8 处
  OR REPLACE(文件 13 第 3 处)。增量仅限:锁集增 summary_accept(一行)、
  (可选)context_summary 行 FOR SHARE、history belt IF 包裹(IF 臂=economy
  原文逐字含 V3003;ELSE=单源材料+guard+V3007)、tools belt 后 summary belt。
  未变形路径(actions_enabled=false 及 action='full')与文件 12 字节同路径。
  授权链:控制器核实+用户授权 oracle 裁决(2026-09-22,
  docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md)+L4 检查点 1-14。
  若本授权被推翻:回退=summary 消费延期(M2 记 blocked/deferred),
  不得弱化 O1/O3 断言假绿。

E-DP7-2(belt (ii) 首版限制的显性化,plan 冻结不改):
  DP3 OQ4 已把真窗口让渡 DP7(「真窗口=新 transform 名+新策略版本行,
  首版 verbatim」)。action='full' 时 (ii) 仍为 history 段=sha256(canonical
  messages 全文),原文语句与 V3003 逐字保留;action<>'full' 时 (ii) 改为
  「段字节=v13_history_section_material 对 canonical 的确定性投影,且
  v13_history_belt_guard 用 canonical 独立复核(尾段后缀/回退结构像/span)」。
  (i) 不放宽:blob_land 返回值与段 content_hash、payload_ref.content_hash 恒等。

C-DP7-M1(M1 断言文字澄清,plan 冻结不改):
  M1「round1 检查失败」与「decision 行数恰 2」互斥(检查失败不调 Jev ⇒
  round1 无 decision 行 ⇒ 全程恰 1 行)。gate 按 M1a(检查失败路径,1 行)/
  M1b(验收 reject 路径,2 行)/M1-neg(同文本重验,零新增)三行读法实现;
  模板种子 epoch 显式 'pre-finalize';两轮间 provider/model GUC 恒定。
```

### refresh v3 的 diff 允许清单（对照 economy 加载态；gate L4-2 文本执法）

相对 `v13/economy/v13_economy.sql` 的 refresh，允许且仅允许四类编辑（gate 以 difflib hunk 逐项断言）：

1. 策略锁 `FOR UPDATE` 的 name IN 集合加 `'summary_accept'`（一行内增名）；
2. adopted `context_summary` effect 行 `FOR SHARE`（pricing 锁后、形状守卫前；零行合法）；
3. history belt 包 IF：**IF 臂 = economy 原文四行逐字**（含 V3003 文案；仅绑定名 `v_hist`→`v_full`）；ELSE = 单源材料哈希比对 + guard + blob_land（全 V3007）；
4. tools belt 后、`v13_artifact_land` 前的 summary belt（不变量 9：重算材料恒等才落行，零信 effect 自报哈希）。

其余（入口 kind/fence 校验、锁序骨架、形状守卫全文、装配-校验-inline 调用序、complete CAS、tools belt 全文、artifact_land、result 补挂、sessions 指针、返回值）economy 加载态逐字。调度条件用哈希相等而非读 action：未变形（含 actions off）⇒ 全文哈希==段哈希 ⇒ 走 IF 臂 ⇒ **v1 生产与文件 12 字节同路径**（gate L4-3 断言）。

## 动作层（actions_enabled 门控）

`v13_history_action` 封闭词表 `full | tail | spill | round_drop | final_trim`：

- actions off / 无需压缩（且非硬窗口/E(r) 判定）→ `full`；需压缩=actions on 且（硬窗口 bp≥10000 或（r 已知且 effective tier≥CompactHistory）——r_unknown 只按硬窗口，OQ5）。
- 需压缩 且 可消费 adopted summary → `tail`（keep_tail_turns 尾段，transform 仍 `verbatim`——裁决 §3.2.2；summary 段 `summarize`）。
- 需压缩 无可用 summary → 固定梯「装得下就停」：spill（tool/result 正文→stub，引用 event 的 source_effect_id）→ round_drop（最老完整可压缩 round，逐 round 记 compaction 段）→ final_trim（裁到只剩最后一个 round）。停机判定=动作后 est 重跑三桶（与 material 函数逐字同一算法）。

可消费 adopted 谓词：最新 succeeded `context_summary` 行（created_at+effect_id 打破平局，禁 now()）+ `result.adopted=true` + **request 冻结的 `span_digest` == 当前 canonical 前缀 digest**（span=前缀消息级 sha256 序；span 一律取 request 冻结值，不读 result 副本）。前缀=protected tail（keep_tail_turns 个 user turn）之外的消息。

### 回退链与硬类保护

- compaction 段：kind=`compaction`（多段时 `compaction:<8hex>`，多段化规则通用），transform `{applied:false, reason: compaction_round_drop|compaction_final_trim}`，payload_ref 与段哈希恒等（validate v3 执法）。被丢内容的 blob 不落行（与 DP3 skipped 段同纪律——skipped 段从未物化；正文仍可从 canonical/events 回取）。
- **goal/tools 段永不受梯、永不入 compact_hint**（gate O5 字节不变断言）。
- 三级不跳级由 `v13_history_belt_guard` 规则 3 执法（final_trim 在场 ⇒ 前缀 round 已全部被丢）。
- economics.summary = `{intent, consumed, fallback}`（键集封闭；validate v3 执法）。intent 在 actions on+应压缩+前缀非空时在场（含 pack_ok=策略在场∧session asks<cap——日闸留在 schedule 运行面，装配零时钟）；fallback 在未消费且有解释时在场（steps 允许 `[]`——O2 的 span_stale 在 action='full'/IF 臂下亦可观测），basis 词表 `{none,no_budget,no_effect,checks_failed,rejected,cjk,span_stale}`。

## 驱动契约（turn 静默期）

1. turn 的 llm effect 终态、零活跃 effect 后，驱动调 `v13_summary_schedule(sid)`（纯 SQL，route 登录）——任一守卫不过=no-op RETURN NULL 零事件（single-active/intent 在场/调度闸+花费闸/spans 仍在 canonical）。
2. prepare worker 双连接（route 主：claim→读 span 正文→外部 LLM 生成→`v13_summary_checks`；resolve 副：`v13_summary_envelope`→`v13_resolve_judgments(env,1)`→按 (signal, context 等值) 单查 decision_id→`v13_summary_verdict`）。新消息先到则 turn 等待（有界：≤packs×(1 gen+1 Noul)；一页账 v3 见 economy README）。
3. worker 读 span：按 request.span 的消息级哈希从 history blob（artifacts 按 content_hash 回取）选成员——粒度即消费谓词的同一单源。

### worker 契约

- `context_summary` complete 的 result 携 `{rounds:[{body,content_hash,checks,decision_id,verdict}], adopted, basis}`；**自报 content_hash 不被任何消费面信任**（settle 重算材料哈希恒等才落行——不变量 9；gate O1-3 故意填错自报值断言）。
- llm result 应携 usage+model（economy P0-1——分位桶谓词读 result 侧）；mock 仅测试。
- 检查失败不调 Jev（K2）；重生成=新 LLM 调用非重问（round 2 新文本⇒新 ctx⇒新 request_hash⇒新 decision——M1b）；packs=2 封顶（M2）。

## signal 命名空间与 epoch

- 验收 signal = `summary::<span_digest 64hex>`（新保留前缀；零 `corpus_exists`/`chunk::` 碰撞——DP6 不变量 2 纪律）。
- decisions epoch 由模板属性回填（`trg_decisions_epoch`）：summary_fidelity 的 decision 全部 `pre-finalize`（§6.1「候选/摘要验收等动作承重判断」原文归类）。**模板种子行必须显式写 epoch='pre-finalize'**（列默认是 'pre-bind'）。
- judgment_defaults 追点后 `v13_judgment_defaults_check` 天然过（点形状 {missing,timeout,review} 恰等）；翻新纪律：新版本必含全六键 cap、全点集 defaults。

## 锁序（ops 更新）

settle 全库锁序：`sessions → tools_meta → 策略活动行（六名，含 summary_accept，name 序）→ v13_pricing active（dim 序殿后）→（可选 context_summary 行 FOR SHARE）→ effects（complete CAS）`。**翻版操作（ops）同序取锁**——summary_accept 翻版与 settle 并发时按此序排队（gate H1-type 断言阻塞方向）。

## 与 plan 的实施偏差（逐条列理由；裁决红线优先）

1. **验收信封十二键（plan 十键 + `goal_hash`/`candidates`）**：plan P1-5 的原则是「信封键集逐键对齐 resolve 实际消费面」；加载态 resolve（文件 10 filter 形态）尾部 remaining 计算无条件经 `v13_filter_gate_open`/`v13_filter_bodies_present` 消费 `goal_hash`（64hex）与 `candidates`（array），缺键即 V3006（gate L1 断言十二键）。plan 写「十键」时的参照系是 DP2 原文；对齐**实际加载态**是 P1-5 原则的正确延伸。
2. **compaction 段 kind=`compaction`（plan validate v3 词表只 +summary）**：被丢 round 的独立段不能是 kind='history'（多段化规则会把主 history 段改名为 `history:8hex`，冻结的 refresh belt 按 `section_id='history'` 取段即断——裁决 §3.2.4 允许清单禁止改 belt），也不能是 kind='summary'（裁决 guard 规则 3「回退 manifest 无 summary 段」+ validate 双向一致「consumed NULL ⇒ summary 段数 0」）。新增 kind 是 DP3 契约 #7「增 kind 只加行不改结构」的形态。
3. **fallback 在「未消费但有解释」时在场（steps 允许 `[]`）**：裁决 §3.2.5 断言 10 要求 span_stale 时 history 哈希回全文（IF 臂）且 basis='span_stale' 可观测——若 fallback 仅在梯运行时在场，action='full' 时 basis 无处安放。steps=`[]` 仅出现在 basis≠'none' 且 action='full' 的组合（validate 词表执法）。
4. **O4 的 plan 措辞「reason='summary_unavailable'」落在 economics.summary.fallback.basis='no_budget'**：四新 reason 在 validate 词表内（手构造正向可过），v1 装配不产 skipped summary 段（guard 规则 3 与 validate 双向一致结构性排除）；预留失败的装配半边由 fallback trace 承载。
5. **economics.pressure/tier/er 决策记录用全量候选基面（fcls/ford），装箱/段产额用动作后基面（cls/ordered）**：动作层决策必须以压缩前压力为依据（否则 J1 的 intent 在收缩后消失）；action='full' 时两基面值恒等（材料相同）。这是 §3.2.2「sec_src 走单源材料」的结构推论，非词面增删。
6. **J4 的 plan 措辞「active manifest 段 hash 集」读作「当前 canonical 消息哈希集」**：target_span 粒度=前缀消息级哈希（裁决 §3.2.1(a) 消费谓词的同一单源），消息级哈希不在 sections 的 content_hash 集内；按 canonical 存在性检查保持「span 已变则等下一版 intent」语义。
7. **L5 的 plan 措辞「decision 进 judgments.final_action='include'」**：DP6 装配的 judgments 消费集只收 corpus_exists+chunk 过滤候选；v3 增量把 consumed 的 summary decision 并入消费集（final_action='include'，epoch 随行）——plan L5 的字面要求。

## 运维注记

- **激活 actions 的前置**：`l_eff_tokens` 必须大于 R_o 冷启动预留（8192）——否则 effective_budget 归零、三桶全空，settle 在动作层全梯耗尽后仍不 fit 时 history 段会被 budget-skip，guard 规则 3 将 V3007 拒绝（fail-loud，不静默）。本地校准流程见 economy README。
- **effect_attempt_cap 翻新纪律**：新版本必含全六键；降 cap 需清场（DP1 M1-9 同族）。
- **summary_accept 翻新纪律**：受保护元素抽取规则变更=新 transform 名+本行新版本（DP3 契约 #9）；CJK 校准 fixture 落地前 mode 恒 `reject_only`（翻 `calibrated` 是数据动作，gate N3 演练后即回滚）。
- **放弃分支措辞纪律**：「零新增 Jev 调用≠零成本」——已超时/失败的调用可能已计费（§6.4-8；gate O6 断言口径=零新增 judgment_calls 行）。
- exact replay：收缩不写 canonical、不 UPDATE 旧 artifact——旧 history blob（收缩前全文）原字节永可回取（gate P5）。
- 与 DP8 的缝：render_policy/latch 零耦合（economy README §1.4 同源）。
