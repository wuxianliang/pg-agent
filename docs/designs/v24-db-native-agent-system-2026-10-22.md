# v24：数据库原生 agent 系统第一性原理规格

> 日期：2026-10-22；v24 是工作名，不是已发布版本。
> 状态：[仅规格] 新系统设计候选，供独立 Oracle 批判；没有 v24 实现证据。
> 本轮只写文档，不运行 gate，不修改代码，不 stage、commit 或 push。
> 权威范围：本文定义新系统；不追认 v13、v23、v99 或 zcordis 已满足本文合同。

## 0. 阅读合同与证据边界

[第一性推导] 本设计从不可撤销事实与责任开始，而不是从现有表结构开始。

[第一性推导] 数据库原生意味着：资格、授权、身份、状态转移和未清偿责任以数据库提交为准。

[第一性推导] 它不意味着把模型调用、进程管理或文件操作塞进 SQL 事务。

[仅规格] 关键判断使用以下四种标注；本节标注规则也适用于各表中的条目。

| 标注 | 含义 | 不能推出 |
|---|---|---|
| [已实现] | 本次读到的旧系统源码存在相应机制 | v24 已实现，或本轮实跑通过 |
| [仅规格] | 本文或被引用设计规定的协议 | 已有生产保证 |
| [第一性推导] | 从失败、权限与持久性边界推导的选择 | 已被形式证明 |
| [开放] | 尚无足够证据或未闭合的义务 | 可以默认放行 |

[已实现] v99 Phase 0 有六动词、单 claimed 槽、attempt pin、唯一 T2、unknown 墙和不可变审计表。

[已实现] v99 的 `spawn_subsession` 返回 simulated，不创建 child run；当前 effect kind 只有 llm/tool/human。

[仅规格] v99 原生插件平面的 runtime、install、scope、cleanup、provider 接线仍是设计。

[仅规格] zcordis 的 fiber、episode、recovery_plan、全局 G 和命名步授权重设计提供机制参照。

[已实现] zcordis P06 是目录分类与声明校验；P07 有 grant 状态与 issuer_kind 字段。

[第一性推导] 有目录行、角色文本或签名，均不证明真实执行者有权执行副作用。

[已实现] Cordis database 样例的 Driver.init 逐步 start、登记 driver、provide database，并逆序 dispose。

[第一性推导] 这证明需要持久化获取顺序与清理责任，不证明任意数据库写入都能被 stop 撤销。

[仅规格] 本文不声称论文的 recovery、progress 或 confluence 定理已转移到这个系统。

## 1. 设计命题与不可省略的责任

### 1.1 必须持久的东西

[第一性推导] 一旦后续动作可能依赖它，资格和结果就必须先持久化。

[仅规格] 必须持久：请求去重键、完整规范输入、权限来源、配置版本、operation/effect 身份。

[仅规格] 必须持久：claim/fence、结果 receipt、unknown、预算预留、资源身份和清理义务。

[仅规格] 必须持久：fiber 声明、episode committed view、逆描述符、恢复进度与残留。

[仅规格] 必须持久：parent-child 谱系、role/workflow 绑定、cancel 域、handoff 水位。

[仅规格] 必须持久：唤醒事实、待维护项目、失败责任 owner 与超期 debt。

### 1.2 可以丢的东西

[仅规格] 可丢：模型对象、语言闭包、连接、缓存、LISTEN 消息、内存中的候选和调度提示。

[仅规格] 可丢：从规范账本可确定性重建的 snapshot、索引、队列视图与观察摘要缓存。

[第一性推导] 丢失候选只能延迟执行，不能改变授权、产生新 effect 或擦掉责任。

[仅规格] 宿主 journal 是外部 IO 回执、provider 侧明细与该 run 后续 model 请求对话原文的唯一持久处；它丢失不改变任何十表行与已知/未知边界，但使该 run 的续链不可重建（history_missing → failure），只能经 command_recover 转 unknown。

### 1.3 至多一次、恢复与失败责任

[第一性推导] DB 可原子决定接纳一次结果，却不能原子提交远程世界与本地事务。

[仅规格] 因而拆开三个承诺：一次资格、一次受信投递、一次本地接纳。

[仅规格] 外部投递后结果不明时停止该逻辑 effect；租约到期不重新授权 IO。

[仅规格] 本地接纳至多一次由 DB 强制；外部投递至多一次条件于受信 adapter 不重投 token，不保证 provider 内部去重或执行次数。

[第一性推导] 可逆只适用于系统拥有写入权且能检查恢复前提的状态域。

[仅规格] emission 默认 A 类可对账；声明补偿不会把历史 emission 变成未发生。

[仅规格] 每条责任必须有 logical owner、执行 owner 和最终升级 owner，不能只写“后台处理”。

| 责任 | logical owner | 执行 owner | 最终升级 owner |
|---|---|---|---|
| [仅规格] 业务结果 | run/effect | 持租约 driver | run owner / parent |
| [仅规格] 插件恢复 | episode/range | recovery service | scope manager |
| [仅规格] 进程证停 | runtime/obligation | host inspector | deployment operator |
| [仅规格] 权限批准 | grant/approval | governance service | 人类 approver |
| [仅规格] 活性债务 | work_item | maintenance service | deployment operator |

## 2. 细腰与依赖方向

### 2.1 一种资格，一种交接，一种接纳

[仅规格] 细腰是一个有类型的 `EffectEnvelope`，及其 `admit → claim → execute → accept/advance` 协议。

[仅规格] 信封由稳定 effect_id、operation_id、执行域、冻结目标、权限证据、输入和披露合同组成。

[仅规格] 同一 effect_id 同时连接语义账与执行账；attempt 是执行证据身份，不是新的业务身份。

[第一性推导] 普通模型请求、spawn 子 agent、修改插件和卸载 fiber 都需要这套资格与交接。

[第一性推导] 它足够统一三者，因为三者的区别在状态转移解释器与授权对象，不在另一套 claim。

[仅规格] 细腰不包含任意 SQL、语言闭包、自然语言执行指令或插件自报的完成标志。

```text
角色 / 工作流策略 ─────┐
打包 / 治理策略 ───────┼─> typed operation admission
语义运行时 / fiber ────┘              │
                         EffectEnvelope + 双账本
                                      │
                           执行基质 T1 / T2
                           │          │
                       DB interpreter 受信 host adapter
```

### 2.2 五层职责

| 层 | 负责 | 依赖 | 禁止 |
|---|---|---|---|
| [仅规格] 效应代数 | 类型、足迹、逆前提、observer、残留 | 无 IO 的纯定义 | 调度、访问 DB、把测试当证明 |
| [仅规格] 语义运行时 | fiber、episode、binding、恢复计划 | 代数和细腰 ABI | 自己发网络、自己 spawn |
| [仅规格] 执行基质 | operation、claim、receipt、advance | 类型注册与窄解释器接口 | 理解业务 prompt、私建 fiber 状态机 |
| [仅规格] 打包治理 | manifest、approval、grant、scope、安装 | 细腰与声明接口 | 直接改 fiber/CE 生命周期 |
| [仅规格] 角色工作流 | delegation、角色约束、任务依赖、升级 | 细腰与只读观察 | 第二套 worker/lease/retry |

[仅规格] 层级是职责划分，不是语义层必须包住所有 run 的调用栈。

[仅规格] 普通 run 的 episode_id 可以为空；停用插件语义层时内核仍能执行内建受信 export。

[仅规格] 执行基质通过固定 kind 分派到引擎内解释器，不运行插件提供的任意 SQL callback。

[仅规格] `fiber_control` 解释器属于语义层；基质只检查信封、CAS、原子提交与 receipt。

[仅规格] 内建 bootstrap export、部署者和维护服务不依赖待安装插件，避免 agent 即插件的自举循环。

### 2.3 禁止出现的第二套系统

[仅规格] workflow 不持 executor token；plugin 不持独立 task lease；supervisor 不决定重试。

[仅规格] notify/recovery/cleanup 的分类只是 `operations/work_items` 的索引，不是独立执行队列。

[仅规格] policy 可以建议候选；唯一 admission/classifier 决定资格；唯一 claim 发放执行 token。

[仅规格] agent 可以替代策略 driver，但不可绕过相同的准入和预算检查。

## 3. 承诺、降级与非目标

### 3.1 承诺编号

| ID | 承诺 | 负责 discharge 的对象 |
|---|---|---|
| [仅规格] I01 | 所有受支持状态变化均有受控 operation 或 effect | API ACL、解释器、commit_bundle |
| [仅规格] I02 | 外部 IO 前 T1 已确认提交，控制连接 IDLE | driver/adapter 合同与 failpoint |
| [仅规格] I03 | 每 run 至多一个 claimed effect | partial UNIQUE、classifier |
| [仅规格] I04 | 同 effect 至多一份接纳结果与一次 advance | receipt UNIQUE、turn advance UNIQUE |
| [仅规格] I05 | 未知业务结果不重投、不续链 | unknown 墙、driver fencing |
| [仅规格] I06 | 旧 generation 可记事实，不得发布新业务后继 | T2 current-generation 守卫 |
| [仅规格] I07 | fiber 状态只经 fiber_control 与十规则扩展提交 | 私有 writer、语义事件守卫 |
| [仅规格] I08 | 逆消费与可逆 DB 变更同事务 | range CAS、DB interpreter |
| [仅规格] I09 | caller 从认证连接及派生凭证获得 | principals、delegations、executor mapping |
| [仅规格] I10 | cancel 不擦未知、预算或资源责任 | cancel seal、obligations |
| [仅规格] I11 | 每 episode 冻结 provider 身份与值版本 | committed_views、binding_versions |
| [仅规格] I12 | 每待维护项有 owner、截止目标、终止/升级路径 | work_items、debt、部署检查 |

### 3.2 允许且可观察的降级

[仅规格] 业务 unknown：run=blocked_unknown，只能观察、取消与清理，不能自动恢复业务执行。

[仅规格] 资源 unknown：保留 obligation 与活引用；允许独立 inspect，拒绝宣称 disposed。

[仅规格] 恢复前提冲突：episode 进入 blocked_recovery 投影，四态本身仍为 unloading。

[仅规格] worker 停摆：系统安全但不活；队列年龄与 missing_owner debt 必须暴露。

[仅规格] 依赖不可满足：fiber 保持 inactive，展示缺依赖；不伪造 active。

[仅规格] 投影损坏：关闭相应 readiness 闩，保留日志，重建后才恢复资格。

[仅规格] 有界 drain 到期：停止自动等待并升级人工；不强制释放 provider、句柄或 CAS 引用。

### 3.3 首版非目标

[仅规格] 单 PostgreSQL、单可信 host、同库原子事务；无跨节点接管或分布式事务。

[仅规格] 无恶意插件 OS 沙箱；签名、schema 校验、SQL ACL 都不替代沙箱。

[仅规格] 无任意 Cordis JavaScript 源码兼容、同步嵌套 RPC、任意 middleware 栈迁移。

[仅规格] 无 exactly-once 外部效果、无无条件终止、无普遍 confluence、无任意补偿组合定理。

[仅规格] 无自动下载依赖、运行安装脚本、模型生成代码即刻执行或自动扩权批准。

## 4. 效应合同：先限定能承诺什么

### 4.1 两个正交分类轴

[仅规格] `execution_domain=db|host` 决定事务协议；`disclosure=R|C|A|O` 决定恢复承诺。

