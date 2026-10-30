# v13 Stage 42：goal_workflow 开发计划

## 1. Summary

在 stage 41 生产者提交 `v13: add agentctl steer answer cancel` 已经进入 `main`，且该树上 `test_agentctl_verbs.py` 与 `test_plan_arm.py` 都退出 0 之后，追加 stage 42 `goal_workflow`。不等 D-3 正文消费闭合。生产面只新增一个 `STABLE`、`SECURITY INVOKER`、不进 `tools` 目录的函数 `public.v13_macro_suggestion(uuid, jsonb)`。测试面用**一个** `LoopDriver`、进程内 Fake 夹具、以及只活在 `v13/goal_workflow/test_goal_workflow.py` 里的常数 `GOAL_WORKFLOW_MAX_ADVANCE = 4`，把已经装载的 `workflow_template` version 1 / chain `first_real_chain` 走成：一条 `advancement_task` todo、一个子会话、一次事务外 `read_file_py`、根上 `todo_delta` 归档为 `done`。接纳位只来自同一次调用里 Postgres 重跑的 `v13_should_run(p_sid) AND v13_quota_eligible(p_sid)`；建议 JSON 里的布尔读入后丢弃。四次 `v13_advance` 分别打在现有 prefix 的 llm 臂、`v13_advance` 体内的 spawn 臂、prefix 的子会话读臂、以及 prefix 的根归档臂上，因此到不了 `v13_route`。这是第一份绿场景，不是无人值守，不调用四个 agentctl 动词，不交付 stage 43–45，不闭合 D-3。

实现是**纯尾追加，不做重构**：不改 `v13_advance`、`LoopDriver`、`v13_spawn_writer_ok`、`effects.kind` 或 stage 1–41 的 SQL。宏观门放在场景调用方。子会话上的读走 `RealChain._complete_read` 的同一事务形状，不走 `LoopDriver.serve`。

**本文是实施规格，不是执行报告。** 本规划任务不写生产代码、不跑 gate、不暂存、不提交。下文命令只给以后获准施工的实现者。开工条件是生产者提交已在 `main` 且两条 stage 41 gate 在该树上退出 0，不是 D-3 闭合。该条件在 HEAD `95af56b` 上已经满足（见 §2.1）；D-3 仍未闭合。本计划修订不授权创建 `v13/goal_workflow/`。

**2026-10-08 用户确认（本计划，不重开）：** 评估成功对象保留六键 `schema_version`、`ok`、`admitted`、`should_run`、`quota_eligible`、`gate`；形状失败与 missing 仍是父合同三键。配额合取证明保留：SAVEPOINT 里插入并激活 `quota_window` version 2（`allowed=0`），断言后必须回滚，成功剧本不得看见 `allowed=0`。这一条不单独证明 AND 的两个操作数可以分开为真；旁边再加一个同样回滚的 shadow `should_run` 夹具，期望 `should_run=true`、`quota_eligible=false`、`admitted=false`，不替换 `allowed=0` 那一条。成功剧本不构造 `RealChain`，只导入纯函数，canonical / pointer / `_complete_read` 的 SQL 由场景自己写。

权威顺序沿用父合同文首：长期循环计划 §2 > 父计划 T0–T7 > `docs/reviews/v13-agentctl-da-rulings-2026-10-03.md` > Phase A–D。父合同是 `docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md` 的 stage 42 与 PR Plan 第 3 项。2026-10-08 数据库-only 约束有效：不采用 D-A.2 file sink。`read_file_py` 是任务 subject 读取，不是控制面文件。行号以函数名为锚；漂移不换实现路径。

**声称句（README、测试模块 docstring、矩阵条文使用这一句，字符级原样，不准加宽）：**

> 单 goal、测试超级用户、Fake 夹具、场景自有 advance 上界 4（常数只活在 `v13/goal_workflow/test_goal_workflow.py`）、无真实 provider、唯一推进者是一个 `LoopDriver`：宏观门放行后，`workflow_template` version 1 / `first_real_chain` 展开成一条 advancement todo、一个子会话、一次 `read_file_py`、根上归档为 done，根与子都没有 human effect。已有 human pending 时场景停在非终态、不 skip、不 complete、不 cancel。这不是人可以离开生产终端。

### 范围边界

- 新目录只有四个文件：`v13/goal_workflow/v13_goal_workflow.sql`、`setup_db.py`、`test_goal_workflow.py`、`README.md`。
- `v13/load.py` 只在两个容器尾部追加 `goal_workflow` / 42。目录名、stage 键、编号一致。不能跳过 40 或 41。
- `v13/plan_arm/test_plan_arm.py` 只改 `r1_load_append_ok` 与 `r1_phase_d_prefix_allowance` 两个函数体。`r0_source_scope`、`r1_driver_restore`、模块级 AST 不动。
- 新 SQL 里只有 `v13_macro_suggestion` 及其 `REVOKE` / `GRANT` / `COMMENT`。不 `INSERT` tools，不插入 route policy，不 `CREATE OR REPLACE` 任何既有函数。
- 从 41 只消费已经冻结的 route policy `controller` version 1。开会话 spec 只能是 `{"route_policy_name":"controller","version":1}`。不调用 `v13_agentctl_observe` / `steer` / `answer` / `cancel`，不实现 D-3，不回填 stage 41 的矩阵行或台账行。
- 不调用 `RealChain.run` / `_run`、`plan_prelude`、`plan_admit`、`decide`、`decide_exit`、`GoalSupervisor.tick`、`run_turn`、`v13_parse`、`v13_wake_is_satisfied_v1`、`v13_claim(`、`v13_claim_fair`。不取 `13002` / `13003`。
- 不把 `v13_workflow_resolve` 或 `v13_child_pointer` 写进 `LoopDriver.ALLOWED_CONTROL_SQL`。场景用自己的游标调用它们，与 `RealChain` 相同，不改 `driver.py`。
- 不新增表、列、索引、触发器、事件 type、route action、`effects.kind`。活体 kind 是七值；不断言「仍是五值」，也不新增第八值。
- `spawn_subsession.enabled` 保持 true。不把「保持 true」写成新能力。
- `actl_driver_demoted` 继续延期。替代是 `actl_driver_untouched` 与 `actl_scene_no_decide_exit`。
- I1–I4、E2 worktree 握手、D-9、stage 43–45、LoopX quota / outcome_floor / spend / settlement / writeback、wake：本文件不给新答案、不给实现。父计划 Open Questions 保持开放。
- 外部 IO 只在事务外的 FakeLLM / FakeTool 里发生。测试进程不打开网络套接字，不调用 `poison()`，不设置 `typesafe.endpoint`。

---

## 2. Current-state analysis

### 2.1 施工前置与 HEAD `95af56b` 的工作区

开工门在本修订写入时已经满足：HEAD 是 `95af56b`，提交信息 `v13: add agentctl steer answer cancel`，在 `main` 上且与 `origin/main` 同步。已在 `main` 上的生产 stage 停在 41（`agentctl_verbs`）。两条 stage 41 gate 在该树上退出 0，记在矩阵第 87 行（`test_agentctl_verbs.py` 1017 checks，`test_plan_arm.py` 104 checks）。D-3 正文消费仍未闭合，不是开工前置。本段只更正快照。本计划修订不授权创建 `v13/goal_workflow/`，也不授权把 42 的路径放进放行闭集。放行闭集今天仍把 42 当非法（见 §2.3）。

- HEAD 是 `95af56b`，提交信息 `v13: add agentctl steer answer cancel`。已在 `main` 上的生产 stage 停在 41。前一个 HEAD 是 `a19aefc`（`v13: add agentctl observe tool`，生产 stage 停在 40）。
- 生产者提交 `95af56b` 已在 `main`。该提交是 9 个文件：`v13/agentctl_verbs/v13_agentctl_verbs.sql`、`v13/agentctl_verbs/test_agentctl_verbs.py`、`v13/agentctl_verbs/setup_db.py`、`v13/agentctl_verbs/README.md`、`v13/load.py`、`v13/plan_arm/test_plan_arm.py`，以及矩阵、台账、parity 三份 review。这些路径不得与 42 打进同一次提交，也不许为了 42 回改它们。正文消费未闭合不要求 `test_agentctl_verbs.py` 退出非 0，也不禁止已经落地的该生产者提交。不发明消费者。不写「D-3 已闭合」或「已取代 R11」。
- `v13/goal_workflow/` 不存在。`v13_macro_suggestion` 全库零定义，只出现在父计划与本脚手架。本文件修订不创建该目录。
- 本文件可以先成文。实现者开工前必须看到的状态是：HEAD 的历史含提交 `v13: add agentctl steer answer cancel`，`UV_FROZEN=1 uv run python v13/agentctl_verbs/test_agentctl_verbs.py` 与 `test_plan_arm.py` 都已在该提交的树上退出 0。不等 D-3 正文消费闭合，不要求名为消费已发生的断言通过。本修订写入时 HEAD 就是 `95af56b`，该状态已经成立。复验时 HEAD 仍是 `a19aefc`、或 41 只在 index 里、或该生产者提交不在 HEAD 的历史上，就停止。禁止把 41 的未提交内容和 42 打进同一次提交。看到该状态也不授权创建 `v13/goal_workflow/`。

若该生产者提交改动了 `controller` version 1 的插入位置或 `load.py` 的尾部，实现者重读那些行再写 spec 常量。消费合同不变：只消费冻结的 `controller` / 1，不调用四个动词，不实现 D-3。

### 2.2 装载尾

`v13/load.py` 的 `SQL_LOAD_ORDER` 最后两项是 `agentctl/v13_agentctl.sql` 然后 `agentctl_verbs/v13_agentctl_verbs.sql`（`:57-58`）。`STAGE_THROUGH` 尾是 `"agentctl": 40`、`"agentctl_verbs": 41`（`:100-102`）。`files_through` 用 `STAGE_THROUGH[stage]` 截 `SQL_LOAD_ORDER[:n]`（`:106-108`）。新 stage 必须同时追加到两个容器的尾部，键与目录名相同，编号是 42。`files_through`、`run_psql`、`load_stage`、文件头注释都不改。

42 的 setup 调用 `load_stage(..., "agentctl_verbs")`，装到 41 为止。本 stage SQL 由测试在安装快照之后单独 `run_psql`，与 `v13/agentctl_verbs/setup_db.py` 把 SQL 留在 gate 里的做法相同。

### 2.3 放行闭集今天把 42 当非法

`r1_load_append_ok`（`v13/plan_arm/test_plan_arm.py`，定义自 `:327`）的 `approved` 恰为三项：`fair_claim/39`、`agentctl/40`、`agentctl_verbs/41`（`:407-416`）。失败文案是 `append is not fair_claim/39 then agentctl/40 then agentctl_verbs/41`。检查顺序保持：纯尾、路径唯一、键唯一、编号唯一、连续编号、目录键对齐、plus 行对应、最后才是 approved 元组。`order_names` 仍是 `workspace_admit`、`frontier_gap`、`goal_supervise`、`fair_claim`。36–38 在 `fb295ac` 前缀内，不重算成追加。

`r1_phase_d_prefix_allowance`（定义自 `:425`）的精确闭集只有 stage 40 四路径与 stage 41 四路径。没有目录前缀放行。`allow()` 的路径条件是三个前缀，或 `stage40`，或 `stage41`。合成负例已经把下面两件事当非法，42 必须把它们**前移**到尚未批准的 `external_exec` / 43，不能删掉负例：

- `extra | {"v13/goal_workflow/test_goal_workflow.py"}` 的 needle 是 `outside the three prefixes`（`:718-720` 一带）。
- 在合法 41 尾后再追加 `goal_workflow` / `v13_goal_workflow.sql` / 42，tracked 含该 SQL，needle 是三项 approved 文案（`:734-745` 一带）。

`r0_source_scope`（`:746` 起）一字不改。`r1_load_append_ok` 与 `r1_phase_d_prefix_allowance` 在 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 里不存在，所以改这两个函数体不会触发 `changed existing test`。模块级语句、import、常量一旦变化，会触发 `changed module setup`。出现这两种文案就撤回越界编辑，不准放宽 `r0_source_scope` 的 AST 例外。

`r1_driver_restore`（`:275-298`）把 `v13/loop_driver/driver.py` 去掉唯一的 `R1_SETTLE_ONCE_BEGIN` / `END` 哨兵块之后，与 `fb295ac` 的 `driver.py` 字节相等。42 的 `actl_driver_untouched` **调用这个函数**，不重写一份比较。`actl_driver_demoted` 不实现：它要求 `driver.py` 不再走 `decide_exit`，而哨兵外字节不能改。

### 2.4 从 41 消费的政策，以及 42 不走的 sql 臂

`controller` version 1 的插入在 `v13/agentctl_verbs/v13_agentctl_verbs.sql` 的 `$policy$` 块：先确认 `default` / 2 已 frozen，再 `INSERT` policy 行，从 `default` / 2 **按列**复制 thresholds，再追加 16 条 pass 带 `[0.60, Infinity)`，核对带集后 `state = frozen`（插入点约 `:399-421`，复制与 16 行在同一 DO 块内）。随后才插入 `controller_surface` version 1。42 的 SQL **不再插入**这份政策，也不读 `controller_surface` 来授权。

`v13_plan_commit_entry`（`v13/plan_contract/v13_plan_contract.sql:155-177`）只检查 `version` 再调用 `v13_open_session`。`v13_open_session`（`v13/spawn/v13_spawn.sql:285-315`）接受的键只有 `route_policy_name` 与 `version`，不写 `parent_session_id`，不写事件。sessions 的 `trg_sessions_policy_guard` 要求被引用的 route policy 已经 frozen（`v13/schema/v13_core.sql:552-558`）。所以 spec 必须指向已冻结的 `controller` / 1。

`RealChain.SPEC` 是 `{"route_policy_name": "default", "version": 2}`（`v13/real_chain/chain.py:22`）。照抄它会开会话开到错误政策上。42 禁止使用 `RealChain.SPEC`。

