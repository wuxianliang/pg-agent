# v8-dev Loop 2 · T1 P0 修订说明（2026-09-11）

- **修订对象**：`docs/designs/v8-dev.md`（本轮单一写入者串行修订；557 行 → 563 行）
- **依据**：Oracle L4 审核 `docs/reviews/v8-dev-oracle-l4-review-2026-09-11.md` 的 5 个 P0（L4-04 / L4-07 / L4-08 / L4-14 / L4-18），按本轮冻结裁定逐字落实；不以报告中的"最小修复建议"为准。
- **范围纪律**：仅修上述 5 个 P0；19 个 P1（L4-01~03、05~06、09~13、15~17、19~24）未触碰。此前 11 轮已闭合的 step 状态机 / 聚合规则 / 派生表 / 取消矩阵 / WORKSPACE_LOST failure-drain 均未回退、未削弱、未绕过。

---

## L4-04 · grant 充要条件缺 slice 撤销 / 租户一致 / 资源归属

- **改动位置**：
  - §2.1「有效 grant 当且仅当」谓词：改为全条件合取，并新增三个强制合取项（编号列表）——(1) 所属 slice `revoked_at IS NULL`，slice 撤销同事务级联失效其下全部 grant（或等效检查）；(2) grant / slice / 调用 session / 目标资源 `workspace_id` 租户一致，由复合外键或等效数据库约束强制；(3) 实际访问对象属于 `slice.spec` 资源集合，slice-membership 校验对所有 capability 统一执行，RLS 不得替代。
  - §0 不变量 17：补「有效性充要条件以 §2.1 为准，含 slice 未撤销、租户一致与 slice-membership」交叉引用（措辞对齐，不扩权）。
  - Conformance 14：补两个子断言——slice 已撤销但 grant 未撤销 → `GRANT_DENIED`；同租户、不同 slice 的资源访问 → `GRANT_DENIED`。
- **规范决策**：三项合取为强制项而非可选实现细节；「仅检查 grant 自身 revoked_at 不足以判定有效」显式写入，封死按字面实现漏洞。
- **波及交叉引用**：§0 不变量 12（数据库强制口径一致，未改写）；不变量 9/11 复核无需改写。

## L4-07 · workspace mutation 改为带完成态的受控操作 + fenced publish

- **改动位置**：
  - §2.2 第 1 条：mutation 模型改为固定三段受控操作——(i) DB CAS 登记（`op_seq+1`，op 级 `status=in_flight`，事务内禁外部 IO）→ (ii) 事务外执行 → (iii) fenced publish（同一 DB 事务写回 `status=completed` 并推进 checkpoint，digest MUST 覆盖最新已完成 `op_seq`/`generation`）。发布点 fencing：lease/fence 被接管后旧 worker 的 publish MUST 被 `owner_fence` CAS 拒绝，stale publish 不得写进 checkpoint，其事务外写入只能落 generation 私有对象/不可变区域。
  - §2.2 第 2 条（handoff）：MUST 在同一控制事务确认无 `in_flight` mutation 且 checkpoint = 最新已完成执行态，方可写 `handoff_ready`；无法证明走 `WORKSPACE_LOST`，MUST NOT 恢复「旧但 digest 自身正确」的 checkpoint。
  - §2.2 第 3 条（materialize）：同步增加「checkpoint 未覆盖最新已完成执行态（含未收束 in_flight mutation）」失败条件与同一禁止句。
  - §0 不变量 3（补 workspace handle 所有权 fence 与 publish 点拒绝）、18（补覆盖最新已完成执行态口径与禁止恢复旧 checkpoint）。
  - Conformance 13：补 checkpoint 覆盖判定与 fenced publish 拒绝断言。
- **规范决策**：单次 DB 前置 CAS 不再被视为充分隔离；迟到外部写入的隔离交给发布点 fencing + generation 私有区域。workspace handle 生命周期状态集（L4-06，P1）未触碰。
- **波及交叉引用**：§0 不变量 3/18；§3.1.1「所有这些事务都 MUST 遵守 workspace checkpoint/lost 既有规则」复核一致（未改）。

## L4-08 · turn 续行判定冻结为 decision_only 持久化合同

- **改动位置**：
  - §3.2.1 聚合规则 6：改写——`final_tools=true` tools batch 全成功 step 终态化后 session MUST `ready` 且 coordinator MUST 创建下一 decision step（「下一 step」存在性由 turn 未闭合这一持久化事实决定，禁止「无下一 step」非持久化判据）；`decision_only=true` decision step 成功即 turn 关闭 step，session 聚合仍 `ready`；聚合本身 MUST NOT 产生 `completed`。
  - §3.2.1 派生表「全部成功 terminalize」行：session 列由「ready 或 completed」改为「ready / NULL（completed 仅经 finish_session）」。
  - §3.2.1 多 step 聚合段：「否则全部成功 → completed」改为「→ ready（completed 仅经 finish_session）」。
  - §3.1.1 转移表 `claimed→completed` 行：finish_session guard 改为与聚合共用同一 SQL 判定函数——turn 内全部 step 成功且最后一个 step 为 `decision_only=true` 关闭 step，且无未密封计划或待处理工作；`completed` 仅经本行进入。
  - §3.1.2 初始 decision seal 段：在 `decision_only` 既有持久化字段定义处标注其为唯一 turn-complete 信号（引用既有字段，未新增第二字段）。
  - Conformance 5：补「工具→再决策→无工具回答」流程中间态断言（session=ready 而非 completed、coordinator MUST 创建下一 decision step、completed 无其他路径）。
