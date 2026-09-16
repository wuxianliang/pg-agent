# V8-dev L4 增量终审报告（Round 2）

- **审核对象**：`docs/designs/v8-dev.md`（550 行，F-01/F-02 修订后版本）
- **前序报告**：`docs/reviews/v8-dev-l4-review-2026-09-10.md`（P0=0、P1=2：F-01、F-02）
- **审核日期**：2026-09-10
- **审核范围**：增量终审——仅复核本轮 13 处编辑波及章节（§2.2 第 3 条、§3.1 advance_session、§3.1.1 terminal 行、§3.1.2 seal 段与 receipt 表、§3.2.1 planned 行/聚合例外/派生表、§3.3 repair 条目、Conformance 第 1/13 条），外加修复者自曝疑点 `ready → succeeded` 死边裁决与全文交叉引用回归扫描。
- **判定标准（冻结）**：通过 = 全文无 P0、无 P1（剩余最多 P2/nit）。

---

## 1. 总结与最终结论

**最终结论：不通过（存在 1 个 P1，无 P0）。**

F-01、F-02 两项修复均判定 **PASS**：seal 双路径拆分在 guard 强度、receipt 幂等、状态表三层闭合；WORKSPACE_LOST fail-closed 五处联动方向一致、例外链无实质矛盾。但修复者自曝的疑点经裁决成立：**§3.2.1 `ready` 行的 `ready → succeeded` 是不可达死边，且其 guard 字面上可被满足（ready 步骤已持久化 `final_tools=true`），存在跳过工具执行直接终态化的误实现风险**，记为 F-11（P1）。

**计数：P0 = 0，P1 = 1（F-11），P2 维持前轮 6 条（F-03~F-08），新增 nit 2 条（F-12、F-13）。**

---

## 2. F-01 验证：PASS

**修复内容核对**：

| 检查点 | 结果 |
|---|---|
| 双命名路径拆分 | §3.1.2 明确"同一原子 seal 实现的两个入口"：**初始 decision seal**（CAS 前置 `planned, stage=decision`，同事务创建/校验 step、密封唯一 LLM slot、写 sealed_batch_no 与 batch identity）与 **tools seal**（CAS 前置 `ready, stage=decision`，guards 1–4）。F-01 原缺口消除 |
| guard 强度一致性 | 初始 seal 明文"CAS 同时校验 driver/epoch/fence、active mode、无 sticky cancel"，与 tools seal guard 2 完全对齐；tools seal 额外的 decision result identity / plan_hash / `final_tools=true` 核验为路径固有（初始路径尚无 decision result，不适用），不构成强度缺失 |
| receipt 幂等 | guard 1 明文"两条路径共用"；seal receipt 键按路径拆分（tools seal 按 decision result identity；初始 seal 按 step 首个 batch identity），重放仅返回原 receipt 并为新 command_id 保存引用，与 §3.1.2 通用 binding/receipt 规则一致 |
| 死边删除理由 | §3.2.1 `planned` 行改为 `waiting_effect, cancel_requested`，并注明"`ready` 仅表示已接受 decision result 后等待 tools seal，planned step 没有可冻结的 decision result"——理由成立：`ready, stage=decision` 的不变量是"已冻结 plan_hash + 已接受 decision result identity"，planned 步骤两者皆无，任何实现都无法写出满足该不变量的 `planned → ready` 转移 |
| 联动 | §3.1 advance_session 伪代码改为"create step + 初始 decision seal"同一事务；Conformance #1 补充初始 seal 重放断言（覆盖 step 同事务创建与 assemble 预创建两种情形）；quiescing 拒绝清单同时覆盖 `create_step/prepare_step/seal_batch`，无逃逸路径 |
| 新缺口扫描 | 未发现。初始 seal 的 CAS 失败（step 已非 planned）必先经 guard 1 receipt 查重，重放安全；`planned → cancel_requested`（sticky cancel 关闭未密封计划）与 `request_cancel` 语义自洽 |

**判定：PASS。**

---

## 3. F-02 验证：PASS

**修复内容核对**：

- §2.2 第 3 条：确定性 fail-closed——一旦 `workspace/lost` 或 `WORKSPACE_LOST`（两条检出路径均覆盖），session MUST 在同一控制事务进入 `failed` / `failure_code=WORKSPACE_LOST`，"不存在「由政策决定」的分支"；未决 effect 的 completion/repair 仅收束与审计，MUST NOT 离开 `failed`、MUST NOT 恢复执行；继续的唯一途径是 fork。原 F-02 开放分支消除。

**例外链矛盾检查（逐项）**：

