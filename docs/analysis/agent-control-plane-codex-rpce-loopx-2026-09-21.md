# Agent 控制平面对照调查:Codex / RepoPrompt-CE / LoopX → pg-agent 的统一之道

> 日期:2026-09-21。方法:三个 explore probe(RP-CE 本地源码 / LoopX 本地 checkout / Codex web)
> + 主会话本地验证(vendored codex 0.153.4 二进制、RP-CE 驱动协议逐行抽查、
> LoopX 裁决原文抽查)。probe 完整报告见附录 A/B/C,证据等级见 §7。
> 姊妹篇:`repoprompt-native-on-v13-feasibility-v2-2026-09-21.md`(文件与上下文收集平面);
> 本文覆盖的是**控制平面**(agent loop / 会话 / 委托 / 治理)。
>
> 一句话结论:**Codex 管 turn、RP-CE 管会话、LoopX 管 goal,但三者传递的是同一种东西
> (有界工作段)、保护的是同一条底线(干预面常开、durable state 不归执行者)、
> 用的是同一组动词(观察/注入/应答/取消)。pg-agent 的统一之道不是把三套原语粘起来,
> 而是让最小 loop(parse+advance+settle)成为唯一的存在层——turn、会话、goal
> 只是这层之上的策略行、事件类型和视图。**

---

## 1. 三者各自的控制设计

### 1.1 Codex:黑盒 turn 引擎(最内层,秒–分尺度)

控制模式是**进程内的 turn 状态机**,外部只给「方向盘」不给「变速箱」:

- **turn 是唯一执行单位**:user msg → model → tool_call → sandbox check → execute → 回环;
  `finish_reason=stop` 或 `max_turns` 封界。turn 内部循环不可插拔、不可观察。
- **暴露的控制点**(vendored 二进制 `codex --help` 实测,0.153.4;驱动协议见 RP-CE
  `CodexNativeSessionController`,§1.2):
  - `startUserTurn` / `steerUserTurn` —— steering 是一等公民;`codex queue` 子命令
    给运行中会话排队消息;
  - `interruptUserTurn(expectedTurnID:)` —— 带回执(`CodexTurnInterruptReceipt`);
  - `respondToServerRequest(id:)` —— 审批应答;
  - `compactThread` —— 压缩;
  - `resume` / `fork` —— rollout 会话文件持久化、恢复、分叉;
  - **`getThreadGoal` / `setThreadGoalObjective` / `setThreadGoalStatus` / `clearThreadGoal`**
    —— codex 自己已开始把「目标」从聊天线程里拆出来。
- **沙箱与审批**:read-only / workspace-write / danger-full-access 三级 ×
  suggest / auto-edit / full-auto 审批三级。
- **驱动面三档**:`codex exec`(一次性)、`codex mcp-server`(被别的 agent 当工具调)、
  `codex app-server`(JSON-RPC 全功能;RP-CE 走这条路,220MB 二进制 vendor 进
  `.build/codex-runtime/0.153.4/`)。
- 其他子命令面:`agents`(共享 local app-server daemon 的会话浏览)、`review`、
  `apply`(把 agent 产的 diff 施回工作树)、`cloud`、`remote-control`、`exec-server`。

### 1.2 RepoPrompt-CE:驾驶舱 + 委托拓扑(中间层,时–日尺度)

它**自己不实现 loop**——loop 在 provider 进程里。它拥有的是 loop 外围的一切。
三层结构(MCP 工具面 → Agent Mode Runtime → Provider):

```
MCP 控制层(agent_run / agent_manage,给上层 agent 用)
  └─ Domain Runtime:唯一生命周期 authority(DomainAgentRunSessionStore + 中立 DTO)
       └─ Agent Mode Runtime(per-provider coordinator + 生命周期 tracker + oversight)
            └─ Provider 进程(Claude native / Codex native / ACP: Cursor·OpenCode·Grok)
```

- **唯一生命周期 authority**(关键裁决):`docs/spec/headless-mcp-domain-runtime-m5-ai-agent-interaction.md`
  ——Domain Runtime 拥有 session 生命周期,view model 只是投影;terminal publication
  需要精确 epoch + commit ID(幂等);drain 期间新 waits 与 cancellation-handler installs
  fail-closed。liveness 由 `AgentRunLifecycleTracker` 单调序列保证,拒绝乱序/重复信号,
  心跳不计入 `lastRealProgress`(`AgentRunLifecycleContracts.swift:135-236`)。
- **provider 中立合约**:`NativeAgentRuntimeControlling` 五原语
  (`Sources/RepoPrompt/Features/AgentMode/Runtime/Native/NativeAgentRuntimeContracts.swift`;
  设计文档 `docs/architecture/provider-plugins.md` §Provider-neutral native runtime contract):
  `startOrResume` / `sendUserMessage` / `interruptTurn` / `respondToPermissionRequest` /
  `shutdown`(另有 `applyModelAndEffort`)。Claude-native、Codex-native、ACP 全部收敛到这一组。
