# v20 三层实现参考（2026-10-13）

定位：本文档是 `docs/designs/v20-runtime-charter-draft-2026-10-12.md`（下称「草案」）的细化参考。它不替换草案，不是开发合同，不修改草案本文，不含代码实现。名词沿用草案（Control.execute、WorkerRequest/TurnReceipt、disposition、Kernel、Host、Tool Gateway、artifact、fence、CAS、admission、PlanProposal/PlanRevision、workflow frontier 等）。

核实声明：撰写前重新打开并通读了草案第 3、4、9 节；抽查了以下来源并在文中标为「已核对」：

- `v13/loop_driver/driver.py:441` 起 `run_turn`（可选 override、terminal/stop 短路、一次入口 advance、有界 serve、decide/take_exit）；同文件 `:27` 出口词五词闭集、`:315` serve、`:423` take_exit、`:468` settle_once、`:555` run_controller_once、`:573` SQL advance 四词闭集（waiting/terminal/stale/progressed）。
- `v13/plan_arm/v13_plan_arm.sql:332` 为 `CREATE OR REPLACE FUNCTION public.v13_advance`；同文件 `:355` 会话行锁、`:360-367` 七键 stale 判定、`:771` 起 sql/tool/llm/human/finish/reject 路由。
- `v13/load.py:34` control（stage 17）、`:49` plan_arm（stage 32），后装载的 CREATE OR REPLACE 覆盖先前的 `v13_advance`。
- `repoprompt-ce/Sources/RepoPromptShared/Workflows/WorkflowPrompt+Orchestrate.swift:1-80`：`rp-orchestrate` 是拼出来的 prompt 字符串（frontmatter + Phase 段落），不是状态机。
- `repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Models/AgentWorkflow.swift:122`：`AgentWorkflowDefinition` struct，`:141` 带运行时 template（注释标明 runtime-only、不持久化）。早前调查报告写的 220 行是错的。
- Warp 工厂文档存在：`https://docs.warp.dev/factories/how-factories-work/`。
- MASS 仓库（本地 `/Users/wxl/Projects/mass`，remote `https://github.com/SakanaAI/mass.git`）：README 称 RHI 阶段在权重固定时搜索多 agent workflow、后训练才用轨迹更新权重；README 只链接 `https://arxiv.org/abs/2610.12176`。RHI 论文摘要已核对：`https://arxiv.org/abs/2607.15524`，harness 写成 prompt 级规格，用成对反馈迭代，评测细则不直接交给优化器。仓库正文没有这个编号。
- MASS `harness_improvement/iterate_multi_agent_prompt.py:35-36`：design block 的两个 marker。同文件约 `:2189-2190`：仲裁 winner 为 B 时，冠军才换成当前版本；约 `:2196-2200`：evaluate-only 路径写出 `retained_workflow.json`，没赢基线时 `beats_reference` 为假。
- MASS `mass/pipeline.py:112-130`：搜索调用该脚本，`--judge-vs-baseline` 对照 `reference`，最后一轮 `--evaluate-only`，模型为当前 `model_id`，后端 local-vllm；`:141-143`：`beats_reference` 为假的任务不进 collect。
- MASS `runtime/run_episode.sh:5-13`：qwen-code 的采样、窗口、超时、yolo、stream-json 与原 episode 字节级一致。

除上述位置外，本文引用的 v13、RepoPrompt-CE 细节均来自既有调查报告，未逐行复核；网络检索类来源除 Warp 工厂页和 RHI 论文摘要外未逐条打开。第 6 节汇总未核实清单。

---

## 1. 与草案的关系，以及本文档解决的问题

草案第 1、2 节已经把原则写死：PostgreSQL 是 durable control truth，Kernel 是唯一 durable mutation owner，三层不是三个 scheduler，外部 IO 不进事务，v20 不做 v13 stage 45 也不 runtime import v13。本文档不复述也不改动这些原则，只回答三个草案还没落到代码层面的问题：

1. **第一层（微观 loop）**：v13 的问题不是机制不够，而是同一事实被逐步叠加出多个推进者和多份事实。草案 3.1 的一次 turn 流水线，需要明确「唯一事实是什么、哪些 v13 写者必须收掉」。
2. **第二层（中观 workflow）**：RepoPrompt-CE 已经有一套在运行的会话/run 控制面，但推进依赖 provider 流。v20 要把其中已经本地化的对象收进 Control，使 workflow 与 loop 合成一个原生控制面，而不是在 loop 之外再跑一个由 prompt 驱动的编排器。
3. **第三层（宏观方向）**：草案第 9 节已有 Macro Planner / Advisor 和 PlanProposal，但还缺三类外部借鉴能补上的状态与门：长程编排的耐久记忆、Warp 式软件工厂的持久作业单与工序图、递归自我改进对运行时本身的最低约束。

