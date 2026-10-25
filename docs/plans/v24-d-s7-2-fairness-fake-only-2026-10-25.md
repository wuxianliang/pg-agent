# v24 D-S7-2：公平调度独立设计与 Fake-only 验证计划

日期：2026-10-25。状态：设计计划及其后续 M-F1 实施已完成；设计阶段曾纳入 Oracle 2026-10-25 批量裁定并完成独立设计审查与最终保真核对。实现阶段修改了 `v24/host/worker.py` 并新增 S12 Fake-only 证据，未修改 SQL、loader、HostDB 或 HostJournal 格式；完整执行记录见 §13。

## 1. Goal 与完成定义

为 v24 D-S7-2 提供可执行的 host-only 公平调度设计及 Fake-only 验证方案，明确负载假设、scope 服务机会、类别与 effect 等待界限、恢复工作、G 锁关系和可证伪证据。后续实施新增可选多 scope 入口，保留单 scope 旧入口；不把有限测试写成生产环境无条件 starvation-freedom。

本计划完成于：所有实质设计决策已有证据或带来源的 Oracle 裁定；实现接口、状态、错误边界、逐文件范围、确定性模型、真实 host/DB 集成用例、命令和里程碑发布义务明确；一次独立设计审查与导出保真核对完成。后续 M-F1 已按本计划实施并完成，但这不等于 D-S7-2 广义债务关闭。

不在本轮范围：v99 开发、第二批语言、跨主机接管、真实 provider 实验、吞吐/P99/成本/质量评估、内核新表/新列/新 RPC、journal 格式迁移、并行 IO、claim 抢占。既有 Python/Node plugin plane 已交付，作为兼容性回归保留。

## 2. Background 与当前状态

### 2.1 来源和版本边界

