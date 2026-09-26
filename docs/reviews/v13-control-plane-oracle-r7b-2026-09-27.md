# v13 控制面 Oracle R7b 微裁：并发日程改生产锁序（2026-09-27）

- 触发：R7 §5 日程落地后残余 40P01——守卫已不在环内，环换为：A 只持 latch 后直接 INSERT，`events.session_id` 外键 RI 检查需 sessions 行 `FOR KEY SHARE`，与 B（`v13_complete`，已持该行 `FOR UPDATE`）冲突 → A 等 B；B 的写者等 A 的 latch。根因 = R7 日程「A 不锁 sessions 行」制造 `latch→sessions(FK)` **倒置序**；生产恒 `sessions→latch`（两调用点在持 sessions 锁内才调写者，外键 KEY SHARE 由自持更强锁即时满足）。同时解释 R7 §1 存疑的「NOWAIT 也死锁」（第二参与者 = FK）。
- 通道：三车道（grokBuild / codex / claude-fable-5）**一致接受修正案**。全文：`prompt-exports/oracle-review-2026-09-27-012805-new-chat-6C10c7-a0d1.md`（gitignored）。
- 地位：R7 的微裁。**只替换**并发日程的取锁顺序与等待观测（计划 §3.7、R7 §5）。不动：守卫无锁、写者 latch `FOR UPDATE` + 两条语句、真值表、部分唯一索引、守卫校验集、23505 残留接受、R3c 闭集、D11(R6)/D13/D14/第四务、零新表零新列、stage 1–20 冻结。

## §0 裁定

| 案 | Verdict |
|---|---|
| A 按生产序先 sessions `FOR UPDATE` 再 latch `FOR UPDATE` 再 INSERT；B 走 `v13_complete` 停在 sessions 行；观察点移至 sessions 等待 | **接受（三通道一致）** |
| A 裸调写者 / 只持 latch | 拒绝（同形倒置，模拟生产不存在的形状） |
| 给守卫/写者加锁、改锁原语、把 sessions 锁封进写者 | 拒绝（越界） |

## §1 日程替换句（计划 §3.7 / R7 §5）

> **并发 gate（R7b 日程）**：两连接默认 READ COMMITTED。连接 A `BEGIN` 后**按生产取锁序**：① `SELECT 1 FROM sessions WHERE session_id=<sid> FOR UPDATE`（仅持此锁时先做等待观测，见 §2）；② 观测到 B 等待后，再 `SELECT 1 FROM latches WHERE session_id=<sid> AND name='worktree' FOR UPDATE`；③ 在已持两锁内直接 INSERT 一条符合守卫全部不变量的 `worktree/released`（source=另一条已成功 effect；守卫无锁；A 自持 sessions `FOR UPDATE` 使外键 `FOR KEY SHARE` 即时满足，**INSERT 必须成功不得 40P01**）。连接 B 对另一条合格 `worktree_release` 调 `v13_complete`，A 提交前必须停在 A 持有的 sessions 行上、不得先返回、不得声称已到 latch。A `COMMIT` → B 获 sessions 锁 → 写者取 latch → **新语句**重查见事件 → 空操作返 `succeeded`。事件仍 1 行；零 `v13: worktree released`/`23505`/`40P01`；第三条合格 effect 再 complete 仍 succeeded 事件仍 1。`lock_timeout` 只判「等待不出现」；禁只锁 latch、禁先 latch 后 sessions（倒置=越界）；禁把 INSERT 移到确认等待之前。

**观测时点（grokBuild 收紧）**：等待证据必须在 A 仅持 sessions 锁、未锁 latch、未 INSERT 时采到（A 同持两锁后，同一 xid ShareLock 分不清等哪行）；A 在等待出现前提交 = 日程退化串行 = gate 失败。

## §2 pg_locks 断言（codex/fable 合并）

三项**同时**成立，由不参与竞争的观察连接采：① `pg_blocking_pids(B_pid)` 含 `A_pid`；② B 存在对 **A 的 xid** 的 `locktype='transactionid'`、`mode='ShareLock'`、`granted=false` 记录（A 的 xid 用 `pg_current_xact_id()` 记录）；③ `pg_stat_activity` 中 B `wait_event_type='Lock'` 且 `wait_event='transactionid'`。**不得**写成「对 sessions tuple granted=false」（行锁等待落在持有者 xid 上不落在 tuple 上，latch 等待与 sessions 等待同形；B 停在哪行由取锁序保证不由对象名区分）；tuple lock 记录仅作诊断。

## §3 三通道附带收紧（一并有效）

1. **两条语句规则的动态证明不再主张**（codex/fable 一致）：B 等待点前移后，写者两条语句都在 A 提交后执行，融合单语句写法同样能过本日程——该结构约束**只由源码断言钉住**（写者事件重查不在含 latch `FOR UPDATE` 的同一语句内）；文档/README 不得声称本日程验证了它。
2. **resolve_unknown 持锁前提复核**（fable P1.2）：「生产从不倒置」依赖两调用点在调写者前确持本会话 sessions 行锁。`complete` 已实测证实；**`v13_resolve_unknown` 施工时必须复核**——若不持，不得自行补锁，报事实复裁。
3. 停工条款追加：按 §1 序仍 40P01 → 停工附 pg_locks+CONTEXT；A 一锁 latch 即 40P01（说明 B 在等 sessions 时已持 latch，与 complete 锁序不符）→ 停工报事实，禁把 latch 锁挪到 complete 取 sessions 之前。

## §4 台账与文档落地

F25 处置列末尾追加一句（不新增行）：「R7b：日程改生产序取锁（sessions→latch），观察点移至 sessions 行等待；pg_locks 断言为 B 对 A xid 的 transactionid ShareLock；禁只锁 latch（FK 倒置成环 40P01）。」计划头部 r7→r7b；R7 记录顶部加 R7b 链接注（§5 原文保留、以 R7b 为准）；preflight 末尾追加 R7b 注（新 40P01 来自旧日程的测试锁序倒置，不推翻 §1–§7 GO 与 R7 守卫无锁裁定）。
