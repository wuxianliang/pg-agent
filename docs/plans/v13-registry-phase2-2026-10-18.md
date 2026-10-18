# v13 时空注册面第二阶段：消费侧集成开发计划

> 计划日期：2026-10-18
> 范围：Phase 2 运行时消费集成；Phase 3 仅作最终收尾。
> 状态：W5/W6 测试与文档验收通过；实现提交 `937a864115694373250417daa374b05fad64267b` 已推送到 `origin/v99`，提交后净 tracked-tree 复验与完整 51 项已通过；文档 post-commit 收尾提交仍由父协调 agent 处理。

### 执行记录

- [x] W0-W1：Stage 41 prefix / effective-object 守卫与 overlay 基础。实际运行 registry gate 16/16 groups、483 checks，consumer foundation gate 12 checks，均 exit 0；`git diff --check` 通过。未提交或推送。
- [x] W2-W3：claim/completion pin 与八键 freshness。实际运行 consumer 55 checks、registry 16 groups/485 checks、fair 137 checks、ACL 197 checks，envelope/filter 全绿；未提交或推送。
- [x] W4：真实控制消费者 superseded projection；W5 补齐实际 tool spawn、repair/replan continuation、human 六键与 loaded pg_proc 证据。consumer 独立实跑 289 checks exit 0（完整序列结果另列）。
- [x] W5-W6 测试/工件：离线隔离预验证 parity → ports 均 exit 0 后，从 #1 严格串行跑完原 50 + consumer 51 项：49 项 exit 0，#17/#18 为预期 exit 1/2，51 项均 trace restore。registry 16组485 checks、consumer 289 checks、govern 228、goal_supervisor 74、read_tools E4 均通过。README/matrix/ledger 已更新；未暂存/提交/推送，父协调 agent review 与提交后净树复验仍待处理。

历史首红证据（不作为当前结论）：`prompt-exports/w5-phase2-final-20261019/results.json` 及同目录
manifest/head/逐项日志。逐项 51 状态见 registry README，偏差见 S42R-9。
goal_supervisor frozen 路径修正后，静态入口通过，最终序列 goal_supervisor
74 / govern 228 均 exit 0，无真实冲突。#30 在 480.16 秒后编译失败，
非 timeout；未修改外部 PiSwift 或冻结 driver。30 项均 trace bytes/mode
恢复，pg.jsonl SHA-256 为
`3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`、
mode 0644，未运行项不补算。

历史兼容预验证（2026-10-19，S42R-10；不作为当前结论）：活动 PiSwift clean main/a73c391
保持不动；找到保留 tag v0.87.1/bfccb32（历史基线、非 throws/四元组），建立
独立 detached worktree。通过 ignored Swift 工具路径 override 与临时 package
副本（仅副本依赖路径替换、Sources 全等）预验证 parity，exit 1：SwiftPM 更新
MacPaw/OpenAI 时 github.com TLS 连接失败。依用户任一非预期失败即停，本轮
不重试、不改依赖策略；ports 未运行，新完整 51 项未启动。证据在
`prompt-exports/w5-piswift-compat/`；trace 恢复、用户 checkout 与 frozen
Sources/manifest 未变。W5/W6 仍未完成，提交前条件不满足，不暂存/提交/推送。

最新完成证据（S42R-11）：`prompt-exports/w5-phase2-offline51-20261019/results.json`
含 51 条真实执行记录、同目录 manifest/head/逐项日志；总 gate 用时 951.81 秒，
未拼接旧尝试。旧 tag 的 Package.resolved 固定的 OpenAI 提交已在本地缓存；
复制锁文件到 ignored 临时 packages 并使用 `--disable-automatic-resolution --skip-update`
后，离线构建 exit 0（472.93 秒），parity/ports 预验证及完整序列均通过。
PiSwift 活动 main/a73c391 与 detached v0.87.1/bfccb32 均 clean，活动 checkout、
冻结 Sources/manifest 未修改；重现命令与 51 项逐项退出码见 registry README。
默认 parity 仍报告 node_modules 缺失，未启用 PI_PARITY_REQUIRE_ALL，不声称全平面覆盖。
测试及收尾文档前置条件已满足；§7 的父协调 agent review、实现提交/推送已完成，
post-commit receipt 已由本轮补齐，文档收尾提交仍由父协调 agent 处理。

