# Postgres-Native Agent · V10 设计稿（raw）

> 基线：冻结的 `docs/designs/v8-dev.md`——18 条不可妥协不变量、四平面、双运行时、规范化行为 ABI，全部原样继承。
>
> v10 在其上做**叠加式重构**：把 assemble 平面（不变量 9 的宿主）显式化为五阶段 context pipeline，新增 poml 声明层插件形态，吸收 pgAgentOS 两个要素。
>
> 本文是**设计稿**，对标 `v8.md` 的叙事密度，不是 `v8-dev.md` 的实现规范。状态机级的 MUST/MUST NOT 细节（seal 事务、receipt 元组级）留给 v10-dev——v10 的核心贡献是架构叙事（"上下文装配回归数据库"），未审定细节不提前伪冻结。
>
> 输入：`docs/analysis/v10-sources-digest-2026-09-10.md`（contextpipe / poml / pgAgentOS 三源研究）+ 2026-09-16 第三轮复审。本稿所引“v8 §”均指 871 行冻结 `v8-dev.md`，不指历史 `v8.md`；本次修订尚待父控制器复审。

---

## 0. 一句话宪法

- **v8 的 18 条不变量零修改**（v8-dev §0，编号与语义原样引用）。四平面、双运行时、闭合状态机、effect ledger、seal/receipt/fence 语义全部保留。v10 的改动集中在不变量 9 的**实现结构**，不是它的语义。
- v10 新增一句：**上下文装配是一等 SQL 查询路径**。catalog、optimizer、statistics、EXPLAIN——ContextPipe 从数据库借走的四件套，回到数据库成为表与函数。
- 管道的编排者不是新组件，是既有的 assemble 控制事务。五阶段不是新运行时，是 `advance_session` 里一个未展开步骤的内部结构显式化。
- poml 是**声明式 section 作者语言**，不是管道的总声明，更不是 prompt 的私有格式（§4）。

## 1. 统一叙事：上下文装配即查询执行

### 1.1 类比成立，但修正一处

ContextPipe 论文自我定位 "structurally isomorphic to query execution"（Abstract），与 v8 不变量 9 完全兼容。但类比对象不是"SQL 文本 × 执行器"整体，而是**声明式意图 × 带 catalog/optimizer/statistics/EXPLAIN 的执行器**。区别在于：SQL 文本是用户意图的全部，而 poml 文档只是**众多 context source 之一**——它经注册标签产出部分 section 的内容；fold 产物（历史）、recall 产物（记忆）、tool catalog（generation 绑定）都不经过 poml。

因此 v10 的统一叙事是：

> **上下文装配是一等 SQL 查询路径**：catalog（sections 目录）+ optimizer（确定性 tier-gated 变换）+ statistics（PipelineStats）+ EXPLAIN（assembly_trace），全部绑定 v8 既有的 snapshot / cutoff / generation。

poml 在此叙事中的位置是**声明式 section 作者语言**：它声明某些 section 的内容结构，而非声明整个上下文。poml 之于其声明的 section，如 view 定义之于其产物——声明参与计划，不拥有执行。

### 1.2 四件套 → 表与函数

| 数据库概念 | v10 对象 | 形态 | v8 锚点 |
|---|---|---|---|
| catalog | `context_section_catalog` | agent_context schema 普通表 + 稳定视图 | 不变量 9 的 generation 绑定 |
| optimizer | `plan_assembly` 计算核 | 显式冻结输入 → 确定性计划；SQL/plpgsql、固定 `search_path` | 不变量 9；v8-dev §3.3 既有 assemble manifest |
| statistics | `context_stats` | 表（Feedback 写、Plan 读，跨 session 持久） | 统计面，类比 pg_statistic 的对外部分 |
| EXPLAIN | `assembly_traces` + `explain_assembly()` | execution 审计落表；inspection 仅返回计划与 trace | v8-dev §3.3 inspect 只读 |

明确：**不做 PG 系统视图伪装**。sections 目录、统计等是 agent_context schema 的普通表 + 稳定视图；这是权威性与生命周期选择，不以“系统视图由 C 实现、扩展无法建视图”为理由。

1. 注册、统计更新与 generation 发布需要受控写入的业务状态，不应伪装成 PG 内核元数据。
2. 租户 RLS、slice/grant 授权及 generation 版本化由业务表与 capability API 承载，视图只提供稳定读取接口。
3. 目录值经 MVCC 读取后进入既有 assemble manifest；“有快照”不等于授权永久有效，实时门仍独立成立（§2.2）。

取舍标准：当某对象需要 (a) 租户隔离、(b) 版本化快照绑定、(c) 被 capability API 写入三者之一时，它是业务表。"系统视图"修辞仅用于**设计叙事**（"这个目录之于 pipeline，正如 information_schema 之于 planner"），不用于实现形态。introspection 需求由稳定视图 + `explain_assembly()` 满足，与论文 §4.1 Runtime Introspection 对等。

### 1.3 与 v8 四平面的映射

| v8 平面 | v10 增量 |
|---|---|
| history（`session_events`） | 不变。History section 经 fold 读它，cutoff 绑定 |
| control | 既有控制表 + 目录/闩锁/persona_version（权威目录态：决定 plan 的输入，绑定 generation）；assembly plan/trace 行为审计留存（同 receipt 待遇，不可清理） |
| projection | 可由冻结源重建同字节的渲染缓存、spill 与 fold projection；不可重建内容按持久 artifact 保留，不能仅归为缓存（§2.4） |
| workspace | 不变。WorkingMemory 类 section **不引入**——workspace 是执行态，不是 context source |

### 1.4 与 Astra 的形态差异：状态全是表行

Astra 的 `PipelineSession` 是进程内可跨 turn 可变对象（latches/emergent/recovery/stats 持有于内存）。pg-agent 采纳的持久状态**全部是表行**（跨调用 recovery 本版不采纳），session 行锁提供 Astra 用单例提供的 turn 级串行化。专有耦合逐项重绑：

| Astra 概念 | pg-agent 重绑 |
|---|---|
| `PipelineSession` 进程内态 | session 控制行 + `context_latches` / `context_emergent` / `context_stats` 表 |
| SectionKind 13+ kinds 中的 RuntimeIdentity / RuntimeVolatile / DeferredTools / WorkingMemory（数量依论文/代码版本而异） | 重绑为 PG 语境 kinds（§2.3）；WorkingMemory 不引入（§1.3） |
| `ProviderCachePolicy`（代码内 policy 常量） | catalog 注册表行（`provider_cache_policies`：provider → marker 上限 / 粒度 / global scope 支持），Plan 读行而非读代码 |
| `ContextChannelProvider` trait（bridge 逃逸口） | 不需要：插件经 `systemPrompt.section` 登记（v8 §4 既有 capability），登记产物是 catalog 行；trait 的编译期迭代保证换成"注册即行、Plan 枚举行" |
| Memoria / MemoryEntry | v8 `recall` 能力缝的 DB-local 授权读取，或预先发布的完整记忆 artifact；首版不为目标 session 自动调度检索（§2.2） |
| `SpillBackend` trait | `context_spill` 表（bytea/TOAST + sha256），无 trait，一种实现 |
| `RecoveryState`（PTL 后 tier 升级态） | 不照搬跨调用恢复状态；首版只有 seal 前装配决策内的 tier 升级，最终选择进 manifest。provider PTL 依 v8 失败合同收束（§2.5） |

## 2. 上下文管道（新章）

### 2.1 五阶段 = assemble 的内部结构

v8-dev §3.1 的 `advance_session` 已将 step 创建与初始 decision seal 同事务发布，§3.3 已有 assemble manifest。v10 展开其内部计算与应用，不另造前置持久化 step：

```text
v8:  tx: assemble + create step + 初始 decision seal
v10:  tx: Plan → Bind(DB) → Optimize → Serialize
            → create step + 初始 decision seal（payload 即序列化产物）
```

seal 语义、receipt、fence、audit 原样继承。Astra 把 Execute 拆为 Serialize + 外部 provider dispatch——在 pg-agent 里，Serialize 进事务、Execute 就是既有 LLM effect，这个拆分恰好落进 v8 的"短事务 + effect worker"结构，不需要新容器。

### 2.2 阶段–事务归属表（本章锚点）

