# v13 native wait / poll / steer

| 项 | 值 |
|---|---|
| 日期 | 2026-10-09 |
| 状态 | 可实施合同。尚未写代码，尚未跑 gate。本轮用户要求进入可实施阶段；下面的取舍是该要求下的合同，不是更早澄清里的用户原话，也还不是审核通过 |
| 结果对照 | CE `agent_run` 的 poll / wait / steer。不移植 Swift |
| 里程碑 | 一个 Python 宿主里程碑。不注册 stage 45，不注册 stage 46，不追加 `SQL_LOAD_ORDER` |
| 提交信息 | 门绿之后才允许 `v13: add native wait poll steer`。本文件不授权现在提交 |
| 权威 | 已明确的用户要求及仓库约定 > 已有效的设计裁决 > 本文件。活体代码是现状，不是新增行为的授权 |

## Goal

用现有数据库动词提供 poll、wait，以及「后续一次判断能看见 steer 正文」。不移植 Swift。不新增推进实现，不抽出 `serve()` 的 claim / IO / complete，不新增事件类型或列，不改冻结的 `driver.py`。宿主调用现有 `advance()` / `serve()` 只在下面的唯一运行时入口前提下成立。本合同不证明多个既有入口可以安全共存。

交付的定义只有一个：本宿主在调用现有 `LoopDriver.serve()` 之前，把该条 steer 的正文和 `steer_event_id` 放进内存中的 `judgment` 层；`serve()` 里的 `llm(four_layers(), peek)` 因此带上它们。`effects.request` 不是交付通道。hash 不是交付。take 的返回值不是交付。

## 本轮关闭的取舍

用户要求进入可实施阶段。下列五项不再悬空。

| 项 | 合同 | 为何是这一条 |
|---|---|---|
| 执行所有权 | 新宿主只调用现有 `LoopDriver.serve()` / `advance()`，且同一目标在该期间不得有第二个入口。不重写领用、IO、complete | `serve()` 在 IO 之后才按 effect_id 领用（`driver.py:315-385`）。预 IO 领用是另一套执行，父计划 S3 不在必经路径（父计划 `:66`，`:670`）。`v13_claim(text,integer)` 不能按 target 领用（`v13_fanout.sql:266-303`） |
| wait | CE 风格。终态或 `pending_human` 立即返回。普通 seq 与 `cancel_pending` 只重读。外部 steer 单独返回中断 | CE `executeWait` 在 actionable 或超时 `<= 0` 时返回（`AgentRunMCPToolService.swift:1009-1046`）。`cancel_pending` 不是终态 |
| 终态 | `completed` / `failed` 允许用现有 `user/message` append 开新回合。`cancelled`、goal `stopped`、human pending、未消费 cancel，在 append 之前拒绝 | append 本身会复位前两种状态（`v13_core.sql:72-82`），且不复位 `cancelled`。不新增 resume |
| 水位 | 不新增。在途 `serve()` 按定义不是被转向的那一轮 | 现有 `attempt_no` / `fence` 不记录领用时的 seq（`v13_core.sql:109-112`）。父计划 Data Model 无新事件 type（`:579`）。本里程碑不需要该水位 |
| 装载 | 不改 `v13/load.py`，不改 `files_through` | `r1_load_append_ok` 拒绝删除行，并且下一号必须连续（`test_plan_arm.py:327-421`）。45 必须留空。因此本里程碑不加 SQL 文件 |

## 稳定偏差

这些不是待补的洞。审核通过后仍然成立。

1. 不能修改已经发出的 provider 请求。另一个进程里已经进入 `llm()` 的 `serve()` 看不见这次 steer。CE 有向当前运行派发的路径；本里程碑不补。所核证据不支持「CE 保证取消在途 provider 调用」。
2. 唤醒等待者不等于模型已收到正文。
3. 纯 `wait` 不调用 `advance` 或 `serve`。`steer --wait` 是组合：记录，最多一次 `step`，然后按 CE 风格等。它不会在等待期间循环 `serve`。那会变成第二个后台推进者。
4. 运行前提，不是测试安排：对同一目标 session，从本宿主进入 `take`、`advance` 或 `serve` 起，到该次调用返回止，不得再有 `RealChain.serve()`（`chain.py:139`）、`LoopDriver.run`（`driver.py:459`）或 `GoalSupervisor.tick`（`goal_supervisor/driver.py:201`，其内部会调 `settle_once`，`driver.py:468`）针对该目标运行。门不并发启动它们，只证明测试遵守这个前提，不构成产品保证。产品入口若不能保证该前提，本里程碑不得用于那种共存部署。父计划 `:661` 只约束第一份场景，不是已经禁用这些函数。
5. `pending_human` 是原生的「需要输入」。不宣称等于 CE 的 interaction 对象。
6. 默认等待 120 秒是本宿主的选择，不是 CE 事实。

