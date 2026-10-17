# v13 Stage 40 `ce_run`

## 状态与范围

**状态更新（2026-10-17）：下述阻塞已被 v99 预提交全绿覆盖（见「47 条全量回归与 goal_supervisor 探针」节），历史状态保留如下、不抹去。** 当时工作树经逐文件 SHA-256 比对复制至隔离 workspace/PGDATA（基线 `7db352643e16d777721a278b3977d8b6f686eb1b`），按完整 47 条清单顺序执行：前 7 条 exit 0，其中 CE 为 16/16 组、665 检查；第 8 条 economy 在 H1 `out_a == 'accepted'` 断言 exit 1，余下 39 条及 goal_supervisor 三种命令未运行。先前独立诊断在 H1 观察器的错误函数签名查询处失败，未保存真实 receipt；随后一次有界隔离复测 exit 0/ALL PASS，H1 `out_a=accepted`，立即捕获的 claim receipt 属 G2 judge effect 而非 H1 目标，H1 最终 succeeded，因而全局 claim 选择线索不能解释最初红灯，根因仍未明。两次诊断分别见 `prompt-exports/w4-economy-h1-reproduction-2-20261017.log` 与 `prompt-exports/w4-economy-h1-root-cause-20261017.md`。只读检查确认 PG 18.4/Stannum 0.4.0；未改冻结源码/CE/授权代码。精确命令等价性、哈希、原始输出、进程结论和最小后续诊断见 `prompt-exports/w4-economy-h1-handoff-20261017.md`；完整结果在 `prompt-exports/w4-final-precommit-20261017/`。停止全部后续 gate，无暂存/提交/推送，未达到 all47-green + docs-ready/集成 Oracle 审核边界。

本目录是 Stage 40 CE 六动词原生控制面的文档入口：`start`、`poll`、`wait`、`cancel`、`steer`、`respond`。它描述专用临时数据库中的 Fake 验证宿主，不是 CE 产品、agent_manage、生产多 worker 接管或真实 provider 运行时。W1/W2 已完成，W3 已定向实库交接。以下为历史记录：有效的 2026-10-17 round 7 独立 gate 在正确 wake 期望 `[1,1,1,2]` 下 exit 0、16/16 组、517 断言；另一次历史完整顺序回归在第 11 条 fair_driver 冻结字节检查 exit 1 后停止，前 10 条实际 exit 0，其中 CE 使用错误 wake 期望，不能计为有效验收，剩余 36 条未运行。Stage 40 未完成。

Stage 40 采用 P1 收口：旧 Stage 40–44 与 controller thin cut 已退役，不保留旧 #86–#91 作为新实现证据。`run_id=session_id` 是 headless 身份；active steer 是同 epoch 的 queued follow-up，不承诺中断正在执行的 provider；terminal steer 才开新 epoch。单个 run 由一个 CE driver 推进，不能同时由 LoopDriver/RealChain/GoalSupervisor 驱动。

**证据口径勘误（2026-10-17）：** `665` 是 runtime-review 修正完成后、最近一次 static guard edits 之前的后续隔离证据（CE 16/16；全量清单第 8 条 economy H1 停止），不是里程碑或 all47 通过。其后独立 economy 复测 exit 0 仅证明该单项在另一隔离运行中通过，不能补算或替代已中止的 47 条序列。有效 round 7 的 `517` 断言及其逐组计数使用了正确 wake 期望 `[1,1,1,2]`，属于独立历史证据；第 5/6 轮及此前顺序回归中的 CE 运行使用错误 `[1,1,2,3]`，属于无效历史结果。二者不能合并或相互替代。此前另一轮完整清单在第 11 条 `fair_driver` 停止，也保留为历史；后续隔离回归在第 8 条 economy 停止，二者不是同一次运行。

## 数据与入口契约

SQL 持久化五表：`v13_ce_runs`、`v13_ce_epochs`、`v13_ce_operations`、`v13_ce_snapshots`、`v13_ce_wakes`。operations 是可变账本，wakes/events 是追加历史；本阶段不提供 TTL/GC。保留的 registration/owner generation、continuity、related_follow_up/unrelated、expired/superseded 字段没有六动词 producer，不把夹具覆盖写成运行时能力。