v13 逐步叠加造成的控制权分裂（调查报告，除注明外未逐行复核）：

1. driver 进程内计数和出口词，与已提交的 SQL advance 不是同一个事实；`take_exit` 在 provider 出口还会再 advance 一次并丢掉结果词（已核对，`driver.py:429-434`）。
2. plan_contract 用 apply_id 写 plan/todo，effect 用 idempotency_key；计划推进和 turn 推进是两份事实（调查报告，未逐行复核）。
3. agentctl steer/answer 跨会话写事件，或自己 claim 再调 `v13_complete`，target loop 看不到同一事务里的收据（调查报告，未逐行复核）。
4. goal stop/resume、harness_settle、recover_idle、supervisor tick 各自再推进或扫库（调查报告，未逐行复核）。
5. effects 租约至少有 fanout claim、fair_claim、driver 内联 claim、workspace opener、agentctl answer 五个写者（driver 内联 claim 已核对，`driver.py:360-371`；其余四个未逐行复核）。
6. 出口词表分裂：driver 五词（已核对，`driver.py:27`）、SQL advance 四词（已核对，`driver.py:573`）、controller 六词与 supervisor 自己的 word（调查报告，未逐行复核）。

入口旁路：调查称没找到 `LoopDriver.run_turn` 的生产调用者；`RealChain._run` 直接 `serve`，`GoalSupervisor.tick` 直接 `settle_once`（调查报告，未逐行复核；`settle_once` 本体已核对，`driver.py:468-552`）。

---

## 2. 第一层：agent loop 怎么扎实实现

### 2.1 一次 turn 的唯一事实

对照草案 3.1 的 `admit turn → build WorkerRequest → DB-free Worker execution → bounded tool calls → validate TurnReceipt → commit receipt/state → pure disposition`：

**一次 turn 在数据库里只有一类已提交事实：Control 的一次推进（admission）加上一次回执提交（receipt commit）。** v13 已经把这个形状做出来了，可以作为 v20 的正面参照（均已核对）：

- 推进：`v13_advance` 在会话行锁内做七键 stale 判定（session_version、max_event_seq、goal_hash、route_policy_name、route_policy_version、tools_revision、candidate_generation_revision），stale 直接返回不推进（`v13_plan_arm.sql:355-369`）；随后在同一路径里路由 sql/tool/llm/human/finish/reject（`:771-868`）。返回词闭集为 waiting/terminal/stale/progressed 四词（`driver.py:573`）。
- 回执：serve 把外部 IO 放在无事务处执行，随后在同一个已提交事务里完成 scoped claim（对即将完成的那条 effect 的带条件 UPDATE）+ `v13_complete` + settlement advance（`driver.py:315-385`）。
- turn 编排：`run_turn` 只有一次入口 advance、有界 serve 循环、一次 exit 判定（`driver.py:441-466`）。

v20 应保留的 v13 机制名（调查汇总；除上一段注明处外未逐行复核）：三表（sessions/events/effects）、七键 stale、单一 advance、scoped claim + fence + complete、事务外 IO、harness 键闭集与校验、wake 满足判定、origin_user_seq、只读折叠（goal lifecycle、should_run、scheduler hint、plan gate、agentctl observe、macro suggestion、ce_map）、纯 receipt 校验。 durable 表另有 decisions、v13_policies（调查报告，未逐行复核）。

### 2.2 必须收掉的第二写者

针对第 1 节的六条分裂，v20 的收法（不写代码，只写归属）：

