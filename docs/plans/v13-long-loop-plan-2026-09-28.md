# v13 长循环 Phase 0 计划（2026-09-28）

**状态：Phase 0 文档与技术裁决已接受。** 运行时未实现。A–D 未审核，不得开工。此前「候选、未经父复审」以及收尾当时尚未提交，都是历史状态。父已复跑最终证据。本里程碑按路径提交这两份文档。

接受的是本计划与证据文档。不是 stage 变绿，不是产品可用，不是活体 advance 已拒绝 stopped 根上的非空 `failed`。调查只是本地背景，不是必读，不提交。接受不依赖读取 gitignore 文件。审核导出只作本地溯源：`prompt-exports/oracle-review-2026-09-28-234859-new-chat-152bff-398c.md`。

## 1. 优先级

1. 本轮用户已定的四期范围与首期真链，高于追溯表里的任何旧切片建议。
2. 已核路线图句子。
3. 已核活体 SQL。
4. 本文技术裁决。
5. 调查建议。

冲突则停。不得改 stage 1–29 来对齐。技术裁决不是用户产品投票。

## 2. 用户决定与技术裁决分开

**用户已决定：** v13 继续开发，不是 v14/v15，不是外层 wrapper。PG 是唯一控制语义 owner。外部 IO 不进事务。不建第二状态源，不建工作流引擎。四期以后全写；本文只留未审核占位。未审核范围固定为：A 控制链加首期真链（含 G2，以及该真链必要的 read 接线）；B 工具 G1；C 单 goal 无人值守；D 多 goal 公平、并发帽与 soak。真链一步到位。Fake 是确定性 gate 手段，不是分期依据，A 不是 Fake 期。真实 provider 验收须另行授权；本次不调用。PC-4 可后期实现。不改 stage 1–29，不改父循环 memory。隔离一次性测试库已授权；现有库不得 DROP。

**不是用户逐条点名：** 原子写者、状态闭集、delta 四动词、水位与门序拆分、explore 豁免拆分、L19「租约边界」。这些是本轮技术裁决或简报转述。L19 路线图原文（`:125`）是不建 lane fence、不新返回词。不得把这些句子改写成用户产品投票，也不得因此禁止以后正当的 `ASK_USER`。

## 3. 范围

本期交付本计划与 `docs/reviews/v13-long-loop-phase0-evidence-2026-09-28.md`。探针留在 `prompt-exports/`，不得 `git add`。证据文档内嵌可执行脚本，不靠忽略文件单独充证。

不实现 24 项运行时。不改 `v13/load.py` 与 stage 1–29 字节。不建驱动器。不跑 stage runner。不把 demo 写成生产事实。

## 4. 已核现状

行号本轮重读。错行已改。

### 4.1 装载

`v13/load.py`：`SQL_LOAD_ORDER` 29 项，末项 `govern/v13_govern.sql`，`STAGE_THROUGH["govern"]=29`。其中 `mgraph_assembly` 是第 16 项，`seam` 是第 21 项。通过 govern 的 29 项已经包含这两者。不得重排，不得再装一次。`read_tools/` 不在这 29 项里。新 stage 的 SQL 只追加在表尾。本轮不改 `load.py`。

### 4.2 should_run

活跃策略 version 3：`v13/govern/v13_govern.sql:348-359`。`duty_cycle` 的 effect 是 `shadow`，`goal_stopped` 是 `block`。`:396-399` 只是 id 允许名单，同时允许 `block` 和 `shadow`，不是返回分支。`duty_cycle` 仅当 `effect='block'` 才返回：`:425-428`。因此 `duty_cycle=0` 不是活体 `should_run=false`。`goal_stopped` 的判定在 `:438-444`，返回在 `:444`；status 为 `completed`/`failed`/`cancelled` 时不命中。探针只证明 `goal_stopped` 这条 block。

`v13_should_run` 仍是 `v13/should_run/v13_should_run.sql:195-202`，返回 gate IS NULL。govern 未替换它。`v13_triage_prework` 的假返回在 `v13/should_run/v13_should_run.sql:239-243`。govern 未替换该函数。govern 替换了 gate（`:361`）和 `v13_advance`（`:720`）。`quota_window` 是 stage 27，更早替换过 gate；govern 后加载生效。

### 4.3 advance 与收据

活体 `v13_advance`：`:720`。会话锁：`:737` `FOR UPDATE`。本文「advance ⑤」指 harness 收据写入，不是 `v13/loop/advance.sql` 的预算步。候选谓词 `:849-852`。尚无同源 `turn/material_spent` 时 `:862-866` **就会**写。不读 `v13_should_run`。已有同源收据不插第二条。

`should_run=false` 零新 effect 的臂：spawn `:805-808`（`:809` 是 `v13_spawn_batch_allowed`，不是该臂）、approval `:894-897`、continuation `:941-944`。两键入队 `:911-912`。`resolve/failed`：`:978-983`（`duty<>0` 且 should_run 假且 `p_snap->>'failed' IS NOT NULL`；键缺失与 JSON null 都是 SQL NULL，`false`、`0`、非空文本不是）；`:989-992`（布尔 `failed` 为真，不读 should_run）。探针 snap 无 `failed` 键，两条都没跑到。explore RAISE：`v13/triage/v13_triage.sql:529`。本轮未重跑该测试。

### 4.4 actor、指纹、hint、claim

`v13_control_operator()`：`v13/acl/v13_acl.sql:74-86`。超级用户，或 `pg_has_role(current_user,'v13_route','USAGE')`。`v13_control_authorized`：`:90-118`。NULL actor 时等于 operator；非 NULL 只在 actor 是 target 的直接父时为真。自身为假。

