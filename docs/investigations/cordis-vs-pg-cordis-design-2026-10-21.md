# Investigation: Cordis vs pg_cordis — 设计思路差异

## Summary

**差异是架构性的，不是成熟度差异。** 两边都以 Postgres 为权威、都拒绝「第二队列」、都不承诺外部副作用 exactly-once——真正分野是**把执行组织在什么东西周围**：

- **pg_cordis** = 可复用的耐久任务底座：执行围绕 `jobs` + claim + **命名步 `s-N` 与持久 checkpoint**，不同 locus 的合格 worker 都能接续；并**设计保留**一个可选的 Cordis fiber/反应性层（L3），其中**工作做完服务仍可 active**（run DONE 但 fiber episode 仍 OPEN）。授权是**逐语句 live grant**，撤销下一语句即生效。
- **v99 插件面** = 有边界的 CE 执行平面：执行围绕 **CE epoch + 冻结的可执行闭包 + 逐 effect 准入**，一个 run 一个受租约约束的 driver；**模型 final 但进程还活着不算正常完成**（须落 closeout intent + shutdown/inspect + 资源义务全解决才封口）。授权在 **epoch 准入时冻结**，撤销只挡新准入，停正在跑的活必须显式 `cancel`。

最干净的判别式是**插件寿命 vs 激活它的工作的寿命**，以及**授权新鲜度（live vs epoch-frozen）**——这两条即使两边把计划中的组件全做完也依然成立。

另外核实出一处**事实错误**：`docs/designs/v8.md:87` 声称核动词「与 pg_cordis 五件套对齐」，但 pg_cordis D4 的五项是 `claim/log checkpoint/sleep/scoped event/任务级 retry`，v8 的是 `claim/checkpoint/yield/wait/sleep`，**仅 3/5 重合**；`v8-revision.md:382` 自己也承认当时已列成八组动词。这是措辞问题，不足以推出协议不兼容。

**若两者要互操作，唯一真正的硬点是授权时机**：同名同 schema 的 export 可以给出相反的授权裁决。共享目录绝不等于共享授权裁决。

## 对比对象（用户已确认）

用户裁决：「我们之前讨论和设计的 Cordis」= **本仓 v99/core 原生多语言 Cordis 插件平面设计**（`.claude/worktrees/v99/docs/designs/v99-core-native-plugin-plane-2026-10-20.md`），**不是**外部任何项目。对比目标 = **本地 pg_cordis**（`/Users/wxl/Projects/zcordis-pgembed/`，Postgres SQL agent 内核）。

要求的角度只有两个：**① 架构与控制流**（谁拥有循环、事务/IO 围栏、状态机形态、崩溃恢复）；**② 取舍与弃用**（各自拒绝/保留/改造了哪些 Cordis 语义）。

## Symptoms

用户问题：「我们之前讨论和设计的 Cordis 和我本地的 pg_cordis 项目的设计思路有什么不同？」

需要先消歧：本机存在至少三个互不相同的 "Cordis" 指称（本次对比只用 D vs C）：

| # | 指称 | 位置 | 性质 | 本次角色 |
|---|------|------|------|----------|
| A | 上游 Cordis 内核 (Koishi) | `/Users/wxl/Projects/deepseek-harness/vendor/cordis` | 官方 JS DI/插件内核 | 语义基准 |
| B | cordis core 设计 (zcordis) | `/Users/wxl/Projects/cordis-db-agent/` | Python/DuckDB 插件生命周期目录 | 旁证对照 |
| C | pg_cordis | `/Users/wxl/Projects/zcordis-pgembed/` | Postgres 内嵌内核 | **对比目标** |
| D | 本仓 v99 插件面 | `.claude/worktrees/v99/docs/designs/` | 「DB 即 harness」 | **我方设计** |

### 关键事实边界

- v99 有**两层**，不可混为一谈：**Phase 0 已实现**（11 表、六 CE 动词、单 run driver lease、T1-before-IO、唯一 T2，Fake-only，gate 绿）；**M1 插件面纯设计**（schema/ABI v2，Oracle 曾判 `Not ready` 且未复审）。
- pg_cordis 同样有两层：**已实现 p21**（`sql/0000`–`0021`，P02–P19，约 226 测试函数）；**Sept-13 重设计是设计基线**（`fibers`/`external_calls`/`spawn_admissions`/`dispatch` 已规定但未落地，`docs/plans/PHASE0A-*` 仍 `draft — pending plan critique`）。
- 上游 Cordis 4.0.0-rc.7 vendored 版带本地加固（`vendor/README.md:40` reentrant disposal 修复），移植判断应对准 vendored 行为而非 pristine upstream。

## Background / Prior Research

### A. 上游 Cordis 内核（语义基准，非对比方）

来源：explore agent 实读 `deepseek-harness/vendor/cordis` + `docs/cordis-primer.md`。

- **内核边界**：约 2.7k LOC 的纯 in-process DI + 插件生命周期 + 事件总线。**没有** IO、持久化、调度、tool/LLM、transport 概念（`vendor/cordis/README.md:3-7,76-87` 明确把 Loader/HMR/timer/logger-console 拆成独立包）。
- **Fiber 状态机**：`PENDING/LOADING/ACTIVE/FAILED/DISPOSED/UNLOADING`（`vendor/cordis/src/fiber.ts:147-154`）。
- **服务注册无覆盖**：`ctx.provide(name, value)` 重复即抛 `service "x" has been registered at <fiber>`（`reflect.ts:277-305`）；「覆盖」只能靠不同 `isolate(name)` label 或 dispose 后重新 provide。
- **dispose 顺序**：`_unload` 反转 disposables（新的先），在 `Promise.all` 下执行 —— 调用*开始*是逆序，但**异步完成无序**，错误被 log 后吞掉（`fiber.ts:675-696`）。即上游**没有事务性卸载**。
- **isolate 是查找作用域，不是安全边界**（`context.ts:121-125`、`reflect.ts:237-243`）。
- **没有全局 shutdown**：root fiber `dispose = () => this.restart()`（`fiber.ts:331`）。
- **HMR 是生态层**（`@cordisjs/plugin-hmr` + Loader + Node loader internals），不在核心内核。
- **最接近「IO 前钩子」的只有 `internal/dispatch`**：在 `EventsService.dispatch()` 里、filter 与 listener 调用*之前*同步发出（`events.ts:165-175,351`）。但它是 `emit`（**不被 await**），只在插件真的 dispatch 非 `internal/` 事件时触发；直接调 service（如 `ctx.llm.complete()`）不经过它。→ **要保证 `dispatch_started` 先落盘，harness 必须 (a) 把所有 IO 挂在 dispatched event 后面并在 `internal/dispatch` observer 里*同步*持久化，或 (b) 直接包住 IO service。异步持久化无法保证先完成。** 这解释了 `v8-revision.md:345` 把「官方 Cordis 能否在外部 IO 前持久化 `dispatch_started`」列为 P0 前置验证的原因。
- 「一切皆插件」是**约定而非内核不变量**：`EventsService`/`LoggerService`/`ReflectService`/`RegistryService` 是在 `Context` 里 eager 构造的，不是挂载的插件（`context.ts:77-81`）。

### B. pg_cordis（对比目标）

来源：explore agent 实读 `/Users/wxl/Projects/zcordis-pgembed`。