入口总数为 12：九个核心 SQL 入口、`v13_ce_discover_work`/`v13_ce_claim_effect` 两个 scoped 宿主入口，以及额外受限维护入口 `v13_ce_requeue_stale()`；仍只有六个控制动词。所有入口都先做真实 caller/actor 授权、request_id/digest 重放判定，再按 `sessions -> ce_runs -> epoch -> operation -> effect` 锁序。poll/wait/discovery 纯读；wait_check/ce_wait 的返回是唯一八键闭集 `schema_version/reason/snapshot/registration_generation/epoch_ordinal/continuity_generation/interaction/wake_id`，不添加 `ok`。

### start 身份、caller 与 cutoff

root start 要求真实 operator；child start 在父 session 锁内取 `next_seq - 1` 作为包含上界，父 `next_seq=0` 零写返回 `parent_prefix_empty`。start 生成新的 session UUID，并在同一事务建立 session、run、initial epoch、start operation、user/message 事件和 ready LLM effect。唯一私有 `v13_ce_insert_session(uuid,uuid,bigint) RETURNS uuid` 是 `v13_spawn_owner` 持有的 SECURITY DEFINER bridge，只做单行 INSERT/RETURNING；它不做授权、不做父锁、不替代既有 trigger。setup 必须验证 owner/ACL、helper 直调 42501、宿主不可 SET ROLE 到 owner，且超级用户直接 INSERT 仍受 sessions owner trigger 拒绝。真实外部 caller 由专用 helper 读取 `SET ROLE` 后的 `current_setting('role')`（否则 `session_user`），不能使用 definer 的 `current_user`。

### wait、steer、cancel 与续接

wait 优先级为 steering wake > actionable snapshot > epoch advanced > waiting/timeout；每个 waiter 自带 `after_wake_id`，不同 waiter 各自可看到一次，不能描述为 CE 全局消费。self-origin 只隐藏 `snapshot.steering_message` 正文，仍返回 interrupted 与 wake 游标。active steer 不换 epoch，写入 queued operation 并用 driving token 阻止旧发布；旧 ready/claimed driving effect 仍可完成并记账，但发布归档为 superseded history。cancel 只取消目标 run，同步 CE/session 状态，不递归取消子 run：本 session 的 `sessions` 状态变为 `cancelled`，追加严格格式的 `session/cancelled` 事件并消费严格格式的 `cancel/requested`；真实 actor/request 审计由独立 CE 审计事件持久化，避免 terminal steer 恢复 ready 后旧取消墙重现。这是 CE/session 控制结算，不终止事务外的 claimed provider；迟到 receipt 按原 tokens 结算或返回 stale/unknown，不复活 cancelled run。正常 T2 必须把 receipt、后继 admit/promotion 和 publish 在同一个事务提交，禁止 accept 已提交而 continuation 另行提交。

### 工具、输入与 IO 边界

工具 schema 是私有固定闭集，不读取 `tools.param_spec` 作为参数 schema；本阶段只允许 `spawn_subsession` 的 draft-07 `{task: string}`、长度 1–1024、`additionalProperties=false`。Fake adapter 返回 `adapter=ce-fake-spawn, simulated=true`，不调用原生 spawn handler、不创建子 session；CE child 只能由 `start(parent)` 建立。被 steer 取代且未准入工具 operation 的旧 `tool_calls` 只在派生 Fake 输入中转换为 `superseded` 普通历史文本，不伪造 tool result；已准入工具仍按 effect 账本结算。

T1 admit/claim COMMIT 后连接必须 IDLE，事务外执行 Fake LLM/Tool IO，T2 才 accept/续接/publish COMMIT。每 run 单 CE driver；每轮在独立短事务调用 route-only 的 `v13_ce_requeue_stale()`，它仅委托未修改的 `public.v13_requeue_stale()`，返回 `{schema_version:1,ok:true,recovery:<原计数json>}`，作用域是**全库**而非目标 run，不写 CE snapshot/revision/wake。真实 route 直调冻结 invoker 会因 pgmq schema USAGE 失败，故不得绕过包装；ce_wait 不做回收。claim 是 scoped 的，不能调用全局 `v13_claim` 抢走别的 run；unknown 没有 CE 恢复入口，任何 enqueue/promotion 继续拒绝。真实 provider、socket、pg_sleep、网络均不在 gate 内。

### 专用数据库与权限