- **规范决策**：`decision_only` 是 §3.1.2 既有持久化字段（decision completion 持久化 `decision_only`/`final_tools` 标记），本轮仅引用并声明其唯一信号地位；`completed` 收敛为 finish_session 单一路径，聚合与 finish_session 共用同一 SQL 判定函数。
- **波及交叉引用**：§3.1.1 转移表 `N→聚合目标` 行（聚合目标不再含 completed，自动一致）；§3.2.1 `ready`/`blocked_unknown_effect` 行中「聚合规则 6」引用复核一致（未改）；§1.1/§3.1.1 quiescing guard (iv) 引用复核一致（未改）。

## L4-14 · recovery 第 3 步重构为三个有序判定

- **改动位置**：
  - §3.2.2 recovery 接管第 3 步：由「(a) 结果已知性 / (b) 继续尝试资格」两判定重构为三判定，先来先决、不得合并或互相替代——(a) 结果已知性：证据四分类 `known_success | known_failure | known_cancellation | unknown`（仅绑定该 attempt 的可验证证据才算 known；无证据无论预算 MUST unknown，既有冻结原样保留）；(b) 结算：known_success/known_cancellation 照常结算不进重试判定，unknown → `unknown_outcome` 仅 repair；(c) known_failure 处置：先过执行许可 gate（sticky cancel 已设 / session 已因 §2.2 第 3 条 WORKSPACE_LOST 终态 / 所属批次已终态收束 / `driver_mode=quiescing` → MUST NOT 回 `ready`、MUST NOT 建新 attempt，走受控边 `failed_retryable -> failed_terminal`，保留原失败 code + audit `RETRY_STOPPED_BY_CLOSURE` + `retry_stop_reason`），gate 通过再判既有谓词 `retry_eligible`。cancel 等关闭条件 MUST NOT 塞进 `retry_eligible`（否则错改已知失败在取消下的分类）。
  - Conformance 3：补 gate 断言（关闭条件下 known_failure MUST 受控收束；gate + `retry_eligible` 双通过才可建下一 attempt）。
- **规范决策**：统一原 3(a)/3(b) 的证据类别（同一四分类）；受控边、audit 名、`retry_stop_reason` 有序分类函数全部复用 §3.2.2 既有闭合集合，未新增第二套。原第 3 步全部既有要求（预算耗尽≠已知失败、receipt/幂等细节、下一 attempt 前置条件）原样保留在第 4—6 步与新 (a)/(b)/(c) 中。
- **波及交叉引用**：§3.2.1 规则 5 / 派生表（`retry_stop_reason` 派生口径不变）；Conformance 11 quiescing 断言（既有，一致未改）；§3.3 repair 可接管状态集（L4-17，P1，未触碰）。

## L4-18 · append_events 事件类型权限矩阵 + §5.1 写入路径列

- **改动位置**：
  - §3.1.2 新增 append_events 事件类型权限矩阵段（闭合）：语义结果类事件（`assistant/message`(final)、`tool/result`、`turn/end {interrupted:true}`、`turn/end {outcome:unknown}`、repair closer 等——凡由 effect 终局/收束产生的语义结果）MUST 仅由数据库内部命令（`complete_effect` / `repair` / seal / `request_cancel` 收束 / `reconcile`）生成并绑定其生成 identity；公开 `append_events`（含 §5 compat append facade）仅允许白名单输入类/观测类事件（`user/message`、`agent/inject`、`assistant/chunk`、heartbeat 等）；越权 MUST 稳定拒绝（新闭合 code `EVENT_TYPE_RESTRICTED`，落 `rejected_mismatch` receipt 并保留具体 code）；`logical_event_key` 唯一性保留为兜底防线。
  - §3.1.2 命令 receipt 表 `append_events` 行：补权限矩阵约束引用。
  - §5 首段：「所有事件经受控 append facade 写入」改为「统一受控路径」——语义结果类按 §5.1 写入路径路由 ledger 命令（compat 经 completion/repair facade），不得经公开 append facade 直接写等价语义事件；输入/观测类经白名单 append facade。
  - §5.1 映射表：新增「写入路径」列——assistant final / tool result / turn/end（normal 与 interrupted）MUST 路由到对应 ledger 命令；chunk / user message / inject / turn start 走白名单 append facade；compaction 走控制平面；load() closer 走共享 repair。
  - Conformance 1：补断言——公开 append 追加语义结果类事件 MUST 稳定拒绝 `EVENT_TYPE_RESTRICTED` 且不写任何语义事件；白名单正常追加；completion facade 路由后仍只产生一批事件。
- **规范决策**：`EVENT_TYPE_RESTRICTED` 为新闭合拒绝 code，登记于 §3.1.2 receipt 拒绝体系（`rejected_mismatch` 具体码）、命令表、§5 首段、§5.1 表与 Conformance 1 五处，保持闭合；`RETRY_STOPPED_BY_CLOSURE` 为既有闭合 audit 名，本轮仅复用。
- **波及交叉引用**：§2 capability API `event_append`（「受控 API」表述一致，未改）；§3.3 append_events seq 分配机制（未改，与矩阵正交）。

---

## 附加一致性对齐（未扩权、未触碰 P1）

- §0 不变量 3/17/18 仅做措辞对齐；7/9/11/12 复核一致无需改写。
- 裁定未指定 Conformance 落点的 L4-07 / L4-14，按闭合性纪律在 Conformance 13 / Conformance 3 增补了直接复述冻结文本的子断言，未引入新行为。
- §5.1 新增「写入路径」列对裁定未逐一列举的行（turn start 归白名单输入类、normal turn/end 归 turn 关闭路径数据库内部命令、tool/call 归受控 seal/ledger 路径——其 `effect_id` 绑定为既有要求）做了与裁定类别一致的具体化，供复核确认。