最新提交后净树证据（S42R-12）：实现 HEAD
`937a864115694373250417daa374b05fad64267b`，`origin/v99` 已从
`5be562d..937a864` 推送成功；tracked tree 在运行前后均为空。沿用旧 tag
`v0.87.1` detached PiSwift worktree 与本地锁文件/缓存离线隔离环境，从 #1
严格串行重跑完整 51 项；receipt 为
`prompt-exports/w5-phase2-postcommit-20261019/results.json`，另有
`manifest.json`、`head.txt`、`head-after.txt`、`tracked-after.txt`、
`results-summary.txt`、`trace-after.txt` 和 `verify-after.json`。51 行均
`valid=true`、`trace_restored=true`，49 项 exit 0，#17/#18 预期 exit 1/2，
总 item 用时 911.44 秒；trace SHA-256 为
`3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`、mode
0644。`verify.py` 证明活动 PiSwift `a73c391`、旧 worktree
`bfccb32`、冻结 Sources/manifests 均未变且 clean。默认 parity 仍跳过缺失的
`node_modules` 平面，未启用 `PI_PARITY_REQUIRE_ALL`，不作 all-plane/真实
provider 声明；不修改 runtime、测试逻辑或 runner。

## 1. 目标、完成标准与边界

### 1.1 目标

把 Stage 41 已实现的全局 registry `revision`、`tools_revision` 接入实际运行链：

`claim -> pinned context -> worker IO -> complete -> event projection -> route/advance/parse`。

Phase 2 必须提供可回溯的 effect-context pin、严格 completion overload、registry-aware freshness，以及对所有真实控制消费者的 superseded 投影过滤，同时保留旧调用兼容、CE 并行面和 Stage 41 前缀字节守卫。

### 1.2 Done when

- global claim 从五键变六键，只增加 `context_revision`；fair claim 从 SIX 变 SEVEN，只增加该键；CE 的七键 claim 完全不变。
- 每次成功 claim 在同一事务产生不可变 pin；strict completion 精确校验 effect/attempt/fence pin 和 `context_revision`。
- `v13_probe`、最终 `v13_judgment_envelope`、`v13_snap_of` 和有效 `v13_advance` 遵守同一 revision 不变量：envelope 在单条语句内自洽，snapshot 只投影该 envelope，advance 以第八键比对并弃批；它们不声称跨事务共享一个物理 statement snapshot。advance freshness 从七键增至八键而不改公开签名。
- `llm/message`、`tool/result`、`resolve/failed` 以及刷新探明的 `tool/call`、repair/replan、human/responded 消费者均有明确的 source-effect pin 投影过滤；旧 legacy、无 effect 的 synthetic、CE 事件不被误删。
- Stage 1 前缀、前 39 个 SQL 文件、`v13/load.py` 41 项、CE 文件/测试闭集仍通过静态与运行时守卫。
- Phase 2 自己完成 registry/consumer gates、README、conformance matrix、deviation ledger、完整回归、按路径提交和当前 v99 分支推送。Phase 3 不补运行时功能、不补测试行为、不承担 Phase 2 遗漏。

### 1.3 非目标

- 不新增 loader stage，不修改 `v13/load.py` 的 `SQL_LOAD_ORDER`。
- 不迁移 `tools`、`v13_policies`、thresholds 或 CE 三个 generation；不调用任何 `v13_ce_*` 函数。
- 不改变 `v13_advance(uuid,jsonb)`、旧五参数/六参数 `v13_complete`、旧事件 payload 形状或 `control/spawn` exact-key guard。
- 不在 claim/complete 事务内做 provider、网络、等待或其他外部 IO。
- 不把全局 clock 改成 scope-local freshness；任意 scope 的 registry 写导致全局旧 pin/在途 advance 失效是本阶段明确接受并测试的成本。

## 2. 现状与证据

### 2.1 Stage 41 和加载后的有效对象

`v13/load.py` 的 registry 是第 41 项（`v13/load.py:58,102`；尾部断言 `v13/registry/test_registry.py:237-240`），Stage 2 只能把 sentinel 分隔的 overlay 追加到 `v13/registry/v13_registry.sql`。同名 SQL 定义按加载顺序覆盖，施工前用 `pg_proc` 的 `regprocedure`、owner、`prosecdef`、`proconfig`、volatility、`pronargdefaults`、ACL 做安装态复核。

