# v13 四步调查：S1、S2、E 计划、I1–I4（2026-10-06）

UA 已收口。`main` 在 `c360bd2`（`v13: record the progress human_pending continuation`），其历史含 `b304695`（`v13: add authorized fake unattended acceptance`）。`v13/load.py` 的 `STAGE_THROUGH` 停在 `fair_claim: 39`，仓库里没有 `v13/agentctl/`。下一刀是 S1 agentctl-observe。E1–E3 当前只解锁计划成文，不解锁实现。I1–I4 仍后置。这四步都不能把 UA 计划 §8 的禁止项悄悄写成已经成立。

本文只复述已裁决范围和活体依赖。函数名与路径对照过当前 `pg-agent` 树，以及 `/Users/wxl/Projects/repoprompt-ce`、`/Users/wxl/Projects/loopx`。对不上的符号没有换一个看起来像的名字顶上。

权威顺序仍是：用户既有决定 > 裁决记录 `docs/reviews/v13-agentctl-da-rulings-2026-10-03.md` > 设计稿 `docs/designs/v13-agent-control-minimal-form-2026-10-02.md` > 调查 `docs/investigations/v13-phase-d-reopen-reference-survey-2026-10-02.md` §8.2。调查 §8.2 里被裁决改写的句子，下面按裁决写，不按调查的原建议写。

## 四步总表

| 步 | 现在开发什么 | 主要依赖 | 落地之后能观察到什么 |
|---|---|---|---|
| S1 agentctl-observe | 一个 `kind=sql` 的只读工具行 `agentctl_observe`，handler `v13_agentctl_observe`，`STABLE`。同笔追加加载序、收紧 `r1_load_append_ok`、做 D-2 勘误 | `v13_observe`、`v13_scheduler_hint`、`v13_child_pointer`，以及 catalog 的 sql 工具守卫。目录 `v13/agentctl/` 还不存在 | 一个 agent turn 经这一个工具读控制面。未授权 id 走 `v13_observe` 的整次零行。无写动词、无 guard 扩员、无新事件生产者。`spawn_subsession` 仍是 `enabled=true`，dispatch 零 DDL |
| S2 agentctl-write | **S1 之后另一次提交**：`agentctl_steer` / `agentctl_answer` / `agentctl_cancel` 三员同笔，只包装既有动词 | 两参 `v13_cancel`、六参 `v13_complete`、`v13_append_event`、`v13_control_authorized`、`v13_named_sql_writer` | 模型经 FakeLLM 选出这三个动词；Python 只做 executor-of-record。身份从 `p_sid` 派生。无新 `effects.kind`、无新 route 动作、无外部 IO 进事务 |
| E1–E3 | **只写计划，不写代码**。E1 薄入口、E2 用 RP-CE 承载已有五原语、E3 Postgres→文件单向投影 | 现有 turn（`loop_driver`）、监督 tick、ACL、claim/fence、workspace、should_run、quota_window | 计划入库之前，运行时没有任何新行为。计划必须写明 fail-closed、PG 重跑 admission、禁止双推进者。没有 stage 号，也没有 gate 脚本 |
| I1–I4 | 现在不开发。调查 §8.2 的内化清单：根树配额、只读咨询 lane、wake、公平面残留 | 已有的 session 局部配额、should_run 门 v3、`v13_wake_is_satisfied_v1`、`v13_claim` / `v13_claim_fair` | 四项都还没立项成计划。落地前不能声称 PC-4、咨询 lane、auto-wake 或帽已罩住活体 `v13_claim` |

## 1. S1 agentctl-observe

### 开发什么

设计 §5 把 S1 定成 stage 40a，一次提交、一个 gate：`uv run python v13/agentctl/test_agentctl.py`。新目录 `v13/agentctl/`，SQL 文件名设计写的是 `v13/agentctl/v13_agentctl.sql`。工具行只有一条：

| 项 | 已写死的值 |
|---|---|
| 行名 | `agentctl_observe` |
| kind | `sql` |
| handler | `v13_agentctl_observe` |
| 波动性 | `STABLE` |
| 组合 | `v13_observe` + `v13_scheduler_hint` + `v13_child_pointer` |
| gate | `actl_catalog_rows`、`actl_actor_gate`（读路径）、`actl_guard_closed` |

同一次提交还要做三件收尾，不能拆开先做：

1. 把新 SQL 追加进 `v13/load.py` 的 `SQL_LOAD_ORDER` 和 `STAGE_THROUGH`。D-1：不得先改冻结规则、后补 stage。不得改 stage 1–16 的文件。
2. 收紧 `r1_load_append_ok`（`v13/plan_arm/test_plan_arm.py`）。设计 §7 曾写「放宽」，裁决 D-1 的用词是「追加项闭集收紧版」。以裁决为准。
3. D-2：修正 parity R6，台账加勘误。dispatch 零 DDL。不得把 `spawn_subsession` 的 `enabled` 从 false 翻成 true 记成交付——活体从 `af5950f` 起就是 `true`。

`spawn_subsession` 保持 `enabled=true`。S1 不给 `v13_named_sql_writer` 加臂，不新增 VOLATILE 例外，不生产事件。

### 依赖

这些符号都在当前加载序里。后文件的 `CREATE OR REPLACE` 才是活体。

