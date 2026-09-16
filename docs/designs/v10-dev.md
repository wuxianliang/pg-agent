# Postgres-Native Agent V10 实现规范草稿

> 状态：基于轮 5 准出的 raw，待实现规范审核；未执行实现与运行验收。
> 撰写日期：2026-09-16。唯一交付为本文件；本文件不改变冻结 v8、raw、审核记录或 v9。
> 效力：完整继承 v8 不变量，精确引用 v8 协议，完整定义 v10 增量；MUST/MUST NOT 为待审核合同。

输入指纹（实际文件 SHA-256，不代表实现 commit）：
- `docs/designs/v10-raw.md`：468 行；`6473130311666a393751ce7c4e8f4c8224abb77d9aeef2dbff4e40a789a30b0a`。
- `docs/designs/v8-dev.md`：871 行；`445306132fa01b278d479bc465c9a71c3b241407ec8a88b4d654967856237287`。
- `docs/reviews/v10-raw-oracle-review-2026-09-10.md`：244 行；`d6c0d0caedfe79d42a5ba6dd170aa7e56e558a085b01a7030729b71ccbd46c01`。
- 撰写合同：`prompt-exports/oracle-plan-2026-09-16-112233-new-chat-d11b11-133d.md`，690 行，§3 与 §5。

## 0. 基线、范围与不变量〔D1〕

### 0.1 文档效力

冻结基线为 `docs/designs/v8-dev.md` §0「不可妥协的不变量」（L5–24，附录 A 登记原句锚点）。
raw 页首及 §9.1 的“尚待复审”是历史时点；审核归档轮 5（L212–239）已裁定 0 P0 / 0 P1 / 1 P2，允许撰写。
准出不代表本实现规范已审，也不代表 v8 runtime 已就绪；三重门见 §7.1。
冲突效力：冻结 v8 合同优先；v10 范围按准出 raw 与轮 5 裁定；研究 digest 仅溯源，不增加需求。
本文唯一 schema/协议归属分别为 §2/§3–§5 与 §6；验收唯一归 §7；原 v8 字节算法与状态表不复制。

### 0.2 继承不变量 1–18

**本列表内原有“§”引用均指冻结 `v8-dev.md`，不是本文件同号章节。**

1. `session_events` 只追加；单个 session 的 `seq` 连续、单调且唯一。
2. 会话历史与调度控制态分离；`sessions`、`steps`、`effect_requests`、`leases` 和插件世代是权威控制态，不是 projection（effect 执行态的权威细分：`effect_attempts` 是每次执行 attempt 的唯一权威，`effect_requests` 的执行字段为其同事务维护的派生快照——快照仍属控制态、由数据库事务维护，不是可重建 projection；见 §3.2.2 双表权威性冻结）（step 定位指针括注：`sessions.active_step_id` 与 `sessions.drain_step_id` 均为定位辅助指针、非第二真相源——「每 session 至多一个非终态 step」的事实由 steps 部分唯一约束权威表达，见 §3.1）。
3. 每次 session claim、effect claim 与 workspace handle 所有权都有独立 fence；旧 fence 永远不能覆盖新 fence（含 workspace 受控操作 publish 点：lease/fence 被接管后，旧 worker 的 publish MUST 被 `owner_fence` CAS 拒绝，见 §2.2 第 1 条）。effect claim fence 的接管有独立前置（§3.2.2 接管流程第 2 步 guard）：仅当该 attempt 的 job lease 已过期或已被明确撤销时，recovery 方可 CAS 推进 `current_job_fence` 并接管结算；job lease 仍有效时 MUST 跳过该 attempt——不推进 fence、不撤销 lease、不结算；撤销仍有效 job lease 并立即接管只能经 operator 显式授权的受控内部操作 `FORCE_JOB_TAKEOVER`（记原因与审计），不是普通 recovery 路径。
4. 外部网络、LLM、工具和宿主语言 handler 不得在数据库事务内执行。
5. 每个逻辑 effect 有稳定 `effect_id`；重试复用 identity，新调用不得复用。
6. 系统只保证本地逻辑结果最多提交一次；外部副作用是否 exactly-once 取决于 provider 能力。
7. 无法判断外部副作用是否发生时进入 `unknown`，禁止把未知当普通失败盲目重放。
8. NOTIFY 和消息队列只是唤醒/传输优化；数据库扫描始终能够恢复进度。
9. assemble、fold、catalog、grant 和 policy 都绑定明确的 snapshot、cutoff 或 generation。
10. 并行 effect 的完成顺序不得改变模型语义；语义顺序在 dispatch 前确定。
11. authorization 等强制策略缺席、超时或错误时失败封闭。
12. 插件不能绕过 capability API；限制必须由数据库权限强制，而不只靠约定。
13. 每个 step/effect 固定 plugin generation、implementation digest 和 contract version。
14. 行为合同是规范；pinned compat 是参考实现，不是自动漂移的真理来源。
15. 同一 session 在同一 `driver_epoch` 内只有一个 driver 可以推进状态。
16. 租户 `workspace_id` 与执行态 `workspace_handle` 不是同一个对象。
17. 每次 seam 调用、route 解析、以及 effect 从 `ready` 进入 `dispatch_started`，都必须在同一事务中校验仍然有效的 grant；有效性的充要条件以 §2.1 为准，含所属 slice 未撤销、`workspace_id` 租户一致与 slice-membership。
18. yield / 换 worker 之前必须留下覆盖最新已完成执行态（最新已完成 `op_seq`/`generation`，无未收束 `in_flight` mutation）的 workspace checkpoint，或显式记录 `workspace/lost`。下一 worker 不得静默创建空 workspace；缺失、digest 不匹配或 checkpoint 未覆盖最新已完成执行态时返回 `WORKSPACE_LOST`，MUST NOT 恢复「旧但 digest 自身正确」的 checkpoint。

适用说明：v10 只展开不变量 9 的实现结构；内容冻结不缓存授权，persona version 不永久钉住 generation。

### 0.3 新增不变量 19–20

以下编号为本草稿分配，待本规范审核冻结，**未随 raw 准出成为冻结实现合同**。

19. **执行装配与初始 decision seal 原子发布。**一次 execution 装配的 Plan、Bind、Optimize、Serialize，以及选定 manifest、plan/trace、latch 变更、emergent 消费和 spill 状态应用，MUST 与新 decision step、唯一 LLM slot 及其首个 attempt 的初始 decision seal 在同一控制事务提交；不得存在已提交但未 seal 的装配工作或无 LLM slot 的前置 step。历史成功命令的重放复用原冻结结果，不重新装配。inspection 仅复用计算核，不适用创建、seal 与持久化义务。
20. **Bind 不执行外部工作。**Bind MUST 仅消费经当前授权取得的 DB-local 值及已受控发布的完整不可变 artifact；MUST NOT 执行网络、foreign table/dblink 外部访问、live workspace 读取、renderer 或宿主 handler。首版不得在缺输入时自动创建 preparation 工作；缺必需输入按 `needs_preparation` 合同返回。未来自动准备必须先定义合法的持久化执行归属并另行审核。

### 0.4 首版范围

- execution 与初始 decision seal 原子提交；tools seal 不装配；inspection 新计算与 explain 历史格式化分开。
- preparation 仅独立预构建后受控发布；PTL 仅 seal 前本地预算升级，provider PTL 依既有失败合同。
- emergent 目标为同 session、同 turn 的下一合格新 decision 装配；不是下一 turn，不是工作账本。
- P0–P3 不重新分期；churn 与八条论文 alert 整体延期；v9 pack/队列/apply 不默认接入。
- v9 是 v6 代码线的预建/刷新轨；v10 是 v8 合同上的装配轨，generation 域不互换，freshness 不等于授权。

## 1. 行为合同、canonical 与双运行时〔D2〕

### 1.1 继承 ABI

`docs/designs/v8-dev.md` §1.2「规范化行为 ABI」（L35–73）与 §1.3「canonical JSON 与 render」（L75–81）为唯一原合同。
v10 不改 normalize、事件键、流完整性、证据分类、turn reducer、canonical profile 或已有 portable occurrence 定义。
比较面 schema 各自版本化；input_digest/decision_digest 不替代 effect request_hash，装配投影不得反向修改事件 ABI。

### 1.2 assembly conformance

比较输入必须是 §3.2 全部实际消费值；stats 的历史 usage/latency 被消费则冻结，当前运行 usage/latency 不在输入中。
`assembly_conformance@v1` 输出为 `{canonical_request_bytes,canonical_decision}`；前者明确指下述最终 provider wire bytes，后者为合同 canonical descriptor；分别比较，不以物理 manifest_hash 作跨实例等价键。
三层边界（不改变 v8 §1.3）：(1) **合同 descriptor** 采用既有步骤0边界转义→schema/NFC/时间/tagged integer/JCS/hash；普通 `$ref/$defs/$int/$$int` 键各加一个 `$`，协议标注的大整数 tag 不转义；正式输入已转义，不重复转义。(2) **不透明内容**（文本、工具 schema、IR 或二进制）进入 descriptor 时统一为 `Bytes@v1={encoding:"base64",data:<RFC4648标准字母表、必需padding、无空白>,size:<字节数>,sha256:<小写hex>}`；严格解码后重编码必须相等，size/hash逐字节复核；bytea 不直接充当 JCS 值，内容内部不再执行步骤0/NFC/时间改写；Bytes封装自身是合同对象，仍执行步骤0（encoding/data/size/sha256无`$`键，base64字符串不递归解作JSON）。(3) **provider wire** 由 seal 前 Serialize 唯一生成并冻结，host 只能原样发送。
内容恢复仅发生于 Serialize 的值边界：已校验 Bytes 解码一次；声明为文本则严格 UTF-8，声明为 JSON 则无重复键、精确解析；合同结构字段按其 schema 还原一次普通 `$` 键/tagged整数，内容内部普通 `$int` 对象不是协议 tag。还原仅生成 provider 语义值，绝不回流 descriptor 校验/hash；工具 schema 中 `$ref/$defs` 原义保留而非发送 `$$ref/$$defs`。
`provider_wire_json@v1` 冻结为 UTF-8 JSON、无BOM/额外空白、对象键按UTF-16序、字符串转义与有限数值采用JCS规则；精确int64节点例外按十进制整数输出，不经float。超安全整数仅在provider policy明示允许的数值位置输出精确十进制，否则 INVALID_PROVIDER_REQUEST；不得发送合同tag对象冒充provider数值。非NFC不透明文本原字节语义保留；二进制仅policy明示的base64字段可用，否则拒绝。serializer/profile升级必须新版本。
LLM effect payload为版本化`ProviderRequest@v1` descriptor，包含model/params/policy/serializer与`wire:Bytes@v1`；seal前须证明其恢复后的model/params/tools与最终wire逐字段一致，不允许metadata显示已授权A而wire实际发送B；既有 request_hash=对**完整已转义descriptor**执行v8 canonical hash，覆盖最终wire的完整base64而非只覆盖其摘要，**不是直接SHA-256(wire)**。最终wire在seal前定型、计tokens并校验；dispatch只解码已冻结wire并验其size/hash与payload关联，不重新Serialize或还原内部JSON。
portable 映射在排序/计算**之前**确定；fixture 提供逻辑 tenant/session/turn 名与 source 身份，不是输出后抹掉 ID。

| 控制/审计字段 | portable 映射或排除 | 保留要求 |
|---|---|---|
| W/S/T 归属 | fixture 逻辑 workspace/session/turn 位置 | 实际进入 provider 内容的 W/S/date 字符串仍原字节保留 |
| step_id/effect_id | decision occurrence、slot ordinal 与稳定 source 关系 | 不把物理 UUID 当排序键；既有事件 ABI 不受此映射影响 |
| cutoff/physical seq | 捕获的 logical_history 与截断内容摘要 | heartbeat 改 seq 不改语义来源；真实 History 文本不得删 |
| generation_id | generation 成员的内容/implementation/contract 摘要 | 同代 ID 异实现不相等，不能只删 generation 字段 |
| section/source/候选 identity | §3.3 规范键、producer occurrence、candidate ordinal | 必须排序前存在；并列不可用物理 row ID 消解 |
| persona version/artifact 引用 | 不可变内容、完整 render identity、依赖/provenance 摘要 | 实际内容字节参与请求，不能只比 hash 忽略碰撞 |
| stats bucket version | 输入审计定位值；计算投影保留实际数值与统计 profile | version 不影响计算不入 decision；实际消费值必入输入 |
| command/receipt/attempt/lease/fence | 排除 | 原始控制记录仍留存、仍做安全验收 |
| plan/trace/inspection ID、worker、时钟/耗时 | 排除 | date 若为 SessionRuntime 内容则冻结并比较，不一概删除 |
| actual usage/cache hit/miss/ANALYZE | 排除 | 单独观测报告，禁止覆盖确定决策 |

canonical_decision 保留序列：final_tier/tier_trials、压力分子分母/reserve、section_order/budget/实测tokens、transforms（版本/逻辑键/applied或skipped/reason）、degradation/spill、marker、prefix_share/reason。
消费投影保留 producer/target occurrence、kind/hash、候选位置、选中与窗口结束原因；不保留 consumer 物理 step ID。
比较以 canonical 对象/数组的定义顺序，不对已排序 section 数组再无序集合化；同内容不同逻辑来源仍可不同。
provider 请求不是可任意脱敏的比较摘要：真实 model/params、消息 role/text、工具名/参数 schema、tool-call ID 内容、marker 全字节比较。
若两执行将不同物理 ID 字符串真的放入 prompt，它们不是“同逻辑输入”，fixture 必须固定这些内容或报告差异，不能删除掩盖。
输入 schema 升级、tokenizer/profile/statistics 变化为不同输入；相同输入在物理 ID/插入序/locale 扰动下请求与 decision 必须相同。

### 1.3 render conformance

`render_conformance@v1` 输入为 §5.2 完整 render identity、冻结 source/data/闭包；输出为 IR canonical JSON 与各 section canonical 内容字节。
native/compat 预构建 harness 分别执行各自 renderer/Writer/component，再对照；共读同一发布行不是独立渲染通过。
源码不变但 renderer/component/依赖改变必须新 identity；不同 identity 不承诺相等，跨 generation 同 identity 仍需授权。
compat 不得私有渲染后直接送模型；render projection 失败不改既有 execute 成功，引用 v8 §1.3 末条（L81）。

### 1.4 prompt/dispatch 双门

prompt 来源门证明“发出的字节出自受控 effect payload”；dispatch 门证明“外部 I/O 之前已经受权并持久派发”。
native/compat 都必须从相同数据库管道取得冻结 payload，禁止 host 追加 system prompt/重排 tools/改 marker。
每次实际 I/O 比较最终送出 request 与受控 payload 的字节关联；transport credential 可在外部安全通道附加，不是改 prompt 的许可。
精确继承 `docs/designs/v8-dev.md` §5.2「dispatch 拦截门闩（缩小支持面）」（L786–811）的两维 capability 与测试边界。
dispatch_interception≠sync_before_io 时只允许非执行 T0 数据库契约；真实 I/O 子例 blocked，不能拿数据库绿代替。
driver_switch_capability=unsupported 时切换正向 blocked，必须运行 UNSUPPORTED 零 mode/fence/switch-intent 修改的负向替换。
新 prompt 门是额外必须项，不是第三种允许跳过执行安全的能力；支持真实 I/O 却绕过来源门应 failed 而非 blocked。
报告按 fixture/subcase×driver×数据库层/真实 I/O 层给 passed/failed/blocked；未运行仍标未运行，不冒充 capability blocked。
未知 compat 事件的 audit/失败规则继承 v8 §5.1/§5.2，不得丢弃以维持 portable 绿。

## 2. 数据平面与权限〔D2；写集 D3〕

### 2.1 对象登记表

类型约定：W/S/T/E 分别为 workspace/session/turn/effect 的既有 identity 类型；所有对象显式携带 W。
新版本 identity 为非空规范文本或结构，计数为非负bigint，内容为bytea；所有K/唯一键/FK的物理索引映射统一遵守下述IdentityKey，物理digest不参与portable排序。
`IdentityKey@v1`：参照v8 §3.1.2 J08（turn-end稳定键digest+完整canonical留存），v10每个逻辑复合键整体编码为带对象/键域名的canonical tuple，取SHA-256固定32字节键；完整canonical bytes必留非索引列，命中后必须逐字节比较，不能拿第二个hash替代。FK先比完整目标identity再绑定digest；各类publication/security_context/transport定位、artifact/render/presentation、catalog/profile/persona/latch/source、stats桶与管理记录均适用，v8原键不变。
一般v10唯一索引为W（UUID 16字节）+32字节tuple digest，键载荷48字节；不得索引无界text/JSON。完整identity canonical bytes上限1,048,576字节（含域与复合封装），超限 IDENTITY_TOO_LARGE；digest命中异完整identity为 IDENTITY_DIGEST_COLLISION，零业务写、不覆盖、不另选碰撞键。授权前置后、身份索引访问前先验长度，再锁内全文比对；inspection只返回诊断。
**对象命令定位例外（不改v8键）**：binding保存完整`PublicationIdentity@v1=(域,W,publication_id)`（≤1MiB）及受保护32字节`binding_locator=SHA-256(该完整canonical bytes)`，禁止调用方指定locator；查找/重放先逐字节比原identity。receipt身份与物理唯一键直接为`(W,binding_locator,key_kind,key_value)`，kind为闭合集1字节编号、三类key_value均为32字节算法输出（hex显示须解码），固定键载荷81字节；不再带入完整publication_id，也不再次hash此键。其规范描述固定小于512字节，故binding界内身份的accepted、业务拒绝、畸形拒绝、冲突均有可保存receipt，不存在派生1MiB溢出出口。
publication身份无效/超限或locator碰撞不占binding，走`object_ingress_rejections`：受保护有界security_context_id（UUID）+既有transport_rejection_key，原报文/完整收到identity仅留非索引列供精确比对，结果码与碰撞定位留存；不借冲突locator引用别人的receipt。内容identity超限/碰撞则使用本请求已合法定位的普通object receipt；两种碰撞路径不得混用，均保持原对象不变。ingress/授权审计的上下文定位使用认证层分配的固定UUID，不拼接publication全文进派生键。
下表 K 为主键（隐含首列 W）；跨表 FK MUST 带 W，session 对象另带 S/T 并校验既有父对象一致，禁止跨租户悬挂引用。
I=不可变内容/目录，C=权威控制绑定，A=不可清理审计，P=可重建 projection，ST=跨 session 统计；均非新调度平面。
保留 R=随 session/effect 与 receipt 显式销毁；V=有引用不得删，权威 artifact 仅显式销毁；P=可从冻结源重建同字节。