| 有效对象 | 最终来源 | 当前事实 | Phase 2 变化 |
|---|---|---|---|
| `v13_probe(uuid)` | `v13/manifest/v13_manifest.sql:830-843` | 七个 freshness 字段 | 加 `registry_revision`，成为八键 |
| `v13_judgment_envelope(uuid)` | `v13/filter/v13_filter.sql:485-579` | 最终 20 个顶层键；早期 manifest 定义已被覆盖 | 在同一 statement snapshot 加第 21 键 `registry_revision` |
| `v13_snap_of(jsonb)` | `v13/resolve/v13_resolve.sql:384-401` | envelope 纯投影 | 只投影 envelope 的 registry revision，不重新读 clock |
| `v13_snapshot(uuid)` | `v13/envelope/v13_envelope.sql:566-567` | wrapper 调 `v13_snap_of(v13_judgment_envelope(...))` | wrapper 形状不变 |
| `v13_parse(uuid)` | `v13/economy/v13_economy.sql:353-398` | `resolve/failed` 计入 retry/abandon | 排除 superseded effect-backed failure；保留无 pin synthetic |
| `v13_advance(uuid,jsonb)` | `v13/plan_arm/v13_plan_arm.sql:332-869` | plan_arm 是最终定义；fanout/triage copies 已被覆盖 | 八键 freshness；所有真实控制查询按 projection 过滤 |
| `v13_route(uuid,jsonb)` | `v13/loop/advance.sql:110-178` | 当前 turn `llm/message`/`tool/result` 驱动 finish | 加 current pin predicate，保留 origin_user_seq |
| `v13_claim` | `v13/fanout/v13_fanout.sql:266-303` | 五键 global claim/CAS | 六键，原子 pin |
| `v13_claim_fair` | `v13/fair_claim/v13_fair_claim.sql:421-599` | 独立 fair CAS，六键含 `root_session_id` | SEVEN，route 仍 42501 |
| `v13_complete` | `v13/acl/v13_acl.sql:245-451,459-470` | 六参数 body、五参数 wrapper；session -> effect 锁序 | 新增无默认尾参的七参数 strict overload；旧签名不变 |
| cap/triage/closeout/govern | `v13/seam/v13_seam.sql:95-280`; `v13/triage/v13_triage.sql:325-358,511-528`; `v13/spawn/v13_spawn.sql:585-739`; `v13/govern/v13_govern.sql:453-507,517-570`（scheduler 定义从 517，tool/call 消费点 559-570） | human/responded、repair/replan、tool/call 真实驱动控制转换 | 按 source-effect pin 投影过滤 |

Stage 41 context 已返回 `revision`、`tools_revision` 和 `context_hash`（设计文档 §4.4、`v13/registry/v13_registry.sql`）。`v13_registry_meta.revision` 仅是诊断值；读面必须读全局 singleton clock，缺 seed 必须 RAISE，不能回退 0。

### 2.2 刷新探明的控制消费者

旧草案只过滤 finish/failure 三类事件，这不足以满足代码事实：

- `tool/call` 在有效 `v13_advance` 中聚合并 spawn 子 session/effect（`v13/plan_arm/v13_plan_arm.sql:471-508`），同时被 `v13_triage_block_explore_spawn`（`v13/triage/v13_triage.sql:511-528`）和 `v13_scheduler_hint`（`v13/govern/v13_govern.sql:559-570`）消费。
- repair/replan 进入 plan_arm continuation/material/cap 分支、seam tail-gap/cap exemption、triage fold、spawn closeout 和 recover-idle（`v13/plan_arm/v13_plan_arm.sql:436-444,524-534,605-611`; `v13/seam/v13_seam.sql:176-269`; `v13/triage/v13_triage.sql:325-358`; `v13/spawn/v13_spawn.sql:585-739`; `v13/govern/v13_govern.sql:453-507`）。它们不是 audit-only。
- human/responded 通过 `v13_cap_answer_anchor`/`v13_cap_human_answered` 释放 cap（`v13/seam/v13_seam.sql:95-167`）。
- `resolve/failed` 由 economy parse 计数；advance 自己产生的无 source synthetic failure 必须保留。
- `frontier_gap` 明确排除其 source_effect_id 对应 effects 的 synthetic replan（`v13/frontier_gap/v13_frontier_gap.sql:295-320`），因此 projection 必须区分 synthetic 与 effect-backed。

payload 不能随意加锚：repair/replan 只允许 `{schema_version}`，human/responded 是精确六键（`v13/control/v13_control.sql:447-458`），tool/call 是精确 `{args,id,name,schema_version}` 且 spawn guard 固定 name/args（`v13/spawn/v13_spawn.sql:246-258`）。因此 Phase 2 采用 side-table source-effect pin mapping，不改业务 payload，也不静默放宽 guard。

## 3. 设计

### 3.1 Overlay 与数据对象

在 `v13/registry/v13_registry.sql` Stage 1 `COMMIT` 后追加唯一 sentinel：

```text
-- STAGE42_CONSUMER_OVERLAY_BEGIN
...
-- STAGE42_CONSUMER_OVERLAY_END
```

Stage 1 前缀字节必须原样保留；无新 loader stage。新增两张 owner-only 表：

#### `v13_effect_context_pins`

- `effect_id uuid NOT NULL`，引用 `effects(effect_id)`；`attempt_no integer > 0`；`fence bigint > 0`。
- `scope_id uuid NOT NULL`，引用 `sessions(session_id)`，由 pin helper 校验等于 effect 的 session。
- `context_revision bigint >= 0`、`tools_revision bigint >= 0`、`claimed_at timestamptz NOT NULL DEFAULT clock_timestamp()`。
- 主键 `(effect_id, attempt_no)`；可保留唯一键 `(effect_id, attempt_no, fence)` 作为 mapping 的交叉校验，确保 capture trigger 不能写入与 pin fence 不同的值（attempt_no 本身是 re-claim 的唯一递增点，fence 不是第二 pin 行）。
- BEFORE UPDATE/DELETE immutable trigger 永久 RAISE；没有 host role、PUBLIC、worker、resolve、recall、route、spawn_owner 的表级 DML/SELECT。