[仅规格] `purpose=business|maintenance` 决定 unknown 墙和预算豁免，不由 caller 自选。

| 披露 | 必需描述符 | 可声称的结果 | 失败责任 |
|---|---|---|---|
| [仅规格] R 可逆 | inverse、前后版本、observer、受控足迹 | 限定投影恢复到 ≃ | 冲突则 blocked_recovery |
| [仅规格] C 可补偿 | compensation、业务谓词、允许残留 | 经验证的 ≈c，保留残留 | 补偿失败/unknown 留债 |
| [仅规格] A 可对账 | receipt schema、reconcile 方法、责任人 | 已知/未知及可审计残留 | 对账或人工关闭业务 |
| [仅规格] O 不透明 | 无足够披露 | 托管副作用拒绝准入 | 不能伪装 A/R |

[第一性推导] “执行成功”与“可逆”是不同判断；成功 receipt 不能证明 inverse 正确。

[仅规格] 普通 LLM/网络工具默认 A；受控 binding 注册为 R；退款等业务修正可为 C。

[仅规格] stop 进程只处理 acquisition；不能撤销进程已经发送的消息。

### 4.2 合法效应语言与 independence

[仅规格] 默认 `L_eff` 只含版本化 REG、UNREG、owned-cell SET、snapshot GET 和 typed EMIT。

[仅规格] REG/UNREG/SET 经 DB 解释器；EMIT 经 host adapter，默认 A。

[仅规格] 任意 Python/Node 只产生声明式结果；代码本身仍受信，不能据此声称全部行为被强制截获。

[仅规格] 每 R effect 声明并记录 read_set、write_set、ownership domain 和实际版本。

[第一性推导] 写不同 key 不够；读别人的可变态后计算自己的值也建立恢复依赖。

[仅规格] 可选择性恢复仅允许：写域独占，读域为不可变快照或已登记的 episode 依赖。

[仅规格] 其他共享读建立 dependency edge，依赖者退出前不得撤销提供者；禁止隐含共享写。

[仅规格] 运行时不接受“作者说可交换”作为任意序撤销许可；首版只做受限域的 LIFO 与依赖逆序。

[第一性推导] 全局串行 G 消除事务交错，不消除跨事务的语义依赖，不能 discharge independence。

[开放] 冲突图 D3 能否扩展选择性恢复，留待单独模型与成本测量。

### 4.3 组合与 observer 的实际限度

[仅规格] 一段全 R trace 只有在独占足迹、依赖关闭和 inverse 前提成立时才声称投影恢复。

[仅规格] C/A 混合 trace 记录每个原效应、修正效应与 residue，不将整段自动提升为 R 或 C。

[第一性推导] `R∘C=C` 这类简单等级表不能证明两个补偿谓词兼容，本文不采用为定理。

[仅规格] observer 是固定版本、只读、有限测试向量；结果保存 witness_evidence_id。

[仅规格] observer 覆盖集、等价关系、不能观察的域都随 manifest 固定。

[开放] 有限 observer 无法证明所有环境不可区分；R 的一般正确性仍有受信作者义务。

[仅规格] witness 分两段：admission 固定恢复模板；apply 时原子捕获旧值与版本；结果证据后追加。

[第一性推导] 外部调用前通常拿不到实际逆参数；只能预存模板并在 receipt 中绑定资源身份。

[仅规格] 若外部结果丢失，则模板状态保持 uncertain，不能虚构 inverse 参数并开始补偿。

## 5. 身份阶梯与时钟

### 5.1 身份不是一条链上的别名

| 身份 | 含义 | 持久关系与边界 |
|---|---|---|
| [仅规格] install_id | 某 host 上批准制品的一份安装 | 不等于实例，不带全局 active |
| [仅规格] scope_id | 权限、配置与恢复拥有域 | parent 固定，子授权只收缩 |
| [仅规格] fiber_id | 固定实现/配置的组件实例 | 跨多个 episode；升级创建新 fiber |
| [仅规格] episode_id | 一次激活直到完全卸载 | 一 fiber 至多一个 OPEN |
| [仅规格] run_id | 一个可控制任务或引擎控制流 | 可无 episode；一个 episode 可承载多个 run |
| [仅规格] epoch_id | run 的一次配置/交互连续期 | terminal steer 才新开；配置不可原改 |
| [仅规格] turn_id | 一个 effect 加一次 advance 的最小步 | 不等于一次模型加全部工具 |
| [仅规格] operation_id | 一次控制命令或执行准入 | 固定 run/epoch/generation 与 typed target |
| [仅规格] effect_id | 一次逻辑副作用 | 一 operation 至多一个主 effect |
| [仅规格] attempt_id | 一次提交的执行资格 | 绑定 driver_fence/effect_fence 与输入 |
| [仅规格] runtime_id | 一次 OS 实例 | host/boot/start_token 固定；不复用 |

[仅规格] episode 与 run 是一对多关联，所有关联均需同 scope/install 合法性校验。

[仅规格] bootstrap/activation 控制 run 可在 episode 创建前存在，L-Begin 才分配 episode。

[仅规格] episode OPEN 不代表业务 run 必须 running；active 服务可以暂时没有任务。

[仅规格] runtime 可以服务同 episode 的多个 run，但同一 persistent runtime 至多一个在途 invoke。

[仅规格] 该限制用 runtime_invocations 的 partial UNIQUE 强制，不引入 runtime lease。

[仅规格] runtime 死亡可导致多个 run 的已 claim 工作 unknown；新实例不能继承旧投递权。

### 5.2 各时钟只做一件事

| 时钟 | 增长原因 | 不代表 |
|---|---|---|
| [仅规格] scope_revision | desired config 改变 | 当前任务发布资格 |
| [仅规格] resolution_revision | 公开 provider 路由切换 | 已冻结 episode 视图改变 |
| [仅规格] driving_generation | 有效 steer/respond/handoff fencing | 进程重启 |
| [仅规格] run_revision | 可观察 CE 快照改变 | IO 执行唯一性 |
| [仅规格] driver_fence | 失租接管、cancel 撤权 | 外部进程已停止 |
| [仅规格] effect_fence | claim、撤权与 unknown | 新业务意图 |
| [仅规格] runtime_epoch | 同组件的新实例 | 可复用旧 token |

[仅规格] 组合 FK 验证 effect、operation、turn、run、epoch、generation 一致。

[仅规格] attempt pin 固定完整 handle：provider fiber/episode、binding version、grant revision、artifact 与 schema。

[仅规格] 旧 runtime 的结果只能对应原 attempt；不能推进新 epoch 或替换新 provider 的结果。

## 6. 数据模型与权威分配

### 6.1 同库三 schema

[仅规格] 首版采用同一数据库的 `v24_exec`、`v24_sem`、`v24_gov`；跨 schema 一个提交。

[第一性推导] 双账本是语义分工，不是两个能独立裁决同一事实的真相源。

[仅规格] `commit_bundles` 给一次原子提交中的两账事件建立显式关联；不依赖跨事务时间戳猜顺序。

[仅规格] 状态表是投影或协调权威；不可变历史表与短命凭证严格区分。

### 6.2 执行模型

| 表 / PK | 关键字段 / 枚举 | 权威与约束 |
|---|---|---|
| [仅规格] runs / run_id | status、root_id、parent_run_id、scope_id、generation | CONTROL；parent/root 不可改 |
| [仅规格] epochs / epoch_id | run_id、ordinal、config_snapshot_id、closed_at | 一 run 一个 open epoch |
| [仅规格] turns / turn_id | run_id、epoch_id、ordinal、effect_id、advanced_bundle_id | 每 effect 恰一 turn；advance 至多一次 |
| [仅规格] operations / operation_id | target、verb、status、seq、source_effect_id | pending/completed/archived/closed；seq 在 run 内唯一 |
| [仅规格] effects / effect_id | kind、purpose、domain、status、operation_id | ready/claimed/succeeded/failed/unknown/cancelled |
| [仅规格] attempts / attempt_id | effect_id、attempt_no、fences、pin、disposition | 不可变授权；每 effect 已投递资格至多一份 |
| [仅规格] receipts / effect_id | attempt_id、status、result、digest、bundle_id | 接纳结果不可变，effect_id UNIQUE |
| [仅规格] execution_events / (run_id,seq) | kind、身份、核验时刻、bundle_id | append-only 历史 |
| [仅规格] requests / (principal_id,request_id) | endpoint、canonical_input、response | 精确 replay，不按 digest 单独认同 |
| [仅规格] wakes / wake_id | run_id、epoch_id、reason、watermark | durable 事实，不含执行资格 |
| [仅规格] snapshots / run_id | revision、status、interaction、closeout_intent | 可重建读投影 |
| [仅规格] work_items / item_id | kind、owner_class、due_at、operation_id、state | 分类索引；不能另发 claim |
| [仅规格] commit_bundles / bundle_id | request/effect、event counts、schema_version | 不可变；提交联结根 |

[仅规格] run status：running / waiting_for_input / completed / failed / cancelled / blocked_unknown。

[仅规格] operation 的四个本地控制命令 start/steer/respond/cancel 创建即 completed；执行准入才 pending。

[仅规格] effect kind：model/tool/human/agent_control/fiber_control/runtime_control/governance/recovery。

[仅规格] domain、purpose、权限需求从 kind/action 的固定分类器推导，caller 不得降级分类。

### 6.3 语义模型

| 表 / PK | 关键字段 / 枚举 | 权威与约束 |
|---|---|---|
| [仅规格] effect_contracts / effect_id | disclosure、template、footprints、observer、owner | 不可变；与 effects 同事务创建 |
| [仅规格] semantic_events / (stream_id,seq) | effect_id?、rule、old/new、bundle_id、evidence | append-only；fiber/episode 与 effect 历史 |
| [仅规格] fibers / fiber_id | parent_id、install_id、state、retired、fault | inactive/reloading/active/unloading 投影 |
| [仅规格] episodes / episode_id | fiber_id、OPEN/CLOSED、outcome、closure_reason | partial UNIQUE(fiber_id) WHERE OPEN |
| [仅规格] committed_views / (episode_id,key) | provider_episode_id、binding_version_id | OPEN 内不可改；值域支持 relied |
| [仅规格] provisions / (realm_id,key) | owner_fiber_id | 声明寿命预留，remove 才释放 |
| [仅规格] binding_versions / binding_version_id | owner_episode_id、key、value/handle、schema | 不可变版本；不得存活闭包 |
| [仅规格] bindings / (realm_id,key) | current_version_id | 受控当前投影，REG/UNREG 唯一写口 |
| [仅规格] recovery_ranges / range_id | episode_id、frozen、end_coord、state | planned/applying/blocked/consumed |
| [仅规格] recovery_items / (range_id,ordinal) | original_effect_id、inverse、expected_version | 描述符不可改；逐项恢复 |
| [仅规格] recovery_consumptions / (range_id,ordinal) | recovery_effect_id、evidence、bundle_id | UNIQUE，消费证明不可变 |
| [仅规格] residues / residue_id | origin_effect_id、predicate、owner、state | open/contained/accepted；不删除原事实 |
| [仅规格] obligations / obligation_id | runtime/episode、origin_effect_id、reason | 资源责任权威，不由业务状态覆盖 |
| [仅规格] resolutions / obligation_id | resolving_effect_id、evidence | 同目标成功 inspect/cleanup 才可关联 |

[仅规格] 所有 effect 都有 contract；纯控制 operation 可无 effect，但仍有执行事件与 commit bundle。