| 文件 | 活体符号 | 和 S1 的关系 |
|---|---|---|
| `v13/observe/v13_observe.sql:43` | `v13_observe(p_actor uuid, p_ids uuid[])`，`STABLE`，返回表 | 组合的读主体。任一 id 未过 `v13_control_authorized` 就 `RETURN`，此时还没有 `RETURN NEXT`，整次调用零行，不是按 id 滤掉一行 |
| `v13/acl/v13_acl.sql:90` | `v13_control_authorized(p_actor, p_target)` | 直接亲缘：`sessions.parent_session_id` 必须就是 `p_actor`。自己看自己返回 false。目标不存在返回 false。`p_actor` 为 NULL 时落到 `v13_control_operator()` |
| `v13/attention/v13_attention.sql:183` | `v13_scheduler_hint(p_sid)` 的首份定义，`STABLE`，返回 `text` | 被下一行替换 |
| `v13/govern/v13_govern.sql:517` | 同名函数的活体替换，仍是 `STABLE` / `text` | 未知会话 `RAISE`，不返回空行 |
| `v13/workflow_bind/v13_workflow_bind.sql:7,128` | `v13_child_pointer(...)`，`VOLATILE`，返回 `uuid` | 文件头写明 `workflow/pointer` 只由它写。它不是读函数 |
| `v13/catalog/v13_catalog.sql:18-58` | `v13_tools_catalog_frozen` | enabled 的 sql 工具必须是 `(uuid, jsonb) → jsonb`。`VOLATILE` 只有 `v13_named_sql_writer` 非空且 `v13_spawn_writer_ok` 为真才豁免 |
| `v13/spawn/v13_spawn.sql:42-49,1757-1760` | `v13_named_sql_writer` 只认 `v13_spawn_subsession`；`spawn_subsession` 行 `enabled=true` | S1 不改这个 CASE，也不改这行 |
| `v13/envelope/v13_envelope.sql` | tools_catalog | 设计 §3.1：param_spec 非空的 enabled sql/tool 行进入 judgment envelope。S1 不改 envelope 文件 |
| `v13/control/v13_control.sql` | advance 的 sql 分派臂 | 设计说 handler 走既有 sql 快路。S1 不改 control 文件 |
| `v13/load.py:56-98` | 末项 `fair_claim` / `39` | 新 stage 只能尾部追加 |
| `v13/plan_arm/test_plan_arm.py:327,409,635` | `r1_load_append_ok`、`r1_phase_d_prefix_allowance`、`r0_source_scope` | 见缺口。`r0_source_scope` 会调用前缀闭集 |

`fb295ac` 的 `v13` 树里已经有 catalog、acl、observe、attention、govern、workflow_bind、spawn、envelope、control。`r0_source_scope` 把这些文件放在保护集里（排除项只有指定测试、README、`v13_plan_arm.sql`、`loop_driver/driver.py`、`load.py`）。S1 不能就地改它们。新行为只能出现在新追加的 SQL 里，靠调用上面这些函数。

### 落地后能观察到什么

- `tools` 里多一行 `agentctl_observe`，`kind=sql`，handler 为 `v13_agentctl_observe`，函数 `provolatile` 是 stable。
- `spawn_subsession` 的 `enabled` 仍是 true。没有第二条 dispatch 行，也没有 `UPDATE tools` 去「翻 true」。
- gate `actl_catalog_rows`、`actl_actor_gate`、`actl_guard_closed` 在 `v13/agentctl/test_agentctl.py` 里退出码 0。名单外的 VOLATILE sql 工具仍被 catalog 拒绝。
- 一个 FakeLLM turn 可以发出这个工具调用，并在同一事务里读到控制面投影。未授权 id 得到零行。
- 这一提交不出现 steer/answer/cancel 行，不出现新的 `steer/injected` 生产者，不改 `v13_named_sql_writer` 的 CASE。
- parity 文档里 R6 不再写「`spawn_subsession` 行保持 `enabled=false`」。台账有一行勘误，指向 F22 的真问题是 catalog 具名例外，不是 enabled 开关。盘点快照（prompt-exports）不回改。
- `SQL_LOAD_ORDER` 比现在多且只多尾部项；`STAGE_THROUGH` 编号接续，不跳号。stage 1–16 文件字节不动。

### CE / LoopX 为什么把范围收在这里

LoopX 全树没有 `agentctl` 这个符号。它的配额、wake、`outcome_floor` 是文件账本和宿主 hint，不是一行 sql 工具能装下的东西。`loopx/control_plane/quota/accounting_admission.py` 的 `quota_accounting_admission` 对 `runs/index.jsonl` 和 source guard 取文件锁。这是事务外的文件 IO。S1 若去「顺便读配额」，就会把这种 IO 带进 sql 工具。所以 S1 只组合 v13 里已经存在的三个函数。

RP-CE 没有 Postgres 控制面，Sources 里也没有 `source_principal`。`DomainAgentSessionOperationAuthorizer.swift` 写明调用者身份来自服务端路由（`RequestMetadata` → connection purpose），从不来自工具参数；oversight grant 也不从工具参数收。`request_attention` 在 `MCPAgentControlToolProvider.swift` 的说明里是：`accepted` 表示已存储或已在队列，从不表示已唤醒、已送达或已执行。S1 因此不能把「读到了控制面」写成「会话会被唤醒」或「观察者获得了 operator」。

CE 的 `agent_run` poll/steer/respond 改的是 CE 进程里的会话，不是数据库动词。那是 E2 的承载问题，不是 S1 要移植的实现。

### 文档缺口

这些缺口没有现成答案。S1 不能靠实现者补一句设计把它们填上。

