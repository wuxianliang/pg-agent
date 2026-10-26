# Cordis v2 DP2：安装与成功激活生命周期 Deep Plan

状态：**B0 已结项；W1 已结项（commit `50affb0`，已推送 `origin/v24`）；W2 已结项（commit `1a7deaa`，已推送 `origin/v24`）；W3 已结项（commit `cd93134`，已推送 `origin/v24`）；W4 已结项（commit `d5fd1bc`，已推送 `origin/v24`）；W5 closeout 已于 `d5fd1bc` 之上串行重跑全部当前门禁，全部 `EXIT 0`，按授权收尾 commit/push。** B0 于 2026-10-26 在指定 worktree 实跑既有五条 Cordis DP1 命令、十一条 v24 命令与单列 s9（全部退出码 0），复核十二个冻结 SQL SHA-256 与 `57e2c1e` 冻结 diff（逐一相同 / diff 为空）。W1 的测试命令、真实结果与边界见 §6「W1 证据」；W2 的 layout 裁决、实现、19 条 post-fix 实测结果与 bounded review 修复见 §6「W2 证据」。W3–W5 的测试命令仍是未来验收要求，不得从 B0/W1/W2 绿色推断其行为。

## 1. Summary

DP2 定向扩展已完成的 Cordis 内核，交付声明式安装、scope 创建后果、最小依赖解析、成功的 P0–P4 激活和无活义务的基本 dispose。继续使用现有 `advance(uuid,jsonb)`、十张表、G 锁、请求/receipt 重放及调用方 COMMIT 合同；通过私有解释器、封闭类型的 delta 和实际领域应用器填补 DP1 接缝。最关键的协议扩展是允许已登记的 ready reconcile 后继被执行，而不是被现有身份冲突检查拒绝。所有失败、漂移和需要清理的路径保留 `0A000`，只回滚当前调用，不提前实现 DP3。

### Goal

实现以下生产路径，并用独立 `CDP2-*` gate 验收：

1. `command_install`：声明校验 → scope 创建或复用 → install/fiber 创建。
2. `command_reconcile`：P0 目标请求 → P1 begin → 每批至多 32 条贡献的 P2 → 阶段边界 P3 一致性检查 → P4 finish。
3. `command_dispose`：证明全部活义务不存在后，写 fiber/install 墓碑。
4. 每个成功调用原子提交领域变更、effect receipt、request 首次 response、事件和后继。
5. 每个拒绝或异常均有精确错误证据及十表零写证明。

不将上述结果称为完整 G1–G4、完整生命周期、Confluence、卸载、恢复或事件精化通过。

## 2. Current-state analysis

### Background：权威、基线与复用范围

唯一产品规格为 `docs/designs/cordis-plugin-system-2026-10-25.md`。DP1 计划中的阶段边界和已裁决的 ABI、锁序、角色模型继续有效。DP1 matrix/ledger 中的退出码属于历史证据；DP2 必须重新运行并记录当前结果。

实施前核对指定 worktree、`v24` 分支、当前 HEAD、用户文件和 `origin/v24` 跟踪关系。本次只读核验时 HEAD 为 `0590d47`：DP1 提交依次为 `5163b23`（loader/fixture）、`e9ccf30`（DDL）、`69efd38`（kernel/ACL）、`0590d47`（closeout）。它们证明 DP1 已交付，不能替代 DP2 的本轮回归。`57e2c1e` 是冻结 v24 的比较基线，**不是 DP2 预期 HEAD**。不修改主 checkout，不覆盖既有未跟踪文档。

直接复用：

- `load.py` 的十六文件 canonical manifest 和调用方事务。
- `principal_id`、`effect_id_for`、canonical bytes、24 个错误码及角色族认证。
- `advance` 的纯参数预检、G、replay-first、claim 和 terminal receipt 顺序。
- typed closure、512 个目标上限和现有行锁全序。
- `events` 的事务内 entity `max(seq)+1` 分配。
- DP1 `Server`、`TestDB`、十表 `snapshot()` 和跨连接持久化证明模式。

阶段依据可直接核对：DP1 将 install、scope、成功 P0–P4 与无活义务基本 dispose 划给 DP2，并把 drift/failure/leave/unload/inverse/barrier 留给后续阶段（`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:206-219`）。DP1 的 README 记录五条 Cordis gate、11 条 v24 closeout 命令、单列 s9 及所有 interpreter 仍为 `0A000`（`v24/cordis/dp1/README.md:5-17`）；矩阵记录 2026-10-26 closeout 和冻结证据（`docs/reviews/cordis-v2-dp1-conformance-matrix-2026-10-25.md:80-99`），台账保留 final W4 证据（`docs/reviews/cordis-v2-dp1-deviation-ledger-2026-10-25.md:27-31`）。DP1 夹具可复用的具体模式是 `test_kernel.py` 导入 `Server`、`TestDB` 与 `test_ddl.snapshot`（`v24/cordis/dp1/test_kernel.py:16-17`）；snapshot 覆盖 `TABLES` 全集（`v24/cordis/dp1/test_ddl.py:29-35`）。DP2 helper 应调用这些 fixture API 并维持各 gate 自己的数据库生命周期，不复制 fixture 实现，也不把 `v24` 的产品 fixture 当作 Cordis 入口。

`v24/sql/45_capability.sql` 的 resolver/check 和 `40_interpreters.sql` 的激活逻辑仅作行为先例。Cordis 使用自己的字段、解释器和数据合同，不调用或修改冻结的 v24 函数。

### 现有职责、关系和写入点

现有调用链为：

```text
调用方构造 outcome
  → advance：preflight → G → session_user 认证
  → request/effect replay target 加锁与重放
  → discover_closure → lock_closure → 再发现复验
  → interpret_command / interpret_settlement
  → validate_and_apply_delta
  → 调用方 COMMIT
```

当前接缝可定位到 `v24/cordis/sql/40_advance.sql:150-203`（解释器 stub 与 delta validator）、`:204-228`（receipt/request/event applier）和 `:279-340`（command replay、空 closure seed、claim 与解释器 dispatch）。terminal guard 的现有缺口在 `v24/cordis/sql/30_triggers.sql:58-68`：它保护 identity/input 与计数单调，但未冻结 terminal outcome/status；必须随 W1 writer 一起补齐。

| 组件 | 当前行为 | DP2 必须补齐 |
|---|---|---|
| command closure | `seed=[]` | 从已有目标、路由、owner、provider 和义务生成闭包 |
| `interpret_command` | `0A000` | install、reconcile 成功路径和基本 dispose |
| `validate_delta` | 非空 domain/successors 被拒 | 封闭类型、分支写集、ownership、DAG、批量检查 |
| applier | 只写 receipt/request/event | 实际领域写入及 ready 后继 |
| successor kind | 不含 `command_reconcile` | 增加该内部后继种类 |
| successor identity | 未定义、未插入 | 保持 `effect_id_for` ABI 的确定性身份 |
| command effect | 不绑定 fiber/episode | 根据已验证命令上下文绑定 |
| existing command effect | 一律 `effect_id_conflict` | 仅接纳严格匹配的 ready reconcile 后继 |
| response | `emitted=[]` | 返回本次新建后继 effect ID |
| events | 每个 delta 最多一条 | 每个状态变化阶段一条聚合事件；保留单 entity 游标分配，多实体 stream 覆盖留给 DP5 |
| episode guard | 未冻结 `committed_view` | 补不可变保护 |
| settlement/barrier | `0A000` / `true` | 保留现状，不扩展业务语义 |

数据关系必须保持：

- `fibers.current_episode_id` 指向同 fiber 的 open episode。
- install/fiber owner 引用历史 `(fiber_id, episode_id)`，不追随 current 指针。
- contribution 属于一个固定 episode，`seq` 在该 episode 内递增。
- activation pin 冻结 contribution 和 `provider_epoch`，不改绑。
- `episodes_one_open`、service 地址和 reconcile 槽位都是立即检查的 partial unique index。

因此，不能在旧 reconcile 仍 ready 时插入下一条同 fiber reconcile；必须先结算当前 effect，再插后继。延迟 FK 不会延迟这些唯一性检查。

### 变更策略

采用定向扩展，不重构冻结 v24，也不新建 scheduler、通用 SQL executor 或第二种生命周期账本。DP1 的协议路径已经有实跑证据；本阶段只扩展它缺少的领域上下文、解释器和应用能力。

W2 的 SQL layout 由用户 2026-10-26 裁决：新增 `v24/cordis/sql/41_lifecycle.sql`，置于 `40_advance.sql` 与 `50_permissions.sql` 之间，canonical manifest 由十五文件增至十六文件。`40_advance.sql` 仍 ≤1200 物理行，DDL 前缀 `10`–`17`/`20`/`30` 仍 ≤900 物理行；十五张表、列、枚举与扩展均不变。W2 的 install/admission/resolver/check helper 全部落在 41，`40_advance.sql` 只保留必要的命令入口接缝；不把 helper 移出预算或把代码藏进 JSON。

## 3. Design

### 3.1 执行索引

`B0` 是实现前基线里程碑；它与设计定义的激活阶段 `P0` 无关。`B0` 的全部既有 gate 实跑并更新 stage README、matrix、ledger 后，必须作为独立里程碑提交并推送，不能与 W1 合并。后续 W1–W5 同样各自独立收尾。

| 工项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| B0 | 固定当前基线 | 五条 DP1、十一条 v24 及单列 s9 命令有本轮结果，冻结 diff/hash 一致，README/matrix/ledger 已更新，并已按用户授权独立提交推送到 `origin/v24`，B0 结项 | DP2 README、matrix、ledger、plan | — | S：证据与环境核验 |
| W1 | 后继执行与 typed delta 基础 | ready child 可执行并持久重放，terminal receipt 不可重开，伪造/越界/故障零写 | `40_advance.sql`、`30_triggers.sql`、DP1/DP2 kernel gates | B0 | L：内核协议与应用器 |
| W2 | 安装与 scope 后果 | 三种 scope、声明、owner 账本、resolve、committed-view/root/DAG 保护与维护 fixture 通过 | `40_advance.sql`、`41_lifecycle.sql`、`30_triggers.sql`、install/DDL gates | W1 | L：准入与解析 |
| W3 | 成功 P0–P4 | 真实命令完成零贡献、单批、多批激活，ω/pin/seq/totality 与精确事件通过 | `40_advance.sql`、activation gate | W2 | L：分阶段生命周期 |
| W4 | 基本 dispose 与失败边界 | 全实例无义务墓碑化成功，各活义务和六种 host 状态阻止，DP3 seam 回滚 | `40_advance.sql`、boundary gate | W3 | M：证明与边界 |
| W5 | closeout | 全部当前 gate、冻结检查、预算与工件通过，未覆盖范围明确 | README、matrix、ledger、plan | W1–W4 | S：回归与收尾 |

W1–W4 串行修改 SQL。每个里程碑均以当前可运行的全部 gate 为结项条件。

### 3.2 定位、边界与发布合同

DP2 交付的内部合同如下：

| 合同 | 内容 |
|---|---|
| C2-Command | 三种 lifecycle command 的精确 payload |
| C2-Continuation | ready reconcile 身份、执行和 receipt 规则 |
| C2-Resolve | scope 路由、可用 provider 及数据 check |
| C2-Episode | immutable ω、iterator、批次和 epoch |
| C2-Delta | 分支专属的 typed mutation 和写入顺序 |
| C2-Dispose | 无活义务证明及墓碑 |
| C2-Boundary | unsupported 路径 `0A000`，当前调用零提交 |

以下明确不进入 DP2：

- target drift 的处理、失败记录、自动 retry。
- closing/divert/error、leave/unload、withdraw/release、inverse 执行。
- 完整 live 失效传播、drain/barrier、公平扫描和恢复。
- run、reducer、model/tool、dispatch/listener 的执行。
- `intercept`、overlay 合并和外部制品准备。

`barrier_ready()` 保留 `true` 接缝；DP2 生命周期不调用它来表示等待。`interpret_settlement()` 保留 `0A000`。生命周期成功 response 继续 `revision=0`，不赋予 freshness 含义。

### 3.3 设计 § → 工项 → gate 映射

| 产品规格 | DP2 落点 | 工项 | 本地 gate |
|---|---|---|---|
| §3.1–§3.2 | ABI、replay-first、原子 receipt/后继 | W1 | CDP2-K |
| §3.3 | 三生命周期分支；settlement 仍未实现 | W2–W4 | CDP2-I/A/B |
| §3.4 | typed 写集、owner、confinement、联合 DAG | W1–W3 | CDP2-K/A |
| §4.2–§4.3 | 历史 owner、current、epoch、唯一性 | W2–W3 | CDP2-I/A |
| §5.1 O-Insert | 安装及 fiber 创建 | W2 | CDP2-I |
| §5.2 P0–P4 | 有界成功激活 | W3 | CDP2-A |
| §6.1 | 记录 service/child inverse；不执行 | W2–W3 | CDP2-I/A |
| §6.3 | requires→冻结 activation pin | W3 | CDP2-A |
| §7.1、§7.4、§7.6 | 局部 totality、ω 不变和准入证据 | W3 | CDP2-A/B |
| §10.1 | 表数、文件数、行预算、B/批量 | 每项 | 全部 |
| O-Remove / DP1 基本 dispose 边界 | 无义务墓碑 | W4 | CDP2-B |

这里的映射只验证相应机制，不证明 §7 的完整命题。

### 3.4 SQL / 接口草案：共同约定

#### 接口与执行上下文

保留以下签名：

```text
advance(uuid, jsonb) → jsonb
interpret_command(uuid, uuid, jsonb, jsonb) → jsonb
interpret_settlement(uuid, uuid, jsonb, jsonb) → jsonb
validate_delta(jsonb, text, boolean default false) → jsonb
validate_and_apply_delta(uuid, uuid, jsonb, jsonb, jsonb) → jsonb
```

