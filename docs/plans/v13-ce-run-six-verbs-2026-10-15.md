# v13 Stage 40 `ce_run`：CE 六动词原生控制与冗余清理开发计划

| 项 | 值 |
|---|---|
| 日期 | 2026-10-15 |
| 状态 | 2026-10-17 v99 预提交全绿（见 §2.4）：47 条保留脚本 + goal_supervisor 两探针全绿；集成静态 Oracle review 无 P0/P1 阻断；待 §8.1.5 人工核对后按路径提交、同清单净树复验、推送。此前 W4 阻塞历史见 §2.2/§2.3，不抹去 |
| 架构 | 方案 B：PL/pgSQL CE 控制表 + 既有 v13 effect 账本 |
| 清理裁决 | P1：退役 Stage 40–44 与 controller 薄切共 22 文件，以 Stage 40 ce_run 收口 |
| 评审依据 | `docs/reviews/v13-ce-run-six-verbs-plan-critique-2026-10-15.md`，逐项处置见 §10 |
| 修订后复核 | 2026-10-16 窄范围复审的 Codex 与附加 Oracle 均正常返回，确认三个 P1；已综合修订，见 §10.4。修订后尚未复审，不标记计划审核通过；尚未运行实现 gate |
| 提交信息 | `v13: replace post-phase-d control stubs with native ce_run six-verb stage` |

## 1. Goal & Summary

在 v13 agent-loop 的 sessions/events/effects 上实现 start/poll/wait/cancel/steer/respond，数据库负责准入、围栏、结算与快照，Python 仅负责提交后的 Fake IO 和等待。保留 Stage 1–39 的受保护业务字节，不重写 v13_advance，不删除单活跃 effect 索引。删除过渡入口，新增 `v13/ce_run/{v13_ce_run.sql,setup_db.py,test_ce_run.py,README.md}` 四文件。

本计划不是 CE 全产品移植：run_id=session_id 采用 headless 身份，六动词语义参照 app 路径；active steer 使用串行 queued follow-up，不承诺中断 provider；waiter 自携 wake 游标，与 CE 全局一次消费存在差异。真实 provider、agent_manage、工作流、生产多 worker 接管不在本里程碑。

## 2. Execution Index

**唯一交付里程碑是 Stage 40 ce_run。** W1–W4 是同一里程碑内部工作包，不各自提交；删除旧代码但新入口不可用的中间态不是完成。所有核心及保留 v13 回归门禁绿、工件更新后一次提交、净树复验、立即推送，不积压下个里程碑。

| 工作包 | 内容 | 完成条件 | 依赖 |
|---|---|---|---|
| W1 | 确认删除依赖，退役 22 文件，恢复 driver 哨兵外基线，更新 load | 删除清单精确；Stage 1–39 字节不变；load 尾部 fair_claim/39 + ce_run/40 | 无 |
| W2 | plan_arm/fair_claim 冻结门禁适配 | 脏树/净树均验证白名单与反例，不靠提前暂存通过测试 | W1 |
| W3 | 五表、九个核心入口、scoped discovery/claim 与私有辅助函数、setup | 装载、权限、身份/锁序/结算/交接契约可测试 | W1/W2 |
| W4 | 薄 Worker/Wait、16 组具名探针、README/矩阵/台账 | §8 核心及全部保留 v13 gate 全绿，收尾工件真实记录，提交/净树复验/推送 | W3 |

### 2.1 实施进度（2026-10-17）

以下为实施记录，不改变 W1–W4 同属唯一 Stage 40 里程碑的提交边界。

- [x] W1/W2：精确退役 22 文件、loader 收敛至 fair_claim/39 → ce_run/40、driver 哨兵外恢复 base；冻结闭集与精确退役负例已适配。独立审计 223 个非豁免受保护文件及函数/模块闭集通过；spawn/acl/twophase 实跑 exit 0，fair_claim 定向 29 检查与 18 函数哈希通过。完整 loop_driver/fair_claim/plan_arm 仍因 ce_run 四文件缺失 exit 1，ce_run 缺失 exit 2，不称整体 gate 通过。52−6+1=47 完整预期清单与实际命令结果见 v13/loop_driver/README.md。
- [x] W3：CE SQL 与专用库 setup 已完成实现及定向实库交接，完整 gate 由 W4 验证，不能据此声称 Stage 40 完成。最终 setup 装载/ACL/delta、runtime smoke 均 exit 0；已实测 child cutoff、human respond、CE instruction steer、固定八键 wait、tool admission/promotion、cancel→steer→LLM→tool→next_turn→terminal、claimed cancel 迟到真实结算及不复活快照。receipt 有明确 replay 标志；已知 tool_calls shape 返回 bridge_rejected，effect 保持 claimed、operation archived，审计第二连接可见；独特未知 P0001 故障注入原样传播并回滚，fixture 已清理。setup 公开 name/OID、四类唯一 LOGIN/role OID、before/after；早期创建失败、角色事务回滚、cleanup 异常保留及合法 owner ACL/非owner 拒绝实测通过。§10.5/10.6 接缝裁决已接入。
- [ ] W4：Fake Worker/Wait 与完整 16 组具名探针已实现，import-safe、真实非超级用户宿主、第二连接提交证据、显式锁屏障及真实租约 unknown 均接入。2026-10-17 第 7 轮 `UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py` exit 0，16/16 组、517 断言，零独立用例失败；严格采用 §4.2.3/§4.2.5 的 reactivation 旧 epoch 期望 `[1,1,1,2]`。W4 曾错误改为 `[1,1,2,3]`，故第 5/6 轮及顺序回归 CE 行虽保留原始退出码，也不计有效验收；历史解释已在独立实跑记录纠正，未回填或追认通过。
- [ ] W4 完整回归仍阻塞：重新枚举恰好 47 条并顺序独立执行，前 10 条实际 exit 0（其中 CE 为上述错误期望历史运行），第 11 条 `UV_FROZEN=1 uv run python v13/fair_driver/test_fair_driver.py` exit 1，`test_stage_bytes:222` 输出 `(78432, 926)`，DB setup 前停止；第 12–47 条全部未运行。其 STAGE_PATHS/load.py 相对 HEAD 全空检查与 P1 退役/冻结适配/文档脏树冲突，协调者另行处理；不修改冻结测试、不跳过、不暂存/提交绕过。README/矩阵/台账已按真实部分结果更新，完整命令/检查摘要/精确 diff 路径和历史红灯见 `prompt-exports/w4-ce-run-actual-results-2026-10-17.md`。本轮只跑第 7 轮新 gate，不恢复 47 条回归；W4/里程碑、提交后复验、推送均未完成。
- [ ] 集成审查、按路径提交、提交后同一完整 gate 清单复验、推送。

### 2.2 接续验证记录（2026-10-17；覆盖 §2.1 的旧状态，不抹去历史失败）

- CE 独立运行时审查发现的 instruction promotion、interaction id/kind、NULL expected_epoch CAS、respond one-of 与 reactivation failure 字段五项已修正。`prompt-exports/v13-ce-run-review-fixes-2026-10-17-final.log` 记录 `UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py`：exit 0、16/16 组、665 断言、零独立失败；它不是后续 guard 修改后的最终全量证据。
- `prompt-exports/v13-stage40-regression-manifest.log` 记录首次全量 47 条均实际执行，41 条 exit 0；goal_supervisor、mgraph/test_stannum_usage、pi_ports、plan_arm、read_tools、workspace_admit 六条 exit 1。日志和历史失败原样保留，不追认全绿。
- goal_supervisor 的授权范围内契约分层已静态实现，真实运行待验证，见 §10.9；`accept_unattended.py` 不变。
- parity trace 在子测试间未恢复导致冻结 gate 污染；批准 §10.10 精确编排修正，尚待实现和实跑验证。
- Stannum 共享环境 0.5.1 与冻结 0.4.0 断言不符；正在调查隔离 prefix/数据目录方案，不改断言、不降级共享安装。Node/Duck 前置依赖已完成安装/校验，不等于测试通过。
- 此前 final-tree complete47 attempt 在 #8 实际 exit 1；后续 economy 隔离复测通过但不补算该序列。须从 #1 重新执行全部 47 条，若全绿再完成最终文档/集成审查；提交后同清单净树复验与 push 尚未开始。禁止在这些条件未满足时提交/推送。

### 2.3 W4 最终树隔离回归与 economy 阻塞（2026-10-17）

- 已读 AGENTS/计划及既有 Stannum/trace handoff；93798/80310 的 OS PID 均不存在，runner session 均 Unknown process id，开跑前无其他 v13 gate/PG 进程，团队仅当前 agent。仅能确认不再运行，无法追认两个旧命令的退出码。
- 使用已证明的 pinned pgembed 785aa58 + Stannum 0.4.0 prefix、新 workspace/PGDATA；保留 Git HEAD `7db352643e16d777721a278b3977d8b6f686eb1b`，覆盖实际工作树并逐文件核对 SHA-256，不是仅 archive HEAD。每条实际命令、退出码、完整输出、47 路径清单、冻结哈希和原始 patch 保存在 `prompt-exports/w4-final-precommit-20261017/`。额外 no-sync/project/PYTHONPATH 参数及 initdb/GUC 的精确等价性见 `prompt-exports/w4-economy-h1-handoff-20261017.md`；共享 prefix/PGDATA 未降级或写入。
- ACL/attention/catalog/CE/characterize/chunks/control 七条 exit 0；CE 16/16 组、665 检查。第 8 条 economy H1 `test_economy.py:1700` 期望 `out_a == 'accepted'`，实际断言 exit 1；原断言未打印 receipt。立即停止，余下 39 条与 goal_supervisor 默认/拒绝/非法参数命令均未运行；不能声称最终 trace nested gate 或全量通过。外层八条 trace existence/bytes/mode 恢复检查均 true。
- 先前独立诊断因错误查询 `v13_claim(text)`（真实签名 `v13_claim(text,integer)`）而未捕获 receipt；该 instrumentation exit 1 不是第二次 gate 失败。随后另获一次有界隔离复测：完整 economy 测试 exit 0/ALL PASS，H1 `out_a=accepted`；立即保存的 claim receipt 属 G2 `judge` effect（与 H1 目标 effect_id 不同），而 H1 `context_refresh` 最终 `succeeded`。这证明全局 claim 选择线索本身不能解释最初红灯，最初失败未能重现，根因仍未建立。复测与诊断分别记录在 `prompt-exports/w4-economy-h1-reproduction-2-20261017.log`、`prompt-exports/w4-economy-h1-diagnostic-2-20261017.json`、`prompt-exports/w4-economy-h1-root-cause-20261017.md`；不能用独立复测替换被中止的 47 序列。PG 18.4、Stannum 0.4.0，独立库/prefix 未触及共享数据库；其余历史隔离与命令证据见 handoff。
- 未改 economy/CE 实现与测试/授权/v20；未继续 gate、未暂存/提交/推送。按用户新边界，未来全部 47 绿且文档就绪后也必须先停给协调者消费一次集成静态 Oracle review，再决定提交；当前尚未到该边界。

### 2.4 v99 收尾：47 条全量回归全绿（2026-10-17）

按用户指令，FDFAED98 的 W4 收尾改在 `v99` 分支/worktree 继续。主检出当前工作树（含 §10.9–§10.11 修正）的 272 个冻结集文件（`v13/**` + 本计划 + 覆盖矩阵 + 偏差台账）逐文件 SHA-256 核对后 port 进 v99；`v13/pi_ports/node_modules`、`v13/read_tools/.duck-venv` 以真实拷贝落地（committed .gitignore 原样忽略）；PGDATA 用被证明过的 pinned pgembed 785aa58（隔离 prefix、PG 18.4、Stannum 0.4.0）全新 initdb（`--no-locale -E UTF8`，conf 显式 extension/library path 指向隔离 prefix）；node v24.13.1、go 1.24.5、swift 6.3.2 在场。顺序 runner `prompt-exports/w4-v99-runner.py`：冻结核对 → 47 条独立顺序执行 + goal_supervisor 两探针 → 每条后精确恢复 `v13/pi_parity/traces/pg.jsonl` → 首个无效即停。

两次被保留的阻断尝试：attempt-01 停在 #30 pi_parity——2026-10-17 12:54:56 `/Users/wxl/Projects/PiSwift` 被 `git pull` 自 bfccb32（2026-09-27，冻结 driver 合同基线）快进到 0f44e03，`createAgentSession` 变 `async throws`、`toolExecutionEnd` 四元组变五元组，全新构建编译失败；主检出同晨全部绿证据均在 pull 之前且其构建缓存已被作废（判定性重跑正在被迫重建同版本接口）。经用户裁决回滚 PiSwift 至 bfccb32（detached，原分支指针保留 0f44e03）；driver 适配 0f44e03 不并入本里程碑，留作独立后续变更。attempt-02 停在 #36 read_tools——`~/.duckdb/extensions/v1.5.5/osx_arm64` 钉版扩展缓存从未落地，duck/ring 面按 skip 语义 exit 2；随后实跑被批准的 `v13/read_tools/duck_bringup.py`（INSTALL FROM community，sitting_duck/duck_block_utils sha256 钉版校验通过、loaded=true）。阻断尝试证据：`prompt-exports/w4-v99-attempt01-piswift-0f44e03/`、`prompt-exports/w4-v99-attempt02-duck-absent/`。