## 不改的东西

不编辑：两份 `driver.py`、`v13_plan_arm.sql`、`v13_acl.sql`、`v13_envelope.sql`、stage 1–44 的 SQL、`v13/load.py`。不 `CREATE OR REPLACE` 活体 `v13_claim`。不创建 `v13/workflow_project/`。不把 45 或 46 放进 `STAGE_THROUGH`。不新增表、列、`effects.kind`、事件 type。不用文件承载控制状态。

活体路径判断是 `r1_phase_d_prefix_allowance` 里嵌套的 `allow()`（`test_plan_arm.py:422` 起，`allow` 在 `:516`）。它消费 `extra = tracked - protected`，只放行 `prefixes`、`stage40`–`stage44` 和 `fresh_ok`。`fb295ac` 的 `test_plan_arm.py` 没有这个函数，也没有 stage 40–44 的路径白名单；不得改一个基线里不存在的判断。`r0_source_scope` 只把基线已有函数钉死（`:903-916`），所以改这个后加的 `r1_` 函数是允许的扩展点。`r1_load_append_ok` 不改。

## 宿主

目录 `v13/native_control/`。四个跟踪文件，没有第五个：

1. `host.py`
2. `setup_db.py`
3. `test_native_host.py`
4. `README.md`

没有 `v13_native_control.sql`。`setup_db.py` 只装到 `ce_map`。库名 `ll_native_control_<pid>_<six-hex>`。拒绝已存在的库和 `agent_v13_` 前缀。只有该门的 `finally` 删除自己创建的库。

产品入口是这个宿主加它的 CLI，不是测试回调，也不是 `RealChain`。CLI 的 `steer --wait` 和库的 `step` 走同一段代码。调用方必须自己保证上面的唯一运行时入口前提；宿主不会替调用方禁用其他进程。

连接角色是 `v13_route`。该角色已有：`v13_agentctl_observe`、`v13_agentctl_steer`（`v13_agentctl_verbs.sql:341`）、`v13_append_event`、`v13_control_authorized`（`v13_acl.sql:479`）、`v13_should_run`（`v13_should_run.sql:735`）、`v13_quota_eligible`（`v13_quota_window.sql:301`）、`v13_goal_lifecycle`（`v13_govern.sql:1201`），以及对 `sessions` / `events` / `effects` 的 SELECT。缺任一执行权限则停，不改成 `SECURITY DEFINER`，不扩大授权。

### poll

`poll(conn, actor, spec) -> object`

一次短读事务调用 `v13_agentctl_observe(actor, spec)`，提交，原样返回。零写。不解释 hint。hint 不调用 `advance`。

### wait

`wait(conn, actor, spec, *, timeout_seconds=120.0, poll_interval_seconds=0.05, cancel_requested=None, since_seq=None) -> dict`

超时是有限数，排除布尔，范围 `0..3600`。间隔 `0.01..1.0`。非法则 `ValueError`，文案 `native wait timeout` 或 `native wait interval`。`since_seq` 缺省表示不检测 steer 中断；若给出，必须是 `-1` 到 `bigint` 最大的整数。

每次读取都在短事务里提交。sleep 时连接不得处于 idle in transaction。数据库错误传播，不把旧快照当成成功。

对 observe 可见行：`is_terminal OR pending_human` 为真则 actionable。NULL 当 false。`cancel_pending` 和 `last_event_seq` 变化都不是 actionable。

若 `since_seq` 已给出，只在 observe 可见的 session 上查询 `events`。存在 `type = 'steer/injected'` 且 `seq > since_seq` 时，结果是 `interrupted_by_steering`。不得用 `last_event_type` 代替这次查询。不见的 session 不查，避免未授权行泄漏。

空可见批返回 `unavailable`。不区分不存在与未授权。超时 0 返回 `poll`，不 sleep。否则 actionable 优先于中断、取消和超时。到点或取消时再读一次，actionable 仍然优先。游标和 `since_seq` 在一次 wait 内不变。

返回键恰为 `schema_version=1`、`reason`（`poll` | `interesting` | `interrupted_by_steering` | `timed_out` | `unavailable` | `cancelled`）、`snapshot`、`interesting_ids`。`interesting_ids` 只在 `interesting` 时非空。

### steer

`steer(conn, actor, target, text) -> object`

调用现有 `v13_agentctl_steer` 并提交。不 take，不 advance，不改 layers。返回该函数的收据。这是「已记录」，不是已交付。

### take

`take(conn, actor, target, steer_event) -> dict`

一个 `READ COMMITTED` 事务。隔离级别不对则回滚并报 `v13: native take isolation`。

