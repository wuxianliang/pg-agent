# v13 agent 控制的极简形态（agent as controller 的最小落地形态）

> 日期：2026-10-02。状态：设计稿——只写文书，零代码改动，不 commit。
> 回答三个问题：三谱系控制原语能不能统一、v13 为什么「交付了全部动词却没有一个 agent 在
> 驱动 loop」、最小落地形态是什么。
> 输入：盘点卷宗 `prompt-exports/v13-control-inventory-2026-10-02.md`（下称「盘点」）、
> 实测 drill `prompt-exports/rp-goal-e2e-drills-2026-10-02.md`（下称「drill」）、
> 谱系调查 `docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md`（下称「谱系」）、
> 迁移调查 `docs/analysis/v13-control-plane-migration-2026-09-25.md`（下称「迁移」）、
> R2 终裁 `docs/reviews/v13-control-plane-oracle-r2-2026-09-21.md`（§0/§1–§3/§5）、
> F/L 对照 `docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md`（下称「parity」）、
> 无人值守计划 `docs/plans/v13-unattended-continuation-authorization-plan-2026-10-01.md`
> （下称「UA 计划」）、本会话 RP-CE 控制面实测（2026-10-02，§1.3）。
> 锚点抽查见 §1.4：6 处，5 处确认，1 处勘误（勘误影响 §2/§3/§7 三处表述，已就地修正）。

## 0. 背景与问题重述

用户卡点的转译：RP-CE 里一个 orchestrator 会话能用五原语派发子 agent、应答权限、改工具面、
回收会话；LoopX 用一套文件控制面让 goal 活过任何一次执行；连 pi 都能用一个进程 + 一份
session JSONL 构成完整控制环。而 v13 交付了 39 个 stage（`v13/load.py:17-57` 的
`SQL_LOAD_ORDER`，`STAGE_THROUGH :59-99`；覆盖矩阵文书停在 29，代码已到 39——盘点「前提
修正」）、全套控制动词、13 组 gate 全绿，却**没有任何一个运行时里「驱动器本身是一个 agent
turn、把控制动词当工具调」**（盘点 §4）。全部驱动器是 Python 进程：gate 夹具、LoopDriver
（`v13/loop_driver/driver.py:118`，17 个允许动词钉在 `ALLOWED_CONTROL_SQL` `:31`）、
GoalSupervisor.tick（`v13/goal_supervisor/driver.py:174`，MAX_TICKS=2）、fair_driver、
RealChain（`v13/real_chain/chain.py:77`，唯一跑通「开环→spawn→子读→归档」全序）与
demo 驱动。

由此三问：**（Q1）** pi / RP-CE / LoopX 的控制原语能不能统一成一个东西，v13 缺的是不是
这个东西？**（Q2）** 如果动词层早已交付，为什么五年——不，四个 stage 世代过去了，agent
作为控制者这一格仍然是空白？**（Q3）** 补上这一格的最小形态是什么，能不能零新表零新列？
§2 给三条裁决，§3 给设计，§4–§7 给对照、分期、负面清单与开放问题。

## 1. 三面实测证据摘要

### 1.1 LoopX + pi drill（~/rp-goal-e2e，2026-10-02）

**loopx 六层文件控制面，哪些是真账本、哪些是即席投影。** 真账本（有独立写路径、mtime 可
指认）：registry（登记命令写，本次未动）、registry 全局镜像（`refresh_state` 写）、goalState
（`todo add/claim/complete` 写 checkbox 与注释）、runHistory（`refresh_state` 写，本次未
追加）、runLog/rollout（`quota should-run`、todo 三动词、`evidence-log` 追加；`task-lease`
不写）。投影（读时计算、无落盘）：attention 队列（goal state 开 user todo + 最新 run 的
recommended_action）、quota（无 slot 账本文件，`should-run` 现算并只追加 `appended:false`
的决策回执，扣槽是另一个默认 dry-run 的动词 `spend-slot`）。lease 是六层之外的第三类：
带 version 的硬租约 JSON + renew/release 回执，不进 goal state 也不进 rollout。

**todo / lease / quota 三分离，且认领自身再拆两层。** 审批在 goal state 的 user gate
（`decision-outcome approve` 才消耗权威，本次未碰）；资格是 `should-run` 只读裁决（不带
`--agent-id` 时停在身份升级，带了才到 operator_gate；ready-score 与 diagnose 内部重跑的
是无 agent 的 should-run，与带 agent 的裁决**不一致**——同一投影两次读出两个答案，即席
性的直接证据）；扣减本次为零（`spent_slots` 恒 0）；认领 = `todo claim`（软所有权，写
`claimed_by`）+ `task-lease acquire`（硬租约，renew 走 CAS `--expected-version`，release
改 status 不 bump version）；`complete` 不要求租约仍 active——release 之后照样结案。

**pi 的 turn/session 语义。** 一个用户 prompt ≠ 一条 assistant 消息：`--mode json` 里
`turn_start…turn_end` 包住的是「无工具回合」；有工具的回合要在 session JSONL 里看多条
assistant（每条带 toolCall + toolResult）。durable 只有 `~/.pi/agent/sessions/<编码
cwd>/<ts>_<id>.jsonl`（`--continue` 续写同一份、`--no-session` 只上 stdout）；工具执行改
的是工作区，session 只留 toolResult 文本；**没有 cancel 开关**——停一次 `-p` 就是进程
结束，JSONL 留着。