S1/S2 那种 `mock_from_needed` → `v13_parse` → `v13_advance` 的 sql 臂夹具**不是**本场景。`v13_resolve_tool_params` 只在 stated 命中 pass 时抄 choice（`v13/loop/advance.sql:169-182`），`mock_from_needed` 对未指定 noul 填 `0.1`（`v13/loop/test_loop.py:126`）。场景不调用 `v13_parse`，因此也不准备 stated noul，不加 triage 带，不提交第二份 override 来「打到 sql 臂」。`typesafe.endpoint` 毒化（`test_loop.py:71-75` 的 `poison()`）不调用。

### 2.5 四次 advance 实际打到的臂

活体 `v13_advance` 在 `v13/plan_arm/v13_plan_arm.sql` 的替换体里。与父计划旧表述不同、必须按活体写进测试的两点：

1. **spawn 臂不在 prefix 里。** 它在 `v13_advance` 自身、prefix 调用之前。有未配对 `tool/call` 时，`v13_should_run` 为 false 就 `RETURN 'waiting'`（`:486`），`v13_spawn_batch_allowed` 为 false 也 `RETURN 'waiting'`（`:489`），两者都不 spawn。只有这两关都过才调用 `v13_spawn_subsession` 并 `RETURN 'progressed'`（`:508`）。prefix 调用在 `:510`，只有返回词 `IS NOT NULL` 才把该词交回去。成功剧本的第 2 个词必须是 `progressed`。若包装器记下 `waiting`，停止并报告是 `:486` 还是 `:489`，不准改 FakeLLM、`spawn_budget`、`v13_spawn_batch_allowed` 或 spawn 臂，也不要把这次 `waiting` 当成 prefix 的 llm 臂。
2. **prefix 返回 NULL 不会停住同一次 advance。** NULL 之后先调用 `v13_triage_steer`（`v13_plan_arm.sql:737-740`），返回非 NULL 就结束，到不了 `v13_route`（`:741`）。本场景的根没有非空 `user/message`，`v13_triage_decide` 在看 override 之前就因 `fold_empty` 返回 `reject`（`v13/triage/v13_triage.sql:93-95`），steer 随后 closeout 成 `terminal`（`v13/triage/v13_triage.sql:433-437`）。有 `user/message` 但没有 `direct` 时，根上才是 `triage_fail_closed` 的 human（`:454-455`）。子会话在 `:446-447` 直接 `RETURN NULL`，然后才是 `v13_route`；intent 缺失时 reason 是 `low_intent_confidence`（`v13/loop/advance.sql:134-135`）。成功剧本的四次返回都在 triage 之前，不靠这些回落。失败条件是任何 `kind=human`、会话变成 `completed|failed|cancelled`、或出现 `low_intent_confidence`。不准改 triage、route 或 `_snap_with` 去换一种回落。

prefix（`v13_plan_advance_prefix`，`:120` 起）与本场景有关的返回点：

| 位置 | 条件 | 返回 |
|---|---|---|
| 子臂约 `:144-158` | `p_sid` 不是 root，`v13_should_run(p_sid)` 为真，`workflow/pointer` 计数 = 1 且 `read_file_py` 计数 = 0 | 入队 `read_file_py`，`RETURN 'waiting'` |
| 紧随其后约 `:161` | 子臂条件不成立 | `RETURN NULL` |
| 根归档约 `:183-205` | 子会话上已成功的 `read_file_py`（`result` 非空）且折叠仍是 `runnable` 的 `advancement_task` | 写 `todo_delta` `runnable→done`，`RETURN 'waiting'` |
| 约 `:289-290` | `NOT v13_plan_gate(root) OR NOT v13_should_run(p_sid)` | `RETURN NULL` |
| 约 `:292-294` | 没有选中 todo，或 `dispatch = 'none'` | `RETURN NULL` |
| provider 臂（`:292` 之后的 `dispatch = 'provider'` 分支） | `v13_selected_todo` 对 `advancement_task` 或 `continuous_monitor` 且 `status=runnable`、无排除绑定给出 `dispatch=provider`（`:86-94`） | 入队 `llm`，`request.route.reason = selected_todo`，最终 `RETURN 'waiting'` |

调用者上已有 `status IN ('ready','claimed')` 的 effect 时，`v13_advance` 在 spawn 臂和 prefix **之前**就 `RETURN 'waiting'`（`:404-466`）。那次 waiting 没有 llm 行。成功剧本第 1 次 advance 之前，调用者上这种 effect 必须是 0。

`v13_selected_todo` 给不出 `provider` 时，prefix 在 `:292-294` 返回 NULL，**同一次** advance 继续往路由走。所以第 1 步之前折叠 `status` 必须已经是 `runnable`，不能只写「有一条 advancement_task」。

### 2.6 驱动器、RealChain 助手、以及不能照搬的入口

`LoopDriver`（`v13/loop_driver/driver.py`）一个实例拥有一条连接，`autocommit = False`。`_sql` 执行一条语句然后 `commit`，并把 `(name, sid)` 记入 `calls`。

| 方法 | 场景用它的方式 | 不用它的原因 |
|---|---|---|
| `plan_commit_entry`（约 `:208-212`） | 传入 controller/1 spec，返回的 uuid 文本就是 root，也是 goal_id | 不改 |
| `plan_writer`（约 `:214-218`） | 第一实参固定是 Python `None`，SQL 侧 actor 为 NULL | 测试超级用户下 `v13_plan_writer` 对 NULL actor 走 `v13_control_operator()`（`v13_plan_contract.sql:811-814`） |
| `submit_override`（`:166-171` 载荷） | 只为了让根上 `max(seq)` 非空 | 不是四次 advance 的条件。载荷键是 `schema_version` 数字 1、`intent=direct`、`reason=""`、`source_principal=operator`。不是 `controller` |
| `advance` | 第 1 次根、第 3 次子 | 每次 `snap_of` 自己会 commit，再单独 commit 一次 advance |
| `serve`（llm 分支调用 `four_layers()`，五参 `v13_complete` 之后无条件 `_settlement_advance`，约 `:372-376`） | **只**服务根上那一个 llm effect。内部那次 advance 是上界 4 里的第 2 次 | 子会话的 `read_file_py` 禁止走 `serve`。`serve` 的返回值是 `('served'\|'blocked'\|'none', outcome)`，**不**把 advance 的词交出来 |
| `complete`（约 `:180-185`，经 `_sql` 约 `:149-157`） | 不调用 | 它只执行五参 `v13_complete` 然后单独 commit，函数体内没有领用 `UPDATE` |
| `_settlement_advance` | 第 4 次：场景打开游标，调用它，再 commit。形状同 `RealChain._settle_root`（`chain.py:312-321`） | 不是再 `serve` |
| `_snap_with` | 只被冻结的 `advance` / `_settlement_advance` 调用 | 信封保持 `{"sid": sid}` |
| `four_layers`（`:402-405`） | 读 `self.layers` 的四段，不拼接、不回写 | `layers` 缺键时在 SQL 之前 `KeyError` |
| `decide` / `take_exit` / `run_turn` / `wake_satisfied` | 不调用 | `ALLOWED_CONTROL_SQL` 里虽有 `v13_wake_is_satisfied_v1`（`driver.py:31-49`），场景与新 SQL 都不调用它 |

`LAYER_ORDER = ("assertion", "assembly", "judgment", "workflow")`（`driver.py:63`）。`layers` 在 `__init__` 里复制；场景在第一次 `four_layers()` 之前整体替换 `driver.layers`。

`RealChain._run`（`chain.py:110-152`）会调用 `plan_prelude`、`plan_admit`，并用 `SPEC`（default/2）。父计划写明 prelude 与 admit 不是四次 advance 的条件。场景**不得**调用 `RealChain.run` / `_run`，也不得构造 `RealChain`。可以导入的只有纯函数与常数：`_plan_answer_ok`（`:32`）、`_spawn_answer_ok`（`:53`）、`text_hash`、`EXCERPT_CAP = 1024`（`:21`）、`LAYER_ORDER` 已从 driver 再导出。`_canonical`（`:182-207`）、`_pointer`（`:242-257`）、`_read_once`（`:259-283`）、`_complete_read`（`:285-310`）的**合同**由场景用自己的 SQL 照抄，不通过 `RealChain` 实例调用，避免顺手走到 `_run`。

`_complete_read` 的合同是同一条事务：`UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, lease_owner=<driver.worker>, lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s AND status='ready' RETURNING attempt_no, fence`，零行则回滚并失败；然后五参 `v13_complete(effect, attempt, fence, 'succeeded', result)`；然后 `commit`；**不再** advance。`driver.worker` 默认 `"loop_driver"`。五参 `v13_complete` 把 actor 填 NULL（`v13/acl/v13_acl.sql:459-470`），对非 human 的 tool 行这是既有通道。不要改走六参，也不要改走 `agentctl_answer`（它只接受 `kind=human`）。

水位：`v13_plan_writer` 的 `plan_commit` 读根上 `max(seq)`，空或不等于 `based_on_seq` 就 `RAISE 'v13: plan writer: waterline'`（`v13_plan_contract.sql:422-424` 与 `:866` 一带的 `v_max` 读取）。`v13_plan_prelude` 是 `STABLE`，只回 `{version}`，不写事件（`:102-121`）。`v13_open_session` 不写事件。所以场景照抄**一次** `submit_override`，只为了 `_canonical` 看得到 seq。这次调用不决定四次 advance 在 `v13_route` 之前返回。省掉水位就停，不准改 `v13_plan_writer`。测试超级用户不调用 `plan_admit`。

`v13_llm_tool_calls`（`v13/spawn/v13_spawn.sql:94-133`）对 `name <> spawn_subsession` 或 `args` 键集不是 `{task}` 的元素 `RAISE 'v13: tool_calls shape'`。id 须匹配 `^[A-Za-z0-9_./:-]+$`，长度 1..128；task 长度 1..1024。场景的 FakeLLM 只发这一种 tool_call。`serve` 在 `text` 空白时返回 `blocked`，不调用 complete（`driver.py` llm 循环）。五参 complete 在 llm 的 `text` 缺失或空白时把结果改成 `failed`，不写 `tool/call`（`v13_acl.sql:401-407`）；`tool/call` 只在结果仍为 `succeeded` 时写入（`:423-427`）。没有 `tool/call` 时 spawn 臂不进入，同一次 advance 会继续往 prefix / 路由走。

`v13_spawn_subsession` 要求父会话 `next_seq >= 1`，否则 `RAISE 'v13: spawn requires prefix'`（`v13_spawn.sql` 约 `:348-349`）。`submit_override` 写下的 `goal/override` 已经满足这个前缀；`plan/committed` 会再拨一次 `next_seq`。spawn 发生在第 2 次 advance，那时前缀已经在。

### 2.7 宏观谓词、停目标、human、配额

活体 `v13_should_run_gate` 是 `v13/govern/v13_govern.sql` 里的 `CREATE OR REPLACE`，不是 `v13/should_run/v13_should_run.sql` 的初稿。初稿只认识四扇门，不能拿来写断言。

- 缺会话：`RAISE EXCEPTION 'v13: unknown session %'`（govern `:373-376`）。
- 活动政策是 `should_run` version 3，JSON 含 `human_pending` / `unknown_wall` / `unconsumed_cancel` / `duty_cycle`（shadow）/ `quota_window` / `capabilities` / `goal_stopped`，后两者以及 `human_pending` 的 effect 都是 `block`（`:348-359`）。version 3 `active=true`，version 2 被关掉。
- `human_pending` 解释臂：该 effect 已经是 `block` 且 `v13_pending_human` 为真时返回这个 id（`:407-411`）。
- `v13_should_run`（`v13/should_run/v13_should_run.sql:195-203`）返回 `v13_should_run_gate(p_sid) IS NULL`。gate 文本 NULL 才是 true。
- `v13_pending_human`（`v13/control/v13_control.sql:121-128`）为真当且仅当本会话存在 `kind=human` 且 `status IN ('ready','claimed')`。
- `v13_quota_eligible`（`v13/quota_window/v13_quota_window.sql`，函数自 `:53`）缺会话 `RAISE 'v13: unknown session %'`（约 `:66-68`）。只数**本会话** `type=turn/material_spent`。活动种子 `window_hours=8760`、`slot_minutes=0`、`allowed=1000000`。`slot_minutes=0` 不做间隔拒绝。本场景的成功条件不靠这种事件消耗配额。
- `v13_goal_stop`（govern `:237-286`）要求 `v13_control_operator()`。测试超级用户为真（`rolsuper`，`v13_acl.sql:74-87`）。存在 `ready|claimed|unknown` effect 时 `RAISE 'v13: goal busy'`（`:271-276`），发生在写 `goal/stopped` 之前。否则追加一条 `goal/stopped`（`:280-286`），不改 `sessions.status`。
- `v13_enqueue_effect(uuid, text, jsonb, text)` 活体在 `v13/control/v13_control.sql:902`，默认 `status=ready`。未消费 cancel 时 RAISE。human 已在 `effect_attempt_cap` 的键里。

`goal_stopped` 解释臂已核对，不是待确认项：`v13/govern/v13_govern.sql:438-446` 在会话非终态、`v13_goal_lifecycle(p_sid) = 'stopped'` 且该门 effect 为 `block` 时 `RETURN v_id`，即文本 `goal_stopped`。不准改 `v13_govern.sql`。若以后这段被替换成别的 id，停止并报告，不要改断言去追新字符串。

`duty_cycle` 在 version 3 里是 `shadow`。duty=0 不会让 `v13_should_run` 变 false。`capabilities` version 1 的 `required` 是空数组，安静会话不会因能力门被挡。成功剧本不要改这两份政策。

### 2.8 模板、指针、折叠、kind 闭集

