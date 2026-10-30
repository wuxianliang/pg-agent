# v13 Stage 43：external_exec 开发计划

## 1. Summary

在 stage 42 已进入 `main`（HEAD `5f65d7a`，`v13: accept one fake goal workflow`）且矩阵第 88 行两条 gate 退出 0 之后，追加 stage 43 `external_exec`：同一份新 SQL 里插入 `v13_policies` 行 `external_executor` version 1，并安装 STABLE、SECURITY INVOKER 函数 `public.v13_external_exec_classify(p_sid uuid, p_spec jsonb)`。函数只按 Oracle 终裁的七步顺序分类；允许列表只来自那一次读到的 active `verbs`；真正执行仍是 stage 41 已有的 parse → advance sql 臂，且本 stage 只对 `agentctl_steer` 做这条证明。这是纯尾追加：不改 `v13_advance`、`driver.py`、信封、stage 1–42 的 SQL。

**本文是实施规格，不是执行报告。** 本规划任务不写生产代码、不跑 gate、不暂存、不提交。下文命令只给以后获准施工的实现者。开工条件是 HEAD 的历史上含 `5f65d7a` 且该树上两条 stage 42 gate 已退出 0。满足该条件也不授权创建 `v13/external_exec/`；本规划任务不授权创建该目录。行号以函数名为锚；漂移不换实现路径。

**声称句（README 首段正文、测试模块 docstring 第一段、矩阵第 89 行条文使用这一句，字符级原样，不准加宽）：**

> 夹具绑定的现存 `p_sid`、`external_executor` version 1、STABLE INVOKER 函数 `v13_external_exec_classify`：允许动词返回七键且 `executed=false`；`source_principal`、未知键、列表外动词、空会话或不存在会话返回两键 `unsupported` 且零写。真正执行仍是既有 parse → advance 的 sql 臂，快照仍是 `controller` / 1。这不是可信产品入口，不是注册身份，不是 task lease。

### 范围边界

- 新目录只有四个文件：`v13/external_exec/v13_external_exec.sql`、`setup_db.py`、`test_external_exec.py`、`README.md`。SQL 文件名已被 `r1_phase_d_prefix_allowance` 的合成负例钉住，不得改名。
- `v13/load.py` 只在 `SQL_LOAD_ORDER` 与 `STAGE_THROUGH` 两个容器的最后一个元素之后各追加一项：`external_exec` / 43。不改 `files_through`、`run_psql`、`load_stage`。
- `v13/plan_arm/test_plan_arm.py` 只改 `r1_load_append_ok` 与 `r1_phase_d_prefix_allowance` 两个函数体。`r0_source_scope`、`r1_driver_restore`、`r1_freeze_positive_proof`、模块级 import 与常量不动。
- 新 SQL 只有：`v13_external_exec_classify`、一条 `external_executor` version 1 的 `INSERT`、`REVOKE`、`GRANT`、函数体外 `COMMENT`。不 `INSERT` `tools`，不 `CREATE OR REPLACE` 任何既有函数，不插入 route policy，不写 `controller_surface`。
- 函数体不出现四个工具名。成员资格只用当次 `SELECT value, version FROM v13_policies WHERE name = 'external_executor' AND active` 读到的 `verbs`。不调用 `v13_policy()`，因为该函数不返回 version。
- 不把 `external_executor` 写入 `v13_parse` 快照的 `route_policy_name` / `route_policy_version`。执行证明只断言这两个字段仍是 `controller` / `1`。
- 不调用 `v13_agentctl_observe`、`v13_agentctl_steer`、`v13_agentctl_answer`、`v13_agentctl_cancel`、`v13_parse`、`v13_advance`、`v13_route`、`v13_append_event`、`v13_control_authorized`。测试进程里的执行证明会执行既有 `v13_parse` / `v13_advance` SQL，那是 sql 臂证明，不是分类函数的调用图。
- 不重放 stage 41 四动词成功语义，不断言 `write_targets`，不 import `v13.agentctl_verbs.test_agentctl_verbs`。
- 不改信封，不增身份字段、表、列、事件 type、`effects.kind`、route action。不实现 `quota_registered_agents`、可信 bind、task lease、`claimedProcessID`、五表 authority store。不向 42/44/45 授予身份。
- 不读写控制文件、projection、receipt、外部身份缓存。仓库源文件不是运行时控制文件。
- 不消费 stage 42 的场景能力：不调用 `v13_macro_suggestion`，不跑四次 advance 剧本，不构造 `LoopDriver` 来推 goal。
- I1–I4、D-6、D-9、E2 worktree 握手、stage 44 的映射语义、stage 45 的非交付：本 stage 不回答、不实现。父计划 Open Questions 保持开放。

## 2. Current-state analysis

### 2.1 施工前置与 HEAD `5f65d7a`

开工门在本规格写入时已经满足，但本文件不授权施工。

- HEAD 是 `5f65d7a`，提交信息 `v13: accept one fake goal workflow`，在 `main` 上。生产装载停在 42（`goal_workflow`）。
- 矩阵第 88 行状态 ✅：`UV_FROZEN=1 uv run python v13/goal_workflow/test_goal_workflow.py` 退出码 0（460 checks），`UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py` 退出码 0（104 checks）。
- `v13/external_exec/` 不存在。`v13_external_exec_classify` 全库零定义。
- 42 的八个交付文件已在该提交里。43 不得回改 `v13/goal_workflow/**`、不得把 42 的未提交差和 43 打进同一次提交。
- 实现者开工前复验：HEAD 历史上能找到 `5f65d7a`，`v13/load.py` 尾仍是 `goal_workflow: 42`，工作区没有要混进本次提交的其他已暂存差。复验失败则停止。看到该状态也不创建目录，直到施工被另行批准。
- D-3 正文消费仍未闭合（台账 S41-D3）。那不是本 stage 的前置，也不在本 stage 修。不写「D-3 已闭合」。

### 2.2 装载尾

`v13/load.py` 的 `SQL_LOAD_ORDER` 最后一项是 `V13_ROOT / "goal_workflow" / "v13_goal_workflow.sql"`（`:59`；尾部三项在 `:57-59`）。`STAGE_THROUGH` 最后一项是 `"goal_workflow": 42`（`:104`；尾部三键在 `:102-104`）。`files_through` 用 `STAGE_THROUGH[stage]` 截 `SQL_LOAD_ORDER[:n]`（`:108-110`）。新 stage 必须同时追加到两个容器的尾部，键、目录名、SQL 文件中段三者一致，编号是 43。不能跳过 40、41、42。

43 的 `setup_db.py` 调用 `load_stage(..., "goal_workflow")`，装到 42 为止。本 stage SQL 由测试在安装快照之后单独 `run_psql`，与 `v13/goal_workflow/setup_db.py` 把 SQL 留在 gate 里的做法相同。setup 不装自己的 SQL。

### 2.3 `plan_arm` 今天如何拒绝 43

`r1_load_append_ok`（定义自 `:327`）的 `approved` 恰为四项（`:407-417`）：`fair_claim/39`、`agentctl/40`、`agentctl_verbs/41`、`goal_workflow/42`。失败文案是下面这一句，在文件里出现 4 次，行号锚是 `:417`、`:713`、`:754`、`:778`：

```text
append is not fair_claim/39 then agentctl/40 then agentctl_verbs/41 then goal_workflow/42
```

四处分别是：

| 锚 | 构造 | 43 合法之后必须变成 |
|---|---|---|
| `:417` | `approved` 与 `got` 不等时的 assert 消息 | 五项文案（见 §3.9） |
| `:713` | `replace("v13_agentctl.sql", "v13_agentctl_extra.sql", 1)` | 同一构造，needle 改五项文案 |
| `:754` | 在 `goal_workflow` 行后追加 `external_exec` / `v13_external_exec.sql` / 43 | 这个构造会变成合法尾。前移到 `ce_map` / `v13_ce_map.sql` / 44 |
| `:778` | `replace("v13_goal_workflow.sql", "v13_goal_workflow_extra.sql", 1)` | 同一构造，needle 改五项文案 |

检查顺序保持，不准重排：纯尾、路径唯一、键唯一、编号唯一、连续编号、目录键对齐、plus 行对应、最后才是 approved 元组。`order_names` 仍是 `workspace_admit`、`frontier_gap`、`goal_supervise`、`fair_claim`。

`r1_phase_d_prefix_allowance`（定义自 `:425`）的 `allow()`（`:504-516`）只放行三个前缀 `v13/goal_supervisor/`、`v13/fair_claim/`、`v13/fair_driver/`，或 `stage40` / `stage41` / `stage42` 各四路径。没有目录前缀放行。`prefixes` 元组不准加入 `v13/external_exec/`。

今天仍被拒绝、43 必须前移的两处：

- `:724-730`：`extra | {"v13/external_exec/test_external_exec.py"}`，needle `outside the three prefixes`。路径一旦进入 stage43 闭集就不再拒绝。
- `:745-750`：`future` 在 `goal_workflow` 行后插入 `external_exec` / 43，tracked 并上 `v13/external_exec/v13_external_exec.sql`，needle 是四项文案。

紧挨 `:778` 之前还有一条活体负例：把 `"goal_workflow": 42` 换成 `"goal_workflow": 43`，needle 是 `stage number is not the next contiguous value`。43 成为合法编号之后，这条会先撞上 `duplicate stage number`（编号唯一先于连续编号）。这与台账 S42-4 把 `"agentctl_verbs": 42` 改成 44 是同一类活体修正。处置见 §3.9，不改检查顺序。

`r0_source_scope`（`:781`）一字不改。`r1_load_append_ok` 与 `r1_phase_d_prefix_allowance` 在 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 里不存在，所以只改这两个函数体不会触发 `changed existing test`。模块级语句、import、常量一旦变化，会触发 `changed module setup`。出现这两种文案就撤回越界编辑。

### 2.4 政策、ACL、`controller_surface`

`v13_policies`（`v13/schema/v13_core.sql:701-741`）：主键 `(name, version)`；部分唯一索引 `ux_v13_policies_one_active` 保证每个 name 至多一行 `active`。触发器 `trg_policies_frozen` / `v13_policies_frozen` 拒绝 DELETE，拒绝改 `name` / `version` / `value`，只允许翻 `active`。触发文案是 `v13: policy rows are immutable (append new version + flip active)`。DELETE 文案是 `v13: policy rows are append-only (no DELETE)`。写错的 value 用下一 version，不 `UPDATE` value。