| 对象 | 类别 / K（W 前缀） | 创建者 / 唯一写入口 | 可变字段 | 引用者 / 保留 / 定义 |
|---|---|---|---|---|
| context_generation_pointer | C / 固定active槽（W内唯一） | stage首次建空行；activate/revoke_active切换 | active_generation、revision与最后操作溯源 | 新装配 / V / §6.1；非第二指针 |
| context_query_registry | I / generation, query_id | generation publisher / manage_context_generation(stage)同包 | 无 | 预构建与provenance / V / §2.4 |
| context_section_catalog | I / generation, section_key | generation publisher / manage_context_generation(stage) | 无 | manifest / V / §2.2 |
| provider_cache_policies | I / generation, policy_version | 同上 | 无 | catalog/manifest / V / §2.2 |
| assembly_profiles | I / generation, profile_version | 同上 | 无 | manifest / V / §2.2 |
| feedback_profiles | I / generation, profile_version | 同上 | 无 | effect 绑定/sample / V / §2.2 |
| persona | C / persona_id | operator / publish_persona_version | current_version 指针 CAS | session 初始化 / V / §2.3 |
| persona_version | I / persona_id, version_id | operator / publish_persona_version | 无 | persona/session / V / §2.3 |
| sessions 内容扩展 | C / S（既有行） | session initializer / initialize_context_session | 首次写后无 | manifest / R / §2.3 |
| poml_documents | I / doc_hash | publisher / publish_context_artifact 的源文档包 | 无 | render output / V / §5.2 |
| context_artifacts | I / artifact_identity | publisher / publish_context_artifact | 无 | Bind/render/spill / V / §5.2 |
| poml_render_outputs | I / render_identity | publisher / 同一发布命令 | 无 | manifest/cache / V / §5.2 |
| context_latches | C / S, latch_key | coordinator / 初始 decision seal 内部应用 | 无，首次成功触发写 | manifest / R / §3.2 |
| context_management_permissions | C / permission_id | 受保护operator根入口 / manage_context_permission | 仅revoked_at null→值、revision+1 | 管理命令/证明核验 / V / §2.4 |
| context_model_defaults | I / generation, defaults_version | generation publisher / manage_context_generation(stage) | 无 | session初始化 / V / §6.1 |
| context_emergent_relations | C / S, producer_effect | completion / 合格 Feedback | consumer_step_id 一次绑定 | candidate/plan / R / §4.3 |
| context_emergent | C / S, producer_effect, kind, content_hash | completion / Feedback；消费由初始 seal | 仅消费删除 | manifest/plan / R / §4.3 |
| effect_feedback_bindings | C / E | coordinator / 初始 decision seal | 无 | Feedback/sample / R / §4.2 |
| context_feedback_samples | A / E, feedback_profile_version | completion / 合格 Feedback | 无 | stats/trace / R / §4.2 |
| context_stats | ST / 完整 bucket_key | completion / 合格 Feedback | digest/EMA/version/updated_at | manifest / 显式销毁 / §4.5 |
| context_spill | P 或 I 引用 / S, occurrence, section_key | coordinator / 初始 decision seal | 首版无在线修改 | plan/manifest / R+P / §3.7 |
| assembly_plans | A / S, occurrence | coordinator / 初始 decision seal | 无 | trace/关系/FK / R / §3.2 |
| assembly_traces | A / S, occurrence | coordinator / 初始 seal；completion / Feedback | 仅 ANALYZE 域补全一次 | explain / R / §4.6 |
| object_command_bindings | A / 完整publication identity（locator索引） | publisher/operator / 对象命令处理 | 无 | object receipts / V / §6.4 |
| object_command_receipts | A / binding_locator, typed_request_key | 同上 | 无 | 发布重放 / V / §6.4 |
| object_ingress_rejections | A / security_context, transport_key | 对象 ingress / 对象命令处理 | 无 | malformed 重放 / 显式销毁 / §6.4 |
| object_authorization_denials | A / security_context, command_identity | 对象授权门 / 对象命令处理 | 无 | 安全审计 / 显式销毁 / §6.4 |

稳定视图只有受权读取投影，无独立写入口或可变真相；fold 缓存沿既有 projection 合同，不新建 fold 权威对象。
元组唯一性、NOT NULL、不可变保护、FK 与域约束由 DB 强制；无可执行 DDL。
除显式可空字段外必填；tenant FK 与引用闭包验证覆盖 JSON 引用，不以“藏在 JSON”规避约束。
R 对象不得由 compaction/缓存清理删除；plan 中消费字节与历史 receipt 同寿命，支撑 occurrence 最大值与重放。
显式销毁是离线 operator 数据生命周期操作：停用相关入口、撤销许可、排空事务并拒绝活跃引用后，按依赖图连同 receipts 整组销毁；不开放运行时 DELETE 命令。

### 2.2 catalog/profile

以下字段均继承上表 W 与 K；版本化 JSON 必须声明 schema 版本，不接受未知必需字段。

| 对象字段 | 类型/约束与含义 |
|---|---|
| catalog.plugin_identity | 非空逻辑插件 identity；绑定 generation 内已登记 implementation |
| catalog.section_key/source_key | 规范文本；section_key 唯一；source_key 为跨实例逻辑来源，非行 ID |
| catalog.source | 单一类型化来源引用；静态/POML/DB-local 不允许运行时隐式合并 |
| catalog.tier/kind/scope/priority | tier 四值见 §3.3；kind 十二值见下；scope=Global/Session/None；priority=Never/High/Normal/Low |
| catalog.est_tokens/bind_latency_ema | 非负整数 token/十进制发布默认估计；不可变，不是运行 EMA |
| catalog.recoverable/provider_markerable | bool；前者只代表同字节重建能力，后者仍受 provider policy 限制 |
| catalog.dependencies | 按逻辑键排序的必需/可选依赖引用数组；要求版本/digest/授权资源边界 |
| catalog.required/source_limits | bool 与正整数 max_bytes；Never 必须 required；空文本可合法但空必需来源不合法 |
| policy.provider/profile_digest | 规范 identity/digest；依赖实际 wire 格式版本 |
| policy.M_max/granularity/prefix_only/global_scope | 非负整数上限；granularity=section/message；后二项 bool |
| policy.ValidSpeakers/role_map | 闭合集建议角色及确定映射；不支持的建议拒绝，不由 Writer 最终分派 |
| assembly profile | 算法/tokenizer/budget/serializer/canonical 版本与实现摘要；provider policy 引用 |
| assembly profile.limits | max_moves、max_clear_tokens 非负整数；L_eff 正整数；reserved R_t/R_s 首版固定 0 |
| assembly profile.transforms | 各tier允许变换及确定执行序；schema删减白名单、History保留组数；optional表示序固定为full→合法缩减→spill_placeholder→placeholder→skip，placeholder字节按Bytes@v1冻结，allow_placeholder为必填bool（false使两类placeholder均不可用），零收益表示跳过 |
| catalog.latch_declarations | generation publisher登记的不可变数组；每项latch_key、declaration_version/digest、source逻辑键、trigger、value_selector；合同见§3.2 |
| feedback profile | profile_version=规范内容SHA-256（同摘要核验全文）；statistics_profile_identity、提取版本、三个kind的字段路径/schema/cap/max_bytes |
| feedback profile.numeric | EMA 的有理系数 a/b（0<a≤b）、decimal scale、计量单位、tokenizer 与 usage schema |

kind 闭合集：Identity、Constraints、History、Memory、ToolSchemas、Skills、ProjectContext、SessionRuntime、TurnVolatile、EmergentSkills、EmergentMemory、EmergentSummary。
Identity/Constraints 固定 Never、禁止压缩重排；WorkingMemory/RuntimeIdentity/RuntimeVolatile/DeferredTools 不另列 kind。
generation stage校验source唯一、依赖无环、逻辑键/声明无歧义与profile完整；activate另验实现ready，失败结果及building→failed归§6.1。context_model_defaults含defaults_version、model_id、params对象、parameter_schema_version、content_digest，全字段不可变；初始化只用已active/retired且未failed的来源generation。
stats 算法、tokenizer、单位或 profile 改变产生新统计身份；不得原地升级已绑定 effect 的 profile。

### 2.3 persona/params

`persona` 字段：W、persona_id、current_version（可空仅用于首次创建前）、pointer_revision 非负整数；指针更新必须 CAS expected_revision。
`persona_version` 字段：W、persona_id、version_id、system_prompt 文本、constraints JSON、model_id、params JSON 对象、content_digest。
版本号由发布 payload 指定；同 version 同完整内容幂等引用、异内容冲突；当前指针不倒推旧 session。
`sessions` 内容扩展字段：persona_version_ref、model_defaults_version、effective_model_id、effective_params、content_binding_digest；只能由§6.1 initialize_context_session与建session同事务首次写入，不假定v8已有create_session receipt合同。
session 初始化以授权后的默认值与 persona_version.params 做 JSONB 顶层右覆盖，**不是递归 deep merge**。
`get_effective_params(defaults_value, persona_params_value)` 只收两个 JSON 对象，输出合并值；不按 session_id 偷读当前默认值。
显式 JSON null 覆盖默认值，然后按参数 schema 判合法；非法 model/params 拒绝初始化，不创建半绑定 session。
defaults 与 persona 均按 canonical profile 校验；冻结所用版本与物化结果，此后不按 turn 重算。
新 decision step 按当前 active plugin generation；旧 step/effect 的实现 generation/digest/contract 不变。
pgAgentOS仅吸收persona/params与ForkPrefix动机；RLS/poll_job为模式确认。send_message仅保留并发编号/幂等批评，不声称函数内多DML非原子。

### 2.4 权限与生命周期

继承 `docs/designs/v8-dev.md` §2「四平面与权限边界」（L83–110）与 §2.1「授权线性化点/两阶段授权快照边界」（L147–165）。

下表为完整映射；C=经v8 grant/driver链认证的session/step/plugin_identity/driver subject，I=同样认证的inspector（非任意SQL role），M=管理许可绑定的认证principal，B=可信builder绑定的v8 subject；都不得由payload自报替代。所有读取逐项检查租户、subject、时间、撤销、membership及max_bytes/max_rows/目标/参数约束。
`slice.spec.context_resources@v1` 是既有slice种类内的类型化精确资源选择器（不加capability/kind枚举）：corpus列出`(resource_kind,logical_identity,version)`，包括catalog/profile/stats/persona/defaults/artifact/trace/emergent-result/query/relation；tool_set列实际tool identities；workspace_exec列session/history范围。选择器不可变，扩权/收窄均撤销重建；未知类型/通配含糊项拒绝。artifact依赖、trace输入及emergent继承源的传递闭包也须逐项membership，不因外层对象可读而豁免。

| 操作 | capability / operator权限 | subject | 实际resource与membership | 约束与线性化/写集 |
|---|---|---|---|---|
| cutoff History、TurnVolatile/inject、SessionRuntime、session latch读取 | fold | C/I | workspace_exec中的S及history截止范围 | cutoff/租户；授权锁后捕获，inspection零写 |
| catalog/policy/assembly及feedback profile、stats、静态Skills/Constraints | recall | C/I | corpus中的generation+section/profile/完整桶键及静态源 | 版本/max_bytes；捕获、seal、dispatch全验 |
| ToolSchemas/模型可见工具 | tool_resolve | C/I | tool_set中的每个实际工具及generation | 可见面/具体schema；两实时门均重验 |
| persona/defaults/effective绑定、artifact/POML包、spill重建源 | recall | C/I；初始化为M绑定的v8 subject | corpus精确版本+全部source_refs/依赖 | max_bytes/sensitivity/版本；初始化或捕获锁内验 |
| emergent消费 | recall AND fold | C | corpus中的`emergent-result(S,T,producer_effect,result_digest)`及继承源闭包；workspace_exec的S/T | 当前consumer subject，不复用producer grant；§4.4资格+seal/dispatch |
| explain历史trace/inspect返回输入 | recall + 每个展开源的对应capability | I | corpus中的trace(S,occurrence)及所有被披露来源闭包 | 当前权限；锁内只读，拒绝亦零审计 |
| 初始/tools seal；ready→dispatch_started | authorize_effect AND effect_submit + 全部实际来源权限 | C/已绑定effect的dispatch subject链 | 具体model/tool/参数目标所属slice + 冻结auth_requirements | v8两独立实时门；§3.5/原v8写集 |
| 普通completion / 非普通入口 | v8 envelope/证据门 | effect绑定provider/adapter/driver | 既有attempt/result归属 | §4.1分流，不借此获得新读取权限 |
| 四标签的schema/migration元数据 | recall | B | corpus中逐个catalog对象/版本 | 受控DB-local只读查询；max_rows/bytes，查询事务授权 |
| query-result/query-plan预物化 | recall，经具名recall_context_query入口（不是新capability） | B | corpus精确query(generation,query_id,query_version)及全部relation依赖闭包 | §2.4登记解析/参数/output约束；物化时锁内授权；DB-local SELECT/EXPLAIN非ANALYZE，零持久写 |
| artifact/persona/generation发布；session初始化 | ARTIFACT_PUBLISH / PERSONA_PUBLISH / GENERATION_MANAGE / SESSION_INITIALIZE | M | 管理许可的W+目标identity/version范围，来源仍须上列v8读取能力 | §6.1/6.4锁内验；完整包/参数上限/CAS |
| 权限签发/撤销与builder信任锚登记 | 受保护operator根权限 | 认证DB operator（worker不可SET ROLE） | W+principal+目标范围 | manage_context_permission对象命令；同权限锁串行，receipt同事务 |

v10显式新增**管理许可协议而非grant.capability值**：`context_management_permissions`保存W/permission_id、principal、operation闭合集（上表四类及BUILD_ATTEST）、target_selector、constraints、not_before/expires_at、revoked_at、revision、issuer与证明公钥/实现范围（BUILD_ATTEST必填）。除撤销与revision外不可变；缺项deny。只有安装时授予的DB operator根角色可经`manage_context_permission(auth,publication_id,issue|revoke,payload)`签发/撤销，payload含完整记录或目标+expected_revision+reason；§6.4 typed键/首占/receipt/crash同款，成功PERMISSION_ISSUED/REVOKED；issue的permission_id同完整记录则复用、异记录PERMISSION_IDENTITY_CONFLICT；字段/范围非法PERMISSION_INPUT_INVALID；revoke锁内CAS expected_revision，失配PERMISSION_REVISION_MISMATCH（已撤销不重复推进revision）；同ID重放零写。worker无表DML；更新约束必须撤销重签，不能靠自报operator字符串。
管理许可锁位在grant/slice之后、generation之前，按(W,permission_id)排序，签发/撤销仅取该位及对象receipt/目标锁，不回取session；subject/TTL/约束/撤销在发布提交前重验，当前发布权限也是历史receipt读取的前置。许可不充当消费grant，发布成功不隐含读取权。
每个source在FrozenInputs持久`auth_requirements`：capability、subject绑定规则、slice_id/grant_id、resource完整逻辑identity/version、constraints摘要及依赖闭包；effect payload的受保护伴随绑定引用该集合，不能由host删改。seal重验本次所有捕获/计算/披露来源（含未选候选、profile/stats）与实际effect参数；dispatch在当前认证subject链上重验同集合及具体请求，按当前时间/撤销/membership判定，不重新读取内容或复算决策。grant替换需新装配，不原地换冻结授权定位；tools seal/dispatch亦各验其具体成员。
provenance首版**仅接受BUILD_ATTEST许可绑定builder的签名证明**；不支持独立DB物化证明或无定义证明登记入口。证明覆盖W、输入字节摘要/版本、来源定位/授权依赖、builder实现/contract/profile及全包产物摘要；查询来源另覆盖下述完整query登记identity/记录digest、实际参数canonical bytes、relation版本/实际依赖集及结果bytes摘要。publisher须同时有目标发布权，核验签名/可信principal/有效许可/来源权，事务内不访问外网；裸自报provenance无效。consumer验证已发布证明完整性及自己的当前源权限，不把builder历史取数权当消费权。
`context_query_registry@v1`是query_id的**唯一权威源**（显式新增登记对象，不把host allowlist或调用方SQL当登记）：字段为W/generation/query_id、query_version、handler_ref（精确指向该generation成员的SQL implementation及具名entry）、implementation_digest/contract_version、parameter_schema及版本、allowed_relation_dependencies（逻辑identity/版本及view/函数展开后的传递闭包）、output_constraints（schema/media/max_rows/max_bytes）与record_digest。仅stage完整包创建，activate前验证唯一query_id、成员/FK/实现摘要与闭包；同generation/query_id换实现或任一字段均GENERATION_IDENTITY_CONFLICT，不原地升级，修改必须新generation/版本。
`recall_context_query(auth,generation,query_id,expected_query_version,params,mode)`是R类受控入口；mode仅result/plan（后者EXPLAIN非ANALYZE）。授权上下文先行，按登记唯一解析、generation须已发布active/retired且未failed、核成员和实际实现digest，再验参数与所有来源当前recall/membership；只执行登记的静态参数化DB-local只读SQL，禁止调用方SQL、动态SQL、FDW/dblink、写函数、外部/宿主调用。执行前锁定或复核DB定义版本，解析实际依赖（含嵌套view/函数）与声明闭包逐项相等；无法证明闭包/零写即拒，不运行后补审计。执行/返回前核输出约束与定义版本未漂移；返回冻结结果及登记/来源描述供可信builder签名，入口本身不签发证明、不写receipt/audit/登记/持久临时结果。
未知query→QUERY_NOT_REGISTERED；期望版本、实际实现digest或定义版本不符→QUERY_VERSION_MISMATCH；参数越schema/范围→QUERY_PARAMETER_OUT_OF_BOUNDS；实际依赖不等声明→QUERY_DEPENDENCY_MISMATCH；输出越界→QUERY_OUTPUT_INVALID；未发布/failed generation分别IMPLEMENTATION_NOT_READY/GENERATION_REVOKED；均R诊断、零持久写且无外调，未通过当前授权先GRANT_DENIED、不泄露query存在性。consumer的auth_requirements保留query登记与源闭包并在seal/dispatch实时重验；builder证明不替代当前权限。
受控写/读取入口逐函数审计 SECURITY DEFINER，拒绝任意动态 SQL/外部 SQL 桥；纯核权限见 §3.1。
READ COMMITTED 强制范围继承 v8 §2「事务隔离级别前提」（L85）；v10 控制写入口统一要求 READ COMMITTED，纯计算不要求。
输入捕获有当前授权锁，seal 再验具体请求，dispatch 再验当前授权；manifest、RLS、freshness 都不能替代任一门。

### 2.5 schema 安装边界

`agent_context` 与新增对象名为本规范逻辑命名；安装前必须出全量冲突扫描，未扫描不得声称物理名称已可安装。
核查域：schema、表/视图、带参数签名函数、类型、索引/约束、同表列；输入为 v1–v9 全部加载 SQL/注册对象及 v8/v9 规划对象。
至少包含 v8_schema/v8_keys 与 v9 ctx_schema；记录文件摘要、数据库/schema/adapter 版本和冲突详情，不以 v9 的 v1–v7 检查替代。
扫描归实现接入验证产物；冲突时阻止 P0 安装，作等价命名映射并审核引用，不改既有命名或协议。
安装原子注册权限/不可变保护/FK/唯一约束后才公开入口；不提供跳过约束的降级安装模式。

## 3. 装配管道与 manifest〔D2+D3〕

### 3.1 入口与初始 seal

继承 `docs/designs/v8-dev.md` §3.1.2「初始 decision seal」（L376–378）：新 step、唯一 LLM slot 与首 attempt 同事务发布。
单一链为 claim → 控制事务捕获输入/Plan/Bind/Optimize/Serialize/应用/初始 seal → 事务外 dispatch → 合格 completion/Feedback。

| 阶段/函数形态 | 输入→输出 | 读写/volatility 纪律 |
|---|---|---|
| capture_assembly_inputs(auth,S,cutoff) | 已授权控制/目录/来源→FrozenInputs | capability 读取与锁；VOLATILE，不调用宿主 |
| plan_assembly(FrozenInputs) | 值→预算/tier/来源需求/PlanValue | 纯 SQL 值计算，IMMUTABLE、INVOKER |
| bind_values(FrozenInputs,PlanValue) | 已捕获字节→BoundSections | 纯值绑定；不再 SQL 取数，不执行 renderer |
| optimize_assembly(BoundSections,PlanValue) | 值→有序 section/变换/marker/决策 | 纯值计算，IMMUTABLE |
| serialize_assembly(values,policy) | 有序值→最终wire+ProviderRequest descriptor（§1.2） | 纯值计算，IMMUTABLE |
| apply_initial_assembly(parent,values) | 决策→§3.5 原子写集 | 父控制入口 VOLATILE，唯一写路径 |
| inspect_assembly(auth,S,cutoff,overrides) | 新假设输入→返回值 | 授权读取入口 VOLATILE，零业务/审计写 |
| explain_assembly(auth,S,through_seq) | 历史已提交 trace→格式化值 | 授权读取入口 VOLATILE，格式化内核可纯值 |


### 3.2 冻结输入

扩展 `docs/designs/v8-dev.md` §3.3「inject 固定 assembly_cutoff_seq / 同一 manifest hash」（L709），不建立第二套 assemble manifest。
先取得 session 控制门、必要 grant/slice 锁与 generation 门，再完成一次明确输入捕获；全程同一控制事务。
依赖发现可以预读只作锁集候选；取得主锁后单一捕获语句/MVCC 快照读可变值，后续阶段不得重读当前 catalog/stats。
目录/generation 指针或依赖集与预读不一致时回滚重新取锁；不在尾段倒序补锁，不提交半 manifest。