- **自身定位**：跑在 `pgembed` 上的 `pg_cordis` 内核 SQL 源（`README.md:3`、`AGENTS.md:7`）。首个产品目标是 **RepoPrompt-CE 类编码 agent**，workspace/Context Builder/selection/worktree/`apply_edits` 都做成插件。
- **循环归属**：`cordis.step_once` 是 PL/pgSQL，**每次 live claim 最多处理一个具名 step `s-N`**（LLM checkpoint 或 mock 调用，然后一个 mock tool observation 或 final），返回 `yield`/`complete`/`fail`（`sql/0005_p05_one_step_driver.sql:69`、`sql/README.md:61`）。`cordis.worker_step` 也是 PL/pgSQL：claim 一个 `cordis.jobs` 行、调一次 P09 in-db queue handler（`sql/0021_p09_in_db_worker.sql:327`）。
- **Python 没有循环**：`pg_cordis_host` 明确「There is no `execute`, `query`, transaction object, HTTP client, worker loop, or host-callable registry」（`docs/host-sql-seam.md:14`），每个 public method 起一个 `psql` 进程（`client.py:478`、`:20`）。
- **五件套（pg_cordis 自己的定义，D4 合同）**：「**五件套进核：claim、log checkpoint、sleep、scoped event、任务级 retry。**」（`docs/decisions/2026-08-23-pending.md:218`、`docs/analysis/2026-08-23-i-architecture-snapshot.md:96`）。注意是 **scoped event 而非 yield/wait**，checkpoint 明确是「log checkpoint / checkpoint ⊂ log」。
- **隔离四缝**：`seam IN ('recall','fold','env_read','tool_dispatch')`（`sql/0020_p08_four_seam_enforcement.sql:14`），对应 `recall_named_corpus`/`fold_slice_messages`/`read_run_env`/`authorize_tool_dispatch`（`:233`、`:447`、`:541`、`:598`）。**grant 每条语句实时读，没有 first-fold 冻结**（`sql/README.md:87`、`slice_live_grants` @ `sql/0007:664`）。
- **三态**：log（真相，append-only）/ projection（派生，永不权威）/ workspace（run 拥有的执行态）。明确**拒绝**「全部状态可从 log 重建」（`docs/designs/2026-09-13-pg-cordis-system-redesign.md:254`、`docs/analysis/2026-08-23-i-architecture-snapshot.md:67-73`）。
- **IO 围栏**：SQL 不能联网；Python client 没有 HTTP client；`cordis.invoke_llm` 是**可替换的 SQL mock hook**，要求 `provider_key = md5(run_id || '/' || step_name)`（`sql/0005:5-67`）；host tool 是 **authorize-only**，`authorize_host_tool` 「returns metadata and never invokes a callable」（`docs/host-sql-seam.md:60`、`client.py:1008-1077`）；**D2 external 执行缝未开**——无 `tool/call→副作用→tool/result` 协议、无宿主执行器、`agent_steps.kind` 枚举里没有 `tool/call`/`tool/result`（`sql/0002:14-27`）。丢响应 = unknown，**绝不自动重试 mutation**（`docs/host-sql-seam.md:74`）。
- **不变量**：L-1 单一队列；L-2 `agent_steps` 唯一历史真相；L-3 **逐语句实时授权**；L-4 D2 边界；L-5 claimed 域 ⊆ artifact 域（`docs/designs/2026-09-13-pg-cordis-system-redesign.md:250`）。I-J1 每行最多一个 live claim、I-J2 旧 token 过不了围栏写、I-J3 状态迁移与 log 审计同事务（`:280`）。
- **血缘**：直接继承上游 **Cordis 论文**（仓内有副本 `docs/A Programming Paradigm for Spatiotemporal Composability.md`，数学设计以它为标尺）与 DSH vendored 源（`vendor/cordis/src/{events,fiber,reflect,registry}.ts`，逐行引用），但明确 DSH「**不能反向成为 pg_cordis 的运行时依赖**」（`docs/designs/2026-09-13-pg-cordis-system-redesign.md:50`）。D8 拒绝 DSH event 兼容层与 `node:vm`。
- ⚠️ **证据注意**：pg_cordis explore agent 读到的是本报告文件（我早先建的存根），所以它「lineage」一节里关于 A/B/C/D 表格的那条引用是**循环证据**，已弃用。其余实读 SQL/docs 的发现不受影响。

### C. 旁证：cordis-db-agent（zcordis 核心设计线）

来源：explore agent 实读 `/Users/wxl/Projects/cordis-db-agent`。用于说明「同一条血缘的另一支怎么选」。

- 自我定位：「DuckDB-backed, Cordis-inspired Python plugin lifecycle catalog」，**not a Cordis port**（`docs/cordis-core-design-v2.md:7`）。
- 采用/拒绝台账（`docs/cordis-core-design-v1.md:60-69`、关键裁决 `:902`）：**采用**「注册是 Fiber-owned effect」「`provide` 重复拒绝」「同步撤回：依赖方在仍能读到 provider 时先 deactivate」「LIFO 逆序 undo」「SQL scope-namespace 隔离」；**拒绝** Context Proxy、per-service `isolate()`/`intercept()`、service replacement/last-writer-wins upsert、async dispose、async effect iterators、Cordis coeffect isolation（realm map per key）。
- 明言「Isolation here means **SQL scope-namespace isolation**, not Cordis per-key isolate」（`:823`）。
- K1 fiber-owned effects / K2 event modes（**deferred**）/ K3 activation effect generation / K4 crash recovery（**Landed, single-process**）/ K5 lease+fencing（paused）/ K6 scope rules（deferred）。跨切不变量 I1–I8（`:238-256`），其中 **I6「Unknown is not success」**、**I7「Honest reversibility」**。
- 无 Postgres/pgembed；纯 Python 3.11 + DuckDB catalog（`cordis_fibers`/`cordis_services`/`cordis_effects`/`cordis_effect_attempts`）。
- **与 pg_cordis 无代码/合同继承证据**：grep `cordis-db-agent`/`zcordis.git` 在 pg_cordis 仓内 0 命中；两者只是 remote 命名都带 `zcordis`。

### D. Context Builder 的初步判定（Phase 2）

Oracle 提出一条**重要修正**：把 v99 说成「driver 拥有循环、SQL 只做准入与结算」**过窄**。v99 的 SQL 本来就承担真实控制迁移 —— model 请求 tool 后由 SQL 建 tool effect、整批结束后由 SQL 建下一个 LLM 调用；driver 无法另起一条 continuation 链。所以 v99 与 pg_cordis 的差别不在「SQL 是否拥有状态机」，而在**步进与外部执行如何被组织**。

反方向也成立：PL/pgSQL 的 `step_once` **不构成自主调度** —— 总有某个东西要在工作可用时再次调用它（P09 的 `worker_step`、未来的 L4 host driver loop）。「Python 没有循环」只说明*已实现*状态下的分工，不证明排他执行所有权。

Oracle 同时指出三类不确定性必须分开：**响应不确定**（DB 是否提交了）、**业务不确定**（外部操作是否发生、结果是什么）、**资源不确定**（进程是否还活着）。replay journal 只能解第一个；process inspect 可能解第三个；**两者都不自动解第二个**。

## Investigator Findings

### 2026-10-21 复核：范围、结论与证据等级

**本次已确认范围**：左侧是本仓 `.claude/worktrees/v99` 内的 **v99/core 原生多语言 Cordis 插件平面设计**；右侧是 `/Users/wxl/Projects/zcordis-pgembed/` 的 **pg_cordis**。不是上游 JS Cordis 与 pg_cordis 的直接比较，也不是 `cordis-db-agent` 的另一套设计。下方历史 Open Questions 中的消歧问题已由本次用户确认解决。本节仅讨论「架构与控制流」「取舍与弃用」。

**主结论**：v99 把 Cordis 的一部分组合语义收进 **CE run + 唯一 driver + 逐 effect 准入/回执/资源义务**；pg_cordis 把 **共享 jobs/claim + 命名步/日志续体** 做成自足内核，再计划叠加可选的 Cordis fiber/反应性运行时。两者都由数据库裁决，外部推进者承担活性；不能概括成「pg_cordis 在 SQL 里自己 while，v99 才有宿主循环」。真正分野是**执行粒度、持续推进责任的契约、失败后允许怎样接续，以及保留多少 Cordis 生命周期语义**。

#### 引用索引与状态口径

以下 `别名:行号` 均指本次直接读取的本地文件；对应源码事实还独立抽查了探针返回的关键代码。行号是 2026-10-21 工作区快照，不是远程 HEAD 或永久版本承诺。

| 别名 | 文件 |
|---|---|
| V99-D | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v99-core-native-plugin-plane-2026-10-20.md` |
| V13-D | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v13-multilingual-plugin-plane-2026-10-20.md` |
| V13-A | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v13-multilingual-plugin-plane-control-annex-2026-10-20.md` |
| V13-P | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v13-multilingual-plugin-plane-plan-2026-10-20.md` |
| PG-R | `/Users/wxl/Projects/zcordis-pgembed/docs/designs/2026-09-13-pg-cordis-system-redesign.md` |
| PG-M | `/Users/wxl/Projects/zcordis-pgembed/docs/designs/2026-09-10-pg-cordis-mathematical-design.md` |
| PG-S | `/Users/wxl/Projects/zcordis-pgembed/docs/analysis/2026-08-23-i-architecture-snapshot.md` |
| PG-H | `/Users/wxl/Projects/zcordis-pgembed/docs/host-sql-seam.md` |

| 对比对象 | 本次核实的实现/设计边界 |
|---|---|
| v99/core **已实现** | Phase0：独立五 SQL 文件、11 表、CE 六动词、run driver lease、effect CAS/pin、原子 receipt T2，以及测试宿主 FakeHost。`v99/core/load.py:6–21`、`v99/core/README.md:9–17,44–58`。README 的 gate 通过记录是既有记录，本次未复跑。 |
| v99 插件平面 **设计** | V99-D:3 原文「**设计稿，尚未实现。**」；:5 还说明旧稿 Oracle 为 **Not ready**，修订稿「尚未再次复审」。Python persistent / Node one-shot / SQL gateway、supervisor journal、cleanup obligations 与生产式连续续租均是 M1 目标，不能拿 Phase0 FakeHost 当完成证明（:35–37,482–485）。 |
| pg_cordis **已实现** | 当前编号 SQL 的实际目录为 `0000–0007,0019,0020,0021`，不是每个中间编号都有文件；最高标记 `p21`。`sql/README.md:39–61,87–89`，`sql/0021_p09_in_db_worker.sql:570–577`。P10 宿主客户端与 P11 交替认领的测试代码也存在，但不等于宿主工具运行时。 |
| pg_cordis **对比用设计基线** | 按本次任务采用 9 月 13 日重设计来比较目标架构；但文件本身仍写「**推荐设计稿（待采纳；未实现）**」（PG-R:5），修订日期为 **2026-09-14**（:4）。因此不把“本次选作基线”写成“仓内文档已正式采纳/实现”。`external_calls`、`spawn_admissions`、fiber/episode、dispatch、维护 loop 等仍列为 absent/specification（:76–84,618–629）。 |