| 疑点 | 裁决 |
|---|---|
| terminal 行"仅 receipt 重放/audit/inspect" vs completion/repair 收束 | §3.1.1 terminal 行已显式增补"§2.2 第 3 条 WORKSPACE_LOST fail-closed 后未决 effect 的 completion/repair 收束（session MUST 保持原终态）"——例外被命名列入，不再是未列出转换，无矛盾 |
| step 级"pending/unknown 禁止 terminal" vs session 级例外 | §3.2.1 明文该禁止的**唯一例外**是 session 级 WORKSPACE_LOST fail-closed；step 级禁止保留（step 仅在 effect 全部终态后才按矩阵收束），session 钉死 `failed`、step/effect 继续按矩阵收束，两层语义无交集冲突 |
| repair 作用域放大 | §3.3 repair 条目将 recovery claim 可接管范围扩到"WORKSPACE_LOST fail-closed 后的 terminal `failed` session"，但限定"**仅限未决 effect 的 repair 收束与审计，MUST NOT 改变 terminal 状态或创建新工作**"；作用域封闭，未波及其他 terminal（completed/cancelled 仍不可接管） |
| 派生表 | 新增行：session 固定 `failed`/`WORKSPACE_LOST`，step outcome_code 收束前 NULL、收束后按 effect 终态派生——与矩阵及例外段一致 |
| Conformance #13 | 增补"session 终态唯一为 `failed`/`WORKSPACE_LOST`，in-flight 未决 effect 的后续 completion/repair 不改变终态、不恢复执行或重建 workspace"，可执行断言 |

**判定：PASS。**（两处文字级缝隙记为 nit，见 F-12/F-13，不构成 P1。）

---

## 4. 专门裁决：`ready → succeeded`（§3.2.1 `ready` 行）—— P1（F-11）

**可达性分析**（穷尽 ready 的全部进入路径）：

1. **decision completion 带 tool calls → `ready, stage=decision`**：此时无 in-flight 批次（decision 批次已结算，tools 未 seal），不存在任何可触发聚合的 completion 事件；唯一合法前进操作是 tools seal（→ `waiting_effect`）。
2. **初始 decision seal / tools seal 前的瞬态**：不适用，seal 即离开。
3. **`failed_retryable → ready`（retry_effect）**：retry_effect 将 effect 置回 `ready`（新 attempt 未 dispatch），随后在 retry 事务的聚合或 dispatch 时按矩阵规则 2（pending sibling）落到 `waiting_effect`；在 step 停留 `ready` 的窗口内 effect 尚未 dispatch，**不可能有 completion 到达**，矩阵规则 6（全部成功 terminalize）不可满足。

而 `decision_only=true` / `final_tools=true` 的成功终态化，按 §3.1.2 guard 4 与矩阵规则 6，**均发生在批次 completion 聚合（`waiting_effect → succeeded`，同事务写 `stage=closed`）**。结论：`ready → succeeded` 无任何可达 guard，是死边——修复者疑点成立。

**为何判 P1 而非 P2/nit**：该边不是无害冗余。`ready, stage=decision` 的 step（decision 带 tool calls）**已持久化 `final_tools=true`**，而 `ready` 行 guard 字面写"仅显式持久化 `decision_only=true` 或 `final_tools=true` 可 terminalize"——一个按状态表字面实现的系统会允许 tool-calls 步骤在工具从未 seal/执行的情况下直接从 `ready` 终态化为 `succeeded`，绕过 §3.1.2 tools seal 与批次执行。这符合 P1 定义（协议冻结前必须修复的、可导致错误实现的状态机缺陷）。

**最小修复建议**：从 `ready` 行删除 `succeeded` 目标，沿用 `planned → ready` 死边删除的同款表述（"成功终态化仅经批次 completion 聚合在 `waiting_effect` 上发生，ready 无 in-flight 批次、无可达 terminalize guard"）；terminalize 边唯一保留在 `waiting_effect → succeeded`。

---

## 5. 回归扫描

本轮 13 处编辑波及章节与全文交叉引用（§0/§1/§2/§3/§5/§6）核对结果：**未引入其他不一致**。

- seal 双路径与 §1.2 ABI、§3.1.1 quiescing 拒绝清单、§5/§6 引用无冲突；receipt 表 `prepare_step/seal_batch` 行已同步双路径措辞。
- WORKSPACE_LOST 链条五处（§2.2、§3.1.1、§3.2.1 例外+派生表、§3.3、Conf #13）方向一致；§0 不变量 18、§7"静默创建空 workspace"条款语义不变。
- 前轮 F-03~F-08（P2）与 F-09/F-10（nit）维持原级别，无一条需升格为 P1。

**新增 nit（不阻塞通过）**：