| 层/正式 schema | 完整字段与适用域 |
|---|---|
| FrozenInputs@v1 | schema_version；history（cutoff、fold_version、logical_history 与内容）；catalog_rows；grant/policy 输入摘要 |
| FrozenInputs 内容 | persona_version 内容、effective_params/model、latch_values/firing_proposals、emergent 候选/关系与逻辑身份 |
| FrozenInputs 来源 | 每source的logical_key、required、source_version、Bytes@v1或frozen_rebuild_ref、hash、dependencies、provenance、stale/drift、§2.4完整auth_requirements |
| FrozenInputs 计量 | model/query_source/statistics_profile_identity、stats实际值/version、tokenizer/算法/预算/profile/serializer/canonical版本、L_eff、R_t/R_s |
| FrozenInputs 渲染 | artifact 与 render identities、provider policy、fork 前缀比较材料；无 live handle 或动态地址 |
| Decision@v1 | P_raw/P_pred、R_o、tier_trials/final_tier、section_order、budgets、measured_tokens、applied/skipped/reasons |
| Decision 结果 | selected/degraded/spilled 内容选择、marker_layout、latch_decisions、consumption_records、prefix_share/不共享原因 |
| ExecutionBinding@v1 | W/S/T/step/E、occurrence、assembly_cutoff_seq、generation/digest/contract、parent_command_id、request_hash |
| assembly_plans | W/S/occurrence、step_id、FrozenInputs、Decision、ExecutionBinding、input_digest、decision_digest、manifest_hash |
| context_latches | W/S/latch_key、declaration_version/digest、latch_value（canonical值）、fired_turn_id、fired_seq（成功装配cutoff）、fired_occurrence |

latch声明随catalog generation发布并校验：`trigger`闭合集为selected_present/selected_equals，后者带input_path及canonical literal（路径与value_selector同一白名单）；`value_selector`为literal或冻结input_path（仅effective_params显式键/指定source的结构化字段，禁止当前时间/SQL/host）；声明含owner source逻辑键、字段schema与缺字段拒绝规则。相同key多声明必须完整相同，否则发布LATCH_DECLARATION_CONFLICT（generation包诊断优先于通用GENERATION_PACKAGE_INVALID）。
纯核从FrozenInputs一次生成proposals（key/declaration_digest/value/source），不能接受worker自报提案；同key同声明同值去重，异值拒LATCH_PROPOSAL_CONFLICT，不按到达顺序抢赢。既有latch先校验声明digest一致，不同则LATCH_DECLARATION_MISMATCH（新generation不得重置旧key）；一致则Bind使用历史冻结值、忽略今日候选值的改变，generation与授权仍实时判定。
未触发key用候选值临时Bind；每个tier在Optimize选定表示、Serialize尚未加marker时定义present(owner)=该section表示为full或合法缩减且其内容将成为非空provider语义片段。`fire(k)=无历史latch(k) AND present(owner) AND (trigger=selected_present OR (trigger=selected_equals AND FrozenInputs[input_path]=literal))`，等值按已校验canonical值逐字节；skip/placeholder/spill_placeholder的present恒false。final firing集合用于marker与最后wire预算；升tier时从同一FrozenInputs重算，不继承失败trial的提案/触发。成功seal才写新latch；回滚/inspection不写，不以Decision反过来作为value权威。
`new_firings`仅本次n将首次写入的key；`turn_has_firing`=new_firings非空 OR 已有latch.fired_turn_id=T。None-scope marker抑制覆盖整个该turn（含同turn后继装配），下一turn不因历史firing抑制；cutoff/seq不是turn identity。首次触发永久不可变，fired_seq仅溯源不新增事件，不冻结授权/generation/共享资格；纯核固定search_path，锁/实时重验不得放STABLE函数。
plan 的 input/decision/binding 三域不可互相替代；inspection 返回同 schema 值，但无 ExecutionBinding 控制实例。
完整 plan FK 指向同事务新 step/E；occurrence 分配/唯一性见 §4.4；新行最终约束可在提交前校验，禁止悬挂提交。
hash有向无环：FrozenInputs内全部bytes先按Bytes@v1封装→canonical→input_digest；输入+算法结果→Decision→decision_digest；Serialize定型wire→ProviderRequest descriptor→既有request_hash；manifest中的wire/原文均使用Bytes@v1。
最终 manifest_hash 覆盖三层（含最终 request_hash）但不含自身；Decision 不含 manifest_hash/request_hash/运行 ANALYZE。
provider payload 不包含 manifest_hash 或 trace hash；trace 引用 Decision，不反向参与请求 hash；不得替代 v8 effect identity。

### 3.3 Plan/Bind

每 source 唯一逻辑键为 `(plugin_identity,section_key,source_key,logical_occurrence)`；kind完整闭合集见§2.2。
logical_occurrence 是来源内部可复现位置，明确区别 §4 的 decision occurrence；重复规范键为输入错误，不按物理 ID 补序。
Identity、Constraints 分别锚定第 1、2 个区段，各自内部按逻辑 source 键字节序；Never-priority 内容均不可压缩/删减。
History 输入来自 cutoff fold 的完整消息组；tool-call/result 为同组原子单元，不拆半组、不重排组内消息。
Bind 核验依赖闭包、来源类型、speaker、required、content digest；DB-local recall 也必须在捕获时完成授权，非 Bind 外调。
ProjectContext 仅已发布 workspace slice；SessionRuntime 由捕获的 model/date/workspace 内容派生；TurnVolatile 仅 cutoff 内 inject/参数。
Memory、Skills、ToolSchemas、三种 Emergent kinds 依冻结目录来源绑定，不借 Astra 未移植 kinds 或 trait 增接口。

压力采用精确整数比值（比较用交叉相乘，不依赖二进制浮点）：
`P_raw = T_used / L_eff`；`P_pred = (T_used + R_o + R_t + R_s) / L_eff`。
T_used 是当前候选请求按冻结 tokenizer 测得的 input token（含消息/工具/wire 开销），不得仅信 est_tokens。
R_o 从冻结 output_tokens 桶取 steady p75 / seal 前保守 p95；空桶 500；R_t/R_s 首版 0。
初始 tier 取 raw 与 steady predictive 两者较高；保守重算后只升级，已有 tier 不因删减后压力下降而降级。

| 压力区间（阈值等号归较高档） | tier | 允许变换的累积集合 |
|---|---|---|
| P<0.60 | Normal | 锚定、有限稳定重排、合法 marker |
| 0.60≤P<0.75 | TrimSchemas | 上述 + ToolSchemas 冗余描述字段删减 |
| 0.75≤P<0.90 | CompactHistory | 上述 + History 完整组确定截取 |
| P≥0.90 | AggressivePrune | 上述 + optional section 的 skip/placeholder/spill |

预算 @v1：B=L_eff−R_o−R_t−R_s−固定 wire 开销；先一次计入全部 Never 全量及其他 required 在当前 tier 的唯一合法最低表示。
该基线不可被 optional 占用；再按 High→Normal→Low、同级规范逻辑键分配：required 升级仅扣目标 tokens−已预留 tokens 的差额，装不下保留最低表示。
optional从空表示起，按full→profile固定序合法缩减→spill_placeholder→placeholder→skip选首个合法且可容纳项；预算驱动的后三种仅AggressivePrune可用，输入缺失的placeholder/skip另按§3.8不依赖压力tier；条件与确切字节见§3.7，不能由实现任选。required最低表示不含这三类，表示序随profile冻结。
基线装不下才试更高 tier，终档无解拒 ASSEMBLY_BUDGET_EXCEEDED；不重复扣 required、不挤掉最低表示，未变换也记 gate/budget 原因。
空 source 集缺 Identity/Constraints 必需锚点，属于缺必需输入；有锚点但其余为空合法；不生成无身份空 prompt。
L_eff≤0、非整数、超数值域或 profile 无预算规则必须拒绝；Never/required 最低表示已超预算不得静默截断。
这些是 v10 自定义版本化规则，不宣称实现论文特有启发式；升级任何排序/分配/变换规则必须升级 assembly profile。

### 3.4 Optimize/Serialize

非锚定 section 全序：scope(Global<Session<None)→priority(Never<High<Normal<Low)→逻辑 section/source/occurrence 的 canonical 字节序。
重排从冻结逻辑输入序开始；一次 move=将目标序下一个错位 section 移到目标位置，依左到右执行至 max_moves，剩余保持稳定。
TrimSchemas 只删 profile 白名单中的说明性字段，不删名称、类型、required、参数约束或授权可见面；顺序按字段规范键。
CompactHistory 仅保留 profile 指定最近完整组；从最早可删组依次移除，累计清除 token 不超过 max_clear_tokens，下一组超限即停。
History 的 Never 组不可移除；不得生成新摘要或调用模型；CompactHistory 是装配变换，不修改 v8 compact 的输入前缀模型。
AggressivePrune 按 Low→Normal→High、再按逻辑键处理 optional，Never 永不参与；spill 不能改变已冻结 source。
每个变换记录 applied 或 skipped（tier_gate、never、move_limit、clear_limit、no_gain、budget_fit）；无进展变换至多执行一次。
重算以本次完整冻结输入与更高 tier 从头计算，不把前轮可变状态当新输入；至多四档，禁止不收敛循环。
Serialize按provider policy定role/消息边界、tools schema/配对；按§1.2唯一恢复/序列化边界产生最终wire及其Bytes封装descriptor，既有canonical profile仅用于合同payload，不能把转义后的schema直接发送。
实测完整 wire tokens；校验 `wire_tokens+R_o(p95)+R_t+R_s ≤ L_eff`，不合则仅在 seal 前尝试更高档。
最终仍超预算或结构非法则不创建请求；不得发送残缺 tool pair、删除 Never、偷偷降 reserve 或现场调用摘要器。
marker输入只能是FrozenInputs.catalog_rows.provider_markerable及绑定的provider_cache_policies行（M_max/granularity/prefix_only/global_scope/role_map），不得由host补默认。令cacheable(section)=非空full/合法缩减 AND provider_markerable=true AND policy粒度/role允许 AND（非Global或global_scope=true）AND NOT（scope=None AND turn_has_firing）；marker资格=cacheable AND scope边界（最终section序中其后scope变化或序尾）。首中不合格原因依序为representation_ineligible/provider_not_markerable/not_scope_boundary/policy_granularity_or_role/global_scope_unsupported/latch_turn_suppressed；记录skipped且不占M_max，不是静默丢弃。
message粒度需消息尾与scope边界重合且消息内各section同scope、全部cacheable，不能借相邻section放marker。prefix_only=true仅从开头连续cacheable的section前缀取合格边界，非边界本身不截断前缀、不cacheable才截断；其余合格但被截断/额度耗尽者记prefix_blocked/marker_limit；按prefix顺序取最多M_max。None-scope并非永久禁用，仅受上述turn窗口与policy约束。
marker本身token/wire开销计入最后预算；标记布局变更后重验消息/配对，Serialize不得删改已供fire判定的section表示，仅编码或失败，因此不存在Serialize后再反向触发latch的第二时点。
provider PTL 不进入本地循环：派发后按 v8 失败/unknown 证据规则收束；合法 retry 保持同 request_hash/payload。

### 3.5 execution 原子应用

成功初始装配写集恰为：冻结三层 plan/trace、首次 latch、emergent 绑定/窗口删除、spill 引用、effect/profile sidecar。
与 v8 新 step、唯一 LLM slot/batch、首 attempt、既有 seal/父命令 receipt、必要唤醒记录同事务提交。
成功提交后 step waiting_effect、effect ready、attempt_no=1；不存在持久 planned 无 effect 或 seal 后补 attempt。
应用前对实际将写的 effect 具体参数执行 seal 授权，检查 generation/current claim/CAS；失败回滚全部 context 决策写集。
纯计算的决策不能自己 INSERT；inspection 不调用应用入口；普通 computation 错误与基础设施错误依 §6.2 分开。

### 3.6 inspection

`explain_assembly(auth,S,through_seq)` 读取 cutoff≤through_seq 的已有成功 execution traces，按 occurrence 格式化；无匹配返回空列表。
它不重跑计算；ANALYZE 缺失按 §4.6 展示原因；无权内容不返回，不能用 trace 历史读取绕过当前权限。
`inspect_assembly(auth,S,cutoff,overrides)` 进行新的假设性装配，返回 inspection_id、input_digest、FrozenInputs、Decision、request_descriptor 或 incomplete。
overrides 仅允许 profile 明示的预算/候选输入值，仍需来源授权；不能伪造授权、实现 readiness 或 published 事实。
inspection_id 仅返回值，不冒充 step_id、不参与 portable 比较；与 execution 共用计算核，不共享写路径。
零写集包含：无 step/effect/receipt/manifest/plan/trace/audit、无 latch/emergent/stats/spill/session/lease/fence 变更。
无需推进 lease 不等于无需授权锁；不承诺任意 PostgreSQL READ ONLY 事务可调用含授权行锁的入口。
缺必需输入返回 incomplete/needs_preparation 与受权缺项；无可发送 descriptor，无隐式预构建或受控审计落表。
已知损坏或无授权返回 §6.2 对应诊断，不伪装缺失；execution 不接受 inspection_id 作许可，必须重新取数/授权/seal。

### 3.7 spill/ForkPrefix

首版明确限定为 **spill_archive@v1：持久保存原文＋确定placeholder/skip**，不发出模型可读取的SpillReference，不承诺检索工具、自动preparation或模型调用。Decision中的`SpillReference@v1`仅审计结构：schema_version、完整source逻辑键、source_digest、byte_size、media_type、representation、replacement:Bytes@v1；身份由source逻辑键+内容摘要决定，不含物理row/session/step ID、不注入wire。
`context_spill`字段：W/S/occurrence/section_key、source_manifest_ref、source_digest、content_ref、cached_bytes（可空）、content_hash、rebuild_spec（可空）、recoverable、SpillReference；content_ref为完整持久artifact或plan冻结bytes。recoverable=true必须有算法版本+全部冻结依赖，可从冻结源重建同bytes并验hash；否则必须权威artifact，不能只留projection。
三种表示选择唯一：optional原文完整、授权/持久性合格且profile.allow_placeholder=true时spill_placeholder可用，应用时写spill关系、wire用profile固定placeholder原字节；缺原文时该项不可用，profile允许placeholder则用同一固定字节而不写spill，否则skip；任一placeholder装不下则skip。skip无section/wire字节；Never/required不适用；授权/完整性失败不得当缺失降级。
placeholder按实际替代内容加完整消息/wire开销计tokens，skip内容token=0但保留必要结构开销；不按原文长度/字节数冒充token。trace保存原始摘要、SpillReference或缺失原因、选中表示及最终发出字节/token；首版无在线清理/回填，缓存缺失只在值内同字节重建。旧manifest不因丢失而换placeholder/skip。
重放无法恢复旧字节返回不完整/失败；已 seal payload 若完整仍可按既有 dispatch 门使用，不再装配。
ForkPrefix 内容复用与 wire 共享分离：前者校验子 session 对实际源的授权+artifact/render identity，后者比较真实 canonical wire 前缀。
wire 共享还须 persona/有效参数、provider profile、tool 可见面、marker 布局、实际内容与依赖全部兼容；hash/scope 不是授权证明。
父 parent_through_seq 必须是 v8 稳定切点；只复制 delegable=true 的不可变 slice grant，新 grant_id，不继承 latch/live handle。
授权不足走拒绝而非 fail-open；其他不兼容退普通装配并记原因，cache probe 不作为共享资格。

### 3.8 缺输入与失败

输入不足、完整性、授权、非法profile/预算、冻结源不可恢复、数据库异常的完整判定表唯一见 §6.2–§6.3；不得制造持久前置step。
optional 未物化且profile允许时，仅新Decision可固定skip/placeholder；成功seal后不得再变，授权失败不降级。
缺必需输入无请求/装配写，使用父拒绝receipt；hash损坏/provenance非法不得伪称缺失；DB故障按§6.6整笔回滚。
inspection对应只读返回incomplete/诊断，无receipt；已seal请求不重装，无法恢复冻结字节不得替换内容。

## 4. Feedback、emergent 与统计〔D3〕

### 4.1 Feedback 判定

资格原文承接 raw §2.2 L107–111：仅普通 `complete_effect` 新接受的、当前未被 supersede attempt 的 LLM 成功终局，且流式结果已满足冻结 v8 成功/完整性判据、usage 合法可用、目标 session 非终态且 driver_mode=active、无 sticky cancel 时，才产生一次 Feedback。
这里“成功终局”依 `docs/designs/v8-dev.md` §3.2.2「complete_effect 两层验证/流事实判定」（L569 起）判定，不看 worker 自报 success。
流式按 v8 已允许成功终局结算的形态判资格，不额外等待尾部 chunk 收齐或 final/chunk 等值验证完成；合法 final/计数先到即按谓词计样，迟到 chunk 不补采/撤样。
该谓词在父事务接受结果后、持相关主锁时求值；聚合与 Feedback 原子提交，等值验证 pending 不制造第二次采样入口。

| 入口/结果 | sample/桶更新 | 待消费候选 | ANALYZE |
|---|---|---|---|
| 普通新接受 LLM 成功，谓词全真，非关闭 decision | 恰一次 | §4.3 生产，§4.4 另验消费 | 同事务补全一次 |
| 同谓词且 decision_only=true | 恰一次 | 当次丢弃，不创建待消费集合 | 补全，标 turn_closed |
| usage 缺失、负数、溢出或单位/schema 不合 | 零 | 零 | 不补；explain 返回 unavailable 原因 |
| observation / stream_progress | 零 | 零 | 零，不扩大 v8 observation 写集 |
| receipt replay / 不同 ID 重复终局 | 零 | 零 | 零，不补过去缺项 |
| superseded / 旧 attempt / 拒绝 | 零 | 零 | 零 |
| failure / unknown / 非 LLM | 零 | 零 | 零 |
| repair / reconcile（含成功） | 零 | 零 | 零 |
| terminal drain / 非 active / sticky cancel | 零 | 零 | 零 |
| artifact 发布 token metadata | 非 LLM 样本 | 零 | 零 |

usage 合法可用指冻结 schema 要求的 input/output token 均为非负域内整数；可选 cache 字段缺失记 null，不猜 0。
可选 Bind 计量缺失不阻止 usage 样本，其桶不更新；非法可选计量只拒该计量；provider/LLM 执行 latency 不得写入 bind_latency 桶。
已接受结果的候选字段无效是 advisory 丢弃，不使成功改失败；sample 身份/冻结绑定冲突不是 advisory。

### 4.2 样本与原子更新

完整字段定义（W 与 K 见 §2.1；引用全部具有租户一致 FK）：

| 对象 | 字段与约束 |
|---|---|
| effect_feedback_bindings | E、S、step_id、feedback_profile_ref、profile_digest、bucket_locator_ref、bind_measurement（可空，值/单位/scale）；随 effect 创建冻结 |
| context_feedback_samples | E、feedback_profile_version、accepted_attempt_no、result_digest、usage、bucket_updates、candidate_decisions、parent_command_id |
| sample.bucket_updates | 按桶键序数组：bucket_key、version_before、version_after、accepted_measurements、missing_measurements |
| sample.candidate_decisions | 提取输入位置、kind/hash、accepted/duplicate/over_cap/invalid/turn_closed 原因、profile digest |

sample K=`(W,E,feedback_profile_version)`；feedback_profile_ref 带 W/generation/version 完整FK，version为内容摘要全局唯一别名，必须等于 E 冻结绑定。
bucket_locator_ref 指 FrozenInputs 的 model/query_source/statistics_profile_identity；model 等于冻结请求 model，query_source 是捕获的逻辑分类，禁止当前默认值或 worker 选桶。
bind_measurement 仅本次 Bind 的可信计量，随 seal 写 sidecar、不入 Decision；缺失或非法不更新该桶，usage 仍按原资格采样。
accepted_attempt FK 指向该 effect 的已接受当前 attempt，digest 必须等于父事务接受的 result_hash；写入后字段全不可变。
不同 command ID 不能绕过 effect 终局约束与 sample 唯一约束；receipt 幂等与 sample 去重是不同防线。
已有sample同绑定/attempt/digest→仅核验，不更新桶；调用方伪造绑定与可信持久行冲突是FEEDBACK_BINDING_CONFLICT普通拒绝；可信sidecar/profile/sample彼此不一致则是持久不变量损坏，走§6.2 INFRA_PROTOCOL_VIOLATION受控出口，不以永久拒绝等待operator改表。
profile 升级不追补旧 effect；其余排除面唯一见 §4.1。