6 参 `v13_complete`：`:245`。锁前非 NULL 只放行 human 且亲缘通过：`:271-274`。锁后同一复核在 `:292-296`。`:297-299` 是 actor 为 NULL、kind 为 human、且不是 operator 的 ELSIF，不是第二处非 NULL 校验。`:300-302` 才是 attempt/fence 不一致则返回 `stale`。给 tool/llm 传会话 UUID 会 RAISE `v13: session not found`。5 参包装 `:459-469` 传 `NULL`。显式 actor 不等于非 NULL。tool/llm 的 NULL 路径不走 human 那条 operator 判定，另受 SQL EXECUTE 与 attempt/fence 约束。`v13_worker` 在 `v13/schema/v13_core.sql:842` 是 `LOGIN NOINHERIT`。`v13_control_operator()` 为超级用户，或当前用户对 `v13_route` 有 USAGE。`v13_route_login` 经 `:847` 被授予 `v13_route`。这是成员事实，不是「只有它才能当 operator」。生产角色是否满足 operator 由后期计划核验。角色创建在 `:816-848`。

`v13_goal_fingerprint`：`:36`。排除名单 `:62-65` 与 `:79-82`：`session/completed|failed|cancelled`、`goal/stopped|resumed`、`control/handoff`、`wake/satisfied`、`turn/material_spent`。新的 plan/todo 种类会计入指纹。`v13_goal_stop` 在仍有 `ready|claimed|unknown` effect 时 RAISE（`:275`）。`v13_goal_resume` 在指纹与停止时不一致时 RAISE（`:335-336`）。本轮不改指纹函数。

`v13_cancel` 显式 actor：`:121`。1 参包装 `:236-241` 传 NULL。`v13_quota_eligible` 只计本 session（`v13/quota_window/v13_quota_window.sql:94-99`）。`v13_claim` 自 `v13/fanout/v13_fanout.sql:266` 是全局 ready 池。`:291-294` 的 `session_id` 只排同一 mutation_scope 的 `op_seq`。hint：`v13/govern/v13_govern.sql:517-576`，只返回 `run_now`/`wait`/`dont_notify`。stopped 返回 `dont_notify` 在 `:545-546`。`:543` 是另一臂的 `run_now`。

### 4.5 路线图

文件：`docs/plans/v13-layered-control-roadmap-2026-09-26.md`。下面行号都指这一份。

F11 `:80` 自答拒折进 F17。F30 `:99` 无 link 表、无 send 账本。L12 `:118`（不是 `:108`；`:108` 是 L2）收据在 advance ⑤、不在 complete。L19 `:125`（不是 `:115`；`:115` 是 L9）。L21 `:127`。L22 `:128`。L24 `:130`。L25 `:131`。L26 `:132` 假则零新 effect。L32 `:138` goal stopped 不等于 `duty_cycle=0`。

### 4.6 探针

历史裸命令 `uv run python prompt-exports/v13-long-loop-p0-advance-receipt-probe.py` 仍有退出码 0 的记录，不改标成冻结命令。本轮规范复现命令是 `UV_FROZEN=1 uv run python prompt-exports/v13-long-loop-p0-advance-receipt-probe.py`，退出码 0。脚本已增加角色 emit，并把 `agent_v13_govern` 缺失改为继续、不 DROP。16 条具名断言的谓词未改，仍全 PASS。旧 return 只看 `PROBE_OK` 与 `BASELINE_MISSING`，忽略 `BASELINE_EXTRA`；现 return 还要求 `ok`、`BASELINE_EXTRA []`、且没有 `FAIL baseline database set changed`。这是加强，不是改写 16 条。清理只 DROP 本次 created 的 `agent_v13_longloop_p0_probe`；名字已存在则拒绝、不 DROP。

| 路径 | 调用前 | 结果 | material | new_effects |
|---|---|---|---|---|
| progress | false / goal_stopped / 0 | waiting；调用后仍 false | 0→1，就会写收据 | [] |
| finish | false / goal_stopped / 0 | terminal，status=completed。调用后 should_run=true、gate=null，因为 status 已 completed | 0→1 | [] |
| spawn_calls_stopped | false / goal_stopped / 0 | waiting；harness 前返回 | 仍 0 | [] |

第三条的 gate 与 material before 在 JSON 里，不在具名 PASS 名中。`pred` 是 setup 的 effect id，不是 `v13_harness_predecessor`。quiet 未跑。本次冻结命令的脚本输出含 `ROLE db=postgres current_user=postgres rolsuper=True` 与 `ROLE db=agent_v13_longloop_p0_probe current_user=postgres rolsuper=True`。这解释了 `v13_goal_stop` 为何通过。生产不得假设超级用户。

## 5. 单库加载声明（本期完成的是声明，不是建库）

首期产品库的 SQL 体就是 `SQL_LOAD_ORDER` 第 1 至 29 项，末项 govern。第 16 项 `mgraph_assembly/v13_mgraph_assembly.sql` 与第 21 项 `seam/v13_seam.sql` 已在其中。不得重排，不得再装。

`v13/read_tools/` 本轮列过目录：没有 `*.sql`。它不是待追加的 SQL 文件列表。`setup_db.py` 会 DROP `agent_v13_read_tools`，`load_stage(..., "seam")`，然后 `run_probes`。那是隔离 fixture，不是产品装载。产品库不得调用它。

