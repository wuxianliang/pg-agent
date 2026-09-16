# V8-dev 实现规范 L4 独立审核报告

- **审核对象**：`docs/designs/v8-dev.md`（Postgres-Native Agent V8 实现规范，547 行，含 8 个 P1 缺口修订）
- **审核级别**：L4（全文独立规范审核）
- **审核日期**：2026-09-10
- **审核范围**：(1) 逐项验证 8 个已修复项是否真正闭合（修复须落在状态表/命令语义/guard 层面）；(2) 全文其余区域：§0 不变量一致性、§1.2/§1.3 canonical、§2.1/§2.2 slice/grant/workspace、§5 compat、§6 路线与验收、闭合集完备性、交叉引用完整性。
- **判定标准（冻结）**：通过 = 全文无 P0、无 P1（剩余最多 P2/nit）。

---

## 1. 总结与最终结论

**最终结论：不通过（存在 2 个 P1，无 P0）。**

本轮针对 8 个 P1 缺口的修订质量整体很高：原子 seal、cancel-wins 矩阵、recovery 接管、拒绝 receipt、effect_audit 元组、driver_mode 状态机、canonicalizer unknown 拆分七项均以 MUST/guard/CAS/派生表形式落在可执行层面，且与 Conformance 最小集合形成闭环，无循环论证。但全文审核发现 2 个**新引入/残留**的 P1：

- **F-01（P1）**：§3.1.2 规定初始 decision batch 由原子 seal 在 `planned, stage=decision` 上创建并"聚合为 `waiting_effect`"，但 §3.2.1 step 转移表中 `planned` 的允许目标只有 `ready, cancel_requested`，**没有 `planned → waiting_effect` 边**。seal guard 第 2 条又统一要求 CAS `status=ready, stage=decision`，与初始 decision seal 作用于 `planned` 相矛盾。这是修订项 1 引入的状态机缺口，两个独立实现者会分别走向"补一条边"和"先 planned→ready 再 seal"两种不同实现。
- **F-02（P1）**：§2.2 第 3 条 WORKSPACE_LOST 后"session 随后进入 `failed` 或 `blocked_unknown_effect` **由政策决定**"。P0A 冻结条款明确包含 `workspace_handle` 生命周期与 `WORKSPACE_LOST`，但冻结点上该生命周期的 session 级后果仍是开放二选一；两份运行时可各自选择不同分支，直接破坏 §1.2 portable 比较所依赖的终态一致性。

其余发现为 P2/nit（见第 3 节），均可推迟。

**计数：P0 = 0，P1 = 2，P2 = 6，nit = 2。**

---

## 2. 八项修复验证（PASS/FAIL）

| # | 修复项 | 判定 | 一行理由 |
|---|---|---|---|
| 1 | 原子 seal（prepare_step/seal_batch 统一）闭合 decision→tools 转移 | **PASS**（附新 P1，见 F-01） | §3.1.2 四条 seal guard（receipt 重放/身份 CAS/同事务写 stage+batch+effects/仅凭持久化 decision_only·final_tools terminalize）完整落地；但初始 decision seal 的 `planned→waiting_effect` 边在 §3.2.1 状态表中缺失，属本次修订引入的新缺口，单列为 F-01 |
| 2 | sticky cancel 混合 sibling 聚合为无自由裁量优先级矩阵 | **PASS** | §3.2.1 六条优先级规则"命中首条即决定，不存在自由裁量"，outcome_code/failure_code 派生表闭合（含 FAILED_TERMINAL_CANCELLED），§1.2 CANCELLED_BY_REQUEST_AFTER_DISPATCH 行与 Conformance #6 一致 |
| 3 | unknown 的 repair-to-ready 全文清除 | **PASS** | effect 闭合集 `unknown_outcome → succeeded|failed_terminal|cancelled_after_dispatch` 唯一；step 表 `blocked_unknown_effect` 无 ready 出边；§3.2.2 明文"永不 repair 为 ready、永不产生新 attempt、禁止 timer retry"，与 §1.2 repair closer 规则一致 |
| 4 | recovery 接管"旧 attempt 必已失效才可创建下一 attempt" | **PASS** | §3.2.2 六步原子流程：同事务推进 job_fence+撤销 job lease→旧 completion 必 stale-reject（STALE_JOB_FENCE）→第 4 步明确"先建新 attempt 再失效旧 attempt MUST NOT"；retry_class 三值闭合集及各自证据条件闭合 |
| 5 | 拒绝 receipt 稳定化 + batch slot 必备字段/唯一约束/创建 CAS | **PASS** | receipt outcome 闭合集 `{accepted, rejected_stale, rejected_mismatch, repair_required}` 覆盖全部拒绝路径且拒绝记录不得随 rollback 丢失；`effect_requests` 含 batch_id/dispatch_ordinal/tool_call_id，双 UNIQUE + slot manifest CAS + "seal 后不得补建/删除/改序" |
| 6 | effect_audit 完整 expected/received 绑定元组与去重键 | **PASS** | 全部 envelope 字段成对出现，敏感 key 仅存可比较 hash；无法定位 effect 时 expected 侧为空、received 侧完整且不跨租户泄漏；去重键覆盖 `hash(canonical(received binding)) + reason`，不再只依赖 result_hash |
| 7 | driver_mode 闭合可执行状态机 | **PASS** | §3.1.1 三行 mode 转移表（begin_switch/quiescing 收束/finish_switch CAS 屏障）+ QUIESCING 全命令拒绝（含已持 lease 的旧 coordinator）+ 旧 worker result 经 reconcile 子操作结算；§1.1/§3.1.1/§3.3/§5 四处一致，§3.3 明文排除"收束与屏障倒置"的循环 |
| 8 | canonicalizer 区分 provider 确认取消与本地 timeout/unknown | **PASS** | §1.2 分列 CANCELLED_BY_PROVIDER 与 UNKNOWN_AFTER_DISPATCH 两 raw 行，unknown 输出唯一（`assistant/partial {outcome:unknown}` + 唯一 `turn/end {outcome:unknown}`）且未 repair 前 portable 比较 MUST 返回 `blocked_unknown_effect`；与 §3.2.2 取消 code 闭合映射、Conformance #15 三方一致 |

