# v13 Phase C 增补计划：R1 点名 T0 同事务结算入口，再重开 M3 监督进程（2026-10-01）

**实施中。** 用户于 2026-10-01 接受本计划并下令开始实施。R1 与 M3 仍未跑通前，不得写成运行时 exit_0。R0 已完成并推送，不在本文件里重验。不得删除或覆盖旧证据。

Oracle 静态复审 `48DC40D4-7091-424C-9C3A-CBF1B59F7BF0`：两路均 **附条件接受**，无新 P0。P1 已写入 §3.5、§3.7、§5.2、§6.1、§7。§9 六条默认已经后续 Oracle 组裁决 **全部接受**（见 §9）。**整份计划已被用户接受，按 §7.3 先提交本文档，再实现 R1，再实现 M3。**

## 1. 授权、基线与和既有合同的关系

用户授权：重新设计 R1/M3 增补计划；先调查与复审，不直接实现 M3。本文件覆盖重开计划 `docs/plans/v13-long-loop-phase-c-reopen-advance-plan-2026-10-01.md` §6 留下的未决合同，不改写 Phase 0/A/B/C 历史计划正文，不改写 R0 计划正文。

### 1.1 活体基线

规划时仓库：

| 对象 | 值 |
|---|---|
| `HEAD` / `origin/main` | `bd72b93d2cfaa2f83730fb7e76c5643b3d450b37` |
| R0 实现提交 | `a2cabf10d362991ceae126884a4bd534a6f8574e` |
| R0 计划提交 | `9a9396f` |
| Phase C M2 | `fb295ac6c7459bb98dac57e37883af549d2d8a4c` |
| 工作区相对 origin/main | 无已跟踪改动。未跟踪的调查、草稿、`prompt-exports/` 不得加入任何提交 |

`a2cabf1..HEAD` 对 `v13/loop_driver`、`v13/goal_supervise`、`v13/plan_arm`、`v13/load.py` 的 diff 为空。R0 之后的提交是并行 v15/v16 线，不改变本期 v13 字节。

规划时文件 SHA-256（文件哈希，不是 `pg_get_functiondef`）：

| 文件 | SHA-256 |
|---|---|
| `v13/loop_driver/driver.py` | `1fd88f70ffff1593680e63c4f67fb046f0ffa8bcd5127cbe0f99f083361d6a98` |
| `v13/loop_driver/v13_loop_driver.sql` | `0b20d7daf066d0c66c71c6f065e5efe883a8719eaf0566b0f4f71f65a2bc0f15` |
| `v13/goal_supervise/v13_goal_supervise.sql` | `712391374cdbefb4ba017b74ba77fa54779da135d9ba364c196a3881756449a5` |
| `v13/load.py` | `5c064ddb525607ca9aeac4c37127893426c13f937dd96d1ad3797537bf5bae69` |
| `v13/plan_arm/v13_plan_arm.sql` | `244a23e8935250a43f3a9cf1684f065746185f78397a0ba8df45e9f864cd9592` |

`driver.py` 与 `goal_supervise` SQL 仍等于 R0 重开计划钉住的指纹。`plan_arm` SQL 是 R0 哨兵块之后的活体，不得在 R1 再改。

R0 十条 gate 已在 `a2cabf1` 实跑 exit 0：`plan_arm` 104、`frontier_gap` 59、`goal_supervise` 172。提交后再跑 `plan_arm` / `frontier_gap` / `goal_supervise` 仍为 0。历史证据行保留在 `docs/reviews/v13-long-loop-phase-c-conformance-matrix-2026-09-29.md` 与同目录偏差台账。本计划不覆盖那些数字。

### 1.2 权威顺序（冲突时按此，调查作废）

1. 本轮用户范围：只做调查与计划；接受前零运行时改动；无真实 provider；无外部 IO。
2. Phase 0 `docs/plans/v13-long-loop-plan-2026-09-28.md` 的用户决定与 T0–T7。本文引用，不改写。
3. 已接受 Phase A，尤其 §5.6、§7.4、T0 结算与 B1 五出口。本文消费 `loop_driver`，不改写 Phase A 计划文件。
4. 已接受 Phase B。本期不编辑 workspace 打开者/接受/exec。
5. 已接受 Phase C `docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md` 的 M2 SQL 与 §4.7/§7.3 监督合同。本文不得再替换 `v13_advance`，不得给 `goal_supervisor` 分配加载键或 SQL。
6. 已接受 R0 重开计划。R0 只关闭根 `ready`/`claimed` 阻断分支的 harness 收据前移。R0 的接受不延伸为 R1/M3 接受。
7. 本文件的 R1/M3 选择。父可整组退回。退回前不得实施。

`docs/investigations/v13-m3-stop-why-and-how-to-advance-2026-09-25.md` 属于 stannum 0.4 的另一条 M3，与本期无关。

### 1.3 R0 已经关闭与仍然打开的停点

R0 已关闭：根会话在 `v13_advance` 的 `ready`/`claimed` 分支可幂等补一张当前 harness 前驱的 `turn/material_spent`，然后仍 `waiting`。human/workspace 不被绕过派发。child 不向上锁根。

R0 明确未关闭、本计划必须面对：