1. **进程内计数与出口词不是事实。** disposition 必须由纯函数从已提交 snapshot 算出（草案 3.1 的 `Snapshot → Disposition`）；Host 不得在进程内另存一份「推进到哪儿了」。`take_exit` 式「判完再补一次推进并丢结果词」的形态（已核对，`driver.py:429-434`）在 v20 中不存在：exit 判定只读，推进只属于 Control。
2. **计划写入与 turn 推进共用一份幂等事实。** 草案 4.2 已把 operation idempotency 固定在 Kernel；计划写入（plan_*）必须走同一个 `Control.execute`，与 turn 的 request_id 共享同一幂等收据，不再出现 apply_id 与 idempotency_key 两套键（v13 分裂为调查报告，未逐行复核）。
3. **跨会话 steer/respond 必须经 Control admission。** 目标 run 的下一个已提交事务必须能看到同一张收据；不允许 SECURITY DEFINER 跨会话动词绕过目标 run 的 admission（调查报告，未逐行复核）。
4. **stop/resume、settle、recover 归并为只读折叠 + Control。** goal lifecycle、should_run、scheduler hint 保持只读投影；任何「再推一把」都回到 `Control.execute`。recover_idle 式全库扫描不进 v20（调查报告，未逐行复核）；恢复逻辑走草案 4.2 的 orphan recovery 单点。
5. **effect/tool invocation 的租约只有一个写者。** scoped claim + fence + complete 收敛到 Control 内部一处（草案 4.2 的 tool admission + owner generation/fence）；fanout claim、fair_claim、workspace opener、agentctl answer 这些平行写者（调查报告，未逐行复核）在 v20 中不存在。
6. **出口词一套闭集。** SQL 返回词、Host 出口词、controller disposition 共用草案 3.1 的五词（run_now/wait/needs_input/stop/failed），不允许第二层、第三层各自造词。

必须拒绝继续叠加的形态（调查汇总，未逐行复核）：多领取入口、多推进者、多套出口词、跨 stage 反复 `CREATE OR REPLACE v13_advance`（已核对装载顺序：`load.py:34` control stage 17、`load.py:49` plan_arm stage 32，后者覆盖前者）、计划写者与 turn 推进并行、SECURITY DEFINER 跨会话动词、recover_idle 扫描、driver 预写判断、Python 里的 t0 副本。

### 2.3 建议补进草案的句子（第一层）

对照草案 3.1 与第 4 节，建议补（完整修订清单见第 5 节）：

- 3.1 补：一次 turn 的 durable 事实只有一次 Control 推进加一次 receipt 提交；Host 进程内的任何计数、出口词、预写判断都不构成事实，重启后必须能从已提交 snapshot 完整重建。
- 4.1 补：`Control.execute` 的返回词与 disposition 使用同一闭集；内部操作（admit_turn、accept_turn_receipt 等）与外部操作共享同一幂等收据空间。
- 4.2 补：receipt validation 是纯函数；它只决定 receipt 是否可提交，不触发任何第二次推进。

---

## 3. 第二层：workflow 怎么和 loop 一体

### 3.1 CE 现状

- CE 的 workflow 本体是 prompt 模板：`WorkflowPrompt+Orchestrate.swift` 开头就是拼出来的 prompt 字符串（frontmatter + Phase 0/1 段落），`rp-orchestrate` 不是状态机（已核对，`:1-80`）。`AgentWorkflowDefinition` 在 `AgentWorkflow.swift:122`，带运行时 template（`:141`，runtime-only、不持久化）（已核对）。
- 控制对象是会话与 run：`AgentSession.parentSessionID`、`AgentRunOwnership`、turn epoch；子 agent 由父模型调 `agent_run start` 创建，解析不到父会话会拒绝；推进者是 provider 流到 terminal commit barrier，再发布到 session store；父会话用 wait 挂起；状态在内存 actor + 文件级 durable metadata（CAS revision）+ 会话 JSON（调查报告，未逐行复核）。
- 必须等 provider 的：turn 推进、orchestrate 的拆解与派发、子结果回收、oracle/context_builder、跨会话 steer（调查报告，未逐行复核）。
- 已经本地的：epoch/generation/registration、wait cursor、terminal 幂等、oracle artifact 的 sha256 + revision CAS、父子关系；plan 导出只是磁盘 markdown，不是结构化 artifact（调查报告，未逐行复核）。

### 3.2 收进 Control 的，与留在 provider 侧的

CE 对象到 v20 的映射（左侧来源除 3.1 已核对处外均为调查报告，未逐行复核）：

| CE 对象/动词 | v20 归属 |
|---|---|
| AgentRun ownership、epoch/generation/registration | Kernel 的 owner generation/fence、revision CAS（草案 4.2） |
| `agent_run` start/wait/poll/steer/cancel | `Control.execute` 公共操作闭集（草案 4.1 已有 start/poll/wait/steer/cancel/spawn/handoff） |
| parentSessionID 父子关系 | `v20_workflow_runs` 父子引用（草案 4.3） |
| terminal commit barrier | accept_turn_receipt 的提交点（草案 4.1 内部操作） |
| oracle artifact 的 sha256 + revision CAS | `v20_artifacts` 内容寻址引用（草案 4.3） |
| census 投影、wait/wake | 只读投影 + 草案 8.2 的 wait/notify |
| lease/fence | 可进内核（草案 4.2）；投递抑制策略留在产品层 |
| workflow 提示词、角色目录、model routing、provider 适配器、UI、权限与 slash skills、WorkspaceContext 的选择与导出 | 留在 CE / 插件侧：workflow 提示词对应草案 3.2 的 WorkflowPolicyPlugin 输入；WorkspaceContext 按草案 5.3 作为 Context Plugin + Read/Mutation Tool |