合格路径事务步骤（业务资格仅本章定义，锁按 §6.5）：
1. 父命令完成授权/envelope/receipt 分流，取得完整主锁集，确认当前 attempt 的新成功终局与合法 usage。
2. **在调用普通step/session成功聚合之前**（先于Feedback正常增量、亦先于v8规则6成功聚合，唯一顺序见§6.2）核验冻结绑定、sample唯一性与sidecar/profile/sample互一致；持久损坏即按该唯一顺序转§6.2同事务INFRA分支——接受合法effect结算事实、直接选受控收束，不得先聚合成功再改写——并跳过3–5且零context增量；正常路径明确全部桶键/提取规则，禁止处理中再寻找其他session。
3. usage 从已接受结果取得，Bind 耗时从 sidecar 取得；按冻结定位与完整桶键序锁桶，初始化/记录 version_before，计算但不提交中间值。
4. 从已接受 canonical result 按 §4.3 提取、去重、cap，关闭分支丢弃全部可投递候选。
5. 原子写 sample、桶 version/数值、必要生产关系/候选、ANALYZE；父结算/事件/receipt 同事务提交。
6. 任一数据库失败回滚本次结算与全部 context 增量；原 command ID 重发走父协议，不创建“统计补偿任务”。

同E两completion ID：先提交唯一sample/桶+1，后者零增量；先者回滚则后者可唯一接受；响应丢失按§6.6父receipt重放。
跨session同桶与cancel竞争的两序唯一见§7.4 V2/V3：前者样本2/version+2，后者依cancel提交先后为sample0/1，不承诺EMA交换律。


### 4.3 emergent 生产

`context_emergent_relations` 字段：W、S、T、producer_step_id、producer_effect_id、producer_occurrence、target_occurrence、consumer_step_id（初始 null）。
K 为 `(W,S,producer_effect_id)`；唯一 `(W,S,target_occurrence)`；target_occurrence 必须等于 producer_occurrence+1。
生产 step/effect 必须通过复合 FK 指向同 S/T；producer_occurrence FK 指向该 step 的 assembly_plan。
consumer_step_id 只允许 null→同 S/T 且 occurrence=target 的 step，绑定必须随该 step 初始 seal 提交；禁止重绑/清空。
关系不存 ready/running/blocked 等调度状态，不含“重试投递”状态或跨 turn 备用消费者。
`context_emergent` 字段：W、S、producer_effect_id、kind、content_bytes、content_hash、candidate_ordinal、produced_seq、cap_class。
kind 闭合集为 EmergentSkills/EmergentMemory/EmergentSummary；FK 指向上述关系；produced_seq 仅关联生产完成事件作溯源。
content_hash为内容字节SHA-256；唯一键为关系+kind+hash，hash命中仍比完整字节；异字节碰撞按完整性失败分流。生产关系另冻结result_digest与producer plan的来源资源闭包作为authorization_lineage；消费后仍由关系/plan留存，dispatch不依赖已删除候选行。
candidate_ordinal 为 canonical result 中该 kind 数组的原始索引，非行号/seq；同 kind 唯一，去重后保留首个索引。
cap_class 是 profile 中对应 kind 的规则键；每 kind 条数 cap 和每项 max_bytes 必须为正整数，无隐藏默认值。
每个候选还须符合该 kind 的文本/结构 schema；schema 与提取字段路径随 profile 冻结，不调用模型或宿主。
缺可选候选字段 → 空集合；存在但类型不合、过大、非法编码 → 丢弃该候选并记录 invalid reason。
提取步骤固定：按 kind 声明序与数组输入序遍历 → 校验内容 → 计算 hash 并全文去重 → 按 candidate_ordinal 保留前 cap。
去重只在生产关系+kind 内；相同内容可在不同生产关系再次出现，不做 session 永久去重。
溢出记录 over_cap，不能覆盖 pre-execution decision trace；生产端唯一约束与锁内计数检查共同强制 cap。
正常非关闭结果即使候选为空也保留生产关系与 sample 的空结果，便于确定窗口，而不是制造空工作。

贯穿向量 E（fixture 3/9 共用）：S 的 occurrence=1 非关闭 decision 返回同 kind `[alpha,alpha,beta,gamma]`，cap=2。
提取去重后保留 alpha(ordinal 0)、beta(ordinal 2)，duplicate 为索引 1，gamma 为 over_cap；sample=1、关系=1、候选=2。
tools seal 不消费；final_tools=true 全成功后，同 turn occurrence=2 初始装配可消费；§4.4 规定选中与未选中窗口结束。
关闭对照：同内容但 decision_only=true，sample=1、关系=0、候选=0；正常 ready 后 finish_session completed。

### 4.4 consumer_relation 与消费

occurrence 唯一含义：**session 内成功提交的新 decision 装配的逻辑序号**；起始 1。
在已取得 session 行锁时，从保留的成功 assembly_plans 求 max+1（无行视为 0）；禁止 PG sequence、请求计数、claim 次数或 seq。
它不是 v8 semantic ordinal；不改事件编号/normalize；预计算可在事务中引用 n，只有提交才分配 n。
`assembly_plans` 的 `(W,S,occurrence)` 与 `(W,S,step_id)` 双唯一确保同成功装配只有一次；回滚不留空洞。

| 消费资格（全合取） | 不满足时 |
|---|---|
| 来源同 W/S/T，target_occurrence=本次 n | 不选；禁止按 produced_seq 窗口近似 |
| 生产 step 已 succeeded，turn 尚未关闭 | 不消费；tools seal 不是消费者 |
| 当前 session/driver/claim 允许创建新工作，无 sticky cancel | 拒绝新装配或关系逻辑失效，按既有状态门 |
| consumer当前subject对emergent-result资源及继承来源闭包满足§2.4 recall+fold，内容完整，候选在目标单次窗口 | 授权/完整性失败依§6，不能复用producer grant或静默转投 |
| 本次为新 execution 初始 decision seal | inspection/replay/retry 不消费、不分配 n |

消费按 kind 的固定序，再按 producer_occurrence、candidate_ordinal、content_hash 字节序；排序前冻结逻辑身份。
可投递项成为 BoundSection 候选；优化器可因预算不选部分，但所有选择/未选原因必须进入成功 plan。
原子写集：绑定关系 consumer_step_id、删除该窗口全部候选（选中与未选中）、plan 保存原字节/不可变引用及窗口结束原因。
该写集与 latch/spill/trace/manifest、新 step、唯一 LLM slot、首 attempt、父 receipt 同一初始 seal 事务。
成功 plan 的 consumption_records 明确 selected 或 budget_skipped 等原因；未选项不留到 n+1，不退回队列。
若缺必需输入/预算拒绝/授权失败/事务回滚，关系不绑定、候选不删、plan 不留、n 不占。
已 seal effect 执行失败也不恢复候选；retry 复用冻结 payload，不能因候选行删除而缺字节。

| 两个提交顺序 | 关系/候选的结果 |
|---|---|
| 装配提交 → cancel | 消费字节已经冻结，cancel 依 v8 收束；不回插候选 |
| cancel → 装配 | session 锁后见 sticky cancel，拒绝；存量候选逻辑失效 |
| turn 关闭/terminal → 装配 | 既有状态门拒绝，无跨 turn/session 消费 |
| 装配回滚 → 新请求 | 新请求仍可取同 n；候选仍完整 |
| 装配提交响应丢失 → 同 ID | 返原 receipt；不重装、不再消费 |
| 合法 heartbeat → 装配，或装配 → heartbeat | 只改物理 seq，不改变 target occurrence/资格 |

逻辑失效=turn关闭OR sticky cancel OR session terminal，读取即排除；首版无清理命令、候选按R保留，observation/terminal drain不借机增写。

### 4.5 stats

完整 bucket_key=`(W,model,query_source,bucket_kind,statistics_profile_identity)`；kind 首版为 output_tokens/input_tokens/bind_latency。
model/query_source 为冻结逻辑 identity；statistics_profile_identity 包含算法、tokenizer、单位与数值舍入规则摘要。
字段：bucket_key、percentile_digest（排序整数/定点数 JSON 数组）、sample_count、ema_value（可空）、version、updated_at。
初始 version=0、sample_count=0、digest=[]、ema=null；每次该桶有合法测量则 version+1、count+1，updated_at 只观测。
一个 Feedback 对同桶最多提供一个已规范化测量；缺可选测量不创建/更新该桶，sample 中记录 missing。
首版 SQL 事务内维护，不同时开放异步 worker 覆写；性能不足只能阻止接入或另审优化，不破坏原子性。
数字规则：非负计量；token 整数，latency 按 profile 单位转固定 scale 十进制；舍入使用 half-even，禁止宿主默认 float。
EMA 初样本=x；以后 `round_half_even((a*x+(b-a)*old)/b, scale)`，a/b 与 scale 随 profile 冻结。
digest 插入至非降序数组；相等样本紧接已有相等段末尾；仅数值参与 digest，不使用时间戳破并列。
若插入后长度为 513，删除 1-based 第 `ceil(513/2)=257` 项（中位数），得到 512；不得截断尾部或随机采样。
percentile 使用 nearest-rank：n>0 时返回第 `max(1,ceil(p*n))` 项；p75=3/4，p95=19/20，计算为精确有理数。
空 output_tokens 桶：R_o=500；非空不足一个样本不可能；不做宿主插值或默认为 0。
同桶并发按锁序串行化，不丢样本；digest 的驱逐与 EMA 对不同完成序可以不同，portable 比较必须固定输入快照。
非法存量 digest（未排序、超 cap、越界）不可静默修复，计算返回 §6 的 INVALID_STATS，阻止新请求形成。

### 4.6 trace/ANALYZE

`assembly_traces` 完整字段：W、S、occurrence、pre_execution、analyze（初始 null）、feedback_sample_ref（初始 null）。
pre_execution 为 §3.2 decision schema 的不可变值：压力/预算、每 section 估计与实测 token、applied/skipped、marker、共享决定。
analyze 为 actual_input/output、cache_read/creation、measurement_missing、estimate_delta、candidate_decisions、bucket_versions。
ANALYZE 与 sample FK 同次 null→值，必须引用本 plan 的 LLM effect 样本；重复写即使同值也不得重复采样。
未采样时 analyze 保持 null；explain 从 v8 结果/入口与冻结 usage schema 推导 unavailable 原因，不能通过观测补写 trace。
applied 与 skipped 都列原因；缺输入/源漂移/降级/cap 丢弃/ANALYZE 缺失可诊断，不重建论文八条 alert。

## 5. POML 与不可变制品〔D2；发布 D3〕

### 5.1 三层序列化


| 层 | 运行位置/输入 | 输出与权限边界 |
|---|---|---|
| Reader→IR | session 装配前的独立 TS 预构建；冻结文档/数据/依赖 | 标准 IR 数据，随完整包发布 |
| Writer | 同一预构建；IR + presentation/render profile | BoundSection 内容文本或 messages 片段；不决定最终 wire |
| pipeline Serialize | 初始 seal 控制事务；绑定值+有序 plan+provider policy | 唯一 canonical provider 请求，进入 effect payload |

Writer 只决定 section 内容字节；消息边界、最终 role、tool-call/result 配对、cache marker 均由 Serialize 独占。
POML 不得表达 cache scope/marker；catalog 为唯一 scope 来源；`speaker` 仅建议，经 ValidSpeakers 校验与 policy 映射。
同 section 的 POML/静态 source 冲突在 catalog 发布时拒绝，不运行时拼接；所有片段被当数据而非逃逸控制指令。

### 5.2 制品/provenance


| 对象/字段 | 类型与合同 |
|---|---|
| context_artifacts.artifact_identity | 发布目标逻辑 identity（规范结构含种类/来源版本）；W 内唯一，不等于 publication_id |
| artifact.content_bytes/content_sha256 | 完整 bytea 与 SHA-256；必须逐字节验证，不只信调用者 hash |
| artifact.media_type/size/sensitivity | 非空文本/非负字节计数/受控分级；size=实际字节数，受权限 max_bytes 限制 |
| artifact.source_refs/dependencies | 有序冻结来源 identity/version/content digest/slice 归属；依赖闭包不含 live path |
| artifact.provenance/provenance_digest | 构建输入摘要、实现/contract 身份、来源授权证明引用与 build profile；规范内容摘要 |
| poml_documents | W、doc_hash、source_artifact_ref；doc_hash 必须匹配源文档字节，源文档也完整发布 |
| poml_render_outputs.render_identity | 规范五元组：doc_hash、data_hash、presentation、render_profile_digest、dependency_closure_digest |
| render output.ir_artifact_ref/section_artifact_refs | 非空 IR 引用与按逻辑 section_key 排序引用；同包验证，不允许只有一半 |
| render output.build_metadata | tokenizer_version、measured_tokens（逐 section 非负整数）、renderer/Writer/component digests、实现登记键 |
| render output.provenance_digest | 对应完整来源与构建证明；必须与包内 artifacts 的身份及依赖一致 |

render profile 完整覆盖 renderer/Writer/component 实现 digest、plugin/contract 版本、locale/timezone/line ending 及所有影响字节配置。
依赖闭包含 `<let>`、stylesheet、include、标签物化数据的冻结版本与内容摘要；只 hash 外部路径不合格。
闭包按规范逻辑键全序、拒绝同键异版本/异字节；有环或无法闭合拒绝发布；空依赖集合有规范空数组摘要。
data_hash 针对实际冻结标签输入，不是查询字符串；source_version 与 provenance 声明必须能对应同一内容版本。
文档、IR、section及工具schema的原内容以Bytes@v1进入发布合同；其metadata/identity descriptor使用既有canonical profile，原内容不擅改换行/Unicode/`$`键。IR需canonical比较时比较其版本化结构descriptor，必须与opaque原字节域区分（§1.2）。
构建时间/机器等纯观测可保存在请求 receipt metadata，不参与 render identity 或内容等价；影响字节字段不可藏在观测域。
profile/token 测量是发布 metadata，不产生 LLM sample；相同渲染身份 token metadata 不一致视为构建证明冲突。
已发布 artifact 没有 building/running/failed 工作状态；未发布与完整已发布两个事实不构成任务调度状态机。

### 5.3 预构建与发布

接口为 `publish_context_artifact(authorization_context, publication_id, complete_package)`；envelope/receipt 唯一见 §6.4。
完整包类型为 generic_artifact / poml_source / poml_render；每包带目标 identity、全部字节、依赖/provenance、请求 hash 声明。

1. 授权前置与 W 归属；不具发布权限则不读取/占用 binding，未知资源不泄露存在性。
2. 处理 transport、canonical/typed key、历史 receipt/首占；命中历史不重新运行完整性验证。
3. 校验 payload schema、声明 hash、目标范围与 max_bytes/media/sensitivity；枚举全包内容 identity。
4. 当前来源授权与构建 provenance 校验；冻结来源版本漂移时不得伪称所需版本，完整旧版本可按其自身 identity 发布但不能命中新的要求。
5. 确认依赖闭包完整；已经发布的依赖须租户/授权/字节一致，新依赖须同包完整登记；缺依赖整包拒绝。
6. POML 包检查 render identity、IR 与所有 section、profile digest、标签实现登记/readiness、provenance 与 measured_tokens。
7. 按 §6.5 锁内容 identity；核验第二道 artifact/render 唯一约束，hash 命中逐字节与规范 provenance 对照。
8. 无冲突时一次写全部 artifact/document/render 引用及 binding/receipt；不得先落 IR 后补 section。

| 内容身份情形 | 内容处理（对象 receipt 另由 §6.4 负责） |
|---|---|
| 新 artifact identity | 新建完整对象；不分配 session 工作 |
| 已有 artifact identity、同字节与规范 metadata/provenance | 返回既有 identity，不重写 |
| 已有artifact identity、异字节/语义metadata/provenance（任何包类型） | ARTIFACT_IDENTITY_CONFLICT优先；即使同render identity也不覆盖 |
| 已有完整 render identity、同全部产物/证明 | 引用已有 IR/section identities，不因新 publication ID 复制 |
| 已有render identity，所有artifact身份检查通过后，任一产物/映射或aggregate证明不同 | RENDER_IDENTITY_CONFLICT，即使用不同publication ID |
| render profile/依赖闭包改变 | 新 render identity；不得误命中旧缓存 |

发布权≠来源读取权≠session消费权；Bind/seal/dispatch不因发布成功豁免，hash相同亦不合并授权关系。
provenance校验不在事务内查询外网，可信发布者/证明来源唯一见§2.4。唯一冲突裁定：先验包自身完整性与证明有效性，再按§6.4先ARTIFACT后RENDER；①复用artifact identity异内容（含证明）→ARTIFACT_IDENTITY_CONFLICT；②全新artifact identities但同render identity异产物/映射→RENDER_IDENTITY_CONFLICT；③同render、同artifact identities及产物，仅aggregate provenance不同且双方证明均合法→RENDER_IDENTITY_CONFLICT。artifact级证明也改变则回①；非法证明先PROVENANCE_INVALID。三类两提交序均保留先者，后者按此分类。

### 5.4 标签与身份隔离

初集四标签通过 components 层 `component()` 注册，不 fork 引擎，不修改 Writer。

| 标签 | 预构建数据取得 | 允许输出 |
|---|---|---|
| `<schema>` | §2.4 recall，catalog对象membership | table/obj + code |
| `<query-result>` | §2.4 recall_context_query(mode=result)，唯一登记+relation闭包/参数/输出约束 | table + code |
| `<migration>` | §2.4 recall，migration/catalog版本membership | code + list |
| `<query-plan>` | 同入口mode=plan，只读EXPLAIN非ANALYZE | code + p |

硬规则 1：仅 stock 内置 IR 节点（可含 env），属性可用 presentation/markup-lang/serializer；禁止自定义 IR 标签。
硬规则 2：标签及 alias 的解析/执行不得跨 render identity 污染；native/compat 同受约束，generation 前缀不是证明。
`plugin_specs.poml_components` 为 generation 发布增量：标签名、alias、component digest、contract version、允许 IR 节点闭合集。
登记键继承 `docs/designs/v8-dev.md` §4「插件协议与世代」（L713–751）的 `(generation_id,identity,plugin_version,handler_name)`。
query_id不由component/alias解析器另建映射；四标签仅消费已冻结输入，query描述及结果经§2.4唯一路径取数、builder签名后随完整包发布。P2 readiness 必须验证标签/alias 解析、依赖闭包、实际实现 digest；同不可变 implementation 可被多个 generation 共享。
Python 不注册标签，只读写源文档/IR/产物 canonical 数据；TS 预构建工具持引擎，标签求值仅消费冻结输入。
独立进程、独立 registry、经验证的 generation-aware resolver 是待验证选型，不强制一代一进程；失败阻止跨身份支持发布。

### 5.5 缓存和保留

权威 artifact/render output 与冻结 spill 关系均保留；可重建展示/索引不是权威，缺失可值内重算，本版不增加在线清理/回填写命令。

## 6. 命令、receipt 与并发协议〔D3〕

### 6.1 入口清单

入口仅有 R（只读）、P（既有父命令内部增量）、O（独立对象写命令）三类；不存在无 receipt 归属的第四类 mutation。

| 入口/内部操作 | 类别/receipt 所有者 | 写集与失败归属 |
|---|---|---|
| plan_assembly / bind_values / optimize_assembly / serialize_assembly | R，值计算无 receipt | 零写；返回 §6.2 类型化诊断 |
| capture_assembly_inputs / explain_assembly / inspect_assembly | R，无 receipt | 读取/锁不等于纯 IMMUTABLE；诊断返回值，无审计落表 |
| get_effective_params | R，无 receipt | 纯值合并；INVALID_PARAMS |
| recall_context_query | R，无receipt/证明登记 | §2.4唯一登记解析+recall门；返回数据/诊断，成功与拒绝均零持久写 |
| create_step 初始 decision / prepare_step、seal_batch 初始分支 | P，实际最外层 v8 命令 | §3.5；§6.2–6.3 拒绝与重放 |
| tools seal / retry_effect | P，原 v8 命令 | 零新装配/消费；只用既有冻结请求 |
| complete_effect 的合格 Feedback | P，complete_effect | §4.2 原子增量；不另 command ID，不扩 v8 内部 audit 五类枚举 |
| request_cancel/finish_session/fail/repair/reconcile | P，原 v8 命令 | v10 只计算关系逻辑失效，无新增清理或采样写集 |
| manage_context_generation(stage/activate/fail_build/revoke_active) | O，v10显式管理命令 | 实现v8 §4发布流程的receipt入口；catalog/policy/profiles/defaults/plugin_specs同包，无第二发布器 |
| initialize_context_session | O，v10显式初始化命令 | 建session与§2.3内容绑定同事务；不是虚构的v8父命令 |
| manage_context_permission | O，operator根对象命令 | §2.4许可签发/撤销，独立object receipt |
| publish_context_artifact | O，对象 receipt | §5.3 包完整发布，§6.4 |
| publish_persona_version | O，同一对象 receipt 机制，不同 kind | version 与受控指针 CAS；§6.4 |
| spill/cache 清理与数据销毁边界 | 非新增运行入口 | 首版不提供在线清理命令；显式离线整组销毁见 §2.1 |

