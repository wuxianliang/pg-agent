# Cordis v2 插件系统：一个提交口，八张表

日期：2026-10-25。设计稿，未实现；本轮只写本文，未建库、未改 schema、未运行 gate。
工作目录 `.claude/worktrees/v99`（v24 分支 checkout）。标注约定：`[规格]` 可实现合同，`[论证]` 有出处的推理，`[边界]` 明确不做，`[未决]` 需未来裁决；表格或代码块前的标记覆盖全表全块。
源码路径相对仓库根；`C/` = `/Users/wxl/Projects/deepseek-harness/vendor/cordis/src/`。前作：`docs/designs/cordis-plugin-core-2026-10-22.md`（下称 v1 稿），`docs/designs/v24-pg-agent-2026-10-22.md`（下称 v24 稿）。

## 0. 摘要

[规格] 本文给出 Cordis v2 的数据库原生插件系统：**一个提交口 `advance`，八张领域表，三个生命周期解释器**。所有领域写入只经 `advance` 在单一控制锁 `G = pg_advisory_xact_lock(24,1)` 下完成；外部 IO 在事务外；COMMIT 是唯一线性化点。

三句话结论：

1. **符合论文标准**：论文 Table 1 的十条生命周期规则逐条落到 `advance` 内的解释器转换（§5），§4.4 的六个命题逐条给出 DB 机制、证明草图与反例（§7）。不声称机器证明。
2. **功能完备的边界**：DSH Cordis 的五个核心概念、五种派发模式、loader/HMR 全部有落点或显式边界（§9）；其中五项 DB 原生不可复刻（同步 disposer 链、ESM 级 HMR、对象身份、prototype 链、同步 `next` 栈）列为红项，不以等价性掩饰。
3. **实现紧凑**：领域表不新增（八张），解释器不新增（三个），可逆性收窄为闭集 `inverse` 加显式 `unknown` 债务；验收为四个 gate（§10）。

核心论旨（全文辩护对象）：

- **一个 `advance` 端口**。插件不是并行进程，是 `advance` 管理的依赖与所有权。
- **episode = 持久化的 θ**。accumulator 由 `contribution` 行的 `seq`/`inverse` 表达，committed view 由 `episode` 行承载；不存闭包、不存按值快照以外的第二份生命周期。
- **pin = coeffect demand**。`live` 是派生谓词，不是通知队列；撤销靠公平扫描发现差异，不靠 watch 表。
- **事件 = listener contribution + dispatch effect**。不建事件表、不建第二状态机。
- **G 串行使 independence 成为 footprint 不变量**，而不是论文的假设前提；论文的 pairwise independence 在本设计中由写入面 confinement 强制成立（§7.2）。

与 v1 稿的关系：v1 稿的七张表本稿扩为八张（`slots` 泛化为 `contributions`，事件总线从“不做”改为“以 contribution + dispatch effect 实现”）；v1 稿「不建 episode 表」的裁决被推翻（§1.4）；v1 稿的 advance 合同、G 锁、崩溃矩阵主体保留。与 v24 稿的关系：十张表删减为八张，`events`/`requests` 判为簿记而非领域表，六动词压为三个解释器加 run 结算（§10.5）。

## 1. 裁决与定位

### 1.1 问题与判据

[规格] 要解决的问题：在不引入第二套生命周期、第二个调度器、第九张领域表的前提下，让 PostgreSQL 内的 agent harness 获得 Cordis 式的插件装配、硬依赖、可逆注册与反应式 coeffect。

三个判据，每个都必须落到可执行证据：

| 判据 | 达标含义 | 证据位置 |
|---|---|---|
| 符合论文标准 | 十条规则逐条有 DB 转换；六命题逐条有前提/机制/草图/gate | §5、§7、§10.2 |
| 功能完备（有界） | DSH 五概念、五派发、loader/HMR 全出现；红项点名并给理由 | §9 |
| 实现紧凑 | 领域表 ≤ 8；解释器 ≤ 3；SQL 行数量级 ≤ v24 的 60% | §10.1 |

### 1.2 v24 基线与删减

[规格] v24 实际十张表：`installs, fibers, slots, pins, effects, runs, scopes, episodes, events, requests`（v24 稿 §3.1）。本稿保留八张为领域表，`events`/`requests` 判为簿记：

| v24 机制 | 本稿裁决 | 依据／代价 |
|---|---|---|
| `slots` | **泛化**为 `contributions`，`kind ∈ {service, listener, cell, reservation, child}` | 事件与 coeffect 因此不需新表；槽位唯一地址退化为 `kind='service'` 子集的约束 |
| `episodes` | **提升为承重表**（θ 的持久化） | v1 稿删表裁决被推翻，见 §1.4 |
| `events` | 簿记，非领域表 | dispatch 事实由 `effect(kind='dispatch')` 承载，listener 由 contribution 承载；事件投影可由 `contributions` + `effects` 派生，本稿仍保留 append-only 事件行作可观测面，但不承载任何生命周期决策 |
| `requests` | 簿记（幂等键 → 首次 response） | 与 `effects` 同一权威行，不构成领域语义 |
| 六动词 `start/poll/wait/cancel/steer/respond` | 压为 run 结算 + 三个生命周期解释器 | 动词是 run 状态机的客户端投影；`wait` 的游标由 `events(entity,seq)` 提供，不需独立表 |
| `scope_control` 命令 | 并入 `install` 解释器 | scope 创建是 install 的声明后果（v24 稿 §6.1 已有此形状） |
| catalog 全量冻结 / 全局 revision freshness | 保留不可变身份 + 精确 pin | 无关目录变化不使旧 pin 失效（v1 稿 §2） |

[边界] 不继承 v24 的 `host_prepare` 跨提交过程、`resource_quiesced_at` 的 unknown 结算细节、`route_path` 物化路由；这三项在 v24 稿 §3.2 有定义，本稿若需要则按 v24 原文取用，不在本文重述。

### 1.3 与 v1 稿的逐条关系

[规格] 不假装 v1 稿不存在。下表是保留／改写／推翻：

| v1 稿裁决 | 本稿 | 理由 |
|---|---|---|
| 七张表 | **改写**为八张 | 事件与 coeffect 必须有可逆落点，只有 `slot` 一个贡献种类不够；§4.4 论证不加第九张 |
| advance 唯一提交口、G 先于行锁、replay 先于 lease 检查、B=16 后继 | **保留** | v24 稿 §2 已实现，本稿不改合同 |
| 「不建 episode 表，只保 `(fiber_id, epoch)`」 | **推翻** | 空贡献 fiber、跨事务多阶段 reconcile、L-Iter 的有界推进都需要 accumulator 与迭代位置；只用 `epoch` 一列无法表达「本 episode 已注册到第几条」与「committed view 是什么」。§4.3 给反例 |
| 「贡献只允许追加 slot／子 fiber，不需通用逆程序」 | **推翻** | 事件 listener 需要可撤销注册，`cell` 需要恢复前值；闭集 inverse 足以表达，见 §6.1 |
| 「v1 不做事件总线」 | **改写** | listener 是 contribution、dispatch 是 effect；不为工具调用造 dispatch 子系统，但事件面本身不再缺席 |
| resolve 沿 realm 路由、只返回未撤且 live 的 provider | **保留** | v1 稿 §2 |
| 崩溃矩阵六处 kill 点 | **保留并扩充**为七处 | §11 |
| 「不做 provider 流量切换／同槽双版本」 | **保留** | 旧槽释放前新 provider 不能占位 |
| 「不做观测等价证明」 | **收窄表述** | 观测等价实例化为单 key 的 ≃_k；需读对象内部状态的观察一律拒绝（§2.5） |

### 1.4 为什么必须推翻 v1 的「无 episode 表」

[论证] 反例（最小可构造）：fiber A 无任何 contribution（空 inject、不 provide），依赖 M。A 反复 off→on，M 中途 off→on。若只有 `(fiber_id, epoch)`：

1. `epoch` 递增只能表达「第几次激活」，无法表达「本次激活注册到第几条 contribution 就被打断了」——L-Raise 的 accumulator 撤回范围不可知；
2. L-Iter 的「本次 episode 用哪一份 ω」只能靠 `epoch` 猜，而 target 在一次 episode 内变化时（L-Divert）需要区分「已提交的 ω」与「新 ω」，一列装不下；
3. 空贡献 fiber 的「已装载」事实与「装载到一半」无法区分，v1 稿用 `activation_effect_id` 补这一列，其本质就是 episode 指针。

[规格] 因此 `episode` 是 θ 的持久化：`accumulator`（由 contribution 行的 `(fiber_id, episode_id, seq)` 隐式表达）、`committed_view`、`iterator` 剩余位置、`epoch`。这不是实现细节，是论文 θ 的列化。

### 1.5 定位声明

[规格] 本文不是三语宿主、不是任意 JS 插件运行时、不是生产级外部一致性证明。交付的是：受信单宿主、声明式安装、硬依赖、可排空 model/tool 回路、事件面与 coeffect 派生。

## 2. 形式基础：Γ、θ、effect、coeffect、≃ 的数据库解释

### 2.1 结论先行

[规格] Γ 是数据库。一个 key 的「值」是四元组 `(contribution_id, provider_episode, descriptor_digest, contract_version)`，不是活对象、不是闭包。这个选择是本设计与 DSH Cordis 最大的语义差异，代价在 §9.3 单列。

### 2.2 记号表

[规格] 全文统一术语，首次出现给英文。

| 记号 | 论文出处 | 本设计的数据库实体 |
|---|---|---|
| Γ | §3.1.1 effect context | 活 contribution 行 + scope 路由 + episode 的 committed view |
| θ_n | §4.1、§4.3 | `episodes` 行（accumulator + committed view + iterator） |
| target_n | §4.1 | **派生，不落列**：`target(γ,f) = if fibers.want_on then resolve(fibers.scope_id, manifest->'requires') else ⊥`。论文的 target_n 是 required keys → providers 的映射（一个 fiber 可从不同 provider 取多个 key），单列装不下；`want_on` 只是请求位 |
| ω_n（committed view） | §4.3 | `episodes.committed_view`（jsonb，L-Begin 冻结的 key→provider 映射，即 ω） |
| epoch_n | §4.1 | `episodes.epoch`，经 `fibers.current_episode_id` 读取；**不在 `fibers` 上存第二份** |
| e_n / Ψ（effect 与逆） | §3.1 | `contributions` 行及其 `inverse` 闭集 op |
| σ_n（coeffect 表） | §3.2 | `pins` 行（consumer → provider contribution 的 demand） |
| d（coeffect spec） | §3.2.1 | `installs.manifest->'requires'` 声明 |
| n ≺ m（优先级） | §4.4.4 | `installs.priority`，无环由 advance 校验 |
| step^t / edit^t | §4.3 | 一次 `advance` 调用及其 delta |
| ≃ | §3.3.2 Def 33 | 观测等价：Definition 33 加「dom(F) 一致且每个 fiber 的每个控制字段一致」。本文的「数据等价」是 ≃ 在单 key 上的实例化（下记 ≃_k），**不是 ≃ 的替代品** |
| ≈ | §4.4.1（eq. 52–53） | **控制字段近似**：两个状态在 σ 表（key→provider 绑定映射）与 ambient state 上**逐项相同**；只遗忘 registry 对「谁安装了它们」的记录，即控制字段 θ、τ、π、d、p、e 与 dom(F)。**不是**「未绑定的 key 可遗忘」——σ 的任何差异都使 ≈ 不成立 |
| ≃_k | §3.3.2 Def 33 在单 key 上的实例 | 同 key、同 descriptor digest、同 contract version、同 check 结果。本文的「数据等价」指这个，不冒充整状态的 ≃ |

### 2.3 effect 侧：可逆的是行操作，不是任意函数

[论证] 论文 §3.1.2 定义 revertible effect function `(f,g)`，要求 `g` 由作者提供、运行时只信任；§3.1.3 的 independence 是 pairwise 假设。本设计收窄为**可验证的逆**：

[规格] `inverse` 只能是四种闭集 op 之一：`delete_row`、`restore_prev`（描述符回到 `prev_contribution_id`）、`release_reservation`、`dispose_child`。advance 在提交前检查后置条件（行不存在／描述符等于 prev／引用数为零）。外部资源对应 `inverse='unknown'`，必须显式标注并计入债务，不得声称已证明可逆。

[论证] 这个收窄不违反论文：论文 §3.1.2 的 witness 条件 `g(f(γ)) = γ` 在闭集 op 上逐条成立（Theorem 16 的 LIFO 情形），而 independence 本设计由 footprint confinement 强制（§7.2），不是假设。代价：任意 JS disposer 不能进入 JSON 冒充可逆，`unknown` 是显式债务。

### 2.4 coeffect 侧：spec/notify/isolation/interception

[规格] 四个概念各自的落点，全部不新增表：

| 论文概念 | 出处 | 落点 |
|---|---|---|
| spec d（依赖声明） | §3.2.1 | `installs.manifest->'requires'`；激活时逐 key resolve 并写 pin |
| notify（依赖变化唤醒） | §3.2.2 | **无表**。派生谓词 `live` + 公平扫描就是通知机制（§6.3） |
| isolation（解析隔离） | §3.2.3 | `scopes.realm_overrides`，resolve 时沿祖先链合并；realm 是隔离不是 ACL |
| interception（拦截改写） | §3.2.3 | `scopes.intercept jsonb`，resolve 时合并（§6.5） |

[论证] 论文 §3.2.2 的 notification 在 DB 里没有对应物的原因是：论文运行时的 notify 是为了把「依赖变了」推给活对象；本设计的消费者不是活对象而是行，行的变化由 MVCC 与派生查询直接可见，推送层是冗余的。这不是忽略该节要求，而是换了观测模型后该要求被满足（§9.3）。

### 2.5 观测等价 ≃：被强化为数据等价

[规格] 论文的 ≃ 是 Definition 33 加 dom(F) 与每个 fiber 的每个控制字段的一致。本设计实例化到单 key：`k₁ ≃_k k₂` 当且仅当同 key、同 descriptor digest、同 contract version、且 `check` 谓词结果相同。