1. **行数互相矛盾。** 设计 §3.1 表有四条新工具加一条复用的 dispatch。§3.3 的 `actl_catalog_rows` 写「四行 kind=sql」。§5 的 S1 写「单行 STABLE 工具」。S1 按 §5 只登记 `agentctl_observe`。§3.3 那句「四行」没有改成「S1 只断言一行，另外三行尚不存在」。
2. **返回形状只有「三函数组合」六个字。** 三个活体函数对不上：`v13_observe` 返回表，`v13_scheduler_hint` 返回 `text`（未知会话直接 `RAISE`），`v13_child_pointer` 返回 `uuid` 并且是 `VOLATILE` 写者。catalog 却要求 sql handler 为 `(uuid, jsonb) → jsonb`。包装函数的 jsonb 键集没有写。
3. **`v13_child_pointer` 不是读。** 设计 §3.1 在函数名后面加了一个「读」字。活体函数写 `workflow/pointer`，而且是该事件的唯一写者。把它放进一个 `STABLE` 工具，和「零事件生产」直接冲突。文档没有给出替代的读函数，也不该在 S1 里新造一个。
4. **没有 40a / 40b 的 `STAGE_THROUGH` 键。** 设计说新文件编号 40，又把 S1/S2 叫做 40a/40b。`r1_load_append_ok` 要求每个追加 SQL 路径对应一个整数键，编号接续、不跳号。40a/40b 不是这种键。S1 与 S2 是一个 SQL 文件改两次，还是两个键，文档没写。
5. **只点名 `r1_load_append_ok` 不够。** 该函数相对 `fb295ac` 的 `load.py` 接受任何规范形态的尾部追加，只要目录已跟踪、编号接续、且 `workspace_admit < frontier_gap < goal_supervise < fair_claim` 仍成立。它现在并不把尾部钉死。真正挡住新目录的是 `r1_phase_d_prefix_allowance`：`fb295ac` 之后新增的跟踪文件必须落在 `v13/goal_supervisor/`、`v13/fair_claim/`、`v13/fair_driver/`，fresh 文件只允许 `v13/goal_supervisor/accept_unattended.py`。`v13/agentctl/` 会在 `outside the three prefixes` 失败。`r0_source_scope` 会调用这个函数。收紧必须和 stage 同一提交；不能先把前缀闭集放开。
6. **收尾文件名不完整。** D-2 点了 parity 与台账。活体错句在 `docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md` 的 R6 行（「行保持 `enabled=false`」）。台账 `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` 已有两行 F22，写的是 enabled=true 时 parse 会被拒，且该缝已关闭。勘误是加记录，不是重写这两行的历史。设计说的「矩阵 / README」没有点名新文件路径。

## 2. S2 agentctl-write（steer / answer / cancel 三员同笔）

### 开发什么

S2 是 S1 之后的下一次提交，不是 S1 的后半。设计 §5 叫它 stage 40b。三行一次落地，并同时扩 `v13_named_sql_writer`、加版本化 controller 策略行、跑完全链 gate。裁决 D-4 的条件就是「三员同笔」，不是先 steer 再 answer。

三员只包装既有动词：

| 工具 | 包装 | 活体签名 |
|---|---|---|
| `agentctl_steer` | `v13_append_event(target, 'steer/injected', …)` | `v13/schema/v13_core.sql:62`：`(p_sid, p_event_id, p_type, p_payload, p_source_effect uuid DEFAULT NULL) → bigint`。函数体内会 `UPDATE sessions` 推进 `next_seq` |
| `agentctl_answer` | 先 `v13_control_authorized`，再六参 complete | `v13/acl/v13_acl.sql:245`：`(p_actor, p_effect, p_attempt, p_fence, p_status, p_result) → text` |
| `agentctl_cancel` | 两参 cancel | `v13/acl/v13_acl.sql:121`：`(p_actor, p_sid) → text` |

acl 里还有五参 `v13_complete`（`:459`，把 actor 填 NULL）和一参 `v13_cancel`（`:236`，同样填 NULL）。NULL actor 会走 operator 分支。S2 必须调用上面的带 actor 重载，不能调用这两层包装。

D-4 的部署纪律：`SECURITY DEFINER`、固定 `search_path`、专用 `NOLOGIN` 属主、`REVOKE PUBLIC`。属主不得把调用者隐式升成 operator。授权在可信的 `p_sid` 上下文里做。这是 spawn SQL 档，不是新档。

D-3：`source_principal=controller` 允许，但只能从当前 `p_sid` 派生。模型自报的值要覆盖掉。`v13_control_authorized` 仍是硬前置，不得放宽成任意后代。审计三联是调用者、目标、注入事件。

D-5：用版本化策略行区分 controller 会话。不新增 session 标记或列。策略不持有 goal、授权或结算事实。

D-7：不新增 `effects.kind`，不新增 route 动作。动词选择必须来自模型输出。Python 不得硬编码 spawn→observe→steer→answer→cancel 这种控制序列。judge 档不是 S2。

gate：`actl_chain_full`、`actl_approval_two_phase`、`actl_steer_watermark`、`actl_cancel_sticky`、`actl_no_io`、`actl_driver_demoted`，加上 D-3、D-4 的检查（伪造 operator、越权零写、watermark、正文消费、write_targets 按调用图、拒绝路径零写、四件套）。台账欠一句：「2026-10-03 双车道复访，父签认关闭」。

明确不做：skip、无人值守 `plan_commit`、`v13_agent_run`、judge 档、真实 provider，以及下面「仍不能当成已经成立」里的 UA §8 各项。外部 IO 留在事务外。FakeLLM / FakeTool，不开套接字。

### 依赖

S1 的全部依赖仍在。S2 额外坐在这些活体上：