- **MCP 控制原语**(probe A 报告,附录 A):`agent_run op=start|poll|wait|cancel|steer|respond`
  + `agent_manage op=list_agents|list_sessions|extract_handoff|create_session|resume_session|
  stop_session|list_workflows`。审批流:provider 发 approval/question/elicitation →
  session 进 waiting 态 → 外部 `respond` + 精确 `interaction_id`;transport 层在每个
  suspension point 重新验证两端 live endpoint 身份,防 replay。
- **session 状态机**:`idle → running → waitingForUser/Question/Approval →
  completed/cancelled/failed`(`AgentChatModels.swift:596-614`);run lifecycle:
  `starting → preparingRuntime → running → waitingForInteraction/retrying/cancelling → terminal`。
- **委托拓扑**:session 树(子 agent 派发)、fork、`extract_handoff`(`<forked_session>` XML,
  transcript + 可选文件内容 + delivery_id)、worktree 绑定
  (`AgentSession.swift:219-223`,`worktreeBindings` + `worktreeMergeOperations` 持久化在
  session JSON;merge 状态机 preview→approval→apply→conflict→commit, reload 后由
  reconciler 校验 preview artifacts)。
- **oversight 四 owner 分离**(`docs/architecture/agent-session-oversight-auto-wake.md:13-24`):
  link authority(授权)/ passive reducer(队列归并)/ claim-receipt(immutable batch)/
  wake coordinator(准入)故意 disjoint;`request_attention` 是 attributed untrusted
  target signal,永不可授权;tombstone(`.cancelledBeforeDispatch`)是 fence 不是记账。
- **编排是提示词不是引擎**:`rp-orchestrate` workflow
  (`Sources/RepoPromptShared/Workflows/WorkflowPrompt+Orchestrate.swift`)本质是
  「plan/decompose/delegate」系统提示 + `agent_run` 工具面——**LLM 即编排器**,
  没有硬编码 pipeline。

### 1.3 LoopX:治理与经济层(最外层,天–周尺度)

定位 "Long-horizon agent control plane for durable, governed work across Codex,
Claude Code, and other harnesses"。不管单次对话,管「goal 活过任何一次执行」。
**六层持久控制面**(`docs/architecture.md`,落地形态全是文件系统):

| 层 | 物理载体 | 内容 |
|---|---|---|
| 1 Registry | `.loopx/registry.json` | goal_id、agents、quota 策略、self_repair、execution_profile |
| 2 Goal State | `ACTIVE_GOAL_STATE.md` | objective、todos、gates、evidence、validation notes |
| 3 Run Log | `.loopx/runs/` JSON+MD | classification、summary、recommended_action、outcome |
| 4 Run History | compact indexes(JSONL) | run_id、turn_key、result_kind、spent_slots |
| 5 Status/Attention | 投影 | agent/user todo summary、quota、interaction_contract |
| 6 Compute Quota | registry policy + slot 事件 | duty-cycle、spent_slots、state |

核心裁决(原文已抽查):

- **Goal ≠ chat thread**(`docs/state-interaction-model.md:24-38`):「A goal is not a chat
  thread. A thread can execute a goal, but the goal must survive thread reloads, network
  interruptions, and multiple project agents.」
- **Executor 是 ephemeral 的,不拥有真相**(同文 :49-67):executor-owned state 仅限
  当前对话上下文、本地工具输出、临时决策;durable state 全部归 goal stores。
- **Quota 只管计算资格,与 reward/审批/写权限分离**(`docs/quota-allocation.md:13-22`):
  「quota means compute quota only. It does not decide human reward, write approval,
  production permission, or operator gate outcomes.」quota=0 是 goal 级硬暂停。
- **Registered agents are peers, no durable leader**(`README.md:126-128`):
  claim(`claimed_by` 软所有权)+ 可选 file-backed 硬租约 + `interaction_contract` 路由
  决定谁行动。
- **turn transaction contract**:`turn_transaction_contract.json` 定义 turn 边界;
  host 返回 `result_kind ∈ {VALIDATED_PROGRESS, VALIDATED_COMPLETION, REPAIR_REQUIRED,
  REPLAN_REQUIRED, USER_ACTION_REQUIRED, WAIT}`,只有 material kinds 触发结算。
- **settlement 三步链**:DURABLE_WRITEBACK → QUOTA_SPEND → TERMINAL_CLOSEOUT;
  「spend exactly once after validated delivery」——扣减发生在 durable writeback 之后,
  不是执行前预扣。TS runtime 拥有 identity/receipt/replay/ordering,Python 只做 callback adapter。