注册 DML 形状已核，生产闭合未完成。`test_read_tools.py` 的 `run_ring` 在运行时 `INSERT INTO tools` 四行（`TOOL_ROWS`，约 `:896`）：`read_pi`、`read_file_swift`、`read_file_py`、`read_duck`。基线工具 7 个（`BASELINE_TOOLS`，约 `:923`）。同一 fixture 从当前 `default` v1 复制出新 version，追加 8 条 `NEW_BANDS`，再冻结。`open_session` 传入的 JSON 是 `{"route_policy_name":"default","version":2}`（`test_read_tools.py:1101`）。落列是 `sessions.route_policy_version`，夹具断言为 2。输入键不是列名。`v13_open_session({})` 仍不是绑定证据。README `:128`：hub 按冻结 `request.handler` 分派。README 偏差台账 P1（`:151` 一带）：无 `goal/override` 的根会话会多一个 `triage` choice；没有 `triage` pass 带时 `v13_triage_steer` fail-closed。环上首次 `v13_parse` 前调用 `v13_submit_override`，`intent=direct`。种子 v1 与该 v2 都不加 triage pass 带。这些是 fixture 事实，不是产品注册已经闭合。

产品闭合仍要后期计划核验：会话的 `route_policy_version` 必须指到那份已冻结的新 version；根上首次 parse 前要有同等 override，或另有已审核的 triage pass 带。默认开会话规则本轮未重读，写在 §10。不要把 `run_ring` 当成产品完成。停在 seam 时 parse 前 `UPDATE tools SET enabled=false WHERE name='spawn_subsession'`（测试约 `:1279`）是 catalog 豁免尚未装上的 fixture 特例。产品库装到 govern 后不要抄这句。

stannum GRANT 不是 `SQL_LOAD_ORDER` 的一项。字面与 `v13/characterize/setup_db.py:23-31` 相同：`GRANT USAGE ON SCHEMA stannum` 以及 `score_bound`、`score_bound_indexed`、`tokenize` 的 EXECUTE，授予 `v13_recall`、`v13_resolve`、`v13_route`。该文件注释写明这是部署面授权，因为角色身份走 recall 链会 42501，且 SQL 文件内不得写这条 GRANT。README P2 写加载 seam 不需要额外 stannum GRANT。探针在 `load_stage(govern)` 之后执行同一字面；装载本身发生在 GRANT 之前并成功。探针连接是超级用户，因此这次三案没有证明该 GRANT 对探针闭环必需，也没有证明产品角色不需要它。产品安装把它列为未决依赖：后期计划按产品角色核验。不冒称已完成，也不把它写成第 30 个 SQL。

角色创建在 `v13/schema/v13_core.sql:816-848`。`v13_route_login` 经 `:847` 入 `v13_route`。`v13_worker` 是 NOINHERIT。operator 的定义只是 §4.4 的函数事实。生产谁满足该函数，后期核验。`v13_spawn_owner` 的 CREATE 本轮未重读。

**已声明的组合：** 新建库，名不定，不得复用既有 `agent_v13_*` 或探针名；按 1..29 装入 govern，已含 mgraph_assembly 16 与 seam 21；不追加 read_tools SQL；不调用 read_tools `setup_db.py`。四行 INSERT 与 8 条带只是已核 DML 形状。handler 在 claim 提交之后、complete 之前跑。

**未闭合，列在 §10：** `route_policy_version` 绑定；首次 parse 前的 override 或 triage pass；产品角色与 stannum GRANT 核验；产品库名；不把 fixture 的 `max_cycles=6` 抄进产品种子（README：该种子只活在会被 DROP 的库）。

## 6. 技术裁决

### T0 步序

**裁决.** harness 消费 material 候选且该 `source_effect_id` 尚无收据时，`:862-866` 就会写。不是可写。`should_run=false` 只保证对应臂零新 effect。quiet = 本跳不调用 `v13_advance`，探针未证明。未消费 tool/call 在 `:805-808` 返回，不写收据；调用前仍是 false / goal_stopped / material=0。

**证据.** §4.3、§4.6。L26 `:132`。

**不做.** 不概括成所有假路径都写或都不写。不改写者去读 should_run。驱动器不自写收据，不用 task_class 豁免。

**后期.** 已有候选的 effect 回合必须调用 advance 并接受结果。规划与 quiet 靠不进入写者，不靠豁免旗。保护已经 stopped 的根时，禁止顶层 `p_snap->>'failed' IS NOT NULL` 再调用 advance。这包括 `false`、`0` 和非空文本。键缺失与 JSON null 不同：`->>` 得到 SQL NULL，不进入该禁令。不要断言 stop 之前写下的失败事件必然破坏 resume：`v13_goal_stop` 会按当时事件重算指纹。永久拒绝的序是已经写下 `goal/stopped` 之后再进入 `:978-983` 或 `:989-992`。这两臂不在指纹排除名单（`:62-65`、`:79-82`）。IO 前的只读检查有并发竞态；后期必须在与 `v13_goal_stop` 相同的根会话锁内重验。这是驱动器或新 stage 的开工门，不声称旧实现已经安全。终态根在 `:754-756` 先 `RETURN 'terminal'`，到不了 `:978`，不在本禁令范围。审核稿写的 `:739-741` 经核对是 unknown session 的 RAISE 与其后的 `v13_probe`，不是终态返回，不写入合同。安全处置未审核。本轮不改 stage 1–29，也不改指纹函数。

### T1 联合语义

**裁决.** plan 与 todo 是事件加 STABLE 折叠。不建表。todo 不是 session/effect，禁止用 spawn 表示。`claimed_by` 只是归因，不是租约。`v13_should_run` 只返回布尔。selected_todo 是单独的只读折叠，零写、不入队。函数名不冻结。

