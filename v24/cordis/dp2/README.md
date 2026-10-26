# Cordis v2 DP2

DP2 定向扩展 Cordis DP1 协议内核，交付声明式安装、scope 创建后果、最小依赖解析、成功的 P0–P4 激活和无活义务的基本 dispose。产品行为由 `docs/designs/cordis-plugin-system-2026-10-25.md` 规定；本 README 记录实现状态与真实 gate 结果。DP1 的历史验收保留在 `v24/cordis/dp1/README.md` 与 `docs/reviews/cordis-v2-dp1-*`，不被本阶段重写。计划见 `docs/plans/v24-cordis-dp2-lifecycle-plan-2026-10-26.md`。

## 当前状态

**B0–W5 已结项。W3 `cd93134`，W4 `d5fd1bc`，均已推送 `origin/v24`。W5 在 `d5fd1bc` 上串行重跑 21 条门禁，全部退出 0。不得从 DP2 绿色推断 DP3。**

- B0 只做证据与环境核验：固定 worktree/分支/HEAD/upstream、串行实跑既有五条 Cordis DP1 命令、十一条 v24 命令与单列 s9、复核十二个冻结 SQL SHA-256 与冻结 diff，并更新本 README、matrix、ledger 与计划的 B0 证据。B0 未修改生产实现、未修改冻结目录、未新增 SQL 文件或 helper。
- W1 已结项：reserved successor identity、ready child 执行/重放、P0→P1 generation 复验、command closure、typed delta 与真实 applier、terminal receipt guard；生产 spec-valid lifecycle 解释器仍抛 `0A000`，由 disposable probe 驱动 CDP2-K。W1 的五项 bounded Oracle review 发现已全部修复，最终 18 条 gate 全绿。
- W2 已在 `v24/cordis/sql/41_lifecycle.sql` 实现 install declaration、contracts/check、root/existing/child scope admission、owner ledger、unique-root / final-state DAG / committed-view guard 与 resolver。`40_advance.sql` 只保留 3 行 command entry seam。CDP2-I 与全量回归本轮均 `EXIT 0`；one bounded review 完成且六项发现修复，W2 按授权在本轮收尾 commit/push。
- 发布授权（2026-10-26 用户给出）：本计划逐里程碑 commit 并 push `origin/v24`；这是任务特定授权，不改写根与 worktree `AGENTS.md` 的 `origin main` 规则。B0、W1、W2 已据此结项。

## Commands

既有命令（B0/W1 已实跑，退出码见 matrix）：

```bash
uv run python v24/cordis/load.py
uv run python v24/cordis/dp1/setup_db.py --self-check
uv run python v24/cordis/dp1/test_environment.py
uv run python v24/cordis/dp1/test_ddl.py
uv run python v24/cordis/dp1/test_kernel.py
```

v24 回归（十一条，B0/W1 已实跑）：

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

单列扩展命令，不计入十一条（B0/W1 已实跑）：

```bash
uv run python v24/s9/test_g8.py
```

DP2 自有 gate：

```bash
uv run python v24/cordis/dp2/test_kernel.py      # CDP2-K，W1 — 通过
uv run python v24/cordis/dp2/test_install.py     # CDP2-I，W2 — 通过
uv run python v24/cordis/dp2/test_activation.py  # CDP2-A，W3 — 通过
uv run python v24/cordis/dp2/test_boundaries.py  # CDP2-B，W4 — 通过
```

## B0 基线证据（2026-10-26）

- worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，分支 `v24`，B0 HEAD `0590d4703ea1404febbc82d6114fd8d91f385902`，upstream `origin/v24`，`origin/v24...v24` = `0 0`。
- B0 时工作区无已修改/已暂存的跟踪文件；已有 24 个未跟踪文件且全部位于 `docs/` 下，属用户输入，B0 未暂存、未改写。B0 只按路径暂存四个 DP2 工件。
- 环境：Python 3.12.11、psycopg2 2.9.12（dt dec pq3 ext lo64）、PostgreSQL 18.4（180004），仅 Unix socket。
- B0 时预算：`v24/cordis/load.py` 是十五文件 canonical manifest；`40_advance.sql` 340 物理行；DDL 前缀 `10`–`17`/`20`/`30` 合计 350 物理行。
- 冻结证据：十二个 `v24/sql/*.sql` SHA-256 与 DP1 P0 记录逐一相同；`git diff 57e2c1e -- v24/load.py v24/sql v24/s1..s12` 为空（exit 0）。
- B0 关闭提交已推送 `origin/v24`（非 force、未跳过 hook）。

## W1 证据（2026-10-26；已结项）

