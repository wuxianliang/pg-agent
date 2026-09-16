# V8-dev 全文 L4 独立审核（2026-09-11）

- **审核者**：Oracle（chat `new-chat-12A856`，全新会话，声明"审核依据仅为本次提供的选区全文，不引用其他设计稿或既有审核结论"）
- **对象**：`docs/designs/v8-dev.md`（2026-09-10 17:27 版本，约 590 行 / 88KB，即 11 轮修复后的"冻结"版本）
- **结论**：**全文存在 P0 和 P1 缺陷，当前版本尚不具备协议冻结条件**（5 P0 + 19 P1）
- **重要背景**：本审核推翻了 2026-09-10 的终裁（"无 P0/P1"）。昨日终裁的全文复扫是增量聊天中的快速扫描；本审核是全新深审。审核同时复核确认：此前 11 轮修复的 step 状态机/聚合规则/派生表本身闭合（见文末复核表），新发现集中在未深审区域与旧 P2 的升级。

---

## 一、Canonicalizer 与规范化 ABI

### L4-01 · P1 — chunk 的重排、去重与 attempt 归属未冻结

- **位置：**§1.2 canonicalizer 表；§3.1.2 事件 key；§6 Conformance 10。
- **问题：**正文只规定"按 seq 合并 chunk"，但 Conformance 要求覆盖 chunk 乱序、重复。`seq` 是数据库接受顺序，不是 provider 的流内顺序；正文没有规定 chunk 的稳定身份、流内序号、重复判据及 retry 后采用哪个 attempt 的前缀。同一逻辑输出可能因传输重复或重试残留被拼接两次，进而触发 final/chunk conflict。仅规定事件属于 observational 不能解决这个问题。
- **最小修复建议：**冻结流事件最小字段和规则，例如 `(effect_id, attempt_no, stream_id, chunk_index)`；明确重复同内容去重、同 index 异内容冲突、乱序重排，以及被取代 attempt 的 chunk 是否排除。将这些规则加入 Conformance 10 的跨运行时 golden fixtures。

### L4-02 · P1 — 已知终局的 turn 级归并规则不完整

- **位置：**§1.2 provider cancellation、sticky-cancel cancellation、repair closer 各行及其后优先级说明。
- **问题：**多个 unresolved unknown 已明确归并成一个 `turn/end`，但多个**已知**终局没有同等完整的归并规则。例如同一 turn 中，一个 effect 是 `CANCELLED_BY_PROVIDER`，另一个是在 sticky cancel 下收束为 `CANCELLED_BY_REQUEST_AFTER_DISPATCH`，对应两行分别要求输出不同 reason 的 `turn/end`。正文没有确定应保留哪一个、是否允许多个，亦未完整定义它们与已有 normal `turn/end`、repair closer 的竞争关系。控制层 cancel-wins 不能自动补成 canonicalizer 的事件归并规则。
- **最小修复建议：**增加唯一的 turn-finalization reducer：规定每个 turn 至多一个 canonical end，并冻结 unknown、sticky cancellation、provider cancellation、failure、success 的优先级和 payload；明确 repair 如何替换 provisional end，以及重复 closer 的逻辑归属。

### L4-03 · P1 — canonical JSON 的"版本化 profile"尚未真正定义

- **位置：**§1.3；§3.1.2 `command_request_hash`；§6 P0A、Conformance 10。
- **问题：**"RFC 8785 JCS 或版本化等价子集"、NFC、RFC 3339 UTC、大整数 string/tagged type 仍不足以唯一决定接受范围与 hash。尤其未规定：
  - 非 NFC 输入是拒绝还是转换，以及规范化后对象 key 冲突如何处理；
  - 时间小数秒、等价 UTC 表示是否保留或归一；
  - tagged integer 的具体 schema；
  - schema 校验、Unicode/时间处理、JCS 序列化的精确顺序。

  SQL 重算 hash 与 Node/Python 等端可能各自符合这些文字要求，却得到不同字节。
- **最小修复建议：**冻结具名 `canonical_profile_version`，明确接受/拒绝规则、转换顺序、序列化字节与 hash 算法；提供包括 key 碰撞、时间等价形式、大整数边界在内的 golden vectors，并使 command、effect、result、manifest hash 共用该 profile。

## 二、grant、slice 与 workspace

### L4-04 · P0 — 有效 grant 的充要条件遗漏 slice 撤销与资源绑定

