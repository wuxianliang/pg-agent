# Cordis v2 DP3

DP3 从 DP2 内核继续做失效传播与可逆退役。权威规格是 `docs/designs/cordis-plugin-system-2026-10-25.md`，实施计划是 `docs/plans/v24-cordis-dp3-teardown-plan-2026-10-27.md`。各阶段原始结果保留在 DP3 conformance matrix 与 deviation ledger；DP1/DP2 历史验收不在这里改写。

## 当前状态

**B0=`ba4f533`、W1=`103ec596`、W2=`72af2528` 已发布到 `origin/v24`。W3 已于 2026-10-27 在 W2 基线上实现并通过 23 条串行门禁；本提交发布 W3 到 `origin/v24`。W4–W5 尚未实现。**

W3 最终门禁于 2026-10-27 在 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`、分支 `v24`、HEAD `72af2528` 加 W3 改动（提交前）上实跑。计划 §4.1 的 21 条旧命令、CDP3-P、CDP3-T 依次单独启动并等待退出，**23 条全部退出 0，总耗时 62.92 秒**。命令、耗时及结果见 `docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md` 的 W3 节。

- 生产 P6 路径由 `p6_plan` 选定唯一分支：hard unsupported → unknown → open owned run／其他 ready/claimed effect → terminal run pins → contribution inverse（最高未释放 seq DESC，≤32，含不支持项不过滤）→ activation pins（`(key,id)`，≤32）→ close。run pins 先按 `(consumer_run_id,key,id)`，与 activation pins 合计≤32。
- `command_barrier` 只把可等待 DB 义务映射为 v1 deferred；unknown inverse 为 `blocked_unknown` 零写；cell/reservation inverse 与 host_io/settlement 为 `0A000` 整笔回滚。deferred 不写十表、不消费 request/effect。
- `contribution_inverse`、`pins_release`、`episode_close` 为闭集 typed op；applier 逐项重查 fresh SQL 后置条件。close 只设置 `episodes.closed_at`、清 `fibers.current_episode_id`/`retire_started_at`，不重写 state/outcome/failure/want_on/dispose，也不开新 episode。
- `run_pin_release_delta` 只消费 owner/episode 对齐、`ended_at` 非空、无未结 effect/unknown/host_io 的 terminal run；只释放其未释放 pin，不写 run result/settlement。
- inverse/pin-release 步骤产生一个 ordinal 0 的 `command_reconcile/advance` 后继以便同一 LOGIN 继续 drain；close 无后继。现有协议只允许 reserved key 的 `advance`，host 用 P0 `off` 空闲 schedule 取得首个 P6 槽；这不是新调度器。
- child inverse 只接受 owner-fixture 已 tombstone 的 child，否则 deferred。为满足 `14_contributions.sql` 的 `released_at ⇒ withdrawn_at` CHECK，同次 inverse 写把 `withdrawn_at` 作为释放簿记前置；P5 `withdrawn_ids` 仍不含 child，物理行与 FK 保留。该 schema-forced 语义记入 deviation ledger。
- CDP3-T 覆盖 activation pin（无 run）阻断 provider release、open run/ready/claimed（含过期 lease）/unknown/host_io barrier、ended-run 仅 pin release、32+1 严格 DESC、run/activation 排序与合计 32、service/listener ledger inverse、tombstoned child inverse、历史 pin/prev FK、withdraw 不释放地址而 release 后可复用、空贡献 close、重复刷新不重复释放、deferred 十表零写。listener/cell/reservation/unknown/run/child tombstone 使用 owner fixture，只证明具名账本/阻塞边界。
- CDP3-P7 用真实 P6 证明 deferred 十表零写、屏障清除后同 request 首次提交、byte-identical replay；W1 的非生产 probe 仍只是协议探针。

## 容量与冻结

40=1356、41=1141、42=758，全部 helper 合计 **3255≤5000** 物理行。共享预算函数仍在临时三文件树验证恰好5000通过、5001拒绝。DDL 前缀461≤900，manifest17（loader未改、已核验），十表，仅 `advance` 为 SECURITY DEFINER，public function EXECUTE 0；源码 VIEW/EXTENSION 均0。十二份 frozen SQL SHA-256 与 DP2 matrix 一致，`57e2c1e` frozen diff、v8 相对 HEAD diff、`git diff --check` 均退出0。

## 历史与证明边界

B0 的21条旧命令与 W1 的22条命令、W2 的23条命令均有各自独立实跑记录。B0 当时 helper2227、DDL414、manifest16；W1 当时 helper2283、DDL414、manifest17；W2 当时 40=1259、41=1119、42=557，合计2935，DDL458。W1 deferred/blocked_unknown/unsupported 与非 ready barrier replay 是 disposable 非生产 probe，调用方提交后第二连接取得 G；它们不证明生产 P6。

W3 的生产 `command_barrier` 已接线，`lifecycle_step` 仍返回 idle 且未被 `advance`/`interpret_command` 调用（CDP3-P4 保持）。**W4 已激活实例 dispose、DP4 settlement、DP5 listener/dispatch/intercept/overlay、DP6 scanner/external recovery 与 child cleanup fan-out 尚未实现。** host_io/settlement 继续保守拒绝，不能由终态标签推断外部资源已释放。旧 pin release、run、cell/listener/reservation、cycle/损坏历史使用 owner fixture，只证明具名账本或拒绝边界，不证明生产注册、dispatch、run settlement、外部恢复或自动扫描。child inverse 的既有 CHECK 未修改。

用户授权 DP3 各里程碑独立 commit/push `origin/v24`，覆盖 AGENTS.md 的默认分支指令。本提交仅逐路径暂存 W3 精确文件，保留原有10份 dirty docs及24份无关 untracked 文件。
