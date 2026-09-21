# 第 4 章：决策平面——判断即行，路由即视图

> 前置：第 1–3 章。产出：`v13/decide/decide.sql`（decisions/thresholds/v_routes）（G2 验收）。
> 对照上游：`v12/decide`（G2：批次生命周期、hash 缓存、阈值路由带）。
> 设计对照：`docs/designs/v13-context-on-pg.md` §3.1（动作闭集）、§6.8（v）（triage）。

## 4.1 这一章要做什么

agent 每一步都面临判断：该用哪个工具？继续还是停止？这个结果可接受吗？
常规做法把这些判断埋在 Python 控制流里——`if score > 0.7: ...`。
问题：判断不可见、不可审计、换了模型就漂移、同一问题问两遍花两遍钱。

v13 的立场一句话（v12 的灵魂，保留）：

> **SQL 管算术与顺序，Jev 管语义与判断，LLM 只管生成。**

- 判断 = `decisions` 表里的一行（提问是 INSERT，回答是 UPDATE 一次）；
- 路由 = 带阈值的 **VIEW**（阈值是数据不是代码）；
- 幂等 = `request_hash` 唯一约束（同一问题第二次问，命中缓存直接重放）。

**Jev 是 adapter 不是 schema 绑定**：判断平面的消费者可以是 TypeSafe Jev
（类型化概率）、也可以是普通 LLM 回答同一批问题行——换 provider 零 schema 变化
（Oracle 裁决：alpha 端点不该焊进核心）。

## 4.2 最小形态

```sql
CREATE TABLE decisions (
  decision_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id   uuid NOT NULL REFERENCES sessions,
  question     text NOT NULL CHECK (question ~ '^[\x20-\x7E]+$'),  -- ASCII：判断题英文
  context      jsonb NOT NULL,       -- fold_state 摘要：SQL 算好的现成字段
  answer       jsonb,                -- {choice|score|noul, confidence, ...} 只许 NULL→非NULL 一次
  provider     text, model text,
  request_hash text NOT NULL,        -- (question, context, provider, model) 的 hash
  status       text NOT NULL DEFAULT 'open' CHECK (status IN
               ('open','answered','cached','failed')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (request_hash)              -- 幂等缓存即唯一约束
);

CREATE TABLE thresholds (            -- 版本化路由带：策略是数据
  policy_name text, policy_version int,
  signal text,                       -- 决策信号名，如 route.continue
  band_no int,                       -- 带序
  lo double precision, hi double precision,
  action text NOT NULL,              -- sql/tool:<name>/llm/human/finish/reject
  PRIMARY KEY (policy_name, policy_version, signal, band_no)
);

CREATE OR REPLACE VIEW v_routes AS     -- 路由 = latest decisions × thresholds 的视图
SELECT d.session_id, d.decision_id, t.action, t.band_no
FROM decisions d
JOIN LATERAL (
  SELECT * FROM thresholds t
  WHERE t.policy_name  = (sessions_row.route_policy).name     -- 第 1 章 route_policy
    AND t.policy_version = (sessions_row.route_policy).version
    AND t.signal = d.signal_name
    AND d.confidence BETWEEN t.lo AND t.hi
  ORDER BY t.band_no LIMIT 1
) t ON true;
```

## 4.3 逐段解释

- **`question` ASCII CHECK**：Jev 类判断模型对 CJK 准确率低（v12 调研结论）——
  判断题一律英文，中文只允许出现在 `context` 里。**让建表语句替你做行为约束**（DDL 即策略）。
- **`answer` 只许 NULL→非 NULL 一次**：答案不可改。要修正 = 追加新决策行，
  不覆盖旧答案——审计链完整。
- **`UNIQUE(request_hash)` 是全部缓存机制**：同（问题+上下文+provider）重复请求
  在 INSERT 时冲突 → 状态改 `cached` → 直接读旧行。没有缓存表、没有 TTL 逻辑、
  没有失效器——一行 UNIQUE 买掉一族重试代码（v12 已裁）。