解释器返回成功 delta，或现有 `error_v1` 封套；后者由 `advance` 直接返回，不能进入 applier。unsupported 路径抛 `0A000`。

新增私有函数的职责及形状：

| 函数 | 输入 → 输出 | 性质 |
|---|---|---|
| `command_seed(kind,payload)` | 命令 → typed seed / 错误封套 | 只读；不取行锁 |
| `command_closure(kind,payload)` | 命令 → 有界完整目标集 / NULL | 只读；复用 discovery |
| `check_policy_valid(policy)` | JSON → boolean | IMMUTABLE |
| `check_policy_ok(policy,descriptor)` | JSON、JSON → boolean | IMMUTABLE |
| `resolve(scope_id,keys)` | scope、text[] → 解析行集 | STABLE、只读、私有 |
| `validate_domain(effect,principal,outcome,delta,closure)` | 完整上下文 → NULL / 错误封套 | 无 DML |
| `successor_request_key(parent,ordinal)` | UUID、整数 → text | IMMUTABLE |
| 三个私有 lifecycle interpreter | 与现有 command seam 相同参数 → delta / 错误 | 无 DML |

所有 helper 为 `SECURITY INVOKER`，固定 `search_path=pg_catalog,v24_cordis,pg_temp`，不授予协议角色 EXECUTE。只有 `advance` 是 DEFINER writer。

#### 字段边界

除现有 body ≤1 MiB、深度 ≤32、递归对象键 ≤200 外：

- UUID 必须为非 null UUID 字符串；先验证再 cast。
- key、realm、identity、version、contract version、capability 名称长度为 1–128。
- digest 为小写 SHA-256 hex64。
- 整数先验证 JSON 类型、整数形式和范围，再 cast。
- 未列出的 payload 字段一律 `invalid_args`。
- `requires`、`provides` 各至多 256 项，并分别禁止重复 key。
- 总 body 限制继续生效，不因这些局部上限放宽。

生命周期专属 payload 校验发生在 request replay 未命中后、closure 首次加锁前。有效旧 request 仍先返回首次 response，不重新解释 payload。

### 3.5 后继：保持 ABI 的登记、执行与重放

#### 身份与输入

DP2 successor 保持现有三字段结构：

```text
{ ordinal, kind, input }
```

增加可执行的 `kind='command_reconcile'`；DP2 每次最多生成一条，固定 `ordinal=0`。全局 B=16 保持，其他业务 kind 仅保留结构合同，DP2 生命周期无权生成。

内部 request key 固定为：

```text
cordis/reconcile/<parent-effect-uuid>/<ordinal>
```

child effect ID 通过现有算法计算：

```text
effect_id_for(parent principal, reserved request key, 'command_reconcile')
```

不直接采用 v24 的 `md5(parent:kind:ordinal)`：那会与当前 command 的 `effect_id_for` 校验冲突。Oracle-adjudicated 2026-10-26：采用 reserved request key + 现有 `effect_id_for`，并且只在 continuation 首次执行时写 request receipt；这样保留现有 command 身份和首次 response replay 语义。

`input` 是完整 reconcile payload：

```text
{ fiber_id, action:"advance", expected_control_seq }
```

不保存 phase 名；phase 从 DB 事实推导。

ready child 同时冻结：

- `parent_id`、`ordinal`、`fiber_id`。
- 创建时已存在的 `episode_id`，begin 前为 NULL。
- `request_actor=parent.request_actor`。
- `status=ready`，attempt/fence 为 0，无 outcome/settled_at。

#### 不能提前写 child 的 requests

生成 ready child 时只插 `effects`，**不插 `requests`**。`requests` 表保存已执行命令的首次 response；提前写入会使 replay-first 跳过尚未执行的 phase。

因此，DP2 必须扩展 existing-effect 分支，而不是用占位 request 绕开现有冲突检查。

#### 执行已有 ready child

调用方使用 child 的确定性 ID、保留 request key、冻结 payload 和现有 `admit_and_apply` 信封提交。

request replay 未命中后，`advance` 允许 existing effect 继续执行，条件必须同时成立：

1. kind 为 `command_reconcile`，status 为 `ready`。
2. parent/ordinal 完整，ordinal 为 0，parent 已 succeeded。
3. request key、派生 effect ID、stored input 完全匹配。
4. `request_actor=session_user`，parent 与 child 的 actor 一致。
5. fiber/episode 绑定与生成时上下文一致。
6. 该 child 没有已存在的 request receipt。

否则 `effect_id_conflict`，零写；不得重新创建或覆盖 existing effect。

DP2 continuation 由创建它的同一 LOGIN 执行。这保留当前 principal ABI；跨 LOGIN 的维护执行权不是本阶段隐含增加的权限。

已有 child 是 replay target：在其余 closure pass 前锁定。执行成功后更新这条 effect 为 succeeded，并首次插入它的 request。之后重复提交原命令原样返回该 request response。

continuation 的失败与重试合同必须显式固定：

| 情形 | 结果 | 写入 |
|---|---|---|
| `action=advance` 的 payload 缺键、未知键、ID/整数类型非法 | `invalid_args` | 零写 |
| effect ID 不存在或对当前 role 不可见 | `not_found_or_denied` | 零写 |
| effect 存在但 kind/status 不是 `command_reconcile`/`ready`，或 parent/ordinal、reserved key、派生 ID、stored input、fiber/episode binding、parent actor 不匹配 | `effect_id_conflict` | 零写 |
| child 的 `request_actor` 与 `session_user` 不同 | `effect_id_conflict`；同 role family 也不例外 | 零写 |
| child input 的 `expected_control_seq` 与当前 fiber.control_seq 不同，或 want_on/current episode 前提不再成立 | P1 开始前 `stale_generation`；已有 episode 的 P2/P4 属阶段边界 drift，抛 `0A000` | 零写；SQL 异常须 rollback |
| P1/P2/P4 的依赖、check、provider、注册或阶段边界不满足 | `0A000` | 当前事务回滚；child 仍为 `ready`，不生成 request/event/successor |

`expected_control_seq` 在 P1 解析、建 episode 或任何领域 DML **之前**重新读取并比较；P3 的 provider/target 漂移仍使用 `0A000`，不把已入场后的绑定变化伪装成 generation mismatch。对失败的 ready child，调用方修复依赖后可重新提交同一 child ID、同一 reserved request key 和同一 frozen input；首次成功只写一条 request、一条阶段事件和下一条 successor，重试不会重复 contribution、event 或 successor。若 originating LOGIN 永久不可用，child 在本 DP2 合同下保持 ready/blocked，不能用新 LOGIN、`on` no-op、`off` 或自动 retry 替换它；handoff 属后续阶段。

`action=advance` 与 reserved request key 必须成对出现；任何新外部 command 不得借用 `cordis/reconcile/` 前缀发 `on/install/dispose`。请求 replay 命中仍先按首次 response 返回；未命中且保留 key/动作组合不合法时返回 `invalid_args`，正确组合但 child 不存在时 `not_found_or_denied`，已有 child 身份内容不符时 `effect_id_conflict`。不为该拒绝插 effect/request。

#### 当前 effect 与下一条后继

应用顺序必须使当前 reconcile 先离开 ready，再插下一条 ready reconcile，以满足 I7。response 的 `emitted` 是本次实际新建 child ID，按 ordinal 排序；finish/no-op 为 `[]`。

P1 effect 创建时 episode 尚不存在，其 `episode_id=NULL` 保持不可变；P1 生成的下一条 child 才绑定新 episode。不能回填已有 effect 的 immutable episode 字段。command_dispose 是 install-scoped：其 command effect 的 `fiber_id`、`episode_id`、`run_id` 均固定为 SQL NULL，授权来自 payload 的 `install_id`、closure 中的全部实例集合和 install-wide proof；applier 必须独立重算并逐项比对 `fiber_ids`，不能把单个 effect fiber 当作批量 tombstone 权限。

### 3.6 安装声明、scope 与 ownership

#### `command_install` payload

精确顶层字段：

```text
install_id, fiber_id, scope, owner,
identity, version, manifest, artifact_digest,
contracts, policy_ref, overlay
```

ID 由调用方预选，因此不扩展 response ABI，也不需要通过公开 SELECT 取得安装结果。

`scope` 是以下三种闭集变体：

| mode | 精确字段 | 行为 |
|---|---|---|
| `existing` | `mode,id` | 使用已有开放 scope |
| `root` | `mode,id,realm_overrides` | 创建 `parent_id=NULL` scope |
| `child` | `mode,id,parent_id,realm_overrides` | 在开放 parent 下创建 scope |

新 scope 的 `intercept={}`、`closed_at=NULL`。任何祖先 `closed_at` 非 null 均阻止新准入。

`owner` 为 JSON null，或精确 `{fiber_id,episode_id}`：

- owner 为 null 仅用于创建设计规定的唯一 bootstrap root fiber；数据库已有 ownerless fiber 时拒绝。Oracle-adjudicated 2026-10-26：采用唯一 root，依据设计 §4.2 的 root owner 关系与 §7.1 的唯一 root 约束，避免形成多个无主资源树。
- 非空 owner 必须指向该 owner 的 current、open、active episode；owner 及其祖先均未请求 dispose、未 disposed、未 retire。
- scope 路由与 owner 资源归属独立，不要求同一个 scope。
- install owner pair 与新 fiber owner pair 必须相同。

唯一 root 既是 admission 规则也是数据库最终状态不变量：`30_triggers.sql` 在 deferred final-state guard 中拒绝第二个 `fibers.owner_id IS NULL` 的行；已 disposed 的历史 root 仍占用该 root 槽，因为 DP2 保留身份历史且 dispose 不删除 fiber。普通 command 在首次 DML 前返回 `invalid_args`，owner DML 负例在 COMMIT 时以 SQLSTATE `23514` 回滚；两条路径都要证明十表快照不变。该 guard 读取事务最终存活行，不以中间 NEW 值计数；生产路径已持 G，维护 fixture 的写事务也须在任何领域 DML 前先取 G，使 final-state 检查复用既有事务锁，不引入行锁之后再取 G 的反向锁序。

root 安装允许 root/existing scope；child 安装允许 existing/child scope。其他组合 `invalid_args`。

#### manifest 的 DP2 数据合同

精确字段为：

```text
requires, provides, priority, check
```

- `requires`：唯一 key 字符串数组，声明顺序保留。
- `provides`：唯一 key 的 service 声明数组；每项精确为 `{key,descriptor,contract_version}`。
- `priority`：32 位有符号整数。严格数值顺序本身无环；相同值不产生优先关系。
- `check`：require key → check policy 的 object；只允许引用 `requires` 中的 key，缺项表示无额外 check。

DP2 只从 `provides` 注册 service。listener/cell/reservation 的安装执行不在本阶段。child contribution 由 ownerful install 的资源创建产生，见下文。

每个 service descriptor 是 object，必须含非空 `capability`，指向本 install 的 `contracts` 成员；其他字段是不可变数据。`contract_version` 必须与对应合同一致。

`contracts` 是 capability 名 → 合同的 object。每个被使用合同精确包含：

```text
contract_version, handler_digest,
replay:{repeat:boolean, concurrent:boolean}
```

DP2 冻结每个 capability 的 handler digest、版本和显式 replay 权利，接受四种 `replay.repeat`/`replay.concurrent` 组合；不从 descriptor、read-only 标志或幂等 key 推断“外部写”。DP2 没有外部写 classifier、handler 执行或 host-effect producer，因此所有 `provides` 都是 service-registration 与 dependency-check 声明，不能在本阶段请求外部资源。若出现 `contracts.host_io`，仍按 DP1 的精确合同形状校验和保存，但它不创建 `host_io` effect，也不授权 DP2 新的执行路径；DP1 的 host claim 仍只校验 `installs.contracts.host_io` 与 frozen `effects.input.contract` 的匹配，首次 claim 与过期 reclaim 的 replay-right 规则不变。所有能力都只做声明准入；不加载 adapter、不执行 handler。

首次 claim 的 frozen `effects.input.contract` 精确为 `{contract_version,handler_digest}`，两值必须与 `installs.contracts.host_io` 一致；失配沿用 `invalid_args`。过期 reclaim 还要求 `replay.repeat=true` 且 `replay.concurrent=true`，缺失/false/失配沿用 `blocked_unknown`。这些既有 seeded DP1 claim 用例继续实跑；DP2 不创造 host effect 或 host binding。

`policy_ref` 只接受 null 或 `chat_tool`，作为后续阶段的数据引用。`overlay` 必须为 `{}`；非空 overlay 以及使用 interception 的安装执行抛 `0A000`，不悄悄忽略配置。

#### O-Insert 与 child 资源账本

无外部准备的 install 直接创建：

- `installs.state='installed'`。
- fiber `want_on=false`、`control_seq=0`、current=NULL。
- 无 episode、activation pin 或激活 successor。

安装不等于激活；P0 由独立 reconcile 命令启动。

W2 早于 W3，不能靠真实 P0–P4 现场构造 active owner。`dp2/test_support.py` 因此只为 W2 维护 DML 提供一个 spec-valid active-owner fixture：owner install/fiber、`want_on=true`、`current_episode_id` 指向同 fiber 的 open `active` episode、不可变的 `committed_view`/DP2 iterator v1、合法 epoch 与空或已声明 provides 的一致性；该 seed 仅满足 admission 前提，不计入 CDP2-A 的成功激活证据。W3 另用真实 `command_install` + P0–P4 从空库创建 owner，再验证 ownerful install，避免测试为了顺序而放宽 owner admission。

ownerful install 还在 owner episode 追加一条 contribution：

- kind=`child`，descriptor 精确为 `{"child_fiber_id":<新child的UUID字符串>}`。
- inverse 精确为 `{"op":"dispose_child"}`，contract_version=`1`。
- seq 为该 owner episode 已有最大 seq 加一。
- 同步更新 owner iterator 的 `registered_through`，不改变声明迭代位置。