F-08结构清单完成，管理/初始化合同如下；协议仍待父控制器L4复审，不以流程名推定receipt已继承。
**generation指针唯一合同**：作用域固定为workspace；本文管理的generation有唯一W归属、跨W引用拒绝（共享全局不可变implementation不受影响）。`context_generation_pointer(W,active_generation nullable,revision bigint,last_operator,last_changed_at,last_command_ref)`是唯一active指针，不从状态=active的行反推/另存缓存指针；非NULL目标仅可为同W已发布active代；禁止直接回指retired恢复服务，恢复必须发布全新generation identity（见下文）。首个成功stage在同一O事务建NULL/revision=0行，指针命名空间锁串行首次建行；请求拒绝/回滚不留空行。尚无行与NULL对新装配均NO_ACTIVE_GENERATION、零控制写；只读入口不得补建行。
指针/revision写者全集仅：stage首次初始化；activate的building→active切换（旧目标非NULL则active→retired）；revoke_active承接既有v8强制下线，仅显式置空。后两者同事务CAS完整expected_active_generation+revision并revision+1，操作者/时间/目标/旧新revision随O receipt审计；同ID重放与拒绝不推进。fail_build、readiness报告、初始化/装配与后台扫描不得切指针；首版不开放其他受权切换入口，也不允许自动回退。
**共用O合同**：两命令使用§6.4的(W,publication_id)身份域、已路由command_kind及三类typed key；payload/完整来源/CAS均进入command_request_hash，不混用session command_id。前置授权→typed key/历史receipt/首占→新请求guard→原子写与receipt；成功/拒绝均固定结果，历史重放不读今日persona/defaults/readiness。管理权限仍作重放前置；下述新请求guard不得追溯覆盖历史accepted O receipt（含旧payload）：同ID同hash返回原结果，不重验新guard、不改原receipt、不重做指针/状态/drain写入。

| 命令 / 完整payload比较域 | 当前权限、锁/CAS与成功写集 | 稳定结果与crash两序 |
|---|---|---|
| manage_context_generation(stage)；target_generation、action=stage、完整v8 specs/implementations/members、catalog/policies/assembly/feedback/latch declarations/model_defaults/components/query_registry与全包digest | GENERATION_MANAGE+来源权限；统一§6.5子序→object binding→内容identity全序；创建building候选/不可变成员增量与必要的首次空指针同事务，复用同键同digest implementation；同identity异包或同implementation键异digest先拒GENERATION_IDENTITY_CONFLICT；同target同完整包的新请求若retired拒GENERATION_STATE_MISMATCH，否则返回已有generation/状态且不重置为building | accepted/GENERATION_STAGED含generation+digest；同identity异包GENERATION_IDENTITY_CONFLICT、依赖/规则非法GENERATION_PACKAGE_INVALID；无半包 |
| 同入口activate；action=activate、target_generation、expected_state=building、package_digest、expected_active_generation/revision、完整readiness证明 | 同上；预发现旧/新generation集，锁内重扫不一致则回滚重取；所有路径均用§6.5指针→generation子序，之后binding；验证可信worker的全部需支持driver/成员digest与当前readiness，CAS building→active、旧active→retired及指针revision+1 | accepted/GENERATION_ACTIVATED；状态/CAS失配GENERATION_STATE_MISMATCH/GENERATION_POINTER_MISMATCH；缺ready IMPLEMENTATION_NOT_READY，不切指针 |
| 同入口fail_build；action=fail_build、target_generation、expected_state=building、package_digest、受保护构建失败证明/原因 | GENERATION_MANAGE；同序锁；证明是扫描/依赖/预加载失败，CAS building→failed；不得改active指针或已绑定工作 | accepted/GENERATION_BUILD_FAILED；状态失配GENERATION_STATE_MISMATCH；不把运行handler故障当构建失败 |
| 同入口revoke_active（既有强制下线的具名O包装）；action、target_generation、expected_state=active、package_digest、expected_active_generation/revision、必填replacement_generation=NULL、致命缺陷原因 | GENERATION_MANAGE覆盖下线目标；§6.5全session预锁+指针优先+generation全序+锁内重扫；验证置空payload、同W目标状态/包及完整指针CAS，且target_generation=当前非NULL指针；active→failed、指针置NULL/revision+1与v8全套drain同事务，每受影响session派生受控父命令/receipt（见下段），审计落v8 session域 | accepted/GENERATION_REVOKED含指针旧新值/revision及各drain结果；replacement缺字段/非NULL或包非法GENERATION_PACKAGE_INVALID；状态失配GENERATION_STATE_MISMATCH，指针/CAS或target与指针不符GENERATION_POINTER_MISMATCH；普通handler故障不得使用 |
| initialize_context_session；target_S、driver、persona_id、expected_pointer_revision+expected_persona_version、明确defaults_ref（generation/version/digest）、参数schema版本与全部初始配置 | SESSION_INITIALIZE+persona/defaults的当前recall；目标S缺行亦先取session身份事务锁，存在则锁行→grant/slice/管理许可→defaults generation→object binding→persona指针/不可变来源；锁内核对双expected与版本，§2.3合并/校验并CAS“session不存在” | accepted/SESSION_INITIALIZED含S、实际persona/defaults版本、物化model/params及content_binding_digest；目标已存在SESSION_IDENTITY_CONFLICT；缺persona/defaults或其generation未发布SESSION_INPUT_INCOMPLETE、已failed GENERATION_REVOKED；非法参数INVALID_PARAMS；双expected失配PERSONA_POINTER_MISMATCH；拒绝零session/内容半写 |

stage成功只表示候选完整入库，不表示active；预加载在事务外由受信worker完成；activate仅核v8当前readiness事实与包内签名证明（绑定W/target_generation/package_digest/driver/implementation_digest、loaded=true、有效期/可信principal，信任锚由§2.4 BUILD_ATTEST许可保护），证明随receipt留存，不增无receipt登记写入口。已有building候选的扫描/依赖/预加载失败必须调用fail_build（同包不同action使用新publication_id）持久failed；未形成候选的非法请求只有拒绝receipt，不能先active再下线。revoke_active完整承接v8 §4下线七条（含三合取、既有cause/取消优先及全session预锁/重扫），仅补O receipt与统一指针锁位，不另造下线状态机；与activate共用同一指针先行子序，不得先锁generation再锁pointer。新增generation digest覆盖v8成员及v10增量全包，原成员算法不变。
**恢复服务唯一流程**：下线显式置NULL后，operator以全新generation identity执行stage→事务外readiness→activate；可复用旧代同键同digest的全局不可变implementations，但必须为新代插入新成员行，v10包内generation归属/引用绑定新代，重算完整package_digest；不得stage旧retired identity充当复活。
恢复代readiness必须重新绑定W/新generation/该package_digest及全部driver/implementation_digest，旧代证明不可挪用；stage不改既存NULL指针/revision，activate须CAS当前NULL/revision。恢复代正常building→active，若再发现致命缺陷仍active→failed，按同一revoke_active协议置空并drain，无特殊恢复状态边。
禁止的是retired成为新装配的服务指针，不是撤销retired既有工作：已绑定step/job的dispatch/seal/retry及in-flight沿用冻结v8规则，不新增retired→failed/active边。NULL期间新装配NO_ACTIVE_GENERATION零控制写；claim后拒绝仍须独立显式yield，不隐式释放lease或递增fence。
**revoke_active×v8内部审计域接合（每session受控父命令）**：外层O命令持有(W,publication_id)管理身份、active指针处置与总结果，自身不充当任何session的父命令，O身份仍不混用session command_id（§6.4合同不变）。对每个受影响session在同一O事务内定义session域受控父命令/receipt身份：授权直接继承外层O的GENERATION_MANAGE判定（含下线目标权限；恢复代的stage/activate另按各自来源/管理权限判定），不设第二授权入口、非调用方可指定；parent_command_id由版本化受控派生函数从O完整PublicationIdentity与目标session_id确定性派生，派生域与普通调用方command_id构造上不冲突（普通session命令不得命中该域，命中即实现缺陷）；command_request_hash覆盖O command_kind/目标generation/全部CAS字段与该session的drain作用域，同O重放对同session派生同command_id同hash；session域父binding/receipt随drain同事务首占，receipt结果引用外层O的binding_locator/publication identity作关联字段。v8内部子操作（generation_revocation_drain及伴随的shared_cancel_closure/compact_terminal_abort）继续绑定该session域父receipt，按v8 §3.1.2五类闭合集与internal_op_ordinal分配/唯一性规则原样执行（不扩枚举、不改event_key五元组派生域），逐session独立编号。外层O result逐session枚举drain/收束结果与各自父receipt引用；提交前crash（含全部派生父receipt与审计）整体回滚，提交后同O ID重放只返原O结果、不再次drain、不追加审计行。
初始化是P0基础写入口：固定已发布persona/defaults输入的创建/幂等/原子性先验5-I0；真实persona发布竞争/覆盖/版本变化在P1扩展5-I1，不把基础写安全推迟至P1。初始化仅创建ready session，driver_mode=active、driver_epoch/session_fence初值0、无lease/active_step/drain_step/turn/step/effect，其余v8必填初值按冻结schema；不生成user/turn事件、不自动claim。不同命令争同S只有一者创建，后来者SESSION_IDENTITY_CONFLICT；同命令响应丢失返回同S/原版本，绝不另造S。persona发布与初始化共用persona指针锁：更新先→旧expected初始化拒；初始化先→冻结旧版本后更新，新session可显式请求新expected。session身份锁不得在授权/对象尾段后补取。
上述各action提交前crash：业务/binding/receipt全回滚，原ID重试；提交后响应丢失：全部业务与receipt同时可见，同ID只返原结果。并发相同ID由object binding串行，异payload只写IDEMPOTENCY_CONFLICT；CAS失败首占拒绝，新输入必须新ID。无执行网络/handler、无session preparation账本。

### 6.2 初始装配命令

继承 v8 §3.1.2「核心命令与 receipt 幂等」（L337–360）的 envelope/typed key/授权前置/首占；算法不另写。
成功 result_canonical 扩展只含原 seal 结果引用及 manifest_hash、occurrence；request_hash 仍为既有 effect hash，不是命令 hash。
执行顺序：授权调用上下文→请求键→历史 receipt→binding 冲突/声明 hash→跨命令历史 seal lookup→新请求控制 guard→输入/计算→授权/seal/原子提交。
跨命令命中既有 step/batch identity 必须比较原冻结 slot/request；相同只返回原 seal 并写新父 receipt，不读取新 stats/artifact 重装。
新请求 guard 按既有 session/driver/claim/fence、turn/compact、generation 与 seal 规则执行，不用本章诊断替代原码。
以下稳定code仅用于v10增量；前置授权失败在receipt域外，普通计算拒绝outcome=rejected_mismatch、控制与事件零写；可信持久不变量损坏不是普通计算拒绝，按表后受控INFRA分支处理。

| 失败域（同域首中序） | code / 写集 / 恢复 |
|---|---|
| 当前来源/参数授权失败 | GRANT_DENIED / 父 receipt（前置则独立安全审计）/ 恢复授权后新 ID |
| profile/schema/kind/limit非法；latch提案/声明不一致 | INVALID_ASSEMBLY_INPUT 或 LATCH_PROPOSAL_CONFLICT / LATCH_DECLARATION_MISMATCH / 父receipt / 修正版本或新key，不改历史latch |
| stats 非法 | INVALID_STATS / 父 receipt / 修复数据新 ID，不静默混桶 |
| artifact hash/provenance 损坏 | ARTIFACT_CORRUPT / PROVENANCE_INVALID / 父 receipt / 受控恢复或新版本 |
| 必需输入不足 | NEEDS_PREPARATION / §6.3 / 不走 INFRA |
| 冻结源无法同字节恢复 | FROZEN_INPUT_UNAVAILABLE / 父 receipt 或只读 incomplete / 恢复同字节 |
| Never/required 超预算、终档无解 | ASSEMBLY_BUDGET_EXCEEDED / 父 receipt / 新配置、新 ID |
| 最终消息或配对非法 | INVALID_PROVIDER_REQUEST / 父 receipt / 修正 profile，新 ID |
| 调用输入声称的profile/绑定与完整可信持久状态不符 | FEEDBACK_BINDING_CONFLICT / 父拒绝receipt，零结算/context/控制写 / 更正输入新ID |
| 可信持久sidecar/profile/sample之间不变量损坏（非调用方伪造） | INFRA_PROTOCOL_VIOLATION / 下述受控fail-closed+drain，不适用普通拒绝零控制写 / 禁止原地修复或补采 |

授权失败先于任何缺项暴露；多缺项按§6.3排序；其余按输入结构→identity边界/碰撞→完整性→缺失→预算→wire顺序；同域按source规范键。identity诊断及receipt归属见§2.1，不让索引异常替代稳定结果。
持久绑定损坏限v10 manifest应有的sidecar缺失/摘要或FK不合，或已有sample与可信effect接受事实矛盾；经SQL核验，不由worker提交failure_code。**唯一聚合顺序（同事务不两读，§4.2步骤2回指本条）**：① v8 envelope/attempt证据与成功decision语义校验 → ② **在调用普通step/session成功聚合之前**核验v10持久绑定（冻结绑定、sample唯一、sidecar/profile/sample互一致）→ ③ 发现损坏时接受合法effect结算事实、直接选受控INFRA收束，不得先运行普通成功聚合再改写；实现若已暂写成功聚合态，该暂写不构成本段意义的既存终态。普通新终局complete_effect已通过v8证据门时，父层仍按事实接受attempt结果（成功不能改成provider失败），但跳过全部Feedback写与普通成功聚合、同事务调用v8 §3.1.1第(3)类内部fail_session(INFRA_PROTOCOL_VIOLATION)，抑制正常新工作续行；父accepted receipt保留原结算结果并附context_failure与受控failure/drain结果，**不是普通拒绝receipt偷偷修改控制态**。
恢复扫描经既有recovery claim/reconcile受控事务重新验证持久损坏后调用同一内部出口；遵守完整八位预锁集（含所有drain对象）、有效job lease不抢占。complete_effect若发现未预锁drain对象则整事务回滚重取，不倒序补锁。入口/父结算/INFRA控制态/既有审计/父receipt同事务；inspection、observation、repair和历史receipt重放均不得借诊断增加context写或补采。
未dispatch effect按既有cancelled_before_dispatch；in-flight按unknown/pending/皆无三分支drain，session立即failed/INFRA_PROTOCOL_VIOLATION、未完成step按v8 INFRA规则收束。**两分支精确冻结**（均以前述聚合前核验为前提）：
- 触发completion为closing decision（decision_only=true）→ effect终态succeeded、结算事实与结果事件保留，进入本次处理时非终态的step按INFRA收束（failed_terminal/INFRA_PROTOCOL_VIOLATION，drain三分支同款）、session failed/INFRA_PROTOCOL_VIOLATION；不走普通成功关闭，无规则6的step succeeded/session ready。
- 触发completion为非关闭decision（含冻结tools plan）→ effect终态同样succeeded、真实result/冻结plan字节保留，step/session收束同上。两分支均将已有plan作废但保留字节：tools seal按terminal session既有seal门拒绝、不创建后继step；不调用finish_session、无completed、无Feedback写，父accepted receipt保留原结算与context_failure。
**两分支仍必须进入v8-dev §1.2唯一turn-finalization reducer**：INFRA terminal failure是原优先级(4)的终结候选，不因跳过普通成功聚合而跳过reducer，也不先产出成功end再覆盖。plan作废后不再算待续行工作；在无已有end、无未决unknown、无pending、无sticky/provider cancel且无其他待续行工作等原资格满足时，同事务追加唯一`turn/end {interrupted:true, reason:failed}`（失败end+1、正常成功end+0），占用原canonical `turn_end_key`槽位。
其他槽位状态、unknown/pending/cancel与已有end一律按该唯一reducer三段顺序及v8-dev §3.1.2事件键/槽位/repair supersedes规则处理；不得无条件断言总end+0或+1、另定义资格/优先级、覆盖已有end或产生第二个canonical end。
**「既存终态/failure cause保留」一律限定为进入本次处理前已持久化的状态**（不含本事务暂写出的成功聚合态——唯一顺序②使其本不发生）；已有terminal session/step不改原终态及failure_code/outcome_code，尤其WORKSPACE_LOST/既有INFRA cause保留；仅其原合法drain入口收束。禁止UPDATE/DELETE不可变sidecar/profile/sample、删除receipt重跑或补采旧成功；恢复业务只能经新session/新合法工作，不是修旧成功。
提交前crash全部回滚（含reducer事件/槽位与父receipt）；提交后丢响应按同completion ID重放父原receipt/结果（含context_failure），无二次fail/sample/end，原canonical槽位不变；新completion ID遵循terminal/drain门，不能靠换ID绕损坏；扫描幂等核验不重复改cause。
inspection 使用相同 code 的只读返回值，无 receipt/audit；它的缺项语义标识为 incomplete/needs_preparation。
计算返回的可预期拒绝不触发 session failed；真实 assemble 异常按 `v8-dev.md` §3.1.1「fail_session 第(3)类 INFRA」（L286）受控处理，非调用方任选失败码。
事务故障先整笔回滚，INFRA 若需持久收束必须经既有合法受控入口；不提交半 plan、不假造拒绝 receipt 已落库。

### 6.3 needs_preparation

稳定语义名 needs_preparation；父 receipt `outcome=rejected_mismatch`、`code=NEEDS_PREPARATION`，不扩 v8 四 outcome。
结果字段为 code、missing_inputs 数组；每项 logical_source_identity、required_version/dependency_digest、missing_class。
missing_class 闭合集 missing/unpublished/version_unavailable；未完成包视 unpublished，不引入 building 工作态。
数组按 canonical `(logical_source_identity,required_version,dependency_digest,missing_class)` 字节序；只描述受权资源。

| 时点/操作 | session/lease/fence | receipt/重试结果 |
|---|---|---|
| 正常 claim 后首次拒绝 | 保持 claimed 与原 lease/fence | 首占 ID，固定缺项；无隐式 yield |
| 制品未齐，同 command ID | 不重做 guard/装配 | 授权前置后返回原拒绝 |
| 制品齐，同 command ID | 同上 | 仍原拒绝，不改 receipt |
| coordinator 独立显式 yield | 遵守 checkpoint/lost，释放后 ready 或既有收束 | 独立控制操作，不是拒绝副作用 |
| 新 claim + 新 command ID | 当前 envelope/lease/fence 才有效 | 重新授权捕获；满足则新初始 seal |
| 缺 artifact 的 inspection | session/lease/fence 不变 | incomplete，零 receipt/审计 |

显式 yield 精确继承 `docs/designs/v8-dev.md` §4 第4条「in-flight / NO_ACTIVE_GENERATION」（L740）及 §2.2「checkpoint/lost」（L192–194）。
coordinator 不得持控制事务等待制品；备齐与发布由调用方事务外负责，不能把旧 claim/lease 原样带入新执行身份。

### 6.4 对象发布 receipt

独立命令形态：`publish_context_artifact(auth,publication_id,package)` / `publish_persona_version(auth,publication_id,version_and_pointer)`，以及§6.1 manage_context_generation、initialize_context_session、§2.4 manage_context_permission，均复用本节O协议。
envelope 含 W、publication_id、command_kind、transport 声明 request_hash、完整 payload；不含 session claim/lease/fence 作为授权替代。
persona payload 含完整 version 内容、是否设置 current、expected_pointer_revision；operator 权限独立于 artifact 发布权。

| 对象 | 完整字段（W 隐含） |
|---|---|
| object_command_bindings | 完整PublicationIdentity@v1 canonical bytes（含publication_id）、binding_locator、first_key_kind、first_key_value、first_outcome、command_kind |
| object_command_receipts | binding_locator、key_kind、key_value、command_kind、outcome、code、result_canonical、result_hash、declared_hash（可空）、created_at；原publication identity经binding引用 |
| object_ingress_rejections | security_context_id（受保护UUID）、transport_key、原报文/收到的完整identity、code、result_canonical；ID无效/超限或binding_locator碰撞时使用 |
| object_authorization_denials | security_context、command_identity、code=GRANT_DENIED；同安全上下文同命令幂等一行，独立O审计域，不与v8 session command_receipts共享命名空间 |

