# V8-dev 全文 L4 独立审核 · 第二轮（2026-09-11 晚）

- **审核者**：Oracle（新聊天深审，声明"历史审核报告仅用于问题溯源，不把此前各轮 PASS 当作本轮已验证事实"）
- **对象**：`docs/designs/v8-dev.md` 612 行版本（Loop 2 T1~T6 全部修复后）
- **结论**：**1 P0 + 12 P1（V8-L4-25~37），尚不具备协议冻结条件**
- **重要**：审核的闭合性复核表确认此前修复（grant 三合取、workspace fenced publish、INFRA 同构 drain、seal 双路径、append 白名单、effect 级预算、compact 状态机、两维 capability 矩阵等）未被推翻；新发现全部是已修机制在更深组合路径上的剩余缺口。

## 发现清单（P0 优先）

### V8-L4-33 · P0 — recovery 在批次聚合判定前分配新 attempt，绕过 terminal sibling 的批次关闭
- 位置：§3.2.2 recovery 第 3(c)/4 步；§3.2.1 规则 2、4、5；Conformance 3/5
- 问题：执行许可 gate 只检查"批次已终态收束"，但 pending effect 存在时批次按规则 2 尚未终态。反例：A=dispatch_started（已知失败证据、retry_eligible 通过）、B=failed_terminal（budget_exhausted）——普通 completion 路径：A 分类 retryable → pending 消失 → 规则 4 关闭全批为 failed；recovery 路径：批次未终态 → gate 通过 → 立即给 A 分配新 attempt → 重新 pending → B 无法触发批次关闭。两入口产生额外外部执行与不同 code（FAILED_TERMINAL vs FAILED_RETRY_BUDGET_EXHAUSTED）。
- 最小修复：recovery 先对旧 attempt 已知结果执行共享失败分类并按全批状态计算关闭/等待/可重试决策；仅当批次满足普通 retry 资格（规则 5 批次条件）才同事务分配新 attempt；terminal/cancel sibling 存在时执行共享收束；unknown/pending sibling 存在时不得绕过批次限制。Conformance 补非 sticky 场景两入口三层一致性测试。

### V8-L4-34 · P1 — recovery 与普通 completion 对 known failure 的证据门槛不一致
- 位置：§3.2.2 recovery 3(a) vs complete_effect 失败分类
- 问题：recovery 写"provider 确定性失败**或**副作用未发生证据 → known_failure"；completion 写"确定性失败**且**副作用未发生"。provider 失败回执不必然证明副作用状态；provider_idempotent 只保证重试安全不证明结果已知。且 no-effect 证据须明确绑定当前 attempt（旧 attempt 证据不可复用）。
- 最小修复：抽出唯一证据分类函数（单一定义、completion/recovery/repair 三处引用）：失败回执+副作用未发生证明 → known_failure；失败回执但副作用不明 → unknown（幂等能力不改变）；成功/取消同理绑定 attempt。补两入口一致性用例。

### V8-L4-25 · P1 — turn reducer 未区分"终结候选"与"允许终结"
- 位置：§1.2 表 + reducer；§3.2.1 规则 2、6
- 问题：pending 时"不终结"与表行"对应 turn MUST 输出 turn/end"冲突。场景 1：A provider-cancelled + B 仍 dispatch_started（控制层等待，表行要求 end）。场景 2：带 tool calls 的 succeeded decision 缺 final（控制层须等 tools seal，missing_final 行却要求 end）。
- 最小修复：reducer 拆三段：unknown provisional 表示 → turn 终结资格 guard（无 pending、无待续行工作）→ 资格后按优先级选唯一 reason。表行改为产生"候选"，受 guard 约束；missing_final 仅修饰关闭 decision。补两负向用例。

### V8-L4-26 · P1 — 全部 pre-dispatch 取消时 sticky 分支仍要求 after-dispatch reason
- 位置：§1.2 reducer (2)；§3.3 request_cancel
- 问题：唯一 effect 在 dispatch 前被取消 + sticky latch → reducer 按 sticky 要求 cancelled_by_request_after_dispatch，与"pre-dispatch 不产出 after_dispatch reason"冲突。
- 最小修复：sticky 分支加 dispatch-phase guard；全未派发取消的唯一 canonical 输出冻结（新 reason `cancelled_by_request_before_dispatch` 或显式无 end 的关闭语义，需可被 fork guard 消费）。Conformance 15 断言具体输出。

### V8-L4-27 · P1 — provisional 替换键与只追加事件唯一键未分层
- 位置：§1.2 repair 取代；§3.1.2 UNIQUE(session_id,logical_event_key)
- 问题：closer 用同 key 会被"同 key 异内容拒绝"；用新 key 则无关联字段。未区分"原始追加身份"与"canonical 替换身份"。
- 最小修复：分三层冻结：原始事件不可变 `event_key`（幂等唯一约束）；canonical 槽位键（如 `turn_end_key`）；closer 的 `supersedes`/resolution binding。normalize 按槽位+supersedes 替换；原始约束只管追加幂等。补"unknown→部分 repair→全部 repair"只追加重算测试。