[仅规格] DB 内 fiber 变更也有 receipt，不能因为没有外部 IO 就绕双账本。

[仅规格] outcome=success/error/NULL 与 episode OPEN/CLOSED 分离；fiber fault 为独立单调错误闩。

[仅规格] pending-notify 是 work_items 的 notify 分类；marker 可合并，未处理 revision 水位不可倒退。

### 6.4 治理与角色模型

| 表 / PK | 内容 | 约束 |
|---|---|---|
| [仅规格] principals / principal_id | login_role_oid/name、enabled、kind | 两者同时匹配认证 session_user |
| [仅规格] scopes / scope_id | parent、owner、open、current_snapshot | parent 不变；关闭前检查子域与引用 |
| [仅规格] config_snapshots / snapshot_id | scope/revision、parent snapshot、desired set | immutable；UNIQUE(scope,revision) |
| [仅规格] manifests / manifest_digest | identity/version、schemas、inject/provide、capabilities | 同名同版异内容拒绝 |
| [仅规格] artifacts / artifact_digest | file list、raw digests、CAS location | 没有安装脚本或可变 latest |
| [仅规格] approvals / approval_id | 三摘要、批准主体、权限上限、signature | 不可变；revoke 另追加 |
| [仅规格] installs / install_id | host、manifest、artifact、state | preparing/installed/draining/dispose_pending/disposed/quarantined |
| [仅规格] grants / (grant_id,revision) | subject、scope、verbs、limits、approval | 不可变版本；子权限取交集 |
| [仅规格] roles / (role_id,version) | allowed exports、control verbs、output contract | 不可变；文本角色不授权 |
| [仅规格] workflow_bindings / binding_id | workflow/version、node、role/version、run | admission 固定，变更须新 operation |
| [仅规格] delegations / delegation_id | source run/effect、target、verbs、expiry | 不接受自报 actor；可撤销投影 |
| [仅规格] budget_accounts / account_id | parent、limit、reserved、spent、uncertain | 非负、合计不越限；root 统一锁 |
| [仅规格] budget_entries / entry_id | effect、reserve/settle/release、量纲 | immutable；幂等业务键 |
| [仅规格] transitions / transition_id | old/new provider、state、cutover_revision | prepared/warming/cutover/draining/done/blocked/aborted |
| [仅规格] resource_refs / ref_id | live owner、install/runtime、release fact | 只释放一次；历史引用不算 live ref |

### 6.5 双账本与重建

[仅规格] admission 同事务建立 operation、turn、effect、contract 和 prepared 两账事实。

[仅规格] T1 同事务追加 attempt 授权与 pin；语义账只声明 prepared，不声明 applied。

[仅规格] host IO 在两事务之间；T2 原子写 receipt、execution event、semantic outcome、advance 和 journal。

[仅规格] DB domain 的真实变更、旧值捕获与上述 T2 同事务；失败整体回滚。

[仅规格] 两账都引用 bundle_id/effect_id；semantic applied 必须有成功 receipt 或同 bundle 的 DB 施加事实。

[第一性推导] “两账各自独立重建”不能解释为从一账凭空恢复另一账丢失的事实。

[仅规格] 历史账本从备份/WAL 恢复；投影由指定账本 fold，不能反向从现态补写历史。

[仅规格] rebuild 先关闭 readiness 并提交，再一致读、验证 FK/状态轨迹、原子换投影、重开闩。

[仅规格] 不按 created_at 选胜者，不去重冲突历史，不复活 lease、delegation 或旧执行许可。

[仅规格] 重建测试比较授权集合、unknown、relied、预算、fault 与 outcome，不只比较行数。

## 7. 基础 loop：一次 effect，一次 advance

### 7.1 最小状态机

```text
admit: operation pending + effect ready + contract prepared
                         │ T1 claim / COMMIT
                         ▼
                       claimed
                 ┌───────┼────────┐
                 │       │        │
             succeeded failed   unknown
                 │       │        │
              T2 advance once     └─> blocked_unknown（业务）
                 │
           next ready / wait / closeout intent
```

[仅规格] turn 是上述一次 effect 与它的唯一 advance；工具批次是多个 turn。

[仅规格] model→tool1→tool2→model 不能隐藏成一个对外 at-most-once 单元。

[仅规格] 一次 advance 可以原子准入有限后继，但本次不能执行后继 IO。

[仅规格] effect failed 只指确定失败或确定未执行；可能部分外部成功必须 unknown 或显式残留。

[仅规格] cancelled 只用于未 claim 的效果；claimed 不被 cancel 直接改为 failed/cancelled。

### 7.2 T1 与执行资格

[仅规格] 顺序：认证→G→request replay→固定锁序→准入/预算/权限复验→claim→attempt pin→COMMIT。

[仅规格] driver 必须确认 COMMIT；应答丢失先查询原 request，不能假设回滚而重新发起。

[仅规格] Token 含 effect、attempt、run/epoch/generation、fences、完整冻结输入、目标 handle 与合同摘要。

[仅规格] 受信 driver 检查连接 IDLE，才把 token 交给 host adapter。

[仅规格] 外部资格首版只签发一次；attempt_no 不意味着可以重试已经授权投递的业务 IO。

[仅规格] 确定未投递后的重新尝试采用显式 successor effect、引用旧 effect 与未执行证据，重新预算。

[第一性推导] 这个保守默认牺牲自动恢复率，避免把“只读”或“幂等 key”当成重试授权。

### 7.3 T2 与 advance

[仅规格] 唯一 `accept_receipt` 验证原 principal、attempt pin、fences、schema 和完整结果。

[仅规格] 已提交原请求 replay 在当前 lease/generation/terminal 检查之前，仍须验证原主体身份。

[仅规格] 接纳后同事务写 turn advanced、operation completed/archived、工具结果、后继及预算结算。

[仅规格] 当前 generation 才能发布 interaction、业务后继、final intent；旧 generation 仅追加真实结果。

[仅规格] 无论 current/stale，已接纳业务成本与资源义务都不能丢弃。

[仅规格] T2 任意后半段失败使全部回滚；原结果保留并重交 T2，绝不重做 IO。

[仅规格] DTO 违规不能被修成虚构业务失败；无法取得合法可信结果则隔离并进入 unknown。

### 7.4 DB domain 的执行

[仅规格] DB effect 仍先 T1 提交；执行事务中由固定 DB interpreter 施加变更并原子 T2。

[仅规格] 不允许外部 IO、任意动态 SQL、等待另一事务完成或语言 callback 进入该事务。

[仅规格] 数据库事务回滚可重试相同 DB 执行，因为其变更与 receipt 同生死；不适用 host effect。

[仅规格] DB 提交回执丢失也先 replay；不能用“事务内可回滚”推断已经提交的操作未发生。

### 7.5 lease、fence 与 unknown

[仅规格] 每 run 一个 driver lease；维护与普通工作共用该 run 的 claimed 槽。

[仅规格] 推荐 60s lease、20s 独立连接续租；数值是首版配置目标，不是正确性常数。

[仅规格] 过期不可续活；新 driver 实例有新 owner UUID 与更高 fence。

[仅规格] takeover 将旧 claimed 记录为 unknown，清执行槽；不重新投递旧 host effect。

[仅规格] 业务 unknown 墙挡该 run 的新业务，不挡其他 run 或精确资源维护。

[仅规格] unknown 历史不被改写；晚到证据只能追加 observation，不让旧 fence 获得发布权。

[仅规格] 首版业务 unknown 的出口是 cancel；证据驱动 resume 是开放债务，不能私加 resolve。

### 7.6 wake、等待与封口

[仅规格] wake 与快照/控制事实同事务落库；NOTIFY 只是可丢提示。

[仅规格] wait 使用短读事务、LISTEN 后复查、单调 deadline、超时再读、每 waiter 独立 cursor。

[仅规格] 等待时不持事务，不消费工作，不更新访问时间或 wake consumed_at。

[仅规格] final 先写 closeout_intent；正常封口需无业务 unknown、在途工作、interaction、attached child 和未解决资源。

[仅规格] 最后一笔 cleanup 可完成原 intent；cancelled 的 cleanup 只补账，不改 seal/snapshot/wake。

[仅规格] 每 epoch 唯一 closeout；cancel seal 明列未结算 claim、unknown、child 与资源责任。

[仅规格] 服务 episode active 不阻止一个普通请求 run 完成；只检查该 run 拥有的资源和引用。

## 8. 六动词的精确合同

### 8.1 公共 envelope

[仅规格] 入口为 `control(verb,target,expected_revision?,request_id?,payload,credential?)`。

[仅规格] verb 只允许 start/poll/wait/cancel/steer/respond；业务能力通过 typed exports 暴露。

[仅规格] start/steer/respond/cancel 是本地 CE operation；poll/wait 不写 operation 或 request journal。

[仅规格] agent 管理别的 agent 时，调用意图先成为 agent_control effect，再由其 DB T2 应用目标 CE operation。

[仅规格] 返回区分 admitted、replayed、rejected；admitted 不表示外部执行已完成。

[仅规格] start 的 expected_revision 必须为空；cancel/steer/respond 必须匹配锁后的 run_revision，respond 另匹配 interaction_id；精确 replay 先于版本检查，冲突零写。

[仅规格] 所有业务拒绝整体回滚且零业务写；诊断另由受信边界记无敏感信息日志。

### 8.2 逐动词定义

| verb | 做什么 | 不做什么 | 边界与失败 |
|---|---|---|---|
| [仅规格] start | 创建 run/epoch、固定 role/config/budget、首个 execution admission | 不在事务内 IO，不自动 active fiber | 单短事务；任何准入失败全回滚 |
| [仅规格] poll | 授权后读已提交 snapshot/水位 | 不 claim、不修复、不刷 notify | 单 MVCC 读；失败不写库 |
| [仅规格] wait | 检查 cursor，事务外等提示并重读 | 不驱动 child、plugin 或 lifecycle | 短读+事务外等待；超时/断连零状态写 |
| [仅规格] cancel | 禁新业务、撤 fence、关 ready、写唯一 seal 与取消域 | 不证明 IO 停止、不清 unknown/责任 | 单事务；树展开另为幂等 effect |
| [仅规格] steer | 同 epoch 新 generation/输入；终态可开新 epoch | 不改旧 pin、不能代答 approval/question | 原子归档旧 ready+新 admission；失败零写 |
| [仅规格] respond | 精确消费当前 interaction，校验答案，generation+1 | 不处理任意 effect，不授 grant | 一个事务内部 human settle；错误保留原 interaction |

### 8.3 start 的边界

[仅规格] 顶层 start 需 scope execute；child start 需可验证 source effect 的 delegation 与 spawn admission。

[仅规格] 首个模型依赖未 ready 的 persistent runtime 时，只准入 runtime start，后继描述符持久保存。

[仅规格] start runtime 的 T2 成功后才准入真正业务；重复请求返回同 run/runtime/token。

[仅规格] 普通 start 不创建 fiber；实例化插件需显式 plugin.instantiate，落为 fiber_control。

### 8.4 steer/respond 的边界

[仅规格] active steer 不抢占已 claim；旧结果可结算但不续链，旧 ready 归档。

[仅规格] active steer 不改变 epoch config 与 provider handle；新解析只能新 episode/新 epoch。

[仅规格] completed/failed 的 terminal steer 需先前资源已收尾，再冻结当前合法配置开新 epoch。

