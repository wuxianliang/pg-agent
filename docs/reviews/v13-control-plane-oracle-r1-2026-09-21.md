# v13 控制面九题 Oracle 裁决记录 R1(2026-09-21)

> 输入:完备性复核(`v13-control-plane-completeness-review-2026-09-21.md`)九题
> (缺口 1–5 + 缝 A/B/C + 任务分级 triage + 整体修改)。
> 通道:ask_oracle plan 模式,Oracle 组双模型(gpt-5.6-sol@xhigh + grok-4.6@xhigh)并行,
> 上下文=8 文件 selection(调查报告/复核/设计文档/ch05·08·12·13·14)。
> 状态:**R1 完成,共识 14 条,分歧 3 处待拍板**(见 §0)。拍板后按 A15–A21 修订编号并入计划。

## 0. 共识与分歧(主会话合并摘要)

### 0.1 双模型一致(可直接采纳)

1. **零新表零新列**:信封族全住 `artifacts.kind` + pg_jsonschema + `tools.input_schema`;
   worktree/handoff/triage 均不 ALTER sessions。
2. **续跑=新 effect_id + 新冻结 request**:禁止同 effect_id 换 request 再 attempt
   (attempt 只服务同一 request_hash 的运输重试;审批答案改变 request 内容)。
   逻辑关联字段(`logical_turn_id`/`continuation_index` 或 `resume_from{effect_id,artifact_hash}`)
   住在 request artifact 内,不加 effect 列。
3. **审批两段接线**:harness effect 以 succeeded + 需审批信号终态化(单活跃释放)
   → human effect → 续跑 effect(mode=resume)。禁止 needs_approval 作为 effect status。
4. **handoff 信封**:artifacts 载荷 + 稳定 delivery_id 幂等,不采 XML;
   transcript 存 manifest/hash 引用不复制正文。
5. **v_goal_tree**:参数化递归 CTE 函数,纯查询不建投影表;预算递归聚合
   (subtree spent/reserved 计入 root);attention 固定优先级排序;
   物化进 YAGNI(触发:看板 p95 超标)。**投影永不做授权来源**。
6. **closeout 事件族**:session/completed|failed|cancelled 三终结事件,
   载荷=对账收据(spent/produced hashes/children 汇总/unconsumed 清点/state_hash),
   与 session 终态、预算终态**同事务**;前置条件 fail-closed
   (active=0、unknown=0、pending human=0、子树终态或显式 superseded);
   closeout 不再扣预算只对账。
7. **子终态唤醒父**:子 closeout **不得**在持子 FOR UPDATE 的事务里写父事件
   (锁序对撞,ch02 两级锁序红线);唤醒=调用者 parse+advance 或扫地僧
   `v13_recover_idle` 扩谓词(「非终态+无活跃 effect+子齐父未验收」);
   子终态行是真相,通知只是唤醒提示。
8. **worktree 零列方案**:binding=latch(`name='worktree'`,value=worktree_id 非路径)
   + `worktree_binding` artifact + prepare/merge/release 走 FS effect;
   路径是 host-local 投影不是真相;子会话**不继承**父 worktree(共享可变 FS
   打破父子并行);mutating harness 无 active binding → fail-closed 拒 claim;
   worktree latch 默认不参与 prefix_identity。
9. **steer**:G-ctx1 扩断言(4 条);claimed 期间的 steer 不缝进已冻结 request,
   settle 后下一格消费;旧 request_hash 不得用于新水位。
10. **cancel 传导**:handler 合同三步+一务(控制订阅义务);目录声明
    interruptible(required/best_effort/unsupported 或 bool+metadata);核心不杀进程;
    mutating 中断后副作用不明 → **unknown**(cancelled 不得掩埋,继承 ch12);
    partial artifact 只作审计不过 completion gate;与 ch11 的区分:
    kill-at-every-boundary=崩溃语义杀 worker,本缝=控制语义 handler 杀子进程。
    父 cancel 子树=同事务对子孙扇出 cancel/requested 事件。
11. **spawn=tools 目录行,不扩 v_routes**:与 v13_fork 同 primitive(两列+forked 事件
    + validate-spawn + 预算准入);预算只做 **reserved 准入**(subtree_reserved+
    requested ≤ 剩余),不预扣 turn_no(spent 只在各会话 advance/closeout 递增——
    双计数红线);服务端派生字段(parent/cutoff/fence/prefix identity/quota)模型不可提供。
12. **triage=decisions 一题 + thresholds 带宽 + SQL 短路 + Jev 中间带 + fail-closed 不拆**:
    不建 task 表/coordinator/固定 decompose pipeline;分解方案=LLM 产 plan artifact
    + spawn 工具调用(RP-CE「LLM 即编排器」);深度靠每次 spawn 前再准入+quota 自然界定
    + max_spawn_depth 策略(非代码常量);子会话默认 direct(再拆需 override 或高置信);
    根上长度/字数不是硬分界(「做完这个产品」很短且复杂)。
13. **验收链**:父完成条件=plan 内每个 required task 有唯一有效 child 且全 completed
    + artifacts 可消费 + 无未处理 failed/unknown + integration gates + 父最终 synthesis;
    SQL 全成功可自动 finish(首版),failed/取消走 human 或 reject 策略带;
    不要求「全子完成必须 human」;无 barrier 表。
14. **最小落地集三件(原子)**:①信封族+续跑+审批两段;②spawn+goal_tree+closeout
    +recover_idle 子树谓词(一件产品切片);③G-ctx1-steer+interruptible 第四务。
    worktree 随后、任何 mutating 外部 harness 启用前必须完成。

### 0.2 分歧 3 处(待用户拍板,主会话倾向已注)

| # | 议题 | gpt-5.6-sol | grok-4.6 | 主会话倾向 |
|---|---|---|---|---|
| D1 | harness result 分类 | LoopX 六分类进 accepted 事件(VALIDATED_PROGRESS/COMPLETION/REPAIR/REPLAN/USER_ACTION/WAIT),harness 原始输出叫 candidate_kind | **v13 四值(progress/finish/wait/reject)为路由权威**;REPAIR/REPLAN 降为事件信号(repair/required、replan/required);六值只作 delivery_kind 对照注释 | **倾向 grok**:v_routes 动作空间闭集,六值焊进路由=第三套动词(复核 §0 尺子);REPAIR/REPLAN 是 fold 信号不是路由动作;gpt 的「父控制器需区分修环境 vs 重计划」用事件信号即可满足 |
| D2 | spawn 的 kind | 不能 kind=sql(ch05「纯只读函数」),做成 ledgered effect tool(handler='pg-control',走 claim/complete) | kind=sql + **修正教条为写允许名单**(sql 快路=变更相、零外部 IO、零队列;允许名单内函数可写 sessions/events/latches/artifacts 指针) | **倾向 grok**:ch06 §6.7 原文「sql 档的全部效果就是数据库自身状态」本就支持库内写;ch05「纯只读」与 ch06 有措辞张力,统一为「sql=库内零 IO+写允许名单」;spawn 走队列多一跳且是假重工具;v12 inline/queue 双模是先例。**代价**:必须同步修 ch05/ch06 措辞(部署 gate 同发) |
| D3 | triage 信号集首版范围 | 丰富 rubric(work_unit_band/coupling/risk_band/candidate module 数等 10 项) | 最小集(content_hash/depth/children/quota/user_intent_override/mutating_hint),模块数不进首版(防解析相新 IO);candidate-module 信号待 T0 recall 落地后加 | **合并采纳**:首版=grok 最小集+fail-closed;candidate-module 数依赖 candidate_set_hash(已在水位内,非新 IO),随 §11 步骤 3 recall 落地后按 gpt 版加入;gpt 的 explore_then_retry(中间带派单个只读 explore 子会话再 triage)作为第四路由结果并入,映射到既有 llm 动作 |

### 0.3 随裁决发现的文档 bug(两模型之一指出,均须修)

- **G-ctx6 矛盾**(gpt 发现):设计 §5.4 裁「tier 只升不降仅单次 Plan 内」,
  §10 G-ctx6 仍写「跨 turn 成立」→ gate 文字改为「单 Plan 内单调,跨 turn hysteresis」。
- **ch05 vs ch06 措辞张力**(grok 发现):「纯只读函数」vs「sql 档=数据库自身状态」
  → 统一为「sql=库内零外部 IO;默认只读;写允许名单」(随 D2 拍板)。

### 0.4 修订编号建议(grok 提出,两轮兼容)

A15 信封族 / A16 closeout / A17 spawn+sql 写允许名单 / A18 interruptible 第四务 /
A19 worktree-as-latch / A20 triage 证据动作分离 / A21 recover_idle 子树谓词。
与 I-file-1…7 正交。

---



---

# 附录:Oracle 轮 1 原文(gpt-5.6-sol@xhigh)

# 1. Summary

应采用**定向补齐合同与信封**，不做核心重构：保留现有 9 表、`parse → advance → effect → settle` 唯一推进链，只新增版本化 artifact 形状、开放事件类型、目录行、策略行、递归视图和 worker 合同。关键裁决是：harness 暂停后续跑必须创建**新 effect、共享同一 logical turn**；结果采用 LoopX 六分类；spawn 走目录化 ledgered tool 而非扩展 `v_routes`；triage 是 decisions + thresholds 上的确定性路由，LLM 只负责生成分解方案；worktree、interrupt、handoff 都继续服从 effect/fence/unknown，不引入第二个状态机或真相源。

# 2. Current-state analysis

## 2.1 当前责任与数据流

现有权威链路是：

1. `sessions` 拥有会话/goal 控制状态；`parent_session_id + parent_cutoff_seq` 表达 O(1) fork。
2. `events` 是 append-only 干预与事实日志。
3. `v13_parse` 在无会话行锁的解析事务中补齐 `decisions`，记录事件水位、`goal_hash`、`candidate_set_hash`。
4. `v13_advance` 锁定 session，复核水位，读取 `v_routes`，创建 effect、检查预算或终结 session。
5. worker 通过 `claim → 外部 IO → complete` 执行 effect；稳定 ID、attempt、fence、lease、unknown 处理并发与崩溃。
6. settle 同事务写结果/artifact/event、更新预算并再次推进。
7. human、cancel、steer 都只能进入 events/effects 平面。

这与第 5 章的核心裁决一致：

> “循环本身住在调用者手里，状态机住在数据库里。”  
> — `docs/tutorials/v13/chapters/05-turn-and-advance.md` §5.1

外部 harness 已被定位为普通 handler：

> “`handler='claude-code'` 的 worker 跑 `claude -p`……长时运行外部 agent 运行时只是又一个 handler。”  
> — `docs/tutorials/v13/chapters/13-long-running-goals.md` §13.4

跨语言边界也已冻结：

> “任何语言之间永不直接通信，只通过行交换。”  
> — `docs/tutorials/v13/chapters/08-multi-language-harness.md` §8.1

## 2.2 当前可复用的扩展点

| 需求 | 应复用的现有扩展点 |
|---|---|
| handoff、request、result | `artifacts` JSON 载荷 + pg_jsonschema |
| steer、cancel、child closed | 开放事件类型 |
| provider/harness | `tools.handler` + 单 effect 队列 |
| approval | human effect |
| continuation | 新 effect + 冻结 request |
| spawn | tools 目录 + ledgered tool effect |
| quota、triage | `decisions` + `thresholds` |
| goal dashboard | 递归 CTE |
| worktree | tool effects + artifacts + mutation_scope |
| closeout | session 终态 + exactly-once 终结事件 |

完备性复核已经正确限定了改动范围：

