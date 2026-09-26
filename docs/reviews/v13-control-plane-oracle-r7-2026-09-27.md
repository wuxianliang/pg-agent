# v13 控制面 Oracle R7 终裁：D12 守卫/写者锁协议死锁复裁（2026-09-27）

- 触发：stage 21 施工实测——R5 二/三轮「守卫按同一锁序重锁 `latches(session,'worktree')`」在 PG18 稳定死锁（`40P01`）。R5 已预授权该停工（「若活体锁序不允许，则停工报告，不能临时发明另一套顺序」）。本裁决解除该停工点。
- 通道：三车道（grokBuild grok-4.7-build-fast-xhigh / codex gpt-5.6-sol@xhigh / claude-fable-5@xhigh）。**2:1 选定①（守卫无锁）**：grokBuild、fable 选①；codex 选②（咨询锁），异议全文存档 §7。全文：`prompt-exports/oracle-review-2026-09-27-011302-new-chat-6c10c7-73d7.md`（gitignored）。
- 地位：与 R5/R6 同级。**只替换**守卫与写者的锁协议形状及相关计划句（§3.2 步 10、§3.5 守卫段与 23505 句、§3.7 并发日程与源码断言、§5.6 锁序停工条、§3.8 台账 F25）。不重开：D12 事件权威/首次转移幂等/两个调用点/写者真值表结局/部分唯一索引/守卫校验集与 `v13: worktree released` 文案、D11(R6)/D13/D14/第四务、R5 其余、零新表零新列、stage 1–20 字节冻结、**R3c 类号闭集（不新增类号、不换体 `v13_advisory_class`）**。

## §0 总表

| 候选 | Verdict | 一句理由 |
|---|---|---|
| ① 守卫改无锁 MVCC 校验，写者保留 latch `FOR UPDATE` | **选定（2:1）** | 删掉死锁环上唯一可删的边；不新设锁序、不开 R3c 闭集；latch INSERT-once（V3008）使 binding 不可变→守卫无锁读无陈旧风险 |
| ② 写者+守卫统一改两参咨询锁（class 13002） | 拒绝（多数意见）；codex 异议存档 §7 | 守卫无锁后写者行锁无同事务重入需求；为生产不可达的旁路竞态开 R3c 闭集、换掉真值表已写死的行锁原语 |
| ③ 其他 | 拒绝 | `ON CONFLICT DO NOTHING`（真值表已禁+守卫先于冲突裁决）；`pg_locks` 探测持有态（不稳，不能当协议）；GUC/会话标志跳锁（影子状态源，越界）；`AFTER INSERT`/延迟触发器（零写语义变） |

## §1 死锁事实（施工实测，复现稳定）

环：T1 持 latch 行 `FOR UPDATE`；T2（complete→写者）排队等该 tuple（`pg_locks` 对 T1 的 transactionid ShareLock granted=false）；T1 INSERT `worktree/released` → 守卫在 T1 内**重锁同一行** → **PG tuple lock 无同事务重入豁免**，持有者再次请求排到等待者 T2 之后 → 环 → `deadlock detected`。`NOWAIT`/`SKIP LOCKED`/`FOR SHARE` 均不解除（根因是重入排队语义，非锁模式）。生产暴露：写者持锁→INSERT→守卫重锁，任一等待者到场即成环。fable 注：「NOWAIT 也死锁」难以由守卫自重重入完全解释，环内可能有第二参与者——①把守卫彻底移出锁参与，对机制不明也稳健；若残余环仍现，报事实附 `pg_locks` 快照与 CONTEXT 行复裁。

## §2 写者最终条文（保持 R5 真值表 + 两条语句规则）

`v13_record_worktree_released`（VOLATILE plpgsql）。资格/空操作/payload 闭集/`source_effect_id`/禁 `ON CONFLICT DO NOTHING`/禁锁事件行/禁捕获子串：维持 R5。无事件时临界区 = **先后两条独立语句**：

1. `SELECT ... FROM latches WHERE session_id=p_sid AND name='worktree' FOR UPDATE`（资格已保证存在；调用点已持会话锁之后执行）。
2. **上一条返回之后的新语句**重查该 binding 事件：已有（source 任意）→ 空操作；仍无 → INSERT 恰一条。

**两条语句规则（承重）**：禁止把事件读取并进第 1 条（JOIN/CTE 同语句）——READ COMMITTED 下事件侧停在语句起始快照，等锁醒来看不见对方已提交事件，法定并发日程会落入 INSERT 并打出 `23505`。写者不取咨询锁、不对 latch 用 `NOWAIT`/`SKIP LOCKED`。`23505` 与 `v13: worktree released` 不得进会收成 unknown/replay/stale 的 EXCEPTION（preflight §7.3：两调用点无 EXCEPTION 块，天然成立；禁为此补捕获/重试）。

## §3 守卫最终条文（无锁）

`v13_seam_event_guard`（VOLATILE plpgsql，BEFORE INSERT FOR EACH ROW，`WHEN (NEW.type='worktree/released')`，只 RAISE 不改行，不改 stage 17 守卫）。**全程无锁**：不对任何行取 `FOR UPDATE`/`FOR SHARE`/`FOR NO KEY UPDATE`/`FOR KEY SHARE`，不 `LOCK TABLE`，不取任何 `pg_advisory_*`，不用 `NOWAIT`/`SKIP LOCKED`，不调会锁该 latch 的函数。全部校验为普通 MVCC 读（触发器内 READ COMMITTED 快照）：