约束来源：不变量 4（含宿主 handler 禁事务内执行）、9、12、17，以及 v8-dev §2/§2.1、§3.1/§3.3。**输入获取、纯计算、状态应用是三类职责，不强制映射为三个固定 volatility 层**：读取/授权入口提供值，计算核只消费显式值，控制入口应用决策并负责锁/CAS。需要行锁、实时重验或 CAS 的路径不能塞入 STABLE 读取函数；只有不读可变表、不写状态的计算核才可声明 IMMUTABLE。函数签名及 volatility 逐函数审计留 v10-dev。

v8-dev §3.3 已规定 fold/recall/catalog/grant/policy 绑定同一 manifest hash。v10 **扩展既有 assemble manifest**，纳入计算实际消费的 catalog、stats、persona/有效参数、latch/emergent 值、artifact 字节与 provenance、tokenizer/预算规则、render/provider/canonical profile 和降级决策。**冻结计算输入不冻结授权有效性**：按 v8-dev §2.1 的授权线性化点执行锁/CAS，seal 与 dispatch 各自重验当前有效 grant/slice；不得把 manifest 当授权凭证。v8-dev §2 指定的锁后重扫描协议事务保持 READ COMMITTED 前提及入口检查，不将它误写成所有纯读取的隔离要求。

| 阶段 | 事务归属 | 输入/计算职责 | execution 状态应用 |
|---|---|---|---|
| **Plan** | 控制事务内 | 获取 catalog/stats 等值、形成冻结输入；计算 pressure/tier/budget | 提交选定 manifest/plan，非纯函数自行落表 |
| **Bind（DB）** | 控制事务内 | 经 capability API 读取 cutoff fold、persona、emergent 候选、已发布 artifact；禁止外部 I/O | 消费 emergent、冻结 latch 属控制写入，与 seal 原子提交；inspection 不做这些写入 |
| **Optimize** | 控制事务内 | 排序、tier-gated 变换、marker 与 spill 决策均为纯计算 | 控制入口写 spill、applied/skipped trace，不称这些 INSERT 为纯函数 |
| **Serialize** | 控制事务内 | 生成 canonical provider 请求；验证 wire prefix 共享资格 | 选定 payload 随初始 decision seal 写入 effect_requests，seal 后不可重装 |
| **Execute** | **事务外** | 既有 LLM effect 的 dispatch / 外部调用 | completion 仍按 v8 证据、receipt/fence/聚合合同分流；v10 增量仅限下述合格 Feedback |
| **Feedback** | 合格的普通终局 `complete_effect` 事务内 | 读取本次已接受 LLM 成功结果与 usage | 样本去重后原子更新统计、emergent 与 ANALYZE；不是对所有 completion 的通用回调 |

**preparation 范围裁定**：DB-local 已授权读取可直接进入 Bind；事务外检索、live workspace 读取与 TS 渲染不能进入控制事务。首版只消费**预先发布、已完成物化的不可变 artifact**：构建在目标 session 装配之前由独立预构建流程完成，发布入口只接收完整字节、依赖摘要与 provenance，经受控授权/完整性校验后一次发布；未完成/迟到/依赖漂移的制品不冒充所需版本。发布是 v10 新增的控制写操作，需权限与 receipt 合同（§3.2），不是 session preparation batch 或无 step 的 effect。首版不调度构建、不承诺恢复外部预构建进度；缺必需物化输入时返回 `needs_preparation`，不创建 step/effect，由调用方备好制品后重新请求装配。

**`needs_preparation` 控制入口约定**：这是可恢复的前置输入不足，不自动映射为 `INFRA_ASSEMBLY_FAILED`，不新增 session 等待态。execution 拒绝不创建 step/effect、不消费 emergent，保持请求事务进入前的 session/lease/fence；已 claim 的 session 仍为 `claimed`，拒绝事务不隐式释放 lease 或推进 fence。参照 v8-dev §4 第 4 条 `NO_ACTIVE_GENERATION` 模式，coordinator 须经独立、遵守 checkpoint/lost 与现行状态门的显式 yield 释放 lease、回 `ready`（或经既有收束路径离开），不能持控制事务等待制品。命令 receipt 与重新装配身份见 §3.2；inspection 仍按 §2.6 零写集返回。

自动 preparation effect（包括动态 `<query-result>`/recall/poml_render）明确延期；仅新增 effect kind 不会获得合法 slot。未来若扩展，须单独论证单活跃 step、seal、取消、unknown、driver switch 与 generation drain，不能声称继承 v8 的现成 preparation 协议。

**Feedback 触发合同（首版）**：仅普通 `complete_effect` 新接受的、当前未被 supersede attempt 的 LLM 成功终局，且流式结果已满足冻结 v8 成功/完整性判据、usage 合法可用、目标 session 非终态且 driver_mode=active、无 sticky cancel 时，才产生一次 Feedback。样本逻辑身份为 `(effect_id, feedback_profile_version)`，其中 profile 随 effect 创建冻结，绑定已接受 attempt 与 result digest 作冲突校验；升级 profile 不追补旧 effect，不同 command_id 不得重复计样。样本登记与 percentile/EMA 更新、emergent 入队、ANALYZE 补全在同一事务提交；重放不补更新、不重复消费。

非终局 observation、拒绝、receipt replay、旧 attempt、失败/unknown、repair/reconcile（包括其成功收束）、终态 drain 以及非 LLM effect **均不进入 usage 样本、不更新 EMA、不产生 emergent**。它们只保留各自 v8 已允许的观测/审计，不扩大受限写集。首版不追补 repair/reconcile 的 usage：恢复成功与统计采样是两件事；渲染 token 测量是发布 metadata，不伪装为 LLM Feedback。去重存储与样本/聚合并发细节留 v10-dev。

**统计采样与 emergent 投递分离**：以上 Feedback 资格谓词、effect/profile 去重与原子提交合同不变；其中“emergent 入队”只适用于仍可能有合法后继装配的候选，实际消费另受 §2.4 的资格门约束。满足上述谓词的 `decision_only=true` 成功关闭 decision 仍恰计一次 usage/EMA 样本并补全 ANALYZE，但因 turn 已关闭，其 emergent 候选在同次处理即丢弃、不入待消费集合，不承诺下一次消费。合格非关闭 decision 产生的候选按 §2.4 等待后继装配；统计成功不等于保证可投递。

### 2.3 SectionKind：PG 重绑的闭合集

```text
Identity         ← persona_version 快照（§5.2 吸收项）
Constraints      ← persona_version + 输出格式行
History          ← fold(session_events, cutoff)（v8 既有 fold 缝）
Memory           ← DB-local recall 授权读取 / 已发布记忆 artifact
ToolSchemas      ← tool catalog @ generation（v8 既有）
Skills           ← 插件目录 provide 的 section 行
ProjectContext   ← 已发布 workspace slice 内容 artifact（非 live workspace）
SessionRuntime   ← session 控制行派生（model/date/workspace_id 等，Session scope）
TurnVolatile     ← turn 参数、inject @ cutoff
EmergentSkills / EmergentMemory / EmergentSummary ← context_emergent 行
```

锚定规则（论文 Lemma 1/2 保留）：Identity/Constraints 不参与重排、永不被压缩（priority=Never）；tool-call/result 配对由 History 折叠的原子性保证——v8 事件结构既有，不需要论文 Lemma 3 的新机制。

**枚举完整性**：Astra 靠编译期 exhaustive match 保证新增 kind 不会漏掉预算分配；SQL 没有这个机制。v10 用两道保险：catalog 的 kind 列以 CHECK 约束钉住闭合集；conformance fixture 枚举全部 kinds × budget 分配规则，断言每种 kind 都被覆盖——新 kind 进了 catalog 却没接预算规则时，fixture 红（§8 第 8 条）。

### 2.4 表形态（agent_context schema，暂名）