该 install effect 绑定 owner fiber/episode；root install effect 绑定新 root fiber、episode=NULL。如此，创建 child 的写入属于 effect owner，不以新 child 的名义修改另一个 fiber 的 episode。

DP2 只记录 child inverse，不执行它。

#### 安装冲突与外部准备

DP2 将 `artifact_digest` 视为不可变声明，不创建 CAS reservation/ref，不进行物理准备或释放；设计 §8.1 的 `preparing`/`host_io` 路径及跨存储恢复仍留在后续 host 工作。DP2 的可执行证明只依赖下面枚举的数据库事实，不添加没有存储来源的“其他外部义务”谓词。

- 同 request key、相同 payload：已有 request 原样 replay。
- 不同 request key 遇相同 `(scope_id,identity,version)`：`install_identity_conflict`，即使声明相同也不复用既有实例。
- 已存在的新 install/fiber/scope UUID：`invalid_args`，detail 标明冲突字段。
- service 地址占用不在 install 时预占；在实际注册边界检查。
- direct install 只命名调用方已在宿主预部署的 artifact：写 `state='installed'`，不创建 CAS reservation/ref，不发 `host_io` effect，不产生 host successor。payload 没有 preparation/execution 变体；额外的 `prepare` 或执行字段是 `invalid_args`，而非一个隐式 host path。

这是一条明确的 DP2 准入收窄；不改变已经存在的 DP1 `host_io` claim 合同。设计 §8.1 指出外部 CAS 引用与 PG 非原子；DP2 只记录调用方声明的 digest，不创建或释放外部引用。`artifact_digest` 本身不代表 install-owned CAS ref。若目标 install 的任一实例通过现有 fiber、episode 或 run ownership 关联到 `host_io` effect，则 basic dispose 对所有状态一律保守抛 `0A000`：`ready`/`claimed` 表示待处理，`unknown` 表示未对账，`succeeded`/`failed`/`cancelled` 也不作为 CAS release certificate。DP2 不接受任何 input/outcome 字段作为外部释放证明；后续 host 对账范围负责处理。

### 3.7 最小 resolve 与 check

#### 解析接口

私有 `resolve(scope_id uuid, keys text[])` 返回：

```text
key, contribution_id, provider_fiber_id,
provider_episode_id, provider_epoch,
descriptor, descriptor_digest, contract_version, available
```

每个输入 key 返回一行，保持输入顺序；未命中行保留 key，provider 字段为 NULL，available=false。输入至多 256 项。函数只读、不取 G、不锁行；`advance` 使用它时已经持 G，并随后将有关行纳入 closure。

#### scope 路由

1. 递归沿 `parent_id` 收集当前 scope 到根。
2. 对每个 key 取最近的显式 `realm_overrides[key]`。
3. 无显式项时使用固定 realm 文本 `root`。
4. realm 确定后只查该 `(realm,key)`，不跨 realm fallback。
5. scope 缺失、祖先闭合、parent 环或有界遍历超限均不返回可用 provider。

`realm_overrides` 的值必须是非空 realm 字符串。realm 不授予权限。无显式覆盖时使用设计规定的共享 `root` realm。

DP2 不实现 intercept/overlay 合并。解析路径存在非空 intercept，或候选 provider 的 install 带非空 overlay 时，生命周期入口抛 `0A000`。Oracle-adjudicated 2026-10-26：选择最小递归 resolver + root realm 默认值 + 受限 check 谓词；intercept/overlay 留给后续阶段，依据 DP1 的分工与设计 §6.5/§8.1。

#### provider 准入

一个直接候选至少满足：

- kind=service，withdrawn/released 均为空。
- 所属 episode open、active，且为 provider current episode。
- provider want_on=true，无 retire/dispose 请求或墓碑。
- install 为 installed。
- scope 和 owner 祖先均开放。
- 不存在匹配当前 control_seq 的 failure。

P1 和后续阶段还检查 provider 依赖闭包中的既有 activation pins：epoch/历史身份正确、provider 端仍满足上述准入，冻结绑定没有失效。发现失效即走 unsupported `0A000`。

这是激活入口的只读安全检查，不产生失效通知、递归 reconcile 或 teardown，也不声称交付完整 live 子系统。

descriptor digest 按 `sha256(UTF8(canonical_json(descriptor)))` 派生，不增加 digest 列。

#### check policy

接受两种值：

- JSON null：通过。
- 精确 `{v:1,op:"equals",path:[...],value:...}`。

path 长度为 1–8，每段为 1–128 字符的 object key。只沿 JSON object 读取，不解释数组下标；缺路径返回 false，存在时按 JSONB 相等比较。

policy 形状非法在 install admission 返回 `invalid_args`。合法 policy 求值为 false 是依赖失败，P1/P3 抛 `0A000`；不写 `fibers.failure`，不产生 `dependency_unresolved` receipt。

### 3.8 P0–P4：数据、phase 选择与状态变化

#### reconcile payload

精确字段：

```text
{fiber_id, action, expected_control_seq}
```

action 的成功闭集为 `on/advance`。`off/retry` 是可识别但未实现的请求，payload 形状合法时抛 `0A000`；其他未知 action 返回 `invalid_args`。`expected_control_seq` 为非负 bigint。

- `on` 是 DP2 唯一新建的外部目标命令。
- `advance` 仅允许执行已登记的 ready successor；不得用新 request 自创 phase。
- `off`、`retry` 与任何 active episode 的改目标由 DP3 负责；DP2 收到时以 `0A000` 整笔回滚。
- 不接受 caller 提供 episode、iterator、provider、批量大小或 phase。

#### P0：目标请求

| 情形 | 行为 |
|---|---|
| expected sequence 不匹配 | `stale_generation`，零写 |
| `on`，当前 want_on=false 且无 open episode | want_on=true，control_seq+1，生成唯一 successor |
| `on`，want_on=true | 域 no-op；保留已有 successor，不另建、不递增 sequence |
| `off` 或 `retry` | `0A000`，不改目标；这些命令不属于 DP2 成功激活范围 |

`on` 即使 no-op，也先检查 install、scope 和 owner 准入。control_seq 已为 bigint 最大值时返回 `budget_exceeded`。

P0 不以缺依赖写失败状态；依赖解析在 P1。不同请求对 already-on 的域 no-op仍各自记录 command receipt。

#### P1：L-Begin

无 open episode、want_on=true 的 successor 执行：

0. 先复验 child input 的 `expected_control_seq` 等于当前 fiber.control_seq、fiber.want_on=true 且 current_episode_id=NULL；不满足即 `stale_generation`，不创建 episode 或 pin。
1. 完成全部 requires 的解析、check、provider 准入和联合 DAG 校验。
2. 任一不满足，抛 `0A000`，当前调用零写。
3. epoch=`coalesce(max历史epoch,0)+1`；超过 int 最大值返回 `budget_exceeded`。
4. 创建 open reloading episode，冻结 committed view。
5. 同事务为每个 require 插入一条 activation pin，冻结 provider_epoch。
6. 设置 fiber.current_episode_id。
7. 生成下一条 successor；零 provides 也通过独立 P4 完成。

不在 P1 注册 service。

#### committed view

`episodes.committed_view` 是 require key → binding object：

```text
key → {
  contribution_id, provider_fiber_id,
  provider_episode_id, provider_epoch,
  descriptor_digest, contract_version
}
```

digest 使用 hex64 文本。key 集必须恰等于 requires；零依赖为 `{}`。该对象不包含运行游标、target 状态或另一份生命周期。

增加 immutable guard：episode 创建后，`committed_view` 不允许改变。关闭 episode 也不改历史 ω。

#### iterator

新 episode 的 iterator 精确为：

```text
{v:1, next_index:0, registered_through:-1, control_seq:<P0 sequence>}
```

- `next_index` 指向 immutable `manifest.provides` 的下一项。
- `registered_through` 是本 episode 已登记最大 seq，空账本为 -1。
- `control_seq` 冻结 L-Begin 对应的请求代次。
- 不复制 provides 全量、不持久化执行程序。

#### P3：每个后续阶段开始前的只读检查

P2/P4 前都重新解析 target，并比较：

- want_on、控制代次。
- requires 的完整 key 集和 binding。
- provider episode/epoch、descriptor digest、contract version、check 结果。
- 当前 pin 集与 committed view 一一对应。

任何变化、缺失或失败均抛 `0A000`，不转 closing，不改 ω，不换 pin，不推进 iterator。

P3 是阶段边界校验，不单独生成 effect。

#### P2：L-Iter

当 episode reloading 且 `next_index < provides.length`：

1. 从 immutable provides 的 `next_index` 起取连续至多 32 项。
2. 使用本 episode 的固定依赖视图；不得在批次中途换绑。
3. 每项按自身 scope 的路由确定 service realm。
4. 完整预检本批地址、descriptor、合同、owner 和 seq。
5. 创建 service contribution，inverse 精确为 `{"op":"delete_row"}`，prev=NULL。
6. seq 从 `registered_through+1` 起连续递增。
7. 同事务推进 iterator，结算当前 effect，生成下一条 successor。

地址被任何未 released service 占用，包括 withdrawn 或 reloading provider 的行，均视为注册失败，抛 `0A000`。唯一索引继续兜底，不能用 `ON CONFLICT DO NOTHING` 掩盖失败。

一批第 32 条失败必须使前 31 条及 iterator 一并回滚。

#### P4：L-Finish

当 reloading 且 iterator 已消费完 provides：

1. 先通过 P3。
2. committed view 和 activation pins 对 requires 完全覆盖。
3. 本 episode 的 service key 集恰等于声明 provides；逐项 realm、descriptor、contract version、inverse 和 seq 对应。
4. 不得有缺项、额外 service、重复项或提前 withdrawn/released。
5. child contribution 不计入 service totality。
6. 更新 `episodes.state='active'`，不改 ω、epoch 或 fiber current。
7. 不产生后继，outcome 保持 NULL，留待未来 episode 关闭。

任一 totality 不符抛 `0A000`。零贡献 fiber 仍以 open active episode 表示，不能省略成功事实。

#### rollback 的精确范围

`0A000` 回滚的是当前 advance 所在事务。先前 phase 已 COMMIT 的 episode、pin 或 contribution 前缀继续存在。

例如第二批失败，不撤销已提交的第一批；本调用既不增加半批贡献，也不执行清理。安全排空这些已提交前缀属于 DP3。

### 3.9 closure、ownership 与联合 DAG

#### command closure

request replay/conflict 仍先于 discovery。未命中后，从 payload 提取**已有**目标：

- install：existing scope 或新 scope 的 parent、owner/current episode、既有身份冲突行及 bootstrap root 检查目标。
- P0：fiber、install、scope/owner 链、current episode、已有 reconcile。
- P1：上述目标、历史 epoch 行、全部 require provider 及其依赖闭包。
- P2/P4：episode、pins、已有 accumulator、实时 require provider、本批 service 地址占用行。
- dispose：install 全部实例及其所有义务相关行。

待创建 UUID 不作为不存在的 seed 传给现有 discovery。它们放在拟新增集合中，由 G 下的身份/唯一性校验处理。

扩展 `target_refs`/command closure 的按分支发现能力，保留 typed allowlist和 512 上限。反向集合通过有界迭代加入目标；遇第 513 个不同 typed target 立即停止，不先物化无界子树。

closure 行锁保持：

```text
G → replay target
  → scopes（depth、UUID）
  → runs → effects → installs → fibers
  → episodes → contributions → pins
```

加锁后重新计算完整 command closure，集合或关键绑定漂移即 `retry_with_closure`。不得解释到一半再补锁。

#### DAG

图的节点为 fiber，边为：

- 活 child → owner。
- 活 activation consumer → provider。
- 活 run pin 的 run owner → provider，仅作为既有数据检查。

新 child owner 边和 P1 新 pin 边必须与既有边合并后无环。使用去重 visited 集和递归栈；遍历受同一 closure 上限约束。

- 图有环：`cleanup_cycle`，零写。
- 无法在上限内完成证明：`retry_with_closure`，零写。
- 不靠 priority 数值替代资源 DAG 检查。

增加 deferred final-state DAG guard，覆盖 owner/pin 边变化；它是防绕过兜底，生产路径仍必须在首次 DML 前完成证明。DAG guard 的错误固定为 SQLSTATE `23514`（`reason` 区分 cycle 与验证上限），覆盖 fibers owner、activation pin、run pin 与 run ownership 的相关 INSERT/UPDATE/DELETE，重新读取最终行和 `released_at`/disposed 状态；删除中间行或释放边后按最终图判断。typed validator 的合法路径仍在 DML 前返回 `cleanup_cycle`/`retry_with_closure`，不依靠 COMMIT 异常当正常业务响应。

#### confinement

validator 从 effect/command 上下文确定允许 owner，不接受 delta 自报授权：

- P0 只改目标 fiber 的请求字段。
- P1 只创建该 fiber 的新 episode/pins，并设置它的 current。
- P2/P4 只写当前 owner episode。
- child install 只向已验证的 owner episode 追加 child 账本。
- dispose 只写本 install 已证明无义务的实例及 install。

修改其他 fiber 的 open episode 一律 `invalid_outcome`。

### 3.10 typed delta 与应用器

#### envelope

保留精确顶层：

```text
{domain:[...], receipt:{status}, events:[...], successors:[...]}
```

不增加任意 SQL、表名、column map、caller principal 或另一个 outcome body。

domain 改为封闭 tagged union：

| op | 承载内容 | 允许来源 |
|---|---|---|
| `scope_create` | 新 scope 身份、parent、realm overrides | install |
| `install_create` | 已验证声明及 owner | install |
| `fiber_create` | 初始身份和 owner | install |
| `fiber_control` | 目标位及新 control_seq | P0 |
| `episode_begin` | 新身份、ω、iterator、activation pins、current 目标 | P1 |
| `contribution_append` | 完整 service 或 child 账本行 | P2 / child install |
| `episode_progress` | next_index、registered_through | P2 / child install |
| `episode_activate` | 目标 episode ID | P4 |
| `basic_dispose` | install ID、已证明无义务的实例 ID 集 | dispose |

