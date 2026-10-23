# v24 独立 Oracle 批判 brief

> 日期：2026-10-22；自包含设计压缩，不是实现报告。
> 主文：`docs/designs/v24-db-native-agent-system-2026-10-22.md`（§0–§22）。
> [仅规格] v24 是工作名，全部新机制待实现；本轮未跑 gate、未改代码、未提交。
> 请找反例与承重漏洞，不把方案补成另一套系统后再评价。

## 1. 命题与证据边界

[第一性推导] 新系统必须同时承载可靠 agent loop、代理管理代理和 Cordis 插件生命周期。
DB 决定资格、授权、身份、结果与责任；外部 IO 在事务外。
策略可由人、规则或 agent 提供，执行资格不能随策略更换而旁路。

[已实现] v99 Phase0 有六动词、claim/pin、单 claimed、唯一 T2、receipt replay、unknown、ACL；仅 Fake。
当前 simulated spawn 不创建 child；v99 插件面、zcordis fiber/recovery 重设计均不能当成现成功能。
[已实现] Cordis database Driver.init 展示 inject model、start、逐步 provide、逆序 dispose。
[第一性推导] 这要求持久获取/恢复责任，却不能证明 stop 能撤销已经发生的业务写入。

[仅规格] 主文吸收 prior Oracle 五条：双账本、身份阶梯、六动词/fiber 边界、锁序/真实 caller、活性 owner。
它修正三种过强读法：串行化不证明 independence；episode 不等于 run；混合补偿等级表不是组合定理。

## 2. 细腰与本体

[仅规格] 细腰是 typed EffectEnvelope 与 `admit→claim→execute→accept/advance` 协议。
信封固定 effect/operation、执行域、目标 handle、输入、权限来源、披露合同。
普通 IO、spawn child、管理插件均使用同一 qualification/claim/receipt，不另建调度器。

[仅规格] 五层：纯效应代数；fiber/恢复语义运行时；T1/T2 执行基质；manifest/grant 打包治理；role/workflow 策略。
语义层不直接 IO；基质经固定 kind 调解释器，不接插件任意 SQL callback。
workflow/notify/cleanup 分类只有 work_item 索引，没有第二 claim/lease。
普通 run 可无 fiber；内建 bootstrap 与维护服务不依赖待激活插件。

[仅规格] 身份：install→组件 fiber→一次激活 episode；任务另有 run→epoch→turn→operation→effect→attempt。
runtime 是 OS 实例身份。一个 episode 可服务多个 run；一 fiber 至多一个 OPEN episode。
turn 严格是一次 effect 加一次 advance；model→两个 tool→model 是四步，不能藏成一次外部原子效果。
一个 persistent runtime 可服务多个 run，但 invocation 唯一约束使它至多一个在途调用；没有第二 runtime lease。

[仅规格] scope_revision 管配置，resolution_revision 管路由，generation 管发布权，run_revision 管快照。
driver/effect fence 管执行授权，runtime_epoch 管实例；这些时钟不相互替代。
attempt pin 包含 provider episode、binding version、schema、artifact、grant revision。

## 3. 两账、数据与事务

[仅规格] 同库分 v24_exec/v24_sem/v24_gov schema；用 effect_id 连接两账，用 commit_bundle 标识原子关联。
执行账：attempt/pin、receipt、execution_events、request response；语义账：contract、semantic_events、inverse/range、evidence/residue。
不是两个独立裁决同一事实的真相源；不能从一账猜造另一账丢失的事实。

[仅规格] 核心键：runs(run_id)、epochs(epoch_id)、turns(turn_id)、operations(operation_id)、effects(effect_id)。
receipts(effect_id) UNIQUE；turn.advanced_bundle_id 至多一次；一 run partial UNIQUE claimed。
requests(principal_id,request_id) 保存完整 canonical input 与首响应，不仅比较 digest。
纤维表：fibers、episodes、committed_views(episode,key)、provisions(realm,key)、binding_versions、bindings。
恢复表：effect_contracts(effect_id)、recovery_ranges、recovery_items(range,ordinal)、consumptions(range,ordinal)。
治理/控制表：principals、grants、roles、workflow_bindings、delegations、budget_accounts/entries、transitions、resource_refs。