setup 先加载 Stage 39，再收回宿主/继承角色的数据库 `TEMPORARY` 与 `public` schema `CREATE`，记录 before，局部加载 ce_run SQL 一次，记录 after。CE SECURITY DEFINER owner 固定为受信超级用户且满足既有 `v13_control_operator()`；宿主使用非超级用户 `v13_route`，recall 只覆盖读等待正例，不授 CE 表裸读写。数据库/schema 收权是专用库部署前提，不泛化到其他 stage 库，也不防恶意库属主或超级用户。

## 16 组具名探针（有效 round 7 历史证据）

2026-10-17 `UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py` 第 7 轮独立运行 exit 0，16/16 组、517 断言，零独立用例失败；该轮已使用正确 wake 期望 `[1,1,1,2]`，不是“修正前 wake 期望”。它是独立历史证据，不能覆盖后续 runtime-review 后、static guard edits 前的 665 检查结果。其 active wake=current epoch、reactivation wake=OLD epoch，跨 epoch 期望严格为 `[1,1,1,2]`。此前第 5/6 轮与顺序回归中的 CE 运行采用了错误的 `[1,1,2,3]`，虽保留其原始退出码/输出，但不作为契约验收，不能追认或补算进回归序列。`test_ce_run.py` 已覆盖计划既定的 16 组具名探针：1 `native_load_untouched`；2 `native_plan_arm_closed_set`；3 `native_frozen_driver_bytes`；4 `native_start_identity`；5 `native_poll_pure`；6 `native_wait_cursor`；7 `native_cancel_scope`；8 `native_steer_paths`；9 `native_respond_once`；10 `native_acl_roles`（含 maintenance route-only/非超级用户 ACL）；11 `native_io_boundary`（含 maintenance 全库短事务）；12 `native_receipt_fences`；13 `native_unknown_vs_archive`（含维护回收后的 unknown 墙）；14 `native_operation_handoff`；15 `native_snapshot_once`；16 `native_static_setup`。后随的逐组计数 `48/3/3/48/7/37/16/31/36/90/23/34/31/66/26/18` 仅属于这次 517 断言的历史分解，不是最新 665 计数。覆盖包括第二连接提交可见、真实锁屏障、原子 T2 崩溃/丢 COMMIT 响应重放、真实租约回收 unknown、自 wake 正文隐藏与跨 epoch 游标；continuity superseded 仅为明确 reserved 夹具，不宣称六动词 producer。

## 历史 47 条回归命令与结果（第 11 条停止）

2026-10-17 重新枚举 `v13/**/test_*.py` 恰好 47 条，与下列历史清单一致。该清单在第 11 条 fair_driver 首次非零后停止，余下 36 条 `not_run`；它不是当前运行状态。后续隔离回归另在第 8 条 economy H1 停止，余下 39 条及 goal_supervisor 命令未运行。数值为脚本自报检查数；未自报总数的脚本标明实际输出的 PASS 行数。其中 CE 行明确保留错误期望运行的历史结果；第 7 轮正确期望的独立通过不替代回归重跑。完整命令、退出码、摘要及历史红灯见忽略工件 `prompt-exports/w4-ce-run-actual-results-2026-10-17.md`；不能把这次部分回归写成 47 条通过。