**读法**：LoopX 的「控制」= 把一次 CLI 调用拆到不同文件写，其中约一半（attention/quota）
根本不落盘；pi 的控制面 = 进程边界 + 一份 append-only 日志。两者的动词都不需要 v13 没有
的机器（§2 裁决一）。

### 1.2 v13/v15 盘点卷宗

39 stage 全景与动词锚点表见盘点 §1–§2（control 17–20 四 stage 动词选列 + acl/observe/
handoff/govern/quota/should_run/attention/plan/child 各追加层）。与本题直接相关的四个
事实：

1. **极小 loop 的形状**：一个 turn = 一个 effect + 一次 advance；`v13_advance(p_sid,
   p_snap)` 返回 `progressed|waiting|terminal|stale` 闭集（`v13/loop/advance.sql:196`
   签名，§1.4 已抽查；活体为 `SQL_LOAD_ORDER` 末次换体，parity 文头口径）；收尾路由
   `v13_claim`（`v13/fanout/v13_fanout.sql:266`）领 ready→事务外 IO→`v13_complete`→
   同事务再 advance。
2. **actor 合同已在**：stage 23 `v13_control_authorized(p_actor, p_target)`
   （`v13/acl/v13_acl.sql:90`，§1.4 已抽查）+ `v13_observe(actor,ids[])`
   （`v13/observe/v13_observe.sql:43`）+ `v13_session_log`（`:130`）。parity Phase B
   注记：六动词以 `SET ROLE v13_route` 走通，「合同已证明，仓库驱动器未在 agent 路径传
   actor，未交付」。
3. **v15 是另一套语言面**（13 stage、`v15/` 全树 `v13_` 引用数 = 0）：不是 v13 loop 的
   最新形态，是独立设计线（盘点 §3）。
4. **五条卡点**（盘点 §5 末）：无 agent 自己的调用面；驱动环不是 agent turn；子→父回执流
   与 cleanup 缺失；长跑无驻留；v15↔v13 无桥。

### 1.3 RP-CE 控制面实测（2026-10-02，本会话第一手）

本 orchestrator 会话在 RP-CE 里实跑五原语：`agent_run start`（3 个并行子 agent）、
`wait`（first-of-N 竞速）、`respond`（权限应答，accept / accept_for_session / decline）、
`steer`（中途改子 agent 工具面）、`agent_manage get_log`（抽完整转录）、
`cleanup_sessions`（删会话）。机制要点：

- **(i) 参数化 Bash 命令的权限面 fail-closed，且批准不粘住**：同一命令的批准 accept 后
  下一次仍要再批，形成批准环；控制者必须保姆式逐次应答，或 steer 子 agent 绕开该命令。
- **(ii)** `get_log` 可取完整忠实转录（含工具调用与结果）。
- **(iii)** 会话持久化在 app 内、可事后清理。
- **(iv)** 一个「review 委托」从派发到回收约 2 分钟。

**印证**：RP-CE 的审批是「交互式权限面」——interaction broker + 精确 interaction_id +
进程内 epoch，回答必须来自一个活着的对话端。v13 已裁的审批是「数据 + 有界动词」：
`wait_reason=approval` + 恰一 human effect + 六参 `v13_complete`（C4/C5 在函数体内执法）。
后者对无人值守严格更优：应答可以是**另一个 agent turn 的一次库内写**，不需要任何进程
活着等交互。（§2 裁决一、§3.1 agentctl_answer 的直接依据。）

### 1.4 锚点抽查与勘误

对盘点卷宗的 file:line 抽查 6 处（`read_file` + `git blame`）：

| 锚点 | 结果 |
|---|---|
| `v13/loop/advance.sql:196` `v13_advance(p_sid uuid, p_snap jsonb) RETURNS text` | ✅ 确认 |
| `v13/loop_driver/driver.py:31` `ALLOWED_CONTROL_SQL` 17 动词 | ✅ 确认（逐个数过，17 项） |
| `v13/schema/v13_core.sql:96` `CREATE TABLE effects` | ✅ 确认（core 期 kind CHECK 为五值，`harness` 第六值由后续 stage 换体加入，与盘点一致） |
| `v13/observe/v13_observe.sql:43` / `:130` | ✅ 确认 |
| `v13/acl/v13_acl.sql:90` `v13_control_authorized` | ✅ 确认 |
| `v13/spawn/v13_spawn.sql:1757` spawn_subsession 行「enabled=false，R6 残留」 | ❌ **勘误**：行号对，值错——活体是 `enabled=true` |

**勘误详情**：`git blame -L 1757,1760` 显示该 INSERT 自出生提交 `af5950f`（stage 18，
2026-09-26）起就是 `'{}'::jsonb, true`；全树无任何 SQL stage 对它做 `UPDATE tools SET
enabled=false`（只有 seam/read_tools/pi_parity/pi_ports 四组**测试夹具**在运行时临时禁用
并注明「下次 setup_db 恢复」）；catalog stage gate 反向断言 `P6 spawn_subsession
enabled is True`（`v13/catalog/test_catalog.py:158-159`）。parity §6 R6 行「`spawn_subsession`
行保持 `enabled=false`」与其引用的台账 F22 原文自相矛盾——台账 F22
（`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md:99`）写的是「目录行
enabled=**true** 时 `v13_parse` 会被拒」，即当年真问题是 catalog 谓词无具名例外，该缝已
由 catalog stage（D14/R5/R7/R9–R12 裁决链）关闭。盘点沿用了 parity R6 的错误表述。
**影响**：裁决三 dispatch 项的「enabled 翻 true」实为 no-op——行已在且已可用；§7 开放
问题 2 相应改写为「勘误确认 + 台账/parity 表述修正」。