> “三条缝都是信封与合同形状……无需改核心 schema。”  
> — `docs/reviews/v13-control-plane-completeness-review-2026-09-21.md` §3

## 2.3 当前阻塞点与两处真实矛盾

1. harness effect 没有冻结的 request/result/interaction 协议，无法安全续跑。
2. sticky cancel 没有主动传到长跑子进程。
3. parent/child 只有身份关系，没有正常编排入口和验收闭环。
4. goal tree、closeout、worktree binding 仍只有概念，没有合同形状。
5. triage 没有第一跳政策。

另有两处文档矛盾必须随本轮修正：

- 完备性复核建议 `spawn_subsession(kind=sql)`，但第 5 章明确规定 SQL 快路只执行**纯只读函数**。spawn 会写 sessions/events，不能标成 SQL 快路。
- `v13-context-on-pg.md` §5.4 已裁“只升不降仅在单次 Plan 内”，但 §10 G-ctx6 仍写“跨 turn 成立”。Gate 应改为“单 Plan 内单调，跨 turn 走 hysteresis”。

# 3. Design

## 3.1 控制面信封族

### 裁决

全部使用版本化 artifact 形状和 `tools.input_schema`，不建表。冻结五种类型：

1. `control.handoff.v1`
2. `harness.request.v1`
3. `harness.result.v1`
4. `harness.interaction.v1`
5. `harness.interaction_response.v1`

所有引用均使用 artifact hash；凭据永不进入载荷，由 worker 进程注入。

### continuation 与 effect 身份

**续跑必须创建新 effect，不得复用旧 effect 的新 attempt。**

理由：

- attempt 只表示“同一冻结 request 的运输重试”。
- 审批答案、resume token、continuation index 会改变 request 内容。
- 将变化后的 request 放进同一 effect ID 会破坏 request freeze、幂等身份和 unknown 对账。

引入仅存在于 request artifact 中的两个逻辑字段，不加 effect 列：

- `logical_turn_id`：整个外部 turn 的稳定身份。
- `continuation_index`：从 0 单调递增。

关系如下：

```text
harness effect E0
  └─ result USER_ACTION_REQUIRED
      └─ human effect H0
          └─ response artifact
              └─ harness effect E1
                   logical_turn_id = E0.logical_turn_id
                   continuation_index = 1
                   predecessor_effect_id = E0
```

预算按 `logical_turn_id` exactly-once 结算，而不是按 continuation effect 数量结算。E0、H0、E1 严格串行，因此不破坏单活跃索引。

### request 信封字段

至少包含：

- `schema_version`
- `logical_turn_id`
- `continuation_index`
- `mode ∈ {start,resume,respond_to_interaction}`
- `prompt_artifact_ref`
- `external_thread_id`、可选 opaque resume locator
- `predecessor_effect_id`
- `interaction_response_ref`
- `session_id`
- `event_cutoff_seq`
- `goal_hash`
- `prefix_identity`
- handler/provider/model/profile 版本
- sandbox、approval、timeout、harness 内部 max-turns 策略
- request hash

外部 thread ID 是投影定位符，不是权威状态。无法恢复时必须返回 `REPAIR_REQUIRED`，不能自行创建“看起来相同”的新线程。

### result 分类

采用 LoopX 六分类，不采用 `progress/finish/wait/reject` 四分类：

- `VALIDATED_PROGRESS`
- `VALIDATED_COMPLETION`
- `REPAIR_REQUIRED`
- `REPLAN_REQUIRED`
- `USER_ACTION_REQUIRED`
- `WAIT`

理由：`USER_ACTION_REQUIRED` 是审批两段接线所必需，`REPAIR_REQUIRED` 与 `REPLAN_REQUIRED` 也不能压成同一个 reject，否则父控制器无法区分“修执行环境”和“重做计划”。

harness 原始输出只能叫 `candidate_kind`；SQL/handler 合同验证通过后，事件中才记录 accepted 六分类。`VALIDATED_COMPLETION` 仍需通过 session acceptance gates，不能由外部 harness 单方面宣布。

| accepted kind | 后续行为 | goal quota spend |
|---|---|---|
| VALIDATED_PROGRESS | 写 durable progress，继续 advance | 是，同 logical turn 一次 |
| VALIDATED_COMPLETION | 进入本地验收，合格后 closeout | 是，同 logical turn 一次 |
| REPAIR_REQUIRED | 路由 repair；累计修复次数 | 否 |
| REPLAN_REQUIRED | 重新 triage/orchestrate | 否 |
| USER_ACTION_REQUIRED | 建 human effect | 否 |
| WAIT | 等待明确 wake condition | 否 |

provider usage 始终记录；“不扣 goal slot”不等于调用免费。repair/replan 必须有策略上限，超过后转 human/failed。

`WAIT` 必须携带机器可判定的唤醒条件，例如事件类型、`not_before`、child terminal 或 artifact 到达；缺失条件则信封非法，防止不可恢复的永久 waiting。

### 审批两段接线

第一段 harness effect 以 effect 状态 `succeeded` 终态化，结果分类为 `USER_ACTION_REQUIRED`。它表示“本控制段成功产出审批请求”，不是原业务已完成。

随后：

1. 写 interaction artifact。
2. advance 创建 human effect。
3. human settle 写 response artifact。
4. advance 创建 continuation harness effect。
5. continuation 使用新 effect ID、同 logical turn ID。

若 provider 的 pending request 无法跨进程恢复，adapter 不得声明 resumable；恢复失败返回 `REPAIR_REQUIRED`。

### handoff 信封

必须包含：

- 稳定 `delivery_id`
- source session、source cutoff seq
- target session 或 target task key
- objective artifact
- transcript manifest/ref，而非复制可变聊天文本
- file/evidence artifact refs
- acceptance contract ref
- policy/profile versions
- supersedes/retry 关系

目标 session 追加 `handoff/accepted` 后才可消费；相同 `delivery_id` 重复投递不得二次注入 prompt。

### 反例

- 把 continuation 当 attempt：审批答案改变 request，但 effect ID 不变，重试时无法知道应重发旧请求还是新答案。
- 使用四分类：审批、环境修复和重新规划都退化成 reject，控制器只能靠字符串猜测。
- 在第一 effect 未终态时创建 human effect：直接违反单 session 单活跃 effect。

### Gate

- 同一 interaction 重复回答只创建一个 continuation effect。
- continuation request 改一字节必须得到新 effect ID；相同冻结 request 重试保持原 effect ID。
- 同 logical turn 的多个 continuation 最多扣一次 quota。
- `USER_ACTION_REQUIRED` 缺 interaction artifact 时 complete 被拒。
- `WAIT` 缺 wake condition 时 complete 被拒。
- handoff 缺任一 artifact、cutoff 不匹配或 delivery 重复时 fail-closed。

---

## 3.2 `v_goal_tree` 递归视图

### 裁决

实现为参数化、`STABLE` 的关系函数 `v_goal_tree(root_session_id)`；语义上是视图，不建投影表。普通无参数视图会先展开所有 root，无法可靠限制递归工作量。

返回一行一个 session，字段固定为：

### 身份字段

- `root_session_id`
- `session_id`
- `parent_session_id`
- `parent_cutoff_seq`
- `depth`
- `path`
- `cycle_detected`

发现环时整棵查询报错，不返回部分树。

### 生命周期字段

- session status、terminal kind
- active effect ID/kind/status/handler
- current turn number
- `last_real_progress_at`：只看 material result，不把 lease heartbeat 当进展
- waiting reason

### 子树汇总

- direct/total child count
- active/completed/failed/cancelled child count
- unresolved unknown effect count
- `all_required_children_completed`
- `any_descendant_failed`
- `any_descendant_unknown`

### 预算字段

- budget policy/version
- local limit、spent、reserved、remaining
- subtree spent、reserved
- root limit、remaining
- quota eligibility

子 session 的消耗和活动 reservation 必须计入 root；不能在每层重新获得一份完整余额。

### attention 字段

固定优先级：

1. unresolved unknown
2. pending human/operator gate
3. failed child、repair/replan required
4. runnable idle
5. stale lease/recovery needed
6. waiting external condition
7. running
8. terminal/no attention

排序键固定为：

```text
(attention_rank, attention_since, depth, session_id)
```

### 刷新策略

首版只用纯查询。只有在真实目标树规模下该查询 p95 超过既定 dashboard SLO，才允许增加**可重建投影**；投影永远不能成为 closeout、quota 或 spawn 的授权来源。

这延续了第 13 章的裁决：

> “dashboard（投影）→ 视图。”  
> — `docs/tutorials/v13/chapters/13-long-running-goals.md` §13.1

### 反例

以投影表授权 closeout 会产生刷新窗口：child 已失败而旧投影仍显示 completed，父 goal 被错误终结。

### Gate

- 环检测 fail-closed。
- 同一快照内 root remaining 等于 root limit 减所有后代 spent/reserved。
- heartbeat 不改变 `last_real_progress_at`。
- child 从 running 变 completed 后，同事务后查询立即可见，不等待 refresh job。
- 1、2、4 层树的预算聚合结果一致。

---

## 3.3 closeout 事件族

### 裁决

定义三个 exactly-once 事件：

- `session/completed.v1`
- `session/failed.v1`
- `session/cancelled.v1`

终结事件与 session 终态、最终预算对账必须在同一事务完成。closeout 不再扣一次预算，只核对 settle 已完成的扣减。

### 公共载荷

- `schema_version`
- terminal status 与 reason code
- trigger effect/event
- `input_cutoff_seq`
- final turn number
- route/budget/context policy versions
- accounting：
  - admitted/reserved units
  - distinct spent logical turns
  - usage totals
  - local/subtree spent
  - root remaining
- outputs：
  - primary artifact refs
  - artifact count by kind
  - 排序后的 artifact hash 集合摘要
- children：
  - required/completed/failed/cancelled/active counts
- unresolved snapshot：
  - active effects
  - unknown effects
  - pending human
  - actionable unconsumed events
- canonical `state_hash`

事件行本身已有时间和 seq，不在 payload 重复写可伪造的时间戳。

### variant 字段

- completed：acceptance decision IDs、passed gate refs。
- failed：统一 `{Type, Problem, Solution}`、failed effect、retry exhaustion。
- cancelled：cancel event seq、interrupt receipt refs、partial artifact refs、请求者。

### 终结前置条件

所有终态共同要求：

- active effect = 0
- unknown effect = 0
- pending human = 0
- child 要么终态，要么被显式 detached/superseded
- quota 对账相等

completed 额外要求：

- 所有 required child completed
- required artifact 可消费
- acceptance gates 全部通过
- actionable unconsumed events = 0

cancelled/failed 可以忽略输入，但必须在 closeout 中记录 `input_cutoff_seq` 和被放弃输入的计数；终态后普通 user message 应被拒，开放的 reward/audit 事件仍可追加。

预算断言以 `logical_turn_id` 去重。approval continuation 不得多扣；WAIT、repair、replan、human 不得伪装成 material spend。

### 反例

- 用 artifact 数组完整复制所有产物会让终结事件无限膨胀；应只存 primary refs、计数和集合 hash。
- cancel 覆盖 unknown 会把“不知道外部副作用是否发生”伪装成“已取消”。

### Gate

- 重复 closeout 不产生第二个终结事件或第二次预算变动。
- distinct material logical turns 数量与 spent ledger 一致。
- 有 unknown 时三种 closeout 全部拒绝。
- completed 且 required child failed 时拒绝。
- continuation 链只有一次 spend。

---

## 3.4 worktree 隔离

### 裁决

可以零核心 schema 改动。worktree 由 tool effect 创建和回收；权威绑定由 immutable artifact + typed events 表达，sessions 不加路径列。