最终序列（attempt-03）49 项全部有效：47 条保留脚本全部 exit 0（CE 16/16 组、665 检查、零独立失败；read_tools 首次真跑 duck 面与 E4 嵌套全量，含逐条 trace 恢复；economy H1 序列内绿，历史红灯不追认、根因仍未建立）；`--unattended-continuation` 探针 exit 1 且以既有 ask_user 拒绝尾部收尾；`bad-args` 探针 exit 2 且在任何建库前仅打印 usage。完整命令、逐条退出码/耗时/日志、冻结清单与基线：`prompt-exports/w4-v99-precommit-20261017/`。按 §8.1：消费集成静态 Oracle review → 提交前人工核对 plan_arm 受保护 diff → 按路径提交（v99 分支）→ 同一 49 项清单净树复验 → push origin v99。economy H1 根因留作后续独立诊断；PiSwift 升级与冻结 driver 适配留作后续独立变更。集成静态 Oracle review 已消费（无 P0/P1 阻断，P2 建议中仅文档头前向标记已采纳，其余留作后续变更）。提交前人工核对（§8.1.5）完成：vs `fb295ac6` 的 plan_arm diff 改动均为 `test_stage_bytes` 体内修改、新增 `r0_*`/`r1_*` 具名函数及嵌套助手；`run()` 的三行 `r0_*` 接线经 vs-HEAD 核实属既有 `a2cabf1`，非本里程碑改动；无越界受保护改动。提交 `683ea0e`（46 文件）后净树复验在 #30 pi_parity `historical_frozen` 首红（§10.12 设计缺口）：里程碑提交使 §10.8 适配过的两个守卫文件进入 committed 面而被旧检查拒绝；已按 §10.12 修正（`run_guard` 体内具名放行），首红证据 `prompt-exports/w4-v99-postcommit-20261017/`（#1–29 绿，#30 红）。修正后重跑、追加修复提交与同一 49 项清单净树复验按 §8.1.6 执行。

## 3. Background & Current-State Analysis

### 3.1 上游调查与本地裁决
权威调查为 `docs/investigations/ce-agent-run-six-verbs-for-v13-2026-10-14.md` 和 `docs/investigations/v20-epoch-operation-for-v13-ce-control-2026-10-14.md`。
- start 总是新 session；poll 纯读；cancel 不换 run/epoch ordinal；respond 精确消费 interaction 且不开 epoch。
- **活跃 steer 同 epoch 投递；仅非活跃/终态 reactivation 创建 steering epoch**，continuity 不变。不能把“所有 steer 都换 epoch”当作 CE 原语。
- epoch 是执行资格；operation 是一次准入，同 epoch 可多行；effect 是领取/租约/外部副作用账本。CE operation 不是替代 effect。
- T2 stale 只归档当前 operation 的回执，不覆盖新快照；有真实有效 claim 的迟到结果仍需结算 effect，避免必然落入 unknown。
- PL/pgSQL archive 后不可 RAISE 让归档回滚；正常返回结构化结果，宿主 COMMIT 后才映射协议拒绝。

### 3.2 已验证接缝与不能误用的行为
- 复用 `v13_append_event`、`v13_enqueue_effect`、`v13_complete`、`v13_requeue_stale` 及稳定 effect_id/idempotency_key；不重定义它们。
- enqueue 的 unknown 阻断仅针对**同身份 effect**；CE 各 enqueue 路径必须另查会话级 unknown。request_id 不替代外部幂等键。
- `v13_cancel` 递归取消子树 ready effects，追加 cancel/requested，但不更新 sessions.status；终态返回 replay 且不清槽。CE 单 run cancel/steer 清槽**不直接调用它**，复用其 UPDATE 的单 session 版本并保留原函数。
- `v13_append_event(user/message)` 只复位 completed/failed，不复位 cancelled；terminal steer 必须显式更新 sessions.status=ready。
- `v13_control_authorized` 拒绝 self；`v13_control_operator` 检查 current_user。SECURITY DEFINER 中不能用它识别外部调用者，见 §4.3。
- `v13_complete` 返回 accepted/replay/stale；human one-of、harness 等校验会 RAISE；llm_result_shape 还能把 succeeded 降为 failed，不能只看传入 outcome。
- `LoopDriver` 的 scoped claim/commit/事务外 Fake IO/complete/settlement 是 CeWorker 的时序样板；不调用普通 serve/advance 驱动 CE 会话。

### 3.3 硬约束与冻结门禁机制
1. **唯一 `v13_advance` 约束**：`v13/plan_arm/v13_plan_arm.sql` 是 `v13_advance` 的唯一替换者（`v13/loop_driver/v13_loop_driver.sql:2-3`）；新 Stage SQL 不得 redefine `v13_advance`、`v13_claim`、`v13_complete`、`v13_enqueue_effect`、`v13_requeue_stale`、`v13_should_run*`、`v13_spawn_subsession`、`v13_recover_idle`、`v13_goal_fingerprint` 等被 `fair_claim`（`HASH_FNS`）和 `plan_arm` 钉住哈希的函数。
2. **源码冻结基线（`v13/plan_arm/test_plan_arm.py`）**：
   - `base = "fb295ac6c7459bb98dac57e37883af549d2d8a4c"`（Stage 38 提交）；`phase_d = "78e77c710bf06a0a1c771b822a3837c5db4c66d0"`（Stage 39 提交）。
   - `r0_source_scope()`（`test_plan_arm.py:944-1029`）钉死 `base` 所有受保护路径字节，仅豁免 4 个测试文件（`test_plan_arm.py`, `test_frontier_gap.py`, `test_goal_supervise.py`, `test_loop_driver.py`）、4 个 README、`v13_plan_arm.sql`（R0 哨兵外字节必须还原为 `base`）、`v13/loop_driver/driver.py`（R1 哨兵外字节还原为 `base`）、`v13/load.py`。在 4 个受保护测试文件中，`base` 已有的函数体除 `test_stage_bytes` 外必须字节一致；新增或修改的辅助函数必须命名为 `r0_*` / `r1_*`；模块级 import 与常量完全冻结。
   - 2026-10-17 独立 AST/字节审计澄清：`run()` 中 `r0_direct_cases(cur)`、`r0_preceding_walls(cur)`、`r0_quota_boundary(cur)` 三个调用由既有提交 `a2cabf1` 引入，phase_d 与当前 HEAD 已包含；本里程碑不得增删改这三行或 run/main 其他字节。此为既有 R0 接线的精确记录，不新增一般性的 run/main 修改豁免。审计核实其余 39 个 base 函数体与全部 23 条顶层非函数语句字节一致；本次工作树仅改变计划允许的 test_stage_bytes/r0_/r1_ 范围。
   - `test_plan_arm.py` 中现有的 `r1_driver_restore`（`:272`）、`r1_freeze_positive_proof`（`:348`）、`r1_load_append_ok`（`:413`）、`r1_phase_d_prefix_allowance`（`:508`）、`r0_source_scope`（`:944`）全部是 `base` 之后新增的 `r0_/r1_` 函数，可自由重写函数体。
3. **两个 `test_stage_bytes` 脏树窗口陷阱与存量红灯（已核实）**：
   - 陷阱 (a)：`v13/plan_arm/test_plan_arm.py:250` 的 `test_stage_bytes` 对 `git diff HEAD -- v13/load.py` 断言 `removed == []`。P1 删除 HEAD 中 Stage 40–44 的 10 行（5 条 SQL + 5 条 stage）在提交前会产生 `-` 行。
   - 陷阱 (b)：`v13/fair_claim/test_fair_claim.py:341` 的 `test_stage_bytes` 监控路径包含 `v13/plan_arm` 与 `v13/loop_driver` 且硬编码 `len(SQL_LOAD_ORDER) == 39`（当前在 `main` 上直接运行 `uv run python v13/fair_claim/test_fair_claim.py` 即因 `44 != 39` 退出码 1 红灯）。
   - 陷阱 (c)：`v13/fair_claim/test_fair_claim.py:458` 的 `test_reread` 断言 `SQL_LOAD_ORDER[-2].name == "v13_goal_supervise.sql"` 且 `SQL_LOAD_ORDER[-1].name == "v13_fair_claim.sql"`；需要在 `test_plan_arm.py` 的 `fair_test_ok` 中将 `test_reread` 加入豁免并更新其尾部断言。
4. **Stage 41 删除后的 `spawn` 函数回退验证**：
   - `v13/agentctl_verbs/v13_agentctl_verbs.sql` 曾对 `v13/spawn/v13_spawn.sql`（`base` 受保护文件）中的 `v13_named_sql_writer`（`spawn:42`）与 `v13_spawn_writer_ok`（`spawn:1657`）执行 `CREATE OR REPLACE`，并插入了 `controller`/1 路由策略与 4 条 `agentctl_*` `tools` 行。删除 Stage 41 后，数据库自动恢复 `v13_spawn.sql` 的基线定义；受保护 stage（1–39）无任何代码依赖 `controller` 策略或 `agentctl_*`。

### 3.4 P1 / P2 冗余代码清理裁决（Oracle 终局裁定）
**裁决：采用 P1（彻底退役 Stage 40–44 与 `controller_files`，以单一 Stage 40 `ce_run` 收口）。**

理由：
1. **消除虚假控制面与双入口冲突**：保留 Stage 40–44（P2）会留下多个重叠但残缺的半成品入口（只读 `v13_agentctl_observe`、无人消费的 `steer/injected`、永远返回 `executed: false` 的 `v13_external_exec_classify`、纯静态字符串 `v13_ce_map`），继续制造“事件已记录即等于指令已投递”的错误契约。
2. **收敛冻结边界**：P1 将 `v13/load.py` 从 HEAD 的 44 阶段收敛回 `base`（1–38）+ `phase_d`（`fair_claim`/39）+ `ce_run`/40，相对 `base` 依然是严格的纯尾追加（`fair_claim/39` → `ce_run/40`），不触碰任何 `base` 或 `phase_d` 保护字节。
3. **一次性修复存量红灯**：在同一次里程碑中修复 `v13/fair_claim/test_fair_claim.py` 的 `test_stage_bytes` 与 `test_reread`，消除 Stage 40–44 遗留的门禁断裂。

---

## 4. Component & Interface Design

### 4.1 五表与持久化回执
所有表在 public schema；CE 表/sequence 不给宿主裸读写权限，权限矩阵见 §4.3。标识 UUID、计数 bigint（正数，除 wake cursor 可为 0）；时间使用 timestamptz。

| 表 | 字段与约束 |
|---|---|
| v13_ce_runs | run_id PK；session_id UNIQUE FK sessions，CHECK run_id=session_id；registration_generation/owner_generation 默认 1；current_epoch_ordinal、continuity_generation 默认 1；status 六值；interaction、failure_reason；revision 默认 1；driving_operation_id；owner_backend_pid（仅诊断）；updated_at |
| v13_ce_epochs | epoch_id PK；run_id FK；ordinal、continuity_generation、registration_generation；transition_kind initial/steering/related_follow_up/unrelated；created_at/closed_at；UNIQUE(run_id,ordinal)、UNIQUE(run_id,epoch_id)，每 run 至多一个未关闭 epoch |
| v13_ce_operations | operation_id PK；request_id text UNIQUE 非空；run_id/epoch_id 组合 FK 保证归属；verb start/steer/respond/cancel/admit_turn/admit_tool；owner_generation、registration_generation；attempt_seq（run 内单调，UNIQUE）；status pending/completed/archived/closed；input_message、payload、payload_digest；effect_id 可空且非空时唯一；result（T2 回执含 outcome）；admission_result（准入返回）；publications jsonb 默认 {}（publication request→摘要/expected_revision/原返回）；created_at/completed_at |
| v13_ce_snapshots | run_id PK/FK；registration_generation、epoch_ordinal、revision；status、interaction、assistant_text、failure_reason；last_operation_id FK（最近 driving publication）；interaction_effect_id FK effects（human 通道）；updated_at |
| v13_ce_wakes | wake_id bigserial PK；run_id FK、registration_generation、epoch_ordinal；reason snapshot/steering_requested/terminal/cancelled/superseded；steering_message、interaction、origin_run_id、created_at |

- runs/snapshots 的 status 为 running/waiting_for_input/completed/failed/cancelled/expired；interaction 非空必须是有非空 UUID id/kind 的对象。
- driving_operation_id 在 operations 建齐后加 FK；同 epoch 后续 steering 能使旧 driving publication 失效，不能只靠 epoch 围栏。旧 driving LLM 回执若含 `tool_calls`，`v13_complete` 可照常追加原始 transcript 事件，但该旧 operation 不得再经 `admit_tool`；Worker 组装后续输入时将其标记为 superseded history，不把这些孤儿 call 当作待执行工具，也不生成新的 tool effect。
- 索引：operations(run_id,epoch_id,status,attempt_seq)；wakes(run_id,registration_generation,epoch_ordinal,wake_id)。显式快照/wake 变更的事务末尾 pg_notify('v13_ce_run_changed',run_id|revision)，通知只是提示；receipt/claim 单独执行不生产 CE snapshot 通知。
- 六动词只生产 initial/steering；registration/owner generation 固定 1，owner_backend_pid 不充当跨事务锁。related_follow_up/unrelated/换代/持久 expired 留待以后；合成 expired 可达，superseded 仅有夹具判定测试，不声称六动词已提供 producer。

