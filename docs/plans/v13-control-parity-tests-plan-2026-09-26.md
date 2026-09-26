# v13 控制面对照测试计划：RP-CE / LoopX 控制功能逐项对齐（2026-09-26）

## 目标（用户原始诉求）

pg-agent v13 已交付控制面（stage 17–20，`v13/{control,spawn,fanout,triage}`，20/20 gate 绿）。
本计划要做三件事：

1. **调查** repoprompt-ce 与 loopx 两仓的「控制 Agent 运行」代码与测试，产出逐项功能清单（行为合同 + 源码锚点 + 两仓各自的测试锚点）。
2. **一一对应**撰写 v13 控制功能全面测试；LLM 相关测试用 **StepFun 真实 API**（key 在 `~/.zshrc`）。
3. **完成对照清单**：RP-CE 与 LoopX 的哪些控制功能在 v13 一模一样实现了、哪些改变了（含裁决依据）、哪些完全没有实现。

## 交付物

| # | 交付物 | 路径 | 性质 |
|---|---|---|---|
| D1 | RP-CE 控制功能盘点卷宗 | `prompt-exports/parity-rpce-2026-09-26.md` | 工作资产（gitignored） |
| D2 | LoopX 控制功能盘点卷宗 | `prompt-exports/parity-loopx-2026-09-26.md` | 工作资产（gitignored） |
| D3 | v13 现状盘点卷宗 | `prompt-exports/parity-v13-2026-09-26.md` | 工作资产（gitignored） |
| D4 | v13 控制面全面测试套件 | `demo_v13/`（新文件，不改既有） | **commit** |
| D5 | 对照清单文档 | `docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md` | **commit** |

## 工作项

- [x] **W1（explore）** RP-CE 控制功能盘点 — 完成 2026-09-26，产出 F1–F30 → `prompt-exports/parity-rpce-2026-09-26.md`（3 处锚点漂移已记录）。：以 `prompt-exports/cpm-probe-b-rpce-mechanisms-2026-09-25.md` 为底，核验锚点仍有效，补齐「测试锚点」（Tests/ 下哪些 XCTests 覆盖该功能）。范围：五原语（startOrResume/sendUserMessage/interruptTurn/respondToPermissionRequest/shutdown）、agent_run 六 op（start/poll/wait/cancel/steer/respond）、worktree 管理、会话持久化与恢复、审批交互（interaction id 匹配语义）、fork/handoff、epoch/cursor 判定。输出=编号功能表 F1..Fn，每项：名称/源码锚点/行为合同（可断言不变量 3–6 条）/RP-CE 测试锚点。
- [x] **W2（explore）** LoopX 控制功能盘点 — 完成 2026-09-26，产出 L1–L41 → `prompt-exports/parity-loopx-2026-09-26.md`（要点：LoopX 无 mid-turn interrupt，靠准入/结算门控）。：以 `cpm-probe-c-loopx-mechanisms-2026-09-25.md` 为底，同上格式。范围：六层文件控制面（registry/goalState/runLog/runHistory/attention/quota）、settlement 链（writeback→spend→closeout）、scheduler/turn_driver、heartbeat、handoff、coordination/collaboration、cancel/interrupt、multi_subagent/steward_executor（spawn 族）、command_receipts/outbox/leases（已知 v13 明确不搬，仍要入表）。测试锚点=tests/control_plane*、tests/control_plane_ts。
- [x] **W3（explore）** v13 现状盘点 — 完成 2026-09-26，产出 V1–V47 + 残留 R1–R13 → `prompt-exports/parity-v13-2026-09-26.md`。：stage 17–20 的 SQL/函数/事件全集 + demo_v13 接线（e2e_control.py/e2e_spawn.py/control_smoke.py/approval_contract.py）+ 既有 gate 覆盖了什么 + 哪些是 fake/真实 + 已知残留（closeout/inbox_residual、quota spent·voided 事件族、material_cap human、真 worker 第四务线、children_terminal P3 未用等）。
- [x] **W4（pair）** 测试套件 — 完成 2026-09-26：`demo_v13/parity/`（9 组 + README + parity_all），StepFun step-3.7-flash，两连绿 + 编排器独立复跑绿（9/9）。注意：demo_v13/ 整体在 .gitignore（:33），套件为未跟踪工作资产（与既有真实 API 脚本先例一致）。：读 D1–D3 + 本计划。对 v13 已实现的每个控制功能写 1:1 对应测试（StepFun 真实 API 走 demo_v13 Settings.load 换端点）；v13 未实现的功能不写测试（进 D5 的「完全没实现」）。产出独立可跑脚本（`uv run python ...` 退出码 0=通过），两次复现全绿；跑 stage 17–20 gate 防回归。
- [x] **W5（design→pair）** 对照清单 D5 — 完成 2026-09-26（design 通道 ACP 故障，pair 通道一次成稿）：`docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md`。RP-CE 30 条：改变 17 / 没实现 13；LoopX 41 条：改变 13 / 没实现 28；一模一样 0（严格含失败模式标准）。未裁 3 条已对照 R3 链确认。：三分栏（一模一样/改变/完全没实现），每条带两侧锚点 + 证明测试 + 「改变」须引裁决依据（R1/R2/R3 链或迁移报告「明确不做」节）。
- [x] **W6（orchestrator）** 收尾完成 2026-09-26：抽查验证（F23 latch 无写入者 fanout:85、repair_cap 跳续传臂 triage:750）；parity 套件三连绿（W4×2 + 编排器×1，stage 17–20 gate W4 跑绿且无 tracked 文件变更）；commit `0ce970e` 已推 origin/main（两件 docs；套件在 gitignored demo_v13/ 按先例不跟踪）。