「可收成 loop 之上的 step/handoff/child」即上表前六行：ownership、epoch CAS、start/wait/poll/steer/cancel、terminal commit、父子关系、census 投影、oracle artifact store、wait/wake。

### 3.3 关键变化：workflow 推进不再等另一个 provider

现状里 turn 推进、orchestrate 拆解、子结果回收都要等 provider 流到位（调查报告，未逐行复核）。v20 的对应形态：

- workflow step 的推进 = Control 读已提交事实 + 纯 WorkflowPolicyPlugin 决策。模型仍然只负责产生建议——草案 3.2 的 decision JSON（`workflow_id`、`workflow_revision`、`decision`、`actions[]`）就是建议的唯一形态；dispatch 由 Control 按 admitted plan 执行，不依赖任何 provider 在场。
- 父 workflow 等子结果不是同步阻塞在另一个模型上：wait 是 durable signal（子 run 的 terminal 提交产生事件，父 run 由 wait/notify 唤醒后重读 snapshot），丢通知也能靠 bounded poll 收敛（草案 8.2）。
- workflow 模板（提示词、角色目录）仍是插件输入，但「执行到哪一步、下一步是什么」是 `v20_workflow_steps` 的已提交状态，不再是 prompt 上下文里的隐含约定。

建议补进草案的句子（第二层）：

- 3.2 补：workflow 实例的当前步骤、父子关系和 terminal 状态是 Kernel durable 状态（`v20_workflow_runs/steps`），WorkflowPolicyPlugin 的纯计划只描述「下一步建议」，不携带推进权。
- 4.1 补：start/wait/poll/steer/cancel/spawn/handoff 对 loop run 与 workflow run 是同一组动词；workflow 不获得第二组控制动词。

---

## 4. 第三层：草案第 9 节还缺的状态与门

本节全部是外部借鉴，用来补草案第 9 节，不是再造一个内核。网络检索类来源除 Warp 工厂页外未逐条打开；论文未逐篇打开。

### 4.1 长程编排：三条最有用的机制

针对「宏观任务 → 多条原生 workflow → 10 次以上调用仍记住整体状态」：

1. **耐久项目记忆，计划、执行纪律、状态日志分开，每次调用先读。** Codex 长程任务的做法：`https://developers.openai.com/blog/run-long-horizon-tasks-with-codex`。
2. **只追加事件日志 + 折叠摘要。** OpenHands condensation、Temporal child workflow 与 continue-as-new、Anthropic session log 均属此类；父任务只存子流程 id、状态和摘要，不复制子流程全文。
3. **裁决是 durable signal，不是同事务里的同步等待。** Temporal child workflow、Restate durable promise、Cognition 的单写者 + 更强模型裁决。

旁证（不要写成内核必须项）：LangGraph 的 thread 与跨 thread store 分级、Inngest 的 step id memo、Goose 的 parent_session_id、MetaGPT 的结构化文档而不是对话、MAAD 的 evaluator 门（草案 9.7 已吸收）、HiAgent/CAT 按子目标折叠、Exp-SWE-Agent 的项目级记忆表。外部模型与 embedding 不进事务。不确定标注：Devin 内部架构、SWE-MeM 预印本编号、Goose 文档站同步关系。

### 4.2 软件工厂（Warp 为主）

Warp（工厂页已核对）：work item 是一等持久对象；foreman 为每个 work item 延续一条会话，按 triage → planning → building → reviewing 路由，阶段可跳过或退回；spec 必须人批；工厂开 PR 但不代做合并；阶段定义在 Git 里的 skill 文件，外层循环只对 skill 定义开 PR。`https://docs.warp.dev/factories/how-factories-work/`、`https://docs.warp.dev/platform/orchestration/`。

同类只借工序、不借云沙箱：Factory 的 spec 门与 worker/validator 分工（validator 细节来自第三方报道，标不确定）；Devin 的结构化 pipeline 与带出处的记忆笔记；Jules 的 plan 审批与固定为 PR 的交付物；Copilot Workspace 历史设计 Task → Spec → Plan → Implementation（后来下线）；Cursor 把 durable loop、机器状态、对话状态拆开。