[仅规格] cancelled 不可重开；blocked_unknown 不准 steer/respond；closeout_intent 期间同样拒绝。

[仅规格] instruction 可由明确 steer 消费；approval/question 必须 respond，不从自然语言猜答案。

[仅规格] human 内部 effect 在一个事务中 claim/settle；不发给 worker，也不伪造 driver lease。

[仅规格] respond 是向当前交互提供数据；若需治理批准，审批者能力还要独立验证。

### 8.5 cancel 的线性化

[仅规格] cancel 与 T2 争同一 G 和 run 锁，以先提交者为线性化顺序。

[仅规格] T2 先成功则保留结果与成本，cancel 随后关闭尚未执行的后继。

[仅规格] cancel 先成功则撤旧 token；未提交 receipt 只可晚到审计，不接受旧结果推进。

[仅规格] cancel 不直接把 fiber 设 inactive；它只能准入后续 fiber_control retirement/unload。

[仅规格] 取消控制 run 本身不取消已经形成的独立清理义务；维护服务有自己的恢复授权。

## 9. 代理管理代理：同一效应面

### 9.1 agent 作为 driver

[第一性推导] 选择下一动作是策略，执行资格与提交是内核；两者无需绑定 Python 进程。

[仅规格] 人类、规则程序或 agent 都可根据 poll/observe 选择 typed operation。

[仅规格] agent 策略输出经 T2 校验后成为 agent_control effect；执行器仍需受信 transport/DB interpreter。

[仅规格] 模型没有 DB 凭据，不直接持有可伪造的 actor_id；transport 不可从任意 JSON 选择 source run。

[仅规格] 执行凭证绑定已提交 source effect、export、target、verbs、scope、budget 与 expiry。

[仅规格] 若 agent 负责驱动 child，只能用授予的接口推动；不获得 child 的 driver secret 或全部历史。

### 9.2 spawn admission

[仅规格] `agent.spawn` 是 DB domain 的 agent_control effect；不是 OS spawn，也不是第二个队列。

[仅规格] T1 固定 parent、spawn_key 与 canonical input；规范化对象含 child role/workflow 版本、scope、完整输入和额度申请，排除 transport request_id，编码版本入 digest。

[仅规格] T2 在 root/parent 锁下复验 cancel 域、depth、fanout、quota、grant 与 workflow node。

[仅规格] 同事务预留 child budget、创建 child run/epoch/role binding、parent-child edge 和结果 handle；requests journal 与 child birth record（即 parent-child edge）均保存 canonical input、digest、parent_id、spawn_key、child_id 和 source effect_id。

[仅规格] UNIQUE(parent_run_id,spawn_key) 绑定 canonical input digest；T2 在新划转/建 child 前查 birth record：digest 与规范字节相同才 replay 同 child，不同则闭集错误 `spawn_key_conflict`，零新 child、零重复预算划转；不能靠换 request_id 绕过。

[仅规格] 父不等待 child；结果 handle 仅含被授权的观察/控制入口和最小身份。

[仅规格] child scope 权限为父委派∩角色∩workflow∩批准 grant；不继承全部 env、凭据或 transcript。

[仅规格] admission 任一检查失败，预算、child、事件全部回滚，parent 收确定拒绝结果。

### 9.3 parent-child 授权

[仅规格] 谱系不自动等于全部控制权；直接 parent 仍需对应 verb delegation。

[仅规格] 默认 parent 可以 observe/steer/cancel；respond 还需 interaction 的允许 responder 集。

[仅规格] 默认无祖先、孙辈、兄弟、反向 parent 控制权；cancel 域传播由系统权限完成。

[仅规格] child 不能用 parent_id 参数冒充 parent；真实 source 来自 source effect 的 attempt 绑定。

[仅规格] delegation 撤销挡新控制 admission；已 claim 的外部调用只能 fence/unknown，不能假装回滚。

### 9.4 role 与 workflow

[仅规格] role 是版本化能力上限、工具集合、输出合同和 escalation policy，不只是 system prompt。

[仅规格] workflow node 绑定 role/version、允许前驱证据、输入/输出 schema、join policy、budget 上限。

[仅规格] 工作流 DAG 是 admission 约束，不拥有独立 runnable/claimed 状态机。

[仅规格] 前驱满足只产生候选 work_item；workflow.advance effect 原子校验证据并准入下一 operation。

[仅规格] 同 node 的 activation_key 唯一；重复观察、重复 notify 不能创建第二个 child。

[仅规格] role/workflow 改版只影响新绑定；运行中变更须显式 rebind operation、新 generation 与授权复核。

[仅规格] workflow 不能自动越过 unknown、human approval、预算或 cancel 域。

### 9.5 handoff

[仅规格] `agent.handoff` 固定源 run、目标角色、transcript 前缀水位、内容摘要、显式交接对象集。

[仅规格] 它不是复制所有状态，也不把 v13 handoff 收据等同于执行权转移。

[仅规格] T2 原子创建/绑定目标 run、写 handoff receipt、增加源 generation 并冻结源新业务准入。

[仅规格] 已在途源 effect 只能结算历史；目标必须看见其 unresolved 集，不能重复执行同一业务意图。

[仅规格] 首版仅在源无 claimed/unknown 且 ownership 可转移时允许独占任务 handoff。

[仅规格] 有 unknown 时允许材料交接，但不得标记业务所有权已完成转移；人工负责后续对账。

[仅规格] parent_run_id 不改写；另记 handoff edge 和受限 delegation，避免谱系循环。

### 9.6 observe、等待与 escalation

[仅规格] observe 是授权只读批量快照，返回 state、pending interaction、cancel、event watermark、debts。

[仅规格] 单批任一未授权目标则整批隐藏/统一拒绝；分页上限固定，不从 events 侧泄漏存在性。

[仅规格] parent wait(child) 是只读等待；parent run 自身若要持久等待，使用 typed await operation 登记条件。

[仅规格] child 终态写 durable wake；join effect 重读证据后决定继续，不由 wait 偷偷执行。

[仅规格] escalation 是 agent_control effect，创建固定 owner/deadline 的 interaction，不自动扩权。

[仅规格] 无审批者或到期未答保持 waiting 并形成 debt；默认不 skip、不把沉默当批准。

### 9.7 budget/quota 与取消树

[仅规格] budget 是总量账户，quota 是并发/窗口额度；所有执行入口共享 admission 闸。

[仅规格] T1 前预留最大成本；T2 以可信 usage 结算，unknown 保留 uncertain，不自动退回。

[仅规格] provider 无硬上限能力时只承诺本地准入上限，外部超额作为受信/业务债务显式记录。

[仅规格] child 额度从 parent escrow 划转，不靠分别检查两个可被并发透支的计数器。

[仅规格] cleanup/recovery 不消耗业务预算，但有部署者专用有界维护池，耗尽则升级而非丢责任。

[仅规格] cancel 根事务建立不可逆 cancel 域并 seal 根；spawn/claim/T2 准入读取祖先 cancel 域。

[仅规格] 全体后代的 seal/fence 由 cancel_tree work_items 分批 effect 展开，重放按目标去重。

[仅规格] 因祖先域已生效，尚未展开的 child 也不能启动新业务；在途 IO 仍可能完成。

[仅规格] root closeout 展示 pending_cancel_children；不声称大树所有行在一个事务内完成收尾。

## 10. Cordis 对象映射与运行语义

### 10.1 对象映射

| Cordis 对象 | PG 表达 | 差异与承诺 |
|---|---|---|
| [仅规格] plugin definition | manifest + immutable artifact | 声明不是装载成功 |
| [仅规格] Context/scope | scope + episode + capabilities | 不存活闭包与任意对象图 |
| [仅规格] fiber | fibers 行与语义事件 | 同实现实例，可跨 activation |
| [仅规格] Service | provide 的数据版本或调用 handle | 活对象身份不跨崩溃持久化 |
| [仅规格] inject | typed dependency spec + committed_views | 解析冻结，按依赖变化重新激活 |
| [仅规格] provide | provisions 预留 + REG binding | 声明唯一与当前可见分开 |
| [仅规格] ctx.effect | effect contract + recovery item | 任意 disposer 不自动等于 R |
| [仅规格] dispose | fiber inverse/recovery + resource cleanup | 不等于删除安装制品 |
| [仅规格] notify | 持久 dirty revision + 分类 effect | 不同步回调，不保证原 JS 轨迹等价 |
| [仅规格] driver 子插件 | 独立 fiber 提供 scoped service handle | 底层连接/stop 属资源义务 |

[已实现] database 样例中 Database 是 model Service，Driver inject model，再提供 database。

[第一性推导] 因而抽象服务与具体 driver 必须分开实例化与退役；不能把包安装当 provider active。

[仅规格] 宿主 SDK 只把 `ctx.effect/provide/get` 编译成 typed 请求，不把原 JS 调用栈保存到 PG。

### 10.2 provision、binding 与通知

[仅规格] 每 `(realm,key)` 至多一个声明 owner；inactive provider 也保留 provision。

[仅规格] binding 的 value 或 handle 固定版本，active 且未 retired 才对新解析可见。

[仅规格] episode Begin 记录 key→provider episode→binding version 全映射；OPEN 内不可替换。

[仅规格] 旧 binding 的实际资源必须存续直到全部依赖 episode 退出。

[仅规格] notify 覆盖 binding 变化、fiber 跨 active、retired、scope 路由与新建空 inject fiber。

[仅规格] notify 分类先比较 satisfaction，再比较 provider/version target；neutral 不能吞 target drift。

[仅规格] dirty marker 消费与候选 effect 准入同事务；候选执行时重新 live 校验。

[仅规格] 新 marker 带更高 revision，不会被旧 marker 的消费覆盖；全量扫描负责遗漏检测。

### 10.3 fiber 十规则

[仅规格] 下表是 Cordis 十规则在本系统的持久协议；增加显式子域与外部恢复守卫。

| 规则 | 前提 | fiber_control T2 写出 |
|---|---|---|
| [仅规格] O-Insert | 父存在未 retired、声明无冲突、依赖图合法 | inactive、provision 预留、声明事件；不自动 active |
| [仅规格] O-Retire | 实例存在，任意四态 | retired=true、子树 retire 域、dirty；不直接 unload |
| [仅规格] O-Remove | retired+inactive、无 OPEN、无子/活引用/未消费 range | 去在线实例与 provision；历史保留 |
| [仅规格] L-Begin | inactive、无 fault、未 retired、依赖满足 | 新 OPEN episode、冻结 view、reloading |
| [仅规格] L-Iter | reloading、view 未漂移、前步已 land、执行授权有效 | 一步 effect/逆捕获与进度事件，保持 reloading |
| [仅规格] L-Finish | reloading、末步已记录逆、view 相同 | active、outcome=success；episode 仍 OPEN |
| [仅规格] L-Divert | reloading、target 漂移或实现不可用 | unloading、pending reason=DIVERTED，保持已落地逆 |
| [仅规格] L-Raise | reloading 的确定错误；finalize 阶段需匹配 pending error | 先转 unloading 并固定 pending error；全部恢复后才写 fault/error 并 close |
| [仅规格] L-Leave | active、target 漂移或 retired | unloading、撤可见性、notify；不直接删 binding |
| [仅规格] L-Unload | unloading、无 relied/在途正向/子域责任，恢复完成 | inactive、episode CLOSED、保留 outcome/fault |

[仅规格] installed 是 reloading/active/unloading 且有 OPEN episode 的谓词，不是第五个状态。