每个变体采用下列 DP2 `delta_v1` 精确键集；生成时间、effect/principal、状态初值由 applier 推导，不接受 delta 覆盖。所有变体的行内容、计数和状态前提由 `validate_domain` 与解释器独立复验：

| op | exact keys（键外拒绝） | nested / nullable 规则 |
|---|---|---|
| `scope_create` | `op,id,parent_id,realm_overrides` | `id` UUID；`parent_id` 为 UUID 或 JSON null；`realm_overrides` 是 string→non-empty string object；`intercept` 只由 applier 置 `{}`，不在 delta 中出现 |
| `install_create` | `op,id,scope_id,owner_fiber_id,owner_episode_id,identity,version,manifest,artifact_digest,contracts,policy_ref,overlay` | owner 两字段同空或同非空；状态/created_at 由 applier 产生；overlay 必须 `{}`；artifact digest 为小写 hex64 |
| `fiber_create` | `op,id,install_id,owner_id,owner_episode_id,scope_id` | owner pair 同空或同非空；`want_on=false`、`control_seq=0`、current=NULL 由 applier 产生 |
| `fiber_control` | `op,fiber_id,want_on,control_seq` | 只允许当前分支目标 fiber；control_seq 为非负整数；不得携带 current/episode/failure |
| `episode_begin` | `op,id,fiber_id,epoch,committed_view,iterator,pins` | epoch 非负整数；iterator 必须 v1 四字段；pins 数组每项精确为 `{id,key,contribution_id,provider_episode_id,provider_epoch}`，consumer 字段由 applier 从 fiber/episode 补出 |
| `contribution_append` | `op,id,fiber_id,episode_id,seq,kind,realm,key,descriptor,prev_contribution_id,inverse,contract_version` | service 的 realm/key 为非空字符串、prev=NULL、inverse=`{"op":"delete_row"}`；child 的 realm/key/prev 为 null、descriptor 精确为 `{"child_fiber_id":<UUID字符串>}`、inverse=`{"op":"dispose_child"}`；inverse 必须是上述精确单键 object；DP2 不产生 `unknown`/其他 inverse 或其他 contribution kind，保留既有表级闭集只作后续数据合同 |
| `episode_progress` | `op,episode_id,next_index,registered_through` | next_index 为 0–provides.length 整数；registered_through 为 -1–bigint max 整数，等于当前 accumulator 的 max(seq)；只推进当前 episode，child append 不推进 next_index |
| `episode_activate` | `op,episode_id` | 只能把当前 reloading episode 置 active；state/outcome/closed_at 由 applier 推导 |
| `basic_dispose` | `op,install_id,fiber_ids` | `fiber_ids` 是 install 的完整实例集合、UUID 无重复并按 UUID 排序；applier 重新从 closure 比对，不接受 caller 缩小集合 |

每个 domain 中 UUID 字段是合法 UUID 字符串，指定 nullable 字段必须显式 JSON null；counter 必须先检验 JSON number、整数语法和范围再 cast。seq/control_seq 用非负 bigint；epoch 用正 int（DP2 从 1 起）；仅 registered_through 允许 -1。committed_view 每个 binding 精确六键，provider UUID、hex64 digest、版本字符串与本节 pin 条目逐项一致；pins 不接收 consumer_run_id/created_at/released_at，数组按 requires 排序、恰一 key 一 pin。每个数值递增先检查耗尽并返回 `budget_exceeded`，不以溢出异常替代已命名错误。

`install_id`、`fiber_id`、新 scope ID 来自已验证的 command payload；episode、activation pin 和 contribution ID 由私有 interpreter 用 PostgreSQL 内建 `gen_random_uuid()` 生成一次并在同一 delta 中复用，applier 不重新生成。`event_id` 沿用现有 applier 的 `gen_random_uuid()`。UUID 碰撞不采用 upsert，意外唯一性异常整笔回滚。回滚后内部 UUID 可以重新生成，因为此前没有已提交行；成功后 request replay 不再调用解释器。只有 continuation effect ID 必须按 §3.5 确定性派生。caller 不可通过 delta 自报 principal、effect、request actor 或时间戳；owner/identity 字段必须与已验证 payload/DB 上下文逐项一致。

约束：

- 每个 delta 至多 512 个 domain 项。
- P2 至多 32 条 service append；child install 恰至多一条 child append。
- successor 至多 16，全局 ordinal 0–15 不重复；DP2 lifecycle 实际至多一条 reconcile ordinal 0。
- events 至多 1 条；采用下列 DP2 aggregate-event 合同，保留每个 entity 自己的 `max(seq)+1` 游标，但明确不承诺一个阶段同时出现在多个 entity stream；多实体通知覆盖留给 DP5。
- class→receipt status 映射保持 DP1。
- 非 command settlement 不因新 validator 获得 domain 写权。
- `p_structure_only=true` 只证明形状，不授予写权；旧 DP1 inverse probe改成对应 typed contribution probe。

#### 校验与实际写入

顺序固定为：

1. 完整结构及上下文验证，无 DML。
2. 领域行按 FK 依赖应用；scope→install→fiber→episode→contribution/pin/current。
3. 插入外部 command effect，或结算已有 ready continuation。
4. 插入当前命令的 request 首次 response。
5. 追加事件。
6. 插入 ready successors。

`emitted` 在写 response 前按确定性 child identity 算出，必须与最后实际插入集合相同。effect/request/event/successor 的任何意外 SQL 错误直接传播，不捕获后返回成功。

不要把 `basic_dispose` 作为可任意指定 fiber 集的批量更新接口；applier 重新比对该 install 的完整实例集合及 proof。

#### 事件集合

事件仅作簿记；每个成功且有状态变化的生命周期 command **恰好**追加一条下列 aggregate event。字段集合是 exhaustive，ID 均为 UUID 字符串；root install 的 owner 字段与 `child_contribution_id` 为 JSON null；replay、拒绝、回滚和成功 no-op 均不追加事件。

| 分支 | `(entity_type, entity_id, event_kind)` | exhaustive payload keys / 顺序 |
|---|---|---|
| install | `('install', install_id, 'install_created')` | `scope_id,scope_created,fiber_id,owner_fiber_id,owner_episode_id,child_contribution_id`；`scope_created` 为 boolean |
| P0 | `('fiber', fiber_id, 'fiber_target_requested')` | `want_on,control_seq` |
| P1 | `('fiber', fiber_id, 'episode_begun')` | `episode_id,epoch,control_seq,require_keys,pin_ids`；keys 按 manifest requires 顺序、pin_ids 与之对应 |
| P2 | `('fiber', fiber_id, 'contributions_appended')` | `episode_id,contribution_ids,seq_from,seq_through,next_index`；IDs 按 seq 顺序 |
| P4 | `('fiber', fiber_id, 'episode_activated')` | `episode_id,epoch` |
| dispose | `('install', install_id, 'install_disposed')` | `fiber_ids`；按 UUID 排序 |

沿用 entity 内 `max(seq)+1`、G 串行和现有 event ID/FK 生成；P4 只发 fiber stream，不另发 episode stream，ownerful install 不另发 owner stream。该选择不声称保留 DP5 所需的多实体通知覆盖，只保留单 entity cursor 的机械语义；DP1 的单事件上限继续有效，不引入任意 64 事件阈值。

### 3.11 基本 dispose

payload 精确为 `{install_id}`，不接收 force、cleanup 或 descendants 参数。

设 F 为 `fibers.install_id=目标 install.id` 的全部行。closure 和 proof 必须包含 F（含已 disposed 历史实例）、它们的 episodes/contributions、consumer 属 F 或 provider contribution 属 F 的活 pins、`runs.owner_fiber_id ∈ F` 的 runs、owned child fibers/installs，以及关联 effects。关联 host effect 的精确定义为 `effects.fiber_id ∈ F`，或其 `episode_id` 属于 F 的 episode，或 `effects.run_id` 指向 owner 在 F 的 run；三者取并集去重。仅 artifact digest 相同不构成关联，也不能从任意未定义的 input/outcome 字段推断 CAS 已释放。

在同一次 G/closure 校验中证明该 install 的**全部实例**均无：

- open episode，包括 current=NULL 但仍有 open episode 的不一致情况。
- 活 activation pin，或活 run pin 对应的 owner 义务。
- `ended_at IS NULL` 的 run。
- `released_at IS NULL` 的 contribution。
- 未 disposed child fiber、未 disposed owned child install。
- ready/claimed effect 关联目标实例时均阻止（不止 lifecycle/host：seeded 的 dispatch/listener/model/tool/run_start 同样不能漏掉）；通过现有 fiber/episode/run ownership 及 lifecycle input 中精确目标 ID 建立关联。当前正在验证且尚未创建的 dispose command 不算旧义务。
- install.state 必须为 `installed`；`preparing`、`prepare_failed`、`prepare_unknown`、`dispose_pending` 不属于 DP2 basic-dispose 成功域。
- 任何关联实例的 `host_io` effect，无论状态是 `ready`、`claimed`、`unknown`、`succeeded`、`failed` 还是 `cancelled`；DP2 没有 CAS-release certificate，terminal host receipt 也不能证明外部资源已经释放。

还要求实例 want_on=false。不能用 current=NULL、lease 到期、host effect 不在 ready 队列或子树当前不可见替代证明。`artifact_digest` 只是声明字段，不构成 install-owned CAS obligation；direct install 成功路径因此只证明数据库义务为空并把 install/fiber 置墓碑，完整 O-Remove 的外部 CAS 释放仍留在后续阶段。

成功时：

- 对未 disposed fiber 同时写首次 `dispose_requested_at`、`disposed_at`。
- install.state=`disposed`。
- 保留所有历史行，不关闭 scope、不释放 contribution、不删 pin。
- 不写 dispose_pending，不产生清理后继。

任一活义务或无法证明的 host 义务存在：抛 `0A000`，不先写 dispose 请求。已 disposed install 返回 `already_terminal` 零写；原成功 request 仍先 replay。basic dispose 的 effect 授权按 install-wide closure 证明，不能用一条代表性 fiber 或 caller 自报的 `fiber_ids` 缩小检查集合。

child 基本 dispose 不删除 owner 的 child contribution。该账本属于 owner episode，未来由它的 inverse 处理。

### 3.12 错误行为与写类

DP2 所有闭集错误均为 W0：返回稳定 JSON，当前调用无领域行、request、effect、event 或 successor 写入。生命周期成功才记录 receipt。

`0A000` 和意外 SQL 错误必须由调用方 rollback；随后用新事务确认十表与调用前一致。

| 结果 | DP2 生产者 |
|---|---|
| `invalid_args` | payload/声明/check/合同形状；非法新 ID 冲突；第二个 ownerless root |
| `unauthorized` | 原角色族、class/kind 权限 |
| `not_found_or_denied` | 目标 install/fiber/scope 或合法派生 ID 对应的 ready continuation 不存在 |
| `request_conflict` | 原 request 身份冲突 |
| `effect_id_conflict` | 原派生 ID 错误；existing effect 不符合 ready continuation 合同 |
| `receipt_conflict`、`stale_claim`、`blocked_unknown` | 保留 DP1 claim/receipt 生产者 |
| `stale_generation` | 外部 P0 或尚未 begin 的 P1 expected_control_seq 不匹配；P2/P4 drift 仍为 `0A000` |
| `install_identity_conflict` | 不同请求重复安装地址 |
| `scope_closed` | 新安装/P0 on 的 scope 祖先闭合 |
| `owner_closing` | 新安装/P0 on 的 owner 不再允许准入 |
| `install_not_ready` | P0 on 的 install 非 installed |
| `already_terminal` | 新 dispose 请求针对已 disposed install |
| `budget_exceeded` | control_seq、epoch、seq 数值耗尽 |
| `invalid_outcome` | typed delta、写集、批量或后继违规 |
| `cleanup_cycle` | owner/provider 联合图有环 |
| `retry_with_closure` | 超限、缺失已发现引用、锁后漂移 |
| `0A000` | 缺依赖、check=false、注册失败、target drift、需清理 dispose、已关联任意 host obligation、未实现配置/执行 |
| SQL 异常传播 | 未预期约束错误、注入故障、数据库错误 |

`dependency_unresolved`、`provide_conflict`、`registration_stale`、`interaction_mismatch`、`provider_unavailable`、`spawn_key_conflict` 没有新增 DP2 生命周期生产者，matrix 标记保留。不能为“错误码覆盖率”把 binding 的 `0A000` 改成这些码。

错误 detail 使用具名 `reason` 和必要目标 ID，不回传整份 descriptor、合同或内部 SQL。unsupported seam 的异常文本区分具体边界，SQLSTATE 统一为 `0A000`。

### 3.13 gate 断言与强制负例

#### 独立脚本

```bash
uv run python v24/cordis/dp2/test_kernel.py
uv run python v24/cordis/dp2/test_install.py
uv run python v24/cordis/dp2/test_activation.py
uv run python v24/cordis/dp2/test_boundaries.py
```

分别输出 `CDP2-K/I/A/B` 具名断言，exit 0 才通过。均使用真实 canonical SQL、真实 LOGIN 和生产 applier；不依赖网络、pytest 或 FakeHost journal。DP2 各 `test_*.py` 在任何数据库连接前，按 `Path(__file__).resolve()` 将 `dp1` 的确切目录加入模块搜索路径，再导入既有 `setup_db.Server/TestDB` 与 `test_ddl.snapshot`；不得创建同名副本模块遮蔽它们。`test_support.py` 封装调用，不成为新 loader/fixture 实现。所有 TestDB 仍沿用既有随机名、精确 OID 清理和 Unix socket 合同。

#### 具名断言