### 4.2 九个核心入口与额外宿主入口

以下九个核心入口、额外 scoped discovery/claim 与 CE stale 维护包装入口均 `RETURNS jsonb`；poll/wait_check/discovery 为 STABLE，其余写入口为 VOLATILE。discovery 不增加第七个控制动词。

#### 通用规则
- 目标写入口先授权，再按 sessions → ce_runs → epoch → operation → effect 锁定；同层多行按主键稳定排序，禁止 effect→run 反向锁序。委托冻结的 v13_complete/v13_enqueue_effect/v13_append_event 前须已取得所需 sessions/CE 前缀锁，使内部 sessions 锁为同事务重入；不得先锁 effect 再回头首次取 session/run 锁。effect 锁在链尾由冻结结算 helper 或 scoped claim 取得；promotion 新增 operation 同样遵守层序，不为锁重入改写冻结函数。
- 准入 request_id 先用固定命名空间的事务 advisory lock 串行，再查唯一键；digest 包含 verb、actor、run、输入与 CAS 参数。重放必须先授权，同键同输入返回 admission_result（可另附当前 snapshot），不同输入 request_id_conflict。当前 snapshot 不是“start 时快照”。
- JSON 类型、允许键、非空文本/UUID 先验；UTF-8 message 限 64 KiB，JSON 入参序列化限 1 MiB（octet_length）。业务结果继续用已有 human/tool/harness validator；没有 validator 的 CE 字段自行校验，不能声称免费复用不存在的全局限制。
- 每次 enqueue 都含 operation_id（包括相同参数的两次工具），保留业务必需字段；每个路径都查会话级 unknown，包括 human/续跑/promotion。新 start 虽无旧 effect，仍走相同检查。
- 公共返回至少含 schema_version=1、ok；唯一例外是 wait_check/ce_wait，所有成功/拒绝/超时分支均为 §4.2.3 固定八键，不含 ok，以 reason 表示判定。poll/discovery 不适用该例外。错误使用结构化 reason/disposition。异常边界见 accept_receipt。

#### 1. v13_ce_run_start(p_actor uuid, p_message text, p_request_id text, p_parent_session uuid DEFAULT NULL)
- root 仅 operator；子 start 校验 parent 存在及 actor 对 parent 的关系。签名不接受 session_id，协议层收到该键必须拒绝而非丢弃。
- start 在授权、request 重放判定及父 sessions 行锁之后生成新 UUID，通过私有 `v13_ce_insert_session(uuid,uuid,bigint) RETURNS uuid` 显式插入 session_id、parent_session_id、parent_cutoff_seq；helper 返回值须等于生成的 SID。root 两个 parent 字段为 NULL；child 使用父锁内 `next_seq−1` 作为包含上界，父 next_seq=0 时零写返回 `parent_prefix_empty`。父锁持续到整个 start 提交或回滚；重放不重算 cutoff 或生成新 SID。session 与全部 CE 初始对象在同一事务创建，后继异常整体回滚，不留下孤儿 session。其余列依赖既有默认值：status=ready、next_seq=0、turn_no=0、route_policy_name=default/version=1、created_at=now()；不绕过既有约束/触发器。创建 run(run_id=session_id,running,revision=1)、initial epoch(ordinal/continuity=1)、start operation(attempt_seq=1)、user/message 与 ready llm effect；request 嵌 operation_id。
- 设置 driving_operation_id、running snapshot、snapshot wake，存 admission_result 并 notify。返回 run/session/operation/effect、registration/epoch/continuity/revision/status。同 request 重放保留身份，不同 request 总是新建。

#### 2. v13_ce_run_poll(p_actor uuid, p_run_id uuid, p_registration bigint DEFAULT NULL)
- STABLE、零写/锁/notify；未授权、未知目标或指定 registration 失配统一合成 expired。
- 一次 SQL 快照返回 run/session、registration、epoch、continuity、revision、status、interaction、assistant_text、failure_reason、last_operation_id、updated_at。

#### 3. v13_ce_run_wait_check(p_actor uuid, p_run_id uuid, p_registration bigint, p_epoch bigint, p_after_wake_id bigint DEFAULT 0)
- STABLE 纯判定，不 consume wake、不 sleep/advance。删除 p_timeout_ms，预算全归 ce_wait。参数非空且 registration/epoch 正数、wake cursor 非负；未来/不存在 epoch 返回 invalid_wait_args；未知/未授权/registration 失配统一 expired。
- continuity 不同返回 superseded（reserved 分支）；相同可追新 epoch。未消费的 `steering_requested` wake 优先于 actionable snapshot（interaction 非空、waiting_for_input 或终态），actionable snapshot 优先于本地超时；返回 steering wake 时携回该 wake_id，避免 waiter 用普通 snapshot 吞掉 steering 中断。
- 单独过滤 reason=steering_requested，在同 registration 的 [p_epoch,current_epoch] 内找 wake_id>游标的下一条（升序），不可让普通 snapshot wake 遮蔽。active wake 记当前 epoch，reactivation wake 记旧 epoch。返回 interrupted_by_steering；origin_run_id=p_actor 时只抑制正文：依赖 §1 的 run_id=session_id headless 身份，p_actor 指发起控制的 session；NULL operator/recall 不命中自打断抑制，不把任意宿主 UUID 当 run 身份。
- self-origin wake 仍必须返回 interrupted_by_steering，不能整条过滤。顶层八键不变；仅 interrupted 分支在当前 snapshot 对象上添加 `steering_message` 提示字段，外来或 NULL operator 返回 wake 原正文，origin_run_id 与 p_actor 均非 NULL 且相等时返回 JSON null。snapshot 的当前 status/revision/interaction 等原字段不变，poll 不添加此提示字段。
- interrupted 返回的顶层 epoch_ordinal 为所选 wake 的 epoch，snapshot 仍为当前快照；waiter 携回该 epoch 与 wake_id，再次等待时先排空较旧 epoch 的剩余 steering wake。无 steering 后 actionable/epoch_advanced/waiting 返回当前 epoch，不能在第一条旧 wake 后跳到最新 epoch 而漏掉中间 wake。
- 未消费 steering wake 和 actionable snapshot 均不存在时，若 epoch 已前进返回 `epoch_advanced`；若 epoch 已前进同时存在 actionable snapshot，则仍返回 actionable snapshot（并使用当前 snapshot 的 epoch/revision/interaction），不得用 `epoch_advanced` 丢掉可操作状态。返回固定八键：schema_version、reason、snapshot、registration_generation、epoch_ordinal、continuity_generation、interaction、wake_id，不适用值为 null。
- “一次性”由 waiter 自己推进 wake_id 保证，跨 ce_wait 调用携回 after_wake_id；不同 waiter 可各看到一次。它不是 CE 的全局 pending wake 消费，偏差台账必须说明。poll 不消费 wake。

#### 4. v13_ce_run_cancel(p_actor uuid, p_run_id uuid, p_request_id text)
- 授权/幂等/锁序；cancelled 重试 replay，其余终态 already_terminal。仅目标 run，不级联子 run。
- 插入 completed cancel operation，保存 admission_result；关闭目标 pending operations/当前 epoch（ordinal 不变），清 interaction。仅将本 session ready effects 改 cancelled、fence+1、清 lease/error；记录本 session cancel/requested 及真实 actor/request 审计。
- claimed 不伪装已取消、不撤销外部 IO；其真实回执仍可 T2 记账。CE run/snapshot 和 sessions 同事务 cancelled，并追加本 session 的真实 `session/cancelled` 结算事件，沿用冻结的严格 seal 格式；actor/request 另写 CE 审计事件，避免向冻结事件正文塞入非法字段。该结算事件用于消费已处理的 cancel/requested；否则冻结 v13_unconsumed_cancel 在 terminal steer 恢复 ready 后仍会阻塞后续 enqueue。revision+1、cancelled wake。该事件与通知都只表示 CE/session 控制状态，不表示底层 provider 已被终止；禁止通过首次 enqueue 时暂留 cancelled 状态掩盖未消费请求。

#### 5. v13_ce_run_steer(p_actor uuid, p_run_id uuid, p_message text, p_request_id text, p_expected_epoch bigint)
- 授权/非空输入/request 重放；重放先于 CAS；校验 expected_epoch 与 unknown 墙。非 instruction interaction 返回 use_respond，零写。
- **A 活跃：同 epoch。** 新 steer operation 和输入事件持久排队，不关 epoch、不关闭旧 operations、不取消其 ready effect。设新 driving_operation_id，阻止旧 driving 发布终态；旧回执仍可结算自身 effect/operation。无活跃 effect 时 promotion，有则 effect_id=NULL 等待。steer 提交后旧 driving 的 ready LLM effect 仍允许被领取并完成真实 T2 结算，但其 publish 必须因 driving token 过期而归档且不得改快照；其结果事件进入 transcript，作为后续 steer 输入的历史。探针 8 必须覆盖“steer 后旧 ready effect 已 claim”的窗口，禁止把该结果误报为新 driving 发布。
- 对 instruction interaction，沿 respond 的 human/CE 通道交付指令并清 interaction，确保 human 槽位结算后同 epoch llm 续跑。human instruction 必须构造 `response=<steering_message>` 的 one-of 结果（不写 `answers`/`skip` null 键），CE 通道保存同一正文但不创建 human effect。普通 provider 采用 queuedFollowUp：新指令在该 steer operation 绑定的后续 llm 输入中消费；已绑定旧 ready effect 仍可能先执行一次旧请求，因此不承诺“steer 后第一次 provider 调用即包含新指令”，也不承诺中断网络，写入偏差台账。
- **B 终态复活：** completed/failed/cancelled 精确 CAS；关闭旧 epoch/旧 pending，仅单 session 清旧 ready；显式 sessions=ready。创建 ordinal+1 的 steering epoch，continuity 不变，插入新 driving steer，绑定或等待旧 claimed T2 后自动 promotion。
- 两路径均更新 running snapshot、清旧终态字段、revision+1、写 steering_requested(origin/message)；A 用当前 epoch，B 用旧 epoch。禁止调用 v13_cancel 清槽以免幻影取消/子树副作用。

#### 6. v13_ce_run_respond(p_actor uuid, p_run_id uuid, p_interaction_id text, p_response jsonb, p_request_id text)
- 授权/幂等/锁序；interaction_id 必须合法 UUID 且精确匹配当前对象。新 request 对已消费 id 返回 interaction_mismatch；原 request 同输入只重放回执，不再次消费。
- interaction.channel 默认 human，允许显式 ce 本地通道；p_response 为 response/answers/skip 恰一的合法对象。仅声明这两种本地交付通道，不声称实现 CE 全部 provider 专属 approval 枚举。未知响应格式 unsupported_response。
- human 从 snapshot.interaction_effect_id 找 ready human，request.interaction_ref=id；scoped claim 后构造 {schema_version:1,interaction_ref:<exact id>,<one-of>}，调用 v13_complete(NULL,...succeeded...)。不要为另外两个 one-of 写 null 键；严格符合 v13_acl.sql human 校验。
- 两通道都在同事务创建 pending respond operation（保留 interaction+answer），清 interaction/binding；sessions=ready，CE=running；设 driving 并 promotion 后续 llm。human 结算不代表后续 llm 已完成，非 human 也不能空队列 running。
- 不开 epoch，保存 admission_result、revision+1、wake reason 固定为 `snapshot` 并 notify。回应必须由可信宿主外部输入路径准入，不把 respond 暴露给目标 agent 自答。

#### 7. v13_ce_admit_operation(p_actor uuid, p_run_id uuid, p_epoch bigint, p_verb text, p_payload jsonb, p_request_id text, p_driving_operation uuid)
- 仅 admit_turn/admit_tool；完整 CE 授权/幂等/锁序，要求当前未关闭 epoch、run=running、driving token 匹配、无 unknown。旧 turn 不得在新 steer 后准入自己的工具。
- 授权及 request 重放之后，新准入按 epoch、run 状态、driving token 顺序校验；分别零写返回 `ok=false, disposition=rejected, reason=stale_epoch/run_not_running/stale_driving`；通过这些检查后若存在会话级 unknown，零写返回 `ok=false, disposition=rejected, reason=unknown_wall`。Worker 遇任一拒绝立即停止旧分支，不做 Fake IO、不补 effect、不 publish；没有可提交审计也不虚称已归档。
- 插入 pending operation 前，admit_tool 必须验证 tools 目录中存在且 enabled、参数通过 CE 私有 schema helper 与既有 `jsonb_matches_schema(json,jsonb)`；enqueue/promotion 前复核目录与 schema。`tools.param_spec` 是 question/stated/options 提问模板，不能当作参数 schema。私有 `v13_ce_tool_schema(text) RETURNS json` 为 IMMUTABLE/SECURITY DEFINER、受信超级用户 owner、固定 search_path 且无宿主 EXECUTE，内含唯一 `spawn_subsession` draft-07 schema：object、required task string 长度 1–1024、additionalProperties=false。私有 `v13_ce_tool_check(text,jsonb) RETURNS text` 返回 NULL 或拒绝 reason；未知/disabled/无 CE schema 的工具为 invalid_tool，参数不符为 invalid_tool_args。无 schema 不放行；不新增 policy 或目录行、不调用有副作用的 handler。T2 仍执行冻结结果 validator，不能代替准入期校验。
- admit_tool payload 闭集为 `tool`（string）、`params`（object）、`source_operation_id`（UUID string）、`tool_call_index`（JSON 非负整数）、可选 `tool_call_id`（冻结 id 格式、1–128 字符）；来源必须匹配当前 driving，失配零写 `invalid_tool_source`，其他非法 envelope 为 invalid_args。业务 effect.request 原样保留这些字段并添加新 operation_id；Worker 用确定性 `ce:<source>:tool:<index>` 重放。promotion 复核失败将该 queued operation 归档为 invalid_tool_at_promotion，并继续检查后续队列；正常 T2 仍必须落实完整续接，不能留下 running 空队列。同 epoch 可多行，不复活 controller policy。
- promotion 在无 ready/claimed/unknown 时绑定下一 pending；未绑定者禁止 IO。admit_turn 更新 driving，admit_tool 不抢占 driving。
- 返回 operation/request/epoch/effect/status；未领取时 attempt_no/fence=null，尚未绑定 queued=true，不能虚构 claim tokens。