- **位置：**§0 不变量 9、11、12、17；§2.1 "有效 grant 当且仅当"。
- **问题：**该充要条件检查 grant 自身的撤销、时间、subject、capability 和 constraints，却没有要求：
  1. 被引用 slice 的 `revoked_at IS NULL`；
  2. grant、slice、调用 session 和目标资源具有一致的租户归属；
  3. 实际访问对象属于 `slice.spec` 指定的资源集合。

  因而按字面实现时，撤销 slice 后原 grant 仍可被判定有效；同租户内也可能只检查 constraints 而越过 slice 边界。RLS 无法替代 agent 内资源授权。
- **最小修复建议：**把上述三项加入授权判定的强制合取条件；用复合外键或等效数据库约束保证租户绑定，并对所有 capability 统一执行 slice-membership 校验。新增"slice 已撤销但 grant 未撤销"和"同租户、不同 slice"拒绝测试。

### L4-05 · P1 — 同事务检查 grant 不等于与撤销线性化

- **位置：**§0 不变量 9、17；§2.1；§3.3 manifest snapshot；§3.2.2 dispatch gate。
- **问题：**未规定 grant/slice 撤销与 dispatch 的锁或版本 CAS 协议。一个事务读取有效 grant 后，另一个事务可以撤销并提交，前者随后仍提交 `dispatch_started`；"在同一事务检查"本身没有冻结该竞争的胜负规则。此外，assemble 的 manifest 绑定与 dispatch 时"当前有效 grant"之间，哪些是固定快照、哪些必须实时重验，也未区分。
- **最小修复建议：**定义授权线性化点、数据库时钟口径及撤销参与的锁/CAS 协议；冻结 slice/spec/constraints 的版本或不可变性。明确"模型可见集合使用固定 manifest，实际派发仍按当前撤销状态重新授权"，并覆盖 revoke/dispatch 并发测试。

### L4-06 · P1 — workspace 的闭合状态图不支持正文要求的生命周期

- **位置：**§2.2 开头状态图及第 2、3 条。
- **问题：**声明的闭合图是：`uninitialized -> active -> handoff_ready -> {lost, discarded}`。但成功 materialize 后下一 worker 必须重新使用 workspace，缺少 `handoff_ready -> active`；active 状态直接检测到丢失、完成或失败时，也分别需要正文实际要求的 `active -> lost/discarded`。首次初始化、接管后的 owner fence 更新，以及 lost 与 fail 后 discarded 的关系没有闭合定义。
- **最小修复建议：**改成完整迁移表，分别列出首次初始化、checkpoint、成功 materialize、异常丢失和最终丢弃；为每条边规定 owner fence、generation、checkpoint 字段的原子更新及是否保留 lost 诊断信息。

### L4-07 · P0 — workspace 的 DB 前置 CAS 不能隔离迟到的外部 mutation

- **位置：**§0 不变量 3、18；§2.2 第 1—3 条；§3.1.1 异步 completion/cancel 撤销协调 lease。
- **问题：**规定的是 mutation **之前**增加 `op_seq`，随后才进行事务外文件/REPL 操作。存在以下窗口：旧 worker CAS 成功，随后 lease 被撤销或接管，新 worker materialize，旧 worker 的实际写入才完成。单次 DB 前置检查不能阻止该迟到写入，也不能证明 checkpoint 覆盖的 `op_seq` 对应的操作已经完成。正文还没有要求恢复时 checkpoint 的 op_seq/generation 必须覆盖最新已提交执行态，而不只是 digest 自身正确。
- **最小修复建议：**将 workspace mutation 定义为有完成状态的受控操作，并在实际存储发布点执行 fencing；可采用 generation 私有对象、不可变 checkpoint 和 fenced publish CAS。handoff 必须确认无未收束 mutation，checkpoint 与最新已完成 op_seq/generation 一致；无法证明时走 `WORKSPACE_LOST`，不得恢复旧但 digest 正确的 checkpoint。

## 三、Session、step 与命令协议

### L4-08 · P0 — step 成功被错误地用作 session/turn 完成依据

- **位置：**§3.1 logical step 定义；§3.1.1 `finish_session`；§3.2.1 聚合规则 6。
- **问题：**规则 6 写成"step 成功，有下一 step 则 session=ready，否则 completed"，但没有持久化字段或 SQL 判定规则定义"有下一 step"。`final_tools=true` 仅保证当前 tools 批次是该 step 的最终批次，并不证明 turn 已结束。正常的"模型发出工具调用 → 工具完成 → 再做一次模型决策"流程，在下一 step 尚未创建时会被直接置为 `completed`，与 `finish_session` 要求 SQL 确认 turn 结束冲突。
- **最小修复建议：**冻结由 SQL 消费的持久化 continuation/turn-end 决策。step 成功但 turn 未关闭时应进入 `ready`；只有明确的 turn-complete guard 才允许 session `completed`，并与 `finish_session` 共用同一判定函数。