- **`context` = fold_state**：SQL 预先算好的现成字段（开放任务数、预算余量、
  最近结果摘要、**工具目录摘要**——第 6 章）。判断模型只读现成字段，
  不做算术——「不擅长数学/计数」的劣势被分工消解。
- **阈值路由带**：`BETWEEN lo AND hi` 的有序带，逐题比对、永不组合 p 与 1−p
  （概率无恒等式，v12 风险规避）。低置信落 `human` 带——**弃权是路由的一种**。
- **策略版本化**：`route_policy`（name, version）住在 session 行上。
  改阈值 = 插新版本行，旧会话继续用旧版本——第 14 章 redeploy 的地基。

## 4.4 硬性规定与 gate

```text
G2（decide gate）节选断言：
✓ 同 request_hash 二次插入被拒且旧答案可重放（缓存命中不重打 API）
✓ 答案只许写一次；二次 UPDATE 被拒
✓ 非 ASCII 问题被 CHECK 拒绝
✓ 阈值带无缝隙无重叠（gate 扫描 thresholds 校验区间连续性）
✓ 低置信（低于所有带）落 human 兜底带
✓ 路由输出动作 ∈ {sql, tool:*, llm, human, finish, reject}
```

动作闭集只有这六个值。harness 结果（`result_kind` / `delivery_kind`，第 5/7 章）
与 triage 分类（`direct` / `decompose` / `human`，Jev Choice 三值）都不是第 7 个 action——
**信封枚举不是动词，CASE 它的代码才是**；triage 分类只映射到既有动作（4.5）。

## 4.5 triage.v1：信号最小集与优先级阶梯（A20）

一个新 goal 的第一格路由问的是「直接做、拆开做、还是交给人」。这题不新增
动作：triage 分类只**映射到**既有 `llm`/`human` 动作，`thresholds.action`
闭集不变。

**判断模板**（单一 `triage.v1` 模板声明全部字段——`decisions.context` 投影
闭集一次立全，分级只指启用时序、不指声明集）：

| 期 | 字段 | 说明 |
|---|---|---|
| **10a 期**（不依赖目标树，可与信封族同批） | `task_content_hash`、`task_est_tokens`、`user_intent_override`、`has_mutating_hint`、`policy_version`、`explore_evidence_hash`，以及同一模板内声明的五个树字段（值恒 null） | 任务指纹；体量估计（中间带特征，根上不作硬拆）；来自 `goal/override` 事件（第 1 章）；写操作暗示；策略版本；探索证据指纹（无探索则 null）；树字段见 10b 行 |
| **10b 期**（树字段填实值；依赖 spawn 与 goal tree，A17+A21） | `ancestor_depth`、`n_nonterminal_children`、`remaining_turns`、`quota_remaining`、`subtree_reserved`（10a 期已声明为 null 的同一批字段，此时填实值） | 距根深度；未终结子会话数；本会话剩余 turn；预算余量；子树已预留 |

**null 纪律**：`triage.v1` 单一模板在 10a 期就把树字段声明为 null（null ≠ 0——
10a 期阶梯规则 5–6 不点火，没有树信号就不做树判断；10b 期同一批字段填实值；
不存在「10b 追加声明字段」——声明集自始闭全）。「根+无 override 不得
SQL 默认 direct」由 gate 钉死。Jev 首版输出仅 `Choice{direct,decompose,human}` +
confidence，不输出 9 项 rubric（rubric 依赖项不进首版；保留 SQL 可判定项）。

**优先级阶梯**（规范，7 条照录；替代「最高优先」口头语）：

```text
1 空 fold → reject
2 duty_cycle=0 → 不建工作
3 硬安全：depth≥max_spawn_depth 或剩余<min_child_max_turns → 禁 decompose
  （override=decompose 也不得裂变 → human/waiting；禁止静默 direct 假装已拆）
4 override=direct → direct（不经 Jev）
5 override=decompose 且过 3 → llm 编排（工具面含 spawn），不经 Jev
6 ancestor_depth≥1 且无 override → SQL 默认 direct
7 其余（根、无 override）→ Jev thresholds 映射；无/超时/失败 → fail-closed
```