| ID | 必须证明 |
|---|---|
| CDP2-K1 | G→replay target→完整 closure 的锁序；replay 不发现/等待无关 closure |
| CDP2-K2 | ready continuation 无预写 request；执行后首次生成 request；重复提交原样 replay |
| CDP2-K3 | child identity、parent/ordinal、actor/input 不可伪造；`emitted` 与实际后继一致 |
| CDP2-K4 | 每种 typed op 的有效 golden delta、缺键/多键/类型/null/inverse/pin 嵌套形状负例；分支权限、跨 install 写入拒绝；全部预检先于 DML |
| CDP2-K5 | effect/request/events/successor 注入故障均整笔回滚 |
| CDP2-K6 | terminal effect 不可重开或替换 outcome/settled_at；request response 不可替换；合法 ready→succeeded 只产生一次 receipt |
| CDP2-K7 | continuation 的 expected_control_seq 在 P1 DML 前复验；generation/actor/input 不匹配的精确错误与零写；失败后同一 ready child 可重试且不重复贡献/事件/successor |
| CDP2-K8 | 每个状态改变分支的 exhaustive aggregate event tuple/payload、entity seq、no-op/refusal/replay 无 event；单 entity cursor 范围与 DP5 deferred 边界明确 |
| CDP2-I1 | bootstrap root、existing scope、child scope 的安装和 owner 关系 |
| CDP2-I2 | 合同/check/manifest/realm 声明校验；安装不激活、不执行 IO；四种 replay boolean 组合均只作声明数据 |
| CDP2-I3 | ownerful install 的 child ledger、seq、inverse 和 owner effect 绑定；W2 使用 spec-valid active-owner maintenance fixture，W3 再以真实 P0–P4 创建 owner |
| CDP2-I4 | realm 最近覆盖、root 默认、跨 realm 无 fallback；resolve 零写 |
| CDP2-I5 | deferred final-state unique-root guard 拒绝第二个 ownerless fiber（disposed 历史 root 仍占用 root 槽） |
| CDP2-A1 | P0 CAS/no-op；每 fiber 至多一条 ready/claimed reconcile |
| CDP2-A2 | P1 同事务冻结 ω、pins、provider_epoch 和 current |
| CDP2-A3 | 0、1、32、33 项 provides 的批次/seq/iterator，且每批 ≤32；33 项 fixture 共用合同且满足现有 body/键上限 |
| CDP2-A4 | P4 requires/provides totality；零贡献 fiber 仍有 active episode |
| CDP2-A5 | service 地址互斥；provider 未 active 时不可解析；不同 realm 同 key 可成功 |
| CDP2-A6 | ownership/confinement/联合 DAG；committed view immutable |
| CDP2-B1 | unsupported 依赖/check/注册/漂移路径精确 `0A000`，当前调用零写 |
| CDP2-B2 | 无义务基本 dispose；每一种义务单独阻止墓碑化 |
| CDP2-B3 | disposed 不复活；历史行保留；不出现 closing/divert/error/withdraw/release |
| CDP2-B4 | 表数/manifest/ACL/DEFINER/1200 与900行预算 |
| CDP2-B5 | basic dispose 对多实例 install 的完整集合 proof；漏实例/混入别的 install 的 delta 被拒；一个实例有义务即全体不墓碑化；所有 kind 的 ready/claimed effect 与六种关联 host 状态逐一拒绝；无 host/CAS ownership 的 direct-install 正例通过 |

#### 强制负例

每例断言精确错误 JSON、SQLSTATE 或约束名，并比较十表快照：

1. 不同 request 重复 `(scope_id,identity,version)`：`install_identity_conflict`。
2. 同 realm/key 第二个 service 注册：`0A000`；另以 owner DML证明索引 `23505`。
3. 同 fiber 第二个 open episode：实际 partial unique `23505`。
4. pin provider_epoch 错配：deferred guard `23514`。
5. contribution fiber/episode 错配：复合 FK `23503`。
6. delta 修改另一 fiber open episode：`invalid_outcome`。
7. 17 个 successors、ordinal 重复或 >15：`invalid_outcome`。
8. 单个 P2 delta 33 条 service append：`invalid_outcome`。
9. 未获当前分支权限的非空 domain：`invalid_outcome`。
10. 同一 ready reconcile 两连接重复提交：一次执行、一次首次 response replay，无第二批贡献或后继。
11. 原请求已 replay 后不再校验 continuation 当前状态；无 request 时，parent/ordinal、reserved key、actor、stored input 或 binding 伪造必须 `effect_id_conflict`，且零写。
12. P0→P1 generation 改变：`stale_generation`；按正确 ID/key 提交不存在的 child：`not_found_or_denied`；P1 后改 control/target 或 provider 绑定：P2/P4 抛 `0A000`，ω/pin/iterator 不变。依赖修复后原 ready child 可重试并只执行一次。
13. 缺依赖、equals=false、同批后部地址冲突：`0A000`。
14. P4 缺一项/多一项 provision：`0A000`，不能 active。
15. dispose 的 open episode、活 pin、run、贡献、child 以及关联 `host_io` 的 `ready`、`claimed`、`unknown`、`succeeded`、`failed`、`cancelled` 六种状态分别阻止；direct install 没有 host effect/CAS ownership 的正例成功。
16. immutable ω、terminal receipt、input 和 ownership 修改被 guard 拒绝。
17. 512/513 closure 边界、typed 去重、缺失引用和锁后漂移。
18. 非空 intercept/overlay：`0A000`，不忽略配置；未知的 `prepare`/执行字段：`invalid_args`；合法 direct install 不产生 `host_io` effect 或 CAS ownership。

JSON 错误路径执行 caller COMMIT 后比较快照；SQL 异常路径先 rollback，再开启验证事务并 COMMIT 后比较。不能在 aborted transaction 上伪称完成 COMMIT。

#### 原子性和并发证据

- 用实际锁等待、`pg_blocking_pids` 和 G 的 `objsubid=2` 证明顺序，不用 sleep 猜测。
- 两连接争用同 service 地址：一个激活，另一个注册阶段 `0A000`；其先前成功 phase 不计作本次半写。
- P2/P4 之前还要复验 episode 的 immutable fiber/epoch 绑定、open/reloading 状态与 iterator v1；历史或不一致状态不通过成功路径，不改写为“修复后继续”。
- 在批次末尾、current 设置后、effect/request 后、successor 插入时分别注入异常。
- 测试触发器和函数替身只存在 disposable probe DB；生产 fixture 不替换 applier。
- unsupported 用例检查所有相关列，特别是没有 closing/divert/error/withdrawn_at/released_at。

#### DP1 gate 的必要维护

DP1 gate 必须继续独立可跑，但不能继续断言生产 `interpret_command` 全部为 `0A000`：

- W1 的 terminal guard 与 continuation writer 同步更新 DDL negatives：合法 ready→succeeded 成功；旧 status 为 succeeded/failed/unknown/cancelled 时，不得改 status、outcome、settled_at、attempt/fence 或 claim/lease 字段，违规 `55000`；requests 既有 immutable response 证明继续保留。
- W2 新增 root/DAG guard 后，`v24/cordis/dp1/test_ddl.py:73` 的 `seed()` 原有两个 ownerless fibers 加反向 pin 将不再是合法正例：改为一条 root、其 active episode 和合法 ownerful 子实例，基础正例不得同时形成 child→owner 与 owner→child 的 pin 环。专门的跨 episode FK、重复 root 和环图用独立 savepoint/COMMIT 负例保留原意。`test_kernel.py` 的 `host_seed()` 与 closure 规模 probe 同步采用单 root 的合法 owner 图；不要关闭 guard 或放宽 root/DAG 规则使 fixture 通过。
- 保留 committed protocol probe，仅在 disposable DB 替换解释器/barrier。
- hash 对比改为证明 production **DP2 command 实现**和原 settlement seam 未被 probe 修改。
- production command 用真实合法 DP2 payload 验证；malformed payload 返回当前约定错误。
- 原 empty-only 拒绝断言改为未获分支权限的 typed domain 拒绝。
- 保留 24-code、ACL、preflight、claim、replay-first、锁序和 durable receipt 证据。
- `interpret_settlement` 仍明确验证 `0A000`。

### 3.14 回归命令与证据工件

每个里程碑先串行运行以下现有五命令，再运行当前已交付的 DP2 脚本：

```bash
uv run python v24/cordis/load.py
uv run python v24/cordis/dp1/setup_db.py --self-check
uv run python v24/cordis/dp1/test_environment.py
uv run python v24/cordis/dp1/test_ddl.py
uv run python v24/cordis/dp1/test_kernel.py
```

B0、各提交里程碑和最终 closeout 均按以下顺序记录 v24 回归；同 worktree pgembed gates 不并发：

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

单列扩展命令，不计入十一条：

```bash
uv run python v24/s9/test_g8.py
```

沿用 DP1 的十二文件 SHA-256 和冻结 diff 检查，比较 `v24/load.py`、`v24/sql`、`v24/s1`–`v24/s12`；再核对全部 untracked 文件。不得修改冻结目录以使回归通过。

每次更新：

- `v24/cordis/dp2/README.md`：合同、实际命令/退出码、当前边界。
- `docs/reviews/cordis-v2-dp2-conformance-matrix-2026-10-26.md`：每个具名断言、生产者、证据、退出码、未覆盖项和预算。
- `docs/reviews/cordis-v2-dp2-deviation-ledger-2026-10-26.md`：本文实施选择、协议扩展、失败及修正，不删除历史。
- 本计划：里程碑状态，未运行项保持未验证。

## 4. File-by-file impact

| 文件 | 改动 | 原因 / 顺序 |
|---|---|---|
| `docs/plans/v24-cordis-dp2-lifecycle-plan-2026-10-26.md` | 用本文扩展 scaffold，维护执行状态 | 实施前固定合同 |
| `v24/cordis/sql/40_advance.sql` | 新增 resolver/check/command closure/typed validator/三个生命周期私有分支；扩展 continuation 接纳、实际领域应用、metadata、events 和 successors | W1 基础先于 W2–W4；全部 helper 计入1200行 |
| `v24/cordis/sql/30_triggers.sql` | W1 保护 terminal effect/receipt 不可重开；W2 冻结 committed_view、增加唯一 root 与 final-state 联合 DAG guard | 与相应生产 writer/gate 同一里程碑；计入900行 |
| `v24/cordis/dp1/test_kernel.py` | 更新 obsolete seam/empty-only 预期、`host_seed()` 和 closure probes 的单 root/DAG fixture；保留适用协议证据及 probe/hash 对比 | W1 协议扩展及 W2 guard 的对应适配各自原子落地 |
| `v24/cordis/dp1/test_ddl.py` | W1 terminal receipt 保护正负例；W2 ω/root/DAG 正负例及 `seed()` 合法 owner 图适配，维护写事务先取 G | 与各自 guard 原子落地；保留现有 FK/epoch/不可变负例意图 |
| `v24/cordis/dp1/README.md` | 增加“DP2 后当前行为”说明，保留 DP1 历史验收 | 不重写历史状态 |
| `v24/cordis/dp2/test_support.py` | 复用 DP1 fixture/snapshot；封装有效 payload、API、逐 phase 驱动、零写与 SQLSTATE 断言；为 W2 维护 DML 构造 spec-valid active owner fixture | 不复制 Server/TestDB，不成为生产入口；owner seed 不计作激活证据 |
| `v24/cordis/dp2/test_kernel.py` | CDP2-K | W1 |
| `v24/cordis/dp2/test_install.py` | CDP2-I | W2 |
| `v24/cordis/dp2/test_activation.py` | CDP2-A | W3 |
| `v24/cordis/dp2/test_boundaries.py` | CDP2-B | W4 |
| `v24/cordis/dp2/README.md` | 阶段合同、命令、结果、限制 | 各里程碑更新 |
| DP2 conformance matrix | 具名覆盖和本轮证据 | 各里程碑更新 |
| DP2 deviation ledger | 显式选择、偏差、失败修正 | 各里程碑更新 |

不修改：

- `v24/cordis/load.py`、十六文件 manifest、DP1 environment 的精确 tuple。
- DP1 `TABLES`、fixture catalog 表集和角色族。
- `00_schema.sql`、八张领域表文件、两张簿记表及 `20_relations.sql`。
- 冻结的 `v24/load.py`、`v24/sql/**`、`v24/s1`–`v24/s12`。
- DP1 已完成 matrix/ledger 的历史证据。

`50_permissions.sql` 最后执行的全函数撤权继续覆盖新增私有 helper；ACL gate 必须证明没有新公开入口。

## 5. Risks and migration

### 持久化与回退

不增加表、列、enum 或 extension，也不迁移 v24 数据。新增持久合同是：

- reconcile successor 的 reserved request key 和冻结 input。
- committed view binding object。
- iterator v1。
- typed delta 仅在事务内传递，不存储为恢复计划。

DP1 没有生命周期 producer，因此其合法已有数据不要求批量改写。owner-seed 的 `{}` iterator/manifest 不能被当作已通过 DP2 admission；执行时未满足 DP2 合同必须拒绝，不能补猜字段。

schema loader 是新库加载器，不是在线 migration。DP2 gates 使用 disposable DB 重建。对已有长期 Cordis DB 的升级不在本阶段发布范围。

一旦存在 DP2 ready continuations，回退至 DP1 无法推进它们。应保留 DB 并前向修复；不能通过删除 pin/contribution 或伪造终态回退。已执行 command 的首次 response仍按 request 原样重放。

### 主要风险与回退条件