## 2. 裁决

### 裁决一（统一性）：控制原语可以统一，且统一发生在两个面上，v13 已经做完较难的一个

**数据面（状态与动词）——已统一，无需新东西。** 三谱系的持久状态是同一物件的三种介质：
pi 的 session JSONL、RP-CE 的 session JSON + epoch 序列、LoopX 的六层文件目录，在 v13 里
都是 `sessions`（`:12`）/`events`（`:28`）/`effects`（`:96`）三表 + 39 stage 动词层
（`v13_append_event` `v13/schema/v13_core.sql:62` 是唯一事件写入口）。drill §1.1 是新
证据：LoopX 六层里真账本只有 registry/goalState/runHistory/runLog 四层，attention 与
quota 连文件都不是；pi 的 durable 全部内容是一份 JSONL。parity 的「一模一样 = 0」不是
反证——17（RP-CE）+13（LoopX）条「改变」桶证明的是**换体**而非缺机器：核心意图留在
函数里，失败模式按 v13 的 RAISE/`replay`/`stale` 闭集重铸（parity §0 结论 1–3）。

**角色面（谁持有 turn 边界）——统一公式 =「turn 边界持有者 + 四动词」。** 三谱系在此
分岔：pi = **进程内持有**（session JSONL + CLI 标志即全部控制面，无 cancel，进程死即
turn 死）；RP-CE = **委托给 Domain Runtime**（五原语盖在 provider 进程上，liveness 靠
单调序列，M5「唯一生命周期 authority」）；LoopX = **完全不持有**（纯协议：宿主说 CLI
方言，LoopX 只在 loop 外围生产/验证控制面上下文，adapter 三档里 v13 对应的恰恰是它不管
的那档）。v13 把 turn 边界放在 **SQL（`v13_advance`）**——三谱系中最强持有位：effect
创建即冻结、claim 走 fence、complete 走 CAS、崩溃留墙，**任何角色的任何驱动都以同一个
函数复核边界，进程死了边界还在**。角色面的统一因此不是「再写一个抽象层」，而是：turn
边界持有者（v13 SQL）+ 四动词（观察/注入/应答/取消，谱系 §2 已证三谱系每层对下层只用
这四个的变体）。外部 harness 一律 wrapper 档（R2 §2.2 路径 A 的立场、迁移 §2.6「主档」）。

**「不能一比一理解」的部分不是原语，是 harness 的会话管理语义。** parity 完全没实现
桶里真正无对应物的（F5/F8/F16/F19/F21/F24/F25/F26/F30 与 L1–L7 等 28 条）几乎全是
**进程内机器**：TTL 摘记录、冷恢复、审批经纪人、shutdown drain、oversight send 账本。
它们的 v13 对应物是行 + 谓词的映射原则（迁移 §2.4 表）：cancel = 停会话（`v13_cancel`，
不删行）；dormant = `wait_reason ∈ {evidence,quota}` + `not_before`（wake 四变体
`v13_wake_is_satisfied_v1`，oneOf event/not_before/artifact/children_terminal）；
resume = wake 满足后同 session 新 effect_id（A15 续跑）；cleanup = `v13_closeout`
（收据 + 终态，不删行）。**全落已有行，不建新机器。** F19 的「删会话」在 v13 是原则
分歧不是缺口：行是真相，删行 = 销真相（迁移 §2.2「墓碑删除不迁」）。

### 裁决二（卡住根因）：不缺规格、不缺动词，缺一个从未被 gate 要求过的角色反转

盘点 §4 的结构性事实：agent（LLM）在 v13 只生产 judgment / harness_result，从不选动词；
动词由驱动器按 `ALLOWED_CONTROL_SQL` 闭集调用。**修正一处**（§1.4 勘误后）：
`spawn_subsession` 是登记且 enabled 的 sql 工具行，advance 的 spawn 臂消费模型 tool_calls
（`v13/fanout/v13_fanout.sql:563-580` 一类活体），所以「派发」这一动词其实已经
agent-可选——R2 §2.3 路径 A 设计的就是这条路，gate 也覆盖。真正从无 agent 路径的是
**observe / steer / answer / cancel 四个**，以及把四者串成控制环的「controller 会话」。
主命题不变，且更精确了：

**为什么没人建？因为规格链精确交付了动词层与矩阵，但没有任何 gate 写着「一个 agent
turn 以工具调用形态驱动这些动词」。** R2/R3 裁决链的主语始终是「SQL 合同在 `SET ROLE`
下成立」：stage 23 证明 actor 亲缘合同、stage 24–25 证明 observe/session_log/handoff
合同、Phase C 证明 should_run/hint/stop——每一份收尾工件都如实写着「合同已证明，驱动器
未交付」（parity Phase B/C 注记原文）。gate 绿 = 合同绿；agent 作为控制者这一格从未进入
任何断言，所以四个 stage 世代没人填它。文档严格性不是错，是覆盖面恰好在这里留白。
对照组：RP-CE 的编排干脆是提示词——「LLM 即编排器，工具面就是那组控制动词」（谱系
§1.2 `rp-orchestrate`）；v13 缺的不是引擎，是工具面的这一侧接线。

### 裁决三（极简形态 = 最小新增面）

