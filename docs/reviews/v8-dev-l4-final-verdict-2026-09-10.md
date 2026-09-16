# V8-dev 实现规范 L4 终裁（冻结通过）

- **终裁时间**：2026-09-10（Oracle chat `untitled-chat-72410C`，全文复扫）
- **对象**：`docs/designs/v8-dev.md`（约 590 行，11 轮修订后版本）
- **冻结判定标准**：全文无 P0、无 P1；剩余最多 P2/nit —— **已满足**

## 终裁结论（Oracle 原文要点）

1. 三项残留修复（规则 4 同事务收束 retryable sibling、`retry_stop_reason` 全路径有序分类函数、`begin_switch` 四项安全点 guard + quiescing recovery 禁回 ready）**全部 PASS**，三处修订波及面交叉核对未发现新引入 P0/P1。
2. 状态机复扫：九状态出边 ⊇ 聚合规则 1–6（含扩展规则 3 与 drain 三分支）全部可达目标；每条规则 step+session 目标齐备；取消 code、receipt outcome、`retry_class`、effect 状态图等闭合集均闭合。
3. 全文 §0–§8 快速复扫未发现新增问题；遗留项均为 P2/nit 级，按冻结标准允许保留。
4. **最终结论：当前全文无 P0、无 P1，满足冻结条件（剩余仅为允许保留的 P2/nit）。**

## 修复轨迹（22 → 0）

| 轮 | 发现 | 修复 |
|---|---|---|
| 基线 | 22 条（前序 Oracle） | — |
| R4 | 8 P1（协议核） | 原子 seal、cancel-wins、repair-to-ready 清除、recovery 接管、receipt/slot、audit 元组、driver_mode、canonicalizer |
| R5–R6 | F-01/F-02 → F-11 | 初始 seal 状态边、WORKSPACE_LOST fail-closed、ready→succeeded 不安全边 |
| R7–R8 | R-01~R-03 | retry 出边、repair 恢复出边、聚合补全出边 |
| R9 | R-04~R-11（8 条） | 规则 2 双分支+session 目标、规则 3 provider-cancel、retry_eligible、failure-drain、terminal finish_switch、driver_switch_capability |
| R10–R11 | V-01~V-06（1 P0 + 5 P1）→ 3 残留 | 结果已知性/重试资格拆分（P0）、drain 三分支、受控关闭边、共享取消收束、retry_stop_reason、SWITCH_DEFERRED 安全点 |

## 允许保留的遗留项（P2/nit）

- F-03（P2）：grant 有效性谓词缺 slice 撤销传播
- F-04（P2）：§1.3 "RFC 8785 JCS 或版本化等价子集"仍允许多实现；golden vectors 未强制（审核建议并入 P0A 冻结前清理）
- F-06 已升格修复（driver_switch_capability）；F-05 已随 R-04 消解
- F-07（P2）：workspace_handle 状态闭合图与正文对齐
- F-08（P2/nit）：transition_wait/sleep receipt 表行、§5.2 引用集合核对
- F-09/F-10（nit）：step 级 code 命名层级注记、§2.1 seam 清单点名 route 解析
- R11 修复者记录的次要残留：入口残留无 effect 的 planned step 对 finish_switch 屏障的判读（仅活性）；规则 4 为 sibling 写 budget_exhausted 后 code 仍按规则序取 FAILED_TERMINAL

## 审核链

- 替代审核（Oracle 不可用期间）：Kimi K3 design 会话 `9A36997E`，报告 `docs/reviews/v8-dev-l4-review-2026-09-10.md`、`...-round2.md`（其"无 P1"终裁被 Oracle 推翻，仅作辅助证据）
- 权威终裁：Oracle `untitled-chat-72410C`（本文摘录）
- 循环记忆：`prompt-exports/loop-orchestrate-v8-dev-runs.md`