- **`context_section_catalog`**：目录本体。列对齐论文 Table 2 九字段（`tier, kind, scope, priority, est_tokens, bind_latency_ema, recoverable, provider_markerable, dependencies`）+ v8 必备列（`workspace_id, generation_id, plugin_identity`）。RLS 按 workspace_id；`generation_id` 使目录随插件世代版本化（应用不变量 13 于目录内容）。
- **`context_latches`**：`(session_id, latch_key, latch_value, fired_seq)`。首次触发时同事务写入，之后冻结——论文 SessionLatches 的 SQL 形态，对应"one-shot DDL committed inside a transaction"。防 cache break：已选择的 beta header/feature flag 等内容参数中途不翻转；latch 不冻结当前授权、generation 或 provider 共享资格（§2.2/§2.7）。
- **`context_emergent`**：概念字段为 `(session_id, item_id, kind, content, content_hash, produced_seq, consumer_relation, cap_class)`。TTL = 生产 effect 完成后，同 session **下一次符合条件的新 decision step 的 execution assemble**，不是冻结 v8 的“下一 turn”。ContextPipe 的下一装配轮次映射为 v8 新 decision step 的初始 decision 装配：前一 decision 返回 tools → tools 批次以 `final_tools=true` 全成功 → 同 turn 下一 decision step（v8-dev §3.1/§3.2.1 规则 6）；tools seal 本身不是该轮装配。消费资格要求生产 step 已收束、所属 turn 未关闭、session 可按既有状态门创建新工作；不新造 turn 或持久化未 seal step。
  - `consumer_relation` 表达生产 effect/step 与下一逻辑装配 occurrence、目标 decision step 的关系，目标绑定与初始 seal 原子提交；occurrence 按成功提交的新 decision 装配计，不按请求尝试次数计。`produced_seq` 仅作溯源；`session_events` 物理 seq 含工具与 observational 事件，不隐式等于装配轮次，禁止以 `produced_seq+1`/物理 seq 窗口判资格（撤销旧 `consume_by_seq` 表意）。inspection 不消费也不推进 occurrence；assemble 回滚不消费、不推进或占住目标资格；已 seal effect 的 retry 不重新装配、不再次消费，复用冻结 manifest/payload。
  - 写入时 content_hash 去重；per-list cap 由唯一约束 + 计数检查实现。消费删除与 assemble/初始 seal 原子提交；该 step 后续 Execute 失败不恢复已消费项：emergent 是提示而非工作账本，消费字节已进冻结 manifest，同请求重放不能因源行删除而少字节。下一合格装配提交即结束该批候选的单次投递窗口，未选入项亦不延到再下一 step。turn 关闭（`decision_only=true` 成功）、cancel 或 session terminal 后无合法后继装配的项一律逻辑失效、丢弃投递资格，不跨 turn/session 转投；判失效不开放终态新工作或 observation 写集。物理清理、关系存储与并发原子性细节留 v10-dev；TTL/hash/cap 三重保险保留。
- **`context_stats`**：`(workspace_id, model, query_source, bucket_kind, percentile_digest jsonb, ema_fields..., updated_at)`。percentile digest 用 jsonb 存排序样本数组（cap 512、median 驱逐——论文 §3.8 的 exact sorted digest，plpgsql 实现简单可审）。单 turn 开销与多 session 同桶正确性均由 §9.3 spike 验证；若采用 worker 计算，仍须版本校验/合并与原子提交，不能以覆盖结果丢失并发样本。
- **`context_spill`**：持久行保存内容字节、hash 与源 manifest 引用，不用 temp table 或 FDW。可重建源必须从冻结源重建**同字节**并验 hash；不可重建源按持久 artifact 保留，不可当缓存驱逐。optional 只允许在**一次新的装配决策**中选择 placeholder/跳过，选择及原因进入 manifest 与 decision trace；同一已冻结 manifest 重放时不能因今日丢失而换 placeholder。无法恢复冻结字节则明确失败/不完整；已 seal 请求只使用其冻结 payload。授权失败永不按 optional 降级（不变量 11）。
- **`assembly_plans` / `assembly_traces`**：每次成功 execution assemble 的 plan 行与 trace 行（inspection 仅返回值；audit 类，绑定 `(session_id, step_id, snapshot/cutoff/generation)`）。trace 含 applied 与 skipped 变换（论文 Property 1 审计完整性——被 gate 阻止的步骤与执行的步骤同样可观测）。
- **函数**：输入获取/授权入口、消费显式冻结值的 `plan_assembly` 计算核、execution 控制应用入口、`explain_assembly` 与 inspection 入口；不可把按 session_id 读表的入口统称 immutable。签名留 v10-dev。

### 2.5 压力、tier 与纯函数纪律

压力公式照搬论文 §2.2/§3.2：

```text
P_raw  = T_used / L_eff
P_pred = (T_used + R_o + R_t + R_s) / L_eff
```

R_o 从冻结的 `(model, query_source)` 分桶值取 p75（steady）/ p95（seal 前保守重算），空桶回退固定 floor（500 tokens）；R_t/R_s 是类型化预留槽，当前估为 0。tier 阈值 0.60 / 0.75 / 0.90（Normal / TrimSchemas / CompactHistory / AggressivePrune）；predictive 只升不降。**首版仅支持 seal 前本地预算重算与 tier 升级**，最终选择随 manifest/payload 冻结，不持久化跨调用 PTL streak。

provider 返回 PTL 后按 v8-dev §3.2.1/§3.2.2 既有证据与失败合同处理：同一 effect 的合法 retry 仍复用冻结 request_hash/payload；不能通过 retry 改 prompt。terminal failure 即时派生 session failed，不存在失败后自动新建 step 的恢复窗口。跨调用自动重装恢复明确延期，须先扩展协议；unknown 保持 unknown，不能靠 PTL 计数推断为已知失败。

重排按 cache scope 波动率升序（Global < Session < None，同 scope/同优先级的并列以冻结的逻辑 section/source identity 或跨实例可重现的规范键破并列成全序；键及必要的逻辑 occurrence 区分随输入冻结，按规范字节序比较，禁止依赖物理行 ID、locale 或无序查询结果）；Identity/Constraints 锚定不参与排序；marker 放在 scope 边界，受 `provider_cache_policies` 行的 M_max/粒度/prefix-only 约束；本 turn 翻转的 latch 抑制 None-scope marker。reorder 受 max_moves 约束，CompactHistory 受 max_clear_tokens 熔断。

**纯计算纪律**：tier、budget、重排序与 marker 计算只消费显式冻结值，输出计划值与 decision trace，不读实时表、不写 spill/latch/plan。SQL 计算核采用 `SECURITY INVOKER`、固定 `search_path`；输入获取与受控应用不冒充纯函数（§2.2）。这是可回放性要求，不是另行冻结第三条新不变量。

### 2.6 EXPLAIN 与 explain-only

execution trace 行落表（audit 类），`explain_assembly(session_id, through_seq)` 返回格式化 trace——对应论文 §5 EXPLAIN ANALYZE 的双层结构：pre-execution 部分是 EXPLAIN（压力分解、tier、每 section 计划/实测 token、变换决策、marker 位置），post-execution 部分是 Feedback 补全的 ANALYZE（实际 input/output token、cache read/creation、与计划估计的 delta）。

**execution / inspection 双模式**共享 Plan → Bind(DB) → Optimize → Serialize 的计算核，**不共享写入行为**。execution 经控制入口将 manifest、plan/trace、latch、emergent 消费、spill 与 step/初始 decision seal 同事务应用；inspection 完全只读，plan/trace/请求描述符都是返回值，不写上述表、不写 stats/receipt、不建 step/effect、不取推进 session 的 lease，也不持久化审计。若未来需要持久化 inspection 审计，必须另立显式有写入的操作。

无 step 的 inspection 使用返回值中的独立 `inspection_id`（不冒充 step_id）及输入 manifest digest/cutoff 标明本次观察；身份不参与 portable 比较。读取先满足调用方当前权限；本地表/TOAST 可读，foreign table、dblink、live workspace、宿主 handler 与任何外部 I/O 禁止。缺已物化输入时返回 `incomplete/needs_preparation` 与缺项，不触发准备、不伪造可发送请求；可选降级仅按 §2.4 形成新的假设决策。inspection 结果不能直接当执行许可，execution 必须重新授权并完成 seal。

### 2.7 ForkPrefix：父子前缀共享

v8-dev §3.3 的稳定 `parent_through_seq` 只保证子会话逻辑历史，不自动赋予父 prompt 共享资格。ForkPrefix 分两层：**不可变内容 artifact 复用**只免去重新构建，仍校验子会话对实际来源的读取授权与内容/provenance；**provider canonical wire prefix 共享**必须在 Serialize 层另验实际依赖的授权、内容字节、渲染身份、persona/有效参数及 provider profile/marker 布局全部兼容。Global/Session scope 与 sha256 相同本身均非授权证明。

