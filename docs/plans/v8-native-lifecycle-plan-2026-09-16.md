# V8 Native 生命周期补全计划（P0A 剩余冻结件）· 2026-09-16

> **交付状态（2026-09-16 完成）**：G6 tools seal ✅ 333 PASS / G7 retry+takeover+repair ✅ 602 PASS / G8 cancel 收束族 ✅ 315 PASS / G9 流式 grammar ✅ 139 PASS。全部 13 gate 合计 **2312 PASS**。偏差台账与 Conformance 矩阵随各 stage 更新（见 `docs/reviews/`）。

基线：G1–G5 全绿（930 PASS / 0 FAIL），P0A 核心 + P0B 闭环已交付（见 `v8/README.md`）。本计划把规格中已实现范围之外的 **Native 效应生命周期** 冻结件补全，全部纯本地可测、无外部依赖（P0C/pinned DSH 另行排期）。

实现依据：原文 `docs/designs/v8-dev.md`（权威）+ `docs/analysis/v8-impl-digest/` 分节摘要。前置台账：
- 偏差台账：`docs/reviews/v8-p0ab-deviation-ledger-2026-09-16.md`
- Conformance 覆盖矩阵：`docs/reviews/v8-p0ab-conformance-matrix-2026-09-16.md`

## Stage 划分（顺序执行，前一 gate 不过不进下一个）

### G6 tools seal 与工具批次（`v8/tools/`，库 `agent_v8_tools`）

合同：摘要 s31b §2.6.2（tools seal 四步）、s32a §4.1 step 状态机、Conformance 1/5/7 相关断言。

1. `complete_effect` 扩展：非空 tools plan 的成功 decision result → step 聚合 `ready, stage=decision`、冻结 `decision_result_identity=(effect_id, attempt_no, result_hash, event_key)` 与 `plan_hash`/`plan_canonical`（既有列），**不 terminalize**；session 回 `ready`（中间态 MUST `ready` 非 `completed`——「工具→再决策→无工具回答」流程，Conformance 5）。
2. `seal_batch` 命令（tools seal 四步，逐字）：(i) 先查 command receipt 与唯一 seal receipt（相同 result/batch identity + plan_hash + slot payload 重放即使换 command_id 返回原 seal receipt、为新 command_id 保存引用；不一致 mismatch）；(ii) 锁 session/step（主锁序）、CAS `ready, stage=decision` + expected sealed_batch_no + driver/epoch/fence + active + 无 sticky cancel、核验 decision result identity、按持久化 plan 重算匹配 plan_hash、`final_tools=true`；(iii) 同事务写 `stage=tools`、`sealed_batch_no+1`、batch identity、slot manifest、全部 tool effect（`create_effect_in_seal` 构建模式：首个 attempt 同事务、发布即 ready）、密封、聚合 `waiting_effect`；(iv) terminalize 条件：仅 `decision_only=true` 成功 decision 或 `final_tools=true` 全成功 tools batch → `stage=closed`。
3. tool effect 的 dispatch/complete 复用 G4 通道；`tool/result` 语义事件由 SQL 生成；slot 级 occurrence identity（同 batch 同工具同参数两 slot → 两条独立 `tool/call` 事件，Conformance 1(4)）。
4. coordinator 续行：`final_tools=true` 批全成功 → 创建下一 decision step（额外决策 MUST 新建 step）；`decision_only=true` 关 turn（既有）。
5. 并行工具反序完成按 ordinal 聚合得到相同 trace（Conformance 7）。
6. 验收：上述全部 + seal 幂等/CAS 负向零副作用 + chaos（工具阶段边界 kill 重跑收敛）+ 五 gate 全量回归。

### G7 失败/重试/接管 + repair（`v8/retry/`，库 `agent_v8_retry`）

合同：摘要 s32a §3.2/§3.3（retry_eligible/retry_stop_reason/recovery 接管六步）、s32b §2.1/2.2/2.7（retry_cohort_allocation 六步、superseded 语义、repair）、Conformance 2/3/5。

1. **G7a 失败结算与重试**：`known_failure` 双要件（失败回执 + 已持久化「外部副作用未发生」证据）开启结算；`retry_eligible` 谓词（预算 + retry_class + 证据持久化，grant 不是谓词输入）；`retry_cohort_allocation` 共享子操作六步（虚拟聚合→cohort 冻结→授权检查（P0B 无 grant 模型，此步恒过并注记）→generation 门（同上）→同事务分配（`attempt_no+1`、复用 identity、旧 attempt 写 `superseded_by_attempt_no`、effect 回 `ready` 一次提交）→分配后最终聚合）；`retry_effect` 命令（两入口之一）；聚合规则 4/5 与 `retry_stop_reason` 有序分类、`FAILED_RETRYABLE`/`FAILED_TERMINAL`/`FAILED_RETRY_BUDGET_EXHAUSTED` 派生；`fail_session` 第 (1) 类来源（规则 4 批次）。
2. **G7b recovery 接管**：无结果 in-flight attempt 的单一事务接管（八位锁序子集、job lease guard——仍有效则跳过、CAS 推进 `current_job_fence`、撤旧 lease、旧 attempt 结算 unknown 或取代、cohort 命中则原子分配、effect 置 ready）；接管后旧 completion stale-reject（既有 STALE_JOB_FENCE 路径联测）；`superseded` 四条断言（Conformance 2）；两表一致性。
3. **G7c repair**：unknown 唯一出口；`REPAIR_EVIDENCE_REQUIRED`（仅「副作用未发生」证据或状态不明失败回执不获采信）；closer 追加（`closer_event_key@v1`、`turn_end_closers` 表启用、`(v)` 六条校验、resolution 唯一约束幂等、supersedes 链头 CAS、`REPAIR_TARGET_INVALID`）；槽位受保护更新函数（G2 GUC 通道的正式使用方）；normalize 消费 closer 取代 provisional（canonicalizer 补 supersedes 处理）；`blocked_unknown_effect` 恢复出边（规则 5 补全、`ready, stage=decision` 受控恢复出边）；混合 sibling 验收（unknown+retryable → blocked → repair 证实 → 规则 5 收束）。
4. 验收：Conformance 2/5 强制用例子集（入口一致性、纯 eligible 批次两路径对照、证据分类一致性、unknown repair 三终态、双表/fence/superseded 断言）+ chaos（kill 后 lease 到期接管收敛）+ 全量回归。

