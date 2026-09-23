# v13 periphery (DP8) — latches / canonical render / ForkPrefix·shadow / intent soft gate

第 14 号 SQL 文件（`SQL_LOAD_ORDER` 纯末尾追加），v13 外围 P1 平面：
latches（INSERT once + admission + F13 并发回读）、canonical render 函数族
（wire/receipt/render，wire 不落库）、ForkPrefix spawn 壳（fork +
validate-spawn + cache probe）、shadow 即查询（observe/streak，flip=人审）、
触点 5 意图软门控（v1 仅记录面）、generation 真值接管（OQ2 会话级 latch
冻结）、**token 十一键谱恢复**（DP7 键谱回归修复，plan 附 A #1）。

- 权威：`docs/plans/v13-dp8-periphery-p1-plan-2026-09-20.md`（§3.1→§3.8
  即本目录 SQL 的物理顺序）。
- Gate：`uv run python v13/periphery/test_periphery.py`（退出码 0 = 通过；
  A–I 九组，128 checks）。提交前 DP1–DP7 全部十三个 stage gate 在各自前缀库
  复跑（AGENTS.md 前置条件 1；上游库不加载本文件，结构性零影响——gate I5）。

## 运维纪律（README 必记六条）

1. **fork 子会话 v1 = spawn/replay 壳**：可读（`v13_replay` 逐字节）、可审计
   （`forked` 事件）、可对账（首个 llm 走 cache probe）；**不可推进 turn**
   （advance/route 的 events 读面未改写——会话树读穿透/预算继承/turn-running
   是激活缝，plan OQ4/§1.4/附 A #3）。误用时子会话 canonical_state 为空、
   装配产出空 history 的合法 manifest——非静默错数据。`files_cutoff` 冻结
   （v2 对齐 A12）同为立法侧登记，落地归未来 R0a。
2. **llm worker 契约扩记**：request 构造 = `v13_render(sid)::text`（jsonb
   canonical 序列化）；result 在 DP7 契约（usage/model）之上单侧扩两键
   `wire_digest` 与 `usage.cache_read_input_tokens`（缺省=no-op 无对账面，
   非错误；DP7 附 A #3 同款「result 增键零上游改动」先例）。
3. **generation / system blocks 真值运维流程**：机制已落地（v2 行结构 +
   system_block blob 通道 + 会话级 latch 冻结），值仍 mock。翻 v3 仪式 =
   ①owner 经 `v13_blob_land(eff, to_jsonb(text), 'system_block')` 落系统块
   正文；②计算 digest（空表 `'-none-'`；否则
   `sha256(jsonb_agg(blob inline ORDER BY 列表序)::text)` hex）；③INSERT
   generation v3（列表 + digest）+ 双 UPDATE 翻 active；④**必须同批补
   `v13_pricing` 行**——新 provider/model 无定价行时 economics.er 的
   e_base 为 NULL，validate V3007 fail-loud（gate C2 fixture 实证）。已 pin
   会话不受影响（latch 冻结，ch14.5 安全绳，gate C2）。
4. **flip = 人审仪式**：`v13_shadow_streak(name, shadow_version)` 查询就绪
   度（连续零 diff ≥ `shadow_flip.min_zero_diff_turns`=10 才 ready）；翻版 =
   INSERT 新版 + 双 UPDATE 翻 active（身份/token 追动链自然触发，gate C4/G6
   同链）；auto-flip 不存在（§6.7 在线 learned policy 拒绝项；源码断言
   gate G6）。观察面经 `shadow_watch.targets`（词表封闭
   {render_policy, assemble_manifest}，带外 V3008）；tier/hint flip 的证据面
   归 DP7 校准流程——两证据面并行不混。
5. **intent_gate 激活三前提**（chunk sections 落地前不武装，
   `actions_enabled=false` 仅记录面）：①manifest 可选段词表存在；②确定性
   收窄规则同批定义；③needed 不变性断言前置满足。v1 执法：STABLE 纯读 +
   源码零 `typesafe_ask` + judgment_calls 零增量（gate H6 三重）。
6. **probe 容差键校准**：`cache_probe` 策略行
   `{tolerance_ratio, min_tokens}`；差额
   `|actual − est| > max(est×ratio, min_tokens)` 落 `audit/cache_probe`
   事件（basis=estimate_gap / wire_mismatch 可叠加）。容差外噪声多 → 翻版
   收紧；事实禁用 = tolerance 1.0（行仍在）。**est 语义实证**：稳定前缀 =
   已落地 blob 的段（system+tools+churn=0 段 body）——首次装配时当前材料
   blob 尚未落地故不计入（新字节本就不会命中缓存，语义自洽）；对账锚 =
   `effect.result->context_artifact_id`，免疫 complete 后换指针（gate F6）。

## 与 DP7 的契约关系声明