1. `v13_control_authorized`。未授权或目标不存在：`v13: session not found`。零写。
2. `SELECT ... FROM sessions WHERE session_id = target FOR UPDATE`。再查授权。
3. 已有且仅有一条 `user/message`，其 payload 的 `steer_event_id` 等于该事件：返回 `noop`。`text` 为 JSON null。带上那条桥的 `input_event_id`。不重放正文。
4. 多于一条：`v13: native take ledger`。零写。
5. 目标 `status = cancelled`，或 `v13_goal_lifecycle` 为 `stopped`，或 observe 该行 `pending_human` / `cancel_pending` 为真：`v13: native take blocked`。零写。不把 take 当 resume。
6. 目标上存在 `ready`、`claimed` 或 `unknown` effect：`v13: native take busy`。零写。不改在途回合的锚。
7. 最早一条没有桥引用的 `steer/injected`，其 `event_id` 必须等于参数。否则 `v13: native take order`。不跳过更早的一条。
8. 源载荷必须是生产者那三键，`text` 去空白后非空。否则 `v13: native take payload`。
9. `v13_append_event` 追加 `user/message`。`source_effect_id` 为 NULL。载荷恰为 `schema_version`、`text`、`steer_event_id`、`steer_seq`。不写 `source_principal`。

返回键恰为 `schema_version`、`outcome`（`taken` | `noop`）、`target`、`steer_event_id`、`steer_seq`、`input_event_id`、`input_seq`、`text`。`noop` 的 `text` 为 null。调用方要正文时按 `input_event_id` 再读桥，不依赖第一次返回值。

这是「已建立输入锚」，不是已交付。同一事件的第二次 take 不换锚。

### step

`step(driver, actor, target) -> dict`

`driver` 必须是调用方已经构造的一个 `LoopDriver`。本函数不 `LoopDriver(...)`。不调用 `GoalSupervisor.tick`。

1. 读 `driver.layers`。四个键必须已在，且值都是字符串。缺则 `ValueError`，文案 `native step layers`。此时尚未 take。
2. `take`。`blocked` / `busy` / 没有未桥接 steer：原样返回，不 `advance`，不 `serve`。
3. `taken` 与 `noop` 都可以进入下面的重试判断。`noop` 只表示锚已在，不表示已交付，也不禁止崩溃后重试。
4. 若该目标已有 `origin_user_seq` 等于这次 `input_seq` 、且 `status` 属于 `succeeded` / `failed` / `unknown` / `cancelled` 的 effect：返回 `already_settled`。不 `advance`，不 `serve`，不把本次调用记为 `delivered`。正文仍从桥行读回。
5. 另一次短读。`v13_should_run AND v13_quota_eligible` 都为真才继续。否则 `deferred`。不 `advance`。
6. 按 `input_event_id` 读桥的 `text` 与 `steer_event_id`。读不到则失败，不 `serve`。
7. 若已有 `ready` effect，但它不是 `kind = llm` 且 `origin_user_seq = input_seq` 的最早一条：返回 `admitted_no_effect`，不调用 `serve`，也不 `advance`。人工 effect、tool effect、其他 origin 都走这条。不得借这次 step 触发 tool 副作用。没有 `ready` effect 时不在这一步返回。
8. 还没有匹配的 ready llm effect 时，调用 `driver.advance(target)` 一次（`driver.py:173`，它自己 `snap_of` 并提交）。再查一次。仍不是匹配的 ready llm effect：`admitted_no_effect`，不 `serve`。
9. 只有该时才改内存中的 `judgment` 值：原文字后追加 `[v13-steer ...]` 与 `[/v13-steer]`，中间是逐字正文和 `steer_event_id`。四个键名不合并，不回写 `v13_policies`。然后调用 `driver.serve(target)` 一次。
10. `finally` 恢复调用前的 `layers`。
11. 只有这一次 `serve` 进入了 `llm()`，且该次 `four_layers()` 的 `judgment` 含该正文和该 `steer_event_id`，才是 `delivered`。`serve` 返回 `none`、`blocked`，或处理了非 llm effect，都不是交付。`blocked` 时 effect 仍可能是 `ready`，后一次 step 可以再 `serve` 这一条；这是失败重试，不是成功完成后的第二次交付。

一次 step 最多 `advance` 一次、`serve` 一次。`serve` 内部已有的 provider 重试上限仍属于这一次调用，不另计一次 step。成功结算后的再次 `step` 必须走 `already_settled`，不得再进 `llm()`。

### steer_and_wait

库函数，不是 SQL。先 `steer` 并提交。等待失败不回滚已提交的记录。

`wait=false`：只返回收据。若还带了 `timeout_seconds`，忽略超时，警告文案：

```text
Ignoring timeout_seconds because wait=false; steering was accepted without waiting.
```