fork grant 仅按 v8-dev §2.2 第 4 条复制 `delegable=true` 的不可变 slice grant（新 grant_id）；不继承父控制态、live handle 或 latch。权限不足则禁止复用并按授权策略处理；其余不兼容则普通装配，决策 trace 记录不共享原因。cache probe 仅观测，不作为资格或正确性证据。父后续变化不改已冻结子请求；负向 fixture 归 §8/§9 P1。

### 2.8 双运行时义务：prompt 装配拦截门闩

五阶段是**数据库内**结构：Plan/Bind/Optimize/Serialize 是 SQL 函数与表，native 与 dsh-compat 走同一套函数。dsh-compat 的差异仅在 Execute 侧（Node host 的 LLM 调用路径），这正是 v8 §5 既有 adapter 层职责。compat 必须经同一 `plan_assembly` 拿到序列化产物，**禁止 host 侧自行拼 prompt**——写入 compat 义务清单，是 v8 §5.2 dispatch 拦截门闩的自然延伸（dispatch 拦截管"IO 前落盘"，prompt 装配拦截管"prompt 字节出自产物表"）。可回放性（论文 Property 2）由"全部输入是表行快照 + 纯函数"保证，双运行时共享。

### 2.9 两条新不变量候选

v10-raw 提出、v10-dev 审定（编号在 v10-dev 冻结时分配；18 条既有不变量零修改，见 §7.1）：

1. **执行管道与 seal 同事务**：execution 的 Plan/Bind/Optimize/Serialize 必须与 decision seal 同一控制事务；trace 与 plan 行同事务提交。inspection 仅复用计算核，不适用 seal/落表义务。
2. **Bind 禁外部 I/O**：首版只消费 DB-local 授权值及预先发布的完整 artifact；若未来由 runtime 自动准备外部源，必须先定义合法的持久化执行归属，不得绕过 effect ledger。

## 3. Native 核的变化

### 3.1 advance_session 的展开

见 §2.1。唯一结构变化：LLM effect 的 payload 从"assemble 时生成"变为"Serialize 产物"——`request_hash` 覆盖该 payload，幂等键照旧库内算，fence/lease/envelope 校验零改动。seal/receipt/fence/audit 全部原样继承。

### 3.2 命令与对象增量

- `explain_assembly(session_id, through_seq)`：只读格式化函数，inspection 类，不推进状态机。
- EXPLAIN-only assemble 变体：同 §2.6，inspection 类（不创建 step/effect、不改 session 状态，§8 第 2 条断言）。
- 首版不新增自动调度的 `poml_render`/`recall` effect kind；v8 的 effect_submit/create_effect 没有无 step 通道，已 seal batch 也不能补成员（v8-dev §3.1/§3.1.2/§3.2.2）。
- 新增受控 artifact 发布写入口（暂称 `publish_context_artifact`）：输入为已完成制品，校验发布权限、内容/依赖摘要与 provenance 后原子发布；与目标 session 执行解耦，不调用 renderer、不创建工作、不替代来源读取授权。这是独立对象管理写命令，不直接复用 v8 的 session receipt 键域：拟以 `(workspace_id, publication_id)` 绑定规范化发布内容，重复同内容返回原发布 identity、异内容拒绝。仅受权发布者可调用，发布权不授予目标 session 读取权；借鉴 v8-dev §3.1.2 授权前置/幂等原则，独立 receipt 命名空间与权限/schema 在 v10-dev 定型，不声称 v8 已有该命令。
- `needs_preparation` 是既有 execution 装配控制入口的前置拒绝结果，不是发布命令或新等待态。通过授权前置门、已进入命令处理的可归属请求，将该结果及缺项记入父控制命令的稳定 receipt；沿用 v8-dev §3.1.2 的历史 receipt 命中原样返回、不重执行，即使制品随后补齐，同 command ID 也不会重新装配。调用方负责在事务外补齐并受控发布所需版本，确认缺项满足后，以**新 command ID** 和当前有效 claim/lease/envelope 发起新的 execution 装配请求；不复用旧拒绝身份或旧 lease。§2.2 的显式 yield 与装配拒绝是两个控制操作；具体入口归属、receipt 结果编码和重发流程在 v10-dev 定型，不扩展 v8 闭合 outcome 集，inspection 不落 receipt。
- 发布命令从 P0 起就须保证制品发布与其独立 receipt 原子提交；响应丢失后同 publication ID 重发返回原结果。§8 fixture 7 拆为 **P0 基础发布组 / P2 渲染扩展组**；P2 增渲染身份验证，不是首次测试发布命令。
- 对象清单为 §2.4 + §5.1；入口分为只读 inspection/格式化、既有控制命令的内部应用增量、独立发布写命令三类。F-08 先核对清单，再在写命令定型后收口 receipt；新增函数名、effect kind 不自动等于新增 receipt 行（§7.2）。

### 3.3 R11 残留核对

R11 改为冻结合同的**回归断言**：v8-dev §3.1、§3.1.1 begin_switch guard (iv)、§3.1.2 初始 decision seal 及 §3.2.1 已排除无 effect 的持久化 planned step。pipeline 不得重新引入该中间态；首版不增 preparation 工作，因此不改 switch/drain 屏障。未来扩展准备协议须重新证明，不能援用已消失的问题域。

规则 4 精确继承 v8-dev §3.2.1：关闭残留 eligible sibling 后产生 `not_retry_eligible`，与 `budget_exhausted` 混合时 code 为 `FAILED_TERMINAL`；只有全部 terminal failure reason 为 `budget_exhausted` 才是 `FAILED_RETRY_BUDGET_EXHAUSTED`。规则 5 仅接无 terminal failure 的 eligible retryable 批次；验收不能只检查“预算耗尽”字样。

## 4. 提示词语言（新章）

### 4.1 poml 是什么、不是什么

poml（Prompt Orchestration Markup Language）：HTML 风格标记 + 组件体系 + CSS 风格 stylesheet + 模板，三遍渲染（Reader → IR → Writer）。pg-agent 采纳它的**内容结构声明**能力，不采纳它的"prompt 总格式"地位。

- **是**：声明式 section 作者语言。渲染产物是 catalog 中部分 section 的 source（经注册标签产出）。
- **不是**：管道的总声明——fold/recall/catalog 不经过它；也不是 prompt 的私有格式——线格式由 pipeline Serialize 独占（§4.2）。

### 4.2 三层序列化边界

| 层 | 职责 | 产出 | 时点 |
|---|---|---|---|
| 1. poml Reader → IR | 声明层内部：源文档 → IR 元素树 | 数据，随完整制品发布 | 首版预构建流程；自动 effect 延期 |
| 2. poml Writer | 内容序列化：IR → section 文本 / messages 片段 | **BoundSection 的 artifact 内容** | 首版预构建后完整发布，Bind 仅消费；未来自动路径须在渲染 effect 内执行落表，Bind 仍仅消费 |
| 3. pipeline Serialize | 线序列化：`(π, μ, M)` → provider 请求 | provider 请求描述符 | assemble 控制事务内 |

Writer 回答"这个 section 的字节是什么"，不回答"这些字节在请求里的位置"。**pipeline Serialize 是 provider 请求的唯一权威**：唯一拥有消息边界、role 分派、cache marker 放置、tool-call/result 配对的位置。对应 v8 §1.3 "execute 返回 canonical result 是权威值，render 是 projection" 的同构关系。

"两套序列化会不会冲突"——会冲突的情形只有一种：poml Writer 被要求产出最终消息文本，而 pipeline 又要重排。该情形被"Writer 只产 section 内容、Serialize 独占线格式"规则在结构上排除。

约束规则：

- poml 侧**禁止表达 cache 语义**（无 marker、无 scope 标注权）。`<role>`/`<task>` 经 Writer 产出文本后，其 CacheScope 由 **catalog 行**决定——哪个 section kind 消费这份文档，目录行的 scope 字段说了算。这防止声明层越权决定执行层缓存布局，类比：SQL 文本不能指定 buffer pool 策略。
- poml 的 `speaker` 属性映射为消息 role 的**建议**：Bind 阶段校验合法性（ValidSpeakers），pipeline Serialize 保留最终分派权（如 speaker=system 的内容是否并入 system block，由 provider policy 决定）。
- 冲突检测：同一 section 既有 poml 源又有静态文本源时，catalog 行的 `source` 字段唯一指定，不存在运行时合并。