1. **一个工具族**：在既有 `tools` 表登记 `v13_agentctl` 族（kind=sql）——observe /
   steer / answer / cancel 四个新行 + dispatch 复用既有 `spawn_subsession` 行（勘误后：
   零翻转）。零新表零新列（R1.1 / R2 §0 纪律内）。
2. **一个控制者会话模式**：controller session 就是一个普通会话，其 effects 路由到上述
   工具行；B1 出口机的语义留 SQL 侧（四值 result_kind + closeout 前置，已有）；Python
   LoopDriver 在 controller 路径降级为 executor-of-record（claim→事务外 IO→complete），
   即 R2 已裁的 wrapper 档。不建第二推进函数。
3. **一个 gate**：新 stage 只追加 `SQL_LOAD_ORDER`；FakeLLM 发出工具调用序列，跑
   「spawn 子会话→observe→steer→answer 审批→cancel→closeout」全链，断言四值
   result_kind 与逐子回执；不变量 4 不破（FakeLLM/FakeTool，无网络）。
4. **长跑驻留：不建新调度。** goal 行 + `v13_should_run` 三前缀门 + `v13_scheduler_hint`
   是 tick 源（stage 26/28–29 已交付）；UA 计划需要的是拍板执行不是重设计——读后判断
   它与裁决三**正交**（它授权的是 GoalSupervisor 有界 2 轮循环的 exit 0 验收，不建
   controller 会话、不碰 tools 表），唯一交互点是 `load.py` 追加时序与它的冻结中心
   （§7 开放问题 1）。
5. **v15 桥不做**：与本题正交。v13 自身 loop 内暴露动词是最短路径；v15 `jaz.bind_tool`
   闭集（`v15/tools/v15_tools.sql:221`）以后可挂同一族动词，属后续项。

## 3. 极简形态设计

### 3.1 agentctl 工具族：tools 行落点草案

新 stage `v13/agentctl/v13_agentctl.sql`（编号 40，只追加 `SQL_LOAD_ORDER` 与
`STAGE_THROUGH`）。tools 行五条（列形状沿既有 INSERT：name/description/kind/handler/
param_spec/enabled）：

| tool 名 | kind | handler（底层动词） | param_spec 草案 | 读写 | 备注 |
|---|---|---|---|---|---|
| `agentctl_observe` | sql | `v13_agentctl_observe`（组合 `v13_observe` + `v13_scheduler_hint` + `v13_child_pointer` 读） | `{"ids":{"question":"Which sessions?","stated":"uuid[]","options":{}},"hint":{"question":"Include scheduler hint?","stated":"bool","options":{"yes":"…","no":"…"}}}` | 只读（STABLE） | 不触发 VOLATILE 例外——catalog 只拒 VOLATILE，STABLE sql 工具是常态（`session_stats` 先例） |
| `agentctl_steer` | sql | `v13_agentctl_steer`（`v13_append_event(target, 'steer/injected', …)`；正文键集 = §7 开放问题 3） | `{"target":{"…":"uuid"},"text":{"…":"str ≤1024"}}` | 写 events | VOLATILE，具名例外扩员（见下） |
| `agentctl_answer` | sql | `v13_agentctl_answer`（体内先 `v13_control_authorized`，再转发 stage 23 六参 complete actor 重载） | `{"target":{"…":"uuid"},"interaction_ref":{"…":"str"},"response":{"…":"str"}}`（answers/skip 通道沿 D6 v1） | 写 effects/events | C4/C5 由 complete 体内执法，本函数零结算逻辑 |
| `agentctl_cancel` | sql | `v13_agentctl_cancel`（`v13_control_authorized` + 两参 `v13_cancel` actor 重载） | `{"target":{"…":"uuid"}}` | 写 events | 粘性 cancel、不改 unknown（A18） |
| （dispatch） | sql | `v13_spawn_subsession`（**复用既有行**，`v13_spawn.sql:1757`，enabled=true） | 走 harness/llm result 的 tool_calls 通道（`{task, tool_call_id}`，spawn:106-129） | 写 sessions/events | 不新增行；模型 tool_calls → advance spawn 臂同事务批量建子（R2 §2.3 路径 A） |

**两条消费通道，都已活体存在**：observe/steer/answer/cancel 走「询问→sql 快路」——
param_spec 非空使四行进入 controller 会话的 judgment envelope（`v13/envelope/
v13_envelope.sql:422-426` 的 tools_catalog 取 enabled 且 kind∈{sql,tool} 行），FakeLLM
答 tool_action → 路由 action=sql → advance 的 sql 分派臂读 tools_catalog（kind=sql 且
enabled，`v13/control/v13_control.sql:1441-1446` 一类活体）同事务执行 handler，回执 =
effect 行（kind=tool）+ `tool/result` 事件（R2 §2.4「库内动作的回执是事件+行」）。
dispatch 走「tool_calls→spawn 臂」：harness/llm result 的 `tool_calls` 冻结后下一格
advance 批量建 N 子（`v13/fanout/v13_fanout.sql:563-580`）。**本设计不新增第三条通道。**

**actor 授权接线（stage 23 合同的直接引用）**：sql 工具 handler 签名 `(p_sid uuid,
p_spec jsonb)→jsonb`——`p_sid` 是**当前会话**，天然就是调用者身份。三个写动词体内第一
步 `v13_control_authorized(p_sid, p_target)`（`v13/acl/v13_acl.sql:90`，直接亲缘校验；
operator 例外沿台账 C15 活体口径）。controller 对非子孙 target 一律拒。零新参数面、零新
角色。