要写进草案细化的三个选择：

1. **作业单是持久对象。** work item 对应草案 9.4 的 `v20_plan_tasks`：有状态、有验收条件、有 evidence 引用，不是 prompt 里的一行 todo。
2. **工序图是持久对象，编排只做确定性路由和门。** Warp 的 triage/planning/building/reviewing 对应一张 admitted 的工序图（`v20_plan_edges` + workflow_route）；foreman 的「路由」是纯函数 + Control admission，模型的自由度在工序内部，不在工序之间。
3. **记忆是带出处的短笔记，与流程定义分开。** 记忆条目带 provenance（来源 artifact hash / run id / 时间），与 skill 文件式的流程定义分离存放、分离修订。

### 4.3 递归自我改进：2026 年的参照是「改 harness、搜索期不改权重」

这里「改」的对象是运行时自己的工具、工作流和策略，不是帮用户改业务代码。MASS（本地 `/Users/wxl/Projects/mass`，remote `https://github.com/SakanaAI/mass.git`）不引入 RepoPrompt-CE，也不作为 v20 的 harness 实现。它改的是基准任务提示词里的一段设计块，循环内同一个模型做执行、提议和裁判，然后用轨迹做后训练。这和 CE 的会话、父子 agent、外部 oracle 不是一层。下面留下的只是已经核对过的边界，不是要搬的代码。README 只链接 MASS 论文 `https://arxiv.org/abs/2610.12176`（正文未打开）。RHI 论文摘要已核对：`https://arxiv.org/abs/2607.15524`。

MASS 的 RHI 阶段（README，已核对）：在权重固定时搜索多 agent workflow；后训练阶段才用轨迹更新权重。搜索期的形态（除注明外均已核对）：

- **改动面被 marker 框住**：design block 的两个 marker 在 `harness_improvement/iterate_multi_agent_prompt.py:35-36`，提议只落在框内。
- **执行 runtime 冻结**：`runtime/run_episode.sh:5-13` 的 qwen-code 采样、窗口、超时、yolo、stream-json 与原 episode 字节级一致。脚本里「NOTHING else」那句说的是脚本相对原版只多了 MODEL_ID、代理和 HIW_CONDITION，不是说 harness 什么都不能改。
- **对照固定的无 harness 基线**：`mass/pipeline.py:112-130`，搜索用 `--judge-vs-baseline` 对照 `reference`，最后一轮 `--evaluate-only`，模型是当前 `model_id`，后端 local-vllm。
- **没赢基线就不进下一阶段**：`mass/pipeline.py:141-143`，`beats_reference` 为假的任务不进 collect。`retained_workflow.json` 由 `harness_improvement/iterate_multi_agent_prompt.py` 约 `:2196-2200` 在 evaluate-only 路径写出，没赢基线时 `beats_reference` 为假——不要理解成「只有赢了才写这个文件」。
- **平局和失败不换冠军**：冠军只在仲裁 winner 为 B 时才换成当前版本（`harness_improvement/iterate_multi_agent_prompt.py:2189-2190`）。

一条必须保住的分界：MASS 循环内用同一个模型做执行、提议和成对裁判。草案仍然要求提议与 admission 分离。能留下的边界是：改动面被框住、执行 runtime 冻结、对照固定基线、平局和失败不换当前版本、没有通过对照就不进下一阶段。这些边界不依赖把 MASS 放进 CE。

适合放进 CE 的是产品形态的可替换 harness，而不是基准搜索加后训练。最接近的公开例子是 Prime Agent 的 Continual Harness（博客已核对：`https://www.primeintellect.ai/blog/prime-agent`；论文 `https://arxiv.org/abs/2608.23552` 正文未打开）。可改的是补充 prompt、memory、skill、subagent 规格；base system prompt 不可改；`/refine` 在 turn 边界应用小改动，并按 refinement id 回滚。它自己会把编辑应用到 harness 上，所以进 CE 时应用点必须走 Control admission，由 oracle 裁决，不能照搬自动应用。直接 CRUD 是否绕过快照，第三方笔记这么说，仓库代码未核对。

Self-Harness（`https://arxiv.org/abs/2606.09498`，正文未打开）的回归门更干净：held-in 与 held-out 不退步才晋升，拒绝则旧 harness 不动。它没有会话和子 agent 面，只适合抄闸门，不适合当运行时。RHO 自己做偏好裁决，和 MASS 同一类，不采用。HSI、Meta-Harness、auto-harness 是离线搜索或仓库级批处理，不作为 CE 的会话层。

### 4.3.1 JAZ 与上下文搜集