### 一、架构与控制流

#### A1. 谁拥有 loop：不是 SQL while 与 Python while 的二分

**v99（设计）**将三种责任分清：

> 「数据库管理身份与执行资格；受信宿主装载代码；唯一 CE driver 推进工作。……不引入另一套插件 task/run/lease。」—— [V99-D:9](</Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v99-core-native-plugin-plane-2026-10-20.md:9>)

DB 选择 ready 工作、验证准入与结果；driver 持续 acquire/recover/discover/claim/执行/结算；supervisor 只提供进程事实与批准 adapter 执行，不持 DB 凭据、不 claim、不另做自动重执行（V99-D:385–405）。**“唯一”是每 run 一位有效 driver，不是整个部署只能有一个进程。** 同 run 同时至多一个 claimed effect；runtime epoch 是进程身份，不是第二租约（:66–74）。Phase0 已有 run lease/claim/receipt 的实现；独立生产 driver 与插件 supervisor 尚无实现（`v99/core/README.md:46–58,109–111`）。

**pg_cordis（已实现）**同样不是自主循环。`step_once` 在一个 live claim 下处理至多一个 `s-N`，其中包含 LLM checkpoint/mock 和一个 mock 工具观察或 final，然后返回 outcome；它不 claim 下一步，也不负责 HTTP、等待或 job 状态切换（`sql/README.md:61`；`sql/0005_p05_one_step_driver.sql:69–79,634–635`）。`worker_step` 才组合 claim→调用一次 queue handler→映射 yield/complete/fail/wait，但调用后同样返回（`sql/0021_p09_in_db_worker.sql:376–443,444–519`）。下一轮必须由 caller 再次调用并逐轮提交。

> 「There is no `execute`, `query`, transaction object, HTTP client, worker loop, or host-callable registry.」—— [PG-H:14](</Users/wxl/Projects/zcordis-pgembed/docs/host-sql-seam.md:14>)

这句话的范围是 **现有 `CordisHostClient`**，不代表“pg_cordis 设计拒绝一切宿主循环”。重设计 L4 明写「**驱动循环（claim→begin_named_step→handler→结算）内建于此**」（PG-R:190–192）；Phase 0b 还要求宿主 maintenance loop 同批交付、无普通可认领 job 时仍运行（:553–555,619）。库内与宿主执行者共享同一 jobs/claim，而非各建队列（PG-S:87–88）。

**本轴结论**：两边都要外部承担重复调用和维护活性。v99 把**同 run 连续推进者**明确建成受租约约束的 CE 角色；pg_cordis 的核心抽象是**可由不同 locus 接续的一次命名步/claim**，未来循环在 L4，维护另有持续 owner。原 lead 中“pg_cordis Python 没循环，所以 loop 完全归 DB”的推论不成立。

#### A2. 事务与外部 IO：共同边界，相异的原子单元

**pg_cordis p21 的库内路径**：`worker_step` 一次 SQL 调用内 claim、调 handler、写日志并 yield/complete/fail，caller 最后 commit。未捕获的 handler 异常会使整个语句失败，不能把这个库内路径误写成已经跨 HTTP 的 durable 外呼（`sql/0021_p09_in_db_worker.sql:376–430,433–477`；`sql/README.md:89`）。`invoke_llm` 实际只是读取 `jobs.payload.mock_llm.responses[step_name]` 并返回 JSON（`sql/0005_p05_one_step_driver.sql:42–65`）。把它替换成事务中真实 HTTP，不能从现有 mock 正确性推出安全性。

**p21 的宿主路径**是另一种原子边界：

> 「One method = one committed statement. Checkpoint or `emit_step_scoped` must succeed **before** `yield_claim` / `complete_claim` / `fail_claim`.」—— [PG-H:28](</Users/wxl/Projects/zcordis-pgembed/docs/host-sql-seam.md:28>)

一次普通方法启动一次 `psql`；`sleep_claim` 有“探测 + 调用”两个进程的明确例外（PG-H:20,66；`pg_cordis_host/client.py:1148–1187`）。因此 checkpoint 成功、yield 尚未提交时崩溃，是**有历史、job 仍 RUNNING**的合法窗口；接管者读日志判断接续点。客户端没有跨方法事务、没有 heartbeat thread（PG-H:28–38）。

**D2 不是 p21 已实现外呼协议**：P06 有 external 分类，但现有宿主 `authorize_host_tool` 仅返回 descriptor，并拒绝非 `read_only/replayable/none`（`pg_cordis_host/client.py:1019–1077`）。PG-R:76 原文为「**external 执行缝未开**」。重设计才指定：`tool/call` + 执行许可提交后外呼，再以独立事务写 result；无 COMMIT 回执不得外呼（PG-R:282–322）。

**v99（Phase0 基础已实现；插件扩展为设计）**把推进拆成更细的 effect：

> 「外部执行前 T1 COMMIT、控制连接 IDLE；执行后唯一 T2 原子接纳、生成 successors、发布与写 replay journal。」—— [V99-D:69](</Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v99-core-native-plugin-plane-2026-10-20.md:69>)

`accept_receipt` 是结算/后继准入/对话发布的同一事务；Phase0 代码可见 replay-first、CAS 校验与末尾 journal（`v99/core/sql/30_ce.sql:458–503,595–607`）。设计中的模型工具批次也是 LLM effect T2 建各工具 effect，整批完成后再建下一 LLM（V99-D:435–439），而不是以“一次 LLM + tools”为一个 claim 执行单位。长 IO 期间控制连接 IDLE、续租走独立连接（:253–257,387–391）。

两边均不应把“IO 不进事务”误解为“SQL 不能在事务内计算”。pg_cordis 保留库内事务性插件路径（PG-M:1241–1244）；v99 首版 SQL 工具仅为独立连接的 **READ ONLY** 查询，禁止其函数内网络/文件/进程 IO，控制事务不跨该查询（V99-D:251–261）。

**本轴结论**：共同原则是**外部副作用不与数据库提交假装原子**。pg_cordis 以日志 checkpoint + job 转移、未来 D2 call/result 分层接续；v99 以逐 effect 的唯一 T2 同时决定“账是否结清、下一工作是否产生、对话能否发布”。这不是“pg_cordis 已经在 SQL 事务里跑真实 LLM”的对比。

#### A3. 状态机的主角：任务与可选 fiber，还是 CE 与资源义务

| 层面 | pg_cordis | v99 |
|---|---|---|
| 当前主状态机 | **已实现** `jobs`: PENDING/RUNNING/WAITING/SLEEPING/DONE/ERROR；一 run 一行，claim token 决定有效写者（PG-R:262–280；P04 是最终覆盖版）。 | **Phase0 已实现** run/epoch/turn/operation/effect；run 是 CE 生命周期实体，operation 是准入，effect 是副作用账本（`v99/core/README.md:44–48`）。 |
| 插件生命周期 | **设计** L3 可选 fiber: inactive/reloading/active/unloading，另有 retired、fault、episode；普通 run 不经过 L3（PG-R:214–216,350–381）。 | **设计** install、scope snapshot、runtime、refs、cleanup obligations；runtime 为 reserved/starting/ready/stopping/stopped/quarantined/unknown（V99-D:203–214）。不引入另一个插件 task/run/lease（:9,67）。 |
| “工作成功”后 | **设计** L-Finish 可使 run DONE，但成功 fiber 的 episode **仍 OPEN**，服务保持 installed/active，后续依赖变化再 Leave/Unload（PG-R:354,365–371）。 | **设计** ModelFinal 先保存 closeout intent；persistent 进程需 shutdown/inspect，资源义务全解决才正常完成 CE。runtime 禁止跨 CE epoch 复用（V99-D:383,441–449）。 |
| 历史与当前权威 | **已实现/设计延伸** `agent_steps` 唯一历史 SoT；jobs/grants/bindings 等可以是当前控制或值权威，**不是所有表都从 log 重建**（PG-R:222–254）。 | **设计** 多种明确的不可变事实与状态表：requests、pins、observations、config snapshots、refs 等各司其职；CE snapshot 是每 run 投影（V99-D:88–96,169–214）。不继承 pg_cordis 的单 `agent_steps` 历史合同。 |

**本轴结论**：pg_cordis 试图让“耐久任务执行”和“可反应、可恢复的插件生命周期”分层共存；v99 让插件服从一个 CE 执行生命周期，并把长期进程的真实收尾作为正常完成的前置条件。两边的 run/epoch/fiber/runtime 不能按名称直接一一对应。