目录增加 ledgered tools：

- `prepare_worktree`
- `merge_worktree`
- `release_worktree`

生命周期：

```text
prepare effect
→ worktree.binding artifact
→ workspace/bound event
→ harness effects
→ merge/retain/release decision
→ release effect
→ workspace/released 或 cleanup_failed event
```

### binding artifact

至少包含：

- binding ID
- owner session ID
- repository identity
- base revision
- unique branch/ref
- opaque host-local workspace locator
- host ID
- cleanup policy
- generation
- mutation scope
- creation effect ID

路径是外部 projection；PG 不把“该目录目前存在”当真相。

### 创建与回收责任

- advance 发现 mutating harness 尚无有效 binding 时，先创建 prepare effect。
- worktree handler 执行所有 Git/FS IO。
- parent/orchestrator 在 merge、handoff 或 closeout 前选择 release/retain。
- closeout 前必须完成 disposition；保留给 handoff 是合法终态，但必须有显式 retention artifact，不得靠目录碰巧还在。

### mutation scope

使用三个不同作用域：

- worktree add/remove：repository administration scope
- worktree 内编辑：`worktree:<binding_id>`
- merge/apply 到目标分支：destination branch scope

不同 worktree 可并行；对同一目标分支的 merge 必须串行。

创建和清理都是外部 mutating effect。崩溃后无法确认是否已创建/删除时进入 unknown；重试使用由 session/repo/base 派生的确定性 binding ID 和路径，先 reconcile 后继续。

### 反例

将绝对路径写进 sessions 列会把 host-local projection 升格为 durable truth；迁移 worker 或清理目录后 session 行仍声称 workspace 存在。

### Gate

- mutating harness 无 active binding 时不能 claim。
- 两个 child session 得到不同 binding 和 branch。
- 同一 binding 的 edit effect 按 op_seq 串行。
- merge 使用目标分支 mutation scope。
- prepare/release 崩溃窗口进入 reconcile/unknown，不得盲重放。

---

## 3.5 steer 消费时机

### 裁决

定义 `control/steer.v1` 事件，至少带：

- stable steer ID
- instruction artifact
- `expected_effect_id`
- `expected_request_hash`
- delivery mode：`current_only | current_or_next | next`
- source principal

消费分两条路径：

1. **effect 创建前到达**：事件 seq 改变水位，旧 parse snapshot 必须作废；重解析后的 request 包含 steer。
2. **effect 已 claimed 后到达**：
   - 声明 live-steer 能力的 handler 按事件 seq 转发，并记录 provider receipt。
   - 不具备可靠幂等 receipt 的 handler 不得声明 live-steer；事件留到下一 effect。

request/result 必须记录：

- `consumed_through_seq`
- `observed_through_seq`
- delivered steer IDs

旧 `expected_effect_id` 的 steer 不能滑入新 turn。`current_or_next` 才可自动降级为下一 turn；`current_only` 目标已结束时写 undeliverable 事件并等待调用者处理。

### G-ctx1 增补

- parse 暂停时插入 steer 不被阻塞。
- parse 返回后、advance 前插入 steer：advance 返回 stale/reparse，零新 effect、零预算扣减。
- 重解析后的 request hash 必须包含该 steer。
- live steer 以事件 seq 顺序投递。
- worker takeover 不得重复投递；provider 不支持 steer idempotency 时自动禁用 live 模式。
- cancel 已出现时，不再向当前 effect 投递后续 steer。

---

## 3.6 cancel 主动传导

### 裁决

不增加 `interruptible bool` 列。布尔值无法表达强制程度、截止时间和 receipt。采用：

1. worker 合同新增“控制订阅义务”；
2. `tools.input_schema` 顶层 annotation 声明版本化 interrupt policy：

- `required`
- `best_effort`
- `unsupported`

并携带 deadline、receipt schema 版本。

`claude-code` 等长跑 handler 必须声明 `required`。实现时需验证 pg_jsonschema 是否允许 `x-v13-*` annotation；若当前 validator 禁止未知 keyword，则放入现有目录 metadata JSON，不新增列。

### 执行模型

- 控制 watcher 与当前 claim attempt 同生命周期。
- watcher 不持数据库事务，使用 LISTEN 或短轮询读取事件。
- 丢失 lease/fence 后立即停止发信号。
- cancel 到达后调用 provider interrupt/API/进程信号，记录 receipt，然后结算。

### 结算形状

- 已确认外部 turn 停止且无副作用歧义：effect `cancelled`，可附 partial artifacts。
- partial artifact 必须标为 partial，不能满足 completion gate。
- mutating effect 中断后副作用状态不明：effect `unknown`，不能标 cancelled。
- 不支持主动中断的 handler 退回 sticky cancel，但目录若声明 `required` 则该 worker 不得 claim。

这扩展但不推翻第 12 章：

> “不强制杀正在跑的 effect——cancel 是个事实。”  
> — `docs/tutorials/v13/chapters/12-intervention.md` §12.3

新的精确含义是：核心仍不直接改写 claimed effect；**拥有 claim 的 handler 有合同义务主动中断**。

### 与 ch11 kill 边界的关系

- cooperative interrupt 是控制语义，有 provider receipt。
- kill-at-every-boundary 是崩溃/恢复测试，没有成功中断的证明。
- 强杀只能作为 deadline 后的监督动作；进程死亡不等于调用未发生。
- 强杀后的 mutating effect 默认 unknown；read-only/idempotent effect 才能按原恢复规则重领。

### Gate

- required handler 在 cancel deadline 内发出 interrupt。
- receipt 与 cancel seq、effect ID、attempt/fence 对应。
- stale worker 的 cancelled settle 被 fence 拒绝。
- mutating interruption无证明时只能进入 unknown。
- partial output 不通过 completion gate。
- cancel 后不创建新工作。

---

## 3.7 spawn 子会话

### 裁决

选择 tools 目录入口，不扩展 `v_routes` 动作空间；但**不能使用 `kind=sql`**。

第 5 章规定：

> “纯只读函数（`tools.kind='sql'`）在变更相同一事务内直接执行。”  
> — `docs/tutorials/v13/chapters/05-turn-and-advance.md` §5.4

因此 `spawn_subsession` 应是普通 ledgered tool：

- kind：现有 effect-backed tool 类
- handler：`pg-control`
- mutating：true
- 实际执行：调用受限的数据库控制函数
- 幂等键：source effect + model tool-call ID/task key

它仍使用现有 claim/fence/complete，不是新机制。

### 模型可提交的参数

- `task_key`
- objective artifact ref
- handoff artifact ref
- task class
- role/profile hint
- requested budget cap
- replay kind：`exact_replay | recompute | fresh_fork`
- workspace policy
- acceptance contract ref
- dependency task keys

以下字段由服务端从 source effect 派生，模型不能提供：

- parent/root session ID
- cutoff seq
- source effect/fence
- current prefix identity
- remaining root quota
- policy versions

### spawn 事务

按 root → parent 的固定锁顺序：

1. 校验 source effect/fence、parent 非终态且未 cancel。
2. 校验 task key 幂等。
3. 校验预算 reservation 和 parent closeout reserve。
4. 调用 ch14 validate-spawn。
5. 校验 replay kind/prefix identity/worktree policy。
6. 插入 child session。
7. 写 child `forked`/handoff event 和 parent child-created event。
8. 返回稳定 child session ID。

全部原子提交。调用在 child 已插入后崩溃时，重试根据幂等键返回同一 child。

### 调用权限

不是“仅 LLM 可调”：

- LLM：经工具面调用。
- 人工/operator：可经同一受限函数调用。
- dream/repair worker：持合法 source effect/fence 时可调。
- 任意 worker 不得直接 INSERT sessions。

工具可见性由 role/profile 和 allowlist 控制。

### Gate

- 重复 tool call 只得到一个 child。
- 同幂等键、不同参数 fail-closed。
- validate-spawn 失败时零 child 行。
- child row、forked event、handoff、预算 reservation 原子出现。
- 普通 direct role 看不到 spawn tool。
- `v_routes` 枚举保持不变。

---

## 3.8 任务分级路由 triage

### 裁决

triage 是 `decisions + thresholds + v_routes` 上的一组信号，不建 todo 表、调度器或 decomposition runtime。

第一跳：

```text
root user event
→ parse：确定性事实 + triage decision
→ advance：
   direct             → 普通 llm/harness effect
   orchestrate        → orchestrator prompt 的 llm effect
   explore_then_retry → orchestrator 只派一个 explore child
   human_gate         → human effect
```

四种结果仍映射到现有 `llm/human` 动作；不新增 route action。分解方案由 LLM 产 artifact，并通过 `spawn_subsession` 创建 child，符合 RP-CE“LLM 即编排器”。

### triage 信号集

#### 确定性事实

- objective hash、goal hash、repo revision
- 用户是否显式要求 direct/parallel/delegate
- 显式 deliverable 数量
- 显式 path root/repository 数量
- recall candidate 的 module 数量及 candidate-set hash
- 当前 tree depth、active children
- root quota 的 remaining/reserved
- capability 缺口
- 硬风险标记：schema migration、生产写入、凭据、不可逆操作、外部副作用
- 当前 task class：
  - `advancement_task`
  - `continuous_monitor`
  - `user_gate`
  - `user_action`

#### 判断证据

使用版本化 rubric，输出：

- `work_unit_band ∈ {atomic,few,many,unknown}`
- `independent_workstreams`
- `coupling ∈ {low,medium,high}`
- `mutation_scope_band`
- `acceptance_complexity`
- `needs_exploration`
- `estimated_segment_band`
- `risk_band`
- confidence/accept/review

不使用 LOC、工时或自然语言 token 数作为硬路由依据；这些预测不稳定，只能作为 shadow telemetry。

triage 判断复用现有 judgment resolver，不新增事务内 IO 通道；生成分解方案的 LLM 必须走 effect。

### direct 与复杂任务边界

初始 threshold seed：

- candidate modules `≤1` 为 low，`2` 为 middle，`≥3` 为 high。
- module count 单独不能强制分解；跨文件机械修改可能仍是 atomic。

**direct 必须同时满足：**

- 没有 unresolved hard risk/capability gate；
- deliverable ≤1；
- repo/mutation scope ≤1；
- work unit 为 atomic；
- independent workstreams ≤1；
- acceptance 为 simple；
- 预算可容纳 direct cap；
- 判断不在 review/unknown 带。

**orchestrate 任一条件即可触发：**

- 用户明确要求分解/并行；
- 至少两个独立可验收 deliverable；
- 至少两个 repository 或 mutation scope；
- work unit 为 many；
- direct 预算上限明显不足；
- 高 candidate-module 数同时伴随 multi-gate、探索需求或多工作流。

**middle band：**

- 两个 module；
- module 很多但高耦合；
- scope/风险判断置信度不足；
- 无法可靠预估独立工作流。

middle band 默认 `explore_then_retry`：只建一个 read-only explore child，取得 module/coupling/evidence 后重新 triage。风险不明、预算不足或 capability 缺失则转 human gate，不能冒险 direct。

### 深度与预算联动

不设置代码常量式最大深度；但每次 spawn 必须：

- reservation ≥ 1 个 material unit；
- 为 parent 保留至少 1 个 synthesis/closeout unit；
- 受 root 总 quota 和并发 child policy 限制。

因此树深被有限 quota 自然界定，不可能零成本无限递归。策略行可额外设置 `max_active_children`，初始建议 4；这是并发保护，不是第二套层级调度。

task class 的初始 child cap：

- explore：1 个 material segment
- validation：1 个
- advancement：2 个
- continuous monitor：每次 wake 1 个