`v13_policy(text)`（`:731-741`）是 STABLE，无 active 行时 `RAISE EXCEPTION 'v13: no active policy row for % (seed lost?)'`。它只返回 `value`，不返回 `version`。分类函数不调用它；无行 RAISE 的文案按 `external_executor` 写成同一句的字面量。

`controller_surface` version 1 插在 `v13/agentctl_verbs/v13_agentctl_verbs.sql:498-512`，键是 `schema_version`、`route_policy_name`、`route_policy_version`、`tools`，工具顺序是 `agentctl_observe`、`agentctl_steer`、`agentctl_answer`、`agentctl_cancel`。43 的政策行不得复制 `route_policy_name`、`route_policy_version`、`tools` 这三个键。动词数组的顺序与这份 `tools` 数组相同，但键名是 `verbs`。

`controller` version 1 在同文件 `$policy$` 块（`:384-496`）插入并 `state = frozen`。`trg_sessions_policy_guard`（`v13_core.sql:540-565`）要求 sessions 引用的 route policy 已冻结。执行证明开会话因此用 `{"route_policy_name":"controller","version":1}`。`external_executor` 不是 route policy，不插入 `v13_route_policies`。

ACL 先例是 `v13/goal_workflow/v13_goal_workflow.sql:5-9` 与 `:93-94`：`LANGUAGE plpgsql`、`STABLE`、不写 `SECURITY DEFINER`、`SET search_path = pg_catalog, public`、不 `STRICT`、不 `ALTER OWNER`、`REVOKE EXECUTE ... FROM PUBLIC`、`GRANT EXECUTE ... TO v13_route`。不授 `v13_recall`、`v13_worker`、`v13_resolve`、`v13_spawn_owner`。分类函数不是 `tools` 行，目录守卫不会检查它。不要为了「看起来像工具」插一行 tools：那会拨 `v13_tools_meta` 的 revision。

键比较复用既有读者，不新写助手：

- `v13_json_keys`（`v13/control/v13_control.sql:102-105`）按键名排序返回 `text[]`。`schema_version` 排在 `verb` 前，也排在 `verbs` 前。
- `v13_json_int_ok(p, 1)`（`:107-112`）要求 jsonb 类型是 number、文本匹配 `^[0-9]+$`、数值在 0 与 1 之间。它接受 0 和 1。再要求文本恰为 `'1'`，两者合取才是整数 1。jsonb 会把 `1.0` 规范成 `1`；沿用这个既有读者，不另写拒绝 `1.0` 的助手。

D-A.1（`docs/reviews/v13-agentctl-da-rulings-2026-10-03.md:21`）的「政策版本入 request 快照」不得通过改信封实现。`policy_version` 只出现在分类成功返回值，值是当次读到的行 `version`。

### 2.5 sql 臂与 S2 序言

`v13_route` 在意图、工具、目录 kind 都命中时，对 `kind = 'sql'` 返回 `action=sql`、`reason=in_db_handler`、`tool`、`params`（`v13/loop/advance.sql`，`RETURN jsonb_build_object('action','sql',...)`，核实位置 `:151-153`；函数自 `:110`）。`v13_resolve_tool_params` 紧随其后：某 param 只有 `stated::<tool>::<key>` 命中 pass 带才抄 `param::<tool>::<key>` 的 choice。

`v13_advance` 的活体在 `v13/plan_arm/v13_plan_arm.sql`。prefix 与 triage 都返回 NULL 之后才调用 `v13_route`，随后 `PERFORM v13_append_event(..., 'turn/route', v_route)`，再 `CASE v_route->>'action' WHEN 'sql'`（`turn/route` 写入在 `:770`，`WHEN 'sql'` 在 `:772`，该臂 `RETURN 'progressed'` 在 `:813`）。sql 臂从信封 `tools_catalog` 里取 `kind=sql` 且 enabled 的 handler，动态 `EXECUTE` 该 handler，插入一条 `effects` 行，无异常时再写 `tool/result`，`RETURN 'progressed'`。43 不改这两份文件。执行证明只断言 advance 的词是 `progressed`、最新 `turn/route` 的 `action=sql` 且 `tool=agentctl_steer`。不断言 effect 行、`tool/result`、`write_targets`。

S2 序言在 `prepare_chain`（`v13/agentctl_verbs/test_agentctl_verbs.py:1262-1313`），成功链在 `actl_chain_full` 里把它接到 advance（`:1336-1370`）：

1. `v13_open_session`，spec 为 `controller` / 1。
2. 非空 `user/message`。
3. `v13_spawn_subsession` 一个子会话。`v13_spawn_subsession` 要求父会话 `next_seq >= 1`，所以用户消息必须在 spawn 之前。
4. 根上 `status IN ('ready','claimed')` 的 effect 计数为 0。不为 0 时 `v13_advance` 在进路由之前就 `RETURN 'waiting'`。
5. `v13_submit_override`，载荷键是 `schema_version` 数字 1、`intent=direct`、`reason=""`、`source_principal=operator`。
6. `shrink_catalog`：`kind IN ('sql','tool')` 且 enabled、名字不在 `["spawn_subsession", "agentctl_steer"]` 的行 `enabled=false`。
7. stated noul `0.9`，`param::` choice。`gate_action` noul `0.9`，`gate_off_topic` noul `0.1`，`risk` score `0.5` confidence `0.9`，`intent` choice `sql_answer`，`tool` choice `agentctl_steer`。
8. `v13_parse` 后 `remaining=0`，`failed` 与 `abandon` 都是 false，`snap.route_policy_name/version` 是 `controller` / `1`。
9. advance 前 `UPDATE sessions SET context_active_revision = v13_context_required(session_id)`（`:1336-1341`）。
10. `v13_advance(root, parsed)`，parsed 是 `v13_parse` 的整个 jsonb，不是只拿 `snap`。
11. 词是 `progressed`。最新 `turn/route` 的 `action=sql` 且 `tool=agentctl_steer`（`:1363-1370`）。

`:1400-1406` 的 `write_targets` 比较不复制。四个动词的 answer/cancel 链不复制。

`agentctl_steer` 的 pass 带在 controller/1 上是 `param::` 与 `stated::` 的 `target` 与 `text`（`v13/agentctl_verbs/v13_agentctl_verbs.sql:411-414`）。同文件 `tools` 插入的 `param_spec` 键恰为 `target` 与 `text`（`:345-357`），kind 是 `sql`，`enabled` 是 true，handler 是 `v13_agentctl_steer`。执行证明按这两个键组 overrides。实现时若活体行已不是这个键集，停止并报告，不准猜额外键，也不准改带。

零调用测量先例：连接上 `SET track_functions = 'all'`（`test_agentctl_verbs.py:162`），事务内用 `pg_stat_xact_user_functions`（`:438-462`）。探针是一次可回滚的 `v13_control_authorized(NULL, NULL)`；看不到增量就报告环境阻塞并失败，不把断言降级。`COMMIT` 清掉事务内计数。`SET` 用会话级，不用 `SET LOCAL`。

`mock_from_needed` 与 `set_mock` 活在 `v13/loop/test_loop.py`。stage 41 从该模块导入它们。stage 42 记下未指定 noul 会被填 `0.1`（该文件约 `:126`）。43 的执行证明导入这两个函数，不复制第二份 mock 构造器。`mock_from_needed(cur, sid, **over)` 在 `v13/loop/test_loop.py:111`，`set_mock(cur, mock)` 在 `:67`。对不上就停止并按活体签名改调用，不改 mock 的判定语义。不调用 `poison()`，不设置 `typesafe.endpoint`。

### 2.6 复用与阻断

| 已有物件 | 43 的用法 |
|---|---|
| `v13_json_keys`、`v13_json_int_ok` | 请求与政策 value 的键序、整数 1 双检 |
| `v13_policies` 与冻结触发器 | 插入 version 1；测试在 SAVEPOINT 里翻 active、插入下一 version，然后 ROLLBACK |
| `v13_open_session` | 分类夹具与执行证明的现存 `p_sid`。分类夹具不需要 `plan_commit_entry` |
| `controller` / 1 与四个工具名 | 只消费。政策 `verbs` 抄名称与 `controller_surface` 的顺序，不抄那一行的其他键 |
| `prepare_chain` 的 SQL 序言 | 在 `test_external_exec.py` 里重写一份，只服务 `agentctl_steer` |
| `mock_from_needed`、`set_mock` | 执行证明导入 |
| `r0_source_scope` | `main` 在建库之前调用。不复制函数体 |
| stage 42 的 `setup_db.py` 形状 | 库名、扩展探针、`CREATED`、装到前一 stage |
| stage 42 的 `read_window` / SAVEPOINT 政策夹具 | 快照列改成终裁点名的四张关系；政策变更必须回滚 |

阻断（不准改这些来修绿）：`v13/loop/advance.sql`、`v13/plan_arm/v13_plan_arm.sql`、`v13/loop_driver/driver.py`、`v13/goal_supervisor/driver.py`、`v13/goal_supervisor/accept_unattended.py`、`v13/fair_claim/v13_fair_claim.sql`、`v13/fair_driver/driver.py`、`v13/spawn/v13_spawn.sql`、`v13/envelope/v13_envelope.sql`、`v13/acl/v13_acl.sql`、`v13/resolve/v13_resolve.sql`、`v13/schema/v13_core.sql`、`v13/control/v13_control.sql`、`v13/agentctl/**`、`v13/agentctl_verbs/**`、`v13/goal_workflow/**`、stage 1–16。`ALLOWED_CONTROL_SQL` 不增加名字。

## 3. Design

### 3.1 执行索引

Size 是相对工作量，不是工期。W1–W4 在同一次待提交树上一起变绿；提交发生在 W5 文档收尾且两条 gate 再跑退出 0 之后。不能先提交放行规则。W0 未满足时 W1 不准开始。满足 W0 不授权创建目录。

