# v13 controller thin cut

一个里程碑。把已经存在的两层接上：纯函数读回执，`LoopDriver` 上的一条 sibling hop 只调用一次既有 `v13_advance`，让冻结信封选出的 `agentctl_steer` 经 SQL route 写到目标会话，再用既有 `v13_agentctl_observe` 读回。不建第二份 `v13_advance`，不建 `v13_agent_run`，不新增 SQL，不注册 stage 45。

本文件是实现合同。`docs/plans/v13-native-wait-poll-steer-2026-10-09.md` 是被拒绝的另一份合同，不要按它做。

## Goal

controller 路径上，模型选择表现为既有信封判断，推进表现为既有 `v13_advance` 的 sql 臂，下一步表现为一个不写库的纯函数。旧的 `run_turn` / `decide_exit` / `take_exit` 不再拥有这条路径。

## Done when

- `UV_FROZEN=1 uv run python v13/loop_driver/test_controller_vertical.py` 退出码 0。
- `UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py` 退出码 0。
- `UV_FROZEN=1 uv run python v13/agentctl_verbs/test_agentctl_verbs.py` 退出码 0。
- `UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py` 退出码 0。
- 纵向链断言成立：信封选出 `agentctl_steer` → 一次 `v13_advance` → sql 臂执行 handler → 目标会话有 `steer/injected` → `v13_agentctl_observe` 读回 → 纯函数返回 `run_now`。轨迹里没有 `serve`、`v13_complete`、`decide_exit`、`take_exit`、`GoalSupervisor.tick`。
- `v13/load.py` 的 `SQL_LOAD_ORDER` 与 `STAGE_THROUGH` 未改。44 个 stage 仍在，45 不存在。
- 收尾工件已更新：`v13/loop_driver/README.md`、控制面矩阵第 91 行、偏差台账 `TC-1`–`TC-4`。
- 不把 `actl_driver_untouched` 或「driver 字节没变」当成完成。

## Execution index

| # | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W1 | 纯函数与回执闭集 | 六个词、优先级、`ValueError` 文案被构造回执覆盖 | `v13/loop_driver/controller.py` | 无 | S |
| W2 | 一次 advance 的 controller hop | `progressed` 后单独读 observe；其它词不读、不 `serve` | `v13/loop_driver/driver.py` | W1 | S |
| W3 | 字节冻结改为只放行这一个方法 | 去掉哨兵和该方法后字节等于 `fb295ac`；第三个新文件仍被拒 | `v13/plan_arm/test_plan_arm.py` | 与 W2、W4 同一工作区，否则 `r0_source_scope` 红 | M |
| W4 | 纵向 gate | 信封链、waiting、stale、六词、禁 FakeLLM | `v13/loop_driver/test_controller_vertical.py` | W1、W2；库用 `load_stage(..., "agentctl_verbs")` | M |
| W5 | 收尾工件 | README 追加合同与断言名；矩阵 #91；台账 TC-1–TC-4 | README、两份 review | 四条 gate 先绿 | S |

不要拆成 S1/S2/S3 或 stage 45。W1–W4 是同一个里程碑的顺序，不是四个可独立关闭的 stage。

## Closed decisions

这些已经定死，实现时不要再选。

1. **模型选择走信封，不走 FakeLLM `tool_calls`。** `v13_route`（`v13/loop/advance.sql:110-163`）的工具名来自冻结信封的 `intent` / `tool` choice（`:116-117`）。llm 结果里的 `tool_calls` 只会被 `v13_complete` 记成 `tool/call`（`v13/acl/v13_acl.sql:408-410` 捕获，`:424-427` 追加），下一次 route 看到 `llm/message` 就 `finish`（`advance.sql:130-131`）。已绿的正向链是 `prepare_chain`（`test_agentctl_verbs.py:1262`）→ `v13_parse` → `v13_advance`（`actl_chain_full` 在 `:1315-1442`）。本 gate 复制这条链。不构造 FakeLLM，不把 `tool_calls` 接到 route。
2. **`run_controller_once` 调用 `advance` 恰好一次，永不调用 `serve`。** `agentctl_*` 是 `kind=sql`。活体 `v13_advance` 的 `WHEN 'sql'`（`v13/plan_arm/v13_plan_arm.sql:772-813`）在 advance 事务内 `EXECUTE` handler，插入已 `succeeded` 的 tool effect，返回 `progressed`。没有 ready effect 可领。`serve`（`driver.py:315-385`）只服务 `llm`/`tool`，这里调用它要么得到 `none`，要么误领别的 effect。
3. **新方法不进 R1 哨兵。** 哨兵继续只包 `settle_once`。`r1_driver_restore` 先核对函数体内的方法锚点，再剥该方法与哨兵，剩余字节等于 `fb295ac6c7459bb98dac57e37883af549d2d8a4c`。改 `run_turn` / `take_exit` / `serve` / `advance`，或再加第二个方法，必须失败。
4. **纯函数不碰库。** 不 import `LoopDriver`，不调模型，不睡眠，不写状态。未知形状是 `ValueError`，不是 disposition。
5. **不改** `v13/load.py`、`v13/loop/advance.sql`、`v13/plan_arm/v13_plan_arm.sql`、`v13/agentctl/**`、`v13/agentctl_verbs/**`、`v13/goal_supervisor/**`、`v13/goal_workflow/**`、`v13/external_exec/**`、`v13/ce_map/**`、`v13/loop_driver/setup_db.py`。不新增表、列、`effects.kind`、事件类型、GRANT。
6. **测试是 host。** 没有生产 `while`。一次决策最多一次 hop。
7. **observe 不含 steer 正文。** `pointers` 只连 `workflow/pointer`（`v13/agentctl/v13_agentctl.sql:114-121`）。快乐路径读 `last_event_type`、`last_event_seq`、`ok`、target id。正文只由测试直接读 `events`。
8. **`repair` / `replan` 是内存事实。** 不新增 SQL 扫描 `repair/required` 或 `replan/required`。生产 hop 把这两位置 `false`。构造回执覆盖这两个词。
9. **`run_controller_once` 接受调用方传入的 parse 结果。** 这样活体 `stale` 可达。方法自己抓的新 snap 看不到 watermark 变化之前的状态。