**映射与阈值带示例**：`direct` → 既有 `llm`（单会话直做）；`decompose` →
既有 `llm`（编排，工具面含 `spawn_subsession`）；`human` → 既有 `human`。
分类词统一：Jev `Choice` 三值 {direct,decompose,human}；`explore_then_retry`
是**策略标签**（review 带触发的同会话探索路线，见下），不是第四分类。
分类词与策略标签只作 decision context，永不进 `thresholds.action`：

```sql
-- 例：triage.choice 带——Choice × confidence 落带，action 仍是闭集值
INSERT INTO thresholds(policy_name, policy_version, signal, band_no, lo, hi, action)
VALUES ('default', 1, 'triage.choice', 1, 0.00, 0.60, 'human'),  -- 低置信兜底
       ('default', 1, 'triage.choice', 2, 0.60, 1.00, 'llm');    -- direct/decompose 均映射 llm
```

**fail-closed**：Jev 超时/缺失时 decision 不落行（第 5 章解析相纪律）——
根+无 override → 不得静默 direct，走 `human`；depth≥1 → 默认 `direct`；
零 child。override 排序低于深度/预算硬安全：override=decompose 打穿硬门 →
human/waiting，零 child。

**review 带**：置信度落在 review 带（有答案、置信度居中）时处理有序——
**首次 review（未探索过）→ 允许恰一次同会话只读 explore（细则见下）；
再次 review（已探索过）→ 版本化默认策略行**——种子 = 根 `human` / 子
`direct`，永不默认 `decompose`；改种子 = 插新 thresholds 版本，不改函数
（版本化路由先例，设计 §6.1）。

**explore 细则（首版 = 同会话）**：review 带且根上**未探索过** → 允许恰一次
同会话只读 explore（`llm` + 只读 explore 工具面；不 spawn、不占
`ancestor_depth`/`subtree_reserved`；usage 正常记账）；已探索仍 review 带 →
版本化默认（根 `human` / 子 `direct`，见上）。explore 证据回流 = evidence artifact（可选 `explore/completed` 事件，
第 1 章），`explore_evidence_hash` 变 → request_hash 变 → 新 decision 行
（不复用旧 verdict、不改写 candidate_set_hash）。P2 升级 = 只读 explore
child 走完整 spawn 准入（depth+1，超深不豁免）。

```text
G-triage 族（triage gate）节选断言：
✓ G-triage-action-closed：thresholds.action 仍属闭集；explore_then_retry/
  orchestrate/decompose 永不出现——Jev Choice 三值（direct/decompose/human）
  与策略标签 explore_then_retry 只作 decision context/策略标签，不是第四分类
✓ G-triage-review-band：再次 review（已探索过）→ 版本化默认策略行——种子 =
  根 human/子 direct，永不默认 decompose
✓ G-triage-explore-once：根上 review 带且未探索过 → 恰一次同会话只读 explore
  （零 spawn、不占 ancestor_depth/subtree_reserved）；已探索仍 review 带 →
  版本化默认（根 human/子 direct）
✓ G-triage-10a-null-tree：10a 树字段值为 null 不点火（null≠0）；根+无
  override 不得 SQL 默认 direct（走 human）；超时/缺失 decision 不落行——
  根→human、depth≥1→direct、零 child；override 打穿硬安全 → 零 child+human/waiting
✓ G-triage-explore-depth：超深（depth≥max_spawn_depth）零 explore child；
  首版 explore 同会话（零 spawn、不占 ancestor_depth/subtree_reserved）
✓ G-triage-evidence-hash：explore_evidence_hash 变 → request_hash 变 →
  新 decision 行；不复用旧 verdict、不改写 candidate_set_hash
```

## 4.6 检查点练习

1. 加 `v_fold_state(p_sid)` 函数：聚合 sessions/events/decisions 成判断吃的 context
   jsonb（开放任务数、turn 余量、最近 effect 状态）。断言纯函数：同输入同输出。
2. 造一个两信号决策（`route.next` + `risk.check`），写组合路由视图：
   risk=reject 时无视 route.next 直接 reject。体会「路由是视图」组合的成本是零。
