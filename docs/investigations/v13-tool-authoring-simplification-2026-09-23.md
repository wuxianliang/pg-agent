# v13 工具编写复杂度调查与简化方案（2026-09-23）

> 起因：`docs/tutorials/v13/how_to_make_a_tool_for_v13.md` 交付后用户反馈——教程本身就证明
> 「工具设计很难理解」。本文调查复杂度的真实来源，回答：**是 tool 机制要改，
> 还是增加一个高层次的结构（如某些 agent 项目「函数就是工具」）？**
> 方法：逐层定性复杂度（本质/半本质/偶发）→ 对照「函数即工具」谱系的取舍 →
> 分层方案空间与推荐。所有事实带锚点，可复核。

---

## 0. 结论摘要（先给答案）

1. **机制主体不该换。** 两档目录、effect 账本、claim/complete、守卫、revision/探针——
   这些复杂度是 v13 的产品本身（崩溃安全、可审计、否决带、fail-closed），
   十二轮裁决反复确认过。「函数即工具」的**执行语义**（模型自由选工具产参数、
   无带式否决）与 v13 的存在理由直接冲突，换掉等于放弃 v13。
2. **该补的是「编著面」（authoring plane）**——而且仓库已有两个雏形
   （v13.1 的 manifest→目录编译器、demo 的 harness/driver），只是没推广、没转正。
3. 复杂度真正集中的两处，分别对应两个动作：
   - **参数机制太重**（双问+双带+策略版本五步舞）→ 有一个值得立项的**机制收敛**
     （param 随 tool 选择一次判，DP11 级），它同时解决一个实测的**性能膨胀问题**（§1.3 F2）；
   - **运行环境样板**（hub 循环、mock 相位、版本指向）→ **纯编著层封装**即可消掉，零机制变更。
4. 一个必须修的小机制脚枪：**session 默认策略版本是 DDL 常量 1**，注册带参工具后
   忘了显式指向新版本 = 参数**静默丢失**（§1.3 F1）。

分层推荐（详见 §3）：

| 层 | 内容 | 机制变更 | 优先级 |
|---|---|---|---|
| Tier 1 | `v13_register_tool()` + `v13/toolkit.py`（hub 框架）+ `drive_turn()` 测试助手 | 零 | 必做 |
| Tier 2a | 默认策略指针（消 F1 脚枪） | 小 | 必做（与 Tier 1 配套） |
| Tier 2b | 参数带缺省值（param/stated 族 fallthrough） | 小 | 可选（与 Tier 3 二选一） |
| Tier 3 | param 随 tool choice 一次判（消双问+解膨胀） | 中（DP11 级裁决） | 建议立项 |
| Tier 4 | LLM 原生 tool_calls 替判断面 | 大（v14 级） | 不做（DP10 §7.1 已裁推迟） |

---

## 1. 现状调查：复杂度到底在哪

### 1.1 教程的九节 ≈ 作者要懂的九层，逐层定性

| # | 教程节 | 知识点 | 定性 |
|---|---|---|---|
| 1 | 两档 kind | 外部 IO 有无定档位 | **本质**（不变量 4：外部 IO 无事务原子性） |
| 2 | 目录行语法 | `::` 禁用/ASCII/options=object/先函数后 INSERT | 半本质（signal 身份设计，可守卫代劳但要知道） |
| 3 | 守卫行为 | 写入时校验/fail-closed/启用时复验 | 本质（DB 执法是产品） |
| 4 | 参数五步舞 | param_spec→双信号→双带→**策略新版本→复制→追加→freeze→session 指向** | **半本质+偶发**（见下） |
| 5 | revision/stale | 任何目录 DML→bump→在途信封弃批 | 本质（TOCTOU 纪律），但作者只需一句结论 |
| 6 | worker 合同 | claim/renew/complete/requeue/重启纪律/幂等/unknown | 本质（at-least-once 的代价），但**样板可框架化** |
| 7 | 测试相位 | GUC 两级+mock 覆盖表+remaining tripwire | **偶发**（没有声明式助手） |
| 8 | 部署形态 | 零 SQL vs SQL_LOAD_ORDER/源码扫描 gate | 偶发（约定，可文档化+工具化） |
| 9 | 提交纪律 | AGENTS.md | 与工具机制无关 |

**关键观察：无参工具在 v13 已经接近「函数即工具」。** sql 档 = 一个函数 + 一行 INSERT
（§2.1 两件东西）；tool 档 = 一个 Python 函数 + 一行 INSERT + hub 里一个分派条目。
真正的重量全部压在**带参数**的工具上，和**运行环境**的知识上。

### 1.2 参数机制为什么这么重（解剖五步舞）