### 为什么不改 `run_turn`

`run_turn`（`driver.py:441-464`）拥有入口 advance、serve 循环、`decide`、`take_exit`。它没有生产调用者，只有 `test_loop_driver.py`。把它改成 controller 会把 B1 退出机和 provider IO 焊进本不该 serve 的路径，并破坏哨兵外字节。sibling 方法是最小接线。调查报告建议 3（`docs/investigations/v13-dev-structure-drift-2026-10-09.md`）里「改 `run_turn` / `take_exit`」不采用；采用的是建议 1 和 2：停止把「文件没被碰」当进展，只证一条纵向链。

### 为什么拒绝 native wait/poll/steer

那份计划是另一个 host：调用现有 `serve` / `advance`，冻住 `driver.py`，再加 poll/wait/steer 时间语义和 `user/message` 桥。本里程碑只接「信封 → sql 臂 → observe → 纯函数」。不做睡眠、不做用户消息桥、不声称 provider 已读到正文、不改 `effects.request`、不加 `take` / `step` / `steer_and_wait`。

## Current state

### 已有推进链

1. 根会话 `route_policy_name = controller`，version `1`。
2. `mock_from_needed` / `set_mock`（`v13/loop/test_loop.py`）填判断。
3. `v13_parse`（`v13/resolve/v13_resolve.sql:661`）返回顶层同时带 `envelope` 和 `remaining` 的 jsonb。`actl_chain_full` 把**整份** parse 结果传给 `v13_advance`，不是只传 `parsed["snap"]`（`test_agentctl_verbs.py:1307-1308`）。
4. 调用 advance 之前，绿链还会：

```sql
UPDATE sessions
   SET context_active_revision = v13_context_required(session_id)
 WHERE session_id = <root>
```

见 `test_agentctl_verbs.py:1329-1332`。`actl_chain_full` 把整份 parse 结果传给 `v13_advance` 在 `:1333`。gate 必须复制这一步，否则不要自己发明另一套 prelude。

5. 活体 `v13_advance` 是 `v13/plan_arm/v13_plan_arm.sql:332` 的最后一次 `CREATE OR REPLACE`。其后 stage 不替换它。`WHEN 'sql'`（`:772-813`）从 `p_snap->'envelope'->'tools_catalog'` 取 handler，事务内 `EXECUTE`，写已 `succeeded` 的 tool effect 与 `tool/result`，返回 `progressed`。活体返回词只有 `stale` / `waiting` / `terminal` / `progressed`（另有前缀与 triage 的 `waiting` / `terminal` 透传）。第五词不存在；若 Python 拿到 `None` 或其它文本，按下文 fail-closed 处理，不要去找活体来源。
6. `v13_agentctl_steer`（`v13/agentctl_verbs/v13_agentctl_verbs.sql:61-134`）要求调用者政策 `controller` / `1`，检查 `v13_control_authorized`，在**目标**会话追加 `steer/injected`。返回 `{schema_version, caller, target, event_id, seq}`。
7. `v13_agentctl_observe` 零写。行来自 `v13_observe`（`v13/observe/v13_observe.sql:44-55`）：`session_id`、`status`、`is_terminal`、`last_event_seq`、`last_event_type`、`pending_human`、`cancel_pending`，另有 `ordinal`、`parent_session_id`、`spawn_kind`、`turn_no`。后四列忽略。`EXECUTE` 只授给角色 `v13_route`（`v13_agentctl.sql:134-135`；角色定义在 `v13_core.sql:822`，与函数同名）。形状失败的包装多一个 `reason` 键（`v13_agentctl.sql:21-27`）。未授权 id 是 `ok=true` 且 `rows=[]`，不是 `ok=false`。

### 驱动器

`LoopDriver`（`driver.py:118`）拥有一条连接、显式 commit、`calls`。

- `advance`（`:173-178`）经 `_sql` 调用 `v13_advance` 并 commit，`calls` 追加 `("v13_advance", sid)`。返回的是裸 text，不是 jsonb 对象。
- `_read`（`:157-163`）执行 SQL 并 commit，**不**追加 `calls`，**不**检查 `ALLOWED_CONTROL_SQL`。observe 走 `_read`，因此不要把 `v13_agentctl_observe` 加进 `ALLOWED_CONTROL_SQL`（`:31-49`）或 `READ_HELPERS`（`:52-58`）。那两个元组本里程碑一个字不改。
- `serve`（`:315-385`）在事务外做 IO，再在同一事务里 claim + `v13_complete` + settlement advance，`calls` 追加 `("v13_complete", sid)`（`:380`）。只领 `llm` / `tool`。
- `run_turn`（`:441-466`）/ `take_exit` / `decide_exit` 保持原样。`GoalSupervisor.tick` 的推进只经 `settle_once`（`v13/goal_supervisor/driver.py:201`）。它还会调生命周期与租约辅助，但从不调 `serve` / `run_turn` / `v13_complete`，所以不进入本路径。