#### `v13_effect_context_event_pins`

- `(session_id uuid, event_seq bigint)` 主键，引用 `events(session_id,seq)`。
- `effect_id, attempt_no, fence` 引用 pin 的唯一键；校验 event 的 `source_effect_id` 与 effect 对齐。
- 同样 append-only；仅由可信 events AFTER INSERT capture trigger 写入。
- event mapping 按精确 attempt/fence 绑定，不能只按 effect_id 猜 latest：同一 effect 可被重新 claim，旧完成必须保持旧 context 归属。

events AFTER INSERT trigger 只处理 `source_effect_id IS NOT NULL`：存在精确 pin 时插 mapping；无 pin 历史的 legacy/CE 或 source 不存在的 synthetic 不插 mapping且不抛错；若已有 pin 历史却 mapping malformed/缺失，控制 projection 返回 false、不 RAISE。三类 trigger 函数（pin immutable、mapping immutable、event capture）均为 owner `SECURITY DEFINER`、固定 `search_path = pg_catalog, public`、PUBLIC REVOKE，避免 route、spawn_owner、triage 的事件写入路径因 mapping 表 owner-only 而 42501。mapping 失败与 event 插入同事务回滚，不能留下半写。

### 3.2 Helper 与 ACL

所有 helper 使用可信 owner、`SECURITY DEFINER`、`SET search_path = pg_catalog, public`，并以 `has_function_privilege` 验证最终 ACL：

| Helper | 语义 | EXECUTE |
|---|---|---|
| `v13_registry_fences() RETURNS TABLE(registry_revision bigint, tools_revision bigint)` | `STABLE SECURITY DEFINER` 一次读取 global clock 与 tools singleton；任一 seed 缺失即 P0001 | route、recall、resolve（仅此窄 helper；resolve 仍不能调用 registry context） |
| `v13_effect_context_pin_insert(effect,attempt,fence,scope,context_rev,tools_rev)` | `VOLATILE SECURITY DEFINER` 校验 effect token/session 后插入 pin；失败传播使 claim 回滚 | route；fair claim 由 owner 内部调用 |
| `v13_effect_context_pin_lookup(effect,attempt,fence)` | `STABLE SECURITY DEFINER` 精确返回 scope、context_revision、tools_revision | route-only |
| `v13_effect_context_pin_matches(effect,attempt,fence,context_rev)` | `STABLE SECURITY DEFINER` exact pin match；缺 pin 与 revision mismatch 可区分 | route、spawn_owner |
| `v13_effect_context_event_current(session,seq)` | `STABLE SECURITY DEFINER` mapping 存在且双 revision 等于当前全局 fences 才 true；malformed false | route、resolve |
| `v13_effect_context_effect_current(effect)` | `STABLE SECURITY DEFINER` 无 pin 历史视为 legacy true；有历史但无当前精确 pin 或双标量旧则 false | route、resolve |

`v13_registry_context` ACL 仍为 recall+route，resolve 继续 42501；fair claim owner-only，route 继续 42501（`v13/fair_claim/test_fair_claim.py:630-637`）。strict completion 只授 route+spawn_owner，不授 PUBLIC、worker、resolve。pin 表本身永不向这些角色授表权限；worker 如需读取，必须经 route-capable driver 或窄授 definer helper，不能假设 `v13_worker` 直读。

### 3.3 Claim、pin 与 completion

Global claim 保留默认 lease 参数，返回：

```text
{effect_id, attempt_no, fence, kind, request, context_revision}
```

Fair claim 返回：

```text
{attempt_no, effect_id, fence, kind, request, root_session_id, context_revision}
```

两者只新增 `context_revision`，不把 `tools_revision` 暴露为第三 claim 键。实现可用一条 data-modifying statement物化 fences、CAS 与 pin，也可保留多语句但必须在同一事务中由 commit 前双 fences 复核兜底；pin/FK/唯一约束失败必须回滚 CAS。claim 不对 registry clock `FOR UPDATE`，避免与 Stage 41 写面 `clock -> meta -> sessions -> registrations` 形成反向锁序。fair claim 保留 `advisory 13002 -> root session -> child session -> effect`。

保留现有：

```text
v13_complete(effect, attempt, fence, status, result DEFAULT NULL)
v13_complete(actor, effect, attempt, fence, status, result DEFAULT NULL)
```

新增严格 overload，七个参数全部 required：

```text
v13_complete(actor, effect, attempt, fence, status, result, context_revision)
```

