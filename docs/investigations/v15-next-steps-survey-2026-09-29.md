# v15 后续项目探索性研究：该做什么、预期什么

2026-09-29。三路探查（规格待做清单 / jaz 参考实现形态 / demo 现状）+ 会话裁决史综合。证据均带 file:line；不构成开工承诺，供排期裁决。

---

## 总览：四个候选的定位

| 候选 | 一句话 | 规模 | 证据价值 | 风险 |
|---|---|---|---|---|
| A. 发布驱动源码 | force-add `demo_v15/` 8 文件 | 极小（一次提交） | 可复现性/展示 | 几乎无 |
| B. 更深链 demo | depth 5–8 尾委托链 + prior_history + 上下文告警 | 小 | 论文 StuLife 性质首验 | 中（成本可控） |
| C. 多任务 demo | 同迭代扇出 + meta-agent 读 trace 自改 prompt（CSI 模式） | 中 | 唯一零覆盖机制 + 论文第二条性质 | 中高 |
| D. v15 功能扩展 | ValidateReturn/ReturnType/回放/外部工具/扇出并行 | 中—大 | 能力补全 | 回放与并行高 |

---

## A. 发布驱动源码（force-add）

**干什么**：按 `da4663e` 先例（3 文件 735 行、单行提交信息）force-add 8 个源文件：`demo_v15/{README.md,db.py,task.py,script.py,drive.py,assert_e2e.py,report.py,test_harness.py}`（共 2291 行）。**不 add** `reports/`（计划明令报告不入库）与 `__pycache__/`。

**已验证的安全性**：无硬编码 key（key 只从进程环境读，`drive.py:73-75`）；`report.py:171-176` 已有 redact 机制且实测 `reports/` 零 key 命中；`test_harness.py` 的 keyless 子进程用例随源码入库后可直接复跑。

**预期效果**：
- demo 从「一次性本地证据」变成「任何人可复跑的仓库资产」——fake 路径零 key 零成本即可跑通全链断言（`DEMO_MODE=fake`），real 路径有 key 即可；
- `assert_e2e.py`（935 行、13 条 §0.2 断言 + 22 级失败分类）成为 v15 语义的活文档；
- 需要同步改三处文书：`.gitignore` 例外说明、AGENTS 入口句已就位（M1 已写 `demo_v15/drive.py`，发布后该句从「指向 gitignored 目录」变为「指向入库脚本」）、demo 计划的跟踪策略节补一行 Run record。

**建议**：做，且最先做（B/C 都会改驱动，改完一起发布更整洁——也可以 B 之后做）。

---

## B. 更深链 demo（depth 5–8）

**干什么**：把 `task.py` 参数化（`ROOT_HOPS` 现写死 3，`validate_hops`/断言链/剧本长度全部写死 depth 3），跑 depth 5–8 的 echo relay；装上 `context_window_warning` hook（两套冻结正文已在 `v15_govern.sql:867-914` 落地、9 处 gate 断言，**但从未在真栈触发过**）；任务设计改为「当上下文告警到达时用 `jaz.prior_history` 检索祖先历史再委托」（论文 §4.1 的 tail-recursive delegation + far recall 模式）。

**硬约束（探查确认）**：
- 全局清单单例 `max_depth=8`（`v15_schema.sql:1039-1046`）是硬顶——**depth ≥ 9 需要改清单行**（操作员动作，非规格变更）；demo ceilings（现 4/4/2/30000）在清单内收紧即可调到 8；
- `CAP=256` 步数闸：链长 × 重扫步数需实测（裁决 8 明令不改 CAP）；
- 成本：现 depth 3 花费 $0.00126；depth 8 粗估 ×3–5（上下文逐层增长），池上限 32 次调用 / $2 仍宽裕；
- **`jaz.prior_history` 与 `context_window_warning` 是两个「gate 全绿但真栈零执行」的承重件**——这正是本项的核心证据价值。

**预期效果**：
- 论文 StuLife 性质（深度 70 链 + far recall）在 v15 上的首次缩比验证：证明「历史是关系 + 祖先 id 传递」的设计在真模型多跳委托下成立、不退化；
- 触发 `context_window_warning` → 模型按教学正文改用 prior_history 的完整回路（论文 Takeaway 1 的 SQL 版）；
- 暴露长链下的真实成本曲线与上下文增长速率，为后续预算治理提供数据。

**风险**：模型在 depth 5+ 可能偷懒（不转发 note、直接编 seal）——22 级失败分类已能精确诊断；note 预算 3 次迭代机制沿用。