| 项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W0 | 确认 42 已在 `main` | HEAD 历史上有 `5f65d7a`；矩阵第 88 行两条 gate 退出 0；装载尾是 `goal_workflow: 42`；`v13/external_exec/` 仍不存在 | 只读 git、`v13/load.py`、矩阵 | §2.1 | S |
| W1 | 追加装载与精确放行 | 尾项恰为 39–43；stage43 四路径在 `allow()` 内且不进 `prefixes`；`ce_map`/44 仍被拒绝；四项文案四处都变成五项 | `v13/load.py`；`test_plan_arm.py` 两个函数体 | W0 | M |
| W2 | 分类函数与政策行 | 签名、七步、两种失败对象、七键成功、两条 RAISE 文案、ACL、函数体零动词名，全部符合 | `v13/external_exec/v13_external_exec.sql` | 累计装到 42；`v13_json_keys` 与 `v13_policies` 已在 | M |
| W3 | 一次性库与安装差 | 库装到 `goal_workflow`；政策行恰好 +1；`tools`、meta、relations、events、effects、`controller`、`controller_surface` 不变 | `setup_db.py`；测试的安装段 | W1、W2 | M |
| W4 | 分类断言、RAISE、一条 sql 臂 | 每个 `ext_` 名字有唯一输入与期望；两条 gate 退出 0 | `test_external_exec.py`；README 合同段（无实跑结论） | W3；四个新路径已跟踪 | L |
| W5 | 绿后文档 | README 有实跑记录；矩阵第 89 行；台账 `## Stage 43`。不回改 40–42 | README；矩阵；台账 | W4 两条 gate 退出 0 | S |
| W6 | 同笔提交 | 最终树重跑两 gate 退出 0；闭集一次提交，信息是父计划 PR 第 4 项 | §4 的八个文件 | W5 | S |

### 3.2 `v13_external_exec_classify`

一个 PostgreSQL 函数，不新增类型、表、辅助函数或服务。文件 `v13/external_exec/v13_external_exec.sql`。调用方只有测试里的直接 `SELECT`。不进入 `ALLOWED_CONTROL_SQL`。不进入 `tools`。`v13_advance` 不调用它。

```text
public.v13_external_exec_classify(p_sid uuid, p_spec jsonb) → jsonb
```

| 属性 | 固定设计 |
|---|---|
| 语言 | `plpgsql`。用独立语句把七步分成顺序，不靠 SQL 布尔短路 |
| 易变性 | `STABLE` |
| 安全 | 默认 `SECURITY INVOKER`。源文件不得出现 `SECURITY DEFINER` |
| NULL | 不声明 `STRICT`。SQL NULL 的 `p_spec` 走步骤 1，返回 jsonb。SQL NULL 的 `p_sid` 在步骤 5 返回 unsupported |
| `search_path` | 恰为 `pg_catalog, public`，写在函数的 `SET` 上 |
| 属主 | 安装者。不 `ALTER OWNER`，不建角色 |
| EXECUTE | `REVOKE` FROM `PUBLIC`；只 `GRANT` TO `v13_route` |
| 执行 | 同步，当前语句内。无 `COMMIT`、无动态 `EXECUTE`、无 `EXCEPTION WHEN` 捕获块 |
| 写入 | 零。函数体无 `INSERT`、`UPDATE`、`DELETE`。不调用写函数 |
| 读 | 步骤 5 一次 `sessions` 存在性查询。步骤 6 入口一次政策查询。更早的返回不执行这两次查询 |

选择 plpgsql 的理由：步骤 1–5 必须在读政策之前返回，SQL `AND` 不保证调用顺序，而无 active 行必须在步骤 6 才 RAISE。

函数体 `$fn$` 内，包括注释，不得出现四个工具名 `agentctl_observe`、`agentctl_steer`、`agentctl_answer`、`agentctl_cancel`，也不得出现 `btrim`。允许列表只来自当次读到的数组，动词比较不裁剪空白、不改大小写。

限定名：`public.v13_json_keys`、`public.v13_json_int_ok`、`public.sessions`、`public.v13_policies`。

安装事务的语句顺序固定：`BEGIN`；`CREATE FUNCTION`；`INSERT` 政策行；`REVOKE`；`GRANT`；`COMMENT`；`COMMIT`。函数或政策行已存在则整笔回滚，不做 upsert，不做 `CREATE OR REPLACE`。

`COMMENT` 写在函数体外，英文，固定大意：STABLE read; classifies one verb against the active external_executor row; does not execute; success carries executed false and the row version; not a tools row; does not raise on shape or unsupported. 注释里不写四个工具名，不写 `v13_agentctl_`。

数据流：测试 `SELECT` → 函数内顺序判断 → 要么返回两键 jsonb，要么在步骤 6 RAISE，要么返回七键 jsonb。没有监听者，没有通知，没有第二份缓存。重复调用在政策行不变时返回同一 jsonb。调用被丢弃则没有副作用。单连接串行测试不把「读与翻 active 之间的并发窗口」写成产品承诺；函数不加锁。

### 3.3 判定顺序与精确 jsonb

命中即返回。失败对象只有 `ok` 与 `reason` 两键。不 RAISE 于 shape 或 unsupported。成功对象恰好七键。`policy_version` 只出现在成功对象里。比较用解析后的 jsonb 相等，不比较文本键序。

| 步 | 条件 | 结果 | 是否读 `sessions` | 是否读政策 |
|---|---|---|---|---|
| 1 | `p_spec` 是 SQL NULL，或 `jsonb_typeof` 不是 `object` | `{"ok":false,"reason":"shape"}` | 否 | 否 |
| 2 | 对象含键 `source_principal`（值为 null 也算有键） | `{"ok":false,"reason":"unsupported"}` | 否 | 否 |
| 3 | 存在除 `schema_version` 与 `verb` 以外的键 | `{"ok":false,"reason":"unsupported"}` | 否 | 否 |
| 4 | `v13_json_keys` 不是恰好 `ARRAY['schema_version','verb']`，或 `schema_version` 未同时通过 `v13_json_int_ok(..., 1)` 与文本 `'1'`，或 `verb` 的 `jsonb_typeof` 不是 `string` | `{"ok":false,"reason":"shape"}` | 否。此步结束前不查 | 否 |
| 5 | `p_sid` 是 SQL NULL，或 `sessions` 无 `session_id = p_sid` | `{"ok":false,"reason":"unsupported"}` | 只做存在性 | 否 |
| 6 | 读政策。无行，或 value 非法：RAISE。`verb` 不在 `verbs`：unsupported | 见下文 | 已在步骤 5 做过 | 恰好一次 |
| 7 | 否则 | 七键成功 | 已做过 | 已做过 |

步骤 3 与步骤 4 不准并成「键集不是那两键就 shape」。多出来的键是 unsupported；缺键才落到步骤 4 变成 shape。`source_principal` 必须在步骤 2 返回，因此它和坏 `schema_version` 同时出现时仍是 unsupported，不是 shape。这是终裁顺序，不是实现者可调的优先级。

步骤 4 的整数双检：

```text
public.v13_json_int_ok(p_spec->'schema_version', 1) IS TRUE
AND (p_spec->>'schema_version') IS NOT DISTINCT FROM '1'
```

两臂都要。只写 `v13_json_int_ok` 会把数字 0 放进后续步骤。文本 `'1'` 单独成立不够，字符串 `"1"` 必须在这一步 shape。

步骤 5 的存在性查询：

```text
p_sid IS NULL
OR NOT EXISTS (
  SELECT 1 FROM public.sessions WHERE session_id = p_sid)
```

不调用 `v13_control_authorized`。不读 `route_policy_name`、`route_policy_version`、`status`。子会话与根会话一样只看行在不在。`WHERE session_id = NULL` 不会命中；NULL `p_sid` 必须在 `EXISTS` 之外用 `IS NULL` 判定，否则会掉进步骤 6。

步骤 6 的唯一读：

```text
SELECT value, version
  INTO v_value, v_version
  FROM public.v13_policies
 WHERE name = 'external_executor'
   AND active;
```

`NOT FOUND` 时：

```text
RAISE EXCEPTION 'v13: no active policy row for external_executor (seed lost?)';
```

找到行之后，下面任一成立就：

```text
RAISE EXCEPTION 'v13: external_executor policy';
```

- `v13_json_keys(v_value)` 不是恰好 `ARRAY['schema_version','verbs']`。
- `schema_version` 未同时通过 `v13_json_int_ok(v_value->'schema_version', 1)` 与文本 `'1'`。
- `verbs` 不是无重复字符串数组。

无重复字符串数组的判定顺序固定，避免先把非字符串 cast 成 text：

1. `jsonb_typeof(v_value->'verbs')` 是 `array`。不是则 RAISE 政策文案。
2. `jsonb_array_elements` 的每个元素 `jsonb_typeof` 都是 `string`。有一个不是则 RAISE。
3. `count(*)` 等于 `count(DISTINCT 元素文本)`。不等则 RAISE。

空数组通过这三步。空数组不是这条 RAISE。随后成员资格失败，返回 unsupported。

成员资格用当次数组，不 `btrim`：

```text
(v_value->'verbs') ? (p_spec->>'verb')
```

`?` 对 jsonb 字符串数组做精确元素匹配。不命中则返回 unsupported，不 RAISE。命中则步骤 7。

步骤 7 用 `jsonb_build_object`，恰好这些键：

| 键 | 值 |
|---|---|
| `schema_version` | jsonb 数字 `1`。这是返回合同的版本，不是政策行的 `version` 列 |
| `ok` | jsonb 布尔 `true` |
| `classified` | jsonb 布尔 `true` |
| `executed` | jsonb 布尔 `false`。`jsonb_typeof` 必须是 `boolean` |
| `verb` | `p_spec->>'verb'`，与入参原样相同 |
| `policy_name` | 文本 `external_executor` |
| `policy_version` | 当次 `SELECT` 得到的 `version` 整数。安装后的成功路径是 `1`。测试用回滚掉的 version 2 证明它不是函数体里的常量 `1` |

`executed` 不是字符串 `"false"`。成功对象不含 `reason`、`verbs`、`source_principal`。

两条失败对象：

```json
{"ok": false, "reason": "shape"}
{"ok": false, "reason": "unsupported"}
```

### 3.4 政策行

同一 SQL 文件、同一事务、单个 `::jsonb` 字面量。不用 `jsonb_build_object`，不用 `||` 拼接。键只有 `schema_version` 与 `verbs`。`active=true`。version 是整数 `1`。

字面量字符级如下（动词顺序与 `controller_surface` 的 `tools` 相同）：

```text
'{"schema_version":1,"verbs":["agentctl_observe","agentctl_steer","agentctl_answer","agentctl_cancel"]}'::jsonb
```

插入目标是 `public.v13_policies (name, version, value, active)`，`name` 为 `external_executor`。这四个名字在整份 SQL 文件里各出现恰好一次，且只出现在这个字面量里。`pg_get_functiondef` 对应的函数体里出现次数为 0。

stage 43 不交付 version 2。version 2 只活在测试的 SAVEPOINT 里，ROLLBACK 之后行数为 0。

### 3.5 安装增量

比较基准是「`load_stage` 到 `goal_workflow`、尚未 `run_psql` 本文件」的快照。然后 `run_psql` 本文件，再比较。

必须成立：