不得写成 `result DEFAULT NULL, context_revision`，PostgreSQL 禁止 required 参数跟在 default 后。新增私有共同 completion implementation（例如 `v13_complete_contextual(..., context_revision, require_pin)`），legacy overload 传 `require_pin=false`，strict overload 传 `true`，避免复制现有六参数 body；strict implementation 顺序：

1. 保留 authorization、`session -> effect` 锁序和现有 token 检查。
2. attempt/fence mismatch 先返回 `stale`，不查 pin、不写 event。
3. `context_revision IS NULL OR < 0` 在 token 匹配后以 SQLSTATE `22023` 报参数错误。
4. exact pin 缺失以 `P0001` 报 `v13: complete context pin missing`，零结算/事件写。
5. pin 存在但 revision 不匹配返回 `stale`，零写。
6. exact match 后沿用状态语义：终态 `replay`，正常结算 `accepted`。
7. 不比较当前 clock；旧但精确的 pin 允许完成，由投影按当前双 fences 吸收为 superseded。

completion payload 不加 `context_revision`。judge failure 的 `resolve/failed` 必须改为传 `source_effect_id = p_effect`，payload `{effect_id,path,origin_user_seq}` 保持原形；其他 human/tool/repair/replan/tool-call guard 不动。CE completion 无 pin，保持并行。

### 3.4 Superseded projection

定义：

```text
current(pin) = pin.context_revision = global_clock.revision
            AND pin.tools_revision = tools_meta.revision
```

这是全局 invalidation，不使用 scope meta。以下消费者逐项改为通过 mapping/effect helper 过滤；`source_effect_id IS NULL` 且没有 pin 历史的 legacy/synthetic 继续按原语义：

| 消费者 | 过滤位置 | 验收语义 |
|---|---|---|
| `v13_route` (`loop/advance.sql:123-130`) | 当前 turn finish 查询的 event WHERE | superseded llm/message/tool/result 不 finish；origin_user_seq 规则保留 |
| `v13_advance` (`plan_arm:471-508` 及 receipt/repair 分支) | tool/call 聚合、predecessor 与 repair/replan ledger 查询 | 旧 tool call 不 spawn；旧 harness evidence 不 retry/closeout |
| `v13_triage_block_explore_spawn` | tool/call existence query | 旧 call 不触发 explore guard；legacy call 仍遵守旧 guard |
| `v13_scheduler_hint` | 未完成 tool/call count | superseded call 不强制 wait |
| `v13_triage_fold_reason` | repair/replan count 与 cap-human existence | 旧 signal 不产生 cap action |
| `v13_cap_answer_anchor` / `v13_cap_human_answered` | human/responded event、source effect、anchor selection | 旧 human response 不释放 cap；六键 payload 不变 |
| `v13_harness_tail_gap` / `v13_tail_gap_cap_exempt` | harness effect 与 repair/replan evidence | 旧 signal 不制造 tail-gap 或 exemption |
| `v13_closeout` | unconsumed repair/replan/material/wake/approval receipt | 旧 evidence 不阻止终态、不进入 receipt |
| `v13_recover_idle` | repair/replan existence/fingerprint/nudge | 旧 signal 不生成 recover nudge |
| `v13_parse` (`economy:361-367`) | effect-backed resolve/failed failure count | 旧 judge failure 不耗 retry；advance 无 source synthetic 仍计数 |
| canonical state current-turn branch | 仅当前 turn machine-message branch | 旧消息不进入当前判断；历史 append-only 审计保留 |
| frontier gap | 不改 synthetic producer；helper 对无 effect 历史返回 legacy eligible | synthetic replan 不被误过滤 |

实施期必须在 loaded `pg_proc` 函数体上盘点上述事件/函数引用；每个命中必须归入该表或有单独测试证明 audit-only，禁止以较早被覆盖 SQL 定义代替有效函数分析。

### 3.5 Probe、snapshot、envelope

- `v13_probe` 七键增 `registry_revision`。
- 有效 `v13_judgment_envelope` 20 键增至 21 键，并在同一 statement snapshot 读取 fences；其余键、hash 公式和 envelope 语义不变。
- `v13_snap_of` 只投影 envelope 中同一 revision；不得再次读 clock。
- `v13_snapshot` wrapper 不改。
- `v13_advance` freshness tuple 增第八项 `registry_revision`，公开签名不改；缺 key 视 stale，缺 clock seed RAISE。
- `v13_effect_envelope`（有效定义 `v13/envelope/v13_envelope.sql:602-608`，由 `v13_advance` 在 `v13/plan_arm/v13_plan_arm.sql:726` 用于 judge 建账）必须继续剔除所有 freshness 水位键，新增的 `registry_revision` 也不得进入 request envelope/effect hash。否则 unrelated-scope registry write 会改变 `v13_effect_id` 身份（`v13/schema/v13_core.sql:168-182`），制造新 effect、断代 attempt 并留下孤儿在途行；第八键已经由 advance stale 负责弃批，不能把它重复带入业务 request。