- `run_turn` 不是已接受的 M3 入口。
- T0 禁令在 `loop_driver` 里跨已提交事务，与后续 `v13_advance` 不在同一把根锁下。
- Phase A 前缀（stage 33）没有 `v13_unpaid_harness_turn` / `v13_harness_settle`（stage 38）。
- unknown / cancel / stale / terminal 仍可能在 ready/claimed 之前返回；waiting 不自动等于收据成功。
- `goal_supervisor` 目录不存在；旧草稿已停放且不是起点。
- `unattended_continuation` 在一跳入口被点名且 T0 拒绝成立之前，不得写成 `exit_0`。点名之后该断言仍按 Phase C §7.3：进程以 `v13: supervisor: ask_user` 非零退出，直到父改这一项本身。

## 2. 本计划冻结的默认（接受前可整组退回）

下列默认写入合同，便于复审。接受本计划即接受这些默认。若父只要其中一部分，退回后改写本节，不要口头覆盖。

| ID | 默认 | 不是 |
|---|---|---|
| D1 | 点名的一跳入口是 `LoopDriver.settle_once(self, sid) -> str`。只接收根 `session_id` | 不是 `run_turn`，不是 `serve`，不是 `take_exit`，不是 `decide`，不是 `v13_harness_settle` 的 Python 别名 |
| D2 | 返回词是结算/advance 闭集，外加 `skipped_failed`。闭集至少包括 `skipped_failed`、`waiting`、`terminal`、`stale`，以及活体 `v13_advance` 在该路径上实际返回的其它词。测试钉死实跑词，不发明新词 | 不是 B1 的 `wait`/`user_action`/`provider`/`stopping`。禁止把 `waiting` 改写成 `wait` |
| D3 | `settle_once` 与监督 tick 都不调用 FakeLLM/FakeTool，不做文件系统/网络 IO。每 tick 至多一次 `v13_advance`，且只发生在 `settle_once` 内。Phase C 具名入口提到的 FakeLLM、以及 R0 重开「最多一次 IO hop」，**都不授权**结算提交后再 `serve`/`v13_complete`。hop 计数对监督 tick 为 0 次 provider IO | 不是 Phase A pump。监督进程不调用 provider。`fake_hop_persists_then_observed` 证明的是这次 advance 写下的 SQL 行被下一 tick 看见 |
| D4 | 一个 tick 的唯一结算者是 `settle_once`。不得再调用 `v13_harness_settle`，不得再调用 `run_turn` | `v13_harness_settle` 仍留给 M2 SQL 测试。生产监督路径禁用 |
| D5 | `settle_once` 只用 stage ≤33 已有函数：`v13_goal_lifecycle`、`v13_harness_predecessor`、`v13_probe`、`v13_context_required`、`v13_advance`、以及 `sessions` 行锁。源码不得出现 `v13_unpaid_harness_turn`、`v13_harness_settle`、`v13_observe_fold`、`v13_notify_project`、`v13_goal_ambiguous_hold`、`v13_goal_lease_once`、`v13_replan_gap_insert` | 不新增加载键，不改 `v13/load.py`，不给 `loop_driver` SQL 增加 VOLATILE 函数 |
| D6 | T0 重读、根锁、（如有）effect 锁、以及至多一次 `v13_advance` 必须在同一未提交事务里。返回后连接必须 `IDLE`，不得跨 IO 持锁 | 不得先 `lifecycle()`/`snap_of()` 提交，再另开事务 `advance()` |
| D7 | 当前夹具是 DB owner/superuser。SQL `EXECUTE` 与 `v13_control_operator()` 分开断言。不声称产品 operator 可执行 | 不把 superuser 绿写成角色闭合 |
| D8 | 旧草稿 `prompt-exports/phase-c-m3-parked-2026-10-01/` 标明非证据、非起点。M3 从本文件与已接受 Phase C 规格重写，不恢复该目录，不把它的 HOLD/skip/非零输出当验收 | 不 `git add` 该目录 |

D2 是对 Phase C §4.7「一个会话 id 进，返回 Phase A 已有的一个出口词」的明确修正：B1 出口词与 `v13_advance` 返回词不是同一词表。本计划不复制 B1 出口机，因此不能假装返回 B1 词。

## 3. R1：点名入口的冻结算法

R1 是独立实现里程碑。它只让 Phase A 前缀也能证明 T0 同事务拒绝，并给出 M3 可 import 的名字。R1 通过不等于 M3 通过，也不等于无人值守完成。

### 3.1 适用范围

`settle_once(sid)` 只接受根：`sessions.session_id = sid AND parent_session_id IS NULL`。child 调用立即失败并零 advance：不得 `v13_plan_map_root` 后去锁根，不得扫描整树。监督进程永远传根 id。

`run_turn`、`serve`、`take_exit`、`decide`、`t0_advance_blocked`、`_settlement_advance` 的既有字节保持不变。Phase A 的 55 个断言不得删除或放宽。`complete` 后的结算 advance 仍按 Phase A 在 complete 同一事务内发出；那不是本入口，也不计入「每 tick 一次」。

R1 精确变更面（相对 `fb295ac`/`bd72b93` 的 `driver.py`）：