[仅规格] admission 同事务创建 effect+contract+turn+prepared 事实；T1 追加唯一 attempt/pin，再 COMMIT。
确认提交且控制连接 IDLE 后才 host IO；COMMIT 应答丢失先查原 request。
T2 原子接纳 receipt、写两账 outcome、预算结算、advance、有限后继、snapshot/wake、request journal。
DB domain 则在 DB interpreter 的执行/T2 同事务施加真实变更与捕获旧值；不做外部 IO。
DB 回滚可重试相同解释；host 投递不适用此规则。

[仅规格] host effect 只签发一次投递资格；外部至多一次条件于受信adapter不重投，不保证provider内部次数；DB强制接纳至多一次。
租约到期不重投，幂等key/只读标签不自动授权重试。
确定未执行后的新尝试是显式 successor effect，引用旧 effect/证据并重新预算。
receipt 已提交则原参数 replay；未提交且原结果保留、原 fence 仍合法则重交 T2，不重 IO。
旧 generation 可记结果和成本，不得生成业务 successor/interaction/final；资源责任仍保留。

[仅规格] run 状态：running/waiting_for_input/completed/failed/cancelled/blocked_unknown。
effect 状态：ready/claimed/succeeded/failed/unknown/cancelled；failed 不能掩盖可能部分外部成功。
takeover 将旧 claimed→unknown；业务墙挡本 run 新业务，只允许观察、cancel 与精确维护。
首版无业务 unknown resume；晚到证据只追加，不改旧结果或复活旧 fence。

[仅规格] final 写 closeout_intent；无业务未知、交互、在途工作、attached child、所属资源责任才正常 close。
cancel seal 可先终结业务但列未结算/unknown/child/资源；后续 cleanup 不改原 seal/snapshot/wake。
wake 持久，NOTIFY 可丢；wait 短读、事务外等待、LISTEN 后复查、超时再读，独立 cursor。

## 4. 承重不变量与统一控制边界

[仅规格] I01–I04：受支持写入均有 operation/effect；T1 确认后 IO；单 claimed；单 receipt/advance。
[仅规格] I05–I08：业务 unknown 不续链；旧代不发布；fiber 只经 fiber_control；DB 逆与消费同提交。
[仅规格] I09–I12：身份从认证/派生凭证获得；cancel不擦责任；episode provider/value固定；维护项有owner/debt。
start无expected_revision；cancel/steer/respond需匹配锁后revision，respond还匹配interaction；精确replay先于版本检查。

| 动词 | CE、fiber 与 role/workflow 的统一边界 [仅规格] |
|---|---|
| start | 创建 run/epoch、固定配置角色预算；冷 runtime 先 start effect；插件实例化另经 fiber_control |
| poll | 授权只读；不 claim、修复、flush 或推进 workflow |
| wait | 事务外等 wake；parent wait 不自动 steer/respond child，不驱动 lifecycle |
| cancel | 禁新业务、撤 fence、关 ready、seal；不能直接 inactive fiber 或清 unknown；可准入 retire |
| steer | 新 generation；同 epoch pin 不变，旧 claimed 可结算不续链；不能换 provider/代答审批 |
| respond | 仅精确当前 interaction/responder；内部 human 原子结算；不能自行批准 grant 或改 fiber |

[仅规格] run/epoch/generation 只由 CE operation/advance 改；fiber/episode/view/provision/binding/route 由 fiber_control 改。
recovery effect 可施加已登记逆并消费范围；episode close 仍由最后 fiber_control 核验。
governance effect 改 manifest/install/grant/scope desired config，不直接提交 active。
OS 事实由无 DB 凭据 supervisor 出证，经 runtime_control 接纳；DB 不由 PID/超时猜死亡。

## 5. 代理控制代理

[仅规格] agent 的控制意图先成为 agent_control DB effect，再在 T2 应用目标 CE operation。
真实 source 来自 DB delegation 与 source attempt；transport 同时审计 executor/source，不信 JSON actor。
角色是版本化工具/verb/输出上限；workflow node 是准入前提与 join policy，不拥有执行 lease。