`workflow_template` version 1 已在 `v13/workflow_bind/v13_workflow_bind.sql:10-27` 插入，`chain` 为 `first_real_chain`，四段 layer 都是非空文本。`v13_workflow_resolve(text, int)`（`:29` 起）在名字缺失、未 active、或形状不规范时 RAISE；成功时只返回四键 `assertion` / `assembly` / `judgment` / `workflow` 的文本，不执行正文。`v13_child_pointer(uuid, uuid, uuid, uuid, bigint)`（同文件后部）是 `workflow/pointer` 的唯一写者。同会话部分唯一索引 `ux_events_workflow_pointer`。载荷键恰为 `schema_version`、`parent_session_id`、`root_session_id`、`todo_id`、`up_to_seq`。42 不替换这个函数。

折叠用一参 `v13_plan_todo_fold(uuid)`（`v13/plan_contract/v13_plan_contract.sql:180-191`）。归档先例是 `v13/real_chain/test_real_chain.py:392-399`：一条 `todo/delta` 且 `payload.canonical.status_to = done`，折叠 `status = done`，archive 词是 `waiting`。

`effects.kind` 的活体 CHECK 是七值：`judge|tool|llm|context_refresh|human|context_summary|mgraph_consolidate`（`v13/mgraph/v13_mgraph.sql:2688-2692`）。父计划里的五值闭集已过时。42 不新增第八值，测试不断言「CHECK 仍是五值」。成功剧本用到的是其中的 `llm` 与 `tool`。

### 2.9 ACL 先例与反例

照抄 `v13_agentctl_observe` 的授权两句（`v13/agentctl/v13_agentctl.sql` 函数体之后，约 `:134-135`）：

- `REVOKE EXECUTE ON FUNCTION ... FROM PUBLIC`
- `GRANT EXECUTE ON FUNCTION ... TO v13_route`

函数属性照观察函数，不照三个写动词：`LANGUAGE plpgsql`、`STABLE`、不写 `SECURITY DEFINER`、`SET search_path = pg_catalog, public`、不 `ALTER OWNER` 到 `v13_spawn_owner`、不声明 `STRICT`。

禁止照 `v13_tool_session_stats` 保留 PUBLIC EXECUTE（`v13/schema/v13_core.sql:911-935`，该函数的注释写明 PUBLIC 是演示只读 handler 的有意例外）。宏观函数不是 `tools` 行，目录守卫（`v13/catalog/v13_catalog.sql:36-64`）不会检查它。不要为了「看起来像工具」插一行 tools：那会拨 `tools_revision`，并让非本场景的会话在目录里看见它。

`v13_policies.value` 不可 UPDATE（`v13_core.sql:711-725`）。42 不插入、不翻转任何 `v13_policies` 行。配额反例若要在测试里临时把 `allowed` 做成 0，只能在 **SAVEPOINT** 里追加 `quota_window` version 2 再翻 active，然后必须回滚（见 §3.6）。产品 SQL 里不做这件事。

### 2.10 测试形态、零写窗口、文档现状

stage 测试是脚本，不是 pytest：`check()` 失败即 `AssertionError`，进程以非 0 结束。库名形如 `ll_<stage>_<pid>_<hex6>`。`setup_db.py` 只 `load_stage` 到**前一** stage：`v13/agentctl/setup_db.py` 装到 `fair_claim`，`v13/agentctl_verbs/setup_db.py` 装到 `agentctl`。42 装到 `agentctl_verbs`。同名库已存在则退出，不 DROP、不接管。`CREATED` 仅在 `CREATE DATABASE` 成功之后为真。

零写窗口先例是 `v13/agentctl/test_agentctl.py` 的 `snapshot_read_window`（`:183-207`）与 `actl_read_zero_write`（`:631-641`）。源码扫描先例是同文件 `BANNED`（`:53-56`）与 `actl_no_io`（`:645-655`）：扫 `pg_get_functiondef`，`v13_claim` 按 `v13_claim(` 认，避免误伤别的标识符；`pg_stat` 数不到就报告环境阻塞，不降级。AST 调用扫描先例是 `v13/goal_supervisor/test_goal_supervisor.py:1060-1145`：`ast.walk` 认 `Call` 的 `Name.id` 或 `Attribute.attr`。FakeLLM 先例是 `v13/loop_driver/test_loop_driver.py:220-238` 与 `v13/real_chain/test_real_chain.py:75-115` 的 `Probe`。

矩阵 `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` 列是 `| # | 条文 | 状态 | 测试落点 | 缺口 |`。Stage 40 的 **86** 仍在 `:108-112`。当前最后一行是 Stage 41 的 **87**（`## Stage 41` 在 `:114`，行在 `:118`）：状态 ✅，记录 `test_agentctl_verbs.py` 1017 checks 与 `test_plan_arm.py` 104 checks，退出码都是 0；缺口写明正文消费未闭合。台账 `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` 列是 `| # | 事实 | 处置 |`，Stage 40 节仍是 S40-1 与 S40-D2（`:155-162`）。`## Stage 41` 在 `:164`，S41-1 / S41-2 / S41-D3 在 `:168-170`；S41-D3 保持未关闭。stage 42 的行还没有。42 **不回填** 41，也不改第 86 行、第 87 行、S40-1 / S40-D2、S41-1 / S41-2 / S41-D3、F22，也不写「已取代 R11」。不在本计划里预写 42 的行号。实现时用当时文件里的最大号 + 1；本快照最大号是 87，所以下一次追加是 88，除非 W5 之前矩阵又长了新行。

### 2.11 复用与阻断

| 已有物件 | 42 的用法 |
|---|---|
| `v13_workflow_resolve`、`LAYER_ORDER`、`four_layers` | 原样读四段文本放进 `driver.layers` |
| `_plan_answer_ok`、`_spawn_answer_ok`、`text_hash`、`EXCERPT_CAP` | 导入后做判定，不复制第二份规则 |
| `LoopDriver.plan_commit_entry` / `submit_override` / `plan_writer` / `advance` / `serve` / `_settlement_advance` | 唯一推进者的全部推进入口 |
| `v13_child_pointer`、`v13_plan_map_root`、`v13_plan_todo_fold` | 场景游标直接调用；不加入 `ALLOWED_CONTROL_SQL` |
| `v13_should_run`、`v13_should_run_gate`、`v13_quota_eligible` | 只由 `v13_macro_suggestion` 在会话存在之后调用 |
| `v13_goal_stop`、`v13_enqueue_effect` | 只出现在两条独立负夹具里 |
| `r1_driver_restore` | `actl_driver_untouched` 直接调用 |
| `controller` / 1 | 只当作已经 frozen 的开会话目标 |

阻断（不准改这些来修绿）：`v13/loop/advance.sql`、`v13/plan_arm/v13_plan_arm.sql`、`v13/loop_driver/driver.py`、`v13/goal_supervisor/driver.py`、`v13/goal_supervisor/accept_unattended.py`、`v13/fair_claim/v13_fair_claim.sql`、`v13/fair_driver/driver.py`、`v13/spawn/v13_spawn.sql`、`v13/envelope/v13_envelope.sql`、`v13/acl/v13_acl.sql`、`v13/real_chain/v13_real_chain.sql`、`v13/real_chain/chain.py`、`v13/govern/v13_govern.sql`、`v13/quota_window/v13_quota_window.sql`、stage 1–16、`v13/agentctl/**`、`v13/agentctl_verbs/**`。

---

## 3. Design

### 3.1 执行索引

Size 是相对工作量，不是工期。W1–W6 是同一次里程碑提交，但提交发生在两条 gate 都绿、文档收尾之后。不能先提交放行规则。W0 未满足时 W1 不准开始。

| 项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W0 | 确认 41 生产者提交已在 `main` | HEAD 是 `v13: add agentctl steer answer cancel`（本快照为 `95af56b`）；41 的两条 gate 在该树上曾经退出 0（矩阵第 87 行）；工作区没有混入的 41 未提交差。不等 D-3 正文消费闭合。本快照这些条件已满足；复验失败则 W1 仍不准开始。满足 W0 不授权创建 `v13/goal_workflow/` | 只读 git 与 `v13/load.py` 尾 | §2.1 | S |
| W1 | 追加装载与精确放行 | 尾项恰为 39、40、41、42；十二个 stage 40/41/42 路径保留；`external_exec`/43 仍被拒绝 | `v13/load.py`；`test_plan_arm.py` 两个函数体 | W0 | M |
| W2 | 安装只读宏观函数 | 签名、三类返回、ACL、丢弃布尔、缺会话不调用两谓词、零写，全部符合；无 tools 行、无政策行 | `v13/goal_workflow/v13_goal_workflow.sql` | 累计装到 41；`controller`/1 已 frozen | M |
| W3 | 一次性库与安装差 | 唯一库装到 `agentctl_verbs`；除新函数外定义哈希不变；失败也只删本进程的库 | `setup_db.py`；测试的安装段 | W1、W2 | M |
| W4 | 十条断言与一条成功剧本 | 成功剧本 advance 词序列恰为四次；三条独立夹具分开；两条 gate 都退出 0 | `test_goal_workflow.py`；README 合同段 | W3；四个新路径已跟踪 | L |
| W5 | 绿后文档 | README 有实跑记录；矩阵与台账只追加 42；不回填 41 | README；矩阵；台账 | W4 两条 gate 退出 0 | S |
| W6 | 同笔提交 | 最终树重跑两 gate 退出 0；闭集一次提交 | §4 的文件 | W5 | S |

### 3.2 `v13_macro_suggestion`

一个 PostgreSQL 函数，不新增类型、表、辅助函数或服务。文件 `v13/goal_workflow/v13_goal_workflow.sql`，由安装者属主创建。调用方是测试里的直接 `SELECT`，以及成功剧本在五个检查点上的直接 `SELECT`。不修改任何既有调用方。不进入 `ALLOWED_CONTROL_SQL`。

```text
public.v13_macro_suggestion(p_sid uuid, p_suggestion jsonb) → jsonb
```

| 属性 | 固定设计 |
|---|---|
| 语言 | `plpgsql`。用独立 `IF` 把「形状 → 会话存在 → 谓词」分成三段，不靠 SQL 布尔短路 |
| 易变性 | `STABLE` |
| 安全 | 默认 `SECURITY INVOKER`。源文件不得出现 `SECURITY DEFINER` |
| NULL | 不声明 `STRICT`。SQL NULL 的 `p_suggestion` 走形状失败，返回 jsonb，不返回 SQL NULL |
| `search_path` | 恰为 `pg_catalog, public`，写在函数的 `SET` 上 |
| 属主 | 安装者。不 `ALTER OWNER`，不建角色 |
| EXECUTE | `REVOKE` FROM `PUBLIC`；只 `GRANT` TO `v13_route`。不授 `v13_recall`、`v13_worker`、`v13_resolve`、`v13_spawn_owner` |
| 执行 | 同步，当前语句内只读。无后台、无 `COMMIT`、无动态 `EXECUTE`、无 `EXCEPTION WHEN` 捕获块 |
| 写入 | 零。不调用 `v13_append_event`、`v13_enqueue_effect`、`v13_plan_writer`、`v13_child_pointer`、`v13_goal_stop` |
| tools | 不是 `tools` 行，不进信封目录 |

选择 plpgsql 而不是一条 SQL 表达式：缺会话时两个谓词都会 RAISE，必须在调用它们之前返回。SQL `AND` 不保证调用顺序。

函数不读 `route_policy_name`。政策不是宏观门的输入。成功剧本使用 `controller` / 1，是因为 `plan_commit_entry` 必须引用一份已经冻结的产品政策，不是因为这个函数要 fail-close 到 controller。

**建议闭集。** 对象键只允许下面这一组，外加可选 `note`。`v13_json_keys`（`v13/control/v13_control.sql:102-106`）按键排序。合法排序结果只有两种：

- `kind`, `schema_version`, `subject_session_id`, `suggested_should_run`
- `kind`, `note`, `schema_version`, `subject_session_id`, `suggested_should_run`

| 键 | 类型与取值 | 用完之后 |
|---|---|---|
| `schema_version` | jsonb number，`v13_json_int_ok(..., 1)` 为真，且文本恰为 `1` | 不回显到失败对象 |
| `kind` | jsonb string，恰为 `macro_suggestion`。不 `btrim` | 不匹配即形状失败 |
| `subject_session_id` | jsonb string，`v13_canonical_uuid` 为真，且文本与 `p_sid::text` 相同 | 不是规范小写 8-4-4-4-12，或与 `p_sid` 不同：形状失败。确认之前不 `::uuid` |
| `suggested_should_run` | jsonb boolean。`true` 与 `false` 都过形状 | **丢弃**。不参与 `admitted`，不出现在返回值里 |
| `note` | 仅当键存在：jsonb string，`char_length(btrim(text)) <= 256`。0 与纯空白合法。按字符，不按字节。不截断 | 不存储、不返回 |

未知键（包括 `source_principal`、`admitted`、`ok`、`should_run`、`skip`、`gate`）在谓词之前失败。`note` 的 256 是本函数自己的上限，不要抄 steer 的 1024。

**检查顺序，每一步失败都立刻返回，不落下一步：**

1. `p_suggestion` 是 SQL NULL，或 `jsonb_typeof` 不是 `object` → 形状对象。
2. 键集不是上面两种排序结果之一 → 形状对象。
3. `schema_version` 不是数字 1 → 形状对象。字符串 `"1"`、`0`、`2`、`1.5` 都失败。
4. `kind` 不是恰好 `macro_suggestion` → 形状对象。
5. `subject_session_id` 不是规范 uuid 文本，或与 `p_sid::text` `IS DISTINCT FROM` → 形状对象。比较必须用 `IS DISTINCT FROM`，不准用 `<>`。`p_sid` 为 SQL NULL 时，`<>` 的结果是 NULL，`IF` 不进入，函数会掉进步骤 8 返回 missing。`IS DISTINCT FROM` 才把这次调用留在形状对象，并且不调用两个谓词。不声明 `STRICT`。
6. `suggested_should_run` 的 `jsonb_typeof` 不是 `boolean` → 形状对象。字符串 `"true"` **不**接受。这个函数不经过 `v13_resolve_tool_params`，没有观察函数那种 `"true"` / `"false"` 字符串通道。
7. 有 `note` 时不满足第 7 键的字符约束 → 形状对象。
8. `sessions` 中不存在 `session_id = p_sid` → **missing 对象**。禁止调用 `v13_should_run_gate`、`v13_should_run`、`v13_quota_eligible`。
9. 否则计算接纳位并返回评估对象。