| 风险 | 控制与验证 |
|---|---|
| ready child 被当作已执行 request | child 创建时无 request；执行后跨连接 replay gate |
| I7 的立即唯一性导致 successor 插入失败 | 当前 effect 先 settled，后插 child；实际事务测试 |
| 分批激活失败后前缀遗留 | 明确只回滚当前调用；不冒充可卸载，DP3 接管 |
| 新 closure 漏反向关系 | 分支 seed、锁后重算、义务逐项负例和512护栏 |
| graph 行级分离被误当全局独立性证明 | 联合 DAG/写集只记局部证据，不宣称完整Confluence |
| descriptor/check/合同规则与未来插件不兼容 | wire shape显式版本化、只接受声明数据；不执行动态谓词 |
| SQL预算被 helper 拆分掩盖 | 40全部物理行≤1200；10–17/20/30累计≤900 |
| 新 guard 破坏 DP1 fixture 合法序列 | guard读取最终状态，保留 deferred 正例并全跑DP1 |
| 角色切换或跨 LOGIN 推进改变命令principal | DP2同LOGIN执行continuation；真实角色测试 |
| `epoch` / seq / continuation 在失败后耗尽或不匹配 | 先检查数值边界、冻结 input 与 DB 代次；明确 JSON 错误和 0A000 的分界，不写失败收据 |
| originating LOGIN 丢失 | 保留 ready 行与 frozen actor；本阶段不重绑身份，后续 scanner 设计必须解决 handoff |
| 事件聚合使 episode/owner stream 无独立事件 | 显式 DP2 cursor 范围与 CDP2-K8 证明；DP5 再决定多实体通知 |
| 外部准备被误认为无需 settlement | direct install 不获取 CAS ref、不产生 host effect；任何已关联 host_io 状态阻止 basic dispose |

预算超限时先简化本阶段实现，不能移动到预算外文件、提高上限或把程序藏进 JSON。无法保持预算即记录未达标，不能以局部绿色结项。

### 分歧点清单

以下五项由 Oracle 于 2026-10-26 裁决，均属工程/协议合同判断，不是用户偏好；具体实现和验证见对应章节。scope/root 路径和最小 resolver 的具体 JSON 字段是本 plan 提出的 DP2 wire v1，须在 DP2 ledger 标为新增局部合同，不冒充既有设计条文。

| 项 | Oracle 裁决 | 理由与信心 | 何种证据会推翻 |
|---|---|---|---|
| 后继身份与回执 | reserved request key，经现有 `effect_id_for` 派生 ID；ready child 先不写 request | 保持 command ABI 和首次 response replay（高） | 新 ABI 明确要求 ID 独立于 command key，或要求执行前即有 request receipt |
| resolver/config 范围 | 递归最小 resolver、root realm 默认、受限 equals check；intercept/overlay 后置 | 符合 DP1 分工及 `scopes.parent_id` 路由形状（高） | 新规格要求 DP2 就支持非空 interception/overlay |
| 失败映射 | malformed/stale 使用现有稳定错误；未实现的依赖/检查/注册/漂移/清理路径 `0A000` 全回滚 | 不虚构已实现失败转换（高） | 新合同定义这些错误码的 receipt/replay 与状态转换 |
| SQL 文件布局 | 新增 `41_lifecycle.sql`（40 与 50 之间），manifest 十六文件；40 ≤1200、DDL 前缀 ≤900 | 用户 2026-10-26 对 layout/cap 的裁决；W2 helper 与命令入口分离，实测预算通过 | 实测 40 或 DDL 前缀超限，或新增表/列/枚举/扩展 |
| root/owner 准入 | 唯一 ownerless root；ownerful install 要求开放 active owner episode | 与设计 §4.2/§7.1 的 root 与 owner 图约束一致（高） | 修订设计明确允许多个独立 ownerless roots |

#### 评审后补充裁决与可覆盖假设

Oracle-adjudicated 2026-10-26：有界评审指出原 draft 的外部写 classifier、CAS 证明和事件流覆盖没有可执行来源。以下四项采用 Oracle 的保守选择；它们包含阶段范围/兼容性或部署偏好，**是本计划假设，不是用户已确认的永久产品限制**。

| 假设 | 采用与理由 | 信心 / 推翻条件 |
|---|---|---|
| 外部能力声明 | 不增加 external-write classifier；DP2 只注册 service 声明、保存四种 replay 组合，无 handler/host producer。现有 DP1 first-claim/reclaim 绑定合同保留 | 高；明确 DP2 外部执行需求且给出 classifier/producer/settlement 合同则重开 |
| CAS 与 dispose | direct install 不取得 CAS 所有权；任何关联 host_io 状态均阻止 basic dispose。digest 无法证明 ownership/release | 高；发现权威 CAS ownership/ref/release 表示，或 direct install 必须取得 ref 则重开 |
| 事件覆盖 | 每个状态变化一条精确 aggregate event，no-op 零事件；多 entity 通知留 DP5，保留当前单事件 validator | 中高；DP2 验收需要同时消费 fiber/episode 等多个 stream 则重开 |
| LOGIN 部署 | continuation 限 originating LOGIN；不分离 executor/principal，保留 effect_id_for ABI。丢失该 LOGIN 时未执行 child 保持 blocked | 高；DP2 明确需要跨 LOGIN 扫描或账号替换则在 W1 前重开 |

其余固定合同：保留 `revision=0`；P2 只生成 service，ownerful install 只追加 child 账本；未知 payload preparation/execution 字段返回 `invalid_args`。具体合同、理由和推翻条件在实施时写入 DP2 deviation ledger。

有界评审的八项发现已落实为 terminal guard 提前到 W1、P1 generation/失败重试表、精确 typed delta 与 install-wide dispose 权限、事件 tuple、声明/claim 合同、可判定 host 检查、unique-root guard，以及 W2 active-owner maintenance fixture。详见 `docs/reviews/v24-cordis-dp2-lifecycle-plan-critique-2026-10-26.md`；该评审是静态文档证据，不是 gate 通过证据。

### 已裁决的 scaffold 歧义

以下选择已经由设计、DP1 边界或本次 Oracle 裁决解决；与其对应的契约和证据见上文各节。

| 原开放项 | 本计划采用 | 依据 / 验证 |
|---|---|---|
| resolve默认realm、签名 | root文本默认；九列私有只读接口 | §6.5根共享realm；递归路由正负例 |
| intercept/overlay是否DP2 | 不合并，遇非空执行请求`0A000` | DP1阶段表归DP5 |
| check闭集 | require-key映射，null/equals | v24数据谓词先例；这是新明确wire合同 |
| command payload/phase | 三种精确payload；stage从DB推导 | §5.1禁止caller决定生命周期分支 |
| ω/iterator形状 | binding map与四字段iterator v1 | §4.2语义，避免复制生命周期 |
| admission错误还是全部0A000 | 声明/身份/准入用W0；依赖/注册/漂移用0A000 | 区分非法请求与binding的未实现失败转换 |
| scope创建 | existing/root/child闭集；root默认realm | O-Insert必要时建scope，scope_control并入install |
| installed/preparing | 仅无需host准备的installed | settlement明确后续 |
| dispose时机 | W4实交付、每种义务具名gate | binding明确包含基本dispose |
| SQL布局 | 新增41，manifest十六文件；40只留命令入口接缝 | 40/DDL前缀预算与十五表不变 |
| revision | 0 | DP1无freshness，DP2不引入新语义 |

实施前仍须核实的事实：

实施前的 B0 验证项：当前 HEAD/upstream、用户未提交文件、Python/PG18/本地依赖，以及新增 SQL/helper 的物理行预算；33 项 provides 的 fixture 必须共享合同并满足 body ≤1 MiB、递归键数 ≤200。若实测与记录不符，按证据更新 matrix/ledger；预算超限或 upstream 与目标分支不一致时暂停，不降低门槛。

## 6. Implementation order

1. **B0：记录当前基线，并在提交推送后独立结项。** 阅读实际 AGENTS，核对 worktree/branch/HEAD/upstream/依赖；串行运行现有五条 Cordis 命令、十一条 v24 命令和单列 s9，复核十二个冻结 SQL hash 及冻结 diff。记录真实结果，不能照抄 DP1 历史退出码。更新 DP2 README、conformance matrix、deviation ledger 与本计划的 B0 证据；所有 gate 通过后，B0 作为独立里程碑按路径暂存、提交、推送。DP1 计划记录 `v24`/`origin/v24`，而根与 worktree AGENTS 的推送路径写作 `main`/`origin/main`；本计划不自行解决该冲突。可完成本地验证和工件，但若推送目标仍不明，按 Open Questions 停在提交/推送边界并请求用户裁决。（2026-10-26 用户已授权逐里程碑 commit + push `origin/v24`，B0 据此结项。）

2. **W1：原子落地内核扩展与对应测试更新（本地已完成；证据见本节）。** 先实现 reserved successor identity、ready continuation 执行、P0→P1 generation 复验、command closure 接线、typed 结构/上下文校验和真实 applier；同时把 terminal effect/receipt guard 放进 `30_triggers.sql`，在本里程碑保护 ready→succeeded、禁止 terminal reopen/outcome 替换，并保留 requests response immutable。保留尚未实现的领域分支`0A000`。同一里程碑更新 obsolete DP1 kernel 预期并新增 CDP2-K；用 disposable probe 证明域写、receipt 和后继的原子性、失败后 ready child 可重试。不得提交一个只能登记、不能执行的后继协议，也不能先提交没有 terminal guard 的 durable receipt writer。

3. **W2：安装、路由和 guard。** 新增 `41_lifecycle.sql`，实现声明/check/contracts、scope 变体、root/owner 准入、O-Insert 和 child 账本；加入 committed_view immutable、唯一 root deferred final-state guard 与联合 DAG 兜底。使用 `test_support.py` 的 spec-valid active-owner maintenance fixture 验证 ownerful admission，同时明确该 seed 不是激活证据。guard、writer、DDL/kernel 预期及 CDP2-I 必须一起落地。实际验证 direct install 不激活、不生成 host/CAS preparation；四种 replay boolean 只被存储和校验。

4. **W3：P0–P4。** 实现 CAS/no-op、P1 完整冻结、P3 只读一致性检查、≤32 的 P2 及 P4 totality；每个状态改变阶段同时落地本计划的精确 aggregate event，成功 no-op/replay 不落 event。新增 CDP2-A 和对应 unsupported 负例；用真实 API 驱动全部 phase，不能用 owner DML 代替成功路径。确认当前 effect 先结算、next successor 后插入，并在第二批失败后用同一 ready child 继续而不重复写。

5. **W4：基本 dispose 和边界。** 实现 install-wide 全实例无义务证明及墓碑；对关联 `host_io` 的 ready/claimed/unknown/succeeded/failed/cancelled 六种状态逐一拒绝，并证明 direct install 没有 CAS ownership。新增 CDP2-B。逐个证明活义务、缺依赖、check 失败、漂移、注册失败均不产生提前清理或 failure 状态；unsupported 路径只能回滚当前调用，不写 closing/divert/error/withdrawn_at/released_at。

6. **W5：closeout。** 按既定顺序重跑全部当前 Cordis/DP2/v24 gate，记录独立退出码、预算、冻结 hash/diff 和未覆盖项。确认无新增表/SQL 文件/公开 writer，事件游标范围按 DP2 单 entity 合同记录，且生产 settlement 仍 `0A000`。

B0、W1、W2、W3、W4、W5 分别是独立里程碑：每项须运行该阶段全部 gate 与必要回归、更新 DP2 README/matrix/ledger/plan，再按具体路径暂存、检查暂存内容与凭据、单独 commit/push；不得把相邻里程碑合并提交。B0 核实的 upstream 只作证据，不凌驾于尚未关闭的发布分支 Open Question。禁止 `git add -A`、`git add .`、`--no-verify`、reset 用户改动或 force-push。里程碑未绿不得进入下一项；远端冲突按实际仓库规则处理。

### B0 证据（2026-10-26 实跑；已按用户授权提交并推送 `origin/v24`，B0 结项）

B0 的本地验证与四个工件已完成；发布授权（2026-10-26）：用户明确授权本 DP2 计划按里程碑逐个 commit 并 push 到 `origin/v24`；这是针对本工作任务的具体授权，不改写根与 worktree `AGENTS.md` 的 `origin main` 规则，也不切换用户工作树或改写历史。 B0 已按该授权提交并推送，里程碑结项。

**环境与仓库事实**

| 项 | 实测值 |
|---|---|
| worktree / 分支 | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` / `v24` |
| HEAD | `0590d4703ea1404febbc82d6114fd8d91f385902` |
| upstream | `origin/v24`；`git rev-list --left-right --count origin/v24...v24` = `0 0` |
| DP1 交付提交 | `5163b23`（loader/fixture）、`e9ccf30`（DDL）、`69efd38`（kernel/ACL）、`0590d47`（closeout） |
| 冻结比较基线 | `57e2c1e`（非 DP2 预期 HEAD） |
| Python / psycopg2 / PostgreSQL | 3.12.11 / 2.9.12（dt dec pq3 ext lo64）/ 18.4（180004），仅 Unix socket |
| 跟踪文件工作区 | 无修改、无暂存、无删除 |
| 未跟踪文件 | B0 前已有 24 个，全部位于 `docs/`，属用户输入；B0 只新增本文与三个 DP2 工件 |
| Cordis manifest | `v24/cordis/load.py` 改为十六文件；新增 `41_lifecycle.sql`，十五张表不变 |
| 预算 | `40_advance.sql` 340 物理行（≤1200）；DDL 前缀 `10`–`17`/`20`/`30` 合计 350 物理行（≤900） |

**实跑结果（串行执行）**

| 命令 | 退出码 |
|---|---:|
| `uv run python v24/cordis/load.py` | 0 |
| `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 |
| `uv run python v24/cordis/dp1/test_environment.py` | 0 |
| `uv run python v24/cordis/dp1/test_ddl.py` | 0 |
| `uv run python v24/cordis/dp1/test_kernel.py` | 0 |
| `uv run python v24/load.py` | 0 |
| `uv run python v24/s1/setup_db.py --self-check` | 0 |
| `uv run python v24/s1/test_ddl.py` | 0 |
| `uv run python v24/s1/test_g1.py` | 0 |
| `uv run python v24/s2/test_g3a.py` | 0 |
| `uv run python v24/s3/test_g2.py` | 0 |
| `uv run python v24/s4/test_g2b.py` | 0 |
| `uv run python v24/s5/test_g4.py` | 0 |
| `uv run python v24/s6/test_g5.py` | 0 |
| `uv run python v24/s8/test_g7.py` | 0 |
| `uv run python v24/s7/test_g6.py` | 0 |
| `uv run python v24/s9/test_g8.py`（单列） | 0 |

