# v23 minimal agent loop 开发计划 critique

**日期：2026-10-10 · 类型：有界 design critique（重新派出）· 不修改计划/设计/源码/测试，不运行 gate/setup，不提交。**

## 0. 范围、输入与方法

评审对象：`docs/plans/v23-minimal-agent-loop-plan-2026-10-10.md`（1776 行待评草稿，下称"草稿"）。

保真基线：`prompt-exports/oracle-plan-2026-10-10-084809-plan-v23-vertical-ga-ecc9.md` 中 `## Generated Plan`（第 116 行）之后的模型计划正文（第 124–1882 行，下称"基线"）；前面的 Final Prompt/Selection/工具包装不作为计划内容。

未整合裁决：`prompt-exports/oracle-chat-2026-10-10-085740-plan-v23-vertical-ga-1113.md`（Oracle A–H，下称"裁决 A–H"），按用户说明**不是已通过决定**，只作为对照证据。

权威设计：`docs/designs/v23-minimal-agent-loop-2026-10-09.md`（2026-10-10 修订版，下称"设计"）。

代码证据仅取 v23 当前 8 文件（`v23/v23.sql:1-50`、`setup_db.py:1-53`、`worker.py:1-196`、`control.py:1-494`、`disposition.py:1-100`、`host.py:1-62`、`test_minimal_loop.py:1-232`、`README.md:1-17`）与 `AGENTS.md:1-78`。当前 Git HEAD 为 `c5a495d`，基线行号已部分过期，本报告全部改用当前行号证据。

严重性约定：**P0 = blocking**，不解决则 W0 合同无法冻结或按文实现必然产出错误行为；**P1 = 非全局阻塞，但必须在对应工作项（W1–W6）开工前裁定**，否则该工作项返工；**P2 = 非阻塞**，移交实现前修正即可。

---

## 1. 保真结论（草稿 vs 导出基线）

**结论：草稿对基线保真，无实质内容丢失；但裁决 A–H 基本未整合，且多数 P0/P1 缺陷直接继承自基线。**

逐节比对结果：

- 草稿 §1–§10 与基线对应章节逐段一致（§3 设计、§4 文件影响、§5 错误边界、§6 风险、§7 步骤、§8 W 索引、§9 共 47 条 gate、§10 共 20 条非目标均相同）。
- 草稿的新增均为正当增补：第 4–6 行状态与"单一里程碑 M1、W0–W7/Step 1–8 不可独立关闭"的元声明；§11 仓库执行与收尾纪律（与 `AGENTS.md:1-78` 对齐）。基线无 §11。
- 草稿修正了基线的多处过期行号，方向正确：`_mutate` 分段 207-418→`v23/control.py:256-418`（草稿 plan:64）、`_finalize` 420-454→`:385-418`（plan:66）、cancel 描述 456-494→`:420-494`（plan:77）、"不修改的文件"中 `v13/loop_driver/driver.py:1-44`→`v13/fair_driver/driver.py:1-44`（plan:1190，与导出 Selection 一致，已实测该文件 44 行且含 `TRANSACTION_STATUS_IDLE`）。
- 草稿仍有残留行号错误与一处悬空引用，见 P2-1。
- 参考文件抽查属实：`v8/closeout/v8_closeout.sql:116-142` 确为 `v_wait_notify`（"never carries authority"）；`v13/loop_driver/controller.py` 恰 108 行；`v13/control/test_control.py:603-644` 区域为 SET ROLE 权限探针测试（恰好支持裁决 G 的做法）；`v12/queue_worker.py:105-149` 为 transient 重试/回滚形状。

**裁决 A–H 整合状态**：A（pending/done/recovered）未出现；B（advisory fence）未出现；C（retry 固定顺序）仅被草稿 §3.5 T2 重试算法部分覆盖；D（两类工具失败）与草稿 §2.4 D 直接冲突；E（park_until_change、跨 Host 注册表）未出现；F 仅"外部 stop 复用 request ID"被吸收（plan:864），其 budget 重排违反设计 §5.3，草稿正确地未吸收，但引入了自身矛盾（P1-4）；G 仅"worker 不能连接"雏形出现（plan:1008），关键断言缺失；H 的 stopped/null-receipt 修正未出现，且草稿 §3.7 校验项 19 与其相反（P0-4）。

---

## 2. P0 发现（blocking）

### P0-1 request/input digest 分离后，durable request digest 没有存储位置；在途幂等冲突与恢复重放失去机制