需要扩容时追加 budget-request 事件，由 parent/human gate 处理；child 不能自行扩大。

### 分解与验收链

orchestrator 首先产 `decomposition_plan` artifact，每个 task 包含：

- stable task key
- objective/handoff
- dependencies
- role/profile
- budget request
- workspace policy
- required outputs
- acceptance gates

父 goal 的完成条件不是“所有 child 都 terminal”，而是：

1. plan 中每个 required task 有且仅有一个当前有效 child，或显式 superseded。
2. 所有 required child 为 completed。
3. required artifacts 可消费且通过 schema/lineage 检查。
4. 无 unknown、failed、cancelled child 未被处理。
5. integration/merge/validation gates 通过。
6. parent 完成最终 synthesis/validation effect。
7. 最后才允许 closeout。

child closeout 向 parent 追加幂等 `child/terminal` 事件，触发 parse；若该通知事务间隙丢失，扫地僧通过 goal-tree 查询恢复。它是唤醒提示，不是真相源。

高风险、merge conflict、验收 review band 才进入 human；普通全部通过不要求人工。

### 是否引入新机制

没有。数据落点为：

- triage：decisions
- 分界：thresholds
- 分解方案：artifact
- 执行：既有 llm/tool effects
- child：sessions
- 交接/验收：artifacts + events
- 聚合：`v_goal_tree`
- 推进：原 parse+advance

### Gate

- 同 objective/candidate/policy request hash 二次 triage 零外部调用。
- goal hash 或 candidate-set hash 改变后旧 triage 不可复用。
- simple fixture 不创建 child。
- complex fixture 必须先有 plan artifact，再 spawn。
- middle fixture最多先创建一个 explore child。
- child reservation 不足时零 session 行。
- 递归 spawn 无法突破 root quota。
- child 全 terminal 但有 failed/unknown 时 parent 不得 completed。
- threshold 版本重放得到确定性相同路由。
- 迟到 decision 不修改已冻结 manifest。

---

## 3.9 整体文档与教程修改

### `docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md`

保持为日期化调查快照，不回写裁决。可仅增加指向最终设计章节的后记；不能改写其证据等级。

### `docs/reviews/v13-control-plane-completeness-review-2026-09-21.md`

追加 A/B/C resolution 表：

- A：worker interrupt contract + unknown。
- B：五类控制信封、六分类、continuation effect。
- C：ledgered `spawn_subsession`。

同时更正 `kind=sql` 建议。

### `docs/designs/v13-context-on-pg.md`

追加“控制平面闭环”章节，纳入：

- 信封族和 logical-turn/continuation 身份。
- 六分类映射。
- closeout receipt。
- worker interrupt/steer 合同。
- worktree binding。
- spawn 与 triage。
- goal-tree 字段。
- 无新表/列的 schema 总结。
- 新 gate 和交付顺序。

修正 §10 G-ctx6 为“单 Plan 内单调；跨 turn hysteresis”。

### 已提供教程章节

- `05-turn-and-advance.md`
  - 增加 steer 水位 gate。
  - 增加 accepted result 六分类映射。
  - 增加 closeout 前置条件和 logical-turn 预算对账。
  - triage 成为 root/child 第一次正常路由前的 decision。

- `08-multi-language-harness.md`
  - 三步合同扩为“三步 + 控制订阅义务”。
  - 定义 live steer、interrupt、receipt、lease-loss 行为。
  - 增加 harness envelope conformance fake。

- `12-intervention.md`
  - 明确核心不直接改写 claimed effect。
  - 区分 sticky cancel、cooperative interrupt、forced kill。
  - 定义 partial artifact 与 unknown。
  - 加 interaction 两段续跑。

- `13-long-running-goals.md`
  - 落定 `v_goal_tree` 字段和 attention 排序。
  - 加 reservation/subtree accounting。
  - 加 triage、parent acceptance、child terminal wake。
  - “总成本 2 列”更新为“2 列 + payload/event/view contracts”，仍无新表。

- `14-fork-and-replay.md`
  - 增加 spawn tool 与 validate-spawn 原子衔接。
  - 定义普通 delegation 默认 `fresh_fork`。
  - exact/recompute 仅用于明确 replay。
  - 加 handoff、budget reservation、worktree policy。

### 其余教程章节的章节级改动

- 第 1 章：注册 steer/handoff/child/terminal 事件形状。
- 第 2 章：说明 logical turn 与 effect/attempt 的三层身份。
- 第 3 章：child closeout 唤醒和 WAIT 恢复。
- 第 4 章：triage decision 模板与 threshold bands。
- 第 6 章：新增 spawn/worktree 目录行；重申 SQL 快路只读。
- 第 7 章：加入五类控制 artifact schema、partial/acceptance contract。
- 第 9 章：只补 mutation_scope/worktree 交叉引用，不改变文件面设计。
- 第 10 章：candidate-module triage 信号绑定 candidate-set hash。
- 第 11 章：区分 cooperative interrupt 与 crash kill。
- 第 15 章：goal tree/attention dashboard 与控制面闭合判据。
- 第 16 章：增加 turn/session/goal 三种读法的端到端集成 gate。

# 4. File-by-file impact

| 文件 | 修改 | 依赖 |
|---|---|---|
| `docs/designs/v13-context-on-pg.md` | 冻结九题全部合同、schema 增量为零、新 gate、修正 G-ctx6 | 首先修改 |
| `docs/reviews/v13-control-plane-completeness-review-2026-09-21.md` | 标记缝 A/B/C 已裁，修正 spawn SQL 矛盾 | 依赖设计裁决 |
| `docs/tutorials/v13/chapters/05-turn-and-advance.md` | triage、六分类、steer watermark、closeout | 依赖信封/事件命名 |
| `docs/tutorials/v13/chapters/08-multi-language-harness.md` | 控制 watcher、interrupt policy、receipt | 依赖 request/result schema |
| `docs/tutorials/v13/chapters/12-intervention.md` | 主动中断、partial、unknown、approval continuation | 与 ch08 必须原子更新 |
| `docs/tutorials/v13/chapters/13-long-running-goals.md` | goal tree、预算聚合、验收链 | 依赖 closeout/spawn |
| `docs/tutorials/v13/chapters/14-fork-and-replay.md` | spawn + validate-spawn + handoff/worktree | 依赖 spawn 参数冻结 |
| 其余第 1/2/3/4/6/7/9/10/11/15/16 章 | 按 §3.9 的接口落点局部增补 | 在主五章之后同步 |

# 5. Risks and migration

这些改动不新增表或必需列，属于 additive protocol migration，但需处理版本混跑：

- 新 envelope 使用不可变 `schema_version=1`；旧 worker 不得 claim 新 schema。
- tools 目录需把 handler contract/schema 版本纳入 claim 资格。
- request/result schema、worker 和 `v13_complete` 校验必须原子部署，否则新 result 会被旧 SQL 误判。
- 历史 terminal session 不强制回填；视图将缺失 closeout receipt 显示为 `legacy/unreconciled`。如需回填，只追加审计事件，不重算或修改历史预算。
- provider 不支持 pending interaction resume 时，只能声明不支持并走 repair，不能模拟兼容。
- worktree locator 是 host-local projection，迁移 worker 后必须 reconcile。

# 6. Implementation order

1. **冻结协议**：确定 artifact/event 名称、六分类、logical-turn/continuation 身份和 closeout 前置条件。
2. **原子落地 envelope + settle**：schema 校验、result 映射、approval 三 effect 链、logical-turn exactly-once budget。
3. **落地 closeout**：三终结事件、预算/artifact/child 对账。
4. **扩展 worker 合同**：steer/cancel watcher、interrupt receipt、partial/unknown；与 ch08/ch12 gate 同步。
5. **落地 worktree tools**：prepare/merge/release、binding artifact、mutation scopes。
6. **落地 spawn tool**：`pg-control` ledgered handler、预算 reservation、validate-spawn、handoff。
7. **落地 `v_goal_tree`**：生命周期、预算、attention 与 child acceptance 汇总。
8. **落地 triage**：decision template、threshold seed、orchestrator prompt、decomposition plan。
9. **端到端验收**：分别以 Codex turn、RP-CE session delegation、LoopX goal 三种读法跑闭合 gate。
10. **更新 §11 交付排序**：
    - 在原步骤 1 前插入“控制协议冻结”。
    - 原步骤 1 后插入 envelope/closeout/worker control。
    - 原步骤 3 recall 完成后启用 candidate-module triage。
    - worktree/spawn/goal tree 与 stannum 刻画并行，不依赖检索扩展。

# 7. 最小落地集

如果只能先做三组：

1. **控制信封 + 六分类 + approval continuation + closeout**：先让 wrapper turn 可持久、可暂停、可对账。
2. **steer/cancel 主动传导 + unknown**：保证干预面在长跑 harness 上真实有效。
3. **spawn + triage + 最小 goal-tree/child 验收闭环**：让会话委托与 goal 治理真正闭合。

worktree 随后必须在启用任何 mutating 外部 harness 前完成；否则只能开放 read-only/explore profile。

---

# 附录:Oracle 轮 2 原文(grok-4.6@xhigh)

# 1. Summary

在**不增加执行机制、不改 9 表骨架、不为 turn/会话/goal 分层建服务**的前提下，把调查报告缺口 1–5 与完备性复核缝 A/B/C、以及「第一跳 triage」收成同一组原语上的**信封、目录行、事件类型、视图谓词、worker 合同**。做法是：harness 续跑用**新 effect + 冻结 request**（禁止同 `effect_id` 换 request 再 attempt）；结果分类以 v13 四值驱动 `v_routes`，LoopX 六值只作对照注释；审批走「settle → human → 再开 harness effect」两段；`v_goal_tree` 纯视图；closeout 三条终结事件带对账载荷；worktree 用 latch+artifact+effect，零会话列；steer 补进 G-ctx1 水位断言；长跑中断是 handler **一务** + 目录声明；`spawn_subsession` 落 `tools`（`kind=sql` 写允许名单），不改 `v_routes`；triage 是 `decisions` 一题，SQL 先短路、Jev 只裁中间带，分解失败封闭为「不拆」。相对 `docs/designs/v13-context-on-pg.md` §11，控制面收尾与承重件**并行插入**，不依赖 stannum。

---

## 2. Current-state analysis

### 2.1 已闭合的机器（不要重做）

三条时间尺度已经是**同一组原语的三种读法**，不是三层服务（调查 §2–§3；复核 §0）。

| 原语 | 所有者 | 相关变异点 | 推进/观察 |
|---|---|---|---|
| `sessions` + `parent_session_id` / `parent_cutoff_seq` | 行是 goal/会话身份 | fork/spawn 落行；预算归属语义已预付（ch13「2 列 + 2 纪律」） | 视图投影树 |
| `events` append-only 无洞 `seq` | 唯一干预通道 | `v13_append_event`；G-ctx1 禁止解析相挡住 INSERT | 水位 = `max_event_seq` / `goal_hash` / `candidate_set_hash` |
| `effects` 四件套 + 单活跃索引 | 有界工作段 | `v13_claim` / `v13_complete`；`ready`/`claimed` 互斥 | settle = LoopX DURABLE_WRITEBACK |
| `decisions` + `request_hash` | Jev 证据，不授权动作（设计 §6.1） | `v13_parse` 里 `v13_resolve_judgments` | 变更相只读已落行 |
| `thresholds` + `v_routes` | 动作授权 | 动作空间闭集：`sql` / `tool` / `llm` / `human` / `finish` / `reject`（ch05 §5.2④；复核 §2 缝 C） | 版本化带宽 |
| `tools` 目录 | handler 词表、`kind`、allowlist、`mutating` | 轻工具变更相同事务；重工具入队 | 新能力 = INSERT 行 |
| `artifacts` | 内容寻址不可变 | 第 7 章平面；`produced_by` 溯源 | 信封载体 |
| `v13_parse` + `v13_advance` | 唯一推进函数 | 两事务；三来源同语义（settle / 扫地僧 / 人工） | 水位不一致弃批 |
| `v13_cancel` 粘性 | 事实，不杀 in-flight（ch12 §12.3） | claimed 等 settle 吸收 | 不传导子进程（缝 A） |
| pg_cron 扫地僧 | `v13_requeue_stale` / `v13_recover_idle` / 投影 / `verify_index` | **不是** `SELECT v13_advance FROM sessions`（ch13 §13.2） | 丢通知缝 |