步骤 1–7 即使会话不存在也返回形状，不返回 missing。步骤 8 在步骤 1–7 都通过之后才发生。

**接纳位（只在步骤 9）：**

```text
gate_text       = v13_should_run_gate(p_sid)      -- text 或 SQL NULL
should_run_bool = v13_should_run(p_sid)           -- boolean
quota_bool      = v13_quota_eligible(p_sid)       -- boolean
admitted        = should_run_bool AND quota_bool
```

三个调用都发生。`admitted` 的表达式里不出现 `p_suggestion` 的任何字段。`suggested_should_run = false` 而两个谓词为真时，`admitted` 仍是 true。`suggested_should_run = true` 而 `goal_stopped` 或配额不合格时，`admitted` 仍是 false。

谓词若在步骤 8 之后仍 RAISE（会话在存在性检查与谓词之间被删掉），异常原样传播。不写 `EXCEPTION WHEN` 把它收成 JSON。测试是单连接串行，不把这个窗口做成产品承诺。

函数体 `$fn$` 内，包括注释，不得出现：`dblink`、`pg_net`、`lo_import`、`lo_export`、`pg_read_file`、`pg_write_file`、`copy program`、`v13_wake_is_satisfied_v1`、`v13_claim(`、`v13_claim_fair`、`13002`、`13003`、`v13_agentctl_`。整份 SQL 文件同样不得出现这些记号，也不得出现 `INSERT INTO tools`、`SECURITY DEFINER`、动态 `EXECUTE`。说明写在 `$fn$` 外的 `COMMENT` 里。

`COMMENT` 固定大意（英文，写在函数体外）：STABLE read；discards `suggested_should_run`；`admitted` is `v13_should_run AND v13_quota_eligible`；not a tools row；does not raise on a shape or missing session.

安装是一个 `BEGIN ... COMMIT`：`CREATE FUNCTION`，然后 `REVOKE`，然后 `GRANT`，然后 `COMMENT`，然后 `COMMIT`。不做 upsert。函数已存在则整笔回滚。

### 3.3 返回 jsonb 的三种精确形状

比较用 jsonb 相等，不比较文本里的键顺序。不得多键，不得少键。

**形状失败**（步骤 1–7）。父合同钉死的三键，不要加 `schema_version`：

```json
{"ok": false, "reason": "shape", "admitted": false}
```

**会话不存在**（步骤 8）：

```json
{"ok": false, "reason": "missing", "admitted": false}
```

**评估成功**（步骤 9），无论 `admitted` 是 true 还是 false。`gate` 在 SQL NULL 时是 JSON null，键仍然存在：

```json
{
  "schema_version": 1,
  "ok": true,
  "admitted": true,
  "should_run": true,
  "quota_eligible": true,
  "gate": null
}
```

| 键 | 类型 | 含义 |
|---|---|---|
| `schema_version` | number `1` | 只出现在评估对象 |
| `ok` | boolean `true` | 两个谓词已经被调用 |
| `admitted` | boolean | `should_run AND quota_eligible` |
| `should_run` | boolean | `v13_should_run` 的返回值 |
| `quota_eligible` | boolean | `v13_quota_eligible` 的返回值 |
| `gate` | string 或 null | `v13_should_run_gate` 的文本。null 表示没有 block id |

测试必须同时钉住这条不变量：`admitted == (should_run and quota_eligible)`，且 `should_run == (gate is None)`。矛盾的三元组即失败。不返回 `note`、`suggested_should_run`、`subject_session_id`、`reason`（评估对象没有 `reason`）。

没有第四种 reason。不 RAISE 出 `v13: agentctl args` 那种文案。这是和 stage 41 写动词的合同差异：写失败必须进异常，宏观读失败必须是 jsonb，这样调用方用返回值停住，而不是靠 sql 臂收异常。本函数本来就没有 sql 臂。

安静、未停、无 human、配额种子仍是默认时，评估对象是 `admitted=true`、`should_run=true`、`quota_eligible=true`、`gate=null`。`goal/stopped` 已经写下且没有 human 时：`admitted=false`、`should_run=false`、`quota_eligible=true`、`gate="goal_stopped"`。根上有 ready human 时：`admitted=false`、`should_run=false`、`gate="human_pending"`。`quota_eligible` 在没有 `turn/material_spent` 时仍为 true；human 门先于配额门，不要求这次把配额打成 false。

### 3.4 成功剧本

一个 Python 对象（测试内的普通类或闭包，不是新的生产服务）持有：一个 `LoopDriver`、一个 FakeLLM、一个 FakeTool、`root`、`child`、`todo_id`、`apply_id`、`advance_words` 列表、宏观调用次数。成功剧本全进程只有这一个 `LoopDriver` 的 `advance` / `serve` / `_settlement_advance` 被调用。拒绝夹具与 human 夹具用直接 SQL，不调用 `v13_advance`。

FakeLLM 记录每一次的 `layers` 实参、`peek["kind"]`、以及调用时 `driver.conn.get_transaction_status()`。

- `peek["kind"] == "plan"`：返回 `{"todos":[{"text":"read one bounded file","task_class":"advancement_task","status":"runnable","verb":"add_new","due":null}]}`。文本长度在 1..1024。不带 `todo_id`。
- 其他 peek（`serve` 送来的 llm effect）：返回 `{"text":"open one child for the bounded read","tool_calls":[{"id":"tc-read","name":"spawn_subsession","args":{"task":"read the bound file"}}]}`。必须过 `_spawn_answer_ok`。名字不是 `spawn_subsession`、带了 `result_kind`、或多一个 tool_call：场景 RAISE，不调用 complete，不执行任何 `v13_agentctl_*`。
- FakeTool `read_file_py`：记录 `tool_name` 与事务状态，返回固定 excerpt 字符串 `"bounded excerpt"`。非空，长度远小于 1024。不读控制文件，不打开套接字。

`driver.tools` 只放 `read_file_py` 这一个键。成功路径不经过 `serve` 的 tool 分支，但 handler 必须登记，以便负向断言能说明「就算 serve 被误用，也不会走到网络」。

**上界。** 模块级赋值恰一处：`GOAL_WORKFLOW_MAX_ADVANCE = 4`。包装在真正调用 `v13_advance` 之前检查 `len(advance_words) >= GOAL_WORKFLOW_MAX_ADVANCE`，成立则 `raise AssertionError("scene_advance_cap")`，不执行 SQL。三处真正的推进都走这个包装：

- 包装 `driver.advance`
- 替换实例上的 `_settlement_advance`（先调原方法，再把 `(sid, word)` 记入 `advance_words`）。`serve` 内部调用的是实例方法，因此第 2 次会被记到。替换发生在 Python 实例上，不改 `driver.py` 文件字节。

期望词序列，会话 id 用根与子的实际 uuid：

| # | 调用 | 词 |
|---|---|---|
| 1 | `advance(root)` | `waiting` |
| 2 | `serve(root)` 内部的 `_settlement_advance(root)` | `progressed` |
| 3 | `advance(child)` | `waiting` |
| 4 | 场景直接 `_settlement_advance(root)` 后 commit | `waiting` |

`serve` 自己的返回值必须是 `("served", "accepted")`。它不是第 2 次的词。词来自包装器。

**宏观检查点**在成功根上恰 5 次，每次都要求评估对象 `ok is True` 且 `admitted is True`。任何一次不是，场景抛错并停止，不执行该检查点后面的写步骤。5 次的位置：

1. `plan_commit_entry` 与 `submit_override` 都已 commit 之后，`plan_writer` 之前。
2. `plan_writer` commit 之后，第 1 次 `advance` 之前。
3. `serve` 之前。
4. `v13_child_pointer` commit 之后，`advance(child)` 之前。
5. 子会话读完成 commit 之后，第 4 次 `_settlement_advance` 之前。

每次宏观 `SELECT` 自己的快照窗口前后相等（函数零写）。窗口不要包住相邻的 `plan_writer` 或 advance。

**有序步骤。** 每一步都假定上一步已经 commit，连接处于 idle。

1. **解析四层。** `SELECT v13_workflow_resolve('workflow_template', 1)`。取四键，按 `LAYER_ORDER` 放进新 dict。任一键缺失或 `btrim` 后为空则失败。然后 `driver.layers = 该 dict`。这一步在任何 `four_layers()` 之前，包括计划 IO 和 `serve`。不把四段拼成一个字符串，不写回 `v13_policies`。
2. **开会话。** `driver.plan_commit_entry({"route_policy_name":"controller","version":1})`。返回文本记为 `root`。断言 `sessions.route_policy_name/version` 是 `controller` / 1，`parent_session_id` 是 NULL，`status` 不是终态。不调用 `plan_prelude`、`plan_admit`。
3. **水位。** `driver.submit_override(root)`。断言根上恰一条 `goal/override`，`max(seq)` 非空。不把这次调用算进四次 advance。
4. **检查点 1。** 宏观建议的 `subject_session_id` 是 `root` 的规范文本，`suggested_should_run` 是 jsonb `true`，`schema_version` 是数字 1，`kind` 是 `macro_suggestion`。`admitted` 必须为 true。否则不调用 `plan_writer`。
5. **计划 IO（事务外）。** `_assert_idle`：`get_transaction_status()` 必须是 `TRANSACTION_STATUS_IDLE`。调用 `llm(driver.four_layers(), {"kind":"plan"})`。用导入的 `_plan_answer_ok` 判定。失败则停，不写 plan。最多 `PROVIDER_ATTEMPT_CAP`（2）次；夹具第一次就合法，`driver.attempts_used` 保持 0。记录到的事务状态必须是 idle。
6. **canonical 然后 `plan_writer`。** 读根上 `max(seq)`，SQL NULL 则停（这就是水位失败，不准去改写者）。`apply_id = uuid4()`。canonical 对象键恰为 `schema_version`（数字 1）、`call_kind`（`"plan_commit"`）、`based_on_seq`（刚才的 seq 的 int）、`supersedes`（JSON null）、`todos`（长度 1）。todo 键恰为 `todo_id`（新 uuid 文本）、`text`、`text_hash`（导入的 `text_hash`）、`task_class`、`status`（`"runnable"`）、`due`（JSON null）、`verb`（`"add_new"`）。按 `uuid.UUID(todo_id).bytes` 排序后再交给写者。调用 `driver.plan_writer(root, apply_id, "plan_commit", canonical)`，让驱动器传 SQL NULL actor。写者返回之后、第 1 次 advance 之前，折叠该 todo 的 `status` 必须已经是 `runnable`，`task_class` 必须是 `advancement_task`。根上 `ready|claimed` effect 计数必须是 0。
7. **检查点 2。** 再读宏观。`admitted` 不是 true 则不 `advance`。
8. **第 1 次 advance。** `advance(root)`。期望词 `waiting`。根上恰一条 `kind=llm`、`status=ready` 的 effect，`request.route.reason = selected_todo`。这把 prefix 的 provider 臂和 `:404-466` 的提前 waiting 分开：后者不会有这条 llm 行。到不了 `v13_route` 的原因：prefix 返回非 NULL，`v13_advance` 在 `:511-512` 返回。禁止在这一步 `serve`、禁止 `v13_child_pointer`、禁止 `v13_parse`。
9. **检查点 3。** `serve` 之前再读宏观。
10. **第 2 次，只 `serve(root)`。** Fake 的 llm 答案过 `_spawn_answer_ok`，事务状态 idle。`serve` 返回 `("served", "accepted")`。第二项是五参 `v13_complete` 委托六参后的 `RETURN 'accepted'`（`v13/acl/v13_acl.sql:456`，五参在 `:470`；`driver.py:385`）。包装器记下的词是 `progressed`。原因：complete 写下一条 `tool/call`（`name=spawn_subsession`），spawn 臂在 `:508` `RETURN 'progressed'`，早于 prefix。若词是 `waiting`，按 §2.5 停在 `:486` 或 `:489`，不要改夹具去追绿。断言恰一个子会话，`parent_session_id = root`。根上 llm effect 为 `succeeded`。子会话 `status` 不是终态。禁止对子会话 `serve`。禁止再对根 `advance`。
11. **指针。** commit 已经由 `serve` 完成。用场景自己的游标，照 `_pointer` 的五个参数：`child`；子会话的 `parent_session_id`；`v13_plan_map_root(child)`（必须等于 root）；折叠里恰一行 `task_class=advancement_task AND effect_id IS NOT NULL` 的 `todo_id`；根上 `max(seq)`。这个 `effect_id` 是第一次 `advance(root)` 的 provider 臂写下的 llm effect（`v13_plan_arm.sql:309-328`，apply id 前缀 `bind:`），不是 `read_file_py`，也不是步骤 1 的 layer 解析。查询必须在 `serve` 之后。提前查会得到 NULL，`v13_child_pointer` 随后 RAISE `v13: workflow pointer: payload`。`SELECT v13_child_pointer(...)`。断言子会话上 `workflow/pointer` 恰一条。不把函数名加入 `ALLOWED_CONTROL_SQL`。
12. **检查点 4。** 然后才 `advance(child)`。
13. **第 3 次 advance。** `advance(child)`。期望 `waiting`。子会话上恰一条 `status=ready`、`tool_name=read_file_py`、`kind=tool` 的 effect。到不了路由的原因：子臂 `v_ptr_n = 1 AND v_read_n = 0`（约 `:144-158`）返回 `waiting`。若读文件效果已经存在，该臂返回 NULL（`:161`），同一次 advance 会继续往路由走并冒出 human。所以这一步之前禁止 complete 这条 effect，也禁止 `serve(child)`。
14. **事务外 FakeTool。** `_assert_idle`。取出那条 ready 的 `read_file_py`（`effect_id`、`tool_name`、`request`）。`tool_name` 不是 `read_file_py`，或落在 `("edit","write","bash")`，则失败。调用 FakeTool。excerpt 不是非空 str，或 `len > EXCERPT_CAP`，则在任何 `UPDATE` 之前失败。记录到的事务状态必须是 idle。
15. **`_complete_read` 同一事务。** 打开游标：领用 `UPDATE ... RETURNING attempt_no, fence`（`lease_owner` 用 `driver.worker`）；零行则 rollback 并失败；五参 `v13_complete(effect_id, attempt, fence, 'succeeded', {"excerpt": excerpt})`；`commit`。不调用 `driver.complete`。不调用 `_settlement_advance`。不 `advance(child)`。断言该 effect `status=succeeded`，`result.excerpt` 等于夹具字符串。
16. **检查点 5。** 根结算之前再读宏观。
17. **第 4 次。** 新开游标，调用包装后的 `_settlement_advance(cur, root)`，然后 `commit`。期望词 `waiting`。到不了路由的原因：根归档臂（约 `:183-205`）看见已成功的 `read_file_py` 与仍 `runnable` 的 advancement todo，写 `todo_delta` 后返回 `waiting`。禁止用 `serve(root)` 代替：此时根上没有可服务的 ready 非 human effect，`serve` 会返回 `none` 并且不 advance，归档不会发生。禁止用 `driver.advance` 代替这次调用：第 4 次的形状是 `_settle_root`，snap 与 advance 在同一事务。
18. **停止。** `advance_words` 长度必须是 4。进入第 5 次包装必须在 SQL 之前抛 `scene_advance_cap`。成功剧本里若出现 `kind=human` 的 effect，或出现 `reason=low_intent_confidence` 的事件，本剧本失败。这不是安静的成功。