**证据：**

- 草稿裁定两种 digest 分离（plan:344-364），并规定 `active_input_digest` 只存 input digest（plan:282、plan:355-363）。
- 当前代码只有一种 digest：`control.py:259` `digest = self._request_digest(op, actor, req)`，它同时被写入 `active_input_digest`（`control.py:299`、`:336`）和 `WorkerRequest.input_digest`（`control.py:339-340`）；在途重复请求的语义冲突检测依赖 `control.py:275-277` 用 `active_input_digest` 比对 request digest。
- 分离之后：在途窗口（T1 已提交、T2 未完成）内 request digest（含 operation、actor、语义字段）**没有任何 durable 存储**；`op_cache` 按草稿只在 T2/cancel 时写入（plan:409、plan:473-476）。
- 裁决 A（chat:7-28）给出的机制正是补这个洞：T1 提交前在 `op_cache` 写 `pending`（operation、actor 摘要、request_digest、input_digest、admission revision），T2 替换为 `done`，recovery 替换为 `recovered`；`pending` 不进 RunSnapshot——草稿 plan:287 已排除 `op_cache`（当前代码 `control.py:71-77` 亦同），天然满足。

**问题：** 分离裁定一旦执行，`control.py:275-277` 的在途 `idempotency_conflict` 检测即失效或语义错误（拿 input digest 比 request digest；同 instruction 不同 actor 的在途重放无法识别）；同时裁决 C（chat:56-80）要求的"先查 cache（done/recovered）→ 仅 pending 才查 active"固定 retry 顺序、裁决 H（chat:182-196）的 recovery `recovered` 收据都没有承载物。进程内可靠 `_Owner.digest`（`control.py:52-58`）比对只能覆盖 owner 存活路径，owner 丢失与 T1 commit ack 丢失后的重观察路径没有 durable 依据。

**修法（二选一，必须显式裁定，推荐前者）：**

1. 采纳裁决 A：`op_cache` 条目三态 `pending/done/recovered`。单表兼容——`op_cache` 是 `v23_runs` 行内 jsonb（`v23.sql:25`），不新增列、不新增表；`v23_control` 的 INSERT 与限定 UPDATE（含 `op_cache`）授权已具备（`v23.sql:43-46`）。T1 在提交前随同事务写 `pending`；T2 将同事务把 `pending` 替换为 `done`（与最终 Run 状态原子提交，满足裁决 C 的 ack-丢失语义）；recovery 替换为 `recovered`（见 P1-7）。
2. 或明确裁定不引入 pending：固定在途重复只与进程内 `_Owner.digest` 比对，owner 丢失一律走"关闭 + 后续重试返回通用 closed/idempotency_conflict"，并放弃恢复后确定性重放。此方案必须同样写成显式合同并配 gate。

**验证场景：** T1 提交后模拟进程崩溃，重观察可发现 `pending` 且不触发 Worker 重放；在途期间同 `request_id` 改 actor/instruction/response → `idempotency_conflict` 零写；同 `request_id` 同语义 → 绑定原 owner，Worker 次数恒为 1；`expected_revision` 变化不影响 request digest（重放可携带新 revision）。

### P0-2 草稿把 handler raise/不可序列化/超限当作"该调用的结构化失败"，回合可继续 completed——违反设计 §6.5

**证据：**

- 草稿 plan:159："未知工具、handler 异常、输入无法 JSON 序列化、输出超限都转为该调用的结构化失败"；plan:615-616（§3.4.3 每调用"失败则写有界 structured error"，随后 plan:617 继续"生成最终 result"）；plan:1248（§5.4 "handler 返回不可 JSON 序列化值：记录 bounded structured failure"）。
- 设计 §6.5（design:899）："`start`、`steer`、`respond` 的 Worker 或工具异常都在事务外捕获。Control 只开新的 T2，提交 `failed` 回执并把 Run 置为 `stopped/worker_failed`。异常路径不得再调 Worker"。设计 §3.4 工具边界（design:253）只把"结构化失败"作为 tool_calls 内的一类**数据**。
- 裁决 D（chat:88-93）与设计一致地区分两类：业务失败（handler 正常返回有界失败对象）是数据，可进 `tool_calls` 且回合可 `progress/completed`；handler raise、不可序列化、超限、运行时异常是 Worker 异常，必须产出 `failed` TurnReceipt → `stopped/worker_failed`，不得吞异常继续 `completed`。
- 基线（export:277）与草稿文字相同，缺陷继承自基线。