外部 harness 已裁 **wrapper**：bounded turn 在 v13，harness = `handler` worker（调查 §4；ch13「executor = handler」）。RP-CE 五原语已有落点：`startOrResume`→建 effect；`sendUserMessage`/`steer`→`append_event`；`interruptTurn`→cancel 事件（进程级未闭合）；`respondToPermissionRequest`→human effect；`shutdown`→租约/fence。

### 2.2 阻塞点（字段/合同，不是新循环）

1. **会话间 handoff 无信封**（调查 §5.1）；**effect↔harness 无 request/result/续跑字段**（复核缝 B）。`v13_complete` 一笔到底，中途抛不出审批。
2. **`v_goal_tree` 未写死字段**（ch13 练习 1）；**closeout 三出口未写死形状**（ch05 练习 1）。
3. **worktree 与 `mutation_scope` 的归属未裁**（复核 1.3）；sitting_duck 在 duck 侧，不覆盖 `handler='claude-code'`。
4. **steer 消费**只靠水位复核叙事，G-ctx1 未钉「旧 `request_hash` 不得进新现场」（调查 §3.3、缺口 5）。
5. **粘性 cancel 不杀 20–30min harness**（复核缝 A；ch12 原文 vs ch11 崩溃杀点）。
6. **`v_routes` 无建会话动词**；ch14 已证明 worker 可以是「新会话的创建者」，但未进编排路径（复核缝 C）。
7. **第一跳 triage 不存在**。现有路由假定「本会话就是执行者」。分解若做成 Python pipeline 或新调度表，即调查 §5 反面警示。

### 2.3 可复用、禁止复制

- 复用：`v13_fork` / `v_prefix_events` / validate-spawn / 三种回放（ch14）；human effect=慢速 worker（ch12）；`v13_resolve_judgments` 双速（ch05）；latch INSERT-once（设计 §5.1）；artifacts + `pg_jsonschema`（设计 §8）；`recover_idle` 谓词（ch13）。
- 禁止：六层控制面表（v11 / ch13）；`v_routes` 加编排状态机；harness in_loop 回写自己的状态（调查 §4–§5）；同 `effect_id` 在 request 已变后 `attempt++`（破坏 ch08「请求已冻结」）；child closeout 与 parent `FOR UPDATE` 同事务抢锁（见 §3.8 / §3.2）。

### 2.4 针对性改 vs 重构

**针对性填补。** parse+advance、单活跃、干预面、settle 同事务预算均已承重。缺口与缝在复核 §3 已定性为「信封与合同形状」。triage 用既有 `decisions`×`thresholds`×spawn 工具即可，无需第三循环。唯一要**明文修正**的既有句子：ch05「`kind=sql` = 纯只读函数」——会话树写入（`v13_fork` / `v13_spawn_subsession`）是库内行变更、非外部 IO，必须进变更相允许名单，否则要么违反只读教条，要么把建会话打进队列变成假重工具。

### 2.5 实现期必须核对（文档未给冻结 DDL）

| 未知 | 核对方法 |
|---|---|
| `effects.status` 闭集、是否已有 `cancelled` | 对照 v8/v12 账本与 ch12 伪代码 |
| `tools` 是否已有 `metadata jsonb` / `input_schema` | 有则 `interruptible` 进 metadata，不加列 |
| `v13_complete` 参数与 `v13_recover_idle` 谓词原文 | 以将落地的 `v13/loop/*.sql` 为准扩谓词 |
| 文件面 I-file-1…7 逐条原文 | 本上下文仅有「FS IO 全 effect」互证；实现前打开姊妹篇，确认 worktree 不另开 FS 控制面 |
| `v13_fork` 是否已实现 | 未实现则与 spawn **同一 PR 落地**（共享 primitive） |

**假定（全文有效）：** 单活跃 = `UNIQUE (session_id) WHERE status IN ('ready','claimed')`；`v13_append_event` 更新 `sessions.next_seq`；生成 IO 永不进事务；harness 内部 loop 不可观察。

---

## 3. Design

### 3.1 控制面信封族（缺口 1 + 缝 B）

**裁决：** 全部是 `artifacts.kind` + `pg_jsonschema` + `tools.input_schema`，**零新表、零 effect 链列**。续跑 = **新 `effect_id` + 新冻结 request**。结果路由权威 = **v13 四值**。审批 = 两段 effect，中间 human，靠 artifact 引用关联。

#### 种类与载荷（闭集）

| `artifacts.kind` | 方向 | 核心字段（形状，非实现） |
|---|---|---|
| `handoff` | 会话→会话 | `delivery_id`（幂等）、`from_session_id`、`to_session_id`、`transcript_hashes[]`、`file_hashes[]`（可选）、`goal_artifact_hash`、`parent_cutoff_seq` |
| `harness_request` | effect→harness | `mode: start\|resume`、`harness`、`harness_session_ref`（对 v13 不透明）、`prompt`、`policy{sandbox, approval_mode}`、`approval_response?`、`resume_from{effect_id, artifact_hash}` |
| `harness_result` | harness→effect | **`result_kind: progress\|finish\|wait\|reject`**、`wait_reason?: approval\|evidence\|quota`、`delivery_kind?`（LoopX 六值，**只注释/对照，路由不读**）、`harness_session_ref`、`resume_token?`、`interaction_id?`、`partial?: bool`、产出 `content_hash[]` |
| `approval_question` | 上行 | `interaction_id`、`question`、`origin_effect_id`、`resume_token` |

Handoff **不**采用 RP-CE `<forked_session>` XML（调查附录 A）；正文进 artifacts，事件只存 hash。`delivery_id` 冲突：`ON CONFLICT` / 唯一 `(delivery_id)` 在 artifact 外键或事件载荷校验——重复投递不建第二会话。

#### 续跑为什么不能是同 `effect_id` 的新 attempt

ch08：「请求已冻结：worker 原样发送 request」。attempt 只服务**同一 `request_hash`** 的崩溃/unknown 重试。审批后 request 多了 `approval_response` 与人的答案，hash 必变。同 id 换 request = 第二真相，fence 对账失效。

逻辑键（uuid v5 输入，示意）必须包含：`session_id + tool_name + mode + harness_session_ref + interaction_id? + resume_from.effect_id? + request_body_hash`。同一续跑被 recover 两次 → 同一 `effect_id`。

#### 审批两段与单活跃

```
harness_1 claim → 子进程停在审批
  → v13_complete(succeeded, harness_result{result_kind:wait, wait_reason:approval, ...})
  → 该 effect 离开 ready/claimed（单活跃释放）
v13_parse / v13_advance
  → 建 human effect（request 指向 approval_question）
human settle
v13_parse / v13_advance
  → 建 harness_2（mode=resume，request 内嵌 resume_from + approval_response）
```

禁止：`needs_approval` 作为 `effects.status`（会扩大四件套）；禁止同一行先 succeeded 再变回 claimed。关联只经 `resume_from` 与 `produced_by`，不经 `predecessor_effect_id` 列。

乱序/重复：迟到的 harness_1 `complete` 走既有 fence → stale；重复 human settle 由 fence 拒；harness_2 在 human 未终态前不可建（变更相只在无活跃 effect 时建下一单）。

#### result 四值，不用 LoopX 六值进路由

| 信封 `result_kind` | 变更相 | LoopX 对照（非权威） |
|---|---|---|
| `progress` | 不终结；下一格 parse+advance | VALIDATED_PROGRESS；REPAIR/REPLAN **降为事件信号**（`repair/required`、`replan/required`），仍走 `progress` |
| `finish` | `v_routes` → finish + closeout | VALIDATED_COMPLETION |
| `wait` | 不建下一执行 effect；`wait_reason=approval` 则建 human | USER_ACTION_REQUIRED / WAIT |
| `reject` | reject + closeout `failed` | 不可恢复 |

**理由：** 复核缝 B 问的是「路由视图怎么消费」；`v_routes` 闭集没有 repair/replan。六值焊进动作空间 = 第三套动词（调查 §3.1 / 复核 §0 已拒）。REPAIR/REPLAN 是 fold 信号，给后续 triage/steer 看，不是新机器。

#### 并发与失败

- wrapper 超时：按既有 unknown 墙（ch12），不把「审批暂停」标 unknown——审批是 **succeeded + wait**，副作用（harness 会话仍活）记在 `harness_session_ref`，由下一 resume 接。
- resume 时 harness 会话已死：worker 申报 known 失败 → `result_kind=reject` 或 `progress`+事件 `harness/session_lost`；**禁止**静默 `mode=start` 另开会话（会裂第二执行者）。要重开必须新 effect 且 `mode=start`，由策略/人显式授权。
- 空 prompt + `mode=start`：fail-closed reject（对齐 ch05 练习 2 空 fold）。

#### Gate 草案

- 同逻辑续跑两次 claim → 同一 `effect_id`；request 字节含 `resume_from.effect_id`。
- 审批段：harness_1 与 human、human 与 harness_2 **从未**同时 `ready|claimed`。
- `delivery_kind` 被乱填不影响 `v_routes`（只读 `result_kind`）。
- `mode=resume` 缺 `resume_token` 或缺 `resume_from.artifact_hash` → 不得入队。

---

### 3.2 `v_goal_tree`（缺口 2）

**裁决：** **纯 `VIEW` + 递归 CTE**，不建投影表。字段含**预算递归聚合**与**计算列 attention 键**；刷新 = 查询时。物化进 YAGNI：仅当看板 p99 实测超标（对齐设计 §12「age 排除：目标树是递归 CTE」；LoopX 看板「projection, side-effect free」）。

#### 视图形状

`v_goal_tree(root_id uuid)`（参数化函数返回 setof，或 `WHERE` 根过滤；实现选函数，避免无参全库扫）。

每行：

- 身份：`session_id`、`parent_session_id`、`depth`、`root_id`
- 状态：`session_status`、`turn_no`、`max_turns`
- 活跃工作：`active_effect_kind`、`handler`、`effect_status`、`lease_until`（LEFT JOIN 单活跃）
- 预算：`spent_turns`（本行 `turn_no`）、`reserved_turns`（本行 `max_turns`）、`subtree_spent`、`subtree_reserved`（非终态子孙 `max_turns` 之和）、`quota_remaining`（策略行 − 子树已花；**资格只读 thresholds，与 cron 间隔无关**）
- 汇总：`n_children`、`n_active_desc`、`n_waiting_desc`、`n_terminal_desc`、`n_failed_desc`
- 干预：`has_cancel`、`has_unconsumed`、`last_material_seq`、`last_material_at`
- `attention_rank`（生成，不落盘）：`user_gate/human` > `unknown` > `cancel` > `duty_cycle=0` > 其余按 `last_material_at` 新者优先