[仅规格] spawn T2 验祖先 cancel 域、depth/fanout、role/workflow、grant/quota，原子建 child/handle、划转 escrow。
UNIQUE(parent,spawn_key) 绑定 canonical input（角色/workflow版本、scope、完整输入、额度；排除request_id，编码版本入digest）。
requests 与 child birth record（parent-child edge）存规范字节/digest、parent/key/child/source effect；同digest及字节才返回同child，否则 `spawn_key_conflict`，不建child/重复划转。
父不等child；权限=父委派∩角色∩workflow∩grant；parent也需verb授权，无默认祖先/孙辈/兄弟权，respond另验responder。

[仅规格] handoff固定transcript水位/摘要；无claimed/unknown才可独占转移，目标/收据与源fence同提交，谱系不改、另记edge。
unknown仅材料交接；observe只读，await/join是operation、wake后重验；escalation有owner/deadline，沉默不批准/skip。

[仅规格] T1前预留、T2可信usage结算；unknown不退预算，维护有界池耗尽升级；provider无硬cap只承诺本地准入上限。
cancel先提交祖先域，spawn/claim/后继检查，后代seal/fence分批effect展开；未展开child也禁新业务，在途IO未必停止。

## 6. Cordis 与恢复

[仅规格] fiber 四态 inactive/reloading/active/unloading，另有 retired、单调 fault；episode OPEN/CLOSED 与 outcome 分离。
十规则：Insert 预留且 inactive；Retire 建子树域；Remove 需无子/OPEN/引用/范围；Begin 冻结 view 并 reloading。
Iter 一步落地及捕获逆；Finish active+success 但 episode OPEN；Divert 失配转 unloading。
Raise 先转unloading，固定pending error；恢复后匹配finalize才fault/error/FAILED close，不能普通Unload吞错；Leave撤可见性。
Unload全守卫满足才close；Raise分步不继承原证明，外部恢复每子步也是effect。
[仅规格] runtime_invocations(attempt_id PK,runtime_id,provider_episode_id,run_id,effect_id,state)；state=claimed/settled/unknown，partial UNIQUE(runtime_id)覆盖claimed/unknown，不增lease。
T1写invocation、T2置settled、takeover/隔离置unknown；G及既定锁序下close扫描E关联的所有run，存在claimed则拒绝或留unloading，unknown资源义务未清也不卸载；单run结束不得删invocation。

[仅规格] provisions 保证同 realm/key 单声明源；binding version 不可变；committed view 按值域判断 relied。
父子support edge使父卸载先退役子并等贡献/责任清偿；notify覆盖binding/active/retired/route/新空inject，先satisfaction后drift。
marker消费与候选admission同提交，执行live重验，高revision不被旧消费覆盖。

[仅规格] R=受控精确恢复，C=补偿谓词，A=对账/残留，O=拒托管；网络/LLM默认A。
L_eff=版本化REG/UNREG/owned SET/snapshot GET/typed EMIT；R需独占写/不可变快照读，否则登记episode依赖，共享读也加边。
仅LIFO/依赖逆序；G不证明independence，R/C/A等级不构成组合定理；任意语言仍受信。
observer有限测试不证全部观测等价，witness正确性由作者负责。

[仅规格] range 冻结终点，逆本身为新 effect；DB 逆检查 expected version、改值、消费同 T2。
外部补偿 unknown 不重发；新 inspect 可解资源责任，不能洗白业务 unknown。
closure 标exact/compensated/residual；residual需scope manager接管，保留责任/未证停live refs，不豁免dispose/Remove，不授权业务resume。

## 7. 插件治理与升级

[仅规格] manifest 固定 entry agent/tool/service、schema、依赖、能力；service 是数据/异步 handle，不是旁路 IO。
install effect 预留 install/reservation；T1 后验包/CAS，receipt 后 installed；不直接 active。
approval 固定 manifest/artifact/adapter；模型只能申请，不能自己批准；子 scope 权限求交。
grant revoke 挡新 admission/claim，已投递结果仍允许记账，不据此准入未授权后继。
dispose 先检查 live refs/义务、reserve，host 事务外释放该 install 一份 CAS 引用，再 confirm。
agent 的 plugin verbs 都走相同 effect/审批面；agent run 可无 fiber，agent 插件可提供多个任务 run。