**证据.** `:195-202`。L19 `:125` 不建 lane fence。这是技术裁决，不是用户点名。

**不做.** 不扩展 should_run 的返回形状。不把未核的 64/8 写成常数。

### T1.1 写者：两种语义、幂等、锁序

同一具名 SQL，两种调用，不得混成一次 `plan/committed`。

- `plan_commit`：同事务写 `plan/committed` 与初始 `todo/delta`。建立或替换当前 advancement 计划。受水位约束。
- `todo_delta`：只写 `todo/delta`。用于完成、绑定、到期、丢弃。不写 `plan/committed`，不刷新 `based_on_seq`，不把已失效计划重新变成当前 advancement 计划。水位失效后仍可记账。记账不是复活。

目标域钉死为根。plan/todo 事件只写根会话事件流。任何 actor 或子任务提交先映射到 root，锁 root 行，不锁子会话来代替。selected_todo 读同一条根流。不把子会话改成第二事件域。

`apply_id` 的唯一域是 root。`plan/committed` 与 `todo/delta` 的载荷写入 `apply_id`、`call_kind`、`canonical` jsonb。会话锁内只在根流上按 `apply_id` 查找。同 `call_kind` 且 `canonical` jsonb 相等：重放，返回该次 `plan_id` 与 `todo_id` 列表，零新事件，不调用 provider。同键但 `call_kind` 或 jsonb 不同：RAISE、零写。相等用 jsonb 相等。若 jsonb 相等不够，停并 `ASK_USER`。生成 `canonical` 的算法不在本轮冻结，列入 §10。不建 `command_receipts`。同一次 `plan_commit` 的初始 `todo/delta` 与那条 `plan/committed` 共用 `apply_id`、`call_kind=plan_commit` 和同一份 `canonical`。此后的完成、绑定、到期、归档 delta 才用各自的 `apply_id`。初始 delta 若改用 `call_kind=todo_delta`，会落入同键异种类并整笔 RAISE。

`plan_commit` 重放的查询作用域是根流上同 `apply_id` 的 `plan/committed` 及其同事务、同 `call_kind=plan_commit` 的初始 delta。当前有效计划只决定哪些 `todo_id` 有资格进入 selected_todo。对这些 id，status、绑定、`due`、归档折叠根流上的完整历史，不以本次 `plan_commit` 为历史起点。旧计划期间的绑定与归档不丢。替换后，不在新计划成员集里的 todo 不可选。`reuse` 或直接引用必须由新 `plan_commit` 同事务写明，且不得重置 class、status、绑定、`due`、归档。直接引用适用同一 `reuse` 校验：同 todo 且文本哈希不变，否则 RAISE。文本哈希算法与 `canonical` 算法同列 §10，未冻结。`continuous_monitor` 不例外。

锁内顺序：映射 root；`FOR UPDATE` 锁 root；授权（T1.4）；查找并核对已有 `apply_id`；合法重放直接返回、零写，此步先于 stopped/终态拒绝，因此成功提交后响应丢失、随后被 stop 的重试仍返回原身份，且不追加事件、不改指纹；异参在此步 RAISE。仅首次请求才检查 stopped/终态，再做水位比较（只对 `plan_commit`）和状态迁移校验。会话锁使并发首次提交只插入一次。

**证据.** 收据写者不读计划，所以计划不能借 effect 回合落地。存储位置与重放优先级在这里写死。规范算法未冻结。

事件闭集：`plan/committed`、`todo/delta`。动词：`add_new`、`update`、`link_successor`、`reuse`。同事务全成或全败。写者零 effect，不调用 `v13_advance`。`todo_id` 是载荷 UUID。task_class：`advancement_task`、`continuous_monitor`、`user_gate`、`user_action`、`blocker`。`add_new` 后 class 不可变。

初态按类，不是一条总闭集再打补丁：

| class | add_new 初态 |
|---|---|
| advancement_task | `pending` 或 `runnable` |
| user_gate / user_action / blocker | `pending`、`runnable`，或 `blocked` |
| continuous_monitor | 只许 `waiting`，且 `due` 非空。这是唯一例外，不是从 `pending` 迁来 |

空 `due` 的 monitor `add_new`：RAISE、零写。status 闭集：`pending`、`runnable`、`waiting`、`blocked`、`done`、`dropped`。迁移：`pending`→`runnable|dropped`；`runnable`→`waiting|blocked|done|dropped`；`waiting`→`runnable|blocked|dropped`；`blocked`→`runnable|dropped`；`done` 与 `dropped` 无出边。`waiting→dropped|blocked` 是取消与退役出口，不得被「到期才能离开 waiting」盖掉。

一次 monitor 成功不是 `done`。同一 todo 在同一 delta 里 `runnable→waiting`，并写上新的非空 `due`。`done`/`dropped` 只表示退役。`reuse` 仅同 todo 且文本哈希不变，否则 RAISE。关系拒环，只指向同一 goal。`resume_when` 只是 `{on,id}` 闭集，不是表达式语言。

初态按类的表仍是合同。同键异参不再静默成功。

**不做.** 不建 `plan/superseded` 种类。不在本轮插入事件。不冻结函数名。

**后期.** 用户消息把 todo 标完成，是 `todo_delta`，不是 `plan_commit`，也不是 C5 的 `skip`。事件种类若被旧闭集拒绝，不得改旧文件。新 stage 不能放行就停并 `ASK_USER`。该校验本轮未重读。

### T1.2 水位只约束 plan_commit