**VOLATILE 具名例外扩员（steer/answer/cancel 三员）**：沿 `v13_spawn_subsession` 同款
纪律——`SECURITY DEFINER SET search_path = pg_catalog, public`、属主 = 专用 NOLOGIN
控制角色、`REVOKE PUBLIC` 后仅授控制角色、签名 `(uuid,jsonb)→jsonb`、prosrc 无 IO 通道；
扩员 = 给 `v13_named_sql_writer`（`v13/spawn/v13_spawn.sql:42-49`，单源 CASE，现仅一员）
及配套谓词加臂 + 本设计文书即「设计修订」那一半 + 部署 gate 同发（R2 §2.2 扩员程序；
禁止 `UPDATE tools` 扩员）。write_targets 声明：steer→`{events}`；answer→
`{effects,events}`；cancel→`{effects,events}`；`mutating=false`（库内写，崩溃即回滚，
与 spawn 同语义）。**张力**：这会是具名闭集的第 2–4 次扩员，触碰 R2 §7 gpt 少数意见的
复访触发条件（「第三次扩员诉求 → spawn 档位重开」）——列入 §7 开放问题 4。

**controller 会话模式**：无新列、无新枚举。controller = 普通会话（`v13_open_session`
出生，D4 已裁入口）+ 其监督目标由子会话亲缘表达（`parent_session_id`）。它与普通会话的
全部差别是**策略数据**：版本化策略行让它的工作面含 agentctl 四行（param_spec 非空即
入 envelope），不改任何函数。

### 3.2 controller 会话的 effect 流（时序文字版）

```
tick 源：scheduler_hint（stage 28）/ 人工 / GoalSupervisor（stage 38，不改制）
  │
  ▼
① v13_advance(controller_sid, snap)          ── SQL 侧，唯一推进函数
     路由=llm；request 冻结，含 agentctl 工具面（envelope tools_catalog）
  │
  ▼
② executor-of-record（Python，降级档）claim llm effect
     事务外 Fake/真实 provider 调用（不变量 3/4：锁内零外部 IO）
  │
  ▼
③ v13_complete(succeeded, harness_result{result_kind, tool_calls})
     四值 result_kind = {progress|finish|wait|reject}（A15 权威键）
  │
  ▼
④ 下一格 v13_advance：识别本 turn 的动词选择
     ├─ tool_call{spawn_subsession} ──→ spawn 臂：同事务 v13_spawn_subsession
     │     建 N 子（forked/child-created 回执、席位预算、两参咨询锁）
     ├─ tool_action{agentctl_observe} ──→ sql 快路：同事务读投影，tool/result 回执
     ├─ tool_action{agentctl_steer}   ──→ sql 快路：target 会话 steer/injected 事件
     │     → target 的 max_event_seq 前推 → 在途 advance 步 0 返 stale（R11 覆写点）
     ├─ tool_action{agentctl_answer}  ──→ sql 快路：authorized → 六参 complete
     │     消费 target 恰一 pending human → target 续跑新 effect_id（审批两段）
     └─ tool_action{agentctl_cancel}  ──→ sql 快路：authorized → v13_cancel
           → target 的 required 档 worker complete(cancelled)；unknown 不被掩埋
  │
  ▼
⑤ 子会话推进：同一台 advance 机器（B1 出口语义在 SQL：waiting/terminal/closeout 前置）
     子 finish → v13_closeout（三终结事件 + 收据，与终态/预算终态同事务）
  │
  ▼
⑥ 子齐父未验收 → v13_recover_idle / 下一次 tick 把 controller 扫进验收臂
     controller 自身 finish → 同一 closeout 机器封账
```

要点：②是 Python 仅存的职责（R2 wrapper 档）；①③④⑤⑥全部在 SQL；controller 自身被
人审批时（wait_reason=approval），应答方是上层人或另一个 controller——同一动词，递归
闭合。B1 出口机的 Python 实现（`decide_exit` `driver.py:95`）不在 controller 路径上，
其既有调用方（RealChain 等）不受影响。

### 3.3 gate 断言清单草案

新 gate：`uv run python v13/agentctl/test_agentctl.py`（独立脚本、自建库、FakeLLM/
FakeTool、退出码 0 = 通过；同 stage 全部 gate + 此前 1–39 回归）。

| 断言名 | 内容 |
|---|---|
| `actl_catalog_rows` | 四行 kind=sql、enabled、param_spec 形状；`spawn_subsession` 行未被改动（enabled 仍 true） |
| `actl_guard_closed` | 名单外 VOLATILE sql 工具仍被 catalog 拒（沿 G-sql-write-closed）；三新员过深检（DEFINER/search_path/属主/REVOKE/无 IO 通道） |
| `actl_actor_gate` | 非 authorized（非直接亲缘）的 steer/answer/cancel 全拒且零写；controller 对兄弟/祖先 target 拒 |
| `actl_chain_full` | FakeLLM 脚本序列 spawn(2 子)→observe→steer→answer→cancel→closeout：四值 result_kind 逐 turn 断言；逐子回执（forked / child-created / closeout 收据）齐 |
| `actl_approval_two_phase` | answer 错 interaction_ref RAISE 且消息含 current（沿 C4）；答对则恰消费一个 human、target 新 effect_id、全程 status 无审批词 |
| `actl_steer_watermark` | steer 后在途 advance 返 stale；claimed 期间 request 不变（R1.9） |
| `actl_cancel_sticky` | required 档收到 cancel 后 settle cancelled；unknown 不被 cancel 改写 |
| `actl_no_io` | gate 全程无网络套接字、无真实 provider（不变量 4）；锁内零外部 IO |
| `actl_driver_demoted` | controller 路径的 Python 侧调用面 ⊆ {claim, complete, provider 调用}；无 decide_exit 参与（源码级断言，沿 UA 计划 AST 扫描先例） |