**问题：** 按草稿实现，handler 抛异常后回合仍可能以 `completed` 落库，被中止的模型回合被伪装成正常完成——这正是用户点名"工具业务失败与 handler raise 不可混为 completed"的情形，且直接违反权威设计 §6.5。草稿 §5.3 表（plan:1229）自身也写着 Worker 抛异常 → `stopped/worker_failed`，与 §2.4 D/§3.4.3 的"该调用结构化失败后继续"自相矛盾。

**修法：** 按裁决 D 改写 §2.4 D、§3.4.3、§5.4：plan 先全量预验证（数量、输入可序列化、单项大小）；handler 正常返回的失败对象作为该调用数据；handler raise/输出不可序列化/输出超限/预验证失败 → FakeWorker 返回 `failed` TurnReceipt（携带已执行工具的有界记录与当前异常记录），T2 落 `stopped/worker_failed`、调用方收 `WorkerError`（与 plan:1229、plan:411 现有失败优先级一致）。

**验证场景：** 业务失败（`ok=false`）进入同一 receipt 且回合可按 plan 续跑；handler raise → Run `stopped/worker_failed`、`decide` 返回 stop、无下一次 Worker、调用方 `WorkerError`；handler 返回不可序列化值 → 同上而非"结构化失败后 completed"。

### P0-3 `waiting_input` 下 Host 忙循环/活锁：public wait 立即返回，草稿未规定 park 机制

**证据：**

- 设计 §4.3（design:463）与草稿 plan:213：`waiting_input`/`completed`/`stopped` 时 wait 立即返回；当前 `control.py:460` 亦同。
- 草稿 Host 循环（plan:826-834）：`decide` 对 `waiting_input` 返回 `wait` → Host "exactly one wait" → 立即返回 → 再 `decide` → 无限空转。当前 `host.py:40-45` 正是此结构（`timeout_seconds=0.05` 对 `waiting_input` 无效，因为根本不 LISTEN）。
-  Host 不能自己 LISTEN：设计 §6.1（design:847）"Host 不直接读取数据库表"，非目标 8（plan:1745）禁止 Host 直接写 PostgreSQL；park 只能在 Control 内。
- 裁决 E（chat:111-121）给出不新增第七 op 的解法：Control 内部非 op 方法 `park_until_change`（读并结束事务 → 事务外 LISTEN → 阻塞于通知/Host 本地 wake event/有界安全超时 → 醒后重读），parent respond 与外部 cancel 的 post-commit NOTIFY 唤醒，通知丢失由安全超时兜底，`execution_accepted` 翻转由 Host 实例内 event 唤醒。
- 草稿对 `execution_accepted=False` 的停车语义也完全未规定：此时不会产生任何数据库变化，纯 wait 只在超时节奏上空转。

**问题：** 按草稿实现的 Host 在 child `needs_input` 场景（设计 §7.3、gate 21 所在链路）必然活锁或 CPU 空转；若 gate 以 `Host.drive` 驱动 `needs_input` 剧本，单线程环境下甚至永远无法等到 respond。这是 ownership/lifecycle 维度上基线与草稿共同漏掉的核心缺口。

**修法：** 在 §3.8 增加显式裁定：采纳裁决 E 的 Control 内部 park（非 op、非 scheduler、零写、零 Worker，有界安全超时兜底），Host 对 `waiting_input` 与 `execution_accepted=False` 使用 park 而非循环 public wait；外部 stop/respond 经 post-commit NOTIFY 与 Host 本地 event 双通道唤醒。若拒绝裁决 E，必须给出同样不新增公共入口/第七 op 的替代并证明无忙循环。

**验证场景：** gate 证明 `waiting_input` 下 Host 不 busy-spin（如断言两次 revision 变化之间 public wait 调用次数有界/阻塞在 LISTEN 上）；parent respond、外部 stop、`execution_accepted` 翻转三类事件均能唤醒 parked Host 并触发重新 `decide`；屏蔽 NOTIFY 后安全超时仍能收敛。

### P0-4 草稿 §3.7 校验项 19 要求 `stopped`/`used>0` 必须有 receipt——使计划自身规定的合法状态非法

**证据：**

