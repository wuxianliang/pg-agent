# S12：D-S7-2 host-only 公平调度（M-F1）

S12 验证 `HostWorker.run_scopes_until_idle()` 的有限、公平合同与 Fake-only 对抗轨迹。生产入口只新增 `v24/host/worker.py` 的同步内存调度；不改 12 个 SQL、HostDB RPC 表、HostJournal 格式或旧单 scope 入口。

## M-F1 执行结果（2026-10-25）

M-F1 是一个完整里程碑，a/b/c 为内部依赖步骤。验证 runner 以 `UV_NO_ENV_FILE=1` 并清除 provider 凭据变量运行；31/31 命令 exit 0。完整命令、`executed_at`、source/tree 摘要、日志 SHA-256 与限制见 [`docs/reviews/v24-d-s7-2-fairness-execution-2026-10-25.md`](../../docs/reviews/v24-d-s7-2-fairness-execution-2026-10-25.md)。

G11 全量及 G11-A…L 单 case 均通过；旧 closeout、G8/G9/G10、Node 和 multilingual smoke 均通过。证据仅使用 Fake transport/handlers 与真实 Unix PostgreSQL fixture；未调用真实 provider。D-S7-2 广义主债务仍开启，O2 的 burst=3 是未测量偏好假设。

## 合同边界

- 固定授权 roster 采用 scope round-robin；默认 roster 由 `host_scopes` 分页枚举，显式 roster 不调用枚举。
- fresh opportunity 是 discovery-originated effect 的一次物理 claim 尝试；host burst=3，第四次 fresh 在 business 可用时选 business。同类按 `(created_at, effect_id)` 循环。
- 每次顶层 fair 调用每 effect 至多一次物理 claim；prepared-ready 与 discovery 共享 guard，claimed-token resume 不产生新 claim。恢复命令、prepared dispatch、reconcile 与 fresh opportunity 分开计数。
- 每 visit 最多一个 prepared dispatch、一次 `recover(16)` 和一个 fresh dispatch，串行且最多一个在飞。`max_rounds` 只限制 visit 次数。
- 启动 ownership 覆盖三类 journal 未决记录。已有 `settlement_committed` 的历史先过滤；roster 内确认 terminal 且没有本地 outcome 的 unfinished 记录写入既有 `settlement_committed` conflict `database_terminal_no_outcome`，不伪造业务成功。off-roster 未核销 debt fail-fast。
- G11 的数值公平断言只适用于 opportunity-dense 窗口；空、blocked、竞争和动态到达保留 visit 轨迹，不删样本套用上界。Fake 脚本耗尽即失败。

## 验证

从仓库根执行：

```bash
uv run python v24/s12/test_g11.py
uv run python v24/s12/test_g11.py --only G11-A
# --only 支持 G11-B … G11-L
```

G11是独立脚本，不依赖pytest，不调用真实provider或网络。每个A…L均含真实HostWorker+HostDB+PostgreSQL夹具路径，外部执行使用有限ScriptTransport/Fake handler；全生命周期拒绝网络入口，允许Unix PostgreSQL。另有104个纯选择状态与3,168个独立参考模型入口场景（最多9次visit），比较选择、RR访问、cursor/streak、机会/冲突计数和独立计算的stop_reason。实际选择/claim/visit与模型枚举摘要持久写入fixture的`v24_fake.journal`，不进产品十表。G9继续验证legacy生命周期；M-F1同时执行G11全量/12个单case和既有全量回归。

## 覆盖矩阵

| Case | 覆盖 |
|---|---|
| G11-A | 旧单scope域缺口、真实多scope claim/execute/settle与RR机会计数 |
| G11-B | 旧恒host优先反例、burst=3、第四fresh business、prepared-ready/claimed-token独立额度与物理guard |
| G11-C | 65 项分页、64 边界、单 visit 预算 |
| G11-D | 完整scan页间插入与非原子快照边界、新scope下次roster |
| G11-E | live orphan 隔离与其他 scope 继续 |
| G11-F | recover(16) 命令/applied 分离 |
| G11-G | deferred 冲突、调用内 guard、下次调用重试 |
| G11-H | 相同输入 cold 选择一致 |
| G11-I | unknown 与 terminal/no-outcome 核销 |
| G11-J | 真实cancel_requested过期→cancel_late；取消封存字段不变且零重发 |
| G11-K | 参数边界与 off-roster ownership |
| G11-L | 真实3 scope负载3/4/50的dense RR前缀公平；独立模型枚举S=1..3、streak/cursor/预算/竞争 |

G11 使用有限 fake，不能证明开放到达下的 starvation-freedom、墙钟等待或 debt 有界、跨崩溃/多主机公平、真实 provider 可用性/延迟/成本/质量，D-S7-2 广义主债务保持开启。