### L4-09 · P1 — 多 step session 的 reducer 不是完整函数

- **位置：**§3.1 `active_step_id`；§3.1.2 `create_step`；§3.2.1 最后一段多 step 聚合。
- **问题：**单批次六条规则均有 step/session 目标，但多 step 归并段只列 unknown、cancel、terminal failure、全成功，未完整规定 pending、`failed_retryable`、等待 tools seal 的 `ready`、尚未 seal 的 `planned` 等组合。同时，没有明确约束"同一 session 是否至多一个非终态 step"。若允许多个，`failed_terminal` step 与 pending step 共存时，该段的 failure 分支会与"pending 时禁止 terminal session"冲突；若不允许，则"有下一 step"的表示仍需说明。
- **最小修复建议：**二选一冻结：数据库强制单一非终态 active step，并定义后继计划如何表示；或提供完整的跨 step reducer。明确 active_step_id 的设置、清除、校验和 session code 的唯一派生。

### L4-10 · P1 — `fail_session` 是已公布但未闭合的命令

- **位置：**§3.1.1 转移表；§3.1.2 命令清单；§3.2.1 失败 code 闭合集。
- **问题：**除 WORKSPACE_LOST 专门路径和 effect failure 聚合外，未定义 `fail_session` 的合法原因、前置状态、pending/unknown 处理、step 目标及 failure code。对于尚无 effect 的 `planned` step，状态表只允许 WORKSPACE_LOST 导致 `failed_terminal`；一般协议/assemble 失败应如何执行该公开命令没有合法路径。
- **最小修复建议：**明确 `fail_session` 是否仅为既有失败聚合的内部入口。若支持独立失败，补充闭合原因集合、step/session 目标、未派发与 in-flight effect 的 drain 规则及 receipt；若不支持，删除其独立公开语义。

### L4-11 · P1 — seal 内部创建与 `create_effect` 的已 seal 前置条件形成循环

- **位置：**§3.1.2 初始 decision seal、tools seal 第 3 条；§3.2.2 batch-slot 校验。
- **问题：**seal 要在同一事务创建全部 effect 后完成密封；但 `create_effect` 又必须验证 batch 是当前"已 seal"的 batch，且 seal 后不得补建 effect。正文未区分 seal 事务内部的构建子操作与 seal 后公开调用，按这些前置条件直接实现会出现"未 seal 不能创建，已 seal 不能补建"的循环。
- **最小修复建议：**明确内部 `create_effect_in_seal` 可针对本事务尚未发布、manifest 已冻结的 batch 创建成员，最后一次性标记 sealed；公开 `create_effect` 在 sealed batch 上只能进行同 slot 同请求的 lookup/replay，不能插入。

### L4-12 · P1 — 错误的声明 hash 与 receipt 唯一键之间缺少完整规则

- **位置：**§3.1.2 `command_request_hash`、receipt 先返回规则及 mismatch 规则。
- **问题：**正文同时要求 SQL 按实际请求重算 hash、声明 hash 不匹配必须拒绝、同一 receipt key 必须先返回原结果、所有拒绝必须持久化稳定 receipt。若某请求已经接受，随后同 command_id、同实际 payload 仅携带错误的声明 hash，实际 canonical hash 仍命中原 receipt：应返回 accepted 还是 mismatch？若另存拒绝，使用声明 hash 还是实际 hash 作为键也未冻结。
- **最小修复建议：**区分 `received_request_hash` 与 `computed_request_hash`，明确 hash 校验和 receipt lookup 的顺序；为 malformed-envelope 拒绝定义独立稳定键或拒绝记录规则，避免与已接受请求的 receipt 冲突。补充"正确 payload、错误声明 hash"的前后顺序测试。

## 四、Effect、recovery 与 retry

### L4-13 · P1 — retry budget 的作用域与规则 5 的混合集合语义未冻结