[规格] **这是 ≃ 的实例化，不是替代**：≃_k 只覆盖「一个 key 的提供者是否可互换」，不覆盖 dom(F)、不覆盖控制字段、不覆盖多 key 的组合结构。凡需要整状态 ≃ 的论证（如 §7.6 的范式唯一性）必须另给 σ 层的相等性，不能只引用 ≃_k。

[边界] 凡需要「读对象内部状态」「比较对象身份」「遍历 prototype 链」的观察一律拒绝，不提供对应查询。论文 §3.3.2 允许在 ≃ 下比较运行时状态；本设计把可观测面收窄到数据层，因此**不声称与 DSH Cordis 观察等价**，只声称保住了 §4.4 六个命题所依赖的那部分不变量。这是显式边界，不是疏漏。

### 2.6 本章不变量清单

[规格] 全文后续引用的代号：

| 代号 | 不变量 |
|---|---|
| I1 | 一个 key 至多一个 live service contribution（部分唯一索引） |
| I2 | 每个 live consumer 的每个 require key 恰有一个 pin |
| I3 | pin 指向的 contribution 在其 `released_at` 置位前不被物理删除 |
| I4 | 一个 fiber 至多一个 open episode |
| I5 | contribution 的 `seq` 在 episode 内严格单调 |
| I6 | 一次 advance 至多产生 B=16 条后继 |
| I7 | 每 fiber 至多一个未结算的 reconcile effect |
| I8 | 领域表无裸 DML 路径（除 advance 与簿记表的受控追加） |

## 3. 一个提交口：advance 合同

### 3.1 签名与身份

[规格] `advance(effect_id uuid, outcome jsonb) -> jsonb`（SQL ABI 与 v24 稿 §2.1 一致）。**v24 的 `outcome_v1` 精确外形是六键信封**：`{"v":1,"class":"command|claim|success|failure|unknown","claim":{"attempt":N,"fence":N,"owner":"..."}|null,"body":{...},"receipt_key":"..."}`。command 与 claim 的 `claim` 必须为 null，`body` 为已验证的命令负载；外部 effect 必须携当前 attempt/fence/owner；`unknown` 不得携可执行后继；`receipt_key` 可省略且不参与匹配。返回 `{v:1, disposition:"committed|replay|deferred", effect_id, emitted:[uuid...], revision, claim:{...}|null}`。

[规格] 本文行文把上述信封简写为「三元组 `(token, code {apply,ok,error}, value)`、`disposition ∈ {settled,replay,deferred}`」。**这是叙述抽象，不是 v24 的字面外形**；映射关系固定，不引入新语义：

| 本文简写 | v24 实际 |
|---|---|
| `code='apply'`（DB 命令，token 空） | `class='command'`，`claim=null` |
| `code='ok'` | `class='success'` |
| `code='error'` | `class='failure'` |
| （简写未单列） | `class='unknown'`：未决外呼，不得发布后继，只可转对账 |
| `token` | `claim.attempt` + `claim.fence` + `claim.owner` 三元，缺一不可 |
| `value` | `body` |
| `disposition='settled'` | `disposition='committed'` |

[规格] 身份错误、冲突 receipt、已被替代的 token 返回稳定错误 JSON 并**零写**；意外 SQL 错误必须抛出回滚，不吞掉。`deferred` 只用于屏障未满足的 DB refresh，不结算、不留半步副作用。

[规格] 调用方以独立 READ COMMITTED 短事务包住一次调用及 COMMIT；函数本身不提交。先取事务级控制锁 G，再读业务行。外部 execute 必须在确认 claim 已 COMMIT 且连接 IDLE 之后进行。

### 3.2 事务内顺序

[规格] 固定顺序，不可交换：

```text
1. lock G                       -- pg_advisory_xact_lock(24,1)
2. authenticate caller          -- principal, role
3. lock effect row              -- SELECT ... FOR UPDATE
4. replay check                 -- 已接纳 receipt → 比身份与内容 → 返回 replay
5. validate                     -- schema/claim/pins/episode epoch/budget/B/已声明能力
6. barrier check                -- 未满足 → deferred（零写，释放 G）
7. delta := interpreter(effect) OR reduce(pinned_policy, state, outcome)
8. validate delta               -- 闭集 inverse、ownership、清理 DAG 无环、后继 ≤ B
9. apply delta + store outcome/settlement
10. append successors (dedup by (parent_id, ordinal))
```

[规格] 第 4 步先于第 6 步：replay 在 lease／终态校验之前，因此过期 lease 不阻挡重放（v24 稿 §2.2）。第 6 步的 barrier 只检查 DB 可见事实，不等外部 IO、不持锁跨 IO。

### 3.3 三个生命周期解释器

[规格] 核内只有三个生命周期解释器，加一个受限 reducer：

| 解释器 | command kind | 职责 | 生成的后继 |
|---|---|---|---|
| `install` | `command_install` | 声明校验、scope 创建、安装记录、spawn 子 fiber | `fiber_reconcile` |
| `fiber_reconcile` | `command_reconcile` | 改目标、resolve requires、注册 contribution、activate/deactivate/cleanup 阶段推进 | `fiber_reconcile`（唯一）、`dispatch`、业务 effect |
| `dispose` | `command_dispose` | 请求并完成终止，墓碑 | `fiber_reconcile`（子）、`dispose`（子） |
| `reduce` | 非 command，随 run 结算调用 | `reduce(policy_ref, run_state, fact) -> (state, intents)`，只读 reducer，不写表不 IO | 业务 effect |

[规格] 模型／工具完成走与生命周期相同的事实通道，不按名称写分支（v1 稿 §2 保留）。策略是预部署、受限只读的 reducer；v1 只交付 `chat_tool`。

### 3.4 delta footprint 校验

[规格] 每次 advance 提交前校验 delta 的写入面：

1. **ownership**：每条新 contribution 的 `fiber_id` 必须是本 effect 的 owner fiber 或其在同一 episode 内创建的子 fiber；
2. **confinement**：delta 不得写其他 fiber 的 open episode、不得释放他人的 slot；撤销只能作用于本 episode 的 contribution；
3. **DAG**：child→owner 边与 consumer→provider 边合并后无环；
4. **闭集**：每条 inverse 在 §2.3 四类之内，或显式 `unknown`；
5. **有界**：后继 ≤ B=16；本 fiber 的 reconcile 惯性槽 ≤ 1。

[论证] confinement（第 2 条）是「independence 由设计强制」的技术落点：论文 §3.1.3 假设两个 effect 的写入域不相交，本设计由 advance 在 G 下拒绝越界 delta，使该前提不是假设而是不变量（§7.2）。

### 3.5 advance 绝不做

[规格] 外呼、等待别的 effect 完成、持锁跨 IO、任意动态 SQL、解释用户闭包、执行后继 IO——一律不做。T2 回滚后重交同一 receipt，不重新执行 IO。

[边界] G 不是分布式租约。单宿主、单 driver 是明确前提；多宿主下 G 无意义，本稿不承诺任何跨宿主正确性。

## 4. 八张表：承重列、约束与派生状态

### 4.1 总览

[规格] 八张领域表：`installs(plugin), scopes, fibers, episodes, contributions, pins, runs, effects`。命名上 `installs` 保留 v24 原名以免与实现脱节，概念上即「plugin」。每张表的承重列如下；JSON 只装已校验声明、数据与策略状态，不藏第二份生命周期、资源图或待执行程序。

### 4.2 逐表承重列

[规格]

| 表 | 承重列与责任 |
|---|---|
| `installs` | `id` 不可变声明身份；`scope_id` 安装地址；`owner_fiber_id`/`owner_episode_id` 配对可空的资源归属（FK 到 `episodes(fiber_id, episode_id)`，固定历史身份，不引用 fibers 当前投影）；`identity`/`version` 与 `UNIQUE(scope_id, identity, version)`；`manifest jsonb`（**其内**含 `requires[]` 硬依赖即 coeffect spec d、`provides[]`、`priority` 即 ≺、受控 check，同行不可变）；`artifact_digest`（内容寻址）；`contracts`（版本化 ABI、宿主 handler、显式 replay 权利）；`policy_ref`（获准 reducer 身份）；`overlay jsonb NOT NULL DEFAULT '{}'`（配置覆盖，resolve 时合并，嵌套深度 ≤ 4）；`state ∈ {preparing, installed, prepare_failed, prepare_unknown, dispose_pending, disposed}` |
| `scopes` | `id`；`parent_id` 只增不改的路由继承树；`realm_overrides jsonb`（key→realm，缺省继承，根缺省共享 root realm）；`intercept jsonb`（§6.5）；`closed_at` 单调。realm 是解析隔离，不是 ACL |
| `fibers` | `id` 实例终身身份；`install_id` 声明快照身份；`owner_id` 不可改资源归属树，唯一 root 可空；`scope_id` 解析地址（独立于 owner）；`want_on boolean NOT NULL DEFAULT false` 请求位（target 由 §2.2 派生，不落列）；`control_seq` 显式重试／目标变更序号；`current_episode_id` 当前 open episode 投影（可空；激活代次读 `episodes.epoch`，本表不存 epoch）；`owner_episode_id` 与 `owner_id` 配对的归属代次（清理闭包与跨代收养防护）；`retire_started_at` 不可反转事实；`failure` 失败事实及对应 control_seq；`dispose_requested_at`；`disposed_at` 不可复活墓碑 |
| `episodes` | `id`；`fiber_id`；`epoch`（`UNIQUE(fiber_id, epoch)`）；`state ∈ {reloading, active, closing}`；`committed_view jsonb`（L-Begin 冻结的 ω：required key → provider contribution 映射）；`iterator jsonb`（L-Iter 剩余位置与已注册上界）；`opened_at`/`closed_at`；`outcome ∈ {ok, error, divert, retire}`；`UNIQUE(fiber_id) WHERE closed_at IS NULL`（I4） |
| `contributions` | `id` 稳定能力引用；`fiber_id`/`episode_id` 贡献 owner；`seq` episode 内注册顺序（I5）；`kind ∈ {service, listener, cell, reservation, child}`；`realm`/`key` 注册地址（service/cell 用）；`descriptor jsonb`（不可变数据、版本化能力地址、check、listener 的 event/mode/priority/filter/exec）；`prev_contribution_id`（覆盖前值，`restore_prev` 的逆）；`inverse`（闭集 op 或 `unknown`）；`contract_version`；`withdrawn_at` 拒新解析；`released_at` 引用清零后释放 |
| `pins` | `consumer_fiber_id`/`consumer_episode_id`（激活期消费者，二者同空或同非空）或 `consumer_run_id`（run 消费者），严格 XOR；`key`；`contribution_id` 钉住的 provider 贡献及其 epoch；`created_at`/`released_at`。部分唯一 `UNIQUE(consumer_fiber_id, consumer_episode_id, key) WHERE released_at IS NULL` 与 `UNIQUE(consumer_run_id, key) WHERE released_at IS NULL`；`INDEX(contribution_id) WHERE released_at IS NULL` 支撑派生引用数 |
| `runs` | `id` 请求身份；`owner_fiber_id`/`owner_episode_id`；`scope_id`；`state`（reducer 数据状态：冻结输入、策略进度）；`remaining_steps` 有限步数；`ended_at` 排空事实；`result`；`parent_run_id`/`spawn_key` |
| `effects` | `id`；`parent_id`/`ordinal`（有界后继，`UNIQUE(parent_id, ordinal)`）；`fiber_id`/`episode_id` owner 与激活 fence；`run_id` 业务推进归属（可空于控制命令）；`kind ∈ {command_install, command_reconcile, command_dispose, dispatch, listener_call, model_call, tool_call, run_start, host_io}`；`status ∈ {ready, claimed, succeeded, failed, unknown, cancelled}`（v24 稿 §2.6 原样；本文行文里的「settled」是 succeeded/failed 的合称，cancelled 只可由 ready 态落，claimed 态不得谎报取消）；`input jsonb`（冻结参数、精确 pin/contribution 引用，提交后不可变）；`request_actor`；`claim_owner`；`attempt`；`token`/`lease_until`；`outcome`；`settled_at` |

### 4.3 关键约束

[规格]

- `contributions`：`UNIQUE(realm, key) WHERE kind='service' AND released_at IS NULL`（I1）；`UNIQUE(fiber_id, episode_id, seq)`；`withdrawn_at ≤ released_at` 单调；listener 用 `UNIQUE(fiber_id, episode_id, descriptor->>'event', descriptor->>'listener_id') WHERE released_at IS NULL` 防同 episode 重复注册同一 listener。
- `episodes`：`UNIQUE(fiber_id) WHERE closed_at IS NULL`；必须有 `UNIQUE(fiber_id, episode_id)` 供 `installs` 与 `fibers.current_episode_id` 的历史身份 FK 使用；后者绝不引用 `fibers.current_episode_id`。
- `fibers`：owner/self FK、`disposed_at` 墓碑 CHECK；owner 图与 pin 图合并无环由 advance 在 G 内验证（CHECK 无法表达）。
- `effects`：部分唯一 `UNIQUE(run_id) WHERE kind='model_call' AND status IN ('ready','claimed')`；`listener_call` 不设此约束（一次 dispatch 可有多个子 effect）；请求标识／input／已结算 outcome 不可变。
- `pins`：consumer 严格 XOR CHECK（§附录 A 的确切表达式）；`consumer_episode_id` 必须属于 `consumer_fiber_id`；被钉 contribution 的 `episodes.epoch` 必须等于 pin 冻结时记下的 provider epoch。

[论证] 上述单行约束由 DB 保证（Preservation 的第一层机制，§7.1）；跨行不变量（live、屏障、disposed 禁写、DAG 无环）由 advance 在 G 下强制，DEFERRABLE 约束触发器兜底。两类机制的分工写在 §7.1。

### 4.4 `slots` 如何泛化为 `contributions`

[规格] v1 稿只有 `slot` 一种贡献。本稿五类：

| kind | 注册地址 | descriptor 必填 | inverse 典型形态 |
|---|---|---|---|
| `service` | `(realm, key)` 唯一 | capability 地址、contract_version、check | `delete_row` + 释放唯一地址 |
| `listener` | `(fiber, episode, event, listener_id)` | event、mode、priority、filter、exec | `delete_row`（无外部引用） |
| `cell` | `(realm, key)`，可覆盖 | 当前值、`prev_contribution_id` | `restore_prev` |
| `reservation` | `(fiber, resource_key)` | 资源标识、额度 | `release_reservation` |
| `child` | 指向子 fiber | 子 fiber id | `dispose_child` |