**概要：8/8 PASS**（项 1 的 PASS 针对 decision→tools 原子性本身；其引入的状态表缺边作为新发现 F-01 单列）。

---

## 3. 全部发现（按级别排序）

### P1

| 编号 | 位置 | 问题 | 最小修复建议 |
|---|---|---|---|
| F-01 | §3.2.1 step 转移表 vs §3.1.2 seal 段 | 初始 decision batch 由原子 seal 在 `planned, stage=decision` 上 CAS 创建并"聚合为 `waiting_effect`"，但 step 转移表 `planned` 行仅有 `ready, cancel_requested` 两个目标，缺 `planned → waiting_effect`；同时 seal guard 2 统一写"CAS 校验 `status=ready, stage=decision`"，与初始 seal 作用于 `planned` 冲突。"同一原子 seal 操作的两个入口"实际有两种 CAS 前置状态，规范未承认 | 在 step 转移表 `planned` 行增加 `waiting_effect` 目标，guard 注明"仅经 §3.1.2 初始 decision seal（同事务创建并密封唯一 LLM slot）"；seal guard 2 改为区分两个入口的 CAS 前置（初始：`planned, stage=decision`；tools：`ready, stage=decision` 且已核验 decision result identity） |
| F-02 | §2.2 第 3 条 | WORKSPACE_LOST 后"session 随后进入 `failed` 或 `blocked_unknown_effect` **由政策决定**"。P0A 冻结清单包含 workspace_handle 生命周期与 WORKSPACE_LOST，但该分支在冻结点上仍是开放二选一，两个运行时可各自实现不同分支，终态与 observable trace 均分歧 | 将分支条件确定性化并写入 §2.2（例如：存在未收束 in-flight effect → `blocked_unknown_effect`，否则 → `failed`，failure_code 固定 `WORKSPACE_LOST`）；若确需政策，则政策本身必须作为版本化合同字段绑定到 session/run 并进入 portable 比较前提 |

### P2