CDP1-D 报 97 个零写负例加正例与真实 COMMIT 失败；CDP1-K 报 66 个已提交零写断言并确认 lifecycle interpreter 仍为 `0A000`；s9 报 23 个具名 case。未采集各命令耗时（耗时不是 B0 的必需证据），证据为退出码与打印出的具名断言。

**冻结证据**：十二个 `v24/sql/*.sql` 的 SHA-256 与 DP1 P0 记录逐一相同；`git diff 57e2c1e -- v24/load.py v24/sql v24/s1..s12` 退出 0 且无输出。没有为让回归通过而修改冻结目录。

**B0 未覆盖**：CDP2-K/I/A/B 全部具名断言（脚本不存在）、DP2 全部生命周期行为、33 项 provides fixture、512/513 DP2 closure 边界、新 helper 的行预算实测、以及发布本身。这些保持未验证，直到对应 W 项实跑。

**提交/推送状态（已关闭）**：发布授权由用户于 2026-10-26 给出（逐里程碑 commit + push `origin/v24`）。B0 关闭提交即B0 关闭提交（subject：`v24: close out Cordis DP2 B0 baseline with gate and frozen evidence`），已推送到 `origin/v24`（非 force、未跳过 hook）；推送前 `origin/v24...v24` 为 `0 0`，推送后本地与 `origin/v24` 同步。提交只包含四个 DP2 工件路径，未使用 `git add -A` / `git add .`，未卷入 24 个未跟踪用户文档，未 reset 用户改动。B0 核实的 upstream 只作证据，不凌驾于用户授权。后续 W1–W5 沿用同一发布目标，仍遵循「本里程碑推送后才进入下一里程碑」的纪律；远端冲突按实际仓库规则处理。

### W1 证据（2026-10-26 实跑；已结项：commit `50affb0`，pushed `origin/v24`）

W1 在 B0 HEAD `5e36a5a` 之上实现，结项提交为 `50affb0`（subject：`v24: implement DP2 continuation and typed delta kernel`），已推送到 `origin/v24`。改动为 `v24/cordis/sql/40_advance.sql`（340→1196 物理行）、`v24/cordis/sql/30_triggers.sql`（+10 行，194 行）、DP1 的 `test_ddl.py`/`test_kernel.py` 预期，以及新增 `v24/cordis/dp2/test_support.py`、`v24/cordis/dp2/test_kernel.py`。W1 当时未新增 SQL 文件、manifest 仍十五文件；W2 随后新增 `41_lifecycle.sql` 并扩为十六文件。

**实跑结果（全部串行，退出码 0）**

| 组 | 命令数 | 结果 |
|---|---:|---|
| 十一条 v24 回归 + 单列 s9 | 12 | 全部 0；G1–G8 具名断言通过，s9 23 个 case 通过 |
| Cordis loader/fixture/environment | 3 | 全部 0 |
| CDP1-D | 1 | 0；113 个零写 DDL probe（terminal 正反向、attempt/fence 增减、request response）；输出 `terminal attempt/fence +1 and -1 -> 55000` |
| CDP1-K | 1 | 0；66 个 committed zero-write assertions |
| CDP2-K | 1 | 0；K1–K8/K4b 全部具名断言 |

18/18 命令逐条 `EXIT 0`；命令级清单见 matrix 的「Actual W1 exit codes」。

**Intermediate failure（诚实记录）**：第一轮 post-review 全量复跑在 `[5] uv run python v24/cordis/dp1/test_kernel.py` 返回 `EXIT 1`，`test_kernel.py:428` 报 `KeyError: 'disposition'`。根因是 strict event validator 最初拒绝了 DP1 probe 的 synthetic `receipt` event（payload `{}`），使成功的 host settlement 返回 error。修复为保留 `receipt` 的 object-only 形状后，CDP1-K 单独复跑退出 0，最终 18 条全量复跑全部 `EXIT 0`；失败轮不作为通过证据。

**CDP2-K 覆盖**：K1 G→target→scope closure 顺序与 locked-scope replay 绕过；K2 ready child 无 request、P0→P1→P2→P4/install/dispose 一次执行写 request/event/successor、首次响应 replay 逐字节相同、mixed-history dispose 保留旧时间戳；K3 absent/non-ready/wrong derivation/actor/parent/input/fiber/ordinal 拒绝与 ordinal 1 合法、ordinal 16 拒绝；K4 九种 op 的 golden/missing/extra/type/null、六种 event 的 null/type、invalid successor、branch/cross-fiber 预检、pin 结构；K4b production seam、scope/owner/dispose/pin/provide 边界、512 fibers + 1 episode 的 513 closure cutoff、P0 no-op event/successor；K5 scope/effect/settle/request/event/successor 注入故障后十表零写；K6 terminal 字段与 response 不可变；K7 `stale_generation`、P2 drift `0A000`、失败后 ready child 同一 receipt 重试一次 + replay；K8 聚合事件精确 tuple/payload、单 entity cursor、no-op/replay 不落 event。

**Wire v1 对齐**：`command_dispose` 的 command payload 严格为 `{install_id}`，`fiber_ids` 只在内部 `basic_dispose` delta 中由 DB 派生；root scope 严格为 `{mode,id,realm_overrides}`（无 `parent_id`），existing 为 `{mode,id}`，仅 child 有 `parent_id`。DP1/DP2 fixture 已同步；K2 的 dispose/root 与 K4b 的 subset/root-parent_id 负例覆盖。`test_kernel.py` 在 fixture import 前用 `Path(__file__).resolve().parents[1] / 'dp1'` 显式插入 DP1 目录；K2 的 event cursor 是带 `assert` 的 `[0,1,2,3]` 证明；K2 还覆盖 child 的**非 NULL `episode_id`**：episode 已 closed（`current_episode_id=NULL`）或 open 但不再 current 时，均返回 `effect_id_conflict` / `continuation_binding`，并以 owner 全表 snapshot 证明零写。

**Full bounded Oracle review（完成；五项发现全部修复）**：bounded Oracle review 已完整覆盖 W1 变更，提出以下五项 actionable findings，均有对应修复与 CDP2-K/CDP1 证据：

1. **P1.1 event null/type**：新增 `json_array_valid` / `event_payload_valid`，在 `validate_delta` 内对六种 lifecycle aggregate event 的嵌套 UUID/整数/布尔/数组逐项做类型与 null 校验；分支比较改用 `IS DISTINCT FROM`，避免 `NULL <> expected` 被当成通过。DP1 的 host `receipt` 事件保留 object-only 形状，避免破坏 CDP1-K settlement。
2. **P1.2 successor prevalidation**：lifecycle successor 在 `validate_domain` 的 DML 前统一要求 `kind='command_reconcile'`、`ordinal=0`、精确 input；其他业务 kind 只保留 `validate_delta` 的结构合同，实际 lifecycle 返回 `invalid_outcome`/`successor_kind`（plan §3.5 的 B=16 结构合同不变）。
3. **P1.3 dispose closure 513**：dispose closure 的 `UNION` 结果加 `LIMIT 513` 并在每次 append 后检查；512 fibers + 1 episode 的负例证明第 513 个 distinct target 在 materialize 前被拒。
4. **P1.4 dispose timestamps**：`basic_dispose` 只更新 `disposed_at IS NULL` 的 fiber 并用 `coalesce(dispose_requested_at,...)` 保留首次请求时间；mixed-history dispose 负例保留旧 `dispose_requested_at`/`disposed_at`，只给 fresh fiber 落时间戳。
5. **P2 cross-fiber test**：P2 负例补齐合法 `episode_begun` event 与 successor，断言 `invalid_outcome`/`p1_context`，并保留 episode DML sentinel 证明零写。

新增 CDP2-K 负例：六种 event 的 null/type、invalid successor、512 fibers + 1 episode 的 513 closure、mixed-history dispose 时间戳。

CDP2-K 使用一次性 `TestDB` 并在 probe DB 内替换解释器；真实 `advance`、`validate_delta`、`validate_domain`、`validate_and_apply_delta`、trigger 与锁图均执行。生产 `interpret_command`/`interpret_settlement` 对 spec-valid lifecycle payload 仍为 `0A000`。

**预算与冻结（W1 历史，W2 已更新）**：W1 结束时 `40_advance.sql` 1196/1200（余 4 行）、`30_triggers.sql` 194 行、DDL 前缀 360/900、manifest 十五文件；W1 的 review 修复增加 event payload 校验、successor 预检、closure 上界与 dispose 时间戳保护，留下 4 行。该余量促成 W2 layout 裁决。W2 后实测：`40_advance.sql` 1119/1200、`41_lifecycle.sql` 586、`30_triggers.sql` 248、DDL 前缀 414/900、manifest 十六文件。十二个 `v24/sql/*.sql` SHA-256 与 DP1 P0 表逐项相同；`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1..s12` 退出 0 且无输出。

**W1 边界**：W1 时 W2 的 ownerful/child-scope install 与 resolver、W3 的完整 P0–P4 生产激活、W4 的生产 dispose、W5 closeout 均未实现；W2 现已在 §6「W2 证据」实现，W3/W4/W5 仍未实现。`effects_one_reconcile` 仍限制每 fiber 一个 ready/claimed reconcile，故 `validate_delta` 只允许 `command_reconcile` successor 使用 ordinal 0；16 successor 结构上限主要覆盖其他 kind。continuation 仍要求与创建者同一 LOGIN；P1/P2 unsupported 失败后 child 保持 ready 且无 request，可同一 child 重试一次。Oracle 审查：W1 full bounded Oracle review 已完成，五项发现即上述 P1.1–P1.4/P2 并全部修复；早期 focused chat 另确认 parent-fiber predicate、terminal guard 的 ready→succeeded/terminal 拒绝，terminal guard 的 attempt/fence 顺序由该 chat 指出并修复，CDP1-D 增加双向负例。此前 full-file review 请求在配置的 xhigh Oracle model 上超时；该 timeout 只说明 full-file 尝试未完成，不否定 W1 bounded review 已完成，也不冒充完整 full-file review。

**发布状态**：W1 已按 2026-10-26 用户授权单独 commit `50affb0` 并 push `origin/v24`，推送前后 `origin/v24...v24` 为 `0 0`。W2 已按用户 layout 裁决实现；one bounded Oracle review 已完成，六项发现全部修复，19 条 post-fix gate 全部 `EXIT 0`；按 2026-10-26 授权，W2 在本轮收尾单独 commit 并 push `origin/v24`；提交 hash 记录在最终报告。W3 已在 §6「W3 证据」实现并按授权收尾；W4 未开始。

### W2 证据（2026-10-26 已实现；bounded review 完成；按授权提交收尾）

**范围与布局**：W2 只实现 install declaration、contracts/check、root/existing/child scope admission、owner ledger、unique-root / final-state DAG / committed-view guard 与 resolver。用户 2026-10-26 的 layout 裁决落在 `v24/cordis/sql/41_lifecycle.sql`（586 物理行），置于 `40_advance.sql` 与 `50_permissions.sql` 之间；`40_advance.sql` 只保留 3 行 command entry seam，实测 1119/1200；DDL 前缀 `10`–`17`/`20`/`30` 实测 414/900（`30_triggers.sql` 248）；canonical manifest 十六文件；十五张表及列/枚举/扩展不变。未修改 `v24/load.py`、`v24/sql/**`、`v24/s1`–`v24/s12`。

**CDP2-I**：新增 `v24/cordis/dp2/test_install.py`，本轮 `uv run python v24/cordis/dp2/test_install.py` 退出 0。覆盖 I1 direct root install 为纯数据、replay 逐字节相同、second ownerless root 拒绝；I2 ownerless install 到 existing open scope；I3 owner ledger seq/descriptor/inverse/progress、scope/owner/UUID/identity/0A000 负例，以及 uppercase UUID canonicalization、owner iterator 的 numeric `v`/exact keys、current-generation failure 拒绝；I4 declaration/contracts/check 四种 replay 组合与 malformed shape 零写；I5 nearest realm override、root default、无跨 realm fallback、provider admission、256-key 边界与 NULL key；I5b closed ancestor 使整条 resolver chain unavailable；I5c ancestor 的 `dispose_requested_at` 同时关闭 child admission 与 descendant resolution；I6 unique root、pin/run DAG cycle、committed-view immutable；I6b disposed ownerless root 仍占 unique root；I6c 19-fiber dense DAG 不再因 path multiplicity 被误拒；I7 forged install delta 的 context/ledger/event/successor 校验，install-owner mutation 命中 `install_create`。active-owner fixture 仅为维护 DML，不计入 CDP2-A 激活证据；生产 P0–P4 与 dispose 仍 `0A000`。

**19 条 gate（串行，真实退出码）**：

| # | Command | Exit |
|---:|---|---:|
| 1 | `uv run python v24/cordis/load.py` | 0 |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 |
| 8 | `uv run python v24/load.py` | 0 |
| 9 | `uv run python v24/s1/setup_db.py --self-check` | 0 |
| 10 | `uv run python v24/s1/test_ddl.py` | 0 |
| 11 | `uv run python v24/s1/test_g1.py` | 0 |
| 12 | `uv run python v24/s2/test_g3a.py` | 0 |
| 13 | `uv run python v24/s3/test_g2.py` | 0 |
| 14 | `uv run python v24/s4/test_g2b.py` | 0 |
| 15 | `uv run python v24/s5/test_g4.py` | 0 |
| 16 | `uv run python v24/s6/test_g5.py` | 0 |
| 17 | `uv run python v24/s8/test_g7.py` | 0 |
| 18 | `uv run python v24/s7/test_g6.py` | 0 |
| 19 | `uv run python v24/s9/test_g8.py` | 0 |