#### A4. 崩溃恢复：恢复任务、重放 DB 回执、重发外部工作必须分开

本调查分开三种不确定性：**响应不确定**（DB 是否已提交）、**业务不确定**（外部操作是否发生/结果如何）、**资源不确定**（进程是否还活着）。receipt journal 可以解第一种，可信 inspect 可以解第三种；两者都不自动证明第二种。这是对下列恢复合同的归纳，不能把三个 unknown 混成一种。

**pg_cordis 已实现的任务恢复**：P04 的 stale/fail 可以增加同一 jobs 的 recovery attempt，按 backoff 回 SLEEPING/PENDING，耗尽转 ERROR；已有 error 日志则直接终态，不再增加 attempt（`sql/0004_p04_sleep_retry.sql:620–679,754–827,858–886`）。`claim_job` 入口内调用 due/stale 清扫，仍需有人持续调用；租约过期不会释放挂死事务持有的行锁（PG-R:107,553–555）。这是**任务级恢复**，不证明 external 工具可以重发。

**pg_cordis 已实现的宿主丢响应**：

> 「Treat command timeout, killed `psql`, host SIGINT/SIGKILL, and orphan `psql` children as **unknown outcome**. … Never automatically retry a mutation.」—— [PG-H:74](</Users/wxl/Projects/zcordis-pgembed/docs/host-sql-seam.md:74>)

丢失 claim 应答不能从 `claimed_by` 猜出 token；应等待过期/恢复。其他 mutation 丢响应按 job/log/checkpoint 读回核对（PG-H:36,76–86）。这与 P04 的服务端任务 retry 不是矛盾：**不盲重发 SQL mutation ≠ 不允许按状态机重新认领任务**。

**pg_cordis D2 设计**更细：OPEN→RESULT/ABANDONED/INDETERMINATE；接管不能自动换 call attempt。只读 replayable 或合同明确的 idempotent+operation_key 可获 replay 许可；non_retryable 只能 settle_only/对账。旧执行世代可以追加 late observation，不能用旧 token 改 current/status（PG-R:284–316）。所以不能把最终差异说成“pg_cordis 一律不重试，v99 会重试”，也不能反过来说“pg_cordis 一律重试外部调用”。

**v99 基础/设计**更保守地区分两种重放：已经提交的 DB receipt 可以从 journal 返回首次响应；未知外部业务不自动重发。Phase0 已有 replay 在 lease 检查之前的实现（`v99/core/sql/30_ce.sql:468–493`）；M1 再扩完整 binding 与 request journal。新 driver 接管后，旧 claimed business 进入 unknown/blocked_unknown，而不是 ready。即使目标只读 SQL，断连且不能确认未执行也不自动重发旧 effect（V99-D:261,455–468）。

资源恢复是 v99 M1 的额外重点：supervisor 先 fsync spawn intent，再 spawn，再持久化 OS identity；spawn 后身份落盘前崩溃只能 ambiguous，不能再 spawn 同 token（V99-D:395–403）。cleanup unknown 可由**新的**可信 inspect/shutdown 证据解决资源义务，旧 unknown 事实保留；business unknown 不随进程证停而消失。cancel 可终结业务接单，不能证明 IO 已停，也不免除资源清理（:66–74,443–468）。以上进程机制仍是设计，不是 Phase0 能力。

**本轴结论**：pg_cordis 倾向以 checkpoint/分类许可提高可安全接续工作的恢复能力；v99 优先阻断不明业务、保全回执与进程身份，并允许资源清理独立收敛。前者多承担 replay 分类、部署纪律和 continuation 正确性的证明；后者多承担人工取消/阻塞和保守性带来的活性成本。两边均不承诺外部 exactly-once（PG-R:302,316；V99-D:73）。

#### A5. 授权与版本变化：live slice 与冻结 epoch 闭包

pg_cordis 的已实现四缝是 `recall_named_corpus / fold_slice_messages / read_run_env / authorize_tool_dispatch`，逐语句读取 **slice live grants**，无 first-fold freeze，下一语句能看到 revoke；P05 legacy step 与 P03 event 动词尚未被四缝包装（`sql/README.md:87–89`；PG-H:50–60）。PG-M:1232,1241–1256 又明确：locus 决定 SQL/host 分工，但宿主四缝是受控调用路径约束，**不是恶意 worker 的 OS 沙箱**。

v99 M1 把 scope 配置及完整依赖/grant/adapter/artifact 闭包冻结在 **CE epoch admission**；父子 scope 固定 parent snapshot，只能显式 rebase。drain/revoke 禁止新 epoch，但已准入 epoch 的 continuation、active steer/respond 沿用旧闭包；要停止既有工作需 cancel（V99-D:88–100,216–226）。driving generation 另管对话发布权，旧 generation 结果可入 history，但不得续旧链（:66–74）。

**本轴结论**：pg_cordis 优先选择访问时的权限新鲜度；v99 优先选择进行中执行的闭包稳定性。不能写成“撤销两边都立刻取消”或“v99 撤销没有作用”；它们承诺的生效边界不同。live 数据授权与冻结配置闭包并非所有用途都互斥，本报告只比较各自明确承诺，不推导全面等价/优劣。

### 二、取舍与弃用

#### B1. 保留、拒绝与转化的 Cordis 语义

| 语义 | pg_cordis 的取舍 | v99 M1 的取舍 |
|---|---|---|
| DI 与服务值 | **已实现** P06 接受 inject/provide/intercept 声明形状，但不执行依赖装配。**设计** `provide(name,value)` 拆成 JSON 数据按值 + `identity@impl_version` 能力寻址，闭包/活对象不入 DB（PG-R:64,79,567–577）。 | **设计** manifest requires/exports、显式 desired set/import handles、schema/grant 闭包校验；handle 不能同步执行，调用被转换为受账本控制的 effect。它是实际组合合同，不能贬成“仅借几个词/元数据”（V99-D:152–165）。 |
| Scope/隔离 | **已实现** slice-bound grants 与四缝；**设计** realm=(slice,key) 受限隔离，不承诺 JS `isolate` 每个键任意跨 realm 分割（PG-M:697–715,1232–1256）。 | **设计** scope 树、固定父快照、子授权单调收缩、显式 rebase。采用 scope 的组合/授权意义，未承诺 JS 对象 Context 或 isolate 源码兼容（V99-D:11,216–226）。 |
| Fiber、反应性、惯性 | **设计保留并持久化**：可选 L3 中有十条生命周期规则、committed_view、按值 relied、notify、逆序 recovery。普通任务核不依赖 fiber（PG-R:214–218,350–381）。 | **首版范围外**：不建立该 fiber/coeffect 自动重估模型，选择冻结 epoch + generation + drain/cleanup 的显式生命周期；未来须经有版本 export ABI 扩展，不能声称永久禁止（V99-D:9–11,66–100,203–226）。 |
| Event/middleware | **已实现** P03 是 first-write-wins rendezvous，**不是**重复事件总线。**设计** dispatch 尝试对应 on/once/emit/parallel/serial/bail/waterfall，但 serial 必须有短路、waterfall 仅尾调用子集，无一般同步栈回卷（PG-R:229,579–604）。 | **明确拒绝首版任意 middleware/event-hook 与同步嵌套 RPC**；保留的是 CE 事件/审计/进程 observation、durable wake cursor，不是 Cordis event bus 的兼容实现（V99-D:11,339–348）。 |
| disposer / 可逆性 | **设计转化**：仅 REG 形获取映射为持久 recovery_plan 的 LIFO 逆程序；任意 disposer 留既有 Profile S 或按 D2 外部效果处理，不假装数据库事务能撤销 HTTP/文件（PG-R:364–375,590）。 | **设计转化**：dispose 成为 drain + live refs/obligations 检查 + 释放 CAS 引用 + confirm；cleanup 证明进程停止/资源释放，不等于撤销业务外部副作用（V99-D:218–226,395–403,443–468）。 |
| JS 兼容与动态代码 | D8 已锁「不做 DSH 迁移器 / 事件兼容层 / node:vm」（PG-S:100）。**设计** Profile S 只容既有离线受信部署继续保留源语义，既不引入也不打包 DSH；Profile D 才映射到持久层，动态模型代码不进入 PG 动词面（PG-R:561–565,593–604）。 | **明确不提供 JS Cordis 源码兼容**。首版仅批准的离线 Python/Node/SQL fixtures、固定 adapter，不接受任意 argv/第三方代码。签名/capability 不是恶意代码沙箱（V99-D:11,74,399–405）。 |
| 核内执行面与子任务 | **已实现** queue handler 在 SQL 事务内执行；通用 session tool executor 当前只收 read_only。**设计/合同** 子 run 必 enqueue 返回 handle，dispatch item 同样复用 jobs，禁止第二队列（PG-S:87–101；PG-R:247–250,743–749）。 | **设计** Python/Node 由 supervisor，SQL 工具首版只读；工具结果不发嵌套调用、不自行创建 run/epoch/effect（V99-D:163–165,253–261,439）。**Phase0** `spawn_subsession` 是 simulated Fake 结果，并未创建 child run（`v99/core/README.md:54,109`），不能拿它说已经拥有 pg_cordis D9。 |