| 文件 | 关系 |
|---|---|
| `v13/schema/v13_core.sql` | `v13_append_event`。`events.type` 是开放词表，`steer/injected` 不需要新 DDL。写 events 的同时写 sessions 的序号 |
| `v13/acl/v13_acl.sql` | 六参 complete、两参 cancel、`v13_control_authorized`。complete 体内已有 human 应答与 unknown 墙，answer 包装本身不再写一套结算 |
| `v13/spawn/v13_spawn.sql:42-49` | `v13_named_sql_writer` 今天只返回 spawn 一员：`write_targets` 为 `artifacts, events, latches, sessions`，`mutating=false`。S2 要加臂，但这个文件在 `fb295ac` 保护集里，不能就地编辑 |
| `v13/catalog/v13_catalog.sql` | 三员是 VOLATILE，必须走具名写者豁免，否则 `v13_tools_catalog_frozen` 拒绝装载 |
| `v13/envelope/v13_envelope.sql`、`v13/control/v13_control.sql` | 既有 envelope 与 sql 快路。S2 不新增第三条通道 |
| `v13/fanout/v13_fanout.sql` | spawn 臂仍是 dispatch 的活体路径。S2 不改这条臂，也不把 cancel 换成别的扇出 |
| `v13/loop_driver/driver.py` | `decide_exit` 在 `:95` 定义，`LoopDriver.decide` 在 `:408` 调用它。`r1_driver_restore`（`test_plan_arm.py:275`）要求去掉 R1 哨兵后，该文件逐字节等于 `fb295ac` |
| `v13/plan_arm/test_plan_arm.py` | S1 收紧过的加载闭集。S2 若再追加 SQL 路径，闭集要在 S2 这一笔里再收紧，不能提前放开 |

### 落地后能观察到什么

- `tools` 里再多三行：`agentctl_steer`、`agentctl_answer`、`agentctl_cancel`，都是 `kind=sql`，三函数满足 DEFINER / 固定 `search_path` / NOLOGIN 属主 / `REVOKE PUBLIC`。
- `v13_named_sql_writer` 的活体 CASE 含这三员。`v13/spawn/v13_spawn.sql` 字节仍等于 `fb295ac`，加臂出现在追加 SQL 的 `CREATE OR REPLACE` 里，而不是去改保护文件。
- 有一条版本化策略行，request 快照里能看到策略版本。`sessions` 没有新列、没有新的 controller 枚举。
- FakeLLM 的工具调用序列能跑通设计 §3.3 的链：steer 之后在途 advance 因 `max_event_seq` 前移而 stale；answer 用错 `interaction_ref` 则 RAISE 且消息含 current，用对则恰消费一个 human；cancel 后 required 档进入 cancelled，`unknown` 不被改写。
- 非直接亲缘的写调用零写。模型放进载荷的 `source_principal` 不会原样落库。
- `effects.kind` 闭集和 route 动作闭集与 S2 之前相同。
- gate 进程没有网络套接字、没有真实 provider。Python 侧没有一份写死的控制脚本；动词来自 FakeLLM 输出。
- 台账有那句父签认。R2 §7 的重开条件按 R-1=α 记为关闭，且只记这一句，不另开 spawn 档。

### CE / LoopX 为什么把范围收在这里

D-3 的「覆盖模型自报身份」在 CE 里已经是活体规则，不是新发明。`DomainClientPrincipal.swift` 把 `claimedProcessID` 标成客户端握手元数据，注释写明从不授予权威；权威进程号是内核观察到的 `processID`，另有 `hostLaunchToken` 这种 assurance。`MCPConnectionManager.swift` 同时记下 claimed PID 和 observed kernel peer PID，claimed 值本身不构成准入。`DomainAgentSessionOperationAuthorizer.swift` 的调用者分类来自服务端路由，工具参数不能把某人说成 operator。所以 S2 的 `source_principal` 必须由 `p_sid` 覆盖，不能做成像载荷里的一个可信任字段。

`AgentRunMCPToolService.swift` 里没有名为 `executePoll` 的函数。`op=poll` 走 `executeWait(args, forcePoll: true)`（约 `:425`）。`executeSteer`（`:1218`）和 `executeRespond`（`:1505`）改的是 CE 的 `AgentMode` 会话：steer 向那个进程内会话投递指令，respond 回答 pending interaction。它们不调用数据库动词。因此 S2 的三员留在 Postgres；CE 是以后的承载（E2），不是 S2 要链接的库。

LoopX 说明 S2 不能把配额或 wake 塞进这三员。`accounting_admission.py` 拿文件锁，锁的是运行目录里的账本，不是一行 `effects`。`loopx/control_plane/scheduler/scheduler_hint.py` 的 `build_scheduler_hint` 只构造 hint 字典，文件里没有 `time.sleep`，spend 政策写成 “no quota spend”。`loopx/control_plane/turn_driver/loop_controller.py` 开头写明自己是纯函数：不调用模型、不 sleep、不改宿主调度、不写状态、不扣配额。真正执行 wake 的是 `loopx/codex_cli_scheduler.py` 的 `execute_codex_cli_local_scheduler_tick_result`，而且要显式 opt-in。wake 不是一个 S2 动词。`outcome_floor` 是 `loopx/execution_profile.py` 的配置，再由 `loopx/quota.py` 的 `quota_with_handoff_outcome_floor` 叠到交付文件上，不是 Postgres 约束。

### 文档缺口