[仅规格] relied 按 committed_view 的值域 provider_episode_id 检查，包括正在 unloading 的依赖者。

[仅规格] fault 只在完成错误恢复后写一次；成功卸载不能清 fault，重新尝试需要新 fiber。

[仅规格] L-Raise 的恢复跨多事务时只保存 pending error；尚未完成不能对外宣称 error 已清偿。

[第一性推导] 外部补偿无法在一个 DB 事务内完成，因此不能照搬“先恢复再 error”的单事务叙事。

[仅规格] 各子步仍为独立 effect；最后一个 fiber_control 校验全部完成后写正式 fault/close。

[仅规格] L-Raise 分 request/finalize 两个有血缘的阶段；pending error 的卸载不能按普通 L-Unload 关闭，最终必须保留 FAILED 原因与同一 error。

[仅规格] 这是一项持久协议扩展；不能把它称作未经修改的十规则或继承原论文证明。

### 10.4 在途、父子域与恢复边界

[仅规格] L-Iter 是 fiber_control 对语义步骤的核准；实际 host effect 的 outcome 由原 receipt land。

[仅规格] 每个 episode 至多一个未 land 的正向步骤；非 reloading 不准新正向 admission。既有 runtime_invocations 以 attempt_id 为 PK，固定 runtime_id、provider_episode_id、run_id、effect_id；状态 claimed/settled/unknown，partial UNIQUE(runtime_id) WHERE state IN ('claimed','unknown')，强制一个 persistent runtime 至多一个未清在途调用。

[仅规格] invocation 与 T1 claim 同提交，T2 原子置 settled；takeover/隔离置 unknown，仍保留资源义务。Leave/Divert 撤新准入；在 G 与既定 episode/runtime 锁序下，close 检查 provider_episode_id 指向本 episode 的所有 run 的 claimed invocation，存在则拒绝或保持 unloading 等待，不能随某一 run 结束卸载。

[仅规格] unknown 的正向步骤建立 residue/obligation，阻挡“精确恢复完成”与 episode close。

[仅规格] 父 episode 拥有创建子 fiber 的 support edge；父卸载先 retire 子域，再等其义务清偿。

[第一性推导] 本设计比只按 provider relied 的方案更保守，因为声称父域恢复必须包含子贡献。

[仅规格] 这不是论文原样定理；support edge 与 dependency edge 都参与卸载偏序并在准入查环。

[仅规格] 父子 scope 的授权继承与恢复拥有关系分开；不是每个 child scope 都被任意父任务拥有。

[仅规格] O-Remove 自底向上；不可 unlink 子树或删除历史以绕过守卫。

## 11. 恢复、补偿与 close 的实际算法

### 11.1 有序恢复

[仅规格] episode 的可恢复贡献按 `(step_ordinal,effect_ordinal)` 建立冻结逆序范围。

[仅规格] 范围冻结后不得追加；end_coord 明确，不靠“当前最大 seq”推断终点。

[仅规格] recovery planner 先确认无新正向许可，按依赖逆序选择 range 尾部未消费项。

[仅规格] 每项逆本身是新 recovery effect，具有 original_effect_id 和稳定 idempotency key。

[仅规格] DB 逆在 T2 检查 expected version、恢复旧值、写 consumption，同事务提交。

[仅规格] expected version 不符则 blocked；不得无条件 SET 旧值覆盖后来合法写入。

[仅规格] 已消费项只读 replay；重复恢复不会再应用逆或再次退钱。

### 11.2 外部补偿与资源检查

[仅规格] host compensation 同样 T1→IO→T2；receipt 成功才消费对应责任或记录残留状态。

[仅规格] compensation unknown 不重发；只能新 inspect/reconcile effect 获取证据或人工升级。

[仅规格] 新 inspect 能解决“资源已停”义务，但不能把原业务 unknown 改成成功。

[仅规格] irreversible emission 可能留下 accepted residue；这不等于 ≃ 恢复，不允许标 exact_closed。

[仅规格] episode closure 记录 recovery_grade=exact|compensated|residual，不从 state=inactive 推断精确恢复。

[仅规格] residual closure 只允许人类 scope manager 明确接管责任，保留 blocker/debt 和历史；它不释放未证停资源的 live refs，也不豁免 dispose/Remove 的资源守卫。

[仅规格] 该出口不是业务 resume；原 run 仍只能 cancel，不能借 residual acceptance 续业务。

### 11.3 插件失败隔离

[仅规格] 模型/工具确定业务失败只影响所属 run；fiber 初始化失败进入 L-Raise，依赖者不激活。

[仅规格] malformed frame、超时或 runtime 身份异常隔离该 runtime，所有受影响在途调用 unknown；§10.4 invocation 不得随调用方 run 结束删除，跨 run claimed 挡 episode close，unknown 继续受资源义务守卫，确认清偿前不卸载。

[仅规格] 独立 run、维护服务和内建控制解释器仍可运行；插件不能占有全局 G 等 IO。

[仅规格] 不把 DB 崩溃或受信 driver 故障误称为已被插件隔离解决。

## 12. 安装、授权、激活与 dispose

### 12.1 manifest 与可信制品

[仅规格] manifest 包含 identity/version、adapter/digest、entry kinds、完整 schema、inject/provide、能力申请。

[仅规格] entry 可导出 agent/tool/service；三者都映射到固定调用 ABI 与 effect kind。

[仅规格] service 导出的是数据或异步调用 handle；不能通过 service 绕过 effect 面同步 IO。

[仅规格] artifact 列出原始文件路径/大小/digest；拒绝路径逃逸、symlink、重复路径与运行安装脚本。

[仅规格] canonical 编码有明确版本与测试向量；DB 产 canonical bytes，宿主验原字节不自行重编码。

[仅规格] approval 固定 manifest/artifact/adapter 三摘要、批准 entry/capability 上限与批准者。

[仅规格] 签名只证明来源与批准；包内容和 adapter 同一性由受信 host verifier discharge。

### 12.2 install 的两阶段资源协议

[仅规格] governance.install effect 的 admission 预留稳定 install_id、reservation_id 与允许制品。

[仅规格] T1 后 host 验签、校验文件并保留一份 CAS 引用；prepare receipt 再把 install 置 installed。

[仅规格] install 半途崩溃保留 preparing 与 reservation；通过原请求/journal inspect，不重复扣引用。

[仅规格] install 不直接激活 fiber，不 bump 任意 scope 的当前 provider。

[仅规格] 未关联 reservation 有部署者 reaper owner；先查 DB 引用与原 request，再决定释放。

### 12.3 grant 与 scope

[仅规格] 模型可请求 grant；只有认证 approver 能批准；issuer_kind 由真实 principal 类型推导。

[仅规格] scope 子集授权按 verb、资源、版本、限额求交，不接受文本“管理员”角色升权。

[仅规格] desired config 固定父快照；rebase 显式换更高父版本，所有变更原子验证或全回滚。

[仅规格] grant revoke 挡新 admission/claim；已投递效果不能撤销，接纳真实结果仍须允许记账。

[仅规格] 已 claim 的 token 记录原授权；撤权后的结果仅结算该事实，不据此生成新的未授权业务。

[仅规格] 紧急 revoke 同时取消相关准入域并产生清理任务；不能只改配置再声称在途 IO 已停。

### 12.4 激活与退役

[仅规格] plugin.activate 先以 governance effect 提交 desired config，再准入 fiber_control O-Insert/Begin。

[仅规格] 配置提交与 fiber active 是两个不同事实；API 展示 desired/applied/degraded，不能返回虚假已激活。

[仅规格] deactivate 通过 fiber_control retire/Leave/recovery；install 仍保留，可以按政策再实例化。

[仅规格] drain 禁新实例/episode，保留旧 handle 的资源责任；期限到期升级，不自动强卸载。

[仅规格] dispose 前必须 draining、无 live refs、未解决义务或 claim；DB 先写 reservation。

[仅规格] host 在事务外释放该 install 的一份 CAS 引用；confirm receipt 才置 disposed。

[仅规格] 共享 artifact 仍被其他 install 引用时可以 dispose 当前 install，不删除共享 bytes。

[仅规格] 同 reservation release/confirm 幂等；超时不复活 disposed_pending，也不重复释放。

### 12.5 agent 控制插件，插件作为 agent

[仅规格] agent 获得 plugin.preview/install/activate/deactivate/upgrade/dispose 的 typed export 子集。

[仅规格] preview 是只读；其余调用和普通工具一样经过 effect admission、预算、权限与 receipt。

[仅规格] agent 不能批准自己的 grant/manifest；升级需要的新权限形成 human approval interaction。

[仅规格] agent 插件的 manifest 固定角色与 export 合同，实例 fiber 为多个任务 run 提供 agent entry。

[仅规格] agent run 也可持有插件管理能力；“agent 即插件”不意味着每个 run 都必须拥有 fiber。

[仅规格] 插件内创建 agent 只能提交 agent.spawn 请求；不能直接开进程或写 child run。

## 13. provider transition 与 hot reload

### 13.1 单源纪律与并存

[第一性推导] 同 realm/key 的单源预留禁止直接让两个 provider 声称同一键。

[仅规格] 新旧 provider 放入不同 private realm；稳定 public key 由唯一 broker fiber 提供。

[仅规格] broker 的 versioned route 选择某个 private provider；新 consumer episode 固定具体 route/version。

[仅规格] committed view 同时固定 broker 与实际 provider episode；不能只固定 broker 而让调用漂移。

[仅规格] 首版支持原子 cutover，不支持百分比流量；扩展加权路由需独立一致性设计。

### 13.2 transition 状态机

| 状态 | 动作 | 失败与回退 |
|---|---|---|
| [仅规格] prepared | 固定 old/new、schema、grant、budget、transition_id | 验证失败零切换 |
| [仅规格] warming | 新 fiber Begin/Finish，运行 canary observer | 失败退役新 fiber，旧路由不动 |
| [仅规格] cutover | fiber_control 原子更换 broker route version 与 resolution_revision | 提交响应丢失 replay，不按当前版本猜 |
| [仅规格] draining | 新 episode 走新路由；旧 episode 保留旧 handle | deadline 到期形成 blockers/debt |
| [仅规格] done | 旧依赖/调用清零，恢复旧 fiber 后释放引用 | 未证停不能 done |
| [仅规格] blocked/aborted | 明示 unknown、恢复或兼容性问题 | 不强制宣布回滚成功 |

[仅规格] cutover 本身属于 fiber_control，不由 scope 配置 UPDATE 或 steer 偷改。

[仅规格] 旧 consumer 不原地换 provider；由 notify 请求 Leave/Unload，再 Begin 新 episode。

[仅规格] 老 provider 有 in-flight invoke 时不得卸载；relied 与 runtime invocation 两个守卫均需满足。

[仅规格] cutover 后回退是新 route revision；已在新 provider 上发生的外部效果仍保留责任。

[第一性推导] 回退路由不等于回滚世界；schema 相同也不证明行为兼容。

### 13.3 hot reload

[仅规格] hot reload = 显式新 artifact/approval/fiber + transition；不修改在用代码文件。

[仅规格] 文件 watcher 只能提出候选，不能自动批准或直接重启进程。

[仅规格] 旧版本不可用时旧 handle 报稳定 unavailable/unknown，不静默 fallback 到新版本。

[开放] 带状态服务的状态迁移与双写语义未闭合；P5 默认只接受无状态或显式导入导出合同。