3. 破坏性实验：把阈值改成有缝隙（lo/hi 不连续），gate 应在 thresholds 校验断言上红。

## 4.7 回到 vN 对照

- `v12/decide/test_decide.py`：批次生命周期 + hash 幂等 + 路由带的全部断言。
  v13 的减法：`decision_batches/jev_questions/jev_decisions` 三表压成一张
  `decisions`（provider 无关形态，Oracle 裁决的形状）；阈值表原样。
- v8 没有独立决策平面——判断藏在 step 决策与 LLM effect 里。
  v13 把「判断」升为一等行，这是 v12 对底座的最大贡献。

## 4.8 内在合理性：前因后果

**作用力。** 先列事实——它们关于运行环境，不关于任何设计偏好：**判断调用
有成本**（外部 IO，按次计费、按延迟等待），且**同题答案可缓存**——
同一个 (question, context, provider, model) 再问一遍答案不变，重问即
纯浪费。**概率输出无恒等式**：置信度不满足任何算术定律，组合 p 与
1−p 的结果不可靠，唯一可信的操作是逐题定界。**CJK 输入对判断类
模型的精度劣化是可测事实**。**阈值是要反复调的**，而阈值写在代码里
意味着每次微调都要重新部署。**外部 IO 与事务无原子性、超时≠失败**：
判断请求可能失败，可能超时后其实成功；进程可能在任何指令边界崩溃。

**推导。** 这些力逼出本章的三张对象。同题可缓存 ⇒ 判重可以只是一条
`UNIQUE (request_hash)`：**声明式执法**让 INSERT 冲突即缓存命中，
不需要 TTL、不需要失效器、不需要应用层先查后插。判断有成本且要可
回放 ⇒ 判断必须是**行**（`decisions`）：提问一次 INSERT、回答一次
UPDATE，`answer` 只许 NULL→非 NULL 一次——**SELECT 即审计，
重放即读旧行**。概率无恒等式 ⇒ 路由只能**逐题比对带**（`confidence
BETWEEN lo AND hi`），永不组合置信度做算术。CJK 劣化 ⇒ 判断题一律
英文、由 CHECK 在 DDL 层执法——**让数据库替你拒绝错误输入**，而不是
依赖每次调用前的自觉。阈值要常调 ⇒ 阈值是**数据不是代码**
（`thresholds` 插行即生效），路由是**视图**——视图是计算不是存储，
策略改动零迁移、可版本化。

**反事实。** 把判断降级为 Python 控制流（`if score > 0.7: ...`），
失败时序：第 1 步，turn 3 与 turn 7，agent 两次问同一个「继续还是
停止」——没有 request_hash 判重，两次都打外部 API，同题重问，计费
翻倍；第 2 步，周二换 provider，同样的 fold_state 走出不同分支——
没有行即没有比对基准，行为漂移无人察觉；第 3 步，事后复盘问「当初
为何落 human」——判断留在已退出的进程内存里，不可 SELECT、不可
重放；第 4 步，调阈值要改代码重新部署，部署窗口内崩溃随时可在任意
指令边界发生，新旧行为交错且不可审计。若保留表但去掉 UNIQUE：判重
落到应用代码，先 SELECT 再 INSERT——两个并发会话在两步之间都能
通过检查（**行锁只在事务内**，应用层检查挡不住竞态），缓存随之膨胀
成一族 TTL/失效/清扫代码，还要各自兜「超时≠失败」的边角。

**被拒替代。** 其一，**配置文件阈值**：文件改动同样要重新部署，且
无法按 session 挂版本——旧会话被迫跟随新阈值，策略不可回放；在
「阈值是数据」的力下严格更差。其二，**专用规则引擎**：在数据库旁
再立一个有状态组件，判断结果落在库外——审计要多查一个系统，回放
要复刻引擎内部状态，而它承担的职责本可由一张表加一个视图完成。
其三，**把判断合并进生成调用**：省一次调用，但答案混在生成文本里
——同题重问无法命中缓存（没有独立的 request_hash），也没有干净的
confidence 可落带——重问照付全价，路由失去输入，两头都亏。