### 4.3 渲染产物与准备边界

poml 渲染需要 TS 运行时，不能在 SQL assemble 或 Bind 中调用。首版遵守 §2.2 的范围缩减：**只消费预先发布的完整 IR/section artifact**，提供预构建与校验工具，不在目标 session 文档变更时自动 `effect_submit`。未来自动 `poml_render` 必须是有合法 step/batch/slot 归属的 effect；该协议未扩展前不交付 runtime 调度，也不借“冷路径”豁免账本。

**渲染身份**由 `(doc_hash, data_hash, presentation, render_profile_digest, dependency_closure_digest)` 决定。render profile 覆盖 renderer/Writer 与 component 实现 digest、plugin/contract 版本、locale/timezone/line ending 等影响字节的配置；依赖闭包覆盖 `<let>`、stylesheet、include、标签数据源的冻结版本与内容摘要，不能只 hash 外部路径。发布时验证实际构建 provenance 与该身份一致，缓存、产物、manifest 与 fixtures 使用同一身份。

跨 generation 仅在该渲染身份相同且当前授权满足时复用；generation 是绑定与 readiness 域，不是内容相等的替代判据。源码未变但 renderer/component/依赖变化必须得到不同身份。IR 可作为 Plan 输入，tokenizer 版本与实测 token 数随发布 metadata 冻结，Bind 只读产物字节；这些 token 测量不写入 LLM usage 样本。

### 4.4 标签初集与两条硬规则

挂载点：**components 层**。插件经 `component()` 注册 DB 标签，不 fork poml、不改 writer.ts。初集四个：

| 标签 | 数据来源（capability 缝） | 产出（标准 IR 节点组合） |
|---|---|---|
| `<schema>` | catalog 读取缝 | `table` / `obj` + `code` |
| `<query-result>` | 预构建时经授权查询缝物化的数据（grant 约束 max_rows；不在 Bind 动态执行） | `table` + `code` |
| `<migration>` | catalog 读取缝 | `code` + `list` |
| `<query-plan>` | 预构建时经授权查询缝物化的 EXPLAIN 结果 | `code` + `p` |

属性沿用 poml 内置（`presentation` / `markup-lang` / `serializer` 等）。

**硬规则 1（Writer 解耦）**：DB 标签的 render 函数只许产出 poml 内置 IR 节点（`table`/`obj`/`code`/`env`/`p`/`list` 等，可带 `presentation`/`markup-lang`/`serializer` 属性），**禁止自定义 IR 标签**。stock Writer 无需任何分支——Writer 耦合坑在规则层消解，不靠自律。

**硬规则 2（渲染身份隔离的证明义务）**：标签及 alias 的解析与执行不得跨渲染身份污染；同一进程交错使用新旧 generation，也只能得到各自绑定实现的结果，native/compat 受同一约束。generation 前缀本身不是 alias 隔离证明。独立进程、独立 registry 实例、经验证的 generation-aware resolver 都是候选，由 §9 的小型隔离验证选择；验证未过不得发布跨身份渲染支持，compat 内联不能成为旁路。

v8-dev §4 的登记键实际为 `(generation_id, identity, plugin_version, handler_name)`，readiness 绑定 implementation digest；同一不可变 implementation 可被多个 generation 共享。v10 将标签解析/依赖闭包的校验纳入自身发布 readiness 义务，不把“一代一 OS 进程”写成 v8 合同。

**数据获取只经 capability API**（不变量 12）：`<schema>`/`<query-result>` 的预构建数据取得需授权，发布与消费仍分别验证权限。render 函数只对冻结输入求值；动态查询结果未经物化时返回需准备，不允许在标签求值中打开 live DB/宿主连接。

`plugin_specs` 拟新增声明字段 `poml_components`（标签清单）；P2 制品发布校验标签实现与 readiness/provenance，未来 render worker claim 的接线须随 preparation 协议另审。

### 4.5 四个坑的规避汇总 + Python 分层

| 坑 | 规避 |
|---|---|
| Writer 耦合 | 硬规则 1：只产标准 IR 节点 |
| ComponentRegistry 全局单例 | 硬规则 2：跨渲染身份不污染的证明义务；隔离方案经验证选择，native/compat 无旁路 |
| Python 盲区 | 分层消解：Python 侧从不注册标签，它读写的是落表的 poml 源文档与渲染产物（canonical JSON）；注册只发生在持有 poml 引擎的 TS 预构建工具侧（未来自动化才接 render worker）。标签注册是代码（插件实现），文档与 IR 是数据（合同）——这不是 workaround，是架构分层 |
| IR 语义膨胀 | 初集仅 4 标签；通用数据用既有 `<table>`/`<obj>` 承载；新增标签需 v10-dev 逐个立项 |

### 4.6 双运行时渲染一致性

- **native / dsh-compat**：首版均消费同一受控发布的产物表；预构建验收 harness 分别运行两侧 renderer，不能以共读一行替代独立渲染字节对照。
- compat host 不得私有渲染后直进 prompt；未来内联 render effect 也须满足合法执行归属、相同渲染身份隔离及受控结果写入，当前不作为既有能力承诺。
- 同一完整渲染身份与冻结输入，两侧产物 canonical JSON 字节一致；输出差异不能用 cache hit 或相同 source doc 掩盖。该独立比较面入 F-04 增量 vectors（§6、§8 第 6/7 条）。

## 5. 数据面要点

### 5.1 agent_context schema 表清单（暂名）

```text
context_section_catalog     -- 目录本体（§2.4）
provider_cache_policies     -- provider → marker 上限/粒度/global scope（§1.4）
context_latches             -- session 闩锁（§2.4）
context_emergent            -- 下一合格 decision step 装配消费的涌现上下文（非下一 turn，§2.4）
context_stats               -- 分桶统计 + EMA（§2.4）
context_spill               -- 超大 section 溢出（§2.4）
assembly_plans              -- 每次 assemble 的 plan 行（audit）
assembly_traces             -- applied + skipped 变换 trace（audit）
persona / persona_version   -- §5.2
poml_documents              -- poml 源文档行（暂名）
poml_render_outputs         -- IR 行 + 渲染产物行（暂名，§4.3）
函数：plan_assembly 族 / explain_assembly / get_effective_params
artifact 发布入口           -- 只发布预构建完成的内容；不创建目标 session 工作（§3.2）
feedback 样本登记           -- effect 级逻辑身份去重；与统计/emergent 更新原子提交（§2.2）
```

各持久对象按 workspace_id 隔离且只能经受控入口写入；目录发布/世代切换、artifact 发布、session 内容初始化、execution 应用与 Feedback 各有独立写集。Feedback 更新统计不改不可变目录内容；RLS 不代替 capability 授权（§5.5）。

### 5.2 persona / persona_version（吸收项 1）

pgAgentOS 的 persona 指针表 + persona_version 不可变快照（immutable 触发器模式直接借用）。version 含 system_prompt / model_id / params；作为 Identity/Constraints section 的持久化形态；session 创建时冻结 `persona_version_id`。

与插件世代是**两层**——这是重叠消解的关键论断：

> **世代钉代码**（implementation digest + contract version，不变量 13 管）；**persona version 钉内容**（system prompt 文本 + params）。session 只冻结 `persona_version_id` 与有效参数；generation **逐 step/effect 绑定**，新 assemble 取当前 active generation，旧 step/effect 保留旧代（v8-dev §4、§6 Conformance 8）。Identity 内容不因代码换代隐式变化，session 也不能因 persona 冻结而永久钉住 catalog generation。

v8 有插件世代，但没有"prompt/persona 内容"的不可变快照——世代钉的是实现 digest，不是 Identity section 的文本。这是真实增量。

### 5.3 get_effective_params() JSONB 合并（吸收项 2）

用于 pipeline 的 model/params 解析：model 注册表默认值 `||` persona_version.params（JSONB 合并，后者覆盖前者），纯 SQL 函数。session 创建时物化进 session 控制行——**latch 语义，防 cache break**，不做每 turn 重算。

### 5.4 pgAgentOS 取舍总表

与 v8 已有机制逐项对账后，digest 的"融入 5 项"高估了增量：