- `public` 下 `proname LIKE 'v13_%'` 或 `proname = 'v_goal_tree'` 的定义、属主、`prosecdef`、`provolatile`、`proconfig`、`proisstrict`：除新函数外逐个相等。
- 新函数恰好一条，身份参数是 `p_sid uuid, p_spec jsonb`。`prosecdef` 为 false，`provolatile` 为 `s`，`proisstrict` 为 false，`proconfig` 去空格后含 `search_path=pg_catalog,public`，属主是 `current_user`。
- `tools` 全表逐列不变。`v13_tools_meta.revision` 与 `candidate_generation_revision` 不变。
- 无新表、新列、新索引、新触发器。`events` 行数不变。`effects` 行数不变。
- `v13_route_policies` 行集不变。`controller` / 1 的 `state` 仍是 `frozen`。
- `controller_surface` / 1 的 `name, version, active, value::text` 与安装前那一行相等。
- `v13_policies` 的行集等于安装前的行集再加恰好一行：`external_executor`、version `1`、`active` true、value 与 §3.4 的 jsonb 相等。这就是「政策行 +1」。不准写成 stage 42 `install_compare` 里的 `policy rows unchanged`（`test_goal_workflow.py` 约 `:600`）。
- `v13_named_sql_writer('v13_external_exec_classify')` 为 NULL。`v13_spawn_writer_ok('v13_external_exec_classify')` 为 false。不给这两个函数加分支。
- `has_function_privilege`：`v13_route` 为真；`public`、`v13_recall`、`v13_worker`、`v13_resolve`、`v13_spawn_owner` 为假。
- `SET ROLE v13_route` 对一条已存在的 controller/1 会话、动词 `agentctl_steer`，返回 §3.3 的七键且 `policy_version=1`。形状失败不算这条证明。`SET ROLE v13_recall` 得到 sqlstate `42501`。测完 `RESET ROLE`。不建持久登录角色。召回角色的失败用 SAVEPOINT 包住，避免事务进入 aborted 后无法 `RESET ROLE`。

`spawn_subsession.enabled` 在安装前后都是 true。执行证明里的 `shrink_catalog` 会改别的工具的 `enabled`，所以「tools 不变」只在安装比较里断言，不在执行证明之后再拿安装前快照来比。

### 3.6 分类夹具与断言名

每个名字是一次 `check()` 的 label，对应表中那一个输入和那一个期望。可以在同一 Python 函数里依次调用，不准把多个输入合成一个没有名字的循环后只留一个 label。凡返回 jsonb 的调用，调用前后四张关系的行级快照相等：`sessions`、`events`、`effects`、`v13_policies`。快照用 `row_to_json(别名)::text`，排序键分别是 `session_id`、`(session_id, seq)`、`effect_id`、`(name, version)`。

下文 `S` 是一条已存在的会话，由 `v13_open_session('{"route_policy_name":"controller","version":1}'::jsonb)` 得到，开在快照窗口之外。`missing` 是 `uuid4()` 且 `sessions` 里没有这行。政策处于安装后的 version 1 active，除非该行写明 SAVEPOINT。

零写窗口只包住那一次 `SELECT v13_external_exec_classify`。不要把 `v13_open_session` 包进窗口。

SQL NULL 与 JSON null 是两种绑定，不准都用 Python `None`。psycopg2 把 `None` 发成 SQL NULL，`cur.execute("SELECT ...(%s::jsonb)", (None,))` 发不出 JSON null。照 `v13/goal_workflow/test_goal_workflow.py:54-55` 与 `:209-220`：`SQL_NULL` 绑成字面量 `NULL::jsonb`（`p_sid` 的 SQL NULL 用 `NULL::uuid`）；`JSON_NULL` 绑成字面量 `'null'::jsonb`。嵌套的 JSON null（`verb` 为 null）可以 `json.dumps`。步骤 1 必须在调用 `v13_json_keys` 之前看 `jsonb_typeof`：`coalesce` 不替换 jsonb null，`jsonb_object_keys` 会拒绝它（`v13/control/v13_control.sql:102-105`）。不新增第三种失败对象。

**步骤 1 与步骤 4，期望两键 `shape`。** 这些调用在政策被关掉时也必须仍返回 shape；那个证明集中在 §3.7 的 `ext_inactive_*`，这里先在政策 active 时钉住返回值。

| label | `p_sid` | `p_spec` | 期望 |
|---|---|---|---|
| `ext_shape_null_spec` | `S` | SQL NULL | shape |
| `ext_shape_json_null` | `S` | JSON null | shape |
| `ext_shape_array` | `S` | `[]` | shape |
| `ext_shape_scalar` | `S` | JSON 字符串 `scalar` | shape |
| `ext_shape_number` | `S` | JSON 数字 `1` | shape |
| `ext_shape_bool` | `S` | JSON `true` | shape |
| `ext_shape_empty` | `S` | `{}` | shape |
| `ext_shape_only_verb` | `missing` | `{"verb":"agentctl_steer"}` | shape。若实现把步骤 5 放到步骤 4 前面，这里会变成 unsupported |
| `ext_shape_only_version` | `S` | `{"schema_version":1}` | shape |
| `ext_shape_version_string` | `S` | `{"schema_version":"1","verb":"agentctl_steer"}` | shape |
| `ext_shape_version_zero` | `S` | `schema_version` 为数字 `0`，`verb` 为 `agentctl_steer` | shape |
| `ext_shape_version_two` | `S` | `schema_version` 为数字 `2`，`verb` 为 `agentctl_steer` | shape |
| `ext_shape_version_fraction` | `S` | `schema_version` 为数字 `1.5`，`verb` 为 `agentctl_steer` | shape |
| `ext_shape_verb_number` | `S` | `schema_version` 数字 `1`，`verb` 数字 `1` | shape |
| `ext_shape_verb_null` | `S` | `schema_version` 数字 `1`，`verb` JSON null | shape |
| `ext_shape_verb_object` | `S` | `schema_version` 数字 `1`，`verb` 为 `{}` | shape |

**步骤 2、3、5、6 的成员失败，期望两键 `unsupported`。** 对象里没有 `policy_version`。

| label | `p_sid` | `p_spec` | 期望 |
|---|---|---|---|
| `ext_unsupported_source_principal` | `S` | 合法两键再加 `source_principal` = `controller` | unsupported |
| `ext_unsupported_principal_bad_version` | `S` | `source_principal` = `controller`，`schema_version` = `"1"`，`verb` = `agentctl_steer` | unsupported，不是 shape |
| `ext_unsupported_unknown_note` | `S` | 合法两键再加 `note` = `x` | unsupported |
| `ext_unsupported_note_bad_version` | `S` | `note` = `x`，`schema_version` 数字 `2`，`verb` = `agentctl_steer` | unsupported，不是 shape |
| `ext_unsupported_unknown_policy_version` | `S` | 合法两键再加 `policy_version` 数字 `1` | unsupported。调用方不能自己填版本 |
| `ext_unsupported_unknown_executed` | `S` | 合法两键再加 `executed` 布尔 `false` | unsupported |
| `ext_unsupported_null_sid` | SQL NULL | `{"schema_version":1,"verb":"agentctl_steer"}` | unsupported |
| `ext_unsupported_missing_session` | `missing` | 同上 | unsupported |
| `ext_unsupported_unknown_verb` | `S` | `verb` = `not_a_verb` | unsupported |
| `ext_unsupported_prefixed_verb` | `S` | `verb` = `v13_agentctl_steer` | unsupported |
| `ext_unsupported_padded_verb` | `S` | `verb` = ` agentctl_steer`（前有一个空格） | unsupported。证明不 `btrim` |
| `ext_unsupported_empty_verb` | `S` | `verb` = `""` | unsupported，不是 shape。空字符串仍是字符串，成员资格失败 |

**步骤 7，期望七键，`executed` 是布尔 false，`policy_version` 是数字 1，`verb` 与入参逐字符相同，`policy_name` 是 `external_executor`。**

| label | `verb` |
|---|---|
| `ext_classify_observe` | `agentctl_observe` |
| `ext_classify_steer` | `agentctl_steer` |
| `ext_classify_answer` | `agentctl_answer` |
| `ext_classify_cancel` | `agentctl_cancel` |

`ext_repeat_steer`：对 `S` 与 `agentctl_steer` 再调用一次。返回对象与 `ext_classify_steer` 相等，快照仍相等。

成功对象的 Python 期望形状（`agentctl_steer`；其余三个只改 `verb`）：

```text
schema_version = 1
ok = true
classified = true
executed = false
verb = "agentctl_steer"
policy_name = "external_executor"
policy_version = 1
```

键集长度是 7。`executed` 用 `is False` 判断，不用字符串比较。

### 3.7 RAISE、关政策、以及回滚掉的 version 2

所有政策变更都在 SAVEPOINT 内，`finally` 里 `ROLLBACK TO SAVEPOINT`。ROLLBACK 之后：`external_executor` version 1 仍是唯一行且 `active`，version 2 的行数为 0，四张关系与 SAVEPOINT 之前的快照相等。下一个夹具开始前先看到这个恢复结果；恢复失败就停止，不准在脏政策上继续。

无 active 行与坏 value 的 RAISE 用阶段 41 `measured_reject` 的形状测「异常前零写」：外层 SAVEPOINT 先做政策变更；内部 `DO` 块在调用前记下 `v13_append_event(uuid,uuid,text,jsonb,uuid)` 的 `pg_stat_xact_user_functions.calls`，用嵌套 `BEGIN ... EXCEPTION WHEN OTHERS` 接住分类调用，把 `MESSAGE_TEXT` 与 calls 增量写入 `ON COMMIT DROP` 的临时表。增量必须是 0。消息用等号比较，不用子串。然后 `ROLLBACK TO`。语句原子性会撤销失败语句自己的写，所以单靠 ROLLBACK 后的快照不够；再加两条源码锁：`prosrc` 小写压空白后不含 `insert`、`update`、`delete`、`v13_append_event`、`v13_enqueue_effect`。`DO` 块开始前先做一次 `v13_control_authorized(NULL, NULL)` 探针；增量小于 1 则 `RAISE EXCEPTION 'environment block: track_functions'`，测试失败退出，不改断言。

**关政策后步骤 1–5 仍返回 jsonb。** SAVEPOINT 内只执行 `UPDATE v13_policies SET active = false WHERE name = 'external_executor' AND version = 1`。然后：