- **adapter 三层深度**(`state-interaction-model.md:476-493`):`in_loop`(harness 可回调
  LoopX API)/ `wrapper`(LoopX 定 turn 边界、harness 执行)/ `passive_posthoc`(只能事后观察)。
- **推进机制**:scheduler heartbeat / manual tick → `quota should-run` 门卫(紧执行前的
  authoritative 判定)→ 五种出口(delivery / user_gate / await_evidence / quiet_noop / repair)。
  `quota plan` 只是 advisory hint。

---

## 2. 三者关系:不是三层楼,是一条控制谱系的三个时间尺度

三者不是竞争的三套设计,而是**同一个控制问题在不同尺度上的三段**,接口单位都是
「有界工作段(bounded work segment)」:

```
LoopX   ── 天/周尺度:goal·资格·门·奖励·结算 ──┐
                                             │ 委托一个 bounded turn
RP-CE   ── 时/日尺度:会话·委托·worktree·上下文 ──┤
                                             │ 驱动一个 provider turn
Codex   ── 秒/分尺度:turn 内循环·审批·沙箱    ──┘
                                             │ 执行一次 tool call
                                          沙箱/进程
```

每层对下层只用四个动词的变体:**观察 / 注入 / 应答 / 取消**
(poll↔snapshot↔status;steer↔interaction_contract↔queue;respond↔approval↔gate;
cancel↔interrupt↔quota=0)。

每一层都独立发现了同一条纪律:**durable state 不归执行者**
(LoopX:executor is ephemeral;RP-CE:Domain Runtime 是唯一 authority;
DSH:durable replay 在 `session/event`、live control 在 `agent/*` 两平面分离——
`deepseek-harness/docs/agent-lifecycle.md`,第四参照,附录 D)。

两个微妙关系:

1. **RP-CE 与 LoopX 方向相反**:两者都想当「跨 harness 控制层」,但 RP-CE 是
   **交互驾驶舱**(人坐中间,多 provider 会话并排,orchestrate 靠 LLM 提示词),
   LoopX 是**自治经济**(goal 坐中间,agent 是同侪短命工人,靠合同与配额驱动)。
2. **Codex 在向上长**:thread goal / queue / fork 这些原语原本属于上层
   (LoopX 的 goal 层、RP-CE 的 steer),底层引擎正在自己吸收——印证这些概念
   是谱系上的公共财产,不是某一家的发明。

---

## 3. pg-agent 怎么「成为一个整体」:五个统一机制

「三套原语」的解药不是设计一个统一接口层,而是**让每个高阶概念成为同一组低阶原语的
投影或约束**。v13 已经回答了一大半:

1. **状态只有一个家(PG)。** Codex 的 rollout 文件、RP-CE 的 session JSON、LoopX 的
   六层文件目录,是同一个东西的不同介质。v13 的「行是唯一真相」统一成表;
   外部 harness 的内部状态降格为**投影缓存**,权威永远在 events/effects。
2. **只有一个推进函数(parse + advance)。** 它同时就是 Codex 的 turn 状态机、
   RP-CE 的 lifecycle tracker、LoopX 的 turn driver——区别只在「谁拨这一格、
   拨之前检查哪条策略」。三个推进来源(settle 唤醒/扫地僧/人工)语义相同(v13 ch05 已裁)。
3. **只有一条干预通道(events INSERT,永不阻塞)。** G-ctx1 保护的「干预面」就是
   Codex 的 steering/queue、RP-CE 的 steer op、LoopX 的 interaction_contract
   要保护的同一件事。水位复核(goal_hash/candidate_set_hash)解决的正是 RP-CE 用
   epoch+单调序列、Codex 用 turnID 回执解决的同一问题:**旧意图不得用于新现场**。
4. **只有一个结算点(settle)。** LoopX settlement 三步链在 v13 里天然存在:
   settle 本身 = DURABLE_WRITEBACK;effect 终态化 + 预算同事务扣减 = QUOTA_SPEND;
   终结事件(completed/failed/cancelled,ch05 练习 1)= TERMINAL_CLOSEOUT。
   LoopX 用整个 settlement 子系统换来的「spend 只在 validated writeback 之后」,
   v13 用「预算检查与工作创建同事务」一句纪律就拿到了。
5. **高层语义全部是数据投影,不是新机器。** RP-CE 最高层的编排干脆是提示词
   (LLM 即编排器,工具面就是那组控制动词);LoopX 的看板/attention queue 明确标注
   「projection, side-effect free」。v13:goal=sessions 行,quota=策略行,
   reward=开放事件,看板=递归 CTE 视图,orchestrate=decisions 表 + 路由视图。
   **没有任何一层控制需要新的执行机制。**(与 v11-dev 附录 A.1、v13 ch13 的
   「拒绝六层控制面表结构」裁决一致。)