### 字节与路径冻结

- `r1_driver_restore`（`test_plan_arm.py:275-291`）现在要求剥掉唯一 R1 哨兵后 `driver.py` 等于 `fb295ac`。`:314` 规定哨兵外改 `run_turn` 必须失败。整段剥离证不出方法体变异：变异会随方法一起被剥掉，残余仍等于基线。机制见下文文件影响。
- `r0_source_scope`（`:847-928`）把 `fb295ac` 里已有的测试函数体冻住，`test_stage_bytes` 除外。它在 `:900-902` 调用三个 `r1_*`，并被 `test_plan_arm.py`、`test_agentctl_verbs.py:1583`、`test_loop_driver.py:931` 引用。`fb295ac` 的 `test_plan_arm.py` 没有 `r0_*` / `r1_*`。因此可以改这三个 `r1_*` 函数体。不可以改 `fb295ac` 已有函数体，不可以改模块级 import / 常量 / 非函数顶层（`:925` 的 `changed module setup`）。批准方法文本必须嵌在 `r1_*` 函数体里，不能是模块级常量。新函数名必须以 `r0_` 或 `r1_` 开头。
- `r1_phase_d_prefix_allowance`（`:422`）的 `allow()`（成员断言 `:517-519`，减法断言 `:520-521`）对 `extra` 里每个路径要求：以三个前缀开头，或落在 `stage40`–`stage44` 集合，否则 `"outside the three prefixes: " + name`。然后 `extra - known_names - stage40..44` 必须 `<= fresh_ok`。两个新文件两个断言都要放行。不要把 `v13/loop_driver/` 加进 `prefixes`。
- `v13/loop_driver/setup_db.py` 在 protected 字节里，且只 `load_stage` 到 stage 33。新 gate 自建库，不改这个文件。
- `test_loop_driver.py:909-931` 的 `r1_static_sentinel` 要求全文件里 `FROM sessions WHERE session_id = %s FOR UPDATE` 恰好一次，且哨兵开始之前次数为 0。新方法放在哨兵结束之后，且不得包含这句 SQL。

### 活体 waiting / stale

- **waiting：** `prepare_chain(cur, verb, False)` 然后 `v13_advance` 返回 `waiting`，human effect 的 reason 是 `triage_fail_closed`（`test_agentctl_verbs.py:1381-1412`，检查在 `:1400` 与 `:1406`）。这是本 gate 的活体路径。另一条已有路径不在本 gate 覆盖：会话上已有 `ready` / `claimed` effect 时，`v13_advance` 在 `v13_plan_arm.sql:404-467` 直接返回 `waiting`。`wait` 不等于「triage 拒判」。
- **stale：** `actl_steer_watermark`（`:1497-1526`）。先 `v13_parse` 子会话，再由父会话 `call_verb` 写入 `steer/injected`，再用**写入之前**的 parse 结果 `v13_advance(child, parsed)`，返回 `stale`。方法必须接受这份调用方 snap，否则这条活体证明不可达。不要退回「只测构造回执」。`snapshot_window` 是该测试模块 `:325` 的全库快照，不是 advance 的返回字段。

### 参考边界（不抄引擎）

- LoopX `decide_loop_disposition` 是纯转移（`loopx/loopx/control_plane/turn_driver/loop_controller.py:1-17`）。八词里的 `capability_action_required` 和 `stop` 不进 v13 本切。
- RP-CE `agent_run` 是一个 `execute(op)`（`AgentRunMCPToolService.swift:412-438`）。v13 对应面已是 SQL route 上的 `agentctl_*`。不建 `v13_agent_run`。
- D-A / D-A.3（`docs/reviews/v13-agentctl-da-rulings-2026-10-03.md`）：同一部署不得有两个独立推进者。本切不新增推进者。它不证明 `run_turn`、`GoalSupervisor.tick`、`RealChain` 不会并发碰同一目标。

## Design

### 调用图

```text
test host
  → mock_from_needed / set_mock
  → v13_parse                         # 整份 jsonb，不是 parsed["snap"]
  → UPDATE context_active_revision    # 复制 actl_chain_full:1329-1332
  → LoopDriver.run_controller_once    # 一次；本切没有 hop 前闸门
       → LoopDriver.advance           # 恰好一次；传入的 snap 原样进 v13_advance
            → v13_route
            → plan_arm WHEN 'sql'
            → v13_agentctl_steer      # 仅 progressed 的快乐路径
       → 若 progressed：_read v13_agentctl_observe
       → decide_controller_disposition(receipt)   # 方法内本地 import；此时还没有 disposition 键
  → 返回 receipt + disposition
```

没有生产循环，也没有 hop 前的纯函数调用。hop 之前不存在 `advance_word` / `observe` / `readback`，不能组回执。「host 只在 `run_now` 时再调一次 hop」只约束本切之外的串联；本里程碑不串联。构造回执测试直接调纯函数，不经过 hop。`waiting` / `terminal` / `stale` 不调用 observe，不调用 `serve`。

### `decide_controller_disposition`

文件：`v13/loop_driver/controller.py`。只依赖标准库。

```text
decide_controller_disposition(receipt: Mapping) -> str
```