| 符号 | 变更 |
|---|---|
| `LoopDriver.settle_once` | 新增，仅哨兵块内 |
| 哨兵块内的局部帮助函数 | 仅服务于锁、重读、IDLE 检查；不得成为第二入口 |
| `run_turn` / `serve` / `take_exit` / `decide` / `t0_advance_blocked` / `_settlement_advance` / `advance` / `snap_of` / `_snap_with` | 字节不变 |
| `ALLOWED_CONTROL_SQL` | 字面不变 |
| `READ_HELPERS` | 字面不变 |
| `v13_loop_driver.sql` / `load.py` | 字节不变 |
| `r0_source_scope` | 扩展冻结证明，见 §6.1 |

### 3.2 固定伪代码（实现必须按此顺序，不得靠短路猜测）

```
settle_once(sid):
  若连接已有未提交事务: 失败，零 SQL 写
  SET TRANSACTION ISOLATION LEVEL READ COMMITTED
  若 isolation 不是 read committed: 失败，零 advance
  LOCK sessions WHERE session_id = sid FOR UPDATE
    -- 锁语句必须与 v13_goal_stop 所锁的那一行相同：sessions.session_id = p_sid
  重读 parent_session_id；非 NULL 则失败，零 advance
  重读 v13_goal_lifecycle(sid)
  pred := v13_harness_predecessor(sid)
  若 pred IS NULL: 不调用 v13_advance；提交；返回约定的 quiet 词（见 3.4）
  LOCK effects WHERE effect_id = pred FOR UPDATE
  按活体 harness 未付谓词重读该行（kind=tool、is_harness_tool、request_ok、
    origin_user_seq=last_user_seq、status=succeeded、finish 或 progress 且无同源
    repair/required 与 replan/required、尚无同源 turn/material_spent）
  任一不匹配: 不调用 v13_advance；提交；返回约定的 quiet 词
  stored := 该行 result（原样 jsonb，不增删 failed/route）
  若 lifecycle = stopped 且 stored->failed 非 JSON null 且键存在:
    不调用 v13_advance；提交；返回 'skipped_failed'
    -- false / 0 / 空串 / 非空文本都走这条；键缺失与 JSON null 不走
  同事务构造 probe 快照（可复用 _snap_with，但不得先 commit）
  word := v13_advance(sid, snap)     -- 本入口唯一一次 advance
  提交
  断言连接 IDLE、本后端不再持有该 session 行锁
  return word
```

锁顺序固定：`sessions[sid] → 读 parent → 选 pred → effects[pred] → 全谓词重读 → T0 → advance`。不存在 pred 时不锁 NULL id。重读不匹配则零收据、零新 effect。意外数据库错误正常失败/回滚，不用 `EXCEPT`/`try` 吞掉后改成 `waiting`。

T0 判断只用锁内重读的 `stored` 与 `lifecycle`，不用入口参数里伪造的 snap，也不用 `snap_of` 已提交缓存。这与 `v13_harness_settle` 的存储快照绑定同义，但实现不得调用该函数。

`v13_advance` 自己还会再锁 `sessions[p_sid]`；同一事务内是同一把锁，不得因此另开事务。

### 3.3 禁止事项

- 不得调用 `v13_complete`、`v13_claim`、claim UPDATE、`serve`、`run_turn`、`v13_goal_stop`。
- 不得 INSERT/UPDATE effects/events/sessions/artifacts（`_snap_with` 里已有的 `context_active_revision` 同步除外，且必须留在本事务内）。
- 不得写 `turn/material_spent`；收据仍只由 advance 臂或 R0 阻断块写出。
- 不得在返回前做任何 IO hop。
- 不得把 `max_serves=1` 的 `run_turn` 包装成这个入口。现有 `run_turn` 在 `max_serves=1` 时仍可能：入口 advance + serve 后 settlement + provider requeue，三次 `v13_advance`。
- 不得新增 SQL 文件、加载键、策略版本、GRANT 角色故事。

### 3.4 quiet 与未付

quiet = 本跳不调用 `v13_advance`。无未付合格前驱时 `settle_once` 必须 quiet。有未付合格前驱且未被 T0 挡住时，必须恰好一次 `v13_advance` 并接受其返回词。

无候选时的返回词冻结为 `waiting`（与现有阻断等待同一词，不是 B1 `wait`）。测试区分：quiet 的 `waiting` 零新 `v13_advance` 调用；有候选的 `waiting` 必须检查同源收据是否增加。

### 3.5 两连接 stop/advance 交错（确定性，不用 sleep 猜胜者）

至少两条，都用 `pg_blocking_pids` 确认等待后再放行，轮询间隔不是胜者依据：

1. **stop 先提交。** 连接 A 锁根并保持。连接 B 进入 `settle_once` 并被观测到等待该锁。A 在锁内写入 stopped（合法 `v13_goal_stop`；若 goal busy 则夹具先清 ready/claimed/unknown 或使用已 stopped 根）并把该 harness `result.failed` 写成非 null，提交。B 获得锁后必须 `skipped_failed`，零 `v13_advance`，零新收据，零 `resolve/failed`。
2. **settle 先持锁。** 连接 B 已持根锁尚未 advance。连接 A 的 `v13_goal_stop` 等待。B 完成 `v13_advance` 并提交。A 随后按活体 stop 合同进行（busy 则 RAISE，已停则 lifecycle）。不得出现「T0 检查时未停、advance 时已停却仍调用 advance」。