## 4. 与既有裁决链一致性对照表

| 本设计条目 | 对应条文 / F·L 编号 |
|---|---|
| agentctl 四行 kind=sql、库内零外部 IO | R2 §2.1（A17 sql 档教条：默认只读 + 具名写允许名单）；谱系 §3.2 |
| 三员 VOLATILE 具名例外扩员 | R2 §2.2 扩员程序（guard 源码 + 设计修订 + gate 同发）；张力 = R2 §7 gpt 复访触发（§7 开放问题 4） |
| dispatch 复用 spawn_subsession + tool_calls 通道 | R2 §2.3 路径 A（complete→下一格 advance 同事务批量建子）；parity F1/F6（改变桶）；G-spawn-fanout 既有 |
| answer = 六参 complete + 恰一 human | R2 §1.2（A15 审批两段、`wait_reason=approval` normative）；R3 D6（v1 载荷 `interaction_ref`+`response`+`answers`+`skip`）；parity F11/F27（改变桶）；stage 23 actor 重载（parity Phase B F17 注记——本设计即「驱动器接线」那一步） |
| steer 落 R11 request 覆写点 | R1.9 + R2 §1.2；parity F2（改变桶）；R11 残留（parity §6：正文未写——本文 §3.1 补的就是正文，键集待裁） |
| steer/injected 事件 | ch01 已登记、代码零生产者（迁移 §2.1）；本设计补首个生产者，事件 type 零 DDL（core:37 开放词表） |
| cancel = 粘性 v13_cancel | R2 A18（interruptible 三档、核心不杀进程、mutating 中断→unknown）；parity F3/F9（改变桶） |
| observe = 读行 + hint 投影 | 迁移 §2.2 poll 行（STABLE 投影、不建快照表）；parity F7/F8/F18（F8/F18 已由 stage 24 补入改变桶注记） |
| controller 会话 effects 路由 + 唯一推进 | 谱系 §3.2（parse+advance 是唯一推进函数）；v13 不变量 3/4 |
| LoopDriver 降级 executor-of-record | 迁移 §2.6 wrapper 主档；谱系 §4（五原语 = 已有动词换名） |
| B1 出口语义留 SQL | R2 §0 共识（三个推进来源语义相同）；「不建 `v13_agent_run` 第二推进函数」= 迁移 §0 明确不做 |
| 零新表零新列 | R1.1 / R2 §0 |
| 不搬 LoopX 26 表、不加 epoch 列、decisions.epoch 不复用 | 迁移 §0 / §2.4 / §3（同名警告） |
| 长跑驻留 = goal 行 + should_run 三前缀门 + hint | parity Phase C（L26/L21/L5 已补注记；「pg_cron 是扫地僧不是节拍器」）；不建新调度 = 迁移 §2.6 |
| dormant/resume/cleanup 映射 | 迁移 §2.4 投影读法表；F16/F24/F25/F26 保持「已裁不建」 |
| v15 桥不做 | 盘点 §3（v15 零 v13_ 引用；`v15/tools/v15_tools.sql:221` bind_tool 为后续挂点） |
| stage 1–16 字节冻结 | 迁移 §5（后 stage 换体不改前 stage 文件；新 SQL 只追加 `SQL_LOAD_ORDER`） |

## 5. 实施分期建议（最小切片；每片 = 一个可跑 gate + 一次提交推送，遵循 AGENTS.md）

- **S1（stage 40a）agentctl-observe**：单行 STABLE 工具 + `actl_catalog_rows`/
  `actl_actor_gate`（读路径）+ `actl_guard_closed`（回归）。零 guard 改动、零 VOLATILE、
  零事件生产——先证「agent turn 以工具调用读控制面」这一最小角色反转。收尾工件：矩阵/
  台账/README + parity R6 勘误行（§7 开放问题 2 的落地）。
- **S2（stage 40b）agentctl-write**：steer/answer/cancel 三行 + `v13_named_sql_writer`
  扩臂（同发部署 gate）+ controller 策略行 + `actl_chain_full`/`actl_approval_two_phase`/
  `actl_steer_watermark`/`actl_cancel_sticky`/`actl_no_io`/`actl_driver_demoted` 全链
  FakeLLM gate + 1–39 全量回归。
- **S3（可选，独立里程碑）executor-of-record 收口**：controller 路径的 Python 侧从
  LoopDriver 抽出最小 claim/IO/complete 三步件（RealChain 复用），`decide_exit` 退出
  controller 路径的断言转正。
- 每片顺序：测试全绿 → 更新收尾工件 → 按路径 `git add` → commit（`v13: <祈使句>`）→
  `git push origin main`。S2 依赖 S1；S3 依赖 S2；S1 可独立先行。

## 6. 明确不做清单（防漂移）

- 不建 `v13_agent_run` 总调度 / 第二推进函数（迁移 §0；谱系 §3.2 反面）。
- 不搬 LoopX 26 表（`quota_spends`/`command_receipts`/`outbox`/`leases`/六层文件面）；
  不建 `quota/spent|voided` 事件（R3b/R3c 已裁禁止）。