binding逻辑身份为完整`PublicationIdentity@v1`，物理唯一`(W,binding_locator)`；receipt唯一及FK分别为`(W,binding_locator,key_kind,key_value)` / `(W,binding_locator)`，严格采用§2.1固定81字节键，不再把publication全文拼进派生identity。访问binding/receipt前必须比完整publication identity；locator碰撞只落ingress稳定拒绝、不得关联既有binding；内容identity超限/碰撞则落本合法binding下的普通receipt，均不覆盖原对象。
outcome 独立闭合集 `{accepted,rejected}`；accepted key 只用 canonical_request_hash；command_kind 取已路由端点，payload 声明只校验不当存储来源。
declared_hash 仅恰一可解析 header 时有值，缺失/重复/损坏为 NULL 并在拒绝 result 记形态；accepted 必须非空且等于 computed，不以伪 hash 填拒绝行。
typed key 三值为 canonical_request_hash/rejection_fingerprint/transport_rejection_key；算法精确复用 v8 §1.3「canonical JSON 与 render」（L77–78），只改变作用域。
request hash 覆盖 command kind、目标逻辑 identity、全部内容、依赖/provenance、pointer CAS 与影响结果的 metadata；声明 hash 不入键。
判定顺序与占用/写集如下（O 表示 object binding+receipt；无业务写均不改 session/event/sample）：

| 首中条件 | outcome/code | binding / 其他写集 | 重发 |
|---|---|---|---|
| 授权前置不通过 | 返回 GRANT_DENIED，域外 | 不查/不占 O；仅独立授权拒绝审计 | 重新授权可进入，不泄漏历史 |
| ID不可归属、超限或binding身份digest碰撞 | rejected/MALFORMED_TRANSPORT 或 IDENTITY_TOO_LARGE 或 IDENTITY_DIGEST_COLLISION | 不占binding；§2.1 ingress拒绝 | 原报文按transport key重放 |
| 已有同 typed key receipt | 原 outcome/code | 零写，含零 audit 增量 | 原结果；不重验证内容 |
| 已占 ID，异 typed key | rejected/IDEMPOTENCY_CONFLICT | 首 binding 不改，写冲突 receipt | 原冲突；不毒化首请求 |
| 有 ID 但 transport 畸形 | rejected/MALFORMED_TRANSPORT | 首占 O，transport key | 原拒绝 |
| transport 合法但不可 canonical | rejected/INVALID_CANONICAL_PAYLOAD | 首占 O，fingerprint key | 原拒绝 |
| 声明 hash 不等 computed | rejected/REQUEST_HASH_MISMATCH | 首占 O，computed key | 只改 header 同 ID 仍原拒绝 |
| identity超上限/digest命中异完整identity | rejected/IDENTITY_TOO_LARGE 或 IDENTITY_DIGEST_COLLISION | 可归属ID首占O；ID自身不可归属走§2.1 ingress | 不交给btree异常/不覆盖旧键 |
| 当前来源/目标权限不足 | rejected/GRANT_DENIED | 首占 O，无对象 | 修复权限后新 ID |
| 缺完整 bytes/依赖/包成员 | rejected/ARTIFACT_INCOMPLETE | 首占 O，无半包 | 补齐后新 ID |
| hash/size/media/schema 非法 | rejected/ARTIFACT_INVALID | 首占 O，无对象 | 修正后新 ID |
| provenance/依赖身份不符 | rejected/PROVENANCE_INVALID | 首占 O，无对象 | 新完整证明、新 ID |
| 实现未 ready/未验证 alias | rejected/IMPLEMENTATION_NOT_READY | 首占 O，无对象 | 通过验证后新 ID |
| artifact identity 同名异内容 | rejected/ARTIFACT_IDENTITY_CONFLICT | 首占 O，不改已有内容 | 新 ID 也不能绕过身份冲突 |
| render identity 同名异产物/证明 | rejected/RENDER_IDENTITY_CONFLICT | 首占 O，不改已有包 | 新 ID 仍冲突 |
| persona version 异内容/参数非法/CAS 失配 | rejected/PERSONA_VERSION_CONFLICT 或 INVALID_PARAMS 或 PERSONA_POINTER_MISMATCH | 首占 O，version/指针零部分写 | 修正 payload、新 ID |
| 管理/初始化的新请求guard失败 | rejected/§6.1或§2.4具体code | 首占O，零业务写 | 同ID原拒绝；更正后新ID |
| 管理/初始化全部通过 | accepted/§6.1或§2.4具体code | 首占O+该action完整写集 | 原结果，零重复初始化/切指针 |
| 全部通过，新或同身份同内容 | accepted/PUBLISHED | 首占 O+必要完整对象/指针更新 | 原 identity；无重复发布 |

ID域边界/碰撞先于binding查重；transport路径选择先于查重，三类typed key共用查重，畸形transport不尝试canonical/fingerprint。表中内容行按command_kind路由：artifact包才适用ARTIFACT/RENDER/包证明行，persona只用其行，generation/初始化/管理许可使用§6.1/§2.4 guard；所有类型共用前置授权、identity、typed key与首占规则。
业务拒绝也首占 publication_id，不能用同 ID 补齐后重新执行；result_canonical 固定 code、受权 target 与成功 identities/拒绝原因。
错误多发时严格表序；ARTIFACT_IDENTITY_CONFLICT始终先于RENDER_IDENTITY_CONFLICT（§5.3三类），不能因包类型更换优先序。persona三类按version冲突→参数非法→指针CAS；管理/初始化按§6.1列出的状态/身份→参数/证明→CAS顺序，不存在任意挑code。
对象与 receipt 全同事务；普通失败不能 rollback 掉稳定拒绝；DB 故障不伪装为业务拒绝，整事务回滚后原 ID 重发。revoke_active的外层O result按session枚举各drain/收束结果及其session域父receipt引用（§6.1接合段）；O与全部派生父receipt/内部审计同事务，提交前crash全回滚、提交后同O ID重放零drain零审计增量；O身份域与session command_id命名空间构造上分离，不同W同publication_id或不同session同名ID均不串读。

### 6.5 锁序与并发

继承 `docs/designs/v8-dev.md` §3.1.2「八位主锁序」（L356）为不可改变的子序列：
`session → grant/slice → generation → step → effect → attempt → turn_end_slot → compact`。
相关 v8 锁全部取得后才进入固定尾段：`Feedback 样本/绑定 → stats 桶 → latches → emergent 生产关系/候选 → spill 关系 → plan/trace`。
统一完整序为：**全部已预锁sessions → grant/slice → 管理许可 → active-pointer命名空间锁/行 → generation身份锁/行全序 → step → effect → attempt → turn_end_slot → compact → object binding/receipt及内容identity（若涉及）→ context尾段**。pointer与generation是主序generation位内子序，所有入口共用；缺行身份锁也在所属位取得。多session按v8 UUID binary/非UUID UTF-8序；generation按(W,generation identity)全序，其他同位按完整键字节序，stats按§4.5、不依赖locale。不需要的位跳过：stage/activate/fail_build不取session且永不后取；只读绑定generation的tools seal/retry/recovery无需pointer，但不得取generation后再回取pointer；新装配读active指针必须先pointer后generation。
父 v8 receipt/binding 首占仍先于业务 mutation；尾段不得发明嵌套命令或反向要求父 receipt 的锁。
需要创建的新 step/effect 行在主协议内原子构造，不能持尾段锁后再取其他既有主序对象的锁。
输入获取先确定全部授权与主锁候选集；持尾段锁后发现遗漏时整事务回滚重试，不倒序补锁。
计算 stats 冻结值可用 MVCC 读，无需为只读 Plan 占更新锁；消费写需 session 串行，Feedback 桶更新必须持桶锁。

| 路径 | 持锁集合与两序裁定 |
|---|---|
| completion 同桶跨 session | 各自先持所属 session/主锁，再按桶全序；桶锁后不得再锁任何 session/grant/generation |
| 同 E 重复 sample | session/effect/attempt 串行+sample 唯一键；先提交者唯一写，后者无统计增量 |
| 消费 vs cancel；关闭后请求 | cancel两序由session锁裁定；生产decision关闭只验关闭后拒绝（3d-close），不构造不可达消费先行序 |
| generation 下线 vs seal/allocation | 下线先预锁目标generation全部已关联session（含终态历史step归属），再授权/管理许可→pointer→下线目标generation；持generation排他锁以READ COMMITTED新语句快照重扫，发现任何未预锁session/遗漏generation即整笔回滚、全序重取，不尾段补锁。置failed/指针/每session派生父receipt/drain/O同事务（父receipt在该session预锁后、drain前写入，不新增锁位）；有限重试仅在新关联最终停止且公平调度时保证，v8七条不弱化 |
| 发布 vs 消费 | 发布仅完整 immutable 对象；消费读已提交对象，不请求发布事务的 session 锁 |
| 两发布事务同 identity | grant/slice→管理许可→对象binding→内容identity全序→原子包；后者同内容复用或稳定冲突 |
| 初始化×persona发布；activate×下线/activate | 初始化先S身份锁→授权→defaults generation→binding/persona指针尾段；persona发布无session/generation回取。activate与下线都先pointer再相关generation全序；预读锁集在锁内不符即整体重试，同expected竞争仅一者切换，另一者稳定状态/CAS拒绝。首次stage用同pointer命名空间锁防双建；不存在G→pointer反向边 |
| 撤销×capture/seal（行锁实现） | 撤销在授权锁前提交则拒；装配先持锁则撤销阻塞至seal提交，之后下一dispatch重验拒。不得声称capture后撤销能抢先提交 |
| 授权CAS替代实现 | capture读revocation_version后、seal提交前设调度点；撤销推进版本先提交→CAS失败回滚/重判拒，seal CAS先提交→撤销后影响下一dispatch；不得把此调度当行锁两序 |

多桶、多个候选唯一键首次插入也按上述全序；缺行的唯一冲突须锁内重读，不做读-改-写覆盖。
数据库 deadlock/serialization 故障必须回滚整笔，无部分 receipt；同原始命令重试，不能返回伪稳定业务拒绝。

### 6.6 crash/replay

| 崩溃切点 | 可见性 | 恢复入口与不得发生的行为 |
|---|---|---|
| 输入捕获/计算之后、初始 seal 提交前 | 无新增 step/plan/slot/消费/occurrence | 同父 ID 重发；不得恢复一个未 seal step |
| 初始 seal 提交后、响应前 | 完整 step+LLM+attempt+manifest/receipt | 同父 ID 读原结果；worker 只派发已持久 payload |
| NEEDS_PREPARATION 拒绝提交后 | 只有稳定父 receipt/binding | 同 ID 即使补齐也拒绝；新 ID/当前 claim 才能重装 |
| completion 增量中途 | 父结算与 sample/桶/候选/ANALYZE 全回滚 | 原 command 重发；无异步补样本 |
| completion 提交后、响应前 | 全部终局增量可见一次 | 父 receipt replay；无第二样本或候选 |
| 预构建中途/部分上传 | 无已发布对象 | 外部调用方自行恢复，不创建 preparation 账本 |
| 发布校验或写对象后、提交前 | 对象/关系/binding/receipt 全无新增 | 原 publication ID 重发完整包，无半发布 |
| 发布提交后、响应前 | 完整对象与 receipt 同可见 | 原 ID 返回原 identity，禁止再次 renderer |
| 并发同 render/artifact identity | 一完整包或原有包 | 同字节复用，异产物稳定冲突；两提交序都测 |
| persona version/指针提交前后 | 仅旧全态或新全态 | 原 publication ID 重放不再次移动指针 |

重放历史 receipt 的授权前置仍成立；历史成功不是旧 owner 的新写许可，不重新验证今日输入再改历史结果。

## 7. 开发路线与验收〔D3〕

### 7.1 前置门

| 三重门 | 必需产物 | 未满足时 |
|---|---|---|
| 规范完成门 | 本文结构/对象/协议/映射/DoD 自洽，随后实现规范审核 | 草稿可交付，不标实现通过 |
| 实现接入门 | v8 实现 commit、DB/schema/adapter 版本与闭环证据、命名扫描、F-08 清单 | 阻止正式 P0 接入；固定输入计算试验不替代 |
| 功能发布门 | 阶段全部子例、性能预算/隔离验证、capability 分层报告 | 不发布未验证支持面，不推迟基础安全至 P3 |

v8 接入证据精确锚定 `docs/designs/v8-dev.md` §6「P0B Native 最小闭环 / P0C compat 同合同闭环」（L819–825）与 §5.2 矩阵。
至少证实 seal/首 attempt/completion、权限/receipt、unknown/repair/reconcile、generation/canonicalizer；不能以 v6/v9 测试替代。

### 7.2 P0–P3

| 阶段 | 规范承诺/实现依赖 | 首验集合与回归 |
|---|---|---|
| P0 | 最小源（静态 Identity/Constraints、cutoff History、ToolSchemas、预发布 artifact）；完整 kind 预算、manifest、双模式、seal/Feedback/发布基础、固定输入初始化、当前授权、compat prompt 门 | 1、2、5基础（含5-I0/5-M组）、7-P0、7-K组、8、9-P0、A/B/D基础；canonical/assembly vectors |
| P1 | P0 后接真实 persona/params发布、初始化指针竞争/覆盖/版本变化、emergent 消费、spill、ForkPrefix；引用/保留合同有效 | 3、4、5扩展（含5-I1）、9-P1、C；回归 P0，特别5-I0/9-P0 |
| P2 | P0/P1 后接四标签预构建、完整 render identity、发布/缓存、隔离/readiness | 6、7-P2、D渲染扩展；回归 7-P0；render vectors |
| P3 | 所有前期工件齐备，汇总 F/R11、F-08、三个比较面、命名与延期证据 | 全集回归，完整 capability 报告；不是首次补安全 |

R5-P2-1 **由本规范分组处置关闭**，不是 fixture 已通过：9-P0 不含 P1 真实消费，不能报告“fixture 9 全绿”。

### 7.3 fixture 清单

所有子例共享以下九维合同；下表的覆盖值替换默认值，因此不是省略输入/写集/恢复的测试标题。
固定底座 F：W=a、S=s、T=t，driver active/无cancel/有效claim与generation g；cutoff固定逻辑历史，无context增量；DB预构建=离线renderer harness+发布DB，非真实effect loop。
F 的冻结 profile 使用 tokenizer=fake_tokens@1、L_eff=10000、a/b=1/2、scale=0、max_moves=8、max_clear_tokens=2000、每 kind cap=2/max_bytes=64。
fake_tokens@1 为测试纯值适配：源/变换表示与完整 wire 的 token 数都在 vector 明示；不用于声称生产 tokenizer 已验证。
F 最小源的总 wire_tokens=100，空 output 桶 reserve=500；每个 golden 必须保存完整输入 canonical bytes 与预期输出 bytes，不仅 hash。
命令 C1/C2 表示不同 ID；C1×2 表示全部 payload 原样重发同 ID；发布使用 P1/P2，不能与 session command 域混用。
写集计数模板 X：新 step/batch/LLM effect/首 attempt/plan/trace/effect_feedback_binding 各+1、父 binding/receipt 各+1；catalog/各profile/policy 修改0，sample/候选0，latch/spill/消费由子例另列，无v10新事件。
模板 R：新父 binding/拒绝 receipt 各+1，其他业务/semantic/context 增量=0；同 ID 重发所有增量=0；授权前置为 A0（仅独立审计+1）。
模板 F1：样本+1、每有测量桶 version/count+1、ANALYZE 补一次；本章 completion 均非流式 final 文本，既有 assistant/message+1。
F1 非关闭后 step ready/decision、session ready、无 turn/end；关闭后 step succeeded/closed、session ready、turn/end+1；finish 后才 completed。
模板O：object binding/receipt各+1；成功写集按该包/action、重用则0，拒绝业务0；artifact/persona发布的session/events/sample/候选均0；初始化成功显式覆盖为session+1且内容扩展同一行。
除明示外子例为数据库层、capability 无要求；I/O 后缀子例为真实 I/O 层、要求 sync_before_io，缺则 blocked。
纯计算/inspection 无 receipt（记“无”）；accepted 的原 v8 code 未定义时不捏造新 code，下面以 accepted/原结果表达。
写命令各注入提交前 crash（增量0）、提交后丢响应（原ID重放增量0），恢复见§6.6；只读/纯值无持久crash态，再调用重新观察，不承诺历史响应重放。
并发行必须跑两提交序；非并发子例的顺序维度为不适用；所有子例当前报告状态均为**未运行**，下列数字为预期而非结果。