[论证] 泛化的收益：事件（§6.4）、coeffect 预留（§6.3）、子 fiber 所有权（§5 的 O-Insert 后继）都用同一套可逆账本，不需要第四、第五张表。代价：`UNIQUE(realm,key)` 从全局约束降为 `kind='service'` 子集约束，DB 不再替我们防「listener 与 service 同 key」——这由 advance 的声明校验负责（`installs.provides[]` 只声明 service 与 cell）。

### 4.5 为什么没有第九张表

[规格] 逐个候选给反证：

| 候选新表 | 为什么不需要 |
|---|---|
| `events`（领域表） | listener 是 contribution；dispatch 是 effect；游标由 `effects(settled_at, id)` 与 `UNIQUE(parent_id, ordinal)` 提供 |
| `coeffects`/`watches` | pin 就是 demand；live 是派生谓词（§6.3） |
| `interceptions` | `scopes.intercept jsonb`，resolve 时合并（§6.5） |
| `notify`/`dirty`/`wake` | 公平扫描；唤醒可丢，事实不可丢（§11） |
| `refcounts` | `INDEX(contribution_id) WHERE released_at IS NULL` 派生计数 |
| `recovery_plan` | 重跑 resolve + 未结算 effect 就是恢复入口 |
| `committed_views`（按值快照表） | committed view 是 `episodes.committed_view` 一列；按值历史快照是显式不做项（§12） |
| `dispatch_state` | 不建表；dispatch 的进度由已结算 `listener_call` 子行派生（§6.4） |

[规格] 若最终论证必须第九张表，必须在本节补反例与代价，不得默默加。当前无此需求。

### 4.6 派生状态：不存枚举

[规格] 显式状态由查询推导，不落列：

```text
active     = 存在 open episode.state='active' ∧ live ∧ retire_started_at IS NULL
reloading  = open episode.state='reloading'
unloading  = retire_started_at IS NOT NULL ∧ 旧激活存在
closing    = open episode.state='closing'
inactive   = 无 open episode（closed_at 已置位）；论文的 Inactive(ζ) 由此派生，不落列
pending    = want_on ∧ 无 open episode ∧ 无当前 failure ∧ dispose_requested_at IS NULL
live(n)    = 所有 pin 指向 live contribution ∧ provider episode 未 closing ∧ want_on ∧ check 通过 ∧ owner 未 dispose
```

[论证] 论文 §4.2 的 fiber 状态机在本设计里是**投影**而非存储：存的是事实（目标、episode、retire 事实、墓碑），显示状态查询推导。这避免了「两份状态机可能不一致」这一类承重面（v1 稿 §8 同裁决）。

### 4.7 空贡献 fiber 与墓碑保留

[规格] 已装载的空贡献 fiber 由 open episode（`state='active'`，零 contribution）表示，不能「为了可推导」删除这条成功事实。退役 contribution 与已结算 effect 保留历史行；清理条件检查活义务而非要求历史行消失。

## 5. 十条生命周期规则：逐条落到 SQL 转换

### 5.1 规则总表

[规格] 论文 Table 1（§4.3，规则作为对 fiber 的写入）的逐条落点。Ψ 列是论文的 effect 列；「DB 写」列是本设计的实际行变更；「effect kind」列是承载该转换的 effect 类型。

| 论文规则 | θ 前 → 后（论文 Table 1） | 触发 | DB 写（表.列） | 后置／不变量 | effect kind |
|---|---|---|---|---|---|
| **O-Insert** | undefined → Inactive(⊥) | 外部请求安装 | `installs` 新行（state=installed）；`fibers` 新行（want_on=false, current_episode_id=NULL）；必要时 `scopes` 新行 | dom(F) 增加一个名字；fiber 无 episode（I4 保持） | `command_install` |
| **O-Retire** | unconstrained → unchanged | owner 退役或显式 retire 请求 | `fibers.want_on=false`（target 随之变 ⊥）；`fibers.retire_started_at`（若已有激活） | τ 改变；**不写 contribution、不改 episode**——只改请求位，由后续 L-Leave/L-Unload 执行 | `command_reconcile` |
| **O-Remove** | Inactive(−) → undefined | dispose 且无活义务 | `fibers.dispose_requested_at`、`disposed_at`；`installs.state=disposed`；释放 install 自有的内容寻址引用 | 墓碑不可复活；共享 artifact 不因他人引用被拒（v24 稿 §6.1） | `command_dispose` |
| **L-Begin** | Inactive(⊥) → Reloading(e, id, ω) | 第一个 reconcile 阶段 | `episodes` 新行（epoch=prev+1, state='reloading', committed_view=冻结的 target 映射, iterator=requires 全量）；`fibers.current_episode_id` 指向它；逐 key 写 activation `pins`（I2） | installed 变真；ω 在此刻定下，之后不变（§7.4） | `command_reconcile` |
| **L-Iter** | Reloading(i,g,ω) → Reloading(i′,g∘h,ω) | 每个 contribution 注册阶段 | `contributions` 新行（kind/realm/key/descriptor/inverse/seq）；`episodes.iterator` 前进；`episodes` 的 accumulator 由 contribution 的 `(fiber_id, episode_id, seq)` 隐式追加 | seq 严格单调（I5）；已注册部分按 seq 可 LIFO 撤回 | `command_reconcile` |
| **L-Finish** | Reloading(i,g,ω) → Active(g∘h,ω) | 最后一条 contribution 提交后 | `episodes.state='active'`（激活代次即 `episodes.epoch`，不写 `fibers`） | 空贡献 fiber 也有 open active episode（§4.7） | `command_reconcile` |
| **L-Divert** | Reloading(i,g,ω) → Unloading(g∘h,ω,⊥) | 阶段边界发现实时 resolve 的 target ≠ committed_view | `episodes.state='closing'`、`outcome='divert'`；**不 apply inverse**——accumulator 由 `(fiber_id, episode_id, seq)` 携带进 closing，等屏障满足后随 L-Unload 一并撤销；新目标留给下一次 reconcile | Ψ = id_Γ 或 pr₁∘i（论文 Table 1），即本步只写控制字段；ω 不变；不中途重解析；已注册部分**暂不**撤回，L-Unload 才撤回 | `command_reconcile` |
| **L-Raise** | Reloading(i,g,ω) → Unloading(g,ω,ξ) | 注册失败／check 失败／声明不符 | `episodes.state='closing'`、`outcome='error'`；`fibers.failure`（含 control_seq）；**不 apply inverse** | Ψ = id_Γ（论文 Table 1）；错误在 L-Raise 记录，恢复在 L-Unload 执行，L-Unload 必须在落到 Inactive(ζ) 之前 apply 完 accumulator；不自动重试同一 control_seq | `command_reconcile` |
| **L-Leave** | Active(g,ω) → Unloading(g,ω,⊥) | target→⊥ 或依赖失效或 owner 退役 | `contributions.withdrawn_at`（service/cell/listener 全部）；`episodes.state='closing'`；**不删 pin、不写 released_at** | 新 resolve 不再返回该 provider；旧 pin 仍可读（§7.3） | `command_reconcile` |
| **L-Unload** | Unloading(g,ω,ζ) → Inactive(ζ) | 屏障满足（pin 清零、run 排空、子 fiber 已清） | 按 seq DESC 删 contribution 或置 `released_at`；删 activation pin；`episodes.state='closing'`、`closed_at=now()`；`fibers.current_episode_id=NULL`、`retire_started_at=NULL` | 本 fiber 写入的绑定全部消失、其他 fiber 的绑定不受影响（≈ 对照「删去本 episode 各步后的反事实状态」，不是字面初始态；§7.2）；唯一地址释放；Inactive 由「无 open episode」派生（§4.6），不写 `state='inactive'` | `command_reconcile` |

[论证] 表中「effect kind」列说明十条规则全部由 `command_reconcile`（除 O-Insert/O-Remove）承载，不新增命令种类——这是「一个提交口」在生命周期层的含义：论文的十条关系规则在本设计中是一个解释器的多个分支，而分支选择由 DB 事实（episode.state、target、pin 计数）决定，不是由宿主内存的状态机决定。

### 5.2 分期：一阶段一 advance

[规格] reconcile 分期，每期一次 advance 调用、一次 COMMIT：

| 阶段 | 前提 | 动作 | 结算后置 |
|---|---|---|---|
| P0 定目标 | 无 | 写 `want_on`/`control_seq` | 生成唯一 reconcile effect（占 I7 惯性槽） |
| P1 begin | want_on ∧ 无 open episode | resolve 全部 requires → 开 episode（reloading）→ 写 activation pin | 生成下一阶段 reconcile |
| P2 iter | episode reloading | 注册**一批** contribution（一次事务内，数量有界：≤ 32 条） | iterator 前进；若还有剩余，生成下一阶段 |
| P3 divert 检查 | 每阶段边界 | 比较实时 resolve 出的 target 映射与 committed_view | 不等 → 转 closing（记 `outcome='divert'`，**不 apply inverse**）；相等 → 继续 |
| P4 finish | iterator 空 | episode→active（激活代次即 episode.epoch） | 无后继（或被扫描触发新的差异） |
| P5 leave | target→⊥ ∨ 依赖失效 | 撤可见性 + episode→closing | 生成唯一 cleanup reconcile |
| P6 unload | 屏障满足 | seq DESC apply inverse（撤销 L-Iter／L-Divert／L-Raise 携带下来的全部 accumulator）+ close episode | 结算；无后继 |

[规格] `deferred` 只在 P6 屏障未满足时出现，且**零写**：不推进 iterator、不写 withdrawn_at、不改 episode.state，直接释放 G 与事务。等待屏障必须结束事务，不得持 G 轮询。

[规格] **L-Divert 与 L-Raise 都不 apply accumulator**：两者只写控制字段（Ψ = id_Γ 或 pr₁∘i，论文 Table 1），把已累积的 inverse 留给 L-Unload。论文 §4.3.3 明确 L-Divert「routes through Unloading rather than applying the accumulator where it stands」，§4.3.4 的 L-Raise 同样只把 error 作为 outcome 带入 Unloading，「the accumulator built up to the failing iteration is applied there」——那里的 there 指 L-Unload。因此本设计中 closing 是一个**携带 accumulator 的等待态**，不是一个「已经撤干净」的状态；§11 的崩溃恢复依赖这一点：kill 在 closing 与 L-Unload 之间不掉数据，因为 inverse 还在 contribution 行里。

[论证] 「一次事务内一批 contribution」而非「一条一事务」的理由：论文 §4.3.2 的 L-Iter 是单步关系，但一次迭代可以注册多个组件（Definition 47 的 register 是组件级）；有界批量（≤32）保留了「阶段边界可插入 L-Divert」的性质，同时把事务次数从 O(贡献数) 降到 O(贡献数/32)。若某插件的 contribution 数超过 32，仍可分多阶段完成，正确性不依赖批量大小。

### 5.3 一次完整走查

[规格] 符号样例，不是本轮数据库操作。初始：scope S→root realm；tool fiber T 已激活（`ep_T.epoch=1`），contribution `t=(root, tool.echo, T, ep_T, service)`；agent fiber A 属 root owner，want_on=true、无 open episode，硬依赖 `[model, tool.echo]`，policy=chat_tool；model fiber M 已 installed 未激活。`P(A1,k,x)` 是 A 在 ep_A1 的 activation pin；`P(r,k,x)` 是 run r 的 pin；w/l 是 withdrawn_at/released_at。

[规格]

| 步骤 / effect | 行变更 | 后继与可见性 |
|---|---|---|
| e1 `install(M,S,owner=root)` | `installs` + `fibers`（want_on=false）；无 contribution | 安装不等于激活；A 仍是派生 pending（缺 model） |
| e2 `reconcile(M)` P0 | M.want_on=true, control_seq=1 | 生成 e3（占 M 的 I7 槽） |
| e3 `reconcile(M)` P1 | M.ep1（reloading, ω=∅）；M.current_episode_id=ep1 | 空 inject 满足，iterator 空 |
| e4 `reconcile(M)` P4 | ep1→active（ep1.epoch=1）；插入 `m=(root, model, M, ep1, service)` | resolve(S,[model])→m；扫描发现 A 可推进 |
| e5 `reconcile(A)` P1 | A.ep1（reloading）；插入 `P(A1,model,m)`、`P(A1,tool.echo,t)` | A 此刻无 run，M 也不能绕过 A 释放 m |
| e6 `reconcile(A)` P2/P4 | 注册 A 的 contribution（本例：一条 service `a=(root, agent.chat, A, ep1)`）；ep1→active（ep1.epoch=1） | A active；生成 e7 run_start |
| e7 `run_start(A,input,budget=3)` | live 复验；插入 r（owner=A1）；按 ep1 绑定 `P(r,model,m)`、`P(r,tool.echo,t)` | 生成 e8 `model_call(m)`，输入冻结且含 pin 引用 |
| e8 → IO → `ok(tool.echo,args)` | 先 claim/COMMIT，宿主外呼，advance 接纳；r.state 保存决策，budget 3→2 | reducer 只能选已有 run pin 中的能力；生成 e9 `tool_call(t)` |
| e10 `reconcile(M)` P0 | M.want_on=false, control_seq=2, M.retire_started_at, `m.w=now`；`m.l` 仍空 | 新 resolve 无 model；A 的 live 立即为假，拒新 run；旧 r 继续用 m |
| e11 `reconcile(A)` P5 | 依赖失效：A.retire_started_at，`a.w=now`，A.ep1→closing | 生成唯一 e11c cleanup(A) |
| e11c `reconcile(A)` P6 | 被 r 挡住 → **deferred，零写** | 释放 G；不创建第二条 cleanup |
| e12 `reconcile(M)` P6 | 被 `P(A1,model,m)` 挡住 → deferred，零写 | 同上 |
| e13 → IO → `ok(final)` | 原 r 的 pin/epoch 仍有效，接纳；budget 1→0；r.ended_at/result；删两条 run pin | 不重新 resolve 改绑；r 结束不自动删 A1 的 pin |
| 重交 e11c | r 已空；删 `a` 的两类引用后删 activation pin；A.ep1 closed，current_episode_id=NULL，retire_started_at=NULL | e11c 结算；A.want_on 仍真但缺 model → 派生 pending，无持久 pending 任务 |
| 重交 e12 | m 无消费者 pin；`m.l=now`；M.ep1 closed，M.retire_started_at=NULL | e12 结算；旧行历史保留，唯一地址释放 |
| e14 `dispose(M)` | M.dispose_requested_at、disposed_at；installs.state=disposed | 不可 retry M；T 保留；A 仍 pending——inject 缺失不等于 owner 被 dispose |