#### 8. v13_ce_accept_receipt(p_actor uuid, p_operation_id uuid, p_request_id text, p_status text, p_result jsonb)
- receipt 含 effect_id/attempt_no/fence/effect_result，先校验身份/类型；effect_id=NULL 拒绝，不能在 T2 造 effect/claim。outcome+result 一起比较重放。
- A request mismatch：仅记 ce/receipt_request_mismatch，不改目标 operation/effect。receipt request_id 固定为 `ce:<operation_id>:receipt`，不与原 admission request_id 混用。B completed 同回执 replay，冲突 receipt_conflict，不重复 complete；首次返回 `replayed=false`，存储重放返回 `replayed=true` 并携原 receipt 身份/摘要/outcome，Worker 见重放不得再次续接。已处理 stale 重试不重复记账。
- C closed 保持 closed；D epoch/registration/owner 过期的 pending 改 archived。关联 effect 若仍 claimed 且 tokens 匹配，**同 T2 用真实结果结算**，不发布旧快照；tokens stale 不得释放他人 lease，返回 stale_claim。effect 已 unknown 返回 unknown_wall，不能借 archive 恢复。closed/archived 行在首次真实结算时也保存 outcome+result；其状态保持不变，重试比较该存储回执，不重复追加 archive/wake。
- closed/archive 的已知结果释放槽位后，同 T2 promote 当前 epoch 队列；终态 cancel 不 promotion。归档/audit 正常返回，由宿主 COMMIT 后映射拒绝，禁止归档后 RAISE。
- E 有效行遇 unknown 返回 unknown_wall；F 有效 claimed 经 v13_complete 接受后 operation=completed，同 T2 promotion，但不增加 CE revision、不更新 snapshot、不追加 CE wake/notify。工具完成不结束 run。准入/控制动词和 publish 的显式快照变更才推进 revision；底层 effect 事件/工作通知不等同于 CE snapshot wake。
- complete 的 accepted/replay 仍需检查实际 effect 终态；llm_result_shape 可能降为 failed。stale 不算成功；unknown outcome 禁 promotion，不能伪造 completed run。
- 有效正常回执的 accept 不是独立 COMMIT 点：Worker 必须在同一 T2 内完成全部后继 admit/publish，再一起提交（§4.4）。返回实际 outcome 与锁内 revision，不能仅凭入参 succeeded 决定续接；stale/closed/archive/unknown 等分支按已有审计规则提交且不续接。
- 预期 shape/业务异常用子事务只包底层结算，失败回滚该块，外层 archive/audit 并返回 bridge_rejected，effect 不假结算；剩余 claimed 按租约规则处理。非预期数据库故障传播、整体回滚，禁止 WHEN OTHERS 吞错或声称故障时归档已落盘。

#### 9. v13_ce_publish_snapshot(p_actor uuid, p_operation_id uuid, p_request_id text, p_expected_revision bigint, p_snapshot jsonb)
- publications 按 request 保存摘要/expected_revision/原返回；同 request+输入重放优先于终态/围栏检查，零新增 revision/wake，冲突 request_id_conflict。
- 新发布验证 epoch/registration/owner/current driving；expected_revision 必须等于当前 revision，否则 revision_conflict。旧 epoch/旧 driving/终态后的新提交只归档审计，pending 才改 archived，completed/closed 不回退。
- 存储重放优先；对任何新 publication，在写入前检查当前 snapshot.interaction：非空一律零写返回 ok=false, reason=interaction_pending，包括 running/第二次 waiting/terminal，不能覆盖正文、binding 或 human effect。仅精确匹配的 respond、instruction steer 或显式 cancel 可消费现存 interaction。无 interaction 时新 publication 还须当前 run=running，否则 run_not_running；不能仅凭原 driving 已结算绕过等待状态。
- driving effect 须先真实结算；不得靠发布抹掉 claimed/unknown。waiting/terminal 有其他 pending 工具或更新的 steering 返回 pending_work，不能丢队列。仅 running/waiting_for_input/completed/failed 可发布。
- running 更新文本；waiting 校验 id/kind/channel，CE=waiting_for_input、sessions=waiting。human 通道同事务 enqueue 带 operation_id/interaction_ref 的 human effect，保存 binding；ce 通道不造 human。human 不与 driving llm 共用 operation.effect_id 的唯一绑定。
- completed/failed 同步 CE 与 sessions 同名终态、清 interaction/binding、关闭 epoch；工具无权发布终态。revision+1；wake reason 固定为 `terminal`，running/waiting_for_input 发布的 wake reason 固定为 `snapshot`，并保存 publication 回执。

### 4.3 角色、Actor 与 SECURITY DEFINER

| 对象/入口 | PUBLIC | v13_worker | v13_recall | v13_route |
|---|---|---|---|---|
| CE 五表/sequence | 无 | 无 | 无 | 无 |
| 写动词、admit/accept/publish、scoped discovery/claim、CE stale 维护包装 | 无 | 无 | 无 | EXECUTE |
| poll/wait_check | 无 | 无 | EXECUTE（仍校验 actor） | EXECUTE |
| 内部 caller/actor/promotion/结算辅助 | 无 | 无 | 无 | 无（仅属主） |

- migration 由可信 schema owner 执行；不给 route 裸 INSERT sessions。CE SECURITY DEFINER 函数及 CE 表的属主保持受信超级用户；唯一新增函数属主例外是私有 `v13_ce_insert_session(uuid,uuid,bigint) RETURNS uuid`：由既有 `v13_spawn_owner` 持有，SQL/VOLATILE/SECURITY DEFINER、非 STRICT、固定 search_path=pg_catalog,public，仅 INSERT public.sessions 的身份与父前缀三列并 RETURNING session_id。该 helper 无授权或父锁逻辑，全部由外层 start 完成；所有正常约束与 trigger 保留。创建、改 owner、撤权在同一 migration 事务，清除 PUBLIC 与所有非属主显式 EXECUTE（包括默认权限）；不授任何宿主 EXECUTE。既有角色属性、membership、函数和基表 ACL 不变，宿主不能继承或 SET ROLE 为 v13_spawn_owner；受信属主/超级用户仍可直接调用 helper，不能宣称仅 start 能调用。其余 CE 函数不享受该 owner 例外。入口 SECURITY DEFINER、search_path=pg_catalog,public、完整限定表名；创建与 REVOKE 同事务，避免默认 PUBLIC EXECUTE 窗口。由于 human respond/steer 的底层结算固定调用 `v13_complete(NULL::uuid,...)`，本阶段专用临时库固定由受信超级用户作为 CE SECURITY DEFINER 函数及 schema owner，setup 必须验证其 `rolsuper` 与既有 `v13_control_operator()` 均为真；不交付非超级用户 owner 部署路径，不为此给 route/宿主角色新增既有表 DML 或冻结函数 EXECUTE 授权。该 owner 不与宿主调用登录身份共用；宿主正例必须使用非超级用户连接，不能用 owner 绕过 ACL gate。CE 自己的 actor helper 仍以真实外部 caller 为准，不把 definer owner 当成外部 operator。
- definer 会调用含未限定表名、且自带 search_path 的冻结函数；仅给新函数限定表名不足以防 temp/public 对象遮蔽。CE 使用专用新建数据库，装载完基线后收回 PUBLIC 及宿主测试角色的数据库 TEMPORARY、public schema CREATE（并检查继承角色无残余授权），schema owner 不与调用登录身份共用。不能改冻结函数字节来绕过此问题；ACL gate 必须验证调用角色不能创建临时/同名 public 对象。schema owner 是受信角色；不承诺防御恶意库属主/超级用户。此处数据库/schema 级收权是显式新增部署约束，不是“既有表 ACL 零变”的例外放行；基线对比必须分别检查两者，不能略过所有 ACL。
- 私有 v13_ce_caller_role 在 definer 内取 current_setting('role') 非 none 的 SET ROLE 身份，否则 session_user，验证角色存在。不接受 caller 参数，不用 definer 的 current_user，也不能只看 session_user 而忽略 SET ROLE 降权。
- actor helper 先验证真正 caller 是 route 成员/超级用户；读也允许 recall，但不会自动成为写 operator。`operator` 的可测试定义是：真实 caller 为 `v13_route` 成员或超级用户，且写入口的 `p_actor IS NULL`；非空 actor 必须存在且为目标自身或直接父。root start 要 operator，子 start 校验 parent 关系。SECURITY DEFINER 内只使用专用 caller helper，不使用 definer 身份或冻结的 `v13_control_operator()` 判定外部调用者。
- 读授权固定为：真实 caller 为 route/recall 成员或超级用户时，p_actor=NULL 是只读 operator，可观察任意 run；非空 p_actor 仍须存在且为目标自身/直接父。recall 的 NULL 读身份不授予任何写入口；未知/未授权统一 expired。探针 10 固定覆盖 recall 的 NULL/self/parent 正例及陌生 actor 负例。
- p_actor 是可信宿主提供的身份，不是不可信多租户凭证；host 须验证真实调用 agent 与外部响应来源。self 控制不代表可让 agent 自答。
- CE 校验后调用 v13_complete(NULL::uuid,...)，保留真实 actor 审计。不得在 definer 中把 v13_control_operator() 的属主身份当成外部授权。
- gate 必须验证非 superuser 登录正例、普通用户/worker 负例、recall 只读与 SET ROLE 降权；超级用户独跑不能证明 ACL。既有 base 表权限不在本里程碑重构。

### 4.4 薄 Worker/Wait 与辅助函数

四文件闭集不变，CeWorker/ce_wait 为 test_ce_run.py 可导入 helper，导入零副作用，main guard 才建库/跑测试。它是 Fake 验证宿主，不冒充生产 runtime。CeWorker 用具备 v13_route USAGE 的非超级用户宿主登录建立专用连接（不是 v13_worker，也不是 definer owner）；ce_wait 可用同一类 route 登录，另用 recall 登录覆盖只读等待正例。不得为了复用 LoopDriver 连接而给 v13_worker 增加 CE EXECUTE。