- 草稿 plan:776："19. completed/stopped/used>0 等组合必须有合理 receipt"（基线 export:894 相同，缺陷继承）。
- 与草稿自身矛盾的三类必须合法的状态：初始轮 invalid receipt → `stopped/invalid_worker_receipt`、`turns_used=0`、`latest_receipt=NULL`（plan:1230，当前 gate `test_minimal_loop.py:203` 已断言 `latest_receipt is None`）；cancel-late 首轮 → `stopped/late_result_after_cancel`、`turns_used=0`、`latest_receipt=NULL`（plan:1233，`test_minimal_loop.py:179-181` 已断言）；orphan recovery → `stopped/cancelled`、不写 receipt（plan:115-118）。
- 当前 `disposition.py:70-71` 已实现正确规则（`waiting_input`/`completed`/`used>0` 才强制 receipt；`stopped`+`used=0`+NULL receipt 合法）。按项 19 实现将**回退**现行正确行为。
- 裁决 H（chat:198-204）正是修此项：仅 `worker_failed` 需要 durable failed receipt；`invalid_worker_receipt`、`cancelled`、`late_result_after_cancel` 可无 receipt。

**问题：** Host 对 orphan-closed / late-closed / 初始 invalid 的 Run 调 `decide` 将抛 `ValueError` 而非返回 `stop`，driver 在计划自己制造的状态上崩溃；gate 32/33/34/29 的最终快照也无法通过快照校验。

**修法：** 按裁决 H 重写项 19：receipt 强制仅适用于 `waiting_input`、`completed`、`worker_failed`（须为 durable failed receipt）与 `turns_used>0`；`stopped` 且 `turns_used=0` 在 `cancelled`/`invalid_worker_receipt`/`late_result_after_cancel` 下允许 `latest_receipt=NULL`。

**验证场景：** 三种 `stopped`+`used=0`+`receipt=NULL` 组合逐一通过 `validate_snapshot` 且 `decide` 返回 `stop`；`worker_failed` 无 receipt 与 `completed` 无 receipt 仍被拒绝。

---

## 3. P1 发现（对应工作项开工前必须裁定）

### P1-1 多进程构造 Control 会误关活 owner；裁决 B 的 fence 未裁定，且其"锁释即进程死"推理不成立——需显式 fail-closed 合同

**证据：** 当前每个 `Control.__init__` 都跑 `_recover_orphans`（`control.py:86`、`:112-126`），扫描所有 `running` 行并关闭不在模块级 `_owners`（`control.py:62-63`）中的行。第二进程接入同一 gate 库即会关闭第一进程的在途 Run。草稿 §6.3（plan:1279-1281）把"新进程一律视为无主并关闭"当作既定边界，§2.4 B（plan:121）同；但未把"同进程多 Control 共享模块级 `_owners`"这一安全前提固定为不变量，也没有任何 gate 证明被误关后旧 owner 的 T2 不会覆写。裁决 B（chat:34-52）提出 session 级 `pg_advisory_lock` fence + 按 DSN 共享 `_ControlRuntime`；但按用户指出的问题，fence 连接断开只证明**会话**结束，不证明进程/Worker 已死——"新进程取得锁即可确认旧进程已退出"（chat:40）在旧进程 fence 连接静默断开时失效，会造成双活与误关。

**修法（二选一，显式裁定）：**

1. 拒绝 fence，把"每个 gate 库同时只允许一个 active Control 进程"写成显式 scope 限制，并固定两条安全网不变量：(a) `_owners`/`_owners_lock` 为进程内按 DSN 共享的模块级 registry（plan:712-729 需补此句），禁止实例化改造；(b) 误关不会腐蚀 durable 状态——旧 owner 的 T2 依赖行锁 + `active_operation_id` 匹配（`control.py:389-392`），只得到冲突、不写 receipt。配 gate：第二 registry（清空的 `_owners` 或子进程）关闭在途 Run 后，原 owner T2 不覆写、不加 turns、不写 latest_receipt。
2. 采纳 fence，但必须补 fail-closed 半区：持有 fence 的进程一旦检测到 fence 连接丢失，必须立即停止服务新 op 并放弃在途 T2（由 (b) 兜底），否则不许启动恢复。

**验证场景：** 两进程同时构造 Control，只有一个执行 recovery（方案 2）或第二进程的关闭不造成 durable 覆写（方案 1）；同进程两个 Control 实例互不误关；释放/断开 fence 后的行为符合所选合同。

### P1-2 工具总量上限按现定义不可达；9 调用的预验证时机未规定