`read_file_py` 的结果只通过五参 `v13_complete` 进入既有 `effects.result` 与 `tool/result`。不写 projection 文件、receipt 文件或恢复日志。不把 excerpt 再写进 `driver.layers`。

第 1 次之前若折叠还不是 `runnable`，prefix 在 `:292-294` 返回 NULL，同一次 advance 会进 `v13_route`。测试用「恰一条 ready llm，且 human 计数为 0」钉住没有掉进那条路。

### 3.5 成功时库里必须能看见的行

全部针对成功剧本那一个 root 与它唯一的 child。

- 根上 `plan/committed` 恰 1 条。`todo/delta` 里 `payload->'canonical'->>'status_to' = 'done'` 恰 1 条。
- `v13_plan_todo_fold(root)` 里 `task_class=advancement_task` 恰一行，`status=done`。
- 子会话恰 1 个，`parent_session_id` 是根。
- 子会话上 `workflow/pointer` 恰 1 条。场景源码里写指针的调用只有 `v13_child_pointer`。
- 子会话上 `tool_name=read_file_py` 且 `status=succeeded` 恰 1 条。`result->>'excerpt'` 是非空字符串且 `char_length` ≤ 1024，并等于夹具 excerpt。
- 根上 llm effect `status=succeeded`。对应 `tool/call` 的 `name` 是 `spawn_subsession`，`args` 只有 `task`。
- 根与子的 effects 里 `kind=human` 的行数都是 0。`type=steer/injected` 的行数是 0。`type=cancel/requested` 与 `human/responded` 的行数是 0。
- 根上 `goal/override` 恰 1 条，来自步骤 3。它不是 human，也不是 steer。
- 第 4 次的词是 `waiting`。根与子的 `sessions.status` 都不属于 `completed|failed|cancelled`。
- `turn/material_spent` 的计数**不是**成功条件。断言不得要求它大于 0，也不得用它消耗配额。
- `spawn_subsession.enabled` 仍为 true。
- advance 词序列恰为 §3.4 的四行。宏观检查点恰 5 次且都 `admitted=true`。

`effects.kind` 只断言成功行的 kind 是 `llm` 或 `tool`。不断言约束定义等于五值列表。

### 3.6 三条独立夹具

三条都不进入 §3.4 的四次 advance，不共用成功 root，互不为另一种结局。每条都用 `plan_commit_entry` 的 controller/1 开自己的会话（human 与拒绝需要一个真实 `p_sid`；形状失败里的 missing 用没有行的 uuid）。

**`scene_macro_reject_zero_write`。** 安静会话：`plan_commit_entry` 之后，`effects` 里 `status IN ('ready','claimed','unknown')` 的行数为 0。不 enqueue，不 override 也行（本夹具不调用 `plan_writer`）。调用 `v13_goal_stop(sid, 'operator_stop')`。空会话不会让 `v13_goal_fingerprint` 因为「没有事件」而 RAISE：会话行存在时它读 `v13_probe`（`v13/manifest/v13_manifest.sql:830-843`，缺事件时 `max_event_seq` 为 `-1`）并返回哈希；没有 `goal/stopped` 时 `v13_goal_fold` 是 `running`。按夹具跑。不要补 `user/message`。若这里 RAISE `v13: goal busy`，说明夹具不安静，先修夹具。若仍 RAISE 别的文案，停止并报告，不准改 `v13_goal_stop` 或 `v13_govern.sql`。父合同允许留下的只有开会话那一行加上这一条 `goal/stopped`。

然后窗口只包住一次 `v13_macro_suggestion`，建议里 `suggested_should_run` 为 jsonb `true`。期望评估对象：`ok=true`、`admitted=false`、`should_run=false`、`quota_eligible=true`、`gate="goal_stopped"`。窗口前后：`plan/committed` 新增 0、`todo/delta` 新增 0、`effects` 新增 0，其余快照列相等。该会话上 `goal/stopped` 恰 1 条，这 1 条在窗口之外已经存在。此后不调用 `plan_writer`、`advance`、`serve`、`v13_child_pointer`。

**`scene_suggestion_shape_zero_write`。** 每种子都用快照包住那一次 `SELECT`，前后相等。形状样本至少包括：

| 输入 | 期望 |
|---|---|
| SQL NULL | 形状对象 |
| JSON null、数组、标量、空 object | 形状对象 |
| 缺任一必填键 | 形状对象 |
| 额外键 `source_principal` 或 `admitted` | 形状对象 |
| `kind` 为别的字符串、或带首尾空格 | 形状对象 |
| `schema_version` 为字符串 `"1"`、或数字 0、2 | 形状对象 |
| `subject_session_id` 大写、空白、无连字符、或另一条真实会话的 uuid | 形状对象。谓词增量为 0。有真实会话但 subject 不同，仍然是形状，不是 missing |
| `suggested_should_run` 为字符串 `"true"` 或数字 1 | 形状对象 |
| `note` 为 JSON null、或 `btrim` 后 257 个字符 | 形状对象 |
| `note` 为 256 个 `字`（按字符 256，按字节更多）且其余合法 | **不是**形状失败：走评估 |
| 省略 `note`，其余合法 | 评估 |
| `p_sid` 是 SQL NULL，建议其余合法，`subject_session_id` 是一条规范 uuid 文本 | 形状对象。三个谓词的事务内调用增量都是 0。不是 missing |
| `p_sid` 与 `subject_session_id` 同为某个**没有行**的规范 uuid，其余合法 | missing 对象。`v13_should_run`、`v13_should_run_gate`、`v13_quota_eligible` 的事务内调用增量都是 0 |

丢弃证明放在本函数里，另开一条会话，不 advance：合法建议且 `suggested_should_run` 为 jsonb `false`。期望 `admitted=true`、`should_run=true`、`quota_eligible=true`、`gate=null`，窗口零写。这证明 false 没有被当成 `AND` 的一项。

配额合取证明也放在本函数里，用 SAVEPOINT，并且必须回滚：

- `INSERT quota_window` version 2，`active=false`，value 键仍是 `allowed` / `schema_version` / `slot_minutes` / `window_hours`，`allowed=0`，其余与 version 1 相同（`schema_version` 数字 1，`window_hours` 8760，`slot_minutes` 0）。
- `UPDATE` version 1 `active=false`，再 `UPDATE` version 2 `active=true`。先关后开，避免 `ux_v13_policies_one_active` 撞车。不准 `UPDATE` value。
- 对一条未停、无 human 的会话调用宏观函数，`suggested_should_run=true`。期望 `quota_eligible=false`、`should_run=false`、`admitted=false`、`gate="quota_window"`（version 3 里这扇门在 `goal_stopped` 之前，本会话又没停）。
- `ROLLBACK TO SAVEPOINT`。随后断言活动的 `quota_window` 仍是 version 1，version 2 不存在。成功剧本不得看见 `allowed=0`。

上面这一条证的是 `gate="quota_window"` 时 `admitted=false`。version 3 里 `quota_window` 是 `block` 且排在 `goal_stopped` 之前（`v13/govern/v13_govern.sql:429-432`），所以 `quota_eligible=false` 时 `should_run` 也是 false。只断言 `admitted = should_run` 的错误实现会通过这一条，也会通过返回三元组不变量。合取本身要用第二个 SAVEPOINT，同样必须回滚，不替换上一条：

- 插入未激活的 `should_run` 下一版（今天最大是 3，所以是 version 4；若已有更高版，用 max+1，不覆盖已有行）。value 键恰为 `gates` 与 `schema_version`，`schema_version` 为数字 1，`gates` 恰一个元素 `{"id":"quota_window","effect":"shadow"}`。这能过 `v13_should_run_gate` 的键集与 id 白名单（`v13/govern/v13_govern.sql:380-398`）。`shadow` 不 `RETURN` 门 id。
- 再插入未激活的 `quota_window` version 2，`allowed=0`，键与上一条证明相同。
- 先把 `should_run` version 3 与 `quota_window` version 1 的 `active` 设为 false，再把新两行设为 true。不准 `UPDATE` value。
- 对一条未停、无 human 的会话调用宏观函数。期望 `should_run=true`、`quota_eligible=false`、`admitted=false`、`gate` 为 JSON null。
- `ROLLBACK TO SAVEPOINT`。随后活动行必须仍是 `should_run` version 3 与 `quota_window` version 1。成功剧本不得看见 shadow 政策或 `allowed=0`。

调用计数：`SET track_functions = all`（会话级，不用 `SET LOCAL`）。每个测量事务先做一次可回滚的 `v13_control_authorized` 探针；探针看不到增量就报告环境阻塞并失败，不把谓词换成 spy，不改冻结函数。`COMMIT` 会清掉事务内计数，下一次测量要重新武装。`v13_json_keys` 与 `v13_canonical_uuid` 是 `IMMUTABLE`，可能被内联，不靠它们的计数。

**`scene_human_pending_holds`。** 新的 root。请求体照抄已有夹具 `enqueue_human`（`v13/agentctl_verbs/test_agentctl_verbs.py:213-217`）：`v13_enqueue_effect(root, 'human', {"schema_version":1,"interaction_ref":"ix-goal-workflow-hold"})`。`interaction_ref` 是非空字符串，不必是 uuid；`v13_pending_human` 只看 `kind` 与 `status`。断言该行 `status=ready`、`kind=human`。不调用 `v13_goal_stop`（此时会 `v13: goal busy`）。宏观建议 `suggested_should_run=true`。期望 `admitted=false`、`should_run=false`、`gate="human_pending"`。然后停止。禁止 `v13_cancel`、五参或六参 `v13_complete`、`agentctl_answer`、`agentctl_cancel`，禁止 `UPDATE effects` 把这行改成 `succeeded` / `cancelled` / skipped。断言：该 effect 仍是 `ready`；`cancel/requested` 为 0；`human/responded` 为 0；`sessions.status` 不属于三种终态。这条停止是合同上的成功停止，**不是**「任务被解决」，测试名和 README 都不要把它写成 solved。

`v13_last_user_seq` 在没有 `user/message` 时返回 `-1`（`v13/schema/v13_core.sql:153-156`），缺这条事件本身不是 enqueue 失败。若仍 RAISE，停止并核对函数，不准改 `v13_control.sql`。只有核对证明现有函数确实要求前缀事件时，才在夹具里追加一条非空 `user/message`，并且仍然禁止 advance。

### 3.7 断言怎么证明

十条名字都必须作为 `check()` 的 label 出现。可以在同一函数里再加更细的 label。不要把 `actl_driver_demoted` 加成第十一条。