- 私有 v13_ce_promote_next_effect(p_run_id) 要求持 run 锁；run=running、无 active/unknown 时按 attempt_seq 为当前 epoch 下一 pending/effect=NULL 行绑定 ready effect。无行 no-op；所有 IO 前已绑定且已提交 claim。
- v13_ce_claim_effect(p_actor,p_operation_id,p_worker,p_lease_ms) 是 route 可执行的额外宿主入口，不属于九个核心入口；授权/同一锁序、仅领取 operation.effect_id 对应的 ready 非 human effect，递增 attempt/fence、设 lease，返回 request/idempotency_key/tokens。不调用全局 v13_claim，不领走其他 run；必须保留 v13_attempt_ok 和既有 op_seq/mutation_scope 先后判定，不能只抄 UPDATE 略过领取门禁。
- 私有 v13_ce_claim_bound_effect(p_run_id,p_effect_id,p_worker,p_lease_ms) 实现共同领取原语。公开 claim 校验 operation.effect_id 后才委托；respond/instruction steer 从当前 snapshot.interaction_effect_id 验证 human 归属、interaction_ref、ready 状态后才委托。human 不通过原 driving operation 的 llm effect_id 领取，普通 worker 跳过 human。
- v13_ce_discover_work(p_actor uuid,p_run_id uuid) 是 route 可执行的额外 SECURITY DEFINER/STABLE 只读入口，使用写宿主同等级 actor 授权（非 recall），未知/未授权统一 unauthorized。一次 SQL 快照返回 schema_version/ok、run_id/current epoch/revision/status/current driving_operation_id，以及该 epoch 全部 pending operation 按 attempt_seq 排序的闭集摘要 operation_id/verb/attempt_seq/effect_id/effect_status；effect=NULL 显式 queued，effect 非空区分 ready/claimed/unknown。不返回其他 run 的行、原始结果或任意表查询能力，不加锁/不 promotion/不推进 revision/wake。摘要仅为提示，claim/admit 仍在锁内重新校验资格。
- 额外宿主维护入口 `v13_ce_requeue_stale() RETURNS jsonb` 是 VOLATILE/SECURITY DEFINER、受信超级用户 owner、固定 search_path=pg_catalog,public；仅 route EXECUTE，函数内仍按真实 caller fail-closed 验证 route 身份。它仅委托未改写的 `public.v13_requeue_stale()`，返回 `{schema_version:1,ok:true,recovery:<原计数json>}`；不取得 CE/session 前缀锁、不写 CE snapshot/revision/wake。W4 实跑证明 route 直调冻结 invoker 函数会在 pgmq schema USAGE 报 42501，因此通过该窄包装实现原定回收动作，不扩大旧角色、pgmq 或基表 ACL。此维护包装不是新增控制动词。
- Worker 仅凭 run_id 调 discovery 发现当前 driving 和 pending，禁止裸读 CE 表；ready 可 claim；queued 等控制/结算事务的 promotion 后重新发现；**claimed 不接管重放**，等原回执或租约到 unknown。owner_backend_pid/短锁不保证跨 IO 独占；部署每 run 单 CE 驱动，但并发 scoped claim 仍必须只有一方成功。
- 工具执行本阶段仅提供 `spawn_subsession` 的显式 Fake adapter，按 claim.request 的原始 `params.task` 返回带 `adapter=ce-fake-spawn`、`simulated=true` 的确定性结果；不执行原生 spawn handler、不拼接 children、不创建子 session。CE child run 仍由 start(parent) 创建；其他模板工具继续走原有 advance/judgment 管线，在 CE 中为 invalid_tool。
- 输入组装不得把原始 events 直接当 provider 工具协议：对被 steer 取代且未准入对应工具 operation 的旧 LLM `tool_calls`，保留原始 events 不变，仅在派生 Fake 输入中转换为带 `superseded` 标记的普通历史文本，移除未配对的协议 tool-call 标记，不伪造 tool result、不执行孤儿工具。已在 steer 前准入的工具 operation 继续按账本结算，不因该投影而丢弃。投影使用 route 既有可读的 events.source_effect_id、来源 LLM effects.request.operation_id 和工具 effects.request 的 source_operation_id/tool_call_index（及可选 tool_call_id）对应原始调用；不裸读 CE operations，不扩 discovery 的当前 epoch pending 闭集。probe 8/14 必须覆盖孤儿调用和已准入调用两条路径，偏差台账记录投影规则。
- T1 admit/claim COMMIT → 断言 psycopg2 TRANSACTION_STATUS_IDLE → Fake LLM/Tool IO（回调内再断言）→ T2 accept/续接/publish COMMIT。无外部 IO 进入事务。CeWorker 每轮扫描目标 run 前先在独立短事务调用 CE 包装 `v13_ce_requeue_stale()`，由其委托既有 `v13_requeue_stale()`；该函数无参数，会全库回收并重建工作通知，不是 scoped 回收，不能改写其冻结字节或声称只影响目标 run。仅在本阶段专用临时库使用这一全库维护行为；调用时不持 CE/session 行锁，不与 admit/claim/accept/publish 混在同一事务，回收 COMMIT 后再开始有序 CE 锁事务。Worker 运行时每轮触发，崩溃后由重启的 Worker 第一轮触发；Worker 停止且无人重启时不承诺自动回收，ce_wait 保持纯等待不触发维护。探针 13 验证 claim 后 Worker 停止、租约过期、重启首轮转 unknown 且各 enqueue 路径受墙阻断，并验证另一 run 的过期 effect 也会被该全库函数处理。
- stale/archive/request_mismatch/unknown/bridge_rejected 先提交可提交审计再停旧分支，不 publish；SQL 负责已知结果结算与自动交接。正常工具全结束后准入 admit_turn；llm 的工具准入/最终发布仍须 driving token，不能跨 steer 偷写。`accept_receipt` 只结算 effect/operation、记录回执并做 promotion，不推进 `v13_ce_runs.revision`、不写 snapshot wake；revision 与 snapshot wake 只由 `publish_snapshot`（以及明确的 start/steer/respond/cancel 写入口）推进。正常 accept 返回实际 outcome 及其持 run 锁时读取的当前 revision。**唯一正常路径是同一 T2 原子提交回执及完整续接，禁止 split COMMIT**：LLM 给出工具时一次性准入全部有序 tool operations；无工具时 publish waiting/terminal（需继续运行则同事务 admit_turn，不能只发 running 文本）；工具回执结算后若还有 pending 则 promotion，最后一个工具结算时同事务 admit_turn；实际失败则同事务发布 failed 或准入明确的可继续分支。新 turn 的 driving token 更新与以上结算一并提交。publish 使用 accept 返回的固定 CAS revision，禁止重读最新 revision 掩盖冲突。任何正常续接的 SQL 故障或非预期拒绝须回滚整个 T2，不得捕获后只提交 accept；stale/archive 等既定拒绝分支可独立提交审计但不发布旧结果。没有 durable continuation/outbox，故不允许以“宿主保存返回值”为拆分借口。
- Worker 内部 request_id 为确定性文本：`ce:<source_operation_id>:receipt`、`ce:<source_operation_id>:publish:<purpose>`、`ce:<source_operation_id>:tool:<zero_based_index>`、`ce:<source_operation_id>:next_turn`；purpose 为固定 waiting/terminal/running，不含时钟/随机数/重读 revision。工具索引取该次已校验 LLM 结果的原顺序。控制动词外部 request_id 保持调用方提供，二者用前缀隔离。COMMIT 回应丢失后仅凭原 request/receipt 重放存储回执，不再次做 IO；重放响应不得再次触发续接副作用。
- 未确定外部副作用不自动重试；只有 Fake/明确未发送的瞬时失败可进程内有界重试（max_attempts=2），保留原 idempotency_key。
- Worker 取消不撤销已提交 T1；pending/claimed 由显式 cancel 或真实租约规则处理。

ce_wait(conn,actor,run_id,registration_gen,epoch_ordinal,timeout_seconds=5.0,poll_interval=0.05,after_wake_id=0)：
1. 专用连接起始 IDLE；timeout 有限且 [0,3600]，interval 有限且 [0.01,1]，wake cursor 非负；非法输入零 SQL，不提交别人事务。
2. LISTEN v13_ce_run_changed/COMMIT，再短查询 wait_check/COMMIT；读状态不跨等待持事务。
3. epoch_advanced 追游标；interesting/expired/superseded/interrupted 立即返回。携回 wake_id 防下一次重复；固定八键同 §4.2.3。
4. 到 deadline 再查一次 actionable，仍 waiting 才 timed_out。select.select 在 IDLE 等通知，周期重读兜底；不把通知 payload 当权威。
5. finally UNLISTEN/COMMIT；断连传播，清理错误不遮蔽原异常。waiter 游标一次性而非全局消费写入 README/偏差台账。

## 5. File-by-File Impact & Gate Freeze Adaptation

### 5.1 新增四文件
1. v13_ce_run.sql：五表、九个核心入口、scoped discovery/claim 与私有辅助；不固定辅助函数总数，不覆写冻结函数。
2. setup_db.py：库名 ll_ce_run_<pid>_<6hex>，严格验证模式、拒绝 agent_v13_ 前缀与已存在库；检查 stannum/pg_jsonschema 等既有扩展。先 `load_stage(...,"fair_claim")`，再按 §4.3 完成数据库 TEMPORARY/public CREATE 收权和 CE SECURITY DEFINER owner/operator 判定，记录 ACL/函数/表的 before 基线；之后用 setup_db.py 局部 helper `load_ce_run(server,db)` 调既有 load.run_psql 仅执行 `v13/ce_run/v13_ce_run.sql` 一次；禁止此处调用 load_stage(...,"ce_run") 重跑 1–39。随后记录 after 并比较 Stage 39→40 仅有计划内对象/ACL 变化，不能先装完再伪称比较前后。基线须涵盖全部既有 public 函数定义/属主/ACL、表结构/ACL及既有角色属性/membership；after 均不变，新增 CE 函数仅私有 INSERT helper 允许 v13_spawn_owner，其余 definer 必须受信超级用户。创建状态属于单次调用：严格匹配 ll_ce_run_<pid>_<6hex>，CREATE 成功后记录数据库 OID；finally 只 DROP 本次确实创建且当前名称/OID均匹配的库。同名拒绝或CREATE失败不能触发DROP，清理异常不能遮蔽原始错误，导入零建库副作用。
3. test_ce_run.py：Worker/Wait helpers、非 superuser ACL、§8 全部探针；Fake-only，不开真实 provider/socket。
4. README.md：声明范围、权限/身份、IO/lease、单入口前提、偏差、保留字段、数据库清理、真实门禁命令与结果。

### 5.2 精确删除文件清单（22 个文件，`git rm`）
```text
v13/agentctl/README.md
v13/agentctl/setup_db.py
v13/agentctl/test_agentctl.py
v13/agentctl/v13_agentctl.sql
v13/agentctl_verbs/README.md
v13/agentctl_verbs/setup_db.py
v13/agentctl_verbs/test_agentctl_verbs.py
v13/agentctl_verbs/v13_agentctl_verbs.sql
v13/goal_workflow/README.md
v13/goal_workflow/setup_db.py
v13/goal_workflow/test_goal_workflow.py
v13/goal_workflow/v13_goal_workflow.sql
v13/external_exec/README.md
v13/external_exec/setup_db.py
v13/external_exec/test_external_exec.py
v13/external_exec/v13_external_exec.sql
v13/ce_map/README.md
v13/ce_map/setup_db.py
v13/ce_map/test_ce_map.py
v13/ce_map/v13_ce_map.sql
v13/loop_driver/controller.py
v13/loop_driver/test_controller_vertical.py
```

### 5.3 修改文件与脏树/净树门禁精确适配
1. **`v13/load.py`**：
   - `SQL_LOAD_ORDER` 移除 `agentctl`、`agentctl_verbs`、`goal_workflow`、`external_exec`、`ce_map` 五项，在 `V13_ROOT / "fair_claim" / "v13_fair_claim.sql",` 之后追加唯一第 40 项：`V13_ROOT / "ce_run" / "v13_ce_run.sql",`。
   - `STAGE_THROUGH` 移除 40–44 旧键，在 `"fair_claim": 39,` 之后追加 `"ce_run": 40,`。
2. **`v13/loop_driver/driver.py` 与 `v13/loop_driver/README.md`**：
   - `driver.py`：删除 `# R1_SETTLE_ONCE_END` 之后的 `def run_controller_once(...)` 方法全文，使文件在剥离 `# R1_SETTLE_ONCE_BEGIN ... # R1_SETTLE_ONCE_END` 后与 `fb295ac6c7459bb98dac57e37883af549d2d8a4c:v13/loop_driver/driver.py` 字节 100% 相等。
   - `README.md`：移除末尾 `## Controller thin cut` 章节。
3. **`v13/plan_arm/test_plan_arm.py`**：
   - **`test_stage_bytes()`（`:250-269`）**：保持对 `paths`（Stage 1–29 受保护目录）`diff == b""` 的检查；对 `v13/load.py` 的检查改为验证当前 `v13/load.py` 相对于 `fb295ac6c7459bb98dac57e37883af549d2d8a4c:v13/load.py` 无任何删除行（`removed_vs_base == []`），且若相对于 `HEAD` 存在 `-` 行，仅允许与固定十行字面集合（旧 5 条 SQL_LOAD_ORDER 项 + 旧 5 条 STAGE_THROUGH 项）完全相等的退役 Stage 40–44 行（提交后 `diff HEAD` 为空时同样自动通过）；禁止关键词、前缀或子串放行。
   - **`r1_driver_restore(current, original)`（`:272-346`）**：移除 `APPROVED_CONTROLLER_METHOD`；断言 `b"def run_controller_once" not in current`；剥离唯一的 `# R1_SETTLE_ONCE_BEGIN ... # R1_SETTLE_ONCE_END` 块后断言 `restored == original`。2026-10-16 已全文搜索 `v13/loop_driver/test_loop_driver.py`，无 `controller` / `run_controller_once` 引用；因此该文件无需为删除 controller 修改模块级 import/常量。W1 再核查一次并在 README 记录；若实施时出现新的受保护引用，停下调整计划，不能用 r1 helper 绕过冻结的模块级字节。
   - **`r1_freeze_positive_proof()`（`:348-411`）**：验证空 sentinel 失败、`run_turn` 改名失败、`v13_advance` 泄漏失败，以及注入 `def run_controller_once`（无论在 sentinel 外或内）均失败。
   - **`r1_load_append_ok(base_text, current_text, tracked)`（`:413-506`）**：`approved` 更新为：
     ```python
     approved = [
         ("fair_claim", "v13_fair_claim.sql", "fair_claim", 39),
         ("ce_run", "v13_ce_run.sql", "ce_run", 40),
     ]
     ```
     失败断言文案更新为 `"append is not fair_claim/39 then ce_run/40: " + str(got)`。
   - **`r1_phase_d_prefix_allowance()`（`:508-941`）**：
     - 将 `stage40..stage44` 与 `controller_files` 替换为单一集合：
       ```python
       stage40 = {
           "v13/ce_run/v13_ce_run.sql",
           "v13/ce_run/setup_db.py",
           "v13/ce_run/test_ce_run.py",
           "v13/ce_run/README.md",
       }
       ```
     - 在 `fair_test_ok`（`:565-579`）中将 `if func == "test_stage_bytes": continue` 扩展为 `if func in ("test_stage_bytes", "test_reread"): continue`。
     - 更新 `allow()` 与末尾合成负例（`reject_reason`），覆盖 `stage40` 缺失跟踪路径、越界文件 `v13/ce_run/extra.py`、非法编号 41/40a、以及未计划的 Stage 41 `not_scheduled`。