### G8 request_cancel 收束族（`v8/cancel/`，库 `agent_v8_cancel`）

合同：摘要 s31a（request_cancel/粘性 latch/无活跃工作分支三窗口）、s32b §2.8/2.9（共享取消收束、pre-dispatch 双表同步）、Conformance 6/15。

1. `request_cancel` 命令：粘性 latch（`cancellation_epoch` 递增）、无活跃工作分支三窗口同事务收束（含 turn/end 派生——reducer 优先级 (2) 二分 before/after dispatch）、与 `finish_session` 竞争两提交序。
2. 共享取消收束子操作 `shared_cancel_closure`（五出口、AG01 触发源、`CANCELLED_BY_REQUEST_AFTER_DISPATCH`/`RETRY_SUPPRESSED_BY_CANCEL`/`COMPLETED_AFTER_CANCEL`）；cancel-wins 矩阵（sticky × provider）。
3. pre-dispatch 取消双表原子同步（`cancelled_before_dispatch`/`ABORTED_BEFORE_DISPATCH`，迟到 completion 拒绝）。
4. cancel 与 dispatch/finish 并发按数据库线性化点分类；混合取消 turn fixture（reducer 输出唯一 end、sticky 优先 provider——Conformance 15）；终结资格 guard 负向（pending sibling 无已知 end）。
5. 验收：Conformance 6/15 相关强制用例 + chaos + 全量回归。

### G9 流式 grammar（`v8/stream/`，库 `agent_v8_stream`）

合同：原文 §1.2 流完整性屏障 + §3.2.2 计数 ABI grammar（摘要 s32b §3.2）、Conformance 10。

1. `execution_mode='streaming'` 的 descriptor/attempt 创建（列已有）；`assistant/chunk` 六项归属校验补第 (2) 已结算分支（(3)(6) 依赖 grant 模型——本 stage 以最小 grant stub 或注记降级，见风险）。
2. `stream_complete` 字段矩阵五形态（O04）：`true`∧计数（恰一/并存 C=N+1）→ 完整流；缺失（无论有无计数）与 `true`∧无计数 → 结构层 schema reject（四步序第 (iii) 步，证据分类之后）；`false`∧计数完整/缺失 → pending observation（`stream_progress` 观测事件、observation receipt 三元组 `(attempt_no, observation_ordinal, payload digest)`、控制态零修改、五款状态门）。
3. 计数 ABI：收齐 = 集合精确相等 {0..N} / {0..C-1}、`C=N+1` 并存校验、`final_chunk_index ≤ 2^63-2`、`chunk_count ≤ 2^63-1`、额外 index 超范围判据（F4 直接记冲突不等值推导）、值域边界 vectors（2^53-1 number / 2^63-1 tagged / 2^53 裸拒 tagged 收 / 2^63 全拒）。
4. 等值断言时序：final 先到尾部 chunk 未到 → pending、窗口内补齐执行、窗口耗尽按证据分类（`STREAM_INCOMPLETE`）；三表示对照（仅 N / 仅 C / 并存）判定一致。
5. `assistant/partial` 合成（unknown/cancelled 路径前缀）；`CANONICALIZER_CONFLICT` 双层（normalize 仍通过 + 验收器读持久化冲突事实判失败）；canonicalizer 流事件消费（已有合并规则接线）。
6. 验收：Conformance 10 流完整性屏障时序用例 + 字段矩阵五形态 vectors + 计数边界 vectors + chaos + 全量回归。

## 依赖与风险

- **G9 的 chunk 第 (6) 项**（调用方归属三合取）依赖 §2.1 grant 模型：届时插入最小 grant stub（slices/grants 表 + 有效 grant 谓词）或注记降级，在 G9 开工时定。
- **G7 接管与 G8 cancel 的交互**（sticky 下共享收束）跨 stage：G8 必须在 G7 之后；两 stage 合同互引处以原文为准。
- 每 stage 新 SQL 追加 `v8/load.py`；不得破坏既有五 gate（每 stage 全量回归）。
- 各 stage 完成后更新 Conformance 覆盖矩阵与偏差台账。

## 明确不做（本轮之后另行排期）

P0C compat（需 pinned DSH Node host，环境未确认）、§2.1 完整 grant/slice 模型与 §4 插件世代（P1）、driver epoch 切换、compact 三命令、WORKSPACE_LOST/INFRA failure-drain、audit 指纹三键与 occurrences 子表、fork。