两边共同弃用的不是 Cordis 的“组合”目标，而是**把进程内对象/闭包/同步回调当成可天然跨语言、跨事务、跨崩溃保存的东西**。差别在于：pg_cordis 的持久适配档案仍想保存较多 fiber/反应性/可逆注册语义；v99 首版选更窄、更显式的配置组合与执行资源生命周期。

#### B2. v13 控制附录会不会推翻以上判断？

不会推翻分工原则，但**不能把附录机制直接套到 v99**。

> 「**DB** 验证持久状态转换、授权与 CAS；**host** 验签、隔离、可信进程身份及执行批准适配器；**driver** 持续扫描、续租、恢复和推进。」—— [V13-A:15](</Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v13-multilingual-plugin-plane-control-annex-2026-10-20.md:15>)

V13-A:102 采用 **runtime lease + bound effect lease**；:112 要保持旧 claim ABI；:116–145 设计 `v13_plugin_complete` 包装与旁路封堵。v99 权威文档专门裁决：

> 「不引入 runtime/effect 双租约；不保留旧 claim ABI；不复制完整 agent_manage/goal/quota 产品面」—— [V99-D:46](</Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v99-core-native-plugin-plane-2026-10-20.md:46>)

因此附录是 **v13 的设计伴随合同**，对 v99 是被选择性采用的参照：采用责任分层、持续续租、unknown、可信进程身份/收据；拒绝双租约、旧 ABI 与完整产品面。V13-D:80–103 与 V13-P:77–88 也支持这种分工，但都不能证明 v99 插件 runtime 已实现。这里是**明确的设计取舍**，不是漏读附录后强行调和两个不兼容合同。

#### B3. “与 pg_cordis 五件套对齐”核验：字面不成立，不能扩大成全面不兼容

原始两组不是同一清单：

> 「D4 | 五件套进核：claim、checkpoint、sleep、scoped event、任务级 retry。habitat/SDK 非核」—— [PG-S:96](</Users/wxl/Projects/zcordis-pgembed/docs/analysis/2026-08-23-i-architecture-snapshot.md:96>)

> 「核动词（与 pg_cordis 五件套对齐，不另起一套词）」—— [`docs/designs/v8.md:87`](</Users/wxl/Projects/pg-agent/docs/designs/v8.md:87>)

> 「yield 五件套」明确为 `claim / checkpoint / yield / wait / sleep`；`complete/fail`、`heartbeat`、`release_stale` 是终结与维护动词 —— [`docs/designs/v8-revision.md:379`](</Users/wxl/Projects/pg-agent/docs/designs/v8-revision.md:379>)

同一修订文 :382 原文为 **「五件套」现在列了八组动词。**；v8 正文 :90–97 确实列了八组。精确五项重合只有 claim/checkpoint/sleep；yield/wait 没有逐项等于 scoped event/task-level retry。

**裁决**：如果“对齐”指**五项名称或分类一一相同**，该说法不实/不精确；但不能据此断言功能上少了 event/retry 或整体协议不兼容。v8 把 wait、fail、release_stale 等列在另一分组，必须逐行为比对。更不能拿历史 v8 的该句代替此次 v99 架构：v99 已选择独立 CE/effect/run lease 合同及独立 loader（V99-D:46,67–74,472；`v99/core/load.py:1–10`）。本调查记录差异，**未修改历史 v8 文档**。

### 三、各自正确之处与付出的代价

| 分歧轴 | pg_cordis 正确抓住的事 / 代价 | v99 正确抓住的事 / 代价 |
|---|---|---|
| loop 与执行粒度 | 让库内/宿主共享 claim、日志续体与任务内核，worker 可替换；但 p21 还缺产品循环与完整宿主执行缝，未来维护 owner 必须真正部署。 | 把持续推进、续租、恢复写成明确 driver 责任，减少“有 SQL 就会自己活”的误判；但同 run 单 claimed 与 FIFO 有意限制并行，连续 driver 仍待实现。 |
| 原子性与恢复 | 持久 checkpoint 与分类 D2 有利于安全接续，SQL 事务可覆盖库内效应；代价是 continuation、重放资格和 legacy/new 路径组合证明复杂。 | 唯一 T2 同时决定结算/后继/发布，receipt replay 与 unknown 分离清楚；代价是即使安全重算可能存在，也常选择阻塞业务，恢复活性较保守。 |
| 插件生命周期 | 不把 durable run 强绑 fiber，仍保留服务激活、依赖失配与逆程序等 Cordis 语义；代价是可选 L3 本身非常复杂，不能靠目录声明宣称已经有运行时。 | 明确进程身份、spawn 崩溃窗口、引用与 cleanup，final 不伪称资源已停；代价是舍弃首版反应性/通用事件/任意 disposer 兼容，并增加收尾阻塞。 |
| 授权时机 | live slice gate 有清楚的逐访问撤销边界；代价是长流程必须承认中途授权变化与现有 legacy 路径未全面覆盖。 | epoch 闭包固定，升级/drain 不悄悄改进行中执行；代价是 revoke 不等于立即打断，必须有显式 cancel 与可观察 blockers。 |

**对用户问题的直接回答**：pg_cordis 更像“可由任意受信语言 worker 驱动的持久任务核，并计划承载可选 Cordis 运行时”；这里设计的 v99 Cordis 更像“由唯一 CE driver 推进、数据库统一裁决的原生多语言插件执行平面”。共同底线是 DB 权威、显式授权、单一执行资格来源、IO 与事务分离、不谎称外部 exactly-once；并不是一个更 Cordis、另一个更 SQL 这么简单。

### 四、调查执行与限制

- 已收齐三个并行只读探针：v13 控制附录/v99 分工、pg_cordis p21 loop/IO、语义取舍/五件套；关键结论再由主调查者直接读取设计与 SQL/Python 源码抽查，未仅依赖探针摘要。
- 本轮**只修改此调查报告**，不改两仓源码、设计合同、测试或历史计划；不是某条实现 stage/gate 的里程碑完成，不触发以实现完成为条件的 commit/push 流程。
- **未运行数据库 gate、provider、产品循环或故障注入测试；未提交或推送。** 本节的“已实现”指源树存在且读到相应路径，不等于本轮动态验收通过。文件中的既有测试记录只作为历史证据标识。
- 未查询远程状态，不把文档记录的 HEAD、通过状态、采纳建议自动当成当前远程事实。两份设计的新机制都必须经过其各自实施和验收，才能转为已交付能力。

## Investigation Log

### Phase 1 - Triage
**Hypothesis:** 问题需要先消歧「Cordis」指哪一个
**Findings:** 机上有 A/B/C/D 四个候选指称；B 与 C 分属两个独立 git 仓（B remote=`zcordis.git`，C remote=`zcordis-pgembed.git`）
**Evidence:** `git remote -v` in both repos；`find` 结果
**Conclusion:** 待用户确认对比对（见 Report 末尾 Open Questions）

## Root Cause

### 一句话回答

**两者不是「谁更 Cordis、谁更 SQL」，而是把执行组织在不同的东西周围，并因此对「插件能活多久」「授权何时失效」「崩溃后能怎样接续」给出了互不兼容的可观察承诺。** 这不是成熟度差异——即使两边都把计划中的组件全部做完，下面三条差异依然成立。

### 共同底线（先划清不差异的部分）

四或五条承重原则两边完全一致，所以不能用它们解释差异：

1. 数据库是权威（身份、准入、账本、生命周期）；
2. 显式授权，不存在隐式提权；
3. 单一执行资格来源（pg_cordis 的 `jobs` claim / v99 的 run driver lease），且都明确拒绝「第二队列」；
4. 外部副作用**绝不与数据库提交假装原子**；
5. 两边都不承诺外部副作用 exactly-once（`PG-R:302,316`、`V99-D:73`）。

> Oracle 特别纠正过一个流行误判：**不存在「pg_cordis 的循环在 SQL 里自己 while、v99 才有宿主循环」这回事。** v99 的 SQL 本来就承担真实控制迁移（model 请求 tool 后由 SQL 建 tool effect，整批结束后由 SQL 建下一个 LLM 调用，见 `v99/core/sql/30_ce.sql:458` 起的 `accept_receipt`）；而 pg_cordis 的 `step_once`/`worker_step` 都是**单次调用**，总有外部东西要再次调用它。两边都靠外部承担活性。

### 不可约化的三条差异

#### 差异 1（最根本）：续体（continuation）的单位不同