| 断言 | 证明方式 |
|---|---|
| `scene_solved_no_human` | 跑完 §3.4 后核对 §3.5。`kind=human` 为 0，`steer/injected` 为 0，`advance_words` 长度 = 4。出现 human 或 `low_intent_confidence` 则失败 |
| `scene_archive_waiting` | `advance_words[3]` 的词是 `waiting`；`v13_plan_todo_fold(root)` 该 todo `status=done`；根与子 `status` 都不在 `completed\|failed\|cancelled`；`todo/delta` 的 `status_to=done` 恰 1。先例对照 `test_real_chain.py:392-399`，但是本场景自己的行，不调用 `RealChain` |
| `scene_layers_unjoined` | FakeLLM 至少被调用两次（plan 与 serve）。每一次 `layers` 都是长度 4 的有序对，名字恰为 `LAYER_ORDER`，文本分别等于 `v13_workflow_resolve` 的四段，且都非空。实参的类型不是 `str`。四段无分隔符拼接后的字符串不得等于任何一个单独的 layer 文本，也不得作为 llm 的唯一字符串实参出现。另起一个 `layers={}` 的 `LoopDriver`（不调用 `advance`）：`four_layers()` 抛 `KeyError`，`effects` 计数不变 |
| `scene_macro_reject_zero_write` | §3.6 的 `goal_stop` 夹具。建议为 true 时 `admitted=false` 且 `gate=goal_stopped`。窗口内零新增 `plan/committed`、`todo/delta`、effects |
| `scene_suggestion_shape_zero_write` | §3.6 的形状矩阵（含 SQL NULL `p_sid`）、missing 的零谓词增量、`suggested_should_run=false` 仍 `admitted=true`、回滚掉的 `allowed=0` / `gate=quota_window`，以及回滚掉的 shadow 合取（`should_run=true` 且 `quota_eligible=false` 时 `admitted=false`） |
| `scene_human_pending_holds` | §3.6。effect 仍 `ready`；无 `cancel/requested`、无 `human/responded`；该夹具函数的 AST 不得 `Call` `v13_cancel`、`v13_complete`、`v13_agentctl_answer`、`v13_agentctl_cancel`，也不得 `UPDATE` 这条 human 行。不扫进程级 SQL 日志：成功剧本自己要调用五参 `v13_complete`。会话非终态 |
| `scene_no_wake_no_claim` | 见下文扫描。证明新 SQL 与场景调用图都不含 wake / claim / 13002 / 13003 / IO 记号 |
| `actl_driver_untouched` | `git cat-file -e fb295ac6c7459bb98dac57e37883af549d2d8a4c^{commit}`。失败则停止，不准换成 HEAD。`original = git show <hash>:v13/loop_driver/driver.py` 的字节，`current` 为工作区该文件字节，调用 `v13.plan_arm.test_plan_arm.r1_driver_restore(current, original)`。不改 `driver.py` |
| `actl_scene_no_decide_exit` | 见下文 AST。扫描对象是 `test_goal_workflow.py` 全模块 |
| `scene_advance_cap` | 常数是 4；第 5 次在 SQL 之前失败；失败前后事件计数、human 计数、折叠 `done` 都不变 |

**`scene_no_wake_no_claim` 的扫描。** 两路，不要用一条「扫整个测试文件子串」的实现：测试源码里的 needle 元组会把自己打红。

1. SQL：`pg_get_functiondef('public.v13_macro_suggestion(uuid,jsonb)'::regprocedure)` 以及磁盘上的 `v13_goal_workflow.sql` 全文，压空白、转小写后不得含 `dblink`、`pg_net`、`lo_import`、`lo_export`、`pg_read_file`、`pg_write_file`、`copy program`、`v13_wake_is_satisfied_v1`、`v13_claim(`、`v13_claim_fair`、`13002`、`13003`。`v13_claim` 只按 `v13_claim(` 认，与 `test_agentctl.py:645-655` 相同。同时不得含 `security definer` 与 `execute ` 动态执行（`EXECUTE FUNCTION` 这种触发器语法本文件没有；用「`execute ` 出现在函数体内」会误伤 `REVOKE EXECUTE`，所以只扫函数体 `prosrc`，不把文件头的 `GRANT EXECUTE` 算进去）。`prosrc` 不得含 `v13_agentctl_`。
2. 场景：对 `test_goal_workflow.py` 做 `ast.walk`，任何 `Call` 的名字（`Name.id` 或 `Attribute.attr`）不得是 `v13_wake_is_satisfied_v1`、`v13_claim`、`v13_claim_fair`。字符串常量里出现这些字不算调用。

**`actl_scene_no_decide_exit` 的 AST。** 同一棵树上，`Call` 的 `Name.id` 或 `Attribute.attr` 不得是：

- `decide`、`decide_exit`、`run_turn`、`tick`
- `plan_prelude`、`plan_admit`
- `run`、`_run`（挡住 `RealChain.run` / `_run`；本模块不应再有别的 `run` 方法。若包装器需要名字，用 `run_scene`，不要用 `run`）
- `v13_agentctl_observe`、`v13_agentctl_steer`、`v13_agentctl_answer`、`v13_agentctl_cancel`
- `v13_parse`

另外：不得 `Call` 名字 `RealChain` 或 `GoalSupervisor`。允许导入 `LoopDriver`、`_plan_answer_ok`、`_spawn_answer_ok`、`text_hash`、`EXCERPT_CAP`、`LAYER_ORDER`、`as_obj`、`r1_driver_restore`。成功路径必须能看见对 `v13_complete`、`v13_child_pointer`、`v13_workflow_resolve`、`v13_plan_writer`、`v13_advance`、`v13_submit_override`、`v13_macro_suggestion` 的调用；这些不在禁止表里。`v13_goal_stop` 与 `v13_enqueue_effect` 只允许出现在拒绝夹具与 human 夹具的函数里。实现时用 `ast` 父指针把这两次调用的外围函数名钉死，避免成功剧本也去 stop 或 enqueue human。

**`scene_advance_cap`。** 成功剧本结束、折叠已经是 `done` 之后，再调用一次包装过的 `advance(root)`。期望 `AssertionError` 且文案含 `scene_advance_cap`。用快照证明这次尝试没有新事件、没有 human、折叠仍是 `done`。禁止为了观察第 5 次的词而真的执行 `v13_advance`：prefix 在没有选中 todo 时返回 NULL（`:292-294`），根上的 `v13_triage_steer` 会在 `v13_route` 之前入队 human。那是 gate 失败，不是可以观察的「第 5 次 waiting」。

常数的位置：测试源码里 `GOAL_WORKFLOW_MAX_ADVANCE = 4` 恰一次。用 `git grep -n -F GOAL_WORKFLOW_MAX_ADVANCE -- v13` 证明每一条命中都是 `v13/goal_workflow/test_goal_workflow.py`。不要扫整个仓库：本计划与父合同都会写出这个标识符，提交之后全库 grep 会红。README 的声称句写「上界 4」，不写这个标识符。SQL 里不写这个上界。

**`actl_driver_untouched` 的导入。** `from v13.plan_arm.test_plan_arm import r1_driver_restore`。当前文件尾是 `if __name__ == "__main__"` 守卫（`v13/plan_arm/test_plan_arm.py:1731`），导入不会跑 `main`，也不会创库。不要复制一份 `r1_driver_restore`。若以后有人把 `main()` 抬到模块级，停止，不要改这个入口去「方便导入」。

成功剧本的模块 docstring 第一段就是声称句原文。

### 3.8 装载与合成负例

`v13/load.py` 只追加两行，分别在两个容器最后一个元素之后：

```text
V13_ROOT / "goal_workflow" / "v13_goal_workflow.sql",
"goal_workflow": 42,
```

`r1_load_append_ok` 的 `approved` 改为四项，顺序固定：

```text
("fair_claim", "v13_fair_claim.sql", "fair_claim", 39)
("agentctl", "v13_agentctl.sql", "agentctl", 40)
("agentctl_verbs", "v13_agentctl_verbs.sql", "agentctl_verbs", 41)
("goal_workflow", "v13_goal_workflow.sql", "goal_workflow", 42)
```

失败文案改为 `append is not fair_claim/39 then agentctl/40 then agentctl_verbs/41 then goal_workflow/42`。`order_names` 不改。函数签名不改。

`r1_phase_d_prefix_allowance` 增加集合，不把 `"v13/goal_workflow/"` 放进 `prefixes`：

```text
v13/goal_workflow/v13_goal_workflow.sql
v13/goal_workflow/setup_db.py
v13/goal_workflow/test_goal_workflow.py
v13/goal_workflow/README.md
```

`allow()` 的路径条件变为：三个前缀，或 stage40 四路径，或 stage41 四路径，或 stage42 四路径。`extra - known_names - stage40 - stage41 - stage42 <= fresh_ok`。stage42 必须是 tracked 的子集，缺一则 needle 为 `stage 42 path is not tracked`。旧 needle `outside the three prefixes`、`stage 40 path is not tracked`、`stage 41 path is not tracked` 保持原文。

必须改写的旧负例（它们一旦 42 合法就会换失败原因或不再失败）：

| 今天的构造 | 42 之后会怎样 | 新构造与 needle |
|---|---|---|
| `extra \| {v13/goal_workflow/test_goal_workflow.py}`，needle `outside the three prefixes` | 路径已在 stage42 里，不再拒绝 | 改为 `v13/external_exec/test_external_exec.py`，needle 仍是 `outside the three prefixes` |
| 在 verbs 尾后追加 `goal_workflow` / `v13_goal_workflow.sql` / 42 | 那就是合法尾；若 live 已经含 42，再 replace 会变成重复路径 | 改为在 `goal_workflow` 行后再追加 `external_exec` / `v13_external_exec.sql` / 43，tracked 并上该 SQL 路径。`replace` 的 count 为 1。needle 为**新的四项文案** |
| `replace("v13_agentctl.sql", "v13_agentctl_extra.sql", 1)` 期望三项文案 | 元组不匹配时的文案变了 | 同一构造，needle 改为四项文案 |

保留不动的负例：`v13/agentctl/extra.py`、`v13/agentctl_verbs/extra.py`、缺 stage 40 文件、缺 stage 41 文件、`"agentctl": 40a`、`"agentctl": 41` 的 duplicate stage number、`"agentctl_verbs": 40` 的 duplicate stage key、`"agentctl_verbs": 42` 的不连续编号、`"agentctl_verbs": 41a`、三前缀外的 `v13/not_allowed/x.py`、以及函数前半对 fair_claim 结构的全部 `must_reject`。

另加，每次只改一个条件：

- `v13/goal_workflow/extra.py` → `outside the three prefixes`
- tracked 去掉 `v13/goal_workflow/v13_goal_workflow.sql` → `stage 42 path is not tracked`
- `"goal_workflow": 43` 而 SQL 路径仍是该项 → `stage number is not the next contiguous value`
- `"goal_workflow": 42a` → `load diff plus line is not a canonical append`
- `replace("v13_goal_workflow.sql", "v13_goal_workflow_extra.sql", 1)` → 四项文案

`replace` 一律 `count=1`。`v13_agentctl.sql` 不是 `v13_agentctl_verbs.sql` 的子串（中间还有 `_verbs`），既有那条负例可以留在 verbs 文件名之外；不要改成无 count 的全替换。

### 3.9 一次性库与安装比较

`setup_db.py` 沿 `v13/agentctl_verbs/setup_db.py`，不调用会 DROP 固定库名的旧 `prepare()`。

- `DB = ll_goal_workflow_{pid}_{secrets.token_hex(3)}`。
- 拒绝 `agent_v13_` 前缀和 `agent_v13_longloop_p0_probe`。
- `probe_extension`：`stannum`、`pg_jsonschema` 缺一即失败。
- 同名已存在则退出，不 DROP、不接管。`CREATED` 仅在 `CREATE DATABASE` 成功后为 true。不预先 DROP。
- `load_stage(server, DB, "agentctl_verbs")`。不在 setup 里应用 `v13_goal_workflow.sql`。
- 连接用 `get_server()` 的本地 URI。不另查是不是 Unix socket。不调用 `poison()`。不设置真实 provider。
- 测试在 `create` 之前进入 `try/finally`。只在 `CREATED` 时 `DROP DATABASE "{DB}" WITH (FORCE)`。清理失败使进程非 0。DROP 成功之前不打印最终成功结论。`setup_db.main` 若被直接调用，它的 `SystemExit` 不得绕开测试的 `finally`：创建步骤放进测试的 `try`。

安装比较在任何行为夹具之前，基准是「装到 41、尚未跑本文件」的快照：

- `public` 下 `proname LIKE 'v13_%'` 或 `proname = 'v_goal_tree'` 的定义哈希、属主、`prosecdef`、ACL、`provolatile`：除新函数外全部不变。新函数恰为 `v13_macro_suggestion(p_sid uuid, p_suggestion jsonb)`。`prosecdef` 为 false，`provolatile` 为 `s`，`proconfig` 去空格后含 `search_path=pg_catalog,public`。
- `tools` 全表逐列不变，包含 `agentctl_observe`、三个写动词、`spawn_subsession`、四条 read 工具。`v13_tools_meta.revision` 与 `candidate_generation_revision` 不变。
- 无新表、新列、新索引、新触发器。安装期 `events` 与 `effects` 计数不变。
- `v13_route_policies` 与 `v13_policies` 的行集不变。不重插 `controller`。断言 `controller` / 1 存在且 `state=frozen`，然后 `plan_commit_entry` 能用这份 spec 开会话。不在 42 的测试里重数那 16 条带；带集的主人是 stage 41。若 frozen 行不存在，停止：41 没有装进来。
- `v13_named_sql_writer('v13_macro_suggestion')` 为 NULL，`v13_spawn_writer_ok` 为 false。observe 的 named 仍为 NULL。`v13_spawn_writer_ok('v13_spawn_subsession')` 仍为 true。
- ACL：`v13_route` 可 EXECUTE；`public`、`v13_recall`、`v13_worker`、`v13_resolve`、`v13_spawn_owner` 不可。`SET ROLE v13_route` 对一条已存在会话做一次评估调用并成功；`SET ROLE v13_recall` 得到 `42501`。形状失败的返回不算 route 的成功证明。不建持久登录角色。测完 `RESET ROLE`。
- `spawn_subsession.enabled` 在安装前、安装后、行为测试后都是 true，该行其余列不变。

`main` 开头先跑不碰数据库的静态断言（`r0_source_scope`、`actl_driver_untouched`、AST、常数 grep），再创建库。`r0_source_scope` 会调用放行检查，因此跑本 gate 之前四个新路径以及改过的 `load.py`、`test_plan_arm.py` 必须已经 `git add`。

行为顺序：安装比较 → 形状 / missing / 丢弃 / 配额 SAVEPOINT → `goal_stop` 拒绝 → human pending → 成功剧本 → 第 5 次上界。配额 SAVEPOINT 必须在成功剧本之前结束并回滚。

### 3.10 错误、边界、并发