| 编号 | 位置 | 问题 | 建议 |
|---|---|---|---|
| F-12 | §3.1.1 recovery_claim 段 vs §3.3 | §3.1.1 仍写 recovery_claim"可在任意 `N`（非终态）上"取得，§3.3 新增可接管 WORKSPACE_LOST 后的 terminal `failed`；terminal 行虽已命名 repair 收束例外，但 recovery_claim 一句未同步 | 在 §3.1.1 recovery_claim 句末补"及 §2.2 第 3 条 fail-closed 后的 `failed`（仅限收束）" |
| F-13 | §3.2.1 聚合矩阵规则 1 | 规则 1 字面"任一 unknown_outcome → step/session `blocked_unknown_effect`"未提及 WORKSPACE_LOST 例外下 session 钉死 `failed`；例外段文字已覆盖，但矩阵本身是"唯一聚合函数"的权威表述 | 在规则 1 或矩阵引言补一句"WORKSPACE_LOST 例外下 session 级目标固定为 `failed`，矩阵仅收束 step/effect" |

---

## 6. 下一轮最小修复组

仅剩 1 个 P1，单组即可闭合：

- **G1（F-11）**：删除 §3.2.1 `ready` 行的 `succeeded` 出边并注明死边理由（同 `planned → ready` 的处理方式）；可选联动：在 Conformance #1 或 #6 邻近补一条"tools 未 seal 的 ready step 不得 terminalize"的断言。
- 顺带（nit，可同批）：F-12、F-13 两处文字同步。

F-03~F-08（P2）按原计划进入 P0B/P1 阶段处理，其中 F-03（slice 撤销传播）与 F-06（§1.1 MUST 措辞）仍建议在 P0A 冻结前扫掉。

---

## 附：核对记录

- 重读章节：§2.2（120–156 行）、§3.1/§3.1.1（157–232 行）、§3.1.2（233–288 行）、§3.2.1/§3.2.2（289–413 行）、§3.3（414–437 行）、§6 Conformance（518–537 行）。
- F-01 核对：双路径 guard 逐项比对（driver/epoch/fence、active mode、sticky cancel、receipt 共用、seal receipt 键、batch identity 写入），状态表 `planned` 行与 §3.1.2 互引一致。
- F-02 核对：例外链五处联动逐条比对，terminal 行/矩阵/派生表/repair 作用域/Conf #13 无方向性冲突。
- `ready → succeeded` 裁决：穷尽 ready 的三条进入路径逐一验证无可达 guard，并评估字面 guard 的误实现风险后定级 P1。

---

## 终裁（2026-09-10，第三轮增量复核）

复核范围：F-11（§3.2.1 `ready` 行）、F-12（§3.1.1 recovery_claim 句）、F-13（§3.2.1 聚合规则 1）三处修订（文档 550 行）。

### 三项判定

| 编号 | 判定 | 理由 |
|---|---|---|
| F-11 | **PASS** | `ready` 行出边已删为 `waiting_effect, cancel_requested`；guard 写入死边理由（无 in-flight 批次、无可达 terminalize guard、terminalize 仅属于 `waiting_effect` 行与聚合规则 6）及原 P1 定级理由（`final_tools=true` 字面可满足导致工具未执行即终态化的误实现风险），并明确 decision_only completion 直接 `waiting_effect → succeeded` 不停留 ready |
| F-12 | **PASS** | recovery_claim 句已补"terminal `failed` session 仅限 §2.2 第 3 条 WORKSPACE_LOST 未决 effect 收束（与上表 terminal 行例外一致），不得开展新工作"，与 §3.3 repair 条目、terminal 行三方一致 |
| F-13 | **PASS** | 聚合规则 1 已补括注"唯一例外：WORKSPACE_LOST fail-closed 下 session 目标固定为 `failed`，不因 unknown 改变"，与例外段及派生表一致 |

### 新问题扫描

- `ready` 行新 guard 文字与 `waiting_effect` 行（`succeeded` 为批次聚合目标）、聚合规则 6（成功 terminalize 语义）、§3.1.2 guard 4（terminalize 写 `stage=closed`）交叉一致，无残留第二处 `ready → succeeded` 引用。
- F-12/F-13 为纯文字同步，未触碰任何 guard 强度或状态集合。
- 未发现任何新引入的不一致。

### 最终结论

**通过。** F-11 闭合后全文无 P0、无 P1。

**最终定级：P0=0、P1=0，剩余 P2=6（F-03~F-08）、nit=2（F-09、F-10），达到冻结标准。** 建议 F-03（slice 撤销传播）与 F-06（§1.1 MUST 措辞）按原计划并入 P0A 冻结前清理，其余 P2/nit 进入 P0B/P1 阶段处理。