返回且仅返回：`run_now` | `wait` | `user_action_required` | `repair` | `replan` | `terminal`。

回执顶层键必须恰好是：

```text
schema_version, caller, target, advance_word, target_seq_before,
observe, readback, repair_required, replan_required
```

| 字段 | 类型 | 来源 |
|---|---|---|
| `schema_version` | 整数 `1`，布尔 `True` 非法 | 合同 |
| `caller` | 小写规范 UUID 文本 | hop 的 `sid` |
| `target` | 小写规范 UUID 文本 | hop 的 `target` |
| `advance_word` | `progressed` \| `waiting` \| `terminal` \| `stale` | 一次 `advance` 的返回词 |
| `target_seq_before` | 整数 `>= -1`，布尔非法 | 调用方在 hop 前读到的目标 `max(seq)`，没有事件时为 `-1` |
| `observe` | observe 包装对象或 `null` | 仅 `progressed` 之后的原始返回；其它词为 `null` |
| `readback` | 归一化行或 `null` | 从唯一一行抽出的子集；不可用时为 `null` |
| `repair_required` | 布尔 | 生产 hop 恒 `false`；构造回执可 `true` |
| `replan_required` | 布尔 | 同上 |

`observe` 必有这五个键：`schema_version`、`ok`、`rows`、`hints`、`pointers`。允许且仅允许额外一个键 `reason`，而且只在 `ok` 为 false 时（活体形状失败包装，`v13_agentctl.sql:21-27`）。成功包装没有 `reason`；成功时出现 `reason`，或出现其它多余键，是 `controller receipt observe shape`。`ok=false` 仍是合法包装，然后走优先级 2 的 `repair`，不要把它当成形状错误。生产 hop 自己构造 `{ids, hint}`，`ok=false` 几乎不可达；真正可达的 repair 是 `ok=true` 且 `rows` 为空（未授权或不存在的 id 被整批隐藏）。

`hints` / `pointers` 只校验是列表，不参与判定。`pointers` 不是 steer 读回（`v13_agentctl.sql:112-124` 只连 `workflow/pointer`）。

`readback` 必须恰好含：`session_id`、`status`、`is_terminal`、`last_event_seq`、`last_event_type`、`pending_human`、`cancel_pending`。`session_id` 是小写规范 UUID。`last_event_type` 可以是字符串或 `null`。`cancel_pending` 只保存，不单独改变 disposition。

UUID 文本必须能被解析，且字符串形式与输入完全一致（小写）。与现有夹具写出的 uuid 文本对齐，不要另做大小写折叠。

#### `ValueError` 文案（逐字）

| 条件 | message |
|---|---|
| 不是 mapping | `controller receipt must be an object` |
| 顶层键不是闭集 | `controller receipt keys` |
| `schema_version` 不是整数 1 | `controller receipt schema_version must be 1` |
| `caller` 非法 | `controller receipt caller must be canonical uuid` |
| `target` 非法 | `controller receipt target must be canonical uuid` |
| `advance_word` 不在四词内 | `controller receipt advance_word` |
| `target_seq_before` 非法 | `controller receipt target_seq_before` |
| `repair_required` 不是布尔 | `controller receipt repair_required` |
| `replan_required` 不是布尔 | `controller receipt replan_required` |
| `observe` 不是 `null` 也不是合法包装 | `controller receipt observe shape` |
| `readback` 不是 `null` 也不是合法行 | `controller receipt readback shape` |
| observe 与 readback 结构不一致 | `controller receipt observe/readback mismatch` |

形状坏是错误，不是 disposition。下面这些是合法形状上的语义，返回 `repair`，不抛：

- `ok` 为 false
- `rows` 为空或不是恰好一行可用行
- 行的 `session_id` 不等于 `target`
- `last_event_seq` 不大于 `target_seq_before`
- 归一化字段与 `readback` 不一致

#### 优先级（命中即返回）

1. 形状不可验证 → `ValueError`。
2. `repair`：`repair_required` 为真，或 `advance_word == "stale"`，或 `progressed` 且读回不可用（上列语义）。`stale` 不要求 observe 对象；此时 observe / readback 必须是 `null`，否则形状错误。
3. `terminal`：`advance_word == "terminal"`，或读回 status 为 `completed` / `failed` / `cancelled`，或 `is_terminal` 为真。
4. `user_action_required`：`pending_human` 为真。
5. `replan`：`replan_required` 为真。
6. `run_now`：`progressed`，读回可用且序号前进，非终态，无 human，无 replan。非终态包括 `ready`、`waiting`、`blocked_unknown`（`v13_core.sql:14-15`）。`blocked_unknown` 在本切没有独立词；序号已前进且无 human 时就是 `run_now`。不把 LoopX 的 `capability_action_required` 加进来。这不表示 controller 会去唤醒该状态，只表示本切不发明第七个词。
7. `wait`：`advance_word == "waiting"`，且更优规则都未命中。`waiting` 包含 triage 拒判，也包含会话上已有 ready/claimed effect。本 gate 只造前一种。

必须另测的次序，防止实现把规则换位：

- repair 压过 terminal
- terminal 压过 `pending_human`
- `pending_human` 压过 replan
- replan 压过 `run_now`
- 仅 `cancel_pending` 为真不改变一次合法的 `run_now`

`waiting` 时 observe 为 `null`，因此没有行上的 `pending_human`。不要为了 waiting 去读 observe。