实施前用 `rg` 盘点所有 envelope/snapshot exact-key、`needed_count`、candidate hash 和 `snap` 读取者；仅更新真实 20 键闭集断言。至少复核 `v13/filter/test_filter.py`、`v13/envelope/test_envelope.py`、`v13/resolve/test_resolve.py`、`v13/economy/test_economy.py`、`v13/plan_arm/test_plan_arm.py` 是否存在精确键断言。

### 3.6 Worker 协议、事务与锁

worker 使用具备 route 能力的 adapter/driver，而非直接假设 `v13_worker` 拥有 pin/context 权限。Global claim 走 route 身份；fair claim 必须走其 owner 身份，不能按 route 身份调用（route denial 仍是 42501）；两条身份线都使用对应的窄 helper 完成 pin/context 复核：

1. IDLE connection 开启短 claim 事务，按 global 或 fair 身份调用对应 claim，得到 `context_revision`；CAS 与 pin 同事务。
2. 通过 route helper 精确取 pin，确认 effect/attempt/fence/context_revision 对齐，并读取 tools_revision。
3. 以 pinned revision 调 `v13_registry_context(scope, revision)`；cache key 固定为 `(scope_id, context_revision, tools_revision)`。
4. 在 commit 前再次读取 `v13_registry_fences()`，若双标量变化则 rollback claim，让 effect 回到可领取状态；不锁 clock。
5. commit 后确认连接 IDLE，才执行外部 provider/tool IO。
6. 另开 completion 事务调用 strict 七参 overload，传 pin 的 context_revision；event mapping 与事件同事务完成。

registry writer 锁序保持 `clock -> meta -> sessions -> registrations`；fair claim 保持 advisory/root/child/effect；completion 保持 session/effect。pin/event mapping trigger 不锁 clock、不反向锁 session/effect。锁屏障使用真实 `pg_locks`/`pg_blocking_pids`，不用 sleep 推断。

## 4. 逐文件影响与执行索引

| Work item | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W0 有效对象与 prefix 锁定 | 固化 Stage 1 字节、effective `pg_proc` 和 ACL allowlist | 前缀 hash、前 39 文件、loader 41 项、CE pins 全部有静态证据；签名/owner/ACL 记录完毕 | `v13/load.py`; `v13/registry/v13_registry.sql`; Stage 1 setup/test | Stage 41 commit `5be562d` | S |
| W1 Overlay 基础 | 新增 pin/event-pin 表、索引、FK、immutable guards、event capture、fences/projection helpers | 两张表恰增；无额外 sequence/role/ACL；mapping 精确 attempt/fence；Stage 1 prefix validator 仍绿 | `v13/registry/v13_registry.sql` | W0 | M |
| W2 Claim 与 completion | 原子 pin claim、strict 七参、legacy/CE 兼容、ACL | global 六键、fair SEVEN；strict stale/replay/accepted/P0001/22023 行为和 rollback 通过 | `v13/registry/v13_registry.sql`; effective claim/completion definitions; `v13/fair_claim/test_fair_claim.py` | W1 | L |
| W3 Freshness | 八键 probe/snapshot/envelope/advance | 21-key envelope、八键 stale、双连接一致性和 unrelated-scope global stale 通过 | overlay replacements for effective manifest/filter/resolve/plan_arm functions; impacted tests | W1 | L |
| W4 Consumer projection | 所有真实控制消费者过滤 superseded | route/tool-call/repair-replan/human-cap/parse/closeout/govern/seam/triage tests pass；payload guards untouched | overlay replacements for effective loop/plan_arm/seam/triage/spawn/govern/economy/resolve consumers | W2, W3 | XL |
| W5 Guard 与 gate | 两段 delta、独立 consumer gate、fair/envelope tests | Stage 1 16 probes identity unchanged；consumer gate admitted by exact closure；no arbitrary delta | `v13/registry/setup_db.py`; `test_registry.py`; new `v13/registry/test_consumer.py`; fair tests | W1-W4 | L |
| W6 文档与 Phase 2 验收 | README/matrix/ledger 记录真实证据 | 51-item manifest, trace restore, matrix row, `S42R-*` entries and no prefilled claims | registry README; conformance matrix; deviation ledger | W5 | M |

### 4.1 Setup 与闭集

`v13/registry/setup_db.py:27-32,319-393,548-583` 改为 prefix snapshot -> Stage 1 validator -> overlay snapshot -> precise overlay validator。overlay allowlist 只包括两张 pin 表、其 indexes/FKs/immutable/capture triggers、批准 replacement functions 和明确 ACL；所有其他关系、函数、角色、sequence、数据库/schema ACL 必须与 prefix 相等。`pg_proc` 对照必须包含 `oid::regprocedure`、owner、`prosecdef`、`proconfig`、volatility、`pronargdefaults` 和 ACL；strict 七参的 `pronargdefaults=0` 是硬性断言。