| 情况 | 行为 |
|---|---|
| prefix 返回 NULL | 同一次 `v13_advance` 先走 `v13_triage_steer`。本场景的根没有 `user/message`，回落是 `reject` closeout，不是 `low_intent_confidence`。子会话才会落到 `v13_route`。成功断言把 human、终态和 `low_intent_confidence` 都钉成失败。不准改 triage、route、advance 或 `_snap_with` |
| 第 1 步前 todo 不是 `runnable` | `v13_selected_todo` 不给 `provider`，prefix `:292-294` 返回 NULL，同一次 advance 进路由。`plan_writer` 之后立刻断言折叠是 `runnable`，再 advance |
| llm `text` 空白或 tool_call 不合格 | `serve` 返回 `blocked`，或 complete 把 llm 标成 `failed` 且不写 `tool/call`。spawn 臂不进入。场景要求 `("served","accepted")` 且第 2 个词是 `progressed`，否则红 |
| 第 2 个词是 `waiting` | 不是 FakeLLM 失败，也不是 prefix llm 臂。停下来看 `:486`（`should_run` 为 false）或 `:489`（`v13_spawn_batch_allowed` 为 false）。不准改 spawn 预算或 spawn 臂 |
| excerpt 空或长度 > 1024 | `_read_once` 合同：在领用 `UPDATE` 之前失败。成功子会话上先用 SAVEPOINT 喂 `""` 和 1025 字符，期望异常且 effect 仍 `ready`、`attempt_no` 不变；回滚后再走合法 excerpt |
| `layers` 未赋值或少一键 | `four_layers()` 抛 `KeyError`，SQL 不执行。`scene_layers_unjoined` 用空 dict 证明。成功剧本在步骤 1 赋值 |
| `admitted=false` 仍调用 `plan_writer` / `advance` / `serve` / `v13_child_pointer` | 检查点函数在 `admitted is not True` 时抛错，后续步骤没有调用。拒绝夹具用零新增 plan/effect 证明 |
| 对子会话 `serve` | `serve` 在 complete 之后还会 advance。读文件已存在时子臂返回 NULL，同一次 advance 进路由。步骤 13 禁止。词序列多一次就不等于四行期望 |
| 归档后再 advance | `scene_advance_cap` 在 SQL 之前失败。真的第 5 次会进路由 |
| 用 `driver.complete` 完成读 | 领用不在该函数里。若先 commit 领用再 complete，complete 失败会留下 `claimed`。场景的领用与五参 complete 共享一个 commit |
| 形状失败被写成 RAISE | 调用方拿不到 `{ok:false,reason:"shape"}`。步骤 1–7 只返回 jsonb |
| 缺会话仍调用两谓词 | 谓词 RAISE `v13: unknown session %`，测试看不到 missing 对象。步骤 8 的调用增量必须是 0 |
| `suggested_should_run` 参加了 AND | `false` 建议在安静会话上会得到 `admitted=false`。丢弃证明要求它仍为 true |
| 宏观调用与下一次 advance 之间 should_run 变化 | 单推进者、单连接。接受这个窗口。不断言「fence 已经咨询 should_run」。不引入 `13002` |
| 重复的宏观调用 | 状态不变时返回相同 jsonb。成功剧本固定 5 次，多一次或少一次都红 |
| 重复 `v13_child_pointer` 且载荷相同 | 活体会返回已有 event_id。场景只调用一次。载荷不同会 `replay_conflict`，场景不构造第二次 |
| `v13_goal_stop` 碰上升级中的 effect | `v13: goal busy`，且不会写下 `goal/stopped`。拒绝夹具必须先保证零行 ready/claimed/unknown |
| human 夹具被写成「清掉 human 就算解决」 | effect 必须保持 `ready`。成功剧本与 human 夹具是两套库状态 |
| 安装中途失败 | `BEGIN/COMMIT` 整笔回滚，库里没有半个函数。测试 `finally` 只 DROP 本进程创建的库 |
| `pg_stat_xact_user_functions` 看不见探针 | 报告环境阻塞，退出非 0。不改断言去迎合 |
| 导入 `test_plan_arm` 跑了 `main` | 停止。不复制 `r1_driver_restore` |
| 41 的 `controller`/1 插入在闭合时挪了位置 | 重读 `$policy$` 块。42 仍只检查 frozen 并引用它 |

连接与事务：场景的写都在 `LoopDriver` 那条连接上，显式 commit。FakeLLM / FakeTool 只在 `TRANSACTION_STATUS_IDLE` 时运行。宏观函数没有自己的事务控制。第 4 次与读完成是两段事务：读的 commit 在前，根上的 `_settlement_advance` 在后。中断（异常）时 `serve` 与 `_complete_read` 的既有 `except` 会 rollback 当前事务；测试让异常冒出，`finally` 仍 DROP 数据库。不在失败路径上 `commit`。

不存在持久化 schema 变更，因此没有迁移、没有旧行转换、没有「旧代码读新列」。已冻结的 `controller` / 1 不 UPDATE。将来若要改宏观函数的行为，用下一次前向提交在更后的 stage 文件里 `CREATE OR REPLACE`，不重写本文件的历史。

### 3.11 被拒绝的替代

父计划 Alternatives 里与 42 有关的五条，加上三条活体更正。都不采用。

| 替代 | 不用的理由 |
|---|---|
| 场景里用 Python 直接调用 steer / answer / cancel | 那是第三条写通道。`v13_llm_tool_calls` 也不接受这些名字。场景不 `v13_parse`，动词不会从模型输出进 `v13_route` |
| 把判断信封塞进 `_snap_with`，或在 `v13_advance` 里加宏观臂 | `driver.py` 与 `v13_plan_arm.sql` 都冻结。prefix 在 `should_run` 为 false 时返回 NULL，同一次 advance 仍会进路由，所以门放在调用方才停得住 |
| 新工作流表、新事件 type、或第八个 `effects.kind` | `plan/committed`、`todo/delta`、effect、`workflow/pointer` 已经盖住这条剧本。活体 kind 已是七值，不是父计划旧文的五值；七值够用 |
| 用 `GoalSupervisor.tick` 当推进者 | tick 不 `serve` llm，也不调用 `plan_writer`。`v13/goal_supervisor/driver.py` 字节被钉住。`SUPERVISOR_MAX_TICKS` 是 2，不能改。human pending 时 tick 只报告 waiting |
| 领用改走 `v13_claim` 或 `pg_advisory_xact_lock(13002, …)` | 那是 I4。`v13_fair_claim.sql` 与 fair driver 字节钉住。本场景的 fence 是按 `effect_id` 精确 `fence+1` 的既有 `UPDATE`，分别在 `serve` 与 `_complete_read` 里 |
| 调用 `RealChain.run` / `_run` | `_run` 会 `plan_prelude`、`plan_admit`，并用 `SPEC` default/2。prelude 与 admit 不是四次返回的条件。spec 必须是 controller/1 |
| 用 `driver.complete` 代替 `_complete_read` | `complete` 只把五参 `v13_complete` 单独 commit，体内没有领用 `UPDATE`。领用与 complete 必须同一事务，然后不再 advance 子会话 |
| 把宏观门塞进 `v13_advance` 新臂 | 要改冻结的 advance。prefix 对 `should_run=false` 的 NULL 不会吃掉后续路由。门保持在调用方的五次只读检查点 |

也不把四层收成一个新运行时，不建第二推进者，不把 stage 42 的 Fake 剧本说成 LoopX `build_quota_should_run` 或 outcome_floor 已经生效。

### 3.12 取舍

| 选择 | 另一头 | 理由 |
|---|---|---|
| 评估对象六键，形状/missing 保持父合同三键 | 三种都加 `schema_version` | 父合同把失败对象写成了没有 `schema_version` 的字面量。评估对象父合同只描述了字段，补 `schema_version` 是为了和观察函数的成功对象一样可版本化 |
| 布尔键名 `should_run`、`quota_eligible`，门文本键名 `gate` | 用函数全名当键，或省略 `gate` 只留 `admitted` | 全名键更长且没有既有调用方。省略 `gate` 就无法区分 `goal_stopped` 与 `human_pending` 与 `quota_window` |
| 场景导入纯函数，手写 canonical / pointer / complete 的 SQL | 实例化 `RealChain` 再调用方法 | 实例方法挂在会跑 `_run` 的类上。SQL 形状在 §3.4 写死，避免实现者另发明 canonical |
| 第 2 次的词用实例包装器截获 | 改 `serve` 让它返回 advance 词 | `driver.py` 不能改。`serve` 今天丢弃这个词 |
| 第 4 次直接 `_settlement_advance` | 再 `serve` 或 `driver.advance` | `serve` 在没有 ready effect 时不 advance。`driver.advance` 把 snap 与 advance 分成两次 commit，不是 `_settle_root` |
| 配额 `allowed=0` 只活在回滚的 SAVEPOINT | 把产品 `quota_window` 改成 0，或插入一百万条 `turn/material_spent` | 种子 `allowed=1000000`。改活动政策会污染同库的成功剧本。material 行还有来源守卫 |
| 宏观函数不查 controller 政策 | 非 controller 会话返回形状失败 | 父合同的接纳位只有两个谓词。controller/1 是开会话约束 |
| 合成负例前移到 `external_exec`/43 | 删掉 `goal_workflow` 负例 | 42 自己的路径一旦合法，旧负例会打红放行，或不再证明「未来 stage 仍被拒绝」 |

---

## 4. File-by-file impact

本计划文件不进实现提交。实现提交的闭集是下面八个文件。stage 43 及以后的路径不进这次提交。

| 文件 | 变更 | 原因与依赖 |
|---|---|---|
| `v13/goal_workflow/v13_goal_workflow.sql` | 新增。一个函数、`REVOKE`、`GRANT`、函数体外 `COMMENT`。无 tools 行、无政策、无 `CREATE OR REPLACE` | W2。依赖累计 stage 41 已提供 `v13_should_run`、`v13_quota_eligible`、`v13_json_keys`、`v13_canonical_uuid`、`v13_route` |
| `v13/goal_workflow/setup_db.py` | 新增。库名 `ll_goal_workflow_*`，`load_stage(..., "agentctl_verbs")`，不应用本 SQL | W3。沿 verbs 的 setup，不调用会 DROP 固定库的旧 `prepare()` |
| `v13/goal_workflow/test_goal_workflow.py` | 新增。安装比较、§3.6 三夹具、§3.4 剧本、§3.7 十条断言。模块 docstring 含声称句 | W4。依赖 SQL、setup、`chain.py` 的纯函数、`r1_driver_restore`、改过的闭集。跑之前路径必须已跟踪 |
| `v13/goal_workflow/README.md` | 新增。声称句原文、签名、三种返回、五次检查点、四次 advance 的词、非目标、两条 gate 命令。实跑记录留到 W5 | 首轮 gate 前必须被跟踪，否则 `stage 42 path is not tracked`。成功结论依赖 W4 |
| `v13/load.py` | 仅两个容器尾部各一行：`goal_workflow` / 42 | W1。与新目录同笔。不改 `files_through` |
| `v13/plan_arm/test_plan_arm.py` | 仅 `r1_load_append_ok` 与 `r1_phase_d_prefix_allowance` 的函数体：四项 approved、stage42 四路径、负例前移到 `external_exec`/43 | W1。`r0_source_scope` 与 `r1_driver_restore` 不动 |
| `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` | 仅 W5。新开 `## Stage 42`，追加一行。行号 = 当时最大号 + 1。不写 Stage 41 行 | 两条 gate 都退出 0 之后 |
| `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` | 仅 W5。新开 `## Stage 42`。不改 F22，不改 S40-1 / S40-D2，不改 S41-D3，不补写「取代 R11」 | 同 W5 |

**明确不改：**

`v13/loop/advance.sql`、`v13/plan_arm/v13_plan_arm.sql`、`v13/loop_driver/driver.py`、`v13/goal_supervisor/driver.py`、`v13/goal_supervisor/accept_unattended.py`、`v13/fair_claim/v13_fair_claim.sql`、`v13/fair_driver/driver.py`、`v13/spawn/v13_spawn.sql`、`v13/envelope/v13_envelope.sql`、`v13/acl/v13_acl.sql`、`v13/real_chain/v13_real_chain.sql`、`v13/real_chain/chain.py`、`v13/workflow_bind/v13_workflow_bind.sql`、`v13/govern/v13_govern.sql`、`v13/quota_window/v13_quota_window.sql`、`v13/should_run/v13_should_run.sql`、`v13/control/v13_control.sql`、`v13/catalog/v13_catalog.sql`、`v13/mgraph/v13_mgraph.sql`、`v13/schema/v13_core.sql`、`v13/agentctl/**`、`v13/agentctl_verbs/**`、stage 1–16 的全部文件、parity 文档、设计稿、裁决记录。`ALLOWED_CONTROL_SQL` 不增加名字。`SUPERVISOR_MAX_TICKS` 不改。

README 在 W4 就写清：声称句；函数不是 tools 行；三种 JSON；`suggested_should_run` 丢弃；缺会话不调用两谓词；成功剧本的推进者只有一个 `LoopDriver`；第 2 次是 `serve` 内部的 spawn 臂 `progressed`；子读是事务外 FakeTool 加同一事务的领用与五参 complete；第 4 次是 `_settlement_advance` 后 `waiting`；human pending 是停住不是解决；`actl_driver_demoted` 延期；不调用四个动词；不交付 43–45；两条 gate 命令。W4 的 README 不写「实跑通过」。

矩阵行（W5，列与第 86 行相同）：

- 条文含声称句原文，并点明生产新增只有 `v13_macro_suggestion`。
- 状态 ✅ 只在两条命令都退出 0 之后填写。W5 之前不写这一行，避免文档先绿。
- 测试落点写实际命令与 `check` 计数。
- 缺口写：不证明无人值守、真实 provider、LoopX quota / outcome_floor / writeback、wake、CE 进程控制。不实现 stage 43–45。不实现 `actl_driver_demoted`。不调用四个 agentctl 动词。不闭合 D-3。不新增 `effects.kind`。

台账至少三行：