未知 advance 词在纯函数里是 `ValueError("controller receipt advance_word")`。驱动器方法若从 SQL 拿到四词之外的返回，另抛 `ValueError("controller: unsupported advance word: " + word)`，不调用 observe，不调用 `serve`，不把异常折成 `repair`。

### `LoopDriver.run_controller_once`

放在类内、`# R1_SETTLE_ONCE_END` 之后、类的最后一个方法。本地 import，禁止改文件顶层 import。剥掉该方法和哨兵后的字节必须等于 `fb295ac`，包括不要留下多出来的空行。

```text
run_controller_once(self, sid, target, *, snap=None, target_seq_before) -> dict
```

- `sid`：交给 `v13_advance` 的会话。
- `target`：期望被观察的会话。快乐路径上它是子会话，不是 root。
- `snap`：有则原样传给 `self.advance(sid, snap)`。无则 `self.advance(sid)`，走现有 `snap_of`。活体 stale 与快乐路径都必须传入。传入的对象是 `v13_parse` 的整份结果。
- `target_seq_before`：必填整数，`>= -1`，非布尔。
- 返回回执加上一个键 `disposition`。调用纯函数时还没有这个键。先判定，再把键加进返回值。纯函数看到多余键必须 `ValueError`。

步骤：

1. 在任何 SQL 之前校验 `sid`、`target`、`target_seq_before`。非法则 `ValueError`，零 SQL。
2. `advance` 恰好一次。
3. 词是 `waiting` / `terminal` / `stale`：不 observe，不 `serve`。`observe` 与 `readback` 为 `null`。`repair_required` 与 `replan_required` 为 `false`。本地 import 纯函数，返回。
4. 词是 `progressed`：用 `_read` 做一次已提交的短读，与 advance 不共享事务：

```text
SELECT public.v13_agentctl_observe(%s::uuid, %s::jsonb)
```

参数：`sid`，`{"ids": [target], "hint": false}`。然后归一化唯一行，组回执，调纯函数，返回。

5. 其它词，包括 SQL 返回 `None`：`ValueError("controller: unsupported advance word: " + word)`。不 observe，不 serve。这是防御，不是第五个活体词。
6. 不捕获 `advance`、observe 查询、或纯函数的异常。`v13_advance` 抛出的 snapshot/session 错误原样传播，不重试，不折成 `repair`，不发第二次 advance。连接上已打开的事务按现有 rollback 纪律处理。

正常成功时 `LoopDriver.calls == [("v13_advance", sid)]`。任何非异常结果都不得出现 `("v13_complete", sid)`。方法体不得出现对 `serve`、`run_turn`、`decide`、`decide_exit`、`take_exit`、`complete`、`GoalSupervisor` 的调用。

生产方法不把 steer 正文或 event id 放进回执。

### 纵向 gate

文件：`v13/loop_driver/test_controller_vertical.py`。没有单独的 `setup_db.py`。

库名形如 `ll_controller_vertical_<pid>_<six-hex>`。拒绝 `agent_v13_` 前缀，拒绝丢掉已存在的库。`load_stage(server, DB, "agentctl_verbs")` 一次装到 stage 41。不要再 `run_psql` 动词 SQL（`CREATE FUNCTION`，不是 `OR REPLACE`，装两次会失败）。`finally` 只丢自己创建的库。连接用 `server.get_uri(DB)`，与 `test_agentctl_verbs.py` 一样是超级用户。不 `SET ROLE`，不加 GRANT。超级用户绕过 `EXECUTE` ACL，这只证明 gate 能调用，不证明产品角色。文件头写：

```text
Run: UV_FROZEN=1 uv run python v13/loop_driver/test_controller_vertical.py
```

夹具从 `v13.agentctl_verbs.test_agentctl_verbs` import `prepare_chain`、`shrink_catalog`、`call_verb`、`controller_pair`、`snapshot_window`，从 `v13.loop.test_loop` import `set_mock` 与 `mock_from_needed`。这两个模块的连接都在函数内，`main` 有守卫，import 无副作用。不要调用它们的 `main`，也不要在 gate 文件里复制 `INSERT INTO` 语句。`test_loop_driver.py:252-275` 的 `static_check` 扫描 `v13/loop_driver/*.py`，命中 `insert into effects/events/sessions/artifacts` 或 `update sessions set status` 会红。`context_active_revision` 那句更新不是 `set status`，可以写在 gate 文件里。`driver.py` 新方法的源码不得包含 `test_loop_driver.py:283-285` 的禁词（`v13_recover_idle`、`v13_spawn_subsession`、`v13_child_pointer`、`v13_workflow_resolve`、`v13_open_session`、`v13_insert_nudge`、`v13_goal_resume`、`v13_cancel`、`v13_route(`）。

1. controller / 1 根会话，追加 user message，创建一个子会话。
2. 快乐路径 `with_override=True` 等价：提交既有 override，否则会落进 `triage_fail_closed`。
3. 把目录收成 `spawn_subsession` 加 `agentctl_steer`。
4. `mock_from_needed` 设置 `intent=sql_answer`、`tool=agentctl_steer`、`target` / `text` 的 stated 与 param、以及 gate/risk。正文非空，与 `prepare_chain` 一样用固定测试文本（现有链用 `"steer-text"`）。
5. `v13_parse`。保留整份结果。
6. 复制 `context_active_revision` 更新。
7. hop 前读目标 `COALESCE(max(seq), -1)`。

快乐路径调用：

```text
run_controller_once(root, child, snap=parsed, target_seq_before=before)
```

