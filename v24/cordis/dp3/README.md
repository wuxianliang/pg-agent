# Cordis v2 DP3

DP3 从 DP2 内核继续做失效传播与可逆退役。权威规格是 `docs/designs/cordis-plugin-system-2026-10-25.md`，实施计划是 `docs/plans/v24-cordis-dp3-teardown-plan-2026-10-27.md`。各阶段原始结果保留在 DP3 conformance matrix 与 deviation ledger；DP1/DP2 历史验收不在这里改写。

## 当前状态

**B0=`ba4f533`、W1=`103ec596` 已发布。本提交交付 W2 到 `origin/v24`；推送后按用户最新指令暂停，不开始 W3–W5。**

W2 最终门禁于 2026-10-27 在 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`、分支 `v24`、HEAD `103ec596040506e74a7babdc240312885843d9f0` 加 W2 未提交改动上实跑。计划 §4.1 的 21 条旧命令、CDP3-P、CDP3-L 依次单独启动并等待退出，**23 条全部退出 0，总耗时 87.36 秒**。命令、耗时及结果见 `docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md` 的 W2 节。

- transitive live 在 resolve、owner/install admission、activation consistency 与 reconcile 共用 provider 诊断；private `pin_readable` 沿冻结 pin/contribution/provider episode 读取，provider off/closing/withdrawn 不使旧未释放 pin 失读。
- 生产 P0 on/off/retry 实现 CAS、首次 no-op receipt 与精确 replay、ready/claimed I7 coalescing、bigint overflow。旧 NULL/non-NULL fence 不改 input、不追加旧代；过时 NULL-fence 槽结算 no-op 后，后续合法当前代控制可激活。
- reloading control/target drift 走 Divert，不 withdraw。active 失效走 Leave/P5，同次精确 withdraw 可见贡献全集（≤256），不 release pin。P0 只写控制/retire 事实。
- P2 address/contract、P3 check/contract、P4 可归因 totality 失败提交 exact failure-v1 Raise；P1 无 episode 缺依赖仍 `dependency_unresolved`、十表零写，可用原 input 重试。
- typed writer/validator/applier 同步实现；domain validator 独立重算 selector 与 P1 resolver target、完整 P0/closing delta。既存写目标须在 closure，应用后以 VOLATILE fresh SQL 验证。
- CDP3-L 证明精确 after-write `23505/contributions_service_addr` 回滚当前两行批次和 iterator、保留已提交32行 prefix、同 advance 提交一条 Raise；六写入边界故障整笔回滚，其他 unique/FK/CHECK/cancel/timeout 原异常传播。
- DAG/写 closure 512/513、P5 256/257、601 closed generations/600 terminal parents 历史剪枝、failure 七键与单向 guard、独立 validator 伪造负例、抑制 INSERT 后置失败均通过。DP1/DP2 按意图迁移，保留真实 service/child、1/32/33、basic dispose、ACL/claim/replay/锁序路径。

## 容量与冻结

40=1259、41=1119、42=557，全部 helper 合计 **2935≤5000** 物理行。共享预算函数仍在临时三文件树验证恰好5000通过、5001拒绝。DDL 前缀458≤900，manifest17（loader未改、已核验），十表，仅 `advance` 为 SECURITY DEFINER，新 helper 无 public EXECUTE；源码 VIEW/EXTENSION 均0。十二份 frozen SQL SHA-256 与 DP2 matrix 一致，`57e2c1e` frozen diff、v8 相对 HEAD diff、`git diff --check` 均退出0。

## 历史与证明边界

B0 的21条旧命令与 W1 的22条命令均有各自独立实跑记录。B0 当时 helper2227、DDL414、manifest16；W1 当时 helper2283、DDL414、manifest17。W1 deferred/blocked_unknown/unsupported 与非 ready barrier replay 是 disposable 非生产 probe，调用方提交后第二连接取得 G；它们不证明生产 P6。

W2 的生产 `command_barrier` 仍返回 NULL，`lifecycle_step` 仍返回 idle 且未接线。**P6 inverse、pin release、episode close、已激活实例 dispose 尚未实现，W3–W5 暂停。** CDP3-T/D/B 未新增或运行。旧 pin release、run、cell/listener/reservation、cycle/损坏历史使用 owner fixture，只证明具名账本或拒绝边界，不证明生产注册、dispatch、run settlement、外部恢复或自动扫描。child inverse 的既有 CHECK 未修改。

用户授权本 W2 独立 commit/push `origin/v24`，覆盖 AGENTS.md 的默认分支指令。提交仅包含 W2 精确路径，保留原有10份 dirty docs及24份无关 untracked 文件。