[规格] 清理顺序固定：先退出 child/consumer，再清本 fiber 的 contribution，最后删其 inject pin；contribution 释放须引用数为零（I3）。dispose 活父时，祖先 dispose 谓词立即封住后代新准入，逐个子 effect 清理，父最后墓碑化；不一次生成无界子树。

[规格] 反激活后立刻再 activate 只改最新目标；旧 m 仍 withdrawn，待上述屏障清完才允许新 provider 占位（不接受切换空窗内的双版本）。激活失败回滚所有新增 contribution 并记 failure；retry 增 control_seq，不是复活 disposed 实例。

## 6. 可逆账本与反应式 coeffect

### 6.1 可逆账本：contribution + 闭集 inverse

[规格] 每次注册／覆盖／子 fiber 创建 = 一条 contribution，带 `seq` 与 `inverse`。撤销按 `(episode_id, seq DESC)` 逐条 apply；每条 inverse 是闭集 op，advance 提交前检查后置条件：

| inverse | 适用 kind | 后置条件（advance 提交前检查） |
|---|---|---|
| `delete_row` | service, listener, child | 行不存在；若为 service 且持有唯一地址，该地址无其他 live 占用 |
| `restore_prev` | cell | 当前值行被删，`prev_contribution_id` 指向的行重新可见且描述符等于 prev |
| `release_reservation` | reservation | 额度回到预留前；无活 pin 引用该 reservation |
| `dispose_child` | child | 子 fiber 已 disposed（墓碑）或无活义务 |
| `unknown` | 任意（外部资源） | **不检查**；计入显式债务，见 §6.2 |

[规格] 不得把「任意 disposer/闭包」塞进 JSON 冒充可逆。`inverse` 的取值域是上表闭集加 `unknown`，schema 层 CHECK 拒绝其他值。

[论证] 与 v1 稿的差异：v1 稿称「贡献只允许追加 slot／子 fiber，不覆盖共享旧值，不需通用逆程序」。本稿需要 `restore_prev`（cell 覆盖）与 `release_reservation`，因此通用到闭集；但**仍不承认任意 disposer**，收窄的判据是「后置条件可在同一事务内由 SQL 验证」。

### 6.2 unknown 债务

[规格] 外部资源（真实文件句柄、外部服务会话）的撤销无法在事务内验证，标 `inverse='unknown'`，并强制携带 `debt` 描述：资源标识、补偿动作声明、是否已授权重放。advance 允许提交，但在 §12 的债务清单中显式列出。

[边界] 不声称已证明含 `unknown` 的 episode 满足 Recovery Exactness；§7.2 的前提 P2 显式排除含 `unknown` 的 contribution，此时只保证 LIFO 顺序被尝试，不保证状态复原。

### 6.3 pin 是 coeffect demand，live 是派生谓词

[规格] `installs.manifest->'requires'` 是 spec d。L-Begin 时对每个 key resolve 并写 pin，pin 冻结 `(contribution_id, provider_episode_id, provider_epoch, seq)`——即「本 consumer 在这一代依赖哪一个具体的提供者贡献」；`provider_epoch` 即 Appendix A 的 `pins.provider_epoch` 列。

[规格] fiber 的 live = 所有 activation pin 仍指向未 `released_at` 的 contribution ∧ 各 provider 的 episode 未 closing ∧ `want_on` 为真 ∧ check 谓词通过 ∧ owner 未 disposed。任一为假 → 该 fiber 不 live → 触发 L-Leave/L-Unload 路径。

[规格] 两段式释放：provider 的 `withdrawn_at` 只阻**新解析**；`released_at` 必须等该 contribution 的活 pin 归零。因此旧 pin 在消费者排空期间仍可读（论文 §4.4.3 Th 63 的 consumer can still read k throughout teardown）。

[规格] 反应式机制：**没有 watch 表、没有 notify 队列、没有 revision 失效广播**。宿主维护循环公平扫描 fiber 的目标/live 差异与未结算 reconcile effect，复用唯一惯性槽（I7）。唤醒可丢，事实不可丢。

[论证] 活性前提必须显式写成假设，因为 DB 不强制公平性：

| 代号 | 假设 |
|---|---|
| E1 | 宿主维护循环在有限时间内扫描每个 fiber 至少一次（公平扫描） |
| E2 | 宿主在 finite time 内提交已 claim effect 的 outcome（或显式标注 unknown 并进入对账） |
| E3 | 每 fiber 的 reconcile 阶段序列有限收敛（无外部资源永久阻塞屏障；若阻塞，安全地停在 deferred，不谎报完成） |

[论证] E1–E3 是 §7.5 Progress 的前提，不是 DB 能证明的性质。这是本设计相对 DSH 的实质差异：DSH 的 notify 由微任务队列保证，本设计换成扫描保证，代价是延迟上界由宿主循环周期决定，不是由事件推送决定。

### 6.4 事件：listener contribution + dispatch effect

[规格] 事件面三件套，全部落在已有结构：

1. **listener 是 contribution**：`kind='listener'`，descriptor 含 `event`、`mode`、`priority`、`filter`、`exec`。注册与撤销走同一可逆账本。
2. **dispatch 是 effect**：`kind='dispatch'`，`input` 含 event 名、参数、模式，提交后不可变。**不存 cursor、不存 acc**：进度由已结算的 `listener_call` 子行派生——`next_ordinal = max(settled ordinal) + 1`、`joined = count(settled children)`、`acc = fold(children.outcome ORDER BY ordinal)`。dispatch 未结算时没有 outcome 行，状态不可能寄存在 outcome 上；`effects.input` 在 v24 又不可变，故两者都不能当游标。
3. **listener_call 是子 effect**：每个被调 listener 一条 `kind='listener_call'`，`ordinal` 决定调用顺序（priority 降序，同 priority 按 contribution seq 升序）。`UNIQUE(parent_id, ordinal)` 使同一 ordinal 不会被调用两次，这是幂等恢复的锚点，也是进度派生的基数来源。

[规格] 五种派发模式的语义，逐一定义：

| 模式 | 论文/DSH 语义 | 本设计落点 | 同步性 |
|---|---|---|---|
| `emit` | 不等待结果（`C/events.ts:32` 的 `DispatchMode`） | dispatch effect 生成全部 listener_call 子 effect，不等其结果即 settled；后续由各子 effect 独立 advance | 异步 |
| `parallel` | await 全部 listener | 一次生成全部 listener_call 子 effect；每个子 effect 结算后 advance 重算 `joined`，等于计划的 listener 数时结算 dispatch 并写 acc | 异步精化 |
| `serial` | 顺序 await，首个 bail 停 | 只生成 ordinal 最小的未调用者；每个子 effect 结算后 advance 派生 `next_ordinal`，再生成下一条或结算 dispatch | 异步精化 |
| `bail` | 顺序，首个 bail 值短路 | 同 serial；任一子 effect 的 outcome 命中 bail 谓词时 advance 直接结算 dispatch，不再派生 `next_ordinal` | 异步精化 |
| `waterfall` | `next` 续延，后者接前者的值 | **v2 显式边界**：需要同步 next 栈，DB 事务内不可复刻。落点为「串行链 + acc 传递」：advance 从已结算子行 fold 出 acc，作为下一条 listener_call 的 input 传入。不承诺 next 的同步调用栈语义 | 收窄 |

[规格] 同步／异步二分：listener 分 `exec ∈ {in_db, host}`。`in_db` listener 是受控 SQL 谓词或 reducer，在 advance 内同步执行，`listener_call` 无外呼；`host` listener 变成子 effect，由宿主执行。

[规格] **refinement 命题**（§7.6 展开）：在 listener 步独立 + 公平调度（E1–E3）前提下，异步 dispatch 的可观测结果（acc、join 计数、被调用集合）与同步参考语义一致；不满足前提时列为偏差，主要是 `waterfall` 的 next 栈与 `emit` 的排序保证。

[边界] 不做：DSH 的 `thisArg` 绑定、listener 抛错中断整个 dispatch（本设计 listener 失败 = 该 listener_call 的 error outcome，dispatch 继续，除非模式是 bail）、同步 disposer 链。

### 6.5 isolation 与 interception

[规格] isolation：`scopes.realm_overrides` 在 resolve 时沿祖先链合并，近者优先；缺省继承，根缺省共享 root realm。realm 是解析隔离，**不是 ACL**。

[规格] interception：`scopes.intercept jsonb` 在 resolve 时合并，可对 `(realm,key)` 声明「替换 descriptor digest」或「拒绝」。合并规则与 realm_overrides 同构（近者优先，本 scope 显式项覆盖祖先）。

[论证] 论文 §3.2.3 的 interception 在 DSH 中是 Proxy 层的运行时改写；本设计把它降到 resolve 时的数据合并，因此 interception 只能改**描述符**（下游据此选择 adapter/contract version），不能改已执行的计算。这是收窄，不是等价。

[规格] 授权不在此列：role/grant + advance 的 principal 认证承担授权；scope 不是授权域（R8，v1 稿 §1 同裁决）。

### 6.6 事件与工具调用的关系

[规格] agent 回路的 model/tool 调用**不**伪装成 dispatch。它们直接是 `model_call`/`tool_call` effect。事件面服务于「插件观察 harness 事件」这一独立需求，两者共用 effect 通道但不互相依赖。这守住 v1 稿「不为了工具调用先造 dispatch 子系统」的边界。

## 7. 六个命题：陈述、前提、机制、证明草图、gate、反例

### 7.0 读法

[规格] 每条命题给六项：陈述（论文原文要点的文字复述）、前提、DB 机制、证明草图、gate、前提不成立时的反例。**不声称机器证明**；全部是证明草图与证明义务。

### 7.1 Preservation（论文 §4.4.1, Th 59）

[规格] **陈述**：若 registry F^t well-formed（论文 Definition 58 的四条款），则任一规则步后 F^{t+1} 仍 well-formed。

[规格] **well-formed 的四条款**（Definition 58，逐条给出 DB 机制）：

| 款 | 论文要求 | DB 机制 |
|---|---|---|
| (1) | 每个 parent 指针落在 dom(F) ∪ {root} | `fibers.owner_id` 自引用 FK + 「唯一 root 的 owner 为空」CHECK；root install 的两列配对为空 |
| (2) | 不同 fiber 的 provisions 不相交 | 部分唯一索引 `contributions_service_addr`（`UNIQUE(realm,key) WHERE kind='service' AND released_at IS NULL`，I1） |
| (3) | installed_n ⇒ ω_n 对 d_n total 且取值在 dom(F) | L-Finish 时逐 key 校验 `committed_view` 覆盖 `manifest->'requires'` 全集，且每个 value 指向一个 live contribution；不满足则 L-Raise |
| (4) | installed consumer m 把 k 解析到 n ⇒ installed_n | pin 写入口校验 provider contribution 属于 open episode 且 provider 未 disposed；provider dispose 谓词立即封住新 pin |

[规格] **前提**：P1.1 每条规则的 precondition 由 advance 校验；P1.2 所有写入经 advance（I8）；P1.3 schema 约束（FK/UNIQUE/CHECK）在事务提交时全部满足。

[规格] **机制**：三层，逐层对应四条款。

1. 单行层（覆盖款 1、款 2）：§4.3 的 UNIQUE/CHECK/FK（`contributions_service_addr`、consumer 严格 XOR CHECK、墓碑 CHECK、owner 自引用 FK）。
2. 跨行层（覆盖款 3、款 4）：L-Finish 的 totality 校验、pin 写入口的 provider-installed 校验、delta footprint 校验（§3.4 的 ownership/confinement/闭集/有界）+ 清理 DAG 无环。
3. 兜底层：DEFERRABLE 约束触发器在 COMMIT 前复查 §4.3 记录的跨行口径。

[规格] **证明草图**：对十条规则逐一归纳，每步只证「被写到的那些条款仍成立」。O-Insert 只写 `installs`/`fibers`/`scopes` 新行：款 1 由新行的 owner FK 满足，款 2/3/4 在新 fiber 尚无 contribution 与 pin 时 vacuously 成立。L-Iter 只写 `contributions` 新行：款 2 由 `contributions_service_addr` 的唯一性保证（P1.3）；款 3 尚不要求（episode 仍 reloading）；款 4 由「本 fiber 自己的 contribution 不属于任何他人的 pin 目标」平凡成立。L-Finish 是唯一使款 3 变非平凡的一步，故 totality 校验必须落在这一步而不是 L-Begin。L-Unload 删行或置 `released_at`：款 2 因地址释放而保持，款 4 因 pin 已清零（屏障）而保持。归纳步的关键是「每条规则只写它声明的列」——这正是论文 Table 1 第五列「control fields edited」的内容，本设计把它实现为解释器的白名单写集。

[规格] **gate**：G1（§10.2）注入每条规则的边界，检查无部分提交；对四条款各构造一条越界 delta——款 1 造悬空 owner、款 2 造同址双 live service、款 3 造 `provides[]` 缺项的 L-Finish、款 4 造指向 disposed provider 的 pin——advance 必须拒绝且零写。

[规格] **反例**：若 P1.2 破防（宿主获得裸 DML 路径，例如直接 `UPDATE fibers SET want_on`），则 O-Retire 的 τ 写入绕过 G，两个 fiber 可并发制造环形 owner/pin 图而 DAG 检查看不见。此时 Preservation 失效。

### 7.2 Temporal / Recovery Exactness（论文 §4.4.2, Th 61；推论 Cor 62）