**状态**：已执行（2026-09-29–30，计划 `docs/plans/v15-deep-chain-demo-plan-2026-09-30.md`，两场景 `tail_ok`；「上下文逐层增长」的旧估计已被实测推翻——每跳恒 ~2.6KB，调查原文保留作历史）。详见该计划文末 Run record。

---

## C. 多任务 demo（CSI 模式）

**干什么**：两个递进子项。
1. **同迭代扇出**：一个迭代里 `bind a; bind b; return(jsonb_build_object(...jaz.var...))`——v15 的挂起模型**按构造支持**（bind1 挂起→子1 终态→恢复到 bind2→再挂起→…→return 读双 var），但探查确认**全仓零 gate 覆盖**（现有 grandchild 测试的两次 bind 分属两次 LLM 回复）。先补 FakeLLM gate，再真栈。
2. **meta-agent 读 trace 自改 prompt**（论文 AppWorld CSI：root 批量派 solver、读子 `__history__` 诊断失败、改下批的 instructions/skills）：v15 机制全部就位且 gate 已证明——solver 让子 `jaz."return"(jsonb_build_object('answer',..., 'history', (select jsonb_agg(...))))` 或 root 用 `jaz.prior_history(子id)` 读（**注意**：prior_history 限祖先方向，读子轨迹要靠子自己返回，这正与论文「tell the subagent to return its history」一致）；iteration 预算、input 不传子、scope 复制均已 gate 覆盖。

**预期效果**：
- 子项 1 补上 v15 唯一的机制覆盖空洞，证明「扇出 = 顺序 bind 的自然结果」这一设计承诺；
- 子项 2 是论文**第二条性质（自改进）**的 v15 首验——meta-agent 在纯 SQL 方言里完成「派单→读 trace→改 prompt→再派单」闭环，对应论文 Table 2 的 JAZ invoke 优势来源；
- 若成功，v15 就同时具备论文两大 case study 的缩比版（B=长程记忆，C=自改进），故事完整。

**风险**：真栈成本高于 B（多任务批 × 多轮）；模型读子轨迹 SQL 聚合可能出错（教学文本只有一句 prior_history 引导，可能需要 note 迭代）；子项 2 失败形态可能是「模型不用 trace 只凭记忆改」——断言须检查 root 是否真读了子历史（如要求 root 引用子 trace 中的具体错误码）。

---

## D. v15 功能扩展（按性价比排序）

规格事实基础：五个预留效应名（`supply_llm_response/supply_invoke_result/modify_invoke_result/supply_exec_result/modify_llm_response`）当前每个 phase 一律 `P1506` 拒绝（§9.4:1889、V15-D21）；启用任一都走 **design revision + 错误码表尾追加**（P1540–P1548 还有 9 个空位，§18 明令不得预占）。

### D1. ValidateReturn / ReturnType（推荐首批）

- **jaz 形态**：ValidateReturn ~150 行（REPLExecComplete/InvokeComplete 两级检查 + 对象身份跳过副作用型 validator、异常原样透传）；ReturnType ~220 行（beartype 类型检查 + 构造期探针 fail-fast）。二者都只用 `ModifyExecResult`（return→continue 降级）。
- **v15 落点**：`repl_exec/complete` 的 `exec_result` 通道**已存在**（budget_forcing 在用，§9.4 现只允许 return→continue 一种改写）。要做的是：① 允许表扩 return→**raise**（校验失败）；② validator 不能是 Python callable（v15 无进程内 hook），退化为**注册的 SQL 谓词函数**（hook_defs 已有登记机器：STABLE、NOLOGIN owner、digest 校验——照搬）；③ ReturnType 退化为 jsonb 形状检查（jsonpath 谓词，规格 §5.3 已明确不引入 pg_jsonschema，形状检查放 handler 体内）；④ 计数器（max_failures 容忍语义）用现成的 `hook_counters` 表。
- **预期效果**：论文 Figure 1 的 `ReturnType(list[Figure])` 例子补全；「return guard 让 agent 保持工作」的可靠终止语义可用；工作量约一个新 stage（SQL 为主，复用全部既有机器）。

### D2. 轨迹回放（复杂度最高，谨慎）