`based_on_seq` 绑定提交时的会话序。其后新的用户消息或 steer 使该计划对 advancement 失效。失效是折叠谓词，不是触发器，不是自动插入。`plan_commit` 在锁内、且已排除合法重放之后，比较水位；不一致则 RAISE、零写。当前 advancement 计划 = 最新一条仍通过水位谓词的 `plan/committed`。替换是新的 `plan/committed`，`supersedes` 指向旧 `plan_id`。

`todo_delta` 不参加这比较，也不制造新的当前计划。用户消息或 steer 的活体种类字面本轮未重读。写者开工前必须重读。对不上就停。这是开工门，不是已通过。

### T1.3 计划门不是 should_run 的新 block

**裁决.** 计划门是单独的只读谓词。它不是 `v13_should_run` 的新 block id，也不把该布尔改成「无计划即假」。谓词为假只跳过未来新 stage 在 `CREATE OR REPLACE v13_advance` 里新增的那一个 selected_todo advancement 臂。不改其它臂。子会话不套这个谓词。控制动词不咨询它。函数名后置。合同不空：谓词回答「该根是否有 T1.2 的当前计划，且选出的 todo 属于该计划」。

stage 29 里没有这个臂。下面这些都不是计划门站点，插入点若落在其中就停：spawn `:805-808`，approval `:894-897`，continuation `:941-944`，收据 `:862-866`，`context_refresh` `:1012`，预算 human `:1027`，`resolve_budget` `:996`，judge `:1043`，`v13_triage_steer` `:1056`，`v13_route` `:1060`，`CASE` `:1089`。无计划的根今天仍走这些路径；不得把「指不出臂」落成在 `CASE` 里全局停工。

这一份替换同时写入 T1.6 的锁内绑定。两段各自 `CREATE OR REPLACE` 会互相覆盖，禁止。本轮不实现。具体接线是 §10 开工门，后续 stage 必须核实。

**后期测试（只出现在 §9，计划，未跑，未通过）：** 无当前计划时根 advancement 不制造新 effect；控制动词在原成功条件下仍可用；finish 在调用前 should_run 为假时仍可结算并写收据。

### T1.4 规划无 material，不是无治理

豁免只包括：不调用 `v13_advance`，不插入 effect，不制造 material 候选。不豁免授权、停复、成本。

没有 `apply_id` 的新规划调用，在模型 IO 前做只读准入：根会话存在，status 不是 `completed`/`failed`/`cancelled`，生命周期不是 stopped，调用者通过下面的授权。失败则不调用 provider。已有 `apply_id` 的重试不得用这道准入跳过写者，否则停后的合法重放不可达；先调用写者，由 T1.1 返回原身份或 RAISE。首次写入才在锁内拒绝 stopped/终态。合法重放不走这道拒绝。不得在 stopped 上追加新的 plan/todo 事件。那些种类不在指纹排除名单里，写入会使 `v13_goal_resume` `:335-336` 拒绝恢复。本轮不改 `v13_goal_fingerprint`。将来若要排除这些种类，是另一份已审核计划里的新 stage 替换，T1.4 不隐含它。`v13_goal_stop` 只挡忙碌 effect（`:275`），挡不住无 effect 的规划写入，所以写者必须自己拒写。

成本：发起规划调用的驱动器负责有限重试和成本记录。次数本轮不定。禁止无界重试。`quota_window` 看不见这次调用，所以「不扣 material」不等于可以忙等。

规划写者自己的授权只允许两类，不套到普通 tool/llm complete：显式 `NULL::uuid` 且 `v13_control_operator()` 为真；或非 NULL 且 `v13_control_authorized(actor, target)` 为真（直接父）。根没有父，所以非 NULL 的根规划恒拒。直接父形状保留，是为了与 human complete 的亲缘一致；在「事件只写根」下，它没有成功实例。不把子会话改成事件目标来制造成功实例。显式 NULL 且不是 operator：RAISE、零写。这不是「禁止一切 NULL」。无人值守规划仍未授权。

合法重放先于 stopped/终态拒绝，见 T1.1。首次请求才在写入前拒绝 stopped/终态。重放不追加事件，因此不放宽指纹保护。`todo_delta` 的首次到期更新同样不在 stopped 上写会改变指纹的事件。

### T1.5 explore

`v13: explore spawn`（`:529`）保持 RAISE。计划门不把它改成成功只读。只读工具子集归 G1 / Phase B，不是改这条 RAISE。本轮未重跑回归。

### T1.6 选择、绑定、monitor 节律

selected_todo：0 或 1 行。`dispatch`：`provider`、`operator`、`none`。`advancement_task` 或 `continuous_monitor` 且 `runnable` → `provider`。`user_gate`/`user_action`/`blocker` 需要人时 → `operator`，驱动器不得为此调用 provider。「需要人」的精确谓词归实现期，这三类不得派到 `provider` 已写明。其余 → `none`。全序：事件序，再 `todo_id` 字节序。should_run 为假时不为它入队 advance。

候选必须属于当前有效计划，见 T1.1。排除：绑定的 effect 未终态；或子会话 status 不在 `completed`/`failed`/`cancelled`；或 effect/子会话已终态，但对应结果尚未由 todo 折叠确认。终态失败不自动回到 `runnable`。从未离开 `runnable` 的 todo，在归档 delta 写入前也不可再选。