### 3.1 概念映射总表(整体性的验证判据)

| 概念 | Codex | RP-CE | LoopX | v13 落点 |
|---|---|---|---|---|
| 有界执行 | turn | run/epoch | bounded turn | effect 四件套 + turn_no/max_turns |
| 干预 | steer/queue | steer op | interaction_contract | events INSERT(G-ctx1) |
| 审批 | approval req | interaction_id respond | user_gate | human effect |
| 压缩 | compactThread | compaction/oracle export | — | transcript chunks 投影 |
| 恢复/分叉 | resume/fork rollout | handoff XML/resume | goal survives threads | 行是真相 + parent_session_id |
| 配额 | — | — | quota slot spend | 策略行,同事务扣减 |
| 目标 | thread goal(新长出) | — | goal 层(六层之首) | sessions 控制行 |
| 委托 | 子 agent(埋在内部) | session 树 + worktree | todos/handoff | 子会话 + 类型化事件 |
| 结算 | turn end | terminal publication(epoch+commit 幂等) | writeback→spend→closeout | settle + 终结事件 |
| 编排 | — | orchestrate 提示词工作流 | — | decisions + v_routes |

---

## 4. 外部 harness 的定位:wrapper 深度

最容易做错的一步是把 Codex 当平等的控制面接进来(那就真的是三套原语了)。
用 LoopX 的 adapter 三档裁决:pg-agent 以 **wrapper** 为主档——**bounded turn 的边界
握在 v13 手里,harness 只是一个 tool effect 的 handler**(`handler='codex'` /
`'claude-code'`,v13 ch13 已裁「executor = handler worker」)。

此时 RP-CE 五原语恰好就是 wrapper 档所需的全部驱动面:

| NativeAgentRuntimeControlling 原语 | v13 对应 |
|---|---|
| `startOrResume` | 建 effect(handler 参数 + lease) |
| `sendUserMessage` / `steerUserTurn` | append_event(干预通道) |
| `interruptTurn` | cancel 事件(同一条通道) |
| `respondToPermissionRequest` | human effect 应答 |
| `shutdown` | 租约回收 / fence |

**五原语没有一个是 v13 缺的机制**——它们是 effects/events/human 平面上已有的五个
动词换个名字。这就是「一个整体」的可验证判据:驱动一个外部 harness 不需要任何
新表、新循环、新状态机。

---

## 5. 缺口清单(是字段与事件形状,不是机器)

1. **handoff 内容协议**:RP-CE 的 `<forked_session>` XML(transcript + file contents +
   delivery_id)说明「交接物」需要结构化形状;v13 有 `parent_session_id` 缝但没定
   handoff 事件的信封。
2. **goal 树递归视图** `v_goal_tree`:v13 ch13 练习 1 的位置,LoopX attention
   queue/看板的对应物。
3. **closeout 事件族**:completed/failed/cancelled 终结事件形状(ch05 练习 1),
   LoopX closeout 段的对应物。
4. **worktree 隔离纪律**:RP-CE 把「每个 agent 会话绑一个 worktree」做成控制面一等公民;
   v6.1 的 sitting_duck 工作台在 duck 侧解决了类似问题,但 v13 的 `handler='claude-code'`
   worker 跑在文件系统上时的隔离归属还没裁。
5. **steer 的会话语义**:DSH 用 inbox claim + waterfall 让 steering 走和正常输入完全
   同一条路;v13 的 events 天然如此(steer 就是一条 message 事件),「turn 进行中注入的
   事件何时被消费」= 水位复核已覆盖,只需在 gate 里加断言。

**反面警示**(什么时候会碎成三套原语):
- 给外部 harness 开 in_loop 回调深度并让它写自己的状态 → 第二个真相源;
- 把 quota 做成独立服务而不是策略行 → 第二套调度面(v11 已拒);
- 把 orchestrate 写成 Python pipeline 而不是 decisions+路由 → 第三个循环。
三者都已经替我们踩过这些坑并写在文档里。

---

## 6. 与既有裁决的关系

- `docs/designs/v11-dev.md` 附录 A.1:loopx 行「采纳 run-bound reward overlay /
  quota 持久门控,拒绝六层控制面表结构」——本文 §3.5 与之一致,且补齐了
  RP-CE/Codex 两个新参照的互证。
- `docs/designs/v13-context-on-pg.md` §4.3(两阶段 advance)/§6.2 触点 6/§8 pg_cron:
  本文 §3.2/§3.3 直接引用。
- `docs/tutorials/v13/chapters/13-long-running-goals.md` 映射表「2 列 + 2 纪律」:
  本文 §5 缺口 1–3 是该映射表的收尾工件细化,不推翻任何一行。
