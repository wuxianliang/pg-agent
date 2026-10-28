# Cordis v2 DP5：事件派发与描述符解析 Deep Plan

> 状态：规划完成；B0 已于 2026-10-28 在 DP4 HEAD `ba66776` 上完成重裁并通过容量准入；W1/W2 已在该 HEAD 上实施并分别通过 32/32、33/33 命令（W2 为 31 继承 + `CDP5-R` + `CDP5-E`）并本地提交；W3 未启动。本文相对路径以 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` 为根；main checkout 不含 Cordis。DP1–DP4 已完成；DP4 W5 及两次收尾补正已本地提交，DP5 在 B0 重裁后接续。本文把 W1/W2 写成有实跑证据的已交付里程碑，W3+ 仍只写实施合同。
>
> 文中“现状”是规划快照，不是执行时 HEAD；“拟新增”是实施合同，不代表代码已存在。执行前重新记录 HEAD、工作区和所有引用符号，禁止把另一个会话的未提交工作作为 DP5 已完成事实。

## 1. Goal 与完成边界

DP5 在唯一 `advance` 提交口上交付 listener 生产注册、`dispatch/listener_call` 五模式事件面、overlay/intercept 有效描述符解析，以及设计稿 G4 的事件 refinement 证据。沿用 contribution 可逆账本、effect receipt、G 锁、独立 validator 与 typed applier，不新增领域表、命令或第二调度器。

**Done when：**

1. listener 经 `command_install` 声明和 reconcile P2/L-Iter 生产注册；混合 service/listener 的 seq、iterator、P4 totality、withdraw 与 P6 LIFO 都有生产证据；旧 manifest 无 listeners 时行为与字节保持。
2. 五种模式都有合法生产与执行路径；跨插件观察、priority 排序、serial/bail 短路、waterfall acc 链、emit 只保证生成，均有具名测试。in_db 在同次 advance 内执行；host 只在 claim COMMIT、连接 IDLE 后外呼。
3. dispatch input 冻结候选集；运行中进度只从可信 listener_call 子行及本次虚拟 receipt 派生，不把运行中 cursor/acc 写回 input 或未结算 outcome，不新增 dispatch_state；终态 result.acc 按五模式合同保留。重复 receipt 不重复子行或封口。
4. overlay/intercept 的有效 descriptor、check、committed view、run digest 与实际执行配置一致；旧 pin 在 provider withdrawn/closing 后仍可排空，released 后拒绝。
5. `CDP5-E/D/R/B` 四脚本和届时全部旧脚本独立进程、串行实跑 exit 0；保留所有非目标安全断言；旧拒绝边界只在同里程碑有生产证据后替换。
6. 十表（八领域表加 requests/events）、三 command kind、24 协议错误码、唯一 `SECURITY DEFINER=advance`、public EXECUTE 0、无 VIEW/EXTENSION；全部私有 helper 合计≤5500 物理行（2026-10-28 用户授权重裁），DDL 前缀≤900；冻结 SQL hash 不变。
7. loader、budget、README、conformance matrix、deviation ledger 与本文各 Result 已更新；按 AGENTS 实测→工件→逐路径 add→commit→push，先解决分支目标冲突。

**明确不做：**公平 scanner、§11 全量崩溃矩阵自动恢复、unknown 外部对账、upgrade/HMR、cancel/steer/respond、spawn/child run、多宿主、cell/reservation 生产 writer、realm ACL、`thisArg`、同步 disposer 链。waterfall 不恢复同步 next 控制权。model/tool 仍是直接 effect，不伪装成 dispatch。DP5 只认领 G4 事件/解析部分，不冒称 G1–G4 全规格已完成。

**两项实施闸门：**DP4 W5 已完成。2026-10-28 用户明确授权将私有 helper 总上限从 5000 修订为 5500；B0 在 HEAD `ba66776` 的工作树上实测 40–49 合计 **4338**，`R=5500−4338=1162≥900`，容量闸门重裁为通过（见 §9 B0-revised），31 条继承命令 **31/31 exit 0**。AGENTS 的 `origin main` 与工作树 `v24` 目标冲突仍未解决；本 worktree 的 `origin/v24` 仍停在 `4b34bf2`、分支领先 9 个提交，故 B0 不 commit、不 push，把发布留给 orchestration/用户点名目标。

## 2. Background 与 current-state analysis

### 2.1 权威、阶段分工与规划快照

唯一产品依据是 `docs/designs/cordis-plugin-system-2026-10-25.md`：§6.4（`:427`）事件三件套、五模式、in_db/host；§6.5（`:451`）intercept；§7.7（`:603`）精化及反例；§8.1（`:619`）overlay；§10.1（`:724`）预算；G4（`:754`）验收。DP1 分工表 `docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:206` 将 listener/dispatch/intercept/overlay 划给 DP5，扫描/恢复/unknown/升级划给 DP6。DP4 计划 `docs/plans/v24-cordis-dp4-run-settlement-plan-2026-10-27.md:5` 明确不做事件面。

规划初查 HEAD 为 `17c855d`（DP4 B0）；context builder 核证期间前进到 `e8b6cce`（DP4 W1），当时 W2 有未提交 model 变更，W3/W4/W5 未完成。DP4 已有的 26 条旧 gate + CDP4-R 历史实跑记录只是上游证据，本文没有重新运行。DP5 执行者必须接收 DP4 W5 的 HEAD、README、matrix、ledger、实际 helper 符号和完整命令清单；不得把规划时文件行号当固定接口。

该中间快照 helper：40=1546、41=1211、42=1000、43=459，共4216，余784；DDL前缀461、manifest18、十表。余784仍由 DP4 剩余工作共享，不是 DP5 可用预算。DP4 工作树同时含用户既有设计稿、DP1/DP2 文档等改动，DP5 不修改或暂存它们。

**B0 重裁快照（2026-10-28）：**DP4 已完成并本地提交到 `ba66776`（`v24` 分支；`origin/v24` 仍为 `4b34bf2`，`git rev-list --left-right --count origin/v24...HEAD` 为 `0 9`）。W5 之后另有 `73973d1`（harden settlement validation）与 `ba66776`（split settlement validation helpers）两次补正；`43_loop.sql` 为 **592** 行、25 个私有函数，工作树对该文件无未提交 diff，`CDP4-T/X/B` 均通过。B0 在 `ba66776` 加用户未提交的 41 去重重构与 5500 预算上重跑 31 条继承命令，**31/31 exit 0，185.9 秒**；helper 实测 40=1549、41=1197、42=1000、43=592，合计 **4338**；`R=1162`。规划时的 4216/784 与 blocked 的 4320/680 都只是历史快照，不是当前准入值。

### 2.2 接缝证据表

行号取规划快照；DP4 变化文件以“路径+符号”定位为主，B0 更新 matrix 中的实测锚点。

| 接缝 | 已存在事实 | DP5 改动责任 |
|---|---|---|
| listener DDL | `14_contributions.sql:6` 五kind、`:22` listener部分唯一地址 `(fiber,episode,event,listener_id)` | 复用，不加表/新listener索引 |
| effects | `17_effects.sql:8` 已有 dispatch/listener_call；`:16` ordinal 0–15；`:24` parent/ordinal唯一 | DB内部parent与provider-owned child使用同一账本 |
| pins | `15_pins.sql:11` consumer fiber/run XOR | dispatch不能持pin，不借run伪装引用 |
| 配置列 | `10_installs.sql:16` overlay；`11_scopes.sql:5` intercept | 现列足够，不增加领域列 |
| manifest | `41_lifecycle.sql:54` `manifest_shape_valid` 精确四键，provides要求service capability | 可选第五键listeners，不复用provides |
| 注册 | `41_lifecycle.sql` `interpret_reconcile` P2硬编码service；40 `contribution_append`只允许service/child | 统一registration_plan，扩listener typed校验与totality |
| fail-closed | 41 `install_admission`（`:205`）拒非空overlay/intercept；`activation_admission`、`activation_bindings`、`service_realm`、42 `scope_live_fault/live_node_fault`同类拒绝 | 同里程碑替换为形状、有效描述符和权限校验，不能只删拒绝 |
| resolve | `41_lifecycle.sql:543` 只合并realm近者优先，不读intercept | realm先解析，然后nearest-rule替换/拒绝 |
| 配置写入 | 40 `install_create`要求overlay={}；`scope_create` applier写死intercept={} | 扩typed op形状、install生产者、独立重算与后置条件 |
| settlement | `40_advance.sql:417` `interpret_settlement`只路由run三kind，其余0A000 | host listener_call接event planner；dispatch不开放外部claim/settle |
| ACL/合同 | 40 `role_allowed` service四kind；43 `claim_contract`按owner/provider区分 | 仅增加host listener_call，冻结descriptor与合同一致 |
| 后继 | 40 `validate_delta`已含两event kind但无input形状；`validate_domain`分支闸；applier未知kind0A000 | p4窄口flat dispatch，listener child仅typed append |
| 纯算子模式 | 43 的planner+独立validator重算，BEGIN ATOMIC reducer及依赖证明 | 复用风格，不能让validator只信planner |
| 闭包 | 43 `settlement_seed`按kind扩张；40 target_refs/discover/lock；42 `delta_write_closure_ok` | 增snapshot/provider/install/sibling/scope读写集合；旧kind不扩散 |
| 后置条件 | 42 `assert_delta_applied`未知op落ELSE NULL | 每个新增op具名WHEN，另加最终事件阶段检查 |
| 撤销 | 42 `withdraw_ids`已含listener；`p6_plan`（`:684`）允许listener/delete_row并查ready/claimed/unknown effect | 复用逻辑撤销；补跨owner parent unknown查询 |
| 不可变性 | `30_triggers.sql:75` 冻结effect input/终态；`:96` scope仅冻结id,parent,close墓碑 | 新增scope规则列UPDATE守卫，不能谎称已有 |
| 读通道 | DP4 claim响应input，applier响应emitted，无协议角色表SELECT | 增execution配置和可claim ready_effects元数据，无新writer |

DP3 中 listener inverse 只有 fixture 证据，不能倒写成历史生产实现（DP3 plan `:184`）。DP2 plan `:661`、`:694` 的 events≤1 是单entity簿记语义，多实体通知留DP5；本计划以listener/effect覆盖证明多插件通知，继续保留每delta至多一个bookkeeping event。events不是调度事实。

### 2.3 保持的协议与冻结面

same LOGIN continuation、replay-first、`revision=0`、24错误码、body≤1MiB/递归键≤200/depth≤32、closure≤512、B=16、successors≤16、三command闭集不变。COMMIT是唯一线性化点，外部IO不进入事务或G锁区。

冻结 `v24/load.py`、`v24/sql/**` 十二份SQL、`v24/s1`–`s12`；设计稿与DP1–DP4计划只读。可修改的是Cordis线 `v24/cordis/**`，其中30触发器属于本线DDL前缀，并非上述十二份冻结SQL；新增scope守卫仍计入DDL预算。所有私有helper无论拆函数/文件均计入总预算，禁止移出40–49逃逸。`50_permissions.sql`最后执行，撤销新增私有函数的public执行权。

## 3. 执行索引与总体数据流

| 项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| B0 | DP4交接、容量与发布目标核证 | DP4 W5实测旧gate全绿；按5500上限重算R=1162≥900；目标冲突已记录且不发布；冻结/工作区记录 | 本文、loader、budget、旧gate索引、matrix | DP4 W5；只读核证可先做 | M |
| W1 | overlay/intercept与旧run一致执行 | R1–R4/R8绿，旧摘要兼容、scope守卫和配置传递证据 | 30、40–43、test_resolution | B0 | L |
| W2 | listener生产注册与完整撤销 | E注册子集绿：统一totality、跨批、撤销与fixture屏障；不发dispatch、不要求事件排序/未生成unavailable | 40–42、test_listeners | W1 | L |
| W3 | 原子交付事件producer和五模式 | D绿；flat/open/append/settle、同步cascade、host路径和所有validator一并落地 | 40–44、loader/budget、test_dispatch | W2 | L |
| W4 | refinement与显式偏差 | R全绿；独立参考、纯度、emit/waterfall边界 | test_resolution、README/matrix/ledger | W3 | M |
| W5 | 全量回归与收尾 | E/D/R/B和全旧gate串行绿；实际预算/hash/Result完整 | 全DP5路径 | W4 | M |

数据流：install声明→P1冻结硬依赖→P2统一注册→P4 totality→p4对可见listener拍快照→flat dispatch与typed open→同步in_db或ready host child→host claim取冻结配置→事务外调用→receipt→虚拟后态派生progress→独立validator→原子append/seal→至多一条簿记event→emitted/ready_effects。

W2只完成注册，不提前开放producer。W3必须将producer、执行、validator、applier、postcondition、teardown fence、测试作为一个里程碑交付，避免持久化不可消费的dispatch。

## 4. Detailed design

### 4.1 listener声明与registration plan

manifest只接受两个exact-key集合：旧 `{requires,provides,priority,check}`，或再加 `listeners`。缺失与空数组走legacy快路径，不重写旧声明、不改变无listener的P2/P4 delta。`provides`继续是原有service声明；不扩作listener或顺带实现cell。

`listeners` 长度0–16，每项精确八键：

```text
{listener_id,event,mode,priority,filter,exec,contract_version,sync_reads}
listener_id/event: text 1..128
mode: emit|parallel|serial|bail|waterfall
priority: int32
filter: null | 现有{v:1,op:"equals",path:[text...],value:json} check_policy
sync_reads: JSON boolean false（必填）
exec:
  {type:"in_db",op:"const",value:json}
| {type:"in_db",op:"acc"}
| {type:"in_db",op:"append",value:json}
| {type:"in_db",op:"fail",code:text}
| {type:"host",capability:"listener_call"}
```

in_db的contract_version固定 `in_db_v1`，handler digest为 `H(C(exec))`；host要求install的`contracts.listener_call`存在且版本相等，继承其handler_digest及replay.repeat/concurrent，不能凭descriptor扩大重放权利。listener_id由声明者提供，manifest内唯一；现有episode/event/listener_id唯一索引提供最后防线。filter作用于事件params，不是provider descriptor。sync_reads缺失/true/null/字符串均拒绝；它是声明约束，不是host独立性证明。

`registration_plan(install)`为`provides ++ listeners`，保留provides顺序再按listeners声明顺序。每个plan item有kind与原位置；P2仍每批≤32，iterator.next_index指统一序列下一项，registered_through指最后contribution seq。listener行：realm/key/prev均NULL，inverse=`{op:"delete_row"}`，contract_version独立列，descriptor精确为八键中除contract_version外的七键（包括sync_reads），先应用合法overlay。

扩40的contribution_append形状/分支写集/semantic validator、41的P2生产器与activation_total、42后置检查。P4验证每个plan item的kind/seq/descriptor/contract_version/inverse与数量、连续性，不能只数provides。service继续验证realm唯一地址；listener不占service地址。同episode错误注册进入既有L-Raise→closing→P6，不在Raise中提前apply inverse。跨32项的target变化仍只Divert，完整accumulator交给P6，禁止混合激活。

install校验只证明本声明≤16，不用单manifest公式冒充跨scope fanout证明；实际候选集和创建数在p4原子验证。非法声明`invalid_args`；伪造delta/注册错配`invalid_outcome`；数据库唯一性SQLSTATE按原内核规则保留，不吞成成功。

### 4.2 overlay/intercept精确ABI与有效描述符

#### 4.2.1 overlay

空`{}`是legacy identity。非空精确：

```text
{v:1,services:{<provides key>:patch-object},listeners:{<listener_id>:patch-object}}
```

两个map必填，可为空；分命名空间避免service key与listener_id碰撞。未知声明名拒绝。object递归合并；array/scalar/null整体替换，不定义删除。patch根必须object，合并结果必须合法descriptor。深度≤4以patch/effective descriptor的语义容器树计：object/array根为第1层，scalar不增容器层，ABI wrapper不计；协议body原有depth32/200键/1MiB照常。使用同一深度函数，提供4/5层边界和array内object测试。

保护所有身份：service capability及独立contract_version不变；listener listener_id/event/mode、exec类型/授权handler、contract_version不可变；允许priority/filter及schema允许的配置变化，合并后重新全量校验。identity/version/artifact_digest不在descriptor patch空间。overlay不是新install链，无环问题，也不改变install唯一性。

#### 4.2.2 intercept

scope声明缺省沿用旧形状；新增可选intercept键，非空精确：

```text
{v:1,rules:[rule...]}
rule = {realm,key,action:"reject"}
     | {realm,key,action:"replace",descriptor,descriptor_digest,contract_version}
```

realm/key沿用现有标识验证；单scope的(realm,key)唯一，规则数受现有payload/key/closure预算约束，不引入无界查找。replace是完整descriptor替换，不是patch；`descriptor_digest`为hex64且等于`H(C(descriptor))`，contract_version必须等provider列，capability必须等stored descriptor，授权handler/replay不变。replace descriptor也按§4.2.1同一语义容器深度函数限制≤4，规则/ABI wrapper不计入描述符深度，协议整体预算仍不放松；不能只验overlay而漏intercept。规则在安装时做结构/摘要/深度校验，在解析到具体provider时做身份/合同相容校验，不相容拒解析且不得注册半个provider。

顺序：先按realm_overrides得effective realm→从consumer scope向根找第一条匹配intercept→none用stored descriptor、reject使新resolve unavailable、replace用完整descriptor。近scope规则整个覆盖远者，不叠加多个replace。intercept只作用service resolve；listener没有(realm,key)地址，不把intercept硬套listener。scope是路由不是ACL。

40的scope_create op增加可选intercept，applier不再硬编码{}；install_create允许合法overlay。41 install_payload/scope_shape/install_admission与生产delta、40精确op/独立validator、42postcondition必须同步，缺省路径字节不变。所有现有非空拒绝点逐个登记并替换，不能只绕install_admission而让live/check持续拒绝。

#### 4.2.3 摘要、scope守卫与实际执行配置

`C=既有canonical_json`，`H(x)=hex sha256(UTF8(x))`。P2存overlay后的descriptor；resolve对其应用intercept；check、activation_bindings与committed_view使用最终有效descriptor与`H(C(effective))`。

新增30的scope UPDATE守卫冻结`realm_overrides/intercept`，变化SQLSTATE55000；保留id/parent/close墓碑规则。原守卫没有此保证，不能仅凭“无生产writer”声称不可变。该文件是Cordis可变DDL，约+6–12行计入DDL≤900；守卫不声称防住能关闭触发器的superuser。

DP4的pin、committed_view字段及`{policy,schema,toolset}`三摘要ABI不增键：

- run_bindings从committed_view取冻结descriptor_digest并与同一effective resolver核对；run_digests按key排序计算toolset，禁止回到raw contribution hash。
- 旧run drain使用固定run.scope/key、pinned contribution、不可变scope链规则与provider列重算有效配置；不调用要求当前available的新resolve，不因withdrawn/closing改绑；released/epoch/contract/digest错配拒绝。
- model/tool claim保持input与pin形状；非空配置路径响应增加`execution:{descriptor,descriptor_digest}`，实际adapter必须执行该配置。空配置可保留原响应快路径。descriptor必须匹配已冻结摘要与provider授权合同，不能只hash正确但执行raw descriptor。
- listener_call input冻结完整descriptor，摘要与snapshot相等；host收到冻结配置，无需表SELECT。handler_digest/replay沿授权contracts，不允许任意切换adapter。

不新增overlay/intercept来源摘要列；摘要对象只取最终effective descriptor。诊断来源如以后需要另开ABI，本DP不添加第二套摘要，避免与有效摘要漂移。未来若要求在线更新scope规则，须另开版本化设计；不能移除守卫让旧run依赖可变配置。

### 4.3 dispatch生产入口、路由、排序与快照

**Oracle裁定的scope假设：**DP5唯一producer为p4 `fiber.activated`；允许声明其他event，但只是“可注册，无生产者”，明确列ledger。事件范围将来可扩，不冒称全harness覆盖。

`activation_successors(fiber_id)`在reloading且activation_total满足时求值，与DP4 run_start先例相同，不能提前要求本episode数据库已active。以source fiber的scope向祖先路由：同scope其他插件及祖先scope已active/live、未withdrawn/released的listener，加本次即将active episode的listener（用已验证episode_activate虚拟后态）；排除后代/旁支与不live者。不做同名遮蔽。filter对冻结params `{fiber_id,episode_id,epoch}` 求值，按mode分组。

每组总排序：`priority DESC, seq ASC, fiber_id ASC, episode_id ASC, contribution_id ASC`；UUID用PG原生顺序，仅打破跨episode同seq的平局。scope_distance不作为额外priority，保持设计的priority/seq优先。mode组顺序emit/parallel/serial/bail/waterfall。

先保留原run_start 0或1项，再从下一个ordinal编号dispatch，无run_start时从0开始。无匹配listener时p4 delta逐字节保持原值。其他reconcile分支、install/dispose、run/model/tool均不得产生dispatch；validate_domain必须逐字节等于activation_successors，出现非该分支dispatch返回invalid_outcome零写。command路径仍仅三kind，不开放dispatch command。

上限同时验证：全事件筛选后候选≤16、单dispatch≤16、每个dispatch终身child ordinal 0–15、flat successors≤16、**本次实际创建的effect总数≤16**。设r=run_start数、m=dispatch组数、a=本次open及必然同步cascade创建child数，则p4需`r+m+a≤16`。16人parallel加parent已17，必须拒绝；有run_start则18。不得截断、静默跳过或藏nested children绕预算。serial未来child不在本次创建数内，但各次advance同样≤16。超限p4 invalid_outcome、十表零写，不将其转成半激活或无限deferred。

listener集合固定后不随新注册重选；后续失活按§4.6 unavailable处理。空匹配集不生成dispatch，不占run_start槽；纯参考层单独验证空集合的模式identity，不能用fixture伪称生产过零人dispatch。

### 4.4 冻结effect ABI与读取通道

flat successor继续精确`{ordinal,kind,input}`，不加children。dispatch input精确：

```text
{v:1,dispatch_id,event:"fiber.activated",mode,
 params:{fiber_id,episode_id,epoch},bail,listeners:[snapshot...]}
snapshot = {listener_id,contribution_id,provider_fiber_id,
 provider_episode_id,provider_epoch,descriptor_digest,ordinal}
```

serial/bail的bail固定equals(path=["bail"],value=true)；其他null。dispatch_id沿原successor_effect_id(actor,p4_effect,ordinal,"dispatch")确定。snapshot顺序与ordinal一致，不含可变progress。

listener_call input精确：

```text
{v:1,dispatch_id,event,mode,ordinal,listener_id,contribution_id,
 provider_fiber_id,provider_episode_id,provider_epoch,
 descriptor,descriptor_digest,params,acc,
 contract:{contract_version,handler_digest}}
```

acc在waterfall初始为params，其余null；后续waterfall取前一投影。descriptor来自冻结引用指向的不可变overlay后contribution，并须digest相等。snapshot/input长度、key/depth/字节在创建前整体验证，复制descriptor不能绕协议边界；某个较复杂合法listener配置可能因整体冻结input上限使dispatch拒绝，应有明确invalid_outcome与测试，不能承诺任意16复杂descriptor均容纳。

dispatch owner=source fiber/episode；child owner=provider fiber/episode；run_id均NULL。每个child的parent_id严格dispatch.id；child ID和request key由`dispatch.request_actor,dispatch.id,ordinal,"listener_call"`的现有确定性helper产生，绝不用当前child作为下一child parent。request_actor继承source actor；host continuation仍同LOGIN claim_owner。

响应保留emitted全部新effect ID；新增`ready_effects:[{effect_id,kind}]`仅列本次创建且可外部claim的ready effect（不含dispatch、in_db、内部unavailable）。重放必须区分两条既有路径：command request replay逐字节返回最终缓存response（包括原emitted/ready_effects），不重算producer或重发写入；host terminal receipt replay返回disposition=replay且emitted/ready_effects均空，不重新运行listener。不得清空command缓存中的emitted，continuation认证仍依赖它（40 `advance` request replay与`continuation_target_fault`）；旧路径响应保持现有字节。不增加表SELECT、public函数或scanner。手动测试driver维护emitted/ready_effects，丢内存后自动发现属DP6。

### 4.5 原子typed操作、virtual receipt与in_db同步

dispatch是内部aggregate：只ready→succeeded，service/admin/operator不能claim或外部settle；emit在open事务内立即succeeded，其他在必要children完成时封口。内部synthetic outcome外层精确为`{v:1,class,claim:null,body}`；listener success的class="success"，body精确`{kind:"listener_call",result:{value:json}}`；listener failure的class="failure"，body为`{kind:"listener_call",error:{code:text,detail?:object}}`（仅detail可省）；dispatch的class="success"，body精确`{kind:"dispatch",result:<§4.6精确parent result>}`。listener_settle.outcome及applier构造的parent outcome逐层exact-keys校验，缺失/额外键或class配对错误均invalid_outcome。上述内部结果只由可信执行链生成，不是可从advance外部提交的凭据，不能放宽外部success/failure必须claim token的规则。in_db/unavailable child直接可信终态，attempt=fence=0，无lease/claim；fail/invalid_acc/listener_unavailable均为合法failure数据。

新增typed op精确键：

| op | 形状与职责 |
|---|---|
| dispatch_open | `{op,dispatch_id}`；与本delta一个flat dispatch一一对应；展开本次预验证计划，无持久cursor |
| listener_append | `{op,dispatch_id,ordinal,input}`；仅首批集合或精确next项，禁止跳号/重号/跨dispatch |
| listener_settle | `{op,effect_id,source,outcome}`；source仅in_db/unavailable，不代替host receipt |
| dispatch_settle | `{op,dispatch_id,result}`；仅ready parent，可信重算结果，applier构造outcome |

planner把open后的完整append/settle/seal链生成在本次内存delta中；不在JSON列藏第二状态机。每个op仍要结构校验、semantic写集、closure、applier、具名postcondition。dispatch_open不是可独立任意调用的函数，不增加公开执行权。

**执行顺序固定：**在任何业务写前完成完整计划与校验→既有domain op顺序（包括episode_activate）→本次command effect/host receipt→flat successors插入→按计划dispatch_open、listener_append/内部listener_settle拓扑顺序→dispatch_settle→最终postconditions→至多一条簿记event→确定最终response并插入command requests缓存→返回同一response。command effect receipt与requests缓存必须拆开：前者在子行插入前存在以满足parent FK，后者从当前早写位置移到事件阶段与最终响应集合验证之后。emitted合并全部flat successor与listener_append新建ID；ready_effects筛选最终仍ready且可外部claim者。response可从已验证delta预构造，但缓存前必须证明两集合等于实际落库集合，首次返回与requests.response逐字节一致；不得先缓存旧response再返回补充后的response。

当前assert_delta_applied位于event后继之前，只能验证既有op；新增event phase必须在其全部写入后另做完整检查。事务任一点异常全部回滚；不捕获失败后返回成功、部分receipt或部分激活。非事件路径沿原顺序，不能无故调整DP4。

**virtual current receipt：**planner读数据库siblings，再按effect_id用当前合法receipt覆盖本行旧claimed记录；后续本次同步child也加入虚拟表。每行计数一次；joined/acc不含旧claimed版本。validator独立再构造一次虚拟后态，并检查连续前缀、ownership、digest、created数及seal条件。不能因当前receipt尚未落库而漏算最后一人。

in_db exec为预部署纯`IMMUTABLE STRICT BEGIN ATOMIC`算子：const返回value；acc返回输入acc；append要求acc为array则追加value，其他产生内部failure code `invalid_acc`；fail返回内部failure code。params仅供filter及初始waterfall使用，无任意SQL/函数名/动态SQL/RAISE/外呼/读表。每次advance逻辑执行最多16人；planner/validator各求值一轮最多32次，applier只落结果不重算算子；replay前置返回求值0次。同步cascade的创建数预先整体验证，不能中途留下无人驱动in_db ready半链。

### 4.6 五模式、错误、unknown与撤销

可信settled只含succeeded/failed；unknown不计joined。`next_ordinal=coalesce(max(settled.ordinal)+1,0)`；serial/bail/waterfall还要求已结算项为连续前缀，不能用max掩盖缺洞。acc按ordinal fold。success投影`result.value`；failure投影`{error:{code,detail?}}`。

短路仅success且value为object、`value.bail`为JSON boolean true；字符串true、failure、unknown不命中。

| mode | 转换与结果 |
|---|---|
| emit | open生成全部children；in_db同事务求值，host ready独立推进；parent result精确`{v:1,mode:"emit",generated:[listener_id...]}`，不伪写called/joined最终值，不再更新 |
| parallel | open生成全部children，允许host乱序；全部可信终态且无unknown后seal，acc为ordinal有序投影数组 |
| serial | 每次只创建下一项，首bail停止，acc为已结算连续前缀投影数组，含命中项 |
| bail | 同serial短路；acc为首命中value，无命中null |
| waterfall | 下一input.acc取当前投影，失败也作为error值传下去；最终acc为最后投影；不支持“不调用next”控制权 |

非emit parent result精确`{v:1,mode,acc,joined,called:[listener_id...],bailed:boolean}`；called按ordinal列实际执行者，内部unavailable不列called但计joined。failure一般继续；错误不中断整个dispatch；serial/bail只有上述success谓词停。

host receipt body精确：success `{kind:"listener_call",result:{value:json}}`；failure `{kind:"listener_call",error:{code:text,detail?:object}}`；unknown `{kind:"listener_call"}`。外部不得提交in_db receipt、synthetic unavailable、parent outcome或typed ops。error.code是listener数据域，不增加第25个协议错误码。

unknown是合法receipt写入：保存unknown，不event、不续链、不封parent。parallel/emit已有ready sibling仍可claim，已claimed sibling可结算；不把整个dispatch错误地设为全组禁claim。sequential后继冻结，非emit parent不能seal。重放同unknown返回原receipt，不由DP5清除债务。external unknown对账属DP6。

**所有权与屏障：**

- listener不是hard coeffect，不建pin。已创建call按provider ownership参与现有P6 ready/claimed→deferred、unknown→blocked_unknown；允许withdrawn/closing期间按旧快照排空，要求未released、episode未closed、epoch/digest一致、provider未disposed。
- 尚未生成的sequential snapshot项没有provider-owned effect fence；不得谎称现有P6保留了它。若推进时不再active/live或已withdrawn/released，创建该ordinal的内部unavailable failure child（code listener_unavailable），不外呼、不重选provider，继续模式fold。验证时须支持历史行仍存但已released的unavailable分支。
- 非emit parent属于source；若其任何provider-owned child unknown，source P6也必须blocked_unknown，补p6_plan/dispose相关派生查询。否则source只看到ready parent会永久误报普通deferred。emit parent已封口，source可退出；children各自provider fence继续有效。
- logical delete_row仍是withdrawn/released tombstone，保留历史行，非物理DELETE；消费空时P6按seq DESC，其他fiber绑定不变。listener撤销不会给event source增加activation pin。

### 4.7 closure、validator与错误优先级

p4快照读集必须在G下纳入closure，包含source、可见scope链、候选provider install/fiber/episode/contribution，所有新增引用在lock前seed及lock后重读中一致。listener settlement包含当前effect、dispatch、所有已创建siblings、所有snapshot引用、provider installs、owner/scope/pin依赖的实际闭包。不能只按`2+3×16≈50`猜≤64：仅parent+16children+16×(contribution/fiber/episode/install)已81，再加其他依赖。按去重真实集合≤512验证；513零写。历史600effect/source closure不应全部吸进来，只精确parent/siblings和本次引用。

`settlement_seed`只对listener_call扩张；p4另扩reconcile_command_seed对应分支。其他kind保持DP4 W5逐字节种子，保护旧512/513与600历史行测试。lock顺序继续scopes/runs/effects/installs/fibers/episodes/contributions/pins；新增row必须同时在delta_write_closure_ok声明，不能以G替代row closure合同。

独立`validate_event_domain`先逐字节重算event_delta，再独立检查：snapshot可见性/排序/filter/上界；parent/source/provider owner；input exact keys/epoch/descriptor/contract；本次虚拟receipt；每个append连续序号；in_db结果及32求值界；非emit seal基数/acc/called/bailed；emit只generated；四op写集；无runs/pins改动；总created≤16；closure≤512；每advance至多一个event。

对host success/failure的dispatch_progress，validate_event_domain还须独立锁定event.entity_type="effect"、entity_id=当前child.parent_id；payload.dispatch_id等该parent，effect_id/ordinal/mode等当前receipt及冻结input，joined/sealed/bailed等虚拟后态。每次合法host success/failure写一条，unknown为零条；p4继续原activation event。不得只检查payload结构。

`assert_delta_applied`与event-stage final assert分别验证append行全部冻结列、settle终态/outcome精确ABI/attempt/fence、parent exact result、无重复行/额外后继、emitted/ready_effects与实际集合相等。用replace_function注入伪planner及漏op负例，不能只测试正常生成器。

错误优先级沿上游：纯信封错误→角色授权→terminal replay→closure/fence/lease/合同→semantic plan→原子apply。terminal replay不被后来的provider撤销/lease/unknown挡住。dispatch或in_db外部claim为unauthorized；合法host stale attempt/fence/wrong LOGIN按原错误；dependency_unresolved用于不可读取的已创建call；invalid_outcome用于伪造/超限计划。0A000继续仅明确未实现的host_io等seam；数据库SQLSTATE不伪造成新error_v1。

### 4.8 簿记、恢复与同步读禁令

一次advance仍≤1条簿记event，p4保留原activation事件以保持旧流；host settlement采用`dispatch_progress`，payload精确`{dispatch_id,effect_id,ordinal,mode,joined,sealed,bailed}`，entity_type固定为`"effect"`，entity_id=dispatch_id。现有结构validator只要求entity_type为string（40 `validate_delta`），因此新增event semantic validator必须同时锁定该literal、parent ID和payload与虚拟后态的一致性；event_payload_valid新增精确分支。不能为每个同步child无界追加event。

multi-plugin通知由冻结listener snapshot与parent/ordinal child事实证明，不靠bookkeeping events覆盖每个entity。宿主只使用ready_effects驱动host，所有effect包括内部终态仍在emitted审计集合中。

每个receipt、后续child、内部cascade和parent seal同事务；在receipt后/event前后/append后/seal前注入回滚必须恢复十表。parallel两个连接争最后receipt由G串行，只有一人seal。same host receipt replay emitted/ready_effects空；command request replay仍返回原缓存的完整response，两者均不重做写入或in_db求值。冲突receipt按原replay规则拒绝。半程kill/断连接后人工重交claimed receipt或驱动已ready host child，从数据库子行重新派生；无scanner、无自主活性承诺，不冒称G3。

sync_reads:false让非法声明可执行拒绝；in_db闭集无读，不能依赖同步共享状态。host外部共享状态不可由“无表SELECT”证明独立，P7.1/P7.3仍是前提。emit parent只generated，用延迟host child反例证明parent已完成≠child已调用；不能编造const算子写共享cell。waterfall只对acc-chain做参考比较，显式记next控制权偏差。

### 4.9 模块与函数合同

以下为拟新增/改动私有接口；全部SECURITY INVOKER、显式search_path，无public EXECUTE。基础BEGIN ATOMIC依赖必须在调用者前装载：纯merge/声明/effective resolver放41的使用点之前，不把静态依赖放晚装载44。44只承载事件planner，位于43后50前。

| 接口 | 形态/职责 |
|---|---|
| event_policy() | IMMUTABLE→jsonb，统一16 listener/16 created/16 cascade/4 depth数值 |
| listener_decl_valid(item,contracts) | IMMUTABLE→bool，exact八键及exec/contract/sync_reads |
| registration_plan(install_row) | STABLE→jsonb，provides++listeners统一位置/seq |
| descriptor_merge(base,patch) | IMMUTABLE→jsonb，纯merge与语义深度 |
| overlay_apply(manifest,overlay,item) | IMMUTABLE→jsonb或错误值，命名空间与保护字段 |
| intercept_for(scope_id,realm,key) | STABLE→none/reject/replace值，nearest规则 |
| descriptor_effective(scope_id,realm,key,stored) | STABLE→descriptor/digest/contract校验结果，不强求provider当前available |
| activation_successors(fiber_id) | STABLE→原run_start+flat dispatch数组，用虚拟active后态 |
| listener_exec(exec,params,acc) | IMMUTABLE STRICT BEGIN ATOMIC→成功/失败值，四op闭集 |
| listener_call_readable(input) | STABLE→读取许可；区分已创建drain与未创建unavailable |
| dispatch_progress(dispatch_id,virtual_receipts) | STABLE→joined/next/acc/called/bailed派生，不持久化 |
| event_delta(effect_id,outcome) | STABLE→四键delta，含完整有界in_db展开计划 |
| validate_event_domain(effect_id,principal,outcome,delta) | STABLE→error或NULL，逐字节重算+独立不变量 |
| listener_claim_contract(effect_row) | STABLE→host授权合同；in_db/dispatch不对外claim |
| event_apply_postconditions(delta) | 私有验证器，event阶段全部落库后检查四op与响应集合 |

40负责结构路由/applier/ACL；41 install/reconcile/resolve；42 live/teardown/closure及postcondition；43保留DP4run并委托有效配置/seed；44事件算法；50统一撤权。不得新增第四个公开解释器或绕advance的writer。

## 5. File-by-file impact与容量

| 文件 | 预计净增/修改 | 依赖 |
|---|---|---|
| sql/30_triggers.sql | +6–12，冻结scope规则，计DDL前缀 | W1 |
| sql/41_lifecycle.sql | +180–230，基础merge/声明/统一注册/解析/p4路由 | W1–W3 |
| sql/43_loop.sql | +20–40，有效run绑定/digest/claim配置/seed | 先接DP4 W5 |
| sql/44_events.sql | 新+360–440，snapshot/纯exec/progress/planner/validator | W3 |
| sql/40_advance.sql | +180–230，typed op/ACL/响应/事件stage及缓存一致性 | 与事件执行原子 |
| sql/42_teardown.sql | +50–80，closure/op后置/跨owner unknown fence | W1/W3 |
| v24/cordis/load.py | +约1，CANONICAL_ORDER插44于43后50前，self_check 18→19 | W3首次新增44 |
| helper_budget.py | +2–6，HELPERS加44、临时五文件树、保留5500/5501 | 与loader同步 |
| dp1/test_kernel.py、dp2/test_boundaries.py、dp3/test_boundaries.py | 三处manifest/预算布局断言精确更新 | W3 |
| dp4/test_boundaries.py及实际新增边界测试 | 只替换event相关拒绝，保留run/host_io/scanner断言 | W3生产证据同时 |
| dp5/test_listeners.py | 约180–260，CDP5-E | W2 |
| dp5/test_dispatch.py | 约280–400，CDP5-D | W3 |
| dp5/test_resolution.py | 约220–320，CDP5-R及独立参考 | W1/W4 |
| dp5/test_boundaries.py | 约160–240，CDP5-B | W5 |
| dp5/README.md、DP5 matrix/ledger、本文 | 命令/范围/每里程碑Result | 各里程碑更新 |

helper预计净增790–1020行；5500上限相对B0实测4338提供1162行余量，覆盖高估1020后仍余142行，不是“900行即可装下”的承诺。DDL新增后不再声称精确461。不改八领域表DDL或追加列；既有overlay/intercept列足够。新SQL只登记`v24/cordis/load.py`，冻结`v24/load.py`不动，matrix注明本线适用loader，禁止照AGENTS示例去改v8/load.py。

**容量准入（2026-10-28 用户授权重裁）：**用户明确授权把设计§10.1的私有helper总上限从5000修订为5500；设计稿对应行已同步，DP1–DP4历史验收记录不改写。B0在`ba66776`工作树实测40–49合计**4338**（40=1549、41=1197、42=1000、43=592），`R=5500−4338=1162`，保留原`R≥900`的保守预留：R<900不开始W1；R≥900仅准入，每个里程碑仍实际合计≤5500。上限提高的理由是实测4338 + DP5高估1020 = 5358，5500留142行修复余量；它不是删除独立validator、五模式或协议限制的授权。超限仍先消除语义等价重复plumbing，保留独立验证与必要行为；不得缩测试、删模式、压行或移出40–49。若后续实测仍超5500，先回设计§1重裁，不能把该上限当作可自动突破的估计。

**W1 实测（2026-10-28）：**40=1567、41=1354、42=1007、43=668，合计**4596≤5500**，`R=904`；DDL 465≤900；私有函数138；manifest18；十表；唯一DEFINER `advance`、public EXECUTE 0。W1净增258行，R仍≥900，但这只是下一里程碑的准入值，不是W2–W5容量证明。

**W2 实测（2026-10-28）：**40=1589、41=1473、42=1015、43=668，合计**4745≤5500**，`R=755`；DDL 仍 465≤900；私有函数144；manifest18；十表；唯一DEFINER `advance`、public EXECUTE 0。W2净增149行且未新增helper文件/loader项/44。R=755只是W3准入值，不是W3–W5容量证明。

## 6. Gate与verification specification

### 6.1 共用纪律

脚本独立可跑，无pytest、无网络，复用dp1/setup_db.py、dp2/test_support.py、DP4实际交付的dp4_support，不新建角色/数据库helper。同步参考实现放Python测试代码，独立实现sort/filter/exec/fold，不调用event_delta/SQL planner作为答案。

仅**预期被拒绝**的协议调用要求：实际提交尝试、错误码/SQLSTATE匹配、调用前后十表snapshot完全相等。合法failure/unknown本应写receipt，分别断言规定的原子写集；注入回滚才要求整事务snapshot相等。不能套用“一切负结果零写”。需DB owner构造坏事实时标fixture，不冒充生产路径；每项交付至少一次纯生产install→reconcile→event→receipt→P6链。

### 6.2 CDP5-E：test_listeners.py

- E1：旧四键manifest及listeners=[]兼容，无listener的P2/P4 delta字节不变；optional第五键之外未知键拒绝。
- E2：service+listener总数跨32批，seq/next_index/registered_through连续，P4逐项totality；中间改变target产生Divert，不混代注册；空贡献fiber仍active事实。
- E3：listener_id重复、同episode event/id碰撞拒绝；新episode可复用。跨episode快照排序归D11，在W3生产验证。
- E4：伪造realm/key/prev/inverse/contract_version/seq/descriptor、缺项冒P4、额外typed写入，独立validator零写拒绝；listener不占service地址。
- E5：16/17声明边界、非法mode/filter/exec、host缺合同/版本错、in_db版本错、sync_reads缺失/true/非boolean，实际调用零写。
- E6：生产P5 withdraw、P6 LIFO逻辑release和历史listener行保留；不要求W2已能claim/settle。已创建call的withdrawn/closing drain及released拒绝归W3 D6/D10，未生成snapshot项unavailable归D3/D4。
- E7：无listener pin、无run伪装；W2仅以明确标注fixture的既有provider-owned effect验证ready/claimed阻P6、unknown阻P6，不冒充生产dispatch证据。source跨provider unknown派生屏障和emit source退出归W3 D7/D1。

### 6.3 CDP5-D：test_dispatch.py

- D1 emit：跨插件生产全部child，parent只generated，host可延迟执行、parent永不改；source可退出而provider仍被child fence；in_db同advance终态、无claim/lease，重放不再求值。
- D2 parallel：乱序receipt、两个连接竞争最后一人、唯一parent seal；acc/ joined/called精确，虚拟当前receipt不漏计或双计。
- D3 serial：只一个活动next，首JSON true bail停；字符串true不命中，失败继续；prefix缺洞/伪跳号拒绝。尚未生成的snapshot项失活/撤销/released时，生产内部listener_unavailable failure、不外呼、不重选，并继续fold。
- D4 bail：首命中acc为该value，无命中null；called含命中、不含后续、failure与unavailable不触发短路。
- D5 waterfall：初值params、append/acc/const按链传递，failure error对象继续；invalid_acc成为合法failure；最终acc等独立acc-chain参考，明确无next栈。
- D6 篡改parent/provider/episode/epoch/digest/descriptor/contract、外部伪in_db结果、内部synthetic outcome缺失/额外键或class/body不配、注入错误planner/漏postcondition，零写；子ID只依dispatch+ordinal；已创建call的provider已released时dependency_unresolved零写。
- D7 host unknown落receipt、无event/续链/seal；已有ready sibling仍可claim，claimed仍可结算；source/provider fence正确；replay已终态优先于后来撤销。
- D8 receipt后、append后、seal前、event后注入回滚，无部分状态/请求缓存/响应；command request replay逐字节等最终缓存（保留emitted/ready_effects），host receipt replay两数组空，均零求值/零新行且continuation认证不破坏；dispatch_progress的effect literal/parent ID/payload伪造被拒。断连接后人工续驱，使用数据库派生不依内存cursor。
- D9 延迟host的emit同步读反例，证明generated不等called；host共享外部状态仅记录P7.1破防，不声称独立性。
- D10 claim COMMIT后连接IDLE才FakeTool；生产已创建host call在provider withdrawn/closing期间按冻结配置排空；sameLOGIN、旧attempt/fence、不同receipt、reclaim replay双真/双假边界；不真实外呼。
- D11 scope链含祖先同scope/旁支/后代、当前虚拟active和其他active/live；同priority跨episode按seq及UUID确定排序、无run_start ordinal0、空候选不生成；只p4合法producer。
- D12 实际created=16通过/17拒绝，包含parent/run_start/in_db cascade；纯sequential16快照可逐步推进，parallel16+parent必须拒绝；input key/byte预算与closure边界不得用截断通过。

### 6.4 CDP5-R：test_resolution.py

- R1 overlay递归merge、array/scalar/null替换、双命名空间重名、未知目标/保护身份拒绝、语义深度4通过5拒绝；wrapper不计语义深度但协议全体budget不放松。
- R2 intercept近者整体覆盖、reject/none/完整replace、realm先解析、replace descriptor语义深度4通过/5拒绝（wrapper不计）、digest伪造/合同身份漂移拒绝、scope_shape→create→resolve生产路径。
- R3 effective descriptor、check、committed_view、run input/toolset与实际claim execution一致；无配置时DP4摘要和旧路径字节不变。
- R4 provider withdrawn后旧run按pin有效配置排空、released拒绝、新resolve被reject；不能重新resolve改绑。
- R5 纯度：BEGIN ATOMIC/IMMUTABLE、pg_depend传递闭包无pg_class，故意读表探针必须检测到依赖；无dynamic SQL/外呼/RAISE。
- R6 独立Python同步参考逐模式比较acc/joined/实际called（含重复listener_id跨provider的多重集），serial/bail短路一致；emit比较generated、waterfall只比较收窄acc链；空集合identity有单独参考断言。
- R7 P7.1/P7.3和E1–E3前提明确，host只证生成/结算/撤销、无时序等价；sync_reads=false不冒充外部隔离。
- R8 scope规则UPDATE guard实际55000，close墓碑不回退；install overlay不变；新增私有函数ACL无泄漏；provider handler/replay不可通过replace扩大。

W1已交付R1–R4/R8；R5–R7保留W4。R4当前用withdrawn contribution证明旧pin排空，不用retired fiber（DP4 run liveness仍拥有provider关闭语义）。R2的listener命名空间在W1只验证非空目标被拒，W2补声明内成功与同名跨命名空间用例。

### 6.5 CDP5-B：test_boundaries.py

- B1 十表/manifest19/唯一DEFINER/public EXECUTE0/无VIEW或EXTENSION；command仍3、协议错误仍24；dispatch/in_db外部claim拒绝，host listener service允许而admin/operator拒绝。
- B2 全部helper物理行≤5500，临时五文件树恰5500通过5501拒绝，DDL≤900；loader漏44/重复/乱序与budget漏模块均失败。
- B3 有证据替换DP4两event-kind不可claim为“dispatch/in_db不可，host listener可”；保留host_io settlement0A000、无scanner/sweep/recover、run_pin_release_delta只读、DP4run所有断言。
- B4 非event kind seed逐字节等DP4 W5；p4/host settlement实测closure512/513，历史600effects不被无关扫描拖入；读写所有provider/install/sibling被锁。
- B5 manifest16/17 listener、created16/17、snapshot/receipt字节与200key边界、24error闭集；合法failure/unknown是限定写入而非零写。
- B6 全冻结hash、冻结目录diff、git diff --check、private helper纯度、同LOGIN/replay-first和24协议错误保持。
- B7 全旧新脚本逐进程串行exit0，matrix逐项记HEAD/命令/耗时/退出码/证据；无“未跑但应通过”。

### 6.6 命令与回归顺序

所有命令从v99根运行。B0已接收DP4 W5的确切命令索引并展开写入DP5 README/matrix；该31条索引（26旧gate + `CDP4-R/M/T/X/B`）已在当前树逐条独立进程串行实跑，**31/31 exit 0，185.9秒**（见§9 B0-revised）。当前26条旧命令索引在`docs/reviews/cordis-v2-dp4-conformance-matrix-2026-10-27.md:69`；必须s8先s7，不能按目录名自动排序。追加DP4实际五gate（run/reducer/loop/boundaries及其布局门实际入口，以W5清单为准），再运行：

```bash
uv run python v24/cordis/dp5/test_listeners.py
uv run python v24/cordis/dp5/test_dispatch.py
uv run python v24/cordis/dp5/test_resolution.py
uv run python v24/cordis/dp5/test_boundaries.py
```

每个里程碑重跑所有旧stage及本DP已经交付的完整脚本；W1的resolution脚本当时只含已交付R项，后续新增项不得伪装skip为绿。W2运行E中注册/撤销/fixture子集并明确未覆盖项；W3补齐D及跨episode排序、真实drain、snapshot unavailable，随后才宣称E/D事件覆盖完整；W4完成R，W5加入B并全跑。不并行DROP/CREATE同名gate DB，不接管正在开发的DP4测试资源。

冻结核验沿DP4脚本/矩阵十二SQL SHA256；另运行`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12`及`git diff --check`。hash列表引用权威矩阵，不复制一份易漂移清单。

## 7. Risks、tradeoffs与回退

- 可选listeners比新install列轻，保持旧exact四键；provides混装会污染realm地址与唯一性，拒绝。
- p4 activation producer避免model一次16工具slot冲突，又能证明跨插件观察；代价是只覆盖一种事件。scope向祖先和事件集合是Oracle保守scope假设，非用户既定产品决策。
- DB内部dispatch aggregate避免给ready parent引入claimed续延；代价是typed append/seal、virtual receipt、applier阶段和请求缓存必须完整同事务。若无法在容量内保留独立验证则停，不能回nested后继或host驱动in_db。
- 16是创建总数上限，不是承诺每mode均可16人一批；parallel/emit最大实际人数还要减parent、run_start和其他mode组。明确拒绝优于截断，因为截断会改变精化called集合；拆dispatch需要新join语义，非本计划。
- listener无pin；未创建snapshot项可能unavailable，必须可观测且不声称硬依赖保持；已创建child由provider-owned fence排空。source unknown补查不可遗漏。
- scope守卫是行为收紧，owner正常UPDATE将被55000拒绝；只在隔离gate库验证，不直接改DP4正在用的数据库。未来可变scope需版本化。
- 790–1020行估计可能仍不足；900预留准入不是容量证明，5500是用户授权上限而非目标值。预算硬失败优先，不能以删模式/validator满足。
- waterfall next与emit同步完成偏差具名记账；任意host独立性/公平性仍是假设。
- 回退使用追加revert，不reset/force。W1/W2可独立回退相应配置/注册行为；W3之后先停DP5驱动，保留receipt/ledger并识别非终态event，不把含新声明/op的数据库交给旧代码继续跑。未知外部义务不能伪cancel；DP5不提供降级迁移器。

## 8. Oracle裁决与baseline修正记录

Oracle-adjudicated 2026-10-28；两lane均选择A路线。以权威设计和实际代码仲裁lane细节分歧，未把偏好当作用户决定：

| 决策 | 采用与理由 | 置信度/可推翻条件 |
|---|---|---|
| 声明/producer | optional listeners；p4跨可见插件fiber.activated | 工程高；scope/事件集合是保守假设，产品要求别的路由时重裁 |
| parent/typed原子模型 | flat successor+四typed op，in_db同步、虚拟receipt、总created≤16 | 中高；applier/预算不能证明则停，不能弱化同步语义 |
| 五模式/unknown | serial与bail都首success bail停；已有parallel ready sibling继续 | 高；只有权威参考/明确产品要求可改变 |
| 配置/摘要 | overlay双map、intercept完整replace、scope实际守卫、claim传有效配置、DP4摘要shape不变 | 中高；运行中scope更新或adapter不能执行配置须重裁 |
| 容量/阶段 | 900预留准入，硬上限5500（2026-10-28用户授权）；B0实测R=1162通过准入；W2仅注册，W3原子开事件面 | 硬上限高、900充分性低；职责预算实测可调整估计 |
| emit依赖 | 必填sync_reads:false+纯度证明，host独立性仍前提 | 高；任意host隔离证明超DP5 |

lane细节：排序采用设计priority/seq优先再UUID，不加scope_distance业务优先级；overlay固定两个map简化exact shape；replace显式contract_version便于核对独立列；listener priority/filter可配置但handler身份受保护。一lane称30文件冻结，已被实际冻结路径与DP2“不修改”范围反证：30是本线可改文件，scope守卫计DDL，不另建trigger逃预算。scope不能防关闭触发器的superuser。来源digest没有必需消费方，不新增，最终effective hash承担原验证覆盖。

对context_builder生成稿的支持性内容保留；以下为具证据替换，而非删细节：

| baseline问题 | 最终修正与依据 |
|---|---|
| p4只选本episode、单manifest fanout公式 | 跨scope候选+运行时完整created预算；多插件观察见设计§6.6，单声明不能证明跨插件计数 |
| nested children、ID依当前child | flat三键+typed append，parent/ID固定dispatch；符合现有successor exact keys与parent/ordinal唯一 |
| in_db要host claim/settle | 同advance内部结果，符合§6.4同步要求；保留外部token规则 |
| serial不短路、emit伪called | 恢复设计首bail停、emit只generated；保留失败继续和waterfall收窄 |
| 全组unknown禁claim | 允许既有siblings排空，仅冻结后续链/seal，避免扩大未知义务 |
| scopes“已不可变”、raw/effective digest分叉 | 实际守卫+旧pin有效配置+claim execution，同一摘要与配置 |
| descriptor map重名、patch式intercept | 双命名空间；完整replace+摘要/合同校验，贴合替换descriptor digest原文 |
| 猜closure≤64、漏siblings/install | 精确去重读写闭包，至少81再加链；512/513实测 |
| W2发不可消费dispatch、R≥900当充分 | W2只注册，W3全原子；900只是估计准入 |
| 合法failure/unknown也零写、local-only发布 | 分开限定写集/拒绝零写；恢复AGENTS逐里程碑commit+push并先解决目标冲突 |

Phase 6有界审阅见`docs/reviews/v24-cordis-dp5-events-resolution-plan-critique-2026-10-28.md`。四项发现均已落入实施合同：B1拆command effect receipt与末尾requests缓存并区分两种重放；B2将排序/unavailable/真实drain移入W3 D，W2 E不依赖事件planner；B3锁定event entity与虚拟后态；B4恢复内部listener/dispatch outcome的exact ABI。最终保真检查另补齐intercept replace descriptor深度4/5覆盖；未重开六项Oracle路线。

## 9. Implementation order与收尾纪律

### B0 — 交接、容量与发布目标

Goal/Done when/Key files/Dependencies/Size见§3。先只读确认DP4 W5已交付，获取实际HEAD、branch/upstream、用户工作区路径清单、冻结hash、所有脚本与符号、helper/DDL实际行数。按5500上限先算R，再决定能否变更；R<900或DP4未完成时不创建空44、不改loader、不提交“基线完成”。2026-10-28用户授权重裁后，本节保留原始blocked Result作为历史；重裁结果见下方B0-revised，并已在该树实际执行。不把未完成工作当完成。

发布目标未明确时，只读核证可继续；在任何需里程碑commit+push的变更前停，等用户明确v24分支对应远程目标。不得照抄main push、不得把旧DP4 local-only作为本次授权。本计划不在Oracle模式中打断用户，阻断在交接处明示。

准入后B0建立DP5 README/matrix/ledger与完整命令索引，重跑全部旧gate，记录真实Result。不提前登记空44；44首次随W3可用实现登记。

**Result（2026-10-28，blocked at capacity admission）：**在 worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`、分支 `v24`、upstream `origin/v24`、HEAD `f11942938243d7108d218d6c45c2b01e240f5214` 上完成只读核证。`git fetch origin` 后 `origin/v24...HEAD` 为 `0 7`（0 behind / 7 ahead），7 个提交是 DP4 B0→W5（`17c855d`、`e8b6cce`、`8cbc5f3`、`dbd943d`、`faccab4`、`348b9b8`）加 W5 验收补正 `f119429`；DP4 README/matrix/ledger 与五个 DP4 gate 脚本均在 HEAD，W5 的 31 条命令记录为 147.0 秒绿。31 条继承命令（26 旧 gate + `CDP4-R/M/T/X/B`）于当前树逐条独立进程串行重跑，**31/31 exit 0**，总耗时 184 秒，s8 先于 s7；日志 `/tmp/dp5-b0-gates.log`。

实测 helper：40=1549、41=1211、42=1000、43=560，合计 **4320≤5000**，故 **R=680**；DDL 前缀 **461≤900**，manifest 18，十表，唯一 `SECURITY DEFINER` 仍为 `advance`，public EXECUTE 0。**R=680<900，准入不通过**；且本计划估计 DP5 净增 790–1020，低端也超过 680。按 §5/§9-B0，未创建 `44_events.sql`、未改 `v24/cordis/load.py`、未改 `helper_budget.py`、未开始 W1；不把 B0 记为“基线完成”。十二份冻结 `v24/sql` SHA-256 全部匹配 DP4 矩阵，`git diff --exit-code 57e2c1e -- v24/load.py v24/sql ... v24/s12` 与 `git diff --check` 均 exit 0。

已建立 `v24/cordis/dp5/README.md`、`docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md`、`docs/reviews/cordis-v2-dp5-deviation-ledger-2026-10-28.md`，矩阵含 31 条命令索引、helper 符号与工作区快照。发布目标冲突未解：`AGENTS.md` 指向 `origin main`，实际分支 `v24` 跟踪 `origin/v24`；DP4 的 local-only 裁决不构成本次授权。因容量 gate 失败且目标未明，B0 未 commit、未 push，工件留在工作区待审。W1 准入无效；下一步只能先做语义等价去重并复测 R，仍不足则回设计 §1 重裁。

**B0 后续只读容量审计（2026-10-28）：**另派一位独立 pair agent 检查实际 40–49 helper 去重可行性；未修改实现、测试、loader 或数据库，也未重跑 gate。该审计估计可保持语义的 plumbing 去重约 85–115 行（乐观约 120），主要候选是 delta envelope 构造、lineage/scope walker、iterator predicate 等；这只是静态估计，尚无实现或实跑证明。即使按 120 行计算，R 也仅约 800，仍低于 900 准入。独立 validator、postcondition、冻结 input 校验不得作为删减对象。该 5000 口径下的结论已被下方 5500 重裁取代；41 的 `fiber_chain` 去重只回收 14 行，不是本次准入的关键。发布目标确认仍待用户答复。

**B0-revised（2026-10-28，capacity admission passed）：**在 worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`、分支 `v24`、HEAD `ba66776cab82d05cbd1a0ef97bb27f5e1895378f` 上完成；`git fetch origin` 后 `origin/v24` 仍为 `4b34bf2`，`origin/v24...HEAD` 为 `0 9`（0 behind / 9 ahead）。DP4 交付链为 `17c855d`→`e8b6cce`→`8cbc5f3`→`dbd943d`→`faccab4`→`348b9b8`→`f119429`→`73973d1`→`ba66776`；后两个提交分别是 W5 后的 settlement validation 加固与可读性拆分。`43_loop.sql` 为 **592** 行、25 个私有函数，工作树对该文件无未提交 diff，`CDP4-T/X/B` 全绿，故按“当前 43_loop 稳定”接收。用户未提交的 41 去重重构用 `fiber_chain` 共享递归 walker 替代四个 PL/pgSQL walker，把 41 从 1211 降到 1197；正常/环/512 溢出路径由 CDP2/CDP3 gate 覆盖，缺失 owner 由 `fibers_owner_id_fkey` 拒绝，未发现可生产触达的语义漂移。`helper_budget.py` 的 `LIMIT=5500` 由 CDP1-K0 在临时树上实跑 5500 通过/5501 拒绝。31 条继承命令逐条独立进程串行重跑，**31/31 exit 0**，总耗时 **185.9 秒**，s8 先于 s7；日志 `/tmp/dp5-b0-readjudication/gates.log`、逐条 `/tmp/dp5-b0-readjudication/gates.tsv`。helper 实测 40=1549、41=1197、42=1000、43=592，合计 **4338≤5500**，`R=5500−4338=1162≥900`；DDL **461≤900**，manifest 18，十表，唯一 `SECURITY DEFINER` 为 `advance`，public EXECUTE 0；十二份冻结 `v24/sql` SHA-256 与 `57e2c1e` frozen diff、`git diff --check` 均不变。未创建 `44_events.sql`，未改 `v24/cordis/load.py`（18 entries），未开始 W1，未 commit、未 push。发布目标仍未解决：`origin/v24` 停在 `4b34bf2`，AGENTS 指向 `origin main`；本 B0 不自行选择目标，留给 orchestration。

### W1 — overlay/intercept与有效执行配置

在41前置基础纯函数，原子修改40形状/生产者、41解析与所有fail-closed、42 live、43摘要/claim、30scope守卫，加入R1–R4/R8。证明无配置legacy、旧pin drain和实际adapter配置。重跑完整旧stage，工件回填再独立提交推送。

**Result（2026-10-28，implemented, verified and locally committed）：**在 worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`、分支 `v24`、HEAD `ba66776` 上完成 W1，未新建 `44_events.sql`，未改 `v24/cordis/load.py`（18 entries）或 `helper_budget.py` 的 5500 上限，未实现 listener 注册或 dispatch producer。

实现：

- `41_lifecycle.sql` 新增 `descriptor_depth`/`descriptor_merge`/`descriptor_patch_ok`/`overlay_apply`/`install_overlay_valid`/`scope_intercept_valid`/`intercept_for`/`descriptor_effective`；`manifest_shape_valid`/`scope_shape_valid`/`install_payload_valid`/`install_admission`/`install_delta`/`validate_install_domain`/`resolve`/`activation_admission`/`activation_bindings`/`activation_total`/`interpret_reconcile`/`service_realm` 改为有效描述符与合法非空配置；删除旧的 `scope_intercepted` 全线拦截。
- `40_advance.sql` 的 `scope_create` 可选 `intercept`、`install_create` 合法 overlay、P1/P2 独立验证、scope applier 与 claim `execution` 通道；`42_teardown.sql` 的 `assert_delta_applied`/`scope_live_fault`/`live_node_fault`/`fiber_live_state` 改为 effective descriptor；`43_loop.sql` 的 `run_bindings`/`run_digests`/`run_successor_binding`/`run_settle_facts` 使用冻结 `descriptor_digest` 与同一 effective resolver，新增 `run_binding_desc`/`claim_execution`，model/tool claim 在非空配置下返回 `execution:{descriptor,descriptor_digest}`，空配置保持 DP4 响应字节。
- `30_triggers.sql` 新增 `realm_overrides`/`intercept` UPDATE 冻结守卫（55000），保留 id/parent/close 墓碑规则。

测试：`v24/cordis/dp5/test_resolution.py` 交付 R1、R2、R3、R3b（无配置字节对照）、R4、R8；R5–R7 属 W4，未在本里程碑冒充。R1 覆盖递归 merge、array/scalar/null 替换、双命名空间、未知目标、保护身份、语义深度 4/5、协议 200 键边界；R2 覆盖 nearest replace/reject、realm 先解析、无回落、完整 replace、digest/contract/depth 拒绝、1–16 规则与生产 scope_create→resolve；R3 覆盖 check/committed_view/run input/toolset/claim execution 一致、provider contract 不被 replace 扩大；R4 覆盖 withdrawn 旧 pin 排空、新 resolve 不可用、frozen contract/digest 错配与 released 拒绝且不改绑；R8 覆盖 scope 规则 55000、close 墓碑、install overlay 不变与新增私有函数 ACL。

实跑：W1 脚本单独 exit 0；31 条继承命令逐条独立进程串行重跑后再跑 `CDP5-R`，**32/32 exit 0，总耗时 155 秒**（逐条 `/tmp/dp5-w1/gates.tsv`、分命令 `/tmp/dp5-w1/gate-01..32.log`）。helper 实测 40=1567、41=1354、42=1007、43=668，合计 **4596≤5500**，`R=5500−4596=904`；DDL 前缀 **465≤900**，manifest 18，十表，私有函数 **138**，唯一 `SECURITY DEFINER` 为 `advance`，public EXECUTE 0。十二份冻结 `v24/sql` SHA-256、`v24/load.py` 与 `v24/s1`–`s12` 未变。

边界：W1 的 listeners overlay 命名空间被形状接受但非空目标仍拒绝，因为 W2 才有 listener 声明；W2 已替换为声明内校验并补跨命名空间同名用例（见 W2 Result）。R4 用 withdrawn contribution（不是 retired fiber）证明旧 pin 排空，因为 DP4 的 run liveness 仍拥有 provider-fiber 关闭语义。发布目标仍未由用户点名：W1 只做本地提交，不 push、不推断 `origin/main` 或 `origin/v24`。

### W2 — listener注册与撤销

交付八键listeners、registration_plan、跨32批iterator、P4 totality、delete_row撤销与E注册子集。此阶段仍拒dispatch/listener外部执行，不产生生产dispatch；针对既有provider-owned effect的P6屏障测试可fixture构造，明确不执行listener claim/settlement、不是事件producer或drain生产证据；跨episode排序、snapshot unavailable和真实drain都在W3 D交付。完整旧gate及当时E注册子集全绿后更新工件并提交推送；跨episode排序、真实drain与未生成unavailable保留到W3 D，不得以skip冒充通过。

**Result（2026-10-28，implemented, verified and locally committed）：**在 worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`、分支 `v24`、HEAD `c3ddd94` 上完成 W2；未新建 `44_events.sql`，未改 `v24/cordis/load.py`（18 entries）或 `helper_budget.py`，未实现 dispatch producer、listener_call 执行、host receipt 或 event planner。

实现：`41_lifecycle.sql` 新增 `listener_exec_valid`/`listener_desc_shape`/`listener_desc_valid`/`listener_decl_valid`/`listener_patch_ok`/`registration_plan`；`manifest_shape_valid` 接受可选 `listeners` 第五键（0–16，精确八键，`listener_id` 内唯一，host 合同/版本、in_db 版本、`sync_reads=false`）；`overlay_apply`/`install_overlay_valid` 改为声明内 listener overlay 校验（仅 priority/filter、保护身份）；`activation_total` 与 `interpret_reconcile` 的 P2/P4 改为统一 `registration_plan`，跨32项 iterator/seq/registered_through 连续。`40_advance.sql` 的 `contribution_append` 结构校验允许 listener（realm/key/prev NULL、`delete_row`、每批 service+listener≤32），P2/P4 独立 validator 逐项重算 plan。`42_teardown.sql` 的 P2/P4 诊断同样使用 plan；P5 `withdraw_ids` 与 P6 listener inverse 沿用既有生产路径。

测试：`v24/cordis/dp5/test_listeners.py` 交付 E1–E7 注册/撤销子集：legacy/listeners=[] 兼容、双命名空间 overlay、跨32批与 target Divert、重复/碰撞/新episode复用、构造 delta 零写拒绝、16/17 与非法声明边界、生产 P5/P6 LIFO release、无 listener pin/run 与 fixture P6 barrier。E1–E7 不声称跨episode排序、未生成 unavailable 或真实 drain；这些是 W3 D 证据。E7 的 ready/claimed/unknown effect 明确标为 owner fixture。

实跑：31条继承命令逐条独立进程串行重跑后跑 `CDP5-R`/`CDP5-E`，**33/33 exit 0**（167 秒；逐条 `/tmp/dp5-w2-final2/gates.tsv`、分命令 `/tmp/dp5-w2-final2/gate-01..33.log`）。helper 实测 40=1589、41=1473、42=1015、43=668，合计 **4745≤5500**，`R=755`；DDL 465≤900，manifest 18，十表，私有函数 144，唯一 `SECURITY DEFINER` 为 `advance`，public EXECUTE 0。十二份冻结 `v24/sql` SHA-256、`v24/load.py` 与 `v24/s1`–`s12` 未变。

边界：W2 只做注册/撤销；dispatch producer、listener_call 执行、宿主机 receipt、event planner 与 `44_events.sql` 均未启动。发布目标仍未由用户点名：W2 只做本地提交，不 push、不推断 `origin/main` 或 `origin/v24`。

### W3 — 生产与执行原子闭环

增加44并同步loader19、HELPERS五文件、三处manifest gate；一次交付p4producer/快照/closure、四typed op/virtual receipt、in_db cascade、host claim/receipt、ready_effects/execution通道、父子ID、请求response缓存一致性、source/provider fence、全部validator与postcondition及D。仅此时以证据替换旧“listener不可claim”，dispatch/in_db仍不可claim。重跑全部旧gate与已交付E/D/R、预算和冻结，再收尾工件commit+push。

Result：未执行。

### W4 — refinement与偏差

独立Python同步参考验证五mode对应观察、纯度依赖闭包/读表探针、host条件性证明、emit与waterfall具名偏差；补混代激活回归和无配置DP4摘要证据。R全绿及全旧stage通过后工件/独立commit+push。

Result：未执行。

### W5 — 全量验收

B加全部旧新命令串行实跑，十二hash和冻结diff、helper实际行数、DDL、manifest19、十表/1DEFINER、ACL、无scanner/网络全部记录。README/matrix/ledger/本文Result逐项覆盖；保留未认领的DP6与G4其余项。不能要求用户所有工作区干净，只要求暂存区仅本里程碑确定路径。

Result：未执行。

**每里程碑工件：**`v24/cordis/dp5/README.md`；`docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md`；`docs/reviews/cordis-v2-dp5-deviation-ledger-2026-10-28.md`；本文Result；新增SQL时loader/budget同步。矩阵写Scope/Environment/HEAD/冻结hash/Capacity/每命令exit与Evidence/未覆盖，台账列Baseline/DP treatment/Evidence与Final unclaimed scope。

**提交发布顺序：**实际全绿→工件→`git status`→按精确路径`git add <paths>`→`git status`与staged diff确认→`git commit -m "v24: <祈使句摘要>"`→已核准目标的普通push。严禁add -A/add .、--no-verify、force/force-with-lease、reset --hard，疑似凭据文件打开确认且不提交。push拒绝先fetch看差异，安全时rebase后再推；不能安全合并就停，不越过失败继续下一里程碑。

## 10. References、保真索引与hand-off

所有引用均为v99内路径；source行号是规划快照，执行时重定位符号。

- `docs/designs/cordis-plugin-system-2026-10-25.md:427`：三件套/五mode；`:451`：intercept；`:603`：refinement与偏差；`:619`：overlay；`:724`：预算；`:754`：G4；`:787`：半程恢复；`:810`：债务/非目标。
- `docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:206`：DP分工；DP2 plan `:661`/`:694`：多实体通知边界；DP3 plan `:184`：listener fixture证明边界。
- `docs/plans/v24-cordis-dp4-run-settlement-plan-2026-10-27.md:29`：接口接缝；`:74`：planner/claim/seed先例；`:277`：历史裁决；`:294`：测试；`:348`：预算/收尾。
- `docs/reviews/cordis-v2-dp4-conformance-matrix-2026-10-27.md:69`：26条旧命令与顺序；DP4 W5完成后以其实际完整清单更新交接索引。
- `v24/cordis/sql/14_contributions.sql:22`、`15_pins.sql:11`、`17_effects.sql:16`、`30_triggers.sql:75`/`:96`、`42_teardown.sql:684`；40/41/43按§2接缝符号定位。
- `v24/cordis/load.py:6`、`v24/cordis/helper_budget.py:11`、`AGENTS.md`。
- `docs/reviews/v24-cordis-dp5-events-resolution-plan-critique-2026-10-28.md`：一次有界完整性/设计审阅，B1–B4已按§8处理。

### 10.1 context_builder覆盖ledger与最终落点

| 基线内容 | 保留/修正位置 |
|---|---|
| Summary/Goal/Done when/非目标、当前DP4状态与4216预算 | §1、§2、§5，历史观察与交付区分 |
| 逐接缝现状、端到端链路 | §2.2、§3；保留scope/install硬编码与live拒绝点 |
| listener声明、contract、filter、唯一性、统一seq/iterator/totality | §4.1；sync_reads与producer预算见§4.3 |
| merge/overlay/intercept/深度/身份/摘要/run drain | §4.2；修正作用树、完整replace、scope守卫与实际配置 |
| p4producer/排序/快照/两effect ABI/claim/parent状态 | §4.3–4.5；nested改typed，覆盖验证不丢失 |
| 五模式、failure、unknown、withdraw、epoch/digest | §4.6；修正serial与unknown，新增unavailable/source fence |
| 崩溃/replay/并发/emit独立children | §4.5–4.8；command缓存重放与host receipt重放分开；不冒称scanner恢复 |
| planner函数/独立validator/closure/后置/事件payload | §4.5、§4.7–4.9；内部outcome exact ABI、事件entity/虚拟后态、精确集合与final postcondition |
| emit同步读禁令/纯度/refinement前提 | §4.8、R5–R7、§7 |
| file impact/预算估计/loader19/五文件边界 | §5、B2、W3 |
| E1–E7/D1–D10/R1–R7/B1–B7全部验证 | §6，修正无效零写期望并增加D11–D12/R8；跨episode排序与未创建unavailable从E移D，保留覆盖且W2不依赖W3 |
| tradeoffs/回退/实现顺序与每项五字段 | §3、§7、§9 |
| 六项开放决策及替代方案/理由 | §8，均经Oracle裁定，scope/900标假设 |
| 探查证据、旧gate替换与工件/发布纪律 | §2、§6.5–6.6、§9、References |

保真检查完成（2026-10-28）：逐项对照上述ledger与完整baseline生成正文，保留或具证据修正全部适用实施内容；审阅B1–B4已纳入，未把本计划核对当作数据库gate通过。规划中间export可清理，本文与审阅工件留存。

### 10.2 保留开放项与后续工作流

没有留给实现者临场选择的核心算法问题。以下是显式交接条件：DP4 HEAD `ba66776` 的实际接口与31条gate已由B0接收；5500/900准入已在`R=1162`实测通过；用户核准的远程/分支目标仍未解决，发布留给orchestration。scope向祖先路由与仅fiber.activated producer是可被用户覆盖的Oracle保守假设。任何新证据推翻已裁决合同，先更新计划/预算/测试，不能在实现中悄悄扩大或缩减。

推荐下一步`rp-build`按B0开始；若使用`rp-orchestrate`，共享40–43与同名gate DB的实现/测试仍串行，不能把四typed op与producer拆成独立不完整里程碑。本文仅完成计划，所有Result均未执行。