环：`depth` 上限取策略 `max_spawn_depth`（默认 8）；CTE 超深或回到已见 id → 视图仍返回已见节点，**gate 另断言无环**（ch13 已要求）。

#### 谁读

- 看板 / 人：直接 SELECT。
- **`v13_advance` / `fold_state`：** 协调者会话（存在未终态子会话，或已有 `child/closed` 待消费）必须读子树汇总，决定 `wait` vs 验收，**禁止**为「看树」建订阅服务。

#### 子完成如何唤醒父（锁序）

子 closeout **不得**在持有子 `sessions FOR UPDATE` 的同一事务里 `v13_append_event(parent)`：`append` 要改父 `next_seq`，与父变更相 `FOR UPDATE` **锁序对撞**（ch02 两级锁序）。

**唤醒：**

1. 子终结只写子日志 closeout。
2. 调用者在子事务提交后**可以** `parse+advance(parent)`（与三来源同语义）。
3. `v13_recover_idle` 谓词扩展（仍是扫地僧，不是节拍器）：

```
非终态 AND 无 ready/claimed effect AND (
  有未消费事件
  OR 存在子会话 AND 全部子终态 AND 父尚无一条「覆盖最后子终态」的验收/closeout
)
```

连续两扫仍须零**多余** effect；验收只建一次 human/finish。

---

### 3.3 closeout 事件族（缺口 3）

**裁决：** 三种事件类型，载荷是**对账收据**（计数 + hash），不含正文。写在变更相、与 session 终态、预算终态**同一事务**（LoopX TERMINAL_CLOSEOUT = 调查 §3.4）。

#### 事件

| `type` | 触发 | 必有载荷 |
|---|---|---|
| `session/completed` | `v_routes=finish` | 见下 |
| `session/failed` | `reject` 或预算耗尽强制失败 | `closeout_reason ∈ {reject, budget_exhausted, harness_reject, invalid_input}` |
| `session/cancelled` | 粘性路径收束 | `closeout_reason=cancel`；前缀必须存在 `cancel/requested` |

公共字段：`turn_no_final`、`spent{turns, subtree_turns}`、`produced_hashes[]`、`produced_count`、`unconsumed{count, max_seq, types[]}`、`pending_effects_count`（必须 0）、`parent_session_id`、`active_policy{name, version}`。

`unconsumed`：**列出，不静默丢**。`cancel/requested` 算已消费。其它未消费用户消息进载荷；gate 不因多一条未消费而拒 closeout（避免干预面被「必须先耗尽 inbox」卡死），但 `completed` 且 `unconsumed.types` 含 `user/message` → 审计事件 `closeout/inbox_residual`（仍同一通道）。

#### 预算对账

不变量（与 ch05⑤、ch13 子树聚合同一句话）：

- `turn_no_final` = 本会话变更相成功递增次数。
- `subtree_spent` = 子孙 closeout `spent.turns` 之和（无子孙则为 0）。
- 父未终态时，父配额视图含本会话花费。
- `pending_effects_count=0`；否则不得写终结（fail-closed）。unknown 未 `resolve_unknown` → **不得** closeout（ch12：cancel 不能掩埋 unknown）。

---

### 3.4 worktree 隔离（缺口 4）

**裁决：零核心 schema 列。** 创建/回收是 **FS effect**；绑定是 **latch + artifact**；与并行纪律的接点是 **`mutation_scope` 约定**。不把路径写进 `sessions`（路径是执行者环境，不是身份；goal 活过线程，worktree 不活过机器——LoopX「executor ephemeral」）。

#### 归属

| 动作 | 谁 | 形态 |
|---|---|---|
| 创建 | 该 session 第一个 harness `mode=start` 的 worker，或目录工具 `ensure_worktree`（同样 handler） | 进程内建目录/worktree；成功后 artifact `worktree_binding{worktree_id, path_or_ref, git_head?, created_by_effect_id}` |
| 冻结 | 同会话 `latches.name='worktree'`，`value=worktree_id`（**不是**绝对路径，避免机器漂移打碎语义） | INSERT once；参与 ForkPrefix 与否：**默认不参与 prefix_identity**（path/id 会无意义地 cache-break）。身份仍是 system/tools/model/其它 latch |
| 关联会话 | 事件 `session/worktree_bound` + latch；不 ALTER `sessions` | |
| 回收 | **closeout 之后**的独立 effect 或扫地 `v13_reap_worktrees`（YAGNI，默认不自动 rm） | 无 closeout 不得删；有未终态子且误共享 → 禁止共享（见下） |
| 并行 | 该会话 mutating 文件/harness effect 的 `mutation_scope = 'wt:'\|\|worktree_id` | 复用 ch08 `op_seq`；跨 session 不同 scope 可并行 |

**谁不创建：** `v13_advance`、parse、INSERT `sessions`。无 binding 就跑 mutating harness → worker fail-closed，settle `reject`。

**fork/spawn：** 子会话**不继承**父 `worktree` latch（共享工作树 = 共享可变 FS，打破 ch14「父子并行无共享可变状态」）。分解默认 `fresh_fork` + 新 worktree。`exact_replay` 声明复用父 worktree → **validate-spawn 拒**（复用 FS ≠ 复用 prefix cache）。

与 I-file：FS 变更只经 effect；binding 是证据行，不是第二套 worktree 表。

---

### 3.5 steer 消费时机（缺口 5）

**裁决：** 不改推进函数结构；**扩展 G-ctx1**。语义已在设计 §6.1「快照复核」与调查 §3.3：steer 就是 `user/message`（或 `steer/injected`，若要可过滤；**权威仍是 events INSERT**）。进行中 turn **不**把新事件缝进已冻结 request。

#### 数据路径

1. 解析相：`v13_parse` 读水位，算 `request_hash` / 候选。
2. 此时 B 连接 `v13_append_event(steer)` 必须立即成功（既有 G-ctx1）。
3. `v13_advance(stale_snap)`：锁下水位 ≠ snap → **弃批、零新 effect**，返回调用者可识别的 `reparse`（或现有等价文本）。
4. 重 parse：`fold_state` 含 steer 的 `seq`；新 `request_hash` ≠ 旧。
5. 已 `claimed` 的 harness：request 不变；steer 等该 effect settle 后再被下一格消费。进程内「把 steer 推给子进程」仅当缝 A `interruptible` 且 handler **自愿**读新事件——**核心不保证**，gate 不要求 in-flight 融合。

重复 steer：多条事件，fold 全收，不去重（人连发即连发）。丢弃：只允许水位弃批丢**过期 snap**，不丢事件行。

#### Gate 草案（`G-ctx1-steer`）

- parse 暂停中 INSERT steer 立即成功。
- 随后 `advance(旧 snap)` → `reparse`，`effects` 无新行，`typesafe` 调用不按旧 hash 出站。
- 再 parse+advance：fold 含该 `seq`；若建 llm/harness，`request_hash` 与无 steer 基线不同。
- claimed 期间插入的 steer：**不得**出现在该 effect 的冻结 request 里；settle 后下一格必见。

---

### 3.6 cancel 传导深度（缝 A）

**裁决：** **handler 合同加第四务（订阅 cancel）为主**；`tools.interruptible`（或 `metadata.interruptible`）为**声明**，供 claim/UI/gate 过滤，**不是**内核杀进程。默认 `false` = 维持 ch12 粘性。长跑 harness 目录行必须 `true`，否则 G6 扩断言红。

#### 合同（ch08 三步 → 三步 + 一务）

```
1 claim
2 IO
3 complete
4 若本单 tools.interruptible：执行期间轮询（或 LISTEN，进程内）本 session
   是否已有 cancel/requested；有则中断子进程，再 complete
```

核心不发信号、不引入 pg_net。杀点是 worker 读到的**事实**（与 ch11「杀点是事实、恢复靠账本」同构；ch11 杀的是 worker 自身/崩溃边界，本缝杀的是**子 harness 进程**）。

#### 中断后 settle

| 观察 | `v13_complete` status | result |
|---|---|---|
| 子进程已停、无未确认 mutating 副作用 | `cancelled` | `harness_result{result_kind:reject 或 wait, partial:true, hashes}`；会话走粘性 closeout |
| mutating 中杀、对面不知是否生效 | **`unknown`** | 证据；**禁止**用 cancelled 掩埋（ch12 原文） |
| 未订阅 / `interruptible=false` | 粘性：跑完再 settle，advance 吸收 | 与现网相同 |

`cancelled` 的 effect 仍留痕；turn 不继续。部分结果只作审计，不得当 `progress` 成功交付。

#### 父取消与子树

`v13_cancel(root)`：**同事务**对非终态子孙各插一条 `cancel/requested`（只写事件，不 lock-and-kill 子进程）。子孙 worker 按声明自行中断。父 closeout 仍等：子孙 unknown 先 resolve；或父先 cancelled、子孙仍跑——**不允许**。父 cancelled 的 gate：所有子孙已终态或已有 cancel 事件且无「无 cancel 的活跃 claimed mutating」。实现取严：父 closeout 推迟到子孙无 `ready|claimed` 且无未解 unknown。干预面仍开（事件已插入）。

#### Gate

- G6：cancel 后 `interruptible` fake 在上限内（测试用短时钟）停止「外部调用计数」不再增加；`false` 的 fake 可跑完再吸收。
- unknown+cancel：只能 `resolve_unknown` 关门。
- 核心 SQL 中不出现对 OS pid 的引用。

---

### 3.7 spawn 子会话（缝 C）

**裁决：`INSERT tools` 一行 `spawn_subsession`，不把 `spawn` 加入 `v_routes`。** 执行函数 `v13_spawn_subsession` 与 `v13_fork` **同一 primitive**（两列 + `forked` + 可选 handoff artifact + validate-spawn + 预算准入）。`kind=sql`，列入**变更相写允许名单**（仅会话树：INSERT `sessions` / 事件 / latch，零外部 IO）。

**理由：** 复核缝 C 已给哲学——「重工具走账本、路由只做动作分类」；编排闭环是 LLM（或人、dream worker）调工具，不是路由多一个状态（调查 §1.2「编排是提示词不是引擎」）。硬编码 `v_routes=spawn` 会让 triage 不经模型直接裂变，变成被拒的 pipeline。

#### 参数（`tools.input_schema`）

```
parent_session_id     -- 工具面默认当前 session
cutoff_seq            -- 默认父当前 max_seq；写入后永不改
replay_kind           -- exact_replay | recompute | fresh_fork
                      -- 分解默认 fresh_fork
objective_hash?       -- 子 goal artifact；缺省则 inherit 父 goal_hash
budget: { mode: share|fixed, max_turns, quota_share? }
handoff_hash?         -- kind=handoff
```

预算准入（与父 `FOR UPDATE` 同事务）：

```
subtree_reserved + requested_max_turns ≤ parent 剩余可分配
```

`subtree_reserved` = 非终态子孙的 `max_turns` 之和（与 `v_goal_tree` 同式）。超则函数失败，advance 不落子行（fail-closed）。实际扣减仍按 ch13：花费递归聚合，**不**在 spawn 时预扣 turn_no；预留的是 **admission 上限**。

validate-spawn（ch14）：`exact_replay` 且将破坏 prefix_identity → 拒；分解默认 `fresh_fork`，允许新 hash。绑定父 worktree → 拒。

#### 谁可调

| 调用者 | 允许 |
|---|---|
| 变更相因 llm 点名该工具走 `v_routes=sql` | 是（主路径） |
| 人工/`psql` 直调函数 | 是（第三来源） |
| dream worker / 任意已连库 worker | 是（ch14「日志读者 + 新会话创建者」） |
| 子进程 harness 自己 INSERT sessions | **否**（第二真相） |