| | pg_cordis | v99 |
|---|---|---|
| 执行单位 | **命名步 `s-N` + 持久 checkpoint + jobs 转移**；不同 locus 的合格 worker 都能接续同一个 job | **逐 effect 准入**；一个 run 一个受租约约束的 driver 执行已准入的工作 |
| 粒度证据 | `step_once` 一次 live claim 至多一个 `s-N`（`sql/README.md:61`）；宿主路径「One method = one committed statement」（`PG-H:28`） | T1 COMMIT → 控制连接 IDLE → IO → **唯一原子 T2** 同时完成结算/建后继/发布/写 replay journal（`V99-D:69`） |

粒度本身**可以**互相适配（一个命名步里可以含多个独立记账的 effect）。真正硬的是由此产生的下面两条可观察合同。

#### 差异 2（最能一刀切开两者）：插件的寿命 vs 激活它的工作的寿命

这是最干净的判别式，且**不受实现进度影响**：

- **pg_cordis 明许「工作做完、服务还活着」。** 重设计的 L-Finish 可让 run DONE，但成功 fiber 的 episode **仍 OPEN**，服务保持 installed/active，等后续依赖变化再 Leave/Unload（`PG-R:354,365-371`）。
- **v99 不容许「模型 final、进程还活着」算正常完成。** ModelFinal 只落 closeout intent，persistent 进程必须 shutdown/inspect，资源义务全解决才封口；runtime 禁止跨 CE epoch 复用（`V99-D:383,441-449`）。

即：pg_cordis 是**可复用的耐久任务底座**，插件生命周期可以长于激活它的那次工作；v99 是**有边界的 CE 执行平面**，进程身份属于某个 epoch，长期进程的真实收尾是正常完成的前置条件。

#### 差异 3（互操作时最危险）：授权新鲜度相反

- **pg_cordis = 逐语句实时授权。** 四缝 `recall/fold/env_read/tool_dispatch` 每条语句读 **slice live grants**，**没有 first-fold 冻结**，下一语句就能看到 revoke（`sql/README.md:87`、`sql/0007:664`）。
- **v99 = epoch 准入时冻结整个可执行闭包**（配置/依赖版本/grant/adapter/artifact）。revoke/drain 只禁止**新** epoch 准入；已准入 epoch 的 continuation 沿用旧闭包，要停正在跑的活必须显式 `cancel`（`V99-D:96,216-226`）。

两者各自自洽，但**对同一个 export、同一份输入、同一条目录项可以给出相反的授权裁决**：v99 epoch 启动时 grant 有效 → grant 被撤 → 同 epoch 再请求调用 → v99 放行（冻结闭包），pg_cordis 拒绝（live grant）。这不是 bug，是合同不同。

### 「五件套对齐」是字面不实（已双向核实）

- `v8.md:87` 声称核动词「与 pg_cordis 五件套对齐，不另起一套词」，但其列出的五项是 `claim / checkpoint / yield / wait / sleep`（`v8-revision.md:379`）；
- pg_cordis D4 的五项是 `claim / log checkpoint / sleep / **scoped event** / **任务级 retry**`（`docs/decisions/2026-08-23-pending.md:218`）；
- 精确重合只有 **claim / checkpoint / sleep 三项**。`v8-revision.md:382` 自己也承认「五件套」当时已列成**八组**动词。

**但不要把它扩大成「功能不兼容」或「整体协议不可互通」**：yield/wait 与 scoped event/task-level retry 是不同切法，不是一一缺失。它的正确用途是**修正措辞**，不是推翻架构判断。

### 两侧的取舍台账（各自留下了什么、扔了什么）

| Cordis 语义 | pg_cordis | v99 M1 |
|---|---|---|
| DI / 服务值 | P06 接受 inject/provide 声明形状但**不执行装配**；设计把 `provide(name,value)` 拆成「JSON 数据按值 + `identity@impl_version` 能力寻址」，活对象不入 DB | manifest requires/exports + 显式 desired set/imports + schema/grant 闭包校验；handle 是冻结能力引用，调用转成受账本控制的 effect |
| scope / 隔离 | slice-bound grants + 四缝；设计 realm=(slice,key) 受限隔离，不承诺 JS `isolate` 逐键任意分割 | scope 树 + 固定父快照 + 子授权单调收缩 + 显式 rebase；不承诺 JS Context/isolate 源码兼容 |
| Fiber / 反应性 / 惯性 | **设计保留并持久化**（可选 L3：十条生命周期规则、committed_view、按值 relied、notify、逆序 recovery），但**普通任务核不依赖 fiber** | **首版范围外**；改用冻结 epoch + generation + drain/cleanup 的显式生命周期，未来须经有版本 export ABI 扩展 |
| event / middleware | P03 是 first-write-wins rendezvous，**不是**重复事件总线；设计 dispatch 只覆盖 on/once/emit/parallel/serial/bail/waterfall 子集 | **明确拒绝**首版任意 middleware/event-hook 与同步嵌套 RPC（`V99-D:11`） |
| disposer / 可逆性 | 仅 REG 形获取映射为持久 recovery_plan 的 LIFO 逆程序；不假装 DB 事务能撤销 HTTP/文件 | dispose = drain + live refs/obligations 检查 + 释放 CAS 引用 + confirm；不伪称业务副作用被撤销 |
| JS 兼容 / 动态代码 | D8 已锁「不做 DSH 迁移器 / 事件兼容层 / node:vm」；Profile S 只容既有离线受信部署 | 明确不提供 JS 源码兼容；首版仅批准离线 Python/Node/SQL fixtures + 固定 adapter |

**两边真正共同弃用的**不是 Cordis 的「组合」目标，而是**把进程内对象/闭包/同步回调当成可以天然跨语言、跨事务、跨崩溃保存的东西**。差别只在保留多少生命周期机制：pg_cordis 的持久适配档案仍想留住较多 fiber/反应性/可逆注册语义；v99 首版选更窄、更显式的配置组合与执行资源生命周期。

### 各自的代价（不是一边更好）

- **pg_cordis**：worker 可替换、库内/宿主共享同一 claim、checkpoint 利于安全接续 → 代价是 continuation、重放资格、legacy/new 路径组合的证明更复杂；可选 L3 本身很重，**不能靠目录声明宣称已经有那个运行时**；live 授权意味着长流程必须承认中途授权变化，且 P05 legacy step 与 P03 event 动词**尚未被四缝包装**。
- **v99**：唯一 T2 同时决定结算/后继/发布，receipt replay 与 unknown 分离清楚，不伪称资源已停 → 代价是同 run 单 claimed + FIFO 有意限制并行；即使安全重算可能存在也常选择阻塞业务（活性较保守）；epoch 冻结意味着 **revoke ≠ 立即打断**，必须配显式 cancel 与可观察 blockers，且 drain **没有有界完成承诺**。

## Recommendations

### R1. 先修措辞，不是先改架构

`docs/designs/v8.md:87` 的「与 pg_cordis 五件套对齐，不另起一套词」按字面不实（仅 3/5 重合，且 `v8-revision.md:382` 自承已列成八组）。建议在同一处补一句限定：说明这是**立意对齐**（都取「核内自带耐久执行原语」而非「上层框架负责」），不是逐动词 ABI 对齐；并把 pg_cordis 侧的 `scoped event`/`任务级 retry` 显式列为**有但本仓用 yield/wait 表达**的等价关切。

`v8-revision.md:380` 已把 `pg_cordis`/`zcordis-pgembed` 放进外部兼容清单，要求「用途、适用范围、版本/commit、接口摘要、验证证据，未知一律 `null + note`」。按该条把两边的五件套动词表各填一行即可闭环，无需改设计。

### R2. 若两者需要互操作，唯一真正的硬点是授权时机（差异 3）

同名同 schema 的 export **不等于可替换**。最小互操作合同必须写明（`v8-revision.md:380` 只给了溯源要求，缺的是**版本化行为合同**）：

| 合同项 | 必须写明 |
|---|---|
| 版本与 export 身份 | 钉住两边 commit、schema/ABI 版本、精确 export 身份、实现 digest、输入/输出 schema，并附行为验证证据 |
| 授权档案 | 区分 `epoch-frozen` 与 `live-per-statement` 两种档案；共享 entry 必须声明本次调用受哪个档案管辖 |
| 撤销边界 | 互操作档案下，每个受保护缝/派发许可事务都做一次 live 授权检查；**已提交的撤销必须在检查前生效**。冻结 grant 只作为授权上界，不能覆盖接收方执行的撤销 |
| 执行权威 | 每次桥接调用指定唯一权威派发 owner；外部 job/step 映射到本地 effect + 不可变 request 身份；任何一方不得自行「帮忙」另起一次执行 |
| 否认与不确定 | 派发前已证拒绝 → 明确 *not executed*；可能已执行 → 保留 unknown。**重放已提交回执 / 重新认领 job / 重发外部 IO 是三件不同的事，各有各的许可** |

判定规则：**共享目录绝不等于共享授权裁决。** 任一端无法执行所声明的档案，该 entry 即不兼容，必须拒绝。