4. **`v13/fair_claim/test_fair_claim.py`**：
   - **`test_stage_bytes()`（`:341-377`）**：不新增任何顶层函数或 import；将 `len(SQL_LOAD_ORDER) == 39` 更新为 `len(SQL_LOAD_ORDER) == 40 and STAGE_THROUGH["fair_claim"] == 39 and STAGE_THROUGH["ce_run"] == 40`。2026-10-16 已读取实际 paths 列表：监控包含 `v13/plan_arm` 与 `v13/loop_driver`，不包含自身 `v13/fair_claim`，故 Oracle 的条件性 self-diff 风险不成立，不新增自身白名单。自身函数闭集仍由 plan_arm 的 `fair_test_ok` 校验。dirty-tree 中只有精确集合 `{"v13/plan_arm/test_plan_arm.py", "v13/loop_driver/driver.py", "v13/loop_driver/README.md", "v13/loop_driver/controller.py", "v13/loop_driver/test_controller_vertical.py", "v13/load.py"}` 可跳过通用 `diff == b""`；这些路径的内容正确性分别由 plan_arm r0/r1 闭集/字节 gate 与本项 load 检查负责。监控集合中所有其他路径必须 `diff == b""`，不得按目录/前缀豁免。对 `git diff HEAD` 的检查允许本次里程碑对 `v13/plan_arm/test_plan_arm.py`、`v13/loop_driver/{driver.py,README.md,controller.py,test_controller_vertical.py}` 与 `v13/load.py` 的预期变更（提交后 `diff HEAD` 为空时同样通过），同时对 `fb295ac6` 的 Stage 1–38 SQL 文件与 `78e77c71` 的 `v13/fair_claim/v13_fair_claim.sql` 做字节零改动校验。对 load.py 的删除行检查同 plan_arm：dirty diff 非空时与固定十行字面集合精确相等，clean diff 为空时通过；此规则不套用到 driver 等其他文件，后者用独立字节/函数闭集验证。禁止用关键词、前缀或子串放行。
   - **`test_reread(cur)`（`:458-534`）**：将 `load_tail_goal_supervise` 更新为校验 `SQL_LOAD_ORDER[37].name == "v13_goal_supervise.sql"`、`SQL_LOAD_ORDER[38].name == "v13_fair_claim.sql"`、`SQL_LOAD_ORDER[39].name == "v13_ce_run.sql"` 且 `files_through("fair_claim")[-1].name == "v13_fair_claim.sql"`。
5. **收尾评审工件**：
   - `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md`：标记旧 `#86`–`#91`（Stage 40–44 与 Controller thin cut）已由 P1 退役，并追加新的 `## Stage 40 (ce_run)` 覆盖行（在实际跑绿门禁后填入真实日期、命令与检查数）。
   - `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md`：追加 `## Stage 40 (ce_run)` 偏差与裁决记录（记录 P1 退役 Stage 40–44、双层 Actor 桥接、同 epoch 多行 operation 与单活跃 effect 桥接、以及 basic loop 与 `v13_advance` 职责分层）。

---

## 6. State, Data Flow, Errors & Edge Cases

### 6.1 故障与恢复
- admit 后 claim 前崩溃：effect=ready 可继续领取；queued effect=NULL 必须 promotion 后才 IO。
- **claim 提交后无论 IO 前后崩溃**，外部状态均不能假定安全；原 worker 携真实 tokens 可结算，否则租约回收到 unknown，禁止重新做一遍。原计划“IO 前崩溃恒为 ready”不成立。
- 真实迟到回执：已知结果按原 claim 记账、CE 只归档、不改新快照；同 T2 promotion 避免 running 空队列。未知/过期 claim 不假结算。
- T2 必须把正常 accept 与全部后继 admit/publish 原子提交（§4.4）：提交前任意崩溃整体回滚，原 effect 仍 claimed；无真实回执的重启者只等租约到 unknown，不重复外部 IO。提交成功即已有完整工具队列/下一 turn/等待或终态，不能出现“回执已提交、续接未提交”的中间状态。重启仅持 run_id 经 discovery 找 ready/queued 并继续；不是凭发现接口重做 claimed IO。T2 COMMIT 回应丢失时用确定性 request_id 重放存储 receipt/admission/publication，无重复 IO/revision/wake。accept 不推进 revision/wake，publish 使用其锁内固定 CAS；本阶段不交付拆分事务或 outbox 恢复。
- active steer 不换 epoch，靠 driving token 防旧发布；terminal steer 新 epoch 靠 epoch+driving 双围栏。
- cancel 只目标 run；CE/sessions 同步 cancelled，旧 claimed 后续只记账，子 run 不受影响。cancel 不等于终止已在事务外执行的进程。迟到 receipt 仍按原 effect tokens 进入 `accept_receipt`：若 claim 有效则允许底层 `v13_complete` 记账并保持 CE cancelled 快照不回退；若 tokens 已失配/已 unknown 则返回 stale_claim/unknown_wall。已核对 `v13/acl/v13_acl.sql`：`cancel not pending` 只在 `p_status='cancelled'` 分支检查，真实 succeeded/failed 不进入该分支；不得把真实 outcome 改写为 cancelled。`v13_complete` 按 attempt/fence/status 而非仅按墙钟租约判断 stale，租约过时但尚未被回收且 tokens 仍匹配的真实回执仍可结算；回收改 fence/status 后不得结算。探针 7 验证这些分支并确认 CE 与 sessions 不因迟到结果复活。

### 6.2 零写拒绝与返回边界
空输入/超界/非法 id、CAS stale、use_respond、interaction mismatch、unknown enqueue 均零业务写；request mismatch 的专用审计是明确例外。读未授权/未知统一 expired；写未授权统一 unauthorized，不用不同错误泄露存在性。原 request 重放不算重复回答。返回 bridge_rejected 不等于 effect 已结算；非预期 SQL 故障整体回滚、宿主不得声称归档已提交。

## 7. Tradeoffs, Risks & Non-Goals

- 删除 22 文件是破坏性源码清理，不是旧 Stage 44 生产库升级脚本。数据库从 Stage 39 重建至 40；不提供自动增量迁移/回滚。
- 旧 agentctl/ce_map/controller 调用方迁移到 ce_run，无兼容别名。宿主直调，不新增 tools/sql-route，不复活 controller policy。
- 单 session 仅 CE worker 推进；不得同时由 LoopDriver.serve/RealChain.serve/GoalSupervisor.tick 驱动。这是部署纪律，不是结构性强制，README 必须明确。并发 claim 可防重复 effect，不等于生产多 worker 接管保证。
- unknown 无 CE 恢复入口：steer/respond/admit/promotion 等 enqueue 路径继续拒绝；本里程碑不授权绕过 unknown 或自动重做 IO。可信运维沿用既有机制处理不确定性不属于六动词交付；测试夹具可销毁临时库重建，但不是生产恢复证明，偏差台账单列。
- TEMPORARY/public CREATE 收权由 ce_run setup 在专用库中建立；ACL 证明仅适用于满足这一部署前提的专用库，不能泛化到其他 stage 测试库。全库 stale 回收的范围与 Worker 停止时无自动回收也须记入 README/偏差台账。
- CE 参数 schema 是私有函数代码闭集，与 tools.param_spec 模板无关；本阶段仅允许 spawn_subsession/{task}，且执行仅为带 simulated 标记的 Fake adapter，不证明原生 spawn、预算或子会话行为。扩大工具集合须在后续 stage 显式扩 schema 和 adapter，不能默认开放目录中全部 enabled 工具。
- operations 是可变账本，wakes/events 为追加历史；无自动 TTL/GC，不能误称 operations append-only。未来清理须协调 CE 五表与 sessions/effects，本阶段临时库整体 DROP。
- 单 run cancel、queuedFollowUp、waiter cursor wake、reserved generation/continuity、Fake-only helper 均明确记入偏差台账；不宣称 CE app 或 agent_manage 完整等价。
- 普通 v13 的 judge/context_refresh/plan/spawn/fanout/triage/quota/govern 仍留原机制，但不是在同一个 CE run 上混用旧驱动。
- spawn writer 白名单回退、冻结白名单放宽、SECURITY DEFINER 身份、双事实终态和 late receipt 租约是重点风险；用专门反例而非删 gate 缓解。

## 8. Implementation Order & Verification

### 8.1 实施、收尾与提交
1. 先确认全部 22 路径、调用依赖、base/phase_d 字节与冻结负例；设计 W2 适配，再清理 driver/文件并更新 load。W1/W2 中间红灯不称完成。
2. 创建四文件，实现 schema/权限/scoped discovery/claim，再 T1 六动词与 promotion，再按同一 T2 原子完成 receipt、后继 admit 与 publish；补齐 Fake/Wait 与全部探针。
3. **脏树测试不得要求提前 git add。** 冻结门禁的文件集合在限定 v13 路径内合并 git ls-files --cached 与 --others --exclude-standard，并过滤已删除路径；缺文件/extra.py/受保护字节改动仍拒绝。§5.3 的“tracked”指最终交付闭集，不是测试前已暂存。
4. 实跑 §8.3 核心门禁及全部保留的 v13 回归 gate，全部成功后更新 stage README、load 注册、覆盖矩阵与偏差台账，记录真实日期/检查数/命令；不把 reserved 夹具覆盖记成生产能力，不因 gate 红而自行豁免。
5. 提交前独立人工核对 `git diff fb295ac6c7459bb98dac57e37883af549d2d8a4c -- v13/plan_arm/test_plan_arm.py`，确认非 `r0_*`/`r1_*`/`test_stage_bytes` 的受保护改动为空，并记录核对结果，不能仅依赖会自检自身的冻结 gate。git status，按路径 git add（含精确删除，不用 -A/.），git diff --cached 与 status 核对；检查凭据，commit 不跳 hook。本计划/上游报告若尚未跟踪，交付时逐项确认并显式加入，不能全量收进 unrelated untracked。
6. 提交后重跑 §8.3 同一完整 gate 清单（不只七道核心），均绿立即 git push origin main。失败停该步，不 push、不跳 hook；修正后重跑并追加修复提交，不 force/reset。远程拒绝先 fetch，不能安全 rebase 时问用户。

### 8.2 test_ce_run.py 具名覆盖矩阵（16 组）
| # | 探针名 | 必须验证 |
|---|---|---|
| 1 | native_load_untouched | Stage 1–39 函数/表/ACL/SQL 字节基线，新 SQL 装载前后比较 |
| 2 | native_plan_arm_closed_set | 四文件闭集，未跟踪新文件可测；extra.py、缺文件、越界 stage 反例 |
| 3 | native_frozen_driver_bytes | 唯一 R1 sentinel、哨兵外 base 字节、无 controller/第二个 advance |
| 4 | native_start_identity | 新 run=session、initial/running、空输入/外来 session_id/超界拒绝、并发同 request 唯一；root/child 私有 INSERT、parent 授权、next_seq−1 cutoff 的实际继承边界与双连接串行、空父零写 parent_prefix_empty、重放不重算 cutoff、异常整体回滚 |
| 5 | native_poll_pure | READ ONLY 查询、表/revision/wake 零变、未授权/不存在/stale registration 合成 expired |
| 6 | native_wait_cursor | steering wake 优先于 actionable snapshot、timeout/finite 参数、追 epoch、自打断抑制、普通 wake 不遮蔽、重复 wait 游标、丢通知重读；superseded 夹具明确标 reserved |
| 7 | native_cancel_scope | ordinal/run 不变、pending closed、仅目标 ready 取消、CE/sessions 同步、claimed 迟到记账、子 run 不受影响 |
| 8 | native_steer_paths | active 不换 epoch 且实际输入消费；steer 后旧 ready/claimed driving 允许结算但 publish 被 token 围栏归档；terminal 含 cancelled 复活/CAS stale/use_respond；instruction 通道 |
| 9 | native_respond_once | human interaction_ref/one-of、ce 通道、错误 id/二次消费拒绝、原 request replay、两通道都 llm 续跑 |
| 10 | native_acl_roles | 非 superuser operator/self/parent 正例、陌生 actor/worker/recall 写负例、recall 读、SET ROLE 降权、CE 表直接 DML 拒绝、TEMP/public 同名对象创建拒绝；helper 直调 42501、唯一 owner 例外元数据、宿主不可切换 spawn_owner、既有角色/ACL 不变及超级用户直接 INSERT 仍被原 trigger 拒绝 |
| 11 | native_io_boundary | T1/claim 提交、IO 前/内 IDLE、T2 提交、同 effect 并发 claim 单胜、不同 run 不串领；route 裸读 CE 表拒绝，discovery 按 run/epoch 返回 ready/queued 闭集，与 promotion 及多个 queued steer 的顺序一致，重启仅凭 run_id 可接力；queued 工具在目录 disabled 后 promotion 必须归档并继续后续队列，保持正常 T2 完整续接；执行载荷仅经 claim.request 与既有 events/effects 读取，discovery 不扩闭集 |
| 12 | native_receipt_fences | request mismatch、replay/outcome 冲突、closed 保持、archive 由第二连接确认证明已提交；事务屏障覆盖两个合法锁序：旧 T2 已 BEGIN 但未取 session/run 锁时让 steer/cancel 先获锁提交，旧 T2 后记账不发布；旧 T2 已获锁时控制事务必须等待其 COMMIT，随后控制状态成为最终快照；在 accept 已进入但尚未 COMMIT 的断点注入崩溃，确认 receipt、后继 admit/publish 同回滚且不重复 IO。不得编排双方持冲突行锁却要求后者先提交的死锁测试 |
| 13 | native_unknown_vs_archive | 真实迟到 claimed 结算不砖化；tokens 失配不解 lease；claim 后/IO 后丢失经回收 unknown，各 enqueue 阻断；底层异常不假结算 |
| 14 | native_operation_handoff | 同 epoch 多相同参数 tool 不碰撞、独立完成、T2 自动接力、queued 无 effect 禁 IO、不自动结束 run；spawn_subsession 原样 task 的真实 schema 正例与缺失/空串/非字符串/超长/额外键负例；无 CE schema 工具拒绝；来源/index/id/envelope 负例与确定性重放；Fake adapter simulated 结果且不创建 session |
| 15 | native_snapshot_once | publication 存储重放、revision conflict、终态新提交拒绝、pending_work、waiting human producer/终态双事实；未消费 interaction 时旧 running、第二次 waiting、terminal publish 均返回 interaction_pending 且 interaction/binding/effect/revision 不变，随后精确 respond/instruction steer 才能消费 |
| 16 | native_static_setup | Fake-only/无网络 import/pg_sleep/宿主裸 CE DML；setup 同名库拒绝、创建失败不误删、扩展/导入零副作用 |