| 子例 / 阶段 / 边界 | 固定输入与命令序列 | receipt、状态/行数、canonical 输出及恢复断言 |
|---|---|---|
| 1a / P0 / DB | F；同逻辑键同 scope/priority 两 section a,b；改物理 ID/插入序/locale，C1 seal、C1×2、C2 同 seal | 首次 X；重放0，C2 仅新父 receipt/binding；按逻辑 a,b 排序，请求/Decision 相同，无重装 |
| 1b / P0 / DB | F 同 frozen stats；改变本次 cache/latency/worker/attempt；另组改冻结 stats/tokenizer | 前组请求/Decision 同字节；后组视不同输入；不要求 observational 行相同 |
| 1c / P0 / I/O | F；native/compat 各 C1 seal→dispatch→fake provider；host 尝试另拼 prompt | 正向最终 wire=冻结请求；负向来源门 failed 且不得 I/O；dispatch 仍独立持久，不能仅比较 DB 行 |
| 1d / P0 / DB+I/O分列 | tools opaque JSON=`{"$defs":{"X":{"type":"string"}},"$ref":"#/$defs/X"}`；descriptor普通`$int:"label"`/`$$int`与协议tag=9007199254740992对照 | wire保留$ref/$defs语义，不出现错误$$ref；descriptor普通键分别为$$int/$$$int，tag仍$int；request_hash按descriptor且wire完整被覆盖，host二次转义/序列化负向禁止I/O |
| 1e / P0 / DB | text UTF-8 `é`=c3a9→base64 w6k=、非NFC e+0301、binary 00ff→AP8=；整数±(2^53−1)、±2^53、±(2^63−1)、溢出与裸超界 | opaque文本保留两种不同字节；descriptor非NFC拒绝；binary不得作JSON值/文本，policy允许base64时精确输出AP8=；合同超界必须tag，wire仅允许位置输出精确十进制；非法padding/size/hash/整数拒绝，零X |
| 2a / P0 / DB | F 有候选/latch 提案；inspect 两次、explain 空历史 | 无 receipt；所有业务/审计表与 lease/fence/occurrence 差量0；inspection_id 独立，请求为假设值 |
| 2b / P0 / DB | F 缺 required artifact；inspect；注入 foreign/dblink/live/handler source | 前者 incomplete/needs_preparation、无 descriptor；后者拒 INVALID_ASSEMBLY_INPUT；零落表/零外调 |
| 2c / P0 / DB | F 无来源授权；inspect/explain 历史 | GRANT_DENIED 返回、零审计；不能通过 trace 泄漏内容；恢复授权后全新只读调用 |
| 3a / P1 / DB | §4.3 向量 E；C1 completion→tools seal→1 个 tool success→新 C2 decision | F1+关系1/候选2；tools seal 候选仍2（tool/call+1）；工具完成 tool/result+1 后 step succeeded、turn 开；C2 为 X，n=2、候选0、关系绑定1 |
| 3b / P1 / DB | E先普通成功completion→final_tools=true tools seal→全部tool受权dispatch/成功收束，step succeeded且turn开→新claim；inspect、C2装配回滚、C3 seal→该LLM dispatch→有证据known retryable failure（预算未耗尽、session ready/step failed_retryable）→新claim/retry_effect | inspect/回滚消费0、n不占；C3消费一次；retry仅既有attempt分配，plan/候选不变、payload含alpha/beta；不得对未dispatch ready或unknown直接retry |
| 3c / P1 / DB | E；工具期间插 session/heartbeat，另组无 heartbeat；C2 输入预算只选 alpha | 两组相同 target n=2；heartbeat 单独观测+1；成功消费删除2，plan 记 alpha selected/beta budget_skipped；n=3 不可再消费 beta |
| 3d-close / P1 / DB | E的关闭decision对照completion→同turn新decision→finish | sample1/关系0/候选0、step succeeded/session ready；新decision为R/TURN_ALREADY_CLOSED，n不进；finish才completed，不构造消费先于该生产decision关闭 |
| 3d-cancel / P1 / DB | E非关闭且tools全成功；cancel×后继消费两序 | cancel先R/既有取消门拒绝、不绑定/不推进n、候选逻辑失效；消费先X删除2/绑定1后cancel按v8收束，不回插 |
| 4a / P1 / DB | F AggressivePrune、optional完整原文1000token装不下，profile placeholder UTF-8=`[omitted]`（5b6f6d69747465645d，fixture实测3token）可容纳；C1 seal后移除测试缓存、从冻结源重建→C1重放 | X+spill1，保存完整原文及SpillReference；新wire该section精确[omitted]而非spill:物理ID，计替代3token+wire开销；重放仍同wire，原文同bytes/hash，不能因缓存缺失换表示 |
| 4b / P1 / DB | 不可重建源仅projection的发布负向；新决策optional缺失，placeholder可容纳/不可容纳两组；随后C1重放 | 前者ARTIFACT_INCOMPLETE；可容纳wire精确[omitted]、spill0；不可容纳skip无该section字节、内容token0；重放保持；权限不足GRANT_DENIED不降级，旧源不可恢复则FROZEN_INPUT_UNAVAILABLE |
| 5-P0 / P0 / DB | F固定persona/params；C1 seal→LLM受权dispatch/非关闭成功→final_tools=true tools seal→全部工具dispatch/成功收束（step succeeded、turn开）；发布新defaults/g2并activate、新claim后C2新decision | 两次X；旧session内容绑定同，旧step=g、新step=g2；不在仍有活跃step时建C2，不把defaults版本发布当原地修改 |
| 5-P1 / P1 / DB | publish_persona_version P1/P1×2/P2 CAS 冲突；初始化 session，后更新指针 | O 与原 identity；CAS失配 rejected/PERSONA_POINTER_MISMATCH；旧 session params 不变，新 session 取新版本；真实顶层合并/null vectors |
| 5-L1 / P0 / DB | declaration@1 selected_present、literal=true；有/无入wire的owner两组，C1首次seal | selected组X+latch1且fired_turn_id=T/fired_occurrence=1；skip/placeholder组latch0；wire/Decision记录确定firing |
| 5-L2 / P0 / DB | 同L1但首次应用后回滚，再inspect与新ID成功seal | 回滚/inspect均latch0/n不占；新seal仍首次触发1，不沿用失败trial |
| 5-L3 / P0 / DB | 同key重复同值提案，另组同声明异值；发布同key异声明 | 同值去重latch1；异值R/LATCH_PROPOSAL_CONFLICT；异声明O/LATCH_DECLARATION_CONFLICT，零latch |
| 5-L4 / P0 / DB | 按5-P0合法收束后换g2：同key同声明/同key异声明/新key三组 | 同声明沿用历史值不重触；异声明R/LATCH_DECLARATION_MISMATCH；新key可首触；不得随generation重置旧latch |
| 5-L5 / P0 / DB | 首次firing后按5-P0收束，同T后继n（cutoff已变）；另组关闭T后经合法user/turn开始T2 | 同T new_firings为空但turn_has_firing=true、None marker被抑制；T2无新firing则恢复资格；同ID重放零写 |
| 5-M / P0 / DB | generation stage→事务外ready证明→activate；缺ready、CAS竞争、fail_build；初始化基础见5-I0、P1仅扩展5-I1 | 各成功action仅其完整写集+O；缺ready不切指针，CAS后者固定拒绝；building失败持久failed；每action提交前crash全0/提交丢响应原ID零写 |
| 5-Ma / P0 / DB | g0 active，g1已ready building；不同ID的activate(g1)×revoke_active(g0,replacement_generation=NULL)，同expected指针，两提交序；下线预锁后插入新关联session | activate先则下线GENERATION_STATE_MISMATCH；下线先则activate GENERATION_POINTER_MISMATCH；仅赢家revision+1/完整O；均pointer→generation无锁环；新关联迫使下线整笔回滚全序重取，零部分drain/receipt，终态历史session亦预锁 |
| 5-Mb / P0 / DB | g1/g2均ready building，异ID activate共用expected指针；另同ID同payload并发重放 | 两序均唯一赢家切换/revision+1；异ID后者GENERATION_POINTER_MISMATCH，未激活候选仍building；同ID只返原成功、无第二revision；锁内发现预读旧目标变化整体重取 |
| 5-Mc / P0 / DB | W无pointer行，两个不同generation首次stage并发；stage各写点crash，提交后丢响应；只读装配在无行/NULL时调用 | 成功stage共建唯一NULL/revision=0行，重放不重建；回滚不留空行，另已提交stage的行不受影响；无行/NULL均NO_ACTIVE_GENERATION零控制写；首次activate从NULL/0单次切换 |
| 5-Md / P0 / DB | revoke_active下一个generation关联两session：A含ready未dispatch effect、B含pending/unknown或持compact lock；提交前kill、提交后丢响应、同O ID重放；另不同W同publication_id、不同session同名派生command_id对照 | 逐session审计归属：各session内部子操作行parent_session_id=自身、parent_command_id=派生值、ordinal自0独立编号，(parent_session_id,parent_command_id,ordinal)三元组与event_key五元组重放查询返回同值；A未dispatch按drain收束、B按三分支/等待落定；提交前kill全0（含O/派生父receipt/审计），提交后重放原O结果零drain零审计增量；跨W/跨session同名ID零串读 |
| 5-Me / P0 / DB | 起点pointer=(g0,r)、g0 active、g1 ready building；异O ID依次A1=activate(g1,expected g0/r)、D1=revoke_active(g1,NULL,expected g1/r+1)、S2=stage全新g2复用g0实现但新成员/v10引用/包、事务外新readiness、A2=activate(g2,expected NULL/r+2) | A1后g0 retired、pointer=(g1,r+1)；D1后g1 failed、(NULL,r+2)；S2仅建g2 building、revision仍r+2；A2后g2 active、(g2,r+3)，g0仍retired；独立分支在A2提交前用新ID传NULL/r旧CAS拒GENERATION_POINTER_MISMATCH，仅拒绝O；NULL窗口新装配NO_ACTIVE_GENERATION零控制写 |
| 5-Mf / P0 / DB | 续5-Me，g2产生A的ready未dispatch effect/attempt及B已dispatch pending；A满足三合取且无既有终态/cause/cancel，B无其他终态条件；D2=revoke_active(g2,NULL,expected g2/r+3)；独立分支在D2提交前用新ID传g2/r+2；g0既有工作作对照 | D2使g2 failed、pointer=(NULL,r+4)；A effect/attempt同转cancelled_before_dispatch/ABORTED_BEFORE_DISPATCH，审计GENERATION_REVOKED，step/session按三合取失败；B保持pending/waiting_effect，可completion/repair，后续沿原聚合/三分支；旧CAS只拒GENERATION_POINTER_MISMATCH；g0既有dispatch/seal/retry不因本次下线受限 |
| 5-Mg / P0 / DB | 5-Me/5-Mf每action各写点提交前kill、提交后丢响应；D1/D2各有两受影响session，沿5-Md再跑unknown/compact分支；最终NULL/r+4后分别重放A1/D1/S2/A2/D2原ID/原payload | 提交前仅本action增量全0、保留前缀状态/revision；原ID重试一次成功。D1/D2的O逐session枚举父receipt/drain结果，parent_session_id、派生command_id、ordinal及event_key按5-Md独立核验；O/全部父receipt/内部审计/drain/指针全有或全无；重放各返各自原结果，不返最后一次结果，零revision/drain/receipt/审计增量 |
| 5-Mh / P0 / DB | 均新O ID且其余前置合法：D1的replacement非NULL(g0 retired或任意代)/缺字段；stage(g0,原完整包)；activate(g0,expected_state=building)；g2包成员/包内generation引用仍属g0；g2合法包仅提供g0或异package证明 | 依序GENERATION_PACKAGE_INVALID、GENERATION_STATE_MISMATCH、GENERATION_STATE_MISMATCH、GENERATION_PACKAGE_INVALID、IMPLEMENTATION_NOT_READY；仅拒绝O，无候选/指针/成员/drain半写；不得直接回指retired、stage复活或挪用旧证明；同identity异包仍GENERATION_IDENTITY_CONFLICT |
| 5-Mi / P0 / DB | 预置新guard前已accepted的旧O receipt（含旧非NULL replacement payload），当前管理授权有效；按原ID/hash重放，另异payload同ID及同payload新ID对照；再重放5-Me的S2（此时g2已failed） | 旧ID返回各自历史accepted结果、不用今日guard覆盖；异payload同ID IDEMPOTENCY_CONFLICT，新ID非NULL replacement按5-Mh拒绝；原S2仍返原stage结果，不重建/复活g2；全部重放不改当前NULL/r+4、generation状态、原receipt或内部审计，不把历史结果当新服务许可 |
| 5-I0 / P0 / DB | 固定已发布persona/defaults及合法params；initialize_context_session C1一次创建→丢响应C1×2→异C2争同S（亦跑两提交序）；各写点crash | ready session总1，内容绑定/物化值与O全有或全无，无turn/step/effect；同ID原S/版本且零增量；异IDSESSION_IDENTITY_CONFLICT仅拒绝O；首事务回滚则另一命令可创建，binding/receipt不留半态 |
| 5-I1 / P1 / DB | 真实publish_persona_version与初始化两序；顶层右覆盖/null、非法params、persona/defaults版本变化；回归5-I0 | 更新先旧expected拒PERSONA_POINTER_MISMATCH，初始化先冻结旧版；新S显式取新版本、旧S不漂移；非法INVALID_PARAMS零session；绑定与O仍原子，非在P1才首次验基础写安全 |
| 6a / P2 / DB预构建 | 固定四标签/全部依赖，两 harness 分别渲染 | 无 session receipt；IR/section canonical bytes 相同；Python 不注册标签，缓存共享不充当对照 |
| 6b / P2 / DB预构建 | 新旧 alias 同名交错，两提交/执行序，另组共享 implementation | 各得各自实现内容；污染则 failed/readiness 不可发布；换 component/依赖必须新 render identity |
| 7-P0a / P0 / DB | 单 artifact 包 P1→P1×2→P1异内容→P2同内容 | accepted/PUBLISHED 对象1；重放0；冲突 rejected/IDEMPOTENCY_CONFLICT 仅receipt+1；P2 O 内容0、原identity |
| 7-P0b / P0 / DB | 无权/跨 W；畸形 transport/非canonical/坏 hash；修正后同ID和新ID | 无权A0不占O；余者按§6.4首占拒绝O；同ID原拒绝，新ID重校验；无对象/事件/sample |
| 7-P0c / P0 / DB | P1 完整发布各写点 crash；并发 P2 同 artifact 同/异 bytes | 提交前全0、提交后对象与O同时可见；两序同字节收敛1，异字节后者ARTIFACT_IDENTITY_CONFLICT |
| 7-P2a / P2 / DB | source+IR+1 section完整包，P1/P2同render；独立三组：复用artifact ID异bytes/新artifact IDs异产物/同artifact及产物仅合法aggregate证明异；各跑两提交序 | 同包artifact3/doc1/render1+O、同内容后者只O；三组后者依次ARTIFACT_IDENTITY_CONFLICT / RENDER_IDENTITY_CONFLICT / RENDER_IDENTITY_CONFLICT；先者原包不改，两码同时满足取ARTIFACT |
| 7-K / P0 / DB | 高熵长presentation/publication/source/桶键及复合identity，含域封装总长1MiB/1MiB+1；受控内容digest与binding_locator碰撞分组注入 | 界内全文非索引留存，普通索引48bytes、O receipt例外81bytes/描述<512bytes；边界publication可保存receipt；ID自身超限/locator碰撞走ingress不占他人binding，内容超限/碰撞走本binding普通receipt；稳定IDENTITY_TOO_LARGE/IDENTITY_DIGEST_COLLISION且原行不变，无截断/btree异常 |
| 7-Kr / P0 / DB | publication完整identity恰1MiB，三组独立初态首请求分别accepted/业务拒绝/transport畸形拒绝；各组原ID原报文重放→同ID异typed key冲突；各切点丢响应 | accepted、业务拒绝、畸形拒绝、IDEMPOTENCY_CONFLICT四结果均可持久receipt；同ID原key返原结果、异key仅冲突receipt+1；三类typed key均固定32bytes，合法ID不因派生键超限转ingress；提交丢响应重放零写，locator碰撞的ingress与内容碰撞的普通receipt亦稳定重放 |
| 7-P2b / P2 / DB | 换 profile/闭包；缺 IR/section、错误 provenance、未ready/alias不合法；跨代复用后撤权 | 新身份不误中；对应ARTIFACT_INCOMPLETE/PROVENANCE_INVALID/IMPLEMENTATION_NOT_READY；完整同身份可复用但消费撤权拒绝 |
| 8a / P0 / DB | 十二 kinds×四 tiers×required/optional 合法组合；unknown kind | 每种有预算分支；未知/缺规则INVALID_ASSEMBLY_INPUT；无请求/写集R；Never 只允许 required |
| 8b / P0 / DB | 精确压力 .60/.75/.90；L=0/负/非整数；空源；Never超B；max_moves=0/clear=0 | 等号高档；非法L拒；空源NEEDS_PREPARATION；Never超限ASSEMBLY_BUDGET_EXCEEDED；熔断/配对不破坏 |
| 8c / P0 / DB | 同一非空section在scope边界、M_max=1、prefix_only=false、policy允许None、无firing，仅切provider_markerable true→false；另message内混true/false | true有一个marker、false无且reason=provider_not_markerable、额度不占；消息混合不得间接放marker；对照同T firing为latch_turn_suppressed；完整wire/token差异固定 |
| 9-P0a / P0 / DB | E 生产段、同C1重放、C2重复completion、关闭decision对照 | F1一次、桶version+1；非关闭关系1候选2，关闭关系0候选0；duplicate/over_cap理由可查；关闭仍ready |
| 9-P0b / P0 / DB | observation、拒绝、旧attempt、failure/unknown、repair/reconcile成功、terminal drain、非LLM各单独初态 | 各沿v8原receipt/控制结果，context sample/桶/候选/ANALYZE增量全0；非终局观测只有receipt+stream_progress+规定audit |
| 9-P0-stream / P0 / DB | 合法成功final/结束计数先到，尾部chunk未齐→completion→迟到chunk（等值/冲突两组） | completion恰sample1/各合法测量桶+1，ANALYZE补一次；迟到chunk context增量0，等值/冲突仅按v8审计，不撤样 |
| 9-P0c / P0 / DB | 缺usage/非法usage；空/非法候选；cap=1/2边界；digest长度512、EMA两值 | 缺usage不采；候选非法仍F1且advisory；插第513删257，p75/p95 nearest-rank；EMA(100,200)=150 |
| 9-P0d / P0 / DB | 两session同桶、C1 completion中途故障、相同E不同profile伪造 | 两序均样本2/version+2，无丢更新；故障增量0；profile不等冻结绑定FEEDBACK_BINDING_CONFLICT，不计样 |
| 9-P0e1 / P0 / DB | 可信sidecar完整，仅调用profile伪造C1；更正新C2；另两组真实持久sidecar损坏+合法成功completion：closing（decision_only=true）/非关闭（含冻结tools plan）。两损坏组前置：session/step未终态，无已有end/未决unknown/sticky或provider cancel，除触发effect外无pending、除本次作废plan外无待续行工作 | C1拒FEEDBACK_BINDING_CONFLICT、C2正常F1；两损坏组均effect=succeeded（结算/结果事件保留）、step=failed_terminal/INFRA_PROTOCOL_VIOLATION、session=failed/INFRA_PROTOCOL_VIOLATION，context增量0；无step succeeded/session ready、finish/completed/Feedback；真实result/已有plan字节保留但plan作废，tools seal按terminal门拒绝且无后继step；结算后原reducer资格满足，优先级(4)追加failed interrupted end恰1、正常成功end0，原turn_end_key槽位恰1；父receipt=accepted原结算+context_failure；同ID重放原receipt，end增量0/槽位不变；新ID仅terminal/drain门，不能重新采样 |
| 9-P0e2 / P0 / DB | 持久损坏且session lease空/过期，recovery_claim→reconcile扫描两次；job lease有效/过期对照 | 受控INFRA出口同cause，未dispatch取消、pending/unknown按v8 drain；有效job lease不抢占；两次context增量0，不UPDATE不可变行 |
| 9-P0e3 / P0 / DB | 已terminal WORKSPACE_LOST/既有INFRA及已终态step，再发现sidecar/sample冲突 | 原session failure_code/step outcome/终态不变；仅原合法drain或审计，零补采，不能假造新失败改cause |
| 9-P0e4 / P0 / DB | e1持久损坏closing/非关闭两组，沿用e1全部前置与plan作废后的reducer资格：提交前kill、提交后丢响应、同completion ID重试/重放 | 提交前kill使effect结算/step聚合/INFRA收束/父receipt及end事件/槽位增量全0；同ID重试首次提交或提交后丢响应，两组均effect=succeeded、step=failed_terminal/INFRA_PROTOCOL_VIOLATION（从未暂写SUCCEEDED/ready）、session=failed/INFRA_PROTOCOL_VIOLATION、父accepted receipt含原结算/context_failure；无finish/completed/Feedback，plan作废保留字节；原reducer优先级(4)仅追加failed interrupted end1、正常成功end0，原turn_end_key槽位1；提交后同ID重放原receipt，零增量零改写、不重复end/槽位；不可变sample/profile/sidecar全文不变 |
| 9-P1 / P1 / DB | 完整重跑3a–3d且回归9-P0全部 | 真实后继消费、单次窗口、rollback/retry/终止失效同3；不得只验生产就标9全绿 |
| A1 / P0 / DB | 行锁方案：撤销在授权锁/capture之前提交→装配；或装配先锁/capture，撤销阻塞→seal提交→撤销提交→下一dispatch；另跨slice同W | 第一序R/GRANT_DENIED且X全0（若入口权限也撤销则A0）；第二序X有效但后dispatch GRANT_DENIED、零I/O；不得调度capture后撤销抢先seal |
| A1-CAS / P0 / DB条件项 | 仅实现选v8 CAS替代时：capture读version→撤销推进version→seal CAS；反序CAS先成功提交 | 前者CAS冲突回滚/重判GRANT_DENIED、零X；后者X后撤销、下一dispatch拒；行锁实现标不适用而非执行该不可达时序 |
| A3 / P0 / DB（P1/P2扩展） | 逐§2.4矩阵遗漏一个capability/resource membership/约束；artifact完整但源依赖撤权；emergent producer可读但consumer不可读；伪builder证明 | 各deny/零X或零I/O，inspection连审计0；仅外层slice或相同W不放行；管理许可撤销同锁两序；POML query越relation/max_rows拒；证明不可信PROVENANCE_INVALID |
| A3-query / P0 / DB（P2真实query扩展） | 同generation/query_id换实现或登记字段；未知query/版本或实现digest漂移/参数越界/实际依赖超声明/输出越限；裸DB物化证明替代builder签名 | stage换字段GENERATION_IDENTITY_CONFLICT且原登记不变；recall_context_query分别QUERY_NOT_REGISTERED/QUERY_VERSION_MISMATCH/QUERY_PARAMETER_OUT_OF_BOUNDS/QUERY_DEPENDENCY_MISMATCH/QUERY_OUTPUT_INVALID，零receipt/audit/外调；未授权先GRANT_DENIED；伪替代证明发布PROVENANCE_INVALID且零对象 |
| A2 / P0 / DB | F 初始seal各写点kill；R11混合eligible+budget terminal/全budget耗尽 | 无planned无effect；混合FAILED_TERMINAL，全budget FAILED_RETRY_BUDGET_EXHAUSTED；不新增context写/恢复step |
| B1 / P0 / DB | claimed缺required，C1拒→补齐发布→C1重放→显式yield/新claim/C2 | R/NEEDS_PREPARATION前后相同；拒时lease/fence不变；yield依checkpoint/lost；C2才X；无等待态 |
| B2 / P0 / DB | 预构建期间source v1→v2、迟到v1包、无变化另一source | 需要v2仍NEEDS_PREPARATION；坏hash/provenance非缺失；另一源字节不变；无自动刷新 |
| B3 / P0 / DB | seal前p95触发升级；派发后PTL已知失败/无证据unknown两个初态 | 前者单X记录最终tier；后者按v8失败或unknown，无新plan/改payload；retry若合法字节不变 |
| C1 / P1 / DB | 稳定fork切点；不delegable、收窄权限、不同persona/provider/render各例 | 不继承live/latch；无权GRANT_DENIED，其他不兼容普通X且prefix_share=false；父后续事件不改子请求 |
| C2 / P1 / DB | 内容identity相同但wire marker/tool可见面不同；父先改/子先seal两序 | 内容可复用≠wire共享；canonical prefix 不同则不共享；子冻结后零重装 |
| D-P0 / P0 / DB+I/O分列 | prompt门与dispatch门各单独破坏；switch supported/unsupported | 每门独立负向；I/O缺sync则blocked；unsupported强制UNSUPPORTED且mode/fence不变；不得Native绿替compat |
| D-P2 / P2 / DB预构建 | 6b隔离向量加compat私有render直送企图 | 通过发布/来源链才可用；旁路failed、零未授权I/O；回归D-P0，不因共读artifact标隔离通过 |