- 交付边界：只新增 STABLE INVOKER 函数；场景是 Fake 四次 advance；`controller`/1 只消费不重定义；`driver.py` 哨兵外字节未改。
- 建议布尔丢弃；`admitted` 由两个谓词重算；缺会话不调用谓词；函数零写。
- human pending 的停止不是任务解决。stage 45 不交付。`read_file_py` 是 subject 读取，不是控制文件，也不是 file sink。

---

## 5. Risks

| 风险 | 处置与停止条件 |
|---|---|
| 生产者提交不在 HEAD 上就开始写 42，或把 41 和 42 一次提交，或空等 D-3 闭合 | 本修订时该提交已在 `main`，哈希 `95af56b`。W0 不满足就停止。`git status` 里若 41 仍是 staged，不准 `git add` 42。正文消费未闭合不阻止开工，也不在本 stage 修。不发明消费者。W0 已满足仍不授权创建 `v13/goal_workflow/` |
| 开工时 `controller`/1 的插入或 load 尾与本文行号不一致 | 以函数名和 `policy_name='controller'` 重读。消费合同不变。不在 42 里重插政策 |
| 照抄 `RealChain.SPEC`，会话开在 default/2 | spec 字面量只有 controller/1。测试读回 `route_policy_name/version` |
| 把 spawn 臂写成 prefix 的返回，第 2 次去等 `waiting` | 第 2 个词必须是 `progressed`（`:508`）。`:486` / `:489` 的 `waiting` 是停下来报告的失败，不是期望词 |
| prefix NULL 之后用改 `_snap_with` 或改 `v13_route` 来消 human | 停止。human 计数为 0 是成功条件，修运行时是越界 |
| todo 还没 `runnable` 就 advance，或 llm 文本为空仍当成功 | 步骤 6、10 的断言先红。不准改 `v13_selected_todo` |
| 对子会话 `serve`，或归档后再真的 advance 第五次 | 词序列不等，或 `scene_advance_cap` 发现事件增加。第五次必须在 `execute` 之前抛错 |
| 用 `driver.complete` 完成读，领用已经 commit | 读完成只允许一段事务。SAVEPOINT 里的空 excerpt 必须仍是 `ready` |
| `layers` 忘了赋值，把 `KeyError` 当成数据库故障去改 SQL | `scene_layers_unjoined` 把空 dict 的 `KeyError` 钉成预期 |
| 形状失败 RAISE，或 missing 路径叫了会 RAISE 的谓词 | 返回对象不相等，或调用增量非 0 |
| `suggested_should_run` 被 AND 进去 | 丢弃证明：false 仍 `admitted=true` |
| 为了证明配额，把活动 `quota_window` 留在 `allowed=0` | SAVEPOINT 必须回滚。成功剧本前复验 version 1 仍 active |
| 新函数留着 PUBLIC，或插了 tools 行 | 安装比较：PUBLIC 无 EXECUTE；`tools` 与 revision 不变 |
| 断言 `effects.kind` 仍是五值，或给 CHECK 加第八值 | 活体是七值（`v13_mgraph.sql:2688-2692`）。只断言本剧本用到 `llm` 与 `tool` |
| 放行写成整个 `v13/`，或删掉负例 | 精确四路径。`external_exec`/43 与 `extra.py` 仍拒绝 |
| `replace` 无 count，误伤 `v13_agentctl_verbs.sql` 或打出第二份 42 行 | `count=1`。未来负例从 `goal_workflow` 行往后插 43 |
| 改了 `r0_source_scope` 或模块级 AST | `changed existing test` / `changed module setup` 出现时撤回，不放宽例外 |
| 测试失败后 DROP 了别的库 | 唯一名字；`CREATED` 仅在 CREATE 成功后为真；不预先 DROP |
| 文档先写 ✅，或把 human 停住写成无人值守已成立 | W5 整段后置。声称句不准加宽 |
| `git add -A` 卷进本计划、41 的红测试、或 43 的空目录 | 只按 §6 的路径暂存 |
| 导入测试模块触发旧 `main`，或 `pg_stat` 不可用 | 先做导入核对。计数不可用就报告环境阻塞 |
| 两个 Git 基线不可读 | `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 与 `78e77c710bf06a0a1c771b822a3837c5db4c66d0` 必须能 `git cat-file`。缺失则停止，不换成 HEAD |
| 把并发窗口写成「fence 读过 should_run」 | 不写进 README，不引入 advisory lock |

无新表、无事件回填、无 `default` / 2 或 `controller` / 1 的迁移。安装事务失败整笔回滚。已推送之后的修正是下一次前向提交，不 `reset` 本里程碑，不解冻 `controller` / 1。

**已经核对，不再当开放项：**

- `test_plan_arm.py:1731` 是 `if __name__ == "__main__"` 守卫，导入 `r1_driver_restore` 不会跑 `main`。
- `v13_should_run_gate` 在 stopped 且 effect 为 `block`、会话非终态时返回 `goal_stopped`（`v13/govern/v13_govern.sql:438-446`）。
- `v13_last_user_seq` 无 `user/message` 时返回 `-1`（`v13/schema/v13_core.sql:153-156`）。human 夹具不要为了这个函数去补事件。
- 空会话上 `v13_goal_fingerprint` 不因缺少事件而 RAISE。`v13_probe` 把缺事件收成 `max_event_seq=-1`（`v13/manifest/v13_manifest.sql:834-835`）。

**仍只在实现时核对，不构成新产品选择：**

- 行号漂移以函数名为准。空会话上的 `v13_goal_stop` 按 §3.6 跑，不因为「没有事件」而预判失败。

---

## 6. Implementation order and verification

### 6.1 实施顺序

1. **W0，确认施工基线。** HEAD 的提交信息是 `v13: add agentctl steer answer cancel`，且该提交上两条 stage 41 gate 曾退出 0。D-3 正文消费未闭合不阻止开工。不得回改 41 去发明消费者。`v13/load.py` 尾是 `agentctl_verbs: 41`。`controller` / 1 在该提交的 SQL 里被冻结。两个 Git 基线 `git cat-file -e` 成功。`r1_driver_restore` 对当前 `driver.py` 通过。工作区没有要混进本次提交的其他修改。本修订写入时 HEAD 是 `95af56b`，提交信息就是上一句，两条 gate 的退出码 0 记在矩阵第 87 行，故「HEAD 仍是 `a19aefc`」这一停止条件当前不触发。复验时 HEAD 仍是 `a19aefc`、或 41 只在 index 里、或 HEAD 的历史上没有该生产者提交，就停止。满足本条不授权创建 `v13/goal_workflow/`。不改旧 gate 去适配 42。

2. **W1–W3 一起写到可运行。** 四个新文件同时出现。README 含声称句和合同，不含实跑结论。`load.py` 只追加两行。`test_plan_arm.py` 只改两个函数体，含 §3.8 的 needle。SQL 只有 `v13_macro_suggestion`。setup 装到 `agentctl_verbs`。不得单独提交放行。

3. **W4 的全部断言。** 一个 `LoopDriver`，FakeLLM / FakeTool，无 `v13_parse`，无网络。第 5 次 advance 的包装在 SQL 之前失败。`actl_driver_demoted` 不出现。

4. **首次 gate 前按路径暂存。** `plan_arm` 用 `git ls-files`，看不见未跟踪文件。

```bash
git add -- \
  v13/goal_workflow/v13_goal_workflow.sql \
  v13/goal_workflow/setup_db.py \
  v13/goal_workflow/test_goal_workflow.py \
  v13/goal_workflow/README.md \
  v13/load.py \
  v13/plan_arm/test_plan_arm.py
```

禁止 `git add -A`、`git add .`。禁止暂存 `v13/external_exec/`、`v13/agentctl_verbs/` 的新改动、`driver.py`、本计划文件。

5. **顺序执行两条 gate。** 脚本不是 pytest。都要退出码 0。

```bash
UV_FROZEN=1 uv run python v13/goal_workflow/test_goal_workflow.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```

任一非 0 就停止收尾。按失败断言修根因，再暂存同一组路径并重跑。出现 `changed existing test` 或 `changed module setup` 时撤回越界编辑，不改 `r0_source_scope`。禁止把第 5 次改成真的 `v13_advance` 来换退出码。禁止调用 `poison()`。一次性库由 `finally` DROP。

6. **两条都绿之后才做 W5。** README 补实际命令、退出码、`check` 计数。矩阵只追加 Stage 42 一行，行号取当时最大号 + 1，条文含声称句原文，状态才填 ✅。台账只新开 Stage 42。不回填 Stage 41，不改第 86 行，不改 S40-1 / S40-D2，不改 F22。然后：

```bash
git add -- \
  v13/goal_workflow/README.md \
  docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md \
  docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md
```

7. **最终树再跑第 5 步两条命令。** 看 `git diff --check`、暂存路径闭集、以及没有未暂存的 `v13/` 差。不得用文档更新前的退出码代替这一次。

8. **同一次提交。** 仅获准施工的实现者执行：

```bash
git commit -m "v13: accept one fake goal workflow"
git push origin main
```

不使用 `--no-verify`，不 force-push，不改写历史。hook 失败修根因。stage 43、44、45 不在这一笔里。本规划任务不执行该提交。

步骤 4 与 5 必须在同一次待提交树上重复到都绿，不能先推放行、以后再补 SQL。步骤 6 依赖步骤 5 的退出码 0，不能与红的测试同笔。

### 6.2 验收清单

同时成立才算 stage 42 完成：

- 两条指定 gate 在最终文件上退出 0，一次性库已删除。
- 装载尾恰为 `goal_workflow: 42`。1–41 前缀不变。`v13/external_exec/` 仍被合成负例拒绝。
- 生产新增恰一个 STABLE INVOKER 函数。没有新 tools 行、新表、新列、新事件 type、新 `effects.kind`、新政策。`controller` / 1 仍是 41 冻结的那一版。
- 形状与 missing 是 §3.3 的三键对象，且不调用两个谓词。评估对象六键。`suggested_should_run=false` 在安静会话上仍 `admitted=true`。`goal_stop` 之后 `admitted=false` 且函数窗口零写。
- 成功词序列是 `waiting`、`progressed`、`waiting`、`waiting`。折叠 `done`。human 与 `steer/injected` 为 0。第 5 次没有执行 `v13_advance`。
- 子读是事务外 FakeTool，领用与五参 `v13_complete` 同一事务，之后没有子会话 advance。
- `driver.py` 经 `r1_driver_restore` 与 `fb295ac` 一致。场景 AST 没有 `decide`、`decide_exit`、`run_turn`、`tick`、`RealChain`、四个 `v13_agentctl_*`。
- `spawn_subsession.enabled` 仍为 true。`r0_source_scope` 未改。
- 文档只记录 stage 42 的实跑。声称句没有被加宽成「人可以离开生产终端」。

**交付结论只能是：单 goal、Fake、上界 4 的第一份绿场景，以及一个零写的宏观建议函数，已经在一个 `LoopDriver` 上验证。不能据此声称无人值守、真实 provider、stage 43–45、CE 进程控制、wake、LoopX quota / outcome_floor / writeback 或 D-3 已经交付。**

## References

- 父合同：`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md`（stage 42、第一份绿场景、断言表、PR Plan 第 3 项）
- 对照写法：`docs/plans/v13-stage41-agentctl-verbs-2026-10-08.md`、`docs/plans/v13-stage40-agentctl-observe-2026-10-08.md`
- 权威顺序：`docs/plans/v13-long-loop-plan-2026-09-28.md` §2 > 父计划 T0–T7 > `docs/reviews/v13-agentctl-da-rulings-2026-10-03.md`
- 矩阵第 86 行：`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md:108-112`
- 台账 S40-1 / S40-D2：`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md:155-162`
- 装载：`v13/load.py:57-58`、`:100-102`、`:106-108`
- 放行：`v13/plan_arm/test_plan_arm.py` 的 `r1_driver_restore`（`:275`）、`r1_load_append_ok`（`:327`，approved `:407-416`）、`r1_phase_d_prefix_allowance`（`:425`，goal_workflow 负例 `:718-745`）、`r0_source_scope`（`:746`）
- 臂：`v13/plan_arm/v13_plan_arm.sql` 子臂 `:144-161`、归档 `:183-205`、门与未选中 `:289-294`、提前 waiting `:404-466`、spawn `:467-508`、prefix 调用 `:510`；`v13/loop/advance.sql:134-135`、`:169-182`
- 驱动器与链：`v13/loop_driver/driver.py` 的 `ALLOWED_CONTROL_SQL`、`submit_override`、`complete`、`plan_commit_entry`、`plan_writer`、`serve`、`_settlement_advance`、`_snap_with`、`four_layers`；`v13/real_chain/chain.py:21-22`、`:32`、`:53`、`:110-152`、`:182-207`、`:242-310`
- 宏观谓词：`v13/govern/v13_govern.sql:237-286`、`:348-359`、`:373-376`、`:407-411`；`v13/should_run/v13_should_run.sql:195-203`；`v13/quota_window/v13_quota_window.sql:53` 与未知会话 RAISE；`v13/control/v13_control.sql:121-128`、`:902`
- ACL 与反例：`v13/agentctl/v13_agentctl.sql` 的 REVOKE/GRANT；`v13/schema/v13_core.sql:911-935`；`v13/acl/v13_acl.sql:401-407`、`:423-427`、`:459-470`
- kind 七值：`v13/mgraph/v13_mgraph.sql:2688-2692`
- 政策插入（只消费，不重写）：`v13/agentctl_verbs/v13_agentctl_verbs.sql` 的 `$policy$` 块（约 `:399-421`）
- 夹具先例：`v13/agentctl/test_agentctl.py:53-56`、`:183-207`、`:631-655`；`v13/real_chain/test_real_chain.py:75-115`、`:392-399`；`v13/loop_driver/test_loop_driver.py:220-238`；`v13/goal_supervisor/test_goal_supervisor.py:1060-1145`；`v13/agentctl_verbs/setup_db.py`