| label | 输入 | 期望 |
|---|---|---|
| `ext_inactive_shape_null` | `p_spec` SQL NULL，`p_sid` = `S` | shape，不 RAISE |
| `ext_inactive_unsupported_principal` | 与 `ext_unsupported_source_principal` 相同 | unsupported，不 RAISE |
| `ext_inactive_unsupported_note` | 与 `ext_unsupported_unknown_note` 相同 | unsupported，不 RAISE |
| `ext_inactive_shape_version` | 与 `ext_shape_version_string` 相同 | shape，不 RAISE |
| `ext_inactive_unsupported_null_sid` | 与 `ext_unsupported_null_sid` 相同 | unsupported，不 RAISE |
| `ext_inactive_unsupported_missing_sid` | 与 `ext_unsupported_missing_session` 相同 | unsupported，不 RAISE |
| `ext_raise_no_active_row` | `p_sid` = `S`，`{"schema_version":1,"verb":"agentctl_steer"}` | RAISE，`MESSAGE_TEXT` 等于 `v13: no active policy row for external_executor (seed lost?)`。append 调用增量为 0 |

这七条在同一个 SAVEPOINT 里按上表顺序执行，最后一条才 RAISE。前六条若读了政策，会提前 RAISE，这条表就把「步骤 1–5 不读政策」钉死。RAISE 只发生在良形且会话存在、随后要读政策的入口。

**value 不能 UPDATE。** `ext_policy_value_immutable`：SAVEPOINT 内 `UPDATE v13_policies SET value = '{"schema_version":1,"verbs":[]}'::jsonb WHERE name = 'external_executor' AND version = 1`。期望 RAISE，消息等于 `v13: policy rows are immutable (append new version + flip active)`。ROLLBACK 后 value 仍是 §3.4 的 jsonb。因此后面的坏 value 全部用下一 version，不 UPDATE。

**坏 value。** 每个 label 自己的 SAVEPOINT。`version` 用 `COALESCE(max(version),0)+1`，在干净库上是 2。先 `INSERT ... active=false`，再把 version 1 的 `active` 设为 false，再把新行设为 true。然后用 `S` 与 `agentctl_steer` 调用。期望都是 `v13: external_executor policy`，append 增量为 0，然后 ROLLBACK。

| label | 新行 value 与 version 1 的唯一差别 |
|---|---|
| `ext_raise_policy_extra_key` | 多一个键 `note` = `x`，`verbs` 仍是那四个字符串 |
| `ext_raise_policy_version_number` | `schema_version` 为数字 `2` |
| `ext_raise_policy_version_string` | `schema_version` 为字符串 `"1"` |
| `ext_raise_policy_verbs_dup` | `verbs` 为 `["agentctl_steer","agentctl_steer"]` |
| `ext_raise_policy_verbs_element` | `verbs` 为 `["agentctl_observe", 1]` |
| `ext_raise_policy_verbs_scalar` | `verbs` 为 JSON 字符串 `agentctl_steer`，不是数组 |

**空数组不是政策 RAISE。** `ext_unsupported_empty_verbs_array`：同样的 version 2 翻转，value 是 `{"schema_version":1,"verbs":[]}`。调用 `agentctl_steer` 返回两键 unsupported，不 RAISE，返回里没有 `policy_version`。然后 ROLLBACK。

**`policy_version` 来自行，不来自函数体常量。** `ext_policy_version_from_row`：version 2 的 value 与 version 1 完全相同，翻转 active 后调用 `agentctl_steer`。七键成功，`policy_version` 是数字 `2`，`schema_version` 仍是数字 `1`，`executed` 仍是布尔 false，`verb` 仍是 `agentctl_steer`。ROLLBACK 之后再调用一次，`policy_version` 回到数字 `1`。stage 43 不留下 version 2。

**成员资格只用当次 `verbs`。** `ext_membership_uses_row`：version 2 的 value 是 `{"schema_version":1,"verbs":["agentctl_observe"]}`，翻转 active。`agentctl_observe` 返回七键且 `policy_version` 为 2。`agentctl_steer` 返回两键 unsupported。ROLLBACK 后 version 1 恢复，`agentctl_steer` 再次成功且 `policy_version` 为 1。这一条防止函数体用拼接躲过字面量扫描、却仍忽略读到的数组。

执行证明开始前再断言一次：活动行是 `external_executor` / 1 / §3.4 的 value，version 2 行数为 0。label：`ext_active_v1_before_exec`。

### 3.8 执行证明

只做一条 `agentctl_steer`。不跑 observe、answer、cancel 的 parse → advance。不比较 `write_targets`。不断言 `steer/injected` 的正文被消费。不断言 effect 的 `status`。分类函数不在这条路径上。

两个本地函数，不 import `test_agentctl_verbs`。`ext_steer_sql_arm` 只拥有下面步骤 1–9 与 11–13（没有插在中间的第 10 步）。它的源码含 `v13_parse` / `v13_advance`，不含 `v13_external_exec_classify`。兄弟函数拥有 label `ext_steer_classify_uncalled`：在同一未提交事务里，调用 `ext_steer_sql_arm` 之前和之后各读一次 funcid 计数。这个兄弟的源码含分类函数签名，不含 `v13_parse` 或 `v13_advance`。`main` 可以调用两者。不扫整个测试文件的子串，否则禁止记号元组会把自己打红。一个函数同时含两边的字符串，就通不过自己的扫描。

连接在这条证明上保持 `autocommit = False`，并且已经 `SET track_functions = 'all'`。同一事务内完成从开会话到 advance 的全部语句，测量窗口中间不 `COMMIT`。开始前 `set_config('typesafe.provider','mock',false)` 与 `set_config('typesafe.model','jev-mock',false)`。不调用 `poison()`，不设置 `typesafe.endpoint`。

有序步骤：

1. 读 `tools` 里 `name = 'agentctl_steer'` 的 `param_spec`。键集不是恰好 `target` 与 `text` 则停止并报告。kind 不是 `sql` 或 `enabled` 不是 true 同样停止。不改这行来凑绿。
2. `v13_open_session`，spec `{"route_policy_name":"controller","version":1}`。记为 `root`。
3. `v13_append_event(root, 新 uuid, 'user/message', '{"text":"route agentctl_steer"}')`。文本非空。
4. `v13_spawn_subsession(root, spec)`。第二参必须是 `{"schema_version":1,"children":[{"tool_call_id":"tc-"+8 位十六进制,"task":"routed child"}]}`。键集不是恰好 `children` 与 `schema_version` 时活体 RAISE `v13: spawn args`（`v13/spawn/v13_spawn.sql:330-335`）。返回 jsonb 不是 uuid。`child` 取 `children[0].session_id` 的文本，与 `spawn_one`（`test_agentctl_verbs.py:200-214`）相同。不改 `v13_spawn.sql`。`v13_open_session` 插入的 status 已是 `ready`（`:312`）；用户消息必须在 spawn 之前，否则 `next_seq < 1` 会 RAISE `v13: spawn requires prefix`（`:347-348`）。这不是步骤 5 的 ready 计数失败。
5. 根上 `ready|claimed` effect 计数为 0。不为 0 则停止并报告，不改 spawn。
6. `v13_submit_override(root, {"intent":"direct","reason":"","schema_version":1,"source_principal":"operator"})`。
7. `UPDATE tools SET enabled = false WHERE enabled AND kind IN ('sql','tool') AND NOT (name = ANY(ARRAY['spawn_subsession','agentctl_steer']))`。
8. 组装 overrides 并调用 `mock_from_needed`、`set_mock`。overrides 的键与值：
   - `intent`：choice `sql_answer`，confidence `0.9`，`probabilities` 只含这个 choice。
   - `tool`：choice `agentctl_steer`，同样的 confidence 形状。
   - `gate_action`：`{"type":"noul","noul":0.9}`。
   - `gate_off_topic`：`{"type":"noul","noul":0.1}`。
   - `risk`：`{"type":"score","score":0.5,"confidence":0.9}`。
   - `stated::agentctl_steer::target` 与 `stated::agentctl_steer::text`：noul `0.9`。
   - `param::agentctl_steer::target`：choice 为 `child` 的文本。
   - `param::agentctl_steer::text`：choice 为 `steer-text`。
9. `SELECT v13_parse(root)`。断言 `remaining = 0`，`failed` 是 false，`abandon` 是 false，`snap.route_policy_name = controller`，`snap.route_policy_version` 的文本是 `1`。label：`ext_steer_parse_controller`。这里的政策名不是 `external_executor`。
11. `UPDATE sessions SET context_active_revision = v13_context_required(session_id) WHERE session_id = root`。
12. `SELECT v13_advance(root, parsed)`，`parsed` 是步骤 9 的整个 jsonb。
13. 返回词等于 `progressed`。根上最新一条 `type = 'turn/route'` 的 `payload.action` 等于 `sql`，`payload.tool` 等于 `agentctl_steer`。label：`ext_steer_sql_arm`。

`ext_steer_classify_uncalled` 的计数：

```text
funcid = 'public.v13_external_exec_classify(uuid,jsonb)'::regprocedure
coalesce(sum(calls), 0)
```

计数包住整个 `ext_steer_sql_arm` 调用，不插在 parse 与 advance 之间。按 `funcid` 查 `pg_stat_xact_user_functions`，不把签名字符串拿去比 `funcname`。`funcname` 只是 `v13_external_exec_classify`。用签名去比 `funcname` 会在调用前后都找不到行，增量恒为 0，即使 advance 调用了分类函数。先例是 `measured_reject` 把 `funcid` 绑到 `regprocedure`（`test_agentctl_verbs.py:424-441`）。第一次调用前没有行则当作 0。调用 `ext_steer_sql_arm` 之后增量必须等于 0。窗口内不 `COMMIT`；`COMMIT` 会清掉 `pg_stat_xact_*`。开始前仍做一次可回滚的 `v13_control_authorized(NULL, NULL)` 探针；增量小于 1 则失败并报 `environment block: track_functions`，不把未调用断言降级。

词不是 `progressed`，或 `turn/route` 不是 `sql` / `agentctl_steer`：停止并报告实际词与 payload。不准改 `v13_plan_arm.sql`、`advance.sql`、triage、route、`_snap_with`，也不准在分类函数里调用 advance 来「补上」执行。

绿的 `progressed` 不是 handler 成功。sql 臂先写 `turn/route`（`v13_plan_arm.sql:770`），再接住动态 `EXECUTE` 的 `OTHERS`，仍 `RETURN 'progressed'`（`:795-813`）。handler 缺失或 RAISE 时，`action=sql` 与 `tool=agentctl_steer` 仍在。不因此追加 `effects.status`、`tool/result` 或 `write_targets` 断言，也不改 `v13_plan_arm.sql` 或 `advance.sql`。`ext_steer_sql_arm` 绿只证明词、路由载荷、以及分类函数调用增量为 0。它不是产品入口。

