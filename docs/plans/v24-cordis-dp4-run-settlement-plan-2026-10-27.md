# Cordis v2 DP4：run 结算与 model/tool 回路 Deep Plan

> 本文是 DP4 的实施计划；已交付事实以 §8 各阶段 result 为准。相对路径均以 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` 为根，main checkout 不含 Cordis 实现。规划时 HEAD 为 `4b34bf2`（DP3 W5 closeout）；动手前必须重测 HEAD 并写入 matrix。

## 1. Goal 与完成边界

在已完成 DP1/DP2/DP3 的 Cordis v2 内核上，交付生产级 run 生命周期：`run_start`/`model_call`/`tool_call` 三类 effect 的生产创建、claim 与外呼后结算，受限只读 `chat_tool` reducer，run pin 绑定与使用，步数预算，终止状态与封口。使设计稿 §5.3 的 e7→e13 走查可经真实 `advance` 闭环跑通，且 DP1/DP2/DP3 的 26 条既有 gate 不回退。

**Done when**：DP4 五个新 gate（`CDP4-R/M/T/X/B`）与 DP3 收尾的 26 条命令串行全绿；e7→e13 走查有生产证据；`host_io`/`dispatch`/`listener_call` 仍保守拒绝；helper `40–49` 合计 ≤5000、DDL ≤900、manifest 18、十表、唯一 `SECURITY DEFINER` 仍是 `advance`；十二份冻结 SQL hash 不变；README/matrix/ledger 与本文 result 已回填。

**明确不做**（DP5/DP6 或设计稿 §12.3）：listener 注册与 dispatch、intercept/overlay、宿主公平扫描、崩溃矩阵全量恢复、unknown 外部对账、upgrade/HMR、cancel/steer/respond 六动词、多宿主、spawn/child run（`parent_run_id`/`spawn_key` 保持 NULL）、interaction 应答通道。

## 2. Current-state analysis

### 2.1 权威、基线与完成事实

唯一产品规格是 `docs/designs/cordis-plugin-system-2026-10-25.md`。DP4 的范围由 DP1 计划的分工表固定：`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:206-219` 的 DP4 行 =「run 创建与推进、`chat_tool` reducer、model/tool settlement、pin 使用、预算与终止状态」；DP5 才有 listener/dispatch/intercept/overlay，DP6 才有扫描器、崩溃矩阵与 unknown 对账。设计稿 `:765` 的切片 S4 与 `:751`/`:753` 的 G1/G3 是 DP4 的验收来源。

DP1/DP2/DP3 全部交付并已推送 `origin/v24`：DP2 收尾 `d5fd1bc`，DP3 B0 `ba4f533`、W1 `103ec596`、W2 `72af2528`、W3 `284d7f2`、W4 `f6a3a74`、W5 `4b34bf2`（`v24/cordis/dp3/README.md`「当前状态」）。DP3 收尾的未交付清单明确列出 settlement、run 生产 writer、scanner/fairness、外部恢复与 dispatch 面（`docs/reviews/cordis-v2-dp3-deviation-ledger-2026-10-27.md` Final unclaimed scope）。

现容量（DP3 W5 实测）：`40_advance.sql`=1373、`41_lifecycle.sql`=1211、`42_teardown.sql`=966，合计 **3550≤5000**；DDL 前缀 **461≤900**；manifest **17**；十表；唯一 `SECURITY DEFINER` = `advance`；public function EXECUTE 0；源码 VIEW/EXTENSION 0。DP4 在 5000 总预算内可用余量 **1450 行**。

DP3 留下的硬约束：`run_pin_release_delta` 只消费可信 terminal DB 事实（owner/episode 对齐、`ended_at` 非空、无 `host_io`、无 `ready/claimed/unknown` effect），DP4 的 terminal settlement 必须在同事务复用同一规则（`docs/plans/v24-cordis-dp3-teardown-plan-2026-10-27.md:194`）。DP3 的 `host_io` `0A000`、无 scanner、`run_pin_release_delta` 只读三条断言必须**保留**；只有「无 SQL 写 `runs`」与「settlement 仍 `0A000`」两条被生产证据替换（`v24/cordis/dp3/test_boundaries.py:239-283`）。

### 2.2 当前调用链与接缝

`advance(uuid,jsonb)` 是唯一提交口：预检信封 → `G=(24,1)` → `role_allowed` 预检（kind 用 `coalesce(kind,'host_io')`）→ 读 effect `FOR UPDATE` → 二次 `role_allowed` → 终态 replay → `discover_closure`/`lock_closure`/闭包重读 → claim 或 `interpret_settlement`/`interpret_command` → `validate_and_apply_delta`（`40_advance.sql:1201-1344`）。

| 接缝 | 现状（file:line） |
|---|---|
| `runs` DDL | `16_runs.sql:1-13`：owner/episode/scope NOT NULL、`parent_run_id`/`spawn_key`、`state jsonb`（仅 object，无字节上界）、`remaining_steps int>=0`、`ended_at`、`result`；`runs_spawn_slot` 唯一索引。identity/ownership 与 `ended_at` 墓碑由 `30_triggers.sql:56-63` 冻结。 |
| `pins` DDL | `15_pins.sql:1-15`：**无 `provider_episode_id` 列**；consumer fiber XOR run；`pins_run_active=UNIQUE(consumer_run_id,key) WHERE released_at IS NULL`（`:15`）。设计附录 A 的草案列未随 DP1 落地。 |
| `effects` DDL | `17_effects.sql:1-27`：kind 闭集已含 `model_call/tool_call/run_start`；六态；`attempt/fence/lease_until`；outcome/settled_at 真值表；`UNIQUE(parent_id,ordinal)`；`effects_one_model_inflight(run_id)`。**无 `token uuid`、无 `resource_quiesced_at`**。 |
| settlement | `40_advance.sql:401-403` `interpret_settlement` 直接 `RAISE ... 0A000`；非 command 结算都路由到它（`:1344`）。 |
| ACL | `40_advance.sql:147-163` service 分支写死 `p_kind='host_io'`；`alias='service'` 嵌在 `FOREACH` 内且 `pg_auth_members` 计数恰为 1，admin/operator 永远进不到该分支。 |
| claim | `40_advance.sql:1314-1339` 从 owner install 读 `contracts->'host_io'`；binding 逐字节相等；reclaim 要求 `replay.repeat/concurrent` 双真；`barrier_ready` 恒 true（`:252-253`）；attempt/fence+1。 |
| 后继 | `40_advance.sql:430-448` 结构白名单含三个 run kind，但无 input 约束；`:1175-1190` applier 对非 `command_reconcile` 抛 `0A000`；`successor_effect_id` 硬编码 `command_reconcile`（`:259-263`）。 |
| delta op | `40_advance.sql:449-664` 17 个 domain op，无 run/pin bind/model/tool op；`:667-670` 对 settlement 强制空 domain/successors。 |
| 校验器 | `validate_domain` **开头**（`:689-696`）拒绝任何 kind ≠ `command_reconcile` 的后继；p4 分支（`:961-963`）要求 successors 为空。二者都必须为 p4 的 `run_start` 开窄口。 |
| 闭包 | `discover_closure`/`target_refs`（`:185-249`）只沿正向列边；`pins→runs` 是反向边，run 的 pins 不可达。`delta_write_closure_ok`（`42:5-40`）缺 `('run_id','runs')` 配对。 |
| 后置条件 | `assert_delta_applied`（`42:41-157`）的 `CASE ... ELSE NULL` 对未知 op 静默放行（`:150`）——5 个新 op 不补 `WHEN` 就等于没有后置证明。 |
| run pin 释放 | `pins_release` applier（`40:1100-1115`）的 run 分支要求该 run 上无 `host_io/ready/claimed/unknown` effect；**结算时本 effect 仍是 `claimed` 且带 `run_id`，会自阻塞**，必须追加 `x.id IS DISTINCT FROM p_effect_id`。 |
| 读通道 | `50_permissions.sql:7-16` 只给协议角色 schema USAGE + `advance` EXECUTE，**无表 SELECT**；claim 响应（`40:1336-1339`）只回 `claim` 三元，不回 effect `input`。DP4 必须让 claim 响应携带冻结的 `input`，并由宿主维护 `emitted` 日志；否则 service 无法取得 prompt/args。 |
| pin 可读 | `pin_readable`（`42:359-366`）只要求 `released_at IS NULL` 与 epoch 相等，**不要求 `withdrawn_at IS NULL`**；与 `resolve`（`41:543-602`）分叉，正好支撑 e10/e13「旧 run 用旧 pin」。 |
| p4 生产者 | p4 的 delta 在 `41_lifecycle.sql:1039-1043` 构造，且该分支要求 `ep.state='reloading'`（`:1002-1004`）、随后才 apply `episode_activate`。因此 `run_start_successor` **只能在 reloading + activation_total 满足时发后继**，不能要求 `active`；`active` 检查属于结算时。改 41 不可避免。 |
| reducer | `v24/cordis` 无 reducer / `chat_tool`；`policy_ref='"chat_tool"'` 是 install 唯一非 null 值（`41:125`）；`installs.contracts` 已强制每 capability `{contract_version,handler_digest,replay:{repeat,concurrent}}`（`41:42-53`）。 |
| 测试断言 | `dp1/test_kernel.py:307-309` 断言三个 run kind 对 service 返回 `unauthorized`——W1 与 ACL 改动同里程碑替换（B0 保留，以维持旧 gate 绿）。`dp3/test_boundaries.py:239-283` 断言 settlement 为 `0A000`、源码无 run DML、无 scanner——前两条按 §3.10 替换，第三条保留。 |

### 2.3 固定合同、预算与证明边界

保持 I1–I8、same LOGIN continuation、replay-first、24 错误码闭集、`revision=0`、body ≤1MiB、递归键 ≤200、closure ≤512、successor ≤16、B=16、十表、仅一个 `SECURITY DEFINER`。不新增命令 kind（仍 3 类）、不新增公开 writer、不建第二调度器、不复活六动词。

约束边界：
- 外部 IO 只在 claim 已 COMMIT 且连接 IDLE 后进行；`advance` 不持锁跨 IO。
- `run_start` 是 DB-only 步骤（无外呼），但仍走 claim/settle 以复用 fence/replay/所有权；因此它**不接受 `unknown`**（见 §3.9）。
- 设计稿 §12.2 的债务继续有效：模型重复计费、外部 exactly-once、`unknown` 外部资源复原不可验证、E1/E2 由宿主提供。
- 冻结：`v24/load.py`、`v24/sql/**`、`v24/s1`–`s12` 十二份 SQL 不得改动；设计稿只读。

## 3. Design

### 3.1 执行索引

| # | 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|---|
| B0 | 基线与脚手架 | 固定 HEAD；注册 18 号 manifest；四文件预算证明 | 26 条旧 gate 全 exit 0；四文件恰好 5000 通过/5001 拒绝 | `load.py`、`helper_budget.py`、`dp1/test_kernel.py`、`dp2/test_boundaries.py`、`dp3/test_boundaries.py`、空 `43_loop.sql`、DP4 计划/matrix | 无 | M |
| W1 | `run_start` 生产与绑定 | p4 发 `run_start`；claim 合同主体改为 provider；`run_create`/`run_pin_bind`/`run_refused`；闭包种子；后继身份泛化 | `CDP4-R` 绿；真实 P0–P4→run_start→run/pins/model_call；拒启与伪造后继零写 | 43、40、41、42、`dp4/test_run.py` | B0 | L |
| W2 | model 结算与 reducer | 纯 reducer、三摘要、model receipt、`run_state`/`run_budget`、tool 后继、`already_terminal` | `CDP4-M` 绿；e8 budget 3→2；摘要漂移/非法 intent/超限零写；三处注入回滚无部分提交 | 43、40、42、`dp4/test_reducer.py` | W1 | L |
| W3 | tool 结算与批次屏障 | tool receipt、pin/key/liveness、sibling 事实查询、唯一 continuation、unknown 兄弟结算 | `CDP4-T` 绿；N 工具全结算才续；双连接竞态仅一个 continuation；withdrawn pin 仍可读、released pin 拒结算 | 43、40、42、`dp4/test_loop.py` | W2 | L |
| W4 | 预算与终止 | `run_seal`、final/budget/model_failed 三终局、pin 释放、current-effect 排除 | `CDP4-X` 绿；e7→e13 闭环；unknown 不封口且阻塞 P6；封口后结算零写 | 43、40、42、`dp4/test_boundaries.py` | W3 | L |
| W5 | 收尾 | 全量串行 gate、工件、冻结与预算核验 | 26 条旧命令 + `CDP4-R/M/T/X/B` 全 exit 0；十二份冻结 hash 不变；README/matrix/ledger/本文 result 完整 | 全部 + docs | W4 | M |

每项必须把 writer、validator、guard、对应测试作为同一里程碑原子落地；不得把多个里程碑压进一次提交。

### 3.2 模块与接口

**新增 `v24/cordis/sql/43_loop.sql`**（≤560 物理行，插在 `42_teardown.sql` 之后、`50_permissions.sql` 之前）。设计稿的三个 run 解释器合并为一个 `run_delta` planner 的三个分支，不新增第四张表/调度器；这是为 5000 行预算做的无损合并，CDP4-B 用行为测试而非函数个数证明覆盖。全部是 `SECURITY INVOKER` 私有函数，显式 `search_path`。

| 函数 | 形态 | 职责 |
|---|---|---|
| `run_policy()` | SQL IMMUTABLE → jsonb | 唯一数值出处：`{v:1,max_steps:64,max_state_bytes:65536,max_tool_calls:16,max_successors:16,max_run_pins:32}` |
| `chat_tool_schema()` | SQL IMMUTABLE → jsonb | `{v:1,name:'chat_tool_v1',fields:['text','tool_calls','interaction','final','usage']}` |
| `run_digests_of(p_pins jsonb)` | SQL IMMUTABLE | 输入 `[{key,descriptor_digest}]`（按 key 排序），输出 `{policy,schema,toolset}` 三 sha256 hex |
| `run_digests(p_run uuid)` | SQL STABLE | 从 live run pins join contributions 现算 descriptor digests，再调 `run_digests_of` |
| `run_id_for(p_effect uuid)` / `run_pin_id_for(p_run uuid,p_key text)` | SQL IMMUTABLE | 私有命名空间确定性 uuid，供规划器精确复算 |
| `run_state_valid(p_state jsonb)` | SQL IMMUTABLE | 六键/phase/batch/final/字节界的最小校验 |
| `run_start_receipt_valid` / `model_receipt_valid` / `tool_receipt_valid` | SQL IMMUTABLE | 各 receipt 的 exact-keys 与 class/status 配对 |
| `claim_contract(p_eff effects)` | plpgsql STABLE | `host_io`/`run_start` 读 owner install；`model_call`/`tool_call` 沿 `input.pin_id`→contribution→provider install 读 capability 合同 |
| `run_start_successor(p_fiber uuid)` | plpgsql STABLE → jsonb | 满足条件返回一条 ordinal 0 的 `run_start`，否则 `[]` |
| `reduce_chat_tool(p_state,p_fact)` | SQL IMMUTABLE STRICT `BEGIN ATOMIC` | 纯变换 `{v,state,intents}`；无表、无 IO、无动态 SQL、无 `RAISE` |
| `run_delta(p_effect,p_outcome)` | plpgsql STABLE | 设计稿的三个 run 解释器（`run_start`/`model`/`tool`）在这里按 `eff.kind` 三分支实现，共用一个 planner；读 DB 事实、调 reducer、翻译成四键 delta 或错误 JSON |
| `validate_run_domain(...)` | plpgsql STABLE → jsonb\|NULL | 独立重算 `run_delta` 与全部不变量，拒绝伪造 interpreter |
| `settlement_seed(p_effect uuid)` | plpgsql STABLE | 非 run kind 逐字节等价旧种子；三个 run kind 扩张 provider/run/pins |

**`40_advance.sql`（+≤270 行，只加路由与 plumbing）**
- `interpret_settlement` 白名单 `CASE`：三个 run kind → `43` 的规划器；`host_io`/`dispatch`/`listener_call` 仍 `0A000`。
- `role_allowed`：service kind 扩为 `host_io/run_start/model_call/tool_call`；**保留** `host_io` 与 alias 机制。
- claim 的合同读取改调 `claim_contract`（不再只看 `host_io`）。
- `validate_delta(p_delta,p_class,p_structure_only,p_kind DEFAULT NULL)`：run 结算类才放行 domain/successors；三个 run kind 的 successor input 精确形状；5 个新 op 分支；`run_progress`/`run_refused` 事件分支。
- `validate_domain`：开头后继循环放行 `run_start`；分支判定后加「非 p4 出现非 reconcile kind 即 `invalid_outcome`」；p4 的 successors 与 `run_start_successor(f)` 精确相等。
- `validate_and_apply_delta`：按 `p_kind` 路由到 `validate_run_domain`；顺序数组插入 5 op；后继 applier 增三个 run kind；`v_emitted` 收全部后继 id；非 RUN 分支的闭包种子改用 `settlement_seed`。
- `successor_effect_id` 增 `p_kind text DEFAULT 'command_reconcile'`；`successor_request_key` **保持不变**（`requests` 行只在 command 路径插入，`40:1155-1166`；后继只插 effects，`40:1178-1185`，不存在 request_key 撞键）。`effect_id_for` 已把 kind 混入哈希（`40:6`），三参调用点行为不变。
- claim 响应（`40:1336-1339`）增加 `input` 字段（冻结的 `effects.input`），不新增 public writer；宿主以每次 advance 返回的 `emitted` 维护本地日志（effect id/kind/args），这是 DP4 唯一读通道。崩溃后重新发现 ready effect 属 DP6 scanner。

**`41_lifecycle.sql`（+≤25 行）**：p4 的 `episode_activate` delta 的 successors 从 `'[]'` 改为 `run_start_successor(f.id)`；不得在 p4 直接写 run/pins。

**`42_teardown.sql`（+≤65 行）**：`delta_write_closure_ok` 增 `('run_id','runs')`、`run_pin_bind.pins[].contribution_id`/`provider_episode_id`；`assert_delta_applied` 增 5 个 `WHEN`；**不改** `run_pin_release_delta` 与 `p6_plan`。

**`16_runs.sql`（+1 行）**：`state` CHECK 追加 `AND octet_length(state::text)<=65536`。

### 3.3 闭包缺口与 `settlement_seed`

`discover_closure` 只沿正向边，run 的 pins 不可达；`run_start` 到不了 `committed_view` 的 provider。因此以 `p_effect_id` 为种子时，必须为三个 run kind 扩张：

```text
seed := [{t:effects,id}]
eff 缺失或 kind ∉ {run_start,model_call,tool_call} → 原样返回          -- host_io/dispatch/listener 逐字节不变
kind=run_start: 只取 run_start_successor 选中的 model/tool 绑定（≤32，不是整个 committed_view）:
    ∀ (k,v) ∈ 该过滤集: seed += {contributions,v.contribution_id}, {fibers,v.provider_fiber_id}, {episodes,v.provider_episode_id}
eff.run_id 非空:
    seed += {runs,run_id}
    ∀ live pin p (consumer_run_id=run_id, released_at IS NULL):
        seed += {pins,p.id}, {contributions,p.contribution_id}, {episodes,c.episode_id}
return 去重 + 按 (t,id) 排序
```

实现约束：
- 去重必须用 `SELECT DISTINCT` 子查询（`jsonb_agg(DISTINCT x ORDER BY x->>'t')` 在 PostgreSQL 会报错）；变量名不用 `out`（PL/pgSQL 参数模式关键字）。
- 锁后重比对必须**重算** `settlement_seed(p_effect_id)`，不能复用旧种子；pin 集在锁前后变化即 `retry_with_closure` 零写。
- 上界：run(1)+pins(≤32)+contributions(≤32)+provider episodes(≤32)+effect(1)+owner 链(≈6) ≈ 104，远低于 512。`manifest.requires` 允许 256 项（`41:58-62`），但 `run_start` 只 seed 过滤后的 model/tool 绑定；CDP4-B 用「256 个无关 requires + 32 个 model/tool」实测不越过 512。
- 非 run kind 的种子必须与 DP3 逐字节相同，否则 CDP1-K 的 512/513 与 CDP3-B7 的 600 历史 effect 断言会翻转。

### 3.4 `run_start`：生产、claim 与结算

**生产者（p4）**。`run_start_successor(f)` 仅在下列全真时返回一条 `{ordinal:0,kind:'run_start',input:{v,fiber_id,episode_id,contract}}`，否则 `[]`：
- `installs.policy_ref='chat_tool'`；
- owner install 的 `contracts` 含形状合法的 `run_start`（owner 只需声明它；`model_call`/`tool_call` 的合同属于 provider，按计划 pin 逐个校验，不要求 owner 声明）；
- `committed_view` 中 `capability='model_call'` 恰好 1 个，`capability ∈ {model_call,tool_call}` 总数 ≤32，且每个 pin 的 provider 合同 capability 与 effect kind 一致；
- 当前 episode 是该 fiber 的 current、`state='reloading'`、`activation_total(f)` 已满足（p4 随后 apply `episode_activate`），且该 episode 无 open run、无 `ready/claimed` run effect。

**不要把 `active` 放进生产者**：p4 在 `episode_activate` 之前求值（`41:1002-1004,1039-1043`），要求 `active` 会让 `run_start` 永远不产生。

p4 的 `validate_domain` 必须拒绝：两条及以上 run_start、ordinal≠0、非 `chat_tool` install 出现 run_start、`input` 键不符；伪造一律 `invalid_outcome` 零写。非 p4 分支出现任何非 `command_reconcile` 后继同样是 `invalid_outcome`。

**claim**。合同取 owner install 的 `contracts->'run_start'`；`run_start` **允许在 owner 已不 live 时 claim**，否则 ready effect 会永久阻塞 P6。

**结算**。receipt body 精确 `{v:1,request:object,steps:int}`。检查顺序固定：receipt 结构 → `failure` → owner liveness → replay 权利 → 建 run。
- `steps ∈ [1,run_policy()->>'max_steps']`；`request` 必须是 object；`runs.remaining_steps` 初始化为 `steps`。
- 请求与预算冻结在不可变的 `effects.outcome` 中；`run_start.input` 只携带 owner/episode/contract，不复制 request。
- `failure`：effect 终态 failed，不建 run，发 `run_refused{reason:'start_failed'}`。
- owner live 判定（此时 activation 已提交）：`eff.episode_id = fibers.current_episode_id` 且 `episodes.state='active'` 且 `fiber_live_resolve_ok(owner,episode)`；`P0401` → `retry_with_closure` 零写。
- owner 已不 live：按 class 映射状态终态结算（`success`→`succeeded`），**不建 run/pins/后继**，发一个 `run_refused{reason:'owner_closing'}` 事件，并在 response 返回 reason；原 receipt 原样保存在 `effects.outcome` 以支持 replay。
- **replay 权利**：仅对 `success` 检查；从每个计划 pin 的 provider `installs.contracts->capability->replay` 读，要求 `repeat && concurrent` 双真。任一 provider 不满足 → 整个 run 拒绝（不静默丢弃能力，否则 digest 承诺的 toolset 会变）：effect 按 class 映射终态结算，不建 run/pins/后继，发 `run_refused{reason:'replay_right_missing'}`，原 receipt 保留以支持 replay。这是 DP4 新增的更强检查：当前首次 claim 不查双真，只在 reclaim 时查（`40:1329-1331`）。
- owner 仍 live 且 replay 通过：`run_create`（确定性 `run_id_for(effect)`）+ `run_pin_bind`（从 `committed_view` 取 `capability ∈ {model_call,tool_call}`，≤32，pin id 用 `run_pin_id_for`）+ 一条 ordinal 0 `model_call`（`pin_id`/`key` 取唯一 model pin，`input.digests` 用 `run_digests_of(planned pins)`，`contract` 取该 pin 的 provider 合同）+ 恰一个 `run_progress`（step=0, phase='model', sealed=false）。
- `unknown`：`invalid_outcome` 零写（DB-only 步骤不存在外部不确定性），caller 需在 lease 后重领并提交 success/failure。

### 3.5 `model_call` / `tool_call` 结算与 reducer

**冻结的 successor input（exact keys）**

| kind | input |
|---|---|
| `run_start` | `{v,fiber_id,episode_id,contract}` |
| `model_call` | `{v,run_id,pin_id,key,digests,contract}` |
| `tool_call` | `{v,run_id,pin_id,key,descriptor_digest,call_id,args,contract}` |

`contract` = `{contract_version,handler_digest}`；`digests` = `{policy,schema,toolset}` 三 hex64。`model_call` 的 `run_id` 必须等于 `effects.run_id`；`tool_call` 的 `pin_id`/`key` 必须命中该 run 的活 pin。

**claim 合同主体**。`model_call`/`tool_call` 沿 `input.pin_id → pins → contributions → provider fibers → installs.contracts->(descriptor->>'capability')` 读取，且 capability 必须等于 effect kind；`host_io`/`run_start` 仍读 owner install。`contracts` 由 immutable 守卫冻结，claim 时读取不会在结算前漂移。

**receipt body**

| effect | class | body |
|---|---|---|
| `model_call` | success | `{kind:'model_call',result:{text,tool_calls,interaction,final,usage}}`（五键精确；`text` 是 string 可为空；`interaction` 必须 null；`final` 是 bool；`tool_calls` 每项 `{call_id,key,args}`、key/call_id 唯一；`usage` 为 null 或值均非负整数的对象；`final=true` 与 tool_calls 互斥） |
| `model_call` | failure | `{kind:'model_call',error:{code:text,detail?:object}}`（不回 result） |
| `tool_call` | success/failure | `{kind:'tool_call',result:{status,output,usage}}`；success 配 `ok`、failure 配 `error`、`output` object、`usage` 为 null 或 `{wall_ms:int>=0}` |
| `run_start` | success | `{v:1,request:object,steps:int}`；failure 为 `{v:1,error:{code:text}}` |
| 任意 | unknown | 只带 kind，不得携 successors/intents（advance 已有检查 `:1229`） |

**reducer**。`p_fact = {v,effect_kind,class,receipt,remaining_steps,tools:[{key,pin_id}],live_siblings:int,unknown_in_run:bool}`；`tools`/计数由 `run_delta` 从 DB 读出，reducer 不读表。输出 `{v,state,intents}`，intents 闭集 `emit_model{}`、`emit_tool{ordinal,key,call_id,args}`、`close_run{reason,text,dropped_tool_calls}`；非法输入返回哨兵，由规划器转 `invalid_outcome`。决策表：

| 事实 | 结果 |
|---|---|
| model success，`final=true`（tool_calls 必须空） | `close_run(final)` |
| model success，非 final，r'=r−1=0 | `close_run(budget_exhausted)` |
| model success，非 final，N=0 或 N>16 或 key∉tools 或 call_id 重复 | 哨兵 → `invalid_outcome` 零写 |
| 1≤N≤r' | N 个 `emit_tool`，`phase='tools'` |
| N>r'（结构合法但不可执行） | `close_run(budget_exhausted,dropped=N)`，不建部分批次 |
| model failure | `close_run(model_failed)` |
| tool success/failure，`live_siblings>0` | 只更新 step/预算，不发 intent |
| tool 结算后 `live_siblings=0` 且 `unknown_in_run` | 同上，不封口、不释放 pin |
| `live_siblings=0`，r'=0 | `close_run(budget_exhausted)` |
| `live_siblings=0`，r'>0 | `emit_model`，`phase='model'`，`batch=[]` |
| unknown | 不调 reducer；无 domain/事件/后继 |
| interaction≠null、未知键、usage 形状错、class/status 不配对 | 哨兵 → `invalid_outcome` 零写 |

**model 结算**：先拒绝已封口 run（`already_terminal`）与结构非法 receipt（`invalid_outcome` 零写）；校验 `input.digests = run_digests(run)`；预算每次 success/failure 扣 1，`run_start` 与 `unknown` 不扣；`success` 翻译 intents；`failure` 封口 `model_failed`；扣减后为负 → `budget_exceeded` 零写（正常路径不可达，作防御）。

`batch` 语义：它是**本批次原始冻结清单**，不随兄弟结算缩减。reducer 的 `p_fact` 只带 `live_siblings`，因此单兄弟结算时不试图移除当前项；只有最后一个兄弟结算且需要 continuation 时才清空 `batch`，封口时 `batch=[]`，unknown 墙导致不续时保留冻结清单。`live_siblings` 定义为「同 `parent_id`、`kind='tool_call'`、`status IN ('ready','claimed')` 且 `id IS DISTINCT FROM p_effect_id`」的计数。批次 key 在冻结时唯一；模型返回重复 key → `invalid_outcome`。

**tool 结算**：校验 `input.pin_id`/`key` 与活 pin；`pin_readable` 为真即可用（**不要求 `withdrawn_at IS NULL`**），`released_at` 非空 → `dependency_unresolved`；结算后查同 `parent_id` 的 sibling `tool_call`，任何 `ready/claimed`（含过期 lease）都不发 continuation；全部终态才发**一条** ordinal 0 `model_call`，其 parent 取当前 tool effect（避免原 model 已满 16 个 ordinal 时耗尽）；unknown 存在时不发 continuation、不封口、不释放 run pin。

**continuation 去重**：不依赖 `UNIQUE(parent_id,ordinal)`（不同 tool 的 parent 不同）。三层保证：G 串行、屏障不变量（本 tool 处于 claimed 时其批次不可能已有 continuation）、`effects_one_model_inflight` 兜底。continuation 的唯一索引冲突落在 domain 子事务之外，按 SQLSTATE `23505` 原样抛出，不得翻译成生命周期错误。

### 3.6 run 状态、预算与终止

**`runs.state` 精确六键**：

```text
{v:1, origin:uuid, step:int, phase:'model'|'tools'|'sealed', batch:[{ordinal,key,call_id}], final:bool}
```

- `origin` = 产生该 run 的 `run_start` effect id。`run_start.run_id` 恒为 NULL（effect 创建时 run 尚不存在且 `run_id` 不可变），`origin` 是 run→请求体的唯一持久链路；请求体在 `origin` 的不可变 `effects.outcome` 中。
- `batch` ≤16，`ordinal`/`call_id` 唯一；`sealed` 要求 `batch=[]`；`final=true` 只允许在 `sealed`。
- 字节 ≤65536：DDL CHECK 兜底，`validate_run_domain` 先行返回 `invalid_outcome`，避免漏出 23514。
- 不存 transcript；模型文本进终态 `result` 或 event payload。

**预算**：`remaining_steps` 每次 model/tool 的 success/failure 结算扣 1；`run_start`、`unknown` 不扣；N 个 tool_calls 必须 ≤ 扣减后的预算，否则按 `budget_exhausted` 封口并记 `dropped_tool_calls=N`。开放 run 不变量：`remaining_steps ≥ live tool 数 ≥ 0`。

**终止**：终态 = `ended_at IS NOT NULL` 且 `result IS NOT NULL`，同事务发 `run_seal` + `pins_release`（先 seal 后 release）。

```text
result = {v:1, reason:'final'|'budget_exhausted'|'model_failed', output:object, dropped_tool_calls:int}
```

- `final`：模型显式 final；`output` = 规范化模型结果。
- `budget_exhausted`：非 final 且预算归零，或 tool 数超预算；`output={}`，`dropped_tool_calls` 记被丢弃数。
- `model_failed`：可信 model failure；`output` = 错误对象。**DP4 范围裁决**（设计走查只列 final/budget）：失败 effect 无恢复路径，不封口会让 `p6_plan` 永久 `deferred/run`，违反 G2「旧 run 可排空」。
- 取消不进入 DP4。`run_refused` 不是 run 终态（根本没有 run）。

### 3.7 typed delta op、applier 顺序与事件

| op | 精确键 | applier | 后置条件 |
|---|---|---|---|
| `run_create` | `op,id,owner_fiber_id,owner_episode_id,scope_id,state,remaining_steps` | INSERT，`parent_run_id`/`spawn_key`=NULL | 行存在、`remaining_steps≥1`、state 合法且 ≤65536、owner/episode/scope 与 effect 对齐 |
| `run_pin_bind` | `op,run_id,pins[{id,key,contribution_id,provider_episode_id,provider_epoch}]` | 只写 `pins` 实际存在的列；`provider_episode_id` 仅作校验 | 每条未释放、contribution 活、epoch 与 `contributions.episode_id→episodes.epoch` 相等、≤32、无 `pins_run_active` 冲突 |
| `run_state` | `op,run_id,state` | `UPDATE runs SET state=...` | 六键精确、phase 合法、≤65536（**不断言 `ended_at IS NULL`**：postcondition 在 `run_seal` 之后执行） |
| `run_budget` | `op,run_id,remaining_steps` | `UPDATE ... WHERE id=... AND remaining_steps=old-1 RETURNING` | 持久值等于目标值、≥0（算术与「旧值」在 **pre-DML** `run_delta`/validator 证明，不在事后 postcondition 里重算） |
| `run_seal` | `op,run_id,effect_id,result` | `UPDATE runs SET ended_at=clock_timestamp(),result=... WHERE ended_at IS NULL RETURNING` | `ended_at` 非空、result 形状合法、该 run 除 `effect_id` 外无 `host_io/ready/claimed/unknown` effect；首写由 `WHERE ended_at IS NULL` + 不可变触发器保证 |

applier 顺序：

```text
episode_begin → run_create → run_pin_bind → run_state → run_budget
→ …既有 contribution 操作…
→ contribution_inverse → run_seal → pins_release → episode_close → episode_activate
```

- `run_create` 必须先于 `run_pin_bind`（`pins.consumer_run_id→runs(id)` 非延迟 FK）。
- `run_seal` 必须先于 `pins_release`（后者要求 `ended_at` 非空）。
- `pins_release` 的 run 分支追加 `AND x.id IS DISTINCT FROM p_effect_id`；对 DP3 零行为变更（P6 的 effect 是 reconcile、`run_id IS NULL`）。
- 后继 applier：`run_start` 的 `fiber_id/episode_id` 取自 input，`run_id=NULL`；`model_call`/`tool_call` 的 owner 与 `run_id` 取 `runs` 与 input；三者 `request_actor=v_actor`。`v_emitted` 收全部后继 id（DP3 的 dispose admitted 检查因此仍成立且更强）。

事件：新增 `run_progress`（`entity_type='run'`, `entity_id=run_id`），payload `{run_id,effect_id,effect_kind,step,remaining_steps,phase,sealed,reason}`；`step` = 已结算的 model/tool effect 数（不含 `run_start` 与 unknown）；`reason ∈ {final,budget_exhausted,model_failed,null}`；model/tool 的 success/failure 各一条，unknown 不发。`run_start` 的 success 发一条 step=0 的 `run_progress`；`run_start` 的 failure 与拒启没有 run，发 `run_refused`（`entity_type='run'`, `entity_id=effect_id`），payload `{run_id:null,effect_id,reason:'owner_closing'|'start_failed'|'replay_right_missing'}`。单次 advance 仍至多一个事件（`validate_delta :421` 不动）。

### 3.8 `validate_run_domain`

不信任 interpreter：先 `p_delta IS DISTINCT FROM run_delta(p_effect_id,p_outcome)` 即 `invalid_outcome`，再做独立不变量检查：
1. 每个 kind/class 的 op 基数精确（run_start：0 或 1 个 run_create + 1 个 run_pin_bind + 1 个 successor；model/tool：1 个 run_state + 1 个 run_budget，封口时 + 1 个 run_seal + ≤32 pin release）。
2. tool intent 的 `pin_id`/`key` 命中该 run 的活 pin；`model_call` 的 `digests` 等于 `run_digests(run)`，`run_id` 等于 `effects.run_id`。
3. state 转移等于旧 state + 单一事实；`run_budget` 等于旧值−1；`phase`/`batch`/`final` 自洽。
4. 后继 ≤16、tool ≤16 且 ≤扣减后预算、pin ≤32；后继的 run/fiber/episode 绑定与锁定 effect 一致。
5. `run_create` 的 `id` 不存在；`run_seal` 只在未封口时可达，且同事务释放该 run 的全部 live pin。
6. 事件与重算事实逐字段相等。

### 3.9 并发、replay 与错误优先级

- replay-first：command replay 返回存储 response；terminal replay 返回 `disposition='replay'` 且 `emitted=[]`，不得重复 event/successor。
- 过期 lease 不阻碍可信原 receipt；重领才 attempt/fence+1；reclaim 要求 `replay.repeat && replay.concurrent`，否则 `blocked_unknown`。
- run 有 unknown effect 时：已 claimed 的 sibling 仍接受可信 receipt（扣预算、写 state、无 continuation/封口/pin release）；该 run 的 `ready` effect 新 claim 返回 `blocked_unknown` 零写。**claim 分支必须显式加这条检查**（`barrier_ready` 恒 true，只能产出 deferred，不能产出该错误码）；优先级：终态 replay → unknown wall → lease/reclaim → barrier → attempt/fence。`p6_plan`（`42:650-734`）的 unknown 检查先于 `deferred/run`，无需改。
- 封口后结算 → `already_terminal` 零写；对已终态 effect 再 claim → SQLSTATE `55000`（immutable trigger 既有口径）。
- `dependency_unresolved`：pin 已释放、provider episode epoch 漂移、contribution 已释放；`withdrawn_at` 非空不算。
- 首次 claim 目前不检查 replay 双真（只在 reclaim `:1329-1331`）；DP4 在 `run_start` 处新增更强检查，因此无 replay 权利的 provider 无法进入任何 run。
- `P0401` → `retry_with_closure` 零写。
- 错误码只用既有 24 个：`invalid_outcome`、`invalid_args`、`budget_exceeded`、`already_terminal`、`blocked_unknown`、`stale_claim`、`unauthorized`、`receipt_conflict`、`retry_with_closure`、`dependency_unresolved`、`effect_id_conflict`、`not_found_or_denied`。不得新增第 25 个。

### 3.10 Oracle 裁决（2026-10-27，用户授权代决）

| # | 决策 | 裁决与理由 | 置信 |
|---|---|---|---|
| 1 | `run_start` 的 request/steps 来源 | **B**：p4 只带 `{v,fiber_id,episode_id,contract}`；`{v,request,steps}` 由 success receipt 提交并冻结在不可变 `effects.outcome`。A 会把唯一生产入口变成 `request={},steps=3` 的 fixture，且无法改预算。 | 高 |
| 2 | model/tool claim 合同主体 | **B**：沿 `pin_id→contribution→provider install` 读 `contracts->capability`，capability 必须等于 effect kind；handler/replay 权利属 provider adapter。owner install 只提供 `agent.chat`。 | 高 |
| 3 | model failure 与超预算 tool_calls | **B**：model failure 封口 `model_failed`；N>r' 封口 `budget_exhausted` 并记 `dropped_tool_calls=N`，不建部分批次。结构非法或未声明 capability 仍是 `invalid_outcome` 零写。 | 中高 |
| 4 | unknown 之后的兄弟结算 | **B**：照常接受可信 receipt、扣预算，但不发 continuation/不封口/不释放 pin；unknown wall 由 `p6_plan` 表达。新 claim 返回 `blocked_unknown`。 | 中高 |
| 5 | `model_call` input | **A**：`{v,run_id,pin_id,key,digests,contract}`。request/state 可从 `run_start.outcome` 与 `runs.state` 重建，复制会漂移。 | 高 |
| 6 | owner 已不 live 时的 `run_start` | **B**：按 class 映射终态结算（success→succeeded），不建 run/pins/后继，发 `run_refused{owner_closing}` 并在 response 返回 reason；原 receipt 保留以支持 replay。 | 中 |
| (i) | `run_start` 仍走 claim/settle | 确认：保留单一 effect/receipt 路径，p4 不直接写 run。 | — |
| (ii) | reducer 纯度证明 | 确认并加强：`LANGUAGE sql IMMUTABLE BEGIN ATOMIC` + `pg_depend` 传递闭包无 `pg_class`；非 `pg_catalog` callee 也必须 `BEGIN ATOMIC`；保留源码正则作二级 lint。 | — |
| 7 | install 级 replay 权利 | **A1**：不改 DP2 安装准入（`contracts_valid` 继续允许 false，DP2 fixture 依赖它）；在 `run_start` 结算处要求计划中的 model/tool provider 双真，否则 `run_refused{replay_right_missing}`。A2（静默不发后继）无诊断信息，拒绝。 | 高 |
| 8 | 里程碑发布 | **B**：每里程碑独立本地 commit，按路径 stage；未获显式目标前**不 push**。DP3 的 `origin/v24` 授权是里程碑/分支特定的，不自动延续；不得按 `AGENTS.md` 的默认 `origin main` 推送 v24。 | 极高 |

裁决 3 的 `model_failed`/`dropped_tool_calls` 是 DP4 范围决策，不是用户已表达的永久产品偏好；裁决 4 的 claim 阻断与裁决 6 的事件形状是保守默认。三者都要在 deviation ledger 具名。

## 4. Gate 与验证规格

每脚本独立可跑：`uv run python v24/cordis/dp4/<file>.py`，退出码 0 = 通过；fixture 复用 `dp1/setup_db.py`、`dp2/test_support.py`，不新建 DB/role helper。每个负例必须提交尝试调用，并与调用前十表 snapshot 比较证明零写。

### 4.1 `CDP4-R` — run 创建与绑定（W1）

- R1 真实 install→P0→P1→P2→P4：`policy_ref='chat_tool'` 时 p4 产恰一条 ordinal 0 `run_start`；非 chat_tool 时 `successors=[]`。
- R2 `run_start` claim（owner 已 closing 也允许）→success：`runs` 一行、owner/episode/scope 对齐、`remaining_steps=steps`、run pin 数 = `committed_view` 的 model/tool capability 数、一条 ordinal 0 `model_call`（`digests` 三键）、恰一个 `run_progress`。
- R3 同 receipt 重放：`disposition='replay'`、`emitted=[]`，runs/pins/effects/events 计数与 successor 不变；不同 bytes → `receipt_conflict`。
- R4 伪造 p4 后继（两条 run_start、ordinal 1、非 chat_tool、run 已存在、input 键不符）→ `invalid_outcome` 零写。
- R5 owner 已不 live：终态结算、无 run/pins/后继、`run_refused` 一条；`P0401` → `retry_with_closure` 零写。
- R6 合同主体：owner install 不声明 model/tool 合同时，pin 指向的 provider 合同仍可 claim；伪造 provider capability ≠ kind → `invalid_outcome`/`unauthorized` 零写。
- R7 replay 权利：provider `repeat=false` 与仅 `concurrent=false` 两种 fixture 都能成功安装（DP2 语义不变），但 `run_start` success 结算终态拒绝，`runs`/`pins`/后继皆零，恰一条 `run_refused{replay_right_missing}`，同 receipt 重放一致；双真对照正常建 run。DP4 的 run-capable fixture 必须自备双真合同（`dp2/test_support.seed_provider` 默认 `concurrent=False`）。

### 4.2 `CDP4-M` — model 结算与 reducer（W2，M6 移至 W4）

- M1 e8：claim→success，budget 3→2，state `step=1,phase='tools',batch=N`，N 个 `tool_call` ready。
- M2 三摘要：`policy/schema/toolset` 与 `run_digests` 逐字节相等；篡改任一 → `invalid_outcome` 零写。
- M3 schema 负例：未知键、`interaction≠null`、`final` 与 tool_calls 并存、N>16、key∉tools、call_id 重复、usage 形状错。
- M4 reducer 纯度：`IMMUTABLE`；`pg_depend` 传递闭包无 `pg_class`；故意写一个 `BEGIN ATOMIC` 读 `runs` 的探针函数必须暴露 `pg_class` 依赖（证明检测有效）。
- M5 注入回滚：在 receipt 写入后、event 后、**successor 插入后**分别注入失败（三个点都在同一事务内），十表与 requests 快照回到调用前，effect 仍 claimed。

### 4.3 `CDP4-T` — tool 结算与批次屏障（W3）

- T1 并行 N 个 tool：全部结算前无 continuation；最后一个结算后恰一条 `model_call`，parent 是该 tool。
- T2 同 receipt 重放不产生第二个 continuation；双连接同时结算两个 sibling，仅后者观察到 batch 关闭并只产一条 continuation。
- T3 过期 lease 的 sibling 仍算 `ready/claimed`，不得提前续。
- T4 pin 语义：provider `withdrawn` 但未 release 时旧 run 仍可结算；`released` 后 → `dependency_unresolved` 零写；`pin_id`/`key` 不一致 → `invalid_outcome`。
- T5 unknown sibling：另一 sibling 的可信 receipt 仍被接受并扣预算，但不发 continuation/不封口/不释放 pin；新 claim → `blocked_unknown`；`p6_plan` 返回 `blocked_unknown`。
- T6 tool failure 仍完成批次并可触发 continuation 或预算封口。
- T7 provider 合同路径的 replay：过期但未重领的原 receipt 仍重放；重领成功（repeat/concurrent 双真）后旧 token 才 `stale_claim`；同 key 异 bytes → `receipt_conflict`；缺 replay 权利的 provider 在 reclaim 时 `blocked_unknown`。

### 4.4 `CDP4-X` — 预算、终止与 e7→e13（W4）

- M6 model failure → `model_failed` 封口 + pin 释放，无后继（W2 实现 reducer 分支，本阶段接 `run_seal` 验收）。
- X1 `final`：`run_seal(final)` + `pins_release` 同事务；`ended_at`/`result` 正确；封口后结算 → `already_terminal` 零写；已终态 effect 再 claim → `55000`。
- X2 `budget_exhausted`：1→0 时封口；`dropped_tool_calls` 记录正确；不建部分 tool。
- X3 e7→e13 全走查：3→2→1→0，e10 provider retire 后旧 run 继续用旧 pin/epoch，e11c/e12 deferred 零写，e13 不重新 resolve 改绑。
- X4 完成的 run 释放全部 run pin；`run_pin_release_delta` 只读断言保留；P6 在 seal 后不再被 run 阻塞。
- X5 防御性 `budget_exceeded`（扣减为负）零写。

### 4.5 `CDP4-B` — 布局、ACL、预算与回归（W5）

- B1 十表、manifest 18、唯一 `SECURITY DEFINER`、public EXECUTE 0、VIEW/EXTENSION 0。
- B2 helper 四文件合计 ≤5000，临时四文件树恰好 5000 通过/5001 拒绝；DDL 前缀 ≤900（实测 462）。
- B3 ACL：service 可 claim/settle 四 kind；admin/operator 对三个 run kind 一律 `unauthorized`；跨 family 拒绝。未获 replay 双真的 provider 在 DP4 生产链路里已被 `run_start` 拒绝，因此“reclaim 时 `blocked_unknown`”只能用 owner-fixture 的 `model_call`/`tool_call` 行构造，并标为 fixture 证据。
- B4 生产证据替换：`runs` 只经 `run_create`/`run_state`/`run_budget`/`run_seal` 四个 op 写，`pins` 只经 `run_pin_bind` 写（按 `ELSIF v_op='run_` 切分源码断言 DML 只在五分支内）；`host_io` 六态仍 `0A000` 且快照不变；`dispatch`/`listener_call` 不可 claim；scanner/sweep/recover 正则保留并扩展到 DP4 新增函数；`run_pin_release_delta` 无 DML。
- B5 结构上限：successor 16/17、batch 16/17、run pin 32/33、closure 512/513；600 条历史 effect 不膨胀 closure；`settlement_seed` 对 `host_io` 与 DP3 逐字节相同。
- B6 冻结与隔离：十二份 frozen SHA-256、`57e2c1e` diff、`git diff --check`；只 stage DP4 路径。

### 4.6 每阶段旧 gate

B0 与 W5 必须串行实跑 DP3 收尾的全部命令（`docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md` 的 26 条表），一次一条、独立进程、退出码 0；不得以旧绿代替新闭环。W1–W4 各自至少重跑 DP1/DP2/DP3 相关 gate 与新增 gate，证据写 matrix。

## 5. File-by-file impact

| 文件 | 变更 | 依赖 |
|---|---|---|
| `v24/cordis/sql/43_loop.sql` | 新建：policy/schema/digests/claim_contract/run_start_successor/reducer/run_delta/validate_run_domain/settlement_seed | 先于 40 的引用 |
| `v24/cordis/sql/40_advance.sql` | settlement 分派、ACL、claim 合同、`validate_delta` kind、p4 闸、5 op、后继 applier、seed、`pins_release` 排除自身 | 43 全部签名 |
| `v24/cordis/sql/41_lifecycle.sql` | p4 successors → `run_start_successor(f.id)`（≤25 行） | 43 |
| `v24/cordis/sql/42_teardown.sql` | 闭包 pair/refs、5 个 postcondition（≤65 行） | 40/43 同步 |
| `v24/cordis/sql/16_runs.sql` | state ≤65536 CHECK（+1） | 独立 |
| `v24/cordis/load.py` | `43_loop.sql` 入 canonical order（17→18），`self_check_manifest` 计数 | B0 |
| `v24/cordis/helper_budget.py` | `HELPERS` 四文件、`_write_tree` 四份、5000/5001 证明 | B0 |
| `dp1/test_kernel.py`、`dp2/test_boundaries.py`、`dp3/test_boundaries.py` | manifest/预算计数；dp1 的 unauthorized 断言；dp3 的 settlement/run-writer 断言替换 | B0/W1/W5 |
| `dp4/test_run.py`、`test_reducer.py`、`test_loop.py`、`test_boundaries.py` | 新建 gate | W1–W5 |
| `dp4/README.md`、DP4 matrix/ledger | 新建收尾工件 | W5 |
| 本文 | 回填裁决与各阶段 result | W5 |

预算核算：3550 + 560(43) + 270(40) + 25(41) + 65(42) = **4470 ≤5000**，余量 530；DDL 461+1=**462 ≤900**。实际行数每里程碑实测；若预测超 4800，先简化校验，不压行、不挪文件、不删行为。

## 6. Risks、兼容与回退

- **pins 无 `provider_episode_id` 列**：op 形状保留该键仅作校验，applier 不写不存在的列；CDP4-R2 用真实 fixture 验。
- **request 不在 effect input**：`runs.state.origin` + `run_start.outcome` 是唯一链路；文档与 ledger 明写，不得再复制进 state。
- **`emitted` 扩张**：收全部后继 id；DP3 dispose 仍只发 reconcile 后继，行为不变，但 CDP4-B 重跑 CDP3-D 证明。
- **闭包种子回归**：三个 run kind 才扩张；非 run kind 必须逐字节不变，否则 512/513 与 600 历史 effect 断言翻转。
- **`pins_release` 自阻塞**：必须排除 `p_effect_id`；这是 W4 的核心缺陷修复，CDP4-X 专测。
- **reducer 纯度证明的局限**：`pg_depend` 传递闭包需 PG 记录 BEGIN ATOMIC 依赖；非 `pg_catalog` callee 不 BEGIN ATOMIC 会让证明静默失效。W1 用故意读表的探针验证检测有效；若 PG18 缺失该类依赖，退化为「IMMUTABLE + 源码 lint + 白名单 callee」，并在 ledger 记明。
- **unknown 永久墙**：DP4 不解决；ready `run_start` 若永远无人 claim 也会挡 P6。二者都属 DP6 scanner，ledger 明列。
- **`model_failed`/dropped 属 DP4 范围决策**：非用户永久偏好，可在后续里程碑改判。
- **postcondition 时序**：`assert_delta_applied` 在全部 domain op 之后执行，因此 `run_state`/`run_budget` 不能断言「run 仍 open」，`run_budget` 也不能在事后证明「旧值−1」；这两项必须在 pre-DML `run_delta`/validator 与 `UPDATE ... RETURNING` 中证明，事后只断言持久值。遗漏会让每个封口结算整体回滚。
- **P4 相位**：生产者求值发生在 `episode_activate` 之前，只能要求 `reloading` + activation totality；把 `active` 写进生产者会让 DP4 无法启动任何 run。
- **回退**：每里程碑独立 commit；若 W3 阻塞，可先交付 W1+W2（run 创建 + model + final/budget 封口），在 ledger 明写 tool 批次未通，不得以旧绿冒充。
- **发布授权（Oracle 裁决 8，B）**：DP4 只做每里程碑独立本地 commit，按路径 stage；不 push。W5 以 push-ready 摘要结束（commit 列表、分支、`git status`）；若后续获授权，只向用户点名的远程/分支推送，用 `-u`，不 force。

## 7. Implementation order

### B0 — 基线与脚手架

固定 `git rev-parse HEAD`、upstream、工作区、工具链、frozen hash/diff；建空 `43_loop.sql`；`load.py`/`helper_budget.py`/三处 gate 的 18 号 manifest 与四文件预算。**B0 不改 ACL 断言**：`dp1/test_kernel.py:307-309` 的 `unauthorized` 断言保持到 W1（ACL 与 run_start 同里程碑落地时一起替换）。`dp3/test_boundaries.py:239-283` 的「settlement 0A000 / 无 run writer」两条在 W1 替换；`host_io` `0A000`、无 scanner、`run_pin_release_delta` 只读三条从头保留。

**Result**（2026-10-27）：在 worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`、分支 `v24`、HEAD `4b34bf28e83791a7af3356f8036237afca78b67a` 上完成。26 条旧命令逐条独立启动并等待退出，全部 exit 0，总耗时 118 秒。`43_loop.sql` 为 2 行无行为脚手架（注释 + `DO` 空块，因为 psycopg2 拒绝空查询）；四文件 helper 合计 **3552≤5000**，临时 5000/5001 边界由 CDP1-K0 实跑通过；DDL 461≤900，manifest 18，十表，唯一 `SECURITY DEFINER` 仍为 `advance`。冻结 SQL 12 个 hash 不变。B0 只做本地 commit，不 push；B0 commit 为 `17c855d`。

### W1 — `run_start` 生产与绑定

43 的 policy/schema/digests/id 派生/`claim_contract`/`run_start_successor`/`settlement_seed`；41 的 p4 后继；40 的 ACL、claim（含 `input` 回传与 unknown guard）、`validate_delta` kind、p4 闸、后继 applier、`run_create`/`run_pin_bind`、`run_refused`/`run_progress`；42 的闭包 pair/refs 与两个 postcondition。同时替换 `dp1/test_kernel.py:307-309` 的 unauthorized 断言（service 获准、admin/operator 仍拒）。验收 `CDP4-R`（含 R5 owner-closing；该路径不依赖 `run_seal`，可在 W1 交付）。

**Result**（2026-10-27）：在 B0 commit `17c855d` 之上完成。27 条命令（26 条旧 gate + CDP4-R）逐条独立启动并等待退出，全部 exit 0，总耗时 117 秒。CDP4-R1–R7 全部通过：p4 对 chat_tool 恰发一条 ordinal 0 `run_start`，非 chat_tool 为零；claim 携带冻结 `input`；run/pin/model 后继/事件精确；原 receipt replay 零写、异 bytes `receipt_conflict`；伪造 p4 后继、owner-closing、P0401、provider capability 错配均零写；repeat=false 与 concurrent=false 两种 provider 都安装成功但在 `run_start` 被 `replay_right_missing` 拒绝。四文件 helper **4040≤5000**（40=1546、41=1211、42=1000、43=283），DDL 461，manifest 18，十表，唯一 DEFINER 仍为 `advance`。本里程碑只做本地 commit，不 push。

### W2 — model 结算与 reducer

纯 reducer、model receipt、`run_state`/`run_budget`、tool 后继、digests 校验、`already_terminal`。验收 `CDP4-M`（M1–M5）；`model_failed` 封口与 M6 随 W4 的 `run_seal` 一起交付。

**Result**（2026-10-27）：在 W1 commit `e8b6cce` 之上完成。28 条命令（26 条旧 gate + `CDP4-R` + `CDP4-M`）逐条独立启动并等待退出，全部 exit 0，总耗时 121 秒。CDP4-M1–M5 全部通过：e8 的 `3→2` 预算与冻结 batch、三条摘要逐字节比对与三种漂移零写、schema/usage/text 负例零写、reducer 纯度与读表探针检测、receipt/event/successor 三处注入回滚且 effect 仍为 claimed。`model_failed`/final/budget 的 `close_run` 在 W2 返回 `invalid_outcome{reason:run_seal_unimplemented}`，M6 与封口按计划留在 W4。四文件 helper **4216≤5000**（40=1546、41=1211、42=1000、43=459），DDL 461，manifest 18，十表，唯一 `SECURITY DEFINER` 仍为 `advance`。W2 只做本地 commit，不 push。

### W3 — tool 结算与批次屏障

tool receipt、pin/key/liveness、sibling 查询、唯一 continuation、unknown 兄弟结算、claim 阻断。验收 `CDP4-T`。

**Result**（2026-10-27）：在 W2 commit `8cbc5f3` 之上完成。29 条命令（26 条旧 gate + `CDP4-R`/`M`/`T`）逐条独立启动并等待退出，全部 exit 0，总耗时 134 秒。CDP4-T1–T7 全部通过：N 个 tool 串行结算时最后一个才发恰一条 `model_call`（parent 为该 tool）；双连接竞态恰好一个响应 `emitted` 为 1、另一个为零，且 continuation 的 parent 是关闭 batch 的 tool；过期 lease 仍计 live sibling；withdrawn 未 release 的 pin 可结算，released 则 `dependency_unresolved` 零写；unknown 兄弟接受可信 receipt 并扣预算，但不发 continuation/不封口/不释放 pin，新 claim 与 P6 均 `blocked_unknown`；tool failure 正常关闭 batch；过期原 receipt 重放/重领/new token 与 `stale_claim`/`receipt_conflict` 均符合合同。W3 按 §3.2 把 model/tool 结算合并回单一 `run_delta` planner，移除 W2 的 `model_delta` 与 W3 的 `tool_delta`，43 为 **509**（预备态 555），无压行或搬文件；四文件 helper **4266≤5000**（40=1546、41=1211、42=1000、43=509），DDL 实测 **461**（W1 的 state CHECK 是原行内追加，不增物理行），manifest 18，十表，唯一 `SECURITY DEFINER` 仍为 `advance`。W3 只做本地 commit，不 push。

### W4 — 预算与终止

`run_seal`（含 `effect_id`）、final/budget/model_failed、`pins_release` 与 current-effect 排除、e7→e13。验收 `CDP4-X`（含 M6）。

### W5 — 收尾

26 条旧命令 + `CDP4-R/M/T/X/B` 串行全绿；冻结 hash、预算、DDL、ACL 复核；README/matrix/ledger 与本文 result 回填。每个里程碑按路径 `git add`、独立本地 commit 并记录 commit id；**不 push**。收尾输出 push-ready 摘要（commit 列表、分支、`git status`），等用户点名远程/分支后再推。

## 8. References 与保真索引

- 规格：`docs/designs/cordis-plugin-system-2026-10-25.md:159-228`（advance 合同/顺序/解释器）、`:263-311`（规则与派生）、`:336-381`（分期/走查/清理）、`:383-463`（账本/coeffect/事件）、`:465-603`（命题）、`:617-651`（装载/ABI）、`:655-718`（DSH 对照）、`:722-786`（预算/gate/切片）、`:787-810`（崩溃矩阵）、`:812-853`（债务/不做）、`:855-1043`（DDL/伪代码）。
- 边界与前作：DP1 plan `:206-247`；DP2 plan `:120-236`；DP3 plan `:1-60,194,450-491`；DP3 matrix/ledger 全文。
- 实现：`40_advance.sql:147-163,185-263,401-403,430-448,449-670,946-963,981-1191,1201-1344`；`41_lifecycle.sql:42-80,125,543-602,689-696,818-824,1002-1004,1039-1043`；`42_teardown.sql:5-40,41-157,349-366,635-734`；`15_pins.sql`、`16_runs.sql`、`17_effects.sql`、`30_triggers.sql:56-95`、`50_permissions.sql`。
- 语义参考（不同 schema，不复制）：`docs/designs/v24-pg-agent-2026-10-22.md:108-147,258-317`；`v24/sql/48_loop.sql:1-45,1355-1410,1486-1505`；`v24/host/worker.py`。
- 工件：DP1/DP2/DP3 的 README/matrix/ledger；`AGENTS.md:7-57`；`v24/cordis/load.py`、`helper_budget.py`。

保真索引（export lane 1/2/3 → 本文）：

| Export 实质项 | 落点 |
|---|---|
| 现状：settlement stub、ACL、后继、p4、闭包、postcondition ELSE NULL | §2.2 表 |
| 新 `43_loop.sql` 与函数清单 | §3.2 |
| `run_policy`/`chat_tool_schema`/三摘要 | §3.2、§3.5 |
| reducer 合同与决策表 | §3.5 |
| run state 五/六键、字节界、result | §3.6 |
| 预算口径与终止理由 | §3.6 |
| 5 个 typed op、顺序、postcondition | §3.7 |
| `settlement_seed` 与闭包缺口 | §3.3 |
| `pins_release` 排除自身 | §3.7、§4.4 |
| p4 生产者与 41 改动 | §3.4 |
| 合同主体（provider） | §3.5、§4.1 R6 |
| unknown/失败/超预算语义 | §3.5、§3.6、§3.9 |
| replay/lease/竞态/错误优先级 | §3.9 |
| gate `CDP4-R/M/T/X/B` | §4 |
| file impact、预算、风险、顺序 | §5–§7 |
| critique 的 P4 相位、postcondition 时序、batch 语义、unknown claim guard、owner 合同归属、seed 上界、读通道 | §3.2–§3.9、§4.2–§4.5、§6 |

有证据的修正（非遗漏）：lane 声称「41 不改」与 p4 实际在 `41:1039-1043` 冲突，本文改为允许 ≤25 行；lane 的 `run_pin_bind` 写入 `provider_episode_id` 与 `15_pins.sql` 冲突，改为仅校验；lane 的 `jsonb_agg(DISTINCT … ORDER BY …)` 语法不成立，改为 `SELECT DISTINCT`；lane 的 continuation 依赖 `UNIQUE(parent_id,ordinal)` 被证伪，改为 G+屏障+`effects_one_model_inflight`；三份 lane 一致认为 `unknown` 不扣预算，按设计「不释放预算」定稿；§9 已改为已决项。

## 9. Open Questions 与 hand-off

已裁决（§3.10）：request/steps 来源、合同主体、失败/超预算封口、unknown 兄弟结算（含不扣预算）、model input、owner_closing 拒启、run_start 走 claim/settle、reducer 纯度证明。以下为实施时仍需观察或属后续里程碑：

1. **ready `run_start` 永久无人 claim**：DP4 不解决，属 DP6 scanner；owner 的 P6 会一直 `deferred/effect`。
2. **install 级 replay 权利（已裁决 A1）**：不改 DP2 安装准入；`run_start` 结算处拒绝无 `repeat && concurrent` 的 model/tool provider。matrix/ledger 记为 DP4 范围的窄解释，不是 claim 级证明。
3. **PG18 `pg_depend` 对 BEGIN ATOMIC 的覆盖**：W1 的探针若证明依赖记录不完整，降级为「IMMUTABLE + 源码 lint + callee 白名单」。
4. **发布授权（已裁决 B）**：DP4 只做本地 commit，不 push；W5 输出 push-ready 摘要，等用户点名目标。
5. **e7 预算=3 的来源**：走查用 3 仅是示例；生产预算由 `run_start` receipt 的 `steps` 决定，范围 1..64。