- 不给 RP-CE epoch/fencing 加列；`decisions.epoch`（bind 相位）不复用为 run generation
  （迁移 §2.4 同名警告）。
- stage 1–16 字节冻结不动；新 SQL 只追加 `SQL_LOAD_ORDER`（迁移 §5）。
- 不建 dormant/interrupted/TTL/冷恢复/审批经纪人/grant 类/oversight send 账本
  （F16/F20/F21/F24/F25/F26/F30 维持「已裁不建」）。
- 不删会话行：停会话 = cancel，封账 = closeout（F19 原则分歧，不是缺口）。
- 不扩 `effects.kind` 闭集；不新增 route 动作（动作闭集 finish/reject/human/sql/tool/llm，
  R2 §4）；不建第 7 个 action。
- 不做 v15 桥（正交；后续项）。
- 本设计不动 UA 计划的任何条款（其冻结中心保护 `v13/goal_supervisor/**` 与 fair 两目录，
  与 agentctl stage 无文件交集；时序交互见 §7）。

## 7. 开放问题（留给用户拍板）

1. **UA 计划 go/no-go 与时序。** 读后判断：它与裁决三正交（授权 GoalSupervisor 2 轮循环
   exit 0 验收，不建 controller 会话、不碰 tools 表、明确「不给 `load.py` 增键」）。
   唯一交互：UA 计划的冻结中心以 `fb295ac`/`R1` 为基线、追加项锁死 fair_claim；agentctl
   需要追加 stage 40。三个选项：**A** UA 先行、agentctl 后跟（agentctl 提交时同笔放宽
   `r1_load_append_ok` 追加项闭集——既有纪律「未来里程碑同提交改冻结中心」）；**B**
   agentctl 先行（UA §2.2 的预存红集合改变，其计划须复审）；**C** 只做其一。倾向 A
   （UA 是已写好等拍板的验收机器，agentctl 是新设计）。
2. **R6 前提勘误的确认。** 活体证据（§1.4）：`spawn_subsession` 出生即 `enabled=true`
   （`af5950f`），parity §6 R6 行与盘点引用沿用了错误表述。需拍：S1 收尾时同笔修正
   parity R6 行 + 盘点不回改（prompt-exports 是快照）+ 台账加一行勘误记录；
   agentctl 的 dispatch 零 DDL。
3. **steer 正文（R11）的键集。** `steer/injected` 载荷闭集草案：
   `{schema_version:1, text, source_principal}`。分叉点：`source_principal` 是否允许
   `controller`（新值）还是只 `{user, operator}`（沿 `goal/override` 先例「模型不得自
   写」）？若允许 controller，须带会话身份且过 `v13_control_authorized`（§3.1 接线已
   含）；若不允许，controller 的 steer 以 operator 身份注入或本动词只归人。倾向：允许
   `controller` 但亲缘校验为硬前置——否则裁决三的 steer 工具名存实亡。
4. **guard 具名例外的扩员节奏与 D2 复访触发。** 三员一次扩（S2 一笔）还是两批（observe
   先行不需例外，写动词后置）？R2 §7 gpt 复访触发条件「具名闭集出现第三次扩员诉求 →
   spawn 档位重开」会被触碰：需要用户显式签认「agentctl 扩员属 R2 §2.2 设计内用途
   （具名写允许名单正是为此类函数立法），不构成 spawn 档位重开信号」，或先走一次
   复访轮。倾向前者（名单的语义就是「库内写、崩溃即回滚」的目录化，agentctl 三员与
   spawn 同语义），但这是条文级决定，不擅自代裁。
5. **（次级）controller 会话的出生语义。** 是否需要一个专用 `spawn_kind`/策略标记区分
   controller 会话与普通会话（纯投影用途，便于 attention 排序），还是完全靠策略行
   区分？倾向后者（零新标记；attention 的 `lifecycle` 列已够用）。

**已裁（2026-10-08 stage 40 追加，不删上文）。** 五条已被 2026-10-03 裁决覆盖：第 1 条→ D-1（A，UA 先行）；第 2 条→ D-2（确认勘误，本 stage 只追加 R6 勘误）；第 3 条→ D-3（允许 `source_principal=controller`，裁决不等于本 stage 实现，写动词在 stage 41）；第 4 条→ D-4（S1 观察先行，S2 三员同笔）；第 5 条→ D-5（版本化策略行，零新标记；本 stage 不建 `controller` 政策）。

## 8. 增补：Jev 决策层帖子的启示（2026-10-02 同日，主会话补记）

来源：TypeSafe AI《Jev in the Agent Loop: A Complete Guide to Decision-Layer Automation》
（x.com/N01ennn/status/2103542021071978601，主会话读取转述；vendor 内容，数字自评，
参考不进裁决链）。该文把 agent loop 的模型形状行三分：[G] 生成留 frontier LLM、[D] 决策
搬廉价类型化决策模型（Choice/Score/Noul + calibrated confidence）、[C] 硬规则归代码。

### 8.1 印证（v13 已有对应物，零动作）

- [G]/[D]/[C] 三分 ≈ v13 effect 分类：llm 生成 / judge 决策 / SQL 谓词硬规则
  （should_run 三前缀门、quota、席位预算、thresholds）。