[仅规格] 升级新旧 provider 分别在 private realm，public key 仅一个 broker owner，守单源纪律。
consumer view 固定 broker route 与实际 provider episode/version，不能只固定 broker 身份。
transition：prepared→warming→cutover→draining→done，另 blocked/aborted；首版原子切换，无百分比流量。
cutover 是 fiber_control，route+revision+事件同提交；旧 episode 继续旧 handle，退出后重激活。
回退是新 route revision，不撤销新 provider 已做 emission；有状态迁移未闭合。

## 8. 锁、真实 caller 与恢复窗口

[仅规格] 所有 mutation：认证→事务级排他 G→request/replay→scope→root→排序 runs→epochs→operations→effects→fibers/episodes→binding keys→runtimes→budgets/refs/ranges→两账/journal→提交。
内部不嵌套公共 API/新 request lock；跨 run 先定对象集，扩大则回滚重规划；不握 G 等 IO/依赖。
G 仅换取首版并发可审查性；拆闸是开放问题。挂死事务的锁不随 lease 到期释放。
session_user name+OID→principal；SET ROLE 不换身份；GUC/自报 issuer/current_user 不认证。
PUBLIC/default EXECUTE 撤权；插件无核表 DML；DBA/host/adapter 仍受信。

[仅规格] 必须正确覆盖的窗口及默认恢复：

| 窗口 | 恢复要求 [仅规格] |
|---|---|
| T1 后 spawn 前 | 原实例可继续；owner 丢失保守 unknown/inspect，不推断未启动 |
| spawn 后身份落盘前 | ambiguous、不重 spawn；OS identity 需 host/boot/start/token，不靠 PID |
| T2 响应丢失 | 原完整参数 journal replay，不换配置或重 IO |
| cleanup unknown | 新 inspect 解 obligation，旧 unknown 与业务墙保留 |
| fiber unload 崩溃 | 仅继续未消费逆；episode 不提前 close |
| install 半途 | 原 reservation/journal 核对 CAS，不重扣引用 |
| provider cutover 中 | 同事务 route/事件，replay 判提交；不改旧 view |
| cancel 与 T2 | 同 G/run 串行；先 T2 保事实，先 cancel 拒旧发布 |
| spawn/取消树展开半途 | child+预算同提交；祖先域已挡新资格 |

## 9. 活性、验证与阶段

[仅规格] notify/activation/recovery/cleanup/transition各有driver/capability，共用control run lease/fence。
初始SLO：notify30s、activation60s、recovery/cleanup30s首尝试，drain5min升级不强卸；非终止定理。
DB回滚最多8次退避，host unknown不重发；阻塞登记水位不忙循环；scope轮转/aging、有界工作/维护配额。
指标：eligible_age/blocked_age、starvation、missing_owner、uncertain_budget；部署者管进程/挂死会话/磁盘，缺owner关readiness。

[仅规格] 五桶：结构DDL、协议模型、证据failpoint、活性drill、受信义务；阶段独立脚本/Fake退出0才通过，本轮未跑。
`spawn_key_input_conflict`：spawn(k,A)后新request的spawn(k,B)拒绝、零新child/重复划转；同digest/字节replay同child。
`episode_close_cross_run_inflight`：E服务R1/R2，R2已claim，R1结束触发close必须拒绝/等unloading，不卸载。
`t1_host_crash_t2_replay`：T1提交→离线host调用/保留原T2→host崩溃→原T2 replay，按§3合法fence/已提交/失权分支处置；断言IO一次、无第二effect、receipt或unknown责任可追踪，丢结果不造receipt。