归档合同，本轮不实现，但是合同。成功由幂等 `todo_delta` 记到该类的完成态并留下绑定归档。monitor 成功由幂等 `todo_delta` 做 `runnable→waiting` 并写新的非空 `due`。失败确认是既有 verb=`update` 的 `todo_delta`，独立 `apply_id`，不是第五个 verb。quarantine 只是该载荷及其 STABLE 折叠：失败 `effect_id` 加未解除标记。不建表，不加列，不加 status，不加事件种类。同一 delta 若当时仍是 `runnable`，把 status 改为 `blocked`，并写下该载荷。不自动 `dropped`。selector 排除折叠出未解除失败标记的 todo，即使 status 仍是 `runnable`，即使绑定字段被清掉。记录失败本身不是派发许可。普通 `update` 不得绕过：不得把带未解除标记的 todo 改回 `runnable`，也不得单独清标记。re-enable 也不是第五个 verb，而是 `update` 的受限形状：独立 `apply_id`，原子 `blocked→runnable` 并清除标记。`done` 与 `dropped` 无出边，不得用这条形状重开。这些 delta 各自带 `apply_id`，走同键重放 / 异参 RAISE。advance 替换臂调用写者，不得绕过写者直接 INSERT，不得另造第二写者。

**并发窗没有闭合。** fence/lease 只排斥同一 effect 的再次 claim。合同顺序，未实现：T1.3 那一个 selected_todo 臂，在 `:737` 已持有的会话锁内重读 selected_todo，创建或采纳 effect，同一事务经写者写入绑定，提交之后才做外部 IO。不把活体 `v13_advance` 说成今天的唯一入队者。`v13_recover_idle` 是否也入队，本轮未重读，列入 §10。替换写不出且不改 stage 1–29，就停。

到期提升 `waiting→runnable` 是带独立 `apply_id` 的 `todo_delta`，不是只读折叠谓词。全篇按这一读法，不再把它读成折叠桶。走 T1.1。首次写入服从 T1.4：stopped 或终态拒绝、零事件。条件仍是 class 为 `continuous_monitor`、当前 `waiting`、`due` 非空且 `due <=` 调用者时间戳。成功节律是另一条 delta：`runnable→waiting` 加新的非空 `due`。这不删除其它类的 `waiting→dropped|blocked`。非 monitor 的回程动词仍留 §10，本轮不新造。SQL 不睡觉，不把 due 写进 hint。

### T2 C5

两键保持 `:911-912`。选项与截止时间写旁路 `interaction/offered`，同一 `interaction_ref`，至多一条。`offer_kind`：`approval`、`question`。分流。超时不自动写答案。

`skip=true` 是活体 one-of（`:368-372`）。未知键 `:335-336`。非法 skip `:361-362`。它是人工授权动作：operator 的显式 NULL，或直接父的非 NULL，经 6 参 `v13_complete`。不是无人值守权限。驱动器不得以 agent 身份自答。F11 `:80`。不留「若 skip 不存在就 ASK_USER」。

未另行授权时，`human_pending` 且 `should_run=false` 不是卡死，不是完成，不是 terminal，也不是 gate 红。session 保持非终态 `waiting`；human effect 保持待应答，不自动 complete、不自答、不自 skip。授权缺口是「无人值守 skip 尚未获准」，不是「等待本身破损所以必须自动 skip」。`interaction/offered` 也不在指纹排除名单。首次在 stopped 或终态上写这条旁路，与 T1.4 一样拒绝、零写。合法重放不追加事件。

### T3 D18

前沿投影 STABLE、零写、不入队。L24 `:130`：计数器、cap、streak、配额不足只许让 should_run 为假，禁止因此插入 `replan/required`。允许的插入只有计划图语义缺口，每义务至多一条，具名 SQL，锁内重读。advance 不插。哈希句：规范序列化，排除计数器；`responds_to_frontier_hash` 相等且新前沿哈希不同才算回应。本轮不实现。写不出与 L24 的区别就停并 `ASK_USER`。D3 第三类断言排在哈希句之后，此前不得标绿。

### T4 D19

不建 link 表、send 账本（F30 `:99`）。只对已授权 id 做 STABLE 零写折叠。观察者不代答。V11 未核。不挡 Phase 0。函数体行号未重读。

### T5 D20

不建 cadence ACK、新收据、RRULE、scheduler 状态表。节律是驱动器睡眠加已有三值 hint。非 `run_now` 不入队。`run_now` 再判 should_run。due 不进 hint。观测事件默认不建。提案须同时满足非授权、不当门、无 RRULE、无 epoch、无 turn_no、stopped 不插、配额中性，并引用 L21 `:127`、L22 `:128`、L25 `:131`。R3b 行号未核。少一条就维持不建并 `ASK_USER`。

### T6 开工门（加载声明已在 §5，这里不重复成「未做」）

本轮不实现驱动器。T1.4 的 operator-NULL / 直接父只适用于规划写者和相应人工控制。tool/llm complete 使用显式 NULL，另核 SQL EXECUTE 与 attempt/fence，不传会话 UUID，也不因此要求 operator。human complete 才走非 NULL 亲缘。探针用 5 参 complete 只是造前驱，不是生产豁免。children_terminal 行号未重读则不得开工 R1。一库一树仍需要，因为 claim 是全局池，且禁止改 `v13/fanout/v13_fanout.sql`。

### T7 PC-4

本轮不实现 root 配额。不改 `:94-99`。后期形状是新 stage 里的 STABLE 重算，加 should_run 新版本门，不是第二账本。声称 goal 级配额或无人值守多 spawn 预算之前不得开工。席位常数未重读，不写 8 或 64。

## 7. 追溯

建议归属按 §2 的四期，未审核，不是开工许可，不是切片改名。K/R/W/U/M 只是调查主题记号，不分配期次。没有「M 无字母期」。没有「A=Fake、B=真链」。