- 决策「在 loop 旁边、不进对话」（省 KV cache 重建税；帖子算术：中途降档回档比不降更贵）
  ≈ judge effect 吃 snapshot（`v13_advance(p_sid, p_snap)` 七键探针），judgment 是
  事件+行，不污染目标会话上下文——v13 独立 judgment 行的经济论证。
- 类型化闭集答案 ≈ result_kind 四值（A15）；「模型报信念、代码持阈值」= thresholds 在
  SQL 的既有分离。
- 不确定性升级 ≈ unknown 墙 + `v13_resolve_unknown`（比帖子的 escalate 更严：封锁到
  人裁决，不自动放行）。
- decide≠prove（决定完成与确认完成分离）≈ closeout 计数前置 + artifact 收据 +
  state_hash；LoopX spend_rule 先验证后扣减。
- 动作菜单随状态重建 ≈ envelope tools_catalog 每 turn 从 enabled 行重建（§3.1
  param_spec 门控正是此机制）。

### 8.2 增量（四个吸收点，并入 §7 开放问题族，编号 OQ-J*）

- **OQ-J1 judgment 载荷契约**：judge effect 载荷裁闭集 schema——三原语 Choice（选项+
  逐项概率+confidence）/ Score（rubric 档位+分布）/ Noul（[0,1]）+ 问题键；阈值全留
  SQL。类比 D6 审批载荷闭集的立法方式。零新表零新列，纯载荷契约。
- **OQ-J2 controller 的 system-1 档位**：§3.2 ①「路由=llm」不是唯一档——controller 可
  为 judge 驱动的廉价调度环（SQL + judge），frontier 花费只留给 worker 生成。agentctl
  设计不受冲击，多一档更便宜的实施路径；裁点 = controller 会话策略行选 llm 还是 judge
  作路由 effect（与 §7.5 出生语义同笔拍）。
- **OQ-J3 档位决策时机规则**：模型档位在 request 冻结前由 judge 裁出并绑定，禁会话
  中途降档（降-回升的重读成本吃掉全部节省）；执法点 = request 冻结机制（现成）。
- **OQ-J4 judge 化两落点**：(a) GoalSupervisor.tick 现只有 streak 计数，加「每 N 轮
  progressing/repeating 双 Noul」stuck 检测（帖子的廉价模式）；(b) context_refresh 的
  tier 分配交廉价 judge（逐 chunk 相关性 Score → 不显示/短/长/全文），替代摘要驱动——
  与上下文平面 tier 单调性裁定同构，分配器换档不换面。

### 8.3 红线（不吸收）

- vendor 自评数字（193x/444x 等）不当规范，不进裁决链。
- Jev 是外部 provider：引入即受不变量 4 + 两入口规则约束（事务内零外部 IO）；决策层
  只能是 provider 面的一种，不碰控制面。
- 决策模型也吃 prompt injection（type safety 保证答案形状、不保证推理完整性）——
  judge 输入延续证据纪律，untrusted 内容不得移动裁决。
- 零新原语原则不变：全部映射进 judge effect + SQL 阈值，不给 Jev 开任何新机制。

### 8.4 与既有 Jev 调查的接续（日后深挖的入口）

仓库里已有一层更深的 Jev 调查：`docs/investigations/jev-engineering-overall-design-impact-2026-09-22.md`
（**半成品**：Investigator Findings 完整，Summary/Root Cause/Recommendations/Preventive
Measures 四段全待补）。接续要点：

- 关键事实：v13 §2.2 `pg_typesafe` 封装的就是 TypeSafe 的 Jev（choice/score/noul）——
  OQ-J1 的三原语词汇已在库里，judgment 载荷契约是给既有封装定消费面 schema，不是引
  入新概念。
- 该调查 Findings（:113-233）已裁定：H1a goal 去重=台账增量（spawn 准入一条 SELECT，
  在飞硬拒/历史带水位新鲜度）；H1b 缓存经济学=台账增量（YAGNI 触发器：换模型决策落
  地时补确定性 SQL 函数）；H1c 条件化指令件=装配策略谓词非新 ContextSource；H2
  harness 即工具路由器=部分吸收+显式拒绝（构造参数需生成、按 turn 抽 schema 击穿前缀
  身份等三条理由）。其编号勘误仍有效：下一个可用号 A22（修订）/B19（文档 bug）/E7。
- 同域关系：OQ-J3（档位决策时机）是 H1b「换模型一格」的 gate 化表达；OQ-J2 的
  system-1 controller 与 H2 的「SQL 预筛+判断面终选」同构。日后深挖 Jev 线应先读完
  该 Findings 再动笔；补齐其四段待补结论可作为一个独立小任务（结论多半可从本节与
  上一轮 5 增量级结论合成）。

---

*执笔：主会话（Sonnet 5 1M）。证据等级：§1.1/§1.2 引 drill/盘点卷宗（探针级，锚点抽查
见 §1.4）；§1.3 为本会话第一手实测；§2–§3 为设计判断，每行落点均可指回 R2/R3 条文或
活体锚点；§1.4 勘误有 blame 证据。§8 为主会话同日补记（帖子转述级，未引原文存档）。
未改代码、未 commit。*

**已裁（2026-10-08 stage 40 追加，不删上文）。** §8 的 OQ-J1→D-6，OQ-J2→D-7，OQ-J3→D-8，OQ-J4→D-9。裁决不等于本 stage 实现。2026-10-08 父计划不采用 D-A.2 的 file sink，不否认 2026-10-03 裁决。stage 45 明确不交付。