调用计数用独立连接 `track_functions` 或测试仪表，不改产品 SQL。零 advance 不得只靠 `receipt=0` 代替。

夹具不得真空：

- **stop 先提交** 必须使用**已经 stopped** 的根，或在持锁连接里先清掉 ready/claimed/unknown 使活体 `v13_goal_stop` 能成功。测试先断言 A 的 `v13_goal_stop` 返回了 `goal/stopped` 载荷（或等价成功），再放行 B。不得在 A 实际 RAISE `v13: goal busy` 的情况下声称 stop 赢了。
- **settle 先持锁** 的夹具允许 A 随后 `goal busy`（B 的未完成 effect 仍在）。该负例要断言的是 busy/RAISE，不是 stop 成功。两条夹具的前置状态写进断言名，不能互相冒充。

### 3.6 IDLE 证明

`settle_once` 返回后，同一 psycopg2 连接：

- `connection.info.transaction_status` 为 IDLE（psycopg2 `TRANSACTION_STATUS_IDLE`）；
- 另一连接对同一 `sessions` 行 `FOR UPDATE NOWAIT` 成功。

测试过程中不得把锁或事务带到 Fake IO。本入口本来就没有 Fake IO。

### 3.7 回滚与顺序证明

`v13_advance` 或锁内重读若 RAISE：整笔 `settle_once` 事务回滚，连接回到 IDLE 且仍可复用。下一次 `settle_once` 必须重新 `LOCK`、重新读 lifecycle/result，不得沿用失败事务里的 snap、pred 或 T0 判断。不存在跨尝试的 T0 时间戳。

顺序断言（可用 SQL 日志或 `calls`，不得靠 sleep）：同一事务内，`sessions ... FOR UPDATE` 先于 `v13_goal_lifecycle`，后者先于（若发生）`v13_advance`。T0 命中 `skipped_failed` 时，日志里不得出现 `v13_advance`。

### 3.8 `waiting` 且未付的可见失败面

`settle_once` 仍返回活体词（`waiting` / `stale` / `terminal` 等）。它不把未付解释成成功，也不抛出「未付」异常——发现与失败属于监督 tick。

R1（无监督进程）测试：unknown/cancel/stale 夹具上 `settle_once` 返回上述词之一，且 `v13_harness_predecessor` 对应行仍无同源 `turn/material_spent`。断言名必须含 `unpaid_remaining`，不得写成 `waiting_ok`。

M3 tick：在 `settle_once` 返回且该候选仍被未付谓词看见时，tick **失败**，进程/调用打印并退出非零，消息恰好 `v13: supervisor: unpaid_remaining`。不是 `v13: supervisor: ask_user`，不是 Python `waiting` 当作出口。此时零 lease/recover/replan/stop。`skipped_failed` 不走这条。

## 4. 加载合同

| 前缀 | `load_stage` | 文件数 | 本期必须能跑 |
|---|---|---|---|
| Phase A `loop_driver` | `loop_driver` = 33 | `SQL_LOAD_ORDER[:33]` | R1 全部新断言 + 既有 55 条 |
| Phase C `goal_supervise` | `goal_supervise` = 38 | 全部 38 | 既有 172 条；SQL 不变 |
| M3 `goal_supervisor` | 无键；setup 仍装到 `goal_supervise` | 38，无新 SQL | M3 断言 |

`v13/load.py` 全字节不变。表尾仍是 stage 38 `goal_supervise`。发现 M3 必须有 SQL 或必须替换 `v13_advance`：停。

R1 的 `loop_driver` gate 必须断言：

```sql
SELECT to_regprocedure('public.v13_unpaid_harness_turn(uuid)') IS NULL
   AND to_regprocedure('public.v13_harness_settle(uuid,uuid,uuid,jsonb)') IS NULL
```

并且 `driver.py` 源码不含这些名字。监督进程（M3）可以调用 `v13_unpaid_harness_turn` 做只读发现，然后把根 id 交给 `settle_once`；不得把发现到的 id 再交给 `v13_harness_settle`。

未付谓词对齐：M3 用 `v13_unpaid_harness_turn` 的 0/1 行与 `v13_harness_predecessor` 对照。R1 在 stage 33 用同一套活体 SELECT（前驱 + 未付过滤）而不包装成新 SQL 函数。两条路径选中的 `effect_id` 必须相同；对不上停，不在 Python 里另写胜者。

## 5. M3：监督 tick（R1 被接受并落地之后）

M3 是第二个实现里程碑。目录 `v13/goal_supervisor/`，无 SQL，无加载键。不复制 B1 出口机。不调用真实 provider。不 import `run_turn`。

### 5.1 允许的 SQL 与 Python

生产 `driver.py` 允许：