1. **steer 载荷仍是草案。** 设计 §7 开放问题 3 的键集是 `{schema_version:1, text, source_principal}`。D-3 只决定了 `controller` 这个值怎么来，没有把键集收成最终合同。
2. **审计三联没有列定义。** D-3 点了调用者、目标、注入事件三样，没有写它们是事件载荷的三个键、单独的表，还是从 `p_sid` 与 `v13_append_event` 的返回值现推。不能自己加表或加列。
3. **`write_targets` 不能抄设计稿上的手写集合。** 设计 §3.1 写的是 steer→`{events}`，answer→`{effects,events}`，cancel→`{effects,events}`。活体 `v13_append_event` 已经会改 `sessions`。两参 cancel 会改 effects 并经 append 再改 sessions。六参 complete 还有 human 事件、unknown 墙、worktree 等路径。D-4 要求按实际调用图核实，包括 answer→complete 的传递写、触发器、closeout/unknown、以及拒绝路径零写。核实结果文档里还没有。本文不给一套替代集合。
4. **D-8 禁止实现者发明换档边界。** retry、超时重试、stale recovery、replay、repair 不得换档。新 `effect_id` 本身不是换档资格。reject、无效 tool action、重复 wake、no-op advance 不是换档边界。steer/answer/wake 造成的新 effect 算不算边界，要逐类另裁。S2 不选 judge 档，也不写这张边界表。
5. **`actl_driver_demoted` 和 driver 冻结撞在一起。** 断言要求 controller 路径的 Python 调用面落在 claim、complete、provider 调用之内，且没有 `decide_exit`。活体 `LoopDriver.decide` 仍调用 `decide_exit`，而 `driver.py` 在哨兵之外不能改。设计把「抽出 claim/IO/complete」放在可选的 S3，S3 不是这四步之一。文档没有说明 S2 的源码级断言怎样在不改 `driver.py` 的前提下为真。
6. **40b 的加载键仍然没有。** 见 S1 缺口 4。S2 不能靠再编一个 40b 键混过去。

## 3. E1–E3：当前解锁的是计划成文

### 开发什么

裁决解锁表写的是：R-2 父决（已取 α）之后，**E1–E3 计划成文**，形状按 D-A 甲，加上 E3 的改写。不是建 stage，不是写 gate，不是改 `driver.py`。

仓库里没有这份计划。`docs/plans/` 下没有 agentctl 或 E1–E3 承载计划。调查 §8.2 是送裁前的路线图，不是这份计划。

计划要写的三块，以裁决为准：

**E1 外部契约。** 在现有 turn 上加薄的 ingress/egress，不建第二份 `v13_advance`。外部执行者是一条受限的版本化策略行，身份在可信适配入口绑定。注册只让这个执行者可被识别，不授予 operator。provider 载荷或工具参数里自报的身份一律拒绝。载体表达不了的能力标 unsupported，fail-closed，不用外部文件权威临时补洞。政策版本进入 request 快照。

**E2 RepoPrompt-CE 承载。** v13 里五原语已经有对应动词。对照调查所引用的 `docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md` §4：

| CE 原语 | 该文给的 v13 对应 |
|---|---|
| `startOrResume` | 建 effect（handler 参数 + lease） |
| `sendUserMessage` / `steerUserTurn` | `append_event` |
| `interruptTurn` | cancel |
| `respondToPermissionRequest` | human effect 应答 |
| `shutdown` | 租约回收 / fence |

RP-CE 是宿主侧的承载，不是第二套控制面。计划要写的是宿主映射，不是把 CE 的会话对象搬进 Postgres。

**E3 Postgres→文件，单向。** 投影在事务外。幂等键是事件水位或收据。投影失败不回滚 Postgres，也不改写 Postgres 里的事实。文件可以删掉再从 events/fold 重建。人改了文件，不回流。不调用 LoopX 会另建权威的写路径（todo、quota、settlement）。不启用 LoopX 的 authority store。不与 `postgresql_v0` 同库共存。允许一个部署级的 liveness 开关停掉重复的自主 tick；那不是模式表，也不是模式列。replan、lease、claim、fence、准入、stop 仍由 PG 执法。同一部署不能同时跑 `goal_supervisor` 和一个外部 driver，当作两个独立推进者。

D-A 把调查 §8.2 的三句话改掉了，计划不能照抄：

- 不是「乙起步、甲收敛」。甲是唯一权威。
- 不是「LoopX should-run 转发成 v13 admission」。LoopX 只给建议，PG 自己重跑 admission、quota、claim、fence、授权。
- 不是模式开关。D-A.3 否决了模式状态。被驾驶时让 `goal_supervisor` 静默，这句不能写进计划。

### 依赖

计划必须点名这些已有面，避免再设计一套平行机器。

| 路径 | 计划里它是什么 |
|---|---|
| `v13/loop_driver/driver.py` | 现有 turn：`run_turn`、`settle_once`、`_snap_with`。E1 的薄入口坐在这上面。该文件哨兵外字节冻结，计划不能把「改 driver」写成实施步骤 |
| `v13/goal_supervisor/driver.py` | 现有监督 tick。无 SQL、无加载键。E3 的「不得两个推进者」指的就是它和外部 driver |
| `v13/goal_supervisor/accept_unattended.py` | UA 验收脚本。声称上限就是计划 §8。E 计划不能把这份验收说成外部承载已经跑通 |
| `v13/schema/v13_core.sql` | sessions / events / effects 与 `v13_append_event`。ingress 进的是已有事件，不是新表 |
| `v13/acl/v13_acl.sql` | `v13_control_authorized` 与带 actor 的 complete/cancel。外部身份不能绕过它 |
| `v13/fanout/v13_fanout.sql:266` | 活体 `v13_claim(p_worker, p_lease_ms)`。LoopX 的 lease 只作适配输入，不替代这次领用 |
| `v13/periphery/v13_periphery.sql` | latch、canonical render、shadow。投影可以读这些折叠，但不能把 shadow 当成第二权威 |
| `v13/seam/v13_seam.sql` | `worktree/released` 折叠与 cap 豁免。E2 若提到 worktree，现有缝在这里，不在一份新状态机里 |
| `v13/workspace_admit/` | 工作区 effect 的打开、路径互斥、子集政策行。无文件系统 |
| `v13/workspace_exec/` | 另一份脚本上的 edit/write/bash。无 SQL。Fake 退出码不是产品可用，本目录不授权无人值守 |
| `v13/should_run/v13_should_run.sql` | 门的前身。活体门已被 govern 换体 |
| `v13/quota_window/v13_quota_window.sql` | session 局部的 `v13_quota_eligible`。E3 重跑 admission 时用的是这个 PG 合同，不是 LoopX 文件 |