带一个参数的工具，现状要写（`how_to_make_a_tool_for_v13.md` §4.3）：

```
① INSERT v13_route_policies ('default', N+1)        -- 建 draft 版本
② INSERT thresholds SELECT ... FROM v1              -- 逐行复制全部种子带
③ INSERT thresholds × 2（param::/stated::）          -- 追加参数带
④ UPDATE ... state='frozen'                          -- 冻结
⑤ 每个 session 显式指定 route_policy_version=N+1     -- DDL 默认是常量 1！
```

每一步的存在都有裁决理由（`v13_core.sql:449-473` 注释链）：

- 带**版本化+冻结**：turn 5 #35——「同 (name,version) 永远同带集」，版本=内容地址，
  七键探针复核才完备；在飞 turn 不被路由语义变更突袭；
- 带**只能进 draft**：turn 6 #39——封死「冻结后追带」的并发窗口；
- session **只能引用 frozen**：turn 5 #35——不消费浮动语义。

即：五步舞是 **TOCTOU/审计纪律的代价**，不是疏忽。但对工具作者来说，
这是纯机械劳动——**机械劳动就应该被一个函数吃掉**（§3 Tier 1）。

param 双问（`stated::` noul + `param::` choice）是 v12 血统
（`v12/turn/v12_turn.sql:296-322` param_spec 原样移植），语义是**反幻觉 grounding**：
只有用户陈述过（stated 命中 pass 带）才收参数值，否则省略、绝不猜值。
这是半本质复杂度——有真实价值，但**实现形态可以收敛**（§3 Tier 3）。

### 1.3 两个实测问题（不只是难，还有脚枪和性能）

**F1（静默失败脚枪）：session 默认策略版本是 DDL 常量 1。**
`sessions.route_policy_version int NOT NULL DEFAULT 1`（`v13_core.sql:22-24`）。
注册带参工具→新带在 v2→**新 session 若忘了显式指定 v2，参数带永远不命中**
（`v_routes` 对 thresholds 是 INNER JOIN，无带=不命中）→ 参数被静默省略，
worker 收不到参数，**全程零报错**。DP10 计划被迫把「session 指定 v2」写成不变量 5
——用纪律补 DDL 的洞，每个后续使用者都要重新踩一遍。

**F2（性能膨胀）：needed 问数随目录参数线性增长，且每轮全量重问。**
`v13_needed_judgments`（`v13/resolve/v13_resolve.sql:98-128`）对**每个 enabled 工具的
每个参数**发射 2 问。判断哈希含 ctx（`v13_request_hash` 七材料含 `p_context`），
ctx 每轮随事件变化 ⇒ 同一 signal 每轮也是新哈希 ⇒ **缓存不跨轮命中，全量重问**。
实测数据点：种子目录 9 问；DP10 双工具后 13 问，一个 2 工具 turn 的幸福路径
`judgment_calls == 4` 批（DP10 D6，每 parse 一批）≈ 52 问答对。
外推：20 工具 × 3 参数 = 185 问/轮 ≫ 快路上限 32/批 × 1 批
（`resolve_fast_path` 种子）⇒ **每轮都走 judge 慢路**（挂 effect、worker 往返）。
这不是易用性问题，是机制随目录规模**结构性变慢**——教程 ch6 目标形态的
consumes/produces 预筛（未落地）和 Tier 3（§3）都是对它的回应。

### 1.4 已有的「高层结构」雏形（方向已被设计预演过）

- **v13.1 工作台平面**（`docs/designs/v13.1-workbench-plane.md` §4.1）：
  `workbenches.manifest` 自报工具声明 → SQL 展开成 `tools` 目录行（幂等 UPSERT，
  digest 换版→目录翻新→revision bump）。**「声明式清单 → 目录行编译器」已是既定方向**，
  只覆盖 duck 族。本文 Tier 1 是同一思想的单工具入口。
- **demo harness/driver**（`v13/demo/harness.py` 242 行、`driver.py` 376 行，gitignored）：
  expect/fixture/gap_mock/假判断服务器/拨格循环已经写了一遍——证明编著层可行，
  但锁在本地不入库。
- **`mock_from_needed`**（`v13/loop/test_loop.py:78-98`）：按 needed 自动生成合法答案——
  离「按目标路由反推相位」只差一层（§3 Tier 1c）。

---

## 2. 对照：「函数就是工具」的谱系给了什么、收了什么