JAZ（本机 `/Users/wxl/Projects/jaz`，论文本地副本 `docs/references/jaz-paper-harness-as-a-language.md`，作者单位 MIT CSAIL）不是文件系统或大代码库的检索器。论文把评测限制在基准环境自带的工具上，并写明 agent 不能访问文件系统或互联网。Takeaway 2 的主张是：对原始对象做完整的编程访问，胜过在大对象上放一个预制搜索工具。

它适合的是一次 invoke 树里的 session 历史。`__history__` 是 REPL 里的列表，由 agent loop 单独写入（`src/jaz/_agent.py` 约 968、1052 行，已核对）。模型用自己写的代码在这份历史上做精确查找，再把引用传给子 `invoke`。没有 embedding，没有排序，也没有跨进程的可查索引。

因此：session 历史适合借「历史是可编程对象」这一条；文件系统和大代码库不适合把 JAZ 当成搜集器。整份采用 JAZ 会得到第二个 agent loop。`docs/designs/v15-jaz-dev.md` 已经把 `invoke` 写成另一套 Postgres 行为合同，并且写明 Python REPL 沙箱不是 v15 的权威。对 v20 / CE，只把已有的 WorkspaceContext 和会话记录暴露成只读对象；预算、递归和消息缓冲仍留在现有 Control。

十条最低要求，按约束对象标注（内核 / 可替换 harness / 评估工件）：

1. 提议与 admission 分离：提议、评测、批准是控制面上的不同角色，admission 只走 Control。至于是不是同一个模型充当提议者与裁判，属于 harness 的选择，内核不禁止（MASS 的自监督即如此）。【内核】
2. 只有一个版本化入口：所有自我修改经同一个 `Control.execute` 版本化操作进入，有 request_id 与幂等收据。【内核】
3. 外部 IO 与评测不进事务：搜索、评测、调模型都在事务外，结果以 artifact + digest 回提交。【内核】
4. 可改面枚举封闭且有边界：只有工具实现、prompt、workflow/governance policy 可改，单次提案的改动面像 MASS 的 marker 一样被框住；admission、fence、幂等、恢复、审计、stop 对改进者只读。【内核】
5. 执行 runtime 冻结：搜索/评测期间执行 runtime（采样参数、窗口、超时等）不变，可变的只有被框住的改动面。【内核】
6. 对照固定基线：每次评测对照固定的无改动基线（MASS 的 `reference`），基线定义本身不被改进者修改。【评估工件】
7. 平局与失败不换冠军：只有明确胜过基线的候选才替换当前版本；未胜出的候选保留为只追加的 archive 记录。【可替换 harness（裁决口径）+ 内核（archive 只追加）】
8. 没赢基线不进下一阶段：未通过对照的提案不驱动后续 workflow frontier。【可替换 harness】
9. 可回滚与审计链：每个 admitted 修改可指回前一版本，回滚本身也是版本化 Control 操作；从提案、评测证据、admission 决定到生效版本，全程在 `v20_events`/`v20_artifacts` 可追。【内核】
10. 改进预算与停机：自我改进消耗与普通任务同一 quota/attention 体系，stop 对改进回路同样有效；默认人批，仅白名单低风险 route 可自动 admit（与草案第 14 节问题 7 一致）。【内核（预算/停机）+ 可替换 harness（白名单范围）】

明确不进内核：训练循环（MASS 的后训练阶段不在 v20 借鉴范围内）、事务内调模型；admission 本身永远不是可改面（见第 4 条）。

### 4.4 第 9 节缺的状态与门

把 4.1–4.3 落到草案第 9 节已有的名词上，缺的是：

1. **宏观记忆三件套。** 草案已有 PlanRevision（计划），还缺「执行纪律」与「状态日志」两个持久对象。建议：状态日志为 append-only 表（可并入 `v20_events` 的宏观分区），折叠摘要为 `v20_artifacts` 的内容寻址 artifact；父任务只存子 workflow 的 id、状态和摘要 artifact 引用。这是「10 次以上 workflow 调用后宏观状态仍可读」的直接支撑：每次 workflow 调用先读计划 + 纪律 + 状态日志摘要，而不是重建全部历史。
2. **持久作业单与工序图。** 草案 9.4 的 `v20_plan_tasks/edges` 已能承载；要补的是把 Warp 的工序语义写进去：每个 task 的 workflow_route 指向一张 admitted 工序图，工序之间的转移是确定性路由 + 门（spec 门、evaluator 门），可跳过或退回，但跳过与退回本身也是 Control 操作。
3. **裁决门作为 durable signal。** 「分歧交给 oracle」的落地形态：oracle 调用是一次工具/workflow 步骤，其结果是 `v20_artifacts` 里带 hash 的裁决 artifact；等待它的 workflow step 处于 wait，由裁决提交事件唤醒（草案 8.2），不是同事务同步等待。这直接支撑「先调查，再计划，再实现或编排，分歧交给 oracle」的用法：调查（草案 9.6 investigate 只读模式）→ PlanProposal → admission 门 → admitted frontier 上的实现/编排 step → 分歧时挂起等 oracle 裁决 artifact。
4. **自我改进门。** 可替换面是补充 prompt、skill、subagent 规格和记忆，不是 MASS 的基准设计块，也不是 JAZ 的 invoke 循环。提案在 turn 边界提交，对照固定基线或回归工件，由 oracle / Control admission 决定是否生效；平局与失败不替换当前版本。适用第 4.3 节十条。