- 只读：`v13_unpaid_harness_turn`、`v13_scheduler_hint`、`v13_notify_project`、`v13_observe_fold`、`v13_goal_ambiguous_hold`、`v13_should_run`、`v13_plan_current`、`v13_selected_todo`、`v13_wake_is_satisfied_v1`、`v13_frontier_project`、`v13_goal_lifecycle`
- 写入：`v13_replan_gap_insert`、`v13_goal_lease_once`、`v13_recover_idle`（仅当加载后正文仍不 INSERT effect、不调用 `v13_advance`）、`v13_goal_stop`（仅第 10 步）
- Python：`LoopDriver.settle_once`（唯一结算者）
- 写入：`v13_replan_gap_insert`、`v13_goal_lease_once`、`v13_recover_idle`（仅当加载后正文仍不 INSERT effect、不调用 `v13_advance`）、`v13_goal_stop`（仅第 10 步）
禁止：`v13_advance`、`v13_harness_settle`、`v13_complete`、`v13_evidence_check`、`v13_plan_writer`、`v13_plan_commit_entry`、`v13_plan_admit`、`v13_open_session`、`v13_spawn_subsession`、`v13_child_pointer`、`v13_enqueue_effect`、`v13_claim`、`v13_cancel`、`v13_insert_nudge`、`v13_interaction_offer`、`v13_llm_tool_calls`、`v13_goal_resume`、`LoopDriver.run_turn`、`LoopDriver.serve`、`LoopDriver.take_exit`。禁止 INSERT/UPDATE effects、events、sessions、artifacts。禁止写 `turn/material_spent`。

`static_check` 扫生产 `driver.py`：`v13_` 调用超出上表即失败。注释里出现名字不算调用。测试文件可以调用活体函数做夹具。

### 5.2 一次 tick，上界 `supervisor_max_ticks = 2`

无睡眠，无 `pg_cron`。事务内无文件系统 IO、无网络。每个写步骤自己的事务。未付结算保持自己的事务（即一次 `settle_once`，其内部一事务）。顺序冻结如下，只此一份，不得在别处再写相对顺序：

1. 终态则返回，不消费 `request_stop`。
2. **在任何其它写调用之前**决定唯一结算者 = `settle_once`。有未付候选则调用一次并提交。提交之后本 tick 不再结算。human 待应答不得跳过这次结算。
3. **wrapper/入口返回后的强制解释（本计划对 Phase C §4.2 的收口）：**
   - `skipped_failed`：立即安全结束本 tick。零 `lease_once`、零 `recover_idle`、零 `replan_gap_insert`、零 hop、零 `v13_goal_stop`。不把 `request_stop` 当成已消费。
   - 其它返回词：若同一候选仍被 `v13_unpaid_harness_turn` 看见（包括返回 `waiting`/`stale`/`terminal` 但收据未付），本 tick **失败**，消息恰好 `v13: supervisor: unpaid_remaining`。这不是成功等待，也不是 ASK_USER。unknown 墙、cancel 墙、stale 快照都走这条。
   - 返回 `waiting` 且该候选已消失（R0 根 ready/claimed 补收据后的合法状态）：结算成功，继续第 4 步。
4. human 仍为 `ready` / `claimed` / `unknown` 才挡住后续步骤，并返回 `waiting`。不 skip、不 complete、不 cancel 该 human。这次返回不消费 `request_stop`。谓词不得用 `v13_pending_human` 或 `LoopDriver.human_pending` 代替，因为它们不计 `unknown`。
5. 未 stopped、非终态、且水位投影 `omitted_complete` 为真时，才可能插入一条还没有义务的缺口。一次 tick 至多一条。调用前 `READ COMMITTED`。第 4 步已返回则本步不执行。
6. 读 ambiguous hold。有 hold 行：`deliver=false`；**不**调用接受函数、`v13_recover_idle`、`v13_goal_lease_once`、任何 hop；不把行标成 `unknown`/`ready`/`succeeded`/`failed`。路径继续被 Phase B 未终态扫描占住。
7. 无 hold、根未 stopped、非终态时，`lease_once` 可以零次。若调用，只更新传入的那一个有限租约 `p_effect_id`。infinity/NULL/opener 零更新。
8. 无 hold 时允许至多一次 `v13_recover_idle`。返回值只进进程内报告，不得导致入队、claim、改 lease、标 unknown、再调用 advance。
9. 读 hint 与 notify，再读 observe。
10. 只有本 tick 没有在第 3/4 步失败或返回 `waiting`，且 `request_stop` 为真、根不是终态时，才走 `v13_goal_stop`。不要求出口词 `stopping`。不加 B1 出口词。`request_stop` 不得先 hop 再停；本 tick 本来就没有 hop。

replan 相对 stop 的顺序只冻结在第 5 步与第 10 步：有 waiting/失败早退则两者都不跑；否则 insert 先于 stop。断言 `replan_insert_before_stop_only` 钉这一处，不在别处重复发明顺序。

### 5.3 旧 M3 断言全部保留

Phase C §7.3 列出的名字全部保留，语义按本节解释，不得删、不得改成跳过：