### 落地后能观察到什么

计划成文之后，能观察到的只有文档：

- `docs/plans/` 里有一份新计划，分出 E1、E2、E3，并写明每块的非目标。
- 计划引用 D-A / D-A.1 / D-A.2 / D-A.3，而不是调查 §8.2 的「乙起步」。
- 计划里能找到：受限策略行、可信适配绑定、unsupported fail-closed、五原语映射、单向投影、事务外、水位或收据幂等、不调 LoopX todo/quota/settlement 写路径、不启用 authority store、无 `postgresql_v0` 同库、无模式表、同一部署只有一个推进者。
- 运行时不变：没有新 stage 号，没有 `test_*.py` gate，`STAGE_THROUGH` 仍可以停在 39，直到另一份经过复审的实施计划开工。调查 §8.2 写过「一条 Fake-provider 的外部进程 e2e」，那是调查的建议，不是现在就要出现的脚本。

### CE / LoopX 为什么这个范围合理

分析 §4 的判断是：五原语没有一个是 v13 缺的机制，外部 harness 是 wrapper。CE 源码支持「承载」而不是「再做一个控制面」。`AgentRunMCPToolService` 已经把 start/poll/steer/respond/cancel 做成对**本进程会话**的操作。`OracleExportFileWriter.swift` 把导出写进工作区文件，失败时文件可以留在原地，调用方要自己查看，不能盲目重试。`MCPReadFileToolProjection.swift` 只是把 `read_file` 的回复投影成界面能显示的结构。两者都是单向物化到文件或 UI，并且都不授予 operator。它们也不读 Postgres。所以 E3 可以借用这个形状，但不能说 CE 已经在投影 v13。

LoopX 同样没有一条 Postgres 事件到 LoopX 文件的投影。`loopx/control_plane/coordination/coordination_projection.ts` 把协调记录收成 Todo 读模型，文件里没有 Postgres。`local_authority_shadow_projection.py` 按源文件身份编码 todos/leases 分区，也不读 Postgres。因此 E3 仍要新写，而且不能把这两份投影当成「I 已经有了，可以直接做配额」。

`loopx/control_plane/quota/should_run.py` 的 `build_quota_should_run`（`:264`）返回一份决策载荷。它不写 v13，也不代替 `v13_should_run_gate`。这就是 D-A 把「转发」改成「PG 重跑」的代码侧理由。

`local_authority_provider.ts` 把默认提供者定为 `file`（`DEFAULT_LOCAL_AUTHORITY_PROVIDER`）。`authority_store.ts` 里 postgresql 的 stage 是 `stage2b_candidate`，不是默认实现。`postgresql_authority_store.ts` 有五张表：`authority_store_metadata`、`authority_heads`、`authority_commits`、`authority_events`、`authority_receipts`。该文件没有 quota、wake、`outcome_floor` 这些字。同库共存既被 D-A.2 否决，也补不进 I1–I3 的语义。

`loopx/control_plane/work_items/task_lease.py` 与 `todo_claim.ts` 的 claim 走文件或 `AuthorityStore`。它们可以当适配输入的对照，不能当 operator 例外，也不能替换 `v13_claim`。

### 文档缺口

- 没有 E 计划文件，没有 stage 号，没有 gate 脚本，没有政策行的列定义。D-A.1 只规定了方向：注册不等于 operator，身份来自可信适配，版本进快照，表达不了就走 R4 四问。
- 调查 §8.2 的 E2 还写了 worktree 绑定握手和 merge 人工门。裁决没有把这两项排成实现，也没有给 gate 名。计划若要收它们，必须写成待裁问题，不能写成 S2 之后的默认施工。
- 调查 §8.4 仍把 D-A 列成未决问题（乙起步、模式开关、postgresql 同库）。裁决记录已经否决了这三项。两份文档没有互相同步。设计稿 §7/§8 与调查 §8.2/§8.4 的「已裁」回填，裁决记录说随首个里程碑提交，现在还没做。那次回填不是本调查要做的事。

## 4. I1–I4（调查 §8.2，不是 D-9）

这四项来自 `docs/investigations/v13-phase-d-reopen-reference-survey-2026-10-02.md` §8.2 末段，对应原文的 R1–R4。裁决把近期目标定成「PG 已支持子集」，完整多日无人值守等这四项内化。它们现在没有计划文件，没有 stage 号。本节只写已经能核对的范围，不开工。

### I1 PC-4：根树配额

开发什么：把 `v13_quota_eligible` 从「只数本会话」改成沿根树重算；should_run 门升到 v4，新增 block id（调查举例 `goal_quota`）；`outcome_floor` 做成 `outcome_gap_streak` 的 fold。不建 quota 表，不建 `quota/spent` 或 `quota/voided` 事件。调查写明重开要另贴加载后 gate 全文哈希。

活体不是这件事。`v13/quota_window/v13_quota_window.sql:53` 的 `v13_quota_eligible` 是 `STABLE`，只数 `session_id = p_sid` 且 `type = 'turn/material_spent'` 的事件。这是 stage 27 的 session 局部窗口。`v13/govern/v13_govern.sql:348-359` 的活体政策行是 `should_run` version 3；gates 闭集为 `human_pending`、`unknown_wall`、`unconsumed_cancel`、`duty_cycle`、`quota_window`、`capabilities`、`goal_stopped`。没有 `goal_quota`。`v13_should_run_gate` 会拒绝闭集外的 id。全树 SQL 没有 `quota/spent` 表或事件。

`v13/govern/v13_govern.sql` 与 `v13/quota_window/v13_quota_window.sql` 都在 `fb295ac` 保护集里。I1 不能就地改这两份文件。