### 8.3 验证命令（提交前后均退出码 0）
```bash
UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py
UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py
UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
UV_FROZEN=1 uv run python v13/spawn/test_spawn.py
UV_FROZEN=1 uv run python v13/acl/test_acl.py
UV_FROZEN=1 uv run python v13/twophase/test_twophase.py
```

上述七道是核心集合，不是回归全集。提交前后均须运行全部保留的 `v13/**/test_*.py`（包括 `goal_supervise`、`frontier_gap`、`real_chain`，以及没有 SQL stage 的驱动测试），每个脚本用 `UV_FROZEN=1 uv run python <path>` 独立执行，任何非零退出都阻止提交/推送。2026-10-16 当前清单有 52 个脚本，§5.2 精确退役 6 个、加入 ce_run 后预期 47 个；W1 用实际文件枚举核对并把最终路径/命令/退出码清单写入 README，不能靠过滤失败测试缩小集合。既有 setup 按各自 `files_through(stage)` 装载，并非都装到 40；ce_run 的装载前后基线探针负责新增 SQL 的 Stage 39→40 影响，全量脚本负责 loader/冻结检查与旧入口回归。不得把旧 setup 全改成装载到 40。

load.py dirty-window 的固定退役字面集合如下；必须比较带重复计数的行集合（或排序行列表），以拒绝重复删除，且只在 diff 含删除行时要求恰为这十行。无删除行时仍须经过 base 纯尾追加/闭集检查：
```python
retired_load_lines = [
    '    V13_ROOT / "agentctl" / "v13_agentctl.sql",',
    '    V13_ROOT / "agentctl_verbs" / "v13_agentctl_verbs.sql",',
    '    V13_ROOT / "goal_workflow" / "v13_goal_workflow.sql",',
    '    V13_ROOT / "external_exec" / "v13_external_exec.sql",',
    '    V13_ROOT / "ce_map" / "v13_ce_map.sql",',
    '    "agentctl": 40,',
    '    "agentctl_verbs": 41,',
    '    "goal_workflow": 42,',
    '    "external_exec": 43,',
    '    "ce_map": 44,',
]
```

## 9. References
- docs/investigations/ce-agent-run-six-verbs-for-v13-2026-10-14.md
- docs/investigations/v20-epoch-operation-for-v13-ce-control-2026-10-14.md
- docs/reviews/v13-ce-run-six-verbs-plan-critique-2026-10-15.md
- prompt-exports/oracle-plan-2026-10-15-164431-v13-ce-oracle-a3effd-66ce.md（Generated Plan；本地忽略文件，不作提交必需）
- v13/schema/v13_core.sql、v13/acl/v13_acl.sql、v13/twophase/v13_twophase.sql
- v13/plan_arm/{v13_plan_arm.sql,test_plan_arm.py}、v13/fair_claim/test_fair_claim.py、v13/loop_driver/{driver.py,test_loop_driver.py}

## 10. Review Disposition
本次是计划修订，不代表实现/测试完成。下列映射对应 critique 的全部编号（含子项），供实施时回查。

| 评审编号 | 修订处置 |
|---|---|
| 1.1、3.1、5.1 | §4.2.5：active 同 epoch、terminal 新 epoch、cancelled 显式复位 |
| 1.2、4.3 | §4.2.6：human/ce 均同事务创建后续 llm 工作，不空转 |
| 1.3、4.4、5.6 | §4.2.6/9：human producer/binding、interaction_ref/one-of；显式 ce 通道不绑定 human |
| 1.4、2.10 | §4.2.7/§4.4：锁序、明确空 claim tokens、仅 scoped claim |
| 1.5、2.11、3.5 | §4.1/§4.2：admission_result/result/publications 分存，请求/结果重放不混用 |
| 1.6、4.8 | §8.2：16 组具名探针、崩溃/通知/多连接竞态 |
| 1.7、2.13（setup） | §5.1：前后装载分界、库名/扩展/所有权清理守卫 |
| 1.8、5.2 | §7：只宿主直调，不加 tools/controller |
| 1.9、4.1–4.2、4.5 | §4.4/§6/§7：ready/claimed 恢复边界、单入口、迁移/取消/数据保留 |
| 1.10 | §4.2：大小限制；返回闭集扩为八键以携带 wake_id，明确偏离七键基线 |
| 1.11 | §3.2/§4.4：复用 LoopDriver 时序而非重做其控制面 |
| 2.1、4.6 | §4.3：definer、真实 caller、表/函数权限矩阵、非 superuser gate |
| 2.2–2.4、5.3–5.4 | §4.2.8/§4.4：真实 T2 结算 claimed、自动 promotion、禁止 IO 后造 effect |
| 2.5 | §4.2.3/5：wake epoch 归属与跨 epoch/wake 水位查询 |
| 2.6、3.2、4.7 | §3.2/§4.2.4/5：单 run 取消/清槽，不走子树 v13_cancel；同步 sessions；固定锁序 |
| 2.7、2.13（receipt） | §4.2.8：accepted/replay/stale、实际 effect outcome、异常子事务/回滚边界 |
| 2.8、3.4 | §3.2/§4.2：会话级 unknown 每个 enqueue 路径自查 |
| 2.9（effect 身份） | §4.1/§4.2：operation_id 入 request，非空 effect_id 唯一 |
| 2.12、5.5 | §4.1：reserved 字段/无 producer 声明，不编造 runtime 覆盖 |
| 2.13（publish/status） | §4.2.9：终态幂等优先、旧发布围栏、sessions.waiting 映射 |

### 10.1 Oracle 初审修订（2026-10-16）
初审导出：`prompt-exports/oracle-review-2026-10-16-122214-new-chat-99a280-0c2d.md`（忽略文件，不作为交付必需）。这是计划复核，不代表任何实现测试已运行。

| 初审项 | 处置 |
|---|---|
| P1-1 stale 回收触发者 | §4.4：Worker 每轮/重启首轮独立事务调用全库 requeue；明确非 scoped、无 Worker 无自动回收，probe 13 |
| P1-2 receipt revision/CAS | §4.2.8/§4.4/§6.1：receipt 不推进 CE revision/wake，返回锁内 revision，T2 原子 publish 或固定 CAS 拒绝并发冲突 |
| P2-3 旧 ready effect | §4.2.5：允许已绑定旧请求执行/结算，driving 围栏拒绝发布；新输入由 steer 后续 effect 消费，probe 8 |
| P2-4 controller 测试依赖 | §5.3：已搜索 test_loop_driver 无引用；不修改冻结 import/常量，W1 复核 |
| P2-5 operator | §4.3：真实 route/超级用户 + actor=NULL，非 superuser/SET ROLE 门禁 |
| P2-6 cancel/complete | §6.1：实读 ACL，cancelled outcome 才检查 cancel not pending；真实 succeeded/failed 保持原 outcome，probe 7 |
| P2-7 wait 优先级 | §4.2.3/探针 6：授权/身份与 continuity 判定之后 steering wake > actionable snapshot > timeout |
| P2-8 wake reason | §4.2.9：terminal 与 snapshot 明确分流，不把 receipt 当 snapshot |
| P2-9 回归集合 | §8.1/8.3：提交前后全量保留的 v13 测试脚本，明确旧 stage 不都装到 40 |
| P2-10 dirty-window 放行 | §5.3/8.3：固定十行精确比较并保留负例/clean-tree/base 检查 |
| P2-11 并发交错 | 探针 12：屏障覆盖控制先获锁、T2 先获锁两种可执行交错，不要求不可能的提交顺序 |
| 残余风险 | §7/8.1：单入口依赖部署；unknown 无 CE 恢复出口；ACL 专用库前提；人工独立核对冻结自检文件 |

### 10.2 Oracle 二次复核修订（2026-10-16）
二次复核导出：`prompt-exports/oracle-review-2026-10-16-143409-new-chat-bf4948-b49b.md`（忽略文件，不作为交付必需）。主 Oracle 因 interactive inactivity watchdog 失败；附加 Oracle 返回实质意见且未发现新增 P1，不能标记整个 Oracle 组通过。以下项目已核对处置，待终审。

| 二次复核项 | 处置 |
|---|---|
| fair_claim self-diff | §5.3.4：实读 paths 不含自身，条件性风险不成立；保留 plan_arm 的 fair_test_ok 闭集，不放宽自身白名单 |
| superseded tool_calls | §4.2.7/§4.4：命名零写拒绝；派生输入将未准入孤儿 call 转普通历史文本，不改原始事件、不伪造 result；已准入工具继续结算 |
| instruction 结果形状 | §4.2.5：human 通道固定 response 正文 one-of，CE 通道不造 human |
| setup 基线顺序 | §5.1.2：fair_claim → 收权/owner → before → ce_run → after；数据库/schema 收权独立核对 |
| wait epoch+actionable | §4.2.3：steering > actionable（即使 epoch 前进）> epoch_advanced > waiting/timeout；逐 wake 携 epoch 游标，防跳过中间 wake |
| SECURITY DEFINER owner | §4.3：owner 须满足既有 v13_control_operator 判定，终审后收敛为专用库受信超级用户 owner；外部 actor helper 仍取真实 caller |

### 10.3 Oracle 终审处置（2026-10-16）
终审导出：`prompt-exports/oracle-review-2026-10-16-145147-new-chat-e4057c-df21.md`（忽略文件，不作为交付必需）。附加 Oracle 明确“无 P1”，确认此前处置映射与正文一致；主 Oracle 再次因 interactive inactivity watchdog 失败，整组状态 failed，不能记为完整 Oracle 通过。以下三项 P2 已按终审建议补齐，补齐后未再次调用 Oracle；本次仅修订计划，未实现 Stage 40、未运行实现 gate，也未完成里程碑提交/推送。

| 终审项 | 处置 |
|---|---|
| respond/admit 枚举 | §4.2.6：respond wake=snapshot；§4.2.7：会话级 unknown 零写拒绝 reason=unknown_wall |
| owner 权限路径 | §4.3：专用临时库固定受信超级用户 owner，不交付非超级用户 owner 路径，不扩大 route 既有表/函数权限；非超级用户宿主验证 ACL |
| Worker/Wait 连接身份 | §4.4：Worker 用非超级用户 route 登录，Wait 用 route/recall；不复用 v13_worker，不使用 definer owner 登录 |

### 10.4 Oracle 窄范围复审与综合修订（2026-10-16）
本轮 Oracle group `41F3DE5F-5A56-4C8C-BB72-95E6126814DC` 正常完成，Codex 与附加 lane 均返回；Codex 输出见 `prompt-exports/oracle-review-2026-10-16-224202-new-chat-598607-d334.md`（忽略文件，不作为交付必需）。两 lane 对下列三个 P1 与 wait 响应例外意见一致。本节记录审核反馈及正文处置；修订后尚未再次复审，不能宣称该版本计划已获审核通过。本次仍未实现 Stage 40、未运行实现 gate。