这条路径会通过既有 sql 臂进入 `v13_agentctl_steer` 的 handler。那是 `v13_advance` 的活体行为。测试源码不以 Python `Call` 直接点名四个 `v13_agentctl_*`。分类夹具函数的源码不得包含 `v13_parse` 或 `v13_advance`。`ext_steer_sql_arm` 的源码不得包含 `v13_external_exec_classify`。`ext_steer_classify_uncalled` 的源码不得包含 `v13_parse` 或 `v13_advance`。两边用 `ast` 加源码字符串分开钉，不靠扫整个测试文件的子串。

### 3.9 装载与合成负例

`v13/load.py` 只追加两行：

```text
V13_ROOT / "external_exec" / "v13_external_exec.sql",
"external_exec": 43,
```

`r1_load_append_ok` 的 `approved` 改为五项，顺序固定：

```text
("fair_claim", "v13_fair_claim.sql", "fair_claim", 39)
("agentctl", "v13_agentctl.sql", "agentctl", 40)
("agentctl_verbs", "v13_agentctl_verbs.sql", "agentctl_verbs", 41)
("goal_workflow", "v13_goal_workflow.sql", "goal_workflow", 42)
("external_exec", "v13_external_exec.sql", "external_exec", 43)
```

失败文案改为：

```text
append is not fair_claim/39 then agentctl/40 then agentctl_verbs/41 then goal_workflow/42 then external_exec/43
```

`:417`、`:713`、`:754`、`:778` 四处旧四项文案全部换成这一句。函数签名不改。`order_names` 不改。

`r1_phase_d_prefix_allowance` 增加集合，不把 `"v13/external_exec/"` 放进 `prefixes`：

```text
v13/external_exec/v13_external_exec.sql
v13/external_exec/setup_db.py
v13/external_exec/test_external_exec.py
v13/external_exec/README.md
```

`allow()` 的路径条件变为：三个前缀，或 stage40 四路径，或 stage41 四路径，或 stage42 四路径，或 stage43 四路径。`extra - known_names - stage40 - stage41 - stage42 - stage43 <= fresh_ok`。stage43 必须是 tracked 的子集，缺一则 needle 为 `stage 43 path is not tracked`。旧 needle `outside the three prefixes`、`stage 40 path is not tracked`、`stage 41 path is not tracked`、`stage 42 path is not tracked` 保持原文。

必须改写的旧负例：

| 今天的构造 | 43 之后会怎样 | 新构造与 needle |
|---|---|---|
| `extra \| {v13/external_exec/test_external_exec.py}`，needle `outside the three prefixes`（`:724-730`） | 路径进入 stage43，不再拒绝 | 改为 `v13/ce_map/test_ce_map.py`，needle 仍是 `outside the three prefixes` |
| 在 `goal_workflow` 后追加 `external_exec` / `v13_external_exec.sql` / 43（`:745-750`） | 那就是合法尾 | 改为在 `external_exec` 行后再追加 `ce_map` / `v13_ce_map.sql` / 44。`replace` 的 count 为 1。tracked 并上 `v13/ce_map/v13_ce_map.sql`。needle 为五项文案 |
| `replace("v13_agentctl.sql", "v13_agentctl_extra.sql", 1)`（`:713`） | 元组仍不匹配，但文案变了 | 同一构造，needle 改为五项文案 |
| `replace("v13_goal_workflow.sql", "v13_goal_workflow_extra.sql", 1)`（`:778`） | 同上 | 同一构造，needle 改为五项文案 |
| `"goal_workflow": 42` 换成 `"goal_workflow": 43` | 与新的 `external_exec: 43` 撞车，先报 `duplicate stage number` | 换成 `"goal_workflow": 45`。45 不在 1–43 里，连续编号检查会在看到 45 时失败。needle 仍是 `stage number is not the next contiguous value` |

父计划只钉了目录 `v13/ce_map/` 与 `test_ce_map.py`，没有钉 SQL 文件名。负例按「目录名即 stage 键、SQL 为 `v13_<key>.sql`」补上 `v13_ce_map.sql`。44 不在本 stage 创建。

保留不动的负例：`v13/not_allowed/x.py`、`v13/agentctl/extra.py`、`v13/agentctl_verbs/extra.py`、`v13/goal_workflow/extra.py`、缺 stage 40/41/42 文件、`"agentctl": 40a`、`"agentctl": 41` 的 duplicate stage number、`"agentctl_verbs": 40` 的 duplicate stage key、`"agentctl_verbs": 44` 的不连续编号、`"agentctl_verbs": 41a`、`"goal_workflow": 42a`、以及函数前半对 fair_claim 结构的全部 `must_reject`。`"agentctl_verbs": 44` 这条在 `agentctl_verbs` 这个键上就把连续编号打断，走不到后面的 42/43，needle 不用改。

另加，每次只改一个条件：

- `v13/external_exec/extra.py` → `outside the three prefixes`
- tracked 去掉 `v13/external_exec/v13_external_exec.sql` → `stage 43 path is not tracked`
- `"external_exec": 44` 而 SQL 路径仍是该项 → `stage number is not the next contiguous value`。这里的 44 与上面 goal_workflow 改成 45 不冲突：两条是不同的 `replace`，都从合法活体出发。`"external_exec": 44` 不会和别的键重复，失败点在连续编号（43 的下一格被写成 44，前面的 42 之后期望 43）。
- `"external_exec": 43a` → `load diff plus line is not a canonical append`
- `replace("v13_external_exec.sql", "v13_external_exec_extra.sql", 1)` → 五项文案

`replace` 一律 `count=1`。`v13_agentctl.sql` 不是 `v13_agentctl_verbs.sql` 的子串。`v13_external_exec.sql` 在合法文件里只出现一次。

### 3.10 一次性库

`setup_db.py` 沿 `v13/goal_workflow/setup_db.py`。

- `DB = ll_external_exec_{pid}_{secrets.token_hex(3)}`。`token_hex(3)` 是 6 个十六进制字符。
- 拒绝 `agent_v13_` 前缀和名字 `agent_v13_longloop_p0_probe`。
- `probe_extension`：`stannum`、`pg_jsonschema` 缺一即失败。
- 同名已存在则退出，不 DROP、不接管。`CREATED` 仅在 `CREATE DATABASE` 成功后为 true。
- `load_stage(server, DB, "goal_workflow")`。不在 setup 里应用 `v13_external_exec.sql`。
- 连接用 `get_server()` 的本地 URI。不调用 `poison()`。
- 测试在 `create` 之前进入 `try/finally`。只在 `CREATED` 时 `DROP DATABASE "{DB}" WITH (FORCE)`。清理失败使进程非 0。DROP 成功之前不打印 `[ok]`。`setup_db.main` 若被直接调用，它的 `SystemExit` 不得绕开测试的 `finally`：创建步骤放进测试的 `try`。

`main` 开头先跑不碰数据库的 `r0_source_scope()` 与源码扫描，再创建库。`r0_source_scope` 会调用放行检查，因此跑 gate 之前四个新路径以及改过的 `load.py`、`test_plan_arm.py` 必须已经 `git add`。

行为顺序：安装比较 → §3.6 的 active 政策分类 → §3.7 的关政策、不可变 value、坏 value、空数组、version 2、成员资格 → `ext_active_v1_before_exec` → §3.8 执行证明。任一 SAVEPOINT 未回滚就不得进入执行证明。

### 3.11 错误、边界、并发

| 情况 | 行为 |
|---|---|
| 步骤 3 被写成「键不全则 shape」 | `ext_unsupported_unknown_note` 得到 shape。多键必须是 unsupported |
| 步骤 5 放在步骤 4 前 | `ext_shape_only_verb` 在 missing sid 上得到 unsupported |
| NULL `p_sid` 只用 `EXISTS` | `WHERE session_id = NULL` 不命中，函数掉进步骤 6 去读政策。`ext_unsupported_null_sid` 在关政策时会变成 RAISE。步骤 5 必须先判断 `p_sid IS NULL` |
| 关政策后步骤 1–5 RAISE | `ext_inactive_*` 失败。说明这些步骤读了政策 |
| 良形且会话存在、无 active 行却返回 unsupported | `ext_raise_no_active_row` 失败。缺行必须是那句 seed lost RAISE |
| 坏 value 返回 jsonb | 六个 `ext_raise_policy_*` 失败。消息必须是 `v13: external_executor policy`，不加详情后缀 |
| 空数组走政策 RAISE | `ext_unsupported_empty_verbs_array` 失败 |
| 函数体写死四个名字或写死 `policy_version` 为 1 | `ext_source_scan` 或 `ext_policy_version_from_row` 失败。`ext_membership_uses_row` 再挡住拼接躲扫描 |
| `executed` 被写成 `true` 或字符串 | 七键相等失败 |
| 成功对象多带 `verbs` 或失败对象多带 `policy_version` | 键集不等 |
| 调用 `v13_policy()` | 拿不到 version。`ext_policy_version_from_row` 失败；源码里也不准出现 `v13_policy(` |
| 分类函数去调用四个写动词或 `v13_advance` | `prosrc` 扫描失败；执行证明的分类增量也不再是「路径上为 0」这一单独命题 |
| 执行证明去断言 `write_targets` 或重放 answer/cancel | 超出终裁第 5 条。不写这些断言 |
| Python `None` 同时充当 SQL NULL 与 JSON null | `ext_shape_json_null` 没有发出 `'null'::jsonb`。按 §3.6 的两种字面量绑定 |
| 用 `funcname` 匹配签名字符串来数分类调用 | 增量恒为 0。必须用 `funcid = ...::regprocedure` |
| 把绿的 `progressed` 当成 handler 成功，再补 effect 断言换绿 | 超出终裁。不追加 `effects.status` / `tool/result` / `write_targets`，不改 sql 臂 |
| advance 词不是 `progressed` | 停止并报告。不改 sql 臂。根上若已有 ready effect，先看步骤 5 的计数。spawn 若 RAISE `v13: spawn args` 或 `v13: spawn requires prefix`，那是步骤 4 的调用形状，不是这条 |
| `param_spec` 不是 `target`+`text` | 停止并报告。不改 controller 带 |
| `pg_stat` 看不见探针 | 环境阻塞，退出非 0 |
| 安装中途失败 | `BEGIN/COMMIT` 整笔回滚。测试 `finally` 只 DROP 本进程创建的库 |
| `SET ROLE` 之后事务 aborted | 召回角色的 42501 包在 SAVEPOINT 里，然后 `RESET ROLE` |
| 重复分类调用 | 政策不变时 jsonb 相同。`ext_repeat_steer` |
| 并发翻转 active | 本 stage 不加密，不加锁。测试单连接串行。不把这个窗口写成身份合同 |
| 旧代码读到新政策行 | 旧读者按 name 取自己的行，不解释 `external_executor`。无迁移。回滚本次提交后，新库不再装这行；已有一次性库随测试 DROP |