| digest 建议 | v8 现状 | v10 裁定 |
|---|---|---|
| persona version 不可变快照 | v8 有插件世代（不变量 13）但**没有** persona 内容快照——世代钉实现 digest，不钉 Identity 文本 | **吸收（真实增量）**，§5.2 |
| `get_effective_params()` JSONB 合并 | v8 无参数分层合并机制 | **吸收（真实增量）**，§5.3 |
| `set_tenant()` + RLS | v8-dev §2/§2.1 已有 workspace_id + RLS + capability 权限边界（不变量 12/17） | **降级为模式确认**：v8 语义已超集；仅引用其"session 级 set_config 被 policy 消费"作为既有模式佐证，不引入新对象 |
| `run.parent_run_id` 嵌套 DAG | v8 已有 fork 的 `parent_session_id` + `parent_through_seq`（§3.3），subagent fanout 走子 session | **拆分**：嵌套执行 DAG 本身**跳过**（与 v8 session/fork 重叠，引入即第二套真相）；唯一吸收"父子共享上下文前缀"的动机——由 ForkPrefix 承接（§2.7），比 parent_run_id 更贴合 v8 模型 |
| `poll_job()` SKIP LOCKED | v8 effect ledger 的 claim 语义已超集（fence + lease + envelope 校验） | **跳过**（作模式确认引用）：plain SKIP LOCKED 没有 fence/envelope，低于 v8 水位 |

抛弃五项，全部确认：

- RAG 套件（管道不完整：embedding 仅 enqueue 无 worker；与外部 pipeline 路线冲突）；
- skills `impl_type='http'`（DB 存 HTTP endpoint 当工具，既不安全也不可观测）；
- `principal.role` 列（无配套授权逻辑的虚假安全）；
- glass box 叙事（"每个 thought 都是行"，无 reasoning trace 表支撑）；
- **`send_message()` 的并发编号/幂等缺口**：撤销“多条 DML 因而非原子”的批评，函数内这些语句处于调用事务中；真正需补的是并发 turn 编号分配及重发去重合同。v10 继续继承 v8 的受控编号、receipt 与初始 decision seal 原子发布，不以错误的原子性归因作反面教材；digest 对应条目同步更正。

总结论：pgAgentOS 的真实增量只有 1.5 项（persona version 快照、params JSONB 合并，加上 ForkPrefix 动机），其余是 v8 已有机制的重述。印证"按要素取舍、不整体引入"的既定立场——且取舍结果比 digest 建议更保守。

### 5.5 RLS 与 grant 衔接（F-03 清理）

agent_context 的租户 RLS 不能代替 slice-membership、参数级 capability 与当前 grant 有效性。F-03 核心规范**已在 v8-dev §2.1 正文**：slice 撤销、租户一致、membership 及授权线性化点一并继承，seal/dispatch 双实时门不能延期。v10 从 P0 起验证 catalog/Bind/发布入口的适用路径与数据库写权限；`recoverable` 仅指内容重建能力，不影响授权失败封闭。冻结输入只为重放计算，不缓存执行许可。

### 5.6 命名

`agent_context` 及对象名均暂定。命名核查输入清单为本文 §2.4/§3.2/§5.1，基线清单为 v1–v9 已加载 SQL/注册对象（含 `v8/schema/v8_schema.sql`、`v8/schema/v8_keys.sql` 与 `v9/ctx_schema/ctx_schema.sql` 等模块），并对照冻结 v8-dev 与 v9 spec 的规划对象。检查覆盖 schema、表/视图、带签名函数、类型、索引/约束及同表列名，记录文件/版本、核查域与冲突结果。

**当前证据仅是设计清单对照，不是全库自动验收**。v9 spec §8 只要求“命名已对照 v1–v7 检查无冲突”，不能推成“W1 已自动验收 v1–v9 无冲突”。完整导出/自动扫描报告是 v10-dev 定名与 P0 接入前的工件，本稿不声称已经通过。

## 6. 双运行时与行为合同：v10 增量

v8-dev §1.2 的 `normalize → observable_trace` 与不变量 14 不变。v10 **独立定义 assembly conformance**，不将原始 plan/trace 审计行直接作为 portable 对象：

1. **冻结输入 → canonical request + canonical decision trace**。输入覆盖 §2.2 既有 manifest 的扩展值：catalog/历史逻辑切点、persona/有效参数、latch/emergent、artifact 内容/依赖、冻结 stats 数值、tokenizer/计算规则版本、render/provider/canonical profile。历史 usage/latency 若被 stats 算法消费，须先固定成输入；测试时不得读取运行中漂移的桶。
2. **decision trace**只比较确定性选择（顺序、预算、tier、applied/skipped 原因、spill 降级、marker、prefix 共享决策）。输出不含本次实际 usage、latency、cache hit/miss、worker、时间戳、attempt、lease/fence、command/receipt ID、物理 plan/trace/inspection 行 ID；这些属于 observational/audit。session/step/effect 等执行实例 ID 与物理 seq/generation ID 不直接进入比较，按 portable 逻辑位置/内容与实现摘要映射；不能误删实际进入 provider 请求的内容字节。投影 schema/映射在 v10-dev 冻结。
3. **渲染 conformance**另比较完整渲染身份下的 IR/section canonical 字节（§4.3），跨 generation 相同身份可复用、不同身份不可假定相等。缓存命中与否不参与正确性比较。

§2.5 的 tie-break 逻辑 section/source identity（或规范键）属于冻结输入与 portable 映射，须在排序前确定；不能先用物理 ID 排序、再在输出投影删掉 ID 来假装确定性。相同逻辑输入在物理 ID、插入/查询顺序与 locale 扰动下仍须产出相同 section 顺序、canonical request 与 decision trace。

compat 经同一数据库计算/应用路径拿到冻结请求，禁止 host 拼 prompt 或私有渲染直送。prompt 来源门与 v8-dev §5.2 dispatch 门分别证明“用哪份字节”和“I/O 前已持久化派发”，互不替代。验收继承 capability 矩阵的 passed/failed/blocked 口径，数据库层对照不能冒充真实 compat loop 的 I/O 层通过。

## 7. 与 v8 的关系

### 7.1 不变量零修改声明

v8-dev §0 的 18 条不变量**逐条零修改**——编号与语义原样引用，不改写。v10 改动集中在不变量 9 的实现结构：

> 不变量 9（原文）：assemble、fold、catalog、grant 和 policy 都绑定明确的 snapshot、cutoff 或 generation。

v10 把 assemble 展开为五阶段后，每一阶段继承同一绑定（职责、manifest 与实时授权边界见 §2.2）。新增的两条候选（§2.9）是**叠加**，编号与冻结在 v10-dev。

### 7.2 清理项对账（以 871 行冻结 v8-dev 正文为准）

历史审查标签保留用于追踪，不再将旧问题摘要当当前规范缺口；本轮不修改冻结基线。

| 历史问题 | 当前冻结条款 | 剩余验收 | v10 触碰范围 |
|---|---|---|---|
| F-03：slice 撤销传播曾缺失 | v8-dev §2.1 已含级联失效/等效检查、租户一致、membership、锁/CAS、seal/dispatch 双门 | 新目录、Bind 与发布入口的授权/并发撤销负向验证 | §5.5；P0 即生效，P3 只汇总证据 |
| F-04：canonical 多实现/强制 vectors 曾不明 | v8-dev §1.3 已冻结唯一 JCS profile，§6 Conformance 10 已强制 vectors | 继承 canonical/normalize 验收，增加 assembly portable 投影与 render identity vectors | P0 起跑 canonical + fixture 1/8，P2 增 render，P3 汇总三层证据 |
| F-07：workspace_handle 图文曾需对齐 | v8-dev §2.2 已有权威完整迁移表与正文边协议 | 验证接入路径不退化 checkpoint/lost、保留交叉引用 | 首版不读 live workspace；复用制品不等于继承 handle；不改 v8 正文 |
| F-08：命令清单/receipt/引用集合对账 | v8-dev §3.1.2 是写命令 receipt 合同；§5.2 是 compat 能力与测试边界 | 第一步现在核 §3.2 入口/对象清单；第二步在 v10-dev 写命令定型后核 receipt/envelope/权限/拒绝与重放覆盖 | 只读格式化与 inspection 不增 receipt；内部应用随父命令；独立发布写命令需合同，effect kind 本身不是命令；P0 接入前收口，后续增量随阶段更新 |
| F-09：step code 命名层级注记 | v8-dev §3.2.1 已区分 step outcome_code 与 session failure_code | 验证 fixture 使用正确层级，文档保留出处 | P0 R11 回归，P3 汇总 |
| F-10：route 解析显式点名 | v8-dev §0 不变量 17 已点名 route，§2.1 有效 grant/参数再授权适用 | 新入口不得因名称不同漏授权 | P0 capability 清单，非后补安全 |
| R11：planned 无 effect 与规则 4 code 的旧判读 | v8-dev §3.1/§3.1.1/§3.1.2 已排除持久化 planned 无 LLM slot；§3.2.1 规则 4/5 闭合 | “不得重新引入”断言；混合 not_retry_eligible → FAILED_TERMINAL，全 budget-exhausted → FAILED_RETRY_BUDGET_EXHAUSTED | §3.3；P0 assemble/seal 与 PTL 边界回归 |

