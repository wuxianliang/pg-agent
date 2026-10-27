# Cordis v2 DP3：失效传播与可逆退役 Deep Plan

> 本文描述完整 DP3 计划；已交付范围以 §8 各阶段 result 为准。B0=`ba4f533`、W1=`103ec596`、W2=`72af2528`、W3=`284d7f2` 已发布。W4 已于 2026-10-27 在 W3 基线上实现并通过 24 条串行门禁；本提交发布 W4 到 origin/v24。W5 仍未实现。所有相对路径均以 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` 为根；main checkout 不含此 Cordis 实现。

## 1. Goal 与完成边界

在已完成 DP1/DP2 的 Cordis v2 内核上，交付完整的传递 live 派生、控制漂移与失效传播、L-Divert/L-Raise/L-Leave/L-Unload、两段 withdraw/release、闭集 inverse、activation/run pin release、P6 drain 屏障，以及已激活实例的有界 dispose 清理。沿用 `advance(uuid,jsonb)`、八张领域表加两张簿记表、G 锁、same LOGIN continuation、I7 单 reconcile 槽位、单聚合事件和现有 24 错误码闭集；不把DP3扩成新调度器或跨 LOGIN 执行系统。

DP3 完成的证据必须区分生产命令与构造事实：service/child 的创建、激活、退役和清理经真实 `advance`；cell/reservation/listener/unknown/run 若生产入口尚不存在，只能由 owner fixture 构造事实，再经真实协议验证账本或阻塞语义。fixture 不证明生产注册、dispatch、完整 run 回路或外部恢复。DP4 settlement，DP5 listener/dispatch/intercept/overlay，DP6 全宿主公平扫描、崩溃矩阵和 unknown 外部对账仍不实现。

验收还要求：command 屏障 deferred 十表零写、不消费 request/receipt、不产生 successor；调用方结束事务释放 G 后再等待；旧 continuation 身份校验与正常控制代/target drift 分类分离；P2 批次失败时同一 `advance` 原子记录 Raise，且未知 SQL 异常仍原样失败；旧 pin 在 drain 期间仍可读；历史 FK 不被物理删除破坏；清理每批有界；所有适用旧 gate 和新增 DP3 gate 按阶段串行实跑并更新证据工件。

## 2. Current-state analysis

### 2.1 权威、基线与 DP2 收尾

唯一产品规格是 `docs/designs/cordis-plugin-system-2026-10-25.md`。DP1 将 DP3 划为 live/失效传播、Divert/Raise、leave/unload、withdraw/release、inverse、activation/run pin release、drain 和已激活实例 dispose；DP4 是 run/model/tool settlement，DP5 是 dispatch/listener/intercept/overlay，DP6 是全宿主扫描、公平性、崩溃恢复和 unknown 外部对账。参见 `docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:206-219`。

本计划的已知起点为 v99 工作树 `v24@9fe6b5b`；DP2 W5 在较早 `d5fd1bc` 基线上的 21 条命令退出 0 是历史记录，不是 DP3 的新验证。B0 重查实际 HEAD、upstream、工作区、工具链、frozen hash/diff 与门禁，不复制历史退出码。DP2 conformance matrix 的 Scope/B0 状态、deviation ledger 的 W4 状态和 DP2 README 有互相矛盾的过期描述；B0 基于提交链和原始记录订正“当前状态”，保留旧阶段事实和原始测试结果，不伪造新证据。参见 DP2 matrix `:7, :185-204`、ledger `:47-64`、`v24/cordis/dp2/README.md:159-179`。B0 已于 2026-10-27 按提交链订正这些当前状态：当前 HEAD 为 `9fe6b5b`，与 `origin/v24` 对齐；2026-10-26 的历史行和退出码保留。新的 21 条退出码只写在 DP3 工件。本段对矛盾的描述保留为计划编写时的起点。

DP2 ledger 中 `origin/v24` 授权只针对 DP2；仓库 `AGENTS.md:7-57` 对后续里程碑写有逐里程碑全绿、工件更新、逐路径 stage、commit、push `origin main` 的纪律。DP3 的首次发布目标存在用户授权冲突，Oracle 不能代为授权。规划当时尚未取得发布授权。2026-10-27 用户明确授权全部 DP3 里程碑逐个 commit 并 push `origin/v24`，不改写 `AGENTS.md`。B0、W1、W2 已分别发布为 `ba4f533`、`103ec596`、`72af2528`。W3 的门禁已在 W2 基线上完成，本提交发布 W3 到 origin/v24。

### 2.2 当前调用链与数据关系

命令路径目前为：信封/canonical 输入预检 → `G=(24,1)` → session_user/role family 认证 → request replay-first → continuation 身份检查 → command seed、closure 发现、有序锁、锁后复验 → install/reconcile/dispose interpreter → typed delta/domain 验证 → FK 序应用器 → effect/request、单聚合 event 和 successor → 调用方提交。关键入口在 `v24/cordis/sql/40_advance.sql:1014-1130`，delta 验证与应用在 `:357-565, :623-1012`。

| 组件 | 当前事实与 DP3 接缝 |
|---|---|
| `40_advance.sql` | `barrier_ready()` 当前恒 true（`:205-206`）；command `off/retry` 早期 `0A000`（`:1041-1043`）；仅 claim 分支已有 deferred（`:1109-1111`）。`continuation_state` 同时检查身份与 generation/target/phase 漂移（`:278-331`）；锁后还有复验（`:604-611`）。typed delta 只有既有 install、control、begin、append、progress、activate、basic dispose 等 op，domain 分支无 P3/P5/P6（`:357-565, :623-930`）；当前 successor 只允许 reconcile（`:962-963`）。
| `41_lifecycle.sql` | DP2 的 manifest/check/install、resolve、activation、reconcile 和 dispose 主体。`interpret_reconcile` 只完成 P0/P1/P2/P4；off/retry 与漂移仍拒绝，active/closing 不推进（`:861-964`）。`resolve` 已过滤 withdrawn/released/provider failure（`:530-536`）；`provider_closure_ok` 检查 pin/provider 代次（`:743-745`），但不是完整传递 live；activation totality 已有（`:843-856`）。dispose 只在九类义务全无时墓碑，关联 host_io 保守阻塞（`:1040-1097`）。DP3 的 withdraw/release/failure/closing 写路径不存在。
| DDL/guard | `effects_one_reconcile` 是每 fiber 至多一条 ready/claimed reconcile 的唯一索引（`17_effects.sql:27`）；I7 不得放松。`prev_contribution_id` 与 `pins.contribution_id` 是非延迟 FK（`20_relations.sql:14,18`），历史引用要求优先 tombstone。`30_triggers.sql:31-60,162-164,181-234` 已有 immutable/tombstone、current episode、epoch 与 owner+activation+run pin 合并 DAG 守卫。保留 closure/depth 512、graph distinct elements 262144。
| contribution 与运行 | schema 允许五种 inverse，但 `validate_delta` 当前只放行 service/delete_row 与 child/dispose_child（`14_contributions.sql:11-13`; `40_advance.sql:509-527`）。run 无生产创建/settlement 回路；`interpret_settlement` 保持 `0A000`（`:354-356`）。direct install 没有 CAS/refcount 资源所有权证明。

关系不变量：fiber 是终身身份，owner 与 owner episode 不随 current episode 改绑；episode 的 committed view 冻结；contribution 的 descriptor/inverse/seq 和 pin 的 provider/epoch 是历史身份；pin 是 demand；ready continuation 的 input、actor、parent/ordinal 不能重写。事件保留单次状态变化一个精确聚合事件，no-op/replay/deferred 零事件；多实体 stream 属 DP5。

**设计理由（推断）：**缺口集中在 teardown 状态变换和 command deferred 接线；保留现有协议和账本比重写状态模型更能维护 DP1/DP2 已验证合同。历史 FK、I7、same LOGIN 与 G 共同约束方案，不能以 fixture 绕开。

### 2.3 固定合同、预算与证明边界

整个计划保持 I1–I8：单 key 至多一个 live service；每个 live consumer require key 恰一个 pin；I3 pin 指向的 contribution 在释放前不物理删除；每 fiber 至多一个 open episode；episode seq 单调；一次 advance successor ≤16；I7 单 fiber 至多一个未结算 reconcile；无裸领域 DML。还保持 same LOGIN continuation、replay-first、稳定 24 错误码、`revision=0`、P2 ≤32、body ≤1MiB、递归键 ≤200、closure ≤512、successor ≤16、10 表、仅一个 SECURITY DEFINER。不得新增公开 writer、第二调度器或 run_start。

DP2 历史测量为 `40_advance.sql` 1130 行、`41_lifecycle.sql` 1097 行、DDL 前缀414/900、manifest16、表10，B0 必须重测。**用户决定（2026-10-27）：advance 与全部 private helper 的总预算统一为≤5000物理行（含空行、注释），替代原1200上限及其预算内重裁阻塞；设计稿 `:735,743`、DP1 `:46,237` 与DP2计划已同步修订。** 计数覆盖40/41/42及未来任何承载私有helper的模块，不是每文件5000。历史合计2227在新预算内，距上限2773行；无需先压缩再开展DP3，实际容量以B0重测为准。B0 时 DP1 `test_kernel.py` 与 DP2 `test_boundaries.py` 仍为旧单文件1200断言。W1 已把它们迁到 40–49 合计≤5000。共享 `assert_helper_budget` 在临时 `40_advance.sql`/`41_lifecycle.sql`/`42_teardown.sql` 树上接受合计恰好 5000 物理行，并在 5001 行时拒绝；字面整数比较不是该证明。B0 的旧 gate 绿色不是该项证据。实测见 §8 W1 result。只有实际合计超过5000时才先简化或回到规格裁决；不得擅自抬限、删必要行为、挪文件或压成长行规避。manifest17、DP1 exact tuple 与 DP2 boundary 计数/预算 gate 同步修改。冻结 `57e2c1e` 的 `v24/load.py`、`v24/sql`、`v24/s1`–`s12` 十二份 SQL hash/diff 必须保持一致；Cordis 只用 `v24/cordis/load.py`，不能注册进 frozen loader 或修改 v8 loader。

## 3. Design

### 3.1 执行索引

| Work item | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| B0 | 固定 v99 起点与 DP2 文档状态 | 基线、21 条旧命令、frozen diff/hash、容量有本轮记录；订正三处过期当前状态，不改历史测试事实 | DP3 plan/README/matrix/ledger；DP2 README/matrix/ledger | 无 | M |
| W1 | 同步5000总预算gate与SQL布局并落实 deferred、continuation/coalescing 协议 | DP1/DP2旧预算断言迁移，全部advance/helper模块合计≤5000且5000/5001边界通过；由 CDP3-P非生产probe证明身份负例、command deferred十表零写、释放G、I7与旧claim/replay | `40_advance.sql`、`41_lifecycle.sql`、`42_teardown.sql`、loader/gates、DP3 support/protocol | B0；Oracle布局裁决；用户5000总预算修订 | L |
| W2 | live、P3 drift、Divert/Raise/Leave | CDP3-L；传递准入失效、failure v1、窄原子 Raise、P5 withdraw 不释放 pin | 40/41/布局裁决文件、30 guards、DP2 activation/boundary、DP3 live | W1 | L |
| W3 | P6 drain、inverse、pin release、episode close | CDP3-T 与 CDP3-B 的 teardown 边界通过；32 上限、倒序、历史 FK、run fixture、旧 pin 语义通过 | 40/41/42、30 triggers、DP3 teardown/fixtures | W2 | L |
| W4 | 已激活实例有界 dispose | CDP3-D；有限目标/后继、父不早墓碑、无持锁等待、自身协调不死锁 | 40/41、DP2 boundaries、DP3 dispose | W3 | L |
| W5 | 全阶段 closeout | 所有现存旧 gate + 5 个 DP3 gate 串行退出 0；冻结/预算/工件完整 | DP3 tests/README/matrix/ledger/plan | W4 | M |

每个 work item 必须先确认本阶段文件集，writer、validator、guard、对应测试按同一里程碑原子落地。B0 与 W1–W5 独立，不把多个里程碑积压到一个提交。

### 3.2 SQL 布局、helper、delta 与事件接口

**Oracle-adjudicated 2026-10-27：新增 canonical `42_teardown.sql` 的布局保持；用户于同日将 advance 与全部私有helper的跨模块硬预算修订为≤5000物理行。预算数值以用户决定为准，不归因于Oracle。** 42 放在 41 之后、50 之前；40 保留协议编排、deferred 接线以及 typed delta 验证/应用入口；41 保留 install、resolver、P0–P4 和既有 dispose 事实查询；42 只承载 live/barrier、P3/P5/P6、inverse 后置条件与单对象 dispose helper。W1 同步旧预算gate并核验40/41/42及未来helper模块全部物理行合计≤5000；当前2227行不再触发前置压缩或重裁。仅实际总量超限时简化实现，仍无法满足则stop/re-scope；不以文件迁移、重复helper或压成长行规避。

同一布局里程碑同步把 Cordis `load.py` manifest、DP1 environment 精确 tuple、DP2 boundary 文件数更新为17；所有 helper 为 private SECURITY INVOKER、固定 `search_path`，不新增公开 EXECUTE、表、列、enum 或 extension；仅 `advance` 继续 SECURITY DEFINER。

私有接口必须有稳定、可断言的返回合同：

| 接口 | 精确职责与边界 |
|---|---|
| `lifecycle_step(effect_id, outcome, closure) → jsonb` | 只读选择一个 `control/idle/begin/iterate/finish/divert/raise/leave/inverse_batch/pin_release_batch/close/dispose_request/dispose_progress/dispose_wait/dispose_finish` tag；不把 tag 写成第二状态机。 |
| `command_barrier(effect_id, outcome, closure) → jsonb NULL/response` | 只判断可等待 DB 义务；ready 返回 NULL，等待返回 v1 deferred，unknown 返回 `blocked_unknown`，未支持义务返回 `0A000`；不撤销 claim、不给外部 IO 下结论。 |
| `fiber_live_state(fiber_id, episode_id) → jsonb` | 返回 `{live, reason, visited_count, closure_overflow}` 的有限对象；容量/图错误独立于 `live=false`。 |
| `pin_readable(pin_id) → boolean` | 只沿 pin→冻结 contribution→原 provider episode 读取；不调用 `resolve`，不受 provider 当前 off/closing/withdrawn 影响。 |
| `teardown_op_valid(op) → boolean` | exact keys、闭集 tag、UUID/seq/数量上限、同一 fiber/episode 和 DB 推导 ID 集；拒绝 caller timestamp、任意 inverse 或跨 fiber 目标。 |
| `validate_teardown_domain(...) → jsonb` | 在 DML 前重算 ownership、ω/target、精确 contribution/pin 集、事件和 successor；验证所有写目标已在 closure。 |
| `apply_teardown_op(op) → void` | 仅执行已验证闭集写集；固定 DML 顺序和后置条件失败均抛 SQL 异常，不能转成成功。 |
| `run_pin_release_delta(run_id) → jsonb` | 仅消费可信 terminal run（owner/episode 对齐、`ended_at` 非空、无未结 effect/host_io）；只返回≤32的 pin release，不写 run 结果或 settlement。 |

共同 delta 始终为 `{domain, receipt, events, successors}` 四个键。领域 op 使用精确字段：`fiber_retire{fiber_id,episode_id}`、`episode_close_start{fiber_id,episode_id,outcome,failure}`、`contributions_withdraw{fiber_id,episode_id,contribution_ids[]}`（≤256）、`contribution_inverse{fiber_id,episode_id,contribution_ids[]}`（≤32、seq DESC）、`pins_release{fiber_id,episode_id,pin_ids[]}`（≤32）、`episode_close{fiber_id,episode_id}`、`install_dispose_request{install_id}`、`fiber_dispose_request{install_id,fiber_id,want_on,control_seq}`、`fiber_dispose_finish{install_id,fiber_id}`、`install_dispose_finish{install_id}`。inverse 由账本推导，调用方不能改写 descriptor、timestamp、程序或 release 顺序。

所有新 op 的 JSON 对象都包含 `op` discriminator 加上述精确字段，不接受额外键；ID 为非空 UUID，ID 数组去重且顺序由 DB 重算；seq 是非负 bigint，outcome 仅 `divert/error/retire`。`episode_close_start.failure` 仅 error 分支为下文 v1 对象，其余为 JSON null；`fiber_dispose_request.want_on` 恒 false，control_seq 仅在需改变控制时递增一次。receipt 仍为现有 `{status:"succeeded"}`；不新增宿主提供的时间或状态字段。

| 分支 | 允许的领域写集与固定 DML 顺序 | 事件归属 |
|---|---|---|
| Divert / Raise | `fiber_retire`（仅首次）→`episode_close_start`；Raise 原子写 failure，不碰 contribution/pin/iterator | fiber 的 `episode_closing` |
| P5 Leave | `fiber_retire`→`episode_close_start(outcome=retire)`→`contributions_withdraw`，同次提交，不拆成多次 Leave | fiber 的 `episode_closing` |
| P6 inverse | 一个 `contribution_inverse`，严格倒序执行≤32项，逐项后置验证，不能夹入 pin release/close | fiber 的 `contributions_released` |
| P6 pin release | 一个 `pins_release`，按下文 run→activation 顺序合计≤32，不能夹入 inverse/close | fiber 的 `pins_released` |
| P6 close | 一个 `episode_close`；先保持episode.state=closing并设置outcome/closed_at，再清 current pointer 与 retire facts，事务末 deferred guard 校验；本次不 begin | fiber 的 `episode_closed` |
| dispose | 一次只允许 seal、一个 fiber 控制请求、一个 fiber finish 或一个 install finish；可附至多一个所选 fiber reconcile 后继，不跨 child 直接写其 episode/账本 | 目标 install 的 `install_dispose_progress` |

validator 在 DML 前重算每分支完整集合、前置事实及上述 whitelist，拒绝混合不相容 op、超数和越权目标；应用后用 fresh SQL 验证，失败抛异常回滚整个 advance。其后按既有顺序结算当前 effect/receipt/request、写单 event、插 successor；当前 reconcile 必须先 settlement 再插同 fiber 后继以满足 I7。

聚合事件的闭集 payload 也必须可断言：`episode_closing{episode_id,epoch,control_seq,outcome,reason,failure,withdrawn_ids}`、`contributions_released{episode_id,contribution_ids,seq_from,seq_through}`、`pins_released{episode_id,activation_pin_ids,run_pin_ids}`、`episode_closed{episode_id,epoch,outcome,control_seq}`、`install_dispose_progress{phase,fiber_id,child_install_id,scheduled_targets}`；可选字段用 JSON null，phase 仅 `requested/fiber_requested/fiber_disposed/work_scheduled/completed`。event wrapper 沿用精确四键 `{entity_type,entity_id,event_kind,payload}`，前三种清理事件及 closing/closed 的 entity_type 为 fiber、entity_id 为被清理 fiber；dispose 的 entity_type 为 install、entity_id 为当前 dispose request 目标 install，scheduled_targets 是本次选定 fiber UUID 数组、长度≤1。epoch 是非负整数，control_seq 是非负 bigint；ID 数组由当前批次事实精确推导，seq_from/seq_through 对应本批最大/最小 seq；outcome 同 closing episode，reason 仅 `control_drift/target_drift/dependency_lost/dispose/failure`，failure 仅 Raise 时为 v1对象，其余 JSON null。无所选 fiber/child 时对应字段 JSON null；withdrawn_ids 仅 P5含本次精确 ID，其他 closing为空数组。新后继专属调度使用 `phase=work_scheduled`；seal/fiber控制/fiber墓碑/install墓碑分别使用 requested/fiber_requested/fiber_disposed/completed。

有领域变化或本次新建后继恰一条事件；两者同时发生仍只有该领域分支的一条事件。只有无领域写的 dispose successor-only 分支使用 work_scheduled。真实 no-op、仅复用槽、replay、deferred 和错误零事件。**这明确修改 `40_advance.sql:643-645` 当前 domain非空 iff一事件的 validator 合同**，W4 同步修改结构/语义校验与 replay/cursor 断言，并在 ledger 记录局部事件假设；不能只改 interpreter。

### 3.3 command deferred、事务和 replay

command 屏障检查放在身份验证、replay-first、closure/有序锁和锁后复验之后，任何领域/receipt/request/event/successor 写入之前。`interpret_command` 不直接返回四键 delta；先返回私有控制结果 `{kind:"ready"|"deferred"|"blocked_unknown"|"unsupported", step, barrier, context}`，仅 `kind="ready"` 才转换为 `{domain,receipt,events,successors}` 交给现有 validator/applier。`advance` 在 `validate_and_apply_delta` 之前拦截其余三种结果，按既有稳定错误或 v1 deferred 响应结束。W1 只能用 disposable non-production probe 验证这个分流、十表零写和事务释放 G；真实 P6 分类、commit、replay 与 cleanup 证据归 W3，不得把 probe 标成生产 P6。

只有确实进入 P6 或 dispose drain refresh 且屏障属于可等待 DB 事实时才返回既有 v1 外形：`{v:1, disposition:"deferred", effect_id, emitted:[], revision:0, claim:null}`。

deferred 精确保证：不写领域表、effects 状态/outcome/settled_at、requests、events 或 successor；不推进 iterator、withdraw/release 或 episode state；ready continuation 保持原身份和 input；fresh command 不消费 request key。replay-first 仍在屏障前：已提交请求继续重放首次 response。未知 inverse 是 `blocked_unknown` 零写；不支持的外部/settlement 义务保持 `0A000`；身份伪造仍是稳定错误。claim 分支 `barrier_ready` ABI 和活 lease 的 `stale_claim/claim_busy` 原语义不改。

PostgreSQL xact advisory lock G 不能由函数主动释放。deferred 调用方必须马上 COMMIT 或 ROLLBACK 并确认事务结束，再等待/重试；严禁持 G 轮询。用第二连接在第一连接结束事务后成功取 G 作为 gate 证据。

### 3.4 continuation 身份、控制漂移与 I7 coalescing

严格身份拒绝仍包括 reserved key/effect ID/kind/parent/ordinal 错误、actor 非原 LOGIN、input 不匹配、ready 行带 claim/receipt、parent 未成功结算或关系不在闭集，以及 episode fence 被关闭/替换。身份与绑定错误零写，按既有稳定码或 `retry_with_closure` 分流。

有效身份下的 `control_seq` 变化、want_on 翻转、target 变化以及 episode 合法推进至 active/closing 属正常控制事实，由生命周期选择器处理，不再作为身份伪造。旧 continuation 的策略必须保证：旧 input 不能复活 closing episode、不能追加旧代 contribution；可提交清理/no-op，新代只能由§3.6规定的当前代合法请求/continuation在旧episode彻底close后建立；旧代input不能开始新代。generation drift 与 episode binding corruption 不能混为一类。

I7 不变且不替换 ready 行：同 fiber 存在 ready/claimed reconcile 时，P0 控制请求可提交自己的控制事实和 request receipt，但不更改旧 effect identity/input/actor，也不新建第二槽；槽空且确实需要推进才创建唯一 successor。当前 continuation 要先结算才能插同 fiber successor。claimed 行不能被接管或改绑。新鲜 no-op command 仍保存其首次 receipt；“合并零写”仅指对既有槽位不写，绝不能把成功控制请求说成十表零写。测试覆盖 on/off/retry 交错、same LOGIN、旧 NULL/non-NULL fence、replay 与槽位唯一。

W4 必须显式扩展当前 `continuation_state` 的 parent whitelist（`40_advance.sql:300-305`），不能声称已兼容 dispose：只允许成功同 LOGIN 的①reconcile parent→同 fiber reconcile；②dispose parent→该 parent 已永久 seal 的目标 install owner子树中、本次 validator 确定选中的一个fiber reconcile。第二分支不要求 parent.fiber_id=child.fiber_id，但必须以parent.input.install_id、owner lineage、精确selected target证明权限，不能放行任意跨fiber关系。输入精确为 `{fiber_id,action:"advance",expected_control_seq}`，request key继续用 `successor_request_key(parent_id,0)`，ID继续用 `successor_effect_id(actor,parent_id,0)`；effects.fiber_id绑定选定fiber、episode_id绑定插入当时的current episode。子请求payload/input/actor/parent/ordinal不可修改。`validate_delta`、domain validator、`continuation_state`和applier四处同时适配，parent非成功/不同LOGIN/未seal子树/越界target负例均零写拒绝。

### 3.5 live 传递闭包与旧 pin 可读

使用单一、去重、有界的依赖闭包判定；`resolve`、activation admission 和 reconcile 阶段复用它，不各自维护递归状态机。求值先核对 fiber/install/scope/owner lineage、dispose/retire/want_on/current failure，再验证当前 open active episode；随后核对 committed_view 的 require key 集与未释放 activation pin key 集精确一致、contribution/provider epoch/descriptor/check 匹配，递归访问 provider 固定 `(fiber_id,episode_id)`。共享 provider 用 visited set 去重；run pin 不构成 fiber-live 递归边。空 requires 的 active fiber 在自身条件满足时 live。owner lineage 与 activation DAG 一并检查，图环/容量错误不能伪装成普通“不 live”；closure/depth 上限保持 512，超限返回 `retry_with_closure`。

`resolve` 保持九列 `(pkey,contribution_id,provider_fiber_id,provider_episode_id,provider_epoch,descriptor,descriptor_digest,contract_version,available)`（`41_lifecycle.sql:488-490`）的既有名称、顺序、类型和输出，不返回 withdrawn/released 或非 live provider；不要增加“绕过 withdraw”的 resolver flag。旧 pin 读取走 pin ID → 冻结 contribution ID → 原 provider episode/epoch/descriptor 的只读路径，不调用 resolve、不因 provider off/closing/withdrawn 而改绑或拒读；必须要求 pin 未 released、contribution 未 released、冻结身份一致。I3 保证 released contribution 不与活 pin 并存。release 后 pin 不再可读。

闭包采用队列/visited set，节点为固定 `(fiber_id,episode_id)`，每个节点和依赖边只处理一次，复杂度 O(V+E)，不是枚举全部路径；每个被访 provider 都重复完整 lineage/current active/want_on/retire/dispose/current-failure/totality/check 检查，并要求每条 activation pin 未 released、指向 contribution 未 withdrawn/未 released、冻结 epoch/descriptor/contract 相符。旧 fixture 也必须具备精确 require-key/pin-key 对应，不能为测试豁免 totality。diagnostic 的 reason 取有限内部枚举；closure_overflow/cycle 独立传播为 `retry_with_closure`，不得转成 `available=false`/`dependency_unresolved`。pin-readable 仅 private helper 或 owner只读测试入口，分别验证旧 activation/run pin，不能增加 public EXECUTE 或 DP4执行 API。

provider 失效后 live 是派生的，可立即阻新工作；consumer 的 Leave/Unload 由其后续 same-LOGIN reconcile 驱动。DP3 不承诺自动扇出、扫描公平性或故障后唤醒；gate 显式提交 consumer reconcile 证明失效传递。

### 3.6 P0–P5、Divert/Raise 与失败原子性

阶段选择每次只做一个状态步骤：重查最新 control/retire/dispose；reloading 时比较实时 target 与冻结 ω 的完整 binding（key、provider fiber/episode/epoch、descriptor digest、contract/check）；active 时按 live 判定 Leave 或 no-op；closing 只进 P6。直接 `on/off/retry` 请求先按下文P0真值表只记录控制事实，不在该调用顺带执行P5/P6。对 `action=advance` 的生命周期推进，优先级为：身份/绑定伪造拒绝 → disposed拒绝、dispose-pending仅允许清理 → closing的P6 drain → reloading的control/target/check漂移（Divert/Raise）→ active的live失效（Leave）→ P1/P2/P3/P4正常推进；dispose seal不能挡住已有episode清理。控制与 target 漂移只要满足身份合同就进入上述选择器，不能被早期 `effect_id_conflict` 截断。

**Oracle-adjudicated 2026-10-27：P0 只记录控制/retire 事实，P5 才 withdraw。Confidence：高。** 设计规则表与 P0–P6 分期把可见性撤销置于 Leave/P5；走查 `:367` 的“P0 withdraw”视为与 `:320-345` 不一致的缩写，不覆盖规则级合同。P0 不写 `withdrawn_at`、`released_at`、pin 或 episode closing；P5/L-Leave 将 episode 置 closing/outcome=retire 并撤销新解析可见性，仍不释放 pin、不 inverse。仅在规格作者正式修订并同步规则表、阶段表和崩溃语义时才重开。

P0 选择器的可执行真值表：

| 请求 | 当前事实 | 必须写入 | 禁止写入 |
|---|---|---|---|
| `on` | `want_on=false` | `want_on=true`、`control_seq+1`；有 ready/claimed reconcile 时只提交自身 receipt 并复用旧槽 | 改写旧槽 input/actor/parent/ordinal，或创建第二 reconcile |
| `on` | `want_on=true` | 控制 no-op；首次 request receipt 仍持久化 | 清除 failure、改 episode、创建 successor |
| `off` | `want_on=true` | `want_on=false`、`control_seq+1`；可登记 retire fact | 调用 active admission、withdraw/release、inverse |
| `off` | `want_on=false` | 控制 no-op；若存在待清理旧代且槽为空才登记一个清理后继 | 改写已有槽或创建新 episode |
| `retry` | `want_on=true` 且（failure.control_seq=当前seq 或当前 episode.state=closing）；否则 `stale_generation` 零写 | `control_seq+1`，先退役旧代；旧 continuation 不能追加旧代 contribution | 同代自动重试、删除 failure 复活 |
| 直接on/off/retry | `dispose_pending/disposed` | 返回既有 `already_terminal`/`owner_closing` 稳定错误 | 重新 want_on、开 episode、接纳 pin/contribution |

`expected_control_seq` 必须在每个直接控制请求上 CAS 校验；`control_seq=9223372036854775807` 且需要递增时返回 `budget_exceeded(reason=control_seq)` 零写。关闭 scope/owner 不得阻止 off 退役；on/retry 则必须通过 lineage admission。

- **Divert：**closing/outcome=divert，记录必要 retire 控制事实；不改 ω/iterator、不撤销、不 release、不 inverse。
- **Raise：**closing/outcome=error，写下文精确 v1 `fibers.failure`；不把 SQL 原文或外部值存入 failure，不 inverse 已提交 prefix。同 control_seq 不自动 retry；显式 retry 增 control_seq。
- **Leave：**episode 转 closing/outcome=retire，撤销当前 episode contribution 对新解析的可见性；不删除 contribution、不释放 pin、不置 released_at。

P5 withdraw 集必须是该 episode 中 `kind IN ('service','cell','listener') AND withdrawn_at IS NULL AND released_at IS NULL` 的**精确全集**，≤256，且整个写集纳入closure≤512；超限在任何写入前 `retry_with_closure`，不静默分批 Leave。child/reservation/unknown 不执行可见性 withdrawal，但其账本和债务仍保留供 P6 分类，不能用排除 withdrawal 暗示已释放。此集合只定义新解析可见性撤销，不扩大 inverse 能力；P5 不设置 `released_at`，且所有非集合 kind 的 withdrawn/released 值必须原样不变。

- **P1 无 episode 缺依赖：**Oracle-adjudicated 2026-10-27，返回既有 `dependency_unresolved` 稳定错误，detail 仅含有限缺依赖事实；十表零写，不建 episode/failure/pin、不消费 request/effect、不创建 successor，保留原 input 供后续重试。不得将缺依赖伪装成空成功/pending receipt。其他准入事实使用已有稳定错误。

失败批次采取“全批预检，已知业务失败只产生 Raise delta”。address/contract/check/declaration/totality 在 P2/P3/P4 的批次 DML 前分类；validator 重算分类与 failure，applier 同一事务提交 closing+failure+event+effect/request。P2 service 唯一冲突防御分支是必需合同，不是 optional：在至少一条本批 contribution DML 已发生后注入 SQLSTATE `23505` 且 constraint 精确为 `contributions_service_addr`，窄子事务必须回滚本批所有 contribution 与 iterator 写，再重新验证并应用 Raise；receipt/request/event/successor 不在被捕获子事务内。其他 unique/FK/CHECK/权限/取消/超时/连接/内部错误一律重新抛出，使整次 advance 回滚；禁止 `WHEN OTHERS` 转换为成功、Raise 或 deferred。此前已提交的 P2 prefix 保留在 accumulator，后续 P6 清理。

**Oracle-adjudicated 2026-10-27（F4 窄复核）：**failure 按实际检测阶段记录，包含 P3，reason 固定 `totality_failed`。尚无 Raise 时 `fibers.failure` 可为 SQL NULL；非空必须恰含 `{v,control_seq,episode_id,phase,code,reason,key}` 七键。`v` 为 JSON 整数1，`control_seq` 为0..9223372036854775807的整数并等于失败 episode 的冻结代次；`episode_id` 是该 fiber 的失败 episode UUID 字符串，其余字段为下表字符串，不允许 JSON null 或额外键。key 必须等于对应 manifest key，长度1..128（沿用现有 `json_text`/manifest 合同，纠正 Oracle 主 lane 的1..256建议）。

| phase | code | reason | key 与条件 |
|---|---|---|---|
| p2 | provide_conflict | address_conflict | 冲突的 provide key |
| p2 | registration_stale | contract_drift | 注册声明/contract 校验失败的 provide key |
| p3 | registration_stale | contract_drift | 冻结绑定不变但声明/contract 校验失败的 require key |
| p3 | provider_unavailable | check_failed | 冻结绑定不变但 check 失败的 require key |
| p4 | registration_stale | totality_failed | manifest 顺序中首个缺失或不匹配的 provide key |

P3 先比较实时 target 与冻结 binding；绑定变化走 Divert、不写 failure。P4 `totality_failed` 的 key 为 manifest 顺序首个缺失或不匹配 provide key；空 provides 若 totality 失败，或损坏事实无法归到单一 key，按内部一致性异常传播并回滚，不生成无 key Raise。此处采用主 Oracle 的可定位 key 合同，替代另一 lane 的 P4 null 候选；gate 覆盖空 provides成功、缺失、失配以及无合法归因的损坏事实。不得写 SQL message、descriptor 原文、动态程序或外部值。failure 是单字段快照：下一次合法 Raise 整体覆盖；close/retry/begin/activate 不清空，旧代 JSON 不再是 current failure；各代历史由 episode outcome 和 Raise event 保留，不宣称字段本身是追加历史表。Confidence：高；仅权威规格或已接受消费者合同可推翻。

close→begin 由下表决定；close 与 begin 分成两次 advance，不因 close 自行扫描或重写旧 continuation input。开始新代时重新执行 P1 admission/target/check，绝不沿用旧 ω。

| closing outcome / cause | close 后动作与责任 |
|---|---|
| divert：最新 target 变化，或 off→on / 合法 retry 已递增控制代 | want_on=true、无 current failure、未 dispose 且 lineage/admission通过时，由最新合法 same-LOGIN fresh reconcile 请求或冻结身份且输入确属当前代的 continuation 在后续调用 begin；旧代 input 只能 cleanup/no-op，不能冒充新代 |
| retire：当前仍 off 或 dispose | 不 begin；清理后仅继续 dispose/finalizer |
| retire：dependency-only Leave | 不在同 control_seq 自动重启。依赖恢复后，调用方新 same-LOGIN reconcile 请求重做 P1；没有自动 wakeup/scanner，缺依赖仍保留原 input、零写 |
| error：Raise | current failure 阻止 begin；必须显式合法 retry递增控制代，再按第一行进入新代；provider恢复不能自动清 failure |
| 任何 cause，owner/scope关闭或永久dispose seal | 拒绝新 admission，允许清理收敛；不创建新代 |

### 3.7 P6 drain、inverse 与 pin release

屏障必须分辨可等待义务与不可执行债务：当前 reconcile 不阻塞自身；仍 open 的 owned run、指向本 episode contribution 的活 activation/run pin、未清 child、其他业务 ready/claimed effect 是屏障；unknown inverse 返回 `blocked_unknown`；当前 DP3 无生产处理器的 host_io/settlement 保持拒绝或 `0A000`，不能把终态标签推断为外部资源已释放。只有可由 DP3 后续合法步骤清除的等待事实才 deferred。

清理顺序遵守设计固定 DAG：先 child/consumer，再本 fiber contribution，最后本 fiber 对 provider 的 inject/activation pin。contribution inverse 按 seq DESC，单批 ≤32；pin release 单批 ≤32；每步重新读取/验证剩余工作，不增加持久 cleanup cursor。工作由 `released_at IS NULL` 派生。child 或 consumer 未退出前不能释放提供给它们的 contribution；贡献仍未全部 release 前不能提前释放相应 activation pin；贡献的活 pin 非零不能 release。所有历史行保留 tombstone。close 时同事务更新 episode/current pointer/retire facts，遵守 `30_triggers.sql` current episode deferred guard。close 后是否开始新代只按最新 want_on、failure、dispose、owner/admission 与实时 target 判断。

**Oracle-adjudicated 2026-10-27：inverse 生产范围限 service 与 child，Confidence：高。** `service/delete_row`、`child/dispose_child` 经真实生产 `advance` 执行并证明；`listener/delete_row` 只能由 owner fixture 构造事实，再走真实 teardown advance 证明账本清理，不能声称生产 listener 注册/dispatch。当前缺少可判定 current-value/额度投影的 `cell/restore_prev` 与 `reservation/release_reservation` 返回 `0A000` 并整笔回滚；不得由 fixture 创造语义。`unknown` 返回 `blocked_unknown`、零写并保留债务。schema 上有 inverse tag 不等于拥有生产恢复能力；只有未来规格和生产路径提供权威恢复事实才扩大。该 fixture/拒绝范围是 DP3 阶段假设，不是永久产品限制。

所有逆操作逐 kind 校验后置条件；同批遇到不支持项或 unknown 不得跳过它继续释放更低 seq。受历史 pin、`prev_contribution_id` FK 与历史保留合同约束，`delete_row` 在 DP3 中解释为逻辑撤销：保留物理 contribution 行并置 `released_at`，从 live resolve/唯一地址集合中移除；这一语义差异要记录到 deviation ledger。旧 pin/read、prev 引用 FK 和唯一地址只有 release 后才可复用都用 SQL 断言证明。

每次 P6 按确定顺序只选择一个分支：①分类全部相关barrier/unknown/unsupported；可信terminal run的自有pin是可释放工作，不当作外部等待；②先释放这些run pins，按 `(consumer_run_id,key,id)` 取前32，使本episode已结束run不自阻provider contribution；open run或外部活consumer仍是barrier；③child/外部consumer退出条件满足后，剩余贡献选最高unreleased seq起前32项（包含不支持项，不可过滤）逐项inverse；④贡献全部released后释放activation pins，按 `(key,id)` 取前32；⑤确认无活义务后单独close。若在贡献已经全released时同时有terminal run和activation pins，可以在同一pins_release中按run在前、activation在后合计取前32，不能每类各32。每步preflight和锁后重验重推集合，不增加cursor或宿主页码。

W3的CDP3-T仅以owner fixture构造已tombstone child，证明parent inverse前置条件；W4的CDP3-D才证明生产child清理、永久seal和完整父树收敛。child或外部consumer未退出时不越权清理。此排序保留export的terminal run-pin→contribution→activation-pin顺序，避免把可释放的terminal pin错误归为永久屏障。

service/listener 的 inverse 后置条件为：资源不再出现在 live resolve/地址占用集合，贡献 withdrawn/released，原物理行、descriptor/inverse/seq及历史FK保留，且活 pin数为0；只有 release 才释放唯一地址，withdraw单独不释放地址。listener owner fixture 只能证明此账本路径，不证明 dispatch。child 的后置条件是 child tombstone，或 child 无任何活义务且永久祖先 dispose seal 生效；`dispose_pending` 不能回到 installed，整个 owner lineage 的 activation/resolve/retry/register 都检查祖先状态。若不能证明无复活路径，就必须等 child tombstone；parent ledger release 后仍要用真实 advance 尝试 child/后代复活并证明零写拒绝。cell/reservation 不伪造后置条件；unknown/unsupported 出现在最高批次时整批零写/回滚，不能跳项。

run release helper 只消费可信的 terminal DB 事实：run owner/episode 与 cleanup 对齐、`ended_at` 已设置、无未结 effect/unknown/host_io，且 pin 确属该 run、未 release。DP3 不写 run 结果、不结束 run、不实现 settlement；run fixture 仅证明屏障与 release helper，通过真实 teardown `advance` 释放 pin，不声称完整 run 回路。未来 DP4 必须在 terminal settlement 同事务复用相同 release 规则。

### 3.8 有界 dispose、closure 与锁顺序

dispose 保留外部 `command_dispose({install_id})` 信封；不新增 dispose continuation kind、reserved namespace 或第二 controller 身份。**Oracle-adjudicated 2026-10-27：每次 advance 最多推进一个 fiber，或一个 child-install 的一个清理步骤；最多新增一个 successor（ordinal 0）。Confidence：中高；这是 DP3 保守范围假设，不是 I7/B=16 的逻辑必然限制。** 首次请求仅登记目标 install 的 dispose-pending 并封住后代新准入；此后按 child/consumer 优先挑一个可推进对象，同层按对象类型与 UUID 稳定排序，不遍历或推进无界子树。已有 reconcile 槽则合并、不改 frozen input/actor；槽空才建唯一 successor。父 install 最终墓碑是独立最后一步；只有所有实例及最终义务通过现有 `dispose_block_reason` 才能 disposed。唯一 successor 始终是所选 fiber（含 child-install 内所选 fiber）的 `command_reconcile`，沿用现有 reserved key、effect ID 派生、冻结 input、parent 关系及 ordinal0。父 install controller 不占 successor：同一 LOGIN 以新的 `command_dispose` request key 显式重入，观察 child 工作并执行最终墓碑；原 request 只 replay 首次 response。重复 fresh dispose 由 G 串行化，重读同一 dispose seal/未结算槽并合并，不创建竞争 controller；`emitted` 只列本次新插入的 ID。child episode/contribution/pin 只由 child 的 reconcile 清理，parent 不直接关闭外部 consumer。

每次只处理单对象的必要步骤，最多一个 successor；B=16 是全局硬上限而非 dispose 工作额度。该范围选择的理由是减少协调写集和 closure，复用 ordinal 0/单槽/单聚合事件，使 child-first、父不早墓碑与无持锁等待更易证明；不声称 16-fiber 批量不可能正确。只有出现具体合法调用序列证明单对象在显式 same-LOGIN 后续调用下无法完成清理，并且批量方案仍证明 I7、单事件、closure≤512、child-first、父最后及事务释放 G，才推翻此假设。

不得持 G 等待子任务、外部 IO、run 或 consumer；先提交一个有限工作步骤，结束事务，再由同 LOGIN 后续调用观察完成事实。若没有可提交步骤且仅有可等待 barrier，才 deferred。DP3 不新增 ready→cancelled facility：ready/claimed business effect、unknown、host_io 都保持 barrier 或既有稳定拒绝，lease expiry 不视为完成、取消或资源释放。控制 coordinator 不应把自身经验证的协调 effect 当作外部业务阻塞，但不能按 kind 无条件排除任意 effect。父不早于 child/consumer 墓碑；provider 不越权关闭外部 consumer。

测试 driver 不代表生产 scanner：对有界 fixture 以 `16 × (1 + F + I + E + C + P)` 为燃料上限，F/I/E/C/P 分别为 seal 建立时未墓碑 fibers、未 disposed installs、open episodes、未释放 contributions、相关活 pins 的计数；每个 productive committed step 必须降低下述一次性里程碑 rank；纯 replay/coalescing 不计进展。无 rank 下降、出现 deferred/blocked_unknown/unsupported 或燃料耗尽即报告阻塞，不能把局部成功拼成完成。P1 provider 出现后以保留的原 continuation input 重交；dispose parent 每次使用新 request key，原 key 只 replay。合并 owner+activation+run DAG 无环仍由 `activation_dag` 预检与 deferred trigger 兜底。

rank 是测试 driver 的字典序 `(M,U)`：seal 后为固定 fixture 建立一次性里程碑集合——每 install 的 seal/最终墓碑，每 fiber 的 retire/进入closing/close/最终墓碑，每 contribution inverse，每活 pin release；M 为尚未完成的数量，批次完成可同时减少多个。U 为当前已可执行而尚无唯一 ready/claimed continuation 代表的下一阶段数；纯 schedule使 M不变、U下降，领域推进必须使 M下降，允许暴露下一阶段使U增加。每个里程碑仅计一次，不将 request receipt、重放或重复schedule计进展；seal 禁止新增生命周期义务。driver 每轮取新快照核对 rank，全部 attempts计入燃料，replay/coalescing另作独立断言而不放入推进循环；外部consumer/unknown/unsupported为停止并报告，不将阻塞fixture声称完成。

closure seed 只纳入当前批次实际会写的 fiber/install/episode/contribution/pins、必要 owner/scope lineage、当前 effect/直接 parent 身份与屏障证明目标；terminal 历史 parent 不递归扩展，released 历史不全量锁入。所有写目标仍须被 closure 覆盖，512 去重上限、既有表序/scope depth/UUID 锁序、G-before-row-lock 和锁后复验不能弱化。闭包/图容量超限在 DML 前 `retry_with_closure`。fixture owner DML 必须先取 G。pre-read 分类 helper 可声明 `STABLE`，但任何 apply 后置条件、released/pin/current 终态检查必须在同一 `VOLATILE` 调用中重新发起 SQL 查询，不能复用 apply 前快照；这也是 fault-after-write 与事务取消测试的判定边界。

锁定/读取矩阵中“G读”表示只读 barrier/admission事实在所有 writer先取G的前提下稳定，不代表可省略写目标行锁；任何缺失写目标或锁后事实改变都在DML前 `retry_with_closure`。

| 分支 | 必须有序锁定的写目标 | G稳定读取的证明集合 | 锁后复验 |
|---|---|---|---|
| P0/control | 本fiber/install、当前effect、必要scope/owner lineage、将创建/结算的当前槽 | current episode、existing ready/claimed槽、ancestor seal | CAS、actor、frozen input、I7、dispose/owner准入 |
| P1/P2/P3/P4 | 当前fiber/episode、当批contribution/pin目标、parent-child install/fiber写目标 | 完整provider live诊断、manifest/ω、scope/owner、唯一地址 | target/epoch/check、精确批次、provider仍live、地址约束 |
| P5 | fiber/episode、精确withdraw全集 | 活pin/owner/consumer关系、控制事实 | 全集≤256且closure≤512、ω/closing cause不变 |
| P6 inverse | fiber/episode、本批最高seq贡献、child inverse会改变的child控制对象 | reverse activation/run pins、相关runs/effects/host_io、child活义务 | blocker集、highest seq集合、逐kind后置前提 |
| P6 pin/close | 目标pins及本fiber/episode/current pointer；close涉及的retire事实 | run terminal证明、全部剩余贡献/pins/child/effect/host_io | terminal owner/ended_at、精确排序和≤32、无遗漏活义务 |
| dispose | 目标install与本次选定单对象、相关fiber控制/墓碑、current effect/新槽 | descendants/consumer退出、run/effect/host_io阻塞、lineage seal | 选择仍确定、槽未竞争、child-first和parent-last条件 |

terminal effect parent只验证直接绑定后停止递归；多代closed/released历史仅按必需FK读取、不全量加入closure。用长 continuation parent链、数百closed/released代次证明当前小写集仍可推进；真实当前工作集512/513分别通过/提前拒绝，注入reverse-pin/run/child集合漂移验证不漏写目标。所有表的既定锁顺序、scope depth与UUID排序保留，不按事件顺序锁表。

### 3.9 errors、事件和事务结果

| 条件 | 响应/异常 | 持久结果 |
|---|---|---|
| malformed/伪造身份/过期 public CAS | 既有稳定错误 | 十表零写 |
| 有效旧 continuation 控制/target drift | Divert/Leave/cleanup/no-op 分支 | 仅合法状态变化 |
| P1 无 episode 且缺 required provider | `dependency_unresolved`（Oracle adjudicated 2026-10-27） | 十表零写；无 episode/failure/pin/request/successor；保留原 input 可重试 |
| P1 其他准入失败 | 对应既有稳定错误 | 十表零写 |
| 已开始 episode 的已分类注册失败 | committed Raise | failure+closing，历史 prefix 留待清理 |
| 可等待 P6/dispose barrier | deferred | 十表零写，不消费 request/effect |
| unknown | `blocked_unknown` | 债务原样保留，零写 |
| 当前未支持 inverse/settlement | `0A000` | 本次调用整体回滚 |
| closure/图容量或锁后变化 | `retry_with_closure` | DML 前零写 |
| 其他 SQL 错误 | 原异常传播 | 整个事务回滚 |
| committed request replay | 首次 response | 零写 |

单次领域变化或dispose新调度恰一条fiber/install aggregate event（successor-only修改见§3.2）；纯no-op、deferred、replay、错误为零事件。失败被“记录为 Raise”时 command receipt succeeded 的含义是成功提交 lifecycle failure 事实，不表示插件激活成功。事件 payload 不参与阶段选择，不新增多实体 stream。

## 4. Gate 与验证规格

新增五个独立脚本，复用 DP1 Server/TestDB/TABLES/snapshot 和 DP2 `test_support.py` 的 `api/command/no_write/sqlstate/replace_function/seed_*` 风格。每个脚本自建 disposable DB；生产可达转换走真实 `advance`。owner DML fixture 必须注释/标记证明范围，不能冒充生产路径。

| Gate | 脚本 | 必须具名验证 |
|---|---|---|
| CDP3-P | `v24/cordis/dp3/test_protocol.py` | W1范围：disposable non-production interpreter/barrier probe证明私有分流、deferred十表snapshot不变、无effect settlement/request/event/successor、结束事务后第二连接可取G；既有same LOGIN/身份/replay/I7/claim负例。W2起累计加入off/on/retry真值表与coalescing、fresh no-op receipt。W3起累计加入真实P6 deferred、屏障满足后同request首次提交和原样replay；不得把W1 probe当成生产P6证据。
| CDP3-L | `test_live.py` | M→A→B 传递失效、owner/scope 关闭、空 requires、缺/多 pin、check、epoch、failure v1 exact keys/types/nullability、dense DAG visited 去重、512/513；新解析失败而旧 pin 可读且 release 后不可读；Divert 不 withdraw、P0 不 withdraw/P5 才 withdraw、Raise 不 inverse；P1 `dependency_unresolved` 十表零写且保留 input；P2 历史 prefix 保留；窄 `23505`/`contributions_service_addr` 注入必须发生在至少一条本批 contribution 写入后，并证明本批 contribution/iterator 写全回滚、此前已提交 prefix保留、同调用仅提交一条Raise；分别在domain DML、iterator、effect settlement、request、event、successor六个边界注入失败并证明原异常/全调用回滚；其他 unique/FK/CHECK/cancel/timeout异常传播；failure P2/P3/P4组合闭集、类型、key和总量归因负例；off/on/target变化不让旧代append。
| CDP3-T | `test_teardown.py` | activation pin 即使无 run 也阻 provider release；open run/ready/claimed/unknown/host_io barrier，lease expiry 不当完成或取消；ended run fixture 只证明 pin release；32+1 严格逆序，run pins按consumer_run_id/key/id、activation pins按key/id；service/listener 真实 inverse 后置条件；child inverse 仅以 owner fixture 构造的 tombstoned child证明账本前置条件，不声称生产 child cleanup；历史 pin/prev FK 保留；released 地址才可复用；空贡献 episode close；多次刷新不重复释放；deferred 零写。
| CDP3-D | `test_dispose.py` | 真实已激活父/子；dispose-pending 即时封住后代 activation/resolve/retry/register；唯一 successor 仅为所选 child/fiber reconcile、ordinal0，parent controller 由新 same-LOGIN dispose request 重入；原 request replay、重复 fresh request 合并且不竞争；每次最多一个 fiber 或 child-install 清理步骤；existing reconcile 槽合并；child tombstone 或永久 seal 后才能释放 parent ledger；父不早墓碑；无 current episode 但有活义务不能完成；不同 LOGIN 不接管；host_io 六态保守阻塞；墓碑不复活；rank driver 有界推进且无持 G 等待环。
| CDP3-B | `test_boundaries.py` | 10表/0新公开 writer/单 DEFINER/40/41/42及未来helper模块全部物理行合计≤5000/DDL≤900/manifest17；service+child生产路径；listener仅owner fixture+真实teardown账本清理、无注册/dispatch结论；cell与reservation分别经真实advance返回SQLSTATE `0A000` 且十表整笔回滚；unknown返回`blocked_unknown`、债务snapshot不变且零写；ready/claimed状态与lease字段不变、不转cancelled；settlement `0A000`；dispatch/intercept/overlay 不被接通；无 run_start/外部恢复；closure与batch上限。

CDP3-B 还必须覆盖：长parent链/多closed代历史不膨胀当前closure，真实512/513与reverse-pin/run/child锁后漂移；双连接同realm同key地址竞争仅一方成功、不同realm同key均成功；P5精确全集256/257边界；apply后inverse/close后置失败整笔回滚；single successor-only event、domain+schedule仍一event、coalescing emitted=[]、replay不重复event。测试读取的是所有十表snapshot及相关sequence/immutable输入，不仅比较API响应。

DP2 gate 迁移逐条按断言意图审查：off/retry 不再作为 unsupported 哨兵；原“同 episode 失败后继续 append”改为 Raise→清理→显式 retry 新 episode；只有已由 DP3 接管的预期 0A000 改成新状态断言；DP4/DP5/DP6 负例、ACL、replay、claim、锁序和身份测试必须保留。不能因新 fixture 或新测试而删除旧真实成功路径。完整 DP1/DP2 测试文件实施前必须读取定位具体断言，不从本计划推定兼容。

### 4.1 每阶段旧 gate 命令

以下命令必须一条一条串行启动、等到退出、记录真实退出码；任何失败即停。不得用分号、后台并发或只读 pipeline 尾部状态。

```bash
uv run python v24/cordis/load.py
uv run python v24/cordis/dp1/setup_db.py --self-check
uv run python v24/cordis/dp1/test_environment.py
uv run python v24/cordis/dp1/test_ddl.py
uv run python v24/cordis/dp1/test_kernel.py
uv run python v24/cordis/dp2/test_kernel.py
uv run python v24/cordis/dp2/test_install.py
uv run python v24/cordis/dp2/test_activation.py
uv run python v24/cordis/dp2/test_boundaries.py
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
uv run python v24/s9/test_g8.py
```

DP3 脚本从建成的里程碑起加入累计序列：

```bash
uv run python v24/cordis/dp3/test_protocol.py
uv run python v24/cordis/dp3/test_live.py
uv run python v24/cordis/dp3/test_teardown.py
uv run python v24/cordis/dp3/test_dispose.py
uv run python v24/cordis/dp3/test_boundaries.py
```

### 4.2 B0 与冻结/工件核验

B0 在 v99 根独立记录 `pwd -P`、`git rev-parse --show-toplevel`、branch、HEAD、status（含 untracked）、upstream、`git fetch origin` 与 `git rev-list --left-right --count origin/v24...v24`、`git branch -vv`、平台、uv/Python/psycopg2/PG 版本、`.venv` 实际路径/属主/非 symlink；验证 worktree 和依赖归属，不把 main checkout 环境当 v99。

每里程碑实际运行并记录：十二份 `v24/sql/*.sql` 按路径逐个 SHA-256 与 DP2 matrix frozen 值；`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12`；`git diff --check`；40、41、42及未来helper模块各自物理行和合计≤5000（含空行、注释）；DDL prefix≤900、manifest精确项、表10、view/extension 0、DEFINER 1、closure 512、batch32、successor16。冻结 hash/diff 只证明冻结目录未变，不代替 DP3 gate。

每里程碑更新 DP3 `README.md`、`docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md`、`...deviation-ledger...` 与计划状态；loader 未改变时也记录 manifest 已核验。B0 订正 DP2 matrix `:7, :188-204`、ledger `:60-64`、DP2 README `:7, :159-167` 的当前状态，保留历史结果。DP1 README 追加 DP3 行为指针，不改 DP1 历史验收。

## 5. File-by-file impact

| 路径 | 预期变更 | 顺序/边界 |
|---|---|---|
| 本计划 | 完整规格、裁决理由、每阶段状态 | 本轮主要交付；critique为工作流审查工件 |
| `v24/cordis/sql/40_advance.sql` | command deferred 控制结果接线、身份/漂移分流、teardown typed op、successor 结构、closure 收敛、窄 P2 防御路径 | 与41/42及未来helper模块一起受总计≤5000物理行硬限 |
| `v24/cordis/sql/41_lifecycle.sql` | off/retry、P0–P4、live/admission委派、P3/Raise/Leave接线、dispose既有义务复用 | 保留 DP2 install/resolver/P0–P4主体并委派teardown helper |
| `v24/cordis/sql/42_teardown.sql` | 新增 canonical teardown 模块；private live/barrier/inverse/dispose helpers | 41后50前，loader与所有精确计数断言同里程碑 |
| `v24/cordis/sql/30_triggers.sql` | release/pin最终状态、episode单向关闭、disposed/run-end单调守卫 | 与 writer及DDL gate同阶段 |
| `v24/cordis/load.py` | canonical order加入42，精确数量改为17 | 不修改 frozen `v24/load.py` 或 v8 loader |
| DP1 `test_environment.py`,`test_ddl.py`,`test_kernel.py` | exact tuple/DDL guard/旧协议断言按新合同适配；test_kernel.py旧单文件1200改为全部advance/helper模块总计≤5000 | W1同步预算迁移，保留claim/replay/ACL/锁序负例及DDL≤900 |
| DP2 `test_kernel/install/activation/boundaries.py` | 替换由DP3接管的unsupported预期，补新live/关闭边界；test_boundaries.py旧单文件1200改为全部advance/helper模块总计≤5000 | W1同步预算迁移，后续行为与对应实现同里程碑原子更新 |
| `v24/cordis/dp3/test_support.py` | 复用DP1/DP2 Server/TestDB/snapshot/seed，标记fixture证明范围 | 不是生产维护器 |
| DP3五个 `test_*.py` | CDP3-P/L/T/D/B具名断言 | 每阶段新增后加入累计门禁 |
| DP3 README 与 DP3 matrix/ledger | 实际命令结果、覆盖、偏差、fixture边界、失败历史 | 每里程碑更新 |
| DP2 README/matrix/ledger；DP1 README | 订正当前状态或追加指针 | 不能改写历史通过事实 |
| `v24/cordis/sql/50_permissions.sql` | 预期不变；用 gate 证明新 helper无公开 EXECUTE | 如确需改权限，重新审查唯一 DEFINER/公开面 |

明确不修改八领域表与两簿记表定义、`20_relations.sql` 的非延迟历史FK、冻结 v24 loader/SQL/s1–s12、v8 loader；除非 Oracle 裁决后证明规格必要，并重新进行范围审查。

## 6. Risks、兼容与回退

| 风险 | 控制/停止条件 |
|---|---|
| 正常 drift 被误作身份攻击，旧 continuation 卡住 I7 | identity/binding 与 control selector 分开；交错 off/on/retry 与旧 fence 测试 |
| coalescing 改写 frozen input 或放松 I7 | 不更新 ready 行；保留唯一索引；当前 continuation 先结算再插 successor |
| deferred 留下 receipt/半步释放或持 G 等待 | mutation前返回、十表snapshot、第二连接取G；调用方立即结束事务 |
| P2 catch 吞掉内核错误 | 业务预检优先；捕获仅精确已分类 constraint；所有其他异常重抛 |
| live 递归重复路径/误把容量当 false | visited去重、512上限、容量独立错误、dense DAG与边界gate |
| 旧 pin 被新 resolver 规则拒绝 | pin-by-id冻结读取与resolve分开；withdraw不改旧pin可读性 |
| tombstone 被实现成物理删除破坏历史FK | 释放标志保留行；证明 prev/pin 引用仍可查 |
| run/cell/reservation/listener fixture 被当成生产能力 | matrix分列真实advance与owner DML；无生产入口处 fail closed |
| dispose 无界展开或 coordinator 自等待 | 单批硬上限、child-first、释放事务再推进；无DP6公平性声明 |
| SQL拆文件掩盖预算 | 40/41/42及未来helper模块逐项和合计一起报告，总计≤5000物理行；manifest与DP1/DP2预算断言同步；仅实际超限才简化/重裁 |
| DP3数据回退DP2不可推进 | 无在线migration/回退承诺；保留数据库前向修复，不伪造终态 |

兼容策略：保留既有 iterator v1 的精确键 `v,next_index,registered_through,control_seq`、冻结ω/committed_view及所有已提交response，不用 teardown cursor替换iterator，不补写历史receipt。loader仅用于独立 disposable DB的全量装载，不是在线migration；40在42之前创建时的函数体引用必须在canonical整库load自检覆盖，SQL-language定义不得前向引用尚未创建对象，PL/pgSQL延迟解析也不能掩盖首次调用失败。DP2数据库没有自动升级/降级承诺；若未来需升级，单列前向迁移计划，出现DP3 closing/released事实后不回退DP2 writer，不通过改历史终态“修复”。

守卫与writer同阶段落实：withdrawn_at/released_at只能NULL→首次值且不可回退；活pin禁止指向released贡献；活pin→released允许且身份仍immutable；episode.state只reloading→active/closing、active→closing；closed通过closed_at非空表示（schema无closed枚举），封闭后state/outcome/closed_at不可回退或重写；close原子清current pointer/retire facts；install dispose_pending→disposed不可逆；fiber disposed及run ended_at首次值不可清除或改写。guard不能误拒同事务FK序写入；deferred最终事实校验与即时identity guard分别测试。

## 7. 用户预算修订、Oracle-adjudicated decisions 与发布阻塞

用户选择 Oracle adjudicates。以下工程选择于 2026-10-27 经一次批量裁决，并针对 dispose handoff、预算和 failure 等审查发现的材料歧义做了窄复核。用户随后于2026-10-27明确将总预算设为5000，覆盖先前1200裁决及其压缩阻塞；其余工程裁决不变。理由、置信度、推翻条件和范围假设均记录如下；dispose 单步、显式手动重入、successor-only event 和测试燃料含保守范围假设，并非用户表达的偏好；其余按工程证据裁决。

| 决策 | 最终选择与理由 | Confidence / 推翻条件 |
|---|---|---|
| SQL布局/预算 | Oracle布局仍为canonical42、manifest17；40协议、41既有生命周期、42 teardown。用户2026-10-27修订：40/41/42及未来helper模块全部物理行合计≤5000；历史2227在预算内，余2773，无前置压缩阻塞。W1同步迁移旧预算gate；实际超5000才简化/重裁 | 用户明确决定，非Oracle偏好假设；覆盖旧1200裁决。计数含空行、注释，拆文件不扩大预算；后续改变上限须有新授权 |
| P0/P5 withdraw | P0只写控制/retire，P5才closing并撤新解析可见性；P0不写withdrawn/released/pin | 高。只有正式修订规格并同步规则表、阶段表和崩溃语义才推翻 |
| inverse范围 | service/delete_row、child/dispose_child生产执行；listener仅fixture+真实teardown账本清理；cell/reservation无可判定projection时0A000；unknown为blocked_unknown。`delete_row`保留历史行，以released_at逻辑释放 | 高。需权威恢复投影/生产入口或历史归档证明才扩大/改物理语义；fixture不能推翻 |
| continuation/I7 | 不改ready input/actor/parent/ordinal/episode身份；有效旧continuation只清旧代或no-op；当前effect先结算再建唯一后继 | 高。需具体合法交错证明该合同永久卡槽且有满足I7/same LOGIN的替代 |
| Raise/deferred与有界清理 | 业务失败全批预检产生Raise；防御时仅精确23505+`contributions_service_addr`窄回滚；未知异常整笔回滚。deferred零写、不消费request/effect/receipt/event/successor并结束事务释放G；inverse/pin各≤32 | 高。fault injection若显示窄捕获吞其他写则移除/进一步收紧，绝不改catch-all |
| dispose单步 | 每次advance最多一个fiber或一个child-install清理步骤，最多一个successor(ordinal 0)，child/consumer优先、父最终完成 | 中高。DP3保守范围假设，不是I7/B=16逻辑必然；需具体合法序列证明单步不能完成且批量仍满足I7、B16、单事件、closure512、child-first、父最后及事务释放G才推翻；仅性能收益不够 |
| P1缺依赖 | 无episode且缺required provider返回既有`dependency_unresolved`，十表零写，不建episode/failure/pin、不消费request或successor，保留原input重试 | 高。仅正式合同要求committed pending/no-op并定义receipt/wakeup才推翻 |
| dispose handoff | 唯一 successor 只代表所选 child/fiber 的 ordinal0 reconcile；parent controller 与最终墓碑由同一 LOGIN 的新 `command_dispose` request key 重入，原 key 只 replay；已有工作合并不竞争 | 高。只有已实现并通过 gate 的 kind-aware dispose continuation 合同能推翻 |
| retry/close→begin | retry 仅 current failure 或 closing 旧代；on-on 纯 no-op receipt；close 后新 begin 需最新合法 same-LOGIN 请求/continuation，无自动 scanner | 高。只有权威合同明确 poke/无条件 retry/自动唤醒才推翻 |
| child inverse seal | child 已 tombstone，或无活义务且 parent `dispose_pending` 的永久 lineage seal 已封锁 activation/resolve/retry/register；无法证明 seal 则等 tombstone | 中。若 seal 下仍可复活，退回 tombstone-only |
| W1/W3 证据边界 | W1 只做 non-production interpreter/barrier probe；真实 P6 分类、commit、replay、cleanup 移到 W3 | 高。除非 W1 前移真实 P6 selector/applier 并由生产 advance gate 验证 |
| successor-only event | 新建 successor 产生目标 install 的 `install_dispose_progress(work_scheduled)` 单聚合事件；复用槽、no-op、replay、deferred、error 均零事件 | 中高；这是 DP3 局部事件假设。若消费者合同证明 successor-only 必须零事件，需同步修订 validator/gate |
| cancellation | DP3 不增加 ready→cancelled facility；ready/claimed/unknown/host_io 是 barrier 或稳定拒绝，lease expiry 不视为完成/取消/释放 | 高；只有已有生产取消入口及完整 ownership/receipt/drain 合同才推翻 |
| failure v1 | phase按实际检测点为p2/p3/p4；七键闭集与code/reason/key精确组合见§3.6，P4可定位key；不清空旧代字段，历史由episode/event保存 | 高；无既有生产writer兼容负担，权威消费者合同可推翻；key上限沿用源码128 |
| finite driver | 测试 driver 用新 request keys、原 key 只 replay；fixture fuel=`16 × (1+F+I+E+C+P)`，每个 productive step 严格降 rank；燃料公式为测试假设，不是生产上限 | 中高；若合法 required fixture 超燃料或 rank 无法下降，报告失败并按证据修正 rank/系数，不缩减必需覆盖，也不取消进展要求 |

发布分支/remote 是**用户级阻塞**而非 Oracle 工程问题：`AGENTS.md` 写 origin main，DP2 的 origin/v24 授权不延伸至 DP3。2026-10-27 用户已明确目标为 `origin/v24` 并授权全部 DP3 里程碑逐个发布。B0/W1/W2/W3 已发布。W4 已实现且 24 条门禁全绿，本提交发布；W5 未实现。

## 8. Implementation order

### B0 — 基线与工件订正

- **Goal：**固定真实 v99 基线与 DP2 当前完成状态。
- **Done when：**重新跑 §4.1 的21条旧命令；HEAD/upstream/status/env、12 hashes、frozen diff、40/41/DDL/manifest测量完整；三处DP2当前状态订正并保留历史证据；DP3 README/matrix/ledger建立。不得复制DP2退出码。
- **Key files：**本计划、DP2 README/matrix/ledger、DP1 README、DP3收尾工件。
- **Dependencies：**无。发布目标为用户 2026-10-27 授权的 `origin/v24`；本工作项由 B0 提交发布。
- **Size：**M。
- **B0 result (2026-10-27)：**21 条既有命令在本工作树 HEAD `9fe6b5b` 上逐条实跑，退出码均为 0。冻结 diff 与 `git diff --check` 退出 0。十二份 SQL SHA-256 与 DP2 matrix 一致。测得 40=1130、41=1097、42 不存在、合计 2227、DDL 前缀 414、manifest 16、表 10；CDP2-B 断言仅一个 DEFINER。源码无 VIEW/EXTENSION。DP2 三处过期当前状态已订正，历史行保留。DP3 README、matrix、ledger 已建立。未改 SQL 与测试。该结果在门禁当时尚未提交。B0 由前一个提交发布。5000/5001 迁移未跑。细节见 `docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md`。

### W1 — 布局、协议、deferred 与槽位

- **Goal：**按裁决新增42并落实私有控制结果；保留旧协议身份、replay、I7和claim行为。
- **Done when：**同步迁移DP1 test_kernel.py与DP2 test_boundaries.py旧预算断言，证明40/41/42及未来helper模块全部物理行合计≤5000，并验证总计5000通过/5001拒绝；CDP3-P 的 non-production barrier probe 通过，证明 command 分流、十表零写和第二连接取 G，但不宣称生产 P6；身份伪造与正常drift分离；以probe验证coalescing不改ready input，真实off/on/retry状态转换及gate留W2；42及17项loader/exact tuple/boundary断言同步通过。
- **Key files：**40、41、42、`v24/cordis/load.py`、DP1 environment/kernel、DP2 boundary、DP3 support/protocol。
- **Dependencies：**B0、Oracle布局裁决、用户2026-10-27的5000总预算修订。
- **Size：**L。
- **W1 result (2026-10-27)：**同一工作树、未提交 HEAD `9fe6b5b`。两处 P2 关闭后，22 条命令再次逐条实跑，退出码均为 0：§4.1 的 21 条，然后 `uv run python v24/cordis/dp3/test_protocol.py`。CDP3-L/T/D/B 未加入、未运行。`splitlines()` 实测 40=1170、41=1097、42=16、合计 2283≤5000。审查的两处 P2 已关闭。共享 `v24/cordis/helper_budget.py` 的 `assert_helper_budget` 在临时目录上被调用：文件恰好是 `40_advance.sql`、`41_lifecycle.sql`、`42_teardown.sql`，合计 5000 物理行时返回 5000，合计 5001 时抛出 `AssertionError` 且总数为 5001。DP1 `test_kernel.py` 直接调用 `prove_helper_budget_boundary()`，不导入 DP2。DP2 `test_support.assert_helper_budget` 先跑同一证明再检查真实目录，所以 CDP2-K、CDP2-I、CDP2-B 都执行它。字面 5000/5001 整数比较不是该证明。40/41/42 在这次修复中没有改行数。DDL 前缀 414。manifest 17。表 10。仅 `advance` 为 SECURITY DEFINER。源码无 VIEW/EXTENSION。冻结 diff 与 `git diff --check` 退出 0。`42_teardown.sql` 只有生产 `command_barrier`（返回 NULL）和只读 `lifecycle_step`（精确 `{tag:"idle"}`，`advance` 与 `interpret_command` 不调用）。其余六项 teardown helper 未建。command 私有控制结果在 `validate_and_apply_delta` 之前分流。deferred、`blocked_unknown`、`unsupported` 由替换 `command_barrier` 的非生产探针证明：十表零写，调用方提交后第二连接取得 G。该探针不是生产 P6。replay-first 在屏障仍非 ready 时证明：生产 NULL `command_barrier` 下先提交一笔 admitted existing-scope install（`disposition` committed）；再把函数换成 `{disposition:"deferred"}` 与 `{disposition:"blocked_unknown"}`；同一 request（同一 key、同一 payload、同一 effect）重放首次 response，十表快照不变，仍是一条 request 与一条 event；然后才在 `finally` 恢复原函数。该重放不是生产 P6，也不是 W3 的屏障满足后首次提交。身份伪造仍是 `effect_id_conflict`。有效身份下的 generation/target/phase 由 `continuation_state` 返回无 `code` 的 `{class:"control", reason}`，advance 仍在解释器前以 `0A000` 失败关闭。ready input 的 UPDATE 为 `55000`，第二 ready reconcile 为 `23505`，已有槽时 `on` 为 `0A000`。没有合并提交，也没有改槽 input。`off`/`retry` 仍 `0A000`。claim 与 I7 保持。未实现 Divert/Raise/Leave、live、P5、P6 或已激活实例 dispose。该结果在门禁当时尚未提交。本提交发布 W1。细节见 DP3 matrix 与 ledger。

### W2 — live 与进入 closing

- **Goal：**传递live、P3 target/frozen-view比较、Divert/Raise/Leave和failure记录。
- **Done when：**CDP3-L及CDP3-P的真实off/on/retry/CAS/overflow/coalescing累计断言通过；新解析随失效关闭，旧pin仍可读；P0不withdraw、P5才withdraw；Divert/Raise不inverse；已分类失败同调用原子Raise；未知异常整笔回滚；P1缺依赖返回`dependency_unresolved`且零写；生产service/child成功路径仍真实。
- **Key files：**40/41/选定teardown SQL、30 triggers、DP2 activation/boundaries、DP3 live。
- **Dependencies：**W1。
- **Size：**L。
- **W2 result (2026-10-27)：**门禁实跑于 v99、分支 `v24`、HEAD `103ec596040506e74a7babdc240312885843d9f0` 加本阶段未提交改动。最终按 §4.1 的21条旧命令，再 CDP3-P、CDP3-L，逐条启动并等待退出；23条全部退出0，总耗时87.36秒。实现 transitive live 与 private `pin_readable`；resolve、owner/install admission、activation consistency 与 reconcile 复用同一 provider live 诊断。真实 P0 on/off/retry 覆盖 CAS、首次 no-op receipt/replay、ready/claimed coalescing、bigint overflow、旧 NULL/non-NULL fence；旧 NULL-fence 槽按原 input 结算零领域写 no-op，不冒用新代，后续合法控制可激活。reloading 控制/target drift Divert 不 withdraw；active 失效 Leave 在同次 advance 精确 withdraw≤256，不 release pin。P2 address/contract、P3 check/contract、P4 可归因 totality 失败提交 exact failure-v1 Raise；P1 缺依赖仍 `dependency_unresolved` 十表零写，保留 input 可重试。typed writer/validator/applier 同步落地；domain validator 独立重算 selector 与 P1 resolver target、完整 closing/P0 delta；所有既存写目标须在 closure，应用后以 VOLATILE fresh SQL 校验。
- **W2 failure/边界证据：**CDP3-L2 在真实32行已提交 prefix之后，本批第二条 INSERT 的 AFTER trigger 看到累计34行才抛精确 `23505/contributions_service_addr`；窄子事务回滚本批及 iterator，再同一 advance 只提交一条 Raise。domain、iterator、effect settlement、request、event、successor 六边界故障均整笔回滚；其他 unique/FK/CHECK/cancel/timeout 原异常传播。L3/L4/L9 覆盖 failure 七键类型/NULL/五组合、冻结 episode 代次、单向 closing/withdraw/failure guard。L5/L6/L7/L8 覆盖诊断一致性、dense DAG512/513、write closure512/513、601 closed generations与600 terminal parent历史不膨胀、P5全集256/257及无关kind不变、伪造P1 target/旧P2/closing cause拒绝及 suppressed INSERT 后置失败。DP1/DP2旧断言按意图迁移，保留 service/child、1/32/33、basic dispose、多fiber/host六态、ACL/claim/replay成功与拒绝路径。一次 Oracle review 的两项发现已修复并在最终批次验证；初轮 generation selector/validator 不一致及旧 unsupported/诊断断言失败记录见 ledger，不将初轮记为绿色。
- **W2容量/冻结/范围：**40=1259、41=1119、42=557，合计2935≤5000；5000/5001临时树预算证明仍执行。DDL前缀458≤900、manifest17、十表、唯一DEFINER=`advance`、源码VIEW/EXTENSION均0；新helper没有public EXECUTE。十二份冻结SQL hash与DP2 matrix一致，`57e2c1e`冻结diff、v8相对HEAD diff、`git diff --check`均退出0。四份DP3工件更新；loader未改、manifest已核验。未接通P6 inverse/pin release/close或已激活dispose，`command_barrier`生产仍NULL、`lifecycle_step`仍idle/unwired；fixture release、run、cell/listener/reservation、cycle/历史损坏只证明明确账本边界。本提交仅逐路径暂存W2，保留10份无关dirty docs和24份无关untracked。发布后立即暂停W3–W5。

### W3 — P6 drain 与 inverse

- **Goal：**closing episode有界卸载、pin release、close和最新目标再begin。
- **Done when：**CDP3-T通过；inverse/pin批次≤32且倒序；最高 seq≤32 精确选择，若所选集包含 unsupported/unknown 整批不得过滤跳过；历史FK可查；unknown/unsupported明确阻塞；run fixture仅证明barrier语义；P6 deferred十表零写。
- **Key files：**30、40/41/42、DP1 DDL gate、DP3 teardown。
- **Dependencies：**W2。
- **Size：**L。
- **W3 result (2026-10-27)：**门禁实跑于 v99、分支 `v24`、HEAD `72af2528`（W2 基线）加 W3 改动（提交前）。按 §4.1 的 21 条旧命令，再 CDP3-P、CDP3-T，逐条单独启动并等待退出；**23 条全部退出 0，总耗时 62.92 秒**。生产路径经真实 `advance` 证明：
  - P6 selector `p6_plan` 按固定顺序分类 hard unsupported、unknown、open owned run、其他 ready/claimed effect、terminal run pins、contribution inverse、activation pins、close；`command_barrier` 把 deferred 映射为私有控制结果，ready 返回 NULL，unknown/unsupported 在写入前以 `blocked_unknown`/`0A000` 失败关闭。
  - typed op `contribution_inverse`（≤32、seq DESC）、`pins_release`（run pins 按 `(consumer_run_id,key,id)` 在前，activation pins 按 `(key,id)` 在后，合计≤32）、`episode_close`；对应事件 `contributions_released`、`pins_released`、`episode_closed` 均进入闭集 payload 校验。
  - `run_pin_release_delta(run_id)` 只消费 owner/episode 对齐、`ended_at` 非空、无未结 effect/unknown/host_io 的 run，只返回未释放 pin，不写 run result/settlement。
  - applier 逐项重查 fresh SQL 后置条件；close 只写 `episodes.closed_at`、清 `fibers.current_episode_id`/`retire_started_at`，不重写 state/outcome/failure/want_on/dispose。deferred 当前 episode guard 在同一事务通过。
  - `reconcile_command_seed` 纳入 current episode 的全部未释放 contribution（含 child/withdrawn）、owned runs 与 run pins，保持 512 上限，不拉取全部 released 历史。
  - child inverse 仅接受 owner-fixture 已 tombstone（`fibers.disposed_at`）的 child；否则 deferred。因 `14_contributions.sql` 的 CHECK 要求 released 前 withdrawn 非空，applier 在同一 inverse 写中把 `withdrawn_at` 作为释放簿记前置，保留物理行/FK；P5 `withdrawn_ids` 仍不含 child。该 schema-forced 语义记入 deviation ledger。
  - 生产 successor 策略：inverse 与 pin-release 步骤各产生一个 ordinal 0 的 `command_reconcile/advance` 后继，使同一 LOGIN 能继续 drain；close 不产生后继、不开新 episode。原因是现有协议只允许 reserved key 的 `advance`；host 通过 P0 `off` 空闲 schedule 获得首个 P6 槽。该选择在 ledger 记录为协议约束下的最小后继，不是新调度器。
  - `lifecycle_step` 保持只读 idle 且未接线；CDP3-P4 契约不变。`30_triggers.sql` 只新增 run `ended_at` 首次值不可清除/改写的单调 guard。
  - CDP3-T 覆盖：无 run 的 activation pin 阻断 provider release 并被真实 consumer pin-release 解锁；open run／ready／claimed（含过期 lease）／unknown／host_io barrier；ended-run fixture 只释放 pin；32+1 严格 seq DESC；run/activation 排序与合计 32；service/listener 账本 inverse（listener 为 owner fixture）；tombstoned child inverse；历史 pin/prev FK 保留；withdraw 单独不释放地址、release 后才可复用；空贡献 close；重复刷新/重放不重复释放；deferred 十表零写。
  - CDP3-P7 用真实 P6 证明 deferred 十表零写、同 request 在 open run 结束后首次提交、再次调用 byte-identical replay；不再引用 W1 非生产 probe 作为生产 P6 证据。
- **W3容量/冻结/范围：**40=1356、41=1141、42=758，合计 **3255≤5000**；临时 5000/5001 预算证明仍由 CDP1-K0/CDP2-K0/I0/B 执行。DDL 前缀 461≤900、manifest 17、十表、唯一 DEFINER=`advance`、public function EXECUTE 0、源码 VIEW/EXTENSION 均 0。十二份 frozen SQL SHA-256 与 DP2 matrix 一致；`57e2c1e` frozen diff、v8 相对 HEAD diff、`git diff --check` 均退出 0。未修改 loader、表、列、enum 或 extension。W4 已激活 dispose、DP4 settlement、DP5 listener/dispatch/intercept/overlay、DP6 scanner/external recovery 与 child cleanup fan-out 仍未实现；host_io/settlement 继续保守拒绝，不得由终态标签推断外部资源已释放。本提交发布 W3 到 origin/v24。

### W4 — 已激活实例 dispose

- **Goal：**在不无界扇出的情况下封住准入并推进子项、fiber和install墓碑。
- **Done when：**CDP3-D通过；唯一 successor 只代表一个 child/fiber reconcile，parent controller 由新 same-LOGIN dispose request 重入；每次最多一个fiber或child-install清理步骤；child tombstone 或永久 seal 后才释放 parent ledger；父不早关闭；rank driver 在燃料内严格收敛；持锁等待为零；same LOGIN 与I7保持；host_io仍保守阻塞。
- **Key files：**40/41/42、DP2 boundaries、DP3 dispose。
- **Dependencies：**W3。
- **Size：**L。
- **W4 result (2026-10-27)：**v99、分支 `v24`、HEAD `284d7f2d420f6c9a73b1326bb7b4497ee8fa498e` 加 W4 改动（提交前）。按 §4.1 的 21 条旧命令，再 CDP3-P、CDP3-T、CDP3-D，**24 条逐条串行启动并等待退出，全部退出 0，总耗时 93 秒**。
  - 首次 `command_dispose({install_id})` 只写 `install_dispose_request`：把目标 install 置 `dispose_pending` 并产生 `install_dispose_progress(phase=requested)`，不清理 fiber。`dispose_ancestor_sealed` 让整个 owner lineage 的 activation/resolve/retry/register 在看得到的 ancestry 上失败关闭；`fiber_lineage_open`、`live_node_fault`、`activation_admission`、`install_admission` 复用该检查。
  - 后续每次 dispose request 只选一个对象：最深 descendant fiber 优先，其次 child-install 墓碑，再本 install fiber，最后父 install 墓碑。所选 fiber 有 open episode 时先发 `fiber_dispose_request`（`want_on=false`，必要时 `control_seq+1`）并附唯一个 ordinal 0 `command_reconcile/advance`；否则只 schedule 同 fiber reconcile（successor-only `work_scheduled` 事件，domain 为空）；无 episode 但 `want_on=true` 时只写 control 不发 successor；槽已存在时合并为无事件 no-op。
  - typed ops 为 `install_dispose_request`、`fiber_dispose_request`、`fiber_dispose_finish`、`install_dispose_finish`；`install_dispose_progress` payload 严格四键，phase 仅 `requested/fiber_requested/fiber_disposed/work_scheduled/completed`，`scheduled_targets` 长度≤1，无目标为 JSON null。有领域写时恰一条领域事件；successor-only schedule 恰一条 `work_scheduled`；domain+successor 仍只一条领域事件；coalescing/replay/deferred/error 零事件。
  - `continuation_state` 扩展 dispose parent 分支：只接受成功、同 LOGIN、目标 install 已 seal 且 selected fiber 位于该 install owner subtree 的 ordinal 0 reconcile；不要求 parent.fiber_id=child.fiber_id。validator 通过 `dispose_delta` 独立重算 target/phase/successor/event，伪造 interpreter 输出零写拒绝（CDP3-D7）。
  - applier 用 fresh VOLATILE SQL 校验后置条件；`fiber_dispose_request/finish` 只写 fiber 控制/墓碑，`install_dispose_finish` 要求 `dispose_block_reason` 清空且该 install 全部 fiber 已墓碑。父 install 墓碑只能在 child install 与自身全部义务清空后发生。
  - `dispose_plan` 在写入前对整棵 sealed subtree 保守检查：任意 host_io（六态）→ `unsupported/0A000`，非 host unknown → `blocked_unknown`，非 reconcile ready/claimed effect 或 open run → deferred。dispose 不持 G 等待；CDP3-D5 证明 deferred 十表零写、调用方提交后第二连接取得 G、run 结束后新 request 继续。
  - `dispose_command_seed` 只锁定 target install 与本次选中 fiber（或 child install）；episode/owner/scope 由 `discover_closure` 的引用链补入，已结算 effects、released pins、ended runs 与历史 episode 不进 closure。512 上限与锁后复验保留；600 条 settled 历史 effect 的回归仍可收敛（CDP3-D9）。W3 的 `reconcile_command_seed` 未改。
  - CDP3-D 覆盖真实 activated parent/child 的 child-first、parent-last、唯一 successor、原 request replay、fresh request 合并、dispose seal 后 register/on/retry/resolve 零写拒绝、不同 LOGIN 拒绝、host_io 六态保守阻塞、tombstone 不复活，以及燃料 `16×(1+F+I+E+C+P)` 内的 `(M,U)` rank driver（productive step 降 M，schedule-only 降 U，coalescing 不计数，无阻塞）。
  - DP2 `test_boundaries.py` 与 `test_kernel.py` 按意图迁移到 staged dispose：clean/multi-fiber 真实收敛、各义务与六态 host_io 仍阻断。`basic_dispose` 已从生产 validator/applier/typed op 闭集中删除；非生产 probe 也使用 staged op。
  - 一次 Oracle review 发现四点并已修复：dispose closure 不再纳入历史 episode/effect/run/pin；dispose parent successor 必须 ordinal 0 且被 parent receipt 的 `emitted` 精确列出；`basic_dispose` 旁路删除；JSON error 负例改用十表零写快照。另修复多级 child install 的完成顺序为 depth DESC，避免父 child install 先被选中而永久 deferred。CDP3-D8/D9 覆盖后继伪造与历史 closure；D1 扩展到 root→child→grandchild。
- **W4容量/冻结/范围：**40=1373、41=1193、42=964，合计 **3530≤5000**；临时 5000/5001 预算证明仍执行。DDL 前缀 461≤900、manifest 17、十表、唯一 DEFINER=`advance`、public function EXECUTE 0、源码 VIEW/EXTENSION 均 0。十二份 frozen SQL SHA-256 与 DP2 matrix 一致；`57e2c1e` frozen diff、v8 相对 HEAD diff、`git diff --check` 均退出 0。未实现 W5/CDP3-B、DP4 settlement、DP5 listener/dispatch/intercept/overlay、DP6 scanner/fairness/external recovery；child cleanup 由父 controller 通过真实 `command_reconcile`/dispose advance 驱动，外部 consumer 仍为 owner fixture/阻塞边界。本提交发布 W4 到 origin/v24。

### W5 — 最终边界与收尾

- **Goal：**证明本阶段全部合同并完整记录限制。
- **Done when：**21条旧命令+5条新增DP3 gate按最终文件串行退出0；freeze/hash、容量、manifest、ACL、10表、单DEFINER都记录；matrix/ledger/README覆盖生产/fixture/未实现三类证据；无遗留失败。
- **Key files：**全部DP3 gate和收尾工件。
- **Dependencies：**W4。
- **Size：**M。

每个里程碑收尾顺序：全部当前gate串行实跑且全绿 → 更新计划/README/matrix/ledger及loader核验 → `git status` → 按具体路径逐项 `git add`（严禁 `-A`/`.`）→ 检查 staged name-status、完整diff、diff-check和凭据 → 独立commit → 仅推送用户明确授权目标。失败即停，不跳过hook，不 force-push，不重置用户历史，不把多个里程碑合并提交。B0/W1/W2/W3 已按此纪律发布到 `origin/v24`（`ba4f533` / `103ec596` / `72af2528` / `284d7f2`）。W4 已由本提交发布到 origin/v24；W5 不得自动开始。

## 9. References 与保真索引

- 规格：`docs/designs/cordis-plugin-system-2026-10-25.md:87-427,465-603,617-639,722-860,1000-1071`（不变量、advance、生命周期/inverse/live、命题前提、upgrade顺序、预算/gates/debts、伪代码/术语）。
- 阶段边界与前作：DP1 plan `:195-280,:371-449`；DP2 plan `:1-100,:889-1018,:1178-1223`。
- 实现：`v24/cordis/sql/40_advance.sql:140-331,357-565,623-1130`；`41_lifecycle.sql:530-536,717-964,1040-1097`；`20_relations.sql:12-23`；`30_triggers.sql:31-234`；`17_effects.sql:25-28`。
- 工件简称：DP2 matrix=`docs/reviews/cordis-v2-dp2-conformance-matrix-2026-10-26.md`；DP2 ledger=`docs/reviews/cordis-v2-dp2-deviation-ledger-2026-10-26.md`；DP1/DP2 plan分别为`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md`、`docs/plans/v24-cordis-dp2-lifecycle-plan-2026-10-26.md`。
- 验证/历史：DP2 matrix/ledger、`v24/cordis/dp1/README.md`、`dp2/README.md`、`dp2/test_support.py` 与 `test_boundaries.py`；仓库 `AGENTS.md:7-57`。

保真检查清单：

| Export baseline item | 本计划落点 |
|---|---|
| I1–I8、same LOGIN、单事件、24码、容量与冻结基线 | §2.3、§4.2 |
| 私有control结果、exact op/whitelist/DML序、事件schema及successor-only改约 | §3.2-3.3、§3.9、CDP3-P/B |
| P0真值表、failure七键组合、close→begin矩阵 | §3.6、CDP3-L |
| live逐节点诊断、O(V+E)、九列resolve/private pin ABI | §3.5、CDP3-L/T |
| 分支closure锁/读/复验、长历史、fresh VOLATILE后置检查 | §3.8、CDP3-B |
| dispose handoff、parent whitelist、永久seal、rank/fuel | §3.4、§3.7-3.8、CDP3-D |
| iterator v1、loader非在线迁移、单向guard与前向修复 | §6、CDP3-B |
| deferred 零写、不消费receipt/request、结束事务释放G | §3.3、CDP3-P |
| 身份与正常control drift分离、I7 coalescing | §3.4、CDP3-P/L |
| 失败批回滚后同调用Raise、窄异常范围 | §3.6、CDP3-L |
| live传递性与withdraw期间旧pin可读 | §3.5、CDP3-L/T |
| cleanup DAG、FK、tombstone、倒序和批量 | §2.2、§3.7-3.8、CDP3-T |
| bounded dispose与锁死风险 | §3.8、CDP3-D |
| run/cell/reservation/listener/unknown fixture证明边界 | §1、§3.7、§4、CDP3-B |
| file-by-file、风险、回退、阶段和逐阶段验证 | §5-8 |
| DP2收尾订正、逐路径发布纪律、发布用户阻塞 | §2.1、§4.2、§8 |

保真复核结论（2026-10-27）：原export各实质章节的current state、接口/数据流、错误边界、file impact、风险/兼容、实施顺序与验证均有上述落点。相冲突lane并非同时要求实现：16对象dispose/新dispose kind替换为裁决后的单对象+外部重入；P1空成功/on-poke替换为dependency_unresolved+on-on no-op；cell/reservation fixture“恢复成功”替换为fail closed；domain-only event和40单文件预算替换为显式事件改约及三文件总预算。failure P3/可定位key按窄裁决固定，key长度以源码128纠正Oracle256建议；resolve九列及episode closed_at表示按源码纠正。原三/六脚本候选的具名验证无损归入五脚本，不创建多余gate。不得把这些有证据的修正理解为遗漏；DP1/DP2完成事实与测试历史未重写。用户2026-10-27的明确修订将原1200总预算及其前置压缩阻塞替换为5000总预算，其他保真落点不变，旧gate迁移与新边界验证列入W1。

保真与引用检查已完成：基线coverage ledger逐项保留或按上述证据修正；旧gate命令路径存在，SQL引用与9列resolve/episode状态按当前源码复核。设计critique已逐项处理，保留`docs/reviews/v24-cordis-dp3-teardown-plan-critique-2026-10-27.md`作为审查工件；临时context_builder export在本检查后删除。计划编写当时没有 gate 运行结果，静态核对不能写成测试通过。B0 执行后，21 条既有命令的退出码以 DP3 matrix 为准。

## 10. Open Questions 与 hand-off

总预算由用户于2026-10-27明确修订为5000物理行；其余工程设计项已由 Oracle 于同日裁决：新增42；P0控制/P5 withdraw；production inverse 范围与逻辑 tombstone；保持 frozen continuation/I7；窄 Raise、零写 deferred；P1缺依赖 `dependency_unresolved`；dispose 单对象且每次最多一个 successor。dispose 单步及不可达 inverse 范围是明确的 DP3 保守范围假设，不是用户已表达的永久产品偏好。

B0 已于 2026-10-27 重测：40=1130、41=1097、42 不存在、合计 2227，DDL 前缀 414，manifest 16，仍低于 5000，没有触发压缩。W1 当时仍须把 DP1 `test_kernel.py` 与 DP2 `test_boundaries.py` 的单文件 1200 断言迁到合计 5000 通过 / 5001 拒绝；B0 旧 gate 全绿不是那项迁移。21 条既有命令的 B0 退出码在 DP3 matrix 的 B0 节，不在本节复写。2026-10-27 用户明确授权全部 DP3 里程碑逐个 commit 并 push `origin/v24`，不改写 `AGENTS.md`。B0 由前一个提交发布，不实现生产 SQL、不改测试。

W1 已于 2026-10-27 在未提交工作树上完成：40=1170、41=1097、42=16、合计 2283，manifest 17，DDL 414。审查指出的两处 P2 已关闭：共享 `assert_helper_budget` 在临时 40/41/42 树上接受恰好 5000 行、拒绝 5001 行；已提交请求在 `command_barrier` 仍为 deferred 与 blocked_unknown 时重放首次 response 且零写，然后才恢复原函数。22 条命令于该修复后串行重跑，退出码均 0，见 DP3 matrix 的 W1 节，不改写上面的 B0 测量。`lifecycle_step` 的 idle、command deferred 探针和这次 replay 都不是生产 P6，也不是 W3 的屏障满足后首次提交。以上为 W1 门禁当时记录，W1 已发布为 `103ec596`。W2 的实现和23条全绿结果见 §8 W2 result 与 DP3 matrix/ledger；W2 已独立发布到 `origin/v24`。W3 已于 2026-10-27 实现：P6 drain、inverse、run/activation pin release、episode close 和真实 deferred/首次提交/replay 均有生产路径证据，见 §8 W3 result 与 DP3 matrix/ledger。W4 已于 2026-10-27 实现：seal-only 首步、单对象 bounded dispose、child-first/parent-last、dispose-parent successor whitelist、successor-only 单事件、host_io 保守阻塞、deferred 零写与燃料内 rank 收敛，24 条门禁全绿，见 §8 W4 result 与 DP3 matrix/ledger。本提交发布 W4 到 origin/v24；W5（最终 closeout）仍未实现。