- `repoprompt-native-on-v13-feasibility-v2-2026-09-21.md`:姊妹篇(文件面);
  本文的控制面结论不与 I-file-1…7 冲突,wrapper 深度裁决与「FS IO 全 effect」一致。

---

## 7. 证据等级(诚实声明)

| 来源 | 等级 | 说明 |
|---|---|---|
| RP-CE probe A 报告(附录 A) | 源码级 | 文件路径+行号引用;`NativeAgentRuntimeControlling` 协议与 provider-plugins.md 已由主会话逐行复核 |
| LoopX probe B 报告(附录 B) | 源码级 | 六层/裁决/settlement 带路径;quota-allocation.md 与 state-interaction-model.md 关键原文已由主会话抽查 |
| Codex probe C 报告(附录 C) | **推断级** | probe 自述「基于仓库文档结构与公开文档路径推断」;主会话已用 vendored codex 0.153.4 二进制 `--help` 补验子命令面(§1.1),并从 RP-CE `CodexNativeSessionController` 协议反推驱动面——但 codex-rs 内部实现(rollout 文件格式、compaction 细节、app-server JSON-RPC 方法全名)未经源码级验证,引用时注意 |
| DSH agent-lifecycle | 文档级 | 本地 checkout `deepseek-harness/docs/agent-lifecycle.md`,mermaid 时序图原文 |
| 综合分析(§2–§5) | 设计判断 | 映射表每行的 v13 落点均锚定 v13 已有章节,无新增机制主张 |

---

## 附录 A:RP-CE 控制面 probe 报告全文(probe-A,haiku,源码级)

### (a) 控制原语清单

| 原语 | 所在 | 语义 |
|---|---|---|
| `agent_run op=start` | `AgentRunMCPToolService.executeStart` L401 | 创建新 session 并启动 provider 进程;总是新 session,不支持指定已有 session_id |
| `agent_run op=poll` | `executeWait` L386 (forcePoll=true) | 非阻塞读取当前 snapshot;timeout=0 等价 |
| `agent_run op=wait` | `executeWait` L389 | 阻塞等待直到 run 进入可操作状态;支持多 session 竞速 `session_ids` |
| `agent_run op=cancel` | `executeCancel` L1051 | 取消活跃 run;对 startup-pending 的 follow-up run 同样有效 |
| `agent_run op=steer` | `executeSteer` L1095 | 向活跃/非活跃 run 注入后续指令;非活跃时创建新 epoch 而不替换 session activation |
| `agent_run op=respond` | `executeRespond` L1374 | 响应 pending interaction(approval/question/elicitation),需精确 `interaction_id` |
| `agent_manage op=list_agents` | `executeListAgents` L208 | 列出 provider 及 task_labels(explore/engineer/pair/design) |
| `agent_manage op=list_sessions` | `executeListSessions` L302 | 列出全部 agent session(live + persisted) |
| `agent_manage op=extract_handoff` | `executeExtractHandoff` L555 | 导出 `<forked_session>` XML(transcript + 可选 file contents) |
| `agent_manage op=create_session` | L593 | 创建空白 session(默认 engineer role) |
| `agent_manage op=resume_session` | L196 | 恢复已有 session |
| `agent_manage op=stop_session` | L200 | 停止 live session |
| `agent_manage op=list_workflows` | L198 | 列出 built-in + custom workflow 定义 |

Interaction 审批流:provider 发 approval/question/elicitation → session 进
`waitingForApproval`/`waitingForQuestion`(`AgentSessionRunState` L596-614)→
外部 respond + interaction_id(`AgentModeViewModel+Types.swift` L81-87
`RunInteractionStateChangeReason`)。Transport 层在每个 suspension point 重新验证
两端 live endpoint 身份,防 replay。

### (b) Session 状态机

Run lifecycle(`AgentRunLifecycleContracts.swift` L73-80):
`starting → preparingRuntime → running →(waitingForInteraction | retrying | cancelling)→ terminal`

AgentSessionRunState(`AgentChatModels.swift` L596-614):
`idle → running → waitingForUser/Question/Approval → completed/cancelled/failed`;
isActive = running + 三种 waiting。Auto-wake 内嵌状态机
(`agent-session-oversight-auto-wake.md` L481-513):`.preparingDispatch` /
`.cancelledBeforeDispatch`(tombstone fence)/ `.dispatching`。

### (c) 分层结构

```
MCP Control Plane (RepoPromptMCP + Infrastructure/MCP/Agent/)
  - agent_run/agent_manage 工具定义、会话路由、授权、wait scope 管理
        │ NativeAgentRuntimeControlling
Agent Mode Runtime (Features/AgentMode/)
  - AgentModeViewModel(协调器)、AgentTabSession、
    CodexAgentModeCoordinator/ClaudeAgentModeCoordinator、
    AgentRunLifecycleTracker、DomainAgentSessionLinkAuthority
        │ HeadlessAgentProvider / Native
Provider Layer
  - ClaudeNativeProcessSessionController、CodexSessionControlling(codex CLI)、
    ACP(OpenCode/Cursor/Grok/Antigravity)、RepoPromptClaudeCompatibleProvider
```