[规格] **陈述**（论文 §4.4.2, Th 61 的准确形式）：设 episode [b,u] 属于 fiber n，步序列 pairwise independent，则把 n 在本 episode 累积的 accumulator 作用到关闭时的状态，其结果 ≈ **把本 episode 的各步从序列中删除后的反事实状态**：

```text
g_n^u(γ^u) ≈ (Ψ^{t_l} ∘ … ∘ Ψ^{t_1})(γ^b)
```

即「撤销后的状态」与「这些步从未发生过的状态」在 ≈ 下相等。Cor 62（terminal recovery）是 episode 以任意结局关闭时的特例。**这不是「≈ 字面上的初始状态」**：若另一个 independent fiber 在 [b,u] 内注册了某个 key，反事实状态里该绑定**存在**，字面初始状态里**不存在**——两侧 σ 不同，此时 ≈ 只对反事实状态成立，对字面初始状态不成立。

[规格] **前提**：P2.1 本 episode 的 contribution 的 inverse 全在闭集（无 `unknown`）；P2.2 步序列 pairwise independent；P2.3 episode 期间 Γ 中被其他 fiber 绑定的 key 未被本 fiber 覆盖（single-source 纪律）。

[规格] **机制**：`contributions.seq` + `episodes` 作为 accumulator + LIFO apply + footprint confinement（§3.4 第 2 条）。

[规格] **证明草图**：accumulator 由 `(fiber_id, episode_id, seq)` 隐式定义，无需存闭包列表。L-Unload 时按 seq DESC 逐条 apply inverse，第 k 条的后置条件由 §6.1 的检查保证；由于 confinement，其他 fiber 的 delta 不写本 fiber 的行，故 apply 顺序不受外部交错影响（这是 P2.2 被强制成立的技术理由，见下）。

[规格] **≈ 用在哪一步**：比较基准是**删除本 episode 各步后的反事实序列**，不是字面初始状态。撤销完成后两侧的 σ 逐项相同，理由分两半：(a) 本 fiber 注册的每条 contribution 已删除或已 `restore_prev`，其写出的每条 activation pin 已删除，故**本 fiber 的绑定在两侧都消失**；(b) 其他 fiber 在 [b,u] 内注册的 binding，在反事实序列中仍然发生（被删的只有本 episode 的步），在撤销后的状态中也仍然在（confinement 保证本 fiber 的 delta 不碰它们的行），故**其他 fiber 的绑定在两侧都存在**。允许不同的是**控制字段**：episode 身份与历史（新开又关了一个 episode）、target、accumulator（已清空）、dom(F) 的记录。论文的 ≈（§4.4.1 eq. 52–53）遗忘的正是这部分，而不是「未绑定的 key」。

[论证] 这个区分有实际后果：若把 ≈ 误读成「未绑定 key 可遗忘」，就会放行一种错误实现——撤销时漏删一条无人引用的 contribution，并以「没有 consumer 绑定它」为由声称 ≈ 成立。按正确定义，该 contribution 仍占据 `(realm,key)` 唯一地址（§7.1 款 2），σ 因此不同，≈ 不成立。款 2 与这里的 σ 相等性是同一件事的两面。

[规格] **不讨论全局回滚**：本设计只保证单 fiber episode 的 σ 复原，不保证跨 fiber 的原子回滚；跨 fiber 的一致性由 owner/pin 的清理 DAG 与屏障逐步达成。论文的 Th 61 在 pairwise independence 下也只给出单 accumulator 的复原（§4.4.2），不承诺全局回滚。

[规格] **independence 是强制而非假设**：论文 §3.1.3 与 Th 61 都把 pairwise independence 当前提。本设计中 advance 在 G 下拒绝越界 delta（confinement），因此两个不同 fiber 的 contribution **行级写入域不相交**——它们完全可能写同一张表（都写 `contributions`），只是不写同一行；论文的前提成为本设计的不变量。G 串行化进一步使「交错」退化为提交序，不存在真正的并发控制写。

[规格] **gate**：G2（§10.2）——构造 A 依赖 M，M off→on 交错迟到 receipt 与 A 清理，再让空贡献 A 反复加载；断言旧 epoch 不污染新 A、pin 不提前消失、无未记录的半步 setup。

[规格] **反例**：若 P2.1 破防（contribution 带 `inverse='unknown'` 且 episode 正常关闭），则 accumulator 无法验证复原，Th 61 不成立——此时只能声称「已尝试 LIFO 撤销」，债务进 §12。若 P2.3 破防（两个 fiber 覆盖同一 cell key），则 `restore_prev` 的 prev 指针可能指向已被第三方删除的行，后置条件检查失败，advance 拒绝——表现为功能不可用而非静默错误，这是可接受的失效模式。

### 7.3 Spatial / Ordering（论文 §4.4.3, Th 63）

[规格] **陈述**：fiber 只在其依赖被提供处开始转换（三分：provider 的 episode 严格包含 consumer 的 episode；consumer 在 teardown 全程仍能读 k；provider 的撤离被推迟到 dependents 消失之后，且该推迟最终释放）。

[规格] **前提**：P3.1 pin 在 L-Begin 冻结且不可改绑；P3.2 `withdrawn_at` 只阻新解析；P3.3 `released_at` 等活 pin 归零；P3.4 释放最终发生（否则定理的「eventually releases」失败）。

[规格] **机制**：pin 冻结 + 两段式 withdraw/release + 清理 DAG（child→owner 与 consumer→provider 合并无环）。

[规格] **证明草图**：(1) provider episode 严格包含 consumer episode：consumer 的 L-Begin 要求所有 pin 指向 live contribution，而 contribution 属于 provider 的 open episode；consumer 的 L-Unload 删 pin，provider 才能 close——故 provider 的 close 在 consumer close 之后。(2) teardown 期间可读：`withdrawn_at` 不删行，pin 仍指向该行，resolve 对既有 pin 的访问不经 `withdrawn_at` 过滤（只对新 resolve 过滤）。(3) eventually：屏障检查是「活 pin 数 = 0」，宿主公平扫描（E1）保证消费者最终被 reconcile，故 pin 最终归零。

[规格] **gate**：G2——provider off 后新 run 被拒、旧 run 可排空、无 run 的 activation pin 仍挡 provider 释放；两种树（owner 树、inject 图）独立且混合环被拒。

[规格] **反例**：若 P3.4 破防（宿主停止扫描，或某 run 永久悬挂），则 provider 的 `released_at` 永不置位，Th 63 的「eventually releases」失效。本设计的回应是安全阻塞 drain 而非谎报完成（§11），并把这列为 E1 假设的显式后果。

### 7.4 Spatial / Resolution Coherence（论文 §4.4.3, Th 64）

[规格] **陈述**：设 episode [b,u] 在 ω 开，则 Reloading 区间内的每一次迭代都用 L-Begin 提交的同一个 ω；target 变了就 divert，绝不中途重解析。

[规格] **二分（论文 §4.4.3 对 Th 64 的结论）**：fiber 离开 Reloading 区间时，恰好落入以下两支之一——

| 支 | 规则 | 结局 | 之后适用什么 |
|---|---|---|---|
| (a) | L-Finish | → Active，committed view 就是 ω，**ω 被保持到区间结束** | 无需恢复；激活所用的依赖集合自始至终是同一份 |
| (b) | L-Divert 或 L-Raise | → Unloading（Ψ = id_Γ，不 apply accumulator） | **Corollary 62（recovery）适用**：accumulator 由后续 L-Unload 在屏障满足后 apply，σ 复原到删除本 episode 各步后的反事实状态（§7.2） |

[规格] 两支的共同点是：**区间内每一次迭代都对着 L-Begin 定下的单一 ω 运行**。target 在一次 episode 内变化只可能把 fiber 从 (a) 赶到 (b)，不可能引起区间内的第二次 resolve。

[规格] **前提**：P4.1 `committed_view` 在 L-Begin 后不可变（除 close）；P4.2 每个 reconcile 阶段边界比较**实时 resolve 出的 target 映射**与 `committed_view`，两者同构（required key → provider contribution），含 `want_on` 翻转导致的 ⊥；P4.3 阶段中途不重新 resolve。

[规格] **机制**：`episodes.committed_view` 冻结 + 每阶段 divert 检查（§5.2 P3）+ `fibers.control_seq` 参与比较。

[规格] **证明草图**：iterator 的内容在 L-Begin 时由 target 推导一次并写入 `episodes.iterator`；L-Iter 只消费 iterator 不改写它；阶段边界的比较若发现实时 `target(γ,f) ≠ committed_view` 则转 closing 并记 `outcome='divert'`（**不 apply inverse**，论文 Table 1 的 Ψ = id_Γ），新目标由下一次 L-Begin 重新推导。故任何一次注册所用的依赖集合都是同一个 ω 的快照。

[规格] **gate**：G4（§10.2）——在 reconcile 多阶段之间修改 target，断言不会出现「前半段用旧 ω、后半段用新 ω」的混合激活。

[规格] **反例**：若 P4.3 破防（实现为了「优化」在阶段中途重跑 resolve），则可能出现同一 episode 内两个不同代的 model provider 各注册一部分 contribution，L-Unload 的 LIFO 复原不再对应单一 ω。这属于实现 bug， gate 的任务就是抓住它。

### 7.5 Progress（论文 §4.4.4, Th 66）

[规格] **陈述**（论文 §4.4.4, Th 66 全文）：设 ≺ 无环、每 fiber 的 `len(e_n) ≤ K`、名字集 𝔑（Definition 60）有限，且每步应用论文某规则，则 (1) 非 quiet 时必有某规则可应用（无死锁）；(2) 对任一 fiber n，整个执行上作用于它的步数满足

```text
S(n) ≤ (K + 4) · (V(n) + 1)
```

其中 `V(n)` 是 n 的 target 变化次数。

[规格] `(K+4)·(V(n)+1)` 是**全局上界**；`K+4` 只是它在「target 稳定区间」上的局部版本——论文把一个极大稳定区间内的步数压到 K+4（激活 ≤ K 次 L-Iter，加上有界的 L-Begin/L-Finish/L-Unload/L-Raise 开销），再乘区间数 `V(n)+1`。因此**不能把 K+4 当作定理的全部**：一个反复 off/on 的 fiber，其总步数随 V(n) 线性增长，不是常数。

[规格] 本设计的 `V(n)` 由 `fibers.control_seq` 给出：每次目标变更递增一次，故 `V(n) ≤ control_seq`，上界在 DB 行上可计算。但这不等于有界——控制面可无限次翻转目标，此时 S(n) 无界而 Progress 仍成立（定理只要求上界表达式存在，不要求它小）。

[规格] **前提**：P5.1 ≺（priority）无环，由 advance 在 install 时校验；P5.2 每 fiber 至多一个未结算 reconcile（I7）；P5.3 宿主公平扫描（E1）与及时提交（E2）；P5.4 iterator 长度 ≤ |requires|（有界）。

[规格] **机制**：公平扫描 + I7 惯性槽 + priority 无环 + iterator 有界。

[规格] **证明草图**：(1) 无死锁——设 ¬quiet^t，则某 fiber 既不满足 quiet 第一款（无 open reloading episode）也不满足第二款（target 与 committed_view 一致）；读 Table 1 对应该状态组合的规则必可应用。屏障未满足时本设计返回 deferred 而非阻塞，故 DB 侧不存在「等一个永不到来的事件」的死锁。(2) 步数上界——在 target 稳定的极大区间内，fiber 的状态转移只能是 Inactive→Reloading→Active（K 次 L-Iter，K=|requires|+contribution 数）或 →Unloading→Inactive（有限次清理阶段）；每次转移对应一个 reconcile effect，I7 保证同一时间只有一个在飞，故区间内 ≤ K+4 步；区间数 ≤ V(n)+1，相乘得 S(n) ≤ (K+4)(V(n)+1)。quiet 的判定是「无 open reloading episode 且 target 与 committed_view 一致且无未结算 reconcile」，这三个都由 DB 行直接判定。

[规格] **这是条件定理**：公平性由宿主循环提供，DB 不强制。E1–E3 是外部假设，§6.3 已列。

[规格] **gate**：G3（§10.2）——反复 off/on、断宿主、撤 provider，记录每 fiber 未结算 reconcile ≤ 1、每 advance 后继 ≤ B、**单个稳定区间内步数 ≤ K+4，且总步数 ≤ (K+4)(control_seq+1)**。

[规格] **反例**：若 E1 破防（宿主只扫「队列非空」而漏掉目标变化但无 effect 的 fiber），则出现永久 pending：DB 事实正确但无人推进。v1 稿的教训是「维护循环不只盯队列不空」，本设计沿用一个公平扫描 + 派生谓词的组合。

### 7.6 Confluence（论文 §4.4.5, Th 73）

[规格] **陈述**（论文 §4.4.5, Th 73）：设步序列到达 quiescent γ^T（无 failed fiber）、步 pairwise independent，且支撑集 𝔑 按 Definition 67 取，则任意两个序列在 ≈/≃ 下到达同一范式，等于静态装配。

[规格] **前提**：P6.0 **Definition 67 的支撑集条件**：quiescent 时 𝔑 恰好是 active fiber 的集合——即每个仍 installed 的 fiber 都在支撑集内，且没有已退出（Unloading/Inactive）的 fiber 留在其中。论文由 Lemma 70 从「≺ 无环 + 无 failed fiber + totality（Definition 69）」导出该条件，它不是定理的免费赠品；若支撑集多含一个已退出 fiber，范式比较的对象就错了。P6.1 ≺ 无环；P6.2 contribution add-only + 唯一地址（I1）；P6.3 **total-on-provision（论文 Definition 69）**：当一个 fiber 的激活走完 L-Finish，该 fiber **自己**的 `dom(σ_n)` 必须等于它声明的 `p_n`——`provides[]` 的每个 key 都已 installed。于是任何 consumer 解析 `p_n` 中的 key 时必然找得到它；P6.4 failed fiber 不使 relied 为真；P6.5 G 串行控制写。