断言标签（`check` 的 label 必须逐字出现）：

| label | 含义 |
|---|---|
| `controller_chain_progressed` | `advance_word == "progressed"` |
| `controller_chain_route_sql` | 根上最新 `turn/route` 的 `action == "sql"` 且 `tool == "agentctl_steer"` |
| `controller_chain_tool_effect` | 根上恰好一个 `agentctl_steer` effect，`succeeded`，error 为空；不是 `ready` |
| `controller_chain_observe_ok` | observe `schema_version == 1`，`ok is True`，`rows` / `hints` / `pointers` 是列表 |
| `controller_chain_target_match` | readback `session_id == child` |
| `controller_chain_last_event_type` | `last_event_type == "steer/injected"` |
| `controller_chain_last_event_seq_moved` | `last_event_seq > before` |
| `controller_chain_steer_text` | 测试自己读目标 `events`，基线之后有预期正文；生产代码不读这列 |
| `controller_chain_no_serve` | `calls` 里没有 serve |
| `controller_chain_no_complete` | 没有 `("v13_complete", root)` |
| `controller_chain_one_advance` | `calls == [("v13_advance", root)]` |
| `controller_chain_disposition` | 返回的 `disposition == "run_now"`，且去掉该键后纯函数返回同一个词 |

waiting（无 override，复制 `:1381-1405`）：

| label | 含义 |
|---|---|
| `controller_waiting_word` | `advance_word == "waiting"` |
| `controller_waiting_disposition` | `wait` |
| `controller_waiting_triage` | 仍是 `triage_fail_closed`，证明用的是现有拒绝臂 |
| `controller_waiting_no_observe` | 返回的 observe 为 `null` |
| `controller_waiting_no_serve` | 无 serve |
| `controller_waiting_no_complete` | 无 complete |

stale（复制 `:1497-1526` 的顺序：先 parse 子会话，父会话直接 `v13_agentctl_steer` 抬水位，再）：

```text
run_controller_once(child, child, snap=parsed_child, target_seq_before=before_child)
```

这一跳本身不负责注入。注入发生在 hop 之前，否则 snap 不会 stale。

| label | 含义 |
|---|---|
| `controller_stale_word` | `advance_word == "stale"` |
| `controller_stale_disposition` | `repair` |
| `controller_stale_supplied_snapshot` | 传入的是写入前的 parse 结果，不是方法自抓的 snap |
| `controller_stale_no_observe` | observe 为 `null` |
| `controller_stale_no_serve` | 无 serve |
| `controller_stale_no_complete` | 无 complete |
| `controller_stale_zero_write` | import 的 `snapshot_window` 在 advance 前后相等（全库快照，不是返回字段） |
| `controller_stale_seq_plus_one` | 注入步把 child `next_seq` 恰好加 1（`:1518-1520`）；advance 本身不再加 |
| `controller_stale_tokens` | 既有 human effect 的 request / hash / attempt / fence / lease 不变（`:1526`） |

纯函数不连数据库。标签：

| label | 回执 | 结果 |
|---|---|---|
| `controller_disposition_run_now` | progressed，行可用，序号前进，非终态，无 human，两事实为假 | `run_now` |
| `controller_disposition_wait` | waiting，observe/readback 为 null | `wait` |
| `controller_disposition_user_action_required` | 合法 progressed 行，`pending_human` 真 | `user_action_required` |
| `controller_disposition_repair` | stale，或 progressed 读回空/错目标，或 `repair_required` 真 | `repair` |
| `controller_disposition_replan` | 合法 progressed 行且 `replan_required` 真 | `replan` |
| `controller_disposition_terminal` | status 三终态之一，或 `is_terminal`，或 `advance_word == "terminal"` | `terminal` |
| `controller_disposition_unknown_shape` | 非 mapping 或缺键 | 上表对应 `ValueError` |
| `controller_disposition_unknown_advance_word` | 四词之外 | `ValueError("controller receipt advance_word")` |

另加五个次序断言，label：`controller_priority_repair_over_terminal`、`controller_priority_terminal_over_human`、`controller_priority_human_over_replan`、`controller_priority_replan_over_run_now`、`controller_priority_cancel_pending_ignored`。

源码与运行都不得使用 FakeLLM、provider、`socket`、`urllib`、`http.client`、`requests`、`httpx`，不得用 `tool_calls` 选工具。判断夹具只走现有 mock。不打开网络套接字（`AGENTS.md`）。

### 数据流与事务

- `advance` 保持现有 commit。sql 臂的 effect 与 `steer/injected` 在那次提交里。
- observe 是之后另一次短读，`_read` commit 之后才做纯函数判定。
- 两者之间不持有打开的事务。
- 本方法没有 provider IO，也没有 advance 返回之后的写。
- observe 失败不回滚已经提交的 steer。查询异常传播。合法但不可用的读回变成 `repair`，不得伪装成 `run_now`。
- `progressed` 单独不是交付。必须有目标读回。即便如此，也只证明 durable 记录，不证明 provider 读过正文（台账 S41-D3 仍未关闭）。

## File-by-file impact

### `v13/loop_driver/controller.py` — 新

纯函数、私有校验、六词、上列文案。不 import 驱动器或数据库。

### `v13/loop_driver/driver.py` — 只加一个方法

不得改：`EXIT_WORDS`、`NOT_EXIT_WORDS`、`ALLOWED_CONTROL_SQL`、`READ_HELPERS`、`__init__`、`advance`、`serve`、`_settlement_advance`、`four_layers`、`decide`、`take_exit`、`run_turn`、`settle_once`、哨兵内容、顶层 import。