### V8-L4-28 · P1 — canonical profile 缺类型识别与 $int 接受域
- 位置：§1.3 (1)(3)(4) 步
- 问题：时间归一未限定 schema 类型化字段（形似 RFC 3339 的普通文本会被改写？）；`$int` 十进制词法（前导零/符号/-0/范围）未冻结；工具 JSON 中裸 `$int` 键与保留类型未区分。
- 最小修复：时间归一仅限 schema 显式时间字段；$int 词法冻结（无前导零、无 +、-0 拒绝、范围边界）、保留名转义规则；不符唯一表示 → schema 拒绝。golden vectors 补齐。

### V8-L4-29 · P1 — rejection fingerprint 的 header 剔除协议未定义
- 位置：§1.3 fingerprint (1)(2)；§3.1.2 envelope
- 问题："按字节区间定位剔除"依赖未定义的 envelope 字节格式、字段名、边界、重复/畸形处理——两端可能剔除不同区间。
- 最小修复：结构性分离方案（声明 hash 走 transport 元数据通道，fingerprint = SHA-256(payload 原始字节)，无需剔除）或冻结唯一 framing+定位算法。vectors 覆盖首尾/重复/边界。

### V8-L4-30 · P1 — receipt 第 (4) 步把"开始处理"等同 accepted
- 位置：§3.1.2 四步判定 (2)(4)
- 问题：hash 正确但 fence 过期/guard 失败的首次请求结局应为 rejected_stale/mismatch，(4) 却指定 accepted，与 first_outcome 记录实际结局矛盾。
- 最小修复：(4) 改为"进入完整 guard 判定，按实际 outcome 写 binding 与 receipt"（首占结局含全部四类）。补一致性断言。

### V8-L4-31 · P1 — 空 tools plan × decision_only=false 组合无聚合出口
- 位置：§3.1.2 结果校验；§3.2.1 规则 6
- 问题：单向蕴含允许 [] + false + false 的成功 completion——无 tool calls 不能等 seal、非 decision_only 不能关闭、单一活跃 step 阻止新建——规则 6 无目标。
- 最小修复：双向冻结（空 plan ⟺ decision_only=true；非空 ⟺ false+final_tools=true；其余 DECISION_PLAN_INVALID）；decision_only 分支 final_tools 固定值。补四组合负向测试。

### V8-L4-32 · P1 — 无非终态 active step 时 request_cancel 无 session 收束
- 位置：§3.1 单一活跃 step；§3.1.1 request_cancel
- 问题：空 session ready / waiting_event / sleeping / 关闭 step 成功但未 finish 的窗口——设置 latch 但无 step 可终态化，session 无终态路径（claim 又被 latch 禁止）。
- 最小修复：request_cancel 增加无活跃 step 分支：无未决 effect 时直接原子派生 session cancelled（保留既有 terminal step 不变）、处理 lease/fence 与 canonical 关闭表示；与 finish_session 竞争按提交序。覆盖三窗口测试。

### V8-L4-35 · P1 — implementation 唯一键与 generation 成员关系未闭合
- 位置：§4 plugin_implementations/generation 流程
- 问题：行含 generation_id 但唯一键不含——G2 复用 G1 未变实现时无法插入（冲突）或改归属（破坏旧代）。
- 最小修复：二选一：全局不可变实体 + 新增 generation_members(generation_id, implementation_id)；或 generation 内实例 + 调整唯一键 + 定义跨代逻辑身份。补"单插件变更，同版本实现被新旧代引用"测试。

### V8-L4-36 · P1 — active→failed 强制下线未绑定调度与既存工作处置
- 位置：§4 generation；§3.2.2 dispatch gate
- 问题：active 指针指向 failed generation 时新 assemble 行为、已绑定未派发 step/job 能否 claim/dispatch、in-flight 如何收束、ready 的 handler 是否被拦——均未定义。
- 最小修复：冻结 failed generation 不可调度规则、active 指针处置（回退或空）、未派发/in-flight drain 政策与稳定 code；与 retired（既存工作继续）明确区分。Conformance 8 补用例。

### V8-L4-37 · P1 — capability 矩阵未区分数据库协议测试与真实 compat I/O 门控测试
- 位置：§5.2 矩阵；Conformance 14/16；P0C
- 问题：dispatch_interception 降级时 Conformance 14 被要求照常执行——但"撤销后 dispatch 被拒"的数据库测试通过≠"外部 I/O 不先于授权发生"的真实 loop 测试（after-I/O adapter 可能已发出外部动作）。
- 最小修复：fixture/subcase 层标测试边界：数据库命令/存储/合成事件测试无依赖照常；经真实 compat loop 验证授权先于外部 I/O 的子用例依赖 sync_before_io，降级即 blocked；数据库测试不得替代。同步 Conformance 14/16、P0C 报告分类。

## 闭合性复核（审核确认，不再报告）
grant 三合取/线性化、workspace 迁移表/fenced publish/failure-drain、driver_mode/begin_switch 四 guard/terminal finish_switch 例外、INFRA 同构、seal 双路径/create_effect_in_seal、append 白名单/compat-unmapped 路径、单一活跃 step、computed hash 首占、effect 级预算/规则 4-5、recovery 单事务、compact 状态机、fork 稳定切点、插件绑定键/排序、building→failed、两维 capability 矩阵——九状态出边复核全部覆盖，无回退。

## 下轮分组（控制器）
- T7=H3：V8-33（P0）+ V8-34
- T8=H1：V8-25/26/27/28/29
- T9=H2：V8-30/31/32
- T10=H4：V8-35/36/37
