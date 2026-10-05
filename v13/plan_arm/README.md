# v13 plan_arm

Phase A 第三段。唯一一份 `CREATE OR REPLACE v13_advance`。它是 govern 里活体函数的副本，加上调用 `v13_plan_advance_prefix` 的一段。插入点在 spawn 块 `RETURN 'progressed'` 之后、`v13_harness_predecessor` 之前。不改 `:790-829`，不插入 T1.3 点名臂内部。

源函数正文 SHA-256（`v13/govern/v13_govern.sql` 里从 `CREATE OR REPLACE FUNCTION public.v13_advance` 到对应 `END $function$`）：

`515eea33d95079580648e61651aeaae61b20252ee2a4f0eb34a10a31680d2911`

超级用户夹具不是产品角色证明。本目录不证明产品库名、产品角色、stannum、PC-4，也不证明 material 已扣。`should_run` 政策 version 仍是 3。不调用 `v13_child_pointer`。不替换 `v13_recover_idle` 或指纹函数。

## 臂

- 子会话：结算与派发跳过，零 plan/todo。恰好一条 `workflow/pointer` 且还没有任何 `read_file_py` effect 时，`should_run` 为真才建 `tool` effect。不写 `tool/call`。
- 根、未 stopped：先核对子 `read_file_py` 摘录，命中则经写者 `runnable→done` 并返回 `waiting`，零新 effect。
- harness `progress|finish` 且绑定的 advancement 仍是 `runnable`：写归档后落入活体收据臂，同一事务。`wait`/`reject` 不写。monitor 不猜 due，不归档成 `done`。
- `failed|cancelled` 且仍 `runnable`：一条隔离 `update`，`status_to=blocked`。
- 门为真且 `should_run` 为真才派发。`provider` 的 kind 是活体模型回合的 `llm`。`operator` 是 `human`。`none` 不建 effect。首次绑定是 `status_from=status_to` 的载荷更新。
- stopped：本调用新增 plan/todo 为 0，活体 finish 仍可写收据。

## R0：root 阻断期间的收据（2026-10-01）

上文保留 Phase A 历史合同；R0 按 `docs/plans/v13-long-loop-phase-c-reopen-advance-plan-2026-10-01.md` 修改当前唯一 advance：仅在已锁 `p_sid` 自身是根、且已进入 ready/claimed early return 时，按活体当前 harness 前驱及 signals/material ledger 条件补一张幂等收据，随后仍 waiting。普通调用和 supervisor wrapper 同样适用，不用 marker，不因记账派发或 closeout。

- 锁序：已持有 root session → 选择当前前驱 → effect FOR UPDATE → 重读。child 不映射、不向上锁 root。unknown/cancel/terminal/stale 前序墙保持原样。
- 非法 result/signals、非合格/已付前驱、signal/material 冲突安全不匹配，零 receipt；不吞数据库异常。原非阻断臂的错误与派发正文未改。
- root stopped 且存储 failed 为 false/0/空串/文本时，新早退块不补记；null/缺键可补记。这不是 direct advance 零调用的证明，也不改变旧非阻断臂。
- receipt 提前提交后，下一轮 spawn/plan prefix 可因 session-local 配额临界而等待；测试用真实 receipt 与合法 human response 做 allowed=1/宽松配额对照，不改 should_run/quota 实现，不声称 PC-4。
- `R0_DECL_BEGIN/END`、`R0_RECEIPT_BEGIN/END` 是唯一新增区。去掉两区后 SQL bytes 必须与 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 完全一致；测试还冻结原功能测试/模块设置。缺 git 基线对象时明确失败，不以 HEAD 干净替代。
- 冻结中心放行的新跟踪文件只在 `v13/goal_supervisor/`、`v13/fair_claim/`、`v13/fair_driver/`。这些已知文件钉 `78e77c7` 的字节。`v13/load.py` 不钉整文件：只允许两表表尾的规范追加，`r1_load_append_ok` 用内存变异做正向失败证明。`v13/goal_supervisor/test_goal_supervisor.py` 与 `v13/fair_claim/test_fair_claim.py` 只放开 `test_stage_bytes`；fair 这份测试不得另增顶层函数。
- stage 32 测试不依赖 Phase C SQL。stage 38 另测 wrapper、workspace、统计调用数及并发锁交错。运行结果统一记在 Phase C 覆盖矩阵的 R0 新行；不覆盖历史 M1/M2。

R0 只证明 material 记账，不证明 blocker 已解除、finish 已 closeout 或 M3 续行已通。R1 点名入口是 `LoopDriver.settle_once`；本目录 SQL 仍不改。