```text
UV_FROZEN=1 uv run python v13/acl/test_acl.py                         # exit 0; 197 checks
UV_FROZEN=1 uv run python v13/attention/test_attention.py             # exit 0; 156 checks
UV_FROZEN=1 uv run python v13/catalog/test_catalog.py                 # exit 0; 128 emitted PASS lines
UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py                   # historical sequence row: exit 0; 517; WRONG wake expectation (invalid for that sequence)
UV_FROZEN=1 uv run python v13/characterize/test_characterize.py       # exit 0; 144 emitted PASS lines
UV_FROZEN=1 uv run python v13/chunks/test_chunks.py                   # exit 0; 298 emitted PASS lines
UV_FROZEN=1 uv run python v13/control/test_control.py                 # exit 0; 93 emitted PASS lines
UV_FROZEN=1 uv run python v13/economy/test_economy.py                 # exit 0; 238 emitted PASS lines
UV_FROZEN=1 uv run python v13/envelope/test_envelope.py               # exit 0; 395 emitted PASS lines
UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py           # exit 0; 136 checks (script total)
UV_FROZEN=1 uv run python v13/fair_driver/test_fair_driver.py         # historical exit 1; stage_bytes (78432, 926); 1 attempted, 0 passed; STOP
UV_FROZEN=1 uv run python v13/fanout/test_fanout.py                   # not_run
UV_FROZEN=1 uv run python v13/filter/test_filter.py                   # not_run
UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py       # not_run
UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py   # not_run
UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py # not_run
UV_FROZEN=1 uv run python v13/govern/test_govern.py                   # not_run
UV_FROZEN=1 uv run python v13/handoff/test_handoff.py                 # not_run
UV_FROZEN=1 uv run python v13/loop/test_loop.py                       # not_run
UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py         # not_run (stopped at fair_driver; prior historical exit 1)
UV_FROZEN=1 uv run python v13/manifest/test_manifest.py               # not_run
UV_FROZEN=1 uv run python v13/memory/test_memory.py                   # not_run
UV_FROZEN=1 uv run python v13/mgraph/test_mgraph.py                   # not_run
UV_FROZEN=1 uv run python v13/mgraph/test_stannum_usage.py             # not_run
UV_FROZEN=1 uv run python v13/mgraph_assembly/test_mgraph_assembly.py # not_run
UV_FROZEN=1 uv run python v13/observe/test_observe.py                 # not_run
UV_FROZEN=1 uv run python v13/periphery/test_periphery.py              # not_run
UV_FROZEN=1 uv run python v13/pi_parity/test_pi_parity.py              # not_run
UV_FROZEN=1 uv run python v13/pi_ports/test_pi_ports.py                # not_run
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py               # not_run (stopped at fair_driver; prior historical exit 1)
UV_FROZEN=1 uv run python v13/plan_contract/test_plan_contract.py     # not_run
UV_FROZEN=1 uv run python v13/plan_read/test_plan_read.py             # not_run
UV_FROZEN=1 uv run python v13/quota_window/test_quota_window.py       # not_run
UV_FROZEN=1 uv run python v13/read_tools/test_read_tools.py           # not_run
UV_FROZEN=1 uv run python v13/real_chain/test_real_chain.py           # not_run
UV_FROZEN=1 uv run python v13/recall/test_recall.py                   # not_run
UV_FROZEN=1 uv run python v13/resolve/test_resolve.py                 # not_run
UV_FROZEN=1 uv run python v13/schema/test_schema.py                   # not_run
UV_FROZEN=1 uv run python v13/seam/test_seam.py                       # not_run
UV_FROZEN=1 uv run python v13/should_run/test_should_run.py           # not_run
UV_FROZEN=1 uv run python v13/spawn/test_spawn.py                     # not_run (stopped at fair_driver; prior W1/W2 exit 0)
UV_FROZEN=1 uv run python v13/summary/test_summary.py                 # not_run
UV_FROZEN=1 uv run python v13/triage/test_triage.py                   # not_run
UV_FROZEN=1 uv run python v13/twophase/test_twophase.py               # not_run (stopped at fair_driver; prior W1/W2 exit 0)
UV_FROZEN=1 uv run python v13/workflow_bind/test_workflow_bind.py     # not_run
UV_FROZEN=1 uv run python v13/workspace_admit/test_workspace_admit.py # not_run
UV_FROZEN=1 uv run python v13/workspace_exec/test_workspace_exec.py   # not_run
```

W1/W2 的准确证据：独立保护文件/函数闭集审计通过；spawn、acl、twophase 实跑 exit 0；fair_claim 定向 29 检查与 18 个函数哈希通过；setup 生命周期抽查具备 name/OID、四类 LOGIN 角色 OID、before/after、早期失败回滚与 cleanup 异常保留证据。这些早期证据不替代后续验证；上述完整回归清单是历史记录，并非当前运行状态。当前预期是 52 条旧脚本减 6 条退役、加 1 条 ce_run，共 47 条；不得以失败过滤缩小最终集合。

## 47 条全量回归与 goal_supervisor 探针（2026-10-17，v99 预提交全绿）