**证据：** 草稿 plan:160 维持 8 / 4096 / 32768 常量；当前 validator 按"逐项 json 字节求和"（`worker.py:107-116`）：8 × 4096 = 32768，求和**永远不会超过** 32768 → `MAX_TOOL_TOTAL_BYTES` 分支（`worker.py:115-116`）是死代码，gate 36"总量上限全部执行"（plan:1681-1684）无法诚实证明。裁决 D（chat:93-95）指出应校验 canonical 序列化后 `tool_calls` 数组总字节（含数组 framing），8 个接近 4096 的合法 item 即可真实超界；并要求数量为 9 时在任何 handler 执行前拒绝（返回 failed receipt），第 9 个不得执行、不得静默裁剪。草稿对"9 调用何时拒绝"完全未规定（plan:612-619 的循环内"检查调用数量上限"语义不明）。

**修法：** 采纳裁决 D：总量按 canonical 序列化数组计量（或相应调低常量）；plan 级全量预验证先于任何 handler；gate 36 用真实 handler 输出构造恰好边界、超单项、超总量、9 调用四种用例，禁止伪造不可达数据。

**验证场景：** 8 × 接近 4096 的真实输出触发 aggregate limit；9 调用计划零 handler 执行且落 failed receipt；边界值（恰好 4096/恰好总量）通过。

### P1-3 权限证明弱于裁决 G：PUBLIC CONNECT 未收、gate 全程以 superuser 连接、缺 SET ROLE 探针

**证据：** 草稿仅"确认 Control 连接使用可执行设计权限的角色；增加 gate 用于验证 `v23_worker` 无法连接"（plan:1007-1009）与 gate 46（plan:1714-1716）。当前事实：`v23.sql:42-47` 只有 schema USAGE/表级授权与 `REVOKE ALL ... FROM v23_worker`；`setup_db.py:43-45` 仅 `ALTER ROLE v23_control LOGIN`、REVOKE PUBLIC CREATE、REVOKE worker CONNECT——**没有** `REVOKE CONNECT ON DATABASE ... FROM PUBLIC`，也没有显式 `GRANT CONNECT TO v23_control`；`local_dsn()` 默认不带 user（`setup_db.py:18-26`），gate 的 Control（`test_minimal_loop.py:49`）与 schema 审计（`:53`）全部以默认 superuser 连接，`v23_control` 的授权是否足以跑通六 op 从未被证明。裁决 G（chat:161-170）给出了设计对齐的具体断言集。`v13/control/test_control.py:603-644` 已有同款 SET ROLE 探针形状可参考。

**修法：** 按裁决 G 收紧 §3.10 与 gate 46：`REVOKE CONNECT ... FROM PUBLIC`；仅 `GRANT CONNECT TO v23_control`；gate 的 Control DSN 显式 `user=v23_control` 并以其跑全部六 op；admin 仅用于 setup 与审计；`SET ROLE v23_worker` 探针证明无表读写；明确 `NOLOGIN` 不是权限正确的证据。

**验证场景：** PUBLIC 无 CONNECT；superuser 不出现在 Control 行为路径；worker 不能登录且 SET ROLE 后不能 CRUD；`v23_control` 能完成 start/T2/cancel/poll/wait/steer/respond。

### P1-4 budget × waiting_input/respond：草稿 §3.7 与 §5.4 自相矛盾；裁决 F 的重排违反设计 §5.3，须保留固定优先级或提请用户裁决

**证据：** 草稿 §3.7 固定优先级（plan:781-791）照抄设计 §5.3（design:761-771）：`waiting_input`（→wait）在 `budget exhausted`（→stop）之前。但草稿 §5.4（plan:1239）写"`turns_used == turn_budget`：decide 返回 stop……未关闭时必须 cancel"，无条件成立——对 `waiting_input` 且预算耗尽的 Run，两处给出相反答案。裁决 F（chat:145）主张"预算已耗尽"先于 waiting 返回 stop，**这违反权威设计 §5.3 的固定顺序**，按用户要求不可偷偷改设计。同时 respond 的预算 admission 在草稿中未规定（plan:527-550 的 T1 前置检查无预算项），而当前代码对 steer/respond 共用预算检查（`control.py:333-334` 抛 `budget_exhausted`）；设计 §4.6（design:641-647）对 respond 未提预算。

**修法（必须显式二选一）：**