- payload 键集恰两键；`schema_version` JSON 数字 1；binding canonical uuid。
- source 非空、同 session、是 succeeded 的 `worktree_release` tool effect。
- payload binding 从 source **冻结 request** 复制（不读 worker result），并与该会话 worktree latch 行 binding 逐字相同（读 binding 字段，不读 `value->>'state'` 作状态判断）；无 latch 行 → RAISE 零事件。
- 同 binding 已有事件且 `NEW.source_effect_id` ≠ 既有行 source → RAISE `v13: worktree released` 零写。

串行旁路（对方事件已提交）得守卫具名 RAISE；**并发**双旁路/旁路×写者彼此看不见未提交行时，后到者由部分唯一索引以 `23505` 拒绝——R5 已定义的「最后带层」，非新出口。不为并发旁路补具名 RAISE 而把锁加回守卫。

## §4 竞态 23505 落写者：接受（多数意见）

旁路直插不取 latch 行锁、在写者「锁内重查已过、索引键未插」窗口先提交 → 写者 INSERT 收 `23505`、整笔回滚；旁路那条事件留下；该 binding 仍恰一行。接受理由：两个生产调用点都先取同一 latch 行锁，后到者在释放后的**新语句**里看见已提交事件并空操作——生产到不了此残留；调用方重试 complete 按真值表空操作 succeeded。**codex 异议**：旁路直插是守卫明确覆盖的合法入口，23505 落写者不可接受——存档 §7，复访触发=该残留实际发生或出现第二个生产插入者。法定并发日程仍要求零 23505；残留不写成测试通过条件、不构造为 gate（无可确定性构造点，禁暂停点）。

## §5 并发日程（替换计划 §3.7 该段）

- 连接 A `BEGIN` 后**只**对 `latches(session,'worktree')` 执行 `FOR UPDATE` 并持有。**A 不锁 sessions 行**（否则 B 停在会话锁上，看不到 latch 互斥）。
- 连接 B 对另一条合格 `worktree_release` 调 `v13_complete`；A 提交前 B 必须停在该 tuple 锁上（`pg_locks`：对 A 的 transactionid ShareLock granted=false），不得先返回。
- A 在已持行锁内直接 INSERT 一条满足守卫全部不变量的 `worktree/released`（source=另一条已成功 effect）；守卫无锁校验、不重锁 → **此 INSERT 必须成功，不得 40P01**。
- A `COMMIT`；B 获锁后以**新语句**重查、见事件、空操作、返 `succeeded`。事件仍 1 行；零 `v13: worktree released`、零 `23505`、零 `40P01`。第三条合格 effect 再调一次 complete 仍 succeeded、事件仍 1。
- `lock_timeout` 只判等待失败；禁「锁外先查无事件再让对方插入」当通过条件；禁生产函数暂停点。

直接 INSERT 串行负例组（第二 source RAISE、事件数不变）原样保留，不与本日程互替；异常块结构断言不替。

源码断言（`pg_get_functiondef`，非对全文件禁 FOR UPDATE——写者必须保留）：

- 守卫函数体不出现 `FOR UPDATE`、`FOR SHARE`、`FOR NO KEY UPDATE`、`FOR KEY SHARE`、`LOCK TABLE`、`pg_advisory_`、`NOWAIT`、`SKIP LOCKED`。
- 写者函数体出现对 `latches` 的 `FOR UPDATE`，且不出现 `pg_advisory_`、`ON CONFLICT`；事件重查不在含 `FOR UPDATE` 的同一条语句内。

## §6 计划/文档落地

§3.2 步 10 守卫描述、§3.5 守卫段（R5 锁序停工句由本裁决关闭，不得把锁加回）、§3.5 真值表第三行（补两条语句规则）、§3.5 23505 句、§3.7 并发日程与源码断言、§5.6（锁序停工条标 R7 已解除；再给守卫加锁=越界停工）、§3.8 增 F25、头部 r6→r7。R6 记录顶部加 R7 链接注（不回写历史）；preflight 末尾追加 R7 注（死锁是施工期实测，不改 §1–§7 GO）。

台账 F25（独立，不并 F24，≠ parity F25）：

| # | 事实 | 处置 |
|---|---|---|
| F25 | D12 锁协议（R7）。PG tuple lock 无同事务重入豁免：持有者再次 FOR UPDATE 排到等待者之后，与写者已持的 latch 行锁成环（40P01）；NOWAIT/SKIP LOCKED/FOR SHARE 不解除；生产写者路径同样暴露。裁决：守卫改无锁 MVCC 校验（latch INSERT-once 使 binding 不可变，无锁读无陈旧）；写者保持 latch FOR UPDATE + **两条独立语句**（锁与重查分句，防 READ COMMITTED 语句快照打出 23505）。残留仅「无锁旁路直插在写者窗口内先提交→写者 23505 整笔回滚」：生产两调用点同经行锁彼此不可达 | 接受残留。不加咨询锁、不开 R3c 类号、不捕获 23505、不加暂停点。并发日程零 40P01/零 23505；若残余死锁仍现→附 pg_locks+CONTEXT 复裁 |

## §7 codex 异议存档（复访触发：残留实际发生 / 出现第二个生产插入者）

codex 裁②：写者+守卫统一 `pg_advisory_xact_lock(v13_advisory_class('worktree_release'), hashtext(session_id::text||':'||canonical_binding))`，R3c 闭集单点窄授权加 `worktree_release→13002`（既有映射/行为/元数据不变）；守卫=静态 canonical 校验先于取锁、数据库校验锁后；写者=咨询锁内重查后 INSERT；测试日程观察点改 advisory 等待。其拒绝①的理由：旁路直插是守卫明确覆盖的合法入口，23505 落结算写者违反既有异常边界；唯一索引不是正常并发仲裁器。多数意见反驳：该竞态生产不可达且测试不可确定性构造；开闭集代价不成比例。若复访，codex 全文（§3–§6/§9）即施工文本。