Overlay 的 replacement allowlist 必须在 `setup_db.py` 与静态 gate 中逐名列出，而不是用前缀通配：`v13_probe(uuid)`、`v13_judgment_envelope(uuid)`、`v13_snap_of(jsonb)`、`v13_effect_envelope(jsonb)`、`v13_claim(text,integer)`、`v13_claim_fair(text,integer)`、五/六/七参数 completion body/wrappers、`v13_route(uuid,jsonb)`、`v13_advance(uuid,jsonb)`、`v13_parse(uuid)`、`v13_canonical_state(uuid)`、`v13_cap_answer_anchor(uuid,uuid)`、`v13_cap_human_answered(uuid,uuid)`、`v13_harness_tail_gap(uuid,uuid)`、`v13_tail_gap_cap_exempt(uuid,uuid)`、`v13_closeout(uuid,text,text,boolean)`、`v13_triage_fold_reason(uuid)`、`v13_triage_block_explore_spawn(uuid)`、`v13_recover_idle()`、`v13_scheduler_hint(uuid)`，以及新增 `v13_registry_fences`、pin insert/lookup/match、event-current/effect-current helper 和共同 completion implementation。实施期必须用 `pg_proc.oid::regprocedure` 对照该清单，确认没有借 overlay 创造第二个公开签名；`v13_advance` 的公开签名保持不变。

`test_registry.py:236` 的八函数计数只针对 prefix；`:285-293` 明确列出 Phase 1 四文件和新增 consumer gate 文件；`:689-700` 的 `native_events_and_probe` 必须改为断言 register/retire 后 `registry_revision` 推进而其余 freshness 键不变；`:871-875` 的 16 probes 名称与顺序不变。新 `v13/registry/test_consumer.py` 单独承载 Phase 2 probes，不向 Phase 1 计数混入。`v13/registry/README.md:147-218` 的 50 项 manifest 扩为 51 项，实际结果在测试后填写。

### 4.2 受影响的接口测试

原计划要求 fair claim 和 fair driver 的 SIX 常量改为 SEVEN；安装态复核后按 S42R-6 保留 Stage 39 前缀 gate 的 SIX，由独立 overlay consumer gate 验证 SEVEN；保留 route 42501。fanout/loop/pi parity 现有子集读不因增键重写，只有 exact-key assertion 盘点确认存在时才更新。envelope/filter/resolve/economy/plan_arm 测试逐一依据实际 key-set 盘点改动，不凭文件名猜测。

## 5. 测试矩阵与验收

| Gate | 必须证明 |
|---|---|
| `native_claim_pin` | global 六键、fair SEVEN、pin 一次/CAS、failed claim 不插 pin、pin 失败整体 rollback、clock seed 缺失 P0001 |
| `native_worker_protocol` | pinned context 双标量、三元 cache key、commit 前变化 rollback、worker 角色不能直读 pin/context |
| `native_strict_complete` | 7 参数成功/replay/token stale；NULL/负数 22023；missing pin P0001；revision mismatch stale；旧 pin 在 clock 前进后仍可 accepted |
| `native_legacy_complete` | 五/六参数 unpinned 调用继续工作；pinned effect legacy completion 的 event mapping；CE 无 pin 行为不变 |
| `native_event_pin_atomicity` | effect event + mapping 原子；exact attempt/fence；duplicate/immutable/malformed 分支；payload guards 不变 |
| `native_route_projection` | current finish；superseded llm/tool result 不 finish；origin_user_seq 保持 |
| `native_tool_call_projection` | superseded tool/call 不 spawn、不触发 triage、不计 scheduler；legacy/synthetic 保持 |
| `native_repair_replan_projection` | current signal 驱动 plan/seam/fold/closeout/recover；superseded 不驱动；frontier synthetic 保留 |
| `native_human_cap_projection` | current human response 释放 cap；superseded 不释放；六键 payload 不变 |
| `native_parse_closeout` | superseded resolve failure 不耗 retry；advance synthetic failure 仍计；旧 receipt 不阻塞 closeout |
| `native_global_freshness` | unrelated scope register/retire 使本 scope pin/advance stale，证明 global blast radius；meta 不冒充 source；同一 logical judge request 的 `v13_effect_id` 在 registry 写前后保持不变，证明 `v13_effect_envelope`/hash 排除了 registry_revision |
| `native_envelope_snapshot_consistency` | 21-key envelope、snap 同 revision、probe 八键、advance 第八键 stale、双连接一致 |
| `native_acl` | pin 表所有角色零表权；claim route-only；fair route 42501；strict completion route+spawn_owner；context recall+route；resolve 42501 |
| `native_lock_barriers` | `pg_locks`/`pg_blocking_pids` 证明无 clock 反锁、既有锁序不逆转、失败无半写 |
| `native_overlay_static` | prefix byte、前 39 SQL、loader 41 项、Stage 1 3-table/8-function、Stage 2 allowlist、无 extra files/roles |

