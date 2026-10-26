# Cordis v2 DP2

DP2定向扩展已完成的 Cordis DP1 协议内核，交付声明式安装、scope 创建后果、最小依赖解析、成功的 P0–P4 激活和无活义务的基本 dispose。产品行为由 `docs/designs/cordis-plugin-system-2026-10-25.md` 规定；本 README 记录实现状态与真实 gate 结果。DP1 的历史验收保留在 `v24/cordis/dp1/README.md` 与 `docs/reviews/cordis-v2-dp1-*`，不被本阶段重写。计划见 `docs/plans/v24-cordis-dp2-lifecycle-plan-2026-10-26.md`。

## 当前状态

**B0 已结项：本地验证 + 提交 + 推送 `origin/v24`（B0 关闭提交（subject：`v24: close out Cordis DP2 B0 baseline with gate and frozen evidence`））。W1–W5 尚未实现、未运行，不得从 B0 绿色推断任何 DP2 生命周期行为。**

- B0 只做证据与环境核验：固定 worktree/分支/HEAD/upstream、串行实跑既有五条 Cordis DP1 命令、十一条 v24 命令与单列 s9、复核十二个冻结 SQL SHA-256 与冻结 diff，并更新本 README、matrix、ledger 与计划的 B0 证据。
- B0 未修改任何生产实现、未修改冻结目录（`v24/load.py`、`v24/sql/**`、`v24/s1`–`v24/s12`）、未新增 SQL 文件或 helper，也未触碰 `v24/cordis/sql/**`。
- 生产 `interpret_command` 仍对全部 lifecycle 分支抛 `0A000`，`interpret_settlement` 仍为 `0A000`，`barrier_ready()` 仍为接缝值；DP2 的 typed delta、resolver、check、command closure、后继执行与领域 applier 均不存在。
- CDP2-K/I/A/B 四个 gate 脚本与 `test_support.py` 尚未创建；W2 的 spec-valid active-owner maintenance fixture 也不存在。它们不是 B0 的验收项。
- 发布授权（2026-10-26 用户给出）：本计划逐里程碑 commit 并 push `origin/v24`；这是任务特定授权，不改写根与 worktree `AGENTS.md` 的 `origin main` 规则。B0 已据此提交并推送，里程碑结项；W1–W5 沿用同一目标。

## Commands

既有命令（B0 已实跑，退出码见 matrix）：

```bash
uv run python v24/cordis/load.py
uv run python v24/cordis/dp1/setup_db.py --self-check
uv run python v24/cordis/dp1/test_environment.py
uv run python v24/cordis/dp1/test_ddl.py
uv run python v24/cordis/dp1/test_kernel.py
```

v24 回归（十一条，B0 已实跑）：

```bash
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s2/test_g3a.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s5/test_g4.py
uv run python v24/s6/test_g5.py
uv run python v24/s8/test_g7.py
uv run python v24/s7/test_g6.py
```

单列扩展命令，不计入十一条（B0 已实跑）：

```bash
uv run python v24/s9/test_g8.py
```

DP2 自有 gate（W1–W4 交付时逐条新增，当前**不存在**，不得当作已通过）：

```bash
uv run python v24/cordis/dp2/test_kernel.py      # CDP2-K，W1
uv run python v24/cordis/dp2/test_install.py     # CDP2-I，W2
uv run python v24/cordis/dp2/test_activation.py  # CDP2-A，W3
uv run python v24/cordis/dp2/test_boundaries.py  # CDP2-B，W4
```

## B0 基线证据（2026-10-26）

- worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，分支 `v24`，HEAD `0590d4703ea1404febbc82d6114fd8d91f385902`（`v24: close out Cordis DP1 with final regression evidence`），upstream `origin/v24`，`origin/v24...v24` = `0 0`。
- DP1 交付提交依次为 `5163b23`（loader/fixture）、`e9ccf30`（DDL）、`69efd38`（kernel/ACL）、`0590d47`（closeout）；`57e2c1e` 是冻结 v24 的比较基线，不是 DP2 预期 HEAD。
- 工作区无已修改/已暂存的跟踪文件；B0 前已有 24 个未跟踪文件且全部位于 `docs/` 下，属用户输入，B0 未暂存、未改写。
- 环境：Python 3.12.11、psycopg2 2.9.12（dt dec pq3 ext lo64）、PostgreSQL 18.4（180004），仅 Unix socket。
- 预算：`v24/cordis/load.py` 仍是十五文件 canonical manifest；`v24/cordis/sql/40_advance.sql` 340 物理行（≤1200）；DDL 前缀 `10`–`17`/`20`/`30` 合计 350 物理行（≤900）。
- 冻结证据：十二个 `v24/sql/*.sql` SHA-256 与 DP1 P0 记录逐一相同；`git diff 57e2c1e -- v24/load.py v24/sql v24/s1..s12` 为空（exit 0）。
- 结项：B0 只按路径暂存四个 DP2 工件（本 README、DP2 conformance matrix、DP2 deviation ledger、DP2 plan），未 `git add -A`、未卷入 24 个未跟踪用户文档；该B0 关闭提交（subject：`v24: close out Cordis DP2 B0 baseline with gate and frozen evidence`）已推送 `origin/v24`（非 force、未跳过 hook）。

## 边界

DP2 不实现：target drift 处理、失败记录与自动 retry；closing/divert/error、leave/unload、withdraw/release、inverse 执行；完整 live 失效传播、drain/barrier、公平扫描与恢复；run/reducer/model/tool/dispatch/listener 执行；`intercept`、overlay 合并与外部制品准备。这些路径保留 `0A000` 或现有 DP1 行为，不提前实现 DP3。