- **位置：**§3.2.1 `steps.retry_count/max_retries`、聚合规则 5、派生表；§3.2.2 `retry_eligible`、`retry_stop_reason`。
- **问题：**预算字段仅明确列在 step 上，但谓词和停止原因按 effect 描述，没有规定预算是每 effect、每 batch 还是每 step，以及并行 sibling 如何消耗预算。规则 5 又以"任一 eligible retryable"进入可重试分支，而其否分支按"存在 ineligible retryable 或 budget-exhausted terminal"描述。特别是在采用 effect 级预算时，eligible sibling 与 budget-exhausted terminal sibling 共存的结果，不能仅从派生表获得无歧义答案。
- **最小修复建议：**冻结预算作用域、初始值、递增时点及并发分配顺序；把规则 5 改写为互斥、穷尽的集合判定，明确终态预算失败是否关闭整个批次。为 `retry_stop_reason` 保存足以判断"创建时即无资格"的历史事实，不能依赖可变当前字段反推。

### L4-14 · P0 — recovery 的 safe-retry 分支没有纳入 sticky cancel/失败关闭

- **位置：**§3.1.1 sticky cancel；§2.2 failure-drain；§3.2.2 recovery 第 3、4 步及共享取消子操作。
- **问题：**`retry_eligible` 只包含预算、retry class 和证据；recovery 第 3 步只额外区分 quiescing。于是 active 模式下，已设置 sticky cancel、仍有 in-flight attempt 的 session，在 recovery 获得确定失败证据且预算可用时，按该流程仍会提交 `dispatch_started -> ready` 并进入下一 attempt 路径。这与禁止取消后 retry、共享取消收束及 WORKSPACE_LOST 后禁止恢复工作直接冲突。
- **最小修复建议：**把结果已知性、失败的安全重试资格和**当前是否允许继续执行**分成三个判定。先应用 sticky-cancel、WORKSPACE_LOST、批次关闭和 quiescing 收束，再决定是否允许返回 ready；不要简单把 cancel 塞进安全资格谓词，否则又会错误改变已知 retryable failure 的取消分类。

### L4-15 · P1 — recovery 两事务边界留下可派发但无新 attempt 的中间态

- **位置：**§3.2.2 recovery 第 3、4 步；effect 状态图；§0 不变量 8。
- **问题：**第 3 步让 effect 回到 `ready`，第 4 步却要求该事务提交后才能创建下一 attempt。由此存在持久化窗口：effect 已 ready，但当前 attempt 已被失效且下一 attempt 尚不存在。正文没有给出该窗口的控制标志、dispatch 禁止条件、下一 attempt 的幂等分配命令及扫描恢复规则；`retry_effect` 的既有前置状态又是 `failed_retryable`。
- **最小修复建议：**引入明确的 recovery-pending 标志/子状态，或其他不可派发的持久化表示；规定只有新 attempt 已原子分配并具备合法 envelope 时才能进入可派发 ready。为两次提交之间的 crash 增加扫描恢复和重复创建 CAS 测试。

### L4-16 · P1 — recovery 的"结果已知性"定义排除了随后要求处理的成功和取消

- **位置：**§3.2.2 recovery 第 3(a)、3(b) 步。
- **问题：**3(a) 的"仅当"列举 provider 确定失败或外部副作用未发生的证据，否则必须 unknown；3(b) 却要求"已知成功/取消照常结算"。两处没有统一的证据类别与处理顺序。若扩展 3(a) 接受成功证据，非 quiescing 分支的"结果已知且满足 retry_eligible"又不能被原样当成重试 guard，否则可能把已知成功送入 retry 路径。
- **最小修复建议：**先将证据分类成 `known_success / known_failure / known_cancellation / unknown`，分别结算；只有 `known_failure` 才进入 retry 判定。冻结每类证据需要的 attempt binding、payload 与接收路径。

### L4-17 · P1 — recovery claim 的交叉引用遗漏主要修复状态，并混淆空 lease 与过期 lease

- **位置：**§3.1.1 recovery_claim；§3.3 repair 项。
- **问题：**§3.1.1 允许在任意非终态、lease 空缺或过期时 recovery claim；§3.3 的可接管枚举却遗漏 `blocked_unknown_effect` 和 `cancel_requested`，且写成必须校验"过期 lease_until"，未包含 lease 空缺。照 §3.3 实现会阻断最需要 repair 的 unknown 状态，或因 NULL expiry 无法取得 recovery lease。
- **最小修复建议：**删除重复的不完整枚举，直接引用 §3.1.1 的闭合集和 `lease IS NULL OR expired` guard；保留 WORKSPACE_LOST 与既存 switch intent 的终态例外即可。增加无 lease 的 blocked/cancel 状态 recovery 测试。

