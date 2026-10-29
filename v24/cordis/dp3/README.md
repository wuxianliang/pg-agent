# Cordis v2 DP3

DP3 从 DP2 内核继续做失效传播与可逆退役。权威规格是 `docs/designs/cordis-plugin-system-2026-10-25.md`，实施计划是 `docs/plans/v24-cordis-dp3-teardown-plan-2026-10-27.md`。各阶段原始结果保留在 DP3 conformance matrix 与 deviation ledger；DP1/DP2 历史验收不在这里改写。

## 当前状态

**B0=`ba4f533`、W1=`103ec596`、W2=`72af2528`、W3=`284d7f2` 已发布到 `origin/v24`。W4 已于 2026-10-27 在 W3 基线上实现并通过 24 条串行门禁，由其提交发布。W5 已实现并通过最终 26 条串行门禁；本提交发布 W5 到 `origin/v24`，DP3 的 B0–W5 全部交付。**

W4 最终门禁于 2026-10-27 在 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`、分支 `v24`、HEAD `284d7f2d420f6c9a73b1326bb7b4497ee8fa498e` 加 W4 改动（提交前）上实跑。计划 §4.1 的 21 条旧命令、CDP3-P、CDP3-T、CDP3-D 依次单独启动并等待退出，**24 条全部退出 0，总耗时 93 秒**。命令、耗时及结果见 `docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md` 的 W4 节。

W3 最终门禁于 2026-10-27 在 W2 基线上实跑，23 条全部退出 0，总耗时 62.92 秒；其生产 P6 证据保留在 matrix/ledger 的 W3 节。

- 生产 P6 路径由 `p6_plan` 选定唯一分支：hard unsupported → unknown → open owned run／其他 ready/claimed effect → terminal run pins → contribution inverse（最高未释放 seq DESC，≤32，含不支持项不过滤）→ activation pins（`(key,id)`，≤32）→ close。run pins 先按 `(consumer_run_id,key,id)`，与 activation pins 合计≤32。
- `command_barrier` 只把可等待 DB 义务映射为 v1 deferred；unknown inverse 为 `blocked_unknown` 零写；cell/reservation inverse 与 host_io/settlement 为 `0A000` 整笔回滚。deferred 不写十表、不消费 request/effect。
- `contribution_inverse`、`pins_release`、`episode_close` 为闭集 typed op；applier 逐项重查 fresh SQL 后置条件。close 只设置 `episodes.closed_at`、清 `fibers.current_episode_id`/`retire_started_at`，不重写 state/outcome/failure/want_on/dispose，也不开新 episode。
- `run_pin_release_delta` 只消费 owner/episode 对齐、`ended_at` 非空、无未结 effect/unknown/host_io 的 terminal run；只释放其未释放 pin，不写 run result/settlement。
- inverse/pin-release 步骤产生一个 ordinal 0 的 `command_reconcile/advance` 后继以便同一 LOGIN 继续 drain；close 无后继。现有协议只允许 reserved key 的 `advance`，host 用 P0 `off` 空闲 schedule 取得首个 P6 槽；这不是新调度器。
- child inverse 只接受 owner-fixture 已 tombstone 的 child，否则 deferred。为满足 `14_contributions.sql` 的 `released_at ⇒ withdrawn_at` CHECK，同次 inverse 写把 `withdrawn_at` 作为释放簿记前置；P5 `withdrawn_ids` 仍不含 child，物理行与 FK 保留。该 schema-forced 语义记入 deviation ledger。
- CDP3-T 覆盖 activation pin（无 run）阻断 provider release、open run/ready/claimed（含过期 lease）/unknown/host_io barrier、ended-run 仅 pin release、32+1 严格 DESC、run/activation 排序与合计 32、service/listener ledger inverse、tombstoned child inverse、历史 pin/prev FK、withdraw 不释放地址而 release 后可复用、空贡献 close、重复刷新不重复释放、deferred 十表零写。listener/cell/reservation/unknown/run/child tombstone 使用 owner fixture，只证明具名账本/阻塞边界。
- CDP3-P7 用真实 P6 证明 deferred 十表零写、屏障清除后同 request 首次提交、byte-identical replay；W1 的非生产 probe 仍只是协议探针。
- W4 首次 dispose 只登记目标 install 的 `dispose_pending` 并封住后代准入，不清理 fiber；后续每个 same-LOGIN 的新 dispose request 只推进一个对象：最深 descendant fiber、child-install 墓碑、本 install fiber、父 install 墓碑。
- 所选 fiber 的 open episode 先经 `fiber_dispose_request`（`want_on=false`；必要时 `control_seq+1`）和唯一个 ordinal 0 `command_reconcile/advance` 进入真实 P5/P6；无 episode 且无义务后 `fiber_dispose_finish`。槽已存在时不建第二槽，无事件 no-op。
- `install_dispose_progress` 严格四键，phase 仅 `requested/fiber_requested/fiber_disposed/work_scheduled/completed`，`scheduled_targets` ≤1。domain 写恰一条领域事件；successor-only schedule 恰一条 `work_scheduled`；coalescing/replay/deferred/error 零事件。
- `continuation_state` 新增 dispose parent → 该 parent 已 seal 的 owner subtree 中 selected fiber reconcile 分支；`dispose_delta` 独立重算 target/phase/successor/event，伪造 interpreter 输出零写拒绝。
- `dispose_plan` 对 host_io 六态保守返回 `unsupported/0A000`，unknown 返回 `blocked_unknown`，open run / 非 reconcile ready/claimed effect 返回 deferred；不持 G 等待，deferred 十表零写。
- `dispose_command_seed` 只锁定 target install 与本次选中 fiber/child install；episode/owner/scope 由引用链补入，settled/released 历史不膨胀 closure。dispose parent successor 必须 ordinal 0 且被 parent receipt 的 `emitted` 精确列出。
- `basic_dispose` 已从生产 typed op、validator、applier 和事件闭集删除；非生产 probe 也使用 staged op。
- CDP3-D 覆盖 root→child→grandchild 的 child-first、parent-last、seal no-revival、不同 LOGIN 拒绝、原 request replay、fresh request 合并、伪造后继拒绝、600 条历史 effect 不膨胀 closure，以及燃料 `16×(1+F+I+E+C+P)` 内的 `(M,U)` rank driver。一次 Oracle review 的 closure/successor/basic-dispose/negative-test 发现和自审的多级 child-install 顺序已修复。

W5 最终门禁于 2026-10-27 在同一工作树、分支 `v24`、HEAD `f6a3a74` 加 W5 改动（提交前）上实跑。§4.1 的 21 条旧命令加 CDP3-P/L/T/D/B **26 条依次单独启动并等待退出，全部退出 0，总耗时 121.64 秒**。W4 的 24 条表漏掉 CDP3-L；W5 首次执行时 CDP3-L5 在 owner-chain cycle 上失败，暴露 W4 回归并已修复（详见 matrix/ledger 的 W5 节）。

- CDP3-B 证明十表、零新公开 writer、唯一 SECURITY DEFINER、helper 预算、DDL 前缀、17 项 manifest、无 VIEW/EXTENSION、public EXECUTE 0。
- 生产路径成功证据限于真实 service 与 child activation；listener 只用 owner fixture 构造账本行，再由真实 teardown 清理，不声称生产注册或 dispatch。
- cell/reservation inverse 经真实 `advance` 返回 `0A000` 并十表回滚；unknown 返回 `blocked_unknown` 零写；ready/claimed/过期 lease 不被当作完成或取消；settlement 仍 `0A000`；dispatch/intercept/overlay 未接通；无 run_start writer 或外部恢复。
- closure 512、batch 32、successor 16 上限；真实 512/513；600 个 terminal parent 与 601 个 closed 代不膨胀当前 closure；reverse-pin/run/child 锁后漂移在 DML 前以 `retry_with_closure` 拒绝。
- 双连接同 realm 同 key 地址竞争仅一方成功；不同 realm 同 key 均成功；P5 精确 256 通过、257 提前拒绝；inverse/close 后置失败整笔回滚；successor-only 单事件、domain+schedule 单事件、coalescing `emitted=[]`、replay 不重复 event。
- 所有负例读取十表 snapshot 及相关 immutable/iterator 输入；iterator v1 精确键、loader 拒绝 autocommit/在线迁移、forward-only guards 保持；独立 validator 拒绝伪造 target/phase/event/successor。

## 容量与冻结

40=1373、41=1211、42=966，全部 helper 合计 **3550≤5000** 物理行。共享预算函数仍在临时三文件树验证恰好5000通过、5001拒绝。DDL 前缀461≤900，manifest17（loader未改、已核验），十表，仅 `advance` 为 SECURITY DEFINER，public function EXECUTE 0；源码 VIEW/EXTENSION 均0。十二份 frozen SQL SHA-256 与 DP2 matrix 一致，`57e2c1e` frozen diff、v8 相对 HEAD diff、`git diff --check` 均退出0。

## 历史与证明边界

B0 的21条旧命令与 W1 的22条命令、W2 的23条命令均有各自独立实跑记录。B0 当时 helper2227、DDL414、manifest16；W1 当时 helper2283、DDL414、manifest17；W2 当时 40=1259、41=1119、42=557，合计2935，DDL458；W4 当时 40=1373、41=1193、42=964，合计3530；W5 最终 40=1373、41=1211、42=966，合计3550。W1 deferred/blocked_unknown/unsupported 与非 ready barrier replay 是 disposable 非生产 probe，调用方提交后第二连接取得 G；它们不证明生产 P6。

W3 的生产 `command_barrier` 已接线，`lifecycle_step` 仍返回 idle 且未被 `advance`/`interpret_command` 调用（CDP3-P4 保持）。**W4 已激活实例 bounded dispose 与 W5 边界门禁/closeout 已交付；DP4 settlement、DP5 listener/dispatch/intercept/overlay、DP6 scanner/external recovery 与无界 child cleanup fan-out 尚未实现。** host_io/settlement 继续保守拒绝，不能由终态标签推断外部资源已释放。旧 pin release、run、cell/listener/reservation、cycle/损坏历史使用 owner fixture，只证明具名账本或拒绝边界，不证明生产注册、dispatch、run settlement、外部恢复或自动扫描。child cleanup 由父 controller 经真实 `command_reconcile` 与 dispose advance 驱动，但外部 consumer/unknown 仍是阻塞边界；W3 的 owner-fixture tombstone 不是该生产路径。child inverse 的既有 CHECK 未修改。

用户授权 DP3 各里程碑独立 commit/push `origin/v24`，覆盖 AGENTS.md 的默认分支指令。本提交仅逐路径暂存 W5 精确文件，保留原有 dirty docs 及无关 untracked 文件。