建议补进草案的句子（第三层）：

- 9.4 补：宏观状态日志为 append-only，折叠摘要是 `v20_artifacts` 的内容寻址 artifact；父 workflow 对子 workflow 只持有 id、状态与摘要引用。
- 9.5 补：selected task 的工序转移是确定性路由加门；门不通过时 task 停在原状态并记录原因，不自动改道。
- 9.6 补：oracle/裁决类分歧以 durable signal 建模——等待方 wait、裁决 artifact 提交事件唤醒，不做同事务同步等待。

---

## 5. 对草案的修订清单

按草案章节给出「建议补上这句话」，每条指回现有小节。以下建议不推翻草案已写死的原则：内核唯一写入（草案 2、4.2、13.7）、三层不是三个 scheduler（草案 2、3.3、9.2）、外部 IO 不进事务（草案 4.4、10.6）、不 runtime import v13（草案 1、13.1）。

### 3.1（微观 loop）

- 补：一次 turn 的 durable 事实只有一次 Control 推进加一次 receipt 提交；Host 进程内的计数、出口词与预写判断不构成事实，重启后必须能从已提交 snapshot 重建。（依据：v13 分裂 1、6；`driver.py:441-466`、`:573`，已核对）
- 补：微观 disposition 五词是 SQL 返回词、Host 出口词与上层 controller 共用的同一闭集。

### 3.2（中观 workflow）

- 补：workflow 实例的当前步骤、父子关系与 terminal 状态是 Kernel durable 状态；WorkflowPolicyPlugin 的纯计划只携带建议，不携带推进权。（依据：CE ownership/epoch/parentSessionID，调查报告，未逐行复核）
- 补：workflow 推进不依赖 provider 在场；父等子是 durable signal 加 wait/notify，不是同步阻塞。

### 4.1（唯一公共入口）

- 补：start/poll/wait/steer/respond/cancel/spawn/handoff 对 loop run 与 workflow run 是同一组动词；内部操作与外部操作共享同一幂等收据空间，计划写入（plan_*）也走此入口。（依据：v13 分裂 2、3，调查报告，未逐行复核）
- 补：返回词与 disposition 使用同一闭集。

### 4.2（不可插件化部分）

- 补：receipt validation 是纯函数，只决定 receipt 可否提交，不触发第二次推进。（依据：`take_exit` 反例，`driver.py:429-434`，已核对）
- 补：effect/tool invocation 的 scoped claim + fence + complete 在 Control 内部只有一处实现。（依据：v13 五个租约写者，调查报告，未逐行复核）

### 4.3（最小 durable 对象）

- 补：`v20_workflow_runs` 携带父引用；oracle/裁决类结果进入 `v20_artifacts` 并以 hash 引用进控制链。

### 4.4（事务边界）

- 补：评测、训练式循环与一切 provider/工具调用同属「事务外 IO」，其结果以 artifact + digest 回提交。（依据：4.3 节十条之 3）

### 8.2（wait/notify）

- 补：跨 run 的等待（父等子、step 等裁决）统一建模为 durable signal：等待方 commit 后 wait，信号方提交产生事件唤醒；丢通知由 bounded poll 收敛。（依据：4.1 机制 3、4.4 节 3）

### 9.4（计划持久化）

- 补：增加宏观状态日志（append-only）与折叠摘要 artifact；父 workflow 对子 workflow 只持有 id、状态与摘要引用。（依据：4.1 机制 1、2）
- 补：plan task 即作业单，是带验收条件与 evidence 引用的持久对象。（依据：4.2 选择 1）

### 9.5（宏观顺序与选择）