`b6_rows_present`，`fourth_duty_none_or_live_name`，`unattended_not_claimed_by_loop_alone`，`quiet_does_not_call_advance`，`unpaid_progress_calls_advance_once`，`unpaid_finish_calls_advance_once`，`second_settlement_no_second_receipt`，`wait_reject_not_settled`，`stopped_failed_snap_no_advance`，`stopped_without_failed_key_still_settles`，`multiple_unpaid_candidates`，`human_pending_does_not_skip_settlement`，`planning_does_not_call_advance`，`monitor_quiet_does_not_call_advance`，`human_wait_no_skip`，`workspace_complete_does_not_call_advance`，`settlement_does_not_dispatch_claimed_workspace`，`driver_does_not_write_material_spent`，`unattended_continuation`，`fake_hop_persists_then_observed`，`provider_word_does_not_start_second_machine`，`recover_not_on_claim_path`，`recover_return_does_not_enqueue`，`no_lease_loop`，`replan_insert_before_stop_only`，`notify_dto_no_event`，`observe_no_answer`，`static_check`，`no_real_provider`，`policy_version_still_3`，`stage_bytes`。

新增、不得替代上表的断言：

- `named_entry_is_settle_once`
- `settle_once_not_run_turn`
- `t0_same_txn_root_lock`
- `stop_advance_interleave_stop_wins`
- `stop_advance_interleave_settle_holds`
- `connection_idle_after_settle_once`
- `phase_a_prefix_has_no_unpaid_helper`
- `skipped_failed_safe_return_no_lease_recover_replan`
- `waiting_with_unpaid_remaining_is_failure`（unknown/cancel/stale 各一条夹具；M3 消息恰好 `v13: supervisor: unpaid_remaining`）
- `human_ready_claimed_settles_then_waits`（R0 后应能绿）
- `human_unknown_does_not_count_as_success`
- `request_stop_not_consumed_on_human_wait`
- `request_stop_does_not_hop`
- `hold_skips_accept_recover_lease_hop`
- `execute_vs_control_operator_separated`
- `no_parked_draft_import`

`unattended_continuation`：一跳已点名且 T0 拒绝已由 `stopped_failed_snap_no_advance` 证明之后，**仍非零退出** `v13: supervisor: ask_user`。这一行不是 `exit_0`。其它断言失败时报告那个失败，不得用 ASK_USER 覆盖。

`fake_hop_persists_then_observed`：一次 tick 调用 `settle_once`，结果落成 SQL 行（收据和/或 advance 产生的既有效应），下一次 tick 看见，不依赖人，不调用真实 provider。标绿不把矩阵的 `unattended_continuation` 写成 `exit_0`。

`human_pending_does_not_skip_settlement` 的正例夹具用 human `ready` 或 `claimed`（R0 已能付收据）。unknown 走新增失败态断言，不混进这条正例。

## 6. 源码保护

活体冻结的真正中心不是各目录自己的 `git diff HEAD`，而是 `v13/plan_arm/test_plan_arm.py` 的 `r0_source_scope()`。它被 `plan_arm`、`frontier_gap`、`goal_supervise` 三个 gate 调用。当前硬条款：

- 基线对象 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 必须存在。
- `git ls-files v13` ⊆ 该基线 `v13/` 树。**任何新的已跟踪 `v13/` 文件都会让三条 gate 变红**，包括未来的 `v13/goal_supervisor/**`。
- 除三份测试、三份 README、以及 `v13/plan_arm/v13_plan_arm.sql` 外，基线里每一个受保护文件都必须与 `fb295ac` 字节相等。**`v13/loop_driver/driver.py`、`test_loop_driver.py`、`README.md`、`v13_loop_driver.sql`、`v13/load.py` 都在这个集合里。**
- 那三份测试文件：既有 `FunctionDef` 正文不变（`test_stage_bytes` 除外）；`main`/`run` 只允许追加 `r0_*()` 调用；**新的顶层函数名必须 `r0_` 前缀。**

因此：只改 frontier/goal_supervise 的 `stage_bytes` 路径列表，而不改 `r0_source_scope`，R1 一改 `driver.py` 就会红。本计划把扩展该辅助函数列为 R1 的第一允许项，而不是「8 行改 driver」。

### 6.1 R1 允许路径（一个提交）

1. `v13/plan_arm/test_plan_arm.py`：只扩展 `r0_source_scope()`（该函数相对 `fb295ac` 本就是新增，改它不违反既有函数字节冻结）。新增条款必须仍先通过全部现有 R0 哨兵/SQL 还原证明。允许：
   - `driver.py` 不再走整文件相等，改走 §6.1 末的 R1 哨兵还原证明；
   - 把 `v13/loop_driver/test_loop_driver.py` 与 `README.md` 加入测试/README 例外集，按 AST 冻结既有顶层函数，新测试函数名必须 `r1_` 前缀；`main`/`run` 只允许追加 `r1_*()` 调用；
   - 前缀规则从「只能 `r0_`」放宽为「`r0_` 或 `r1_`」，以便三份共享测试文件追加 R1 冻结检查；不得删除或改写既有 `r0_*` 测试正文；
   - **R1 提交仍禁止新的 `v13/` 目录。** `tracked <= protected` 暂不放行 `goal_supervisor`。