- 绑定 worktree：`/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，实际分支 **v24**，本次读取源码 HEAD `6d53a2d05a2e5439e7694125d4751ba053acb147`。路径名不表示本轮推进 v99。保留主检出与本worktree的其他修改及既有无关untracked工件；不暂存它们。
- 正式前计划为 `docs/plans/v24-post-closeout-followup-2026-10-25.md`，其 :369–380 要求公平性独立计划覆盖负载、服务/等待目标、调度、G/串行 IO、模型与对抗证据。`:7` 明确正式归属；另一个 `v24-closeout-followup-2026-10-25.md` 是既有未跟踪草稿，不是实施依据，禁止覆盖。
- 前轮发布 merge `d13391d27f9c7363906282af4cea4160c5aa97a8`、审计 `fc6f3222b329bea13adfb2baae03d38202142409` 已完成；当前分支未含 main 的审计文档追加。后续实施重新核对 fetch 后基线、源 SHA 和执行树，不将这些历史值当作未来实时远端状态。
- D-S7-2 仍开启：`docs/reviews/v24-deviation-ledger-2026-10-23.md:258`、`:552`；`v24/s7/README.md:364`、`v24/s9/README.md:132`、`v24/s10/README.md:82`。G6 只证安全/线性化；G9-R `v24/s10/test_g9.py:1349` 只证 bounded round，不证公平。

### 2.2 实际调度和协议

| 接缝 | 当前行为与设计含义 |
|---|---|
| `v24/host/worker.py:88` | `run_until_idle(scope,max_rounds=16)` 只迭代一个 scope；无跨 scope 公开入口。反复只调用 A 造成 B 无机会是调用域缺口，不能称为已有跨 scope 调度器的缺陷。 |
| `worker.py:102` | `run_once`：IDLE → reconcile → resume prepared（命中即返回）→ live orphan（本 scope 提前返回）→ expired/recover → discover → `ready[0]`。 |
| `worker.py:152`、`:205`、`:263` | journal 查询按 effect 首现序，跨 scope 交错；resume、reconcile、orphan 各自可影响新工作的等待，不能只替换排序函数。 |
| `worker.py:314` | 对本 scope 的 `host_effects` 完整翻页后过滤 ready；最终按 `(host类别优先,effect UUID)` 重排，非 SQL 页序。host=`host_prepare/host_release/inspect_resource`，business=`model_call/tool_call`。 |
| `v24/sql/49_host_reads.sql:129` | `host_effects` 授权及过滤按 scope，返回 ready/claimed 五种 external kind，页序 `(created_at,effect_id)`，单页最多 64 项，跨 RPC 无公共快照。无 due_at/priority/queue_position。 |
| `worker.py:342`、`v24/host/db.py:174` | service claim → committed+token → 两连接 IDLE → `host_effect` 重读 status/token → 串行执行 → journal finished → service settle。失败 claim 不授权 IO。 |
| `v24/host/db.py:30`、`:135` | 九个既有只读 RPC 加 advance/command_recover 共 11 名；`host_scopes(scope=None,after=None,limit=64)` 可枚举授权可见 scope。恰有 control/service 两连接，每 RPC commit/rollback。 |
| `v24/sql/49_recovery.sql` | recover 每次至多 16 项，G 下重发现；replay_safe host reset_ready，no_replay 业务 unknown，cancel_requested → cancel_late，manual 仅记 debt。lease 不是抢占或释放挂死事务的机制。 |

数据流仍为 `HostWorker → 既有 host 读者 → advance claim → token 复核 → IDLE 外部执行 → HostJournal → advance settle`。G=`pg_advisory_xact_lock(24,1)` 是 advance 第一个显式锁；闭包与锁序负责安全，PostgreSQL 等锁不构成应用公平证明。

`u_effects_model_call` 是**每 run**至多一个 live model call；一个 scope 可有多个 run/effect，不能据此推导 scope 成本相同。`fence<=attempt_no`、claimed 的 owner/lease 约束、unknown 墙均保持。lease_ms ∈[1,300000]；adapter timeout ∈(0,239]，lease 为 `min((ceil(timeout_s)+60)*1000,300000)`，model 分发前剩余 lease 至少 `int(timeout_s*1000)+5000`。这些是许可边界，不是完成时间保证。

### 2.3 规格与复用证据

`docs/designs/v24-db-native-agent-system-2026-10-22.md:1123` §17.2/17.3 明确为仅规格：跨 scope DRR、同 scope due_at/age/id、维护配额、blocked 与 eligible age 分离、claimed 不抢占、重试不扩大 IO 权限；无实测到达/服务率及长尾不声明 debt 有界。§17.1 的 maintenance control run、八类 owner 和 work_items 不是当前实现。

可复用夹具：`v24/s1/setup_db.py:555` 的唯一库、四角色、Unix-only DSN、单事务加载与精确 OID 清理；`v24/s9/h_support.py:213` 的 scope/run/effect seed、scan/state/fingerprint；`v24/s6/g5_support.py` 十表快照；`v24/s7/g6_support.py` held-G、无环、两顺序和零写；`v24/s4/fake_llm.py` 的有限 FakeLLM/FakeTool；G9 的 FakeClock、ScriptTransport、网络拒绝、J1/J2/J3 窗口。`seed_history` 创建终态历史，不能替代 >64 **ready** 播种。

### 2.4 不可变边界与导出纠正

- 历史冻结九文件与 `996cb5bc86f38fe5cbc21d058e93df54b4923620` 对比：`10_schema.sql`、`20_triggers.sql`、`30_advance.sql`、`40_interpreters.sql`、`45_capability.sql`、`46_cleanup.sql`、`47_verbs.sql`、`48_loop.sql`、**`49_recovery.sql`**（正式前计划 :523–535）。原 builder 输入误把 `00_schema.sql` 放入九文件，现纠正；本设计进一步要求现有 **全部 12 SQL** 不变。
- `v24/load.py:9` 的 CANONICAL_ORDER/SQL_LOAD_ORDER 共 12 文件；无 `00_extensions.sql`。不得增加第 13 文件、队列、claim 协议、错误码或权限。
- `HostJournal` 六类 event_type、v=1、核心键、request_digest、flock、0700/0600、fsync/读回与秘密拒绝不变。scheduler 状态不持久化；允许既有 journal 本地 IO 与 fixture PostgreSQL Unix socket。
- host 类恒优先是**旧选择策略**，不是内核资格安全条件；新类别配额是有意的新入口行为，不能同时声称保留恒优先。
- builder 把 plugin host 称未来 scaffolding、正式前计划称未跟踪、精确 closeout 命令留待发现，均由现存 G10/正式计划与 §9 清单纠正。G9 历史证明边界不回写成 G10 之前已有 plugin 证据。

## 3. Oracle 裁定（2026-10-25）

Oracle 在核对本计划与所选源码后对六项开放决策作一次批量裁定；下表记录选项、理由、置信度及推翻条件。此裁定仅决定设计计划，不授权实现、运行 gate、真实 provider 或发布。

| ID | Oracle 裁定 | 理由、置信度及推翻条件 |
|---|---|---|
| O1 | **A：host-only RR，以 fresh claim 尝试计机会；不做加权 DRR。** | 现有读者没有服务成本/权重；内存 DRR 可做但重启无 deficit 来源。放弃加权倾斜与跨重启债务恢复。置信度：事实高、选择中高。若出现明确加权需求、可复核成本定义及合规的债务恢复来源，可重开。 |
| O2 | **A：host burst=3；host 与 business 均有候选时第四次 fresh 选择给 business；同类按 `(created_at UTC,effect_id)` 循环。** | 3 是未测量支持的偏好假设，不是实测结论。置信度：中。负载证据或明确业务合同要求其他比例，或显示 3:1 不满足需求时重定比例并重推上界和用例。 |
| O3 | **A：显式 roster 可用；缺省由 `host_scopes` 授权枚举后固定；scope effects 完整分页扫描。** | 复用现有授权读者；保留 closed scope 清理义务；枚举结果不是 DB 原子快照。本专项不增量扫描或固定页预算，公平合同要求有限且最终结束的扫描。置信度：边界高、运行适用性中。若有明确运行预算证明完整 scan 不适用，另行设计预算语义；部分扫描不能冒称完整公平。 |
| O4 | **A：reconcile 有限列表快照；至多一个 prepared dispatch、一次 `recover(16)`，之后仍允许一次 fresh dispatch；额度分开、执行串行。** | live orphan 只阻所属 scope，RR 仍推进；has_more 后续访问，manual 不自动处理。置信度：中高。若对抗轨迹显示恢复仍压住 fresh，或额度违反已确认 IO 合同，重推 FC。 |
| O5 | **A：同类循环游标推进，单次顶层 fair 调用内每 effect 至多一次物理 claim（含 prepared-ready）；不做三次失败 quarantine。** | 每次 deferred/已确认 stale 或 terminal 竞争后跳过该 effect 至本次调用结束，下次调用重新读 DB；协议错误 fail-fast。需私有结构化 attempt 结果，旧入口仍映射旧行为。置信度：高。若循环推进造成可复核过载或违反明确重试政策，才评估含指纹、释放/再探测、debt、idle 的有限隔离。 |
| O6 | **A：M-F1 仅兑现 FC 子合同并登记证据；D-S7-2 广义主债务继续开启。** | 有限 Fake、单进程合同不证明开放到达、跨崩溃、多主机、墙钟 debt 有界。置信度：证据边界高、关闭政策中高。只有明确范围裁定重定义主债务并同步台账/关闭标准后才可考虑关闭；G11 通过本身不足。 |

### 3.1 Phase 6 新接缝的补充裁定

同一Oracle chat于2026-10-25根据独立审查与最终保真核对的具体代码证据补裁D1–D4：

| ID | 裁定、理由与置信度 | 可推翻条件 |
|---|---|---|
| D1 | prepared-ready重新claim仍按恢复来源计`prepared_attempts`，不计fresh机会/游标/streak；但所有物理claim共享调用内attempted guard。证据`worker.py:160`的ready分支确实重新claim，claimed分支才复用token；维持O4独立额度。路径事实高、计数选择中高。 | 明确要求所有物理claim计fresh，或对抗轨迹证明该划分不满足目标；须先重推FC/burst。 |
| D2 | worker专用journal；roster必须覆盖全部未决journal effects，启动时用既有`host_effect`逐项核验；缺失/拒绝/畸形/域外均抛`HostContractError` ownership failure。只核验三查询器并集中过滤已核销历史后的逻辑未决ID；具体过滤与terminal核销顺序见D4。查询范围事实高、使用约束中高。 | 明确受支持的共享journal/subset需求，或合法未决项不可通过既有读者确定scope；另定worker-wide debt，不能静默跳过。 |
| D3 | 无合作式调用方取消参数或墙钟deadline；max_rounds仅限visit边界，不中断visit内恢复/claim/IO/settlement。同步接口与既有effect取消独立，置信度高；本项是保守范围假设。 | 明确调用方取消/期限需求及在途IO、journal、stats和恢复完整合同。 |
| D4 | **B：fair-only worker 以过滤、核验后的逻辑未决集合替代原始journal查询并集。**先排除已有`settlement_committed`的记录，再对剩余ID逐项做ownership point-read；完成整个ownership核验后，对roster内且`unfinished_dispatches`、无`dispatch_finished`、effect状态确认为`succeeded/failed/unknown/cancelled`的记录，使用既有`settlement_committed`写入`conflict=true, reason=database_terminal_no_outcome, database_status=<终态>`以核销本地debt。理由：`_reconcile`已用该事件记录database-terminal与token冲突，既有格式足以表达本地冲突核销；不伪造dispatch_finished/业务成功，不改查询器/格式。置信度高。 | 若有受支持消费者要求每条`settlement_committed`必须对应`dispatch_finished`或成功receipt，或合法终态可恢复执行，则退回C并明确保留terminal unfinished debt。D4由Oracle 2026-10-25窄补裁。 |

专用journal是调用方使用约束：现有journal无worker身份/scope字段，不能证明历史归属；flock仍只证明单写者。自然`KeyboardInterrupt`/进程退出不吞掉、不报成功；有journal按既有窗口恢复，claim后尚未写journal依既有过期claim恢复。D2/D3均为可由用户覆盖的范围假设。

## 4. 合同、假设与等待界限

### 4.1 计数单位

- **scope visit**：RR 选中 roster 中一 scope 并运行 fair 阶段；空、blocked、失败也计一次，游标均前进。
- **新工作机会（fresh opportunity）**：由discovery选中一个ready external candidate并尝试一次claim；deferred/确证竞争仍计机会，不能计成功或完成。prepared-ready虽物理claim，按D1属于恢复来源而不计fresh。
- **prepared resume**：journal已有未开始工作，claimed复用token，ready重新claim；独立恢复额度，不计fresh effect cursor/streak/new_opportunities。ready重新claim共享attempted guard；claimed-token复用不消耗该集合。之后仍可对不同未尝试effect进行fresh选择；若已无候选则该visit不满足数值公平前提。
- **执行/完成**分别为外部调用与已确认 settlement，不能与 opportunity 混计。settlement_committed 可能只记 conflict，完成必须检查其 payload/DB 结果。

### 4.2 FC 合同与 opportunity-dense 前提

| ID | 契约与证伪条件 |
|---|---|
| FC-1 scope | 固定S的RR访问合同：任意S次连续visits每scope恰一次。数值机会合同仅在**opportunity-dense窗口**成立：每个visit结束、到达discovery且恰产生一次discovery来源claim尝试；此时连续S·k次全局机会各scope恰k次。空/blocked/全部已尝试/prepared耗尽候选/fatal visit使该窗口失效，不能从轨迹删掉这些visit再套公式。 |
| FC-2 类别 | 同一 scope 两类持续可用，host 新选择最多连续 3 次，第 4 次选择 business。business 不可用时 host 可运行且 streak 饱和到 3；business 再出现即有配额。只计 fresh 选择，prepared 的最多一次额外 dispatch 单列。 |
| FC-3 effect/冲突 | 固定有限的同类候选数 N，循环游标选择后即推进。单次顶层 fair 调用中每 effect 最多一次物理 claim（含 prepared-ready）；deferred 或已确认的 stale/terminal 竞争后跳过至调用结束，下次调用重新读取。有限稳定且可 claim 的目标在至多 N 次该类选择内得到一次 claim 尝试；协议错误 fail-fast，不适用剩余机会界。 |
| FC-4 冷启动 | 相同 DB 可见输入、journal 前缀、host 配置、显式 roster及同一脚本化transport/claim响应，两次冷启动生成相同选择序列；每次运行前恢复相同DB+journal快照，或使用两套完全相同fixture。基础用例只走lease-independent路径或把lease状态种在远离过期边界处；G9 FakeClock只控制ScriptTransport，不控制`HostDB.remaining_lease_ms`所用`datetime.now`或SQL `now()`。warm游标无需等于cold下一步。重启重置公平历史，不恢复已失的债务。 |
| FC-5 零额外副作用 | roster/分页/纯选择不写十个域表；RPC 名仍为既有 11 名；不引入网络/sleep/第二队列。快照、rpc_log、静态扫描任一不符即失败。claim/settle/recover 的既有写不冒充零写。 |
| FC-6 协议安全 | 两连接 IO 前 IDLE、claim 后 token/status 复核、单在飞、fence≤attempt、每 run 一个 live model、unknown 不复活、cancel seal 不变；任一破坏即失败。 |

**上界推理**：固定 roster 每 S visits 轮回一次；同类 N 个有限稳定候选的循环指针每次选择推进，至多 N 次该类选择到目标。两类在attempted过滤后持续可用且 burst=3 时，目标类别至多 4N 次本 scope fresh 选择得到一次 claim 尝试。换算为至多 **4SN 次全局机会/visits** 还要求固定 S、每次 visit 均结束并到达 fresh discovery、每次均产生一次 fresh opportunity。若计数范围包括无机会 visits，该换算不成立。N=1 的 business 首次机会界为 4S。prepared、live orphan、无 ready、竞争造成的本次调用跳过、fatal error、动态到达或不终止 scan 都会使相应前提失效。以上不保证 claim 成功、外部执行、settlement 或墙钟完成时间。

### 4.3 两类假设

| 契约假设（Fake 可强制） | 失效后撤回的结论 |
|---|---|
| 有限固定 roster，候选集合有限，测量窗口无改变集合/排序的到达；每页和 journal 阶段最终返回 | 不能推导完整轮回的进展或静态分页 RPC 上界。 |
| 目标持续 ready、结构有效、可 claim；无 live orphan、权限/协议错误；每 visit 到 fresh 阶段 | 只保留 scope visit 的轮转规则，不保证该 effect 机会/成功。 |
| 单 worker、单在飞；无第二 claimant或按脚本精确注入；所测决策的时间输入受控或与lease边界无关 | 不保证成功率、等服务或序列可复现。 |
| 无 HostCrash、journal 损坏/锁冲突，max_rounds 足够 | 不保证跨崩溃公平或未完成观察窗口。 |
| 单 visit 所见 journal 列表取有限快照，不在扫描中追逐新尾项 | 无有限工作量证明。 |

| 环境/运维假设（本轮不作结论） | 限制 |
|---|---|
| DB/G/OS 最终让调用返回；既有 READ COMMITTED、30s statement、5s lock、5s idle-in-transaction timeout | 超时不是成功服务，G 不保证公平；挂死数据库会话仍由部署方处置。 |
| journal 磁盘可写、fsync可靠、目录与单写者所有权成立 | 失败当步停止，不以公平为名跳过 durable outcome。 |
| 到达率、服务率、外部调用时长和长尾尚未测量 | 不声称 wall-clock/P99/吞吐/debt 有界。 |

开放系统仅作弱化观察：固定 roster 在 **visits** 计数上轮转；扫描前已存在且持续可见的 ready 项在一个**完整且结束**的 scan 中被考虑，scan 后到达留待后续完整 scan；跨页并发变化可遗漏本轮快照之外项，不保证下一 visit 一定看到所有动态项。新 scope 在本次 roster 构建完成后出现，留到下一调用。没有有限/终止假设时，不给 W 次墙钟或机会内被考虑的承诺。

FC-2的类别可用性在完整scan及attempted过滤之后计算；FC-3的N是目标discovery类别的有限eligible候选数。单次调用候选耗尽后不继续宣称机会密集；FC-1访问轮转仍可单独验证。G11必须保存全部visits而非仅成功/机会子序列。

## 5. 组件、接口、状态与算法

### 5.1 接口与所有权

后续仅在 `v24/host/worker.py` 新增同步入口：`HostWorker.run_scopes_until_idle(scope_ids: Iterable[str] | None = None, max_rounds: int = 16) -> RoundStats`。按 O3，`None` 通过 `host_scopes` 分页枚举并固定本次调用 roster；显式 roster 则不调用该枚举读者。scope UUID 标准化、去重、排序；拒绝非法 UUID、单字符串冒充 iterable、bool/非正整数 max_rounds；空显式roster先验证按D4过滤后的逻辑未决journal集合为空，再返回零visits idle；非空债务按D2报ownership failure。既有 `run_once(scope)` 与 `run_until_idle(scope,max_rounds)` 签名、返回与顺序保持兼容，新入口不通过改写旧 `_order_key` 偷换旧行为。

max_rounds 在新入口是 **visits**，非 pass 或成功次数。同一实例跨调用保存 last scope，按新 roster 中严格大于该 ID 的首项继续、末端回绕；scope 删除/新增不使用失效位置索引。参数变化的公平域从本次 roster 起算；不把不同 roster 的机会拼成 FC-1。

`HostDB` 不改接口/调用表，`HostJournal` 不改格式。worker 内共享 claim→重读→execute→settle 核心；为 fair 路径区分 deferred/error/token race，可在 worker 内引入私有结构化 attempt 结果，旧 `_claim_and_execute` 继续映射为原 dict/None。结果至少区分是否调用 claim、是否 committed、是否 token 复核成功、是否执行/settle、原 reply 和错误类别；禁止再次 claim 仅为获得错误详情。

### 5.2 内存状态与清理

| 状态 | 语义/生命周期 |
|---|---|
| `next_scope_after` | 最近访问 scope UUID，visit 开始即推进，blocked/失败不回滚；新实例 None。 |
| `effect_cursor[(scope,class)]` | 最近选中 `(created_at UTC,effect_id)`，比较使用解析后的时区时间与 UUID稳定序，失败也前进；无候选不推进。 |
| `host_streak[scope]` | 0..3；选择 host 饱和加一，选择 business归零；按尝试而非成功计数。 |
| `resume_cursor[scope]` | 以journal首次出现序号+effect ID为稳定锚点，选中/检查后推进；候选移除选严格后继并回绕，不用可变列表索引重置到首项。 |
| `attempted_effects: set[UUID]` | 每次顶层fair调用新建，返回/异常销毁。所有`db.claim`前检查并加入，包括prepared-ready；响应丢失/畸形也不能再次claim；claimed-token resume不加入。不实现失败计数/quarantine。 |
| `visited_this_pass`、`pass_progress`、`pass_pending` | 调用局部；从本调用实际起始scope开始，访问roster每项恰一次构成pass；pass结束后重置。不能跨调用拼成完整idle观察。 |

跨调用游标/streak仅属实例，不写DB/journal。每调用只清理离开roster的per-scope映射；不得清除标量`next_scope_after`，它仍用于新roster严格后继定位。调用局部集合不跨调用保存。cold从排序起点重置；频繁重启可反复偏向起点，保留跨重启公平债务，不声称由DB重建warm历史。

`RoundStats`保留旧字段/merge/progress语义；fair新增计数`scope_visits`、`new_opportunities`、`claim_conflicts`、`prepared_attempts`、`orphan_blocked`、`recovery_commands`、`recovery_applied`，以及`recovery_has_more: bool`、`manual_debt_ids: set[UUID]`、`pending_work: bool`、`stop_reason`（idle/budget_exhausted/blocked_no_progress）。recovered在旧入口仍是命令数，fair也不得冒充applied数；额外恢复字段按真实response记录：`response['recovery']`中的`applied`、`skipped`为数组，`manual_debt`为整数，`has_more`为bool（`49_recovery.sql:443`）；`recovery_applied=len(applied)`，不能用命令数代替。manual debt IDs由完整effects scan识别，不能把回包整数当ID集合。累计数求和；debt按返回时每scope最新完整观察的残留ID去重，已消失的debt移除，不永久union；has_more按scope最新回包维护；pending_work表示**返回时最近完整pass的残留工作**，不历史OR。若预算截断pass，保守pending_work=True。旧merge不累加rounds/idle，fair聚合显式设置rounds=scope_visits、idle和stop_reason，不依赖merge推导停止。skip/conflict/访问不计进展，执行/settle逐项累计；last_reply仅诊断。fair的`pass_progress`不使用legacy `RoundStats.progress`自动推导：只计实际执行、已确认settlement、`applied`非空的实际恢复状态推进，或D4成功落盘解除的本地debt；no-op recover即便命令计数增加也不算进展。D4核销不增成功settled/reconciled；启动核销不是scope visit，也不能替代完整pass的idle观察。

### 5.3 每 visit 的状态流

1. **Roster与ownership**：显式域先验证；默认调用 `db.host_scopes(scope=None,after=after_scope_uuid,limit=64)`，下一页取并验证`response['next_cursor']['scope_id']`为严格递增UUID（不是传cursor字典）。取得三个journal查询器的有限快照并去重；先排除已有`settlement_committed`的ID（普通或conflict payload均表示本地已核销），再逐项`host_effect`核验剩余ID的身份、有效状态与scope。必须先完成整个启动集合ownership核验，之后才可写入terminal核销记录；roster外且未核销的unfinished即便DB已terminal也报`HostContractError`，空roster亦如此。只有过滤后集合为空才可按空roster idle。roster内未finished且确认effect为`succeeded/failed/unknown/cancelled`的unfinished，以现有`settlement_committed`记录terminal/no-outcome conflict；见§6。保留closed scope的cleanup/release义务，不按closed_at排除。所有页保持授权；非法cursor/重复非推进cursor/错误信封fail-fast，不能当空页。完成枚举得到固定列表，但它不是数据库一致性快照；构建完成前没有公平窗口。
2. **选 scope**：确定性 RR，计 visit并推进 last scope；assert_all_idle。
3. **Reconcile**：取本 visit 开始的 pending列表快照，保持既有 token/outcome比对；同token重提原结果，无重复IO；terminal/changed token只记现有冲突。不得为了公平丢弃未确认 outcome。
4. **Orphan 检查 1**：对过滤后的unfinished dispatch逐项严格point-read。roster内effect已为四种terminal状态之一时，写入D4核销记录（不增加成功/执行计数）；ready保留既有恢复资格，claimed按lease判live/expired。live claim阻塞本scope并结束visit，RR继续；过期信息交recovery，不能把未知结果请求重发。读错误fatal。
5. **Prepared**：快照候选按该scope journal轮转，至多恢复一个；ready走已有claim；claimed须原token匹配且lease足够；终态记冲突；不足lease留待既有恢复。恢复后继续本visit（异常传播除外）。
6. **Orphan 检查 2**：重新读取过滤后的unfinished集合。准备执行若留下live dispatch，则停止该scope本次visit；确认terminal且ownership已通过则按D4核销；不能让它越过新工作选择。启动ownership的读不能当作以后visit的状态许可。
7. **Recovery**：最多一条`command_recover(scope,key,16)`；仅在发现非manual过期项时触发，manual-only不空转；has_more不在本visit循环清空。回包分别记录命令完成和实际处理数，现有`_recover`返回1只是命令计数，**不是恢复effect数**。recover后第三次检查orphan并重新point-read；例如启动时claimed、recover后terminal须以此新读核销，不能依据`recovery.applied`或缓存结果写标记。live状态仍只阻所属scope。
8. **Discovery**：该scope独立完整翻页，筛ready external五类；不做跨scope全局表扫描。完整scan结束后排除attempted_effects，再计算类别可用性；无未尝试候选则无fresh机会且ready残留使pending=True。与expiry预扫不可复用旧资格为写许可，最终claim重检。
9. **类别/同类选择**：按FC-2挑类别；该类按时间/UUID排序，从effect_cursor严格后继选首项，末端回绕。选中就推进类别游标与streak；单次顶层调用内每effect至多一次fresh claim，竞争后跳过至下次调用，不在本次调用反复抢同一effect。
10. **Claim/执行**：现有service claim、committed token、IDLE、host_effect token/status复核后执行；一次visit最多一个prepared和一个fresh，**顺序执行、最多一个在飞**。两次之间也重新assert IDLE。deferred/确认的stale或terminal竞争记claim_conflict，不授权IO/receipt。
11. **停止与idle**：visit结束先更新pass状态；若刚好完成pass，优先判定idle或blocked_no_progress，再判budget。因此S=1空scope、max_rounds=1返回idle；完整无进展但有债务返回blocked_no_progress；只有未满足停止条件且预算耗尽才budget_exhausted。pending按过滤后的逻辑未决集合计算，不能把原始`unfinished_dispatches()`中已写`settlement_committed`的历史再算债务。完整roster pass无进展且仍有ready/claimed、逻辑pending/prepared/unfinished、recover has_more/manual debt、live orphan或claim conflict，返回`idle=False/blocked_no_progress`并保留原因；`progress==0`绝不足以判idle。roster内terminal/no-outcome核销须先成功fsync/读回，才从pending扣除。只有完整观察一轮后没有可处理工作、未解决journal outcome、已知blocked工作或未决竞争，才可`idle=True`。空roster且无pending为idle。idle是该轮非原子观察的结果，不代表未来无到达；没有fresh discovery的visit也不满足FC-1。

### 5.4 各阶段工作量、分页和资源

令scope s一次effects scan观察到的external行数为E_s，`P_s=max(1,ceil(E_s/64))`；默认roster枚举页数`P_R=max(1,ceil(S/64))`，显式roster不调用该读者（0页）；pin页数同样至少一RPC。空effects集合的一次scan仍须一次读者RPC，不能写0页。Roster与scan均跨RPC无公共快照。

每visit expiry预扫加discovery最多`2P_s`个host_effects RPC；reconcile最多`2J_p`（一个host_effect加可能settle），prepared最多`J_r`，三次orphan复查最多`J_u1+J_u2+J_u3`（统一快照数界为`3J_u`）；J取**整个journal候选快照**，因为当前helpers可能先读再过滤scope。启动ownership额外`U`次host_effect（U为排除已有`settlement_committed`后的去重逻辑未决ID数；terminal核销复用该次point-read）；每visit另最多1次recover、fresh claim+重读2次、prepared-ready可能额外claim+重读2次（claimed-token复用无此pair）、至多两条执行路径各自pins/资格读与settle。错误分类额外重读按§6单列，不能漏算；orphan terminal核销复用三次orphan检查的point-read，不增加确认RPC。对V visits的分页部分为`P_R+2Σ(v_s P_s)`，Σv_s≤V；不是所有RPC总量。model路径另加`max(1,ceil(N_run_pins/64))`页/次，其他既有读写按实际rpc_log单列。

上述公式只描述启动且最终结束的有限scan所需分页读，不是READ COMMITTED动态扫描的绝对上界。无限新增scope/effect可追逐has_more而使枚举/scan不结束；O3已裁定本专项不增预算或增量扫描器，运行适用性仍为未验证限制，不能把不完整scan包装成完整公平窗口。每scope独立分页只分开授权与候选，不代表A长scan不延迟B墙钟；机会顺序不受队列长度加权。max_rounds不限制单visit页数、journal长度、响应字节、累计候选内存或时间。64是项数，request无全局字节上限；保留D-PF-1容量披露，不重复H13的64MiB硬上界误称。

## 6. 恢复、错误与取消边界

| 场景 | 行为与证据 |
|---|---|
| finished未settled（G9-J1） | 同token重提同outcome，不重发HTTP/工具；settle错误保留pending，不能虚构完成。 |
| recovery unknown胜旧success（G9-J2） | 旧journal只记conflict；run不revive、不生成旧run model successor、不重复IO。 |
| started未finished（G9-J3） | live隔离所属scope；expired经原recover；无自动重发授权。 |
| prepared无started | 原token、请求digest、kind、lease及现有执行前置复核；ready重新claim；最多一个恢复后继续fresh。 |
| blocked_unknown | 保持unknown_wall_delta：清interaction/pending_steer、turn/revision递增、只扣wall、既有unknown/run_blocked事件与pin/预算语义；scheduler不重投unknown。 |
| cancel_requested过期 | recover → cancel_late；cancel seal字节不变；不因配额修改取消语义。 |
| deferred/token race | 记录来源对应计数和竞争，零IO/receipt；推进fresh游标（仅discovery来源），本次顶层调用跳过；下次顶层调用重新读DB。不伪造claim。 |
| stale_claim/终态竞态 | 重读确认状态变化，转既有recover/移出ready；不把业务过期lease当第二attempt授权。 |
| invalid_args/unauthorized/其他协议错误 | claim invalid_args须按下表重读区分terminal race；非竞争协议错误立即HostDBError，不隔离或重试隐藏配置问题。 |
| receipt_conflict | 保留原journal outcome，按既有reconcile冲突路径；不覆盖receipt或发新IO。 |
| settle replay | 仍按既有非错误结算路径记账，无额外dispatch。 |
| manual debt/has_more | 显式pending/debt；manual不自动清偿，has_more留待后续visit，不宣称idle。 |

Claim/settlement按阶段的精确分类如下（代码依据：`v24/sql/30_advance.sql:579`、`:880`及`worker.py:342`、`:688`）：

| 观察结果 | fair路径动作 |
|---|---|
| Claim `deferred`，claim token为空 | 预期live-claim竞争；该次尝试计数，零IO/receipt，本effect本次顶层调用内跳过。非空/畸形token为协议错误。 |
| Claim `stale_claim` | 至多一次`host_effect`重读确认：当前是已过期business claim、terminal，或与选中时状态/token不同的可验证竞态。确认后计数并抑制该effect，交既有recovery额度，不发第二次business attempt。读失败、畸形或无法证实竞态则fatal。 |
| Claim `invalid_args` | 重读一次。当前terminal则确认终态竞争，按O5抑制；仍nonterminal则为畸形request/lease等协议错误，立即`HostDBError`。当前SQL终态claim返回`invalid_args`，不能期待`already_terminal`。 |
| Claim `committed`及结构有效token | 一次`host_effect`重读；claimed状态和token完全匹配才授权执行。状态/token不匹配视为零IO token race，本调用抑制；读失败或envelope畸形则fatal。token需具备有效attempt/fence整数及owner字段，不能凭字典非空授权。 |
| 未知disposition、committed缺token、畸形envelope/cursor、driver异常、`unauthorized`、`effect_id_conflict`及其他非竞态错误 | 立即`HostDBError`/`HostContractError`或传播driver异常，不转成可跳过冲突，不再次claim取详情。 |
| Settlement正常`committed`或`replay` | 按既有结算结果/事件记账，无额外dispatch；冲突标记仍不等于业务完成。 |
| Settlement `receipt_conflict`/`stale_claim` | 保留durable outcome交reconcile/冲突路径；不转成fresh-claim冲突或新IO。其他settlement协议错误fatal，不沿用legacy全部错误返回False的映射。 |

**D4 terminal/no-outcome 核销**：只针对`unfinished_dispatches()`中的ID，且当前没有`dispatch_finished`或`settlement_committed`。启动时ownership point-read同时可用于本轮核销；整个启动集合ownership校验通过前不得追加任何标记。只对roster内且本次有效读确认effect状态为`succeeded`、`failed`、`unknown`或`cancelled`的记录，复用`_record_settlement()`写入`{"conflict":true,"reason":"database_terminal_no_outcome","database_status":<status>}`；digest、可选run_id和原claim取最近`dispatch_started`；原记录无claim时按既有conflict写法使用空字典，缺少合法started元数据时报journal错误，不从已清空的terminal行拼造token。此处no_outcome仅表示journal没有`dispatch_finished`，不能推断外部IO未发生。不得追加dispatch_finished、业务outcome、receipt、`reconciled=true`或成功计数，也不调用settle/recover。若effect在最后一次检查后才终态，保守保留pending至下次visit/调用；不承诺即时发现并发终态。只在journal append及fsync/读回成功后从逻辑pending中排除；已有settlement_committed的普通或conflict记录均过滤，即使原查询器仍返回unfinished。off-roster且无settlement标记即使DB terminal也先报ownership failure；ready、claimed(live/expired/manual)、run状态不能替代effect terminal。recovery后terminal必须由第三次orphan检查重新读取；这三次orphan及启动ownership已计入§5.4，无额外确认RPC。所有point-read/envelope/身份错误及journal写入错误严格失败。

fair路径必须使用严格wrapper校验读者、claim、settle、recover响应；不得复用legacy `_reconcile`/`_resume_prepared`/`_orphan_state` 对point-read错误静默跳过、`_expired_claims`把读/cursor错误当False、`_recover`把错误当零、`_settle`把所有错误当False的映射。上述legacy入口保持现有语义以兼容。claim错误按上表分竞态和协议错误；reconcile及prepared/orphan的读错误、recover错误envelope、非法cursor、settle畸形响应及其他非竞态错误均fail-fast。`HostDBError`/驱动异常、`HostContractError`（特别是连接非IDLE）、`HostCrash`、`JournalError`/`JournalVersionError`/`JournalCorrupt`/`JournalLocked`均终止当步并沿原路径传播/恢复，公平入口不自动重试。`AdapterFailure`保持现有no-IO failure settle；`ProviderRejected`/`ProviderUncertain`/`OSError`沿现有adapter failure/unknown映射，不能一概改为抛出或重发。callback/fixture hook异常也不得吞掉。

内核封闭24码不变：invalid_args、unauthorized、not_found_or_denied、request_conflict、effect_id_conflict、receipt_conflict、stale_generation、registration_stale、already_terminal、owner_closing、install_not_ready、interaction_mismatch、provider_unavailable、scope_closed、dependency_unresolved、provide_conflict、install_identity_conflict、budget_exceeded、invalid_outcome、stale_claim、cleanup_cycle、retry_with_closure、blocked_unknown、spawn_key_conflict。claim committed/deferred和settlement replay语义不变；host侧诊断不新增内核码。

## 7. Fake-only 模型与验证设计

### 7.1 模型映射与证据层次

| 模型对象 | 实现映射 |
|---|---|
| turn / roster | 新入口一次scope_visit / effects.scope_id，host_effects按scope过滤。 |
| fresh opportunity | 实际选择并尝试claim，失败仍计机会、成功/执行单列。 |
| restore work | reconcile/prepared/orphan/recover单列计数与额度，不能冒充新机会。 |
| claim success | committed+非空token且后续host_effect状态/token一致。 |
| completion | journal与DB已确认的settlement，conflict标记不算业务完成。 |
| 模型边界 | 有限S/k/N/J/V；时钟/响应受控；不建模真实provider延迟、G/OS公平、多主机或长期开放到达。 |

不能只用打印RR序列证明实现。`fair_support.py`提供独立有界参考状态机，枚举S∈{1,2,3}、每类候选数0..2、streak0..3、所有cursor起点、空/blocked/竞争结果和budget截断，检查FC不变量与有界可达性质；保存枚举规模、最大步长、反例最短轨迹。若状态空间缩减，说明对称性/有限界，不从枚举推出任意N的定理。

生产选择器必须由新入口实际调用；模型以独立规则计算结果，与生产选择器逐步等价比较（scope/class/id/cursor/streak/终止理由）。不能复制实现函数作为期望值。数学上界推导覆盖任意有限S/N，枚举与集成用于发现实现偏离，三者相互补充。

选择seam仅用于模型、零写、脚本化错误；**G11-A/B/C/E/F/I/J/K至少包含真实HostWorker+HostDB+PostgreSQL fixture路径**，claim/token/execute/settle不能全部stub。使用G9脚本化adapter或Fake handlers，记录实际claim/重读/执行顺序。G11-G可以注入竞争信封但须另有真实两连接竞争/终态race证据；G11-H选择快照可stub，另核对真实journal恢复窗口。生产代码不新增测试专用SQL/公开API。

### 7.2 夹具、隔离与封锁

- 复用setup_db，唯一disposable DB、四角色、12 SQL同事务加载、闭合catalog、v24_fake.journal；每个隔离case使用全新HostJournal，另用新fixture或唯一scope及显式roster，防止跨case journal debt污染。gate串行，不是pytest。
- owner仅做明确fixture播种。结构有效model/tool需真实run/pins等；优先复用G9/G2b完整run夹具；不能用畸形request在实际claim路径伪造成功。>64 ready通过seed_effect循环或s12 fixture-only批量helper，另保留terminal seed_history以检验过滤。
- 选择与IO证据写owner-autocommit的`v24_fake.journal`或由现有durable journal支持的测试证据；进程内列表/计数可作即时断言，不能是唯一持久结果。记录case、visit、scope、class/effect、claim结果、cursor/streak、恢复计数、stop_reason；不写prompt/content/key/DSN。模型trace摘要附参数与最小反例。
- 纯选择前后十表snapshot/diff/fingerprint一致；真实claim/settle/recover集成按预期delta检查，不能错误要求整个执行零写。D4终态核销另断言仅有journal本地记录、十个域表零写，且重启后不因原始unfinished查询结果重复阻塞。测试journal不属于产品十表。
- G11全生命周期try/finally包住`install_no_network/restore_no_network`，拒绝socket connect/create_connection、urlopen与真实provider opener；仅允许既有Unix PostgreSQL基础设施。测试不得打开真实网络socket。
- FakeLLM/FakeTool及ScriptTransport均使用有限脚本；脚本耗尽立即失败，不默认成功、不随机补响应、不回退真实provider。
- 静态扫描新s12全部py与新增/修改host路径，复用G9 `FORBIDDEN_IMPORTS`、time.sleep、FROM V24.禁项及11函数调用集合；scan规则只覆盖已有允许例外，不能为测试放宽产品边界。journal秘密拒绝、0700/0600、二写者flock继续由G9覆盖。
- held_g/wait_for_g_block/assert_no_wait_cycle/held_open_then_probe/two_orders、G2b ordered_advance_race只用于确定顺序与安全；READY/go握手而非sleep/随机压力。held-G期间读者零写/无等待环，不推断调度公平。

### 7.3 ADV / G11矩阵

| ID | 确定性构造 | 断言与失败条件 |
|---|---|---|
| ADV-1 / G11-A | 实现前保存旧单scope只驱A的域缺口演示；另在同scope不断补host候选、保留business的旧优先反例。后以显式A/B roster和合法Fake执行，保证测量窗口持续ready。 | 旧域演示不称内部跨scope bug；新FC-1机会各k；真实claim/settle符合序列。任一scope少于k失败。旧反例脚本以“预期缺口被复现”成功退出，不把实现红gate提交。 |
| ADV-2 / G11-B | 同scope ≥4 host与持续business；选择模型和真实执行各跑；prepared-ready host与discovery fresh按两种先后交错，包含同effect与不同effect。 | discovery fresh前三host、第四business；prepared-ready按恢复来源计数且不推进streak/cursor/opportunity，但与discovery共享调用内物理claim guard；claimed-token resume无新claim；最多一个prepared+一个fresh顺序执行，不同effect仍可fresh。第四fresh仍host/同effect重复claim/两在飞失败。 |
| ADV-3 / G11-C | A ≥65真实ready external（含同timestamp稳定UUID边界）+terminal history，B ready；实际分页。加入空集合及正好64/128边界。 | 每页≤64，完整遍历无重复/遗漏、游标推进；B下一轮visit不按A队列长度加权；不声称墙钟不延迟。选择十表零写；实际执行delta正确。 |
| ADV-4 / G11-D | 固定A/B，在B scan前、页间、scan后用握手插入/终结项；另在roster构建后加scope。 | 仅在静态/持续可见条件断言完整考虑；动态页间不冒充快照；新scope下次调用；无限尾插属于O3确定的预算/前置边界。 |
| ADV-5 / G11-E | A journal started无finished、DB live claim，B合法ready；实际worker。另覆盖A终态、已核验ownership。 | live A orphan_blocked+idle=False；B仍获机会；A零重复IO；roster内terminal可D4核销，完整无进展pass不能被标idle。 |
| ADV-6 / G11-F | A 17个过期replay_safe host，加manual debt，B ready；真实recover。另manual-only；用过期unfinished dispatch使三次orphan复查均可到达。覆盖recover后terminal必须由第三次fresh point-read核销。 | 每visit≤1 recover、每命令应用≤16、has_more后续visit；manual-only不重复空recover；B继续；分别核对启动ownership U与三次orphan `J_u1+J_u2+J_u3`实际RPC；命令数、`recovery.applied`行数、manual debt分开；manual/ready/claimed debt仍pending，terminal核销复用point-read且无额外RPC。 |
| ADV-7 / G11-G | scripted claim seam覆盖deferred空token、terminal目标`invalid_args`与malformed-request `invalid_args`、stale重读确认/失败、committed token mismatch/畸形envelope、unauthorized、settle错误及recover/read错误；真实两连接竞争与receipt_conflict；同scope多visit、队首wrap-around及第二候选。 | 零未授权IO/receipt；terminal invalid_args重读后可跳过，nonterminal invalid_args及错误/矛盾重读fatal；游标让其他effect仍得机会；每effect本次顶层调用最多一次物理claim，deferred/stale/terminal/token race均抑制到下次顶层调用再读；prepared-ready与discovery交错共享guard；settle冲突保留证据。 |
| ADV-8 / G11-H | 两次cold运行前恢复相同DB+journal prefix，或造两套相同fixture；config/roster/transport脚本相同并持久记录选择。另warm/cold比较及每步重启反例。 | lease-independent或远离过期边界条件下cold序列一致；不把G9 FakeClock当作host/SQL时钟，不宣称lease边界恢复决定受控。不能直接顺序跑两个已共享改变状态的worker充当相同输入；不要求warm=cold，不宣称跨重启公平。 |
| ADV-9 / G11-I | 复用G9-J2真实unknown/blocked_unknown与旧success journal，运行新入口；另以started/no-finished且DB为unknown构造terminal/no-outcome。 | 有dispatch_finished的旧success走原reconcile，不降格核销；started/no-finished按D4追加指定conflict，保留原digest/claim，不伪造outcome/成功/receipt；无revive/旧run successor/重复IO，interaction/pending/预算/pin/事件按SQL原义。 |
| ADV-10 / G11-J | cancel_requested的expired claim，保存cancel seal字节，真实recover。 | reason=cancel_late，seal不变，effect不再claim/执行。 |
| ADV-11 / G11-K | ≥2 scopes，同worker连续max_rounds=1；空roster、非正/非法参数、roster增删、blocked无进展、完整空pass与预算边界；各ownership失败case独立journal。已解决的started/no-finished带普通及conflict settlement记录并置于roster外；未核销off-roster unfinished置DB terminal。 | 每次≤1visit，后继继续；blocked残留idle=False；S=1且max_rounds=1的空scope完整pass优先返回idle；空roster仅过滤已核销项后的逻辑未决集合为空才idle。roster外已有settlement记录不读DB/不阻塞；roster外无标记即使terminal也在任何核销写入前ownership failure；缺失/拒绝/畸形读同样失败；预算截断pass idle=False；未完成窗口不算公平结论。 |
| ADV-12 / G11-L | ≥3 scope ready负载1/3/50，维持活跃集合；单类/双类、失败首项、N项全cursor起点，模型与生产等价；另造empty/conflict visit。 | 仅opportunity-dense窗口（每visit完成discovery且恰有一次discovery-originated claim）断数值界：各scope机会相等/任意前缀差≤1、effect在N类机会/4SN全局机会界内尝试；empty/conflict轨迹保留所有visits，只断RR visit轮转；候选耗尽后缩小集合须重新起窗。 |

### 7.4 D4 journal核销专项区分（复用G11，不新增gate）

- **K / 已解决历史与归属**：started/no-finished分别带普通和conflict `settlement_committed`，置于roster外并让point-read不可用，断言不读该ID且不留pending；对无标记的域外terminal则ownership failure，不得写核销，空roster同样失败。启动集合后一个ID失败时，前一个terminal ID也不得提前写标记。
- **F / I / 四终态与真实恢复**：roster内unfinished分别为`succeeded/failed/unknown/cancelled`，至少一个真实recover到unknown；断言指定reason/status、原digest/run_id/claim保留、只有一条核销记录、十域表零写、无新dispatch/伪outcome/receipt/业务成功计数；其他工作清空后可经完整pass返回idle。
- **E / F / 非终态**：replay-safe recover到ready、live claimed、expired/manual claimed，以及run terminal但effect未terminal，均不得写terminal/no-outcome标记；原恢复资格与debt保留。启动claimed→recover terminal时，必须在第三次orphan检查重新point-read；不能凭启动缓存或applied行收口，且不额外做第四次确认读取。
- **I / 有durable outcome优先**：已有`dispatch_finished`的旧success与DB unknown冲突，继续原reconcile并保留原outcome，不能降格为no-outcome。
- **G / 错误与元数据**：缺失/拒绝/畸形/未知status/身份不匹配/驱动错误不能当终态；缺少合法started元数据或digest/token不合法也不得合成证据。按启动ownership与后续严格错误路径各自终止，零标记、零虚假idle。
- **H / 持久化与重启**：核销成功后重启不重复追加、不再被原始unfinished阻塞；在append/fsync/读回窗口注入现有journal失败与尾行中断，未成功核销时仍重新核验，不预先解除pending；不修改现有journal格式或尾行恢复规则。

## 8. 逐文件影响与取舍

| 文件 | 后续影响/依赖 |
|---|---|
| `v24/host/worker.py` | 唯一产品实现修改：新入口、内部选择/attempt结构、RR/cursor/burst、fair恢复额度、stats；复用旧执行核心，旧入口兼容。 |
| `v24/s12/fair_support.py`（新） | 模型/枚举、有效多scope/ready播种、durable测试trace、脚本化竞争、snapshot/顺序辅助；不建新产品表。 |
| `v24/s12/test_g11.py`（新） | G11-A…L独立脚本、--only、网络/静态/catalog/零写guards与真实DB集成。复用S1，不新建setup_db。 |
| `v24/s12/README.md`（新） | FC、假设、参数、矩阵、命令、真实结果、未覆盖范围。 |
| `v24/s7/README.md`、`s9/README.md`、`s10/README.md` | 新合同/证据与D-S7-2剩余债务；原G6/G8/G9历史范围不改写。 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 专项FC/G11扩展行，source_sha/时间/exit，历史11/11和G8/G9/G10计数不变。 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | O6限定子合同已验证、D-S7-2主债务继续开启、RR取舍及剩余债务；同步重复摘要。 |
| 本计划 | 后续只追加真实执行/偏差记录，不能提前填通过。 |
| 正式post-closeout-followup计划 | 只在后续登记处追加专项链接，保留M-F/M-P历史。 |

不修改：全部12 SQL、loader两个元组、HostDB调用表/接口、HostJournal版本/事件/核心格式、S1角色/OID/catalog逻辑、既有s1–s11 gate、v15/v13/v99。若实现证明这些边界必须改变，停止该方案并修订独立设计，不顺手扩范围。

取舍：RR给等机会不等时长；失去DRR异构权重/债务能力。循环同类顺序给静态有限候选上界，不是假FIFO或无限到达下age保证。内存状态简单但warm历史不可恢复；scan累积内存和RPC随负载增长。恢复额外dispatch不计fresh但有独立上限；不把配额称全部IO等量。

无schema或journal迁移。回退是停止使用新入口、切回旧单scope调用；已写journal与DB结果保留并按原恢复语义处理，不能删除未settled outcome。后续撤回实现用正常revert并跑回归，不删除历史证据或改写SQL。

## 9. 执行索引、里程碑与验证命令

### 9.1 工作项索引

| Item | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| P0 | 核对基线/授权/版本/命令 | source树、冻结diff、12文件顺序、D-S7-2位置和环境清单明确 | AGENTS、本计划、正式前计划、matrix/ledger | 本计划裁定完成 | S |
| M-F1a | 定稿反例、模型和失败边界 | 旧缺口/优先反例可复现，参考模型与contract匹配；不伪称新实现通过 | s12支持/模型、worker待修改点 | P0 | M |
| M-F1b | 实现host-only调度并完成G11 | 所有FC、ADV及真实DB集成全绿，legacy不变 | worker、s12三件套 | M-F1a | L |
| M-F1c | 回归与收尾发布 | §9.2全量适用验证exit0、文档一致、按路径commit并立即push | matrix/ledger、s7/s9/s10/s12 README、本计划 | M-F1b | M |

**里程碑只有 M-F1 一个**，a/b/c是同一stage的内部依赖工作项，不是各自可积压的完成gate。源码反例与实现前记录保存在同一reviewable工作树，先复现再实现；不提交故意红的新实现gate。M-F1全部测试通过→更新工件→立即单里程碑提交/推送；不得做完后累积其他里程碑。若执行另拆stage，先修订计划并为每stage列全量gate/收尾/立即发布边界。

顺序：P0核实→保存旧反例→锁定模型/断言→实现worker→G11全量及单case→既有全量回归→收尾一致性→commit/push。任何失败停在当步修因，不降低标准。源码记录区分HEAD与未提交执行树（diff/树摘要），记录executed_at（Asia/Shanghai）、完整source_sha、命令、exit、输出摘要和工件位置；证据文档追加不冒充同一源码已重跑。

### 9.2 精确命令

以下是计划阶段冻结的从 worktree 根串行执行清单；M-F1 已按此清单及 G11 A…L 扩展实际执行，逐命令证据见 §13。冻结 closeout 顺序来源正式前计划 :538–555，恰 11 条：

```bash
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s2/test_g3a.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s5/test_g4.py
uv run python v24/s6/test_g5.py
uv run python v24/s8/test_g7.py
uv run python v24/s7/test_g6.py
```

既有extension / offline兼容（均需exit0，单case不代替全量）：

```bash
uv run python v24/s9/test_g8.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py
uv run python v24/s11/test_g10.py
uv run python v24/s11/test_node.py --node
UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke
uv run python -m v24.host.plugin_smoke
uv run python -m v24.host.plugin_smoke --multilingual-smoke
```

smoke无flag只证明not_requested/exit0，plugin无flag同样不是生命周期证明；G10、Node、multilingual才提供对应执行证据。Node缺工具链exit2是未验证，不能登记通过。真实provider带flag不在本计划验证清单，不调用、不查询key。

新增G11（路径是**待创建**实现工件）：

```bash
uv run python v24/s12/test_g11.py
uv run python v24/s12/test_g11.py --only G11-A
uv run python v24/s12/test_g11.py --only G11-B
uv run python v24/s12/test_g11.py --only G11-C
uv run python v24/s12/test_g11.py --only G11-D
uv run python v24/s12/test_g11.py --only G11-E
uv run python v24/s12/test_g11.py --only G11-F
uv run python v24/s12/test_g11.py --only G11-G
uv run python v24/s12/test_g11.py --only G11-H
uv run python v24/s12/test_g11.py --only G11-I
uv run python v24/s12/test_g11.py --only G11-J
uv run python v24/s12/test_g11.py --only G11-K
uv run python v24/s12/test_g11.py --only G11-L
```

冻结核对（源/候选树，期望exit0；另比P0起点确认全部SQL、loader、db/journal无改）：

```bash
git diff --exit-code 996cb5bc86f38fe5cbc21d058e93df54b4923620 -- v24/sql/10_schema.sql v24/sql/20_triggers.sql v24/sql/30_advance.sql v24/sql/40_interpreters.sql v24/sql/45_capability.sql v24/sql/46_cleanup.sql v24/sql/47_verbs.sql v24/sql/48_loop.sql v24/sql/49_recovery.sql
```

收尾顺序依AGENTS：测试全绿→matrix/ledger/stage README→`git status`→逐路径`git add <path>`→再看暂存区及敏感内容→正常hook的`git commit -m 'v24: ...'`→立即正常push。禁止add-all、force、reset-hard解决分歧、no-verify。若实施仍在v24分支，不能用`git push origin main`误推未含新提交的陈旧本地main：遵循既有隔离发布惯例，把已验证v24源合入最新origin/main候选、验证实际候选并正常推HEAD到main；远端分叉无法安全处理时才请求用户决定。原发布授权持续有效，但**本轮仅规划不执行Git发布**。

## 10. 收尾判据、风险与剩余问题

无阻塞性开放设计问题。可由用户覆盖的假设为O2 burst=3（未实测偏好）、D2 worker专用journal/roster覆盖（范围约束）、D3不加调用方合作取消/deadline（范围约束）；覆盖任一项时先修订相应FC、接口和验证，不将假设写成用户已确认需求。

未来M-F1完成要求：已裁定FC全部有确定性模型与G11证据；A…L全量和单case实跑；纯调度零域写、真实执行预期delta、11 RPC/网络/静态guard不变；§9全部适用验证exit0；matrix、ledger、stage README、计划记录引用同一FC/case/source树/时间/exit；D-S7-2状态依O6而不是依据绿色计数自行缩窄定义。

风险：warm游标在重启丢失；无限到达/大journal导致单visit不终止或成本增长；claim机会不等于成功；错误被隔离会隐藏权限/配置；恢复prework与新工作配额混计；旧入口未接入新调度时无跨scope承诺。每项分别由H/D/F/G/B/A用例和文档限制覆盖；无法由Fake排除的生产条件保留债务。

剩余未验证范围必须保留：普遍starvation-freedom、墙钟等待/debt有界、跨崩溃/多主机公平、真实provider时延/可用性/费用/模型质量、第二批语言。不能因G11通过改写历史closeout 11/11、G8 23/23、G9 11/11、G10 8/8，或把本计划作为任何已运行结果。

## 11. References

- `docs/plans/v24-post-closeout-followup-2026-10-25.md:369`（触发条件）、`:523`（冻结）、`:538`（精确命令）。
- `docs/designs/v24-db-native-agent-system-2026-10-22.md:1123` §17.2/17.3 与 §18（活性模型/环境假设）。
- `docs/reviews/v24-deviation-ledger-2026-10-23.md:258`、`:552`；`docs/reviews/v24-conformance-matrix-2026-10-23.md:217`、`:224`、`:530`。
- `v24/host/worker.py:88`、`:102`、`:152`、`:205`、`:263`、`:314`、`:342`、`:688`；`v24/host/db.py:30`、`:135`、`:144`、`:174`、`:184`、`:195`、`:204`；`v24/host/journal.py:273`、`:288`、`:300`。
- `v24/sql/49_host_reads.sql:129`、`v24/sql/49_recovery.sql`、`v24/load.py:9`；`v24/s1/setup_db.py:555`、`v24/s9/h_support.py:213`、`v24/s7/g6_support.py`、`v24/s6/g5_support.py`。
- `v24/s10/test_g9.py:91`、`:117`、`:1349`、`v24/s11/test_g10.py`、`v24/s11/test_node.py`、`v24/host/plugin_smoke.py`、`AGENTS.md`。

## 12. 保真核对与设计修正记录

基线为本次context_builder导出的Generated Plan（不含前置prompt/selection），及同chat续导出的补充；完整读取后按以下清单维护。Phase 7.5最终保真核对于2026-10-25完成；覆盖清单逐项对应到下表，并以§12.2审查报告核对结论。

| 基线内容组 | 本文位置/处理 |
|---|---|
| Summary、host-only范围、旧接口兼容、非目标 | §1、§5、§8 |
| 当前worker顺序/DB两连接/G/journal/读者/每run约束 | §2、§5–6 |
| RR/DRR、burst3、created_at循环、scope来源、内存状态 | §3–5；开放选择交Oracle |
| FC1–6、两类假设、cold输入包含journal、无wall-clock | §4，新增per-effect界且不将每run等同每scope |
| 11步算法、恢复后fresh、scope隔离、recover16/manual | §5.3、§6 |
| 分页/RPC/J/pins/动态到达/累计内存 | §5.4、§4.3；纠正空页RPC和无限到达前提 |
| 冲突/unknown/cancel/24错误/adapter边界 | §6；O5循环跳过、严格错误分类及D4 terminal/no-outcome核销与恢复后重读 |
| 模型映射/Fake/guard/seed_history/持久trace/ADV1–12 | §7，补独立枚举和命名真实集成覆盖 |
| 逐文件/禁止修改/回退/风险 | §8、§10 |
| 依赖顺序、全部命令、工件、commit/push | §9；补精确11条，合成一个完整stage里程碑 |
| 限定子合同/剩余未验证范围 | §3 O6、§10；FC 子合同可登记，D-S7-2 广义主项继续开启 |

### 12.2 Phase 6审查、补裁与最终核验

独立设计审查报告：[v24 D-S7-2 fairness plan critique](../reviews/v24-d-s7-2-fairness-plan-critique-2026-10-25.md)。其发现已逐项处理：FC-1数值界限定在opportunity-dense窗口；pass状态和真实进展定义补明；idle先于budget的边界固定；recovery命令数/applied/manual debt/has_more分离；三次orphan读取与RPC上界补齐；标量scope anchor保留；默认roster next_cursor严格取scope_id；claim/settle错误精确分类；cold fixture一致性和FakeClock边界明确；G11覆盖恢复/ownership/错误与数值前提。

Oracle原始裁定记录在本会话chat `v24-d-s7-2-fairness-desi-00F277`，日期2026-10-25：O1–O6、D1–D3及针对审查后terminal unfinished接缝的D4。D4新增`settlement_committed` conflict核销，是现有格式支持的本地no-outcome冲突记录；不代表业务完成，且整个ownership集合核验成功后才可写。D2专用journal、D3无调用方取消参数是范围假设；O2 burst=3是未实测偏好假设。Phase 7.5对context_builder两个导出生成正文逐项walk：当前源码分析、接口/状态/流、FC与前提、分页/RPC、恢复/错误、Fake/ADV、逐文件、取舍回退、顺序/命令/发布义务及未验证债务均在对应章节保留；源码证据纠正与D4实质增补见§2.4、§3、§5–7。最终命令、引用和符号按worktree源码再次核验；无material open question遗留。保真检查完成后，已清理本次两个`oracle-plan-2026-10-25-151628-…-0d54.md`与`oracle-plan-2026-10-25-153303-…-8d91.md`临时导出；保留本文、审查报告与Oracle裁定来源。设计阶段不涉及实现；后续实现与发布结果记录于§13。

对基线的实质替换须由§3裁定/审查证据支持：quarantine→单次调用循环跳过、idle条件、scan终止域、原债务保留；不以精简为由删除正确细节。历史冻结/正式计划归属/plugin交付状态等已核实纠正见§2.4。最终审查工件链接与裁定来源已在本节及§13补充。

## 13. M-F1 执行记录（2026-10-25）

M-F1a/b/c 作为一个里程碑完成。实现仅修改 `v24/host/worker.py`，新增 `v24/s12/fair_support.py`、`v24/s12/test_g11.py` 与 S12 README；12 个 SQL、`v24/load.py`、`v24/host/db.py`、`v24/host/journal.py` 与 legacy 入口相对 P0 基线 `996cb5bc86f38fe5cbc21d058e93df54b4923620` 均无 diff。全量验证 runner 在清除 provider 凭据并设置 `UV_NO_ENV_FILE=1` 的环境下执行 31/31 命令，全部 exit 0；逐命令时间、输出摘要、日志 SHA-256 和树摘要见 [`docs/reviews/v24-d-s7-2-fairness-execution-2026-10-25.md`](../reviews/v24-d-s7-2-fairness-execution-2026-10-25.md)。

审查期间修复并回归了 no-IO finished 重入 prepared、settlement effect 身份校验、terminal outcome 相等性、跨 scope pending 污染、no-IO 进展计数、pin cursor 绑定、独立模型停止决策以及 D4 部分 marker 起点。G11 提供有限 Fake-only FC 子合同证据；O2 burst=3 仍是未测量偏好假设，D-S7-2 广义公平债务保持开启。