**冻结证据**：十二个 `v24/sql/*.sql` SHA-256 与 DP1 P0 表逐项相同；`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 … v24/s12` 退出 0 且无输出。

**Review 状态（已完成，六项修复）**：2026-10-26 的 one bounded Oracle review（两个 lane）已完成，确认并修复六项发现：① `install_delta`/`validate_install_domain` 的 caller UUID 文本大小写与 canonical UUID 比较不一致，改为 canonical UUID/JSON UUID 比较并新增 uppercase regression；② `fiber_lineage_open` 遗漏 `dispose_requested_at`，现在每个 ancestor 都视为 closed，并新增 child-install 与 descendant-resolve 负例；③ owner iterator 仅按 `->>'v'` 接受 numeric/string 且允许额外键，现要求 exact `{v,next_index,registered_through,control_seq}` 且 `v` 为 numeric `1`；④ owner admission 未拒绝 current-generation `failure`，现以 `owner_closing`/`install_owner_failure` 拒绝；⑤ `guard_fiber_graph` 的 `UNION ALL` path enumeration 可误拒 dense DAG，现改为去重 `(root,node,depth)` reachability、按 distinct graph elements 限流并保留 multiple-root/cycle/depth 检查，新增 19-fiber dense DAG regression；⑥ forged test 的 install-owner mutation 改为定位 `install_create`。六项均有 CDP2-I 覆盖，post-fix 19 条 gate 全部 `EXIT 0`。

**W2 边界（历史）**：W2 结项时生产 P0–P4 与 dispose 仍 `0A000`。W3 现已实现生产激活。

### W3 证据（2026-10-26 已实现；按授权提交收尾）

**范围**：生产 `interpret_reconcile` 实现 P0 CAS/no-op、P1 冻结 ω/pins/epoch/current、P3 只读一致性、≤32 的 P2 与 P4 totality。成功路径用真实 `command_install` + `command_reconcile`，不用 owner DML 冒充激活证据。`off`/`retry` 与 dispose 仍 `0A000`。

**预算**：`40_advance.sql` 1125/1200；`41_lifecycle.sql` 1038；DDL 前缀 414/900；`30_triggers.sql` 248；manifest 十六文件；十五张表不变。未修改 `v24/load.py`、`v24/sql/**`、`v24/s1`–`v24/s12`。`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 … v24/s12` 退出 0。

**CDP2-A**：`uv run python v24/cordis/dp2/test_activation.py` 退出 0。覆盖 0/1/32/33 provides、P0 replay/no-op/stale、缺依赖后同一 ready child 重试一次、33 项第二批失败后同一 child 重试且不重复第一批、不同 realm 同 key、真实 owner 准入、committed view immutable。可达命令图不构造 pin 环；`activation_dag` 直接调用证明 cycle，child requires owner 证明不误拒。

**中间失败**：首轮串行里 `uv run python v24/cordis/dp2/test_kernel.py` 退出 1。根因是 K4/锁序 probe 仍把生产 `on`/空 manifest continuation 当成 `0A000`。改为 `off` 与非准入 manifest 仍 `0A000`。修复后该命令退出 0。失败轮不作为通过证据。

**post-fix 退出码**：Cordis loader、DP1 fixture/environment/CDP1-D/CDP1-K、CDP2-I、CDP2-A 为串行 `EXIT 0`；CDP2-K 为修复后 `EXIT 0`。v24 loader、s1 fixture/DDL/G1、s2 G3a、s3 G2、s4 G2b、s5 G4、s6 G5、s8 G7、s7 G6、s9 G8 串行全部 `EXIT 0`。

**W3 边界（历史）**：W3 结项时生产 dispose 仍 `0A000`。W4 现已实现基本 dispose。

### W4 证据（2026-10-26 已实现；按授权提交收尾）

**范围**：`interpret_dispose` 对 install 全部实例做无活义务证明后写墓碑。阻止项包括 want_on、open episode、未释放 contribution、活 pin、未结束 run、未 disposed child install、ready/claimed effect（六种 kind）以及关联 `host_io` 的 ready/claimed/unknown/succeeded/failed/cancelled。direct child install 无 host/CAS 时成功。`off`/`retry`、drift 转 closing、failure 记录仍 `0A000`。

**预算**：`40_advance.sql` 1130/1200；`41_lifecycle.sql` 1097；DDL 前缀 414/900；manifest 十六文件；十张表；仅 `advance` 为 DEFINER。冻结 diff 退出 0。

**CDP2-B**：`uv run python v24/cordis/dp2/test_boundaries.py` 退出 0。

**退出码**：Cordis loader、DP1 fixture/environment/CDP1-D/CDP1-K、CDP2-K/I/A/B 串行全部 `EXIT 0`。v24 loader、s1 fixture/DDL/G1、s2 G3a、s3 G2、s4 G2b、s5 G4、s6 G5、s8 G7、s7 G6、s9 G8 串行全部 `EXIT 0`。

**W4 边界**：不关闭 scope、不释放 contribution、不执行 inverse、不写 closing/divert/error。已激活且仍有 open episode 或未释放 contribution 的 fiber 不能 basic dispose。settlement 仍 `0A000`。

### W5 证据（2026-10-26 closeout；HEAD `d5fd1bc` 之上重跑）

重跑时本地与 `origin/v24` 均为 `d5fd1bc`。21 条命令串行全部 `EXIT 0`：Cordis loader、DP1 fixture/environment/CDP1-D/CDP1-K、CDP2-K/I/A/B、v24 loader、s1 fixture/DDL/G1、s2 G3a、s3 G2、s4 G2b、s5 G4、s6 G5、s8 G7、s7 G6、s9 G8。`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 … v24/s12` 退出 0。预算：`40_advance.sql` 1130/1200，`41_lifecycle.sql` 1097，DDL 前缀 414/900，manifest 十六文件，十张表，仅 `advance` DEFINER。

**仍未覆盖**：`off`/`retry`；drift 不转 closing，不写 failure，不自动 retry；leave/unload、withdraw/release、inverse 执行；closing/divert/error 不是 DP2 成功状态；`interpret_settlement` 仍 `0A000`；`barrier_ready` 仍为 `true` 接缝；已激活且有 open episode 或未释放 contribution 的实例不能 basic dispose；direct install 不取得 CAS；continuation 仍限 originating LOGIN；多 entity 事件流留 DP5。可达命令图不构造 pin 环，cycle 由 `activation_dag` 直接调用证明。


## 7. Open Questions

**发布分支与 push 目标：已由用户裁决。** 2026-10-26 用户明确授权本计划按里程碑逐个 commit 并 push 到 `origin/v24`。这是发布授权，不是对规格或代码的改动：发布授权（2026-10-26）：用户明确授权本 DP2 计划按里程碑逐个 commit 并 push 到 `origin/v24`；这是针对本工作任务的具体授权，不改写根与 worktree `AGENTS.md` 的 `origin main` 规则，也不切换用户工作树或改写历史。 指定 worktree 为 `v24` 并跟踪 `origin/v24`，与该授权一致。B0 已按此授权结项（证据见 §6）；W1–W5 沿用同一目标，仍不可越过“本里程碑必须完成推送才进入下一里程碑”的纪律，也不得自行改推 `main`、切换用户工作树或改写历史。

其余工程选择已由代码、DP1 分工或 Oracle 裁决确定。§5 标注的四项范围/兼容性/部署假设可由用户覆盖；跨 LOGIN scanner、真正 host/CAS lifecycle 和多 entity 通知须在对应后续阶段重新确认，不能从 DP2 绿色推断它们已实现。B0 已结项（本地验证 + 提交 + 推送 `origin/v24`）；W1 已结项（commit `50affb0`，已推送 `origin/v24`），五项 bounded Oracle review 发现全部修复、最终 18 条 gate 全绿；W2 已结项（commit `1a7deaa`）；W3 已实现，CDP2-A 与 post-fix 门禁 `EXIT 0`，按授权在本轮收尾 commit/push；W4 未开始，W5 随后。每个里程碑完成后同样逐项提交推送，不把相邻里程碑合并成一次提交。

## 8. References

以下行号均基于本次只读核验的 v24 worktree；未来实现改变行号后按符号定位，不以历史行号代替当前源码。

- `docs/designs/cordis-plugin-system-2026-10-25.md:159`：advance ABI；`:239`：承重列；`:320`：O-Insert/O-Remove；`:334`：P0–P6；`:475`：Preservation；`:629`：artifact/host preparation。
- `docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:188`：host claim/replay 合同；`:200`：角色模型；`:206`：DP1–DP6 边界和 fail-closed 裁决。
- `v24/cordis/dp1/README.md:5`；`docs/reviews/cordis-v2-dp1-conformance-matrix-2026-10-25.md:80`；`docs/reviews/cordis-v2-dp1-deviation-ledger-2026-10-25.md:27`：DP1 历史验收与冻结证据。
- `v24/cordis/sql/40_advance.sql:150`：解释器/validator；`:204`：applier；`:279`：command replay；`:311`：host claim 的 contracts.host_io 绑定。
- `v24/cordis/sql/30_triggers.sql:58`：当前 effect immutable guard；`v24/cordis/sql/17_effects.sql:26`：in-flight partial unique indexes；`v24/cordis/sql/14_contributions.sql:11`：inverse JSON object；`v24/cordis/sql/18_events.sql:1`：单 entity event 数据结构。
- `v24/cordis/dp1/setup_db.py:137`：TestDB 和 random role family；`v24/cordis/dp1/test_ddl.py:29`：十表 snapshot；`:73`：旧 seed；`v24/cordis/dp1/test_kernel.py:16`：fixture 导入；`:71`：host_seed。
- `docs/plans/v24-s1-kernel-2026-10-23.md`：执行索引、写类和 gate 证据结构先例。
- `v24/sql/45_capability.sql`、`v24/sql/40_interpreters.sql`：仅作 resolver/check/activation 行为先例，不调用或修改冻结函数。
- `docs/reviews/v24-cordis-dp2-lifecycle-plan-critique-2026-10-26.md`：一次有界评审、八项发现与支持保留的范围收窄。
- `AGENTS.md:7`、`:50`：独立里程碑纪律及发布目标冲突。

## 9. Preservation audit

2026-10-26 已完成对 context_builder 导出生成正文的保真核验；不把前置 prompt/context echo 当计划。本表仅记录可追溯的覆盖与修正，所有 implementation gate 仍为**未运行**。

| baseline 实施内容 | 最终落点 / 核验结果 |
|---|---|
| Summary、成功范围、历史证据与冻结基线 | §1–2；补齐 DP1 四个提交及实际接缝 refs，历史通过不作为本轮结果 |
| 执行索引、合同映射、签名/权限、字段和 body 限制 | §3.1–3.4；保留全部合同，新增 Size；基线 P0 改名 B0 避免与 lifecycle P0 混淆 |
| reserved child identity、actor/input/binding、无预写 request、replay-first、I7 写序 | §3.5；完整保留并补精确错误、P1 generation、失败后重交与 LOGIN 丢失边界 |
| install/scope/owner、manifest/contracts、child inverse/seq、重复安装 | §3.6；完整保留，补 unique-root guard 和 W2 spec-valid active-owner fixture |
| 递归 resolve、realm、provider closure、digest、equals/null check | §3.7；完整保留；原“十列”纠正为实际九列 |
| P0–P4、ω、iterator、epoch、pin、32批量、totality、跨事务前缀 | §3.8；完整保留；删除成功 off/retry 因超出 DP1 的成功激活分工，两者具名 `0A000` 负例保留 |
| closure 锁序、512/513、联合 DAG、confinement | §3.9；完整保留，明确 final-state guard/错误和维护 G 锁纪律 |
| tagged delta、写序、emitted、非 command 无领域写权 | §3.10；完整保留，补 exact keys、null/类型、inverse/pin 形状、UUID 来源、install-wide dispose 授权 |
| 事件名单、seq、replay 不重复 | §3.10、CDP2-K8；用一条精确聚合事件替代无依据的64上限/多行设计，保留每阶段信息与验证；明确多 entity stream 覆盖后置，Oracle 假设见 §5 |
| replay 权利 | §3.6、§5；替换“所有 provided 能力都必须两权利为true”，因 DP1 只对 host reclaim 施加该条件且 DP2 无外部执行；四组合与原 host binding 测试均保留 |
| 准备模式与 host/CAS 义务 | §3.6、§3.11；替换无字段可构造的“需准备请求”与无存储来源的通用 CAS 检查：direct install 不取 ref、未知字段 invalid_args、任意关联 host_io 状态阻止 dispose |
| basic dispose、保留历史、错误闭集/W0、0A000 全回滚 | §3.11–3.12；完整保留并补多实例/跨 install 权限和六种 host status 断言 |
| 具名 gates、强制负例、并发/异常注入、DP1 gate 维护 | §3.13；baseline 各项均保留或以上述具名替代验证，补 terminal guard/root/fixture/事件/重交负例 |
| 五条DP1、四条DP2、十一条v24、单列s9、hash/diff、收尾工件 | §3.14；命令与回归顺序保留；所有既有脚本路径已检查存在，DP2 路径明确为待新建 |
| file impact、不改目录、迁移/回退、风险、裁决、引用、实施顺序与逐里程碑发布 | §4–8；完整保留，receipt guard 提前 W1；发布目标原列为唯一发布问题，2026-10-26 已由用户裁决为逐里程碑 push `origin/v24` |

baseline 中的 generic narration、重复表述、tool wrapper、末尾会话提示和多余代码围栏未纳入最终计划；其余受支持的实施事实、理由、约束与验证要求已逐项保留或按上表证据修正。

保真核验完成后已尝试清理原始导出；RepoPrompt 对该导出的物理删除返回 `Protected physical mutation is unsupported`，因此未绕过保护，保留该 ignored 临时工件。它不是实施输入的额外权威，执行以本文和设计/当前代码为准。