[规格] **机制**：G 串行 + I1 唯一地址 + **L-Finish 的 totality 校验** + failure 抑制同 control_seq 自动重试。totality 校验是 P6.3 的落点：L-Finish 逐 key 检查**本 fiber 自己** `provides[]` 中的每个 key 在本 episode 内都有一条 live contribution，缺一项则激活失败（L-Raise，转 closing，**不 apply inverse**，撤销留给 L-Unload），**绝不产生半个 provider**。

[论证] **批量原子性是支撑机制，不是定义**。一批 contribution 在同一事务提交（§5.2 P2，≤ 32 条）使「L-Finish 之后不存在只注册了一半的 episode」更容易成立，但 Definition 69 的要求是 L-Finish 这一步的校验本身；即使批量大小为 1，或一个 fiber 的 provision 跨多个 advance 阶段注册，只要 L-Finish 做了 totality 校验，P6.3 就成立。反过来说，若把 P6.3 定义为「事务原子可见」，则跨阶段的 fiber 会被误判为不合规。

[规格] **证明草图**：局部菱形交换。两个可应用的规则若作用于不同 fiber，其 delta 的写入域由 confinement 保证不交（§7.2），故可交换；若作用于同一 fiber，I7 保证只有一个 reconcile 在飞，顺序由提交序唯一确定。quiescent 时无 open reloading episode，所有 fiber 的 target 与 committed_view 一致。由 P6.0，此时支撑集恰好是 active fiber 集，于是比较范围不含已退出者；由 P6.3，每个 active fiber 的 `dom(σ_n)` 已等于其 `p_n`，故 σ 由活 contribution 唯一确定；≈ 遗忘的是控制字段（episode 身份与历史、target、accumulator、dom(F) 的记录），σ 必须相同；≃ 允许等价描述符。故范式唯一。

[规格] **反例**：若 P6.3 破防（L-Finish 不校验 totality，允许 `provides=[a,b]` 只注册 `a` 就转 active），则该 fiber 自己的 `dom(σ_n)` 缺 `b`，consumer 按 `p_n` 解析 `b` 时得到缺行，quiescent 的定义被破坏——静态装配会直接拒绝该组件，动态装配却放它过去，两者不等价。若 P6.0 破防（一个已 L-Unload 的 fiber 仍被算进支撑集），则范式里多出一个不存在的 fiber，两个序列的「静态装配」参照物不同，Confluence 无从比较。若 P6.2 破防（允许同槽双版本），则 quiescent 时 σ 有两个候选值，菱形不交换。本设计显式拒绝双版本（§4.6、§12），代价是切换空窗。若 P6.4 破防（failed fiber 仍被 relied），则 consumer 的 pin 指向一个 L-Raise 的 fiber，quiescent 定义被破坏；实现上由 `fibers.failure` + control_seq 参与 live 谓词防止。

### 7.7 refinement：异步 dispatch 与同步参考语义

[规格] **命题**：设 listener 步相互独立（无共享 cell 写冲突）、宿主满足 E1–E3，则以 `parallel`/`serial`/`bail` 模式派发同一事件的**可观测结果**（最终 acc、join 计数、被调用 listener 的多重集）与同步参考语义（DSH 的 `C/events.ts` 对应模式）一致。

[规格] **前提**：P7.1 listener 间无数据依赖（除 waterfall 的 acc 链）；P7.2 调度公平；P7.3 listener 不依赖调用顺序以外的同步副作用。

[规格] **证明草图**：同步参考语义是一次事务内按 priority 顺序调用全部 listener；本设计把每次调用拆成独立 `listener_call` effect，由 advance 按 ordinal 依次结算。由于 P7.1，调用次序不影响各自 outcome；acc 的合并若满足交换律（`parallel` 的 join）则与顺序无关。`serial`/`bail` 的短路由 advance 在结算时检查**该子 effect 的 outcome 是否命中 bail 谓词**决定，等价于同步的提前返回。

[规格] **偏差（不满足前提时）**：(a) `waterfall` 的 `next` 是同步续延，本设计的 acc 传递丢失「listener 可选择不调用 next」这一控制权，除非在 listener ABI 中显式建模；(b) `emit` 在同步语义下「全部 listener 已被同步调用」，本设计只保证「全部 listener_call 已被生成」，调用发生在本事务之外；(c) 若 listener 间有数据依赖（P7.1 破防），异步结果依赖调度顺序，与同步语义可能不同。

[规格] **gate**：G4 的事件部分——用 `in_db` listener（确定性谓词）对照同步参考实现，逐模式比对 acc 与被调用集合；`host` listener 只验证「生成、结算、撤销」三态，不断言时序。

[规格] **反例**：若把 `emit` 当作「同步已全部执行」使用（例如 listener 写 cell 后同一事务内读它），则读到的是 dispatch 前的值。这是可观测偏差，必须在使用侧显式禁止：`emit` 的 listener 不得声明对同一 event 的同步读依赖。

## 8. 装载、升级与多语言

### 8.1 声明式装载映射论文 §5.2.1

[规格] loader 的三件套映射：

| 论文 §5.2.1 | 本设计 |
|---|---|
| entry（声明式条目） | `installs.manifest` 的 `requires/provides/priority/scope` |
| config（配置覆盖） | `installs.overlay jsonb NOT NULL DEFAULT '{}'`：同一行的配置覆盖，只改 descriptor 的非身份字段，不改 identity/version/digest |
| overlay（合并） | resolve 时按 overlay 的键路径合并，嵌套深度 ≤ 4；不存在第二条 install 行，故无环可言，也不违反 `UNIQUE(scope_id, identity, version)` |

[规格] 制品内容寻址：`artifact_digest` 是 sha256；同 `(scope_id, identity, version)` 不同 digest 拒绝（v24 稿 §3.2 已有此约束）。install 不执行安装脚本、不自动下载。

[规格] 外部制品需要宿主准备时，install admission 写 `preparing` 并发 `host_io` effect；receipt 经 advance 后 `preparing→installed`，failure/unknown 进 `prepare_failed|prepare_unknown`。CAS 外部引用的物理变化不可能与 PG 原子，commit 前后崩溃靠 reservation 幂等/reconcile 收敛——这是显式债务（§12）。

### 8.2 upgrade / rollback

[规格] 升级 = 新 `installs` 行（新 version）+ 新 fiber + 旧 fiber 走 L-Leave/L-Unload；不是原地改 manifest。回滚 = 再把旧 version 激活一遍，同样走新 fiber。manifest、requires、provides 与 digest 同行不可变，从结构上排除「原名覆盖后仍称旧能力可执行」。

[规格] 升级是**先破后立**，不能反过来：I1 的 `UNIQUE(realm, key) WHERE kind='service' AND released_at IS NULL` 不允许同一地址同时有两个 live provider，所以新 fiber 无法在旧 fiber 仍持地址时完成 L-Finish。顺序只能是：旧 fiber L-Leave（撤可见性）→ 屏障排空（旧 run 与 activation pin 清零）→ L-Unload 释放地址 → 新 fiber L-Begin/L-Finish 占位。代价是**切换空窗**：窗口内该 key 无 live provider，新 resolve 失败、旧 pin 可排空。这正是 §12.3 已列明的「接受切换空窗」，不是疏漏；想要无空窗就需要同槽双版本，那会破坏 Confluence 的 P6.2（§7.6）。

### 8.3 HMR：显式边界

[规格] HMR 落点为「制品版本切换 + 旧 episode 排空 + 新 episode 装载」，即 §8.2 的 upgrade 路径加一个宿主侧的文件监视触发器。

[边界] **不承诺 ESM 级热替换**。依据：论文 §5.2.2 自己说明 HMR 是 illustrative 而非规范义务；DSH 的 HMR 依赖 ESM module cache 失效（`vendor/hmr/src/index.ts`），数据库内没有可失效的模块缓存等价物。DB 侧可复刻的只有「哪一版制品对应哪一 episode」，不可复刻的是「同一进程内替换函数定义而不丢状态」。因此本设计只承诺**带排空的版本切换**，状态保持类 HMR 明确不做。

### 8.4 多语言 handler ABI

[规格] 保留 versioned handler ABI（v24 稿 §6 的 line-JSON 形态）：每条 request/response 一行 JSON，`contract_version` 进 descriptor 并参与 resolve 的相等性判定（§2.5）。

[边界] 不承诺 JS 闭包、对象身份、prototype 链、同步 `next` 栈。论文 §6.4 的语言独立性是设计目标，不是本版实现义务；本版的义务是「任何语言的 handler 只要遵守 line-JSON ABI 就能被同一套 contribution/pin/episode 机制管理」。

[规格] 语言相关的部分只有 adapter：adapter digest 进 `installs.contracts`，advance 只认 digest 不认内容。

## 9. DSH 对照与完备性矩阵

### 9.1 论文 → 本设计

[规格] 状态取值：`满足`（有等价落点）、`强化`（比论文更强）、`收窄`（弱于论文，有理由）、`不做`。

| 论文要求 | 出处 | 落点 | 状态 | 理由／证明 |
|---|---|---|---|---|
| effect context Γ | §3.1.1 | 活 contribution + scope 路由 + committed view | 满足 | §2.1 |
| revertible effect function (f,g) | §3.1.2 | `inverse` 闭集 op | **强化** | 论文信任作者提供的 g；本设计只承认可验证的 g（§6.1） |
| independence of effects | §3.1.3 | footprint confinement | **强化** | 论文是 pairwise 假设；本设计由 advance 强制（§7.2） |
| iterator / 多步 effect | §3.1、§4.3.2 | `episodes.iterator` + 有界批量 L-Iter | 收窄 | 一次 advance 内批量 ≤ 32；不承认任意长的同步迭代 |
| coeffect spec d | §3.2.1 | `installs.manifest->'requires'` | 满足 | §6.3 |
| notification | §3.2.2 | 派生 `live` + 公平扫描 | **收窄** | 无推送层；代价是延迟上界由扫描周期决定（§6.3） |
| isolation | §3.2.3 | `scopes.realm_overrides` | 满足 | §6.5 |
| interception | §3.2.3 | `scopes.intercept jsonb` | 收窄 | 只能改描述符，不能改已执行计算（§6.5） |
| unified context | §3.3.1 | Γ 是库，effect 与 coeffect 共用同一 contribution 账本 | 满足 | §2.1、§4.4 |
| observational equivalence ≃ | §3.3.2 Def 33 | ≃_k（单 key 实例化）+ σ 层相等性 | **收窄** | 整状态 ≃ 需 dom(F) 与控制字段一致，本设计只实例化到 key 级（§2.5） |
| 十条规则 | §4.2–4.3 Table 1 | §5.1 逐条 | 满足 | §5.1 |
| Preservation | §4.4.1 Th 59 | 三层约束 + advance，锚定 Def 58 四条款 | 满足 | §7.1 |
| Temporal / Recovery | §4.4.2 Th 61, Cor 62 | seq + episode + LIFO | 满足（P2.1 排除 unknown） | §7.2 |
| Spatial / Ordering | §4.4.3 Th 63 | pin 冻结 + 两段释放 | 满足（P3.4 依赖 E1） | §7.3 |
| Spatial / Resolution Coherence | §4.4.3 Th 64 | committed_view 冻结 | 满足 | §7.4 |
| Progress | §4.4.4 Th 66 | 公平扫描 + I7 | 满足（条件） | §7.5 |
| Confluence | §4.4.5 Th 73 | G 串行 + I1 + L-Finish totality（Def 69） | 满足 | §7.6 |
| effect tracking | §5.1.1 | `effects` 账本 | 满足 | §4.2 |
| coeffect operations | §5.1.2 | pin 派生 live，无运行时 op 表 | 收窄 | 同上 notification |
| component lifecycle | §5.1.3 | 三解释器 + episode | 满足 | §3.3、§5 |
| context access | §5.1.4 | `resolve(scope_id, keys)` STABLE 只读 | 收窄 | 不提供 get 逃生口（v1 稿 §4 A3 改写） |
| loader entry/config/overlay | §5.2.1 | §8.1 | 满足 | §8.1 |
| HMR | §5.2.2 | 制品版本切换 + 排空 | **收窄** | 论文自述 illustrative；无 ESM cache 等价物（§8.3） |
| boundary / security | §6.1–6.3 | realm≠ACL、禁裸 DML、单宿主 | 收窄 | 不承诺沙箱与多租户（§12） |
| language independence | §6.4 | line-JSON ABI + adapter digest | 收窄 | 设计目标非本版义务（§8.4） |

### 9.2 DSH Cordis → 本设计

[规格] DSH 源码基准：`C/reflect.ts`（provide/resolve/isolate/intercept）、`C/fiber.ts`（状态机、effect、unload）、`C/events.ts:32`（`DispatchMode`）、`vendor/loader/src/config/entry.ts`、`vendor/hmr/src/index.ts`。

| DSH 行为 | 本设计等价物 | 差异 | 影响可观察语义？ |
|---|---|---|---|
| 插件即 Service（`apply`/`dispose`） | `installs.manifest` + `contributions` + `episodes` | 无代码执行，只有声明与行 | **是**：不能跑任意 apply |
| Context 是 Proxy 容器 | Γ 是数据库行集合 | 无对象、无闭包 | **是**：§2.5 |
| inject 硬依赖，ACTIVE + check | `installs.manifest->'requires'` + pin + `live` 谓词 | check 限受控只读谓词 | 否 |
| typed events 五模式 | contribution(listener) + effect(dispatch) + listener_call | 异步精化；waterfall 收窄 | **是**：§6.4、§7.7 |
| `ctx.effect` 逆序释放、幂等 disposer | `inverse` 闭集 + seq DESC LIFO | 闭集限制、unknown 债务 | 否（对外部资源是） |
| disposer 错误不阻断后续 | L-Unload 逐条 inverse，失败记 outcome 继续 | 等价 | 否 |
| Fiber 六态 PENDING/LOADING/ACTIVE/FAILED/UNLOADING/DISPOSED（`C/fiber.ts:144–153`） | 派生状态（§4.6） | 论文十规则四态；FAILED 由 `fibers.failure` 表达，不设为独立持久态 | 否 |
| loader 声明式 entry + overlay | `installs.manifest` + `installs.overlay` | 等价 | 否 |
| HMR | 制品版本切换 + 排空 | **无 ESM cache 失效** | **是**：无状态保持热换（§8.3） |
| scope filter / isolate / intercept | `realm_overrides` + `intercept` | 只能改描述符 | **是**：无运行时 Proxy 改写（§6.5） |