Domain Runtime(`RepoPromptDomainRuntime/`)位于 MCP 与 Agent Mode 之间,拥有生命周期
authority(`DomainAgentRunSessionStore`、`DomainInteractionBroker`);
`AgentModeViewModel` 是投影/编排层,不拥有生命周期(M5 文档 L11)。

### (d) 关键设计裁决(15 条,摘)

1. provider 插件 seam 是静态 SwiftPM 组合,非动态加载(`docs/architecture/provider-plugins.md` L15)。
2. provider-neutral 原生运行时合约五原语(同文 L186-213)。
3. oversight 四 owner 分离(link authority / passive reducer / claim-receipt / wake coordinator
   故意 disjoint,`agent-session-oversight-auto-wake.md` L13-24)。
4. target-derived content 永不可授权(`request_attention` 是 attributed untrusted target signal,同文 L54-58)。
5. auto-wake tombstone 是 fence 不是 bookkeeping(同文 L481-513)。
6. task label 路由到 provider+model 候选链(`AgentModelCatalog.swift` L1760-1849;
   start 默认 `.pair`,`AgentRunMCPToolService.swift` L283)。
7. 多 provider 按 runtime kind 分流(`AgentRuntimeProviderService.swift` L232-331;
   `claude_native`/`codex_native`/`*_acp`)。
8. worktree 绑定持久化在 session JSON,merge 操作独立状态机(`AgentSession.swift` L219-223;
   `AgentSessionWorktreeMergeOperation.swift` L9-17;reload 后 reconciler 校验)。
9. handoff/fork 双通道:`<forked_session>` XML + `pendingHandoffPayload` 在目标 tab
   首次 user send 时注入(`AgentManageMCPToolService.swift` L555-562;
   `AgentModeViewModel.swift` L17943-17944)。
10. codex 内嵌为 `.build/codex-runtime`,支持 `/compact`、`/goal`、`/computer-use`
    native slash commands(`CodexAgentModeCoordinator.swift` L40-64)。
11. liveness 由单调序列保证(`AgentRunLifecycleContracts.swift` L135-236)。
12. M5:Domain Runtime 是唯一生命周期 authority;terminal publication 精确 epoch+commit;
    drain 期间 fail-closed(`docs/spec/headless-mcp-domain-runtime-m5-ai-agent-interaction.md` L11-28)。

---

## 附录 B:LoopX probe 报告全文(probe-B,haiku,源码级)

### (a) 控制原语清单

| # | 原语 | 定义 |
|---|---|---|
| 1 | Goal | durable 工作对象,跨线程/agent/harness 失效不丢失;拥有 objective、active state、authority sources、gates、todos、quota、run history |
| 2 | Turn | 一次 bounded 执行单元:quota should-run 判定 → 选 todo → host 执行 → 验证 → durable writeback → quota spend,全链路 typed contract |
| 3 | quota should-run | 每次心跳/手动的门卫原语;返回 interaction_contract,枚举 should_run/user_gate/wait/repair/quiet_noop |
| 4 | interaction_contract | 机器可读执行合同;含 agent_channel.primary_action + cli_channel.next_cli_actions,executor 只按合同行动 |
| 5 | Todo | 最小可执行或等待单元;task_class(advancement_task/continuous_monitor/user_gate/user_action)、claimed_by、required_capabilities、required_write_scopes |
| 6 | Claim / Task Lease | 软所有权(claimed_by)+ 可选硬租约(file-backed);非排他锁,允许更好证据或 gate 优先 |
| 7 | Gate | typed 阻断:user_gate(lane-scoped/global)、operator_gate、capability_gate、boundary_projection_repair |
| 8 | Quota slot | duty-cycle(0.0–1.0);每 slot=1 分钟自动计算预算;spend 仅在 validated writeback 后一次 |
| 9 | Human Reward Overlay | run 级可选 human_reward 附件(实验性,reward_memory.py);绑定特定 run,非模型内部 belief |
| 10 | Scheduler Hint | harness 心跳调度提示:RRULE/interval/backoff/monitor wait phase(scheduler_hint.py) |
| 11 | Handoff | 跨 agent 交接通过 todo lifecycle 表达(unblocks_todo_id、superseded_by、resume_when),不是隐藏 chat memory |
| 12 | Settlement | turn 结束 effect 链:DURABLE_WRITEBACK → QUOTA_SPEND → TERMINAL_CLOSEOUT;TS runtime 拥有 identity/receipt/ordering,Python 只做 callback adapter |
| 13 | Capability Gate | per-todo 执行前检查(required_capabilities vs host 实际能力);缺能力 → repair_bridge/ask_owner/skip |
| 14 | Self-Repair | 可选 per-goal 策略,允许 agent 在 stalled 时花一轮修复 LoopX health blocker |