每次成功 spawn：**一条 `forked`（或 `session/spawned`）事件**，载荷含 `replay_kind`、`prefix_identity`、预算声明；handoff 另条或同事务附 hash。ch13 预算归属 gate 已有，加「spawn 即落 forked」。

`kind=sql` 教条修正（必须写进 ch05/ch06，否则实现者会做成只读而无法 INSERT）：

> sql 快路 = 变更相、零外部 IO、零队列。默认只读；**允许名单**内函数可写 `sessions`/`events`/`latches`/`artifacts` 指针。名单外写 → 部署 gate 红。

---

### 3.8 任务分级路由 triage（新题）

**裁决：** 采纳「decisions 一题 + thresholds 带宽 + 中间带 Jev + 子任务=spawn + 深度靠再 triage 而非固定层数」，但**改三条**以免暗建成编排引擎：

1. **根上长度不是简单/复杂的硬分界**（一句「做完这个产品」很短且复杂）。
2. **Jev 只产 `triage_class` 证据，SQL 策略独占是否 spawn**（设计 §6.1）。失败封闭：**不拆**（`direct` 或 `human`），永不默认 `decompose`。
3. **验收不靠新 gate 服务**：子终态由扫地谓词 + fold 读 `v_goal_tree`；SQL 先判全成功则父可 finish；有失败/取消走 human 或 `reject` 策略带。

#### 这不是新机制

用的是：判断信封模板 `triage.v1`、`v13_resolve_judgments`、thresholds、`spawn_subsession`、`wait`（有活跃子且无新用户意图时）、`recover_idle` 扩谓词、closeout。没有 task 表、没有 coordinator 运行时、没有固定 decompose pipeline。会话是否协调者 = **是否有子孙**（或 latch `triage_verdict`），不加 `sessions.role`。

ch14 dream / 显式 `v13_fork` **绕过** triage（调用方已声明 `replay_kind`）。

#### 信号集（`triage.v1` 投影；未声明字段不得出站——设计 §6.5）

硬进信封（便宜、可复现）：

| 字段 | 来源 | 用途 |
|---|---|---|
| `task_content_hash` | 当前用户任务 artifact | 缓存键 |
| `task_est_tokens` | SQL 估计 | 中间带特征，**根上不作硬拆** |
| `ancestor_depth` | parent 链 | 硬规则 |
| `n_nonterminal_children` | 树 | 硬规则 |
| `remaining_turns` / `quota_remaining` / `subtree_reserved` | 会话+策略+视图 | 硬规则 |
| `user_intent_override` | 事件 `goal/direct` \| `goal/decompose` \| null | 最高优先 |
| `has_mutating_hint` | 目录/关键词廉价提示，**不是**模块数分析 | 仅软特征 |
| `policy_version` | thresholds | 信封版本 |

**不进首版：** 「涉及模块数」、仓扫描、预取（触点 6 仍在台账）。模块图若存在，只能是**先前会话已落的 artifact**，经声明字段进入，不得为 triage 新开解析相 IO。

#### 分界（SQL 短路 → 中间带 → 默认）

```
1. fold 空 → reject（ch05 练习 2）
2. duty_cycle=0 → 不建工作（既有）
3. user_intent_override=direct → direct
4. user_intent_override=decompose → 仍要过预算/深度准入，然后 llm（工具面含 spawn），不经 Jev
5. ancestor_depth ≥ max_spawn_depth 或 剩余可分配 < 再开一个最小子会话
     → 禁止 decompose，direct；分不出则 human
6. ancestor_depth ≥ 1 且 override is null
     → 默认 direct（子任务已收窄；再拆必须 override 或中间带高置信 decompose）
7. 其余（典型：depth=0 且无 override）→ Jev Choice{direct, decompose, human}
     raw 不可变；thresholds 映射动作
     review/超时/缺失 → triage_fail_closed：根默认 human，depth≥1 默认 direct
```

**不要**用 `task_est_tokens < N ⇒ 简单`。N 只作 Jev 特征或 shadow hint。

中间带预算：走既有快路批上限（默认 ≤1 批）。triage 与摘要验收抢批时，策略行规定 triage 优先（无 triage 证据不得 `decompose`）。

#### 深度与 bounded turn 联动

- 无全局层数机器；`thresholds`：`max_spawn_depth`、`min_child_max_turns`、`parent_orchestrator_max_turns`。
- **根若 `decompose`：** 根变为协调者——自身 `max_turns` 只覆盖编排（triage/验收/spawn 调用），**工作 turn 在子会话**。实现：decompose 裁决落 latch `triage_verdict=decompose`（INSERT once）并**下调**根剩余编排预算（策略常量，非新列也可写 sessions 已有 `max_turns` 若尚未递增——若已跑过 turn，只限制**剩余**可分配给子的额度）。
- 每个 spawn 再跑准入（§3.7）。子会话 parse **再走 triage**（通常命中规则 6 → direct）。
- 根不得与子抢同一 worktree（§3.4）。

#### 验收链

```
子 closeout 提交
  →（可选）调用者 parse+advance(父)
  → 否则 recover_idle 扩谓词捞起父
父 fold：
  子树未齐 → wait（零新执行 effect；用户 steer 仍可进 events）
  全 completed → SQL 允许 finish，或一条 accept 判断（触点 2 级，P1 仅当要做语义验收；首版 SQL 全成功即 finish）
  任一 failed/cancelled → 策略：human 或 reject，禁止假装 completed
```

不要「全子完成必须 human」。不要 barrier 表。

#### 反例（做错会怎样）

- 根用字数硬拆：短目标裂不出树；长描述被无意义拆成十几棵空会话，quota 被 `subtree_reserved` 占满，真正执行者拿不到 turn。
- Jev 超时默认 `decompose`：解析相失败却裂变——第二调度面的伪装。
- 父 closeout 同事务写父事件：锁序对撞，干预面或父 advance 卡死。
- 为 triage 建 `tasks` 表 / coordinator 进程：复核 §0 尺子红，v11 第二调度面复活。
- 固定 `max_depth` 当产品功能、却不跑准入：深层子会话超支；或深度 1 封死再 triage，复杂工作无法逐步收窄。
- 子会话再拆无 override：扇出爆炸，看板不可读，预算预留下限被打穿。

#### Gate 草案（`G-triage`）

- 空 fold → reject，零子会话。
- override=`direct` → 零 `spawn_subsession` 调用。
- override=`decompose` 且剩余可分配 < `min_child_max_turns` → 零子行，human 或 waiting，不静默 direct 假装已拆。
- `ancestor_depth ≥ max_spawn_depth` → Jev 即使返回 decompose，SQL 仍 `direct`。
- mock 下 Jev 超时：根不落子会话；decision 不落行（ch05「超时不落行」）。
- 同 `task_content_hash`×同投影二次 parse：零新增 Jev（`request_hash` 命中）。
- 两子完成后父被 recover：至多一个验收/finish 路径；连续两扫零多余 effect。
- 改未声明字段（例如临时加入「模块数」）→ 出站 payload 不变（§6.5 canary）。

---

### 3.9 文档与交付排序（第 9 题）

**原则：** 章节级补丁，不重写 16 章；设计文加一节「控制面信封与三读法闭合」，不改 §4 承重件。相对 `docs/designs/v13-context-on-pg.md` §11：**控制面收尾与承重件并行**，不插入 stannum 刻画之后——信封/closeout/steer/spawn 不依赖检索。

#### 落地分层（什么进核心、什么不进）

| 层 | 进 | 不进 |
|---|---|---|
| 核心 schema（9 表） | **零新表零新列**（worktree/handoff/triage 均不 ALTER `sessions`） | `sessions.worktree_path`、`predecessor_effect_id`、`tasks`、`emergent`（仍 P2） |
| 核心函数/视图 | `v13_spawn_subsession`（与 `v13_fork` 同 primitive）、`v_goal_tree`、closeout 写入点、`v13_recover_idle` 谓词扩展、sql 写允许名单、`v13_cancel` 子树事件扇出 | 新 advance、新队列、pg_net |
| 目录行 | `spawn_subsession`；harness 工具 `input_schema`；`interruptible`；判断模板 `triage.v1` | 每 provider 一张表 |
| 事件类型（开放词表） | `session/completed\|failed\|cancelled`、`forked`/`session/spawned`、`session/worktree_bound`、`closeout/inbox_residual`、`repair/required`、`replan/required`、`steer/injected`（可选别名，权威仍是 message） | 新生命周期状态机 |
| artifacts + jsonschema | 四信封 + `worktree_binding` + `approval_question` | XML handoff |
| worker 合同文档 | 第四务；wrapper 一笔到底 vs 审批两段 | 内核杀 pid |
| thresholds | `quota.should_run`、`max_spawn_depth`、`min_child_max_turns`、`triage` 带宽、`triage_fail_closed` | cron 间隔当 duty_cycle |

#### 设计文档（`v13-context-on-pg.md`）

| 位置 | 改什么 |
|---|---|
| §3 后或新 **§3.1 控制面闭合尺子** | 复核 §0 整段迁入：三读法动词闭合；禁为层次建服务 |
| §6.1 快照复核 | 显式点名 steer = 事件；旧 `request_hash` 不得用于新水位（缺口 5） |
| 新 **§6.8 控制面信封族**（短） | 四 kind、续跑=新 effect、四值路由、审批两段、禁止同 id 换 request |
| §9 增量 | 只追加「无新表；信封在 artifacts」一句，不画新 DDL |
| §10 | `G-ctx1` 扩 steer；新 `G-ctx10` 信封/单活跃两段；`G-triage`；G6 扩 interruptible |
| §11 | 在步骤 1 并列插入「控制面最小集」（见下优先序），不推迟到步骤 4–6 |
| §12 YAGNI | 工作树自动 reap、看板物化、triage 进模块图、LoopX 六值升格为路由 —— 各写触发条件 |
| §13 教程映射 | 增补 ch05/06/08/12/13/14 指针（见下） |

**不改：** §4.1–4.8 召回/chunks/两阶段物理、§5 五件套经济学、§7 T0/T1/T2。

#### 教程 16 章（章节级）

| 章 | 补丁 |
|---|---|
| **ch05** | 练习 1 升格为规范：closeout 三形状 + 预算对账；`kind=sql` 改为「零外部 IO 快路 + 写允许名单」；`v13_advance` ① 后加「协调者：有未齐子树则 wait」。G-ctx1 加 steer 四条。 |
| **ch06**（未在本次细读，必须补） | `INSERT tools`：`spawn_subsession`；允许名单执法；`interruptible`/`input_schema` 为目录数据。练习：只 INSERT + 起 worker，SQL 文件零改（保持 ch08 练习 3）。 |
| **ch07** | artifacts 硬性规定增加四信封 kind + `pg_jsonschema` 版本；handoff 只存 hash。 |
| **ch08** | 三步 + 一务；G6 扩「cancel 后 interruptible handler 外部调用提前停」；错误信封增加 `cancelled`/`unknown` 对照表。 |
| **ch11** | 一段对照：kill-at-every-boundary = 崩溃杀 worker；缝 A = 控制语义杀子进程；恢复仍只靠账本。 |
| **ch12** | 粘性为默认；`interruptible` 为合同升级；unknown+cancel 顺序不改；审批上行「human = 慢速 worker」加两段时序图。 |
| **ch13** | 练习 1 升格：`v_goal_tree` 字段族；映射表加信封/closeout/worktree latch 三行（成本仍 0 列）；`recover_idle` 扩谓词写进 §13.2，强调仍非节拍器；练习 3 与 spawn+reward 对齐。 |
| **ch14** | `v13_fork` 与 spawn 同 primitive；validate-spawn 加「禁止共享 worktree」；dream 路径绕过 triage。 |
| **ch15** | 台账：自动 reap worktree、看板物化、六值路由；元原则三条下加「控制面新增先过三读法尺子」。 |
| **ch01/02** | 仅交叉引用：事件类型开放；不要加列。 |
| **ch04** | `triage.v1` 作为 decisions 模板一例；阈值带映射 `direct/decompose/human`。 |
| **ch10** | 不把 triage 塞进 assemble；triage 不是 context section。 |