## 14. 统一控制矩阵

### 14.1 六动词 × fiber 生命周期 × 角色/工作流

[仅规格] 表内“准入”均指创建 effect/operation；没有任何单元格授权直接 UPDATE fiber。

| CE 动词 | inactive / install | reloading | active | unloading / unknown | role/workflow |
|---|---|---|---|---|---|
| [仅规格] start | 开普通 run；显式插件请求另准入 O-Insert/Begin | 等依赖 ready，不能跳 Finish | 绑定冻结 handle 开任务 | 不绑定卸载中 provider；unknown 拒新业务 | 固定 role/version、node、budget；spawn 需资格 |
| [仅规格] poll | 只读 desired/缺依赖 | 只读步骤/责任 | 只读结果/水位 | 只读 blockers/debt | observe 授权过滤，不推进 DAG |
| [仅规格] wait | 事务外等 wake | 同左，不驱动 Iter | 同左，不自动 steer | 同左，不尝试 Unload/inspect | parent wait 不代答、不接管 child |
| [仅规格] cancel | 取消 run ready；可准入 retire | fence 正向，不删已落地逆 | 禁新业务；生命周期另走 Leave | 保留 recovery/cleanup/unknown | 建祖先 cancel 域，分批 seal 后代 |
| [仅规格] steer | 新 generation 业务；不激活 | 原 epoch pin 不变，不强 Finish | 不换 provider；可请求 transition export | unknown/closeout 拒绝；不恢复旧实例 | 授权 parent 指令；rebind 另 operation |
| [仅规格] respond | 仅当前交互 | 可提供初始化所需答案，仍不改态 | 答当前问题，generation+1 | 不清未知或范围；治理审批独立验权 | responder 集检查；human 批准不自动扩权 |

### 14.2 唯一写入口矩阵

| 状态域 | 唯一合法 writer | 不合法旁路 |
|---|---|---|
| [仅规格] run/epoch/generation/interaction | CE operation 与 accept/advance 私有 helper | plugin SQL、driver 裸表、policy callback |
| [仅规格] fiber/episode/retired/fault/view | fiber_control T2 十规则解释器；close 必查所有关联 run 的 invocation，无 claimed 且资源义务已清 | cancel/steer/respond 或单 run close 直接卸共享 episode |
| [仅规格] provision/binding/route | fiber_control 的 REG/UNREG/transition 子规则 | governance config、任意工具 DML |
| [仅规格] effect status/receipt/turn | claim/recover/accept 单入口 | adapter 自报“已完成”后直写 |
| [仅规格] inverse 应用/范围消费 | recovery effect T2；fiber close 只核验 | cleanup 随手删除范围 |
| [仅规格] approval/grant/install/scope config | governance effect 的窄解释器 | agent 自签 grant、admin 裸表日常操作 |
| [仅规格] OS process state | supervisor 出证，runtime_control 接纳 | DB 由 PID/超时猜死活 |
| [仅规格] workflow 资格/child/budget | agent_control T2、统一 admission | workflow 自建 scheduler 或旁路 enqueue |

[仅规格] fiber_control 只改 fiber 语义域，不自给任意业务资格；需要后继时调用同一私有 admission。

[仅规格] CE operation 可准入 fiber_control，但不能代替它提交 lifecycle；两者不能互相冒充。

[仅规格] recovery 可改 owned cell/binding 的逆投影，但 episode close 仍须最后 fiber_control 核准。

## 15. 事务、锁序与真实 caller

### 15.1 首版可执行全局锁序

[仅规格] 首版所有 mutation 使用同一事务级排他 advisory G；不跨 IO 持有。

[仅规格] 以下顺序适用于 API、worker T1/T2、维护、配置、授权、重建和内部解释器。

```text
认证与无写形状校验
→ G（固定数据库内键，事务级；首个锁）
→ request lock(principal_id,request_id)，检查 replay
→ scopes（scope_id ASC）与 config/readiness 行
→ root control rows（root_run_id ASC）
→ runs（run_id ASC，包括 source 与 target）
→ epochs → operations（run_id,seq）→ effects（effect_id）
→ fibers（fiber_id）→ episodes → provision/binding keys（realm,key）
→ runtime / invocation rows（runtime_id）
→ budget accounts（account_id）→ refs / obligations / ranges
→ append 两账、commit_bundle、snapshot/wake、request response
→ COMMIT / ROLLBACK
```

[仅规格] G 在 request lock 前，避免持其他请求锁进入嵌套跨对象操作形成新环。

[仅规格] replay 仍先于 live lease/config 检查，只多持 G；没有“读请求顺手修复”。

[仅规格] 内部 helper 接受已持锁 context，不嵌套公共入口、开第二连接或获取新 request lock。

[仅规格] 跨 run agent_control 必须在顶层确定 source/target/root 集合，排序后锁定并复验。

[仅规格] 发现对象集扩大则整事务回滚重规划；不在 effect 锁后补一个未排序 run 锁。

[仅规格] 逻辑守卫不满足立即结束事务；禁止握 G 等依赖者、进程、网络、human 或另一个持 G 者。

[第一性推导] G 让受支持短写事务串行，是首版可审查性取舍，不是性能终局或语义独立性证明。

[开放] 未来 scope 共享/独占闸与局部锁并发需重新证明全部跨域入口；本规格不提前承诺。

### 15.2 真实身份与代理凭证

[仅规格] 登录角色 name+OID 映射 principal；角色重建不继承旧身份。

[仅规格] `session_user` 是认证来源；SECURITY DEFINER 的 current_user 是 owner，不能当业务 caller。

[仅规格] SET ROLE 只缩小可用 endpoint 能力，不改变 principal；GUC 永不作为身份或门禁证明。

[仅规格] p_actor 只能缺省或等于从凭证解析出的 source；自报 issuer_kind/role/parent 无效。

[仅规格] 服务凭证的 agent source 由 DB 已签发 delegation_id 与 source attempt 推导，不信工具 JSON。

[仅规格] transport 认证为 executor principal；DB 同时审计 executor 与被委派 source，不能只存其中一个。

[仅规格] 人类管理批准、agent 委派、host 执行与维护权限是分开的 capability 集。

[仅规格] 不存在与无权限统一拒绝；精确 replay 只回给原主体及被允许的结果读取者。

### 15.3 ACL 与受信边界

[仅规格] 所有公共函数固定 search_path、固定 owner、精确签名授权；PUBLIC 与默认 EXECUTE 全部撤销。

[仅规格] 插件、operator、service 无核表 DML；不可变账本拒 UPDATE/DELETE/TRUNCATE。

[仅规格] superuser/owner 是部署受信边界；自检只能发现漂移，不能抵御恶意 DBA。

[仅规格] supervisor 无 DB 凭据；只保留本机 journal、进程身份与观测证据，不 claim 或重执行。

[仅规格] driver/executor 凭据不得进入插件环境；provider secret 仅由批准 adapter 注入最小边界。

[仅规格] SQL tool 使用独立最低权限 READ ONLY 计算事务；控制连接 IDLE，函数内部无外部 IO。

[仅规格] SQL gateway 固定函数身份与依赖闭包 digest，限制投影/行数/时间；READ ONLY 不单独证明安全。

[仅规格] 不运行任意 PL/动态 SQL；生产 DDL 必须停机或使用新版本身份，不原改被 pin 的实现。

## 16. 崩溃与竞争恢复矩阵

[仅规格] 各行的恢复都需原请求与已提交事实；“不明”是合法结果，不是测试失败的借口。

| 窗口 | DB / host 已有事实 | 恢复与 owner | 禁止行为 |
|---|---|---|---|
| [仅规格] admission 后、T1 前 | ready+contract+预算预留 | driver 发现原 effect 并 claim | 另建逻辑 effect/child |
| [仅规格] T1 COMMIT 应答丢失 | attempt 可能已提交 | 原 driver replay request，确认后才投递 | 默认回滚后重新分配资格 |
| [仅规格] T1 后 spawn 前 | claimed；host 未知 | 原活实例可继续；实例丢失则 unknown+inspect | DB claimed 推断未启动后重 spawn |
| [仅规格] spawn 后身份落盘前 | journal 有 intent，无完整 OS identity | supervisor 标 ambiguous；operator/inspect 隔离 | 同 token 再 spawn，或按 PID 误杀 |
| [仅规格] IO 成功、T2 前死亡 | 外部可能已变，DB claimed | takeover→unknown；保留原 evidence，cancel/对账 | 重新外呼拿一次结果 |
| [仅规格] T2 中途异常回滚 | receipt/advance 均未提交 | 原合法 owner 重交原 receipt；失权则 late evidence | 部分后继已可执行或重复 IO |
| [仅规格] T2 提交、响应丢失 | receipt+两账+advance+journal 同提交 | 原完整请求 replay，返回首响应 | 用新 fence/配置重造 receipt |
| [仅规格] cleanup unknown | 旧 cleanup 结果不明、obligation 未清 | 新 inspect effect 出证后写 resolution | 改原 unknown，洗白业务 unknown |
| [仅规格] fiber unload 中死亡 | consumed 前缀与未消费尾部 | recovery worker 从尾部剩余项继续；episode OPEN | 重复应用已消费逆或提前 close |
| [仅规格] plugin install 半途 | preparing+reservation，CAS 可能已保留 | governance recovery 查同 reservation/journal | 重扣引用、无证据 installed/disposed |
| [仅规格] provider cutover 中死亡 | route 更新与 transition 事件同事务 | transition worker replay；读 revision 判事实 | 半切换，旧 episode 改 handle |
| [仅规格] cancel 与 T2 竞争 | 同 G/run 线性化 | 先 T2 则结果保留；先 cancel 则旧 token 拒绝 | claimed 直接改失败或旧结果复活 |
| [仅规格] child 已建、spawn 应答丢失 | child+budget+handle receipt 同事务 | replay 原 agent_control effect 得同 child | 按时间查最新 child 或再扣 escrow |
| [仅规格] notify 消费中崩溃 | marker/candidate 准入同事务 | 未提交重扫，已提交发现原 candidate | 丢 marker 又无 candidate |
| [仅规格] grant revoke 与 T1 竞争 | 由 G 顺序决定 | revoke 先则拒 claim；投递已授权则只结算事实 | 后到结果生成未授权新后继 |
| [仅规格] handoff 创建目标后丢响应 | 目标与源 fence/receipt 同提交 | replay，源不能重新发业务 | 创建第二目标或改 parent 谱系 |
| [仅规格] cancel 树展开半途 | 祖先 cancel 域已提交 | maintenance 继续未 seal 后代；准入已被挡 | 新 child 越过未展开窗口 |
| [仅规格] supervisor journal 丢失 | DB 有 runtime，host 不能出完整证据 | resource_unknown；部署 operator 接管 | 查无记录等同进程不存在 |
| [仅规格] rebuild 中崩溃 | readiness CLOSED 持久 | recovery 从规范账本重建并完整验证 | 开闩或从投影补历史 |

[仅规格] 本机 journal 写序为 fsync intent→spawn→fsync identity；不存在 syscall 与持久化的原子承诺。

[仅规格] ProcessIdentity 包含 host_id/boot_id/pid/os_start_identity/runtime_id/runtime_epoch/start_token。

[仅规格] not_found 需完整 journal 与同 host/boot 的 OS 检查；ACK、心跳缺失都不是证停。