### (b) 六层控制面实际形态

见 §1.3 表。Goal-owned state 完整清单(state-interaction-model.md):
project-local registry entry / active goal state file / compact run index /
private run payloads / optional human_reward overlays / optional compute quota + spend ledger。

### (c) 分层结构图

```
HUMAN / OPERATOR(boundary decisions·reward·approval·deferral·credentials)
        │ gate / reward / priority
LOOPX CONTROL PLANE(六层持久状态 + effect interpreter)
  子域:goals/ todos/ agents/ quota/ scheduler/ turn_driver/ handoff/ work_items/ coordination/
        │ TurnEnvelope / interaction_contract(typed JSON)
EXECUTOR HARNESS LAYER(registered agents are peers, no leader)
  SUPPORTED_HOSTS = {codex-cli, claude-code, dsh, generic-cli} + codex-app/kunluncode/opencode/pi/zcode/agy…
  adapter 三档:visible TUI / isolated-headless subprocess / in_loop(API·tool call)
  executor-owned state 仅内存:当前对话上下文、本地工具输出、临时决策
        │ subprocess / tool call / API
BOTTOM PROCESS(Codex CLI / Claude Code / …,LoopX 不可见其内部 loop)
  返回 stdout JSON(符合 HOST_RESULT_FIELDS 约束)
```

关键边界:LoopX 只管 durable state(文件/JSONL);executor 只管 ephemeral context;
两者通过 TurnEnvelope(入)+ LoopXTurnResult(出)两个 typed JSON contract 交互。

### (d) 关键设计裁决(15 条,摘)

1. 六层而非更多层;probe surface 明确「not a seventh layer」(architecture.md L1-13)。
2. Goal ≠ Chat Thread(state-interaction-model.md L24-38)。
3. Executor 是 ephemeral,不是 durable truth(同文 L49-67)。
4. Quota 与 Reward 分离(quota-allocation.md L13-17)。
5. Quota 是 compute-only,不是权限系统(同文 L14-22)。
6. Quota=0 = goal 级硬暂停(区别于单 agent 的 monitor_only)(同文 L34-46)。
7. Registered Agents Are Peers, No Durable Leader(README.md L126-128)。
8. Adapter 三层深度 in_loop/wrapper/passive_posthoc(state-interaction-model.md L476-493);
   不变式:LoopX 在 agent loop 外围生产/验证控制面上下文,无论 loop 是否原生配合。
9. 推进 = scheduler heartbeat/manual tick → quota should-run(quota plan 只是 advisory)
   (同文 L246-270;quota-allocation.md L237-276)。
10. bounded turn 由 turn_transaction_contract.json 界定;result_kind 六值,只有 material
    kinds 触发 writeback+spend(turn_driver/driver.py L28-42;executor.py L77-101)。
11. governance 三层:hard gates(人类/控制器显式决策)/ capability gates(机器可判定)/
    human reward(run-bound overlay)(同文 L152-214;operator_gate.py)。
12. LoopX vs harness 状态边界(actor boundaries 表,同文 L206-214;architecture.md L121-148):
    LoopX 管 durable facts/event ledger/active-state projection/authority/quota/gates/restartability;
    agent 管 belief synthesis/action selection/bounded implementation/validation choice;
    human 管 reward/approval/private material/production decisions。
    中断/steer/cancel 经 interaction_contract 传导。
13. effect interpreter 架构:六层共同解释每轮 loop 的一个 effect request
    (model → effect request → harness interprets → observation → model)(architecture.md L46-68)。
14. settlement 双 runtime 分治(settlement_driver.py L1-7)。
15. writeback 后才 spend(state-interaction-model.md L360-365;quota-allocation.md L107-117)。

---

## 附录 C:Codex probe 报告全文(probe-C,haiku,推断级——见 §7)

### (a) 控制原语清单

| 原语 | 说明 |
|---|---|
| turn 启动 | 用户消息注入,loop 取下一轮模型 completion |
| turn 终止 | finish_reason=stop 或 max_turns |
| tool_call 审批 | 沙箱拦截后向用户/驱动者发审批请求,阻塞 loop |
| steering 消息 | turn 进行中插入新消息,改变当前轮行为 |
| cancel | 中断模型 streaming 与工具执行 |
| session 持久化 | 每轮 rollout 写入会话文件,支持 resume/fork |
| compaction | 上下文超限时摘要压缩,保留会话连续性 |
| fork | 从已有 rollout 派生新 session |
| 沙箱策略切换 | read-only / workspace-write / danger-full-access |
| approval mode | suggest / auto-edit / full-auto |
| exec 非交互模式 | 单次任务 |
| MCP server 模式 | codex mcp 暴露为 MCP server |
| app-server / codex-proto | 本地 socket + JSON-RPC/proto 程序化控制 |