### 9.3 五个 DB 原生不可复刻点（红项）

[规格] 逐一点名，给边界，不给等价性承诺：

| # | DSH 能力 | 为什么 DB 不可复刻 | 本设计边界 |
|---|---|---|---|
| R1 | **同步 disposer 链** | disposer 是 JS 函数，可能在事务内做 IO；持 G 跨 IO 违反 §3.5 | 外部资源的 disposer 只能在事务外由宿主执行，对应 `inverse='unknown'` 债务；事务内只做行撤销 |
| R2 | **ESM 级 HMR** | 无模块缓存可失效；PG 无「替换函数定义不丢状态」 | 只做带排空的版本切换（§8.3） |
| R3 | **对象身份与活引用** | 行没有身份连续性；MVCC 每次读是新版本 | 用 `(contribution_id, provider_episode, digest, contract_version)` 四元组替代身份（§2.1） |
| R4 | **prototype 链 / 动态方法** | descriptor 是 jsonb 数据，无方法表 | 能力是「地址 + contract_version」，调用经 adapter；不提供运行时扩展方法 |
| R5 | **同步 `next` 栈（waterfall）** | next 是同步续延，跨事务无法保持调用栈 | acc 链传递；丢失「listener 可弃权不调 next」的控制权（§6.4、§7.7） |

[规格] 这五条是本设计**失去的能力**，不是待补的缺口。凡需要它们的插件形态（有状态闭包、进程内热修、同步中间件栈）不在 v2 支持范围内。

### 9.4 完备性结论

[规格] DSH 五个核心概念（Service/Context/inject/events/effect）全部有落点；五种派发模式全部定义，其中 `waterfall` 为显式收窄；loader 有等价物；HMR 有收窄等价物。红项 5 条已在 §9.3 列名。据此声称「功能完备」的准确表述是：**在声明式、数据化、单宿主、受信主体这四个前提内完备**；超出即超出。

## 10. 紧凑实现：预算、四个 gate 与施工切片

### 10.1 紧凑性预算

[规格] 数字口径（实现完成时复核，超支即失败）：

| 项 | 预算 | 说明 |
|---|---|---|
| 领域表 | **8** | §4.1；簿记表 `events`/`requests` 另计，不计入领域表 |
| 领域 SQL 文件 | 8 | 一表一文件 + `load.py` 顺序登记 |
| 生命周期解释器 | **3** | install / fiber_reconcile / dispose（§3.3） |
| reducer | 1（`chat_tool`） | 只读、预部署 |
| 命令 kind | 3（command_install / command_reconcile / command_dispose） | 不含 run_start 与业务 kind |
| advance 内 SQL 行数 | **≤ 1200（历史；DP6 2026-10-28 授权改为仅报告）** | 单一 SECURITY DEFINER 函数体加私有 helper；对照 v24 稿同口径 |
| 领域 DDL 行数 | ≤ 900（历史；DP6 2026-10-28 授权改为仅报告） | 八张表的 CREATE/INDEX/CONSTRAINT |
| 宿主维护循环 | 1 | 公平扫描，无第二调度器 |
| 后继上限 B | 16 | I6 |
| gate | **4** | §10.2 |

[论证] 紧凑性的判据不是行数少，而是**承重面少**：每张表、每个解释器、每个队列都是必须一致维护的状态。本设计的承重面数为 8（表）+ 3（解释器）+ 1（扫描循环）+ 1（锁 G），不随插件数量增长。DSH 的对应承重面是 fiber 树 + effect 栈 + 事件总线 + loader 缓存 + HMR 缓存，其中后两者在 DB 内无对应物也不引入（§9.3）。

[规格] 超支处理（DP1–DP5 历史口径）：若实现时 advance 超过 1200 行，先拆私有 helper 函数（不增加表与 kind）；若仍超，说明有未识别的第五个概念，必须回到 §1 重裁，不得用 JSON 字段偷藏第二状态机（v24 稿 §3.3 同纪律）。

[规格] DP6 容量行数授权（2026-10-28，用户原文：「授权无视容量预算要求」）。该授权覆盖三项行数容量预算：advance 与全部私有 helper 的总行数、`43_loop.sql` 单文件可读性行数、领域 DDL 物理行数；不覆盖 `closure<=512`、`successor<=16`、协议 key/depth、ACL、validator/postcondition、replay 与事务外 IO 等语义边界。自本日起，DP6 仍须实测并报告这三项行数（40–49 全量、43、领域 DDL 与簿记分列），但不再以行数作为 DP6 准入或 gate 失败条件，也不设新的有限行数上限。W1 落实预算/gate 配套时只解除行数上限断言，保留完整文件/manifest 校验（19 项 canonical order、缺失/重复/未登记/符号链接负例）和全部语义负例。历史计量及 DP1–DP5 Result 保留不改；本授权仅适用于 DP6，除非用户另行授权。

### 10.2 四个 gate

[规格] 每项独立可跑脚本、FakeLLM/FakeTool、零网络；阶段完成后按 AGENTS.md 跑全阶段测试并逐里程碑提交。任一反例即失败。

| gate | 覆盖 | done when |
|---|---|---|
| **G1 单提交口** | §3、§7.1 | §5.3 到 e13 闭环可跑；在 receipt／状态／后继每处注入回滚后无部分提交；重复原 receipt 恰一个结算与后继；冲突 receipt／旧 token／未声明能力零写；非法 reducer intent 不能越权写表；IO 时连接非 IDLE 立即失败；裸 DML 被拒（I8） |
| **G2 依赖与撤销** | §7.2、§7.3、§7.6 | 双连接同 realm/key 激活只有一个成功，不同 realm 同名均成功；缺任一 inject 不激活、空 inject 可激活；无关注册不打废 pin；provider off 后新 run 被拒、旧 run 可排空、无 run 的 activation pin 仍挡释放；两种树独立、清理混合环被拒、dispose 墓碑不可复活；同槽双版本被拒 |
| **G3 崩溃后无需第二引擎** | §11、§7.5 | 在 §11 七处 kill 宿主／断开连接，丢光内存与所有唤醒，仅重启扫描即到达预期 r/result、pin/contribution 释放与墓碑；off→on 竞态仍先清后载；每 fiber 未结算 reconcile ≤ 1；每 advance 后继 ≤ B；未获 replay 权利的能力无法安装，未完成外呼不被伪造成功 |
| **G4 事件与 coeffect 精化** | §6.4、§7.4、§7.7 | 五种派发模式逐一定义并测试；`in_db` listener 对照同步参考实现逐模式比对 acc 与被调用集合；listener 撤销走同一账本；多阶段 reconcile 之间改 target 不产生混合激活；intercept 合并近者优先且 depth ≤ 4；overlay 键路径 depth ≤ 4（同行 jsonb，不存在链与环） |

### 10.3 施工切片

[规格] 顺序，每片一个可跑 gate：

| 片 | 内容 | gate |
|---|---|---|
| S1 | 八表 DDL + advance 骨架（锁、replay、validate、delta apply） | G1 的 receipt/回滚部分 |
| S2 | install + reconcile 的 O-Insert/L-Begin/L-Iter/L-Finish | G1 闭环、G2 前半 |
| S3 | pin/live + L-Leave/L-Unload/L-Divert/L-Raise + 屏障 | G2 后半 |
| S4 | run 结算 + reducer + model/tool effect + 预算 | G1 全、G3 前半 |
| S5 | contribution 五 kind + inverse 闭集 + unknown 债务登记 | G4 前半 |
| S6 | dispatch effect + listener_call + 五模式 + intercept/overlay | G4 全 |
| S7 | 崩溃矩阵七点 + 扫描循环 + dispose 子树 | G3 全 |

### 10.4 与 v24 的 diff

[规格] 实现时相对 v24 稿的改动面：

| v24 | v2 |
|---|---|
| `slots` | 改名 `contributions` 并加 `kind`/`inverse`/`prev_contribution_id` |
| `episodes.state` | 收敛为 `{reloading, active, closing}`，论文四态由派生查询表达 |
| 六动词客户端面 | 删除，压为 run 结算 + 事件游标 |
| `scope_control` 命令 | 并入 install |
| `events` 表 | 降为簿记，不承载决策 |
| 新增 | `scopes.intercept`、`installs.overlay`、`installs.priority`、`contributions.inverse` |

### 10.5 与 v1 稿的 diff

[规格] §1.3 已逐条列出。实现层面的净变化：多一张表（episode）、多四类 contribution（listener/cell/reservation/child）、多一个 dispatch effect kind、少一个「无 episode」假设。

## 11. 崩溃矩阵

[规格] 单宿主维护循环公平扫描所有 fiber 的目标/live 差异与未结算 effect，复用唯一 reconcile 惯性槽；不只盯「队列不空」。扫描／唤醒可丢，事实不可丢；等待屏障必须结束事务。重跑 resolve + 未结算 effect 就是恢复入口，不需要持久 notify 或宿主内存恢复计划。

[规格]

| kill 边界 | 数据库留下什么 | 重启动作／收敛条件 |
|---|---|---|
| install／激活事务内、COMMIT 前 | 整笔回滚，或完整已提交行；没有半个 episode／contribution／pin | 查原 effect receipt；未结算则重交 apply，已结算 replay |
| 激活已 COMMIT、扫描 A 前 | M1/ep_M/contribution m 已在，A 尚无 open episode | 全量公平重跑 resolve 发现 A 可激活，提交唯一 reconcile；不依赖 notify 曾送达 |
| L-Iter 批次中途、COMMIT 前 | 该批 contribution 全部回滚，iterator 未前进 | 重交同 reconcile；seq 可重用（事务回滚后不承诺无空洞，与 v24 稿 §3.1.9 同口径） |
| claim COMMIT 后、外呼前／中／返回后但 receipt 未提交 | effect 有 token/lease，pin 仍在；DB 不知道外呼是否发生 | 有可信 receipt 就仅重交 advance；否则按**显式 replay 合同**在资格到期后重领；旧 token 不再有发布权 |
| advance 已改 run、尚未追加后继／COMMIT | 同事务全部回滚，不会「结果已消费、工具没入队」 | 用保留 receipt 重交；后继唯一索引防重；COMMIT 回执丢失先查／replay |
| dispatch 半程（部分 listener_call 已结算） | dispatch effect 未结算；进度只存在于已结算的 listener_call 子行，无游标列可丢 | 重交 dispatch 的下一阶段 advance；`next_ordinal`/`joined`/`acc` 由子行重新派生，已结算的 listener_call 由 `UNIQUE(parent_id, ordinal)` 防重，已 fold 进 acc 的部分不重复合并 |
| contribution 已 withdrawn，consumer/provider 尚未清；或 cleanup 已提交、provider cleanup 未提交 | 新可见性已撤；剩余 pin、未结算 reconcile 事实仍在 | resolve 发现失效消费者；先排 run→清 consumer pin→释放 provider contribution，不能提前删 provider |
| dispose 完成 COMMIT 后、宿主未确认 | disposed 墓碑与原 receipt 都在 | replay 原 effect；重启扫描不能把它当 pending 再激活 |

[规格] lease 到期只禁止再凭它发起新 IO，并允许重领；原 token 若尚未被重领替代，可信原结果仍可 T2 提交。重领才递增 attempt、更换 token；两者均在 G 下裁决，不靠时间竞态丢结果。

[规格] 自动 IO 恢复只准合同明确允许重复／并发重投的能力；不是看到 read_only 或「有幂等 key」就推定可重放。v2 拒绝无此权利的外部写工具；模型重复计费、外部 exactly-once 不在保证内。永久 host 故障／悬挂 run 会安全阻塞 drain，不承诺凭数据库猜出完成。租约只撤数据库发布权，不取消已发外呼。

[规格] 事件簿记的崩溃语义：`events` 行与领域变更同事务，故不存在「领域变了但事件没记」；只存在「事件记了但宿主没读到」，这由游标重放解决（`events(entity_type,entity_id,seq)` 单调，回滚后序号可重用，故不承诺无空洞，只承诺无重复可见）。

## 12. 证伪、显式债务与明确不做

### 12.1 三个最可能推翻设计的实验

[规格]

| 可能错处 | 最小实验／判死条件 |
|---|---|
| 「八张表 + episode 一列 committed_view」足以承载真实插件 | 迁移 DSH 一个中等插件（带 cell 状态、listener、跨事务 setup）。若出现「必须存第三份生命周期」「committed_view 必须按值历史化」或「inverse 必须变成任意闭包」，则表预算或闭集裁决失败，须回 §4.5 重开第九张表的论证 |
| 「公平扫描 + 派生 live」足够反应式 | 用 Fake 延迟与高频 off/on，测量 provider withdraw 到 consumer live 变假的延迟分布与扫描周期。若延迟上界不可接受，说明 notification 收窄（§9.1）的代价超出预期，须补一个受控的唤醒通道（NOTIFY + 扫描兜底），不得引入 watch 表 |
| 「异步 dispatch refinement」在真实 listener 下成立 | 构造有数据依赖的 `in_db` listener 组（P7.1 破防），比对同步参考语义。若结果依赖调度顺序且无法用交换律挽救，则 §7.7 的 refinement 命题失败，`parallel` 须降级为「无序、结果多重集相等」的更弱承诺 |

### 12.2 显式债务清单

[规格] 以下已知不闭合，实现时必须在代码与文档中标记，不得声称已解决：

| 债务 | 位置 |
|---|---|
| `inverse='unknown'` 的外部资源复原不可验证 | §6.2、§7.2 P2.1 |
| 外部 CAS 制品的物理变化与 PG 事务非原子 | §8.1 |
| 模型重复计费、外部 exactly-once | §11 |
| 无 replay 权利的外部写能力被拒，支持面收窄 | §11 |
| 公平性（E1）与及时提交（E2）由宿主提供，DB 不强制 | §6.3、§7.5 |
| `waterfall` 的 next 控制权丢失 | §6.4、§9.3 R5 |
| 事件序号回滚后可重用，不承诺无空洞 | §11 |

### 12.3 明确不做