- **jaz 形态**：TrajectoryReplay 1119 行——`supply_llm_response` 效应、每 invoke 独立队列树、三条分歧检测（消息编辑签名/助手内容/observation 重渲染）。另有录制侧 TrajectoryRecorder 714 行（ATIF JSON）+ DirectoryRecorder 853 行（已知**非线程安全**）。
- **v15 的三重难点**（探查确认）：① LLM 调用在 v15 是表行不是函数调用——「supply」= 不插 provider 行、插入伪造 settled attempt，还得走同样的校验/记账；② 分歧检测没有 jaz 的 seam——committed prompt 是 SQL fold 的结果，要么 Python 重跑 fold（第二份实现会漂移、假分歧烧真钱），要么**在写入时存 canonical prompt hash**（推荐：`llm_requests` 加一列或 payload 加一键，随 revision）；③ `supply_llm_response` 要进效应闭集允许表（revision + gate）。
- **预期效果**：确定性回归测试的真实闭环——同一 trace 无网络重放（jaz 里 replay 的 cost/budget 照常生效这个设计值得照抄：v15 版可让 `calls_used` 照计、cost 记 0）；对 demo CI 化（真模型跑一次录下来，之后 gate 重放）有直接价值。**但优先级取决于是否需要 CI 级回归**——若 FakeLLM 剧本已够用（现状：够），可缓。

### D3. 外部工具（bind_invoke 式延续协议）

- **规格现状**（探查纠偏）：偏差台账 D05 的最终文本是「工具同步、纯 SQL、`external=true` 抛 `V15_EXTERNAL_TOOL`」——**「外部工具沿用语句间延续」只是设计期 oracle 讨论的意向，未写进冻结文本**。做它 = 真 revision：新增 `jaz.bind_tool(name, args)` 类控制形式 + `v15_tool_wait` 挂起态 + 工具请求/attempt 表（镜像 llm_requests/attempts 机器）+ worker 侧工具执行入口（第二个 socket 入口，AGENTS 例外句再扩）。
- **jaz 对照**：jaz 的外部工具 = 普通 Python callable 直接入 REPL（零 ACL、全能力）；v15 已走相反轴（catalog+grants+per-tool role，安全面更重）。移植的真缺口是「工具要做网络/文件 IO」——而这恰是不变量 4 的领地。
- **预期效果**：解锁 web_search/文件系统类工具（论文 Figure 1 的 `web_search` 输入）；但 demo 层面暂无硬需求（echo relay 不需要真工具，FakeTool 已覆盖测试面）。**建议等出现真实用例再做**。

### D4. map_invoke / 并行（不推荐近期做）

- 探查实证：**jaz 自己也没有 `map_invoke`**（全工作区零命中；只有 `ainvoke`+宿主 `asyncio.gather`），且 jaz 多个内置 hook 在并发下**已知是坏的**（replay 的单栈 mis-serving #1310、DirectoryRecorder 无锁、budget 共享祖先状态）。v15 第一轮架构裁决就把「共享池 + 并行 map_invoke 的锁序死锁」列为 key risk（`v15-oracle-round1.md:175`）。
- v15 要做需：父保持 suspended 期间并发 claim N 子（改 §0.10 单租约模型）、锁序全面重审、invoke_events 单 seq 与并发写的关系重设计。
- **扇出的顺序 bind 形态（C1）已覆盖 90% 的用例价值**，并行只省 wall-clock。**建议搁置**，等有「必须并行否则超时」的真实工作负载再裁。

---

## 推荐路线

```
A（发布驱动）→ B（更深链）→ C1（扇出 gate+真栈）→ D1（ValidateReturn/ReturnType）
                                          ↘ C2（CSI meta-agent）—— 与 D1 可并行
D2（回放）按 CI 需求插队；D3（外部工具）等用例；D4（并行）搁置
```

理由：A/B/C 是证据线（复现性→论文性质一→论文性质二），成本递增但全部复用现有机器、零规格变更（B 只改 demo ceilings 与清单行）；D1 是能力线里性价比最高的（复用 hook 登记 + exec_result 通道，一个 stage 的量）；D2/D3 是重型 revision，等需求明确；D4 连 jaz 参考实现都没解决正确性，不做。

## 会话补充注记

- demo 计划当时把「外部工具沿用 bind_invoke 延续」写进了背景——探查证实该句**不在冻结规格**（D05 是同步语义），后续若起草 D3 计划须以 D05 原文为基线；
- B 项的 depth 上限 8 来自清单单例——这是操作员可改的行，不是规格不变量；但 demo 计划裁决 10「不放宽 $2/32」继续有效，depth 8 的成本须先在池内实测；
- C1 有一个设计承诺要验：父恢复语义「按 stmt_index 顺序取第一条 running」（`v15_io.sql:780-810`）意味着 N 个 bind 顺序执行——gate 要断言的就是这个顺序性本身。