2. `v13/loop_driver/driver.py`：仅在唯一哨兵块内新增 `settle_once` 及其局部帮助函数。不得改 `run_turn` / `serve` / `take_exit` / `decide` / `t0_advance_blocked` / `_settlement_advance`。`ALLOWED_CONTROL_SQL` 与 `READ_HELPERS` 元组字面保持不变（本入口不新增 SQL 动词；根锁是 `sessions` 行锁，与 claim 路径同类，静态扫描须把这一条 `FOR UPDATE` 冻结为恰好一次，且只出现在哨兵块内）。
3. `v13/loop_driver/test_loop_driver.py`：既有 55 个断言的函数正文逐字保留；只追加 `r1_*` 测试。
4. `v13/loop_driver/README.md`：说明点名入口、T0 同事务、不授权无人值守。B6 表 15 行名字不变。
5. `v13/frontier_gap/test_frontier_gap.py` 与 README：`test_stage_bytes` 可改；既有功能测试逐字保留；可追加 `r1_*` 冻结检查。不得改 Frontier SQL。
6. `v13/goal_supervise/test_goal_supervise.py` 与 README：同样只改 `test_stage_bytes`/共享冻结调用，可追加 `r1_*`；不得删减既有断言；本目录 SQL 全字节不变。
7. Phase C 覆盖矩阵与偏差台账：新增 R1 行，状态先 `not_run`，实跑后再 `exit_0`。不覆盖 M1/M2/R0 历史行。

哨兵：`# R1_SETTLE_ONCE_BEGIN` / `# R1_SETTLE_ONCE_END`，恰好一对，不嵌套，`fb295ac` 与当前 `bd72b93` 的 `driver.py` 均无此标记。去掉该对及其内部完整行后，剩余字节必须与 `git show fb295ac:v13/loop_driver/driver.py` 相等（与 R0 相同的对象读取法：`git cat-file -e` + `git show`）。`v13/loop_driver/v13_loop_driver.sql` 与 `v13/load.py` 必须与该基线全等。

正向对照：把哨兵块改成空、或把 `run_turn` 改一行、或在块外新增 `v13_advance` 调用，冻结检查必须失败。这证明扩展后的 `r0_source_scope` 放行的是哨兵内的 `settle_once`，不是整文件解冻。

其它未授权目录（workspace、real_chain、plan_arm SQL、govern、control）仍要求相对 `fb295ac` 无源码变化，R0 的 plan_arm SQL 哨兵还原继续有效。

### 6.2 M3 允许路径（后一个提交）

`v13/goal_supervisor/` 新建 `driver.py`、`test_goal_supervisor.py`、`setup_db.py`、`README.md`；矩阵/台账本行；不得改 `load.py`。不得纳入 parked 草稿、`prompt-exports/`、调查、stage 1–29、Phase A/B 已有目录。

M3 **必须再次扩展** `r0_source_scope()`：把 `v13/goal_supervisor/` 下新跟踪文件从 `tracked <= protected` 失败改为允许，并且这些新文件不得被要求等于 `fb295ac`（基线里没有它们）。不得把这个放宽写成「整个 `v13/` 都可以新增」。R1 已授权的 `loop_driver` 哨兵块在 M3 提交中保持。

M3 的 `stage_bytes`：无 `load.py` 变化；其余未授权目录相对 R1 提交为空 diff。

### 6.3 明确不改

`v13/plan_arm/**` 的 SQL、R0 哨兵块、收据谓词；`v13/goal_supervise/v13_goal_supervise.sql`；`v13/load.py`；`v13/workspace_*`；`v13/govern` 的 `v13_goal_stop`；策略 version 3；指纹函数；fanout。

## 7. 验收命令与提交

### 7.1 R1 命令

开工先确认下列十条在未改 `loop_driver` 的当前 HEAD 仍可 exit 0（R0 已证明过；R1 开工再跑一遍，失败即停）。R1 实施后同一十条必须全绿，且 `loop_driver` 的 checks ≥ 55 + 本节新增条数。结算覆盖必须打在 `settle_once` 上，不得用 `run_turn` 冒充；其中至少一条断言证明锁先于 T0/advance。

```bash
UV_FROZEN=1 uv run python v13/plan_contract/test_plan_contract.py
UV_FROZEN=1 uv run python v13/plan_read/test_plan_read.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py
UV_FROZEN=1 uv run python v13/workflow_bind/test_workflow_bind.py
UV_FROZEN=1 uv run python v13/real_chain/test_real_chain.py
UV_FROZEN=1 uv run python v13/workspace_admit/test_workspace_admit.py
UV_FROZEN=1 uv run python v13/workspace_exec/test_workspace_exec.py
UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py
UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py
```

临时库已存在即拒绝，不 DROP 原库；不使用 `agent_v13_%`；只 DROP 本次创建的库。无真实 provider。不改共享 stannum 安装。

### 7.2 M3 命令

在 R1 提交已经 push 的树上：

```bash
UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py
```

加上 §7.1 十条回归。`unattended_continuation` 的非零 `v13: supervisor: ask_user` 是该断言的接受形态，不是整门失败。其它断言必须 exit 路径上为真；进程最后按 Phase C §7.3 发出 ASK_USER。矩阵 `goal_supervisor` 行不得写成 `exit_0`。`expected_nonzero` 只描述这一项，未跑之前整门仍是 `not_run`。

### 7.3 提交顺序

1. 本计划文件单独提交（文档，不冒充运行时）。
2. R1 实现：十条全绿 → 矩阵/台账 R1 行 → 按路径 add → commit → push。
3. M3 实现：M3 gate 按 §7.2 接受 + 十条回归 → 矩阵/台账 M3 行（`unattended_continuation` 仍非 exit_0）→ 按路径 add → commit → push。