1. 保留设计 §5.3 固定优先级：`waiting_input`+预算耗尽 → `wait`；同时把 §5.4 的 budget 条款限定为"非 waiting_input"；明确裁定 respond T1 检查 `turns_used < turn_budget`（与当前代码一致），预算耗尽 → `budget_exhausted` 零写零 Worker；并写明 Host 的出口只有外部 cancel（配合 P0-3 的 park，不会活锁空转）。
2. 或将"设计 §5.3 是否把 budget 提到 waiting_input 之前"标记为未决设计问题，显式提请用户裁决后再改设计，计划不得先行吸收裁决 F。

**验证场景：** `decide(waiting_input, used==budget)` 的结果与所选合同一致并有 gate 断言；respond 超预算 → `budget_exhausted` 零写、Worker 次数不变；gate 8（plan:1579-1580）补充 waiting_input 维度。

### P1-5 steer/respond 重试的 request ID 稳定性未规定（外部 stop 已规定）——现行 host.py 每次新 ID 会卡死

**证据：** 草稿 §3.8.4（plan:864）只规定外部 stop"revision conflict 时重新 poll 后使用同一 stop request ID 重试"。对 steer/respond 的 revision conflict / ack 丢失重试无任何规定；当前 `host.py:38`、`:51` 每次循环 `_next_request_id()` 生成新 ID——一旦 steer 的 T1 已提交而 ack 丢失，Host 用新 ID 重试会撞上 `running`/`busy`（`control.py:311`），既无法绑定原 owner 也无法完成回合，driver 永久卡住。裁决 F（chat:136-143）给出规则：poll → 重新 `decide` → 仅仍为 `run_now` 才重试；同一 continuation 语义复用原 request ID，语义改变才废弃换新。

**修法：** 在 §3.8.2/§3.8.4 增加"每个语义操作一个稳定 request ID，跨 poll/re-decide 重试复用；`decide` 结果改变（转为 respond/cancel/返回）才废弃"的裁定，并列入 `host.py` 影响清单（plan:1104-1114 目前无此项）。

**验证场景：** 注入 steer T1-ack 丢失：Host 以同一 ID 重试 → 绑定原 owner 或命中 cache，Worker 次数恒 1，恰好一轮被 admit；revision conflict 后 poll/re-decide 只产生一轮新 mutation。

### P1-6 跨 Host 实例的同 Run 唯一性被弱化（设计 §6.1 要求进程级）

**证据：** 设计 §6.1（design:810）"Host 进程内必须为每个 Run 建立唯一驱动协程"；草稿 §3.8.1（plan:816-820）只"保持一个 Host 实例内的 `_active`"（当前 `host.py:21` 为实例字段）。同进程两个 Host 实例可对同一 Run 各起一个 driver，靠数据库 revision 兜底（设计 §8 `v23_single_run_coroutine` 允许兜底但要求 Host 层先拒绝）。裁决 E（chat:121）给出进程级 `(dsn, run_id)` driver registry 加锁，外部 stop/respond 不算第二 driver。

**修法：** 采纳进程级 registry（与 P1-1 的共享 runtime 同一层），在 §3.8.1 把"实例内 `_active`"改为"进程级 `(dsn, run_id)` registry + 实例 `_active`"；明确 stop/respond 不占 driver 名额。

**验证场景：** 两个 Host 实例对同一 run_id 同时 `drive`，第二个在 Host 层 `HostBusyError`、零 DB/Worker 副作用；`drive_async` 与 `drive` 共享同一保护（plan:818-819 已有此要求）。

### P1-7 owner 恢复后的重放语义不确定（草稿允许 orphaned_operation/closed 多分支 vs 裁决 H 的单一 recovered 收据）

**证据：** 草稿 plan:119-120："不为原在途 request 伪造成功 cache；当前请求返回已关闭状态或明确的 `orphaned_operation`/`closed` 错误"——两种可观察结果并存，且恢复后同一 request 的精确重试走哪条路径未规定。裁决 H（chat:184-196）裁定为唯一结果：recovery 把 `pending` 替换为 `recovered`（响应 = 关闭后最新快照，`outcome=recovered_orphan`、`error=owner_lost`），精确重试永远返回该 recovered response，不看历史 running 快照、不重 Worker、不再 mutation，"没有 `orphaned`、`active_conflict` 等可选分支"。草稿 plan:1235 的 `stopped/cancelled` 落库部分与 H 一致（当前 `control.py:121` 也是 `cancelled`）。