### 7.3 不变量 9 实现结构升级说明

v8 的 assemble 已有明确 manifest 绑定（v8-dev §3.3），不是只有“相信 seal”的黑盒。v10 增加阶段化计算核与可检查的决策投影，使既有绑定可以解释；不是重新发明快照合同，也不是新增授权豁免。

### 7.4 与 v9 context_early 的共存边界

对照冻结 `docs/plans/v9-context-early-spec-2026-09-15.md` §0/§3/§5/§8：两轨并行，吸收经验但不搬迁权威表。

| 维度 | v9 context_early | v10 |
|---|---|---|
| 基线 | v6 代码线，只读继承 v3–v6；独立 W1–W9 | 冻结 v8-dev 合同；可运行基线需经 §9 接入门验证 |
| 主对象 | context pack/slice、ctx 操作；任务锚点为 parked run | section catalog、assemble manifest、plan/trace；step 与 seal 同事务发布 |
| 核心职责 | 预建、标脏、增量刷新、新鲜度诊断 | 选择、绑定、优化、序列化、合格 Feedback |
| generation 域 | pack 构建/刷新代次，用于结果适用性 | plugin generation 绑定实现/合同；persona 内容版本另域，不能互换 |
| gate 语义 | ctx_gate 返回 fresh/sync_refresh/drift_delta 建议，不执行刷新 | 输入完整性/当前授权/seal/dispatch 各自检查；ctx_gate 不是现成 freshness barrier |
| 执行协议 | PGMQ ctx_heavy + Python worker + apply_queue_result/apply_ctx_result | v8 ledger/receipt/fence；首版准备仅预发布 artifact，不能借 parked run 无 step 模型接入 |

可吸收依赖 manifest、内容摘要/provenance、精确失效，以及“准备期间源变更、迟到产物、未受影响来源不变”的负向测试；inspection 展示 source_version/stale/drift/needs_preparation，但不自动刷新。**freshness 与 authorization 正交；新鲜度变化不改写已 seal 请求。**若明确决定消费 v9 pack，另加单向 adapter 与集成 gate，不默认进入 P0、不共享控制态；v10 不必等待 v9 全落地。命名证据范围见 §5.6。

## 8. Conformance 增量（新增 fixture）

1. **assembly 确定性回放**：完整冻结输入 → canonical request + decision trace（§6）；两运行时各跑计算核。改变 worker/attempt/物理行 ID、实际 cache/latency 不影响比较；改变冻结 stats/tokenizer/profile 必须作为不同输入。P0 同时验 prompt 来源门，真实 compat loop 子用例与数据库层分列。补同 scope、同优先级的多个 section：固定逻辑 section/source identity 与内容，扰动物理 ID、插入/无序查询返回顺序及 locale，两运行时的排序、canonical request 与 decision trace 仍一致（§2.5/§6）。
2. **inspection 零写集与缺输入**：不创建 step/effect、manifest/plan/trace 审计行、receipt、spill，不消费 emergent、不写 latch/stats、不改 session/lease；仅返回带 inspection 身份的值。缺 artifact 返回 incomplete/needs_preparation，禁止现场准备；验证本地读取与禁外部 I/O 边界。
3. **emergent TTL/去重/cap**：按 §2.4 仅下一合格新 decision step 的 execution assemble 消费：decision 产候选 → tools 全成功（`final_tools=true`）→ **同 turn 下一 decision** 的 Bind 消费一次；tools seal 不消费。inspection 与 assemble 回滚不消费、不推进/占住目标 occurrence；提交消费后已 seal effect retry 不重装配、不再次消费，冻结字节不丢。期间插入合法 observational 事件（如 `session/heartbeat`）改变物理 seq，但不改变消费资格或目标逻辑 occurrence。`decision_only=true` 关闭 turn 的候选不入待消费集合；cancel/session terminal 前已入队但无消费者的项逻辑失效、不转投。重复 Feedback 不重复入队；超 cap 决策留 trace，消费与 seal 原子提交，未选入候选不延至再下一 step。
4. **spill 冻结重放**：可重建源丢失后重建同字节；不可重建源受持久保留。optional 缺失只在新决策选降级并冻结；重放旧 manifest 不换 placeholder，已 seal payload 不变；授权失败不可 fail-open。
5. **latch/persona 与 generation 正交**：latch 与有效参数物化后源默认值变化不改冻结内容；新 step 用新 active generation、旧 step 保留旧代；换代后的渲染身份变化不得伪称 prefix 不变。P0 用固定 persona 输入，P1 补真实 persona_version 路径。
6. **poml 双运行时字节与隔离**：同完整渲染身份/冻结输入，两侧独立渲染产物一致；旧新代 alias 交错解析不能污染，compat 不旁路；依赖/实现变化及缺失 provenance 拒绝误复用。
7. **制品发布幂等（分组验收）**：完整身份同内容重复发布收敛；同身份异字节/错误 provenance 拒绝；不同 render profile/依赖摘要不误命中；跨 generation 相同身份复用仍需当前授权。不是未定义的 preparation effect 重试测试。
   - **7-P0 基础组**：同 `(workspace_id, publication_id)` 同内容重放返回原 identity、异内容稳定冲突；授权前置与跨 workspace 隔离；发布与独立 receipt 原子性（故障不能半发布）；响应丢失后重发仍唯一发布。P0 最小 artifact 即验，不等待 poml。
   - **7-P2 渲染扩展组**：render profile、依赖闭包、alias/readiness 校验；同渲染身份异产物冲突（包括使用不同 publication ID 试图绕过冲突）；不同渲染身份不误复用，跨代相同身份仍经当前授权。与 fixture 6 合验。
8. **SectionKind × budget 全覆盖**：P0 计算核可执行即枚举全部闭合集，未知/未覆盖 kind 即红；source adapter 暂未接入不免除预算规则覆盖。后续新增 kind 随阶段扩 vectors。
9. **Feedback 分流/去重**：普通合格 LLM 成功终局恰一次样本/EMA，emergent 可投递性另按 §2.2/§2.4；失败、unknown、observation、拒绝、receipt replay、不同 command_id 重复 completion、旧 attempt、repair/reconcile 成功、终态 drain、非 LLM tool effect 均不产生这些更新。observation 对照断言其 v8 受限写集不扩大；重试最终成功只对被接受 attempt 采一次，发布 token metadata 不混入 usage。补两支对照：decision→tools→同 turn 下一 decision 可投递；合格 `decision_only=true` 关闭 decision 仍计一次统计，但候选当次丢弃、没有消费者。配合 fixture 3 验 retry/inspection/assemble 回滚不再次或提前消费；插入 observation 不入样本、不产 emergent、不改变逻辑消费资格，禁止以物理 seq 跳变判过期。

补充验收组（不冒充既有编号）：**A** manifest/授权并发撤销、初始 seal 原子性及 R11；**B** 预发布必需输入缺失/迟到/源变化、seal 前预算升级、provider PTL 失败与 unknown 不重装；**C** ForkPrefix 内容复用与 wire 共享分离（不 delegable、权限收窄、persona/provider/render profile 不兼容、父切点后变化）；**D** compat prompt/dispatch 双门与 generation/alias 隔离。A/B/D 基础在 P0，C 与 persona 扩展在 P1，D 渲染扩展在 P2。B 另验 `needs_preparation`：可恢复不足不自动 INFRA、不建 step/effect、不消费 emergent、不新增等待态；已 claim 拒绝保持 session/lease/fence、coordinator 独立显式 yield；同 command ID 在补齐前后均只返原 receipt，新命令身份经当前授权/claim 才可重装配；缺项由调用方补齐，inspection 仍无 receipt/lease 写入。完整输入输出、crash/atomicity vectors 与 capability 分派表由 v10-dev 定稿，raw 不复制状态表。