- 结项提交：`50affb0`（subject：`v24: implement DP2 continuation and typed delta kernel`），已推送 `origin/v24`。
- 范围：reserved successor identity、ready child 执行与持久 replay、P0→P1 generation 复验、command closure 接线、九种 typed delta 的闭合结构/上下文校验与真实 applier、terminal effect/receipt guard、CDP2-K。
- W1 改动：`v24/cordis/sql/40_advance.sql`（340→1196 物理行）、`v24/cordis/sql/30_triggers.sql`（+10 行，194 行）、DP1 的 `test_ddl.py`/`test_kernel.py` 预期，以及新 `v24/cordis/dp2/test_support.py` 与 `test_kernel.py`。W1 当时未新增 SQL 文件，manifest 仍十五文件。
- W1 实跑：CDP1-D 退出 0（113 个零写 DDL probe）；CDP1-K 退出 0（66 个 committed zero-write assertions）；CDP2-K 退出 0（K1–K8/K4b）。最终 18 条命令在同一轮串行复跑，逐条 `EXIT 0`（完整清单见 matrix「W1 actual results」）。
- W1 bounded Oracle review 已完成，五项 actionable findings（event null/type、successor prevalidation、dispose closure 513、dispose timestamp preservation、cross-fiber P1 context）全部修复并复跑。
- W1 结束时预算：`40_advance.sql` 1196/1200（余 4 行）；DDL 前缀 360/900（`30_triggers.sql` 194）；manifest 十五文件。该 4 行余量促成 W2 的 SQL layout 裁决。
- W1 边界：生产 install/resolver（W2 现已实现）、完整 P0–P4（W3）、生产 dispose（W4）在 W1 时未实现；`effects_one_reconcile` 仍限制每 fiber 一个 ready/claimed reconcile；continuation 仍要求与创建者同一 LOGIN。

## W2 证据（2026-10-26 已实现；bounded review 完成；按授权提交收尾）

### 范围与布局

- 新增 `v24/cordis/sql/41_lifecycle.sql`（586 物理行），置于 `40_advance.sql` 与 `50_permissions.sql` 之间；`50_permissions.sql` 的 revoke-all 覆盖全部新 private helper。
- `40_advance.sql` 实测 1119/1200；只保留 3 行 command entry seam（`install_preflight` 调用与 typed error 返回），W2 主体不在 40。
- DDL 前缀 `10`–`17`/`20`/`30` 实测 414/900；`30_triggers.sql` 248 行，新增 committed-view immutable 与 deferred final-state graph guard。
- `v24/cordis/load.py` manifest 十六文件；`v24/cordis/dp1/test_environment.py` 的精确 tuple 同步。十五张表及列/枚举/扩展不变；未修改冻结 `v24/load.py`、`v24/sql/**`、`v24/s1`–`v24/s12`。

### 实现

- 41 内实现 install payload/scope/owner/declaration/contracts/check 校验，`install_admission`（scope 模式、scope lineage、owner ledger、identity/UUID collision、unique root、owner iterator v1、seq budget），`install_delta`，`validate_install_domain`，`install_command_seed`，`resolve`，`install_preflight` 与 `install_references`。
- direct install 只写 scope/install/fiber；ownerful install 追加 child contribution（精确 descriptor/inverse/contract_version）与 episode_progress；不创建 episode、activation pin、host/CAS effect 或 successor。四种 replay boolean 只存储和校验。
- resolver 为只读 STABLE、9 列输出：递归 scope parent、最近 realm override、root default、缺失/closed/cyclic chain 返回 unavailable、NULL/>256 keys 返回零行、intercept/overlay 非空 `0A000`。
- `30_triggers.sql` 的 deferred guard 读取最终行：唯一 ownerless root（含 disposed root）、live child→owner / pin consumer→provider / run owner→provider 边的 cycle、depth 512 / 262144 行上限，SQLSTATE `23514` 且 reason 区分 cycle 与 validation limit；episode committed_view 在 UPDATE 时不可变（`55000`）。

### CDP2-I

`v24/cordis/dp2/test_install.py` 覆盖：

- I1 direct root install 为纯数据、replay 逐字节相同、second ownerless root 拒绝。
- I2 ownerless install 到 existing open scope，仍只有一个 root。
- I3 owner ledger seq/descriptor/inverse/progress、scope/owner/UUID/identity/0A000 负例。
- I4 declaration/contracts/check 四种 replay 组合、malformed shape 零写、256-char key 边界。
- I5 nearest realm override、root default、无跨 realm fallback、provider admission、256-key 与 NULL-key 边界。
- I5b closed ancestor 使整条 resolver chain unavailable（独立 DB）。
- I6 unique root、pin/run DAG cycle、committed-view immutable。
- I6b disposed ownerless root 仍占 unique root 槽（独立 DB）。
- I5c ancestor 的 `dispose_requested_at` 同时关闭 child admission 与 descendant resolution（独立 DB）。
- I6c 19-fiber dense DAG 在去重 reachability 下提交，旧 path cap 回归不再误拒（独立 DB）。
- I7 forged install delta 的 context/ledger/event/successor 校验；install-owner mutation 定位 `install_create`。
- bounded review 修复的 uppercase UUID canonicalization、owner iterator numeric `v`/exact keys、current-generation failure 拒绝，均在 I3 覆盖。

active-owner fixture 仅用于维护 DML，不计入 CDP2-A 激活证据。生产 P0–P4 与 dispose 仍 `0A000`。

### 19 条 gate（串行，真实退出码）