保留原 50 项逐脚本回归和每项 trace restore；consumer gate 作为第 51 项。预期为 49 项 exit 0 加两个 goal_supervisor 契约 exit 1/2；任何退出码不符立即停止，不能以部分运行冒充全绿。

## 6. 错误、兼容与回滚

| 情况 | 固定行为 |
|---|---|
| clock/tools seed 缺失 | fences/probe/envelope/claim fail-closed P0001，不返回 0 |
| pin insert/FK/unique 失败 | 原 SQLSTATE 传播，CAS、pin、event 全回滚 |
| strict revision NULL/负数 | token 匹配后 SQLSTATE 22023，零结算写 |
| pin 缺失 | P0001 `complete context pin missing`，零写 |
| pin revision mismatch | `stale`，零写，可用正确 revision 重试 |
| attempt/fence mismatch | 优先 `stale`，不访问 pin |
| exact pin + terminal effect | `replay` |
| old exact pin + current clock advanced | completion 仍可 `accepted`；projection 视 superseded |
| legacy 5/6 参数 | 不要求 pin，旧调用继续工作 |
| malformed/missing projection anchor | false、不 RAISE；无 pin 历史的 legacy/synthetic eligible |
| CE effect | 无 pin mapping，CE 仍按 Stage 40 契约 |

Phase 2 是 additive overlay，无旧数据迁移。回退受支持方式是重建 Stage 1 数据库；在线回退先停 capture、恢复 Stage 1 函数，按维护策略保留新表，不直接 DROP 仍被 FK 引用的 pin/mapping，也不删除 append-only events。

## 7. 提交、推送与 Phase 3

2026-10-19 收尾 agent 权限边界（非用户全局覆盖）：经父协调会话 get_log
核对，首轮原文“你本轮先完成验收工件并报告结果，不 commit/push，我会在 review 后
处理最终提交与 v99 推送”是协调 agent 对收尾 agent 的交接要求，不是用户取消
全任务提交要求。本收尾 agent 只执行验收、更新工件并交接，不暂存/commit/push；
父协调 agent review 后负责按 AGENTS 与本节流程提交、提交后净树复验和 v99 推送。
AGENTS 的里程碑提交/推送要求仍适用于全任务，未被取消。本轮脏树验收不是
post-commit receipt；提交前路径/凭据与暂存审查、提交后净树复验由父协调 agent 完成。

1. W0-W5 完成后实际运行 registry gate、consumer gate、fair/envelope impacted tests 和 README 51 项全回归。
2. 更新 README 的真实结果、matrix 的独立 Phase 2 区段（不覆盖旧 Stage 42 goal_workflow 行）、ledger 的 `S42R-*` 条目；不得预填“通过”。
3. `git diff --check`、prefix hash、前 39 个 SQL、loader 41 项、CE byte pins、overlay allowlist 和凭据审查全部通过后，按路径 `git add`；禁止 `git add -A`/`git add .`/`--no-verify`。
4. 使用 `<版本>: <祈使句摘要>` 提交。提交后净树按同一顺序重跑并补 post-commit receipt；gate 全绿后立即提交该收尾工件。
5. 推送前核对当前 worktree 分支 v99、upstream 和 remote；按任务目标推送 v99 对应远端，不盲推 `origin/main`，不 force push/reset。远端分叉按 AGENTS 约定 fetch/rebase 后重试。
6. Phase 3 只做最终全回归、跨层证据、runbook/文档和最终偏差归档；不得新增 SQL、runtime behavior、claim/context 字段、测试逻辑或改变 Phase 2 ACL/guard。

## 8. 风险、权衡与最终证据

- **全局失效**：global singleton 简化祖先组合与 time-travel；registry 是低频管理面，unrelated scope 也使旧 pin/advance stale 是明确成本，必须写入测试和 `S42R-*`。
- **side-table**：增加 mapping 表/trigger，但不破坏 exact payload guard，并能按 attempt/fence 区分 re-claim；effect_id 单行或“取 latest pin”不满足迟到完成语义。
- **权限**：route-capable adapter + narrow definer helper 避免扩大 pin 表权限；strict completion 不超过既有 route/spawn_owner 面。
- **回滚**：overlay sentinel 可静态识别，Stage 1/CE 不动；在线回退不删除历史 events。

最终实施证据必须包括：effective source 对照表、被覆盖定义表、ACL 矩阵、global/fair/CE claim 键集差异、pin/mapping schema、每个 superseded consumer 的过滤位置、锁序屏障、51 项 manifest、Stage 2 matrix 行、`S42R-*` ledger 和提交/推送 receipt。所有结果以实际 gate 为准，本计划不预先宣称实现完成。