所有事件计数均是本次命令增量，继承 v8 自身必要 audit 另按其精确向量断言；v10 不额外分配 semantic/observational seq。

### 7.4 并发/crash vectors

| vector | 两提交序与精确收敛（输入沿对应 fixture） | crash/replay 入口 |
|---|---|---|
| V1 撤销×seal/dispatch | 行锁：撤销先授权锁→零创建；seal持锁先提交→撤销提交→下一dispatch拒；独立dispatch先提交则撤销不追溯已派发；CAS单列A1-CAS | A1/D；拒绝与成功各按原ID重放，不造capture后撤销抢先seal序 |
| V2 两session同桶 | C1→C2、C2→C1 均sample2/version+2；EMA按各序可异；锁轨迹无反向边 | 9-P0d；中途回滚0，提交丢响应不补样 |
| V3 重复completion/cancel | completion先sample1；cancel先sample0；不同ID重复同E仍≤1 | 9-P0a/3d；父结算与context全有或全无 |
| V4 消费×cancel | tools已全成功的非关闭E；消费先删除2/绑定1，cancel先消费0/逻辑失效；关闭仅3d-close顺序对照 | 3/9-P1；回滚n不占，提交后payload不丢 |
| V5 发布×发布 | 同identity同包两序对象总数1；异包两序先者保留，复用artifact ID异内容取ARTIFACT，新artifact同render异产物/仅aggregate证明异取RENDER | 7-P0c/7-P2a；IR/section与O原子 |
| V6 缺输入×发布 | 拒绝先同ID永拒；发布先全量capture可成功；缺项列表只含受权项 | B1；新ID使用当前claim，无隐式yield |
| V7 generation×seal | 下线先GENERATION_REVOKED/零X；seal先X后按v8 drain，不反向补session锁 | A2/5/D；R11无前置step |

每个 crash 点用独立连接观察提交可见性，不能只检查调用返回；同ID响应丢失与新ID业务重试分别报告。

### 7.5 spike/延期

| 验证待办 / 阻塞时点 | 测量输入与产物 | 失败处置/影响条款 |
|---|---|---|
| stats / SQL维护实现冻结前 | 多session同/异桶、512/513 digest、重复样本、cap；吞吐/p95锁等待/一致性报告 | 阻止相关P0实现冻结；§4.5/§6.5原子SQL合同不变，worker优化另审 |
| fold / projection方案冻结前 | 冷全历史/增量、长会话cutoff、失效/重建成本；基准+取舍记录 | 阻止相关projection发布；§3.2/3.7仍要求同字节，不捏造摘要 |
| payload / ledger存储接入前 | 大请求TOAST、claim/heartbeat、读取/replay；写放大/WAL/延迟预算报告 | 阻止存储接入；不先验宣称拆heartbeat解决问题，request_hash不变 |
| POML隔离 / P2选型与跨身份发布前 | 新旧同名alias交错、共享实现、native/compat；隔离选择记录+负向证据 | 不发布未证实支持面；§5.4义务不以进程前缀替代 |
| 实现后 vectors/crash/capability / 各阶段发布前 | §7.3–7.4完整golden字节、故障轨迹、两运行时分层报告 | 不记绿，不用DB结果替I/O；修复后重跑相应集合 |

三 spike 未完成不阻止本草稿形成，禁止把性能预算写成实测保证；v8 runtime/命名接入证据另见 §7.1。
churn counter 延期：首版无持久字段/Feedback义务；八条论文 trace alert 整体延期，不猜规则、不当执行门。
alert后续规则要求见§8；没有churn不是fixture缺失。

### 7.6 准出报告

passed 仅实际执行且断言满足；failed 记差异；blocked 仅按继承capability矩阵；未执行记未运行，不发明通过结论。
F-03授权、F-04 canonical/normalize/assembly及render子集、F-07 checkpoint、F-08入口、F-09 code层、F-10 route、R11逐项回归汇总。
文档自查见附录 A.4；它不是上述运行报告，本次所有实现、spike、隔离与运行验收均未执行。

## 8. 明确不做〔D1〕

- 不 fork poml、不改 writer.ts、不引入自定义 IR；POML 不决定 provider wire、scope 或 marker。
- 不伪装 PG 系统视图；不复制 PipelineSession、run DAG 或第二套执行账本。
- 不修改 18 条不变量、冻结 v8、raw、digest、v9 spec、历史审核或 v1–v9 代码。
- 不在 Bind 执行网络、foreign table/dblink、live workspace、TS renderer 或宿主 handler。
- 不恢复自动 recall/poml_render preparation、无 step 工作、seal 后补 slot、后台等待态。
- 不恢复跨调用 PTL streak/自动重装，不把 unknown 当已知失败，不在失败终态自动新建 step。
- 不跨 turn/session 转投 emergent，不给 inspection 增 receipt、审计落表或隐式准备。
- 不因普通 cache miss 改冻结请求为 placeholder；授权失败无 optional 豁免。
- 不强制一代一个进程，不以 generation 前缀替代隔离证明，compat 无私有 prompt/render 旁路。
- 不引入 pgAgentOS RAG、http-skill、无授权逻辑的 role 列、glass-box thought 叙事或 poll_job 第二队列。
- 首版不承诺 churn 指标或论文八条 alert；后续 alert 只能是有版本/阈值/测试的只读诊断，不成为执行门。
- 不默认消费 v9 pack，不搬 ctx 控制表/PGMQ/apply 协议；单向 adapter 必须另立集成 gate。
- 不做在线权威 artifact 驱逐，不恢复外部预构建进度；销毁仅显式受控流程。
- 本轮不写生产代码、补丁、可执行 DDL/迁移，不宣称未执行的测试、spike 或 runtime gate 已通过。
- 扩大上述范围必须单独审核对 step/seal/取消/unknown/switch/generation drain 的影响。

## 9. 对外表述〔D1〕

- catalog、optimizer、statistics、EXPLAIN 回到数据库，成为受控的表与函数，不是 PG 系统元数据。
- POML 是 section 的声明语言；pipeline Serialize 是 provider wire 的唯一权威。
- 一份行为合同、两份运行时：prompt 来自受控产物，外部执行仍由既有 effect ledger 管理。
- v10 是 v8 assemble 的内部展开，不是新 runtime；18 条不变量原样继承，19/20 待本规范审核冻结。
- 保证限于本地逻辑结果最多提交一次、确定性冻结重放与当前授权；不承诺 provider exactly-once、缓存命中或未验证性能。
- **v10-dev 实现规范草稿完成，基于轮 5 准出的 raw，待实现规范审核；未执行实现与运行验收。**

## 附录 A 术语与来源映射

### A.1 raw 全章节迁移索引

下表已逐行落实；逐节以实际 raw 标题定位，行范围辅助，不以研究 digest 替代 raw。

| raw 子节（468 行版） | v10-dev 落点 | 处置 |
|---|---|---|
| §0 L13–18 | §0 | 已规范化 |
| §1.1 L22–30 | §0、§9 | 设计背景 |
| §1.2 L32–47 | §2.1、§2.4 | 已规范化；IdentityKey索引与完整授权矩阵/管理许可 |
| §1.3 L49–56 | §2.1 | 已规范化 |
| §1.4 L58–70 | §2、§3、§8 | 已规范化；跨调用 recovery 不做 |
| §2.1 L74–85 | §3.1、§6.2 | 已规范化 |
| §2.2 L86–111 | §0、§3、§4.1、§6 | 已规范化；自动 preparation 延期 |
| §2.3 L113–130 | §2.2、§3.3、§7.3 | 已规范化 |
| §2.4 L132–142 | §2.1、§3.2、§3.7、§4 | 已规范化；latch声明/turn窗口、spill_archive限定、Feedback损坏受控出口 |
| §2.5 L144–159 | §3.3–3.4、§7.3 | 已规范化；跨调用 PTL 延期 |
| §2.6 L161–167 | §3.6、§4.6 | 已规范化 |
| §2.7 L169–173 | §3.7、§7.3 C | 已规范化 |
| §2.8 L175–178 | §1.4 | 已规范化 |
| §2.9 L179–185 | §0.3 | 新增 19/20，待本规范审核 |
| §3.1 L188–191 | §3.1、§6.2 | 已规范化 |
| §3.2 L192–200 | §3.6、§6、§7 | 已规范化 |
| §3.3 L202–206 | §7.3 A | 继承/回归，不是旧缺口 |
| §4.1 L210–216 | §5.1 | 已规范化 |
| §4.2 L217–233 | §5.1 | 已规范化 |
| §4.3 L235–241 | §1.2、§5.2–5.3、§6.4 | 已规范化；三层字节合同、可信provenance与ARTIFACT优先 |
| §4.4 L243–265 | §5.4、§7.5 | 已规范化；隔离验证门保留 |
| §4.5 L266–274 | §5.4、§8 | 已规范化；不改 Writer |
| §4.6 L275–280 | §1.3、§7.3 | 已规范化 |
| §5.1 L283–302 | §2.1、§6.1 | 已规范化；显式generation/初始化O命令，不虚构v8父命令 |
| §5.2 L304–313 | §2.3、§6.1 | 已规范化；persona指针与初始化线性化/receipt |
| §5.3 L314–316 | §2.3 | 已规范化 |
| §5.4 L318–339 | §2.3、§8、§9 | 设计背景；取舍显式保留 |
| §5.5 L340–343 | §2.4、§6、§7 | 已规范化 |
| §5.6 L344–348 | §2.5、§7.1 | 已规范化；扫描证据待验 |
| §6 L350–360 | §1、§7 | 已规范化；descriptor/opaque/wire分层与边界vectors |
| §7.1 L364–370 | §0 | 已规范化 |
| §7.2 L372–384 | §6.1、§7、A.3 | 继承/回归 |
| §7.3 L386–389 | §3.2 | 已规范化 |
| §7.4 L390–403 | §0.4、§2.5、§7 | 已规范化；v9 adapter 不默认接入 |
| §8 L405–419 | §7.3–7.4 | 已规范化；9与7分期，A1行锁/CAS分列、3b/5-P0合法前置 |
| §9.1 L423–431 | §0.1、§7.1 | 已规范化；状态以轮 5 为准 |
| §9.2 L433–442 | §7.2 | 已规范化 |
| §9.3 L444–451 | §7.5、§8 | 验证门保留；churn/alert 延期 |
| §10 L453–462 | §8 | 已审不做 |
| §11 L463–468 | §9 | 对外叙事，不作运行承诺 |

### A.2 固定术语

| 术语 | 唯一含义 |
|---|---|
| turn / decision step | 前者为v8逻辑turn、可含多个step；后者为一次模型决策及后续tools批次 |
| decision assembly occurrence | session 内成功提交的新 decision 装配序号，非事件 seq/semantic ordinal |
| 初始 decision seal / tools seal | 前者同事务发布新step/唯一LLM/首attempt；后者消费已接受tools plan、不装配 |
| execution / inspection | 前者与初始seal原子提交控制写；后者新只读假设装配、非历史trace格式化 |
| manifest | 既有 assemble manifest 的 v10 三层扩展，非授权凭证 |
| Feedback sample / emergent candidate | 前者合格普通LLM成功终局恰一次统计；后者提示内容、非工作账本/调度实体 |
| consumer_relation | 生产来源与唯一后继位置/消费者的关系 |
| publication identity / artifact identity | 前者workspace对象命令幂等身份；后者已发布内容对象身份；两域不可互代 |
| render identity | 文档/数据/presentation/profile/依赖闭包五元组 |
| plugin generation | v8 实现/readiness 域，非 persona version 或 v9 pack generation |
| assembly conformance / raw 准出 | 前者冻结输入到请求/确定决策的独立比较面；后者仅允许撰写、非实现/运行通过 |

### A.3 冻结 v8 具名锚点与审核承接

下表路径统一为 `docs/designs/v8-dev.md`（页首 871 行及 SHA-256）；原句起始均按实际正文复核，行号仅辅助。

| § / 具名段落 | 行范围 | 原句起始 / 本文用途 |
|---|---|---|
| §0 不可妥协的不变量 | L5–24 | `1. session_events 只追加`（标识原文带反引号）/ §0.2全文继承 |
| §1.2 规范化行为 ABI；§1.3 canonical JSON 与 render | L35–81 | `行为合同比较的是版本化的`；`canonical profile 冻结为具名` / §1、§6键算法 |
| §2 四平面；§2.1 授权线性化/双门 | L83–110；L147–165 | `运行前提（数据库版本冻结）`；`有效 grant 当且仅当` / PG15/角色/F-03/F-10 |
| §2.2 checkpoint/lost/fork | L192–195 | `1. 持有 session lease 的 worker 才可 mutate` / F-07、§3.7、§6.3 |
| §3.1 单一活跃 step；§3.1.1 INFRA | L201–223；L286 | `本节的 MUST / MUST NOT`；`fail_session 是受控内部入口` / R11、§6.2 |
| §3.1.2 receipt/八位锁序；初始decision/tools seal | L337–360；L376–386 | `stream_ingest 不映射为独立命令`；`command_request_hash MUST 由 SQL`；`初始 decision seal` / §6 |
| §3.2.1 聚合规则4/5/6 | L435–464 | `effect → step → session 聚合必须` / 关闭ready、R11规则4/5回归 |
| §3.2.2 effect identity / complete_effect验证 | L466–695；L569 | `Session fence、job fence 与 effect identity`；`complete_effect 验证冻结为` / retry、Feedback |
| §3.3 assemble manifest | L709 | `inject 固定 assembly_cutoff_seq` / §3.2既有绑定 |
| §4 generation成员/readiness/第4条 | L731–749；L740 | `plugin_implementations 显式携带`；`4. in-flight` / §2.2、§5.4、§6.3 |
| §5.2 dispatch拦截 / §6 P0B/P0C | L786–811；L819–825 | `P0C 开始之前必须验证`；`实现 user event` / §1.4、§7.1 |

审核路径为 `docs/reviews/v10-raw-oracle-review-2026-09-10.md`：轮3 L95–180、轮4 L182–210、轮5 L212–244；最新裁决优先。
轮5 L216“0 P0 / 0 P1 / 1 P2”与L238准出承接 → consumer_relation §4.3–4.4/§6.5；Feedback §4/§6.5；needs_preparation §3.8/§6.2–6.3。
发布承接 → §5/§6.4–6.6；R5-P2-1（L234）→ §7.2–7.4分组关闭；轮4稳定排序裁定→§3.3–3.4/fixture1。
F-04继承唯一canonical与v8 Conformance10，新增§1比较面；F-08→§6.1；F-09→§7 A2；F/R11均为继承回归，不恢复旧缺口。
研究 digest 只作来源背景，不以其旧13/15 kinds或旧planned问题覆盖raw；v9共存来源为raw §7.4，不承诺整合。

### A.4 DoD 自查与微观决定

以下仅文档自查，A1等序号对应撰写合同§3.9；轮1 L4基线为0 P0/9 P1/2 P2。版本承接索引：Turn1修订逐项补D1-P1-1..9与D1-P2-1（轮2确认六项关闭）；Turn2修订补D2四项——D2-P1-1查询权威源、D2-P1-2指针锁图、D2-P1-3派生identity边界、D2-P2-1初始化P0基础/P1扩展分期（5-I0/5-I1，轮3确认关闭）；Turn3（本轮）处置轮3维持的D2-P1-4（§4.2/§6.2唯一聚合顺序与两分支冻结、fixture 9-P0e1/e4三层断言）与新增D3-P1-1（§6.1/§6.4/§6.5/fixture 5-Md revoke_active每session受控父命令×v8内部审计域接合）。
S1续跑仅补D2-P1-4：§6.2两分支复用v8-dev §1.2唯一reducer优先级(4)，9-P0e1/e4补资格前置、失败end/槽位与crash/原receipt重放断言；当时generation问题与fixture1a nit未处理。

S2仅补D4-P1-2：§6.1/§6.5改为显式置空→全新恢复代发布→再次下线，5-Ma及5-Me–5-Mi覆盖生命周期/CAS/逐session审计/crash/历史重放；未改retired既有工作规则，fixture1a nit仍留后续。
以上各轮均仅静态核验，**结构检查完成、协议自查待父控制器L4关闭**；不能把落文当审核通过。D1-P2-2仍留P2渲染发布schema/fixture7-P2定稿前承接，本轮未裁定。

| 组 | 逐项检查与证据 | 文档结论 |
|---|---|---|
| A（9项） | A1固定章号；A2对象/IdentityKey/权限§2；A3三类入口、A4显式管理/初始化合同§6.1；A5拒绝/INFRA/crash§6；A6锁序§6.5；A7承接A.3；A8分组§7；A9无可执行DDL | 结构检查完成，协议待L4关闭 |
| B | raw §0–11及全部子节见A.1；规范化/背景/已审延期，无研究摘要替代，范围不重开 | 结构检查完成 |
| C（12项） | C1全文18条比较；C2原子seal；C3retry冻结；C4ready后finish；C5排除入口；C6occurrence独立；C7当前双门；C8内容/世代正交；C9对象receipt独立；C10三层字节不改ABI；C11双门/双边界；C12 F/R11 | 防回归静态检查完成，协议待L4关闭 |
| D（11项） | D1无自动准备；D2无跨调用PTL；D3不跨turn投递；D4inspection零落表；D5不换冻结placeholder；D6Writer不控wire；D7不强制进程隔离；D8不默认v9；D9既有文件只读；D10无生产代码；D11不报未运行通过 | 范围/结构检查完成 |
| E | v8接入/命名证据、三spike、POML隔离、实现后vectors/crash/capability见§7.1/7.5；另D1-P2-2按轮1承接，非本轮任务 | 结构检查完成；审核/运行验证未执行 |

计划未指定的微观决定集中登记，均为本草稿待审核版本化规则，不冒充raw已冻结细节：
- M1：profile/sidecar/关系/拒绝的逻辑schema、全部FK带W；统一IdentityKey与完整identity碰撞检查、管理许可/源权限矩阵§2；context_query_registry@v1为query_id唯一权威登记源（§2.4，显式新增登记对象，非host allowlist/调用方SQL，recall门零receipt/audit）；失效候选不增后台清理。
- M2：priority/required最低表示/有限重排/白名单Trim/完整History变换；版本化latch声明与turn窗口、provider_markerable资格、spill_archive确定表示§3，均有fixture。
- M3：digest第257项驱逐、nearest-rank百分位、half-even定点EMA、冻结桶定位与可空Bind计量sidecar；可选缺失不更对应桶，不收provider耗时。
- M4：persona顶层右覆盖/null后验schema、指针CAS与session初始化串行；generation stage/activate/fail_build/revoke_active及初始化显式O合同§6.1（revoke_active含每session受控父命令/receipt派生与v8内部审计域接合，fixture 5-Md）；恢复服务仅NULL→新identity stage/readiness/activate，5-Me–5-Mi验证再次下线及旧receipt不被新guard改写；包三形态不变。
- M5：descriptor/Bytes@v1/provider wire三层与hash无环、portable映射；O receipt两outcome、ARTIFACT优先；binding_locator固定81字节receipt键为统一键尺寸的O域显式例外（普通复合键48bytes，§2.1/§6.4、fixture 7-K/7-Kr）；既有request_hash仍canonical descriptor，不改v8算法。
- M6：控制写统一READ COMMITTED；预读仅发现锁集、锁后单次捕获；合法History原子组截取而非调用摘要器。
- M7：sample/候选排序、trace一次补全与正常分流不变；持久损坏受控INFRA/drain保持父cause；A1真实行锁两序与CAS单列、3b/5-P0前置已补，运行证据仍待§7。