| 阶段 | 退出条件与证伪重点 [仅规格] | 明确不做 |
|---|---|---|
| P0 | 纯合同模型、字节向量、共享读恢复反例正确拒绝 | IO/安装/fiber公开面 |
| P1 | 六动词/双账本纵向链、T2回滚、unknown/ACL/wait；故障链全分支通过 | child/fiber/原生进程 |
| P2 | role/child/escrow/join/cancel树；伪parent/孙辈/超额拒绝；spawn冲突负测、代理控制故障链全分支通过 | 完整workflow语言/插件 |
| P3 | 十规则/恢复/notify owner/重建；relied/重复逆/fault拒绝；跨run close负测通过 | 任意disposer/安装升级 |
| P4 | 离线三语言、CAS、agent管理插件、真实supervisor；spawn歧义不重做 | 恶意沙箱/真实provider/跨host |
| P5 | broker transition、固定handle、回退/饥饿drill、基准；同episode漂移必须失败 | 百分比流量/通用状态迁移 |

## 10. 默认决策、十个危险假设与具体问题

[第一性推导] 五默认：受限 L_eff 管 R、受信 adapter 管 A/C；D2语义强制+全局G短事务；先drain后原子transition；单机受信；同库分schema双账本。
[开放] 无跨节点、不可信隔离、unknown resume、通用补偿组合定理、有状态迁移或性能证明。

| 最危险假设 [开放] | owner/discharge；失败降级 |
|---|---|
| 1 adapter 不重投 token | adapter审计/计数/failpoint；未知则停止 |
| 2 插件无隐藏 IO | 作者/部署审核；仅受信，不冒充沙箱 |
| 3 足迹含全部 reads | L_eff解释器强制；拒R或加依赖 |
| 4 inverse/observer 足够 | 作者+reviewer向量；降C/A与残留 |
| 5 mutation 全部先G | kernel入口清单/ACL；漂移关readiness |
| 6 source不可被冒名 | auth/transport凭证与负测；拒控制 |
| 7 预算界定实际花费 | adapter硬cap/usage；uncertain/overrun debt |
| 8 OS证停可信 | host完整journal/identity/reap；resource_unknown |
| 9 维护持续公平 | deployment监控/停摆drill；不承诺终止 |
| 10 provider行为兼容 | service owner/canary；不切或blocked |

[开放] 八问：请给反例、严重度、修法及阶段：

1. 双账本/bundle能否防止已执行无恢复责任、语义applied无执行事实？
2. 独占写/快照读/依赖/support足够支撑R吗，缺何独立性/观察足迹前提？
3. 跨run invocation守卫能防共享服务早卸吗，claim/close竞争漏什么？
4. delegation/source审计及spawn输入绑定能防冒名/deputy/权限膨胀/key误用吗？
5. CE/fiber/recovery writer、分步Raise与residual close，是否有死路或虚假恢复？
6. G-first/对象集/祖先cancel域，是否漏入口、回滚窗口或有活性闭环？
7. realm/broker/pin能守单源、不漂移吗，切换回退缺何证据？
8. P1/P2故障链后，哪些阶段仍局部绿而整体不可用，缺何反例？

## 11. Oracle 两轮处置

[仅规格] 第 1 轮 SATISFIED（P0/P1）；原文 `prompt-exports/oracle-review-v24-initial-2026-10-22.md`。以下仅规格处置，未实现/测试。

- D1/P2：主§9.2/18.2、P2，brief §5/9/10；requests/birth record唯一键绑定规范输入，`spawn_key_input_conflict`。
- D2/P3：主§10.4/11.3/14/18.2、P3，brief §6/9/10；runtime_invocations唯一与跨run close守卫，`episode_close_cross_run_inflight`。
- 跨阶段：主§18.2、P1/P2，brief §9/10；effect/attempt/receipt/requests/unknown义务禁重IO/第二effect，`t1_host_crash_t2_replay`。

[仅规格] 第 2 轮 SATISFIED，无 must-fix；原文 `prompt-exports/oracle-review-v24-final-2026-10-22.md`。两条非阻塞显式化建议已纳入：

- 主§18.2、P1/P2：T2提交丢应答后receipt/两账bundle/预算/advance/后继各一次、首响应一致；回滚接纳全无、可追责、不造receipt；跨host重启持久记录证IO一次、无第二effect。
- 主§18.2、P3：总名下新增 `episode_close_after_claim`（claim先则close等/拒）、`episode_close_before_claim`（close先则拒后续claim）；unknown义务未清仍禁卸载。