## 五、事件权威性、compact 与 fork

### L4-18 · P0 — 公开 append 与 compat 映射仍可绕过 effect ledger 生成语义结果

- **位置：**§2 capability API；§3.1.2 `append_events`、`complete_effect`；§5、§5.1。
- **问题：**`complete_effect` 禁止 worker 携带任意 events，并要求 SQL 生成 canonical 结果；但 `append_events` 没有冻结可接受的事件类型及其控制态绑定要求。§5 又要求 compat 的 assistant final、tool result 等经 append facade 写入。按字面实现，持有 append capability 的调用方可直接追加成功 `tool/result` 或 `assistant/message`，而不接受对应 effect completion；也可能先 append，再由 completion 重复生成，造成 history 与 ledger 两套事实。
- **最小修复建议：**保留结果、取消、closer 等事件类型为数据库内部专用，必须绑定已接受 completion/repair/seal 的生成 identity；公开 append 仅允许明确列出的输入和观测事件。compat facade 对结果事件必须路由到 ledger 命令，由该命令原子追加，不能直接插入等价语义事件。

### L4-19 · P1 — compact 的"谁先提交谁赢"缺少可执行的互斥 guard

- **位置：**§3.3 compact；§3.2.2 dispatch gate；§6 Conformance 6。
- **问题：**"创建 compact lock 与创建 LLM effect 都锁 session 行"只能串行化事务，不能单独定义互斥。正文没有完整规定已有 LLM effect 时哪些 compact 状态必须拒绝，以及已有 compact lock 时 LLM create/dispatch 是拒绝还是等待；stale compact lock 接管后的旧 owner 提交 guard 也未冻结。"保持既有规则"没有指向可作为本合同组成部分的完整定义。
- **最小修复建议：**增加 compact 控制状态表、锁冲突矩阵、稳定返回码和 fenced finalize/abort 操作；定义固定 through_seq 的输入及输出如何提交。Conformance 6 应分别覆盖两个先后顺序与 stale owner 提交。

### L4-20 · P1 — fork 固定切点与 unresolved unknown 的继承缺少闭合规则

- **位置：**§1.2 unknown/repair；§2.2 fork；§3.3 fork。
- **问题：**子会话固定继承 parent cutoff 内事件，父会话随后 repair 不得改变子历史。若 cutoff 内已经包含 provisional unknown，父 repair 又位于 cutoff 之后，子会话会保留 unresolved unknown；正文没有说明该 unknown 是否允许继承、是否复制控制态，或如何在子 session 内合法修复父 effect identity。直接使用父 effect 当前控制态消除 unknown 又会违反固定历史切点。
- **最小修复建议：**明确 fork guard：最小方案是禁止继承未决 effect/unknown 所在的未闭合范围，要求选择更早的稳定切点；若要支持，必须定义子会话自己的 resolution/source binding、权限和独立修复语义。

## 六、插件、compat 与 Conformance

### L4-21 · P1 — 插件实现的绑定键和确定排序口径不完整

- **位置：**§4 `plugin_specs`、`plugin_implementations`、唯一键及拓扑排序。
- **问题：**
  - implementation 记录没有明确的 contract-version 绑定字段，却要求以 contract_version 参与唯一性；
  - 唯一键省略 driver，未说明同 identity/contract/locus/plugin_version 的 Native 与 compat 实现如何共存；
  - 排序和登记使用 `implementation_version`，目录字段却名为 `plugin_version`；
  - `identity ASC`、version ASC 未规定跨 SQL/宿主运行时一致的比较口径。

  这些会影响实现解析、冲突判定和 generation 内容，而非仅是命名风格。
- **最小修复建议：**冻结 implementation 到具体 plugin contract 的外键，明确 driver 是否属于实现身份；统一 version 字段名及版本比较方式，并规定字符串使用固定二进制/Unicode 比较规则，不依赖数据库 locale 或宿主默认排序。

### L4-22 · P1 — generation 发布状态图缺少构建失败出口

- **位置：**§4 `building -> active -> retired|failed`；§6 Conformance 8。
- **问题：**完整扫描、digest 校验、依赖解析、预加载都可能在激活前失败；但图中只有 active 后的 failed 出口。若按该生命周期实现，失败候选只能永久停留 building，或先进入 active 再失败，后者与 refresh 失败不得改变 active generation 的要求冲突。
- **最小修复建议：**补充 `building -> failed`，规定失败候选不得发布 active 指针；明确 active 运行期故障是独立的 generation failure，还是 readiness/健康状态变化，避免混用两种失败。