注意这条会**收窄 v99 对这批 export 承诺的连续性**，不是现成的 M1 能力，必须显式协商成 profile。

### R3. 别把「设计稿」当「已交付」——两边的证据状态必须分开陈述

- v99：Phase 0 已实现且 Fake-only；**M1 插件面纯设计**，`V99-D:3` 自述「设计稿，尚未实现」，`:5` 自述旧稿 Oracle 判 **Not ready** 且未复审。Python/Node adapter、supervisor journal、cleanup obligations、生产式连续续租**均未实现**。
- pg_cordis：产品树仍是 **p21**；`external_operations`/`external_calls`/`spawn_admissions`/fiber/episode/dispatch **specified 但 absent**（`PG-R:84`）；D2 外呼缝**未开**（`PG-R:76`）。
- 另注意一处**文档自相矛盾**：`PG-R:5` 仍写「推荐设计稿（待采纳；未实现）」，而 `docs/decisions/2026-09-16-redesign-adoption.md:10` 记录已采纳为设计基线。Sept-16 的采纳决定**不等于实现**，也不消除重设计文档里那个未更新的状态行。引用时两处都要提。

### R4. 若目标是「让 v99 拿到 pg_cordis 的反应式插件生命周期」

差异 2 说明这不是加个字段的事：v99 必须先把「插件寿命可以长于激活它的那次工作」变成一等公民（episode 概念、服务在 run DONE 后仍 active 的合法性、依赖失配时的 Leave/Unload 契约），否则只能靠 epoch 外的手工重准入模拟，会丢掉原本的资源义务封口保证。按 `V99-D:11` 的说法，这类扩展**应走有版本的 export ABI**，不要原地改 schema v2。

## Preventive Measures

### P1. 消歧先行：机上有四个互不相同的 "Cordis"

`A` 上游 JS 内核 / `B` cordis-db-agent（zcordis，DuckDB+Python）/ `C` pg_cordis（Postgres SQL）/ `D` 本仓 v99 插件面。写「Cordis 语义」而不点名是哪一个，是这类讨论反复打转的根因。**建议在 `docs/designs/` 下固定一张四行指称表**，所有 Cordis 相关文档引用它而不是各自复述。

### P2. 「与 X 对齐」必须附逐项映射表

本次唯一一处事实错误（`v8.md:87`）正是「对齐」被当成语义断言写进了正文。凡写「与外部项目 Y 的动词/五件套对齐」，旁边必须有一张 `Y 的项 → 本仓的项 → 差异` 的映射表；凑不出映射表就降级写成「立意相近」。`v8-revision.md:380` 的外部兼容清单（未知一律 `null + note`）已经是正确形态，应前移到写设计时而不是修订时。

### P3. 设计文档必须自标证据等级，且区分「设计/已实现/已验收」

这次能得出可靠结论，靠的是 `V99-D:3`、`:5` 和 `PG-R:5`、`:84` 这几行状态声明。若没有它们，很容易把 pg_cordis 的 L3 fiber 设计当成已运行、或把 v99 的 M1 当成已交付。建议把 `IMPLEMENTED / SPECIFIED / DEFERRED` 三态标记（`PG-R:5` 已自用这套）提升为两仓共同约定。

### P4. 「未知」必须分成三类，禁止合并叙述

**响应不确定**（DB 是否提交）、**业务不确定**（外部操作是否发生、结果是什么）、**资源不确定**（进程是否还活着）。replay journal 只解第一种，可信 inspect 只可能解第三种，**两者都不自动解第二种**。把三者写成一种「unknown」是恢复语义最容易被误读的地方；`V99-D` 和 `PG-H:74` 都正确地把它们分开了，值得作为显式约定保留。

### P5. 警惕「循环归属」这类伪二分

「SQL 拥有循环 vs Python 拥有循环」在本案是伪命题：v99 的 SQL 已承担控制迁移，pg_cordis 的 PL/pgSQL 步进函数也是单次调用。真正的问法是三个分开的问题：**谁决定下一个持久状态**、**谁承担重复推进的活性**、**谁持有执行所有权**。Oracle 与 pair 都在这一点上做了修正，说明这是高频误判。

### P6. 授权时机要作为显式设计轴记录，而不是隐含在实现里

`live-per-statement` 与 `epoch-frozen` 都是正当选择，但**必须写在合同里**，否则互操作时会静默产生授权绕过或意外的连续性丧失。建议任何插件/授权面文档都显式声明自己站在哪一侧，以及撤销的生效边界是什么。

## Open Questions

（原始两条消歧问题已由用户于 Phase 1 答复解决：我方 = 本仓 v99 插件面设计，对比目标 = 本地 pg_cordis。以下为调查后仍开放的问题。）

1. **pg_cordis 的 L3 fiber 层是否真的要落地？** 若永不落地，差异 2 大幅缩小（两者都只剩「显式生命周期」），pg_cordis 相对 v99 的独特性主要剩 live-per-statement 授权与 jobs 复用底座。目前 `PG-R` 仍是待采纳/未实现状态。
2. **本仓是否要把 `v8.md:87` 的措辞修掉（R1）？** 属文档修正，不改任何代码或 gate，不触发 AGENTS.md 的里程碑提交流程。需 owner 确认是否愿意改历史设计文档。
3. **若将来要做互操作，授权档案 profile 由谁先定？** 需要两边 owner 共同裁定，不能单方面收窄。
4. **v99 M1 的下一次 Oracle 复审排期。** `V99-D:5` 自述尚未复审；本调查只比对设计意图，不构成对 M1 设计正确性的复审。

---

# 裁决卷宗：谁的设计更可取？

> 本节为 Oracle 裁决而写。用户提问（2026-10-22）：「谁的设计更可取？」
> 前置结论（本报告 Root Cause 一节）：差异是**架构性**而非成熟度。本节请 Oracle **排名次**，不是再描述差异。

## 0. 认识论前提（务必先读）

**pg_cordis 不在本 workspace 内，Oracle 无法直接读取它。** 本卷宗引用的每一条 pg_cordis 证据都是调查者（agent + pair + 我本人）从 `/Users/wxl/Projects/zcordis-pgembed/` 逐字抄录的二手引文，带 `file:line`。v99 一侧的设计文档与已实现 SQL 则在 Oracle 的 selection 内，可自行复核。

**要求**：请在此前提下裁决；若某条结论**依赖一条无法自行核实的 pg_cordis 断言**，明确标出该断言，不要把它当作已证事实。

## 1. 判据（我用来判的标准，请质疑或替换）

「可取」至少有三个互不兼容的读法，请 Oracle 说明自己按哪个判，或分别给：

| 读法 | 问题 | 谁占优 |
|---|---|---|
| **A. 论证质量** | 哪个的推理更深、更少自相矛盾、更经得起推敲 | 待裁 |
| **B. 尺码正确** | 哪个的抽象量与机制量匹配它声明的目标 | 我判 pg_cordis |
| **C. 可交付性** | 哪个更可能真的做完并跑起来 | 我判 pg_cordis |

三者可以给出不同答案——**这正是本问题的难点**。请 Oracle 分别裁决，再给总排名。

## 2. 量化不对称（本次新核实，非二手）

| 指标 | v99 | pg_cordis |
|---|---|---|
| SQL 落地文件 | **5 个**（`00_extensions/10_schema/20_ledger/30_ce/40_permissions`） | **10 个**，合计 **6656 行** |
| 表数量 | **11**（`10_schema.sql` 内 `CREATE TABLE` 计数） | 已实现 13 张产品表 + 设计态对象另计 |
| `15_plugin_plane.sql` | **不存在**（仍是设计稿） | n/a |
| 已实现公共 CE 动词 | 6 个（`start/poll/wait_check/cancel/steer/respond`）+ worker/driver helper | 动词面更大（claim/renew/yield/complete/fail/checkpoint/await/emit/refresh_plugins/register_host_plugin/grant 系列/四缝四个/worker_step/step_once） |
| 测试 | Phase0 有 gate 脚本，插件面无测试 | **228 个用例** / **13 个测试文件** |
| commit | Phase0 一版 | **15 个**，P02→P19 逐个交付 |
| 执行语义 | **Fake-only**（FakeLLM/FakeTool） | **Fake-only**（`invoke_llm` 是 SQL mock hook，host tool authorize-only） |

**关键**：两边都还是 Fake-only，所以「谁能跑真实 agent」目前都不成立。不对称在**内核的完成度与证伪次数**（228 vs 0）。

## 3. pg_cordis 案卷（我主张它更可取的理由）