[仅规格] DB effect 崩溃是不同分支：变更与 receipt 同事务，无提交则可重新解释，不适用 host IO。

## 17. 活性、公平与 maintenance owner

### 17.1 一个执行队列，多个持久责任类别

[仅规格] work_items 是候选与责任索引，执行仍须准入 operations/effects 并获取所属 run lease。

[仅规格] 无业务 run 可认领时，内建 maintenance control run 仍可执行，不依赖某个插件启动。

[仅规格] maintenance control run 按 scope 分片是组织方式，不新增 claim API。

| 类别 | owner 进程/角色 | lease/fence | 重试、终止与等待目标 |
|---|---|---|---|
| [仅规格] notify | semantic-maintainer / notify capability | 所属 control run lease | DB 失败最多 8 次退避；30s 分类目标；耗尽升级 |
| [仅规格] activation | lifecycle-driver / fiber_control | control run lease+effect fence | live 重验；阻塞订阅水位，60s 首次进度目标 |
| [仅规格] recovery | recovery-driver / recovery capability | 同上+range CAS | DB 逆最多 8 次；外部 unknown 不重发；30s 首次尝试 |
| [仅规格] cleanup | host-driver / exact runtime capability | run lease+runtime token | inspect 新 effect；shutdown unknown 不重放；30s 首次尝试 |
| [仅规格] cancel_tree | control-maintainer / tree capability | control run lease | 分批有界扫描；10s 展开目标；祖先域先挡资格 |
| [仅规格] stale lease | execution-maintainer / recover capability | 新 driver fence | 到期10s内扫描目标；unknown 不执行 IO |
| [仅规格] install/dispose | governance-recovery / reservation capability | control run lease | 原 reservation replay/inspect；120s 首次核对 |
| [仅规格] transition | lifecycle-driver / transition capability | control run lease | 路由 CAS；默认5min drain 后升级，不强卸载 |

[仅规格] 数字是健康部署下的初始 SLO，不是绝对最长完成时间；退出前必须以测量调整。

[仅规格] 队列 owner 必须随相应能力同批交付；missing owner/readiness 检查不通过则不开放准入。

### 17.2 公平规则

[仅规格] 跨 scope deficit round-robin，同 scope 按 due_at/age/稳定 item_id 排序。

[仅规格] 每轮预留维护配额，但 cleanup 不永久压住 business；连续维护上限后切换可执行业务。

[仅规格] 已 claimed 不可抢占；单次工作有时间/输出/扫描上限，阻塞项不能占队首无限重试。

[仅规格] 依赖阻塞返回 blocked 并登记 awaited watermark；变化或定期全扫才重新候选，避免忙循环。

[仅规格] poisoned item 超重试预算后进入 escalated，保留 obligation；不是悄悄丢进死信后当完成。

[仅规格] 自动重试仅适用于已回滚 DB 事务/未发 IO 的协议步骤；不扩大 host 业务投递许可。

### 17.3 debt 与环境责任

[仅规格] liveness_debt 记录 owner_class、oldest_age、due_at、blocker、retry_count、last_progress、escalation_owner。

[仅规格] 指标含 eligible_age、blocked_age、processed_rate、starvation_count、missing_owner、uncertain_budget。

[仅规格] eligible_age 与 blocked_age 分开；等 human 不是 worker 饥饿，二者都可能需要告警。

[仅规格] deployment operator 负责启动/重启维护进程、处置挂死 DB 会话、可用磁盘与 host journal。

[第一性推导] lease 到期不会释放打开事务的行锁/G；DB statement_timeout 与运维终止会话承担该责任。

[仅规格] 目标为短事务 p99 与 G 等待可测，设置 lock_timeout/statement_timeout/idle_in_transaction_timeout。

[开放] 不在未测量到达率、服务率和长尾前声称债务有界或所有 fiber 最终静默。

## 18. 验证总账：五桶与证伪

### 18.1 五桶分离

| 桶 | 要证明/观察什么 | 工件与 owner | 可机械化程度 |
|---|---|---|---|
| [仅规格] 结构 | FK、唯一、append-only、状态枚举、身份一致 | schema owner 的 DDL 与负测 | 可机械检查；不证明外部事实 |
| [仅规格] 协议 | T1/T2、唯一 advance、unknown、十规则、锁序 | kernel/semantic owner 的有限模型与并发测试 | 部分；模型需与实现对应 |
| [仅规格] 证据 | 纵向链、故障窗口、实际调用数、重建 | gate owner 的确定性 failpoint/trace | 可重复实跑，非普遍证明 |
| [仅规格] 活性 | 公平轮转、停摆检测、恢复时间、drain debt | maintenance owner 的压力/停机 drill | 有界场景可测；环境公平不是定理 |
| [仅规格] 受信 | adapter 守序、真实 caller、OS identity、作者 witness | deployment/adapter/plugin owner | 可自检/审计；不能全部形式强制 |

### 18.2 必须先造的反例

[仅规格] `spawn_key_input_conflict`（P2）：spawn(k,A) 成功后以新 request_id 调 spawn(k,B)，B 的 canonical input 不同，必须返回 spawn_key_conflict，child 总数不增、预算不重复划转；同 digest/字节 replay 同 child。
[仅规格] `episode_close_cross_run_inflight`（P3）为总名，E 服务 R1/R2：`episode_close_after_claim` 令 R2 claim 先提交，再由 R1 结束触发 close，必须看见跨 run invocation 并拒绝或留在 unloading，保留 invocation、不得卸载；`episode_close_before_claim` 令守卫满足的 close 先提交，后续 R2 claim 必须拒绝已关闭/不可服务的 E，不投递调用；两顺序均保留 unknown 资源义务未清不得卸载的断言，T2/unknown 按原协议结算。
[仅规格] `t1_host_crash_t2_replay`（P1/P2）：T1 提交→离线 host 夹具调用并保留原结果/T2 请求→host 进程崩溃→原请求 T2 replay。两分支：① T2 已提交但应答丢失，replay 返回与首响应一致，receipt、两账 bundle、预算结算、advance、业务后继各只生效一次；② T2 回滚，先断言接纳写入全无，原 effect/attempt/receipt 或 unknown+obligation 可追责，原 owner/fence 仍合法才重交原 T2，失权仅 late evidence/unknown，结果丢失不得伪造 receipt。两分支均以跨 host 重启仍保留的夹具持久调用记录（非进程内计数）核验实际 IO 仅一次，不得新建第二个 effect。
[仅规格] 错误 inverse 覆盖后来的合法值：必须 version conflict，不得“恢复成功”。

[仅规格] 两个 effect 写不同 key 却读共享可变态：必须记录依赖或拒 R，不能自动判断 independent。

[仅规格] model 返回伪造 actor/issuer_kind：不能改变授权来源，也不能获得 parent 权限。

[仅规格] poll/wait 被反复调用：两账、预算、fiber、队列与 revision 完全不变。

[仅规格] provider key 名碰巧等于 fiber UUID：relied 仍按值域，不按 key 字面判断。

[仅规格] cancel 后 cleanup 成功：原业务 unknown、seal、成本与 residual 不变。

[仅规格] 旧 generation T2 返回成功：事实入历史，但无旧链后继或新 interaction。

[仅规格] install/dispose response 丢失：CAS 引用变化一次，不因共享 bytes 存在拒 confirm。

[仅规格] stop 一个维护 owner：必须形成 missing_owner/overdue debt，不能只保持静默积压。

### 18.3 模型、属性与端到端证据

[仅规格] TLA+/Alloy 有限模型覆盖两个 run、两个 provider、两代 fence、cancel/receipt/transition 竞争。

[仅规格] 检查安全状态不可达；公平条件显式作为模型假设，不从模型通过推断生产无条件终止。

[仅规格] 属性测试生成 REG/GET/SET/UNREG trace，验证所有权、LIFO、冲突与 observer 投影。

[仅规格] DB 两会话 barrier 用锁等待事实确定竞争窗口，不用 sleep 长短宣称先后。

[仅规格] host failpoint 统计实际 invoke/spawn 次数，分别覆盖投递前、syscall 后、T2 前后。

[仅规格] gate 默认 FakeLLM/FakeTool、离线进程夹具，不访问真实 provider；脚本退出0才算通过。

[仅规格] 内核链、插件链、parent-child 链必须有正向调用证据，静态禁止扫描只是补充。

[仅规格] 每阶段维护 conformance matrix、deviation ledger、README 与 loader 清单；本文不冒充这些工件已存在。

## 19. 分期 P0–P5

[仅规格] 每阶段都是能证伪的垂直切片；后阶段不倒写前阶段证据，不开放半个恢复运行时。

### P0：模型与合同冻结

[仅规格] 范围：EffectEnvelope、身份阶梯、R/C/A/O、observer、两账/bundle、锁序、真实 caller 模型。

[仅规格] 范围：纯内存 reference interpreter 与两个 run 的状态模型；不建立生产调度。

[仅规格] 退出：模型检查无双 advance/跨 epoch 发布；规范字节与 schema 测试向量固定。

[仅规格] 退出：受限 L_eff 的独占写/快照读恢复成立；共享读反例明确拒绝或产生依赖。

[仅规格] 反例：串行两个读算写 effect 后撤第一个，若覆盖第二个仍被判 exact，P0 不通过。

[仅规格] 明确不做：host IO、安装、fiber 公开面、真实 provider、多语言。

### P1：可靠内核与双账本最小闭环

[仅规格] 范围：六动词、单 run、T1/T2、turn=effect+advance、request replay、ACL、wake、unknown、预算。

[仅规格] 范围：一个 DB effect 与一个离线 Fake host effect，共用双账本与唯一 classifier。

[仅规格] 退出：start→model→tool→model→final 正向链；全部 T2 回滚点无半后继/半语义结果。

[仅规格] 退出：claim/receipt 响应丢失、takeover、cancel 竞争、wait 零写、最低角色负测及 §18.2 `t1_host_crash_t2_replay` 两分支全部断言通过：提交丢应答后首响应一致，receipt/两账 bundle/预算/advance/业务后继各一次；回滚无接纳写入、责任可追踪、不造 receipt；跨 host 重启持久记录证 IO 一次、无第二 effect。

[仅规格] 反例：IO 成功而 T2 回滚后故意重启，若再次 invoke 或既无 receipt 又无 unknown，P1 不通过。

[仅规格] 明确不做：parent-child、fiber/notify、install、原生进程；普通 run 不依赖语义插件层。

### P2：有角色的代理控制

[仅规格] 范围：agent_control、spawn/handle、delegation、role/workflow、escrow、observe、escalation、cancel 树。

[仅规格] 范围：受限 handoff、持久 join 条件；agent 策略与规则策略经同一接口。

[仅规格] 退出：父创建两个 child，观察、steer、respond、join；异角色受限工具集实际生效。

[仅规格] 退出：预算并发无透支；树取消窗口无新业务越界；spawn replay 恰同 child 与 escrow；§18.2 `spawn_key_input_conflict` 及代理控制链的 `t1_host_crash_t2_replay` 通过，复用 P1 两分支全部断言（首响应一致、五项各一次/回滚全无、追责与禁造 receipt），跨 host 重启持久记录证 IO 一次、无第二 effect。

[仅规格] 反例：伪造 parent JSON、孙辈控制、两个并发 child 消耗最后额度必须被拒；否则不通过。

[仅规格] 明确不做：完整工作流语言、任意 DAG 自动求解、插件生命周期、未知业务 resume。