### L4-23 · P1 — compat 降级能力与 Conformance blocked 清单不匹配

- **位置：**§5.2；§6 Conformance 1—3、11、13、16；P0C 路线。
- **问题：**`dispatch_interception ≠ sync_before_io` 时，只明确将第 5、6 条和第 15 条中的取消/unknown fixture 标记 blocked；但第 3 条也直接测试 dispatch 后 unknown/recovery，第 11 条涉及 in-flight 切换收束，第 13 条涉及 WORKSPACE_LOST 后 in-flight completion/unknown。未定义这些测试的 capability 依赖，容易出现同一缺失能力只阻塞部分条目，其余被错误记为 portable 通过。
- **最小修复建议：**建立 fixture/subcase → capability 的显式矩阵，而不是只引用几个总编号。P0C 验收前必须生成完整的 passed/failed/blocked 报告；`compat-only` 也应作用于明确的插件/fixture 支持范围，不能仅丢弃不支持的事件后仍宣称该 fixture portable。

### L4-24 · P1 — Conformance 5 把"无 provider 幂等"错误等同于 unknown

- **位置：**§6 Conformance 5；§0 不变量 7；§3.2.2 recovery 第 3 步、`retry_class`、`retry_eligible`。
- **问题：**Conformance 5 写成"provider 无幂等能力时进入 unknown，不自动重放"。正文则明确区分结果已知性与重试资格：即便 provider 不支持幂等，只要有绑定当前 attempt 的可验证"副作用未发生"证据，仍可按 `verifiable_no_effect` 安全重试；反过来，即使 provider 支持幂等，无终局证据时也仍须 unknown。当前验收文字可能要求实现错误分类。
- **最小修复建议：**将验收拆成两个正交维度：是否有终局证据决定 known/unknown；known failure 是否满足完整 `retry_eligible` 决定是否重试。至少覆盖"幂等但未知""非幂等但证实未发生""非幂等且未知"三类。

## 七、所要求的闭合性与可追溯性复核

### Step 九状态与聚合目标（复核确认，不重复报告已修复项）

| 检查项 | 复核结果 |
|---|---|
| `planned` 的取消 | 已明确同事务 `planned -> cancel_requested -> cancelled`，不需要新增直接出边 |
| `ready` 的取消及 tools seal | 已明确取消两跳和 seal 到 `waiting_effect`；禁止 `ready -> succeeded` 有依据 |
| `waiting_effect` | 六条聚合规则所需的可达变更目标已列出 |
| `failed_retryable` | retry 回 `waiting_effect`，以及取消、失败关闭出口已列出 |
| `cancel_requested` | sticky pending 保持取消等待，unknown、取消完成及 WORKSPACE_LOST 出口已有定义 |
| `blocked_unknown_effect` | repair 后到 `ready`、`failed_retryable`、等待态和终态的必要出边已补齐 |
| 三个 terminal step 状态 | 不再推进；WORKSPACE_LOST 前已成功终态的 step 保留原终态已有例外说明 |
| 六条聚合规则的双层目标 | 每条均写有 step 与 session 目标；问题集中于 L4-08、09、13 的判定依据和集合语义，而非简单漏写目标 |

### §0、§5、§6 与交叉引用

- §0 的 grant、workspace fencing、唯一结果权威及停止语义，分别受到 L4-04、07、18、14 的实质影响。
- WORKSPACE_LOST 的"session 立即失败、step 按 unknown/pending 分支逐步 drain"在正文中已有明确覆盖，不应再误报为一律提前终态化 step。
- driver switch 的 begin-switch 四项 guard、quiescing 收束、terminal session 的既存 switch intent 例外均已有定义；其可执行性仍依赖 L4-14—17 的 recovery 修复。
- 数字章节引用本身基本可定位；主要交叉引用问题是 L4-17 的重复定义漂移、L4-19 的未展开"既有规则"和 L4-23—24 的验收口径不一致。
- 上述修复应落入 P0A 的冻结内容，并为对应 Conformance 增补子用例；能力不足的 compat 测试必须保持 blocked，不能以 Native 通过或 unknown 字节一致代替 portable 语义通过。

---

## 结论

**全文存在 P0 和 P1 缺陷，当前版本尚不具备协议冻结条件。**

（P0 ×5：L4-04、L4-07、L4-08、L4-14、L4-18；P1 ×19：L4-01~03、L4-05~06、L4-09~13、L4-15~17、L4-19~24）