1. **被证伪过 228 次 vs 0 次。** v99 插件面自述「设计稿，尚未实现」（`V99-D:3`），且旧稿 Oracle 判 `Not ready` 后**未复审**（`V99-D:5`）。没实现的恢复语义只能看合理性，不能看正确性。
2. **核心抽象更小且每个承重。** 一个 `jobs` 行 + claim 协议 + append-only `agent_steps`；五件套 `claim/log checkpoint/sleep/scoped event/任务级 retry`（`docs/decisions/2026-08-23-pending.md:218`）每一项都在承重。v99 为同样目标铺了 requests/pins/observations/config snapshots/refs/cleanup obligations 六类表，表达力更强但要一起做对的更多。
3. **`checkpoint ⊂ log`（`PG-S:89`）是两边最漂亮的一步。** 历史与 checkpoint 是同一 append-only 结构，恢复时**无需在两存储间对账**。v99 没有这个性质。
4. **插件装载成本低两个数量级。** in-db 插件 = 一段 COMMENT JSON（实例见 `sql/0021_p09_in_db_worker.sql:566`）+ `SELECT cordis.refresh_plugins();`。对比 v99 M1 的 manifest→artifact→Ed25519 approval→install→activation→scope snapshot→grant 管线。
5. **威胁模型尺码。** 两边都只跑受信离线代码；`V99-D:74` 明说签名/capability **不构成沙箱**。既然不是安全边界，那套签名+审批+digest 闭环只是溯源审计——为本地单用户 agent 建它属尺码错配。
6. **逐语句 live 授权对「会碰用户工作区」的 agent 更安全。** 撤销下一语句即生效（`sql/README.md:87`，无 first-fold 冻结）；v99 要等 epoch drain，且 `V99-D` 自承 **drain 无有界完成承诺**，长活 epoch 可无限期钉住旧版本。v99 是用安全换连续性。

### pg_cordis 的代价（我不隐瞒）

无 artifact 身份、无能力上限、无审批留痕；**D2 外呼缝未开**（`PG-R:76`「external 执行缝未开」），即「让它成为 agent 的那条缝」还不存在；可选 L3 fiber 层极重且不能靠目录声明宣称已有运行时。

## 4. v99 案卷（它真正更强的两处）

1. **三类 unknown 分离**——响应不确定（DB 是否提交）/ 业务不确定（外部操作是否发生、结果是什么）/ 资源不确定（进程是否还活着）。replay journal 只解第一种，可信 inspect 只可能解第三种，**两者都不自动解第二种**。这是两边设计里最好的一个想法；pg_cordis 没有，因为它的外呼缝还没开，还没被迫回答「HTTP 到底发了没有」。
2. **资源义务作为一等公民**——`V99-D` 的 cleanup obligation + 进程身份证据 + spawn 崩溃窗口 ambiguous 处理（`:395-403`）。pg_cordis 对「进程活得比 run 久」没有答案。
3. （次要）单一原子 T2 同时决定结算/后继/发布/落 journal，原子性叙事比 pg_cordis 的「checkpoint 再 yield」更强。

### v99 的代价

**未建面极大**：整个 M1（manifest/artifact/install/activation/scope/grant/runtime/refs/obligations + 三语言 adapter + supervisor + 线协议 + 崩溃矩阵）全是设计。且 `V99-D:46` 明确拒绝继承 v13 的 registry/loader，等于**第三次从零推导同一地盘**，每推导一次就多一批表。附证：`v8.md:87` 声称与 pg_cordis 五件套对齐而实际仅 3/5 重合（见 Root Cause）——**文档声称与外部对齐而实际没对齐**，正是「没有实现来压缩设计」的后遗症。

## 5. 我的立场与我的软肋

**立场：pg_cordis 更可取**，理由是 B（尺码正确）+ C（可交付性），不是因为论证更深。

**我可能错的地方（请重点攻这几点）**：

- 我可能把「已实现」的权重给得太高。若判据是 A（论证质量），v99 的崩溃矩阵可能直接翻盘——尤其 pg_cordis 连 D2 都没开，等于**还没进入那道最难的题**。
- 我可能误判了 v99 那套 manifest/approval 的价值。若未来目标是插件分发或多租户，它就是承重而非仪式。
- pg_cordis 的「小」可能是**欠债**而非美德：没有 artifact 身份与版本 pinning，将来做升级/回滚会比 v99 更痛。
- 两份设计的作者是同一人、不同时间点。所以这可能不是「两种哲学之争」而是「同一个人后来做了更周全的推导」。若如此，判「pg_cordis 更可取」就等于判「早稿更可取」，需要更强理由。

## 6. 请 Oracle 裁决的具体事项

1. 按判据 A / B / C **分别排名**，再给总排名，并说明自己更看重哪个判据、为什么。
2. 正面回应第 5 节四个软肋，逐条给「成立 / 不成立 / 需补证」。
3. 裁决「pg_cordis 的极简是美德还是欠债」，并给出**判别条件**（什么条件下它会从美德变欠债）。
4. 若结论是 v99 更可取，请说明**在它一行未实现的前提下**，这个结论的效力边界在哪；是否应改为「v99 的*方法*更可取，但当前*产物*不可取」。
5. 标出任何**依赖不可核实的 pg_cordis 断言**的结论。

> 附：本卷宗不构成对 v99 M1 设计正确性的复审（`V99-D:5` 自述尚未复审），也不替代任何一方的实现 gate。

## 7. Oracle 裁决（2026-10-22，chat `investigate-cordis-vs-pg-EA688F`）

### 裁决结果

| 判据 | 胜方 |
|---|---|
| **A. 论证质量** | **v99 略胜** |
| **B. 尺码正确** | **v99 胜**（但仅针对它声明的「原生多语言插件平面」目标） |
| **C. 可交付性** | **pg_cordis 明显胜** |

Oracle 的加权：**B 45% / A 35% / C 20%**。理由是「设计评判先看是否正确匹配声明的目标；实现进度重要，但不能把尚未覆盖目标的较小内核自动评成更好的完整设计」。

**总体：v99 的方法更可取；pg_cordis 的当前产物更可用。**

> **v99 的方法更可取，但当前 v99 插件产物不可取为已交付系统；pg_cordis 的当前内核更可用，但不能因此宣布它已解决完整插件执行问题。**

### 对我立场的裁决

- **C（可交付性）：我正确。** 且「不能被架构漂亮抵消」。
- **B（尺码正确）：我错，Oracle 驳回了我的「过度设计」判断。** 见下。
- **A（论证质量）：我把「已实现」的权重放得过高。**

### Oracle 对我最有力的一条反驳（我接受）

> 你的「过度设计」判断隐含了一个较窄目标：本地、单用户、受信代码、没有插件分发和多租户治理。但 v99 明确声明的目标是：实际运行 Python 长活插件、Node 单次插件和只读 SQL 工具，并支持安装、依赖组合、作用域继承、升级、授权、排空和退役（`V99-D:9`）。
>
> 针对这个目标，manifest、artifact、approval、install、activation、scope snapshot、grant、runtime、resource ref 和 cleanup obligation 并非单纯的安全仪式。它们分别承担：可复现的插件身份、代码与适配器绑定、跨语言 ABI 解析、scope 可见性、in-flight pin、drain 与 dispose、进程资源收尾。
>
> 「签名和 capability 不是 OS sandbox」只说明它们不能阻止恶意代码（`:74`），不说明身份、版本、授权和资源账本没有必要。

**这是对我第 3、5 条理由的正面驳回，且成立。** 我此前是拿 pg_cordis 的**较窄目标**去量 v99 的**较宽目标**，尺子拿错了。

### 四个软肋的裁决

1. **「我可能过度看重已实现」——成立。** 影响 C，但不应主导 A 或 B；228 个测试是交付证据，不是完整目标的证明。
2. **「manifest/approval 可能只是过度建设」——对本目标不成立。** 对单一可信进程与单用户 fixture 可删减；对 v99 自己声明的跨语言安装/升级/授权/排空/退役，它们是承重机制。
3. **「pg_cordis 的小可能是未来债务」——Oracle 的回答在传输中被截断，未取得。**
4. **「同一作者不同时间」是否改变裁决——未取得。**

### 认识论标注（Oracle 自设）

Oracle 把**全部 pg_cordis 内部事实标为 `[C-外部未核]`**（无法自行验证），把我本轮独立核实的数量表标为 `[C-用户核实]`。它明确说：即便 pg_cordis 的 `checkpoint ⊂ log`/named-step/task-level retry 确实更优雅，**也不能据此证明它已覆盖外部副作用、进程身份与资源收尾**。

### 效力边界（Oracle 自述）

> v99 这个胜出结论的效力仅限于架构选择和合同设计。它不能证明 M1 可实现、无死锁、能完成三语言链路，尤其不能替代尚未进行的复审和 gate。

### 传输状态（须知）

本轮两次 `ask_oracle` 调用均被后端 `interactive inactivity watchdog` 终止；第一次的裁决正文成功送达（上文即其内容），但正文在软肋第 3 条处被截断；**要求补完第 3、4 条与我第 4、5 项提问的第二次调用完全未送达**（chat 中该条为空）。故软肋 3/4 与「可证伪条件」「不可核实断言清单」三项**未取得 Oracle 意见**，本报告不代为编造。依「重复相同失败且外部状态无变化即停止重试」的处理原则，未再重试。