### (b) 分层结构

```
驱动接口层(exec / mcp / app-server JSON-RPC/proto)
会话管理层(rollout / resume / fork / compaction / AGENTS.md 注入)
主循环层(user msg → model → tool_call → sandbox check → execute → 回环)
沙箱/审批层(exec policy / approval mode / tool permission)
```

### (c) 暴露 vs 埋点

对外:`codex exec`(启动/终止 turn)、`codex mcp`(外部 agent 经 MCP 发起 turn)、
`app-server`(turn 开始/结束事件流、审批请求事件回调)、审批请求事件推送。
对内:turn 内 tool_call 路由与顺序、sandbox 策略解析、compaction 触发时机、
AGENTS.md 扫描时机、streaming 中断与 resume、审批默认值继承链
(config.toml → requirements.toml → 运行时)。

### (d) 来源

- <https://github.com/openai/codex>(Rust,docs/ 目录 15 个文件)
- developers.openai.com/codex/security、/exec-policy、/exec、/config-basic
  (均 308 重定向至 learn.chatgpt.com 对应页)
- 仓库内 docs/agents_md.md、docs/exec.md、docs/execpolicy.md、docs/sandbox.md、
  docs/config.md 均为外链重定向页
- probe 自述局限:实际内容需抓取 learn.chatgpt.com 系列页面验证

**主会话补验**(2026-09-21,vendored 二进制实测):子命令面含 `agents`(共享
app-server daemon 会话浏览)、`exec`、`review`、`mcp-server`、`app-server`、
`remote-control`、`app`、`sandbox`、`apply`(diff 施回工作树)、`resume`、
`queue`(给运行中会话排队消息)、`fork`、`cloud`、`exec-server`。
RP-CE 驱动协议(`Sources/RepoPrompt/Infrastructure/AI/Providers/Codex/AppServer/
CodexNativeSessionController.swift:129-189`)另暴露:startOrResume×3 形态、
readThreadSnapshot、startUserTurn、steerUserTurn、interruptUserTurn(expectedTurnID)、
reconcileAndInterruptCurrentTurn、compactThread、getThreadGoal/setThreadGoalObjective/
setThreadGoalStatus/clearThreadGoal、pendingTurnFailure/acknowledgePendingTurnFailure、
cancelCurrentTurn、cleanupConversation、shutdown、respondToServerRequest、
setThreadName、listHooksForCurrentWorkspace/trustHooksForCurrentWorkspace。

---

## 附录 D:第四参照 DSH(主会话直接调查,文档级)

`deepseek-harness/docs/agent-lifecycle.md`(DeepSeek 官方开源 harness,Cordis
everything-is-a-plugin 架构,「the agent loop itself is a plugin」):

- **两平面分离**:durable replay 住在 `session/event`,live control/status 住在
  `agent/*`——「SDK users that need replayable transcript data should consume
  session/event; agent/* is the live coordination API for queue/status, prompt
  interception, request construction, steering, continuation, and errors.」
- **turn/step 两级生命周期**:turn/start → step/start →(prepare → reconcile →
  derive/freeze request → stream → tools with barriers + bounded rolling pool)→
  step/end → claim pending next-step input → turn/end。
- **inbox + claim**:用户 followup 落 inbox(spliced/inserted 事件),driver claim
  (inbox/claimed 事件,带 turn 号)——steering 与注入上下文走同一 waterfall。
- **pre-step 权威裁决**:hooks waterfall 可 authoritative reject;拒绝时 claimed batch
  保持移除、open turn 不花 step。
- **失败记录**:失败/重试/取消的 attempt 若无 surface message,以 `assistant/attempt`
  落账;成功调用总是 `assistant/message`(含 content-less 与 max-tokens 结束)。
- **与 v13 的同构**:「durable 行 + live 投影」=「events 表 + 视图」;inbox claim =
  events INSERT + 水位复核;pre-step reject = reject 路由。

---

*调查执行:主会话(Opus 4.8 1M)+ probe-A/B/C(haiku:max,agent_run detach)。
方法:本地 checkout 源码调查(RP-CE `~/Projects/repoprompt-ce`、LoopX `~/Projects/loopx`、
DSH `~/Projects/deepseek-harness`)+ vendored codex 0.153.4 二进制实测 + web。
主会话抽查记录:provider-plugins.md §Provider-neutral contract(逐行)、
quota-allocation.md L1-30、state-interaction-model.md L20-45、codex --help、
CodexNativeSessionController.swift L129-189、WorkflowPrompt+Orchestrate.swift L1-80。*