| # | Command | Exit |
|---:|---|---:|
| 1 | `uv run python v24/cordis/load.py` | 0 |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 |
| 8 | `uv run python v24/load.py` | 0 |
| 9 | `uv run python v24/s1/setup_db.py --self-check` | 0 |
| 10 | `uv run python v24/s1/test_ddl.py` | 0 |
| 11 | `uv run python v24/s1/test_g1.py` | 0 |
| 12 | `uv run python v24/s2/test_g3a.py` | 0 |
| 13 | `uv run python v24/s3/test_g2.py` | 0 |
| 14 | `uv run python v24/s4/test_g2b.py` | 0 |
| 15 | `uv run python v24/s5/test_g4.py` | 0 |
| 16 | `uv run python v24/s6/test_g5.py` | 0 |
| 17 | `uv run python v24/s8/test_g7.py` | 0 |
| 18 | `uv run python v24/s7/test_g6.py` | 0 |
| 19 | `uv run python v24/s9/test_g8.py` | 0 |

### 冻结、review 与发布状态

- 十二个 `v24/sql/*.sql` SHA-256 与 DP1 P0 记录逐一相同；`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 … v24/s12` 退出 0 且无输出。
- **Bounded review 已完成（六项修复）**：2026-10-26 的 one bounded Oracle review（两个 lane）确认并修复：① caller UUID 文本大小写与 canonical UUID 比较不一致；② `fiber_lineage_open` 遗漏 `dispose_requested_at`；③ owner iterator 接受 string `v`/额外键；④ owner admission 未拒绝 current-generation `failure`；⑤ DAG guard 的 `UNION ALL` path enumeration 误拒 dense DAG；⑥ forged test mutation 打错 operation。六项均有 CDP2-I 覆盖，post-fix 19 条 gate 全部 `EXIT 0`。
- **发布收尾**：W2 按 2026-10-26 授权以显式路径 `git add`、commit 并 push `origin/v24`，无 force、无 hook skip；提交 hash 记录在最终报告。W3 不得从本绿色推断或提前开始。

## W3 证据（2026-10-26）

- 生产 `interpret_reconcile` 完成 P0 CAS/no-op、P1 冻结、P3 一致性、≤32 P2、P4 totality。成功证据来自真实 API，不是 owner DML。
- `40_advance.sql` 1125/1200；`41_lifecycle.sql` 1038；DDL 前缀 414/900；manifest 十六文件。冻结 diff 退出 0。
- `uv run python v24/cordis/dp2/test_activation.py` 退出 0（A1–A6）。
- 中间失败：首轮 `test_kernel.py` 退出 1（旧的生产 `on`=`0A000` 预期）。修复后退出 0。
- Cordis loader/fixture/environment/CDP1-D/CDP1-K/CDP2-I/CDP2-A 串行退出 0；CDP2-K 修复后退出 0。v24 十一条加 s9 串行退出 0。
- 未覆盖：生产 dispose、`off`/`retry`、drift 转 closing、failure/leave/unload/inverse。settlement 仍 `0A000`。

## W4 证据（2026-10-26）

- 生产 `interpret_dispose` 在证明 install 全部实例无活义务后写墓碑。成功例是真实 direct child install，没有 host/CAS effect。
- 单独阻止：want_on、open episode、未释放 contribution、活 pin、未结束 run、未 disposed child install、六种 kind 的 ready/claimed effect、六种 `host_io` 状态。
- B1：缺依赖、check=false、地址冲突、control drift 仍 `0A000`，当前调用零写。
- `40_advance.sql` 1130/1200；`41_lifecycle.sql` 1097；DDL 414/900；十张表；manifest 十六文件；仅 `advance` DEFINER。
- Cordis 九条与 v24 十二条（含 s9）本轮串行全部退出 0。冻结 diff 退出 0。
- 未覆盖：closing/divert/error、leave/unload、withdraw/release、inverse 执行、settlement。已激活且仍有 open episode 或未释放 contribution 的实例不能 basic dispose。

## W5 closeout（2026-10-26）

在 `d5fd1bc` 上串行重跑，全部退出 0：Cordis loader、DP1 fixture/environment/CDP1-D/CDP1-K、CDP2-K/I/A/B、v24 loader、s1 fixture/DDL/G1、s2–s6、s8、s7、s9。冻结 diff 退出 0。`40_advance.sql` 1130/1200，`41_lifecycle.sql` 1097，DDL 414/900，manifest 16，十张表，仅 `advance` DEFINER。

仍未覆盖：`off`/`retry`；不把 drift 转成 closing，不写 failure，不自动 retry；leave/unload、withdraw/release、inverse；closing/divert/error；settlement 仍 `0A000`；已激活且有 open episode 或未释放 contribution 的实例不能 basic dispose；无 CAS ownership；continuation 限同一 LOGIN；多 entity 事件留 DP5。

## 边界

DP2 不实现：target drift 处理、失败记录/自动 retry；closing/divert/error、leave/unload、withdraw/release、inverse 执行；完整 live 失效传播、drain/barrier、公平扫描与恢复；run/reducer/model/tool/dispatch/listener 执行；`intercept`、overlay 合并与外部制品准备。这些路径保留 `0A000` 或现有 DP1 行为，不提前实现 DP3。