**修法：** 采纳裁决 H 并与 P0-1 的 pending 配套：`recovered` 不是"伪造成功"，而是确定的关闭收据；删除 §2.4 B 的"或"分支，固定精确重试 = 返回 recovered response。若采纳 P0-1 方案 2（无 pending），则必须替代性地固定"重试一律返回通用 closed 响应"为唯一分支。

**验证场景：** recovery 后原 request 连续两次精确重试返回完全相同的 recovered response；revision 只 +1 一次、turns 不变；迟到 Worker 结果不能覆盖 recovered 状态（T2 active 检查兜底）。

---

## 4. P2 发现（非阻塞，移交实现前修正）

### P2-1 残留过期/错误引用束

- plan:627（§3.5 "文件：`v23/control.py:207-454`"）：207 是 `execute`；T1/Worker/T2 实现为 `_mutate` `control.py:256-383` + `_finalize` `:385-418`。
- plan:1045（§4 control 影响 "重点为 `_mutate` `:207-418`、`_finalize` `:420-454`、`_cancel`/`_wait` `:456-494`"）：实际 `_mutate` 256-383、`_finalize` 385-418、`_cancel` 420-455、`_wait` 457-494。与 plan:64-66 已修正的口径自相矛盾。
- plan:102、plan:714（"`_owners` 位于 `v23/control.py:49-60`"）：`_Owner` 在 `control.py:52-58`，`_owners`/`_owners_lock` 在 `:62-63`。
- plan:67（wait "见 `v23/control.py:420-494`"）：`_wait` 实为 457-494；420-455 是 `_cancel`。
- plan:21（"本文的 Background 记录当前工作区证据"）：草稿正文没有 Background 节（初始 38 行骨架已被 1776 行草稿取代），应改为"本文 §2"。
- plan:65（外部 IO 约束引用 `AGENTS.md:66-78`）：该规则实在 `AGENTS.md:73-78`；66-72 是 push 规则。引用范围可收窄。

**修法：** 按上述当前行号统一修正。**验证：** 逐条对照 `control.py:207,256,385,420,457,62` 与 `AGENTS.md:73`。

### P2-2 start T1 写入枚举漏 `active_input_digest`

plan:391 的 INSERT 枚举只有 `status=running`、`revision=1`、`active_operation_id=request_id`、`active_base_revision=1`，而设计 §4.1（design:372）要求"保存 `active_input_digest`"，草稿 §3.2.1 也保留该列；当前代码 `control.py:296-299` 已写入。**修法：** 枚举补齐；P0-1 落地后此处还需同时写 `pending` op_cache。**验证：** start T1 后行内 active 三元组完整且满足 `v23.sql:29-32` CHECK。

### P2-3 多条新增 gate 缺少确定性实现机制，存在沦为空断言的风险

- gate 13 read/LISTEN race（plan:1594-1596）：需要确定性地在首次 read 与 LISTEN 之间注入 mutation（测试钩子或 barrier 线程），草稿未规定。
- gate 14 通知丢失（plan:1597-1598）：需明确屏蔽手段（如 monkeypatch `_notify` 为空操作）。
- gate 32/33 进程重启（plan:1664-1671）：同进程 `fresh_control` 共享模块级 `_owners`（`control.py:62`），**不等于**重启；须明确用清空 registry 或子进程模拟。
- gate 16 事务状态（plan:1601-1605）：需明确探针（`pg_stat_activity`/`TRANSACTION_STATUS_IDLE`，`v13/fair_driver/driver.py` 已有形状）。

**修法：** 为每条指定注入/探针机制。**验证：** 四条断言在屏蔽/注入开启与关闭时结果可区分（非恒真）。

### P2-4 "授权 → cache → expected_revision"顺序正确但缺 gate 断言

草稿顺序正确（plan:466-476 步骤 2→3→4；plan:90；当前代码 `control.py:271-274`、`:428-429` 均先 `_authorize` 后 `_cached`）。缺两条断言：未授权 actor 携带他人已缓存 `request_id` → `not_found_or_unauthorized`（cache 不作存在性 oracle）；steer/respond 的 cache 命中优先于 stale `expected_revision`（gate 26 只覆盖 cancel，plan:1638-1642）。**修法：** gate 24/26 扩展两例。**验证：** 两例分别命中对应错误码且零写。

### P2-5 ack 丢失场景需在 gate 27/24 中显式区分，并点名现行 `_finalize` 重试偏差