源码扫描两路：

1. 磁盘上的 `v13_external_exec.sql` 压空白、转小写后不得含 stage 42 的禁止记号：`dblink`、`pg_net`、`lo_import`、`lo_export`、`pg_read_file`、`pg_write_file`、`copy program`、`v13_wake_is_satisfied_v1`、`v13_claim(`、`v13_claim_fair`、`13002`、`13003`。也不得含 `security definer`、`insert into tools`、`v13_agentctl_`。政策字面量没有 `v13_` 前缀，文件级扫描 `v13_agentctl_` 不会误伤它。四个无前缀工具名在文件里各恰好一次。
2. `prosrc` 另不得含：四个无前缀工具名、`v13_parse`、`v13_advance`、`v13_route`、`v13_append_event`、`v13_control_authorized`、`v13_policy(`、`btrim`、`security definer`、动态 `execute`、`insert`、`update`、`delete`、`route_policy`。`GRANT EXECUTE` 在函数体外，不在 `prosrc` 里，所以「`execute` 不得出现在 prosrc」不会误伤授权语句。

测试模块的 `ast.walk`：任何 `Call` 的 `Name.id` 或 `Attribute.attr` 不得是 `v13_agentctl_observe`、`v13_agentctl_steer`、`v13_agentctl_answer`、`v13_agentctl_cancel`、`v13_wake_is_satisfied_v1`、`v13_claim`、`v13_claim_fair`。字符串常量里的 SQL 不算 Call。`v13_control_authorized` 允许出现在探针 SQL 字符串里，不允许出现在分类函数的 `prosrc` 里。

### 3.12 被拒绝的替代与取舍

| 替代 | 不用的理由 |
|---|---|
| 分类函数直接调用四个写动词 | 那会变成第三分发器。终裁要求分类不执行 |
| 函数体写死四个动词名 | 允许列表的唯一来源是当次 active value |
| 调用 `v13_policy()` | 不返回 version，而成功对象必须带回读到的 version |
| 把 `external_executor` 写进 `route_policy_name` 或信封 | D-A.1 不得靠改信封实现。快照只证明 `controller` / 1 |
| 重放 stage 41 四动词成功语义，或断言 `write_targets` | 终裁第 5 条把执行证明收成一条 `agentctl_steer` 的 sql 臂 |
| import `test_agentctl_verbs` | 该模块是 stage 41 gate。43 只复制序言 SQL 的语义 |
| 把 `v13/external_exec/` 放进 `prefixes` | 放行是四路径闭集。目录前缀会放过 `extra.py` |
| 删掉 `external_exec` 负例 | 未来 stage 必须仍被拒绝。负例前移到 `ce_map`/44 |
| `UPDATE` 政策 value 来做坏值夹具 | 触发器拒绝。用下一 version 加翻转 active，然后 ROLLBACK |
| 把 version 2 留在安装 SQL 里 | 本 stage 只交付 version 1 |
| 改 `driver.py` 或 `v13_advance` 来调用分类函数 | 两者都冻结。执行路径本来就不经过分类函数 |
| 顺手实现 stage 44 映射或 stage 45 | 父计划把它们留在本 stage 之外 |

| 选择 | 另一头 | 理由 |
|---|---|---|
| 失败对象两键，成功对象七键 | 失败也带 `schema_version` | 终裁写明失败对象只有 `ok` 与 `reason` |
| 未知键是 unsupported，缺键是 shape | 凡键集不对都 shape | 终裁步骤 3 与步骤 4 的结果不同，测试能把它们分开 |
| `policy_version` 只在成功返回值 | 写进 parse 快照 | 信封冻结；D-A.1 不靠改快照落地 |
| 执行证明停在 `turn/route` | 继续断言 effect 与 child diff | 再往下就是 stage 41 的成功语义 |
| 负例 SQL 名用 `v13_ce_map.sql` | 只拒绝目录、不钉文件名 | 与 42 把 `v13_external_exec.sql` 钉进负例的做法相同，父计划已钉目录与 `test_ce_map.py` |
| `"goal_workflow": 43` 改成 `45` | 保持 43 并改 needle 去迎合 duplicate | 编号唯一先于连续编号。要保住的 needle 是连续编号那句 |

## 4. File-by-file impact

本计划文件不进实现提交。实现提交的闭集是下面八个文件。`v13/ce_map/` 不创建，不进这次提交。

| 文件 | 变更 | 原因与依赖 |
|---|---|---|
| `v13/external_exec/v13_external_exec.sql` | 新增。一个函数、一条政策 `INSERT`、`REVOKE`、`GRANT`、函数体外 `COMMENT` | W2。依赖累计 stage 42 已提供 `v13_json_keys`、`v13_json_int_ok`、`v13_policies`、`sessions`、角色 `v13_route` |
| `v13/external_exec/setup_db.py` | 新增。库名 `ll_external_exec_*`，`load_stage(..., "goal_workflow")`，不应用本 SQL | W3。沿 goal_workflow 的 setup |
| `v13/external_exec/test_external_exec.py` | 新增。安装比较、§3.6 与 §3.7 的全部 `ext_` label、§3.8 一条 sql 臂。模块 docstring 第一段是声称句 | W4。依赖 SQL、setup、`mock_from_needed`、`set_mock`、`r0_source_scope`。跑之前路径必须已跟踪 |
| `v13/external_exec/README.md` | 新增。声称句原文、签名、七步、两键失败、七键成功、政策字面量、非目标、两条 gate 命令。实跑记录留到 W5 | 首轮 gate 前必须被跟踪，否则 `stage 43 path is not tracked` |
| `v13/load.py` | 仅两个容器尾部各一行：`external_exec` / 43 | W1。与新目录同笔 |
| `v13/plan_arm/test_plan_arm.py` | 仅两个函数体：五项 `approved`、四处文案、stage43 四路径、负例前移到 `ce_map`/44、`goal_workflow` 的 43 改为 45 | W1。`r0_source_scope` 不动 |
| `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` | 仅 W5。在第 88 行之后新开 `## Stage 43`，追加第 89 行 | 两条 gate 都退出 0 之后。不改 86–88 |
| `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` | 仅 W5。在 `## Stage 42` 之后追加 `## Stage 43` | 同 W5。不改 PC 行、S40、S41、S42 |

**明确不改：** §2.6 的阻断列表，外加 `v13/loop/test_loop.py`、`v13/goal_workflow/test_goal_workflow.py`、矩阵第 86–88 行、台账 Stage 40–42。`v13_named_sql_writer` 与 `v13_spawn_writer_ok` 不加 `external_executor` 或分类函数的分支。

README 在 W4 就写清：声称句；函数不是 tools 行；七步顺序；失败两键、成功七键且 `executed` 为布尔 false；`policy_version` 只在成功返回值里；无 active 行与坏 value 的两条 RAISE 原文；空数组是 unsupported；真正执行是既有 parse → advance，快照仍是 `controller` / 1；不调用四个写动词；不交付注册身份、trusted bind、task lease；不回答 44/45。W4 的 README 不写「实跑通过」。

矩阵第 89 行列与第 88 行相同：

- 条文含声称句原文，并点明生产新增是 `v13_external_exec_classify` 与 `external_executor` version 1。
- 状态 ✅ 只在两条命令都退出 0 之后填写。
- 测试落点写实际命令与 `check` 计数。
- 缺口写：不证明注册身份、可信 bind、task lease、`claimedProcessID`、五表 authority store、CE 进程控制、wake、无人值守。不实现 stage 44 的映射语义，不实现 stage 45。不改 `driver.py`、信封、`v13_advance`。不把 `external_executor` 写入 route 快照。不闭合 D-3。不消费 stage 42 场景能力。

台账至少四行：

- S43-1：只新增 STABLE INVOKER 分类函数与 `external_executor` version 1。执行证明是一条 `agentctl_steer` 的既有 sql 臂。不是可信产品入口。
- S43-2：动词列表只来自当次 active value。函数体不写四个名字。shape 与 unsupported 是两键 jsonb、零写。两条 RAISE 文案按终裁。`policy_version` 只在成功返回值，且等于读到的行。
- S43-3：D-A.1 的政策版本不靠改信封实现。parse 快照仍是 `controller` / 1。无身份列，无控制文件。
- S43-4：合成负例从 `external_exec`/43 前移到 `ce_map` / `v13_ce_map.sql` / 44。`"goal_workflow": 43` 会先撞 duplicate stage number，故改为 45，needle 仍是连续编号那句。不改 `r1_load_append_ok` 的检查顺序，不放宽 `r0_source_scope`。

## 5. Risks

| 风险 | 处置与停止条件 |
|---|---|
| HEAD 不是含 `5f65d7a` 的树，或把 42 的未提交差和 43 一次提交 | W0 失败则停止。不授权创建目录 |
| 把未知键实现成 shape | `ext_unsupported_unknown_note` 与 `ext_unsupported_note_bad_version` 会红。不改终裁顺序 |
| 步骤 5 使用 `<>` 或只写 `EXISTS`，NULL `p_sid` 漏进读政策 | `ext_inactive_unsupported_null_sid` 会 RAISE。用 `IS NULL` |
| 为了证明零写去 `UPDATE` value | 触发器拒绝。坏 value 只走 version 2 + ROLLBACK |
| version 2 漏出 SAVEPOINT，执行证明看见空 `verbs` 或 `policy_version` 2 | `ext_active_v1_before_exec` 必须在执行证明之前 |
| 执行证明失败时去改 sql 臂或补 `write_targets` 断言换绿 | 停止。只报告词与 `turn/route` payload |
| `param_spec` 与 `target`/`text` 不一致 | 规格写入时该行键集是 `target` 与 `text`（`v13_agentctl_verbs.sql:345-357`）。活体变了就停止并报告，不改 controller 带 |
| `mock_from_needed` 签名与 stage 41 调用不一致 | 停止，按 `v13/loop/test_loop.py` 活体改调用。不改 noul 的 pass 带语义，不调用 `poison()` |
| 放行写成整个 `v13/external_exec/`，或删掉未来负例 | 精确四路径。`ce_map`/44 与 `extra.py` 仍拒绝 |
| `"goal_workflow": 43` 留着，needle 被改成 duplicate | 那是换断言去迎合检查顺序。编号必须改成 45，needle 保持连续编号 |
| `replace` 无 count，打到第二处文件名 | `count=1` |
| 改了 `r0_source_scope` 或模块级 AST | `changed existing test` / `changed module setup` 出现时撤回 |
| 新函数留着 PUBLIC，或插了 tools 行 | 安装比较：PUBLIC 无 EXECUTE；`tools` 与 revision 不变 |
| 文档先写 ✅，或把夹具分类写成可信入口 | W5 后置。声称句不准加宽 |
| `git add -A` 卷进本计划、42 的差、或空的 `v13/ce_map/` | 只按 §6 的路径暂存 |
| `pg_stat` 在 `EXCEPTION` 子事务里不可见 | 探针失败即环境阻塞。同时靠 `prosrc` 无 DML 钉住零写 |
| 一次提交里顺手写 stage 44 映射 | `v13/ce_map/` 不在闭集里。负例只在字符串里提到它 |