| 项 | 约束 | 归属（未审核） | 不得声称 |
|---|---|---|---|
| A1 | T1 写者、水位、门序、规划豁免。无计划则根 advancement 不入队 | A | 有过 plan 事件即放行 |
| A2 | 状态机、绑定键、selected_todo。禁止 spawn 当 todo | A | 已有计划层 |
| A3 | 有界读。LIMIT 不是扫描硬顶 | A | 前沿已可读 |
| A4 | 入口零 INSERT。不建 command_receipts | A | ingress 已等于 start-goal |
| B1 | 出口纯函数。闭集本轮不冻结 | A | 心跳已按计划选下一项 |
| B2 | 断言、组装、判断模板、工作流模板分开。真链要消费的组装在首期，不单列成 Fake 期 | A | 一份 SYSTEM_PROMPT 即完成 |
| B3 | 不建 ACK。T5 | A 的不做项；C/D 不得重开 | hint 已被 ACK |
| B4 | 语义缺口 replan。T3。哈希句未实现不得标绿 | C | 停滞治理已有语义前沿 |
| B5 | 写者是 harness。消费且无同源收据就会写。quiet 未证明 | C | 驱动器是收据写者 |
| B6 | 所有权表未交付。T6 是门 | A；C 声称无人值守前也要这张表 | 驱动器只做 IO 已闭合 |
| C1 | 模板数据。隔离证明未退出码 0 前不复用判断模板表 | A | 已有 judgment_templates 即目录已接上 |
| C2 | 标签进策略。explore 保持 RAISE。工具子集是 G1 | 合同 A；子集交付 B | explore 已是成功只读 |
| C3 | 子会话一条指针消息。不改 session_log | A | handoff 收据已是内容水合 |
| C4 | 咨询桥依赖 G2。多 lane 后置 | 首期真链所需在 A；多 lane 在 D | prompt-exports 已是 oracle 桥 |
| C5 | 未授权时合法行为是非终态 waiting。skip 是人工动作，不是解卡许可 | 等待合同约束各期；无人值守 skip 若要做，在 C，且现在未授权 | 问答卡死所以必须自动 skip |
| C6 | 零写观察。不新增授权。V11 未核 | C | auto-wake 已闭合 |
| C7 | SQL 键、驱动器 DTO、provider schema 分开。不把 Fake 映射和真链拆到两期 | A | 剧本 result_kind 等于 provider 输出已接上 |
| D1 | 通知是策略。stopped 上不插。不承诺 exactly-once | C | attention 已是用户通道 |
| D2 | 证据按任务类。无键的既有 complete 保持可用 | C | 子会话齐了还要等 artifact |
| D3 | 用 v13 自己的义务条数。依赖 T3 | C | 哈希句之前把断言标绿 |
| G1 | 工作区工具面。本轮零改动。read_tools 不进 SQL_LOAD_ORDER | B。首期真链必要的 read 接线在 A，不把整个 G1 提前算成已交付 | 已能自由改代码 |
| G2 | 真实 provider 与必要 read。Fake 绿不是产品可用。本次未调用 | A | 第一条真实调用已走通 |
| G3 | 进程监督与通知入口。人守终端不得宣称无人值守已通 | C | 有循环即有运营接线 |
| G4 | 续租、不确定窗口、PC-4、公平与 soak。T7 未实现 | 单 goal 续租与配额声称在 C；公平、饥饿、多日 soak 在 D | session-local 配额就是 goal 级；20 项写完即可跨天 |

24/24 都在 A–D 内。依赖只表示先后。

## 8. Phase 0 验收

任务：文档层已接受。父复跑最终证据后再决定提交。停止。不开 A。

本期 gate 只是隔离探针，不是 `v13/<stage>/test_*.py`。退出码 0。结果以 §4.6 与证据文档为准。`git diff --stat -- v13` 必须为空。

允许将来声称的只有：文档与技术裁决被接受。禁止声称阶段已绿、产品可用、A–D 已审核、后期 gate 已跑、绑定窗已闭合、加载声明等于库已建成。

本轮不追加 `SQL_LOAD_ORDER`。N 仍是 29。后期 stage 的测试、1..N 回归、矩阵、台账、README 五样都不更新。路径本轮不编。

## 9. 未审核占位

四段都未审核、不得开工、不是裁决。调查切片不得改名为这些期。

**计划，未跑，未通过。** 后期确定性 stage gate 计划使用 `UV_FROZEN=1 uv run python v13/<stage>/test_<name>.py`，退出码 0。真实 provider 验收独立且须另行授权。Fake 绿不是产品可用。本轮没跑这些命令。

下面这些也是计划，未跑，未通过，只放在这里：无当前计划时新 selected_todo 臂不制造新 effect，其它臂仍可用；控制动词在原成功条件下仍可用；finish 在调用前 should_run 为假时仍结算并写收据；两次 `plan_commit` 中间插入用户消息后，旧计划的 todo 不可被 selected，除非新计划显式 reuse；合法重放在随后 stop 之后仍返回原 `plan_id`/`todo_id` 且零写；旧计划已绑定 effect 后，新计划 reuse 同一 `todo_id`，折叠仍看见旧绑定，不重置 status；`done`/`dropped` 与 monitor 的旧 `due` 在 reuse 后仍在；失败归档后、受限 `update` 清除标记之前不可再选；已 stopped 的根上，snap 缺 `failed`、`failed` 为 JSON null、`failed=false`、`failed=true` 的计划测试：缺失与 JSON null 不因本禁令被拒，`IS NOT NULL` 的输入不写 `resolve/failed`、不破坏这次调用之后的 resume 指纹（驱动器纪律，非 advance 自检；T0）。这些都是计划，未跑，未通过。