草稿 §3.5 的 T2 重试算法（plan:695-708）已含"先查 op_cache"，但 gate 27（plan:1643-1646）只写 "T2 transient failure"，未区分 commit 前失败（用同一 receipt 重提交）与 commit 成功 ack 丢失（直接返回 cache）；也未点名现行偏差：`control.py:363-369` 的重试循环捕获 `OperationalError` 后重进 `_finalize`，后者在 active 已清除时抛 `active_operation_conflict`（`control.py:391-392`）而非返回 cache——调用方将收到错误异常。T1 ack 丢失（行已在、客户端不知）同理只在 owner-join 中隐含覆盖。**修法：** gate 27 拆两种子场景（Worker 次数均恒 1、revision 不增）；在 §2.4 或 §4 点名该现行 bug。**验证：** commit-ack-loss 重试返回已提交 response；T1-ack-loss 重试绑定原 owner、不二次 Worker。

---

## 5. 基线与草稿共同遗漏的维度映射

- **Ownership：** P0-1（durable request digest/pending）、P1-1（进程边界与 fence fail-closed、共享 registry 不变量）、P1-7（恢复重放确定性）。
- **Lifecycle：** P0-3（waiting_input 停车）、P1-6（进程级 driver 唯一性）、P1-4（budget×waiting_input 生命周期出口）。
- **Failure：** P0-2（两类工具失败）、P0-4（stopped/null-receipt 合法性）、P1-2（失败边界可达性）。
- **Cancellation：** P1-5（重试 ID 稳定性）；cancel 的 cache/zero-write/授权顺序本身已核验为正确（见 P2-4 与 §1）。
- **Testability：** P1-2（aggregate 可证明性）、P1-3（权限证明真实性）、P2-3（注入机制）、P2-4/P2-5（断言缺口）。

## 6. 会实质改变实现、需要显式裁定（部分需用户裁决）的决策清单

1. 是否采纳 `op_cache` 三态 `pending/done/recovered`（P0-1，推荐采纳；单表兼容）。——blocking W0。
2. 工具失败两类语义按设计 §6.5 落实（P0-2，须改草稿 §2.4 D/§3.4.3/§5.4）。——blocking W0/W2。
3. Host park 机制（P0-3，推荐裁决 E 的 Control 内部 `park_until_change`，非第七 op）。——blocking W0/W5。
4. `stopped`+`used=0`+`receipt=NULL` 合法性修正（P0-4，按裁决 H 改校验项 19）。——blocking W0/W4。
5. 多进程 scope：显式单 active Control 进程限制 + 安全网 gate，或 fence + 连接丢失 fail-closed 半区（P1-1）。——W3/W6 前。
6. 设计 §5.3 固定优先级是否更动（P1-4）：**默认保留**；若要采纳裁决 F 的 budget 重排，必须先由用户裁决并改设计稿，计划不得自行吸收。
7. respond 的预算 admission（P1-4 附带，建议与当前代码 `control.py:333-334` 保持一致并成文）。
8. 恢复后重放是否唯一 recovered 收据（P1-7，随决策 1 联动）。

## 7. 统计与最重要阻塞

- **P0：4**（P0-1 digest 存储、P0-2 工具失败语义、P0-3 Host 活锁、P0-4 stopped 校验矛盾）——全部 blocking。
- **P1：7**（P1-1 多进程/fence、P1-2 上限可达性、P1-3 权限证明、P1-4 budget×waiting_input、P1-5 重试 ID、P1-6 跨实例唯一性、P1-7 恢复重放）。
- **P2：5**（P2-1 行号束、P2-2 INSERT 枚举、P2-3 gate 机制、P2-4 顺序断言、P2-5 ack 场景拆分）。

**保真结论：** 草稿对导出基线保真、无实质内容丢失或弱化（新增 §11 与里程碑元声明为正当增补；数处行号修正方向正确）；裁决 A–H 基本未整合，主要缺陷均继承自基线并被当前代码证据确认。

**最重要阻塞：** P0-1。digest 分离裁定抽掉了在途窗口的 durable request digest，使在途幂等冲突检测、T1/T2 ack 丢失重观察（裁决 C）与恢复确定性重放（裁决 H）同时失去承载；W0 合同无法在不裁定 pending/done/recovered（或显式替代）的情况下冻结，且它是四个 P0 中唯一同时卡住幂等、取消、恢复三条链路的根因。