LoopX 侧的对照是文件账本，不是已落地的 PG 约束：`loopx/quota.py` 的 `quota_with_handoff_outcome_floor` 读取 `post_handoff_outcome_gap_streak`，超过 `execution_profile.py` 里的 `outcome_floor` 阈值就把配额态改成 focus_wait。`accounting_admission.py` 用文件锁保护 spend 账本。这证明 floor 与根树配额仍在 I，也证明 S2 的库内动词做不了这件事。

落地之后才能观察到的，现在都还没有：根树上的花费改变父会话的 `v13_quota_eligible`；门版本为 4 且多一个配额 block；streak fold 存在且不新增事件种类。在此之前，PC-4 仍是 UA §8 禁止声称的项。

缺口：block id 的名字、满额时 block 还是 shadow，调查 §8.4 自己标成未裁。没有 I1 计划，也没有「加载后 gate 全文哈希」的稿。

### I2 C4：只读咨询 lane

开发什么：一组只读的 llm 咨询 lane。闭集、有序收据、不建仲裁器，也不做答案合成。裁决仍走既有 human / ASK_USER。调查建议首期闭集 1+4，并写明 lane 是否占用 `spawn_budget` 必须另裁。这个 1+4 不是裁决过的常数。

依赖是既有 llm effect 与 fanout，不是新状态源。`v13/spawn/v13_spawn.sql` 的席位预算是会话树的预算，不是 lane 预算。本文不把 CE 的 Oracle roster 源文件写进来：那些路径不在本次核对过的引用清单里。调查 §3.2 已把「coordinator 不合成、不投票、不选赢家」记为 RP-CE 的非目标；I2 若立项，应把这句抄进计划合同，而不是在 S2 或 E 计划里实现它。

`MCPDomainToolResourceAdmissionController.swift` 是另一件事：它按连接限制并发（例如 `exclusiveConnection = 1`，`controlConnection = 8`），管的是 CE 进程内的实时宿主，不是 v13 的咨询 lane，也不是 S2 的写动词。它归 I，不归 E，不归 S2。

落地之后才能观察到：同一轮只读 llm effect 按 lane 顺序留下收据，没有仲裁函数，没有第二份目标状态。现在观察不到。

缺口：闭集大小、lane 与 `spawn_budget` 的关系，都还是调查 §8.4 的未决问题。没有计划，没有 gate。

### I3 V11：读并接线 auto-wake

开发什么：阅读并接线已有的 `v13_wake_is_satisfied_v1`。多日、真实 provider 是另一次授权，不包含在接线里。节律保持 `v13_scheduler_hint` 加驱动器睡眠，不进口 LoopX 的 RRULE 状态表。

活体函数在 `v13/spawn/v13_spawn.sql:783`（control 里的同名函数已被这次替换）。签名是 `(p_sid, p_effect, p_wake jsonb) → boolean`。UA 计划 §9 把「调用 `v13_wake_is_satisfied_v1` 或声称 auto-wake」列为停止条件。函数存在不等于 V11 已读、已接线、已被消费。

CE 的唤醒消费者是 `AgentModeViewModel+SessionLinkAutoWake.swift`。文件头写明它是某个观察者自动 lane-update turn 的临时准入，不是会话控制动词。`request_attention` 的 `accepted` 仍然不是唤醒。所以注意力请求不能算 I3 已经接通。

LoopX 把 hint 与执行拆开：`scheduler_hint.py` 与 `loop_controller.py` 不 sleep、不扣费；`codex_cli_scheduler.py` 的执行函数要 opt-in。v13 若要接线，接线点是 PG 谓词加现有 hint/睡眠，不是把 opt-in 执行器搬进来，也不是给 S2 加一个 wake 工具。

`v13/goal_supervisor/driver.py` 不在 `fb295ac` 树上，但 `r1_phase_d_prefix_allowance` 把它钉在 phase D 基线字节上（已知文件除三份特例外必须与 `78e77c7` 的 blob 相同）。I3 不能顺手改这个 driver。

落地之后才能观察到：某个已授权的 tick 会读 `v13_wake_is_satisfied_v1`，未满足则不推进，满足则同会话续跑。真实多日运行仍要单独的 provider 授权。现在这两件事都观察不到。

缺口：谁调用 wake（监督 tick 内还是独立消费者）调查 §8.4 标成未裁。没有阅读记录，没有接线计划。

### I4 PD-H：公平面残留，H1 优先

开发什么：处理 Phase D 台账 `docs/reviews/v13-long-loop-phase-d-deviation-ledger-2026-09-29.md` 的 PD-H1..H9。优先 H1（帽的洞）。把活体 `v13_claim` 纳入帽，必须另写计划。其余条目维持台账，直到那份计划逐条改它们的状态。

活体分裂是实的。`v13/fanout/v13_fanout.sql:266` 的 `v13_claim(p_worker text, p_lease_ms integer)` 是领用函数。`v13/fair_claim/v13_fair_claim.sql:421` 的 `v13_claim_fair` 才取 `pg_advisory_xact_lock(13002, 1)` 并读 `global_concurrency`。同文件 `:58` 还断言 `v13_advance` 体内不得出现 `CREATE OR REPLACE FUNCTION public.v13_claim`。`:71` 禁止白名单之外的函数体提到 `13002`/`13003`。台账 PD-H1 写明：活体 `v13_claim` 不取 13002，不读 `global_concurrency`，帽满之后仍可领走。

`v13/fair_claim/v13_fair_claim.sql` 与 `v13/fair_driver/driver.py` 落在三前缀里，字节被 phase D 基线钉住。I4 不能把「修 H1」写成编辑这两个文件的附带改动。