### `v13/loop_driver/test_controller_vertical.py` — 新

上面的 gate。不 import `v13/loop_driver/setup_db.py`。

### `v13/plan_arm/test_plan_arm.py` — 只改 `r1_*` 函数体

`r1_driver_restore` 的函数体里放一份方法源码字节锚点（局部变量，不是模块级常量）。名字就叫 `APPROVED_CONTROLLER_METHOD`。内容是类内 `run_controller_once` 的完整源码，含它的前导缩进，不含方法前后多出来的空行。以后改方法必须同时改这份锚点，否则负例与正例一起红。

顺序：

1. 保持一对哨兵、`settle_once` 在哨兵内、哨兵内那句 `FOR UPDATE` 恰好一次。
2. 哨兵外恰好一个 `def run_controller_once`。零个或两个以上立即失败。方法在哨兵内也失败（哨兵外计数为 0，或哨兵块里出现这个 def）。
3. 抽出的方法文本必须逐字节等于 `APPROVED_CONTROLLER_METHOD`。空方法、改一个字节、与锚点不一致，都在剥离之前失败。不要先剥再比基线——那样变异会跟着方法一起消失，残余仍等于 `fb295ac`。
4. 只有第 3 步通过才剥掉该方法（含随它增加的空白）和哨兵。剩余字节等于 `fb295ac` 的 `driver.py`，且不含 `FOR UPDATE`。

`r1_freeze_positive_proof` 保留现有失败例（空哨兵、`run_turn` 改名、哨兵外再泄漏一个 `v13_advance`），并加上：找不到 `run_controller_once`、方法出现两次、方法被挪进哨兵、方法体与锚点差一个字节。

`allow()` 两处都要认识精确集合：

```text
{
  "v13/loop_driver/controller.py",
  "v13/loop_driver/test_controller_vertical.py",
}
```

第一处断言（`:518`）把集合成员当成放行，否则第三个文件仍以 `"outside the three prefixes: "` 失败。第二处（`:520`）从 `extra` 里减去这个集合，与 stage40–44 同样处理，避免撞上 `fresh file outside accept_unattended.py`。不要改 `prefixes`。负例：`v13/loop_driver/third_controller_file.py` 被拒，且消息以 `outside the three prefixes` 开头。两个新文件在被跟踪之后必须被接受。`r1_load_append_ok` 与 `r0_source_scope` 对 `load.py` 的「不得追加」保持原样。

`docs/plans/` 与 `docs/reviews/` 不在 `git ls-files -- v13` 的 `extra` 里，不必放进这个集合。

### `v13/loop_driver/README.md` — 只追加

不要改写现有 B1 / B6 / `settle_once` 节。文件在 `r0_source_scope` 的 readmes 排除集里（`test_plan_arm.py:888-889`），不在字节钉死循环里。追加一节，写明：

- 方法签名，以及「传入整份 parse 结果，不是 `parsed["snap"]`」
- stale 必须由调用方传入写入前的 snap；方法自抓的新 snap 到不了活体 stale
- 一次 advance、不 serve、不进 `run_turn`
- observe 请求形状 `{ids: [target], hint: false}`
- 回执与六词；`blocked_unknown` 不另开词
- 不授权无人值守，不证明 provider 消费正文
- 上列全部 `check` label，含 `controller_stale_seq_plus_one` 与 `controller_stale_tokens`
- 命令 `UV_FROZEN=1 uv run python v13/loop_driver/test_controller_vertical.py`

现有断言名列表（README `:76` 与 `:78`）保留。新名字写在追加节，不要塞进旧段落中间，也不要改 `## B6` 表。

### 矩阵与台账

`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` 在 #90 之后追加 **#91**，不要用 native 计划的 S46 措辞：

> Controller thin cut：判断信封驱动一次既有 `v13_advance` sql 臂执行 `agentctl_steer`，目标经既有 `v13_agentctl_observe` 读回，纯函数返回六词之一。无 FakeLLM，无 serve，无生产循环，无新 SQL，无 stage 45。

缺口栏写明：不证明 provider 交付、无人值守、多入口共存、wait/poll/steer host、D-3 正文消费。测试落点在四条命令实际退出码 0 之后才写成 ✅。未跑过不要写通过。

`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` 在 Stage 44 之后追加，标签不与 `S44-5` 冲突，也不暗示 stage 45：

| # | 事实 | 处置 |
|---|---|---|
| TC-1 | 六词纯函数，固定优先级；repair/replan 是内存事实。`blocked_unknown` 在序号前进且无 human 时落 `run_now`，不新增词 | 接受。不扫描 SQL。不引入 `capability_action_required` |
| TC-2 | 信封 → `v13_parse` → 一次 `v13_advance` → sql `agentctl_steer` | 接受。不是 FakeLLM tool_calls |
| TC-3 | observe 证明目标身份、序号前进、`last_event_type=steer/injected`；无 serve/complete | 接受。正文只由测试读 `events`。不闭合 S41-D3 |
| TC-4 | 精确两个新文件放行；loader 不变；无 stage 45；不声称 provider 或无人值守 | 接受 |

### 明确不改

`v13/load.py`、`v13/loop_driver/setup_db.py`、`advance.sql`、`v13_plan_arm.sql`、agentctl 两目录、`goal_supervisor`、`goal_workflow`、`external_exec`、`ce_map`。`goal_workflow` 的 `DECIDE_BANNED` 留作历史夹具，不要把它拷进新 gate，也不要为了本里程碑去删它。