| 编号 | 位置 | 问题 | 最小修复建议 |
|---|---|---|---|
| F-03 | §2.1 "有效 grant 当且仅当" | 有效性谓词只检查 grant 自身字段，未包含所属 slice 的 `revoked_at IS NULL`；slice 撤销后其下 grant 是否继续有效未规定（撤销传播缺口） | 在谓词中追加"所属 slice `revoked_at IS NULL`"，或明文规定 slice 撤销必须同事务/级联撤销全部相关 grant 并给出线性化点 |
| F-04 | §1.3 | "RFC 8785 JCS **或版本化等价子集**"仍允许两个实现各选一种；"等价"无判定程序，golden vectors 未强制（Conformance #10 只要求跨语言一致，未规定固定测试向量） | 定 JCS 为唯一 MUST，"等价子集"降级为需逐版本批准的例外；在 Conformance #10 增加强制 golden vector 集（Unicode/大整数/时间/空值）的字节级断言 |
| F-05 | §3.2.1 聚合规则 2 | sticky cancel 已请求且仍有 pending sibling 时，规则 2 只写"step `waiting_effect`；session 保持 `waiting_effect`"，未说明 step 是否应处于 `cancel_requested`（step 表存在 `cancel_requested → waiting_effect` "pending 时保持取消等待"的边，两处语义重叠），实现者可能一个走 cancel_requested 一个走 waiting_effect | 规则 2 补一句：sticky cancel 下 pending 未清时 step 聚合目标为 `cancel_requested`（保持取消等待），session 保持 `waiting_effect`；或在 step 表中删除歧义边之一 |
| F-06 | §1.1 vs §3.3/§5/§6 P2 | §1.1 写"MUST 支持 driver_mode 切换协议"，§3.3/§5 保留"无法满足屏障则 driver 创建后不可变、switch 返回 UNSUPPORTED"的回退，§6 又把"driver migration 是否支持"推迟到 P2 才明确。三者方向一致但 §1.1 的 MUST 字面上与"P2 再决定"存在张力 | §1.1 改为"声称支持切换的 driver MUST 遵循该协议；不支持切换的 driver MUST 创建后不可变且 switch 返回 UNSUPPORTED"，并在 §6 P0A 冻结项中固定该二选一语义，P2 仅决定各 runtime 的宣称 |
| F-07 | §2.2 状态闭合 | `uninitialized -> active -> handoff_ready -> {lost, discarded}` 字面上只允许 handoff_ready 之后进入 lost，但第 2 条允许 yield 前直接"追加 workspace/lost 并置 lost"（即从 active 入 lost）；闭合图与正文规则不完全吻合 | 闭合集改为 `active -> {handoff_ready, lost}`、`handoff_ready -> {lost, discarded}`，与第 2/3 条对齐 |
| F-08 | §3.1.2 命令表 / §5.2 | `transition_wait`、`transition_sleep` 未出现在 receipt 稳定结果表中（其幂等/receipt 语义仅靠通用段）；§5.2 引用"§6 第 5、6 条及第 15 条"而 Conformance #16 自身也是 compat blocked 条款，引用集合可再核对是否应含 #5 中 unknown 部分以外的条目 | 在 receipt 表补 wait/sleep 行（返回原等待条件 identity）；§5.2 引用复核一次（nit 级） |

### nit

| 编号 | 位置 | 问题 |
|---|---|---|
| F-09 | §3.2.1 派生表 | `blocked_unknown_effect` 的 step outcome_code 复用 effect 级 code `UNKNOWN_AFTER_DISPATCH`，语义正确但命名层级混用，建议后续改为 step 级别名或在表中注明复用关系 |
| F-10 | §0 不变量 17 vs §2.1 | 不变量 17 把 seam 调用、route 解析、`ready→dispatch_started` 并列，正文 §2.1 清单中"route 解析"未单独成条目（隐含于 tool_resolve/authorize_effect），建议 §2.1 点名一次以免实现漏检 |

---

## 4. 下一轮修复分组建议（针对剩余 P1）

两个 P1 相互独立，可分两组并行修复，均只涉及小幅状态表/谓词修订，不动整体架构：

1. **G1：初始 decision seal 状态边（F-01）** —— 修订 §3.2.1 `planned` 行 + §3.1.2 seal guard 2 的入口区分。建议与 Conformance #1（"prepare_step/seal_batch 重试只产生一个 sealed batch"）联动补一条初始 seal 的重放断言。
2. **G2：WORKSPACE_LOST session 后果确定性化（F-02）** —— 修订 §2.2 第 3 条，把"由政策决定"替换为确定性分支或版本化政策字段；同步在 Conformance #13 追加 session 终态断言。

P2 项建议在 P0A 冻结前一并扫掉 F-03（grant/slice 撤销传播）与 F-06（§1.1 MUST 措辞），其余可进入 P0B/P1 阶段处理。

---

## 附：审核方法与一致性核对记录

- 全文 547 行完整读取；对 8 项修复逐一核对"状态表 / 命令语义 / guard"三层落点，并与 §1.2 ABI 表、§3.2.2 取消 code 映射、§6 Conformance 最小集合做三方交叉。
- 闭合集核对：session 状态（10 值）、driver_mode（2 值）、step status（9 值）与 stage（3 值）、effect 状态图、workspace_handle 状态、receipt outcome（4 值）、retry_class（3 值）、EffectResult outcome（6 值）、取消 code 映射——除 F-01/F-07 外每状态均有出边或终态规则。
- 交叉引用核对：§1.1→§3.1.1、§1.2→§5、§3.1.2→§3.2.2、§3.2.1↔§3.2.2、§3.2.2→§6 #3、§5.2→§6 #5/#6/#15/#16，引用目标均存在且语义相符。
- §0 十八条不变量逐条对正文：均可找到对应强制条款（17→§2.1 seam 清单，18→§2.2，15→§3.1.1 driver_epoch 等）。