### P3：持久 Cordis 语义与恢复原子公开

[仅规格] 范围：fiber 十规则、provision/binding/view、notify、DB R 逆、range、scope support edge。

[仅规格] 范围：一个内建 service 与 consumer；recovery/notify/activation owner 同批交付。

[仅规格] 退出：insert→Begin→Iter→Finish→Leave→Unload→新 episode，旧 outcome 保持。

[仅规格] 退出：按值 relied、父子恢复、末步逆、range 崩溃、重建 guard 等价、observer 套件及 §18.2 `episode_close_cross_run_inflight` 两顺序通过：`episode_close_after_claim` 必见跨 run invocation 并等/拒，`episode_close_before_claim` 必拒已关闭/不可服务 episode 的 claim；unknown 义务未清始终阻止卸载。

[仅规格] 反例：卸载被依赖 provider、重复消费逆、fault 后 Begin、父恢复忽略子贡献，必须正确阻塞。

[仅规格] 明确不做：任意 disposer、外部 R 精确恢复、制品安装、多语言、provider 升级。

### P4：打包、真实离线进程与治理

[仅规格] 范围：manifest/artifact/approval/grant、install/scope、Python/Node/只读 SQL、supervisor journal。

[仅规格] 范围：runtime_control、cleanup obligation、CAS dispose、agent 管理插件与 human 审批。

[仅规格] 退出：agent 经 effect 安装批准包→激活→调用 service/tool→退役→资源证停→dispose 完整链。

[仅规格] 退出：长调用续租、spawn ambiguous、凭据不泄漏、共享 artifact、最低 SQL executor 均有证据。

[仅规格] 反例：spawn 后身份落盘前杀 supervisor；若重 spawn/误杀 PID/无证释放引用，P4 不通过。

[仅规格] 明确不做：恶意代码沙箱、在线下载、真实 provider、跨 host、滚动路由与状态迁移。

### P5：provider transition 与运行证据

[仅规格] 范围：private realms+broker、原子 cutover、notify 重激活、drain deadline、显式回退。

[仅规格] 范围：五桶总账、维护停摆/饥饿 drill、吞吐/G 等待/恢复时间基准、retention 设计。

[仅规格] 退出：两个 provider 并存，旧 episode 始终旧 handle，新 episode 始终新 handle，旧资源最终按证据释放。

[仅规格] 退出：切换崩溃、canary 失败、回退、长活消费者阻塞都可观察，无未知被洗白。

[仅规格] 反例：cutover 后 broker 让同 episode 下一调用漂到新 provider，或强卸仍被依赖旧实例，P5 不通过。

[仅规格] 明确不做：百分比流量、通用有状态迁移、跨节点、生产 exactly-once 或论文全定理声明。

## 20. 五个默认决策与开放债务

### 20.1 报告 §5.5 的建议默认

| 决策点 | 建议默认 | 理由与保留债务 |
|---|---|---|
| [第一性推导] 效应语言范围 | 托管 R 用受限 L_eff；受信任意语言经 A/C adapter | 只有拥有的可恢复状态能承诺 R；任意代码不可自动截获 |
| [第一性推导] independence 级别 | D2 足迹/所有权强制；P0–P5 全局 G 串行短事务 | D2 管语义依赖，G 管并发协议；二者不能互相替代 |
| [第一性推导] 升级语义 | P4 drain，P5 private realm+broker 原子 transition | 先可达资源收尾，再显式滚动；不做同键双 provider |
| [第一性推导] 信任模型 | 单机受信部署、审核包、可信 adapter/DBA | 不把签名当沙箱；不可信产品需要另立隔离合同 |
| [第一性推导] 存储拆分 | 同库分 schema、同事务双账本+bundle | 最小化分布式双写；分库需要 outbox/协议重设计 |

[仅规格] 这些是建议默认，不要求用户在本轮批准；实施计划必须显式确认采用或记录偏离。

### 20.2 最危险的十个承重假设

| 假设 | owner / discharge | 失败时降级 |
|---|---|---|
| [开放] adapter 绝不重投 host token | adapter owner：journal、计数、failpoint、代码审计 | unknown；不宣称外部 at-most-once 已验证 |
| [开放] 插件不偷偷做未披露 IO | plugin/deployment owner：审核、凭据隔离；未来 OS sandbox | 只限受信，不泛称强制效应纯度 |
| [开放] R 足迹包含全部 reads | L_eff interpreter：强制操作集、版本/依赖记录 | 拒 R 或建立依赖，不能任意序恢复 |
| [开放] inverse/observer 真正代表业务等价 | plugin author+reviewer：向量、属性与证据 | 降为 C/A，保留残留 |
| [开放] 全部 mutation 都先 G | kernel owner：入口清单、ACL、并发审计 | readiness 关闭，不能混入裸表路径 |
| [开放] agent source 不能被 transport 冒名 | auth/transport owner：attempt 派生 credential 与负测 | 拒绝控制，审计 executor/source |
| [开放] 预算预留能界定实际花费 | adapter/provider owner：硬 cap、可信 usage | uncertain/overrun debt，不退回预算 |
| [开放] supervisor 能给可信证停 | host operator：boot/start identity、journal、reap | resource_unknown、阻 dispose |
| [开放] maintenance 持续公平服务 | deployment owner：健康探针、停摆/压力 drill | debt 与 escalated，不承诺终止 |
| [开放] transition 的 schema 与行为兼容 | service owner：canary/版本合同、迁移限制 | warming 失败不切；切后残留由 owner 承担 |

### 20.3 其他债务

[开放] 业务 unknown 的证据驱动 resume：谁批准、如何隔离旧投递与新资格，未设计为首版能力。

[开放] 全局 G 的吞吐、跨 scope 隔离、优先级反转与饥饿，需要 P5 数据才能决定拆闸。

[开放] 补偿等价的组合、复杂 C/A trace 的残留边界，没有统一定理。

[开放] stateful provider 的迁移、兼容性、旧写入排空与回退，超出默认 transition。

[开放] retention/归档必须保留 request replay、未知责任和 range 证据；不能简单 TTL 删账。

[开放] 多机 OS 身份、跨节点服务与多库账本不在本协议；扩展需要新的故障模型。

## 21. prior Oracle 五条的吸收与修正

| Oracle 原则 | 本文采用 | 必要修正 |
|---|---|---|
| [仅规格] 双账本 | §§4、6、7，effect_id+commit_bundle | 账本不独立猜真相；模板与实际 witness 分开 |
| [仅规格] 身份阶梯 | §5，fiber/episode/run/operation/effect/runtime | 增 turn/attempt；episode 可承载多 run，不等于 run |
| [仅规格] 六动词与 fiber 边界 | §§8、10、14 | agent 跨 run 控制先 effect；L-Raise 外部恢复分步 |
| [仅规格] 锁序与真实 caller | §15，G-first+排序对象集+派生 credential | 本轮不默认细粒度并发；G 不证明 independence |
| [仅规格] 活性 owner | §17，每类 owner/fence/SLO/debt | 责任分类不是第二 claim；SLO 不等于终止定理 |

[第一性推导] 采用 Oracle 的“先闭内核资格与结果，再开恢复/插件公开面”顺序。

[仅规格] P0 纯语义模型先行，但 P1 内核不依赖 fiber；P3 公开 fiber 与恢复同批交付。

[第一性推导] 对原报告中简单混合披露组合、两账独立重建、episode=run 的过强读法明确收窄。

[仅规格] 本文没有把 prior Oracle 的建议当成已验收架构，也没有让它替作者承担设计责任。

## 22. 证据索引与待裁决问题

[仅规格] Oracle 第 1 轮：SATISFIED（P0/P1），D1/D2 已处置；原文 `prompt-exports/oracle-review-v24-initial-2026-10-22.md`，处置仅指规格修订，非实现或负测已通过。
[仅规格] Oracle 第 2 轮：SATISFIED，无 must-fix；两条显式化建议已纳入；原文 `prompt-exports/oracle-review-v24-final-2026-10-22.md`，非实现/测试验收。
### 22.1 本轮实读材料

| 来源 | 用途 | 证据限制 |
|---|---|---|
| [仅规格] `cordis-db-plugin-six-verb-report-2026-10-21.md` §§2–5 | G1–G10、prior Oracle 与默认决策 | 报告判断不是实现证据 |
| [仅规格] `cordis-v99-vs-zcordis-2026-10-21.md` | 四对象事实地图与论文条件 | 未复跑测试；本文不用“推断”旧标签充当保证 |
| [已实现] `v99/core/sql/10_schema.sql` | 单 claimed、FK、immutable trigger | 只证明当前 Phase0 对象 |
| [已实现] `v99/core/sql/20_ledger.sql`、`30_ce.sql`、`40_permissions.sql` | claim/T2/replay/closeout/ACL | Fake-only；本轮未运行 |
| [仅规格] v99 插件设计与计划（2026-10-20 文件名） | runtime、scope、CAS、ABI、崩溃处理 | M1 未实现 |
| [已实现] v13 control/spawn/fanout/handoff/workflow_bind/goal_supervise/acl/observe README | 控制接口与已知部署边界 | README 的历史 gate 不等于本轮产品证明 |
| [仅规格] zcordis `2026-09-13-pg-cordis-system-redesign.md` §§3–5、8 | 所有权、十规则、全局 G、五桶 | L3/D2 新能力仍为规格 |
| [已实现] zcordis `0000/0006/0007` SQL 选段 | namespace、目录、grant 类型 | 不把自报 issuer_kind 当认证 |
| [已实现] database `core/src/{database,driver,index}.ts`、postgres `src/index.ts` | Service/inject/yield dispose 与 driver 生命周期 | 进程内行为不提供持久恢复证明 |
| [仅规格] `v23-minimal-agent-loop-2026-10-09.md` | 短事务/纯策略/六动词边界 | 不继承单表或一轮隐藏多 IO 的范围 |
| [仅规格] Oracle 原文 `134311-fa81`、`134344-adc8`、`134657-3a66` | 评价、五条设计、实施建议 | 仅对原 brief 的独立意见 |

### 22.2 优先要求 Oracle 证伪的三个裁决

[开放] 第一：双账本+commit_bundle+DB/host 两种执行域，是否仍存在 receipt 已接纳而恢复责任缺失的窗口？

[开放] 第二：D2 独占写/快照读+依赖边+父子 support 守卫，是否足以支持受限 R 的选择性恢复，还是必须进一步收窄？

[开放] 第三：agent_control 跨 run、祖先 cancel 域与 fiber/provider transition 共用 G 的协议，是否存在权限或活性闭环漏洞？

[仅规格] 压缩 brief 位于 `docs/analysis/v24-oracle-critique-brief-2026-10-22.md`，只压缩本文，不增加新合同。

### 22.3 A–L 覆盖索引

| 要求 | 主文位置 [仅规格] |
|---|---|
| A 分层与依赖 | §2 |
| B 基础 loop 与身份 | §§5–8 |
| C 控制原语与 agent driver | §§8–9 |
| D Cordis 插件与升级 | §§10–13 |
| E 统一控制矩阵与旁路 | §14 |
| F 数据模型、双账与重建 | §§4–7 |
| G 事务、锁序、caller、ACL | §15 |
| H 崩溃恢复矩阵 | §16 |
| I 活性、公平、owner | §17 |
| J 五桶验证与证伪 | §18 |
| K P0–P5 退出与反例 | §19 |
| L 非目标、债务、五默认 | §§3、20–21 |