### Phase A

控制链，并且首期就包含真链，含 G2 与该真链必要的 read 接线。不是 Fake-only 期。

### Phase B

工具执行 G1。首期已经声明的 read 注册不在这里再算成另一期。

### Phase C

单 goal 无人值守。未授权的 human waiting 不是本期必须用 skip 修掉的破损。

### Phase D

多 goal 公平、并发帽、soak。原调查带 M 在这一期里面，不是第五期。

## 10. 未决开工门

不是通过：产品库名；`route_policy_version` 绑定；首次 parse 前的 override 或已审核 triage pass；产品角色与 stannum GRANT 核验；`canonical` 生成算法与 reuse 文本哈希算法（相等运算符已定为 jsonb 相等）；已 stopped 的根上，顶层 `p_snap->>'failed' IS NOT NULL` 不得再调用 advance；锁内重验尚未实现，不声称旧实现已安全；T1.3/T1.6 那一份 `CREATE OR REPLACE v13_advance` 尚未写出，且不得把计划门插进 §T1.3 点名的活体臂；`v13_recover_idle` 是否入队未重读；非 monitor 的 `waiting→runnable` 回程动词未新造；children_terminal 行号；用户消息/steer 种类字面；B1 出口闭集；事件种类闭集校验；迟到 complete 的重放行号；规划写者未实现；PC-4 未实现；一库多 goal 的领用查询未写出；真实 provider 未授权；A–D 未审核。`e915e92` 落后 origin/main 14 是快进前的历史基线，不再是开工门。

V11、席位常数、result_kind 四值字面、矩阵路径：后期再核，本轮不编。

第一刀必读是本计划与证据文档里的复现块，加上 §4 已核行。路线图路径是 `docs/plans/v13-layered-control-roadmap-2026-09-26.md`，行号见 §4.5。忽略的探针脚本不是必读。调查不提交，也不是干净克隆必读。

## 11. 提交边界

文档层已接受。收尾当时尚未提交是历史。本里程碑路径级 add 只有本计划与证据文档。禁止 add 探针、日志、`prompt-exports/`、`uv.lock`、父 memory、调查、stage 1–29。禁止 `git add -A`、force、`reset --hard`、自动 stash、跳 hook。调查若要进仓库，由父另决，不是本轮目标。无法安全同步就停。

## 12. 本轮关闭

| 父项 | 落点 |
|---|---|
| 四期范围；M 不游离；A 不是 Fake | §2、§7、§9 |
| 单库加载；DML 形状已核，路由绑定与 GRANT 未闭合 | §5、§10 |
| 根流、apply_id 载荷、重放先于停复、旧 todo 不可选 | T1.1、T1.2 |
| 绑定窗未闭合；归档 delta 走 T1.1；不是第二写者 | T1.6、§10 |
| 根规划非 NULL 恒拒；不套 tool/llm complete | T1.4、T6 |
| 计划门是未来新臂，不占用活体 CASE | T1.3、§10 |
| monitor 初态、到期 delta、成功回 waiting、失败 quarantine | T1.1、T1.6 |
| 已 stopped 根上禁止 `p_snap->>'failed' IS NOT NULL`；quarantine 只是 update 载荷 | T0、T1.6、§10 |
| 证据自包含；退出条件加强后重跑 | 证据文档；§4.6 |
| 行号；用户决定与技术裁决分开；waiting 不是终态 | §4、§2、T2 |
| 忽略文件与调查不是干净克隆必读；不提交调查 | §3、§10、§11 |

## 13. 最终审核记录

2026-09-28 三路接受的是文档与技术裁决，不是运行时。group `5929D334-42BD-4DA0-A6F0-A224B81E65B4`。chats：`new-chat-152BFF`、`new-chat-oracle-2-2CAAE1`、`new-chat-oracle-3-457866`。三路都是 P0=0、P1=0。P2 计数分别为 0、1、2。主-pair 互动 session：`224B0560-B94A-4BC8-BDD7-9D795FF75677`。导出路径只是本地溯源，接受不依赖打开它或任何 gitignore 文件。

文档接受收尾当时尚未提交、尚未推送。那是当时状态，不是本里程碑完成后的现状。

父最终复跑：`UV_FROZEN=1 uv run python prompt-exports/v13-long-loop-p0-advance-receipt-probe.py`，退出码 0。脚本输出 16 条 PASS，`PROBE_OK True`，`BASELINE_MISSING []`，`BASELINE_EXTRA []`，`agent_v13_govern` 前后 effects 1 / events 14 / sessions 7。本地佐证日志 `prompt-exports/v13-long-loop-p0-parent-verification.log`，不是必读。

未做：产品 SQL/Python、A–D、真实 provider、全部 stage gate。

已勘误的 P2：§9 后期命令改为 `UV_FROZEN=1`；stopped 测试注明驱动器纪律、非 advance 自检；终态先返回经核对是 `:754-756`，不是 `:739-741`。

历史基线：HEAD `e915e92` 落后 `origin/main` 14。快进后基线是 `9177ab5`，与 `origin/main` 一致。incoming 37 个路径是 `.gitignore`、两份 pi review、`v13/pi_parity/`、`v13/pi_ports/`。没有改 `v13/load.py`，也没有改 stage 1–29 既有 SQL。这不是全部 stage gate 已重跑。`uv.lock` 本地修改保留，hash-object `c1f6c0068bbb6174947d3337bcc72dfc546406bd`。