ch03/09 不改机制。

#### 相对 §11 的插入点（优先序）

§11 原序：承重件 → stannum 刻画 → T0 recall → 经济学/摘要 → latch/intent → T1 台账。

控制面插入：

1. **与 §11.1 承重件并行（P0，不依赖 stannum）**  
   closeout 形状；G-ctx1-steer；信封四值 + 续跑新 effect + 审批两段（有 FakeHarness 即可）；`v_goal_tree` 纯视图；`recover_idle` 扩谓词。  
   *理由：这些是账本正确性，缺了三读法在文档上「填了缺口 1–5」仍不闭合（复核结论）。*

2. **紧随 ch06 目录可测之后（P0/P1）**  
   `spawn_subsession` + sql 写允许名单 + validate-spawn 衔接 + 子树 cancel 事件扇出。

3. **与 ch08/G6 同批（P1）**  
   interruptible 合同 + 长跑 fake；worktree = latch + FS effect（无新列）。

4. **triage.v1（P1，但晚于 spawn）**  
   无 spawn 的 triage 只能 human/direct，分解闭环不存在。先 SQL 短路 + fail-closed，再接 Jev 中间带。

5. **不插入 §11 主链**  
   工作树自动回收、看板物化、delivery_kind 升格、模块数信号、预取（仍 §12）。

编号：复核建议 A15 起——建议 **A15 信封族、A16 closeout、A17 spawn/sql 名单、A18 interruptible、A19 worktree-as-latch、A20 triage 证据/动作分离、A21 recover_idle 子树谓词**。与 I-file-1…7 正交，互不改对方字段。

---

## 4. File-by-file impact

实现者按「文档 → SQL 合同 → fake → gate」落地。下列为**将创建/修改的规范与代码锚点**（仓库当前以 docs 与未来 `v13/loop` 为准；教程产出路径已写明）。

### 文档（先冻结裁决，再写 SQL）

| 文件 | 变更 | 为何 | 顺序约束 |
|---|---|---|---|
| `docs/designs/v13-context-on-pg.md` | 增 §3.1 尺子、§6.8 信封；§10/§11/§12/§13 补丁 | 设计权威；与教程冲突时以本文+冻结稿为准 | 必须先于 SQL |
| `docs/reviews/v13-control-plane-completeness-review-2026-09-21.md` | 文末加「Oracle 2026-09-21：缝 A/B/C 已裁」指针 | 防二次开缝 | 可与设计稿同批 |
| `docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md` | 不改调查正文；若需可加「落点已裁」脚注 | 调查保持证据，避免改写史 | 无 |
| `docs/tutorials/v13/chapters/05-turn-and-advance.md` | closeout 规范、sql 名单、协调者 wait、G-ctx1-steer | 推进函数合同 | 依赖设计 §6.8/§10 |
| `docs/tutorials/v13/chapters/06-*.md`（目录章，实现时打开全文） | spawn 行、interruptible、input_schema | 缝 C / 缝 A 声明面 | 与 spawn 函数同批 |
| `docs/tutorials/v13/chapters/07-*.md` | 信封 kind | 缺口 1+B | 先于 harness fake |
| `docs/tutorials/v13/chapters/08-multi-language-harness.md` | 第四务、G6 | 缝 A | 依赖目录列/metadata |
| `docs/tutorials/v13/chapters/11-*.md` | 崩溃杀 vs 控制杀 | 防实现者把 kill worker 当 interrupt harness | 与 ch08 同批可读 |
| `docs/tutorials/v13/chapters/12-intervention.md` | 两段审批、interruptible 默认粘性 | 缝 A/B | 依赖信封 |
| `docs/tutorials/v13/chapters/13-long-running-goals.md` | 视图字段、recover 谓词、映射表三行 | 缺口 2、验收唤醒 | 依赖 closeout 类型 |
| `docs/tutorials/v13/chapters/14-fork-and-replay.md` | fork=spawn primitive、worktree 拒共享 | 缝 C+缺口 4 | 与 spawn 原子 |
| `docs/tutorials/v13/chapters/04-*.md`、`15-*.md` | triage 模板；YAGNI | 第 8 题 | 晚于 spawn |

### SQL / 运行时（实现阶段；本计划不给补丁）

| 预期路径 | 变更 | 为何 | 顺序 |
|---|---|---|---|
| `v13/loop/advance.sql`（ch05 产出） | 水位弃批含 steer 语义（若尚未）；协调者 wait；closeout 调用点；sql 允许名单分派 `v13_spawn_subsession` | 唯一推进函数仍只这一处 | 先 closeout+steer，再 spawn 分派 |
| 既有 `v13_append_event` / events 类型检查 | 放行新 type；closeout 载荷 jsonschema | 开放类型 | 与 closeout 同批 |
| `v13_complete` | 接受 `cancelled`；unknown 规则不改；`harness_result.result_kind` 校验 | 缝 A/B | 先于 interruptible fake |
| `v13_cancel` | 子孙 `cancel/requested` 扇出 | 树取消 | 可独立，建议与 spawn 同批测树 |
| `v13_requeue_stale` / `v13_recover_idle` | 扩「子齐父未验收」 | 非节拍唤醒 | 依赖 closeout 已能写 |
| 新 `v13_spawn_subsession` + `v13_fork`（若无） | 两列、forked、准入、validate-spawn | 缝 C | 与 ch14 练习 1 **原子落地** |
| 新 `v_goal_tree` / `v13_goal_tree(root)` | 递归 CTE | 缺口 2 | 依赖 parent 列（已有）+ closeout 字段可读即可先出瘦视图，再加 spent |
| `thresholds` seed | triage / depth / min child turns | 第 8 题 | 晚于 spawn |
| `tools` seed | `spawn_subsession`；harness 行 schema | 缝 C/B | 与函数同批 |
| `judgment_templates` `triage.v1` | 投影声明 | 第 8 题 | 晚于 thresholds |
| `v13/fakes.py`（及第二语言 fake） | FakeHarness：start/resume/approval/interrupt；interruptible 时钟 | G6/G-ctx10 | 信封 schema 冻结后 |
| jsonschema 夹具 | 四信封 + closeout + worktree_binding | fail-closed 校验 | 与 ch07 同批 |

**不改：** `chunks`/`transcript_chunks`/`latches` DDL 形状（仅**使用** latch 名 `worktree`/`triage_verdict`）；`v_routes` 动作枚举；pg_cron 四条 job 的「不是 advance 全表扫描」形态（可改 `recover_idle` 函数体，不改调度哲学）。

---

## 5. Risks and migration

- **无持久 schema 迁移。** 旧库无新列可读。新事件类型：旧 worker 忽略未知 type（append-only 读者应 fail-open 于未知 type、fail-closed 于未知 **effect status**）。若现存 `v13_complete` 拒 `cancelled`，本变更与 closeout **必须同发**，否则 interruptible worker 无法落账。
- **`kind=sql` 语义收窄/放宽是行为破坏。** 旧读者若假定「sql = SELECT-only」，允许名单外的写仍必须拒。文档与部署 gate 同发，避免有人把任意 DML 塞进快路。
- **回滚：** 停用 spawn 工具行 + 停用 `triage.v1` 即关闭分解；信封校验关掉会使 harness  degenerated——回滚应保留 jsonschema。
- **配额双计数风险：** 若实现者既在 spawn 时预扣 `turn_no` 又在子 advance 递增，对账必炸。本裁决：**spawn 只做 reserved 准入，spent 只在各会话 advance/closeout。**
- **锁序：** 子 closeout 写父 = 已知死锁/干预面风险，属实现红线。

---

## 6. Implementation order

每步应能单独编译/跑所属 gate。标 **原子** 的必须同 PR。

1. **冻结文档：** 设计 §3.1/§6.8 + ch05 closeout 规范 + 信封 jsonschema 夹具。可测：schema 例行能通过 `pg_jsonschema`。
2. **closeout 三事件 + 预算对账断言**（ch05 练习 1 升格）。原子：session 终态 UPDATE + 事件 INSERT。G4 扩：finish/reject/cancel 各一条收据。
3. **G-ctx1-steer**（只加测试 + 若 advance 弃批文案未区分则补返回值）。不依赖 harness。
4. **`v_goal_tree` 瘦视图**（身份/状态/活跃 effect），gate：无环、深度上限。
5. **`v13_fork` + `v13_spawn_subsession` + tools 行 + sql 写允许名单 + forked 事件**（**原子**）。validate-spawn 含拒共享 worktree。ch14 练习 1 与缝 C 同绿。
6. **`v13_recover_idle` 扩谓词 + 协调者 wait**（**原子** 于「有子树的 turn」测试）。关 cron、只 settle：有界单会话仍走完（ch13 既有断言不回退）。
7. **信封驱动 FakeHarness：** request/result 四值、审批两段、续跑新 `effect_id`、单活跃不重叠。`G-ctx10`。
8. **`v13_cancel` 子树扇出 + interruptible 第四务 + G6 扩**（可与 7 并行，合入前两者都要对 unknown+cancel）。
9. **worktree latch + `worktree_binding` artifact + mutating harness 无 binding 则拒。** 不改 sessions。
10. **thresholds + `triage.v1` + fail-closed。** 先只 SQL 短路（步骤 10a），再开 Jev 中间带（10b）。G-triage。
11. **补 `v_goal_tree` 预算聚合字段**（若步骤 4 未含），与 closeout `spent` 对账。
12. **YAGNI 不实现：** reap、物化看板、六值路由、模块数。

步骤 2+3 可先于 5；**5 未落地则 10 不得声称 decompose 闭环**。步骤 7 与 5 无硬依赖，但审批续跑测试需要 advance 稳定。

---

## 最小落地集（只能做三件）

三件必须**一起**才能让复核「会话读法仍剩 3 缝」收口，且不碰 stannum：

1. **控制面信封族 + 续跑新 effect + 审批两段**（A15 / 缝 B + 缺口 1）——没有它，wrapper 无法驱动 Codex/RP-CE 审批与续跑，五原语只在纸上映射。  
2. **`spawn_subsession` = fork primitive + sql 写允许名单 + `v_goal_tree` + closeout + `recover_idle` 子树谓词**（A16/A17/A21 / 缺口 2–3 + 缝 C）——没有它，会话树能 fork 不能编排，goal 看板与 TERMINAL_CLOSEOUT 不闭合。视为**一件原子产品切片**（多文件，但同一发布）。  
3. **G-ctx1-steer + interruptible 第四务**（缺口 5 + 缝 A）——没有它，turn 读法的干预在文档上成立、在长跑 harness 上花钱不停，且旧意图可能污染新现场。

**刻意不进前三：** worktree 列级方案（已裁零列，可第四件用 latch）、triage Jev 中间带（前三之后用 SQL 短路 + 人工/LLM 直接调 spawn 已能分解）、LoopX 六值。

**一句话给实现者：** 先让「行上的信封、终结收据、建子会话工具、水位弃批、可选杀子进程」在同一条 parse+advance 上闭合；不要为 Codex/RP-CE/LoopX 各建一个控制面。