| | OpenAI function calling / Anthropic tool use | MCP | LangChain `@tool` 等 | Claude Code（权限提示） | **v13 现状** |
|---|---|---|---|---|---|
| 编著面 | schema+函数，harness 自动注册 | server 声明，client 发现 | 装饰器/类型推导 | 工具内建+skill | **函数+INSERT+（参数）五步舞** |
| 谁选工具 | 模型（每调用） | 模型 | 模型 | 模型 | **Jev 判断落行+带裁量** |
| 谁产参数 | 模型自由生成 args | 模型 | 模型 | 模型 | **stated 门+choice，绝不猜值** |
| 否决面 | 无（tool choice 粗粒度） | 无 | 无 | **人肉权限提示** | **数据带（注入/风险/置信）** |
| 可审计 | 日志（事后） | 日志 | 日志 | 日志 | **decisions 行+哈希+缓存世代** |
| 崩溃语义 | harness 代码负责 | 同 | 同 | 同 | **DB 账本+fence+幂等 id** |

三点结论：

1. 「函数即工具」的**编著体验**（authoring = 写一个函数 + 一行声明）确实是对的，
   v13 应该要——Tier 1 就是把它搬进来，底下仍然编译成目录行。
2. 它的**执行语义**（模型自由选择+自由产参+无否决带）正是 v13 十二轮裁决拒绝的东西。
   注意 Claude Code 的权限提示本质上就是人肉版的 v13 带——**否决需求是普遍的，
   区别只在它是代码/提示还是数据**。v13 把它做成数据换来了审计与版本化。
3. 参数 grounding 是 v13 独有的强项（模型幻觉参数在 function-calling 里是常态），
   简化时**不能丢语义，只能收敛形态**（Tier 3 的设计约束）。

---

## 3. 方案空间与推荐

### Tier 1（必做，零机制变更）：编著面三件套

**1a. `v13_register_tool()` —— 一个 SQL 函数吃掉五步舞。**

```sql
-- 签名草案（SECURITY DEFINER，owner=控制角色，EXECUTE 只给部署角色）
SELECT v13_register_tool(
  p_name        := 'read_file_py',
  p_description := 'read a file (python native port)',
  p_kind        := 'tool',               -- 'sql' | 'tool'
  p_handler     := 'worker:read_file_py',
  p_param_spec  := '{"path": {...}}'::jsonb,
  p_param_band  := 0.60                  -- param/stated 族带值，镜像种子约定
);
-- 返回：(registered=true, policy_version=N+1)
```

行为（单事务编排，全部是**已被守卫许可的 DML**，函数只是个客户端）：
sql 档先复用 tools_guard 的校验语义（函数在则 INSERT 目录行时守卫自然放行）→
有参数时：`INSERT v13_route_policies (name, max(version)+1)`（draft）→
从**最高 frozen 版本**逐行复制带 → 按 `p_param_band` 追加 param/stated 带 → freeze。
守卫、revision bump、事件触发器全部照常触发——**零机制变更**，纯粹把 DP10 §3 的
手工 SQL 序列函数化。

**1b. `v13/toolkit.py`（tracked）—— hub 框架，把 demo driver 转正。**

```python
from v13.toolkit import tool, run_hub

@tool("read_file_py", kind="tool", params={"path": "which file"})
def read_file(p):                       # 注册进 DISPATCH 表
    return {"text": Path(p["path"]).read_text()}

run_hub(conn_factory, DISPATCH)         # claim→按 request.handler 分派→complete；
                                       # 内置：超时映射(failed/unknown 二分)、
                                       # renew_lease 心跳、重启结算纪律、幂等键携带
```

**1c. `drive_turn()` —— 测试助手，按目标路由反推 mock 相位。**

```python
from v13.toolkit import drive_turn
snap = drive_turn(cur, sid, route_to=("read_file_py", {"path": "hello.txt"}))
# 内部由目标反推 intent/gate_action/gate_off_topic/risk/tool/stated::/param:: 覆盖，
# 替掉教程 §6 的相位配方；remaining==0 tripwire 内置
```

教程效果：§2（sql 档）= 函数 + 一行 `register_tool`；§3（tool 档）= 函数 + 装饰器；
§4.3/§6 整节删除。九节缩到约三节（档位选择、param_spec 语义、纪律红线）。

### Tier 2a（必做，小机制）：默认策略指针

消 F1。机制量级：sessions 允许 `route_policy_version` 解析为 NULL→查 active 指针
（如 `v13_policies` 加 `route_policy_default` 行，或 `v13_route_policies` 加 active 列
——具体形态走计划评审）。`register_tool` 冻结新版本后翻指针。
**张力**：session 显式 pin 版本 vs 跟随默认——建议「INSERT 时不指定=跟随指针，
指定了=pin」（显式优先，默认兜底），既保审计又不逼每个使用者记版本号。

### Tier 2b（可选，小机制）：参数带缺省值