无新表、无新列、无事件回填、无 `controller` / 1 的迁移。政策 value 插错时，本次提交用前向修正加 version 2 并翻转 active，不 `UPDATE` version 1，不 `reset` 已推送的里程碑。一次性测试库 DROP 即消失。

**已经核对，不再当开放项：**

- 四项文案的四处锚：`test_plan_arm.py:417`、`:713`、`:754`、`:778`。
- `allow()` 的三前缀或 stage40/41/42：`:504-516`。`external_exec` 负例：`:724-730`、`:745-750`。
- `v13_json_keys` 排序、`v13_json_int_ok` 接受 0 与 1：`v13/control/v13_control.sql:102-112`。
- 政策 value 不可 UPDATE，无 active 行的 `v13_policy` 文案：`v13/schema/v13_core.sql:701-741`。
- `controller_surface` 四个工具名的顺序：`v13/agentctl_verbs/v13_agentctl_verbs.sql:498-512`。
- sql 臂 `WHEN 'sql'`：`v13/plan_arm/v13_plan_arm.sql:772-813`（`turn/route` 写入 `:770`）。`v13_route` 的 `action=sql`：`v13/loop/advance.sql:151-153`（函数自 `:110`）。
- `prepare_chain` 与 `turn/route` 断言：`test_agentctl_verbs.py:1262-1313`、`:1336-1370`。`write_targets` 在 `:1400-1406`，不复制。

**已核对，实现时若活体已变则停止，不构成新产品选择：**

- `tools.param_spec` 中 `agentctl_steer` 的键恰为 `target` 与 `text`（`v13/agentctl_verbs/v13_agentctl_verbs.sql:345-357`）。对不上就停止。
- `mock_from_needed(cur, sid, **over)` 在 `v13/loop/test_loop.py:111`，`set_mock(cur, mock)` 在 `:67`。对不上就按活体改调用点。

## 6. Implementation order and verification

### 6.1 实施顺序

1. **W0，确认施工基线。** HEAD 历史上有 `5f65d7a`，矩阵第 88 行两条 gate 为退出码 0，`v13/load.py` 尾是 `goal_workflow: 42`，`v13/external_exec/` 不存在。工作区没有要混进本次提交的其他修改。满足本条不授权创建 `v13/external_exec/`。不改旧 gate 去适配 43。

2. **W1–W4 一起写到可运行。** 四个新文件同时出现。README 含声称句和合同，不含实跑结论。`load.py` 只追加两行。`test_plan_arm.py` 只改两个函数体，含 §3.9 的五项文案与 `ce_map`/44 负例。SQL 只有分类函数和一条 version 1 政策。setup 装到 `goal_workflow`。不得单独提交放行。

3. **首次 gate 前按路径暂存。** `plan_arm` 用 `git ls-files`，看不见未跟踪文件。

```bash
git add -- \
  v13/external_exec/v13_external_exec.sql \
  v13/external_exec/setup_db.py \
  v13/external_exec/test_external_exec.py \
  v13/external_exec/README.md \
  v13/load.py \
  v13/plan_arm/test_plan_arm.py
```

禁止 `git add -A`、`git add .`。禁止暂存 `v13/ce_map/`、`v13/goal_workflow/` 的新改动、`driver.py`、本计划文件。

4. **顺序执行两条 gate。** 脚本不是 pytest。都要退出码 0。

```bash
UV_FROZEN=1 uv run python v13/external_exec/test_external_exec.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```

任一非 0 就停止收尾。按失败的 `ext_` 或 `plan_arm` 断言修根因，再暂存同一组路径并重跑。出现 `changed existing test` 或 `changed module setup` 时撤回越界编辑，不改 `r0_source_scope`。禁止改 sql 臂、禁止调用 `poison()`、禁止把执行证明扩成四个动词。一次性库由 `finally` DROP。

5. **两条都绿之后才做 W5。** README 补实际命令、退出码、`check` 计数。矩阵只追加第 89 行，条文含声称句原文，状态才填 ✅。台账只新开 `## Stage 43`。不回填第 86–88 行，不改 S40、S41、S42。然后：

```bash
git add -- \
  v13/external_exec/README.md \
  docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md \
  docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md
```

6. **最终树再跑第 4 步两条命令。** 看 `git diff --check`、暂存路径闭集、以及没有未暂存的 `v13/` 差。不得用文档更新前的退出码代替这一次。

7. **同一次提交。** 仅获准施工的实现者执行：

```bash
git commit -m "v13: add external executor ingress check"
git push origin main
```

不使用 `--no-verify`，不 force-push，不改写历史。hook 失败修根因。stage 44、45 不在这一笔里。本规划任务不执行该提交。

步骤 3 与 4 必须在同一次待提交树上重复到都绿。步骤 5 依赖步骤 4 的退出码 0。

### 6.2 验收清单

同时成立才算 stage 43 完成：

- 两条指定 gate 在最终文件上退出 0，一次性库已删除。
- 装载尾恰为 `external_exec: 43`。1–42 前缀不变。`v13/ce_map/` 仍被合成负例拒绝，SQL 名钉的是 `v13_ce_map.sql`。
- 生产新增恰一个 STABLE INVOKER 函数，加恰好一行 `external_executor` version 1。没有新 tools 行、新表、新列、新事件 type、新 `effects.kind`、新 route policy。`controller` / 1 与 `controller_surface` / 1 仍是 41 的那两行。
- 步骤 1 与 4 返回两键 shape。步骤 2、3、5 与列表外动词返回两键 unsupported。四条允许动词返回七键，`executed` 是布尔 false，`policy_version` 是数字 1。
- 关政策后步骤 1–5 仍返回 jsonb。良形且会话存在时无 active 行 RAISE `v13: no active policy row for external_executor (seed lost?)`。六种坏 value RAISE `v13: external_executor policy`。空数组返回 unsupported。合法 version 2 的成功对象里 `policy_version` 是 2，回滚后不留下该行。
- 凡返回 jsonb 的分类调用，前后 `sessions`、`events`、`effects`、`v13_policies` 行级快照相等。
- 执行证明只有 `agentctl_steer`：`v13_parse` 快照是 `controller` / 1，advance 词是 `progressed`，最新 `turn/route` 是 `action=sql` 且 `tool=agentctl_steer`，该路径上按 `funcid` 计的 `v13_external_exec_classify` 调用增量是 0。`ext_steer_sql_arm` 与 `ext_steer_classify_uncalled` 的源码禁区分开。没有 `write_targets` 断言。绿的 `progressed` 不是 handler 成功，也不是产品入口。
- `driver.py`、`v13_advance`、信封未改。`r0_source_scope` 未改。
- 文档只记录 stage 43 的实跑。声称句没有被加宽成可信产品入口、注册身份或 task lease。

**交付结论只能是：夹具绑定的现存 `p_sid` 上，`external_executor` version 1 与一个零写的 STABLE 分类函数已经把允许动词分成七键且 `executed=false`，并把 `source_principal`、未知键、列表外动词、空会话与不存在会话分成两键 `unsupported`。真正执行仍是既有 parse → advance 的 sql 臂，且只对 `agentctl_steer` 复核到 `controller` / 1。不能据此声称注册身份、可信 bind、task lease、CE 进程控制、stage 44 映射或 stage 45 已经交付。**

## References

- 父合同：`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md`（能力表 `:77-104`，E1 `:517-519`，依赖表 `:494-535`，数据模型 `:568-622`，PR 第 4 项 `:769-783`）
- 结构范本：`docs/plans/v13-stage42-goal-workflow-2026-10-08.md`（§3.8 负例前移）
- 终裁：`prompt-exports/oracle-chat-2026-10-09-013449-untitled-chat-58124a-90ec.md`（本规格的函数、政策字面量、七步、两条 RAISE、执行证明范围）
- D-A.1：`docs/reviews/v13-agentctl-da-rulings-2026-10-03.md:21`
- 矩阵第 88 行与下一行位置：`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md:124` 之后为第 89 行
- 台账：`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` 的 `## Stage 42` 之后追加 `## Stage 43`
- 装载：`v13/load.py:59`（尾部三项 `:57-59`）、`:104`（尾部三键 `:102-104`）、`files_through` `:108-110`
- 放行：`v13/plan_arm/test_plan_arm.py` 的 `r1_load_append_ok`（`:327`，文案 `:417`）、`r1_phase_d_prefix_allowance`（`:425`，`allow()` `:504-516`，负例 `:713`、`:724-730`、`:745-750`、`:754`、`:778`）、`r0_source_scope`（`:781`）
- 政策与助手：`v13/schema/v13_core.sql:701-741`；`v13/control/v13_control.sql:102-112`；`v13/agentctl_verbs/v13_agentctl_verbs.sql:384-512`
- 函数头先例：`v13/goal_workflow/v13_goal_workflow.sql:5-9`、`:93-94`；setup 先例 `v13/goal_workflow/setup_db.py`；一次性库清理先例 `v13/goal_workflow/test_goal_workflow.py:1548`
- sql 臂：`v13/plan_arm/v13_plan_arm.sql:772-813`；`v13/loop/advance.sql:151-153`
- S2 序言：`v13/agentctl_verbs/test_agentctl_verbs.py:1262-1313`、`:1336-1370`；零调用测量 `:162`、`:438-462`
- 调查原文已被父计划收窄，不照抄「改 driver」或「政策版本入 route 快照」：`docs/investigations/v13-s1-s2-e-i-four-step-survey-2026-10-06.md:169-176`