LoopX 的 `postgresql_v0` 不能用来堵这个洞。它不是默认 store，五张表也不含配额、wake 或 outcome_floor。D-A.2 禁止本期启用独立 authority store，也禁止同库共存。

落地之后才能观察到：一份单独计划通过之后，活体 `v13_claim` 与 `v13_claim_fair` 对同一顶帽的行为被写进 gate。在此之前，帽只约束 `v13_claim_fair`。多 goal 公平、全局并发帽、多日 soak 仍是 UA §8 的禁止声称项。Phase D 目录在树上，只表示文件在，不表示验收覆盖了它们。

缺口：调查 §8.4 问要不要重开「禁止 `CREATE OR REPLACE v13_claim`」。没有选择，没有计划。

### 这四项共同依赖

| 路径 | 用在哪一项 |
|---|---|
| `v13/quota_window/v13_quota_window.sql` | I1 的现有 session 局部计数 |
| `v13/should_run/v13_should_run.sql` | I1 门的前身 |
| `v13/govern/v13_govern.sql` | I1 的活体门 v3 与活体 `v13_scheduler_hint`；I3 的节律仍是这个 hint |
| `v13/spawn/v13_spawn.sql` | I1 的席位预算对照；I3 的 `v13_wake_is_satisfied_v1` |
| `v13/attention/v13_attention.sql` | hint 的首份定义，已被 govern 替换 |
| `v13/goal_supervisor/driver.py` | I3 不能顺手改的监督 tick |
| `v13/fair_claim/v13_fair_claim.sql` | I4 的 `v13_claim_fair` 与 13002 |
| `v13/fair_driver/driver.py` | I4 的公平领用驱动，字节钉在 phase D 基线 |

CE 的 auto-wake 文件和 `MCPDomainToolResourceAdmissionController` 是 I3/I 的宿主参照，不是 E 或 S2 的实施材料。LoopX 的文件锁配额、纯 hint、opt-in wake、文件上的 outcome_floor，是 I1/I3 的参照，不是 S2 的动词。

## D-9 是另一条 I，不是 I1–I4 的别名

裁决 D-9 把两个落点「立项排 I 系列」。解锁表写的是：D-6 里程碑之后，才有 judge 载荷合同，然后才是 D-7 的 judge 档和 D-9 的两个落点。前置是 D-6，不是 S1，也不是调查 §8.2 的 I1。

D-6 本身还没做。它要的是带判别标签的消费合同，闭集 `choice|score|noul`，加 `schema_version` 和问题键。选项集绑在冻结的 request 上。阈值留在 SQL。这不是 PC-4，也不是咨询 lane。

D-9 只有两个落点，对应设计 §8.2 的 OQ-J4：

1. **双 Noul 的卡住证据。** 前置是 D-6，外加 UA 收口（UA 现已收口，D-6 未做）。N 和阈值要版本化。双 Noul 只作为判断证据，不直接变成执行权。
2. **`context_refresh` 的 tier。** 不破坏 tier 单调性、证据保留和输入信任边界。分配器换档不换面。

两条各自要 Fake-provider gate，失败时保守。不得把「更便宜」写成唯一通过标准。

调查 §8.2 的 I1–I4 是配额、lane、wake、公平面。D-9 这条 I 是 judge 载荷落地。裁决记录用了同一个字母，两套编号不是同一张表。不要把双 Noul 写成 I1，也不要把 `context_refresh` tier 写成 I3 或 I4。

## 仍不能当成已经成立

UA 计划 `docs/plans/v13-unattended-continuation-authorization-plan-2026-10-01.md` §8 的禁止清单对这四步仍然有效。授权脚本退出 0 只覆盖：单 goal、DB owner/superuser、Fake 夹具、轮数上界 2、无真实 provider；人不回答时保持 waiting 且不 skip。下面这些不能由 S1、S2、E 计划或 I 的存在改成已成立：

- 人可以离开生产终端。没有守护进程，没有唤醒闭环，轮数上界是 2，human 挂起只是报告。
- 产品角色或 EXECUTE 已经分开。夹具仍是超级用户。
- 真实 provider、`V13_REAL_PROVIDER_AUTHORIZATION`、任何网络调用。
- PC-4、goal 级配额、无人值守多 spawn 预算。
- V11 已读、auto-wake 已闭合、wake 已被消费。
- 多 goal 公平、全局并发帽、多日 soak。
- 无人值守 skip，无人值守 `plan_commit`。
- unknown / cancel / stale 墙已经被 `v13_advance` 消化。
- exactly-once 通知、outbox、送达保证。
- 现有 `goal_supervisor` gate 是 `exit_0`。§9.2 记录它在 74 checks 之后仍发出 `v13: supervisor: ask_user`。
- 把 `SUPERVISOR_MAX_TICKS = 2` 读成运行时长达标。
- 授权脚本成功等于生产可用。

§9.2 只作为边界：`accept_progress_second_round_quiet` 的停止原因保持 `human_pending`（human 原因 `low_intent_confidence`，status 仍 `ready`）。要把它变成 `stable_waiting`，就得改 `v13_advance` 或 `v13/loop_driver/driver.py` 的 `_snap_with`。这两处都不属于 S1、S2、E1–E3、I1–I4。

另外这几句也不成立：

- S1 已经登记了四行工具。设计 §5 只给一行；另外三行是 S2。
- 把 `spawn_subsession.enabled` 维持为 true 算作 S1 的功能交付。
- E 计划写完等于外部执行者可以连上，或 CE 已经在投影 Postgres。
- LoopX 的 should-run、文件锁配额、opt-in scheduler 可以在 I1/I3 之前充当 v13 的权威。
- `postgresql_v0` 的五张表已经包含配额、wake 或 outcome_floor。它们没有。
- D-9 的双 Noul 或 `context_refresh` tier 是 I1–I4 的另一套叫法。