`param::`/`stated::` 信号族在无带行时按策略行（如 `param_gate = {"pass": 0.60}`）
fallthrough，其余信号（gate_off_topic/risk/intent…）**不参与 fallthrough**。
五步舞对「只想让参数流过去」的场景整体消失（register_tool 也不再需要动策略版本）。
**代价**：param 门从「显式带行」降为「约定+策略行」，审计粒度下降；且与
「路由变更是显式审计事件」的 freeze 精神有张力（但 param 带只影响参数流通，
不影响任何否决面——安全性论证成立）。**若 Tier 3 立项则本项不做**。

### Tier 3（建议立项，DP11 级）：param 随 tool choice 一次判

把「选工具」和「定参数」合并进**一次判断**：`tool` choice 的答案扩展携带
`params` 分量（判后由 SQL 校验：choice ∈ 目录、params 键 ⊆ param_spec、
值 ∈ options、未陈述的参数必须省略——**grounding 从带执法移到题目约束+判后校验**，
「SQL 管算术，Jev 管语义」原文兑现）。

- 消掉的：每参数 2 问 2 带 → 0 问 0 带；五步舞、F2 膨胀（needed = 常数 5，
  与目录参数总数无关）、双问的教导成本。
- 动的面：`v13_needed_judgments`（**cgr 缝就是为这种演化预留的**，DDL event trigger
  会 bump `candidate_generation_revision` 触发弃批）、`v13_resolve_tool_params`、
  `v13_route`、判断模板 answer 校验；判断哈希材料变化（缓存世代一次性失效，可接受）。
- 保留的：反幻觉语义（判后校验兜底）、choice 证据行、阈值带对 tool 信号本身的
  pass 裁量、risk/gate 否决面全部不动。
- 需要一轮正经计划评审（仓库惯例：investigation → plan → 裁决 → DP 编号）。

### Tier 4（不做）：LLM 原生 tool_calls 替判断面

DP10 §7.1 已裁「工具选择属判断平面，另一条变更线」。它是最简编著面
（真·函数即工具），但等于放弃判断即行/带否决/可审计——是 v14 级战略选择，
不是简化补丁。记台账。

---

## 4. 推荐组合与教程改造预览

| 交付 | 内容 | 后教程形态 |
|---|---|---|
| DP-next A | Tier 1 + Tier 2a（`register_tool` + `toolkit.py` + `drive_turn` + 默认指针） | 写工具 = ①函数 ②一行注册/装饰器 ③gate。教程 §4.3/§6 删，§3 的 hub 样板删 |
| DP11（候选） | Tier 3（param-in-choice） | 带参工具与无参工具同价；needed 恒 5 问；F2 消失 |

对照「函数就是工具」：改造后的 v13 在**编著面等价**（函数+一行声明），
**执行面仍是 v13**（账本/带/审计/崩溃安全）——这是本调查建议的最终形态。

---

## 5. 开放问题（留给裁决）

1. Tier 2b 的 fallthrough 是否违反「路由变更显式审计」精神？（若 Tier 3 通过则此题消失）
2. Tier 3 的 answer `params` 分量放 typesafe 校验哪层（模板 answer_schema vs 判后 SQL 校验）？
3. 默认策略指针与七键探针的关系（指针变化是否进探针，防在飞 turn 被换策略）？
4. `register_tool` 是否也应该收编「删/禁/改」（`unregister_tool`/`disable_tool`），
   还是保持 DML 直写？
5. v13.1 的 manifest 编译器与本方案的关系（建议：register 先行，manifest 复用其内部步骤）。

---

## 附：证据索引

- 教程本体：`docs/tutorials/v13/how_to_make_a_tool_for_v13.md`（九节结构）
- 五步舞与守卫：`v13/schema/v13_core.sql:449-577`（route_policies/thresholds/sessions 三守卫）、
  种子带 `:959-984`、sessions 默认 `:22-24`
- param 双问血统：`v12/turn/v12_turn.sql:296-322`
- needed 线性膨胀：`v13/resolve/v13_resolve.sql:98-128`（全目录循环）、
  request_hash 含 ctx（`:152-160`）、快路上限种子（`v13_core.sql:752` 附近
  `resolve_fast_path`）、DP10 D6（`docs/plans/v13-dp10-multilang-tools-plan-2026-09-23.md` §4 M2）
- 编著面雏形：`docs/designs/v13.1-workbench-plane.md` §4.1（manifest→目录行编译器）、
  `v13/demo/harness.py` / `driver.py`（gitignored）、`v13/loop/test_loop.py:78-130`
- 被裁先例：DP10 §7.1（native tool_calls 推迟）、§7.3（ch6 目标列不做）