按用户对 FDFAED98 协调线的收尾指令，Stage 40 收尾在 `v99` worktree 续跑：主检出当前工作树（含 §10.9–§10.11 修正）的 272 个冻结集文件（`v13/**` + 计划 + 矩阵 + 台账）逐文件 SHA-256 核对后 port 进 v99；依赖输入 `v13/pi_ports/node_modules`、`v13/read_tools/.duck-venv` 以真实拷贝落地（被 committed .gitignore 原样忽略）；PGDATA 由被证明过的 pinned pgembed 785aa58（隔离 prefix，PG 18.4 + Stannum 0.4.0）全新 initdb（`--no-locale -E UTF8`，conf 显式 `extension_control_path`/`dynamic_library_path` 指向隔离 prefix）；node v24.13.1、go 1.24.5、swift 6.3.2 全部在场。顺序 runner（`prompt-exports/w4-v99-runner.py`）逐条独立执行、每条后精确恢复 `v13/pi_parity/traces/pg.jsonl`，首个无效即停。

两次被保留的阻断尝试：attempt-01 停在 #30 pi_parity——当日 12:54:56 `/Users/wxl/Projects/PiSwift` 被 `git pull` 自 bfccb32（2026-09-27，v13 冻结 driver 的合同基线）快进到 0f44e03，`createAgentSession` 变 `async throws`、`toolExecutionEnd` 四元组变五元组，全新构建编译失败；主检出同晨绿证据均在 pull 之前且其缓存已被作废。经用户裁决回滚 PiSwift 至 bfccb32（detached，原分支指针保留 0f44e03），driver 适配新 API 不并入本里程碑、留作独立后续变更。attempt-02 停在 #36 read_tools——`~/.duckdb/extensions/v1.5.5/osx_arm64` 钉版扩展缓存从未落地，duck/ring 面按 skip 语义 exit 2；随后实跑被批准的 `v13/read_tools/duck_bringup.py`（INSTALL FROM community，sha256 钉版校验通过、loaded=true）。证据：`prompt-exports/w4-v99-attempt01-piswift-0f44e03/`、`prompt-exports/w4-v99-attempt02-duck-absent/`。

最终序列 49 项全部有效：47 条脚本 exit 0（逐条真实退出码/耗时/日志见 `prompt-exports/w4-v99-precommit-20261017/results.json`；CE 为 16/16 组、665 检查、零独立失败；read_tools 首次真跑 duck 面与 E4 嵌套全量并含每条后 trace 恢复）；`--unattended-continuation` 探针 exit 1 且以既有 ask_user 拒绝尾部收尾；`bad-args` 探针 exit 2 且在任何建库前仅打印 usage。economy H1 根因仍未建立；v99 三次序列内该断言均绿，历史红灯不作追认。提交后按计划 §8.1.6 以同一 49 项清单净树复验并推送。

## 交付边界

## 冻结边界独立审计

`prompt-exports/v13-ce-freeze-audit-2026-10-17.md` 的独立只读审计（未运行数据库 gate、未编辑代码）确认：`test_plan_arm.py` 顶层非函数语句 23 条逐条字节相等；39 个既有受保护函数体全等；`run()` 内 `r0_direct_cases`、`r0_preceding_walls`、`r0_quota_boundary` 三行来自既有 `a2cabf1`，不是本次改动；driver 剥离 R1 sentinel 后与 base 全等；`load.py` 为纯尾追加；phase_d 39 个 SQL 零失配。该审计本身不等于数据库 gate 通过；“维护包装已由新 gate 第 10/11/13 组实测通过”是 runtime-review 后、static guard edits 前的历史 665 证据，不能转述为当前 gate 或 47 条回归通过。
本 README 记录 Stage 40 的设计范围、偏差和实际证据。2026-10-17 dirty-tree amendment 仅修改冻结 validator/具名 guard body：精确排除已命名 guard 文件，body-only 比较保留签名、decorator、module/comment bytes，并用 comment/function 负例证明边界；`protected_dirty` 的放行仅为让 parity/ports/read-tools 互相识别这四个具名 guard 文件，不放宽业务断言或任意路径。四个 body pin 与 git commit/parent 证据详见计划 §10.8。最终 legacy 日志在 `prompt-exports/stage40-final-*.log`；goal_supervisor 的 74-check trailing `ask_user` exit 1 是原有 documented behavior，pi_ports/read_tools exit 2 是 toolchain skip semantics。此前“CE gate 未在独立 runtime review 期间重跑，待 SQL/test 修正后运行一次”是 runtime-review 期间的历史状态；665 证据已记录该轮后续结果，不能把这段历史待办写成当前 gate 或 all47 结论。2026-10-17 v99 预提交 47 条全量回归与两探针已全绿（见「47 条全量回归与 goal_supervisor 探针」节）；提交后净树复验与推送按计划 §8.1.6 执行。