## Risks

- **无迁移。** 回滚只删两个新文件、删一个方法、还原冻结测试与文档。无库回滚。
- **超级用户。** gate 不证明 `v13_route` 以外的产品角色能 `EXECUTE` observe。不放宽 GRANT。
- **stale 依赖传入的旧 snap。** 方法不重试、不自抓、不在 stale 之后 serve。下一步是 `repair`。修复策略不在本切。
- **`progressed` 不是交付。** 不写「provider 已看到正文」。
- **单入口未证。** D-A.3 仍然有效。本 gate 不证明其它推进者已停止。
- **重复调用无账本。** 本里程碑每个构造 hop 只调一次。第二次会看到被第一次改变的会话，不在合同内。
- **冻结边界。** 改 `fb295ac` 已有函数体或 `test_plan_arm.py` 的模块级 setup 会红（`changed existing test` / `changed module setup`）。`r0_source_scope` 本身是后加的 `r0_`，名字前缀允许改它，但本里程碑不动它。放行只发生在三个 `r1_*` 函数体里。

## Implementation order

1. 写 `controller.py` 与构造回执用例（可先放在新 gate 文件里，库还不必起来）。
2. 在 `driver.py` 哨兵后只加 `run_controller_once`。本地 import。不改其它符号。
3. 改三个 `r1_*` 函数，使当前工作区被放行，负例仍失败。与步骤 2、4 同时存在，否则 `test_plan_arm.py` 或 `test_loop_driver.py` 会因字节或未跟踪路径变红。
4. 写纵向 gate：自建库、`load_stage(..., "agentctl_verbs")`、快乐路径、waiting、stale、禁 FakeLLM。
5. 跑四条命令。红了只在批准文件里修。不要改 SQL、`load.py`、`setup_db.py` 或旧驱动器方法来逼绿。
6. 四条都退出码 0 之后，追加 README、矩阵 #91、台账 TC-1–TC-4。未实跑不要写 ✅。
7. 文档改完再跑一遍四条命令。
8. 按 `AGENTS.md` 收尾：按路径 `git add`，禁止 `git add -A` / `git add .`。一次提交，信息沿用 `<版本>: <祈使句摘要>`，例如 `v13: wire controller hop to existing agentctl sql route`。然后 `git push origin main`。不要 force-push。不要把本计划与其它未完成线卷进同一次提交。

## Verification

退出码 0 为通过。四条都要跑，不只新文件：

```bash
UV_FROZEN=1 uv run python v13/loop_driver/test_controller_vertical.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
UV_FROZEN=1 uv run python v13/agentctl_verbs/test_agentctl_verbs.py
UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py
```

| 命令 | 必须证明 |
|---|---|
| `test_controller_vertical.py` | 信封链而非 tool_calls；一次 sql hop；observe 读回；无 serve/complete；活体 waiting；传入旧 snap 的活体 stale；六词与优先级；无 FakeLLM |
| `test_plan_arm.py` | 剥哨兵加剥方法后等于 `fb295ac`；重复/缺失/挪进哨兵失败；两个新文件被放行；第三个新文件被拒；`load.py` 未追加 |
| `test_agentctl_verbs.py` | 生产者未改仍绿 |
| `test_loop_driver.py` | 旧驱动器行为仍绿；`r1_static_sentinel` 仍见哨兵内唯一 `FOR UPDATE`；`r0_source_scope` 仍返回该基线 commit |

任何结果都不得声称：生产循环、provider 交付、in-flight 打断、wait/poll/steer host、无人值守、D-3 已闭合、stage 45、多个独立推进者可以共存。

## References

- `docs/investigations/v13-dev-structure-drift-2026-10-09.md`
- `docs/designs/v13-agent-control-minimal-form-2026-10-02.md`（`actl_driver_demoted`）
- `docs/reviews/v13-agentctl-da-rulings-2026-10-03.md`
- `docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:298-302`
- `docs/plans/v13-stage42-goal-workflow-2026-10-08.md`（历史禁调，不是模板）
- `docs/plans/v13-native-wait-poll-steer-2026-10-09.md`（本切拒绝）
- `v13/plan_arm/v13_plan_arm.sql:332`、`:404-467`、`:772-813`
- `v13/loop/advance.sql:110-163`
- `v13/loop_driver/driver.py:31-58`、`:118`、`:157-178`、`:315-385`、`:441-466`
- `v13/agentctl_verbs/test_agentctl_verbs.py:1262`、`:1315-1442`、`:1329-1333`、`:1381-1412`、`:1497-1526`
- `v13/plan_arm/test_plan_arm.py:275-324`、`:422`、`:516-542`、`:847-928`
- `loopx/docs/reference/protocols/turn-loop-controller-v0.md`
- `repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:412-438`

## Open questions

无。审查里会改合同的点已经选定，不再挂起：

- 没有 hop 前闸门。
- 方法锚点嵌在 `r1_driver_restore` 函数体内，匹配之后才剥离。
- gate import 生产夹具 helper，不复制 `INSERT`。
- observe 允许失败包装上的 `reason`；`rows=[]` 是 repair。
- `blocked_unknown` 落 `run_now`，不加第七个词。
- stale gate 保留 `seq +1` 与 tokens。
- 矩阵用 #91，台账用 `TC-*`，都不占用 stage 45。