[规格] 以下均不进入 v2：

- 观测等价证明：只保选定逻辑不变量；DSH 微任务／Promise 时序没有迁移。
- 不可信代码沙箱与多租户授权：仅受信主体、窄角色、禁裸 DML；realm 不是安全边界。
- 多宿主／分布式所有权：一个受信 driver，G 串行控制写；不把事务锁包装成分布式租约证明。
- provider 流量切换／灰度／同槽双版本：旧 contribution 释放前新 provider 不能占位，接受切换空窗。
- committed_view 的按值历史化与多代并存：只保当前 episode 的 committed view。
- 状态保持型 HMR、ESM 级热替换。
- 任意 host apply/disposer、同步 disposer 链、跨步共享旧值恢复。
- 同步 `next` 栈与 listener 对 dispatch 的同步读依赖。
- 包管理／热装代码：只有预部署版本化 handler，安装是声明与实例安装。
- v13/v99/v24 全 ABI 与历史 gate 兼容：新内核旁路实现；现有代码与 gate 留原位，不能以旧绿代替新闭环。

### 12.4 结论的硬边界

[规格] 八张表、一个领域提交口，靠贡献身份、依赖冻结与所有权闭合生命周期；少的是可承诺的能力，不是把尚未解决的协议藏起来。本文的每个「满足」都附带前提代号，每个「收窄」都附理由，每个「不做」都在 §12.3 列名。

## 附录 A：DDL 草图

[规格] 只给表、关键列、索引与约束的形状，不写完整 PL/pgSQL，不是可执行脚本。命名与 v24 实现保持连续以便对照。

```sql
-- 领域表 1/8：installs（= plugin）
CREATE TABLE installs (
  id                uuid PRIMARY KEY,
  scope_id          uuid NOT NULL REFERENCES scopes(id),
  owner_fiber_id    uuid CHECK ((owner_fiber_id IS NULL) = (owner_episode_id IS NULL)),
  owner_episode_id  uuid,                       -- FK(owner_fiber_id, owner_episode_id) -> episodes
  identity          text NOT NULL,
  version           text NOT NULL,
  manifest          jsonb NOT NULL,             -- 内含 requires[]/provides[]/priority/check
  artifact_digest   text NOT NULL,              -- sha256
  contracts         jsonb NOT NULL,             -- ABI 版本、handler digest、replay 权利
  policy_ref        text,
  overlay           jsonb NOT NULL DEFAULT '{}',-- 配置覆盖，resolve 时合并，嵌套深度 ≤ 4
  state             text NOT NULL CHECK (state IN
     ('preparing','installed','prepare_failed','prepare_unknown','dispose_pending','disposed')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (scope_id, identity, version)
);

-- 领域表 2/8：scopes
CREATE TABLE scopes (
  id               uuid PRIMARY KEY,
  parent_id        uuid REFERENCES scopes(id),
  realm_overrides  jsonb NOT NULL DEFAULT '{}',
  intercept        jsonb NOT NULL DEFAULT '{}',
  closed_at        timestamptz
);

-- 领域表 3/8：fibers
CREATE TABLE fibers (
  id                   uuid PRIMARY KEY,
  install_id           uuid NOT NULL REFERENCES installs(id),
  owner_id             uuid REFERENCES fibers(id),
  owner_episode_id     uuid,                    -- 与 owner_id 配对的归属代次
  scope_id             uuid NOT NULL REFERENCES scopes(id),
  want_on              boolean NOT NULL DEFAULT false,  -- 请求位；target 由 §2.2 派生，不落列
  control_seq          bigint NOT NULL DEFAULT 0,
  current_episode_id   uuid,                    -- FK(fiber_id, current_episode_id) -> episodes
  retire_started_at    timestamptz,
  failure              jsonb,
  dispose_requested_at timestamptz,
  disposed_at          timestamptz,
  CHECK ((owner_id IS NULL) = (owner_episode_id IS NULL))
);

-- 领域表 4/8：episodes（θ 的持久化）
CREATE TABLE episodes (
  id              uuid PRIMARY KEY,
  fiber_id        uuid NOT NULL REFERENCES fibers(id),
  epoch           int  NOT NULL,
  state           text NOT NULL CHECK (state IN ('reloading','active','closing')),
  committed_view  jsonb NOT NULL DEFAULT '{}',  -- L-Begin 冻结的 ω：required key -> provider contribution
  iterator        jsonb NOT NULL DEFAULT '{}',  -- 剩余位置与已注册上界
  outcome         text CHECK (outcome IN ('ok','error','divert','retire')),
  opened_at       timestamptz NOT NULL DEFAULT now(),
  closed_at       timestamptz,
  UNIQUE (fiber_id, epoch),
  UNIQUE (fiber_id, id)                        -- 供 installs/fibers 的历史身份 FK 使用
);
CREATE UNIQUE INDEX episodes_one_open ON episodes(fiber_id) WHERE closed_at IS NULL;

-- 领域表 5/8：contributions（slots 泛化）
CREATE TABLE contributions (
  id                  uuid PRIMARY KEY,
  fiber_id            uuid NOT NULL REFERENCES fibers(id),
  episode_id          uuid NOT NULL,
  seq                 int  NOT NULL,
  kind                text NOT NULL CHECK (kind IN
     ('service','listener','cell','reservation','child')),
  realm               text,
  key                 text,
  descriptor          jsonb NOT NULL,
  prev_contribution_id uuid REFERENCES contributions(id),
  inverse             jsonb NOT NULL,            -- 闭集 op 或 {"op":"unknown","debt":...}
  contract_version    text NOT NULL,
  withdrawn_at        timestamptz,
  released_at         timestamptz,
  FOREIGN KEY (fiber_id, episode_id) REFERENCES episodes(fiber_id, id),
  UNIQUE (fiber_id, episode_id, seq)
);
CREATE UNIQUE INDEX contributions_service_addr ON contributions(realm, key)
  WHERE kind = 'service' AND released_at IS NULL;                        -- I1
CREATE UNIQUE INDEX contributions_listener_addr
  ON contributions(fiber_id, episode_id, (descriptor->>'event'), (descriptor->>'listener_id'))
  WHERE kind = 'listener' AND released_at IS NULL;

-- 领域表 6/8：pins
CREATE TABLE pins (
  id                   uuid PRIMARY KEY,
  consumer_fiber_id    uuid,
  consumer_episode_id  uuid,
  consumer_run_id      uuid,
  key                  text NOT NULL,
  contribution_id      uuid NOT NULL REFERENCES contributions(id),
  provider_epoch       int  NOT NULL,      -- 冻结时的 episodes.epoch，防跨代串读
  created_at           timestamptz NOT NULL DEFAULT now(),
  released_at          timestamptz,
  CHECK ((consumer_fiber_id IS NOT NULL) <> (consumer_run_id IS NOT NULL)),
  CHECK ((consumer_fiber_id IS NULL) = (consumer_episode_id IS NULL))
);
CREATE UNIQUE INDEX pins_fiber_active ON pins(consumer_fiber_id, consumer_episode_id, key)
  WHERE released_at IS NULL;
CREATE UNIQUE INDEX pins_run_active ON pins(consumer_run_id, key) WHERE released_at IS NULL;
CREATE INDEX pins_contribution_live ON pins(contribution_id) WHERE released_at IS NULL;

-- 领域表 7/8：runs
CREATE TABLE runs (
  id                uuid PRIMARY KEY,
  owner_fiber_id    uuid NOT NULL REFERENCES fibers(id),
  owner_episode_id  uuid NOT NULL,
  scope_id          uuid NOT NULL REFERENCES scopes(id),
  parent_run_id     uuid REFERENCES runs(id),
  spawn_key         text,
  state             jsonb NOT NULL DEFAULT '{}',
  remaining_steps   int  NOT NULL,
  ended_at          timestamptz,
  result            jsonb
);
CREATE UNIQUE INDEX runs_spawn_slot ON runs(parent_run_id, spawn_key)
  WHERE spawn_key IS NOT NULL;

-- 领域表 8/8：effects
CREATE TABLE effects (
  id            uuid PRIMARY KEY,
  parent_id     uuid REFERENCES effects(id),
  ordinal       int,
  fiber_id      uuid REFERENCES fibers(id),
  episode_id    uuid,
  run_id        uuid REFERENCES runs(id),
  kind          text NOT NULL CHECK (kind IN
     ('command_install','command_reconcile','command_dispose','dispatch',
      'listener_call','model_call','tool_call','run_start','host_io')),
  status        text NOT NULL CHECK (status IN
     ('ready','claimed','succeeded','failed','unknown','cancelled')),  -- v24 §2.6 原样
  input         jsonb NOT NULL,
  request_actor text NOT NULL,
  claim_owner   text,
  attempt       int  NOT NULL DEFAULT 0,
  token         uuid,
  lease_until   timestamptz,
  outcome       jsonb,
  settled_at    timestamptz,
  resource_quiesced_at timestamptz,
  UNIQUE (parent_id, ordinal)
);
CREATE UNIQUE INDEX effects_one_model_inflight ON effects(run_id)
  WHERE kind = 'model_call' AND status IN ('ready','claimed');
CREATE UNIQUE INDEX effects_one_reconcile ON effects(fiber_id)
  WHERE kind = 'command_reconcile' AND status IN ('ready','claimed');

-- 簿记（不计入领域表）
CREATE TABLE events (
  event_id     uuid PRIMARY KEY,
  effect_id    uuid REFERENCES effects(id),
  seq          bigint NOT NULL,
  entity_type  text NOT NULL,
  entity_id    uuid NOT NULL,
  event_kind   text NOT NULL,
  payload      jsonb NOT NULL,
  UNIQUE (entity_type, entity_id, seq),
  UNIQUE (effect_id, entity_type, entity_id, event_kind)
);
```

[规格] `episodes` 的 `UNIQUE(fiber_id, id)` 供 `installs(owner_fiber_id, owner_episode_id)` 与 `fibers.current_episode_id` 的外键固定历史身份，绝不引用 `fibers` 的当前投影（v24 稿 §3.2 同纪律）；`contributions` 的 `FOREIGN KEY (fiber_id, episode_id)` 同理依赖它。`pins.provider_epoch` 在写 pin 时从 `episodes.epoch` 取值，与 v24 稿 §3.2「pin provider epoch 必须等于 slot epoch」同口径；advance 在复验时比对二者。部分唯一性一律用 `CREATE UNIQUE INDEX ... WHERE ...` 表达——PostgreSQL 不接受表内联的 partial `UNIQUE` 约束。

## 附录 B：advance 伪代码

[规格] ≤ 20 行，与 §3.2 的顺序一致。

```text
lock G; authenticate caller; lock effect
if accepted receipt exists: compare identity/outcome; return replay
validate command or claim token, pins, episode epoch, schema, budget, B
if DB refresh barrier not met: return deferred                 -- 零写
delta := lifecycle_interpreter(effect) OR reduce(pinned_policy, state, outcome)
validate delta: closed inverses, ownership, footprint confinement,
                cleanup DAG acyclic, <= B successors
apply delta; store outcome and settlement; append deduped successors
return settled                    -- caller COMMIT; no IO here
```

[规格] `deferred` 分支不写任何领域行，直接释放 G 与事务；`replay` 分支零写。两条路径都不产生后继。

## 附录 C：术语表

[规格] 全文统一用法。

| 术语 | 英文 | 定义（本设计口径） |
|---|---|---|
| 贡献 | contribution | 一次可逆注册的行；`kind` 五类；带 `seq` 与闭集 `inverse` |
| 插曲 | episode | 一个 fiber 一次装载尝试的持久化 θ：accumulator（由 contribution 行隐式表达）+ committed view + iterator |
| 已提交视图 | committed view | L-Begin 冻结的 ω；episode 内所有迭代用它 |
| 依赖钉 | pin | coeffect demand：consumer（fiber+episode 或 run）到具体 contribution 的冻结引用 |
| 活性 | live | 派生谓词：pin 全指向未释放 contribution、provider episode 未 closing、目标非 ⊥、check 通过、owner 未 disposed |
| 撤可见性 | withdraw | `contributions.withdrawn_at`：只阻新解析，不删行、不影响既有 pin |
| 释放 | release | `contributions.released_at`：活 pin 归零后才可置位；之后唯一地址才可复用 |
| 逆 | inverse | 闭集 op：`delete_row`/`restore_prev`/`release_reservation`/`dispose_child`，或显式 `unknown` |
| 累加器 | accumulator | 本 episode 已注册 contribution 的 LIFO 序列，由 `(fiber_id, episode_id, seq)` 定义 |
| 提交口 | advance | 唯一领域写入口；先 G 后行锁；replay 先于 lease 检查；COMMIT 是唯一线性化点 |
| 控制锁 | G | `pg_advisory_xact_lock(24,1)`；单宿主前提；不是分布式租约 |
| 派发 | dispatch | 事件广播，落为 `kind='dispatch'` 的 effect + 若干 `listener_call` 子 effect |
| 精化 | refinement | 异步 dispatch 与同步参考语义在可观测结果上的一致（§7.7） |
| 反应域 | realm | 解析隔离单位；一个 key 在 realm 内唯一；不是 ACL |
| 足迹禁闭 | footprint confinement | delta 不得写其他 fiber 的 open episode 或释放他人 contribution；independence 的技术强制点 |
| 控制字段近似 | ≈ | 论文 §4.4.1 eq. (52)–(53)：两个状态在 σ 表（key→provider 绑定）与 ambient state 上逐项相同，只遗忘 registry 对「谁安装了它们」的记录（θ、τ、π、d、p、e 与 dom(F)）。**不是**「未绑定的 key 可遗忘」 |
| 观测等价 | ≃ / ≃_k | ≃ = Definition 33 + dom(F) 一致 + 每个 fiber 的每个控制字段一致；≃_k 是其在单 key 上的实例（同 key、同 descriptor digest、同 contract version、同 check）。本文的「数据等价」指 ≃_k，不替代 ≃ |
| 簿记表 | bookkeeping | `events`/`requests`；不承载生命周期决策，不计入领域表预算 |

---

[规格] 本文只新增此一个文件；未改代码、未改 schema、未运行 gate、未改其他文档。