| 本轮复审项 | 级别 | 处置 |
|---|---|---|
| route 无表权限时 Worker 无法发现 queued/ready 工作，重启及 steer/respond 后无法仅凭 run_id 接力 | P1 | §4.3/§4.4 新增 route 可执行、actor 授权、单 run/当前 epoch 闭集 `v13_ce_discover_work`；不授表权限，不锁/写状态；探针 11 覆盖裸读拒绝、ready/queued、promotion、多条 queued steer 与仅凭 run_id 重启接力 |
| accept 已 COMMIT、后继 admit/publish 尚未提交时崩溃，可能留下 running 空队列或丢终态/工具续接 | P1 | §4.2.8/§4.4/§6.1 将正常 receipt 与完整后继 admit/publish 提升为唯一同 T2 原子 COMMIT 路径，禁止 split COMMIT；定义稳定内部 request_id、COMMIT 回应丢失的存储回执重放，以及 probe 12 的 accept 前 COMMIT 崩溃注入。事务未提交时整体回滚，重启不重复 IO；无真实回执的已执行 IO 最终按租约到 unknown，继续受既有 unknown 墙保护 |
| 新 publication 可覆盖未消费 interaction，导致丢题/孤儿 human effect | P1 | §4.2.9/探针 15：存储重放优先后，任何新 publication 遇非空 interaction 均零写 `interaction_pending`；只有精确 respond/instruction steer/cancel 消费；验证 interaction/binding/effect/revision 不变 |
| 通用返回要求 `ok`，wait 固定八键不含 `ok` | P2 | §4.2 通用规则明确 wait_check/ce_wait 的全分支唯一结构例外及 reason 语义，探针 6 断言精确闭集 |
| 冻结 helper 锁重入、recall actor、start sessions 默认值、load_ce_run、fair_claim 路径白名单、origin_run_id 语义、admit_tool validator 时点 | P2 | 分别在 §4.2 通用规则、§4.3、§4.2.1、§5.1.2、§5.3.4、§4.2.3、§4.2.7 明确锁序重入、NULL 只读 operator、sessions 列/默认值、单 SQL 局部装载、精确六路径 diff 集合、headless 身份依赖及准入期工具验证 |

### 10.5 实施期 owner 接缝裁决（2026-10-17）

首轮 W3 实库探针确认：`v13_sessions_insert_owner` 对超级用户直接 INSERT 也抛出 `v13: sessions insert owner`；`v13_open_session` 无显式 SID/parent 参数，后补 parent/cutoff 又被 `v13: fork columns are write-once` 拒绝。用户授权由 Oracle 按实用性裁决并继续工作流，无需再次确认。

Oracle group `F72AD343-B761-4573-A710-AB02C4C82FE9` 两路正常返回，共同支持唯一私有 INSERT helper 和 child cutoff 修订。导出：`prompt-exports/oracle-plan-2026-10-17-020946-new-chat-8cbd74-9da4.md`（忽略文件、实施上下文，不作为提交必需）。采用主 Oracle 的具体接口与验证要求：RETURNS uuid、SQL 单 INSERT/RETURNING、空父 reason=parent_prefix_empty、setup 全量基线及单次调用/OID 清理；不采用附加 lane 的“setup 无需修改”或 void 返回建议，因为现有 setup 尚不能证明完整 owner/ACL 与安全 cleanup。

- 唯一私有 helper owner 例外详见 §4.3，不提升既有角色、不更改冻结函数/表 ACL、不禁用 trigger。
- cutoff 修订为父锁内 next_seq−1，实施代理必须核验实际父前缀读取谓词及谱系读取，不能仅照抄 spawn 样板。
- W3 草稿的锁序、receipt 围栏/重放、promotion/human 交付、publication、wait/discovery 仍有缺口，必须在 W3 验收前完成，不能转记为 W4 测试项。SQL 可装载不等于 W3 完成。
- 本裁决不形成独立里程碑。最终仍按全部 47 脚本脏树与提交后复验、单 Stage 40 提交和推送执行。

### 10.6 实施期工具 schema 接缝裁决（2026-10-17）

实读确认 tools.param_spec 是参数提问模板，不存在计划此前假定的每工具 params_schema；冻结 v13_llm_tool_calls 仅接受 spawn_subsession/{task}。拒绝通过清空 params 绕过错误 validator，因为那会丢弃调用语义。

Oracle 同组继续裁决：主 lane 因 interactive inactivity watchdog 失败，附加 lane 正常返回；整组不是成功审核。导出 `prompt-exports/oracle-plan-2026-10-17-031346-new-chat-8cbd74-2c43.md`（忽略文件）。采用附加 lane 的私有固定 schema helper、单工具准入闭集、真实 jsonb_matches_schema 与显式 Fake adapter 方案，已落实到 §4.2.7、§4.4、§7、probe 11/14。schema 不写既有 policy/catalog 行，不改变 Stage 1–39 结构或 ACL。

协调者纠正导出中的两处越界：投影从既有 events/effects.request 连接来源，不能裸 JOIN CE operations；discovery 保留原计划的当前 epoch pending 摘要契约，不按导出新写的“六键”另改结构。setup 是否需适配以实际新增私有函数的 owner/ACL 验证为准，不把导出的“零修改”当作跳过检查的理由。promotion 归档失效工具后继续队列，正常 T2 仍必须完整续接。

本裁决不代表 W3 验收或门禁通过，不新增里程碑。

### 10.7 W4 实跑接缝修正（2026-10-17）

W4 的真实非超级用户探针暴露两个运行缺口：root 的陌生 actor 通过 nullable parent 比较得到 SQL NULL，授权 helper 必须统一 fail-closed 返回 false；route 直调冻结 invoker stale 回收函数缺少 pgmq schema USAGE。后者采用 §4.4 的窄 CE definer 维护包装，旧函数、角色与 pgmq/base ACL 不变。SQL/setup/Worker/文档分别在各自文件中接线，新增入口纳入 ACL 精确矩阵。它沿用已定的全库短事务维护语义，不构成新控制动词或里程碑；必须重新实跑相关门禁后才能填绿。

### 10.8 Stage 40 dirty-tree freeze amendment (2026-10-17)

This amendment is limited to freeze validators and named guard bodies. It does not relax runtime assertions, SQL/setup/CE tests, driver or SQL byte proofs, or arbitrary dirty paths.

- `test_stage_bytes` path allowances are exact files only: the R0 sentinel SQL and README/guard files reached through neighboring stage pathspecs; `fair_claim` names the four newly adapted guard tests. `goal_supervisor`'s cached-only loader is handled by the exact untracked `v13/ce_run/v13_ce_run.sql` fallback, while fair_driver's supervisor allowlist compares every goal-supervisor byte except the named `test_stage_bytes` body. Every remaining path is still compared byte-for-byte.
- The body-only exception is explicitly named for `v13/workspace_admit/test_workspace_admit.py:test_stage_bytes`, `v13/pi_parity/test_pi_parity.py:{protected_dirty,run_guard}`, `v13/pi_ports/test_pi_ports.py:{protected_dirty,run_guard}`, and `v13/read_tools/test_read_tools.py:{protected_dirty,run_g}`. `protected_dirty` is included because the guard itself must recognize the other explicitly amended guard files; `run_guard`/`run_g` are included because they are the candidate entry points that enforce that recognition. The validator preserves each approved function's decorators/signature and compares all bytes outside approved bodies, including module comments and unrelated functions. Negative mutations cover an unrelated module comment and an unrelated existing function for every body-only file.
- `v13/goal_supervisor/test_goal_supervisor.py:test_stage_bytes` is a separate phase-D guard allowance consumed by fair_driver's `supervisor_allowlist_not_edited`: the rest of that directory remains exact-byte frozen, and the guard body has the same signature-preserving, module-comment/unrelated-function negative proof.
- Baselines are pinned to the first commit that introduced the corresponding protected file/contract, rather than silently using `HEAD`: workspace admit `2f7d515` (parent `12438a5`, adds the test file); pi parity `fcec59d` (parent `8b15588`, hardens its evidence contract); pi ports `4436cd8` (parent `e218e5c`, adds the port boundary guard); read tools `30cdfd6` (parent `dc69001`, aligns the read-tool port/spec). `git show --stat` identifies the named file in each commit. These pins isolate the pre-existing contract bytes while the shared R0/phase-D bases continue to prove the rest of the protected tree.
- `r0_source_scope` still proves the fixed base/phase-D SQL and module bytes; its four body pins are not a general rebaseline and do not authorize unrelated differences.

Legacy affected-script evidence after the last validator edit (CE deliberately not rerun while the independent runtime review owns `v13/ce_run/v13_ce_run.sql` and `v13/ce_run/test_ce_run.py`):

| Script | Exit | Checks/evidence |
|---|---:|---|
| `v13/plan_arm/test_plan_arm.py` | 0 | 104/104 |
| `v13/fair_claim/test_fair_claim.py` | 0 | 136/136 |
| `v13/fair_driver/test_fair_driver.py` | 0 | 40/40 |
| `v13/frontier_gap/test_frontier_gap.py` | 0 | 59/59 |
| `v13/goal_supervise/test_goal_supervise.py` | 0 | 172/172 |
| `v13/goal_supervisor/test_goal_supervisor.py` | 1 (documented) | 74 checks; only trailing `unattended_continuation: v13: supervisor: ask_user` |
| `v13/workspace_admit/test_workspace_admit.py` | 0 | 65/65 |
| `v13/loop_driver/test_loop_driver.py` | 0 | 91/91 |
| `v13/pi_parity/test_pi_parity.py` | 0 | 123 pass lines |
| `v13/pi_ports/test_pi_ports.py` | 2 | 228 pass lines; toolchain skip semantics |
| `v13/read_tools/test_read_tools.py` | 2 | 156 pass lines; toolchain skip semantics |

Logs are preserved under ignored `prompt-exports/stage40-final-*.log`. CE validation is **pending** the separate runtime-review corrections; it must run once at the end afterward. This bounded legacy work does not claim the complete 47-script regression, staging, commit, or push.

### 10.9 goal_supervisor Fake gate 与授权拒绝探针分层（2026-10-17）

按用户授权重新设计验收契约：固定无参数命令只有全部原有 Fake 检查成功后才 exit 0，并声明不构成无人值守授权；精确 `--unattended-continuation` 旗标保留原 ASK_USER 拒绝尾部及 exit 1；任何其他参数在任何检查/建库前仅打印 usage 并 exit 2。`accept_unattended.py` 及环境授权规则不变。Oracle 附加 lane 提出此方案，主 lane watchdog 失败，不声称 Oracle group 通过。

新增例外仅为 `v13/goal_supervisor/test_goal_supervisor.py:main` 函数体；签名/decorator、模块级字节、run 与业务断言仍冻结。`plan_arm:r1_phase_d_prefix_allowance` 验证 default/probe/bad args 的可执行 Fake 控制流、故障传播、清理和负例；`fair_driver:test_static` 精确识别此 body-only 例外与 README 纯追加，`test_stage_bytes` 的精确路径集合纳入该 README。无一般 main/run 豁免。静态交接见 `prompt-exports/v13-goal-gate-redesign-results.md`；实际 exit 证据待补，不能凭静态检查填绿。

### 10.10 嵌套回归 trace 恢复边界（2026-10-17）

批准仅在 `v13/read_tools/test_read_tools.py:run_e4` 函数体增加子进程逐项 finally 恢复：精确保存/恢复 `v13/pi_parity/traces/pg.jsonl` 的调用前字节及存在性，不能用 HEAD 覆盖用户预存修改、不能宽泛 clean/reset。原子脚本枚举、命令、timeout、退出码和失败累计语义保持；有价值的生成 trace 先留入忽略证据目录。`plan_arm:r0_source_scope` 仅为该函数新增 body-only 例外并验证签名/模块字节不变及恢复/失败语义反例；不放宽业务断言或其他文件。外层完整回归也须在每条命令后精确恢复同一已知测试产物，不等全批结束。实现/实跑尚待验收，此条不构成 gate 通过或新里程碑。

### 10.11 Oracle 窄范围复审记录（2026-10-17）

Oracle group `71B20DB2-B37C-4FC1-B90D-ACCA5E1AF4E7` 已完成两路 scoped review。其发现已按本轮授权静态处置：`r1_phase_d_prefix_allowance` 对 `fair_claim:test_reread` 仅允许精确 loader-tail 替换并保留其余字节/签名/decorator，补充断言与签名负例；`e4_restore_ok` 补充 child pre-write error、untouched/deleted trace 与 second-child failure 夹具；README/本节事实口径已校正。该复审基于 selected scope，不是 CE runtime approval、milestone approval 或 all47 regression approval；未运行 gate，不形成提交/推送条件。


### 10.12 pi_parity 历史冻结检查的提交后窗口修正（2026-10-17）

提交后净树复验在 #30 pi_parity 首红处暴露设计缺口：`run_guard` 的 `historical_frozen` 检查拒绝 `PI_PARITY_BASE..HEAD` 间对 `FROZEN_PREFIXES`（`v13/read_tools/`、`v13/pi_ports/`）或 `v8/` 的任何已提交改动；§10.8 对 pi_ports/read_tools 两守卫文件的 body-only 适配在脏树窗口内合法（未提交），里程碑提交落地后该两项进入 committed_names 而被拒。修正仅限 `run_guard` 函数体（§10.8 既有 body-only 制度内）：新增本地具名集合 `stage40_committed_guards`（恰为 `v13/pi_ports/test_pi_ports.py`、`v13/read_tools/test_read_tools.py` 两项）并在 `historical_frozen` 中排除；两文件的字节正确性仍由各自 gate 的 pin 基线（4436cd8/30cdfd6）body-only 校验证明，其余任何 frozen-prefix 或 `v8/` 已提交改动仍被拒绝。模块级字节、签名、其余函数不变；修正后须重跑受影响 gate，按 §8.1.6 追加修复提交并以同一 49 项清单净树复验后推送。首红证据：`prompt-exports/w4-v99-postcommit-20261017/`（#1–29 绿，#30 红）。