## 硬约束

1. **stage 1–20 字节冻结**：不改 `v13/` 任何既有 SQL/test/README；测试套件只新增文件。
2. 测试是独立脚本（退出码 0=通过），沿用 `demo_v13/e2e_control.py` 接线范本（harness worker + Settings.load）。
3. **外部 IO 一律不进数据库事务**；LLM 调用只在驱动器侧。
4. StepFun 环境换法（已实证）：`export DEEPSEEK_API_KEY=$STEPFUN_API_KEY OPENAI_API_URI=$STEPFUN_CODING_PLAN_API OPENAI_MODEL=step-3.7-flash`；`STEPFUN_API_KEY`/`STEPFUN_CODING_PLAN_API` 在 `~/.zshrc:188-189`。**非交互 shell 必须先 source ~/.zshrc**。备用模型 step-3.5-flash-2603 / step-3.5-flash（均 18/18 验证过）。
5. DB：`uv run server.py start|uri`（pgembed PG18.4）；控制面库 setup 见 `demo_v13/setup_db_control.py`。
6. 不重开已裁结论：R2 §1–§3、R3/R3a/R3b/R3c 链条文是「改变」判定的依据源，不是待议项。
7. 提交：按路径 `git add`（禁 `-A`/`.`），`v13: <祈使句摘要>`，结尾 Co-Authored-By 行，push origin main。

## 先验资产（不重做）

- 映射总表：`docs/analysis/v13-control-plane-migration-2026-09-25.md` §2（RP-CE 五原语/六 op/LoopX 机制→PG 落地）
- 谱系文：`docs/analysis/agent-control-plane-codex-rpce-loopx-2026-09-21.md`
- 裁决链：`docs/reviews/v13-control-plane-oracle-r{1,2}-2026-09-21.md`、`v13-control-plane-oracle-r3-2026-09-26.md`（含 r3a/b/c）
- 交付记录：`docs/reviews/v13-control-plane-{conformance-matrix,deviation-ledger}-2026-09-26.md`
- 卷宗：`prompt-exports/cpm-probe-{a,b,c}-2026-09-25.md`