禁止 `git add -A`。禁止把未跟踪调查、Phase D 草稿、`prompt-exports/`、停放草稿、凭据卷进来。禁止 `--no-verify`、force-push、`reset --hard`。

## 8. 允许声称与停止条件

R1 通过后只能声称：在 DB owner/superuser 确定性夹具、Phase A 前缀与完整 Phase C 前缀上，`LoopDriver.settle_once` 是已点名的根结算入口；T0 与 advance 同事务同根锁；无未付则 quiet；有未付则至多一次 `v13_advance`；返回后 IDLE。不声称无人值守完成，不声称产品角色，不声称真实 provider。

M3 按 §7.2 接受后只能声称：单 goal、Fake 夹具下，监督进程可以在人不回答时保持 `waiting` 且不为解卡而 skip；结算走 `settle_once`；`unattended_continuation` 仍是 ASK_USER。不得声称人可以离开生产终端，不得声称 PC-4，不得声称 V11 auto-wake，不得声称 unknown/cancel/stale 墙已被 advance 消化。

出现下列任一情况则停并更新计划，不得标绿：需要改 R0 收据块或 `v13_advance` 其它分支；需要 `load.py` 新键；需要从 Phase A 前缀调用 stage 38 helper；需要复制 B1 出口机或包装 `run_turn`；需要恢复 parked 草稿；需要自动 skip human；测试靠 sleep 猜锁胜者；用 ASK_USER 覆盖真实失败。

## 9. 接受前须用户确认的条款 — Oracle 已裁决接受

裁决组：`9EF8F0F4-98E5-4593-B04E-A870A65C01B5`（§9.1–2）、`EE4967BA-DF71-4412-9F1E-88B38B368D26`（§9.3–4）、`D3CC6AB5-0F54-4BD2-B399-F5EAEAB04FB7`（§9.5–6）。两路均未否决任何一条默认。§9.2 作为对 Phase C §4.7「B1 出口词」的明示修正被接受。§9.3 附一条澄清（已写入 D3）：不授权结算后再 Fake serve。**§9 不再是开放选项。用户已于 2026-10-01 接受整份计划并下令实施；本节本身已闭合。**

| # | 默认 | 裁决 |
|---|---|---|
| 1 | `LoopDriver.settle_once(self, sid) -> str`。反对三参数 | **ACCEPT**。Phase C 具名入口是一个会话 id；四参数留在已有 `v13_harness_settle` |
| 2 | 返回结算/advance 词 + `skipped_failed`，不映射 B1 `wait` | **ACCEPT**（修正 Phase C §4.7）。词表保持 `waiting`/`stale`/`terminal`/`skipped_failed` 以及活体 advance 的其它实跑词；禁止把 `waiting` 改写成 `wait` |
| 3 | 监督 tick 结算后不得 Fake 伺服 | **ACCEPT**，澄清见 D3。hop=0 指零次 provider IO；不得 `v13_complete`/`serve` |
| 4 | unknown/cancel/stale 未付则失败；不改 `v13_advance` | **ACCEPT**。Phase C §1：必须替换 advance 则停 |
| 5 | `unattended_continuation` 仍 ASK_USER，矩阵不是 `exit_0` | **ACCEPT**。Phase C §7.3：父必须自己改这一项 |
| 6 | 先扩展 `r0_source_scope` 再改 `driver.py` | **ACCEPT**。该 helper 按 `fb295ac` 字节冻结 `driver.py` |

下列原文保留为已裁决条款，不再当作提问：

1. **入口名字与形状。** 默认 `LoopDriver.settle_once(self, sid) -> str`。是否改成别的名字，或改成 `(sid, effect_id, snap)` 三参数（更像 `v13_harness_settle`）？本计划反对三参数：那会把发现职责送回调用方，并诱使 Phase A 测试伪造 snap。
2. **返回词表。** 默认结算/advance 词 + `skipped_failed`，明确修正 Phase C「B1 出口词」。是否强制映射到 B1？本计划反对映射。
3. **监督 tick 是否允许结算提交后再做一次 Fake 伺服。** 默认不允许。Phase C 写明监督进程不调用 provider。若父要求「最多一次 IO hop」指一次 `serve`，那是另一份合同，会碰到 `request_stop` 不能先 hop 再停。
4. **unknown 墙。** 默认：正例用 ready/claimed；unknown/cancel/stale 若仍未付则 tick 失败，矩阵显式残留，不冒充无人值守完成。是否改为继续改 `v13_advance` 去消化 unknown？那会触发 Phase C §1 停止条件，必须另开计划。
5. **`unattended_continuation`。** 默认即使 R1+M3 其它断言全绿，这一项仍 ASK_USER、矩阵不是 `exit_0`。父若要把该项改成 `exit_0`，必须在接受函里写明，不能靠实现者推断。
6. **冻结中心是 `r0_source_scope`，不是各目录 `stage_bytes`。** 默认 R1 先扩展该函数再改 `driver.py`；M3 再放行 `v13/goal_supervisor/`。不同意这一条就无法在不红掉 R0 三条 gate 的情况下落地。

**§9 已闭合。用户已于 2026-10-01 接受整份计划并下令实施。**