## 9. 路线图

### 9.1 准出顺序与实现依赖

**依赖主线**：冻结 v8 对账 + 入口/对象清单 + 本稿边界裁定 → raw 复审 → v10-dev → 已验证 v8 runtime 接入门 → P0 → P1 → P2 → P3。raw 复审前可做协议草案、目录骨架与 spike，不得将未审结论写成正式实现规范。

**raw → v10-dev 准出门**：父控制器按第三轮同等四镜头复审（轮 2/3 全 P1 逐条核验、871 行冻结 v8-dev 对账、v9 共存、路线图完备性），达到 **0 P0 / 0 P1** 才正式进入 v10-dev。本稿修订不是已通过复审；preparation/PTL 已选首版收窄方向，Feedback 入口分流、manifest/授权、generation/render identity、spill/prefix/比较面须正文与 fixtures/路线图一致；剩余 P2 有阶段与验收工件。

**v8 规格冻结不等于 runtime 就绪**。正式 P0 接入前必须选定并记录 v8 实现 commit、数据库/schema 与 adapter 版本、已通过的合同集：最小 Native seal/首 attempt/completion 闭环、权限/receipt、unknown/repair/reconcile、generation、canonicalizer 及 compat capability 报告（v8-dev §6 P0B/P0C 与 §5.2）。若这些未就绪，其建设与验证是独立前置依赖；不得把当前 schema 或 v6/v9 运行结果当 v8 闭环。固定输入 adapter 可以先验证纯计算，不能据此宣称完整 P0 接入已通过。本轮不建设或修改 v8 runtime。

F-08 **两步**：raw 阶段已有 §3.2 三类入口/对象清单；v10-dev 定型写命令、内部子操作与只读入口后，P0 接入前逐项核 receipt、权限、envelope、拒绝/重放覆盖；后续阶段有新增再增量核对，不等 P3 才第一次审。

### 9.2 P0–P3 交付与验收

| 阶段 | 前置合同 | 实现依赖 | 阶段交付 | 验收工件 |
|---|---|---|---|---|
| **P0：最小源集的端到端管道，不接 poml** | §2.2 三职责/双模式/manifest + F-03 当前授权 + 唯一 canonical profile；首版 preparation/PTL 限界 | v10-dev 与 v8 接入门；固定输入 adapter → 静态 Identity/Constraints、cutoff History、ToolSchemas、预发布 artifact 最小源集；stats/fold/payload 各 spike 在相关方案冻结前 | 基础表与受控写入口、完整预算计算核、execution/inspection、Serialize→初始 decision seal、合格 Feedback；compat prompt 门从本阶段接入，不延到 P2 | fixture **1/2/5/9 + 首版 8 + 7-P0 基础发布组**；9 区分采样与可投递性；A/B/D 基础；canonical/assembly vectors；R11 两条回归；F-03 seal/dispatch 撤销负向；数据库层与真实 compat loop 的 passed/failed/blocked 报告 |
| **P1：persona / emergent / spill / ForkPrefix** | session 内容冻结与逐 step generation；冻结 spill/prefix 授权合同 | P0；spill 保留/同字节重建策略，发布 provenance | persona_version 与参数物化；emergent TTL/cap/消费（下一合格 decision step 装配，非下一 turn）；spill；Serialize wire prefix 资格校验与观测 | fixture **3/4**、5 的真实 persona 扩展、C 负向组；保留/丢失重放报告；缓存命中不充当通过条件 |
| **P2：poml 预构建制品与标签初集** | render identity/依赖闭包、两条硬规则；仍不增加自动 preparation 协议 | P0/P1 发布与消费链；POML resolver 隔离验证通过，native/compat harness | 四标签预构建、IR/section 发布与缓存、poml_components/readiness/provenance；不交付自动 render effect 调度 | fixture **6/7-P2 渲染扩展组**（保留 7-P0 回归）、D 渲染隔离扩展、迟到/源变化/未受影响来源对照；render vectors、发布幂等与权限报告 |
| **P3：汇总与准出** | 早期安全/canonical 合同已生效，不作首次补课 | P0–P2 工件齐备 | F/R11 对账汇总、F-08 增量复核、F-04 三层 vectors（canonical、normalize、assembly；含渲染子集） | 全 fixture 回归与 capability 报告、P2/spike 去向、命名核查报告；不得用 P3 汇总替代 P0 验收 |

P0 最小 source 集是接入范围，不是忽略其余 kind 的许可；fixture 8 在计算核可执行即跑，未接 source 的 kind 用固定输入 vectors 覆盖。DDL/FK/索引/RLS、函数签名/volatility、manifest/trace portable schema、发布 receipt/crash 边界、spill 清理与 worker readiness 细节留 v10-dev；不能借“下放”重新打开 raw 已裁定的范围。

### 9.3 并行 spike、协议验证与延期项

- **R2-P2-1 stats 并发 spike**：在 stats 实现冻结前测多 session 同桶锁竞争、digest 插入/驱逐、EMA 丢更新与重复抑制；产吞吐/延迟与一致性报告，再选 SQL 内维护或带版本校验的 worker 计算方案，不能仅把结果覆盖回表。
- **R2-P2-2 fold spike**：在 projection 方案冻结前测冷启动全历史与增量重建、cutoff 一致性和失效成本；产长会话基准与取舍记录。
- **R2-P2-3 大 payload spike**：在 ledger 存储接入前测 TOAST/不可变 payload/派生执行快照的写放大、WAL、读取与重放成本；不预判拆 heartbeat 必然解决 TOAST，产存储方案与预算报告。
- **preparation/PTL 两项协议探索**：raw 已分别裁定“只消费预发布完成 artifact”和“仅 seal 前升级”；v10-dev 记录延期与负向验收 B，不能以探索名义暗中添加新工作。若未来启用自动准备或跨调用恢复，先重新评审 step/seal/取消/unknown/switch/generation drain 与终态合同影响，不阻塞本次收窄版。
- **POML 隔离小验证**：在 P2 实现选型前，以新旧 generation 同名标签/alias 交错、共享实现、compat 内联场景验证 §4.4 结果义务；输出选择记录与失败用例。未通过则该支持面不发布，不能以 key 前缀代替证明。
- **churn/alert（轮 1 P2-3）**：留 v10-dev 显式采纳/延期，输出计数器/告警规则的决定与验收工件；首版不默认引入。v9 pack adapter 仅在另行决定消费时立项，不是等待 v9 W1–W9 的默认依赖。

## 10. 明确不做

- **不 fork poml，不改 writer.ts。** DB 标签只产内置 IR 节点（硬规则 1）。
- **不做 PG 系统视图伪装。** 目录是普通表 + 稳定视图（§1.2）。
- **Bind 不做外部 I/O。** 首版仅消费 DB-local 授权值及预发布完整 artifact；不偷渡 preparation batch/slot 或自动跨调用 PTL 恢复（§2.2/§2.5）。
- **不引入 pgAgentOS 的 RAG 套件、http-skill、run DAG。** 取舍按要素、不按整体（§5.4）。
- **不让 poml 属性决定 cache scope。** CacheScope 的决定权在 catalog 行（§4.2）。
- **不在 v10 动 18 条不变量。** 新增只走候选清单（§2.9），v10-dev 审定。
- **不引入第二套执行真相。** 没有 PipelineSession 进程内态、没有 parent_run DAG、没有非原子 turn 创建。

## 11. 对外表述

- ContextPipe 从数据库借来的四件套——catalog、optimizer、statistics、EXPLAIN——回到数据库，成为表与函数。
- poml 是 section 的声明语言，不是 prompt 的私有格式；线格式只有一个权威，就是 pipeline Serialize。
- 一份行为合同、两份运行时，v10 之后依然成立：五阶段是数据库内结构，native 与 compat 走同一套函数；prompt 字节由表决定，不由 host 决定。
- v10 不是新运行时，是 v8 assemble 步骤的显式化；18 条不变量一条没动，新增的两条候选正在路上。