**触点 1（压缩 hint）纯消费 DP7**（plan 附 A #9 / OQ6）：hint 生产、记录面
（`economics.compact_hint`）、硬类保护、flip 证据门槛全部沿用
`docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md` §1.4 与其实现
（v13/economy、v13/summary）；本 stage **零 hint 代码**。本 plan 的 shadow
仪器只覆盖 {render_policy, assemble_manifest} 族——tier 动作 flip 的双跑
在 actions off 时恒等无信息量，其证据面归 DP7 校准流程（gate G4 词表
执法即此分工的消费侧确认）。

## 实施偏差/实证台账（对照 plan）

| # | 项 | 处置 |
|---|---|---|
| 1 | 换体七复制源 | 按「复制源=加载序最新形态」规则取 **13 号终态**（plan 表格"12 号"为计划冻结时点快照——13 号 refresh v3 本体即 12 号 v2+belt）；assemble/validate 同理取 13 号 |
| 2 | refresh 锁集 | 13 号现六名（含 M2 增的 summary_accept）+`render_policy`=**七名**；plan 字面六名若照抄会删 summary_accept 削弱 DP7 belt，按「同缝扩展」意图合并 |
| 3 | 换体八 blob_land | kind 词表扩的实现形态=签名 2→3 参（`p_kind DEFAULT 'context_section'`，既有调用点零改动）⇒ DROP 旧两参形态再建；墓碑注记同 latch_digest；system_block 无 partial unique 索引→直插，自证 CHECK 原样适用 |
| 4 | goal_hash 草案笔误 | `SELECT … INTO v_row.content_hash`（record 字段不可作 INTO 目标）→ 标量变量；语义零变化（plan 自注「实施期机械自检」类） |
| 5 | shadow_streak 列名 | events 时间列= `at`（草案 created_at）；同事务时间戳 tie 由 fixture 显式 `at` 错开 |
| 6 | intent_gate 对齐加载态 | thresholds 实列名 `policy_name/policy_version`（草案 route_policy_*）；DP5 分段器返回**纯文本段数组**（单类游程）⇒ CJK 判定=段首字符码位（区间常量镜像 DP5 同组） |
| 7 | PG18 词法/优先级 | render_wire marker 首字面量 `'['::text` 消歧（`[` 开头字面量在 PL/pgSQL 赋值语境被按 JSON 解析）；`||`/`->>` 同层左结合 ⇒ `(s->>'k')` 括号 |
| 8 | A5 扫描口径 | 新 RAISE 全 V3008（**34** 检查点）；全文 RAISE/errcode=104/97 纸面钉死（裸 7 条=机械复制体逐条在案：context_required 每输入 ×4+refresh 入口 ×2+blob_land ×1；validate 的 RAISE 全部带 ERRCODE、不计入 bare） |
| 9 | A12 files_cutoff | **不落列**：v2 节自述「执法侧立法、换体登记=不适用」，A–I gate/§4.2/README 必记均无它，v13 无 file pointer/epoch/git tips 数据源；激活缝随 R0a（SQL 内注记+本条） |
| 10 | latch_fire/fork REVOKE PUBLIC | plan §3.8 草案 REVOKE 清单遗漏两 DEFINER 面（默认 PUBLIC 可执行）；gate A6 负向抓获后补 |
| 11 | invoker 链 ACL 补全 | manifest 既有授予使 resolve/recall 可执行 prefix_identity/context_required/render（INVOKER）⇒ 子函数（generation_effective/latch_digest/ident_ver/render_wire/render_section_body）EXECUTE 随家族补齐三角色 |
| 12 | est 语义实证 | 稳定前缀=已落地 blob 段（见纪律 6）；F 组 fixture 两步 settle（落 blob→latch 追动→重 settle）构造 est∈(1024,5120) 窗 |
| 13 | generation 翻版×pricing 耦合 | 见纪律 3（er 形状 fail-loud 实证） |
| 14 | I6 fixture 对齐 | manifest 候选带 `decision_id:null` 增键 ⇒ 比较剥键；decision 行需 64hex request_hash + 真实 template 行（epoch_fill 触发器执法） |
| 15 | I4 形态 | in-test=装载切片（恰 14 文件）+上游对象在场断言；十三 gate 前缀库复跑是 gate 外的 AGENTS.md 仪式（本 README 头部与提交记录在案） |
| 16 | 纸面计数 | 顶层语句 40（附 B 草案 36/37：+DROP 换体机械件、+invoker 链补全 GRANT、+外围行守卫块等实施期形态）；函数 23 定义零重复；`$$` 配平 |
| 17 | G3 shadow 差异面 | 差异经 budget 真咬（64 tokens 装箱裁段）构造；同值翻版在小组会话下投影恒等 |
| 18 | C6 负向 | 毁 generation 行负向需**未 pin** 会话（pinned 会话 latch 兜底不读活动行——OQ2 语义的正面证据） |

## 教程映射

§13 第 14 章指针（正文零改动）：14.3 三件套=fork/validate-spawn（E 组）+
cache probe（F 组）；14.4 三种回放=E2；14.5 三列不可变/latch 进身份/redeploy
安全绳=A4/C2；14.6 ForkPrefix/回放七条=E 组 v1 断言，会话树五条=激活缝；
14.7 练习 1/2/3/4=E8/E4·E5/F·E2/E7。