- 补：selected task 的工序转移是确定性路由加门；门不通过时 task 停在原状态并记录原因，不自动改道；spec/evaluator 门的通过与退回都是 Control 操作。（依据：4.2 选择 2，Warp 工厂页已核对）

### 9.6（调查与 replan）

- 补：分歧与裁决以 durable signal 建模；「分歧交给 oracle」是 wait 加裁决 artifact 唤醒，不是同步等待。（依据：4.1 机制 3）

### 9.9（强制执行边界）

- 补：宏观调用每次先读 admitted 计划、执行纪律与状态日志摘要，再选择 frontier；宏观状态在多次 workflow 调用之间不依赖会话内存。（依据：4.1 机制 1）

### 新增小节建议（第 9 节内）

- 新增「运行时自我改进边界」小节：写入第 4.3 节十条，主例为 MASS 的 RHI 阶段（搜索期改 harness、不改权重），标明可改面（工具实现、prompt、workflow/governance policy，单次改动面有 marker 式边界）与只读面（admission、fence、幂等、恢复、审计、stop）；自我改进提案走与 PlanProposal 相同的 admission 通道，对照固定基线评测，平局/失败不换当前版本。（依据：4.3 节；MASS 本地仓库已核对；2026 同类旁证均未逐条打开）

---

## 6. 未核实清单

撰写时已重新打开的位置见文首核实声明。以下均未重新核对，引用时按「调查报告，未逐行复核」或「未打开」对待：

**v13（调查报告，未逐行复核）：**

- schema 正文、被覆盖的旧 advance 正文（`v13/loop/advance.sql`、`v13/control/v13_control.sql` 中的定义未打开；仅确认 `load.py` 装载顺序与 `v13_plan_arm.sql:332` 的 CREATE OR REPLACE）。
- `workflow_bind` 全文、`external_exec`。
- `LoopDriver.run_turn` 的生产调用者之有无。
- `RealChain._run` 直接 serve、`GoalSupervisor.tick` 直接 settle_once 的具体实现。
- plan_contract apply_id 与 effect idempotency_key 两份事实的细节；agentctl steer/answer 的跨会话写路径；goal stop/resume、harness_settle、recover_idle、supervisor tick 的各自推进；fanout claim、fair_claim、workspace opener、agentctl answer 四个租约写者；controller 六词与 supervisor 出口词。
- decisions 表、v13_policies 的表结构与写者。
- 未连库验证 pg_proc 中的实际函数定义。

**RepoPrompt-CE（调查报告，未逐行复核；仅 `WorkflowPrompt+Orchestrate.swift:1-80` 与 `AgentWorkflow.swift:122/141` 已核对）：**

- `AgentSession.parentSessionID`、`AgentRunOwnership`、turn epoch 的定义与使用点。
- provider 流到 terminal commit barrier、再发布到 session store 的落盘全链。
- wait cursor、terminal 幂等、census 投影、wait 决策表全文、auto-wake 四个 owner。
- activation 替换时序、各 runner 如何映射 run state。
- oracle artifact 的 sha256 + revision CAS 实现点；plan 导出仅为磁盘 markdown 的断定。

**网络检索（除 Warp 工厂页外未逐条打开）：**

- Codex 长程任务博客、OpenHands condensation、Temporal child workflow / continue-as-new、Restate durable promise、Anthropic session log、Cognition 单写者裁决、LangGraph、Inngest、Goose、MetaGPT、HiAgent/CAT、Exp-SWE-Agent、Factory、Devin、Jules、Copilot Workspace、Cursor 的具体描述。
- 2026 同类旁证：Self-Harness（2606.09498）、HSI（2608.08466）、RHO（2606.05922）、Meta-Harness（2603.28052）、Mixture of Self-Improving Branches（2609.37834）、auto-harness（`https://github.com/neosigmaai/auto-harness`）正文未打开。Prime Agent 只核对了博客 `https://www.primeintellect.ai/blog/prime-agent`；论文 2608.23552 正文未打开；直接 CRUD 是否绕过快照未核对仓库代码。
- 更早一代的 DGM、Gödel Agent、ADAS、Voyager、Reflexion 未逐篇打开，且不再作为主体参照。
- MASS 论文 `https://arxiv.org/abs/2610.12176` 正文未打开（已核对的是 README 与文首所列源码位置）。RHI 论文 `https://arxiv.org/abs/2607.15524` 只核对了摘要，仓库正文没有这个编号。
- 明确标为不确定：Devin 内部架构、SWE-MeM 预印本编号、Goose 文档站同步关系、Factory validator 细节（第三方来源）。