`wait=true` 或给出 `timeout_seconds`：`since_seq` 用刚返回的 steer `seq`，因此自己的注入不构成中断。然后最多 `step` 一次。`busy` / `blocked` / `deferred` 时不 `serve`。最后 `wait`。返回里分开 `recorded`、`step`、`wait`。不得把 `recorded` 或 `anchor` 写成 `delivered`。

## 装载放行

同一提交只改活体的 `allow()`（`test_plan_arm.py:516`）：给它增加一个精确路径集合，恰为上面四个文件。这个集合必须被 `allow()` 的 `extra` 循环消费，与 `stage40`–`stage44` 同级，不是目录前缀。不把 `v13/native_control/` 加进 `prefixes`。闭集外的 `v13/native_control/extra.py` 仍走现有拒绝，文案仍以 `outside the three prefixes` 开头（`:519`）。

不改 `r1_load_append_ok`。不改 `v13/load.py`。不改 `fb295ac` 已有函数的字节。`files_through("ce_map")` 仍是 44。45 不是键。46 不是键。

## 验收

Fake only。新测试源不得出现 `socket.`、`urllib`、`http.client`、`requests`、`httpx`。

```bash
UV_FROZEN=1 uv run python v13/native_control/test_native_host.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```

必须有的断言名：

`native_poll_is_observe`，`native_wait_actionable_only`，`native_wait_ignores_seq_and_cancel`，`native_wait_interrupt_queries_events`，`native_wait_own_steer_not_interrupt`，`native_wait_no_transaction_while_sleeping`，`native_wait_no_advance`，`native_steer_records_only`，`native_take_oldest_bridge`，`native_take_noop_hides_text`，`native_take_blocked_before_append`，`native_take_busy_before_append`，`native_take_reopen_completed_only`，`native_step_uses_existing_serve`，`native_step_layers_restored`，`native_step_delivery_is_llm_argument`，`native_step_not_effect_request`，`native_step_one_serve`，`native_step_noop_no_second_delivery`，`native_step_skips_non_llm`，`native_step_single_entry_required`，`native_steer_wait_separates_delivery`，`native_no_new_event_type`，`native_load_untouched`，`native_plan_arm_closed_set`，`native_frozen_driver_bytes`，`native_no_network`。

`native_step_delivery_is_llm_argument` 的 Fake 必须包在传给 `LoopDriver` 的 `llm` 上，并因 `judgment` 里的正文给出不同输出。只看 hash、只看 take 返回值、或由测试自己拼四层，都不算过。

`native_frozen_driver_bytes` 沿用现有 R1 哨兵：`driver.py` 去掉哨兵后仍等于 `fb295ac`。

门绿之后才把矩阵追加为 #91，台账追加 `S46-1`–`S46-4`。注意台账号不表示 `STAGE_THROUGH` 里有 46。

#91 不得宽于：

> Python 宿主在现有 observe 上提供事务外 wait，在现有 steer 上记录，并把一条 steer 桥进 `user/message` 锚后，经现有 `LoopDriver.serve()` 的 `four_layers()` 送出正文。不新增 SQL 装载项，不注册 stage 45 或 46，不改 `driver.py`。Wait 不授权 advance。在途 provider 调用不被改写。

| 台账 | 事实 |
|---|---|
| S46-1 | poll 是现有 observe。wait 的立即返回只看终态和 `pending_human`。`cancel_pending` 与任意 seq 不结束等待 |
| S46-2 | 桥是输入锚。交付只由匹配的 llm effect 进入 `serve()` 后的 `llm(four_layers(), peek)` 证明。`noop` 不回放正文。已终态的同 origin effect 使再次 step 返回 `already_settled`，不再进 `llm()` |
| S46-3 | 不新增事件、列或领用函数。在途完成不算被转向的那一轮，因为该次 `llm()` 没有这段 citation |
| S46-4 | 装载文件未改。45 与 46 都不是 `STAGE_THROUGH` 的键。放行只多一个四文件闭集 |

缺口写进 #91：无真实 provider、无无人值守、无 CE 进程内派发、不证明多入口共存、唯一运行时入口前提不满足则本里程碑不适用、无 stage 45、不把本里程碑写成 D-3 已整体闭合。

## 明确不做

- 不把 `user/message` 桥称为消费完成。
- 不把改 `effects.request` 当交付。追加 `steer/injected` 不会改变已有 request（`test_control.py:519`）；入队注释写明同 ID 不覆盖 request（`v13_core.sql:206-211`）。
- 不新增 `native/claim`。不改五参 / 六参的选择；五参已委托六参 NULL actor（`v13_acl.sql:459-494`）。
- 不在 SQL 里 `pg_sleep`、`LISTEN`、`NOTIFY`。
- 不把 `GoalSupervisor.tick` 当等待者或推进者。

## References

- `docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md`
- `v13/plan_arm/test_plan_arm.py`
- `v13/loop_driver/driver.py`
- `repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift`
